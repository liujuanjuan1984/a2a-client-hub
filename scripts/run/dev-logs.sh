#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FORMATTER="$ROOT/scripts/run/pretty_logs.py"

DEFAULT_APP="${COMPASS_BACKEND_PM2_NAME:-compass-backend}"
APP_NAME="${1:-$DEFAULT_APP}"
if [[ $# -gt 0 ]]; then
  shift
fi

DEFAULT_LINES="${COMPASS_PM2_LOG_LINES:-100}"
INJECT_LINES=1
for arg in "$@"; do
  if [[ "$arg" == "--lines" ]]; then
    INJECT_LINES=0
    break
  fi
done

EXTRA_ARGS=("$@")
if (( INJECT_LINES == 1 )); then
  EXTRA_ARGS+=("--lines" "$DEFAULT_LINES")
fi

if ! command -v pm2 >/dev/null 2>&1; then
  echo "pm2 command not found." >&2
  exit 1
fi

if [[ ! -x "$FORMATTER" ]]; then
  echo "Missing log formatter at $FORMATTER" >&2
  exit 1
fi

echo "Tailing JSON logs for $APP_NAME (Ctrl+C to exit)..."
pm2 logs "$APP_NAME" --json "${EXTRA_ARGS[@]}" | "$FORMATTER"
