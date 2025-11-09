"""Database connection and session management utilities."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool

from app.core.config import settings

logger = logging.getLogger(__name__)

POOL_SIZE = 10
MAX_OVERFLOW = 20
POOL_TIMEOUT = 30
POOL_RECYCLE = 3600
POOL_PRE_PING = True


def _create_engine():
    is_sqlite = settings.database_url.startswith("sqlite")

    if is_sqlite:
        engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            echo=settings.debug,
            future=True,
        )
    else:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=POOL_PRE_PING,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            echo=settings.debug,
            future=True,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000",
            },
        )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, connection_record):  # pragma: no cover - instrumentation
        logger.debug("Database connection established")

    @event.listens_for(engine, "checkout")
    def _on_checkout(dbapi_conn, connection_record, connection_proxy):  # pragma: no cover - instrumentation
        pool: Pool = connection_proxy._pool
        checked_out = pool.checkedout()
        total = POOL_SIZE + MAX_OVERFLOW
        if checked_out >= total - 2:
            logger.warning(
                "Database connection pool nearly exhausted",
                extra={"checked_out": checked_out, "max": total},
            )

    @event.listens_for(engine, "checkin")
    def _on_checkin(dbapi_conn, connection_record):  # pragma: no cover - instrumentation
        logger.debug("Database connection returned to pool")

    return engine


def get_pool_status() -> dict[str, int]:
    pool = engine.pool
    return {
        "size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "max_size": POOL_SIZE + MAX_OVERFLOW,
    }


def check_pool_health() -> tuple[bool, str]:
    try:
        status = get_pool_status()
        utilisation = status["checked_out"] / status["max_size"] if status["max_size"] else 0
        if utilisation > 0.9:
            return False, f"Pool {utilisation:.0%} utilised ({status['checked_out']}/{status['max_size']})"
        if utilisation > 0.7:
            return True, f"Pool {utilisation:.0%} utilised (warning threshold)"
        return True, f"Pool healthy ({status['checked_out']}/{status['max_size']} in use)"
    except Exception as exc:  # pragma: no cover - instrumentation
        return False, f"Failed to inspect pool: {exc}"


def _log_and_raise(exc: Exception) -> None:
    logger.error("Database transaction rolled back", extra={"error": str(exc)})


def _session_factory():
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
        expire_on_commit=False,
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception as exc:
        db.rollback()
        _log_and_raise(exc)
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
        except Exception:
            pass
        finally:
            db.close()


@contextmanager
def get_db_context(*, commit_on_exit: bool = False) -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        if commit_on_exit:
            db.commit()
    except Exception as exc:
        db.rollback()
        _log_and_raise(exc)
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
        except Exception:
            pass
        finally:
            db.close()


engine = _create_engine()
SessionLocal = _session_factory()
