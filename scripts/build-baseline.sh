#!/usr/bin/env bash
# alembic squash baseline 생성기. **손으로 쓰지 않는다** — 기계 생성 + 기계 정규화다.
#
# 왜 손으로 안 쓰는가:
#   0001~0104 체인이 만드는 카탈로그는 relation 108개 + routine 112개 + 제약/인덱스
#   수백 개다. 손으로 옮기면 빠뜨린 것을 아무도 모른다. 이 저장소가 2026-08-13에만
#   세 번 겪은 결함이 전부 "사본이 원본과 조용히 어긋남"이었다.
#
# 왜 3 스키마로 좁히는가:
#   role / schema / extension은 **체인 밖 bootstrap이 정본**이다
#   (`docker/postgres-role-bootstrap.sh`, `tests/integration/_tvn34_migration_bootstrap.py`).
#   baseline이 그것까지 재현하려 들면 손으로 옮겨야 하는 prologue가 생기고, 그게
#   이 작업의 최대 위험 표면이 된다. 스코프를 좁히면 그 표면이 통째로 사라진다.
#
# 왜 owner/ACL을 살리는가:
#   ADR-090의 소유권 분리(schema owner / state procedure owner / audit writer)가
#   보안 경계 본체다. `--no-owner`로 지우면 baseline이 그 경계를 재현하지 못한다.
#
# 왜 ACL 블록마다 role을 바꾸는가:
#   GRANT/REVOKE는 **객체 소유자만** 할 수 있다. baseline은 전 구간을 한 role
#   (`ktm_feature_schema_owner`)로 돌리는데, ADR-090의 role은 `NOINHERIT`이라
#   membership이 있어도 권한이 승계되지 않는다. 그리고 소유자가 아닌 GRANT는
#   **오류가 아니라 경고 후 무시**다. 그래서 첫 시도는 exit 0으로 조용히 통과하면서
#   routine 10개가 PUBLIC EXECUTE로 남았다(체인 102 → baseline 112). pg_dump가 ACL
#   블록마다 `Owner:` 주석을 달아 주므로 소유자를 기계적으로 유도해 `SET LOCAL ROLE`
#   한다. 그리고 그게 실제로 먹었는지 baseline 끝에서 digest로 **자기검증**한다 —
#   조용히 무시되는 결함은 조용히 잡히지 않는 검사기로 막을 수 없다.
#
# 사용:
#   # 1단계: isolated 0236에서 artifact/manifest를 기계 생성한다. 이 결과는 아직
#   # deploy candidate가 아니며, 2단계 final oracle을 통과해야만 release evidence다.
#   scripts/build-baseline.sh --mode materialize --isolated-0236-reference \
#     --source-certificate PATH --receipt PATH --out NEW_DIR \
#     <0236-container> <0236-db> [--admin-user U]
#
#   # 2단계: clean final candidate image가 실제 `300` migration을 적용한 fresh
#   # oracle과 source를 대조하고, 1단계 output 및 현재 candidate artifact의 byte
#   # 동등성을 재검증한다.
#   scripts/build-baseline.sh --mode verify --isolated-0236-reference \
#     --source-certificate PATH --receipt PATH --materialization-receipt PATH --out NEW_DIR \
#     --fresh-300-container CONTAINER --fresh-300-db DB \
#     --fresh-300-receipt PATH --candidate-build-receipt PATH \
#     <0236-container> <0236-db> [--admin-user U]
#
# `300`는 `0236`의 clean/disposable reference에서만 생성한다. 실제 n150, clone,
# fixture DB를 이 generator 입력으로 쓰는 것은 금지다. 아래 Docker label, raw head,
# source image/PG identity, static seed projection 및 immutable receipt를 모두 통과하지
# 않으면 dump 전에 중단한다.
set -euo pipefail

die() { printf 'build-baseline: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
OUT_DIR=""
ADMIN_USER=""
ISOLATED_REFERENCE=0
RECEIPT_PATH=""
FRESH_300_CONTAINER=""
FRESH_300_DB=""
FRESH_300_RECEIPT=""
MATERIALIZATION_RECEIPT=""
SOURCE_CERTIFICATE=""
CANDIDATE_BUILD_RECEIPT=""
HANDOFF_REHEARSAL_RECEIPT=""
MODE="verify"
CANDIDATE_IMAGE_EXPECTED=""
CANDIDATE_COMMIT_EXPECTED=""
CANDIDATE_PROVENANCE_JSON=""
CANDIDATE_SEALED_PARENT=""
CANDIDATE_SEALED_ROOT=""
SOURCE_CREATOR_SCRIPT_SHA256=""
FRESH_CREATOR_SCRIPT_SHA256=""
MATERIALIZER_SCRIPT_SHA256=""
SOURCE_COMMIT="01d65b2ad4ee265a3ef6b01448f6abf573a906a8"
SOURCE_HEAD="0236_tvn41s_compaction_drained"
SOURCE_IMAGE="postgis/postgis:16-3.5-alpine"
SOURCE_IMAGE_ID="sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c"
SOURCE_PG_VERSION="160014"
SOURCE_POSTGIS_VERSION="3.5.6"
SOURCE_MIGRATION_TREE="cb52c39e3d0f37bfe229532d94c2c91ea289b725"
RETIRED_MANIFEST_SHA256="3a3e96da12e8c8517fcac094749451307bb2b43e9bac249f2abe8864601d136e"
SOURCE_CHOREOGRAPHY="legacy-bootstrap>0225>m01-bootstrap>0232>0233>m05-pre-bootstrap>0235>0236>m05-repair-bootstrap"
SOURCE_DATABASE_TEMPLATE="template1"
SOURCE_GIT_TREE="84cd91c38700bdad2e817605d4cb3bc480affc2b"
SOURCE_DOCKERFILE_SHA256="882c042eb4a4b5f8bb66acc07301d7312a61e4377431b0627f6a5c906dda6975"
SOURCE_BOOTSTRAP_SHA256="b76dfc0317622c659be6b690c057c47c968ee1ea9dafbb873ae97c8dc34eea5c"
FRESH_BASELINE_SEED_RELATIONS=(
  "feature.curated_source_rules"
  "feature.curated_sources"
  "feature.curated_themes"
  "ops.feature_override_field_paths"
  "provider_sync.provider_dataset_operation_scopes"
  "provider_sync.provider_dataset_operations"
  "provider_sync.provider_datasets"
)
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --admin-user) ADMIN_USER="${2:?--admin-user needs a value}"; shift 2 ;;
    --out) OUT_DIR="${2:?--out needs a value}"; shift 2 ;;
    --receipt) RECEIPT_PATH="${2:?--receipt needs a value}"; shift 2 ;;
    --fresh-300-container) FRESH_300_CONTAINER="${2:?--fresh-300-container needs a value}"; shift 2 ;;
    --fresh-300-db) FRESH_300_DB="${2:?--fresh-300-db needs a value}"; shift 2 ;;
    --fresh-300-receipt) FRESH_300_RECEIPT="${2:?--fresh-300-receipt needs a value}"; shift 2 ;;
    --candidate-build-receipt) CANDIDATE_BUILD_RECEIPT="${2:?--candidate-build-receipt needs a value}"; shift 2 ;;
    --handoff-rehearsal-receipt) HANDOFF_REHEARSAL_RECEIPT="${2:?--handoff-rehearsal-receipt needs a value}"; shift 2 ;;
    --materialization-receipt) MATERIALIZATION_RECEIPT="${2:?--materialization-receipt needs a value}"; shift 2 ;;
    --source-certificate) SOURCE_CERTIFICATE="${2:?--source-certificate needs a value}"; shift 2 ;;
    --mode) MODE="${2:?--mode needs a value}"; shift 2 ;;
    --isolated-0236-reference) ISOLATED_REFERENCE=1; shift ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
CONTAINER="${ARGS[0]:?container required}"
DB="${ARGS[1]:?db required}"
USER_NAME="${ADMIN_USER:-postgres}"

[ "${#ARGS[@]}" -eq 2 ] || die "container와 db만 위치 인자로 허용한다"
[ "$MODE" = "materialize" ] || [ "$MODE" = "verify" ] || \
  die "--mode는 materialize 또는 verify여야 한다"
