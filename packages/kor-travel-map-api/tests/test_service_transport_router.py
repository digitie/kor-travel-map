"""``/v1/service/transport/*`` — Valkey 없이 재는 계약(ADR-114 D6).

실제 Valkey로 재는 교체·GEO·순회·REST 왕복은
``tests/integration/test_valkey_transport_state.py``가 소유한다. 여기서는 표면 등록·인증 정책·입력
검증·Valkey 미설정 503·가격 추이 프록시(transport T4 질의 변환·실제 응답 모양·cursor 두
페이지·409/422/501/timeout·주유소 불일치·플래그·현재가 보존)를 본다.
"""

from __future__ import annotations

import gzip
import json
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
    MAX_PRICE_HISTORY_BODY_BYTES,
    PriceHistoryRequest,
    PriceHistoryUnavailableReason,
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


def _as_wire(response: httpx.Response) -> httpx.Response:
    """``content=``·``json=``로 만든 응답은 이미 읽힌 상태라 ``aiter_raw``가 ``StreamConsumed``를
    낸다 — 실제 전송처럼 원문 stream으로 다시 싼다(``_raw`` 응답은 그대로)."""
    try:
        data = response.content
    except httpx.ResponseNotRead:
        return response
    return httpx.Response(
        response.status_code, headers=response.headers, stream=httpx.ByteStream(data)
    )


def _mock(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: _as_wire(handler(request)))


async def _fetch(
    handler: Any,
    settings: KorTravelMapSettings = _ENABLED,
    *,
    request: PriceHistoryRequest | None = None,
) -> Any:
    return await fetch_price_history(
        settings,
        _STATION_KEY,
        request=PriceHistoryRequest(limit=10) if request is None else request,
        transport=_mock(handler),
    )


def test_public_params_translate_to_transport_t4_names() -> None:
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=9)))
    assert PriceHistoryRequest(
        product_code="B027", since=since, until=until, limit=200, cursor="opaque"
    ).params == {
        "product": "B027",
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-23T09:00:00+09:00",
        "limit": "200",
        "cursor": "opaque",
    }
    assert PriceHistoryRequest(limit=5).params == {"limit": "5"}


async def test_price_history_success_sends_t4_query_and_parses_the_real_shape() -> None:
    seen: list[httpx.Request] = []

    def _ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page(status="stale"))

    request = PriceHistoryRequest(
        since=datetime(2026, 10, 1, tzinfo=UTC),
        until=datetime(2026, 10, 23, tzinfo=UTC),
        limit=200,
        cursor="c-1",
    )
    outcome = await _fetch(_ok, request=request)
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
    (sent,) = seen
    assert sent.url.path == f"/v1/service/exports/fuel-stations/{_STATION_KEY}/price-history"
    assert dict(sent.url.params) == {
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-23T00:00:00+00:00",
        "limit": "200",
        "cursor": "c-1",
    }
    assert sent.headers["X-Kor-Travel-Transport-Service-Token"] == "s" * 40
    # 압축을 받지 않는다 — 본문 상한을 원문 크기로 잰다(gzip 조각은 통째로 풀린다).
    assert sent.headers["Accept-Encoding"] == "identity"


# transport 503 problem+json(성공한 수집 근거 없음) — export_price_history.py의 실제 본문.
_NO_COLLECTION = {
    "type": "about:blank",
    "title": "Service Unavailable",
    "status": 503,
    "detail": "성공한 유가 수집 이력이 없습니다.",
    "instance": "/v1/service/exports/fuel-stations/A0000001/price-history",
    "meta": {
        "generated_at": "2026-10-23T00:00:01Z",
        "source_collected_at": None,
        "source_status": "failed",
        "item_count": 0,
    },
}


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(404, json={"detail": "Not Found"}), "upstream_not_found"),
        (httpx.Response(501, json={"status": 501}), "upstream_unsupported"),
        (httpx.Response(409, json={"status": 409}), "upstream_rejected"),  # cursor 없이 409
        (httpx.Response(422, json={"status": 422}), "request_rejected"),
        (httpx.Response(503, json=_NO_COLLECTION), "upstream_no_collection"),
        (httpx.Response(503, json={"status": 503}), "upstream_unavailable"),
        (httpx.Response(503, text="maintenance"), "upstream_unavailable"),
        (httpx.Response(502, text="bad gateway"), "upstream_unavailable"),
        (httpx.Response(304), "upstream_rejected"),
        (httpx.Response(200, text="<html>"), "upstream_contract"),
    ],
)
async def test_price_history_failures_degrade_to_unavailable(
    response: httpx.Response, reason: str
) -> None:
    outcome = await _fetch(lambda _request: response)
    assert (outcome.history, outcome.reason, outcome.cursor_expired) == (None, reason, False)


