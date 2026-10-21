# ApplyPilot AI - Implementation plan

Status legend: [ ] not started, [~] in progress, [x] done and tested. This file is updated as phases finish; the
"Verified" lines record what was actually run.

## Findings from inspection (Step A)
- The folder contained only `CLAUDE_CODE_MASTER_PROMPT.md` and was not a Git repository; `git init` was run (local only, nothing pushed).
- Toolchain on the dev machine: macOS (Apple Silicon), Python 3.15.0, Node 26, npm 11. No Docker, uv or pnpm assumed.
- All backend dependencies install with wheels on Python 3.15 (FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PyMuPDF, python-docx, Playwright).
- Chromium is installed with `playwright install chromium`; no system Chrome is required.
- No conflicts with the master prompt were found.

## Assumptions and conservative defaults
- **Single local user.** The app is local-first and binds to 127.0.0.1; there is no application login, so the optional `users`
  table is not created. Multi-user isolation tests from the prompt are therefore not applicable and this is documented in SECURITY.md.
- Submission mode defaults to **Review before submission**. Auto-submit exists but is off and needs several explicit conditions.
- Only the local **mock employer** is a site where form filling and submission are enabled. Every other site is treated as
  "manual handoff" until an integration declares its capabilities.
- AI defaults to a deterministic **mock provider** (output labelled DEMO). A generic OpenAI-compatible provider exists but is unverified without a key.
- Real job source: **Arbeitnow public API** (search only, user-enabled, off by default). Its published terms are silent on rate limits and
  attribution, so the adapter caches, makes at most one request per search, attributes the source and never applies automatically.

## Architecture in one paragraph
FastAPI + SQLAlchemy (SQLite) backend with pure, unit-tested core modules (`states`, `policy`, `matching`, `answers`, `redact`, `untrusted`),
service modules that own transactions, thin API routers, an async Playwright automation package, and a local mock employer site for
browser tests. A React + TypeScript + Vite + Tailwind frontend talks to the typed API. See `docs/ARCHITECTURE.md`.

## Phases and status

Legend: **[x] done and tested**, [~] partly done, [ ] not done. "Tested" means an automated test in this repository passes; see the verification record below.

### Phase 1 - Foundation and profile: [x]
Config, DB + Alembic migrations (0001 schema, 0002 `filled_version`; `alembic check` clean), profile/education/experience/skills/projects CRUD, preferences, fact provenance (extracted data stays unconfirmed), approved-answer library, export, deletion, dashboard and navigation.

### Phase 2 - Résumé and documents: [x]
PDF/DOCX upload with extension/MIME/magic/size/encryption/zip-bomb checks, heuristic parser with correction preview, apply/confirm, master and tailored résumés and cover letters with claim provenance, versions, diff, DOCX/PDF/TXT download, approval, deterministic DEMO labelling.

### Phase 3 - Job discovery and matching: [x]
Manual URL (robots, SSRF, login-wall refusal) and pasted-text import with JSON-LD parsing, mock source, Arbeitnow adapter (verified live once), duplicate detection, filters, explainable weighted match with unknowns excluded, shortlist, stale-match detection.

### Phase 4 - AI answer engine: [x]
Classifier with sensitive/legal categories first, grounded answers from confirmed facts and the approved library, limits, missing-information detection, review rules, injection defences, validated structured output, provider interface (mock + OpenAI-compatible, the latter only with a mocked transport).

### Phase 5 - Browser automation: [x] (mock employer only)
Local mock employer (six variants), Playwright manager with origin guard, field detection with semantic mapping, text/select/radio/checkbox/file/textarea handling, read-back verification, validation-error detection, per-action checkpoints, challenge pause.

### Phase 6 - Review, authorization, submission: [x] (mock employer only)
Central state machine, backend policy, version-bound approval, compare-and-set idempotent submission, outcome verification, `SUBMISSION_UNCONFIRMED`, user attestation, audit log, in-app notifications, tracker, pause/resume/cancel, crash recovery.

### Phase 7 - Hardening, UI, docs: [~]
Done: React UI for every specified page, keyboard and axe-core checks, security review with a CSRF/DNS-rebinding fix, documentation, clean-clone verification.
Not done: PostgreSQL profile and Docker (optional in the spec), dependency vulnerability audit, Kanban view, VoiceOver/manual screen-reader testing, responsive layout checked only by construction (not on a phone), real-site integrations.

## Verification record

**2026-10-21, macOS on Apple Silicon, Python 3.15.0, Node 26.11.1, Playwright Chromium (headless).**
The project was cloned fresh from Git and set up by following the README commands exactly (venv, `pip install -e ".[dev]"`, `playwright install chromium`, `cp .env.example .env`, `alembic upgrade head`, `npm install`, `npm run build`), then started with `scripts/run-local.sh`.

| Check | Result |
|---|---|
| `alembic upgrade head` on a fresh checkout | passes (**the first clean-clone attempt failed here** because `data/` did not exist; fixed in `alembic/env.py` and covered by a regression test) |
| Live server from `run-local.sh` | `/api/health` ok, UI served, mock employer served, API docs served, mock search created 8 jobs |
| `ruff check app tests` / `mypy app` | clean (56 source files) |
| Backend `pytest` (unit, integration, real-browser, UI end-to-end) | **224 passed** in ~86 s |
| Frontend `eslint`, `tsc`, `vitest`, `vite build` | clean, **15 passed**, build ok (101 kB gzipped JS) |
| axe-core (WCAG 2.0 A/AA) on dashboard, jobs, job detail, application review, tracker, settings, bot, activity, profile, résumé studio | no critical or serious violations |
| Secret scan of tracked files | only intentionally fake strings in tests; no `.env`, database or uploads tracked |

Bugs found by this verification work and fixed along the way (each has a regression test): stale relationship caches producing an incomplete master résumé; mock AI answering unrelated questions from job skills; yes/no skill questions classified as essays; auto-submit state not flushed before the compare-and-set; pause/cancel ignored while waiting for input; an unused state-machine edge that could skip approval; log redaction only covering existing handlers; **cross-site POSTs could reach no-body endpoints such as submit (CSRF guard and Host check added)**; the mock employer ignoring its mount prefix; Arbeitnow remote listings reported as "unknown".

**Not verified** (not claimed): behaviour on Linux/Windows or Python/Node versions other than the above; a real AI provider; any real employer site; screen-reader testing by a human; responsive layout on a phone; dependency vulnerability scans; PostgreSQL.

## Next phase
1. Add a real, permitted integration path for one application site with its own fixture, login/verification pausing and `last_tested` date.
2. Run `npm audit` / `pip-audit`, and add an automatic retention purge.
3. Exercise the OpenAI-compatible provider against a live endpoint with a real key.
4. Optional: Kanban view, PostgreSQL profile, Docker.
