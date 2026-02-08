#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"${REPO_ROOT}/scripts/dev/bootstrap_python.sh"

cd "${REPO_ROOT}/backend"

"${REPO_ROOT}/.venv/bin/python" -m ruff check app tests ../scripts/dev