async def test_price_history_409_after_a_cursor_is_a_restart_signal() -> None:
    outcome = await _fetch(
        lambda _request: httpx.Response(409, json={"status": 409}),
        request=PriceHistoryRequest(cursor="c", limit=5),
    )
    assert (outcome.history, outcome.reason, outcome.cursor_expired) == (None, None, True)


@pytest.mark.parametrize(
    "raw_price",
    [b"NaN", b"Infinity", b"-Infinity", b"1e400", b'"sNaN"', b'"1700"', b"true"],
)
async def test_price_history_rejects_non_finite_and_non_number_prices(raw_price: bytes) -> None:
    body = (
        b'{"meta":{"generated_at":"2026-10-23T00:00:01Z","source_collected_at":null,'
        b'"source_status":"ok","item_count":1},"station_key":"A0000001","items":[{"product_code":'
        b'"B027","observed_at":"2026-10-22T00:00:00Z","price":' + raw_price + b'}],'
        b'"next_cursor":null,"has_more":false}'
    )
    outcome = await _fetch(lambda _request: httpx.Response(200, content=body))
    assert (outcome.history, outcome.reason) == (None, "upstream_contract")


_ROW_0922 = {"product_code": "B027", "observed_at": "2026-09-22T00:00:00Z", "price": 1.0}
_ROW_1022 = {"product_code": "B027", "observed_at": "2026-10-22T00:00:00Z", "price": 1.0}
_ROW_D047 = {"product_code": "D047", "observed_at": "2026-10-21T00:00:00Z", "price": 1.0}
_SINCE = datetime(2026, 10, 1, tzinfo=UTC)
_UNTIL = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rows", "request_", "ok"),
    [
        ([_ROW_1022], PriceHistoryRequest(product_code="B027"), True),
        ([_ROW_1022, _ROW_D047], PriceHistoryRequest(product_code="B027"), False),
        ([_ROW_1022], PriceHistoryRequest(since=_SINCE, until=_UNTIL), True),  # 양끝 포함
        ([_ROW_0922], PriceHistoryRequest(since=_SINCE), False),
        ([_ROW_1022], PriceHistoryRequest(until=_UNTIL - timedelta(seconds=1)), False),
        # 보내지 않은 끝은 transport 기본 창을 추측하지 않는다(cursor 페이지가 창을 뺀 경우).
        ([_ROW_0922], PriceHistoryRequest(cursor="c"), True),
    ],
)
async def test_price_history_rows_must_match_the_requested_product_and_window(
    rows: list[dict[str, Any]], request_: PriceHistoryRequest, ok: bool
) -> None:
    outcome = await _fetch(lambda _request: httpx.Response(200, json=_page(rows)), request=request_)
    assert (outcome.reason is None) is ok, outcome.reason
    if not ok:
        assert outcome.reason == "upstream_contract"


