"""최종 정본 공항 DTO를 보존하는 pure codec. DB/파일/worker 수용은 아니다."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, model_serializer

from kortravelmap.dto import Address
from kortravelmap.dto._time import KST
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import provider_snapshot_artifact as codec
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from kortravelmap.providers.kor_travel_transport_native import (
    AIRPORT_NAME_NORMALIZER_REVISION,
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)

_PINS = codec.SnapshotArtifactPins(
    code_revision="a" * 40,
    sdk_inventory_sha256="b" * 64,
    provider="kor-travel-transport",
    dataset_key="transport_airports",
    source_entity_type="airport",
    normalizer_revision=AIRPORT_NAME_NORMALIZER_REVISION,
    geo_domain="transport-airport-geo-v1",
    clock_domain="aware-clock-preserved-v1",
)
_AT = datetime(2026, 10, 25, 5, 0, 1, 123456, tzinfo=UTC)
_VERSION, _DATA = "dv1-" + "1" * 32, "dd1-" + "2" * 32


async def _input(count=1, *, resolved=False):
    values = []
    for n in range(count):
        item = TransportAirport(
            f"P{n:02}",
            "공항",
            "Airport",
            "ZZZZ",
            "서울",
            TransportCoordinate(lat=37.5, lon=127.0) if resolved else None,
            {},
        )
        evidence = (
            TransportGeoEvidence(
                "resolved", _VERSION, _DATA, Address(bjd_code="1156011000"), "0" * 64
            )
            if resolved
            else TransportGeoEvidence("not_requested")
        )
        values.append(await transport_item_to_native_bundle(item, fetched_at=_AT, geo=evidence))
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
    return tuple(values), geo


def _state(value):
    if isinstance(value, BaseModel):
        return (type(value), value.model_fields_set.copy(), {k: _state(v) for k, v in value})
    if isinstance(value, datetime):
        return type(value), value.isoformat(), value.tzinfo, value.fold
    if isinstance(value, Decimal):
        return type(value), value.as_tuple()
    if isinstance(value, dict):
        return {k: _state(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return type(value), [_state(v) for v in value]
    return type(value), value


@pytest.mark.parametrize("resolved", [False, True])
async def test_actual_converter_fifteen_lossless_fieldsets_clocks_and_digest(resolved):
    bundles, geo = await _input(15, resolved=resolved)
    before = _state(bundles)
    encoded = codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    decoded = codec.decode_provider_snapshot_artifact(encoded, expected_pins=_PINS)
    assert _state(decoded.bundles) == before
    assert _state(bundles) == before
    assert len(encoded) <= 1_048_576
    assert (
        codec.encode_provider_snapshot_artifact(decoded.bundles, decoded.geo, pins=_PINS) == encoded
    )
    assert codec._snapshot(bundles, geo, _PINS) == decoded.native_input_digest
    for original, restored in zip(bundles, decoded.bundles, strict=True):
        assert original is not restored
        assert original.source_record.raw_data is not restored.source_record.raw_data
        assert original.source_record.source_record_key == restored.source_record.source_record_key
        assert original.source_record.raw_payload_hash == restored.source_record.raw_payload_hash
        assert original.feature.feature_id == restored.feature.feature_id
        assert original.provider_field_presence == restored.provider_field_presence
    if geo:
        assert decoded.geo == geo
        assert decoded.geo.observed_data_tokens is not geo.observed_data_tokens
        geo.observed_data_tokens.clear()
        assert decoded.geo.observed_data_tokens == {_DATA}


@pytest.mark.parametrize("observed", [None, set(), frozenset(), {_DATA}, frozenset({_DATA})])
async def test_geo_none_empty_and_collection_type_preserved(observed):
    bundles, _ = await _input()
    geo = GeoLoadContext(GeoApplied(reverse=False, geocode=False), None, observed)
    decoded = codec.decode_provider_snapshot_artifact(
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS), expected_pins=_PINS
    )
    assert type(decoded.geo.observed_data_tokens) is type(observed)
    assert decoded.geo.observed_data_tokens == observed


@pytest.mark.parametrize("tz", [UTC, KST, timezone(timedelta(hours=9), "KST-fixed")])
async def test_default_and_explicit_clocks_and_decimal_representation(tz):
    bundles, _ = await _input(resolved=True)
    original = bundles[0]
    original.feature.updated_at = _AT.astimezone(tz).replace(fold=1)
    original.feature.coord = original.feature.coord.model_copy(update={"lon": Decimal("127.0000")})
    raw = codec.encode_provider_snapshot_artifact(bundles, None, pins=_PINS)
    restored = codec.decode_provider_snapshot_artifact(raw, expected_pins=_PINS).bundles[0]
    assert _state(restored) == _state(original)
    assert "created_at" not in restored.feature.model_fields_set
    assert "imported_at" not in restored.source_record.model_fields_set


@pytest.mark.parametrize("field", list(_PINS.__dataclass_fields__))
async def test_all_expected_pins_are_exact(field):
    bundles, geo = await _input()
    raw = codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.decode_provider_snapshot_artifact(raw, expected_pins=replace(_PINS, **{field: "bad"}))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'"\xff"',
        b"[" * 65 + b"0" + b"]" * 65,
        b"[0," + b"0," * 8192 + b"0]",
        b" " * 1_048_577,
        b"{}",
    ],
)
def test_preparse_invalid_bytes_duplicate_nan_depth_nodes_and_size(raw):
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.decode_provider_snapshot_artifact(raw, expected_pins=_PINS)


@pytest.mark.parametrize(
    "mutation", ["extra", "domain", "version", "digest", "whitespace", "duplicate"]
)
async def test_envelope_tamper_rejected(mutation):
    bundles, geo = await _input()
    raw = codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    data = json.loads(raw)
    if mutation == "extra":
        data["extra"] = None
    elif mutation == "domain":
        data["domain"] = "other"
    elif mutation == "version":
        data["version"] = True
    elif mutation == "digest":
        data["native_input_digest"] = "0" * 64
    if mutation == "whitespace":
        raw = json.dumps(data).encode()
    elif mutation == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    else:
        raw = codec._json_bytes(data)
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.decode_provider_snapshot_artifact(raw, expected_pins=_PINS)


async def test_budget_before_native_digest_and_foreign_serializer(monkeypatch):
    bundles, geo = await _input()
    calls = []
    monkeypatch.setattr(codec, "_artifact_digest", lambda _: calls.append(True))
    bundles[0].source_record.raw_data["name_korean"] = "x" * 1_048_577
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []

    class Foreign(BaseModel):
        @model_serializer
        def serialize(self):
            calls.append(True)
            return "bad"

    bundles, geo = await _input()
    bundles[0].feature.detail.facility_info["foreign"] = Foreign()
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


async def test_count_empty_unknown_shape_and_raw_lineage_rejected():
    bundles, geo = await _input()
    for invalid in ((), bundles * 2731):
        with pytest.raises(codec.UnsupportedSnapshotArtifact):
            codec.encode_provider_snapshot_artifact(invalid, geo, pins=_PINS)
    bundles[0].source_record.raw_payload_hash = "0" * 32
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)


async def test_no_foreign_deepcopy_or_custom_timezone_is_invoked():
    from datetime import tzinfo

    calls = []

    class ForeignPin:
        def __deepcopy__(self, memo):
            calls.append("copy")
            raise AssertionError("must not invoke")

    bundles, geo = await _input()
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(
            bundles, geo, pins=replace(_PINS, geo_domain=ForeignPin())
        )
    assert calls == []

    class ForeignTimezone(tzinfo):
        def utcoffset(self, dt):
            calls.append("offset")
            raise AssertionError("must not invoke")

    bundles[0].feature.updated_at = _AT.replace(tzinfo=ForeignTimezone())
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


@pytest.mark.parametrize("kind", ["extra", "missing", "fieldset", "nested_nan", "url", "naive"])
async def test_constructed_or_mutated_dto_is_not_silently_normalized(kind):
    bundles, geo = await _input()
    bundle = bundles[0]
    if kind == "extra":
        bundle.feature.__dict__["unknown"] = "extra"
    elif kind == "missing":
        del bundle.source_record.__dict__["source_record_key"]
    elif kind == "fieldset":
        bundle.feature.model_fields_set.add("unknown")
    elif kind == "nested_nan":
        bundle.feature.detail.payload["n"] = float("nan")
    elif kind == "url":
        from pydantic import AnyUrl

        bundle.feature.urls.homepage = AnyUrl("https://example.invalid/")
    else:
        bundle.feature.updated_at = _AT.replace(tzinfo=None)
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)


@pytest.mark.parametrize("type_name", ["decimal", "model", "dict", "enum", "datetime", "tuple"])
async def test_unknown_or_malformed_tag_rejected(type_name):
    bundles, geo = await _input()
    data = json.loads(codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS))
    data["bundles"] = [type_name, "not-supported"]
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.decode_provider_snapshot_artifact(codec._json_bytes(data), expected_pins=_PINS)


async def test_full_model_validation_does_not_hide_typed_any_coercion():
    bundles, geo = await _input()
    # PlaceDetail payload는 Any다. 정수/float/bool/null/Decimal/tuple 차이를 모두 보존한다.
    bundles[0].feature.detail.payload = {
        "int": 1,
        "float": 1.0,
        "negative_zero": -0.0,
        "bool": True,
        "null": None,
        "decimal": Decimal("1.2300"),
        "tuple": (1, "1"),
    }
    raw = codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    decoded = codec.decode_provider_snapshot_artifact(raw, expected_pins=_PINS)
    assert _state(decoded.bundles) == _state(bundles)
    assert codec.encode_provider_snapshot_artifact(decoded.bundles, decoded.geo, pins=_PINS) == raw


async def test_whole_geo_plus_dto_source_budget_before_any_encoding(monkeypatch):
    bundles, _ = await _input()
    bundles[0].feature.detail.payload["x"] = "x" * 600_000
    geo = GeoLoadContext(
        GeoApplied(reverse=False, geocode=False),
        DatasetRef(version_token=_VERSION, reference_months={"x": "y" * 600_000}),
    )
    calls = []
    monkeypatch.setattr(codec, "_pack", lambda _: calls.append(True))
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


def test_stream_encoder_includes_envelope_overhead_in_byte_cap():
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec._json_bytes({"envelope": "x" * 1_048_570})


@pytest.mark.parametrize("kind", ["mapping", "dict", "str", "int", "list", "fieldset"])
async def test_exact_type_preflight_never_calls_foreign_hooks(kind, monkeypatch):
    from collections.abc import Mapping

    calls = []

    def foreign(*args, **kwargs):
        calls.append("hook")
        raise RuntimeError("must not invoke")

    class ForeignMapping(Mapping):
        __getitem__ = foreign
        __iter__ = foreign
        __len__ = foreign
        items = foreign

    class ForeignDict(dict):
        items = foreign
        __iter__ = foreign

    class ForeignStr(str):
        encode = foreign
        __str__ = foreign

    class ForeignInt(int):
        __repr__ = foreign
        bit_length = foreign

    class ForeignList(list):
        __iter__ = foreign

    class ForeignSet(set):
        __iter__ = foreign

    variants = {
        "mapping": ForeignMapping(),
        "dict": ForeignDict(),
        "str": ForeignStr("value"),
        "int": ForeignInt(1),
        "list": ForeignList(),
    }
    bundles, geo = await _input()
    if kind == "fieldset":
        object.__setattr__(bundles[0].feature, "__pydantic_fields_set__", ForeignSet())
    else:
        bundles[0].feature.detail.payload["unsupported"] = variants[kind]
    monkeypatch.setattr(codec, "within_place_projection_budget", foreign)
    monkeypatch.setattr(codec, "_pack", foreign)
    monkeypatch.setattr(codec, "_artifact_digest", foreign)
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []


@pytest.mark.parametrize("shape", ["dict_cycle", "list_cycle", "nodes", "escaped_bytes"])
async def test_preflight_is_bounded_before_common_budget_pack_or_hash(shape, monkeypatch):
    bundles, geo = await _input()
    if shape == "dict_cycle":
        data = {}
        data["self"] = data
    elif shape == "list_cycle":
        data = []
        data.append(data)
    elif shape == "nodes":
        data = [None] * 8193
    else:
        data = "\x01" * 200_000
    bundles[0].feature.detail.payload["bounded"] = data
    calls = []
    monkeypatch.setattr(codec, "within_place_projection_budget", lambda _: calls.append("budget"))
    monkeypatch.setattr(codec, "_pack", lambda _: calls.append("pack"))
    monkeypatch.setattr(codec, "_artifact_digest", lambda _: calls.append("hash"))
    with pytest.raises(codec.UnsupportedSnapshotArtifact):
        codec.encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    assert calls == []
