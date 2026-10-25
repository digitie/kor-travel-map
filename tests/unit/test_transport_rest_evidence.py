"""휴게소 reader의 Geo 비교 domain 경계. DB 출처/reader 실행 증거는 아니다."""

import hashlib
import struct
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from kortravelmap.infra.transport_rest_evidence import (
    REST_AREA_ADDRESS_FIELDS,
    REST_AREA_GEO_DIGEST_DOMAIN,
    REST_AREA_READER_REVISION,
    RestAreaGeoFacts,
)


def _facts() -> RestAreaGeoFacts:
    return RestAreaGeoFacts(
        dataset_id=15,
        source_entity_key="se_" + "a" * 64,
        source_record_key="sr_" + "b" * 20,
        raw_payload_hash="c" * 32,
        feature_id=UUID("45b6b1f3-8a85-4984-932f-dc04358cb08b"),
        coordinate_ewkb="0101000020e6100000" + struct.pack("<dd", 126.45, 37.46).hex(),
        address=(
            "인천 휴게소",
            None,
            None,
            "2811010100",
            None,
            "28110",
            "28",
            None,
            None,
            "22382",
            "인천광역시",
            "중구",
        ),
        geo_version_token="version1",
        geo_data_token="data1",
        reverse_outcome="called",
        stamped_at=datetime(2026, 10, 25, tzinfo=UTC),
    )


def test_digest_has_independent_fixed_field_order_and_length_frames() -> None:
    f = _facts()
    values = (
        "15",
        f.source_entity_key,
        f.source_record_key,
        f.raw_payload_hash,
        str(f.feature_id),
        f.coordinate_ewkb,
        *f.address,
        "version1",
        "data1",
        "called",
        "2026-10-25T00:00:00.000000Z",
    )
    encoded = REST_AREA_GEO_DIGEST_DOMAIN
    for value in values:
        encoded += (
            b"\0"
            if value is None
            else b"\1" + len(value.encode()).to_bytes(8, "big") + value.encode()
        )
    assert f.digest() == hashlib.sha256(encoded).hexdigest()
    assert len(REST_AREA_ADDRESS_FIELDS) == 12
    assert len(REST_AREA_READER_REVISION) <= 32


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_id", 16),
        ("source_record_key", "sr_" + "d" * 20),
        ("raw_payload_hash", "d" * 32),
        ("geo_version_token", "v2"),
        ("geo_data_token", "d2"),
        ("stamped_at", datetime(2026, 10, 25, 0, 0, 1, tzinfo=UTC)),
    ],
)
def test_digest_binds_each_identity_token_and_stamp(field: str, value: object) -> None:
    f = _facts()
    assert replace(f, **{field: value}).digest() != f.digest()


def test_null_empty_and_delimiter_text_are_unambiguous() -> None:
    f = _facts()
    assert (
        replace(f, address=("", *f.address[1:])).digest()
        != replace(f, address=(None, *f.address[1:])).digest()
    )
    assert replace(f, address=("x\ny:1", *f.address[1:])).digest() != f.digest()


def test_same_instant_has_one_utc_digest() -> None:
    f = _facts()
    assert (
        replace(f, stamped_at=f.stamped_at.astimezone(timezone(timedelta(hours=9)))).digest()
        == f.digest()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_id", True),
        ("dataset_id", 0),
        ("source_entity_key", "a" * 1_000_000),
        ("raw_payload_hash", "f" * 63),
        ("raw_payload_hash", "f" * 64),
        ("reverse_outcome", "geocoded"),
        ("reverse_outcome", "not_called"),
        ("geo_data_token", " token"),
        ("geo_data_token", "x\0y"),
        ("geo_version_token", "한" * 100),
        ("address", (None,)),
        ("address", [None] * 12),
        ("address", ("한" * 3000,) + (None,) * 11),
        ("stamped_at", datetime(2026, 10, 25)),
    ],
)
def test_invalid_or_unbounded_claim_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="rest-area Geo"):
        replace(_facts(), **{field: value})


@pytest.mark.parametrize(
    ("lon", "lat"), [(float("nan"), 37.0), (127.0, float("inf")), (181.0, 37.0)]
)
def test_coordinate_binary_is_checked_before_float_text(lon: float, lat: float) -> None:
    with pytest.raises(ValueError, match="rest-area Geo"):
        replace(_facts(), coordinate_ewkb="0101000020e6100000" + struct.pack("<dd", lon, lat).hex())


def test_aware_time_outside_utc_datetime_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="observation range"):
        replace(_facts(), stamped_at=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))))


@pytest.mark.asyncio
async def test_actual_converter_source_record_uses_32hex_payload_prefix() -> None:
    from kortravelmap.core.ids import make_payload_hash, make_source_record_key
    from kortravelmap.dto import Address, SourceRecord
    from kortravelmap.infra.feature_repo import _make_source_entity_key
    from kortravelmap.providers.kor_travel_transport import TransportRestArea
    from kortravelmap.providers.kor_travel_transport_native import (
        TransportGeoEvidence,
        transport_item_to_native_bundle,
    )
    from kortravelmap.providers.krex import rest_area_natural_key

    address = Address(bjd_code="2811010100")
    item = TransportRestArea(
        "temporary",
        "인천휴게소",
        "고속도로",
        "서울",
        126.45,
        37.46,
        "032-123-4567",
        None,
        None,
        None,
        {},
    )
    item = replace(item, natural_key=rest_area_natural_key(item))
    bundle = await transport_item_to_native_bundle(
        item,
        fetched_at=datetime(2026, 10, 25, tzinfo=UTC),
        geo=TransportGeoEvidence("resolved", "version1", "data1", address, "d" * 64),
    )
    record = bundle.source_record
    assert type(record) is SourceRecord
    assert len(record.raw_payload_hash) == 32
    assert record.raw_payload_hash == make_payload_hash(record.raw_data)
    assert record.source_record_key == make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=record.raw_payload_hash,
    )
    facts = replace(
        _facts(),
        raw_payload_hash=record.raw_payload_hash,
        source_record_key=record.source_record_key,
        source_entity_key=_make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        ),
        address=tuple(getattr(address, field) for field in REST_AREA_ADDRESS_FIELDS),
    )
    assert len(facts.digest()) == 64


def test_rest_digest_is_disjoint_from_airport_for_identical_facts() -> None:
    from dataclasses import asdict

    from kortravelmap.infra.transport_airport_evidence import AirportGeoFacts

    rest = _facts()
    assert rest.digest() != AirportGeoFacts(**asdict(rest)).digest()


def test_foreign_timezone_is_rejected_before_its_hook() -> None:
    from datetime import tzinfo

    calls = []

    class ForeignTimezone(tzinfo):
        def utcoffset(self, dt):
            calls.append("utcoffset")
            raise AssertionError("foreign timezone hook")

    with pytest.raises(ValueError, match="rest-area Geo observation time"):
        replace(_facts(), stamped_at=datetime(2026, 10, 25, tzinfo=ForeignTimezone()))
    assert calls == []


def test_canonical_seoul_zone_preserves_original_instant_digest() -> None:
    from zoneinfo import ZoneInfo

    facts = _facts()
    assert (
        replace(facts, stamped_at=facts.stamped_at.astimezone(ZoneInfo("Asia/Seoul"))).digest()
        == facts.digest()
    )
