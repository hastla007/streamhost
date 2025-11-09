"""Integration tests covering security and streaming edge cases."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import check_pool_health
from app.core.security import CSRF_EXPIRY_KEY, CSRF_PREVIOUS_KEY, generate_csrf_token
from app.db.base import Base
from app.models import MediaAsset, PlaylistEntry
from app.services.stream_engine import LiveStreamManager, StreamLaunchPlan
from app.web.routes import playlist_submit


class MockRequest:
    """Lightweight request object carrying session state for CSRF validation."""

    def __init__(self) -> None:
        session: dict[str, str] = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace(session=session)
        self.session = session
        self.headers: dict[str, str] = {}
        self.url = SimpleNamespace(path="/playlist")


@pytest.mark.anyio
async def test_ffmpeg_crash_cleans_temporary_artifacts(monkeypatch, tmp_path):
    """Ensure a crashing FFmpeg process releases temporary concat files."""

    manager = LiveStreamManager()

    media_file = tmp_path / "video.mp4"
    media_file.write_text("dummy")

    plan = StreamLaunchPlan(
        playlist_id=1,
        media_files=[media_file],
        destination="rtmp://localhost/live/test",
        profiles=[("1920x1080", 4000)],
        encoder="libx264",
        preset="veryfast",
        fps=30,
    )

    class DummyStream:
        def __init__(self, lines: Iterable[str]):
            self._lines = [f"{line}\n".encode() for line in lines]

        async def readline(self) -> bytes:
            await asyncio.sleep(0)
            if self._lines:
                return self._lines.pop(0)
            return b""

    class FailingProcess:
        def __init__(self) -> None:
            self.returncode: Optional[int] = None
            self.stderr = DummyStream(["frame=1", "fps=30", "bitrate=1000kbits/s"])

        async def wait(self) -> int:
            await asyncio.sleep(0)
            if self.returncode is None:
                self.returncode = 1
            return self.returncode

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    created_dirs: list[Path] = []

    real_tempdir = tempfile.TemporaryDirectory

    def tracking_tempdir(*args, **kwargs):
        temp = real_tempdir(*args, **kwargs)
        created_dirs.append(Path(temp.name))
        return temp

    async def fake_subprocess_exec(*_args, **_kwargs):
        return FailingProcess()

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracking_tempdir)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
    monkeypatch.setattr(settings, "stream_restart_max_attempts", 1)
    monkeypatch.setattr(settings, "stream_restart_base_delay", 0)
    monkeypatch.setattr(settings, "stream_restart_max_delay", 0)

    await manager.start_stream(plan)

    await asyncio.sleep(0.1)

    await manager.stop_stream()

    assert created_dirs, "Expected concat directory to be created during stream startup"
    for path in created_dirs:
        assert not path.exists(), f"Temporary directory {path} should be cleaned"


@pytest.mark.anyio
async def test_csrf_token_allows_grace_period(monkeypatch, tmp_path):
    """Submitting a form with an expiring token should succeed via the grace period."""

    engine = create_engine(
        f"sqlite:///{tmp_path / 'csrf.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    monkeypatch.setattr(settings, "csrf_token_ttl_seconds", 0.1)

    try:
        with Session() as session:
            asset = MediaAsset(
                title="Token Test",
                genre="action",
                duration_seconds=120,
                file_path="/tmp/token.mp4",
                checksum="token",
            )
            session.add(asset)
            session.commit()
            media_id = asset.id

        request = MockRequest()
        original_token = generate_csrf_token(request)
        request.session[CSRF_EXPIRY_KEY] = time.time() - 1
        request.session[CSRF_PREVIOUS_KEY] = original_token
        generate_csrf_token(request)

        with Session() as session:
            response = await playlist_submit(
                request,
                media_id=media_id,
                csrf_token=original_token,
                db=session,
            )

        assert response.status_code == 303

        with Session() as session:
            count = session.query(PlaylistEntry).count()
            assert count == 1
    finally:
        engine.dispose()


def test_health_endpoint_reports_pool_exhaustion(monkeypatch):
    """Database pool health helper should report exhaustion when thresholds are exceeded."""

    dummy_pool = SimpleNamespace(
        size=lambda: 10,
        checkedout=lambda: 28,
        overflow=lambda: 5,
    )

    monkeypatch.setattr("app.core.database.engine", SimpleNamespace(pool=dummy_pool))

    healthy, message = check_pool_health()
    assert not healthy
    assert "Pool" in message and "28/30" in message


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific escaping only applies on Windows")
def test_windows_concat_paths_are_escaped(tmp_path):
    """Ensure Windows concat entries escape single quotes consistently."""

    manager = LiveStreamManager()

    media_file = tmp_path / "folder" / "clip 'quotes'.mp4"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_text("data")

    concat_file = manager._create_concat_file([media_file])
    contents = concat_file.read_text().strip()

    expected_path = media_file.resolve().as_posix().replace("'", "'\\''")
    assert contents == f"file '{expected_path}'"

    manager._cleanup_concat()
