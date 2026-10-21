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

## Phases and acceptance criteria

### Phase 1 - Foundation and profile
Scope: repo setup, config, DB + Alembic migration, profile/education/experience/skills/projects CRUD, preferences, fact provenance, export, delete.
Acceptance: profile round-trips through the API; extracted facts stay unconfirmed until confirmed; export contains all data; delete removes everything; migration applies on a clean DB.

### Phase 2 - Documents
Scope: PDF/DOCX upload with extension/MIME/size/magic checks, text extraction, heuristic structured parse, parse preview and apply/confirm, master resume, tailored resume and cover-letter drafts with claim provenance, versions, DOCX/PDF download.
Acceptance: malformed or oversized files are rejected safely; drafts only contain confirmed facts; every generated claim lists its source facts; drafts start unapproved.

### Phase 3 - Jobs and matching
Scope: `JobSourceAdapter` interface with capability declarations, manual URL/text import (robots-aware fetch, SSRF guard, JSON-LD parsing), mock source, Arbeitnow adapter, duplicate detection, filters, explainable match score, shortlist.
Acceptance: score has per-component breakdown with unknowns excluded and weights normalized; duplicates are detected; every job has source URL and retrieval time.

### Phase 4 - Answer engine
Scope: question classifier, grounded answers from confirmed facts and the approved-answer library, limits, missing-info detection, sensitive/legal handling, prompt-injection defenses, validated structured output.
Acceptance: sensitive and legal questions never get unattended answers; unknown facts are never filled; numbers not in the facts are rejected; injection text cannot alter settings.

### Phase 5 - Browser automation
Scope: mock employer site (basic, multi-step, validation errors, expired session, human verification, ambiguous and confirmed results), Playwright manager, field detection and semantic mapping, per-action checkpoints, challenge handoff.
Acceptance: Playwright fills the mock form and reads values back; required-field validation errors are detected; challenges pause the workflow and are never bypassed.

### Phase 6 - Review, authorization, submission
Scope: central state machine, policy engine, approval bound to application version, idempotent submission, outcome verification, `SUBMISSION_UNCONFIRMED`, audit log, notifications, tracker.
Acceptance: all safety tests listed in section 18 of the master prompt pass.

### Phase 7 - Frontend, hardening, docs
Scope: React UI for all pages, accessibility and responsive layout, frontend checks, security review, README/USER_GUIDE/INTEGRATIONS/SECURITY, clean-install verification.
Acceptance: setup commands in the README work from a clean checkout; backend tests, type check, frontend build and browser tests pass.

## Risks
| Risk | Mitigation |
|---|---|
| Heuristic resume parsing is imperfect | Always show a parse preview; nothing becomes a verified fact without user confirmation |
| Real sites change or forbid automation | Capability registry defaults to manual handoff; only the mock site is automated |
| LLM output may be wrong or injected | Treat as untrusted; validate with Pydantic; grounding checks; sensitive/legal answers need the user |
| Ambiguous submission results | `SUBMISSION_UNCONFIRMED`, no auto-retry, user-attested resolution only |
| Python 3.15 is very new | Dependencies pinned loosely and verified; `requires-python >= 3.11` so older versions also work |

## First vertical slice (Step D) task list
1. Profile create/read/update. 2. Resume upload and parse preview. 3. Manual job import + mock source. 4. Explainable match.
5. Grounded answer drafts with mock AI. 6. Application preparation and review. 7. Playwright fills the mock employer form.
8. Workflow checkpoints and tracker.
