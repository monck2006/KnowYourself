"""Model boundaries with synthetic credentials and no paid/network requests."""

from dataclasses import replace
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from app.config import Settings
from app import llm


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "business.sqlite3", allowed_origins=(),
                    knowledge_database_path=tmp_path / "knowledge.sqlite3", llm_enabled=True,
                    llm_model="deepseek-v4-flash", llm_api_key="synthetic-test-key")


@pytest.fixture
def assessment():
    return {"episode_version": 3, "triage": {"level": "routine", "label": "记录观察", "summary": "需核实变化"},
            "evidence": [{"id": "symptom:0", "kind": "symptom", "label": "症状", "value": "咳嗽", "state": "present"}],
            "knowledge": [{"id": "1543", "title": "Cough", "excerpt": "Original source excerpt"}]}


def output(text="记录显示咳嗽，仍需核实持续时间。"):
    return {"explanations": [{"text": text, "evidence_ids": ["symptom:0"], "knowledge_ids": ["1543"]}],
            "uncertainties": ["持续时间尚不明确"], "consultation_notes": ["向医生说明症状发生时间"]}


@pytest.mark.parametrize("change", [
    {"evidence_ids": ["invented-fact"]}, {"knowledge_ids": ["invented-source"]},
    {"evidence_ids": []}, {"unexpected": "extra"},
])
def test_invalid_references_and_extra_item_fields_are_rejected(assessment, change):
    body = output()
    body["explanations"][0].update(change)
    with pytest.raises(ValueError):
        llm.validate_explanation(body, llm.prompt_data(assessment))
    with pytest.raises(ValueError):
        llm.validate_explanation({**output(), "triage": "routine"}, llm.prompt_data(assessment))


@pytest.mark.parametrize("text", [
    "建议服用药物。", "每次500mg。", "每次5毫克每日三次。",
    "服用阿莫西林，每次五百毫克，每日三次，连续七天。", "无需就医。",
])
def test_prescriptions_and_doses_fail_closed(settings, assessment, monkeypatch, text):
    monkeypatch.setattr(llm, "request_completion", lambda *_: output(text))
    result = llm.generate_explanation(settings, assessment)
    assert result["status"] == "unavailable"
    assert "explanations" not in result
    assert assessment["triage"]["level"] == "routine"


@pytest.mark.parametrize("fault", [TimeoutError("private-provider-key"), URLError("private-provider-key"),
                                   HTTPError("https://example.invalid", 500, "private-provider-key", {}, None)])
def test_transport_errors_keep_local_result_and_do_not_echo_provider(settings, assessment, monkeypatch, fault):
    def fail(*_):
        raise fault

    monkeypatch.setattr(llm, "request_completion", fail)
    result = llm.generate_explanation(settings, assessment)
    assert result["status"] == "unavailable"
    assert "private-provider-key" not in json.dumps(result)


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "ftp://api.deepseek.com",
                                  "https://user:password@api.deepseek.com", "https://api.deepseek.com?token=x",
                                  "https://[invalid"])
def test_invalid_urls_never_reach_transport(settings, assessment, monkeypatch, url):
    def forbidden(*_):
        pytest.fail("Invalid destination must not receive credentials or health data")

    monkeypatch.setattr(llm, "request_completion", forbidden)
    result = llm.generate_explanation(replace(settings, llm_base_url=url), assessment)
    assert result["status"] == "not_configured"


def test_private_fields_and_raw_history_are_excluded(assessment):
    assessment.update(account="PRIVATE_ACCOUNT", display_name="PRIVATE_NAME", region="PRIVATE_LOCATION",
                      notes="PRIVATE_NOTES", history=["PRIVATE_HISTORY"])
    for kind in ("region", "profile", "history", "description"):
        assessment["evidence"].append({"id": kind, "kind": kind, "value": "PRIVATE_" + kind})
    assessment["evidence"][0]["account"] = "PRIVATE_EXTRA"
    assessment["knowledge"][0]["source_url"] = "PRIVATE_URL"
    serialized = json.dumps(llm.prompt_data(assessment))
    assert "PRIVATE_" not in serialized
    assert "symptom:0" in serialized and "1543" in serialized


def test_emergency_skips_transport(settings, assessment, monkeypatch):
    monkeypatch.setattr(llm, "request_completion", lambda *_: pytest.fail("Emergency must bypass model"))
    assessment["triage"]["level"] = "emergency"
    assert llm.generate_explanation(settings, assessment)["status"] == "skipped"


@pytest.mark.parametrize("content", ["not JSON", '```json\n{}\n```', "[]"])
def test_response_requires_json_object(settings, assessment, monkeypatch, content):
    class Opener:
        def open(self, req, timeout):
            return BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}).encode())

    monkeypatch.setattr(llm, "build_opener", lambda *_: Opener())
    assert llm.generate_explanation(settings, assessment)["status"] == "unavailable"


def test_exact_model_json_transport_and_redirect_guard(settings, assessment, monkeypatch):
    calls = []

    class Opener:
        def open(self, req, timeout):
            calls.append((req, timeout))
            assert timeout == 15
            return BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(output())}}]}).encode())

    handlers = []
    monkeypatch.setattr(llm, "build_opener", lambda handler: handlers.append(handler) or Opener())
    assert llm.generate_explanation(settings, assessment)["status"] == "generated"
    req = calls[0][0]
    body = json.loads(req.data)
    assert body["model"] == "deepseek-v4-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert req.get_header("Authorization") == "Bearer synthetic-test-key"
    assert handlers[0].redirect_request(req, None, 302, "redirect", {}, "https://attacker.invalid") is None

    class RedirectOpener:
        def open(self, req, timeout):
            calls.append((req, timeout))
            raise HTTPError(req.full_url, 302, "redirect", {"Location": "https://attacker.invalid"}, None)

    monkeypatch.setattr(llm, "build_opener", lambda *_: RedirectOpener())
    assert llm.generate_explanation(settings, assessment)["status"] == "unavailable"
    assert len(calls) == 2
    assert all(call[0].full_url == "https://api.deepseek.com/chat/completions" for call in calls)
