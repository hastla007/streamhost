"""FastAPI application entrypoint for StreamHost."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.middleware import CSRFMiddleware, DatabaseCapacityMiddleware, RequestTimeoutMiddleware
from app.core.security import redis_client
from app.core.sessions import (
    SESSION_MAX_AGE,
    ServerSessionMiddleware,
    periodic_session_cleanup,
)
from app.db.init_db import init_database
from app.db.migrate import run_migrations
from app.db.session import SessionLocal
from app.services.cleanup import cleanup_service
from app.web.routes import router as web_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""

    configure_logging()

    app = FastAPI(title="StreamHost", version="0.1.0", debug=settings.debug)

    if redis_client:
        app.add_middleware(ServerSessionMiddleware, redis=redis_client)
    else:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.secret_key,
            max_age=SESSION_MAX_AGE,
            same_site="lax",
        )
    app.add_middleware(CSRFMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    app.add_middleware(RequestTimeoutMiddleware, timeout=settings.request_timeout_seconds)
    app.add_middleware(
        DatabaseCapacityMiddleware,
        threshold=settings.pool_reject_threshold,
    )

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(api_router)
    app.include_router(web_router)

    session_cleanup_task: Optional[asyncio.Task] = None

    @app.on_event("startup")
    async def startup() -> None:
        """Initialise database schema and defaults."""

        attempts = settings.db_migration_max_retries
        base_delay = settings.db_migration_retry_delay_seconds
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                run_migrations()
                last_error = None
                break
            except Exception as exc:  # pragma: no cover - exercised in integration tests
                last_error = exc
                if attempt == attempts:
                    logger.exception(
                        "Database migrations failed after %s attempts", attempts
                    )
                    raise

                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Database migration attempt %s/%s failed; retrying in %.1fs",
                    attempt,
                    attempts,
                    delay,
                    exc_info=exc if settings.debug else None,
                )
                await asyncio.sleep(delay)

        if last_error:
            raise last_error

        with SessionLocal() as db:
            init_database(db)
            db.commit()

        await cleanup_service.start()

        nonlocal session_cleanup_task
        if redis_client:
            session_cleanup_task = asyncio.create_task(periodic_session_cleanup(redis_client))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        """Cleanup background services on shutdown."""

        await cleanup_service.stop()
        if session_cleanup_task:
            session_cleanup_task.cancel()
            try:
                await session_cleanup_task
            except asyncio.CancelledError:
                pass

    logger.info("StreamHost application initialised", extra={"env": settings.app_env})
    return app


app = create_app()
