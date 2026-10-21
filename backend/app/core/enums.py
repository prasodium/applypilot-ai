from __future__ import annotations

from enum import StrEnum


class FactSource(StrEnum):
    USER_ENTERED = "user_entered"
    RESUME_EXTRACTED_UNCONFIRMED = "resume_extracted_unconfirmed"
    USER_CONFIRMED = "user_confirmed"
    DERIVED = "derived"


class SubmissionMode(StrEnum):
    RESEARCH_ONLY = "research_only"
    PREPARE_ONLY = "prepare_only"
    REVIEW_BEFORE_SUBMISSION = "review_before_submission"  # default
    AUTHORIZED_AUTO_SUBMIT = "authorized_auto_submit"


class AppState(StrEnum):
    JOB_DISCOVERED = "JOB_DISCOVERED"
    JOB_ANALYZED = "JOB_ANALYZED"
    JOB_SHORTLISTED = "JOB_SHORTLISTED"
    APPLICATION_PREPARING = "APPLICATION_PREPARING"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    ACCOUNT_CREATION_REQUIRED = "ACCOUNT_CREATION_REQUIRED"
    EMAIL_VERIFICATION_REQUIRED = "EMAIL_VERIFICATION_REQUIRED"
    HUMAN_VERIFICATION_REQUIRED = "HUMAN_VERIFICATION_REQUIRED"
    PROFILE_INFORMATION_REQUIRED = "PROFILE_INFORMATION_REQUIRED"
    FORM_IN_PROGRESS = "FORM_IN_PROGRESS"
    FORM_VALIDATION_FAILED = "FORM_VALIDATION_FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    SUBMISSION_PENDING_APPROVAL = "SUBMISSION_PENDING_APPROVAL"
    SUBMISSION_IN_PROGRESS = "SUBMISSION_IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_UNCONFIRMED = "SUBMISSION_UNCONFIRMED"
    APPLICATION_FAILED = "APPLICATION_FAILED"
    APPLICATION_WITHDRAWN = "APPLICATION_WITHDRAWN"
    JOB_CLOSED = "JOB_CLOSED"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    NEEDS_USER_INPUT = "needs_user_input"
    APPROVED = "approved"  # the user explicitly approved this exact answer
    EDITED = "edited"  # the user wrote/changed it
    REJECTED = "rejected"


class QuestionType(StrEnum):
    FULL_NAME = "full_name"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    EMAIL = "email"
    PHONE = "phone"
    LOCATION = "location"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    PORTFOLIO = "portfolio"
    EDUCATION = "education"
    EXPERIENCE_YEARS = "experience_years"
    SKILLS = "skills"
    SALARY = "salary_expectation"
    START_DATE = "start_date"
    RELOCATION = "relocation"
    WORK_AUTHORIZATION = "work_authorization"  # sensitive
    SPONSORSHIP = "sponsorship"  # sensitive
    DEMOGRAPHIC = "demographic"  # sensitive
    CRIMINAL_HISTORY = "criminal_history"  # sensitive
    DISABILITY = "disability"  # sensitive
    LEGAL_CERTIFICATION = "legal_certification"  # legal: always user action
    RESUME_UPLOAD = "resume_upload"
    COVER_LETTER = "cover_letter"
    MOTIVATION = "motivation"
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    REFERRAL = "referral"
    OTHER = "other"


SENSITIVE_TYPES = {
    QuestionType.WORK_AUTHORIZATION,
    QuestionType.SPONSORSHIP,
    QuestionType.DEMOGRAPHIC,
    QuestionType.CRIMINAL_HISTORY,
    QuestionType.DISABILITY,
}
LEGAL_TYPES = {QuestionType.LEGAL_CERTIFICATION}


class DocumentKind(StrEnum):
    RESUME_UPLOAD = "resume_upload"
    MASTER_RESUME = "master_resume"
    TAILORED_RESUME = "tailored_resume"
    COVER_LETTER = "cover_letter"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_USER = "waiting_user"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # process stopped mid-run; resumable (never for a submit in progress)
