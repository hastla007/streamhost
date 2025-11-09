"""Database initialisation helpers."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SystemSetting, User
from app.security.passwords import get_password_hash

logger = logging.getLogger(__name__)


def ensure_admin_user(db: Session) -> None:
    """Create a default administrator if none exist."""

    admin_username = "admin"
    existing = db.scalar(select(User).where(User.username == admin_username))
    if existing:
        return

    password = settings.admin_default_password
    user = User(username=admin_username, hashed_password=get_password_hash(password), is_admin=True)
    db.add(user)
    logger.warning("Created default admin user", extra={"username": admin_username})


def ensure_default_settings(db: Session) -> None:
    """Ensure a single row of system settings exists."""

    settings_row = db.scalar(select(SystemSetting).limit(1))
    if settings_row:
        return

    system_settings = SystemSetting(
        stream_resolution=settings.stream_resolution,
        stream_bitrate=settings.stream_bitrate,
        stream_fps=settings.stream_fps,
        hardware_accel=settings.stream_hardware_accel,
        contact_email=settings.alert_email,
    )
    db.add(system_settings)


def init_database(db: Session) -> None:
    """Populate defaults required for the application to start."""

    ensure_admin_user(db)
    ensure_default_settings(db)
    db.flush()
