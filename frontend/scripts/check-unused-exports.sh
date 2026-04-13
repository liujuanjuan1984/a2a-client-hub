#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${FRONTEND_DIR}"

OUTPUT="$(
  ./node_modules/.bin/ts-prune | rg -v \
    'used in module| - default$| - ErrorBoundary$|lib/storage/mmkv.web.ts:10 - buildPersistStorageName|lib/storage/mmkv.web.ts:33 - createPersistStorage|test-utils/mockMmkv.ts:1 - createMockMmkvModule' \
    || true
)"

if [[ -n "${OUTPUT}" ]]; then
  printf '%s\n' "${OUTPUT}"
  exit 1
fi
