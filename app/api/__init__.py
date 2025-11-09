"""API routers for StreamHost."""
from fastapi import APIRouter

from app.api.routes import auth, media, playlist, stream, system

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(stream.router, prefix="/stream", tags=["stream"])
router.include_router(playlist.router, prefix="/playlist", tags=["playlist"])
router.include_router(media.router, prefix="/media", tags=["media"])
router.include_router(system.router, prefix="/system", tags=["system"])
