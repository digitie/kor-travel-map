#!/usr/bin/env bash
# `300` baseline의 historical source를 disposable DB에서 실제 재현하고 증명한다.
#
# label이나 raw alembic row만으로는 source provenance가 아니다. 이 도구는 exact clean
# detached 0236 checkout과 legacy image의 migration bytes를 먼저 확인한 뒤, 빈 cluster에서
# legacy → M01 → M05 choreography를 실행한다. old graph는 이 legacy image 안에서만 쓰며
# current production image/active migration tree에는 mount·copy·import하지 않는다.
set -euo pipefail

die() { printf 'create-application-0236-source-oracle: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
SOURCE_ROOT=""
SOURCE_SEALED_ROOT=""
SOURCE_SEALED_PARENT=""
SOURCE_IMAGE=""
CONTAINER=""
DATABASE=""
RECEIPT=""
VOLUME=""
POSTGIS_IMAGE="postgis/postgis:16-3.5-alpine"
SOURCE_DATABASE_TEMPLATE="template1"
POSTGIS_BOOTSTRAP_DATABASE="postgres"
SOURCE_COMMIT="01d65b2ad4ee265a3ef6b01448f6abf573a906a8"
SOURCE_HEAD="0236_tvn41s_compaction_drained"
SOURCE_MIGRATION_TREE="cb52c39e3d0f37bfe229532d94c2c91ea289b725"
RETIRED_MANIFEST_SHA256="3a3e96da12e8c8517fcac094749451307bb2b43e9bac249f2abe8864601d136e"
CHOREOGRAPHY="legacy-bootstrap>0225>m01-bootstrap>0232>0233>m05-pre-bootstrap>0235>0236>m05-repair-bootstrap"

# certificate는 repository 안에 남기지 않는다. lexical prefix만 검사하면
# `/repo/../repo/...`나 symlink parent로 이 경계를 우회할 수 있으므로, 처음부터
# physical·private parent와 canonical target을 사용한다.
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
    --source-root) SOURCE_ROOT="${2:?--source-root needs a value}"; shift 2 ;;
    --source-image) SOURCE_IMAGE="${2:?--source-image needs a value}"; shift 2 ;;
    --container) CONTAINER="${2:?--container needs a value}"; shift 2 ;;
    --database) DATABASE="${2:?--database needs a value}"; shift 2 ;;
    --receipt) RECEIPT="${2:?--receipt needs a value}"; shift 2 ;;
    --volume) VOLUME="${2:?--volume needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) die "위치 인자는 허용하지 않는다: $1" ;;
  esac
done

