from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        ai_provider="mock",
        mount_mock_employer=False,
        serve_frontend=False,
        _env_file=None,  # never read a developer's real .env during tests
    )


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


SYNTHETIC_PROFILE = {
    "legal_name": "Alex Example", "preferred_name": "Alex", "email": "alex@example.test", "phone": "+1 555 010 0000",
    "city": "Springfield", "country": "USA", "linkedin_url": "https://linkedin.example/in/alex-example",
    "github_url": "https://github.example/alex-example", "headline": "Backend engineer (synthetic test profile)",
    "summary": "Synthetic profile used only in tests.",
}


@pytest.fixture()
def profile(client):
    r = client.put("/api/profile", json=SYNTHETIC_PROFILE)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def candidate(client, profile):
    client.patch("/api/profile", json={"summary": "Backend engineer who enjoys reliable systems."})
    for s in ("Python", "SQL", "Docker", "Git"):
        client.post("/api/profile/skills", json={"name": s})
    client.post("/api/profile/experience", json={
        "employer": "Acme Corp", "title": "Software Engineer", "start_date": "2021-01", "is_current": True,
        "responsibilities": ["Maintained internal reporting tools", "Built REST APIs with Python and FastAPI"],
        "achievements": ["Reduced report generation time from 40 to 12 minutes"], "technologies": ["Python", "FastAPI"]})
    client.post("/api/profile/projects", json={"name": "Job Tracker", "summary": "A command-line tool to track job applications",
                                                "contribution": "Sole developer", "technologies": ["Python", "SQLite"]})
    client.post("/api/profile/education", json={"institution": "State University", "degree": "B.Sc", "major": "Computer Science",
                                                  "start_date": "2015", "end_date": "2019"})
    return client


@pytest.fixture()
def job_id(candidate):
    return candidate.post("/api/jobs/search", json={"source": "mock", "query": "backend"}).json()["items"][0]["id"]
