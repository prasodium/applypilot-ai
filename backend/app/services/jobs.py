"""Job import, search, duplicate detection, filtering, matching and shortlist."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.skills import find_skills
from app.core.text import slug_key
from app.core.untrusted import sanitize_external_text, scan_for_injection
from app.db import utcnow
from app.errors import Forbidden, NotFound, Unprocessable
from app.jobsources.base import SearchQuery, SourceError
from app.jobsources.registry import search_adapters
from app.models import JobListing, JobMatch
from app.schemas import JobImportIn, JobOut, JobSearchIn, MatchComponent, MatchOut
from app.services import audit, job_parser, matching
from app.services import profile as profile_svc
from app.services.urlfetch import fetch_page

USER_FIELDS = {"company", "title", "location", "work_arrangement", "employment_type", "description", "application_url", "status"}
_ATTRIBUTION = {"arbeitnow": "Listings provided by Arbeitnow (https://www.arbeitnow.com). Apply on the listing page.",
                "mock": "Synthetic demo data. No real employer is involved."}


def canonical_url(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return url
    return f"{p.scheme}://{p.netloc.lower()}{p.path.rstrip('/')}"


def dedupe_key(company: str, title: str, location: str) -> str:
    base = slug_key(re.sub(r"\(demo\)", "", company, flags=re.I), title, location.split(",")[0])
    return hashlib.sha256(base.encode()).hexdigest()


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if not k.startswith("_")}


def upsert(db: Session, fields: dict[str, Any]) -> tuple[JobListing, bool, int | None]:
    """Insert a listing unless an equivalent one exists (same company/title/location, or same canonical URL)."""
    f = _clean(fields)
    f["description"] = sanitize_external_text(f.get("description", ""), 60_000)
    f["flags"] = sorted(set(f.get("flags") or []) | {f"possible_prompt_injection: {h}" for h in scan_for_injection(f["description"])})
    key = dedupe_key(f["company"], f["title"], f.get("location", ""))
    existing = db.scalar(select(JobListing).where(JobListing.dedupe_key == key))
    if existing is None and f.get("source_url") and not f["source_url"].startswith(("mock://", "manual://")):
        existing = db.scalar(select(JobListing).where(JobListing.source_url == f["source_url"]))
    if existing is not None:
        return existing, False, existing.id
    job = JobListing(**f, dedupe_key=key, retrieved_at=f.get("retrieved_at") or utcnow())
    db.add(job)
    db.flush()
    audit.record(db, "job_imported", f"Job imported from {job.source_name}", entity_type="job", entity_id=job.id,
                 meta={"source": job.source_name, "flags": len(job.flags)})
    return job, True, None


def _ensure_source_allowed(db: Session, source: str) -> None:
    allowed = profile_svc.get_preferences(db).allowed_sources
    if source not in allowed:
        raise Forbidden(f"The '{source}' source is not enabled. Enable it in Settings first.", code="source_not_allowed")


def import_job(db: Session, body: JobImportIn, settings: Settings) -> tuple[JobListing, bool, int | None, list[str]]:
    _ensure_source_allowed(db, body.source)
    notes: list[str] = []
    html, text, url = body.html, body.text, body.url
    if url and not (html or text):
        mock_origin = "{0.scheme}://{0.netloc}".format(urlparse(settings.mock_employer_base_url))
        url, html = fetch_page(url, allow_origins={mock_origin})
    try:
        if html or text:
            fields = job_parser.parse_job(html=html, text=text, url=url or "manual://pasted", source=body.source)
        else:
            fields = {"company": "", "title": "", "source_name": body.source, "source_url": "manual://entered", "description": "",
                      "required_qualifications": [], "preferred_qualifications": [], "responsibilities": [], "flags": [],
                      "work_arrangement": "unknown", "employment_type": "", "seniority": "", "location": "", "status": "open"}
    except ValueError as exc:
        raise Unprocessable("No job title could be found. Add the title and company yourself.", code="no_title") from exc
    for k, v in body.fields.items():
        if k in USER_FIELDS and isinstance(v, str):
            fields[k] = v.strip()[:60_000 if k == "description" else 1000]
    if not fields.get("title"):
        raise Unprocessable("A job title is required.", code="no_title")
    fields.setdefault("company", "Unknown company")
    if not fields.get("company"):
        fields["company"] = "Unknown company"
    job, created, dup = upsert(db, fields)
    if not created:
        notes.append(f"This job already exists (id {job.id}); nothing was added.")
    else:
        compute_and_store_match(db, job.id)
    return job, created, dup, notes


def search(db: Session, body: JobSearchIn, settings: Settings) -> dict[str, Any]:
    _ensure_source_allowed(db, body.source)
    adapter = search_adapters()[body.source]
    try:
        raw = adapter.search(SearchQuery(body.query, body.location, body.remote_only, body.limit))
    except SourceError as exc:
        raise Unprocessable(str(exc), code="source_unavailable") from exc
    items, created, dups = [], 0, 0
    for r in raw:
        f = dict(r.fields)
        if f.get("application_url", "").startswith("{MOCK}"):
            f["application_url"] = settings.mock_employer_base_url.rstrip("/") + f["application_url"].removeprefix("{MOCK}")
        job, was_new, _ = upsert(db, f)
        if was_new:
            compute_and_store_match(db, job.id)
        created += was_new
        dups += (not was_new)
        items.append(job)
    audit.record(db, "jobs_searched", f"Search on {body.source}: {len(items)} results", meta={"source": body.source, "new": created})
    return {"source": body.source, "items": items, "created": created, "duplicates": dups,
            "attribution": _ATTRIBUTION.get(body.source, "")}


def get_job(db: Session, job_id: int) -> JobListing:
    j = db.get(JobListing, job_id)
    if j is None:
        raise NotFound(f"Job {job_id} not found")
    return j


def to_out(job: JobListing) -> JobOut:
    out = JobOut.model_validate(job)
    out.match_score = job.match.score if job.match else None
    return out


def list_jobs(db: Session, *, q: str = "", source: str = "", status: str = "", user_status: str = "", arrangement: str = "",
              location: str = "", min_score: float | None = None, sort: str = "newest", page: int = 1, page_size: int = 25) -> tuple[list[JobListing], int]:
    stmt = select(JobListing).outerjoin(JobMatch, JobMatch.job_id == JobListing.id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(JobListing.title).like(like), func.lower(JobListing.company).like(like),
                              func.lower(JobListing.description).like(like)))
    for col, val in ((JobListing.source_name, source), (JobListing.status, status), (JobListing.user_status, user_status),
                     (JobListing.work_arrangement, arrangement)):
        if val:
            stmt = stmt.where(col == val)
    if location:
        stmt = stmt.where(func.lower(JobListing.location).like(f"%{location.lower()}%"))
    if min_score is not None:
        stmt = stmt.where(JobMatch.score >= min_score)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(JobMatch.score.desc().nullslast(), JobListing.id.desc()) if sort == "score" else stmt.order_by(JobListing.id.desc())
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), total


def set_user_status(db: Session, job_id: int, status: str) -> JobListing:
    j = get_job(db, job_id)
    j.user_status = status
    audit.record(db, f"job_{status}", f"Job marked {status}", entity_type="job", entity_id=job_id)
    return j


def analyze(db: Session, job_id: int) -> JobListing:
    """Re-extract qualifications/responsibilities from the stored description (e.g. after the user edits it)."""
    j = get_job(db, job_id)
    sec = job_parser.split_sections(sanitize_external_text(j.description))
    if sec["required"] or sec["preferred"] or sec["responsibilities"]:
        j.required_qualifications, j.preferred_qualifications, j.responsibilities = sec["required"], sec["preferred"], sec["responsibilities"]
    j.flags = sorted({f"possible_prompt_injection: {h}" for h in scan_for_injection(j.description)})
    audit.record(db, "job_analyzed", "Job analyzed", entity_type="job", entity_id=job_id,
                 meta={"required_skills": find_skills("\n".join(j.required_qualifications))})
    compute_and_store_match(db, job_id)
    return j


# ------------------------------------------------------------------ matching glue
def candidate_view(db: Session) -> matching.CandidateView:
    p = profile_svc.fresh_profile(db)
    prefs = profile_svc.get_preferences(db)
    exp = [x for x in p.experience if x.confirmed]
    proj = [x for x in p.projects if x.confirmed]
    evidence = " ".join([" ".join([x.title, x.employer, *x.responsibilities, *x.achievements, *x.technologies]) for x in exp]
                        + [" ".join([x.name, x.summary, x.contribution, *x.technologies, *x.related_skills]) for x in proj])
    resp = " ".join([" ".join([*x.responsibilities, *x.achievements]) for x in exp] + [" ".join([x.summary, x.contribution]) for x in proj])
    months = sum(matching.months_between(x.start_date, x.end_date, x.is_current) for x in exp)
    return matching.CandidateView(
        skills={s.name.lower() for s in p.skills if s.confirmed}, evidence_text=evidence, responsibilities_text=resp,
        titles=[x.title for x in exp], degrees=[f"{e.degree} {e.major}" for e in p.education if e.confirmed],
        years_experience=round(months / 12, 1), has_experience_or_projects=bool(exp or proj), target_roles=prefs.target_roles,
        locations=prefs.locations, remote_preference=prefs.remote_preference, employment_types=prefs.employment_types)


def job_view(j: JobListing) -> matching.JobView:
    return matching.JobView(title=j.title, required_text="\n".join(j.required_qualifications), required_lines=j.required_qualifications,
                            preferred_lines=j.preferred_qualifications, responsibilities=j.responsibilities, description=j.description,
                            work_arrangement=j.work_arrangement, location=j.location, employment_type=j.employment_type,
                            seniority=j.seniority)


def compute_and_store_match(db: Session, job_id: int) -> JobMatch:
    job = get_job(db, job_id)
    prefs = profile_svc.get_preferences(db)
    res = matching.compute_match(job_view(job), candidate_view(db), prefs.match_weights or None)
    breakdown = {"components": [c.__dict__ for c in res.components], "unknowns": res.unknowns, "disclaimer": res.disclaimer}
    weights = {c.key: c.weight for c in res.components}
    m = db.scalar(select(JobMatch).where(JobMatch.job_id == job_id))
    fp = profile_svc.fingerprint(db)
    if m is None:
        m = JobMatch(job_id=job_id, score=res.score, breakdown=breakdown, weights=weights, profile_fingerprint=fp)
        db.add(m)
    else:
        m.score, m.breakdown, m.weights, m.profile_fingerprint, m.computed_at = res.score, breakdown, weights, fp, utcnow()
    db.flush()
    db.refresh(job)
    return m


def match_out(db: Session, m: JobMatch) -> MatchOut:
    b = m.breakdown
    comps = [MatchComponent(key=c["key"], label=c["label"], score=c["score"], weight=c["weight"], explanation=c["explanation"],
                            matched=c["matched"], gaps=c["gaps"]) for c in b["components"]]
    return MatchOut(score=m.score, components=comps, unknowns=b["unknowns"], disclaimer=b["disclaimer"], computed_at=m.computed_at,
                    stale=m.profile_fingerprint != profile_svc.fingerprint(db))


def rematch_all(db: Session) -> int:
    ids = db.scalars(select(JobListing.id)).all()
    for i in ids:
        compute_and_store_match(db, i)
    return len(ids)


_ = datetime
