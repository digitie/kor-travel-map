"""H35 typed request/receipt 계약의 fail-close 회귀 테스트."""

from __future__ import annotations

import copy
import json

import pytest

from kortravelmap.cli._h35_contract import (
    CONTRACT_VERSION,
    DATABASE_IDENTITY_GOLDEN_VECTOR,
    H35ContractError,
    compute_database_identity,
    parse_request,
    receipt_digest,
)

pytestmark = pytest.mark.unit

_TRANSACTION_ID = "00000000-0000-0000-0000-000000000001"
_SOURCE_REVISION = "1" * 40
_DATABASE_IDENTITY = DATABASE_IDENTITY_GOLDEN_VECTOR["digest"]


def _request(
    operation: str,
    *,
    prior_receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "operation": operation,
        "transaction_id": _TRANSACTION_ID,
        "source_revision": _SOURCE_REVISION,
        "database_identity": _DATABASE_IDENTITY,
        "prior_receipt": prior_receipt,
        "prior_receipt_digest": (
            receipt_digest(prior_receipt) if prior_receipt is not None else None
        ),
    }


def _receipt(
    operation: str,
    *,
    schema_before: str,
    schema_after: str,
    prior_receipt_digest: str | None = None,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "operation": operation,
        "transaction_id": _TRANSACTION_ID,
        "status": "accepted",
        "source_revision": _SOURCE_REVISION,
        "database_identity": _DATABASE_IDENTITY,
        "request_digest": "2" * 64,
        "prior_receipt_digest": prior_receipt_digest,
        "schema_before": schema_before,
        "schema_after": schema_after,
        "forward_boundary": (
            "not_crossed"
            if schema_after == "0063_pipeline_root_id"
            else "schema_0078"
        ),
        "row_counts": {},
        "checks": [],
        "runtime_mutation_count": 0,
        "external_event_count": 0,
    }


def test_database_identity_golden_vector_is_exact() -> None:
    assert (
        compute_database_identity(
            transaction_id=DATABASE_IDENTITY_GOLDEN_VECTOR["transaction_id"],
            database=DATABASE_IDENTITY_GOLDEN_VECTOR["database"],
            system_identifier=DATABASE_IDENTITY_GOLDEN_VECTOR["system_identifier"],
        )
        == DATABASE_IDENTITY_GOLDEN_VECTOR["digest"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "h35-map/v0"),
        ("operation", "verify"),
        ("transaction_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("source_revision", "A" * 40),
        ("source_revision", "1" * 39),
        ("database_identity", "A" * 64),
        ("database_identity", "1" * 63),
    ],
)
def test_preflight_rejects_wrong_or_noncanonical_request_fields(
    field: str,
    value: object,
) -> None:
    request = _request("preflight")
    request[field] = value

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(request), operation="preflight")


@pytest.mark.parametrize("unknown_value", [None, 0, False, [], "value"])
def test_request_rejects_unknown_key(unknown_value: object) -> None:
    request = _request("preflight")
    request["unknown"] = unknown_value

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(request), operation="preflight")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "null",
        "[]",
        "not-json",
        "{} {}",
        '{"operation":"preflight"}',
    ],
)
def test_request_rejects_non_object_or_incomplete_stdin(raw: str) -> None:
    with pytest.raises(H35ContractError):
        parse_request(raw, operation="preflight")


def test_request_rejects_duplicate_json_keys() -> None:
    raw = json.dumps(_request("preflight"))
    duplicate = raw.replace(
        '"operation": "preflight"',
        '"operation": "verify", "operation": "preflight"',
    )

    with pytest.raises(H35ContractError):
        parse_request(duplicate, operation="preflight")


