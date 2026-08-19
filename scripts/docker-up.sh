#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

API_ENV_FILE="${KOR_TRAVEL_MAP_API_ENV_FILE:-$ROOT_DIR/packages/kor-travel-map-api/.env}"
FRONTEND_ENV_FILE="${KOR_TRAVEL_MAP_FRONTEND_ENV_FILE:-$ROOT_DIR/packages/kor-travel-map-admin/frontend/.env.local}"

SCOPED_ENV_FOUND=0
SCOPED_ENV_VALUE=""
read_scoped_env_key() {
  local file="$1"
  local wanted_key="$2"
  local line key value first last
  SCOPED_ENV_FOUND=0
  SCOPED_ENV_VALUE=""
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    [[ "$key" == "$wanted_key" ]] || continue
    if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
      echo "duplicate key in scoped env: $wanted_key" >&2
      exit 1
    fi
    value="${line#*=}"
    if [[ ${#value} -ge 2 ]]; then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ "$first$last" == '\"\"' || "$first$last" == "''" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" =~ [[:space:]]# ]]; then
        echo "inline comments are not allowed in scoped env values: $wanted_key" >&2
        exit 1
      fi
    fi
    SCOPED_ENV_FOUND=1
    SCOPED_ENV_VALUE="$value"
  done <"$file"
}

scoped_env_has_key() {
  local file="$1"
  local wanted_key="$2"
  local line key
  [[ -f "$file" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    if [[ "$line" =~ ^export[[:space:]]+ ]]; then
      line="${line:${#BASH_REMATCH[0]}}"
    fi
    key="${line%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" == "$wanted_key" ]] && return 0
  done <"$file"
  return 1
}

scoped_env_contains_value() {
  local file="$1"
  local protected_value="$2"
  local line
  [[ -n "$protected_value" && -f "$file" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == *"$protected_value"* ]] && return 0
  done <"$file"
  return 1
}

reject_manual_create_key_in_root_env() {
  local key="$1"
  local root_env_file
  for root_env_file in "$ENV_FILE" "$ROOT_DIR/.env"; do
    if scoped_env_has_key "$root_env_file" "$key"; then
      echo "$key must not be configured in root env because Dagster reads that file" >&2
      exit 1
    fi
  done
}

export_scoped_env_key() {
  local file="$1"
  local key="$2"
  local default_value="${3-}"
  if [[ -v "$key" ]]; then
    export "$key"
    return 0
  fi
  read_scoped_env_key "$file" "$key"
  if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
    export "$key=$SCOPED_ENV_VALUE"
  else
    export "$key=$default_value"
  fi
}

validate_manual_feature_create_credentials() {
  local raw_name=KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN
  local digest_name=KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256
  local flag_name=KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED
  local raw="${!raw_name:-}"
  local digest="${!digest_name:-}"
  local flag="${!flag_name:-false}"
  local computed protected_name protected_value

  if [[ "$flag" != "true" && "$flag" != "false" ]]; then
    echo "$flag_name must be exactly true or false" >&2
    exit 1
  fi
  if [[ ${#raw} -lt 32 || "$raw" =~ [[:space:]] ]]; then
    echo "$raw_name must be at least 32 characters and contain no whitespace" >&2
    exit 1
  fi
  if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "$digest_name must be lowercase SHA-256 hex" >&2
    exit 1
  fi
  computed="$(printf '%s' "$raw" | sha256sum)"
  computed="${computed%% *}"
  if [[ "$computed" != "$digest" ]]; then
    echo "manual Feature create raw token SHA-256 must match the API digest" >&2
    exit 1
  fi

  for protected_name in \
    KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET \
    KOR_TRAVEL_MAP_API_SERVICE_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_READ_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN \
    KOR_TRAVEL_MAP_API_METRICS_TOKEN; do
    protected_value="${!protected_name:-}"
    if [[ -n "$protected_value" && "$raw" == "$protected_value" ]]; then
      echo "manual Feature create credential must be distinct from existing credentials" >&2
      exit 1
    fi
  done
  while IFS= read -r protected_name; do
    protected_value="${!protected_name:-}"
    if [[ -n "$protected_value" \
      && ( "$protected_value" == *"$raw"* \
        || "$protected_value" == *"$digest"* ) ]]; then
      echo "manual Feature create credentials must be distinct from public frontend values" >&2
      exit 1
    fi
  done < <(compgen -A variable NEXT_PUBLIC_)
  for protected_name in \
    KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256 \
    KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256; do
    protected_value="${!protected_name:-}"
    if [[ -n "$protected_value" && "$digest" == "$protected_value" ]]; then
      echo "manual Feature create digest must be distinct from curation credentials" >&2
      exit 1
    fi
  done
  protected_value="${KOR_TRAVEL_MAP_API_CACHE_TARGET_SERVICE_PRINCIPALS:-}"
  if [[ -n "$protected_value" && "$protected_value" == *"$digest"* ]]; then
    echo "manual Feature create digest must be distinct from cache-target credentials" >&2
    exit 1
  fi
}

for manual_create_key in \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  reject_manual_create_key_in_root_env "$manual_create_key"
done
for manual_create_api_env_file in \
  "$API_ENV_FILE" \
  "$ROOT_DIR/packages/kor-travel-map-api/.env"; do
  if scoped_env_has_key \
    "$manual_create_api_env_file" \
    KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN; then
    echo "raw manual Feature create token is not allowed in API env" >&2
    exit 1
  fi
done
export_scoped_env_key "$FRONTEND_ENV_FILE" KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN
export_scoped_env_key "$API_ENV_FILE" KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256
export_scoped_env_key "$API_ENV_FILE" KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED false
validate_manual_feature_create_credentials
manual_create_raw="$KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"
manual_create_digest="$KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256"
manual_create_flag="$KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED"
reject_exported_manual_feature_create_aliases \
  "$manual_create_raw" \
  "$manual_create_digest"
for manual_create_root_env_file in "$ENV_FILE" "$ROOT_DIR/.env"; do
  if scoped_env_contains_value "$manual_create_root_env_file" "$manual_create_raw" \
    || scoped_env_contains_value \
      "$manual_create_root_env_file" \
      "$manual_create_digest"; then
    echo "manual Feature create credentials must not appear in root/Dagster env" >&2
    exit 1
  fi
done
for manual_create_api_env_file in \
  "$API_ENV_FILE" \
  "$ROOT_DIR/packages/kor-travel-map-api/.env"; do
  if scoped_env_contains_value \
    "$manual_create_api_env_file" \
    "$manual_create_raw"; then
    echo "raw manual Feature create token must not appear in API env" >&2
    exit 1
  fi
done
unset \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED

export KOR_TRAVEL_MAP_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"

# 외부(공유) 객체 저장소 모드 (#372, ADR-052 amendment):
# kor-travel-docker-manager 소유 RustFS를 쓸 때는 자체 rustfs 계열을 기동하지 않고,
# 공유 인스턴스 포트(12101/12105)를 stop 대상에 넣지 않는다 — 넣으면
# stop-fixed-ports.sh가 공유 `tripmate-rustfs` 컨테이너를 중지시킨다.
#
# 외부(공유) 인프라 모드:
# kor-travel-docker-manager 소유 PostGIS(:5432) + RustFS(:12101)를 함께 쓸 때 local
# postgres/rustfs 계열을 모두 기동하지 않는다.
external_infra="${KOR_TRAVEL_MAP_INFRA_EXTERNAL:-false}"
external_db="${KOR_TRAVEL_MAP_DB_EXTERNAL:-false}"
external_object_store="${KOR_TRAVEL_MAP_OBJECT_STORE_EXTERNAL:-false}"

compose_files=(-f docker-compose.yml)
services=(postgres dagster-db-init db-role-bootstrap dagster-storage-migrate api frontend dagster dagster-daemon)
ports=("$KOR_TRAVEL_MAP_API_PORT" "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" "$KOR_TRAVEL_MAP_DAGSTER_PORT")

if [[ "$external_infra" == "true" ]]; then
  compose_files+=(-f docker-compose.external-infra.yml)
  services=(dagster-storage-migrate api frontend dagster dagster-daemon)
elif [[ "$external_db" == "true" ]]; then
  compose_files+=(-f docker-compose.external-db.yml)
  services=(rustfs rustfs-init dagster-storage-migrate api frontend dagster dagster-daemon)
  ports+=("$KOR_TRAVEL_MAP_RUSTFS_API_PORT" "$KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT")
elif [[ "$external_object_store" == "true" ]]; then
  compose_files+=(-f docker-compose.external-object-store.yml)
else
  services=(postgres dagster-db-init db-role-bootstrap rustfs rustfs-init dagster-storage-migrate api frontend dagster dagster-daemon)
  ports+=("$KOR_TRAVEL_MAP_RUSTFS_API_PORT" "$KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT")
fi

# dev 기본 네트워크 = Docker host 모드. 서비스 간 주소를 127.0.0.1:<12xxx>로 고정하고
# ports 매핑을 제거한다(docker-compose.host.yml). 마지막 override로 적용해 mode override
# 위에 얹는다. 브리지로 되돌리려면 KOR_TRAVEL_MAP_DOCKER_NETWORK=bridge.
docker_network="${KOR_TRAVEL_MAP_DOCKER_NETWORK:-host}"
if [[ "$docker_network" == "host" ]]; then
  compose_files+=(-f docker-compose.host.yml)
fi

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required from ignored deployment env or vault" >&2
    exit 1
  fi
}

# T-VN-34A / ADR-090 — service principal DSN은 bootstrap owner에서 유도하지 않는다.
# compose를 직접 실행하지 않고 공식 launcher를 쓸 때도 interpolation 전에 정확한
# deployment secret 집합을 fail-closed 한다.
for name in \
  KOR_TRAVEL_MAP_MIGRATOR_PG_DSN \
  KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN \
  KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN; do
  require_env "$name"
done

if [[ "$external_infra" != "true" && "$external_db" != "true" ]]; then
  for name in \
    KOR_TRAVEL_MAP_POSTGRES_PASSWORD \
    KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN \
    KOR_TRAVEL_MAP_MIGRATOR_PASSWORD \
    KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD \
    KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE; do
    require_env "$name"
  done
fi

if [[ "$docker_network" == "host" ]]; then
  require_env KOR_TRAVEL_MAP_HOST_DAGSTER_PG_URL
elif [[ "$external_infra" == "true" || "$external_db" == "true" ]]; then
  require_env KOR_TRAVEL_MAP_EXTERNAL_DOCKER_DAGSTER_PG_URL
else
  require_env KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL
fi

# dev(기본) 기동. 고정 포트가 이미 사용 중이면 새 포트로 열지 않고 강제종료 여부를
# 묻는다. 강제종료하지 않으면 preflight가 exit 1 → set -e로 기동 중지(기존 서비스/prod 보존).
# 프롬프트 없이 강제종료하려면 KOR_TRAVEL_MAP_FORCE_KILL_PORTS=1.
"$ROOT_DIR/scripts/preflight-ports.sh" "${ports[@]}"

cd "$ROOT_DIR"
compose=(docker compose --env-file /dev/null)
KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN=manual-feature-create-build-placeholder \
KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256=0000000000000000000000000000000000000000000000000000000000000000 \
KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false \
  "${compose[@]}" "${compose_files[@]}" build "${services[@]}"
KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN="$manual_create_raw" \
KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="$manual_create_digest" \
KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED="$manual_create_flag" \
  "${compose[@]}" "${compose_files[@]}" up -d --no-build "${services[@]}"
manual_create_raw=""
manual_create_digest=""
manual_create_flag=""
KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN=manual-feature-create-build-placeholder \
KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256=0000000000000000000000000000000000000000000000000000000000000000 \
KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false \
  "${compose[@]}" "${compose_files[@]}" ps
