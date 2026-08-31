#!/usr/local/bin/python -I
"""Manager/local fresh-init 전용 application ``300`` migration executable.

이 command는 daemon entrypoint의 "기동 중 Alembic" 경로가 아니다. 역할 bootstrap이
끝난 virgin DB에 대해 restricted migrator로 exact ``300`` root를 한 번 적용하고 closed
runtime ACL을 조정한 뒤 종료한다. bootstrap-superuser credential과 API/UI credential은
받지 않으며, raw version table이 이미 있으면 어떤 repair/stamp도 하지 않고 거부한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from alembic import command
from kortravelmap.infra.application_schema_head import (
    BASELINE_ROOT_REVISION,
    application_schema_head,
)
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

#: `command.upgrade(config, "head")`가 도달해야 하는 revision. graph에서 파생한다.
_DESTINATION_HEAD: Final = application_schema_head()
_MIGRATOR_DSN_ENV: Final = "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN"
_SCHEMA_OWNER_ROLE_ENV: Final = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"
_BOOTSTRAP_DSN_ENV: Final = "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN"
_PROFILE_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE"
_IMAGE_REVISION_ENV: Final = "KOR_TRAVEL_MAP_IMAGE_REVISION"
_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_FRESH_MIGRATE_IMAGE_ID"
_MIGRATOR_ROLE: Final = "ktm_feature_migrator"
_DATABASE_OWNER: Final = "ktm_feature_schema_owner"
_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])
_INSTALLED_BIN_DIR: Final = Path("/usr/local/bin")
_FENCE_PATH: Final = Path("/run/kor-travel-map-application-fresh-migrate/fence.json")
_FENCE_SCHEMA: Final = "kor-travel-docker-manager.map-fresh-300-migrate-fence.v2"
_FENCE_OPERATION: Final = "map-fresh-300"
_STATIC_CONTRACT_SCHEMA: Final = "kor-travel-map.application-baseline-contract.v1"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_DATABASE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPERATION_RECEIPT_TABLE: Final = "ops.application_schema_operation_receipts"
_OPERATION_KIND: Final = "application-root-300"
_RESULT_SCHEMA: Final = "kor-travel-map.application-fresh-300-root.v2"
_MISSING_RECEIPT_SCHEMA: Final = (
    "kor-travel-map.application-fresh-300-root-missing-receipt.v1"
)
_OPERATION_LOCK_KEY: Final = "kor-travel-map:application-schema-300-operation"
_FENCE_FIELDS: Final = frozenset(
    {
        "schema",
        "transaction_id",
        "operation_id",
        "journal_sha256",
        "journal_generation",
        "operation",
        "map_candidate_commit",
        "map_candidate_image_id",
        "postgres_image_id",
        "destination_head",
        "reference_manifest_sha256",
        "source_catalog_sha256",
        "destination_catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "source_alembic_version_sha256",
        "destination_alembic_version_sha256",
        "runtime_invariants_sql_sha256",
        "database_name",
        "database_oid",
        "database_owner",
        "postgres_system_identifier",
        "writer_fence_expires_at",
    }
)
_CONTRACT_FIELDS: Final = frozenset(
    {
        "schema",
        "application_head",
        "reference_manifest_sha256",
        "postgres_image_id",
        "source_catalog_sha256",
        "destination_catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "source_alembic_version_sha256",
        "destination_alembic_version_sha256",
        "runtime_invariants_sql_sha256",
    }
)
_PRE_ROOT_NOLOGIN_ROLES: Final = (
    "ktm_curation_admin_executor",
    "ktm_curation_audit_writer",
    "ktm_curation_command_owner",
    "ktm_curation_provider_executor",
    "ktm_feature_audit_writer",
    "ktm_feature_create_provider_executor",
    "ktm_feature_reference_reconciliation_service_executor",
    "ktm_feature_request_admin_executor",
    "ktm_feature_request_procedure_owner",
    "ktm_feature_request_service_executor",
    "ktm_feature_runtime",
    "ktm_feature_schema_owner",
    "ktm_feature_state_procedure_owner",
    "ktm_manual_feature_admin_executor",
    "ktm_manual_feature_procedure_owner",
    "ktm_manual_provider_dedup_admin_executor",
    "ktm_manual_provider_dedup_detector_executor",
    "ktm_manual_provider_dedup_procedure_owner",
)
_PRE_ROOT_LOGIN_ROLES: Final = (
    "ktm_feature_api_runtime",
    "ktm_feature_dagster_runtime",
    "ktm_feature_migrator",
)
_PRE_ROOT_MEMBERSHIPS: Final = (
    ("ktm_curation_admin_executor", "ktm_feature_api_runtime", False, True, False),
    ("ktm_curation_audit_writer", _DATABASE_OWNER, False, False, True),
    ("ktm_curation_command_owner", _DATABASE_OWNER, False, False, True),
    (
        "ktm_curation_provider_executor",
        "ktm_feature_dagster_runtime",
        False,
        True,
        False,
    ),
    ("ktm_feature_audit_writer", _DATABASE_OWNER, False, False, True),
    (
        "ktm_feature_create_provider_executor",
        "ktm_feature_dagster_runtime",
        False,
        True,
        False,
    ),
    (
        "ktm_feature_reference_reconciliation_service_executor",
        "ktm_feature_api_runtime",
        False,
        True,
        False,
    ),
    (
        "ktm_feature_request_admin_executor",
        "ktm_feature_api_runtime",
        False,
        True,
        False,
    ),
    ("ktm_feature_request_procedure_owner", _DATABASE_OWNER, False, False, True),
    (
        "ktm_feature_request_service_executor",
        "ktm_feature_api_runtime",
        False,
        True,
        False,
    ),
    ("ktm_feature_runtime", "ktm_feature_api_runtime", False, True, False),
    ("ktm_feature_runtime", "ktm_feature_dagster_runtime", False, True, False),
    (_DATABASE_OWNER, _MIGRATOR_ROLE, False, False, True),
    ("ktm_feature_state_procedure_owner", _DATABASE_OWNER, False, False, True),
    (
        "ktm_manual_feature_admin_executor",
        "ktm_feature_api_runtime",
        False,
        True,
        False,
    ),
    ("ktm_manual_feature_procedure_owner", _DATABASE_OWNER, False, False, True),
    (
        "ktm_manual_provider_dedup_admin_executor",
        "ktm_feature_api_runtime",
        False,
        True,
        False,
    ),
    (
        "ktm_manual_provider_dedup_detector_executor",
        "ktm_feature_dagster_runtime",
        False,
        True,
        False,
    ),
    (
        "ktm_manual_provider_dedup_procedure_owner",
        _DATABASE_OWNER,
        False,
        False,
        True,
    ),
)
_PRE_ROOT_SCHEMA_CREATORS: Final = (
    "ktm_curation_audit_writer",
    "ktm_curation_command_owner",
    "ktm_feature_audit_writer",
    "ktm_feature_request_procedure_owner",
    "ktm_feature_state_procedure_owner",
    "ktm_manual_feature_procedure_owner",
    "ktm_manual_provider_dedup_procedure_owner",
)
_PRE_ROOT_EXTENSION_SCHEMA_USERS: Final = (
    "ktm_curation_command_owner",
    "ktm_feature_api_runtime",
    "ktm_feature_dagster_runtime",
    "ktm_feature_runtime",
    "ktm_feature_state_procedure_owner",
    "ktm_manual_provider_dedup_procedure_owner",
)


class FreshMigrationError(RuntimeError):
    """fresh root migration의 fail-closed 오류."""


def _parse_args(arguments: Sequence[str] | None) -> tuple[str, UUID | None]:
    values = list(sys.argv[1:] if arguments is None else arguments)
    profile = os.environ.get(_PROFILE_ENV)
    if profile == "production":
        if values == ["migrate", "--writer-fence-receipt", str(_FENCE_PATH)]:
            return "migrate", None
        if len(values) == 3 and values[:2] == ["recover", "--operation-id"]:
            try:
                return "recover", UUID(values[2])
            except ValueError as exc:
                raise FreshMigrationError("fresh 300 recovery operation id is invalid") from exc
        if len(values) == 3 and values[:2] == ["probe-missing", "--operation-id"]:
            try:
                return "probe-missing", UUID(values[2])
            except ValueError as exc:
                raise FreshMigrationError("fresh 300 probe operation id is invalid") from exc
    elif profile == "local-dev":
        if values == ["migrate"]:
            return "migrate", None
    else:
        raise FreshMigrationError(f"{_PROFILE_ENV} must be exact production or local-dev")
    raise FreshMigrationError(
        "only the profile-fixed migrate/recover/probe operation is accepted"
    )


def _application_root() -> Path:
    for candidate in _APPLICATION_ROOT_CANDIDATES:
        if (candidate / "alembic.ini").is_file() and (candidate / "alembic").is_dir():
            return candidate
    raise FreshMigrationError("installed application Alembic root is unavailable")


def _config(dsn: str) -> Config:
    root = _application_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise FreshMigrationError(f"fresh 300 {label} digest is invalid")
    return value


def _static_contract_helper_path() -> Path:
    """installed image에서는 root-owned immutable contract helper만 허용한다."""

    if Path(__file__).resolve().parent != _INSTALLED_BIN_DIR:
        return _application_root() / "docker" / "application-schema-contract.py"
    path = _INSTALLED_BIN_DIR / "ktm-application-schema-contract"
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FreshMigrationError(
            "installed application baseline contract is unavailable"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o555
    ):
        raise FreshMigrationError("installed application baseline contract helper is unsafe")
    return path


def _load_static_contract_module() -> ModuleType:
    path = _static_contract_helper_path()
    try:
        loader = importlib.machinery.SourceFileLoader("application_schema_contract", str(path))
        spec = importlib.util.spec_from_loader("application_schema_contract", loader)
        if spec is None or spec.loader is None:
            raise ImportError("application schema contract loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError) as exc:
        raise FreshMigrationError("installed application baseline contract is unavailable") from exc


def _load_database_contract_module() -> ModuleType:
    """fresh-only read-only DB contract module만 고정 경로에서 읽는다."""

    installed = Path(__file__).resolve().parent == _INSTALLED_BIN_DIR
    path = (
        Path("/app/docker/application-schema-db-contract.py")
        if installed
        else _application_root() / "docker" / "application-schema-db-contract.py"
    )
    try:
        metadata = path.lstat()
        if installed and (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o444
            or metadata.st_nlink != 1
        ):
            raise OSError("unsafe installed database contract module")
        loader = importlib.machinery.SourceFileLoader(
            "application_schema_db_contract", str(path)
        )
        spec = importlib.util.spec_from_loader("application_schema_db_contract", loader)
        if spec is None or spec.loader is None:
            raise ImportError("application database contract loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError) as exc:
        raise FreshMigrationError(
            "installed application database contract is unavailable"
        ) from exc


def _static_contract() -> Mapping[str, str]:
    module = _load_static_contract_module()
    try:
        value = module.application_contract()
    except Exception as exc:
        raise FreshMigrationError("installed application baseline contract is invalid") from exc
    if not isinstance(value, Mapping) or set(value) != _CONTRACT_FIELDS:
        raise FreshMigrationError("installed application baseline contract field set is invalid")
    if value["schema"] != _STATIC_CONTRACT_SCHEMA or value["application_head"] != _DESTINATION_HEAD:
        raise FreshMigrationError("installed application baseline contract identity is invalid")
    for key in _CONTRACT_FIELDS - {"schema", "application_head", "postgres_image_id"}:
        _require_sha256(value[key], key)
    if not isinstance(value["postgres_image_id"], str) or not _IMAGE_ID_PATTERN.fullmatch(
        value["postgres_image_id"]
    ):
        raise FreshMigrationError("installed application baseline PostgreSQL image is invalid")
    return {key: str(item) for key, item in value.items()}


def _require_fixed_fence(
    *, allow_expired_for_read_only_probe: bool = False
) -> tuple[Mapping[str, Any], str]:
    """host root가 fixed mount에 발행한 production generation만 읽는다."""

    try:
        directory_metadata = _FENCE_PATH.parent.lstat()
        file_metadata = _FENCE_PATH.lstat()
    except OSError as exc:
        raise FreshMigrationError("fresh 300 migrate fence is unavailable") from exc
    if (
        not stat.S_ISDIR(directory_metadata.st_mode)
        or stat.S_ISLNK(directory_metadata.st_mode)
        or directory_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise FreshMigrationError("fresh 300 migrate fence directory is unsafe")
    if (
        not stat.S_ISREG(file_metadata.st_mode)
        or stat.S_ISLNK(file_metadata.st_mode)
        or file_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or file_metadata.st_nlink != 1
    ):
        raise FreshMigrationError("fresh 300 migrate fence file is unsafe")
    if Path(__file__).resolve().parent == _INSTALLED_BIN_DIR and (
        directory_metadata.st_uid != 0
        or file_metadata.st_uid != 0
        or stat.S_IMODE(file_metadata.st_mode) != 0o444
    ):
        raise FreshMigrationError("fresh 300 migrate fence must be root-owned mode 0444")
    try:
        descriptor = os.open(_FENCE_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (file_metadata.st_dev, file_metadata.st_ino)
            ):
                raise FreshMigrationError("fresh 300 migrate fence changed while opening")
            raw = os.read(descriptor, 262_144)
            if os.read(descriptor, 1):
                raise FreshMigrationError("fresh 300 migrate fence is too large")
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreshMigrationError("fresh 300 migrate fence is invalid") from exc
    if not isinstance(value, Mapping) or set(value) != _FENCE_FIELDS:
        raise FreshMigrationError("fresh 300 migrate fence field set is invalid")
    if value["schema"] != _FENCE_SCHEMA or value["operation"] != _FENCE_OPERATION:
        raise FreshMigrationError("fresh 300 migrate fence schema is invalid")
    try:
        UUID(str(value["transaction_id"]))
        UUID(str(value["operation_id"]))
    except (TypeError, ValueError) as exc:
        raise FreshMigrationError("fresh 300 migrate fence transaction id is invalid") from exc
    if type(value["journal_generation"]) is not int or value["journal_generation"] <= 0:
        raise FreshMigrationError("fresh 300 migrate fence generation is invalid")
    for key in (
        "journal_sha256",
        "reference_manifest_sha256",
        "source_catalog_sha256",
        "destination_catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "source_alembic_version_sha256",
        "destination_alembic_version_sha256",
        "runtime_invariants_sql_sha256",
    ):
        _require_sha256(value[key], key)
    if (
        not isinstance(value["map_candidate_commit"], str)
        or not _COMMIT_PATTERN.fullmatch(value["map_candidate_commit"])
        or not isinstance(value["map_candidate_image_id"], str)
        or not _IMAGE_ID_PATTERN.fullmatch(value["map_candidate_image_id"])
        or not isinstance(value["postgres_image_id"], str)
        or not _IMAGE_ID_PATTERN.fullmatch(value["postgres_image_id"])
        or value["destination_head"] != _DESTINATION_HEAD
        or not isinstance(value["database_name"], str)
        or not _DATABASE_PATTERN.fullmatch(value["database_name"])
        or type(value["database_oid"]) is not int
        or value["database_oid"] <= 0
        or value["database_owner"] != _DATABASE_OWNER
        or not isinstance(value["postgres_system_identifier"], str)
        or not value["postgres_system_identifier"].isdigit()
    ):
        raise FreshMigrationError("fresh 300 migrate fence identity is invalid")
    try:
        expires_at = datetime.fromisoformat(str(value["writer_fence_expires_at"]))
    except ValueError as exc:
        raise FreshMigrationError("fresh 300 migrate fence expiry is invalid") from exc
    if expires_at.tzinfo is None or (
        not allow_expired_for_read_only_probe
        and expires_at.astimezone(UTC) <= datetime.now(UTC)
    ):
        raise FreshMigrationError("fresh 300 migrate fence has expired")
    return value, hashlib.sha256(raw).hexdigest()


def _verify_fence_candidate(
    fence: Mapping[str, Any], contract: Mapping[str, str]
) -> None:
    expected = {
        "postgres_image_id": contract["postgres_image_id"],
        "destination_head": _DESTINATION_HEAD,
        "reference_manifest_sha256": contract["reference_manifest_sha256"],
        "source_catalog_sha256": contract["source_catalog_sha256"],
        "destination_catalog_sha256": contract["destination_catalog_sha256"],
        "seed_sha256": contract["seed_sha256"],
        "privileged_residue_sha256": contract["privileged_residue_sha256"],
        "source_alembic_version_sha256": contract["source_alembic_version_sha256"],
        "destination_alembic_version_sha256": contract[
            "destination_alembic_version_sha256"
        ],
        "runtime_invariants_sql_sha256": contract["runtime_invariants_sql_sha256"],
    }
    if any(fence[key] != value for key, value in expected.items()):
        raise FreshMigrationError("fresh 300 migrate fence baseline binding drifted")
    if (
        os.environ.get(_IMAGE_REVISION_ENV) != fence["map_candidate_commit"]
        or os.environ.get(_IMAGE_ID_ENV) != fence["map_candidate_image_id"]
    ):
        raise FreshMigrationError("fresh 300 migrate fence does not match this Map image")


async def _assert_virgin_version_table(connection: AsyncConnection) -> None:
    """blank row도 acceptance하지 않아 fresh action의 재실행을 차단한다."""

    version_table = await connection.scalar(
        text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    )
    if bool(version_table):
        raise FreshMigrationError(
            "fresh 300 migration requires no existing public.alembic_version table"
        )


async def _assert_restricted_migrator_session(
    connection: AsyncConnection, fence: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """DSN 이름이 아니라 실제 LOGIN principal을 migration 전에 고정한다.

    image가 non-root여도 ``MIGRATOR_PG_DSN``에 bootstrap superuser URL을 넣을 수
    있다. handoff와 마찬가지로 connection의 ``session_user``와 ``current_user``를
    모두 exact migrator로 닫아, superuser가 ``SET ROLE``만 흉내 내는 우회를
    metadata/version-table mutation 전에 거절한다.
    """

    try:
        row = (
            await connection.execute(
                text(
                    "SELECT session_user::text, current_user::text, role.rolsuper, "
                    "current_database(), database_row.oid, "
                    "pg_catalog.pg_get_userbyid(database_row.datdba), "
                    "(SELECT system_identifier::text "
                    "FROM pg_catalog.pg_control_system()) "
                    "FROM pg_catalog.pg_roles AS role "
                    "JOIN pg_catalog.pg_database AS database_row "
                    "ON database_row.datname = current_database() "
                    "WHERE role.rolname = session_user"
                )
            )
        ).one_or_none()
    except Exception as exc:  # DSN authority/host details는 로그에 내보내지 않는다.
        raise FreshMigrationError("fresh 300 migration cannot verify migrator session") from exc
    if (
        row is None
        or str(row[0]) != _MIGRATOR_ROLE
        or str(row[1]) != _MIGRATOR_ROLE
        or bool(row[2])
    ):
        raise FreshMigrationError("fresh 300 migration must connect as restricted migrator")
    identity = {
        "database_name": str(row[3]),
        "database_oid": int(row[4]),
        "database_owner": str(row[5]),
        "postgres_system_identifier": str(row[6]),
    }
    if fence is not None and any(fence[key] != value for key, value in identity.items()):
        raise FreshMigrationError("fresh 300 migrate fence database binding drifted")
    return identity


async def _assert_exact_destination_version(
    connection: AsyncConnection, expected_destination_facet: str
) -> str:
    try:
        contract_sql = (
            _application_root()
            / "alembic"
            / "baseline"
            / "application-destination-alembic-version.sql"
        ).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FreshMigrationError("installed destination Alembic facet is unavailable") from exc
    await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
    await connection.execute(text("SET search_path = public, x_extension"))
    rows = await connection.execute(
        text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
    )
    versions = tuple(str(value) for value in rows.scalars().all())
    facet_rows = await connection.execute(text(contract_sql))
    digest = hashlib.sha256()
    for item in facet_rows.scalars():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\n")
    destination_facet = digest.hexdigest()
    if versions != (_DESTINATION_HEAD,):
        raise FreshMigrationError(
            "fresh migration did not produce the exact expected raw revision"
        )
    if _DESTINATION_HEAD != BASELINE_ROOT_REVISION:
        # **head를 baseline root 너머로 올리려면 배포 계약 자체를 확장해야 한다.**
        #
        # sealed baseline(`alembic/baseline/*.sha256`)은 `300` 시점의 물리 catalog와
        # `alembic_version` facet을 고정한다. facet 계약 SQL은 조건에
        # `alembic_version = ARRAY['300']`을 담은 **단일 boolean**이라, head가 움직이면
        # 언제나 `…mismatch` 한 값만 낸다 — 옮겨갈 digest가 존재하지 않는다. catalog도
        # 새 migration이 객체를 더하는 순간 baseline digest와 어긋난다.
        #
        # 그래서 이 자리에서 "facet 대조를 건너뛰고 baseline digest를 receipt에 적는"
        # 우회를 한 적이 있는데, 그것은 실패를 downstream으로 미룰 뿐이었다.
        # `application-schema-fresh-finalize.py:418`과
        # `application-schema-final-permit.py:602`가 **live DB를 같은 baseline digest와**
        # 다시 대조하므로, fresh 설치가 통과해도 프로덕션 API/Dagster 컨테이너가
        # 기동을 거부한다.
        #
        # 올바른 해법은 계약을 baseline 너머로 **확장**하는 것이다 — baseline digest는
        # `300` 도달 순간에만 대조하고, 그 이후 상태는 fresh-install operation receipt가
        # 관측 digest를 정본으로 남겨 finalize·final-permit이 그것과 대조한다. receipt는
        # 이미 fence → journal → Manager evidence로 결박돼 있으므로 신뢰 사슬은 끊기지
        # 않는다. 그 작업이 끝나기 전까지는 **조용히 통과시키지 않는다.**
        raise FreshMigrationError(
            "application head is beyond the sealed baseline root; the deployment "
            "contract must be extended past the baseline before a migration can "
            "ship (see docs/reports/m03-child-migration-blast-radius-2026-08-31.md)"
        )
    if destination_facet != expected_destination_facet:
        raise FreshMigrationError(
            "fresh 300 migration destination facet does not match baseline"
        )
    return destination_facet


async def _acquire_operation_lock(connection: AsyncConnection) -> None:
    """root/finalize를 같은 DB transaction advisory lock으로 직렬화한다."""

    await connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    )


def _pre_root_attestation_sql() -> str:
    expected_roles = ", ".join(
        f"('{role}', {'TRUE' if role in _PRE_ROOT_LOGIN_ROLES else 'FALSE'})"
        for role in (*_PRE_ROOT_NOLOGIN_ROLES, *_PRE_ROOT_LOGIN_ROLES)
    )
    role_names = ", ".join(
        f"'{role}'" for role in (*_PRE_ROOT_NOLOGIN_ROLES, *_PRE_ROOT_LOGIN_ROLES)
    )
    expected_memberships = ", ".join(
        "(" + ", ".join(
            (
                f"'{granted_role}'",
                f"'{member_role}'",
                "TRUE" if admin_option else "FALSE",
                "TRUE" if inherit_option else "FALSE",
                "TRUE" if set_option else "FALSE",
            )
        ) + ")"
        for granted_role, member_role, admin_option, inherit_option, set_option in (
            _PRE_ROOT_MEMBERSHIPS
        )
    )
    expected_acl_rows = [
        ("public", "PUBLIC", "USAGE"),
        ("public", "pg_database_owner", "USAGE"),
        ("public", "pg_database_owner", "CREATE"),
    ]
    for schema_name in ("feature", "provider_sync", "ops"):
        expected_acl_rows.extend(
            (
                (schema_name, _DATABASE_OWNER, "USAGE"),
                (schema_name, _DATABASE_OWNER, "CREATE"),
            )
        )
        for role in _PRE_ROOT_SCHEMA_CREATORS:
            expected_acl_rows.extend(
                (
                    (schema_name, role, "USAGE"),
                    (schema_name, role, "CREATE"),
                )
            )
    expected_acl_rows.extend(
        (
            ("x_extension", _DATABASE_OWNER, "USAGE"),
            ("x_extension", _DATABASE_OWNER, "CREATE"),
        )
    )
    expected_acl_rows.extend(
        ("x_extension", role, "USAGE")
        for role in _PRE_ROOT_EXTENSION_SCHEMA_USERS
    )
    expected_acls = ", ".join(
        f"('{schema_name}', '{role}', '{privilege}')"
        for schema_name, role, privilege in expected_acl_rows
    )
    return f"""
