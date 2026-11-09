"""원천 좌표 결측 → 주소 정지오코딩 fallback(#1459 §4).

운영 2026-11-09: 축제 240·주차장 735·국가유산 place 1,338건이 주소(번지까지)를 갖고도 좌표 없이
적재됐다(asset이 reverse만 넘겼다). 행정구역까지인 주소(국가유산 행사 "경상남도 밀양시", MCST 클래스
"서울특별시 강서구 화곡6동")는 대표점이라 쓰지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate
from kortravelmap.geocoding import (
    address_has_location_number,
    cached_address_geocoder,
    geocode_missing_coordinate,
    kor_travel_geo_reverse_geocoder,
)
from kortravelmap.providers.krheritage import heritage_items_to_bundles
from kortravelmap.providers.standard_data import (
    cultural_festivals_to_bundles,
    parking_lots_to_bundles,
)

pytestmark = pytest.mark.unit

_FETCHED = datetime(2026, 11, 9, 9, 0, tzinfo=timezone(timedelta(hours=9)))
_POINT = Coordinate(lon=Decimal("128.6826"), lat=Decimal("37.6710"))


class _Geocoder:
    def __init__(self, answer: Coordinate | None = _POINT) -> None:
        self.calls: list[Address] = []
        self.answer = answer

    async def __call__(self, address: Address) -> Coordinate | None:
        self.calls.append(address)
        return self.answer


class _Reverse:
    def __init__(self) -> None:
        self.calls: list[Coordinate] = []

    async def __call__(self, coord: Coordinate) -> Address | None:
        self.calls.append(coord)
        return Address(bjd_code="5176025021", sigungu_code="51760", sido_code="51")


@pytest.mark.parametrize(
    ("road", "legal", "expected"),
    [
        ("강원특별자치도 평창군 대관령면 대관령로 135-9", None, True),
        (None, "전남광주통합특별시 신안군 안좌면 소곡리 599-4번지", True),
        (None, "경북 경주시 진현동 15번지 불국사", True),
        ("인천광역시 남동구 아암대로 1454 해오름광장", None, True),
        (None, "경상남도 밀양시", False),
        (None, "서울특별시 강서구 화곡6동", False),
        (None, "서울특별시 중구 을지로3가", False),
        (None, None, False),
        ("", "", False),
    ],
)
def test_address_has_location_number(road: str | None, legal: str | None, expected: bool) -> None:
    assert address_has_location_number(Address(road=road, legal=legal)) is expected


async def test_geocode_missing_coordinate_keeps_source_coordinate() -> None:
    geocoder = _Geocoder()
    source = Coordinate(lon=Decimal("127"), lat=Decimal("37"))
    address = Address(road="서울특별시 종로구 세종대로 1")
    assert await geocode_missing_coordinate(source, address, geocoder) == source
    assert geocoder.calls == []


async def test_geocode_missing_coordinate_skips_coarse_address_and_missing_geocoder() -> None:
    geocoder = _Geocoder()
    assert await geocode_missing_coordinate(None, Address(legal="경상남도 밀양시"), geocoder) is None
    assert geocoder.calls == []
    assert await geocode_missing_coordinate(None, Address(road="세종대로 1"), None) is None


async def test_cached_address_geocoder_remembers_answers_and_misses() -> None:
    inner = _Geocoder(answer=None)
    cached = cached_address_geocoder(inner)
    address = Address(road="서울특별시 종로구 세종대로 1", legal="서울특별시 종로구 세종로 1-1")
    assert await cached(address) is None
    assert await cached(address) is None
    assert len(inner.calls) == 1
    assert await cached(Address()) is None
    assert len(inner.calls) == 1


class _GeoClient:
    """``KorTravelGeoRestClient``의 ``geocode``만 흉내 — 도로명은 못 찾고 지번은 찾는다."""

    _stats = None

    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    async def geocode(self, query: str, *, type_: str = "road", fallback: str = "none") -> Any:
        self.queries.append((query, type_))
        if type_ == "road":
            return SimpleNamespace(status="NOT_FOUND", candidates=())
        candidate = SimpleNamespace(
            confidence=0.9, point=SimpleNamespace(lon=126.9, lat=37.5), address=None, region=None
        )
        return SimpleNamespace(status="OK", candidates=(candidate,))


async def test_geo_reverse_geocoder_geocodes_address_road_then_parcel() -> None:
    client = _GeoClient()
    geocoder = kor_travel_geo_reverse_geocoder(client)  # type: ignore[arg-type]
    coord = await geocoder.geocode_address(  # type: ignore[attr-defined]
        Address(road="서울 어딘가로 1", legal="서울 어딘가동 1-1")
    )
    assert coord == Coordinate(lon=Decimal("126.9"), lat=Decimal("37.5"))
    assert client.queries == [("서울 어딘가로 1", "road"), ("서울 어딘가동 1-1", "parcel")]


def _festival(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "fstvl_nm": "대관령눈꽃축제",
        "opar": "송천 주변",
        "fstvl_start_date": date(2025, 1, 24),
        "fstvl_end_date": date(2025, 2, 2),
        "fstvl_co": None,
        "mnnst_nm": "대관령면축제위원회",
        "auspc_instt_nm": None,
        "suprt_instt_nm": None,
        "phone_number": "033-335-3995",
        "homepage_url": None,
        "relate_info": None,
        "rdnmadr": "강원특별자치도 평창군 대관령면 대관령로 135-9",
        "lnmadr": "강원특별자치도 평창군 대관령면 횡계리 661",
        "latitude": None,
        "longitude": None,
        "reference_date": date(2025, 6, 20),
        "instt_code": None,
        "instt_nm": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_festival_without_coordinate_is_geocoded_then_reverse_geocoded() -> None:
    geocoder = _Geocoder()
    reverse = _Reverse()
    [bundle] = await cultural_festivals_to_bundles(
        [_festival()],
        fetched_at=_FETCHED,
        reverse_geocoder=reverse,
        address_geocoder=geocoder,
    )
    assert bundle.feature.coord == _POINT
    assert reverse.calls == [_POINT]
    assert bundle.feature.address.bjd_code == "5176025021"
    # 원천 payload는 그대로다(좌표 없음).
    assert bundle.source_record.raw_data["latitude"] is None
    assert geocoder.calls[0].road == "강원특별자치도 평창군 대관령면 대관령로 135-9"


async def test_festival_with_source_coordinate_does_not_call_geocoder() -> None:
    geocoder = _Geocoder()
    [bundle] = await cultural_festivals_to_bundles(
        [_festival(latitude=37.6, longitude=128.7)],
        fetched_at=_FETCHED,
        address_geocoder=geocoder,
    )
    assert geocoder.calls == []
    assert bundle.feature.coord == Coordinate(lon=Decimal("128.7"), lat=Decimal("37.6"))


async def test_festival_without_geocoder_stays_unplaced() -> None:
    [bundle] = await cultural_festivals_to_bundles([_festival()], fetched_at=_FETCHED)
    assert bundle.feature.coord is None


def _parking(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "prkplce_no": "345-2-000145",
        "prkplce_nm": "퍼플교주차장1",
        "prkplce_se": "공영",
        "rdnmadr": None,
        "lnmadr": "전남광주통합특별시 신안군 안좌면 소곡리 599-4번지",
        "prkcmprt": 40,
        "parkingchrge_info": "무료",
        "latitude": None,
        "longitude": None,
        "phone_number": None,
        "instt_code": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_parking_without_coordinate_is_geocoded_from_parcel_address() -> None:
    geocoder = _Geocoder()
    [bundle] = await parking_lots_to_bundles(
        [_parking()], fetched_at=_FETCHED, address_geocoder=geocoder
    )
    assert bundle.feature.coord == _POINT
    assert geocoder.calls[0].legal == "전남광주통합특별시 신안군 안좌면 소곡리 599-4번지"


def _heritage(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "key": SimpleNamespace(
            ccba_kdcd="11", ccba_asno="0000260000000", ccba_ctcd="37", natural_key="11-26-37"
        ),
        "name_ko": "경주 불국사 금동비로자나불좌상",
        "category": "국보",
        "region": "경상북도",
        "sigungu": "경주시",
        "longitude": "0.0",
        "latitude": "0.0",
        "location_text": "경북 경주시 진현동 15번지 불국사",
        "designated_at": "19621220",
        "owner": "불국사",
        "image_url": None,
        "geom_wkt": None,
        "boundary_source": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_heritage_place_with_zero_coordinate_is_geocoded() -> None:
    geocoder = _Geocoder()
    [bundle] = await heritage_items_to_bundles(
        [_heritage()], fetched_at=_FETCHED, address_geocoder=geocoder
    )
    assert bundle.feature.coord == _POINT
    assert geocoder.calls[0].legal == "경북 경주시 진현동 15번지 불국사"


async def test_heritage_place_with_region_only_location_stays_unplaced() -> None:
    geocoder = _Geocoder()
    [bundle] = await heritage_items_to_bundles(
        [_heritage(location_text="경상남도 밀양시")], fetched_at=_FETCHED, address_geocoder=geocoder
    )
    assert bundle.feature.coord is None
    assert geocoder.calls == []
