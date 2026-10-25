"""Rest 전용 후보 codec의 lossless/선검사 경계. DB·운영215 수용은 아니다."""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, model_serializer

from kortravelmap.dto import Address
from kortravelmap.dto._time import KST
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import rest_area_snapshot_artifact as codec
from kortravelmap.infra._snapshot_artifact_codec import CodecProfile, guard_wire, preflight
from kortravelmap.infra.provider_snapshot_artifact import (
    SnapshotArtifactPins,
    UnsupportedSnapshotArtifact,
    decode_provider_snapshot_artifact,
)
from kortravelmap.providers.kor_travel_transport import TransportRestArea
from kortravelmap.providers.kor_travel_transport_native import (
    REST_AREA_SCALAR_NORMALIZER_REVISION,
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from kortravelmap.providers.krex import rest_area_natural_key

_PINS = SnapshotArtifactPins(
    code_revision="a" * 40,
    sdk_inventory_sha256="b" * 64,
    provider="kor-travel-transport",
    dataset_key="transport_rest_areas",
    source_entity_type="rest_area",
    normalizer_revision=REST_AREA_SCALAR_NORMALIZER_REVISION,
    geo_domain="transport-rest-area-geo-v1",
    clock_domain="aware-clock-preserved-v1",
)
_AT = datetime(2026, 10, 25, 5, 0, 1, 123456, tzinfo=UTC)
_VERSION, _DATA = "dv1-" + "1" * 32, "dd1-" + "2" * 32


async def _input(count=1, *, resolved=False, phone="031-123-4567"):
    result = []
    for n in range(count):
        item = TransportRestArea(
            "pending",
            f"휴게소{n}",
            "경부선",
            "상행",
            127.0 if resolved else None,
            37.5 if resolved else None,
            phone,
            None,
            None,
            None,
            {},
        )
        item = replace(item, natural_key=rest_area_natural_key(item))
        evidence = (
            TransportGeoEvidence(
                "resolved", _VERSION, _DATA, Address(bjd_code="1156011000"), "0" * 64
            )
            if resolved
            else TransportGeoEvidence("not_requested")
        )
        result.append(await transport_item_to_native_bundle(item, fetched_at=_AT, geo=evidence))
    geo = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(
                version_token=_VERSION,
                data_token=_DATA,
                activated_at=_AT,
                reference_months={"bjd": "202610"},
            ),
            {_DATA},
        )
        if resolved
        else None
    )
    return tuple(result), geo


def _state(value):
    if type(value) is GeoLoadContext:
        return (
            type(value),
            _state(value.geo_applied),
            _state(value.current_dataset),
            _state(value.observed_data_tokens),
        )
    if isinstance(value, BaseModel):
        return type(value), value.model_fields_set.copy(), {k: _state(v) for k, v in value}
    if type(value) is datetime:
        return type(value), value.isoformat(), value.tzinfo, value.fold
    if type(value) is Decimal:
        return type(value), value.as_tuple()
    if type(value) is dict:
        return {k: _state(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return type(value), [_state(v) for v in value]
    if type(value) in (set, frozenset):
        return type(value), sorted(value)
    return type(value), value


@pytest.mark.parametrize("resolved", [False, True])
async def test_canonical_215_whole_lossless_fieldsets_identity_clock_geo(resolved):
    bundles, geo = await _input(215, resolved=resolved)
    before = _state(bundles)
    raw = codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    restored = codec.decode_rest_area_snapshot_artifact(raw, expected_pins=_PINS)
    assert len(raw) <= 1_048_576
    assert len(restored.bundles) == 215
    assert _state(restored.bundles) == before == _state(bundles)
    assert _state(restored.geo) == _state(geo)
    assert (
        codec.encode_rest_area_snapshot_artifact(restored.bundles, restored.geo, pins=_PINS) == raw
    )
    assert codec._snapshot(bundles, geo, _PINS) == restored.native_input_digest
    for original, decoded in zip(bundles, restored.bundles, strict=True):
        assert decoded is not original
        assert decoded.source_record.raw_data is not original.source_record.raw_data
        assert decoded.source_record.source_record_key == original.source_record.source_record_key
        assert decoded.source_record.raw_payload_hash == original.source_record.raw_payload_hash
        assert decoded.feature.feature_id == original.feature.feature_id
        assert decoded.provider_field_presence.supplied_fields == frozenset(
            {"core.name", "place.phones"}
        )
        assert decoded.source_record.fetched_at == _AT
        assert "imported_at" not in decoded.source_record.model_fields_set
    if geo is not None:
        geo.observed_data_tokens.clear()
        assert restored.geo.observed_data_tokens == {_DATA}


@pytest.mark.parametrize("phone", [None, "", "   "])
async def test_explicit_empty_phone_presence_preserved(phone):
    bundles, geo = await _input(phone=phone)
    restored = codec.decode_rest_area_snapshot_artifact(
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS), expected_pins=_PINS
    ).bundles[0]
    assert restored.feature.detail.phones == []
    assert "place.phones" in restored.provider_field_presence.supplied_fields
    assert restored.source_record.raw_data["phone_number"] == phone


@pytest.mark.parametrize("observed", [None, set(), frozenset(), {_DATA}, frozenset({_DATA})])
async def test_geo_none_empty_and_set_types_preserved(observed):
    bundles, _ = await _input()
    geo = GeoLoadContext(GeoApplied(reverse=False, geocode=False), None, observed)
    restored = codec.decode_rest_area_snapshot_artifact(
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS), expected_pins=_PINS
    )
    assert type(restored.geo.observed_data_tokens) is type(observed)
    assert restored.geo.observed_data_tokens == observed


