"""Stream status endpoints."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db, get_db_context
from app.core.security import csrf_protect, enforce_rate_limit, redis_client
from app.schemas import HealthResponse, StreamStatus
from app.services.stream_engine import PREVIEW_DIR
from app.services.stream_manager import stream_manager

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("/status", response_model=StreamStatus, dependencies=[Depends(get_current_user)])
async def get_stream_status() -> StreamStatus:
    """Return the latest stream metrics."""

    return await stream_manager.status()


@router.post(
    "/start",
    response_model=StreamStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(csrf_protect), Depends(get_current_user)],
)
async def start_stream(media_id: int, db: Session = Depends(get_db)) -> StreamStatus:
    """Start streaming a media item to the configured RTMP destination."""

    return await stream_manager.start(db, media_id=media_id)


@router.post(
    "/stop",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(csrf_protect), Depends(get_current_user)],
)
async def stop_stream(db: Session = Depends(get_db)) -> None:
    """Stop the running stream if one exists."""

    await stream_manager.stop(db)


def _resolve_preview_asset(name: str) -> Path:
    candidate = (PREVIEW_DIR / name).resolve()
    if not (candidate == PREVIEW_DIR or PREVIEW_DIR in candidate.parents):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")
    if not candidate.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")
    return candidate


@router.get("/preview.m3u8")
async def preview_master() -> FileResponse:
    """Return the master HLS playlist for local monitoring."""

    path = _resolve_preview_asset("master.m3u8")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl")


@router.get("/preview/{asset:path}")
async def preview_asset(asset: str) -> FileResponse:
    """Serve generated HLS playlists and segments."""

    path = _resolve_preview_asset(asset)
    media_type = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t"
    return FileResponse(path, media_type=media_type)


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
