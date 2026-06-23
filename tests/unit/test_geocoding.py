"""``test_geocoding`` — kor-travel-geo REST API v2 연동 (kortravelmap.geocoding).

kor-travel-geo를 import하지 않고:
- 순수 변환 함수(``reverse_response_to_address``/``geocode_response_to_coordinate``)는
  REST v2 응답 shape(``CandidateV2``/``AddressV2``/``RegionV2``/``PointV2``)를 만족하는
  fake dataclass로 검증.
- ``KorTravelGeoRestClient`` + 콜러블 팩토리는 ``httpx.MockTransport``로 실 HTTP 경로
  (``POST /v2/*`` JSON body + 응답 파싱 + 변환)를 서버 없이 검증.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
import pytest

from kortravelmap.dto import Address, Coordinate
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    cached_address_resolver,
    cached_reverse_geocoder,
    geocode_response_to_address,
    geocode_response_to_coordinate,
    kor_travel_geo_address_geocoder,
    kor_travel_geo_address_resolver,
    kor_travel_geo_reverse_geocoder,
    resolve_regions_within_radius,
    resolve_sigungu_by_radius,
    reverse_response_to_address,
)

pytestmark = pytest.mark.unit

# -- kor-travel-geo REST v2 응답 fake (structural Protocol 만족) -------------------


@dataclass(frozen=True)
class _Point:
    lon: float
    lat: float


@dataclass(frozen=True)
class _AddrV2:
    full: str = ""
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    legal_dong_code: str | None = None
    admin_dong_code: str | None = None
    road_name: str | None = None
    road_name_code: str | None = None


@dataclass(frozen=True)
class _RegionV2:
    sig_cd: str | None = None
    bjd_cd: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    eup_myeon_dong: str | None = None
    legal_dong: str | None = None
    admin_dong: str | None = None


@dataclass(frozen=True)
class _CandV2:
    confidence: float = 0.0
    match_kind: str = ""
    address: _AddrV2 | None = None
    point: _Point | None = None
    distance_m: float | None = None
    region: _RegionV2 | None = None


@dataclass(frozen=True)
class _RevResp:
    status: str = "OK"
    candidates: tuple[_CandV2, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _GeoResp:
    status: str = "OK"
    candidates: tuple[_CandV2, ...] = field(default_factory=tuple)


_FULL_ADDR_ROAD = _AddrV2(
    full="서울특별시 영등포구 여의공원로 120",
    road_address="서울특별시 영등포구 여의공원로 120",
    postal_code="07237",
    legal_dong_code="1156010100",
    admin_dong_code="1156051000",
    road_name="여의공원로",
    road_name_code="115603122001",
)
_FULL_ADDR_PARCEL = _AddrV2(
    full="서울특별시 영등포구 여의도동 8",
    parcel_address="서울특별시 영등포구 여의도동 8",
    postal_code="07237",
    legal_dong_code="1156010100",
    admin_dong_code="1156051000",
)
_FULL_REGION = _RegionV2(
    sig_cd="11560",
    bjd_cd="1156010100",
    sido="서울특별시",
    sigungu="영등포구",
    eup_myeon_dong="여의도동",
    legal_dong="여의도동",
    admin_dong="여의동",
)


# -- reverse_response_to_address ----------------------------------------------


def test_reverse_full_mapping() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                confidence=0.66,
                match_kind="road",
                address=_FULL_ADDR_ROAD,
                point=_Point(126.978, 37.567),
                distance_m=5.0,
                region=_FULL_REGION,
            ),
            _CandV2(
                confidence=0.66,
                match_kind="parcel",
                address=_FULL_ADDR_PARCEL,
                point=_Point(126.978, 37.567),
                distance_m=6.0,
                region=_FULL_REGION,
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
    assert addr.road_name_code == "115603122001"


def test_reverse_derives_codes_from_bjd() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(full="x", legal_dong_code="4117310200"),
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "4117310200"
    assert addr.sigungu_code == "41173"
    assert addr.sido_code == "41"


def test_reverse_bjd_falls_back_to_region() -> None:
    # address.legal_dong_code가 없으면 region.bjd_cd로 채움.
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(full="x"),
                region=_RegionV2(bjd_cd="1156010100"),
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1156010100"


def test_reverse_sig_cd_fallback_when_bjd_missing() -> None:
    """kor-travel-geo v2 ``RegionV2.sig_cd``를 bjd 없는 응답에서도 보존한다."""
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="region",
                address=_AddrV2(full="서울특별시 영등포구"),
                region=_RegionV2(
                    sig_cd="11560",
                    sido="서울특별시",
                    sigungu="영등포구",
                    eup_myeon_dong="여의도동",
                ),
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code is None
    assert addr.sigungu_code == "11560"
    assert addr.sido_code == "11"
    assert addr.admin == "여의도동"
    assert addr.sido_name == "서울특별시"
    assert addr.sigungu_name == "영등포구"


def test_reverse_road_falls_back_to_full() -> None:
    # road match candidate가 없으면 대표 candidate의 road_address(없으면 full)로 road 채움.
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(
                    full="서울특별시 영등포구 여의도동 8",
                    parcel_address="서울특별시 영등포구 여의도동 8",
                ),
                distance_m=3.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.legal == "서울특별시 영등포구 여의도동 8"
    assert addr.road == "서울특별시 영등포구 여의도동 8"  # full fallback


def test_reverse_picks_closest_as_primary() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(full="가까움", legal_dong_code="1111010100"),
                distance_m=3.0,
            ),
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(full="멈", legal_dong_code="1156010100"),
                distance_m=50.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1111010100"  # 최근접 항목이 대표


def test_reverse_road_parcel_text_split() -> None:
    # road candidate → road, parcel candidate → legal 로 분리 채움.
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="road",
                address=_AddrV2(
                    full="서울특별시 영등포구 여의공원로 120",
                    road_address="서울특별시 영등포구 여의공원로 120",
                    legal_dong_code="1156010100",
                ),
                distance_m=5.0,
            ),
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(
                    full="서울특별시 영등포구 여의도동 8",
                    parcel_address="서울특별시 영등포구 여의도동 8",
                    legal_dong_code="1156010100",
                ),
                distance_m=6.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.road == "서울특별시 영등포구 여의공원로 120"
    assert addr.legal == "서울특별시 영등포구 여의도동 8"


def test_reverse_max_distance_filters_out() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_FULL_ADDR_PARCEL,
                distance_m=500.0,
            ),
        ),
    )
    assert reverse_response_to_address(resp, max_distance_m=100.0) is None


def test_reverse_non_ok_status_is_none() -> None:
    resp = _RevResp(
        status="NOT_FOUND",
        candidates=(_CandV2(match_kind="parcel", address=_AddrV2(full="x")),),
    )
    assert reverse_response_to_address(resp) is None


def test_reverse_empty_candidates_is_none() -> None:
    assert reverse_response_to_address(_RevResp()) is None


def test_reverse_invalid_codes_dropped_not_raised() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(
                    full="x",
                    legal_dong_code="짧음",
                    admin_dong_code="999",
                    postal_code="123",
                ),
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code is None
    assert addr.sigungu_code is None
    assert addr.sido_code is None
    assert addr.zipcode is None  # 5자리 아님 → drop
    assert addr.admin_dong_code is None  # 10자리 아님 → drop


def test_reverse_bjd_value_error_is_caught() -> None:
    """``normalize_bjd_code``는 비-10자리 입력에 ValueError raise — 이 raise가
    ``reverse_response_to_address``까지 새지 않도록 보장(graceful drop)."""
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                # 숫자지만 비-10자리 — normalize_bjd_code가 ValueError raise.
                address=_AddrV2(full="x", legal_dong_code="1234"),
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.bjd_code is None
    assert addr.sigungu_code is None
    assert addr.sido_code is None


def test_reverse_zipcode_five_digit_filter() -> None:
    resp = _RevResp(
        candidates=(
            _CandV2(
                match_kind="parcel",
                address=_AddrV2(full="x", postal_code="04520"),
                distance_m=1.0,
            ),
        ),
    )
    addr = reverse_response_to_address(resp)
    assert addr is not None
    assert addr.zipcode == "04520"


@pytest.mark.parametrize("bad_status", ["NOT_FOUND", "ERROR"])
def test_reverse_handles_all_non_ok(bad_status: str) -> None:
    resp = _RevResp(
        status=bad_status,
        candidates=(_CandV2(match_kind="parcel", address=_AddrV2(full="x")),),
    )
    assert reverse_response_to_address(resp) is None


# -- geocode_response_to_coordinate -------------------------------------------


def test_geocode_point_to_coordinate() -> None:
    resp = _GeoResp(
        candidates=(
            _CandV2(
                confidence=0.9,
                match_kind="road",
                point=_Point(lon=127.05, lat=37.55),
            ),
        ),
    )
    coord = geocode_response_to_coordinate(resp)
    assert coord is not None
    assert coord.lon == Decimal("127.05")
    assert coord.lat == Decimal("37.55")


def test_geocode_response_to_address_uses_structured_legal_dong_code() -> None:
    resp = _GeoResp(
        candidates=(
            _CandV2(
                confidence=0.92,
                match_kind="road",
                address=_FULL_ADDR_ROAD,
                region=_FULL_REGION,
            ),
        )
    )

    address = geocode_response_to_address(resp, min_confidence=0.8)

    assert address is not None
    assert address.road == "서울특별시 영등포구 여의공원로 120"
    assert address.bjd_code == "1156010100"
    assert address.sigungu_code == "11560"
    assert address.sido_code == "11"


def test_geocode_response_to_address_filters_low_confidence() -> None:
    resp = _GeoResp(
        candidates=(
            _CandV2(
                confidence=0.3,
                match_kind="road",
                address=_FULL_ADDR_ROAD,
                region=_FULL_REGION,
            ),
        )
    )

    assert geocode_response_to_address(resp, min_confidence=0.8) is None


def test_geocode_picks_max_confidence() -> None:
    resp = _GeoResp(
        candidates=(
            _CandV2(confidence=0.4, match_kind="road", point=_Point(1.0, 1.0)),
            _CandV2(confidence=0.95, match_kind="road", point=_Point(127.0, 37.0)),
        ),
    )
    coord = geocode_response_to_coordinate(resp)
    assert coord is not None
    assert coord.lon == Decimal("127.0")
    assert coord.lat == Decimal("37.0")


def test_geocode_min_confidence_filters_out() -> None:
    resp = _GeoResp(
        candidates=(
            _CandV2(confidence=0.4, match_kind="road", point=_Point(127.0, 37.0)),
        ),
    )
    assert geocode_response_to_coordinate(resp, min_confidence=0.8) is None


def test_geocode_non_ok_is_none() -> None:
    resp = _GeoResp(
        status="ERROR",
        candidates=(_CandV2(confidence=0.9, point=_Point(1.0, 2.0)),),
    )
    assert geocode_response_to_coordinate(resp) is None


def test_geocode_no_candidates_is_none() -> None:
    assert geocode_response_to_coordinate(_GeoResp(status="OK")) is None


def test_geocode_no_point_is_none() -> None:
    resp = _GeoResp(candidates=(_CandV2(confidence=0.9, match_kind="road"),))
    assert geocode_response_to_coordinate(resp) is None


# -- KorTravelGeoRestClient + 콜러블 팩토리 (httpx.MockTransport) -----------------


def _mock_client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://kor-travel-geo.test",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _body(request: httpx.Request) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(request.content.decode())
    return parsed


def test_rest_reverse_geocoder_hits_endpoint() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        assert request.method == "POST"
        assert request.url.path == "/v2/reverse"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.66,
                        "match_kind": "parcel",
                        "address": {
                            "full": "서울특별시 영등포구 여의도동 8",
                            "parcel_address": "서울특별시 영등포구 여의도동 8",
                            "postal_code": "07237",
                            "legal_dong_code": "1156010100",
                        },
                        "point": {"lon": 126.924, "lat": 37.526},
                        "distance_m": 5.0,
                        "region": {"sig_cd": "11560", "bjd_cd": "1156010100"},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            reverse = kor_travel_geo_reverse_geocoder(
                KorTravelGeoRestClient(http), radius_m=100
            )
            addr = await reverse(
                Coordinate(lon=Decimal("126.924"), lat=Decimal("37.526"))
            )
            assert addr is not None
            assert addr.bjd_code == "1156010100"
            assert addr.sigungu_code == "11560"
            assert addr.zipcode == "07237"

    asyncio.run(_run())
    body = seen[0]
    assert body["lon"] == 126.924
    assert body["lat"] == 37.526
    assert body["radius_m"] == 100
    assert body["include_region"] is True
    assert body["include_zipcode"] is True


def test_rest_reverse_geocoder_accepts_lon_lat_point_aliases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/reverse"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.9,
                        "match_kind": "parcel",
                        "address": {
                            "full": "서울특별시 중구 세종대로 110",
                            "parcel_address": "서울특별시 중구 태평로1가 31",
                            "legal_dong_code": "1114010300",
                        },
                        "point": {"lon": 126.9777, "lat": 37.5662},
                        "region": {"sig_cd": "11140", "bjd_cd": "1114010300"},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            reverse = kor_travel_geo_reverse_geocoder(KorTravelGeoRestClient(http))
            addr = await reverse(
                Coordinate(lon=Decimal("126.9777"), lat=Decimal("37.5662"))
            )
            assert addr is not None
            assert addr.bjd_code == "1114010300"

    asyncio.run(_run())


def test_rest_address_geocoder_hits_endpoint() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        assert request.method == "POST"
        assert request.url.path == "/v2/geocode"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.9,
                        "match_kind": "road",
                        "point": {"lon": 127.1, "lat": 37.4},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kor_travel_geo_address_geocoder(KorTravelGeoRestClient(http))
            coord = await geocode(
                Address(
                    road="서울특별시 영등포구 여의공원로 120", bjd_code="1156010100"
                )
            )
            assert coord is not None
            assert coord.lon == Decimal("127.1")
            assert coord.lat == Decimal("37.4")

    asyncio.run(_run())
    body = seen[0]
    assert body["road_address"] == "서울특별시 영등포구 여의공원로 120"
    assert "jibun_address" not in body
    assert body["fallback"] == "none"


def test_rest_address_geocoder_accepts_lon_lat_point_aliases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/geocode"

        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.9,
                        "match_kind": "road",
                        "point": {"lon": 127.1, "lat": 37.4},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kor_travel_geo_address_geocoder(KorTravelGeoRestClient(http))
            coord = await geocode(Address(road="서울특별시 영등포구 여의공원로 120"))
            assert coord == Coordinate(lon=Decimal("127.1"), lat=Decimal("37.4"))

    asyncio.run(_run())


def test_rest_address_geocoder_accepts_legacy_xy_point() -> None:
    """pre-ADR-062 ``point.x/y`` 응답도 REST 파서 fallback으로 계속 읽는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.9,
                        "match_kind": "road",
                        "point": {"x": 127.1, "y": 37.4},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kor_travel_geo_address_geocoder(KorTravelGeoRestClient(http))
            coord = await geocode(Address(road="서울특별시 영등포구 여의공원로 120"))
            assert coord is not None
            assert coord.lon == Decimal("127.1")
            assert coord.lat == Decimal("37.4")

    asyncio.run(_run())


