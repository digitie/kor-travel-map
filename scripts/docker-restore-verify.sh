#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

POSTGRES_DB="${KOR_TRAVEL_MAP_POSTGRES_DB:-kor_travel_map}"
POSTGRES_USER="${KOR_TRAVEL_MAP_POSTGRES_USER:-kor_travel_map}"
DAGSTER_POSTGRES_DB="${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB:-kor_travel_map_dagster}"

RESTORE_APP_DB="${KOR_TRAVEL_MAP_RESTORE_APP_DB:-${POSTGRES_DB}_restore}"
RESTORE_DAGSTER_DB="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:-${DAGSTER_POSTGRES_DB}_restore}"
RESTORE_RUSTFS_VOLUME="${KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:-kor-travel-map-rustfs-restore}"
RESTORE_SKIP_RUSTFS="${KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS:-0}"

validate_identifier() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Invalid ${label}: ${value}" >&2
    exit 2
  fi
}

validate_volume_name() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "Invalid ${label}: ${value}" >&2
    exit 2
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 127
  fi
}

database_exists() {
  local database_name="$1"
  docker compose --env-file /dev/null exec -T postgres psql \
    -U "$POSTGRES_USER" \
    -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname = '${database_name}'" |
    tr -d '[:space:]'
}

require_database() {
  local database_name="$1"
  if [[ "$(database_exists "$database_name")" != "1" ]]; then
    echo "Database does not exist: ${database_name}" >&2
    exit 1
  fi
}

query_scalar() {
  local database_name="$1"
  local sql="$2"
  docker compose --env-file /dev/null exec -T postgres psql \
    -U "$POSTGRES_USER" \
    -d "$database_name" \
    -tAc "$sql" |
    tr -d '[:space:]'
}

require_command docker
validate_identifier "$RESTORE_APP_DB" "restore app database"
validate_identifier "$RESTORE_DAGSTER_DB" "restore Dagster database"
validate_volume_name "$RESTORE_RUSTFS_VOLUME" "restore RustFS volume"

require_database "$RESTORE_APP_DB"
require_database "$RESTORE_DAGSTER_DB"

FEATURE_COUNT="$(query_scalar "$RESTORE_APP_DB" "SELECT count(*) FROM feature.features")"
DAGSTER_TABLE_COUNT="$(query_scalar "$RESTORE_DAGSTER_DB" "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')")"

if [[ "$RESTORE_SKIP_RUSTFS" == "1" ]]; then
  RUSTFS_FILE_COUNT="skipped"
else
  docker volume inspect "$RESTORE_RUSTFS_VOLUME" >/dev/null
  RUSTFS_FILE_COUNT="$(
    docker run --rm -v "${RESTORE_RUSTFS_VOLUME}:/data:ro" alpine:3.20 \
      sh -c "find /data -type f | wc -l" |
      tr -d '[:space:]'
  )"
fi

cat <<SUMMARY
Restore verification complete:
  app_db=${RESTORE_APP_DB} feature_count=${FEATURE_COUNT}
  dagster_db=${RESTORE_DAGSTER_DB} table_count=${DAGSTER_TABLE_COUNT}
  rustfs_volume=${RESTORE_RUSTFS_VOLUME} file_count=${RUSTFS_FILE_COUNT}
SUMMARY
