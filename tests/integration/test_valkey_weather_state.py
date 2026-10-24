"""ADR-114 2단계 — 실제 Valkey(일회용 컨테이너)로 weather 상태 적재 op → REST 왕복을 잰다.

세대 교체 자체(CAS·부분 쓰기·거부·grace)는 1단계 ``test_valkey_transport_state.py``가 같은 store로
잰다. 여기서는 weather 쪽 효과를 본다 — weather export(가짜 HTTP)를 끝까지 받아 위치 단위로 싣고,
위치 GEO로 근처를 찾아 다른 데이터셋을 같은 id로 붙이고, 지난 예보 시각을 읽을 때 떼고, 한
데이터셋이 없어도 묶음이 나오고, 비정상 집합은 교체하지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.infra.valkey_state import ShrinkGuard, ValkeyStateStore, make_valkey_client
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_CURRENT,
    DATASET_DAILY_SUMMARIES,
    DATASET_FORECAST_SHORT,
    DATASET_LOCATIONS,
    weather_location_feature_id,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._valkey import valkey_container

pytestmark = pytest.mark.integration

LENIENT = ShrinkGuard(min_ratio=0.5, baseline_min=2, min_count=1)


@pytest.fixture(scope="session")
def valkey_url() -> Iterator[str]:
    with valkey_container() as url:
        yield url


@pytest.fixture
async def store(valkey_url: str) -> AsyncIterator[ValkeyStateStore]:
    settings = KorTravelMapSettings.model_construct(
        valkey_url=SecretStr(valkey_url),
        valkey_connect_timeout_seconds=1.0,
        valkey_socket_timeout_seconds=2.0,
    )
    client = make_valkey_client(settings)
    await client.flushdb()
    active = ValkeyStateStore(client, build_ttl_seconds=120, retire_grace_seconds=60)
    try:
        yield active
    finally:
        await client.aclose()


@pytest.fixture
async def api(store: ValkeyStateStore) -> AsyncIterator[httpx.AsyncClient]:
    from kortravelmap.api.app import create_app
    from kortravelmap.api.routers.service_weather import get_weather_state_store
    from kortravelmap.api.settings import ApiSettings

    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    app.dependency_overrides[get_weather_state_store] = lambda: store
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://map.test"
    ) as client:
        yield client


def _weather_settings() -> KorTravelMapSettings:
    return KorTravelMapSettings.model_construct(
        kor_travel_weather_base_url="http://weather.test",
        kor_travel_weather_service_token=SecretStr("w" * 40),
        kor_travel_weather_page_size=2,
        kor_travel_weather_timeout_seconds=5.0,
        kor_travel_weather_connect_timeout_seconds=1.0,
        weather_daily_summary_days=14,
    )


def _meta(count: int, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    meta: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "source_collected_at": (now - timedelta(minutes=4)).isoformat(),
        "source_status": "ok",
        "item_count": count,
        "snapshot_id": "snap",
        "next_cursor": None,
        "has_more": False,
    }
    meta.update(overrides)
    return meta


def _pages(rows: list[dict[str, Any]], size: int = 2, **meta: Any) -> dict[str | None, Any]:
    """rows를 cursor 페이지로 나눈다(cursor = 페이지 번호 문자열)."""
    pages: dict[str | None, Any] = {}
    chunks = [rows[i : i + size] for i in range(0, len(rows), size)] or [[]]
    for index, chunk in enumerate(chunks):
        key = None if index == 0 else str(index)
        more = index + 1 < len(chunks)
        pages[key] = {
            "items": chunk,
            "meta": _meta(
                len(chunk), has_more=more, next_cursor=str(index + 1) if more else None, **meta
            ),
        }
    return pages


_REAL_ASYNC_CLIENT = httpx.AsyncClient


#: 가짜 weather가 내는 경로 → cursor 페이지. ``_load``가 적재 op 동안만 httpx client를 바꿔
#: 끼운다(API 미들웨어가 ``isinstance(…, httpx.AsyncClient)``를 쓰므로 REST 호출 중에는 원래
#: 타입이어야 한다).
_ROUTES: dict[str, dict[str | None, Any]] = {}


def _serve(_monkeypatch: pytest.MonkeyPatch, routes: dict[str, dict[str | None, Any]]) -> None:
    _ROUTES.clear()
    _ROUTES.update(routes)
    _ETAGS.clear()


_ETAGS: dict[str, str] = {}
"""경로 → 첫 페이지 ETag. 있으면 그 값으로 ``If-None-Match``가 오면 304를 낸다."""


def _weather_handler(request: httpx.Request) -> httpx.Response:
    etag = _ETAGS.get(request.url.path)
    if etag is not None and request.headers.get("if-none-match") == etag:
        return httpx.Response(304, headers={"etag": etag})
    pages = _ROUTES[request.url.path]
    cursor = request.url.params.get("cursor")
    headers = {"etag": etag} if etag is not None and cursor is None else {}
    return httpx.Response(200, json=pages[cursor], headers=headers)


def _routed_client(**kwargs: Any) -> httpx.AsyncClient:
    return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(_weather_handler), **kwargs)


def _location(location_id: str, lon: float, lat: float) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "name": f"위치 {location_id}",
        "latitude": lat,
        "longitude": lon,
        "legal_dong_code": "1111010100",
        "sido_name": "서울특별시",
        "sigungu_name": "종로구",
    }


async def _load(store: ValkeyStateStore, dataset: Any, **kwargs: Any) -> dict[str, Any]:
    import kortravelmap.dagster.weather_state as weather_state

    spec = next(s for s in weather_state.WEATHER_STATE_SPECS if s.dataset is dataset)
    spec = replace(spec, dataset=replace(spec.dataset, guard=LENIENT))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(weather_state.httpx, "AsyncClient", _routed_client)
        return await weather_state.load_weather_state(
            spec,
            settings=_weather_settings(),
            run_id="run-int",
            allow_shrink=kwargs.get("allow_shrink", False),
            store=store,
        )


async def test_load_then_nearest_bundle_joins_every_dataset(
    store: ValkeyStateStore, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    locations = [
        _location("seoul", 126.978, 37.5665),
        _location("busan", 129.0756, 35.1796),
        _location("jeju", 126.5312, 33.4996),
    ]
    current = [
        {
            "location_id": "seoul",
            "provider": "python-kma-api",
            "metric_key": key,
            "value": value,
            "unit": unit,
            "target_at": (now - timedelta(minutes=40)).isoformat(),
            "known_at": (now - timedelta(minutes=30)).isoformat(),
            "forecast_style": "nowcast",
        }
        for key, value, unit in [("T1H", 12.3, "deg_c"), ("REH", 55.0, "%"), ("PTY", 0.0, "code")]
    ]
    targets = [now + timedelta(hours=h) for h in (-2, -1, 1, 2)]
    forecasts = [
        {
            "location_id": "seoul",
            "provider": "python-kma-api",
            "forecast_style": "short",
            "known_at": (now - timedelta(hours=3)).isoformat(),
            "published_at": (now - timedelta(hours=3)).isoformat(),
            "target_at": [t.isoformat() for t in targets],
            "metrics": {"TMP": [9.0, 10.0, 11.0, 12.0], "SKY": ["1", "1", "3", None]},
        },
        {
            "location_id": "busan",
            "provider": "python-kma-api",
            "forecast_style": "short",
            "known_at": now.isoformat(),
            "published_at": now.isoformat(),
            "target_at": [(now + timedelta(hours=1)).isoformat()],
            "metrics": {"TMP": [18.0]},
        },
    ]
    # 끝난 두 날의 아침(오늘 아침은 읽는 시각에 따라 partial이라 비교하지 않는다 — W7).
    today = (now + timedelta(hours=9)).date() - timedelta(days=1)  # KST 어제
    yesterday = today - timedelta(days=1)
    daily = [
        {
            "location_id": "seoul",
            "date": day.isoformat(),
            "slot": "morning",
            "temp_min": temp - 2,
            "temp_max": temp + 2,
            "temp_avg": temp,
            "humidity_avg": humidity,
            "precip_sum_mm": 0.0,
            "precip_occurred": False,
            "sky_code": 1,
            "wind_speed_avg": 1.5,
            "sample_count": 6,
            "source_providers": ["python-kma-api"],
            "partial": False,
        }
        for day, temp, humidity in [(yesterday, 10.0, 50.0), (today, 7.0, 72.5)]
    ]
    _serve(
        monkeypatch,
        {
            "/v1/service/exports/locations": _pages(
                locations, source_collected_at=None, source_status="stale"
            ),
            "/v1/service/exports/current": _pages(current),
            "/v1/service/exports/forecasts": _pages(forecasts),
            "/v1/service/exports/daily-summaries": _pages(daily),
        },
    )

    # 적재 전: 위치가 없으면 503 NOT_LOADED.
    early = await api.get("/v1/service/weather/nearest", params={"lon": 126.98, "lat": 37.57})
    assert early.status_code == 503
    assert early.json()["code"] == "WEATHER_STATE_NOT_LOADED"

    loaded = await _load(store, DATASET_LOCATIONS)
    assert loaded["count"] == 3
    assert loaded["geo_count"] == 3
    assert loaded["pages"] == 2
    await _load(store, DATASET_CURRENT)
    await _load(store, DATASET_FORECAST_SHORT)
    await _load(store, DATASET_DAILY_SUMMARIES)

    response = await api.get(
        "/v1/service/weather/nearest",
        params={"lon": 126.98, "lat": 37.57, "forecast_styles": ["short", "mid"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    seoul_id = weather_location_feature_id("seoul")
    assert data["location"]["feature_id"] == seoul_id
    assert data["location"]["address"]["bjd_code"] == "1111010100"
    assert 0 < data["location"]["distance_m"] < 1_000
    # 위치 roster는 원천 수집 시각이 없다 — loaded_at 기준, weather가 늘 보내는 stale은 싣지 않는다.
    assert data["location_freshness"]["source_collected_at"] is None
    assert data["location_freshness"]["source_status"] is None
    assert data["location_freshness"]["stale"] is False

    assert data["current"]["status"] == "ok"
    assert {o["metric_key"] for o in data["current"]["observations"]} == {"T1H", "REH", "PTY"}
    assert data["current"]["freshness"]["source_status"] == "ok"

    short = data["forecasts"]["short"]
    assert short["status"] == "ok"
    (group,) = short["groups"]
    assert len(group["target_at"]) == 2  # 지난 두 시각은 읽을 때 뗐다(W5)
    assert group["metrics"] == {"TMP": [11.0, 12.0], "SKY": ["3", None]}
    assert data["forecasts"]["mid"]["status"] == "not_loaded"
    assert data["forecasts"]["ultra_short"] is None  # 고르지 않은 style

    slots = data["daily_summaries"]["slots"]
    assert [s["date"] for s in slots] == [yesterday.isoformat(), today.isoformat()]
    assert slots[0]["vs_previous_day"] is None
    assert slots[1]["vs_previous_day"]["temp_avg_delta"] == -3.0
    assert slots[1]["vs_previous_day"]["humidity_avg_delta"] == 22.5

    # 같은 묶음을 id로 — sections로 부분만.
    detail = await api.get(
        f"/v1/service/weather/locations/{weather_location_feature_id('busan')}",
        params={"sections": ["forecasts"]},
    )
    assert detail.status_code == 200, detail.text
    detail_data = detail.json()["data"]
    assert detail_data["current"] is None
    assert detail_data["daily_summaries"] is None
    assert detail_data["forecasts"]["short"]["groups"][0]["metrics"] == {"TMP": [18.0]}
    jeju = await api.get(f"/v1/service/weather/locations/{weather_location_feature_id('jeju')}")
    assert jeju.json()["data"]["current"]["status"] == "no_data"
    missing = await api.get("/v1/service/weather/locations/f_global_w_0000000000000000")
    assert missing.status_code == 404

    # 목록 순회 + 최신 관측 붙이기.
    first = await api.get(
        "/v1/service/weather/locations", params={"limit": 2, "include_current": "true"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    seen = [item["feature_id"] for item in body["data"]["items"]]
    cursor = body["meta"]["page"]["next_cursor"]
    assert cursor
    rest = await api.get("/v1/service/weather/locations", params={"limit": 2, "cursor": cursor})
    seen += [item["feature_id"] for item in rest.json()["data"]["items"]]
    everyone = ("seoul", "busan", "jeju")
    assert sorted(seen) == sorted(weather_location_feature_id(i) for i in everyone)
    attached = {item["feature_id"]: item["observations"] for item in body["data"]["items"]}
    if seoul_id in attached:
        assert attached[seoul_id] is not None
    assert body["data"]["current_freshness"]["dataset"] == DATASET_CURRENT.name

    near_busan = await api.get(
        "/v1/service/weather/locations",
        params={"lon": 129.08, "lat": 35.18, "radius_m": 5_000},
    )
    assert [i["feature_id"] for i in near_busan.json()["data"]["items"]] == [
        weather_location_feature_id("busan")
    ]
    far = await api.get(
        "/v1/service/weather/nearest", params={"lon": 131.0, "lat": 37.0, "radius_m": 1_000}
    )
    assert far.status_code == 404

    status = (await api.get("/v1/service/weather/status")).json()["data"]
    loaded_names = {d["dataset"] for d in status["datasets"] if d["loaded"]}
    assert loaded_names == {
        DATASET_LOCATIONS.name,
        DATASET_CURRENT.name,
        DATASET_FORECAST_SHORT.name,
        DATASET_DAILY_SUMMARIES.name,
    }
    assert len(status["datasets"]) == 7


async def test_shrunken_location_roster_is_not_swapped(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dagster import Failure

    full = [_location(f"l{i}", 127.0 + i * 0.01, 37.5) for i in range(6)]
    _serve(monkeypatch, {"/v1/service/exports/locations": _pages(full)})
    first = await _load(store, DATASET_LOCATIONS)
    assert first["count"] == 6
    _serve(monkeypatch, {"/v1/service/exports/locations": _pages(full[:2])})
    with pytest.raises(Failure) as excinfo:
        await _load(store, DATASET_LOCATIONS)
    assert str(excinfo.value.metadata["failure_kind"].value) == "state_swap_refused"
    assert (await store.current_meta(DATASET_LOCATIONS.name)).count == 6
    # 운영자 override 한 번이면 받아들이고 기록한다.
    shrunk = await _load(store, DATASET_LOCATIONS, allow_shrink=True)
    assert shrunk["count"] == 2
    assert shrunk["guard_override"] is True
    meta = await store.current_meta(DATASET_LOCATIONS.name)
    assert meta.source_status == "ok"


def _kma_group(location_id: str, hours: tuple[int, ...]) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "location_id": location_id,
        "provider": "python-kma-api",
        "forecast_style": "short",
        "known_at": now.isoformat(),
        "published_at": now.isoformat(),
        "target_at": [(now + timedelta(hours=h)).isoformat() for h in hours],
        "metrics": {"TMP": [float(h) for h in hours]},
    }


def _air_value(location_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "location_id": location_id,
        "provider": "python-airkorea-api",
        "metric_key": "PM10",
        "value": 31.0,
        "unit": "ug/m3",
        "target_at": (now - timedelta(minutes=30)).isoformat(),
        "known_at": (now - timedelta(minutes=20)).isoformat(),
        "forecast_style": "observed",
    }


async def test_nearest_takes_each_section_from_the_nearest_location_with_data(
    store: ValkeyStateStore, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """가장 가까운 대기질 측정소에는 예보가 없다 — 예보는 다음으로 가까운 KMA 격자에서 온다."""
    locations = [
        _location("air-1", 127.000, 37.500),  # 요청 좌표 바로 옆 대기질 측정소
        _location("kma-1", 127.020, 37.500),  # 약 1.8 km 떨어진 KMA 격자
        _location("kma-far", 127.400, 37.500),
    ]
    _serve(
        monkeypatch,
        {
            "/v1/service/exports/locations": _pages(locations),
            "/v1/service/exports/current": _pages([_air_value("air-1")]),
            "/v1/service/exports/forecasts": _pages(
                [_kma_group("kma-1", (1, 2, 30)), _kma_group("kma-far", (1,))]
            ),
        },
    )
    await _load(store, DATASET_LOCATIONS)
    await _load(store, DATASET_CURRENT)
    await _load(store, DATASET_FORECAST_SHORT)

    response = await api.get(
        "/v1/service/weather/nearest",
        params={"lon": 127.0001, "lat": 37.5, "radius_m": 100_000, "forecast_styles": "short"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["location"]["location_id"] == "air-1"
    assert data["current"]["source"]["location_id"] == "air-1"
    short = data["forecasts"]["short"]
    assert short["status"] == "ok"
    assert short["source"]["location_id"] == "kma-1"
    assert 1_000 < short["source"]["distance_m"] < 3_000
    assert data["daily_summaries"]["status"] == "not_loaded"
    assert data["daily_summaries"]["source"] is None

    # 시간 창 — 3시간 안만.
    windowed = await api.get(
        "/v1/service/weather/nearest",
        params={
            "lon": 127.0001,
            "lat": 37.5,
            "forecast_styles": "short",
            "to": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        },
    )
    (group,) = windowed.json()["data"]["forecasts"]["short"]["groups"]
    assert group["metrics"]["TMP"] == [1.0, 2.0]

    # 배치 — feature_id와 weather location_id를 함께, 없는 id는 missing.
    batch = await api.post(
        "/v1/service/weather/locations/batch",
        json={
            "feature_ids": [weather_location_feature_id("air-1"), "f_global_w_0000000000000000"],
            "location_ids": ["kma-1", "nope"],
            "sections": ["forecasts"],
            "forecast_styles": ["short"],
        },
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()["data"]
    assert [item["location"]["location_id"] for item in body["items"]] == ["air-1", "kma-1"]
    assert body["items"][0]["forecasts"]["short"]["status"] == "no_data"  # 배치는 그 위치 그대로
    assert body["items"][1]["forecasts"]["short"]["source"]["location_id"] == "kma-1"
    assert body["missing"] == [
        {"feature_id": "f_global_w_0000000000000000", "location_id": None},
        {"feature_id": None, "location_id": "nope"},
    ]


async def test_broken_stored_value_is_reported_as_unavailable(
    store: ValkeyStateStore, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra.valkey_state import state_key

    _serve(
        monkeypatch,
        {
            "/v1/service/exports/locations": _pages([_location("a", 127.0, 37.5)]),
            "/v1/service/exports/current": _pages([_air_value("a")]),
        },
    )
    await _load(store, DATASET_LOCATIONS)
    await _load(store, DATASET_CURRENT)
    meta = await store.current_meta(DATASET_CURRENT.name)
    feature_id = weather_location_feature_id("a")
    await store.client.hset(
        state_key(DATASET_CURRENT.name, meta.generation, "items"), feature_id, b'{"x": 1}'
    )
    response = await api.get(f"/v1/service/weather/locations/{feature_id}")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["current"]["status"] == "unavailable"


async def test_not_modified_reload_keeps_the_generation_and_records_the_check(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, {"/v1/service/exports/locations": _pages([_location("a", 127.0, 37.5)])})
    _ETAGS["/v1/service/exports/locations"] = 'W/"roster-1"'
    first = await _load(store, DATASET_LOCATIONS)
    meta = await store.current_meta(DATASET_LOCATIONS.name)
    assert meta.source_etag == 'W/"roster-1"'
    assert meta.checked_at is None
    second = await _load(store, DATASET_LOCATIONS)
    assert second["unchanged"] == "not_modified"
    assert second["checked"] is True
    after = await store.current_meta(DATASET_LOCATIONS.name)
    assert after.generation == first["generation"]
    assert after.checked_at is not None
    assert after.loaded_at == meta.loaded_at
