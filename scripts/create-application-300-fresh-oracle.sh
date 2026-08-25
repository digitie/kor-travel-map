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
CANDIDATE_SEALED_PARENT=""
CANDIDATE_SEALED_ROOT=""
CANDIDATE_GIT_TREE=""
CANDIDATE_DOCKERFILE_SHA256=""
CANDIDATE_BASE_IMAGE_REFERENCE=""
CANDIDATE_BASE_IMAGE_ID=""
CANDIDATE_BASE_ROOTFS_LAYERS_SHA256=""
CANDIDATE_FULL_ROOTFS_LAYERS_SHA256=""
CANDIDATE_BUILD_RECEIPT=""
CANDIDATE_BUILD_RECEIPT_SHA256=""
CANDIDATE_PROVENANCE_JSON=""
RECEIPT=""
VOLUME=""
FRESH_MIGRATE_FENCE_VOLUME=""
FRESH_FINALIZE_FENCE_VOLUME=""
POSTGIS_IMAGE="postgis/postgis:16-3.5-alpine"
FRESH_DATABASE_TEMPLATE="template1"
POSTGIS_BOOTSTRAP_DATABASE="postgres"

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
    --candidate-build-receipt) CANDIDATE_BUILD_RECEIPT="${2:?--candidate-build-receipt needs a value}"; shift 2 ;;
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
[ -n "$CANDIDATE_BUILD_RECEIPT" ] || die "--candidate-build-receipt가 필요하다"
[ -n "$RECEIPT" ] || die "--receipt가 필요하다"
[[ "$CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "container 이름이 잘못됐다"
[[ "$DATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "database 이름이 잘못됐다"
[[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "candidate commit은 full SHA-1이어야 한다"
canonicalize_receipt_target "$RECEIPT"

# fresh oracle은 candidate image를 다시 계산해도 되지만, 같은 tag를 나중에 다른 image로
# 바꿔 끼운 일을 놓치지 않으려면 sealed build 시점의 full RootFS/image-ID receipt에도
# 결박돼야 한다. verifier가 external receipt의 owner/mode/path와 모든 byte proof를
# fail-close로 검사한다.
CANDIDATE_PROVENANCE_JSON="$(bash "$SCRIPT_DIR/build-application-300-candidate.sh" \
  --verify --candidate-commit "$CANDIDATE_COMMIT" --image "$CANDIDATE_IMAGE" \
  --git-root "$REPOSITORY_ROOT" --receipt "$CANDIDATE_BUILD_RECEIPT")"
CANDIDATE_BUILD_RECEIPT_SHA256="$(sha256sum "$CANDIDATE_BUILD_RECEIPT" | awk '{print $1}')"
[[ "$CANDIDATE_BUILD_RECEIPT_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate build receipt SHA-256을 얻지 못했다"

if [ -z "$VOLUME" ]; then
  VOLUME="${CONTAINER}-data"
fi
[[ "$VOLUME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "volume 이름이 잘못됐다"
docker container inspect "$CONTAINER" >/dev/null 2>&1 && die "container가 이미 존재한다"
docker volume inspect "$VOLUME" >/dev/null 2>&1 && die "volume이 이미 존재한다"

# candidate source도 현재 checkout이 아니라 requested Git object의 sealed archive만 쓴다.
# 이 script의 checkout은 object store와 oracle creator 자체를 읽는 용도일 뿐이고,
# baseline migration·bootstrap·receipt contract의 physical input에는 들어가지 않는다.
git -C "$REPOSITORY_ROOT" cat-file -e "${CANDIDATE_COMMIT}^{commit}" || \
  die "requested candidate commit object가 local Git object store에 없다"
CANDIDATE_GIT_TREE="$(git -C "$REPOSITORY_ROOT" rev-parse "${CANDIDATE_COMMIT}^{tree}")"
CANDIDATE_SEALED_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-fresh-candidate.XXXXXX")"
CANDIDATE_SEALED_ROOT="$CANDIDATE_SEALED_PARENT/source"
mkdir "$CANDIDATE_SEALED_ROOT"
if ! git -C "$REPOSITORY_ROOT" archive --format=tar "$CANDIDATE_COMMIT" \
  | tar -x -C "$CANDIDATE_SEALED_ROOT"; then
  die "candidate Git archive를 만들지 못했다"
fi
cleanup_candidate_seal() {
  [ -z "${candidate_app_manifest:-}" ] || rm -f -- "$candidate_app_manifest"
  [ -z "${candidate_image_app_manifest:-}" ] || rm -f -- "$candidate_image_app_manifest"
  [ -z "${candidate_runtime_manifest:-}" ] || rm -f -- "$candidate_runtime_manifest"
  [ -z "${candidate_image_runtime_manifest:-}" ] || rm -f -- "$candidate_image_runtime_manifest"
  [ -z "${candidate_entrypoint_manifest:-}" ] || rm -f -- "$candidate_entrypoint_manifest"
  [ -z "${candidate_image_entrypoint_manifest:-}" ] || rm -f -- "$candidate_image_entrypoint_manifest"
  [ -z "${candidate_dependency_sbom:-}" ] || rm -f -- "$candidate_dependency_sbom"
  [ -z "${proof_tools_manifest:-}" ] || rm -f -- "$proof_tools_manifest"
  [ -z "${CANDIDATE_SEALED_PARENT:-}" ] || rm -rf -- "$CANDIDATE_SEALED_PARENT"
  CANDIDATE_SEALED_PARENT=""
  CANDIDATE_SEALED_ROOT=""
}
trap 'status=$?; cleanup_candidate_seal; exit "$status"' EXIT
python3 - "$CANDIDATE_SEALED_ROOT" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
required = (
    "docker/api.Dockerfile",
    "docker/postgres-role-bootstrap.sh",
    "docker/application-schema-db-contract.py",
    "docker/application-schema-fresh-300.py",
    "docker/application-schema-fresh-finalize.py",
    "docker/application-schema-final-permit.py",
    "docker/application-schema-contract.py",
    "docker/application-schema-head.py",
    "scripts/create-application-300-fresh-oracle.sh",
    "alembic.ini",
    "alembic/env.py",
    "alembic/versions/300_schema_baseline.py",
    "alembic/baseline/application-reference.json",
)
for relative in required:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"sealed candidate required file is missing or symlinked: {relative}")
for path in [root, *root.rglob("*")]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"sealed candidate contains a symlink: {path.relative_to(root)}")
    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise SystemExit(f"sealed candidate contains a non-regular entry: {path.relative_to(root)}")
for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
    os.chmod(path, 0o555 if path.is_dir() else 0o444)
os.chmod(root, 0o555)
PY
# Current oracle code is allowed to drive Docker only after it is proved equal to
# the candidate's sealed proof toolchain. Otherwise a local edited creator can
# manufacture a receipt for an intact candidate image.
proof_tools_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-fresh-proof-tools.XXXXXX")"
for proof_relative in \
  scripts/create-application-300-fresh-oracle.sh; do
  sealed_proof_tool="$CANDIDATE_SEALED_ROOT/$proof_relative"
  current_proof_tool="$REPOSITORY_ROOT/$proof_relative"
  [ -f "$sealed_proof_tool" ] && [ ! -L "$sealed_proof_tool" ] || \
    die "sealed candidate proof tool이 없다: $proof_relative"
  [ -f "$current_proof_tool" ] && [ ! -L "$current_proof_tool" ] || \
    die "executing proof tool이 regular file이 아니다: $proof_relative"
  cmp -s "$sealed_proof_tool" "$current_proof_tool" || \
    die "executing proof tool이 sealed candidate commit과 다르다: $proof_relative"
  printf '%s  %s\n' "$(sha256sum "$sealed_proof_tool" | awk '{print $1}')" "$proof_relative" \
    >>"$proof_tools_manifest"
done
candidate_proof_tools_manifest_sha256="$(sha256sum "$proof_tools_manifest" | awk '{print $1}')"
rm -f -- "$proof_tools_manifest"
[[ "$candidate_proof_tools_manifest_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate proof tool manifest SHA-256을 얻지 못했다"
candidate_attested_proof_tools_manifest_sha256="$(python3 - "$CANDIDATE_PROVENANCE_JSON" <<'PY'
from __future__ import annotations

import json
import re
import sys

value = json.loads(sys.argv[1])
digest = value.get("candidate_proof_tools_manifest_sha256")
if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("sealed candidate proof tool manifest digest is invalid")
print(digest)
PY
)"
[ "$candidate_proof_tools_manifest_sha256" = "$candidate_attested_proof_tools_manifest_sha256" ] || \
  die "candidate proof tool manifest가 sealed candidate attestation과 다르다"
CANDIDATE_DOCKERFILE_SHA256="$(sha256sum "$CANDIDATE_SEALED_ROOT/docker/api.Dockerfile" | awk '{print $1}')"
CANDIDATE_BASE_IMAGE_REFERENCE="$(python3 - "$CANDIDATE_SEALED_ROOT/docker/api.Dockerfile" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

declarations: dict[str, str] = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"FROM (python@sha256:[0-9a-f]{64}) AS (builder|runtime)", line.strip())
    if match:
        reference, stage = match.groups()
        if stage in declarations:
            raise SystemExit(f"duplicate candidate Dockerfile stage: {stage}")
        declarations[stage] = reference
if set(declarations) != {"builder", "runtime"}:
    raise SystemExit("candidate Dockerfile must declare exactly pinned builder/runtime Python bases")
if declarations["builder"] != declarations["runtime"]:
    raise SystemExit("candidate Dockerfile builder/runtime base references differ")
print(declarations["runtime"])
PY
)"
[[ "$CANDIDATE_BASE_IMAGE_REFERENCE" =~ ^python@sha256:[0-9a-f]{64}$ ]] || \
  die "candidate Dockerfile immutable base declaration을 읽지 못했다"
CANDIDATE_BASE_IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$CANDIDATE_BASE_IMAGE_REFERENCE")"
[[ "$CANDIDATE_BASE_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "candidate Dockerfile base image ID를 얻지 못했다"
candidate_image_id="$(docker image inspect -f '{{.Id}}' "$CANDIDATE_IMAGE")"
candidate_image_commit="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CANDIDATE_IMAGE")"
[ "$candidate_image_commit" = "$CANDIDATE_COMMIT" ] || \
  die "candidate image OCI revision이 requested candidate commit과 다르다"
candidate_image_tree="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-git-tree"}}' "$candidate_image_id")"
candidate_image_dockerfile_sha256="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-dockerfile-sha256"}}' "$candidate_image_id")"
candidate_image_base_image_reference="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-reference"}}' "$candidate_image_id")"
candidate_image_base_image_id="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-id"}}' "$candidate_image_id")"
[ "$candidate_image_tree" = "$CANDIDATE_GIT_TREE" ] || \
  die "candidate image Git tree label이 sealed candidate와 다르다"
