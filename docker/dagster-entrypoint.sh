#!/bin/sh
set -eu

api_only_name="$(
  /usr/local/bin/python -I -c '
import os

manual_create_names = {
    "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
    "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
    "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED",
}
print(
    next(
        (
            name
            for name in os.environ
            if name in manual_create_names
            or name.startswith(
                ("KOR_TRAVEL_MAP_API_OPS_", "KOR_TRAVEL_MAP_OPS_")
            )
        ),
        "",
    ),
    end="",
)
'
)"
if [ -n "$api_only_name" ]; then
  case "$api_only_name" in
    KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN | \
      KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 | \
      KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED)
      echo "manual Feature create credential key must not enter Dagster process: $api_only_name" >&2
      ;;
    *)
      echo "API-only ops principal key must not enter Dagster process: $api_only_name" >&2
      ;;
  esac
  exit 1
fi

application_privileged_name="$(
  /usr/local/bin/python -I -c '
import os

exact_names = {
    "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE",
    "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN",
    "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD",
    "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN",
    "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD",
    "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD",
    "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN",
    "KOR_TRAVEL_MAP_POSTGRES_DB",
    "KOR_TRAVEL_MAP_POSTGRES_PASSWORD",
    "KOR_TRAVEL_MAP_POSTGRES_USER",
}
print(
    next(
        (
            name
            for name in os.environ
            if name in exact_names
            or name.startswith("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_")
        ),
        "",
    ),
    end="",
)
'
)"
if [ -n "$application_privileged_name" ]; then
  echo "application migration/bootstrap credential key must not enter Dagster process: $application_privileged_name" >&2
  exit 1
fi

if [ "${KOR_TRAVEL_MAP_DAGSTER_PROFILE+x}" = "x" ]; then
  dagster_profile="$KOR_TRAVEL_MAP_DAGSTER_PROFILE"
else
  dagster_profile="production"
fi
case "$dagster_profile" in
  production | local-dev) ;;
  *)
    echo "KOR_TRAVEL_MAP_DAGSTER_PROFILE must be exactly production or local-dev" >&2
    exit 1
    ;;
esac
if [ "$dagster_profile" = "production" ] \
  && { [ "${PYTHONPATH+x}" = "x" ] \
    || [ "${PYTHONHOME+x}" = "x" ] \
    || [ "${PYTHONUSERBASE+x}" = "x" ]; }; then
  echo "production Dagster forbids PYTHONPATH, PYTHONHOME, and PYTHONUSERBASE overrides" >&2
  exit 1
fi
if [ "$dagster_profile" = "production" ] \
  && [ "${PYTHONNOUSERSITE:-}" != "1" ]; then
  echo "production Dagster requires PYTHONNOUSERSITE=1" >&2
  exit 1
fi
if [ "$dagster_profile" = "production" ] \
  && [ "${PATH:-}" != "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin" ]; then
  echo "production Dagster requires the sealed runtime PATH" >&2
  exit 1
fi
if [ "$dagster_profile" = "production" ] \
  && [ "${DAGSTER_HOME:-}" != "/opt/dagster/dagster_home" ]; then
  echo "production Dagster requires the sealed DAGSTER_HOME" >&2
  exit 1
fi

runtime_preflight() {
  # webserver와 daemon이 실제로 읽을 canonical dagster.yaml, metadata DSN과
  # root-owned metadata DB identity permit을 migration one-shot과 같은 verifier로
  # 먼저 결박한다. application final permit만으로 metadata target은 증명되지 않는다.
  if ! /usr/local/bin/python -I \
    /usr/local/bin/ktm-dagster-storage verify-identity >/dev/null; then
    echo "Dagster runtime requires a valid metadata database identity permit" >&2
    exit 1
  fi
  if [ "$dagster_profile" = "production" ]; then
    # API permit만 확인하면 Dagster webserver/daemon이 같은 Map DB에 permit 없이
    # 직접 연결할 수 있다. consumer-specific immutable Dagster image ID와 자기 runtime
    # DSN의 DB identity/raw 300은 sealed verifier가 함께 검사한다.
    # verifier가 확인하는 named DSN과 Dagster resource가 실제로 읽는
    # KOR_TRAVEL_MAP_PG_DSN은 문자열까지 완전히 같은 한 연결이어야 한다.
    # Compose의 같은 interpolation만으로는 직접 docker run/overlay에서의
    # split-brain을 막지 못한다. 기존 PG_DSN이 다른 값이면 permit 실행 전
    # 거부하고, 같거나 미설정이면 named runtime DSN으로 단일화한다.
    dagster_runtime_dsn="${KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN:?KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN is required in production}"
    if [ "${KOR_TRAVEL_MAP_PG_DSN+x}" = "x" ] \
      && [ "$KOR_TRAVEL_MAP_PG_DSN" != "$dagster_runtime_dsn" ]; then
      echo "KOR_TRAVEL_MAP_PG_DSN must exactly equal KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN in production" >&2
      exit 1
    fi
    export KOR_TRAVEL_MAP_PG_DSN="$dagster_runtime_dsn"

    if ! /usr/local/bin/python -I \
      /usr/local/bin/ktm-application-schema-final-permit verify-dagster; then
      echo "production Dagster requires a valid Docker Manager application final permit" >&2
      exit 1
    fi
    unset KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN
  fi
  /usr/local/bin/python -I -m kortravelmap.dagster.runtime_preflight
}

