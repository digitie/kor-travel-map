#!/bin/sh
set -eu

# production은 첫 external command보다 먼저 image의 interpreter/import/command
# resolution 경계를 고정한다. PATH override가 있으면 `sed` 등 credential-bearing
# child를 permit 전에 바꿔치기할 수 있으므로 값이 정확히 같아야 한다.
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
if [ "$api_profile" = "production" ] \
  && { [ "${PYTHONPATH+x}" = "x" ] \
    || [ "${PYTHONHOME+x}" = "x" ] \
    || [ "${PYTHONUSERBASE+x}" = "x" ]; }; then
  echo "production API forbids PYTHONPATH, PYTHONHOME, and PYTHONUSERBASE overrides" >&2
  exit 1
fi
if [ "$api_profile" = "production" ] \
  && [ "${PYTHONNOUSERSITE:-}" != "1" ]; then
  echo "production API requires PYTHONNOUSERSITE=1" >&2
  exit 1
fi
if [ "$api_profile" = "production" ] \
  && [ "${PATH:-}" != "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin" ]; then
  echo "production API requires the sealed runtime PATH" >&2
  exit 1
fi

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

# T-VN-M01 — 생성 전용 원문 token은 Next.js server runtime만 소유한다. set-but-empty도
# 배선 오류이므로 migration/settings import보다 먼저 API container 유입을 거부한다.
if [ "${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN+x}" = "x" ]; then
  echo "raw manual Feature create token must not enter API container" >&2
  exit 1
fi

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
ops_fixture_is_set="${KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN+x}"
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
if [ "$ops_read_is_set" != "$ops_cancel_is_set" ] \
  || [ "$ops_read_is_set" != "$ops_fixture_is_set" ]; then
  echo "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN, KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN, and KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN must be configured together" >&2
  exit 1
fi
if [ "$ops_read_is_set" != "x" ]; then
  if [ "$ops_principal_required" = "true" ]; then
    echo "ops principal is required but read/cancel/fixture tokens are absent" >&2
    exit 1
  fi
else
  ops_read_token="$KOR_TRAVEL_MAP_API_OPS_READ_TOKEN"
  ops_cancel_token="$KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN"
  ops_fixture_token="$KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN"
  if [ -z "$ops_read_token" ] && [ -z "$ops_cancel_token" ] && [ -z "$ops_fixture_token" ]; then
    if [ "$ops_principal_required" = "true" ]; then
      echo "ops principal is required but read/cancel/fixture tokens are empty" >&2
      exit 1
    fi
  elif [ -z "$ops_read_token" ] || [ -z "$ops_cancel_token" ] || [ -z "$ops_fixture_token" ]; then
    echo "ops read, cancel, and fixture tokens must all be empty or all be non-empty" >&2
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
    case "$ops_fixture_token" in
      *[[:space:]]*)
        echo "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN must contain no whitespace" >&2
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
    if [ "${#ops_fixture_token}" -lt 32 ]; then
      echo "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN must be at least 32 characters" >&2
      exit 1
    fi
    if [ "$ops_read_token" = "$ops_cancel_token" ] \
      || [ "$ops_read_token" = "$ops_fixture_token" ] \
      || [ "$ops_cancel_token" = "$ops_fixture_token" ]; then
      echo "ops read, cancel, and fixture tokens must be distinct" >&2
      exit 1
    fi
    if [ "$ops_read_token" = "$api_proxy_secret" ] || [ "$ops_cancel_token" = "$api_proxy_secret" ] \
      || [ "$ops_fixture_token" = "$api_proxy_secret" ]; then
      echo "ops read/cancel/fixture tokens must be distinct from the admin proxy secret" >&2
      exit 1
    fi
    if [ -n "$api_service_token" ]; then
      if [ "$ops_read_token" = "$api_service_token" ] || [ "$ops_cancel_token" = "$api_service_token" ] \
        || [ "$ops_fixture_token" = "$api_service_token" ]; then
        echo "ops read/cancel/fixture tokens must be distinct from the service token" >&2
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
# profile 값과 production interpreter/PATH 경계는 첫 external command보다 앞에서
# 이미 검증했다.
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
if [ "$ops_read_is_set" = "x" ] && [ -n "${KOR_TRAVEL_MAP_API_OPS_READ_TOKEN}" ] \
  && [ -n "${KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN}" ]; then
  ops_pair_configured=true
