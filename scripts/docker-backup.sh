#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-env.sh"

KOR_TRAVEL_MAP_POSTGRES_DB="${KOR_TRAVEL_MAP_POSTGRES_DB:-kor_travel_map}"
KOR_TRAVEL_MAP_POSTGRES_USER="${KOR_TRAVEL_MAP_POSTGRES_USER:-kor_travel_map}"
KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB="${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB:-kor_travel_map_dagster}"
KOR_TRAVEL_MAP_BACKUP_ROOT="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"
KOR_TRAVEL_MAP_BACKUP_ID="${KOR_TRAVEL_MAP_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING="${KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING:-0}"
KOR_TRAVEL_MAP_COMMAND_ID="${KOR_TRAVEL_MAP_COMMAND_ID:-}"
KOR_TRAVEL_MAP_COMMAND_OPERATION="${KOR_TRAVEL_MAP_COMMAND_OPERATION:-}"
KOR_TRAVEL_MAP_COMMAND_RECOVERY="${KOR_TRAVEL_MAP_COMMAND_RECOVERY:-0}"
KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN="${KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN:-}"
KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED="${KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED:-0}"
KOR_TRAVEL_MAP_COMMAND_MARKER_KEY="${KOR_TRAVEL_MAP_COMMAND_MARKER_KEY:-}"
KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND="${KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND:-}"
KOR_TRAVEL_MAP_COMMAND_BACKUP_ID="${KOR_TRAVEL_MAP_COMMAND_BACKUP_ID:-}"
KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST="${KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST:-}"

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

select_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    echo "$PYTHON_BIN"
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "required command not found: python3" >&2
    exit 127
  fi
}

# shellcheck source=scripts/domain-command-fence.sh
source "$ROOT_DIR/scripts/domain-command-fence.sh"

with_maintenance_lock() {
  if [[ "${1:-}" == "--maintenance-lock-child" ]]; then
    return 0
  fi
  local python_bin
  python_bin="$(select_python)"
  exec "$python_bin" "$ROOT_DIR/scripts/with-pg-advisory-lock.py" \
    --key "maintenance:backup-restore" \
    -- "$ROOT_DIR/scripts/docker-backup.sh" --maintenance-lock-child "$@"
}

validate_identifier KOR_TRAVEL_MAP_POSTGRES_DB "$KOR_TRAVEL_MAP_POSTGRES_DB"
validate_identifier KOR_TRAVEL_MAP_POSTGRES_USER "$KOR_TRAVEL_MAP_POSTGRES_USER"
validate_identifier KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB"
validate_path_component KOR_TRAVEL_MAP_BACKUP_ID "$KOR_TRAVEL_MAP_BACKUP_ID"
validate_path_component KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET "$KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET"
validate_path_component KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET "$KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET"

require_command docker
require_command sha256sum
with_maintenance_lock "$@"
if [[ "${1:-}" == "--maintenance-lock-child" ]]; then
  shift
fi

compose=(docker compose --env-file /dev/null)
writer_services=(api frontend dagster dagster-daemon rustfs)

if [[ "$KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING" != "1" ]]; then
  running_services=()
  for service in "${writer_services[@]}"; do
    container_id="$("${compose[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container_id" ]] && docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null | grep -q true; then
      running_services+=("$service")
    fi
  done

  if (( ${#running_services[@]} > 0 )); then
    echo "writer services are running: ${running_services[*]}" >&2
    echo "stop API/Dagster/RustFS writers first, or set KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING=1 for a best-effort snapshot." >&2
    exit 1
  fi
fi

backup_dir="$KOR_TRAVEL_MAP_BACKUP_ROOT/$KOR_TRAVEL_MAP_BACKUP_ID"
acquire_domain_command_fence
python_bin="$(select_python)"
"$python_bin" "$ROOT_DIR/scripts/reserve-backup-destination.py" \
  --backup-root "$KOR_TRAVEL_MAP_BACKUP_ROOT" \
  --command-id "$KOR_TRAVEL_MAP_COMMAND_ID" \
  --backup-id "$KOR_TRAVEL_MAP_BACKUP_ID" \
  --input-digest "$KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST"
rm -rf -- "$backup_dir/postgres" "$backup_dir/rustfs" "$backup_dir/meta"

mkdir -p "$backup_dir/postgres" "$backup_dir/rustfs" "$backup_dir/meta"

created_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
app_dump="postgres/$KOR_TRAVEL_MAP_POSTGRES_DB.dump"
dagster_dump="postgres/$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB.dump"
rustfs_archive="rustfs/rustfs-data.tar.gz"

dump_db() {
  local database_name="$1"
  local output_relpath="$2"
  local output_path="$backup_dir/$output_relpath"

  echo "dumping PostgreSQL database: $database_name"
  "${compose[@]}" exec -T postgres pg_dump \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --format=custom \
    --no-owner \
    --no-privileges \
    > "$output_path.tmp"
  mv "$output_path.tmp" "$output_path"
}

dump_db "$KOR_TRAVEL_MAP_POSTGRES_DB" "$app_dump"
dump_db "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" "$dagster_dump"

echo "archiving RustFS Docker volume"
"${compose[@]}" run --rm --no-deps --entrypoint sh \
  -v "$backup_dir/rustfs:/backup" \
  rustfs-perms \
  -c "tar czf /backup/rustfs-data.tar.gz -C /data ."

cat > "$backup_dir/meta/manifest.json" <<EOF
{
  "schema_version": 1,
  "backup_id": "$KOR_TRAVEL_MAP_BACKUP_ID",
  "created_at_utc": "$created_at_utc",
  "mode": "docker-compose-cold-backup",
  "components": {
    "postgres_app": "$app_dump",
    "postgres_dagster": "$dagster_dump",
    "rustfs": "$rustfs_archive"
  },
  "databases": {
    "app": "$KOR_TRAVEL_MAP_POSTGRES_DB",
    "dagster": "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB"
  },
  "object_storage": {
    "feature_bucket": "$KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET",
    "offline_upload_bucket": "$KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET",
    "volume_service": "rustfs-perms:/data"
  }
}
EOF

(
  cd "$backup_dir"
  sha256sum "$app_dump" "$dagster_dump" "$rustfs_archive" > meta/SHA256SUMS
)

python_bin="$(select_python)"
"$python_bin" "$ROOT_DIR/scripts/write-domain-command-marker.py" \
  --backup-root "$KOR_TRAVEL_MAP_BACKUP_ROOT" \
  --command-id "$KOR_TRAVEL_MAP_COMMAND_ID" \
  --operation "$KOR_TRAVEL_MAP_COMMAND_OPERATION" \
  --marker-key "$KOR_TRAVEL_MAP_COMMAND_MARKER_KEY" \
  --effect-kind "$KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND" \
  --effect-state "created" \
  --backup-id "$KOR_TRAVEL_MAP_COMMAND_BACKUP_ID" \
  --input-digest "$KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST"
release_domain_command_fence
echo "backup completed: $backup_dir"
echo "verify with: cd \"$backup_dir\" && sha256sum -c meta/SHA256SUMS"
