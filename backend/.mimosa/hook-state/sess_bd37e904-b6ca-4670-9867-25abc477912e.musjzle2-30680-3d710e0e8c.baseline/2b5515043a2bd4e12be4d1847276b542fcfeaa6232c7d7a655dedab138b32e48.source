"""SQLite connections and versioned schema creation."""

from pathlib import Path
import sqlite3


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path), timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def initialize(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database_path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("数据库版本高于应用支持版本，请勿使用旧版应用打开")
        if version == 0:
            statements = (
                """CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    consent_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""",
                """CREATE TABLE sessions (
                    token_digest TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )""",
                "CREATE INDEX sessions_user_idx ON sessions(user_id)",
                "CREATE INDEX sessions_expiry_idx ON sessions(expires_at)",
                """CREATE TABLE episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL DEFAULT 1,
                    started_at TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
                "CREATE INDEX episodes_user_started_idx ON episodes(user_id, started_at DESC, created_at DESC)",
            )
            for statement in statements:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
