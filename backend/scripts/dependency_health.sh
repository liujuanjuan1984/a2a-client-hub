#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "${REPO_ROOT}/backend"

uv sync --extra dev --locked
uv pip check
uv pip list --outdated
uv run pip-audit
