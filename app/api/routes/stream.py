"""Stream status endpoints."""
from __future__ import annotations

import subprocess
from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db, get_db_context
from app.core.security import csrf_protect, enforce_rate_limit, redis_client
from app.schemas import HealthResponse, StreamStatus
from app.services.stream_manager import stream_manager

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("/status", response_model=StreamStatus, dependencies=[Depends(get_current_user)])
def get_stream_status() -> StreamStatus:
    """Return the latest stream metrics."""

    return stream_manager.status()


@router.post(
    "/start",
    response_model=StreamStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(csrf_protect), Depends(get_current_user)],
)
def start_stream(media_id: int, db: Session = Depends(get_db)) -> StreamStatus:
    """Start streaming a media item to the configured RTMP destination."""

    return stream_manager.start(db, media_id)


@router.post(
    "/stop",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(csrf_protect), Depends(get_current_user)],
)
def stop_stream(db: Session = Depends(get_db)) -> None:
    """Stop the running stream if one exists."""

    stream_manager.stop(db)


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Perform dependency checks for readiness probes."""

    issues: list[str] = []

    try:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - relies on infrastructure failures
        issues.append(f"Database: {exc}")

    try:
        if redis_client:
            redis_client.ping()
        else:
            issues.append("Redis: Not connected")
    except Exception as exc:  # pragma: no cover - external dependency
        issues.append(f"Redis: {exc}")

    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, check=False)
        if result.returncode != 0:
            issues.append("FFmpeg: Not available")
    except Exception as exc:  # pragma: no cover - depends on ffmpeg availability
        issues.append(f"FFmpeg: {exc}")

    if not issues:
        status_text = "healthy"
    elif len(issues) <= 1:
        status_text = "degraded"
    else:
        status_text = "unhealthy"

    return HealthResponse(
        status=status_text,
        timestamp=datetime.utcnow(),
        details={"issues": issues} if issues else None,
    )
