"""Custom middleware for StreamHost."""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.database import get_pool_status

logger = logging.getLogger("streamhost.request")


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort requests that exceed the configured execution timeout."""

    def __init__(self, app, timeout: float) -> None:  # type: ignore[override]
        super().__init__(app)
        self._timeout = max(0.0, timeout)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._timeout <= 0:
            return await call_next(request)

        try:
            async with asyncio.timeout(self._timeout):
                return await call_next(request)
        except asyncio.TimeoutError:
            logger.warning("Request timed out", extra={"path": str(request.url.path), "timeout": self._timeout})
            raise HTTPException(status_code=504, detail="Request timeout exceeded") from None


class DatabasePoolGuardMiddleware(BaseHTTPMiddleware):
    """Reject requests when the database connection pool is exhausted."""

    def __init__(self, app, threshold: float) -> None:  # type: ignore[override]
        super().__init__(app)
        self._threshold = max(0.0, min(1.0, threshold))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._threshold <= 0:
            return await call_next(request)

        status = get_pool_status()
        utilisation = status["checked_out"] / status["max_size"] if status["max_size"] else 0.0
        if utilisation >= self._threshold:
            logger.error(
                "Rejecting request due to database pool exhaustion",
                extra={"checked_out": status["checked_out"], "max": status["max_size"], "threshold": self._threshold},
            )
            raise HTTPException(status_code=503, detail="Database capacity exceeded")

        return await call_next(request)
