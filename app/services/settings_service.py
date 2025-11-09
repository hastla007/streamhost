"""Persisted system settings service."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting
from app.schemas import SystemSettings


def get_settings(db: Session) -> SystemSettings:
    settings_row = db.scalar(select(SystemSetting).limit(1))
    if not settings_row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Settings not initialised")
    return SystemSettings(
        stream_resolution=settings_row.stream_resolution,
        stream_bitrate=settings_row.stream_bitrate,
        stream_fps=settings_row.stream_fps,
        hardware_accel=settings_row.hardware_accel,
        contact_email=settings_row.contact_email,
    )


def update_settings(db: Session, payload: SystemSettings) -> SystemSettings:
    settings_row = db.scalar(select(SystemSetting).limit(1))
    try:
        if not settings_row:
            settings_row = SystemSetting(**payload.model_dump())
            db.add(settings_row)
        else:
            for key, value in payload.model_dump().items():
                setattr(settings_row, key, value)
        db.flush()
        db.commit()
        db.refresh(settings_row)
    except Exception:
        db.rollback()
        raise

    return SystemSettings(
        stream_resolution=settings_row.stream_resolution,
        stream_bitrate=settings_row.stream_bitrate,
        stream_fps=settings_row.stream_fps,
        hardware_accel=settings_row.hardware_accel,
        contact_email=settings_row.contact_email,
    )
