"""실 public Rest converter + synthetic wire의 순수 준비 계약. 실제 SD/PG 증거가 아니다."""

import asyncio
import json
import struct
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.feature_repo import _make_source_entity_key, _provider_field_patch_payload
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.transport_rest_evidence_reader import (
    RestEvidenceEnvelope,
    decode_transport_rest_evidence,
)
from kortravelmap.providers import kor_travel_rest_evidence as preparation
from kortravelmap.providers.kor_travel_transport import TransportRestArea
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from kortravelmap.providers.krex import rest_area_natural_key
from tests.unit.test_transport_rest_evidence_reader import _rejection, _wire

_AT = datetime(2026, 10, 25, tzinfo=UTC)
_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")
_VERSION, _DATA = "dv1-" + "a" * 32, "dd1-" + "b" * 32
_PINS = SnapshotArtifactPins(
    code_revision="a" * 40,
    sdk_inventory_sha256="b" * 64,
    provider="kor-travel-transport",
    dataset_key="transport_rest_areas",
    source_entity_type="rest_area",
    normalizer_revision="transport-rest-area-name-phones-v1",
    geo_domain="transport-rest-area-geo-v1",
    clock_domain="aware-clock-preserved-v1",
)


async def _input(*, coordinate=False, phone="031-123-4567", name="TEST"):
    item = TransportRestArea(
        "pending",
        name,
        "route",
        "direction",
        127.0 if coordinate else None,
        37.5 if coordinate else None,
        phone,
        None,
        None,
        None,
        {},
    )
    item = replace(item, natural_key=rest_area_natural_key(item))
    geo = (
        TransportGeoEvidence("resolved", _VERSION, _DATA, _ADDRESS, "0" * 64)
        if coordinate
        else TransportGeoEvidence("not_requested")
    )
    return await transport_item_to_native_bundle(item, fetched_at=_AT, geo=geo)


async def _fixture(*, coordinate=False, phone="031-123-4567"):
    old = await _input(coordinate=coordinate, phone=phone)
    current = old.model_copy(deep=True)
    current.source_record.fetched_at = _AT + timedelta(hours=1)
    wire = _wire()
    row = wire["items"][0]
    record = old.source_record
    entity = _make_source_entity_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
    )
    substitutions = {
        row["source_entity"]["source_entity_key"]: entity,
        row["source_entity"]["source_entity_id"]: record.source_entity_id,
        row["current_record"]["source_record_key"]: record.source_record_key,
        row["current_record"]["raw_payload_hash"]: record.raw_payload_hash,
    }

    def adjust(value):
        if type(value) is dict:
            return {key: adjust(child) for key, child in value.items()}
        if type(value) is list:
            return [adjust(child) for child in value]
        return substitutions.get(value, value) if type(value) is str else value

    wire = adjust(wire)
    row = wire["items"][0]
    for name in ("base_record", "name_value_record", "phones_value_record", "current_record"):
        row[name].update(
            raw_data=record.raw_data, fetched_at=_AT.isoformat(), imported_at=_AT.isoformat()
        )
    values = json.loads(
        _provider_field_patch_payload(
            old.feature, feature_uuid=row["feature"]["feature_id"], parent_feature_id=None
        )[0]
    )
    for name, field in (
        ("name_base", "core.name"),
        ("name_candidate", "core.name"),
        ("phones_base", "place.phones"),
        ("phones_candidate", "place.phones"),
    ):
        row[name]["value_json"] = values[field]
    ewkb = struct.pack("<BIIdd", 1, 0x20000001, 4326, 127.0, 37.5).hex() if coordinate else None
    for base in row["non_scalar_base"]:
        path = base["field_path"]
        if path == "core.coord":
            base.update(
                value_json=None,
                value_json_sql_null=coordinate,
                value_geometry_sql_null=not coordinate,
                geometry_ewkb=ewkb,
            )
        else:
            base["value_json"] = values[path]
    row["feature"].update(
        coord_sql_null=not coordinate,
        geometry_ewkb=ewkb,
        coord_precision_digits=old.feature.coord_precision_digits,
        address=old.feature.address.model_dump(mode="json"),
        **{
            field: values["core." + field]
            for field in ("legal_dong_code", "admin_dong_code", "sido_code", "sigungu_code")
        },
    )
    if coordinate:
        row["geocode_stamp"] = {
            "feature_id": row["feature"]["feature_id"],
            "geo_version_token": _VERSION,
            "geo_data_token": _DATA,
            "reverse_outcome": "called",
            "stamped_at": _AT.isoformat(),
        }
    context = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(version_token=_VERSION, data_token=_DATA),
            frozenset({_DATA}),
        )
        if coordinate
        else None
    )
    return wire, current, context


