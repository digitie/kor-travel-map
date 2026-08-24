#!/usr/local/bin/python
"""Map application schema의 one-shot ``0236 → 300`` metadata handoff.

이 executable은 Docker Manager가 writer fence를 확보한 뒤에만 호출한다. DDL, data
rewrite, raw ``alembic_version`` SQL은 사용하지 않는다. 같은 connection/outer
transaction 안에서 exact source preflight → Alembic controlled stamp → final-state
postflight를 수행하므로 postflight가 실패하면 source ``0236`` row가 보존된다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import stat
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from alembic import command
from kortravelmap.infra.db import make_async_engine

_SOURCE_HEAD: Final = "0236_tvn41s_compaction_drained"
_DESTINATION_HEAD: Final = "300"
_HANDOFF_TAG: Final = "application-schema-0236-to-300"
_SCHEMA_OWNER_ROLE: Final = "ktm_feature_schema_owner"
_SCHEMA_OWNER_ROLE_ENV: Final = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"
_HANDOFF_CAPABILITY_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_HANDOFF_CAPABILITY_PATH"
_HANDOFF_CAPABILITY_DIRECTORY: Final = Path("/run/kor-travel-map-application-handoff")
_HANDOFF_CAPABILITY_FILE: Final = _HANDOFF_CAPABILITY_DIRECTORY / "capability"
_RESULT_SCHEMA: Final = "kor-travel-map.application-baseline-handoff.v2"
_FENCE_RECEIPT_SCHEMA: Final = (
    "kor-travel-docker-manager.map-application-schema-handoff-fence.v3"
)
_FENCE_OPERATION: Final = "map-application-schema-0236-to-300"
_IMAGE_REVISION_ENV: Final = "KOR_TRAVEL_MAP_IMAGE_REVISION"
_HANDOFF_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_HANDOFF_IMAGE_ID"
_HANDOFF_ADVISORY_LOCK_KEY: Final[tuple[int, int]] = (300, 236)
_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])
_CATALOG_CONTRACT_SQL: Final = "application-catalog.sql"
_CATALOG_CONTRACT_SHA256: Final = "application-catalog.sha256"
_SEED_CONTRACT_SQL: Final = "application-seed.sql"
_SEED_CONTRACT_SHA256: Final = "application-seed.sha256"
_PRIVILEGED_RESIDUE_CONTRACT_SQL: Final = "application-privileged-residue.sql"
_PRIVILEGED_RESIDUE_CONTRACT_SHA256: Final = "application-privileged-residue.sha256"
_RUNTIME_INVARIANTS_SQL: Final = "application-runtime-invariants.sql"
_REFERENCE_MANIFEST: Final = "application-reference.json"
_REFERENCE_MANIFEST_SHA256: Final = "application-reference.sha256"
_REFERENCE_SCHEMA: Final = "kor-travel-map.application-baseline-reference.v1"
_IMMUTABLE_SEED_RELATIONS: Final = (
    "ops.feature_override_field_paths",
)
_MAP_VISIBLE_CONTRACT_KEYS: Final = (
    "catalog_sha256",
    "seed_sha256",
)
_CANONICAL_CONTRACT_GUC_STATEMENTS: Final = (
    "SET LOCAL quote_all_identifiers TO off",
    "SET LOCAL DateStyle TO 'ISO, YMD'",
    "SET LOCAL IntervalStyle TO 'postgres'",
    "SET LOCAL TimeZone TO 'UTC'",
    "SET LOCAL extra_float_digits TO 3",
    "SET LOCAL lc_numeric TO 'C'",
    "SET LOCAL bytea_output TO 'hex'",
    "SET LOCAL standard_conforming_strings TO on",
    "SET LOCAL xmlbinary TO 'base64'",
)
_FENCE_RECEIPT_FIELDS: Final = frozenset(
    {
        "schema",
        "transaction_id",
        "journal_sha256",
        "operation",
        "map_candidate_commit",
        "map_candidate_image_id",
        "postgres_image_id",
        "source_head",
        "destination_head",
        "reference_manifest_sha256",
        "catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "pre_privileged_residue_sha256",
        "runtime_invariants_sql_sha256",
        "database_name",
        "database_oid",
        "database_owner",
        "postgres_system_identifier",
        "writer_fence_expires_at",
    }
)

_NOLOGIN_ROLES: Final = (
    "ktm_feature_schema_owner",
    "ktm_feature_state_procedure_owner",
    "ktm_feature_audit_writer",
    "ktm_feature_runtime",
    "ktm_curation_command_owner",
    "ktm_curation_audit_writer",
    "ktm_curation_admin_executor",
    "ktm_curation_provider_executor",
    "ktm_manual_feature_procedure_owner",
    "ktm_manual_feature_admin_executor",
    "ktm_feature_create_provider_executor",
    "ktm_feature_request_procedure_owner",
    "ktm_feature_request_service_executor",
    "ktm_feature_request_admin_executor",
    "ktm_manual_provider_dedup_procedure_owner",
    "ktm_manual_provider_dedup_detector_executor",
    "ktm_manual_provider_dedup_admin_executor",
    "ktm_feature_reference_reconciliation_service_executor",
)
_LOGIN_ROLES: Final = (
    "ktm_feature_migrator",
    "ktm_feature_api_runtime",
    "ktm_feature_dagster_runtime",
)
_APPLICATION_ROLES: Final = _NOLOGIN_ROLES + _LOGIN_ROLES
_EXPECTED_DATABASE_SEARCH_PATH: Final = ("search_path=public, x_extension",)
_EXPECTED_ROLE_CONNECTION_LIMIT: Final = -1
_EXPECTED_ROLE_VALID_UNTIL: Final = "infinity"
_EXPECTED_MEMBERSHIPS: Final = frozenset(
    {
        ("ktm_curation_admin_executor", "ktm_feature_api_runtime", False, True, False),
        ("ktm_curation_audit_writer", "ktm_feature_schema_owner", False, False, True),
        ("ktm_curation_command_owner", "ktm_feature_schema_owner", False, False, True),
        ("ktm_curation_provider_executor", "ktm_feature_dagster_runtime", False, True, False),
        ("ktm_feature_audit_writer", "ktm_feature_schema_owner", False, False, True),
        ("ktm_feature_create_provider_executor", "ktm_feature_dagster_runtime", False, True, False),
        (
            "ktm_feature_reference_reconciliation_service_executor",
            "ktm_feature_api_runtime",
            False,
            True,
            False,
        ),
        ("ktm_feature_request_admin_executor", "ktm_feature_api_runtime", False, True, False),
        ("ktm_feature_request_procedure_owner", "ktm_feature_schema_owner", False, False, True),
        ("ktm_feature_request_service_executor", "ktm_feature_api_runtime", False, True, False),
        ("ktm_feature_runtime", "ktm_feature_api_runtime", False, True, False),
        ("ktm_feature_runtime", "ktm_feature_dagster_runtime", False, True, False),
        ("ktm_feature_schema_owner", "ktm_feature_migrator", False, False, True),
        ("ktm_feature_state_procedure_owner", "ktm_feature_schema_owner", False, False, True),
        ("ktm_manual_feature_admin_executor", "ktm_feature_api_runtime", False, True, False),
        ("ktm_manual_feature_procedure_owner", "ktm_feature_schema_owner", False, False, True),
        ("ktm_manual_provider_dedup_admin_executor", "ktm_feature_api_runtime", False, True, False),
        (
            "ktm_manual_provider_dedup_detector_executor",
            "ktm_feature_dagster_runtime",
            False,
            True,
            False,
        ),
        (
            "ktm_manual_provider_dedup_procedure_owner",
            "ktm_feature_schema_owner",
            False,
            False,
            True,
        ),
    }
)
_X_EXTENSION_USAGE: Final = {
    "ktm_feature_schema_owner": True,
    "ktm_feature_state_procedure_owner": True,
    "ktm_feature_audit_writer": False,
    "ktm_feature_runtime": True,
    "ktm_curation_command_owner": True,
    "ktm_curation_audit_writer": False,
    "ktm_curation_admin_executor": False,
    "ktm_curation_provider_executor": False,
    "ktm_feature_migrator": False,
    "ktm_feature_api_runtime": True,
    "ktm_feature_dagster_runtime": True,
    "ktm_manual_feature_procedure_owner": False,
    "ktm_manual_feature_admin_executor": False,
    "ktm_feature_create_provider_executor": False,
    "ktm_feature_request_procedure_owner": False,
    "ktm_feature_request_service_executor": False,
    "ktm_feature_request_admin_executor": False,
    "ktm_manual_provider_dedup_procedure_owner": True,
    "ktm_manual_provider_dedup_detector_executor": False,
    "ktm_manual_provider_dedup_admin_executor": False,
    "ktm_feature_reference_reconciliation_service_executor": False,
}

_CATALOG_FINGERPRINT_SQL: Final = """
SELECT item
FROM (
    SELECT 'relation:' || namespace.nspname || '.' || relation.relname || ':'
           || relation.relkind::text || ':' || pg_get_userbyid(relation.relowner)
           || ':' || coalesce(relation.relacl::text, '') || ':'
           || relation.relrowsecurity::text || ':' || relation.relforcerowsecurity::text AS item
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    UNION ALL
    SELECT 'column:' || namespace.nspname || '.' || relation.relname || '.' || attribute.attname
           || ':' || pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
           || ':' || attribute.attnotnull::text || ':' || attribute.attidentity::text
           || ':' || attribute.attgenerated::text || ':'
           || coalesce(pg_get_expr(default_value.adbin, default_value.adrelid), '')
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef AS default_value
      ON default_value.adrelid = attribute.attrelid
     AND default_value.adnum = attribute.attnum
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
      AND attribute.attnum > 0 AND NOT attribute.attisdropped
    UNION ALL
    SELECT 'constraint:' || namespace.nspname || '.' || relation.relname || '.' || con.conname
           || ':' || con.contype::text || ':' || con.convalidated::text || ':'
           || con.condeferrable::text || ':' || con.condeferred::text || ':'
           || pg_get_constraintdef(con.oid, true)
    FROM pg_catalog.pg_constraint AS con
    JOIN pg_catalog.pg_class AS relation ON relation.oid = con.conrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    UNION ALL
    SELECT 'index:' || namespace.nspname || '.' || relation.relname || '.' || index_relation.relname
           || ':' || index_row.indisvalid::text || ':' || index_row.indisready::text || ':'
           || index_row.indislive::text || ':' || pg_get_indexdef(index_row.indexrelid)
    FROM pg_catalog.pg_index AS index_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = index_row.indrelid
    JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index_row.indexrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    UNION ALL
    SELECT 'routine:' || namespace.nspname || '.' || routine.proname || '('
           || pg_get_function_identity_arguments(routine.oid) || '):'
           || pg_get_userbyid(routine.proowner) || ':' || coalesce(routine.proacl::text, '')
           || ':' || pg_get_functiondef(routine.oid)
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    UNION ALL
    SELECT 'trigger:' || namespace.nspname || '.' || relation.relname || '.' || trigger.tgname
           || ':' || trigger.tgenabled::text || ':' || pg_get_triggerdef(trigger.oid, true)
    FROM pg_catalog.pg_trigger AS trigger
    JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND NOT trigger.tgisinternal
    UNION ALL
    SELECT 'schema:' || namespace.nspname || ':' || pg_get_userbyid(namespace.nspowner)
           || ':' || coalesce(namespace.nspacl::text, '')
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
    UNION ALL
    SELECT 'extension:' || extension.extname || ':' || namespace.nspname || ':'
           || extension.extversion
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
    WHERE extension.extname IN ('postgis', 'pgcrypto', 'pg_trgm', 'pg_prewarm')
    UNION ALL
    SELECT 'database:' || pg_get_userbyid(database_row.datdba) || ':'
           || coalesce(database_row.datacl::text, '') || ':' || coalesce(
               (
                   SELECT string_agg(setting.value, '|' ORDER BY setting.value)
                   FROM pg_catalog.pg_db_role_setting AS setting_row
                   CROSS JOIN LATERAL unnest(setting_row.setconfig) AS setting(value)
                   WHERE setting_row.setdatabase = database_row.oid
                     AND setting_row.setrole = 0
                     AND setting.value LIKE 'search_path=%'
               ),
               ''
           )
    FROM pg_catalog.pg_database AS database_row
    WHERE database_row.datname = current_database()
    UNION ALL
    SELECT 'role:' || role.rolname || ':' || role.rolcanlogin::text || ':'
           || role.rolinherit::text || ':' || role.rolsuper::text || ':'
           || role.rolcreatedb::text || ':' || role.rolcreaterole::text || ':'
           || role.rolbypassrls::text || ':' || role.rolreplication::text
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = ANY(CAST(:roles AS text[]))
    UNION ALL
    SELECT 'membership:' || granted.rolname || ':' || member.rolname || ':'
           || membership.admin_option::text || ':' || membership.inherit_option::text
           || ':' || membership.set_option::text
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
    JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
    WHERE granted.rolname = ANY(CAST(:roles AS text[]))
       OR member.rolname = ANY(CAST(:roles AS text[]))
) AS catalog
ORDER BY item
"""


class HandoffError(RuntimeError):
    """operator-safe controlled handoff failure."""


def _parse_args(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="exact 0236-to-300 Map application schema handoff"
    )
    parser.add_argument(
        "--confirm-0236-to-300",
        action="store_true",
        help="exact source/target metadata handoff를 명시적으로 승인한다",
    )
    parser.add_argument(
        "--writer-fence-receipt",
        required=True,
        metavar="PATH",
        help=(
            "Docker Manager가 root-owned mode 0444로 read-only mount한 "
            "writer fence receipt JSON path"
        ),
    )
    parsed = parser.parse_args(arguments)
    if not parsed.confirm_0236_to_300:
        parser.error("--confirm-0236-to-300 is required")
    if not Path(parsed.writer_fence_receipt).is_absolute():
        parser.error("--writer-fence-receipt must be an absolute JSON receipt path")
    return parsed


def _application_root() -> Path:
    """image `/app`와 source-tree test 양쪽에서 application artifact root를 찾는다."""

    for root in _APPLICATION_ROOT_CANDIDATES:
        if (root / "alembic.ini").is_file() and (root / "alembic" / "versions").is_dir():
            return root
    raise HandoffError("application Alembic artifact root is unavailable")


def _config(dsn: str) -> Config:
    root = _application_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


def _baseline_artifact(name: str) -> Path:
    """production image에 함께 넣은 immutable baseline receipt artifact를 연다."""

    path = _application_root() / "alembic" / "baseline" / name
    if not path.is_file() or path.is_symlink():
        raise HandoffError(f"immutable application baseline artifact is unavailable: {name}")
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference_manifest_sha256() -> str:
    """candidate image에 함께 든 generated manifest digest를 fail-closed로 읽는다."""

    raw = _baseline_artifact(_REFERENCE_MANIFEST_SHA256).read_bytes()
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise HandoffError(
            "immutable application baseline reference manifest digest is malformed"
        ) from exc
    if not _is_sha256(value) or raw != f"{value}\n".encode("ascii"):
        raise HandoffError(
            "immutable application baseline reference manifest digest is malformed"
        )
    return value


def _reference_manifest() -> dict[str, Any]:
    """image와 함께 고정한 application baseline reference를 엄격히 연다.

    contract SQL, expected row receipt, schema/seed sidecar가 각각 따로 바뀌면 raw
    `0236`의 version label만으로는 알아낼 수 없다. 이 manifest는 그 파일들의 한
    reference receipt이며, handoff와 fresh `300` 양쪽이 같은 증거를 사용한다.
    """

    path = _baseline_artifact(_REFERENCE_MANIFEST)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _reference_manifest_sha256():
        raise HandoffError("immutable application baseline reference manifest drifted")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise HandoffError("immutable application baseline reference is malformed") from exc
    if not isinstance(value, dict) or value.get("schema") != _REFERENCE_SCHEMA:
        raise HandoffError("immutable application baseline reference schema is invalid")
    source = value.get("source")
    artifacts = value.get("artifacts")
    static_seed_relations = value.get("static_seed_relations")
    if not isinstance(source, dict) or not isinstance(artifacts, dict):
        raise HandoffError("immutable application baseline reference is incomplete")
    expected_source = {
        "git_commit": "01d65b2ad4ee265a3ef6b01448f6abf573a906a8",
        "raw_alembic_revision": _SOURCE_HEAD,
        "container_image": "postgis/postgis:16-3.5-alpine",
        "container_image_id": (
            "sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c"
        ),
        "postgres_server_version_num": "160014",
        "postgis_extension_version": "3.5.6",
    }
    if {key: source.get(key) for key in expected_source} != expected_source:
        raise HandoffError("immutable application baseline source provenance is invalid")
    if tuple(static_seed_relations or ()) != _IMMUTABLE_SEED_RELATIONS:
        raise HandoffError("immutable application baseline static seed inventory is invalid")
    return value


def _manifest_sha256(manifest: dict[str, Any], key: str) -> str:
    artifacts = manifest["artifacts"]
    expected = artifacts.get(key)
    if not isinstance(expected, str) or len(expected) != 64 or any(
        character not in "0123456789abcdef" for character in expected
    ):
        raise HandoffError(f"immutable application baseline manifest digest is malformed: {key}")
    return expected


def _verify_reference_artifacts() -> dict[str, str]:
    """manifest와 image sidecar 전체가 one receipt인지 확인한다."""

    manifest = _reference_manifest()
    file_digests = {
        "schema.sql": "schema_sql_sha256",
        "seed.sql": "seed_sql_sha256",
        _CATALOG_CONTRACT_SQL: "catalog_contract_sql_sha256",
        _SEED_CONTRACT_SQL: "seed_contract_sql_sha256",
        _PRIVILEGED_RESIDUE_CONTRACT_SQL: "privileged_residue_contract_sql_sha256",
        _RUNTIME_INVARIANTS_SQL: "runtime_invariants_sql_sha256",
        _CATALOG_CONTRACT_SHA256: "catalog_contract_receipt_sha256",
        _SEED_CONTRACT_SHA256: "seed_contract_receipt_sha256",
        _PRIVILEGED_RESIDUE_CONTRACT_SHA256: "privileged_residue_contract_receipt_sha256",
    }
    for name, manifest_key in file_digests.items():
        if _sha256_file(_baseline_artifact(name)) != _manifest_sha256(manifest, manifest_key):
            raise HandoffError(f"immutable application baseline artifact digest drifted: {name}")

    expected: dict[str, str] = {}
    for receipt_name, manifest_key, result_key in (
        (_CATALOG_CONTRACT_SHA256, "catalog_contract_sha256", "catalog_sha256"),
        (_SEED_CONTRACT_SHA256, "seed_contract_sha256", "seed_sha256"),
        (
            _PRIVILEGED_RESIDUE_CONTRACT_SHA256,
            "privileged_residue_contract_sha256",
            "privileged_residue_sha256",
        ),
    ):
        try:
            receipt = _baseline_artifact(receipt_name).read_text(encoding="ascii").strip()
        except OSError as exc:
            raise HandoffError("immutable application baseline receipt is unavailable") from exc
        manifest_receipt = _manifest_sha256(manifest, manifest_key)
        if receipt != manifest_receipt:
            raise HandoffError("immutable application baseline receipt/manifest drifted")
        expected[result_key] = receipt
    expected["runtime_invariants_sql_sha256"] = _manifest_sha256(
        manifest, "runtime_invariants_sql_sha256"
    )
    return expected


def _expected_catalog_sha256() -> str:
    return _verify_reference_artifacts()["catalog_sha256"]


def _expected_seed_sha256() -> str:
    return _verify_reference_artifacts()["seed_sha256"]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _writer_fence_expiry(receipt: dict[str, Any]) -> datetime:
    """timezone 없는 fence expiry를 host local timezone으로 추측하지 않는다."""

    try:
        expires_at = datetime.fromisoformat(str(receipt["writer_fence_expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffError("Docker Manager writer fence expiry is invalid") from exc
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise HandoffError("Docker Manager writer fence expiry must include an offset")
    return expires_at.astimezone(UTC)


def _require_unexpired_writer_fence(receipt: dict[str, Any]) -> None:
    """long preflight 뒤에도 stamp/commit 바로 전에 writer fence가 살아 있어야 한다."""

    if _writer_fence_expiry(receipt) <= datetime.now(UTC):
        raise HandoffError("Docker Manager writer fence receipt has expired")


def _load_writer_fence_receipt(receipt_path: str) -> tuple[dict[str, Any], str]:
    """Manager가 mount한 one-shot fence receipt를 fail-closed로 읽는다.

    평문 식별자는 quiesce된 writer/DB/candidate와 아무것도 묶지 못한다. receipt file은
    Manager가 host에서 생성해 read-only mount하며, Map은 filesystem 권한·schema·expiry를
    먼저 확인하고 transaction 안에서 실제 DB identity와 다시 대조한다.
    """

    path = Path(receipt_path)
    if not path.is_absolute():
        raise HandoffError("Docker Manager writer fence receipt path must be absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise HandoffError("Docker Manager writer fence receipt is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise HandoffError("Docker Manager writer fence receipt must be a regular file")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise HandoffError("Docker Manager writer fence receipt is writable by group/other")
    # production image는 appuser로 handoff helper를 실행한다. receipt에는 secret이 없고
    # root-created read-only bind mount가 integrity 경계이므로, root:root 0444만 수용한다.
    # source-tree integration은 fixture file을 current test UID로 만들기 때문에 이 exact
    # production mount rule은 `/app`에만 적용한다.
    if _application_root() == Path("/app") and (
        metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o444
    ):
        raise HandoffError(
            "Docker Manager writer fence receipt must be root-owned mode 0444 in image"
        )
    try:
        with path.open("rb") as source:
            opened_metadata = os.fstat(source.fileno())
            if (opened_metadata.st_dev, opened_metadata.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise HandoffError("Docker Manager writer fence receipt changed while opening")
            raw = source.read()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HandoffError("Docker Manager writer fence receipt is malformed") from exc
    if not isinstance(value, dict) or set(value) != _FENCE_RECEIPT_FIELDS:
        raise HandoffError("Docker Manager writer fence receipt schema is invalid")
    if value.get("schema") != _FENCE_RECEIPT_SCHEMA:
        raise HandoffError("Docker Manager writer fence receipt version is invalid")
    if value.get("operation") != _FENCE_OPERATION:
        raise HandoffError("Docker Manager writer fence receipt operation is invalid")
    try:
        UUID(str(value["transaction_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffError("Docker Manager writer fence transaction id is invalid") from exc
    for key in (
        "journal_sha256",
        "reference_manifest_sha256",
        "catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "pre_privileged_residue_sha256",
        "runtime_invariants_sql_sha256",
    ):
        if not _is_sha256(value.get(key)):
            raise HandoffError(f"Docker Manager writer fence receipt digest is invalid: {key}")
    candidate_commit = value.get("map_candidate_commit")
    candidate_image_id = value.get("map_candidate_image_id")
    postgres_image_id = value.get("postgres_image_id")
    if (
        not isinstance(candidate_commit, str)
        or len(candidate_commit) != 40
        or any(character not in "0123456789abcdef" for character in candidate_commit)
        or not isinstance(candidate_image_id, str)
        or not candidate_image_id.startswith("sha256:")
        or len(candidate_image_id) != 71
        or any(character not in "0123456789abcdef" for character in candidate_image_id[7:])
        or not isinstance(postgres_image_id, str)
        or not postgres_image_id.startswith("sha256:")
        or len(postgres_image_id) != 71
        or any(character not in "0123456789abcdef" for character in postgres_image_id[7:])
    ):
        raise HandoffError("Docker Manager writer fence candidate identity is invalid")
    if (
        value.get("source_head") != _SOURCE_HEAD
        or value.get("destination_head") != _DESTINATION_HEAD
        or value.get("database_owner") != _SCHEMA_OWNER_ROLE
        or not isinstance(value.get("database_name"), str)
        or not isinstance(value.get("database_oid"), int)
        or not isinstance(value.get("postgres_system_identifier"), str)
        or not str(value["postgres_system_identifier"]).isdigit()
    ):
        raise HandoffError("Docker Manager writer fence database binding is invalid")
    _require_unexpired_writer_fence(value)
    return value, hashlib.sha256(raw).hexdigest()


async def _verify_migrator_session(connection: AsyncConnection) -> None:
    """`SET ROLE` 전에 LOGIN principal을 고정한다 — superuser 우회 금지."""

    session_user = await connection.scalar(text("SELECT session_user"))
    if session_user != "ktm_feature_migrator":
        raise HandoffError("controlled handoff must connect as ktm_feature_migrator")


async def _acquire_handoff_advisory_lock(connection: AsyncConnection) -> None:
    """Manager journal 밖의 concurrent stamp도 DB transaction 경계에서 막는다."""

    acquired = await connection.scalar(
        text("SELECT pg_try_advisory_xact_lock(:first, :second)"),
        {"first": _HANDOFF_ADVISORY_LOCK_KEY[0], "second": _HANDOFF_ADVISORY_LOCK_KEY[1]},
    )
    if acquired is not True:
        raise HandoffError("controlled application-schema handoff advisory lock is busy")


async def _verify_writer_fence_binding(
    connection: AsyncConnection,
    receipt: dict[str, Any],
    *,
    expected: dict[str, str],
) -> None:
    """Manager receipt가 현재 DB와 exact candidate/reference를 가리키는지 재확인한다."""

    image_revision = os.environ.get(_IMAGE_REVISION_ENV)
    image_id = os.environ.get(_HANDOFF_IMAGE_ID_ENV)
    if (
        image_revision != receipt["map_candidate_commit"]
        or image_id != receipt["map_candidate_image_id"]
    ):
        raise HandoffError("Docker Manager writer fence candidate does not match this Map image")
    if receipt["reference_manifest_sha256"] != _reference_manifest_sha256():
        raise HandoffError(
            "Docker Manager writer fence reference manifest does not match this Map image"
        )
    source = _reference_manifest()["source"]
    if receipt["postgres_image_id"] != source["container_image_id"]:
        raise HandoffError("Docker Manager writer fence database image does not match baseline")
    if (
        receipt["catalog_sha256"] != expected["catalog_sha256"]
        or receipt["seed_sha256"] != expected["seed_sha256"]
        or receipt["privileged_residue_sha256"] != expected["privileged_residue_sha256"]
        or receipt["pre_privileged_residue_sha256"]
        != expected["privileged_residue_sha256"]
        or receipt["runtime_invariants_sql_sha256"]
        != expected["runtime_invariants_sql_sha256"]
    ):
        raise HandoffError("Docker Manager writer fence receipt does not match baseline contract")
    observed = (
        await connection.execute(
            text(
                """
                SELECT current_database(),
                       (SELECT oid FROM pg_catalog.pg_database
                         WHERE datname = current_database()),
                       (SELECT datdba::regrole::text FROM pg_catalog.pg_database
                         WHERE datname = current_database()),
                       (SELECT system_identifier::text FROM pg_catalog.pg_control_system())
                """
            )
        )
    ).one()
    actual = (str(observed[0]), int(observed[1]), str(observed[2]), str(observed[3]))
    expected_database = (
        str(receipt["database_name"]),
        int(receipt["database_oid"]),
        str(receipt["database_owner"]),
        str(receipt["postgres_system_identifier"]),
    )
    if actual != expected_database:
        raise HandoffError("Docker Manager writer fence database identity does not match")


def _contract_sql(name: str) -> str:
    try:
        sql = _baseline_artifact(name).read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError("immutable application contract query is unavailable") from exc
    if not sql.strip():
        raise HandoffError("immutable application contract query is empty")
    return sql


@contextmanager
def _schema_owner_role_enabled() -> Any:
    previous = os.environ.get(_SCHEMA_OWNER_ROLE_ENV)
    os.environ[_SCHEMA_OWNER_ROLE_ENV] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_SCHEMA_OWNER_ROLE_ENV, None)
        else:
            os.environ[_SCHEMA_OWNER_ROLE_ENV] = previous


@contextmanager
def _one_shot_handoff_capability() -> Any:
    """root-only helper와 generic Alembic invocation을 분리하는 단발 capability."""

    if os.geteuid() != 0:
        raise HandoffError(
            "controlled application-schema handoff must run as root in its one-shot container"
        )
    try:
        _HANDOFF_CAPABILITY_DIRECTORY.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise HandoffError("handoff capability directory already exists") from exc
    capability_descriptor: int | None = None
    previous = os.environ.get(_HANDOFF_CAPABILITY_ENV)
    try:
        capability_descriptor = os.open(
            _HANDOFF_CAPABILITY_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
        )
        token = secrets.token_hex(32).encode("ascii")
        if os.write(capability_descriptor, token) != len(token):
            raise HandoffError("could not write complete handoff capability")
        os.fsync(capability_descriptor)
        os.fchmod(capability_descriptor, 0o400)
        os.close(capability_descriptor)
        capability_descriptor = None
        metadata = _HANDOFF_CAPABILITY_FILE.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or metadata.st_nlink != 1
        ):
            raise HandoffError("handoff capability file did not become root-private")
        os.environ[_HANDOFF_CAPABILITY_ENV] = str(_HANDOFF_CAPABILITY_FILE)
        yield
    except OSError as exc:
        raise HandoffError("could not create root-owned handoff capability") from exc
    finally:
        if capability_descriptor is not None:
            os.close(capability_descriptor)
        if previous is None:
            os.environ.pop(_HANDOFF_CAPABILITY_ENV, None)
        else:
            os.environ[_HANDOFF_CAPABILITY_ENV] = previous
        try:
            _HANDOFF_CAPABILITY_FILE.unlink(missing_ok=True)
            _HANDOFF_CAPABILITY_DIRECTORY.rmdir()
        except OSError:
            # stale root-only state는 다음 execution을 fail-close하게 만들고, 여기서
            # 원래 handoff 오류를 가리지 않는다.
            pass


async def _raw_version(connection: AsyncConnection) -> tuple[str, ...]:
    version_table = await connection.scalar(text("SELECT to_regclass('public.alembic_version')"))
    if version_table is None:
        return ()
    rows = await connection.execute(
        text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
    )
    return tuple(str(value) for value in rows.scalars())


async def _set_canonical_contract_gucs(connection: AsyncConnection) -> None:
    """deparse/formatting-sensitive catalog output을 session 설정에서 분리한다."""

    for statement in _CANONICAL_CONTRACT_GUC_STATEMENTS:
        await connection.execute(text(statement))


async def _contract_sha256(connection: AsyncConnection, contract_sql: str) -> str:
    """contract query의 ordered rows를 canonical UTF-8/LF stream으로 receipt화한다."""

    await _set_canonical_contract_gucs(connection)
    rows = await connection.execute(text(_contract_sql(contract_sql)))
    digest = hashlib.sha256()
    for item in rows.scalars():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


async def _catalog_sha256(connection: AsyncConnection) -> str:
    return await _contract_sha256(connection, _CATALOG_CONTRACT_SQL)


async def _seed_sha256(connection: AsyncConnection) -> str:
    return await _contract_sha256(connection, _SEED_CONTRACT_SQL)


async def _verify_final_role_contract(connection: AsyncConnection) -> None:
    prefixed_roles = tuple(
        str(role)
        for role in (
            await connection.scalars(
                text(
                    "SELECT rolname FROM pg_catalog.pg_roles "
                    "WHERE rolname LIKE 'ktm\\_%' ESCAPE '\\' ORDER BY rolname"
                )
            )
        ).all()
    )
    if prefixed_roles != tuple(sorted(_APPLICATION_ROLES)):
        raise HandoffError("final reserved application role inventory is not exact")

    rows = await connection.execute(
        text(
            """
            SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                   rolcreaterole, rolbypassrls, rolreplication, rolconnlimit,
                   COALESCE(rolvaliduntil::text, '<null>') AS rolvaliduntil
            FROM pg_catalog.pg_roles
            WHERE rolname = ANY(CAST(:roles AS text[]))
            ORDER BY rolname
            """
        ),
        {"roles": list(_APPLICATION_ROLES)},
    )
    role_rows = {
        str(row.rolname): (
            *(bool(value) for value in row[1:8]),
            int(row[8]),
            str(row[9]),
        )
        for row in rows
    }
    if set(role_rows) != set(_APPLICATION_ROLES):
        raise HandoffError("final application role inventory is not exact")
    expected_nologin = (
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        _EXPECTED_ROLE_CONNECTION_LIMIT,
        _EXPECTED_ROLE_VALID_UNTIL,
    )
    expected_login = (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        _EXPECTED_ROLE_CONNECTION_LIMIT,
        _EXPECTED_ROLE_VALID_UNTIL,
    )
    if any(role_rows[role] != expected_nologin for role in _NOLOGIN_ROLES) or any(
        role_rows[role] != expected_login for role in _LOGIN_ROLES
    ):
        raise HandoffError("final application role attributes are not exact")

    memberships = await connection.execute(
        text(
            """
            SELECT granted.rolname, member.rolname, membership.admin_option,
                   membership.inherit_option, membership.set_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
            WHERE granted.rolname LIKE 'ktm\\_%' ESCAPE '\\'
               OR member.rolname LIKE 'ktm\\_%' ESCAPE '\\'
            """
        ),
        {"roles": list(_APPLICATION_ROLES)},
    )
    actual_memberships = frozenset(
        (str(row[0]), str(row[1]), bool(row[2]), bool(row[3]), bool(row[4]))
        for row in memberships
    )
    if actual_memberships != _EXPECTED_MEMBERSHIPS:
        raise HandoffError("final application role membership graph is not exact")

    schemas = await connection.execute(
        text(
            """
            SELECT nspname, pg_get_userbyid(nspowner)
            FROM pg_catalog.pg_namespace
            WHERE nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
            """
        )
    )
    if {tuple(map(str, row)) for row in schemas} != {
        ("feature", _SCHEMA_OWNER_ROLE),
        ("provider_sync", _SCHEMA_OWNER_ROLE),
        ("ops", _SCHEMA_OWNER_ROLE),
        ("x_extension", _SCHEMA_OWNER_ROLE),
    }:
        raise HandoffError("final application schema owner contract is not exact")

    database_contract = await connection.execute(
        text(
            """
            SELECT pg_get_userbyid(database_row.datdba), coalesce(
                (
                    SELECT array_agg(setting.value ORDER BY setting.value)
                    FROM pg_catalog.pg_db_role_setting AS setting_row
                    CROSS JOIN LATERAL unnest(setting_row.setconfig) AS setting(value)
                    WHERE setting_row.setdatabase = database_row.oid
                      AND setting_row.setrole = 0
                ),
                ARRAY[]::text[]
            )
            FROM pg_catalog.pg_database AS database_row
            WHERE database_row.datname = current_database()
            """
        )
    )
    database_row = database_contract.one_or_none()
    if (
        database_row is None
        or str(database_row[0]) != _SCHEMA_OWNER_ROLE
        or tuple(str(value) for value in database_row[1]) != _EXPECTED_DATABASE_SEARCH_PATH
    ):
        raise HandoffError("final application database owner/search_path is not exact")

    role_settings = await connection.execute(
        text(
            """
            SELECT CASE WHEN setting_row.setdatabase = 0
                        THEN '<global>' ELSE '<current>' END,
                   CASE WHEN setting_row.setrole = 0
                        THEN '<all-roles>' ELSE setting_row.setrole::regrole::text END,
                   setting.value
            FROM pg_catalog.pg_db_role_setting AS setting_row
            CROSS JOIN LATERAL unnest(setting_row.setconfig) AS setting(value)
            WHERE (
                setting_row.setdatabase = 0
                AND (
                    setting_row.setrole = 0
                    OR setting_row.setrole IN (
                        SELECT role.oid
                        FROM pg_catalog.pg_roles AS role
                        WHERE role.rolname LIKE 'ktm\\_%' ESCAPE '\\'
                    )
                )
            ) OR (
                setting_row.setdatabase = (
                    SELECT oid FROM pg_catalog.pg_database
                    WHERE datname = current_database()
                )
                AND setting_row.setrole IN (
                    SELECT role.oid
                    FROM pg_catalog.pg_roles AS role
                    WHERE role.rolname LIKE 'ktm\\_%' ESCAPE '\\'
                )
            )
            ORDER BY 1, 2, 3
            """
        ),
        {"roles": list(_APPLICATION_ROLES)},
    )
    if tuple(tuple(map(str, row)) for row in role_settings) != ():
        raise HandoffError("final application role settings are not exact")

    extension_rows = await connection.execute(
        text(
            """
            SELECT extension.extname, namespace.nspname
            FROM pg_catalog.pg_extension AS extension
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
            """
        )
    )
    observed_extensions = {tuple(map(str, row)) for row in extension_rows}
    required_extensions = {
        ("fuzzystrmatch", "public"),
        ("plpgsql", "pg_catalog"),
        ("postgis", "x_extension"),
        ("pgcrypto", "x_extension"),
        ("pg_trgm", "x_extension"),
        ("pg_prewarm", "x_extension"),
    }
    if observed_extensions != required_extensions:
        raise HandoffError("final extension inventory contract is not exact")

    extension_owners = await connection.execute(
        text(
            """
            SELECT extension.extname, owner.rolname, owner.rolsuper
            FROM pg_catalog.pg_extension AS extension
            JOIN pg_catalog.pg_roles AS owner ON owner.oid = extension.extowner
            ORDER BY extension.extname
            """
        )
    )
    if any(
        not bool(row[2]) or str(row[1]).startswith("ktm_")
        for row in extension_owners
    ):
        raise HandoffError(
            "final extension owners must be non-application bootstrap superusers"
        )

    unexpected_postgis_auxiliary_schema = await connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
            "WHERE nspname IN ('topology', 'tiger'))"
        )
    )
    if bool(unexpected_postgis_auxiliary_schema):
        raise HandoffError(
            "final extension inventory must not include PostGIS auxiliary schemas"
        )

    extension_member_owner_violation = await connection.scalar(
        text(
            """
            WITH extension_member AS (
                SELECT dependency.classid, dependency.objid
                FROM pg_catalog.pg_depend AS dependency
                WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                  AND dependency.deptype = 'e'
                  AND dependency.objsubid = 0
            ), member_owner AS (
                SELECT member.classid, member.objid, relation.relowner AS owner_oid
                FROM extension_member AS member
                JOIN pg_catalog.pg_class AS relation
                  ON member.classid = 'pg_catalog.pg_class'::regclass
                 AND relation.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, routine.proowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_proc AS routine
                  ON member.classid = 'pg_catalog.pg_proc'::regclass
                 AND routine.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, type_row.typowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_type AS type_row
                  ON member.classid = 'pg_catalog.pg_type'::regclass
                 AND type_row.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, operator_row.oprowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_operator AS operator_row
                  ON member.classid = 'pg_catalog.pg_operator'::regclass
                 AND operator_row.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, family.opfowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_opfamily AS family
                  ON member.classid = 'pg_catalog.pg_opfamily'::regclass
                 AND family.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, class.opcowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_opclass AS class
                  ON member.classid = 'pg_catalog.pg_opclass'::regclass
                 AND class.oid = member.objid
                UNION ALL
                SELECT member.classid, member.objid, language.lanowner
                FROM extension_member AS member
                JOIN pg_catalog.pg_language AS language
                  ON member.classid = 'pg_catalog.pg_language'::regclass
                 AND language.oid = member.objid
            )
            SELECT EXISTS (
                SELECT 1
                FROM member_owner
                JOIN pg_catalog.pg_roles AS owner ON owner.oid = member_owner.owner_oid
                WHERE NOT owner.rolsuper
                   OR owner.rolname LIKE 'ktm\\_%' ESCAPE '\\'
            )
            """
        )
    )
    if bool(extension_member_owner_violation):
        raise HandoffError(
            "extension members must be owned by non-application bootstrap superusers"
        )

    unsupported_extension_member_class = await connection.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_depend AS dependency
                WHERE dependency.refclassid = 'pg_catalog.pg_extension'::regclass
                  AND dependency.deptype = 'e'
                  AND dependency.objsubid = 0
                  AND dependency.classid <> ALL (ARRAY[
                      'pg_catalog.pg_class'::regclass,
                      'pg_catalog.pg_proc'::regclass,
                      'pg_catalog.pg_type'::regclass,
                      'pg_catalog.pg_operator'::regclass,
                      'pg_catalog.pg_cast'::regclass,
                      'pg_catalog.pg_opfamily'::regclass,
                      'pg_catalog.pg_opclass'::regclass,
                      'pg_catalog.pg_language'::regclass
                  ])
            )
            """
        )
    )
    if bool(unsupported_extension_member_class):
        raise HandoffError("unsupported extension member class is not accepted")

    language_rows = await connection.execute(
        text("SELECT lanname FROM pg_catalog.pg_language ORDER BY lanname")
    )
    procedural_languages = tuple(str(value) for value in language_rows.scalars().all())
    if procedural_languages != ("c", "internal", "plpgsql", "sql"):
        raise HandoffError("final procedural language inventory is not exact")

    replication_topology = await connection.scalar(
        text(
            """
            SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_publication)
                OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_subscription AS subscription
                    WHERE subscription.subdbid = (
                        SELECT oid FROM pg_catalog.pg_database
                        WHERE datname = current_database()
                    )
                )
            """
        )
    )
    if bool(replication_topology):
        raise HandoffError("final replication topology must be empty")

    for role, expected_usage in _X_EXTENSION_USAGE.items():
        observed = await connection.scalar(
            text("SELECT has_schema_privilege(:role, 'x_extension', 'USAGE')"),
            {"role": role},
        )
        if bool(observed) is not expected_usage:
            raise HandoffError("final x_extension usage contract is not exact")


