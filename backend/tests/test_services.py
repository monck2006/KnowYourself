from copy import deepcopy

from app.services import analyze_episode, build_patterns


def episode(**changes):
    item = dict(id="current", chief_complaint="咳嗽", symptoms=["咳嗽"],
                severity=2, status="ongoing", started_at="2026-08-01",
                ended_at=None, outcome="ongoing", vitals={}, medications=[], notes="")
    item.update(changes)
    return item


def history():
    return [episode(id=f"history-{day}", status="ended", outcome="resolved",
                    started_at=f"2026-07-{day:02d}", ended_at=f"2026-07-{day+1:02d}")
            for day in [1, 10, 20]]


def test_similarity_never_means_safe_or_drug_effective():
    result = analyze_episode(episode(medications=[{"name": "某药"}]), history())
    assert result["matched_count"] == 3
    assert result["level"] == "recorded"
    assert "不能证明本次安全" in "".join(result["reasons"])
    assert "不代表疗效判断" in "".join(result["reasons"])


def test_danger_in_free_text_cannot_be_hidden_by_history():
    result = analyze_episode(episode(chief_complaint="胸口疼，喘不上气"), history())
    assert result["level"] == "emergency"
    assert result["sources"]


def test_negative_phrase_is_not_claimed_as_positive_symptom():
    result = analyze_episode(episode(chief_complaint="没有胸痛"), [])
    assert any("不能可靠识别否定" in line for line in result["reasons"])
    assert not any("症状记录包含" in line for line in result["reasons"])


def test_missing_vitals_do_not_claim_normal():
    result = analyze_episode(episode(), history())
    assert any("不能据此判断体征正常" in line for line in result["reasons"])


def test_one_measurement_is_not_fever_duration():
    result = analyze_episode(episode(vitals={"temperature": 39.8}), history())
    assert any("单次读数不能说明" in line for line in result["reasons"])


def test_own_record_and_future_records_are_not_history():
    current = episode(status="ended", ended_at="2026-08-03")
    future = episode(id="future", status="ended", started_at="2026-08-04", ended_at="2026-08-06")
    assert analyze_episode(current, [current, future])["matched_count"] == 0


def test_low_oxygen_overrides_matching_symptoms():
    result = analyze_episode(episode(vitals={"spo2": 92}), history())
    assert result["level"] == "emergency"
    assert any("并不适用于所有人" in line for line in result["reasons"])


def test_repeated_patterns_are_symptoms_not_diagnoses():
    records = history()
    snapshot = deepcopy(records)
    assert build_patterns(records) == [{"symptoms": ["咳嗽"], "occurrences": 3, "last_seen": "2026-07-20"}]
    assert records == snapshot


def test_ongoing_worsening_danger_records_not_used_for_patterns():
    records = [episode(id=str(i), symptoms=["胸痛"], status="ended", outcome="resolved", ended_at="2026-08-02") for i in range(3)]
    assert build_patterns(records) == []
    assert build_patterns([episode(), episode(id="2")]) == []
    assert build_patterns([episode(status="ended", outcome="worsened") for _ in range(3)]) == []
