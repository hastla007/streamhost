"""Playlist management endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import enforce_rate_limit
from app.schemas import (
    DEFAULT_ERROR_RESPONSES,
    PlaylistCreate,
    PlaylistGenerationRequest,
    PlaylistItem,
    PlaylistResponse,
)
from app.services import playlist_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("", response_model=PlaylistResponse, responses=DEFAULT_ERROR_RESPONSES)
def list_playlist(
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> PlaylistResponse:
    """Return the upcoming playlist items."""

    items, total = playlist_service.paginate_playlist(db, limit=limit, offset=offset)
    return PlaylistResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=PlaylistItem,
    status_code=status.HTTP_201_CREATED,
    responses=DEFAULT_ERROR_RESPONSES,
)
def add_playlist_item(payload: PlaylistCreate, db: Session = Depends(get_db)) -> PlaylistItem:
    """Add a new item to the playlist queue."""

    return playlist_service.add_playlist_item(db, payload)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_playlist_item(item_id: int, db: Session = Depends(get_db)) -> None:
    """Remove an item from the playlist if it exists."""

    playlist_service.remove_playlist_item(db, item_id)


@router.post(
    "/generate",
    response_model=PlaylistResponse,
    status_code=status.HTTP_201_CREATED,
    responses=DEFAULT_ERROR_RESPONSES,
)
def generate_playlist(payload: PlaylistGenerationRequest, db: Session = Depends(get_db)) -> PlaylistResponse:
    """Generate a playlist using the intelligent scheduler."""

    items = playlist_service.generate_playlist(db, payload)
    total = playlist_service.count_playlist(db)
    offset = max(total - len(items), 0) if items else total
    return PlaylistResponse(items=items, total=total, limit=len(items), offset=offset)
