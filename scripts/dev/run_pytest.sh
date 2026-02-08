#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"${REPO_ROOT}/scripts/dev/bootstrap_python.sh"
"${REPO_ROOT}/scripts/dev/ensure_postgres.sh"

# The repository guideline mandates `npm run test -- --runInBand`.
# `--runInBand` is a Jest flag; ignore it while forwarding the rest to pytest.
PYTEST_ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --runInBand) ;;
    *) PYTEST_ARGS+=("${arg}") ;;
  esac
done

export DATABASE_URL="${DATABASE_URL:-postgresql:///juanjuan}"

cd "${REPO_ROOT}/backend"
if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
  PYTEST_ARGS=(
    tests/test_auth.py
    tests/test_a2a_integration.py
    tests/test_a2a_proxy_security.py
    tests/test_a2a_schedule_routes.py
    tests/test_a2a_validators.py
    tests/test_a2a_websocket.py
    tests/test_me_sessions_routes.py
    tests/test_health.py
  )
fi

"${REPO_ROOT}/.venv/bin/python" -m pytest "${PYTEST_ARGS[@]}"