async def _verify_catalog_health(connection: AsyncConnection) -> None:
    invalid_indexes = await connection.scalar(
        text(
            """
            SELECT count(*)
            FROM pg_catalog.pg_index AS index_row
            JOIN pg_catalog.pg_class AS relation ON relation.oid = index_row.indrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
              AND NOT index_row.indisvalid
            """
        )
    )
    unvalidated_constraints = await connection.scalar(
        text(
            """
            SELECT count(*)
            FROM pg_catalog.pg_constraint AS con
            JOIN pg_catalog.pg_class AS relation ON relation.oid = con.conrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
              AND NOT con.convalidated
            """
        )
    )
    disabled_triggers = await connection.scalar(
        text(
            """
            SELECT count(*)
            FROM pg_catalog.pg_trigger AS trigger
            JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
              AND NOT trigger.tgisinternal
              -- `A`(ENABLE ALWAYS)는 source-entity lineage fence의 final contract다.
              -- `D`만 실제 disable이므로 transition을 막는다.
              AND trigger.tgenabled = 'D'
            """
        )
    )
    if any(
        int(value or 0) != 0
        for value in (invalid_indexes, unvalidated_constraints, disabled_triggers)
    ):
        raise HandoffError("application catalog has invalid index, constraint, or trigger state")


