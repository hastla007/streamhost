"""Server-rendered pages for the StreamHost dashboard."""
from __future__ import annotations

import math
from typing import Annotated

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status
from starlette.templating import Jinja2Templates

from app.core.database import get_db
from app.core.security import form_csrf_protect, generate_csrf_token
from app.core.types import BaseContext, PaginationInfo
from app.schemas import PlaylistCreate, SystemSettings
from app.models import MediaAsset
from app.services import media_service, playlist_service, settings_service, stream_monitor
from app.services.stream_manager import stream_manager

router = APIRouter()

templates = Jinja2Templates(directory="app/web/templates")


def _common_context(request: Request) -> BaseContext:
    token = generate_csrf_token(request)
    return BaseContext(request=request, csrf_token=token, current_year=datetime.now().year)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _common_context(request)
    playlist_preview = playlist_service.list_playlist(db, limit=3)
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
def playlist(
    request: Request,
    playlist_page: Annotated[int, Query(ge=1, alias="playlist_page")] = 1,
    playlist_page_size: Annotated[int, Query(ge=1, le=200, alias="playlist_page_size")] = 25,
    media_page: Annotated[int, Query(ge=1, alias="media_page")] = 1,
    media_page_size: Annotated[int, Query(ge=1, le=100, alias="media_page_size")] = 25,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = _common_context(request)
    playlist_offset = (playlist_page - 1) * playlist_page_size
    playlist_items, playlist_total = playlist_service.paginate_playlist(
        db, limit=playlist_page_size, offset=playlist_offset
    )
    playlist_pages = max(1, math.ceil(playlist_total / playlist_page_size))

    media_offset = (media_page - 1) * media_page_size
    media_items, media_total = media_service.paginate_media(
        db, limit=media_page_size, offset=media_offset
    )
    media_pages = max(1, math.ceil(media_total / media_page_size))

    playlist_pagination: PaginationInfo = {
        "page": playlist_page,
        "pages": playlist_pages,
        "page_size": playlist_page_size,
        "total": playlist_total,
        "page_param": "playlist_page",
        "size_param": "playlist_page_size",
    }
    media_pagination: PaginationInfo = {
        "page": media_page,
        "pages": media_pages,
        "page_size": media_page_size,
        "total": media_total,
        "page_param": "media_page",
        "size_param": "media_page_size",
    }
    context.update(
        {
            "playlist": playlist_items,
            "playlist_pagination": playlist_pagination,
            "media": media_items,
            "media_pagination": media_pagination,
        }
    )
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
def media(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    context = _common_context(request)
    offset = (page - 1) * page_size
    media_items, total = media_service.paginate_media(db, limit=page_size, offset=offset)
    pages = max(1, math.ceil(total / page_size))
    media_pagination: PaginationInfo = {
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "total": total,
        "page_param": "page",
        "size_param": "page_size",
    }
    context.update(
        {
            "media": media_items,
            "media_pagination": media_pagination,
        }
    )
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