[ "$candidate_image_dockerfile_sha256" = "$CANDIDATE_DOCKERFILE_SHA256" ] || \
  die "candidate image Dockerfile label이 sealed candidate와 다르다"
[ "$candidate_image_base_image_reference" = "$CANDIDATE_BASE_IMAGE_REFERENCE" ] || \
  die "candidate image base reference label이 sealed candidate와 다르다"
[ "$candidate_image_base_image_id" = "$CANDIDATE_BASE_IMAGE_ID" ] || \
  die "candidate image base image ID label이 sealed candidate와 다르다"
candidate_base_rootfs_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$CANDIDATE_BASE_IMAGE_REFERENCE")"
candidate_image_rootfs_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$candidate_image_id")"
candidate_rootfs_digests="$(python3 - "$candidate_base_rootfs_layers" "$candidate_image_rootfs_layers" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys

try:
    base_layers = json.loads(sys.argv[1])
    image_layers = json.loads(sys.argv[2])
except ValueError as exc:
    raise SystemExit(f"candidate image RootFS layer metadata is invalid: {exc}") from exc
if (
    not isinstance(base_layers, list)
    or not isinstance(image_layers, list)
    or not base_layers
    or any(not isinstance(layer, str) or not layer.startswith("sha256:") for layer in base_layers)
    or any(not isinstance(layer, str) or not layer.startswith("sha256:") for layer in image_layers)
):
    raise SystemExit("candidate image RootFS layer metadata shape is invalid")
if image_layers[: len(base_layers)] != base_layers:
    raise SystemExit("candidate image RootFS does not preserve the pinned runtime base layer prefix")
def digest(layers: list[str]) -> str:
    canonical = json.dumps(layers, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()

print(digest(base_layers))
print(digest(image_layers))
PY
)"
mapfile -t candidate_rootfs_digest_fields <<< "$candidate_rootfs_digests"
[ "${#candidate_rootfs_digest_fields[@]}" -eq 2 ] || \
  die "candidate RootFS digest pair를 얻지 못했다"
