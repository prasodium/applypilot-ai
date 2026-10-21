"""Heuristic résumé -> structured preview. Deterministic, no AI, no network.

The result is a PREVIEW: every value is "extracted, unconfirmed". Nothing here writes to the profile; the user corrects the
preview and applies it explicitly (see services.documents.apply_parse).
"""
from __future__ import annotations

import re

from pydantic import ValidationError

from app.core.skills import find_skills
from app.core.untrusted import sanitize_external_text
from app.schemas import EducationIn, ExperienceIn, ParsedResume, ProfileFields, ProjectIn, SkillIn

SECTIONS = {
    "summary": {"summary", "professional summary", "profile", "objective", "career objective", "about me", "about"},
    "experience": {"experience", "work experience", "professional experience", "employment", "employment history",
                   "work history", "internships", "internship experience", "relevant experience"},
    "education": {"education", "academic background", "academics", "qualifications", "education and training"},
    "skills": {"skills", "technical skills", "core skills", "key skills", "technologies", "skills and tools",
               "skills & tools", "tools & technologies", "core competencies"},
    "projects": {"projects", "personal projects", "academic projects", "selected projects", "key projects", "side projects"},
    "other": {"certifications", "certificates", "awards", "achievements", "languages", "interests", "publications",
              "references", "volunteer", "volunteering", "activities", "hobbies"},
}
_ALIAS = {a: sec for sec, names in SECTIONS.items() for a in names}

_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:(?:{_MON}\s+)?(?:19|20)\d{{2}}|\d{{1,2}}/(?:19|20)\d{{2}})"
_RANGE = re.compile(rf"({_DATE})\s*(?:-|–|—|to|until)\s*({_DATE}|present|current|now|ongoing|today)", re.I)
_SINGLE_DATE = re.compile(_DATE, re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")
_URL = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:/[^\s,;|)]*)?", re.I)
_BULLET = re.compile(r"^\s*(?:[•\-*·▪●◦‣]|\d+[.)])\s+")
_TITLE_WORDS = re.compile(r"\b(engineer|developer|intern|analyst|manager|designer|scientist|consultant|lead|architect|administrator|"
                          r"assistant|associate|specialist|officer|director|technician|researcher|programmer|trainee|"
                          r"coordinator|executive|tester|qa)\b", re.I)
_INSTITUTION = re.compile(r"\b(university|college|institute|school|academy|polytechnic)\b", re.I)
_DEGREE = re.compile(
    r"\b(B\.?\s?Sc\.?|B\.?\s?Tech\.?|B\.?\s?Eng\.?|B\.?\s?E\.?|B\.?\s?S\.?|B\.?\s?A\.?|Bachelor(?:'s)?(?:\s+of\s+[A-Za-z &]+)?|"
    r"M\.?\s?Sc\.?|M\.?\s?Tech\.?|M\.?\s?Eng\.?|M\.?\s?S\.?|M\.?\s?A\.?|MBA|Master(?:'s)?(?:\s+of\s+[A-Za-z &]+)?|"
    r"Ph\.?\s?D\.?|Doctorate|Associate(?:'s)?(?:\s+degree)?|Diploma(?:\s+in\s+[A-Za-z &]+)?)\b", re.I)
_GPA = re.compile(r"\b(?:C?GPA)\s*[:\-]?\s*(\d(?:\.\d{1,2})?)(?:\s*/\s*(\d+(?:\.\d+)?))?", re.I)
_TECH_LINE = re.compile(r"^\s*(?:technologies|tech(?:nology)? stack|tech|stack|built with|tools|environment)\s*[:\-]\s*(.+)$", re.I)

