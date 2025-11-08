"""Media library endpoints."""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import MediaItem, MediaList, MediaUploadMetadata, UploadResponse
from app.services.state import app_state, deque_counter

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("", response_model=MediaList)
def list_media() -> MediaList:
    """Return the available media entries."""

    return MediaList(items=list(app_state.media))


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_protect)])
async def upload_media(
    title: str = Form(...),
    genre: str = Form(...),
    duration_seconds: int = Form(...),
    file: UploadFile = File(...),
) -> UploadResponse:
    """Validate and accept a media upload."""

    if not file.content_type or not file.content_type.startswith("video/"):
        app_state.record_failure(f"Unsupported content type: {file.content_type}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only video uploads are supported")

    max_bytes = settings.max_upload_bytes
    received = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            app_state.record_failure(f"Upload exceeds limit: {file.filename}")
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload exceeds configured limit")

    metadata = MediaUploadMetadata(title=title, genre=genre, duration_seconds=duration_seconds)

    media_item = MediaItem(
        id=next(deque_counter),
        title=metadata.title,
        genre=metadata.genre,
        duration_seconds=metadata.duration_seconds,
        file_path=os.path.join("/data/movies", file.filename or "upload"),
        created_at=datetime.utcnow(),
    )
    app_state.media.append(media_item)
    return UploadResponse(message="Media accepted for processing", media_item=media_item)
