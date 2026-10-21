#!/usr/bin/env bash
# Runs every check: frontend lint/types/tests/build, then backend lint/types/tests (incl. real-browser tests).
# The frontend is built first because the UI end-to-end test drives the built app.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== frontend: lint, types, unit tests, build"
(cd frontend && npm run lint && npm run typecheck && npm test && npm run build)
echo "== backend: lint, types, tests"
(cd backend && .venv/bin/ruff check app tests && .venv/bin/mypy app && .venv/bin/pytest -W ignore)
echo "ALL CHECKS PASSED"
