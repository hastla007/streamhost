"""Media library persistence and upload handling."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from datetime import datetime, timezone
import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import asc, func, select
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename

from app.core.config import settings
from app.models import MediaAsset
from app.schemas import MediaItem
from app.services.metadata_extractor import metadata_extractor

try:  # pragma: no cover - optional dependency
    import magic

    MagicError = magic.MagicException  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback when libmagic unavailable
    magic = None
    MagicError = Exception

MEDIA_ROOT = Path(os.getenv("MOVIES_DIR", settings.media_root))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
ALLOWED_MIME_TYPES = {"video/mp4", "video/x-matroska", "video/quicktime", "video/webm", "video/x-msvideo"}


logger = logging.getLogger(__name__)


async def _save_upload_securely(upload: UploadFile) -> tuple[Path, int, str, str]:
    """Persist an upload to disk with strict validation and hashing."""

    if not upload.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Files of type {suffix or 'unknown'} are not supported")

    if upload.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"MIME type {upload.content_type} is not allowed")

    safe_name = secure_filename(upload.filename)
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename supplied")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    unique_id = uuid.uuid4().hex[:8]
    destination = MEDIA_ROOT / f"{timestamp}_{unique_id}_{safe_name}"
    temp_destination = destination.with_suffix(destination.suffix + ".upload")

    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    received = 0
    max_bytes = settings.max_upload_bytes

    try:
        async with aiofiles.open(temp_destination, "xb") as buffer:
            while chunk := await upload.read(8192):
                received += len(chunk)
                if received > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {settings.max_upload_mb}MB limit",
                    )
                await buffer.write(chunk)
                hasher.update(chunk)
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A file with this name already exists") from exc
    except HTTPException:
        temp_destination.unlink(missing_ok=True)
        raise
    except Exception:
        temp_destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    try:
        if magic is None:
            detected_mime, _ = mimetypes.guess_type(str(temp_destination))
            if not detected_mime:
                temp_destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Unable to determine media type",
                )
        else:
            detected_mime = magic.from_file(str(temp_destination), mime=True)
    except MagicError as exc:  # pragma: no cover - depends on libmagic
        temp_destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to inspect media") from exc

    if detected_mime not in ALLOWED_MIME_TYPES:
        temp_destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Detected MIME type {detected_mime} is not supported")

    try:
        temp_destination.replace(destination)
    except FileExistsError as exc:
        temp_destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A file with this name already exists") from exc
    except Exception:
        temp_destination.unlink(missing_ok=True)
        raise

    checksum = hasher.hexdigest()
    return destination, received, checksum, detected_mime


def list_media(db: Session) -> list[MediaItem]:
    """Return all media items sorted by title."""

    records = db.scalars(select(MediaAsset).order_by(asc(MediaAsset.title))).all()
    return [_to_media_item(item) for item in records]


def paginate_media(db: Session, *, limit: int, offset: int) -> tuple[list[MediaItem], int]:
    """Return a paginated slice of media items and the total count."""

    total = db.scalar(select(func.count()).select_from(MediaAsset)) or 0
    if total == 0:
        return [], 0

    stride = max(1, limit)
    max_offset = max(0, ((total - 1) // stride) * stride)
    safe_offset = min(offset, max_offset)

    stmt = (
        select(MediaAsset)
        .order_by(asc(MediaAsset.title))
        .offset(safe_offset)
        .limit(limit)
    )
    records = db.scalars(stmt).all()
    return [_to_media_item(item) for item in records], total


async def create_media(
    db: Session,
    *,
    title: str,
    genre: str,
    duration_seconds: int,
    upload: UploadFile,
) -> MediaItem:
    """Persist an uploaded media file and return its metadata."""

    destination: Path | None = None
    metadata = None
    try:
        destination, _received, checksum, _mime = await _save_upload_securely(upload)
        metadata = await metadata_extractor.extract_metadata(destination)

        asset = MediaAsset(
            title=metadata.title or title,
            genre=genre or metadata.genre or "unknown",
            duration_seconds=metadata.duration_seconds or duration_seconds,
            file_path=str(destination),
            checksum=checksum,
            width=metadata.width,
            height=metadata.height,
            video_codec=metadata.video_codec,
            audio_codec=metadata.audio_codec,
            bitrate=metadata.bitrate,
            frame_rate=metadata.frame_rate,
            thumbnail_path=metadata.thumbnail_path,
        )
        db.add(asset)
        db.flush()
        db.commit()

        return _to_media_item(asset)
    except Exception:
        db.rollback()
        if destination and destination.exists():
            destination.unlink(missing_ok=True)
        if metadata and metadata.thumbnail_path:
            try:
                thumb_path = Path(metadata.thumbnail_path)
                thumb_path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning(
                    "Failed to remove thumbnail during rollback",
                    extra={"thumbnail": metadata.thumbnail_path, "error": str(exc)},
                )
        raise


def _to_media_item(item: MediaAsset) -> MediaItem:
    return MediaItem(
        id=item.id,
        title=item.title,
        genre=item.genre,
        duration_seconds=item.duration_seconds,
        file_path=item.file_path,
        created_at=item.created_at,
        width=item.width,
        height=item.height,
        video_codec=item.video_codec,
        audio_codec=item.audio_codec,
        bitrate=item.bitrate,
        frame_rate=item.frame_rate,
        thumbnail_path=item.thumbnail_path,
    )