def test_rest_address_geocoder_uses_parcel_when_no_road() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.9,
                        "match_kind": "parcel",
                        "point": {"lon": 127.0, "lat": 37.0},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kor_travel_geo_address_geocoder(KorTravelGeoRestClient(http))
            coord = await geocode(Address(legal="서울특별시 영등포구 여의도동 8"))
            assert coord is not None

    asyncio.run(_run())
    body = seen[0]
    assert body["jibun_address"] == "서울특별시 영등포구 여의도동 8"
    assert "road_address" not in body


def test_address_geocoder_returns_none_without_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("주소가 없으면 HTTP 호출하지 않아야 함")

    async def _run() -> None:
        async with _mock_client(handler) as http:
            geocode = kor_travel_geo_address_geocoder(KorTravelGeoRestClient(http))
            assert await geocode(Address()) is None

    asyncio.run(_run())


def test_rest_geocoder_returns_none_on_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "NOT_FOUND", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            reverse = kor_travel_geo_reverse_geocoder(client)
            geocode = kor_travel_geo_address_geocoder(client)
            rev = await reverse(
                Coordinate(lon=Decimal("127"), lat=Decimal("37"))
            )
            geo = await geocode(Address(road="아무 도로 1"))
            assert rev is None
            assert geo is None

    asyncio.run(_run())


