"""정본 converter와 synthetic DB wire를 결합한 준비 경계. 실제 PG 증거는 아니다."""

import json
import struct
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.feature_repo import _provider_field_patch_payload
from kortravelmap.infra.transport_airport_evidence_reader import decode_transport_airport_evidence
from kortravelmap.providers import kor_travel_transport_evidence as preparation
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from tests.unit.test_transport_airport_evidence_reader import _rejection, _wire

_AT = datetime(2026, 10, 25, tzinfo=UTC)
_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")
_VERSION, _DATA = "dv1-" + "a" * 32, "dd1-" + "b" * 32


async def _fixture(*, coordinate=False):
    item = TransportAirport(
        "P01",
        None,
        "TEST",
        None,
        None,
        TransportCoordinate(lat=37.5, lon=127.0) if coordinate else None,
        {},
    )
    geo = (
        TransportGeoEvidence("resolved", _VERSION, _DATA, _ADDRESS, "0" * 64)
        if coordinate
        else TransportGeoEvidence("not_requested")
    )
    old = await transport_item_to_native_bundle(item, fetched_at=_AT, geo=geo)
    current = await transport_item_to_native_bundle(
        item, fetched_at=_AT + timedelta(hours=1), geo=geo
    )
    wire = _wire()
    row = wire["items"][0]
    record = old.source_record
    for name in ("base_record", "name_value_record", "current_record"):
        row[name].update(
            source_record_key=record.source_record_key,
            raw_payload_hash=record.raw_payload_hash,
            raw_data=record.raw_data,
        )
    row["source_head"]["current_source_record_key"] = record.source_record_key
    for name in ("name_base", "name_candidate"):
        target = row[name]
        for key in list(target):
            if key.endswith("source_record_key"):
                target[key] = record.source_record_key
            elif key.endswith("source_hash") or key == "source_raw_payload_hash":
                target[key] = record.raw_payload_hash
    values = json.loads(
        _provider_field_patch_payload(
            old.feature,
            feature_uuid=row["feature"]["feature_id"],
            parent_feature_id=None,
        )[0]
    )
    ewkb = struct.pack("<BIIdd", 1, 0x20000001, 4326, 127.0, 37.5).hex() if coordinate else None
    for base in row["non_name_base"]:
        path = base["field_path"]
        base.update(
            source_record_key=record.source_record_key,
            source_raw_payload_hash=record.raw_payload_hash,
        )
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
        legal_dong_code=values["core.legal_dong_code"],
        admin_dong_code=values["core.admin_dong_code"],
        sido_code=values["core.sido_code"],
        sigungu_code=values["core.sigungu_code"],
    )
    if coordinate:
        row["geocode_stamp"] = dict(
            feature_id=row["feature"]["feature_id"],
            geo_version_token=_VERSION,
            geo_data_token=_DATA,
            reverse_outcome="called",
            stamped_at=_AT.isoformat(),
        )
    return wire, current


def _mock_reader(monkeypatch, wire):
    reader = AsyncMock(return_value=decode_transport_airport_evidence(15, wire))
    monkeypatch.setattr(preparation, "read_transport_airport_evidence", reader)
    return reader


@pytest.mark.parametrize("coordinate", [False, True])
async def test_canonical_whole_input_and_geo_are_diagnostic_only(monkeypatch, coordinate):
    wire, current = await _fixture(coordinate=coordinate)
    reader = _mock_reader(monkeypatch, wire)
    context = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(version_token=_VERSION, data_token=_DATA),
            frozenset({_DATA}),
        )
        if coordinate
        else None
    )
    result = await preparation.prepare_transport_airport_reobservation(
        object(),
        [current],
        dataset_id=15,
        geo=context,
    )
    assert result.eligible
    assert result.input_eof
    assert result.evidence.db_scope_eof
    assert result.reason == "unchanged_reobservation"
    assert result.collector_ready is False
    assert result.requires_database_reverification is True
    reader.assert_awaited_once()


@pytest.mark.parametrize("mutation", ["base", "changed_raw", "scope", "geo_missing", "geo_changed"])
async def test_whole_mismatch_never_returns_partial_success(monkeypatch, mutation):
    coordinate = mutation.startswith("geo_")
    wire, current = await _fixture(coordinate=coordinate)
    if mutation == "base":
        row = next(
            r for r in wire["items"][0]["non_name_base"] if r["field_path"] == "place.phones"
        )
        row["value_json"] = ["extra"]
    if mutation == "changed_raw":
        changed = TransportAirport("P01", "이름 변경", "TEST", None, None, None, {})
        current = await transport_item_to_native_bundle(
            changed, fetched_at=_AT + timedelta(hours=1), geo=TransportGeoEvidence("not_requested")
        )
    if mutation == "scope":
        other = TransportAirport("P02", None, "OTHER", None, None, None, {})
        current = await transport_item_to_native_bundle(
            other, fetched_at=_AT + timedelta(hours=1), geo=TransportGeoEvidence("not_requested")
        )
    _mock_reader(monkeypatch, wire)
    context = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(version_token=_VERSION, data_token="dd1-" + "c" * 32),
            frozenset(),
        )
        if mutation == "geo_changed"
        else None
    )
    result = await preparation.prepare_transport_airport_reobservation(
        object(),
        [current],
        dataset_id=15,
        geo=context,
    )
    assert not result.eligible
    assert (
        result.reason
        == {
            "base": "stored_base_meaning_mismatch",
            "changed_raw": "changed_raw_requires_ex",
            "scope": "whole_scope_mismatch",
            "geo_missing": "stored_projection_unsupported",
            "geo_changed": "stored_projection_unsupported",
        }[mutation]
    )
    assert not result.collector_ready


