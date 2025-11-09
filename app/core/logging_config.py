"""Logging configuration for StreamHost."""
from __future__ import annotations

import copy
import logging.config
from pathlib import Path
from typing import Any, Dict


LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}


def configure_logging() -> None:
    """Apply logging configuration."""

    from app.core.config import settings

    config = copy.deepcopy(LOGGING_CONFIG)
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    config.setdefault("handlers", {})["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "standard",
        "filename": str(log_dir / "streamhost.log"),
        "maxBytes": settings.log_max_bytes,
        "backupCount": settings.log_backup_count,
    }
    config.setdefault("root", {}).setdefault("handlers", ["console"]).append("file")

    logging.config.dictConfig(config)
