"""Metadata extraction utilities for uploaded media."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import ffmpeg

from app.core.config import settings
from app.schemas import MediaMetadata

logger = logging.getLogger(__name__)

THUMBNAIL_DIR = Path(settings.media_root).parent / "thumbnails"
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class _ProbeResult:
    duration_seconds: int
    width: Optional[int]
    height: Optional[int]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    bitrate: Optional[int]
    frame_rate: Optional[str]


class MetadataExtractor:
    """Extract metadata from media files using ffprobe and heuristics."""

    async def extract_metadata(self, filepath: Path) -> MediaMetadata:
        probe = await asyncio.to_thread(self._probe_file, filepath)
        thumbnail = await asyncio.to_thread(self._generate_thumbnail, filepath)
        title, year = self._guess_title_year(filepath)

        return MediaMetadata(
            duration_seconds=probe.duration_seconds,
            width=probe.width,
            height=probe.height,
            video_codec=probe.video_codec,
            audio_codec=probe.audio_codec,
            bitrate=probe.bitrate,
            frame_rate=probe.frame_rate,
            thumbnail_path=str(thumbnail) if thumbnail else None,
            title=title,
            year=year,
            genre=None,
        )

    def _probe_file(self, filepath: Path) -> _ProbeResult:
        try:
            data = ffmpeg.probe(str(filepath))
        except (ffmpeg.Error, OSError, ValueError) as exc:  # pragma: no cover - depends on ffmpeg
            logger.error("ffprobe failed", exc_info=exc)
            raise RuntimeError("Failed to probe media") from exc

        fmt = data.get("format", {})
        duration = fmt.get("duration")
        duration_seconds = int(float(duration)) if duration else 0
        bitrate = int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else None

        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

        frame_rate: Optional[str] = None
        if video_stream:
            frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
            if frame_rate and frame_rate != "0/0":
                try:
                    numerator, denominator = frame_rate.split("/")
                    if int(denominator) != 0:
                        fps = round(int(numerator) / int(denominator), 2)
                        frame_rate = str(fps)
                except Exception:  # pragma: no cover - defensive
                    pass

        return _ProbeResult(
            duration_seconds=duration_seconds,
            width=video_stream.get("width") if video_stream else None,
            height=video_stream.get("height") if video_stream else None,
            video_codec=video_stream.get("codec_name") if video_stream else None,
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            bitrate=bitrate,
            frame_rate=frame_rate,
        )

    def _generate_thumbnail(self, filepath: Path) -> Optional[Path]:
        target = THUMBNAIL_DIR / f"{filepath.stem}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(filepath),
            "-vf",
            "thumbnail,scale=640:-1",
            "-frames:v",
            "1",
            str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            return target
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - depends on ffmpeg
            logger.warning("Failed to generate thumbnail", exc_info=exc)
            return None

    def _guess_title_year(self, filepath: Path) -> tuple[Optional[str], Optional[int]]:
        name = filepath.stem.replace(".", " ")
        match = re.search(r"(?P<title>.+?)(?:\s*(?P<year>19\d{2}|20\d{2}))?$", name)
        if not match:
            return name.title(), None
        title = match.group("title").replace("_", " ").strip().title()
        year_str = match.group("year")
        year = int(year_str) if year_str else None
        return title or filepath.stem.title(), year


metadata_extractor = MetadataExtractor()