# -- KorTravelGeoRestClient 세부 동작 (wire-level 회귀) ---------------------------
#
# base_path/JSON body/예외 전파 등 client 내부 동작은 통합 e2e만으로는 회귀
# 검출이 어렵다 — httpx.MockTransport로 wire-level 동작을 고정한다.


def test_rest_client_base_path_trailing_slash_stripped() -> None:
    """base_path="/v2/" (끝 슬래시) → 내부에서 정규화 후 "/v2/...". 슬래시 중복 없음."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http, base_path="/v2/")
            await client.reverse(127.0, 37.0)
            await client.geocode("서울특별시 중구 세종대로 110")

    asyncio.run(_run())
    assert seen == ["/v2/reverse", "/v2/geocode"]


def test_rest_client_custom_base_path() -> None:
    """base_path를 "/api/v2"로 — 운영 reverse proxy 경로 prefix 시나리오."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http, base_path="/api/v2")
            await client.reverse(127.0, 37.0)

    asyncio.run(_run())
    assert seen == ["/api/v2/reverse"]


def test_rest_client_api_key_is_sent_as_vworld_compatible_query() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.url.params.get("key", "")))
        if request.url.path.endswith("/regions/within-radius"):
            return httpx.Response(
                200,
                json={
                    "center": {"lon": 126.978, "lat": 37.5665},
                    "radius_km": 3.0,
                    "sigungu": [],
                    "emd": [],
                },
            )
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http, api_key=" geo-key ")
            await client.reverse(127.0, 37.0)
            await client.geocode("서울특별시 중구 세종대로 110")
            await client.regions_within_radius(lon=126.978, lat=37.5665)

    asyncio.run(_run())
    assert seen == [
        ("/v2/reverse", "geo-key"),
        ("/v2/geocode", "geo-key"),
        ("/v2/regions/within-radius", "geo-key"),
    ]


