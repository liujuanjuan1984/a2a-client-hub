#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${FRONTEND_DIR}"

OUTPUT="$(
  ./node_modules/.bin/ts-prune \
    -p tsconfig.diagnostics.json \
    -i '^(app/|lib/storage/mmkv.web.ts|test-utils/mockMmkv.ts)' \
    | rg -v 'used in module' \
    || true
)"

if [[ -n "${OUTPUT}" ]]; then
  printf '%s\n' "${OUTPUT}"
  exit 1
fi
