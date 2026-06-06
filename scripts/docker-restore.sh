#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-env.sh"

KRTOUR_MAP_POSTGRES_DB="${KRTOUR_MAP_POSTGRES_DB:-krtour_map}"
KRTOUR_MAP_POSTGRES_USER="${KRTOUR_MAP_POSTGRES_USER:-krtour_map}"
KRTOUR_MAP_DAGSTER_POSTGRES_DB="${KRTOUR_MAP_DAGSTER_POSTGRES_DB:-krtour_map_dagster}"
KRTOUR_MAP_BACKUP_ROOT="${KRTOUR_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"
KRTOUR_MAP_RESTORE_BACKUP_ID="${KRTOUR_MAP_RESTORE_BACKUP_ID:-}"
KRTOUR_MAP_RESTORE_BACKUP_DIR="${KRTOUR_MAP_RESTORE_BACKUP_DIR:-}"
KRTOUR_MAP_RESTORE_APP_DB="${KRTOUR_MAP_RESTORE_APP_DB:-${KRTOUR_MAP_POSTGRES_DB}_restore}"
KRTOUR_MAP_RESTORE_DAGSTER_DB="${KRTOUR_MAP_RESTORE_DAGSTER_DB:-${KRTOUR_MAP_DAGSTER_POSTGRES_DB}_restore}"
KRTOUR_MAP_RESTORE_RUSTFS_VOLUME="${KRTOUR_MAP_RESTORE_RUSTFS_VOLUME:-krtour-map-rustfs-restore}"
KRTOUR_MAP_RESTORE_RECREATE="${KRTOUR_MAP_RESTORE_RECREATE:-0}"
KRTOUR_MAP_RESTORE_SKIP_CHECKSUM="${KRTOUR_MAP_RESTORE_SKIP_CHECKSUM:-0}"
KRTOUR_MAP_RESTORE_SKIP_RUSTFS="${KRTOUR_MAP_RESTORE_SKIP_RUSTFS:-0}"

usage() {
  cat >&2 <<EOF
usage: KRTOUR_MAP_RESTORE_BACKUP_ID=<backup_id> npm run docker:restore
       npm run docker:restore -- <backup_id>

Restores a standalone backup into staging targets only:
  app DB      -> $KRTOUR_MAP_RESTORE_APP_DB
  Dagster DB  -> $KRTOUR_MAP_RESTORE_DAGSTER_DB
  RustFS data -> Docker volume $KRTOUR_MAP_RESTORE_RUSTFS_VOLUME

Set KRTOUR_MAP_RESTORE_RECREATE=1 to drop and recreate existing staging targets.
EOF
}

validate_identifier() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "invalid $name=$value" >&2
    exit 1
  fi
}

validate_path_component() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "invalid $name=$value" >&2
    exit 1
  fi
}

validate_docker_volume() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "invalid $name=$value" >&2
    exit 1
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