CANDIDATE_BASE_ROOTFS_LAYERS_SHA256="${candidate_rootfs_digest_fields[0]}"
CANDIDATE_FULL_ROOTFS_LAYERS_SHA256="${candidate_rootfs_digest_fields[1]}"
[[ "$CANDIDATE_BASE_ROOTFS_LAYERS_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate base RootFS prefix digest를 얻지 못했다"
[[ "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate full RootFS digest를 얻지 못했다"
reference_manifest="$CANDIDATE_SEALED_ROOT/alembic/baseline/application-reference.json"
[[ -f "$reference_manifest" && ! -L "$reference_manifest" ]] || \
  die "application reference manifest가 없다"
manifest_sha256="$(sha256sum "$reference_manifest" | awk '{print $1}')"
candidate_manifest_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
  'sha256sum /app/alembic/baseline/application-reference.json | awk '\''{print $1}'\''')"
[ "$candidate_manifest_sha256" = "$manifest_sha256" ] || \
  die "candidate image baseline manifest가 repository artifact와 다르다"
postgis_image_id="$(docker image inspect -f '{{.Id}}' "$POSTGIS_IMAGE")"
creator_script_sha256="$(sha256sum "$CANDIDATE_SEALED_ROOT/scripts/create-application-300-fresh-oracle.sh" | awk '{print $1}')"
bootstrap_script_sha256="$(sha256sum "$CANDIDATE_SEALED_ROOT/docker/postgres-role-bootstrap.sh" | awk '{print $1}')"

# Image manifest 하나만 같다고 sidecar byte 또는 active migration source까지 같다는
# 뜻은 아니다. candidate가 실제 실행할 모든 baseline 입력을 host의 exact candidate
# commit과 먼저 대조한다. 이 비교가 실패하면 oracle cluster를 만들기 전 중단한다.
candidate_migration_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
  'sha256sum /app/alembic/versions/300_schema_baseline.py | awk '\''{print $1}'\''')"
host_migration_sha256="$(sha256sum "$CANDIDATE_SEALED_ROOT/alembic/versions/300_schema_baseline.py" | awk '{print $1}')"
[ "$candidate_migration_sha256" = "$host_migration_sha256" ] || \
  die "candidate image 300 migration source가 repository candidate와 다르다"
for sidecar in \
  application-catalog.sql \
  application-source-catalog.sha256 \
  application-destination-catalog.sha256 \
  application-reference.json \
  application-reference.sha256 \
  application-runtime-invariants.sql \
  application-seed.sql \
  application-seed.sha256 \
  application-privileged-residue.sql \
  application-privileged-residue.sha256 \
  application-source-alembic-version.sql \
  application-source-alembic-version.sha256 \
  application-destination-alembic-version.sql \
  application-destination-alembic-version.sha256 \
  schema.sql \
  seed.sql; do
  host_sidecar_sha256="$(sha256sum "$CANDIDATE_SEALED_ROOT/alembic/baseline/$sidecar" | awk '{print $1}')"
  candidate_sidecar_sha256="$(docker run --pull=never --rm --entrypoint sh "$candidate_image_id" -ec \
    "sha256sum /app/alembic/baseline/$sidecar | cut -d ' ' -f1")"
  [ "$candidate_sidecar_sha256" = "$host_sidecar_sha256" ] || \
    die "candidate image baseline sidecar가 repository candidate와 다르다: $sidecar"
done

# OCI revision label만으로는 image 내부 /app·installed package·handoff executable을
# 증명하지 못한다. sealed candidate의 runtime inputs를 image byte manifest와 각각
# 대조하고, dependency closure는 receipt에 image ID와 함께 남긴다.
candidate_app_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-app.XXXXXX")"
candidate_image_app_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-app.XXXXXX")"
python3 - "$CANDIDATE_SEALED_ROOT" >"$candidate_app_manifest" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
items: dict[str, Path] = {}

def add(source_rel: str, destination_rel: str) -> None:
    source = root / source_rel
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"candidate /app source is missing or symlinked: {source_rel}")
    if destination_rel in items:
        raise SystemExit(f"duplicate candidate /app destination: {destination_rel}")
    items[destination_rel] = source

for name in (
    "alembic.ini",
    "alembic/env.py",
    "alembic/script.py.mako",
    "docker/api-entrypoint.sh",
    "docker/application-schema-db-contract.py",
):
    add(name, name)
for directory in ("alembic/baseline", "alembic/versions", "resources/curations"):
    base = root / directory
    if not base.is_dir() or base.is_symlink():
        raise SystemExit(f"candidate /app directory is missing or symlinked: {directory}")
    for source in sorted(
        (path for path in base.rglob("*") if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        if "__pycache__" not in source.parts:
            add(source.relative_to(root).as_posix(), source.relative_to(root).as_posix())
for destination, source in sorted(items.items()):
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
root = Path("/app")
for path in sorted(
    (candidate for candidate in root.rglob("*")
     if candidate.is_file() and not candidate.is_symlink() and "__pycache__" not in candidate.parts),
    key=lambda candidate: candidate.relative_to(root).as_posix(),
):
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
' >"$candidate_image_app_manifest"
cmp -s "$candidate_app_manifest" "$candidate_image_app_manifest" || \
  die "candidate image /app execution tree가 sealed Git archive와 다르다"
candidate_app_manifest_sha256="$(sha256sum "$candidate_app_manifest" | awk '{print $1}')"

candidate_runtime_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-runtime.XXXXXX")"
candidate_image_runtime_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-runtime.XXXXXX")"
python3 - "$CANDIDATE_SEALED_ROOT" >"$candidate_runtime_manifest" <<'PY'
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
        raise SystemExit(f"candidate runtime source directory is missing or symlinked: {source_prefix}")
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
docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
root = Path("/usr/local/lib/python3.12/site-packages/kortravelmap")
for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink()):
    relative = path.relative_to(root).as_posix()
    if "__pycache__/" in relative or not (relative.endswith(".py") or relative.endswith(".json") or relative.endswith("py.typed")):
        continue
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
' >"$candidate_image_runtime_manifest"
cmp -s "$candidate_runtime_manifest" "$candidate_image_runtime_manifest" || \
  die "candidate image installed runtime tree가 sealed Git archive와 다르다"
candidate_runtime_manifest_sha256="$(sha256sum "$candidate_runtime_manifest" | awk '{print $1}')"

candidate_entrypoint_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-entrypoints.XXXXXX")"
candidate_image_entrypoint_manifest="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-entrypoints.XXXXXX")"
python3 - "$CANDIDATE_SEALED_ROOT" >"$candidate_entrypoint_manifest" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
for source_rel, destination in (
    ("docker/application-schema-fresh-300.py", "usr/local/bin/ktm-application-schema-fresh-300"),
    ("docker/application-schema-fresh-finalize.py", "usr/local/bin/ktm-application-schema-fresh-finalize"),
    ("docker/application-schema-final-permit.py", "usr/local/bin/ktm-application-schema-final-permit"),
    ("docker/application-schema-contract.py", "usr/local/bin/ktm-application-schema-contract"),
    ("docker/application-schema-head.py", "usr/local/bin/ktm-application-schema"),
):
    source = root / source_rel
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"candidate executable source is missing or symlinked: {source_rel}")
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
for path in (
    Path("/usr/local/bin/ktm-application-schema-fresh-300"),
    Path("/usr/local/bin/ktm-application-schema-fresh-finalize"),
    Path("/usr/local/bin/ktm-application-schema-final-permit"),
    Path("/usr/local/bin/ktm-application-schema-contract"),
    Path("/usr/local/bin/ktm-application-schema"),
):
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"candidate executable is missing or symlinked: {path}")
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to('/')}")
retired = Path("/usr/local/bin/ktm-application-schema-handoff")
if retired.exists() or retired.is_symlink():
    raise SystemExit("retired in-place handoff executable is present")
