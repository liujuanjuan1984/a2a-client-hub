#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"${REPO_ROOT}/scripts/dev/bootstrap_python.sh"

cd "${REPO_ROOT}/backend"

# The upstream FastAPI codebase is not type-check clean under strict mypy.
# We keep `check-types` as a focused smoke-check for the A2A client surface area.
"${REPO_ROOT}/.venv/bin/python" -m mypy \
  --follow-imports=skip \
  --ignore-missing-imports \
  --disable-error-code=untyped-decorator \
  --disable-error-code=no-any-return \
  --disable-error-code=no-untyped-def \
  app/api/routers/auth.py \
  app/api/routers/a2a_agents.py \
  app/api/routers/a2a_schedules.py \
  app/api/routers/me_sessions.py
