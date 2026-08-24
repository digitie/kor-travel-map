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

from alembic import command
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

_DESTINATION_HEAD: Final = "300"
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
_FENCE_FIELDS: Final = frozenset(
    {
        "schema",
        "transaction_id",
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


class FreshMigrationError(RuntimeError):
    """fresh root migration의 fail-closed 오류."""


def _parse_args(arguments: Sequence[str] | None) -> None:
    values = list(sys.argv[1:] if arguments is None else arguments)
    profile = os.environ.get(_PROFILE_ENV)
    if profile == "production":
        expected = ["migrate", "--writer-fence-receipt", str(_FENCE_PATH)]
    elif profile == "local-dev":
        expected = ["migrate"]
    else:
        raise FreshMigrationError(f"{_PROFILE_ENV} must be exact production or local-dev")
    if values != expected:
        raise FreshMigrationError("only the profile-fixed `migrate` operation is accepted")


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


def _load_static_contract_module() -> ModuleType:
    path = _INSTALLED_BIN_DIR / "ktm-application-schema-contract"
    if not path.is_file():
        path = _application_root() / "docker" / "application-schema-contract.py"
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


def _require_fixed_fence() -> tuple[Mapping[str, Any], str]:
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
    if expires_at.tzinfo is None or expires_at.astimezone(UTC) <= datetime.now(UTC):
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


async def _assert_virgin_version_table(dsn: str) -> None:
    """blank row도 acceptance하지 않아 fresh action의 재실행을 차단한다."""

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            version_table = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            )
    finally:
        await engine.dispose()
    if bool(version_table):
        raise FreshMigrationError(
            "fresh 300 migration requires no existing public.alembic_version table"
        )


async def _assert_restricted_migrator_session(
    dsn: str, fence: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """DSN 이름이 아니라 실제 LOGIN principal을 migration 전에 고정한다.

    image가 non-root여도 ``MIGRATOR_PG_DSN``에 bootstrap superuser URL을 넣을 수
    있다. handoff와 마찬가지로 connection의 ``session_user``와 ``current_user``를
    모두 exact migrator로 닫아, superuser가 ``SET ROLE``만 흉내 내는 우회를
    metadata/version-table mutation 전에 거절한다.
    """

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
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
    finally:
        await engine.dispose()
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
    dsn: str, expected_destination_facet: str
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
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
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
    finally:
        await engine.dispose()
    if versions != (_DESTINATION_HEAD,):
        raise FreshMigrationError("fresh 300 migration did not produce exact raw revision 300")
    if destination_facet != expected_destination_facet:
        raise FreshMigrationError("fresh 300 migration destination facet does not match baseline")
    return destination_facet


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
    database_identity = await _assert_restricted_migrator_session(dsn, fence)
    await _assert_virgin_version_table(dsn)
    if fence is not None:
        live_fence, live_fence_sha256 = _require_fixed_fence()
        if live_fence != fence or live_fence_sha256 != fence_sha256:
            raise FreshMigrationError("fresh 300 migrate fence changed before root migration")
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = dsn
    os.environ[_SCHEMA_OWNER_ROLE_ENV] = "true"
    await asyncio.to_thread(command.upgrade, config, "head")
    destination_facet = await _assert_exact_destination_version(
        dsn, contract["destination_alembic_version_sha256"]
    )
    if fence is None:
        await reconcile_runtime_privileges()
        destination_facet = await _assert_exact_destination_version(
            dsn, contract["destination_alembic_version_sha256"]
        )
        return {
            "schema": "kor-travel-map.application-fresh-300-migration.v2",
            "outcome": "migrated",
            "authorization": "local-dev",
            "destination_head": _DESTINATION_HEAD,
            "post_destination_alembic_version_sha256": destination_facet,
        }
    live_fence, live_fence_sha256 = _require_fixed_fence()
    if live_fence != fence or live_fence_sha256 != fence_sha256:
        raise FreshMigrationError("fresh 300 migrate fence changed before result publication")
    return {
        "schema": "kor-travel-map.application-fresh-300-root.v1",
        "outcome": "root-committed",
        "authorization": "manager-fence",
        "destination_head": _DESTINATION_HEAD,
        "map_candidate_commit": fence["map_candidate_commit"],
        "map_candidate_image_id": fence["map_candidate_image_id"],
        "reference_manifest_sha256": contract["reference_manifest_sha256"],
        "writer_fence_receipt_sha256": fence_sha256,
        "writer_fence_transaction_id": fence["transaction_id"],
        "journal_sha256": fence["journal_sha256"],
        "journal_generation": fence["journal_generation"],
        "database_identity": database_identity,
        "expected_destination_alembic_version_sha256": contract[
            "destination_alembic_version_sha256"
        ],
        "post_destination_alembic_version_sha256": destination_facet,
    }


async def async_main(arguments: Sequence[str] | None = None) -> int:
    try:
        _parse_args(arguments)
        result = await _migrate()
    except FreshMigrationError as exc:
        print(f"fresh application 300 migration refused: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("fresh application 300 migration refused: operation failed", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
