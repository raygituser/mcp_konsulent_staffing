from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Deque, Dict, Any, Optional, List

from .pii import scrub_pii

logger = logging.getLogger("audit")


@dataclass
class AuditEvent:
    ts: float
    request_id: str
    action: str
    details: Dict[str, Any]
    ok: bool
    error: Optional[str] = None


class AuditLog:
    """In-memory audit log (dev-mode).
    If Redis is provided, we also mirror events into a short Redis list for durability between restarts.
    """

    def __init__(self, maxlen: int = 200, redis=None, redis_key: str = "audit:events:v1"):
        self._events: Deque[AuditEvent] = deque(maxlen=maxlen)
        self._redis = redis
        self._redis_key = redis_key

    def add(self, request_id: str, action: str, details: Dict[str, Any], ok: bool, error: str | None = None) -> None:
        evt = AuditEvent(ts=time.time(), request_id=request_id, action=action, details=scrub_pii(details), ok=ok, error=error)
        self._events.appendleft(evt)

        # Log full event as JSON (so it shows fully in docker logs)
        try:
            logger.info(json.dumps({"type": "audit_event", **asdict(evt)}, ensure_ascii=False))
        except Exception:
            pass

        # Mirror into Redis (best-effort)
        if self._redis:
            try:
                self._redis.lpush(self._redis_key, json.dumps(asdict(evt), ensure_ascii=False))
                self._redis.ltrim(self._redis_key, 0, 199)
                self._redis.expire(self._redis_key, 60 * 60 * 6)  # keep for 6h
            except Exception:
                pass

    def list(self) -> List[Dict[str, Any]]:
        mem = [asdict(e) for e in list(self._events)]
        if self._redis:
            try:
                raw = self._redis.lrange(self._redis_key, 0, 199)
                parsed = []
                for r in raw:
                    try:
                        parsed.append(json.loads(r))
                    except Exception:
                        continue
                # Prefer Redis if it has data, else memory
                return parsed if parsed else mem
            except Exception:
                return mem
        return mem
