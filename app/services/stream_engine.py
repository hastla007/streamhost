"""Async FFmpeg streaming engine with telemetry and restarts."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import weakref
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.core.config import settings
from app.core.retry import BackoffStrategy, RetryCalculator, RetryConfig
from app.core.types import StreamSnapshot
from app.core.exceptions import StreamingError
from app.schemas import StreamMetrics
from app.utils import ObservedLock

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
        self._lock = ObservedLock("stream_engine_lock")
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
        self._concat_tempdir: Optional[tempfile.TemporaryDirectory] = None
        self._concat_finalizer: Optional[weakref.finalize] = None
        self._consecutive_failures = 0
        self._last_success_time: Optional[datetime] = None
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._is_restarting = False

        try:
            strategy = BackoffStrategy(settings.stream_restart_strategy.lower())
        except ValueError:
            strategy = BackoffStrategy.EXPONENTIAL

        self._retry_calculator = RetryCalculator(
            RetryConfig(
                base_delay=float(settings.stream_restart_base_delay),
                max_delay=float(settings.stream_restart_max_delay),
                max_attempts=settings.stream_restart_max_attempts,
                strategy=strategy,
                jitter=True,
            )
        )

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
            self._consecutive_failures = 0
            self._last_success_time = None
            self._stderr_lines.clear()
            self._is_restarting = False

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
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
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
        self._consecutive_failures = 0
        self._last_success_time = None
        self._stderr_lines.clear()
        self._is_restarting = False
        self._cleanup_concat()

    async def get_metrics(self) -> StreamMetrics:
        """Return the most recent telemetry snapshot."""

        async with self._lock:
            return self._metrics.model_copy(deep=True)

    async def is_running(self) -> bool:
        """Return whether FFmpeg process is currently active."""

        async with self._lock:
            return self._process is not None and self._process.returncode is None

    async def _launch_process(self) -> None:
        assert self._plan is not None

        try:
            concat_file = self._create_concat_file(self._plan.media_files)
        except FileNotFoundError as exc:
            self._last_error = str(exc)
            logger.error("Unable to build FFmpeg playlist", exc_info=exc)
            raise

        self._concat_file = concat_file
        command = self._build_command(self._plan, concat_file)
        logger.info("Starting FFmpeg", extra={"command": command})

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("Failed to launch FFmpeg")
            raise StreamingError(f"Failed to launch FFmpeg: {exc}") from exc

        self._started_at = datetime.now(timezone.utc)
        self._metrics = StreamMetrics()
        self._last_success_time = self._started_at
        self._stderr_lines.clear()

        self._progress_task = asyncio.create_task(self._capture_progress(self._process.stderr))
        self._watchdog_task = asyncio.create_task(self._watch_process())

    async def _watch_process(self) -> None:
        assert self._process is not None

        return_code = await self._process.wait()
        stderr = "\n".join(self._stderr_lines)

        if return_code != 0:
            self._last_error = stderr.strip() or f"FFmpeg exited with code {return_code}"
            logger.error("FFmpeg exited unexpectedly", extra={"code": return_code, "stderr": self._last_error})
            await self._handle_restart()
        else:
            logger.info("FFmpeg completed normally")
            async with self._lock:
                self._last_success_time = datetime.now(timezone.utc)
            await self.stop_stream()

    async def _handle_restart(self) -> None:
        async with self._lock:
            if self._is_restarting or self._plan is None:
                return
            self._is_restarting = True

        try:
            while True:
                process_to_wait: Optional[asyncio.subprocess.Process] = None

                async with self._lock:
                    self._restart_attempts += 1
                    self._consecutive_failures += 1
                    attempts = self._restart_attempts

                    if attempts > settings.stream_restart_max_attempts:
                        logger.critical("Exceeded FFmpeg restart attempts", extra={"attempts": attempts})
                        await self._stop_locked()
                        return

                    if self._last_success_time:
                        elapsed = datetime.now(timezone.utc) - self._last_success_time
                        if elapsed.total_seconds() > 300:
                            logger.info(
                                "Resetting failure counter after stable run",
                                extra={"seconds": int(elapsed.total_seconds())},
                            )
                            self._consecutive_failures = 1

                    if self._process and self._process.returncode is None:
                        process_to_wait = self._process
                        self._process = None

                    self._cleanup_concat()

                if process_to_wait is not None:
                    process_to_wait.terminate()
                    try:
                        await asyncio.wait_for(process_to_wait.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        process_to_wait.kill()
                        await process_to_wait.wait()

                try:
                    delay = self._retry_calculator.calculate_delay(attempts)
                except ValueError:
                    delay = float(settings.stream_restart_max_delay)

                logger.warning(
                    "Restarting FFmpeg after backoff",
                    extra={
                        "attempt": attempts,
                        "delay_seconds": f"{delay:.2f}",
                        "consecutive_failures": self._consecutive_failures,
                    },
                )
                await asyncio.sleep(delay)

                async with self._lock:
                    if self._plan is None:
                        return
                    logger.info("Attempting FFmpeg restart", extra={"attempt": attempts})
                    try:
                        await self._launch_process()
                        self._consecutive_failures = 0
                        return
                    except StreamingError as exc:
                        self._last_error = str(exc)
                        logger.error(
                            "Failed to restart FFmpeg",
                            extra={"attempt": attempts, "error": str(exc)},
                        )
                        continue
        finally:
            async with self._lock:
                self._is_restarting = False

    async def _capture_progress(self, stream: Optional[asyncio.StreamReader]) -> None:
        if stream is None:
            return

        max_line_length = 8192

        while True:
            try:
                line = await asyncio.wait_for(stream.readline(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            if not line:
                break

            if len(line) > max_line_length:
                logger.warning("FFmpeg progress line too long, skipping")
                continue

            decoded = line.decode("utf-8", "ignore").strip()
            if not decoded:
                continue

            if "=" not in decoded:
                async with self._lock:
                    self._stderr_lines.append(decoded)
                continue

            key, value = decoded.split("=", 1)
            await self._update_metrics(key, value)

    async def _update_metrics(self, key: str, value: str) -> None:
        async with self._lock:
            metrics = self._metrics.model_copy(deep=True)
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

    @staticmethod
    def _cleanup_tempdir(tempdir: tempfile.TemporaryDirectory) -> None:  # pragma: no cover - defensive
        try:
            tempdir.cleanup()
        except (PermissionError, OSError):
            logger.warning("Failed to cleanup concat directory during finalizer", exc_info=True)

    def _create_concat_file(self, media_files: Iterable[Path]) -> Path:
        self._cleanup_concat()
        tempdir = tempfile.TemporaryDirectory(prefix="streamhost_playlist_")
        playlist_dir = Path(tempdir.name)
        concat_file = playlist_dir / "playlist.txt"
        try:
            with concat_file.open("w", encoding="utf-8") as handle:
                for path in media_files:
                    resolved = path.resolve()
                    if not resolved.exists():
                        raise FileNotFoundError(f"Media file missing: {resolved}")

                    resolved_path = Path(resolved)
                    if os.name == "nt":
                        normalized = str(resolved_path)
                        escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
                        handle.write(f"file \"{escaped}\"\n")
                    else:
                        normalized = resolved_path.as_posix()
                        escaped = normalized.replace("'", "'\\''")
                        handle.write(f"file '{escaped}'\n")
        except Exception:
            tempdir.cleanup()
            raise
        else:
            self._concat_tempdir = tempdir
            self._concat_finalizer = weakref.finalize(self, self._cleanup_tempdir, tempdir)
            return concat_file

    def _cleanup_concat(self) -> None:
        if self._concat_finalizer is not None:
            try:
                self._concat_finalizer()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.warning("Concat finalizer raised during cleanup", exc_info=True)
            self._concat_finalizer = None

        if self._concat_tempdir is not None:
            try:
                self._concat_tempdir.cleanup()
            except (PermissionError, OSError) as exc:  # pragma: no cover - platform specific
                logger.warning("Failed to cleanup concat directory", exc_info=exc)
            self._concat_tempdir = None
        self._concat_file = None

    def _build_command(self, plan: StreamLaunchPlan, concat_file: Path) -> list[str]:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        threshold_seconds = max(settings.stream_preview_segment_seconds * 3, 30)
        cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
        # _build_command is only called from _launch_process while the engine lock
        # is held, so removing stale preview artefacts here will not race with an
        # active encoder in this process. Multi-instance deployments should still
        # isolate preview directories per host.
        for stale in PREVIEW_DIR.glob("*"):
            try:
                modified = stale.stat().st_mtime
            except OSError:
                continue
            if modified > cutoff:
                continue
            if stale.is_file():
                stale.unlink(missing_ok=True)
            elif stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)

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
            "pipe:2",
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

    async def status_snapshot(self) -> StreamSnapshot:
        async with self._lock:
            running = self._process is not None and self._process.returncode is None
            return StreamSnapshot(
                running=running,
                playlist_id=self._playlist_id,
                started_at=self._started_at,
                last_error=self._last_error,
                metrics=self._metrics.model_copy(deep=True),
            )


live_stream_engine = LiveStreamManager()
