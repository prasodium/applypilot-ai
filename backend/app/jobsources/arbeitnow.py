"""Arbeitnow public job-board API (https://www.arbeitnow.com/api/job-board-api): free, no API key.

Capabilities are deliberately narrow: SEARCH ONLY. Listings are read-only and applying is a manual handoff to the listing page.
The published terms do not state rate limits or attribution rules, so this adapter is conservative: it is disabled until the user
enables it, makes at most one request per search, caches the response for an hour, and always records the source URL.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.skills import find_skills
from app.core.untrusted import scan_for_injection
from app.jobsources.base import JobSourceAdapter, RawJob, SearchQuery, SourceCapabilities, SourceError
from app.services.job_parser import detect_arrangement, html_to_text, split_sections

API_URL = "https://www.arbeitnow.com/api/job-board-api"
CACHE_SECONDS = 3600


class ArbeitnowAdapter(JobSourceAdapter):
    name = "arbeitnow"
    display_name = "Arbeitnow (public job board API)"
    capabilities = SourceCapabilities(
        search=True, fetch_by_url=False, provides_application_url=True, automated_apply=False, requires_auth=False,
        docs_url="https://www.arbeitnow.com/blog/job-board-api",
        last_tested="2026-10-21 (one live read-only search; fields mapped correctly)",
        notes="Read-only search of public listings; apply on the listing page yourself. Listings are mostly in Germany/Europe. "
              "Terms do not state rate limits or attribution rules: results are cached for an hour and attributed to Arbeitnow.",
    )
    _cache: tuple[float, list[dict[str, Any]]] | None = None

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def _fetch(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if ArbeitnowAdapter._cache and now - ArbeitnowAdapter._cache[0] < CACHE_SECONDS and self._transport is None:
            return ArbeitnowAdapter._cache[1]
        try:
            with httpx.Client(timeout=15.0, transport=self._transport, headers={"User-Agent": "ApplyPilotBot/0.1"}, trust_env=False) as c:
                r = c.get(API_URL)
                r.raise_for_status()
                data = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError("Arbeitnow could not be reached right now.") from exc
        if self._transport is None:
            ArbeitnowAdapter._cache = (now, data)
        return data

    def search(self, q: SearchQuery) -> list[RawJob]:
        out: list[RawJob] = []
        for j in self._fetch():
            title, company = str(j.get("title", "")).strip(), str(j.get("company_name", "")).strip()
            loc, desc_html = str(j.get("location", "")), str(j.get("description", ""))
            tags = " ".join(map(str, j.get("tags") or []))
            blob = f"{title} {company} {tags} {loc}".lower()
            if q.query and not all(w in blob or w in desc_html.lower() for w in q.query.lower().split()):
                continue
            if q.location and q.location.lower() not in loc.lower():
                continue
            if q.remote_only and not j.get("remote"):
                continue
            if not title or not j.get("url"):
                continue
            desc = html_to_text(desc_html)
            sec = split_sections(desc)
            ts = j.get("created_at")
            out.append(RawJob({
                "company": company or "Unknown company", "title": title, "location": loc,
                "work_arrangement": "remote" if j.get("remote") else detect_arrangement(loc),
                "employment_type": ", ".join(map(str, j.get("job_types") or []))[:60], "seniority": "",
                "description": desc, "required_qualifications": sec["required"], "preferred_qualifications": sec["preferred"],
                "responsibilities": sec["responsibilities"], "posted_at": datetime.fromtimestamp(int(str(ts)), UTC) if str(ts).isdigit() else None,
                "source_name": "arbeitnow", "source_url": str(j["url"]), "application_url": str(j["url"]), "status": "open",
                "external_id": str(j.get("slug", ""))[:200], "flags": sorted({f"possible_prompt_injection: {h}" for h in scan_for_injection(desc)}),
                "is_demo": False, "_skills_required": find_skills("\n".join(sec["required"])),
                "_skills_preferred": find_skills("\n".join(sec["preferred"])),
            }))
            if len(out) >= q.limit:
                break
        return out
