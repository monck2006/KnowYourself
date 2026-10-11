"""Conversation-guided intake: server-side sanitization, completion, model bounds."""

from contextlib import ExitStack
from datetime import datetime
import json
import secrets

from fastapi.testclient import TestClient
import pytest

from app import intake, llm

API = "/api/v1"
HEADERS = {"X-Zhiji-Client": "1"}
# Synthetic, non-secret values generated at runtime; nothing here is a real credential.
PASSWORD = "pw-" + secrets.token_urlsafe(12)
TEST_KEY = secrets.token_hex(16)


# --- pure server-side logic (no HTTP) --------------------------------------

def test_sanitize_drops_values_outside_schema_bounds():
    clean = intake.sanitize({
        "chief_complaint": "  咳嗽  ", "symptoms": ["发热", " 发热 ", "", "咳嗽"],
        "severity": 9, "started_at": "2030-01-01", "status": "ended", "ended_at": "2020-01-01",
        "disease_category": "infectious", "infection_group": "respiratory",
        "diagnosis_source": "clinician", "vitals": {"temperature": 99, "spo2": 97, "heart_rate": 60.5},
    })
    assert clean["chief_complaint"] == "咳嗽"
    assert clean["symptoms"] == ["发热", "咳嗽"]
    assert clean["severity"] is None
    assert clean["started_at"] == ""          # a future date is rejected
    assert clean["ended_at"] == ""             # ended cleared: no valid start
    assert clean["infection_group"] == "respiratory"
    assert clean["diagnosis_source"] == "unknown"   # no diagnosis name
    assert clean["vitals"] == {"spo2": 97}     # temperature out of range; HR kept as int


def test_merge_ignores_empty_proposals_and_unknown_fields():
    merged = intake.merge({"symptoms": ["咳嗽"], "severity": 2},
                          {"symptoms": [], "severity": 4, "triage": "emergency", "file": "/etc/passwd"})
    assert merged["symptoms"] == ["咳嗽"]      # empty list does not clear
    assert merged["severity"] == 4
    assert "triage" not in merged and "file" not in merged


def test_completion_never_fabricates_unknown_date_or_severity():
    assert intake.is_complete(intake.sanitize({"chief_complaint": "头痛"})) is False
    clean = intake.sanitize({"chief_complaint": "头痛", "symptoms": ["头痛"]})
    assert intake.is_complete(clean) is False
    assert intake.missing_fields(clean) == ["started_at", "severity"]
    with pytest.raises(ValueError):
        intake.build_episode_input(clean)
    complete = intake.merge(clean, {"severity": 3, "started_at": "2020-01-01"})
    built = intake.build_episode_input(complete)
    assert built["severity"] == 3 and built["started_at"] == "2020-01-01"
    assert built["ended_at"] is None and built["observation_ids"] == []


def test_relative_time_context_uses_utterance_local_day():
    context = intake.time_context(datetime.fromisoformat("2026-10-10T16:30:00+00:00"), "Asia/Shanghai", 480)
    assert context["today"] == "2026-10-11"
    assert context["yesterday"] == "2026-10-10"
    payload = llm.intake_prompt_data({"started_at": "2026-10-09"}, [], "昨晚开始", context)
    assert payload["known_fields"]["started_at"] == "2026-10-09"
    assert payload["time_context"] == context


@pytest.mark.parametrize("text", ["建议服用阿莫西林，每次500mg。", "可以确诊为流感。", "无需就医。",
                                  "参见 https://example.com"])
def test_intake_validator_refuses_prescriptions_and_links(text):
    with pytest.raises(ValueError):
        llm.validate_intake_turn({"reply": text, "question": "", "fields": {}})


def test_intake_validator_strips_unknown_fields_and_allows_reported_medicine():
    result = llm.validate_intake_turn({"reply": "我已记下你在服用氨溴索。", "question": "还有别的吗？",
                                       "fields": {"symptoms": ["咳嗽"], "triage": "emergency"}})
    assert result["fields"] == {"symptoms": ["咳嗽"]}
    assert result["question"] == "还有别的吗？"


