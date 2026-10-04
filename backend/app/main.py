"""HTTP API and optional built frontend for desktop browsers and mobile clients."""

from collections.abc import Iterator
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import Headers

from .config import FRONTEND_DIST, Settings
from .db import connect, initialize
from .schemas import AuthResult, Credentials, DeleteAccountInput, EpisodeDetail, EpisodeInput, EpisodeUpdate, RegisterInput, User
from .security import AuthRateLimiter, hash_password, new_session, timestamp, token_digest, verify_password
from .services import analyze_episode, build_patterns

PREFIX = "/api/v1"
COOKIE = "zhiji_session"


class RequestGuard:
    """Enforce body bounds before parsing, same-origin mutations, and safe headers."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        path = scope["path"]

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                csp = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
                if path in {"/docs", "/redoc"}:
                    csp = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; object-src 'none'; frame-ancestors 'none'"
                response_headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy", csp.encode()),
                ])
                if path.startswith("/api/"):
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, secure_send)

        if path.startswith("/api/"):
            origin = headers.get("origin")
            request_origin = f"{scope['scheme']}://{headers.get('host', '')}"
            if origin and origin not in {*self.settings.allowed_origins, request_origin}:
                return await reject(403, "请求来源不受信任")
            if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"} and headers.get("x-zhiji-client") != "1":
                return await reject(403, "缺少客户端校验标记")
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            return await reject(400, "请求长度无效")
        if content_length < 0 or content_length > self.settings.max_body_bytes:
            return await reject(413, "请求内容过大")
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > self.settings.max_body_bytes:
                return await reject(413, "请求内容过大")
            chunks.append(body)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, secure_send)


def user_data(row) -> dict:
    return {key: row[key] for key in ("id", "username", "display_name", "created_at")}


def episode_data(row) -> dict:
    return {
        **json.loads(row["content_json"]),
        **{key: row[key] for key in ("id", "version", "created_at", "updated_at")},
        "analysis": json.loads(row["analysis_json"]),
    }


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def create_app(database_path: Path | str | None = None) -> FastAPI:
    settings = Settings.load(database_path)
    initialize(settings.database_path)
    app = FastAPI(title="知己跨端 API", version="1.0.0")
    app.state.settings = settings
    app.state.auth_limiter = AuthRateLimiter()
    dummy_hash = hash_password("dummy-password-never-valid")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "X-Zhiji-Client"])
    app.add_middleware(RequestGuard, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        # Never reflect request values, passwords, notes or symptoms into error responses.
        errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, exc: sqlite3.OperationalError):
        return JSONResponse(status_code=503, content={"detail": "数据库暂时不可用，请稍后重试"})

    def database() -> Iterator[sqlite3.Connection]:
        connection = connect(settings.database_path)
        try:
            yield connection
        finally:
            connection.close()

    def authenticated(request: Request, db=Depends(database)) -> dict:
        authorization = request.headers.get("authorization")
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise HTTPException(401, "请重新登录", headers={"WWW-Authenticate": "Bearer"})
        else:
            token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 256:
            raise HTTPException(401, "请先登录", headers={"WWW-Authenticate": "Bearer"})
        digest = token_digest(token)
        row = db.execute("""SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
                            WHERE sessions.token_digest=? AND sessions.expires_at>?""", (digest, timestamp())).fetchone()
        if row is None:
            raise HTTPException(401, "登录已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"})
        return {"user": user_data(row), "digest": digest, "password_hash": row["password_hash"]}

    def limit_auth(request: Request, username: str = ""):
        ip = request.client.host if request.client else "unknown"
        if not app.state.auth_limiter.allow(f"ip:{ip}") or (username and not app.state.auth_limiter.allow(f"user:{username}")):
            raise HTTPException(429, "尝试次数过多，请 5 分钟后重试", headers={"Retry-After": "300"})

    def issue_session(db, user: dict, response: Response) -> dict:
        token, digest, expires_at = new_session(settings.session_seconds)
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (timestamp(),))
        db.execute("INSERT INTO sessions(token_digest,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                   (digest, user["id"], timestamp(), expires_at))
        response.set_cookie(COOKIE, token, max_age=settings.session_seconds, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/")
        return {"user": user, "access_token": token, "token_type": "bearer", "expires_at": expires_at}

    def all_episodes(db, user_id: str) -> list[dict]:
        return [episode_data(row) for row in db.execute(
            "SELECT * FROM episodes WHERE user_id=? ORDER BY started_at DESC, created_at DESC, id DESC", (user_id,)
        ).fetchall()]

    def find_episode(db, user_id: str, episode_id: str):
        row = db.execute("SELECT * FROM episodes WHERE id=? AND user_id=?", (episode_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "记录不存在")
        return row

    def analysis_for(db, user_id: str, data: dict, episode_id: str | None = None):
        history = [entry for entry in all_episodes(db, user_id)
                   if entry["id"] != episode_id and entry["started_at"] < data["started_at"]]
        return analyze_episode(data, history)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post(PREFIX + "/auth/register", response_model=AuthResult, status_code=201)
    def register(payload: RegisterInput, request: Request, response: Response, db=Depends(database)):
        limit_auth(request, payload.username)
        now = timestamp()
        user = {"id": str(uuid4()), "username": payload.username, "display_name": payload.display_name, "created_at": now}
        password_hash = hash_password(payload.password.get_secret_value())
        try:
            with db:
                db.execute("INSERT INTO users(id,username,display_name,password_hash,consent_at,created_at) VALUES(?,?,?,?,?,?)",
                           (user["id"], user["username"], user["display_name"], password_hash, now, now))
                result = issue_session(db, user, response)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "该用户名不可用") from None
        return result

    @app.post(PREFIX + "/auth/login", response_model=AuthResult)
    def login(payload: Credentials, request: Request, response: Response, db=Depends(database)):
        limit_auth(request, payload.username)
        row = db.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
        valid = verify_password(payload.password.get_secret_value(), row["password_hash"] if row else dummy_hash)
        if row is None or not valid:
            raise HTTPException(401, "用户名或密码错误")
        with db:
            return issue_session(db, user_data(row), response)

    @app.get(PREFIX + "/auth/me", response_model=User)
    def me(session=Depends(authenticated)):
        return session["user"]

    @app.post(PREFIX + "/auth/logout", status_code=204)
    def logout(response: Response, session=Depends(authenticated), db=Depends(database)):
        with db:
            db.execute("DELETE FROM sessions WHERE token_digest=?", (session["digest"],))
        response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")

    @app.delete(PREFIX + "/account", status_code=204)
    def delete_account(payload: DeleteAccountInput, request: Request, response: Response,
                       session=Depends(authenticated), db=Depends(database)):
        limit_auth(request, session["user"]["username"])
        if not verify_password(payload.password.get_secret_value(), session["password_hash"]):
            raise HTTPException(401, "密码错误")
        with db:
            db.execute("DELETE FROM users WHERE id=?", (session["user"]["id"],))
        response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")

    @app.get(PREFIX + "/export")
    def export(session=Depends(authenticated), db=Depends(database)):
        return {"schema_version": 1, "user": session["user"], "episodes": all_episodes(db, session["user"]["id"]), "exported_at": timestamp()}

    @app.get(PREFIX + "/episodes", response_model=list[EpisodeDetail])
    def list_episodes(session=Depends(authenticated), db=Depends(database)):
        return all_episodes(db, session["user"]["id"])

    @app.post(PREFIX + "/episodes", response_model=EpisodeDetail, status_code=201)
    def create_episode(payload: EpisodeInput, session=Depends(authenticated), db=Depends(database)):
        data, episode_id, now = payload.model_dump(mode="json"), str(uuid4()), timestamp()
        user_id = session["user"]["id"]
        with db:
            db.execute("BEGIN IMMEDIATE")
            analysis = analysis_for(db, user_id, data)
            db.execute("""INSERT INTO episodes(id,user_id,version,started_at,content_json,analysis_json,created_at,updated_at)
                          VALUES(?,?,1,?,?,?,?,?)""", (episode_id, user_id, data["started_at"], json_text(data), json_text(analysis), now, now))
        return episode_data(find_episode(db, user_id, episode_id))

    @app.get(PREFIX + "/episodes/{episode_id}", response_model=EpisodeDetail)
    def get_episode(episode_id: str, session=Depends(authenticated), db=Depends(database)):
        return episode_data(find_episode(db, session["user"]["id"], episode_id))

    @app.put(PREFIX + "/episodes/{episode_id}", response_model=EpisodeDetail)
    def update_episode(episode_id: str, payload: EpisodeUpdate, session=Depends(authenticated), db=Depends(database)):
        data, user_id = payload.model_dump(mode="json", exclude={"version"}), session["user"]["id"]
        with db:
            db.execute("BEGIN IMMEDIATE")
            current = find_episode(db, user_id, episode_id)
            if current["version"] != payload.version:
                raise HTTPException(409, "记录已在另一端修改，请刷新后重试")
            analysis = analysis_for(db, user_id, data, episode_id)
            changed = db.execute("""UPDATE episodes SET version=version+1,started_at=?,content_json=?,analysis_json=?,updated_at=?
                                    WHERE id=? AND user_id=? AND version=?""",
                                 (data["started_at"], json_text(data), json_text(analysis), timestamp(), episode_id, user_id, payload.version))
            if changed.rowcount != 1:
                raise HTTPException(409, "记录已在另一端修改，请刷新后重试")
        return episode_data(find_episode(db, user_id, episode_id))

    @app.delete(PREFIX + "/episodes/{episode_id}", status_code=204)
    def delete_episode(episode_id: str, version: int = Query(ge=1), session=Depends(authenticated), db=Depends(database)):
        user_id = session["user"]["id"]
        with db:
            db.execute("BEGIN IMMEDIATE")
            current = find_episode(db, user_id, episode_id)
            if current["version"] != version:
                raise HTTPException(409, "记录已在另一端修改，请刷新后重试")
            db.execute("DELETE FROM episodes WHERE id=? AND user_id=? AND version=?", (episode_id, user_id, version))
        return Response(status_code=204)

    @app.get(PREFIX + "/overview")
    def overview(session=Depends(authenticated), db=Depends(database)):
        episodes = all_episodes(db, session["user"]["id"])
        return {"episode_count": len(episodes), "ongoing_count": sum(entry["status"] == "ongoing" for entry in episodes),
                "patterns": build_patterns(episodes), "recent_episodes": episodes[:5]}

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        if FRONTEND_DIST.is_dir():
            candidate = (FRONTEND_DIST / path).resolve()
            if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            if path.startswith("assets/"):
                raise HTTPException(404, "资源不存在")
            index = FRONTEND_DIST / "index.html"
            if index.is_file():
                return FileResponse(index)
        return JSONResponse({"message": "知己 API 已启动；请先构建前端", "docs": "/docs"}, status_code=200 if not path else 404)

    return app


app = create_app()
