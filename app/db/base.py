"""SQLAlchemy declarative base and mixins."""
from __future__ import annotations

from datetime import datetime

import re

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, declared_attr, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base class."""


class TimestampMixin:
    """Provides created/updated timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TableNameMixin:
    """Automatically derive table names from class names."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # type: ignore[misc]
        name = cls.__name__
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
