"""Candidate profile, records, fact provenance, preferences, answer library, export and deletion."""
from __future__ import annotations

import hashlib
import json
import shutil
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.enums import FactSource, SubmissionMode
from app.errors import Conflict, NotFound
from app.models import (
    ALL_MODELS,
    ApprovedAnswer,
    CandidateProfile,
    CandidateProject,
    EducationRecord,
    Skill,
    UserPreferences,
    WorkExperience,
)
from app.schemas import (
    ApprovedAnswerIn,
    EducationIn,
    ExperienceIn,
    Fact,
    PreferencesPatch,
    ProfileFields,
    ProfilePatch,
    ProjectIn,
    SkillIn,
)
from app.services import audit

PERSONAL_LABELS = {
    "legal_name": "Legal name", "preferred_name": "Preferred name", "email": "Email", "phone": "Phone",
    "city": "City", "country": "Country", "linkedin_url": "LinkedIn", "github_url": "GitHub",
    "portfolio_url": "Portfolio", "website_url": "Website", "headline": "Headline", "summary": "Summary",
    "work_authorization": "Work authorization", "requires_sponsorship": "Requires sponsorship",
}
KIND_MODEL = {"edu": EducationRecord, "exp": WorkExperience, "skill": Skill, "proj": CandidateProject}


# ------------------------------------------------------------------ profile
def get_profile(db: Session) -> CandidateProfile:
    """The app is single-user and local: exactly one profile row, created on first use."""
    p = db.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if p is None:
        p = CandidateProfile()
        db.add(p)
        db.flush()
    return p


_REL = ["education", "experience", "skills", "projects"]


def fresh_profile(db: Session) -> CandidateProfile:
    """The profile with its record collections re-read from the DB (records may have been added in this same session)."""
    p = get_profile(db)
    db.flush()
    db.expire(p, _REL)
    return p


def replace_profile(db: Session, data: ProfileFields) -> CandidateProfile:
    p = get_profile(db)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    audit.record(db, "profile_updated", "Profile replaced", entity_type="profile", entity_id=p.id)
    return p


def patch_profile(db: Session, data: ProfilePatch) -> CandidateProfile:
    p = get_profile(db)
    changed = data.model_dump(exclude_unset=True)
    for k, v in changed.items():
        setattr(p, k, v)
    audit.record(db, "profile_updated", "Profile fields updated", entity_type="profile", entity_id=p.id,
                 meta={"fields": sorted(changed)})
    return p


# ------------------------------------------------------------------ records
def _apply(obj: Any, data: dict[str, Any]) -> None:
    for k, v in data.items():
        setattr(obj, k, v)


def add_education(db: Session, d: EducationIn, *, source: FactSource = FactSource.USER_ENTERED, confirmed: bool = True) -> EducationRecord:
    r = EducationRecord(profile_id=get_profile(db).id, source=source.value, confirmed=confirmed)
    _apply(r, d.model_dump())
    db.add(r)
    db.flush()
    return r


def add_experience(db: Session, d: ExperienceIn, *, source: FactSource = FactSource.USER_ENTERED, confirmed: bool = True) -> WorkExperience:
    r = WorkExperience(profile_id=get_profile(db).id, source=source.value, confirmed=confirmed)
    _apply(r, d.model_dump())
    db.add(r)
    db.flush()
    return r


def add_skill(db: Session, d: SkillIn, *, source: FactSource = FactSource.USER_ENTERED, confirmed: bool = True) -> Skill:
    pid = get_profile(db).id
    key = d.name.strip().lower()
    existing = db.scalar(select(Skill).where(Skill.profile_id == pid, Skill.name_key == key))
    if existing:
        raise Conflict(f"Skill '{d.name}' already exists", code="duplicate_skill")
    r = Skill(profile_id=pid, name_key=key, source=source.value, confirmed=confirmed)
    _apply(r, d.model_dump())
    db.add(r)
    db.flush()
    return r


