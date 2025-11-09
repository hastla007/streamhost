"""Async FFmpeg streaming engine with telemetry and restarts."""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.core.config import settings
from app.schemas import StreamMetrics

logger = logging.getLogger(__name__)

PREVIEW_DIR = Path(settings.media_root).parent / "preview"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StreamLaunchPlan:
    """Details required to launch a streaming session."""

    playlist_id: int
    media_files: list[Path]
    destination: str
    profiles: list[tuple[str, int]]  # (resolution, bitrate_kbps)
    encoder: str
    preset: str
    fps: int


class LiveStreamManager:
    """Manage FFmpeg streaming processes and parse telemetry."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._progress_task: Optional[asyncio.Task[None]] = None
        self._watchdog_task: Optional[asyncio.Task[None]] = None
        self._metrics = StreamMetrics()
        self._started_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._playlist_id: Optional[int] = None
        self._plan: Optional[StreamLaunchPlan] = None
        self._restart_attempts = 0
        self._concat_file: Optional[Path] = None

    async def start_stream(self, plan: StreamLaunchPlan) -> None:
        """Start streaming using the provided launch plan."""

        async with self._lock:
            if self._process and self._process.returncode is None:
                raise RuntimeError("Stream already running")

            if not plan.media_files:
                raise ValueError("No media files supplied to stream")

            for path in plan.media_files:
                if not path.exists():
                    raise FileNotFoundError(f"Media file missing: {path}")

            self._plan = plan
            self._playlist_id = plan.playlist_id
            self._last_error = None
            self._restart_attempts = 0

            await self._launch_process()

    async def stop_stream(self) -> None:
        """Terminate the running FFmpeg process and cleanup."""

        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        """Internal helper to tear down state while the lock is held."""

        current = asyncio.current_task()
        tasks_to_cancel: list[asyncio.Task] = []

        if self._watchdog_task:
            task = self._watchdog_task
            self._watchdog_task = None
            if task is not current:
                task.cancel()
                tasks_to_cancel.append(task)

        if self._progress_task:
            task = self._progress_task
            self._progress_task = None
            if task is not current:
                task.cancel()
                tasks_to_cancel.append(task)

        for task in tasks_to_cancel:
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Force killing FFmpeg after timeout")
                self._process.kill()
                await self._process.wait()

        self._process = None
        self._metrics = StreamMetrics()
        self._started_at = None
        self._last_error = None
        self._playlist_id = None
        self._plan = None
        self._restart_attempts = 0
        self._cleanup_concat()

    async def get_metrics(self) -> StreamMetrics:
        """Return the most recent telemetry snapshot."""

        async with self._lock:
            return self._metrics

    async def is_running(self) -> bool:
        """Return whether FFmpeg process is currently active."""

        async with self._lock:
            return self._process is not None and self._process.returncode is None

    async def _launch_process(self) -> None:
        assert self._plan is not None

        concat_file = self._create_concat_file(self._plan.media_files)
        self._concat_file = concat_file
        command = self._build_command(self._plan, concat_file)
        logger.info("Starting FFmpeg", extra={"command": command})

        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._started_at = datetime.now(timezone.utc)
        self._metrics = StreamMetrics()

        self._progress_task = asyncio.create_task(self._capture_progress(self._process.stdout))
        self._watchdog_task = asyncio.create_task(self._watch_process())

    async def _watch_process(self) -> None:
        assert self._process is not None

        return_code = await self._process.wait()
        stderr = ""
        if self._process.stderr:
            try:
                stderr = (await self._process.stderr.read()).decode("utf-8", "ignore")
            except Exception:  # pragma: no cover - defensive
                stderr = ""

        if return_code != 0:
            self._last_error = stderr.strip() or f"FFmpeg exited with code {return_code}"
            logger.error("FFmpeg exited unexpectedly", extra={"code": return_code, "stderr": self._last_error})
            await self._handle_restart()
        else:
            logger.info("FFmpeg completed normally")
            await self.stop_stream()

    async def _handle_restart(self) -> None:
        assert self._plan is not None

        async with self._lock:
            self._restart_attempts += 1
            attempts = self._restart_attempts
            if attempts > settings.stream_restart_max_attempts:
                logger.critical("Exceeded FFmpeg restart attempts")
                await self._stop_locked()
                return

            if self._process and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()

            self._cleanup_concat()

        base_delay = settings.stream_restart_base_delay
        max_delay = settings.stream_restart_max_delay
        await asyncio.sleep(min(base_delay * attempts, max_delay))

        async with self._lock:
            if self._plan is None:
                return
            logger.info("Restarting FFmpeg", extra={"attempt": attempts})
            await self._launch_process()

    async def _capture_progress(self, stream: Optional[asyncio.StreamReader]) -> None:
        if stream is None:
            return

        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", "ignore").strip()
            if not decoded or "=" not in decoded:
                continue
            key, value = decoded.split("=", 1)
            await self._update_metrics(key, value)

    async def _update_metrics(self, key: str, value: str) -> None:
        async with self._lock:
            metrics = self._metrics.model_copy()
            try:
                if key == "frame":
                    metrics.frame = int(value)
                elif key == "fps":
                    metrics.fps = float(value)
                elif key == "bitrate":
                    metrics.bitrate_kbps = int(float(value.replace("kbits/s", "").strip() or 0))
                elif key == "speed":
                    metrics.speed = float(value.replace("x", ""))
                elif key == "drop_frames":
                    metrics.dropped_frames = int(value)
                elif key == "buffer_level":
                    metrics.buffer_level_seconds = float(value)
                else:
                    return
            except ValueError:
                logger.debug("Unable to parse metric", extra={"key": key, "value": value})
                return

            self._metrics = metrics

    def _create_concat_file(self, media_files: Iterable[Path]) -> Path:
        playlist_dir = Path(tempfile.mkdtemp(prefix="streamhost_playlist_"))
        concat_file = playlist_dir / "playlist.txt"
        with concat_file.open("w", encoding="utf-8") as handle:
            for path in media_files:
                normalized = path.resolve().as_posix()
                handle.write(f"file '{normalized}'\n")
        return concat_file

    def _cleanup_concat(self) -> None:
        if self._concat_file is not None:
            try:
                shutil.rmtree(self._concat_file.parent, ignore_errors=True)
            finally:
                self._concat_file = None

    def _build_command(self, plan: StreamLaunchPlan, concat_file: Path) -> list[str]:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        for stale in PREVIEW_DIR.glob("*"):
            if stale.is_file():
                stale.unlink(missing_ok=True)

        input_opts = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-re",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-progress",
            "pipe:1",
            "-nostats",
        ]

        hardware_opts: list[str] = []
        encoder = plan.encoder
        preset = plan.preset
        if plan.encoder == "nvenc":
            hardware_opts = ["-hwaccel", "cuda"]
            encoder = "h264_nvenc"
            preset = preset or "p4"
        elif plan.encoder == "qsv":
            hardware_opts = ["-hwaccel", "qsv"]
            encoder = "h264_qsv"
        elif plan.encoder == "videotoolbox":
            hardware_opts = ["-hwaccel", "videotoolbox"]
            encoder = "h264_videotoolbox"
        else:
            encoder = "libx264"
            preset = preset or "veryfast"

        profiles = plan.profiles
        gop = max(plan.fps * 2, 30)
        filter_parts = [f"[0:v]split={len(profiles)}" + "".join(f"[v{idx}base]" for idx in range(len(profiles)))]
        for idx, (resolution, _bitrate) in enumerate(profiles):
            width, height = resolution.split("x")
            filter_parts.append(f"[v{idx}base]scale={width}:{height}[v{idx}]")
        filter_complex = ";".join(filter_parts)

        command = input_opts + hardware_opts + ["-filter_complex", filter_complex]

        var_stream_entries: list[str] = []
        for idx, (resolution, bitrate) in enumerate(profiles):
            command += ["-map", f"[v{idx}]", "-map", "0:a:0"]
            command += [
                f"-c:v:{idx}", encoder,
                f"-b:v:{idx}", f"{bitrate}k",
                f"-maxrate:v:{idx}", f"{bitrate}k",
                f"-bufsize:v:{idx}", f"{bitrate * 2}k",
                f"-preset:v:{idx}", preset,
                f"-r:v:{idx}", str(plan.fps),
                f"-g:v:{idx}", str(gop),
                f"-profile:v:{idx}", "high",
                f"-c:a:{idx}", "aac",
                f"-b:a:{idx}", "160k",
                f"-ac:{idx}", "2",
                f"-ar:{idx}", "48000",
            ]
            bandwidth = bitrate * 1000
            var_stream_entries.append(f"v:{idx},a:{idx},name:{resolution},bandwidth:{bandwidth}")

        segment_template = PREVIEW_DIR / "segment_%v_%05d.ts"
        playlist_template = PREVIEW_DIR / "stream_%v.m3u8"
        command += [
            "-f",
            "hls",
            "-hls_time",
            str(settings.stream_preview_segment_seconds),
            "-hls_playlist_type",
            "event",
            "-hls_flags",
            "delete_segments+independent_segments+program_date_time",
            "-master_pl_name",
            "master.m3u8",
            "-var_stream_map",
            " ".join(var_stream_entries),
            "-hls_segment_filename",
            str(segment_template),
            str(playlist_template),
        ]

        # Map highest quality profile for RTMP output
        command += [
            "-map",
            "[v0]",
            "-map",
            "0:a:0",
            "-c:v",
            encoder,
            "-b:v",
            f"{profiles[0][1]}k",
            "-maxrate",
            f"{profiles[0][1]}k",
            "-bufsize",
            f"{profiles[0][1] * 2}k",
            "-preset",
            preset,
            "-r",
            str(plan.fps),
            "-g",
            str(gop),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-f",
            "flv",
            plan.destination,
        ]

        return command

    def status_snapshot(
        self,
    ) -> tuple[Optional[int], Optional[datetime], Optional[str], StreamMetrics]:
        return self._playlist_id, self._started_at, self._last_error, self._metrics


live_stream_engine = LiveStreamManager()
