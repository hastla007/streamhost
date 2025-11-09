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
from app.core.exceptions import MetadataExtractionError
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
        except ffmpeg.Error as exc:  # pragma: no cover - depends on ffmpeg
            stderr = exc.stderr.decode('utf-8', 'ignore') if exc.stderr else 'No error output'
            logger.error("ffprobe failed", extra={"filepath": str(filepath), "stderr": stderr})
            raise MetadataExtractionError(f"Failed to probe {filepath.name}") from exc
        except (OSError, IOError) as exc:
            logger.error("File access error during probe", extra={"filepath": str(filepath)})
            raise MetadataExtractionError(f"Cannot access file: {filepath.name}") from exc
        except ValueError as exc:
            logger.error("Invalid probe output", extra={"filepath": str(filepath)})
            raise MetadataExtractionError(f"Invalid media format: {filepath.name}") from exc

        fmt = data.get("format", {})
        duration = fmt.get("duration")
        duration_seconds = int(float(duration)) if duration else 0
        bitrate = int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else None

        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

        frame_rate: Optional[str] = None
        if video_stream:
            frame_rate_raw = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
            if frame_rate_raw and frame_rate_raw != "0/0":
                try:
                    numerator, denominator = frame_rate_raw.split("/")
                    denom_int = int(denominator)
                    if denom_int != 0:
                        fps = round(int(numerator) / denom_int, 2)
                        frame_rate = str(fps)
                    else:
                        logger.warning(
                            "Division by zero parsing frame rate",
                            extra={"filepath": str(filepath), "raw": frame_rate_raw},
                        )
                except (ValueError, TypeError, AttributeError) as exc:
                    logger.warning(
                        "Failed to parse frame rate",
                        extra={"filepath": str(filepath), "raw": frame_rate_raw, "error": str(exc)},
                    )
            elif frame_rate_raw:
                logger.debug(
                    "Frame rate information unavailable",
                    extra={"filepath": str(filepath), "raw": frame_rate_raw},
                )

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
