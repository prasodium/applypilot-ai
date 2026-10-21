from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import select

from app.errors import Unprocessable
from app.main import DB
from app.models import CandidateDocument
from app.ratelimit import limit
from app.schemas import (
    ApplyParseIn,
    DocumentDetail,
    DocumentOut,
    GenerateIn,
    ProfileOut,
)
from app.services import documents as svc
from app.services import profile as profile_svc

router = APIRouter(tags=["documents"])


@router.post("/documents", response_model=DocumentDetail, status_code=201, dependencies=[Depends(limit("upload", 20))])
async def upload(request: Request, file: UploadFile = File(...), db=DB):
    s = request.app.state.settings
    data = await file.read(s.max_upload_bytes + 1)  # never buffer more than the limit + 1 byte
    return svc.upload_resume(db, filename=file.filename or "", content_type=file.content_type, data=data,
                             upload_dir=s.upload_dir, max_bytes=s.max_upload_bytes)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(kind: str | None = None, job_id: int | None = None, db=DB):
    q = select(CandidateDocument).order_by(CandidateDocument.id.desc())
    if kind:
        q = q.where(CandidateDocument.kind == kind)
    if job_id is not None:
        q = q.where(CandidateDocument.job_id == job_id)
    return db.scalars(q).all()


@router.post("/documents/master/rebuild", response_model=DocumentDetail, status_code=201)
def rebuild_master(db=DB):
    return svc.generate_master_resume(db)


@router.post("/documents/generate-resume", response_model=DocumentDetail, status_code=201, dependencies=[Depends(limit("generate", 30))])
def generate_resume(body: GenerateIn, db=DB):
    if body.job_id is None:
        return svc.generate_master_resume(db)
    return svc.generate_tailored_resume(db, body.job_id, body.notes)


@router.post("/documents/generate-cover-letter", response_model=DocumentDetail, status_code=201, dependencies=[Depends(limit("generate", 30))])
def generate_cover_letter(request: Request, body: GenerateIn, db=DB):
    if body.job_id is None:
        raise Unprocessable("A job is required to write a cover letter.", code="job_required")
    return svc.generate_cover_letter(db, request.app.state.ai, body.job_id, body.notes)


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, db=DB):
    return svc.get_document(db, doc_id)


@router.post("/documents/{doc_id}/parse", response_model=DocumentDetail)
def parse(doc_id: int, db=DB):
    return svc.parse_document(db, doc_id)


@router.post("/documents/{doc_id}/apply-parse", response_model=ProfileOut)
def apply_parse(doc_id: int, body: ApplyParseIn, db=DB):
    svc.apply_parse(db, doc_id, body)
    return profile_svc.fresh_profile(db)


@router.put("/documents/{doc_id}/text", response_model=DocumentDetail)
def edit_text(doc_id: int, body: dict, db=DB):
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise Unprocessable("Provide the new text.", code="text_required")
    return svc.edit_text(db, doc_id, text)


@router.post("/documents/{doc_id}/approve", response_model=DocumentDetail)
def approve(doc_id: int, db=DB):
    return svc.approve(db, doc_id)


@router.delete("/documents/{doc_id}", status_code=204)
def delete(request: Request, doc_id: int, db=DB):
    svc.delete_document(db, doc_id, request.app.state.settings.upload_dir)
    return Response(status_code=204)


@router.get("/documents/{doc_id}/diff")
def diff(doc_id: int, against: int = Query(...), db=DB):
    return {"lines": svc.diff(db, doc_id, against)}


@router.get("/documents/{doc_id}/download")
def download(doc_id: int, format: str = Query("txt", pattern="^(txt|docx|pdf)$"), db=DB):
    d = svc.get_document(db, doc_id)
    stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in d.filename.rsplit(".", 1)[0])[:80] or "document"
    headers = {"Content-Disposition": f'attachment; filename="{stem}.{format}"'}
    if format == "docx":
        return Response(svc.render_docx(d), media_type=svc.DOCX_MIME, headers=headers)
    if format == "pdf":
        return Response(svc.render_pdf(d), media_type="application/pdf", headers=headers)
    return Response(d.text_content, media_type="text/plain; charset=utf-8", headers=headers)
