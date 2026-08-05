"""Abuse controls for the public, unauthenticated endpoints.

Every public route (check-in, post-test, survey, certificate verification) is
reachable by anyone who can read a printed QR code, and each of them writes to
-- or reads from -- the official CEU record. Without a budget, one script turns
a published event token into unlimited fabricated attendance rows.

This deliberately does NOT introduce a second limiter implementation: it wraps
``LoginRateLimiter`` from :mod:`app.core.security`, the same sliding-window +
lockout guard that already protects ``/auth/login``. The only difference is
what counts as an "attempt": login records only *failed* logins, while a public
endpoint records *every* request, which turns the same mechanism into a plain
rate limiter. State is per-process, which matches the single-worker deployment.

Test-friendliness: the limits are read from settings on first use, so a test
can override a setting and call :meth:`PublicRateLimiter.reset` to pick it up;
``reset()`` also clears every counter, and ``public_rate_limit_enabled = False``
turns the whole thing off.
"""

import threading

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.security import LoginRateLimiter

TOO_MANY_REQUESTS_DETAIL = "Too many requests. Please wait a moment and try again."


def client_ip(request: Request) -> str:
    """Best-effort caller identity.

    The API always runs behind a managed proxy (Render in production), where
    ``request.client.host`` is the proxy itself -- keying on that would put
    every attendee of an event into one shared bucket and lock out a room full
    of people checking in at once. So the forwarded client address wins when
    present. A caller on a directly exposed instance could spoof the header to
    get a fresh bucket; that is the accepted tradeoff for not rate-limiting the
    whole internet as a single client, and the per-token budget still applies.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class PublicRateLimiter:
    """Per-caller request budget for one family of public endpoints."""

    def __init__(self, limit_setting: str) -> None:
        # Name of the Settings attribute holding this family's request cap, so
        # the value is resolved lazily (tests can change it, then reset()).
        self._limit_setting = limit_setting
        self._guard: LoginRateLimiter | None = None
        self._lock = threading.Lock()

    def _current_guard(self) -> LoginRateLimiter:
        with self._lock:
            if self._guard is None:
                self._guard = LoginRateLimiter(
                    max_failures=max(1, int(getattr(settings, self._limit_setting))),
                    window_seconds=settings.public_rate_limit_window_seconds,
                    lockout_seconds=settings.public_rate_limit_lockout_seconds,
                )
            return self._guard

    def reset(self) -> None:
        """Drop every counter and re-read the configured limits."""
        with self._lock:
            self._guard = None

    def check(self, key: str, caller: str) -> None:
        """Count one request from ``caller`` against ``key``; 429 when over."""
        if not settings.public_rate_limit_enabled:
            return
        guard = self._current_guard()
        retry_after = guard.retry_after(key, caller)
        if retry_after:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=TOO_MANY_REQUESTS_DETAIL,
                headers={"Retry-After": str(retry_after)},
            )
        guard.record_failure(key, caller)


# One budget for public writes (submissions), one for public verification
# lookups: an employer checking certificates should not eat into the budget a
# classroom needs to check in, and vice versa.
public_write_limiter = PublicRateLimiter("public_write_rate_limit")
public_verify_limiter = PublicRateLimiter("public_verify_rate_limit")

ALL_PUBLIC_LIMITERS = (public_write_limiter, public_verify_limiter)


def reset_public_rate_limits() -> None:
    """Clear every public limiter -- called by the test fixtures between cases."""
    for limiter in ALL_PUBLIC_LIMITERS:
        limiter.reset()


class PublicRateLimit:
    """FastAPI dependency: budget a public route per caller IP + URL token.

    ``scope`` keeps the different routes from sharing a bucket; ``key_param``
    names the path parameter that identifies the resource (the event token, or
    the certificate number), so one leaked token cannot be used to exhaust
    another event's budget.

    Usage::

        _: None = Depends(PublicRateLimit("checkin", "token"))
    """

    def __init__(
        self,
        scope: str,
        key_param: str | None = None,
        limiter: PublicRateLimiter | None = None,
    ) -> None:
        self.scope = scope
        self.key_param = key_param
        self.limiter = limiter or public_write_limiter

    def __call__(self, request: Request) -> None:
        key = self.scope
        if self.key_param:
            key = f"{self.scope}:{request.path_params.get(self.key_param, '')}"
        self.limiter.check(key, client_ip(request))
