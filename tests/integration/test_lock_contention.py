import asyncio

import pytest

from app.utils import ObservedLock, collect_lock_warnings


@pytest.mark.anyio("asyncio")
async def test_lock_contention_reports_warning() -> None:
    lock = ObservedLock("test_lock")

    async def holder() -> None:
        async with lock:
            await asyncio.sleep(0.05)

    async def waiter() -> None:
        async with lock:
            return

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0)  # allow holder to acquire lock
    await waiter()
    await holder_task

    warnings = collect_lock_warnings(wait_threshold=0.01, hold_threshold=5)
    assert any("test_lock" in warning for warning in warnings)