fi
if [ "$api_profile" = "production" ] && [ "$ops_routes_enabled" = "true" ] \
  && [ "$ops_pair_configured" = "false" ]; then
  echo "production profile is fail-closed (ADR-066): KOR_TRAVEL_MAP_API_OPS_READ_TOKEN, KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN, and KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN must be configured while the ops surface is enabled" >&2
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
      || [ "$cursor_signing_secret" = "$KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN" ] \
      || [ "$cursor_signing_secret" = "$KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN" ]; }; then
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

# T-VN-M01 — production은 kill-switch=false인 사전 provision 단계에서도 digest를
# 요구한다. local-dev도 route를 켜거나 digest를 넣은 순간 같은 형태 검증을 받는다.
manual_feature_create_flag="${KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED:-false}"
case "$manual_feature_create_flag" in
  true | false) ;;
  *)
    echo "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED must be exactly true or false" >&2
    exit 1
    ;;
esac
manual_feature_create_digest="${KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256:-}"
manual_feature_create_digest_required=false
if [ "$api_profile" = "production" ] || [ "$manual_feature_create_flag" = "true" ]; then
  manual_feature_create_digest_required=true
fi
if [ "$manual_feature_create_digest_required" = "true" ] \
  && [ -z "$manual_feature_create_digest" ]; then
  echo "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 must be configured" >&2
  exit 1
fi
if [ -n "$manual_feature_create_digest" ]; then
  case "$manual_feature_create_digest" in
    *[!0-9a-f]*)
      echo "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 must be lowercase SHA-256 hex" >&2
      exit 1
      ;;
  esac
  if [ "${#manual_feature_create_digest}" -ne 64 ]; then
    echo "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 must be lowercase SHA-256 hex" >&2
    exit 1
  fi
fi

# Shell은 raw 미유입과 단순 형태를 먼저 닫고, API settings 정본이 digest와 기존
# credential/curation/cache-target 분리를 재검증한다. 예외 본문은 secret input을
# 포함할 수 있어 밖으로 출력하지 않는다. 이 preflight는 alembic보다 반드시 앞선다.
if ! /usr/local/bin/python -I - <<'PY'
from __future__ import annotations

import sys

from kortravelmap.api.settings import ApiSettings

try:
    ApiSettings()
except (TypeError, ValueError):
    print("API runtime settings credential preflight failed", file=sys.stderr)
    raise SystemExit(1)
PY
then
  exit 1
fi
unset \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED

# schema 변경이 **컨테이너 기동의 부수효과**로 일어나는 것에 대한 방어.
#
# 2026-08-03 prod 사고: pin(`map_release_revision`)은 목표 revision을 가리키는데 실제로는
# alembic chain이 `0072`까지만 담긴 옛 이미지가 배포됐다. 이 스크립트가 조건 없이
# `alembic upgrade head`를 돌려 prod schema를 `0063` -> `0072`로 올린 뒤 **오류 없이**
# 끝냈다. 그 이미지 기준으로는 head까지 간 것이 맞기 때문이다. 그런데 `0072`는 공개
# 큐레이션 링크를 신뢰 불가 상태로 두고 `0073`이 그것을 복구하는 구조라, 공개 표면이
# 0건이 됐다.
#
# KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD — 이미지가 담은 migration chain의 head가
# 기대값과 다르면 **마이그레이션 전에** 죽는다. DB를 건드리지 않으므로 중간 상태가
# 생기지 않는다. 위 사고는 이 값만 넣었으면 잡혔다. 이 게이트는 chain만 검증한다 —
# head가 우연히 같은 stale 이미지는 image↔pin 대조(배포측 몫)가 잡아야 한다.
#
# 배포측 결선이 없으면 게이트는 꺼진 것과 같다. 표준 compose는 이 값을 넣지 않으며
# (local-dev는 필요 없음), production 결선은 배포 orchestrator(docker-manager) compose가
# 명시 값으로 소유한다.
#
# MODE=none(orchestrator 소유 migration)은 도입 직후 제거됐다 — 명분이던 H35 typed
# helper가 같은 사고 대응에서 사문화됐고(tasks.md 재정의), 소비자 없는 fail-open
# 스위치만 남기 때문이다(적대 리뷰 F2). 설정돼 있으면 조용히 무시하지 않고 거부한다.
if [ "${KOR_TRAVEL_MAP_MIGRATION_MODE+x}" = "x" ]; then
  echo "KOR_TRAVEL_MAP_MIGRATION_MODE was removed; startup migration is always on" >&2
  exit 1
