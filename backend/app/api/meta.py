from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.browser.capabilities import registry
from app.core.enums import AppState
from app.errors import NotFound
from app.jobsources.registry import describe_sources
from app.main import DB
from app.models import Application, AuditLog, JobListing, Notification
from app.schemas import (
    AuditOut,
    DashboardOut,
    NotificationOut,
    NotificationPatch,
    PreferencesOut,
    PreferencesPatch,
    SettingsOut,
    SettingsPatch,
)
from app.services import profile as profile_svc

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}


def _settings_out(request: Request, db) -> SettingsOut:
    s = request.app.state.settings
    prefs = profile_svc.get_preferences(db)
    sources = [{**row, "enabled": row["name"] in prefs.allowed_sources} for row in describe_sources()]
    return SettingsOut(app_env=s.app_env, ai_provider=s.ai_provider, ai_model=s.ai_model, ai_api_key_set=bool(s.ai_api_key.get_secret_value()),
                       ai_demo_mode=bool(request.app.state.ai.is_demo), browser_headless=s.browser_headless,
                       mock_employer_base_url=s.mock_employer_base_url, max_upload_mb=s.max_upload_mb,
                       preferences=PreferencesOut.model_validate(prefs), job_sources=sources,
                       site_capabilities=[c.as_dict() for c in registry(s)])


@router.get("/settings", response_model=SettingsOut)
def get_settings(request: Request, db=DB):
    return _settings_out(request, db)


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(request: Request, body: SettingsPatch, db=DB):
    """Settings change ONLY through this explicit, user-initiated call. External content can never reach it."""
    if body.job_source_enabled:
        known = {r["name"] for r in describe_sources()}
        unknown = set(body.job_source_enabled) - known
        if unknown:
            raise NotFound(f"Unknown job source(s): {', '.join(sorted(unknown))}")
        allowed = set(profile_svc.get_preferences(db).allowed_sources)
        for name, on in body.job_source_enabled.items():
            (allowed.add if on else allowed.discard)(name)
        profile_svc.patch_preferences(db, PreferencesPatch(allowed_sources=sorted(allowed)))
    if body.preferences:
        profile_svc.patch_preferences(db, body.preferences)
    return _settings_out(request, db)


@router.get("/sources")
def sources(db=DB):
    prefs = profile_svc.get_preferences(db)
    return [{**row, "enabled": row["name"] in prefs.allowed_sources} for row in describe_sources()]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(request: Request, db=DB):
    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery())) or 0  # noqa: E731
    states = lambda *s: count(select(Application).where(Application.state.in_([x.value for x in s])))  # noqa: E731
    needs = states(AppState.PROFILE_INFORMATION_REQUIRED, AppState.LOGIN_REQUIRED, AppState.HUMAN_VERIFICATION_REQUIRED,
                   AppState.EMAIL_VERIFICATION_REQUIRED, AppState.ACCOUNT_CREATION_REQUIRED, AppState.FORM_VALIDATION_FAILED)
    ready = states(AppState.READY_FOR_REVIEW, AppState.SUBMISSION_PENDING_APPROVAL)
    unconfirmed = states(AppState.SUBMISSION_UNCONFIRMED)
    actions: list[str] = []
    if needs:
        actions.append(f"{needs} application(s) need your input or a challenge completed.")
    if ready:
        actions.append(f"{ready} application(s) are ready for your review.")
    if unconfirmed:
        actions.append(f"{unconfirmed} submission(s) have an unconfirmed result. Check and record the outcome.")
    p = profile_svc.get_profile(db)
    if not p.legal_name:
        actions.append("Create your profile to get started.")
    recent = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(10)).all()
    return DashboardOut(
        jobs_discovered=count(select(JobListing)), shortlisted=count(select(JobListing).where(JobListing.user_status == "shortlisted")),
        draft_applications=states(AppState.APPLICATION_PREPARING, AppState.FORM_IN_PROGRESS, AppState.PROFILE_INFORMATION_REQUIRED),
        awaiting_review=ready, submitted=states(AppState.SUBMITTED), unconfirmed=unconfirmed, needs_user_action=needs,
        recent_activity=[AuditOut.model_validate(r) for r in recent], next_actions=actions, demo_mode=bool(request.app.state.ai.is_demo))


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(unread: bool = False, limit: int = Query(50, ge=1, le=200), db=DB):
    stmt = select(Notification).order_by(Notification.id.desc()).limit(limit)
    if unread:
        stmt = stmt.where(Notification.read.is_(False))
    return db.scalars(stmt).all()


@router.patch("/notifications/{notification_id}", response_model=NotificationOut)
def patch_notification(notification_id: int, body: NotificationPatch, db=DB):
    n = db.get(Notification, notification_id)
    if n is None:
        raise NotFound("Notification not found")
    n.read = body.read
    return n


@router.get("/audit", response_model=list[AuditOut])
def audit_log(event_type: str = "", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db=DB):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    return db.scalars(stmt).all()
