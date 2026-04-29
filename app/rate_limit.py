"""
Per-tenant rate limiter with pluggable storage backends.

Two backends are bundled:

* ``InMemoryBackend``  — sliding-window deque per key. Single-process only.
* ``RedisBackend``     — sliding-window via Redis sorted-set (ZADD/ZREMRANGEBYSCORE).
                        Activated when env var ``RATE_LIMIT_REDIS_URL`` is set
                        and the ``redis`` package is installed.

Backend interface (mirror this if you add a new one):

    class Backend(Protocol):
        def hit(self, key: str, limit: int, window: int, now: float) -> tuple[bool, int]:
            '''Return (allowed, remaining_after_this_call).'''

Limits per subscription plan are configured in PLAN_LIMITS (requests per
WINDOW_SECONDS).
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Optional, Protocol

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .auth import verify_access_token
from .auth_models import SubscriptionPlan


# Requests per WINDOW_SECONDS per tenant.
PLAN_LIMITS: dict[Optional[SubscriptionPlan], int] = {
    SubscriptionPlan.FREE_TRIAL: 120,
    SubscriptionPlan.BASIC: 600,
    SubscriptionPlan.PROFESSIONAL: 3000,
    SubscriptionPlan.ENTERPRISE: 12000,
    None: 60,  # anonymous / pre-auth
}
WINDOW_SECONDS = 60

BYPASS_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json"}
BYPASS_PREFIXES = ("/api/v1/auth/",)


# =============================================================================
# Backends
# =============================================================================

class _Backend(Protocol):
    def hit(self, key: str, limit: int, window: int, now: float) -> tuple[bool, int]: ...


class InMemoryBackend:
    """Sliding-window deque per key. Process-local."""

    def __init__(self) -> None:
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._locks: dict[str, Lock] = defaultdict(Lock)
        self._registry_lock = Lock()

    def hit(self, key: str, limit: int, window: int, now: float) -> tuple[bool, int]:
        with self._registry_lock:
            bucket = self._buckets[key]
            lock = self._locks[key]
        with lock:
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, 0
            bucket.append(now)
            return True, max(0, limit - len(bucket))


class RedisBackend:
    """
    Sliding-window via Redis sorted set.

    For each key, members are unique request timestamps (us precision) scored
    by their unix timestamp. Old entries are trimmed on every call.
    """

    def __init__(self, url: str) -> None:
        import redis  # lazy import; only required when Redis is enabled

        self.client = redis.Redis.from_url(url, decode_responses=False)
        # Fail fast if Redis is unreachable so misconfiguration surfaces at boot.
        self.client.ping()

    def hit(self, key: str, limit: int, window: int, now: float) -> tuple[bool, int]:
        ns = int(now * 1_000_000)
        cutoff = now - window
        pipe = self.client.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        pipe.zadd(key, {str(ns): now})
        pipe.expire(key, window + 5)
        _, count_before, _, _ = pipe.execute()
        if count_before >= limit:
            self.client.zrem(key, str(ns))
            return False, 0
        return True, max(0, limit - (count_before + 1))


def _build_backend() -> _Backend:
    url = os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
    if not url:
        return InMemoryBackend()
    try:
        return RedisBackend(url)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error(
            "Redis rate-limit backend init failed (%s); falling back to in-memory", e
        )
        return InMemoryBackend()


_backend: _Backend = _build_backend()


# =============================================================================
# Middleware
# =============================================================================

def _resolve_key_and_limit(request: Request) -> tuple[str, int]:
    """Identify the caller. Prefer tenant_id from JWT; fall back to client IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        token_data = verify_access_token(token)
        if token_data and token_data.tenant_id is not None:
            return f"tenant:{token_data.tenant_id}", PLAN_LIMITS[SubscriptionPlan.PROFESSIONAL]

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}", PLAN_LIMITS[None]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant sliding-window rate limiter. Backend chosen at module load."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in BYPASS_PATHS or any(path.startswith(p) for p in BYPASS_PREFIXES):
            return await call_next(request)

        key, limit = _resolve_key_and_limit(request)
        allowed, remaining = _backend.hit(key, limit, WINDOW_SECONDS, time.time())

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({limit}/{WINDOW_SECONDS}s). Try again shortly.",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
