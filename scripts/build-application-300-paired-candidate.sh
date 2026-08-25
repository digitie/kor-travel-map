#!/usr/bin/env bash
# 하나의 sealed Git commit에서 API + Dagster application 300 candidate를 함께 증명한다.
set -euo pipefail

die() { printf 'build-application-300-paired-candidate: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
GIT_ROOT="$REPOSITORY_ROOT"
CANDIDATE_COMMIT=""
API_IMAGE=""
DAGSTER_IMAGE=""
API_RECEIPT=""
RECEIPT=""
RECEIPT_PARENT=""
MODE="build"
SEALED_PARENT=""
SEALED_ROOT=""
EXPECTED_RECEIPT=""
APP_MANIFEST=""
IMAGE_APP_MANIFEST=""
RUNTIME_MANIFEST=""
IMAGE_RUNTIME_MANIFEST=""
PROOF_MANIFEST=""
IMAGE_PROOF_MANIFEST=""
DEPENDENCY_SBOM=""
RECEIPT_TMP=""
API_RECEIPT_PREEXISTED=0
API_RECEIPT_FOR_VERIFY=""
RECEIPT_FOR_VERIFY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --candidate-commit) CANDIDATE_COMMIT="${2:?--candidate-commit needs a value}"; shift 2 ;;
    --api-image) API_IMAGE="${2:?--api-image needs a value}"; shift 2 ;;
    --dagster-image) DAGSTER_IMAGE="${2:?--dagster-image needs a value}"; shift 2 ;;
    --api-receipt) API_RECEIPT="${2:?--api-receipt needs a value}"; shift 2 ;;
    --receipt) RECEIPT="${2:?--receipt needs a value}"; shift 2 ;;
    --git-root) GIT_ROOT="${2:?--git-root needs a value}"; shift 2 ;;
    --verify) MODE="verify"; shift ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) die "위치 인자는 허용하지 않는다: $1" ;;
  esac
done

