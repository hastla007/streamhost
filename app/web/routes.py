"""Server-rendered pages for the StreamHost dashboard."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status
from starlette.templating import Jinja2Templates

from app.core.database import get_db
from app.core.security import form_csrf_protect, generate_csrf_token
from app.schemas import PlaylistCreate, SystemSettings
from app.models import MediaAsset
from app.services import media_service, playlist_service, settings_service, stream_monitor
from app.services.stream_manager import stream_manager

router = APIRouter()

templates = Jinja2Templates(directory="app/web/templates")


def _common_context(request: Request) -> dict:
    csrf_token = request.session.get("_csrf_token") or generate_csrf_token(request)
    return {
        "request": request,
        "csrf_token": csrf_token,
    }


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    playlist_preview = playlist_service.list_playlist(db)[:3]
    stream = await stream_manager.status()
    context.update(
        {
            "stream": stream,
            "alerts": [],
            "playlist": playlist_preview,
            "uptime_hours": round(stream.uptime_seconds / 3600, 2),
        }
    )
    return templates.TemplateResponse("home.html", context)


@router.get("/playlist", response_class=HTMLResponse)
def playlist(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    context.update({"playlist": playlist_service.list_playlist(db), "media": media_service.list_media(db)})
    return templates.TemplateResponse("playlist.html", context)


@router.post("/playlist", status_code=status.HTTP_303_SEE_OTHER)
async def playlist_submit(
    request: Request,
    media_id: Annotated[int, Form(ge=1)],
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    asset = db.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    payload = PlaylistCreate(
        title=asset.title,
        genre=asset.genre,
        duration_seconds=asset.duration_seconds,
        media_id=asset.id,
    )
    playlist_service.add_playlist_item(db, payload)
    return RedirectResponse(url="/playlist", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/playlist/remove", status_code=status.HTTP_303_SEE_OTHER)
async def playlist_remove(
    request: Request,
    item_id: Annotated[int, Form(ge=1)],
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    playlist_service.remove_playlist_item(db, item_id)
    return RedirectResponse(url="/playlist", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/media", response_class=HTMLResponse)
def media(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    context.update({"media": media_service.list_media(db)})
    return templates.TemplateResponse("media.html", context)


@router.post("/media/upload", status_code=status.HTTP_303_SEE_OTHER)
async def media_upload(
    request: Request,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    genre: Annotated[str, Form(min_length=1, max_length=64)],
    duration_minutes: Annotated[int, Form(ge=1, le=600)],
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    await media_service.create_media(
        db,
        title=title,
        genre=genre,
        duration_seconds=duration_minutes * 60,
        upload=file,
    )
    return RedirectResponse(url="/media", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    context.update({"settings": settings_service.get_settings(db)})
    return templates.TemplateResponse("settings.html", context)


@router.post("/settings", status_code=status.HTTP_303_SEE_OTHER)
async def settings_submit(
    request: Request,
    stream_resolution: Annotated[str, Form(min_length=3, max_length=32)],
    stream_bitrate: Annotated[int, Form(ge=500, le=20_000)],
    stream_fps: Annotated[int, Form(ge=15, le=120)],
    hardware_accel: Annotated[str, Form(min_length=2, max_length=32)],
    contact_email: Annotated[str, Form(min_length=5, max_length=255)],
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    payload = SystemSettings(
        stream_resolution=stream_resolution,
        stream_bitrate=stream_bitrate,
        stream_fps=stream_fps,
        hardware_accel=hardware_accel,
        contact_email=contact_email,
    )
    settings_service.update_settings(db, payload)
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/monitor", response_class=HTMLResponse)
async def monitor(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    stream = await stream_manager.status()
    health = await stream_monitor.check_stream_health()
    await stream_monitor.alert_if_needed(health)
    context.update(
        {
            "stream": stream,
            "health": health,
            "preview_url": "/api/v1/stream/preview.m3u8",
        }
    )
    return templates.TemplateResponse("monitor.html", context)