def _month_year(token: str) -> str:
    t = token.strip().lower().rstrip(".")
    m = re.match(rf"({_MON})\s+((?:19|20)\d{{2}})$", t, re.I)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1)[:3].lower()]:02d}"
    m = re.match(r"(\d{1,2})/((?:19|20)\d{2})$", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.search(r"((?:19|20)\d{2})", t)
    return m.group(1) if m else ""


def _is_present(token: str) -> bool:
    return token.strip().lower() in {"present", "current", "now", "ongoing", "today"}


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    cur: str | None = None
    for raw in lines:
        line = raw.strip()
        key = re.sub(r"[:\s]+$", "", line.lower())
        key = re.sub(r"^[\W_]+|[\W_]+$", "", key)
        words = key.split()
        if line and len(words) <= 4 and (key in _ALIAS) and not _BULLET.match(line):
            cur = _ALIAS[key]
            sections.setdefault(cur, [])
            continue
        (head if cur is None else sections[cur]).append(line)
    return head, sections


def _parse_header(head: list[str], warnings: list[str]) -> ProfileFields:
    text = "\n".join(head)
    data: dict[str, str] = {}
    if m := _EMAIL.search(text):
        data["email"] = m.group(0)
    else:
        warnings.append("No email address found in the résumé header.")
    stripped = _EMAIL.sub(" ", text)
    if m := _PHONE.search(stripped):
        data["phone"] = re.sub(r"\s+", " ", m.group(1)).strip()
    for m in _URL.finditer(stripped):
        u = m.group(0).rstrip(".,")
        if "@" in u or not re.search(r"[a-z]", u, re.I):
            continue
        full = u if u.lower().startswith("http") else "https://" + u
        low = u.lower()
        if "linkedin." in low:
            data.setdefault("linkedin_url", full)
        elif "github." in low:
            data.setdefault("github_url", full)
        elif re.search(r"\.(com|io|dev|me|net|org|app|co)\b", low) and "portfolio_url" not in data:
            data["portfolio_url"] = full
    cleaned = [_URL.sub(" ", _PHONE.sub(" ", _EMAIL.sub(" ", ln))).strip(" |,-•·") for ln in head]
    for ln in cleaned:
        words = ln.split()
        if 2 <= len(words) <= 5 and all(re.match(r"^[A-Za-z][A-Za-z.'-]*$", w) for w in words) and "legal_name" not in data \
                and not _TITLE_WORDS.search(ln):
            data["legal_name"] = ln
            break
    if "legal_name" not in data:
        warnings.append("Could not identify your name; please enter it.")
    for ln in cleaned:
        if ln != data.get("legal_name") and (m := re.match(r"^([A-Z][A-Za-z .'-]+),\s*([A-Z][A-Za-z .'-]+)$", ln.strip())):
            data["city"], data["country"] = m.group(1).strip(), m.group(2).strip()
            break
    for ln in cleaned:
        if ln and ln != data.get("legal_name") and _TITLE_WORDS.search(ln) and len(ln) < 100 and "," not in ln:
            data["headline"] = ln
            break
    try:
        return ProfileFields.model_validate(data)
    except ValidationError:
        warnings.append("Some contact details looked invalid and were skipped.")
        return ProfileFields.model_validate({k: v for k, v in data.items() if k in {"legal_name"}})


def _is_bullet(line: str) -> bool:
    return bool(_BULLET.match(line))


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _segment(lines: list[str]) -> list[dict]:
    """Group lines into entries: header lines (title/employer/dates) followed by bullet lines."""
    entries: list[dict] = []
    cur: dict | None = None
    for line in lines:
        if not line.strip():
            continue
        if _is_bullet(line):
            if cur is None:
                cur = {"header": [], "bullets": []}
                entries.append(cur)
            cur["bullets"].append(_strip_bullet(line))
        elif cur and cur["bullets"] and line[:1].islower():  # wrapped continuation of the previous bullet
            cur["bullets"][-1] += " " + line.strip()
        else:
            if cur is None or cur["bullets"] or (len(cur["header"]) >= 3):
                cur = {"header": [], "bullets": []}
                entries.append(cur)
            cur["header"].append(line.strip())
    return entries


def _extract_dates(text: str) -> tuple[str, str, bool, str]:
    m = _RANGE.search(text)
    if m:
        end = m.group(2)
        cleaned = (text[: m.start()] + " " + text[m.end():]).strip(" |,-–—()")
        return _month_year(m.group(1)), ("" if _is_present(end) else _month_year(end)), _is_present(end), cleaned
    return "", "", False, text


def _parse_experience(lines: list[str], warnings: list[str]) -> list[ExperienceIn]:
    out: list[ExperienceIn] = []
    for e in _segment(lines):
        header = " | ".join(e["header"])
        start, end, current, rest = _extract_dates(header)
        parts = [p.strip() for p in re.split(r"\s*(?:\||–|—|•|\bat\b|@)\s*|,\s+(?=[A-Z])", rest) if p.strip()]
        if not parts:
            continue
        title = next((p for p in parts if _TITLE_WORDS.search(p)), parts[0])
        others = [p for p in parts if p != title]
        employer = others[0] if others else ""
        location = others[1] if len(others) > 1 else ""
        if not employer:
            warnings.append(f"Experience entry '{title[:40]}' has no employer; please fill it in.")
        tech: list[str] = []
        resp: list[str] = []
        for b in e["bullets"]:
            if m := _TECH_LINE.match(b):
                tech += [t.strip() for t in re.split(r"[,;/|]", m.group(1)) if t.strip()]
            else:
                resp.append(b)
        have = {x.lower() for x in tech}
        tech += [t for t in find_skills(" ".join(resp)) if t.lower() not in have]
        try:
            out.append(ExperienceIn(employer=employer or "(unknown employer)", title=title, start_date=start, end_date=end,
                                    is_current=current, location=location, responsibilities=resp, technologies=tech[:30]))
        except ValidationError as exc:
            warnings.append(f"Skipped an experience entry that failed validation ({exc.errors()[0]['msg']}).")
    return out


def _parse_education(lines: list[str], warnings: list[str]) -> list[EducationIn]:
    entries: list[dict] = []
    cur: dict | None = None

    def new() -> dict:
        nonlocal cur
        cur = {"lines": [], "bullets": []}
        entries.append(cur)
        return cur

    for line in lines:
        if not line.strip():
            continue
        if _is_bullet(line):
            (cur or new())["bullets"].append(_strip_bullet(line))
            continue
        has_inst, has_deg = bool(_INSTITUTION.search(line)), bool(_DEGREE.search(line))
        text_so_far = " ".join(cur["lines"]) if cur else ""
        if cur is None or (has_inst and _INSTITUTION.search(text_so_far)) or (has_deg and _DEGREE.search(text_so_far)) or cur["bullets"]:
            new()
        assert cur is not None
        cur["lines"].append(line.strip())
    out: list[EducationIn] = []
    for e in entries:
        text = " | ".join(e["lines"])
        start, end, _cur, rest = _extract_dates(text)
        expected = bool(re.search(r"expected|anticipated|pursuing", text, re.I))
        if not end and not start and (m := _SINGLE_DATE.search(rest)):
            end = _month_year(m.group(0))
        gpa_m = _GPA.search(text)
        rest = _GPA.sub("", rest)
        inst = next((p.strip() for p in re.split(r"\s*[|,–—]\s*", rest) if _INSTITUTION.search(p)), "")
        deg_m = _DEGREE.search(rest)
        degree = deg_m.group(0).strip() if deg_m else ""
        major = ""
        if deg_m and (mm := re.search(r"\b(?:in|of)\s+([A-Za-z &/]+?)(?:\s*[|,–—(]|$)", rest[deg_m.end() - 3:])):
            major = mm.group(1).strip()
        elif deg_m and (mm := re.search(r"[,|–—]\s*([A-Za-z &/]+?)\s*(?:[|,–—(]|$)", rest[deg_m.end():])) and not _INSTITUTION.search(mm.group(1)):
            major = mm.group(1).strip()
        course = [t.strip() for b in e["bullets"] if (m := re.match(r"(?:relevant )?course(?:work|s)\s*[:\-]\s*(.+)", b, re.I))
                  for t in re.split(r"[,;]", m.group(1)) if t.strip()]
        ach = [b for b in e["bullets"] if not re.match(r"(?:relevant )?course(?:work|s)\s*[:\-]", b, re.I)]
        if not inst and not degree:
            continue
        try:
            out.append(EducationIn(institution=inst or "(unknown institution)", degree=degree, major=major, start_date=start,
                                   end_date=end, is_expected=expected, gpa=gpa_m.group(1) if gpa_m else "",
                                   gpa_scale=(gpa_m.group(2) or "") if gpa_m else "", coursework=course, achievements=ach))
        except ValidationError as exc:
            warnings.append(f"Skipped an education entry that failed validation ({exc.errors()[0]['msg']}).")
    return out


def _parse_skills(lines: list[str]) -> list[SkillIn]:
    seen: dict[str, SkillIn] = {}
    for raw in lines:
        line = _strip_bullet(raw)
        category = ""
        if m := re.match(r"^([A-Za-z &/]{2,30}):\s*(.+)$", line):
            category, line = m.group(1).strip(), m.group(2)
        for item in re.split(r"[,;•|·]|\s{2,}", line):
            item = item.strip(" .-")
            if 1 <= len(item) <= 40 and len(item.split()) <= 4 and item.lower() not in seen:
                seen[item.lower()] = SkillIn(name=item, category=category)
    return list(seen.values())[:80]


def _parse_projects(lines: list[str], warnings: list[str]) -> list[ProjectIn]:
    out: list[ProjectIn] = []
    for e in _segment(lines):
        header = " ".join(e["header"])
        url_m = _URL.search(header)
        url = ""
        if url_m and re.search(r"github|gitlab|\.io|\.dev|\.app|\.com", url_m.group(0), re.I) and "/" in url_m.group(0):
            url = url_m.group(0) if url_m.group(0).lower().startswith("http") else "https://" + url_m.group(0)
            header = header.replace(url_m.group(0), "")
        _, _, _, name = _extract_dates(header)
        name = re.sub(r"\s*[|–—]\s*$", "", name).strip(" |,-–—")
        if not name:
            continue
        tech, summary = [], []
        for b in e["bullets"]:
            if m := _TECH_LINE.match(b):
                tech += [t.strip() for t in re.split(r"[,;/|]", m.group(1)) if t.strip()]
            else:
                summary.append(b)
        try:
            out.append(ProjectIn(name=name[:200], summary=" ".join(summary)[:5000], technologies=tech[:30], url=url))
        except ValidationError:
            warnings.append(f"Skipped project '{name[:40]}' (invalid data).")
    return out


def parse_resume_text(text: str) -> ParsedResume:
    text = sanitize_external_text(text, max_len=200_000)
    warnings: list[str] = []
    if len(text.strip()) < 40:
        return ParsedResume(warnings=["The document contains almost no readable text (it may be a scanned image)."])
    head, sections = _split_sections(text.split("\n"))
    profile = _parse_header(head, warnings)
    if summary := " ".join(s for s in sections.get("summary", []) if s).strip():
        profile.summary = summary[:5000]
    experience = _parse_experience(sections.get("experience", []), warnings)
    education = _parse_education(sections.get("education", []), warnings)
    skills = _parse_skills(sections.get("skills", []))
    projects = _parse_projects(sections.get("projects", []), warnings)
    for name, found in (("experience", experience), ("education", education), ("skills", skills)):
        if not found:
            warnings.append(f"No {name} section was recognised; add it manually if it applies.")
    warnings.append("Everything above was extracted automatically and is UNCONFIRMED. Check each field before saving.")
    return ParsedResume(profile=profile, education=education, experience=experience, skills=skills, projects=projects, warnings=warnings)
