"""Application configuration management."""
from __future__ import annotations

import logging
import os
import re
import secrets
import string
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from typing import Any, Optional, Union

from sqlalchemy.engine import make_url

from pydantic import BaseModel, Field, field_validator, model_validator
from dotenv import load_dotenv

from app.utils.email_validation import EmailNotValidError, validate_email

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)

logger = logging.getLogger(__name__)


def _generate_secret_key() -> str:
    """Return a cryptographically strong secret key."""

    return secrets.token_urlsafe(64)


def _generate_jwt_secret() -> str:
    """Return a random JWT signing secret."""

    return secrets.token_urlsafe(64)


def _generate_admin_password(length: int = 16) -> str:
    """Generate a strong default administrator password."""

    rng = secrets.SystemRandom()
    symbols = "!@#$%^&*()-_=+"
    base_alphabet = string.ascii_letters + string.digits + symbols

    # Ensure the password meets complexity requirements by seeding one
    # character from each required class before filling the remainder.
    required = [
        rng.choice(string.ascii_lowercase),
        rng.choice(string.ascii_uppercase),
        rng.choice(string.digits),
        rng.choice(symbols),
    ]

    remaining = max(length - len(required), 0)
    password_chars = required + [rng.choice(base_alphabet) for _ in range(remaining)]
    rng.shuffle(password_chars)
    return "".join(password_chars)


def _normalise_directory(path_str: str, *, default: Path, description: str) -> str:
    """Return a writable directory path, falling back when necessary."""

    candidate = Path(path_str).expanduser()
    if not candidate.is_absolute():
        candidate = (BASE_DIR / candidate).resolve()

    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as exc:
        fallback = default.resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Unable to create %s at %s (%s); using fallback %s",
            description,
            candidate,
            exc,
            fallback,
        )
        candidate = fallback

    return str(candidate)