' >"$candidate_image_entrypoint_manifest"
cmp -s "$candidate_entrypoint_manifest" "$candidate_image_entrypoint_manifest" || \
  die "candidate image migration executable tree가 sealed Git archive와 다르다"
candidate_entrypoint_manifest_sha256="$(sha256sum "$candidate_entrypoint_manifest" | awk '{print $1}')"

candidate_dependency_sbom="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-sbom.XXXXXX")"
docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
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
' >"$candidate_dependency_sbom"
[ -s "$candidate_dependency_sbom" ] || die "candidate image dependency SBOM이 비어 있다"
candidate_dependency_sbom_sha256="$(sha256sum "$candidate_dependency_sbom" | awk '{print $1}')"

# 독립 계산한 fresh-oracle 관측치도 build receipt를 검증한 candidate verifier 출력과
# key set까지 완전히 같아야 한다. 이 비교를 통과한 뒤에만 candidate identity를 oracle
# container label/receipt로 전파한다.
python3 - "$CANDIDATE_PROVENANCE_JSON" "$CANDIDATE_IMAGE" "$candidate_image_id" \
  "$CANDIDATE_COMMIT" "$CANDIDATE_GIT_TREE" "$CANDIDATE_DOCKERFILE_SHA256" \
  "$manifest_sha256" "$candidate_app_manifest_sha256" \
  "$candidate_runtime_manifest_sha256" "$candidate_entrypoint_manifest_sha256" \
  "$candidate_dependency_sbom_sha256" "$candidate_migration_sha256" \
  "$CANDIDATE_BASE_IMAGE_REFERENCE" "$CANDIDATE_BASE_IMAGE_ID" \
  "$CANDIDATE_BASE_ROOTFS_LAYERS_SHA256" "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" \
  "$candidate_proof_tools_manifest_sha256" "$CANDIDATE_BUILD_RECEIPT_SHA256" <<'PY'
from __future__ import annotations

import json
import sys

try:
    observed = json.loads(sys.argv[1])
except ValueError as exc:
    raise SystemExit(f"sealed candidate verifier result is invalid JSON: {exc}") from exc
keys = (
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_300_migration_sha256", "candidate_base_image_reference",
    "candidate_base_image_id", "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_proof_tools_manifest_sha256",
    "candidate_build_receipt_sha256",
)
expected = dict(zip(keys, sys.argv[2:], strict=True))
if not isinstance(observed, dict) or observed != expected:
    raise SystemExit("fresh oracle candidate observation is not bound to sealed build receipt")
PY

created_container=0
created_volume=0
created_fresh_migrate_fence_volume=0
created_fresh_finalize_fence_volume=0
receipt_tmp=""
fresh_migration_result_file=""
fresh_finalize_result_file=""
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
  [ -z "$fresh_migration_result_file" ] || rm -f -- "$fresh_migration_result_file"
  [ -z "$fresh_finalize_result_file" ] || rm -f -- "$fresh_finalize_result_file"
  if [ "$created_fresh_migrate_fence_volume" = 1 ]; then
    docker volume rm "$FRESH_MIGRATE_FENCE_VOLUME" >/dev/null 2>&1 || true
  fi
  if [ "$created_fresh_finalize_fence_volume" = 1 ]; then
    docker volume rm "$FRESH_FINALIZE_FENCE_VOLUME" >/dev/null 2>&1 || true
  fi
  cleanup_candidate_seal
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
  --label "io.kor-travel-map.application-baseline.candidate-git-tree=$CANDIDATE_GIT_TREE" \
  --label "io.kor-travel-map.application-baseline.candidate-dockerfile-sha256=$CANDIDATE_DOCKERFILE_SHA256" \
  --label "io.kor-travel-map.application-baseline.candidate-base-image-reference=$CANDIDATE_BASE_IMAGE_REFERENCE" \
  --label "io.kor-travel-map.application-baseline.candidate-base-image-id=$CANDIDATE_BASE_IMAGE_ID" \
  --label "io.kor-travel-map.application-baseline.candidate-base-rootfs-layers-sha256=$CANDIDATE_BASE_ROOTFS_LAYERS_SHA256" \
  --label "io.kor-travel-map.application-baseline.candidate-full-rootfs-layers-sha256=$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" \
  --label "io.kor-travel-map.application-baseline.candidate-build-receipt-sha256=$CANDIDATE_BUILD_RECEIPT_SHA256" \
  --label "io.kor-travel-map.application-baseline.candidate-manifest-sha256=$manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.candidate-app-manifest-sha256=$candidate_app_manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.candidate-runtime-manifest-sha256=$candidate_runtime_manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.candidate-entrypoint-manifest-sha256=$candidate_entrypoint_manifest_sha256" \
  --label "io.kor-travel-map.application-baseline.candidate-dependency-sbom-sha256=$candidate_dependency_sbom_sha256" \
  --label "io.kor-travel-map.application-baseline.postgis-image-id=$postgis_image_id" \
  --mount "type=volume,source=$VOLUME,target=/var/lib/postgresql/data" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB="$POSTGIS_BOOTSTRAP_DATABASE" \
  -e POSTGRES_PASSWORD="$oracle_password" \
  "$postgis_image_id" >/dev/null
created_container=1
[ "$(docker inspect -f '{{.Image}}' "$CONTAINER")" = "$postgis_image_id" ] || \
  die "fresh oracle container가 resolved PostGIS image로 시작하지 않았다"

# `pg_isready`는 entrypoint의 temporary postmaster가 살아난 것만 보여 줄 수 있다.
# candidate fresh DB는 official PostGIS init-complete marker 뒤, bootstrap database에서
# template1을 원본으로 명시적으로 만들어야 한다. source oracle과 동일한 순서를 쓰지
# 않으면 /docker-entrypoint-initdb.d의 extension seed와 role bootstrap이 경합한다.
ready=0
for attempt in $(seq 1 45); do
  if docker logs "$CONTAINER" 2>&1 | grep -Fq 'PostgreSQL init process complete' \
    && docker exec "$CONTAINER" pg_isready -U postgres -d "$POSTGIS_BOOTSTRAP_DATABASE" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || die "fresh oracle official PostGIS initialization이 준비되지 않았다"

docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$POSTGIS_BOOTSTRAP_DATABASE" \
  -c "CREATE DATABASE \"$DATABASE\" TEMPLATE $FRESH_DATABASE_TEMPLATE" >/dev/null

# source oracle과 동일한 catalog scope를 receipt에 고정한다. stock image의 fresh guard는
# bootstrap 바로 전에 실행되므로, 그 이전에 template1 clone이 객체/ACL/role residue를
# 갖고 있지 않았다는 별도 immutable evidence가 필요하다.
fresh_initial_virgin_inventory="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At -c "
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
fresh_initial_virgin_inventory="$(python3 - "$fresh_initial_virgin_inventory" <<'PY'
from __future__ import annotations

import json
import sys

print(json.dumps(json.loads(sys.argv[1]), sort_keys=True, separators=(",", ":")))
PY
)"
fresh_initial_virgin_inventory_sha256="$(printf '%s' "$fresh_initial_virgin_inventory" | sha256sum | awk '{print $1}')"
python3 - "$fresh_initial_virgin_inventory" "$fresh_initial_virgin_inventory_sha256" <<'PY'
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
    raise SystemExit(f"fresh initial virgin inventory is not JSON: {exc}") from exc
if observed != expected:
    raise SystemExit(f"fresh template1 DB is not virgin: {json.dumps(observed, sort_keys=True)}")
if hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest() != sys.argv[2]:
    raise SystemExit("fresh initial virgin inventory digest is inconsistent")
PY

bootstrap_dsn="postgresql://postgres:$oracle_password@127.0.0.1:5432/$DATABASE"
docker run --pull=never --rm --network "container:$CONTAINER" \
  --mount "type=bind,source=$CANDIDATE_SEALED_ROOT/docker/postgres-role-bootstrap.sh,target=/bootstrap.sh,readonly" \
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
database_oid="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
database_owner="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c 'SELECT datdba::regrole::text FROM pg_catalog.pg_database WHERE datname = current_database()')"
system_identifier="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c 'SELECT system_identifier FROM pg_catalog.pg_control_system()')"
[[ "$database_oid" =~ ^[0-9]+$ ]] || die "fresh oracle database OID를 얻지 못했다"
[ "$database_owner" = "ktm_feature_schema_owner" ] || \
  die "fresh oracle database owner가 schema owner가 아니다"
[[ "$system_identifier" =~ ^[0-9]+$ ]] || die "fresh oracle PostgreSQL system identifier를 얻지 못했다"

FRESH_MIGRATE_FENCE_VOLUME="${CONTAINER}-fresh-migrate-fence"
docker volume inspect "$FRESH_MIGRATE_FENCE_VOLUME" >/dev/null 2>&1 && \
  die "fresh migrate fence volume이 이미 존재한다"
docker volume create "$FRESH_MIGRATE_FENCE_VOLUME" >/dev/null
created_fresh_migrate_fence_volume=1
python3 - "$reference_manifest" "$CANDIDATE_COMMIT" "$candidate_image_id" \
  "$postgis_image_id" "$DATABASE" "$database_oid" "$database_owner" \
  "$system_identifier" <<'PY' | docker run --pull=never --rm -i --user root \
    --mount "type=volume,source=$FRESH_MIGRATE_FENCE_VOLUME,target=/fresh-migrate-fence" \
    --entrypoint sh "$postgis_image_id" -ec '
set -eu
target=/fresh-migrate-fence/fence.json
[ ! -e "$target" ] && [ ! -L "$target" ] || exit 73
temporary="$(mktemp /fresh-migrate-fence/.fence.XXXXXX)"
trap '\''rm -f -- "$temporary"'\'' EXIT
cat > "$temporary"
chmod 0444 "$temporary"
mv "$temporary" "$target"
trap - EXIT
'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

reference_raw = Path(sys.argv[1]).read_bytes()
reference = json.loads(reference_raw)
artifacts = reference["artifacts"]
transaction_id = str(uuid4())
operation_id = str(uuid4())
journal_preimage = (
    "kor-travel-map.fresh-oracle-manager-generation.v1\0"
    + transaction_id
    + "\0"
    + operation_id
    + "\0"
    + sys.argv[2]
    + "\0"
    + sys.argv[5]
    + "\0"
    + sys.argv[6]
    + "\0"
    + sys.argv[8]
)
value = {
    "schema": "kor-travel-docker-manager.map-fresh-300-migrate-fence.v2",
    "transaction_id": transaction_id,
    "operation_id": operation_id,
    "journal_sha256": hashlib.sha256(journal_preimage.encode("utf-8")).hexdigest(),
    "journal_generation": 1,
    "operation": "map-fresh-300",
    "map_candidate_commit": sys.argv[2],
    "map_candidate_image_id": sys.argv[3],
    "postgres_image_id": sys.argv[4],
    "destination_head": "300",
    "reference_manifest_sha256": hashlib.sha256(reference_raw).hexdigest(),
    "source_catalog_sha256": artifacts["source_catalog_contract_sha256"],
    "destination_catalog_sha256": artifacts[
        "destination_catalog_contract_sha256"
    ],
    "seed_sha256": artifacts["seed_contract_sha256"],
    "privileged_residue_sha256": artifacts["privileged_residue_contract_sha256"],
    "source_alembic_version_sha256": artifacts[
        "source_alembic_version_contract_sha256"
    ],
    "destination_alembic_version_sha256": artifacts[
        "destination_alembic_version_contract_sha256"
    ],
    "runtime_invariants_sql_sha256": artifacts["runtime_invariants_sql_sha256"],
    "database_name": sys.argv[5],
    "database_oid": int(sys.argv[6]),
    "database_owner": sys.argv[7],
    "postgres_system_identifier": sys.argv[8],
    "writer_fence_expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
}
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY

fresh_migration_result_file="$(mktemp "${TMPDIR:-/tmp}/ktm300-fresh-migration-result.XXXXXX")"
docker run --pull=never --rm --network "container:$CONTAINER" \
  --mount "type=volume,source=$FRESH_MIGRATE_FENCE_VOLUME,target=/run/kor-travel-map-application-fresh-migrate,readonly" \
  -e KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE=production \
  -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$migrator_dsn" \
  -e "KOR_TRAVEL_MAP_IMAGE_REVISION=$CANDIDATE_COMMIT" \
  -e "KOR_TRAVEL_MAP_APPLICATION_FRESH_MIGRATE_IMAGE_ID=$candidate_image_id" \
  --entrypoint /usr/local/bin/ktm-application-schema-fresh-300 "$candidate_image_id" \
  migrate --writer-fence-receipt /run/kor-travel-map-application-fresh-migrate/fence.json \
  >"$fresh_migration_result_file"
