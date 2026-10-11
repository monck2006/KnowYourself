"""Private CRUD, observation deduplication and minimum-size regional aggregation."""

from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

import pytest

from app import db as database
from app import health_context as health


NOW = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)
REGION = {"province": "浙江省", "city": "杭州市", "district": "西湖区", "label": "untrusted-client-label"}


def user(db, identifier):
    with db:
        db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (identifier, identifier, identifier, "hash", "2026-10-01", "2026-10-01"))


def profile(db, identifier, *, consent=True, region=None):
    return health.save_profile(db, identifier, {"version": health.get_profile(db, identifier)["version"],
        "birth_year": 1990, "chronic_conditions": ["自报慢性情况"], "family_history": ["自报家庭情况"],
        "region": region or REGION, "regional_consent": consent})


def observation(key, value=80, *, days=0, context="resting", measured_at=None):
    return {"source": "manual", "source_id": key, "metric": "heart_rate", "value": value, "unit": "bpm",
            "measured_at": measured_at or (NOW - timedelta(days=days, minutes=1)).isoformat(),
            "context": context, "device_name": "手动记录"}


def episode(db, identifier, *, days=0, symptoms=None, **fields):
    start = (NOW.astimezone(health.BEIJING).date() - timedelta(days=days)).isoformat()
    content = {"symptoms": symptoms if symptoms is not None else ["咳嗽", "咽痛"], **fields}
    with db:
        db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()), identifier, 1, start, json.dumps(content), "{}", start, start))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "_now", lambda: NOW)
    path = tmp_path / "business.sqlite3"
    database.initialize(path)
    health.initialize_health(path)
    health.initialize_health(path)
    connection = database.connect(path)
    user(connection, "alice")
    user(connection, "bob")
    try:
        yield connection
    finally:
        connection.close()


