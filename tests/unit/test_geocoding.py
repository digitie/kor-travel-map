"""``test_geocoding`` — kraddr-geo REST API v2 연동 (krtour.map.geocoding).

kraddr-geo를 import하지 않고:
- 순수 변환 함수(``reverse_response_to_address``/``geocode_response_to_coordinate``)는
  REST 응답 shape를 만족하는 fake dataclass로 검증.
- ``KraddrGeoRestClient`` + 콜러블 팩토리는 ``httpx.MockTransport``로 실 HTTP 경로
  (요청 params + JSON 파싱 + 변환)를 서버 없이 검증.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
import pytest

from krtour.map.dto import Address, Coordinate
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    cached_reverse_geocoder,
    geocode_response_to_coordinate,
    kraddr_geo_address_geocoder,
    kraddr_geo_reverse_geocoder,
    reverse_response_to_address,
)

# -- kraddr-geo REST v2 응답 fake (structural) --------------------------------


@dataclass(frozen=True)
class _Point:
    x: float
    y: float


@dataclass(frozen=True)
class _Struct:
    level1: str | None = None
    level2: str | None = None
    level4L: str | None = None
    level4LC: str | None = None
    level4A: str | None = None
    level4AC: str | None = None
    level5: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class _RevItem:
    type: str
    text: str
    structure: _Struct
    point: _Point | None = None
    zipcode: str | None = None
    distance_m: float | None = None


@dataclass(frozen=True)
class _RevResp:
    status: str = "OK"
    result: tuple[_RevItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _GeoResult:
    point: _Point


@dataclass(frozen=True)
class _GeoExt:
    confidence: float = 1.0
    bjd_cd: str | None = None
    rncode_full: str | None = None
    zip_no: str | None = None


@dataclass(frozen=True)
class _GeoResp:
    status: str = "OK"
    result: _GeoResult | None = None
    x_extension: _GeoExt | None = None


_FULL_STRUCT = _Struct(
    level1="서울특별시",
    level2="영등포구",
    level4L="여의도동",
    level4LC="1156010100",
    level4A="여의동",
    level4AC="1156051000",
    level5="여의공원로",
)


# -- reverse_response_to_address ----------------------------------------------


def test_reverse_full_mapping() -> None:
    resp = _RevResp(
        result=(
            _RevItem(
                type="road",
                text="서울특별시 영등포구 여의공원로 120",
                structure=_FULL_STRUCT,
                zipcode="07237",
                distance_m=5.0,
            ),
            _RevItem(
                type="parcel",
                text="서울특별시 영등포구 여의도동 8",
                structure=_FULL_STRUCT,
                zipcode="07237",
                distance_m=6.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1156010100"
    assert addr.sigungu_code == "11560"
    assert addr.sido_code == "11"
    assert addr.admin_dong_code == "1156051000"
    assert addr.road == "서울특별시 영등포구 여의공원로 120"
    assert addr.legal == "서울특별시 영등포구 여의도동 8"
    assert addr.admin == "여의동"
    assert addr.zipcode == "07237"
    assert addr.sido_name == "서울특별시"
    assert addr.sigungu_name == "영등포구"
    # reverse structure에는 도로명코드 없음.
    assert addr.road_name_code is None


def test_reverse_derives_codes_from_bjd() -> None:
    resp = _RevResp(
        result=(_RevItem(type="parcel", text="x", structure=_Struct(level4LC="4117310200")),),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "4117310200"
    assert addr.sigungu_code == "41173"
    assert addr.sido_code == "41"


def test_reverse_road_falls_back_to_level5() -> None:
    # road 항목이 없으면 structure.level5(도로명)로 road 채움.
    resp = _RevResp(
        result=(
            _RevItem(type="parcel", text="지번주소", structure=_FULL_STRUCT, distance_m=3.0),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.legal == "지번주소"
    assert addr.road == "여의공원로"  # level5 fallback


def test_reverse_picks_closest_as_primary() -> None:
    resp = _RevResp(
        result=(
            _RevItem(
                type="parcel",
                text="가까움",
                structure=_Struct(level4LC="1111010100"),
                distance_m=3.0,
            ),
            _RevItem(
                type="parcel",
                text="멈",
                structure=_Struct(level4LC="1156010100"),
                distance_m=50.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1111010100"  # 최근접 항목이 대표


def test_reverse_max_distance_filters_out() -> None:
    resp = _RevResp(
        result=(
            _RevItem(
                type="parcel", text="far", structure=_FULL_STRUCT, distance_m=500.0
            ),
        ),
    )
    assert reverse_response_to_address(resp, max_distance_m=100.0) is None


def test_reverse_non_ok_status_is_none() -> None:
    resp = _RevResp(
        status="NOT_FOUND",
        result=(_RevItem(type="parcel", text="x", structure=_Struct()),),
    )
    assert reverse_response_to_address(resp) is None


def test_reverse_empty_result_is_none() -> None:
    assert reverse_response_to_address(_RevResp()) is None


def test_reverse_invalid_codes_dropped_not_raised() -> None:
    resp = _RevResp(
        result=(
            _RevItem(
                type="parcel",
                text="x",
                structure=_Struct(level4LC="짧음", level4AC="999"),
                zipcode="123",
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code is None
    assert addr.sigungu_code is None
    assert addr.sido_code is None
    assert addr.zipcode is None
    assert addr.admin_dong_code is None


@pytest.mark.parametrize("bad_status", ["NOT_FOUND", "ERROR"])
def test_reverse_handles_all_non_ok(bad_status: str) -> None:
    resp = _RevResp(
        status=bad_status,
        result=(_RevItem(type="parcel", text="x", structure=_Struct()),),
    )
    assert reverse_response_to_address(resp) is None


# -- geocode_response_to_coordinate -------------------------------------------


def test_geocode_point_to_coordinate() -> None:
    resp = _GeoResp(
        result=_GeoResult(point=_Point(x=127.05, y=37.55)),
        x_extension=_GeoExt(confidence=0.9),
    )
    coord = geocode_response_to_coordinate(resp)
    assert coord is not None
    assert coord.lon == Decimal("127.05")
    assert coord.lat == Decimal("37.55")


def test_geocode_min_confidence_filters_out() -> None:
    resp = _GeoResp(
        result=_GeoResult(point=_Point(127.0, 37.0)),
        x_extension=_GeoExt(confidence=0.4),
    )
    assert geocode_response_to_coordinate(resp, min_confidence=0.8) is None


def test_geocode_non_ok_is_none() -> None:
    resp = _GeoResp(status="ERROR", result=_GeoResult(point=_Point(1.0, 2.0)))
    assert geocode_response_to_coordinate(resp) is None


def test_geocode_no_result_is_none() -> None:
    assert geocode_response_to_coordinate(_GeoResp(status="OK", result=None)) is None


# -- KraddrGeoRestClient + 콜러블 팩토리 (httpx.MockTransport) -----------------


def _mock_client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://kraddr-geo.test",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def test_rest_reverse_geocoder_hits_endpoint() -> None:
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        assert request.url.path == "/v1/address/reverse"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": [
                    {
                        "type": "parcel",
                        "text": "서울특별시 영등포구 여의도동 8",
                        "structure": {"level1": "서울특별시", "level4LC": "1156010100"},
                        "zipcode": "07237",
                        "distance_m": 5.0,
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            reverse = kraddr_geo_reverse_geocoder(KraddrGeoRestClient(http), radius_m=100)
            addr = await reverse(Coordinate(lon=Decimal("126.924"), lat=Decimal("37.526")))
            assert addr is not None
            assert addr.bjd_code == "1156010100"
            assert addr.zipcode == "07237"

    asyncio.run(_run())
    assert seen[0].get("x") == "126.924"
    assert seen[0].get("y") == "37.526"
    assert seen[0].get("radius_m") == "100"
    assert seen[0].get("type") == "both"


def test_rest_address_geocoder_hits_endpoint() -> None:
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        assert request.url.path == "/v1/address/geocode"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {"crs": "EPSG:4326", "point": {"x": 127.1, "y": 37.4}},
                "x_extension": {"confidence": 0.95, "bjd_cd": "1156010100"},
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kraddr_geo_address_geocoder(KraddrGeoRestClient(http))
            coord = await geocode(
                Address(road="서울특별시 영등포구 여의공원로 120", bjd_code="1156010100")
            )
            assert coord is not None
            assert coord.lon == Decimal("127.1")
            assert coord.lat == Decimal("37.4")

    asyncio.run(_run())
    assert seen[0].get("address") == "서울특별시 영등포구 여의공원로 120"
    assert seen[0].get("type") == "road"


def test_rest_address_geocoder_uses_parcel_when_no_road() -> None:
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(
            200,
            json={"status": "OK", "result": {"point": {"x": 127.0, "y": 37.0}}},
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kraddr_geo_address_geocoder(KraddrGeoRestClient(http))
            coord = await geocode(Address(legal="서울특별시 영등포구 여의도동 8"))
            assert coord is not None

    asyncio.run(_run())
    assert seen[0].get("type") == "parcel"
    assert seen[0].get("address") == "서울특별시 영등포구 여의도동 8"


def test_address_geocoder_returns_none_without_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("주소가 없으면 HTTP 호출하지 않아야 함")

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kraddr_geo_address_geocoder(KraddrGeoRestClient(http))
            assert await geocode(Address()) is None

    asyncio.run(_run())


def test_rest_geocoder_returns_none_on_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "NOT_FOUND"})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KraddrGeoRestClient(http)
            reverse = kraddr_geo_reverse_geocoder(client)
            geocode = kraddr_geo_address_geocoder(client)
            assert await reverse(Coordinate(lon=Decimal("127"), lat=Decimal("37"))) is None
            assert await geocode(Address(road="아무 도로 1")) is None

    asyncio.run(_run())


# -- cached_reverse_geocoder --------------------------------------------------


def test_cached_reverse_geocoder_dedupes_by_coord() -> None:
    calls: list[tuple[Decimal, Decimal]] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append((coord.lon, coord.lat))
        return Address(bjd_code="1156010100")

    cached = cached_reverse_geocoder(_rg)

    async def _run() -> None:
        c1 = Coordinate(lon=Decimal("127.0000001"), lat=Decimal("37.5000001"))
        c2 = Coordinate(lon=Decimal("127.0000002"), lat=Decimal("37.5000002"))  # 6자리 동일
        c3 = Coordinate(lon=Decimal("128.0"), lat=Decimal("38.0"))
        a1 = await cached(c1)
        a2 = await cached(c2)
        a3 = await cached(c3)
        assert a1 is not None
        assert a1.bjd_code == "1156010100"
        assert a2 is a1  # 같은 양자화 키 → 캐시 재사용 (동일 객체)
        assert a3 is not None

    asyncio.run(_run())
    assert len(calls) == 2  # c1/c2 묶임, c3 별도


def test_cached_reverse_geocoder_caches_none() -> None:
    calls = 0

    async def _rg(coord: Coordinate) -> Address | None:
        nonlocal calls
        calls += 1
        return None

    cached = cached_reverse_geocoder(_rg)

    async def _run() -> None:
        c = Coordinate(lon=Decimal("127.0"), lat=Decimal("37.5"))
        assert await cached(c) is None
        assert await cached(c) is None  # None도 캐싱 — 재시도 안 함

    asyncio.run(_run())
    assert calls == 1
