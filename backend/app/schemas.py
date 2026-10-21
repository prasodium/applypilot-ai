"""Pydantic request/response models. Validation lives here so every entry point (API, import, parser) shares it."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import (
    Confidence,
    DocumentKind,
    FactSource,
    QuestionType,
    ReviewStatus,
    SubmissionMode,
)
from app.core.text import valid_partial_date

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_PHONE = re.compile(r"^[+()\-.\s\d]{5,30}$")


def _opt_url(v: str) -> str:
    v = (v or "").strip()
    if v and not re.match(r"^https?://[^\s]+$", v, re.I):
        raise ValueError("must be an http(s) URL")
    return v


def _partial_date(v: str) -> str:
    v = (v or "").strip()
    if not valid_partial_date(v):
        raise ValueError("use YYYY, YYYY-MM or YYYY-MM-DD")
    return v


Str = Annotated[str, Field(max_length=500)]
LongStr = Annotated[str, Field(max_length=5000)]
StrList = Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=100)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ profile


class ProfileFields(BaseModel):
    legal_name: Str = ""
    preferred_name: Str = ""
    email: Str = ""
    phone: Str = ""
    city: Str = ""
    country: Str = ""
    linkedin_url: Str = ""
    github_url: Str = ""
    portfolio_url: Str = ""
    website_url: Str = ""
    preferred_contact: Literal["email", "phone", "either"] = "email"
    address: Str | None = None
    date_of_birth: date | None = None
    work_authorization: Str | None = None
    requires_sponsorship: bool | None = None
    headline: Str = ""
    summary: LongStr = ""

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        v = v.strip()
        if v and not _EMAIL.match(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_ok(cls, v: str) -> str:
        v = v.strip()
        if v and not _PHONE.match(v):
            raise ValueError("not a valid phone number")
        return v

    @field_validator("linkedin_url", "github_url", "portfolio_url", "website_url")
    @classmethod
    def _urls(cls, v: str) -> str:
        return _opt_url(v)


class ProfilePatch(BaseModel):
    """PATCH body: only the provided fields are changed."""

    model_config = ConfigDict(extra="forbid")
    legal_name: Str | None = None
    preferred_name: Str | None = None
    email: Str | None = None
    phone: Str | None = None
    city: Str | None = None
    country: Str | None = None
    linkedin_url: Str | None = None
    github_url: Str | None = None
    portfolio_url: Str | None = None
    website_url: Str | None = None
    preferred_contact: Literal["email", "phone", "either"] | None = None
    address: Str | None = None
    date_of_birth: date | None = None
    work_authorization: Str | None = None
    requires_sponsorship: bool | None = None
    headline: Str | None = None
    summary: LongStr | None = None

    @model_validator(mode="after")
    def _validate_via_full_model(self) -> ProfilePatch:
        ProfileFields.model_validate({k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None})
        return self


class _Prov(BaseModel):
    source: FactSource = FactSource.USER_ENTERED
    confirmed: bool = True


class EducationIn(BaseModel):
    institution: Annotated[str, Field(min_length=1, max_length=300)]
    degree: Str = ""
    major: Str = ""
    start_date: str = ""
    end_date: str = ""
    is_expected: bool = False
    gpa: Annotated[str, Field(max_length=20)] = ""
    gpa_scale: Annotated[str, Field(max_length=20)] = ""
    coursework: StrList = []
    achievements: StrList = []

    _d = field_validator("start_date", "end_date")(lambda cls, v: _partial_date(v))

    @model_validator(mode="after")
    def _order(self) -> EducationIn:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class EducationOut(EducationIn, ORM, _Prov):
    id: int


class ExperienceIn(BaseModel):
    employer: Annotated[str, Field(min_length=1, max_length=300)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    employment_type: Annotated[str, Field(max_length=60)] = ""
    location: Str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    responsibilities: StrList = []
    achievements: StrList = []
    technologies: StrList = []
    metrics: StrList = []

    _d = field_validator("start_date", "end_date")(lambda cls, v: _partial_date(v))

    @model_validator(mode="after")
    def _order(self) -> ExperienceIn:
        if self.is_current and self.end_date:
            raise ValueError("a current position cannot have an end_date")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class ExperienceOut(ExperienceIn, ORM, _Prov):
    id: int


class SkillIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    category: Annotated[str, Field(max_length=80)] = ""
    proficiency: Annotated[str, Field(max_length=40)] = ""
    evidence: LongStr = ""


class SkillOut(SkillIn, ORM, _Prov):
    id: int


class ProjectIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    summary: LongStr = ""
    problem: LongStr = ""
    technologies: StrList = []
    contribution: LongStr = ""
    results: StrList = []
    url: str = ""
    related_skills: StrList = []

    _u = field_validator("url")(lambda cls, v: _opt_url(v))


class ProjectOut(ProjectIn, ORM, _Prov):
    id: int


class ProfileOut(ProfileFields, ORM):
    id: int
    education: list[EducationOut] = []
    experience: list[ExperienceOut] = []
    skills: list[SkillOut] = []
    projects: list[ProjectOut] = []
    updated_at: datetime


class Fact(BaseModel):
    id: str  # e.g. "personal:email", "skill:12", "exp:3"
    kind: str
    label: str
    text: str
    source: FactSource
    confirmed: bool


# ------------------------------------------------------------------ preferences & answers


class PreferencesFields(BaseModel):
    target_roles: StrList = []
    locations: StrList = []
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] = "any"
    employment_types: StrList = []
    salary_min: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    salary_max: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    salary_currency: Annotated[str, Field(max_length=8)] = ""
    sponsorship_preference: Str = ""
    relocation_preference: Str = ""
    start_date: str = ""
    match_threshold: Annotated[int, Field(ge=0, le=100)] = 60
    max_applications_per_day: Annotated[int, Field(ge=0, le=200)] = 5
    allowed_sources: StrList = ["manual", "mock"]
    submission_mode: SubmissionMode = SubmissionMode.REVIEW_BEFORE_SUBMISSION
    match_weights: dict[str, Annotated[float, Field(ge=0, le=1000)]] = {}
    retention_days: Annotated[int, Field(ge=1, le=3650)] = 365
    evidence_capture: Literal["minimal", "none"] = "minimal"

    _d = field_validator("start_date")(lambda cls, v: _partial_date(v))

    @model_validator(mode="after")
    def _salary(self) -> PreferencesFields:
        if self.salary_min is not None and self.salary_max is not None and self.salary_max < self.salary_min:
            raise ValueError("salary_max is below salary_min")
        return self


class PreferencesOut(PreferencesFields, ORM):
    id: int


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_roles: StrList | None = None
    locations: StrList | None = None
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] | None = None
    employment_types: StrList | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    sponsorship_preference: Str | None = None
    relocation_preference: Str | None = None
    start_date: str | None = None
    match_threshold: int | None = None
    max_applications_per_day: int | None = None
    allowed_sources: StrList | None = None
    submission_mode: SubmissionMode | None = None
    match_weights: dict[str, float] | None = None
    retention_days: int | None = None
    evidence_capture: Literal["minimal", "none"] | None = None


class ApprovedAnswerIn(BaseModel):
    question_type: QuestionType
    question_hint: Str = ""
    answer_text: Annotated[str, Field(min_length=1, max_length=5000)]
    sensitive: bool = False


class ApprovedAnswerOut(ApprovedAnswerIn, ORM):
    id: int


# ------------------------------------------------------------------ documents


class DocumentOut(ORM):
    id: int
    kind: DocumentKind
    filename: str
    mime_type: str
    size_bytes: int
    parse_status: str
    parse_error: str
    version: int
    parent_id: int | None
    job_id: int | None
    application_id: int | None
    status: str
    is_demo: bool
    created_at: datetime


class DocumentDetail(DocumentOut):
    text_content: str
    parsed_data: dict[str, Any] | None
    claims: list[dict[str, Any]]


class ParsedResume(BaseModel):
    """Heuristic extraction result. Shown to the user for correction; NOT facts until applied/confirmed."""

    profile: ProfileFields = ProfileFields()
    education: list[EducationIn] = []
    experience: list[ExperienceIn] = []
    skills: list[SkillIn] = []
    projects: list[ProjectIn] = []
    warnings: list[str] = []


class ApplyParseIn(BaseModel):
    parsed: ParsedResume
    confirm: bool = False  # True: user reviewed -> records become user_confirmed. False: saved as unconfirmed.
    apply_profile_fields: bool = True
    replace_existing: bool = False


class GenerateIn(BaseModel):
    job_id: int | None = None
    notes: Annotated[str, Field(max_length=2000)] = ""


# ------------------------------------------------------------------ jobs


class JobImportIn(BaseModel):
    url: str = ""
    html: Annotated[str, Field(max_length=2_000_000)] = ""
    text: Annotated[str, Field(max_length=200_000)] = ""
    source: Literal["manual", "mock", "arbeitnow"] = "manual"
    fields: dict[str, Any] = {}  # optional user overrides (company, title, location...)

    @model_validator(mode="after")
    def _something(self) -> JobImportIn:
        if not (self.url or self.html or self.text or self.fields):
            raise ValueError("provide a url, pasted html/text, or fields")
        return self


class JobSearchIn(BaseModel):
    source: Literal["mock", "arbeitnow"] = "mock"
    query: Annotated[str, Field(max_length=200)] = ""
    location: Annotated[str, Field(max_length=200)] = ""
    remote_only: bool = False
    limit: Annotated[int, Field(ge=1, le=50)] = 20


class MatchComponent(BaseModel):
    key: str
    label: str
    score: float | None  # None = unknown (excluded from the weighted average)
    weight: float  # normalized
    explanation: str
    matched: list[str] = []
    gaps: list[str] = []


class MatchOut(BaseModel):
    score: float
    components: list[MatchComponent]
    unknowns: list[str]
    disclaimer: str
    computed_at: datetime
    stale: bool = False


class JobOut(ORM):
    id: int
    company: str
    title: str
    location: str
    work_arrangement: str
    employment_type: str
    seniority: str
    description: str
    required_qualifications: list[str]
    preferred_qualifications: list[str]
    responsibilities: list[str]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    posted_at: datetime | None
    deadline: datetime | None
    source_name: str
    source_url: str
    retrieved_at: datetime
    application_url: str
    status: str
    external_id: str
    user_status: str
    flags: list[str]
    is_demo: bool
    match_score: float | None = None


class JobImportResult(BaseModel):
    job: JobOut
    created: bool
    duplicate_of: int | None = None
    notes: list[str] = []


class JobsPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


# ------------------------------------------------------------------ applications


class AnswerOut(ORM):
    id: int
    question_id: int
    answer_text: str
    source_fact_ids: list[str]
    confidence: Confidence
    needs_user_input: bool
    sensitive_or_legal: bool
    word_limit: int | None
    character_limit: int | None
    review_status: ReviewStatus
    origin: str
    notes: str


class QuestionOut(ORM):
    id: int
    position: int
    step_index: int
    field_key: str
    label: str
    field_type: str
    required: bool
    options: list[str]
    max_length: int | None
    question_type: QuestionType
    sensitive_or_legal: bool
    is_legal: bool
    answer: AnswerOut | None


class ApplicationOut(ORM):
    id: int
    job_id: int
    state: str
    version: int
    approved_version: int | None
    approved_at: datetime | None
    target_kind: str
    application_url: str
    confirmation_reference: str
    outcome: str
    submitted_at: datetime | None
    notes: str
    last_error: str
    is_demo: bool
    resume_document_id: int | None
    cover_letter_document_id: int | None
    created_at: datetime
    updated_at: datetime
    company: str = ""
    title: str = ""
    location: str = ""
    match_score: float | None = None
    source_url: str = ""
    next_action: str = ""


class ReadinessIssue(BaseModel):
    code: str
    message: str
    question_id: int | None = None


class ApplicationDetail(ApplicationOut):
    questions: list[QuestionOut]
    issues: list[ReadinessIssue]
    ready_for_approval: bool
    submit_decision: dict[str, Any] | None = None


class PrepareIn(BaseModel):
    job_id: int


class AnswerPatch(BaseModel):
    answer_text: Annotated[str, Field(max_length=5000)] | None = None
    review_status: ReviewStatus | None = None


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: Annotated[str, Field(max_length=5000)] | None = None
    answers: dict[int, AnswerPatch] | None = None  # question_id -> change
    resume_document_id: int | None = None
    cover_letter_document_id: int | None = None


class ApproveIn(BaseModel):
    version: int  # must equal the application's current version


class AttestIn(BaseModel):
    outcome: Literal["submitted", "failed"]
    note: Annotated[str, Field(max_length=1000)] = ""


class WorkflowOut(ORM):
    id: int
    application_id: int
    kind: str
    status: str
    state: str
    last_completed_action: str
    last_verified_outcome: str
    retry_count: int
    error_category: str
    next_action: str
    checkpoint: dict[str, Any]
    pause_requested: bool
    cancel_requested: bool
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class WorkflowEventOut(ORM):
    id: int
    ts: datetime
    from_state: str
    to_state: str
    action: str
    detail: str
    ok: bool


class WorkflowDetail(WorkflowOut):
    events: list[WorkflowEventOut]


class NotificationOut(ORM):
    id: int
    ts: datetime
    kind: str
    title: str
    body: str
    application_id: int | None
    read: bool


class NotificationPatch(BaseModel):
    read: bool


class AuditOut(ORM):
    id: int
    ts: datetime
    event_type: str
    entity_type: str
    entity_id: int | None
    summary: str
    meta: dict[str, Any]


class SettingsOut(BaseModel):
    app_env: str
    ai_provider: str
    ai_model: str
    ai_api_key_set: bool  # the key itself is never returned
    ai_demo_mode: bool
    browser_headless: bool
    mock_employer_base_url: str
    max_upload_mb: int
    preferences: PreferencesOut
    job_sources: list[dict[str, Any]]
    site_capabilities: list[dict[str, Any]]


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferences: PreferencesPatch | None = None
    job_source_enabled: dict[str, bool] | None = None


class DashboardOut(BaseModel):
    jobs_discovered: int
    shortlisted: int
    draft_applications: int
    awaiting_review: int
    submitted: int
    unconfirmed: int
    needs_user_action: int
    recent_activity: list[AuditOut]
    next_actions: list[str]
    demo_mode: bool
