"""Dagster 적재 전 좌표/주소 검증 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kortravelmap.dto import Address, Coordinate
from kortravelmap.providers.visitkorea import tourapi_festivals_to_bundles

from kortravelmap.dagster.validation import validate_feature_bundles_address

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 2, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    """`VisitKoreaFestivalItem` Protocol 만족 — provider ``TourItem`` 필드명."""

    content_id: str | None
    title: str | None
    content_type_id: str | None = "15"
    addr1: str | None = None
    addr2: str | None = None
    zipcode: str | None = None
    tel: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    lcls_systm1: str | None = None
    lcls_systm2: str | None = None
    lcls_systm3: str | None = None
    l_dong_regn_cd: str | None = None
    l_dong_signgu_cd: str | None = None
    created_time: datetime | None = None
    modified_time: datetime | None = None
    copyright_division_code: str | None = None
    event_start_date: str | None = None
    event_end_date: str | None = None
    overview: str | None = None
    homepage: str | None = None


_FESTIVAL = _Festival(
    content_id="900101",
    title="서울 봄꽃 축제",
    addr1="서울특별시 영등포구 여의공원로 120",
    addr2="여의도공원",
    tel="02-2670-3114",
    map_x=126.9239,
    map_y=37.5263,
    event_start_date="20260405",
    event_end_date="20260412",
    overview="봄꽃 축제.",
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
    bundles = await tourapi_festivals_to_bundles([_FESTIVAL], fetched_at=_FETCHED)

    validation = validate_feature_bundles_address(bundles)

    assert validation.has_errors
    # F-02: 좌표-있음+bjd-없음은 reverse-geocode 실패이므로 reverse_geocode_failed로 방출.
    assert [issue.code for issue in validation.issues] == ["reverse_geocode_failed"]


async def test_reverse_geocoded_provider_address_matches() -> None:
    bundles = await tourapi_festivals_to_bundles(
        [_FESTIVAL],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
    )

    validation = validate_feature_bundles_address(bundles)

    assert not validation.has_errors
    assert validation.issue_count == 0
