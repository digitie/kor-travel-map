"""ADR-114 2단계 weather 상태 적재 job(Valkey 없이).

정의(STOPPED·tag)·fetcher(cursor·snapshot·410·인증·계수)·실패 분류를 본다. 실제 Valkey 왕복은
``tests/integration/test_valkey_weather_state.py``가 본다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from dagster import DefaultScheduleStatus, Failure
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateItem,
    StateStoreUnavailable,
    StateSwapRefused,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_weather import (
    ADMIN_TOKEN_HEADER,
    WeatherExportContractError,
    WeatherExportFailure,
    WeatherExportMissing,
    WeatherExportNotReady,
    WeatherExportSnapshotExpired,
    WeatherExportUnauthorized,
)
from kortravelmap.providers.kor_travel_weather_state import DATASET_FORECAST_SHORT
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.weather_state as weather_state
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.upstream_requests import (
    counting_upstream_requests,
    observed_upstream_requests,
)
from kortravelmap.dagster.upstream_signal import raise_if_stale
from kortravelmap.dagster.weather_state import (
    WEATHER_EXPORT_LEASE,
    WEATHER_STATE_SPECS,
    WeatherExportNotConfigured,
    WeatherStateJobSpec,
    fetch_weather_current,
    fetch_weather_daily_summaries,
    fetch_weather_forecasts,
    fetch_weather_locations,
    load_weather_state,
    weather_lock_ttl_seconds,
)

TOKEN = "w" * 40
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)


def _settings(**overrides: Any) -> KorTravelMapSettings:
    values: dict[str, Any] = {
        "kor_travel_weather_base_url": "http://127.0.0.1:14201/",
        "kor_travel_weather_service_token": SecretStr(TOKEN),
        "kor_travel_weather_page_size": 2,
    }
    values.update(overrides)
    return KorTravelMapSettings(**values)


@pytest.fixture(autouse=True)
def page_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """HTTP 층 재시도 간격을 0으로, 503 페이지 재시도 대기는 기록만 한다(기록을 돌려준다)."""
    monkeypatch.setattr(weather_state, "_WEATHER_RETRY_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(weather_state, "_jitter", lambda delay: delay)  # 간격 흔들기 끄기
    slept: list[float] = []

    async def _record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(weather_state, "_page_retry_sleep", _record)
    return slept


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(weather_state.httpx, "AsyncClient", factory)
    return seen


def _meta(count: int, **overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "generated_at": NOW.isoformat(),
        "source_collected_at": (NOW - timedelta(minutes=5)).isoformat(),
        "source_status": "ok",
        "item_count": count,
        "snapshot_id": "snap-1",
        "next_cursor": None,
        "has_more": False,
    }
    meta.update(overrides)
    return meta


def _location(location_id: str) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "name": f"위치 {location_id}",
        "latitude": 37.5,
        "longitude": 127.0,
        "legal_dong_code": None,
        "sido_name": None,
        "sigungu_name": None,
    }


# -- 정의 --------------------------------------------------------------------------------


def test_every_dataset_has_a_stopped_schedule_and_no_operation_key() -> None:
    assert len(WEATHER_STATE_SPECS) == 7
    assert len({spec.dataset.name for spec in WEATHER_STATE_SPECS}) == 7
    for spec in WEATHER_STATE_SPECS:
        job = defs.resolve_job_def(spec.job_name)
        schedule = defs.resolve_schedule_def(spec.schedule_name)
        assert schedule.default_status == DefaultScheduleStatus.STOPPED, spec.schedule_name
        assert schedule.job_name == spec.job_name
        assert "kor_travel_map.operation_key" not in job.tags
        assert job.tags["kor_travel_map.job_kind"] == "weather_state"
        assert int(job.tags["dagster/max_runtime"]) == spec.max_runtime_seconds
        # retry policy가 있으면 Dagster가 run 상한 초과 취소에도 재시도를 요청한다(14일 100회).
        (node,) = job.nodes
        assert node.definition.retry_policy is None, spec.job_name


def test_current_ceiling_is_a_temporary_600_and_leaves_room_to_read() -> None:
    # 600초는 weather export 수정 전까지의 임시 상한(480초에서)이다 — 그 뒤 되돌린다. 더 긴 tick은
    # 순회 deadline이 건너뛴다. 읽기 자리를 기다릴 여유(상한 − 꼬리 − 읽기 예산)는 남아 있어야 한다.
    from kortravelmap.providers.kor_travel_weather_state import DATASET_CURRENT

    spec = next(spec for spec in WEATHER_STATE_SPECS if spec.dataset is DATASET_CURRENT)
    assert spec.cron_schedule == "25,40 * * * *"
    assert spec.max_runtime_seconds == 600
    for each in WEATHER_STATE_SPECS:
        assert 0 < each.read_budget_seconds < each.max_runtime_seconds - 60, each.job_name


def test_weather_alert_thresholds_sit_below_the_read_side_max_age() -> None:
    # 소유자 결정(2026-11-24 "나이 기준 혼합"): run 결과는 경고 임계로, 읽기 계약 max_age는 그대로.
    expected = {
        "weather.locations": timedelta(days=2),
        "weather.current": timedelta(hours=2),
        "weather.forecast_ultra_short": timedelta(hours=2),
        "weather.forecast_short": timedelta(hours=8),
        "weather.forecast_mid": timedelta(hours=20),
        "weather.forecast_external": timedelta(hours=8),
        "weather.daily_summaries": timedelta(hours=4),
    }
    assert {spec.dataset.name: spec.stale_alert_after for spec in WEATHER_STATE_SPECS} == expected
    for spec in WEATHER_STATE_SPECS:
        assert spec.stale_alert_after < spec.dataset.max_age, spec.job_name


def _fire_minutes(cron: str) -> set[int]:
    minute = cron.split()[0]
    return {int(value) for value in minute.split(",")}


def test_weather_schedules_do_not_fire_on_the_same_minutes_as_current() -> None:
    # 2026-11-23: current 상한 초과 97건 중 79건이 W5(:41)와 겹친 :40 회차였고, 11-23 21:40에는
    # current·mid·W5가 함께 돌다 셋 다 읽기 경합 503으로 끝났다. current(:25·:40)가 도는 동안
    # (p95 약 6분) 다른 weather 상태 job이 발화하지 않는다.
    by_name = {spec.dataset.name: spec for spec in WEATHER_STATE_SPECS}
    current = _fire_minutes(by_name["weather.current"].cron_schedule)
    busy = {(start + offset) % 60 for start in current for offset in range(7)}
    for spec in WEATHER_STATE_SPECS:
        if spec.dataset.name == "weather.current":
            continue
        clash = _fire_minutes(spec.cron_schedule) & busy
        assert not clash, (spec.job_name, sorted(clash))


def test_lock_ttl_follows_the_run_ceiling() -> None:
    for spec in WEATHER_STATE_SPECS:
        assert weather_lock_ttl_seconds(spec) == spec.max_runtime_seconds + 660


def test_daily_summaries_lock_expires_before_its_next_hourly_tick() -> None:
    # W5 상한을 2,700초로 올렸다. lock TTL(상한 + 취소 유예)이 매시 발화 간격 안이어야
    # 멈춘 run의 lock이 다음 tick을 막지 않는다.
    from kortravelmap.providers.kor_travel_weather_state import DATASET_DAILY_SUMMARIES

    spec = next(spec for spec in WEATHER_STATE_SPECS if spec.dataset is DATASET_DAILY_SUMMARIES)
    assert spec.cron_schedule == "5 * * * *"
    assert weather_lock_ttl_seconds(spec) < 3_600


def test_short_forecast_guard_accepts_measured_live_cycles() -> None:
    # 2026-11-02 운영 실측: 단기예보 한 회차는 완결 추정 약 375곳, 공개 도중 273곳이었다. 포화된
    # odroid에서는 격자 1/3이 빠진 약 250곳 회차도 나온다. 그날 하한 1,000은 "53건 < 1000"으로
    # 모두 거부했다. 깨진 집합(53곳)은 계속 거부한다.
    from kortravelmap.infra.valkey_state import evaluate_shrink_guard

    guard = DATASET_FORECAST_SHORT.guard
    assert evaluate_shrink_guard([], 273, guard) is None
    assert evaluate_shrink_guard([375], 273, guard) is None
    assert evaluate_shrink_guard([375, 340], 250, guard) is None
    assert evaluate_shrink_guard([], 53, guard) is not None
    assert evaluate_shrink_guard([375], 120, guard) is not None


def test_mid_forecast_floor_fits_the_configured_mid_targets() -> None:
    # 중기예보는 weather의 중기 지역 코드 target(운영 21곳: 서울…서귀포)에만 있다. 하한 300곳이면
    # 완결된 집합도 "21건 < 300"으로 영영 거부된다(2026-11-02 운영).
    from kortravelmap.providers.kor_travel_weather_state import DATASET_FORECAST_MID

    assert 0 < DATASET_FORECAST_MID.guard.min_count <= 21


# -- fetcher -----------------------------------------------------------------------------


async def test_locations_follow_the_cursor_with_the_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        None: {
            "items": [_location("a"), _location("b")],
            "meta": _meta(2, has_more=True, next_cursor="c2"),
        },
        "c2": {
            "items": [_location("c")],
            "meta": _meta(1, source_collected_at=None, source_status="stale"),
        },
    }
    seen = _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with counting_upstream_requests():
        fetch = await fetch_weather_locations(_settings())
        counted = observed_upstream_requests()
    assert [row.location_id for row in fetch.rows] == ["a", "b", "c"]
    assert [request.url.path for request in seen] == ["/v1/service/exports/locations"] * 2
    assert all(request.headers[ADMIN_TOKEN_HEADER] == TOKEN for request in seen)
    assert seen[0].url.params["limit"] == "2"
    assert "cursor" not in seen[0].url.params
    assert counted == 2
    # 한 페이지라도 null이면 집계도 null, 상태는 가장 나쁜 값(ADR-114 W4).
    assert fetch.source_collected_at is None
    assert fetch.source_status == "stale"
    assert fetch.pages == 2
    assert fetch.snapshot_id == "snap-1"


async def test_forecast_and_daily_requests_carry_their_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(200, json={
        "items": [], "meta": _meta(0),
    }))
    await fetch_weather_forecasts(_settings(), "mid")
    await fetch_weather_daily_summaries(_settings(weather_daily_summary_days=9))
    await fetch_weather_current(_settings())
    assert seen[0].url.path == "/v1/service/exports/forecasts"
    assert seen[0].url.params["style"] == "mid"
    assert "since" not in seen[0].url.params  # 증분 없이 전량(W3)
    assert seen[1].url.path == "/v1/service/exports/daily-summaries"
    assert seen[1].url.params["days"] == "9"
    assert seen[2].url.path == "/v1/service/exports/current"


async def test_snapshot_change_between_pages_is_a_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        None: {"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")},
        "c2": {"items": [_location("b")], "meta": _meta(1, snapshot_id="snap-2")},
    }
    _install(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages[request.url.params.get("cursor")]),
    )
    with pytest.raises(WeatherExportContractError, match="snapshot_id"):
        await fetch_weather_locations(_settings())


async def test_cycling_cursor_is_a_contract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        lambda _request: httpx.Response(
            200, json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="x")}
        ),
    )
    with pytest.raises(WeatherExportContractError, match="순환"):
        await fetch_weather_locations(_settings())


async def test_expired_snapshot_restarts_from_the_first_page_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor == "c2" and calls.count("c2") == 1:
            return httpx.Response(410, json={})
        if cursor is None:
            return httpx.Response(
                200,
                json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")},
            )
        return httpx.Response(200, json={"items": [_location("b")], "meta": _meta(1)})

    _install(monkeypatch, handler)
    with counting_upstream_requests():
        fetch = await fetch_weather_locations(_settings())
        counted = observed_upstream_requests()
    assert calls == [None, "c2", None, "c2"]
    assert [row.location_id for row in fetch.rows] == ["a", "b"]  # 첫 시도의 행이 섞이지 않는다
    assert counted == 4


async def test_expired_snapshot_twice_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(410, json={})
        return httpx.Response(
            200, json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")}
        )

    _install(monkeypatch, handler)
    with pytest.raises(WeatherExportSnapshotExpired) as excinfo:
        await fetch_weather_locations(_settings())
    assert excinfo.value.retryable is True


@pytest.mark.parametrize(
    ("status", "error", "retryable"),
    [
        (401, WeatherExportUnauthorized, False),
        (404, WeatherExportMissing, False),
        (422, WeatherExportContractError, False),
        (400, WeatherExportFailure, False),
    ],
)
async def test_status_codes_are_classified(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception], retryable: bool
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(status, json={}))
    with pytest.raises(error) as excinfo:
        await fetch_weather_current(_settings())
    assert excinfo.value.retryable is retryable  # type: ignore[attr-defined]
    assert len(seen) == 1  # 재시도할 상태가 아니다


@pytest.mark.parametrize("status", [500, 502, 504, 429])
async def test_gateway_errors_are_retried_and_counted(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    replies = [httpx.Response(status), httpx.Response(200, json={"items": [], "meta": _meta(0)})]
    seen = _install(monkeypatch, lambda _request: replies.pop(0))
    with counting_upstream_requests():
        fetch = await fetch_weather_current(_settings())
        counted = observed_upstream_requests()
    assert fetch.rows == []
    assert len(seen) == 2
    assert counted == 2


# -- 503 페이지 재시도 ----------------------------------------------------------------------

_BUSY: dict[str, Any] = {"code": "EXPORT_TEMPORARILY_UNAVAILABLE"}


def _second_page_fails(
    calls: list[str | None], failures: list[httpx.Response]
) -> Callable[[httpx.Request], httpx.Response]:
    """첫 페이지는 성공, 둘째 페이지(c2)는 ``failures``를 차례로 낸 뒤 성공한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")},
            )
        if failures:
            return failures.pop(0)
        return httpx.Response(200, json={"items": [_location("b")], "meta": _meta(1)})

    return handler


