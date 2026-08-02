"""H35 Map helper의 stdin request와 stdout receipt 계약."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal, cast
from uuid import UUID

CONTRACT_VERSION: Final = "h35-map/v1"
DATABASE_IDENTITY_ROLE: Final = "map_application"
DATABASE_IDENTITY_PREFIX: Final = b"h35-db-identity-v1\0"
DATABASE_IDENTITY_GOLDEN_VECTOR: Final = {
    "transaction_id": "00000000-0000-0000-0000-000000000001",
    "database": "kor_travel_map",
    "system_identifier": "12345678901234567890",
    "digest": "9bca9b82ad2304759581ebf16e724461fcfd7c657e2b41ce5ae3ae54847dee5a",
}

Operation = Literal["preflight", "migrate", "csv5", "verify"]
Status = Literal["accepted", "rejected", "failed"]
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
Receipt = dict[str, JsonValue]

OPERATIONS: Final[tuple[Operation, ...]] = ("preflight", "migrate", "csv5", "verify")
_PREVIOUS_OPERATION: Final[dict[Operation, Operation | None]] = {
    "preflight": None,
    "migrate": "preflight",
    "csv5": "migrate",
    "verify": "csv5",
}
_EXPECTED_PRIOR_SCHEMA: Final[dict[Operation, str | None]] = {
    "preflight": None,
    "migrate": "0063_pipeline_root_id",
    "csv5": "0078_cache_target_gc_observe",
    "verify": "0078_cache_target_gc_observe",
}
_REQUEST_KEYS: Final = frozenset(
    {
        "contract_version",
        "operation",
        "transaction_id",
        "source_revision",
        "database_identity",
        "prior_receipt",
        "prior_receipt_digest",
    }
)
_RECEIPT_KEYS: Final = frozenset(
    {
        "contract_version",
        "operation",
        "transaction_id",
        "status",
        "source_revision",
        "database_identity",
        "request_digest",
        "prior_receipt_digest",
        "schema_before",
        "schema_after",
        "forward_boundary",
        "row_counts",
        "checks",
        "runtime_mutation_count",
        "external_event_count",
    }
)
_SHA256_LENGTH: Final = 64
_REVISION_LENGTH: Final = 40


class H35ContractError(ValueError):
    """stdin request나 prior receipt가 계약을 위반했다."""


class H35IdentityError(RuntimeError):
    """live database identity를 안전하게 계산할 수 없다."""


@dataclass(frozen=True)
class H35Request:
    operation: Operation
    transaction_id: str
    source_revision: str
    database_identity: str
    prior_receipt: Receipt | None
    prior_receipt_digest: str | None
    request_digest: str


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def receipt_digest(receipt: Mapping[str, object]) -> str:
    """manager journal과 공유하는 canonical receipt SHA-256."""
    return hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()


def compute_database_identity(
    *,
    transaction_id: str,
    database: str,
    system_identifier: str,
) -> str:
    """H35 v1 NUL-framed live database identity를 계산한다."""
    _strict_uuid(transaction_id, field="transaction_id")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database) is None:
        raise H35IdentityError("database_identity_input_invalid")
    if (
        not system_identifier.isascii()
        or not system_identifier.isdigit()
        or not 1 <= len(system_identifier) <= 32
    ):
        raise H35IdentityError("database_identity_input_invalid")
    framed = b"".join(
        (
            DATABASE_IDENTITY_PREFIX,
            transaction_id.encode("ascii"),
            b"\0",
            DATABASE_IDENTITY_ROLE.encode("ascii"),
            b"\0",
            database.encode("ascii"),
            b"\0",
            system_identifier.encode("ascii"),
            b"\0",
        )
    )
    return hashlib.sha256(framed).hexdigest()


def bind_database_identity(
    request: H35Request,
    *,
    database: str,
    system_identifier: str,
) -> tuple[H35Request, dict[str, JsonValue]]:
    """receipt가 request echo 대신 live recomputed identity를 사용하도록 request를 bind한다."""
    observed = compute_database_identity(
        transaction_id=request.transaction_id,
        database=database,
        system_identifier=system_identifier,
    )
    bound = replace(request, database_identity=observed)
    return bound, check(
        "live_database_identity",
        expected=request.database_identity,
        observed=observed,
    )


def strict_hex(value: object, *, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise H35ContractError(f"{field} 형식이 올바르지 않습니다.")
    if value != value.lower() or any(character not in "0123456789abcdef" for character in value):
        raise H35ContractError(f"{field} 형식이 올바르지 않습니다.")
    return value


def _strict_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise H35ContractError(f"{field}는 UUID 문자열이어야 합니다.")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise H35ContractError(f"{field}는 UUID 문자열이어야 합니다.") from exc
    if str(parsed) != value:
        raise H35ContractError(f"{field}는 canonical UUID여야 합니다.")
    return value


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise H35ContractError(f"{field}는 JSON object여야 합니다.")
    return cast("dict[str, object]", value)


def _validate_prior_receipt(
    value: object,
    *,
    operation: Operation,
    digest: str | None,
    transaction_id: str,
    source_revision: str,
    database_identity: str,
) -> Receipt | None:
    previous = _PREVIOUS_OPERATION[operation]
    if previous is None:
        if value is not None or digest is not None:
            raise H35ContractError("preflight prior receipt는 null이어야 합니다.")
        return None
    if digest is None:
        raise H35ContractError("prior_receipt_digest가 필요합니다.")
    raw = _mapping(value, field="prior_receipt")
    if frozenset(raw) != _RECEIPT_KEYS:
        raise H35ContractError("prior_receipt key 집합이 contract와 다릅니다.")
    if receipt_digest(raw) != digest:
        raise H35ContractError("prior_receipt_digest가 receipt와 다릅니다.")
    expected = {
        "contract_version": CONTRACT_VERSION,
        "operation": previous,
        "transaction_id": transaction_id,
        "status": "accepted",
        "source_revision": source_revision,
        "database_identity": database_identity,
        "schema_after": _EXPECTED_PRIOR_SCHEMA[operation],
        "runtime_mutation_count": 0,
        "external_event_count": 0,
    }
    for key, expected_value in expected.items():
        if raw.get(key) != expected_value:
            raise H35ContractError(f"prior_receipt.{key}가 이전 phase와 다릅니다.")
    strict_hex(raw.get("request_digest"), length=_SHA256_LENGTH, field="request_digest")
    return cast("Receipt", raw)


def parse_request(raw_content: str, *, operation: Operation) -> H35Request:
    """stdin 단일 JSON request를 strict하게 검증한다."""
    try:
        raw_value = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise H35ContractError("stdin은 단일 JSON object여야 합니다.") from exc
    raw = _mapping(raw_value, field="request")
    if frozenset(raw) != _REQUEST_KEYS:
        raise H35ContractError("request key 집합이 contract와 다릅니다.")
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise H35ContractError("지원하지 않는 contract_version입니다.")
    if raw.get("operation") != operation:
        raise H35ContractError("CLI operation과 request.operation이 다릅니다.")
    transaction_id = _strict_uuid(raw.get("transaction_id"), field="transaction_id")
    source_revision = strict_hex(
        raw.get("source_revision"), length=_REVISION_LENGTH, field="source_revision"
    )
    database_identity = strict_hex(
        raw.get("database_identity"), length=_SHA256_LENGTH, field="database_identity"
    )
    raw_prior_digest = raw.get("prior_receipt_digest")
    prior_digest = (
        None
        if raw_prior_digest is None
        else strict_hex(
            raw_prior_digest,
            length=_SHA256_LENGTH,
            field="prior_receipt_digest",
        )
    )
    prior_receipt = _validate_prior_receipt(
        raw.get("prior_receipt"),
        operation=operation,
        digest=prior_digest,
        transaction_id=transaction_id,
        source_revision=source_revision,
        database_identity=database_identity,
    )
    return H35Request(
        operation=operation,
        transaction_id=transaction_id,
        source_revision=source_revision,
        database_identity=database_identity,
        prior_receipt=prior_receipt,
        prior_receipt_digest=prior_digest,
        request_digest=hashlib.sha256(canonical_json_bytes(raw)).hexdigest(),
    )


def check(name: str, *, expected: JsonValue, observed: JsonValue) -> dict[str, JsonValue]:
    return {
        "name": name,
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
    }


def all_pass(checks: Sequence[Mapping[str, JsonValue]]) -> bool:
    return all(value.get("passed") is True for value in checks)


def receipt(
    request: H35Request,
    *,
    status: Status,
    schema_before: str,
    schema_after: str,
    forward_boundary: str,
    row_counts: Mapping[str, int],
    checks: Sequence[Mapping[str, JsonValue]],
) -> Receipt:
    return {
        "contract_version": CONTRACT_VERSION,
        "operation": request.operation,
        "transaction_id": request.transaction_id,
        "status": status,
        "source_revision": request.source_revision,
        "database_identity": request.database_identity,
        "request_digest": request.request_digest,
        "prior_receipt_digest": request.prior_receipt_digest,
        "schema_before": schema_before,
        "schema_after": schema_after,
        "forward_boundary": forward_boundary,
        "row_counts": {key: int(value) for key, value in sorted(row_counts.items())},
        "checks": [dict(value) for value in checks],
        "runtime_mutation_count": 0,
        "external_event_count": 0,
    }


__all__ = [
    "CONTRACT_VERSION",
    "DATABASE_IDENTITY_GOLDEN_VECTOR",
    "DATABASE_IDENTITY_PREFIX",
    "DATABASE_IDENTITY_ROLE",
    "OPERATIONS",
    "H35ContractError",
    "H35IdentityError",
    "H35Request",
    "JsonValue",
    "Operation",
    "Receipt",
    "all_pass",
    "bind_database_identity",
    "canonical_json_bytes",
    "check",
    "compute_database_identity",
    "parse_request",
    "receipt",
    "receipt_digest",
    "strict_hex",
]
