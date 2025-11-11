"""Custom middleware for StreamHost."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.database import get_pool_status
from app.core.security import (
    CSRF_EXPIRY_KEY,
    CSRF_PREVIOUS_KEY,
    CSRF_SESSION_KEY,
    generate_csrf_token,
    get_session_container,
)

logger = logging.getLogger("streamhost.request")


class CSRFMiddleware(BaseHTTPMiddleware):
    """Ensure requests have an associated CSRF token."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        container = get_session_container(request)

        if container is not None:
            token = container.get(CSRF_SESSION_KEY)
            expiry_raw = container.get(CSRF_EXPIRY_KEY)
            expired = False

            if expiry_raw is not None:
                try:
                    expired = time.time() > float(expiry_raw)
                except (TypeError, ValueError):
                    expired = True

            if token is None or expired:
                if token:
                    container[CSRF_PREVIOUS_KEY] = token
                container.pop(CSRF_SESSION_KEY, None)
                container.pop(CSRF_EXPIRY_KEY, None)
                try:
                    generate_csrf_token(request)
                except RuntimeError:
                    logger.warning("Unable to generate CSRF token; session unavailable")

        response = await call_next(request)
        return response


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
