#!/usr/bin/env bash
set -euo pipefail

runner_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${KOR_TRAVEL_MAP_BACKUP_REPO_ROOT:-$(cd "$runner_dir/.." && pwd)}"
pg_image="${KOR_TRAVEL_MAP_BACKUP_POSTGRES_IMAGE:-postgis/postgis:16-3.5}"
postgres_container="${KOR_TRAVEL_MAP_BACKUP_POSTGRES_CONTAINER:-kor-travel-geo-postgres}"
dagster_container="${KOR_TRAVEL_MAP_BACKUP_DAGSTER_CONTAINER:-kor-travel-map-dagster-latest}"
role_lookup_user="${KOR_TRAVEL_MAP_BACKUP_ROLE_LOOKUP_USER:-kor_travel_map}"
backup_root="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$repo/data/backups}"
backup_id="${1:-${KOR_TRAVEL_MAP_RESTORE_BACKUP_ID:?backup id is required}}"
backup_dir="${KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR:-$backup_root/$backup_id}"
app_target="${KOR_TRAVEL_MAP_RESTORE_APP_DB:?KOR_TRAVEL_MAP_RESTORE_APP_DB is required}"
dagster_target="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:?KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB is required}"
rustfs_volume="${KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME:?KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME is required}"
recreate="${KOR_TRAVEL_MAP_RESTORE_RECREATE:-0}"
skip_checksum="${KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM:-0}"
skip_rustfs="${KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS:-0}"

cd "$repo"

validate_identifier() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "invalid $label: $value" >&2
    exit 2
  fi
}

validate_volume() {
  local value="$1"
  if [[ ! "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "invalid volume: $value" >&2
    exit 2
  fi
}

validate_identifier "$app_target" app_target
validate_identifier "$dagster_target" dagster_target
validate_identifier "$role_lookup_user" role_lookup_user
validate_volume "$rustfs_volume"

python_json() {
  local expr="$1"
  python - "$backup_dir/meta/manifest.json" "$expr" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
expr = sys.argv[2]
if expr == "app_dump":
    print(manifest["components"]["postgres_app"])
elif expr == "dagster_dump":
    print(manifest["components"]["postgres_dagster"])
elif expr == "rustfs":
    print(manifest["components"]["rustfs"])
else:
    raise SystemExit(f"unknown expr: {expr}")
PY
}

dsn_value() {
  local dsn="$1"
  local expr="$2"
  KTM_DSN="$dsn" KTM_EXPR="$expr" python - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit

dsn = os.environ["KTM_DSN"].replace("postgresql+asyncpg://", "postgresql://", 1)
parts = urlsplit(dsn)
expr = os.environ["KTM_EXPR"]
if expr == "user":
    print(parts.username or "")
elif expr.startswith("db:"):
    print(urlunsplit((parts.scheme, parts.netloc, "/" + expr[3:], "", "")))
else:
    raise SystemExit(f"unknown expr: {expr}")
PY
}

super_role() {
  docker exec "$postgres_container" sh -lc \
    "psql -U '$role_lookup_user' -d postgres -tAc \"select rolname from pg_roles where rolsuper order by rolname limit 1\" | tr -d '[:space:]'"
}

prepare_db() {
  local base_dsn="$1"
  local target_db="$2"
  local owner role
  owner="$(dsn_value "$base_dsn" user)"
  validate_identifier "$owner" owner
  role="$(super_role)"
  validate_identifier "$role" super_role
  if [[ "$recreate" == "1" ]]; then
    docker exec -e KTM_SUPER_ROLE="$role" -e KTM_DB="$target_db" "$postgres_container" \
      sh -lc 'psql -U "$KTM_SUPER_ROLE" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$KTM_DB\" WITH (FORCE);"'
  fi
  docker exec -e KTM_SUPER_ROLE="$role" -e KTM_DB="$target_db" -e KTM_OWNER="$owner" "$postgres_container" \
    sh -lc 'psql -U "$KTM_SUPER_ROLE" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$KTM_DB\" OWNER \"$KTM_OWNER\";"'
  docker exec -e KTM_SUPER_ROLE="$role" -e KTM_DB="$target_db" "$postgres_container" \
    sh -lc 'psql -U "$KTM_SUPER_ROLE" -d "$KTM_DB" -v ON_ERROR_STOP=1 <<SQL
CREATE SCHEMA IF NOT EXISTS x_extension;
CREATE SCHEMA IF NOT EXISTS topology;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS postgis_topology WITH SCHEMA topology;
SQL'
}

restore_db() {
  local base_dsn="$1"
  local target_db="$2"
  local dump_rel="$3"
  local role
  prepare_db "$base_dsn" "$target_db"
  role="$(super_role)"
  validate_identifier "$role" super_role
  docker exec -i -e KTM_SUPER_ROLE="$role" -e KTM_DB="$target_db" "$postgres_container" \
    sh -lc 'pg_restore --clean --if-exists --no-owner --no-privileges -U "$KTM_SUPER_ROLE" -d "$KTM_DB"' \
    < "$backup_dir/$dump_rel"
}

if [[ "$skip_checksum" != "1" ]]; then
  (cd "$backup_dir" && sha256sum -c meta/SHA256SUMS)
fi

app_dsn="${KOR_TRAVEL_MAP_PG_DSN:?KOR_TRAVEL_MAP_PG_DSN is required}"
dagster_dsn="$(docker exec "$dagster_container" sh -lc 'printenv KOR_TRAVEL_MAP_DAGSTER_PG_URL')"
restore_db "$app_dsn" "$app_target" "$(python_json app_dump)"
restore_db "$dagster_dsn" "$dagster_target" "$(python_json dagster_dump)"

if [[ "$skip_rustfs" != "1" ]]; then
  if docker volume inspect "$rustfs_volume" >/dev/null 2>&1; then
    if [[ "$recreate" != "1" ]]; then
      echo "restore RustFS volume already exists: $rustfs_volume" >&2
      exit 1
    fi
    docker volume rm "$rustfs_volume" >/dev/null
  fi
  docker volume create "$rustfs_volume" >/dev/null
  docker run --rm \
    -v "$rustfs_volume:/data" \
    -v "$backup_dir/rustfs:/backup:ro" \
    --entrypoint sh \
    "$pg_image" \
    -lc 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf /backup/rustfs-data.tar.gz -C /data'
fi

echo "restore completed into staging targets"
echo "app DB: $app_target"
echo "Dagster DB: $dagster_target"
if [[ "$skip_rustfs" != "1" ]]; then
  echo "RustFS volume: $rustfs_volume"
fi
