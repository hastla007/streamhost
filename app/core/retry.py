"""Retry helpers with configurable backoff strategies."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BackoffStrategy(Enum):
    """Supported backoff strategies."""

    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    FIBONACCI = "fibonacci"


@dataclass
class RetryConfig:
    """Configuration for retry behaviour."""

    base_delay: float = 5.0
    max_delay: float = 300.0
    max_attempts: int = 10
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    jitter: bool = True
    jitter_factor: float = 0.1


class RetryCalculator:
    """Calculate retry delays using a chosen strategy."""

    def __init__(self, config: Optional[RetryConfig] = None) -> None:
        self.config = config or RetryConfig()

    def calculate_delay(self, attempt: int) -> float:
        """Return the delay for a given attempt (1-indexed)."""

        if attempt < 1:
            raise ValueError("Attempt number must be positive")
        if attempt > self.config.max_attempts:
            raise ValueError(f"Attempt {attempt} exceeds max {self.config.max_attempts}")

        if self.config.strategy == BackoffStrategy.LINEAR:
            delay = self.config.base_delay * attempt
        elif self.config.strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.config.base_delay * (2 ** (attempt - 1))
        elif self.config.strategy == BackoffStrategy.FIBONACCI:
            delay = self.config.base_delay * self._get_fibonacci(attempt)
        else:
            delay = self.config.base_delay

        delay = min(delay, self.config.max_delay)

        if self.config.jitter:
            jitter_range = delay * self.config.jitter_factor
            delay = max(0.1, delay + random.uniform(-jitter_range, jitter_range))

        return delay

    def _get_fibonacci(self, n: int) -> int:
        if n <= 2:
            return 1

        a, b = 1, 1
        for _ in range(2, n):
            a, b = b, a + b
        return b

    async def sleep_with_backoff(self, attempt: int) -> None:
        """Sleep for the computed delay."""

        await asyncio.sleep(self.calculate_delay(attempt))
