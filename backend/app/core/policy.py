"""Submission authorization policy: ONE pure function, enforced in the backend (never only in the UI).

Every submission attempt is evaluated here, and again immediately before the submit control is clicked. A denial lists every
reason so the user can see what to fix. Nothing here can be influenced by page content or model output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import AppState, SubmissionMode


@dataclass
class SubmissionContext:
    mode: SubmissionMode
    state: AppState
    version: int
    approved_version: int | None
    site_supports_submission: bool
    issues: list[str] = field(default_factory=list)  # readiness issue codes (missing/unreviewed answers, etc.)
    documents_approved: bool = False
    submitted_today: int = 0
    max_per_day: int = 5
    duplicate_application: bool = False
    already_attempted: bool = False  # SUBMITTED / UNCONFIRMED / IN_PROGRESS for this application
    form_verified_version: int | None = None


@dataclass
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)  # machine codes
    messages: list[str] = field(default_factory=list)  # human text

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reasons": self.reasons, "messages": self.messages}


_MSG = {
    "mode_does_not_allow_submission": "The current submission mode does not allow submitting. Change it in Settings if you want to submit.",
    "site_not_supported": "Automated submission is not supported for this site. Use the prepared documents and apply manually.",
    "state_not_submittable": "The application is not in a state that can be submitted.",
    "already_submitted_or_unconfirmed": "This application was already submitted or its result is unconfirmed. It will not be retried automatically.",
    "approval_missing_or_stale": "You have not approved the current version of this application (it changed after approval, or was never approved).",
    "incomplete_answers": "Some required answers are missing or sensitive/legal answers have not been reviewed.",
    "form_not_verified": "The form has not been filled and verified in the browser for this exact version.",
    "documents_not_approved": "Auto-submit requires the résumé and cover letter to be explicitly approved first.",
    "daily_limit_reached": "The daily application limit has been reached.",
    "duplicate_application": "Another application for this job was already submitted or is awaiting confirmation.",
}


def evaluate_submission(ctx: SubmissionContext) -> Decision:
    reasons: list[str] = []
    if ctx.mode in (SubmissionMode.RESEARCH_ONLY, SubmissionMode.PREPARE_ONLY):
        reasons.append("mode_does_not_allow_submission")
    if not ctx.site_supports_submission:
        reasons.append("site_not_supported")
    if ctx.already_attempted:
        reasons.append("already_submitted_or_unconfirmed")
    else:
        expected = AppState.READY_FOR_REVIEW if ctx.mode == SubmissionMode.AUTHORIZED_AUTO_SUBMIT else AppState.SUBMISSION_PENDING_APPROVAL
        if ctx.state != expected:
            reasons.append("state_not_submittable")
    if ctx.mode == SubmissionMode.REVIEW_BEFORE_SUBMISSION and ctx.approved_version != ctx.version:
        reasons.append("approval_missing_or_stale")
    if ctx.mode == SubmissionMode.AUTHORIZED_AUTO_SUBMIT and not ctx.documents_approved:
        reasons.append("documents_not_approved")
    if ctx.issues:
        reasons.append("incomplete_answers")
    if ctx.form_verified_version != ctx.version:
        reasons.append("form_not_verified")
    if ctx.submitted_today >= ctx.max_per_day:
        reasons.append("daily_limit_reached")
    if ctx.duplicate_application:
        reasons.append("duplicate_application")
    reasons = list(dict.fromkeys(reasons))
    return Decision(allowed=not reasons, reasons=reasons, messages=[_MSG[r] for r in reasons])
