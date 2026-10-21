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