storage_input_preflight() {
  if [ "${KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN+x}" = "x" ] \
    || [ "${KOR_TRAVEL_MAP_PG_DSN+x}" = "x" ] \
    || [ "${KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_DAGSTER_IMAGE_ID+x}" = "x" ] \
    || [ "${KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID+x}" = "x" ]; then
    echo "Dagster metadata migration forbids application runtime/final-permit inputs" >&2
    exit 1
  fi
  if [ -e /run/kor-travel-map-application-final-permit ]; then
    echo "Dagster metadata migration forbids the application final-permit mount" >&2
    exit 1
  fi
}

if [ "$dagster_profile" = "production" ]; then
  # production은 fixed image executable과 한 가지 argv 형상만 허용한다. bare PATH
  # lookup과 shell command override는 permit 뒤 다른 executable을 실행할 수 있으므로
  # Manager launch attestation 이전에도 image 안에서 fail-close한다.
  case "${1:-}" in
    /usr/local/bin/dagster-webserver)
      if [ "$#" -ne 7 ] \
        || [ "${2:-}" != "-m" ] \
        || [ "${3:-}" != "kortravelmap.dagster.definitions" ] \
        || [ "${4:-}" != "-h" ] \
        || [ "${5:-}" != "0.0.0.0" ] \
        || [ "${6:-}" != "-p" ]; then
        echo "production Dagster webserver argv does not match the sealed launch contract" >&2
        exit 1
      fi
      case "${7:-}" in
        "" | *[!0-9]*)
          echo "production Dagster webserver port must be numeric" >&2
          exit 1
          ;;
      esac
      if [ "$7" -lt 1 ] || [ "$7" -gt 65535 ]; then
        echo "production Dagster webserver port is outside 1..65535" >&2
        exit 1
      fi
      runtime_preflight
      ;;
    /usr/local/bin/dagster-daemon)
      if [ "$#" -ne 4 ] \
        || [ "${2:-}" != "run" ] \
        || [ "${3:-}" != "-m" ] \
        || [ "${4:-}" != "kortravelmap.dagster.definitions" ]; then
        echo "production Dagster daemon argv does not match the sealed launch contract" >&2
        exit 1
      fi
      runtime_preflight
      ;;
    /usr/local/bin/ktm-dagster-storage)
      if [ "$#" -ne 2 ] || [ "${2:-}" != "migrate" ]; then
        echo "production Dagster storage argv does not match the sealed launch contract" >&2
        exit 1
      fi
      storage_input_preflight
      ;;
    *)
      echo "production Dagster requires a sealed absolute runtime command" >&2
      exit 1
      ;;
  esac
else
  case "${1:-}" in
    /usr/local/bin/ktm-dagster-storage)
      if [ "${2:-}" = "migrate" ]; then
        storage_input_preflight
      fi
      ;;
    dagster-webserver | /usr/local/bin/dagster-webserver)
      runtime_preflight
      ;;
    dagster-daemon | /usr/local/bin/dagster-daemon)
      if [ "${2:-}" = "run" ]; then
        runtime_preflight
      fi
      ;;
    sh | /bin/sh)
      if [ "${2:-}" = "-c" ]; then
        case "${3:-}" in
          dagster-webserver\ * | exec\ dagster-webserver\ *)
            runtime_preflight
            ;;
          dagster-daemon\ run\ * | exec\ dagster-daemon\ run\ *)
            runtime_preflight
            ;;
        esac
      fi
      ;;
  esac
fi

if [ "$dagster_profile" = "production" ]; then
  # Console-script shebang은 writable HOME의 user-site/sitecustomize를 읽을 수 있다.
  # 검증한 fixed script 자체를 isolated interpreter로 실행해 candidate 밖 Python
  # import 경로를 runtime/daemon/storage process에서도 끊는다.
  exec /usr/local/bin/python -I "$@"
fi
exec "$@"
