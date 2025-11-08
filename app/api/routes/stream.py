"""Stream status endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from app.core.security import enforce_rate_limit
from app.schemas import HealthResponse, StreamStatus
from app.services.state import app_state

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("/status", response_model=StreamStatus)
def get_stream_status() -> StreamStatus:
    """Return the latest stream metrics."""

    return app_state.stream_status


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Basic liveness probe for infrastructure monitoring."""

    return HealthResponse(status="healthy", timestamp=datetime.utcnow())
