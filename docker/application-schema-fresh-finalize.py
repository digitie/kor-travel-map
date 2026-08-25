#!/usr/local/bin/python -I
"""Docker Manager 전용 fresh ``300`` runtime ACL completion one-shot.

fresh root migration은 raw revision ``300``을 transaction으로 확정한 뒤 runtime ACL을
별도 transaction에서 reconcile한다. 그 두 번째 단계가 중단된 경우 API는 final permit
없이 fail-closed해야 하며, generic Alembic 재시도나 version-table 편집으로 복구해서는
안 된다. 이 executable은 Docker Manager가 root-owned fence로 candidate·DB·receipt를
재결박했을 때만 exact raw ``300`` DB의 idempotent ACL completion을 수행한다.
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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import (
    reconcile_runtime_privileges_in_transaction,
)

_DESTINATION_HEAD: Final = "300"
_MIGRATOR_DSN_ENV: Final = "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN"
_BOOTSTRAP_DSN_ENV: Final = "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN"
_IMAGE_REVISION_ENV: Final = "KOR_TRAVEL_MAP_IMAGE_REVISION"
_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_FRESH_FINALIZE_IMAGE_ID"
_MIGRATOR_ROLE: Final = "ktm_feature_migrator"
_DATABASE_OWNER: Final = "ktm_feature_schema_owner"
_FENCE_PATH: Final = Path("/run/kor-travel-map-application-fresh-finalize/fence.json")
_INSTALLED_BIN_DIR: Final = Path("/usr/local/bin")
_FENCE_SCHEMA: Final = "kor-travel-docker-manager.map-fresh-300-finalize-fence.v3"
_FENCE_OPERATION: Final = "map-fresh-300-finalize"
_STATIC_CONTRACT_SCHEMA: Final = "kor-travel-map.application-baseline-contract.v1"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_DATABASE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPERATION_RECEIPT_TABLE: Final = "ops.application_schema_operation_receipts"
_OPERATION_KIND: Final = "application-finalize-300"
_ROOT_OPERATION_KIND: Final = "application-root-300"
_ROOT_RESULT_SCHEMA: Final = "kor-travel-map.application-fresh-300-root.v2"
_RESULT_SCHEMA: Final = "kor-travel-map.application-fresh-300-finalize.v4"
_MISSING_RECEIPT_SCHEMA: Final = (
    "kor-travel-map.application-fresh-300-finalize-missing-receipt.v1"
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
        "prior_fresh_migration_result_sha256",
        "prior_fresh_migration_fence_sha256",
        "prior_fresh_migration_transaction_id",
        "prior_fresh_migration_operation_id",
        "prior_fresh_migration_journal_sha256",
        "prior_fresh_migration_generation",
        "map_candidate_commit",
        "map_candidate_image_id",
        "postgres_image_id",
        "destination_head",
        "reference_manifest_sha256",
        "source_catalog_sha256",
        "destination_catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "pre_privileged_residue_sha256",
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


class FreshFinalizeError(RuntimeError):
    """Manager fence 밖의 fresh completion을 fail-close한다."""


def _parse_args(arguments: Sequence[str] | None) -> tuple[str, UUID | None]:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values == ["finalize", "--writer-fence-receipt", str(_FENCE_PATH)]:
        return "finalize", None
    if len(values) == 3 and values[:2] == ["recover", "--operation-id"]:
        try:
            return "recover", UUID(values[2])
        except ValueError as exc:
            raise FreshFinalizeError("fresh finalize recovery operation id is invalid") from exc
    if len(values) == 3 and values[:2] == ["probe-missing", "--operation-id"]:
        try:
            return "probe-missing", UUID(values[2])
        except ValueError as exc:
            raise FreshFinalizeError("fresh finalize probe operation id is invalid") from exc
    raise FreshFinalizeError(
        "only the fixed fresh-300 finalize/recover/probe operation is accepted"
    )


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise FreshFinalizeError(f"fresh finalize {label} digest is invalid")
    return value


def _require_fixed_fence(
    *, allow_expired_for_read_only_probe: bool = False
) -> tuple[Mapping[str, Any], str]:
    """host root가 publish한 fixed read-only fence만 source한다."""

    try:
        directory = _FENCE_PATH.parent
        directory_metadata = directory.lstat()
        file_metadata = _FENCE_PATH.lstat()
    except OSError as exc:
        raise FreshFinalizeError("fresh finalize writer fence is unavailable") from exc
    if (
        not stat.S_ISDIR(directory_metadata.st_mode)
        or stat.S_ISLNK(directory_metadata.st_mode)
        or directory_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise FreshFinalizeError("fresh finalize writer fence directory is unsafe")
    if (
        not stat.S_ISREG(file_metadata.st_mode)
        or stat.S_ISLNK(file_metadata.st_mode)
        or file_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or file_metadata.st_nlink != 1
    ):
        raise FreshFinalizeError("fresh finalize writer fence file is unsafe")
    # source-tree tests use a private current-UID fixture. Installed image에는 Manager가
    # 만든 root:root 0444 mount만 허용한다.
    if Path(__file__).resolve().parent == Path("/usr/local/bin") and (
        directory_metadata.st_uid != 0
        or file_metadata.st_uid != 0
        or stat.S_IMODE(file_metadata.st_mode) != 0o444
    ):
        raise FreshFinalizeError("fresh finalize writer fence must be root-owned mode 0444")
    try:
        descriptor = os.open(_FENCE_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino)
                != (file_metadata.st_dev, file_metadata.st_ino)
            ):
                raise FreshFinalizeError("fresh finalize writer fence changed while opening")
            raw = os.read(descriptor, 262_144)
            if os.read(descriptor, 1):
                raise FreshFinalizeError("fresh finalize writer fence is too large")
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreshFinalizeError("fresh finalize writer fence is invalid") from exc
    if not isinstance(value, Mapping) or set(value) != _FENCE_FIELDS:
        raise FreshFinalizeError("fresh finalize writer fence field set is invalid")
    if value["schema"] != _FENCE_SCHEMA or value["operation"] != _FENCE_OPERATION:
        raise FreshFinalizeError("fresh finalize writer fence schema is invalid")
    try:
        UUID(str(value["transaction_id"]))
        UUID(str(value["operation_id"]))
    except (TypeError, ValueError) as exc:
        raise FreshFinalizeError("fresh finalize writer fence transaction id is invalid") from exc
    try:
        UUID(str(value["prior_fresh_migration_transaction_id"]))
        UUID(str(value["prior_fresh_migration_operation_id"]))
    except (TypeError, ValueError) as exc:
        raise FreshFinalizeError("fresh finalize prior migration transaction is invalid") from exc
    if (
        type(value["journal_generation"]) is not int
        or type(value["prior_fresh_migration_generation"]) is not int
        or value["prior_fresh_migration_generation"] <= 0
        or value["journal_generation"] <= value["prior_fresh_migration_generation"]
    ):
        raise FreshFinalizeError("fresh finalize journal generation is invalid")
    for key in (
        "journal_sha256",
        "prior_fresh_migration_result_sha256",
        "prior_fresh_migration_fence_sha256",
        "prior_fresh_migration_journal_sha256",
        "reference_manifest_sha256",
        "source_catalog_sha256",
        "destination_catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "pre_privileged_residue_sha256",
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
        raise FreshFinalizeError("fresh finalize writer fence binding is invalid")
    try:
        expires_at = datetime.fromisoformat(str(value["writer_fence_expires_at"]))
    except ValueError as exc:
        raise FreshFinalizeError("fresh finalize writer fence expiry is invalid") from exc
    if expires_at.tzinfo is None or (
        not allow_expired_for_read_only_probe
        and expires_at.astimezone(UTC) <= datetime.now(UTC)
    ):
        raise FreshFinalizeError("fresh finalize writer fence has expired")
    return value, hashlib.sha256(raw).hexdigest()


def _helper_path(source_name: str, installed_name: str) -> Path:
    """source tree와 sealed image 모두에서 same-byte helper를 고정 경로로 연다."""

    if Path(__file__).resolve().parent == _INSTALLED_BIN_DIR:
        path = _INSTALLED_BIN_DIR / installed_name
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise FreshFinalizeError("installed application receipt helper is unavailable") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o555
        ):
            raise FreshFinalizeError("installed application receipt helper is unsafe")
        return path
    return Path(__file__).with_name(source_name)


def _load_static_contract_module() -> ModuleType:
    path = _helper_path("application-schema-contract.py", "ktm-application-schema-contract")
    try:
        loader = importlib.machinery.SourceFileLoader("application_schema_contract", str(path))
        spec = importlib.util.spec_from_loader("application_schema_contract", loader)
        if spec is None or spec.loader is None:
            raise ImportError("application schema contract loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise FreshFinalizeError("installed application baseline contract is unavailable") from exc
    return module


def _load_handoff_contract_module() -> ModuleType:
    """canonical SQL receipt/GUC implementation은 controlled handoff와 공유한다."""

    path = _helper_path(
        "transition-application-schema-0236-to-300.py", "ktm-application-schema-handoff"
    )
    try:
        loader = importlib.machinery.SourceFileLoader("application_schema_handoff", str(path))
        spec = importlib.util.spec_from_loader("application_schema_handoff", loader)
        if spec is None or spec.loader is None:
            raise ImportError("application schema handoff loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise FreshFinalizeError("installed application receipt contract is unavailable") from exc
    return module


def _static_contract() -> Mapping[str, str]:
    module = _load_static_contract_module()
    try:
        value = module.application_contract()
    except Exception as exc:
        raise FreshFinalizeError("installed application baseline contract is invalid") from exc
    if not isinstance(value, Mapping) or set(value) != _CONTRACT_FIELDS:
        raise FreshFinalizeError("installed application baseline contract field set is invalid")
    if value["schema"] != _STATIC_CONTRACT_SCHEMA or value["application_head"] != _DESTINATION_HEAD:
        raise FreshFinalizeError("installed application baseline contract identity is invalid")
    for key in _CONTRACT_FIELDS - {"schema", "application_head", "postgres_image_id"}:
        _require_sha256(value[key], key)
    if not isinstance(value["postgres_image_id"], str) or not _IMAGE_ID_PATTERN.fullmatch(
        value["postgres_image_id"]
    ):
        raise FreshFinalizeError("installed application baseline PostgreSQL image is invalid")
    return {key: str(item) for key, item in value.items()}


async def _assert_restricted_migrator_and_database(
    connection: AsyncConnection,
    fence: Mapping[str, Any],
) -> None:
    try:
        row = (
            await connection.execute(
                text(
                    "SELECT session_user::text, current_user::text, role.rolsuper, "
                    "current_database(), "
                    "(SELECT oid FROM pg_catalog.pg_database "
                    "WHERE datname = current_database()), "
                    "(SELECT datdba::regrole::text FROM pg_catalog.pg_database "
                    "WHERE datname = current_database()), "
                    "(SELECT system_identifier::text "
                    "FROM pg_catalog.pg_control_system()) "
                    "FROM pg_catalog.pg_roles AS role "
                    "WHERE role.rolname = session_user"
                )
            )
        ).one_or_none()
    except Exception as exc:  # DSN authority/host는 error path에 노출하지 않는다.
        raise FreshFinalizeError("fresh finalize cannot verify restricted DB session") from exc
    if (
        row is None
        or str(row[0]) != _MIGRATOR_ROLE
        or str(row[1]) != _MIGRATOR_ROLE
        or bool(row[2])
        or str(row[3]) != fence["database_name"]
        or int(row[4]) != fence["database_oid"]
        or str(row[5]) != fence["database_owner"]
        or str(row[6]) != fence["postgres_system_identifier"]
    ):
        raise FreshFinalizeError("fresh finalize DB session or identity is invalid")


async def _assert_raw_300_and_receipts(
    connection: AsyncConnection,
    expected: Mapping[str, str],
    *,
    expected_catalog_sha256: str,
) -> tuple[str, str, str]:
    module = _load_handoff_contract_module()
    try:
        # migrator는 NOINHERIT LOGIN이다. receipt query는 handoff와 같은 명시
        # schema-owner role과 canonical search_path에서 실행한다.
        await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
        await connection.execute(text("SET search_path = public, x_extension"))
        versions = tuple(
            str(item)
            for item in (
                await connection.scalars(
                    text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                )
            ).all()
        )
        catalog = await module._contract_sha256(  # type: ignore[attr-defined]
            connection, "application-catalog.sql"
        )
        seed = await module._contract_sha256(  # type: ignore[attr-defined]
            connection, "application-seed.sql"
        )
        destination_alembic_version = await module._contract_sha256(  # type: ignore[attr-defined]
            connection, "application-destination-alembic-version.sql"
        )
        await module._verify_runtime_projection_invariants(  # type: ignore[attr-defined]
            connection
        )
    except Exception as exc:
        raise FreshFinalizeError("fresh finalize cannot verify raw 300 receipts") from exc
    if versions != (_DESTINATION_HEAD,):
        raise FreshFinalizeError("fresh finalize requires exact raw revision 300")
    if catalog != expected_catalog_sha256 or seed != expected["seed_sha256"]:
        raise FreshFinalizeError(
            "fresh finalize catalog or seed receipt does not match baseline "
            f"(catalog={catalog}, seed={seed})"
        )
    if (
        destination_alembic_version
        != expected["destination_alembic_version_sha256"]
    ):
        raise FreshFinalizeError(
            "fresh finalize destination Alembic metadata facet does not match baseline"
        )
    return catalog, seed, destination_alembic_version


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


def _canonical_result_bytes(result: Mapping[str, Any]) -> bytes:
    return (json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n").encode()


async def _insert_operation_receipt(
    connection: AsyncConnection,
    *,
    fence: Mapping[str, Any],
    fence_sha256: str,
    expected: Mapping[str, str],
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
            "postgres_image": expected["postgres_image_id"],
            "fence_sha256": fence_sha256,
            "journal_sha256": fence["journal_sha256"],
            "journal_generation": fence["journal_generation"],
            "destination_head": _DESTINATION_HEAD,
            "database_name": fence["database_name"],
            "database_oid": fence["database_oid"],
            "database_owner": fence["database_owner"],
            "system_identifier": fence["postgres_system_identifier"],
            "result_payload": canonical.decode().rstrip("\n"),
        },
    )
    if inserted != fence["operation_id"]:
        raise FreshFinalizeError("fresh finalize operation receipt was not committed")


async def _read_operation_receipt(
    connection: AsyncConnection, operation_id: UUID
) -> Mapping[str, Any]:
    row = await _find_operation_receipt(connection, operation_id)
    if row is None:
        raise FreshFinalizeError("fresh finalize operation receipt does not exist")
    return row


async def _find_operation_receipt(
    connection: AsyncConnection, operation_id: UUID
) -> Mapping[str, Any] | None:
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
        raise FreshFinalizeError("fresh finalize operation receipt is unavailable") from exc
    return row


def _verify_fence_candidate(
    fence: Mapping[str, Any], expected: Mapping[str, str]
) -> None:
    if (
        os.environ.get(_IMAGE_REVISION_ENV) != fence["map_candidate_commit"]
        or os.environ.get(_IMAGE_ID_ENV) != fence["map_candidate_image_id"]
        or fence["postgres_image_id"] != expected["postgres_image_id"]
        or fence["reference_manifest_sha256"]
        != expected["reference_manifest_sha256"]
        or fence["source_catalog_sha256"] != expected["source_catalog_sha256"]
        or fence["destination_catalog_sha256"]
        != expected["destination_catalog_sha256"]
        or fence["seed_sha256"] != expected["seed_sha256"]
        or fence["privileged_residue_sha256"]
        != expected["privileged_residue_sha256"]
        or fence["pre_privileged_residue_sha256"]
        != expected["privileged_residue_sha256"]
        or fence["destination_alembic_version_sha256"]
        != expected["destination_alembic_version_sha256"]
        or fence["runtime_invariants_sql_sha256"]
        != expected["runtime_invariants_sql_sha256"]
    ):
        raise FreshFinalizeError("fresh finalize fence does not match candidate baseline")


async def _finalize() -> Mapping[str, Any]:
    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshFinalizeError("bootstrap-superuser DSN must not enter fresh finalize")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshFinalizeError(f"{_MIGRATOR_DSN_ENV} is required")
    fence, fence_sha256 = _require_fixed_fence()
    expected = _static_contract()
    _verify_fence_candidate(fence, expected)
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            # 이 transaction의 첫 SQL에서 restricted LOGIN과 DB identity를 고정한다.
            await _assert_restricted_migrator_and_database(connection, fence)
            await _acquire_operation_lock(connection)
            pre_catalog, pre_seed, _ = await _assert_raw_300_and_receipts(
                connection,
                expected,
                expected_catalog_sha256=expected["source_catalog_sha256"],
            )
            # source receipt가 오래 걸리는 동안 fence가 만료될 수 있다. 실제 ACL
            # mutation 직전에 same-byte·unexpired generation을 다시 읽는다.
            active_fence, active_fence_sha256 = _require_fixed_fence()
            if active_fence != fence or active_fence_sha256 != fence_sha256:
                raise FreshFinalizeError(
                    "fresh finalize writer fence changed before completion"
                )
            try:
                await reconcile_runtime_privileges_in_transaction(connection)
            except Exception as exc:  # DB/ACL details는 stderr에 노출하지 않는다.
                raise FreshFinalizeError(
                    "fresh finalize runtime ACL reconciliation failed"
                ) from exc
            post_catalog, post_seed, destination_facet = await _assert_raw_300_and_receipts(
                connection,
                expected,
                expected_catalog_sha256=expected["destination_catalog_sha256"],
            )
            # destination receipt와 최종 fence 확인까지 같은 outer transaction이다.
            # 여기서 실패하면 ACL과 catalog가 source facet으로 함께 rollback된다.
            completed_fence, completed_fence_sha256 = _require_fixed_fence()
            if completed_fence != fence or completed_fence_sha256 != fence_sha256:
                raise FreshFinalizeError(
                    "fresh finalize writer fence changed during completion"
                )
            result: Mapping[str, Any] = {
                "schema": _RESULT_SCHEMA,
                "outcome": "finalized",
                "operation_id": fence["operation_id"],
                "destination_head": _DESTINATION_HEAD,
                "map_candidate_commit": fence["map_candidate_commit"],
                "map_candidate_image_id": fence["map_candidate_image_id"],
                "postgres_image_id": expected["postgres_image_id"],
                "reference_manifest_sha256": expected["reference_manifest_sha256"],
                "writer_fence_receipt_sha256": fence_sha256,
                "writer_fence_transaction_id": fence["transaction_id"],
                "journal_sha256": fence["journal_sha256"],
                "journal_generation": fence["journal_generation"],
                "database_identity": {
                    "database_name": fence["database_name"],
                    "database_oid": fence["database_oid"],
                    "database_owner": fence["database_owner"],
                    "postgres_system_identifier": fence["postgres_system_identifier"],
                },
                "prior_fresh_migration_result_sha256": fence[
                    "prior_fresh_migration_result_sha256"
                ],
                "prior_fresh_migration_fence_sha256": fence[
                    "prior_fresh_migration_fence_sha256"
                ],
                "prior_fresh_migration_transaction_id": fence[
                    "prior_fresh_migration_transaction_id"
                ],
                "prior_fresh_migration_operation_id": fence[
                    "prior_fresh_migration_operation_id"
                ],
                "prior_fresh_migration_journal_sha256": fence[
                    "prior_fresh_migration_journal_sha256"
                ],
                "prior_fresh_migration_generation": fence[
                    "prior_fresh_migration_generation"
                ],
                "pre_source_catalog_sha256": pre_catalog,
                "pre_seed_sha256": pre_seed,
                "post_destination_catalog_sha256": post_catalog,
                "post_seed_sha256": post_seed,
                "expected_privileged_residue_sha256": expected[
                    "privileged_residue_sha256"
                ],
                "post_destination_alembic_version_sha256": destination_facet,
            }
            await _insert_operation_receipt(
                connection,
                fence=fence,
                fence_sha256=fence_sha256,
                expected=expected,
                result=result,
            )
            await connection.execute(text("RESET ROLE"))
            await _assert_restricted_migrator_and_database(connection, fence)
    finally:
        await engine.dispose()
    return result


async def _recover(operation_id: UUID) -> Mapping[str, Any]:
    """exact finalize row를 read-only로 재검증해 원 canonical result를 돌려준다."""

    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshFinalizeError("bootstrap-superuser DSN must not enter fresh recovery")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshFinalizeError(f"{_MIGRATOR_DSN_ENV} is required")
    expected = _static_contract()
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            # fence는 응답 유실 뒤 만료될 수 있으므로 row의 DB identity를 live session과
            # 직접 비교한다. mutation 권한은 쓰지 않는다.
            row = await connection.execute(
                text(
                    "SELECT session_user::text, current_user::text, role.rolsuper, "
                    "current_database(), database_row.oid, "
                    "pg_catalog.pg_get_userbyid(database_row.datdba), "
                    "(SELECT system_identifier::text FROM pg_catalog.pg_control_system()) "
                    "FROM pg_catalog.pg_roles AS role "
                    "JOIN pg_catalog.pg_database AS database_row "
                    "ON database_row.datname = current_database() "
                    "WHERE role.rolname = session_user"
                )
            )
            identity_row = row.one_or_none()
            if (
                identity_row is None
                or str(identity_row[0]) != _MIGRATOR_ROLE
                or str(identity_row[1]) != _MIGRATOR_ROLE
                or bool(identity_row[2])
            ):
                raise FreshFinalizeError("fresh finalize recovery session is invalid")
            live_identity = {
                "database_name": str(identity_row[3]),
                "database_oid": int(identity_row[4]),
                "database_owner": str(identity_row[5]),
                "postgres_system_identifier": str(identity_row[6]),
            }
            await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
            receipt = await _read_operation_receipt(connection, operation_id)
            payload = receipt["result_payload"]
            if not isinstance(payload, Mapping):
                raise FreshFinalizeError("fresh finalize receipt payload is invalid")
            canonical = _canonical_result_bytes(payload)
            expected_columns = {
                "operation_id": str(operation_id),
                "operation": _OPERATION_KIND,
                "result_schema": _RESULT_SCHEMA,
                "result_sha256": hashlib.sha256(canonical).hexdigest(),
                "map_candidate_commit": os.environ.get(_IMAGE_REVISION_ENV),
                "map_candidate_image_id": os.environ.get(_IMAGE_ID_ENV),
                "postgres_image_id": expected["postgres_image_id"],
                "destination_head": _DESTINATION_HEAD,
                **live_identity,
            }
            if any(
                str(receipt[key]) != str(value) for key, value in expected_columns.items()
            ):
                raise FreshFinalizeError("fresh finalize operation receipt binding is invalid")
            if (
                payload.get("operation_id") != str(operation_id)
                or payload.get("writer_fence_receipt_sha256")
                != receipt["writer_fence_receipt_sha256"]
                or payload.get("journal_sha256") != receipt["journal_sha256"]
                or payload.get("journal_generation") != receipt["journal_generation"]
                or payload.get("database_identity") != live_identity
            ):
                raise FreshFinalizeError("fresh finalize operation receipt payload drifted")
            catalog, seed, _ = await _assert_raw_300_and_receipts(
                connection,
                expected,
                expected_catalog_sha256=expected["destination_catalog_sha256"],
            )
            if (
                payload.get("post_destination_catalog_sha256") != catalog
                or payload.get("post_seed_sha256") != seed
            ):
                raise FreshFinalizeError("fresh finalize live attestation drifted")
            return dict(payload)
    finally:
        await engine.dispose()


async def _probe_missing(operation_id: UUID) -> Mapping[str, Any]:
    """finalize 재실행이 안전한 exact source pre-state만 typed evidence로 돌려준다."""

    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshFinalizeError("bootstrap-superuser DSN must not enter fresh probe")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshFinalizeError(f"{_MIGRATOR_DSN_ENV} is required")
    fence, _ = _require_fixed_fence(allow_expired_for_read_only_probe=True)
    expected = _static_contract()
    _verify_fence_candidate(fence, expected)
    if str(operation_id) != fence["operation_id"]:
        raise FreshFinalizeError("fresh finalize probe operation does not match fence")

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await _assert_restricted_migrator_and_database(connection, fence)
            # 응답 유실로 이전 container가 아직 transaction을 끝내는 중이어도 같은
            # advisory lock 뒤의 한 snapshot에서 committed/rolled-back 상태를 판정한다.
            await _acquire_operation_lock(connection)
            await connection.execute(text(f"SET ROLE {_DATABASE_OWNER}"))
            if await _find_operation_receipt(connection, operation_id) is not None:
                raise FreshFinalizeError(
                    "fresh finalize probe found an existing operation receipt"
                )

            prior_operation_id = UUID(
                str(fence["prior_fresh_migration_operation_id"])
            )
            prior = await _read_operation_receipt(connection, prior_operation_id)
            prior_payload = prior["result_payload"]
            if not isinstance(prior_payload, Mapping):
                raise FreshFinalizeError("fresh finalize prior receipt payload is invalid")
            prior_canonical = _canonical_result_bytes(prior_payload)
            live_identity = {
                "database_name": fence["database_name"],
                "database_oid": fence["database_oid"],
                "database_owner": fence["database_owner"],
                "postgres_system_identifier": fence["postgres_system_identifier"],
            }
            expected_prior_columns = {
                "operation_id": str(prior_operation_id),
                "operation": _ROOT_OPERATION_KIND,
                "result_schema": _ROOT_RESULT_SCHEMA,
                "result_sha256": fence["prior_fresh_migration_result_sha256"],
                "map_candidate_commit": fence["map_candidate_commit"],
                "map_candidate_image_id": fence["map_candidate_image_id"],
                "postgres_image_id": expected["postgres_image_id"],
                "destination_head": _DESTINATION_HEAD,
                **live_identity,
            }
            if (
                hashlib.sha256(prior_canonical).hexdigest()
                != fence["prior_fresh_migration_result_sha256"]
                or any(
                    str(prior[key]) != str(value)
                    for key, value in expected_prior_columns.items()
                )
                or prior_payload.get("operation_id") != str(prior_operation_id)
                or prior_payload.get("writer_fence_receipt_sha256")
                != fence["prior_fresh_migration_fence_sha256"]
                or prior_payload.get("writer_fence_transaction_id")
                != fence["prior_fresh_migration_transaction_id"]
                or prior_payload.get("journal_sha256")
                != fence["prior_fresh_migration_journal_sha256"]
                or prior_payload.get("journal_generation")
                != fence["prior_fresh_migration_generation"]
                or prior_payload.get("database_identity") != live_identity
            ):
                raise FreshFinalizeError("fresh finalize prior receipt binding is invalid")

            catalog, seed, destination_facet = await _assert_raw_300_and_receipts(
                connection,
                expected,
                expected_catalog_sha256=expected["source_catalog_sha256"],
            )
            return {
                "schema": _MISSING_RECEIPT_SCHEMA,
                "outcome": "receipt-missing-exact-prestate",
                "operation_id": str(operation_id),
                "prior_fresh_migration_operation_id": str(prior_operation_id),
                "prior_fresh_migration_result_sha256": prior[
                    "result_sha256"
                ],
                "destination_head": _DESTINATION_HEAD,
                "map_candidate_commit": fence["map_candidate_commit"],
                "map_candidate_image_id": fence["map_candidate_image_id"],
                "postgres_image_id": expected["postgres_image_id"],
                "reference_manifest_sha256": expected[
                    "reference_manifest_sha256"
                ],
                "database_identity": live_identity,
                "pre_source_catalog_sha256": catalog,
                "pre_seed_sha256": seed,
                "pre_destination_alembic_version_sha256": destination_facet,
            }
    finally:
        await engine.dispose()


async def async_main(arguments: Sequence[str] | None = None) -> int:
    try:
        operation, operation_id = _parse_args(arguments)
        if operation == "finalize":
            result = await _finalize()
        elif operation == "recover":
            result = await _recover(operation_id)  # type: ignore[arg-type]
        else:
            result = await _probe_missing(operation_id)  # type: ignore[arg-type]
    except FreshFinalizeError as exc:
        print(f"fresh application 300 finalize refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