class Settings(BaseModel):
    """Runtime configuration values for the StreamHost service."""

    app_env: str = Field("development", validation_alias="APP_ENV")
    debug: bool = Field(False, validation_alias="DEBUG")
    secret_key: str = Field(default_factory=_generate_secret_key, validation_alias="SECRET_KEY")

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
    stream_bitrate: int = Field(4000, validation_alias="STREAM_BITRATE", gt=0)
    stream_fps: int = Field(30, validation_alias="STREAM_FPS", gt=0)
    stream_hardware_accel: str = Field("auto", validation_alias="STREAM_HARDWARE_ACCEL")

    alert_email: str = Field("admin@example.com", validation_alias="ALERT_EMAIL")
    sentry_dsn: Optional[str] = Field(None, validation_alias="SENTRY_DSN")
    prometheus_port: int = Field(9090, validation_alias="PROMETHEUS_PORT")

    jwt_secret: str = Field(default_factory=_generate_jwt_secret, validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(60, validation_alias="JWT_EXPIRY_MINUTES")
    admin_default_password: str = Field(
        default_factory=_generate_admin_password,
        validation_alias="ADMIN_DEFAULT_PASSWORD",
    )

    rate_limit_requests: int = Field(60, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(60, validation_alias="RATE_LIMIT_WINDOW")
    preview_rate_limit_requests: int = Field(30, validation_alias="PREVIEW_RATE_LIMIT_REQUESTS")
    preview_rate_limit_window: int = Field(60, validation_alias="PREVIEW_RATE_LIMIT_WINDOW")
    csrf_token_ttl_seconds: int = Field(2 * 60 * 60, validation_alias="CSRF_TOKEN_TTL_SECONDS")
    rate_limit_max_keys: int = Field(10_000, validation_alias="RATE_LIMIT_MAX_KEYS")
    request_timeout_seconds: float = Field(30.0, validation_alias="REQUEST_TIMEOUT_SECONDS", ge=0)
    lock_wait_warning_seconds: float = Field(2.0, validation_alias="LOCK_WAIT_WARNING_SECONDS", ge=0)
    lock_hold_warning_seconds: float = Field(10.0, validation_alias="LOCK_HOLD_WARNING_SECONDS", ge=0)
    lock_acquire_timeout_seconds: float = Field(
        10.0,
        validation_alias="LOCK_ACQUIRE_TIMEOUT_SECONDS",
        ge=0,
    )
    max_upload_mb: int = Field(512, validation_alias="MAX_UPLOAD_MB", gt=0)
    media_root: str = Field(str(BASE_DIR / "data" / "movies"), validation_alias="MOVIES_DIR")
    log_dir: str = Field(str(BASE_DIR / "data" / "logs"), validation_alias="LOGS_DIR")
    log_max_bytes: int = Field(10 * 1024 * 1024, validation_alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(5, validation_alias="LOG_BACKUP_COUNT")
    playlist_position_max_retries: int = Field(
        10,
        validation_alias="PLAYLIST_POSITION_MAX_RETRIES",
        ge=1,
    )

    stream_restart_base_delay: int = Field(5, validation_alias="STREAM_RESTART_BASE_DELAY")
    stream_restart_max_delay: int = Field(300, validation_alias="STREAM_RESTART_MAX_DELAY")
    stream_restart_max_attempts: int = Field(10, validation_alias="STREAM_RESTART_MAX_ATTEMPTS")
    stream_restart_strategy: str = Field("exponential", validation_alias="STREAM_RESTART_STRATEGY")
    stream_preview_segment_seconds: int = Field(4, validation_alias="STREAM_PREVIEW_SEGMENT_SECONDS")
    pool_reject_threshold: float = Field(
        0.95,
        validation_alias="POOL_REJECT_THRESHOLD",
        ge=0.0,
        le=1.0,
    )
    db_migration_max_retries: int = Field(
        5,
        validation_alias="DB_MIGRATION_MAX_RETRIES",
        ge=1,
    )
    db_migration_retry_delay_seconds: float = Field(
        2.0,
        validation_alias="DB_MIGRATION_RETRY_DELAY_SECONDS",
        ge=0.0,
    )

    class Config:
        populate_by_name = True

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

    @model_validator(mode="after")
    def normalise_storage_directories(self) -> "Settings":
        """Ensure storage directories are writable within the container."""

        default_media = BASE_DIR / "data" / "movies"
        default_logs = BASE_DIR / "data" / "logs"

        self.media_root = _normalise_directory(
            self.media_root,
            default=default_media,
            description="media storage directory",
        )
        self.log_dir = _normalise_directory(
            self.log_dir,
            default=default_logs,
            description="log directory",
        )
        return self

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
        """Validate alert email addresses using RFC-compliant rules."""

        try:
            validate_email(value, allow_smtputf8=False)
        except EmailNotValidError as exc:
            raise ValueError("ALERT_EMAIL must be a valid email address") from exc
        return value

    @field_validator("stream_resolution")
    @classmethod
    def validate_stream_resolution(cls, value: str) -> str:
        """Ensure stream resolution follows the WIDTHxHEIGHT pattern."""

        pattern = re.compile(r"^(\d{2,5})x(\d{2,5})$")
        match = pattern.match(value.lower())
        if not match:
            raise ValueError("STREAM_RESOLUTION must be formatted as WIDTHxHEIGHT (e.g. 1920x1080)")

        width, height = (int(match.group(1)), int(match.group(2)))
        if width < 320 or height < 240:
            raise ValueError("STREAM_RESOLUTION must be at least 320x240")
        if width > 7680 or height > 4320:
            raise ValueError("STREAM_RESOLUTION must not exceed 7680x4320")

        return f"{width}x{height}"

    @field_validator("stream_bitrate")
    @classmethod
    def validate_stream_bitrate(cls, value: int) -> int:
        """Ensure bitrate is within a sensible range of kilobits per second."""

        if value < 250:
            raise ValueError("STREAM_BITRATE must be at least 250 kbps")
        if value > 200_000:
            raise ValueError("STREAM_BITRATE must be less than or equal to 200000 kbps")
        return value

    @field_validator("stream_fps")
    @classmethod
    def validate_stream_fps(cls, value: int) -> int:
        """Ensure the configured frame rate is within expected bounds."""

        if value < 1 or value > 240:
            raise ValueError("STREAM_FPS must be between 1 and 240")
        return value

    @field_validator("stream_preview_segment_seconds")
    @classmethod
    def validate_preview_segment_seconds(cls, value: int) -> int:
        if value < 1 or value > 30:
            raise ValueError("STREAM_PREVIEW_SEGMENT_SECONDS must be between 1 and 30")
        return value

    @field_validator("admin_default_password")
    @classmethod
    def validate_admin_password(cls, value: str) -> str:
        """Ensure the seeded admin password is rotated from defaults."""

        if value in {"changeme", "change-me", "admin", "password"}:
            raise ValueError("ADMIN_DEFAULT_PASSWORD must be changed from the default value")
        if len(value) < 12:
            raise ValueError("ADMIN_DEFAULT_PASSWORD must be at least 12 characters long")

        classes = {
            "lower": any(char.islower() for char in value),
            "upper": any(char.isupper() for char in value),
            "digit": any(char.isdigit() for char in value),
            "symbol": any(not char.isalnum() for char in value),
        }
        if not all(classes.values()):
            raise ValueError(
                "ADMIN_DEFAULT_PASSWORD must include at least one lowercase letter, "
                "one uppercase letter, one number, and one symbol"
            )
        return value

    @model_validator(mode="after")
    def ensure_database_url(self) -> "Settings":
        """Construct a PostgreSQL URL when one is not explicitly provided."""

        if self.database_url:
            try:
                make_url(self.database_url)
            except Exception as exc:
                raise ValueError(f"DATABASE_URL is invalid: {exc}") from exc
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
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD")
    if admin_password:
        if (
            admin_password not in {"changeme", "change-me", "admin", "password"}
            and len(admin_password) >= 12
            and any(char.islower() for char in admin_password)
            and any(char.isupper() for char in admin_password)
            and any(char.isdigit() for char in admin_password)
            and any(not char.isalnum() for char in admin_password)
        ):
            overrides["admin_default_password"] = admin_password
        else:  # pragma: no cover - defensive logging
            logger.warning(
                "Ignoring weak ADMIN_DEFAULT_PASSWORD from environment; using generated default."
            )
    return Settings(**overrides)


settings = get_settings()