def test_rest_client_reverse_radius_m_none_omits_key() -> None:
    """radius_m=None (기본) → JSON body에서 키 자체 누락 — upstream 기본값 따름."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            await client.reverse(127.0, 37.0)  # radius_m 미지정.

    asyncio.run(_run())
    assert "radius_m" not in seen[0]


def test_rest_client_reverse_include_flags_default_true() -> None:
    """include_region/include_zipcode 기본 True가 JSON body bool로 직렬화."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            await client.reverse(127.0, 37.0)

    asyncio.run(_run())
    body = seen[0]
    assert body["include_region"] is True
    assert body["include_zipcode"] is True


def test_rest_client_reverse_include_flags_false() -> None:
    """include_region/include_zipcode=False가 JSON body에 그대로 반영."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(200, json={"status": "OK", "candidates": []})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            await client.reverse(
                127.0, 37.0, include_region=False, include_zipcode=False
            )

    asyncio.run(_run())
    body = seen[0]
    assert body["include_region"] is False
    assert body["include_zipcode"] is False


@pytest.mark.parametrize(
    ("type_", "key"),
    [("road", "road_address"), ("parcel", "jibun_address")],
)
def test_rest_client_geocode_type_selects_body_key(type_: str, key: str) -> None:
    """type_="road" → road_address, type_="parcel" → jibun_address 필드로 보냄."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [{"confidence": 1.0, "point": {"lon": 1, "lat": 1}}],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            await client.geocode("addr", type_=type_)  # type: ignore[arg-type]

    asyncio.run(_run())
    assert seen[0][key] == "addr"