@pytest.mark.parametrize("zone", [UTC, KST, timezone(timedelta(hours=9), "KST-fixed")])
async def test_nested_any_exact_types_defaults_and_clocks(zone):
    bundles, geo = await _input()
    bundle = bundles[0]
    bundle.feature.detail.facility_info["typed"] = {
        "decimal": Decimal("1.2300"),
        "clock": _AT.astimezone(zone).replace(fold=1),
        "tuple": (None, False, 0),
        "set": {"a", "b"},
        "frozen": frozenset(),
    }
    before = _state(bundle)
    restored = codec.decode_rest_area_snapshot_artifact(
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS), expected_pins=_PINS
    ).bundles[0]
    assert _state(restored) == before
    assert "created_at" not in restored.feature.model_fields_set


@pytest.mark.parametrize("field", list(_PINS.__dataclass_fields__))
async def test_exact_pin_scope_and_code_inventory(field):
    bundles, geo = await _input()
    raw = codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.decode_rest_area_snapshot_artifact(
            raw, expected_pins=replace(_PINS, **{field: "bad"})
        )


@pytest.mark.parametrize("mutation", ["extra", "domain", "version", "digest", "whitespace"])
async def test_envelope_tamper_is_whole_rejection(mutation):
    bundles, geo = await _input()
    raw = codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    data = json.loads(raw)
    if mutation == "extra":
        data["extra"] = None
    elif mutation == "domain":
        data["domain"] = "airport-prepared-typed-v1"
    elif mutation == "version":
        data["version"] = True
    elif mutation == "digest":
        data["native_input_digest"] = "0" * 64
    else:
        raw += b" "
    if mutation != "whitespace":
        raw = codec._json_bytes(data)
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.decode_rest_area_snapshot_artifact(raw, expected_pins=_PINS)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":0,"a":1}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'"\xff"',
        b"{}",
        b"[" * 65 + b"0" + b"]" * 65,
        b" " * 1_048_577,
        b"[" + b",".join([b"0"] * 131_072) + b"]",
    ],
)
def test_wire_preparse_bounds_duplicate_utf8_nan_depth_nodes_bytes(raw):
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.decode_rest_area_snapshot_artifact(raw, expected_pins=_PINS)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "identity",
        "link_feature",
        "link_record",
        "raw_hash",
        "raw_keys",
        "normalizer",
        "presence",
        "empty_name",
        "rest_kind",
    ],
)
async def test_invalid_identity_lineage_presence_rejects_whole_tuple(mutation):
    bundles, geo = await _input(2)
    last = bundles[-1]
    if mutation == "duplicate":
        bundles = (bundles[0], bundles[0])
    elif mutation == "identity":
        last.feature.provider_natural_key = "different"
    elif mutation == "link_feature":
        last.source_link.feature_id = bundles[0].feature.feature_id
    elif mutation == "link_record":
        last.source_link.source_record_key = bundles[0].source_record.source_record_key
    elif mutation == "raw_hash":
        last.source_record.raw_payload_hash = "0" * 32
    elif mutation == "raw_keys":
        last.source_record.raw_data["new"] = None
    elif mutation == "normalizer":
        last.provider_field_presence = last.provider_field_presence.model_copy(
            update={"normalizer_revision": "other"}
        )
    elif mutation == "presence":
        last.provider_field_presence = last.provider_field_presence.model_copy(
            update={"supplied_fields": frozenset({"core.name"})}
        )
    elif mutation == "empty_name":
        last.source_record.raw_data["name"] = " "
    else:
        last.feature.detail.place_kind = "airport"
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)


