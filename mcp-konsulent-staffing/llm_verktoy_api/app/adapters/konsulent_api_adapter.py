from __future__ import annotations

import logging
from typing import List

import httpx

from app.core.models import Konsulent, Result, Ok, Err, ServiceError, ErrorCode
from app.core.resilience import CircuitBreaker, with_retry, RetryConfig

logger = logging.getLogger(__name__)


class KonsulentApiAdapter:
    """Adapter for konsulent-api service (retry + circuit breaker)."""

    def __init__(self, base_url: str, timeout: int = 10, circuit_breaker: CircuitBreaker | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="konsulent-api",
            failure_threshold=5,
            recovery_timeout_seconds=30,
        )
        self._retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.3)

    async def get_all(self) -> Result[List[Konsulent], ServiceError]:
        if not self.circuit_breaker.allow_request():
            logger.warning("konsulent_api_circuit_open")
            return Err(ServiceError(code=ErrorCode.CIRCUIT_BREAKER_OPEN, message="Konsulent API circuit open"))

        try:
            konsulenter = await with_retry(
                self._fetch,
                config=self._retry_config,
                retryable_exceptions=(httpx.TransportError, httpx.TimeoutException),
            )
            await self.circuit_breaker.record_success()
            return Ok(konsulenter)
        except httpx.TimeoutException:
            await self.circuit_breaker.record_failure()
            return Err(ServiceError(code=ErrorCode.KONSULENT_API_TIMEOUT, message=f"Timeout after {self.timeout}s"))
        except Exception as e:
            await self.circuit_breaker.record_failure()
            return Err(ServiceError(code=ErrorCode.KONSULENT_API_UNAVAILABLE, message=str(e)))

    async def _fetch(self) -> List[Konsulent]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/konsulenter")
            resp.raise_for_status()
            data = resp.json()
            return [
                Konsulent(
                    id=k["id"],
                    navn=k["navn"],
                    ferdigheter=tuple([s.lower() for s in k["ferdigheter"]]),
                    belastning_prosent=int(k["belastning_prosent"]),
                )
                for k in data
            ]

    def get_circuit_status(self) -> dict:
        return self.circuit_breaker.get_stats()