@pytest.mark.parametrize("fallback", ["none", "api"])
def test_rest_client_geocode_fallback_passes_through(fallback: str) -> None:
    """fallback 인자가 JSON body `fallback`로 그대로 전달."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [{"confidence": 1.0, "point": {"lon": 1, "lat": 1}}],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            await client.geocode("addr", fallback=fallback)  # type: ignore[arg-type]

    asyncio.run(_run())
    assert seen[0]["fallback"] == fallback


def test_rest_client_reverse_raises_on_http_500() -> None:
    """upstream 500 → httpx.HTTPStatusError 전파 (raise_for_status)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "upstream broken"})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            with pytest.raises(httpx.HTTPStatusError):
                await client.reverse(127.0, 37.0)

    asyncio.run(_run())


def test_rest_client_geocode_raises_on_http_502() -> None:
    """upstream 502 (bad gateway) → 전파."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            with pytest.raises(httpx.HTTPStatusError):
                await client.geocode("addr")

    asyncio.run(_run())


def test_rest_client_regions_within_radius_hits_endpoint() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        assert request.method == "POST"
        assert request.url.path == "/v2/regions/within-radius"
        return httpx.Response(
            200,
            json={
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 3.0,
                "sigungu": [
                    {"code": "11110", "name": "종로구", "relation": "contains"},
                    {"code": "11140", "name": "중구", "relation": "overlaps"},
                ],
                "emd": [
                    {"code": "11110119", "name": "세종로", "relation": "contains"}
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            response = await client.regions_within_radius(
                lon=126.978,
                lat=37.5665,
                radius_km=3.0,
                levels=("sigungu", "emd"),
            )
            assert response.center.lon == 126.978
            assert response.center.lat == 37.5665
            assert response.radius_km == 3.0
            assert [item.code for item in response.sigungu] == ["11110", "11140"]
            assert response.sigungu[0].relation == "contains"
            assert response.sigungu[1].relation == "overlaps"
            assert response.emd[0].code == "11110119"
            assert response.sido == ()

    asyncio.run(_run())
    assert seen == [
        {
            "lon": 126.978,
            "lat": 37.5665,
            "radius_km": 3.0,
            "levels": ["sigungu", "emd"],
        }
    ]


def test_rest_client_regions_within_radius_default_levels() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 3.0,
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            await KorTravelGeoRestClient(http).regions_within_radius(
                lon=126.978,
                lat=37.5665,
            )

    asyncio.run(_run())
    assert seen[0]["levels"] == ["sigungu", "emd"]


def test_rest_client_regions_within_radius_center_xy_fallback_and_malformed_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "center": {"x": 126.978, "y": 37.5665},
                "radius_km": "3.0",
                "sigungu": [
                    {"code": "11110", "name": "종로구", "relation": "contains"},
                    {"code": "", "name": "무효", "relation": "contains"},
                    {"code": "11140", "name": "중구", "relation": "intersects"},
                    "not-object",
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            response = await KorTravelGeoRestClient(http).regions_within_radius(
                lon=126.978,
                lat=37.5665,
                radius_km=3.0,
                levels=("sigungu",),
            )
            assert response.center.lon == 126.978
            assert response.center.lat == 37.5665
            assert [item.code for item in response.sigungu] == ["11110"]

    asyncio.run(_run())


@pytest.mark.parametrize(
    "payload",
    [
        {"radius_km": 3.0, "sigungu": []},
        {"center": {"lon": "bad", "lat": 37.5}, "radius_km": 3.0},
        {"center": {"lon": 126.9, "lat": 37.5}, "radius_km": 0},
    ],
)
def test_rest_client_regions_within_radius_invalid_response_raises(
    payload: dict[str, Any],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def _run() -> None:
        async with _mock_client(handler) as http:
            with pytest.raises(ValueError, match="kor-travel-geo regions response"):
                await KorTravelGeoRestClient(http).regions_within_radius(
                    lon=126.978,
                    lat=37.5665,
                )

    asyncio.run(_run())


def test_rest_client_regions_within_radius_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "maintenance"})

    async def _run() -> None:
        async with _mock_client(handler) as http:
            with pytest.raises(httpx.HTTPStatusError):
                await KorTravelGeoRestClient(http).regions_within_radius(
                    lon=126.978,
                    lat=37.5665,
                )

    asyncio.run(_run())


def test_resolve_sigungu_by_radius_requests_sigungu_only() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 3.0,
                "sigungu": [
                    {"code": "11110", "name": "종로구", "relation": "contains"},
                    {"code": "11140", "name": "중구", "relation": "overlaps"},
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            codes = await resolve_sigungu_by_radius(
                KorTravelGeoRestClient(http),
                lon=126.978,
                lat=37.5665,
                radius_km=3.0,
            )
            assert codes == ("11110", "11140")

    asyncio.run(_run())
    assert seen[0]["levels"] == ["sigungu"]


def test_resolve_regions_within_radius_passthrough() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 5.0,
                "sido": [
                    {"code": "11", "name": "서울특별시", "relation": "contains"}
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            response = await resolve_regions_within_radius(
                KorTravelGeoRestClient(http),
                lon=126.978,
                lat=37.5665,
                radius_km=5.0,
                levels=("sido",),
            )
            assert response.sido[0].code == "11"

    asyncio.run(_run())
    assert seen[0]["levels"] == ["sido"]


def test_kor_travel_geo_reverse_geocoder_max_distance_filters() -> None:
    """팩토리 인자 `max_distance_m`가 변환 함수에 그대로 전달돼 멀리 있는 결과 drop."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.66,
                        "match_kind": "parcel",
                        "address": {
                            "full": "멀리 떨어진 좌표",
                            "legal_dong_code": "1156010100",
                        },
                        "distance_m": 800.0,
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            # 100m 안쪽만 받아들임 — 800m 결과는 drop.
            reverse = kor_travel_geo_reverse_geocoder(client, max_distance_m=100.0)
            dropped = await reverse(
                Coordinate(lon=Decimal("127"), lat=Decimal("37"))
            )
            assert dropped is None
            # 1000m로 완화 — 받아들임.
            reverse_relaxed = kor_travel_geo_reverse_geocoder(
                client, max_distance_m=1000.0
            )
            addr = await reverse_relaxed(
                Coordinate(lon=Decimal("127"), lat=Decimal("37"))
            )
            assert addr is not None
            assert addr.bjd_code == "1156010100"

    asyncio.run(_run())


