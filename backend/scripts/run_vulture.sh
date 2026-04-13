#!/usr/bin/env bash

set -euo pipefail

MODE="${1:-strict}"
STRICT_ARGS=(app tests --min-confidence 80)
EXPLORATORY_ARGS=(
  app
  tests
  --ignore-names
  "pytestmark,model_config"
  --ignore-decorators
  "@app.get,@app.post,@app.put,@app.patch,@app.delete,@app.websocket,@router.get,@router.post,@router.put,@router.patch,@router.delete,@router.websocket,@field_validator,@model_validator,@validator,@root_validator"
)

case "$MODE" in
  strict)
    exec uv run --with vulture vulture "${STRICT_ARGS[@]}"
    ;;
  exploratory)
    exec uv run --with vulture vulture "${EXPLORATORY_ARGS[@]}"
    ;;
  *)
    echo "Usage: scripts/run_vulture.sh [strict|exploratory]" >&2
    exit 2
    ;;
esac
