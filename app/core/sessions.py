"""Redis-backed server-side session management."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from redis import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "streamhost_session"
SESSION_PREFIX = "session:"
SESSION_MAX_AGE = 12 * 60 * 60
SESSION_ABSOLUTE_TIMEOUT = SESSION_MAX_AGE
SESSION_IDLE_TIMEOUT = 2 * 60 * 60


@dataclass
class SessionMetadata:
    created_at: datetime
    last_accessed_at: datetime


class ServerSession:
    """Representation of a server-side session."""

    def __init__(self, session_id: str, redis: Redis, data: Optional[dict[str, Any]] = None) -> None:
        self.session_id = session_id
        self._redis = redis
        self._data = data or {}
        self._modified = False
        self._meta: Optional[SessionMetadata] = None

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:  # pragma: no cover - trivial
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._modified = True

    def pop(self, key: str, default: Any = None) -> Any:
        self._modified = True
        return self._data.pop(key, default)

    def clear(self) -> None:
        self._data.clear()
        self._modified = True

    def is_modified(self) -> bool:
        return self._modified

    def load_metadata(self, *, created_at: datetime, last_accessed_at: datetime) -> None:
        self._meta = SessionMetadata(created_at=created_at, last_accessed_at=last_accessed_at)

    def _serialize(self) -> str:
        now = datetime.now(timezone.utc)
        if self._meta is None:
            self._meta = SessionMetadata(created_at=now, last_accessed_at=now)
        else:
            self._meta.last_accessed_at = now
        payload = {
            "data": self._data,
            "created_at": self._meta.created_at.isoformat(),
            "last_accessed_at": self._meta.last_accessed_at.isoformat(),
        }
        try:
            return json.dumps(payload)
        except TypeError as exc:
            logger.error("Session contains non-serializable data", exc_info=exc)
            raise ValueError("Session data is not JSON-serializable") from exc

    def save(self) -> None:
        payload = self._serialize()
        key = f"{SESSION_PREFIX}{self.session_id}"
        self._redis.setex(key, SESSION_MAX_AGE, payload)
        self._modified = False
        logger.debug("Session persisted", extra={"session": self.session_id[:8]})

    def invalidate(self) -> None:
        key = f"{SESSION_PREFIX}{self.session_id}"
        self._redis.delete(key)
        self._data.clear()
        self._modified = False
        logger.info("Session invalidated", extra={"session": self.session_id[:8]})

    def check_valid(self) -> tuple[bool, Optional[str]]:
        if self._meta is None:
            return True, None
        now = datetime.now(timezone.utc)
        age = (now - self._meta.created_at).total_seconds()
        idle = (now - self._meta.last_accessed_at).total_seconds()
        if age > SESSION_ABSOLUTE_TIMEOUT:
            return False, "absolute_timeout"
        if idle > SESSION_IDLE_TIMEOUT:
            return False, "idle_timeout"
        return True, None


class SessionManager:
    """Create and persist Redis-backed sessions."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def create(self) -> ServerSession:
        return ServerSession(secrets.token_urlsafe(32), self._redis)

    def load(self, session_id: str) -> Optional[ServerSession]:
        key = f"{SESSION_PREFIX}{session_id}"
        try:
            data = self._redis.get(key)
        except Exception as exc:  # pragma: no cover - network failures
            logger.error("Failed to read session", extra={"error": str(exc)})
            return None
        if not data:
            return None
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Invalid session payload", extra={"session": session_id[:8]})
            self._redis.delete(key)
            return None
        session = ServerSession(session_id, self._redis, payload.get("data", {}))
        try:
            created_at = datetime.fromisoformat(payload["created_at"])
            last_accessed_at = datetime.fromisoformat(payload["last_accessed_at"])
        except (KeyError, ValueError):
            logger.warning("Malformed session metadata", extra={"session": session_id[:8]})
            self._redis.delete(key)
            return None
        session.load_metadata(created_at=created_at, last_accessed_at=last_accessed_at)
        is_valid, reason = session.check_valid()
        if not is_valid:
            logger.info("Session expired", extra={"session": session_id[:8], "reason": reason})
            session.invalidate()
            return None
        return session

    def cleanup_expired(self) -> int:
        removed = 0
        try:
            for key in self._redis.scan_iter(match=f"{SESSION_PREFIX}*", count=100):
                session_id = key.decode().replace(SESSION_PREFIX, "")
                session = self.load(session_id)
                if session is None:
                    continue
                valid, reason = session.check_valid()
                if not valid:
                    session.invalidate()
                    removed += 1
        except Exception as exc:  # pragma: no cover - network failures
            logger.error("Session cleanup failed", extra={"error": str(exc)})
        if removed:
            logger.info("Removed expired sessions", extra={"count": removed})
        return removed


class ServerSessionMiddleware(BaseHTTPMiddleware):
    """Middleware that injects Redis-backed session handling."""

    def __init__(self, app, redis: Redis) -> None:
        super().__init__(app)
        self._manager = SessionManager(redis)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session: Optional[ServerSession] = None

        if session_id:
            session = await asyncio.to_thread(self._manager.load, session_id)

        if session is None:
            session = self._manager.create()
            session_id = session.session_id

        request.state.session = session

        response = await call_next(request)

        if session.is_modified() or SESSION_COOKIE_NAME not in request.cookies:
            try:
                await asyncio.to_thread(session.save)
            except ValueError:
                logger.warning("Dropping session with non-serializable payload; issuing fresh session")
                session = self._manager.create()
                request.state.session = session
                session_id = session.session_id
                await asyncio.to_thread(session.save)

            response.set_cookie(
                SESSION_COOKIE_NAME,
                session_id,
                max_age=SESSION_MAX_AGE,
                httponly=True,
                secure=settings.app_env == "production",
                samesite="lax",
            )
        else:
            key = f"{SESSION_PREFIX}{session.session_id}"
            await asyncio.to_thread(self._manager._redis.expire, key, SESSION_MAX_AGE)

        return response


def get_session(request: Request) -> ServerSession:
    if hasattr(request.state, "session"):
        return request.state.session  # type: ignore[return-value]
    raise RuntimeError("Server session middleware not configured")


def has_server_session(request: Request) -> bool:
    return hasattr(request.state, "session")


async def periodic_session_cleanup(redis: Redis) -> None:
    manager = SessionManager(redis)
    while True:
        try:
            await asyncio.sleep(3600)
            removed = await asyncio.to_thread(manager.cleanup_expired)
            logger.debug("Session cleanup run", extra={"removed": removed})
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            break
        except Exception:  # pragma: no cover - defensive
            logger.exception("Session cleanup loop failure")
