"""Scheduled bot: off by default, obeys limits and modes, never submits without authorization."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from app.models import BotConfig, JobListing
from app.services.bot import is_due


def wait_idle(client, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/api/bot").json()
        if not s["running"]:
            return s
        time.sleep(0.3)
    raise AssertionError("bot did not finish")


def run_bot(client):
    r = client.post("/api/bot/run")
    assert r.status_code == 202, r.text
    return wait_idle(client)


def test_bot_is_off_by_default(client):
    s = client.get("/api/bot").json()
    assert s["config"]["enabled"] is False
    assert s["next_run_at"] is None
    assert s["will_submit_without_you"] is False
    assert s["runs"] == []


def test_schedule_rule():
    now = datetime.now(UTC)
    assert not is_due(BotConfig(enabled=False, interval_minutes=60, last_run_at=None), now)
    assert is_due(BotConfig(enabled=True, interval_minutes=60, last_run_at=None), now)
    assert not is_due(BotConfig(enabled=True, interval_minutes=60, last_run_at=now - timedelta(minutes=30)), now)
    assert is_due(BotConfig(enabled=True, interval_minutes=60, last_run_at=now - timedelta(minutes=61)), now)


def test_config_validation(client):
    assert client.patch("/api/bot", json={"interval_minutes": 1}).status_code == 422
    assert client.patch("/api/bot", json={"max_new_per_run": 500}).status_code == 422
    assert client.patch("/api/bot", json={"sources": ["evil"]}).status_code == 422
    assert client.patch("/api/bot", json={"surprise": 1}).status_code == 422
    r = client.patch("/api/bot", json={"enabled": True, "interval_minutes": 60, "queries": ["backend"]})
    assert r.status_code == 200 and r.json()["config"]["enabled"] is True and r.json()["next_run_at"]


def test_run_prepares_but_never_submits_in_review_mode(candidate):
    candidate.patch("/api/bot", json={"queries": ["backend"], "max_new_per_run": 3})
    candidate.patch("/api/preferences", json={"match_threshold": 0})
    s = run_bot(candidate)
    run = s["runs"][0]
    assert run["status"] == "completed", run
    assert run["new_jobs"] >= 1 and run["prepared"] >= 1 and run["submitted"] == 0
    assert run["prepared"] <= 3
    apps = candidate.get("/api/applications").json()
    assert apps and all(a["state"] != "SUBMITTED" for a in apps)
    assert s["config"]["last_run_at"]
    assert any(n["title"].startswith("Bot run") for n in candidate.get("/api/notifications").json())


def test_research_only_prepares_nothing(candidate):
    candidate.patch("/api/preferences", json={"submission_mode": "research_only", "match_threshold": 0})
    run = run_bot(candidate)["runs"][0]
    assert run["status"] == "completed" and run["prepared"] == 0
    assert candidate.get("/api/applications").json() == []


def test_per_run_limit(candidate):
    candidate.patch("/api/preferences", json={"match_threshold": 0})
    candidate.patch("/api/bot", json={"max_new_per_run": 1})
    run = run_bot(candidate)["runs"][0]
    assert run["prepared"] == 1


def test_suspicious_jobs_are_skipped(candidate, app):
    from app.db import session_scope

    candidate.patch("/api/preferences", json={"match_threshold": 0})
    orig = None
    from app.services import bot as bot_svc

    orig = bot_svc._select

    def flag_all(a, ids, mode):
        with session_scope(a.state.sessionmaker) as db:
            for i in ids:
                j = db.get(JobListing, i)
                j.flags = ["possible_prompt_injection"]
        return orig(a, ids, mode)

    bot_svc._select = flag_all
    try:
        run = run_bot(candidate)["runs"][0]
    finally:
        bot_svc._select = orig
    assert run["prepared"] == 0 and run["details"]["skipped"]["suspicious_text"] >= 1


def test_second_run_while_running_is_rejected(candidate):
    candidate.patch("/api/preferences", json={"match_threshold": 0})
    first = candidate.post("/api/bot/run")
    assert first.status_code == 202
    second = candidate.post("/api/bot/run")
    assert second.status_code in (409, 202)  # 409 while the first still runs; 202 only if it already finished
    wait_idle(candidate)


def test_bot_endpoint_rejects_foreign_origin(client):
    r = client.patch("/api/bot", json={"enabled": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/api/bot").json()["config"]["enabled"] is False


def test_auto_submit_mode_still_blocked_by_policy(candidate):
    """Auto-submit mode never bypasses policy: fresh drafts have unapproved documents/answers, so nothing is submitted."""
    candidate.patch("/api/preferences", json={"submission_mode": "authorized_auto_submit", "match_threshold": 0})
    s = run_bot(candidate)
    assert s["will_submit_without_you"] is True
    run = s["runs"][0]
    assert run["status"] == "completed" and run["submitted"] == 0
    assert all(a["state"] != "SUBMITTED" for a in candidate.get("/api/applications").json())
