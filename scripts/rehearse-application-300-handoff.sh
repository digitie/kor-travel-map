#!/usr/bin/env bash
# isolated raw `0236` source에서 candidate one-shot handoff를 실제로 리허설한다.
#
# source↔fresh catalog parity만으로는 `env.py` controlled stamp branch, root-only
# capability, Manager-shaped fence receipt, same-transaction rollback까지 실행됐다는
# 증거가 되지 않는다. 이 도구는 source oracle DB를 절대 고치지 않고, 그 DB에서 만든
# 두 disposable clone에 exact candidate image를 root one-shot으로 실행한다.
#
# - positive clone: valid Manager-shaped receipt → raw `300` + contract receipts
# - negative clone: privileged pre-receipt mismatch → raw `0236` 보존
#
# production/n150 Compose·DB를 입력으로 받지 않는다. source oracle의 isolated label과
# certificate가 없으면 Docker/DB mutation 전에 중단한다.
set -euo pipefail

die() { printf 'rehearse-application-300-handoff: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
SOURCE_CONTAINER=""
SOURCE_DATABASE=""
SOURCE_CERTIFICATE=""
CANDIDATE_IMAGE=""
CANDIDATE_COMMIT=""
CANDIDATE_BUILD_RECEIPT=""
PAIRED_BUILD_RECEIPT=""
RECEIPT=""
FENCE_VOLUME=""
POSITIVE_DATABASE=""
NEGATIVE_DATABASE=""
RECEIPT_PARENT=""
TMPDIR_PATH=""
SOURCE_PASSWORD=""
OBSERVED_CATALOG_SHA256=""
OBSERVED_SEED_SHA256=""
OBSERVED_PRIVILEGED_RESIDUE_SHA256=""
FENCE_RECEIPT_SHA256=""
FENCE_TRANSACTION_ID=""
FENCE_IDENTITY_JSON=""
OBSERVED_FENCE_FILE_METADATA=""

while [ $# -gt 0 ]; do
  case "$1" in
    --source-container) SOURCE_CONTAINER="${2:?--source-container needs a value}"; shift 2 ;;
    --source-database) SOURCE_DATABASE="${2:?--source-database needs a value}"; shift 2 ;;
    --source-certificate) SOURCE_CERTIFICATE="${2:?--source-certificate needs a value}"; shift 2 ;;
    --candidate-image) CANDIDATE_IMAGE="${2:?--candidate-image needs a value}"; shift 2 ;;
    --candidate-commit) CANDIDATE_COMMIT="${2:?--candidate-commit needs a value}"; shift 2 ;;
    --candidate-build-receipt) CANDIDATE_BUILD_RECEIPT="${2:?--candidate-build-receipt needs a value}"; shift 2 ;;
    --paired-build-receipt) PAIRED_BUILD_RECEIPT="${2:?--paired-build-receipt needs a value}"; shift 2 ;;
    --receipt) RECEIPT="${2:?--receipt needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) die "위치 인자는 허용하지 않는다: $1" ;;
  esac
done

for required_name in \
  SOURCE_CONTAINER SOURCE_DATABASE SOURCE_CERTIFICATE CANDIDATE_IMAGE \
  CANDIDATE_COMMIT CANDIDATE_BUILD_RECEIPT PAIRED_BUILD_RECEIPT RECEIPT; do
  [ -n "${!required_name}" ] || die "--$(tr '[:upper:]_' '[:lower:]-' <<<"$required_name")가 필요하다"
