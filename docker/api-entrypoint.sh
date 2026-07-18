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

if [ "${KOR_TRAVEL_MAP_OPS_TOKEN+x}" = "x" ] || [ "${KOR_TRAVEL_MAP_OPS_ACTOR+x}" = "x" ]; then
  echo "legacy root ops principal keys must not enter API container" >&2
  exit 1
fi

if [ "${KOR_TRAVEL_MAP_API_OPS_ACTOR+x}" = "x" ]; then
  echo "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed; the audit actor is fixed" >&2
  exit 1
fi

api_proxy_secret="${KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET:-}"
trimmed_api_proxy_secret="$(printf '%s' "$api_proxy_secret" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [ "$api_proxy_secret" != "$trimmed_api_proxy_secret" ] || [ "${#api_proxy_secret}" -lt 32 ]; then
  echo "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET must be at least 32 characters without surrounding whitespace" >&2
  exit 1
fi

ops_read_is_set="${KOR_TRAVEL_MAP_API_OPS_READ_TOKEN+x}"
ops_cancel_is_set="${KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN+x}"
ops_required_is_set="${KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED+x}"
ops_principal_required=false
if [ "$ops_required_is_set" = "x" ]; then
  ops_principal_required="$KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED"
  case "$ops_principal_required" in
    true | false) ;;
    *)
      echo "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED must be exactly true or false" >&2
      exit 1
      ;;
  esac
fi
if [ "$ops_read_is_set" != "$ops_cancel_is_set" ]; then
  echo "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be configured together" >&2
  exit 1
fi
if [ "$ops_read_is_set" != "x" ]; then
  if [ "$ops_principal_required" = "true" ]; then
    echo "ops principal is required but read/cancel tokens are absent" >&2
    exit 1
  fi
else
  ops_read_token="$KOR_TRAVEL_MAP_API_OPS_READ_TOKEN"
  ops_cancel_token="$KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN"
  if [ -z "$ops_read_token" ] && [ -z "$ops_cancel_token" ]; then
    if [ "$ops_principal_required" = "true" ]; then
      echo "ops principal is required but read/cancel tokens are empty" >&2
      exit 1
    fi
  elif [ -z "$ops_read_token" ] || [ -z "$ops_cancel_token" ]; then
    echo "ops read and cancel tokens must both be empty or both be non-empty" >&2
    exit 1
  else
    case "$ops_read_token" in
      *[[:space:]]*)
        echo "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN must contain no whitespace" >&2
        exit 1
        ;;
    esac
    case "$ops_cancel_token" in
      *[[:space:]]*)
        echo "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must contain no whitespace" >&2
        exit 1
        ;;
    esac
    if [ "${#ops_read_token}" -lt 32 ]; then
      echo "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN must be at least 32 characters" >&2
      exit 1
    fi
    if [ "${#ops_cancel_token}" -lt 32 ]; then
      echo "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be at least 32 characters" >&2
      exit 1
    fi
    if [ "$ops_read_token" = "$ops_cancel_token" ]; then
      echo "ops read and cancel tokens must be distinct" >&2
      exit 1
    fi
    if [ "$ops_read_token" = "$api_proxy_secret" ] || [ "$ops_cancel_token" = "$api_proxy_secret" ]; then
      echo "ops read/cancel tokens must be distinct from the admin proxy secret" >&2
      exit 1
    fi
    api_service_token="${KOR_TRAVEL_MAP_API_SERVICE_TOKEN:-}"
    if [ -n "$api_service_token" ]; then
      if [ "$ops_read_token" = "$api_service_token" ] || [ "$ops_cancel_token" = "$api_service_token" ]; then
        echo "ops read/cancel tokens must be distinct from the service token" >&2
        exit 1
      fi
    fi
  fi
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
