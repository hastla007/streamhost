"""Background cleanup service for temporary assets."""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class CleanupService:
    """Monitor and clean temporary directories."""

    def __init__(self) -> None:
        self.thumbnail_dir = Path(settings.media_root).parent / "thumbnails"
        self.preview_dir = Path(settings.media_root).parent / "preview"
        self.temp_prefix = "streamhost_playlist_"

        self.thumbnail_max_age_days = 30
        self.preview_max_age_hours = 24
        self.max_directory_size_gb = 10

        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._is_running = False

    async def start(self) -> None:
        """Start the background cleanup loop."""

        if self._is_running:
            logger.debug("Cleanup service already running")
            return
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Cleanup service started")

    async def stop(self) -> None:
        """Stop the background cleanup loop."""

        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("Cleanup service stopped")

    async def cleanup_all(self) -> dict[str, int]:
        """Run all cleanup tasks and return statistics."""

        stats = {
            "thumbnails_removed": 0,
            "preview_segments_removed": 0,
            "concat_files_removed": 0,
            "bytes_freed": 0,
        }

        thumbnail_result, preview_result, concat_result = await asyncio.gather(
            asyncio.to_thread(self._cleanup_thumbnails),
            asyncio.to_thread(self._cleanup_preview_segments),
            asyncio.to_thread(self._cleanup_concat_files),
            return_exceptions=True,
        )

        def _merge(result: object, key: str) -> None:
            nonlocal stats
            if isinstance(result, tuple):
                count, bytes_freed = result
                stats[key] = count
                stats["bytes_freed"] += bytes_freed
            elif isinstance(result, Exception):
                logger.error("Cleanup task failed", exc_info=result)

        _merge(thumbnail_result, "thumbnails_removed")
        _merge(preview_result, "preview_segments_removed")
        _merge(concat_result, "concat_files_removed")

        logger.info(
            "Cleanup run completed",
            extra={
                "thumbnails_removed": stats["thumbnails_removed"],
                "preview_segments_removed": stats["preview_segments_removed"],
                "concat_files_removed": stats["concat_files_removed"],
                "mb_freed": f"{stats['bytes_freed'] / 1024 / 1024:.2f}",
            },
        )

        await self._check_directory_sizes()
        return stats

    async def _cleanup_loop(self) -> None:
        while self._is_running:
            try:
                await self.cleanup_all()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error during cleanup loop")
                await asyncio.sleep(300)

    def _cleanup_thumbnails(self) -> tuple[int, int]:
        if not self.thumbnail_dir.exists():
            return 0, 0
        cutoff = datetime.now() - timedelta(days=self.thumbnail_max_age_days)
        removed = 0
        bytes_freed = 0
        for thumbnail in self.thumbnail_dir.glob("*.jpg"):
            try:
                mtime = datetime.fromtimestamp(thumbnail.stat().st_mtime)
                if mtime < cutoff:
                    size = thumbnail.stat().st_size
                    thumbnail.unlink()
                    removed += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                logger.warning("Failed to remove thumbnail", extra={"path": str(thumbnail)})
        return removed, bytes_freed

    def _cleanup_preview_segments(self) -> tuple[int, int]:
        if not self.preview_dir.exists():
            return 0, 0
        cutoff = datetime.now() - timedelta(hours=self.preview_max_age_hours)
        removed = 0
        bytes_freed = 0
        for segment in self.preview_dir.glob("segment_*.ts"):
            try:
                mtime = datetime.fromtimestamp(segment.stat().st_mtime)
                if mtime < cutoff:
                    size = segment.stat().st_size
                    segment.unlink()
                    removed += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                logger.warning("Failed to remove preview segment", extra={"path": str(segment)})
        for playlist in self.preview_dir.glob("stream_*.m3u8"):
            if playlist.name == "master.m3u8":
                continue
            try:
                mtime = datetime.fromtimestamp(playlist.stat().st_mtime)
                if mtime < cutoff:
                    size = playlist.stat().st_size
                    playlist.unlink()
                    removed += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                logger.warning("Failed to remove preview playlist", extra={"path": str(playlist)})
        return removed, bytes_freed

    def _cleanup_concat_files(self) -> tuple[int, int]:
        temp_dir = Path(tempfile.gettempdir())
        if not temp_dir.exists():
            return 0, 0
        cutoff = datetime.now() - timedelta(hours=1)
        removed = 0
        bytes_freed = 0
        for concat_dir in temp_dir.glob(f"{self.temp_prefix}*"):
            if not concat_dir.is_dir():
                continue
            try:
                mtime = datetime.fromtimestamp(concat_dir.stat().st_mtime)
                if mtime < cutoff:
                    size = sum(f.stat().st_size for f in concat_dir.rglob("*") if f.is_file())
                    shutil.rmtree(concat_dir, ignore_errors=True)
                    removed += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                logger.warning("Failed to remove concat directory", extra={"path": str(concat_dir)})
        return removed, bytes_freed

    async def _check_directory_sizes(self) -> None:
        directories = [
            ("thumbnails", self.thumbnail_dir),
            ("preview", self.preview_dir),
        ]
        for name, directory in directories:
            if not directory.exists():
                continue
            try:
                total_size = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
                size_gb = total_size / 1024 / 1024 / 1024
                if size_gb > self.max_directory_size_gb:
                    logger.warning(
                        "Directory size exceeds threshold",
                        extra={
                            "directory": name,
                            "size_gb": f"{size_gb:.2f}",
                            "threshold_gb": self.max_directory_size_gb,
                        },
                    )
                else:
                    logger.debug(
                        "Directory size within limits",
                        extra={"directory": name, "size_gb": f"{size_gb:.2f}"},
                    )
            except OSError:
                logger.warning("Failed to inspect directory size", extra={"directory": name})

    def get_directory_stats(self) -> dict[str, dict[str, float]]:
        stats: dict[str, dict[str, float]] = {}
        directories = [
            ("thumbnails", self.thumbnail_dir),
            ("preview", self.preview_dir),
        ]
        for name, directory in directories:
            if not directory.exists():
                stats[name] = {"size_mb": 0, "file_count": 0}
                continue
            try:
                files = [f for f in directory.rglob("*") if f.is_file()]
                total_size = sum(f.stat().st_size for f in files)
                stats[name] = {
                    "size_mb": total_size / 1024 / 1024,
                    "file_count": len(files),
                }
            except OSError:
                stats[name] = {"size_mb": 0, "file_count": 0, "error": "Failed to read"}
        return stats


cleanup_service = CleanupService()