if (( $# > 1 )); then
  usage
  exit 1
fi

if (( $# == 1 )); then
  KRTOUR_MAP_RESTORE_BACKUP_ID="$1"
fi

validate_identifier KRTOUR_MAP_POSTGRES_DB "$KRTOUR_MAP_POSTGRES_DB"
validate_identifier KRTOUR_MAP_POSTGRES_USER "$KRTOUR_MAP_POSTGRES_USER"
validate_identifier KRTOUR_MAP_DAGSTER_POSTGRES_DB "$KRTOUR_MAP_DAGSTER_POSTGRES_DB"
validate_identifier KRTOUR_MAP_RESTORE_APP_DB "$KRTOUR_MAP_RESTORE_APP_DB"
validate_identifier KRTOUR_MAP_RESTORE_DAGSTER_DB "$KRTOUR_MAP_RESTORE_DAGSTER_DB"
validate_docker_volume KRTOUR_MAP_RESTORE_RUSTFS_VOLUME "$KRTOUR_MAP_RESTORE_RUSTFS_VOLUME"

if [[ "$KRTOUR_MAP_RESTORE_APP_DB" == "$KRTOUR_MAP_POSTGRES_DB" ]]; then
  echo "refusing to restore into production app DB: $KRTOUR_MAP_RESTORE_APP_DB" >&2
  exit 1
fi

if [[ "$KRTOUR_MAP_RESTORE_DAGSTER_DB" == "$KRTOUR_MAP_DAGSTER_POSTGRES_DB" ]]; then
  echo "refusing to restore into production Dagster DB: $KRTOUR_MAP_RESTORE_DAGSTER_DB" >&2
  exit 1
fi

if [[ -z "$KRTOUR_MAP_RESTORE_BACKUP_DIR" ]]; then
  if [[ -z "$KRTOUR_MAP_RESTORE_BACKUP_ID" ]]; then
    usage
    exit 1
  fi
  validate_path_component KRTOUR_MAP_RESTORE_BACKUP_ID "$KRTOUR_MAP_RESTORE_BACKUP_ID"
  KRTOUR_MAP_RESTORE_BACKUP_DIR="$KRTOUR_MAP_BACKUP_ROOT/$KRTOUR_MAP_RESTORE_BACKUP_ID"
fi

backup_dir="$KRTOUR_MAP_RESTORE_BACKUP_DIR"
app_dump="$backup_dir/postgres/$KRTOUR_MAP_POSTGRES_DB.dump"
dagster_dump="$backup_dir/postgres/$KRTOUR_MAP_DAGSTER_POSTGRES_DB.dump"
rustfs_archive="$backup_dir/rustfs/rustfs-data.tar.gz"
manifest="$backup_dir/meta/manifest.json"
checksums="$backup_dir/meta/SHA256SUMS"

require_command docker
require_command sha256sum

for required_path in "$app_dump" "$dagster_dump" "$rustfs_archive" "$manifest" "$checksums"; do
  if [[ ! -f "$required_path" ]]; then
    echo "backup artifact not found: $required_path" >&2
    exit 1
  fi
done

if [[ "$KRTOUR_MAP_RESTORE_SKIP_CHECKSUM" != "1" ]]; then
  echo "verifying backup checksums"
  (
    cd "$backup_dir"
    sha256sum -c meta/SHA256SUMS
  )
fi

compose=(docker compose)

database_exists() {
  local database_name="$1"
  "${compose[@]}" exec -T postgres psql \
    -U "$KRTOUR_MAP_POSTGRES_USER" \
    -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname = '$database_name'" \
    | grep -q 1
}

prepare_database() {
  local database_name="$1"

  if database_exists "$database_name"; then
    if [[ "$KRTOUR_MAP_RESTORE_RECREATE" != "1" ]]; then
      echo "restore target DB already exists: $database_name" >&2
      echo "set KRTOUR_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
      exit 1
    fi
    echo "dropping existing staging DB: $database_name"
    "${compose[@]}" exec -T postgres psql \
      -U "$KRTOUR_MAP_POSTGRES_USER" \
      -d postgres \
      -v ON_ERROR_STOP=1 \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database_name' AND pid <> pg_backend_pid();"
    "${compose[@]}" exec -T postgres dropdb -U "$KRTOUR_MAP_POSTGRES_USER" "$database_name"
  fi

  echo "creating staging DB: $database_name"
  "${compose[@]}" exec -T postgres createdb -U "$KRTOUR_MAP_POSTGRES_USER" "$database_name"
}

restore_database() {
  local dump_path="$1"
  local database_name="$2"

  echo "restoring PostgreSQL dump into $database_name"
  "${compose[@]}" exec -T postgres pg_restore \
    -U "$KRTOUR_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    < "$dump_path"
}

prepare_database "$KRTOUR_MAP_RESTORE_APP_DB"
restore_database "$app_dump" "$KRTOUR_MAP_RESTORE_APP_DB"

prepare_database "$KRTOUR_MAP_RESTORE_DAGSTER_DB"
restore_database "$dagster_dump" "$KRTOUR_MAP_RESTORE_DAGSTER_DB"

if [[ "$KRTOUR_MAP_RESTORE_SKIP_RUSTFS" != "1" ]]; then
  if docker volume inspect "$KRTOUR_MAP_RESTORE_RUSTFS_VOLUME" >/dev/null 2>&1; then
    if [[ "$KRTOUR_MAP_RESTORE_RECREATE" != "1" ]]; then
      echo "restore RustFS volume already exists: $KRTOUR_MAP_RESTORE_RUSTFS_VOLUME" >&2
      echo "set KRTOUR_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
      exit 1
    fi
    echo "removing existing staging RustFS volume: $KRTOUR_MAP_RESTORE_RUSTFS_VOLUME"
    docker volume rm "$KRTOUR_MAP_RESTORE_RUSTFS_VOLUME" >/dev/null
  fi

  echo "restoring RustFS archive into Docker volume: $KRTOUR_MAP_RESTORE_RUSTFS_VOLUME"
  docker run --rm \
    -v "$KRTOUR_MAP_RESTORE_RUSTFS_VOLUME:/data" \
    -v "$backup_dir/rustfs:/backup:ro" \
    alpine:3.20 \
    sh -c "find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf /backup/rustfs-data.tar.gz -C /data && chown -R 10001:10001 /data"
fi

echo "restore completed into staging targets"
echo "app DB: $KRTOUR_MAP_RESTORE_APP_DB"
echo "Dagster DB: $KRTOUR_MAP_RESTORE_DAGSTER_DB"
if [[ "$KRTOUR_MAP_RESTORE_SKIP_RUSTFS" != "1" ]]; then
  echo "RustFS volume: $KRTOUR_MAP_RESTORE_RUSTFS_VOLUME"
fi
