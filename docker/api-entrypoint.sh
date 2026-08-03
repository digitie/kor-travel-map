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
api_service_token="${KOR_TRAVEL_MAP_API_SERVICE_TOKEN:-}"
if [ -n "$api_service_token" ] && [ "$api_service_token" = "$api_proxy_secret" ]; then
  echo "KOR_TRAVEL_MAP_API_SERVICE_TOKEN must be distinct from KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" >&2
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
    if [ -n "$api_service_token" ]; then
      if [ "$ops_read_token" = "$api_service_token" ] || [ "$ops_cancel_token" = "$api_service_token" ]; then
        echo "ops read/cancel tokens must be distinct from the service token" >&2
        exit 1
      fi
    fi
  fi
fi

# ADR-066 T-VN-02/T-VN-03 (#742) — 검증 정본은 settings production matrix
# (ApiSettings.assert_production_ready)다. 그중 "production + ops surface 활성 +
# ops pair 미구성"은 migration이 이미 실행된 뒤 uvicorn 기동에서야 실패해
# 2단계 혼란을 만들므로, 같은 문구로 migration 전에 거부한다(메시지 lockstep).
# 이 ops surface에는 datasets/pipeline뿐 아니라 metrics/log/consistency/deep-health
# 관측 read도 포함하며 모두 같은 read principal pair를 사용한다.
# profile 기본값은 Docker image ENV(production)와 같다. set-but-empty를 조용히
# production으로 접지 않도록 set-vs-unset(+x)로 판정한다 — compose는 막지만
# 직접 ``docker run``은 빈 값을 넘길 수 있고 settings도 빈 문자열을 거부한다.
if [ "${KOR_TRAVEL_MAP_API_PROFILE+x}" = "x" ]; then
  api_profile="$KOR_TRAVEL_MAP_API_PROFILE"
else
  api_profile="production"
fi
case "$api_profile" in
  production | local-dev) ;;
  *)
    echo "KOR_TRAVEL_MAP_API_PROFILE must be exactly production or local-dev" >&2
    exit 1
    ;;
esac
for flag_name in KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED; do
  eval "flag_is_set=\${$flag_name+x}"
  if [ "$flag_is_set" = "x" ]; then
    eval "flag_value=\$$flag_name"
    case "$flag_value" in
      true | false) ;;
      *)
        echo "$flag_name must be exactly true or false" >&2
        exit 1
        ;;
    esac
  fi
done
features_routes_enabled="${KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED:-true}"
ops_routes_enabled="${KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED:-$features_routes_enabled}"
ops_pair_configured=false
if [ "$ops_read_is_set" = "x" ] && [ -n "${KOR_TRAVEL_MAP_API_OPS_READ_TOKEN}" ]; then
  ops_pair_configured=true
fi
if [ "$api_profile" = "production" ] && [ "$ops_routes_enabled" = "true" ] \
  && [ "$ops_pair_configured" = "false" ]; then
  echo "production profile is fail-closed (ADR-066): KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be configured while the ops surface is enabled" >&2
  exit 1
fi

# T-VN-15 — search cursor signing secret은 인증 credential과 분리한다. production
# features surface는 migration 전에 누락을 거부하고, 설정된 값은 profile과 무관하게
# 공백 없는 32자 이상이어야 한다. local-dev 미설정만 process-local fallback을 쓴다.
cursor_signing_secret="${KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET:-}"
if [ "$api_profile" = "production" ] && [ "$features_routes_enabled" = "true" ] \
  && [ -z "$cursor_signing_secret" ]; then
  echo "production profile is fail-closed (ADR-066): KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be configured while the public features surface is enabled" >&2
  exit 1
