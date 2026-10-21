"""Redaction for logs and audit metadata. Passwords, tokens, cookies and verification codes never reach logs."""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import SecretStr

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|session|credential|otp|mfa|verification[_-]?code|"
    r"auth[_-]?code|bearer|private[_-]?key)",
    re.I,
)
_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    (re.compile(r"(?i)\b(password|passwd|pwd|api[_-]?key|token|secret|cookie|code)\s*[=:]\s*\S+"), r"\1=" + REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\b(?:ghp|gho|xox[bap])-?[A-Za-z0-9_]{16,}"), REDACTED),
]


def redact_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact(value: Any) -> Any:
    """Recursively redact: values under sensitive-looking keys are replaced; free text is pattern-scrubbed."""
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, dict):
        return {k: (REDACTED if _SENSITIVE_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Attach to the root logger so nothing sensitive is written even by accident."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
        except Exception:  # never break logging
            pass
        return True
