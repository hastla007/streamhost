"""Playlist persistence helpers."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import asc, func, select, text
from sqlalchemy.exc import SQLAlchemyError
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
    total = db.scalar(select(func.count()).select_from(PlaylistEntry)) or 0
    max_offset = max(0, total - 1)
    safe_offset = min(offset, max_offset)

    items = list_playlist(db, limit=limit, offset=safe_offset)
    return items, total


def count_playlist(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(PlaylistEntry)) or 0


def add_playlist_item(db: Session, payload: PlaylistCreate) -> PlaylistItem:
    if payload.media_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="media_id is required")

    media = db.get(MediaAsset, payload.media_id)
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    try:
        position = _reserve_next_position(db)
        entry = PlaylistEntry(
            media_id=media.id,
            scheduled_start=payload.scheduled_start,
            position=position,
        )
        db.add(entry)
        db.flush()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

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
    try:
        db.delete(entry)
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise


def generate_playlist(db: Session, request: PlaylistGenerationRequest) -> list[PlaylistItem]:
    """Generate and persist a long-running playlist based on strategy rules."""

    planned_items = playlist_scheduler.generate_playlist(db, request)
    if not planned_items:
        return []

    created: list[PlaylistItem] = []

    try:
        next_position = _reserve_next_position(db)

        for item in planned_items:
            media = db.get(MediaAsset, item.media_id)
            if media is None:
                continue
            position = next_position
            next_position += 1
            entry = PlaylistEntry(
                media_id=media.id,
                scheduled_start=item.scheduled_start,
                position=position,
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

        db.commit()
    except Exception:
        db.rollback()
        raise

    return created


def _reserve_next_position(db: Session) -> int:
    """Return the next available playlist position using a locked query."""

    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "")
    # Serialise concurrent callers with FOR UPDATE when the backend supports it.
    # SQLite ignores locking hints, so we omit it there to avoid syntax errors.
    base_query = "SELECT position FROM playlist_entry ORDER BY position DESC LIMIT 1"
    if dialect_name and dialect_name != "sqlite":
        base_query += " FOR UPDATE"

    result = db.execute(text(base_query)).scalar()

    if result is None:
        return 1

    return int(result) + 1


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
