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
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


_FESTIVAL = _Festival(
    fstvl_nm="서울 봄꽃 축제",
    opar="여의도공원",
    fstvl_start_date=date(2026, 4, 5),
    fstvl_end_date=date(2026, 4, 12),
    fstvl_co="봄꽃 축제.",
    mnnst_nm="영등포구청",
    phone_number="02-2670-3114",
    rdnmadr="서울특별시 영등포구 여의공원로 120",
    lnmadr="서울특별시 영등포구 여의도동 8",
    latitude=37.5263,
    longitude=126.9239,
    reference_date=date(2026, 3, 1),
    instt_nm="서울특별시 영등포구",
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
