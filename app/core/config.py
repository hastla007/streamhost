"""Application configuration management."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class Settings(BaseModel):
    """Runtime configuration values for the StreamHost service."""

    app_env: str = Field("development", validation_alias="APP_ENV")
    debug: bool = Field(False, validation_alias="DEBUG")
    secret_key: str = Field(..., validation_alias="SECRET_KEY")

    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    postgres_db: str = Field("moviestream", validation_alias="POSTGRES_DB")
    postgres_user: str = Field("streamadmin", validation_alias="POSTGRES_USER")
    postgres_password: str = Field("please-change-me", validation_alias="POSTGRES_PASSWORD")
    postgres_host: str = Field("localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, validation_alias="POSTGRES_PORT")

    redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
        ],
        validation_alias="CORS_ORIGINS",
    )

    youtube_stream_key: Optional[str] = Field(None, validation_alias="YOUTUBE_STREAM_KEY")
    youtube_rtmp_url: Optional[str] = Field(None, validation_alias="YOUTUBE_RTMP_URL")

    stream_resolution: str = Field("1920x1080", validation_alias="STREAM_RESOLUTION")
    stream_bitrate: int = Field(4000, validation_alias="STREAM_BITRATE")
    stream_fps: int = Field(30, validation_alias="STREAM_FPS")
    stream_hardware_accel: str = Field("auto", validation_alias="STREAM_HARDWARE_ACCEL")

    alert_email: str = Field("admin@example.com", validation_alias="ALERT_EMAIL")
    sentry_dsn: Optional[str] = Field(None, validation_alias="SENTRY_DSN")
    prometheus_port: int = Field(9090, validation_alias="PROMETHEUS_PORT")

    jwt_secret: str = Field("change-me", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(60, validation_alias="JWT_EXPIRY_MINUTES")
    admin_default_password: str = Field("changeme", validation_alias="ADMIN_DEFAULT_PASSWORD")

    rate_limit_requests: int = Field(60, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(60, validation_alias="RATE_LIMIT_WINDOW")
    preview_rate_limit_requests: int = Field(30, validation_alias="PREVIEW_RATE_LIMIT_REQUESTS")
    preview_rate_limit_window: int = Field(60, validation_alias="PREVIEW_RATE_LIMIT_WINDOW")
    csrf_token_ttl_seconds: int = Field(2 * 60 * 60, validation_alias="CSRF_TOKEN_TTL_SECONDS")
    rate_limit_max_keys: int = Field(10_000, validation_alias="RATE_LIMIT_MAX_KEYS")
    max_upload_mb: int = Field(512, validation_alias="MAX_UPLOAD_MB", gt=0)
    media_root: str = Field(str(BASE_DIR / "data" / "movies"), validation_alias="MOVIES_DIR")
    log_dir: str = Field(str(BASE_DIR / "data" / "logs"), validation_alias="LOGS_DIR")
    log_max_bytes: int = Field(10 * 1024 * 1024, validation_alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(5, validation_alias="LOG_BACKUP_COUNT")

    stream_restart_base_delay: int = Field(5, validation_alias="STREAM_RESTART_BASE_DELAY")
    stream_restart_max_delay: int = Field(300, validation_alias="STREAM_RESTART_MAX_DELAY")
    stream_restart_max_attempts: int = Field(10, validation_alias="STREAM_RESTART_MAX_ATTEMPTS")
    stream_restart_strategy: str = Field("exponential", validation_alias="STREAM_RESTART_STRATEGY")
    stream_preview_segment_seconds: int = Field(4, validation_alias="STREAM_PREVIEW_SEGMENT_SECONDS")

    class Config:
        populate_by_name = True

    _email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[str, list[str], None]) -> list[str]:
        if isinstance(value, str):
            parts = [origin.strip() for origin in value.split(",")]
            return [origin for origin in parts if origin]
        if value is None:
            return []
        return list(value)

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

    @field_validator("alert_email")
    @classmethod
    def validate_alert_email(cls, value: str) -> str:
        """Basic validation for alert email addresses without external deps."""

        if not cls._email_pattern.match(value):
            raise ValueError("ALERT_EMAIL must be a valid email address")
        return value

    @model_validator(mode="after")
    def ensure_database_url(self) -> "Settings":
        """Construct a PostgreSQL URL when one is not explicitly provided."""

        if self.database_url:
            return self

        if not self.postgres_password:
            raise ValueError(
                "DATABASE_URL must be provided or POSTGRES_PASSWORD must be set to build one"
            )

        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        db_name = quote_plus(self.postgres_db)
        self.database_url = (
            f"postgresql+psycopg2://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{db_name}"
        )
        return self

    @model_validator(mode="after")
    def ensure_stream_destination(self) -> "Settings":
        """Validate streaming destination configuration."""

        has_key = bool(self.youtube_stream_key)
        has_url = bool(self.youtube_rtmp_url)

        if has_key != has_url:
            raise ValueError(
                "YOUTUBE_STREAM_KEY and YOUTUBE_RTMP_URL must both be provided or both omitted"
            )

        if self.app_env.lower() == "production" and not (has_key and has_url):
            raise ValueError(
                "Production deployments require YOUTUBE_STREAM_KEY and YOUTUBE_RTMP_URL to be configured"
            )

        if has_url:
            parsed = urlparse(self.youtube_rtmp_url)
            if parsed.scheme not in {"rtmp", "rtmps"} or not parsed.netloc:
                raise ValueError("YOUTUBE_RTMP_URL must be a valid RTMP/RTMPS URL")

        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    overrides: dict[str, Any] = {}
    env_mappings = {
        "secret_key": os.getenv("SECRET_KEY"),
        "jwt_secret": os.getenv("JWT_SECRET"),
        "database_url": os.getenv("DATABASE_URL"),
        "postgres_password": os.getenv("POSTGRES_PASSWORD"),
        "youtube_stream_key": os.getenv("YOUTUBE_STREAM_KEY"),
        "youtube_rtmp_url": os.getenv("YOUTUBE_RTMP_URL"),
    }
    overrides.update({k: v for k, v in env_mappings.items() if v})
    return Settings(**overrides)


settings = get_settings()
