#!/usr/bin/env sh
set -eu

retries="${KOR_TRAVEL_MAP_MIGRATION_RETRIES:-30}"
sleep_seconds="${KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS:-2}"
attempt=1

while ! alembic upgrade head; do
  if [ "$attempt" -ge "$retries" ]; then
    echo "alembic upgrade head failed after $attempt attempts" >&2
    exit 1
  fi
  echo "alembic upgrade head failed; retrying ($attempt/$retries)" >&2
  attempt=$((attempt + 1))
  sleep "$sleep_seconds"
done

exec python -m uvicorn kortravelmap.admin.app:app \
  --host 0.0.0.0 \
  --port "${KOR_TRAVEL_MAP_ADMIN_PORT:-12301}"
