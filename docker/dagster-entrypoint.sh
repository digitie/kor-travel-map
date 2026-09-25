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

# ADR-100: 세 비밀번호 이름이 KOR_TRAVEL_MAP_SERVICE_PASSWORD 하나로 합쳐졌고,
# 두 DSN 이름은 이 집합에서 **지웠다**. 이름만 바꾸면 KOR_TRAVEL_MAP_PG_DSN이 금지
# 목록에 들어가는데 아래 production 분기가 그 이름을 요구하므로 Dagster가 매 기동마다
# 죽는다. 애플리케이션 DSN을 이 one-shot에서 차단하는 일은 storage_input_preflight의
# KOR_TRAVEL_MAP_PG_DSN 검사가 계속 맡는다.
exact_names = {
    "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE",
    "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN",
    "KOR_TRAVEL_MAP_SERVICE_PASSWORD",
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
    # 직접 연결할 수 있다. consumer-specific immutable Dagster image ID와 runtime DSN의
    # DB identity/raw 300은 sealed verifier가 함께 검사한다.
    #
    # ADR-100: 예전에는 verifier가 보는 named DSN(`..._DAGSTER_RUNTIME_PG_DSN`)과
    # Dagster resource가 읽는 `KOR_TRAVEL_MAP_PG_DSN`이 **다른 두 이름**이었기 때문에
    # 둘이 문자열까지 같은지 확인하는 split-brain 검사가 필요했다. 이름이 하나가 된
    # 지금 그 검사는 변수를 자기 자신과 비교하는 항진명제라서 지웠다.
    dagster_runtime_dsn="${KOR_TRAVEL_MAP_PG_DSN:?KOR_TRAVEL_MAP_PG_DSN is required in production}"
    export KOR_TRAVEL_MAP_PG_DSN="$dagster_runtime_dsn"

    # ADR-100: 걷어낼 두 번째 DSN 이름이 없다 — `KOR_TRAVEL_MAP_PG_DSN`은 Dagster
    # resource가 읽어야 하므로 남는다.
  fi
  /usr/local/bin/python -I -m kortravelmap.dagster.runtime_preflight
}

storage_input_preflight() {
  # ADR-100: 애플리케이션 DSN을 이 metadata one-shot에서 차단하는 일은 아래
  # `KOR_TRAVEL_MAP_PG_DSN` 검사 하나로 충분하다 — 예전의 per-role 이름은 그 값의
  # 두 번째 통로였고, 통로가 하나가 된 지금 이 검사가 여전히 그것을 잡는다.
  if [ "${KOR_TRAVEL_MAP_PG_DSN+x}" = "x" ]; then
    echo "Dagster metadata migration forbids application runtime inputs" >&2
    exit 1
  fi
}

if [ "$dagster_profile" = "production" ]; then
  # production은 fixed image executable과 한 가지 argv 형상만 허용한다. bare PATH
  # lookup과 shell command override는 permit 뒤 다른 executable을 실행할 수 있으므로
  # Manager launch attestation 이전에도 image 안에서 fail-close한다.
  case "${1:-}" in
    /usr/local/bin/dagster-webserver)
      # ADR-069 짝: webserver는 code location을 더 이상 직접 import하지 않는다
      # (`-m`) — `dagster-code-server`가 유일한 code location 로더가 되고,
      # webserver는 workspace.yaml의 grpc_server로만 그것을 가리킨다(weather/geo/
      # transport와 같은 형태). argv 개수는 그대로 7개다.
      if [ "$#" -ne 7 ] \
        || [ "${2:-}" != "-w" ] \
        || [ "${3:-}" != "/opt/dagster/dagster_home/workspace.yaml" ] \
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
      # ADR-069 짝 — daemon도 더 이상 code location을 직접 import하지 않는다.
      # code location이 로드 가능한지의 신호는 이제 daemon 자신이 아니라
      # dagster-code-server 컨테이너다.
      if [ "$#" -ne 4 ] \
        || [ "${2:-}" != "run" ] \
        || [ "${3:-}" != "-w" ] \
        || [ "${4:-}" != "/opt/dagster/dagster_home/workspace.yaml" ]; then
        echo "production Dagster daemon argv does not match the sealed launch contract" >&2
        exit 1
      fi
      runtime_preflight
      ;;
    /usr/local/bin/dagster)
      # ADR-069 짝 — 실제 code location이 도는 유일한 프로세스. `DefaultRunLauncher`의
      # run worker는 이 프로세스의 자식으로 뜬다. gRPC에는 인증이 없으므로 `-h`는
      # loopback으로 고정한다(weather와 같은 이유 — Manager launch attestation
      # 이전에도 image 안에서 fail-close).
      if [ "$#" -ne 9 ] \
        || [ "${2:-}" != "api" ] \
        || [ "${3:-}" != "grpc" ] \
        || [ "${4:-}" != "-h" ] \
        || [ "${5:-}" != "127.0.0.1" ] \
        || [ "${6:-}" != "-p" ] \
        || [ "${8:-}" != "-m" ] \
        || [ "${9:-}" != "kortravelmap.dagster.definitions" ]; then
        echo "production Dagster code server argv does not match the sealed launch contract" >&2
        exit 1
      fi
      case "${7:-}" in
        "" | *[!0-9]*)
          echo "production Dagster code server port must be numeric" >&2
          exit 1
          ;;
      esac
      if [ "$7" -lt 1 ] || [ "$7" -gt 65535 ]; then
        echo "production Dagster code server port is outside 1..65535" >&2
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
    dagster | /usr/local/bin/dagster)
      if [ "${2:-}" = "api" ] && [ "${3:-}" = "grpc" ]; then
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
