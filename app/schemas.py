"""Pydantic models shared between the API and templates."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator
from starlette import status


class StreamMetrics(BaseModel):
    """Real-time telemetry emitted by the streaming pipeline."""

    frame: int = Field(0, ge=0)
    fps: float = Field(0.0, ge=0.0)
    bitrate_kbps: int = Field(0, ge=0)
    speed: float = Field(0.0, ge=0.0)
    dropped_frames: int = Field(0, ge=0)
    buffer_level_seconds: Optional[float] = Field(None, ge=0.0)


class StreamStatus(BaseModel):
    status: Literal["online", "offline", "starting", "error"]
    uptime_seconds: int = Field(ge=0)
    encoder: str
    target: Optional[str]
    playlist_id: Optional[int]
    started_at: Optional[datetime]
    last_error: Optional[str]
    metrics: StreamMetrics
    last_updated: datetime


class Token(BaseModel):
    access_token: str
    token_type: str


class Alert(BaseModel):
    level: Literal["ok", "warning", "critical"]
    message: str
    timestamp: datetime


class PlaylistItem(BaseModel):
    id: int
    media_id: int
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
    total: int
    limit: int
    offset: int


class MediaMetadata(BaseModel):
    """Extracted metadata for a media asset."""

    duration_seconds: int
    width: Optional[int]
    height: Optional[int]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    bitrate: Optional[int]
    frame_rate: Optional[str]
    thumbnail_path: Optional[str]
    title: Optional[str]
    year: Optional[int]
    genre: Optional[str]


class MediaItem(BaseModel):
    id: int
    title: str
    genre: str
    duration_seconds: int
    file_path: str
    created_at: datetime
    width: Optional[int] = None
    height: Optional[int] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bitrate: Optional[int] = None
    frame_rate: Optional[str] = None
    thumbnail_path: Optional[str] = None


class MediaList(BaseModel):
    items: list[MediaItem]
    total: int
    limit: int
    offset: int


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


class ErrorResponse(BaseModel):
    detail: str


DEFAULT_ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
}


class PlaylistRules(BaseModel):
    """Rules that guide playlist generation."""

    min_gap_between_repeats_hours: int = Field(24, ge=0)
    max_consecutive_same_genre: int = Field(2, ge=1)
    enable_shuffle: bool = True
    enable_scheduled_content: bool = True
    scheduled_events: list[dict[str, Any]] = Field(default_factory=list)


class PlaylistGenerationRequest(BaseModel):
    """Request payload for generating long-running playlists."""

    strategy: Literal["balanced", "genre-rotation", "popularity", "time-of-day"] = "balanced"
    hours: int = Field(24, gt=0, le=168)
    timezone: Optional[str] = None
    rules: PlaylistRules | None = None


class HealthStatus(BaseModel):
    """Aggregated health information for stream monitoring."""

    checks: dict[str, bool]
    metrics: dict[str, float | int]
    issues: list[str] = Field(default_factory=list)
    severity: Literal["ok", "warning", "critical"]

    @property
    def is_critical(self) -> bool:
        return self.severity == "critical"

    @property
    def summary(self) -> str:
        failing = [name for name, healthy in self.checks.items() if not healthy]
        if not failing:
            return "Stream healthy"
        return ", ".join(failing)
