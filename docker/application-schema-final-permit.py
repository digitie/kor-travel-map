#!/usr/local/bin/python
"""Docker Manager final permit을 검사하는 production runtime gate.

permit은 DB 안의 application-writable flag가 아니다. Manager가 host root 경계에서
candidate/DB/receipt를 finalise한 뒤 read-only mount하는 공개용 digest receipt다. 이
executable은 fixed mount의 owner/mode·정확한 JSON field set·candidate artifact binding과
runtime DSN이 실제 가리키는 database name/OID를 확인한다. 비밀, user mapping identity,
superuser DSN은 permit이나 출력에 포함하지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine

_PERMIT_PATH: Final = Path("/run/kor-travel-map-application-final-permit/permit.json")
_PERMIT_SCHEMA: Final = "kor-travel-docker-manager.map-application-final-permit.v2"
_PERMIT_TRANSITIONS: Final = frozenset(
    {
        "map-application-schema-0236-to-300",
        "map-fresh-300",
        "map-fresh-300-finalize",
    }
)
_IMAGE_REVISION_ENV: Final = "KOR_TRAVEL_MAP_IMAGE_REVISION"
_API_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID"
_DAGSTER_IMAGE_ID_ENV: Final = "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_DAGSTER_IMAGE_ID"
_API_RUNTIME_DSN_ENV: Final = "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN"
_DAGSTER_RUNTIME_DSN_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_DATABASE_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_DATABASE_OWNER: Final = "ktm_feature_schema_owner"
_TOP_LEVEL_FIELDS: Final = frozenset(
    {"schema", "transition_kind", "state", "transaction_id", "candidate", "database", "receipts"}
)
_CANDIDATE_FIELDS: Final = frozenset(
    {
        "map_source_commit",
        "api_image_id",
        "dagster_image_id",
        "postgres_image_id",
        "application_head",
        "reference_manifest_sha256",
        "source_alembic_version_sha256",
        "destination_alembic_version_sha256",
        "runtime_invariants_sql_sha256",
    }
)
_DATABASE_FIELDS: Final = frozenset(
    {"name", "oid", "owner", "system_identifier", "identity_sha256"}
)
_RECEIPT_FIELDS: Final = frozenset(
    {
        "expected_catalog_sha256",
        "observed_catalog_sha256",
        "expected_seed_sha256",
        "observed_seed_sha256",
        "expected_privileged_residue_sha256",
        "pre_privileged_residue_sha256",
        "post_privileged_residue_sha256",
        "expected_destination_alembic_version_sha256",
        "observed_destination_alembic_version_sha256",
        "runtime_invariant_violation_count",
    }
)
_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])


class FinalPermitError(RuntimeError):
    """runtime start 전에 permit을 fail-close할 때 쓰는 안정된 오류."""


def _require_exact_fields(value: object, expected: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise FinalPermitError(f"final permit {label} field set is invalid")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise FinalPermitError(f"final permit {label} digest is invalid")
    return value


def _application_root() -> Path:
    for candidate in _APPLICATION_ROOT_CANDIDATES:
        if (candidate / "alembic" / "baseline" / "application-reference.json").is_file():
            return candidate
    raise FinalPermitError("installed application baseline reference is unavailable")


def _database_identity_sha256(
    *, system_identifier: str, name: str, oid: int, owner: str
) -> str:
    """Manager permit와 runtime이 공유하는 non-secret database identity preimage."""

    value = (
        "kor-travel-map.application-final-permit-database.v1\0"
        f"{system_identifier}\0{name}\0{oid}\0{owner}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_reference() -> tuple[str, Mapping[str, Any]]:
    path = _application_root() / "alembic" / "baseline" / "application-reference.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalPermitError("installed application baseline reference is unreadable") from exc
    if not isinstance(value, Mapping) or value.get("schema") != (
        "kor-travel-map.application-baseline-reference.v1"
    ):
        raise FinalPermitError("installed application baseline reference is invalid")
    return hashlib.sha256(raw).hexdigest(), value


def _require_fixed_file() -> bytes:
    try:
        directory = _PERMIT_PATH.parent
        directory_metadata = directory.lstat()
        file_metadata = _PERMIT_PATH.lstat()
    except OSError as exc:
        raise FinalPermitError("final permit is unavailable") from exc
    if (
        not stat.S_ISDIR(directory_metadata.st_mode)
        or stat.S_ISLNK(directory_metadata.st_mode)
        or directory_metadata.st_uid != 0
        or stat.S_IMODE(directory_metadata.st_mode) & 0o022
    ):
        raise FinalPermitError("final permit directory metadata is unsafe")
    if (
        not stat.S_ISREG(file_metadata.st_mode)
        or stat.S_ISLNK(file_metadata.st_mode)
        or file_metadata.st_uid != 0
        or stat.S_IMODE(file_metadata.st_mode) != 0o444
        or file_metadata.st_nlink != 1
    ):
        raise FinalPermitError("final permit file metadata is unsafe")
    try:
        descriptor = os.open(_PERMIT_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != 0
                or stat.S_IMODE(opened.st_mode) != 0o444
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino)
                != (file_metadata.st_dev, file_metadata.st_ino)
            ):
                raise FinalPermitError("final permit changed while opening")
            raw = os.read(descriptor, 262_144)
            if os.read(descriptor, 1):
                raise FinalPermitError("final permit is too large")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise FinalPermitError("final permit cannot be read") from exc


def _validate_permit(raw: bytes, *, consumer: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalPermitError("final permit JSON is invalid") from exc
    payload = _require_exact_fields(value, _TOP_LEVEL_FIELDS, "top-level")
    if payload["schema"] != _PERMIT_SCHEMA:
        raise FinalPermitError("final permit schema is invalid")
    if payload["transition_kind"] not in _PERMIT_TRANSITIONS:
        raise FinalPermitError("final permit transition kind is invalid")
    if payload["state"] != "finalized":
        raise FinalPermitError("final permit is not finalized")
    try:
        UUID(str(payload["transaction_id"]))
    except (TypeError, ValueError) as exc:
        raise FinalPermitError("final permit transaction id is invalid") from exc

    candidate = _require_exact_fields(payload["candidate"], _CANDIDATE_FIELDS, "candidate")
    database = _require_exact_fields(payload["database"], _DATABASE_FIELDS, "database")
    receipts = _require_exact_fields(payload["receipts"], _RECEIPT_FIELDS, "receipts")
    if (
        not isinstance(candidate["map_source_commit"], str)
        or not _COMMIT_PATTERN.fullmatch(candidate["map_source_commit"])
        or not isinstance(candidate["api_image_id"], str)
        or not _IMAGE_ID_PATTERN.fullmatch(candidate["api_image_id"])
        or not isinstance(candidate["dagster_image_id"], str)
        or not _IMAGE_ID_PATTERN.fullmatch(candidate["dagster_image_id"])
        or not isinstance(candidate["postgres_image_id"], str)
        or not _IMAGE_ID_PATTERN.fullmatch(candidate["postgres_image_id"])
        or candidate["application_head"] != "300"
    ):
        raise FinalPermitError("final permit candidate identity is invalid")
    _require_sha256(candidate["reference_manifest_sha256"], "reference manifest")
    _require_sha256(candidate["source_alembic_version_sha256"], "source Alembic facet")
    _require_sha256(
        candidate["destination_alembic_version_sha256"], "destination Alembic facet"
    )
    _require_sha256(candidate["runtime_invariants_sql_sha256"], "runtime invariants")
    if (
        not isinstance(database["name"], str)
        or not _DATABASE_PATTERN.fullmatch(database["name"])
        or type(database["oid"]) is not int
        or database["oid"] <= 0
        or database["owner"] != _DATABASE_OWNER
        or not isinstance(database["system_identifier"], str)
        or not database["system_identifier"].isdigit()
    ):
        raise FinalPermitError("final permit database identity is invalid")
    _require_sha256(database["identity_sha256"], "database identity")
    if database["identity_sha256"] != _database_identity_sha256(
        system_identifier=database["system_identifier"],
        name=database["name"],
        oid=database["oid"],
        owner=database["owner"],
    ):
        raise FinalPermitError("final permit database identity digest is invalid")
    for field in _RECEIPT_FIELDS - {"runtime_invariant_violation_count"}:
        _require_sha256(receipts[field], field)
    if (
        type(receipts["runtime_invariant_violation_count"]) is not int
        or receipts["runtime_invariant_violation_count"] != 0
    ):
        raise FinalPermitError("final permit runtime invariant receipt is invalid")

    reference_sha256, reference = _read_reference()
    artifacts = reference.get("artifacts")
    source = reference.get("source")
    if not isinstance(artifacts, Mapping) or not isinstance(source, Mapping):
        raise FinalPermitError("installed application baseline artifact map is invalid")
    source_postgres_image_id = source.get("container_image_id")
    if (
        not isinstance(source_postgres_image_id, str)
        or not _IMAGE_ID_PATTERN.fullmatch(source_postgres_image_id)
        or candidate["postgres_image_id"] != source_postgres_image_id
    ):
        raise FinalPermitError("final permit database image does not match installed baseline")
    expected = {
        "catalog": artifacts.get("catalog_contract_sha256"),
        "seed": artifacts.get("seed_contract_sha256"),
        "privileged_residue": artifacts.get("privileged_residue_contract_sha256"),
        "source_alembic_version": artifacts.get(
            "source_alembic_version_contract_sha256"
        ),
        "destination_alembic_version": artifacts.get(
            "destination_alembic_version_contract_sha256"
        ),
        "runtime_invariants": artifacts.get("runtime_invariants_sql_sha256"),
    }
    if not all(
        isinstance(value, str) and _SHA256_PATTERN.fullmatch(value)
        for value in expected.values()
    ):
        raise FinalPermitError("installed application baseline receipt is invalid")
    if (
        candidate["reference_manifest_sha256"] != reference_sha256
        or receipts["expected_catalog_sha256"] != expected["catalog"]
        or receipts["observed_catalog_sha256"] != expected["catalog"]
        or receipts["expected_seed_sha256"] != expected["seed"]
        or receipts["observed_seed_sha256"] != expected["seed"]
        or receipts["expected_privileged_residue_sha256"] != expected["privileged_residue"]
        or receipts["pre_privileged_residue_sha256"] != expected["privileged_residue"]
        or receipts["post_privileged_residue_sha256"] != expected["privileged_residue"]
        or candidate["source_alembic_version_sha256"]
        != expected["source_alembic_version"]
        or candidate["destination_alembic_version_sha256"]
        != expected["destination_alembic_version"]
        or receipts["expected_destination_alembic_version_sha256"]
        != expected["destination_alembic_version"]
        or receipts["observed_destination_alembic_version_sha256"]
        != expected["destination_alembic_version"]
        or candidate["runtime_invariants_sql_sha256"] != expected["runtime_invariants"]
    ):
        raise FinalPermitError("final permit receipt does not match installed baseline")

    if consumer == "api":
        image_id_env = _API_IMAGE_ID_ENV
        expected_image_id = candidate["api_image_id"]
    elif consumer == "dagster":
        image_id_env = _DAGSTER_IMAGE_ID_ENV
        expected_image_id = candidate["dagster_image_id"]
    else:
        raise FinalPermitError("final permit consumer is invalid")
    image_revision = os.environ.get(_IMAGE_REVISION_ENV)
    image_id = os.environ.get(image_id_env)
    if (
        image_revision != candidate["map_source_commit"]
        or image_id != expected_image_id
    ):
        raise FinalPermitError("final permit candidate does not match this Map image")
    return payload


def _runtime_dsn(consumer: str) -> str:
    if consumer == "api":
        environment_name = _API_RUNTIME_DSN_ENV
    elif consumer == "dagster":
        environment_name = _DAGSTER_RUNTIME_DSN_ENV
    else:
        raise FinalPermitError("final permit consumer is invalid")
    dsn = os.environ.get(environment_name)
    if not dsn:
        raise FinalPermitError(f"{environment_name} is required for final permit validation")
    return dsn


async def _verify_database(payload: Mapping[str, Any], *, consumer: str) -> None:
    dsn = _runtime_dsn(consumer)
    expected_login = (
        "ktm_feature_api_runtime"
        if consumer == "api"
        else "ktm_feature_dagster_runtime"
    )
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT session_user::text, current_user::text, "
                        "role.rolsuper, "
                        "pg_catalog.pg_has_role(session_user, "
                        "'ktm_feature_schema_owner', 'SET'), "
                        "database_row.datname, database_row.oid, "
                        "pg_catalog.pg_get_userbyid(database_row.datdba), "
                        "(SELECT system_identifier::text "
                        "FROM pg_catalog.pg_control_system()) "
                        "FROM pg_catalog.pg_database AS database_row "
                        "JOIN pg_catalog.pg_roles AS role "
                        "ON role.rolname = session_user "
                        "WHERE database_row.datname = current_database()"
                    )
                )
            ).one()
            versions = tuple(
                str(value)
                for value in (
                    await connection.scalars(
                        text(
                            "SELECT version_num FROM public.alembic_version "
                            "ORDER BY version_num"
                        )
                    )
                ).all()
            )
            live_destination_facet = await _live_destination_facet_sha256(connection)
    except Exception as exc:  # database driver messages can contain an authority/host
        raise FinalPermitError("final permit database binding cannot be verified") from exc
    finally:
        await engine.dispose()
    database = payload["database"]
    observed_identity = _database_identity_sha256(
        system_identifier=str(row[7]),
        name=str(row[4]),
        oid=int(row[5]),
        owner=str(row[6]),
    )
    if (
        str(row[0]) != expected_login
        or str(row[1]) != expected_login
        or bool(row[2])
        or bool(row[3])
        or str(row[4]) != database["name"]
        or int(row[5]) != database["oid"]
        or str(row[6]) != database["owner"]
        or str(row[7]) != database["system_identifier"]
        or observed_identity != database["identity_sha256"]
        or versions != ("300",)
        or live_destination_facet
        != payload["receipts"]["observed_destination_alembic_version_sha256"]
        or live_destination_facet
        != payload["candidate"]["destination_alembic_version_sha256"]
    ):
        raise FinalPermitError(
            "final permit database binding or raw revision does not match runtime DSN"
        )


async def _live_destination_facet_sha256(connection: Any) -> str:
    """runtime login으로 현재 public Alembic metadata ACL까지 다시 증명한다."""

    baseline = _application_root() / "alembic" / "baseline"
    reference_sha256, reference = _read_reference()
    del reference_sha256
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise FinalPermitError("installed application baseline artifact map is invalid")
    sql_path = baseline / "application-destination-alembic-version.sql"
    receipt_path = baseline / "application-destination-alembic-version.sha256"
    try:
        sql_raw = sql_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
        receipt_value = receipt_raw.decode("ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise FinalPermitError("installed destination Alembic facet is unavailable") from exc
    if (
        hashlib.sha256(sql_raw).hexdigest()
        != artifacts.get("destination_alembic_version_contract_sql_sha256")
        or hashlib.sha256(receipt_raw).hexdigest()
        != artifacts.get("destination_alembic_version_contract_receipt_sha256")
        or receipt_raw != f"{receipt_value}\n".encode("ascii")
        or receipt_value
        != artifacts.get("destination_alembic_version_contract_sha256")
        or not _SHA256_PATTERN.fullmatch(receipt_value)
    ):
        raise FinalPermitError("installed destination Alembic facet is invalid")
    try:
        sql_value = sql_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FinalPermitError("installed destination Alembic facet is invalid") from exc
    try:
        rows = await connection.execute(text(sql_value))
    except Exception as exc:
        raise FinalPermitError("live destination Alembic facet cannot be verified") from exc
    digest = hashlib.sha256()
    for item in rows.scalars():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


async def async_main(arguments: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values == ["verify-api"]:
        consumer = "api"
    elif values == ["verify-dagster"]:
        consumer = "dagster"
    else:
        print(
            "final permit verifier accepts only fixed `verify-api` or `verify-dagster` operations",
            file=sys.stderr,
        )
        return 1
    try:
        payload = _validate_permit(_require_fixed_file(), consumer=consumer)
        await _verify_database(payload, consumer=consumer)
    except FinalPermitError as exc:
        print(f"application final permit refused: {exc}", file=sys.stderr)
        return 1
    print("application final permit verified")
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
