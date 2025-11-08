"""Server-rendered pages for the StreamHost dashboard."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status
from starlette.templating import Jinja2Templates

from app.core.security import form_csrf_protect, generate_csrf_token
from app.schemas import MediaItem, PlaylistCreate, PlaylistItem, SystemSettings
from app.services.state import app_state, deque_counter

router = APIRouter()

templates = Jinja2Templates(directory="app/web/templates")


def _common_context(request: Request) -> dict:
    csrf_token = request.session.get("_csrf_token") or generate_csrf_token(request)
    return {
        "request": request,
        "csrf_token": csrf_token,
    }


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    context = _common_context(request)
    context.update(
        {
            "stream": app_state.stream_status,
            "alerts": app_state.alerts,
            "playlist": app_state.get_playlist()[:3],
            "uptime_hours": round(app_state.stream_status.uptime_seconds / 3600, 2),
        }
    )
    return templates.TemplateResponse("home.html", context)


@router.get("/playlist", response_class=HTMLResponse)
def playlist(request: Request) -> HTMLResponse:
    context = _common_context(request)
    context.update({"playlist": app_state.get_playlist()})
    return templates.TemplateResponse("playlist.html", context)


@router.post("/playlist", status_code=status.HTTP_303_SEE_OTHER)
async def playlist_submit(
    request: Request,
    title: str = Form(...),
    genre: str = Form(...),
    duration_minutes: int = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    payload = PlaylistCreate(title=title, genre=genre, duration_seconds=duration_minutes * 60)
    item = PlaylistItem(id=next(deque_counter), **payload.model_dump())
    app_state.add_playlist_item(item)
    return RedirectResponse(url="/playlist", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/playlist/remove", status_code=status.HTTP_303_SEE_OTHER)
async def playlist_remove(request: Request, item_id: int = Form(...), csrf_token: str = Form(...)) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    app_state.remove_playlist_item(item_id)
    return RedirectResponse(url="/playlist", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/media", response_class=HTMLResponse)
def media(request: Request) -> HTMLResponse:
    context = _common_context(request)
    context.update({"media": app_state.media})
    return templates.TemplateResponse("media.html", context)


@router.post("/media/upload", status_code=status.HTTP_303_SEE_OTHER)
async def media_upload(
    request: Request,
    title: str = Form(...),
    genre: str = Form(...),
    duration_minutes: int = Form(...),
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    filename = file.filename or "upload.bin"
    media_item = MediaItem(
        id=next(deque_counter),
        title=title,
        genre=genre,
        duration_seconds=duration_minutes * 60,
        file_path=f"/data/movies/{filename}",
        created_at=datetime.utcnow(),
    )
    app_state.media.append(media_item)
    return RedirectResponse(url="/media", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request) -> HTMLResponse:
    context = _common_context(request)
    context.update({"settings": app_state.settings})
    return templates.TemplateResponse("settings.html", context)


@router.post("/settings", status_code=status.HTTP_303_SEE_OTHER)
async def settings_submit(
    request: Request,
    stream_resolution: str = Form(...),
    stream_bitrate: int = Form(...),
    stream_fps: int = Form(...),
    hardware_accel: str = Form(...),
    contact_email: str = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    form_csrf_protect(request, csrf_token)
    payload = SystemSettings(
        stream_resolution=stream_resolution,
        stream_bitrate=stream_bitrate,
        stream_fps=stream_fps,
        hardware_accel=hardware_accel,
        contact_email=contact_email,
    )
    app_state.update_settings(payload)
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