@pytest.mark.parametrize(
    "body",
    [
        {"json": _BUSY},
        {"json": {"code": "EXPORT_NOT_READY"}},  # 읽기 경합을 이 이름으로 내던 이전 weather
        {"text": "<html>503 Service Unavailable</html>"},  # code 없는 앞단 프록시
    ],
    ids=["temporarily_unavailable", "old_not_ready", "proxy"],
)
async def test_a_503_retries_only_that_page_with_its_cursor_after_retry_after(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float], body: dict[str, Any]
) -> None:
    calls: list[str | None] = []
    failure = httpx.Response(503, headers={"retry-after": "7"}, **body)
    _install(monkeypatch, _second_page_fails(calls, [failure]))
    with counting_upstream_requests():
        fetch = await fetch_weather_locations(_settings())
        counted = observed_upstream_requests()
    assert calls == [None, "c2", "c2"]  # 순회를 처음부터 다시 하지 않는다
    assert [row.location_id for row in fetch.rows] == ["a", "b"]
    assert counted == 3  # 재시도도 요청이다
    assert page_sleeps == [7.0]  # 기준 5초보다 긴 Retry-After를 따른다


@pytest.mark.parametrize(("deadline", "retried"), [(100.0, True), (90.0, False)])
async def test_a_page_retry_starts_only_if_wait_plus_the_slowest_request_fits(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float], deadline: float, retried: bool
) -> None:
    # 첫 페이지가 40초 걸렸다. 45초에 503(Retry-After 7)이면 45 + 7 + 40 = 92초가 deadline 안이어야
    # 다시 묻는다 — 운영의 op는 언제나 유한 deadline으로 돈다.
    now = [0.0]
    monkeypatch.setattr(
        weather_state, "time", SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    )
    calls: list[str | None] = []
    busy = httpx.Response(503, json=_BUSY, headers={"retry-after": "7"})
    inner = _second_page_fails(calls, [busy])

    def slow(request: httpx.Request) -> httpx.Response:
        now[0] += 40.0 if request.url.params.get("cursor") is None else 5.0
        return inner(request)

    _install(monkeypatch, slow)
    with weather_state._paging_deadline(deadline):
        if retried:
            fetch = await fetch_weather_locations(_settings())
            assert [row.location_id for row in fetch.rows] == ["a", "b"]
        else:
            with pytest.raises(WeatherExportNotReady):
                await fetch_weather_locations(_settings())
    assert page_sleeps == ([7.0] if retried else [])


