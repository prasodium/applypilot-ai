"""Small text helpers shared by parsing, matching and answering."""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


def slug_key(*parts: str) -> str:
    return "|".join(re.sub(r"[^a-z0-9]+", " ", norm(p)).strip() for p in parts)


def word_count(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")


def valid_partial_date(s: str) -> bool:
    """YYYY, YYYY-MM or YYYY-MM-DD (resumes mostly carry month/year only). Empty is allowed."""
    return s == "" or bool(_DATE_RE.match(s))
