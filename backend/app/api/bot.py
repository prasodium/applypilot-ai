import asyncio
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.enums import SubmissionMode
from app.main import DB
from app.models import BotRun
from app.ratelimit import limit
from app.schemas import BotConfigPatch, BotRunOut, BotStatusOut
from app.services import bot as svc
from app.services import profile as profile_svc

router = APIRouter(tags=["bot"])
log = logging.getLogger("applypilot.bot")


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("manual bot run crashed", exc_info=task.exception())


def _status(request: Request, db) -> BotStatusOut:
    running = request.app.state.bot_lock.locked()  # read BEFORE the rows: a run that ends meanwhile can then only look newer, never stale
    cfg = svc.get_config(db)
    mode = profile_svc.get_preferences(db).submission_mode
    runs = db.scalars(select(BotRun).order_by(BotRun.id.desc()).limit(20)).all()
    return BotStatusOut(config=cfg, running=running, next_run_at=svc.next_run_at(cfg), submission_mode=mode,
                        will_submit_without_you=mode == SubmissionMode.AUTHORIZED_AUTO_SUBMIT.value, runs=[BotRunOut.model_validate(r) for r in runs])


@router.get("/bot", response_model=BotStatusOut)
def get_bot(request: Request, db=DB):
    return _status(request, db)


@router.patch("/bot", response_model=BotStatusOut)
def patch_bot(request: Request, body: BotConfigPatch, db=DB):
    """Only the user can change bot settings (this call is origin-guarded); job text and web pages can never reach it."""
    svc.patch_config(db, body)
    return _status(request, db)


@router.post("/bot/run", response_model=BotStatusOut, status_code=202, dependencies=[Depends(limit("bot-run", 6))])
async def run_now(request: Request, db=DB):
    """Starts a run in the background and returns immediately; poll GET /api/bot."""
    from app.errors import Conflict

    if request.app.state.bot_lock.locked():
        raise Conflict("The bot is already running.", code="bot_running")
    svc.get_config(db)
    db.commit()  # release the request's write lock (first-use config row) before the background run writes
    task = asyncio.create_task(svc.run_bot(request.app, "manual"))
    request.app.state.bot_tasks.add(task)
    task.add_done_callback(request.app.state.bot_tasks.discard)
    task.add_done_callback(_log_failure)
    for _ in range(100):  # wait until the run holds the lock so the status we report is accurate
        if request.app.state.bot_lock.locked() or task.done():
            break
        await asyncio.sleep(0.01)
    return _status(request, db)


@router.get("/bot/runs", response_model=list[BotRunOut])
def runs(limit: int = Query(20, ge=1, le=100), db=DB):
    return db.scalars(select(BotRun).order_by(BotRun.id.desc()).limit(limit)).all()
