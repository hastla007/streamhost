"""Media library endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import MediaList, MediaUploadMetadata, UploadResponse
from app.services import media_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("", response_model=MediaList)
def list_media(db: Session = Depends(get_db)) -> MediaList:
    """Return the available media entries."""

    items = media_service.list_media(db)
    return MediaList(items=items)


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_protect)])
async def upload_media(
    title: str = Form(...),
    genre: str = Form(...),
    duration_seconds: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Validate and accept a media upload."""

    metadata = MediaUploadMetadata(title=title, genre=genre, duration_seconds=duration_seconds)
    media_item = await media_service.create_media(
        db,
        title=metadata.title,
        genre=metadata.genre,
        duration_seconds=metadata.duration_seconds,
        upload=file,
    )
    return UploadResponse(message="Media accepted for processing", media_item=media_item)