async def test_price_history_deep_or_oversized_bodies_are_upstream_contract() -> None:
    deep = b"[" * 200_000 + b"]" * 200_000
    assert (await _fetch(lambda _r: httpx.Response(200, content=deep))).reason == (
        "upstream_contract"
    )
    huge_rows = [_ROW_1022] * (MAX_PRICE_HISTORY_BODY_BYTES // 60 + 1)
    assert (await _fetch(lambda _r: httpx.Response(200, json=_page(huge_rows)))).reason == (
        "upstream_contract"
    )
    lying = httpx.Response(
        200, content=b"{}", headers={"content-length": str(MAX_PRICE_HISTORY_BODY_BYTES + 1)}
    )
    assert (await _fetch(lambda _r: lying)).reason == "upstream_contract"

    async def _chunks() -> Any:
        for _ in range(3):  # content-length 없이 상한을 넘는 스트림
            yield b" " * (MAX_PRICE_HISTORY_BODY_BYTES // 2)

    streamed = await _fetch(lambda _r: httpx.Response(200, content=_chunks()))
    assert streamed.reason == "upstream_contract"
    assert (await _fetch(lambda _r: httpx.Response(200, content=b"\xff\xfe"))).reason == (
        "upstream_contract"
    )


def _raw(status_code: int, data: bytes, headers: dict[str, str]) -> httpx.Response:
    """원문 그대로의 stream 응답. ``content=``는 생성 때 미리 풀어 버려(깨진 gzip이면 그 자리에서
    터진다) 실제 전송을 흉내 내지 못한다."""
    return httpx.Response(status_code, stream=httpx.ByteStream(data), headers=headers)


def _gzip_response(payload: bytes, status_code: int = 200) -> httpx.Response:
    return _raw(status_code, gzip.compress(payload), {"Content-Encoding": "gzip"})


async def test_price_history_gzip_is_capped_after_decompression() -> None:
    """identity를 무시하고 gzip이 와도 풀린 크기로 상한을 잰다(작은 압축 조각 → 수 MB)."""
    bomb = b'{"pad":"' + b"x" * (MAX_PRICE_HISTORY_BODY_BYTES * 3) + b'"}'
    compressed = gzip.compress(bomb)
    assert len(compressed) < 64 * 1024
    outcome = await _fetch(
        lambda _r: _raw(200, compressed, {"Content-Encoding": "gzip"})
    )
    assert outcome.reason == "upstream_contract"
    # 상한 안의 정상 gzip 페이지는 그대로 읽는다.
    ok = await _fetch(lambda _r: _gzip_response(json.dumps(_page()).encode()))
    assert ok.reason is None
    assert ok.history is not None
    assert len(ok.history.items) == 2


@pytest.mark.parametrize(
    ("data", "encoding"),
    [
        (b"not gzip at all", "gzip"),
        (gzip.compress(json.dumps(_page()).encode())[:-12], "gzip"),  # 잘린 gzip
        (b"{}", "br"),
    ],
)
async def test_price_history_bad_content_encoding_is_upstream_contract(
    data: bytes, encoding: str
) -> None:
    outcome = await _fetch(lambda _r: _raw(200, data, {"Content-Encoding": encoding}))
    assert (outcome.history, outcome.reason) == (None, "upstream_contract")


async def test_price_history_stream_is_cut_before_buffering_past_the_cap() -> None:
    yielded: list[int] = []

    async def _chunks() -> Any:
        for index in range(10):
            yielded.append(index)
            yield b" " * (MAX_PRICE_HISTORY_BODY_BYTES // 2 + 1)

    outcome = await _fetch(lambda _r: httpx.Response(200, content=_chunks()))
    assert outcome.reason == "upstream_contract"
    # 두 번째 조각이 상한을 넘기므로 붙이기 전에 끊고 나머지는 읽지 않는다.
    assert yielded == [0, 1]


_HUGE = b"x" * (MAX_PRICE_HISTORY_BODY_BYTES * 2)


@pytest.mark.parametrize(
    ("response", "request_", "reason", "cursor_expired"),
    [
        (httpx.Response(503, content=_HUGE), None, "upstream_unavailable", False),
        (
            httpx.Response(503, content=b"{}", headers={"content-length": str(len(_HUGE))}),
            None,
            "upstream_unavailable",
            False,
        ),
        (
            _raw(503, b"\x00garbage", {"Content-Encoding": "gzip"}),
            None,
            "upstream_unavailable",
            False,
        ),
        (_gzip_response(json.dumps(_NO_COLLECTION).encode(), 503), None, "upstream_no_collection",
         False),
        (httpx.Response(404, content=_HUGE), None, "upstream_not_found", False),
        (httpx.Response(422, content=_HUGE), None, "request_rejected", False),
        (httpx.Response(501, content=_HUGE), None, "upstream_unsupported", False),
        (httpx.Response(409, content=_HUGE), PriceHistoryRequest(cursor="c"), None, True),
    ],
)
async def test_price_history_oversized_error_bodies_are_classified_by_status(
    response: httpx.Response,
    request_: PriceHistoryRequest | None,
    reason: str | None,
    cursor_expired: bool,
) -> None:
    outcome = await _fetch(lambda _r: response, request=request_)
    assert (outcome.history, outcome.reason, outcome.cursor_expired) == (
        None,
        reason,
        cursor_expired,
    )


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
        _page(status="failed"),  # transport는 failed를 503 problem에만 싣는다
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
            _ENABLED, key, request=PriceHistoryRequest(), transport=httpx.MockTransport(_never)
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
def history_api(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> _HistoryApi:
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
            state["settings"], station_key, transport=_mock(_handler), **kwargs
        )

    monkeypatch.setattr(service_transport, "fetch_price_history", _patched)
    client.app.dependency_overrides[get_state_store] = _FakeStore  # type: ignore[attr-defined]
    return client, seen, state


def test_route_reads_two_pages_with_the_opaque_cursor(history_api: _HistoryApi) -> None:
    client, seen, state = history_api
    page_one = _page(
        [{"product_code": "B027", "observed_at": "2026-10-22T00:00:00Z", "price": 1700.0}],
        next_cursor="opaque-c1",
    )
    page_two = _page(
        [{"product_code": "B027", "observed_at": "2026-10-21T00:00:00Z", "price": None}],
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
            "product_key": "gasoline",
            "product_code": "B027",
            "product_name": "휘발유",
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
        (lambda _r: httpx.Response(409, json={}), {}, "upstream_rejected"),
        (lambda _r: httpx.Response(503, json=_NO_COLLECTION), {}, "upstream_no_collection"),
        (lambda _r: httpx.Response(200, content=b'{"price": NaN}'), {}, "upstream_contract"),
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


def test_route_cursor_409_is_http_409_restart(history_api: _HistoryApi) -> None:
    client, seen, state = history_api
    state["handler"] = lambda _r: httpx.Response(409, json={"status": 409})
    response = client.get(_URL, params={"cursor": "old", "product_code": "B027"})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED"
    assert dict(seen[0].url.params) == {"cursor": "old", "product": "B027", "limit": "200"}


def test_route_non_finite_price_keeps_current_price(history_api: _HistoryApi) -> None:
    client, _seen, state = history_api
    body = (
        b'{"meta":{"generated_at":"2026-10-23T00:00:01Z","source_collected_at":null,'
        b'"source_status":"ok","item_count":1},"station_key":"A0000001","items":[{"product_code":'
        b'"B027","observed_at":"2026-10-22T00:00:00Z","price":1e400}],"next_cursor":null,'
        b'"has_more":false}'
    )
    state["handler"] = lambda _r: httpx.Response(200, content=body)
    response = client.get(_URL)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["history"]["status"], data["history"]["reason"]) == (
        "unavailable",
        "upstream_contract",
    )
    assert data["current_prices"][0]["price"] == 1689.0


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
        "request_rejected",
        "upstream_no_collection",
        "upstream_timeout",
        "upstream_unsupported",
    } <= reasons
    assert "cursor_expired" not in reasons
    assert set(block["properties"]["reason"]["anyOf"][0]["enum"]) == reasons
    conflict = operation["responses"]["409"]["description"]
    assert "TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED" in conflict
    status_doc = block["properties"]["status"]["description"]
    assert "has_more=false" in status_doc
