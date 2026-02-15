from __future__ import annotations

import asyncio
import time
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.settings import settings
from app.metrics import (
    openrouter_key_limit,
    openrouter_key_limit_remaining,
    openrouter_key_usage_total,
    openrouter_key_usage_daily,
    openrouter_key_usage_weekly,
    openrouter_key_usage_monthly,
    openrouter_key_is_free_tier,
    openrouter_key_monitor_last_success_unixtime,
    openrouter_key_monitor_failures_total,
    openrouter_key_present,
    dependency_up,
)

logger = logging.getLogger(__name__)


async def _fetch_key_info(api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch OpenRouter key accounting info.

    Endpoint: GET https://openrouter.ai/api/v1/key
    Returns USD usage/limits per key (helpful for daily/weekly manual tracking).
    """
    url = f"{settings.openrouter_base_url.rstrip('/')}/key"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=10.0)) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json() or {}
            data = payload.get("data") or {}
            return data
    except Exception as e:
        logger.warning("openrouter_key_monitor_failed: %s", e)
        return None


async def openrouter_key_monitor_loop() -> None:
    """Background loop that exports /api/v1/key fields as Prometheus gauges."""
    if not settings.openrouter_key_monitor_enabled:
        return

    # Ensure metrics exist in Prometheus even before the first successful poll.
    # (Grafana otherwise shows "No data" for gauges that have never been set.)
    openrouter_key_limit.set(0.0)
    openrouter_key_limit_remaining.set(0.0)
    openrouter_key_usage_total.set(0.0)
    openrouter_key_usage_daily.set(0.0)
    openrouter_key_usage_weekly.set(0.0)
    openrouter_key_usage_monthly.set(0.0)
    openrouter_key_is_free_tier.set(0.0)
    dependency_up.labels("openrouter_key").set(0)

    if not settings.openrouter_api_key:
        openrouter_key_present.set(0.0)
        return

    openrouter_key_present.set(1.0)

    while True:
        data = await _fetch_key_info(settings.openrouter_api_key)
        if data:
            # Mark dependency up
            dependency_up.labels("openrouter_key").set(1)

            # Record last successful poll time (useful for troubleshooting "No data").
            openrouter_key_monitor_last_success_unixtime.set(float(time.time()))

            # Values are in USD
            openrouter_key_limit.set(float(data.get("limit") or 0.0))
            openrouter_key_limit_remaining.set(float(data.get("limit_remaining") or 0.0))
            openrouter_key_usage_total.set(float(data.get("usage") or 0.0))
            openrouter_key_usage_daily.set(float(data.get("usage_daily") or 0.0))
            openrouter_key_usage_weekly.set(float(data.get("usage_weekly") or 0.0))
            openrouter_key_usage_monthly.set(float(data.get("usage_monthly") or 0.0))

            openrouter_key_is_free_tier.set(1.0 if bool(data.get("is_free_tier")) else 0.0)
        else:
            dependency_up.labels("openrouter_key").set(0)
            openrouter_key_monitor_failures_total.inc()

        await asyncio.sleep(max(10, int(settings.openrouter_key_poll_seconds or 60)))