WITH expected_role(rolname, can_login) AS (VALUES {expected_roles}),
expected_membership(
    granted_role, member_role, admin_option, inherit_option, set_option
) AS (VALUES {expected_memberships}),
actual_membership AS (
    SELECT granted.rolname AS granted_role,
           member.rolname AS member_role,
           membership.admin_option,
           membership.inherit_option,
           membership.set_option
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
    JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
    WHERE granted.rolname IN ({role_names}) OR member.rolname IN ({role_names})
),
expected_acl(schema_name, role_name, privilege_type, is_grantable) AS (
    SELECT schema_name, role_name, privilege_type, FALSE
    FROM (VALUES {expected_acls}) AS expected(
        schema_name, role_name, privilege_type
    )
),
actual_acl AS (
    SELECT namespace.nspname AS schema_name,
           CASE WHEN privilege.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
           privilege.privilege_type,
           privilege.is_grantable
    FROM pg_catalog.pg_namespace AS namespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS privilege
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = privilege.grantee
    WHERE namespace.nspname IN ('public', 'feature', 'provider_sync', 'ops', 'x_extension')
),
expected_extension(extension_name, schema_name) AS (VALUES
    ('fuzzystrmatch', 'public'),
    ('pg_prewarm', 'x_extension'),
    ('pg_trgm', 'x_extension'),
    ('pgcrypto', 'x_extension'),
    ('plpgsql', 'pg_catalog'),
    ('postgis', 'x_extension')
),
actual_extension AS (
    SELECT extension.extname AS extension_name,
           namespace.nspname AS schema_name,
           extension.extversion,
           available.default_version,
           owner.rolname AS owner_name,
           owner.rolsuper AS owner_is_superuser
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
    JOIN pg_catalog.pg_roles AS owner ON owner.oid = extension.extowner
    LEFT JOIN pg_catalog.pg_available_extensions AS available
      ON available.name = extension.extname
),
application_object AS (
    SELECT object.oid
    FROM pg_catalog.pg_class AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.relnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    UNION ALL
    SELECT object.oid
    FROM pg_catalog.pg_proc AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.pronamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
    UNION ALL
    SELECT object.oid
    FROM pg_catalog.pg_type AS object
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object.typnamespace
    WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops')
      AND object.typtype IN ('b', 'c', 'd', 'e', 'r')
)
SELECT CASE WHEN
    current_setting('transaction_read_only') = 'on'
    AND to_regclass('ops.application_schema_operation_receipts') IS NULL
    AND to_regclass('public.alembic_version') IS NULL
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_database AS target_database
        JOIN pg_catalog.pg_database AS template_database
          ON template_database.datname = 'template1'
        WHERE target_database.datname = current_database()
          AND target_database.datistemplate IS FALSE
          AND target_database.encoding = template_database.encoding
          AND target_database.datlocprovider = template_database.datlocprovider
          AND target_database.dattablespace = template_database.dattablespace
          AND target_database.datcollate IS NOT DISTINCT FROM template_database.datcollate
          AND target_database.datctype IS NOT DISTINCT FROM template_database.datctype
          AND target_database.daticulocale IS NOT DISTINCT FROM template_database.daticulocale
          AND target_database.daticurules IS NOT DISTINCT FROM template_database.daticurules
          AND target_database.datcollversion IS NOT DISTINCT FROM template_database.datcollversion
          AND target_database.datallowconn = template_database.datallowconn
          AND target_database.datconnlimit = template_database.datconnlimit
          AND target_database.datacl IS NULL
    )
    AND NOT EXISTS (
        SELECT 1
        FROM expected_role
        LEFT JOIN pg_catalog.pg_roles AS role USING (rolname)
        WHERE role.rolname IS NULL
           OR role.rolcanlogin IS DISTINCT FROM expected_role.can_login
           OR role.rolinherit
           OR role.rolsuper
           OR role.rolcreatedb
           OR role.rolcreaterole
           OR role.rolreplication
           OR role.rolbypassrls
           OR role.rolconnlimit <> -1
           OR role.rolvaliduntil IS DISTINCT FROM 'infinity'::timestamptz
           OR role.rolconfig IS NOT NULL
           OR (expected_role.can_login AND role.rolpassword IS NULL)
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles AS role
        WHERE role.rolname LIKE 'ktm\\_%' ESCAPE '\\'
          AND role.rolname NOT IN ({role_names})
    )
    AND NOT EXISTS (SELECT * FROM expected_membership EXCEPT SELECT * FROM actual_membership)
    AND NOT EXISTS (SELECT * FROM actual_membership EXCEPT SELECT * FROM expected_membership)
    AND NOT EXISTS (
        (SELECT namespace.nspname
         FROM pg_catalog.pg_namespace AS namespace
         WHERE namespace.nspname !~ '^pg_' AND namespace.nspname <> 'information_schema')
        EXCEPT VALUES ('public'), ('feature'), ('provider_sync'), ('ops'), ('x_extension')
    )
    AND NOT EXISTS (
        (VALUES ('public'), ('feature'), ('provider_sync'), ('ops'), ('x_extension'))
        EXCEPT
        (SELECT namespace.nspname
         FROM pg_catalog.pg_namespace AS namespace
         WHERE namespace.nspname !~ '^pg_' AND namespace.nspname <> 'information_schema')
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname = 'public'
          AND namespace.nspowner = 'pg_database_owner'::regrole
    )
    AND (
        SELECT count(*) FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname IN ('feature', 'provider_sync', 'ops', 'x_extension')
          AND namespace.nspowner = '{_DATABASE_OWNER}'::regrole
    ) = 4
    AND NOT EXISTS (SELECT * FROM expected_acl EXCEPT SELECT * FROM actual_acl)
    AND NOT EXISTS (SELECT * FROM actual_acl EXCEPT SELECT * FROM expected_acl)
    AND NOT EXISTS (SELECT * FROM expected_extension EXCEPT
                    SELECT extension_name, schema_name FROM actual_extension)
    AND NOT EXISTS (SELECT extension_name, schema_name FROM actual_extension EXCEPT
                    SELECT * FROM expected_extension)
    AND NOT EXISTS (
        SELECT 1 FROM actual_extension
        WHERE extversion IS DISTINCT FROM default_version
           OR NOT owner_is_superuser
           OR owner_name LIKE 'ktm\\_%' ESCAPE '\\'
    )
    AND NOT EXISTS (SELECT 1 FROM application_object)
    -- Large objects are database-wide and do not belong to feature/provider_sync/ops
    -- schemas.  A restricted migrator can create one and grant its ACL without leaving
    -- any relation/procedure/type behind, so exact fresh-root state must reject them
    -- explicitly rather than relying on the application-object inventory.
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_largeobject_metadata)
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl)
    AND (
        SELECT COALESCE(array_agg(language.lanname::text ORDER BY language.lanname),
                        ARRAY[]::text[])
        FROM pg_catalog.pg_language AS language
    ) IS NOT DISTINCT FROM ARRAY['c', 'internal', 'plpgsql', 'sql']::text[]
    AND (SELECT count(*) FROM pg_catalog.pg_db_role_setting AS setting_row
         WHERE setting_row.setdatabase = (
             SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
         )) = 1
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting_row
        WHERE setting_row.setdatabase = (
                  SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
              )
          AND setting_row.setrole = 0
          AND setting_row.setconfig = ARRAY['search_path=public, x_extension']::text[]
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting_row
        WHERE setting_row.setdatabase = 0
          AND (setting_row.setrole = 0 OR setting_row.setrole IN (
              SELECT role.oid FROM pg_catalog.pg_roles AS role
              WHERE role.rolname LIKE 'ktm\\_%' ESCAPE '\\'
          ))
    )
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_foreign_data_wrapper)
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_foreign_server)
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_publication)
    AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_subscription AS subscription
        WHERE subscription.subdbid = (
            SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
        )
    )
    AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger)
