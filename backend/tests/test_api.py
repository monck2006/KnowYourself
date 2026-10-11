"""Integration checks for shared-device storage and account boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import AuthRateLimiter, token_digest, verify_password


API = "/api/v1"
MUTATION = {"X-Zhiji-Client": "1"}
PASSWORD = "A-private-password-2026"


@pytest.fixture
def database_path(tmp_path):
    return tmp_path / "test.sqlite3"


@pytest.fixture
def client(database_path):
    with TestClient(create_app(database_path=database_path)) as instance:
        yield instance


def register(client, username="alice"):
    response = client.post(API + "/auth/register", headers=MUTATION, json={
        "username": username, "password": PASSWORD,
        "display_name": username, "consent": True,
    })
    assert response.status_code == 201, response.text
    return response


def record(**changes):
    data = {
        "chief_complaint": "咳嗽需要记录", "symptoms": ["咳嗽"],
        "severity": 2, "started_at": "2026-07-01", "status": "ongoing",
        "vitals": {"temperature": 37.2}, "medications": [],
    }
    data.update(changes)
    return data


def create_record(client, **changes):
    response = client.post(API + "/episodes", headers=MUTATION, json=record(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_auth_cookie_bearer_hashing_and_revocation(client, database_path):
    assert client.get(API + "/episodes").status_code == 401
    registered = register(client)
    token = registered.json()["access_token"]
    cookie = registered.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "expires=" in cookie or "max-age=" in cookie
    assert client.get(API + "/auth/me").status_code == 200
    with sqlite3.connect(database_path) as connection:
        stored_password = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        stored_token = connection.execute("SELECT token_digest FROM sessions").fetchone()[0]
    assert stored_password != PASSWORD and PASSWORD not in stored_password
    assert stored_token != token and token not in stored_token
    with TestClient(create_app(database_path=database_path)) as native:
        authorization = {"Authorization": "Bearer " + token}
        assert native.get(API + "/auth/me", headers=authorization).status_code == 200
        assert client.post(API + "/auth/logout", headers=MUTATION).status_code in (200, 204)
        assert native.get(API + "/auth/me", headers=authorization).status_code == 401
    assert client.get(API + "/auth/me").status_code == 401


def test_two_clients_and_restart_share_persistent_records(client, database_path):
    register(client)
    with TestClient(create_app(database_path=database_path)) as second:
        response = second.post(API + "/auth/login", headers=MUTATION,
                               json={"username": "alice", "password": PASSWORD})
        assert response.status_code == 200
        created = create_record(client)
        assert second.get(API + "/episodes").json()[0]["id"] == created["id"]
        assert second.get(API + "/episodes/" + created["id"]).json()["version"] == 1
    with TestClient(create_app(database_path=database_path)) as restarted:
        restarted.post(API + "/auth/login", headers=MUTATION,
                       json={"username": "alice", "password": PASSWORD})
        assert restarted.get(API + "/episodes").json()[0]["id"] == created["id"]


def test_account_isolation_and_export(client, database_path):
    register(client)
    own = create_record(client, chief_complaint="ALICE_PRIVATE_RECORD")
    with TestClient(create_app(database_path=database_path)) as other:
        register(other, "bob")
        create_record(other, chief_complaint="BOB_PRIVATE_RECORD")
        path = API + "/episodes/" + own["id"]
        assert other.get(path).status_code == 404
        assert other.put(path, headers=MUTATION, json=record(version=1)).status_code == 404
        assert other.delete(path + "?version=1", headers=MUTATION).status_code == 404
        assert "ALICE_PRIVATE_RECORD" not in other.get(API + "/episodes").text
        exported = other.get(API + "/export")
        assert exported.status_code == 200
        assert "BOB_PRIVATE_RECORD" in exported.text
        assert "ALICE_PRIVATE_RECORD" not in exported.text
        assert "password_hash" not in exported.text and "access_token" not in exported.text


def test_version_conflicts_and_delete(client):
    register(client)
    created = create_record(client)
    path = API + "/episodes/" + created["id"]
    updated = client.put(path, headers=MUTATION, json=record(version=1, severity=3))
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert client.put(path, headers=MUTATION, json=record(version=1)).status_code == 409
    assert client.delete(path + "?version=1", headers=MUTATION).status_code == 409
    assert client.get(path).json()["severity"] == 3
    assert client.delete(path + "?version=2", headers=MUTATION).status_code == 204
    assert client.get(path).status_code == 404


def test_simultaneous_updates_allow_only_one_writer(client, database_path):
    auth = register(client).json()
    created = create_record(client)
    app = create_app(database_path=database_path)

    def update(severity):
        with TestClient(app) as device:
            return device.put(API + "/episodes/" + created["id"],
                              headers={**MUTATION, "Authorization": "Bearer " + auth["access_token"]},
                              json=record(version=1, severity=severity)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(update, [3, 4]))
    assert sorted(statuses) == [200, 409]
    assert client.get(API + "/episodes/" + created["id"]).json()["version"] == 2


@pytest.mark.parametrize("changes", [
    {"severity": 6}, {"severity": True}, {"symptoms": [42]},
    {"vitals": {"temperature": "37.5"}}, {"vitals": {"spo2": 101}},
    {"started_at": "not-a-date"}, {"started_at": "2099-01-01"},
    {"status": "ended"}, {"status": "ended", "ended_at": "2026-06-30"},
    {"chief_complaint": "   "}, {"unexpected": "PRIVATE_INPUT_MARKER"},
])
def test_invalid_records_fail_without_saving_or_echoing_input(client, changes):
    register(client)
    response = client.post(API + "/episodes", headers=MUTATION, json=record(**changes))
    assert response.status_code == 422, response.text
    assert "PRIVATE_INPUT_MARKER" not in response.text
    assert client.get(API + "/episodes").json() == []


def test_mutation_header_origin_and_sensitive_cache_controls(client):
    register(client)
    assert client.post(API + "/episodes", json=record()).status_code == 403
    blocked = client.post(API + "/episodes", headers={**MUTATION, "Origin": "https://untrusted.example"},
                          json=record())
    assert blocked.status_code == 403
    accepted = client.post(API + "/episodes", headers={**MUTATION, "Origin": "http://testserver"},
                           json=record())
    assert accepted.status_code == 201
    response = client.get(API + "/episodes")
    assert "no-store" in response.headers.get("cache-control", "")
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_expired_session_rejected(client, database_path):
    auth = register(client).json()
    with sqlite3.connect(database_path) as connection:
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        connection.execute("UPDATE sessions SET expires_at = ?", (expired,))
    assert client.get(API + "/auth/me").status_code == 401
    assert client.get(API + "/episodes", headers={"Authorization": "Bearer " + auth["access_token"]}).status_code == 401


def test_account_deletion_removes_data_and_all_sessions(client, database_path):
    auth = register(client).json()
    create_record(client)
    wrong = client.request("DELETE", API + "/account", headers=MUTATION,
                           json={"password": "incorrect-password"})
    assert wrong.status_code in (400, 401, 403)
    assert client.get(API + "/episodes").status_code == 200
    deleted = client.request("DELETE", API + "/account", headers=MUTATION, json={"password": PASSWORD})
    assert deleted.status_code == 204
    assert client.get(API + "/auth/me", headers={"Authorization": "Bearer " + auth["access_token"]}).status_code == 401
    with sqlite3.connect(database_path) as connection:
        for table in ("users", "episodes", "sessions"):
            assert connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_profile_update_is_authenticated_persisted_and_account_scoped(client, database_path):
    path = API + "/account/profile"
    assert client.put(path, headers=MUTATION, json={"display_name": "新昵称"}).status_code == 401
    registered = register(client).json()["user"]
    with TestClient(create_app(database_path=database_path)) as other:
        register(other, "bob")
        response = client.put(path, headers=MUTATION, json={"display_name": "  新昵称  "})
        assert response.status_code == 200
        assert response.json() == {**registered, "display_name": "新昵称"}
        assert other.get(API + "/auth/me").json()["display_name"] == "bob"
    assert client.get(API + "/auth/me").json()["display_name"] == "新昵称"
    assert client.get(API + "/export").json()["user"]["display_name"] == "新昵称"


@pytest.mark.parametrize("payload", [
    {"display_name": ""}, {"display_name": "   "}, {"display_name": "名" * 41},
    {"display_name": "新昵称", "username": "PRIVATE_INPUT_MARKER"},
])
def test_profile_validation_keeps_existing_name(client, payload):
    register(client)
    response = client.put(API + "/account/profile", headers=MUTATION, json=payload)
    assert response.status_code == 422
    assert "PRIVATE_INPUT_MARKER" not in response.text
    assert client.get(API + "/auth/me").json()["display_name"] == "alice"


def test_password_change_keeps_current_session_revokes_others_and_preserves_other_accounts(client, database_path):
    new_password = "A-new-private-password-2026"
    path = API + "/account/password"
    payload = {"current_password": PASSWORD, "new_password": new_password}
    assert client.post(path, headers=MUTATION, json=payload).status_code == 401
    auth = register(client).json()
    with TestClient(create_app(database_path=database_path)) as second, TestClient(create_app(database_path=database_path)) as other:
        second_auth = second.post(API + "/auth/login", headers=MUTATION,
                                  json={"username": "alice", "password": PASSWORD}).json()
        register(other, "bob")
        response = client.post(path, headers=MUTATION, json=payload)
        assert response.status_code == 204 and not response.content
        assert client.get(API + "/auth/me").status_code == 200
        assert client.get(API + "/auth/me", headers={"Authorization": "Bearer " + auth["access_token"]}).status_code == 200
        assert second.get(API + "/auth/me").status_code == 401
        assert second.get(API + "/auth/me", headers={"Authorization": "Bearer " + second_auth["access_token"]}).status_code == 401
        assert other.get(API + "/auth/me").status_code == 200
        with sqlite3.connect(database_path) as connection:
            stored = connection.execute("SELECT password_hash FROM users WHERE username='alice'").fetchone()[0]
            sessions = connection.execute("SELECT token_digest FROM sessions WHERE user_id=?", (auth["user"]["id"],)).fetchall()
        assert stored != new_password and new_password not in stored
        assert verify_password(new_password, stored)
        assert not verify_password(PASSWORD, stored)
        assert sessions == [(token_digest(auth["access_token"]),)]
        assert second.post(API + "/auth/login", headers=MUTATION,
                           json={"username": "alice", "password": PASSWORD}).status_code == 401
        assert second.post(API + "/auth/login", headers=MUTATION,
                           json={"username": "alice", "password": new_password}).status_code == 200


def test_password_change_prevents_inflight_old_password_login_from_creating_session(client, database_path, monkeypatch):
    from app import main

    auth = register(client).json()
    new_password = "A-new-private-password-2026"
    verified, resume_login = Event(), Event()
    verify = main.verify_password

    def paused_verify(password, encoded):
        result = verify(password, encoded)
        if password == PASSWORD and not verified.is_set():
            verified.set()
            assert resume_login.wait(timeout=10), "Password change did not finish while login was paused"
        return result

    monkeypatch.setattr(main, "verify_password", paused_verify)

    def login_with_old_password():
        with TestClient(client.app) as other:
            return other.post(API + "/auth/login", headers=MUTATION,
                              json={"username": "alice", "password": PASSWORD})

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending_login = pool.submit(login_with_old_password)
        try:
            assert verified.wait(timeout=10), "Concurrent login did not reach password verification"
            changed = client.post(API + "/account/password", headers=MUTATION,
                                  json={"current_password": PASSWORD, "new_password": new_password})
            assert changed.status_code == 204
        finally:
            resume_login.set()
        assert pending_login.result(timeout=10).status_code == 401

    assert client.get(API + "/auth/me").status_code == 200
    with sqlite3.connect(database_path) as connection:
        sessions = connection.execute("SELECT token_digest FROM sessions WHERE user_id=?", (auth["user"]["id"],)).fetchall()
    assert sessions == [(token_digest(auth["access_token"]),)]
    assert client.post(API + "/auth/login", headers=MUTATION,
                       json={"username": "alice", "password": new_password}).status_code == 200


@pytest.mark.parametrize("payload", [
    {"current_password": "pw-leak", "new_password": "valid-new-password"},
    {"current_password": PASSWORD, "new_password": "pw-leak"},
    {"current_password": PASSWORD, "new_password": "x" * 129},
    {"current_password": PASSWORD, "new_password": "valid-new-password", "extra": "PRIVATE_INPUT_MARKER"},
])
def test_password_validation_does_not_echo_or_change_credentials(client, database_path, payload):
    register(client)
    response = client.post(API + "/account/password", headers=MUTATION, json=payload)
    assert response.status_code == 422
    assert payload["current_password"] not in response.text and payload["new_password"] not in response.text
    assert "PRIVATE_INPUT_MARKER" not in response.text
    with sqlite3.connect(database_path) as connection:
        stored = connection.execute("SELECT password_hash FROM users").fetchone()[0]
    assert verify_password(PASSWORD, stored)


def test_wrong_current_password_is_rate_limited_without_revoking_sessions(client, database_path):
    auth = register(client).json()
    client.app.state.auth_limiter = AuthRateLimiter(limit=1)
    path = API + "/account/password"
    wrong_password = "incorrect-private-password"
    new_password = "different-private-password"
    wrong = client.post(path, headers=MUTATION, json={"current_password": wrong_password, "new_password": new_password})
    assert wrong.status_code == 401
    assert wrong_password not in wrong.text and new_password not in wrong.text
    limited = client.post(path, headers=MUTATION, json={"current_password": PASSWORD, "new_password": new_password})
    assert limited.status_code == 429 and limited.headers["retry-after"] == "300"
    assert client.get(API + "/auth/me").status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert verify_password(PASSWORD, connection.execute("SELECT password_hash FROM users").fetchone()[0])
        assert connection.execute("SELECT token_digest FROM sessions").fetchall() == [(token_digest(auth["access_token"]),)]


def test_workspace_reuses_one_episode_query_and_matches_compatible_endpoints(client, database_path, monkeypatch):
    assert client.get(API + "/workspace").status_code == 401
    register(client)
    empty = client.get(API + "/workspace").json()
    assert empty == {**client.get(API + "/overview").json(), "episodes": []}
    for day in range(1, 7):
        create_record(client, started_at=f"2026-07-{day:02d}")
    with TestClient(create_app(database_path=database_path)) as other:
        register(other, "bob")
        create_record(other, chief_complaint="BOB_PRIVATE_RECORD")
    expected = {**client.get(API + "/overview").json(), "episodes": client.get(API + "/episodes").json()}
    queries = []
    from app import main
    connect = main.connect

    def traced_connect(path):
        connection = connect(path)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(main, "connect", traced_connect)
    response = client.get(API + "/workspace")
    assert response.status_code == 200
    assert response.json() == expected
    assert len(response.json()["recent_episodes"]) == 5
    assert response.json()["episode_count"] == 6
    assert "BOB_PRIVATE_RECORD" not in response.text
    episode_reads = [query for query in queries if query.startswith("SELECT * FROM episodes")]
    assert len(episode_reads) == 1


def test_openapi_documents_native_contract(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "post" in paths[API + "/auth/login"]
    assert "get" in paths[API + "/episodes"]
    assert "post" in paths[API + "/episodes"]
    assert "put" in paths[API + "/episodes/{episode_id}"]
    assert "put" in paths[API + "/account/profile"]
    assert "post" in paths[API + "/account/password"]
    assert "get" in paths[API + "/workspace"]