def add_project(db: Session, d: ProjectIn, *, source: FactSource = FactSource.USER_ENTERED, confirmed: bool = True) -> CandidateProject:
    r = CandidateProject(profile_id=get_profile(db).id, source=source.value, confirmed=confirmed)
    _apply(r, d.model_dump())
    db.add(r)
    db.flush()
    return r


def _get(db: Session, model: type, rid: int):
    obj = db.get(model, rid)
    if obj is None:
        raise NotFound(f"{model.__name__} {rid} not found")
    return obj


def update_record(db: Session, model: type, rid: int, d: Any) -> Any:
    """User edits make a record user-entered and confirmed (the user has now personally stated it)."""
    obj = _get(db, model, rid)
    data = d.model_dump()
    if model is Skill:
        key = data["name"].strip().lower()
        clash = db.scalar(select(Skill).where(Skill.profile_id == obj.profile_id, Skill.name_key == key, Skill.id != rid))
        if clash:
            raise Conflict(f"Skill '{data['name']}' already exists", code="duplicate_skill")
        obj.name_key = key
    _apply(obj, data)
    obj.source, obj.confirmed = FactSource.USER_ENTERED.value, True
    return obj


def delete_record(db: Session, model: type, rid: int) -> None:
    db.delete(_get(db, model, rid))


# ------------------------------------------------------------------ facts
def _span(a: str, b: str, current: bool = False) -> str:
    if not a and not b:
        return ""
    return f" ({a or '?'} to {'present' if current and not b else (b or '?')})"


def all_facts(db: Session) -> list[Fact]:
    """Flatten the profile into addressable facts with provenance. Personal fields entered by the user are confirmed."""
    p = fresh_profile(db)
    facts: list[Fact] = []
    for field, label in PERSONAL_LABELS.items():
        v = getattr(p, field)
        if v in ("", None):
            continue
        facts.append(Fact(id=f"personal:{field}", kind="personal", label=label, text=str(v),
                          source=FactSource.USER_ENTERED, confirmed=True))
    for e in p.education:
        txt = f"{e.degree or 'Studies'}{' in ' + e.major if e.major else ''} at {e.institution}{_span(e.start_date, e.end_date)}"
        if e.gpa:
            txt += f", GPA {e.gpa}{'/' + e.gpa_scale if e.gpa_scale else ''}"
        facts.append(Fact(id=f"edu:{e.id}", kind="education", label=e.institution, text=txt,
                          source=FactSource(e.source), confirmed=e.confirmed))
    for x in p.experience:
        bits = [f"{x.title} at {x.employer}{_span(x.start_date, x.end_date, x.is_current)}"]
        if x.technologies:
            bits.append("technologies: " + ", ".join(x.technologies))
        if x.achievements:
            bits.append("achievements: " + "; ".join(x.achievements))
        facts.append(Fact(id=f"exp:{x.id}", kind="experience", label=f"{x.title}, {x.employer}", text=". ".join(bits),
                          source=FactSource(x.source), confirmed=x.confirmed))
    for s in p.skills:
        facts.append(Fact(id=f"skill:{s.id}", kind="skill", label=s.name,
                          text=s.name + (f" ({s.proficiency})" if s.proficiency else ""),
                          source=FactSource(s.source), confirmed=s.confirmed))
    for j in p.projects:
        bits = [f"Project {j.name}"]
        if j.summary:
            bits.append(j.summary)
        if j.technologies:
            bits.append("technologies: " + ", ".join(j.technologies))
        if j.contribution:
            bits.append("contribution: " + j.contribution)
        if j.results:
            bits.append("results: " + "; ".join(j.results))
        facts.append(Fact(id=f"proj:{j.id}", kind="project", label=j.name, text=". ".join(bits),
                          source=FactSource(j.source), confirmed=j.confirmed))
    return facts


def confirmed_facts(db: Session) -> list[Fact]:
    """The ONLY facts any generator/matcher/answer engine may use."""
    return [f for f in all_facts(db) if f.confirmed]


