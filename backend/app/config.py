"""Small, explicit runtime configuration; never enable wildcard origins."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BACKEND_ROOT.parent / "frontend" / "dist"
DEFAULT_ORIGINS = "capacitor://localhost,http://localhost,https://localhost"


@dataclass(frozen=True)
class Settings:
    database_path: Path
    allowed_origins: tuple[str, ...]
    cookie_secure: bool = False
    session_seconds: int = 7 * 24 * 60 * 60
    max_body_bytes: int = 1024 * 1024

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
        return cls(
            database_path=Path(database_path or os.getenv(
                "ZHIJI_DATABASE_PATH", str(BACKEND_ROOT / "data" / "zhiji.sqlite3")
            )).expanduser().resolve(),
            allowed_origins=origins,
            cookie_secure=os.getenv("ZHIJI_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
        )
