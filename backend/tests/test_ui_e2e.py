"""Drives the REAL built UI in Chromium against the REAL backend + local mock employer. Skipped if frontend/dist is not built."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.config import BACKEND_DIR, Settings
from app.main import create_app

DIST = BACKEND_DIR.parent / "frontend" / "dist"
AXE = BACKEND_DIR.parent / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
pytestmark = [pytest.mark.browser, pytest.mark.skipif(not (DIST / "index.html").exists() or not AXE.exists(), reason="build the frontend first: cd frontend && npm install && npm run build")]


@pytest.fixture(scope="module")
def ui(tmp_path_factory):
    from playwright.sync_api import sync_playwright

    tmp = tmp_path_factory.mktemp("ui")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    base = f"http://127.0.0.1:{port}"
    settings = Settings(database_url=f"sqlite:///{tmp / 'ui.db'}", upload_dir=tmp / "uploads", ai_provider="mock", mount_mock_employer=True, serve_frontend=True,
                        frontend_dist=DIST, mock_employer_base_url=f"{base}/mock-employer", browser_headless=True, _env_file=None)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield base, browser
        browser.close()
    server.should_exit = True
    t.join(timeout=5)


def seed(base):
    c = httpx.Client(base_url=base + "/api", timeout=30)
    c.patch("/profile", json={"legal_name": "Alex Example", "email": "alex@example.test", "phone": "+1 555 010 0000", "city": "Springfield", "country": "USA",
                              "linkedin_url": "https://linkedin.example/in/alex", "requires_sponsorship": False, "summary": "Backend engineer."}).raise_for_status()
    for s in ("Python", "SQL", "Docker", "Git"):
        c.post("/profile/skills", json={"name": s}).raise_for_status()
    c.post("/profile/experience", json={"employer": "Acme Corp", "title": "Software Engineer", "start_date": "2021-01", "is_current": True,
                                        "responsibilities": ["Built REST APIs with Python and FastAPI"], "technologies": ["Python", "FastAPI"]}).raise_for_status()
    c.post("/profile/projects", json={"name": "Job Tracker", "summary": "A command-line tool to track job applications", "technologies": ["Python"]}).raise_for_status()
    c.post("/profile/education", json={"institution": "State University", "degree": "B.Sc", "major": "Computer Science", "start_date": "2015", "end_date": "2019"}).raise_for_status()
    return c


def axe_violations(page):
    page.add_script_tag(path=str(AXE))
    res = page.evaluate("async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } })).violations")
    return [v for v in res if v["impact"] in ("critical", "serious")]


def test_full_journey_through_the_ui_and_accessibility(ui):
    from playwright.sync_api import expect

    expect.set_options(timeout=60_000)  # real browser runs take seconds
    base, browser = ui
    seed(base)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("dialog", lambda d: d.accept())
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.set_default_timeout(60_000)

    # dashboard + demo-mode honesty
    page.goto(base)
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_text("Demo mode.")).to_be_visible()
    assert axe_violations(page) == [], "dashboard accessibility"

    # search the mock source and open the Globex job
    page.get_by_role("link", name="Jobs", exact=True).click()
    page.get_by_role("button", name="Search").click()
    expect(page.get_by_text("8 new")).to_be_visible()
    assert axe_violations(page) == [], "jobs accessibility"
    page.get_by_role("row").filter(has_text="Globex (demo)").get_by_role("link").first.click()
    expect(page.get_by_role("heading", name="Backend Engineer")).to_be_visible()
    expect(page.get_by_text("Not scored (unknown")).to_be_visible()  # unknown components are shown, not hidden
    assert axe_violations(page) == [], "job detail accessibility"

    # prepare: the browser reads the form and stops because sensitive/legal answers are unknown
    page.get_by_role("button", name="Prepare application").click()
    expect(page.get_by_text("Your input needed")).to_be_visible()
    expect(page.get_by_text("Legal declaration: only you can answer")).to_be_visible()
    expect(page.get_by_text("Mock employer: not a real application")).to_be_visible()
    assert axe_violations(page) == [], "review accessibility"
    shot = Path(__import__("tempfile").gettempdir()) / "applypilot-review.png"
    page.screenshot(path=str(shot), full_page=True)

    page.get_by_role("combobox", name="Are you legally authorized").select_option("Yes")
    page.get_by_role("button", name="Save answer").click()
    expect(page.get_by_text("You approved this")).to_have_count(0)
    page.get_by_role("combobox", name="I certify that the information provided is true and accurate").select_option("Yes")
    page.get_by_role("button", name="Save answer").first.click()
    page.get_by_role("button", name="I have reviewed this: approve answer").click()  # the sponsorship answer came from the profile
    page.get_by_role("button", name="Check form in browser").click()
    expect(page.get_by_text("Ready for review").first).to_be_visible()
    expect(page.get_by_text("every value verified in the browser")).to_be_visible()

    assert httpx.get(base + "/mock-employer/__admin/submissions").json()["submissions"] == []  # nothing submitted yet
    submit = page.get_by_role("button", name="Submit", exact=True)
    expect(submit).to_be_disabled()  # blocked until approval
    page.get_by_role("button", name="Approve this version").click()
    expect(page.get_by_text("Approved, not submitted").first).to_be_visible()
    expect(submit).to_be_enabled()
    submit.click()
    expect(page.get_by_text("Confirmed by the site. Reference: MOCK-")).to_be_visible()
    expect(page.get_by_text("no real application was sent")).to_be_visible()
    subs = httpx.get(base + "/mock-employer/__admin/submissions").json()["submissions"]
    assert len(subs) == 1 and subs[0]["email"] == "alex@example.test"

    # tracker, settings, activity, profile, studio
    page.get_by_role("link", name="Applications", exact=True).click()
    expect(page.get_by_role("row").filter(has_text="Globex (demo)").get_by_text("Submitted")).to_be_visible()
    assert axe_violations(page) == [], "tracker accessibility"
    for name, heading in (("Settings", "Settings"), ("Activity", "Activity"), ("Profile", "Candidate profile"), ("Résumé studio", "Résumé studio")):
        page.get_by_role("link", name=name, exact=True).click()
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        assert axe_violations(page) == [], f"{name} accessibility"
    page.get_by_role("link", name="Settings", exact=True).click()
    expect(page.get_by_role("radio", name="Review before submission (default)")).to_be_checked()
    assert errors == [], errors
    page.close()


def test_keyboard_navigation_reaches_the_main_content(ui):
    base, browser = ui
    page = browser.new_page()
    page.goto(base)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent") == "Skip to content"
    page.keyboard.press("Enter")
    assert page.evaluate("location.hash") == "#main"
    page.close()


def test_spa_serving_is_safe(ui):
    base, _ = ui
    assert httpx.get(base + "/jobs/123").headers["content-type"].startswith("text/html")  # client-side routes fall back to the app
    assert httpx.get(base + "/api/nope").status_code == 404 and httpx.get(base + "/api/nope").headers["content-type"].startswith("application/json")
    assert httpx.get(base + "/..%2f..%2f.env").status_code in (200, 404) and b"DATABASE_URL" not in httpx.get(base + "/..%2f..%2f.env").content
    assert json.loads(httpx.get(base + "/api/health").text)["status"] == "ok"
