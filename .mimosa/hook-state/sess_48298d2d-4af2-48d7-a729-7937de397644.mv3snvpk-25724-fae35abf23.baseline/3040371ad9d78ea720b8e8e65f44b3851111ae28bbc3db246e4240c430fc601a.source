"""Copy an online SQLite backup into an empty PostgreSQL database, atomically.

Usage: python -m app.migrate_postgres --source data/zhiji.sqlite3
The target is read only from ZHIJI_DATABASE_URL to avoid credentials in argv.
"""

import argparse
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from .db import SCHEMA_VERSION, connect, initialize_postgres, is_postgres
from .health_context import DDL as HEALTH_DDL


TABLE_COLUMNS = {
    "users": ("id", "username", "display_name", "password_hash", "consent_at", "created_at"),
    "sessions": ("token_digest", "user_id", "created_at", "expires_at"),
    "episodes": ("id", "user_id", "version", "started_at", "content_json", "analysis_json", "created_at", "updated_at"),
}
HEALTH_TABLE_COLUMNS = {
    "health_profiles": ("user_id", "version", "content_json", "updated_at"),
    "observations": ("id", "user_id", "source", "source_id", "metric", "value", "unit", "measured_at", "context", "device_name"),
}


def migrate(source: Path | str, target_url: str) -> dict[str, int]:
    """Never modify the source; reject existing target tables and rollback on error."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError("SQLite 源文件不存在")
    if not is_postgres(target_url):
        raise ValueError("ZHIJI_DATABASE_URL 必须是 PostgreSQL URL")
    with TemporaryDirectory(prefix="zhiji-migration-") as directory:
        snapshot = sqlite3.connect(str(Path(directory) / "snapshot.sqlite3"))
        try:
            original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=15)
            try:
                original.backup(snapshot)
            finally:
                original.close()
            if snapshot.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("SQLite 源数据库版本不受支持")
            if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("SQLite 源数据库完整性检查未通过")
            if snapshot.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("SQLite 源数据库关联完整性检查未通过")
            source_tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            optional = {table: columns for table, columns in HEALTH_TABLE_COLUMNS.items() if table in source_tables}
            target = connect(target_url)
            try:
                with target:
                    existing = target.execute("""SELECT table_name FROM information_schema.tables
                        WHERE table_schema NOT IN ('pg_catalog','information_schema')
                        AND table_schema NOT LIKE 'pg_toast%' AND table_type='BASE TABLE'""").fetchone()
                    if existing is not None:
                        raise ValueError("目标 PostgreSQL 数据库必须为空；请勿提前启动应用初始化")
                    initialize_postgres(target)
                    if optional:
                        # Use this same connection/transaction; no secondary init.
                        for statement in HEALTH_DDL:
                            target.execute(statement)
                    counts = {}
                    for table, columns in (TABLE_COLUMNS | optional).items():
                        column_sql = ",".join(columns)
                        rows = snapshot.execute(f"SELECT {column_sql} FROM {table}")
                        insert = f"INSERT INTO {table}({column_sql}) VALUES({','.join('?' for _ in columns)})"
                        count = 0
                        while batch := rows.fetchmany(500):
                            for row in batch:
                                target.execute(insert, tuple(row))
                            count += len(batch)
                        if target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != count:
                            raise RuntimeError("迁移行数核验失败")
                        counts[table] = count
                return counts
            finally:
                target.close()
        finally:
            snapshot.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从 SQLite 安全迁移到空 PostgreSQL 数据库")
    parser.add_argument("--source", required=True, type=Path, help="现有 SQLite 业务数据库路径")
    args = parser.parse_args(argv)
    target_url = os.getenv("ZHIJI_DATABASE_URL", "")
    if not is_postgres(target_url):
        print("请通过 ZHIJI_DATABASE_URL 设置目标 PostgreSQL URL。", file=sys.stderr)
        return 2
    try:
        counts = migrate(args.source, target_url)
    except Exception:
        # Never log DSNs, hashes, tokens, record contents or raw driver errors.
        print("迁移失败：目标事务已回滚，源库未修改。请检查源库版本、目标为空及数据库连接。", file=sys.stderr)
        return 1
    print("迁移成功并核验行数：" + ", ".join(f"{table}={count}" for table, count in counts.items()))
    print("源库保留。请保持旧实例停止写入，使用目标数据库启动应用并核验账号和记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
