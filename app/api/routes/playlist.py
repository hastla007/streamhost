"""Playlist management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import PlaylistCreate, PlaylistItem, PlaylistResponse
from app.services import playlist_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("", response_model=PlaylistResponse)
def list_playlist(db: Session = Depends(get_db)) -> PlaylistResponse:
    """Return the upcoming playlist items."""

    items = playlist_service.list_playlist(db)
    return PlaylistResponse(items=items)


@router.post(
    "",
    response_model=PlaylistItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_protect)],
)
def add_playlist_item(payload: PlaylistCreate, db: Session = Depends(get_db)) -> PlaylistItem:
    """Add a new item to the playlist queue."""

    return playlist_service.add_playlist_item(db, payload)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(csrf_protect)],
)
def delete_playlist_item(item_id: int, db: Session = Depends(get_db)) -> None:
    """Remove an item from the playlist if it exists."""

    playlist_service.remove_playlist_item(db, item_id)