done
[[ "$SOURCE_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "source container 이름이 잘못됐다"
[[ "$SOURCE_DATABASE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "source database 이름이 잘못됐다"
[[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "candidate commit은 full SHA-1이어야 한다"
[[ "$SOURCE_CERTIFICATE" == /* && -f "$SOURCE_CERTIFICATE" && ! -L "$SOURCE_CERTIFICATE" ]] || \
  die "source certificate는 absolute regular file이어야 한다"
[[ "$CANDIDATE_BUILD_RECEIPT" == /* && -f "$CANDIDATE_BUILD_RECEIPT" && ! -L "$CANDIDATE_BUILD_RECEIPT" ]] || \
  die "candidate build receipt는 absolute regular file이어야 한다"
[[ "$PAIRED_BUILD_RECEIPT" == /* && -f "$PAIRED_BUILD_RECEIPT" && ! -L "$PAIRED_BUILD_RECEIPT" ]] || \
  die "paired build receipt는 absolute regular file이어야 한다"
[[ "$RECEIPT" == /* ]] || die "rehearsal receipt는 absolute path여야 한다"

canonicalize_receipt_target() {
  local raw_target="$1"
  local raw_parent raw_name canonical_parent canonical_target
  raw_parent="$(dirname -- "$raw_target")"
  raw_name="$(basename -- "$raw_target")"
  [ "$raw_name" != "." ] && [ "$raw_name" != ".." ] || die "rehearsal receipt file name이 잘못됐다"
  [[ "$raw_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || \
    die "rehearsal receipt file name에는 안전한 ASCII 문자만 허용한다"
  [ -d "$raw_parent" ] || die "rehearsal receipt parent directory가 없다"
  canonical_parent="$(realpath -e -- "$raw_parent")"
  [ "$canonical_parent" = "$raw_parent" ] || \
    die "rehearsal receipt parent는 symlink 없는 physical directory여야 한다"
  python3 - "$canonical_parent" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("rehearsal receipt parent must be a regular directory")
if metadata.st_uid != int(sys.argv[2]) or stat.S_IMODE(metadata.st_mode) & 0o022:
    raise SystemExit("rehearsal receipt parent must be private to the invoking operator")
PY
  canonical_target="$(realpath -m -- "$canonical_parent/$raw_name")"
  case "$canonical_target" in
    "$REPOSITORY_ROOT"|"$REPOSITORY_ROOT"/*)
      die "rehearsal receipt는 repository 밖 canonical path여야 한다"
      ;;
  esac
  [[ ! -e "$canonical_target" && ! -L "$canonical_target" ]] || \
    die "rehearsal receipt target이 이미 존재한다"
  RECEIPT="$canonical_target"
  RECEIPT_PARENT="$canonical_parent"
}

canonicalize_receipt_target "$RECEIPT"

cleanup() {
  status=$?
  if [ -n "$POSITIVE_DATABASE" ]; then
    docker exec "$SOURCE_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
      -c "DROP DATABASE IF EXISTS \"$POSITIVE_DATABASE\" WITH (FORCE)" >/dev/null 2>&1 || true
  fi
  if [ -n "$NEGATIVE_DATABASE" ]; then
    docker exec "$SOURCE_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
      -c "DROP DATABASE IF EXISTS \"$NEGATIVE_DATABASE\" WITH (FORCE)" >/dev/null 2>&1 || true
  fi
  [ -z "$FENCE_VOLUME" ] || docker volume rm "$FENCE_VOLUME" >/dev/null 2>&1 || true
  [ -z "$TMPDIR_PATH" ] || rm -rf -- "$TMPDIR_PATH"
  unset SOURCE_PASSWORD
  exit "$status"
}
trap cleanup EXIT

for receipt_path in "$SOURCE_CERTIFICATE" "$CANDIDATE_BUILD_RECEIPT" "$PAIRED_BUILD_RECEIPT"; do
  python3 - "$receipt_path" "$(id -u)" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("external rehearsal input must be a regular non-symlink file")
if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != int(sys.argv[2]):
    raise SystemExit("external rehearsal input must be mode 0600 and owned by the invoking operator")
PY
done

docker container inspect "$SOURCE_CONTAINER" >/dev/null 2>&1 || die "source oracle container가 없다"
[ "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.isolated"}}' "$SOURCE_CONTAINER")" = "true" ] || \
  die "source container는 isolated oracle label이 필요하다"
[ "$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-0236-oracle"}}' "$SOURCE_CONTAINER")" = "true" ] || \
  die "source container는 source-0236 oracle label이 필요하다"

source_container_id="$(docker inspect -f '{{.Id}}' "$SOURCE_CONTAINER")"
source_database_oid="$(docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$SOURCE_DATABASE" -tA \
  -c 'SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()')"
source_system_identifier="$(docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$SOURCE_DATABASE" -tA \
  -c 'SELECT system_identifier::text FROM pg_catalog.pg_control_system()')"
source_postgres_server_version_num="$(docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$SOURCE_DATABASE" -tA \
  -c 'SHOW server_version_num')"
source_postgis_extension_version="$(docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$SOURCE_DATABASE" -tA \
  -c "SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'postgis'")"
source_container_image_id="$(docker inspect -f '{{.Image}}' "$SOURCE_CONTAINER")"
source_image_id="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-id"}}' "$SOURCE_CONTAINER")"
source_image_app_manifest_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-app-manifest-sha256"}}' "$SOURCE_CONTAINER")"
source_image_runtime_manifest_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-runtime-manifest-sha256"}}' "$SOURCE_CONTAINER")"
source_builder_base_image_id="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-builder-base-image-id"}}' "$SOURCE_CONTAINER")"
source_builder_base_image_reference="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-builder-base-image-reference"}}' "$SOURCE_CONTAINER")"
source_build_dockerfile_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-build-dockerfile-sha256"}}' "$SOURCE_CONTAINER")"
source_image_dependency_sbom_sha256="$(docker inspect -f '{{index .Config.Labels "io.kor-travel-map.application-baseline.source-image-dependency-sbom-sha256"}}' "$SOURCE_CONTAINER")"
source_creator_script_sha256="$(sha256sum "$SCRIPT_DIR/create-application-0236-source-oracle.sh" | awk '{print $1}')"
python3 - "$SOURCE_CERTIFICATE" "$source_container_id" "$SOURCE_DATABASE" \
  "$source_database_oid" "$source_system_identifier" "$source_image_id" \
  "$source_container_image_id" "$source_creator_script_sha256" \
  "$source_postgres_server_version_num" "$source_postgis_extension_version" \
  "$source_image_app_manifest_sha256" "$source_image_runtime_manifest_sha256" \
  "$source_builder_base_image_id" "$source_builder_base_image_reference" \
  "$source_build_dockerfile_sha256" "$source_image_dependency_sbom_sha256" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"source certificate cannot be parsed: {exc}") from exc
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
    "source_commit": "01d65b2ad4ee265a3ef6b01448f6abf573a906a8",
    "source_head": "0236_tvn41s_compaction_drained",
    "source_migration_tree": "cb52c39e3d0f37bfe229532d94c2c91ea289b725",
    "retired_manifest_sha256": "3a3e96da12e8c8517fcac094749451307bb2b43e9bac249f2abe8864601d136e",
    "source_image_id": sys.argv[6],
    "postgis_image_id": sys.argv[7],
    "creator_script_sha256": sys.argv[8],
    "source_bootstrap_sha256": "b76dfc0317622c659be6b690c057c47c968ee1ea9dafbb873ae97c8dc34eea5c",
    "migration_choreography": "legacy-bootstrap>0225>m01-bootstrap>0232>0233>m05-pre-bootstrap>0235>0236>m05-repair-bootstrap",
    "raw_alembic_revision": "0236_tvn41s_compaction_drained",
    "postgres_server_version_num": sys.argv[9],
    "postgis_extension_version": sys.argv[10],
    "source_git_tree": "84cd91c38700bdad2e817605d4cb3bc480affc2b",
    "source_dockerfile_sha256": "882c042eb4a4b5f8bb66acc07301d7312a61e4377431b0627f6a5c906dda6975",
    "source_image_app_manifest_sha256": sys.argv[11],
    "source_image_runtime_manifest_sha256": sys.argv[12],
    "source_builder_base_image_id": sys.argv[13],
    "source_builder_base_image_reference": sys.argv[14],
    "source_build_dockerfile_sha256": sys.argv[15],
    "source_image_dependency_sbom_sha256": sys.argv[16],
    "source_database_provisioning": "explicit-create-database-from-template1-after-official-entrypoint-complete",
    "source_database_template": "template1",
    "source_initial_virgin_inventory": initial_virgin_inventory,
    "source_initial_virgin_inventory_sha256": initial_virgin_inventory_sha256,
}
if not isinstance(value, dict) or set(value) != set(expected):
    raise SystemExit("source certificate has an unexpected v8 field set")
if {key: value.get(key) for key in expected} != expected:
    raise SystemExit("source certificate does not bind the observed isolated source")
for key in (
    "source_image_id", "postgis_image_id", "source_builder_base_image_id",
):
    if not isinstance(value[key], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value[key]):
        raise SystemExit(f"source certificate image identity is invalid: {key}")
for key in (
    "creator_script_sha256", "source_bootstrap_sha256", "source_dockerfile_sha256",
    "source_image_app_manifest_sha256", "source_image_runtime_manifest_sha256",
    "source_build_dockerfile_sha256", "source_image_dependency_sbom_sha256",
    "source_initial_virgin_inventory_sha256",
):
    if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
        raise SystemExit(f"source certificate digest is invalid: {key}")
if not re.fullmatch(r"python@sha256:[0-9a-f]{64}", value["source_builder_base_image_reference"]):
    raise SystemExit("source certificate builder base reference is invalid")
PY

# This verifies the current rehearsal executable and all other release proof
# tools against the candidate's sealed archive before any clone is created.
candidate_provenance_json="$(bash "$SCRIPT_DIR/build-application-300-candidate.sh" \
  --verify --candidate-commit "$CANDIDATE_COMMIT" --image "$CANDIDATE_IMAGE" \
  --git-root "$REPOSITORY_ROOT" --receipt "$CANDIDATE_BUILD_RECEIPT")"
mapfile -t candidate_identity < <(python3 - "$candidate_provenance_json" <<'PY'
from __future__ import annotations

import json
import re
import sys

value = json.loads(sys.argv[1])
for key, pattern in (
    ("candidate_image", r"\S+"),
    ("candidate_image_id", r"sha256:[0-9a-f]{64}"),
    ("candidate_commit", r"[0-9a-f]{40}"),
    ("candidate_manifest_sha256", r"[0-9a-f]{64}"),
    ("candidate_proof_tools_manifest_sha256", r"[0-9a-f]{64}"),
):
    item = value.get(key)
    if not isinstance(item, str) or not re.fullmatch(pattern, item):
        raise SystemExit(f"candidate rehearsal provenance field is invalid: {key}")
    print(item)
PY
)
[ "${#candidate_identity[@]}" -eq 5 ] || die "candidate rehearsal provenance identity를 읽지 못했다"
candidate_image="${candidate_identity[0]}"
candidate_image_id="${candidate_identity[1]}"
candidate_commit="${candidate_identity[2]}"
reference_manifest_sha256="${candidate_identity[3]}"
candidate_proof_tools_manifest_sha256="${candidate_identity[4]}"
[ "$candidate_image" = "$CANDIDATE_IMAGE" ] || die "candidate image attestation이 입력 image와 다르다"

paired_dagster_image="$(python3 - "$PAIRED_BUILD_RECEIPT" <<'PY'
import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    image = value["dagster_candidate"]["candidate_image"]
except (KeyError, OSError, TypeError, ValueError) as exc:
    raise SystemExit(f"paired build receipt cannot identify Dagster image: {exc}") from exc
if not isinstance(image, str) or not image or any(character.isspace() for character in image):
    raise SystemExit("paired build receipt Dagster image name is invalid")
print(image)
PY
)"
paired_provenance_json="$(bash "$SCRIPT_DIR/build-application-300-paired-candidate.sh" \
  --verify --candidate-commit "$CANDIDATE_COMMIT" \
  --api-image "$CANDIDATE_IMAGE" --dagster-image "$paired_dagster_image" \
  --git-root "$REPOSITORY_ROOT" --api-receipt "$CANDIDATE_BUILD_RECEIPT" \
  --receipt "$PAIRED_BUILD_RECEIPT")"
candidate_build_receipt_sha256="$(sha256sum "$CANDIDATE_BUILD_RECEIPT" | awk '{print $1}')"
paired_build_receipt_sha256="$(sha256sum "$PAIRED_BUILD_RECEIPT" | awk '{print $1}')"
mapfile -t paired_identity < <(python3 - "$paired_provenance_json" \
  "$candidate_provenance_json" "$candidate_build_receipt_sha256" <<'PY'
from __future__ import annotations

import json
import re
import sys

paired = json.loads(sys.argv[1])
api_candidate = json.loads(sys.argv[2])
expected_top_level = {
    "schema", "candidate_commit", "candidate_git_tree", "paired_builder_script_sha256",
    "api_candidate", "api_candidate_build_receipt_sha256", "dagster_candidate",
    "launch_contract",
}
if not isinstance(paired, dict) or set(paired) != expected_top_level:
    raise SystemExit("paired build receipt has an unexpected field set")
if paired["schema"] != "kor-travel-map.application-300-paired-candidate-build.v1":
    raise SystemExit("paired build receipt schema is invalid")
if paired["api_candidate"] != api_candidate:
    raise SystemExit("paired build receipt does not contain the rehearsed API candidate")
if paired["api_candidate_build_receipt_sha256"] != sys.argv[3]:
    raise SystemExit("paired build receipt does not bind the API receipt bytes")
if (
    paired["candidate_commit"] != api_candidate.get("candidate_commit")
    or paired["candidate_git_tree"] != api_candidate.get("candidate_git_tree")
):
    raise SystemExit("paired build receipt API commit/tree continuity is invalid")
dagster = paired["dagster_candidate"]
expected_dagster = {
    "candidate_image", "candidate_image_id", "candidate_commit", "candidate_git_tree",
    "candidate_dockerfile_sha256", "candidate_base_image_reference",
    "candidate_base_image_id", "candidate_base_rootfs_layers_sha256",
    "candidate_full_rootfs_layers_sha256", "candidate_app_manifest_sha256",
    "candidate_runtime_manifest_sha256", "candidate_proof_manifest_sha256",
    "candidate_dependency_sbom_sha256", "candidate_config_sha256",
    "candidate_dagster_yaml_sha256",
    "application_contract", "application_contract_sha256",
}
if not isinstance(dagster, dict) or set(dagster) != expected_dagster:
    raise SystemExit("paired build receipt Dagster candidate field set is invalid")
if (
    dagster["candidate_commit"] != paired["candidate_commit"]
    or dagster["candidate_git_tree"] != paired["candidate_git_tree"]
    or not isinstance(dagster["candidate_image_id"], str)
    or not re.fullmatch(r"sha256:[0-9a-f]{64}", dagster["candidate_image_id"])
    or not isinstance(dagster["candidate_dagster_yaml_sha256"], str)
    or not re.fullmatch(r"[0-9a-f]{64}", dagster["candidate_dagster_yaml_sha256"])
):
    raise SystemExit("paired build receipt Dagster identity is invalid")
launch = paired["launch_contract"]
expected_launch = {
    "schema", "requires_same_image_id", "application_final_permit_consumers",
    "webserver_image_id", "daemon_image_id", "storage_migration_image_id",
    "webserver_argv_policy", "image_default_webserver_argv", "daemon_argv",
    "storage_migration", "metadata_database_identity_permit",
}
if not isinstance(launch, dict) or set(launch) != expected_launch:
    raise SystemExit("paired build receipt launch field set is invalid")
if (
    launch["schema"] != "kor-travel-map.application-300-dagster-launch.v1"
    or launch["requires_same_image_id"] is not True
    or launch["application_final_permit_consumers"] != ["webserver", "daemon"]
    or any(
        launch[key] != dagster["candidate_image_id"]
        for key in ("webserver_image_id", "daemon_image_id", "storage_migration_image_id")
    )
    or launch["storage_migration"] != {
        "scope": "dagster-metadata-only-excluded-from-application-final-permit",
        "argv": ["/usr/local/bin/ktm-dagster-storage", "migrate"],
    }
    or launch["webserver_argv_policy"] != {
        "fixed_prefix": [
            "/usr/local/bin/dagster-webserver", "-m",
            "kortravelmap.dagster.definitions", "-h", "0.0.0.0", "-p",
        ],
        "port_decimal_minimum": 1,
        "port_decimal_maximum": 65535,
    }
    or launch["image_default_webserver_argv"] != [
        "/usr/local/bin/dagster-webserver", "-m", "kortravelmap.dagster.definitions",
        "-h", "0.0.0.0", "-p", "12702",
    ]
    or launch["daemon_argv"] != [
        "/usr/local/bin/dagster-daemon", "run", "-m", "kortravelmap.dagster.definitions",
    ]
    or launch["metadata_database_identity_permit"] != {
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
        ],
        "forbidden_application_identity_fields": [
            "system_identifier", "name", "oid", "owner",
        ],
        "forbidden_application_raw_revision": "300",
    }
):
    raise SystemExit("paired build receipt launch identity is invalid")
print(dagster["candidate_image_id"])
print(paired["candidate_git_tree"])
PY
)
[ "${#paired_identity[@]}" -eq 2 ] || die "paired candidate identity를 읽지 못했다"
paired_dagster_image_id="${paired_identity[0]}"
paired_candidate_git_tree="${paired_identity[1]}"

candidate_postgres_image_id="$(docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations
import json
from pathlib import Path
print(json.loads(Path("/app/alembic/baseline/application-reference.json").read_text(encoding="utf-8"))["source"]["container_image_id"])
')"
[[ "$candidate_postgres_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "candidate baseline의 PostGIS image ID가 잘못됐다"
[ "$candidate_commit" = "$CANDIDATE_COMMIT" ] || die "candidate commit attestation이 입력 commit과 다르다"

candidate_contract_receipt() {
  local name="$1"
  docker run --pull=never --rm --entrypoint cat "$candidate_image_id" \
    "/app/alembic/baseline/$name" | tr -d '\n'
}

expected_source_catalog_sha256="$(candidate_contract_receipt application-source-catalog.sha256)"
expected_destination_catalog_sha256="$(candidate_contract_receipt application-destination-catalog.sha256)"
expected_seed_sha256="$(candidate_contract_receipt application-seed.sha256)"
expected_privileged_residue_sha256="$(candidate_contract_receipt application-privileged-residue.sha256)"
expected_source_alembic_version_sha256="$(candidate_contract_receipt application-source-alembic-version.sha256)"
expected_destination_alembic_version_sha256="$(candidate_contract_receipt application-destination-alembic-version.sha256)"
expected_runtime_invariants_sql_sha256="$(docker run --pull=never --rm --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations
import json
from pathlib import Path
print(json.loads(Path("/app/alembic/baseline/application-reference.json").read_text(encoding="utf-8"))["artifacts"]["runtime_invariants_sql_sha256"])
')"
for digest in \
  "$expected_source_catalog_sha256" \
  "$expected_destination_catalog_sha256" \
  "$expected_seed_sha256" \
  "$expected_privileged_residue_sha256" \
  "$expected_source_alembic_version_sha256" \
  "$expected_destination_alembic_version_sha256" \
  "$expected_runtime_invariants_sql_sha256"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || die "candidate contract receipt SHA-256을 읽지 못했다"
done

contract_sha256() {
  local database="$1"
  local contract="$2"
  local scope="$3"
  local contract_sql
  contract_sql="$(docker run --pull=never --rm --entrypoint cat "$candidate_image_id" \
    "/app/alembic/baseline/$contract")"
  {
    printf '%s\n' 'BEGIN;'
    if [ "$scope" = "schema-owner" ]; then
      printf '%s\n' 'SET LOCAL ROLE ktm_feature_schema_owner;'
    elif [ "$scope" != "database-superuser" ]; then
      die "unknown contract scope: $scope"
    fi
    printf '%s\n' 'SET LOCAL search_path = public, x_extension;'
    printf '%s\n' 'SET LOCAL quote_all_identifiers TO off;'
    printf '%s\n' "SET LOCAL DateStyle TO 'ISO, YMD';"
    printf '%s\n' "SET LOCAL IntervalStyle TO 'postgres';"
    printf '%s\n' "SET LOCAL TimeZone TO 'UTC';"
    printf '%s\n' 'SET LOCAL extra_float_digits TO 3;'
    printf '%s\n' "SET LOCAL lc_numeric TO 'C';"
    printf '%s\n' "SET LOCAL bytea_output TO 'hex';"
    printf '%s\n' 'SET LOCAL standard_conforming_strings TO on;'
    printf '%s\n' "SET LOCAL xmlbinary TO 'base64';"
    printf '%s\n' "$contract_sql"
    printf '%s\n' 'ROLLBACK;'
  } | docker exec -i "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$database" -tA \
    | sha256sum | awk '{print $1}'
}

raw_revision() {
  docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$1" -tA \
    -c "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version"
}

assert_contracts() {
  local database="$1"
  local phase="$2"
  OBSERVED_CATALOG_SHA256="$(contract_sha256 "$database" application-catalog.sql schema-owner)"
  OBSERVED_SEED_SHA256="$(contract_sha256 "$database" application-seed.sql schema-owner)"
  OBSERVED_PRIVILEGED_RESIDUE_SHA256="$(contract_sha256 "$database" application-privileged-residue.sql database-superuser)"
  if [ "$phase" = "destination" ]; then
    [ "$OBSERVED_CATALOG_SHA256" = "$expected_destination_catalog_sha256" ] || \
      die "destination catalog receipt가 candidate와 다르다"
  else
    [ "$OBSERVED_CATALOG_SHA256" = "$expected_source_catalog_sha256" ] || \
      die "source catalog receipt가 candidate와 다르다"
  fi
  [ "$OBSERVED_SEED_SHA256" = "$expected_seed_sha256" ] || die "source/clone seed receipt가 candidate와 다르다"
  [ "$OBSERVED_PRIVILEGED_RESIDUE_SHA256" = "$expected_privileged_residue_sha256" ] || \
    die "source/clone privileged residue receipt가 candidate와 다르다"
  if [ "$phase" = "source" ] || [ "$phase" = "source-drift" ]; then
    OBSERVED_ALEMBIC_VERSION_SHA256="$(contract_sha256 "$database" application-source-alembic-version.sql schema-owner)"
    if [ "$phase" = "source" ]; then
      [ "$OBSERVED_ALEMBIC_VERSION_SHA256" = "$expected_source_alembic_version_sha256" ] || \
        die "source Alembic metadata facet이 candidate와 다르다"
    else
      [ "$OBSERVED_ALEMBIC_VERSION_SHA256" != "$expected_source_alembic_version_sha256" ] || \
        die "negative source Alembic metadata facet drift가 만들어지지 않았다"
    fi
  elif [ "$phase" = "destination" ]; then
    OBSERVED_ALEMBIC_VERSION_SHA256="$(contract_sha256 "$database" application-destination-alembic-version.sql schema-owner)"
    [ "$OBSERVED_ALEMBIC_VERSION_SHA256" = "$expected_destination_alembic_version_sha256" ] || \
      die "destination Alembic metadata facet이 candidate와 다르다"
  else
    die "unknown Alembic metadata contract phase: $phase"
  fi
}

# Helper는 fence volume을 read-only로 mount한다. handoff 종료 뒤에도 root-owned 0444
# byte가 같은지 확인해, postcondition catalog/privileged receipt가 바로 그 Manager-shaped
# fence 아래에서 관측됐음을 terminal receipt에 남긴다. 실제 production writer quiesce는
# Docker Manager가 별도로 소유하며, 이 isolated clone에는 시작된 writer가 없다.
assert_immutable_fence_file() {
  local expected_sha256="$1"
  mapfile -t fence_file_observation < <(docker run --pull=never --rm --user root \
    --mount "type=volume,source=$FENCE_VOLUME,target=/handoff-fence,readonly" \
    --entrypoint python "$candidate_image_id" -c '
from __future__ import annotations

import hashlib
import os
import stat

path = "/handoff-fence/writer-fence.json"
metadata = os.lstat(path)
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("writer fence is not a regular file")
print(hashlib.sha256(open(path, "rb").read()).hexdigest())
print(f"{metadata.st_uid}:{stat.S_IMODE(metadata.st_mode):03o}")
')
  [ "${#fence_file_observation[@]}" -eq 2 ] || die "mounted writer fence observation을 읽지 못했다"
  [ "${fence_file_observation[0]}" = "$expected_sha256" ] || \
    die "mounted writer fence bytes가 Manager-shaped receipt와 다르다"
  [ "${fence_file_observation[1]}" = "0:444" ] || \
    die "mounted writer fence가 root-owned mode 0444가 아니다"
  OBSERVED_FENCE_FILE_METADATA="${fence_file_observation[1]}"
}

[ "$(raw_revision "$SOURCE_DATABASE")" = "0236_tvn41s_compaction_drained" ] || \
  die "source oracle DB raw Alembic revision이 exact 0236이 아니다"
assert_contracts "$SOURCE_DATABASE" source
source_catalog_sha256="$OBSERVED_CATALOG_SHA256"
source_seed_sha256="$OBSERVED_SEED_SHA256"
source_privileged_residue_sha256="$OBSERVED_PRIVILEGED_RESIDUE_SHA256"
source_alembic_version_sha256="$OBSERVED_ALEMBIC_VERSION_SHA256"

SOURCE_PASSWORD="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$SOURCE_CONTAINER" \
  | awk -F= '$1 == "POSTGRES_PASSWORD" {print substr($0, index($0, "=") + 1); exit}')"
[ -n "$SOURCE_PASSWORD" ] || die "isolated source oracle PostgreSQL password를 읽지 못했다"
source_certificate_sha256="$(sha256sum "$SOURCE_CERTIFICATE" | awk '{print $1}')"

TMPDIR_PATH="$(mktemp -d "${TMPDIR:-/tmp}/ktm300-handoff-rehearsal.XXXXXX")"
suffix="$(openssl rand -hex 6)"
POSITIVE_DATABASE="ktm300_handoff_positive_${suffix}"
NEGATIVE_DATABASE="ktm300_handoff_negative_${suffix}"
FENCE_VOLUME="ktm300-handoff-fence-${suffix}"
docker volume create "$FENCE_VOLUME" >/dev/null

clone_source_database() {
  local target="$1"
  docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -c "CREATE DATABASE \"$target\" TEMPLATE \"$SOURCE_DATABASE\" OWNER ktm_feature_schema_owner" >/dev/null
}

clone_identity_json() {
  local database="$1"
  docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres -d "$database" -tA \
    -c "SELECT json_build_object(
          'database_name', current_database(),
          'database_oid', (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()),
          'database_owner', (SELECT datdba::regrole::text FROM pg_catalog.pg_database WHERE datname = current_database()),
          'postgres_system_identifier', (SELECT system_identifier::text FROM pg_catalog.pg_control_system())
        )::text"
}

write_root_fence_receipt() {
  local database="$1"
  local privileged_digest="$2"
  local target_json="$TMPDIR_PATH/fence-${database}.json"
  local identity
  identity="$(clone_identity_json "$database")"
  python3 - "$target_json" "$identity" "$candidate_commit" "$candidate_image_id" \
    "$reference_manifest_sha256" "$expected_source_catalog_sha256" \
    "$expected_destination_catalog_sha256" "$expected_seed_sha256" \
    "$expected_privileged_residue_sha256" "$privileged_digest" "$candidate_proof_tools_manifest_sha256" \
    "$candidate_postgres_image_id" "$expected_runtime_invariants_sql_sha256" \
    "$expected_source_alembic_version_sha256" \
    "$expected_destination_alembic_version_sha256" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

identity = json.loads(sys.argv[2])
journal_seed = json.dumps(
    {
        "kind": "isolated-application-300-handoff-rehearsal",
        "candidate_commit": sys.argv[3],
        "candidate_image_id": sys.argv[4],
        "database": identity,
        "proof_tools_manifest_sha256": sys.argv[11],
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
value = {
    "schema": "kor-travel-docker-manager.map-application-schema-handoff-fence.v6",
    "transaction_id": str(uuid4()),
    "journal_sha256": hashlib.sha256(journal_seed).hexdigest(),
    "journal_generation": 1,
    "operation": "map-application-schema-0236-to-300",
    "map_candidate_commit": sys.argv[3],
    "map_candidate_image_id": sys.argv[4],
    "postgres_image_id": sys.argv[12],
    "source_head": "0236_tvn41s_compaction_drained",
    "destination_head": "300",
    "reference_manifest_sha256": sys.argv[5],
    "source_catalog_sha256": sys.argv[6],
    "destination_catalog_sha256": sys.argv[7],
    "seed_sha256": sys.argv[8],
    "privileged_residue_sha256": sys.argv[9],
    "pre_privileged_residue_sha256": sys.argv[10],
    "runtime_invariants_sql_sha256": sys.argv[13],
    "source_alembic_version_sha256": sys.argv[14],
    "destination_alembic_version_sha256": sys.argv[15],
    **identity,
    "writer_fence_expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
}
with open(sys.argv[1], "w", encoding="utf-8") as target:
    target.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
PY
  FENCE_RECEIPT_SHA256="$(sha256sum "$target_json" | awk '{print $1}')"
  [[ "$FENCE_RECEIPT_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
    die "Manager-shaped writer fence receipt SHA-256을 얻지 못했다"
  mapfile -t fence_receipt_identity < <(python3 - "$target_json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in (
    "transaction_id", "journal_sha256", "journal_generation", "database_name",
    "database_oid", "database_owner", "postgres_system_identifier",
):
    if key not in value:
        raise SystemExit(f"writer fence field is missing: {key}")
print(value["transaction_id"])
print(value["journal_sha256"])
print(value["journal_generation"])
print(json.dumps({
    "database_name": value["database_name"],
    "database_oid": value["database_oid"],
    "database_owner": value["database_owner"],
    "postgres_system_identifier": value["postgres_system_identifier"],
}, sort_keys=True, separators=(",", ":")))
PY
)
  [ "${#fence_receipt_identity[@]}" -eq 4 ] || die "Manager-shaped writer fence identity를 읽지 못했다"
  FENCE_TRANSACTION_ID="${fence_receipt_identity[0]}"
  FENCE_JOURNAL_SHA256="${fence_receipt_identity[1]}"
  FENCE_JOURNAL_GENERATION="${fence_receipt_identity[2]}"
  FENCE_IDENTITY_JSON="${fence_receipt_identity[3]}"
  [ "$FENCE_IDENTITY_JSON" = "$(python3 - "$identity" <<'PY'
import json
import sys
print(json.dumps(json.loads(sys.argv[1]), sort_keys=True, separators=(",", ":")))
PY
)" ] || die "Manager-shaped writer fence DB identity가 clone과 다르다"
  docker run --pull=never -i --rm --user root \
    --mount "type=volume,source=$FENCE_VOLUME,target=/handoff-fence" \
    --entrypoint sh "$candidate_image_id" -ec \
    'umask 022; rm -f /handoff-fence/writer-fence.json; cat > /handoff-fence/writer-fence.json; chmod 0444 /handoff-fence/writer-fence.json' \
    <"$target_json"
  assert_immutable_fence_file "$FENCE_RECEIPT_SHA256"
}

run_handoff() {
  local database="$1"
  local output="$2"
  local dsn="postgresql+asyncpg://ktm_feature_migrator:${SOURCE_PASSWORD}@127.0.0.1:5432/${database}"
  docker run --pull=never --rm --user root --network "container:$SOURCE_CONTAINER" \
    --mount "type=volume,source=$FENCE_VOLUME,target=/handoff-fence,readonly" \
    -e "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=$dsn" \
    -e "KOR_TRAVEL_MAP_IMAGE_REVISION=$candidate_commit" \
    -e "KOR_TRAVEL_MAP_APPLICATION_HANDOFF_IMAGE_ID=$candidate_image_id" \
    --entrypoint /usr/local/bin/ktm-application-schema-handoff "$candidate_image_id" \
    --confirm-0236-to-300 --writer-fence-receipt /handoff-fence/writer-fence.json \
    >"$output"
}

source_identity_json="$(clone_identity_json "$SOURCE_DATABASE")"

clone_source_database "$NEGATIVE_DATABASE"
negative_identity_json="$(clone_identity_json "$NEGATIVE_DATABASE")"
assert_contracts "$NEGATIVE_DATABASE" source
docker exec "$SOURCE_CONTAINER" psql -q -v ON_ERROR_STOP=1 -U postgres \
  -d "$NEGATIVE_DATABASE" \
  -c "GRANT SELECT ON TABLE public.alembic_version TO ktm_feature_runtime" >/dev/null
assert_contracts "$NEGATIVE_DATABASE" source-drift
negative_before_catalog_sha256="$OBSERVED_CATALOG_SHA256"
negative_before_seed_sha256="$OBSERVED_SEED_SHA256"
negative_before_privileged_residue_sha256="$OBSERVED_PRIVILEGED_RESIDUE_SHA256"
negative_before_source_alembic_version_sha256="$OBSERVED_ALEMBIC_VERSION_SHA256"
write_root_fence_receipt "$NEGATIVE_DATABASE" "$expected_privileged_residue_sha256"
negative_fence_receipt_sha256="$FENCE_RECEIPT_SHA256"
negative_fence_transaction_id="$FENCE_TRANSACTION_ID"
negative_fence_journal_sha256="$FENCE_JOURNAL_SHA256"
negative_fence_journal_generation="$FENCE_JOURNAL_GENERATION"
negative_fence_file_metadata="$OBSERVED_FENCE_FILE_METADATA"
if run_handoff "$NEGATIVE_DATABASE" "$TMPDIR_PATH/negative-result.json" 2>"$TMPDIR_PATH/negative-stderr.log"; then
  die "source Alembic metadata facet drift가 unexpectedly handoff를 통과했다"
fi
[ ! -s "$TMPDIR_PATH/negative-result.json" ] || \
  die "negative handoff failure가 success result stdout을 남겼다"
[ "$(raw_revision "$NEGATIVE_DATABASE")" = "0236_tvn41s_compaction_drained" ] || \
  die "negative handoff failure 뒤 raw 0236 revision이 보존되지 않았다"
assert_immutable_fence_file "$negative_fence_receipt_sha256"
[ "$OBSERVED_FENCE_FILE_METADATA" = "$negative_fence_file_metadata" ] || \
  die "negative handoff 뒤 writer fence metadata가 변했다"
assert_contracts "$NEGATIVE_DATABASE" source-drift
negative_after_catalog_sha256="$OBSERVED_CATALOG_SHA256"
negative_after_seed_sha256="$OBSERVED_SEED_SHA256"
negative_after_privileged_residue_sha256="$OBSERVED_PRIVILEGED_RESIDUE_SHA256"
negative_after_source_alembic_version_sha256="$OBSERVED_ALEMBIC_VERSION_SHA256"
[ "$negative_before_catalog_sha256" = "$negative_after_catalog_sha256" ] \
  && [ "$negative_before_seed_sha256" = "$negative_after_seed_sha256" ] \
  && [ "$negative_before_privileged_residue_sha256" = "$negative_after_privileged_residue_sha256" ] || \
  die "negative handoff failure 뒤 source contract가 변했다"
[ "$negative_before_source_alembic_version_sha256" = \
  "$negative_after_source_alembic_version_sha256" ] || \
  die "negative handoff failure 뒤 source Alembic metadata facet이 변했다"
[ "$(clone_identity_json "$NEGATIVE_DATABASE")" = "$negative_identity_json" ] || \
  die "negative handoff failure 뒤 clone DB identity가 변했다"
[ ! -e "$RECEIPT" ] && [ ! -L "$RECEIPT" ] || \
  die "negative handoff failure가 terminal rehearsal receipt를 만들었다"

clone_source_database "$POSITIVE_DATABASE"
positive_identity_json="$(clone_identity_json "$POSITIVE_DATABASE")"
assert_contracts "$POSITIVE_DATABASE" source
positive_before_catalog_sha256="$OBSERVED_CATALOG_SHA256"
positive_before_seed_sha256="$OBSERVED_SEED_SHA256"
positive_before_privileged_residue_sha256="$OBSERVED_PRIVILEGED_RESIDUE_SHA256"
positive_before_source_alembic_version_sha256="$OBSERVED_ALEMBIC_VERSION_SHA256"
write_root_fence_receipt "$POSITIVE_DATABASE" "$expected_privileged_residue_sha256"
positive_fence_receipt_sha256="$FENCE_RECEIPT_SHA256"
positive_fence_transaction_id="$FENCE_TRANSACTION_ID"
positive_fence_journal_sha256="$FENCE_JOURNAL_SHA256"
positive_fence_journal_generation="$FENCE_JOURNAL_GENERATION"
positive_fence_file_metadata="$OBSERVED_FENCE_FILE_METADATA"
run_handoff "$POSITIVE_DATABASE" "$TMPDIR_PATH/positive-result.json" 2>"$TMPDIR_PATH/positive-stderr.log"
[ -s "$TMPDIR_PATH/positive-result.json" ] || die "positive handoff가 result stdout을 남기지 않았다"
[ "$(raw_revision "$POSITIVE_DATABASE")" = "300" ] || \
  die "positive handoff 뒤 raw Alembic revision이 exact 300이 아니다"
assert_immutable_fence_file "$positive_fence_receipt_sha256"
[ "$OBSERVED_FENCE_FILE_METADATA" = "$positive_fence_file_metadata" ] || \
  die "positive handoff 뒤 writer fence metadata가 변했다"
assert_contracts "$POSITIVE_DATABASE" destination
positive_after_catalog_sha256="$OBSERVED_CATALOG_SHA256"
positive_after_seed_sha256="$OBSERVED_SEED_SHA256"
positive_after_privileged_residue_sha256="$OBSERVED_PRIVILEGED_RESIDUE_SHA256"
positive_after_destination_alembic_version_sha256="$OBSERVED_ALEMBIC_VERSION_SHA256"
[ "$positive_before_catalog_sha256" = "$expected_source_catalog_sha256" ] \
  && [ "$positive_after_catalog_sha256" = "$expected_destination_catalog_sha256" ] \
  && [ "$positive_before_seed_sha256" = "$positive_after_seed_sha256" ] \
  && [ "$positive_before_privileged_residue_sha256" = "$positive_after_privileged_residue_sha256" ] || \
  die "positive handoff 뒤 contract가 immutable baseline에서 벗어났다"
[ "$(clone_identity_json "$POSITIVE_DATABASE")" = "$positive_identity_json" ] || \
  die "positive handoff 뒤 clone DB identity가 변했다"

terminal_receipt_tmp="$TMPDIR_PATH/terminal-receipt.json"
python3 - "$terminal_receipt_tmp" "$candidate_provenance_json" "$source_certificate_sha256" \
  "$source_identity_json" "$source_catalog_sha256" "$source_seed_sha256" "$source_privileged_residue_sha256" \
  "$positive_identity_json" "$positive_fence_receipt_sha256" "$positive_fence_transaction_id" \
  "$positive_fence_file_metadata" "$expected_source_catalog_sha256" "$expected_seed_sha256" \
  "$expected_privileged_residue_sha256" "$positive_after_catalog_sha256" \
  "$positive_after_seed_sha256" "$positive_after_privileged_residue_sha256" \
  "$TMPDIR_PATH/positive-result.json" "$negative_identity_json" \
  "$negative_fence_receipt_sha256" "$negative_fence_transaction_id" "$negative_fence_file_metadata" \
  "$negative_before_catalog_sha256" "$negative_before_seed_sha256" \
  "$negative_before_privileged_residue_sha256" "$negative_after_catalog_sha256" \
  "$negative_after_seed_sha256" "$negative_after_privileged_residue_sha256" \
  "$TMPDIR_PATH/negative-result.json" "$TMPDIR_PATH/negative-stderr.log" \
  "$expected_source_alembic_version_sha256" \
  "$expected_destination_alembic_version_sha256" \
  "$source_alembic_version_sha256" \
  "$positive_before_source_alembic_version_sha256" \
  "$positive_after_destination_alembic_version_sha256" \
  "$negative_before_source_alembic_version_sha256" \
  "$negative_after_source_alembic_version_sha256" \
  "$positive_fence_journal_sha256" "$positive_fence_journal_generation" \
  "$expected_destination_catalog_sha256" "$paired_build_receipt_sha256" \
  "$paired_dagster_image_id" "$paired_candidate_git_tree" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    candidate = json.loads(sys.argv[2])
    source_identity = json.loads(sys.argv[4])
    positive_identity = json.loads(sys.argv[8])
    negative_identity = json.loads(sys.argv[19])
    positive_raw = Path(sys.argv[18]).read_bytes()
    positive = json.loads(positive_raw)
except (OSError, ValueError) as exc:
    raise SystemExit(f"handoff rehearsal result cannot be parsed: {exc}") from exc
for name, identity in (
    ("source", source_identity),
    ("positive", positive_identity),
    ("negative", negative_identity),
):
    if (
        not isinstance(identity, dict)
        or set(identity) != {
            "database_name", "database_oid", "database_owner", "postgres_system_identifier"
        }
        or not isinstance(identity["database_name"], str)
        or not isinstance(identity["database_oid"], int)
        or identity["database_owner"] != "ktm_feature_schema_owner"
        or not isinstance(identity["postgres_system_identifier"], str)
        or not identity["postgres_system_identifier"].isdigit()
    ):
        raise SystemExit(f"{name} database identity is invalid")
for key in (
    "candidate_commit", "candidate_image_id", "candidate_build_receipt_sha256",
    "candidate_proof_tools_manifest_sha256",
):
    if key not in candidate:
        raise SystemExit(f"candidate provenance is missing: {key}")
expected_positive_result = {
    "schema": "kor-travel-map.application-baseline-handoff.v5",
    "outcome": "stamped",
    "source_head": "0236_tvn41s_compaction_drained",
    "destination_head": "300",
    "expected_source_catalog_sha256": sys.argv[12],
    "expected_destination_catalog_sha256": sys.argv[40],
    "expected_seed_sha256": sys.argv[13],
    "expected_privileged_residue_sha256": sys.argv[14],
    "expected_source_alembic_version_sha256": sys.argv[31],
    "expected_destination_alembic_version_sha256": sys.argv[32],
    "pre_privileged_residue_sha256": sys.argv[14],
    "pre_catalog_sha256": sys.argv[12],
    "pre_seed_sha256": sys.argv[13],
    "pre_source_alembic_version_sha256": sys.argv[34],
    "post_catalog_sha256": sys.argv[40],
    "post_seed_sha256": sys.argv[13],
    "post_destination_alembic_version_sha256": sys.argv[35],
    "writer_fence_receipt_sha256": sys.argv[9],
    "writer_fence_transaction_id": sys.argv[10],
    "journal_sha256": sys.argv[38],
    "journal_generation": int(sys.argv[39]),
}
if not isinstance(positive, dict) or positive != expected_positive_result:
    raise SystemExit("positive handoff result is not the exact fenced 0236-to-300 stamp")
if positive_raw.count(b"\n") != 1 or not positive_raw.endswith(b"\n"):
    raise SystemExit("positive handoff result must be exactly one JSON line")
negative_result = Path(sys.argv[29]).read_bytes()
if negative_result:
    raise SystemExit("negative fence mismatch produced a result payload")
negative_error = Path(sys.argv[30]).read_text(encoding="utf-8")
if "source Alembic metadata facet" not in negative_error:
    raise SystemExit("negative handoff did not fail at the source Alembic facet boundary")
for key in (
    "candidate_build_receipt_sha256", "candidate_proof_tools_manifest_sha256",
    "source_certificate_sha256", "positive_writer_fence_receipt_sha256",
    "negative_writer_fence_receipt_sha256", "positive_result_sha256",
    "paired_candidate_build_receipt_sha256",
):
    value = {
        "candidate_build_receipt_sha256": candidate["candidate_build_receipt_sha256"],
        "candidate_proof_tools_manifest_sha256": candidate["candidate_proof_tools_manifest_sha256"],
        "source_certificate_sha256": sys.argv[3],
        "positive_writer_fence_receipt_sha256": sys.argv[9],
        "negative_writer_fence_receipt_sha256": sys.argv[20],
        "positive_result_sha256": hashlib.sha256(positive_raw).hexdigest(),
        "paired_candidate_build_receipt_sha256": sys.argv[41],
    }[key]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit(f"terminal handoff receipt digest is invalid: {key}")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", sys.argv[42]):
    raise SystemExit("terminal handoff receipt paired Dagster image ID is invalid")
if not re.fullmatch(r"[0-9a-f]{40}", sys.argv[43]):
    raise SystemExit("terminal handoff receipt paired Git tree is invalid")
value = {
    "schema": "kor-travel-map.application-300-handoff-rehearsal.v6",
    "candidate_commit": candidate["candidate_commit"],
    "candidate_git_tree": sys.argv[43],
    "candidate_image_id": candidate["candidate_image_id"],
    "candidate_build_receipt_sha256": candidate["candidate_build_receipt_sha256"],
    "paired_candidate_build_receipt_sha256": sys.argv[41],
    "paired_dagster_image_id": sys.argv[42],
    "candidate_proof_tools_manifest_sha256": candidate["candidate_proof_tools_manifest_sha256"],
    "source_certificate_sha256": sys.argv[3],
    "source_database_identity": source_identity,
    "source_catalog_sha256": sys.argv[5],
    "source_seed_sha256": sys.argv[6],
    "source_privileged_residue_sha256": sys.argv[7],
    "source_alembic_version_sha256": sys.argv[33],
    "expected_source_catalog_sha256": sys.argv[12],
    "expected_destination_catalog_sha256": sys.argv[40],
    "expected_seed_sha256": sys.argv[13],
    "expected_privileged_residue_sha256": sys.argv[14],
    "expected_source_alembic_version_sha256": sys.argv[31],
    "expected_destination_alembic_version_sha256": sys.argv[32],
    "positive_database_identity": positive_identity,
    "positive_writer_fence_receipt_sha256": sys.argv[9],
    "positive_writer_fence_transaction_id": sys.argv[10],
    "positive_writer_fence_file_metadata": sys.argv[11],
    "positive_raw_revision": "300",
    "positive_catalog_sha256": sys.argv[15],
    "positive_seed_sha256": sys.argv[16],
    "positive_privileged_residue_sha256": sys.argv[17],
    "positive_source_alembic_version_sha256": sys.argv[34],
    "positive_destination_alembic_version_sha256": sys.argv[35],
    "positive_result_sha256": hashlib.sha256(positive_raw).hexdigest(),
    "negative_database_identity": negative_identity,
    "negative_writer_fence_receipt_sha256": sys.argv[20],
    "negative_writer_fence_transaction_id": sys.argv[21],
    "negative_writer_fence_file_metadata": sys.argv[22],
    "negative_raw_revision": "0236_tvn41s_compaction_drained",
    "negative_catalog_sha256_before": sys.argv[23],
    "negative_seed_sha256_before": sys.argv[24],
    "negative_privileged_residue_sha256_before": sys.argv[25],
    "negative_source_alembic_version_sha256_before": sys.argv[36],
    "negative_catalog_sha256_after": sys.argv[26],
    "negative_seed_sha256_after": sys.argv[27],
    "negative_privileged_residue_sha256_after": sys.argv[28],
    "negative_source_alembic_version_sha256_after": sys.argv[37],
    "negative_failure": "source-alembic-version-facet-mismatch",
    "terminal_receipt_writer": "root-candidate-image-atomic-link",
}
Path(sys.argv[1]).write_text(
    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
receipt_name="$(basename -- "$RECEIPT")"
docker run --pull=never -i --rm --user root \
  --mount "type=bind,source=$RECEIPT_PARENT,target=/handoff-receipt" \
  --entrypoint sh "$candidate_image_id" -ec '
set -eu
name="$1"
target="/handoff-receipt/$name"
[ ! -e "$target" ] && [ ! -L "$target" ] || exit 73
temporary="$(mktemp /handoff-receipt/.ktm300-handoff-receipt.XXXXXX)"
cleanup() { rm -f -- "$temporary"; }
trap cleanup EXIT
cat > "$temporary"
chmod 0444 "$temporary"
ln "$temporary" "$target"
' sh "$receipt_name" <"$terminal_receipt_tmp"
python3 - "$RECEIPT" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
    raise SystemExit("terminal handoff rehearsal receipt is not a regular file")
if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o444:
    raise SystemExit("terminal handoff rehearsal receipt must be root-owned mode 0444")
PY
printf 'application 300 handoff rehearsal passed: receipt=%s\n' "$RECEIPT"
