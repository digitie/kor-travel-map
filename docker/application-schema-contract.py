#!/usr/local/bin/python -I
"""설치된 candidate image의 immutable application ``300`` 계약을 DB 없이 증명한다.

Docker Manager는 mutable tag나 source checkout을 application baseline authority로
해석하지 않는다. 이 executable은 image 안의 root-owned baseline artifacts만 읽고
한 줄 JSON contract를 반환한다. credential, database connection, 환경변수, 현재
작업 디렉터리는 사용하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])
_REFERENCE_SCHEMA: Final = "kor-travel-map.application-baseline-reference.v1"
_CONTRACT_SCHEMA: Final = "kor-travel-map.application-baseline-contract.v1"
_ERROR_SCHEMA: Final = "kor-travel-map.application-baseline-contract-error.v1"
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_HEAD: Final = "300"
_RECEIPT_ARTIFACTS: Final = {
    "source_catalog_sha256": (
        "source_catalog_contract_sha256",
        "source_catalog_contract_receipt_sha256",
        "application-source-catalog.sha256",
    ),
    "destination_catalog_sha256": (
        "destination_catalog_contract_sha256",
        "destination_catalog_contract_receipt_sha256",
        "application-destination-catalog.sha256",
    ),
    "seed_sha256": (
        "seed_contract_sha256",
        "seed_contract_receipt_sha256",
        "application-seed.sha256",
    ),
    "privileged_residue_sha256": (
        "privileged_residue_contract_sha256",
        "privileged_residue_contract_receipt_sha256",
        "application-privileged-residue.sha256",
    ),
    "source_alembic_version_sha256": (
        "source_alembic_version_contract_sha256",
        "source_alembic_version_contract_receipt_sha256",
        "application-source-alembic-version.sha256",
    ),
    "destination_alembic_version_sha256": (
        "destination_alembic_version_contract_sha256",
        "destination_alembic_version_contract_receipt_sha256",
        "application-destination-alembic-version.sha256",
    ),
}
_SQL_ARTIFACTS: Final = {
    "schema_sql_sha256": "schema.sql",
    "seed_sql_sha256": "seed.sql",
    "catalog_contract_sql_sha256": "application-catalog.sql",
    "seed_contract_sql_sha256": "application-seed.sql",
    "privileged_residue_contract_sql_sha256": "application-privileged-residue.sql",
    "source_alembic_version_contract_sql_sha256": (
        "application-source-alembic-version.sql"
    ),
    "destination_alembic_version_contract_sql_sha256": (
        "application-destination-alembic-version.sql"
    ),
    "runtime_invariants_sql_sha256": "application-runtime-invariants.sql",
}


class ApplicationSchemaContractError(RuntimeError):
    """immutable application baseline contract를 안전하게 읽을 수 없을 때의 오류."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _application_root() -> Path:
    for candidate in _APPLICATION_ROOT_CANDIDATES:
        baseline = candidate / "alembic" / "baseline"
        if (baseline / "application-reference.json").is_file() and (
            baseline / "application-reference.sha256"
        ).is_file():
            return candidate
    raise ApplicationSchemaContractError("installed_application_baseline_unavailable")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_sha256(path: Path) -> str:
    try:
        raw = path.read_bytes()
        value = raw.decode("ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ApplicationSchemaContractError("installed_application_baseline_invalid") from exc
    if not _SHA256_PATTERN.fullmatch(value) or raw != f"{value}\n".encode("ascii"):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    return value


def _artifact_digest(manifest: Mapping[str, Any], name: str) -> str:
    value = manifest.get(name)
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    return value


def application_contract() -> Mapping[str, str]:
    """image package data와 baseline receipt가 하나의 immutable contract인지 검증한다."""

    baseline = _application_root() / "alembic" / "baseline"
    reference_path = baseline / "application-reference.json"
    try:
        reference_raw = reference_path.read_bytes()
        reference = json.loads(reference_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationSchemaContractError("installed_application_baseline_unavailable") from exc
    if not isinstance(reference, Mapping) or reference.get("schema") != _REFERENCE_SCHEMA:
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    if _sha256_bytes(reference_raw) != _read_sha256(baseline / "application-reference.sha256"):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    for manifest_key, filename in _SQL_ARTIFACTS.items():
        path = baseline / filename
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ApplicationSchemaContractError(
                "installed_application_baseline_unavailable"
            ) from exc
        if _sha256_bytes(raw) != _artifact_digest(artifacts, manifest_key):
            raise ApplicationSchemaContractError("installed_application_baseline_invalid")

    output: dict[str, str] = {
        "schema": _CONTRACT_SCHEMA,
        "application_head": _HEAD,
        "reference_manifest_sha256": _sha256_bytes(reference_raw),
    }
    source = reference.get("source")
    if not isinstance(source, Mapping):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    postgres_image_id = source.get("container_image_id")
    if not isinstance(postgres_image_id, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", postgres_image_id
    ):
        raise ApplicationSchemaContractError("installed_application_baseline_invalid")
    output["postgres_image_id"] = postgres_image_id
    for output_key, (contract_key, receipt_key, filename) in _RECEIPT_ARTIFACTS.items():
        expected = _artifact_digest(artifacts, contract_key)
        receipt_digest = _artifact_digest(artifacts, receipt_key)
        path = baseline / filename
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ApplicationSchemaContractError(
                "installed_application_baseline_unavailable"
            ) from exc
        if _sha256_bytes(content) != receipt_digest or _read_sha256(path) != expected:
            raise ApplicationSchemaContractError("installed_application_baseline_invalid")
        output[output_key] = expected
    runtime_digest = _artifact_digest(artifacts, "runtime_invariants_sql_sha256")
    output["runtime_invariants_sql_sha256"] = runtime_digest
    return output


def _emit(payload: Mapping[str, str], *, stream: TextIO = sys.stdout) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=stream)


def main(arguments: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    try:
        if values != ["contract"]:
            raise ApplicationSchemaContractError("invalid_arguments")
        _emit(application_contract())
        return 0
    except ApplicationSchemaContractError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
