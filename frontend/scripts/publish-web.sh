#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8787}
CONFIG_PATH=${CONFIG_PATH:-"${ROOT_DIR}/serve.json"}
SERVE_CONFIG_PATH=${SERVE_CONFIG_PATH:-"${ROOT_DIR}/dist/serve.json"}
BUILD_VERSION=${BUILD_VERSION:-$(date +%s)}

append_asset_version_suffix() {
  local target_file="$1"

  BUILD_VERSION="${BUILD_VERSION}" perl -0pi -e \
    's{(/_expo/static/(?:css/[^"'"'"'"'"'"'"'"'"'\''?]+\.css|js/web/[^"'"'"'"'"'"'"'"'"'\''?]+\.js))(?!\?v=)}{$1 . "?v=" . $ENV{BUILD_VERSION}}ge' \
    "${target_file}"
}

cd "${ROOT_DIR}"
rm -rf dist
npx expo export -p web --clear
cp "${CONFIG_PATH}" "${SERVE_CONFIG_PATH}"

while IFS= read -r -d '' html_file; do
  append_asset_version_suffix "${html_file}"
done < <(find dist -type f -name '*.html' -print0)

while IFS= read -r -d '' entry_file; do
  append_asset_version_suffix "${entry_file}"
done < <(find dist/_expo/static/js/web -type f -name 'entry-*.js' -print0)

echo "Serving dist/ on http://${HOST}:${PORT}"

LISTEN_ENDPOINT="tcp://${HOST}:${PORT}"

if [ "${DETACH:-0}" = "1" ]; then
  nohup npx serve -c "${SERVE_CONFIG_PATH}" dist -s --listen "${LISTEN_ENDPOINT}" > /tmp/a2a-web-serve.log 2>&1 &
  echo "Server started in background. Logs: /tmp/a2a-web-serve.log"
  exit 0
fi

npx serve -c "${SERVE_CONFIG_PATH}" dist -s --listen "${LISTEN_ENDPOINT}"
