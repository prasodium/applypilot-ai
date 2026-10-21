# ApplyPilot AI

A **local-first** job-search and application assistant. It imports your résumé, keeps a verified profile, discovers and scores jobs,
drafts tailored documents and answers from facts you have confirmed, fills application forms in a real browser, and tracks what actually
happened, **without ever claiming a submission it could not verify**.

> **Status: working MVP, demo-grade integrations.** Everything runs on your machine in *demo mode* out of the box (mock AI, synthetic jobs,
> and a local **mock employer** website). **No real job application is ever submitted by this version.** Real sites are handled as a manual
> handoff. See [What is and is not implemented](#what-is-and-is-not-implemented).

## What it does

| Step | What happens | Safety rule enforced in code |
|---|---|---|
| Profile | You enter or import facts (education, experience, skills, projects, preferences). | Résumé-extracted data stays **unconfirmed** until you confirm it; only confirmed facts are ever used. |
| Résumé | Upload PDF/DOCX, review the parsed preview, confirm. Generate a master and per-job tailored résumé and cover letter. | Drafts cite the profile facts behind every claim; nothing is invented; drafts stay drafts until you approve them. |
| Jobs | Import a URL or pasted text, or search a source. Duplicates are detected; every job keeps its source URL and retrieval time. | robots.txt respected, private networks and login pages refused, job text treated as untrusted data. |
| Match | A 0-100 score with a per-component breakdown, unknowns excluded and weights renormalized. | Not a hiring prediction, and says so. |
| Answers | Form questions are classified and answered from confirmed facts, with confidence and sources. | Sensitive questions (work authorization, sponsorship, demographics, health, criminal history) are never inferred; legal declarations are never pre-filled. |
| Browser | Playwright fills the form, **reads every value back**, checkpoints each step and stops at the final step. | CAPTCHA, login, MFA and email verification **pause the workflow for you**; nothing is bypassed. Traffic is limited to the allowed site. |
| Review | You see every answer, its sources, confidence and warnings, plus the documents. | Approval is bound to the **exact version**; any later edit revokes it. |
| Bot | An optional scheduled bot (off by default) searches, scores, prepares drafts and fills forms, then stops for you. | It uses the same services and policy as manual actions and **never submits** unless you chose *Authorized auto-submit* and every check passes. |
| Submit | Backend policy engine checks mode, approval, completeness, limits, duplicates, site support. | Default mode is *Review before submission*. Ambiguous results become `SUBMISSION_UNCONFIRMED` and are **never retried automatically**. |

## Requirements

* macOS (developed and tested on Apple Silicon). Linux should work; Windows is untested.
* **Python 3.11 or newer** (tested on 3.15.0) and **Node.js 20 or newer** (tested on 26) with npm.
* ~300 MB for the Playwright Chromium download. No Docker, database server or cloud account is needed.
* No paid API key is needed. An optional OpenAI-compatible key enables a real AI provider (see [Configuration](#configuration)).

## Setup

All commands are run from the repository root. They were run from a clean clone to verify them.

```bash
# 1) Backend: virtual environment, dependencies, browser
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# 2) Configuration (optional: defaults already work for the demo)
cp ../.env.example .env

# 3) Database migrations (also applied automatically on start)
alembic upgrade head

# 4) Frontend: dependencies and production build
cd ../frontend
npm install
npm run build
cd ..
```

## Run

**One command (API + UI + local mock employer on http://127.0.0.1:8000):**

```bash
scripts/run-local.sh
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/api/docs.

**Development with hot reload** (two terminals):

```bash
# terminal 1: backend
cd backend && source .venv/bin/activate
python -m uvicorn app.main:app_factory --factory --reload --host 127.0.0.1 --port 8000

# terminal 2: frontend (proxies /api to the backend) on http://localhost:5173
cd frontend && npm run dev
```

Set `BROWSER_HEADLESS=false` in `backend/.env` to watch the browser fill forms.

## Try the demo (5 minutes)

1. **Profile**: add your name, email, a few skills and one experience (use made-up data), or upload a résumé in **Résumé studio** and *confirm* the parse.
2. **Jobs**: press **Search** on the *Mock jobs* source (synthetic, labelled DEMO). Open a job to see the match breakdown.
3. **Prepare application**: the browser reads the local mock form and stops because sensitive and legal answers are unknown.
4. Answer them yourself, approve the sponsorship answer, press **Check form in browser**, then **Approve this version** and **Submit**.
5. The mock site shows a reference number, ApplyPilot verifies it from the page, and the tracker shows *Submitted* with a note that it was the mock employer.

Try the other mock forms (job list) to see: a multi-step form, a human-verification pause, an expired session, and an **ambiguous** result that becomes *Result unconfirmed*.

## Test, lint and type-check

```bash
scripts/check.sh                 # everything below, in order

# or individually
cd backend && source .venv/bin/activate
ruff check app tests             # lint
mypy app                         # types
pytest -W ignore                 # unit, integration and real-browser tests (~1 minute)
pytest -W ignore -m "not browser"   # fast subset without launching Chromium

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build
```

Last verified run: see [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md#verification-record).

## Reset demo data

```bash
scripts/reset-demo-data.sh       # asks you to type RESET, then deletes backend/data/ (database + uploads) only
```

Or use **Settings → Your data → Delete all my data** in the UI (also exports everything first if you want: *Export everything (JSON)*).

## Configuration

Settings come from environment variables or `backend/.env` ([.env.example](.env.example) lists them all). The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `mock` | `mock` (deterministic, labelled DEMO) or `openai_compatible` |
| `AI_MODEL`, `AI_API_KEY`, `AI_BASE_URL` | empty / empty / OpenAI URL | for `openai_compatible`. The key is never returned by the API or logged. |
| `DATABASE_URL` | `sqlite:///.../backend/data/applypilot.db` | SQLite file |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | `backend/data/uploads`, `10` | private upload storage and size limit |
| `BROWSER_HEADLESS` | `true` | `false` shows the browser |
| `MOUNT_MOCK_EMPLOYER` | `true` | serves the local test site; never mounted when `APP_ENV=production` |
| `SERVE_FRONTEND` | `true` | serve `frontend/dist` from the backend |

## What is and is not implemented

Implemented and covered by automated tests:

* Profile CRUD with fact provenance, preferences, approved-answer library, data export and deletion.
* Résumé upload (PDF/DOCX) with strict validation, parse preview, apply/confirm, master and tailored résumés, cover letters, versions, diffs, DOCX/PDF/TXT download.
* Job import (URL with robots/SSRF protection, pasted text/HTML, JSON-LD), mock source, **Arbeitnow** public-API adapter (read-only, off by default), duplicate detection, filters, explainable match score, shortlist.
* Question classification and grounded answer engine; sensitive/legal handling; limits; prompt-injection defences; provider-independent AI interface with a deterministic mock and an OpenAI-compatible client.
* Central state machine, backend submission policy, version-bound approval, idempotent submission, `SUBMISSION_UNCONFIRMED`, user-attested resolution, audit log, notifications, pause/resume/cancel, crash recovery.
* Playwright automation against the local mock employer (basic, validation, multi-step, expired session, human verification, ambiguous and confirmed results).
* Scheduled background bot (off by default; in-process scheduler, runs while the app is open): discover, score, prepare, fill, then stop for review; auto-submit only in the user's explicit mode and through the same policy. Verified against the mock source and mock employer only.
* React UI for every page in the specification, keyboard accessible; axe-core finds no serious or critical issues on the pages scanned.

**Not implemented, and not claimed:**

* **Real employer sites.** Only the local mock site has form filling and submission enabled. Every other site is a **manual handoff**: documents are prepared, you apply yourself and record the result (stored as "reported by you").
* Login, account creation, email/MFA/CAPTCHA handling: the workflow *pauses* for you; there is no automation of these and no credential storage at all.
* A real AI provider has **not** been exercised against a live service (no key was available): it is tested with a mocked transport only.
* PostgreSQL, Docker, Kanban view, screenshots as evidence, system notifications (notifications are in-app), multi-user accounts.
* Résumé parsing is heuristic, English-oriented, and cannot read scanned images.

See [docs/SECURITY.md](docs/SECURITY.md), [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details and the user-facing [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Executable doesn't exist ... chromium` / "Is Chromium installed?" | `cd backend && source .venv/bin/activate && playwright install chromium` |
| The page says "Cannot reach the ApplyPilot backend" | Start the backend (`scripts/run-local.sh`); in dev the UI proxies `/api` to port 8000. |
| Port 8000 is in use | `APP_PORT=8010 scripts/run-local.sh` (also set `MOCK_EMPLOYER_BASE_URL` to the same port). |
| Blank page after `scripts/run-local.sh` | Build the UI: `cd frontend && npm install && npm run build`. |
| An application sits in "Your input needed" | Open it: the highlighted questions need *your* answer (sensitive and legal questions are never guessed). |
| Match score is 0 or low | Only **confirmed** facts count. Confirm your skills/experience on the Profile page. |
| "Result unconfirmed" | The page did not clearly confirm. Check the employer's site or email, then record the outcome. It is never retried automatically. |
| Tests that need Chromium are skipped/fail | Run `playwright install chromium`; the UI end-to-end test also needs `npm run build`. |
| `pip install` fails | Upgrade pip first (`pip install -U pip`). Installation was verified on Python 3.15 only; 3.11+ is declared but untested. |

## Repository layout

```
backend/            FastAPI app (app/), Alembic migrations, tests (tests/)
  app/core/         pure logic: state machine, policy, classifier, grounding, redaction, untrusted-text handling
  app/services/     profile, documents, resume parser, jobs, matching, answers, applications, workflow runner
  app/browser/      site capabilities, page analysis, form filler, locked-down browser session
  app/jobsources/   job source adapters (mock, arbeitnow) + registry
  app/mock_employer local test website (a fixture, never a real employer)
frontend/           React + TypeScript + Vite + Tailwind UI (typed client generated from the OpenAPI spec)
docs/               plan, architecture, security, integrations, user guide
scripts/            check.sh, run-local.sh, reset-demo-data.sh
```
