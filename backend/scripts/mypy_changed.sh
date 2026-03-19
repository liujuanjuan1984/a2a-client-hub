#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "${REPO_ROOT}"

declare -a CANDIDATES=()
declare -a OUTSIDE_SCOPE=()
declare -A SEEN=()
INCLUDE_REGEX=${MYPY_INCLUDE_REGEX:-^backend/app/((utils|schemas|core|db)/.*\.py|services/(a2a_stream_diagnostics|interrupt_metadata_normalization|invoke_guard)\.py)$}

normalize_path() {
  local path="$1"
  path="${path#./}"
  path="${path#${REPO_ROOT}/}"
  printf '%s' "$path"
}

add_candidate() {
  local raw_path="$1"
  local path
  path=$(normalize_path "$raw_path")

  if [[ ! "$path" =~ ^backend/.*\.py$ ]]; then
    return
  fi

  if [[ ! "$path" =~ $INCLUDE_REGEX ]]; then
    OUTSIDE_SCOPE+=("$path")
    return
  fi

  if [[ ! -f "$path" ]]; then
    return
  fi

  if [[ -n "${SEEN[$path]:-}" ]]; then
    return
  fi

  SEEN["$path"]=1
  CANDIDATES+=("$path")
}

collect_changed_from_git() {
  local base_ref=""

  if [[ -n "${MYPY_BASE_REF:-}" ]]; then
    base_ref="${MYPY_BASE_REF}"
  elif [[ -n "${GITHUB_BASE_REF:-}" ]]; then
    base_ref="origin/${GITHUB_BASE_REF}"
  elif git rev-parse --verify origin/master >/dev/null 2>&1; then
    base_ref="origin/master"
  fi

  if [[ -n "$base_ref" ]] && git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
    while IFS= read -r file; do
      add_candidate "$file"
    done < <(git diff --name-only "$base_ref"...HEAD)
    return
  fi

  if git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    while IFS= read -r file; do
      add_candidate "$file"
    done < <(git diff --name-only HEAD~1 HEAD)
  fi
}

if [[ "$#" -gt 0 ]]; then
  for file in "$@"; do
    add_candidate "$file"
  done
else
  collect_changed_from_git
fi

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  if [[ "${#OUTSIDE_SCOPE[@]}" -gt 0 ]]; then
    echo "Skipping mypy for files outside phase-1 scope (${INCLUDE_REGEX}):"
    printf ' - %s\n' "${OUTSIDE_SCOPE[@]}"
  fi
  echo "No changed backend Python files detected; skipping mypy."
  exit 0
fi

cd "${REPO_ROOT}/backend"

declare -a MYPY_TARGETS=()
for file in "${CANDIDATES[@]}"; do
  MYPY_TARGETS+=("${file#backend/}")
done

echo "Running mypy for changed backend files:"
printf ' - %s\n' "${CANDIDATES[@]}"

uv run mypy --config-file pyproject.toml "${MYPY_TARGETS[@]}"
