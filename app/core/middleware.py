"""Custom middleware for StreamHost."""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
