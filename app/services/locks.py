"""Shared lock instances for service coordination."""
from __future__ import annotations

from app.core.config import settings
from app.utils import ObservedLock

preview_directory_lock = ObservedLock(
    "preview_directory_lock", default_timeout=settings.lock_acquire_timeout_seconds
)

__all__ = ["preview_directory_lock"]
