"""FFmpeg interactions with proper error handling."""
from __future__ import annotations

import logging
import subprocess
from functools import lru_cache
from pathlib import Path

import ffmpeg

logger = logging.getLogger(__name__)


class TranscodingError(RuntimeError):
    """Raised when FFmpeg fails to transcode media."""


@lru_cache(maxsize=1)
def _available_encoders() -> set[str]:
    """Return the set of encoder names supported by the local FFmpeg build."""

    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):  # pragma: no cover - depends on runtime
        return set()

    encoders: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(" "):
            encoders.add(parts[1])
    return encoders


def hardware_encoder_available(name: str) -> bool:
    """Return True if the requested hardware encoder is supported."""

    return name in _available_encoders()


def transcode_media(source: Path, target: Path, *, video_bitrate: str, audio_bitrate: str) -> None:
    """Transcode a media file while capturing FFmpeg failures."""

    logger.info("Starting transcode", extra={"source": str(source), "target": str(target)})
    try:
        (
            ffmpeg
            .input(str(source))
            .output(str(target), video_bitrate=video_bitrate, audio_bitrate=audio_bitrate)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:  # pragma: no cover - requires FFmpeg
        logger.error("FFmpeg failed", exc_info=exc)
        raise TranscodingError("Transcoding failed") from exc


def probe_codecs(source: Path) -> dict:
    """Return codec information for a source file."""

    try:
        probe = ffmpeg.probe(str(source))
    except ffmpeg.Error as exc:  # pragma: no cover - requires FFmpeg
        logger.warning("Unable to probe media", exc_info=exc)
        raise TranscodingError("Failed to probe media") from exc
    return probe
