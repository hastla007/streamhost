"""Pydantic models shared between the API and templates."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class StreamStatus(BaseModel):
    status: Literal["online", "offline", "starting"]
    bitrate_kbps: int = Field(ge=0)
    uptime_seconds: int = Field(ge=0)
    encoder: str
    dropped_frames: int = Field(ge=0)
    last_updated: datetime


class Alert(BaseModel):
    level: Literal["ok", "warning", "critical"]
    message: str
    timestamp: datetime


class PlaylistItem(BaseModel):
    id: int
    title: str
    genre: str
    duration_seconds: int = Field(ge=0)
    scheduled_start: Optional[datetime]


class PlaylistCreate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=120)
    genre: Optional[str] = Field(None, min_length=2, max_length=40)
    duration_seconds: Optional[int] = Field(None, gt=0, lt=12 * 3600)
    scheduled_start: Optional[datetime] = None
    media_id: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_payload(self) -> "PlaylistCreate":
        if self.media_id is None:
            if not all([self.title, self.genre, self.duration_seconds]):
                raise ValueError(
                    "title, genre, and duration_seconds are required when media_id is not provided"
                )
        return self


class PlaylistResponse(BaseModel):
    items: list[PlaylistItem]


class MediaItem(BaseModel):
    id: int
    title: str
    genre: str
    duration_seconds: int
    file_path: str
    created_at: datetime


class MediaList(BaseModel):
    items: list[MediaItem]


class MediaUploadMetadata(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    genre: str = Field(min_length=2, max_length=40)
    duration_seconds: int = Field(gt=0, lt=12 * 3600)


class SystemSettings(BaseModel):
    stream_resolution: str
    stream_bitrate: int = Field(gt=0)
    stream_fps: int = Field(gt=0, lt=145)
    hardware_accel: str
    contact_email: EmailStr


class SettingsResponse(BaseModel):
    settings: SystemSettings


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    timestamp: datetime


class UploadResponse(BaseModel):
    message: str
    media_item: MediaItem
