from __future__ import annotations

from app.jobsources.arbeitnow import ArbeitnowAdapter
from app.jobsources.base import JobSourceAdapter, SourceCapabilities
from app.jobsources.mock import MockJobSource

MANUAL_CAPS = SourceCapabilities(
    search=False, fetch_by_url=True, provides_application_url=True, automated_apply=False,
    notes="Import a single job from a URL (robots.txt respected, login-protected pages refused) or by pasting text/HTML. "
          "Applying on the employer's site is a manual handoff.",
)


def search_adapters() -> dict[str, JobSourceAdapter]:
    return {"mock": MockJobSource(), "arbeitnow": ArbeitnowAdapter()}


def describe_sources() -> list[dict]:
    rows = [{"name": "manual", "display_name": "Manual import (URL or pasted text)", **MANUAL_CAPS.as_dict()}]
    rows += [{"name": a.name, "display_name": a.display_name, **a.capabilities.as_dict()} for a in search_adapters().values()]
    return rows
