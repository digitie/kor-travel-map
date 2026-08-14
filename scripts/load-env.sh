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

export KOR_TRAVEL_MAP_API_HOST="${KOR_TRAVEL_MAP_API_HOST:-127.0.0.1}"
export KOR_TRAVEL_MAP_API_PORT="${KOR_TRAVEL_MAP_API_PORT:-12701}"
export KOR_TRAVEL_MAP_ADMIN_WEB_PORT="${KOR_TRAVEL_MAP_ADMIN_WEB_PORT:-12705}"
export KOR_TRAVEL_MAP_DAGSTER_PORT="${KOR_TRAVEL_MAP_DAGSTER_PORT:-12702}"
export KOR_TRAVEL_MAP_POSTGRES_HOST_PORT="${KOR_TRAVEL_MAP_POSTGRES_HOST_PORT:-5432}"
export KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT="${KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT:-5432}"
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
# geo **소비자** 키는 VWorld 키로 떨어지지 않는다. VWorld 키는 kor-travel-geo가 상류로
# 나갈 때 쓰는 것이고, geo는 그 값을 401(E0401)로 거절한다. 두 이름이 같은 사슬에 있으면
# "설정이 있다"는 착시만 만들고 실패를 첫 요청 시점까지 미룬다 — 2026-08-13 prod에서
# 정확히 그렇게 dagster/daemon이 죽은 키를 들고 있었다(T-VN-H46B).
# 두 이름은 **같은 geo 소비자 자격증명의 별칭**이므로 양방향으로 채운다. 한 방향만
# 두면 `.env.example`이 시키는 대로 `KOR_TRAVEL_MAP_…`만 설정한 개발자의 admin UI가
# 키 없이 뜬다(적대 리뷰 지적). `export_first`는 target이 이미 있으면 그대로 두므로
# 두 줄이 서로를 덮지 않는다.
export_first NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY \
  KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY
export_first KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY \
  NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY
# 별칭이라고 적어 두기만 하면 강제되지 않는다. 키 회전에서 한쪽만 고치면 backend ETL은
# 초록인데 admin UI만 401이 되고 아무도 모른다 — 2026-08-13 사고와 같은 모양이 한 겹
# 위에서 재현된다. (marker: geo_alias_split_brain)
#
# **여기서 exit 하지 않는다.** 이 파일은 항상 `source`되므로(`docker-up.sh`·
# `docker-buildx.sh`·`docker-restore-swap.sh` …) exit는 호출 스크립트를 끝내고,
# 대화형 셸에서는 터미널을 닫는다 — `docker-restore-swap.sh`가 복구 도중 운영자에게
# `source scripts/load-env.sh`를 지시하는데 거기서 그러면 안 된다(적대 리뷰 지적).
# 그리고 서는 것은 이 파일의 우선순위 모델과도 모순이다: `load_env_file`은 다른 모든
# 변수에 대해 `.env`가 주변 env를 **덮는다**. 같은 규칙을 적용해 정본 이름으로 정렬하고
# 경고만 남긴다.
if [[ -n "${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:-}" \
   && -n "${NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY:-}" \
   && "${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY}" != "${NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY}" ]]; then
  echo "load-env: geo_alias_split_brain — KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY와" \
       "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY가 서로 다른 값이다. 둘은 같은 자격증명의" \
       "별칭이므로 한쪽만 회전하면 admin UI만 401이 된다." \
       "정본(KOR_TRAVEL_MAP_…) 값으로 맞춘다." >&2
  export NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY="$KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY"
fi
export_first KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY \
  KAKAO_LOCAL_REST_API_KEY
export_first KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID \
  NAVER_SEARCH_CLIENT_ID
export_first KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET \
  NAVER_SEARCH_CLIENT_SECRET
export_first KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY \
  GOOGLE_PLACES_API_KEY
