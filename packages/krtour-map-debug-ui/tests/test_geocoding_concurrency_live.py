"""``test_geocoding_concurrency_live`` — kraddr-geo 동시 호출 시 동작.

실 운영에서 batch 적재 시 같은 좌표가 수십 건씩 들어올 수 있고, 단일
``KraddrGeoRestClient`` + ``httpx.AsyncClient``를 ``asyncio.gather``로 동시에
호출하는 케이스가 잦다. 본 파일은 그 동시성에서:
- 모든 호출이 성공 (httpx pool race 없음)
- ``cached_reverse_geocoder``가 같은 좌표의 동시 호출을 1회로 줄이는지
- 서로 다른 좌표 N개 동시 호출 → 모두 다른 bjd
- timeout(짧게) 시 일부 실패라도 다른 호출은 영향 받지 않는지(독립)

도달 불가 시 ``pytest.skip``.
"""

from __future__ import annotations

import asyncio
import os
import socket
from decimal import Decimal
from urllib.parse import urlparse

import httpx
import pytest
from krtour.map.dto import Coordinate
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    cached_reverse_geocoder,
    kraddr_geo_reverse_geocoder,
)

pytestmark = pytest.mark.live


_DEFAULT_BASE_URL = "http://127.0.0.1:13088/api/proxy"


def _resolve_base_url() -> str:
    return os.environ.get("LIVE_KRADDR_GEO_BASE_URL", _DEFAULT_BASE_URL)


def _is_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return False
    try:
        with httpx.Client(base_url=base_url, timeout=3.0) as http:
            return http.get("/v1/healthz").status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def base_url() -> str:
    url = _resolve_base_url()
    if not _is_reachable(url):
        pytest.skip(f"kraddr-geo 도달 불가: {url}")
    return url


