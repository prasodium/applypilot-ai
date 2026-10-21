"""SQLAlchemy models. Personal facts live in exactly one place (profile + record tables); everything else references them."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AppState,
    Confidence,
    DocumentKind,
    FactSource,
    ReviewStatus,
    SubmissionMode,
    WorkflowStatus,
)
from app.db import Base, UTCDateTime, utcnow


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Provenance:
    """Every confirmable fact carries its source; extracted data stays unconfirmed until the user confirms it."""

    source: Mapped[str] = mapped_column(String(40), default=FactSource.USER_ENTERED.value)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------- candidate


class CandidateProfile(Timestamped, Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    preferred_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(120), default="")
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")
    github_url: Mapped[str] = mapped_column(String(500), default="")
    portfolio_url: Mapped[str] = mapped_column(String(500), default="")
    website_url: Mapped[str] = mapped_column(String(500), default="")
    preferred_contact: Mapped[str] = mapped_column(String(40), default="email")
    # Optional and sensitive: only stored when the user supplies them voluntarily.
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_authorization: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requires_sponsorship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    headline: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    education: Mapped[list[EducationRecord]] = relationship(cascade="all, delete-orphan", order_by="EducationRecord.id")
    experience: Mapped[list[WorkExperience]] = relationship(cascade="all, delete-orphan", order_by="WorkExperience.id")
    skills: Mapped[list[Skill]] = relationship(cascade="all, delete-orphan", order_by="Skill.id")
    projects: Mapped[list[CandidateProject]] = relationship(cascade="all, delete-orphan", order_by="CandidateProject.id")


class EducationRecord(Timestamped, Provenance, Base):
    __tablename__ = "education_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    institution: Mapped[str] = mapped_column(String(300))
    degree: Mapped[str] = mapped_column(String(200), default="")
    major: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY | YYYY-MM | YYYY-MM-DD
    end_date: Mapped[str] = mapped_column(String(10), default="")
    is_expected: Mapped[bool] = mapped_column(Boolean, default=False)
    gpa: Mapped[str] = mapped_column(String(20), default="")
    gpa_scale: Mapped[str] = mapped_column(String(20), default="")
    coursework: Mapped[list[str]] = mapped_column(JSON, default=list)
    achievements: Mapped[list[str]] = mapped_column(JSON, default=list)


class WorkExperience(Timestamped, Provenance, Base):
    __tablename__ = "work_experiences"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    employer: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(200))
    employment_type: Mapped[str] = mapped_column(String(60), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    achievements: Mapped[list[str]] = mapped_column(JSON, default=list)
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[list[str]] = mapped_column(JSON, default=list)  # only user-verified metrics


class Skill(Timestamped, Provenance, Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("profile_id", "name_key", name="uq_skill_per_profile"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    name_key: Mapped[str] = mapped_column(String(120))  # lower-cased for uniqueness
    category: Mapped[str] = mapped_column(String(80), default="")
    proficiency: Mapped[str] = mapped_column(String(40), default="")  # only if the user provides it
    evidence: Mapped[str] = mapped_column(Text, default="")


class CandidateProject(Timestamped, Provenance, Base):
    __tablename__ = "candidate_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    problem: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    contribution: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[list[str]] = mapped_column(JSON, default=list)  # only verified results
    url: Mapped[str] = mapped_column(String(500), default="")
    related_skills: Mapped[list[str]] = mapped_column(JSON, default=list)


class ApprovedAnswer(Timestamped, Base):
    """User-approved reusable answers (the answer library)."""

    __tablename__ = "approved_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_type: Mapped[str] = mapped_column(String(60), index=True)
    question_hint: Mapped[str] = mapped_column(String(500), default="")
    answer_text: Mapped[str] = mapped_column(Text)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)


class UserPreferences(Timestamped, Base):
    __tablename__ = "user_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_preference: Mapped[str] = mapped_column(String(20), default="any")  # remote | hybrid | onsite | any
    employment_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="")
    sponsorship_preference: Mapped[str] = mapped_column(String(300), default="")
    relocation_preference: Mapped[str] = mapped_column(String(300), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")
    match_threshold: Mapped[int] = mapped_column(Integer, default=60)
    max_applications_per_day: Mapped[int] = mapped_column(Integer, default=5)
    allowed_sources: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["manual", "mock"])
    submission_mode: Mapped[str] = mapped_column(String(40), default=SubmissionMode.REVIEW_BEFORE_SUBMISSION.value)
    match_weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    evidence_capture: Mapped[str] = mapped_column(String(20), default="minimal")  # minimal | none


# ---------------------------------------------------------------- documents


class CandidateDocument(Timestamped, Base):
    __tablename__ = "candidate_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), default=DocumentKind.RESUME_UPLOAD.value, index=True)
    filename: Mapped[str] = mapped_column(String(300), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    storage_path: Mapped[str] = mapped_column(String(500), default="")  # relative to UPLOAD_DIR; never user-supplied
    text_content: Mapped[str] = mapped_column(Text, default="")
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|parsed|failed|applied
    parse_error: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_documents.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job_listings.id", ondelete="SET NULL"), nullable=True)
    application_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{text, source_fact_ids}]
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # generated by the mock AI provider


# ---------------------------------------------------------------- jobs


class JobListing(Timestamped, Base):
    __tablename__ = "job_listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    work_arrangement: Mapped[str] = mapped_column(String(20), default="unknown")  # remote|hybrid|onsite|unknown
    employment_type: Mapped[str] = mapped_column(String(60), default="")
    seniority: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    required_qualifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_qualifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="")
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_name: Mapped[str] = mapped_column(String(60))
    source_url: Mapped[str] = mapped_column(String(1000))
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    application_url: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(10), default="unknown")  # open | closed | unknown
    external_id: Mapped[str] = mapped_column(String(200), default="")
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    user_status: Mapped[str] = mapped_column(String(20), default="new")  # new | shortlisted | rejected
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)  # e.g. "possible_prompt_injection"
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    match: Mapped[JobMatch | None] = relationship(cascade="all, delete-orphan", uselist=False)


class JobMatch(Base):
    __tablename__ = "job_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"), unique=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    profile_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobSourceIntegration(Timestamped, Base):
    __tablename__ = "job_source_integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # never secrets
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    notes: Mapped[str] = mapped_column(String(500), default="")


class PlatformAccount(Timestamped, Base):
    """Metadata only. Passwords/tokens/cookies are never stored; the user signs in manually."""

    __tablename__ = "platform_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="user_managed")
    notes: Mapped[str] = mapped_column(String(500), default="")


# ---------------------------------------------------------------- applications


class Application(Timestamped, Base):
    __tablename__ = "applications"
    __table_args__ = (Index("ix_app_job", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(40), default=AppState.APPLICATION_PREPARING.value, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # bumped by any change to answers/documents
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filled_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # version whose form fill was verified in the browser
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    resume_document_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_documents.id", ondelete="SET NULL"), nullable=True)
    cover_letter_document_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_documents.id", ondelete="SET NULL"), nullable=True)
    target_kind: Mapped[str] = mapped_column(String(10), default="manual")  # mock | manual (no real automation exists)
    application_url: Mapped[str] = mapped_column(String(1000), default="")
    confirmation_reference: Mapped[str] = mapped_column(String(200), default="")
    outcome: Mapped[str] = mapped_column(String(30), default="")  # confirmed | unconfirmed | failed | user_attested
    outcome_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # minimal, redacted
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    submission_attempts: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str] = mapped_column(String(500), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    job: Mapped[JobListing] = relationship()
    questions: Mapped[list[ApplicationQuestion]] = relationship(
        cascade="all, delete-orphan", order_by="ApplicationQuestion.position"
    )
    runs: Mapped[list[WorkflowRun]] = relationship(cascade="all, delete-orphan", order_by="WorkflowRun.id")


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"
    __table_args__ = (UniqueConstraint("application_id", "field_key", name="uq_question_field"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    field_key: Mapped[str] = mapped_column(String(200))  # stable form control identifier (name/id)
    label: Mapped[str] = mapped_column(String(1000))
    field_type: Mapped[str] = mapped_column(String(20), default="text")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_type: Mapped[str] = mapped_column(String(40), default="other")
    sensitive_or_legal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_legal: Mapped[bool] = mapped_column(Boolean, default=False)

    answer: Mapped[ApplicationAnswer | None] = relationship(cascade="all, delete-orphan", uselist=False)


class ApplicationAnswer(Timestamped, Base):
    __tablename__ = "application_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("application_questions.id", ondelete="CASCADE"), unique=True)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    source_fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(10), default=Confidence.LOW.value)
    needs_user_input: Mapped[bool] = mapped_column(Boolean, default=True)
    sensitive_or_legal: Mapped[bool] = mapped_column(Boolean, default=False)
    word_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default=ReviewStatus.PENDING_REVIEW.value)
    origin: Mapped[str] = mapped_column(String(20), default="generated")  # generated | library | user
    notes: Mapped[str] = mapped_column(String(500), default="")  # why it needs input / trimmed etc.


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="fill")  # fill | submit
    status: Mapped[str] = mapped_column(String(20), default=WorkflowStatus.QUEUED.value)
    state: Mapped[str] = mapped_column(String(40), default=AppState.APPLICATION_PREPARING.value)
    last_completed_action: Mapped[str] = mapped_column(String(200), default="")
    last_verified_outcome: Mapped[str] = mapped_column(String(300), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str] = mapped_column(String(60), default="")
    next_action: Mapped[str] = mapped_column(String(300), default="")
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    events: Mapped[list[WorkflowEvent]] = relationship(cascade="all, delete-orphan", order_by="WorkflowEvent.id")


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    from_state: Mapped[str] = mapped_column(String(40), default="")
    to_state: Mapped[str] = mapped_column(String(40), default="")
    action: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")  # safe text only; never field values
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # always redacted


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(1000), default="")
    application_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class BotConfig(Timestamped, Base):
    """Settings of the scheduled background bot (single row). Off by default; changed only by the user."""

    __tablename__ = "bot_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    max_new_per_run: Mapped[int] = mapped_column(Integer, default=5)
    sources: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["mock"])
    queries: Mapped[list[str]] = mapped_column(JSON, default=list)  # empty -> use target roles from preferences
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BotRun(Base):
    __tablename__ = "bot_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(10), default="manual")  # manual | schedule
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | completed | failed
    mode: Mapped[str] = mapped_column(String(40), default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    prepared: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, default=0)
    submitted: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # skip counts, safe error messages, application ids


ALL_MODELS = [
    CandidateProfile, EducationRecord, WorkExperience, Skill, CandidateProject, ApprovedAnswer, UserPreferences,
    CandidateDocument, JobListing, JobMatch, JobSourceIntegration, PlatformAccount, Application, ApplicationQuestion,
    ApplicationAnswer, WorkflowRun, WorkflowEvent, AuditLog, Notification, BotConfig, BotRun,
]
_ = (AppState, Confidence, DocumentKind, ReviewStatus, SubmissionMode, WorkflowStatus)  # re-exported for convenience
