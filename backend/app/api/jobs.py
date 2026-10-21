from fastapi import APIRouter, Depends, Query, Request

from app.errors import NotFound
from app.main import DB
from app.ratelimit import limit
from app.schemas import JobImportIn, JobImportResult, JobSearchIn, JobSearchResult, JobsPage, JobOut, MatchOut, ShortlistIn
from app.services import jobs as svc

router = APIRouter(tags=["jobs"])


@router.post("/jobs/import", response_model=JobImportResult, status_code=201, dependencies=[Depends(limit("import", 30))])
def import_job(request: Request, body: JobImportIn, db=DB):
    job, created, dup, notes = svc.import_job(db, body, request.app.state.settings)
    return JobImportResult(job=svc.to_out(job), created=created, duplicate_of=dup, notes=notes)


@router.post("/jobs/search", response_model=JobSearchResult, dependencies=[Depends(limit("search", 20))])
def search(request: Request, body: JobSearchIn, db=DB):
    r = svc.search(db, body, request.app.state.settings)
    return JobSearchResult(source=r["source"], items=[svc.to_out(j) for j in r["items"]], created=r["created"],
                           duplicates=r["duplicates"], attribution=r["attribution"])


@router.post("/jobs/rematch")
def rematch(db=DB):
    return {"rematched": svc.rematch_all(db)}


@router.get("/jobs", response_model=JobsPage)
def list_jobs(q: str = "", source: str = "", status: str = "", user_status: str = "", arrangement: str = "", location: str = "",
              min_score: float | None = Query(None, ge=0, le=100), sort: str = Query("newest", pattern="^(newest|score)$"),
              page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db=DB):
    rows, total = svc.list_jobs(db, q=q, source=source, status=status, user_status=user_status, arrangement=arrangement,
                                location=location, min_score=min_score, sort=sort, page=page, page_size=page_size)
    return JobsPage(items=[svc.to_out(j) for j in rows], total=total, page=page, page_size=page_size)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db=DB):
    return svc.to_out(svc.get_job(db, job_id))


@router.post("/jobs/{job_id}/analyze", response_model=JobOut)
def analyze(job_id: int, db=DB):
    return svc.to_out(svc.analyze(db, job_id))


@router.post("/jobs/{job_id}/match", response_model=MatchOut)
def match(job_id: int, db=DB):
    return svc.match_out(db, svc.compute_and_store_match(db, job_id))


@router.get("/jobs/{job_id}/match", response_model=MatchOut)
def get_match(job_id: int, db=DB):
    job = svc.get_job(db, job_id)
    if job.match is None:
        raise NotFound("This job has not been matched yet.")
    return svc.match_out(db, job.match)


@router.post("/jobs/{job_id}/shortlist", response_model=JobOut)
def shortlist(job_id: int, body: ShortlistIn, db=DB):
    return svc.to_out(svc.set_user_status(db, job_id, body.status))
