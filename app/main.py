"""FastAPI application entrypoint for StreamHost."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.security import generate_csrf_token
from app.db.init_db import init_database
from app.db.migrate import run_migrations
from app.db.session import SessionLocal
from app.web.routes import router as web_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""

    configure_logging()

    app = FastAPI(title="StreamHost", version="0.1.0", debug=settings.debug)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=12 * 60 * 60,
        same_site="lax",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(api_router)
    app.include_router(web_router)

    @app.middleware("http")
    async def add_csrf_token(request: Request, call_next):  # type: ignore[override]
        """Ensure each session has a CSRF token."""

        if request.session.get("_csrf_token") is None:
            generate_csrf_token(request)
        response = await call_next(request)
        return response

    @app.on_event("startup")
    def startup() -> None:
        """Initialise database schema and defaults."""

        run_migrations()
        with SessionLocal() as db:
            init_database(db)
            db.commit()

    logger.info("StreamHost application initialised", extra={"env": settings.app_env})
    return app


app = create_app()
