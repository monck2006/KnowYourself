"""HTTP API and optional built frontend for desktop browsers and mobile clients."""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import Headers

from .config import FRONTEND_DIST, Settings
from .db import INTEGRITY_ERRORS, OPERATIONAL_ERRORS, connect, initialize
from .schemas import (
    AccountPasswordInput, AccountProfileInput, AuthResult, Credentials, DeleteAccountInput,
    EpisodeDetail, EpisodeInput, EpisodeUpdate, RegisterInput, User,
    HealthProfileInput, ObservationImport, IntakeDraft, IntakeTurnRequest,
)
from .security import AuthRateLimiter, hash_password, new_session, timestamp, token_digest, verify_password
from .services import analyze_episode, build_patterns
from .knowledge import get_topic, initialize_knowledge, knowledge_status, search_topics
from .knowledge_drugs import DrugLookupError, search_drugs
from .competition_data import competition_status, search_competition
from .health_context import (HealthError, initialize_health, get_profile, save_profile,
                             import_observations, get_observations, region_summary, get_health_context)
from .health_context import METRICS as health_metrics
from .assessment import build_assessment
from .assessment_knowledge import retrieve_evidence
from .llm import (ExplanationRequest, INTAKE_PROMPT_VERSION, generate_explanation,
                  generate_intake_turn, model_status, prompt_data)
