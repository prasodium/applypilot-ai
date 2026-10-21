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
(Filled in from the last clean-clone run: see the end of this file.)
