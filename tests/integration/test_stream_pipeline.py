from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MediaAsset
from app.schemas import StreamMetrics
from app.services.stream_engine import StreamSnapshot
from app.services.stream_manager import stream_manager


class DummyEngine:
    def __init__(self) -> None:
        self.running = False
        self.plan = None
        self.started_at: datetime | None = None

    async def is_running(self) -> bool:
        return self.running

    async def start_stream(self, plan) -> None:  # pragma: no cover - simple stub
        self.running = True
        self.plan = plan
        self.started_at = datetime.now(timezone.utc)
        self._process = SimpleNamespace(returncode=None)

    async def stop_stream(self) -> None:
        self.running = False
        self.plan = None
        self.started_at = None
        self._process = None

    async def status_snapshot(self) -> StreamSnapshot:
        return StreamSnapshot(
            running=self.running,
            playlist_id=self.plan.playlist_id if self.plan else None,
            started_at=self.started_at,
            last_error=None,
            metrics=StreamMetrics(),
        )


@pytest.mark.anyio("asyncio")
async def test_stream_manager_start_and_stop(monkeypatch, in_memory_db: Session, tmp_path) -> None:
    media_path = tmp_path / "stream.mp4"
    media_path.write_text("data")
    asset = MediaAsset(
        title="Stream Asset",
        genre="action",
        duration_seconds=600,
        file_path=str(media_path),
        checksum="stream",
    )
    in_memory_db.add(asset)
    in_memory_db.commit()

    dummy_engine = DummyEngine()
    monkeypatch.setattr("app.services.stream_manager.live_stream_engine", dummy_engine)

    original_url = settings.youtube_rtmp_url
    original_key = settings.youtube_stream_key
    settings.youtube_rtmp_url = "rtmp://localhost/live"
    settings.youtube_stream_key = "testkey"

    try:
        status = await stream_manager.start(in_memory_db, media_id=asset.id)
        assert status.status == "online"
        assert status.target and status.target.endswith("/testkey")

        await stream_manager.stop(in_memory_db)
        final_status = await stream_manager.status()
        assert final_status.status in {"offline", "starting"}
    finally:
        settings.youtube_rtmp_url = original_url
        settings.youtube_stream_key = original_key
        stream_manager._session_id = None
        stream_manager._destination = None
        stream_manager._encoder_name = "ffmpeg"
        await dummy_engine.stop_stream()