async def test_page_503_retries_are_bounded_and_stay_retryable(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(503, json=_BUSY, headers={"retry-after": "5"}),
    )
    with pytest.raises(WeatherExportNotReady) as excinfo:
        await fetch_weather_current(_settings())
    # 소진하면 상류 미준비다 — 적재 op는 이번 tick을 건너뛴다(처음부터 다시 읽지 않는다).
    assert excinfo.value.retryable is True
    # 5·10·20·40·60초. 다음 60초는 한 순회 대기 합 180초를 넘는다.
    assert page_sleeps == [5.0, 10.0, 20.0, 40.0, 60.0]
    assert len(seen) == 6


async def test_page_retries_share_one_sleep_cap_per_walk(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    # 페이지마다 따로 맞는 재시도가 쌓여 run 상한을 넘지 않게 한 순회의 대기 합을 180초로 묶는다.
    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(503, json=_BUSY, headers={"retry-after": "25"}),
    )
    with pytest.raises(WeatherExportNotReady):
        await fetch_weather_current(_settings())
    assert page_sleeps == [25.0, 25.0, 25.0, 40.0, 60.0]
    assert len(seen) == 6


async def test_contention_lasting_minutes_resumes_the_same_page(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    # 2026-11-23 운영: 23페이지 순회 도중 경합 503이 35초(종전 대기 합)를 넘게 이어지면 step
    # 재시도가 1페이지부터 다시 읽다 run 상한에 걸렸다. 이제 같은 cursor를 더 기다린다.
    calls: list[str | None] = []
    busy = [httpx.Response(503, json=_BUSY, headers={"retry-after": "5"}) for _ in range(5)]
    _install(monkeypatch, _second_page_fails(calls, busy))
    fetch = await fetch_weather_locations(_settings())
    assert calls == [None] + ["c2"] * 6  # 첫 페이지를 다시 읽지 않는다
    assert [row.location_id for row in fetch.rows] == ["a", "b"]
    assert page_sleeps == [5.0, 10.0, 20.0, 40.0, 60.0]


async def test_page_retry_waits_are_jittered_but_never_shorter_than_retry_after(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    monkeypatch.setattr(weather_state, "_jitter", lambda delay: delay * 0.8)
    calls: list[str | None] = []
    busy = [httpx.Response(503, json=_BUSY, headers={"retry-after": "7"}) for _ in range(3)]
    _install(monkeypatch, _second_page_fails(calls, busy))
    await fetch_weather_locations(_settings())
    # 5·10·20초를 0.8배로 흔들되 Retry-After 7초보다 짧게 기다리지 않는다.
    assert page_sleeps == [7.0, 8.0, 16.0]


async def test_page_retries_spend_the_run_retry_budget(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    from kortravelmap.dagster.upstream_retry import RetryBudget, sharing_run_retry_budget

    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(503, json=_BUSY, headers={"retry-after": "5"}),
    )
    with sharing_run_retry_budget(RetryBudget(limit=1)) as budget:
        with pytest.raises(WeatherExportNotReady):
            await fetch_weather_current(_settings())
        assert budget.used == 1
    assert len(seen) == 2  # 상관 장애면 run 예산이 먼저 끊는다
    assert page_sleeps == [5.0]


@pytest.mark.parametrize(
    ("body", "retry_after", "deadline_in"),
    [
        (_BUSY, "5", 3.0),  # 대기만으로 run 상한(꼬리 제외)을 넘긴다
        (_BUSY, "3600", None),  # 한 번 대기 상한보다 긴 Retry-After — 앞당겨 묻지 않는다
        (_BUSY, "9" * 40, None),  # 아주 긴 delta-seconds도 "아주 오래"다(날짜 해석으로 새지 않는다)
        ({"code": "EXPORT_GONE"}, "5", None),  # 모르는 명시 code는 페이지 재시도하지 않는다
        ({"code": "not a code"}, "5", None),  # 모양이 틀린 명시 code도 프록시 503이 아니다
    ],
    ids=["past_run_deadline", "retry_after_too_long", "huge_delta", "unknown_code", "bad_code"],
)
async def test_page_503_is_not_retried_past_the_run_deadline_or_early(
    monkeypatch: pytest.MonkeyPatch,
    page_sleeps: list[float],
    body: dict[str, Any],
    retry_after: str,
    deadline_in: float | None,
) -> None:
    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(503, json=body, headers={"retry-after": retry_after}),
    )
    deadline = None if deadline_in is None else time.monotonic() + deadline_in
    with weather_state._paging_deadline(deadline), pytest.raises(WeatherExportNotReady):
        await fetch_weather_current(_settings())
    assert len(seen) == 1
    assert page_sleeps == []


async def test_load_hands_its_run_deadline_to_page_retries(
    monkeypatch: pytest.MonkeyPatch, page_sleeps: list[float]
) -> None:
    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(503, json=_BUSY, headers={"retry-after": "5"}),
    )
    metadata = await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id=None,
        allow_shrink=False,
        store=cast(ValkeyStateStore, _FakeStore()),
        deadline=time.monotonic() + 3.0,  # Retry-After 5초를 기다릴 시간이 없다
    )
    assert len(seen) == 1
    assert page_sleeps == []
    # 남은 시간이 없으면 이번 tick을 건너뛴다(step 재시도로 처음부터 다시 읽지 않는다).
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == "weather_not_ready"
    assert metadata["upstream_requests_min"] == 1


