"""End-to-end tests: real headless Chromium + real HTTP mock employer. No real employer is ever contacted."""
from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.mock_employer.app import build_mock_employer

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def mock_site():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(build_mock_employer(), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture(autouse=True)
def reset_site(mock_site):
    httpx.post(mock_site + "/__admin/reset")


@pytest.fixture()
def settings(tmp_path, mock_site) -> Settings:  # overrides the conftest fixture
    return Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", upload_dir=tmp_path / "uploads", ai_provider="mock",
                    mock_employer_base_url=mock_site, mount_mock_employer=False, serve_frontend=False, browser_headless=True, _env_file=None)


def submissions(site):
    return httpx.get(site + "/__admin/submissions").json()["submissions"]


def job_id(client, company):
    client.post("/api/jobs/search", json={"source": "mock"})
    return next(j["id"] for j in client.get("/api/jobs").json()["items"] if company in j["company"])


def wait(client, wid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        w = client.get(f"/api/workflows/{wid}").json()
        if w["status"] not in ("queued", "running"):
            return w
        time.sleep(0.3)
    raise AssertionError(f"workflow {wid} did not finish: {w}")


def runs(client, aid):
    return client.get(f"/api/workflows?application_id={aid}").json()


def latest_run(client, aid):
    return runs(client, aid)[0]


def prepare(client, jid):
    r = client.post("/api/applications/prepare", json={"job_id": jid})
    assert r.status_code == 201, r.text
    d = r.json()
    return d, wait(client, latest_run(client, d["id"])["id"])


def app_detail(client, aid):
    return client.get(f"/api/applications/{aid}").json()


def qid(detail, key):
    return next(q["id"] for q in detail["questions"] if q["field_key"] == key)


def fill_and_wait(client, aid):
    r = client.post(f"/api/applications/{aid}/fill")
    assert r.status_code == 202, r.text
    return wait(client, r.json()["id"])


def answer_known(client, aid):
    """What a careful user does with the questions discovered so far: answer the sensitive/legal ones themselves and approve the
    sponsorship answer that came from their own profile. Multi-step forms reveal later questions only after earlier ones are answered."""
    d = app_detail(client, aid)
    keys = {q["field_key"]: q for q in d["questions"]}
    ch = {}
    for key in ("work_auth", "certify"):
        if key in keys and not keys[key]["answer"]["answer_text"]:
            ch[keys[key]["id"]] = {"answer_text": "Yes"}
    if "sponsorship" in keys and keys["sponsorship"]["answer"]["review_status"] == "pending_review":
        ch[keys["sponsorship"]["id"]] = {"review_status": "approved"}
    if ch:
        r = client.patch(f"/api/applications/{aid}", json={"answers": ch})
        assert r.status_code == 200, r.text
    return ch


def complete_answers(client, aid):
    answer_known(client, aid)
    return app_detail(client, aid)


@pytest.fixture()
def ready(candidate):
    candidate.patch("/api/profile", json={"requires_sponsorship": False})
    return candidate


def to_ready_for_review(client, company="Globex"):
    d, w = prepare(client, job_id(client, company))
    aid = d["id"]
    assert app_detail(client, aid)["state"] == "PROFILE_INFORMATION_REQUIRED" and w["status"] == "waiting_user"
    for _ in range(5):  # each pass answers what is known, then the browser walks further (multi-step forms)
        answer_known(client, aid)
        w = fill_and_wait(client, aid)
        if app_detail(client, aid)["state"] != "PROFILE_INFORMATION_REQUIRED":
            break
    assert w["status"] == "succeeded", w
    d = app_detail(client, aid)
    assert d["state"] == "READY_FOR_REVIEW" and d["issues"] == [] and d["ready_for_approval"] is True
    return aid


def approve_and_submit(client, aid):
    d = app_detail(client, aid)
    r = client.post(f"/api/applications/{aid}/approve", json={"version": d["version"]})
    assert r.status_code == 200, r.text
    s = client.post(f"/api/applications/{aid}/submit")
    assert s.status_code == 202, s.text
    return s.json(), wait(client, s.json()["workflow_id"])


# ======================================================================== happy path
def test_full_flow_review_then_verified_submission(ready, mock_site):
    aid = to_ready_for_review(ready)
    assert submissions(mock_site) == []  # filling and review never submit
    body, w = approve_and_submit(ready, aid)
    assert body["duplicate_request"] is False and w["status"] == "succeeded"
    d = app_detail(ready, aid)
    assert d["state"] == "SUBMITTED" and d["outcome"] == "confirmed" and d["confirmation_reference"].startswith("MOCK-")
    assert d["is_demo"] is True and d["target_kind"] == "mock"
    subs = submissions(mock_site)
    assert len(subs) == 1 and subs[0]["email"] == "alex@example.test" and subs[0]["resume_filename"] == "resume.pdf" and subs[0]["certify"] is True
    assert d["outcome_evidence"]["reference"] == d["confirmation_reference"] and set(d["outcome_evidence"]) <= {"outcome", "checked_at", "page", "reference"}
    assert d["submit_decision"]["allowed"] is False  # nothing further to submit
    events = [e["event_type"] for e in ready.get("/api/audit?limit=500").json()]
    for needed in ("application_prepared", "answer_drafted", "approval_granted", "submission_attempted", "submission_confirmed"):
        assert needed in events, needed
    notes = [n["title"] for n in ready.get("/api/notifications").json()]
    assert "Application submitted" in notes and "Application ready for review" in notes


def test_no_personal_data_in_logs_events_or_evidence(ready, mock_site):
    aid = to_ready_for_review(ready)
    approve_and_submit(ready, aid)
    blob = json.dumps(ready.get("/api/audit?limit=500").json()) + json.dumps(ready.get("/api/notifications").json())
    for w in runs(ready, aid):
        blob += json.dumps(ready.get(f"/api/workflows/{w['id']}").json())
    blob += json.dumps(app_detail(ready, aid)["outcome_evidence"])
    for secret in ("alex@example.test", "+1 555", "linkedin.example", "Springfield", "Reduced report generation"):
        assert secret not in blob, secret


def test_evidence_capture_can_be_turned_off(ready, mock_site):
    ready.patch("/api/preferences", json={"evidence_capture": "none"})
    aid = to_ready_for_review(ready)
    approve_and_submit(ready, aid)
    assert app_detail(ready, aid)["outcome_evidence"] == {"outcome": "confirmed"}


# ======================================================================== required info, sensitive, legal
def test_unknown_required_answers_stop_the_form_and_nothing_is_guessed(ready, mock_site):
    d, w = prepare(ready, job_id(ready, "Globex"))
    d = app_detail(ready, d["id"])
    assert d["state"] == "PROFILE_INFORMATION_REQUIRED" and w["error_category"] == "needs_input"
    codes = {i["message"] for i in d["issues"]}
    assert any("authorized to work" in m for m in codes) and any("certify" in m for m in codes)
    wa = next(q for q in d["questions"] if q["field_key"] == "work_auth")
    cert = next(q for q in d["questions"] if q["field_key"] == "certify")
    assert wa["answer"]["answer_text"] == "" and wa["sensitive_or_legal"] and cert["answer"]["answer_text"] == "" and cert["is_legal"]
    assert submissions(mock_site) == []
    assert ready.post(f"/api/applications/{d['id']}/submit").status_code == 403


def test_sensitive_answers_need_explicit_review_before_approval(ready, mock_site):
    d, _ = prepare(ready, job_id(ready, "Globex"))
    aid = d["id"]
    dd = app_detail(ready, aid)
    ready.patch(f"/api/applications/{aid}", json={"answers": {qid(dd, "work_auth"): {"answer_text": "Yes"}, qid(dd, "certify"): {"answer_text": "Yes"}}})
    w = fill_and_wait(ready, aid)
    d = app_detail(ready, aid)
    assert d["state"] == "READY_FOR_REVIEW" and [i["code"] for i in d["issues"]] == ["sensitive_unreviewed"]  # sponsorship came from the profile
    r = ready.post(f"/api/applications/{aid}/approve", json={"version": d["version"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "incomplete_answers"
    assert w["status"] == "succeeded"


# ======================================================================== validation, multi-step, challenges
def test_multistep_form_is_walked_to_the_final_step_without_submitting(ready, mock_site):
    d, w = prepare(ready, job_id(ready, "Initech"))
    aid = d["id"]
    d = app_detail(ready, aid)
    assert d["state"] == "PROFILE_INFORMATION_REQUIRED"  # step 2 asks the work-authorization question
    keys = {q["field_key"] for q in d["questions"]}
    assert keys >= {"full_name", "email", "phone", "linkedin", "work_auth", "sponsorship"} and "certify" not in keys  # step 3 not seen yet
    assert max(q["step_index"] for q in d["questions"]) == 1
    answer_known(ready, aid)
    w = fill_and_wait(ready, aid)  # now step 3 is reached and reveals the legal declaration
    d = app_detail(ready, aid)
    assert d["state"] == "PROFILE_INFORMATION_REQUIRED" and "certify" in {q["field_key"] for q in d["questions"]}
    assert max(q["step_index"] for q in d["questions"]) == 2
    answer_known(ready, aid)
    w = fill_and_wait(ready, aid)
    d = app_detail(ready, aid)
    assert w["status"] == "succeeded" and d["state"] == "READY_FOR_REVIEW" and {q["field_key"] for q in d["questions"]} >= {"resume", "certify"}
    assert submissions(mock_site) == []


def test_server_side_validation_errors_are_detected(ready, mock_site):
    d, _ = prepare(ready, job_id(ready, "Initech"))
    aid = d["id"]
    answer_known(ready, aid)
    fill_and_wait(ready, aid)  # reaches step 3 and asks for the legal declaration
    answer_known(ready, aid)
    dd = app_detail(ready, aid)
    ready.patch(f"/api/applications/{aid}", json={"answers": {qid(dd, "years_python"): {"answer_text": "5.5"}}})
    w = fill_and_wait(ready, aid)
    d = app_detail(ready, aid)
    assert d["state"] == "FORM_VALIDATION_FAILED" and "whole number" in d["last_error"] and w["error_category"] == "validation"
    ready.patch(f"/api/applications/{aid}", json={"answers": {qid(d, "years_python"): {"answer_text": "5"}}})
    assert fill_and_wait(ready, aid)["status"] == "succeeded"
    assert app_detail(ready, aid)["state"] == "READY_FOR_REVIEW"


def test_human_verification_pauses_for_the_user_and_is_never_bypassed(ready, mock_site):
    d, w = prepare(ready, job_id(ready, "Wayne"))
    aid = d["id"]
    d = app_detail(ready, aid)  # the challenge is detected as soon as the page opens, before any field is touched
    assert d["state"] == "HUMAN_VERIFICATION_REQUIRED" and w["status"] == "waiting_user" and w["error_category"] == "human_verification"
    assert "never tries to solve" in d["next_action"] and d["questions"] == [] and submissions(mock_site) == []
    assert ready.post(f"/api/applications/{aid}/submit").status_code == 403
    again = fill_and_wait(ready, aid)  # re-checking does not get past it either
    assert app_detail(ready, aid)["state"] == "HUMAN_VERIFICATION_REQUIRED" and again["status"] == "waiting_user" and submissions(mock_site) == []
    notes = [n["title"] for n in ready.get("/api/notifications").json()]
    assert "Human verification needed" in notes


def test_expired_session_at_submit_requires_sign_in_and_nothing_is_recorded(ready, mock_site):
    aid = to_ready_for_review(ready, "Soylent")
    body, w = approve_and_submit(ready, aid)
    d = app_detail(ready, aid)
    assert d["state"] == "LOGIN_REQUIRED" and w["error_category"] == "login_required" and d["confirmation_reference"] == ""
    assert submissions(mock_site) == [] and d["outcome"] == ""


# ======================================================================== ambiguity, idempotency, duplicates
def test_ambiguous_result_is_unconfirmed_and_never_retried(ready, mock_site):
    aid = to_ready_for_review(ready, "Stark")
    body, w = approve_and_submit(ready, aid)
    d = app_detail(ready, aid)
    assert d["state"] == "SUBMISSION_UNCONFIRMED" and d["outcome"] == "unconfirmed" and d["confirmation_reference"] == ""
    assert len(submissions(mock_site)) == 1 and "automatically" in d["next_action"]
    n_runs = len(runs(ready, aid))
    again = ready.post(f"/api/applications/{aid}/submit")
    assert again.status_code == 202 and again.json()["duplicate_request"] is True  # idempotent: no second submission
    assert len(submissions(mock_site)) == 1 and len(runs(ready, aid)) == n_runs
    assert ready.post(f"/api/applications/{aid}/fill").status_code == 409  # cannot "re-check" and retry either
    attested = ready.post(f"/api/applications/{aid}/attest", json={"outcome": "submitted", "note": "Saw it in my inbox"}).json()
    assert attested["state"] == "SUBMITTED" and attested["outcome"] == "user_attested" and attested["confirmation_reference"] == ""
    assert attested["outcome_evidence"]["attested_by_user"] is True


def test_repeated_submit_requests_never_double_submit(ready, mock_site):
    aid = to_ready_for_review(ready)
    d = app_detail(ready, aid)
    ready.post(f"/api/applications/{aid}/approve", json={"version": d["version"]})
    first = ready.post(f"/api/applications/{aid}/submit").json()
    second = ready.post(f"/api/applications/{aid}/submit").json()
    assert first["duplicate_request"] is False and second["duplicate_request"] is True and second["workflow_id"] == first["workflow_id"]
    wait(ready, first["workflow_id"])
    third = ready.post(f"/api/applications/{aid}/submit").json()
    assert third["duplicate_request"] is True and len(submissions(mock_site)) == 1


def test_duplicate_application_for_the_same_job_is_refused(ready, mock_site):
    d, _ = prepare(ready, job_id(ready, "Globex"))
    r = ready.post("/api/applications/prepare", json={"job_id": d["job_id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_application"
    assert r.json()["error"]["details"]["application_id"] == d["id"]


# ======================================================================== approval binding and policy
def test_editing_after_approval_invalidates_it(ready, mock_site):
    aid = to_ready_for_review(ready)
    d = app_detail(ready, aid)
    v = d["version"]
    ready.post(f"/api/applications/{aid}/approve", json={"version": v})
    assert app_detail(ready, aid)["state"] == "SUBMISSION_PENDING_APPROVAL"
    ready.patch(f"/api/applications/{aid}", json={"answers": {qid(d, "motivation"): {"answer_text": "Changed after approval"}}})
    d2 = app_detail(ready, aid)
    assert d2["version"] == v + 1 and d2["approved_version"] is None and d2["state"] == "READY_FOR_REVIEW"
    r = ready.post(f"/api/applications/{aid}/submit")
    assert r.status_code == 403 and r.json()["error"]["code"] == "submission_denied"
    assert {"state_not_submittable", "approval_missing_or_stale"} <= set(r.json()["error"]["details"]["reasons"])
    stale = ready.post(f"/api/applications/{aid}/approve", json={"version": v})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"
    assert "form_not_verified" in ready.post(f"/api/applications/{aid}/approve", json={"version": v + 1}).text  # must re-check the edited form
    assert submissions(mock_site) == []
    events = [e["event_type"] for e in ready.get("/api/audit?limit=500").json()]
    assert "approval_revoked" in events


def test_default_mode_is_review_and_unapproved_submit_is_refused(ready, mock_site):
    assert ready.get("/api/preferences").json()["submission_mode"] == "review_before_submission"
    aid = to_ready_for_review(ready)
    r = ready.post(f"/api/applications/{aid}/submit")
    assert r.status_code == 403 and "approval_missing_or_stale" in r.json()["error"]["details"]["reasons"]
    assert submissions(mock_site) == []


@pytest.mark.parametrize("mode", ["prepare_only", "research_only"])
def test_restrictive_modes_never_submit(ready, mock_site, mode):
    aid = to_ready_for_review(ready)
    ready.patch("/api/preferences", json={"submission_mode": mode})
    assert ready.post(f"/api/applications/{aid}/approve", json={"version": app_detail(ready, aid)["version"]}).status_code == 403
    r = ready.post(f"/api/applications/{aid}/submit")
    assert r.status_code == 403 and "mode_does_not_allow_submission" in r.json()["error"]["details"]["reasons"]
    assert submissions(mock_site) == []
    if mode == "research_only":
        assert ready.post("/api/applications/prepare", json={"job_id": job_id(ready, "Initech")}).status_code == 403


def test_auto_submit_needs_every_condition(ready, mock_site):
    ready.patch("/api/preferences", json={"submission_mode": "authorized_auto_submit"})
    aid = to_ready_for_review(ready)
    r = ready.post(f"/api/applications/{aid}/submit")  # documents are still drafts
    assert r.status_code == 403 and "documents_not_approved" in r.json()["error"]["details"]["reasons"]
    d = app_detail(ready, aid)
    for did in (d["resume_document_id"], d["cover_letter_document_id"]):
        ready.post(f"/api/documents/{did}/approve")
    s = ready.post(f"/api/applications/{aid}/submit")
    assert s.status_code == 202, s.text
    assert wait(ready, s.json()["workflow_id"])["status"] == "succeeded"
    assert app_detail(ready, aid)["state"] == "SUBMITTED" and len(submissions(mock_site)) == 1
    assert "auto_submit_authorized" in [e["event_type"] for e in ready.get("/api/audit?limit=500").json()]


def test_auto_submit_is_blocked_by_unresolved_legal_declaration(ready, mock_site):
    ready.patch("/api/preferences", json={"submission_mode": "authorized_auto_submit"})
    d, _ = prepare(ready, job_id(ready, "Globex"))
    aid = d["id"]
    dd = app_detail(ready, aid)
    ready.patch(f"/api/applications/{aid}", json={"answers": {qid(dd, "work_auth"): {"answer_text": "Yes"}}})  # certify deliberately left to the user
    fill_and_wait(ready, aid)
    d = app_detail(ready, aid)
    assert d["state"] == "PROFILE_INFORMATION_REQUIRED"
    r = ready.post(f"/api/applications/{aid}/submit")
    assert r.status_code == 403 and "incomplete_answers" in r.json()["error"]["details"]["reasons"]
    assert submissions(mock_site) == []


def test_daily_limit_is_enforced(ready, mock_site):
    ready.patch("/api/preferences", json={"max_applications_per_day": 1})
    a1 = to_ready_for_review(ready, "Globex")
    approve_and_submit(ready, a1)
    a2 = to_ready_for_review(ready, "Initech")
    d = app_detail(ready, a2)
    ready.post(f"/api/applications/{a2}/approve", json={"version": d["version"]})
    r = ready.post(f"/api/applications/{a2}/submit")
    assert r.status_code == 403 and "daily_limit_reached" in r.json()["error"]["details"]["reasons"]
    assert len(submissions(mock_site)) == 1


# ======================================================================== unsupported sites -> manual handoff
def test_unsupported_site_gets_a_manual_handoff_not_automation(ready, mock_site):
    r = ready.post("/api/jobs/import", json={"text": "Platform Engineer\nRequirements:\n- Python\n", "fields": {
        "company": "RealCorp", "title": "Platform Engineer", "application_url": "https://careers.example.com/apply/123"}})
    jid = r.json()["job"]["id"]
    d = ready.post("/api/applications/prepare", json={"job_id": jid}).json()
    assert d["target_kind"] == "manual" and d["state"] == "READY_FOR_REVIEW" and d["questions"] == []
    assert d["resume_document_id"] and d["cover_letter_document_id"]  # documents are still prepared for the user
    assert ready.post(f"/api/applications/{d['id']}/fill").status_code == 403
    assert ready.post(f"/api/applications/{d['id']}/approve", json={"version": d["version"]}).json()["error"]["code"] == "manual_handoff"
    s = ready.post(f"/api/applications/{d['id']}/submit")
    assert s.status_code == 403 and "site_not_supported" in s.json()["error"]["details"]["reasons"]
    assert latest_run_count(ready, d["id"]) == 0  # no browser run was ever created
    ok = ready.post(f"/api/applications/{d['id']}/attest", json={"outcome": "submitted", "note": "Applied on their site"}).json()
    assert ok["state"] == "SUBMITTED" and ok["outcome"] == "user_attested"


def latest_run_count(client, aid):
    return len(runs(client, aid))


# ======================================================================== pause / resume / cancel / recovery
def test_pause_and_resume_a_running_fill(ready, mock_site):
    d = ready.post("/api/applications/prepare", json={"job_id": job_id(ready, "Globex")}).json()
    wid = latest_run(ready, d["id"])["id"]
    assert ready.post(f"/api/workflows/{wid}/pause").status_code == 200  # requested while the browser is still starting
    w = wait(ready, wid)
    assert w["status"] == "paused" and app_detail(ready, d["id"])["state"] == "FORM_IN_PROGRESS" and submissions(mock_site) == []
    r = ready.post(f"/api/workflows/{wid}/resume")
    assert r.status_code == 202 and r.json()["retry_count"] == 1
    w2 = wait(ready, wid)
    assert w2["status"] == "waiting_user" and app_detail(ready, d["id"])["state"] == "PROFILE_INFORMATION_REQUIRED"
    assert ready.post(f"/api/workflows/{wid}/pause").status_code == 409  # not running any more


def test_cancel_a_running_fill(ready, mock_site):
    d = ready.post("/api/applications/prepare", json={"job_id": job_id(ready, "Globex")}).json()
    wid = latest_run(ready, d["id"])["id"]
    assert ready.post(f"/api/workflows/{wid}/cancel").status_code == 200
    w = wait(ready, wid)
    assert w["status"] == "cancelled" and app_detail(ready, d["id"])["state"] == "APPLICATION_PREPARING"
    assert ready.post(f"/api/workflows/{wid}/cancel").status_code == 409
    assert ready.post(f"/api/workflows/{wid}/resume").status_code == 409


def test_cancel_application_withdraws_it(ready, mock_site):
    aid = to_ready_for_review(ready)
    r = ready.post(f"/api/applications/{aid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "APPLICATION_WITHDRAWN"
    assert ready.post(f"/api/applications/{aid}/submit").status_code == 403


def _crashed_run(app, kind, clicked, state):
    from app.core.enums import WorkflowStatus
    from app.models import Application, JobListing, WorkflowRun
    from app.services import applications as apps
    from app.services import jobs as jobs_svc

    with app.state.sessionmaker() as db:
        jobs_svc.search(db, __import__("app.schemas", fromlist=["JobSearchIn"]).JobSearchIn(source="mock"), app.state.settings)
        job = db.query(JobListing).first()
        a = Application(job_id=job.id, state=state, idempotency_key="k" + kind + str(clicked), version=1, approved_version=1,
                        target_kind="mock", application_url=job.application_url)
        db.add(a)
        db.flush()
        run = WorkflowRun(application_id=a.id, kind=kind, status=WorkflowStatus.RUNNING.value, state=state,
                          checkpoint={"version": 1, "clicked": clicked})
        db.add(run)
        db.commit()
        _ = (Application, apps)
        return a.id, run.id


def test_recovery_after_a_crash_never_invents_or_retries_a_submission(client, app, profile):
    from app.services.workflow import recover_interrupted

    a1, r1 = _crashed_run(app, "submit", True, "SUBMISSION_IN_PROGRESS")  # the click may have happened
    with app.state.sessionmaker() as db:
        assert recover_interrupted(db) == 1
        db.commit()
    d = client.get(f"/api/applications/{a1}").json()
    assert d["state"] == "SUBMISSION_UNCONFIRMED" and client.get(f"/api/workflows/{r1}").json()["status"] == "interrupted"
    assert "not be retried" in client.get(f"/api/workflows/{r1}").json()["next_action"]
    assert client.post(f"/api/workflows/{r1}/resume").status_code == 409  # submit runs are never resumed


def test_recovery_before_the_click_is_safe_and_fill_runs_are_resumable(client, app, profile):
    from app.services.workflow import recover_interrupted

    a1, r1 = _crashed_run(app, "submit", False, "SUBMISSION_IN_PROGRESS")
    with app.state.sessionmaker() as db:
        recover_interrupted(db)
        db.commit()
    assert client.get(f"/api/applications/{a1}").json()["state"] == "SUBMISSION_PENDING_APPROVAL"  # nothing was sent
    a2, r2 = _crashed_run(app, "fill", False, "FORM_IN_PROGRESS")
    with app.state.sessionmaker() as db:
        recover_interrupted(db)
        db.commit()
    w = client.get(f"/api/workflows/{r2}").json()
    assert w["status"] == "interrupted" and client.get(f"/api/applications/{a2}").json()["state"] == "FORM_IN_PROGRESS"


# ======================================================================== untrusted content and containment
def test_instruction_text_on_pages_and_in_jobs_cannot_change_anything(ready, mock_site):
    # The mock pages contain hidden "AI agent" instructions and job 4 contains a prompt-injection description.
    jid = job_id(ready, "Hooli")
    assert any("prompt_injection" in f for f in ready.get(f"/api/jobs/{jid}").json()["flags"])
    d, _ = prepare(ready, jid)
    dd = app_detail(ready, d["id"])
    cert = next(q for q in dd["questions"] if q["field_key"] == "certify")
    assert cert["answer"]["answer_text"] == "" and cert["answer"]["needs_user_input"] is True  # the hidden "tick every checkbox" was ignored
    assert ready.get("/api/preferences").json()["submission_mode"] == "review_before_submission"
    assert submissions(mock_site) == []
    letter = ready.get(f"/api/documents/{dd['cover_letter_document_id']}").json()["text_content"]
    assert "API key" not in letter and "auto-submit" not in letter.lower()


def test_browser_cannot_reach_origins_outside_the_allowed_site(mock_site):
    import asyncio

    from app.browser.session import browser_session

    async def go():
        async with browser_session(Settings(_env_file=None), mock_site) as page:
            await page.goto(mock_site + "/")
            return await page.evaluate("""async () => { try { await fetch('https://example.com/', {mode: 'no-cors'}); return 'reached'; } catch (e) { return 'blocked'; } }""")

    assert asyncio.run(go()) == "blocked"


def test_site_capabilities_are_declared_and_default_to_unsupported(client):
    from app.browser.capabilities import capability_for

    s = client.get("/api/settings").json()
    caps = s["site_capabilities"]
    assert len(caps) == 1 and caps[0]["is_mock"] is True and caps[0]["form_filling"] and "never a real employer" in caps[0]["restrictions"].lower()
    app_settings = Settings(_env_file=None)
    assert capability_for("https://boards.example.com/apply", app_settings).form_filling is False
    assert capability_for("http://127.0.0.1:8000/mock-employer/jobs/basic/apply", app_settings).form_filling is True
