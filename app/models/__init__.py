"""SQLAlchemy models for the StreamHost backend."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TableNameMixin, TimestampMixin


class User(TableNameMixin, TimestampMixin, Base):
    """Authenticated user account."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MediaAsset(TableNameMixin, TimestampMixin, Base):
    """Media file available for streaming."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    playlist_entries: Mapped[list["PlaylistEntry"]] = relationship(back_populates="media")


class PlaylistEntry(TableNameMixin, TimestampMixin, Base):
    """Entry queued for streaming."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_asset.id", ondelete="CASCADE"), nullable=False)
    scheduled_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    media: Mapped[MediaAsset] = relationship(back_populates="playlist_entries")


class SystemSetting(TableNameMixin, TimestampMixin, Base):
    """Mutable system configuration stored in the database."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_resolution: Mapped[str] = mapped_column(String(32), nullable=False)
    stream_bitrate: Mapped[int] = mapped_column(Integer, nullable=False)
    stream_fps: Mapped[int] = mapped_column(Integer, nullable=False)
    hardware_accel: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)


class StreamSession(TableNameMixin, TimestampMixin, Base):
    """Records of streaming runs."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_id: Mapped[Optional[int]] = mapped_column(ForeignKey("media_asset.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="offline")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    media: Mapped[Optional[MediaAsset]] = relationship()
