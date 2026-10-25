"""기존 Transport dataclass/converter를 실제 호출하는 순수 진단 경계 시험."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, model_serializer

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import Address, FeatureBundle, SourceRecord
from kortravelmap.providers.kor_travel_transport import (
    TransportAirport,
    TransportCoordinate,
    TransportRestArea,
)
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    assess_transport_scalar_refresh,
    rebuild_transport_projection,
    transport_item_to_native_bundle,
)
from kortravelmap.providers.krex import rest_area_natural_key

NOW = datetime(2026, 10, 25, tzinfo=UTC)
NONE = TransportGeoEvidence("not_requested")
GEO = TransportGeoEvidence(
    "resolved", "version1", "data1", Address(bjd_code="1111010100"), "a" * 64
)


def airport(*, coords: bool = False) -> TransportAirport:
    return TransportAirport(
        "ICN",
        "인천공항",
        "Incheon Airport",
        "RKSI",
        "인천",
        TransportCoordinate(lat=37.5, lon=127.0) if coords else None,
        {},
    )


def rest(*, phone: str | None = "031-123-4567", coords: bool = False) -> TransportRestArea:
    name, route, direction = "서울휴게소", "경부선", "부산"
    item = TransportRestArea(
        "temporary",
        name,
        route,
        direction,
        127.0 if coords else None,
        37.5 if coords else None,
        phone,
        None,
        None,
        None,
        {},
    )
    return replace(item, natural_key=rest_area_natural_key(item))


async def assess(previous: FeatureBundle, current: FeatureBundle, *, geo=NONE, revision=None):
    return await assess_transport_scalar_refresh(
        previous.source_record,
        current,
        previous_normalizer_revision=(
            previous.provider_field_presence.normalizer_revision if revision is None else revision
        ),
        previous_geo=geo,
        current_geo=geo,
    )


def rehash(record: SourceRecord, raw: dict) -> SourceRecord:
    h = make_payload_hash(raw)
    key = make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=h,
    )
    return record.model_copy(
        update={"raw_data": raw, "raw_payload_hash": h, "source_record_key": key}
    )


@pytest.mark.parametrize("kind", ["airport", "rest"])
@pytest.mark.parametrize("coords", [False, True])
async def test_actual_converter_roundtrip_and_unchanged_reobservation(kind, coords):
    item = airport(coords=coords) if kind == "airport" else rest(coords=coords)
    geo = GEO if coords else NONE
    before = await transport_item_to_native_bundle(item, fetched_at=NOW, geo=geo)
    rebuilt = await rebuild_transport_projection(before.source_record, geo=geo)
    assert rebuilt.source_record is before.source_record
    assert rebuilt.feature.model_dump(
        exclude={"created_at", "updated_at"}
    ) == before.feature.model_dump(exclude={"created_at", "updated_at"})
    current = await transport_item_to_native_bundle(
        item, fetched_at=NOW + timedelta(seconds=1), geo=geo
    )
    result = await assess(before, current, geo=geo)
    assert result.eligible
    assert result.reason == "unchanged_reobservation"
    assert result.requires_database_verification
    assert not result.collector_ready


@pytest.mark.parametrize("phone", [None, "", "   "])
async def test_rest_empty_phone_is_explicit_empty_list(phone):
    b = await transport_item_to_native_bundle(rest(phone=phone), fetched_at=NOW, geo=NONE)
    assert b.feature.detail.phones == []
    assert b.provider_field_presence.supplied_fields == {"core.name", "place.phones"}


async def test_airport_fallback_name_and_presence_use_original_converter():
    b = await transport_item_to_native_bundle(
        replace(airport(), name_korean=None), fetched_at=NOW, geo=NONE
    )
    assert b.feature.name == "Incheon Airport"
    assert b.provider_field_presence.supplied_fields == {"core.name"}


@pytest.mark.parametrize("change", ["name", "phone", "identity", "facility"])
async def test_changed_raw_always_requires_ex(change):
    item = rest() if change == "phone" else airport()
    before = await transport_item_to_native_bundle(item, fetched_at=NOW, geo=NONE)
    changed = {
        "name": lambda: replace(item, name_korean="새 공항"),
        "phone": lambda: replace(item, phone_number="031-999-8888"),
        "identity": lambda: replace(item, code="GMP"),
        "facility": lambda: replace(item, icao_code="RKSS"),
    }[change]()
    current = await transport_item_to_native_bundle(changed, fetched_at=NOW, geo=NONE)
    result = await assess(before, current)
    assert not result.eligible
    assert result.reason == "changed_raw_requires_ex"


@pytest.mark.parametrize("change", ["facility", "address", "name", "phones"])
async def test_full_typed_meaning_rejects_forged_values(change):
    before = await transport_item_to_native_bundle(rest(), fetched_at=NOW, geo=NONE)
    current = before.model_copy(deep=True)
    if change == "facility":
        current.feature.detail.facility_info["extra"] = "forged"
    elif change == "address":
        current.feature.address.road = "forged"
    elif change == "name":
        current.feature.name = "forged"
    else:
        current.feature.detail.phones = []
    result = await assess(before, current)
    assert not result.eligible
    assert result.reason == "current_bundle_not_canonical"


@pytest.mark.parametrize("change", ["link_key", "feature_alias", "detail_alias"])
async def test_lineage_is_not_removed_before_comparison(change):
    before = await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=NONE)
    current = before.model_copy(deep=True)
    if change == "link_key":
        current.source_link.source_record_key = "sr_" + "b" * 20
    elif change == "feature_alias":
        current.source_link.feature_id = "f_" + "b" * 20
    else:
        current.feature.detail.feature_id = "f_" + "b" * 20
    assert (await assess(before, current)).reason == "invalid_current_lineage"


@pytest.mark.parametrize(
    "change", ["hash", "key", "domain", "extra", "nontext", "pair", "infinite", "lossy"]
)
async def test_stored_projection_negative(change):
    before = await transport_item_to_native_bundle(airport(coords=True), fetched_at=NOW, geo=GEO)
    record = before.source_record.model_copy(deep=True)
    if change == "hash":
        record.raw_payload_hash = "a" * 32
    elif change == "key":
        record.source_record_key = "sr_" + "b" * 20
    elif change == "domain":
        record.dataset_key = "other"
    else:
        raw = dict(record.raw_data)
        if change == "extra":
            raw["extra"] = "unsupported"
        elif change == "nontext":
            raw["code"] = 123
        elif change == "pair":
            raw["latitude"] = None
        elif change == "infinite":
            raw["longitude"] = "Infinity"
        else:
            raw["longitude"] = "127.00000000000000001"
        record = rehash(record, raw)
    with pytest.raises(ValueError, match="Transport"):
        await rebuild_transport_projection(record, geo=GEO)


async def test_missing_geo_revision_presence_and_older_input_fail_closed():
    before = await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=NONE)
    missing = await assess_transport_scalar_refresh(
        before.source_record,
        before,
        previous_normalizer_revision=None,
        previous_geo=None,
        current_geo=None,
    )
    assert missing.reason == "missing_geo_evidence"
    assert (
        await assess(before, before, revision="unknown")
    ).reason == "unknown_normalizer_revision"
    no_presence = before.model_copy(update={"provider_field_presence": None})
    assert (await assess(before, no_presence)).reason == "unproven_presence"
    older = before.model_copy(deep=True)
    older.source_record.fetched_at = NOW - timedelta(seconds=1)
    assert (await assess(before, older)).reason == "older_observation"


async def test_changed_geo_tokens_fail_closed():
    before = await transport_item_to_native_bundle(airport(coords=True), fetched_at=NOW, geo=GEO)
    result = await assess_transport_scalar_refresh(
        before.source_record,
        before,
        previous_normalizer_revision=before.provider_field_presence.normalizer_revision,
        previous_geo=GEO,
        current_geo=replace(GEO, data_token="different"),
    )
    assert result.reason == "changed_geo_evidence"


async def test_blank_rest_name_is_not_complete_snapshot():
    with pytest.raises(ValueError, match="one item"):
        await transport_item_to_native_bundle(replace(rest(), name=" "), fetched_at=NOW, geo=NONE)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), 181.0])
async def test_nonfinite_or_out_of_range_input_is_rejected(coordinate):
    with pytest.raises(ValueError, match="Transport"):
        await transport_item_to_native_bundle(
            replace(airport(), coordinate=TransportCoordinate(lat=37.5, lon=coordinate)),
            fetched_at=NOW,
            geo=GEO,
        )


async def test_foreign_serializer_is_rejected_without_execution():
    calls = []

    class Foreign(BaseModel):
        @model_serializer
        def serialize(self):
            calls.append(True)
            return "a" * 2_000_000

    before = await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=NONE)
    current = before.model_copy(deep=True)
    current.feature.detail.payload = Foreign()
    assert (await assess(before, current)).reason == "invalid_bundle_budget"
    assert calls == []


async def test_budget_rejects_large_non_raw_detail_before_dump():
    before = await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=NONE)
    current = before.model_copy(deep=True)
    current.feature.detail.facility_info["huge"] = "a" * 1_048_577
    assert (await assess(before, current)).reason == "invalid_bundle_budget"


async def test_unrecognized_nonempty_phone_preserves_canonical_converter_value():
    b = await transport_item_to_native_bundle(
        rest(phone="internal-ext-203"), fetched_at=NOW, geo=NONE
    )
    assert b.feature.detail.phones == ["internal-ext-203"]


async def test_rest_supplied_identity_must_match_canonical_key():
    with pytest.raises(ValueError, match="자연키 불일치"):
        await transport_item_to_native_bundle(
            replace(rest(), natural_key="forged"), fetched_at=NOW, geo=NONE
        )


async def test_geo_mode_must_have_actual_coordinate_evidence():
    with pytest.raises(ValueError, match="Geo coordinate"):
        await transport_item_to_native_bundle(airport(coords=True), fetched_at=NOW, geo=NONE)
    with pytest.raises(ValueError, match="Geo coordinate"):
        await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=GEO)


async def test_noncanonical_nested_model_is_known_ineligible():
    before = await transport_item_to_native_bundle(airport(), fetched_at=NOW, geo=NONE)
    malformed = before.model_copy(update={"feature": {}})
    assert (await assess(before, malformed)).reason == "noncanonical_bundle"


async def test_observation_timezone_is_required():
    with pytest.raises(ValueError, match="aware"):
        await transport_item_to_native_bundle(
            airport(), fetched_at=datetime(2026, 10, 25), geo=NONE
        )


async def test_ignored_facility_flags_are_not_an_unbounded_object_channel():
    with pytest.raises(ValueError, match="flag type"):
        await transport_item_to_native_bundle(
            replace(rest(), has_gas_station="unknown"), fetched_at=NOW, geo=NONE
        )


@pytest.mark.parametrize("key", ["longitude", "latitude"])
@pytest.mark.parametrize("value", ["1e999999999", "-1e999999999"])
async def test_extreme_finite_decimal_exponent_is_known_ineligible(key, value):
    before = await transport_item_to_native_bundle(airport(coords=True), fetched_at=NOW, geo=GEO)
    current = before.model_copy(deep=True)
    raw = dict(current.source_record.raw_data)
    raw[key] = value
    record = rehash(current.source_record, raw)
    current.source_record = record
    current.source_link.source_record_key = record.source_record_key
    result = await assess(before, current, geo=GEO)
    assert not result.eligible
    assert result.reason == "invalid_typed_projection"


@pytest.mark.parametrize("geo", [NONE, GEO])
async def test_present_airport_coordinate_requires_two_float_components(geo):
    item = replace(airport(), coordinate=TransportCoordinate(lat=None, lon=None))
    with pytest.raises(ValueError, match="coordinate"):
        await transport_item_to_native_bundle(item, fetched_at=NOW, geo=geo)
