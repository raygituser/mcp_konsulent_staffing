from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Awaitable, Tuple, Type

@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 3.0

async def with_retry(
    fn: Callable[[], Awaitable],
    config: RetryConfig,
    retryable_exceptions: Tuple[Type[BaseException], ...],
):
    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn()
        except retryable_exceptions:
            if attempt >= config.max_attempts:
                raise
            delay = min(config.max_delay_seconds, config.base_delay_seconds * (2 ** (attempt - 1)))
            await asyncio.sleep(delay)


class CircuitBreaker:
    """Tiny circuit breaker suitable for demos (in-memory)."""

    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout_seconds: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._failures = 0
        self._opened_at: float | None = None

    def allow_request(self) -> bool:
        if self._opened_at is None:
            return True
        # allow half-open after timeout
        if time.time() - self._opened_at >= self.recovery_timeout_seconds:
            return True
        return False

    async def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    async def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.time()

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "failures": self._failures,
            "open": self._opened_at is not None and not self.allow_request(),
            "opened_at": self._opened_at,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
        }
