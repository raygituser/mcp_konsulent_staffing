from __future__ import annotations

import re
from typing import List, Dict, Any

# A pragmatic "no negativity / no profanity" filter.
# This is intentionally conservative for interview/demo reliability.
PROFANITY_WORDS = [
    # English
    "idiot", "stupid", "dumb", "hate", "kill", "shit", "fuck", "bitch", "asshole",
    "useless", "worst", "crap", "damn",
    # Norwegian (common)
    "faen", "f***", "fuck", "dritt", "jævel", "jævla", "helvete", "idiot", "mongo",
    "hore", "kuk", "pikk", "satan",
]

NEGATIVE_WORDS = [
    # English
    "terrible", "awful", "bad", "poor", "incompetent", "lazy", "problem", "warning",
    # Norwegian
    "dårlig", "elendige", "elendig", "verst", "hater", "hat", "idiot",
    "inkompetent", "lat", "problem", "problematisk", "advarsel", "skandale",
    "svak", "mislykket",
]

# We allow neutral phrases about "ingen funnet" but avoid negative characterisation of people.
_ALLOWED_NEGATIVE_CONTEXT = {"ingen", "ingen.", "ingen,"}

def sammendrag_json_schema() -> Dict[str, Any]:
    # Strict schema to help structured outputs.
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sammendrag": {"type": "string", "minLength": 10, "maxLength": 500},
            "listed_names": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 30},
            "listed_availability": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 100}, "minItems": 0, "maxItems": 30},
        },
        "required": ["sammendrag", "listed_names", "listed_availability"],
    }


def build_prompt(
    *,
    min_tilgjengelighet: int,
    pakrevd_ferdighet: str,
    konsulenter: List[dict],
    total_matchende: int,
    truncated: bool,
    prompt_style: str = "strict",
    examples: List[tuple[str, str]] | None = None,
) -> str:
    # Universal prompting rules: role, goal, constraints, examples.
    note = ""
    if truncated:
        note = f"OBS: Dette er topp-{len(konsulenter)} av totalt {total_matchende} matchende (sortert på tilgjengelighet)."

    examples_text = ""
    if examples:
        # Few-shot guidance from earlier approved summaries (semantic similarity).
        # Keep it short to avoid inflating tokens/cost.
        rows = []
        for q, s in examples[:3]:
            rows.append({"query": q, "sammendrag": s})
        examples_text = f"\nEKSEMPLER (for stil, ikke fakta): {rows}\n"

    style_hint = {
        "strict": "Hold det kort og faktabasert.",
        "friendly": "Vær varm og samarbeidsorientert, men fortsatt profesjonell.",
        "bullet": "Bruk 1 setning + korte punkt, men fortsatt som ren tekst inne i JSON-feltet.",
    }.get((prompt_style or "strict").lower(), "Hold det kort og faktabasert.")

    # We require pure JSON (no markdown) and we explicitly prohibit profanity and negative characterisation.
    return f"""Du er en intern AI-assistent som lager et kort, profesjonelt sammendrag på norsk.

MÅL:
- Lag et menneskeleselig sammendrag om tilgjengelige konsulenter.

DATA:
- Krav: minst {min_tilgjengelighet}% tilgjengelighet og ferdighet '{pakrevd_ferdighet}'.
- Konsulenter (liste): {konsulenter}

{note}

{examples_text}

FORMAT (VIKTIG):
- Returner KUN gyldig JSON som matcher schemaet (ingen markdown, ingen ekstra tekst).
- listed_names og listed_availability skal matche konsulentene som omtales i sammendraget.

TONE/REGLER (VIKTIG):
- Sammendraget må være høflig, nøytralt og profesjonelt.
- Ikke bruk bannord, skjellsord, eller negative karakteristikker om personer.
- Kun fakta fra input: navn og prosent.
- Stil: {style_hint}

HINT:
- Start sammendraget med: "Fant X konsulenter ..."
- Hvis ingen matcher: start med "Fant 0 konsulenter ..." og avslutt kort.
"""


def _tokenize(text: str) -> List[str]:
    t = text.lower()
    t = re.sub(r"[^\w\s%]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t.split(" ") if t else []


def looks_clean(text: str) -> bool:
    tokens = _tokenize(text)
    # Profanity: immediate reject
    for w in PROFANITY_WORDS:
        if w in tokens or w in text.lower():
            return False

    # Negative words: reject unless context is allowed (very limited)
    for w in NEGATIVE_WORDS:
        if w in tokens:
            # allow "ingen" case to describe no matches, but that's not a negative about people
            if w in _ALLOWED_NEGATIVE_CONTEXT:
                continue
            return False

    return True
