"""Shared type definitions for StreamHost."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Dict, Optional, Protocol, TypedDict

from starlette.requests import Request
from starlette.responses import Response

from app.schemas import StreamMetrics


class ASGICallNext(Protocol):
    """Protocol for the ASGI middleware call_next callable."""

    def __call__(self, request: Request) -> Awaitable[Response]:
        """Invoke the next middleware or endpoint."""


class PaginationInfo(TypedDict):
    """Pagination metadata passed to templates."""

    page: int
    pages: int
    page_size: int
    total: int
    page_param: str
    size_param: str


class BaseContext(TypedDict):
    """Base template context shared across pages."""

    request: Request
    csrf_token: str


class HomeContext(BaseContext, total=False):
    """Context payload for the dashboard home view."""

    stream: Any
    alerts: list[Any]
    playlist: list[Any]
    uptime_hours: float


class MediaContext(BaseContext, total=False):
    """Context payload for the media management view."""

    media: list[Any]
    media_pagination: PaginationInfo


@dataclass(frozen=True)
class StreamSnapshot:
    """Immutable snapshot of stream state."""

    playlist_id: Optional[int]
    started_at: Optional[datetime]
    last_error: Optional[str]
    metrics: StreamMetrics