[ "$ISOLATED_REFERENCE" = "1" ] || die "--isolated-0236-reference가 필요하다"
[ -n "$SOURCE_CERTIFICATE" ] || die "--source-certificate PATH가 필요하다"
[ -n "$RECEIPT_PATH" ] || die "--receipt PATH가 필요하다"
[ -n "$OUT_DIR" ] || die "--out NEW_DIR가 필요하다 (기존 artifact directory 직접 수정 금지)"
[[ "$RECEIPT_PATH" == /* ]] || die "--receipt는 absolute path여야 한다"
[[ "$SOURCE_CERTIFICATE" == /* ]] || die "--source-certificate는 absolute path여야 한다"
[[ "$OUT_DIR" == /* ]] || die "--out은 absolute path여야 한다"
[[ ! -e "$OUT_DIR" && ! -L "$OUT_DIR" ]] || die "--out은 아직 존재하지 않는 새 directory여야 한다"
[[ ! -e "$RECEIPT_PATH" && ! -L "$RECEIPT_PATH" ]] || die "--receipt target은 아직 존재하지 않아야 한다"
[ -d "$(dirname -- "$OUT_DIR")" ] || die "--out parent directory가 없다"
[ -d "$(dirname -- "$RECEIPT_PATH")" ] || die "--receipt parent directory가 없다"
[[ -f "$SOURCE_CERTIFICATE" && ! -L "$SOURCE_CERTIFICATE" ]] || \
  die "source 0236 provenance certificate가 없다"
receipt_canonical="$(realpath -m -- "$RECEIPT_PATH")"
out_canonical="$(realpath -m -- "$OUT_DIR")"
source_certificate_canonical="$(realpath -m -- "$SOURCE_CERTIFICATE")"
for external_path in "$receipt_canonical" "$out_canonical" "$source_certificate_canonical"; do
  case "$external_path" in
    "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
      die "receipt와 generated artifact는 repository 밖 canonical path여야 한다"
      ;;
  esac
done

if [ "$MODE" = "materialize" ]; then
  [ -z "$FRESH_300_CONTAINER$FRESH_300_DB$FRESH_300_RECEIPT$MATERIALIZATION_RECEIPT$CANDIDATE_BUILD_RECEIPT$HANDOFF_REHEARSAL_RECEIPT" ] || \
    die "materialize 단계에는 fresh oracle 또는 materialization receipt를 넘길 수 없다"
else
  [ -n "$FRESH_300_CONTAINER" ] || die "--fresh-300-container가 필요하다"
  [ -n "$FRESH_300_DB" ] || die "--fresh-300-db가 필요하다"
  [ -n "$FRESH_300_RECEIPT" ] || die "--fresh-300-receipt PATH가 필요하다"
  [ -n "$MATERIALIZATION_RECEIPT" ] || die "--materialization-receipt PATH가 필요하다"
  [ -n "$CANDIDATE_BUILD_RECEIPT" ] || die "--candidate-build-receipt PATH가 필요하다"
  [ -n "$HANDOFF_REHEARSAL_RECEIPT" ] || die "--handoff-rehearsal-receipt PATH가 필요하다"
  [[ "$FRESH_300_RECEIPT" == /* ]] || die "--fresh-300-receipt는 absolute path여야 한다"
  [[ "$MATERIALIZATION_RECEIPT" == /* ]] || \
    die "--materialization-receipt는 absolute path여야 한다"
  [[ "$CANDIDATE_BUILD_RECEIPT" == /* ]] || \
    die "--candidate-build-receipt는 absolute path여야 한다"
  [[ "$HANDOFF_REHEARSAL_RECEIPT" == /* ]] || \
    die "--handoff-rehearsal-receipt는 absolute path여야 한다"
  [[ -f "$FRESH_300_RECEIPT" && ! -L "$FRESH_300_RECEIPT" ]] || \
    die "fresh 300 oracle provenance receipt가 없다"
  [[ -f "$MATERIALIZATION_RECEIPT" && ! -L "$MATERIALIZATION_RECEIPT" ]] || \
    die "materialization provenance receipt가 없다"
  [[ -f "$CANDIDATE_BUILD_RECEIPT" && ! -L "$CANDIDATE_BUILD_RECEIPT" ]] || \
    die "candidate build provenance receipt가 없다"
  [[ -f "$HANDOFF_REHEARSAL_RECEIPT" && ! -L "$HANDOFF_REHEARSAL_RECEIPT" ]] || \
    die "0236-to-300 handoff rehearsal receipt가 없다"
  fresh_receipt_canonical="$(realpath -m -- "$FRESH_300_RECEIPT")"
  materialization_receipt_canonical="$(realpath -m -- "$MATERIALIZATION_RECEIPT")"
  candidate_build_receipt_canonical="$(realpath -m -- "$CANDIDATE_BUILD_RECEIPT")"
  handoff_rehearsal_receipt_canonical="$(realpath -m -- "$HANDOFF_REHEARSAL_RECEIPT")"
  for external_path in "$fresh_receipt_canonical" "$materialization_receipt_canonical" \
    "$candidate_build_receipt_canonical" "$handoff_rehearsal_receipt_canonical"; do
    case "$external_path" in
      "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
        die "oracle/materialization receipt는 repository 밖 canonical path여야 한다"
        ;;
    esac
  done
fi

# Fresh oracle receipt는 repository 밖에서 generator가 one-shot으로 만든 immutable
# evidence다. 대상 path 교체·symlink·group writable receipt는 provenance가 아니므로
# DB를 읽기 전 fail-close한다. build와 creator는 같은 local operator UID로 실행한다.
if [ "$MODE" = "verify" ]; then
python3 - "$FRESH_300_RECEIPT" "$(id -u)" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"fresh 300 oracle receipt is unreadable: {exc}") from exc
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("fresh 300 oracle receipt must be a regular non-symlink file")
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("fresh 300 oracle receipt must have exact mode 0600")
if metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("fresh 300 oracle receipt owner does not match the build operator")
PY
python3 - "$MATERIALIZATION_RECEIPT" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"materialization receipt is unreadable: {exc}") from exc
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("materialization receipt must be a regular non-symlink file")
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("materialization receipt must have exact mode 0600")
if metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("materialization receipt owner does not match the build operator")
PY
python3 - "$CANDIDATE_BUILD_RECEIPT" "$(id -u)" <<'PY'
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
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("candidate build receipt must have exact mode 0600")
if metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("candidate build receipt owner does not match the build operator")
PY
python3 - "$HANDOFF_REHEARSAL_RECEIPT" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"handoff rehearsal receipt is unreadable: {exc}") from exc
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("handoff rehearsal receipt must be a regular non-symlink file")
if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o444:
    raise SystemExit("handoff rehearsal receipt must be root-owned mode 0444")
PY
fi

python3 - "$SOURCE_CERTIFICATE" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"source 0236 certificate is unreadable: {exc}") from exc
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("source 0236 certificate must be a regular non-symlink file")
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("source 0236 certificate must have exact mode 0600")
if metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("source 0236 certificate owner does not match the build operator")
PY

for relation in "${FRESH_BASELINE_SEED_RELATIONS[@]}"; do
  [[ "$relation" =~ ^[a-z_]+\.[a-z_]+$ ]] || die "static seed relation이 잘못됐다: $relation"
done

if [ "$MODE" = "verify" ]; then
  # receipt가 가리키는 committed candidate와 image를 먼저 얻고, 다음 단계에서 이
  # checkout과 무관한 sealed Git archive→image verifier를 재실행한다. 작업 폴더의
  # clean 상태나 HEAD를 provenance로 쓰지 않는다.
  fresh_candidate_identity="$(python3 - "$FRESH_300_RECEIPT" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"fresh 300 oracle receipt cannot be parsed: {exc}") from exc
if not isinstance(value, dict) or value.get("schema") != "kor-travel-map.application-fresh-300-oracle.v8":
    raise SystemExit("fresh 300 oracle receipt schema is invalid")
image = value.get("candidate_image")
commit = value.get("candidate_commit")
if not isinstance(image, str) or not image or any(char.isspace() for char in image):
    raise SystemExit("fresh 300 oracle receipt candidate image is invalid")
if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise SystemExit("fresh 300 oracle receipt candidate commit is invalid")
print(image)
print(commit)
PY
)"
  mapfile -t fresh_candidate_identity_fields <<< "$fresh_candidate_identity"
  [ "${#fresh_candidate_identity_fields[@]}" -eq 2 ] || \
    die "fresh 300 oracle receipt candidate identity를 읽지 못했다"
  CANDIDATE_IMAGE_EXPECTED="${fresh_candidate_identity_fields[0]}"
  CANDIDATE_COMMIT_EXPECTED="${fresh_candidate_identity_fields[1]}"
  CANDIDATE_PROVENANCE_JSON="$(bash "$SCRIPT_DIR/build-application-300-candidate.sh" \
    --verify --candidate-commit "$CANDIDATE_COMMIT_EXPECTED" \
    --image "$CANDIDATE_IMAGE_EXPECTED" --git-root "$REPOSITORY_ROOT" \
    --receipt "$CANDIDATE_BUILD_RECEIPT")"
  python3 - "$CANDIDATE_PROVENANCE_JSON" <<'PY'
from __future__ import annotations

import json
import re
import sys

try:
    value = json.loads(sys.argv[1])
except ValueError as exc:
    raise SystemExit(f"sealed candidate verifier result is invalid JSON: {exc}") from exc
required = {
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_300_migration_sha256", "candidate_base_image_reference",
    "candidate_base_image_id", "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_proof_tools_manifest_sha256",
    "candidate_build_receipt_sha256",
}
if not isinstance(value, dict) or set(value) != required:
    raise SystemExit("sealed candidate verifier result has an unexpected schema")
if not isinstance(value["candidate_image"], str) or any(char.isspace() for char in value["candidate_image"]):
    raise SystemExit("sealed candidate verifier image is invalid")
for key in ("candidate_commit", "candidate_git_tree"):
    if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{40}", value[key]):
        raise SystemExit(f"sealed candidate verifier commit/tree is invalid: {key}")
for key in (
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_300_migration_sha256", "candidate_base_rootfs_layers_sha256",
    "candidate_proof_tools_manifest_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_build_receipt_sha256",
):
    if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
        raise SystemExit(f"sealed candidate verifier digest is invalid: {key}")
if not isinstance(value["candidate_image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["candidate_image_id"]):
    raise SystemExit("sealed candidate verifier image ID is invalid")
if not isinstance(value["candidate_base_image_reference"], str) or not re.fullmatch(r"python@sha256:[0-9a-f]{64}", value["candidate_base_image_reference"]):
    raise SystemExit("sealed candidate verifier base reference is invalid")
if not isinstance(value["candidate_base_image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["candidate_base_image_id"]):
    raise SystemExit("sealed candidate verifier base image ID is invalid")
PY

  CANDIDATE_SEALED_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-baseline-candidate.XXXXXX")"
  CANDIDATE_SEALED_ROOT="$CANDIDATE_SEALED_PARENT/source"
  mkdir "$CANDIDATE_SEALED_ROOT"
  trap 'rm -f "${RAW:-}" "${RAW2:-}" "${SEED_LIST:-}"; [ -z "${BUILD_DIR:-}" ] || rm -rf -- "$BUILD_DIR"; [ -z "${CANDIDATE_SEALED_PARENT:-}" ] || rm -rf -- "$CANDIDATE_SEALED_PARENT"' EXIT
  if ! git -C "$REPOSITORY_ROOT" archive --format=tar "$CANDIDATE_COMMIT_EXPECTED" \
    | tar -x -C "$CANDIDATE_SEALED_ROOT"; then
    die "candidate Git archive를 만들지 못했다"
  fi
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
    "scripts/create-application-0236-source-oracle.sh",
    "scripts/create-application-300-fresh-oracle.sh",
    "scripts/build-baseline.sh",
    "scripts/rehearse-application-300-handoff.sh",
    "alembic/versions/300_schema_baseline.py",
    "alembic/baseline/application-reference.json",
    "alembic/baseline/application-catalog.sql",
    "alembic/baseline/application-seed.sql",
    "alembic/baseline/application-privileged-residue.sql",
    "alembic/baseline/application-runtime-invariants.sql",
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
  # Candidate proof tools are external to the API image. Prove their sealed
  # filenames and bytes here as well as in the candidate builder, so a later
  # local edit cannot reinterpret an otherwise valid candidate receipt.
  candidate_proof_rows=""
  for proof_relative in \
    scripts/create-application-0236-source-oracle.sh \
    scripts/create-application-300-fresh-oracle.sh \
    scripts/build-baseline.sh \
    scripts/rehearse-application-300-handoff.sh; do
    sealed_proof_tool="$CANDIDATE_SEALED_ROOT/$proof_relative"
    current_proof_tool="$REPOSITORY_ROOT/$proof_relative"
    [ -f "$sealed_proof_tool" ] && [ ! -L "$sealed_proof_tool" ] || \
      die "sealed candidate proof tool이 없다: $proof_relative"
    [ -f "$current_proof_tool" ] && [ ! -L "$current_proof_tool" ] || \
      die "executing proof tool이 regular file이 아니다: $proof_relative"
    cmp -s "$sealed_proof_tool" "$current_proof_tool" || \
      die "executing proof tool이 sealed candidate commit과 다르다: $proof_relative"
    candidate_proof_rows+="$(sha256sum "$sealed_proof_tool" | awk '{print $1}')  $proof_relative"$'\n'
  done
  candidate_proof_tools_manifest_sha256="$(printf '%s' "$candidate_proof_rows" | sha256sum | awk '{print $1}')"
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
  SOURCE_CREATOR_SCRIPT_SHA256="$(sha256sum "$CANDIDATE_SEALED_ROOT/scripts/create-application-0236-source-oracle.sh" | awk '{print $1}')"
  FRESH_CREATOR_SCRIPT_SHA256="$(sha256sum "$CANDIDATE_SEALED_ROOT/scripts/create-application-300-fresh-oracle.sh" | awk '{print $1}')"
  MATERIALIZER_SCRIPT_SHA256="$(sha256sum "$CANDIDATE_SEALED_ROOT/scripts/build-baseline.sh" | awk '{print $1}')"
  reference_manifest="$CANDIDATE_SEALED_ROOT/alembic/baseline/application-reference.json"
  python3 - "$reference_manifest" "$SOURCE_COMMIT" "$SOURCE_HEAD" "$SOURCE_IMAGE" \
    "$SOURCE_IMAGE_ID" "$SOURCE_PG_VERSION" "$SOURCE_POSTGIS_VERSION" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2:]
try:
    value = json.loads(path.read_text(encoding="utf-8"))
    source = value["source"]
    artifacts = value["artifacts"]
except (KeyError, OSError, ValueError, TypeError) as exc:
    raise SystemExit(f"invalid application reference manifest: {exc}") from exc
actual = (
    source.get("git_commit"),
    source.get("raw_alembic_revision"),
    source.get("container_image"),
    source.get("container_image_id"),
    source.get("postgres_server_version_num"),
    source.get("postgis_extension_version"),
)
if value.get("schema") != "kor-travel-map.application-baseline-reference.v1" or actual != tuple(expected):
    raise SystemExit("application reference manifest does not match the generator contract")
required_artifacts = {
    "schema_sql_sha256", "seed_sql_sha256", "catalog_contract_sql_sha256",
    "catalog_contract_sha256", "catalog_contract_receipt_sha256",
    "seed_contract_sql_sha256", "seed_contract_sha256",
    "seed_contract_receipt_sha256", "privileged_residue_contract_sql_sha256",
    "privileged_residue_contract_sha256", "privileged_residue_contract_receipt_sha256",
    "source_alembic_version_contract_sql_sha256",
    "source_alembic_version_contract_sha256",
    "source_alembic_version_contract_receipt_sha256",
    "destination_alembic_version_contract_sql_sha256",
    "destination_alembic_version_contract_sha256",
    "destination_alembic_version_contract_receipt_sha256",
    "runtime_invariants_sql_sha256",
}
if (
    set(artifacts) != required_artifacts
    or any(not isinstance(artifacts[key], str) or len(artifacts[key]) != 64
           or set(artifacts[key]) - set("0123456789abcdef")
           for key in required_artifacts)
):
    raise SystemExit("application reference manifest artifacts are incomplete")
PY
  reference_manifest_sha256="$(sha256sum "$reference_manifest" | awk '{print $1}')"
  candidate_catalog_receipt_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-catalog.sha256")"
  candidate_seed_receipt_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-seed.sha256")"
  candidate_privileged_residue_receipt_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-privileged-residue.sha256")"
  candidate_source_alembic_version_receipt_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-source-alembic-version.sha256")"
  candidate_destination_alembic_version_receipt_sha256="$(tr -d '\r\n' < "$CANDIDATE_SEALED_ROOT/alembic/baseline/application-destination-alembic-version.sha256")"
  for candidate_contract_receipt in \
    "$candidate_catalog_receipt_sha256" "$candidate_seed_receipt_sha256" \
    "$candidate_privileged_residue_receipt_sha256" \
    "$candidate_source_alembic_version_receipt_sha256" \
    "$candidate_destination_alembic_version_receipt_sha256"; do
    [[ "$candidate_contract_receipt" =~ ^[0-9a-f]{64}$ ]] || \
      die "sealed candidate contract receipt SHA-256을 읽지 못했다"
  done
fi

if [ "$MODE" = "materialize" ]; then
  SOURCE_CREATOR_SCRIPT_SHA256="$(sha256sum "$SCRIPT_DIR/create-application-0236-source-oracle.sh" | awk '{print $1}')"
  FRESH_CREATOR_SCRIPT_SHA256="$(sha256sum "$SCRIPT_DIR/create-application-300-fresh-oracle.sh" | awk '{print $1}')"
  MATERIALIZER_SCRIPT_SHA256="$(sha256sum "$SCRIPT_DIR/build-baseline.sh" | awk '{print $1}')"
fi

container_image_id="$(docker inspect -f '{{.Image}}' "$CONTAINER")"
source_container_id="$(docker inspect -f '{{.Id}}' "$CONTAINER")"
container_isolated="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.isolated"}}' "$CONTAINER")"
container_source_oracle="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-0236-oracle"}}' "$CONTAINER")"
container_commit="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-commit"}}' "$CONTAINER")"
container_head="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-head"}}' "$CONTAINER")"
container_source_image_id="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-id"}}' "$CONTAINER")"
container_source_migration_tree="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-migration-tree"}}' "$CONTAINER")"
container_source_git_tree="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-git-tree"}}' "$CONTAINER")"
container_source_dockerfile_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-dockerfile-sha256"}}' "$CONTAINER")"
container_source_image_app_manifest_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-app-manifest-sha256"}}' "$CONTAINER")"
container_source_image_runtime_manifest_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-runtime-manifest-sha256"}}' "$CONTAINER")"
container_source_builder_base_image_id="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-builder-base-image-id"}}' "$CONTAINER")"
container_source_builder_base_image_reference="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-builder-base-image-reference"}}' "$CONTAINER")"
container_source_build_dockerfile_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-build-dockerfile-sha256"}}' "$CONTAINER")"
container_source_image_dependency_sbom_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-dependency-sbom-sha256"}}' "$CONTAINER")"
[ "$container_image_id" = "$SOURCE_IMAGE_ID" ] || die "reference container image ID가 다르다"
[ "$container_isolated" = "true" ] || die "reference container가 disposable/isolated label이 없다"
[ "$container_source_oracle" = "true" ] || die "reference container가 source-oracle certificate label이 없다"
[ "$container_commit" = "$SOURCE_COMMIT" ] || die "reference container source commit label이 다르다"
[ "$container_head" = "$SOURCE_HEAD" ] || die "reference container source head label이 다르다"
[ "$container_source_migration_tree" = "$SOURCE_MIGRATION_TREE" ] || \
  die "reference container source migration tree label이 다르다"
[ "$container_source_git_tree" = "$SOURCE_GIT_TREE" ] || \
  die "reference container source Git tree label이 다르다"
[ "$container_source_dockerfile_sha256" = "$SOURCE_DOCKERFILE_SHA256" ] || \
  die "reference container source Dockerfile digest label이 다르다"
for source_image_manifest_digest in \
  "$container_source_image_app_manifest_sha256" \
  "$container_source_image_runtime_manifest_sha256" \
  "$container_source_build_dockerfile_sha256" \
  "$container_source_image_dependency_sbom_sha256"; do
  [[ "$source_image_manifest_digest" =~ ^[0-9a-f]{64}$ ]] || \
    die "reference container source image manifest digest label이 잘못됐다"
done
[[ "$container_source_builder_base_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "reference container source builder base image ID label이 잘못됐다"
[[ "$container_source_builder_base_image_reference" =~ ^python@sha256:[0-9a-f]{64}$ ]] || \
  die "reference container source builder immutable base image reference label이 잘못됐다"

# certificate의 digest-pinned base reference는 단순 문자열이 아니다. daemon이 실제로
# 그 reference를 같은 immutable image로 해석하고, source runtime image가 그 base의
# RootFS layer를 그대로 prefix로 포함하는지 재관측한다. 이 검사가 없으면 `/app`와
# Python distribution만 같게 만든 다른 OS/base image에 stale label/certificate를 붙인
# 반례가 provenance gate를 통과할 수 있다.
source_builder_base_image_id_actual="$(docker image inspect -f '{{.Id}}' "$container_source_builder_base_image_reference")"
[ "$source_builder_base_image_id_actual" = "$container_source_builder_base_image_id" ] || \
  die "reference source builder immutable base reference가 recorded image ID와 다르다"
source_builder_base_image_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$container_source_builder_base_image_reference")"
source_image_rootfs_layers="$(docker image inspect -f '{{json .RootFS.Layers}}' "$container_source_image_id")"
python3 - "$source_builder_base_image_layers" "$source_image_rootfs_layers" <<'PY'
import json
import sys

try:
    base_layers = json.loads(sys.argv[1])
    source_layers = json.loads(sys.argv[2])
except ValueError as exc:
    raise SystemExit(f"source image RootFS layer metadata is invalid: {exc}") from exc
if (
    not isinstance(base_layers, list)
    or not isinstance(source_layers, list)
    or not base_layers
    or any(not isinstance(layer, str) or not layer.startswith("sha256:") for layer in base_layers)
    or any(not isinstance(layer, str) or not layer.startswith("sha256:") for layer in source_layers)
):
    raise SystemExit("source image RootFS layer metadata shape is invalid")
if source_layers[: len(base_layers)] != base_layers:
    raise SystemExit(
        "source application image RootFS does not preserve the recorded builder base layer prefix"
    )
PY

# source oracle creator가 label만 붙인 prebuilt image를 넘기는 경로를 막는다. detached
# image 자체를 다시 inspect하고 installed distribution manifest를 재계산해야 cert의
# range-dependency proof가 실제 runnable image와 연결된다.
source_image_id_actual="$(docker image inspect -f '{{.Id}}' "$container_source_image_id")"
[ "$source_image_id_actual" = "$container_source_image_id" ] || \
  die "reference source application image ID가 현재 local immutable image와 다르다"
[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$container_source_image_id")" = "$SOURCE_COMMIT" ] || \
  die "reference source application image OCI revision이 다르다"
source_image_dependency_sbom_actual="$(
  docker run --pull=never --rm --entrypoint python "$container_source_image_id" -c '
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
' | sha256sum | awk '{print $1}'
)"
[ "$source_image_dependency_sbom_actual" = "$container_source_image_dependency_sbom_sha256" ] || \
  die "reference source image installed dependency SBOM이 container label과 다르다"

source_revision="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At \
  -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version")"
[ "$source_revision" = "$SOURCE_HEAD" ] || die "reference DB raw Alembic head가 exact 0236이 아니다"
source_pg_version="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At -c 'SHOW server_version_num')"
source_postgis_version="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis'")"
source_system_identifier="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At -c 'SELECT system_identifier FROM pg_catalog.pg_control_system()')"
source_database_oid="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
source_database_owner="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$DB" -At -c 'SELECT datdba::regrole::text FROM pg_catalog.pg_database WHERE datname = current_database()')"
[ "$source_pg_version" = "$SOURCE_PG_VERSION" ] || die "reference PostgreSQL version이 다르다"
[ "$source_postgis_version" = "$SOURCE_POSTGIS_VERSION" ] || die "reference PostGIS version이 다르다"
[[ "$source_system_identifier" =~ ^[0-9]+$ ]] || die "source PostgreSQL system identifier를 얻지 못했다"
[[ "$source_database_oid" =~ ^[0-9]+$ ]] || die "source database OID를 얻지 못했다"
[ "$source_database_owner" = "ktm_feature_schema_owner" ] || die "source database owner가 exact schema owner가 아니다"

# source certificate는 old graph를 실제 runnable detached image로부터 만들었다는
# evidence다. label/raw revision은 편의 정보일 뿐 certificate의 대체물이 아니다.
python3 - "$SOURCE_CERTIFICATE" "$source_container_id" "$DB" "$source_database_oid" \
  "$source_system_identifier" "$SOURCE_COMMIT" "$SOURCE_HEAD" "$SOURCE_MIGRATION_TREE" \
  "$RETIRED_MANIFEST_SHA256" "$container_source_image_id" "$container_image_id" \
  "$SOURCE_CHOREOGRAPHY" "$source_revision" "$SOURCE_PG_VERSION" "$SOURCE_POSTGIS_VERSION" \
  "$SOURCE_GIT_TREE" "$SOURCE_DOCKERFILE_SHA256" "$SOURCE_BOOTSTRAP_SHA256" \
  "$container_source_image_app_manifest_sha256" "$container_source_image_runtime_manifest_sha256" \
  "$container_source_builder_base_image_id" "$container_source_builder_base_image_reference" \
  "$container_source_build_dockerfile_sha256" "$container_source_image_dependency_sbom_sha256" \
  "$SOURCE_CREATOR_SCRIPT_SHA256" \
  "$SOURCE_DATABASE_TEMPLATE" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"source 0236 certificate cannot be parsed: {exc}") from exc
initial_virgin_inventory = {
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
initial_virgin_inventory_sha256 = hashlib.sha256(
    json.dumps(initial_virgin_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
expected = {
    "schema": "kor-travel-map.application-source-0236-oracle.v8",
    "container_id": sys.argv[2],
    "database": sys.argv[3],
    "database_oid": int(sys.argv[4]),
    "postgres_system_identifier": sys.argv[5],
    "source_commit": sys.argv[6],
    "source_head": sys.argv[7],
    "source_migration_tree": sys.argv[8],
    "retired_manifest_sha256": sys.argv[9],
    "source_image_id": sys.argv[10],
    "postgis_image_id": sys.argv[11],
    "migration_choreography": sys.argv[12],
    "raw_alembic_revision": sys.argv[13],
    "postgres_server_version_num": sys.argv[14],
    "postgis_extension_version": sys.argv[15],
    "source_git_tree": sys.argv[16],
    "source_dockerfile_sha256": sys.argv[17],
    "source_bootstrap_sha256": sys.argv[18],
    "source_image_app_manifest_sha256": sys.argv[19],
    "source_image_runtime_manifest_sha256": sys.argv[20],
    "source_builder_base_image_id": sys.argv[21],
    "source_builder_base_image_reference": sys.argv[22],
    "source_build_dockerfile_sha256": sys.argv[23],
    "source_image_dependency_sbom_sha256": sys.argv[24],
    "creator_script_sha256": sys.argv[25],
    "source_database_provisioning": "explicit-create-database-from-template1-after-official-entrypoint-complete",
    "source_database_template": sys.argv[26],
    "source_initial_virgin_inventory": initial_virgin_inventory,
    "source_initial_virgin_inventory_sha256": initial_virgin_inventory_sha256,
}
required = set(expected)
if not isinstance(value, dict) or set(value) != required:
    raise SystemExit("source 0236 certificate schema is invalid")
if {key: value.get(key) for key in expected} != expected:
    raise SystemExit("source 0236 certificate does not bind the observed source")
for key in (
    "source_dockerfile_sha256",
    "source_bootstrap_sha256",
    "source_image_app_manifest_sha256",
    "source_image_runtime_manifest_sha256",
    "source_build_dockerfile_sha256",
    "source_image_dependency_sbom_sha256",
    "creator_script_sha256",
):
    digest = value.get(key)
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set("0123456789abcdef"):
        raise SystemExit(f"source 0236 certificate digest is invalid: {key}")
base_image_id = value.get("source_builder_base_image_id")
if not isinstance(base_image_id, str) or not __import__("re").fullmatch(r"sha256:[0-9a-f]{64}", base_image_id):
    raise SystemExit("source 0236 certificate builder base image ID is invalid")
base_image_reference = value.get("source_builder_base_image_reference")
if not isinstance(base_image_reference, str) or not __import__("re").fullmatch(
    r"python@sha256:[0-9a-f]{64}", base_image_reference
):
    raise SystemExit("source 0236 certificate builder immutable base image reference is invalid")
PY
source_certificate_sha256="$(sha256sum "$SOURCE_CERTIFICATE" | awk '{print $1}')"

if [ "$MODE" = "verify" ]; then
python3 - "$HANDOFF_REHEARSAL_RECEIPT" "$CANDIDATE_PROVENANCE_JSON" \
  "$source_certificate_sha256" "$DB" "$source_database_oid" "$source_database_owner" \
  "$source_system_identifier" "$candidate_catalog_receipt_sha256" \
  "$candidate_seed_receipt_sha256" "$candidate_privileged_residue_receipt_sha256" \
  "$candidate_source_alembic_version_receipt_sha256" \
  "$candidate_destination_alembic_version_receipt_sha256" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from uuid import UUID

try:
    receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    candidate = json.loads(sys.argv[2])
except (OSError, ValueError) as exc:
    raise SystemExit(f"handoff rehearsal receipt/candidate cannot be parsed: {exc}") from exc
catalog_sha, seed_sha, privileged_sha, source_alembic_sha, destination_alembic_sha = (
    sys.argv[8:13]
)
expected_fields = {
    "schema", "candidate_commit", "candidate_image_id", "candidate_build_receipt_sha256",
    "candidate_proof_tools_manifest_sha256", "source_certificate_sha256",
    "source_database_identity", "source_catalog_sha256", "source_seed_sha256",
    "source_privileged_residue_sha256", "source_alembic_version_sha256",
    "expected_catalog_sha256", "expected_seed_sha256",
    "expected_privileged_residue_sha256", "positive_database_identity",
    "expected_source_alembic_version_sha256",
    "expected_destination_alembic_version_sha256",
    "positive_writer_fence_receipt_sha256", "positive_writer_fence_transaction_id",
    "positive_writer_fence_file_metadata", "positive_raw_revision", "positive_catalog_sha256",
    "positive_seed_sha256", "positive_privileged_residue_sha256",
    "positive_source_alembic_version_sha256",
    "positive_destination_alembic_version_sha256", "positive_result_sha256",
    "negative_database_identity", "negative_writer_fence_receipt_sha256",
    "negative_writer_fence_transaction_id", "negative_writer_fence_file_metadata",
    "negative_raw_revision", "negative_catalog_sha256_before", "negative_seed_sha256_before",
    "negative_privileged_residue_sha256_before",
    "negative_source_alembic_version_sha256_before", "negative_catalog_sha256_after",
    "negative_seed_sha256_after", "negative_privileged_residue_sha256_after",
    "negative_source_alembic_version_sha256_after",
    "negative_failure", "terminal_receipt_writer",
}
if not isinstance(receipt, dict) or set(receipt) != expected_fields:
    raise SystemExit("handoff rehearsal receipt has an unexpected field set")
if receipt["schema"] != "kor-travel-map.application-300-handoff-rehearsal.v3":
    raise SystemExit("handoff rehearsal receipt schema is invalid")
for receipt_key, candidate_key in (
    ("candidate_commit", "candidate_commit"),
    ("candidate_image_id", "candidate_image_id"),
    ("candidate_build_receipt_sha256", "candidate_build_receipt_sha256"),
    ("candidate_proof_tools_manifest_sha256", "candidate_proof_tools_manifest_sha256"),
):
    if receipt[receipt_key] != candidate.get(candidate_key):
        raise SystemExit(f"handoff rehearsal receipt candidate binding drifted: {receipt_key}")
if receipt["source_certificate_sha256"] != sys.argv[3]:
    raise SystemExit("handoff rehearsal receipt source certificate binding drifted")
source_identity = receipt["source_database_identity"]
if source_identity != {
    "database_name": sys.argv[4],
    "database_oid": int(sys.argv[5]),
    "database_owner": sys.argv[6],
    "postgres_system_identifier": sys.argv[7],
}:
    raise SystemExit("handoff rehearsal receipt source DB identity drifted")
for name in ("positive_database_identity", "negative_database_identity"):
    identity = receipt[name]
    if (
        not isinstance(identity, dict)
        or set(identity) != set(source_identity)
        or not isinstance(identity["database_name"], str)
        or not isinstance(identity["database_oid"], int)
        or identity["database_owner"] != "ktm_feature_schema_owner"
        or identity["postgres_system_identifier"] != sys.argv[7]
        or identity["database_oid"] == int(sys.argv[5])
    ):
        raise SystemExit(f"handoff rehearsal receipt {name} is invalid")
if (
    not receipt["positive_database_identity"]["database_name"].startswith("ktm300_handoff_positive_")
    or not receipt["negative_database_identity"]["database_name"].startswith("ktm300_handoff_negative_")
    or receipt["positive_database_identity"]["database_oid"]
       == receipt["negative_database_identity"]["database_oid"]
):
    raise SystemExit("handoff rehearsal receipt clone identity separation is invalid")
for key in (
    "source_catalog_sha256", "source_seed_sha256", "source_privileged_residue_sha256",
    "expected_catalog_sha256", "expected_seed_sha256", "expected_privileged_residue_sha256",
    "positive_catalog_sha256", "positive_seed_sha256", "positive_privileged_residue_sha256",
    "negative_catalog_sha256_before", "negative_seed_sha256_before",
    "negative_privileged_residue_sha256_before", "negative_catalog_sha256_after",
    "negative_seed_sha256_after", "negative_privileged_residue_sha256_after",
    "source_alembic_version_sha256", "expected_source_alembic_version_sha256",
    "expected_destination_alembic_version_sha256",
    "positive_source_alembic_version_sha256",
    "positive_destination_alembic_version_sha256",
):
    expected = {
        "source_catalog_sha256": catalog_sha,
        "source_seed_sha256": seed_sha,
        "source_privileged_residue_sha256": privileged_sha,
        "expected_catalog_sha256": catalog_sha,
        "expected_seed_sha256": seed_sha,
        "expected_privileged_residue_sha256": privileged_sha,
        "positive_catalog_sha256": catalog_sha,
        "positive_seed_sha256": seed_sha,
        "positive_privileged_residue_sha256": privileged_sha,
        "negative_catalog_sha256_before": catalog_sha,
        "negative_seed_sha256_before": seed_sha,
        "negative_privileged_residue_sha256_before": privileged_sha,
        "negative_catalog_sha256_after": catalog_sha,
        "negative_seed_sha256_after": seed_sha,
        "negative_privileged_residue_sha256_after": privileged_sha,
        "source_alembic_version_sha256": source_alembic_sha,
        "expected_source_alembic_version_sha256": source_alembic_sha,
        "expected_destination_alembic_version_sha256": destination_alembic_sha,
        "positive_source_alembic_version_sha256": source_alembic_sha,
        "positive_destination_alembic_version_sha256": destination_alembic_sha,
    }[key]
    if receipt[key] != expected:
        raise SystemExit(f"handoff rehearsal receipt contract binding drifted: {key}")
negative_before = receipt["negative_source_alembic_version_sha256_before"]
negative_after = receipt["negative_source_alembic_version_sha256_after"]
if (
    not isinstance(negative_before, str)
    or not re.fullmatch(r"[0-9a-f]{64}", negative_before)
    or negative_after != negative_before
    or negative_before == source_alembic_sha
):
    raise SystemExit("handoff rehearsal negative source facet proof is invalid")
for key in (
    "candidate_build_receipt_sha256", "candidate_proof_tools_manifest_sha256",
    "source_certificate_sha256", "positive_writer_fence_receipt_sha256",
    "positive_result_sha256", "negative_writer_fence_receipt_sha256",
):
    if not isinstance(receipt[key], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key]):
        raise SystemExit(f"handoff rehearsal receipt digest is invalid: {key}")
for key in ("positive_writer_fence_transaction_id", "negative_writer_fence_transaction_id"):
    try:
        UUID(str(receipt[key]))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"handoff rehearsal receipt fence transaction is invalid: {key}") from exc
if (
    receipt["positive_writer_fence_file_metadata"] != "0:444"
    or receipt["negative_writer_fence_file_metadata"] != "0:444"
    or receipt["positive_raw_revision"] != "300"
    or receipt["negative_raw_revision"] != "0236_tvn41s_compaction_drained"
    or receipt["negative_failure"] != "source-alembic-version-facet-mismatch"
    or receipt["terminal_receipt_writer"] != "root-candidate-image-atomic-link"
):
    raise SystemExit("handoff rehearsal receipt terminal state is invalid")
PY
handoff_rehearsal_receipt_sha256="$(sha256sum "$HANDOFF_REHEARSAL_RECEIPT" | awk '{print $1}')"
[[ "$handoff_rehearsal_receipt_sha256" =~ ^[0-9a-f]{64}$ ]] || \
  die "handoff rehearsal receipt SHA-256을 얻지 못했다"
[ "$FRESH_300_DB" != "$DB" ] || die "fresh 300 oracle DB는 0236 source DB와 달라야 한다"
[ "$FRESH_300_CONTAINER" != "$CONTAINER" ] || \
  die "fresh 300 oracle은 0236 source와 다른 disposable PostgreSQL cluster여야 한다"
fresh_image_id="$(docker inspect -f '{{.Image}}' "$FRESH_300_CONTAINER")"
fresh_container_id="$(docker inspect -f '{{.Id}}' "$FRESH_300_CONTAINER")"
fresh_postgis_image_id="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.postgis-image-id"}}' "$FRESH_300_CONTAINER")"
[ "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.isolated"}}' "$FRESH_300_CONTAINER")" = "true" ] || \
  die "fresh 300 oracle에 isolated label이 없다"
[ "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.fresh-300-oracle"}}' "$FRESH_300_CONTAINER")" = "true" ] || \
  die "fresh 300 oracle label이 없다"
[ "$fresh_image_id" = "$SOURCE_IMAGE_ID" ] || die "fresh 300 oracle image ID가 source image와 다르다"
[ "$fresh_postgis_image_id" = "$SOURCE_IMAGE_ID" ] || die "fresh 300 oracle PostGIS receipt가 image ID와 다르다"
source_cluster_mounts="$(docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$CONTAINER")"
fresh_cluster_mounts="$(docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$FRESH_300_CONTAINER")"
[ -n "$source_cluster_mounts" ] || die "source PostgreSQL cluster mount를 확인할 수 없다"
[ -n "$fresh_cluster_mounts" ] || die "fresh PostgreSQL cluster mount를 확인할 수 없다"
[ "$fresh_cluster_mounts" != "$source_cluster_mounts" ] || \
  die "fresh 300 oracle이 source와 같은 PostgreSQL data volume을 사용한다"
fresh_revision="$(docker exec "$FRESH_300_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$FRESH_300_DB" -At \
  -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version")"
[ "$fresh_revision" = "300" ] || die "fresh oracle DB raw Alembic head가 exact 300이 아니다"
fresh_pg_version="$(docker exec "$FRESH_300_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$FRESH_300_DB" -At -c 'SHOW server_version_num')"
fresh_postgis_version="$(docker exec "$FRESH_300_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$FRESH_300_DB" -At -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis'")"
fresh_system_identifier="$(docker exec "$FRESH_300_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$FRESH_300_DB" -At -c 'SELECT system_identifier FROM pg_catalog.pg_control_system()')"
[ "$fresh_pg_version" = "$SOURCE_PG_VERSION" ] || die "fresh oracle PostgreSQL version이 다르다"
[ "$fresh_postgis_version" = "$SOURCE_POSTGIS_VERSION" ] || die "fresh oracle PostGIS version이 다르다"
[[ "$fresh_system_identifier" =~ ^[0-9]+$ ]] || die "fresh PostgreSQL system identifier를 얻지 못했다"
[ "$fresh_system_identifier" != "$source_system_identifier" ] || \
  die "fresh 300 oracle이 source와 같은 PostgreSQL system identifier를 사용한다"
fresh_database_oid="$(docker exec "$FRESH_300_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$FRESH_300_DB" -At -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
[[ "$fresh_database_oid" =~ ^[0-9]+$ ]] || die "fresh oracle database OID를 얻지 못했다"

fresh_candidate_labels_json="$(python3 - \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-image"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-image-id"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-commit"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-git-tree"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-dockerfile-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-manifest-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-app-manifest-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-runtime-manifest-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-entrypoint-manifest-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-dependency-sbom-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-reference"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-image-id"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-base-rootfs-layers-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-full-rootfs-layers-sha256"}}' "$FRESH_300_CONTAINER")" \
  "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.candidate-build-receipt-sha256"}}' "$FRESH_300_CONTAINER")" <<'PY'
from __future__ import annotations

import json
import sys

keys = (
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_base_image_reference", "candidate_base_image_id",
    "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_build_receipt_sha256",
)
print(json.dumps(dict(zip(keys, sys.argv[1:], strict=True)), sort_keys=True, separators=(",", ":")))
PY
)"
creator_script_sha256="$FRESH_CREATOR_SCRIPT_SHA256"
bootstrap_script_sha256="$(sha256sum "$CANDIDATE_SEALED_ROOT/docker/postgres-role-bootstrap.sh" | awk '{print $1}')"
python3 - "$FRESH_300_RECEIPT" "$CANDIDATE_PROVENANCE_JSON" "$fresh_container_id" \
  "$FRESH_300_DB" "$fresh_database_oid" "$fresh_system_identifier" \
  "$SOURCE_IMAGE" "$SOURCE_IMAGE_ID" "$creator_script_sha256" "$bootstrap_script_sha256" \
  "$fresh_candidate_labels_json" "$candidate_destination_alembic_version_receipt_sha256" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    candidate = json.loads(sys.argv[2])
    labels = json.loads(sys.argv[11])
except (OSError, ValueError) as exc:
    raise SystemExit(f"fresh 300 oracle receipt/attestation cannot be parsed: {exc}") from exc
candidate_keys = {
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_300_migration_sha256", "candidate_base_image_reference",
    "candidate_base_image_id", "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_proof_tools_manifest_sha256",
    "candidate_build_receipt_sha256",
}
initial_virgin_inventory = {
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
initial_virgin_inventory_sha256 = hashlib.sha256(
    json.dumps(initial_virgin_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
expected = {
    "container_id": sys.argv[3],
    "database": sys.argv[4],
    "database_oid": int(sys.argv[5]),
    "postgres_system_identifier": sys.argv[6],
    **candidate,
    "bootstrap_phase": "baseline-300",
    "migration_command": (
        "ktm-application-schema-fresh-300 migrate --writer-fence-receipt "
        "/run/kor-travel-map-application-fresh-migrate/fence.json"
    ),
    "postgis_image": sys.argv[7],
    "postgis_image_id": sys.argv[8],
    "creator_script_sha256": sys.argv[9],
    "bootstrap_script_sha256": sys.argv[10],
    "raw_alembic_revision": "300",
    "fresh_database_provisioning": "explicit-create-database-from-template1-after-official-entrypoint-complete",
    "fresh_database_template": "template1",
    "fresh_initial_virgin_inventory": initial_virgin_inventory,
    "fresh_initial_virgin_inventory_sha256": initial_virgin_inventory_sha256,
}
required = {
    "schema", *expected, "application_relation_count", "catalog_sha256", "seed_sha256",
    "privileged_residue_sha256", "destination_alembic_version_sha256",
    "runtime_invariant_violation_count", "fresh_migration_result_sha256",
    "fresh_migration_evidence",
}
if not isinstance(receipt, dict) or receipt.get("schema") != "kor-travel-map.application-fresh-300-oracle.v8":
    raise SystemExit("fresh 300 oracle receipt schema is invalid")
if not isinstance(candidate, dict) or set(candidate) != candidate_keys:
    raise SystemExit("sealed candidate attestation schema is invalid")
if {key: receipt.get(key) for key in expected} != expected or set(receipt) != required:
    raise SystemExit("fresh 300 oracle receipt is not bound to the observed candidate/database")
label_bound_candidate_keys = candidate_keys - {
    "candidate_300_migration_sha256",
    "candidate_proof_tools_manifest_sha256",
}
if not isinstance(labels, dict) or {key: labels.get(key) for key in label_bound_candidate_keys} != {
    key: candidate[key] for key in label_bound_candidate_keys
}:
    raise SystemExit("fresh 300 oracle container labels are not bound to the sealed candidate")
if not isinstance(receipt["application_relation_count"], int) or receipt["application_relation_count"] < 1:
    raise SystemExit("fresh 300 oracle receipt application relation count is invalid")
if receipt["runtime_invariant_violation_count"] != 0:
    raise SystemExit("fresh 300 oracle receipt runtime invariant result is invalid")
for key in (
    "catalog_sha256",
    "seed_sha256",
    "privileged_residue_sha256",
    "destination_alembic_version_sha256",
):
    if not isinstance(receipt[key], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key]):
        raise SystemExit(f"fresh 300 oracle receipt digest is invalid: {key}")
evidence = receipt["fresh_migration_evidence"]
expected_evidence = {
    "schema": "kor-travel-map.application-fresh-300-migration.v2",
    "outcome": "migrated",
    "authorization": "manager-fence",
    "destination_head": "300",
    "map_candidate_commit": candidate["candidate_commit"],
    "map_candidate_image_id": candidate["candidate_image_id"],
    "reference_manifest_sha256": candidate["candidate_manifest_sha256"],
    "database_identity": {
        "database_name": sys.argv[4],
        "database_oid": int(sys.argv[5]),
        "database_owner": "ktm_feature_schema_owner",
        "postgres_system_identifier": sys.argv[6],
    },
    "journal_generation": 1,
    "expected_destination_alembic_version_sha256": sys.argv[12],
    "post_destination_alembic_version_sha256": sys.argv[12],
}
if not isinstance(evidence, dict) or any(
    evidence.get(key) != value for key, value in expected_evidence.items()
):
    raise SystemExit("fresh 300 oracle migration evidence binding drifted")
for key in (
    "writer_fence_receipt_sha256",
    "journal_sha256",
):
    if not isinstance(evidence.get(key), str) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence[key]
    ):
        raise SystemExit(f"fresh 300 oracle migration evidence digest is invalid: {key}")
if not isinstance(evidence.get("writer_fence_transaction_id"), str):
    raise SystemExit("fresh 300 oracle migration fence transaction is invalid")
canonical_evidence = (
    json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
).encode("utf-8")
if (
    not isinstance(receipt["fresh_migration_result_sha256"], str)
    or hashlib.sha256(canonical_evidence).hexdigest()
    != receipt["fresh_migration_result_sha256"]
):
    raise SystemExit("fresh 300 oracle migration result digest is invalid")
PY
candidate_image_id_actual="$(python3 - "$CANDIDATE_PROVENANCE_JSON" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["candidate_image_id"])
PY
)"
candidate_commit_expected="$CANDIDATE_COMMIT_EXPECTED"
fresh_candidate_image="$CANDIDATE_IMAGE_EXPECTED"
fi

BUILD_DIR="$(mktemp -d "$(dirname -- "$OUT_DIR")/.ktm300-baseline.XXXXXX")"
RAW="$(mktemp)"
trap 'rm -f "$RAW" "${RAW2:-}" "${SEED_LIST:-}"; [ -z "${BUILD_DIR:-}" ] || rm -rf -- "$BUILD_DIR"; [ -z "${CANDIDATE_SEALED_PARENT:-}" ] || rm -rf -- "$CANDIDATE_SEALED_PARENT"' EXIT

printf '=== pg_dump --schema-only (feature / provider_sync / ops) ===\n'
docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" \
  --schema-only \
  -n feature -n provider_sync -n ops \
  --exclude-table=public.alembic_version \
  -f /tmp/ktm-baseline-raw.sql
docker cp "$CONTAINER":/tmp/ktm-baseline-raw.sql "$RAW" >/dev/null
docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-raw.sql
printf '원본: %s줄\n' "$(wc -l < "$RAW")"

# routine ACL의 정규화된 digest. **한 곳에서만 정의한다** — 이 문자열이
#   (a) 빌드 시점의 기대값 계산과 (b) baseline이 적용 후 스스로 확인하는 관측값 계산
# 양쪽에 그대로 들어간다. 손으로 두 번 적으면 "검사기가 검사 대상과 어긋난 채 green"이
# 다시 생긴다.
#
# **텍스트가 아니라 유효 권한을 잰다.** 처음에는 `proacl` 문자열에서 `acldefault()`와
# 같은 항목을 빼는 방식이었는데, 그게 정확히 이 작업이 막으려던 결함을 못 잡았다:
# `acldefault('f', owner)`는 `{owner=X/owner, **=X/owner**}`를 돌려준다 — 함수의 기본
# ACL에 **PUBLIC EXECUTE가 포함**된다. 그래서 회수했던 routine 10개에 PUBLIC EXECUTE를
# 다시 부여해도 digest가 **한 글자도 변하지 않았다**(2026-08-14 적대 리뷰 실증).
# 소유자 물화만 지우려던 차감이 명시적 PUBLIC 부여까지 함께 지운 것이다.
#
# 문자열 차감으로는 "기본값과 같아서 생략된 것"과 "명시적으로 부여된 것"을 가를 수
# 없다. 그래서 `has_function_privilege()`로 **유효 권한**을 직접 묻는다 — 소유권 이전이
# proacl을 물화시키든 말든 답이 같고, PUBLIC 부여는 그대로 드러난다.
#
# grantee 목록은 **고정**한다. 처음에는 `pg_roles`에서 `ktm_feature%`를 긁었는데, 그러면
# digest가 환경에 따라 달라지면 안 된다. `300` baseline은 M01/M04/M05까지 마친
# final role graph를 재현하며, LOGIN principal도 일부 routine의 direct EXECUTE grantee다.
# 따라서 `ktm_feature_runtime` 상속만으로 생략하면 안 된다. 아래는 clean `0236`
# reference에서 관측한 direct grantee의 exact set이고, 새 grantee는 guard가 생성 단계에서
# 거부한다. 이 목록은 **두 곳**에 들어간다: digest의 grantee 축과, 그 축이 여전히
# 완전한지 묻는 아래 guard. 손으로 두 번 적으면 "guard가 digest와 다른 목록을 지키는"
# 상태가 생기므로 한 번만 적고 `@GRANTEES@`로 심는다.
# ⚠️ `scripts/compare-schema-catalogs.sh`의 `routineacl` 축은 이 값을 source로 읽는다.
ROUTINE_ACL_GRANTEE_VALUES="('public'),
                             ('ktm_curation_admin_executor'),
                             ('ktm_curation_audit_writer'),
                             ('ktm_curation_command_owner'),
                             ('ktm_curation_provider_executor'),
                             ('ktm_feature_api_runtime'),
                             ('ktm_feature_schema_owner'),
                             ('ktm_feature_state_procedure_owner'),
                             ('ktm_feature_audit_writer'),
                             ('ktm_feature_reference_reconciliation_service_executor'),
                             ('ktm_feature_runtime'),
                             ('ktm_feature_request_admin_executor'),
                             ('ktm_feature_request_procedure_owner'),
                             ('ktm_feature_request_service_executor'),
                             ('ktm_manual_feature_procedure_owner'),
                             ('ktm_manual_provider_dedup_admin_executor'),
                             ('ktm_manual_provider_dedup_detector_executor'),
                             ('ktm_manual_provider_dedup_procedure_owner')"

ROUTINE_ACL_DIGEST_SQL="$(cat <<'SQL'
SELECT encode(sha256(convert_to(coalesce(string_agg(line, chr(10) ORDER BY line), ''), 'UTF8')), 'hex')
  FROM (SELECT grantee.name
               || '|' || n.nspname || '.' || p.proname
               || '(' || pg_get_function_identity_arguments(p.oid) || ')'
               || '|execute=' || has_function_privilege(grantee.name, p.oid, 'EXECUTE')::text
               || '|grantopt=' || has_function_privilege(grantee.name, p.oid, 'EXECUTE WITH GRANT OPTION')::text
                 AS line
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          CROSS JOIN (VALUES @GRANTEES@) AS grantee(name)
         WHERE n.nspname IN ('feature','provider_sync','ops')) s
SQL
)"
ROUTINE_ACL_DIGEST_SQL="${ROUTINE_ACL_DIGEST_SQL/@GRANTEES@/$ROUTINE_ACL_GRANTEE_VALUES}"

# grantee 축이 여전히 **완전한지** 묻는다. digest는 위 고정 목록만 재므로, baseline이 미래에
# 새 role에 routine GRANT를 얻으면 그 축은 조용히 안 재진다 — digest는 한 글자도 안 변한다
# (2026-08-14 적대 리뷰 지적). 그래서 "실제 ACL에 등장하는 grantee 집합 ⊆ 고정 목록"을
# 별도로 단언한다. `pg_roles`를 긁지 않으므로 환경 role 수(테스트 5 / prod 7)와 무관하다.
#
# `coalesce(proacl, acldefault('f', proowner))`가 **load-bearing**이다. routine 112개 중
# 102개가 `proacl IS NULL`(기본 ACL)이라 생 `aclexplode(proacl)`은 그 행을 통째로 못 본다:
# 실측상 생 버전은 3개만 내놓고 **`public`과 `ktm_feature_audit_writer`를 잃는다** —
# PUBLIC EXECUTE 재부여와 SECURITY DEFINER owner 축, 즉 이 digest가 막으려는 결함 두 개가
# 그대로 사각지대가 된다.
ROUTINE_ACL_GRANTEE_GUARD_SQL="$(cat <<'SQL'
SELECT coalesce(string_agg(g.name, ', ' ORDER BY g.name), '')
  FROM (SELECT DISTINCT
               CASE WHEN a.grantee = 0 THEN 'public'
                    ELSE pg_get_userbyid(a.grantee) END AS name
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          CROSS JOIN LATERAL
               aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) AS a
         WHERE n.nspname IN ('feature','provider_sync','ops')) g
 WHERE NOT EXISTS (SELECT 1
                     FROM (VALUES @GRANTEES@) AS known(name)
                    WHERE known.name = g.name)
SQL
)"
ROUTINE_ACL_GRANTEE_GUARD_SQL="${ROUTINE_ACL_GRANTEE_GUARD_SQL/@GRANTEES@/$ROUTINE_ACL_GRANTEE_VALUES}"

printf '=== routine ACL digest (기대값) ===\n'
ACL_DIGEST="$(docker exec "$CONTAINER" psql -U "$USER_NAME" -d "$DB" -tA -c "$ROUTINE_ACL_DIGEST_SQL" | tr -d '[:space:]')"
[ ${#ACL_DIGEST} -eq 64 ] || die "routine ACL digest를 얻지 못했다: ${ACL_DIGEST:0:32}"
printf '  %s\n' "$ACL_DIGEST"

printf '=== routine ACL grantee 축 완전성 (빌드 시점) ===\n'
UNKNOWN_GRANTEES="$(docker exec "$CONTAINER" psql -U "$USER_NAME" -d "$DB" -tA \
  -c "$ROUTINE_ACL_GRANTEE_GUARD_SQL" | tr -d '\r')"
[ -z "$UNKNOWN_GRANTEES" ] || die "routine ACL에 고정 grantee 목록 밖의 grantee가 있다: ${UNKNOWN_GRANTEES} — ROUTINE_ACL_GRANTEE_VALUES에 추가하고 다시 빌드하라 (추가하지 않으면 digest가 그 축을 조용히 안 잰다)"
printf '  목록 밖 grantee 없음\n'

printf '=== 정규화 ===\n'
python3 - "$RAW" "$BUILD_DIR/schema.sql" "$ACL_DIGEST" "$ROUTINE_ACL_DIGEST_SQL" \
  "$ROUTINE_ACL_GRANTEE_GUARD_SQL" <<'PY'
import pathlib, re, sys

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
out_path = pathlib.Path(sys.argv[2])
acl_digest = sys.argv[3]
acl_digest_sql = sys.argv[4]
acl_grantee_guard_sql = sys.argv[5]
lines = raw.splitlines()
kept, dropped = [], {"version": 0, "preamble": 0, "psql_restrict": 0}

# 4. preamble에서 **search_path 고정만** 버린다. alembic/env.py가 트랜잭션 안에서
#    search_path를 세우므로 dump의 `set_config('search_path','')`가 그걸 덮으면 안 된다.
#
#    ⚠️ 나머지 `SET`은 남긴다. 특히 `SET check_function_bodies = false`는
#    **load-bearing**이다 — pg_dump는 함수를 테이블보다 먼저 낼 수 있고, 그때 본문이
#    참조하는 relation이 아직 없으면 컴파일이 실패한다. 처음에 preamble을 통째로
#    버렸다가 정확히 그 오류를 만났다
#    (`ERROR: relation "feature.features" does not exist / compilation of PL/pgSQL
#    function "apply_provider_feature_field_patch"`).
PREAMBLE = re.compile(
    r"^SELECT pg_catalog\.set_config\('search_path'"
)
for line in lines:
    # PostgreSQL 16의 pg_dump는 random token을 품은 `\restrict` / `\unrestrict`
    # pair를 낸다. 이는 psql client-side injection fence이지 server catalog가 아니며,
    # token이 매 dump마다 달라 그대로 두면 deterministic artifact가 될 수 없다.
    # 허용 범위를 이 정확한 한 쌍으로만 닫아 두고, 다른 메타명령은 여전히 fail-close다.
    if re.fullmatch(r"\\(?:un)?restrict [A-Za-z0-9]+", line):
        dropped["psql_restrict"] += 1
        continue
    if line.startswith("\\"):
        raise SystemExit(f"psql 메타명령이 dump에 있다 — 정규화 규칙을 갱신하라: {line[:60]!r}")
    # 3. 판올림마다 바뀌는 버전 주석 2줄
    if line.startswith("-- Dumped from database version") or line.startswith("-- Dumped by pg_dump version"):
        dropped["version"] += 1
        continue
    if PREAMBLE.match(line):
        dropped["preamble"] += 1
        continue
    kept.append(line)

text = "\n".join(kept)

# 5. CREATE SCHEMA -> IF NOT EXISTS. bootstrap이 먼저 만들어 두므로 충돌하면 안 된다.
text, n_schema = re.subn(
    r"^CREATE SCHEMA (feature|provider_sync|ops);$",
    r"CREATE SCHEMA IF NOT EXISTS \1;",
    text,
    flags=re.MULTILINE,
)
if n_schema != 3:
    raise SystemExit(f"CREATE SCHEMA 3개를 기대했는데 {n_schema}개를 바꿨다")

# 7. ACL 블록을 **그 블록의 소유자로** 실행한다 (파일 상단 주석의 근거 참조).
#    pg_dump는 ACL을 파일 끝에 모아 내므로 "첫 ACL 이후는 전부 ACL"을 전제로 삼되,
#    그 전제를 가정하지 않고 **검사한다** — 깨지면 여기서 선다.
HEADER = re.compile(
    r"^-- Name: (?P<name>.+); Type: (?P<type>[A-Z ]+); Schema: (?P<schema>.+); Owner: (?P<owner>.*)$"
)
ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

out: list[str] = []
acl_started = False
expect_close = False
pending_owner: str | None = None
current_role: str | None = None
n_role_switch = 0
for line in text.split("\n"):
    matched = HEADER.match(line)
    if matched:
        block_type = matched.group("type").strip()
        if block_type == "ACL":
            owner = matched.group("owner").strip()
            if not ROLE_NAME.match(owner):
                raise SystemExit(f"ACL 블록 소유자를 읽지 못했다: {line[:90]!r}")
            pending_owner = owner
            expect_close = True
        elif acl_started:
            raise SystemExit(
                "ACL 블록 뒤에 non-ACL 블록이 있다 — role 전환 구간이 파일 끝까지"
                f" 이어진다는 전제가 깨졌다: {line[:90]!r}"
            )
    out.append(line)
    if expect_close and line == "--":
        expect_close = False
        if not acl_started:
            acl_started = True
            out.append("")
            out.append("-- [build-baseline] 아래부터 ACL 구간. 각 블록을 소유자로 실행한다.")
            out.append("SELECT set_config('ktm.baseline_prior_role', current_user, true);")
            out.append("-- 트랜잭션 밖(psql autocommit 등)에서 돌리면 `SET LOCAL`이 통째로")
            out.append("-- 무효가 되어 ACL이 소유자 아닌 세션으로 나가고, 그래도 exit 0으로")
            out.append("-- 끝난다. 커스텀 GUC는 미정의가 아니라 **빈 문자열**로 되돌아오므로")
            out.append("-- 그것만으로는 터지지 않는다 — 그래서 여기서 명시적으로 막는다.")
            out.append("DO $ktm_txn$")
            out.append("BEGIN")
            out.append("    IF coalesce(current_setting('ktm.baseline_prior_role', true), '') = '' THEN")
            out.append("        RAISE EXCEPTION")
            out.append("            'baseline은 하나의 트랜잭션 안에서 적용해야 한다 —"
                       " 트랜잭션 밖에서는 SET LOCAL이 무효라 ACL이 소유자가 아닌 세션으로 나간다'")
            out.append("            USING ERRCODE = '25P01';")
            out.append("    END IF;")
            out.append("END")
            out.append("$ktm_txn$;")
        if pending_owner != current_role:
            current_role = pending_owner
            out.append(f"SELECT set_config('role', '{current_role}', true);")
            n_role_switch += 1
        pending_owner = None

if not acl_started:
    raise SystemExit("ACL 블록을 하나도 찾지 못했다 — pg_dump 출력 형식이 바뀌었다")
out.append("")
out.append("SELECT set_config('role', current_setting('ktm.baseline_prior_role'), true);")

# 8-a. grantee 축 완전성. digest보다 **먼저** 낸다 — 새 grantee는 digest를 바꾸지
#      않으므로(그게 사각지대다) digest가 먼저 통과해 버리면 이 진단이 영영 안 나온다.
out.append(
    "\nDO $ktm_acl_grantee$\n"
    "DECLARE\n"
    "    unknown text;\n"
    "BEGIN\n"
    f"    unknown := ({acl_grantee_guard_sql});\n"
    "    IF unknown <> '' THEN\n"
    "        RAISE EXCEPTION\n"
    "            'baseline routine ACL에 digest가 재지 않는 grantee가 있다: % —"
    " routine ACL digest는 고정 grantee 목록만 재므로 이 축은 조용히 빠진다."
    " scripts/build-baseline.sh의 ROUTINE_ACL_GRANTEE_VALUES에 추가하고 baseline을"
    " 다시 생성하라', unknown\n"
    "            USING ERRCODE = '42501';\n"
    "    END IF;\n"
    "END\n"
    "$ktm_acl_grantee$;"
)

# 8-b. 자기검증. 소유자 아닌 GRANT는 경고만 내고 무시되므로 **적용 성공(exit 0)이
#      ACL 적용의 증거가 되지 못한다.** baseline이 스스로 확인하게 한다.
out.append(
    "\nDO $ktm_acl$\n"
    "DECLARE\n"
    "    observed text;\n"
    f"    expected text := '{acl_digest}';\n"
    "BEGIN\n"
    f"    observed := ({acl_digest_sql});\n"
    "    IF observed IS DISTINCT FROM expected THEN\n"
    "        RAISE EXCEPTION\n"
    "            'baseline routine ACL이 원본과 다르다 (관측 %, 기대 %) — 소유자가 아닌"
    " 세션이 GRANT/REVOKE를 냈을 가능성이 크다', observed, expected\n"
    "            USING ERRCODE = '42501';\n"
    "    END IF;\n"
    "END\n"
    "$ktm_acl$;"
)
text = "\n".join(out)

if not text.endswith("\n"):
    text += "\n"
out_path.write_bytes(text.encode("utf-8"))
print(f"  버전 주석 제거: {dropped['version']}줄")
print(f"  preamble 제거:  {dropped['preamble']}줄")
print(f"  psql restrict fence 제거: {dropped['psql_restrict']}줄")
print(f"  CREATE SCHEMA IF NOT EXISTS 치환: {n_schema}개")
print(f"  ACL role 전환 삽입: {n_role_switch}회")
print(f"  결과: {len(text.splitlines())}줄")
PY

printf '=== seed 데이터 ===\n'
# fresh root seed는 allow-list다. 전체 nonempty table을 dump하면 provider 적재·fixture·
# 운영 audit가 baseline으로 승격된다. 반대로 handoff receipt는 이 fresh seed 전체를
# exact compare하지 않는다 — curated/provider catalog는 정상 admin/운영 command가 바꿀
# 수 있기 때문이다. runtime revision projection 두 표는 migration이 0에서 초기화한다.
#
# disposable `0236` reference에는 아래 fresh seed와 runtime projection 외의 application
# data가 하나도 없어야 한다. 그 전제를 SQL로 증명한 뒤에만 dump한다.
SEED_LIST="$(mktemp)"
printf '%s\n' "${FRESH_BASELINE_SEED_RELATIONS[@]}" > "$SEED_LIST"

unexpected_nonempty="$(docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -q -U "$USER_NAME" -d "$DB" -tA -c "
DO \$\$
DECLARE r record; has_rows boolean;
BEGIN
    CREATE TEMP TABLE ktm_unexpected_nonempty(rel text PRIMARY KEY);
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname IN ('feature', 'provider_sync', 'ops')
          AND (schemaname || '.' || tablename) NOT IN (
              'feature.curated_source_rules',
              'feature.curated_sources',
              'feature.curated_themes',
              'ops.feature_override_field_paths',
              'ops.import_job_event_clock',
              'ops.ops_live_topic_revisions',
              'provider_sync.provider_dataset_operation_scopes',
              'provider_sync.provider_dataset_operations',
              'provider_sync.provider_datasets'
          )
        ORDER BY schemaname, tablename
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I)', r.schemaname, r.tablename)
            INTO has_rows;
        IF has_rows THEN
            INSERT INTO ktm_unexpected_nonempty(rel)
            VALUES (r.schemaname || '.' || r.tablename);
        END IF;
    END LOOP;
END \$\$;
SELECT coalesce(string_agg(rel, ',' ORDER BY rel), '') FROM ktm_unexpected_nonempty;")"
[ -z "$unexpected_nonempty" ] || die "reference DB에 fresh seed 밖의 live/fixture data가 있다: $unexpected_nonempty"

printf 'seed 대상 %s개:\n' "$(wc -l < "$SEED_LIST")"
sed 's/^/  /' "$SEED_LIST"

SEED_ARGS=()
while IFS= read -r rel; do SEED_ARGS+=(-t "$rel"); done < "$SEED_LIST"
if [ "${#SEED_ARGS[@]}" -gt 0 ]; then
  # `--column-inserts` 필수 — `COPY ... FROM stdin`은 migration의 SQL 실행 경로로
  # 돌릴 수 없다.
  docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" \
    --data-only --column-inserts --no-owner \
    "${SEED_ARGS[@]}" -f /tmp/ktm-baseline-seed.sql
  docker cp "$CONTAINER":/tmp/ktm-baseline-seed.sql "$BUILD_DIR/seed.sql" >/dev/null
  docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-seed.sql
  python3 - "$BUILD_DIR/seed.sql" <<'PY'
import pathlib, re, sys
p = pathlib.Path(sys.argv[1])
lines = [
    line for line in p.read_text(encoding="utf-8").splitlines()
    if not line.startswith(("-- Dumped from database version", "-- Dumped by pg_dump version"))
    and not line.startswith("SELECT pg_catalog.set_config('search_path'")
    and not re.fullmatch(r"\\(?:un)?restrict [A-Za-z0-9]+", line)
]
while lines and not lines[-1].strip():
    lines.pop()
p.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
print(f"  seed.sql {len(lines)}줄")
PY
fi
rm -f "$SEED_LIST"

printf '=== 결정론 확인 (같은 DB에서 두 번 뽑아 동일한가) ===\n'
RAW2="$(mktemp)"
docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" --schema-only \
  -n feature -n provider_sync -n ops --exclude-table=public.alembic_version \
  -f /tmp/ktm-baseline-raw2.sql
docker cp "$CONTAINER":/tmp/ktm-baseline-raw2.sql "$RAW2" >/dev/null
docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-raw2.sql
dump_without_volatile_preamble() {
  grep -v '^-- Dumped' "$1" | sed -E '/^\\(un)?restrict [[:alnum:]]+$/d'
}
if diff -q <(dump_without_volatile_preamble "$RAW") <(dump_without_volatile_preamble "$RAW2") >/dev/null; then
  printf '  결정론 OK\n'
else
  printf '  오류: 같은 DB에서 두 dump가 다르다 — baseline이 재현 가능하지 않다\n' >&2
  diff <(dump_without_volatile_preamble "$RAW") <(dump_without_volatile_preamble "$RAW2") | head -5
  exit 1
fi
rm -f "$RAW2"

printf '\nbaseline: %s (%s줄, sha256 %s)\n' \
  "$BUILD_DIR/schema.sql" \
  "$(wc -l < "$BUILD_DIR/schema.sql")" \
  "$(sha256sum < "$BUILD_DIR/schema.sql" | cut -c1-16)"

# application handoff receipt query는 schema/seed dump와 같은 release artifact다.
# query·expected SHA·reference manifest를 따로 고치면 version label만 맞는 DB가
# 통과하거나(혹은 정상 source가 전부 거절되거나) 하는 split-brain이 생긴다. canonical
# query source를 staging directory에 함께 복사하고, source/fresh 양쪽의 ordered UTF-8/LF
# stream을 같은 경로로 실행한 뒤 한 manifest로 닫는다.
if [ "$MODE" = "verify" ]; then
  CANONICAL_BASELINE_DIR="$CANDIDATE_SEALED_ROOT/alembic/baseline"
else
  CANONICAL_BASELINE_DIR="$SCRIPT_DIR/../alembic/baseline"
fi
for contract in \
  application-catalog.sql application-seed.sql application-privileged-residue.sql \
  application-source-alembic-version.sql \
  application-destination-alembic-version.sql \
  application-runtime-invariants.sql; do
  [ -f "$CANONICAL_BASELINE_DIR/$contract" ] && [ ! -L "$CANONICAL_BASELINE_DIR/$contract" ] || \
    die "canonical handoff contract가 없다: $contract"
  cp "$CANONICAL_BASELINE_DIR/$contract" "$BUILD_DIR/$contract"
done

canonical_contract_gucs() {
  # pg_get_* / reg* text / query_to_xml 결과는 search_path만이 아니라 identifier,
  # locale, 날짜·간격·float·bytea 출력 GUC에도 영향을 받는다. source/fresh/production
  # handoff가 서로 다른 DSN/PGOPTIONS여도 같은 DB catalog는 같은 receipt가 되어야 한다.
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

contract_sha256() { # container db contract
  local container="$1"
  local database="$2"
  local contract="$3"
  local privilege_scope="${4:-schema-owner}"
  # handoff와 같은 schema owner/search_path에서 deparse한다. postgres default session으로
  # receipt를 만들면 `pg_get_functiondef()` 등이 정상 handoff session과 다른 SQL을 낼 수
  # 있어 source/fresh가 우연히 서로 같아도 production preflight와 달라질 수 있다.
  {
    printf '%s\n' 'BEGIN;'
    if [ "$privilege_scope" = "schema-owner" ]; then
      printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    elif [ "$privilege_scope" != "database-superuser" ]; then
      die "unknown contract privilege scope: $privilege_scope"
    fi
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    canonical_contract_gucs
    cat "$BUILD_DIR/$contract"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$container" psql -q -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$database" -tA \
    | sha256sum | awk '{print $1}'
}

source_catalog_sha="$(contract_sha256 "$CONTAINER" "$DB" application-catalog.sql)"
source_seed_sha="$(contract_sha256 "$CONTAINER" "$DB" application-seed.sql)"
source_privileged_residue_sha="$(contract_sha256 "$CONTAINER" "$DB" application-privileged-residue.sql database-superuser)"
source_alembic_version_sha="$(contract_sha256 "$CONTAINER" "$DB" application-source-alembic-version.sql)"
expected_source_alembic_version_sha="$(printf '%s\n' 'kor-travel-map.application-source-alembic-version.v1' | sha256sum | awk '{print $1}')"
expected_destination_alembic_version_sha="$(printf '%s\n' 'kor-travel-map.application-destination-alembic-version.v1' | sha256sum | awk '{print $1}')"
for digest in "$source_catalog_sha" "$source_seed_sha" "$source_privileged_residue_sha" \
  "$source_alembic_version_sha" "$expected_source_alembic_version_sha" \
  "$expected_destination_alembic_version_sha"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "contract receipt SHA-256을 얻지 못했다"
done
[ "$source_alembic_version_sha" = "$expected_source_alembic_version_sha" ] || \
  die "isolated 0236 source Alembic metadata facet이 exact source marker와 다르다"
if [ "$MODE" = "verify" ]; then
fresh_catalog_sha="$(contract_sha256 "$FRESH_300_CONTAINER" "$FRESH_300_DB" application-catalog.sql)"
fresh_seed_sha="$(contract_sha256 "$FRESH_300_CONTAINER" "$FRESH_300_DB" application-seed.sql)"
fresh_privileged_residue_sha="$(contract_sha256 "$FRESH_300_CONTAINER" "$FRESH_300_DB" application-privileged-residue.sql database-superuser)"
fresh_destination_alembic_version_sha="$(contract_sha256 "$FRESH_300_CONTAINER" "$FRESH_300_DB" application-destination-alembic-version.sql)"
for digest in "$fresh_catalog_sha" "$fresh_seed_sha" "$fresh_privileged_residue_sha" \
  "$fresh_destination_alembic_version_sha"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "fresh contract receipt SHA-256을 얻지 못했다"
done
[ "$source_catalog_sha" = "$fresh_catalog_sha" ] || \
  die "fresh 300 oracle catalog receipt가 exact 0236 source와 다르다"
[ "$source_seed_sha" = "$fresh_seed_sha" ] || \
  die "fresh 300 oracle immutable handoff seed receipt가 exact 0236 source와 다르다"
[ "$source_privileged_residue_sha" = "$fresh_privileged_residue_sha" ] || \
  die "fresh 300 oracle privileged residue receipt가 exact 0236 source와 다르다"
[ "$fresh_destination_alembic_version_sha" = "$expected_destination_alembic_version_sha" ] || \
  die "fresh 300 oracle destination Alembic metadata facet이 exact destination marker와 다르다"
# Oracle creator가 후보 image의 실제 migration 뒤 남긴 receipt result도, 여기서
# 재계산한 fresh DB result와 byte-exact여야 한다. receipt만 hand-edit하거나 raw `300`
# row를 넣어 만든 DB는 이 independent recheck를 통과할 수 없다.
python3 - "$FRESH_300_RECEIPT" "$fresh_catalog_sha" "$fresh_seed_sha" \
  "$fresh_privileged_residue_sha" "$fresh_destination_alembic_version_sha" <<'PY'
import json
import sys
from pathlib import Path

try:
    receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"fresh 300 oracle receipt cannot be re-read: {exc}") from exc
if (
    receipt.get("catalog_sha256") != sys.argv[2]
    or receipt.get("seed_sha256") != sys.argv[3]
    or receipt.get("privileged_residue_sha256") != sys.argv[4]
    or receipt.get("destination_alembic_version_sha256") != sys.argv[5]
    or receipt.get("runtime_invariant_violation_count") != 0
):
    raise SystemExit("fresh 300 oracle receipt result does not match the observed fresh database")
PY
fi
printf '%s\n' "$source_catalog_sha" > "$BUILD_DIR/application-catalog.sha256"
printf '%s\n' "$source_seed_sha" > "$BUILD_DIR/application-seed.sha256"
printf '%s\n' "$source_privileged_residue_sha" > "$BUILD_DIR/application-privileged-residue.sha256"
printf '%s\n' "$source_alembic_version_sha" > "$BUILD_DIR/application-source-alembic-version.sha256"
printf '%s\n' "$expected_destination_alembic_version_sha" > "$BUILD_DIR/application-destination-alembic-version.sha256"

python3 - "$BUILD_DIR" "$SOURCE_COMMIT" "$SOURCE_HEAD" "$SOURCE_IMAGE" "$SOURCE_IMAGE_ID" \
  "$SOURCE_PG_VERSION" "$SOURCE_POSTGIS_VERSION" "$source_catalog_sha" "$source_seed_sha" \
  "$source_privileged_residue_sha" "$source_alembic_version_sha" \
  "$expected_destination_alembic_version_sha" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
source = {
    "git_commit": sys.argv[2],
    "raw_alembic_revision": sys.argv[3],
    "container_image": sys.argv[4],
    "container_image_id": sys.argv[5],
    "postgres_server_version_num": sys.argv[6],
    "postgis_extension_version": sys.argv[7],
}
catalog_receipt = sys.argv[8]
seed_receipt = sys.argv[9]
privileged_residue_receipt = sys.argv[10]
source_alembic_version_receipt = sys.argv[11]
destination_alembic_version_receipt = sys.argv[12]

def digest(name: str) -> str:
    return hashlib.sha256((out / name).read_bytes()).hexdigest()

value = {
    "schema": "kor-travel-map.application-baseline-reference.v1",
    "source": source,
    "artifacts": {
        "schema_sql_sha256": digest("schema.sql"),
        "seed_sql_sha256": digest("seed.sql"),
        "catalog_contract_sql_sha256": digest("application-catalog.sql"),
        "catalog_contract_sha256": catalog_receipt,
        "catalog_contract_receipt_sha256": digest("application-catalog.sha256"),
        "seed_contract_sql_sha256": digest("application-seed.sql"),
        "seed_contract_sha256": seed_receipt,
        "seed_contract_receipt_sha256": digest("application-seed.sha256"),
        "privileged_residue_contract_sql_sha256": digest("application-privileged-residue.sql"),
        "privileged_residue_contract_sha256": privileged_residue_receipt,
        "privileged_residue_contract_receipt_sha256": digest("application-privileged-residue.sha256"),
        "source_alembic_version_contract_sql_sha256": digest("application-source-alembic-version.sql"),
        "source_alembic_version_contract_sha256": source_alembic_version_receipt,
        "source_alembic_version_contract_receipt_sha256": digest("application-source-alembic-version.sha256"),
        "destination_alembic_version_contract_sql_sha256": digest("application-destination-alembic-version.sql"),
        "destination_alembic_version_contract_sha256": destination_alembic_version_receipt,
        "destination_alembic_version_contract_receipt_sha256": digest("application-destination-alembic-version.sha256"),
        "runtime_invariants_sql_sha256": digest("application-runtime-invariants.sql"),
    },
    "fresh_seed_relations": [
        "feature.curated_source_rules",
        "feature.curated_sources",
        "feature.curated_themes",
        "ops.feature_override_field_paths",
        "provider_sync.provider_dataset_operation_scopes",
        "provider_sync.provider_dataset_operations",
        "provider_sync.provider_datasets",
    ],
    "static_seed_relations": ["ops.feature_override_field_paths"],
}
(out / "application-reference.json").write_text(
    json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(out / "application-reference.sha256").write_text(
    hashlib.sha256((out / "application-reference.json").read_bytes()).hexdigest() + "\n",
    encoding="ascii",
)
PY

python3 - "$BUILD_DIR" "$SOURCE_COMMIT" "$SOURCE_HEAD" "$SOURCE_IMAGE" "$SOURCE_IMAGE_ID" \
  "$SOURCE_PG_VERSION" "$SOURCE_POSTGIS_VERSION" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
value = json.loads((out / "application-reference.json").read_text(encoding="utf-8"))
reference_digest = (out / "application-reference.sha256").read_bytes()
reference_sha256 = hashlib.sha256((out / "application-reference.json").read_bytes()).hexdigest()
if reference_digest != f"{reference_sha256}\n".encode("ascii"):
    raise SystemExit("generated reference manifest digest sidecar drifted")
source = value.get("source")
if value.get("schema") != "kor-travel-map.application-baseline-reference.v1" or source != {
    "git_commit": sys.argv[2],
    "raw_alembic_revision": sys.argv[3],
    "container_image": sys.argv[4],
    "container_image_id": sys.argv[5],
    "postgres_server_version_num": sys.argv[6],
    "postgis_extension_version": sys.argv[7],
}:
    raise SystemExit("generated reference manifest provenance is invalid")
if value.get("fresh_seed_relations") != [
    "feature.curated_source_rules", "feature.curated_sources", "feature.curated_themes",
    "ops.feature_override_field_paths", "provider_sync.provider_dataset_operation_scopes",
    "provider_sync.provider_dataset_operations", "provider_sync.provider_datasets",
] or value.get("static_seed_relations") != ["ops.feature_override_field_paths"]:
    raise SystemExit("generated reference manifest seed inventories are invalid")
files = {
    "schema.sql": "schema_sql_sha256",
    "seed.sql": "seed_sql_sha256",
    "application-catalog.sql": "catalog_contract_sql_sha256",
    "application-catalog.sha256": "catalog_contract_receipt_sha256",
    "application-seed.sql": "seed_contract_sql_sha256",
    "application-seed.sha256": "seed_contract_receipt_sha256",
    "application-privileged-residue.sql": "privileged_residue_contract_sql_sha256",
    "application-privileged-residue.sha256": "privileged_residue_contract_receipt_sha256",
    "application-source-alembic-version.sql": "source_alembic_version_contract_sql_sha256",
    "application-source-alembic-version.sha256": "source_alembic_version_contract_receipt_sha256",
    "application-destination-alembic-version.sql": "destination_alembic_version_contract_sql_sha256",
    "application-destination-alembic-version.sha256": "destination_alembic_version_contract_receipt_sha256",
    "application-runtime-invariants.sql": "runtime_invariants_sql_sha256",
}
for name, key in files.items():
    actual = hashlib.sha256((out / name).read_bytes()).hexdigest()
    if value["artifacts"].get(key) != actual:
        raise SystemExit(f"generated reference artifact digest drifted: {name}")
for name, key in (("application-catalog.sha256", "catalog_contract_sha256"),
                  ("application-seed.sha256", "seed_contract_sha256"),
                  ("application-privileged-residue.sha256", "privileged_residue_contract_sha256"),
                  ("application-source-alembic-version.sha256", "source_alembic_version_contract_sha256"),
                  ("application-destination-alembic-version.sha256", "destination_alembic_version_contract_sha256")):
    if (out / name).read_text(encoding="ascii").strip() != value["artifacts"].get(key):
        raise SystemExit(f"generated contract receipt/manifest drifted: {name}")
PY
generated_reference_manifest_sha256="$(sha256sum "$BUILD_DIR/application-reference.json" | awk '{print $1}')"
materializer_script_sha256="$MATERIALIZER_SCRIPT_SHA256"

if [ "$MODE" = "materialize" ]; then
  # Existing baseline directory를 부분 overwrite하지 않는다. source-only output은
  # final candidate evidence가 아니며, 다음 verify 단계가 exact candidate/fresh oracle
  # 과 다시 묶기 전에는 deploy input으로 쓸 수 없다.
  mv "$BUILD_DIR" "$OUT_DIR"
  BUILD_DIR=""
  receipt_tmp="$(mktemp "$(dirname -- "$RECEIPT_PATH")/.ktm300-materialization-receipt.XXXXXX")"
  python3 - "$receipt_tmp" "$OUT_DIR/application-reference.json" "$source_container_id" \
    "$DB" "$source_database_oid" "$source_system_identifier" "$source_catalog_sha" \
    "$source_seed_sha" "$source_privileged_residue_sha" "$source_certificate_sha256" \
    "$materializer_script_sha256" "$source_alembic_version_sha" \
    "$expected_destination_alembic_version_sha" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
manifest = Path(sys.argv[2])
value = {
    "schema": "kor-travel-map.application-baseline-materialization-receipt.v3",
    "reference_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    "source_container_id": sys.argv[3],
    "source_database": sys.argv[4],
    "source_database_oid": int(sys.argv[5]),
    "source_postgres_system_identifier": sys.argv[6],
    "source_catalog_sha256": sys.argv[7],
    "source_seed_sha256": sys.argv[8],
    "source_privileged_residue_sha256": sys.argv[9],
    "source_certificate_sha256": sys.argv[10],
    "materializer_script_sha256": sys.argv[11],
    "source_alembic_version_sha256": sys.argv[12],
    "destination_alembic_version_sha256": sys.argv[13],
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
  chmod 600 "$receipt_tmp"
  mv "$receipt_tmp" "$RECEIPT_PATH"
  printf 'application baseline materialized (not deploy evidence): %s\n' "$OUT_DIR"
  printf 'materialization receipt (external): %s\n' "$RECEIPT_PATH"
  exit 0
fi

[ "$generated_reference_manifest_sha256" = "$reference_manifest_sha256" ] || \
  die "fresh candidate가 증명한 manifest와 새 generated baseline manifest가 다르다"

# 1단계 source-only materialization은 현재 artifact가 어디에서 왔는지 남긴 외부
# receipt다. verify는 같은 candidate artifact를 source에서 다시 생성해 비교하므로,
# receipt를 바꿔치기하거나 다른 source DB로 만든 output을 final proof에 섞지 못한다.
python3 - "$MATERIALIZATION_RECEIPT" "$generated_reference_manifest_sha256" \
  "$source_container_id" "$DB" "$source_database_oid" "$source_system_identifier" \
  "$source_catalog_sha" "$source_seed_sha" "$source_privileged_residue_sha" \
  "$source_certificate_sha256" "$materializer_script_sha256" \
  "$source_alembic_version_sha" "$expected_destination_alembic_version_sha" <<'PY'
import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"materialization receipt cannot be parsed: {exc}") from exc
expected = {
    "schema": "kor-travel-map.application-baseline-materialization-receipt.v3",
    "reference_manifest_sha256": sys.argv[2],
    "source_container_id": sys.argv[3],
    "source_database": sys.argv[4],
    "source_database_oid": int(sys.argv[5]),
    "source_postgres_system_identifier": sys.argv[6],
    "source_catalog_sha256": sys.argv[7],
    "source_seed_sha256": sys.argv[8],
    "source_privileged_residue_sha256": sys.argv[9],
    "source_certificate_sha256": sys.argv[10],
    "materializer_script_sha256": sys.argv[11],
    "source_alembic_version_sha256": sys.argv[12],
    "destination_alembic_version_sha256": sys.argv[13],
}
if not isinstance(value, dict) or value != expected:
    raise SystemExit("materialization receipt does not bind this source/artifact generator")
PY

# verify는 final candidate image가 포함한 artifact directory와 source-only output의
# 전 파일 byte 동등성을 본다. manifest만 같다는 비교는 sidecar 누락을 숨길 수 있다.
for artifact in \
  schema.sql seed.sql application-catalog.sql application-catalog.sha256 \
  application-reference.json application-reference.sha256 \
  application-runtime-invariants.sql application-seed.sql application-seed.sha256 \
  application-privileged-residue.sql application-privileged-residue.sha256 \
  application-source-alembic-version.sql application-source-alembic-version.sha256 \
  application-destination-alembic-version.sql application-destination-alembic-version.sha256; do
  candidate_artifact="$CANONICAL_BASELINE_DIR/$artifact"
  [[ -f "$candidate_artifact" && ! -L "$candidate_artifact" ]] || \
    die "candidate baseline artifact가 없다: $artifact"
  cmp -s "$BUILD_DIR/$artifact" "$candidate_artifact" || \
    die "source에서 다시 생성한 artifact가 current candidate와 다르다: $artifact"
done

# Existing baseline directory를 부분 overwrite하지 않는다. verified staging directory를
# 한 번 rename해 publish하므로 실패 중간물이 review/commit 대상이 될 수 없다.
mv "$BUILD_DIR" "$OUT_DIR"
BUILD_DIR=""

receipt_tmp="$(mktemp "$(dirname -- "$RECEIPT_PATH")/.ktm300-baseline-receipt.XXXXXX")"
fresh_oracle_receipt_sha256="$(sha256sum "$FRESH_300_RECEIPT" | awk '{print $1}')"
materialization_receipt_sha256="$(sha256sum "$MATERIALIZATION_RECEIPT" | awk '{print $1}')"
python3 - "$receipt_tmp" "$OUT_DIR/application-reference.json" "$source_database_oid" \
  "$fresh_database_oid" "$fresh_catalog_sha" "$fresh_seed_sha" \
  "$fresh_privileged_residue_sha" "$source_container_id" "$source_system_identifier" \
  "$fresh_container_id" "$fresh_system_identifier" "$fresh_candidate_image" \
  "$candidate_image_id_actual" "$candidate_commit_expected" "$CANDIDATE_PROVENANCE_JSON" \
  "$fresh_oracle_receipt_sha256" "$materialization_receipt_sha256" \
  "$source_certificate_sha256" "$handoff_rehearsal_receipt_sha256" \
  "$source_alembic_version_sha" "$fresh_destination_alembic_version_sha" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
manifest = Path(sys.argv[2])
candidate = json.loads(sys.argv[15])
candidate_keys = {
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_manifest_sha256",
    "candidate_app_manifest_sha256", "candidate_runtime_manifest_sha256",
    "candidate_entrypoint_manifest_sha256", "candidate_dependency_sbom_sha256",
    "candidate_300_migration_sha256", "candidate_base_image_reference",
    "candidate_base_image_id", "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_proof_tools_manifest_sha256",
    "candidate_build_receipt_sha256",
}
if not isinstance(candidate, dict) or set(candidate) != candidate_keys:
    raise SystemExit("sealed candidate attestation cannot be propagated to build receipt")
value = {
    "schema": "kor-travel-map.application-baseline-build-receipt.v6",
    "reference_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    "source_database_oid": int(sys.argv[3]),
    "fresh_300_database_oid": int(sys.argv[4]),
    "source_catalog_sha256": sys.argv[5],
    "fresh_300_catalog_sha256": sys.argv[5],
    "source_seed_sha256": sys.argv[6],
    "fresh_300_seed_sha256": sys.argv[6],
    "source_privileged_residue_sha256": sys.argv[7],
    "fresh_300_privileged_residue_sha256": sys.argv[7],
    "source_alembic_version_sha256": sys.argv[20],
    "fresh_300_destination_alembic_version_sha256": sys.argv[21],
    "source_container_id": sys.argv[8],
    "source_postgres_system_identifier": sys.argv[9],
    "fresh_300_container_id": sys.argv[10],
    "fresh_300_postgres_system_identifier": sys.argv[11],
    "fresh_300_candidate_image": sys.argv[12],
    "fresh_300_candidate_image_id": sys.argv[13],
    "fresh_300_candidate_commit": sys.argv[14],
    "fresh_300_candidate_git_tree": candidate["candidate_git_tree"],
    "fresh_300_candidate_dockerfile_sha256": candidate["candidate_dockerfile_sha256"],
    "fresh_300_candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
    "fresh_300_candidate_app_manifest_sha256": candidate["candidate_app_manifest_sha256"],
    "fresh_300_candidate_runtime_manifest_sha256": candidate["candidate_runtime_manifest_sha256"],
    "fresh_300_candidate_entrypoint_manifest_sha256": candidate["candidate_entrypoint_manifest_sha256"],
    "fresh_300_candidate_dependency_sbom_sha256": candidate["candidate_dependency_sbom_sha256"],
    "fresh_300_candidate_300_migration_sha256": candidate["candidate_300_migration_sha256"],
    "fresh_300_candidate_base_image_reference": candidate["candidate_base_image_reference"],
    "fresh_300_candidate_base_image_id": candidate["candidate_base_image_id"],
    "fresh_300_candidate_base_rootfs_layers_sha256": candidate["candidate_base_rootfs_layers_sha256"],
    "fresh_300_candidate_full_rootfs_layers_sha256": candidate["candidate_full_rootfs_layers_sha256"],
    "fresh_300_candidate_proof_tools_manifest_sha256": candidate["candidate_proof_tools_manifest_sha256"],
    "fresh_300_candidate_build_receipt_sha256": candidate["candidate_build_receipt_sha256"],
    "fresh_300_candidate_attestation_sha256": hashlib.sha256(sys.argv[15].encode("utf-8")).hexdigest(),
    "fresh_300_oracle_receipt_sha256": sys.argv[16],
    "materialization_receipt_sha256": sys.argv[17],
    "source_certificate_sha256": sys.argv[18],
    "handoff_rehearsal_receipt_sha256": sys.argv[19],
}
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_tmp"
mv "$receipt_tmp" "$RECEIPT_PATH"

printf 'application reference published: %s\n' "$OUT_DIR"
printf 'build receipt (external): %s\n' "$RECEIPT_PATH"
