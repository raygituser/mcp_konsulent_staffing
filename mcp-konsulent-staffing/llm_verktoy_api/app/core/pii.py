from __future__ import annotations

import re
from typing import Any


_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){7,14}\b")
_KEYLIKE = re.compile(r"\b(sk-[A-Za-z0-9]{10,}|or-[A-Za-z0-9]{10,})\b")


def scrub_pii(value: Any) -> Any:
    """Best-effort scrubber for logs/audit. Keep it simple and deterministic."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [scrub_pii(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_pii(v) for k, v in value.items()}
    s = str(value)
    s = _EMAIL.sub("[EMAIL]", s)
    s = _PHONE.sub("[PHONE]", s)
    s = _KEYLIKE.sub("[KEY]", s)
    return s