async def test_a_request_past_the_run_deadline_is_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(200))
    metadata = await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id=None,
        allow_shrink=False,
        store=cast(ValkeyStateStore, _FakeStore()),
        deadline=time.monotonic() - 1.0,
    )
    assert seen == []
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == "weather_export_too_slow"


async def test_a_request_still_running_at_the_run_deadline_is_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # httpx read timeout은 읽기 한 번의 간격이라 요청 길이를 묶지 못한다(운영 300초 — current 상한
    # 600초의 절반). deadline 직전에 시작한 요청이 run monitor에 죽기(FAILURE) 전에 끊고 건너뛴다.
    async def hang(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    seen = _install(monkeypatch, hang)
    started = time.monotonic()
    metadata = await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id=None,
        allow_shrink=False,
        store=cast(ValkeyStateStore, _FakeStore()),
        deadline=time.monotonic() + 0.3,
    )
    assert time.monotonic() - started < 5
    assert len(seen) == 1
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == "weather_export_too_slow"


async def test_a_transport_retry_is_not_started_past_the_run_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HTTP 층 재시도(전송 오류·5xx)도 대기 뒤 deadline을 넘으면 하지 않는다 — 종전에는 예산 횟수만
    # 보고 15초 뒤 한 번 더 물어 꼬리 60초를 넘길 수 있었다.
    monkeypatch.setattr(weather_state, "_WEATHER_RETRY_BASE_DELAY_SECONDS", 15.0)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("느림", request=request)

    seen = _install(monkeypatch, timeout)
    with weather_state._paging_deadline(time.monotonic() + 5.0), pytest.raises(httpx.ReadTimeout):
        await fetch_weather_current(_settings())
    assert len(seen) == 1


