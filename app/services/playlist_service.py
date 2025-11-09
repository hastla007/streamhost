"""Playlist persistence helpers."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import asc, func, select, text
from sqlalchemy.orm import Session

from app.models import MediaAsset, PlaylistEntry
from app.schemas import PlaylistCreate, PlaylistGenerationRequest, PlaylistItem
from app.services.playlist_scheduler import playlist_scheduler


def list_playlist(db: Session, *, limit: int | None = None, offset: int = 0) -> list[PlaylistItem]:
    stmt = (
        select(PlaylistEntry)
        .order_by(asc(PlaylistEntry.position), asc(PlaylistEntry.id))
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    entries = db.execute(stmt).scalars().all()
    return _serialize_entries(entries)


def paginate_playlist(db: Session, *, limit: int, offset: int) -> tuple[list[PlaylistItem], int]:
    items = list_playlist(db, limit=limit, offset=offset)
    total = db.scalar(select(func.count()).select_from(PlaylistEntry)) or 0
    return items, total


def count_playlist(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(PlaylistEntry)) or 0


def add_playlist_item(db: Session, payload: PlaylistCreate) -> PlaylistItem:
    media = None
    if payload.media_id is not None:
        media = db.get(MediaAsset, payload.media_id)
    if media is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Media item must be provided")

    position = _current_max_position(db)
    entry = PlaylistEntry(
        media_id=media.id,
        scheduled_start=payload.scheduled_start,
        position=position,
    )
    db.add(entry)
    db.flush()

    return PlaylistItem(
        id=entry.id,
        media_id=media.id,
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


def generate_playlist(db: Session, request: PlaylistGenerationRequest) -> list[PlaylistItem]:
    """Generate and persist a long-running playlist based on strategy rules."""

    planned_items = playlist_scheduler.generate_playlist(db, request)
    if not planned_items:
        return []

    position = _current_max_position(db)
    created: list[PlaylistItem] = []

    for offset, item in enumerate(planned_items):
        media = db.get(MediaAsset, item.media_id)
        if media is None:
            continue
        entry = PlaylistEntry(
            media_id=media.id,
            scheduled_start=item.scheduled_start,
            position=position + offset,
        )
        db.add(entry)
        db.flush()

        created.append(
            PlaylistItem(
                id=entry.id,
                media_id=media.id,
                title=media.title,
                genre=media.genre,
                duration_seconds=media.duration_seconds,
                scheduled_start=entry.scheduled_start,
            )
        )

    return created


def _current_max_position(db: Session) -> int:
    """Return the next available playlist position using a locked query."""

    result = db.execute(
        text("SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_entry FOR UPDATE")
    ).scalar()
    next_position = int(result) if result is not None else 1
    return next_position


def _serialize_entries(entries: list[PlaylistEntry]) -> list[PlaylistItem]:
    return [
        PlaylistItem(
            id=entry.id,
            media_id=entry.media_id,
            title=entry.media.title,
            genre=entry.media.genre,
            duration_seconds=entry.media.duration_seconds,
            scheduled_start=entry.scheduled_start,
        )
        for entry in entries
        if entry.media
    ]
