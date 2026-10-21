"""AI question-answering engine (master prompt section 8).

Procedure per question: classify -> detect sensitive/legal -> gather CONFIRMED facts + approved answers -> deterministic answer for
factual fields, provider draft for free text -> validate grounding, numbers and length -> mark anything uncertain for the user.
It NEVER fills an unknown answer, never answers sensitive questions from inference, and never pre-fills a legal certification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import LLMProvider, ProviderError
from app.ai.schemas import FreeTextAnswerOut
from app.core.classify import classify, extract_limits, is_legal, is_sensitive
from app.core.enums import Confidence, ReviewStatus
from app.core.enums import QuestionType as Q
from app.core.grounding import invalid_fact_ids, unsupported_numbers
from app.core.skills import find_skills
from app.core.untrusted import scan_for_injection
from app.models import ApprovedAnswer, JobListing
from app.schemas import AnswerDraft, Fact
from app.services import jobs as jobs_svc
from app.services import profile as profile_svc
from app.services.documents import _fact_fields
from app.services.matching import months_between


@dataclass
class QuestionSpec:
    label: str
    field_type: str = "text"
    options: list[str] = field(default_factory=list)
    max_length: int | None = None
    required: bool = False


@dataclass
class AnswerContext:
    facts: list[Fact]
    profile: dict[str, Any]
    prefs: dict[str, Any]
    library: list[dict[str, Any]]
    experiences: list[dict[str, Any]]  # confirmed: id, title, employer, start, end, current, text
    education: list[dict[str, Any]]
    skills: dict[str, str]  # lower name -> fact id (confirmed, user-listed)
    evidence_skills: set[str]
    job: dict[str, Any]
    cover_letter_text: str = ""
    fields_for: Any = None  # callable(fact_id) -> structured fields


def fit_to_limit(text: str, word_limit: int | None, char_limit: int | None) -> tuple[str, bool]:
    """Shorten at sentence boundaries to fit; returns (text, was_shortened). Never exceeds a limit."""
    def ok(t: str) -> bool:
        return not ((word_limit and len(t.split()) > word_limit) or (char_limit and len(t) > char_limit))

    if ok(text):
        return text, False
    out: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not ok(" ".join([*out, s])):
            break
        out.append(s)
    if out:
        return " ".join(out), True
    words = text.split()
    while words and not ok(" ".join(words)):
        words.pop()
    return " ".join(words), True


def _pick_option(value: str, options: list[str]) -> str | None:
    v = value.strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    for o in options:
        if v and (v in o.lower() or o.lower() in v) and len(o) > 1:
            return o
    return None


class AnswerEngine:
    def __init__(self, ctx: AnswerContext, ai: LLMProvider):
        self.ctx, self.ai = ctx, ai

    # ------------------------------------------------------------------ public
    def draft(self, spec: QuestionSpec) -> AnswerDraft:
        qtype = classify(spec.label, spec.field_type)
        wl, cl = extract_limits(spec.label, spec.max_length)
        base = dict(question_text=spec.label[:1000], question_type=qtype, word_limit=wl, character_limit=cl,
                    sensitive_or_legal=is_sensitive(qtype) or is_legal(qtype))

        def needs(note: str) -> AnswerDraft:
            return AnswerDraft(**base, answer_text="", needs_user_input=True, confidence=Confidence.LOW,
                               review_status=ReviewStatus.NEEDS_USER_INPUT, notes=note)

        if scan_for_injection(spec.label + " " + " ".join(spec.options)):
            return needs("This form text contains instruction-like content, so it was not answered automatically. Please answer it yourself.")
        if is_legal(qtype):
            return needs("This is a legal certification or consent. You must read it and decide yourself; MacGuard never accepts it for you.")
        if is_sensitive(qtype):
            return self._sensitive(spec, qtype, base, needs)
        lib = next((a for a in self.ctx.library if a["question_type"] == qtype.value and not a["sensitive"]), None)
        det = self._deterministic(spec, qtype)
        if det is not None:
            value, ids, conf, note = det
            if value is None:
                if lib:
                    return self._finish(spec, base, lib["answer_text"], [], Confidence.MEDIUM, "Your saved answer", origin="library")
                return needs(note)
            return self._finish(spec, base, value, ids, conf, note)
        if qtype in {Q.RESUME_UPLOAD}:
            return self._finish(spec, base, "[your résumé document will be attached]", [], Confidence.HIGH, "Attached from the application's résumé")
        if lib:
            return self._finish(spec, base, lib["answer_text"], [], Confidence.MEDIUM, "Your saved answer", origin="library")
        return self._free_text(spec, qtype, base, needs)

    # ------------------------------------------------------------------ sensitive
    def _sensitive(self, spec: QuestionSpec, qtype: Q, base: dict, needs) -> AnswerDraft:
        """Only explicit, user-supplied information may be used; otherwise the user is asked. Nothing is inferred."""
        lib = next((a for a in self.ctx.library if a["question_type"] == qtype.value and a["sensitive"]), None)
        if lib:
            d = self._finish(spec, base, lib["answer_text"], [], Confidence.HIGH, "From your saved, approved answer", origin="library")
            d.review_status = ReviewStatus.PENDING_REVIEW  # still needs the user's explicit approval for THIS application
            return d
        p = self.ctx.profile
        if qtype == Q.SPONSORSHIP and p.get("requires_sponsorship") is not None and spec.options:
            opt = _pick_option("yes" if p["requires_sponsorship"] else "no", spec.options)
            if opt:
                d = self._finish(spec, base, opt, ["personal:requires_sponsorship"], Confidence.HIGH, "From the sponsorship answer in your profile")
                d.review_status = ReviewStatus.PENDING_REVIEW
                return d
        if qtype == Q.WORK_AUTHORIZATION and p.get("work_authorization") and spec.field_type in {"text", "textarea"}:
            d = self._finish(spec, base, p["work_authorization"], ["personal:work_authorization"], Confidence.HIGH, "From your profile")
            d.review_status = ReviewStatus.PENDING_REVIEW
            return d
        return needs("This is a sensitive question (work authorization, sponsorship, demographics, health or criminal history). "
                     "Nothing is assumed: please answer it yourself or save an approved answer.")

    # ------------------------------------------------------------------ deterministic (profile/preferences) answers
    def _latest_edu(self) -> dict[str, Any] | None:
        return sorted(self.ctx.education, key=lambda e: e["end"] or "9999")[-1] if self.ctx.education else None

    def _years(self, skill: str | None) -> tuple[float, list[str]]:
        total, ids = 0, []
        for e in self.ctx.experiences:
            if skill and skill.lower() not in {s.lower() for s in find_skills(e["text"])}:
                continue
            total += months_between(e["start"], e["end"], e["current"])
            ids.append(e["id"])
        return round(total / 12, 1), ids

    def _deterministic(self, spec: QuestionSpec, qtype: Q):
        """Returns None if not a factual field, else (value|None, source_ids, confidence, note)."""
        p, pr, label = self.ctx.profile, self.ctx.prefs, spec.label.lower()
        H, M = Confidence.HIGH, Confidence.MEDIUM

        def field_value(v: str, fid: str, note: str = ""):
            return (v, [fid], H, note) if v else (None, [], Confidence.LOW, f"Your profile has no {note or 'value'} for this field.")

        if qtype == Q.FULL_NAME:
            return field_value(p.get("legal_name", ""), "personal:legal_name", "legal name")
        if qtype == Q.FIRST_NAME:
            n = (p.get("legal_name") or "").split()
            return (n[0], ["personal:legal_name"], H, "First word of your legal name") if n else (None, [], Confidence.LOW, "Your profile has no legal name.")
        if qtype == Q.LAST_NAME:
            n = (p.get("legal_name") or "").split()
            return (n[-1], ["personal:legal_name"], H, "Last word of your legal name") if len(n) > 1 else (None, [], Confidence.LOW, "Could not derive a last name; enter it yourself.")
        if qtype == Q.EMAIL:
            return field_value(p.get("email", ""), "personal:email", "email")
        if qtype == Q.PHONE:
            return field_value(p.get("phone", ""), "personal:phone", "phone number")
        if qtype == Q.LINKEDIN:
            return field_value(p.get("linkedin_url", ""), "personal:linkedin_url", "LinkedIn URL")
        if qtype == Q.GITHUB:
            return field_value(p.get("github_url", ""), "personal:github_url", "GitHub URL")
        if qtype == Q.PORTFOLIO:
            v = p.get("portfolio_url") or p.get("website_url") or ""
            return field_value(v, "personal:portfolio_url" if p.get("portfolio_url") else "personal:website_url", "portfolio or website")
        if qtype == Q.LOCATION:
            if "country" in label:
                return field_value(p.get("country", ""), "personal:country", "country")
            if "city" in label and "country" not in label:
                return field_value(p.get("city", ""), "personal:city", "city")
            if "address" in label and "email" not in label:
                return (None, [], Confidence.LOW, "Street addresses are not stored by default; enter it yourself.")
            v = ", ".join(x for x in (p.get("city"), p.get("country")) if x)
            return (v, ["personal:city", "personal:country"], H, "") if v else (None, [], Confidence.LOW, "Your profile has no location.")
        if qtype == Q.EDUCATION:
            e = self._latest_edu()
            if not e:
                return (None, [], Confidence.LOW, "You have no confirmed education records.")
            if re.search(r"gpa|cgpa", label):
                v = e["gpa"] and (e["gpa"] + (f"/{e['gpa_scale']}" if e["gpa_scale"] else ""))
            elif re.search(r"university|school|college|institution", label):
                v = e["institution"]
            elif re.search(r"major|field", label):
                v = e["major"]
            elif "graduat" in label:
                v = e["end"]
            elif "degree" in label:
                v = e["degree"]
            else:
                v = " ".join(x for x in (e["degree"], f"in {e['major']}" if e["major"] else "", f"at {e['institution']}") if x)
            return (v, [e["id"]], H, "") if v else (None, [], Confidence.LOW, "That detail is missing from your confirmed education.")
        if qtype == Q.EXPERIENCE_YEARS:
            skills = find_skills(spec.label)
            years, ids = self._years(skills[0] if skills else None)
            if not ids or years <= 0:
                what = f"with {skills[0]}" if skills else "overall"
                return (None, [], Confidence.LOW, f"No confirmed experience {what}; enter the number yourself.")
            v = str(int(years)) if spec.field_type == "number" or "how many" in label else f"{years:g}"
            return (v, ids, M, "Derived from the dates of your confirmed experience")
        if qtype == Q.SKILLS:
            named = find_skills(spec.label)
            if named and spec.field_type in {"select", "radio", "checkbox"} or (named and re.match(r"^(do|have|are)\b", label)):
                sk = named[0]
                if sk.lower() in self.ctx.skills:
                    opt = _pick_option("yes", spec.options) if spec.options else "Yes"
                    return (opt, [self.ctx.skills[sk.lower()]], H, f"{sk} is a confirmed skill") if opt else (None, [], Confidence.LOW, "No matching option.")
                if sk.lower() in self.ctx.evidence_skills:
                    opt = _pick_option("yes", spec.options) if spec.options else "Yes"
                    return (opt, [], M, f"{sk} appears in your confirmed experience or projects") if opt else (None, [], Confidence.LOW, "No matching option.")
                return (None, [], Confidence.LOW, f"{sk} is not in your confirmed skills; answer this yourself (a 'No' is a claim too).")
            names = list(self.ctx.skills)[:15]
            return (", ".join(n for n in names), [self.ctx.skills[n] for n in names], M, "Your confirmed skills") if names else (None, [], Confidence.LOW, "You have no confirmed skills.")
        if qtype == Q.SALARY:
            lo, hi, cur = pr.get("salary_min"), pr.get("salary_max"), pr.get("salary_currency") or ""
            if lo is None and hi is None:
                return (None, [], Confidence.LOW, "You have not set a salary expectation in your preferences.")
            if spec.field_type == "number":
                if lo is not None and hi is not None and lo != hi:
                    return (None, [], Confidence.LOW, "Your preference is a range; this field needs one number, so please choose it yourself.")
                return (str(lo if lo is not None else hi), [], M, "From your salary preference")
            txt = f"{lo}-{hi} {cur}".strip() if lo is not None and hi is not None and lo != hi else f"{lo if lo is not None else hi} {cur}".strip()
            return (txt, [], M, "From your salary preference")
        if qtype == Q.START_DATE:
            v = pr.get("start_date") or ""
            return (v, [], M, "From your preferences") if v else (None, [], Confidence.LOW, "You have not set a start date in your preferences.")
        if qtype == Q.RELOCATION:
            v = pr.get("relocation_preference") or ""
            if not v:
                return (None, [], Confidence.LOW, "You have not set a relocation preference.")
            if spec.options:
                opt = _pick_option(v, spec.options)
                return (opt, [], M, "From your preferences") if opt else (None, [], Confidence.LOW, "Your preference text does not match any option.")
            return (v, [], M, "From your preferences")
        if qtype == Q.REFERRAL:
            return (None, [], Confidence.LOW, "Only you know how you heard about this job.")
        if qtype == Q.COVER_LETTER and spec.field_type != "file":
            t = self.ctx.cover_letter_text
            return (t, [], M, "Your cover letter draft") if t else (None, [], Confidence.LOW, "No cover letter draft is attached to this application yet.")
        if qtype == Q.COVER_LETTER:
            return ("[your cover letter document will be attached]", [], H, "Attached from the application's cover letter")
        return None

    # ------------------------------------------------------------------ free text via provider
    def _free_text(self, spec: QuestionSpec, qtype: Q, base: dict, needs) -> AnswerDraft:
        wl, cl = base["word_limit"], base["character_limit"]
        job = self.ctx.job
        payload = {
            "question_type": qtype.value, "word_limit": wl, "char_limit": cl,
            "job": {"title": job.get("title", ""), "company": job.get("company", "")}, "required_skills": job.get("required_skills", []),
            "facts": [{"id": f.id, "kind": f.kind, "label": f.label, "text": f.text, "fields": (self.ctx.fields_for(f.id) if self.ctx.fields_for else {})}
                      for f in self.ctx.facts if f.kind in {"project", "experience", "skill", "education"}],
            "untrusted": {"question": spec.label},
        }
        try:
            out = self.ai.generate("free_text_answer", payload, FreeTextAnswerOut)
        except ProviderError:
            return needs("The AI provider could not draft this answer. Please write it yourself.")
        if out.missing_information or not out.answer.strip():
            return needs(out.missing_reason or "There are not enough confirmed facts to answer this. Please write it yourself.")
        allowed = {f.id for f in self.ctx.facts}
        if not out.source_fact_ids or invalid_fact_ids(out.source_fact_ids, allowed):
            return needs("The draft was not grounded in your confirmed facts, so it was discarded. Please write it yourself.")
        texts = [f.text for f in self.ctx.facts if f.id in out.source_fact_ids]
        bad = unsupported_numbers(out.answer, texts, [job.get("title", ""), job.get("company", ""), spec.label])
        if bad:
            return needs(f"The draft contained numbers that are not in your confirmed facts ({', '.join(sorted(bad))}); it was discarded.")
        d = self._finish(spec, base, out.answer, out.source_fact_ids, Confidence.MEDIUM if out.confidence != "low" else Confidence.LOW,
                         "Drafted from your confirmed projects and experience. Review it before approving.")
        d.review_status = ReviewStatus.PENDING_REVIEW
        return d

    # ------------------------------------------------------------------ shared finishing step
    def _finish(self, spec: QuestionSpec, base: dict, value: str, ids: list[str], conf: Confidence, note: str, origin: str = "generated") -> AnswerDraft:
        if spec.options and spec.field_type in {"select", "radio"}:
            opt = _pick_option(value, spec.options)
            if opt is None:
                return AnswerDraft(**base, answer_text="", needs_user_input=True, confidence=Confidence.LOW, review_status=ReviewStatus.NEEDS_USER_INPUT,
                                   notes=f"None of the available options match '{value[:40]}'. Please choose one yourself.")
            value = opt
        text, trimmed = fit_to_limit(value, base["word_limit"], base["character_limit"])
        if trimmed:
            note = (note + " " if note else "") + "Shortened to fit the length limit; please review."
            conf = Confidence.LOW if conf == Confidence.HIGH else conf
        return AnswerDraft(**base, answer_text=text, source_fact_ids=ids, confidence=conf, needs_user_input=False,
                           review_status=ReviewStatus.PENDING_REVIEW, origin=origin, notes=note)


# ------------------------------------------------------------------ context builder (DB -> pure data)
def build_context(db: Session, job: JobListing | None = None, cover_letter_text: str = "") -> AnswerContext:
    p = profile_svc.fresh_profile(db)
    prefs = profile_svc.get_preferences(db)
    facts = profile_svc.confirmed_facts(db)
    exps = [{"id": f"exp:{x.id}", "title": x.title, "employer": x.employer, "start": x.start_date, "end": x.end_date, "current": x.is_current,
             "text": " ".join([x.title, *x.responsibilities, *x.achievements, *x.technologies])} for x in p.experience if x.confirmed]
    edu = [{"id": f"edu:{e.id}", "institution": e.institution, "degree": e.degree, "major": e.major, "end": e.end_date, "gpa": e.gpa, "gpa_scale": e.gpa_scale}
           for e in p.education if e.confirmed]
    cv = jobs_svc.candidate_view(db)
    evidence = {s.lower() for s in find_skills(cv.evidence_text)}
    return AnswerContext(
        facts=facts,
        profile={k: getattr(p, k) for k in ("legal_name", "preferred_name", "email", "phone", "city", "country", "linkedin_url", "github_url",
                                            "portfolio_url", "website_url", "work_authorization", "requires_sponsorship")},
        prefs={k: getattr(prefs, k) for k in ("salary_min", "salary_max", "salary_currency", "start_date", "relocation_preference", "sponsorship_preference")},
        library=[{"id": a.id, "question_type": a.question_type, "answer_text": a.answer_text, "sensitive": a.sensitive}
                 for a in db.scalars(select(ApprovedAnswer).order_by(ApprovedAnswer.id)).all()],
        experiences=exps, education=edu, skills={s.name.lower(): f"skill:{s.id}" for s in p.skills if s.confirmed}, evidence_skills=evidence,
        job={"title": job.title, "company": job.company, "required_skills": find_skills("\n".join(job.required_qualifications))} if job else {},
        cover_letter_text=cover_letter_text, fields_for=lambda fid: _fact_fields(db, fid))


_ = datetime, UTC
