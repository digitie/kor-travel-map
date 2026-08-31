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
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO
from uuid import UUID

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster._core.storage.sql import ALEMBIC_SCRIPTS_LOCATION
from sqlalchemy import create_engine, text

#: application active graph의 유일한 root. head와 달리 움직이지 않는다.
_BASELINE_ROOT_REVISION: Final = "300"

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
_PERMIT_SCHEMA: Final = "kor-travel-map.dagster-storage-database-permit.v2"
_IDENTITY_SCHEMA: Final = "kor-travel-map.dagster-storage-database-identity.v1"
_HEAD_SCHEMA: Final = "kor-travel-map.dagster-storage-head.v1"
_MIGRATE_SCHEMA: Final = "kor-travel-map.dagster-storage-migration.v3"
_CATALOG_SCHEMA: Final = "kor-travel-map.dagster-storage-catalog.v1"
_ERROR_SCHEMA: Final = "kor-travel-map.dagster-storage-migration-error.v1"
_ISOLATED_PYTHON: Final = "/usr/local/bin/python"
_DAGSTER_EXECUTABLE: Final = "/usr/local/bin/dagster"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATABASE_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_ROLE_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPERATION_LOCK_KEY: Final = "kor-travel-map:dagster-storage-operation"
_INTENT_TABLE: Final = "public.ktm_dagster_storage_operation_intents"
_RECEIPT_TABLE: Final = "public.ktm_dagster_storage_operation_receipts"
_PERMIT_FIELDS: Final = frozenset(
    {
        "schema",
        "authority",
        "operation_id",
        "candidate",
        "dagster_database",
        "application_database",
    }
)
_DAGSTER_DATABASE_FIELDS: Final = frozenset(
    {
        "system_identifier",
        "name",
        "oid",
        "owner",
        "login_role",
        "login_role_attributes",
    }
)
_APPLICATION_DATABASE_FIELDS: Final = frozenset(
    {"system_identifier", "name", "oid", "owner"}
)
_CANDIDATE_FIELDS: Final = frozenset(
    {"dagster_image_id", "paired_candidate_build_receipt_sha256", "dagster_config_sha256"}
)
_LOGIN_ROLE_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "superuser",
        "can_login",
        "inherit",
        "create_database",
        "create_role",
        "replication",
        "bypass_rls",
        "connection_limit",
        "valid_until_is_null",
        "role_config_count",
        "database_role_setting_count",
        "granted_role_count",
        "member_role_count",
    }
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
        if set(config) != {
            "telemetry",
            "python_logs",
            "storage",
            "concurrency",
            "run_monitoring",
        }:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        storage = config["storage"]
        postgres = storage["postgres"]
    except (KeyError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        raise DagsterStorageMigrationError("invalid_dagster_yaml") from exc
    if storage != {
        "postgres": {
            "postgres_url": {"env": _DAGSTER_PG_URL_ENV},
            "should_autocreate_tables": False,
        }
    } or postgres != {
        "postgres_url": {"env": _DAGSTER_PG_URL_ENV},
        "should_autocreate_tables": False,
    }:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")


def _validate_root_owned_directory(metadata: os.stat_result) -> None:
    """appuser가 config를 rename/replace할 수 있는 상위 directory를 거부한다."""
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise DagsterStorageMigrationError("unsafe_dagster_home_parent")


def _safe_dagster_config(environment: Mapping[str, str]) -> str:
    """봉인된 canonical config가 metadata DSN env 하나만 읽는지 확인한다."""
    dagster_home_raw = environment.get(_DAGSTER_HOME_ENV)
    if not dagster_home_raw:
        raise DagsterStorageMigrationError("missing_dagster_home")

    dagster_home = Path(dagster_home_raw)
    if dagster_home != _DAGSTER_HOME:
        raise DagsterStorageMigrationError("invalid_dagster_home")

    for directory in (Path("/opt"), Path("/opt/dagster"), _DAGSTER_HOME):
        try:
            _validate_root_owned_directory(directory.lstat())
        except OSError as exc:
            raise DagsterStorageMigrationError("unsafe_dagster_home_parent") from exc

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
    if dagster:
        attributes = _require_fields(
            identity["login_role_attributes"],
            _LOGIN_ROLE_ATTRIBUTE_FIELDS,
            "dagster_storage_permit_identity_invalid",
        )
        if (
            identity["owner"] != identity["login_role"]
            or any(
                attributes[key] is not False
                for key in (
                    "superuser",
                    "inherit",
                    "create_database",
                    "create_role",
                    "replication",
                    "bypass_rls",
                )
            )
            or attributes["can_login"] is not True
            or not isinstance(attributes["connection_limit"], int)
            or isinstance(attributes["connection_limit"], bool)
            or attributes["connection_limit"] != -1
            or attributes["valid_until_is_null"] is not True
            or any(
                not isinstance(attributes[key], int)
                or isinstance(attributes[key], bool)
                or attributes[key] != 0
                for key in ("granted_role_count", "member_role_count")
            )
            or any(
                not isinstance(attributes[key], int)
                or isinstance(attributes[key], bool)
                or attributes[key] != 0
                for key in ("role_config_count", "database_role_setting_count")
            )
        ):
            raise DagsterStorageMigrationError("dagster_storage_login_role_unsafe")
    return identity


def _require_isolated_database_identities(
    dagster_identity: Mapping[str, Any],
    application_identity: Mapping[str, Any],
) -> None:
    """metadata owner/DB가 application identity와 겹치지 않음을 강제한다."""
    if (
        dagster_identity["system_identifier"]
        != application_identity["system_identifier"]
        or dagster_identity["owner"] == application_identity["owner"]
        or (dagster_identity["name"], dagster_identity["oid"])
        == (application_identity["name"], application_identity["oid"])
    ):
        raise DagsterStorageMigrationError("dagster_storage_permit_identity_invalid")


def _read_permit(
    environment: Mapping[str, str], *, profile: str, config_sha256: str
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, str]]:
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
    raw_operation_id = permit["operation_id"]
    try:
        operation_id = str(UUID(str(raw_operation_id)))
    except (TypeError, ValueError) as exc:
        raise DagsterStorageMigrationError(
            "dagster_storage_permit_operation_id_invalid"
        ) from exc
    if not isinstance(raw_operation_id, str) or raw_operation_id != operation_id:
        raise DagsterStorageMigrationError(
            "dagster_storage_permit_operation_id_invalid"
        )
    dagster_identity = _require_database_identity(permit["dagster_database"], dagster=True)
    application_identity = _require_database_identity(
        permit["application_database"], dagster=False
    )
    _require_isolated_database_identities(dagster_identity, application_identity)

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
    return (
        dagster_identity,
        application_identity,
        {
            "operation_id": operation_id,
            "permit_sha256": hashlib.sha256(raw).hexdigest(),
            "config_sha256": config_sha256,
        },
    )


