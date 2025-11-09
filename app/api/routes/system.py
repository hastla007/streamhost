"""System configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import enforce_rate_limit
from app.schemas import DEFAULT_ERROR_RESPONSES, SettingsResponse, SystemSettings
from app.services import settings_service
from app.services.cleanup import cleanup_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("/settings", response_model=SettingsResponse, responses=DEFAULT_ERROR_RESPONSES)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    """Return the currently active configuration snapshot."""

    settings = settings_service.get_settings(db)
    return SettingsResponse(settings=settings)


@router.put(
    "/settings",
    response_model=SettingsResponse,
    responses=DEFAULT_ERROR_RESPONSES,
)
def update_settings(payload: SystemSettings, db: Session = Depends(get_db)) -> SettingsResponse:
    """Persist new configuration values."""

    updated = settings_service.update_settings(db, payload)
    return SettingsResponse(settings=updated)

@router.get("/cleanup/stats", responses=DEFAULT_ERROR_RESPONSES)
def cleanup_stats() -> dict[str, dict[str, float]]:
    """Return current cleanup directory statistics."""

    return cleanup_service.get_directory_stats()


@router.post("/cleanup/run", responses=DEFAULT_ERROR_RESPONSES)
async def cleanup_run() -> dict[str, int]:
    """Trigger an on-demand cleanup cycle."""

    return await cleanup_service.cleanup_all()
