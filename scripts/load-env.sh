#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${KOR_TRAVEL_MAP_ENV_FILE:-"$ROOT_DIR/.env"}"

load_env_file() {
  local line key value first last
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    if [[ "$line" == export\ * ]]; then
      line="${line#export }"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ ${#value} -ge 2 ]]; then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ "$first$last" == '""' || "$first$last" == "''" ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$key=$value"
  done <"$1"
}

if [[ -f "$ENV_FILE" ]]; then
  load_env_file "$ENV_FILE"
fi

reject_exported_manual_feature_create_aliases() {
  local manual_raw="$1"
  local manual_digest="$2"
  local exported_name exported_value
  while IFS= read -r exported_name; do
    case "$exported_name" in
      KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN | \
        KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 | \
        KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED)
        continue
        ;;
    esac
    exported_value="${!exported_name:-}"
    if [[ -n "$exported_value" \
      && ( ( -n "$manual_raw" && "$exported_value" == *"$manual_raw"* ) \
        || ( -n "$manual_digest" \
          && "$exported_value" == *"$manual_digest"* ) ) ]]; then
      echo "manual Feature create credentials must be distinct from exported environment values" >&2
      return 1
    fi
  done < <(compgen -e)
}

export KOR_TRAVEL_MAP_API_HOST="${KOR_TRAVEL_MAP_API_HOST:-127.0.0.1}"
export KOR_TRAVEL_MAP_API_PORT="${KOR_TRAVEL_MAP_API_PORT:-12701}"
export KOR_TRAVEL_MAP_ADMIN_WEB_PORT="${KOR_TRAVEL_MAP_ADMIN_WEB_PORT:-12705}"
export KOR_TRAVEL_MAP_DAGSTER_PORT="${KOR_TRAVEL_MAP_DAGSTER_PORT:-12702}"
export KOR_TRAVEL_MAP_POSTGRES_HOST_PORT="${KOR_TRAVEL_MAP_POSTGRES_HOST_PORT:-5432}"
# KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT는 2026-08-17에 없앴다 — export만 하고
# 읽는 곳이 없어서 override해도 접속 대상이 안 바뀌는 손잡이였다. 공유 DB 모드의
# 포트는 external overlay가 주입하는 `..._PG_DSN` 문자열 안에 있다.
export KOR_TRAVEL_MAP_POSTGRES_DB="${KOR_TRAVEL_MAP_POSTGRES_DB:-kor_travel_map}"
export KOR_TRAVEL_MAP_POSTGRES_USER="${KOR_TRAVEL_MAP_POSTGRES_USER:-kor_travel_map}"
export KOR_TRAVEL_MAP_POSTGRES_PASSWORD="${KOR_TRAVEL_MAP_POSTGRES_PASSWORD:-}"
export KOR_TRAVEL_MAP_RUSTFS_API_PORT="${KOR_TRAVEL_MAP_RUSTFS_API_PORT:-12101}"
export KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT="${KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT:-12105}"
export KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB="${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB:-kor_travel_map_dagster}"
# T-VN-34A / ADR-090 — bootstrap owner에서 application DSN을 유도하지 않는다.
# 호출자가 필요한 한 principal의 DSN을 ignored deployment env/vault에서 명시한다.
# 빈 default조차 export하지 않아 누락은 compose/service의 required gate에서 실패한다.
if [[ -n "${KOR_TRAVEL_MAP_PG_DSN:-}" ]]; then
  export KOR_TRAVEL_MAP_PG_DSN
fi
if [[ -n "${KOR_TRAVEL_MAP_PG_DSN_SYNC:-}" ]]; then
  export KOR_TRAVEL_MAP_PG_DSN_SYNC
fi
if [[ -n "${KOR_TRAVEL_MAP_DAGSTER_PG_URL:-}" ]]; then
  export KOR_TRAVEL_MAP_DAGSTER_PG_URL
fi
if [[ -n "${KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL:-}" ]]; then
  export KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL
fi

export KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL="${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL:-http://127.0.0.1:12501}"
export KOR_TRAVEL_MAP_API_DAGSTER_URL="${KOR_TRAVEL_MAP_API_DAGSTER_URL:-http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}}"
export KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS="${KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS:-[\"127.0.0.1\",\"localhost\",\"::1\",\"dagster\"]}"
export KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL="${KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL:-http://dagster:${KOR_TRAVEL_MAP_DAGSTER_PORT}}"
export KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_ALLOWED_HOSTS="${KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_ALLOWED_HOSTS:-[\"dagster\",\"127.0.0.1\",\"localhost\",\"::1\"]}"
export KOR_TRAVEL_MAP_OBJECT_STORE_ENDPOINT_URL="${KOR_TRAVEL_MAP_OBJECT_STORE_ENDPOINT_URL:-http://127.0.0.1:${KOR_TRAVEL_MAP_RUSTFS_API_PORT}}"
export KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET="${KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET:-kor-travel-map}"
export KOR_TRAVEL_MAP_OBJECT_STORE_REGION="${KOR_TRAVEL_MAP_OBJECT_STORE_REGION:-us-east-1}"
export KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID="${KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID:-kor-travel-map-dev-access}"
export KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY="${KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY:-kor-travel-map-dev-secret}"
export KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL="${KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL:-http://127.0.0.1:${KOR_TRAVEL_MAP_RUSTFS_API_PORT}/${KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET}}"
export KOR_TRAVEL_MAP_OBJECT_STORE_PREFIX="${KOR_TRAVEL_MAP_OBJECT_STORE_PREFIX:-features}"
export KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET="${KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET:-kor-travel-map-uploads}"
export KOR_TRAVEL_MAP_OFFLINE_UPLOAD_PREFIX="${KOR_TRAVEL_MAP_OFFLINE_UPLOAD_PREFIX:-offline-uploads}"
export KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES="${KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES:-104857600}"
export KOR_TRAVEL_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL="${KOR_TRAVEL_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL:-http://rustfs:9000}"
export DAGSTER_DISABLE_TELEMETRY="${DAGSTER_DISABLE_TELEMETRY:-yes}"
# docker build secret(github_token, #370) — 미설정이어도 compose가 unset env로
# 실패하지 않게 빈 값을 보장한다. private provider pin fetch 시에만 실 토큰 필요.
export GITHUB_TOKEN="${GITHUB_TOKEN:-}"
export NEXT_PUBLIC_KOR_TRAVEL_MAP_API="${NEXT_PUBLIC_KOR_TRAVEL_MAP_API:-http://127.0.0.1:${KOR_TRAVEL_MAP_API_PORT}}"
export NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL="${NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL:-http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}}"
export NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL="${NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL:-${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL}}"

export_first() {
  local target="$1"
  shift
  local current="${!target:-}"
  if [[ -n "$current" ]]; then
    export "$target=$current"
    return 0
  fi

  local name value
  for name in "$@"; do
    value="${!name:-}"
    if [[ -n "$value" ]]; then
      export "$target=$value"
      return 0
    fi
  done
}

# Next.js BFF의 server runtime alias다. browser-global 이름이나 VWorld provider key는
# source가 될 수 없다.
export_first KOR_TRAVEL_GEO_API_KEY \
  KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY

export_first KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY \
  DATA_GO_KR_SERVICE_KEY DATAGOKR_API_KEY PUBLIC_DATA_SERVICE_KEY SERVICE_KEY
export_first KOR_TRAVEL_MAP_OPINET_API_KEY \
  OPINET_API_KEY OPINET_SERVICE_KEY
export_first KOR_TRAVEL_MAP_KREX_EX_API_KEY \
  KEX_GO_API_KEY KREX_API_KEY KREX_SERVICE_KEY
export_first KOR_TRAVEL_MAP_KREX_GO_API_KEY \
  DATA_GO_KR_SERVICE_KEY KEX_GO_API_KEY KREX_API_KEY KREX_SERVICE_KEY

export_first NEXT_PUBLIC_VWORLD_API_KEY \
  KOR_TRAVEL_GEO_VWORLD_API_KEY VWORLD_API_KEY
export_first KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY \
  KAKAO_LOCAL_REST_API_KEY
export_first KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID \
  NAVER_SEARCH_CLIENT_ID
export_first KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET \
  NAVER_SEARCH_CLIENT_SECRET
export_first KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY \
  GOOGLE_PLACES_API_KEY
