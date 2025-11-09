import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core import security
from app.core.security import DistributedRateLimiter, RateLimiter, enforce_preview_rate_limit, generate_csrf_token, validate_csrf
from app.core.middleware import RequestTimeoutMiddleware


class MockRequest:
    def __init__(self, host: str = "127.0.0.1") -> None:
        self.client = SimpleNamespace(host=host)
        self.state = SimpleNamespace(session={})
        self.session = self.state.session
        self.headers = {}
        self.url = SimpleNamespace(path="/test")


def test_csrf_token_expires(monkeypatch) -> None:
    request = MockRequest()
    token = generate_csrf_token(request)
    assert token
    request.session[security._CSRF_EXPIRY_KEY] = time.time() - 1

    with pytest.raises(HTTPException) as exc:
        validate_csrf(request, token)
    assert exc.value.status_code == 403
    assert exc.value.detail == "CSRF token expired"


def test_preview_rate_limiter_enforces_limits(monkeypatch) -> None:
    limiter = DistributedRateLimiter(2, 60)
    limiter._memory_fallback = RateLimiter(2, 60)

    monkeypatch.setattr(security, "preview_rate_limiter", limiter)
    monkeypatch.setattr(security, "check_redis_connection", lambda: False)

    request = MockRequest()
    enforce_preview_rate_limit(request)
    enforce_preview_rate_limit(request)
    with pytest.raises(HTTPException):
        enforce_preview_rate_limit(request)


@pytest.mark.anyio
async def test_request_timeout_middleware_triggers_timeout() -> None:
    class DummyApp:
        async def __call__(self, scope, receive, send):  # pragma: no cover - required by Starlette
            raise NotImplementedError

    async def call_next(_: Request) -> Response:
        await asyncio.sleep(0.05)
        return Response("ok")

    middleware = RequestTimeoutMiddleware(DummyApp(), timeout=0.01)
    scope = {"type": "http", "method": "GET", "path": "/timeout", "headers": []}
    request = Request(scope=scope)

    with pytest.raises(HTTPException) as exc:
        await middleware.dispatch(request, call_next)

    assert exc.value.status_code == 504