def _reader(monkeypatch, wire):
    value = AsyncMock(return_value=decode_transport_rest_evidence(15, wire))
    monkeypatch.setattr(preparation, "read_transport_rest_evidence", value)
    return value


@pytest.mark.parametrize("coordinate", [False, True])
@pytest.mark.parametrize("phone", [None, "031-123-4567"])
async def test_canonical_rest_two_scalar_non_scalar_geo_are_diagnostic_only(
    monkeypatch, coordinate, phone
):
    wire, current, geo = await _fixture(coordinate=coordinate, phone=phone)
    reader = _reader(monkeypatch, wire)
    result = await preparation.prepare_transport_rest_area_reobservation(
        object(), [current], dataset_id=15, pins=_PINS, geo=geo
    )
    assert result.eligible
    assert result.input_eof
    assert result.evidence.db_scope_eof
    assert result.reason == "unchanged_reobservation"
    assert not result.collector_ready
    assert result.requires_database_reverification
    reader.assert_awaited_once()


@pytest.mark.parametrize(
    "mutation", ["phones", "name", "base", "changed_raw", "scope", "geo_missing", "geo_changed"]
)
async def test_whole_mismatch_and_non_scalar_provenance_rejection(monkeypatch, mutation):
    coordinate = mutation.startswith("geo_")
    wire, current, geo = await _fixture(coordinate=coordinate)
    row = wire["items"][0]
    if mutation == "phones":
        row["phones_base"]["value_json"] = ["other"]
        row["phones_candidate"]["value_json"] = ["other"]
    elif mutation == "name":
        row["name_base"]["value_json"] = "other"
        row["name_candidate"]["value_json"] = "other"
    elif mutation == "base":
        next(x for x in row["non_scalar_base"] if x["field_path"] == "place.facility_info")[
            "value_json"
        ] = {"highway_name": "different", "direction": "direction"}
    elif mutation == "changed_raw":
        current = await _input(phone="031-123-0000")
    elif mutation == "scope":
        current = await _input(name="OTHER")
    elif mutation == "geo_missing":
        geo = None
    else:
        geo = replace(
            geo,
            current_dataset=geo.current_dataset.model_copy(
                update={"data_token": "dd1-" + "c" * 32}
            ),
        )
    _reader(monkeypatch, wire)
    result = await preparation.prepare_transport_rest_area_reobservation(
        object(), [current], dataset_id=15, pins=_PINS, geo=geo
    )
    assert not result.eligible
    assert not result.collector_ready
    assert (
        result.reason
        == {
            "phones": "stored_scalar_meaning_mismatch",
            "name": "stored_scalar_meaning_mismatch",
            "base": "stored_base_meaning_mismatch",
            "changed_raw": "changed_raw_requires_ex",
            "scope": "whole_scope_mismatch",
            "geo_missing": "stored_projection_unsupported",
            "geo_changed": "stored_projection_unsupported",
        }[mutation]
    )


async def test_max_plus_one_stops_before_codec_and_first_sql(monkeypatch):
    current = await _input()
    reader = AsyncMock()
    monkeypatch.setattr(preparation, "read_transport_rest_evidence", reader)
    calls = []
    monkeypatch.setattr(
        preparation, "encode_rest_area_snapshot_artifact", lambda *a, **k: calls.append("codec")
    )
    consumed = 0

    def inputs():
        nonlocal consumed
        for _ in range(1000):
            consumed += 1
            yield current

    with pytest.raises(ValueError, match="exceeds256"):
        await preparation.prepare_transport_rest_area_reobservation(
            object(), inputs(), dataset_id=15, pins=_PINS
        )
    assert consumed == 257
    assert calls == []
    reader.assert_not_called()