async def _verify_0236_data_closure(connection: AsyncConnection) -> None:
    counts = await connection.execute(
        text(
            """
            SELECT
              (
                SELECT count(*)
                FROM ops.poi_cache_target_snapshot_materials AS material
                WHERE material.compacted_at IS NOT NULL
                  AND material.compaction_drained_at IS NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ops.poi_cache_target_snapshot_material_items AS item
                    WHERE item.material_id = material.material_id
                  )
              ) AS empty_compacted_not_drained,
              (
                SELECT count(*)
                FROM ops.poi_cache_target_snapshot_materials AS material
                WHERE material.orphaned_at IS NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ops.poi_cache_target_snapshots AS receipt
                    WHERE receipt.material_id = material.material_id
                  )
              ) AS unmarked_orphan,
              (
                SELECT count(*)
                FROM ops.poi_cache_target_snapshot_materials AS material
                WHERE material.compaction_drained_at IS NOT NULL
                  AND EXISTS (
                    SELECT 1
                    FROM ops.poi_cache_target_snapshot_material_items AS item
                    WHERE item.material_id = material.material_id
                  )
              ) AS drained_with_items
            """
        )
    )
    row = counts.one()
    if any(int(value) != 0 for value in row):
        raise HandoffError("0236 compaction/orphan data semantic closure is not drained")