def test_intake_validator_accepts_known_tools_and_drops_unknown():
    assert llm.validate_intake_turn({"tool": "severity", "reply": "好", "fields": {}})["tool"] == "severity"
    assert llm.validate_intake_turn({"tool": "next_step", "reply": "好", "fields": {}})["tool"] == "next_step"
    assert llm.validate_intake_turn({"tool": "impact", "reply": "好", "fields": {}})["tool"] == "impact"
    assert llm.validate_intake_turn({"tool": "delete_files", "reply": "好", "fields": {}})["tool"] == ""
    assert llm.validate_intake_turn({"reply": "好", "fields": {}})["tool"] == ""


def test_rule_fallback_tool_follows_missing_then_next_step():
    assert intake.next_tool(intake.sanitize({})) == "chief_complaint"
    assert intake.next_tool(intake.sanitize({"chief_complaint": "头痛"})) == "symptoms"
    assert intake.next_tool(intake.sanitize({"chief_complaint": "头痛", "symptoms": ["头痛"]})) == "started_at"
    complete = intake.sanitize({"chief_complaint": "头痛", "symptoms": ["头痛"], "severity": 2, "started_at": "2026-10-10"})
    assert intake.next_tool(complete) == "next_step"


# --- endpoint behaviour ----------------------------------------------------

