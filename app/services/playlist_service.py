"""Playlist persistence helpers."""
from __future__ import annotations

import logging

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import asc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import MediaAsset, PlaylistEntry, PlaylistPositionCounter
from app.schemas import PlaylistCreate, PlaylistGenerationRequest, PlaylistItem
from app.services.playlist_scheduler import playlist_scheduler

logger = logging.getLogger(__name__)

MAX_POSITION_RETRIES = 5


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
    if total == 0:
        return [], 0

    stride = max(1, limit)
    max_offset = max(0, ((total - 1) // stride) * stride)
    safe_offset = min(offset, max_offset)

    items = list_playlist(db, limit=limit, offset=safe_offset)
    return items, total


def count_playlist(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(PlaylistEntry)) or 0


def add_playlist_item(db: Session, payload: PlaylistCreate) -> PlaylistItem:
    if payload.media_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="media_id is required")

    for attempt in range(MAX_POSITION_RETRIES):
        media = db.get(MediaAsset, payload.media_id)
        if media is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

        try:
            entry = _persist_playlist_entry(
                db,
                media=media,
                scheduled_start=payload.scheduled_start,
            )
            return PlaylistItem(
                id=entry.id,
                media_id=media.id,
                title=media.title,
                genre=media.genre,
                duration_seconds=media.duration_seconds,
                scheduled_start=entry.scheduled_start,
            )
        except IntegrityError as exc:
            db.rollback()
            logger.warning(
                "Detected playlist position race, retrying",  # pragma: no cover - logging only
                extra={
                    "attempt": attempt + 1,
                    "media_id": payload.media_id,
                    "error": str(exc),
                },
            )
        except SQLAlchemyError:
            db.rollback()
            raise

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unable to reserve playlist position after retries",
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

    for item in planned_items:
        entry: PlaylistEntry | None = None
        media: MediaAsset | None = None
        for attempt in range(MAX_POSITION_RETRIES):
            media = db.get(MediaAsset, item.media_id)
            if media is None:
                break
            try:
                entry = _persist_playlist_entry(
                    db,
                    media=media,
                    scheduled_start=item.scheduled_start,
                )
                break
            except IntegrityError as exc:
                db.rollback()
                logger.warning(
                    "Detected playlist position race while generating playlist",  # pragma: no cover - logging only
                    extra={
                        "attempt": attempt + 1,
                        "media_id": media.id,
                        "strategy": request.strategy,
                        "error": str(exc),
                    },
                )
            except SQLAlchemyError:
                db.rollback()
                raise

        if media is None:
            continue

        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to generate playlist due to position contention",
            )

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


def _reserve_next_position(db: Session) -> int:
    """Increment and return the global playlist position counter."""

    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "")
    stmt = select(PlaylistPositionCounter).limit(1)
    if dialect_name != "sqlite":
        stmt = stmt.with_for_update()

    counter = db.execute(stmt).scalars().first()
    if counter is None:
        counter = PlaylistPositionCounter(id=1, value=0)
        db.add(counter)
        db.flush()
        logger.info("Initialised playlist position counter")

    counter.value += 1
    db.flush()
    return counter.value


def _persist_playlist_entry(
    db: Session,
    *,
    media: MediaAsset,
    scheduled_start: datetime | None,
) -> PlaylistEntry:
    """Persist a playlist entry and commit the transaction."""

    position = _reserve_next_position(db)
    entry = PlaylistEntry(
        media_id=media.id,
        scheduled_start=scheduled_start,
        position=position,
    )
    db.add(entry)
    db.flush()
    db.commit()
    return entry


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
