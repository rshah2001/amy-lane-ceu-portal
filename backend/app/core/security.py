import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, role: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


class LoginRateLimiter:
    """In-memory sliding-window brute-force guard keyed by email + client IP.

    After ``max_failures`` failed attempts within ``window_seconds`` the key is
    locked out for ``lockout_seconds``. Dependency-free and thread-safe; state
    is per-process, which is sufficient for the single-worker deployment.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 300,
        lockout_seconds: int = 300,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(email: str, client_ip: str) -> str:
        return f"{email.strip().lower()}|{client_ip}"

    def retry_after(self, email: str, client_ip: str) -> int:
        """Seconds until the key unlocks, or 0 when login may proceed."""
        key = self._key(email, client_ip)
        with self._lock:
            now = time.monotonic()
            locked_until = self._locked_until.get(key)
            if locked_until is None:
                return 0
            if locked_until <= now:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return 0
            return math.ceil(locked_until - now)

    def record_failure(self, email: str, client_ip: str) -> None:
        key = self._key(email, client_ip)
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            attempts = self._failures.setdefault(key, deque())
            attempts.append(now)
            while attempts and attempts[0] <= now - self._window_seconds:
                attempts.popleft()
            if len(attempts) >= self._max_failures:
                self._locked_until[key] = now + self._lockout_seconds
                attempts.clear()

    def reset(self, email: str, client_ip: str) -> None:
        key = self._key(email, client_ip)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _prune(self, now: float) -> None:
        """Drop stale entries so the maps cannot grow without bound."""
        expired_locks = [key for key, until in self._locked_until.items() if until <= now]
        for key in expired_locks:
            del self._locked_until[key]
        cutoff = now - self._window_seconds
        stale = [key for key, attempts in self._failures.items() if not attempts or attempts[-1] <= cutoff]
        for key in stale:
            del self._failures[key]


login_rate_limiter = LoginRateLimiter()