@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHIJI_DATABASE_URL", raising=False)
    monkeypatch.setenv("ZHIJI_DATABASE_PATH", str(tmp_path / "intake-business.sqlite3"))
    monkeypatch.setenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(tmp_path / "knowledge.sqlite3"))
    monkeypatch.setenv("ZHIJI_COOKIE_SECURE", "false")
    monkeypatch.setenv("ZHIJI_OPENFDA_ENABLED", "false")
    monkeypatch.setenv("ZHIJI_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("ZHIJI_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ZHIJI_LLM_API_KEY", TEST_KEY)
    from app.main import create_app
    with ExitStack() as stack:
        def make(enabled=True):
            monkeypatch.setenv("ZHIJI_LLM_ENABLED", str(enabled).lower())
            app = create_app(tmp_path / f"business-{len(stack._exit_callbacks)}.sqlite3")
            return stack.enter_context(TestClient(app))
        yield make


def register(client):
    response = client.post(API + "/auth/register", headers=HEADERS, json={
        "username": "intakeuser", "display_name": "PRIVATE_NAME",
        "password": PASSWORD, "consent": True})
    assert response.status_code == 201, response.text


def turn(client, **body):
    return client.post(API + "/intake/assistant", headers=HEADERS,
                       json={"draft": {}, "message": "", "turns": 0, "cloud_consent": False, **body})


def test_unconfigured_returns_draft_and_never_calls_model(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: pytest.fail("no model call"))
    with clients(enabled=False) as client:
        register(client)
        response = turn(client, draft={"chief_complaint": "咳嗽"}, message="我咳嗽")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "not_configured"
        assert payload["draft"]["chief_complaint"] == "咳嗽"
        assert payload["complete"] is False


def test_generated_turn_updates_draft_and_creates_episode(clients, monkeypatch):
    def fake(*_a, **_k):
        return {"reply": "已记录", "question": "多久了？",
                "fields": {"symptoms": ["咳嗽", "发热"], "severity": 3, "started_at": "2026-10-09"}}
    monkeypatch.setattr(llm, "request_completion", fake)
    with clients() as client:
        register(client)
        payload = turn(client, draft={"chief_complaint": "咳嗽"}, message="两天了", cloud_consent=True).json()
        assert payload["status"] == "generated"
        assert payload["complete"] is True
        assert payload["draft"]["symptoms"] == ["咳嗽", "发热"]
        assert payload["question"] == "多久了？"
        draft = payload["draft"]
        created = client.post(API + "/episodes", headers=HEADERS, json=intake.build_episode_input(draft))
        assert created.status_code == 201, created.text
        assert created.json()["analysis"]["level"] in {"emergency", "attention", "recorded"}


def test_complete_record_without_message_skips_model(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: pytest.fail("no model call"))
    with clients() as client:
        register(client)
        draft = intake.sanitize({"chief_complaint": "头痛", "symptoms": ["头痛"], "severity": 2,
                                 "started_at": "2026-10-10"})
        payload = turn(client, draft=draft, message="").json()
        assert payload["status"] == "complete" and payload["complete"] is True


def test_draft_triage_handles_danger_before_required_answers(clients):
    with clients(enabled=False) as client:
        register(client)
        response = client.post(API + "/intake/triage", headers=HEADERS,
                               json={"symptoms": ["呼吸困难"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["level"] == "emergency"
        assert result["duration_days"] is None
        assert result["action_plan"][0]["priority"] == "now"
        payload = turn(client, message="现在胸痛").json()
        assert payload["triage"]["level"] == "emergency"
        assert payload["draft"]["severity"] is None
        assert payload["draft"]["started_at"] == ""


def test_model_cannot_downgrade_existing_danger(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: {
        "reply": "记下了", "fields": {"symptoms": ["咳嗽"], "severity": 1}})
    with clients() as client:
        register(client)
        payload = turn(client, draft={"symptoms": ["胸痛"], "severity": 5},
                       message="继续", cloud_consent=True).json()
        assert payload["triage"]["level"] == "emergency"


def test_model_chosen_tool_is_passed_through(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: {
        "tool": "started_at", "reply": "好", "question": "从什么时候开始的？",
        "fields": {"chief_complaint": "咳嗽", "symptoms": ["咳嗽"], "severity": 2}})
    with clients() as client:
        register(client)
        payload = turn(client, message="我有点咳嗽", cloud_consent=True).json()
        assert payload["status"] == "generated"
        assert payload["tool"] == "started_at"


def test_emergency_forces_next_step_even_if_model_asked_a_question(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: {
        "tool": "severity", "reply": "好", "question": "多难受？", "fields": {}})
    with clients() as client:
        register(client)
        payload = turn(client, draft={"symptoms": ["胸痛"]}, message="胸口疼", cloud_consent=True).json()
        assert payload["triage"]["level"] == "emergency"
        assert payload["tool"] == "next_step"


def test_unconfigured_tool_falls_back_to_rules(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: pytest.fail("no model call"))
    with clients(enabled=False) as client:
        register(client)
        payload = turn(client, message="我咳嗽").json()
        assert payload["status"] == "not_configured"
        assert payload["tool"] == "chief_complaint"


def test_client_timestamp_requires_timezone(clients):
    with clients(enabled=False) as client:
        register(client)
        assert turn(client, client_time="2026-10-11T10:00:00").status_code == 422


def test_cloud_requires_explicit_consent(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: pytest.fail("no model call"))
    with clients() as client:
        register(client)
        response = turn(client, message="我咳嗽", cloud_consent=False)
        assert response.status_code == 422


@pytest.mark.parametrize("bad", [
    {"reply": "建议每次500mg。", "question": "", "fields": {}},
    {"reply": "好的", "question": "确诊为流感了吗？", "fields": {}},
])
def test_forbidden_model_output_fails_closed(clients, monkeypatch, bad):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: bad)
    with clients() as client:
        register(client)
        payload = turn(client, message="我不舒服", cloud_consent=True).json()
        assert payload["status"] == "unavailable"
        assert payload["draft"]["chief_complaint"] == ""


def test_turn_limit_is_enforced(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: {"reply": "好的", "question": "还有吗？", "fields": {}})
    with clients() as client:
        register(client)
        response = turn(client, message="还有", turns=24, cloud_consent=True)
        assert response.status_code == 429


def test_rate_limit_after_burst(clients, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *a, **k: {"reply": "好的", "question": "还有吗？", "fields": {}})
    with clients() as client:
        register(client)
        codes = [client.post(API + "/intake/assistant", headers=HEADERS, json={
            "draft": {}, "message": "还有", "turns": 0, "cloud_consent": True}).status_code for _ in range(21)]
        assert codes[-1] == 429 and all(code == 200 for code in codes[:20])


def test_provider_errors_are_not_echoed(clients, monkeypatch):
    from urllib.error import URLError

    def fail(*_a, **_k):
        raise URLError("private-provider-key")

    monkeypatch.setattr(llm, "request_completion", fail)
    with clients() as client:
        register(client)
        response = turn(client, draft={"chief_complaint": "咳嗽"}, message="我咳嗽", cloud_consent=True)
        assert response.status_code == 200
        assert response.json()["status"] == "unavailable"
        assert "private-provider-key" not in json.dumps(response.json())
