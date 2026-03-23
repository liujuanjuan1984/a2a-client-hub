#!/usr/bin/env bash

set -euo pipefail

MODE="${1:-strict}"

case "$MODE" in
  strict)
    exec uv run --with vulture vulture app tests --min-confidence 80
    ;;
  exploratory)
    exec uv run --with vulture vulture app tests
    ;;
  *)
    echo "Usage: scripts/run_vulture.sh [strict|exploratory]" >&2
    exit 2
    ;;
esac
