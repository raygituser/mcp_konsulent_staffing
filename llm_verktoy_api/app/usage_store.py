from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, asdict
from typing import Deque, Dict, Any, Optional, List
from collections import deque

import redis as redis_lib

from app.core.settings import settings


@dataclass
class UsageEvent:
    ts: float
    request_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    cached_tokens: int = 0
    cache_hit: bool = False


class UsageStore:
    """In-memory usage store. If Redis is enabled, we mirror:
    - rolling event list (for live stats)
    - daily cost/tokens counters (for budget guards)
    """

    def __init__(self, maxlen: int = 200):
        self._events: Deque[UsageEvent] = deque(maxlen=maxlen)
        self._redis: Optional[redis_lib.Redis] = None
        if settings.redis_enabled:
            self._redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

    def add(self, evt: UsageEvent) -> None:
        self._events.appendleft(evt)
        if self._redis:
            day = dt.date.today().isoformat()
            pipe = self._redis.pipeline()
            pipe.incrbyfloat(f"usage:cost:{day}", evt.cost)
            pipe.incrby(f"usage:tokens:{day}", int(evt.total_tokens))
            pipe.lpush("usage:events:v1", json.dumps(asdict(evt), ensure_ascii=False))
            pipe.ltrim("usage:events:v1", 0, 199)
            # keep daily counters for ~10 days
            pipe.expire(f"usage:cost:{day}", 60 * 60 * 24 * 10)
            pipe.expire(f"usage:tokens:{day}", 60 * 60 * 24 * 10)
            pipe.expire("usage:events:v1", 60 * 60 * 6)
            pipe.execute()

    def list(self) -> List[Dict[str, Any]]:
        # Prefer Redis list for "live stats" across restarts
        if self._redis:
            try:
                raw = self._redis.lrange("usage:events:v1", 0, 199)
                out = []
                for r in raw:
                    try:
                        out.append(json.loads(r))
                    except Exception:
                        continue
                if out:
                    return out
            except Exception:
                pass
        return [asdict(e) for e in list(self._events)]

    def daily_cost(self) -> float:
        day = dt.date.today().isoformat()
        if self._redis:
            v = self._redis.get(f"usage:cost:{day}")
            return float(v) if v else 0.0
        return sum(e.cost for e in self._events if dt.date.fromtimestamp(e.ts).isoformat() == day)

    def daily_tokens(self) -> int:
        day = dt.date.today().isoformat()
        if self._redis:
            v = self._redis.get(f"usage:tokens:{day}")
            return int(float(v)) if v else 0
        return sum(e.total_tokens for e in self._events if dt.date.fromtimestamp(e.ts).isoformat() == day)

    def summary(self) -> Dict[str, Any]:
        return {"daily_cost_credits": self.daily_cost(), "daily_tokens": self.daily_tokens(), "events": self.list()}
