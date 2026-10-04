"""Integration checks for shared-device storage and account boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


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


def test_openapi_documents_native_contract(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "post" in paths[API + "/auth/login"]
    assert "get" in paths[API + "/episodes"]
    assert "post" in paths[API + "/episodes"]
    assert "put" in paths[API + "/episodes/{episode_id}"]
