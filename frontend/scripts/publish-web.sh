#!/usr/bin/env bash
set -euo pipefail

HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8787}

rm -rf dist
npx expo export -p web

echo "Serving dist/ on http://${HOST}:${PORT}"

LISTEN_ENDPOINT="tcp://${HOST}:${PORT}"

if [ "${DETACH:-0}" = "1" ]; then
  nohup npx serve dist -s --listen "${LISTEN_ENDPOINT}" > /tmp/a2a-web-serve.log 2>&1 &
  echo "Server started in background. Logs: /tmp/a2a-web-serve.log"
  exit 0
fi

npx serve dist -s --listen "${LISTEN_ENDPOINT}"