fi
if [ -n "$cursor_signing_secret" ]; then
  case "$cursor_signing_secret" in
    *[[:space:]]*)
      echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must contain no whitespace" >&2
      exit 1
      ;;
  esac
  if [ "${#cursor_signing_secret}" -lt 32 ]; then
    echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be at least 32 characters" >&2
    exit 1
  fi
  if [ "$cursor_signing_secret" = "$api_proxy_secret" ] \
    || { [ -n "$api_service_token" ] && [ "$cursor_signing_secret" = "$api_service_token" ]; }; then
    echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be distinct from admin and service credentials" >&2
    exit 1
  fi
  if [ "$ops_pair_configured" = "true" ] \
    && { [ "$cursor_signing_secret" = "$KOR_TRAVEL_MAP_API_OPS_READ_TOKEN" ] \
      || [ "$cursor_signing_secret" = "$KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN" ]; }; then
    echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be distinct from ops credentials" >&2
    exit 1
  fi
  api_metrics_token="${KOR_TRAVEL_MAP_API_METRICS_TOKEN:-}"
  if [ -n "$api_metrics_token" ] && [ "$cursor_signing_secret" = "$api_metrics_token" ]; then
    echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be distinct from the metrics credential" >&2
    exit 1
  fi
  api_public_key="${KOR_TRAVEL_MAP_API_VWORLD_API_KEY:-}"
  if [ -n "$api_public_key" ] && [ "$cursor_signing_secret" = "$api_public_key" ]; then
    echo "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be distinct from the public API key" >&2
    exit 1
  fi
fi

# schema 변경이 **컨테이너 기동의 부수효과**로 일어나는 것을 막는다.
#
# 2026-08-03 prod 사고: pin(`map_release_revision`)은 목표 revision을 가리키는데 실제로는
# alembic chain이 `0072`까지만 담긴 옛 이미지가 배포됐다. 이 스크립트가 조건 없이
# `alembic upgrade head`를 돌려 prod schema를 `0063` -> `0072`로 올린 뒤 **오류 없이**
# 끝냈다. 그 이미지 기준으로는 head까지 간 것이 맞기 때문이다. 그런데 `0072`는 공개
# 큐레이션 링크를 신뢰 불가 상태로 두고 `0073`이 그것을 복구하는 구조라, 공개 표면이
# 0건이 됐다.
#
# 두 가지 통제를 둔다.
#   EXPECTED_HEAD  이미지가 담은 head가 기대값과 다르면 **마이그레이션 전에** 죽는다.
#                  DB를 건드리지 않으므로 중간 상태가 생기지 않는다. 위 사고는 이 값만
#                  넣었으면 잡혔다.
#   MODE=none      orchestrator(H35 typed helper 등)가 마이그레이션을 소유할 때 끈다.
#                  기동이 schema를 바꾸지 않아야 receipt 계약이 의미를 갖는다.
migration_mode="${KOR_TRAVEL_MAP_MIGRATION_MODE:-auto}"
expected_head="${KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD:-}"

if [ -n "$expected_head" ]; then
  # `alembic heads`는 script 디렉터리만 읽는다 — DB 연결 전에 판정할 수 있다.
  image_heads="$(alembic heads 2>/dev/null | awk 'NF {print $1}')"
  head_count="$(printf '%s' "$image_heads" | grep -c '^' 2>/dev/null || echo 0)"
  if [ -z "$image_heads" ]; then
    echo "alembic heads를 읽지 못했습니다 (KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD 검사 불가)" >&2
    exit 1
  fi
  if [ "$head_count" != "1" ]; then
    echo "이미지의 alembic head가 하나가 아닙니다: $(printf '%s' "$image_heads" | tr '\n' ' ')" >&2
    exit 1
  fi
  if [ "$image_heads" != "$expected_head" ]; then
    echo "이미지의 alembic head가 기대값과 다릅니다." >&2
    echo "  기대: ${expected_head}" >&2
    echo "  이미지: ${image_heads}" >&2
    echo "배포된 이미지가 의도한 revision으로 빌드되지 않았습니다. DB는 건드리지 않았습니다." >&2
    exit 1
  fi
fi

case "$migration_mode" in
  none)
    echo "KOR_TRAVEL_MAP_MIGRATION_MODE=none — alembic upgrade를 건너뜁니다" >&2
    ;;
  auto)
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
    ;;
  *)
    echo "KOR_TRAVEL_MAP_MIGRATION_MODE는 auto 또는 none이어야 합니다: ${migration_mode}" >&2
    exit 1
    ;;
esac

exec python -m uvicorn kortravelmap.api.app:app \
  --host 0.0.0.0 \
  --port "${KOR_TRAVEL_MAP_API_PORT:-12701}"
