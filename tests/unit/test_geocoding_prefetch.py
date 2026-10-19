"""``PrefetchingReverseGeocoder`` — run 수명 캐시 + bounded 동시성 선조회 (ADR-108)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from kortravelmap.dto import Address, Coordinate
from kortravelmap.geocoding import (
    ObservedReverseGeocoder,
    PrefetchingReverseGeocoder,
    cached_reverse_geocoder,
)


def _coord(i: int) -> Coordinate:
    return Coordinate(lon=Decimal("126.9") + Decimal(i) / 1000, lat=Decimal("37.5"))


class _SlowGeocoder:
    """동시에 몇 건이 떠 있는지 재는 대역."""

    def __init__(self, *, fail: set[int] | None = None) -> None:
        self.calls: list[Coordinate] = []
        self.in_flight = 0
        self.peak = 0
        self._fail = fail or set()

    async def __call__(self, coord: Coordinate) -> Address | None:
        self.calls.append(coord)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            index = int((coord.lon - Decimal("126.9")) * 1000)
            if index in self._fail:
                raise TimeoutError(f"geo timeout #{index}")
            return Address(bjd_code="1111010100")
        finally:
            self.in_flight -= 1


async def test_prefetch_dedupes_and_respects_the_concurrency_bound() -> None:
    upstream = _SlowGeocoder()
    geocoder = PrefetchingReverseGeocoder(upstream, concurrency=3)

    coords = [_coord(i % 10) for i in range(40)]  # 고유 좌표 10개가 4번씩
    sent = await geocoder.prefetch(coords)

    assert sent == 10
    assert len(upstream.calls) == 10
    assert upstream.peak <= 3, f"동시 요청이 상한을 넘었다: {upstream.peak}"
    assert upstream.peak > 1, "선조회가 순차로 돌았다 — 동시성이 실제로 쓰이지 않는다"

    # 선조회한 좌표는 변환이 다시 불러도 upstream으로 가지 않는다.
    for coord in coords:
        assert await geocoder(coord) == Address(bjd_code="1111010100")
    assert len(upstream.calls) == 10
    assert geocoder.live_calls == 10


async def test_second_prefetch_of_the_same_coordinates_sends_nothing() -> None:
    upstream = _SlowGeocoder()
    geocoder = PrefetchingReverseGeocoder(upstream, concurrency=2)

    await geocoder.prefetch([_coord(1), _coord(2)])
    assert await geocoder.prefetch([_coord(2), _coord(1)]) == 0
    assert len(upstream.calls) == 2


async def test_prefetch_failure_is_not_cached_and_the_live_retry_raises() -> None:
    """실패를 ``None``으로 캐시하면 bjd 없는 feature가 조용히 적재된다 — 그러면 안 된다."""
    upstream = _SlowGeocoder(fail={7})
    geocoder = PrefetchingReverseGeocoder(upstream, concurrency=2)

    await geocoder.prefetch([_coord(6), _coord(7)])
    assert geocoder.prefetch_failures == 1

    with pytest.raises(TimeoutError):
        await geocoder(_coord(7))
    # 실시간 재시도가 실제로 나갔다(선조회 1 + 재시도 1).
    assert [c for c in upstream.calls if c == _coord(7)] == [_coord(7), _coord(7)]


async def test_cache_is_bounded() -> None:
    upstream = _SlowGeocoder()
    geocoder = PrefetchingReverseGeocoder(upstream, concurrency=4, max_entries=5)

    await geocoder.prefetch([_coord(i) for i in range(8)])
    await geocoder(_coord(0))  # 가장 오래된 항목 — 이미 밀려나 다시 조회한다

    assert len(upstream.calls) == 9


async def test_it_is_an_observed_geocoder_so_the_converter_cache_uses_it() -> None:
    """변환 함수는 주입된 geocoder를 ``cached_reverse_geocoder``로 감싼다. 그 래퍼가
    ``observe``를 부르도록 Protocol을 만족해야 후보 시군구명 증거가 사라지지 않는다."""
    geocoder = PrefetchingReverseGeocoder(_SlowGeocoder(), concurrency=1)

    assert isinstance(geocoder, ObservedReverseGeocoder)
    wrapped = cached_reverse_geocoder(geocoder)
    assert await wrapped(_coord(3)) == Address(bjd_code="1111010100")


@pytest.mark.parametrize("bad", [{"concurrency": 0}, {"concurrency": 1, "max_entries": 0}])
def test_rejects_non_positive_bounds(bad: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        PrefetchingReverseGeocoder(_SlowGeocoder(), **bad)


async def test_probe_prefers_a_coordinate_that_resolved_in_this_run_and_resets_the_window() -> None:
    upstream = _SlowGeocoder()
    geocoder = PrefetchingReverseGeocoder(upstream, concurrency=2, recent_window=10)
    await geocoder.prefetch([_coord(1), _coord(2)])
    assert geocoder.recent_lookups == 2

    reference = Coordinate(lon=Decimal("127.5"), lat=Decimal("36.5"))
    assert await geocoder.probe_healthy(reference) is True
    # 고정 기준점과 이 run의 마지막 좋은 좌표를 **둘 다** 묻는다.
    assert upstream.calls[-2:] == [reference, geocoder.last_good_coord]
    assert geocoder.recent_lookups == 0
    assert (geocoder.probes, geocoder.probe_passes) == (1, 1)


async def test_probe_fails_if_either_the_reference_or_the_last_good_coordinate_is_empty() -> None:
    reference = Coordinate(lon=Decimal("127.5"), lat=Decimal("36.5"))

    async def _reference_only_empty(coord: Coordinate) -> Address | None:
        return None if coord == reference else Address(bjd_code="1111010100")

    geocoder = PrefetchingReverseGeocoder(_reference_only_empty, concurrency=1)
    await geocoder.prefetch([_coord(1)])
    assert geocoder.last_good_coord is not None

    assert await geocoder.probe_healthy(reference) is False
    assert (geocoder.probes, geocoder.probe_passes) == (1, 0)


async def test_probe_falls_back_to_the_reference_and_reports_empty() -> None:
    seen: list[Coordinate] = []

    async def _empty(coord: Coordinate) -> Address | None:
        seen.append(coord)
        return None

    geocoder = PrefetchingReverseGeocoder(_empty, concurrency=1)
    reference = Coordinate(lon=Decimal("127.5"), lat=Decimal("36.5"))

    assert await geocoder.probe_healthy(reference) is False
    assert seen == [reference]


async def test_typed_transport_failure_stops_pending_chunk_and_drains_inflight() -> None:
    from kortravelmap.core.exceptions import GeoRequestError

    calls = 0
    active = 0

    async def unavailable(_coord: Coordinate) -> Address | None:
        nonlocal calls, active
        calls += 1
        active += 1
        try:
            await asyncio.sleep(0)
            raise GeoRequestError("synthetic connection timeout")
        finally:
            active -= 1

    geocoder = PrefetchingReverseGeocoder(unavailable, concurrency=2)
    with pytest.raises(GeoRequestError, match="synthetic"):
        await geocoder.prefetch([_coord(i) for i in range(500)])
    assert calls <= 2
    assert active == 0
    assert geocoder.prefetch_failures >= 1


async def test_cancellation_drains_prefetch_tasks() -> None:
    active = 0
    entered = asyncio.Event()

    async def stalled(_coord: Coordinate) -> Address | None:
        nonlocal active
        active += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    geocoder = PrefetchingReverseGeocoder(stalled, concurrency=2)
    task = asyncio.create_task(geocoder.prefetch([_coord(i) for i in range(50)]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0


@pytest.mark.parametrize("failure", [400, 404, 429, 500, 503, "read_timeout"])
async def test_rest_errors_abort_prefetch_without_caching_missing_address(failure) -> None:
    import httpx
    from pydantic import SecretStr

    from kortravelmap.core.exceptions import GeoRequestError
    from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(failure, json={"detail": "synthetic unavailable"})

    async with httpx.AsyncClient(
        base_url="http://geo.test", transport=httpx.MockTransport(handler)
    ) as http:
        reverse = kor_travel_geo_reverse_geocoder(
            KorTravelGeoRestClient(http, api_key=SecretStr("synthetic-fixture-only"))
        )
        geocoder = PrefetchingReverseGeocoder(reverse, concurrency=2)
        with pytest.raises(GeoRequestError):
            await geocoder.prefetch([_coord(i) for i in range(500)])
        assert 1 <= calls <= 2


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, {"code": "E0100", "field": "key"}),
        (401, {"code": "E0401"}),
    ],
)
async def test_public_key_rejection_aborts_prefetch_without_retrying_every_row(
    status: int, error: dict[str, str]
) -> None:
    import httpx
    from pydantic import SecretStr

    from kortravelmap.core.exceptions import GeoAuthNotConfiguredError
    from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder

    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": error})

    async with httpx.AsyncClient(
        base_url="http://geo.test", transport=httpx.MockTransport(handler)
    ) as http:
        reverse = kor_travel_geo_reverse_geocoder(
            KorTravelGeoRestClient(http, api_key=SecretStr("synthetic-fixture-only"))
        )
        geocoder = PrefetchingReverseGeocoder(reverse, concurrency=2)
        with pytest.raises(GeoAuthNotConfiguredError):
            await geocoder.prefetch([_coord(i) for i in range(500)])
        assert 1 <= calls <= 2
        assert geocoder.prefetch_failures >= 1


async def test_http_not_found_response_is_a_normal_cacheable_result() -> None:
    import httpx
    from pydantic import SecretStr

    from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder

    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "NOT_FOUND", "candidates": []})

    async with httpx.AsyncClient(
        base_url="http://geo.test", transport=httpx.MockTransport(handler)
    ) as http:
        reverse = kor_travel_geo_reverse_geocoder(
            KorTravelGeoRestClient(http, api_key=SecretStr("synthetic-fixture-only"))
        )
        geocoder = PrefetchingReverseGeocoder(reverse, concurrency=2)
        assert await geocoder.prefetch([_coord(i) for i in range(5)]) == 5
        before = calls
        assert await geocoder(_coord(0)) is None
        assert calls == before
        assert geocoder.prefetch_failures == 0
