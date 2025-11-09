import asyncio
import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-please-change-1234567890")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-please-change-1234567890")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "Test-Admin-Password-123!")

from app.db.base import Base


@pytest.fixture()
def in_memory_db() -> Generator[Session, None, None]:
    """Provide an isolated in-memory database session for tests."""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSession()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a fresh event loop for each test module."""

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture()
def anyio_backend():
    """Restrict AnyIO-based tests to asyncio only."""

    return "asyncio"
