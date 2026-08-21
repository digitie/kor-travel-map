#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-env.sh"

KOR_TRAVEL_MAP_POSTGRES_DB="${KOR_TRAVEL_MAP_POSTGRES_DB:-kor_travel_map}"
KOR_TRAVEL_MAP_POSTGRES_USER="${KOR_TRAVEL_MAP_POSTGRES_USER:-kor_travel_map}"
KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB="${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB:-kor_travel_map_dagster}"
KOR_TRAVEL_MAP_BACKUP_ROOT="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"
KOR_TRAVEL_MAP_RESTORE_BACKUP_ID="${KOR_TRAVEL_MAP_RESTORE_BACKUP_ID:-}"
KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR="${KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR:-}"
KOR_TRAVEL_MAP_RESTORE_APP_DB="${KOR_TRAVEL_MAP_RESTORE_APP_DB:-${KOR_TRAVEL_MAP_POSTGRES_DB}_restore}"
KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:-${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB}_restore}"
KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME="${KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:-kor-travel-map-rustfs-restore}"
KOR_TRAVEL_MAP_RESTORE_RECREATE="${KOR_TRAVEL_MAP_RESTORE_RECREATE:-0}"
KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM="${KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM:-0}"
KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS="${KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS:-0}"
KOR_TRAVEL_MAP_RESTORE_SKIP_VERIFY="${KOR_TRAVEL_MAP_RESTORE_SKIP_VERIFY:-0}"
KOR_TRAVEL_MAP_COMMAND_ID="${KOR_TRAVEL_MAP_COMMAND_ID:-}"
KOR_TRAVEL_MAP_COMMAND_OPERATION="${KOR_TRAVEL_MAP_COMMAND_OPERATION:-}"
KOR_TRAVEL_MAP_COMMAND_RECOVERY="${KOR_TRAVEL_MAP_COMMAND_RECOVERY:-0}"
KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN="${KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN:-}"
KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED="${KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED:-0}"
KOR_TRAVEL_MAP_COMMAND_MARKER_KEY="${KOR_TRAVEL_MAP_COMMAND_MARKER_KEY:-}"
KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND="${KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND:-}"
KOR_TRAVEL_MAP_COMMAND_BACKUP_ID="${KOR_TRAVEL_MAP_COMMAND_BACKUP_ID:-}"
KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST="${KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST:-}"

usage() {
  cat >&2 <<EOF
usage: KOR_TRAVEL_MAP_RESTORE_BACKUP_ID=<backup_id> npm run docker:restore
       npm run docker:restore -- <backup_id>

Restores a standalone backup into staging targets only:
  app DB      -> $KOR_TRAVEL_MAP_RESTORE_APP_DB
  Dagster DB  -> $KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB
  RustFS data -> Docker volume $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME

Set KOR_TRAVEL_MAP_RESTORE_RECREATE=1 to drop and recreate existing staging targets.
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
    -- "$ROOT_DIR/scripts/docker-restore.sh" --maintenance-lock-child "$@"
}

with_maintenance_lock "$@"
if [[ "${1:-}" == "--maintenance-lock-child" ]]; then
  shift
fi

