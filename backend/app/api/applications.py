from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from app.main import DB
from app.models import Application, JobListing
from app.ratelimit import limit
from app.schemas import (
    ApplicationDetail,
    ApplicationOut,
    ApplicationPatch,
    ApproveIn,
    AttestIn,
    PrepareIn,
    WorkflowOut,
)
from app.services import applications as svc

router = APIRouter(tags=["applications"])


@router.post("/applications/prepare", response_model=ApplicationDetail, status_code=201, dependencies=[Depends(limit("prepare", 20))])
async def prepare(request: Request, body: PrepareIn, db=DB):
    a, run = svc.prepare(db, request.app.state.ai, request.app.state.settings, body.job_id)
    db.commit()  # the background run must see committed data
    if run is not None:
        request.app.state.runner.start(run.id)
    return svc.detail(db, a, request.app.state.settings)


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(state: str = "", q: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db=DB):
    stmt = select(Application).join(JobListing, JobListing.id == Application.job_id)
    if state:
        stmt = stmt.where(Application.state == state)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(JobListing.title).like(like), func.lower(JobListing.company).like(like)))
    rows = db.scalars(stmt.order_by(Application.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return [svc.to_out(db, a) for a in rows]


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
def get_application(request: Request, application_id: int, db=DB):
    return svc.detail(db, svc.get_application(db, application_id), request.app.state.settings)


@router.patch("/applications/{application_id}", response_model=ApplicationDetail)
def patch_application(request: Request, application_id: int, body: ApplicationPatch, db=DB):
    a = svc.patch(db, application_id, body)
    return svc.detail(db, a, request.app.state.settings)


@router.post("/applications/{application_id}/fill", response_model=WorkflowOut, status_code=202)
async def fill(request: Request, application_id: int, db=DB):
    """Open the form in the browser, fill it from the stored answers and verify every value. NEVER submits."""
    run = svc.start_fill(db, application_id, request.app.state.settings)
    db.commit()
    request.app.state.runner.start(run.id)
    return run


@router.post("/applications/{application_id}/approve", response_model=ApplicationDetail, dependencies=[Depends(limit("approve", 20))])
def approve(request: Request, application_id: int, body: ApproveIn, db=DB):
    a = svc.approve(db, application_id, body.version)
    return svc.detail(db, a, request.app.state.settings)


@router.post("/applications/{application_id}/submit", status_code=202, dependencies=[Depends(limit("submit", 10))])
async def submit(request: Request, application_id: int, db=DB):
    """Policy-gated and idempotent. A repeated request returns the existing run instead of submitting again."""
    a, run, dup = svc.begin_submit(db, application_id, request.app.state.settings)
    db.commit()
    if not dup:
        request.app.state.runner.start(run.id)
    return {"application_id": a.id, "workflow_id": run.id, "duplicate_request": dup, "state": a.state}


@router.post("/applications/{application_id}/attest", response_model=ApplicationDetail)
def attest(request: Request, application_id: int, body: AttestIn, db=DB):
    """The user records what they found (e.g. after an UNCONFIRMED result). Stored as user_attested, not machine-verified."""
    return svc.detail(db, svc.attest(db, application_id, body), request.app.state.settings)


@router.post("/applications/{application_id}/cancel", response_model=ApplicationDetail)
def cancel(request: Request, application_id: int, db=DB):
    return svc.detail(db, svc.cancel(db, application_id), request.app.state.settings)