from . import intake as intake_service

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
                    (b"permissions-policy", b"camera=(self), microphone=(self), geolocation=(self), bluetooth=(self)"),
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
    initialize_health(settings.database_path)
    initialize_knowledge(settings.knowledge_database_path)
    app = FastAPI(title="知己跨端 API", version="1.0.0")
    app.state.settings = settings
    app.state.auth_limiter = AuthRateLimiter()
    app.state.explanation_limiter = AuthRateLimiter(limit=1, window_seconds=30)
    # Guided intake runs one request per turn: allow a small burst, bounded per minute.
    app.state.intake_limiter = AuthRateLimiter(limit=20, window_seconds=60)
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

    async def database_error(request: Request, exc: sqlite3.OperationalError):
        return JSONResponse(status_code=503, content={"detail": "数据库暂时不可用，请稍后重试"})

    for error_class in OPERATIONAL_ERRORS:
        app.add_exception_handler(error_class, database_error)

    @app.exception_handler(HealthError)
    async def health_error(request: Request, exc: HealthError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

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

    def analysis_for(db, user_id: str, data: dict, episode_id: str | None = None, *, episodes=None, context=None):
        history = [entry for entry in (episodes if episodes is not None else all_episodes(db, user_id))
                   if entry["id"] != episode_id and entry["started_at"] < data["started_at"]]
        context = dict(context if context is not None else get_health_context(db, user_id))
        start = datetime.combine(date.fromisoformat(data["started_at"]), time.min, tzinfo=timezone(timedelta(hours=8)))
        if data.get("status") == "ended":
            end = datetime.combine(date.fromisoformat(data["ended_at"]) + timedelta(days=1), time.min, tzinfo=start.tzinfo)
            latest = {}
            for metric in health_metrics:
                row = db.execute("SELECT * FROM observations WHERE user_id=? AND metric=? AND measured_at>=? AND measured_at<? ORDER BY measured_at DESC LIMIT 1",
                                 (user_id, metric, (end - timedelta(days=1)).astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())).fetchone()
                if row:
                    latest[metric] = dict(row)
            context["observations"] = {**context["observations"], "latest": latest}
        reference = datetime.now(timezone.utc) if data.get("status") != "ended" else end.astimezone(timezone.utc)
        resting = db.execute("SELECT * FROM observations WHERE user_id=? AND metric='heart_rate' AND context='resting' AND measured_at>=? AND measured_at<? ORDER BY measured_at DESC LIMIT 1",
                             (user_id, max(start.astimezone(timezone.utc), reference - timedelta(hours=24)).isoformat(), reference.isoformat())).fetchone()
        if resting:
            context["observations"] = {**context["observations"], "latest": {**context["observations"]["latest"], "resting_heart_rate": dict(resting)}}
        # The latest-readings page limit must not truncate the pre-illness baseline.
        context["_baseline_observations"] = [dict(row) for row in db.execute(
            "SELECT * FROM observations WHERE user_id=? AND metric='heart_rate' AND context='resting' AND measured_at>=? AND measured_at<?",
            (user_id, (start - timedelta(days=30)).astimezone(timezone.utc).isoformat(), start.astimezone(timezone.utc).isoformat()))]
        linked = list(dict.fromkeys(data.get("observation_ids") or []))
        if linked:
            rows = db.execute("SELECT * FROM observations WHERE user_id=? AND id IN (" + ",".join("?" for _ in linked) + ")", (user_id, *linked)).fetchall()
            if len(rows) != len(linked):
                raise HTTPException(422, "关联的测量记录不存在或不属于当前账号")
            context["observations"] = {**context["observations"], "items": [dict(row) for row in rows], "latest": {}}
        return analyze_episode(data, history, context)

    def refresh_ongoing(db, user_id: str, episodes: list[dict]):
        if any(entry["status"] == "ongoing" for entry in episodes):
            context = get_health_context(db, user_id)
            for entry in episodes:
                if entry["status"] == "ongoing":
                    entry["analysis"] = analysis_for(db, user_id, entry, entry["id"], episodes=episodes, context=context)
        return episodes

    def overview_data(episodes: list[dict]) -> dict:
        return {"episode_count": len(episodes), "ongoing_count": sum(entry["status"] == "ongoing" for entry in episodes),
                "patterns": build_patterns(episodes), "recent_episodes": episodes[:5]}

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
        except INTEGRITY_ERRORS:
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
            db.execute("BEGIN IMMEDIATE")
            # Password verification is deliberately outside the write lock. Its
            # result must still match the current hash before issuing a session.
            current = db.execute("SELECT * FROM users WHERE id=? AND password_hash=?",
                                 (row["id"], row["password_hash"])).fetchone()
            if current is None:
                raise HTTPException(401, "用户名或密码错误")
            return issue_session(db, user_data(current), response)

    @app.get(PREFIX + "/auth/me", response_model=User)
    def me(session=Depends(authenticated)):
        return session["user"]

    @app.post(PREFIX + "/auth/logout", status_code=204)
    def logout(response: Response, session=Depends(authenticated), db=Depends(database)):
        with db:
            db.execute("DELETE FROM sessions WHERE token_digest=?", (session["digest"],))
        response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")

    @app.put(PREFIX + "/account/profile", response_model=User)
    def update_profile(payload: AccountProfileInput, session=Depends(authenticated), db=Depends(database)):
        with db:
            changed = db.execute("UPDATE users SET display_name=? WHERE id=?", (payload.display_name, session["user"]["id"]))
            if changed.rowcount != 1:
                raise HTTPException(401, "登录已失效，请重新登录")
        return {**session["user"], "display_name": payload.display_name}

    @app.post(PREFIX + "/account/password", status_code=204)
    def change_password(payload: AccountPasswordInput, request: Request,
                        session=Depends(authenticated), db=Depends(database)):
        limit_auth(request, session["user"]["username"])
        with db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck under the write lock: a concurrent password change may have
            # revoked this session after authentication ran.
            current = db.execute("""SELECT users.password_hash FROM users JOIN sessions ON sessions.user_id=users.id
                                    WHERE users.id=? AND sessions.token_digest=? AND sessions.expires_at>?""",
                                 (session["user"]["id"], session["digest"], timestamp())).fetchone()
            if current is None:
                raise HTTPException(401, "登录已失效，请重新登录")
            if not verify_password(payload.current_password.get_secret_value(), current["password_hash"]):
                raise HTTPException(401, "当前密码错误")
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_password(payload.new_password.get_secret_value()), session["user"]["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_digest<>?", (session["user"]["id"], session["digest"]))

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
        user_id = session["user"]["id"]
        observations = [dict(row) for row in db.execute("SELECT id,source,source_id,metric,value,unit,measured_at,context,device_name FROM observations WHERE user_id=? ORDER BY measured_at DESC", (user_id,))]
        return {"schema_version": 2, "user": session["user"], "episodes": all_episodes(db, user_id),
                "health_profile": get_profile(db, user_id), "observations": observations, "exported_at": timestamp()}

    @app.get(PREFIX + "/health/profile")
    def health_profile(session=Depends(authenticated), db=Depends(database)):
        return get_profile(db, session["user"]["id"])

    @app.put(PREFIX + "/health/profile")
    def update_health_profile(payload: HealthProfileInput, session=Depends(authenticated), db=Depends(database)):
        return save_profile(db, session["user"]["id"], payload.model_dump(mode="json"))

    @app.get(PREFIX + "/health/observations")
    def observations(limit: int = Query(default=200, ge=1, le=500), days: int = Query(default=30, ge=1, le=365),
                     session=Depends(authenticated), db=Depends(database)):
        return get_observations(db, session["user"]["id"], limit=limit, days=days)

    @app.post(PREFIX + "/health/observations/import")
    def import_readings(payload: ObservationImport, session=Depends(authenticated), db=Depends(database)):
        return import_observations(db, session["user"]["id"], payload.model_dump(mode="json")["items"])

    @app.get(PREFIX + "/health/region")
    def region(session=Depends(authenticated), db=Depends(database)):
        return region_summary(db, session["user"]["id"])

    @app.get(PREFIX + "/health/context")
    def health_context(session=Depends(authenticated), db=Depends(database)):
        return get_health_context(db, session["user"]["id"])

    @app.get(PREFIX + "/episodes", response_model=list[EpisodeDetail])
    def list_episodes(session=Depends(authenticated), db=Depends(database)):
        return refresh_ongoing(db, session["user"]["id"], all_episodes(db, session["user"]["id"]))

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
        user_id = session["user"]["id"]
        entry = episode_data(find_episode(db, user_id, episode_id))
        entry["analysis"] = analysis_for(db, user_id, entry, entry["id"])
        return entry

    @app.get(PREFIX + "/episodes/{episode_id}/analysis")
    def current_analysis(episode_id: str, session=Depends(authenticated), db=Depends(database)):
        entry = episode_data(find_episode(db, session["user"]["id"], episode_id))
        return analysis_for(db, session["user"]["id"], entry, episode_id)

    def assessment_for(db, user_id: str, entry: dict):
        context = get_health_context(db, user_id)
        now = datetime.now(timezone.utc)
        context["_assessment_now"] = now
        trend_day = date.fromisoformat(entry.get("ended_at") or now.astimezone(timezone(timedelta(hours=8))).date().isoformat())
        trend_start = datetime.combine(max(date.fromisoformat(entry["started_at"]), trend_day - timedelta(days=6)), time.min, tzinfo=timezone(timedelta(hours=8)))
        trend_end = min(now, datetime.combine(trend_day + timedelta(days=1), time.min, tzinfo=trend_start.tzinfo))
        context["_assessment_observations"] = [dict(row) for row in db.execute(
            "SELECT * FROM observations WHERE user_id=? AND measured_at>=? AND measured_at<=? ORDER BY measured_at",
            (user_id, trend_start.astimezone(timezone.utc).isoformat(), trend_end.astimezone(timezone.utc).isoformat()))]
        analysis = analysis_for(db, user_id, entry, entry["id"], context=context)
        result = build_assessment(entry, analysis, context, retrieve_evidence(settings.knowledge_database_path, entry))
        result["model"] = model_status(settings)
        result["model_input"] = prompt_data(result)
        return result

    @app.get(PREFIX + "/assistant/status")
    def assistant_status(session=Depends(authenticated)):
        return model_status(settings)

    @app.get(PREFIX + "/episodes/{episode_id}/assessment")
    def episode_assessment(episode_id: str, session=Depends(authenticated), db=Depends(database)):
        user_id = session["user"]["id"]
        return assessment_for(db, user_id, episode_data(find_episode(db, user_id, episode_id)))

    @app.post(PREFIX + "/episodes/{episode_id}/assessment/explanation")
    def explain_assessment(episode_id: str, payload: ExplanationRequest, session=Depends(authenticated), db=Depends(database)):
        user_id = session["user"]["id"]
        entry = episode_data(find_episode(db, user_id, episode_id))
        if entry["version"] != payload.version:
            raise HTTPException(409, "病程已经更新，请重新读取评估后再生成解释")
        assessment = assessment_for(db, user_id, entry)
        status = model_status(settings)
        if status["status"] == "ready" and assessment["triage"]["level"] != "emergency":
            if status["cloud"] and not payload.cloud_consent:
                raise HTTPException(422, "生成前请明确同意将本次必要事实与资料片段发送到已配置的模型服务")
            if not app.state.explanation_limiter.allow(user_id):
                raise HTTPException(429, "请等待 30 秒后再生成，避免重复调用", headers={"Retry-After": "30"})
        explanation = generate_explanation(settings, assessment)
        if find_episode(db, user_id, episode_id)["version"] != payload.version:
            raise HTTPException(409, "生成期间病程发生更新，请重新读取评估")
        return {"assessment": assessment, "explanation": explanation}

    @app.post(PREFIX + "/intake/triage")
    def intake_triage(payload: IntakeDraft, session=Depends(authenticated)):
        # Uses the same rules as saved episodes, including conservative text mentions.
        # No model or unknown-date/severity defaults are involved.
        return analyze_episode(intake_service.sanitize(payload.model_dump(mode="json")), [])

    @app.post(PREFIX + "/intake/assistant")
    def intake_assistant(payload: IntakeTurnRequest, session=Depends(authenticated)):
        # The draft is re-validated server-side on every turn; the model only proposes.
        draft = intake_service.merge(payload.draft.model_dump(mode="json"), {})
        complete = intake_service.is_complete(draft)
        missing = intake_service.missing_fields(draft)
        def draft_triage(value):
            # Do not let model extraction omit a safety mention in the current text.
            risk_input = {**value, "notes": " ".join([value.get("notes", ""), payload.message.strip()])}
            return analyze_episode(risk_input, [])
        response = {"prompt_version": INTAKE_PROMPT_VERSION, "model": settings.llm_model,
                    "draft": draft, "missing_fields": missing, "complete": complete,
                    "reply": "", "question": "", "tool": intake_service.next_tool(draft),
                    "triage": draft_triage(draft)}
        if complete and not payload.message.strip():
            return {**response, "status": "complete", "tool": "next_step",
                    "notice": "记录已可以保存；如需补充可继续说明。"}
        status = model_status(settings)
        if status["status"] != "ready":
            return {**response, "status": "not_configured", "notice": status["notice"]}
        if status["cloud"] and not payload.cloud_consent:
            raise HTTPException(422, "继续前请明确同意将本轮内容发送到已配置的模型服务")
        if payload.turns >= 24:
            raise HTTPException(429, "本次对话轮次已达上限，请先保存或重新开始",
                                headers={"Retry-After": "30"})
        if not app.state.intake_limiter.allow(session["user"]["id"]):
            raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": "60"})
        context = intake_service.time_context(payload.client_time, payload.timezone, payload.timezone_offset_minutes)
        turn = generate_intake_turn(settings, draft, missing, payload.message.strip(), context)
        tool = response["tool"]
        if turn["status"] == "generated":
            draft = intake_service.merge(draft, turn["fields"])
            missing = intake_service.missing_fields(draft)
            complete = intake_service.is_complete(draft)
            # The model chooses the next dialog; unknown or empty tool falls back to rules.
            tool = turn.get("tool") or intake_service.next_tool(draft)
        triage = draft_triage(draft)
        priorities = {"recorded": 0, "attention": 1, "emergency": 2}
        if priorities[triage["level"]] < priorities[response["triage"]["level"]]:
            triage = response["triage"]
        # A danger signal the rules recognized always opens the action box, even if
        # the model proposed a different tool; the model may not hide it.
        if triage["level"] == "emergency":
            tool = "next_step"
        return {**response, "status": turn["status"], "notice": turn["notice"],
                "reply": turn.get("reply", ""), "question": turn.get("question", ""),
                "draft": draft, "missing_fields": missing, "complete": complete,
                "tool": tool, "triage": triage}

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
        episodes = refresh_ongoing(db, session["user"]["id"], all_episodes(db, session["user"]["id"]))
        return overview_data(episodes)

    @app.get(PREFIX + "/workspace")
    def workspace(session=Depends(authenticated), db=Depends(database)):
        episodes = refresh_ongoing(db, session["user"]["id"], all_episodes(db, session["user"]["id"]))
        return {**overview_data(episodes), "episodes": episodes}

    @app.get(PREFIX + "/knowledge/status")
    def official_status(session=Depends(authenticated)):
        return knowledge_status(settings.knowledge_database_path, settings.openfda_enabled)

    @app.get(PREFIX + "/knowledge/topics")
    def official_topics(q: str = Query(default="", max_length=80), page: int = Query(default=1, ge=1, le=10000),
                        page_size: int = Query(default=12, ge=1, le=50), session=Depends(authenticated)):
        try:
            return search_topics(settings.knowledge_database_path, q.strip(), page, page_size)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get(PREFIX + "/knowledge/topics/{topic_id}")
    def official_topic(topic_id: str, session=Depends(authenticated)):
        result = get_topic(settings.knowledge_database_path, topic_id)
        if result is None:
            raise HTTPException(404, "官方资料不存在")
        return result

    @app.get(PREFIX + "/knowledge/drugs")
    def official_drugs(q: str = Query(min_length=1, max_length=80), session=Depends(authenticated)):
        try:
            return search_drugs(q, settings.knowledge_database_path, settings.openfda_api_key, settings.openfda_enabled)
        except DrugLookupError as error:
            raise HTTPException(error.status_code, error.detail) from None

    @app.get(PREFIX + "/knowledge/competition/status")
    def official_competition_status(session=Depends(authenticated)):
        return competition_status(settings.knowledge_database_path)

    @app.get(PREFIX + "/knowledge/competition")
    def official_competition(q: str = Query(default="", max_length=80),
                             dataset: Literal["cmeie", "cmeee"] = "cmeie",
                             split: Literal["train", "dev", "test"] = "train",
                             page: int = Query(default=1, ge=1, le=100000),
                             page_size: int = Query(default=10, ge=1, le=50), session=Depends(authenticated)):
        return search_competition(settings.knowledge_database_path, q, dataset, split, page, page_size)

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
