"""Playlist management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import PlaylistCreate, PlaylistItem, PlaylistResponse
from app.services.state import app_state, deque_counter

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("", response_model=PlaylistResponse)
def list_playlist() -> PlaylistResponse:
    """Return the upcoming playlist items."""

    return PlaylistResponse(items=app_state.get_playlist())


@router.post("", response_model=PlaylistItem, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_protect)])
def add_playlist_item(payload: PlaylistCreate) -> PlaylistItem:
    """Add a new item to the playlist queue."""

    item = PlaylistItem(id=next(deque_counter), **payload.model_dump())
    return app_state.add_playlist_item(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)])
def delete_playlist_item(item_id: int) -> None:
    """Remove an item from the playlist if it exists."""

    deleted = app_state.remove_playlist_item(item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
