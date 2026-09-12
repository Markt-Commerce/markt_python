#!/usr/bin/env bash
# Rebuild the disposable smoke environment from zero: drop the database,
# re-run every migration, re-seed. Safe to run repeatedly.
#
# Requires the smoke env to be sourced first (DB_* pointing at the disposable
# instance) and refuses to touch anything whose name is not *_smoke.
set -euo pipefail

: "${DB_NAME:?source the smoke env first}"
: "${DB_HOST:?}" ; : "${DB_PORT:?}" ; : "${DB_USER:?}" ; : "${DB_PASSWORD:?}"

if [[ "$DB_NAME" != *_smoke ]]; then
  echo "REFUSING: DB_NAME='$DB_NAME' is not a *_smoke database." >&2
  exit 1
fi
if [[ "$DB_HOST" != "127.0.0.1" && "$DB_HOST" != "localhost" ]]; then
  echo "REFUSING: DB_HOST='$DB_HOST' is not local." >&2
  exit 1
fi

PY="${SMOKE_PYTHON:-python}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> Dropping and recreating $DB_NAME on $DB_HOST:$DB_PORT"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE);" \
  -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" >/dev/null

echo "==> Running migrations from zero"
cd "$REPO"
FLASK_APP=main.run:app PYTHONPATH="$REPO" "$PY" -m flask db upgrade 2>&1 \
  | grep -E "Running upgrade|ERROR" || true

echo "==> Seeding"
PYTHONPATH="$REPO" "$PY" tests/smoke/seed_smoke_data.py 2>&1 \
  | grep -vE "^\s*\[?[0-9]{4}-|INFO |warn|pkg_resources|get_unique_schema|^\s*$" || true

echo "==> Ready"
