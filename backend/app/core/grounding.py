"""Grounding checks for model output. Output is untrusted: it may only use confirmed facts, and may not invent numbers."""
from __future__ import annotations

import re

_NUM = re.compile(r"\b\d[\d,.]*\b%?")
_NUM_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twelve", "twenty", "hundred", "thousand", "million"}


def numeric_tokens(text: str) -> set[str]:
    out = set()
    for m in _NUM.finditer(text or ""):
        tok = m.group(0).rstrip(".,").replace(",", "")
        if tok:
            out.add(tok)
    return out


def unsupported_numbers(answer: str, fact_texts: list[str], extra_allowed: list[str] | None = None) -> set[str]:
    """Numbers (years, percentages, counts, ...) in `answer` that appear in none of the supporting facts."""
    allowed: set[str] = set()
    for t in [*fact_texts, *(extra_allowed or [])]:
        allowed |= numeric_tokens(t)
    return {n for n in numeric_tokens(answer) if n not in allowed}


def invalid_fact_ids(ids: list[str], allowed: set[str]) -> list[str]:
    return [i for i in ids if i not in allowed]
