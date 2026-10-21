"""Audit trail + notifications. Metadata is always passed through `redact`; callers must never pass form values."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.redact import redact, redact_text
from app.models import AuditLog, Notification


def record(db: Session, event_type: str, summary: str = "", *, entity_type: str = "", entity_id: int | None = None,
           meta: dict[str, Any] | None = None) -> AuditLog:
    row = AuditLog(event_type=event_type, entity_type=entity_type, entity_id=entity_id,
                   summary=redact_text(summary)[:500], meta=redact(meta or {}))
    db.add(row)
    return row


def notify(db: Session, title: str, body: str = "", *, kind: str = "info", application_id: int | None = None) -> Notification:
    n = Notification(kind=kind, title=title[:200], body=redact_text(body)[:1000], application_id=application_id)
    db.add(n)
    return n
