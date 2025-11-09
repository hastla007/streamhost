"""Alembic migration runner."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings


def run_migrations() -> None:
    """Apply database migrations using Alembic."""

    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
