#!/usr/bin/env bash
set -euo pipefail

# Test DB bootstrap without Docker.
# We rely on a locally available PostgreSQL server accessible via unix socket.

DB_NAME="${A2A_TEST_DB_NAME:-juanjuan}"

psql -d "${DB_NAME}" -c "SELECT 1" >/dev/null
