#!/usr/bin/env bash
# `0236 → 300` baseline artifact를 검증할 disposable fresh oracle 생성기.
#
# 이 스크립트는 production DB/Compose를 절대 건드리지 않는다. 비어 있는 별도 PostgreSQL
# data volume에서 final role bootstrap을 한 번 수행하고, exact candidate API image 안의
# active `300` migration을 적용한다. 성공 뒤 기록하는 외부 receipt는
# `scripts/build-baseline.sh`가 raw `300` stamp/복제 DB를 거부하는 provenance 입력이다.
set -euo pipefail

die() { printf 'create-application-300-fresh-oracle: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
CONTAINER=""
DATABASE=""
CANDIDATE_IMAGE=""
CANDIDATE_COMMIT=""
RECEIPT=""
VOLUME=""
POSTGIS_IMAGE="postgis/postgis:16-3.5-alpine"

# external evidence는 canonical·private directory에서만 만든다. lexical prefix 검사만
# 하면 `repo/../repo`와 symlink parent를 통한 repository write를 막지 못한다.
canonicalize_receipt_target() {
  raw_target="$1"
  [[ "$raw_target" == /* ]] || die "receipt는 absolute path여야 한다"
  raw_parent="$(dirname -- "$raw_target")"
  raw_name="$(basename -- "$raw_target")"
  [ "$raw_name" != "." ] && [ "$raw_name" != ".." ] || die "receipt file name이 잘못됐다"
  [ -d "$raw_parent" ] || die "receipt parent directory가 없다"
  canonical_parent="$(realpath -e -- "$raw_parent")"
  [ "$canonical_parent" = "$raw_parent" ] || \
    die "receipt parent는 symlink·상대 경로 없는 physical directory여야 한다"
  python3 - "$canonical_parent" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("receipt parent must be a regular directory")
if metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("receipt parent must be owned by the invoking operator")
if stat.S_IMODE(metadata.st_mode) & 0o022:
    raise SystemExit("receipt parent must not be group/world writable")
PY
  canonical_target="$(realpath -m -- "$canonical_parent/$raw_name")"
  case "$canonical_target" in
    "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
      die "receipt는 repository 밖 canonical path여야 한다"
      ;;
  esac
  [[ ! -e "$canonical_target" && ! -L "$canonical_target" ]] || \
    die "receipt target이 이미 존재한다"
  RECEIPT="$canonical_target"
  RECEIPT_PARENT="$canonical_parent"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --container) CONTAINER="${2:?--container needs a value}"; shift 2 ;;
    --database) DATABASE="${2:?--database needs a value}"; shift 2 ;;
    --candidate-image) CANDIDATE_IMAGE="${2:?--candidate-image needs a value}"; shift 2 ;;
    --candidate-commit) CANDIDATE_COMMIT="${2:?--candidate-commit needs a value}"; shift 2 ;;
    --receipt) RECEIPT="${2:?--receipt needs a value}"; shift 2 ;;
    --volume) VOLUME="${2:?--volume needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) die "위치 인자는 허용하지 않는다: $1" ;;
  esac
done

[ -n "$CONTAINER" ] || die "--container가 필요하다"
[ -n "$DATABASE" ] || die "--database가 필요하다"
[ -n "$CANDIDATE_IMAGE" ] || die "--candidate-image가 필요하다"
[ -n "$CANDIDATE_COMMIT" ] || die "--candidate-commit가 필요하다"
[ -n "$RECEIPT" ] || die "--receipt가 필요하다"
[[ "$CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "container 이름이 잘못됐다"
[[ "$DATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "database 이름이 잘못됐다"
[[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "candidate commit은 full SHA-1이어야 한다"
canonicalize_receipt_target "$RECEIPT"

if [ -z "$VOLUME" ]; then
  VOLUME="${CONTAINER}-data"
fi
[[ "$VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "volume 이름이 잘못됐다"
docker container inspect "$CONTAINER" >/dev/null 2>&1 && die "container가 이미 존재한다"
docker volume inspect "$VOLUME" >/dev/null 2>&1 && die "volume이 이미 존재한다"

# 최종 proof는 uncommitted source나 이동한 image tag를 받지 않는다. baseline sidecar는
# image에 복사되므로 repository와 image 안 manifest hash도 양쪽에서 exact여야 한다.
[ -z "$(git -C "$REPOSITORY_ROOT" status --porcelain)" ] || \
  die "fresh oracle은 clean repository에서만 생성한다"
[ "$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)" = "$CANDIDATE_COMMIT" ] || \
  die "candidate commit이 current repository head와 다르다"
candidate_image_id="$(docker image inspect -f '{{.Id}}' "$CANDIDATE_IMAGE")"
candidate_image_commit="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CANDIDATE_IMAGE")"
[ "$candidate_image_commit" = "$CANDIDATE_COMMIT" ] || \
  die "candidate image OCI revision이 requested candidate commit과 다르다"
reference_manifest="$REPOSITORY_ROOT/alembic/baseline/application-reference.json"
[[ -f "$reference_manifest" && ! -L "$reference_manifest" ]] || \
  die "application reference manifest가 없다"
manifest_sha256="$(sha256sum "$reference_manifest" | awk '{print $1}')"
candidate_manifest_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
  'sha256sum /app/alembic/baseline/application-reference.json | awk '\''{print $1}'\''')"
[ "$candidate_manifest_sha256" = "$manifest_sha256" ] || \
  die "candidate image baseline manifest가 repository artifact와 다르다"
postgis_image_id="$(docker image inspect -f '{{.Id}}' "$POSTGIS_IMAGE")"
creator_script_sha256="$(sha256sum "$SCRIPT_DIR/create-application-300-fresh-oracle.sh" | awk '{print $1}')"
bootstrap_script_sha256="$(sha256sum "$REPOSITORY_ROOT/docker/postgres-role-bootstrap.sh" | awk '{print $1}')"

# Image manifest 하나만 같다고 sidecar byte 또는 active migration source까지 같다는
# 뜻은 아니다. candidate가 실제 실행할 모든 baseline 입력을 host의 exact candidate
# commit과 먼저 대조한다. 이 비교가 실패하면 oracle cluster를 만들기 전 중단한다.
candidate_migration_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
  'sha256sum /app/alembic/versions/300_schema_baseline.py | awk '\''{print $1}'\''')"
host_migration_sha256="$(sha256sum "$REPOSITORY_ROOT/alembic/versions/300_schema_baseline.py" | awk '{print $1}')"
[ "$candidate_migration_sha256" = "$host_migration_sha256" ] || \
  die "candidate image 300 migration source가 repository candidate와 다르다"
for sidecar in \
  application-catalog.sql \
  application-catalog.sha256 \
  application-reference.json \
  application-reference.sha256 \
  application-runtime-invariants.sql \
  application-seed.sql \
  application-seed.sha256 \
  schema.sql \
  seed.sql; do
  host_sidecar_sha256="$(sha256sum "$REPOSITORY_ROOT/alembic/baseline/$sidecar" | awk '{print $1}')"
  candidate_sidecar_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
    "sha256sum /app/alembic/baseline/$sidecar | cut -d ' ' -f1")"
  [ "$candidate_sidecar_sha256" = "$host_sidecar_sha256" ] || \
    die "candidate image baseline sidecar가 repository candidate와 다르다: $sidecar"
done

created_container=0
created_volume=0
receipt_tmp=""
cleanup_on_failure() {
  status=$?
  if [ "$status" -ne 0 ]; then
    [ -z "$receipt_tmp" ] || rm -f -- "$receipt_tmp"
    if [ "$created_container" = 1 ]; then
      docker container rm -f "$CONTAINER" >/dev/null 2>&1 || true
    fi
    if [ "$created_volume" = 1 ]; then
      docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    fi
  fi
  exit "$status"
}
trap cleanup_on_failure EXIT

# 이 비밀번호는 disposable cluster/한 번의 candidate migration에만 쓰며, stdout·receipt·
# repository에 기록하지 않는다. 세 LOGIN role에 독립값이 필요해지는 것은 production
# bootstrap의 concern이며 oracle은 catalog 생성 provenance만 증명한다.
oracle_password="$(openssl rand -hex 32)"
docker volume create "$VOLUME" >/dev/null
created_volume=1
docker run --pull=never -d --name "$CONTAINER" \
  --label io.kor-travel-map.application-baseline.isolated=true \
  --label io.kor-travel-map.application-baseline.fresh-300-oracle=true \
  --label io.kor-travel-map.application-baseline.fresh-bootstrap=baseline-300 \
  --label "io.kor-travel-map.application-baseline.candidate-image=$CANDIDATE_IMAGE" \
  --label "io.kor-travel-map.application-baseline.candidate-image-id=$candidate_image_id" \
  --label "io.kor-travel-map.application-baseline.candidate-commit=$CANDIDATE_COMMIT" \
  --label "io.kor-travel-map.application-baseline.candidate-manifest-sha256=$manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.postgis-image-id=$postgis_image_id" \
  --mount "type=volume,source=$VOLUME,target=/var/lib/postgresql/data" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB="$DATABASE" \
  -e POSTGRES_PASSWORD="$oracle_password" \
  "$postgis_image_id" >/dev/null
created_container=1
[ "$(docker inspect -f '{{.Image}}' "$CONTAINER")" = "$postgis_image_id" ] || \
  die "fresh oracle container가 resolved PostGIS image로 시작하지 않았다"

ready=0
for attempt in $(seq 1 45); do
  if docker exec "$CONTAINER" pg_isready -U postgres -d "$DATABASE" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || die "fresh oracle PostgreSQL이 준비되지 않았다"

bootstrap_dsn="postgresql://postgres:$oracle_password@127.0.0.1:5432/$DATABASE"
docker run --pull=never --rm --network "container:$CONTAINER" \
  --mount "type=bind,source=$REPOSITORY_ROOT/docker/postgres-role-bootstrap.sh,target=/bootstrap.sh,readonly" \
  -e KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED=true \
  -e KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE=baseline-300 \
  -e "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN=$bootstrap_dsn" \
  -e KOR_TRAVEL_MAP_POSTGRES_DB="$DATABASE" \
  -e KOR_TRAVEL_MAP_POSTGRES_USER=postgres \
  -e KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE="$DATABASE" \
  -e "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD=$oracle_password" \
  -e "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD=$oracle_password" \
  -e "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD=$oracle_password" \
  "$postgis_image_id" sh /bootstrap.sh

migrator_dsn="postgresql+asyncpg://ktm_feature_migrator:$oracle_password@127.0.0.1:5432/$DATABASE"
docker run --pull=never --rm --network "container:$CONTAINER" \
  -e "KOR_TRAVEL_MAP_PG_DSN=$migrator_dsn" \
  -e KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true \
  --entrypoint sh "$candidate_image_id" -ec 'cd /app && alembic upgrade head'

raw_revision="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version")"
[ "$raw_revision" = "300" ] || die "candidate migration 후 raw Alembic head가 exact 300이 아니다"
database_oid="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
system_identifier="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c 'SELECT system_identifier FROM pg_catalog.pg_control_system()')"
application_relation_count="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c "SELECT count(*) FROM pg_catalog.pg_class AS relation JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace WHERE namespace.nspname IN ('feature','provider_sync','ops') AND relation.relkind IN ('r','p','v','m','f','S')")"
[[ "$database_oid" =~ ^[0-9]+$ ]] || die "fresh oracle database OID를 얻지 못했다"
[[ "$system_identifier" =~ ^[0-9]+$ ]] || die "fresh oracle PostgreSQL system identifier를 얻지 못했다"
[[ "$application_relation_count" =~ ^[1-9][0-9]*$ ]] || die "candidate migration이 application relation을 만들지 않았다"
container_id="$(docker inspect -f '{{.Id}}' "$CONTAINER")"

# Fresh cluster에서 candidate의 contract SQL을 handoff와 같은 role/search_path로
# 실행한다. `alembic_version=300`만 수동으로 넣은 DB는 이 receipt의 catalog/seed
# result와 runtime invariant를 만들 수 없고, build 단계가 source와 다시 대조한다.
contract_sha256() {
  local contract="$1"
  {
    printf '%s\n' 'BEGIN;'
    printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    cat "$REPOSITORY_ROOT/alembic/baseline/$contract"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -tA \
    | sha256sum | awk '{print $1}'
}
fresh_catalog_sha256="$(contract_sha256 application-catalog.sql)"
fresh_seed_sha256="$(contract_sha256 application-seed.sql)"
runtime_invariant_violations="$(
  {
    printf '%s\n' 'BEGIN;'
    printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    cat "$REPOSITORY_ROOT/alembic/baseline/application-runtime-invariants.sql"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -tA \
    | sed '/^$/d' | wc -l | tr -d ' '
)"
[[ "$fresh_catalog_sha256" =~ ^[0-9a-f]{64}$ ]] || die "fresh oracle catalog receipt SHA-256을 얻지 못했다"
[[ "$fresh_seed_sha256" =~ ^[0-9a-f]{64}$ ]] || die "fresh oracle seed receipt SHA-256을 얻지 못했다"
[ "$runtime_invariant_violations" = "0" ] || \
  die "candidate migration 뒤 runtime projection invariant가 실패했다"

receipt_tmp="$(mktemp "$RECEIPT_PARENT/.ktm300-fresh-oracle.XXXXXX")"
python3 - "$receipt_tmp" "$container_id" "$DATABASE" "$database_oid" "$system_identifier" \
  "$CANDIDATE_IMAGE" "$candidate_image_id" "$CANDIDATE_COMMIT" "$manifest_sha256" \
  "$POSTGIS_IMAGE" "$postgis_image_id" "$creator_script_sha256" "$bootstrap_script_sha256" \
  "$candidate_migration_sha256" "$raw_revision" "$application_relation_count" \
  "$fresh_catalog_sha256" "$fresh_seed_sha256" "$runtime_invariant_violations" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
value = {
    "schema": "kor-travel-map.application-fresh-300-oracle.v2",
    "container_id": sys.argv[2],
    "database": sys.argv[3],
    "database_oid": int(sys.argv[4]),
    "postgres_system_identifier": sys.argv[5],
    "candidate_image": sys.argv[6],
    "candidate_image_id": sys.argv[7],
    "candidate_commit": sys.argv[8],
    "candidate_manifest_sha256": sys.argv[9],
    "bootstrap_phase": "baseline-300",
    "migration_command": "alembic upgrade head",
    "postgis_image": sys.argv[10],
    "postgis_image_id": sys.argv[11],
    "creator_script_sha256": sys.argv[12],
    "bootstrap_script_sha256": sys.argv[13],
    "candidate_300_migration_sha256": sys.argv[14],
    "raw_alembic_revision": sys.argv[15],
    "application_relation_count": int(sys.argv[16]),
    "catalog_sha256": sys.argv[17],
    "seed_sha256": sys.argv[18],
    "runtime_invariant_violation_count": int(sys.argv[19]),
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_tmp"
mv "$receipt_tmp" "$RECEIPT"
receipt_tmp=""
trap - EXIT

printf 'fresh 300 oracle created: container=%s database=%s candidate=%s manifest=%s\n' \
  "$CONTAINER" "$DATABASE" "$CANDIDATE_COMMIT" "$manifest_sha256"