fresh_migration_result_sha256="$(sha256sum "$fresh_migration_result_file" | awk '{print $1}')"
fresh_migration_evidence="$(python3 - "$fresh_migration_result_file" "$CANDIDATE_COMMIT" \
  "$candidate_image_id" "$manifest_sha256" "$DATABASE" "$database_oid" \
  "$database_owner" "$system_identifier" "$postgis_image_id" \
  "$expected_source_catalog_sha256" "$expected_seed_sha256" \
  "$expected_privileged_residue_sha256" <<'PY'
import json
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
try:
    value = json.loads(raw)
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"fresh migration result is invalid: {exc}") from exc
if raw != (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode():
    raise SystemExit("fresh migration result is not one canonical JSON line")
expected = {
    "schema": "kor-travel-map.application-fresh-300-root.v2",
    "outcome": "root-committed",
    "authorization": "manager-fence",
    "destination_head": "300",
    "map_candidate_commit": sys.argv[2],
    "map_candidate_image_id": sys.argv[3],
    "postgres_image_id": sys.argv[9],
    "reference_manifest_sha256": sys.argv[4],
    "database_identity": {
        "database_name": sys.argv[5],
        "database_oid": int(sys.argv[6]),
        "database_owner": sys.argv[7],
        "postgres_system_identifier": sys.argv[8],
    },
    "post_source_catalog_sha256": sys.argv[10],
    "post_seed_sha256": sys.argv[11],
    "expected_privileged_residue_sha256": sys.argv[12],
}
if not isinstance(value, dict) or any(value.get(key) != item for key, item in expected.items()):
    raise SystemExit("fresh migration result candidate/database binding drifted")
for key in (
    "writer_fence_receipt_sha256", "journal_sha256",
    "expected_destination_alembic_version_sha256",
    "post_destination_alembic_version_sha256",
):
    if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
        raise SystemExit(f"fresh migration result digest is invalid: {key}")
try:
    from uuid import UUID

    operation_id = UUID(value["operation_id"])
    transaction_id = UUID(value["writer_fence_transaction_id"])
except (KeyError, TypeError, ValueError) as exc:
    raise SystemExit("fresh migration result operation identity is invalid") from exc
if (
    value["operation_id"] != str(operation_id)
    or value["writer_fence_transaction_id"] != str(transaction_id)
    or value["expected_destination_alembic_version_sha256"]
    != value["post_destination_alembic_version_sha256"]
    or value.get("journal_generation") != 1
):
    raise SystemExit("fresh migration result generation/facet evidence is invalid")
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY
)"

raw_revision="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version")"
[ "$raw_revision" = "300" ] || die "candidate migration 후 raw Alembic head가 exact 300이 아니다"
application_relation_count="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -At \
  -c "SELECT count(*) FROM pg_catalog.pg_class AS relation JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace WHERE namespace.nspname IN ('feature','provider_sync','ops') AND relation.relkind IN ('r','p','v','m','f','S')")"
[[ "$application_relation_count" =~ ^[1-9][0-9]*$ ]] || die "candidate migration이 application relation을 만들지 않았다"
container_id="$(docker inspect -f '{{.Id}}' "$CONTAINER")"

# Fresh cluster에서 candidate의 contract SQL을 handoff와 같은 role/search_path로
# 실행한다. `alembic_version=300`만 수동으로 넣은 DB는 이 receipt의 catalog/seed
# result와 runtime invariant를 만들 수 없고, build 단계가 source와 다시 대조한다.
canonical_contract_gucs() {
  # deparse/formatting-sensitive output을 DSN의 PGOPTIONS나 session locale에서 분리한다.
  printf '%s\n' "SET LOCAL quote_all_identifiers TO off;"
  printf '%s\n' "SET LOCAL DateStyle TO 'ISO, YMD';"
  printf '%s\n' "SET LOCAL IntervalStyle TO 'postgres';"
  printf '%s\n' "SET LOCAL TimeZone TO 'UTC';"
  printf '%s\n' "SET LOCAL extra_float_digits TO 3;"
  printf '%s\n' "SET LOCAL lc_numeric TO 'C';"
  printf '%s\n' "SET LOCAL bytea_output TO 'hex';"
  printf '%s\n' "SET LOCAL standard_conforming_strings TO on;"
  printf '%s\n' "SET LOCAL xmlbinary TO 'base64';"
}