def test_request_rejects_nested_duplicate_json_keys() -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    raw = json.dumps(_request("migrate", prior_receipt=prior))
    duplicate = raw.replace('"row_counts": {}', '"row_counts": {"count": 0, "count": 1}')

    with pytest.raises(H35ContractError):
        parse_request(duplicate, operation="migrate")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_request_rejects_non_json_numeric_constants(constant: str) -> None:
    raw = json.dumps(_request("preflight"))
    ambiguous = raw[:-1] + f', "unknown": {constant}}}'

    with pytest.raises(H35ContractError):
        parse_request(ambiguous, operation="preflight")


def test_preflight_rejects_any_prior_receipt() -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(_request("preflight", prior_receipt=prior)), operation="preflight")


def test_phase_chain_accepts_exact_receipts() -> None:
    preflight = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    migrate_request = parse_request(
        json.dumps(_request("migrate", prior_receipt=preflight)),
        operation="migrate",
    )
    migrate = _receipt(
        "migrate",
        schema_before="0063_pipeline_root_id",
        schema_after="0078_cache_target_gc_observe",
        prior_receipt_digest=migrate_request.prior_receipt_digest,
    )
    csv5_request = parse_request(
        json.dumps(_request("csv5", prior_receipt=migrate)),
        operation="csv5",
    )
    csv5 = _receipt(
        "csv5",
        schema_before="0078_cache_target_gc_observe",
        schema_after="0078_cache_target_gc_observe",
        prior_receipt_digest=csv5_request.prior_receipt_digest,
    )

    parsed = parse_request(
        json.dumps(_request("verify", prior_receipt=csv5)),
        operation="verify",
    )

    assert parsed.prior_receipt == csv5
    assert parsed.prior_receipt_digest == receipt_digest(csv5)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", "verify"),
        ("transaction_id", "00000000-0000-0000-0000-000000000002"),
        ("status", "rejected"),
        ("source_revision", "3" * 40),
        ("database_identity", "4" * 64),
        ("schema_after", "0077_cache_target_snapshot_gc"),
        ("runtime_mutation_count", 1),
        ("external_event_count", 1),
    ],
)
def test_migrate_rejects_mixed_or_stale_prior_receipt(
    field: str,
    value: object,
) -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    prior[field] = value

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(_request("migrate", prior_receipt=prior)), operation="migrate")


def test_migrate_rejects_prior_receipt_digest_mismatch() -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    request = _request("migrate", prior_receipt=prior)
    request["prior_receipt_digest"] = "f" * 64

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(request), operation="migrate")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("forward_boundary", "schema_0078"),
        ("row_counts", None),
        ("row_counts", {"public_items": -1}),
        ("checks", None),
        (
            "checks",
            [{"name": "schema_before", "expected": "0063", "observed": "bad", "passed": False}],
        ),
    ],
)
def test_migrate_rejects_semantically_invalid_accepted_receipt(
    field: str,
    value: object,
) -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    prior[field] = value

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(_request("migrate", prior_receipt=prior)), operation="migrate")


def test_migrate_rejects_prior_receipt_after_digest_bound_content_changes() -> None:
    prior = _receipt(
        "preflight",
        schema_before="0063_pipeline_root_id",
        schema_after="0063_pipeline_root_id",
    )
    request = _request("migrate", prior_receipt=prior)
    mutated = copy.deepcopy(prior)
    mutated["row_counts"] = {"public_items": 3_264}
    request["prior_receipt"] = mutated

    with pytest.raises(H35ContractError):
        parse_request(json.dumps(request), operation="migrate")


@pytest.mark.parametrize(
    ("database", "system_identifier"),
    [
        ("KorTravelMap", "123"),
        ("kor-travel-map", "123"),
        ("kor_travel_map", ""),
        ("kor_travel_map", "１２３"),
        ("kor_travel_map", "1" * 33),
    ],
)
def test_database_identity_rejects_noncanonical_live_inputs(
    database: str,
    system_identifier: str,
) -> None:
    with pytest.raises((H35ContractError, RuntimeError)):
        compute_database_identity(
            transaction_id=_TRANSACTION_ID,
            database=database,
            system_identifier=system_identifier,
        )
