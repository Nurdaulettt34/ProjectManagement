#!/bin/sh
# Apply migrations and seed (both idempotent), then start the given command.
set -e
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  flask db upgrade
  flask seed || echo "flask seed failed (set SEED_*_PASSWORD) — continuing without it"
fi
exec "$@"
