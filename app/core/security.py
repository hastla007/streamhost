"""Security helpers for CSRF protection and rate limiting."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Optional

from fastapi import HTTPException, Request
from redis import Redis, exceptions as redis_exceptions
from starlette import status

from app.core.config import settings
from app.core.exceptions import RedisConnectionError

logger = logging.getLogger(__name__)

_CSRF_SESSION_KEY = "_csrf_token"


def _get_session_container(request: Request):
    """Return the session container for the request."""

    if hasattr(request.state, "session"):
        return request.state.session
    return request.session


def generate_csrf_token(request: Request) -> str:
    """Create and persist a CSRF token in the session."""

    token = secrets.token_urlsafe(32)
    session = _get_session_container(request)
    session[_CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request, token: str | None) -> None:
    """Validate the supplied CSRF token against the session."""

    session = _get_session_container(request)
    expected = session.get(_CSRF_SESSION_KEY)
    if not expected or not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")

    if not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


class RateLimiter:
    """Simple in-memory token bucket for rate limiting."""

    def __init__(self, calls: int, period: int, max_keys: int = 10_000) -> None:
        self.calls = calls
        self.period = period
        self.max_keys = max_keys
        self._hits: OrderedDict[str, Deque[float]] = OrderedDict()

    def check(self, identifier: str) -> None:
        now = time.time()

        if identifier not in self._hits and len(self._hits) >= self.max_keys:
            self._hits.popitem(last=False)

        hits = self._hits.setdefault(identifier, deque())

        while hits and now - hits[0] > self.period:
            hits.popleft()

        if len(hits) >= self.calls:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

        hits.append(now)


redis_client: Optional[Redis] = None
_redis_lock = threading.Lock()


def _init_redis_client() -> Optional[Redis]:  # pragma: no cover - external dependency
    try:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        client.ping()
        logger.info("Redis client initialised", extra={"url": settings.redis_url.split("@")[-1]})
        return client
    except (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as exc:
        logger.warning(
            "Redis connection failed; using in-memory rate limiting",
            extra={"error": str(exc)},
        )
        return None
    except redis_exceptions.AuthenticationError as exc:
        logger.error("Redis authentication failed", extra={"error": str(exc)})
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error initialising Redis")
        raise RedisConnectionError(f"Failed to initialise Redis: {exc}") from exc


def check_redis_connection() -> bool:
    """Ensure the Redis client is connected before use."""

    global redis_client

    with _redis_lock:
        if redis_client is None:
            redis_client = _init_redis_client()
            if redis_client is None:
                return False

    try:
        redis_client.ping()
        return True
    except redis_exceptions.RedisError:
        with _redis_lock:
            redis_client = None
        return False


with _redis_lock:
    redis_client = _init_redis_client()


class DistributedRateLimiter:
    """Redis-backed limiter with in-memory fallback for single instance use."""

    def __init__(self, calls: int, period: int) -> None:
        self.calls = calls
        self.period = period
        self._memory_fallback: Optional[RateLimiter] = None

    def check(self, identifier: str) -> None:
        if not check_redis_connection():
            if self._memory_fallback is None:
                self._memory_fallback = RateLimiter(
                    self.calls,
                    self.period,
                    settings.rate_limit_max_keys,
                )
            self._memory_fallback.check(identifier)
            return

        assert redis_client is not None
        key = f"rate_limit:{identifier}"
        now = time.time()

        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, 0, now - self.period)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, self.period)
        results = pipe.execute()
        request_count = results[1]

        if request_count >= self.calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {self.period} seconds.",
            )


rate_limiter = DistributedRateLimiter(settings.rate_limit_requests, settings.rate_limit_window)


def enforce_rate_limit(request: Request) -> None:
    """Dependency that enforces rate limiting by client IP."""

    client_host = request.client.host if request.client else "anonymous"
    rate_limiter.check(client_host)


def csrf_protect(request: Request) -> None:
    """Dependency wrapper for CSRF validation on API requests."""

    token = request.headers.get("X-CSRF-Token")
    validate_csrf(request, token)


def form_csrf_protect(request: Request, token: str | None = None) -> None:
    """Helper for validating CSRF tokens submitted via HTML forms."""

    validate_csrf(request, token)