def confirm_fact(db: Session, fact_id: str) -> Fact:
    kind, _, ident = fact_id.partition(":")
    if kind == "personal":
        if not any(f.id == fact_id for f in all_facts(db)):
            raise NotFound(f"Fact {fact_id} not found")
    elif kind in KIND_MODEL and ident.isdigit():
        obj = _get(db, KIND_MODEL[kind], int(ident))
        obj.confirmed, obj.source = True, FactSource.USER_CONFIRMED.value
        db.flush()
        audit.record(db, "fact_confirmed", f"Fact {fact_id} confirmed", entity_type="fact")
    else:
        raise NotFound(f"Fact {fact_id} not found")
    db.expire_all()
    return next(f for f in all_facts(db) if f.id == fact_id)


def fingerprint(db: Session) -> str:
    """Changes whenever a confirmed fact or a preference that affects matching changes (used to flag stale matches)."""
    prefs = get_preferences(db)
    payload = json.dumps(
        {"facts": sorted((f.id, f.text) for f in confirmed_facts(db)),
         "prefs": [prefs.target_roles, prefs.locations, prefs.remote_preference, prefs.employment_types, prefs.match_weights]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ------------------------------------------------------------------ preferences / answer library
def get_preferences(db: Session) -> UserPreferences:
    p = db.scalar(select(UserPreferences).order_by(UserPreferences.id).limit(1))
    if p is None:
        p = UserPreferences(submission_mode=SubmissionMode.REVIEW_BEFORE_SUBMISSION.value)
        db.add(p)
        db.flush()
    return p


def patch_preferences(db: Session, d: PreferencesPatch) -> UserPreferences:
    from app.schemas import PreferencesFields

    p = get_preferences(db)
    changes = d.model_dump(exclude_unset=True)
    merged = {**{k: getattr(p, k) for k in PreferencesFields.model_fields}, **changes}
    validated = PreferencesFields.model_validate(merged)  # re-validate the combined result (e.g. salary range)
    for k in changes:
        setattr(p, k, getattr(validated, k).value if k == "submission_mode" else getattr(validated, k))
    meta: dict[str, Any] = {"fields": sorted(changes)}
    if "submission_mode" in changes:
        meta["submission_mode"] = p.submission_mode
    audit.record(db, "preferences_updated", "Preferences updated", entity_type="preferences", entity_id=p.id, meta=meta)
    return p


def add_approved_answer(db: Session, d: ApprovedAnswerIn) -> ApprovedAnswer:
    a = ApprovedAnswer(question_type=d.question_type.value, question_hint=d.question_hint, answer_text=d.answer_text,
                       sensitive=d.sensitive)
    db.add(a)
    db.flush()
    audit.record(db, "approved_answer_added", f"Approved answer for {a.question_type}", entity_type="approved_answer", entity_id=a.id)
    return a


# ------------------------------------------------------------------ export / delete
def _row(obj: Any) -> dict[str, Any]:
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def export_all(db: Session) -> dict[str, Any]:
    """Everything the app stores about the user, as JSON (right to inspect/export)."""
    data: dict[str, Any] = {"format": "applypilot-export-v1"}
    for m in ALL_MODELS:
        data[m.__tablename__] = [_row(o) for o in db.scalars(select(m)).all()]
    audit.record(db, "data_exported", "User data exported")
    return data


def delete_all(db: Session, upload_dir: Any = None) -> dict[str, int]:
    """Right to deletion: removes every row and every stored upload. Only an anonymous marker remains."""
    counts: dict[str, int] = {}
    for m in reversed(ALL_MODELS):
        counts[m.__tablename__] = db.execute(delete(m)).rowcount or 0
    shutil.rmtree(upload_dir or get_settings().upload_dir, ignore_errors=True)
    db.flush()
    audit.record(db, "data_deleted", "All user data deleted at the user's request")
    return counts
