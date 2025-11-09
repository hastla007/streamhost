"""Async lock instrumentation utilities."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional


@dataclass
class LockSnapshot:
    """Metrics captured for a single observed lock."""

    name: str
    locked: bool
    max_wait_seconds: float
    current_waiters: int
    hold_duration_seconds: Optional[float]


class LockRegistry:
    """Registry that tracks observed locks for health diagnostics."""

    _locks: set["ObservedLock"] = set()

    @classmethod
    def register(cls, lock: "ObservedLock") -> None:
        cls._locks.add(lock)

    @classmethod
    def snapshots(cls) -> List[LockSnapshot]:
        now = time.monotonic()
        return [lock.snapshot(now) for lock in cls._locks]


class ObservedLock:
    """Wrapper around :class:`asyncio.Lock` with wait/hold instrumentation."""

    __slots__ = ("_name", "_lock", "_wait_times", "_max_wait", "_waiting", "_acquired_at")

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = asyncio.Lock()
        self._wait_times: Deque[float] = deque(maxlen=100)
        self._max_wait = 0.0
        self._waiting = 0
        self._acquired_at: Optional[float] = None
        LockRegistry.register(self)

    @property
    def name(self) -> str:
        return self._name

    async def acquire(self) -> bool:
        start = time.monotonic()
        self._waiting += 1
        try:
            await self._lock.acquire()
        finally:
            self._waiting -= 1
        waited = time.monotonic() - start
        self._wait_times.append(waited)
        if waited > self._max_wait:
            self._max_wait = waited
        self._acquired_at = time.monotonic()
        return True

    def release(self) -> None:
        self._acquired_at = None
        self._lock.release()

    async def __aenter__(self) -> "ObservedLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def snapshot(self, now: Optional[float] = None) -> LockSnapshot:
        if now is None:
            now = time.monotonic()
        hold_duration = None
        if self._acquired_at is not None:
            hold_duration = max(0.0, now - self._acquired_at)
        return LockSnapshot(
            name=self._name,
            locked=self.locked(),
            max_wait_seconds=self._max_wait,
            current_waiters=self._waiting,
            hold_duration_seconds=hold_duration,
        )


def collect_lock_warnings(*, wait_threshold: float, hold_threshold: float) -> List[str]:
    """Return warning messages for locks breaching contention thresholds."""

    warnings: List[str] = []
    for snapshot in LockRegistry.snapshots():
        if snapshot.max_wait_seconds > wait_threshold:
            warnings.append(
                f"{snapshot.name} wait exceeded {wait_threshold:.2f}s (max {snapshot.max_wait_seconds:.2f}s)"
            )
        if (
            snapshot.locked
            and snapshot.hold_duration_seconds is not None
            and snapshot.hold_duration_seconds > hold_threshold
        ):
            warnings.append(
                f"{snapshot.name} held for {snapshot.hold_duration_seconds:.2f}s"
            )
    return warnings


__all__ = ["ObservedLock", "collect_lock_warnings", "LockSnapshot"]
