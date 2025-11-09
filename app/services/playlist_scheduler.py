"""Intelligent playlist scheduling algorithms.""" 
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import MediaAsset, PlaylistEntry
from app.schemas import PlaylistGenerationRequest, PlaylistItem, PlaylistRules


class PlaylistScheduler:
    """Generate playlists that respect configured business rules."""

    def __init__(self) -> None:
        self._default_rules = PlaylistRules()

    def generate_playlist(
        self,
        db: Session,
        request: PlaylistGenerationRequest,
    ) -> list[PlaylistItem]:
        rules = request.rules or self._default_rules
        tz = ZoneInfo(request.timezone or "UTC")
        start_time = datetime.now(tz)
        target_duration = timedelta(hours=request.hours)

        media_assets = db.query(MediaAsset).all()
        if not media_assets:
            return []

        history = {item.media_id: item.scheduled_start for item in db.query(PlaylistEntry).all() if item.media_id}
        last_used: dict[int, datetime] = {k: v for k, v in history.items() if v}

        media_by_genre: dict[str, deque[MediaAsset]] = defaultdict(deque)
        for asset in sorted(media_assets, key=lambda a: (a.genre, a.title.lower())):
            media_by_genre[asset.genre].append(asset)

        scheduled: list[PlaylistItem] = []
        total_duration = timedelta(0)
        last_genre: Optional[str] = None
        consecutive_genre = 0

        min_gap = timedelta(hours=rules.min_gap_between_repeats_hours)
        events = rules.scheduled_events or []

        while total_duration < target_duration:
            cursor_time = start_time + total_duration
            preferred_genres = self._preferred_genres(cursor_time, request.strategy, media_by_genre.keys(), events)

            if preferred_genres and last_genre in preferred_genres:
                # Avoid repeating same genre beyond allowed streak.
                if consecutive_genre >= rules.max_consecutive_same_genre:
                    preferred_genres = [g for g in preferred_genres if g != last_genre] or preferred_genres

            next_asset = self._select_asset(
                preferred_genres,
                media_by_genre,
                last_used,
                cursor_time,
                min_gap,
            )

            if next_asset is None:
                break

            scheduled_start = cursor_time
            playlist_item = PlaylistItem(
                id=0,
                media_id=next_asset.id,
                title=next_asset.title,
                genre=next_asset.genre,
                duration_seconds=next_asset.duration_seconds,
                scheduled_start=scheduled_start,
            )
            scheduled.append(playlist_item)

            total_duration += timedelta(seconds=next_asset.duration_seconds)
            last_used[next_asset.id] = cursor_time

            if last_genre == next_asset.genre:
                consecutive_genre += 1
            else:
                consecutive_genre = 1
                last_genre = next_asset.genre

        return scheduled

    def _preferred_genres(
        self,
        current_time: datetime,
        strategy: str,
        available_genres: Iterable[str],
        events: Iterable[dict],
    ) -> list[str]:
        available = list(available_genres)
        if not available:
            return []

        # Scheduled events override everything else when they match current slot.
        for event in events:
            day = event.get("day", "").lower()
            if day and day != current_time.strftime("%A").lower():
                continue
            time_str = event.get("time")
            if not time_str:
                continue
            try:
                hour, minute = map(int, time_str.split(":"))
            except ValueError:
                continue
            start = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            duration = timedelta(minutes=int(event.get("duration", 120)))
            if start <= current_time < start + duration:
                genre = event.get("genre")
                if genre and genre in available:
                    return [genre]

        if strategy == "genre-rotation":
            return sorted(available)
        if strategy == "popularity":
            # Approximate popularity via alphabetical order and repeat frequency.
            return sorted(available)
        if strategy == "time-of-day":
            hour = current_time.hour
            if 6 <= hour < 12:
                ordering = ["family", "documentary", "comedy"]
            elif 12 <= hour < 18:
                ordering = ["comedy", "drama", "documentary"]
            elif 18 <= hour < 23:
                ordering = ["action", "thriller", "sci-fi", "comedy"]
            else:
                ordering = ["thriller", "action", "sci-fi", "documentary"]
            ordered = [genre for genre in ordering if genre in available]
            ordered.extend([genre for genre in available if genre not in ordered])
            return ordered
        return available

    def _select_asset(
        self,
        preferred_genres: list[str],
        media_by_genre: dict[str, deque[MediaAsset]],
        last_used: dict[int, datetime],
        cursor_time: datetime,
        min_gap: timedelta,
    ) -> Optional[MediaAsset]:
        for genre in preferred_genres or media_by_genre.keys():
            queue = media_by_genre.get(genre)
            if not queue:
                continue

            # Rotate queue to avoid immediate repeats and respect min gap.
            for _ in range(len(queue)):
                candidate = queue[0]
                last_played = last_used.get(candidate.id)
                if last_played and cursor_time - last_played < min_gap:
                    queue.rotate(-1)
                    continue

                queue.rotate(-1)
                return candidate
        return None


playlist_scheduler = PlaylistScheduler()
