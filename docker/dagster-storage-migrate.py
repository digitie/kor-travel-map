#!/usr/local/bin/python -I
"""후보 이미지 안에서 Dagster metadata storage를 attest·migrate한다.

이 파일은 의도적으로 ``kortravelmap`` package를 import하지 않는다. migration-only
경로가 Map code location, application settings 또는 application Alembic chain을 읽으면
candidate storage head의 정본이 다시 흐려진다. 여기서 읽는 migration graph는 이미지에
설치된 Dagster package 자체뿐이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster._core.storage.sql import ALEMBIC_SCRIPTS_LOCATION
from sqlalchemy import create_engine, text

_DAGSTER_HOME_ENV: Final = "DAGSTER_HOME"
_DAGSTER_PG_URL_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_PG_URL"
_DAGSTER_PROFILE_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_PROFILE"
_PERMIT_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_STORAGE_PERMIT_IMAGE_ID"
_PERMIT_PAIRED_RECEIPT_ENV: Final = (
    "KOR_TRAVEL_MAP_DAGSTER_STORAGE_PAIRED_RECEIPT_SHA256"
)
_PERMIT_CONFIG_SHA256_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_STORAGE_CONFIG_SHA256"
_DAGSTER_HOME: Final = Path("/opt/dagster/dagster_home")
_DAGSTER_YAML: Final = _DAGSTER_HOME / "dagster.yaml"
_PERMIT_PATH: Final = Path("/run/kor-travel-map-dagster-storage-permit/permit.json")
_PERMIT_SCHEMA: Final = "kor-travel-map.dagster-storage-database-permit.v1"
_IDENTITY_SCHEMA: Final = "kor-travel-map.dagster-storage-database-identity.v1"
_HEAD_SCHEMA: Final = "kor-travel-map.dagster-storage-head.v1"
_MIGRATE_SCHEMA: Final = "kor-travel-map.dagster-storage-migration.v1"
_ERROR_SCHEMA: Final = "kor-travel-map.dagster-storage-migration-error.v1"
_ISOLATED_PYTHON: Final = "/usr/local/bin/python"
_DAGSTER_EXECUTABLE: Final = "/usr/local/bin/dagster"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATABASE_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_ROLE_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_PERMIT_FIELDS: Final = frozenset(
    {"schema", "authority", "candidate", "dagster_database", "application_database"}
)
_DAGSTER_DATABASE_FIELDS: Final = frozenset(
    {"system_identifier", "name", "oid", "owner", "login_role"}
)
_APPLICATION_DATABASE_FIELDS: Final = frozenset(
    {"system_identifier", "name", "oid", "owner"}
)
_CANDIDATE_FIELDS: Final = frozenset(
    {"dagster_image_id", "paired_candidate_build_receipt_sha256", "dagster_config_sha256"}
)


class DagsterStorageMigrationError(RuntimeError):
    """외부 입력을 반사하지 않는 migration-only 계약 오류."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _dagster_storage_head() -> str:
    """실행 중인 이미지가 설치한 Dagster storage graph의 단일 head를 읽는다."""
    try:
        config = Config()
        config.set_main_option("script_location", ALEMBIC_SCRIPTS_LOCATION)
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_head_unavailable") from exc

    if len(heads) != 1:
        raise DagsterStorageMigrationError("dagster_storage_head_ambiguous")
    return heads[0]