async def test_known_db_rejection_and_sql_error_are_distinct(monkeypatch):
    _, current = await _fixture()
    reader = _mock_reader(monkeypatch, _rejection())
    result = await preparation.prepare_transport_airport_reobservation(
        object(), [current], dataset_id=15
    )
    assert not result.eligible
    assert result.reason == "budget_exceeded"
    original = RuntimeError("private test failure")
    reader.side_effect = original
    with pytest.raises(RuntimeError) as failure:
        await preparation.prepare_transport_airport_reobservation(
            object(), [current], dataset_id=15
        )
    assert failure.value is original


async def test_max_plus_one_stops_before_first_sql(monkeypatch):
    _, current = await _fixture()
    reader = AsyncMock()
    monkeypatch.setattr(preparation, "read_transport_airport_evidence", reader)
    consumed = 0

    def inputs():
        nonlocal consumed
        for _ in range(3000):
            consumed += 1
            yield current

    with pytest.raises(ValueError, match="exceeds2730"):
        await preparation.prepare_transport_airport_reobservation(object(), inputs(), dataset_id=15)
    assert consumed == 2731
    reader.assert_not_called()


async def test_old_nonname_r1_and_current_name_r2_remain_distinct(monkeypatch):
    wire, _ = await _fixture()
    changed = TransportAirport("P01", "새 이름", "TEST", None, None, None, {})
    current = await transport_item_to_native_bundle(
        changed, fetched_at=_AT + timedelta(hours=2), geo=TransportGeoEvidence("not_requested")
    )
    row = wire["items"][0]
    old_key = row["base_record"]["source_record_key"]
    record = current.source_record
    for name in ("name_value_record", "current_record"):
        row[name].update(
            source_record_key=record.source_record_key,
            raw_payload_hash=record.raw_payload_hash,
            raw_data=record.raw_data,
        )
    row["source_head"]["current_source_record_key"] = record.source_record_key
    for name in ("name_base", "name_candidate"):
        target = row[name]
        target["value_json"] = current.feature.name
        for key in list(target):
            if key.endswith("source_record_key"):
                target[key] = record.source_record_key
            elif key.endswith("source_hash") or key == "source_raw_payload_hash":
                target[key] = record.raw_payload_hash
    _mock_reader(monkeypatch, wire)
    result = await preparation.prepare_transport_airport_reobservation(
        object(), [current], dataset_id=15
    )
    assert result.eligible
    returned = result.evidence.items[0]
    assert returned["base_record"]["source_record_key"] == old_key
    assert returned["name_value_record"]["source_record_key"] == record.source_record_key
    assert old_key != record.source_record_key
    assert all(base["source_record_key"] == old_key for base in returned["non_name_base"])


@pytest.mark.parametrize("flag", ["reverse", "geocode"])
async def test_model_copy_invalid_geo_flag_stops_before_sql(monkeypatch, flag):
    _, current = await _fixture()
    reader = AsyncMock()
    monkeypatch.setattr(preparation, "read_transport_airport_evidence", reader)
    context = GeoLoadContext(GeoApplied(reverse=False, geocode=False).model_copy(update={flag: 1}))
    with pytest.raises(ValueError, match="invalid canonical airport Geo context"):
        await preparation.prepare_transport_airport_reobservation(
            object(), [current], dataset_id=15, geo=context
        )
    reader.assert_not_called()


@pytest.mark.parametrize("changed_record", ["name_r2", "current_r3"])
async def test_r2_and_r3_nonname_meaning_must_both_match_stored_r1(monkeypatch, changed_record):
    wire, _ = await _fixture()
    outputs = []
    for label, hour in (("name_r2", 2), ("current_r3", 3)):
        item = TransportAirport(
            "P01",
            "새 이름",
            "TEST",
            "NEW1" if label == changed_record else None,
            None,
            None,
            {},
        )
        outputs.append(
            await transport_item_to_native_bundle(
                item,
                fetched_at=_AT + timedelta(hours=hour),
                geo=TransportGeoEvidence("not_requested"),
            )
        )
    name_bundle, current = outputs
    row = wire["items"][0]
    for label, bundle in (("name_value_record", name_bundle), ("current_record", current)):
        record = bundle.source_record
        row[label].update(
            source_record_key=record.source_record_key,
            raw_payload_hash=record.raw_payload_hash,
            raw_data=record.raw_data,
            fetched_at=record.fetched_at.isoformat(),
            imported_at=record.imported_at.isoformat(),
        )
    name_record, current_record = name_bundle.source_record, current.source_record
    row["source_head"].update(
        current_source_record_key=current_record.source_record_key,
        observed_at=current_record.fetched_at.isoformat(),
    )
    row["source_entity"]["last_seen_at"] = current_record.fetched_at.isoformat()
    row["feature"]["row_revision"] = 3
    row["name_base"].update(
        source_record_key=name_record.source_record_key,
        source_raw_payload_hash=name_record.raw_payload_hash,
        value_json=current.feature.name,
        base_revision=2,
        observed_at=name_record.fetched_at.isoformat(),
    )
    row["name_candidate"].update(
        value_source_record_key=name_record.source_record_key,
        value_source_hash=name_record.raw_payload_hash,
        value_json=current.feature.name,
        value_observed_at=name_record.fetched_at.isoformat(),
        validated_source_record_key=current_record.source_record_key,
        validated_source_hash=current_record.raw_payload_hash,
        validated_at=current_record.fetched_at.isoformat(),
    )
    assert row["current_record"]["raw_data"] == current.source_record.raw_data
    _mock_reader(monkeypatch, wire)
    result = await preparation.prepare_transport_airport_reobservation(
        object(), [current], dataset_id=15
    )
    assert result.eligible is False
    assert result.reason == "stored_nonname_history_mismatch"
    assert result.collector_ready is False
