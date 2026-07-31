#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

POSTGRES_DB="${KOR_TRAVEL_MAP_POSTGRES_DB:-kor_travel_map}"
POSTGRES_USER="${KOR_TRAVEL_MAP_POSTGRES_USER:-kor_travel_map}"
POSTGRES_PASSWORD="${KOR_TRAVEL_MAP_POSTGRES_PASSWORD:-kor_travel_map}"
DAGSTER_POSTGRES_DB="${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB:-kor_travel_map_dagster}"
BACKUP_ROOT="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"

RESTORE_APP_DB="${KOR_TRAVEL_MAP_RESTORE_APP_DB:-${POSTGRES_DB}_restore}"
RESTORE_DAGSTER_DB="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:-${DAGSTER_POSTGRES_DB}_restore}"
RESTORE_RUSTFS_VOLUME="${KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:-kor-travel-map-rustfs-restore}"
RESTORE_SWAP_ENV_FILE="$ROOT_DIR/.env.restore-swap"
RESTORE_SWAP_APPLY="${KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY:-0}"
RESTORE_SWAP_SKIP_VERIFY="${KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY:-0}"
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
    -- "$ROOT_DIR/scripts/docker-restore-swap.sh" --maintenance-lock-child "$@"
}

with_maintenance_lock "$@"
if [[ "${1:-}" == "--maintenance-lock-child" ]]; then
  shift
fi

validate_identifier "$RESTORE_APP_DB" "restore app database"
validate_identifier "$RESTORE_DAGSTER_DB" "restore Dagster database"
validate_volume_name "$RESTORE_RUSTFS_VOLUME" "restore RustFS volume"

marker_verification="performed"
if [[ "$RESTORE_SWAP_SKIP_VERIFY" == "1" && "$KOR_TRAVEL_MAP_COMMAND_RECOVERY" != "1" ]]; then
  marker_verification="skipped"
else
  KOR_TRAVEL_MAP_RESTORE_APP_DB="$RESTORE_APP_DB" \
    KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="$RESTORE_DAGSTER_DB" \
    KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME="$RESTORE_RUSTFS_VOLUME" \
    bash "$ROOT_DIR/scripts/docker-restore-verify.sh"
  if [[ "$KOR_TRAVEL_MAP_COMMAND_RECOVERY" == "1" ]]; then
    marker_verification="recovery_performed"
  fi
fi

python_bin="$(select_python)"
acquire_domain_command_fence
KOR_TRAVEL_MAP_POSTGRES_USER="$POSTGRES_USER" \
  KOR_TRAVEL_MAP_POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  KOR_TRAVEL_MAP_RESTORE_APP_DB="$RESTORE_APP_DB" \
  KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="$RESTORE_DAGSTER_DB" \
  KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME="$RESTORE_RUSTFS_VOLUME" \
  "$python_bin" "$ROOT_DIR/scripts/write-restore-swap-env.py" \
  --project-root "$ROOT_DIR"

if [[ "$RESTORE_SWAP_APPLY" == "1" ]]; then
  COMPOSE_COMMAND=(docker compose --env-file /dev/null)
  COMPOSE_COMMAND+=(--env-file "$RESTORE_SWAP_ENV_FILE")
  "${COMPOSE_COMMAND[@]}" up -d rustfs-perms rustfs rustfs-init api frontend dagster dagster-daemon
  if [[ "$RESTORE_SWAP_SKIP_VERIFY" != "1" || "$KOR_TRAVEL_MAP_COMMAND_RECOVERY" == "1" ]]; then
    KOR_TRAVEL_MAP_RESTORE_APP_DB="$RESTORE_APP_DB" \
      KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="$RESTORE_DAGSTER_DB" \
      KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME="$RESTORE_RUSTFS_VOLUME" \
      bash "$ROOT_DIR/scripts/docker-restore-verify.sh"
  fi
  marker_effect_state="swap_applied"
else
  marker_effect_state="swap_planned"
  cat <<SUMMARY
Restore swap env file generated:
  env_file=${RESTORE_SWAP_ENV_FILE}
  app_db=${RESTORE_APP_DB}
  dagster_db=${RESTORE_DAGSTER_DB}
  rustfs_volume=${RESTORE_RUSTFS_VOLUME}

Apply manually with:
  source scripts/load-env.sh
  docker compose --env-file /dev/null --env-file ${RESTORE_SWAP_ENV_FILE} up -d rustfs-perms rustfs rustfs-init api frontend dagster dagster-daemon
SUMMARY
fi

python_bin="$(select_python)"
"$python_bin" "$ROOT_DIR/scripts/write-domain-command-marker.py" \
  --backup-root "$BACKUP_ROOT" \
  --command-id "$KOR_TRAVEL_MAP_COMMAND_ID" \
  --operation "$KOR_TRAVEL_MAP_COMMAND_OPERATION" \
  --marker-key "$KOR_TRAVEL_MAP_COMMAND_MARKER_KEY" \
  --effect-kind "$KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND" \
  --effect-state "$marker_effect_state" \
  --backup-id "$KOR_TRAVEL_MAP_COMMAND_BACKUP_ID" \
  --input-digest "$KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST" \
  --app-db "$RESTORE_APP_DB" \
  --dagster-db "$RESTORE_DAGSTER_DB" \
  --rustfs-volume "$RESTORE_RUSTFS_VOLUME" \
  --verification "$marker_verification" \
  --env-file "$RESTORE_SWAP_ENV_FILE"
release_domain_command_fence