fi

runtime_dsn="${KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN:?KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN is required}"
if [ "$api_profile" = "production" ]; then
  # Production API는 migration을 소유하지 않는다. Manager one-shot만 migrator DSN을
  # 받고, consumer container는 set-but-empty까지 fail-close한다.
  if [ "${KOR_TRAVEL_MAP_MIGRATOR_PG_DSN+x}" = "x" ]; then
    echo "production API forbids KOR_TRAVEL_MAP_MIGRATOR_PG_DSN" >&2
    exit 1
  fi
  export KOR_TRAVEL_MAP_PG_DSN="$runtime_dsn"
  unset KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE
else
  # local-dev의 명시적 developer launcher만 legacy convenience migration을 유지한다.
  # fresh production과 controlled handoff는 이 분기를 사용하지 않는다.
  migrator_dsn="${KOR_TRAVEL_MAP_MIGRATOR_PG_DSN:?KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required in local-dev}"
  export KOR_TRAVEL_MAP_PG_DSN="$migrator_dsn"
  export KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true
fi

# set-but-empty는 거부한다 — 위 profile 검사와 같은 규약이다. compose `${HOST:-}`
# 패턴에서 host env 누락이 조용한 게이트 해제가 되면 안 된다.
if [ "${KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD+x}" = "x" ]; then
  expected_head="$KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD"
  if [ -z "$expected_head" ]; then
    echo "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD is set but empty; refusing to silently disable the head gate" >&2
    exit 1
  fi
else
  expected_head=""
fi

if [ -n "$expected_head" ]; then
  # `alembic heads`는 script 디렉터리만 읽는다 — DB 연결 전에 판정할 수 있다.
  # 주의: alembic은 CommandError를 **stdout**에 쓰고 비정상 종료한다(stderr 아님).
  # 출력 내용이 아니라 exit code로 실행 실패를 먼저 판정해야 오진 메시지가 나가지 않는다.
  if ! heads_raw="$(/usr/local/bin/python -I -m alembic heads 2>/dev/null)"; then
    echo "alembic heads failed; the image alembic configuration is broken" >&2
    echo "(cannot evaluate KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD; the DB was not touched)" >&2
    printf '%s\n' "$heads_raw" >&2
    exit 1
  fi
  image_heads="$(printf '%s\n' "$heads_raw" | awk 'NF {print $1}')"
  if [ -z "$image_heads" ]; then
    echo "alembic heads printed nothing (cannot evaluate KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD)" >&2
    exit 1
  fi
  head_count="$(printf '%s\n' "$image_heads" | grep -c '^')"
  if [ "$head_count" != "1" ]; then
    echo "the image has more than one alembic head: $(printf '%s' "$image_heads" | tr '\n' ' ')" >&2
    exit 1
  fi
  if [ "$image_heads" != "$expected_head" ]; then
    echo "the image alembic head does not match the expected head" >&2
    echo "  expected: ${expected_head}" >&2
    echo "  image:    ${image_heads}" >&2
    echo "the deployed image was not built with the intended migration chain; the DB was not touched" >&2
    exit 1
  fi
