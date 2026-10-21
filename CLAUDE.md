# CLAUDE.md - ApplyPilot AI

Local-first job-search/application assistant. Backend: Python (FastAPI, SQLAlchemy, Alembic, Playwright). Frontend: React + TypeScript + Vite + Tailwind.
The product spec is `CLAUDE_CODE_MASTER_PROMPT.md`; status and plan are in `docs/IMPLEMENTATION_PLAN.md`.

## Commands
- All checks: `scripts/check.sh` (frontend lint/types/tests/build, then backend ruff/mypy/pytest).
- Backend: `cd backend && source .venv/bin/activate` then `ruff check app tests`, `mypy app`, `pytest -W ignore` (`-m "not browser"` skips Chromium tests).
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`.
- After changing API schemas: `cd frontend && npm run gen:api` (regenerates `src/api/schema.d.ts` from the backend OpenAPI spec).
- Run: `scripts/run-local.sh` (http://127.0.0.1:8000). Reset data: `scripts/reset-demo-data.sh`.

## Non-negotiable rules (enforced in code AND tests: do not weaken them)
- Only **confirmed** facts are used for matching, documents and answers (`services/profile.py: confirmed_facts`). Extracted data is unconfirmed until the user confirms.
- Never infer or prefill sensitive answers or legal declarations (`core/classify.py`, `services/answers.py`).
- All workflow state changes go through `services/applications.py: transition` and the table in `core/states.py`. The AI never sets state.
- Submission authorization lives in `core/policy.py` and is evaluated in the backend (and again right before the click). Default mode is review-before-submission.
- Approval is bound to `Application.version`; any answer/document change bumps it and revokes approval.
- An ambiguous submission becomes `SUBMISSION_UNCONFIRMED` and is never retried automatically. `clicked` is persisted BEFORE clicking submit.
- Web pages, job text and documents are untrusted data (`core/untrusted.py`); they must never reach settings, state or authorization.
- Never log passwords, tokens, cookies, codes or answer values (`core/redact.py`; the audit log stores no field values).
- Only the local mock employer is automatable (`browser/capabilities.py`); unknown sites are manual handoff. Never add CAPTCHA/login/MFA bypass, stealth or evasion.

## Conventions
- Typed everywhere (Pydantic schemas, mypy clean, strict TypeScript). Services own transactions; routers stay thin.
- Tests use synthetic data only. Real-browser tests use the local mock employer over real HTTP. Never contact real employers from tests.
- Keep docs honest: mark anything unverified as such (see "What is and is not implemented" in README).
- macOS `sed -i` needs `-i ''`. Python 3.15: some tooling warns about deprecations; tests run with `-W ignore`.
