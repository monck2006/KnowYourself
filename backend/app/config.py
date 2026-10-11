"""Small, explicit runtime configuration; never enable wildcard origins."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BACKEND_ROOT.parent / "frontend" / "dist"
DEFAULT_ORIGINS = "capacitor://localhost,http://localhost,https://localhost"


@dataclass(frozen=True)
class Settings:
    database_path: Path | str
    allowed_origins: tuple[str, ...]
    knowledge_database_path: Path
    openfda_enabled: bool = True
    openfda_api_key: str = ""
    cookie_secure: bool = False
    session_seconds: int = 7 * 24 * 60 * 60
    max_body_bytes: int = 1024 * 1024
    llm_enabled: bool = False
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: str = field(default="", repr=False)

    @classmethod
    def load(cls, database_path: Path | str | None = None) -> "Settings":
        origins = tuple(dict.fromkeys(
            value.strip().rstrip("/")
            for value in os.getenv("ZHIJI_ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",")
            if value.strip()
        ))
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin or parsed.scheme not in {"https", "http", "capacitor"}
                or not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password
            ):
                raise ValueError("ZHIJI_ALLOWED_ORIGINS 必须是明确的 Origin，不能包含通配符、路径或凭据")
        selected_database = str(database_path or os.getenv("ZHIJI_DATABASE_URL") or os.getenv(
            "ZHIJI_DATABASE_PATH", str(BACKEND_ROOT / "data" / "zhiji.sqlite3")
        ))
        is_postgres = selected_database.startswith(("postgresql://", "postgres://"))
        if "://" in selected_database and not is_postgres:
            raise ValueError("业务数据库仅支持 SQLite 文件或 PostgreSQL URL")
        business_path = selected_database if is_postgres else Path(selected_database).expanduser().resolve()
        knowledge_default = (BACKEND_ROOT / "data" / "knowledge.sqlite3" if is_postgres
                             else business_path.with_name(business_path.stem + ".knowledge.sqlite3"))
        knowledge_path = Path(os.getenv("ZHIJI_KNOWLEDGE_DATABASE_PATH", str(knowledge_default))).expanduser().resolve()
        if not is_postgres and knowledge_path == business_path:
            raise ValueError("知识库必须与账号及病程数据库使用不同文件")
        return cls(
            database_path=business_path,
            knowledge_database_path=knowledge_path,
            openfda_enabled=os.getenv("ZHIJI_OPENFDA_ENABLED", "true").lower() in {"1", "true", "yes"},
            openfda_api_key=os.getenv("OPENFDA_API_KEY", ""),
            allowed_origins=origins,
            cookie_secure=os.getenv("ZHIJI_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
            llm_enabled=os.getenv("ZHIJI_LLM_ENABLED", "false").lower() in {"1", "true", "yes"},
            llm_base_url=os.getenv("ZHIJI_LLM_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            llm_model=os.getenv("ZHIJI_LLM_MODEL", "deepseek-v4-flash").strip(),
            llm_api_key=os.getenv("ZHIJI_LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")).strip(),
        )
