"""Security helpers for CSRF protection and rate limiting."""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request
from starlette import status

from app.core.config import settings

_CSRF_SESSION_KEY = "_csrf_token"


def generate_csrf_token(request: Request) -> str:
    """Create and persist a CSRF token in the session."""

    token = secrets.token_urlsafe(32)
    request.session[_CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request, token: str | None) -> None:
    """Validate the supplied CSRF token against the session."""

    expected = request.session.get(_CSRF_SESSION_KEY)
    if not expected or not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")

    if not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


class RateLimiter:
    """Simple in-memory token bucket for rate limiting."""

    def __init__(self, calls: int, period: int) -> None:
        self.calls = calls
        self.period = period
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, identifier: str) -> None:
        now = time.time()
        hits = self._hits[identifier]
        while hits and now - hits[0] > self.period:
            hits.popleft()
        if len(hits) >= self.calls:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
        hits.append(now)


rate_limiter = RateLimiter(settings.rate_limit_requests, settings.rate_limit_window)


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
