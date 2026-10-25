"""decoder/읽기 TX 계약. synthetic wire는 실제 SD·SDK 의미 증거가 아니다."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.transport_rest_evidence_reader import (
    RestEvidenceReason,
    decode_transport_rest_evidence,
    read_transport_rest_evidence,
)


def _rejection() -> dict[str, object]:
    return {
        "version": 1,
        "dataset_id": 15,
        "evidence_complete": False,
        "db_scope_eof": False,
        "reason": "budget_exceeded",
        "policy_epoch": None,
        "items": [],
    }


def _wire() -> dict[str, object]:
    """lineage를 만족하는 synthetic wire. base 값 의미는 후속 SQL/native가 검증한다."""
    instant = "2026-10-25T00:00:00+00:00"
    key = _make_source_entity_key(
        provider="kor-travel-transport",
        dataset_key="transport_rest_areas",
        source_entity_type="rest_area",
        source_entity_id="test::route::direction",
    )
    raw = {
        "natural_key": "test::route::direction",
        "name": "TEST",
        "route_name": "route",
        "direction": "direction",
        "lon": None,
        "lat": None,
        "phone_number": None,
    }
    digest = make_payload_hash(raw)
    record_key = make_source_record_key(
        provider="kor-travel-transport",
        dataset_key="transport_rest_areas",
        source_entity_type="rest_area",
        source_entity_id="test::route::direction",
        raw_payload_hash=digest,
    )
    fid = "45b6b1f3-8a85-4984-932f-dc04358cb08b"
    record = {
        "source_record_key": record_key,
        "source_entity_key": key,
        "raw_payload_hash": digest,
        "raw_data": raw,
        "fetched_at": instant,
        "imported_at": instant,
    }
    base = {
        "feature_id": fid,
        "field_path": "core.name",
        "provider_dataset_id": 15,
        "source_entity_key": key,
        "source_record_key": record_key,
        "source_raw_payload_hash": digest,
        "value_json": "TEST",
        "base_revision": 1,
        "observed_at": instant,
        "value_json_sql_null": False,
        "value_geometry_sql_null": True,
        "geometry_ewkb": None,
    }
    paths = (
        "core.category",
        "core.coord",
        "core.coord_precision_digits",
        "core.address",
        "core.legal_dong_code",
        "core.road_name_code",
        "core.road_address_management_no",
        "core.admin_dong_code",
        "core.sido_code",
        "core.sigungu_code",
        "core.urls",
        "core.marker_icon",
        "core.marker_color",
        "core.parent_feature_id",
        "core.sibling_group_id",
        "core.raw_refs",
        "place.place_kind",
        "place.biz_number",
        "place.license_date",
        "place.business_hours",
        "place.facility_info",
        "place.reviews_link",
        "place.payload",
    )
    item = {
        "source_entity": {
            "source_entity_key": key,
            "source_entity_type": "rest_area",
            "source_entity_id": "test::route::direction",
            "provider_dataset_id": 15,
            "first_seen_at": instant,
            "last_seen_at": instant,
        },
        "source_head": {
            "source_entity_key": key,
            "current_source_record_key": record_key,
            "lineage_key": "fixture",
            "observed_at": instant,
            "expires_at": None,
        },
        "feature": {
            "feature_id": fid,
            "kind": "place",
            "lifecycle_state": "active",
            "publication_state": "published",
            "quality_state": "valid",
            "row_revision": 1,
            "coord_precision_digits": None,
            "geometry_ewkb": None,
            "coord_sql_null": True,
            "address": {},
            "legal_dong_code": None,
            "road_name_code": None,
            "road_address_management_no": None,
            "admin_dong_code": None,
            "sido_code": None,
            "sigungu_code": None,
        },
        "claim": {
            "feature_id": fid,
            "provider_dataset_id": 15,
            "feature_kind": "place",
            "natural_key": "test::route::direction",
        },
        "membership": {"source_entity_key": key, "source_role": "primary", "feature_id": fid},
        "active_policy": {"feature_id": fid, "policy_revision": 1, "field_paths": ["core.name"]},
        "policy": {
            "provider_dataset_id": 15,
            "policy_revision": 1,
            "normalizer_revision": "transport-rest-area-name-phones-v1",
            "fields": [
                {
                    "field_path": "core.name",
                    "provider_rank": 100,
                    "null_policy": "value",
                    "omitted_policy": "carry_forward",
                }
            ],
        },
        "name_candidate": {
            "feature_id": fid,
            "policy_revision": 1,
            "provider_dataset_id": 15,
            "field_path": "core.name",
            "source_entity_key": key,
            "value_source_record_key": record_key,
            "value_source_hash": digest,
            "validated_source_record_key": record_key,
            "validated_source_hash": digest,
            "value_json": "TEST",
            "availability": "value",
            "reason": "supplied",
            "value_observed_at": instant,
            "validated_at": instant,
            "normalizer_revision": "transport-rest-area-name-phones-v1",
            "value_json_sql_null": False,
            "value_geometry_sql_null": True,
            "geometry_ewkb": None,
        },
        "name_base": base,
        "non_scalar_base": [{**base, "field_path": path, "value_json": None} for path in paths],
        "base_record": deepcopy(record),
        "name_value_record": deepcopy(record),
        "current_record": deepcopy(record),
        "geocode_stamp": None,
    }
    item["active_policy"]["field_paths"] = ["core.name", "place.phones"]
    item["policy"]["fields"].append(
        {
            "field_path": "place.phones",
            "provider_rank": 100,
            "null_policy": "value",
            "omitted_policy": "carry_forward",
        }
    )
    item["phones_candidate"] = {
        **item["name_candidate"],
        "field_path": "place.phones",
        "value_json": [],
    }
    item["phones_base"] = {**base, "field_path": "place.phones", "value_json": []}
    item["phones_value_record"] = deepcopy(record)
    return {
        "version": 1,
        "dataset_id": 15,
        "evidence_complete": True,
        "db_scope_eof": True,
        "reason": None,
        "policy_epoch": 0,
        "items": [item],
    }


def test_lineage_wire_is_not_promoted_to_collector_authority() -> None:
    result = decode_transport_rest_evidence(15, _wire())
    assert result.evidence_complete
    assert result.db_scope_eof
    assert len(result.items) == 1
    assert result.collector_ready is False


def test_known_rejection_is_whole_and_keeps_no_items() -> None:
    result = decode_transport_rest_evidence(15, _rejection())
    assert result.reason is RestEvidenceReason.BUDGET_EXCEEDED
    assert result.items == ()
    assert not result.db_scope_eof


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", True),
        ("dataset_id", 16),
        ("db_scope_eof", True),
        ("items", [{}]),
        ("policy_epoch", 0),
        ("reason", "surprise"),
        ("extra", None),
    ],
)
def test_rejection_schema_is_fail_closed(key: str, value: object) -> None:
    wire = _rejection()
    wire[key] = value
    with pytest.raises(ValueError, match="rest evidence"):
        decode_transport_rest_evidence(15, wire)


@pytest.mark.parametrize(
    ("row", "key", "value"),
    [
        ("source_entity", "source_entity_key", "se_" + "f" * 64),
        ("current_record", "raw_payload_hash", "f" * 64),
        ("name_value_record", "source_record_key", "sr_" + "f" * 20),
        ("membership", "source_role", "enrichment"),
        ("claim", "provider_dataset_id", 16),
        ("name_candidate", "validated_source_hash", "f" * 64),
        ("name_candidate", "normalizer_revision", "old-unknown"),
        ("name_candidate", "value_observed_at", "2026-10-26T00:00:00+00:00"),
        ("name_base", "source_entity_key", "se_" + "f" * 64),
        ("feature", "row_revision", True),
    ],
)
def test_source_policy_and_clock_mismatch_is_not_silently_accepted(
    row: str, key: str, value: object
) -> None:
    wire = _wire()
    wire["items"][0][row][key] = value
    with pytest.raises(ValueError, match="rest evidence"):
        decode_transport_rest_evidence(15, wire)


def test_all_non_scalar_clocks_are_preserved_without_imposing_array_order() -> None:
    wire = _wire()
    wire["items"][0]["non_scalar_base"].reverse()
    result = decode_transport_rest_evidence(15, wire)
    assert len(result.items[0]["non_scalar_base"]) == 23


def test_duplicate_base_field_is_rejected() -> None:
    wire = _wire()
    rows = wire["items"][0]["non_scalar_base"]
    rows[-1] = deepcopy(rows[0])
    with pytest.raises(ValueError, match="base fieldset"):
        decode_transport_rest_evidence(15, wire)


@pytest.mark.parametrize(
    "bad",
    ["x" * 4_194_305, float("nan"), 2**64, object()],
    ids=["over_bytes", "nan", "over_integer", "foreign_primitive"],
)
def test_response_budget_precedes_schema_work(bad: object) -> None:
    with pytest.raises(ValueError, match="rest evidence"):
        decode_transport_rest_evidence(15, {"bad": bad})


def _session(
    mode: str = "repeatable read",
    readonly: str = "on",
    *,
    statement_ms: object = 2000,
    lock_ms: object = 250,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    response = MagicMock()
    response.mappings.return_value.one.return_value = {
        "isolation": mode,
        "read_only": readonly,
        "statement_ms": statement_ms,
        "lock_ms": lock_ms,
    }
    value = MagicMock()
    value.scalar_one.return_value = _rejection()
    session.execute.side_effect = [response, value]
    return session


@pytest.mark.asyncio
async def test_read_uses_only_caller_owned_readonly_rr_and_preserves_transaction() -> None:
    session = _session()
    result = await read_transport_rest_evidence(session, 15)
    assert not result.evidence_complete
    assert session.execute.await_count == 2
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    assert (
        str(session.execute.call_args_list[1].args[0])
        == "SELECT feature.read_transport_rest_snapshot_evidence(:dataset)"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "readonly"), [("read committed", "on"), ("repeatable read", "off")]
)
async def test_wrong_snapshot_mode_never_calls_sd(mode: str, readonly: str) -> None:
    session = _session(mode, readonly)
    with pytest.raises(ValueError, match="read-only repeatable read"):
        await read_transport_rest_evidence(session, 15)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_database_error_is_propagated_with_its_original_identity() -> None:
    session = _session()
    mode = session.execute.side_effect
    first = next(mode)
    error = RuntimeError("fixture database error")
    session.execute.side_effect = [first, error]
    with pytest.raises(RuntimeError, match="fixture database error") as caught:
        await read_transport_rest_evidence(session, 15)
    assert caught.value is error
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statement_ms", "lock_ms"),
    [
        (0, 250),
        (3001, 250),
        (-1, 250),
        (True, 250),
        (None, 250),
        ("2000", 250),
        (2000, 0),
        (2000, 1001),
    ],
)
async def test_unbounded_or_invalid_server_caps_never_call_sd(statement_ms, lock_ms):
    session = _session(statement_ms=statement_ms, lock_ms=lock_ms)
    with pytest.raises(ValueError, match="finite caller SQL timeout"):
        await read_transport_rest_evidence(session, 15)
    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("statement_ms", "lock_ms"), [(1, 1), (3000, 1000)])
async def test_exact_server_cap_boundaries_are_preserved(statement_ms, lock_ms):
    session = _session(statement_ms=statement_ms, lock_ms=lock_ms)
    result = await read_transport_rest_evidence(session, 15)
    assert not result.evidence_complete
    assert session.execute.await_count == 2
    assert all("set_config" not in str(call.args[0]) for call in session.execute.call_args_list)


@pytest.mark.parametrize("bad", ["field", "shape", "history", "validation", "normalizer", "base"])
def test_phones_have_independent_exact_field_provenance_and_shape(bad: str) -> None:
    value = _wire()
    item = value["items"][0]
    if bad == "field":
        item["phones_candidate"]["field_path"] = "core.name"
    elif bad == "shape":
        item["phones_candidate"]["value_json"] = [1]
    elif bad == "history":
        item["phones_candidate"]["value_source_record_key"] = "sr_" + "f" * 20
    elif bad == "validation":
        item["phones_candidate"]["validated_source_hash"] = "f" * 32
    elif bad == "normalizer":
        item["phones_candidate"]["normalizer_revision"] = "transport-airport-name-v1"
    else:
        item["phones_base"]["source_raw_payload_hash"] = "f" * 32
    with pytest.raises(ValueError, match="rest evidence"):
        decode_transport_rest_evidence(15, value)


def test_mixed_scalar_whole_rejection_is_known_but_never_collector_authority() -> None:
    value = _rejection()
    value["reason"] = "mixed_scalar_lineage"
    result = decode_transport_rest_evidence(15, value)
    assert result.reason is RestEvidenceReason.MIXED_SCALAR_LINEAGE
    assert result.collector_ready is False
    assert result.items == ()
