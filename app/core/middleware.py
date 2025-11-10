"""Custom middleware for StreamHost."""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


class DatabaseCapacityMiddleware(BaseHTTPMiddleware):
    """Reject requests when the database pool is critically saturated."""

    def __init__(self, app, threshold: float) -> None:  # type: ignore[override]
        super().__init__(app)
        self._threshold = max(0.0, min(threshold, 1.0))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            status = get_pool_status()
        except Exception:  # pragma: no cover - diagnostic only
            return await call_next(request)

        max_size = status.get("max_size", 0) or 0
        checked_out = status.get("checked_out", 0)
        utilisation = (checked_out / max_size) if max_size else 0.0

        if utilisation >= self._threshold:
            logger.error(
                "Rejecting request due to database pool saturation",
                extra={"checked_out": checked_out, "max_size": max_size, "threshold": self._threshold},
            )
            return JSONResponse(
                {"detail": "Service unavailable due to database load"},
                status_code=503,
            )

        return await call_next(request)
