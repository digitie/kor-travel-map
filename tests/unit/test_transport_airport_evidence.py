"""공항 reader의 Geo 비교 domain 경계. DB 출처/reader 실행 증거는 아니다."""

import hashlib
import struct
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from kortravelmap.infra.transport_airport_evidence import (
    AIRPORT_ADDRESS_FIELDS,
    AIRPORT_GEO_DIGEST_DOMAIN,
    AIRPORT_READER_REVISION,
    AirportGeoFacts,
)


def _facts() -> AirportGeoFacts:
    return AirportGeoFacts(
        dataset_id=15,
        source_entity_key="se_" + "a" * 64,
        source_record_key="sr_" + "b" * 20,
        raw_payload_hash="c" * 64,
        feature_id=UUID("45b6b1f3-8a85-4984-932f-dc04358cb08b"),
        coordinate_ewkb="0101000020e6100000" + struct.pack("<dd", 126.45, 37.46).hex(),
        address=(
            "인천 공항",
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
    encoded = AIRPORT_GEO_DIGEST_DOMAIN
    for value in values:
        encoded += (
            b"\0"
            if value is None
            else b"\1" + len(value.encode()).to_bytes(8, "big") + value.encode()
        )
    assert f.digest() == hashlib.sha256(encoded).hexdigest()
    assert len(AIRPORT_ADDRESS_FIELDS) == 12
    assert len(AIRPORT_READER_REVISION) <= 32


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_id", 16),
        ("source_record_key", "sr_" + "d" * 20),
        ("raw_payload_hash", "d" * 64),
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
    with pytest.raises(ValueError, match="airport Geo"):
        replace(_facts(), **{field: value})


@pytest.mark.parametrize(
    ("lon", "lat"), [(float("nan"), 37.0), (127.0, float("inf")), (181.0, 37.0)]
)
def test_coordinate_binary_is_checked_before_float_text(lon: float, lat: float) -> None:
    with pytest.raises(ValueError, match="airport Geo"):
        replace(_facts(), coordinate_ewkb="0101000020e6100000" + struct.pack("<dd", lon, lat).hex())


def test_aware_time_outside_utc_datetime_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="observation range"):
        replace(_facts(), stamped_at=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))))
