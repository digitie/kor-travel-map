"""``/v1/service/transport/*`` — Valkey 없이 재는 계약(ADR-114 D6).

실제 Valkey로 재는 교체·GEO·순회·REST 왕복은
``tests/integration/test_valkey_transport_state.py``가 소유한다. 여기서는 표면 등록·인증 정책·입력
검증·Valkey 미설정 503·가격 추이 프록시의 실패 분류를 본다.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import ROUTE_POLICIES, RoutePolicy
from kortravelmap.api.routers.service_transport import _encode_cursor, bbox_search_box
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.transport_state_service import (
    fetch_price_history,
    get_state_store,
    set_state_store_for_test,
)

pytestmark = pytest.mark.unit

_PATHS = (
    "/v1/service/transport/fuel-stations",
    "/v1/service/transport/fuel-stations/{feature_id}",
    "/v1/service/transport/fuel-stations/{feature_id}/price-history",
    "/v1/service/transport/rest-areas",
    "/v1/service/transport/rest-areas/{feature_id}",
    "/v1/service/transport/highway-incidents",
    "/v1/service/transport/highway-incidents/{feature_id}",
    "/v1/service/transport/airports",
    "/v1/service/transport/airports/{feature_id}",
    "/v1/service/transport/status",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    set_state_store_for_test(None)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    yield TestClient(app)
    set_state_store_for_test(None)


def test_every_route_is_a_get_on_the_service_surface(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in _PATHS:
        assert set(spec["paths"][path]) == {"get"}, path
        assert ROUTE_POLICIES[path] is RoutePolicy.SERVICE, path


def test_missing_valkey_url_is_503_for_this_surface_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KOR_TRAVEL_MAP_VALKEY_URL", raising=False)
    response = client.get("/v1/service/transport/fuel-stations")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "TRANSPORT_STATE_UNAVAILABLE"
    assert "KOR_TRAVEL_MAP_VALKEY_URL" in body["detail"]
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"lon": 127.0, "lat": 37.5},
        {"min_lon": 127.0, "min_lat": 37.0, "max_lon": 128.0},
        {"lon": 127.0, "lat": 37.5, "radius_m": 10, "min_lon": 1, "min_lat": 1,
         "max_lon": 2, "max_lat": 2},
        {"lon": 127.0, "lat": 37.5, "radius_m": 10, "cursor": "abc"},
        {"min_lon": 128.0, "min_lat": 37.0, "max_lon": 127.0, "max_lat": 38.0},
        {"lon": 127.0, "lat": 37.5, "radius_m": 50_001},
        {"limit": 501},
        {"lon": 127.0, "lat": 89.0, "radius_m": 10},
        {"min_lon": 127.0, "min_lat": 37.0, "max_lon": 128.0, "max_lat": 86.0},
    ],
)
def test_query_shape_is_validated_before_touching_the_store(
    client: TestClient, params: dict[str, Any]
) -> None:
    class _Untouchable:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"store를 건드렸다: {name}")

    client.app.dependency_overrides[get_state_store] = _Untouchable  # type: ignore[attr-defined]
    response = client.get("/v1/service/transport/highway-incidents", params=params)
    assert response.status_code == 422, response.text


def test_garbage_cursor_is_422(client: TestClient) -> None:
    class _Untouchable:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"store를 건드렸다: {name}")

    client.app.dependency_overrides[get_state_store] = _Untouchable  # type: ignore[attr-defined]
    for cursor in ("%%%", "", _encode_cursor("transport.fuel_stations", "g-1", "f_global_p_1")):
        response = client.get("/v1/service/transport/airports", params={"cursor": cursor})
        assert response.status_code == 422, cursor


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_372_797.560856
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


@pytest.mark.parametrize(
    "bbox",
    [(125.0, 33.0, 130.0, 38.6), (126.9, 37.4, 127.1, 37.6), (-10.0, -5.0, 10.0, 5.0)],
)
def test_bbox_search_box_reaches_every_corner_along_its_own_parallel(
    bbox: tuple[float, float, float, float],
) -> None:
    """Valkey BYBOX는 점의 위도에서 동서 거리를 잰다 — 네 모서리 모두 반폭 안이어야 한다."""
    min_lon, min_lat, max_lon, max_lat = bbox
    center_lon, center_lat, width, height = bbox_search_box(*bbox)
    for lon in (min_lon, max_lon):
        for lat in (min_lat, max_lat):
            assert _haversine(center_lon, lat, lon, lat) <= width / 2, (lon, lat)
            assert _haversine(center_lon, center_lat, center_lon, lat) <= height / 2


# -- 가격 추이 프록시 ------------------------------------------------------------------

_ENABLED = KorTravelMapSettings.model_construct(
    transport_price_history_enabled=True,
    transport_price_history_timeout_seconds=2.0,
    kor_travel_transport_base_url="http://transport.test/",
    kor_travel_transport_service_token=SecretStr("s" * 40),
    kor_travel_transport_connect_timeout_seconds=1.0,
)
_HISTORY = {
    "generated_at": "2026-10-23T03:00:00Z",
    "natural_key": "A0000001",
    "items": [
        {
            "product_code": "B027",
            "price": 1689.0,
            "provider_updated_at": "2026-10-22T01:00:00Z",
            "observed_at": "2026-10-22T01:00:00Z",
            "collected_at": "2026-10-23T02:00:00Z",
        },
        {
            "product_code": "B027",
            "price": None,
            "provider_updated_at": None,
            "observed_at": "2026-10-20T01:00:00Z",
            "collected_at": "2026-10-20T02:00:00Z",
        },
    ],
    "truncated": True,
}


async def _fetch(handler: Any, settings: KorTravelMapSettings = _ENABLED) -> Any:
    return await fetch_price_history(
        settings,
        "A0000001",
        params={"limit": "10"},
        transport=httpx.MockTransport(handler),
    )


async def test_price_history_success_is_parsed_strictly() -> None:
    seen: list[httpx.Request] = []

    def _ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_HISTORY)

    outcome = await _fetch(_ok)
    assert outcome.reason is None
    assert outcome.history.truncated is True
    assert [p.price for p in outcome.history.items] == [1689, None]
    assert outcome.history.generated_at == datetime(2026, 10, 23, 3, tzinfo=UTC)
    assert seen[0].url == httpx.URL(
        "http://transport.test/v1/service/exports/fuel-stations/A0000001/price-history?limit=10"
    )


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(404, json={"detail": "Not Found"}), "upstream_not_found"),
        (httpx.Response(503, json={}), "upstream_unavailable"),
        (httpx.Response(502, text="bad gateway"), "upstream_unavailable"),
        (httpx.Response(422, json={}), "upstream_rejected"),
        (httpx.Response(200, text="<html>"), "upstream_contract"),
        (httpx.Response(200, json={**_HISTORY, "natural_key": "B0000002"}), "upstream_contract"),
        (httpx.Response(200, json={**_HISTORY, "truncated": "yes"}), "upstream_contract"),
    ],
)
async def test_price_history_failures_degrade_to_unavailable(
    response: httpx.Response, reason: str
) -> None:
    outcome = await _fetch(lambda _request: response)
    assert (outcome.history, outcome.reason) == (None, reason)


async def test_price_history_transport_errors_are_unavailable() -> None:
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("odroid가 꺼졌다", request=request)

    outcome = await _fetch(_timeout)
    assert (outcome.history, outcome.reason) == (None, "upstream_unavailable")


async def test_price_history_flag_and_configuration_gate_the_call() -> None:
    def _never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청하면 안 된다")

    disabled = _ENABLED.model_copy(update={"transport_price_history_enabled": False})
    assert (await _fetch(_never, disabled)).reason == "disabled"
    blank = _ENABLED.model_copy(update={"kor_travel_transport_service_token": SecretStr("  ")})
    assert (await _fetch(_never, blank)).reason == "not_configured"
    no_url = _ENABLED.model_copy(update={"kor_travel_transport_base_url": None})
    assert (await _fetch(_never, no_url)).reason == "not_configured"
