"""Everything that comes from outside (web pages, job descriptions, PDFs, DOCX, e-mails) is untrusted DATA.

It is sanitized, scanned for instruction-like text, and wrapped in delimiters before any model sees it. No code path lets
external content change settings, authorization or workflow state: those only change through explicit, user-initiated API calls.
"""
from __future__ import annotations

import re
import unicodedata

_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069]
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any |the )?(previous|prior|above|earlier|your) (instructions|prompts?|rules)",
    r"forget (everything|all|your) (above|previous|instructions)",
    r"you are (now )?(a |an )?(different|new) (ai|assistant|agent|model)",
    r"(reveal|show|print|send|output|leak) (me )?(your |the )?(system prompt|api[_ -]?key|secrets?|passwords?|credentials|tokens?)",
    r"(set|change|switch|enable|turn on)\b.{0,40}\b(submission[_ -]?mode|auto[_ -]?submit|authorization|approval)",
    r"(auto[_ -]?submit|approve) (this|the) application",
    r"\b(ai|llm|assistant|automation|agent|bot)s?\b.{0,30}\b(must|should|shall|are required to|please)\b.{0,60}\b(submit|approve|accept|agree|certify|confirm)\b",
    r"(^|\n)\s*(system|assistant)\s*:",
    r"</?\s*(system|instructions?)\s*>",
    r"do not (tell|inform|alert|notify) the user",
]
_INJECTION_RE = [re.compile(p, re.I) for p in _INJECTION_PATTERNS]

DELIM_OPEN = "<<<UNTRUSTED_DATA"
DELIM_CLOSE = "<<<END_UNTRUSTED_DATA>>>"


def sanitize_external_text(text: str, max_len: int = 50_000) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_INVISIBLE)
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_len]


def scan_for_injection(text: str) -> list[str]:
    """Returns the matched snippets (for flagging/UI). Detection never blocks the data; it only labels it."""
    hits: list[str] = []
    for rx in _INJECTION_RE:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0).strip()[:120])
    return hits


def wrap_untrusted(name: str, text: str) -> str:
    """Delimit external text so a model can tell data from instructions; neutralize delimiter look-alikes inside it."""
    safe = text.replace("<<<", "< < <").replace(">>>", "> > >")
    return f"{DELIM_OPEN} name={name!r}>>>\n{safe}\n{DELIM_CLOSE}"
