"""Safety, evidence and bounded monitoring checks for structured follow-ups."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from app.assessment import QUESTION_BANK, build_assessment
from app.schemas import AssessmentQuestionId, EpisodeInput
from app.services import analyze_episode, build_patterns


NOW = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)


def episode(**changes):
    return dict(id="current", version=2, chief_complaint="咳嗽", symptoms=["咳嗽"], severity=2,
                status="ongoing", outcome="ongoing", started_at="2026-10-01", ended_at=None,
                vitals={}, medications=[], notes="", assessment_answers=[]) | changes


def assess(item=None, context=None, knowledge=None):
    item, context = item or episode(), {"_assessment_now": NOW} | (context or {})
    analysis = analyze_episode(item, [], context, now=NOW)
    return build_assessment(item, analysis, context, knowledge or [])


def observation(identifier, value=70, days=0, **changes):
    return dict(id=identifier, source="healthkit", source_id=identifier, metric="heart_rate", value=value,
                unit="bpm", measured_at=(NOW-timedelta(days=days)).isoformat(), context="unknown") | changes


def test_answer_schema_uses_exact_question_bank_and_persists_typed_answers():
    assert set(get_args(AssessmentQuestionId)) == set(QUESTION_BANK)
    data = {key: value for key, value in episode().items() if key not in {"id", "version"}}
    data["assessment_answers"] = [{"question_id": "worsening", "answer": "unknown"}]
    result = EpisodeInput.model_validate(data)
    assert result.model_dump()["assessment_answers"] == data["assessment_answers"]


@pytest.mark.parametrize("answers", [
    [{"question_id": "arbitrary_diagnosis", "answer": "yes"}],
    [{"question_id": "worsening", "answer": "true"}],
    [{"question_id": "worsening", "answer": True}],
    [{"question_id": "worsening", "answer": "no"}] * 2,
    [{"question_id": "worsening", "answer": "no", "extra": "hidden"}],
])
def test_answer_schema_rejects_unknown_duplicate_and_invalid_answers(answers):
    data = {key: value for key, value in episode().items() if key not in {"id", "version"}}
    with pytest.raises(ValidationError):
        EpisodeInput.model_validate(data | {"assessment_answers": answers})


@pytest.mark.parametrize("question", ["breathing_difficulty", "chest_pain", "confusion"])
def test_dangerous_answer_immediately_escalates_despite_mild_severity_and_history(question):
    current = episode(assessment_answers=[{"question_id": question, "answer": "yes"}])
    history = [episode(id="old", started_at="2026-09-01", ended_at="2026-09-02", status="ended", outcome="resolved")]
    result = analyze_episode(current, history, now=NOW)
    assert result["level"] == "emergency"
    assert result["action_plan"][0]["priority"] == "now"
    assert any("补问确认" in reason for reason in result["reasons"])
    assert result["sources"]


@pytest.mark.parametrize("question", ["dehydration", "worsening", "fever_persistent", "medication_reaction"])
def test_actionable_yes_answers_have_same_day_followup(question):
    result = assess(episode(assessment_answers=[{"question_id": question, "answer": "yes"}]))
    assert result["triage"]["level"] == "attention"
    assert result["triage"]["action_plan"][0]["priority"] == "today"
    assert "今天" in result["monitoring"]["next_check_in"]


def test_no_never_clears_explicit_danger_and_conflicting_evidence_is_visible():
    result = assess(episode(symptoms=["胸痛"], assessment_answers=[{"question_id": "chest_pain", "answer": "no"}]))
    assert result["triage"]["level"] == "emergency"
    answer = next(item for item in result["evidence"] if item["id"] == "answer:chest_pain")
    assert answer["state"] == "conflicting"
    assert any("冲突" in line for line in result["limitations"])


def test_ended_label_cannot_hide_current_danger_confirmed_by_followup():
    result = assess(episode(status="ended", ended_at="2026-10-03", outcome="resolved",
                            assessment_answers=[{"question_id": "confusion", "answer": "yes"}]))
    assert result["triage"]["level"] == "emergency"
    assert result["triage"]["action_plan"][0]["priority"] == "now"
    assert "立即" in result["monitoring"]["next_check_in"]


def test_unknown_and_missing_are_not_negative_or_normal():
    result = assess(episode(assessment_answers=[{"question_id": "chest_pain", "answer": "unknown"}]))
    values = {item["id"]: item for item in result["evidence"]}
    assert values["answer:chest_pain"]["state"] == "unknown"
    assert values["answer:breathing_difficulty"]["state"] == "unknown"
    assert values["answer:breathing_difficulty"]["value"] == "未回答"
    assert not any("体征正常" in line and "不能" not in line for line in result["triage"]["reasons"])


def test_question_selection_tracks_context_and_keeps_previously_answered_questions():
    plain = assess(episode(chief_complaint="手指不适", symptoms=["手指不适"]))
    assert "exposure" not in {question["id"] for question in plain["questions"]}
    assert "fever_persistent" not in {question["id"] for question in plain["questions"]}
    result = assess(episode(vitals={"temperature": 38.2}, medications=[{"name": "某药"}],
                            assessment_answers=[{"question_id": "exposure", "answer": "unknown"}]))
    assert len(result["questions"]) == 10
    assert {"fever_persistent", "pregnancy", "immunosuppression", "medication_reaction"} <= {q["id"] for q in result["questions"]}
    assert all(set(question) == {"id", "text", "reason", "priority", "answer", "options"} for question in result["questions"])


def test_explicit_danger_answers_do_not_become_benign_repeated_patterns():
    records = [episode(id=str(i), status="ended", ended_at="2026-10-02", outcome="resolved",
                       assessment_answers=[{"question_id": "confusion", "answer": "yes"}]) for i in range(2)]
    assert build_patterns(records) == []


def test_medication_checks_use_exact_names_and_never_invent_ingredients():
    result = assess(episode(medications=[{"name": "药A"}, {"name": "药A", "response": "worsened"}, {"name": "药a"}],
                            assessment_answers=[{"question_id": "medication_reaction", "answer": "yes"}]))
    checks = result["medication_checks"]
    assert [item["name"] for item in checks if item["status"] == "duplicate"] == ["药A"]
    assert any(item["status"] == "reported_reaction" and item["name"] == "药A" for item in checks)
    assert any(item["status"] == "review" for item in checks)
    assert all(set(item) == {"name", "status", "detail"} for item in checks)
    assert any("不能归因" in item["detail"] for item in checks)


def test_monitoring_keeps_resting_separate_limits_points_and_excludes_other_episodes():
    readings = [observation(f"{day}-{metric}-{context}", 36.5 if metric == "temperature" else 70, day,
                            metric=metric, unit="C" if metric == "temperature" else "bpm", context=context)
                for day in range(10) for metric, context in [("heart_rate", "unknown"), ("heart_rate", "resting"), ("temperature", "unknown")]]
    result = assess(episode(started_at="2026-10-05"), {"observations": {"items": readings}})
    series = result["monitoring"]["metrics"]
    assert sum(len(item["points"]) for item in series) == 14
    assert {item["label"] for item in series if item["metric"] == "heart_rate"} == {"心率（静息）", "心率（活动或场景未知）"}
    assert all(point["at"] >= "2026-10-05" for item in series for point in item["points"])
    assert all(len(item["points"]) <= 7 for item in series)


def test_day_total_revisions_are_not_added_and_invalid_points_are_filtered():
    readings = [observation("steps-old", 100, metric="steps", unit="count", source_id="steps-utc-day-2026-10-11:100:old", measured_at="2026-10-11T02:00:00Z"),
                observation("steps-new", 150, metric="steps", unit="count", source_id="steps-utc-day-2026-10-11:150:new"),
                observation("sleep", 420, metric="sleep_minutes", unit="min"),
                observation("future", 80, measured_at="2026-10-12T00:00:00Z"),
                observation("timezone", 80, measured_at="2026-10-11T00:00:00"),
                observation("wrong-unit", 80, unit="C"), observation("outlier", 300)]
    item = episode()
    analysis = analyze_episode(item, [], now=NOW)
    result = build_assessment(item, analysis, {"_assessment_now": NOW, "observations": {"items": readings}}, [])
    series = {item["metric"]: item for item in result["monitoring"]["metrics"]}
    assert set(series) == {"steps", "sleep_minutes"}
    assert series["steps"]["points"][0]["value"] == 150
    assert "不能用于判断睡眠疾病" in series["sleep_minutes"]["note"]


def test_linked_readings_bound_monitoring_and_manual_vitals_do_not_invent_time():
    result = assess(episode(observation_ids=["linked"], vitals={"temperature": 36.5}),
                    {"observations": {"items": [observation("linked", 70), observation("other", 90)]}})
    assert result["monitoring"]["metrics"][0]["points"][0]["value"] == 70
    assert len(result["monitoring"]["metrics"]) == 1
    assert "measured_at" not in next(item for item in result["evidence"] if item["id"] == "vital:temperature")


def test_ended_window_no_data_and_knowledge_are_truthful_and_inputs_unchanged():
    item = episode(status="ended", ended_at="2026-10-03")
    context = {"_assessment_now": NOW, "observations": {"items": [observation("outside")]}}
    knowledge = [{"id": str(i), "title": "官方主题", "source": "官方来源", "source_url": "https://medlineplus.gov/", "summary": "原文"*1000} for i in range(7)]
    analysis = analyze_episode(item, [], context, now=NOW)
    before = deepcopy((item, analysis, context, knowledge))
    result = build_assessment(item, analysis, context, knowledge)
    assert result["monitoring"]["metrics"] == []
    assert "回顾" in result["monitoring"]["next_check_in"]
    assert len(result["knowledge"]) == 5 and len(result["knowledge"][0]["excerpt"]) == 1200
    assert any("截取" in line for line in result["limitations"])
    assert (item, analysis, context, knowledge) == before
    assert result["triage"] == {key: analysis[key] for key in ("level", "label", "summary", "action_plan", "reasons")}


def test_llm_evidence_contains_course_medication_and_units_without_free_notes():
    result = assess(episode(vitals={"temperature": 37}, medications=[{
        "name": "自报药品", "started_at": "2026-10-02", "response": "unknown", "adherence": "missed", "notes": "private free text"}]),
        {"observations": {"items": [observation("resting", context="resting")]}})
    evidence = {item["id"]: item for item in result["evidence"]}
    assert evidence["course:current"]["value"] == {"duration_days": 11, "status": "ongoing", "outcome": "ongoing"}
    assert evidence["medication:0"]["value"] == {"name": "自报药品", "started_at": "2026-10-02", "response": "unknown", "adherence": "missed"}
    assert "C" in evidence["vital:temperature"]["label"]
    assert "bpm" in evidence["observation:resting"]["label"] and "静息" in evidence["observation:resting"]["label"]
