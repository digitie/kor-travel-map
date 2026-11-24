"""weather 내용 ETag 계약 시험(kor-travel-weather 호출 검토 A2, ADR-114 W3).

weather는 W1 ``locations``·W2 ``current``·W5 ``daily-summaries``의 약한 ETag에서 ``snapshot_id``를
뺐다. 같은 승인 집합이면 snapshot handle TTL(15분)이 지나 새 handle이 발급돼도 ETag가 같고, 첫
페이지 조건부 요청은 본문을 읽기 전에 304로 끝난다. 304는 새 ``snapshot_id``·``next_cursor``를 주지
않는다(본문이 없다).

Map 쪽 계약은 바뀌지 않는다 — 지금 세대의 ``source_etag``를 첫 페이지에만 ``If-None-Match``로
보내고, 304면 받지도 교체하지도 않고 그 세대의 ``checked_at``만 갱신한다. 예보(W3)는 ETag를 보내지
않는다(ADR-122). 이 파일은 그 계약이 weather의 새 의미(handle이 바뀌어도 내용이 같으면 304)와
맞물리는지 고정한다. 실제 Valkey 왕복은 ``tests/integration/test_valkey_weather_state.py``가 본다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateItem,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_weather import (
    EXPORT_PATH_CURRENT,
    EXPORT_PATH_DAILY_SUMMARIES,
    EXPORT_PATH_FORECASTS,
    EXPORT_PATH_LOCATIONS,
)
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_CURRENT,
    DATASET_DAILY_SUMMARIES,
    DATASET_FORECAST_ULTRA_SHORT,
    DATASET_LOCATIONS,
    WeatherStateDataset,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.weather_state as weather_state
from kortravelmap.dagster.weather_state import (
    WEATHER_STATE_SPECS,
    WeatherStateJobSpec,
    fetch_weather_current,
    load_weather_state,
)

TOKEN = "w" * 40
NOW = datetime.now(UTC).replace(microsecond=0)
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _settings() -> KorTravelMapSettings:
    return KorTravelMapSettings(
        kor_travel_weather_base_url="http://127.0.0.1:14201/",
        kor_travel_weather_service_token=SecretStr(TOKEN),
        kor_travel_weather_page_size=2_000,
        kor_travel_weather_forecast_page_size=200,
    )


def _spec(dataset: WeatherStateDataset) -> WeatherStateJobSpec:
    return next(spec for spec in WEATHER_STATE_SPECS if spec.dataset is dataset)


def _location(location_id: str, name: str) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "name": name,
        "latitude": 37.5,
        "longitude": 127.0,
        "legal_dong_code": None,
        "sido_name": None,
        "sigungu_name": None,
    }


def _current(location_id: str, value: float) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "provider": "python-kma-api",
        "metric_key": "T1H",
        "value": value,
        "unit": "deg_c",
        "target_at": (NOW - timedelta(minutes=10)).isoformat(),
        "known_at": (NOW - timedelta(minutes=5)).isoformat(),
        "forecast_style": "nowcast",
    }


def _daily(location_id: str, temp_avg: float) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "date": NOW.date().isoformat(),
        "slot": "morning",
        "temp_min": temp_avg - 1,
        "temp_max": temp_avg + 1,
        "temp_avg": temp_avg,
        "humidity_avg": 50.0,
        "precip_sum_mm": 0.0,
        "precip_occurred": False,
        "sky_code": 1,
        "wind_speed_avg": 1.0,
        "sample_count": 6,
        "source_providers": ["python-kma-api"],
        "partial": False,
    }


def _forecast(location_id: str) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "provider": "python-kma-api",
        "forecast_style": "ultra_short",
        "known_at": NOW.isoformat(),
        "published_at": NOW.isoformat(),
        "target_at": [(NOW + timedelta(hours=1)).isoformat()],
        "metrics": {"T1H": [10.0]},
    }


class _ContentEtagWeather:
    """weather 내용 ETag를 흉내 낸 MockTransport handler.

    ETag는 항목·상태의 digest이고 ``snapshot_id``는 넣지 않는다. 첫 페이지 요청마다 새 snapshot
    handle을 발급한다(handle TTL이 지난 다음 run을 흉내). ``If-None-Match``가 맞으면 본문 없는
    304를 낸다 — weather처럼 같은 ETag와 ``x-source-status``만 싣는다.
    """

    def __init__(self, items: list[dict[str, Any]], *, source_status: str = "ok") -> None:
        self.items = items
        self.source_status = source_status
        self.handles = 0
        self.requests: list[httpx.Request] = []

    @property
    def etag(self) -> str:
        body = json.dumps([self.items, self.source_status], sort_keys=True).encode()
        return 'W/"' + hashlib.sha256(body).hexdigest() + '"'

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.handles += 1
        validator = {"etag": self.etag, "x-source-status": self.source_status}
        sent = request.headers.get("if-none-match")
        if sent is not None and sent.removeprefix("W/") == self.etag.removeprefix("W/"):
            return httpx.Response(304, headers=validator)
        meta = {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_collected_at": (NOW - timedelta(minutes=5)).isoformat(),
            "source_status": self.source_status,
            "item_count": len(self.items),
            "snapshot_id": f"snap-{self.handles}",
            "next_cursor": None,
            "has_more": False,
        }
        if request.url.path == EXPORT_PATH_FORECASTS:
            meta["next_since"] = NOW.isoformat()
        return httpx.Response(200, json={"items": self.items, "meta": meta}, headers=validator)


def _install(monkeypatch: pytest.MonkeyPatch, weather: _ContentEtagWeather) -> None:
    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(weather), **kwargs)

    monkeypatch.setattr(weather_state.httpx, "AsyncClient", factory)


class _Store:
    """세대 하나를 기억하는 가짜 Valkey 저장소. 교체한 meta(``source_etag`` 포함)가 지금 세대다."""

    def __init__(self) -> None:
        self.current: GenerationMeta | None = None
        self.swapped: list[dict[str, Any]] = []
        self.touched: list[tuple[str, str, datetime]] = []

    async def current_meta(self, dataset: str) -> GenerationMeta:
        from kortravelmap.infra.valkey_state import StateNotLoaded

        if self.current is None:
            raise StateNotLoaded(dataset)
        return self.current

    async def touch_checked(self, dataset: str, generation: str, checked_at: datetime) -> bool:
        # 실제 저장소처럼 포인터가 그 세대일 때만 meta의 checked_at 한 필드만 바꾼다.
        assert self.current is not None
        assert self.current.generation == generation
        self.touched.append((dataset, generation, checked_at))
        self.current = replace(self.current, checked_at=checked_at)
        return True

    @asynccontextmanager
    async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
        yield True

    @asynccontextmanager
    async def shared_lease(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[bool]:
        # weather 읽기 줄 세우기(kor-travel-map #1542)가 들어와도 이 시험은 그대로 돈다.
        yield True

    async def swap(self, dataset: str, items: list[StateItem], **kwargs: Any) -> SwapResult:
        self.swapped.append({"dataset": dataset, "items": items, **kwargs})
        meta = GenerationMeta(
            dataset=dataset,
            generation=f"g-{len(self.swapped)}",
            count=len(items),
            geo_count=0,
            lookup_count=0,
            duplicates=0,
            source_collected_at=kwargs["source_collected_at"],
            loaded_at=kwargs["loaded_at"],
            run_id=kwargs["run_id"],
            guard_override=kwargs["allow_shrink"],
            source_status=kwargs["source_status"],
            source_etag=kwargs["source_etag"],
            sync_mode=kwargs.get("sync_mode"),
            sync_cursor=kwargs.get("sync_cursor"),
            full_synced_at=kwargs.get("full_synced_at"),
            row_duplicates=kwargs.get("row_duplicates"),
        )
        self.current = meta
        return SwapResult(meta=meta, previous_generation=None, baseline=None)

    async def retire_other_versions(self, _dataset: str) -> int:
        return 0


async def _run(spec: WeatherStateJobSpec, store: _Store) -> dict[str, Any]:
    return await load_weather_state(
        spec,
        settings=_settings(),
        run_id="run-etag",
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
    )


# (데이터셋, 경로, 항목). 항목 수는 각 데이터셋의 교체 거부 하한 위다.
_ETAG_DATASETS = [
    pytest.param(
        DATASET_LOCATIONS,
        EXPORT_PATH_LOCATIONS,
        [_location(f"loc-{index}", f"위치 {index}") for index in range(1_200)],
        id="locations",
    ),
    pytest.param(
        DATASET_CURRENT,
        EXPORT_PATH_CURRENT,
        [_current(f"loc-{index}", 18.4) for index in range(600)],
        id="current",
    ),
    pytest.param(
        DATASET_DAILY_SUMMARIES,
        EXPORT_PATH_DAILY_SUMMARIES,
        [_daily(f"loc-{index}", 15.0) for index in range(1_200)],
        id="daily_summaries",
    ),
]
# 데이터셋별로 첫 항목에 줄 내용 변경.
_CHANGES: dict[str, dict[str, Any]] = {
    DATASET_LOCATIONS.name: {"name": "이름 바뀐 위치"},
    DATASET_CURRENT.name: {"value": 20.4},
    DATASET_DAILY_SUMMARIES.name: {"temp_avg": 16.0},
}


@pytest.mark.parametrize(("dataset", "path", "items"), _ETAG_DATASETS)
async def test_same_content_under_a_new_snapshot_handle_keeps_the_generation(
    monkeypatch: pytest.MonkeyPatch,
    dataset: WeatherStateDataset,
    path: str,
    items: list[dict[str, Any]],
) -> None:
    weather = _ContentEtagWeather(items)
    _install(monkeypatch, weather)
    store = _Store()
    first = await _run(_spec(dataset), store)
    assert "unchanged" not in first
    (swap,) = store.swapped
    assert swap["source_etag"] == weather.etag
    assert "if-none-match" not in weather.requests[0].headers
    generation = first["generation"]

    # 다음 run: weather는 새 handle(snap-2)을 발급했지만 내용이 같아 ETag가 같다 → 304.
    second = await _run(_spec(dataset), store)
    assert second["unchanged"] == "not_modified"
    assert second["generation"] == generation
    assert len(store.swapped) == 1  # 받지도 교체하지도 않는다
    assert [(name, gen) for name, gen, _ in store.touched] == [(dataset.name, generation)]
    (conditional,) = weather.requests[1:]
    assert conditional.url.path == path
    assert conditional.headers["if-none-match"] == weather.etag
    assert "cursor" not in conditional.url.params  # 304 뒤 cursor를 따라가지 않는다
    assert weather.handles == 2


@pytest.mark.parametrize(("dataset", "path", "items"), _ETAG_DATASETS)
async def test_changed_content_or_status_replaces_the_generation_with_the_new_etag(
    monkeypatch: pytest.MonkeyPatch,
    dataset: WeatherStateDataset,
    path: str,
    items: list[dict[str, Any]],
) -> None:
    weather = _ContentEtagWeather(items)
    _install(monkeypatch, weather)
    store = _Store()
    await _run(_spec(dataset), store)
    first_etag = weather.etag

    # 항목 하나가 바뀌면 weather ETag가 바뀐다 → 조건부 요청이 200 → 새 세대와 새 ETag.
    weather.items = [{**items[0], **_CHANGES[dataset.name]}, *items[1:]]
    changed = await _run(_spec(dataset), store)
    assert "unchanged" not in changed
    assert weather.requests[1].url.path == path
    assert weather.requests[1].headers["if-none-match"] == first_etag
    assert store.swapped[-1]["source_etag"] == weather.etag != first_etag
    changed_etag = weather.etag

    # 내용은 같고 상태만 stale로 바뀌어도 ETag가 바뀐다 → 200 → 새 세대(stale 기록).
    weather.source_status = "stale"
    stale = await _run(_spec(dataset), store)
    assert "unchanged" not in stale
    assert weather.requests[2].headers["if-none-match"] == changed_etag
    assert store.swapped[-1]["source_status"] == "stale"
    assert store.swapped[-1]["source_etag"] == weather.etag != changed_etag
    assert len(store.swapped) == 3
    assert store.touched == []


async def test_not_modified_needs_no_snapshot_or_cursor_and_keeps_the_sent_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weather = _ContentEtagWeather([_current("loc-1", 18.4)])
    _install(monkeypatch, weather)
    stored = weather.etag
    fetch = await fetch_weather_current(_settings(), if_none_match=stored)
    assert fetch.not_modified is True
    assert fetch.rows == []
    assert fetch.pages == 1
    # 304는 본문이 없다 — 새 snapshot_id·cursor 없이 Map이 보낸 ETag를 그대로 둔다.
    assert fetch.snapshot_id is None
    assert fetch.etag == stored
    assert len(weather.requests) == 1


async def test_forecasts_never_send_if_none_match_even_with_a_stored_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 예보 전량의 304는 증분 cursor·전량 시각을 다시 잡지 못한다(ADR-122). weather 내용 ETag가
    # 들어와도 Map은 예보에 If-None-Match를 보내지 않는다.
    weather = _ContentEtagWeather([_forecast(f"loc-{index}") for index in range(600)])
    _install(monkeypatch, weather)
    store = _Store()
    spec = _spec(DATASET_FORECAST_ULTRA_SHORT)
    await _run(spec, store)
    assert store.current is not None
    assert store.current.source_etag == weather.etag
    await _run(spec, store)
    assert all("if-none-match" not in request.headers for request in weather.requests)
    assert len(store.swapped) == 2
