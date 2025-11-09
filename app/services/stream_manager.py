"""Runtime streaming management via FFmpeg."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import asc, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import StreamingError
from app.models import MediaAsset, PlaylistEntry, StreamSession
from app.schemas import StreamMetrics, StreamStatus
from app.services.stream_engine import StreamLaunchPlan, live_stream_engine

logger = logging.getLogger(__name__)


class StreamManager:
    """Controls the lifetime of the ffmpeg streaming process."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._session_id: Optional[int] = None
        self._destination: Optional[str] = None
        self._encoder_name: str = "ffmpeg"

    async def start(
        self,
        db: Session,
        *,
        playlist_entry_id: Optional[int] = None,
        media_id: Optional[int] = None,
    ) -> StreamStatus:
        async with self._lock:
            if await live_stream_engine.is_running():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stream already running")

            destination = self._resolve_destination()
            media_files, first_media_id = self._collect_media_files(db, playlist_entry_id, media_id)
            if not media_files:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No media available to stream")

            profiles = self._build_profiles()
            encoder, preset = self._resolve_encoder()

            self._destination = None
            self._encoder_name = "ffmpeg"

            plan = StreamLaunchPlan(
                playlist_id=playlist_entry_id or 0,
                media_files=media_files,
                destination=destination,
                profiles=profiles,
                encoder=encoder,
                preset=preset,
                fps=settings.stream_fps,
            )

            session = StreamSession(
                media_id=first_media_id,
                status="starting",
                started_at=datetime.now(timezone.utc),
            )
            try:
                db.add(session)
                db.flush()
            except IntegrityError as exc:
                logger.error("Database integrity violation when creating stream session", extra={"error": str(exc)})
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Conflicting stream session",
                ) from exc
            except SQLAlchemyError as exc:
                logger.error("Database error creating stream session", extra={"error": str(exc)})
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create stream session",
                ) from exc

            self._session_id = session.id

            try:
                await live_stream_engine.start_stream(plan)
            except FileNotFoundError as exc:
                session.status = "error"
                session.last_error = f"Media file not found: {exc}"
                db.flush()
                db.rollback()
                self._session_id = None
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            except (OSError, PermissionError) as exc:
                session.status = "error"
                session.last_error = f"File access error: {exc}"
                db.flush()
                db.rollback()
                self._session_id = None
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Cannot access media files",
                ) from exc
            except StreamingError as exc:
                session.status = "error"
                session.last_error = str(exc)
                db.flush()
                db.rollback()
                self._session_id = None
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                ) from exc
            except Exception as exc:
                session.status = "error"
                session.last_error = f"Unexpected error: {type(exc).__name__}"
                db.flush()
                db.rollback()
                self._session_id = None
                logger.exception("Unexpected failure starting stream")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Unexpected streaming error",
                ) from exc

            session.status = "online"
            session.last_error = None
            db.flush()
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                self._session_id = None
                self._destination = None
                self._encoder_name = "ffmpeg"
                await live_stream_engine.stop_stream()
                logger.exception("Failed to commit stream session state", extra={"error": str(exc)})
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to persist stream session",
                ) from exc

            self._destination = destination
            self._encoder_name = self._encoder_display(encoder)

        return await self.status()

    async def stop(self, db: Session) -> None:
        async with self._lock:
            try:
                await live_stream_engine.stop_stream()
                if self._session_id:
                    session = db.get(StreamSession, self._session_id)
                    if session:
                        session.status = "offline"
                        session.ended_at = datetime.now(timezone.utc)
                        db.flush()
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception("Failed to persist stream stop", extra={"error": str(exc)})
                raise
            finally:
                self._session_id = None
                self._destination = None
                self._encoder_name = "ffmpeg"

    async def status(self) -> StreamStatus:
        snapshot = await live_stream_engine.status_snapshot()
        running = snapshot.running

        async with self._lock:
            destination = self._destination
            encoder_name = self._encoder_name

        uptime = 0
        if running and snapshot.started_at:
            uptime = int((datetime.now(timezone.utc) - snapshot.started_at).total_seconds())

        status_text = "offline"
        if running:
            status_text = "online"
        elif snapshot.last_error:
            status_text = "error"
        elif snapshot.playlist_id is not None:
            status_text = "starting"

        return StreamStatus(
            status=status_text,
            uptime_seconds=uptime,
            encoder=encoder_name,
            target=destination,
            playlist_id=snapshot.playlist_id,
            started_at=snapshot.started_at,
            last_error=snapshot.last_error,
            metrics=snapshot.metrics if isinstance(snapshot.metrics, StreamMetrics) else StreamMetrics(),
            last_updated=datetime.now(timezone.utc),
        )

    def _resolve_destination(self) -> str:
        if not settings.youtube_rtmp_url or not settings.youtube_stream_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Destination RTMP not configured")
        return f"{settings.youtube_rtmp_url.rstrip('/')}/{settings.youtube_stream_key}"

    def _collect_media_files(
        self,
        db: Session,
        playlist_entry_id: Optional[int],
        media_id: Optional[int],
    ) -> tuple[list[Path], Optional[int]]:
        media_paths: list[tuple[int, Path]] = []

        if playlist_entry_id:
            entries = (
                db.execute(
                    select(PlaylistEntry).order_by(asc(PlaylistEntry.position), asc(PlaylistEntry.id))
                )
                .scalars()
                .all()
            )
            # Collect from the selected entry onward to keep playback continuous.
            for entry in entries:
                if entry.id == playlist_entry_id or media_paths:
                    if entry.media and entry.media.file_path:
                        media_paths.append((entry.media_id, Path(entry.media.file_path)))

            if not media_paths:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist entry not found")

        elif media_id:
            media = db.get(MediaAsset, media_id)
            if media and media.file_path:
                media_paths.append((media.id, Path(media.file_path)))

        if not media_paths:
            entries = (
                db.execute(
                    select(PlaylistEntry).order_by(asc(PlaylistEntry.position), asc(PlaylistEntry.id))
                )
                .scalars()
                .all()
            )
            for entry in entries:
                if entry.media and entry.media.file_path:
                    media_paths.append((entry.media_id, Path(entry.media.file_path)))

        if not media_paths:
            return [], None

        missing = [path for _mid, path in media_paths if not path.exists()]
        if missing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Missing media files: {missing}")

        paths = [path for _mid, path in media_paths]
        first_media_id = media_paths[0][0]
        return paths, first_media_id

    def _build_profiles(self) -> list[tuple[str, int]]:
        primary_resolution = settings.stream_resolution
        primary_bitrate = settings.stream_bitrate
        profiles = [(primary_resolution, primary_bitrate)]

        # Secondary profiles for adaptive streaming
        profiles.append(("1280x720", max(primary_bitrate // 2, 1800)))
        profiles.append(("854x480", max(primary_bitrate // 3, 1200)))
        return profiles

    def _resolve_encoder(self) -> tuple[str, str]:
        hardware = settings.stream_hardware_accel.lower()
        if hardware in {"nvenc", "qsv", "videotoolbox"}:
            return hardware, "fast"
        if hardware == "auto":
            return "libx264", "veryfast"
        return hardware or "libx264", "veryfast"

    def _encoder_display(self, encoder: str) -> str:
        mapping = {
            "nvenc": "h264_nvenc",
            "qsv": "h264_qsv",
            "videotoolbox": "h264_videotoolbox",
        }
        return mapping.get(encoder, encoder)


stream_manager = StreamManager()
