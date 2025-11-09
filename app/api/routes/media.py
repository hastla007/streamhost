"""Media library endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import enforce_rate_limit
from app.schemas import DEFAULT_ERROR_RESPONSES, MediaList, MediaUploadMetadata, UploadResponse
from app.services import media_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("", response_model=MediaList, responses=DEFAULT_ERROR_RESPONSES)
def list_media(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> MediaList:
    """Return the available media entries."""

    items, total = media_service.paginate_media(db, limit=limit, offset=offset)
    return MediaList(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses=DEFAULT_ERROR_RESPONSES,
)
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