THEN 'kor-travel-map.application-fresh-300-pre-root.v1'
ELSE 'drift' END
"""


async def _assert_exact_pre_root_state(connection: AsyncConnection) -> str:
    try:
        marker = await connection.scalar(text(_pre_root_attestation_sql()))
    except Exception as exc:
        raise FreshMigrationError("fresh 300 pre-root state cannot be attested") from exc
    if marker != "kor-travel-map.application-fresh-300-pre-root.v1":
        raise FreshMigrationError("fresh 300 pre-root state is not exact")
    return str(marker)


async def _find_operation_receipt_if_present(
    connection: AsyncConnection, operation_id: UUID
) -> Mapping[str, Any] | None:
    try:
        if await connection.scalar(
            text(f"SELECT to_regclass('{_OPERATION_RECEIPT_TABLE}') IS NOT NULL")
        ) is not True:
            return None
        row = (
            await connection.execute(
                text(
                    f"SELECT operation_id::text, operation, result_schema "
                    f"FROM {_OPERATION_RECEIPT_TABLE} "
                    "WHERE operation_id = :operation_id"
                ),
                {"operation_id": operation_id},
            )
        ).mappings().one_or_none()
        return None if row is None else dict(row)
    except Exception as exc:
        raise FreshMigrationError("fresh 300 operation receipt cannot be inspected") from exc


def _upgrade_on_existing_connection(connection: Connection, config: Config) -> None:
    """Alembic root와 receipt insert가 하나의 outer transaction을 공유한다."""

    config.attributes["connection"] = connection
    try:
        command.upgrade(config, "head")
    finally:
        config.attributes.pop("connection", None)


async def _assert_application_receipts(
    connection: AsyncConnection,
    expected: Mapping[str, str],
    *,
    expected_catalogs: frozenset[str],
) -> tuple[str, str, str]:
    """full catalog/seed/version와 live projection invariant를 같은 snapshot에서 읽는다."""

    module = _load_database_contract_module()
    try:
        await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
        await connection.execute(text("SET search_path = public, x_extension"))
        catalog = await module.contract_sha256(
            connection, "application-catalog.sql"
        )
        seed = await module.contract_sha256(
            connection, "application-seed.sql"
        )
        destination = await module.contract_sha256(
            connection, "application-destination-alembic-version.sql"
        )
        await module.verify_runtime_projection_invariants(connection)
    except Exception as exc:
        raise FreshMigrationError("fresh 300 cannot verify committed application receipts") from exc
    if catalog not in expected_catalogs or seed != expected["seed_sha256"]:
        raise FreshMigrationError("fresh 300 catalog or seed receipt does not match baseline")
    if destination != expected["destination_alembic_version_sha256"]:
        raise FreshMigrationError("fresh 300 destination metadata receipt does not match baseline")
    return catalog, seed, destination


def _canonical_result_bytes(result: Mapping[str, Any]) -> bytes:
    return (json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n").encode()


async def _insert_operation_receipt(
    connection: AsyncConnection,
    *,
    fence: Mapping[str, Any],
    fence_sha256: str,
    contract: Mapping[str, str],
    database_identity: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    canonical = _canonical_result_bytes(result)
    inserted = await connection.scalar(
        text(
            f"INSERT INTO {_OPERATION_RECEIPT_TABLE} ("
            "operation_id, operation, result_schema, result_sha256, "
            "map_candidate_commit, map_candidate_image_id, postgres_image_id, "
            "writer_fence_receipt_sha256, journal_sha256, journal_generation, "
            "destination_head, database_name, database_oid, database_owner, "
            "postgres_system_identifier, result_payload) VALUES ("
            "CAST(:operation_id AS uuid), :operation, :result_schema, :result_sha256, "
            ":map_commit, :map_image, :postgres_image, :fence_sha256, :journal_sha256, "
            ":journal_generation, :destination_head, :database_name, :database_oid, "
            ":database_owner, :system_identifier, CAST(:result_payload AS jsonb)) "
            "RETURNING operation_id::text"
        ),
        {
            "operation_id": fence["operation_id"],
            "operation": _OPERATION_KIND,
            "result_schema": _RESULT_SCHEMA,
            "result_sha256": hashlib.sha256(canonical).hexdigest(),
            "map_commit": fence["map_candidate_commit"],
            "map_image": fence["map_candidate_image_id"],
            "postgres_image": contract["postgres_image_id"],
            "fence_sha256": fence_sha256,
            "journal_sha256": fence["journal_sha256"],
            "journal_generation": fence["journal_generation"],
            "destination_head": _DESTINATION_HEAD,
            **database_identity,
            "system_identifier": database_identity["postgres_system_identifier"],
            "result_payload": canonical.decode().rstrip("\n"),
        },
    )
    if inserted != fence["operation_id"]:
        raise FreshMigrationError("fresh 300 operation receipt was not committed")


async def _read_operation_receipt(
    connection: AsyncConnection, operation_id: UUID
) -> Mapping[str, Any]:
    try:
        row = (
            await connection.execute(
                text(
                    f"SELECT operation_id::text, operation, result_schema, result_sha256, "
                    "map_candidate_commit, map_candidate_image_id, postgres_image_id, "
                    "writer_fence_receipt_sha256, journal_sha256, journal_generation, "
                    "destination_head, database_name, database_oid, database_owner, "
                    f"postgres_system_identifier, result_payload FROM {_OPERATION_RECEIPT_TABLE} "
                    "WHERE operation_id = :operation_id"
                ),
                {"operation_id": operation_id},
            )
        ).mappings().one_or_none()
    except Exception as exc:
        raise FreshMigrationError("fresh 300 operation receipt is unavailable") from exc
    if row is None:
        raise FreshMigrationError("fresh 300 operation receipt does not exist")
    return dict(row)


async def _migrate() -> Mapping[str, Any]:
    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshMigrationError("bootstrap-superuser DSN must not enter fresh migration")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshMigrationError(f"{_MIGRATOR_DSN_ENV} is required")
    config = _config(dsn)
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (_DESTINATION_HEAD,):
        raise FreshMigrationError("installed active Alembic graph head is not exactly 300")

    profile = os.environ[_PROFILE_ENV]
    contract = _static_contract()
    fence: Mapping[str, Any] | None = None
    fence_sha256: str | None = None
    if profile == "production":
        fence, fence_sha256 = _require_fixed_fence()
        _verify_fence_candidate(fence, contract)
    temporary_environment = {
        "KOR_TRAVEL_MAP_PG_DSN": os.environ.get("KOR_TRAVEL_MAP_PG_DSN"),
        _SCHEMA_OWNER_ROLE_ENV: os.environ.get(_SCHEMA_OWNER_ROLE_ENV),
    }
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = dsn
    os.environ[_SCHEMA_OWNER_ROLE_ENV] = "true"
    try:
        engine = make_async_engine(dsn, pool_size=1)
        try:
            async with engine.begin() as connection:
                database_identity = await _assert_restricted_migrator_session(
                    connection, fence
                )
                await _acquire_operation_lock(connection)
                await _assert_virgin_version_table(connection)
                if fence is not None:
                    live_fence, live_fence_sha256 = _require_fixed_fence()
                    if live_fence != fence or live_fence_sha256 != fence_sha256:
                        raise FreshMigrationError(
                            "fresh 300 migrate fence changed before root migration"
                        )
                await connection.run_sync(_upgrade_on_existing_connection, config)
                destination_facet = await _assert_exact_destination_version(
                    connection, contract["destination_alembic_version_sha256"]
                )
                if fence is None:
                    result: Mapping[str, Any] = {
                        "schema": "kor-travel-map.application-fresh-300-migration.v2",
                        "outcome": "migrated",
                        "authorization": "local-dev",
                        "destination_head": _DESTINATION_HEAD,
                        "post_destination_alembic_version_sha256": destination_facet,
                    }
                else:
                    source_catalog, seed_sha256, destination_facet = (
                        await _assert_application_receipts(
                            connection,
                            contract,
                            expected_catalogs=frozenset(
                                {contract["source_catalog_sha256"]}
                            ),
                        )
                    )
                    live_fence, live_fence_sha256 = _require_fixed_fence()
                    if live_fence != fence or live_fence_sha256 != fence_sha256:
                        raise FreshMigrationError(
                            "fresh 300 migrate fence changed before receipt commit"
                        )
                    result = {
                        "schema": _RESULT_SCHEMA,
                        "outcome": "root-committed",
                        "authorization": "manager-fence",
                        "operation_id": fence["operation_id"],
                        "destination_head": _DESTINATION_HEAD,
                        "map_candidate_commit": fence["map_candidate_commit"],
                        "map_candidate_image_id": fence["map_candidate_image_id"],
                        "postgres_image_id": contract["postgres_image_id"],
                        "reference_manifest_sha256": contract[
                            "reference_manifest_sha256"
                        ],
                        "writer_fence_receipt_sha256": fence_sha256,
                        "writer_fence_transaction_id": fence["transaction_id"],
                        "journal_sha256": fence["journal_sha256"],
                        "journal_generation": fence["journal_generation"],
                        "database_identity": database_identity,
                        "post_source_catalog_sha256": source_catalog,
                        "post_seed_sha256": seed_sha256,
                        "expected_privileged_residue_sha256": contract[
                            "privileged_residue_sha256"
                        ],
                        "expected_destination_alembic_version_sha256": contract[
                            "destination_alembic_version_sha256"
                        ],
                        "post_destination_alembic_version_sha256": destination_facet,
                    }
                    await _insert_operation_receipt(
                        connection,
                        fence=fence,
                        fence_sha256=fence_sha256,
                        contract=contract,
                        database_identity=database_identity,
                        result=result,
                    )
                await connection.execute(text("RESET ROLE"))
                await _assert_restricted_migrator_session(connection, fence)
        finally:
            await engine.dispose()
        if fence is None:
            await reconcile_runtime_privileges()
        return result
    finally:
        for name, previous in temporary_environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


async def _recover(operation_id: UUID) -> Mapping[str, Any]:
    """exact operation row를 read-only로 재검증해 원 canonical result를 돌려준다."""

    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshMigrationError("bootstrap-superuser DSN must not enter fresh recovery")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshMigrationError(f"{_MIGRATOR_DSN_ENV} is required")
    contract = _static_contract()
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            live_identity = await _assert_restricted_migrator_session(connection, None)
            await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
            row = await _read_operation_receipt(connection, operation_id)
            payload = row["result_payload"]
            if not isinstance(payload, Mapping):
                raise FreshMigrationError("fresh 300 operation receipt payload is invalid")
            canonical = _canonical_result_bytes(payload)
            expected_columns = {
                "operation_id": str(operation_id),
                "operation": _OPERATION_KIND,
                "result_schema": _RESULT_SCHEMA,
                "result_sha256": hashlib.sha256(canonical).hexdigest(),
                "map_candidate_commit": os.environ.get(_IMAGE_REVISION_ENV),
                "map_candidate_image_id": os.environ.get(_IMAGE_ID_ENV),
                "postgres_image_id": contract["postgres_image_id"],
                "destination_head": _DESTINATION_HEAD,
                **live_identity,
            }
            if any(str(row[key]) != str(value) for key, value in expected_columns.items()):
                raise FreshMigrationError("fresh 300 operation receipt binding is invalid")
            if (
                payload.get("operation_id") != str(operation_id)
                or payload.get("writer_fence_receipt_sha256")
                != row["writer_fence_receipt_sha256"]
                or payload.get("journal_sha256") != row["journal_sha256"]
                or payload.get("journal_generation") != row["journal_generation"]
                or payload.get("database_identity") != live_identity
            ):
                raise FreshMigrationError("fresh 300 operation receipt payload drifted")
            await _assert_application_receipts(
                connection,
                contract,
                expected_catalogs=frozenset(
                    {
                        contract["source_catalog_sha256"],
                        contract["destination_catalog_sha256"],
                    }
                ),
            )
            return dict(payload)
    finally:
        await engine.dispose()


async def _probe_missing(operation_id: UUID) -> Mapping[str, Any]:
    """root 재실행이 안전한 exact bootstrap-complete pre-state만 증명한다."""

    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshMigrationError("bootstrap-superuser DSN must not enter fresh probe")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshMigrationError(f"{_MIGRATOR_DSN_ENV} is required")
    fence, fence_sha256 = _require_fixed_fence(
        allow_expired_for_read_only_probe=True
    )
    contract = _static_contract()
    _verify_fence_candidate(fence, contract)
    if str(operation_id) != fence["operation_id"]:
        raise FreshMigrationError("fresh 300 probe operation does not match fence")

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            database_identity = await _assert_restricted_migrator_session(
                connection, fence
            )
            # root와 finalize가 쓰는 동일 xact lock 뒤 한 read-only snapshot에서
            # 이전 container transaction의 commit/rollback 결과를 판정한다.
            await _acquire_operation_lock(connection)
            await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
            if await _find_operation_receipt_if_present(connection, operation_id) is not None:
                raise FreshMigrationError(
                    "fresh 300 probe found an existing operation receipt"
                )
            pre_root_state = await _assert_exact_pre_root_state(connection)
            active_fence, active_fence_sha256 = _require_fixed_fence(
                allow_expired_for_read_only_probe=True
            )
            if active_fence != fence or active_fence_sha256 != fence_sha256:
                raise FreshMigrationError("fresh 300 probe fence changed during attestation")
            return {
                "schema": _MISSING_RECEIPT_SCHEMA,
                "outcome": "receipt-missing-exact-prestate",
                "operation_id": str(operation_id),
                "destination_head": _DESTINATION_HEAD,
                "map_candidate_commit": fence["map_candidate_commit"],
                "map_candidate_image_id": fence["map_candidate_image_id"],
                "postgres_image_id": contract["postgres_image_id"],
                "reference_manifest_sha256": contract[
                    "reference_manifest_sha256"
                ],
                "writer_fence_receipt_sha256": fence_sha256,
                "writer_fence_transaction_id": fence["transaction_id"],
                "journal_sha256": fence["journal_sha256"],
                "journal_generation": fence["journal_generation"],
                "database_identity": database_identity,
                "pre_root_state_schema": pre_root_state,
                "expected_post_source_catalog_sha256": contract[
                    "source_catalog_sha256"
                ],
                "expected_post_seed_sha256": contract["seed_sha256"],
                "expected_post_destination_alembic_version_sha256": contract[
                    "destination_alembic_version_sha256"
                ],
            }
    finally:
        await engine.dispose()


async def async_main(arguments: Sequence[str] | None = None) -> int:
    try:
        operation, operation_id = _parse_args(arguments)
        if operation == "migrate":
            result = await _migrate()
        elif operation == "recover":
            result = await _recover(operation_id)  # type: ignore[arg-type]
        else:
            result = await _probe_missing(operation_id)  # type: ignore[arg-type]
    except FreshMigrationError as exc:
        print(f"fresh application 300 migration refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"fresh application 300 migration refused: operation failed ({exc!r})",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
