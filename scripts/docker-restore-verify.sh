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
RESTORE_BACKUP_DIR="${KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR:-}"
RESTORE_BACKUP_ID="${KOR_TRAVEL_MAP_RESTORE_BACKUP_ID:-}"
BACKUP_ROOT="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$ROOT_DIR/data/backups}"

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
    echo "Required command not found: python3" >&2
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

capture_manual_evidence_jsonl() {
  local select_sql="$1"
  local output_path="$2"
  docker compose --env-file /dev/null exec -T postgres psql \
    -X -A -t -q -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" \
    -d "$RESTORE_APP_DB" \
    -c "$select_sql" \
    > "$output_path"
}

verify_manual_feature_evidence() {
  local manifest="$RESTORE_BACKUP_DIR/meta/manifest.json"
  local python_bin
  python_bin="$(select_python)"
  if [[ ! -f "$manifest" ]]; then
    echo "Restore verification failed: manual evidence manifest is missing" >&2
    exit 1
  fi
  local manifest_rows
  if ! manifest_rows="$("$python_bin" - "$manifest" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    evidence = raw["manual_feature_evidence"]
    relations = evidence["relations"]
    schema_version = evidence["schema_version"]
    if schema_version not in {1, 2} or evidence["snapshot_consistency"] != "pg_export_snapshot":
        raise ValueError("unsupported evidence manifest")
    names = [
        "manual_feature_identity_claims",
        "feature_creation_origins",
        "domain_commands",
        "domain_command_results",
    ]
    if schema_version >= 2:
        names.append("feature_requests")
    for name in names:
        item = relations[name]
        count = item["row_count"]
        digest = item["sha256"]
        if not isinstance(count, int) or count < 0:
            raise ValueError(name)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(name)
        print(f"{name}\t{count}\t{digest}")
except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
)"; then
    echo "Restore verification failed: manual evidence manifest is invalid" >&2
    exit 1
  fi

  local evidence_tmp
  evidence_tmp="$(mktemp -d)"
  local name expected_count expected_sha output_path actual_count actual_sha select_sql
  while IFS=$'\t' read -r name expected_count expected_sha; do
    case "$name" in
      manual_feature_identity_claims)
        select_sql="SELECT to_jsonb(claim)::text FROM feature.manual_feature_identity_claims AS claim ORDER BY claim.feature_id"
        ;;
      feature_creation_origins)
        select_sql="SELECT to_jsonb(origin)::text FROM feature.feature_creation_origins AS origin ORDER BY origin.feature_id"
        ;;
      domain_commands)
        select_sql="SELECT to_jsonb(command)::text FROM ops.domain_commands AS command ORDER BY command.command_id"
        ;;
      domain_command_results)
        select_sql="SELECT to_jsonb(result)::text FROM ops.domain_command_results AS result ORDER BY result.command_id"
        ;;
      feature_requests)
        select_sql="SELECT to_jsonb(request)::text FROM ops.feature_requests AS request ORDER BY request.request_id"
        ;;
      *)
        echo "Restore verification failed: unknown manual evidence relation" >&2
        exit 1
        ;;
    esac
    output_path="$evidence_tmp/$name.jsonl"
    capture_manual_evidence_jsonl "$select_sql" "$output_path"
    actual_count="$(wc -l < "$output_path" | tr -d '[:space:]')"
    actual_sha="$(sha256sum "$output_path" | awk '{print $1}')"
    if [[ "$actual_count" != "$expected_count" || "$actual_sha" != "$expected_sha" ]]; then
      echo "Restore verification failed: manual evidence root mismatch for $name" >&2
      rm -rf "$evidence_tmp"
      exit 1
    fi
  done <<< "$manifest_rows"
  rm -rf "$evidence_tmp"
}

require_command docker
validate_identifier "$RESTORE_APP_DB" "restore app database"
validate_identifier "$RESTORE_DAGSTER_DB" "restore Dagster database"
validate_volume_name "$RESTORE_RUSTFS_VOLUME" "restore RustFS volume"

require_database "$RESTORE_APP_DB"
require_database "$RESTORE_DAGSTER_DB"

if [[ -z "$RESTORE_BACKUP_DIR" ]]; then
  if [[ -z "$RESTORE_BACKUP_ID" ]]; then
    echo "Restore verification requires KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR or KOR_TRAVEL_MAP_RESTORE_BACKUP_ID" >&2
    exit 1
  fi
  RESTORE_BACKUP_DIR="$BACKUP_ROOT/$RESTORE_BACKUP_ID"
fi

FEATURE_COUNT="$(query_scalar "$RESTORE_APP_DB" "SELECT count(*) FROM feature.features")"
FEATURE_STATS_READY="$(query_scalar "$RESTORE_APP_DB" "SELECT (last_analyze IS NOT NULL OR last_autoanalyze IS NOT NULL)::int FROM pg_stat_user_tables WHERE schemaname = 'feature' AND relname = 'features'")"
DAGSTER_TABLE_COUNT="$(query_scalar "$RESTORE_DAGSTER_DB" "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')")"

if [[ "$FEATURE_STATS_READY" != "1" ]]; then
  echo "Restore verification failed: feature.features planner statistics are missing" >&2
  exit 1
fi

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

verify_manual_feature_evidence

cat <<SUMMARY
Restore verification complete:
  app_db=${RESTORE_APP_DB} feature_count=${FEATURE_COUNT} feature_stats=ready
  dagster_db=${RESTORE_DAGSTER_DB} table_count=${DAGSTER_TABLE_COUNT}
  rustfs_volume=${RESTORE_RUSTFS_VOLUME} file_count=${RUSTFS_FILE_COUNT}
  manual_feature_evidence=verified
SUMMARY