contract_sha256() {
  local contract="$1"
  local privilege_scope="${2:-schema-owner}"
  {
    printf '%s\n' 'BEGIN;'
    if [ "$privilege_scope" = "schema-owner" ]; then
      printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    elif [ "$privilege_scope" != "database-superuser" ]; then
      die "unknown contract privilege scope: $privilege_scope"
    fi
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    canonical_contract_gucs
    cat "$CANDIDATE_SEALED_ROOT/alembic/baseline/$contract"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -tA \
    | sha256sum | awk '{print $1}'
}
fresh_source_catalog_sha256="$(contract_sha256 application-catalog.sql)"
fresh_seed_sha256="$(contract_sha256 application-seed.sql)"
fresh_privileged_residue_sha256="$(contract_sha256 application-privileged-residue.sql database-superuser)"
fresh_destination_alembic_version_sha256="$(contract_sha256 application-destination-alembic-version.sql)"
runtime_invariant_violations="$(
  {
    printf '%s\n' 'BEGIN;'
    printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    canonical_contract_gucs
    cat "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-runtime-invariants.sql"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$DATABASE" -tA \
    | sed '/^$/d' | wc -l | tr -d ' '
)"
[[ "$fresh_source_catalog_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "fresh oracle source catalog receipt SHA-256을 얻지 못했다"
[[ "$fresh_seed_sha256" =~ ^[0-9a-f]{64}$ ]] || die "fresh oracle seed receipt SHA-256을 얻지 못했다"
[[ "$fresh_privileged_residue_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "fresh oracle privileged residue receipt SHA-256을 얻지 못했다"
[[ "$fresh_destination_alembic_version_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "fresh oracle destination Alembic metadata receipt SHA-256을 얻지 못했다"
expected_destination_alembic_version_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-destination-alembic-version.sha256")"
expected_source_catalog_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-source-catalog.sha256")"
expected_destination_catalog_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-destination-catalog.sha256")"
[ "$fresh_source_catalog_sha256" = "$expected_source_catalog_sha256" ] || \
  die "fresh root source catalog facet이 candidate reference와 다르다"
[ "$fresh_destination_alembic_version_sha256" = "$expected_destination_alembic_version_sha256" ] || \
  die "fresh oracle destination Alembic metadata facet이 candidate reference와 다르다"
[ "$runtime_invariant_violations" = "0" ] || \
  die "candidate migration 뒤 runtime projection invariant가 실패했다"

# production fresh root는 commit receipt를 먼저 남기고, runtime ACL completion은
# 반드시 successor Manager generation의 fixed finalizer로 수행한다. 이렇게 해야
# late ACL failure에도 합성 predecessor hash 없이 root-committed lineage를 복구할 수 있다.
FRESH_FINALIZE_FENCE_VOLUME="${CONTAINER}-fresh-finalize-fence"
docker volume inspect "$FRESH_FINALIZE_FENCE_VOLUME" >/dev/null 2>&1 && \
  die "fresh finalize fence volume이 이미 존재한다"
docker volume create "$FRESH_FINALIZE_FENCE_VOLUME" >/dev/null
created_fresh_finalize_fence_volume=1
python3 - "$reference_manifest" "$CANDIDATE_COMMIT" "$candidate_image_id" \
  "$postgis_image_id" "$DATABASE" "$database_oid" "$database_owner" \
  "$system_identifier" "$fresh_privileged_residue_sha256" \
  "$fresh_migration_result_sha256" "$fresh_migration_evidence" <<'PY' \
  | docker run --pull=never --rm -i --user root \
    --mount "type=volume,source=$FRESH_FINALIZE_FENCE_VOLUME,target=/fresh-finalize-fence" \
    --entrypoint sh "$postgis_image_id" -ec '
set -eu
target=/fresh-finalize-fence/fence.json
[ ! -e "$target" ] && [ ! -L "$target" ] || exit 73
temporary="$(mktemp /fresh-finalize-fence/.fence.XXXXXX)"
trap '\''rm -f -- "$temporary"'\'' EXIT
cat > "$temporary"
chmod 0444 "$temporary"
mv "$temporary" "$target"
trap - EXIT
'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

reference_raw = Path(sys.argv[1]).read_bytes()
reference = json.loads(reference_raw)
artifacts = reference["artifacts"]
prior = json.loads(sys.argv[11])
transaction_id = str(uuid4())
operation_id = str(uuid4())
journal_preimage = (
    "kor-travel-map.fresh-oracle-finalize-generation.v1\0"
    + prior["journal_sha256"]
    + "\0"
    + sys.argv[10]
    + "\0"
    + transaction_id
    + "\0"
    + operation_id
)
value = {
    "schema": "kor-travel-docker-manager.map-fresh-300-finalize-fence.v3",
    "transaction_id": transaction_id,
    "operation_id": operation_id,
    "journal_sha256": hashlib.sha256(journal_preimage.encode("utf-8")).hexdigest(),
    "journal_generation": 2,
    "operation": "map-fresh-300-finalize",
    "prior_fresh_migration_result_sha256": sys.argv[10],
    "prior_fresh_migration_fence_sha256": prior["writer_fence_receipt_sha256"],
    "prior_fresh_migration_transaction_id": prior["writer_fence_transaction_id"],
    "prior_fresh_migration_operation_id": prior["operation_id"],
    "prior_fresh_migration_journal_sha256": prior["journal_sha256"],
    "prior_fresh_migration_generation": prior["journal_generation"],
    "map_candidate_commit": sys.argv[2],
    "map_candidate_image_id": sys.argv[3],
    "postgres_image_id": sys.argv[4],
    "destination_head": "300",
    "reference_manifest_sha256": hashlib.sha256(reference_raw).hexdigest(),
    "source_catalog_sha256": artifacts["source_catalog_contract_sha256"],
    "destination_catalog_sha256": artifacts[
        "destination_catalog_contract_sha256"
    ],
    "seed_sha256": artifacts["seed_contract_sha256"],
    "privileged_residue_sha256": artifacts["privileged_residue_contract_sha256"],
    "pre_privileged_residue_sha256": sys.argv[9],
    "destination_alembic_version_sha256": artifacts[
        "destination_alembic_version_contract_sha256"
    ],
    "runtime_invariants_sql_sha256": artifacts["runtime_invariants_sql_sha256"],
    "database_name": sys.argv[5],
    "database_oid": int(sys.argv[6]),
    "database_owner": sys.argv[7],
    "postgres_system_identifier": sys.argv[8],
    "writer_fence_expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
}
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY

fresh_finalize_result_file="$(mktemp "${TMPDIR:-/tmp}/ktm300-fresh-finalize-result.XXXXXX")"
docker run --pull=never --rm --network "container:$CONTAINER" \
  --mount "type=volume,source=$FRESH_FINALIZE_FENCE_VOLUME,target=/run/kor-travel-map-application-fresh-finalize,readonly" \
  -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$migrator_dsn" \
  -e "KOR_TRAVEL_MAP_IMAGE_REVISION=$CANDIDATE_COMMIT" \
  -e "KOR_TRAVEL_MAP_APPLICATION_FRESH_FINALIZE_IMAGE_ID=$candidate_image_id" \
  --entrypoint /usr/local/bin/ktm-application-schema-fresh-finalize "$candidate_image_id" \
  finalize --writer-fence-receipt /run/kor-travel-map-application-fresh-finalize/fence.json \
  >"$fresh_finalize_result_file"
fresh_finalize_result_sha256="$(sha256sum "$fresh_finalize_result_file" | awk '{print $1}')"
fresh_finalize_evidence="$(python3 - "$fresh_finalize_result_file" "$CANDIDATE_COMMIT" \
  "$candidate_image_id" "$manifest_sha256" "$fresh_migration_result_sha256" \
  "$fresh_migration_evidence" "$expected_source_catalog_sha256" \
  "$expected_destination_catalog_sha256" \
  "$expected_destination_alembic_version_sha256" "$postgis_image_id" \
  "$expected_seed_sha256" "$expected_privileged_residue_sha256" <<'PY'
import json
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
value = json.loads(raw)
prior = json.loads(sys.argv[6])
if raw != (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode():
    raise SystemExit("fresh finalize result is not one canonical JSON line")
expected = {
    "schema": "kor-travel-map.application-fresh-300-finalize.v4",
    "outcome": "finalized",
    "destination_head": "300",
    "map_candidate_commit": sys.argv[2],
    "map_candidate_image_id": sys.argv[3],
    "postgres_image_id": sys.argv[10],
    "reference_manifest_sha256": sys.argv[4],
    "journal_generation": 2,
    "prior_fresh_migration_result_sha256": sys.argv[5],
    "prior_fresh_migration_fence_sha256": prior["writer_fence_receipt_sha256"],
    "prior_fresh_migration_transaction_id": prior["writer_fence_transaction_id"],
    "prior_fresh_migration_operation_id": prior["operation_id"],
    "prior_fresh_migration_journal_sha256": prior["journal_sha256"],
    "prior_fresh_migration_generation": prior["journal_generation"],
    "pre_source_catalog_sha256": sys.argv[7],
    "pre_seed_sha256": sys.argv[11],
    "post_destination_catalog_sha256": sys.argv[8],
    "post_seed_sha256": sys.argv[11],
    "expected_privileged_residue_sha256": sys.argv[12],
    "post_destination_alembic_version_sha256": sys.argv[9],
    "database_identity": prior["database_identity"],
}
if not isinstance(value, dict) or any(value.get(key) != item for key, item in expected.items()):
    raise SystemExit("fresh finalize result lineage binding drifted")
for key in ("writer_fence_receipt_sha256", "journal_sha256"):
    if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
        raise SystemExit(f"fresh finalize result digest is invalid: {key}")
try:
    from uuid import UUID

    operation_id = UUID(value["operation_id"])
    transaction_id = UUID(value["writer_fence_transaction_id"])
except (KeyError, TypeError, ValueError) as exc:
    raise SystemExit("fresh finalize result operation identity is invalid") from exc
if value["operation_id"] != str(operation_id) or value["writer_fence_transaction_id"] != str(transaction_id):
    raise SystemExit("fresh finalize result operation identity is not canonical")
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY
)"

# finalizer 이후 Manager postflight와 같은 privileged observation을 다시 취한다.
fresh_destination_catalog_sha256="$(contract_sha256 application-catalog.sql)"
[ "$fresh_destination_catalog_sha256" = "$expected_destination_catalog_sha256" ] || \
  die "fresh finalize 뒤 destination catalog facet이 candidate reference와 다르다"
fresh_privileged_residue_sha256="$(contract_sha256 application-privileged-residue.sql database-superuser)"
expected_privileged_residue_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-privileged-residue.sha256")"
[ "$fresh_privileged_residue_sha256" = "$expected_privileged_residue_sha256" ] || \
  die "fresh finalize 뒤 privileged residue가 candidate reference와 다르다"

receipt_tmp="$(mktemp "$RECEIPT_PARENT/.ktm300-fresh-oracle.XXXXXX")"
python3 - "$receipt_tmp" "$container_id" "$DATABASE" "$database_oid" "$system_identifier" \
  "$CANDIDATE_IMAGE" "$candidate_image_id" "$CANDIDATE_COMMIT" "$manifest_sha256" \
  "$CANDIDATE_GIT_TREE" "$CANDIDATE_DOCKERFILE_SHA256" "$candidate_app_manifest_sha256" \
  "$candidate_runtime_manifest_sha256" "$candidate_entrypoint_manifest_sha256" \
  "$candidate_dependency_sbom_sha256" "$CANDIDATE_BASE_IMAGE_REFERENCE" \
  "$CANDIDATE_BASE_IMAGE_ID" "$CANDIDATE_BASE_ROOTFS_LAYERS_SHA256" \
  "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" "$CANDIDATE_BUILD_RECEIPT_SHA256" \
  "$POSTGIS_IMAGE" "$postgis_image_id" \
  "$creator_script_sha256" "$bootstrap_script_sha256" "$candidate_migration_sha256" \
  "$raw_revision" "$application_relation_count" "$fresh_source_catalog_sha256" \
  "$fresh_destination_catalog_sha256" "$fresh_seed_sha256" \
  "$fresh_privileged_residue_sha256" "$runtime_invariant_violations" \
  "$candidate_proof_tools_manifest_sha256" "$FRESH_DATABASE_TEMPLATE" \
  "$fresh_initial_virgin_inventory" "$fresh_initial_virgin_inventory_sha256" \
  "$fresh_destination_alembic_version_sha256" "$fresh_migration_result_sha256" \
  "$fresh_migration_evidence" "$fresh_finalize_result_sha256" \
  "$fresh_finalize_evidence" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
value = {
    "schema": "kor-travel-map.application-fresh-300-oracle.v10",
    "container_id": sys.argv[2],
    "database": sys.argv[3],
    "database_oid": int(sys.argv[4]),
    "postgres_system_identifier": sys.argv[5],
    "candidate_image": sys.argv[6],
    "candidate_image_id": sys.argv[7],
    "candidate_commit": sys.argv[8],
    "candidate_manifest_sha256": sys.argv[9],
    "candidate_git_tree": sys.argv[10],
    "candidate_dockerfile_sha256": sys.argv[11],
    "candidate_app_manifest_sha256": sys.argv[12],
    "candidate_runtime_manifest_sha256": sys.argv[13],
    "candidate_entrypoint_manifest_sha256": sys.argv[14],
    "candidate_dependency_sbom_sha256": sys.argv[15],
    "candidate_base_image_reference": sys.argv[16],
    "candidate_base_image_id": sys.argv[17],
    "candidate_base_rootfs_layers_sha256": sys.argv[18],
    "candidate_full_rootfs_layers_sha256": sys.argv[19],
    "candidate_build_receipt_sha256": sys.argv[20],
    "bootstrap_phase": "baseline-300",
    "migration_command": (
        "ktm-application-schema-fresh-300 migrate --writer-fence-receipt "
        "/run/kor-travel-map-application-fresh-migrate/fence.json"
    ),
    "postgis_image": sys.argv[21],
    "postgis_image_id": sys.argv[22],
    "creator_script_sha256": sys.argv[23],
    "bootstrap_script_sha256": sys.argv[24],
    "candidate_300_migration_sha256": sys.argv[25],
    "raw_alembic_revision": sys.argv[26],
    "application_relation_count": int(sys.argv[27]),
    "source_catalog_sha256": sys.argv[28],
    "destination_catalog_sha256": sys.argv[29],
    "seed_sha256": sys.argv[30],
    "privileged_residue_sha256": sys.argv[31],
    "runtime_invariant_violation_count": int(sys.argv[32]),
    "candidate_proof_tools_manifest_sha256": sys.argv[33],
    "fresh_database_provisioning": "explicit-create-database-from-template1-after-official-entrypoint-complete",
    "fresh_database_template": sys.argv[34],
    "fresh_initial_virgin_inventory": json.loads(sys.argv[35]),
    "fresh_initial_virgin_inventory_sha256": sys.argv[36],
    "destination_alembic_version_sha256": sys.argv[37],
    "fresh_migration_result_sha256": sys.argv[38],
    "fresh_migration_evidence": json.loads(sys.argv[39]),
    "fresh_finalize_result_sha256": sys.argv[40],
    "fresh_finalize_evidence": json.loads(sys.argv[41]),
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_tmp"
mv "$receipt_tmp" "$RECEIPT"
receipt_tmp=""
cleanup_candidate_seal
trap - EXIT

printf 'fresh 300 oracle created: container=%s database=%s candidate=%s manifest=%s\n' \
  "$CONTAINER" "$DATABASE" "$CANDIDATE_COMMIT" "$manifest_sha256"
