"""Job posting -> structured fields. The input is untrusted web content: it is sanitized, never executed, and scanned for
instruction-like text (flag only)."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from app.core.skills import find_skills
from app.core.untrusted import sanitize_external_text, scan_for_injection

_REQ = re.compile(r"^(requirements?|qualifications?|what you('|’)ll need|what we('|’)re looking for|must[- ]haves?|minimum qualifications|"
                  r"required (skills|qualifications)|you have|about you|skills required)\b", re.I)
_PREF = re.compile(r"^(nice[- ]to[- ]haves?|preferred( qualifications| skills)?|bonus( points)?|a plus|pluses|good to have|"
                   r"desirable|it would be (great|nice)|extra credit)\b", re.I)
_RESP = re.compile(r"^(responsibilities|what you('|’)ll do|your role|the role|duties|key responsibilities|day[- ]to[- ]day|"
                   r"what you will do|in this role)\b", re.I)
_HEADING_ANY = re.compile(r"^[A-Z][A-Za-z0-9 '’&/,\-]{2,60}:?$")
_SALARY = re.compile(r"(?P<cur>[$€£₹]|USD|EUR|GBP|INR)?\s?(?P<a>\d{2,3}(?:[,.]\d{3})+|\d{2,3}\s?[kK])\s*(?:-|–|—|to)\s*(?:[$€£₹]|USD|EUR|GBP|INR)?\s?(?P<b>\d{2,3}(?:[,.]\d{3})+|\d{2,3}\s?[kK])")
_CUR = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "iframe", "template", "svg", "form", "nav", "footer", "header"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for blk in soup.find_all(["p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"]):
        blk.insert_before("\n")
        blk.insert_after("\n")
    return sanitize_external_text(soup.get_text(" "))


def _num(s: str) -> int | None:
    s = s.strip().lower().replace(" ", "")
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        return int(re.sub(r"[,.]", "", s))
    except ValueError:
        return None


def _salary(text: str) -> tuple[int | None, int | None, str]:
    m = _SALARY.search(text)
    if not m:
        return None, None, ""
    a, b = _num(m.group("a")), _num(m.group("b"))
    if a is None or b is None or a > b or a < 1000 or b > 10_000_000:
        return None, None, ""
    cur = m.group("cur") or ""
    return a, b, _CUR.get(cur, cur.upper())


def _arrangement(text: str, remote_flag: bool | None = None) -> str:
    t = text.lower()
    if remote_flag is True and "hybrid" not in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|work from home|remote)\b", t):
        return "remote"
    if re.search(r"\b(on[- ]?site|in[- ]office|in the office)\b", t):
        return "onsite"
    return "unknown"


def _employment(text: str) -> str:
    t = text.lower()
    for key, label in (("full-time", "full-time"), ("full time", "full-time"), ("part-time", "part-time"), ("part time", "part-time"),
                       ("internship", "internship"), ("intern ", "internship"), ("contract", "contract"), ("freelance", "contract"),
                       ("temporary", "temporary")):
        if key in t:
            return label
    return ""


def _seniority(title: str) -> str:
    t = title.lower()
    for key, label in (("intern", "intern"), ("junior", "junior"), ("jr", "junior"), ("graduate", "junior"), ("senior", "senior"),
                       ("sr.", "senior"), ("staff", "senior"), ("principal", "senior"), ("lead", "lead"), ("manager", "manager")):
        if re.search(rf"\b{re.escape(key)}", t):
            return label
    return ""


def split_sections(text: str) -> dict[str, list[str]]:
    """Group lines under requirement / preferred / responsibility headings. Lines before any heading go to 'intro'."""
    out: dict[str, list[str]] = {"intro": [], "required": [], "preferred": [], "responsibilities": []}
    cur = "intro"
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        bare = line.rstrip(":").strip()
        if len(bare) <= 70 and not line.startswith("-"):
            if _PREF.match(bare):
                cur = "preferred"
                continue
            if _REQ.match(bare):
                cur = "required"
                continue
            if _RESP.match(bare):
                cur = "responsibilities"
                continue
            if _HEADING_ANY.match(line) and line.endswith(":") or (line.isupper() and len(line.split()) <= 5):
                cur = "intro" if cur != "intro" and not (_REQ.match(bare) or _PREF.match(bare) or _RESP.match(bare)) else cur
                continue
        out[cur].append(re.sub(r"^[-•*]\s*", "", line))
    return out


def _jsonld_job(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            types = it.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return it
    return None


def _dt(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def _loc(v: Any) -> str:
    if isinstance(v, list):
        v = v[0] if v else {}
    if isinstance(v, dict):
        a = v.get("address", v)
        if isinstance(a, dict):
            return ", ".join(str(a[k]) for k in ("addressLocality", "addressRegion", "addressCountry") if a.get(k) and isinstance(a[k], (str, int)))
        return str(a)
    return str(v or "")


def parse_job(*, html: str = "", text: str = "", url: str = "", source: str = "manual") -> dict[str, Any]:
    """Returns JobListing field values (without ids/timestamps). Raises ValueError if no title can be found."""
    ld = _jsonld_job(html) if html else None
    body_text = html_to_text(ld.get("description", "") if ld and "<" in str(ld.get("description", "")) and not text else "") if ld else ""
    if html and not text:
        text = html_to_text(html)
    if ld and ld.get("description"):
        d = str(ld["description"])
        body_text = html_to_text(d) if "<" in d else sanitize_external_text(d)
    description = body_text or text
    title = company = ""
    if ld:
        title = str(ld.get("title", "")).strip()
        org = ld.get("hiringOrganization")
        company = str(org.get("name", "") if isinstance(org, dict) else org or "").strip()
    elif html:
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = (h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")).strip()
        m = re.search(r"^(.*?)\s+(?:at|@|-|–|\|)\s+(.+)$", title)
        if m and not company:
            title, company = m.group(1).strip(), re.split(r"\s*[|–-]\s*", m.group(2))[0].strip()
        for attrs in ({"property": "og:site_name"}, {"name": "author"}):
            tag = soup.find("meta", attrs=dict(attrs))  # type: ignore[arg-type]  # bs4 stubs reject plain dict literals
            content = tag.get("content") if tag else None
            if not company and isinstance(content, str) and content.strip():
                company = content.strip()
    if not title and description:
        first = next((ln.strip() for ln in description.split("\n") if ln.strip()), "")
        title = first[:200]
    if not title:
        raise ValueError("No job title found")
    sections = split_sections(description)
    required, preferred, resp = sections["required"], sections["preferred"], sections["responsibilities"]
    all_text = f"{title}\n{description}"
    smin, smax, scur = _salary(all_text)
    base = (ld or {}).get("baseSalary")
    if isinstance(base, dict) and isinstance(base.get("value"), dict):
        v = base["value"]
        try:
            lo, hi = int(float(v.get("minValue"))), int(float(v.get("maxValue")))
            if 0 < lo <= hi:
                smin, smax, scur = lo, hi, str(base.get("currency", scur))
        except (TypeError, ValueError):
            pass
    loc = _loc((ld or {}).get("jobLocation")) if ld else ""
    remote_flag = bool(ld and str(ld.get("jobLocationType", "")).upper() == "TELECOMMUTE") or None
    emp = (ld or {}).get("employmentType")
    emp = (emp[0] if isinstance(emp, list) and emp else emp) or _employment(all_text)
    ident = (ld or {}).get("identifier")
    ext_id = str(ident.get("value", "") if isinstance(ident, dict) else ident or "")
    flags = sorted({f"possible_prompt_injection: {h}" for h in scan_for_injection(description)})
    return {
        "company": (company or "Unknown company")[:300], "title": title[:300], "location": loc[:300],
        "work_arrangement": _arrangement(f"{loc} {all_text}", remote_flag), "employment_type": str(emp).replace("_", "-").lower()[:60],
        "seniority": _seniority(title), "description": description[:60_000], "required_qualifications": required[:60],
        "preferred_qualifications": preferred[:60], "responsibilities": resp[:60], "salary_min": smin, "salary_max": smax,
        "salary_currency": scur, "posted_at": _dt((ld or {}).get("datePosted")), "deadline": _dt((ld or {}).get("validThrough")),
        "source_name": source, "source_url": url, "application_url": str((ld or {}).get("url") or url),
        "status": "open", "external_id": ext_id[:200], "flags": flags,
        "_skills_required": find_skills("\n".join(required)), "_skills_preferred": find_skills("\n".join(preferred)),
    }
