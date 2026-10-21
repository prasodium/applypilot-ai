"""Workflow runner: executes browser runs (fill / submit) with checkpoints, cooperative pause/cancel, and crash recovery.

Rules enforced here:
* the orchestrator (not the AI) decides every state change, through applications.transition;
* a submission is attempted at most once per request; `clicked` is persisted BEFORE the submit control is clicked, so a crash
  afterwards leaves SUBMISSION_UNCONFIRMED and is never retried automatically;
* the policy is re-checked from the database immediately before the click;
* browsers are headless by default, ephemeral, and restricted to the allowed origin.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser.capabilities import capability_for
from app.browser.filler import FillResult, Resolved, click_submit, fill_form
from app.browser.pages import FormField, Outcome
from app.browser.session import browser_session
from app.core.classify import classify, extract_limits, is_legal, is_sensitive
from app.core.enums import AppState, ReviewStatus, WorkflowStatus
from app.db import session_scope, utcnow
from app.errors import Conflict, NotFound
from app.models import Application, ApplicationAnswer, ApplicationQuestion, CandidateDocument, WorkflowEvent, WorkflowRun
from app.services import answers as answers_svc
from app.services import applications as apps
from app.services import audit
from app.services import documents as docs_svc
from app.services import profile as profile_svc

log = logging.getLogger("applypilot.workflow")
RUN_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5


class DbResolver:
    """Resolves form fields to values using ONLY stored answers (drafting new ones from confirmed facts when a field is new)."""

    def __init__(self, app: FastAPI, app_id: int):
        self.app, self.app_id = app, app_id

    async def resolve(self, fields: list[FormField], step_index: int) -> dict[str, Resolved]:
        return await asyncio.to_thread(self._resolve_sync, fields, step_index)

    def _resolve_sync(self, fields: list[FormField], step_index: int) -> dict[str, Resolved]:
        out: dict[str, Resolved] = {}
        with session_scope(self.app.state.sessionmaker) as db:
            a = apps.get_application(db, self.app_id)
            cover = db.get(CandidateDocument, a.cover_letter_document_id) if a.cover_letter_document_id else None
            engine = answers_svc.AnswerEngine(answers_svc.build_context(db, a.job, cover.text_content if cover else ""), self.app.state.ai)
            existing = {q.field_key: q for q in a.questions}
            for f in fields:
                q = existing.get(f.key)
                if q is None:
                    spec = answers_svc.QuestionSpec(f.label, f.field_type, f.options, f.max_length, f.required)
                    d = engine.draft(spec)
                    q = ApplicationQuestion(application_id=a.id, position=len(existing), step_index=step_index, field_key=f.key, label=f.label,
                                            field_type=f.field_type, required=f.required, options=f.options, max_length=f.max_length,
                                            question_type=d.question_type.value, sensitive_or_legal=d.sensitive_or_legal,
                                            is_legal=is_legal(d.question_type))
                    db.add(q)
                    db.flush()
                    q.answer = ApplicationAnswer(question_id=q.id, answer_text=d.answer_text, source_fact_ids=d.source_fact_ids,
                                                 confidence=d.confidence.value, needs_user_input=d.needs_user_input,
                                                 sensitive_or_legal=d.sensitive_or_legal, word_limit=d.word_limit,
                                                 character_limit=d.character_limit, review_status=d.review_status.value, origin=d.origin, notes=d.notes)
                    db.flush()
                    existing[f.key] = q
                    audit.record(db, "answer_drafted", "Answer drafted from confirmed facts", entity_type="application", entity_id=a.id,
                                 meta={"question_type": q.question_type, "needs_input": d.needs_user_input, "confidence": d.confidence.value})
                ans = q.answer
                if f.field_type == "file":
                    kind = "cover_letter" if q.question_type == "cover_letter" else "resume"
                    has = a.cover_letter_document_id if kind == "cover_letter" else a.resume_document_id
                    out[f.key] = Resolved(f"[FILE:{kind}]" if has else None, "" if has else "no_document")
                elif ans and ans.answer_text.strip() and not ans.needs_user_input:
                    out[f.key] = Resolved(ans.answer_text)
                else:
                    out[f.key] = Resolved(None, "needs_user_input")
        return out


class RunHooks:
    def __init__(self, app: FastAPI, run_id: int):
        self.app, self.run_id, self.count = app, run_id, 0

    async def checkpoint(self, action: str, detail: str = "", ok: bool = True) -> None:
        self.count += 1
        with session_scope(self.app.state.sessionmaker) as db:
            run = get_run(db, self.run_id)
            run.last_completed_action = action[:200]
            run.last_verified_outcome = ("verified" if ok else f"failed: {detail}")[:300]
            run.checkpoint = {**run.checkpoint, "actions": self.count}
            db.add(WorkflowEvent(run_id=run.id, from_state=run.state, to_state=run.state, action=action[:200], detail=detail[:500], ok=ok))

    async def should_stop(self) -> str:
        with session_scope(self.app.state.sessionmaker) as db:
            run = get_run(db, self.run_id)
            return "cancel" if run.cancel_requested else "pause" if run.pause_requested else ""


def _render_files(db: Session, a: Application, tmp: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for kind, did, name in (("resume", a.resume_document_id, "resume.pdf"), ("cover_letter", a.cover_letter_document_id, "cover-letter.pdf")):
        if did:
            d = db.get(CandidateDocument, did)
            if d:
                p = tmp / name
                p.write_bytes(docs_svc.render_pdf(d))
                os.chmod(p, 0o600)
                files[kind] = str(p)
    return files


def _mktemp(settings: Any) -> Path:
    base = Path(settings.upload_dir).parent / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    return Path(tempfile.mkdtemp(dir=base))


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _finish_run(run: WorkflowRun, status: WorkflowStatus, *, category: str = "", next_action: str = "", outcome: str = "") -> None:
    run.status, run.error_category, run.next_action = status.value, category, next_action
    if outcome:
        run.last_verified_outcome = outcome[:300]
    if status in (WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        run.finished_at = utcnow()


# ------------------------------------------------------------------ fill
CHALLENGE_STATE = {"human_verification": AppState.HUMAN_VERIFICATION_REQUIRED, "login_required": AppState.LOGIN_REQUIRED,
                   "email_verification": AppState.EMAIL_VERIFICATION_REQUIRED, "account_creation": AppState.ACCOUNT_CREATION_REQUIRED}


def _apply_fill_result(db: Session, run: WorkflowRun, a: Application, res: FillResult, *, from_submit: bool = False) -> None:
    run_version = run.checkpoint.get("version")
    stale = run_version != a.version
    if res.status == "ready":
        if stale:
            apps.transition(db, a, AppState.READY_FOR_REVIEW, action="form checked, but answers changed during the run", run=run)
            _finish_run(run, WorkflowStatus.SUCCEEDED, next_action="Answers changed while the browser ran. Re-check the form.", outcome="stale")
        else:
            a.filled_version = a.version
            apps.transition(db, a, AppState.READY_FOR_REVIEW, action="form filled and verified (not submitted)", run=run,
                            detail=f"{len(res.filled)} fields verified by read-back")
            _finish_run(run, WorkflowStatus.SUCCEEDED, next_action="Review and approve.", outcome=f"{len(res.filled)} fields verified")
        a.last_error = ""
    elif res.status == "needs_input":
        apps.transition(db, a, AppState.PROFILE_INFORMATION_REQUIRED, action="required answers are missing", run=run, detail="; ".join(res.missing)[:400])
        _finish_run(run, WorkflowStatus.WAITING_USER, category="needs_input", next_action="Answer the highlighted questions, then re-check the form.")
        a.last_error = ""
    elif res.status == "challenge":
        st = CHALLENGE_STATE.get(res.challenge, AppState.LOGIN_REQUIRED)
        apps.transition(db, a, st, action=f"site requires: {res.challenge}", run=run, detail="Paused for you. Nothing was bypassed.")
        _finish_run(run, WorkflowStatus.WAITING_USER, category=res.challenge, next_action=apps.NEXT_ACTION[st])
    elif res.status == "validation_failed":
        apps.transition(db, a, AppState.FORM_VALIDATION_FAILED, action="the site rejected a value", run=run, detail="; ".join(res.errors)[:400], ok=False)
        a.last_error = "; ".join(res.errors)[:500]
        _finish_run(run, WorkflowStatus.WAITING_USER, category="validation", next_action=apps.NEXT_ACTION[AppState.FORM_VALIDATION_FAILED])
    elif res.status == "paused":
        _finish_run(run, WorkflowStatus.PAUSED, next_action="Resume to continue.")
    elif res.status == "cancelled":
        apps.transition(db, a, AppState.APPLICATION_PREPARING, action="run cancelled by user", run=run)
        _finish_run(run, WorkflowStatus.CANCELLED, next_action="Start again whenever you are ready.")
    else:
        apps.transition(db, a, AppState.APPLICATION_FAILED, action="browser run failed", run=run, detail=res.reason, ok=False)
        a.last_error = res.reason[:500]
        _finish_run(run, WorkflowStatus.FAILED, category="error", next_action=apps.NEXT_ACTION[AppState.APPLICATION_FAILED])


async def run_fill(app: FastAPI, run_id: int) -> None:
    sm, settings = app.state.sessionmaker, app.state.settings
    with session_scope(sm) as db:
        run = get_run(db, run_id)
        a = apps.get_application(db, run.application_id)
        url, aid = a.application_url, a.id
        cap = capability_for(url, settings)
        if not cap.form_filling:  # defence in depth: the API already refuses, but the runner re-checks
            apps.transition(db, a, AppState.APPLICATION_FAILED, action="site not enabled for automation", run=run, ok=False)
            _finish_run(run, WorkflowStatus.FAILED, category="site_not_supported")
            return
        if apps.state_of(a) != AppState.FORM_IN_PROGRESS:
            apps.transition(db, a, AppState.FORM_IN_PROGRESS, action="browser run started", run=run)
        tmp = _mktemp(settings)
        files = _render_files(db, a, tmp)
    hooks = RunHooks(app, run_id)
    try:
        async with browser_session(settings, _origin(url)) as page:
            res = await fill_form(page, url, resolver=DbResolver(app, aid), files=files, checkpoint=hooks.checkpoint, should_stop=hooks.should_stop)
    except Exception as exc:
        log.warning("fill run %s failed: %s", run_id, type(exc).__name__)
        res = FillResult("error", reason=f"browser_error:{type(exc).__name__}. Is Chromium installed? Run `playwright install chromium`.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with session_scope(sm) as db:
        _apply_fill_result(db, get_run(db, run_id), apps.get_application(db, aid), res)


# ------------------------------------------------------------------ submit
def _evidence(prefs_mode: str, outcome: Outcome, info: dict, url: str) -> dict[str, Any]:
    ev: dict[str, Any] = {"outcome": outcome.value}
    if prefs_mode == "minimal":  # no screenshots, no HTML, no field values
        ev.update({"checked_at": utcnow().isoformat(), "page": urlparse(url).path[:200], **{k: v for k, v in info.items() if k in {"reference", "challenge", "http_status"}}})
    return ev


async def run_submit(app: FastAPI, run_id: int) -> None:
    sm, settings = app.state.sessionmaker, app.state.settings
    with session_scope(sm) as db:
        run = get_run(db, run_id)
        a = apps.get_application(db, run.application_id)
        url, aid = a.application_url, a.id
        decision = apps.decide_submission(db, a, settings, during_submit_from=AppState.SUBMISSION_PENDING_APPROVAL)
        if not decision.allowed:  # revoked/changed between the request and the run: abort BEFORE touching the site
            back = AppState.SUBMISSION_PENDING_APPROVAL if a.approved_version == a.version else AppState.READY_FOR_REVIEW
            apps.transition(db, a, back, action="submission aborted by policy re-check", run=run, detail=",".join(decision.reasons), ok=False)
            _finish_run(run, WorkflowStatus.FAILED, category="policy_denied", next_action="; ".join(decision.messages))
            audit.record(db, "submission_denied", "Policy re-check failed before the run", entity_type="application", entity_id=aid, meta={"reasons": decision.reasons})
            return
        tmp = _mktemp(settings)
        files = _render_files(db, a, tmp)
        mode = profile_svc.get_preferences(db).evidence_capture
    hooks = RunHooks(app, run_id)
    clicked = False
    final_url = url
    outcome = Outcome.AMBIGUOUS
    info: dict[str, Any] = {}
    res: FillResult | None = None
    try:
        async with browser_session(settings, _origin(url)) as page:
            res = await fill_form(page, url, resolver=DbResolver(app, aid), files=files, checkpoint=hooks.checkpoint, should_stop=hooks.should_stop)
            if res.status == "ready":
                with session_scope(sm) as db:  # last authorization check, from the database, right before the click
                    run, a = get_run(db, run_id), apps.get_application(db, aid)
                    final = apps.decide_submission(db, a, settings, during_submit_from=AppState.SUBMISSION_PENDING_APPROVAL)
                    if run.cancel_requested or run.pause_requested or not final.allowed or run.checkpoint.get("version") != a.version:
                        res = FillResult("cancelled", reason="aborted before submit: " + (",".join(final.reasons) or "stopped by user"))
                    else:
                        run.checkpoint = {**run.checkpoint, "clicked": True}  # persisted BEFORE the click: a crash now means UNCONFIRMED
                        a.submission_attempts = max(a.submission_attempts, 1)
                if res.status == "ready":
                    clicked = True
                    outcome, info = await click_submit(page)
                    final_url = page.url
    except Exception as exc:
        log.warning("submit run %s failed: %s", run_id, type(exc).__name__)
        if not clicked:
            res = FillResult("error", reason=f"browser_error:{type(exc).__name__}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with session_scope(sm) as db:
        run, a = get_run(db, run_id), apps.get_application(db, aid)
        if not clicked:
            if res and res.status in ("cancelled", "paused"):
                back = AppState.SUBMISSION_PENDING_APPROVAL if a.approved_version == a.version else AppState.READY_FOR_REVIEW
                apps.transition(db, a, back, action=res.reason or "submission stopped before the submit click", run=run)
                _finish_run(run, WorkflowStatus.CANCELLED if res.status == "cancelled" else WorkflowStatus.PAUSED, next_action="Nothing was submitted.")
            else:
                _apply_fill_result(db, run, a, res or FillResult("error", reason="unknown"), from_submit=True)
            return
        run.last_completed_action = "clicked submit"
        if outcome == Outcome.CONFIRMED and info.get("reference"):
            a.confirmation_reference, a.outcome, a.submitted_at = info["reference"], "confirmed", utcnow()
            a.outcome_evidence = _evidence(mode, outcome, info, final_url)
            a.last_error = ""
            who = " (mock employer: not a real application)" if a.target_kind == "mock" else ""
            apps.transition(db, a, AppState.SUBMITTED, action="submission confirmed by the site", run=run, detail=f"reference {info['reference']}{who}")
            _finish_run(run, WorkflowStatus.SUCCEEDED, outcome=f"confirmed, reference {info['reference']}")
            audit.record(db, "submission_confirmed", "Submission confirmed by an explicit confirmation page", entity_type="application", entity_id=aid,
                         meta={"reference": info["reference"], "mock": a.target_kind == "mock"})
        elif outcome == Outcome.VALIDATION_ERRORS:
            a.last_error = "; ".join(info.get("errors", []))[:500]
            apps.transition(db, a, AppState.FORM_VALIDATION_FAILED, action="the site rejected the submission", run=run, detail=a.last_error, ok=False)
            _finish_run(run, WorkflowStatus.WAITING_USER, category="validation", next_action=apps.NEXT_ACTION[AppState.FORM_VALIDATION_FAILED])
        elif outcome == Outcome.CHALLENGE:
            apps.transition(db, a, AppState.HUMAN_VERIFICATION_REQUIRED, action="human verification appeared at submit", run=run)
            _finish_run(run, WorkflowStatus.WAITING_USER, category="human_verification", next_action=apps.NEXT_ACTION[AppState.HUMAN_VERIFICATION_REQUIRED])
        elif outcome == Outcome.SESSION_EXPIRED:
            apps.transition(db, a, AppState.LOGIN_REQUIRED, action="the site asked for sign-in at submit", run=run)
            _finish_run(run, WorkflowStatus.WAITING_USER, category="login_required", next_action=apps.NEXT_ACTION[AppState.LOGIN_REQUIRED])
        else:  # AMBIGUOUS, or an exception after the click: never claim success, never retry
            a.outcome, a.outcome_evidence = "unconfirmed", _evidence(mode, Outcome.AMBIGUOUS, info, final_url)
            apps.transition(db, a, AppState.SUBMISSION_UNCONFIRMED, action="the result could not be confirmed", run=run,
                            detail="No explicit confirmation was found. It will not be retried automatically.", ok=False)
            _finish_run(run, WorkflowStatus.SUCCEEDED, category="unconfirmed", next_action=apps.NEXT_ACTION[AppState.SUBMISSION_UNCONFIRMED], outcome="unconfirmed")
            audit.record(db, "submission_unconfirmed", "Submission result unconfirmed", entity_type="application", entity_id=aid)


# ------------------------------------------------------------------ runner + recovery
class WorkflowRunner:
    def __init__(self, app: FastAPI):
        self.app = app
        self.tasks: dict[int, asyncio.Task] = {}

    def start(self, run_id: int) -> None:
        if run_id in self.tasks and not self.tasks[run_id].done():
            return
        self.tasks[run_id] = asyncio.create_task(self._execute(run_id), name=f"workflow-{run_id}")

    async def _execute(self, run_id: int) -> None:
        sm = self.app.state.sessionmaker
        try:
            with session_scope(sm) as db:
                run = get_run(db, run_id)
                if run is None or run.status != WorkflowStatus.QUEUED.value:
                    return
                run.status, run.started_at = WorkflowStatus.RUNNING.value, run.started_at or utcnow()
                kind = run.kind
            fn = run_fill if kind == "fill" else run_submit
            await asyncio.wait_for(fn(self.app, run_id), timeout=RUN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise  # shutdown: the run stays RUNNING and is recovered on the next start
        except Exception as exc:  # last resort: never leave an application silently in-flight
            log.exception("workflow %s crashed", run_id)
            with session_scope(sm) as db:
                self._fail_safely(db, run_id, type(exc).__name__)

    @staticmethod
    def _fail_safely(db: Session, run_id: int, why: str) -> None:
        run = get_run(db, run_id)
        if run is None or run.status in (WorkflowStatus.SUCCEEDED.value, WorkflowStatus.FAILED.value, WorkflowStatus.CANCELLED.value):
            return
        a = apps.get_application(db, run.application_id)
        if apps.state_of(a) == AppState.SUBMISSION_IN_PROGRESS:
            if run.checkpoint.get("clicked"):
                a.outcome = "unconfirmed"
                apps.transition(db, a, AppState.SUBMISSION_UNCONFIRMED, action="the run crashed after the submit click", run=run, ok=False)
            else:
                apps.transition(db, a, AppState.APPLICATION_FAILED, action="the run crashed before the submit click", run=run, ok=False)
        elif apps.state_of(a) not in (AppState.SUBMITTED, AppState.APPLICATION_WITHDRAWN):
            apps.transition(db, a, AppState.APPLICATION_FAILED, action="the run crashed", run=run, ok=False)
        a.last_error = f"Run crashed ({why})"
        _finish_run(run, WorkflowStatus.FAILED, category="crash")

    async def shutdown(self) -> None:
        for t in self.tasks.values():
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def recover_interrupted(db: Session) -> int:
    """After a crash/restart: in-flight runs become INTERRUPTED. A submit whose click may have happened becomes UNCONFIRMED."""
    n = 0
    for run in db.scalars(select(WorkflowRun).where(WorkflowRun.status.in_([WorkflowStatus.RUNNING.value, WorkflowStatus.QUEUED.value]))):
        a = db.get(Application, run.application_id)
        run.status, run.error_category = WorkflowStatus.INTERRUPTED.value, "interrupted"
        run.next_action = "The app stopped while this was running."
        n += 1
        if a is None:
            continue
        if run.kind == "submit" and apps.state_of(a) == AppState.SUBMISSION_IN_PROGRESS:
            if run.checkpoint.get("clicked"):
                a.outcome = "unconfirmed"
                apps.transition(db, a, AppState.SUBMISSION_UNCONFIRMED, action="the app stopped during submission; the result is unknown", run=run, ok=False)
                run.next_action = "Check the employer's site, then record the outcome. It will not be retried automatically."
            else:
                back = AppState.SUBMISSION_PENDING_APPROVAL if a.approved_version == a.version else AppState.READY_FOR_REVIEW
                apps.transition(db, a, back, action="the app stopped before the submit click; nothing was sent", run=run)
        audit.record(db, "run_interrupted", f"{run.kind} run interrupted by a restart", entity_type="application", entity_id=run.application_id)
    return n


# ------------------------------------------------------------------ user controls
def get_run(db: Session, run_id: int) -> WorkflowRun:
    r = db.get(WorkflowRun, run_id)
    if r is None:
        raise NotFound(f"Workflow {run_id} not found")
    return r


def request_pause(db: Session, run_id: int) -> WorkflowRun:
    r = get_run(db, run_id)
    if r.status not in (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value):
        raise Conflict(f"Only a running workflow can be paused (status: {r.status}).", code="bad_status")
    r.pause_requested = True
    audit.record(db, "pause_requested", "Pause requested", entity_type="application", entity_id=r.application_id)
    return r


def request_cancel(db: Session, run_id: int) -> WorkflowRun:
    r = get_run(db, run_id)
    if r.status in (WorkflowStatus.SUCCEEDED.value, WorkflowStatus.FAILED.value, WorkflowStatus.CANCELLED.value):
        raise Conflict(f"This workflow is already {r.status}.", code="bad_status")
    if r.status in (WorkflowStatus.PAUSED.value, WorkflowStatus.WAITING_USER.value, WorkflowStatus.INTERRUPTED.value):
        a = apps.get_application(db, r.application_id)
        if apps.state_of(a) not in (AppState.SUBMITTED, AppState.APPLICATION_WITHDRAWN):
            try:
                apps.transition(db, a, AppState.APPLICATION_PREPARING, action="workflow cancelled by user", run=r)
            except Exception:
                pass
        _finish_run(r, WorkflowStatus.CANCELLED, next_action="Start again whenever you are ready.")
    else:
        r.cancel_requested = True
    audit.record(db, "cancel_requested", "Cancel requested", entity_type="application", entity_id=r.application_id)
    return r


def prepare_resume(db: Session, run_id: int) -> WorkflowRun:
    r = get_run(db, run_id)
    if r.kind != "fill":
        raise Conflict("Submit runs are never resumed. Press Submit again if the policy allows it.", code="not_resumable")
    if r.status not in (WorkflowStatus.PAUSED.value, WorkflowStatus.INTERRUPTED.value, WorkflowStatus.WAITING_USER.value):
        raise Conflict(f"This workflow cannot be resumed (status: {r.status}).", code="bad_status")
    if r.retry_count >= MAX_RETRIES:
        raise Conflict("Too many retries. Fix the cause and prepare the form again.", code="retry_limit")
    a = apps.get_application(db, r.application_id)
    if a.state in apps.ATTEMPTED:
        raise Conflict("The application was already submitted.", code="already_submitted_or_unconfirmed")
    if apps.state_of(a) in (AppState.PROFILE_INFORMATION_REQUIRED, AppState.FORM_VALIDATION_FAILED, AppState.LOGIN_REQUIRED,
                            AppState.HUMAN_VERIFICATION_REQUIRED, AppState.EMAIL_VERIFICATION_REQUIRED, AppState.ACCOUNT_CREATION_REQUIRED):
        apps.transition(db, a, AppState.FORM_IN_PROGRESS, action="resumed by user", run=r)
    r.status, r.pause_requested, r.cancel_requested, r.retry_count = WorkflowStatus.QUEUED.value, False, False, r.retry_count + 1
    r.checkpoint = {**r.checkpoint, "version": a.version}
    return r


_ = (classify, extract_limits, is_sensitive, ReviewStatus)
