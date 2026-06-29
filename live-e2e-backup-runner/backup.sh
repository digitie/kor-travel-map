#!/usr/bin/env bash
set -euo pipefail

runner_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="${KOR_TRAVEL_MAP_BACKUP_REPO_ROOT:-$(cd "$runner_dir/.." && pwd)}"
pg_image="${KOR_TRAVEL_MAP_BACKUP_POSTGRES_IMAGE:-postgis/postgis:16-3.5}"
dagster_container="${KOR_TRAVEL_MAP_BACKUP_DAGSTER_CONTAINER:-kor-travel-map-dagster-latest}"
rustfs_container="${KOR_TRAVEL_MAP_BACKUP_RUSTFS_CONTAINER:-kor-travel-rustfs}"
backup_root="${KOR_TRAVEL_MAP_BACKUP_ROOT:-$repo/data/backups}"
backup_id="${KOR_TRAVEL_MAP_BACKUP_ID:?KOR_TRAVEL_MAP_BACKUP_ID is required}"
backup_dir="$backup_root/$backup_id"

cd "$repo"
mkdir -p "$backup_dir/postgres" "$backup_dir/rustfs" "$backup_dir/meta"

python_value() {
  local expr="$1"
  python - "$expr" <<'PY'
import os
import sys
from urllib.parse import urlsplit, urlunsplit

expr = sys.argv[1]
dsn = os.environ["KTM_DSN"].replace("postgresql+asyncpg://", "postgresql://", 1)
parts = urlsplit(dsn)
if expr == "db":
    print((parts.path or "").lstrip("/"))
elif expr == "normalized":
    print(dsn)
elif expr == "postgres":
    print(urlunsplit((parts.scheme, parts.netloc, "/postgres", "", "")))
else:
    raise SystemExit(f"unknown expr: {expr}")
PY
}

raw_app_dsn="${KOR_TRAVEL_MAP_PG_DSN:?KOR_TRAVEL_MAP_PG_DSN is required}"
raw_dagster_dsn="$(docker exec "$dagster_container" sh -lc 'printenv KOR_TRAVEL_MAP_DAGSTER_PG_URL')"
app_dsn="$(KTM_DSN="$raw_app_dsn" python_value normalized)"
dagster_dsn="$(KTM_DSN="$raw_dagster_dsn" python_value normalized)"
app_db="$(KTM_DSN="$app_dsn" python_value db)"
dagster_db="$(KTM_DSN="$dagster_dsn" python_value db)"
app_dump="postgres/${app_db}.dump"
dagster_dump="postgres/${dagster_db}.dump"
rustfs_archive="rustfs/rustfs-data.tar.gz"

dump_db() {
  local dsn="$1"
  local output_rel="$2"
  docker run --rm --network host \
    -v "$backup_dir/postgres:/backup" \
    -e KTM_DSN="$dsn" \
    -e KTM_OUTPUT="/backup/$(basename "$output_rel")" \
    "$pg_image" \
    sh -lc 'pg_dump "$KTM_DSN" --format=custom --no-owner --no-privileges > "$KTM_OUTPUT"'
}

echo "dumping PostgreSQL database: app"
dump_db "$app_dsn" "$app_dump"
echo "dumping PostgreSQL database: dagster"
dump_db "$dagster_dsn" "$dagster_dump"

echo "archiving RustFS data"
docker run --rm \
  --volumes-from "$rustfs_container" \
  -v "$backup_dir/rustfs:/backup" \
  --entrypoint sh \
  "$pg_image" \
  -lc 'tar czf /backup/rustfs-data.tar.gz -C /data .'

created_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export backup_id created_at_utc app_dump dagster_dump rustfs_archive app_db dagster_db
python - "$backup_dir/meta/manifest.json" <<'PY'
import json
import os
import sys

manifest = {
    "schema_version": 1,
    "backup_id": os.environ["backup_id"],
    "created_at_utc": os.environ["created_at_utc"],
    "mode": "n150-live-e2e-backup-runner",
    "components": {
        "postgres_app": os.environ["app_dump"],
        "postgres_dagster": os.environ["dagster_dump"],
        "rustfs": os.environ["rustfs_archive"],
    },
    "databases": {
        "app": os.environ["app_db"],
        "dagster": os.environ["dagster_db"],
    },
    "object_storage": {
        "feature_bucket": os.environ.get("KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET", ""),
        "offline_upload_bucket": os.environ.get("KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET", ""),
        "volume_service": "kor-travel-rustfs:/data",
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as fp:
    json.dump(manifest, fp, ensure_ascii=False, indent=2)
    fp.write("\n")
PY

(
  cd "$backup_dir"
  sha256sum "$app_dump" "$dagster_dump" "$rustfs_archive" > meta/SHA256SUMS
)

echo "backup completed: $backup_dir"