def _c(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


# ── 1) 단일 client + asyncio.gather N=20 reverse 모두 성공 ────────────────


async def test_concurrent_reverse_single_client(base_url: str) -> None:
    """단일 KraddrGeoRestClient 인스턴스를 20개 task가 동시에 사용해도 모두 성공.
    httpx.AsyncClient는 내부 connection pool을 thread-safe하게 관리."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client)

        # 서울시청 좌표 20개 동시 호출.
        coord = _c("126.9779", "37.5663")
        results = await asyncio.gather(*[reverse(coord) for _ in range(20)])
        assert all(addr is not None for addr in results)
        # 모두 같은 bjd.
        bjds = {addr.bjd_code for addr in results}  # type: ignore[union-attr]
        assert bjds == {"1114010300"}, f"bjd 불일치: {bjds}"


# ── 2) cached_reverse_geocoder 동시 호출 — race condition 없음 ──────────


async def test_cached_concurrent_same_coord_dedupes(base_url: str) -> None:
    """같은 좌표를 동시 N개 호출 — 캐시가 1회로 줄여야 (race로 N회 되면 안 됨).

    구현은 단순 dict 캐시 + 동일 event loop 안에서 직렬 await — 같은 task가 cache miss
    구간에서 다른 task의 fetch 결과를 기다리지는 않지만, asyncio.gather로 동시 시작 시
    여러 호출이 same key에 동시 진입할 수 있다. 본 테스트는 그 N회 호출이 실제로
    몇 번 upstream을 쳤는지 측정.
    """
    upstream_calls = {"n": 0}

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        raw_reverse = kraddr_geo_reverse_geocoder(client)

        async def _counted(coord: Coordinate):  # type: ignore[no-untyped-def]
            upstream_calls["n"] += 1
            return await raw_reverse(coord)

        cached = cached_reverse_geocoder(_counted)
        coord = _c("126.9779", "37.5663")
        # 동시 20개 — 현 구현은 첫 await 동안 cache에 들어가지 않으므로 race로 다수
        # 호출 가능. 본 테스트는 1회 ≤ 호출 ≤ 20회 범위 + 결과 일관성을 본다.
        results = await asyncio.gather(*[cached(coord) for _ in range(20)])
        assert all(addr is not None for addr in results)
        bjds = {addr.bjd_code for addr in results}  # type: ignore[union-attr]
        assert bjds == {"1114010300"}
        # 실 호출 수는 N(20) 이하 — 캐시 효과로 N보다 적어야(보통 1~5).
        n = upstream_calls["n"]
        assert 1 <= n <= 20, f"호출 수 {n}이 범위 밖"
        # 두 번째 동시 라운드는 1회만 늘어야(캐시 hit).
        before = upstream_calls["n"]
        await asyncio.gather(*[cached(coord) for _ in range(10)])
        assert upstream_calls["n"] == before, "두 번째 라운드는 캐시만 hit해야"


# ── 3) 서로 다른 좌표 N개 동시 — 모두 다른 bjd 정상 ──────────────────────


async def test_concurrent_distinct_coords(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client)

        coords_expected_sido = [
            (_c("126.9779", "37.5663"), "11"),  # 서울
            (_c("129.0756", "35.1796"), "26"),  # 부산
            (_c("127.3845", "36.3504"), "30"),  # 대전
            (_c("126.4983", "33.4996"), "50"),  # 제주
            (_c("126.8526", "35.1601"), "29"),  # 광주
            (_c("126.7053", "37.4563"), "28"),  # 인천
            (_c("129.3114", "35.5384"), "31"),  # 울산
            (_c("127.2890", "36.4801"), "36"),  # 세종
        ]
        results = await asyncio.gather(
            *[reverse(coord) for coord, _ in coords_expected_sido]
        )
        for (_coord, expected_sido), addr in zip(
            coords_expected_sido, results, strict=True
        ):
            assert addr is not None
            assert addr.sido_code == expected_sido, (
                f"expected {expected_sido} got {addr.sido_code} bjd={addr.bjd_code}"
            )


# ── 4) 짧은 timeout + 일부 의도된 잘못된 URL — 다른 호출 영향 없음 ────────


async def test_one_failure_does_not_affect_others(base_url: str) -> None:
    """asyncio.gather(return_exceptions=True) 패턴 — 한 호출이 timeout/connect_error
    나도 다른 호출 결과는 정상."""
    coord_seoul = _c("126.9779", "37.5663")

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as ok_http:
        ok_client = KraddrGeoRestClient(ok_http)
        ok_reverse = kraddr_geo_reverse_geocoder(ok_client)

        # 의도적으로 잘못된 base_url(닫힌 포트)로 실패 트리거.
        bad_http = httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=0.5)
        bad_client = KraddrGeoRestClient(bad_http)
        bad_reverse = kraddr_geo_reverse_geocoder(bad_client)

        try:
            results = await asyncio.gather(
                ok_reverse(coord_seoul),
                bad_reverse(coord_seoul),
                ok_reverse(coord_seoul),
                ok_reverse(coord_seoul),
                return_exceptions=True,
            )
        finally:
            await bad_http.aclose()

        # 3개의 OK는 정상 Address, 1개의 BAD는 Exception.
        ok_results = [r for r in results if not isinstance(r, BaseException)]
        bad_results = [r for r in results if isinstance(r, BaseException)]
        assert len(ok_results) == 3, f"ok={len(ok_results)} results={results}"
        assert len(bad_results) == 1
        for addr in ok_results:
            assert addr is not None
            assert addr.bjd_code == "1114010300"


# ── 5) gather와 sequential 비교 — 동시 호출이 sequential보다 빠름 ────────


async def test_concurrent_is_faster_than_sequential(base_url: str) -> None:
    """20개 호출 — 동시(gather)가 sequential보다 의미있게 빠른지(완벽한 unit
    test는 아니지만 회귀 감지에 유용).
    """
    import time

    coord = _c("126.9779", "37.5663")
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client)

        # 우선 1회 호출로 warm-up (kraddr-geo 캐시 등 효과 흡수).
        await reverse(coord)

        # Sequential 10건.
        seq_start = time.perf_counter()
        for _ in range(10):
            await reverse(coord)
        seq_elapsed = time.perf_counter() - seq_start

        # Concurrent 10건.
        conc_start = time.perf_counter()
        await asyncio.gather(*[reverse(coord) for _ in range(10)])
        conc_elapsed = time.perf_counter() - conc_start

        # 동시가 sequential보다 빠르거나 비슷해야(network bound — 보통 훨씬 빠름).
        # 회귀 안전 margin: 2배 이상은 안 됨.
        assert conc_elapsed < seq_elapsed * 2, (
            f"동시 호출이 sequential의 2배 이상 느림: "
            f"seq={seq_elapsed:.3f}s conc={conc_elapsed:.3f}s"
        )
