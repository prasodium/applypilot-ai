#!/usr/bin/env bash
# Starts ApplyPilot AI on http://127.0.0.1:8000 (API + built UI + local mock employer). Builds the UI first if needed.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x backend/.venv/bin/python ] || { echo "Create the backend virtualenv first (see README, section 'Setup')."; exit 1; }
[ -f frontend/dist/index.html ] || (cd frontend && npm install && npm run build)
cd backend
exec .venv/bin/python -m uvicorn app.main:app_factory --factory --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