[ -n "$CANDIDATE_COMMIT" ] || die "--candidate-commit이 필요하다"
[ -n "$API_IMAGE" ] || die "--api-image가 필요하다"
[ -n "$DAGSTER_IMAGE" ] || die "--dagster-image가 필요하다"
[ -n "$API_RECEIPT" ] || die "--api-receipt가 필요하다"
[ -n "$RECEIPT" ] || die "--receipt가 필요하다"
[[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "candidate commit은 full SHA-1이어야 한다"
[[ "$GIT_ROOT" == /* && -d "$GIT_ROOT" ]] || die "git root는 absolute directory여야 한다"
GIT_ROOT="$(realpath -e -- "$GIT_ROOT")"
git -C "$GIT_ROOT" cat-file -e "${CANDIDATE_COMMIT}^{commit}" || \
  die "git root에 requested candidate commit object가 없다"

canonicalize_private_output() {
  local raw_path="$1"
  local description="$2"
  [[ "$raw_path" == /* ]] || die "$description path는 absolute여야 한다"
  local raw_parent raw_name canonical_parent canonical_path
  raw_parent="$(dirname -- "$raw_path")"
  raw_name="$(basename -- "$raw_path")"
  [ "$raw_name" != "." ] && [ "$raw_name" != ".." ] || \
    die "$description file name이 잘못됐다"
  [ -d "$raw_parent" ] || die "$description parent directory가 없다"
  canonical_parent="$(realpath -e -- "$raw_parent")"
  [ "$canonical_parent" = "$raw_parent" ] || \
    die "$description parent는 symlink 없는 physical directory여야 한다"
  python3 - "$canonical_parent" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("receipt parent must be a regular directory")
if metadata.st_uid != int(sys.argv[2]) or stat.S_IMODE(metadata.st_mode) & 0o077:
    raise SystemExit("receipt parent must be private to the invoking operator")
PY
  # parent만 physical path로 확정하고 final component는 절대 follow하지 않는다.
  # 기존 receipt는 아래 O_NOFOLLOW open이 symlink를 거부해야 한다.
  canonical_path="$canonical_parent/$raw_name"
  case "$canonical_path" in
    "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
      die "$description path는 repository 밖이어야 한다"
      ;;
  esac
  printf '%s\n' "$canonical_path"
}

API_RECEIPT="$(canonicalize_private_output "$API_RECEIPT" "API receipt")"
RECEIPT="$(canonicalize_private_output "$RECEIPT" "paired receipt")"
[ "$API_RECEIPT" != "$RECEIPT" ] || die "API receipt와 paired receipt path는 달라야 한다"
RECEIPT_PARENT="$(dirname -- "$RECEIPT")"
if [ "$MODE" = "build" ]; then
  [[ ! -e "$RECEIPT" && ! -L "$RECEIPT" ]] || die "paired receipt target이 이미 존재한다"
  if [[ -e "$API_RECEIPT" || -L "$API_RECEIPT" ]]; then
    API_RECEIPT_PREEXISTED=1
  fi
else
  [[ -e "$API_RECEIPT" || -L "$API_RECEIPT" ]] || die "API receipt가 없다"
  [[ -e "$RECEIPT" || -L "$RECEIPT" ]] || die "paired receipt가 없다"
fi

snapshot_strict_receipt() {
  local source_path="$1"
  local snapshot_path="$2"
  local description="$3"
  python3 - "$source_path" "$snapshot_path" "$(id -u)" "$description" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
snapshot = Path(sys.argv[2])
expected_uid = int(sys.argv[3])
description = sys.argv[4]
maximum_size = 1024 * 1024

parent = source.parent
try:
    named_parent = parent.lstat()
    if parent.resolve(strict=True) != parent:
        raise SystemExit(f"{description} parent is not a canonical physical directory")
except OSError as exc:
    raise SystemExit(f"{description} parent cannot be inspected safely: {exc}") from exc

parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
try:
    parent_fd = os.open(parent, parent_flags)
except OSError as exc:
    raise SystemExit(f"{description} parent cannot be opened safely: {exc}") from exc

try:
    opened_parent = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(opened_parent.st_mode)
        or stat.S_ISLNK(named_parent.st_mode)
        or opened_parent.st_uid != expected_uid
        or stat.S_IMODE(opened_parent.st_mode) & 0o077
        or (opened_parent.st_dev, opened_parent.st_ino)
        != (named_parent.st_dev, named_parent.st_ino)
    ):
        raise SystemExit(f"{description} parent is not a private operator-owned directory")

    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        source_fd = os.open(source.name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise SystemExit(f"{description} cannot be opened safely: {exc}") from exc

    with os.fdopen(source_fd, "rb", closefd=True) as stream:
        opened = os.fstat(stream.fileno())
        try:
            named_before = os.stat(source.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise SystemExit(f"{description} path changed before inspection: {exc}") from exc
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(named_before.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != expected_uid
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named_before.st_dev, named_before.st_ino)
        ):
            raise SystemExit(
                f"{description} must be one mode 0600 regular non-symlink file "
                "owned by the operator"
            )
        payload = stream.read(maximum_size + 1)
        if len(payload) > maximum_size:
            raise SystemExit(f"{description} exceeds the maximum trusted size")
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"{description} is not valid UTF-8 JSON: {exc}") from exc
        canonical = (
            json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        if not isinstance(parsed, dict) or payload != canonical:
            raise SystemExit(f"{description} is not one canonical JSON object")
        opened_after = os.fstat(stream.fileno())

    try:
        named_after = os.stat(source.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise SystemExit(f"{description} path changed during inspection: {exc}") from exc
finally:
    os.close(parent_fd)

stable_fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
if any(getattr(opened, field) != getattr(opened_after, field) for field in stable_fields) or any(
    getattr(opened_after, field) != getattr(named_after, field) for field in stable_fields
):
    raise SystemExit(f"{description} changed during inspection")

destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
destination_fd = os.open(snapshot, destination_flags, 0o600)
with os.fdopen(destination_fd, "wb", closefd=True) as stream:
    os.fchmod(stream.fileno(), 0o600)
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
PY
}

publish_private_receipt_no_replace() {
  local source_path="$1"
  local destination_path="$2"
  python3 - "$source_path" "$destination_path" "$(id -u)" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
expected_uid = int(sys.argv[3])
if source.parent != destination.parent:
    raise SystemExit("receipt staging and destination must share one directory")

parent_fd = os.open(
    source.parent,
    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
)
try:
    parent_metadata = os.fstat(parent_fd)
    if (
        parent_metadata.st_uid != expected_uid
        or stat.S_IMODE(parent_metadata.st_mode) & 0o077
    ):
        raise SystemExit("receipt parent must remain private to the invoking operator")

    source_fd = os.open(
        source.name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        source_metadata = os.fstat(source_fd)
        if (
            not stat.S_ISREG(source_metadata.st_mode)
            or source_metadata.st_uid != expected_uid
            or stat.S_IMODE(source_metadata.st_mode) != 0o600
            or source_metadata.st_nlink != 1
        ):
            raise SystemExit("staged receipt is not one private regular file")
        os.fsync(source_fd)
        try:
            os.link(
                source.name,
                destination.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise SystemExit("paired receipt target appeared during publication") from exc
        os.unlink(source.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(source_fd)
finally:
    os.close(parent_fd)
PY
}

SEALED_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-paired-candidate.XXXXXX")"
SEALED_ROOT="$SEALED_PARENT/source"
mkdir "$SEALED_ROOT"
cleanup() {
  local status=$?
  local cleanup_failed=0
  local temporary
  for temporary in \
    "$EXPECTED_RECEIPT" "$APP_MANIFEST" "$IMAGE_APP_MANIFEST" \
    "$RUNTIME_MANIFEST" "$IMAGE_RUNTIME_MANIFEST" "$PROOF_MANIFEST" \
    "$IMAGE_PROOF_MANIFEST" "$DEPENDENCY_SBOM" "$RECEIPT_TMP"; do
    if [ -n "$temporary" ] && ! rm -f -- "$temporary"; then
      cleanup_failed=1
    fi
  done
  if [ -n "$SEALED_PARENT" ] && [ -d "$SEALED_PARENT" ]; then
    if ! chmod -R u+rwX -- "$SEALED_PARENT"; then
      printf 'build-application-300-paired-candidate: sealed temp mode cleanup failed\n' >&2
      cleanup_failed=1
    fi
    if ! rm -rf -- "$SEALED_PARENT"; then
      printf 'build-application-300-paired-candidate: sealed temp cleanup failed\n' >&2
      cleanup_failed=1
    fi
  fi
  [ "$status" -ne 0 ] || [ "$cleanup_failed" -eq 0 ] || status=1
  exit "$status"
}
trap cleanup EXIT
git -C "$GIT_ROOT" archive --format=tar "$CANDIDATE_COMMIT" | tar -x -C "$SEALED_ROOT" || \
  die "candidate Git archive를 만들지 못했다"

python3 - "$SEALED_ROOT" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
required = (
    "docker/api.Dockerfile",
    "docker/dagster.Dockerfile",
    "docker/dagster-entrypoint.sh",
    "docker/dagster-storage-migrate.py",
    "docker/dagster.yaml",
    "docker/application-schema-final-permit.py",
    "docker/application-schema-contract.py",
    "scripts/build-application-300-candidate.sh",
    "scripts/build-application-300-paired-candidate.sh",
    "alembic/baseline/application-reference.json",
)
for relative in required:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"sealed paired candidate input is missing or symlinked: {relative}")
for path in (root, *root.rglob("*")):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"sealed candidate contains a symlink: {path.relative_to(root)}")
    if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
        raise SystemExit(f"sealed candidate contains a non-regular entry: {path.relative_to(root)}")
for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
    os.chmod(path, 0o555 if path.is_dir() else 0o444)
os.chmod(root, 0o555)
PY

sealed_builder="$SEALED_ROOT/scripts/build-application-300-paired-candidate.sh"
cmp -s "$sealed_builder" "$SCRIPT_DIR/build-application-300-paired-candidate.sh" || \
  die "executing paired builder가 sealed candidate commit과 다르다"
builder_script_sha256="$(sha256sum "$sealed_builder" | awk '{print $1}')"

# API receipt가 원자적으로 발행된 뒤 paired 단계가 중단된 경우는
# 원본을 삭제하거나 그대로 신뢰하지 않는다. O_NOFOLLOW로 열고 owner/mode/
# link count와 inode/metadata가 안정적인 한 번의 byte snapshot만 아래 verifier에
# 넘긴다. 그러면 같은 commit/image/receipt가 아닌 partial artifact는 닫힌다.
if [ "$MODE" = "build" ] && [ "$API_RECEIPT_PREEXISTED" -eq 0 ]; then
  api_builder=(
    "$SCRIPT_DIR/build-application-300-candidate.sh"
    --candidate-commit "$CANDIDATE_COMMIT"
    --image "$API_IMAGE"
    --git-root "$GIT_ROOT"
    --receipt "$API_RECEIPT"
  )
  "${api_builder[@]}" >&2
fi
API_RECEIPT_FOR_VERIFY="$SEALED_PARENT/api-receipt.snapshot"
snapshot_strict_receipt "$API_RECEIPT" "$API_RECEIPT_FOR_VERIFY" "API receipt"
if [ "$MODE" = "verify" ]; then
  RECEIPT_FOR_VERIFY="$SEALED_PARENT/paired-receipt.snapshot"
  snapshot_strict_receipt "$RECEIPT" "$RECEIPT_FOR_VERIFY" "paired receipt"
fi

api_builder=(
  "$SCRIPT_DIR/build-application-300-candidate.sh"
  --candidate-commit "$CANDIDATE_COMMIT"
  --image "$API_IMAGE"
  --git-root "$GIT_ROOT"
  --receipt "$API_RECEIPT_FOR_VERIFY"
)
api_candidate_json="$("${api_builder[@]}" --verify)" || die "API candidate 검증에 실패했다"
api_receipt_sha256="$(sha256sum "$API_RECEIPT_FOR_VERIFY" | awk '{print $1}')"

candidate_tree="$(git -C "$GIT_ROOT" rev-parse "${CANDIDATE_COMMIT}^{tree}")"
candidate_dockerfile_sha256="$(sha256sum "$SEALED_ROOT/docker/dagster.Dockerfile" | awk '{print $1}')"
candidate_base_image_reference="$(python3 - "$SEALED_ROOT/docker/dagster.Dockerfile" <<'PY'
import re
import sys
from pathlib import Path

stages = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"FROM (python@sha256:[0-9a-f]{64}) AS (builder|runtime)", line.strip())
    if match:
        reference, stage = match.groups()
        if stage in stages:
            raise SystemExit(f"duplicate Dagster Dockerfile stage: {stage}")
        stages[stage] = reference
if set(stages) != {"builder", "runtime"} or stages["builder"] != stages["runtime"]:
    raise SystemExit("Dagster Dockerfile must use one pinned Python base for both stages")
print(stages["runtime"])
PY
)"
candidate_base_image_id="$(docker image inspect -f '{{.Id}}' "$candidate_base_image_reference")"
[[ "$candidate_base_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "Dagster base image ID를 얻지 못했다"

if [ "$MODE" = "build" ]; then
  docker build --pull=false \
    --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$CANDIDATE_COMMIT" \
    --build-arg "KOR_TRAVEL_MAP_GIT_TREE=$candidate_tree" \
    --build-arg "KOR_TRAVEL_MAP_DOCKERFILE_SHA256=$candidate_dockerfile_sha256" \
    --build-arg "KOR_TRAVEL_MAP_BASE_IMAGE_REFERENCE=$candidate_base_image_reference" \
    --build-arg "KOR_TRAVEL_MAP_BASE_IMAGE_ID=$candidate_base_image_id" \
    -t "$DAGSTER_IMAGE" \
    -f "$SEALED_ROOT/docker/dagster.Dockerfile" \
    "$SEALED_ROOT" >&2
fi

image_id="$(docker image inspect -f '{{.Id}}' "$DAGSTER_IMAGE")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Dagster image ID를 얻지 못했다"
for label_and_expected in \
  "org.opencontainers.image.revision=$CANDIDATE_COMMIT" \
  "io.kor-travel-map.application-baseline.candidate-git-tree=$candidate_tree" \
  "io.kor-travel-map.application-baseline.candidate-dockerfile-sha256=$candidate_dockerfile_sha256" \
  "io.kor-travel-map.application-baseline.candidate-base-image-reference=$candidate_base_image_reference" \
  "io.kor-travel-map.application-baseline.candidate-base-image-id=$candidate_base_image_id"; do
  label="${label_and_expected%%=*}"
  expected="${label_and_expected#*=}"
  observed="$(docker image inspect -f "{{index .Config.Labels \"$label\"}}" "$image_id")"
  [ "$observed" = "$expected" ] || die "Dagster image provenance label이 sealed input과 다르다: $label"
done

candidate_rootfs_digests="$(python3 - \
  "$(docker image inspect -f '{{json .RootFS.Layers}}' "$candidate_base_image_reference")" \
  "$(docker image inspect -f '{{json .RootFS.Layers}}' "$image_id")" <<'PY'
import hashlib
import json
import sys

base = json.loads(sys.argv[1])
image = json.loads(sys.argv[2])
if (
    not isinstance(base, list)
    or not base
    or not isinstance(image, list)
    or any(not isinstance(value, str) or not value.startswith("sha256:") for value in base + image)
    or image[: len(base)] != base
):
    raise SystemExit("Dagster RootFS does not preserve the pinned runtime base prefix")
digest = lambda values: hashlib.sha256(  # noqa: E731
    json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode("ascii")
).hexdigest()
print(digest(base))
print(digest(image))
PY
)"
mapfile -t rootfs_fields <<<"$candidate_rootfs_digests"
[ "${#rootfs_fields[@]}" -eq 2 ] || die "Dagster RootFS digest pair를 얻지 못했다"
candidate_base_rootfs_layers_sha256="${rootfs_fields[0]}"
candidate_full_rootfs_layers_sha256="${rootfs_fields[1]}"

candidate_config_json="$(docker image inspect -f '{{json .Config}}' "$image_id")"
candidate_config_sha256="$(python3 - "$candidate_config_json" <<'PY'
import hashlib
import json
import sys

config = json.loads(sys.argv[1])
expected_entrypoint = ["/usr/local/bin/dagster-entrypoint.sh"]
expected_cmd = [
    "/usr/local/bin/dagster-webserver", "-m", "kortravelmap.dagster.definitions",
    "-h", "0.0.0.0", "-p", "12702",
]
if config.get("User") != "appuser" or config.get("WorkingDir") != "/app":
    raise SystemExit("Dagster image User/WorkingDir does not match the sealed contract")
if config.get("Entrypoint") != expected_entrypoint or config.get("Cmd") != expected_cmd:
    raise SystemExit("Dagster image Entrypoint/Cmd does not match the sealed contract")
environment = config.get("Env")
if not isinstance(environment, list) or any(not isinstance(item, str) for item in environment):
    raise SystemExit("Dagster image environment metadata is invalid")
values = dict(item.split("=", 1) for item in environment if "=" in item)
required = {
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONNOUSERSITE": "1",
    "KOR_TRAVEL_MAP_DAGSTER_PROFILE": "production",
    "KOR_TRAVEL_MAP_IMAGE_REVISION": config["Labels"]["org.opencontainers.image.revision"],
}
if any(values.get(key) != value for key, value in required.items()):
    raise SystemExit("Dagster image sealed runtime environment is invalid")
if any(key in values for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE")):
    raise SystemExit("Dagster image contains a forbidden Python path override")
canonical = {
    "Cmd": config["Cmd"],
    "Entrypoint": config["Entrypoint"],
    "Env": sorted(environment),
    "User": config["User"],
    "WorkingDir": config["WorkingDir"],
}
raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
print(hashlib.sha256(raw).hexdigest())
PY
)"

APP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-app.XXXXXX")"
IMAGE_APP_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-image-app.XXXXXX")"
python3 - "$SEALED_ROOT" >"$APP_MANIFEST" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
base = root / "alembic/baseline"
for source in sorted(path for path in base.rglob("*") if path.is_file() and not path.is_symlink()):
    destination = Path("alembic/baseline") / source.relative_to(base)
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination.as_posix()}")
PY
docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$image_id" -I -c '
import hashlib
from pathlib import Path
root = Path("/app")
for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink()):
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
' >"$IMAGE_APP_MANIFEST"
cmp -s "$APP_MANIFEST" "$IMAGE_APP_MANIFEST" || \
  die "Dagster image /app baseline tree가 sealed candidate와 다르다"
candidate_app_manifest_sha256="$(sha256sum "$APP_MANIFEST" | awk '{print $1}')"

RUNTIME_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-runtime.XXXXXX")"
IMAGE_RUNTIME_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-image-runtime.XXXXXX")"
python3 - "$SEALED_ROOT" >"$RUNTIME_MANIFEST" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
items = {}
for source_prefix, destination_prefix in (
    ("src/kortravelmap", ""),
    ("packages/kor-travel-map-dagster/src/kortravelmap/dagster", "dagster"),
):
    base = root / source_prefix
    for source in sorted(path for path in base.rglob("*") if path.is_file() and not path.is_symlink()):
        destination = "/".join(part for part in (destination_prefix, source.relative_to(base).as_posix()) if part)
        if destination in items:
            raise SystemExit(f"duplicate Dagster runtime destination: {destination}")
        items[destination] = source
for destination, source in sorted(items.items()):
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$image_id" -I -c '
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
  die "Dagster installed runtime tree가 sealed candidate와 다르다"
candidate_runtime_manifest_sha256="$(sha256sum "$RUNTIME_MANIFEST" | awk '{print $1}')"

PROOF_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-proof.XXXXXX")"
IMAGE_PROOF_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-image-proof.XXXXXX")"
python3 - "$SEALED_ROOT" >"$PROOF_MANIFEST" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
for source_rel, destination in (
    ("docker/dagster-entrypoint.sh", "usr/local/bin/dagster-entrypoint.sh"),
    ("docker/dagster-storage-migrate.py", "usr/local/bin/ktm-dagster-storage"),
    ("docker/application-schema-final-permit.py", "usr/local/bin/ktm-application-schema-final-permit"),
    ("docker/application-schema-contract.py", "usr/local/bin/ktm-application-schema-contract"),
    ("docker/dagster.yaml", "opt/dagster/dagster_home/dagster.yaml"),
):
    source = root / source_rel
    print(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {destination}")
PY
docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$image_id" -I -c '
import hashlib
from pathlib import Path
filesystem_root = Path("/")
for value in (
    "/usr/local/bin/dagster-entrypoint.sh",
    "/usr/local/bin/ktm-dagster-storage",
    "/usr/local/bin/ktm-application-schema-final-permit",
    "/usr/local/bin/ktm-application-schema-contract",
    "/opt/dagster/dagster_home/dagster.yaml",
):
    path = Path(value)
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"Dagster proof tool is missing or symlinked: {value}")
    print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(filesystem_root).as_posix()}")
' >"$IMAGE_PROOF_MANIFEST"
cmp -s "$PROOF_MANIFEST" "$IMAGE_PROOF_MANIFEST" || \
  die "Dagster entrypoint/proof tool tree가 sealed candidate와 다르다"
candidate_proof_manifest_sha256="$(sha256sum "$PROOF_MANIFEST" | awk '{print $1}')"
candidate_dagster_yaml_sha256="$(sha256sum "$SEALED_ROOT/docker/dagster.yaml" | awk '{print $1}')"
[[ "$candidate_dagster_yaml_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "sealed Dagster config SHA-256을 얻지 못했다"

DEPENDENCY_SBOM="$(mktemp "${TMPDIR:-/tmp}/ktm300-dagster-sbom.XXXXXX")"
docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$image_id" -I -c '
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
[ -s "$DEPENDENCY_SBOM" ] || die "Dagster dependency SBOM이 비어 있다"
candidate_dependency_sbom_sha256="$(sha256sum "$DEPENDENCY_SBOM" | awk '{print $1}')"

# read-only contract probe와 별개로, 실제 image의 appuser가 writable parent를 통해
# immutable baseline directory를 rename/replace할 수 없는지도 writable container
# layer에서 부정 증명한다. `--read-only`를 여기 쓰면 잘못된 image mode도 가려진다.
docker run --pull=never --rm --network=none --entrypoint /bin/sh "$image_id" -ec '
test ! -w /app/alembic
test ! -w /app/alembic/baseline
! mv /app/alembic/baseline /app/alembic/replaced 2>/dev/null
' || die "Dagster appuser가 immutable application baseline parent를 바꿀 수 있다"

api_image_id="$(python3 - "$api_candidate_json" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
expected = {
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256", "candidate_app_manifest_sha256",
    "candidate_runtime_manifest_sha256", "candidate_entrypoint_manifest_sha256",
    "candidate_dependency_sbom_sha256", "candidate_300_migration_sha256",
    "candidate_base_image_reference", "candidate_base_image_id",
    "candidate_base_rootfs_layers_sha256", "candidate_full_rootfs_layers_sha256",
    "candidate_proof_tools_manifest_sha256", "candidate_build_receipt_sha256",
}
if not isinstance(value, dict) or set(value) != expected:
    raise SystemExit("API candidate verifier returned an unexpected field set")
print(value["candidate_image_id"])
PY
)"
[[ "$api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "verified API image ID가 잘못됐다"

api_application_contract="$(docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$api_image_id" \
  -I /usr/local/bin/ktm-application-schema-contract contract)"
dagster_application_contract="$(docker run --pull=never --rm --network=none --read-only \
  --entrypoint /usr/local/bin/python "$image_id" \
  -I /usr/local/bin/ktm-application-schema-contract contract)"
[ "$api_application_contract" = "$dagster_application_contract" ] || \
  die "API와 Dagster image의 static application contract가 다르다"
application_contract_sha256="$(printf '%s\n' "$dagster_application_contract" | sha256sum | awk '{print $1}')"

EXPECTED_RECEIPT="$(mktemp "${TMPDIR:-/tmp}/ktm300-paired-expected.XXXXXX")"
python3 - "$EXPECTED_RECEIPT" "$api_candidate_json" "$api_receipt_sha256" \
  "$DAGSTER_IMAGE" "$image_id" "$CANDIDATE_COMMIT" "$candidate_tree" \
  "$candidate_dockerfile_sha256" "$candidate_base_image_reference" "$candidate_base_image_id" \
  "$candidate_base_rootfs_layers_sha256" "$candidate_full_rootfs_layers_sha256" \
  "$candidate_app_manifest_sha256" "$candidate_runtime_manifest_sha256" \
  "$candidate_proof_manifest_sha256" "$candidate_dependency_sbom_sha256" \
  "$candidate_config_sha256" "$dagster_application_contract" "$application_contract_sha256" \
  "$builder_script_sha256" "$candidate_dagster_yaml_sha256" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
api_candidate = json.loads(sys.argv[2])
dagster_image_id = sys.argv[5]
value = {
    "schema": "kor-travel-map.application-300-paired-candidate-build.v1",
    "candidate_commit": sys.argv[6],
    "candidate_git_tree": sys.argv[7],
    "paired_builder_script_sha256": sys.argv[20],
    "api_candidate": api_candidate,
    "api_candidate_build_receipt_sha256": sys.argv[3],
    "dagster_candidate": {
        "candidate_image": sys.argv[4],
        "candidate_image_id": dagster_image_id,
        "candidate_commit": sys.argv[6],
        "candidate_git_tree": sys.argv[7],
        "candidate_dockerfile_sha256": sys.argv[8],
        "candidate_base_image_reference": sys.argv[9],
        "candidate_base_image_id": sys.argv[10],
        "candidate_base_rootfs_layers_sha256": sys.argv[11],
        "candidate_full_rootfs_layers_sha256": sys.argv[12],
        "candidate_app_manifest_sha256": sys.argv[13],
        "candidate_runtime_manifest_sha256": sys.argv[14],
        "candidate_proof_manifest_sha256": sys.argv[15],
        "candidate_dependency_sbom_sha256": sys.argv[16],
        "candidate_config_sha256": sys.argv[17],
        "candidate_dagster_yaml_sha256": sys.argv[21],
        "application_contract": json.loads(sys.argv[18]),
        "application_contract_sha256": sys.argv[19],
    },
    "launch_contract": {
        "schema": "kor-travel-map.application-300-dagster-launch.v1",
        "requires_same_image_id": True,
        "application_final_permit_consumers": ["webserver", "daemon"],
        "webserver_image_id": dagster_image_id,
        "daemon_image_id": dagster_image_id,
        "storage_migration_image_id": dagster_image_id,
        "webserver_argv_policy": {
            "fixed_prefix": [
                "/usr/local/bin/dagster-webserver", "-m",
                "kortravelmap.dagster.definitions", "-h", "0.0.0.0", "-p",
            ],
            "port_decimal_minimum": 1,
            "port_decimal_maximum": 65535,
        },
        "image_default_webserver_argv": [
            "/usr/local/bin/dagster-webserver", "-m", "kortravelmap.dagster.definitions",
            "-h", "0.0.0.0", "-p", "12702",
        ],
        "daemon_argv": [
            "/usr/local/bin/dagster-daemon", "run", "-m", "kortravelmap.dagster.definitions",
        ],
        "storage_migration": {
            "scope": "dagster-metadata-only-excluded-from-application-final-permit",
            "argv": ["/usr/local/bin/ktm-dagster-storage", "migrate"],
            "forbidden_application_environment": [
                "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN",
                "KOR_TRAVEL_MAP_PG_DSN",
                "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_DAGSTER_IMAGE_ID",
                "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID",
            ],
            "forbids_application_final_permit_mount": True,
        },
        "metadata_database_identity_permit": {
            "schema": "kor-travel-map.dagster-storage-database-permit.v1",
            "path": "/run/kor-travel-map-dagster-storage-permit/permit.json",
            "production_authority": "docker-manager",
            "canonical_dagster_home": "/opt/dagster/dagster_home",
            "canonical_storage_env": "KOR_TRAVEL_MAP_DAGSTER_PG_URL",
            "candidate_binding_fields": [
                "dagster_image_id", "paired_candidate_build_receipt_sha256",
                "dagster_config_sha256",
            ],
            "dagster_config_receipt_field": "candidate_dagster_yaml_sha256",
            "database_identity_fields": [
                "system_identifier", "name", "oid", "owner", "login_role",
                "login_role_attributes",
            ],
            "required_login_role_attributes": {
                "superuser": False,
                "create_database": False,
                "create_role": False,
                "replication": False,
                "bypass_rls": False,
                "granted_role_count": 0,
                "member_role_count": 0,
            },
            "requires_owner_login_and_effective_role_equality": True,
            "forbidden_application_identity_fields": [
                "system_identifier", "name", "oid", "owner",
            ],
            "forbidden_application_raw_revision": "300",
        },
    },
}
if api_candidate["candidate_commit"] != value["candidate_commit"]:
    raise SystemExit("API and Dagster candidates do not share one sealed commit")
if api_candidate["candidate_git_tree"] != value["candidate_git_tree"]:
    raise SystemExit("API and Dagster candidates do not share one sealed tree")
if api_candidate["candidate_build_receipt_sha256"] != sys.argv[3]:
    raise SystemExit("API candidate receipt digest is inconsistent")
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY

if [ "$MODE" = "build" ]; then
  RECEIPT_TMP="$(mktemp "$RECEIPT_PARENT/.ktm300-paired-build.XXXXXX")"
  cp "$EXPECTED_RECEIPT" "$RECEIPT_TMP"
  chmod 600 "$RECEIPT_TMP"
  publish_private_receipt_no_replace "$RECEIPT_TMP" "$RECEIPT"
  RECEIPT_TMP=""
else
  cmp -s "$EXPECTED_RECEIPT" "$RECEIPT_FOR_VERIFY" || \
    die "paired candidate receipt가 현재 관측한 API + Dagster images와 다르다"
fi

# 최종 출력도 build/verify가 검증한 동일한 안정 snapshot에서만 읽는다.
if [ "$MODE" = "build" ]; then
  RECEIPT_FOR_VERIFY="$SEALED_PARENT/paired-receipt.snapshot"
  snapshot_strict_receipt "$RECEIPT" "$RECEIPT_FOR_VERIFY" "paired receipt"
  cmp -s "$EXPECTED_RECEIPT" "$RECEIPT_FOR_VERIFY" || \
    die "published paired candidate receipt가 expected receipt와 다르다"
fi

# build/verify 모두 stdout에는 strict receipt JSON 한 줄만 남긴다.
python3 - "$RECEIPT_FOR_VERIFY" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps(value, sort_keys=True, separators=(",", ":")))
PY