@pytest.mark.parametrize(
    "failure", [RuntimeError("original SQL error"), asyncio.CancelledError(), TimeoutError()]
)
async def test_exact_sql_error_cancel_timeout_propagate(monkeypatch, failure):
    current = await _input()
    reader = AsyncMock(side_effect=failure)
    monkeypatch.setattr(preparation, "read_transport_rest_evidence", reader)
    with pytest.raises(type(failure)) as caught:
        await preparation.prepare_transport_rest_area_reobservation(
            object(), [current], dataset_id=15, pins=_PINS
        )
    assert caught.value is failure


async def test_known_rejection_keeps_whole_empty_evidence(monkeypatch):
    current = await _input()
    _reader(monkeypatch, _rejection())
    result = await preparation.prepare_transport_rest_area_reobservation(
        object(), [current], dataset_id=15, pins=_PINS
    )
    assert not result.eligible
    assert result.reason == "budget_exceeded"
    assert result.evidence.items == ()


async def test_exact_pin_rejection_before_first_sql(monkeypatch):
    current = await _input()
    reader = AsyncMock()
    monkeypatch.setattr(preparation, "read_transport_rest_evidence", reader)
    with pytest.raises(ValueError, match="unsupported rest-area snapshot artifact"):
        await preparation.prepare_transport_rest_area_reobservation(
            object(), [current], dataset_id=15, pins=replace(_PINS, source_entity_type="airport")
        )
    reader.assert_not_called()


async def test_direct_assessment_revalidates_envelope_before_foreign_mapping_hook():
    current = await _input()
    calls = []

    class ForeignMapping(dict):
        def keys(self):
            calls.append("keys")
            raise RuntimeError("foreign hook")

        def __iter__(self):
            calls.append("iter")
            raise RuntimeError("foreign hook")

    evidence = RestEvidenceEnvelope(15, True, True, None, 0, (ForeignMapping(),))
    with pytest.raises(ValueError, match="invalid rest evidence primitive"):
        await preparation.assess_transport_rest_area_reobservation_evidence(
            [current], evidence, pins=_PINS
        )
    assert calls == []


@pytest.mark.parametrize(
    ("row_name", "field", "value"),
    [
        *(
            (row, "value_json_sql_null", True)
            for row in ("name_base", "phones_base", "name_candidate", "phones_candidate")
        ),
        *(
            (row, "geometry_ewkb", "corrupt")
            for row in ("name_base", "phones_base", "name_candidate", "phones_candidate")
        ),
        ("name_base", "value_geometry_sql_null", False),
        ("non_scalar_base", "geometry_ewkb", "corrupt"),
        ("non_scalar_base", "value_json_sql_null", True),
        ("feature", "geometry_ewkb", "corrupt"),
        ("feature", "coord_sql_null", False),
    ],
)
async def test_direct_assessment_rejects_inconsistent_sql_null_representation(
    row_name, field, value
):
    wire, current, context = await _fixture()
    item = wire["items"][0]
    target = (
        next(row for row in item["non_scalar_base"] if row["value_json"] is not None)
        if row_name == "non_scalar_base"
        else item[row_name]
    )
    target[field] = value
    # Deliberately bypass the normal decoder entry: the public assessment must revalidate.
    evidence = RestEvidenceEnvelope(15, True, True, None, 0, tuple(wire["items"]))
    with pytest.raises(ValueError, match="invalid rest evidence"):
        await preparation.assess_transport_rest_area_reobservation_evidence(
            [current], evidence, pins=_PINS, geo=context
        )


@pytest.mark.parametrize("coordinate", [False, True])
async def test_direct_assessment_keeps_legal_json_null_and_geometry_representation(coordinate):
    wire, current, context = await _fixture(coordinate=coordinate)
    row = next(
        row
        for row in wire["items"][0]["non_scalar_base"]
        if row["field_path"] != "core.coord" and row["value_json"] is None
    )
    assert row["value_json_sql_null"] is False
    assert row["value_geometry_sql_null"] is True
    assert row["geometry_ewkb"] is None
    evidence = RestEvidenceEnvelope(15, True, True, None, 0, tuple(wire["items"]))
    result = await preparation.assess_transport_rest_area_reobservation_evidence(
        [current], evidence, pins=_PINS, geo=context
    )
    assert result.eligible
    assert result.reason == "unchanged_reobservation"
    assert result.collector_ready is False
