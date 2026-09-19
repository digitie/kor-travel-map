"""geo 경계 왕복을 **endpoint별로** 센다.

왜 이 계수가 필요한가. dagster의 reverse geocoder는 `region_fallback_radius_km=0.1`로
결선돼 있어서, 첫 `/v2/reverse`가 법정동코드를 못 채우면 같은 좌표로
`/v2/regions/within-radius`를 한 번 더 친다. 즉 행 하나가 왕복 1회일 수도 2회일 수도
있는데 **그 비율이 오늘 어디에도 없다.** 2026-09-19에 산악 등산로 적재가 3시간 넘게
이벤트 없이 돌았고, 산악 centroid는 fallback이 거의 전량에 걸릴 것으로 *추정*될 뿐
측정된 적이 없다. 추정 위에 동시성·재시도 수치를 얹으면 분모가 틀린 채로 정확한
분자를 계산하게 된다.

**계수는 파생값에 맞추지 않는다.** `len(coords)`나 "호출했으니 1" 같은 값에 맞추면
분자와 분모가 같은 출처라 항진명제다. 여기서는 **가짜 transport가 실제로 받은
요청**을 세어 그것과 대조한다.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.core.exceptions import GeoRequestError
from kortravelmap.dto import Coordinate
from kortravelmap.geocoding import (
    GeoCallStats,
    KorTravelGeoRestClient,
    kor_travel_geo_reverse_geocoder,
)

pytestmark = pytest.mark.unit

_API_KEY = SecretStr("test-key")

#: 좌표가 도로명주소 후보를 못 내는 응답 — bjd_code가 없어 region fallback이 걸린다.
_REVERSE_WITHOUT_BJD: dict[str, Any] = {"candidates": []}

#: fallback이 시군구를 채워 주는 응답.
_REGIONS: dict[str, Any] = {
    "center": {"lon": 127.0, "lat": 37.0},
    "radius_km": 0.1,
    "items": [
        {
            "level": "sigungu",
            "code": "11110",
            "name": "종로구",
            "relation": "covers",
            "distance_m": 0.0,
        }
    ],
}

#: 첫 왕복에서 법정동코드가 나오는 응답 — fallback이 걸리지 않는다.
#:
#: 필드 이름은 `tests/unit/test_geocoding.py`의 구조 Protocol 대역과 맞춘다
#: (`sig_cd`/`sido`/`sigungu`/`postal_code` — v2 wire 이름이 직관과 다르다).
_REVERSE_WITH_BJD: dict[str, Any] = {
    "status": "OK",
    "candidates": [
        {
            "point": {"lon": 127.0, "lat": 37.0},
            "distance_m": 1.0,
            "confidence": 0.9,
            "match_kind": "exact",
            "address": {
                "full": "서울특별시 영등포구 여의공원로 120",
                "road_address": "서울특별시 영등포구 여의공원로 120",
                "postal_code": "07237",
                "legal_dong_code": "1156010100",
                "admin_dong_code": "1156051000",
            },
            "region": {
                "sig_cd": "11560",
                "bjd_cd": "1156010100",
                "sido": "서울특별시",
                "sigungu": "영등포구",
            },
        }
    ],
}


class _RecordingTransport(httpx.AsyncBaseTransport):
    """**실제로 받은 요청**을 기록한다. 이 기록이 계수의 대조군이다."""

    def __init__(
        self,
        reverse_payload: dict[str, Any],
        *,
        fail_paths: set[str] | None = None,
    ) -> None:
        self.seen: list[str] = []
        self._reverse_payload = reverse_payload
        self._fail_paths = fail_paths or set()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.seen.append(path)
        if path in self._fail_paths:
            raise httpx.ReadTimeout("요청이 응답을 받지 못했다", request=request)
        if path.endswith("/regions/within-radius"):
            return httpx.Response(200, json=_REGIONS, request=request)
        return httpx.Response(200, json=self._reverse_payload, request=request)

    def received(self, suffix: str) -> int:
        return sum(1 for path in self.seen if path.endswith(suffix))


def _client(transport: _RecordingTransport, stats: GeoCallStats) -> tuple[Any, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url="http://geo.test", transport=transport)
    client = KorTravelGeoRestClient(http, api_key=_API_KEY, stats=stats)
    return client, http


async def test_counts_match_what_the_transport_actually_received() -> None:
    """계수 = 가짜 transport가 **실제로 받은** 요청 수."""

    transport = _RecordingTransport(_REVERSE_WITHOUT_BJD)
    stats = GeoCallStats()
    client, http = _client(transport, stats)
    geocoder = kor_travel_geo_reverse_geocoder(client, region_fallback_radius_km=0.1)
    try:
        for index in range(4):
            await geocoder(Coordinate(lon=127.0 + index * 0.01, lat=37.0))
    finally:
        await http.aclose()

    assert stats.calls["reverse"] == transport.received("/v2/reverse")
    assert stats.calls["regions_within_radius"] == transport.received(
        "/v2/regions/within-radius"
    )
    assert stats.total_calls == len(transport.seen)


async def test_the_two_endpoints_are_counted_apart() -> None:
    """**합계만 세면 아무것도 답하지 못한다.** 두 축이 실제로 갈려야 한다.

    같은 호출 수라도 fallback이 걸리는 좌표와 아닌 좌표는 왕복 수가 2배 다르다.
    """

    with_fallback = _RecordingTransport(_REVERSE_WITHOUT_BJD)
    without_fallback = _RecordingTransport(_REVERSE_WITH_BJD)
    counts: list[GeoCallStats] = []
    for transport in (with_fallback, without_fallback):
        stats = GeoCallStats()
        client, http = _client(transport, stats)
        geocoder = kor_travel_geo_reverse_geocoder(
            client, region_fallback_radius_km=0.1
        )
        try:
            for index in range(3):
                await geocoder(Coordinate(lon=127.0 + index * 0.01, lat=37.0))
        finally:
            await http.aclose()
        counts.append(stats)

    fallback_stats, direct_stats = counts
    assert fallback_stats.calls["reverse"] == 3
    assert fallback_stats.calls["regions_within_radius"] == 3, (
        "bjd가 없는 응답인데 region fallback이 걸리지 않았다 — 이 검사의 전제가 깨졌다."
    )
    assert direct_stats.calls["reverse"] == 3
    assert direct_stats.calls["regions_within_radius"] == 0, (
        "bjd가 있는데도 fallback이 걸렸다 — 그러면 왕복 수를 가르는 의미가 없다."
    )
    assert fallback_stats.total_calls == 2 * direct_stats.total_calls


async def test_a_failed_round_trip_is_still_a_round_trip() -> None:
    """실패한 왕복도 센다 — **실패한 run이 그 수가 가장 필요한 run이다.**"""

    transport = _RecordingTransport(
        _REVERSE_WITHOUT_BJD, fail_paths={"/v2/reverse"}
    )
    stats = GeoCallStats()
    client, http = _client(transport, stats)
    try:
        with pytest.raises(GeoRequestError):
            await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()

    assert stats.calls["reverse"] == 1, "실패한 왕복이 시도 수에서 빠졌다."
    assert stats.failures["reverse"] == 1
    assert "실패" in stats.summary()


async def test_stats_are_opt_in_and_change_nothing_by_default() -> None:
    """주입하지 않으면 **현행 동작과 같다** — 호출자 여덟 곳이 우연히 달라지지 않는다."""

    transport = _RecordingTransport(_REVERSE_WITH_BJD)
    http = httpx.AsyncClient(base_url="http://geo.test", transport=transport)
    client = KorTravelGeoRestClient(http, api_key=_API_KEY)
    try:
        address = await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()
    assert address is not None
    assert transport.received("/v2/reverse") == 1
    # 계수를 주입하지 않았으므로 클라이언트는 아무것도 기록하지 않는다.
    assert getattr(client, "_stats", "missing") is None


def test_summary_says_zero_rather_than_staying_silent() -> None:
    """0건과 침묵은 다르다 — 로그가 비면 "안 돌았다"와 구별되지 않는다."""

    assert "0건" in GeoCallStats().summary()