fi

if [ "$api_profile" = "production" ]; then
  # production runtime은 Manager final permit 없이 DB를 mutation하지 않는다. final
  # permit verifier가 이 API runtime DSN에서 candidate/DB identity와 exact raw ``300``을
  # 한 번에 확인한다. 그 뒤 migrator DSN으로 별도 `alembic current`를 읽으면 서로 다른
  # DB가 각각 통과하는 split-brain이 생기므로 production에는 generic Alembic probe가 없다.
  if [ "$expected_head" != "300" ]; then
    echo "production API requires KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=300" >&2
    exit 1
  fi
  if ! /usr/local/bin/python -I \
    /usr/local/bin/ktm-application-schema-final-permit verify-api; then
    echo "production API requires a valid Docker Manager application final permit" >&2
    exit 1
  fi
else
# `300` image는 local-dev fresh DB 또는 raw `300`만 generic startup으로 처리한다. `0236`은
# active graph 밖의 퇴역 revision이며 in-place stamp/upgrade를 지원하지 않는다.
if ! current_raw="$(/usr/local/bin/python -I -m alembic current 2>&1)"; then
  case "$current_raw" in
    *"Can't locate revision"*)
      db_revision="$(printf '%s' "$current_raw" | sed -n 's/.*Can'"'"'t locate revision identified by '"'"'\([^'"'"']*\)'"'"'.*/\1/p' | head -1)"
      if [ "$db_revision" = "0236_tvn41s_compaction_drained" ]; then
        echo "the DB is at unsupported retired revision 0236; in-place transition is not available" >&2
        echo "use only the approved destructive fresh rebuild path for application 300" >&2
      else
        echo "the DB Alembic revision is unsupported by the active 300-only image" >&2
        echo "(raw revision: ${db_revision:-unknown}; no archive replay, downgrade, or manual version-table edit is supported)" >&2
      fi
      printf '%s\n' "$current_raw" >&2
      exit 1
      ;;
  esac
fi

retries="${KOR_TRAVEL_MAP_MIGRATION_RETRIES:-30}"
sleep_seconds="${KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS:-2}"
attempt=1

# `0236` source와 알 수 없는 active-graph 밖 revision은 위에서 retry 전에 거부한다.
# 여기서는 일시 연결 오류만 bounded retry로 흡수한다. (POSIX sh — process substitution 없음.)
upgrade_log="$(mktemp)"
trap 'rm -f "$upgrade_log"' EXIT
while ! /usr/local/bin/python -I -m alembic upgrade head 2>"$upgrade_log"; do
  cat "$upgrade_log" >&2
  if [ "$attempt" -ge "$retries" ]; then
    echo "alembic upgrade head failed after $attempt attempts" >&2
    exit 1
  fi
  echo "alembic upgrade head failed; retrying ($attempt/$retries)" >&2
  attempt=$((attempt + 1))
  sleep "$sleep_seconds"
done
cat "$upgrade_log" >&2
rm -f "$upgrade_log"
trap - EXIT

# Ownership transfer strips legacy bootstrap ACLs.  Rebuild the closed runtime
# inventory with the migrator-only SET ROLE path before this shell discards its
# credential; default privileges are intentionally not used for feature state
# or audit objects.
/usr/local/bin/python -I -m kortravelmap.infra.runtime_privileges
fi

# Uvicorn과 그 자식에는 runtime credential만 남긴다. migration credential은
# application code·request handler가 읽을 수 없게 exec 직전에 제거한다.
export KOR_TRAVEL_MAP_PG_DSN="$runtime_dsn"
unset KOR_TRAVEL_MAP_MIGRATOR_PG_DSN
unset KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN
unset KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE
export KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="$manual_feature_create_digest"
export KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED="$manual_feature_create_flag"

exec /usr/local/bin/python -I -m uvicorn kortravelmap.api.app:app \
  --host 0.0.0.0 \
  --port "${KOR_TRAVEL_MAP_API_PORT:-12701}"