def test_run_deadline_counts_from_the_run_start_and_keeps_a_tail() -> None:
    # run monitor는 run 시작부터 센다. step 재시도가 쓴 100초도 남은 시간에서 빠진다.
    spec = WEATHER_STATE_SPECS[1]
    started = time.time() - 100

    def record(run_id: str) -> Any:
        assert run_id == "run-x"
        return SimpleNamespace(start_time=started)

    context = SimpleNamespace(
        instance=SimpleNamespace(get_run_record_by_id=record),
        run_id="run-x",
        run=SimpleNamespace(tags={"dagster/max_runtime": "1000"}),  # run의 실제 tag가 우선
    )
    remaining = weather_state._run_deadline(cast(Any, context), spec) - time.monotonic()
    assert 1000 - 165 < remaining < 1000 - 159.99

    def unavailable(_run_id: str) -> Any:
        raise RuntimeError("instance 조회 실패")

    unknown = SimpleNamespace(
        instance=SimpleNamespace(get_run_record_by_id=unavailable),
        run_id="run-y",
        run=SimpleNamespace(tags={}),
    )
    remaining = weather_state._run_deadline(cast(Any, unknown), spec) - time.monotonic()
    assert spec.max_runtime_seconds - 65 < remaining < spec.max_runtime_seconds - 59.99


@pytest.mark.parametrize(
    "overrides",
    [
        {"kor_travel_weather_base_url": None},
        {"kor_travel_weather_base_url": "  "},
        {"kor_travel_weather_service_token": None},
        {"kor_travel_weather_service_token": SecretStr("")},
    ],
)
async def test_missing_configuration_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(200))
    with pytest.raises(WeatherExportNotConfigured):
        await fetch_weather_locations(_settings(**overrides))
    assert seen == []


async def test_non_json_body_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.providers.kor_travel_weather import WeatherExportMalformed

    _install(monkeypatch, lambda _request: httpx.Response(200, text="<html>"))
    with pytest.raises(WeatherExportMalformed):
        await fetch_weather_locations(_settings())


@pytest.mark.parametrize("status", [500, 429])
async def test_exhausted_transient_status_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _install(monkeypatch, lambda _request: httpx.Response(status))
    with pytest.raises(WeatherExportFailure) as excinfo:
        await fetch_weather_current(_settings())
    assert excinfo.value.retryable is True


async def test_location_id_with_a_pipe_is_a_terminal_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = {**_location("a|b")}
    _install(
        monkeypatch,
        lambda _request: httpx.Response(200, json={"items": [bad], "meta": _meta(1)}),
    )
    with pytest.raises(WeatherExportContractError) as excinfo:
        await fetch_weather_locations(_settings())
    assert excinfo.value.retryable is False


async def test_mid_walk_422_restarts_once_from_the_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor == "c2" and calls.count("c2") == 1:
            return httpx.Response(422, json={})
        if cursor is None:
            return httpx.Response(
                200,
                json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")},
            )
        return httpx.Response(200, json={"items": [_location("b")], "meta": _meta(1)})

    _install(monkeypatch, handler)
    fetch = await fetch_weather_locations(_settings())
    assert calls == [None, "c2", None, "c2"]
    assert [row.location_id for row in fetch.rows] == ["a", "b"]