if (( $# > 1 )); then
  usage
  exit 1
fi

if (( $# == 1 )); then
  KOR_TRAVEL_MAP_RESTORE_BACKUP_ID="$1"
fi

validate_identifier KOR_TRAVEL_MAP_POSTGRES_DB "$KOR_TRAVEL_MAP_POSTGRES_DB"
validate_identifier KOR_TRAVEL_MAP_POSTGRES_USER "$KOR_TRAVEL_MAP_POSTGRES_USER"
validate_identifier KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB"
validate_identifier KOR_TRAVEL_MAP_RESTORE_APP_DB "$KOR_TRAVEL_MAP_RESTORE_APP_DB"
validate_identifier KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"
validate_docker_volume KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME"

if [[ "$KOR_TRAVEL_MAP_RESTORE_APP_DB" == "$KOR_TRAVEL_MAP_POSTGRES_DB" ]]; then
  echo "refusing to restore into production app DB: $KOR_TRAVEL_MAP_RESTORE_APP_DB" >&2
  exit 1
fi

if [[ "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB" == "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" ]]; then
  echo "refusing to restore into production Dagster DB: $KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB" >&2
  exit 1
fi

if [[ -z "$KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR" ]]; then
  if [[ -z "$KOR_TRAVEL_MAP_RESTORE_BACKUP_ID" ]]; then
    usage
    exit 1
  fi
  validate_path_component KOR_TRAVEL_MAP_RESTORE_BACKUP_ID "$KOR_TRAVEL_MAP_RESTORE_BACKUP_ID"
  KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR="$KOR_TRAVEL_MAP_BACKUP_ROOT/$KOR_TRAVEL_MAP_RESTORE_BACKUP_ID"
fi

backup_dir="$KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR"
app_dump="$backup_dir/postgres/$KOR_TRAVEL_MAP_POSTGRES_DB.dump"
dagster_dump="$backup_dir/postgres/$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB.dump"
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

if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM" != "1" ]]; then
  echo "verifying backup checksums"
  (
    cd "$backup_dir"
    sha256sum -c meta/SHA256SUMS
  )
fi

compose=(docker compose --env-file /dev/null)

rewrite_postgres_dsn_database() {
  local dsn="$1"
  local database_name="$2"
  local python_bin
  python_bin="$(select_python)"
  KOR_TRAVEL_MAP_RESTORE_SOURCE_DSN="$dsn" \
    "$python_bin" - "$database_name" <<'PY'
from __future__ import annotations

import os
import sys
from urllib.parse import quote, urlsplit, urlunsplit

database = sys.argv[1]
parts = urlsplit(os.environ["KOR_TRAVEL_MAP_RESTORE_SOURCE_DSN"])
if not parts.scheme.startswith("postgresql") or not parts.netloc:
    raise SystemExit("restore repair requires a PostgreSQL URL DSN")
print(urlunsplit((parts.scheme, parts.netloc, "/" + quote(database, safe=""), parts.query, "")))
PY
}

restore_evidence_schema_version() {
  local python_bin
  python_bin="$(select_python)"
  "$python_bin" - "$manifest" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))[
        "manual_feature_evidence"
    ]["schema_version"]
except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
    value = 0
print(value if isinstance(value, int) else 0)
PY
}

require_restore_boundary_value() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "M05 restore boundary requires $name" >&2
    exit 1
  fi
}

run_restore_bootstrap_phase() {
  local phase="$1"
  local bootstrap_dsn="$2"
  KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED=true \
  KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE="$phase" \
  KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE="$KOR_TRAVEL_MAP_RESTORE_APP_DB" \
  KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN="$bootstrap_dsn" \
  KOR_TRAVEL_MAP_POSTGRES_DB="$KOR_TRAVEL_MAP_RESTORE_APP_DB" \
    "${compose[@]}" run --rm --no-deps db-role-bootstrap
}

preflight_restored_runtime_login() {
  local runtime_dsn="$1"
  local expected_login="$2"
  KOR_TRAVEL_MAP_PG_DSN="$runtime_dsn" \
    "${compose[@]}" run --rm --no-deps --entrypoint python \
      api - "$expected_login" <<'PY'
from __future__ import annotations

import asyncio
import os
import sys

from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, make_async_engine


async def main() -> None:
    engine = make_async_engine(os.environ["KOR_TRAVEL_MAP_PG_DSN"])
    try:
        await assert_runtime_db_privilege_boundary(engine, expected_login=sys.argv[1])
    finally:
        await engine.dispose()


asyncio.run(main())
PY
}

repair_v3_restored_manual_feature_boundary() {
  if [[ "$(restore_evidence_schema_version)" != "3" ]]; then
    return
  fi

  local required_name
  for required_name in \
    KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN \
    KOR_TRAVEL_MAP_MIGRATOR_PG_DSN \
    KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN \
    KOR_TRAVEL_MAP_MIGRATOR_PASSWORD \
    KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD; do
    require_restore_boundary_value "$required_name"
  done

  local restore_bootstrap_dsn restore_migrator_dsn restore_api_dsn restore_dagster_dsn
  restore_bootstrap_dsn="$(rewrite_postgres_dsn_database \
    "$KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN" "$KOR_TRAVEL_MAP_RESTORE_APP_DB")"
  restore_migrator_dsn="$(rewrite_postgres_dsn_database \
    "$KOR_TRAVEL_MAP_MIGRATOR_PG_DSN" "$KOR_TRAVEL_MAP_RESTORE_APP_DB")"
  restore_api_dsn="$(rewrite_postgres_dsn_database \
    "$KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN" "$KOR_TRAVEL_MAP_RESTORE_APP_DB")"
  restore_dagster_dsn="$(rewrite_postgres_dsn_database \
    "$KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN" "$KOR_TRAVEL_MAP_RESTORE_APP_DB")"

  run_restore_bootstrap_phase legacy "$restore_bootstrap_dsn"
  run_restore_bootstrap_phase m05-pre "$restore_bootstrap_dsn"
  KOR_TRAVEL_MAP_MIGRATOR_PG_DSN="$restore_migrator_dsn" \
    "${compose[@]}" run --rm --no-deps --entrypoint /bin/sh \
      api ./docker/migrate-m05.sh
  run_restore_bootstrap_phase m05-repair "$restore_bootstrap_dsn"
  KOR_TRAVEL_MAP_PG_DSN="$restore_migrator_dsn" \
    "${compose[@]}" run --rm --no-deps --entrypoint python \
      api -m kortravelmap.infra.runtime_privileges
  preflight_restored_runtime_login "$restore_api_dsn" ktm_feature_api_runtime
  preflight_restored_runtime_login "$restore_dagster_dsn" ktm_feature_dagster_runtime
}

database_exists() {
  local database_name="$1"
  "${compose[@]}" exec -T postgres psql \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname = '$database_name'" \
    | grep -q 1
}

prepare_database() {
  local database_name="$1"

  if database_exists "$database_name"; then
    if [[ "$KOR_TRAVEL_MAP_RESTORE_RECREATE" != "1" ]]; then
      echo "restore target DB already exists: $database_name" >&2
      echo "set KOR_TRAVEL_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
      exit 1
    fi
    echo "dropping existing staging DB: $database_name"
    "${compose[@]}" exec -T postgres psql \
      -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
      -d postgres \
      -v ON_ERROR_STOP=1 \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database_name' AND pid <> pg_backend_pid();"
    "${compose[@]}" exec -T postgres dropdb -U "$KOR_TRAVEL_MAP_POSTGRES_USER" "$database_name"
  fi

  echo "creating staging DB: $database_name"
  "${compose[@]}" exec -T postgres createdb -U "$KOR_TRAVEL_MAP_POSTGRES_USER" "$database_name"
}

restore_database() {
  local dump_path="$1"
  local database_name="$2"

  echo "restoring PostgreSQL dump into $database_name"
  "${compose[@]}" exec -T postgres pg_restore \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    < "$dump_path"

  # pg_dump/pg_restore는 planner 통계를 보존하지 않는다. 복원 직후의 API나
  # notice reconcile이 빈 통계로 실행되지 않도록 큰 table부터 단계적으로
  # 통계를 만든 뒤에만 staging DB를 검증·swap 대상으로 내보낸다.
  echo "analyzing restored PostgreSQL database: $database_name"
  "${compose[@]}" exec -T postgres vacuumdb \
    -U "$KOR_TRAVEL_MAP_POSTGRES_USER" \
    -d "$database_name" \
    --analyze-in-stages
}

evidence_schema_version="$(restore_evidence_schema_version)"
marker_verification="performed"
if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_VERIFY" == "1" && "$evidence_schema_version" != "3" ]]; then
  marker_verification="skipped"
fi

for database_name in \
  "$KOR_TRAVEL_MAP_RESTORE_APP_DB" \
  "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"; do
  if database_exists "$database_name" && [[ "$KOR_TRAVEL_MAP_RESTORE_RECREATE" != "1" ]]; then
    echo "restore target DB already exists: $database_name" >&2
    echo "set KOR_TRAVEL_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
    exit 1
  fi
done
if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS" != "1" ]] \
  && docker volume inspect "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" >/dev/null 2>&1 \
  && [[ "$KOR_TRAVEL_MAP_RESTORE_RECREATE" != "1" ]]; then
  echo "restore RustFS volume already exists: $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" >&2
  echo "set KOR_TRAVEL_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
  exit 1
fi

acquire_domain_command_fence
prepare_database "$KOR_TRAVEL_MAP_RESTORE_APP_DB"
restore_database "$app_dump" "$KOR_TRAVEL_MAP_RESTORE_APP_DB"

prepare_database "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"
restore_database "$dagster_dump" "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"

repair_v3_restored_manual_feature_boundary

if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS" != "1" ]]; then
  if docker volume inspect "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" >/dev/null 2>&1; then
    if [[ "$KOR_TRAVEL_MAP_RESTORE_RECREATE" != "1" ]]; then
      echo "restore RustFS volume already exists: $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" >&2
      echo "set KOR_TRAVEL_MAP_RESTORE_RECREATE=1 to recreate staging targets." >&2
      exit 1
    fi
    echo "removing existing staging RustFS volume: $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME"
    docker volume rm "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" >/dev/null
  fi

  echo "restoring RustFS archive into Docker volume: $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME"
  docker run --rm \
    -v "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:/data" \
    -v "$backup_dir/rustfs:/backup:ro" \
    alpine:3.20 \
    sh -c "find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf /backup/rustfs-data.tar.gz -C /data && chown -R 10001:10001 /data"
fi

echo "restore completed into staging targets"
echo "app DB: $KOR_TRAVEL_MAP_RESTORE_APP_DB"
echo "Dagster DB: $KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"
if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS" != "1" ]]; then
  echo "RustFS volume: $KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME"
fi

# v3은 M05 구독/ACK root에서 lease를 재구성해야 한다. 그 재구성은 root 검증기의
# fail-closed 후처리이므로 일반적인 verify 우회로 건너뛸 수 없다.
if [[ "$KOR_TRAVEL_MAP_RESTORE_SKIP_VERIFY" != "1" || "$evidence_schema_version" == "3" ]]; then
  KOR_TRAVEL_MAP_RESTORE_APP_DB="$KOR_TRAVEL_MAP_RESTORE_APP_DB" \
  KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB" \
  KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME="$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" \
  KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR="$backup_dir" \
  KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS="$KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS" \
  bash "$ROOT_DIR/scripts/docker-restore-verify.sh"
fi

python_bin="$(select_python)"
"$python_bin" "$ROOT_DIR/scripts/write-domain-command-marker.py" \
  --backup-root "$KOR_TRAVEL_MAP_BACKUP_ROOT" \
  --command-id "$KOR_TRAVEL_MAP_COMMAND_ID" \
  --operation "$KOR_TRAVEL_MAP_COMMAND_OPERATION" \
  --marker-key "$KOR_TRAVEL_MAP_COMMAND_MARKER_KEY" \
  --effect-kind "$KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND" \
  --effect-state "restored" \
  --backup-id "$KOR_TRAVEL_MAP_COMMAND_BACKUP_ID" \
  --input-digest "$KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST" \
  --app-db "$KOR_TRAVEL_MAP_RESTORE_APP_DB" \
  --dagster-db "$KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB" \
  --rustfs-volume "$KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" \
  --verification "$marker_verification"
release_domain_command_fence
