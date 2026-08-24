#!/usr/bin/env sh
set -eu

api_only_name="$(
  python -c '
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

runtime_preflight() {
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

    if ! ktm-application-schema-final-permit verify-dagster; then
      echo "production Dagster requires a valid Docker Manager application final permit" >&2
      exit 1
    fi
    unset KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN
  fi
  python -m kortravelmap.dagster.runtime_preflight
}

case "${1:-}" in
  # Compose는 exec-form으로 webserver를 전달한다.
  dagster-webserver)
    runtime_preflight
    ;;
  # daemon의 실제 runtime subcommand만 DB를 사용한다. help/version 등은
  # metadata 또는 application runtime DSN 없이도 정상 동작해야 한다.
  dagster-daemon)
    if [ "${2:-}" = "run" ]; then
      runtime_preflight
    fi
    ;;
  # Dockerfile 기본 CMD는 port env를 확장하려고 `/bin/sh -c`를 쓴다. command
  # 문자열이 실제 runtime executable로 시작할 때만 같은 preflight를 적용한다.
  # `sh -c 'echo dagster-webserver'` 같은 maintenance command는 건드리지 않는다.
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

exec "$@"
