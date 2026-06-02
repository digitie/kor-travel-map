"""Dagster 적재 전 좌표/주소 검증 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from krtour.map.dto import Address, Coordinate
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

from krtour.map_dagster.validation import validate_feature_bundles_address

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 2, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None


_FESTIVAL = _Festival(
    management_no="DAGSTER-UNIT-FEST-001",
    festival_name="서울 봄꽃 축제",
    venue_name="여의도공원",
    start_date=date(2026, 4, 5),
    end_date=date(2026, 4, 12),
    description="봄꽃 축제.",
    latitude=Decimal("37.5263"),
    longitude=Decimal("126.9239"),
    road_address="서울특별시 영등포구 여의공원로 120",
    jibun_address="서울특별시 영등포구 여의도동 8",
    organizer_name="영등포구청",
    organizer_tel="02-2670-3114",
    data_reference_date=date(2026, 3, 1),
    provider_org_name="서울특별시 영등포구",
)


async def _reverse(coord: Coordinate) -> Address:
    assert coord.lon == Decimal("126.9239")
    return Address(
        road="서울특별시 영등포구 여의공원로 120",
        legal="서울특별시 영등포구 여의도동 8",
        bjd_code="1156010100",
        sigungu_code="11560",
        sido_code="11",
        sido_name="서울특별시",
        sigungu_name="영등포구",
    )


async def test_coordinate_without_reverse_code_is_error() -> None:
    bundles = await cultural_festivals_to_bundles([_FESTIVAL], fetched_at=_FETCHED)

    validation = validate_feature_bundles_address(bundles)

    assert validation.has_errors
    assert [issue.code for issue in validation.issues] == ["missing_bjd_code"]


async def test_reverse_geocoded_provider_address_matches() -> None:
    bundles = await cultural_festivals_to_bundles(
        [_FESTIVAL],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
    )

    validation = validate_feature_bundles_address(bundles)

    assert not validation.has_errors
    assert validation.issue_count == 0
