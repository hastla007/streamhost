"""Stream status endpoints."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import check_pool_health, get_db, get_db_context
from app.core.security import enforce_preview_rate_limit, enforce_rate_limit, redis_client
from app.schemas import DEFAULT_ERROR_RESPONSES, HealthResponse, StreamStatus
from app.services.stream_engine import PREVIEW_DIR
from app.services.stream_manager import stream_manager

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get(
    "/status",
    response_model=StreamStatus,
    dependencies=[Depends(get_current_user)],
    responses=DEFAULT_ERROR_RESPONSES,
)
async def get_stream_status() -> StreamStatus:
    """Return the latest stream metrics."""

    return await stream_manager.status()


@router.post(
    "/start",
    response_model=StreamStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(get_current_user)],
    responses=DEFAULT_ERROR_RESPONSES,
)
async def start_stream(media_id: int, db: Session = Depends(get_db)) -> StreamStatus:
    """Start streaming a media item to the configured RTMP destination."""

    return await stream_manager.start(db, media_id=media_id)


@router.post(
    "/stop",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(get_current_user)],
    responses=DEFAULT_ERROR_RESPONSES,
)
async def stop_stream(db: Session = Depends(get_db)) -> None:
    """Stop the running stream if one exists."""

    await stream_manager.stop(db)


def _resolve_preview_asset(name: str) -> Path:
    decoded = name
    max_decode_iterations = 10
    for _ in range(max_decode_iterations):
        unquoted = unquote(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Excessive URL encoding")

    if any(char in decoded for char in ["/", "\\", "\x00"]) or ".." in decoded:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid asset name")

    candidate = (PREVIEW_DIR / decoded).resolve()

    try:
        candidate.relative_to(PREVIEW_DIR)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")

    if not candidate.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview asset not found")
    return candidate


@router.get(
    "/preview.m3u8",
    responses=DEFAULT_ERROR_RESPONSES,
    dependencies=[Depends(enforce_preview_rate_limit)],
)
async def preview_master() -> FileResponse:
    """Return the master HLS playlist for local monitoring."""

    path = _resolve_preview_asset("master.m3u8")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl")


@router.get(
    "/preview/{asset:path}",
    responses=DEFAULT_ERROR_RESPONSES,
    dependencies=[Depends(enforce_preview_rate_limit)],
)
async def preview_asset(asset: str) -> FileResponse:
    """Serve generated HLS playlists and segments."""

    path = _resolve_preview_asset(asset)
    media_type = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t"
    return FileResponse(path, media_type=media_type)


@router.get("/health", response_model=HealthResponse, responses=DEFAULT_ERROR_RESPONSES)
async def health_check() -> HealthResponse:
    """Perform dependency checks for readiness probes."""

    issues: list[str] = []

    def _db_check() -> None:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))

    try:
        await asyncio.to_thread(_db_check)
    except Exception as exc:  # pragma: no cover - relies on infrastructure failures
        issues.append(f"Database: {exc}")

    try:
        if redis_client:
            await asyncio.to_thread(redis_client.ping)
        else:
            issues.append("Redis: Not connected")
    except Exception as exc:  # pragma: no cover - external dependency
        issues.append(f"Redis: {exc}")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            issues.append("FFmpeg: Not available")
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as exc:  # pragma: no cover - depends on ffmpeg availability
        issues.append(f"FFmpeg: {exc}")

    pool_ok, pool_message = await asyncio.to_thread(check_pool_health)
    if not pool_ok:
        issues.append(f"Database pool: {pool_message}")

    if not issues:
        status_text = "healthy"
        details = None
    elif len(issues) <= 1:
        status_text = "degraded"
        details = {"issues": issues}
    else:
        status_text = "unhealthy"
        details = {"issues": issues}

    if details is None and pool_message:
        details = {"pool": pool_message}

    return HealthResponse(
        status=status_text,
        timestamp=datetime.utcnow(),
        details=details,
    )
