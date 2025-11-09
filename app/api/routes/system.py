"""System configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import SettingsResponse, SystemSettings
from app.services import settings_service

router = APIRouter(dependencies=[Depends(enforce_rate_limit), Depends(get_current_user)])


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    """Return the currently active configuration snapshot."""

    settings = settings_service.get_settings(db)
    return SettingsResponse(settings=settings)


@router.put(
    "/settings",
    response_model=SettingsResponse,
    dependencies=[Depends(csrf_protect)],
)
def update_settings(payload: SystemSettings, db: Session = Depends(get_db)) -> SettingsResponse:
    """Persist new configuration values."""

    updated = settings_service.update_settings(db, payload)
    return SettingsResponse(settings=updated)
