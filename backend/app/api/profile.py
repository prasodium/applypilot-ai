
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.main import DB
from app.models import CandidateProject, EducationRecord, Skill, WorkExperience
from app.schemas import (
    ApprovedAnswerIn,
    ApprovedAnswerOut,
    EducationIn,
    EducationOut,
    ExperienceIn,
    ExperienceOut,
    Fact,
    PreferencesOut,
    PreferencesPatch,
    ProfileFields,
    ProfileOut,
    ProfilePatch,
    ProjectIn,
    ProjectOut,
    SkillIn,
    SkillOut,
)
from app.services import profile as svc

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=ProfileOut)
def get_profile(db=DB):
    return svc.get_profile(db)


@router.put("/profile", response_model=ProfileOut)
def put_profile(body: ProfileFields, db=DB):
    return svc.replace_profile(db, body)


@router.patch("/profile", response_model=ProfileOut)
def patch_profile(body: ProfilePatch, db=DB):
    return svc.patch_profile(db, body)


@router.get("/profile/facts", response_model=list[Fact])
def facts(db=DB):
    return svc.all_facts(db)


@router.post("/profile/facts/{fact_id}/confirm", response_model=Fact)
def confirm_fact(fact_id: str, db=DB):
    return svc.confirm_fact(db, fact_id)


def _crud(path: str, model, add, in_schema, out_schema):
    @router.post(f"/profile/{path}", response_model=out_schema, status_code=201, name=f"add_{path}")
    def create(body: in_schema, db=DB):  # type: ignore[valid-type]
        return add(db, body)

    @router.put(f"/profile/{path}/{{rid}}", response_model=out_schema, name=f"update_{path}")
    def update(rid: int, body: in_schema, db=DB):  # type: ignore[valid-type]
        return svc.update_record(db, model, rid, body)

    @router.delete(f"/profile/{path}/{{rid}}", status_code=204, name=f"delete_{path}")
    def remove(rid: int, db=DB):
        svc.delete_record(db, model, rid)
        return Response(status_code=204)


_crud("education", EducationRecord, svc.add_education, EducationIn, EducationOut)
_crud("experience", WorkExperience, svc.add_experience, ExperienceIn, ExperienceOut)
_crud("skills", Skill, svc.add_skill, SkillIn, SkillOut)
_crud("projects", CandidateProject, svc.add_project, ProjectIn, ProjectOut)


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(db=DB):
    return svc.get_preferences(db)


@router.patch("/preferences", response_model=PreferencesOut)
def patch_preferences(body: PreferencesPatch, db=DB):
    return svc.patch_preferences(db, body)


@router.get("/answer-library", response_model=list[ApprovedAnswerOut])
def list_answers(db=DB):
    from sqlalchemy import select

    from app.models import ApprovedAnswer

    return db.scalars(select(ApprovedAnswer).order_by(ApprovedAnswer.id)).all()


@router.post("/answer-library", response_model=ApprovedAnswerOut, status_code=201)
def add_answer(body: ApprovedAnswerIn, db=DB):
    return svc.add_approved_answer(db, body)


@router.delete("/answer-library/{aid}", status_code=204)
def delete_answer(aid: int, db=DB):
    from app.models import ApprovedAnswer

    svc.delete_record(db, ApprovedAnswer, aid)
    return Response(status_code=204)


@router.get("/data/export")
def export_data(db=DB):
    return JSONResponse(svc.export_all(db), headers={"Content-Disposition": 'attachment; filename="applypilot-export.json"'})


@router.delete("/data")
def delete_data(request: Request, confirm: str = "", db=DB):
    from app.errors import Unprocessable

    if confirm != "DELETE":
        raise Unprocessable("Pass ?confirm=DELETE to permanently delete all local data.", code="confirmation_required")
    return {"deleted": svc.delete_all(db, request.app.state.settings.upload_dir)}
