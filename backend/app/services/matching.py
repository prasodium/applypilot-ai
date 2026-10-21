"""Explainable job match score (0-100). Pure functions over plain data: no DB, no AI, fully unit-testable.

Only CONFIRMED profile facts are used. A component whose input is unknown is EXCLUDED and the remaining weights are
renormalized, so missing optional information never counts as a disqualifier. The score describes overlap between a profile
and a posting; it is not a prediction of hiring outcomes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.skills import find_skills

DEFAULT_WEIGHTS = {
    "required_skills": 30, "relevant_experience": 20, "education": 15, "responsibilities": 15,
    "preferred_skills": 10, "location_preferences": 5, "seniority_type": 5,
}
LABELS = {
    "required_skills": "Required skills", "relevant_experience": "Relevant projects and experience", "education": "Education and eligibility",
    "responsibilities": "Responsibilities", "preferred_skills": "Preferred skills", "location_preferences": "Location and work preferences",
    "seniority_type": "Seniority and employment type",
}
DISCLAIMER = "This score compares your confirmed profile with the posting. It does not predict whether you will be hired."
_STOP = set("the and for with that this from your you our are will have has not but all can who what their they them its into over "
            "about more also such than then when work working team teams role roles join help ability strong good great new".split())


@dataclass
class CandidateView:
    skills: set[str] = field(default_factory=set)            # lower-cased names the user lists as skills (confirmed)
    evidence_text: str = ""                                    # confirmed experience + project text
    responsibilities_text: str = ""                            # confirmed responsibilities/achievements/project summaries
    titles: list[str] = field(default_factory=list)
    degrees: list[str] = field(default_factory=list)
    years_experience: float = 0.0
    has_experience_or_projects: bool = False
    target_roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_preference: str = "any"
    employment_types: list[str] = field(default_factory=list)


@dataclass
class JobView:
    title: str = ""
    required_text: str = ""
    required_lines: list[str] = field(default_factory=list)
    preferred_lines: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    description: str = ""
    work_arrangement: str = "unknown"
    location: str = ""
    employment_type: str = ""
    seniority: str = ""


@dataclass
class Component:
    key: str
    label: str
    score: float | None
    weight: float = 0.0
    explanation: str = ""
    matched: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    score: float
    components: list[Component]
    unknowns: list[str]
    disclaimer: str = DISCLAIMER


def _tokens(text: str, minlen: int = 3) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9+#.]*", text.lower()) if len(t) >= minlen and t not in _STOP}


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)]
    return t


def _stems(text: str) -> set[str]:
    return {_stem(t) for t in _tokens(text)}


def months_between(start: str, end: str, current: bool, now: datetime | None = None) -> int:
    def parse(s: str) -> tuple[int, int] | None:
        m = re.match(r"^(\d{4})(?:-(\d{2}))?", s or "")
        return (int(m.group(1)), int(m.group(2) or 1)) if m else None

    a = parse(start)
    b = parse(end) if end else None
    if a is None:
        return 0
    if b is None:
        if not current:
            return 0
        n = now or datetime.now(UTC)
        b = (n.year, n.month)
    return max(0, (b[0] - a[0]) * 12 + (b[1] - a[1]))


def _degree_level(text: str) -> float:
    t = text.lower()
    if re.search(r"ph\.?\s?d|doctor", t):
        return 3
    if re.search(r"\bmaster|m\.?\s?sc|\bm\.?\s?tech|\bmba\b|\bm\.?\s?eng|\bm\.?s\.?\b", t):
        return 2
    if re.search(r"bachelor|b\.?\s?sc|b\.?\s?tech|b\.?\s?eng|\bb\.?\s?e\.?\b|\bb\.?\s?s\.?\b|\bb\.?\s?a\.?\b", t):
        return 1
    if re.search(r"associate|diploma", t):
        return 0.5
    return 0.0


def _skill_component(key: str, req: list[str], cand: CandidateView, evidence: set[str], note: str = "") -> Component:
    c = Component(key, LABELS[key], None)
    c.matched, c.gaps = [], []
    if not req:
        c.explanation = "The posting does not list recognisable skills here, so this is not scored."
        return c
    pts = 0.0
    for s in req:
        sl = s.lower()
        if sl in cand.skills:
            pts += 1.0
            c.matched.append(s)
        elif sl in evidence:
            pts += 0.7
            c.matched.append(f"{s} (evidenced in your experience/projects, not listed as a skill)")
        else:
            c.gaps.append(s)
    c.score = round(100 * pts / len(req), 1)
    c.explanation = f"{len(c.matched)} of {len(req)} skills are covered by your confirmed profile." + (" " + note if note else "")
    return c


def compute_match(job: JobView, cand: CandidateView, weights: dict[str, float] | None = None) -> MatchResult:
    w = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (weights or {}).items() if k in DEFAULT_WEIGHTS}}
    evidence = {s.lower() for s in find_skills(cand.evidence_text)}
    comps: list[Component] = []

    # 1. required skills
    req = find_skills("\n".join(job.required_lines))
    note = ""
    if not req and not job.required_lines:
        req = find_skills(job.description)
        note = "(The posting has no separate requirements section, so every skill it mentions is treated as required.)"
    comps.append(_skill_component("required_skills", req, cand, evidence, note))

    # 2. relevant projects / experience
    c = Component("relevant_experience", LABELS["relevant_experience"], None)
    title_tokens = {_stem(t) for t in _tokens(job.title) if t not in {"senior", "junior", "lead", "staff", "principal", "intern"}}
    keywords = {s.lower() for s in find_skills(" ".join([job.title, *job.required_lines, *job.preferred_lines, *job.responsibilities]))}
    if not keywords and not title_tokens:
        c.explanation = "Not enough information in the posting to compare."
    elif not cand.has_experience_or_projects:
        c.score, c.explanation = 0.0, "You have no confirmed experience or projects yet."
        c.gaps = sorted(keywords)
    else:
        hay = _stems(cand.evidence_text + " " + " ".join(cand.titles + cand.target_roles))
        hits = [k for k in keywords if k in evidence]
        t_hits = [t for t in title_tokens if t in hay]
        denom = len(keywords) + len(title_tokens)
        c.score = round(100 * (len(hits) + len(t_hits)) / denom, 1) if denom else None
        c.matched = [*(k for k in hits), *(f"role term '{t}'" for t in t_hits)]
        c.gaps = [k for k in keywords if k not in evidence]
        c.explanation = f"{len(hits)} of {len(keywords)} technologies and {len(t_hits)} of {len(title_tokens)} role terms appear in your confirmed experience or projects."
    comps.append(c)

    # 3. education / eligibility
    c = Component("education", LABELS["education"], None)
    need_text = f"{job.required_text}\n{job.description}"
    need = _degree_level(" ".join(job.required_lines)) or _degree_level(job.description[:3000])
    if need:
        have = max((_degree_level(d) for d in cand.degrees), default=0.0)
        equiv = bool(re.search(r"or equivalent|equivalent (practical )?experience", need_text, re.I))
        if have >= need:
            c.score, c.explanation, c.matched = 100.0, "Your confirmed education meets the stated degree requirement.", ["degree requirement"]
        elif equiv:
            c.score, c.explanation = 70.0, "The posting accepts equivalent experience in place of the degree."
        elif have > 0:
            c.score, c.explanation, c.gaps = 50.0, "Your highest confirmed degree is below the stated level.", ["degree level"]
        else:
            c.score, c.explanation, c.gaps = 0.0, "The posting states a degree requirement and you have no confirmed education.", ["degree"]
    else:
        c.explanation = "The posting states no degree requirement, so this is not scored."
    comps.append(c)

    # 4. responsibilities
    c = Component("responsibilities", LABELS["responsibilities"], None)
    if job.responsibilities:
        mine = _stems(cand.responsibilities_text)
        ratios: list[float] = []
        matched: list[str] = []
        gaps: list[str] = []
        for line in job.responsibilities:
            toks = _stems(line)
            if not toks:
                continue
            r = len(toks & mine) / len(toks)
            ratios.append(min(1.0, r * 1.25))
            (matched if r >= 0.4 else gaps).append(line[:100])
        if ratios:
            c.score = round(100 * sum(ratios) / len(ratios), 1)
            c.matched, c.gaps = matched, gaps
            c.explanation = f"{len(matched)} of {len(ratios)} responsibilities resemble work in your confirmed experience or projects."
    if c.score is None:
        c.explanation = "The posting lists no responsibilities, so this is not scored."
    comps.append(c)

    # 5. preferred skills
    comps.append(_skill_component("preferred_skills", find_skills("\n".join(job.preferred_lines)), cand, evidence))

    # 6. location / work preferences
    c = Component("location_preferences", LABELS["location_preferences"], None)
    arr, loc = job.work_arrangement, job.location.lower()
    if arr == "unknown" and not loc or (not cand.locations and cand.remote_preference == "any"):
        c.explanation = "Not enough location or preference information to compare."
    elif arr == "remote" and cand.remote_preference in {"remote", "any"}:
        c.score, c.explanation, c.matched = 100.0, "Remote role; matches your preference.", ["remote"]
    elif cand.remote_preference == "remote" and arr in {"onsite", "hybrid"}:
        c.score, c.explanation, c.gaps = 0.0, "You prefer remote work but this role is not remote.", [arr]
    elif any(pref.lower() in loc or loc and loc.split(",")[0].strip() in pref.lower() for pref in cand.locations):
        c.score, c.explanation, c.matched = 100.0, "The location matches one of your preferred locations.", [job.location]
    elif cand.locations:
        c.score, c.explanation, c.gaps = 30.0, "The location is not in your preferred locations.", [job.location or "unknown location"]
    comps.append(c)

    # 7. seniority / employment type / years
    c = Component("seniority_type", LABELS["seniority_type"], None)
    parts, notes = [], []
    ym = re.search(r"(\d{1,2})\s*\+?\s*(?:or more )?years?", job.required_text + " " + " ".join(job.required_lines), re.I)
    if ym:
        need_y = int(ym.group(1))
        parts.append(min(100.0, 100.0 * cand.years_experience / need_y) if need_y else 100.0)
        notes.append(f"{need_y}+ years asked, about {cand.years_experience:.1f} confirmed")
    elif job.seniority in {"senior", "lead", "staff"}:
        need_y = 5
        parts.append(min(100.0, 100.0 * cand.years_experience / need_y))
        notes.append(f"senior role, about {cand.years_experience:.1f} confirmed years")
    if job.employment_type and cand.employment_types:
        ok = any(e.lower() in job.employment_type.lower() or job.employment_type.lower() in e.lower() for e in cand.employment_types)
        parts.append(100.0 if ok else 0.0)
        notes.append("employment type " + ("matches" if ok else "differs from your preferences"))
    if parts:
        c.score = round(sum(parts) / len(parts), 1)
        c.explanation = "; ".join(notes).capitalize() + "."
    else:
        c.explanation = "No years, seniority or employment-type information to compare."
    comps.append(c)

    known = [x for x in comps if x.score is not None and w.get(x.key, 0) > 0]
    total_w = sum(w[x.key] for x in known)
    unknowns = [x.label for x in comps if x.score is None]
    for x in comps:
        x.weight = round(w[x.key] / total_w, 4) if x in known and total_w else 0.0
    score = round(sum((x.score or 0.0) * x.weight for x in known), 1) if total_w else 0.0
    return MatchResult(score=score, components=comps, unknowns=unknowns)
