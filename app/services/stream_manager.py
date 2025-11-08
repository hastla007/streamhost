"""Runtime streaming management via FFmpeg."""
from __future__ import annotations

import logging
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MediaAsset, StreamSession
from app.schemas import StreamStatus

logger = logging.getLogger(__name__)


class StreamManager:
    """Controls the lifetime of the ffmpeg streaming process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._session_id: Optional[int] = None
        self._started_at: Optional[datetime] = None

    def _build_command(self, media: MediaAsset, destination: str) -> list[str]:
        video_bitrate = f"{settings.stream_bitrate}k"
        args = [
            "ffmpeg",
            "-re",
            "-i",
            media.file_path,
            "-c:v",
            "libx264" if settings.stream_hardware_accel == "auto" else settings.stream_hardware_accel,
            "-b:v",
            video_bitrate,
            "-r",
            str(settings.stream_fps),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "flv",
            destination,
        ]
        return args

    def start(self, db: Session, media_id: int) -> StreamStatus:
        with self._lock:
            if self._process and self._process.poll() is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stream already running")

            media = db.get(MediaAsset, media_id)
            if not media or not media.file_path:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            if not Path(media.file_path).exists():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file missing on disk")

            if not settings.youtube_rtmp_url or not settings.youtube_stream_key:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Destination RTMP not configured")

            destination = f"{settings.youtube_rtmp_url.rstrip('/')}/{settings.youtube_stream_key}"
            command = self._build_command(media, destination)
            logger.info("Starting stream", extra={"command": shlex.join(command)})
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                logger.error("FFmpeg not available", exc_info=exc)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="FFmpeg not installed") from exc

            session = StreamSession(
                media_id=media.id,
                status="online",
                started_at=datetime.now(timezone.utc),
            )
            db.add(session)
            db.flush()
            self._session_id = session.id
            self._started_at = session.started_at
            return self.status()

    def stop(self, db: Session) -> None:
        with self._lock:
            if not self._process:
                return
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            if self._session_id:
                session = db.get(StreamSession, self._session_id)
                if session:
                    session.status = "offline"
                    session.ended_at = datetime.now(timezone.utc)
                    db.flush()
            self._process = None
            self._session_id = None
            self._started_at = None

    def status(self) -> StreamStatus:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            uptime = int((datetime.now(timezone.utc) - self._started_at).total_seconds()) if running and self._started_at else 0
            status_value = "online" if running else "offline"
            return StreamStatus(
                status=status_value,
                bitrate_kbps=settings.stream_bitrate,
                uptime_seconds=uptime,
                encoder="ffmpeg",
                dropped_frames=0,
                last_updated=datetime.now(timezone.utc),
            )


stream_manager = StreamManager()