async def test_mid_walk_422_twice_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(422, json={})
        return httpx.Response(
            200, json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")}
        )

    seen = _install(monkeypatch, handler)
    with pytest.raises(WeatherExportContractError) as excinfo:
        await fetch_weather_locations(_settings())
    assert excinfo.value.retryable is False
    assert len(seen) == 4


async def test_first_page_etag_is_kept_and_304_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == 'W/"v1"':
            return httpx.Response(304, headers={"etag": 'W/"v1"'})
        return httpx.Response(
            200,
            json={"items": [_location("a")], "meta": _meta(1)},
            headers={"etag": 'W/"v1"'},
        )

    seen = _install(monkeypatch, handler)
    fresh = await fetch_weather_locations(_settings())
    assert fresh.etag == 'W/"v1"'
    assert fresh.not_modified is False
    same = await fetch_weather_locations(_settings(), if_none_match='W/"v1"')
    assert same.not_modified is True
    assert same.rows == []
    assert "if-none-match" not in seen[0].headers
    assert seen[1].headers["if-none-match"] == 'W/"v1"'


async def test_unconditional_304_is_a_contract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _request: httpx.Response(304))
    with pytest.raises(WeatherExportContractError):
        await fetch_weather_locations(_settings())


async def test_auth_header_name_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch, lambda _request: httpx.Response(200, json={"items": [], "meta": _meta(0)})
    )
    await fetch_weather_current(_settings(kor_travel_weather_auth_header="X-Weather-Export-Token"))
    assert seen[0].headers["x-weather-export-token"] == TOKEN
    assert "x-admin-token" not in seen[0].headers


# -- 적재 op(가짜 store) ---------------------------------------------------------------------


class _FakeStore:
    def __init__(
        self,
        *,
        locked: bool = False,
        swap_error: Exception | None = None,
        current: GenerationMeta | None = None,
        lease_busy: bool = False,
    ) -> None:
        self.locked = locked
        self.swap_error = swap_error
        self.current = current
        self.lease_busy = lease_busy
        self.lease_waits: list[float] = []
        self.swapped: list[dict[str, Any]] = []
        self.touched: list[tuple[str, str]] = []

    async def current_meta(self, dataset: str) -> GenerationMeta:
        from kortravelmap.infra.valkey_state import StateNotLoaded

        if self.current is None:
            raise StateNotLoaded(dataset)
        return self.current

    async def touch_checked(self, dataset: str, generation: str, _checked_at: Any) -> bool:
        self.touched.append((dataset, generation))
        return True

    @asynccontextmanager
    async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
        assert ttl_seconds > 660
        yield not self.locked

    @asynccontextmanager
    async def shared_lease(
        self, name: str, *, ttl_seconds: float, wait_seconds: float
    ) -> AsyncIterator[bool]:
        assert name == WEATHER_EXPORT_LEASE
        assert ttl_seconds > 0
        self.lease_waits.append(wait_seconds)
        yield not self.lease_busy

    async def swap(self, dataset: str, items: list[StateItem], **kwargs: Any) -> SwapResult:
        if self.swap_error is not None:
            raise self.swap_error
        self.swapped.append({"dataset": dataset, "items": items, **kwargs})
        meta = GenerationMeta(
            dataset=dataset,
            generation="20261024T000000Z-00000000",
            count=len(items),
            geo_count=0,
            lookup_count=0,
            duplicates=0,
            source_collected_at=kwargs["source_collected_at"],
            loaded_at=kwargs["loaded_at"],
            run_id=kwargs["run_id"],
            guard_override=kwargs["allow_shrink"],
            source_status=kwargs["source_status"],
        )
        return SwapResult(meta=meta, previous_generation=None, baseline=None)

    async def retire_other_versions(self, _dataset: str) -> int:
        return 0


def _short_spec() -> WeatherStateJobSpec:
    return next(spec for spec in WEATHER_STATE_SPECS if spec.dataset is DATASET_FORECAST_SHORT)


async def test_forecast_load_groups_per_location_and_records_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = (NOW + timedelta(hours=1)).isoformat()

    def group(location_id: str, provider: str) -> dict[str, Any]:
        return {
            "location_id": location_id,
            "provider": provider,
            "forecast_style": "short",
            "known_at": NOW.isoformat(),
            "published_at": NOW.isoformat(),
            "target_at": [target],
            "metrics": {"TMP": [10.0]},
        }

    body = {
        "items": [group("a", "kma"), group("a", "kma"), group("a", "om"), group("b", "kma")],
        "meta": _meta(4, source_status="stale"),
    }
    _install(monkeypatch, lambda _request: httpx.Response(200, json=body))
    store = _FakeStore()
    metadata = await load_weather_state(
        _short_spec(),
        settings=_settings(),
        run_id="run-w",
        allow_shrink=True,
        store=cast(ValkeyStateStore, store),
    )
    (swap,) = store.swapped
    assert swap["dataset"] == "weather.forecast_short"
    assert len(swap["items"]) == 2  # 위치 단위
    assert swap["source_status"] == "stale"
    assert swap["source_collected_at"] == NOW - timedelta(minutes=5)
    assert metadata["row_duplicates"] == 1
    assert metadata["source_rows"] == 4
    assert metadata["source_status"] == "stale"
    assert metadata["upstream_requests_min"] == 1


