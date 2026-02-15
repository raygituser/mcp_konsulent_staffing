from __future__ import annotations

from app.prompts import looks_clean


def test_looks_clean_allows_neutral_summary():
    s = "Fant 1 konsulent med minst 50% tilgjengelighet og ferdigheten 'Python'. Anna K. har 60% tilgjengelighet."
    assert looks_clean(s)


def test_looks_clean_rejects_profanity():
    assert not looks_clean("Dette er faen meg dårlig")


def test_looks_clean_allows_no_matches():
    assert looks_clean("Fant 0 konsulenter med minst 50% tilgjengelighet og ferdigheten 'Python'.")