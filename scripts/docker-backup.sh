#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-env.sh"

KRTOUR_MAP_POSTGRES_DB="${KRTOUR_MAP_POSTGRES_DB:-krtour_map}"
KRTOUR_MAP_POSTGRES_USER="${KRTOUR_MAP_POSTGRES_USER:-krtour_map}"
KRTOUR_MAP_DAGSTER_POSTGRES_DB="${KRTOUR_MAP_DAGSTER_POSTGRES_DB:-krtour_map_dagster}"
KRTOUR_MAP_BACKUP_ROOT="${KRTOUR_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"
KRTOUR_MAP_BACKUP_ID="${KRTOUR_MAP_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
KRTOUR_MAP_BACKUP_ALLOW_RUNNING="${KRTOUR_MAP_BACKUP_ALLOW_RUNNING:-0}"

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

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

validate_identifier KRTOUR_MAP_POSTGRES_DB "$KRTOUR_MAP_POSTGRES_DB"
validate_identifier KRTOUR_MAP_POSTGRES_USER "$KRTOUR_MAP_POSTGRES_USER"
validate_identifier KRTOUR_MAP_DAGSTER_POSTGRES_DB "$KRTOUR_MAP_DAGSTER_POSTGRES_DB"
validate_path_component KRTOUR_MAP_BACKUP_ID "$KRTOUR_MAP_BACKUP_ID"
validate_path_component KRTOUR_MAP_OBJECT_STORE_BUCKET "$KRTOUR_MAP_OBJECT_STORE_BUCKET"
validate_path_component KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET "$KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET"

require_command docker
require_command sha256sum

compose=(docker compose)
writer_services=(api frontend dagster dagster-daemon rustfs)

if [[ "$KRTOUR_MAP_BACKUP_ALLOW_RUNNING" != "1" ]]; then
  running_services=()
  for service in "${writer_services[@]}"; do
    container_id="$("${compose[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container_id" ]] && docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null | grep -q true; then
      running_services+=("$service")
    fi
  done

  if (( ${#running_services[@]} > 0 )); then
    echo "writer services are running: ${running_services[*]}" >&2
    echo "stop API/Dagster/RustFS writers first, or set KRTOUR_MAP_BACKUP_ALLOW_RUNNING=1 for a best-effort snapshot." >&2
    exit 1
  fi
fi

backup_dir="$KRTOUR_MAP_BACKUP_ROOT/$KRTOUR_MAP_BACKUP_ID"
if [[ -e "$backup_dir" ]]; then
  echo "backup directory already exists: $backup_dir" >&2
  exit 1
fi

mkdir -p "$backup_dir/postgres" "$backup_dir/rustfs" "$backup_dir/meta"

created_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
app_dump="postgres/$KRTOUR_MAP_POSTGRES_DB.dump"
dagster_dump="postgres/$KRTOUR_MAP_DAGSTER_POSTGRES_DB.dump"
rustfs_archive="rustfs/rustfs-data.tar.gz"

dump_db() {
  local database_name="$1"
  local output_relpath="$2"
  local output_path="$backup_dir/$output_relpath"

  echo "dumping PostgreSQL database: $database_name"
  "${compose[@]}" exec -T postgres pg_dump \
    -U "$KRTOUR_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --format=custom \
    --no-owner \
    --no-privileges \
    > "$output_path.tmp"
  mv "$output_path.tmp" "$output_path"
}

dump_db "$KRTOUR_MAP_POSTGRES_DB" "$app_dump"
dump_db "$KRTOUR_MAP_DAGSTER_POSTGRES_DB" "$dagster_dump"

echo "archiving RustFS Docker volume"
"${compose[@]}" run --rm --no-deps --entrypoint sh \
  -v "$backup_dir/rustfs:/backup" \
  rustfs-perms \
  -c "tar czf /backup/rustfs-data.tar.gz -C /data ."

cat > "$backup_dir/meta/manifest.json" <<EOF
{
  "schema_version": 1,
  "backup_id": "$KRTOUR_MAP_BACKUP_ID",
  "created_at_utc": "$created_at_utc",
  "mode": "docker-compose-cold-backup",
  "components": {
    "postgres_app": "$app_dump",
    "postgres_dagster": "$dagster_dump",
    "rustfs": "$rustfs_archive"
  },
  "databases": {
    "app": "$KRTOUR_MAP_POSTGRES_DB",
    "dagster": "$KRTOUR_MAP_DAGSTER_POSTGRES_DB"
  },
  "object_storage": {
    "feature_bucket": "$KRTOUR_MAP_OBJECT_STORE_BUCKET",
    "offline_upload_bucket": "$KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET",
    "volume_service": "rustfs-perms:/data"
  }
}
EOF

(
  cd "$backup_dir"
  sha256sum "$app_dump" "$dagster_dump" "$rustfs_archive" > meta/SHA256SUMS
)

echo "backup completed: $backup_dir"
echo "verify with: cd \"$backup_dir\" && sha256sum -c meta/SHA256SUMS"