def test_profile_create_update_remove_conditions_version_and_isolation(db):
    assert health.get_profile(db, "alice")["version"] == 0
    saved = profile(db, "alice")
    assert saved["version"] == 1 and saved["birth_year"] == 1990
    assert saved["region"]["label"] == "浙江省 · 杭州市 · 西湖区"
    assert saved["region"]["code"] == "area:浙江省/杭州市/西湖区"
    assert health.get_profile(db, "bob")["chronic_conditions"] == []
    with pytest.raises(health.HealthError) as conflict:
        health.save_profile(db, "alice", {"version": 0})
    assert conflict.value.status_code == 409
    cleared = health.save_profile(db, "alice", {"version": 1, "chronic_conditions": [], "family_history": []})
    assert cleared["version"] == 2 and cleared["chronic_conditions"] == cleared["family_history"] == []
    assert not cleared["regional_consent"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_region_grid_is_coarse_and_server_rebuilds_label():
    result = health.normalize_region({"code": "grid:0302:1201", "label": "forged"})
    assert result["code"] == "grid:302:1201"
    assert result["label"] == "约10公里网格 302:1201"
    for code in ("grid:30.25:120.17", "grid:9999:1", "raw:30:120", "area:arbitrary"):
        with pytest.raises(health.HealthError):
            health.normalize_region({"code": code})


def test_observation_idempotency_content_conflict_batch_rollback_and_account_scope(db):
    item = observation("record-1")
    assert health.import_observations(db, "alice", [item]) == {"inserted": 1, "duplicates": 0}
    assert health.import_observations(db, "alice", [item]) == {"inserted": 0, "duplicates": 1}
    assert health.import_observations(db, "bob", [item]) == {"inserted": 1, "duplicates": 0}
    with pytest.raises(health.HealthError) as conflict:
        health.import_observations(db, "alice", [observation("new-record"), item | {"value": 81}])
    assert conflict.value.status_code == 409
    assert health.get_observations(db, "alice")["total"] == 1
    alice_id = health.get_observations(db, "alice")["items"][0]["id"]
    assert health.get_observations(db, "bob", ids=[alice_id])["items"] == []
    assert health.get_observations(db, "alice", ids=[alice_id], limit=500)["total"] == 1
    assert health.get_observations(db, "alice", ids=[])["items"] == []


def test_observation_timezone_normalization_preserves_idempotency(db):
    first = observation("same-instant", measured_at="2026-10-10T20:00:00Z")
    second = first | {"measured_at": "2026-10-11T04:00:00+08:00"}
    health.import_observations(db, "alice", [first])
    assert health.import_observations(db, "alice", [second])["duplicates"] == 1


def test_baseline_uses_three_daily_resting_medians_excludes_active_old_and_future(db):
    items = [observation("day1-a", 60, days=1), observation("day1-b", 100, days=1),
             observation("day2", 70, days=2), observation("day3", 90, days=3),
             observation("active", 200, context="active"), observation("old", 30, days=31),
             observation("future-clock-skew", 190, measured_at=(NOW + timedelta(minutes=1)).isoformat())]
    health.import_observations(db, "alice", items)
    result = health.get_observations(db, "alice", days=1)
    baseline = result["baseline"]["heart_rate"]
    assert baseline["sample_count"] == 3 and baseline["reading_count"] == 4
    assert baseline["median"] == 80 and baseline["p10"] == 72 and baseline["p90"] == 88
    assert result["latest"]["heart_rate"]["source_id"] == "active"
    assert health.get_observations(db, "bob")["baseline"]["heart_rate"]["median"] is None
    assert all(item["source_id"] != "future-clock-skew" for item in result["items"])


@pytest.mark.parametrize("changes", [{"value": float("nan")}, {"value": True}, {"unit": "wrong"},
    {"measured_at": "2026-10-11T04:00:00"}, {"measured_at": "2026-10-12T04:00:00Z"}])
def test_invalid_observations_never_partially_insert(db, changes):
    with pytest.raises(health.HealthError):
        health.import_observations(db, "alice", [observation("good"), observation("invalid") | changes])
    assert health.get_observations(db, "alice")["total"] == 0


def test_delete_account_cascades_private_health_data(db):
    profile(db, "alice")
    health.import_observations(db, "alice", [observation("first")])
    with db:
        db.execute("DELETE FROM users WHERE id=?", ("alice",))
    assert db.execute("SELECT COUNT(*) FROM health_profiles").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def add_participants(db, count):
    for index in range(count):
        identifier = f"participant-{index}"
        user(db, identifier)
        profile(db, identifier)


def test_region_minimum_size_deduplicates_accounts_and_revokes_immediately(db):
    profile(db, "alice")
    add_participants(db, 5)
    for index in range(4):
        for _ in range(2):
            episode(db, f"participant-{index}")
    insufficient = health.region_summary(db, "alice")
    assert insufficient["status"] == "insufficient" and insufficient["signals"] == []
    episode(db, "participant-4")
    available = health.region_summary(db, "alice")
    assert available["status"] == "available"
    assert available["signals"][0]["people_band"] == "5–9"
    assert available["signals"][0]["trend"] == "unknown"
    assert "participant-" not in json.dumps(available)
    assert "count" not in available["signals"][0]
    profile(db, "participant-4", consent=False)
    assert health.region_summary(db, "alice")["signals"] == []
    profile(db, "alice", consent=False)
    assert health.region_summary(db, "alice")["status"] == "disabled"


def test_region_boundaries_other_regions_and_no_consent_are_excluded(db):
    profile(db, "alice")
    add_participants(db, 4)
    for index in range(4):
        episode(db, f"participant-{index}", days=6)
    profile(db, "bob", consent=False)
    episode(db, "bob")
    user(db, "elsewhere")
    profile(db, "elsewhere", region={"province": "江苏省", "city": "南京市", "district": ""})
    episode(db, "elsewhere")
    episode(db, "alice", days=7)  # Previous window cannot make current reach five.
    episode(db, "alice", days=14)  # Outside both windows.
    assert health.region_summary(db, "alice")["signals"] == []
    episode(db, "alice", days=6)
    assert health.region_summary(db, "alice")["signals"][0]["people_band"] == "5–9"


def test_region_trend_requires_both_windows_minimum_and_explicit_infection_group(db):
    profile(db, "alice")
    add_participants(db, 8)
    for index in range(8):
        episode(db, f"participant-{index}", symptoms=[], disease_category="infectious", infection_group="gastrointestinal")
        if index < 5:
            episode(db, f"participant-{index}", days=8, symptoms=["腹泻", "呕吐"])
    signal = health.region_summary(db, "alice")["signals"][0]
    assert signal["cluster"] == "gastrointestinal" and signal["trend"] == "increased"
    assert signal["level"] == "elevated"
    assert health._clusters({"disease_category": "hereditary", "infection_group": "respiratory", "symptoms": []}) == set()
    assert health._clusters({"symptoms": ["发烧", "流涕"]}) == {"respiratory"}


def test_context_contains_only_requested_accounts_private_data(db):
    profile(db, "bob")
    health.import_observations(db, "bob", [observation("bob-private")])
    context = health.get_health_context(db, "alice")
    assert context["profile"]["version"] == 0
    assert context["observations"]["items"] == []
    assert context["observations"]["limit"] == 500
    assert context["region"]["status"] == "disabled"


def metric_observation(key, metric, value, unit):
    return {"source": "healthkit", "source_id": key, "metric": metric, "value": value, "unit": unit,
            "measured_at": NOW.isoformat(), "context": "unknown", "device_name": "厂商设备"}


def test_new_metrics_import_and_hrv_arms_stay_separate(db):
    imported = health.import_observations(db, "alice", [
        metric_observation("diet", "dietary_energy", 520, "kcal"),
        metric_observation("water", "hydration", 1500, "ml"),
        metric_observation("active", "active_energy", 300, "kcal"),
        metric_observation("basal", "basal_energy", 1500, "kcal"),
        metric_observation("sdnn", "hrv_sdnn", 42, "ms"),
        metric_observation("rmssd", "hrv_rmssd", 38, "ms"),
        metric_observation("vo2", "vo2max", 47.5, "mL/kg/min"),
    ])
    assert imported == {"inserted": 7, "duplicates": 0}
    latest = health.get_observations(db, "alice", limit=50)["latest"]
    # SDNN and RMSSD are distinct series and must not collapse into one metric.
    assert latest["hrv_sdnn"]["value"] == 42
    assert latest["hrv_rmssd"]["value"] == 38
    assert latest["vo2max"]["value"] == 47.5 and latest["dietary_energy"]["value"] == 520


@pytest.mark.parametrize("metric,value,unit", [
    ("hrv_sdnn", 900, "ms"), ("vo2max", 2, "mL/kg/min"), ("hydration", -1, "ml"), ("dietary_energy", 10, "ms"),
])
def test_new_metric_out_of_range_or_wrong_unit_is_rejected(metric, value, unit):
    # Range enforcement lives in the API schema; the service rejects unit mismatches.
    from pydantic import ValidationError
    from app.schemas import ObservationInput
    with pytest.raises(ValidationError):
        ObservationInput(source="healthkit", source_id="bad", metric=metric, value=value, unit=unit,
                         measured_at=NOW.isoformat(), context="unknown", device_name="厂商设备")


def test_exercise_metrics_import_and_keep_run_cycle_separate(db):
    imported = health.import_observations(db, "alice", [
        metric_observation("run", "distance_run", 5120, "m"),
        metric_observation("cycle", "distance_cycle", 20300, "m"),
        metric_observation("session", "exercise_minutes", 45, "min"),
    ])
    assert imported == {"inserted": 3, "duplicates": 0}
    latest = health.get_observations(db, "alice", limit=50)["latest"]
    assert latest["distance_run"]["value"] == 5120
    assert latest["distance_cycle"]["value"] == 20300
    assert latest["exercise_minutes"]["value"] == 45


@pytest.mark.parametrize("metric,value,unit", [
    ("distance_run", 400000, "m"), ("distance_cycle", 600000, "m"), ("exercise_minutes", 2000, "min"),
    ("distance_run", 100, "min"),
])
def test_exercise_metric_out_of_range_or_wrong_unit_is_rejected(metric, value, unit):
    from pydantic import ValidationError
    from app.schemas import ObservationInput
    with pytest.raises(ValidationError):
        ObservationInput(source="health_connect", source_id="bad", metric=metric, value=value, unit=unit,
                         measured_at=NOW.isoformat(), context="unknown", device_name="厂商设备")


def test_postgres_health_schema_crud_optional(monkeypatch):
    url = os.getenv("ZHIJI_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set ZHIJI_TEST_POSTGRES_URL to verify against PostgreSQL")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    monkeypatch.setattr(health, "_now", lambda: NOW)
    schema = "zhiji_health_test_" + uuid4().hex
    administrator = psycopg.connect(url, autocommit=True)
    administrator.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def fresh(_path):
        raw = psycopg.connect(url, autocommit=True, row_factory=database._row_factory)
        raw.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return database.PostgresConnection(raw)

    connection = fresh(url)
    try:
        with connection:
            database.initialize_postgres(connection)
        monkeypatch.setattr(health, "connect", fresh)
        health.initialize_health(url)
        health.initialize_health(url)
        user(connection, "alice")
        assert profile(connection, "alice")["version"] == 1
        item = observation("temperature") | {"metric": "temperature", "value": 36.6, "unit": "C"}
        assert health.import_observations(connection, "alice", [item])["inserted"] == 1
        assert health.import_observations(connection, "alice", [item])["duplicates"] == 1
        assert health.get_observations(connection, "alice")["items"][0]["value"] == 36.6
        assert health.region_summary(connection, "alice")["status"] == "insufficient"
    finally:
        connection.close()
        administrator.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        administrator.close()
