from __future__ import annotations

import asyncio

from app.core.resilience import CircuitBreaker


def test_circuit_breaker_opens_and_recovers():
    cb = CircuitBreaker(name="t", failure_threshold=2, recovery_timeout_seconds=0.1)

    assert cb.allow_request()
    asyncio.run(cb.record_failure())
    assert cb.allow_request()
    asyncio.run(cb.record_failure())
    assert not cb.allow_request()  # open

    # wait for recovery window
    import time

    time.sleep(0.11)
    assert cb.allow_request()  # half-open
    asyncio.run(cb.record_success())
    assert cb.allow_request()