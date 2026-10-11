"""Adapter/atomic migration checks, with optional PostgreSQL service integration."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import db
from app import migrate_postgres as migration
from app import health_context as health


def test_placeholder_translation_keeps_literals_and_binds_values():
    statement = "SELECT '?', \"?\", $$?$$, $label$?$label$, '100%' WHERE name=? -- ?\nAND id=? /* ? */"
    translated = db.postgres_sql(statement)
    assert translated == "SELECT '?', \"?\", $$?$$, $label$?$label$, '100%%' WHERE name=%s -- ?\nAND id=%s /* ? */"
    connection = MagicMock()
    wrapped = db.PostgresConnection(connection)
    value = "an apostrophe ' and ?; DROP TABLE users"
    wrapped.execute("SELECT * FROM users WHERE username=?", (value,))
    connection.execute.assert_called_once_with("SELECT * FROM users WHERE username=%s", (value,))


def test_rows_support_mapping_and_index_lookup():
    cursor = SimpleNamespace(description=[SimpleNamespace(name="id"), SimpleNamespace(name="version")])
    row = db._row_factory(cursor)(("episode-1", 3))
    assert dict(row) == {"id": "episode-1", "version": 3}
    assert row[0] == row["id"] == "episode-1"
    assert row[-1] == 3
    assert row[:] == ("episode-1", 3)


def test_write_context_locks_once_commits_and_can_be_reused():
    connection = MagicMock()
    wrapped = db.PostgresConnection(connection)
    with wrapped:
        wrapped.execute("BEGIN IMMEDIATE")
        wrapped.execute("UPDATE users SET display_name=? WHERE id=?", ("Alice", "user-1"))
    statements = [call.args[0] for call in connection.execute.call_args_list]
    assert statements == ["BEGIN ISOLATION LEVEL READ COMMITTED", "SELECT pg_advisory_xact_lock(%s)", "UPDATE users SET display_name=%s WHERE id=%s"]
    connection.commit.assert_called_once()
    connection.close.assert_not_called()
    with pytest.raises(ValueError), wrapped:
        raise ValueError("rollback this transaction")
    connection.rollback.assert_called_once()
    assert not wrapped._in_transaction


def test_lock_failure_rolls_back():
    connection = MagicMock()
    connection.execute.side_effect = [MagicMock(), sqlite3.OperationalError("timeout")]
    wrapped = db.PostgresConnection(connection)
    with pytest.raises(sqlite3.OperationalError):
        with wrapped:
            pass
    connection.rollback.assert_called_once()
    assert not wrapped._in_transaction


def test_connect_failure_hides_driver_credentials(monkeypatch):
    fake = SimpleNamespace(Error=RuntimeError, connect=MagicMock(side_effect=RuntimeError("postgresql://name:secret@host/db")))
    monkeypatch.setattr(db, "psycopg", fake)
    with pytest.raises(sqlite3.OperationalError) as error:
        db.connect("postgresql://name:secret@host/db")
    assert "secret" not in str(error.value)
    assert "postgresql://" not in str(error.value)


def test_sqlite_schema_remains_compatible(tmp_path):
    source = tmp_path / "business.sqlite3"
    db.initialize(str(source))
    db.initialize(source)
    connection = db.connect(source)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.fixture
def source_database(tmp_path):
    path = tmp_path / "source.sqlite3"
    db.initialize(path)
    connection = db.connect(path)
    try:
        with connection:
            connection.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", ("u1", "alice", "Alice", "stored-hash", "2026-10-01", "2026-10-01"))
            connection.execute("INSERT INTO sessions VALUES(?,?,?,?)", ("stored-token-digest", "u1", "2026-10-01", "2026-10-20"))
            connection.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?)", ("e1", "u1", 7, "2026-10-02", '{"notes":"中文健康记录"}', "{}", "2026-10-02", "2026-10-03"))
    finally:
        connection.close()
    return path


class MigrationTarget:
    """Use a real transactional SQLite target to exercise data copy/rollback."""

    def __init__(self, *, occupied=False, fail=False, bad_count=False):
        self.connection = sqlite3.connect(":memory:")
        self.occupied, self.fail, self.bad_count = occupied, fail, bad_count
        self.closed, self.committed, self.rolled_back = False, False, False

    def execute(self, statement, parameters=None):
        if "information_schema.tables" in statement:
            return SimpleNamespace(fetchone=lambda: ("existing",) if self.occupied else None)
        if self.fail and statement.startswith("INSERT INTO episodes"):
            raise sqlite3.IntegrityError("simulated import failure")
        if self.bad_count and statement == "SELECT COUNT(*) FROM episodes":
            return SimpleNamespace(fetchone=lambda: (0,))
        return self.connection.execute(statement, parameters or ())

    def __enter__(self):
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.connection.rollback()
            self.rolled_back = True
        else:
            self.connection.commit()
            self.committed = True

    def close(self):
        self.closed = True  # Keep test inspection available until test cleanup.


def test_migration_preserves_hashes_ids_versions_and_source(source_database, monkeypatch):
    target = MigrationTarget()
    before = source_database.read_bytes()
    monkeypatch.setattr(migration, "connect", lambda url: target)
    try:
        assert migration.migrate(source_database, "postgresql://local/empty") == {"users": 1, "sessions": 1, "episodes": 1}
        assert target.connection.execute("SELECT id,password_hash FROM users").fetchone() == ("u1", "stored-hash")
        assert target.connection.execute("SELECT token_digest FROM sessions").fetchone()[0] == "stored-token-digest"
        assert target.connection.execute("SELECT id,version,content_json FROM episodes").fetchone() == ("e1", 7, '{"notes":"中文健康记录"}')
        assert source_database.read_bytes() == before
        assert target.committed and target.closed
    finally:
        target.connection.close()


@pytest.mark.parametrize("options", [{"occupied": True}, {"fail": True}, {"bad_count": True}])
def test_migration_refuses_occupied_target_or_rolls_back_all_rows(source_database, monkeypatch, options):
    target = MigrationTarget(**options)
    monkeypatch.setattr(migration, "connect", lambda url: target)
    try:
        with pytest.raises((ValueError, RuntimeError, sqlite3.IntegrityError)):
            migration.migrate(source_database, "postgresql://local/empty")
        assert target.rolled_back and target.closed
        assert target.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        target.connection.close()


def test_migration_cli_never_outputs_driver_secrets(source_database, monkeypatch, capsys):
    monkeypatch.setenv("ZHIJI_DATABASE_URL", "postgresql://name:top-secret@host/db")
    monkeypatch.setattr(migration, "migrate", MagicMock(side_effect=RuntimeError("password=top-secret")))
    assert migration.main(["--source", str(source_database)]) == 1
    output = capsys.readouterr()
    assert "top-secret" not in output.err + output.out
    assert "源库未修改" in output.err


def add_health_data(source):
    health.initialize_health(source)
    connection = db.connect(source)
    try:
        saved = health.save_profile(connection, "u1", {"version": 0, "birth_year": 1990,
            "chronic_conditions": ["stored-condition"], "family_history": ["stored-family-history"]})
        health.import_observations(connection, "u1", [{"source": "manual", "source_id": "stored-reading",
            "metric": "temperature", "value": 36.6, "unit": "C", "context": "resting", "device_name": "stored-device",
            "measured_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}])
        reading = dict(connection.execute("SELECT * FROM observations").fetchone())
        return saved, reading
    finally:
        connection.close()


def test_migration_preserves_optional_profiles_observations_and_source(source_database, monkeypatch):
    saved, reading = add_health_data(source_database)
    before = source_database.read_bytes()
    target = MigrationTarget()
    target.connection.row_factory = sqlite3.Row
    monkeypatch.setattr(migration, "connect", lambda url: target)
    try:
        counts = migration.migrate(source_database, "postgresql://local/empty")
        assert counts == {"users": 1, "sessions": 1, "episodes": 1, "health_profiles": 1, "observations": 1}
        assert health.get_profile(target, "u1") == saved
        assert dict(target.execute("SELECT * FROM observations").fetchone()) == reading
        assert source_database.read_bytes() == before
        assert target.committed
    finally:
        target.connection.close()


def test_migration_online_backup_includes_committed_wal(source_database, monkeypatch):
    writer = db.connect(source_database)
    target = MigrationTarget()
    monkeypatch.setattr(migration, "connect", lambda url: target)
    try:
        with writer:
            writer.execute("UPDATE episodes SET version=? WHERE id=?", (8, "e1"))
        # Keep the writer open: committed changes may still reside in the WAL.
        assert migration.migrate(source_database, "postgresql://local/empty")["episodes"] == 1
        assert target.connection.execute("SELECT version FROM episodes").fetchone()[0] == 8
        assert writer.execute("SELECT version FROM episodes").fetchone()[0] == 8
    finally:
        writer.close()
        target.connection.close()


@pytest.fixture
def live_postgres():
    url = os.getenv("ZHIJI_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set ZHIJI_TEST_POSTGRES_URL for PostgreSQL service integration")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    schema = "zhiji_test_" + uuid4().hex
    administrator = psycopg.connect(url, autocommit=True)
    administrator.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def fresh_connection(_url=None):
        raw = psycopg.connect(url, autocommit=True, row_factory=db._row_factory)
        raw.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return db.PostgresConnection(raw)
    wrapped = fresh_connection()
    try:
        yield SimpleNamespace(connection=wrapped, connect=fresh_connection, url=url)
    finally:
        wrapped.close()
        administrator.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        administrator.close()


def test_live_postgres_schema_binding_rollback_and_cascade(live_postgres):
    target = live_postgres.connection
    with target:
        db.initialize_postgres(target)
    with target:
        db.initialize_postgres(target)
        target.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", ("u1", "alice", "A?lice", "hash", "2026-10-01", "2026-10-01"))
        target.execute("INSERT INTO sessions VALUES(?,?,?,?)", ("digest", "u1", "2026-10-01", "2026-10-20"))
    row = target.execute("SELECT id,display_name FROM users WHERE username=?", ("alice",)).fetchone()
    assert row[0] == row["id"] == "u1"
    assert row["display_name"] == "A?lice"
    with pytest.raises(ValueError), target:
        target.execute("UPDATE users SET display_name=? WHERE id=?", ("rolled back", "u1"))
        raise ValueError("rollback")
    assert target.execute("SELECT display_name FROM users").fetchone()[0] == "A?lice"
    with target:
        target.execute("DELETE FROM users WHERE id=?", ("u1",))
    assert target.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("include_health", [False, True])
def test_live_postgres_migration_preserves_records_and_rejects_second_copy(live_postgres, source_database, monkeypatch, include_health):
    if include_health:
        saved, reading = add_health_data(source_database)
    monkeypatch.setattr(migration, "connect", live_postgres.connect)
    expected = {"users": 1, "sessions": 1, "episodes": 1}
    if include_health:
        expected |= {"health_profiles": 1, "observations": 1}
    assert migration.migrate(source_database, live_postgres.url) == expected
    target = live_postgres.connection
    assert target.execute("SELECT password_hash FROM users WHERE id=?", ("u1",)).fetchone()[0] == "stored-hash"
    assert target.execute("SELECT id,version,content_json FROM episodes").fetchone() == {"id": "e1", "version": 7, "content_json": '{"notes":"中文健康记录"}'}
    if include_health:
        assert health.get_profile(target, "u1") == saved
        assert dict(target.execute("SELECT * FROM observations").fetchone()) == reading
    with pytest.raises(ValueError, match="必须为空"):
        migration.migrate(source_database, live_postgres.url)
    assert target.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1


def test_live_postgres_http_accounts_records_conflicts_and_password_revocation(live_postgres, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as api

    monkeypatch.setattr(db, "connect", live_postgres.connect)
    monkeypatch.setattr(api, "connect", live_postgres.connect)
    monkeypatch.setattr(health, "connect", live_postgres.connect)
    application = api.create_app(database_path=live_postgres.url)
    headers = {"X-Zhiji-Client": "1"}
    password = "A-private-password-2026"
    with TestClient(application) as first, TestClient(application) as second, TestClient(application) as other:
        registered = first.post("/api/v1/auth/register", headers=headers, json={
            "username": "alice", "password": password, "display_name": "Alice", "consent": True,
        })
        assert registered.status_code == 201, registered.text
        assert second.post("/api/v1/auth/login", headers=headers, json={"username": "alice", "password": password}).status_code == 200
        assert other.post("/api/v1/auth/register", headers=headers, json={
            "username": "bob", "password": password, "display_name": "Bob", "consent": True,
        }).status_code == 201
        health_profile = {"version": 0, "birth_year": 1990, "chronic_conditions": ["ALICE_CHRONIC"], "family_history": ["ALICE_FAMILY"]}
        saved_profile = first.put("/api/v1/health/profile", headers=headers, json=health_profile)
        assert saved_profile.status_code == 200 and saved_profile.json()["version"] == 1
        assert first.put("/api/v1/health/profile", headers=headers, json=health_profile).status_code == 409
        assert other.put("/api/v1/health/profile", headers=headers, json={"version": 0, "chronic_conditions": ["BOB_PRIVATE_CONDITION"]}).status_code == 200
        assert "BOB_PRIVATE" not in first.get("/api/v1/health/profile").text
        reading = {"source": "health_connect", "source_id": "shared-reading-key", "metric": "heart_rate", "value": 80.0,
            "unit": "bpm", "context": "resting", "device_name": "Test device",
            "measured_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
        imported = first.post("/api/v1/health/observations/import", headers=headers, json={"items": [reading]})
        assert imported.status_code == 200 and imported.json() == {"inserted": 1, "duplicates": 0}
        assert first.post("/api/v1/health/observations/import", headers=headers, json={"items": [reading]}).json()["duplicates"] == 1
        assert other.post("/api/v1/health/observations/import", headers=headers, json={"items": [reading | {"value": 81.0}]}).status_code == 200
        alice_observations = first.get("/api/v1/health/observations").json()
        bob_observation = other.get("/api/v1/health/observations").json()["items"][0]
        assert alice_observations["total"] == 1 and alice_observations["items"][0]["value"] == 80
        assert first.get("/api/v1/health/context").json()["region"]["status"] == "disabled"
        episode_payload = {
            "chief_complaint": "咳嗽需要记录", "symptoms": ["咳嗽"], "severity": 2,
            "started_at": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
            "status": "ongoing", "vitals": {"temperature": 37.2}, "medications": [],
            "observation_ids": [alice_observations["items"][0]["id"]],
        }
        assert first.post("/api/v1/episodes", headers=headers, json=episode_payload | {"observation_ids": [bob_observation["id"]]}).status_code == 422
        created = first.post("/api/v1/episodes", headers=headers, json=episode_payload)
        assert created.status_code == 201, created.text
        record = created.json()
        assert record["analysis"]["profile_context"]["chronic_conditions"] == ["ALICE_CHRONIC"]
        assert record["analysis"]["device_context"]["readings"][0]["value"] == 80
        assert "BOB_PRIVATE" not in created.text
        update = {key: record[key] for key in ("chief_complaint", "symptoms", "severity", "started_at", "status", "vitals", "medications", "version", "observation_ids")}
        update["chief_complaint"] = "咳嗽已减轻"
        assert first.put("/api/v1/episodes/" + record["id"], headers=headers, json=update).status_code == 200
        assert second.put("/api/v1/episodes/" + record["id"], headers=headers, json=update).status_code == 409
        verified, resume_login = Event(), Event()
        original_verify = api.verify_password

        def paused_verify(candidate, encoded):
            valid = original_verify(candidate, encoded)
            if candidate == password and not verified.is_set():
                verified.set()
                assert resume_login.wait(10), "Password change did not finish while login was paused"
            return valid

        monkeypatch.setattr(api, "verify_password", paused_verify)

        def stale_login():
            with TestClient(application) as third:
                return third.post("/api/v1/auth/login", headers=headers, json={"username": "alice", "password": password})

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_login = pool.submit(stale_login)
            try:
                assert verified.wait(10), "Login did not reach password verification"
                changed = first.post("/api/v1/account/password", headers=headers, json={"current_password": password, "new_password": "A-new-private-password-2026"})
                assert changed.status_code == 204, changed.text
            finally:
                resume_login.set()
            assert pending_login.result(timeout=10).status_code == 401
        assert second.get("/api/v1/auth/me").status_code == 401
        exported = first.get("/api/v1/export")
        assert exported.json()["episodes"][0]["version"] == 2
        assert exported.json()["health_profile"]["family_history"] == ["ALICE_FAMILY"]
        assert [item["value"] for item in exported.json()["observations"]] == [80]
        assert "BOB_PRIVATE" not in exported.text and bob_observation["id"] not in exported.text
        assert first.delete("/api/v1/episodes/" + record["id"] + "?version=2", headers=headers).status_code == 204
        assert first.get("/api/v1/episodes").json() == []
