"""System configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import csrf_protect, enforce_rate_limit
from app.schemas import SettingsResponse, SystemSettings
from app.services.state import app_state

router = APIRouter(dependencies=[Depends(enforce_rate_limit)])


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """Return the currently active configuration snapshot."""

    return SettingsResponse(settings=app_state.settings)


@router.put("/settings", response_model=SettingsResponse, dependencies=[Depends(csrf_protect)])
def update_settings(payload: SystemSettings) -> SettingsResponse:
    """Persist new configuration values."""

    updated = app_state.update_settings(payload)
    return SettingsResponse(settings=updated)