def _failing_spec(error: Exception) -> WeatherStateJobSpec:
    async def _collect(_settings: Any, _etag: str | None) -> Any:
        raise error

    return replace(WEATHER_STATE_SPECS[0], collect=_collect)


async def _load(spec: WeatherStateJobSpec, store: _FakeStore) -> dict[str, Any]:
    return await load_weather_state(
        spec,
        settings=KorTravelMapSettings.model_construct(),
        run_id=None,
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
    )


@pytest.mark.parametrize(
    "error",
    [
        WeatherExportUnauthorized("401"),
        WeatherExportMissing("404"),
        WeatherExportContractError("모양"),
        WeatherExportNotConfigured("설정"),
    ],
)
async def test_unrecoverable_weather_failures_turn_off_step_retries(error: Exception) -> None:
    store = _FakeStore()
    with pytest.raises(Failure) as excinfo:
        await _load(_failing_spec(error), store)
    assert excinfo.value.allow_retries is False
    expected_kind = error.failure_kind  # type: ignore[attr-defined]
    assert str(excinfo.value.metadata["failure_kind"].value) == expected_kind
    assert store.swapped == []


def _served(age: timedelta, **overrides: Any) -> GenerationMeta:
    collected = datetime.now(UTC) - age
    values: dict[str, Any] = {
        "dataset": "weather.locations",
        "generation": "g-served",
        "count": 1_400,
        "geo_count": 1_400,
        "lookup_count": 1_400,
        "duplicates": 0,
        "source_collected_at": collected,
        "loaded_at": collected,
        "run_id": "run-old",
        "guard_override": False,
        "source_status": "ok",
    }
    values.update(overrides)
    return GenerationMeta(**values)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (WeatherExportNotReady("503"), "weather_not_ready"),
        (WeatherExportSnapshotExpired("410"), "weather_snapshot_expired"),
        (httpx.ReadTimeout("느림"), "upstream_unreachable:ReadTimeout"),
        (httpx.ConnectError("끊김"), "upstream_unreachable:ConnectError"),
    ],
)
async def test_waitable_weather_failures_skip_the_tick(error: Exception, kind: str) -> None:
    # 상류 미준비는 step 재시도 없이 이번 tick을 건너뛰고 세대를 지킨다(transport와 같은 규칙).
    store = _FakeStore(current=_served(timedelta(hours=1)))
    metadata = await _load(_failing_spec(error), store)
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["upstream_state"] == "not_ready"
    assert metadata["failure_kind"] == kind
    assert metadata["served_generation"] == "g-served"
    assert 3_500 < metadata["served_age_seconds"] < 3_700
    assert metadata["stale_alert"] is False
    assert store.swapped == []


async def test_not_ready_past_the_stale_age_fails_the_run() -> None:
    spec = _failing_spec(WeatherExportNotReady("503"))
    store = _FakeStore(current=_served(spec.stale_alert_after + timedelta(hours=1)))
    metadata = await _load(spec, store)
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["stale_alert"] is True
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(metadata)
    assert excinfo.value.allow_retries is False


async def test_a_busy_export_skips_the_tick_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 다른 weather 상태 적재가 export를 읽는 동안 읽지 않는다 — 기다려도 못 잡으면 건너뛴다.
    seen = _install(monkeypatch, lambda _request: httpx.Response(200))
    store = _FakeStore(current=_served(timedelta(minutes=30)), lease_busy=True)
    metadata = await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id=None,
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
        deadline=time.monotonic() + 800,
    )
    assert seen == []
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == "weather_export_busy"
    # 기다림 = 남은 run 시간 − 읽기 예산(locations 600초)
    (waited,) = store.lease_waits
    assert 180 < waited <= 200


async def test_a_walk_that_cannot_finish_before_the_ceiling_stops_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 상한에 죽으면 빨간 run이 되고 받은 페이지도 버려진다 — 다음 페이지를 끝낼 수 없으면 먼저
    # 멈춘다.
    now = [0.0]
    monkeypatch.setattr(
        weather_state, "time", SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    )

    def slow(request: httpx.Request) -> httpx.Response:
        now[0] += 30.0
        cursor = request.url.params.get("cursor")
        page = int(cursor) if cursor else 0
        return httpx.Response(
            200,
            json={
                "items": [_location(f"l{page}")],
                "meta": _meta(1, has_more=True, next_cursor=str(page + 1)),
            },
        )

    seen = _install(monkeypatch, slow)
    with weather_state._paging_deadline(100.0), pytest.raises(WeatherExportNotReady) as excinfo:
        await fetch_weather_locations(_settings())
    assert excinfo.value.failure_kind == "weather_export_too_slow"
    assert len(seen) == 3  # 30·60·90초 — 넷째(120초)는 deadline 100초를 넘는다


async def test_a_restart_after_410_checks_its_first_page_against_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 410으로 처음부터 다시 받을 때 첫 페이지도 앞 순회가 잰 가장 느린 요청으로 deadline을 본다.
    now = [0.0]
    monkeypatch.setattr(
        weather_state, "time", SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    )
    calls: list[str | None] = []

    def slow(request: httpx.Request) -> httpx.Response:
        now[0] += 40.0
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor == "c2":
            return httpx.Response(410, json={})
        return httpx.Response(
            200,
            json={"items": [_location("a")], "meta": _meta(1, has_more=True, next_cursor="c2")},
        )

    _install(monkeypatch, slow)
    with weather_state._paging_deadline(100.0), pytest.raises(WeatherExportNotReady) as excinfo:
        await fetch_weather_locations(_settings())
    assert excinfo.value.failure_kind == "weather_export_too_slow"
    assert calls == [None, "c2"]  # 80초 + 가장 느린 40초 > 100초 — 다시 시작하지 않는다


