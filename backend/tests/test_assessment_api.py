"""Owned assessment, saved answers, opt-in cloud use and bounded model calls."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app import llm

API = "/api/v1"
HEADERS = {"X-Zhiji-Client": "1"}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHIJI_DATABASE_URL", raising=False)
    monkeypatch.setenv("ZHIJI_DATABASE_PATH", str(tmp_path / "import-only.sqlite3"))
    monkeypatch.setenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(tmp_path / "knowledge.sqlite3"))
    monkeypatch.setenv("ZHIJI_COOKIE_SECURE", "false")
    monkeypatch.setenv("ZHIJI_OPENFDA_ENABLED", "false")
    monkeypatch.setenv("ZHIJI_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("ZHIJI_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ZHIJI_LLM_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(llm, "request_completion", lambda *_: pytest.fail("Unexpected model request"))
    from app.main import create_app
    with ExitStack() as stack:
        def make(enabled=True, app=None):
            monkeypatch.setenv("ZHIJI_LLM_ENABLED", str(enabled).lower())
            if app is None:
                app = create_app(tmp_path / f"business-{len(stack._exit_callbacks)}.sqlite3")
            return stack.enter_context(TestClient(app))
        yield make


def register(client, username="assessmentuser"):
    response = client.post(API + "/auth/register", headers=HEADERS, json={
        "username": username, "display_name": "PRIVATE_NAME", "password": "Synthetic-private-password-2026", "consent": True})
    assert response.status_code == 201, response.text


def episode(**changes):
    value = {"chief_complaint": "咳嗽", "symptoms": ["咳嗽"], "severity": 2,
             "started_at": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
             "status": "ongoing", "notes": "PRIVATE_NOTES", "vitals": {}, "medications": []}
    return {**value, **changes}


def create(client, **changes):
    response = client.post(API + "/episodes", headers=HEADERS, json=episode(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def explain(client, entry, **changes):
    return client.post(API + f"/episodes/{entry['id']}/assessment/explanation", headers=HEADERS,
                       json={"version": entry["version"], **changes})


def test_assessment_requires_authentication_and_episode_ownership(clients):
    owner = clients()
    assert owner.get(API + "/assistant/status").status_code == 401
    assert owner.get(API + "/episodes/unknown/assessment").status_code == 401
    assert owner.post(API + "/episodes/unknown/assessment/explanation", headers=HEADERS,
                      json={"version": 1}).status_code == 401
    register(owner)
    entry = create(owner)
    other = clients(app=owner.app)
    register(other, "otheruser")
    assert other.get(API + f"/episodes/{entry['id']}/assessment").status_code == 404
    assert explain(other, entry, cloud_consent=True).status_code == 404


def test_saved_answers_upgrade_risk_and_stale_versions_conflict(clients):
    client = clients()
    register(client)
    entry = create(client)
    path = API + f"/episodes/{entry['id']}"
    assert client.get(path + "/assessment").json()["triage"]["level"] != "emergency"
    changed = client.put(path, headers=HEADERS, json=episode(version=1,
        assessment_answers=[{"question_id": "breathing_difficulty", "answer": "yes"}]))
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    current = client.get(path + "/assessment").json()
    assert current["triage"]["level"] == "emergency"
    assert current["episode_version"] == 2
    assert explain(client, entry, cloud_consent=True).status_code == 409
    result = explain(client, changed.json())
    assert result.status_code == 200
    assert result.json()["explanation"]["status"] == "skipped"


@pytest.mark.parametrize("value", ["true", 1, "false", None])
def test_cloud_consent_is_strict_boolean(clients, value):
    client = clients()
    register(client)
    response = explain(client, create(client), cloud_consent=value)
    assert response.status_code == 422


def test_not_configured_needs_no_cloud_consent(clients):
    client = clients(enabled=False)
    register(client)
    result = explain(client, create(client))
    assert result.status_code == 200
    assert result.json()["explanation"]["status"] == "not_configured"


def test_ready_cloud_consent_privacy_and_30_second_limit(clients, monkeypatch):
    client = clients()
    register(client)
    entry = create(client)
    captured = []

    def complete(settings, payload):
        captured.append(payload)
        return {"explanations": [{"text": "目前记录了咳嗽。", "evidence_ids": [payload["facts"][0]["id"]],
                                  "knowledge_ids": []}], "uncertainties": [], "consultation_notes": []}

    monkeypatch.setattr(llm, "request_completion", complete)
    assert explain(client, entry).status_code == 422
    assert not captured
    accepted = explain(client, entry, cloud_consent=True)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["explanation"]["status"] == "generated"
    assert "PRIVATE_" not in json.dumps(captured)
    limited = explain(client, entry, cloud_consent=True)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "30"
    assert len(captured) == 1
    # Move only the stored call timestamp; avoid sleeps or changing global clocks.
    for attempts in client.app.state.explanation_limiter._attempts.values():
        attempts[0] -= 31
    assert explain(client, entry, cloud_consent=True).status_code == 200
    assert len(captured) == 2
