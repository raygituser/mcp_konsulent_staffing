from __future__ import annotations

"""Semantic similarity + semantic caching.

This module implements a *free* and dependency-light vector similarity approach.

Instead of requiring external embedding models (which can be large / slow / need downloads),
we use a deterministic hashing vectorizer (feature hashing) to map text -> a fixed-size
vector, and cosine similarity to compare queries.

If Redis is enabled, we persist entries in a Redis list so we can use them as:

1) short-term guidance: retrieve top-K similar past *approved* summaries and include them
   as few-shot examples in the prompt.
2) long-term semantic cache: if similarity exceeds a threshold, return the cached summary
   instead of calling the LLM (saves cost).

This is "semantic" in the sense of vector similarity over token features.
For production-grade vector search you would typically use Redis Stack (RediSearch) or a
dedicated vector DB. This implementation keeps the repo runnable on first try.
"""

import base64
import json
import math
import re
import time
from array import array
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


_WORD_RE = re.compile(r"[\w\-\+]+", re.UNICODE)


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "") if len(t) > 1]


def hash_vector(text: str, *, dims: int = 256) -> Tuple[List[int], float]:
    """Return (vector, norm) using feature hashing.

    Vector is a list[int] of length `dims`.
    """
    vec = [0] * dims
    for tok in _tokens(text):
        h = hash(tok)
        idx = h % dims
        # signed update to reduce collisions bias
        vec[idx] += 1 if (h & 1) else -1
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return vec, norm


def cosine_similarity(a: List[int], a_norm: float, b: List[int], b_norm: float) -> float:
    dot = 0
    for i in range(min(len(a), len(b))):
        dot += a[i] * b[i]
    return float(dot) / float(a_norm * b_norm)


def pack_vector(vec: List[int]) -> str:
    """Pack a small int vector into base64 for Redis storage."""
    arr = array("h", [max(-32768, min(32767, int(v))) for v in vec])
    return base64.b64encode(arr.tobytes()).decode("ascii")


def unpack_vector(b64: str, *, dims: int = 256) -> List[int]:
    raw = base64.b64decode(b64.encode("ascii"))
    arr = array("h")
    arr.frombytes(raw)
    out = list(arr)
    if len(out) < dims:
        out.extend([0] * (dims - len(out)))
    return out[:dims]


@dataclass
class SemanticEntry:
    ts: float
    fingerprint: str
    query: str
    # Stored full LLM payload (must include at least "sammendrag", "listed_names", "listed_availability")
    obj_json: str
    vec_b64: str
    norm: float
    meta: Dict[str, Any]


class SemanticCache:
    def __init__(
        self,
        *,
        redis=None,
        redis_key: str = "semcache:v1",
        dims: int = 256,
        max_entries: int = 500,
    ):
        self._redis = redis
        self._key = redis_key
        self._dims = dims
        self._max_entries = max_entries

    def enabled(self) -> bool:
        return self._redis is not None

    def put(self, *, fingerprint: str, query: str, obj: Dict[str, Any], meta: Dict[str, Any]) -> None:
        if not self._redis:
            return
        vec, norm = hash_vector(query, dims=self._dims)
        entry = SemanticEntry(
            ts=time.time(),
            fingerprint=fingerprint,
            query=query,
            obj_json=json.dumps(obj, ensure_ascii=False),
            vec_b64=pack_vector(vec),
            norm=float(norm),
            meta=meta or {},
        )
        try:
            self._redis.lpush(self._key, json.dumps(asdict(entry), ensure_ascii=False))
            self._redis.ltrim(self._key, 0, self._max_entries - 1)
            # keep for a while; long-term store is still limited by max_entries
            self._redis.expire(self._key, 60 * 60 * 24 * 7)  # 7 days
        except Exception:
            return

    def _load_entries(self, limit: int = 200) -> List[SemanticEntry]:
        if not self._redis:
            return []
        try:
            raw = self._redis.lrange(self._key, 0, max(0, limit - 1))
        except Exception:
            return []
        out: List[SemanticEntry] = []
        for r in raw:
            try:
                d = json.loads(r)
                out.append(
                    SemanticEntry(
                        ts=float(d.get("ts", 0.0) or 0.0),
                        fingerprint=str(d.get("fingerprint", "")),
                        query=str(d.get("query", "")),
                        obj_json=str(d.get("obj_json", "{}")),
                        vec_b64=str(d.get("vec_b64", "")),
                        norm=float(d.get("norm", 1.0) or 1.0),
                        meta=dict(d.get("meta") or {}),
                    )
                )
            except Exception:
                continue
        return out

    def top_k_similar(
        self,
        *,
        fingerprint: str,
        query: str,
        k: int = 3,
        limit_scan: int = 200,
    ) -> List[Tuple[SemanticEntry, float]]:
        """Return top-k similar entries (same fingerprint) with similarity scores."""
        vec, norm = hash_vector(query, dims=self._dims)
        entries = [e for e in self._load_entries(limit_scan) if e.fingerprint == fingerprint]
        scored: List[Tuple[SemanticEntry, float]] = []
        for e in entries:
            try:
                e_vec = unpack_vector(e.vec_b64, dims=self._dims)
                sim = cosine_similarity(vec, norm, e_vec, float(e.norm or 1.0))
                scored.append((e, sim))
            except Exception:
                continue
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[: max(0, k)]

    def maybe_get_cached(
        self,
        *,
        fingerprint: str,
        query: str,
        threshold: float,
        limit_scan: int = 200,
    ) -> Optional[Tuple[Dict[str, Any], float, Dict[str, Any]]]:
        """Return (obj, similarity, meta) if best hit >= threshold."""
        best = self.top_k_similar(fingerprint=fingerprint, query=query, k=1, limit_scan=limit_scan)
        if not best:
            return None
        entry, sim = best[0]
        if sim >= threshold:
            try:
                obj = json.loads(entry.obj_json or "{}")
            except Exception:
                return None
            return obj, sim, entry.meta
        return None

    def context_examples(
        self,
        *,
        fingerprint: str,
        query: str,
        k: int = 3,
        limit_scan: int = 200,
    ) -> List[Tuple[str, str]]:
        """Return (example_query, example_sammendrag) pairs for prompt guidance."""
        out: List[Tuple[str, str]] = []
        for e, _sim in self.top_k_similar(fingerprint=fingerprint, query=query, k=k, limit_scan=limit_scan):
            try:
                obj = json.loads(e.obj_json or "{}")
                s = str(obj.get("sammendrag", "")).strip()
                if s:
                    out.append((e.query, s))
            except Exception:
                continue
        return out
