"""ADR-114 2단계 weather 상태 적재 job(Valkey 없이).

정의(STOPPED·tag)·fetcher(cursor·snapshot·410·인증·계수)·실패 분류를 본다. 실제 Valkey 왕복은
``tests/integration/test_valkey_weather_state.py``가 본다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from dagster import DefaultScheduleStatus, Failure
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateItem,
    StateStoreUnavailable,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_weather import (
    ADMIN_TOKEN_HEADER,
    WeatherExportContractError,
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
from kortravelmap.dagster.weather_state import (
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
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather_state, "_WEATHER_RETRY_BASE_DELAY_SECONDS", 0.0)


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


def test_lock_ttl_follows_the_run_ceiling() -> None:
    for spec in WEATHER_STATE_SPECS:
        assert weather_lock_ttl_seconds(spec) == spec.max_runtime_seconds + 660


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
        (503, WeatherExportNotReady, True),
        (422, WeatherExportContractError, False),
    ],
)
async def test_status_codes_are_classified(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception], retryable: bool
) -> None:
    seen = _install(monkeypatch, lambda _request: httpx.Response(status, json={}))
    with pytest.raises(error) as excinfo:
        await fetch_weather_current(_settings())
    assert getattr(excinfo.value, "retryable") is retryable
    assert len(seen) == 1  # 재시도할 상태가 아니다


async def test_gateway_errors_are_retried_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [httpx.Response(502), httpx.Response(200, json={"items": [], "meta": _meta(0)})]
    seen = _install(monkeypatch, lambda _request: replies.pop(0))
    with counting_upstream_requests():
        fetch = await fetch_weather_current(_settings())
        counted = observed_upstream_requests()
    assert fetch.rows == []
    assert len(seen) == 2
    assert counted == 2


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


# -- 적재 op(가짜 store) ---------------------------------------------------------------------


class _FakeStore:
    def __init__(self, *, locked: bool = False, swap_error: Exception | None = None) -> None:
        self.locked = locked
        self.swap_error = swap_error
        self.swapped: list[dict[str, Any]] = []

    @asynccontextmanager
    async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
        assert ttl_seconds > 660
        yield not self.locked

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
    async def _collect(_settings: Any) -> Any:
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
    assert str(excinfo.value.metadata["failure_kind"].value) == getattr(error, "failure_kind")
    assert store.swapped == []


@pytest.mark.parametrize(
    "error", [WeatherExportNotReady("503"), WeatherExportSnapshotExpired("410")]
)
async def test_waitable_weather_failures_stay_retryable(error: Exception) -> None:
    with pytest.raises(type(error)):
        await _load(_failing_spec(error), _FakeStore())


async def test_valkey_outage_stays_retryable_and_lock_skips() -> None:
    async def _ok(_settings: Any) -> Any:
        return weather_state.WeatherCollected(
            items=[], row_duplicates=0, fetch=weather_state.WeatherFetch([], None, "ok", 1, None)
        )

    spec = replace(WEATHER_STATE_SPECS[0], collect=_ok)
    with pytest.raises(StateStoreUnavailable):
        await _load(spec, _FakeStore(swap_error=StateStoreUnavailable("연결")))

    async def _boom(_settings: Any) -> Any:
        raise AssertionError("잠금을 못 잡았으면 받지 않는다")

    locked = await _load(replace(spec, collect=_boom), _FakeStore(locked=True))
    assert locked["skipped"] == "locked"


def test_collectors_are_bound_to_their_own_style() -> None:
    styles: list[Callable[..., Any]] = [spec.collect for spec in WEATHER_STATE_SPECS]
    assert len(set(styles)) == len(styles)