def _validate_dagster_config(raw: bytes) -> None:
    """Dagster storage target이 canonical DSN env 외에는 읽지 못하게 한다."""
    try:
        config = yaml.safe_load(raw)
        storage = config["storage"]
        postgres = storage["postgres"]
    except (KeyError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        raise DagsterStorageMigrationError("invalid_dagster_yaml") from exc
    if storage != {
        "postgres": {"postgres_url": {"env": _DAGSTER_PG_URL_ENV}}
    } or postgres != {"postgres_url": {"env": _DAGSTER_PG_URL_ENV}}:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")


def _safe_dagster_config(environment: Mapping[str, str]) -> str:
    """봉인된 canonical config가 metadata DSN env 하나만 읽는지 확인한다."""
    dagster_home_raw = environment.get(_DAGSTER_HOME_ENV)
    if not dagster_home_raw:
        raise DagsterStorageMigrationError("missing_dagster_home")

    dagster_home = Path(dagster_home_raw)
    if dagster_home != _DAGSTER_HOME:
        raise DagsterStorageMigrationError("invalid_dagster_home")

    dagster_yaml = dagster_home / "dagster.yaml"
    try:
        metadata = dagster_yaml.lstat()
    except OSError as exc:
        raise DagsterStorageMigrationError("missing_dagster_yaml") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_nlink != 1
        or metadata.st_size > 1024 * 1024
    ):
        raise DagsterStorageMigrationError("invalid_dagster_yaml")
    try:
        descriptor = os.open(dagster_yaml, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            ):
                raise DagsterStorageMigrationError("invalid_dagster_yaml")
            raw = stream.read(1024 * 1024 + 1)
    except OSError as exc:
        raise DagsterStorageMigrationError("invalid_dagster_yaml") from exc
    _validate_dagster_config(raw)
    return hashlib.sha256(raw).hexdigest()


def _require_migration_environment(
    environment: Mapping[str, str],
) -> tuple[str, str, str]:
    """같은 image의 canonical config, profile, metadata DSN을 명시적으로 요구한다."""
    profile = environment.get(_DAGSTER_PROFILE_ENV, "production")
    if profile not in {"production", "local-dev"}:
        raise DagsterStorageMigrationError("invalid_dagster_profile")
    config_sha256 = _safe_dagster_config(environment)

    dagster_pg_url = environment.get(_DAGSTER_PG_URL_ENV)
    if not dagster_pg_url or not dagster_pg_url.strip():
        raise DagsterStorageMigrationError("missing_dagster_pg_url")
    return dagster_pg_url, profile, config_sha256


