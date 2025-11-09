import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.stream_engine import LiveStreamManager, StreamLaunchPlan


@pytest.mark.anyio("asyncio")
async def test_status_snapshot_reports_running_state() -> None:
    manager = LiveStreamManager()
    manager._process = SimpleNamespace(returncode=None)  # type: ignore[attr-defined]
    manager._playlist_id = 42
    manager._started_at = datetime.now(timezone.utc)
    snapshot = await manager.status_snapshot()
    assert snapshot.running is True
    assert snapshot.playlist_id == 42


def test_create_concat_file_escapes_quotes(tmp_path) -> None:
    manager = LiveStreamManager()
    media_file = tmp_path / "sample's clip.mp4"
    media_file.write_bytes(b"")

    concat_path = manager._create_concat_file([media_file])
    try:
        content = concat_path.read_text()
        assert "sample'\\''s clip.mp4" in content
    finally:
        manager._cleanup_concat()


@pytest.mark.anyio("asyncio")
async def test_handle_restart_runs_once(monkeypatch) -> None:
    manager = LiveStreamManager()
    manager._plan = StreamLaunchPlan(
        playlist_id=1,
        media_files=[Path(__file__)],
        destination="rtmp://example/stream",
        profiles=[("1920x1080", 4000)],
        encoder="libx264",
        preset="fast",
        fps=30,
    )

    calls: list[int] = []

    async def fake_restart_loop() -> None:
        calls.append(1)
        await asyncio.sleep(0)

    monkeypatch.setattr(manager, "_restart_loop", fake_restart_loop)

    await asyncio.gather(manager._handle_restart(), manager._handle_restart())

    assert len(calls) == 1
    assert manager._is_restarting is False

def test_create_concat_file_windows_paths(monkeypatch) -> None:
    manager = LiveStreamManager()

    class FakeWindowsPath:
        def __init__(self, text: str) -> None:
            self._text = text

        def resolve(self) -> "FakeWindowsPath":  # pragma: no cover - simple forwarding
            return self

        def exists(self) -> bool:  # pragma: no cover - simple predicate
            return True

        def __str__(self) -> str:  # pragma: no cover - invoked via str()
            return self._text

        def __fspath__(self) -> str:  # pragma: no cover - safety for Path IO
            return self._text

    fake_path = FakeWindowsPath("C\\Videos\\clip\"quote\".mp4")

    monkeypatch.setattr(
        "app.services.stream_engine.os",
        SimpleNamespace(name="nt"),
        raising=False,
    )

    concat_path = manager._create_concat_file([fake_path])
    try:
        content = concat_path.read_text()
        assert "C\\\\Videos\\\\clip\\\"quote\\\".mp4" in content
    finally:
        manager._cleanup_concat()


def test_cleanup_concat_handles_permission_error(monkeypatch) -> None:
    manager = LiveStreamManager()

    class DummyTempDir:
        def cleanup(self) -> None:
            raise PermissionError("locked")

    dummy_dir = DummyTempDir()
    manager._concat_tempdir = dummy_dir  # type: ignore[assignment]

    manager._cleanup_concat()
    assert manager._concat_tempdir is None
