"""Behavior checks for a source-aware personal health workflow, beyond imports."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.services import analyze_episode
from test_api import API, MUTATION, PASSWORD, record, register


NOW = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)


def reading(identifier, value, days=0, **changes):
    item = {"id": identifier, "source": "healthkit", "source_id": identifier,
            "metric": "heart_rate", "value": value, "unit": "bpm",
            "measured_at": (NOW - timedelta(days=days)).isoformat(),
            "context": "resting", "device_name": "Apple Watch"}
    return item | changes


def test_pre_onset_same_source_resting_baseline_and_latest_low_oxygen():
    items = [reading("today", 90), *[reading(str(day), 60, day) for day in (3, 4, 5)],
             reading("different-device", 150, 6, device_name="Other"),
             reading("active", 150, 7, context="active"),
             reading("oxygen", 91, metric="spo2", unit="%", context="unknown")]
    episode = record(started_at="2026-10-10", vitals={"spo2": 99})
    result = analyze_episode(episode, [], {"observations": {"items": items}}, now=NOW)
    assert result["level"] == "emergency"  # A normal manual value cannot hide a new low value.
    assert any("+30 bpm" in text and "3 天" in text for text in result["device_context"]["deviations"])
    assert result["duration_days"] == 2
    assert result["action_plan"][0]["priority"] == "now"


def test_density_limit_does_not_hide_latest_metric_or_baseline():
    current = reading("today", 90)
    baseline = [reading(str(day), 60, day) for day in (3, 4, 5)]
    result = analyze_episode(record(started_at="2026-10-10"), [], {
        "observations": {"items": [], "latest": {"heart_rate": current}},
        "_baseline_observations": baseline,
    }, now=NOW)
    assert len(result["device_context"]["readings"]) == 1
    assert "+30 bpm" in result["device_context"]["deviations"][0]


def test_newer_activity_unknown_heart_rate_does_not_discard_resting_comparison():
    items = [reading("unknown", 120, context="unknown"), reading("resting", 80, measured_at=(NOW-timedelta(hours=1)).isoformat()),
             *[reading(str(day), 60, day) for day in (3, 4, 5)]]
    result = analyze_episode(record(started_at="2026-10-10"), [], {"observations": {"items": items}}, now=NOW)
    assert "+20 bpm" in result["device_context"]["deviations"][0]
    assert {item["id"] for item in result["device_context"]["readings"]} == {"unknown", "resting"}


def test_saved_normal_temperature_cannot_mask_new_fever_reading():
    item = reading("temperature", 39, metric="temperature", unit="C")
    result = analyze_episode(record(started_at="2026-10-10", vitals={"temperature": 37}), [], {"observations": {"items": [item]}}, now=NOW)
    assert any("补充体温变化" in action["title"] for action in result["action_plan"])


def test_unrelated_or_stale_or_active_readings_cannot_create_resting_comparison():
    result = analyze_episode(record(started_at="2026-10-10"), [], {"observations": {
        "items": [reading("stale", 91, 3, metric="spo2", unit="%"), reading("active", 150, context="active")]
    }}, now=NOW)
    assert result["level"] == "recorded"
    assert result["device_context"]["deviations"] == []
    assert all(item["id"] != "stale" for item in result["device_context"]["readings"])


def test_history_duration_and_medication_feedback_have_real_actions():
    episode = record(started_at="2026-10-07", disease_category="hereditary", medications=[{
        "name": "自报药品", "started_at": "2026-10-08", "response": "worsened", "adherence": "missed"}])
    old = [record(id=str(day), status="ended", started_at=f"2026-09-{day:02d}", ended_at=f"2026-09-{day+1:02d}") for day in (1, 5)]
    result = analyze_episode(episode, old, {"profile": {"family_history": ["母亲患病"]}}, now=NOW)
    assert result["duration_days"] == 5
    assert result["history_comparison"]["range_days"] == [2, 2]
    assert result["medication_review"][0]["days"] == 4
    assert result["level"] == "attention"
    titles = {item["title"] for item in result["action_plan"]}
    assert {"这次持续时间超过你的既往记录", "核对用药期间的加重", "记录漏服并核对该药说明", "把家族线索整理成可评估的信息"} <= titles
    assert result["profile_context"]["diagnosis_source"] == "unknown"


def test_region_signal_adds_context_and_never_overrules_emergency():
    episode = record(started_at="2026-10-10", symptoms=["咳嗽", "咽痛", "呼吸困难"])
    result = analyze_episode(episode, [], {"region": {"enabled": True, "status": "available", "signals": [
        {"cluster": "respiratory", "level": "elevated"}]}}, now=NOW)
    assert result["level"] == "emergency"
    assert any("接触与出行史" in item["title"] for item in result["action_plan"])


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(database_path=tmp_path / "health.sqlite3")) as instance:
        register(instance)
        yield instance


def test_profile_observations_feed_current_analysis_and_export_and_cascade(client):
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    created = client.post(API + "/episodes", headers=MUTATION, json=record(started_at=today, vitals={})).json()
    profile = client.put(API + "/health/profile", headers=MUTATION, json={
        "version": 0, "family_history": ["父亲：已确诊遗传病"], "regional_consent": False})
    assert profile.status_code == 200
    item = reading("sync-id", 91, metric="spo2", unit="%", measured_at=datetime.now(timezone.utc).isoformat())
    item.pop("id")
    imported = client.post(API + "/health/observations/import", headers=MUTATION, json={"items": [item]})
    assert imported.json()["inserted"] == 1
    updated = client.get(API + "/workspace").json()["episodes"][0]
    assert updated["id"] == created["id"] and updated["version"] == 1
    assert updated["analysis"]["level"] == "emergency"
    assert updated["analysis"]["profile_context"]["family_history"] == ["父亲：已确诊遗传病"]
    export = client.get(API + "/export").json()
    assert export["schema_version"] == 2 and len(export["observations"]) == 1
    assert client.request("DELETE", API + "/account", headers=MUTATION, json={"password": PASSWORD}).status_code == 204
    from app.db import connect
    db = connect(client.app.state.settings.database_path)
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM health_profiles").fetchone()[0] == 0
    db.close()


@pytest.mark.parametrize("change", [{"value": True}, {"value": 10}, {"unit": "C"}, {"measured_at": "2026-10-01T00:00:00"}])
def test_invalid_observations_are_rejected(client, change):
    item = reading("invalid", 90, metric="spo2", unit="%", measured_at=datetime.now(timezone.utc).isoformat()) | change
    item.pop("id")
    response = client.post(API + "/health/observations/import", headers=MUTATION, json={"items": [item]})
    assert response.status_code == 422


def test_foreign_observation_cannot_be_attached_to_episode(client):
    item = reading("foreign", 60, measured_at=datetime.now(timezone.utc).isoformat())
    item.pop("id")
    client.post(API + "/health/observations/import", headers=MUTATION, json={"items": [item]})
    identifier = client.get(API + "/health/observations").json()["items"][0]["id"]
    client.post(API + "/auth/logout", headers=MUTATION)
    register(client, "bob")
    response = client.post(API + "/episodes", headers=MUTATION, json=record(observation_ids=[identifier]))
    assert response.status_code == 422
    assert client.get(API + "/episodes").json() == []
