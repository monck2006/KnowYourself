"""Password hashing, opaque sessions and a single-process login limiter."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import threading
import time


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="microseconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (n, r, p) != ("16384", "8", "1"):
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(seconds: int) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(48)
    return token, token_digest(token), timestamp(utc_now() + timedelta(seconds=seconds))


class AuthRateLimiter:
    """Bounded process-local sliding window; use shared storage for multiple workers."""

    def __init__(self, limit: int = 20, window_seconds: int = 300):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            # Evict expired keys to keep random usernames/IPs from growing memory forever.
            if len(self._attempts) > 10000:
                self._attempts = defaultdict(deque, {
                    entry: values for entry, values in self._attempts.items()
                    if values and values[-1] > now - self.window_seconds
                })
                if key not in self._attempts and len(self._attempts) > 10000:
                    return False
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True
