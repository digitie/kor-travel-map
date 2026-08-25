#!/usr/bin/env bash
# exact committed candidate만으로 `300` application image를 build한다.
#
# Docker build context에 current worktree를 넘기면 committed candidate와 무관한 WIP,
# untracked file 또는 symlink가 candidate image에 섞일 수 있다. 이 script는 requested
# commit을 Git archive로 seal한 뒤 그 archive만 context로 사용하고, tree/Dockerfile digest를
# image label에 결박한다. caller의 checkout은 Git object store를 읽는 용도 외에는 쓰지 않는다.
set -euo pipefail

die() { printf 'build-application-300-candidate: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
GIT_ROOT="$REPOSITORY_ROOT"
CANDIDATE_COMMIT=""
IMAGE=""
SEALED_PARENT=""
SEALED_ROOT=""
MODE="build"
RECEIPT=""
RECEIPT_PARENT=""
APP_MANIFEST=""
IMAGE_APP_MANIFEST=""
RUNTIME_MANIFEST=""
IMAGE_RUNTIME_MANIFEST=""
ENTRYPOINT_MANIFEST=""
IMAGE_ENTRYPOINT_MANIFEST=""
DEPENDENCY_SBOM=""
PROOF_TOOLS_MANIFEST=""
CANDIDATE_FULL_ROOTFS_LAYERS_SHA256=""
CANDIDATE_BUILD_RECEIPT_SHA256=""
RECEIPT_TMP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --candidate-commit) CANDIDATE_COMMIT="${2:?--candidate-commit needs a value}"; shift 2 ;;
    --image) IMAGE="${2:?--image needs a value}"; shift 2 ;;
    --git-root) GIT_ROOT="${2:?--git-root needs a value}"; shift 2 ;;
    --receipt) RECEIPT="${2:?--receipt needs a value}"; shift 2 ;;
    --verify) MODE="verify"; shift ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) die "위치 인자는 허용하지 않는다: $1" ;;
  esac
done