def _require_fields(
    value: object, expected: frozenset[str], code: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DagsterStorageMigrationError(code)
    return value


def _require_database_identity(
    value: object, *, dagster: bool
) -> Mapping[str, Any]:
    expected = _DAGSTER_DATABASE_FIELDS if dagster else _APPLICATION_DATABASE_FIELDS
    identity = _require_fields(value, expected, "dagster_storage_permit_identity_invalid")
    if (
        not isinstance(identity["system_identifier"], str)
        or not identity["system_identifier"].isdigit()
        or not isinstance(identity["name"], str)
        or not _DATABASE_NAME_PATTERN.fullmatch(identity["name"])
        or not isinstance(identity["oid"], int)
        or isinstance(identity["oid"], bool)
        or identity["oid"] <= 0
        or not isinstance(identity["owner"], str)
        or not _ROLE_NAME_PATTERN.fullmatch(identity["owner"])
    ):
        raise DagsterStorageMigrationError("dagster_storage_permit_identity_invalid")
    if dagster and (
        not isinstance(identity["login_role"], str)
        or not _ROLE_NAME_PATTERN.fullmatch(identity["login_role"])
    ):
        raise DagsterStorageMigrationError("dagster_storage_permit_identity_invalid")
    return identity


def _read_permit(
    environment: Mapping[str, str], *, profile: str, config_sha256: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """root-owned permit에서 metadata와 forbidden application identity를 읽는다."""
    try:
        parent = _PERMIT_PATH.parent.lstat()
        metadata = _PERMIT_PATH.lstat()
    except OSError as exc:
        raise DagsterStorageMigrationError("dagster_storage_permit_unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) & 0o022
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_nlink != 1
        or metadata.st_size > 1024 * 1024
    ):
        raise DagsterStorageMigrationError("dagster_storage_permit_unsafe")
    try:
        descriptor = os.open(_PERMIT_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            ):
                raise DagsterStorageMigrationError("dagster_storage_permit_unsafe")
            raw = stream.read(1024 * 1024 + 1)
        permit = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DagsterStorageMigrationError("dagster_storage_permit_invalid") from exc
    permit = _require_fields(permit, _PERMIT_FIELDS, "dagster_storage_permit_invalid")
    if permit["schema"] != _PERMIT_SCHEMA:
        raise DagsterStorageMigrationError("dagster_storage_permit_invalid")
    dagster_identity = _require_database_identity(permit["dagster_database"], dagster=True)
    application_identity = _require_database_identity(
        permit["application_database"], dagster=False
    )
    if (
        dagster_identity["system_identifier"]
        != application_identity["system_identifier"]
        or (dagster_identity["name"], dagster_identity["oid"])
        == (application_identity["name"], application_identity["oid"])
    ):
        raise DagsterStorageMigrationError("dagster_storage_permit_identity_invalid")

    if profile == "production":
        if permit["authority"] != "docker-manager":
            raise DagsterStorageMigrationError("dagster_storage_permit_authority_invalid")
        candidate = _require_fields(
            permit["candidate"], _CANDIDATE_FIELDS, "dagster_storage_permit_candidate_invalid"
        )
        image_id = environment.get(_PERMIT_IMAGE_ID_ENV, "")
        paired_receipt = environment.get(_PERMIT_PAIRED_RECEIPT_ENV, "")
        expected_config_sha256 = environment.get(_PERMIT_CONFIG_SHA256_ENV, "")
        if (
            not _IMAGE_ID_PATTERN.fullmatch(image_id)
            or not _SHA256_PATTERN.fullmatch(paired_receipt)
            or not _SHA256_PATTERN.fullmatch(expected_config_sha256)
            or candidate
            != {
                "dagster_image_id": image_id,
                "paired_candidate_build_receipt_sha256": paired_receipt,
                "dagster_config_sha256": expected_config_sha256,
            }
            or config_sha256 != expected_config_sha256
        ):
            raise DagsterStorageMigrationError("dagster_storage_permit_candidate_invalid")
    else:
        if permit["authority"] != "local-compose-db-init" or permit["candidate"] is not None:
            raise DagsterStorageMigrationError("dagster_storage_permit_authority_invalid")
    return dagster_identity, application_identity


def _read_observed_identity(
    dagster_pg_url: str,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[bool, bool, bool]]:
    """migration과 같은 DSN에서 DB identity와 application residue를 읽는다."""
    engine = None
    try:
        engine = create_engine(dagster_pg_url)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT control.system_identifier::text AS system_identifier,
                           current_database() AS name,
                           database.oid::bigint AS oid,
                           pg_get_userbyid(database.datdba) AS owner,
                           session_user AS login_role,
                           to_regclass('public.alembic_version') IS NOT NULL AS has_version,
                           to_regnamespace('feature') IS NOT NULL AS has_feature,
                           to_regnamespace('provider_sync') IS NOT NULL AS has_provider_sync,
                           to_regnamespace('ops') IS NOT NULL AS has_ops
                    FROM pg_database AS database
                    CROSS JOIN pg_control_system() AS control
                    WHERE database.datname = current_database()
                    """
                )
            ).mappings().one()
            versions: tuple[str, ...] = ()
            if bool(row["has_version"]):
                versions = tuple(
                    str(item[0])
                    for item in connection.execute(
                        text(
                            "SELECT version_num::text FROM public.alembic_version "
                            "ORDER BY version_num LIMIT 2"
                        )
                    ).all()
                )
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_identity_unavailable") from exc
    finally:
        if engine is not None:
            engine.dispose()
    return (
        {
            "system_identifier": str(row["system_identifier"]),
            "name": str(row["name"]),
            "oid": int(row["oid"]),
            "owner": str(row["owner"]),
            "login_role": str(row["login_role"]),
        },
        versions,
        (bool(row["has_feature"]), bool(row["has_provider_sync"]), bool(row["has_ops"])),
    )


def _verify_database_identity(
    environment: Mapping[str, str]
) -> tuple[str, dict[str, Any]]:
    dagster_pg_url, profile, config_sha256 = _require_migration_environment(environment)
    expected, forbidden = _read_permit(
        environment, profile=profile, config_sha256=config_sha256
    )
    observed, versions, application_schemas = _read_observed_identity(dagster_pg_url)
    if all(
        observed[key] == forbidden[key]
        for key in ("system_identifier", "name", "oid", "owner")
    ):
        raise DagsterStorageMigrationError("dagster_storage_targets_application_database")
    if versions == ("300",) or any(application_schemas):
        raise DagsterStorageMigrationError("dagster_storage_targets_application_schema")
    if observed != dict(expected):
        raise DagsterStorageMigrationError("dagster_storage_database_identity_mismatch")
    return dagster_pg_url, observed


def _run_dagster_instance_migrate(environment: Mapping[str, str]) -> None:
    """Dagster가 제공하는 migration entrypoint를 실행하되 민감 출력은 전달하지 않는다."""
    try:
        completed = subprocess.run(
            [
                _ISOLATED_PYTHON,
                "-I",
                _DAGSTER_EXECUTABLE,
                "instance",
                "migrate",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=dict(environment),
        )
    except OSError as exc:
        raise DagsterStorageMigrationError("dagster_instance_migrate_unavailable") from exc
    if completed.returncode != 0:
        # Dagster의 info 출력이나 DB driver 예외에는 DSN이 포함될 수 있다. 이 명령은
        # container log로도 원문을 넘기지 않고, 호출자가 stable error code만 받게 한다.
        raise DagsterStorageMigrationError("dagster_instance_migrate_failed")


def _read_version_rows(dagster_pg_url: str) -> tuple[str, ...]:
    """동일 DSN의 Dagster storage version table을 읽는다."""
    engine = None
    try:
        engine = create_engine(dagster_pg_url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            ).all()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_version_table_unavailable") from exc
    finally:
        if engine is not None:
            engine.dispose()
    return tuple(str(row[0]) for row in rows)


def _migrate(environment: Mapping[str, str]) -> dict[str, str]:
    head = _dagster_storage_head()
    dagster_pg_url, _ = _verify_database_identity(environment)
    _run_dagster_instance_migrate(environment)
    verified_dagster_pg_url, _ = _verify_database_identity(environment)
    if verified_dagster_pg_url != dagster_pg_url:
        raise DagsterStorageMigrationError("dagster_storage_dsn_changed")
    version_rows = _read_version_rows(dagster_pg_url)
    if len(version_rows) != 1:
        raise DagsterStorageMigrationError("dagster_version_row_count_invalid")
    version_num = version_rows[0]
    if version_num != head:
        raise DagsterStorageMigrationError("dagster_version_mismatch")
    return {
        "schema": _MIGRATE_SCHEMA,
        "status": "migrated",
        "head": head,
        "version_num": version_num,
    }


def _emit(payload: Mapping[str, str], *, stream: TextIO = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    """`head` 또는 `migrate`를 실행하고 안정된 JSON 결과를 출력한다."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["head"]:
            _emit({"schema": _HEAD_SCHEMA, "head": _dagster_storage_head()})
            return 0
        if arguments == ["verify-identity"]:
            _, identity = _verify_database_identity(os.environ)
            _emit(
                {
                    "schema": _IDENTITY_SCHEMA,
                    "status": "verified",
                    "database_name": str(identity["name"]),
                    "database_oid": str(identity["oid"]),
                }
            )
            return 0
        if arguments == ["migrate"]:
            _emit(_migrate(os.environ))
            return 0
        raise DagsterStorageMigrationError("invalid_arguments")
    except DagsterStorageMigrationError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
