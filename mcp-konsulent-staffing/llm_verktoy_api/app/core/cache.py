from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable, Awaitable


@dataclass
class CacheItem:
    value: Any
    expires_at: float


class MemoryCache:
    def __init__(self):
        self._store: Dict[str, CacheItem] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        if time.time() >= item.expires_at:
            self._store.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = CacheItem(value=value, expires_at=time.time() + ttl_seconds)


async def cached_call(
    cache: MemoryCache,
    key: str,
    ttl_seconds: int,
    fn: Callable[[], Awaitable[Any]],
):
    hit = cache.get(key)
    if hit is not None:
        return hit, True
    value = await fn()
    cache.set(key, value, ttl_seconds=ttl_seconds)
    return value, False
