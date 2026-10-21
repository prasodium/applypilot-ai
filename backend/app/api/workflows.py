from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.main import DB
from app.models import WorkflowRun
from app.schemas import WorkflowDetail, WorkflowOut
from app.services import workflow as svc

router = APIRouter(tags=["workflows"])


@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(application_id: int | None = None, status: str = "", limit: int = Query(50, ge=1, le=200), db=DB):
    stmt = select(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(limit)
    if application_id is not None:
        stmt = stmt.where(WorkflowRun.application_id == application_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    return db.scalars(stmt).all()


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: int, db=DB):
    return svc.get_run(db, workflow_id)


@router.post("/workflows/{workflow_id}/pause", response_model=WorkflowOut)
def pause(workflow_id: int, db=DB):
    return svc.request_pause(db, workflow_id)


@router.post("/workflows/{workflow_id}/resume", response_model=WorkflowOut, status_code=202)
async def resume(request: Request, workflow_id: int, db=DB):
    run = svc.prepare_resume(db, workflow_id)
    db.commit()
    request.app.state.runner.start(run.id)
    return run


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowOut)
def cancel(workflow_id: int, db=DB):
    return svc.request_cancel(db, workflow_id)
