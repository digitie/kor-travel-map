"""``test_geocoding`` — kraddr-geo v2 함수 연동 (krtour.map.geocoding).

kraddr-geo를 import하지 않고, v2 응답 shape를 만족하는 fake dataclass로 순수 변환
함수 + 비동기 콜러블 팩토리를 검증한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from krtour.map.dto import Address, Coordinate
from krtour.map.geocoding import (
    geocode_v2_to_coordinate,
    kraddr_geo_address_geocoder,
    kraddr_geo_reverse_geocoder,
    reverse_v2_to_address,
)

# -- kraddr-geo v2 응답 fake (structural) -------------------------------------


@dataclass(frozen=True)
class _Point:
    x: float
    y: float


@dataclass(frozen=True)
class _Region:
    sig_cd: str | None = None
    bjd_cd: str | None = None
    sido: str | None = None
    sigungu: str | None = None
    eup_myeon_dong: str | None = None
    legal_dong: str | None = None
    admin_dong: str | None = None


@dataclass(frozen=True)
class _AddressV2:
    full: str = ""
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    legal_dong_code: str | None = None
    admin_dong_code: str | None = None
    road_name: str | None = None
    road_name_code: str | None = None


@dataclass(frozen=True)
class _Candidate:
    confidence: float = 1.0
    address: _AddressV2 | None = None
    point: _Point | None = None
    region: _Region | None = None


@dataclass(frozen=True)
class _Response:
    status: str = "OK"
    candidates: tuple[_Candidate, ...] = field(default_factory=tuple)


# -- reverse_v2_to_address ----------------------------------------------------


def test_reverse_full_mapping() -> None:
    resp = _Response(
        candidates=(
            _Candidate(
                confidence=0.95,
                region=_Region(
                    sig_cd="11560",
                    bjd_cd="1156010100",
                    sido="서울특별시",
                    sigungu="영등포구",
                    admin_dong="여의동",
                ),
                address=_AddressV2(
                    road_address="서울특별시 영등포구 여의공원로 120",
                    parcel_address="서울특별시 영등포구 여의도동 8",
                    postal_code="07237",
                    admin_dong_code="1156051000",
                    road_name_code="116804166041",
                ),
            ),
        ),
    )
    addr = reverse_v2_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1156010100"
    assert addr.sigungu_code == "11560"
    assert addr.sido_code == "11"
    assert addr.admin_dong_code == "1156051000"
    assert addr.road == "서울특별시 영등포구 여의공원로 120"
    assert addr.legal == "서울특별시 영등포구 여의도동 8"
    assert addr.admin == "여의동"
    assert addr.zipcode == "07237"
    assert addr.road_name_code == "116804166041"
    assert addr.sido_name == "서울특별시"
    assert addr.sigungu_name == "영등포구"


def test_reverse_derives_codes_from_bjd() -> None:
    # region.sig_cd 없어도 bjd_code에서 sigungu/sido 파생.
    resp = _Response(
        candidates=(_Candidate(region=_Region(bjd_cd="4117310200")),),
    )
    addr = reverse_v2_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "4117310200"
    assert addr.sigungu_code == "41173"
    assert addr.sido_code == "41"


def test_reverse_falls_back_to_address_legal_dong_code() -> None:
    resp = _Response(
        candidates=(
            _Candidate(
                region=_Region(),  # bjd_cd None
                address=_AddressV2(legal_dong_code="1156010100"),
            ),
        ),
    )
    addr = reverse_v2_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1156010100"


def test_reverse_picks_highest_confidence() -> None:
    resp = _Response(
        candidates=(
            _Candidate(confidence=0.3, region=_Region(bjd_cd="1111010100")),
            _Candidate(confidence=0.9, region=_Region(bjd_cd="1156010100")),
        ),
    )
    addr = reverse_v2_to_address(resp)
    assert addr is not None
    assert addr.bjd_code == "1156010100"


def test_reverse_min_confidence_filters_out() -> None:
    resp = _Response(candidates=(_Candidate(confidence=0.4),))
    assert reverse_v2_to_address(resp, min_confidence=0.8) is None


def test_reverse_non_ok_status_is_none() -> None:
    resp = _Response(status="NOT_FOUND", candidates=(_Candidate(),))
    assert reverse_v2_to_address(resp) is None


def test_reverse_no_candidates_is_none() -> None:
    assert reverse_v2_to_address(_Response()) is None


def test_reverse_invalid_codes_dropped_not_raised() -> None:
    # 자릿수 안 맞는 코드/우편번호는 ValidationError 없이 None 처리.
    resp = _Response(
        candidates=(
            _Candidate(
                region=_Region(sig_cd="123", bjd_cd="짧음"),
                address=_AddressV2(postal_code="123", admin_dong_code="999"),
            ),
        ),
    )
    addr = reverse_v2_to_address(resp)
    assert addr is not None
    assert addr.bjd_code is None
    assert addr.sigungu_code is None
    assert addr.sido_code is None
    assert addr.zipcode is None
    assert addr.admin_dong_code is None


# -- geocode_v2_to_coordinate -------------------------------------------------


def test_geocode_point_to_coordinate() -> None:
    resp = _Response(candidates=(_Candidate(point=_Point(x=127.05, y=37.55)),))
    coord = geocode_v2_to_coordinate(resp)
    assert coord is not None
    assert coord.lon == Decimal("127.05")
    assert coord.lat == Decimal("37.55")


def test_geocode_skips_candidate_without_point() -> None:
    resp = _Response(
        candidates=(
            _Candidate(confidence=0.99, point=None),  # 최고 confidence지만 point 없음
            _Candidate(confidence=0.5, point=_Point(x=127.0, y=37.0)),
        ),
    )
    coord = geocode_v2_to_coordinate(resp)
    assert coord is not None
    assert coord.lon == Decimal("127.0")


def test_geocode_non_ok_is_none() -> None:
    resp = _Response(status="ERROR", candidates=(_Candidate(point=_Point(1.0, 2.0)),))
    assert geocode_v2_to_coordinate(resp) is None


def test_geocode_no_point_candidate_is_none() -> None:
    resp = _Response(candidates=(_Candidate(point=None),))
    assert geocode_v2_to_coordinate(resp) is None


# -- 비동기 콜러블 팩토리 -----------------------------------------------------


class _FakeClient:
    """kraddr-geo AsyncAddressClient의 v2 메서드 fake."""

    def __init__(self, *, reverse: _Response, geocode: _Response) -> None:
        self._reverse = reverse
        self._geocode = geocode
        self.reverse_calls: list[tuple[float, float, int | None]] = []
        self.geocode_calls: list[dict[str, str | None]] = []

    async def reverse_v2(
        self, lon: float, lat: float, *, radius_m: int | None = None
    ) -> _Response:
        self.reverse_calls.append((lon, lat, radius_m))
        return self._reverse

    async def geocode_v2(
        self,
        *,
        road_address: str | None = None,
        jibun_address: str | None = None,
        sig_cd: str | None = None,
        bjd_cd: str | None = None,
        limit: int = 10,
    ) -> _Response:
        self.geocode_calls.append(
            {
                "road_address": road_address,
                "jibun_address": jibun_address,
                "sig_cd": sig_cd,
                "bjd_cd": bjd_cd,
            }
        )
        return self._geocode


def test_reverse_geocoder_factory() -> None:
    client = _FakeClient(
        reverse=_Response(candidates=(_Candidate(region=_Region(bjd_cd="1156010100")),)),
        geocode=_Response(),
    )
    reverse = kraddr_geo_reverse_geocoder(client, radius_m=50)
    coord = Coordinate(lon=Decimal("127.05"), lat=Decimal("37.55"))
    addr = asyncio.run(reverse(coord))
    assert addr is not None
    assert addr.bjd_code == "1156010100"
    # client에 lon/lat/radius가 전달됐는지.
    assert client.reverse_calls == [(127.05, 37.55, 50)]


def test_address_geocoder_factory() -> None:
    client = _FakeClient(
        reverse=_Response(),
        geocode=_Response(candidates=(_Candidate(point=_Point(x=127.1, y=37.4)),)),
    )
    geocode = kraddr_geo_address_geocoder(client)
    address = Address(
        road="서울특별시 영등포구 여의공원로 120",
        legal="서울특별시 영등포구 여의도동 8",
        sigungu_code="11560",
        bjd_code="1156010100",
    )
    coord = asyncio.run(geocode(address))
    assert coord is not None
    assert coord.lon == Decimal("127.1")
    assert coord.lat == Decimal("37.4")
    # Address.road/legal/코드가 kraddr-geo geocode_v2 인자로 매핑됐는지.
    assert client.geocode_calls == [
        {
            "road_address": "서울특별시 영등포구 여의공원로 120",
            "jibun_address": "서울특별시 영등포구 여의도동 8",
            "sig_cd": "11560",
            "bjd_cd": "1156010100",
        }
    ]


def test_geocoder_returns_none_on_empty_response() -> None:
    client = _FakeClient(reverse=_Response(), geocode=_Response())
    reverse = kraddr_geo_reverse_geocoder(client)
    geocode = kraddr_geo_address_geocoder(client)
    assert asyncio.run(reverse(Coordinate(lon=Decimal("127"), lat=Decimal("37")))) is None
    assert asyncio.run(geocode(Address())) is None


@pytest.mark.parametrize("bad_status", ["NOT_FOUND", "ERROR"])
def test_reverse_to_address_handles_all_non_ok(bad_status: str) -> None:
    resp = _Response(status=bad_status, candidates=(_Candidate(),))
    assert reverse_v2_to_address(resp) is None
