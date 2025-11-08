"""Logging configuration for StreamHost."""
from __future__ import annotations

import logging.config
from typing import Dict, Any


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

    logging.config.dictConfig(LOGGING_CONFIG)
