"""Stream health monitoring and alerting."""
from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import psutil

from app.core.config import settings
from app.schemas import HealthStatus
from app.services.stream_engine import live_stream_engine

logger = logging.getLogger(__name__)


class StreamMonitor:
    """Observe the streaming pipeline and raise alerts when degraded."""

    def __init__(self) -> None:
        self._alert_channels: list[str] = ["email", "slack", "discord"]

    async def check_stream_health(self) -> HealthStatus:
        snapshot = await live_stream_engine.status_snapshot()
        metrics = snapshot.metrics
        started_at = snapshot.started_at
        last_error = snapshot.last_error
        ffmpeg_running = await live_stream_engine.is_running()
        bitrate_target = settings.stream_bitrate
        bitrate_ok = metrics.bitrate_kbps >= int(bitrate_target * 0.7)
        dropped_ok = metrics.dropped_frames < 100

        disk_ok = self._check_disk_space(settings.media_root, threshold_gb=10)
        cpu_ok, cpu_value = self._check_cpu_usage()
        memory_ok, memory_value = self._check_memory_usage()

        checks = {
            "ffmpeg_running": ffmpeg_running,
            "bitrate_stable": bitrate_ok,
            "dropped_frames": dropped_ok,
            "disk_space": disk_ok,
            "cpu_usage": cpu_ok,
            "memory_usage": memory_ok,
        }

        issues: list[str] = []
        if not ffmpeg_running:
            issues.append("FFmpeg process not running")
        if not bitrate_ok:
            issues.append(f"Bitrate below target: {metrics.bitrate_kbps} kbps")
        if not dropped_ok:
            issues.append(f"Dropped frames {metrics.dropped_frames}")
        if not disk_ok:
            issues.append("Low disk space")
        if not cpu_ok:
            issues.append(f"CPU usage high: {cpu_value:.1f}%")
        if not memory_ok:
            issues.append(f"Memory usage high: {memory_value:.1f}%")
        if last_error:
            issues.append(last_error)

        severity = self._determine_severity(checks, issues)
        metrics_map = {
            "bitrate_kbps": metrics.bitrate_kbps,
            "dropped_frames": metrics.dropped_frames,
            "cpu_percent": cpu_value,
            "memory_percent": memory_value,
            "uptime_seconds": self._uptime_seconds(started_at),
        }

        status = HealthStatus(checks=checks, metrics=metrics_map, issues=issues, severity=severity)
        return status

    async def alert_if_needed(self, status: HealthStatus) -> None:
        if status.severity == "ok":
            return

        message = status.summary
        logger.warning("Stream degraded", extra={"severity": status.severity, "summary": message})
        await self.send_alert(self._alert_channels, status.severity, message)

    async def send_alert(self, channels: Iterable[str], severity: str, message: str) -> None:
        """Dispatch an alert to configured channels."""

        for channel in channels:
            logger.info("Alert dispatched", extra={"channel": channel, "severity": severity, "message": message})
            await asyncio.sleep(0)  # Allow cooperative scheduling

    def _check_disk_space(self, path: str, threshold_gb: int) -> bool:
        target = Path(path)
        if not target.exists():
            target = target.parent
        usage = shutil.disk_usage(target)
        free_gb = usage.free / 1024 / 1024 / 1024
        return free_gb >= threshold_gb

    def _check_cpu_usage(self) -> tuple[bool, float]:
        value = psutil.cpu_percent(interval=0.1)
        return value < 90.0, value

    def _check_memory_usage(self) -> tuple[bool, float]:
        memory = psutil.virtual_memory()
        return memory.percent < 90.0, memory.percent

    def _uptime_seconds(self, started_at: datetime | None) -> int:
        if not started_at:
            return 0
        now = datetime.now(timezone.utc)
        return int((now - started_at).total_seconds())

    def _determine_severity(self, checks: dict[str, bool], issues: list[str]) -> str:
        if not checks.get("ffmpeg_running"):
            return "critical"
        if any(not healthy for healthy in checks.values()):
            return "warning" if issues else "warning"
        return "ok"


stream_monitor = StreamMonitor()
