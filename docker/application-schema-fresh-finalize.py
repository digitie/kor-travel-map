#!/usr/local/bin/python
"""Docker Manager 전용 fresh ``300`` runtime ACL completion one-shot.

fresh root migration은 raw revision ``300``을 transaction으로 확정한 뒤 runtime ACL을
별도 transaction에서 reconcile한다. 그 두 번째 단계가 중단된 경우 API는 final permit
없이 fail-closed해야 하며, generic Alembic 재시도나 version-table 편집으로 복구해서는
안 된다. 이 executable은 Docker Manager가 root-owned fence로 candidate·DB·receipt를
재결박했을 때만 exact raw ``300`` DB의 idempotent ACL completion을 수행한다.
"""

from __future__ import annotations

import asyncio
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

from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

_DESTINATION_HEAD: Final = "300"
_MIGRATOR_DSN_ENV: Final = "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN"
_BOOTSTRAP_DSN_ENV: Final = "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN"
_IMAGE_REVISION_ENV: Final = "KOR_TRAVEL_MAP_IMAGE_REVISION"
_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_FRESH_FINALIZE_IMAGE_ID"
_MIGRATOR_ROLE: Final = "ktm_feature_migrator"
_DATABASE_OWNER: Final = "ktm_feature_schema_owner"
_FENCE_PATH: Final = Path("/run/kor-travel-map-application-fresh-finalize/fence.json")
_INSTALLED_BIN_DIR: Final = Path("/usr/local/bin")
_FENCE_SCHEMA: Final = "kor-travel-docker-manager.map-fresh-300-finalize-fence.v1"
_FENCE_OPERATION: Final = "map-fresh-300-finalize"
_STATIC_CONTRACT_SCHEMA: Final = "kor-travel-map.application-baseline-contract.v1"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_DATABASE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_FENCE_FIELDS: Final = frozenset(
    {
        "schema",
        "transaction_id",
        "journal_sha256",
        "operation",
        "map_candidate_commit",
        "map_candidate_image_id",
        "postgres_image_id",
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
_CONTRACT_FIELDS: Final = frozenset(
    {
        "schema",
        "application_head",
        "reference_manifest_sha256",
        "postgres_image_id",
        "catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "runtime_invariants_sql_sha256",
    }
)


class FreshFinalizeError(RuntimeError):
    """Manager fence 밖의 fresh completion을 fail-close한다."""


def _parse_args(arguments: Sequence[str] | None) -> None:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values != ["finalize", "--writer-fence-receipt", str(_FENCE_PATH)]:
        raise FreshFinalizeError("only the fixed fresh-300 finalize operation is accepted")


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise FreshFinalizeError(f"fresh finalize {label} digest is invalid")
    return value


def _require_fixed_fence() -> Mapping[str, Any]:
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
    except (TypeError, ValueError) as exc:
        raise FreshFinalizeError("fresh finalize writer fence transaction id is invalid") from exc
    for key in (
        "journal_sha256",
        "reference_manifest_sha256",
        "catalog_sha256",
        "seed_sha256",
        "privileged_residue_sha256",
        "pre_privileged_residue_sha256",
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
    if expires_at.tzinfo is None or expires_at.astimezone(UTC) <= datetime.now(UTC):
        raise FreshFinalizeError("fresh finalize writer fence has expired")
    return value


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
    dsn: str, fence: Mapping[str, Any]
) -> None:
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
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
    finally:
        await engine.dispose()
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


async def _assert_raw_300_and_receipts(dsn: str, expected: Mapping[str, str]) -> None:
    module = _load_handoff_contract_module()
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            # migrator는 NOINHERIT LOGIN이다. receipt query는 runtime principal 권한으로
            # 넓히지 않고, handoff와 같은 명시 schema-owner role과 canonical search_path에서
            # 실행한다. session_user는 앞 단계의 dedicated migrator assertion으로 유지된다.
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
            await module._verify_runtime_projection_invariants(  # type: ignore[attr-defined]
                connection
            )
    except Exception as exc:
        raise FreshFinalizeError("fresh finalize cannot verify raw 300 receipts") from exc
    finally:
        await engine.dispose()
    if versions != (_DESTINATION_HEAD,):
        raise FreshFinalizeError("fresh finalize requires exact raw revision 300")
    if catalog != expected["catalog_sha256"] or seed != expected["seed_sha256"]:
        raise FreshFinalizeError("fresh finalize catalog or seed receipt does not match baseline")


async def _finalize() -> None:
    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshFinalizeError("bootstrap-superuser DSN must not enter fresh finalize")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshFinalizeError(f"{_MIGRATOR_DSN_ENV} is required")
    fence = _require_fixed_fence()
    expected = _static_contract()
    if (
        os.environ.get(_IMAGE_REVISION_ENV) != fence["map_candidate_commit"]
        or os.environ.get(_IMAGE_ID_ENV) != fence["map_candidate_image_id"]
        or fence["postgres_image_id"] != expected["postgres_image_id"]
        or fence["reference_manifest_sha256"] != expected["reference_manifest_sha256"]
        or fence["catalog_sha256"] != expected["catalog_sha256"]
        or fence["seed_sha256"] != expected["seed_sha256"]
        or fence["privileged_residue_sha256"] != expected["privileged_residue_sha256"]
        or fence["pre_privileged_residue_sha256"] != expected["privileged_residue_sha256"]
        or fence["runtime_invariants_sql_sha256"]
        != expected["runtime_invariants_sql_sha256"]
    ):
        raise FreshFinalizeError("fresh finalize fence does not match candidate baseline")
    await _assert_restricted_migrator_and_database(dsn, fence)
    await _assert_raw_300_and_receipts(dsn, expected)
    # receipt/identity preflight가 오래 걸리는 동안 fence가 만료될 수 있다. 실제 ACL
    # transaction 직전에 same-byte·unexpired fence를 다시 읽어, 만료된 Manager writer
    # boundary 밖에서 권한을 변경하지 않는다.
    active_fence = _require_fixed_fence()
    if active_fence != fence:
        raise FreshFinalizeError("fresh finalize writer fence changed before completion")
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = dsn
    try:
        await reconcile_runtime_privileges()
    except Exception as exc:  # DB/ACL details는 operator stderr에 노출하지 않는다.
        raise FreshFinalizeError("fresh finalize runtime ACL reconciliation failed") from exc
    # reconcile는 자체 atomic transaction이다. late failure의 retry는 same fixed fence가
    # 아직 유효한 동안만 가능하며, Manager는 이 뒤 privileged postflight와 final permit을
    # 새로 발급해야 한다.
    refreshed_fence = _require_fixed_fence()
    if refreshed_fence != fence:
        raise FreshFinalizeError("fresh finalize writer fence changed during completion")
    await _assert_restricted_migrator_and_database(dsn, fence)
    await _assert_raw_300_and_receipts(dsn, expected)


async def async_main(arguments: Sequence[str] | None = None) -> int:
    try:
        _parse_args(arguments)
        await _finalize()
    except FreshFinalizeError as exc:
        print(f"fresh application 300 finalize refused: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": "kor-travel-map.application-fresh-300-finalize.v1",
                "outcome": "finalized",
                "destination_head": _DESTINATION_HEAD,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