def _ok_spec(source_status: str = "ok", index: int = 0) -> WeatherStateJobSpec:
    async def _ok(_settings: Any, _etag: str | None) -> Any:
        fetch = weather_state.WeatherFetch(
            [], datetime.now(UTC) - timedelta(minutes=10), source_status, 1, None
        )
        return weather_state.WeatherCollected(items=[], row_duplicates=0, fetch=fetch)

    return replace(WEATHER_STATE_SPECS[index], collect=_ok)


async def test_stale_source_is_swapped_and_reported_like_transport() -> None:
    # 200 + stale은 값이 왔으므로 교체한다. 상태는 metadata로 남는다(초록이지만 보인다).
    store = _FakeStore()
    metadata = await _load(_ok_spec("stale", index=1), store)  # current는 집합 상태를 알린다
    assert len(store.swapped) == 1
    assert metadata["upstream_state"] == "stale"
    assert metadata["served_generation"] == "20261024T000000Z-00000000"
    # weather 빨강은 Map 적재 기준이다 — 방금 교체했으니 0에 가깝다. 원천 시각은 따로 남는다.
    assert metadata["served_age_basis"] == "loaded"
    assert 0 <= metadata["served_age_seconds"] < 60
    assert metadata["served_source_collected_at"]
    assert metadata["stale_alert"] is False
    fresh = await _load(_ok_spec("ok"), _FakeStore())
    assert fresh["upstream_state"] == "ok"


async def test_weather_refusal_follows_the_served_generation_age() -> None:
    refused = StateSwapRefused("roster가 줄었다", baseline=6, new_count=2)
    fresh = await _load(
        _ok_spec(), _FakeStore(swap_error=refused, current=_served(timedelta(hours=2)))
    )
    assert fresh["skipped"] == "refused"
    assert fresh["failure_kind"] == "state_swap_refused"
    assert fresh["stale_alert"] is False
    stale = await _load(
        _ok_spec(),
        _FakeStore(
            swap_error=refused,
            current=_served(WEATHER_STATE_SPECS[0].stale_alert_after + timedelta(hours=1)),
        ),
    )
    assert stale["skipped"] == "refused"
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(stale)
    assert excinfo.value.allow_retries is False
    assert str(excinfo.value.metadata["failure_kind"].value) == "state_swap_refused"


async def test_valkey_outage_stays_retryable_and_lock_skips() -> None:
    async def _ok(_settings: Any, _etag: str | None) -> Any:
        return weather_state.WeatherCollected(
            items=[], row_duplicates=0, fetch=weather_state.WeatherFetch([], None, "ok", 1, None)
        )

    spec = replace(WEATHER_STATE_SPECS[0], collect=_ok)
    with pytest.raises(StateStoreUnavailable):
        await _load(spec, _FakeStore(swap_error=StateStoreUnavailable("연결")))

    async def _boom(_settings: Any, _etag: str | None) -> Any:
        raise AssertionError("잠금을 못 잡았으면 받지 않는다")

    locked = await _load(replace(spec, collect=_boom), _FakeStore(locked=True))
    assert locked["skipped"] == "locked"


def test_collectors_are_bound_to_their_own_style() -> None:
    styles: list[Callable[..., Any]] = [spec.collect for spec in WEATHER_STATE_SPECS]
    assert len(set(styles)) == len(styles)


async def test_not_modified_touches_the_current_generation_without_swapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(304))
    current = GenerationMeta(
        dataset="weather.locations",
        generation="g-1",
        count=3,
        geo_count=3,
        lookup_count=3,
        duplicates=0,
        source_collected_at=None,
        loaded_at=NOW,
        run_id=None,
        guard_override=False,
        source_status="stale",
        source_etag='W/"v1"',
    )
    store = _FakeStore(current=current)
    metadata = await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id="run-304",
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
    )
    assert metadata["unchanged"] == "not_modified"
    # W1 위치 roster는 집합 상태를 알리지 않는다(weather가 늘 stale을 싣는다) — ok로 보고
    # 나이만 잰다.
    assert metadata["upstream_state"] == "ok"
    assert metadata["served_generation"] == "g-1"
    assert store.swapped == []
    assert store.touched == [("weather.locations", "g-1")]
    assert seen[0].headers["if-none-match"] == 'W/"v1"'
    assert metadata["upstream_requests_min"] == 1


async def test_allow_shrink_forces_a_full_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch,
        lambda _request: httpx.Response(
            200, json={"items": [_location("a")], "meta": _meta(1)}, headers={"etag": 'W/"v2"'}
        ),
    )
    current = GenerationMeta(
        dataset="weather.locations", generation="g-1", count=3, geo_count=3, lookup_count=3,
        duplicates=0, source_collected_at=None, loaded_at=NOW, run_id=None, guard_override=False,
        source_etag='W/"v1"',
    )
    store = _FakeStore(current=current)
    await load_weather_state(
        WEATHER_STATE_SPECS[0],
        settings=_settings(),
        run_id=None,
        allow_shrink=True,
        store=cast(ValkeyStateStore, store),
    )
    assert "if-none-match" not in seen[0].headers
    assert store.swapped[0]["source_etag"] == 'W/"v2"'
