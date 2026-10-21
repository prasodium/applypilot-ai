"""Scheduled background bot: discover -> score -> prepare -> fill -> STOP for the human.

What it does on each run (only if the user enabled it):
  1. searches the user's enabled sources with the user's target roles,
  2. scores new jobs and selects those at/above the match threshold (skipping closed, rejected, duplicate and suspicious ones),
  3. prepares applications up to the per-run and per-day limits (documents + a browser fill for the mock site),
  4. records what happened and notifies the user.
It never changes settings, never answers sensitive/legal questions, never approves anything for the user, and submits ONLY if the user's
submission mode is "authorized auto-submit" AND the normal backend policy allows it. Every action goes through the same services and
policy as a manual action. Job text is untrusted data and cannot influence any of this.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AppState, SubmissionMode, WorkflowStatus
from app.db import session_scope, utcnow
from app.errors import AppError, Conflict
from app.jobsources.registry import search_adapters
from app.models import Application, BotConfig, BotRun, JobListing, WorkflowRun
from app.schemas import BotConfigPatch, JobSearchIn
from app.services import applications as apps
from app.services import audit
from app.services import jobs as jobs_svc
from app.services import profile as profile_svc

log = logging.getLogger("applypilot.bot")
RUN_WAIT_SECONDS = 150


def get_config(db: Session) -> BotConfig:
    c = db.scalar(select(BotConfig).order_by(BotConfig.id).limit(1))
    if c is None:
        c = BotConfig()
        db.add(c)
        db.flush()
    return c


def patch_config(db: Session, body: BotConfigPatch) -> BotConfig:
    c = get_config(db)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v)
    audit.record(db, "bot_config_updated", "Bot settings changed by the user", entity_type="bot", entity_id=c.id,
                 meta={k: v for k, v in changes.items() if k in {"enabled", "interval_minutes", "max_new_per_run"}})
    return c


def next_run_at(cfg: BotConfig) -> datetime | None:
    if not cfg.enabled:
        return None
    return utcnow() if cfg.last_run_at is None else cfg.last_run_at + timedelta(minutes=cfg.interval_minutes)


def is_due(cfg: BotConfig, now: datetime | None = None) -> bool:
    """Pure schedule rule: enabled, and never run or the interval has elapsed."""
    if not cfg.enabled:
        return False
    now = now or datetime.now(UTC)
    return cfg.last_run_at is None or now >= cfg.last_run_at + timedelta(minutes=cfg.interval_minutes)


def _applications_today(db: Session) -> int:
    today = datetime.now(UTC).date()
    n = 0
    for a in db.scalars(select(Application).where(Application.state != AppState.APPLICATION_WITHDRAWN.value)):
        if a.created_at.date() == today:
            n += 1
    return n


# ------------------------------------------------------------------ steps (sync, each in its own transaction)
def _discover(app: FastAPI) -> tuple[list[int], list[str]]:
    """Searches enabled sources. Returns (new job ids, safe error messages). One failing source never aborts the run."""
    new_ids: list[int] = []
    errors: list[str] = []
    with session_scope(app.state.sessionmaker) as db:
        cfg, prefs = get_config(db), profile_svc.get_preferences(db)
        queries = (cfg.queries or prefs.target_roles or [""])[:5]
        sources = [s for s in cfg.sources if s in prefs.allowed_sources and s in search_adapters()]
        skipped = [s for s in cfg.sources if s not in sources]
        if skipped:
            errors.append(f"Skipped sources that are not enabled in Settings: {', '.join(skipped)}")
        before = db.scalar(select(JobListing.id).order_by(JobListing.id.desc()).limit(1)) or 0
        for source in sources:
            for q in queries:
                try:
                    jobs_svc.search(db, JobSearchIn(source=source, query=q, remote_only=prefs.remote_preference == "remote", limit=20), app.state.settings)  # type: ignore[arg-type]
                except AppError as exc:
                    errors.append(f"{source}: {exc.message}")
        new_ids = list(db.scalars(select(JobListing.id).where(JobListing.id > before).order_by(JobListing.id)))
    return new_ids, errors


def _select(app: FastAPI, new_ids: list[int], mode: str) -> tuple[list[int], dict[str, int]]:
    skips = {"below_threshold": 0, "suspicious_text": 0, "closed_or_rejected": 0, "already_applied": 0, "limit_reached": 0}
    chosen: list[int] = []
    with session_scope(app.state.sessionmaker) as db:
        cfg, prefs = get_config(db), profile_svc.get_preferences(db)
        room = min(cfg.max_new_per_run, max(0, prefs.max_applications_per_day - _applications_today(db)))
        scored = []
        for jid in new_ids:
            j = db.get(JobListing, jid)
            if j is None:
                continue
            if j.status == "closed" or j.user_status == "rejected":
                skips["closed_or_rejected"] += 1
            elif j.flags:
                skips["suspicious_text"] += 1  # instruction-like text aimed at AI tools: never auto-prepare these
            elif db.scalar(select(Application.id).where(Application.job_id == jid)) is not None:
                skips["already_applied"] += 1
            elif (j.match.score if j.match else 0) < prefs.match_threshold:
                skips["below_threshold"] += 1
            else:
                scored.append((j.match.score if j.match else 0, jid))
        scored.sort(reverse=True)
        chosen = [jid for _, jid in scored[:room]]
        skips["limit_reached"] = max(0, len(scored) - len(chosen))
        for jid in chosen:
            jobs_svc.set_user_status(db, jid, "shortlisted")
    _ = mode
    return chosen, skips


def _prepare(app: FastAPI, job_id: int) -> tuple[int, int | None]:
    with session_scope(app.state.sessionmaker) as db:
        a, run = apps.prepare(db, app.state.ai, app.state.settings, job_id)
        return a.id, (run.id if run else None)


async def _wait_for_run(app: FastAPI, run_id: int, timeout: float = RUN_WAIT_SECONDS) -> str:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        with session_scope(app.state.sessionmaker) as db:
            r = db.get(WorkflowRun, run_id)
            if r is not None and r.status not in (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value):
                return r.status
        await asyncio.sleep(0.5)
    return "timeout"


# ------------------------------------------------------------------ one run
async def run_bot(app: FastAPI, trigger: str = "manual") -> int:
    lock: asyncio.Lock = app.state.bot_lock
    if lock.locked():
        raise Conflict("The bot is already running.", code="bot_running")
    async with lock:
        sm = app.state.sessionmaker
        with session_scope(sm) as db:
            mode = profile_svc.get_preferences(db).submission_mode
            run = BotRun(trigger=trigger, mode=mode)
            db.add(run)
            db.flush()
            run_id = run.id
            audit.record(db, "bot_run_started", f"Bot run started ({trigger})", entity_type="bot", entity_id=run_id, meta={"mode": mode})
        details: dict[str, Any] = {"skipped": {}, "errors": [], "application_ids": []}
        counts = {"new_jobs": 0, "prepared": 0, "needs_review": 0, "submitted": 0}
        status, summary = "completed", ""
        try:
            new_ids, errors = await asyncio.to_thread(_discover, app)
            details["errors"] += errors
            counts["new_jobs"] = len(new_ids)
            if mode == SubmissionMode.RESEARCH_ONLY.value:
                summary = f"Research only: found {len(new_ids)} new job(s); nothing was prepared."
            else:
                chosen, skips = await asyncio.to_thread(_select, app, new_ids, mode)
                details["skipped"] = skips
                for jid in chosen:
                    try:
                        aid, rid = await asyncio.to_thread(_prepare, app, jid)
                    except AppError as exc:
                        details["errors"].append(f"job {jid}: {exc.message}")
                        continue
                    counts["prepared"] += 1
                    details["application_ids"].append(aid)
                    if rid is not None:
                        app.state.runner.start(rid)
                        await _wait_for_run(app, rid)
                    counts["submitted"] += await _maybe_auto_submit(app, aid, mode)
                    with session_scope(sm) as db:
                        st = apps.state_of(apps.get_application(db, aid))
                        if st not in (AppState.SUBMITTED,):
                            counts["needs_review"] += 1
                summary = (f"Found {counts['new_jobs']} new job(s); prepared {counts['prepared']}; {counts['needs_review']} need your attention"
                           + (f"; submitted {counts['submitted']} under auto-submit" if counts["submitted"] else "") + ".")
        except Exception as exc:  # never let one bad run kill the scheduler
            log.exception("bot run failed")
            status, summary = "failed", f"The bot run failed ({type(exc).__name__}). Check the server log."
        with session_scope(sm) as db:
            r = db.get(BotRun, run_id)
            assert r is not None
            r.status, r.finished_at, r.summary, r.details = status, utcnow(), summary[:500], details
            r.new_jobs, r.prepared, r.needs_review, r.submitted = counts["new_jobs"], counts["prepared"], counts["needs_review"], counts["submitted"]
            get_config(db).last_run_at = utcnow()
            audit.record(db, "bot_run_finished", summary, entity_type="bot", entity_id=run_id, meta=counts)
            audit.notify(db, "Bot run finished" if status == "completed" else "Bot run failed", summary, kind="action" if counts["needs_review"] else "info")
        return run_id


async def _maybe_auto_submit(app: FastAPI, app_id: int, mode: str) -> int:
    """Only in the user's authorized auto-submit mode, and only if the normal policy allows it right now. Otherwise: do nothing."""
    if mode != SubmissionMode.AUTHORIZED_AUTO_SUBMIT.value:
        return 0
    try:
        with session_scope(app.state.sessionmaker) as db:
            a, run, dup = apps.begin_submit(db, app_id, app.state.settings)
            rid = None if dup else run.id
    except AppError:
        return 0  # blocked by policy (unreviewed sensitive answers, unapproved documents, limits...): stays for the user
    if rid is None:
        return 0
    app.state.runner.start(rid)
    await _wait_for_run(app, rid)
    with session_scope(app.state.sessionmaker) as db:
        return 1 if apps.state_of(apps.get_application(db, app_id)) == AppState.SUBMITTED else 0


class BotScheduler:
    """Wakes up every tick; if the bot is enabled and due it runs once. Does nothing for a disabled bot."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name="bot-scheduler")

    async def _loop(self) -> None:
        tick = self.app.state.settings.bot_tick_seconds
        while True:
            try:
                await asyncio.sleep(tick)
                with session_scope(self.app.state.sessionmaker) as db:
                    due = is_due(get_config(db))
                if due and not self.app.state.bot_lock.locked():
                    await run_bot(self.app, "schedule")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("bot scheduler tick failed")

    async def shutdown(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
