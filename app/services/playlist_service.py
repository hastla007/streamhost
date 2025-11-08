"""Playlist persistence helpers."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.models import MediaAsset, PlaylistEntry
from app.schemas import PlaylistCreate, PlaylistItem


def list_playlist(db: Session) -> list[PlaylistItem]:
    entries = (
        db.execute(select(PlaylistEntry).order_by(asc(PlaylistEntry.position), asc(PlaylistEntry.id)))
        .scalars()
        .all()
    )
    return [
        PlaylistItem(
            id=entry.id,
            title=entry.media.title,
            genre=entry.media.genre,
            duration_seconds=entry.media.duration_seconds,
            scheduled_start=entry.scheduled_start,
        )
        for entry in entries
        if entry.media
    ]


def add_playlist_item(db: Session, payload: PlaylistCreate) -> PlaylistItem:
    media = None
    if payload.media_id is not None:
        media = db.get(MediaAsset, payload.media_id)
    if media is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media item must be provided")

    position = db.scalar(select(PlaylistEntry.position).order_by(PlaylistEntry.position.desc())) or 0
    entry = PlaylistEntry(
        media_id=media.id,
        scheduled_start=payload.scheduled_start,
        position=position + 1,
    )
    db.add(entry)
    db.flush()

    return PlaylistItem(
        id=entry.id,
        title=media.title,
        genre=media.genre,
        duration_seconds=media.duration_seconds,
        scheduled_start=entry.scheduled_start,
    )


def remove_playlist_item(db: Session, item_id: int) -> None:
    entry = db.get(PlaylistEntry, item_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    db.delete(entry)
    db.flush()
