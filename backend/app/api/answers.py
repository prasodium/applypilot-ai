from fastapi import APIRouter, Depends, Request

from app.main import DB
from app.ratelimit import limit
from app.schemas import AnswerDraft, DraftAnswerIn
from app.services import answers as svc
from app.services import jobs as jobs_svc

router = APIRouter(tags=["answers"])


@router.post("/answers/draft", response_model=AnswerDraft, dependencies=[Depends(limit("answers", 60))])
def draft_answer(request: Request, body: DraftAnswerIn, db=DB):
    """Draft one answer from confirmed facts. Never stored and never submitted: a preview for the user."""
    job = jobs_svc.get_job(db, body.job_id) if body.job_id else None
    engine = svc.AnswerEngine(svc.build_context(db, job), request.app.state.ai)
    return engine.draft(svc.QuestionSpec(body.label, body.field_type, body.options, body.max_length, body.required))
