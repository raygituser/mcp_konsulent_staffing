from __future__ import annotations

from typing import Dict, Any, List, Tuple

from app.prompts import looks_clean


def validate_schema_obj(obj: Dict[str, Any], allowed: List[Tuple[str, int]]) -> Tuple[bool, str]:
    """Validate LLM output against business rules.
    allowed: list of (name, availability).
    """
    if not isinstance(obj, dict):
        return False, "not_a_dict"
    for k in ("sammendrag", "listed_names", "listed_availability"):
        if k not in obj:
            return False, f"missing_{k}"
    if not isinstance(obj["sammendrag"], str) or len(obj["sammendrag"].strip()) < 10:
        return False, "bad_sammendrag"
    if not looks_clean(obj["sammendrag"]):
        return False, "banned_words_detected"

    names = obj["listed_names"]
    avs = obj["listed_availability"]
    if not isinstance(names, list) or not isinstance(avs, list):
        return False, "bad_lists"
    if len(names) != len(avs):
        return False, "list_length_mismatch"

    allowed_set = {(n, a) for n, a in allowed}
    for n, a in zip(names, avs):
        if (n, a) not in allowed_set:
            return False, "name_or_availability_not_allowed"

    # Names should appear in summary
    for n in names:
        if n and n not in obj["sammendrag"]:
            return False, "name_missing_in_summary"

    return True, "ok"
