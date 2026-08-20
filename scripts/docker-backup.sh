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
evidence_dir="meta/manual-feature-evidence"
snapshot_log="$backup_dir/meta/.app-pg-exported-snapshot"
snapshot_holder_pid=""
app_snapshot_id=""

release_app_snapshot() {
  if [[ -n "$snapshot_holder_pid" ]] && kill -0 "$snapshot_holder_pid" 2>/dev/null; then
    kill "$snapshot_holder_pid" 2>/dev/null || true
    wait "$snapshot_holder_pid" 2>/dev/null || true
  fi
  snapshot_holder_pid=""
}

trap release_app_snapshot EXIT

start_app_snapshot() {
  # ``pg_dump --snapshot``와 canonical evidence JSONL을 같은 repeatable-read
  # snapshot에 결박한다. output 첫 행을 받은 뒤에도 exporter transaction은 dump와
  # 네 relation root가 끝날 때까지 살아 있어야 한다.
  "${compose[@]}" exec -T postgres psql \
    -X -A -t -q -v ON_ERROR_STOP=1 \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$KOR_TRAVEL_MAP_POSTGRES_DB" \
    -c "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot(); SELECT pg_sleep(600);" \
    > "$snapshot_log" 2>&1 &
  snapshot_holder_pid="$!"

  local snapshot_id=""
  local attempt
  for attempt in $(seq 1 100); do
    snapshot_id="$(sed -n '1p' "$snapshot_log" | tr -d '[:space:]')"
    if [[ "$snapshot_id" =~ ^[A-Za-z0-9_-]+$ ]]; then
      app_snapshot_id="$snapshot_id"
      return 0
    fi
    if ! kill -0 "$snapshot_holder_pid" 2>/dev/null; then
      cat "$snapshot_log" >&2
      echo "could not export a PostgreSQL snapshot for manual evidence" >&2
      return 1
    fi
    sleep 0.1
  done
  echo "timed out waiting for PostgreSQL exported snapshot" >&2
  return 1
}

dump_db() {
  local database_name="$1"
  local output_relpath="$2"
  local snapshot_id="${3:-}"
  local output_path="$backup_dir/$output_relpath"
  local snapshot_args=()
  if [[ -n "$snapshot_id" ]]; then
    snapshot_args=("--snapshot=$snapshot_id")
  fi

  echo "dumping PostgreSQL database: $database_name"
  "${compose[@]}" exec -T postgres pg_dump \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --format=custom \
    --no-owner \
    --no-privileges \
    "${snapshot_args[@]}" \
    > "$output_path.tmp"
  mv "$output_path.tmp" "$output_path"
}

capture_evidence_jsonl() {
  local relation_name="$1"
  local select_sql="$2"
  local snapshot_id="$3"
  local output_path="$backup_dir/$evidence_dir/$relation_name.jsonl"

  "${compose[@]}" exec -T postgres psql \
    -X -A -t -q -v ON_ERROR_STOP=1 \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$KOR_TRAVEL_MAP_POSTGRES_DB" \
    -c "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '$snapshot_id'; $select_sql" \
    > "$output_path"
}

relation_count() {
  wc -l < "$1" | tr -d '[:space:]'
}

relation_sha256() {
  sha256sum "$1" | awk '{print $1}'
}

mkdir -p "$backup_dir/$evidence_dir"
start_app_snapshot
dump_db "$KOR_TRAVEL_MAP_POSTGRES_DB" "$app_dump" "$app_snapshot_id"
dump_db "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" "$dagster_dump"

capture_evidence_jsonl \
  manual_feature_identity_claims \
  "SELECT to_jsonb(claim)::text FROM feature.manual_feature_identity_claims AS claim ORDER BY claim.feature_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  feature_creation_origins \
  "SELECT to_jsonb(origin)::text FROM feature.feature_creation_origins AS origin ORDER BY origin.feature_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  domain_commands \
  "SELECT to_jsonb(command)::text FROM ops.domain_commands AS command ORDER BY command.command_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  domain_command_results \
  "SELECT to_jsonb(result)::text FROM ops.domain_command_results AS result ORDER BY result.command_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  feature_requests \
  "SELECT to_jsonb(request)::text FROM ops.feature_requests AS request ORDER BY request.request_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  manual_provider_dedup_cases \
  "SELECT to_jsonb(dedup_case)::text FROM ops.manual_provider_dedup_cases AS dedup_case ORDER BY dedup_case.case_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  manual_provider_dedup_resolutions \
  "SELECT to_jsonb(resolution)::text FROM ops.manual_provider_dedup_resolutions AS resolution ORDER BY resolution.resolution_id" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  feature_reference_reconciliation_events \
  "SELECT to_jsonb(event)::text FROM ops.feature_reference_reconciliation_events AS event ORDER BY event.event_sequence" \
  "$app_snapshot_id"
