#!/usr/bin/env bash
set -euo pipefail

PORT=${PORT:-8787}

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale CLI not found. Please install/enable Tailscale first." >&2
  exit 1
fi

npx expo export -p web

TAILSCALE_IP=$(tailscale ip -4 | head -n 1 | tr -d '\r')
if [ -z "$TAILSCALE_IP" ]; then
  echo "Failed to resolve Tailscale IPv4 address." >&2
  exit 1
fi

echo "Serving dist/ on http://${TAILSCALE_IP}:${PORT}"

LISTEN_ENDPOINT="tcp://0.0.0.0:${PORT}"

if [ "${DETACH:-0}" = "1" ]; then
  nohup npx serve dist -s --listen "${LISTEN_ENDPOINT}" > /tmp/a2a-web-serve.log 2>&1 &
  echo "Server started in background. Logs: /tmp/a2a-web-serve.log"
  exit 0
fi

npx serve dist -s --listen "${LISTEN_ENDPOINT}"