[ -n "$SOURCE_ROOT" ] || die "--source-root가 필요하다"
[ -n "$SOURCE_IMAGE" ] || die "--source-image가 필요하다"
[ -n "$CONTAINER" ] || die "--container가 필요하다"
[ -n "$DATABASE" ] || die "--database가 필요하다"
[ -n "$RECEIPT" ] || die "--receipt가 필요하다"
[[ "$SOURCE_ROOT" == /* && -d "$SOURCE_ROOT" ]] || die "source root는 absolute directory여야 한다"
[[ "$CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "container 이름이 잘못됐다"
[[ "$DATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "database 이름이 잘못됐다"
SOURCE_ROOT="$(realpath -e -- "$SOURCE_ROOT")"
canonicalize_receipt_target "$RECEIPT"
if [ -z "$VOLUME" ]; then VOLUME="${CONTAINER}-data"; fi
[[ "$VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "volume 이름이 잘못됐다"
docker container inspect "$CONTAINER" >/dev/null 2>&1 && die "container가 이미 존재한다"
docker volume inspect "$VOLUME" >/dev/null 2>&1 && die "volume이 이미 존재한다"

# source root는 mutable checkout이 아니라 exact Git object를 읽을 수 있는 local object
# store일 뿐이다. historical image build·bind·manifest의 physical input은 아래 detached
# archive 한 벌만 사용한다. 이 경계를 두지 않으면 archive 대상 commit은 맞아도 checkout의
# untracked/modified Dockerfile·bootstrap script를 source proof에 섞을 수 있다.
git -C "$SOURCE_ROOT" cat-file -e "${SOURCE_COMMIT}^{commit}" || \
  die "source root에 requested source commit object가 없다"
[ "$(git -C "$SOURCE_ROOT" rev-parse "$SOURCE_COMMIT:alembic/versions")" = "$SOURCE_MIGRATION_TREE" ] || \
  die "source migration tree가 다르다"
SOURCE_SEALED_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-source-sealed.XXXXXX")"
SOURCE_SEALED_ROOT="$SOURCE_SEALED_PARENT/source"
mkdir "$SOURCE_SEALED_ROOT"
if ! git -C "$SOURCE_ROOT" archive --format=tar "$SOURCE_COMMIT" \
  | tar -x -C "$SOURCE_SEALED_ROOT"; then
  rm -rf -- "$SOURCE_SEALED_PARENT"
  SOURCE_SEALED_PARENT=""
  SOURCE_SEALED_ROOT=""
  die "source Git archive를 만들지 못했다"
fi
python3 - "$SOURCE_SEALED_ROOT" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
for path in [root, *root.rglob("*")]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"sealed source contains a symlink: {path.relative_to(root)}")
    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise SystemExit(f"sealed source contains a non-regular entry: {path.relative_to(root)}")
for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
    os.chmod(path, 0o555 if path.is_dir() else 0o444)
os.chmod(root, 0o555)
PY
cleanup_source_seal() {
  [ -z "$SOURCE_SEALED_PARENT" ] || rm -rf -- "$SOURCE_SEALED_PARENT"
}
trap cleanup_source_seal EXIT
manifest="$REPOSITORY_ROOT/alembic/retired_versions/0200-0236/manifest.sha256"
[ "$(sha256sum "$manifest" | awk '{print $1}')" = "$RETIRED_MANIFEST_SHA256" ] || \
  die "retired migration manifest digest가 다르다"
python3 - "$SOURCE_SEALED_ROOT" "$manifest" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "alembic" / "versions"
for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    expected, name = line.split(maxsplit=1)
    path = root / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f"source migration does not match retired manifest: {name}")
PY

# arbitrary prebuilt image는 historical source의 증명이 아니다. exact Git archive의
# Dockerfile을 oracle이 직접 no-cache build하고, 이후에는 그 immutable ID만
# 실행한다. Dockerfile의 과거 `python:3.12-slim` tag와 range dependency는 source를
# 다시 쓰지 않고 그때 실제로 resolve된 base image와 installed distribution SBOM을
# certificate에 묶는다. tag를 inspect한 뒤 그대로 build하면 pull race가 남으므로,
# build에는 exact \`python@sha256:…\`만 넣은 외부 one-shot Dockerfile을 쓴다. image tag는
# build output에 붙이는 편의 이름일 뿐 실행 입력이 아니다.
SOURCE_BUILDER_BASE_IMAGE="python:3.12-slim"
python3 - "$SOURCE_SEALED_ROOT/docker/api.Dockerfile" "$SOURCE_BUILDER_BASE_IMAGE" <<'PY'
import sys
from pathlib import Path

dockerfile = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
expected = {
    f"FROM {sys.argv[2]} AS builder",
    f"FROM {sys.argv[2]} AS runtime",
}
actual = {line.strip() for line in dockerfile if line.strip().startswith("FROM ")}
if actual != expected:
    raise SystemExit("legacy Dockerfile base image declarations are not exact")
PY
source_builder_base_image_id="$(docker image inspect -f '{{.Id}}' "$SOURCE_BUILDER_BASE_IMAGE")"
[[ "$source_builder_base_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "source builder base image ID를 얻지 못했다"
source_builder_base_image_reference="$(docker image inspect -f '{{index .RepoDigests 0}}' "$SOURCE_BUILDER_BASE_IMAGE")"
[[ "$source_builder_base_image_reference" =~ ^python@sha256:[0-9a-f]{64}$ ]] || \
  die "source builder immutable base image reference를 얻지 못했다"
source_build_dockerfile="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-dockerfile.XXXXXX")"
python3 - "$SOURCE_SEALED_ROOT/docker/api.Dockerfile" "$source_builder_base_image_reference" \
  "$source_build_dockerfile" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
reference = sys.argv[2]
replacement = source.replace(
    "FROM python:3.12-slim AS builder",
    "FROM " + reference + " AS builder",
).replace(
    "FROM python:3.12-slim AS runtime",
    "FROM " + reference + " AS runtime",
)
if replacement == source or replacement.count(reference) != 2:
    raise SystemExit("legacy source Dockerfile immutable base substitution failed")
Path(sys.argv[3]).write_text(replacement, encoding="utf-8")
PY
source_build_dockerfile_sha256="$(sha256sum "$source_build_dockerfile" | awk '{print $1}')"
source_build_log="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-build.XXXXXX")"
if ! docker build --pull=false --no-cache \
  --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$SOURCE_COMMIT" \
  -t "$SOURCE_IMAGE" -f "$source_build_dockerfile" "$SOURCE_SEALED_ROOT" \
  >"$source_build_log" 2>&1; then
  tail -n 80 "$source_build_log" >&2 || true
  rm -f -- "$source_build_log"
  rm -f -- "$source_build_dockerfile"
  source_build_log=""
  source_build_dockerfile=""
  die "detached source image build가 실패했다"
fi
rm -f -- "$source_build_log"
rm -f -- "$source_build_dockerfile"
source_build_log=""
source_build_dockerfile=""
source_image_id="$(docker image inspect -f '{{.Id}}' "$SOURCE_IMAGE")"
[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$SOURCE_IMAGE")" = "$SOURCE_COMMIT" ] || \
  die "source image OCI revision이 다르다"
postgis_image_id="$(docker image inspect -f '{{.Id}}' "$POSTGIS_IMAGE")"
source_git_tree="$(git -C "$SOURCE_ROOT" rev-parse "$SOURCE_COMMIT^{tree}")"
source_dockerfile_sha256="$(sha256sum "$SOURCE_SEALED_ROOT/docker/api.Dockerfile" | awk '{print $1}')"

# old graph가 실제 실행하는 모든 /app input을 one manifest로 비교한다. 이것은
# env.py/versions 일부만 맞춘 변조 image가 helper SQL이나 alembic.ini로 raw 0236을
# 위조하는 것을 막는다.
source_app_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-app.XXXXXX")"
source_image_app_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-image-app.XXXXXX")"
python3 - "$SOURCE_SEALED_ROOT" >"$source_app_manifest" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
items: dict[str, Path] = {}

def add(source_rel: str, destination_rel: str) -> None:
    source = root / source_rel
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"required source file is missing or symlinked: {source_rel}")
    if destination_rel in items:
        raise SystemExit(f"duplicate source image destination: {destination_rel}")
    items[destination_rel] = source

for name in ("alembic.ini", "alembic/env.py", "alembic/script.py.mako"):
    add(name, name)
for directory in ("alembic/baseline", "alembic/versions", "resources/curations"):
    base = root / directory
    if not base.is_dir() or base.is_symlink():
        raise SystemExit(f"required source directory is missing or symlinked: {directory}")
    for source in sorted(
        (
            path for path in base.rglob("*")
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        add(source.relative_to(root).as_posix(), source.relative_to(root).as_posix())
for name in (
    "docker/api-entrypoint.sh",
    "docker/migrate-to-m01-bootstrap-boundary.sh",
    "docker/migrate-to-m05-bootstrap-boundary.sh",
    "docker/migrate-m05.sh",
    "docker/pre-squash-revisions.txt",
):
    add(name, name)

for destination, source in sorted(items.items()):
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --entrypoint python "$source_image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
root = Path("/app")
paths = (
    candidate for candidate in root.rglob("*")
    if candidate.is_file() and not candidate.is_symlink() and "__pycache__" not in candidate.parts
)
for path in sorted(paths, key=lambda candidate: candidate.relative_to(root).as_posix()):
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
' >"$source_image_app_manifest"
cmp -s "$source_app_manifest" "$source_image_app_manifest" || \
  die "source image /app 실행 입력이 sealed Git archive와 다르다"
source_image_app_manifest_sha256="$(sha256sum "$source_app_manifest" | awk '{print $1}')"

# migration이 import하는 project runtime도 wheel install 결과가 source와 동일해야
# 한다. generated pyc·dist-info는 제외하고, 실행 가능한 source package bytes만 strict
# 비교한다.
source_runtime_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-runtime.XXXXXX")"
source_image_runtime_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-image-runtime.XXXXXX")"
python3 - "$SOURCE_SEALED_ROOT" >"$source_runtime_manifest" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
items: dict[str, Path] = {}
for source_prefix, destination_prefix in (
    ("src/kortravelmap", ""),
    ("packages/kor-travel-map-api/src/kortravelmap/api", "api"),
):
    base = root / source_prefix
    if not base.is_dir() or base.is_symlink():
        raise SystemExit(f"runtime source directory is missing or symlinked: {source_prefix}")
    for source in sorted(
        (path for path in base.rglob("*") if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(base).as_posix(),
    ):
        relative = source.relative_to(base).as_posix()
        destination = "/".join(part for part in (destination_prefix, relative) if part)
        if destination in items:
            raise SystemExit(f"duplicate installed runtime destination: {destination}")
        items[destination] = source
for destination, source in sorted(items.items()):
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --entrypoint python "$source_image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
root = Path("/usr/local/lib/python3.12/site-packages/kortravelmap")
for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink()):
    relative = path.relative_to(root).as_posix()
    if "__pycache__/" in relative or not (relative.endswith(".py") or relative.endswith(".json") or relative.endswith("py.typed")):
        continue
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
' >"$source_image_runtime_manifest"
cmp -s "$source_runtime_manifest" "$source_image_runtime_manifest" || \
  die "source image migration runtime import tree가 sealed Git archive와 다르다"
source_image_runtime_manifest_sha256="$(sha256sum "$source_runtime_manifest" | awk '{print $1}')"

# historical dependency spec에는 range가 있어 rebuild 결과를 image ID만으로 설명하기
# 어렵다. installed distribution name/version 목록을 canonical SBOM으로 남겨 source
# image의 실제 runtime dependency closure를 certificate와 DB-container label에 결박한다.
source_image_dependency_sbom="$(mktemp "${TMPDIR:-/tmp}/ktm300-source-image-sbom.XXXXXX")"
docker run --pull=never --rm --entrypoint python "$source_image_id" -c '
from __future__ import annotations

from importlib.metadata import distributions

rows = []
for distribution in distributions():
    name = distribution.metadata.get("Name")
    if not name:
        raise SystemExit("installed distribution without a name")
    rows.append((name.casefold(), name, distribution.version))
for _, name, version in sorted(rows):
    print(f"{name}=={version}")
' >"$source_image_dependency_sbom"
[ -s "$source_image_dependency_sbom" ] || die "source image dependency SBOM이 비어 있다"
source_image_dependency_sbom_sha256="$(sha256sum "$source_image_dependency_sbom" | awk '{print $1}')"

created_container=0
created_volume=0
receipt_tmp=""
cleanup() {
  status=$?
  [ -z "${source_app_manifest:-}" ] || rm -f -- "$source_app_manifest"
  [ -z "${source_image_app_manifest:-}" ] || rm -f -- "$source_image_app_manifest"
  [ -z "${source_runtime_manifest:-}" ] || rm -f -- "$source_runtime_manifest"
  [ -z "${source_image_runtime_manifest:-}" ] || rm -f -- "$source_image_runtime_manifest"
  [ -z "${source_image_dependency_sbom:-}" ] || rm -f -- "$source_image_dependency_sbom"
  [ -z "${source_build_dockerfile:-}" ] || rm -f -- "$source_build_dockerfile"
  [ -z "${SOURCE_SEALED_PARENT:-}" ] || rm -rf -- "$SOURCE_SEALED_PARENT"
  SOURCE_SEALED_PARENT=""
  SOURCE_SEALED_ROOT=""
  if [ "$status" -ne 0 ]; then
    [ -z "$receipt_tmp" ] || rm -f -- "$receipt_tmp"
    [ "$created_container" = 0 ] || docker container rm -f "$CONTAINER" >/dev/null 2>&1 || true
    [ "$created_volume" = 0 ] || docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

oracle_password="$(openssl rand -hex 32)"
docker volume create "$VOLUME" >/dev/null
created_volume=1
docker run --pull=never -d --name "$CONTAINER" \
  --label io.kor-travel-map.application-baseline.isolated=true \
  --label io.kor-travel-map.application-baseline.source-0236-oracle=true \
  --label "io.kor-travel-map.application-baseline.source-commit=$SOURCE_COMMIT" \
  --label "io.kor-travel-map.application-baseline.source-head=$SOURCE_HEAD" \
  --label "io.kor-travel-map.application-baseline.source-image-id=$source_image_id" \
  --label "io.kor-travel-map.application-baseline.source-migration-tree=$SOURCE_MIGRATION_TREE" \
  --label "io.kor-travel-map.application-baseline.source-git-tree=$source_git_tree" \
  --label "io.kor-travel-map.application-baseline.source-dockerfile-sha256=$source_dockerfile_sha256" \
  --label "io.kor-travel-map.application-baseline.source-image-app-manifest-sha256=$source_image_app_manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.source-image-runtime-manifest-sha256=$source_image_runtime_manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.source-builder-base-image-id=$source_builder_base_image_id" \
  --label "io.kor-travel-map.application-baseline.source-builder-base-image-reference=$source_builder_base_image_reference" \
  --label "io.kor-travel-map.application-baseline.source-build-dockerfile-sha256=$source_build_dockerfile_sha256" \
  --label "io.kor-travel-map.application-baseline.source-image-dependency-sbom-sha256=$source_image_dependency_sbom_sha256" \
  --mount "type=volume,source=$VOLUME,target=/var/lib/postgresql/data" \
  -e POSTGRES_USER=postgres -e POSTGRES_DB="$POSTGIS_BOOTSTRAP_DATABASE" -e POSTGRES_PASSWORD="$oracle_password" \
  "$postgis_image_id" >/dev/null
created_container=1
[ "$(docker inspect -f '{{.Image}}' "$CONTAINER")" = "$postgis_image_id" ] || \
  die "source oracle container image ID가 resolved PostGIS image와 다르다"

# `pg_isready`는 entrypoint가 temporary postmaster를 올린 직후에도 성공한다. 그 시점에는
# /docker-entrypoint-initdb.d의 PostGIS 초기화가 아직 끝나지 않았으므로, 새 source DB는
# 반드시 official entrypoint의 init-complete marker 이후 template1에서 명시적으로 만든다.
ready=0
for attempt in $(seq 1 45); do
  if docker logs "$CONTAINER" 2>&1 | grep -Fq 'PostgreSQL init process complete' \
    && docker exec "$CONTAINER" pg_isready -U postgres -d "$POSTGIS_BOOTSTRAP_DATABASE" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || die "source oracle official PostGIS initialization이 준비되지 않았다"

docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$POSTGIS_BOOTSTRAP_DATABASE" \
  -c "CREATE DATABASE \"$DATABASE\" TEMPLATE $SOURCE_DATABASE_TEMPLATE" >/dev/null

# legacy choreography에 들어가기 전 source DB가 정말 template1의 virgin 상태인지
# fail-close한다. `postgres-role-bootstrap.sh`의 fresh precondition과 동일한 catalog
# 영역을 빠짐없이 receipt에 담는다. relation 수만 0인 경우에는 routine/type/cast/FDW
# 같은 residue를 놓칠 수 있으므로, 하나의 canonical JSON inventory와 digest를 모두
# certificate에 고정한다. 이 inventory는 POSTGRES_DB 자동 생성 경로가 다시 섞여도
# materializer가 받지 않게 하는 source provenance의 일부다.
source_initial_virgin_inventory="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c "
WITH reserved_roles AS (
  SELECT role.oid, role.rolname
  FROM pg_catalog.pg_roles AS role
  WHERE role.rolname LIKE 'ktm\\_%' ESCAPE '\\'
),
application_objects AS (
  SELECT 1
  FROM pg_catalog.pg_class AS object
  JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.relnamespace
  WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  UNION ALL
  SELECT 1
  FROM pg_catalog.pg_proc AS object
  JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.pronamespace
  WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
  UNION ALL
  SELECT 1
  FROM pg_catalog.pg_type AS object
  JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.typnamespace
  WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    AND object.typtype IN ('b', 'c', 'd', 'e', 'r')
)
SELECT jsonb_build_object(
  'application_object_count', (SELECT count(*) FROM application_objects),
  'application_schema_count', (
    SELECT count(*) FROM pg_catalog.pg_namespace
    WHERE nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
  ),
  'database_or_role_setting_count', (
    SELECT count(*)
    FROM pg_catalog.pg_db_role_setting AS setting_row
    WHERE setting_row.setdatabase = (
      SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
    )
       OR setting_row.setrole IN (SELECT oid FROM reserved_roles)
  ),
  'default_acl_count', (SELECT count(*) FROM pg_catalog.pg_default_acl),
  'event_trigger_count', (SELECT count(*) FROM pg_catalog.pg_event_trigger),
  'extension_inventory', COALESCE((
    SELECT jsonb_agg(extension.extname || '@' || namespace.nspname ORDER BY extension.extname)
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
  ), '[]'::jsonb),
  'foreign_data_wrapper_count', (SELECT count(*) FROM pg_catalog.pg_foreign_data_wrapper),
  'foreign_server_count', (SELECT count(*) FROM pg_catalog.pg_foreign_server),
  'non_system_schema_inventory', COALESCE((
    SELECT jsonb_agg(namespace.nspname ORDER BY namespace.nspname)
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname !~ '^pg_' AND namespace.nspname <> 'information_schema'
  ), '[]'::jsonb),
  'public_cast_count', (
    SELECT count(*)
    FROM pg_catalog.pg_cast AS object
    JOIN pg_catalog.pg_type AS source_type ON source_type.oid = object.castsource
    JOIN pg_catalog.pg_type AS target_type ON target_type.oid = object.casttarget
    JOIN pg_catalog.pg_namespace AS source_namespace
      ON source_namespace.oid = source_type.typnamespace
    JOIN pg_catalog.pg_namespace AS target_namespace
      ON target_namespace.oid = target_type.typnamespace
    WHERE source_namespace.nspname = 'public' OR target_namespace.nspname = 'public'
  ),
  'public_collation_count', (
    SELECT count(*)
    FROM pg_catalog.pg_collation AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.collnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_operator_count', (
    SELECT count(*)
    FROM pg_catalog.pg_operator AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.oprnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_proc_count', (
    SELECT count(*)
    FROM pg_catalog.pg_proc AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.pronamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_relation_count', (
    SELECT count(*)
    FROM pg_catalog.pg_class AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.relnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_schema_acl', COALESCE((
    SELECT to_jsonb(ARRAY(
      SELECT entry::text
      FROM pg_catalog.pg_namespace AS namespace
      CROSS JOIN LATERAL unnest(namespace.nspacl) AS entry
      WHERE namespace.nspname = 'public'
      ORDER BY entry::text
    ))
  ), '[]'::jsonb),
  'public_schema_owner', COALESCE((
    SELECT namespace.nspowner::regrole::text
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname = 'public'
  ), '<missing>'),
  'public_text_search_config_count', (
    SELECT count(*)
    FROM pg_catalog.pg_ts_config AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.cfgnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_text_search_dict_count', (
    SELECT count(*)
    FROM pg_catalog.pg_ts_dict AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.dictnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_text_search_parser_count', (
    SELECT count(*)
    FROM pg_catalog.pg_ts_parser AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.prsnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_text_search_template_count', (
    SELECT count(*)
    FROM pg_catalog.pg_ts_template AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.tmplnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_conversion_count', (
    SELECT count(*)
    FROM pg_catalog.pg_conversion AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.connamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_opfamily_count', (
    SELECT count(*)
    FROM pg_catalog.pg_opfamily AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.opfnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_opclass_count', (
    SELECT count(*)
    FROM pg_catalog.pg_opclass AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.opcnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_amop_count', (
    SELECT count(*)
    FROM pg_catalog.pg_amop AS object
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amopfamily
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_amproc_count', (
    SELECT count(*)
    FROM pg_catalog.pg_amproc AS object
    JOIN pg_catalog.pg_opfamily AS family ON family.oid = object.amprocfamily
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = family.opfnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_transform_count', (
    SELECT count(*)
    FROM pg_catalog.pg_transform AS object
    JOIN pg_catalog.pg_type AS type_row ON type_row.oid = object.trftype
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname = 'public'
  ),
  'public_type_count', (
    SELECT count(*)
    FROM pg_catalog.pg_type AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.typnamespace
    WHERE namespace.nspname = 'public'
  ),
  'publication_count', (SELECT count(*) FROM pg_catalog.pg_publication),
  'reserved_application_role_inventory', COALESCE((
    SELECT jsonb_agg(role.rolname ORDER BY role.rolname) FROM reserved_roles AS role
  ), '[]'::jsonb),
  'subscription_count', (
    SELECT count(*)
    FROM pg_catalog.pg_subscription AS subscription
    WHERE subscription.subdbid = (
      SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
    )
  ),
  'user_mapping_count', (SELECT count(*) FROM pg_catalog.pg_user_mapping)
)::text
")"
source_initial_virgin_inventory="$(python3 - "$source_initial_virgin_inventory" <<'PY'
from __future__ import annotations

import json
import sys

print(json.dumps(json.loads(sys.argv[1]), sort_keys=True, separators=(",", ":")))
PY
)"
source_initial_virgin_inventory_sha256="$(printf '%s' "$source_initial_virgin_inventory" | sha256sum | awk '{print $1}')"
python3 - "$source_initial_virgin_inventory" "$source_initial_virgin_inventory_sha256" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys

expected = {
    "application_object_count": 0,
    "application_schema_count": 0,
    "database_or_role_setting_count": 0,
    "default_acl_count": 0,
    "event_trigger_count": 0,
    "extension_inventory": ["plpgsql@pg_catalog"],
    "foreign_data_wrapper_count": 0,
    "foreign_server_count": 0,
    "non_system_schema_inventory": ["public"],
    "public_cast_count": 0,
    "public_collation_count": 0,
    "public_conversion_count": 0,
    "public_amop_count": 0,
    "public_amproc_count": 0,
    "public_opclass_count": 0,
    "public_opfamily_count": 0,
    "public_operator_count": 0,
    "public_proc_count": 0,
    "public_relation_count": 0,
    "public_schema_acl": ["=U/pg_database_owner", "pg_database_owner=UC/pg_database_owner"],
    "public_schema_owner": "pg_database_owner",
    "public_text_search_config_count": 0,
    "public_text_search_dict_count": 0,
    "public_text_search_parser_count": 0,
    "public_text_search_template_count": 0,
    "public_transform_count": 0,
    "public_type_count": 0,
    "publication_count": 0,
    "reserved_application_role_inventory": [],
    "subscription_count": 0,
    "user_mapping_count": 0,
}
try:
    observed = json.loads(sys.argv[1])
except ValueError as exc:
    raise SystemExit(f"source initial virgin inventory is not JSON: {exc}") from exc
if observed != expected:
    raise SystemExit(f"source template1 DB is not virgin: {json.dumps(observed, sort_keys=True)}")
if hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest() != sys.argv[2]:
    raise SystemExit("source initial virgin inventory digest is inconsistent")
PY

bootstrap_dsn="postgresql://postgres:$oracle_password@127.0.0.1:5432/$DATABASE"
migrator_dsn="postgresql+asyncpg://ktm_feature_migrator:$oracle_password@127.0.0.1:5432/$DATABASE"
bootstrap() {
  docker run --pull=never --rm --network "container:$CONTAINER" \
    --mount "type=bind,source=$SOURCE_SEALED_ROOT/docker/postgres-role-bootstrap.sh,target=/bootstrap.sh,readonly" \
    -e KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED=true \
    -e "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE=$1" \
    -e "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN=$bootstrap_dsn" \
    -e "KOR_TRAVEL_MAP_POSTGRES_DB=$DATABASE" -e KOR_TRAVEL_MAP_POSTGRES_USER=postgres \
    -e "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE=$DATABASE" \
    -e "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD=$oracle_password" \
    -e "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD=$oracle_password" \
    -e "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD=$oracle_password" \
    "$postgis_image_id" sh /bootstrap.sh
}
migrate() {
  docker run --pull=never --rm --network "container:$CONTAINER" \
    -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$migrator_dsn" -e "KOR_TRAVEL_MAP_PG_DSN=$migrator_dsn" \
    -e KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true \
    --entrypoint sh "$source_image_id" -ec "cd /app && $1"
}

bootstrap legacy
migrate './docker/migrate-to-m01-bootstrap-boundary.sh'
bootstrap m01
migrate 'alembic upgrade 0232_tvn37d_notice_empty_range'
migrate './docker/migrate-to-m05-bootstrap-boundary.sh'
bootstrap m05-pre
migrate './docker/migrate-m05.sh'
migrate 'alembic upgrade 0236_tvn41s_compaction_drained'
bootstrap m05-repair

revision="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version")"
[ "$revision" = "$SOURCE_HEAD" ] || die "source oracle raw Alembic head가 exact 0236이 아니다"
server_version_num="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c 'SHOW server_version_num')"
postgis_extension_version="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c "SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'postgis'")"
database_oid="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
system_identifier="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c 'SELECT system_identifier FROM pg_catalog.pg_control_system()')"
[[ "$server_version_num" =~ ^[0-9]+$ && "$postgis_extension_version" =~ ^[0-9]+(\.[0-9]+)+$ ]] || \
  die "source oracle PostgreSQL/PostGIS version을 얻지 못했다"
[[ "$database_oid" =~ ^[0-9]+$ && "$system_identifier" =~ ^[0-9]+$ ]] || die "source oracle DB identity를 얻지 못했다"
container_id="$(docker inspect -f '{{.Id}}' "$CONTAINER")"
creator_sha="$(sha256sum "$SCRIPT_DIR/create-application-0236-source-oracle.sh" | awk '{print $1}')"
bootstrap_sha="$(sha256sum "$SOURCE_SEALED_ROOT/docker/postgres-role-bootstrap.sh" | awk '{print $1}')"

receipt_tmp="$(mktemp "$RECEIPT_PARENT/.ktm300-source-0236.XXXXXX")"
python3 - "$receipt_tmp" "$container_id" "$DATABASE" "$database_oid" "$system_identifier" \
  "$source_image_id" "$postgis_image_id" "$creator_sha" "$bootstrap_sha" "$revision" \
  "$server_version_num" "$postgis_extension_version" "$source_git_tree" "$source_dockerfile_sha256" \
  "$source_image_app_manifest_sha256" "$source_image_runtime_manifest_sha256" \
  "$source_builder_base_image_id" "$source_builder_base_image_reference" \
  "$source_build_dockerfile_sha256" "$source_image_dependency_sbom_sha256" \
  "$SOURCE_DATABASE_TEMPLATE" "$source_initial_virgin_inventory" \
  "$source_initial_virgin_inventory_sha256" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
value = {
  "schema": "kor-travel-map.application-source-0236-oracle.v8",
  "container_id": sys.argv[2], "database": sys.argv[3], "database_oid": int(sys.argv[4]),
  "postgres_system_identifier": sys.argv[5], "source_commit": "01d65b2ad4ee265a3ef6b01448f6abf573a906a8",
  "source_head": "0236_tvn41s_compaction_drained", "source_migration_tree": "cb52c39e3d0f37bfe229532d94c2c91ea289b725",
  "retired_manifest_sha256": "3a3e96da12e8c8517fcac094749451307bb2b43e9bac249f2abe8864601d136e",
  "source_image_id": sys.argv[6], "postgis_image_id": sys.argv[7],
  "creator_script_sha256": sys.argv[8], "source_bootstrap_sha256": sys.argv[9],
  "migration_choreography": "legacy-bootstrap>0225>m01-bootstrap>0232>0233>m05-pre-bootstrap>0235>0236>m05-repair-bootstrap",
  "raw_alembic_revision": sys.argv[10], "postgres_server_version_num": sys.argv[11],
  "postgis_extension_version": sys.argv[12], "source_git_tree": sys.argv[13],
  "source_dockerfile_sha256": sys.argv[14], "source_image_app_manifest_sha256": sys.argv[15],
  "source_image_runtime_manifest_sha256": sys.argv[16],
  "source_builder_base_image_id": sys.argv[17],
  "source_builder_base_image_reference": sys.argv[18],
  "source_build_dockerfile_sha256": sys.argv[19],
  "source_image_dependency_sbom_sha256": sys.argv[20],
  "source_database_provisioning": "explicit-create-database-from-template1-after-official-entrypoint-complete",
  "source_database_template": sys.argv[21],
  "source_initial_virgin_inventory": json.loads(sys.argv[22]),
  "source_initial_virgin_inventory_sha256": sys.argv[23],
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_tmp"
mv "$receipt_tmp" "$RECEIPT"
receipt_tmp=""
[ -z "${source_app_manifest:-}" ] || rm -f -- "$source_app_manifest"
[ -z "${source_image_app_manifest:-}" ] || rm -f -- "$source_image_app_manifest"
[ -z "${source_runtime_manifest:-}" ] || rm -f -- "$source_runtime_manifest"
[ -z "${source_image_runtime_manifest:-}" ] || rm -f -- "$source_image_runtime_manifest"
[ -z "${source_image_dependency_sbom:-}" ] || rm -f -- "$source_image_dependency_sbom"
[ -z "${source_build_dockerfile:-}" ] || rm -f -- "$source_build_dockerfile"
source_app_manifest=""
source_image_app_manifest=""
source_runtime_manifest=""
source_image_runtime_manifest=""
source_image_dependency_sbom=""
cleanup_source_seal
SOURCE_SEALED_PARENT=""
SOURCE_SEALED_ROOT=""
trap - EXIT
printf '0236 source oracle created: container=%s database=%s source=%s\n' "$CONTAINER" "$DATABASE" "$SOURCE_COMMIT"
