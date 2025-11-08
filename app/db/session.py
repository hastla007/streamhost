"""Compatibility wrappers around the core database helpers."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine, get_db

__all__ = ["engine", "SessionLocal", "get_db"]


def session_scope() -> Generator[Session, None, None]:
    """Deprecated helper for backwards compatibility."""

    return get_db()