def _read_observed_identity(
    dagster_pg_url: str,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[bool, bool, bool], bool]:
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
                           current_user AS effective_role,
                           role.rolsuper AS login_superuser,
                           role.rolcanlogin AS login_can_login,
                           role.rolinherit AS login_inherit,
                           role.rolcreatedb AS login_create_database,
                           role.rolcreaterole AS login_create_role,
                           role.rolreplication AS login_replication,
                           role.rolbypassrls AS login_bypass_rls,
                           role.rolconnlimit AS login_connection_limit,
                           role.rolvaliduntil IS NULL AS login_valid_until_is_null,
                           COALESCE(pg_catalog.cardinality(role.rolconfig), 0)
                               AS login_role_config_count,
                           (SELECT count(*)::bigint
                              FROM pg_catalog.pg_db_role_setting AS setting
                             WHERE setting.setrole = role.oid)
                               AS login_database_role_setting_count,
                           (SELECT count(*)::bigint
                              FROM pg_auth_members AS membership
                             WHERE membership.member = role.oid) AS login_granted_role_count,
                           (SELECT count(*)::bigint
                              FROM pg_auth_members AS membership
                             WHERE membership.roleid = role.oid) AS login_member_role_count,
                           to_regclass('public.alembic_version') IS NOT NULL AS has_version,
                           to_regnamespace('feature') IS NOT NULL AS has_feature,
                           to_regnamespace('provider_sync') IS NOT NULL AS has_provider_sync,
                           to_regnamespace('ops') IS NOT NULL AS has_ops
                    FROM pg_database AS database
                    JOIN pg_roles AS role ON role.rolname = session_user
                    CROSS JOIN pg_control_system() AS control
                    WHERE database.datname = current_database()
                    """
                )
            ).mappings().one()
            versions: tuple[str, ...] = ()
            has_application_300 = False
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
                # application DB 판정. 종전에는 `version_num = '300'` 하나만 봤는데,
                # `public.alembic_version`은 **현재 head 한 행만** 담으므로 application
                # graph에 child migration이 붙는 순간 이 arm이 조용히 False가 된다 —
                # `_verify_database_identity`의 세 방벽 중 하나를 예외도 로그도 없이
                # 잃는다.
                #
                # 한 번은 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD` env로 넓혔는데,
                # **그 변수는 `kor-travel-map-api` 서비스에만 주입된다.** dagster
                # 서비스에는 없으므로 프로덕션에서 이 arm은 여전히 baseline root만
                # 보았다 — 고친 것처럼 보이지만 아무것도 고치지 않은 상태였다.
                #
                # 설치본이 담고 있는 graph를 직접 읽는다. 이 파일은 의도적으로
                # ``kortravelmap``을 import하지 않지만(위 모듈 docstring), 그것은
                # **패키지를 import하지 않는다**는 뜻이지 설치본의 데이터 파일을 읽지
                # 않는다는 뜻이 아니다 — `docker/application-schema-head.py`도 같은
                # 파일을 같은 방식으로 읽는다.
                application_revisions = _installed_application_revisions()
                has_application_300 = bool(
                    connection.execute(
                        text(
                            "SELECT EXISTS ("
                            "SELECT 1 FROM public.alembic_version "
                            "WHERE version_num::text = ANY(:revisions)"
                            ")"
                        ),
                        {"revisions": sorted(application_revisions)},
                    ).scalar_one()
                )
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_identity_unavailable") from exc
    finally:
        if engine is not None:
            engine.dispose()
    if str(row["login_role"]) != str(row["effective_role"]):
        raise DagsterStorageMigrationError("dagster_storage_login_role_unsafe")
    return (
        {
            "system_identifier": str(row["system_identifier"]),
            "name": str(row["name"]),
            "oid": int(row["oid"]),
            "owner": str(row["owner"]),
            "login_role": str(row["login_role"]),
            "login_role_attributes": {
                "superuser": bool(row["login_superuser"]),
                "can_login": bool(row["login_can_login"]),
                "inherit": bool(row["login_inherit"]),
                "create_database": bool(row["login_create_database"]),
                "create_role": bool(row["login_create_role"]),
                "replication": bool(row["login_replication"]),
                "bypass_rls": bool(row["login_bypass_rls"]),
                "connection_limit": int(row["login_connection_limit"]),
                "valid_until_is_null": bool(row["login_valid_until_is_null"]),
                "role_config_count": int(row["login_role_config_count"]),
                "database_role_setting_count": int(
                    row["login_database_role_setting_count"]
                ),
                "granted_role_count": int(row["login_granted_role_count"]),
                "member_role_count": int(row["login_member_role_count"]),
            },
        },
        versions,
        (bool(row["has_feature"]), bool(row["has_provider_sync"]), bool(row["has_ops"])),
        has_application_300,
    )


def _installed_application_revisions() -> set[str]:
    """설치된 Map package의 migration graph가 담은 revision 전부.

    ``public.alembic_version``에는 현재 head 한 행만 있으므로, "이 DB가 application
    DB인가"를 판정하려면 **graph의 모든 revision**을 후보로 봐야 한다. head 하나만
    보면 중간 revision에서 멈춘 DB를 놓친다.

    설치본을 읽지 못하면 baseline root로 좁힌다 — 판정이 넓어져 격리 가드가 느슨해지는
    것보다 좁아져 시끄러운 편이 안전하다.
    """
    paths = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        raw_path = paths.get(key)
        if not raw_path:
            continue
        manifest = Path(raw_path) / "kortravelmap" / "_application_migration_graph.json"
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        revisions = payload.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            continue
        declared = {str(entry["revision"]) for entry in revisions}
        if _BASELINE_ROOT_REVISION in declared:
            return declared
    return {_BASELINE_ROOT_REVISION}


def _verify_database_identity(
    environment: Mapping[str, str]
) -> tuple[str, dict[str, Any]]:
    dagster_pg_url, profile, config_sha256 = _require_migration_environment(environment)
    expected, forbidden, _ = _read_permit(
        environment, profile=profile, config_sha256=config_sha256
    )
    observed, _, application_schemas, has_application_300 = _read_observed_identity(
        dagster_pg_url
    )
    if all(
        observed[key] == forbidden[key]
        for key in ("system_identifier", "name", "oid", "owner")
    ):
        raise DagsterStorageMigrationError("dagster_storage_targets_application_database")
    if has_application_300 or any(application_schemas):
        raise DagsterStorageMigrationError("dagster_storage_targets_application_schema")
    if observed != dict(expected):
        raise DagsterStorageMigrationError("dagster_storage_database_identity_mismatch")
    return dagster_pg_url, observed


def _run_dagster_instance_migrate(environment: Mapping[str, str]) -> None:
    """Dagster의 schema/data migration과 필수 reindex를 민감 출력 없이 실행한다."""
    for operation in ("migrate", "reindex"):
        try:
            completed = subprocess.run(
                [
                    _ISOLATED_PYTHON,
                    "-I",
                    _DAGSTER_EXECUTABLE,
                    "instance",
                    operation,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=dict(environment),
            )
        except OSError as exc:
            raise DagsterStorageMigrationError(
                "dagster_instance_migrate_unavailable"
            ) from exc
        if completed.returncode != 0:
            # Dagster의 info 출력이나 DB driver 예외에는 DSN이 포함될 수 있다. 이 명령은
            # container log로도 원문을 넘기지 않고, 호출자가 stable error code만 받게 한다.
            raise DagsterStorageMigrationError("dagster_instance_migrate_failed")


def _read_operation_binding(
    environment: Mapping[str, str],
) -> tuple[str, Mapping[str, Any], Mapping[str, str]]:
    dagster_pg_url, profile, config_sha256 = _require_migration_environment(environment)
    expected, _, binding = _read_permit(
        environment, profile=profile, config_sha256=config_sha256
    )
    candidate = (
        environment.get(_PERMIT_IMAGE_ID_ENV, "")
        + ":"
        + environment.get(_PERMIT_PAIRED_RECEIPT_ENV, "")
        + ":"
        + config_sha256
    )
    return (
        dagster_pg_url,
        expected,
        {
            **binding,
            "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        },
    )


def _acquire_session_operation_lock(connection: Any) -> None:
    connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_lock("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    )
    # session lock은 transaction 밖에서도 external Dagster subprocess가 끝날 때까지
    # 유지한다. autobegin transaction만 여기서 닫는다.
    connection.commit()


def _release_session_operation_lock(connection: Any) -> None:
    unlocked = connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_unlock("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    ).scalar_one()
    connection.commit()
    if unlocked is not True:
        raise DagsterStorageMigrationError("dagster_operation_lock_release_failed")


def _acquire_shared_transaction_operation_lock(connection: Any) -> None:
    connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_xact_lock_shared("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    )


def _ensure_operation_outbox(connection: Any) -> None:
    """Dagster DB에 append-only intent/receipt control plane을 설치·검증한다."""

    existing = tuple(
        bool(value)
        for value in connection.execute(
            text(
                "SELECT to_regclass(:intent) IS NOT NULL, "
                "to_regclass(:receipt) IS NOT NULL"
            ),
            {"intent": _INTENT_TABLE, "receipt": _RECEIPT_TABLE},
        ).one()
    )
    if existing not in {(False, False), (True, True)}:
        raise DagsterStorageMigrationError("dagster_operation_outbox_contract_invalid")
    statements = (
        f"""
        CREATE TABLE {_INTENT_TABLE} (
            operation_id uuid NOT NULL,
            permit_sha256 text NOT NULL,
            candidate_sha256 text NOT NULL,
            target_head text NOT NULL,
            pre_state text NOT NULL,
            pre_version_rows jsonb NOT NULL,
            database_name text NOT NULL,
            database_oid bigint NOT NULL,
            database_owner text NOT NULL,
            postgres_system_identifier text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT pk_ktm_dagster_storage_operation_intents
                PRIMARY KEY (operation_id),
            CONSTRAINT ck_ktm_dagster_storage_intent_permit
                CHECK (permit_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_ktm_dagster_storage_intent_candidate
                CHECK (candidate_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_ktm_dagster_storage_intent_head
                CHECK (btrim(target_head) <> ''),
            CONSTRAINT ck_ktm_dagster_storage_intent_state
                CHECK (pre_state IN ('missing', 'old')),
            CONSTRAINT ck_ktm_dagster_storage_intent_rows
                CHECK (jsonb_typeof(pre_version_rows) = 'array'),
            CONSTRAINT ck_ktm_dagster_storage_intent_oid CHECK (database_oid > 0),
            CONSTRAINT ck_ktm_dagster_storage_intent_system
                CHECK (postgres_system_identifier ~ '^[0-9]+$')
        )
        """,
        f"""
        CREATE TABLE {_RECEIPT_TABLE} (
            operation_id uuid NOT NULL,
            result_schema text NOT NULL,
            result_sha256 text NOT NULL,
            final_head text NOT NULL,
            result_payload jsonb NOT NULL,
            committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT pk_ktm_dagster_storage_operation_receipts
                PRIMARY KEY (operation_id),
            CONSTRAINT fk_ktm_dagster_storage_receipt_intent
                FOREIGN KEY (operation_id) REFERENCES {_INTENT_TABLE}(operation_id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_ktm_dagster_storage_receipt_schema CHECK (
                result_schema = 'kor-travel-map.dagster-storage-migration.v3'
            ),
            CONSTRAINT ck_ktm_dagster_storage_receipt_sha256
                CHECK (result_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_ktm_dagster_storage_receipt_payload
                CHECK (jsonb_typeof(result_payload) = 'object')
        )
        """,
        """
        CREATE OR REPLACE FUNCTION public.ktm_reject_dagster_storage_operation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO pg_catalog
        AS $function$
        BEGIN
            RAISE EXCEPTION 'Dagster storage operation evidence is append-only'
                USING ERRCODE = '55000';
        END
        $function$
        """,
        f"CREATE TRIGGER trg_ktm_dagster_storage_intent_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {_INTENT_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION "
        "public.ktm_reject_dagster_storage_operation_mutation()",
        f"CREATE TRIGGER trg_ktm_dagster_storage_receipt_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {_RECEIPT_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION "
        "public.ktm_reject_dagster_storage_operation_mutation()",
        f"REVOKE ALL ON TABLE {_INTENT_TABLE}, {_RECEIPT_TABLE} FROM PUBLIC",
        "REVOKE ALL ON FUNCTION "
        "public.ktm_reject_dagster_storage_operation_mutation() FROM PUBLIC",
    )
    try:
        if existing == (False, False):
            for statement in statements:
                connection.execute(text(statement))
        column_rows = connection.execute(
            text(
                "SELECT CAST(:relation AS text), attribute.attname, "
                "pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) "
                "FROM pg_catalog.pg_attribute AS attribute "
                "WHERE attribute.attrelid = CAST(:relation AS regclass) "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
                "ORDER BY attribute.attnum"
            ),
            {"relation": _INTENT_TABLE},
        ).all() + connection.execute(
            text(
                "SELECT CAST(:relation AS text), attribute.attname, "
                "pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) "
                "FROM pg_catalog.pg_attribute AS attribute "
                "WHERE attribute.attrelid = CAST(:relation AS regclass) "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
                "ORDER BY attribute.attnum"
            ),
            {"relation": _RECEIPT_TABLE},
        ).all()
        columns = {
            str(relation): {
                str(row[1]): str(row[2])
                for row in column_rows
                if str(row[0]) == str(relation)
            }
            for relation in (_INTENT_TABLE, _RECEIPT_TABLE)
        }
        relation_contract = connection.execute(
            text(
                "SELECT count(*) FILTER (WHERE relation.relkind = 'r' "
                "AND relation.relowner = (SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname = current_user) AND NOT relation.relrowsecurity "
                "AND NOT relation.relforcerowsecurity AND relation.relpersistence = 'p'), "
                "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pg_catalog.aclexplode("
                "COALESCE(relation.relacl, pg_catalog.acldefault('r', relation.relowner))) "
                "AS privilege WHERE privilege.grantee = 0)) "
                "FROM pg_catalog.pg_class AS relation "
                "WHERE relation.oid IN (CAST(:intent AS regclass), CAST(:receipt AS regclass))"
            ),
            {"intent": _INTENT_TABLE, "receipt": _RECEIPT_TABLE},
        ).one()
        constraints = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT constraint_row.conname FROM pg_catalog.pg_constraint "
                    "AS constraint_row WHERE constraint_row.conrelid IN "
                    "(CAST(:intent AS regclass), CAST(:receipt AS regclass)) "
                    "AND constraint_row.convalidated"
                ),
                {"intent": _INTENT_TABLE, "receipt": _RECEIPT_TABLE},
            ).all()
        }
        triggers = {
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                text(
                    "SELECT trigger.tgrelid::regclass::text, trigger.tgname, "
                    "trigger.tgenabled::text FROM pg_catalog.pg_trigger AS trigger "
                    "WHERE trigger.tgrelid IN "
                    "(CAST(:intent AS regclass), CAST(:receipt AS regclass)) "
                    "AND NOT trigger.tgisinternal"
                ),
                {"intent": _INTENT_TABLE, "receipt": _RECEIPT_TABLE},
            ).all()
        }
        function_contract = connection.execute(
            text(
                "SELECT count(*) FROM pg_catalog.pg_proc AS routine "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = routine.pronamespace "
                "WHERE namespace.nspname = 'public' "
                "AND routine.proname = 'ktm_reject_dagster_storage_operation_mutation' "
                "AND routine.pronargs = 0 AND routine.prorettype = 'trigger'::regtype "
                "AND routine.proowner = (SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname = current_user) AND NOT routine.prosecdef "
                "AND routine.proconfig = ARRAY['search_path=pg_catalog']::text[] "
                "AND routine.prosrc = :source "
                "AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode(COALESCE("
                "routine.proacl, pg_catalog.acldefault('f', routine.proowner))) "
                "AS privilege WHERE privilege.grantee = 0)"
            ),
            {
                "source": "\n        BEGIN\n            RAISE EXCEPTION "
                "'Dagster storage operation evidence is append-only'\n"
                "                USING ERRCODE = '55000';\n        END\n        "
            },
        ).scalar_one()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_operation_outbox_unavailable") from exc
    if (
        columns
        != {
            _INTENT_TABLE: {
                "operation_id": "uuid",
                "permit_sha256": "text",
                "candidate_sha256": "text",
                "target_head": "text",
                "pre_state": "text",
                "pre_version_rows": "jsonb",
                "database_name": "text",
                "database_oid": "bigint",
                "database_owner": "text",
                "postgres_system_identifier": "text",
                "created_at": "timestamp with time zone",
            },
            _RECEIPT_TABLE: {
                "operation_id": "uuid",
                "result_schema": "text",
                "result_sha256": "text",
                "final_head": "text",
                "result_payload": "jsonb",
                "committed_at": "timestamp with time zone",
            },
        }
        or tuple(int(value) for value in relation_contract) != (2, 0)
        or constraints
        != {
            "pk_ktm_dagster_storage_operation_intents",
            "ck_ktm_dagster_storage_intent_permit",
            "ck_ktm_dagster_storage_intent_candidate",
            "ck_ktm_dagster_storage_intent_head",
            "ck_ktm_dagster_storage_intent_state",
            "ck_ktm_dagster_storage_intent_rows",
            "ck_ktm_dagster_storage_intent_oid",
            "ck_ktm_dagster_storage_intent_system",
            "pk_ktm_dagster_storage_operation_receipts",
            "fk_ktm_dagster_storage_receipt_intent",
            "ck_ktm_dagster_storage_receipt_schema",
            "ck_ktm_dagster_storage_receipt_sha256",
            "ck_ktm_dagster_storage_receipt_payload",
        }
        or triggers
        != {
            (
                _INTENT_TABLE.removeprefix("public."),
                "trg_ktm_dagster_storage_intent_immutable",
                "O",
            ),
            (
                _RECEIPT_TABLE.removeprefix("public."),
                "trg_ktm_dagster_storage_receipt_immutable",
                "O",
            ),
        }
        or int(function_contract) != 1
    ):
        raise DagsterStorageMigrationError("dagster_operation_outbox_contract_invalid")


def _read_version_state(connection: Any, head: str) -> tuple[str, tuple[str, ...]]:
    """missing/old/exact final head를 mutation 전에 분리한다."""

    if not bool(
        connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
    ):
        return "missing", ()
    rows = tuple(
        str(row[0])
        for row in connection.execute(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        ).all()
    )
    return ("final" if rows == (head,) else "old"), rows


def _canonical_result_bytes(result: Mapping[str, Any]) -> bytes:
    return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _dagster_metadata_contract() -> tuple[
    tuple[Any, ...],
    dict[str, tuple[tuple[str, bool], ...]],
    dict[str, tuple[str, ...]],
    tuple[str, ...],
]:
    """설치된 Dagster package에서 fresh storage의 exact 구조를 만든다."""

    try:
        from dagster._core.storage.event_log.migration import (
            ASSET_DATA_MIGRATIONS,
            EVENT_LOG_DATA_MIGRATIONS,
        )
        from dagster._core.storage.event_log.schema import SqlEventLogStorageMetadata
        from dagster._core.storage.runs.migration import REQUIRED_DATA_MIGRATIONS
        from dagster._core.storage.runs.schema import RunStorageSqlMetadata
        from dagster._core.storage.schedules.migration import (
            REQUIRED_SCHEDULE_DATA_MIGRATIONS,
        )
        from dagster._core.storage.schedules.schema import ScheduleStorageSqlMetadata
        from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_contract_unavailable") from exc

    metadatas = (
        RunStorageSqlMetadata,
        SqlEventLogStorageMetadata,
        ScheduleStorageSqlMetadata,
    )
    columns: dict[str, tuple[tuple[str, bool], ...]] = {}
    indexes: dict[str, tuple[str, ...]] = {}
    for metadata in metadatas:
        for table in metadata.sorted_tables:
            table_columns = tuple(
                (str(column.name), not bool(column.nullable)) for column in table.columns
            )
            table_indexes = {str(index.name) for index in table.indexes if index.name}
            for constraint in table.constraints:
                constraint_columns = tuple(str(column.name) for column in constraint.columns)
                if isinstance(constraint, PrimaryKeyConstraint) and constraint_columns:
                    table_indexes.add(
                        str(constraint.name or f"{table.name}_pkey")
                    )
                elif isinstance(constraint, UniqueConstraint) and constraint_columns:
                    table_indexes.add(
                        str(
                            constraint.name
                            or f"{table.name}_{'_'.join(constraint_columns)}_key"
                        )
                    )
            table_index_names = tuple(sorted(table_indexes))
            if table.name in columns and (
                columns[table.name] != table_columns
                or indexes[table.name] != table_index_names
            ):
                raise DagsterStorageMigrationError("dagster_catalog_contract_ambiguous")
            columns[table.name] = table_columns
            indexes[table.name] = table_index_names

    required_migrations = tuple(
        sorted(
            {
                *REQUIRED_DATA_MIGRATIONS,
                *REQUIRED_SCHEDULE_DATA_MIGRATIONS,
                *EVENT_LOG_DATA_MIGRATIONS,
                *ASSET_DATA_MIGRATIONS,
            }
        )
    )
    return metadatas, columns, indexes, required_migrations


def _bootstrap_fresh_dagster_catalog(connection: Any, *, version_state: str) -> None:
    """fresh metadata catalog 전체와 head stamp를 한 DB transaction으로 만든다."""

    metadatas, _, _, _ = _dagster_metadata_contract()
    try:
        for metadata in metadatas:
            metadata.create_all(connection, checkfirst=True)
        if version_state == "missing":
            from dagster._core.storage.sql import stamp_alembic_rev
            from dagster_postgres.run_storage import run_storage
            from dagster_postgres.utils import pg_alembic_config

            stamp_alembic_rev(pg_alembic_config(run_storage.__file__), connection)
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_bootstrap_failed") from exc


def _verify_dagster_catalog(connection: Any, *, head: str) -> str:
    """세 storage의 exact table/column/index와 필수 migration marker를 검증한다."""

    _, expected_columns, expected_indexes, required_migrations = (
        _dagster_metadata_contract()
    )
    expected_tables = {
        *expected_columns,
        "alembic_version",
        _INTENT_TABLE.removeprefix("public."),
        _RECEIPT_TABLE.removeprefix("public."),
    }
    try:
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT relation.relname FROM pg_catalog.pg_class AS relation "
                    "JOIN pg_catalog.pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND relation.relkind IN ('r', 'p')"
                )
            ).all()
        }
        column_rows = connection.execute(
            text(
                "SELECT relation.relname, attribute.attname, attribute.attnotnull "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "JOIN pg_catalog.pg_attribute AS attribute "
                "ON attribute.attrelid = relation.oid "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relname = ANY(CAST(:tables AS text[])) "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
                "ORDER BY relation.relname, attribute.attnum"
            ),
            {"tables": sorted(expected_columns)},
        ).all()
        actual_columns = {
            table_name: tuple(
                (str(row[1]), bool(row[2]))
                for row in column_rows
                if str(row[0]) == table_name
            )
            for table_name in expected_columns
        }
        index_rows = connection.execute(
            text(
                "SELECT source.relname, target.relname, index_row.indisvalid, "
                "index_row.indisready, index_row.indislive "
                "FROM pg_catalog.pg_index AS index_row "
                "JOIN pg_catalog.pg_class AS source ON source.oid = index_row.indrelid "
                "JOIN pg_catalog.pg_class AS target ON target.oid = index_row.indexrelid "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = source.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND source.relname = ANY(CAST(:tables AS text[]))"
            ),
            {"tables": sorted(expected_columns)},
        ).all()
        actual_indexes = {
            table_name: tuple(
                sorted(
                    str(row[1])
                    for row in index_rows
                    if str(row[0]) == table_name
                    and bool(row[2])
                    and bool(row[3])
                    and bool(row[4])
                )
            )
            for table_name in expected_indexes
        }
        marker_rows = connection.execute(
            text("SELECT name, migration_completed FROM public.secondary_indexes")
        ).all()
        completed_markers = {
            str(row[0]) for row in marker_rows if bool(row[1])
        }
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_unavailable") from exc
    state, rows = _read_version_state(connection, head)
    if (
        actual_tables != expected_tables
        or actual_columns != expected_columns
        or actual_indexes != expected_indexes
        or state != "final"
        or rows != (head,)
        or not set(required_migrations).issubset(completed_markers)
    ):
        raise DagsterStorageMigrationError("dagster_catalog_postcondition_mismatch")
    payload = {
        "schema": _CATALOG_SCHEMA,
        "head": head,
        "tables": {
            table_name: {
                "columns": [
                    {"name": column_name, "not_null": not_null}
                    for column_name, not_null in expected_columns[table_name]
                ],
                "indexes": list(expected_indexes[table_name]),
            }
            for table_name in sorted(expected_columns)
        },
        "required_migrations": list(required_migrations),
    }
    return hashlib.sha256(_canonical_result_bytes(payload)).hexdigest()


def _validate_intent(
    row: Mapping[str, Any],
    *,
    binding: Mapping[str, str],
    identity: Mapping[str, Any],
    head: str,
) -> None:
    expected = {
        "operation_id": binding["operation_id"],
        "permit_sha256": binding["permit_sha256"],
        "candidate_sha256": binding["candidate_sha256"],
        "target_head": head,
        "database_name": identity["name"],
        "database_oid": identity["oid"],
        "database_owner": identity["owner"],
        "postgres_system_identifier": identity["system_identifier"],
    }
    if any(str(row[key]) != str(value) for key, value in expected.items()):
        raise DagsterStorageMigrationError("dagster_operation_intent_binding_mismatch")


def _read_intent(connection: Any, operation_id: str) -> Mapping[str, Any] | None:
    return connection.execute(
        text(
            f"SELECT operation_id::text, permit_sha256, candidate_sha256, target_head, "
            "pre_state, pre_version_rows, database_name, database_oid, database_owner, "
            f"postgres_system_identifier FROM {_INTENT_TABLE} "
            "WHERE operation_id = CAST(:operation_id AS uuid)"
        ),
        {"operation_id": operation_id},
    ).mappings().one_or_none()


def _read_receipt(connection: Any, operation_id: str) -> Mapping[str, Any] | None:
    return connection.execute(
        text(
            f"SELECT operation_id::text, result_schema, result_sha256, final_head, "
            f"result_payload FROM {_RECEIPT_TABLE} "
            "WHERE operation_id = CAST(:operation_id AS uuid)"
        ),
        {"operation_id": operation_id},
    ).mappings().one_or_none()


def _migration_result(
    *,
    binding: Mapping[str, str],
    identity: Mapping[str, Any],
    head: str,
    catalog_sha256: str,
) -> dict[str, str]:
    return {
        "schema": _MIGRATE_SCHEMA,
        "status": "migrated",
        "operation_id": binding["operation_id"],
        "permit_sha256": binding["permit_sha256"],
        "candidate_sha256": binding["candidate_sha256"],
        "head": head,
        "version_num": head,
        "database_name": str(identity["name"]),
        "database_oid": str(identity["oid"]),
        "database_owner": str(identity["owner"]),
        "postgres_system_identifier": str(identity["system_identifier"]),
        "catalog_sha256": catalog_sha256,
    }


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    binding: Mapping[str, str],
    identity: Mapping[str, Any],
    head: str,
    catalog_sha256: str,
) -> dict[str, str]:
    payload = receipt["result_payload"]
    if not isinstance(payload, Mapping):
        raise DagsterStorageMigrationError("dagster_operation_receipt_invalid")
    canonical = _canonical_result_bytes(payload)
    expected = _migration_result(
        binding=binding,
        identity=identity,
        head=head,
        catalog_sha256=catalog_sha256,
    )
    if (
        str(receipt["operation_id"]) != binding["operation_id"]
        or receipt["result_schema"] != _MIGRATE_SCHEMA
        or receipt["final_head"] != head
        or receipt["result_sha256"] != hashlib.sha256(canonical).hexdigest()
        or dict(payload) != expected
    ):
        raise DagsterStorageMigrationError("dagster_operation_receipt_invalid")
    return expected


def _prepare_operation(
    connection: Any,
    *,
    binding: Mapping[str, str],
    identity: Mapping[str, Any],
    head: str,
) -> tuple[str, dict[str, str] | None]:
    try:
        _ensure_operation_outbox(connection)
        receipt = _read_receipt(connection, binding["operation_id"])
        if receipt is not None:
            catalog_sha256 = _verify_dagster_catalog(connection, head=head)
            return "done", _validate_receipt(
                receipt,
                binding=binding,
                identity=identity,
                head=head,
                catalog_sha256=catalog_sha256,
            )
        state, rows = _read_version_state(connection, head)
        intent = _read_intent(connection, binding["operation_id"])
        if intent is not None:
            _validate_intent(intent, binding=binding, identity=identity, head=head)
            if state != "final" and (
                state != intent["pre_state"]
                or list(rows) != intent["pre_version_rows"]
            ):
                raise DagsterStorageMigrationError(
                    "dagster_operation_resume_state_mismatch"
                )
            if intent["pre_state"] == "missing" and state in {"missing", "final"}:
                _bootstrap_fresh_dagster_catalog(connection, version_state=state)
            return "execute", None
        if state == "final":
            raise DagsterStorageMigrationError(
                "dagster_final_head_without_operation_intent"
            )
        inserted = connection.execute(
            text(
                f"INSERT INTO {_INTENT_TABLE} (operation_id, permit_sha256, "
                "candidate_sha256, target_head, pre_state, pre_version_rows, "
                "database_name, database_oid, database_owner, postgres_system_identifier) "
                "VALUES (CAST(:operation_id AS uuid), :permit_sha256, :candidate_sha256, "
                ":target_head, :pre_state, CAST(:pre_rows AS jsonb), :database_name, "
                ":database_oid, :database_owner, :system_identifier) "
                "RETURNING operation_id::text"
            ),
            {
                **binding,
                "target_head": head,
                "pre_state": state,
                "pre_rows": json.dumps(rows, separators=(",", ":")),
                "database_name": identity["name"],
                "database_oid": identity["oid"],
                "database_owner": identity["owner"],
                "system_identifier": identity["system_identifier"],
            },
        ).scalar_one()
        if inserted != binding["operation_id"]:
            raise DagsterStorageMigrationError("dagster_operation_intent_not_committed")
        if state == "missing":
            _bootstrap_fresh_dagster_catalog(connection, version_state=state)
        return "execute", None
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_operation_prepare_failed") from exc


def _complete_operation(
    connection: Any,
    *,
    binding: Mapping[str, str],
    identity: Mapping[str, Any],
    head: str,
) -> dict[str, str]:
    try:
        intent = _read_intent(connection, binding["operation_id"])
        if intent is None:
            raise DagsterStorageMigrationError("dagster_operation_intent_missing")
        _validate_intent(intent, binding=binding, identity=identity, head=head)
        catalog_sha256 = _verify_dagster_catalog(connection, head=head)
        existing = _read_receipt(connection, binding["operation_id"])
        if existing is not None:
            return _validate_receipt(
                existing,
                binding=binding,
                identity=identity,
                head=head,
                catalog_sha256=catalog_sha256,
            )
        result = _migration_result(
            binding=binding,
            identity=identity,
            head=head,
            catalog_sha256=catalog_sha256,
        )
        canonical = _canonical_result_bytes(result)
        inserted = connection.execute(
            text(
                f"INSERT INTO {_RECEIPT_TABLE} (operation_id, result_schema, "
                "result_sha256, final_head, result_payload) VALUES ("
                "CAST(:operation_id AS uuid), :result_schema, :result_sha256, "
                ":final_head, CAST(:result_payload AS jsonb)) RETURNING operation_id::text"
            ),
            {
                "operation_id": binding["operation_id"],
                "result_schema": _MIGRATE_SCHEMA,
                "result_sha256": hashlib.sha256(canonical).hexdigest(),
                "final_head": head,
                "result_payload": canonical.decode().rstrip("\n"),
            },
        ).scalar_one()
        if inserted != binding["operation_id"]:
            raise DagsterStorageMigrationError("dagster_operation_receipt_not_committed")
        return result
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_operation_complete_failed") from exc


def _migrate(environment: Mapping[str, str]) -> dict[str, str]:
    head = _dagster_storage_head()
    dagster_pg_url, identity = _verify_database_identity(environment)
    bound_pg_url, bound_identity, binding = _read_operation_binding(environment)
    if bound_pg_url != dagster_pg_url or dict(bound_identity) != identity:
        raise DagsterStorageMigrationError("dagster_storage_dsn_changed")
    engine = create_engine(dagster_pg_url)
    connection = None
    locked = False
    try:
        connection = engine.connect()
        _acquire_session_operation_lock(connection)
        locked = True
        verified_dagster_pg_url, verified_identity = _verify_database_identity(environment)
        if verified_dagster_pg_url != dagster_pg_url or verified_identity != identity:
            raise DagsterStorageMigrationError("dagster_storage_dsn_changed")
        with connection.begin():
            action, recovered = _prepare_operation(
                connection, binding=binding, identity=identity, head=head
            )
        if action == "done":
            if recovered is None:
                raise DagsterStorageMigrationError("dagster_operation_receipt_invalid")
            return recovered
        _run_dagster_instance_migrate(environment)
        verified_dagster_pg_url, verified_identity = _verify_database_identity(environment)
        if verified_dagster_pg_url != dagster_pg_url or verified_identity != identity:
            raise DagsterStorageMigrationError("dagster_storage_dsn_changed")
        with connection.begin():
            return _complete_operation(
                connection, binding=binding, identity=identity, head=head
            )
    finally:
        active_exception = sys.exc_info()[0] is not None
        release_failure: Exception | None = None
        if connection is not None:
            if locked:
                try:
                    _release_session_operation_lock(connection)
                except Exception as exc:
                    release_failure = exc
            connection.close()
        engine.dispose()
        if release_failure is not None and not active_exception:
            raise release_failure


def _recover(environment: Mapping[str, str], operation_id: UUID) -> dict[str, str]:
    head = _dagster_storage_head()
    dagster_pg_url, identity = _verify_database_identity(environment)
    bound_pg_url, bound_identity, binding = _read_operation_binding(environment)
    if (
        bound_pg_url != dagster_pg_url
        or dict(bound_identity) != identity
        or binding["operation_id"] != str(operation_id)
    ):
        raise DagsterStorageMigrationError("dagster_operation_recovery_binding_mismatch")
    engine = None
    try:
        engine = create_engine(dagster_pg_url)
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            _acquire_shared_transaction_operation_lock(connection)
            state, rows = _read_version_state(connection, head)
            if state != "final" or rows != (head,):
                raise DagsterStorageMigrationError("dagster_version_mismatch")
            intent = _read_intent(connection, binding["operation_id"])
            receipt = _read_receipt(connection, binding["operation_id"])
            if intent is None or receipt is None:
                raise DagsterStorageMigrationError("dagster_operation_receipt_missing")
            _validate_intent(intent, binding=binding, identity=identity, head=head)
            catalog_sha256 = _verify_dagster_catalog(connection, head=head)
            return _validate_receipt(
                receipt,
                binding=binding,
                identity=identity,
                head=head,
                catalog_sha256=catalog_sha256,
            )
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_operation_recovery_failed") from exc
    finally:
        if engine is not None:
            engine.dispose()


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
            _, _, binding = _read_operation_binding(os.environ)
            result = _recover(os.environ, UUID(binding["operation_id"]))
            _emit(
                {
                    "schema": _IDENTITY_SCHEMA,
                    "status": "verified",
                    "database_name": result["database_name"],
                    "database_oid": result["database_oid"],
                }
            )
            return 0
        if arguments == ["migrate"]:
            _emit(_migrate(os.environ))
            return 0
        if len(arguments) == 3 and arguments[:2] == ["recover", "--operation-id"]:
            try:
                operation_id = UUID(arguments[2])
            except ValueError as exc:
                raise DagsterStorageMigrationError(
                    "dagster_operation_id_invalid"
                ) from exc
            if arguments[2] != str(operation_id):
                raise DagsterStorageMigrationError(
                    "dagster_operation_id_invalid"
                )
            _emit(_recover(os.environ, operation_id))
            return 0
        raise DagsterStorageMigrationError("invalid_arguments")
    except DagsterStorageMigrationError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
