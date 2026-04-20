#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="${1:-all}"

print_usage() {
  cat <<'EOF'
Usage: scripts/check-dead-code.sh [all|backend|frontend|exploratory-backend]

Modes:
  all                  Run the maintained high-confidence backend + frontend checks.
  backend              Run the maintained high-confidence backend check only.
  frontend             Run the maintained high-confidence frontend check only.
  exploratory-backend  Run the backend exploratory vulture scan for manual triage only.

Notes:
  - Treat strict/backend/frontend modes as high-confidence hygiene checks.
  - Treat exploratory-backend output as manual triage input only.
  - Do not delete code directly from exploratory output without verifying dynamic usages.
EOF
}

run_backend_strict() {
  echo "[dead-code] Running backend strict scan..."
  (
    cd "${REPO_DIR}/backend"
    bash scripts/run_vulture.sh
  )
}

run_backend_exploratory() {
  cat <<'EOF'
[dead-code] Running backend exploratory scan...
[dead-code] Warning: exploratory output is low-confidence triage input only.
[dead-code] Common false positives include FastAPI routes, Pydantic validators,
[dead-code] SQLAlchemy hooks, pytest fixtures, and test doubles.
EOF
  (
    cd "${REPO_DIR}/backend"
    bash scripts/run_vulture.sh exploratory
  )
}

run_frontend_strict() {
  echo "[dead-code] Running frontend strict scan..."
  (
    cd "${REPO_DIR}/frontend"
    bash scripts/check-unused-exports.sh
  )
}

case "${MODE}" in
  all)
    run_backend_strict
    run_frontend_strict
    ;;
  backend)
    run_backend_strict
    ;;
  frontend)
    run_frontend_strict
    ;;
  exploratory-backend)
    run_backend_exploratory
    ;;
  -h|--help|help)
    print_usage
    ;;
  *)
    print_usage >&2
    exit 2
    ;;
esac
