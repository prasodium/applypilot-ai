# Architecture

```
React UI (frontend/)  --typed client generated from OpenAPI-->  FastAPI (backend/app/api/*)
                                                                    |
              +-----------------------+-----------------------------+----------------------+
              |                       |                             |                      |
        services/profile        services/documents          services/jobs           services/applications
        (facts, prefs)          (upload, parse, drafts)     (import, search,        (prepare, edit, approve,
              |                  resume_parser               match, dedupe)          policy, submit, attest)
              |                       |                       jobsources/ + urlfetch        |
              +------- core/ (pure): enums, states, policy, classify, grounding, redact, untrusted -------+
                                                                                           |
                                              services/workflow (runner, recovery) ---- browser/ (Playwright)
                                                                                           |
                                                                       mock_employer (local test site, real HTTP)
SQLite (SQLAlchemy 2.0 + Alembic)   AI provider interface (mock | OpenAI-compatible)
```

## Layers
* **core/** is pure and dependency-free: the state machine (`states.py`), submission policy (`policy.py`), question classifier (`classify.py`), grounding checks, redaction and untrusted-text handling. These carry most safety rules and are unit-tested directly.
* **services/** own transactions and business logic. Routers (`api/`) only validate input, call services and shape output. One DB transaction per request (`get_db`); background runs use short transactions of their own.
* **browser/** is isolated: `capabilities.py` (which sites may be automated), `pages.py` (DOM extraction, challenge and outcome detection), `filler.py` (fill with read-back), `session.py` (headless Chromium, ephemeral profile, network guard).
* **ai/** exposes `generate(task, payload, schema)`. Untrusted text goes in `payload["untrusted"]` and is delimited for real providers. Output is validated by Pydantic and by grounding checks before use. A model can never execute commands, SQL or browser actions.

## Data model (21 tables)
Profile: `candidate_profiles`, `education_records`, `work_experiences`, `skills`, `candidate_projects` (each record carries `source` and `confirmed`), `approved_answers`, `user_preferences`.
Documents: `candidate_documents` (uploads, master, tailored résumé, cover letter; versions via `parent_id`; `claims` hold provenance).
Jobs: `job_listings` (unique `dedupe_key`), `job_matches`, `job_source_integrations`, `platform_accounts` (metadata only; no secrets).
Applications: `applications` (state, `version`, `approved_version`, `filled_version`, unique `idempotency_key`), `application_questions`, `application_answers`.
Workflow/audit: `workflow_runs` (checkpoint JSON, pause/cancel flags), `workflow_events`, `audit_logs`, `notifications`.
There is no `users` table: the app is single-user and local. Models avoid SQLite-specific features so PostgreSQL could be adopted later (not implemented or tested).

## Application workflow
```
APPLICATION_PREPARING -> FORM_IN_PROGRESS -> PROFILE_INFORMATION_REQUIRED <-> FORM_IN_PROGRESS
        ... -> READY_FOR_REVIEW -> SUBMISSION_PENDING_APPROVAL -> SUBMISSION_IN_PROGRESS -> SUBMITTED
                                                                                          -> SUBMISSION_UNCONFIRMED  (no auto retry)
                                                                                          -> FORM_VALIDATION_FAILED / HUMAN_VERIFICATION_REQUIRED / LOGIN_REQUIRED
```
* `prepare` creates the application, tailored résumé and cover letter, and (for the mock site) a **fill run**. The fill run walks the form step by step, drafts an answer for each new field from confirmed facts, and stops at the first required answer it may not supply. It never clicks submit.
* The user edits answers (each edit bumps `version` and revokes approval), re-runs the fill (which sets `filled_version`), then approves that exact version.
* `submit` runs `core/policy.evaluate_submission`, does a compare-and-set into `SUBMISSION_IN_PROGRESS`, and starts a submit run. The run re-fills in a fresh browser, **re-checks the policy from the database**, persists `clicked=true`, clicks once, and classifies the page. Success needs a success phrase **and** a confirmation reference.
* On startup `recover_interrupted` marks in-flight runs `interrupted`; a submit that might have clicked becomes `SUBMISSION_UNCONFIRMED`, one that had not becomes pending approval again.
* Resume of a paused fill re-opens the form and re-fills from the start (idempotent); it does not continue mid-page.

## Scheduled bot
`services/bot.py` runs discover -> select -> prepare (+ browser fill) -> optional policy-gated submit, recording a `bot_runs` row, an audit entry and a notification. `BotScheduler` (started from the app lifespan) wakes every `bot_tick_seconds`, and runs only if `bot_config.enabled` and the interval has elapsed (`is_due`). An `asyncio.Lock` allows one run at a time. The bot calls the same services as the UI (`jobs.search`, `applications.prepare`, `begin_submit`) so limits, policy and the state machine apply unchanged; it has no path to settings or approvals. Tables: `bot_config`, `bot_runs` (21 total).

## Frontend
React 19, React Router, Tailwind 4. `src/api/schema.d.ts` is generated from the backend OpenAPI spec (`npm run gen:api`), so UI and API types cannot drift silently. State is shown as text plus a symbol, never colour alone. Pages: Dashboard, Profile, Résumé studio, Jobs, Job detail, Applications (tracker), Application review, Settings, Bot, Activity.
