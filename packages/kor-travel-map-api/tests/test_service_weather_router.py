"""``/v1/service/weather/*`` — Valkey 없이 재는 계약(ADR-114 2단계 W5·W7).

실제 Valkey로 재는 적재·근처·묶음 왕복은 ``tests/integration/test_valkey_weather_state.py``가
소유한다. 여기서는 표면 등록·인증 정책·입력 검증·Valkey 미설정 503과 순수 함수(지난 예보 시각
제거·전날 대비)를 본다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.dto.weather_state import WeatherDailySlotState, WeatherForecastGroupState

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import ROUTE_POLICIES, RoutePolicy
from kortravelmap.api.routers.service_weather import (
    future_groups,
    get_weather_state_store,
    with_previous_day,
)
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.transport_state_service import set_state_store_for_test

pytestmark = pytest.mark.unit

_PATHS = (
    "/v1/service/weather/locations",
    "/v1/service/weather/locations/{feature_id}",
    "/v1/service/weather/nearest",
    "/v1/service/weather/status",
)
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    set_state_store_for_test(None)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    yield TestClient(app)
    set_state_store_for_test(None)


class _Untouchable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"store를 건드렸다: {name}")


def _forbid_store(client: TestClient) -> None:
    overrides: dict[Any, Any] = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_weather_state_store] = _Untouchable


def test_every_route_is_a_get_on_the_service_surface(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in _PATHS:
        assert set(spec["paths"][path]) == {"get"}, path
        assert ROUTE_POLICIES[path] is RoutePolicy.SERVICE, path


def test_missing_valkey_url_is_503_for_this_surface_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_VALKEY_URL", raising=False)
    for path in ("/v1/service/weather/locations", "/v1/service/weather/status"):
        response = client.get(path)
        assert response.status_code == 503, path
        body = response.json()
        assert body["code"] == "WEATHER_STATE_UNAVAILABLE"
        assert "KOR_TRAVEL_MAP_VALKEY_URL" in body["detail"]
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/service/weather/locations", {"lon": 127.0, "lat": 37.5}),
        ("/v1/service/weather/locations", {"limit": 501}),
        ("/v1/service/weather/locations", {"lon": 127.0, "lat": 37.5, "radius_m": 10,
                                           "cursor": "abc"}),
        ("/v1/service/weather/nearest", {"lon": 127.0}),
        ("/v1/service/weather/nearest", {"lon": 127.0, "lat": 37.5, "radius_m": 50_001}),
        ("/v1/service/weather/nearest", {"lon": 127.0, "lat": 89.0}),
        ("/v1/service/weather/nearest", {"lon": 127.0, "lat": 37.5, "sections": "weather"}),
        ("/v1/service/weather/locations/f_global_w_x", {"forecast_styles": "daily"}),
        ("/v1/service/weather/locations/bad%20id", {}),
    ],
)
def test_query_shape_is_validated_before_touching_the_store(
    client: TestClient, path: str, params: dict[str, Any]
) -> None:
    _forbid_store(client)
    response = client.get(path, params=params)
    assert response.status_code == 422, response.text


def test_transport_cursor_is_rejected_by_the_weather_listing(client: TestClient) -> None:
    from kortravelmap.api.routers.service_transport import _encode_cursor

    _forbid_store(client)
    cursor = _encode_cursor("transport.airports", "g-1", "f_global_p_1")
    response = client.get("/v1/service/weather/locations", params={"cursor": cursor})
    assert response.status_code == 422


# -- 순수 함수 ---------------------------------------------------------------------------


def _group(hours: list[int]) -> WeatherForecastGroupState:
    return WeatherForecastGroupState(
        provider="python-kma-api",
        known_at=NOW - timedelta(hours=3),
        published_at=NOW - timedelta(hours=3),
        target_at=[NOW + timedelta(hours=h) for h in hours],
        metrics={"TMP": [float(h) for h in hours], "SKY": [f"s{h}" for h in hours]},
    )


def test_future_groups_drop_past_targets_and_their_values() -> None:
    kept = future_groups([_group([-2, -1, 0, 1, 2]), _group([-3, -1])], NOW)
    assert len(kept) == 1  # 모두 지난 묶음은 빠진다
    (group,) = kept
    assert group.target_at == [NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2)]
    assert group.metrics == {"TMP": [0.0, 1.0, 2.0], "SKY": ["s0", "s1", "s2"]}


def test_future_groups_keep_untouched_groups_as_is() -> None:
    group = _group([1, 2])
    assert future_groups([group], NOW) == [group]


def _slot(day: int, slot: str, *, temp: float | None, humidity: float | None, samples: int = 6
          ) -> WeatherDailySlotState:
    return WeatherDailySlotState(
        date=date(2026, 10, day),
        slot=slot,  # type: ignore[arg-type]
        temp_min=None if temp is None else temp - 2,
        temp_max=None if temp is None else temp + 2,
        temp_avg=temp,
        humidity_avg=humidity,
        sample_count=samples,
        source_providers=["python-kma-api"],
        partial=False,
    )


def test_previous_day_delta_compares_the_same_slot() -> None:
    slots = [
        _slot(22, "morning", temp=10.0, humidity=50.0),
        _slot(22, "noon", temp=15.0, humidity=40.0),
        _slot(23, "morning", temp=7.5, humidity=70.0),
        _slot(23, "noon", temp=None, humidity=45.0),
        _slot(23, "evening", temp=9.0, humidity=60.0),
        _slot(24, "morning", temp=8.0, humidity=None, samples=0),
    ]
    out = {(s.date.day, s.slot): s for s in with_previous_day(slots)}
    assert out[(22, "morning")].vs_previous_day is None  # 전날 없음
    colder = out[(23, "morning")].vs_previous_day
    assert colder is not None
    assert colder.previous_date == date(2026, 10, 22)
    assert colder.temp_avg_delta == -2.5
    assert colder.humidity_avg_delta == 20.0
    noon = out[(23, "noon")].vs_previous_day
    assert noon is not None
    assert noon.temp_avg_delta is None  # 이쪽 값이 없다
    assert noon.humidity_avg_delta == 5.0
    assert out[(23, "evening")].vs_previous_day is None  # 전날 저녁 없음
    assert out[(24, "morning")].vs_previous_day is None  # 관측 0
