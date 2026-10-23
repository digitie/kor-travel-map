"""``/v1/service/transport/*`` — Valkey 없이 재는 계약(ADR-114 D6).

실제 Valkey로 재는 교체·GEO·순회·REST 왕복은
``tests/integration/test_valkey_transport_state.py``가 소유한다. 여기서는 표면 등록·인증 정책·입력
검증·Valkey 미설정 503·가격 추이 프록시(transport T4 질의 변환·실제 응답 모양·cursor 두
페이지·409/422/501/timeout·주유소 불일치·플래그·현재가 보존)를 본다.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, get_args

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.dto.transport_state import FuelPriceState, FuelStationState, StateAddress
from kortravelmap.infra.valkey_state import GenerationMeta
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import ROUTE_POLICIES, RoutePolicy
from kortravelmap.api.routers.service_transport import _encode_cursor, bbox_search_box
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.transport_state_service import (
    PriceHistoryUnavailableReason,
    fetch_price_history,
    get_state_store,
    price_history_params,
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
        {"min_lon": 120.0, "min_lat": 30.0, "max_lon": 135.0, "max_lat": 45.0},
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


# -- 가격 추이 프록시(transport T4) -----------------------------------------------------

_ENABLED = KorTravelMapSettings.model_construct(
    transport_price_history_enabled=True,
    transport_price_history_timeout_seconds=2.0,
    kor_travel_transport_base_url="http://transport.test/",
    kor_travel_transport_service_token=SecretStr("s" * 40),
    kor_travel_transport_connect_timeout_seconds=1.0,
)
_STATION_KEY = "A0000001"


def _page(
    items: list[dict[str, Any]] | None = None,
    *,
    station_key: str = _STATION_KEY,
    status: str = "ok",
    next_cursor: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """transport ``FuelPriceHistoryExportPage`` 실제 모양(``docs/map-service-price-history.md``)."""
    rows = (
        [
            {"product_code": "B027", "observed_at": "2026-10-22T00:00:00Z", "price": 1700.0},
            {"product_code": "D047", "observed_at": "2026-10-21T00:00:00Z", "price": None},
        ]
        if items is None
        else items
    )
    body: dict[str, Any] = {
        "meta": {
            "generated_at": "2026-10-23T00:00:01Z",
            "source_collected_at": "2026-10-21T00:49:20.470379Z",
            "source_status": status,
            "item_count": len(rows),
        },
        "station_key": station_key,
        "items": rows,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }
    body.update(overrides)
    return body


def _without_meta() -> dict[str, Any]:
    body = _page()
    del body["meta"]
    return body


def _with_meta(**changes: Any) -> dict[str, Any]:
    body = _page()
    body["meta"] = {**body["meta"], **changes}
    return body


async def _fetch(
    handler: Any,
    settings: KorTravelMapSettings = _ENABLED,
    *,
    params: dict[str, str] | None = None,
) -> Any:
    return await fetch_price_history(
        settings,
        _STATION_KEY,
        params={"limit": "10"} if params is None else params,
        transport=httpx.MockTransport(handler),
    )


def test_public_params_translate_to_transport_t4_names() -> None:
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=9)))
    assert price_history_params(
        product_code="B027", since=since, until=until, limit=200, cursor="opaque"
    ) == {
        "product": "B027",
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-23T09:00:00+09:00",
        "limit": "200",
        "cursor": "opaque",
    }
    assert price_history_params(product_code=None, since=None, until=None, limit=5) == {
        "limit": "5"
    }


async def test_price_history_success_sends_t4_query_and_parses_the_real_shape() -> None:
    seen: list[httpx.Request] = []

    def _ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page(status="stale"))

    params = price_history_params(
        product_code="B027",
        since=datetime(2026, 10, 1, tzinfo=UTC),
        until=datetime(2026, 10, 23, tzinfo=UTC),
        limit=200,
        cursor="c-1",
    )
    outcome = await _fetch(_ok, params=params)
    assert outcome.reason is None
    history = outcome.history
    assert history.station_key == _STATION_KEY
    assert history.generated_at == datetime(2026, 10, 23, 0, 0, 1, tzinfo=UTC)
    assert history.source_status == "stale"
    assert history.source_collected_at == datetime(2026, 10, 21, 0, 49, 20, 470379, tzinfo=UTC)
    assert (history.has_more, history.next_cursor) == (False, None)
    # null 가격은 그대로, 원천이 주지 않는 행별 시각은 None(응답 시각으로 채우지 않는다).
    assert [(p.product_code, p.price) for p in history.items] == [
        ("B027", Decimal("1700.0")),
        ("D047", None),
    ]
    assert all(p.collected_at is None and p.provider_updated_at is None for p in history.items)
    (request,) = seen
    assert request.url.path == f"/v1/service/exports/fuel-stations/{_STATION_KEY}/price-history"
    assert dict(request.url.params) == {
        "product": "B027",
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-23T00:00:00+00:00",
        "limit": "200",
        "cursor": "c-1",
    }
    assert request.headers["X-Kor-Travel-Transport-Service-Token"] == "s" * 40


_CURSOR_PARAMS = {"cursor": "c", "limit": "5"}


@pytest.mark.parametrize(
    ("response", "reason", "params"),
    [
        (httpx.Response(404, json={"detail": "Not Found"}), "upstream_not_found", None),
        (httpx.Response(501, json={"status": 501}), "upstream_unsupported", None),
        (httpx.Response(409, json={"status": 409}), "cursor_expired", _CURSOR_PARAMS),
        (httpx.Response(409, json={"status": 409}), "upstream_rejected", None),
        (httpx.Response(422, json={"status": 422}), "request_rejected", None),
        (httpx.Response(503, json={"status": 503}), "upstream_unavailable", None),
        (httpx.Response(502, text="bad gateway"), "upstream_unavailable", None),
        (httpx.Response(304), "upstream_rejected", None),
        (httpx.Response(200, text="<html>"), "upstream_contract", None),
    ],
)
async def test_price_history_failures_degrade_to_unavailable(
    response: httpx.Response, reason: str, params: dict[str, str] | None
) -> None:
    outcome = await _fetch(lambda _request: response, params=params)
    assert (outcome.history, outcome.reason) == (None, reason)


@pytest.mark.parametrize(
    "body",
    [
        _page(station_key="B0000002"),  # 요청과 다른 주유소
        # 옛 Map 가정 모양(natural_key·top-level generated_at·truncated)은 계약이 아니다.
        {
            "natural_key": _STATION_KEY,
            "generated_at": "2026-10-23T00:00:00Z",
            "items": [],
            "truncated": False,
        },
        _page(has_more=True),  # has_more인데 cursor 없음
        _page(next_cursor="c", has_more=False),
        _page(has_more="yes"),
        _page(status="unknown"),
        _with_meta(item_count=5),
        _with_meta(item_count=True),
        _with_meta(generated_at=None),
        _without_meta(),
        _page(
            [
                {"product_code": "B027", "observed_at": "2026-10-20T00:00:00Z", "price": 1.0},
                {"product_code": "B027", "observed_at": "2026-10-22T00:00:00Z", "price": 1.0},
            ]
        ),  # observed_at 내림차순 위반
        _page([{"product_code": "B027", "observed_at": "2026-10-20T00:00:00", "price": 1.0}]),
        _page([{"product_code": "B027", "observed_at": "2026-10-20T00:00:00Z", "price": "x"}]),
        _page([{"observed_at": "2026-10-20T00:00:00Z", "price": 1.0}]),
    ],
)
async def test_price_history_contract_violations_are_upstream_contract(
    body: dict[str, Any],
) -> None:
    outcome = await _fetch(lambda _request: httpx.Response(200, json=body))
    assert (outcome.history, outcome.reason) == (None, "upstream_contract")


async def test_price_history_timeout_and_connection_errors_are_distinct() -> None:
    def _read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("느리다", request=request)

    def _connect_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("odroid가 꺼졌다", request=request)

    def _refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (await _fetch(_read_timeout)).reason == "upstream_timeout"
    assert (await _fetch(_connect_timeout)).reason == "upstream_timeout"
    assert (await _fetch(_refused)).reason == "upstream_unavailable"


async def test_price_history_flag_and_configuration_gate_the_call() -> None:
    def _never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청하면 안 된다")

    disabled = _ENABLED.model_copy(update={"transport_price_history_enabled": False})
    assert (await _fetch(_never, disabled)).reason == "disabled"
    blank = _ENABLED.model_copy(update={"kor_travel_transport_service_token": SecretStr("  ")})
    assert (await _fetch(_never, blank)).reason == "not_configured"
    no_url = _ENABLED.model_copy(update={"kor_travel_transport_base_url": None})
    assert (await _fetch(_never, no_url)).reason == "not_configured"


async def test_price_history_bad_configuration_and_path_keys_never_raise() -> None:
    def _never(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청하면 안 된다")

    bad_url = _ENABLED.model_copy(update={"kor_travel_transport_base_url": "http://[x"})
    assert (await _fetch(_never, bad_url)).reason == "not_configured"
    for key in ("..", ".", "a/b"):
        outcome = await fetch_price_history(
            _ENABLED, key, params={}, transport=httpx.MockTransport(_never)
        )
        assert outcome.reason == "upstream_contract", key


# -- 가격 추이 route(가짜 store, 실제 router·응답 모델) ------------------------------------

_FEATURE_ID = "f_global_p_fuel1"
_STATION = FuelStationState(
    feature_id=_FEATURE_ID,
    category="fuel_station",
    marker_icon="fuel",
    marker_color="#000000",
    name="테스트 주유소",
    natural_key=_STATION_KEY,
    coord=None,
    address=StateAddress(),
    prices=[
        FuelPriceState(
            product_key="gasoline",
            product_code="B027",
            price=1689.0,
            collected_at=datetime(2026, 10, 23, tzinfo=UTC),
        )
    ],
    source_last_seen_at=datetime(2026, 10, 23, tzinfo=UTC),
)


class _FakeStore:
    async def current_meta(self, dataset: str) -> GenerationMeta:
        return GenerationMeta(
            dataset=dataset,
            generation="g-1",
            count=1,
            geo_count=0,
            lookup_count=0,
            duplicates=0,
            source_collected_at=datetime.now(UTC),
            loaded_at=datetime.now(UTC),
            run_id=None,
            guard_override=False,
        )

    async def get_values(self, dataset: str, generation: str, ids: list[str]) -> list[str | None]:
        return [_STATION.model_dump_json() if i == _FEATURE_ID else None for i in ids]


_URL = f"/v1/service/transport/fuel-stations/{_FEATURE_ID}/price-history"
_HistoryApi = tuple[TestClient, list[httpx.Request], dict[str, Any]]


@pytest.fixture
def history_api(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[_HistoryApi]:
    """route를 가짜 store + MockTransport transport로 돌린다. ``state["handler"]``를 바꿔 쓴다."""
    from kortravelmap.api.routers import service_transport

    seen: list[httpx.Request] = []
    state: dict[str, Any] = {"settings": _ENABLED, "handler": None}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = state["handler"](request)
        return result

    async def _patched(_settings: Any, station_key: str, **kwargs: Any) -> Any:
        return await fetch_price_history(
            state["settings"], station_key, transport=httpx.MockTransport(_handler), **kwargs
        )

    monkeypatch.setattr(service_transport, "fetch_price_history", _patched)
    client.app.dependency_overrides[get_state_store] = _FakeStore  # type: ignore[attr-defined]
    yield client, seen, state


def test_route_reads_two_pages_with_the_opaque_cursor(history_api: _HistoryApi) -> None:
    client, seen, state = history_api
    page_one = _page(
        [{"product_code": "B027", "observed_at": "2026-10-22T00:00:00Z", "price": 1700.0}],
        next_cursor="opaque-c1",
    )
    page_two = _page(
        [{"product_code": "D047", "observed_at": "2026-10-21T00:00:00Z", "price": None}],
        status="stale",
    )
    state["handler"] = lambda request: httpx.Response(
        200, json=page_two if request.url.params.get("cursor") == "opaque-c1" else page_one
    )
    query = {"product_code": "B027", "since": "2026-10-01T00:00:00+09:00", "limit": 1}

    first = client.get(_URL, params=query)
    assert first.status_code == 200, first.text
    body = first.json()
    history = body["data"]["history"]
    assert history["status"] == "available"
    assert (history["has_more"], history["next_cursor"], history["truncated"]) == (
        True,
        "opaque-c1",
        True,
    )
    assert body["meta"]["page"]["next_cursor"] == "opaque-c1"
    assert body["meta"]["page"]["page_size"] == 1

    second = client.get(_URL, params={**query, "cursor": history["next_cursor"]}).json()
    history_two = second["data"]["history"]
    assert (history_two["has_more"], history_two["next_cursor"], history_two["truncated"]) == (
        False,
        None,
        False,
    )
    assert history_two["source_status"] == "stale"
    assert history_two["items"] == [
        {
            "product_key": "diesel",
            "product_code": "D047",
            "product_name": "경유",
            "price": None,
            "provider_updated_at": None,
            "observed_at": "2026-10-21T00:00:00Z",
            "collected_at": None,
        }
    ]
    expected_first = {"product": "B027", "from": "2026-10-01T00:00:00+09:00", "limit": "1"}
    assert [dict(r.url.params) for r in seen] == [
        expected_first,
        {**expected_first, "cursor": "opaque-c1"},
    ]


def _raise_read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("느리다", request=request)


@pytest.mark.parametrize(
    ("handler", "params", "reason"),
    [
        (lambda _r: httpx.Response(409, json={}), {"cursor": "old"}, "cursor_expired"),
        (lambda _r: httpx.Response(422, json={}), {"cursor": "bad"}, "request_rejected"),
        (lambda _r: httpx.Response(501, json={}), {}, "upstream_unsupported"),
        (lambda _r: httpx.Response(200, json=_page(station_key="OTHER")), {}, "upstream_contract"),
        (_raise_read_timeout, {}, "upstream_timeout"),
    ],
)
def test_route_keeps_current_prices_when_history_is_unavailable(
    history_api: _HistoryApi, handler: Any, params: dict[str, str], reason: str
) -> None:
    client, _seen, state = history_api
    state["handler"] = handler
    response = client.get(_URL, params=params)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["history"] == {
        "status": "unavailable",
        "reason": reason,
        "generated_at": None,
        "source_collected_at": None,
        "source_status": None,
        "has_more": False,
        "next_cursor": None,
        "truncated": False,
        "items": [],
    }
    assert data["current_prices"][0]["price"] == 1689.0
    assert data["natural_key"] == _STATION_KEY
    assert response.json()["meta"]["page"]["next_cursor"] is None


@pytest.mark.parametrize(
    ("settings_update", "reason"),
    [
        ({"transport_price_history_enabled": False}, "disabled"),
        ({"kor_travel_transport_base_url": None}, "not_configured"),
    ],
)
def test_route_flag_off_or_unconfigured_never_calls_transport(
    history_api: _HistoryApi, settings_update: dict[str, Any], reason: str
) -> None:
    client, seen, state = history_api
    state["settings"] = _ENABLED.model_copy(update=settings_update)
    state["handler"] = lambda _r: pytest.fail("transport를 부르면 안 된다")
    data = client.get(_URL).json()["data"]
    assert (data["history"]["status"], data["history"]["reason"]) == ("unavailable", reason)
    assert data["current_prices"][0]["price"] == 1689.0
    assert seen == []


def test_route_default_limit_is_200_rows_per_page(history_api: _HistoryApi) -> None:
    client, seen, state = history_api
    state["handler"] = lambda _r: httpx.Response(200, json=_page())
    assert client.get(_URL).status_code == 200
    assert dict(seen[0].url.params) == {"limit": "200"}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 1001},
        {"limit": 0},
        {"cursor": ""},
        {"cursor": "x" * 4097},
        {"since": "2026-10-01T00:00:00"},
        {"since": "2026-10-02T00:00:00Z", "until": "2026-10-01T00:00:00Z"},
    ],
)
def test_route_rejects_bad_public_params_without_calling_transport(
    history_api: _HistoryApi, params: dict[str, Any]
) -> None:
    client, seen, state = history_api
    state["handler"] = lambda _r: pytest.fail("transport를 부르면 안 된다")
    assert client.get(_URL, params=params).status_code == 422
    assert seen == []


def test_route_openapi_documents_t4_semantics(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    path = "/v1/service/transport/fuel-stations/{feature_id}/price-history"
    operation = spec["paths"][path]["get"]
    names = {p["name"] for p in operation["parameters"] if p["in"] == "query"}
    assert names == {"product_code", "since", "until", "limit", "cursor"}
    limit = next(p for p in operation["parameters"] if p["name"] == "limit")
    assert (limit["schema"]["default"], limit["schema"]["maximum"]) == (200, 1000)
    block = spec["components"]["schemas"]["PriceHistoryBlock"]
    assert {"has_more", "next_cursor", "truncated", "source_status"} <= set(block["required"])
    point = spec["components"]["schemas"]["PriceHistoryPoint"]
    assert {"type": "null"} in point["properties"]["collected_at"]["anyOf"]
    reasons = set(get_args(PriceHistoryUnavailableReason))
    assert {
        "cursor_expired",
        "request_rejected",
        "upstream_timeout",
        "upstream_unsupported",
    } <= reasons
