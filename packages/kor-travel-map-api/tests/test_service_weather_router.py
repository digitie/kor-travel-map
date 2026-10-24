"""``/v1/service/weather/*`` — Valkey 없이 재는 계약(ADR-114 2단계 W5·W7).

실제 Valkey로 재는 적재·근처·묶음 왕복은 ``tests/integration/test_valkey_weather_state.py``가
소유한다. 여기서는 표면 등록·인증 정책·입력 검증·Valkey 미설정 503과 순수 함수(지난 예보 시각
제거·전날 대비)를 본다.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.dto.weather_state import (
    WeatherCurrentState,
    WeatherDailySlotState,
    WeatherForecastGroupState,
    daily_slot_bounds,
)
from kortravelmap.infra.valkey_state import DatasetRead

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import ROUTE_POLICIES, RoutePolicy
from kortravelmap.api.routers.service_weather import (
    _BrokenValue,
    _Candidate,
    _pick,
    future_groups,
    get_weather_state_store,
    slot_is_partial,
    with_previous_day,
)
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.transport_state_service import set_state_store_for_test

pytestmark = pytest.mark.unit

_PATHS = {
    "/v1/service/weather/locations": {"get"},
    "/v1/service/weather/locations/batch": {"post"},
    "/v1/service/weather/locations/{feature_id}": {"get"},
    "/v1/service/weather/nearest": {"get"},
    "/v1/service/weather/status": {"get"},
}
KST = dt.timezone(dt.timedelta(hours=9))
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
    for path, methods in _PATHS.items():
        assert set(spec["paths"][path]) == methods, path
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
        ("/v1/service/weather/nearest", {"lon": 127.0, "lat": 37.5, "radius_m": 100_001}),
        ("/v1/service/weather/locations", {"lon": 127.0, "lat": 37.5, "radius_m": 100_001}),
        (
            "/v1/service/weather/nearest",
            {"lon": 127.0, "lat": 37.5, "from": "2026-10-25T00:00:00+09:00",
             "to": "2026-10-24T00:00:00+09:00"},
        ),
        ("/v1/service/weather/locations/f_global_w_x", {"from": "2026-10-25T00:00:00"}),
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


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"feature_ids": []},
        {"feature_ids": [f"f_global_w_{i}" for i in range(51)]},
        {"feature_ids": ["a", "a"]},
        {"feature_ids": ["a"], "location_ids": [f"l{i}" for i in range(50)]},
        {"feature_ids": ["a"], "sections": ["weather"]},
        {
            "feature_ids": ["a"],
            "forecast_from": "2026-10-25T00:00:00+09:00",
            "forecast_to": "2026-10-24T00:00:00+09:00",
        },
    ],
)
def test_batch_body_is_validated_before_touching_the_store(
    client: TestClient, body: dict[str, Any]
) -> None:
    _forbid_store(client)
    response = client.post("/v1/service/weather/locations/batch", json=body)
    assert response.status_code == 422, response.text


def test_hundred_km_radius_is_accepted_for_weather(client: TestClient) -> None:
    calls: list[str] = []

    class _NotLoaded:
        async def current_meta(self, dataset: str) -> Any:
            from kortravelmap.infra.valkey_state import StateNotLoaded

            calls.append(dataset)
            raise StateNotLoaded(dataset)

    overrides: dict[Any, Any] = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_weather_state_store] = _NotLoaded
    response = client.get(
        "/v1/service/weather/nearest", params={"lon": 127.0, "lat": 37.5, "radius_m": 100_000}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "WEATHER_STATE_NOT_LOADED"
    assert calls == ["weather.locations"]


def test_transport_cursor_is_rejected_by_the_weather_listing(client: TestClient) -> None:
    from kortravelmap.api.routers.service_transport import _encode_cursor

    _forbid_store(client)
    cursor = _encode_cursor("transport.airports", "g-1", "f_global_p_1")
    # weather 위치 데이터셋의 것만 받는다 — 다른 데이터셋 이름이면 422.
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


def test_future_groups_honour_an_upper_bound() -> None:
    (group,) = future_groups([_group([0, 1, 2, 3])], NOW, until=NOW + timedelta(hours=2))
    assert group.target_at == [NOW + timedelta(hours=h) for h in (0, 1, 2)]


def _slot(
    day: int,
    slot: str,
    *,
    temp: float | None,
    humidity: float | None,
    samples: int = 6,
    partial: bool = False,
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
        partial=partial,
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
    late = datetime(2026, 10, 25, 12, 0, tzinfo=KST)  # 모든 구간이 끝난 뒤
    out = {(s.date.day, s.slot): s for s in with_previous_day(slots, late)}
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


@pytest.mark.parametrize(
    ("hour", "minute", "partial"),
    [
        (4, 59, {"morning": True, "noon": True, "evening": True}),
        (5, 0, {"morning": True, "noon": True, "evening": True}),
        (10, 59, {"morning": True, "noon": True, "evening": True}),
        (11, 0, {"morning": False, "noon": True, "evening": True}),
        (17, 0, {"morning": False, "noon": False, "evening": True}),
        (22, 59, {"morning": False, "noon": False, "evening": True}),
        (23, 0, {"morning": False, "noon": False, "evening": False}),
    ],
)
def test_partial_is_recomputed_from_the_kst_slot_end(
    hour: int, minute: int, partial: dict[str, bool]
) -> None:
    now = datetime(2026, 10, 24, hour, minute, tzinfo=KST)
    for slot, expected in partial.items():
        stored = _slot(24, slot, temp=10.0, humidity=50.0, partial=False)
        assert slot_is_partial(stored, now) is expected, (hour, minute, slot)
        assert slot_is_partial(stored, now.astimezone(UTC)) is expected  # 시간대 무관


def test_slot_bounds_are_kst() -> None:
    start, end = daily_slot_bounds(date(2026, 10, 24), "evening")
    assert start.astimezone(UTC) == datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


def test_finished_slot_loaded_mid_slot_stays_partial_until_reloaded() -> None:
    # 10:30에 적재된 아침 요약은 12:00에 읽어도 10:30까지만 모은 값이다.
    stored = _slot(24, "morning", temp=10.0, humidity=50.0, partial=True)
    assert slot_is_partial(stored, datetime(2026, 10, 24, 12, 0, tzinfo=KST)) is True


def test_morning_at_0630_is_not_compared_with_yesterday() -> None:
    now = datetime(2026, 10, 24, 6, 30, tzinfo=KST)
    slots = [
        _slot(23, "morning", temp=12.0, humidity=50.0),
        _slot(23, "evening", temp=10.0, humidity=60.0),
        _slot(24, "morning", temp=7.0, humidity=80.0, samples=1, partial=True),
    ]
    out = {(s.date.day, s.slot): s for s in with_previous_day(slots, now)}
    today = out[(24, "morning")]
    assert today.partial is True
    assert today.vs_previous_day is None  # 1시간 반 치를 어제 6시간 치와 비교하지 않는다
    assert out[(23, "morning")].partial is False
    # 서버가 적재 때 준 값과 무관하게 읽는 시각으로 다시 계산한다.
    fresh = with_previous_day([_slot(24, "noon", temp=1.0, humidity=1.0, partial=False)], now)
    assert fresh[0].partial is True


def _candidate(feature_id: str) -> Any:
    from kortravelmap.api.routers.service_weather import WeatherLocationOut

    location = WeatherLocationOut(
        feature_id=feature_id,
        category="99000000",
        marker_icon="weather",
        marker_color="P-01",
        location_id=feature_id,
        name=feature_id,
        coord=None,
        address={},
    )
    return _Candidate(location, None)


def _current(feature_id: str, observations: int) -> bytes:
    return WeatherCurrentState(
        feature_id=feature_id,
        location_id=feature_id,
        observations=[
            {
                "provider": "python-kma-api",
                "metric_key": f"M{i}",
                "value": 1.0,
                "unit": None,
                "target_at": NOW,
                "known_at": NOW,
                "forecast_style": "observed",
            }
            for i in range(observations)
        ],
    ).model_dump_json().encode()


def _usable(value: Any) -> Any:
    return list(value.observations) or None


def test_broken_stored_value_is_unavailable_not_no_data() -> None:
    read = DatasetRead("weather.current", "ok", None, [b'{"not": "a state"}'])
    status, chosen, _ = _pick(read, [_candidate("a")], WeatherCurrentState, _usable)
    assert (status, chosen) == ("unavailable", None)
    missing = DatasetRead("weather.current", "ok", None, [None])
    assert _pick(missing, [_candidate("a")], WeatherCurrentState, _usable)[0] == "no_data"
    assert isinstance(_BrokenValue(), _BrokenValue)


def test_pick_skips_candidates_without_usable_data() -> None:
    candidates = [_candidate("near"), _candidate("broken"), _candidate("far")]
    read = DatasetRead(
        "weather.current", "ok", None, [_current("near", 0), b"{", _current("far", 2)]
    )
    status, chosen, observations = _pick(read, candidates, WeatherCurrentState, _usable)
    assert status == "ok"
    assert chosen is candidates[2]
    assert len(observations) == 2
    assert _pick(
        DatasetRead("weather.current", "not_loaded", None, [None] * 3),
        candidates,
        WeatherCurrentState,
        _usable,
    )[0] == "not_loaded"
