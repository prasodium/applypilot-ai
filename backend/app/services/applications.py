"""Application lifecycle: prepare, edit, approve, submit (policy-gated), attest, cancel.

All state changes go through `transition`, which enforces the central state machine and writes workflow events + audit entries.
Approval is bound to an exact application VERSION: any change to answers or documents bumps the version and revokes approval.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.provider import LLMProvider
from app.browser.capabilities import SiteCapability, capability_for
from app.config import Settings
from app.core.classify import extract_limits
from app.core.enums import AppState, Confidence, QuestionType, ReviewStatus, SubmissionMode, WorkflowStatus
from app.core.policy import Decision, SubmissionContext, evaluate_submission
from app.core.states import EDITABLE, NEEDS_USER, check_transition
from app.core.text import word_count
from app.db import utcnow
from app.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.models import Application, ApplicationAnswer, ApplicationQuestion, CandidateDocument, JobListing, WorkflowEvent, WorkflowRun
from app.schemas import (
    AnswerPatch,
    ApplicationDetail,
    ApplicationOut,
    ApplicationPatch,
    AttestIn,
    QuestionOut,
    ReadinessIssue,
)
from app.services import audit
from app.services import documents as docs_svc
from app.services import profile as profile_svc

ATTEMPTED = {AppState.SUBMITTED.value, AppState.SUBMISSION_UNCONFIRMED.value, AppState.SUBMISSION_IN_PROGRESS.value}
FILLABLE = {AppState.APPLICATION_PREPARING, AppState.PROFILE_INFORMATION_REQUIRED, AppState.FORM_VALIDATION_FAILED, AppState.READY_FOR_REVIEW,
            AppState.SUBMISSION_PENDING_APPROVAL, AppState.LOGIN_REQUIRED, AppState.HUMAN_VERIFICATION_REQUIRED,
            AppState.EMAIL_VERIFICATION_REQUIRED, AppState.ACCOUNT_CREATION_REQUIRED, AppState.APPLICATION_FAILED, AppState.FORM_IN_PROGRESS}
NEXT_ACTION = {
    AppState.APPLICATION_PREPARING: "Preparing the application.",
    AppState.PROFILE_INFORMATION_REQUIRED: "Answer the highlighted questions, then re-check the form.",
    AppState.FORM_IN_PROGRESS: "The browser is filling the form. You can pause or cancel.",
    AppState.FORM_VALIDATION_FAILED: "The site rejected a value. Fix the answers, then re-check the form.",
    AppState.HUMAN_VERIFICATION_REQUIRED: "The site shows a human-verification challenge. Complete it yourself. ApplyPilot never tries to solve or bypass it.",
    AppState.LOGIN_REQUIRED: "The site needs you to sign in. Sign in yourself, then re-check the form.",
    AppState.EMAIL_VERIFICATION_REQUIRED: "The site needs an email verification you must complete yourself.",
    AppState.ACCOUNT_CREATION_REQUIRED: "The site needs an account. Create it yourself, then re-check the form.",
    AppState.READY_FOR_REVIEW: "Review every answer and document, then approve.",
    AppState.SUBMISSION_PENDING_APPROVAL: "Approved. Press Submit to send it.",
    AppState.SUBMISSION_IN_PROGRESS: "Submitting. Do not retry; the result will be verified.",
    AppState.SUBMITTED: "Done.",
    AppState.SUBMISSION_UNCONFIRMED: "The result is unclear. Check the employer's site or your email, then record what you found. It will NOT be retried automatically.",
    AppState.APPLICATION_FAILED: "Something failed. See the error, fix it and prepare again.",
    AppState.APPLICATION_WITHDRAWN: "Withdrawn.",
    AppState.JOB_CLOSED: "The job is closed.",
}


# ------------------------------------------------------------------ basics
def _doc(db: Session, doc_id: int) -> CandidateDocument:
    d = db.get(CandidateDocument, doc_id)
    if d is None:
        raise NotFound(f"Document {doc_id} not found")
    return d


def get_application(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise NotFound(f"Application {app_id} not found")
    return a


def state_of(a: Application) -> AppState:
    return AppState(a.state)


def capability(a: Application, settings: Settings) -> SiteCapability:
    return capability_for(a.application_url, settings) if a.application_url else capability_for("", settings)


def transition(db: Session, a: Application, new: AppState, *, action: str, detail: str = "", run: WorkflowRun | None = None, ok: bool = True) -> None:
    old = state_of(a)
    check_transition(old, new)  # raises InvalidTransition (a bug if it ever fires from a service)
    a.state = new.value
    if run is not None:
        run.state = new.value
    ev_run = run or next((r for r in reversed(a.runs) if r.status in (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value)), None)
    if ev_run is not None:
        db.add(WorkflowEvent(run_id=ev_run.id, from_state=old.value, to_state=new.value, action=action[:200], detail=detail[:500], ok=ok))
    audit.record(db, "state_changed", f"{old.value} -> {new.value}: {action}", entity_type="application", entity_id=a.id,
                 meta={"from": old.value, "to": new.value})
    _notify(db, a, new, detail)


def _notify(db: Session, a: Application, new: AppState, detail: str) -> None:
    title = {
        AppState.READY_FOR_REVIEW: "Application ready for review", AppState.PROFILE_INFORMATION_REQUIRED: "Your input is needed",
        AppState.HUMAN_VERIFICATION_REQUIRED: "Human verification needed", AppState.LOGIN_REQUIRED: "Sign-in needed",
        AppState.EMAIL_VERIFICATION_REQUIRED: "Email verification needed", AppState.ACCOUNT_CREATION_REQUIRED: "Account needed",
        AppState.SUBMITTED: "Application submitted", AppState.SUBMISSION_UNCONFIRMED: "Submission result unconfirmed",
        AppState.APPLICATION_FAILED: "Application failed", AppState.FORM_VALIDATION_FAILED: "The form rejected a value",
    }.get(new)
    if title:
        audit.notify(db, title, (detail or NEXT_ACTION.get(new, ""))[:500], kind="action" if new in NEEDS_USER else "info", application_id=a.id)


def new_run(db: Session, a: Application, kind: str, checkpoint: dict[str, Any] | None = None) -> WorkflowRun:
    run = WorkflowRun(application_id=a.id, kind=kind, status=WorkflowStatus.QUEUED.value, state=a.state, checkpoint=checkpoint or {})
    db.add(run)
    db.flush()
    db.refresh(a)
    return run


def active_run(a: Application) -> WorkflowRun | None:
    return next((r for r in reversed(a.runs) if r.status in (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value)), None)


def to_out(db: Session, a: Application) -> ApplicationOut:
    out = ApplicationOut.model_validate(a)
    j = a.job
    out.company, out.title, out.location, out.source_url = j.company, j.title, j.location, j.source_url
    out.match_score = j.match.score if j.match else None
    out.next_action = NEXT_ACTION.get(state_of(a), "")
    return out


# ------------------------------------------------------------------ prepare
def prepare(db: Session, ai: LLMProvider, settings: Settings, job_id: int) -> tuple[Application, WorkflowRun | None]:
    prefs = profile_svc.get_preferences(db)
    if prefs.submission_mode == SubmissionMode.RESEARCH_ONLY.value:
        raise Forbidden("Research-only mode is on: applications are not prepared. Change the mode in Settings.", code="mode_research_only")
    job = db.get(JobListing, job_id)
    if job is None:
        raise NotFound(f"Job {job_id} not found")
    if job.status == "closed":
        raise Unprocessable("This job is closed.", code="job_closed")
    if job.source_name not in prefs.allowed_sources and not job.is_demo:
        raise Forbidden(f"The '{job.source_name}' source is not enabled.", code="source_not_allowed")
    live = db.scalars(select(Application).where(Application.job_id == job_id, Application.state.notin_(
        [AppState.APPLICATION_WITHDRAWN.value, AppState.JOB_CLOSED.value, AppState.APPLICATION_FAILED.value]))).first()
    if live:
        raise Conflict("An application for this job already exists.", code="duplicate_application", details={"application_id": live.id})

    cap = capability_for(job.application_url, settings)
    a = Application(job_id=job_id, state=AppState.APPLICATION_PREPARING.value, idempotency_key=uuid.uuid4().hex,
                    target_kind="mock" if cap.is_mock and cap.form_filling else "manual", application_url=job.application_url,
                    is_demo=job.is_demo or ai.is_demo)
    db.add(a)
    db.flush()
    db.refresh(a)
    audit.record(db, "application_prepared", f"Application prepared ({a.target_kind} target)", entity_type="application", entity_id=a.id,
                 meta={"job_id": job_id, "target": a.target_kind})
    notes: list[str] = []
    try:
        a.resume_document_id = docs_svc.generate_tailored_resume(db, job_id).id
        a.cover_letter_document_id = docs_svc.generate_cover_letter(db, ai, job_id).id
    except Unprocessable as exc:
        notes.append(f"Document drafts: {exc.message}")
    for did in (a.resume_document_id, a.cover_letter_document_id):
        if did:
            _doc(db, did).application_id = a.id
    if notes:
        a.notes = " ".join(notes)
    if a.target_kind == "mock":
        run = new_run(db, a, "fill", {"version": a.version})
        return a, run
    transition(db, a, AppState.READY_FOR_REVIEW, action="manual handoff", detail="No automation is available for this site; apply manually using the prepared documents.")
    a.last_error = ""
    return a, None


# ------------------------------------------------------------------ readiness
def compute_issues(db: Session, a: Application) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    has_resume_q = False
    for q in a.questions:
        ans = q.answer
        text = (ans.answer_text if ans else "").strip()
        if q.question_type == QuestionType.RESUME_UPLOAD.value:
            has_resume_q = True
        if q.required and (ans is None or ans.needs_user_input or not text):
            issues.append(ReadinessIssue(code="answer_missing", message=f"Answer needed: {q.label[:120]}", question_id=q.id))
        elif ans and text and (q.sensitive_or_legal or ans.sensitive_or_legal) and ans.review_status not in (ReviewStatus.APPROVED.value, ReviewStatus.EDITED.value):
            issues.append(ReadinessIssue(code="sensitive_unreviewed", message=f"Review and approve this sensitive/legal answer: {q.label[:120]}", question_id=q.id))
    if has_resume_q and not a.resume_document_id:
        issues.append(ReadinessIssue(code="documents_missing", message="No résumé is attached to this application."))
    return issues


def detail(db: Session, a: Application, settings: Settings) -> ApplicationDetail:
    base = to_out(db, a).model_dump()
    issues = compute_issues(db, a)
    ready = not issues and a.filled_version == a.version and state_of(a) == AppState.READY_FOR_REVIEW and a.target_kind == "mock"
    return ApplicationDetail(**base, questions=[QuestionOut.model_validate(q) for q in a.questions], issues=issues,
                             ready_for_approval=ready, submit_decision=decide_submission(db, a, settings).as_dict())


# ------------------------------------------------------------------ editing (invalidates approval)
def _validate_answer(q: ApplicationQuestion, text: str) -> None:
    if q.options and q.field_type in {"select", "radio"} and text and text not in q.options:
        raise Unprocessable(f"'{q.label[:60]}': choose one of the available options.", code="invalid_option", details={"options": q.options})
    wl, cl = extract_limits(q.label, q.max_length)
    if cl and len(text) > cl:
        raise Unprocessable(f"'{q.label[:60]}': the answer is {len(text)} characters; the limit is {cl}.", code="over_character_limit")
    if wl and word_count(text) > wl:
        raise Unprocessable(f"'{q.label[:60]}': the answer is {word_count(text)} words; the limit is {wl}.", code="over_word_limit")


def patch(db: Session, app_id: int, body: ApplicationPatch) -> Application:
    a = get_application(db, app_id)
    editing_content = body.answers is not None or body.resume_document_id is not None or body.cover_letter_document_id is not None
    if editing_content and state_of(a) not in EDITABLE:
        raise Conflict(f"The application cannot be edited in state {a.state}.", code="not_editable")
    changed = False
    if body.notes is not None:
        a.notes = body.notes
    qmap = {q.id: q for q in a.questions}
    for qid, ch in (body.answers or {}).items():
        q = qmap.get(qid)
        if q is None:
            raise NotFound(f"Question {qid} does not belong to this application")
        _apply_answer(db, q, ch)
        changed = True
    for field_name, kind in (("resume_document_id", "tailored_resume"), ("cover_letter_document_id", "cover_letter")):
        did = getattr(body, field_name)
        if did is not None:
            d = docs_svc.get_document(db, did)
            if d.kind not in (kind, "master_resume") or (kind == "cover_letter" and d.kind != "cover_letter"):
                raise Unprocessable("That document cannot be used here.", code="wrong_document_kind")
            setattr(a, field_name, did)
            d.application_id = a.id
            changed = True
    if changed:
        bump_version(db, a, "answers or documents edited")
    return a


def _apply_answer(db: Session, q: ApplicationQuestion, ch: AnswerPatch) -> None:
    ans = q.answer
    if ans is None:
        ans = ApplicationAnswer(question_id=q.id)
        q.answer = ans
        db.add(ans)
    if ch.answer_text is not None:
        text = ch.answer_text.strip()
        _validate_answer(q, text)
        ans.answer_text = text
        ans.origin = "user"
        ans.needs_user_input = text == ""
        ans.confidence = Confidence.HIGH.value if text else Confidence.LOW.value
        ans.review_status = ReviewStatus.EDITED.value if text else ReviewStatus.NEEDS_USER_INPUT.value
        ans.source_fact_ids = []
        ans.notes = "Written by you." if text else "Needs your input."
    if ch.review_status is not None:
        if ch.review_status == ReviewStatus.APPROVED and not (ans.answer_text or "").strip():
            raise Unprocessable("An empty answer cannot be approved.", code="empty_answer")
        if ch.review_status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.PENDING_REVIEW):
            ans.review_status = ch.review_status.value
        else:
            raise Unprocessable("Use approved, rejected or pending_review.", code="bad_review_status")
    ans.sensitive_or_legal = q.sensitive_or_legal or ans.sensitive_or_legal
    audit.record(db, "answer_edited", "An answer was edited or reviewed", entity_type="application", entity_id=q.application_id,
                 meta={"question_type": q.question_type, "by": "user"})


def bump_version(db: Session, a: Application, reason: str) -> None:
    a.version += 1
    had_approval = a.approved_version is not None
    a.approved_version, a.approved_at = None, None
    if state_of(a) == AppState.SUBMISSION_PENDING_APPROVAL:
        transition(db, a, AppState.READY_FOR_REVIEW, action="approval invalidated", detail=reason)
    if had_approval:
        audit.record(db, "approval_revoked", f"Approval invalidated: {reason}", entity_type="application", entity_id=a.id, meta={"new_version": a.version})
    audit.record(db, "application_version_changed", reason, entity_type="application", entity_id=a.id, meta={"version": a.version})


# ------------------------------------------------------------------ approve / policy / submit
def approve(db: Session, app_id: int, version: int) -> Application:
    a = get_application(db, app_id)
    mode = profile_svc.get_preferences(db).submission_mode
    if mode in (SubmissionMode.RESEARCH_ONLY.value, SubmissionMode.PREPARE_ONLY.value):
        raise Forbidden("The current submission mode does not allow approving a submission.", code="mode_does_not_allow_submission")
    if a.target_kind != "mock":
        raise Unprocessable("This site cannot be submitted automatically; apply manually and record the result.", code="manual_handoff")
    if version != a.version:
        raise Conflict("The application changed since you reviewed it. Review the latest version and approve again.", code="stale_version",
                       details={"current_version": a.version})
    if state_of(a) != AppState.READY_FOR_REVIEW:
        raise Conflict(f"Only an application that is ready for review can be approved (state: {a.state}).", code="bad_state")
    issues = compute_issues(db, a)
    if issues:
        raise Unprocessable("Some answers still need your attention.", code="incomplete_answers", details={"issues": [i.model_dump() for i in issues]})
    if a.filled_version != a.version:
        raise Unprocessable("Re-check the form in the browser first: it has not been verified for this version.", code="form_not_verified")
    a.approved_version, a.approved_at = version, utcnow()
    for did in (a.resume_document_id, a.cover_letter_document_id):
        if did:
            _doc(db, did).status = "approved"
    transition(db, a, AppState.SUBMISSION_PENDING_APPROVAL, action="approved by user", detail=f"version {version}")
    audit.record(db, "approval_granted", f"Application approved (version {version})", entity_type="application", entity_id=a.id, meta={"version": version})
    return a


def attempted_today(db: Session) -> int:
    today = datetime.now(UTC).date()
    n = 0
    for r in db.scalars(select(WorkflowRun).where(WorkflowRun.kind == "submit")):
        if r.started_at.date() == today and r.checkpoint.get("clicked"):
            n += 1
    return n


def decide_submission(db: Session, a: Application, settings: Settings, *, during_submit_from: AppState | None = None) -> Decision:
    """`during_submit_from`: re-check from inside the submit run, where the stored state is already SUBMISSION_IN_PROGRESS."""
    prefs = profile_svc.get_preferences(db)
    cap = capability(a, settings)
    dup = db.scalar(select(Application.id).where(Application.job_id == a.job_id, Application.id != a.id, Application.state.in_(list(ATTEMPTED)))) is not None
    docs_ok = all(_doc(db, d).status == "approved" for d in (a.resume_document_id, a.cover_letter_document_id) if d)
    ctx = SubmissionContext(
        mode=SubmissionMode(prefs.submission_mode), state=state_of(a), version=a.version, approved_version=a.approved_version,
        site_supports_submission=cap.submission and a.target_kind == "mock", issues=[i.code for i in compute_issues(db, a)],
        documents_approved=docs_ok, submitted_today=attempted_today(db), max_per_day=prefs.max_applications_per_day,
        duplicate_application=dup, already_attempted=(a.state in ATTEMPTED) and during_submit_from is None,
        form_verified_version=a.filled_version)
    if during_submit_from is not None:  # inside the submit run the stored state is already IN_PROGRESS: evaluate as the mode expects
        ctx.state = AppState.READY_FOR_REVIEW if ctx.mode == SubmissionMode.AUTHORIZED_AUTO_SUBMIT else AppState.SUBMISSION_PENDING_APPROVAL
    return evaluate_submission(ctx)


def begin_submit(db: Session, app_id: int, settings: Settings) -> tuple[Application, WorkflowRun, bool]:
    """Returns (application, run, duplicate_request). Idempotent: a repeated request never creates a second submission."""
    a = get_application(db, app_id)
    if a.state in ATTEMPTED:
        prev = next((r for r in reversed(a.runs) if r.kind == "submit"), None)
        if prev is None:
            raise Conflict("This application was already handled.", code="already_submitted_or_unconfirmed")
        return a, prev, True
    decision = decide_submission(db, a, settings)
    if not decision.allowed:
        audit.record(db, "submission_denied", "Submission blocked by policy", entity_type="application", entity_id=a.id, meta={"reasons": decision.reasons})
        raise Forbidden("This application cannot be submitted yet.", code="submission_denied", details=decision.as_dict())
    expected = a.state
    auto = profile_svc.get_preferences(db).submission_mode == SubmissionMode.AUTHORIZED_AUTO_SUBMIT.value
    if auto and state_of(a) == AppState.READY_FOR_REVIEW:
        transition(db, a, AppState.SUBMISSION_PENDING_APPROVAL, action="auto-submit authorized by the user's setting")
        audit.record(db, "auto_submit_authorized", "Auto-submit conditions satisfied", entity_type="application", entity_id=a.id)
        db.flush()  # the compare-and-set below must see the new state
    # compare-and-set: only one concurrent request may move the application into SUBMISSION_IN_PROGRESS
    res = db.execute(update(Application).where(Application.id == a.id, Application.state == a.state)
                     .values(state=AppState.SUBMISSION_IN_PROGRESS.value, submission_attempts=Application.submission_attempts + 1))
    if getattr(res, "rowcount", 0) != 1:
        db.refresh(a)
        prev = next((r for r in reversed(a.runs) if r.kind == "submit"), None)
        if prev is None:
            raise Conflict("Another request is already submitting this application.", code="concurrent_submission")
        return a, prev, True
    db.expire(a)
    run = new_run(db, a, "submit", {"version": a.version, "clicked": False, "expected_state": expected})
    db.add(WorkflowEvent(run_id=run.id, from_state=AppState.SUBMISSION_PENDING_APPROVAL.value, to_state=AppState.SUBMISSION_IN_PROGRESS.value,
                         action="submission started", detail="policy checks passed", ok=True))
    audit.record(db, "submission_attempted", "Submission started", entity_type="application", entity_id=a.id, meta={"version": a.version})
    return a, run, False


def start_fill(db: Session, app_id: int, settings: Settings) -> WorkflowRun:
    a = get_application(db, app_id)
    prefs = profile_svc.get_preferences(db)
    if prefs.submission_mode == SubmissionMode.RESEARCH_ONLY.value:
        raise Forbidden("Research-only mode: the browser is not used.", code="mode_research_only")
    cap = capability(a, settings)
    if a.target_kind != "mock" or not cap.form_filling:
        raise Forbidden("Automated form filling is not enabled for this site. Apply manually (manual handoff).", code="site_not_supported")
    st = state_of(a)
    if st not in FILLABLE or st in (AppState.SUBMISSION_IN_PROGRESS,) or a.state in ATTEMPTED:
        raise Conflict(f"The form cannot be re-checked in state {a.state}.", code="bad_state")
    if active_run(a):
        raise Conflict("A browser run is already in progress for this application.", code="run_in_progress")
    if st == AppState.SUBMISSION_PENDING_APPROVAL:
        a.approved_version, a.approved_at = None, None
        transition(db, a, AppState.READY_FOR_REVIEW, action="approval revoked to re-check the form")
    if state_of(a) == AppState.APPLICATION_FAILED:
        transition(db, a, AppState.APPLICATION_PREPARING, action="retry after failure")
    run = new_run(db, a, "fill", {"version": a.version})
    return run


# ------------------------------------------------------------------ user-attested outcomes / cancel
def attest(db: Session, app_id: int, body: AttestIn) -> Application:
    """The USER records what they found. Stored as user_attested; never presented as machine-verified confirmation."""
    a = get_application(db, app_id)
    st = state_of(a)
    manual_ok = st == AppState.READY_FOR_REVIEW and a.target_kind == "manual"
    if st != AppState.SUBMISSION_UNCONFIRMED and not manual_ok:
        raise Conflict("You can record an outcome only for an unconfirmed submission or a manual application.", code="bad_state")
    if body.outcome == "submitted":
        a.outcome, a.submitted_at = "user_attested", utcnow()
        a.outcome_evidence = {"attested_by_user": True, "note": body.note[:200], "recorded_at": utcnow().isoformat()}
        transition(db, a, AppState.SUBMITTED, action="user recorded the application as submitted", detail="user-reported, not machine-verified")
    else:
        a.outcome, a.last_error = "failed", (body.note or "The user reports it was not submitted.")[:500]
        transition(db, a, AppState.APPLICATION_FAILED, action="user recorded that it was not submitted")
    audit.record(db, "outcome_attested", f"User recorded outcome: {body.outcome}", entity_type="application", entity_id=a.id)
    return a


def cancel(db: Session, app_id: int) -> Application:
    a = get_application(db, app_id)
    if state_of(a) in (AppState.SUBMISSION_IN_PROGRESS,):
        raise Conflict("A submission is in progress and cannot be cancelled. Wait for the result.", code="submission_in_progress")
    run = active_run(a)
    if run:
        run.cancel_requested = True
    transition(db, a, AppState.APPLICATION_WITHDRAWN, action="cancelled by user")
    a.approved_version, a.approved_at = None, None
    return a
