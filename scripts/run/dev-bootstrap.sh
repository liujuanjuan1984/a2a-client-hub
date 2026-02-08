#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: dev-bootstrap.sh [options]

Bootstraps Compass development services via PM2 after verifying the local environment.

Options:
  --frontend-host HOST   Hostname or IP for the frontend dev server (default: 127.0.0.1)
  --frontend-port PORT   Port for the frontend dev server (default: 5173)
  --backend-host HOST    Hostname or IP for the backend API server (default: 127.0.0.1)
  --backend-port PORT    Port for the backend API server (default: 8000)
  --force                Ignore port-in-use checks.
  -h, --help             Show this help.

Environment variables override the defaults as well:
  COMPASS_FRONTEND_HOST, COMPASS_FRONTEND_PORT,
  COMPASS_BACKEND_HOST,  COMPASS_BACKEND_PORT.
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ECOSYSTEM_FILE="$ROOT/scripts/run/ecosystem.dev.config.mjs"

BACKEND_PM2_NAME="${COMPASS_BACKEND_PM2_NAME:-compass-backend}"
FRONTEND_PM2_NAME="${COMPASS_FRONTEND_PM2_NAME:-compass-frontend}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ensure_file() {
  local path="$1" message="$2"
  if [[ ! -e "$path" ]]; then
    echo "$message ($path)" >&2
    exit 1
  fi
}

validate_port() {
  local port="$1" label="$2"
  if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
    echo "$label port must be an integer between 1 and 65535: $port" >&2
    exit 1
  fi
}

ensure_port_free() {
  local port="$1" label="$2" allowed="$3"
  if [[ "$FORCE" == "1" ]]; then
    return
  fi

  local allowed_pids=()
  if [[ -n "$allowed" ]]; then
    read -r -a allowed_pids <<<"$allowed"
  fi

  local pids=()
  if command -v lsof >/dev/null 2>&1; then
    mapfile -t pids < <(lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u)
  elif command -v ss >/dev/null 2>&1; then
    mapfile -t pids < <(ss -ltnp "( sport = :$port )" 2>/dev/null | awk 'NR>1 { split($NF,pid,"pid="); if (pid[2] != "") { split(pid[2],pid2,","); print pid2[1]; }}' | sort -u)
  else
    echo "Unable to check port availability (missing lsof/ss). Use --force to bypass." >&2
    return
  fi

  if ((${#pids[@]} == 0)); then
    return
  fi

  if ((${#allowed_pids[@]} > 0)); then
    local filtered=()
    for pid in "${pids[@]}"; do
      local keep=1
      for apid in "${allowed_pids[@]}"; do
        if [[ "$pid" == "$apid" ]]; then
          keep=0
          break
        fi
      done
      if ((keep == 1)); then
        filtered+=("$pid")
      fi
    done
    pids=("${filtered[@]}")
  fi

  if ((${#pids[@]} == 0)); then
    return
  fi

  echo "$label port $port already in use. Use --force to bypass or free the port." >&2
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -nP
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp "( sport = :$port )"
  fi
  exit 1
}

build_cors_origins() {
  local host="$1" port="$2"
  local origins=(
    "http://localhost:$port"
    "http://127.0.0.1:$port"
  )

  if [[ "$host" != "localhost" && "$host" != "127.0.0.1" && "$host" != "0.0.0.0" ]]; then
    origins+=("http://$host:$port" "https://$host:$port")
  fi

  (IFS=,; echo "${origins[*]}")
}

FORCE=0
FRONTEND_HOST="${COMPASS_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${COMPASS_FRONTEND_PORT:-5173}"
BACKEND_HOST="${COMPASS_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${COMPASS_BACKEND_PORT:-8000}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --frontend-host)
      FRONTEND_HOST="${2:-}"
      shift 2
      ;;
    --frontend-port)
      FRONTEND_PORT="${2:-}"
      shift 2
      ;;
    --backend-host)
      BACKEND_HOST="${2:-}"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_command pm2
require_command npm
ensure_file "$ROOT/.venv/bin/python" "Python virtual environment not found"
ensure_file "$ROOT/backend/app/main.py" "Backend entrypoint missing"
ensure_file "$ECOSYSTEM_FILE" "PM2 ecosystem file missing"

# Activate virtual environment so downstream tooling (e.g. pm2 env) inherits it.
# shellcheck source=/dev/null
source "$ROOT/.venv/bin/activate"

if [[ -z "$BACKEND_HOST" ]]; then
  echo "Backend host must not be empty." >&2
  exit 1
fi
if [[ -z "$FRONTEND_HOST" ]]; then
  echo "Frontend host must not be empty." >&2
  exit 1
fi

validate_port "$BACKEND_PORT" "Backend"
validate_port "$FRONTEND_PORT" "Frontend"

backend_pid="$(pm2 pid "$BACKEND_PM2_NAME" 2>/dev/null || true)"
frontend_pid="$(pm2 pid "$FRONTEND_PM2_NAME" 2>/dev/null || true)"

[[ "$backend_pid" == "0" ]] && backend_pid=""
[[ "$frontend_pid" == "0" ]] && frontend_pid=""

ensure_port_free "$BACKEND_PORT" "Backend" "$backend_pid"
ensure_port_free "$FRONTEND_PORT" "Frontend" "$frontend_pid"

export COMPASS_BACKEND_HOST="$BACKEND_HOST"
export COMPASS_BACKEND_PORT="$BACKEND_PORT"
export COMPASS_FRONTEND_HOST="$FRONTEND_HOST"
export COMPASS_FRONTEND_PORT="$FRONTEND_PORT"
export BACKEND_CORS_ORIGINS
BACKEND_CORS_ORIGINS="$(build_cors_origins "$FRONTEND_HOST" "$FRONTEND_PORT")"

echo "Starting Compass services via PM2..."
echo "Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "CORS origins: $BACKEND_CORS_ORIGINS"

start_apps=()
restart_apps=()

if pm2 describe "$BACKEND_PM2_NAME" >/dev/null 2>&1; then
  restart_apps+=("$BACKEND_PM2_NAME")
else
  start_apps+=("$BACKEND_PM2_NAME")
fi

if pm2 describe "$FRONTEND_PM2_NAME" >/dev/null 2>&1; then
  restart_apps+=("$FRONTEND_PM2_NAME")
else
  start_apps+=("$FRONTEND_PM2_NAME")
fi

for app in "${start_apps[@]}"; do
  echo "Starting PM2 app: $app"
  pm2 start "$ECOSYSTEM_FILE" --only "$app" --update-env
done

for app in "${restart_apps[@]}"; do
  echo "Restarting PM2 app: $app"
  pm2 restart "$app" --update-env
done

pm2 status "$BACKEND_PM2_NAME" "$FRONTEND_PM2_NAME"

echo "Use scripts/run/dev-logs.sh <app-name> to tail logs (default app: ${BACKEND_PM2_NAME})."
