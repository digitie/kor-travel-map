#!/usr/bin/env sh
set -eu

removed_provider_keys="
KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY
KOR_TRAVEL_MAP_API_KMA_APIHUB_KEY
KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY
KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY
KOR_TRAVEL_MAP_API_VISITKOREA_SERVICE_KEY
KOR_TRAVEL_MAP_API_KREX_SERVICE_KEY
KOR_TRAVEL_MAP_API_KNPS_SERVICE_KEY
KOR_TRAVEL_MAP_API_AIRKOREA_SERVICE_KEY
KOR_TRAVEL_MAP_API_KRFOREST_SERVICE_KEY
KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED
"
for name in $removed_provider_keys; do
  eval "is_set=\${$name+x}"
  if [ "$is_set" = "x" ]; then
    echo "removed provider runtime key must not enter API container: $name" >&2
    exit 1
  fi
done

if [ "${KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET+x}" = "x" ]; then
  echo "legacy API-specific admin proxy secret must not enter API container" >&2
  exit 1
fi

api_proxy_secret="${KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET:-}"
trimmed_api_proxy_secret="$(printf '%s' "$api_proxy_secret" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [ -z "$api_proxy_secret" ] || [ "$api_proxy_secret" != "$trimmed_api_proxy_secret" ]; then
  echo "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET is required without surrounding whitespace" >&2
  exit 1
fi

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

exec python -m uvicorn kortravelmap.api.app:app \
  --host 0.0.0.0 \
  --port "${KOR_TRAVEL_MAP_API_PORT:-12701}"
