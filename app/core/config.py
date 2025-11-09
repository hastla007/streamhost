"""Application configuration management."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class Settings(BaseModel):
    """Runtime configuration values for the StreamHost service."""

    app_env: str = Field("development", validation_alias="APP_ENV")
    debug: bool = Field(False, validation_alias="DEBUG")
    secret_key: str = Field(..., validation_alias="SECRET_KEY")

    database_url: str = Field(
        "sqlite:///" + str(BASE_DIR / "data" / "streamhost.db"),
        validation_alias="DATABASE_URL",
    )
    postgres_db: str = Field("moviestream", validation_alias="POSTGRES_DB")
    postgres_user: str = Field("streamadmin", validation_alias="POSTGRES_USER")
    postgres_password: str = Field("", validation_alias="POSTGRES_PASSWORD")

    redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")

    youtube_stream_key: Optional[str] = Field(None, validation_alias="YOUTUBE_STREAM_KEY")
    youtube_rtmp_url: Optional[str] = Field(None, validation_alias="YOUTUBE_RTMP_URL")

    stream_resolution: str = Field("1920x1080", validation_alias="STREAM_RESOLUTION")
    stream_bitrate: int = Field(4000, validation_alias="STREAM_BITRATE")
    stream_fps: int = Field(30, validation_alias="STREAM_FPS")
    stream_hardware_accel: str = Field("auto", validation_alias="STREAM_HARDWARE_ACCEL")

    alert_email: EmailStr = Field("admin@example.com", validation_alias="ALERT_EMAIL")
    sentry_dsn: Optional[str] = Field(None, validation_alias="SENTRY_DSN")
    prometheus_port: int = Field(9090, validation_alias="PROMETHEUS_PORT")

    jwt_secret: str = Field("change-me", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(60, validation_alias="JWT_EXPIRY_MINUTES")
    admin_default_password: str = Field("changeme", validation_alias="ADMIN_DEFAULT_PASSWORD")

    rate_limit_requests: int = Field(60, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(60, validation_alias="RATE_LIMIT_WINDOW")
    max_upload_mb: int = Field(512, validation_alias="MAX_UPLOAD_MB")
    media_root: str = Field(str(BASE_DIR / "data" / "movies"), validation_alias="MOVIES_DIR")

    class Config:
        populate_by_name = True

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        """Ensure the application secret key is strong and customised."""

        if value in {"change-me", "changeme", "secret"}:
            raise ValueError(
                "SECRET_KEY must be changed from the default. "
                "Generate a new key with: openssl rand -base64 32"
            )
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        """Ensure the JWT signing secret is sufficiently strong."""

        if value in {"change-me", "changeme", "secret"}:
            raise ValueError(
                "JWT_SECRET must be changed from the default. "
                "Generate a new key with: openssl rand -base64 32"
            )
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    overrides: dict[str, Any] = {}
    return Settings(**overrides)


settings = get_settings()
