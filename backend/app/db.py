"""Small SQLite/PostgreSQL adapter for the application's versioned business data."""

from pathlib import Path
import re
import sqlite3

try:
    import psycopg
except ImportError:  # SQLite remains usable before optional dependencies are installed.
    psycopg = None


INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())
OPERATIONAL_ERRORS = (sqlite3.OperationalError,) + (
    (psycopg.OperationalError, psycopg.InterfaceError) if psycopg else ()
)
SCHEMA_VERSION = 1
# Match SQLite's single writer during account/session rechecks and record updates.
WRITE_LOCK_KEY = 0x5A48494A49
SCHEMA_STATEMENTS = (
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


def is_postgres(database_path: Path | str) -> bool:
    return isinstance(database_path, str) and database_path.startswith(("postgres://", "postgresql://"))


class DatabaseRow(dict):
    """Mapping rows with sqlite.Row's additional numeric lookup."""

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: DatabaseRow(zip(names, values))


def postgres_sql(statement: str) -> str:
    """Translate bound ? parameters, preserving SQL literals and comments.

    SQL statements come from application code, never from user input. PostgreSQL
    percent signs are escaped for psycopg's client parameter binding.
    """
    tokens = re.compile(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/|"
        r"\$\$[\s\S]*?\$\$|\$(?P<tag>[A-Za-z_][A-Za-z_0-9]*)\$[\s\S]*?\$(?P=tag)\$"
    )
    statement = statement.replace("%", "%%")
    translated, previous = [], 0
    for match in tokens.finditer(statement):
        translated.extend((statement[previous:match.start()].replace("?", "%s"), match.group()))
        previous = match.end()
    translated.append(statement[previous:].replace("?", "%s"))
    return "".join(translated)


class PostgresConnection:
    """Expose the subset of sqlite.Connection used by the API.

    Reads outside a context are autocommit, so authentication cannot leave a stale
    transaction before BEGIN IMMEDIATE. Contexts commit/rollback without closing.
    All application write transactions take one advisory lock; PostgreSQL READ
    COMMITTED sees changes committed by the previous writer after waiting.
    """

    def __init__(self, connection):
        self._connection = connection
        self._in_transaction = False

    def _begin(self):
        if self._in_transaction:
            return None
        cursor = self._connection.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
        self._in_transaction = True
        try:
            self._connection.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK_KEY,))
        except Exception:
            self.rollback()
            raise
        return cursor

    def execute(self, statement: str, parameters=None):
        command = statement.strip().rstrip(";").upper()
        if command in {"BEGIN", "BEGIN IMMEDIATE"}:
            return self._begin()
        if command in {"COMMIT", "END"}:
            return self.commit()
        if command == "ROLLBACK":
            return self.rollback()
        if command.startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP ")):
            self._begin()
        if parameters is None:
            return self._connection.execute(statement)
        return self._connection.execute(postgres_sql(statement), parameters)

    def commit(self):
        self._connection.commit()
        self._in_transaction = False

    def rollback(self):
        self._connection.rollback()
        self._in_transaction = False

    def close(self):
        self._connection.close()
        self._in_transaction = False

    def __enter__(self):
        self._begin()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect(database_path: Path | str) -> sqlite3.Connection | PostgresConnection:
    if is_postgres(database_path):
        if psycopg is None:
            raise sqlite3.OperationalError("PostgreSQL 驱动尚未安装，请安装后端依赖")
        try:
            connection = psycopg.connect(
                database_path, autocommit=True, row_factory=_row_factory,
                connect_timeout=15, options="-c lock_timeout=15000 -c statement_timeout=30000",
            )
        except (psycopg.Error, ValueError):
            # Drivers may include connection information in their messages.
            raise sqlite3.OperationalError("PostgreSQL 连接失败，请检查服务和数据库配置") from None
        return PostgresConnection(connection)
    connection = sqlite3.connect(str(database_path), timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def initialize_postgres(connection: PostgresConnection) -> None:
    """Initialize inside the caller's transaction, including the schema marker."""
    connection.execute("""CREATE TABLE IF NOT EXISTS zhiji_schema_version (
        singleton INTEGER PRIMARY KEY CHECK (singleton=1), version INTEGER NOT NULL
    )""")
    row = connection.execute("SELECT version FROM zhiji_schema_version WHERE singleton=1").fetchone()
    version = row[0] if row else 0
    if version > SCHEMA_VERSION:
        raise RuntimeError("数据库版本高于应用支持版本，请勿使用旧版应用打开")
    if version == 0:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute("INSERT INTO zhiji_schema_version(singleton,version) VALUES(1,?)", (SCHEMA_VERSION,))


def initialize(database_path: Path | str) -> None:
    if not is_postgres(database_path):
        database_path = Path(database_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database_path)
    try:
        if is_postgres(database_path):
            with connection:
                initialize_postgres(connection)
            return
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("数据库版本高于应用支持版本，请勿使用旧版应用打开")
        if version == 0:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