@pytest.mark.parametrize("shape", ["items", "source_bytes", "typed_nodes", "cycle"])
async def test_source_limits_before_pack_or_digest(shape, monkeypatch):
    bundles, geo = await _input()
    if shape == "items":
        bundles *= 257
    elif shape == "source_bytes":
        bundles[0].feature.detail.facility_info["x"] = "x" * 2_097_153
    elif shape == "typed_nodes":
        bundles[0].feature.detail.facility_info["x"] = [None] * 65_536
    else:
        values = []
        values.append(values)
        bundles[0].feature.detail.facility_info["x"] = values
    calls = []
    monkeypatch.setattr(codec, "_pack", lambda _: calls.append("pack"))
    monkeypatch.setattr(codec, "_artifact_digest", lambda _: calls.append("hash"))
    monkeypatch.setattr(codec, "within_place_projection_budget", lambda _: calls.append("budget"))
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


async def test_wire_whole_size_rejects_even_when_each_row_fits():
    bundles, geo = await _input(215)
    for bundle in bundles:
        bundle.feature.detail.facility_info["extra"] = "x" * 2000
    envelope = codec._envelope(bundles, geo, _PINS)
    with pytest.raises(UnsupportedSnapshotArtifact, match="airport snapshot artifact"):
        codec._json_bytes(envelope)
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)


@pytest.mark.parametrize("kind", ["mapping", "model", "str", "int", "zone_name"])
async def test_foreign_hooks_rejected_before_common_pack_hash(kind, monkeypatch):
    calls = []

    def foreign(*_args, **_kwargs):
        calls.append("hook")
        raise RuntimeError("foreign hook must not run")

    class ForeignMapping(Mapping):
        __iter__ = foreign
        __len__ = foreign
        __getitem__ = foreign
        items = foreign

    class ForeignModel(BaseModel):
        @model_serializer
        def serialize(self):
            return foreign()

    class ForeignString(str):
        __str__ = foreign
        __len__ = foreign

    class ForeignInt(int):
        bit_length = foreign

    bundles, geo = await _input()
    value = {
        "mapping": ForeignMapping(),
        "model": ForeignModel(),
        "str": ForeignString("x"),
        "int": ForeignInt(1),
        "zone_name": _AT.replace(tzinfo=timezone(timedelta(0), ForeignString("name"))),
    }[kind]
    bundles[0].feature.detail.facility_info["foreign"] = value
    monkeypatch.setattr(codec, "within_place_projection_budget", foreign)
    monkeypatch.setattr(codec, "_pack", foreign)
    monkeypatch.setattr(codec, "_artifact_digest", foreign)
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


def test_fixed_profiles_keep_airport_wire_cap_and_whitelist():
    value = b"[" + b",".join([b"0"] * 8192) + b"]"
    assert guard_wire(value, profile=CodecProfile.REST_AREA)
    with pytest.raises(ValueError, match="unsupported bounded typed snapshot"):
        guard_wire(value, profile=CodecProfile.AIRPORT)
    with pytest.raises(ValueError, match="unsupported bounded typed snapshot"):
        preflight(({},), profile="rest_area")


async def test_rest_artifact_does_not_expand_airport_public_domain():
    bundles, geo = await _input()
    raw = codec.encode_rest_area_snapshot_artifact(bundles, geo, pins=_PINS)
    with pytest.raises(UnsupportedSnapshotArtifact):
        decode_provider_snapshot_artifact(raw, expected_pins=_PINS)


@pytest.mark.parametrize(
    "raw",
    [
        b" " * 1_048_577,
        b"[" * 65 + b"0" + b"]" * 65,
        b"[" + b",".join([b"0"] * 131_072) + b"]",
    ],
)
def test_wire_bounds_reject_before_json_object_allocation(raw, monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("parse")
        raise RuntimeError("parser must not run")

    monkeypatch.setattr(codec.json, "loads", forbidden)
    with pytest.raises(codec.UnsupportedRestAreaSnapshotArtifact):
        codec.decode_rest_area_snapshot_artifact(raw, expected_pins=_PINS)
    assert calls == []
