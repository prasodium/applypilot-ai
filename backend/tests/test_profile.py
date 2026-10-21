from __future__ import annotations

from sqlalchemy import create_engine, inspect

from tests.conftest import SYNTHETIC_PROFILE


def test_profile_created_empty_and_round_trips(client):
    r = client.get("/api/profile")
    assert r.status_code == 200 and r.json()["legal_name"] == ""
    r = client.put("/api/profile", json=SYNTHETIC_PROFILE)
    assert r.status_code == 200 and r.json()["email"] == "alex@example.test"
    assert client.get("/api/profile").json()["city"] == "Springfield"


def test_patch_changes_only_given_fields_and_rejects_unknown(client, profile):
    r = client.patch("/api/profile", json={"phone": "+1 555 010 9999"})
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+1 555 010 9999" and body["legal_name"] == "Alex Example"
    assert client.patch("/api/profile", json={"is_admin": True}).status_code == 422


def test_profile_validation(client):
    for bad in ({"email": "nope"}, {"phone": "abc"}, {"linkedin_url": "javascript:alert(1)"}, {"github_url": "ftp://x"}):
        r = client.patch("/api/profile", json=bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"


def test_sensitive_fields_are_optional_and_never_inferred(client, profile):
    p = client.get("/api/profile").json()
    assert p["work_authorization"] is None and p["requires_sponsorship"] is None and p["date_of_birth"] is None
    facts = {f["id"] for f in client.get("/api/profile/facts").json()}
    assert "personal:work_authorization" not in facts and "personal:requires_sponsorship" not in facts


def test_education_experience_dates_validated(client, profile):
    ok = client.post("/api/profile/education", json={"institution": "State University", "degree": "BSc", "major": "CS",
                                                     "start_date": "2019-09", "end_date": "2023-06"})
    assert ok.status_code == 201 and ok.json()["confirmed"] is True
    assert client.post("/api/profile/education", json={"institution": "X", "start_date": "2023", "end_date": "2019"}).status_code == 422
    assert client.post("/api/profile/education", json={"institution": "X", "start_date": "13/2020"}).status_code == 422
    assert client.post("/api/profile/experience", json={"employer": "Acme", "title": "Dev", "is_current": True,
                                                        "end_date": "2024"}).status_code == 422


def test_skill_uniqueness_case_insensitive(client, profile):
    assert client.post("/api/profile/skills", json={"name": "Python"}).status_code == 201
    r = client.post("/api/profile/skills", json={"name": "python"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_skill"


def test_crud_update_and_delete(client, profile):
    pid = client.post("/api/profile/projects", json={"name": "Tracker", "technologies": ["Python"]}).json()["id"]
    r = client.put(f"/api/profile/projects/{pid}", json={"name": "Tracker v2", "technologies": ["Python", "SQL"]})
    assert r.json()["name"] == "Tracker v2" and r.json()["technologies"] == ["Python", "SQL"]
    assert client.delete(f"/api/profile/projects/{pid}").status_code == 204
    assert client.delete(f"/api/profile/projects/{pid}").status_code == 404


def test_fact_provenance_unconfirmed_until_confirmed(client, app, profile):
    from app.core.enums import FactSource
    from app.schemas import SkillIn
    from app.services import profile as svc

    with app.state.sessionmaker() as db:  # simulate a resume-extracted, not-yet-confirmed skill
        s = svc.add_skill(db, SkillIn(name="Rust"), source=FactSource.RESUME_EXTRACTED_UNCONFIRMED, confirmed=False)
        db.commit()
        sid = s.id
    facts = {f["id"]: f for f in client.get("/api/profile/facts").json()}
    assert facts[f"skill:{sid}"]["confirmed"] is False
    assert facts[f"skill:{sid}"]["source"] == "resume_extracted_unconfirmed"
    with app.state.sessionmaker() as db:
        assert f"skill:{sid}" not in {f.id for f in svc.confirmed_facts(db)}  # generators/matchers never see it
    r = client.post(f"/api/profile/facts/skill:{sid}/confirm")
    assert r.status_code == 200 and r.json()["confirmed"] is True and r.json()["source"] == "user_confirmed"
    with app.state.sessionmaker() as db:
        assert f"skill:{sid}" in {f.id for f in svc.confirmed_facts(db)}
    assert client.post("/api/profile/facts/skill:99999/confirm").status_code == 404
    assert client.post("/api/profile/facts/bogus/confirm").status_code == 404


def test_editing_a_record_makes_it_user_entered(client, app, profile):
    from app.core.enums import FactSource
    from app.schemas import SkillIn
    from app.services import profile as svc

    with app.state.sessionmaker() as db:
        sid = svc.add_skill(db, SkillIn(name="Go"), source=FactSource.RESUME_EXTRACTED_UNCONFIRMED, confirmed=False).id
        db.commit()
    r = client.put(f"/api/profile/skills/{sid}", json={"name": "Go", "proficiency": "intermediate"})
    assert r.json()["confirmed"] is True and r.json()["source"] == "user_entered"


def test_preferences_defaults_are_conservative(client):
    p = client.get("/api/preferences").json()
    assert p["submission_mode"] == "review_before_submission"  # default must be review-before-submit
    assert p["max_applications_per_day"] == 5 and p["match_threshold"] == 60
    assert "mock" in p["allowed_sources"] and "arbeitnow" not in p["allowed_sources"]


def test_preferences_validation_and_audit(client):
    r = client.patch("/api/preferences", json={"match_threshold": 150})
    assert r.status_code == 422 and r.json()["error"]["details"]["errors"][0]["field"] == "match_threshold"
    assert client.patch("/api/preferences", json={"salary_min": 100, "salary_max": 50}).status_code == 422
    assert client.get("/api/preferences").json()["match_threshold"] == 60  # a rejected patch changes nothing
    r = client.patch("/api/preferences", json={"target_roles": ["Backend Engineer"], "salary_min": 50, "salary_max": 100})
    assert r.status_code == 200 and r.json()["target_roles"] == ["Backend Engineer"]
    assert client.patch("/api/preferences", json={"submission_mode": "yolo"}).status_code == 422


def test_export_contains_everything_then_delete_removes_everything(client, profile):
    client.post("/api/profile/skills", json={"name": "SQL"})
    client.post("/api/answer-library", json={"question_type": "start_date", "answer_text": "Two weeks after offer"})
    data = client.get("/api/data/export").json()
    assert data["format"] == "applypilot-export-v1"
    assert data["candidate_profiles"][0]["legal_name"] == "Alex Example"
    assert data["skills"][0]["name"] == "SQL" and data["approved_answers"][0]["answer_text"].startswith("Two weeks")

    assert client.delete("/api/data").status_code == 422  # needs explicit confirmation
    r = client.delete("/api/data?confirm=DELETE")
    assert r.status_code == 200 and r.json()["deleted"]["skills"] == 1
    after = client.get("/api/data/export").json()
    assert after["candidate_profiles"] == [] and after["skills"] == [] and after["approved_answers"] == []
    assert [a["event_type"] for a in after["audit_logs"]].count("data_deleted") == 1  # only an anonymous marker remains


def test_errors_never_leak_internals(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and "Traceback" not in r.text


def test_migration_creates_schema_matching_models(tmp_path):
    from sqlalchemy import select

    from app.config import Settings
    from app.main import init_db
    from app.models import ALL_MODELS

    url = f"sqlite:///{tmp_path / 'm.db'}"
    init_db(Settings(database_url=url, _env_file=None))
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {m.__tablename__ for m in ALL_MODELS} <= tables and "alembic_version" in tables
    _ = select