async def _verify_runtime_projection_invariants(connection: AsyncConnection) -> None:
    """변하는 live revision 값을 freeze하지 않고 `300` 필요 조건만 확인한다."""

    rows = await connection.execute(text(_contract_sql(_RUNTIME_INVARIANTS_SQL)))
    violations = tuple(str(value) for value in rows.scalars())
    if violations:
        raise HandoffError(
            "application runtime revision projection invariant failed: "
            + ", ".join(violations)
        )


async def _verify_runtime_alembic_version_read_contract(connection: AsyncConnection) -> None:
    """API/Dagster runtime이 raw head만 read할 수 있는 public metadata ACL을 고정한다."""

    accepted = await connection.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = 'alembic_version'
                  AND relation.relkind = 'r'
                  AND relation.relacl IS NOT NULL
                  AND has_table_privilege(
                      'ktm_feature_runtime', relation.oid, 'SELECT'
                  )
                  AND NOT has_table_privilege(
                      'ktm_feature_runtime', relation.oid,
                      'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM aclexplode(relation.relacl) AS privilege
                      WHERE NOT (
                          privilege.grantee = relation.relowner
                          OR (
                              privilege.grantee = 'ktm_feature_runtime'::regrole
                              AND privilege.privilege_type = 'SELECT'
                              AND NOT privilege.is_grantable
                          )
                      )
                  )
            )
            """
        )
    )
    if not bool(accepted):
        raise HandoffError("final public Alembic runtime-read ACL is not exact")


async def _grant_runtime_alembic_version_read(connection: AsyncConnection) -> None:
    """metadata-only handoff도 fresh root와 같은 public read boundary를 만든다."""

    await connection.execute(
        text("GRANT SELECT ON TABLE public.alembic_version TO ktm_feature_runtime")
    )


def _map_visible_contract_matches(
    observed: dict[str, str], reference: dict[str, str]
) -> bool:
    """schema-owner가 볼 수 있는 catalog/seed 두 축만 exact 비교한다."""

    return set(observed) == set(_MAP_VISIBLE_CONTRACT_KEYS) and all(
        observed[key] == reference[key] for key in _MAP_VISIBLE_CONTRACT_KEYS
    )


async def _preflight(connection: AsyncConnection, *, expected_head: str) -> dict[str, str]:
    """migrator가 직접 관측 가능한 application contract만 재확인한다.

    ``pg_user_mapping`` 같은 database-superuser 전용 residue는 의도적으로 이 session에
    노출하지 않는다. 그 축은 Docker Manager가 별도 superuser pre/post receipt로 닫고,
    여기서는 Manager가 image reference와 결박한 expected receipt만 받는다.
    """

    if await _raw_version(connection) != (expected_head,):
        raise HandoffError(f"application raw version must be exactly {expected_head}")
    await _verify_final_role_contract(connection)
    await _verify_catalog_health(connection)
    await _verify_0236_data_closure(connection)
    await _verify_runtime_projection_invariants(connection)
    if expected_head == _DESTINATION_HEAD:
        await _verify_runtime_alembic_version_read_contract(connection)
    return {
        "catalog_sha256": await _catalog_sha256(connection),
        "seed_sha256": await _seed_sha256(connection),
    }


def _stamp_on_existing_connection(connection: Connection, config: Config) -> None:
    """env.py에 existing sync connection을 주입해 outer transaction을 계속 사용한다."""

    config.attributes["connection"] = connection
    try:
        with _schema_owner_role_enabled(), _one_shot_handoff_capability():
            command.stamp(
                config,
                _DESTINATION_HEAD,
                purge=True,
                tag=_HANDOFF_TAG,
            )
    finally:
        config.attributes.pop("connection", None)


async def _handoff(writer_fence_receipt_path: str) -> dict[str, str]:
    dsn = os.environ.get("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN")
    if not dsn:
        raise HandoffError("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required")
    config = _config(dsn)
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (_DESTINATION_HEAD,):
        raise HandoffError("installed active Alembic graph head is not exactly 300")
    expected = _verify_reference_artifacts()
    writer_fence_receipt, writer_fence_receipt_sha256 = _load_writer_fence_receipt(
        writer_fence_receipt_path
    )

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            # 반드시 첫 SQL이다. superuser/DB owner가 이 executable로 접속해 `SET ROLE`만
            # 흉내 내는 우회는 여기서 metadata 변경 전에 거절된다.
            await _verify_migrator_session(connection)
            await _acquire_handoff_advisory_lock(connection)
            await _verify_writer_fence_binding(
                connection, writer_fence_receipt, expected=expected
            )
            await connection.execute(text(f"SET ROLE {_SCHEMA_OWNER_ROLE}"))
            # `pg_get_functiondef()`의 deparse가 session search_path에 따라 달라질 수
            # 있으므로, env.py가 stamp 안에서 쓰는 path를 preflight에도 먼저 고정한다.
            await connection.execute(text("SET search_path = public, x_extension"))
            before = await _preflight(connection, expected_head=_SOURCE_HEAD)
            if not _map_visible_contract_matches(before, expected):
                raise HandoffError(
                    "0236 source catalog or seed does not match the immutable 300 reference"
                )
            # receipt를 읽은 뒤 long catalog/data preflight가 실행됐다. raw metadata를
            # 바꾸기 바로 전에 fence 만료를 다시 확인한다.
            _require_unexpired_writer_fence(writer_fence_receipt)
            await connection.run_sync(_stamp_on_existing_connection, config)
            await _grant_runtime_alembic_version_read(connection)
            after = await _preflight(connection, expected_head=_DESTINATION_HEAD)
            if not _map_visible_contract_matches(after, expected):
                raise HandoffError(
                    "300 destination catalog or seed does not match the immutable reference"
                )
            # outer transaction commit 직전에도 살아 있어야 한다. 실패면 same transaction
            # rollback으로 source `0236` raw row가 보존된다.
            _require_unexpired_writer_fence(writer_fence_receipt)
    finally:
        await engine.dispose()

    return {
        "schema": _RESULT_SCHEMA,
        "outcome": "stamped",
        "source_head": _SOURCE_HEAD,
        "destination_head": _DESTINATION_HEAD,
        "expected_catalog_sha256": expected["catalog_sha256"],
        "expected_seed_sha256": expected["seed_sha256"],
        "expected_privileged_residue_sha256": expected["privileged_residue_sha256"],
        "pre_privileged_residue_sha256": writer_fence_receipt[
            "pre_privileged_residue_sha256"
        ],
        "pre_catalog_sha256": before["catalog_sha256"],
        "pre_seed_sha256": before["seed_sha256"],
        "post_catalog_sha256": after["catalog_sha256"],
        "post_seed_sha256": after["seed_sha256"],
        "writer_fence_receipt_sha256": writer_fence_receipt_sha256,
        "writer_fence_transaction_id": str(writer_fence_receipt["transaction_id"]),
    }


async def async_main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_args(arguments)
    try:
        result = await _handoff(parsed.writer_fence_receipt)
    except HandoffError as exc:
        print(f"controlled 0236-to-300 handoff refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
