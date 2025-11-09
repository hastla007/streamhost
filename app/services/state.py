"""In-memory state and operations backing the StreamHost preview."""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from typing import List

from app.schemas import Alert, MediaItem, PlaylistItem, StreamStatus, SystemSettings


class DeadLetterQueue:
    """Simple container to capture failed operations for later inspection."""

    def __init__(self) -> None:
        self.failures: List[str] = []

    def record(self, message: str) -> None:
        self.failures.append(message)


deque_counter = itertools.count(1)


class ApplicationState:
    """Holds lightweight demo data for the dashboard and API."""

    def __init__(self) -> None:
        now = datetime.utcnow()
        self.stream_status = StreamStatus(
            status="online",
            bitrate_kbps=4200,
            uptime_seconds=14 * 3600 + 12 * 60,
            encoder="h264",
            dropped_frames=3,
            last_updated=now,
        )
        self.alerts: List[Alert] = [
            Alert(level="ok", message="All systems nominal", timestamp=now - timedelta(minutes=5)),
            Alert(level="warning", message="Maintenance window scheduled in 3 hours", timestamp=now),
        ]
        self.playlist: List[PlaylistItem] = [
            PlaylistItem(
                id=next(deque_counter),
                title="Neon Skyline",
                genre="sci-fi",
                duration_seconds=8100,
                scheduled_start=now + timedelta(minutes=20),
            ),
            PlaylistItem(
                id=next(deque_counter),
                title="Midnight Chase",
                genre="action",
                duration_seconds=6900,
                scheduled_start=now + timedelta(hours=2),
            ),
            PlaylistItem(
                id=next(deque_counter),
                title="Ocean Dreams",
                genre="documentary",
                duration_seconds=2880,
                scheduled_start=now + timedelta(hours=3, minutes=55),
            ),
        ]
        self.media: List[MediaItem] = [
            MediaItem(
                id=next(deque_counter),
                title="Sunset Boulevard",
                genre="drama",
                duration_seconds=5400,
                file_path="/data/movies/sunset-boulevard.mp4",
                created_at=now - timedelta(days=2),
            ),
            MediaItem(
                id=next(deque_counter),
                title="Galactic Frontier",
                genre="sci-fi",
                duration_seconds=7200,
                file_path="/data/movies/galactic-frontier.mkv",
                created_at=now - timedelta(days=1, hours=3),
            ),
        ]
        self.settings = SystemSettings(
            stream_resolution="1920x1080",
            stream_bitrate=4000,
            stream_fps=30,
            hardware_accel="auto",
            contact_email="admin@example.com",
        )
        self.dead_letters = DeadLetterQueue()

    def get_playlist(self) -> List[PlaylistItem]:
        return list(self.playlist)

    def add_playlist_item(self, item: PlaylistItem) -> PlaylistItem:
        self.playlist.append(item)
        return item

    def remove_playlist_item(self, item_id: int) -> bool:
        before = len(self.playlist)
        self.playlist = [item for item in self.playlist if item.id != item_id]
        return len(self.playlist) != before

    def update_settings(self, payload: SystemSettings) -> SystemSettings:
        self.settings = payload
        return self.settings

    def record_failure(self, message: str) -> None:
        self.dead_letters.record(message)


app_state = ApplicationState()