[ -n "$CANDIDATE_COMMIT" ] || die "--candidate-commit이 필요하다"
[ -n "$IMAGE" ] || die "--image가 필요하다"
[ -n "$RECEIPT" ] || die "--receipt가 필요하다"
[[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || \
  die "candidate commit은 full SHA-1이어야 한다"
[[ "$GIT_ROOT" == /* && -d "$GIT_ROOT" ]] || die "git root는 absolute directory여야 한다"
GIT_ROOT="$(realpath -e -- "$GIT_ROOT")"
git -C "$GIT_ROOT" cat-file -e "${CANDIDATE_COMMIT}^{commit}" || \
  die "git root에 requested candidate commit object가 없다"

canonicalize_receipt_path() {
  local raw_path="$1"
  [[ "$raw_path" == /* ]] || die "candidate build receipt는 absolute path여야 한다"
  local raw_parent
  raw_parent="$(dirname -- "$raw_path")"
  local raw_name
  raw_name="$(basename -- "$raw_path")"
  [ "$raw_name" != "." ] && [ "$raw_name" != ".." ] || \
    die "candidate build receipt file name이 잘못됐다"
  [ -d "$raw_parent" ] || die "candidate build receipt parent directory가 없다"
  local canonical_parent
  canonical_parent="$(realpath -e -- "$raw_parent")"
  [ "$canonical_parent" = "$raw_parent" ] || \
    die "candidate build receipt parent는 symlink 없는 physical directory여야 한다"
  python3 - "$canonical_parent" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("candidate build receipt parent must be a regular directory")
if metadata.st_uid != int(sys.argv[2]) or stat.S_IMODE(metadata.st_mode) & 0o022:
    raise SystemExit("candidate build receipt parent must be private to the invoking operator")
PY
  local canonical_path
  canonical_path="$(realpath -m -- "$canonical_parent/$raw_name")"
  case "$canonical_path" in
    "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
      die "candidate build receipt는 repository 밖 canonical path여야 한다"
      ;;
  esac
  RECEIPT="$canonical_path"
  RECEIPT_PARENT="$canonical_parent"
}

canonicalize_receipt_path "$RECEIPT"
if [ "$MODE" = "build" ]; then
  [[ ! -e "$RECEIPT" && ! -L "$RECEIPT" ]] || \
    die "candidate build receipt target이 이미 존재한다"
else
  python3 - "$RECEIPT" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"candidate build receipt is unreadable: {exc}") from exc
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("candidate build receipt must be a regular non-symlink file")
if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("candidate build receipt must be mode 0600 and owned by the invoking operator")
PY
fi

SEALED_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-candidate-sealed.XXXXXX")"
SEALED_ROOT="$SEALED_PARENT/source"
mkdir "$SEALED_ROOT"
cleanup() {
  local status=$?
  local cleanup_failed=0
  local temporary
  for temporary in \
    "$APP_MANIFEST" "$IMAGE_APP_MANIFEST" "$RUNTIME_MANIFEST" \
    "$IMAGE_RUNTIME_MANIFEST" "$ENTRYPOINT_MANIFEST" "$IMAGE_ENTRYPOINT_MANIFEST" \
    "$DEPENDENCY_SBOM" "$PROOF_TOOLS_MANIFEST" "$RECEIPT_TMP"; do
    if [ -n "$temporary" ] && ! rm -f -- "$temporary"; then
      cleanup_failed=1
    fi
  done
  if [ -n "$SEALED_PARENT" ] && [ -d "$SEALED_PARENT" ]; then
    if ! chmod -R u+rwX -- "$SEALED_PARENT"; then
      printf 'build-application-300-candidate: sealed temp mode cleanup failed\n' >&2
      cleanup_failed=1
    fi
    if ! rm -rf -- "$SEALED_PARENT"; then
      printf 'build-application-300-candidate: sealed temp cleanup failed\n' >&2
      cleanup_failed=1
    fi
  fi
  [ "$status" -ne 0 ] || [ "$cleanup_failed" -eq 0 ] || status=1
  exit "$status"
}
trap cleanup EXIT
if ! git -C "$GIT_ROOT" archive --format=tar "$CANDIDATE_COMMIT" | tar -x -C "$SEALED_ROOT"; then
  die "candidate Git archive를 만들지 못했다"
fi

python3 - "$SEALED_ROOT" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
required = (
    "docker/api.Dockerfile",
    "docker/postgres-role-bootstrap.sh",
    "docker/transition-application-schema-0236-to-300.py",
    "docker/application-schema-fresh-300.py",
    "docker/application-schema-fresh-finalize.py",
    "docker/application-schema-final-permit.py",
    "docker/application-schema-contract.py",
    "docker/application-schema-head.py",
    "scripts/build-application-300-candidate.sh",
    "scripts/create-application-0236-source-oracle.sh",
    "scripts/create-application-300-fresh-oracle.sh",
    "scripts/build-baseline.sh",
    "scripts/rehearse-application-300-handoff.sh",
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

sealed_builder_script="$SEALED_ROOT/scripts/build-application-300-candidate.sh"
current_builder_script="$SCRIPT_DIR/build-application-300-candidate.sh"
[ -f "$sealed_builder_script" ] && [ ! -L "$sealed_builder_script" ] || \
  die "sealed candidate builder script가 없다"
[ -f "$current_builder_script" ] && [ ! -L "$current_builder_script" ] || \
  die "executing candidate builder script가 regular file이 아니다"
# caller checkout은 Git object store를 읽는 용도 외에는 candidate 입력이 아니다. 그럼에도
# verifier 자체가 candidate commit과 다른 WIP이면 receipt를 쓸 수 없게 막는다. 이 비교가
# 통과한 current executable의 digest만 receipt에 기록한다.
cmp -s "$sealed_builder_script" "$current_builder_script" || \
  die "executing candidate builder script가 sealed candidate commit과 다르다"
builder_script_sha256="$(sha256sum "$sealed_builder_script" | awk '{print $1}')"

# Baseline proof는 candidate image 안의 migration뿐 아니라 source oracle, fresh
# oracle, artifact materializer가 함께 이룬다. 이 셋이 caller의 mutable checkout에서
# 바뀌면 sealed image의 byte가 맞아도 receipt를 임의의 probe tool로 만들 수 있다.
# 모든 tool의 sealed path+digest manifest를 receipt에 남기고, 지금 실행하는 사본이
# candidate archive와 byte-exact가 아니면 build/verify를 시작하지 않는다.
PROOF_TOOLS_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-proof-tools.XXXXXX")"
for proof_relative in \
  scripts/create-application-0236-source-oracle.sh \
  scripts/create-application-300-fresh-oracle.sh \
  scripts/build-baseline.sh \
  scripts/rehearse-application-300-handoff.sh; do
  sealed_proof_tool="$SEALED_ROOT/$proof_relative"
  current_proof_tool="$REPOSITORY_ROOT/$proof_relative"
  [ -f "$sealed_proof_tool" ] && [ ! -L "$sealed_proof_tool" ] || \
    die "sealed candidate proof tool이 없다: $proof_relative"
  [ -f "$current_proof_tool" ] && [ ! -L "$current_proof_tool" ] || \
    die "executing proof tool이 regular file이 아니다: $proof_relative"
  cmp -s "$sealed_proof_tool" "$current_proof_tool" || \
    die "executing proof tool이 sealed candidate commit과 다르다: $proof_relative"
  printf '%s  %s\n' "$(sha256sum "$sealed_proof_tool" | awk '{print $1}')" "$proof_relative" \
    >>"$PROOF_TOOLS_MANIFEST"
done
candidate_proof_tools_manifest_sha256="$(sha256sum "$PROOF_TOOLS_MANIFEST" | awk '{print $1}')"
[[ "$candidate_proof_tools_manifest_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate proof tool manifest SHA-256을 얻지 못했다"

candidate_tree="$(git -C "$GIT_ROOT" rev-parse "${CANDIDATE_COMMIT}^{tree}")"
candidate_dockerfile_sha256="$(sha256sum "$SEALED_ROOT/docker/api.Dockerfile" | awk '{print $1}')"
candidate_base_image_reference="$(python3 - "$SEALED_ROOT/docker/api.Dockerfile" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
declarations: dict[str, str] = {}
for line in lines:
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
[[ "$candidate_base_image_reference" =~ ^python@sha256:[0-9a-f]{64}$ ]] || \
  die "candidate Dockerfile immutable base declaration을 읽지 못했다"
candidate_base_image_id="$(docker image inspect -f '{{.Id}}' "$candidate_base_image_reference")"
[[ "$candidate_base_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "candidate Dockerfile base image ID를 얻지 못했다"
if [ "$MODE" = "build" ]; then
  docker build --pull=false \
    --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$CANDIDATE_COMMIT" \
    --build-arg "KOR_TRAVEL_MAP_GIT_TREE=$candidate_tree" \
    --build-arg "KOR_TRAVEL_MAP_DOCKERFILE_SHA256=$candidate_dockerfile_sha256" \
    --build-arg "KOR_TRAVEL_MAP_BASE_IMAGE_REFERENCE=$candidate_base_image_reference" \
    --build-arg "KOR_TRAVEL_MAP_BASE_IMAGE_ID=$candidate_base_image_id" \
    -t "$IMAGE" \
    -f "$SEALED_ROOT/docker/api.Dockerfile" \
    "$SEALED_ROOT"
fi

image_id="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
image_commit="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")"
image_tree="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-git-tree"}}' "$image_id")"
image_dockerfile_sha256="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-dockerfile-sha256"}}' "$image_id")"
image_base_image_reference="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-reference"}}' "$image_id")"
image_base_image_id="$(docker image inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-id"}}' "$image_id")"
if [ "$image_commit" != "$CANDIDATE_COMMIT" ] \
  || [ "$image_tree" != "$candidate_tree" ] \
  || [ "$image_dockerfile_sha256" != "$candidate_dockerfile_sha256" ] \
  || [ "$image_base_image_reference" != "$candidate_base_image_reference" ] \
  || [ "$image_base_image_id" != "$candidate_base_image_id" ]; then
  die "candidate image labels가 sealed Git archive provenance와 다르다"
fi
candidate_base_rootfs_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$candidate_base_image_reference")"
candidate_image_rootfs_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$image_id")"
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
candidate_base_rootfs_layers_sha256="${candidate_rootfs_digest_fields[0]}"
CANDIDATE_FULL_ROOTFS_LAYERS_SHA256="${candidate_rootfs_digest_fields[1]}"
[[ "$candidate_base_rootfs_layers_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate base RootFS prefix digest를 얻지 못했다"
[[ "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate full RootFS digest를 얻지 못했다"

# OCI revision/tree label만으로는 같은 label을 복제한 다른 runtime image를 막지 못한다.
# 아래 세 manifest는 fresh oracle와 baseline verifier가 같은 방식으로 재계산하는 sealed
# source→image byte proof다. `--verify`는 JSON 한 줄만 stdout에 내므로 호출자가 receipt의
# 모든 field를 strict하게 다시 결박할 수 있다.
reference_manifest_sha256="$(sha256sum "$SEALED_ROOT/alembic/baseline/application-reference.json" | awk '{print $1}')"
image_reference_manifest_sha256="$(docker run --pull=never --rm --entrypoint sh "$image_id" -ec \
  'sha256sum /app/alembic/baseline/application-reference.json | awk '\''{print $1}'\''')"
[ "$image_reference_manifest_sha256" = "$reference_manifest_sha256" ] || \
  die "candidate image baseline manifest가 sealed Git archive와 다르다"

candidate_migration_sha256="$(sha256sum "$SEALED_ROOT/alembic/versions/300_schema_baseline.py" | awk '{print $1}')"
image_migration_sha256="$(docker run --pull=never --rm --entrypoint sh "$image_id" -ec \
  'sha256sum /app/alembic/versions/300_schema_baseline.py | awk '\''{print $1}'\''')"
[ "$image_migration_sha256" = "$candidate_migration_sha256" ] || \
  die "candidate image 300 migration source가 sealed Git archive와 다르다"
for sidecar in \
  application-catalog.sql application-source-catalog.sha256 \
  application-destination-catalog.sha256 \
  application-reference.json application-reference.sha256 \
  application-runtime-invariants.sql application-seed.sql application-seed.sha256 \
  application-privileged-residue.sql application-privileged-residue.sha256 \
  application-source-alembic-version.sql application-source-alembic-version.sha256 \
  application-destination-alembic-version.sql application-destination-alembic-version.sha256 \
  schema.sql seed.sql; do
  sealed_sidecar_sha256="$(sha256sum "$SEALED_ROOT/alembic/baseline/$sidecar" | awk '{print $1}')"
  image_sidecar_digest_line="$(docker run --pull=never --rm --entrypoint sha256sum \
    "$image_id" "/app/alembic/baseline/$sidecar")"
  image_sidecar_sha256="${image_sidecar_digest_line%% *}"
  [ "$image_sidecar_sha256" = "$sealed_sidecar_sha256" ] || \
    die "candidate image baseline sidecar가 sealed Git archive와 다르다: $sidecar"
done

APP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-app.XXXXXX")"
IMAGE_APP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-app.XXXXXX")"
python3 - "$SEALED_ROOT" >"$APP_MANIFEST" <<'PY'
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

for name in ("alembic.ini", "alembic/env.py", "alembic/script.py.mako", "docker/api-entrypoint.sh"):
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
docker run --pull=never --rm --entrypoint python "$image_id" -c '
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
' >"$IMAGE_APP_MANIFEST"
cmp -s "$APP_MANIFEST" "$IMAGE_APP_MANIFEST" || \
  die "candidate image /app execution tree가 sealed Git archive와 다르다"
docker run --pull=never --rm --entrypoint sh "$image_id" -ec '
  [ "$(stat -c "%u:%a" /app/resources/curations)" = 0:555 ]
  [ -z "$(find /app/resources/curations -type d \( ! -user root -o ! -perm 0555 \) -print -quit)" ]
  [ -z "$(find /app/resources/curations -type f \( ! -user root -o ! -perm 0444 \) -print -quit)" ]
  ! touch /app/resources/curations/.candidate-mutation
  ! mv /app/resources/curations/manifest.json /app/resources/curations/replaced.json
' || die "candidate image curation execution tree가 appuser에게 writable하다"
candidate_app_manifest_sha256="$(sha256sum "$APP_MANIFEST" | awk '{print $1}')"

RUNTIME_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-runtime.XXXXXX")"
IMAGE_RUNTIME_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-runtime.XXXXXX")"
python3 - "$SEALED_ROOT" >"$RUNTIME_MANIFEST" <<'PY'
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
docker run --pull=never --rm --entrypoint python "$image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
root = Path("/usr/local/lib/python3.12/site-packages/kortravelmap")
for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink()):
    relative = path.relative_to(root).as_posix()
    if "__pycache__/" in relative or not (relative.endswith(".py") or relative.endswith(".json") or relative.endswith("py.typed")):
        continue
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
' >"$IMAGE_RUNTIME_MANIFEST"
cmp -s "$RUNTIME_MANIFEST" "$IMAGE_RUNTIME_MANIFEST" || \
  die "candidate image installed runtime tree가 sealed Git archive와 다르다"
candidate_runtime_manifest_sha256="$(sha256sum "$RUNTIME_MANIFEST" | awk '{print $1}')"

ENTRYPOINT_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-entrypoints.XXXXXX")"
IMAGE_ENTRYPOINT_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-image-entrypoints.XXXXXX")"
python3 - "$SEALED_ROOT" >"$ENTRYPOINT_MANIFEST" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
for source_rel, destination in (
    ("docker/transition-application-schema-0236-to-300.py", "usr/local/bin/ktm-application-schema-handoff"),
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
docker run --pull=never --rm --entrypoint python "$image_id" -c '
from __future__ import annotations
import hashlib
from pathlib import Path
filesystem_root = Path("/")
for path in (
    Path("/usr/local/bin/ktm-application-schema-handoff"),
    Path("/usr/local/bin/ktm-application-schema-fresh-300"),
    Path("/usr/local/bin/ktm-application-schema-fresh-finalize"),
    Path("/usr/local/bin/ktm-application-schema-final-permit"),
    Path("/usr/local/bin/ktm-application-schema-contract"),
    Path("/usr/local/bin/ktm-application-schema"),
):
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"candidate executable is missing or symlinked: {path}")
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(filesystem_root)}" )
' >"$IMAGE_ENTRYPOINT_MANIFEST"
cmp -s "$ENTRYPOINT_MANIFEST" "$IMAGE_ENTRYPOINT_MANIFEST" || \
  die "candidate image migration executable tree가 sealed Git archive와 다르다"
candidate_entrypoint_manifest_sha256="$(sha256sum "$ENTRYPOINT_MANIFEST" | awk '{print $1}')"

DEPENDENCY_SBOM="$(mktemp "${TMPDIR:-/tmp}/ktm300-candidate-sbom.XXXXXX")"
docker run --pull=never --rm --entrypoint python "$image_id" -c '
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
' >"$DEPENDENCY_SBOM"
[ -s "$DEPENDENCY_SBOM" ] || die "candidate image dependency SBOM이 비어 있다"
candidate_dependency_sbom_sha256="$(sha256sum "$DEPENDENCY_SBOM" | awk '{print $1}')"

# image ID는 Docker의 config digest이고, ordered RootFS layer digest는 그 image가 실제로
# 실행할 filesystem 전체를 고정한다. 둘 중 하나만 receipt에 남기면 같은 label·/app
# byte를 가진 별도 OS layer image를 fresh oracle에 바꿔 끼울 여지가 남는다. build mode는
# sealed archive에서 직접 관측한 값을 private one-shot receipt로 쓴다. verify mode는
# receipt의 정확한 field set/값을 다시 관측한 image와 fail-close 비교한다.
if [ "$MODE" = "build" ]; then
  RECEIPT_TMP="$(mktemp "$RECEIPT_PARENT/.ktm300-candidate-build.XXXXXX")"
  python3 - "$RECEIPT_TMP" "$IMAGE" "$image_id" "$CANDIDATE_COMMIT" \
    "$candidate_tree" "$candidate_dockerfile_sha256" "$reference_manifest_sha256" \
    "$candidate_app_manifest_sha256" "$candidate_runtime_manifest_sha256" \
    "$candidate_entrypoint_manifest_sha256" "$candidate_dependency_sbom_sha256" \
    "$candidate_migration_sha256" "$candidate_base_image_reference" \
    "$candidate_base_image_id" "$candidate_base_rootfs_layers_sha256" \
    "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" "$builder_script_sha256" \
    "$candidate_proof_tools_manifest_sha256" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
value = {
    "schema": "kor-travel-map.application-300-candidate-build.v2",
    "candidate_image": sys.argv[2],
    "candidate_image_id": sys.argv[3],
    "candidate_commit": sys.argv[4],
    "candidate_git_tree": sys.argv[5],
    "candidate_dockerfile_sha256": sys.argv[6],
    "candidate_manifest_sha256": sys.argv[7],
    "candidate_app_manifest_sha256": sys.argv[8],
    "candidate_runtime_manifest_sha256": sys.argv[9],
    "candidate_entrypoint_manifest_sha256": sys.argv[10],
    "candidate_dependency_sbom_sha256": sys.argv[11],
    "candidate_300_migration_sha256": sys.argv[12],
    "candidate_base_image_reference": sys.argv[13],
    "candidate_base_image_id": sys.argv[14],
    "candidate_base_rootfs_layers_sha256": sys.argv[15],
    "candidate_full_rootfs_layers_sha256": sys.argv[16],
    "builder_script_sha256": sys.argv[17],
    "candidate_proof_tools_manifest_sha256": sys.argv[18],
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
  chmod 600 "$RECEIPT_TMP"
  mv "$RECEIPT_TMP" "$RECEIPT"
  RECEIPT_TMP=""
else
  python3 - "$RECEIPT" "$IMAGE" "$image_id" "$CANDIDATE_COMMIT" \
    "$candidate_tree" "$candidate_dockerfile_sha256" "$reference_manifest_sha256" \
    "$candidate_app_manifest_sha256" "$candidate_runtime_manifest_sha256" \
    "$candidate_entrypoint_manifest_sha256" "$candidate_dependency_sbom_sha256" \
    "$candidate_migration_sha256" "$candidate_base_image_reference" \
    "$candidate_base_image_id" "$candidate_base_rootfs_layers_sha256" \
    "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" "$builder_script_sha256" \
    "$candidate_proof_tools_manifest_sha256" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    observed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"candidate build receipt cannot be parsed: {exc}") from exc
expected = {
    "schema": "kor-travel-map.application-300-candidate-build.v2",
    "candidate_image": sys.argv[2],
    "candidate_image_id": sys.argv[3],
    "candidate_commit": sys.argv[4],
    "candidate_git_tree": sys.argv[5],
    "candidate_dockerfile_sha256": sys.argv[6],
    "candidate_manifest_sha256": sys.argv[7],
    "candidate_app_manifest_sha256": sys.argv[8],
    "candidate_runtime_manifest_sha256": sys.argv[9],
    "candidate_entrypoint_manifest_sha256": sys.argv[10],
    "candidate_dependency_sbom_sha256": sys.argv[11],
    "candidate_300_migration_sha256": sys.argv[12],
    "candidate_base_image_reference": sys.argv[13],
    "candidate_base_image_id": sys.argv[14],
    "candidate_base_rootfs_layers_sha256": sys.argv[15],
    "candidate_full_rootfs_layers_sha256": sys.argv[16],
    "builder_script_sha256": sys.argv[17],
    "candidate_proof_tools_manifest_sha256": sys.argv[18],
}
if not isinstance(observed, dict) or observed != expected:
    raise SystemExit("candidate build receipt is not bound to the observed sealed image")
PY
fi
CANDIDATE_BUILD_RECEIPT_SHA256="$(sha256sum "$RECEIPT" | awk '{print $1}')"
[[ "$CANDIDATE_BUILD_RECEIPT_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
  die "candidate build receipt SHA-256을 얻지 못했다"

if [ "$MODE" = "verify" ]; then
  python3 - "$IMAGE" "$image_id" "$CANDIDATE_COMMIT" "$candidate_tree" \
    "$candidate_dockerfile_sha256" "$reference_manifest_sha256" \
    "$candidate_app_manifest_sha256" "$candidate_runtime_manifest_sha256" \
    "$candidate_entrypoint_manifest_sha256" "$candidate_dependency_sbom_sha256" \
    "$candidate_migration_sha256" "$candidate_base_image_reference" \
    "$candidate_base_image_id" "$candidate_base_rootfs_layers_sha256" \
    "$CANDIDATE_FULL_ROOTFS_LAYERS_SHA256" "$candidate_proof_tools_manifest_sha256" \
    "$CANDIDATE_BUILD_RECEIPT_SHA256" <<'PY'
from __future__ import annotations

import json
import sys

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
print(json.dumps(dict(zip(keys, sys.argv[1:], strict=True)), sort_keys=True, separators=(",", ":")))
PY
  exit 0
fi

printf 'application 300 candidate built: image=%s image_id=%s commit=%s tree=%s\n' \
  "$IMAGE" "$image_id" "$CANDIDATE_COMMIT" "$candidate_tree"