def test_kor_travel_geo_reverse_geocoder_region_fallback_when_reverse_not_found() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        seen.append((request.url.path, body))
        if request.url.path == "/v2/reverse":
            return httpx.Response(200, json={"status": "NOT_FOUND", "candidates": []})
        return httpx.Response(
            200,
            json={
                "center": {"lon": 126.4407, "lat": 37.4602},
                "radius_km": 0.1,
                "sido": [
                    {"code": "28", "name": "인천광역시", "relation": "contains"}
                ],
                "sigungu": [
                    {"code": "28110", "name": "중구", "relation": "contains"}
                ],
                "emd": [
                    {"code": "28110147", "name": "운서동", "relation": "contains"}
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            reverse = kor_travel_geo_reverse_geocoder(
                client,
                region_fallback_radius_km=0.1,
            )
            addr = await reverse(
                Coordinate(lon=Decimal("126.4407"), lat=Decimal("37.4602"))
            )
            assert addr is not None
            assert addr.bjd_code == "2811014700"
            assert addr.sigungu_code == "28110"
            assert addr.sido_code == "28"
            assert addr.legal == "인천광역시 중구 운서동"

    asyncio.run(_run())
    assert seen == [
        (
            "/v2/reverse",
            {
                "lon": 126.4407,
                "lat": 37.4602,
                "include_region": True,
                "include_zipcode": True,
            },
        ),
        (
            "/v2/regions/within-radius",
            {
                "lon": 126.4407,
                "lat": 37.4602,
                "radius_km": 0.1,
                "levels": ["sido", "sigungu", "emd"],
            },
        ),
    ]


def test_kor_travel_geo_reverse_geocoder_region_fallback_when_bjd_missing() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/v2/reverse":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "candidates": [
                        {
                            "confidence": 0.7,
                            "match_kind": "parcel",
                            "address": {"full": "공항"},
                            "region": {"sig_cd": "48240"},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "center": {"lon": 128.071747, "lat": 35.088591},
                "radius_km": 0.1,
                "sido": [{"code": "48", "name": "경상남도", "relation": "contains"}],
                "sigungu": [
                    {"code": "48240", "name": "사천시", "relation": "contains"}
                ],
                "emd": [
                    {"code": "48240250", "name": "사천읍", "relation": "contains"}
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            reverse = kor_travel_geo_reverse_geocoder(
                KorTravelGeoRestClient(http),
                region_fallback_radius_km=0.1,
            )
            addr = await reverse(
                Coordinate(lon=Decimal("128.071747"), lat=Decimal("35.088591"))
            )
            assert addr is not None
            assert addr.bjd_code == "4824025000"
            assert addr.sigungu_code == "48240"
            assert addr.legal == "경상남도 사천시 사천읍"

    asyncio.run(_run())
    assert seen == ["/v2/reverse", "/v2/regions/within-radius"]


def test_kor_travel_geo_address_geocoder_min_confidence_via_wrapper() -> None:
    """팩토리 인자 `min_confidence`가 변환 함수에 그대로 전달 — 신뢰도 낮은 결과 drop."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.3,
                        "match_kind": "road",
                        "point": {"lon": 127.0, "lat": 37.0},
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            strict = kor_travel_geo_address_geocoder(client, min_confidence=0.8)
            assert await strict(Address(road="아무 도로 1")) is None
            relaxed = kor_travel_geo_address_geocoder(client, min_confidence=0.1)
            coord = await relaxed(Address(road="아무 도로 1"))
            assert coord is not None
            assert coord.lon == Decimal("127.0")

    asyncio.run(_run())


def test_kor_travel_geo_address_geocoder_fallback_passed() -> None:
    """팩토리 인자 `fallback="api"`가 client.geocode JSON body `fallback`로 전달."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_body(request))
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [{"confidence": 1.0, "point": {"lon": 1, "lat": 1}}],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            geocode = kor_travel_geo_address_geocoder(client, fallback="api")
            await geocode(Address(road="아무 도로 1"))

    asyncio.run(_run())
    assert seen[0]["fallback"] == "api"


def test_kor_travel_geo_address_resolver_falls_back_to_parcel() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        seen.append(body)
        if "road_address" in body:
            return httpx.Response(200, json={"status": "OK", "candidates": []})
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 0.95,
                        "match_kind": "parcel",
                        "address": {
                            "full": "서울특별시 영등포구 여의도동 8",
                            "parcel_address": "서울특별시 영등포구 여의도동 8",
                            "legal_dong_code": "1156010100",
                        },
                        "region": {
                            "sig_cd": "11560",
                            "bjd_cd": "1156010100",
                            "sido": "서울특별시",
                            "sigungu": "영등포구",
                        },
                    }
                ],
            },
        )

    async def _run() -> None:
        async with _mock_client(handler) as http:
            client = KorTravelGeoRestClient(http)
            resolver = kor_travel_geo_address_resolver(client, fallback="api")
            resolved = await resolver(
                Address(
                    road="서울특별시 영등포구 여의공원로 120",
                    legal="서울특별시 영등포구 여의도동 8",
                )
            )
            assert resolved is not None
            assert resolved.bjd_code == "1156010100"

    asyncio.run(_run())
    assert "road_address" in seen[0]
    assert "jibun_address" in seen[1]


def test_cached_address_resolver_dedupes_by_display_address() -> None:
    calls = 0

    async def _resolver(address: Address) -> Address | None:
        nonlocal calls
        calls += 1
        return Address(road=address.road, bjd_code="1156010100")

    cached = cached_address_resolver(_resolver)

    async def _run() -> None:
        a1 = await cached(Address(road="서울특별시 영등포구 여의공원로 120"))
        a2 = await cached(Address(road="서울특별시 영등포구 여의공원로 120"))
        assert a1 is not None
        assert a1 is a2

    asyncio.run(_run())
    assert calls == 1


# -- cached_reverse_geocoder --------------------------------------------------


def test_cached_reverse_geocoder_dedupes_by_coord() -> None:
    calls: list[tuple[Decimal, Decimal]] = []

    async def _rg(coord: Coordinate) -> Address | None:
        calls.append((coord.lon, coord.lat))
        return Address(bjd_code="1156010100")

    cached = cached_reverse_geocoder(_rg)

    async def _run() -> None:
        c1 = Coordinate(lon=Decimal("127.0000001"), lat=Decimal("37.5000001"))
        c2 = Coordinate(lon=Decimal("127.0000002"), lat=Decimal("37.5000002"))
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
        first = await cached(c)
        second = await cached(c)  # None도 캐싱 — 재시도 안 함
        assert first is None
        assert second is None

    asyncio.run(_run())
    assert calls == 1