capture_evidence_jsonl \
  feature_reference_reconciliation_acks \
  "SELECT to_jsonb(ack)::text FROM ops.feature_reference_reconciliation_acks AS ack ORDER BY ack.event_id, ack.principal_id" \
  "$app_snapshot_id"
release_app_snapshot

claim_jsonl="$evidence_dir/manual_feature_identity_claims.jsonl"
origin_jsonl="$evidence_dir/feature_creation_origins.jsonl"
commands_jsonl="$evidence_dir/domain_commands.jsonl"
results_jsonl="$evidence_dir/domain_command_results.jsonl"
requests_jsonl="$evidence_dir/feature_requests.jsonl"
cases_jsonl="$evidence_dir/manual_provider_dedup_cases.jsonl"
resolutions_jsonl="$evidence_dir/manual_provider_dedup_resolutions.jsonl"
events_jsonl="$evidence_dir/feature_reference_reconciliation_events.jsonl"
acks_jsonl="$evidence_dir/feature_reference_reconciliation_acks.jsonl"
claim_count="$(relation_count "$backup_dir/$claim_jsonl")"
origin_count="$(relation_count "$backup_dir/$origin_jsonl")"
commands_count="$(relation_count "$backup_dir/$commands_jsonl")"
results_count="$(relation_count "$backup_dir/$results_jsonl")"
requests_count="$(relation_count "$backup_dir/$requests_jsonl")"
cases_count="$(relation_count "$backup_dir/$cases_jsonl")"
resolutions_count="$(relation_count "$backup_dir/$resolutions_jsonl")"
events_count="$(relation_count "$backup_dir/$events_jsonl")"
acks_count="$(relation_count "$backup_dir/$acks_jsonl")"
claim_sha256="$(relation_sha256 "$backup_dir/$claim_jsonl")"
origin_sha256="$(relation_sha256 "$backup_dir/$origin_jsonl")"
commands_sha256="$(relation_sha256 "$backup_dir/$commands_jsonl")"
results_sha256="$(relation_sha256 "$backup_dir/$results_jsonl")"
requests_sha256="$(relation_sha256 "$backup_dir/$requests_jsonl")"
cases_sha256="$(relation_sha256 "$backup_dir/$cases_jsonl")"
resolutions_sha256="$(relation_sha256 "$backup_dir/$resolutions_jsonl")"
events_sha256="$(relation_sha256 "$backup_dir/$events_jsonl")"
acks_sha256="$(relation_sha256 "$backup_dir/$acks_jsonl")"

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
  },
  "manual_feature_evidence": {
    "schema_version": 3,
    "snapshot_consistency": "pg_export_snapshot",
    "relations": {
      "manual_feature_identity_claims": {"path": "$claim_jsonl", "row_count": $claim_count, "sha256": "$claim_sha256"},
      "feature_creation_origins": {"path": "$origin_jsonl", "row_count": $origin_count, "sha256": "$origin_sha256"},
      "domain_commands": {"path": "$commands_jsonl", "row_count": $commands_count, "sha256": "$commands_sha256"},
      "domain_command_results": {"path": "$results_jsonl", "row_count": $results_count, "sha256": "$results_sha256"},
      "feature_requests": {"path": "$requests_jsonl", "row_count": $requests_count, "sha256": "$requests_sha256"},
      "manual_provider_dedup_cases": {"path": "$cases_jsonl", "row_count": $cases_count, "sha256": "$cases_sha256"},
      "manual_provider_dedup_resolutions": {"path": "$resolutions_jsonl", "row_count": $resolutions_count, "sha256": "$resolutions_sha256"},
      "feature_reference_reconciliation_events": {"path": "$events_jsonl", "row_count": $events_count, "sha256": "$events_sha256"},
      "feature_reference_reconciliation_acks": {"path": "$acks_jsonl", "row_count": $acks_count, "sha256": "$acks_sha256"}
    }
  }
}
EOF

(
  cd "$backup_dir"
  sha256sum "$app_dump" "$dagster_dump" "$rustfs_archive" \
    "$claim_jsonl" "$origin_jsonl" "$commands_jsonl" "$results_jsonl" "$requests_jsonl" \
    "$cases_jsonl" "$resolutions_jsonl" "$events_jsonl" "$acks_jsonl" \
    > meta/SHA256SUMS
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
