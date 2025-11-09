import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.stream_engine import LiveStreamManager


@pytest.mark.anyio("asyncio")
async def test_status_snapshot_reports_running_state() -> None:
    manager = LiveStreamManager()
    # Inject a fake running process
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
