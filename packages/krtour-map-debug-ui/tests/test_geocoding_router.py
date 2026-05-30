"""``test_geocoding_router`` — `/debug/geocoding/*` 단위 테스트 (mock kraddr-geo).

httpx.MockTransport로 kraddr-geo 응답을 위조해 reverse/geocode/raw/health 5경로의
입력 매핑 + 응답 처리(매핑/raw/오류)를 DB·외부서비스 없이 검증한다. 실 kraddr-geo
연동은 `test_geocoding_router_live.py`(live mark).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.routers.geocoding import get_settings
from krtour.map_debug_ui.settings import DebugUiSettings

pytestmark = pytest.mark.unit


# ── kraddr-geo mock 응답 빌더 ──────────────────────────────────────────────


def _reverse_ok_payload() -> dict[str, object]:
    return {
        "service": {
            "name": "kraddr-geo",
            "operation": "reverse_geocode",
            "version": "2.0",
            "time": "2026-05-30T00:00:00+00:00",
        },
        "status": "OK",
        "input": {
            "point": {"x": 126.9779, "y": 37.5663},
            "crs": "EPSG:4326",
            "type": "both",
            "zipcode": True,
            "radius_m": 200,
        },
        "result": [
            {
                "type": "road",
                "text": "서울특별시 중구 세종대로 110",
                "structure": {
                    "level0": "대한민국",
                    "level1": "서울특별시",
                    "level2": "중구",
                    "level4L": "태평로1가",
                    "level4LC": "1114010300",
                    "level4A": "명동",
                    "level4AC": "1114055000",
                    "level5": "세종대로",
                    "detail": "110",
                },
                "point": {"x": 126.97770, "y": 37.56620},
                "zipcode": "04524",
                "distance_m": 20.0,
            },
            {
                "type": "parcel",
                "text": "서울특별시 중구 태평로1가 31",
                "structure": {
                    "level0": "대한민국",
                    "level1": "서울특별시",
                    "level2": "중구",
                    "level4L": "태평로1가",
                    "level4LC": "1114010300",
                    "level4A": "명동",
                    "level4AC": "1114055000",
                    "level5": "세종대로",
                    "detail": "31",
                },
                "point": {"x": 126.97770, "y": 37.56620},
                "zipcode": "04524",
                "distance_m": 20.0,
            },
        ],
    }


def _geocode_ok_payload() -> dict[str, object]:
    return {
        "service": {
            "name": "kraddr-geo",
            "operation": "geocode",
            "version": "2.0",
            "time": "2026-05-30T00:00:00+00:00",
        },
        "status": "OK",
        "input": {
            "address": "서울특별시 중구 세종대로 110",
            "type": "road",
            "crs": "EPSG:4326",
            "refine": True,
            "simple": False,
            "fallback": "local_only",
        },
        "result": {"crs": "EPSG:4326", "point": {"x": 126.9777, "y": 37.5662}},
        "x_extension": {
            "source": "local",
            "confidence": 0.95,
            "bjd_cd": "1114010300",
            "rncode_full": "11140RD01",
            "zip_no": "04524",
        },
    }


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str | None = "http://kraddr-geo.test",
) -> TestClient:
    """app + kraddr-geo URL 주입 + 본 lib client의 httpx를 MockTransport로 교체."""
    settings = DebugUiSettings(kraddr_geo_base_url=base_url)

    # `_get_rest_client` / raw 경로 양쪽이 새 `httpx.AsyncClient`를 만든다 — monkey
    # patch로 transport 강제.
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[method-assign]
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    client = TestClient(app)
    # 정리 — 모듈-스코프 patch라 모든 테스트가 끝난 후 복구. pytest fixture로
    # 감싸는 게 더 좋지만 여기서는 단순화를 위해 finalizer 사용.
    client._patch_restore = lambda: setattr(  # type: ignore[attr-defined]
        httpx.AsyncClient, "__init__", original_init
    )
    return client


@pytest.fixture
def restore_httpx_init() -> object:
    original = httpx.AsyncClient.__init__
    yield
    httpx.AsyncClient.__init__ = original  # type: ignore[method-assign]


# ── 503 path: base_url 미설정 ───────────────────────────────────────────


def test_reverse_503_when_base_url_unset(restore_httpx_init: object) -> None:
    settings = DebugUiSettings(kraddr_geo_base_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
    assert r.status_code == 503
    assert "kraddr-geo" in r.json()["detail"]


def test_geocode_503_when_base_url_unset(restore_httpx_init: object) -> None:
    settings = DebugUiSettings(kraddr_geo_base_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    r = client.get("/debug/geocoding/geocode?address=test")
    assert r.status_code == 503


def test_health_no_base_url(restore_httpx_init: object) -> None:
    settings = DebugUiSettings(kraddr_geo_base_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    r = TestClient(app).get("/debug/geocoding/health")
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert body["upstream_status"] is None
    assert "미설정" in body["detail"]


# ── 정상 path: mock kraddr-geo ───────────────────────────────────────────


def test_reverse_ok_maps_to_address(restore_httpx_init: object) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/v1/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=_reverse_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/reverse?lon=126.9779&lat=37.5663&type=both&radius_m=200"
        )
        assert r.status_code == 200
        addr = r.json()["address"]
        assert addr is not None
        # bjd_cd 10자리 → bjd_code + sigungu_code(5) + sido_code(2) 파생.
        assert addr["bjd_code"] == "1114010300"
        assert addr["sigungu_code"] == "11140"
        assert addr["sido_code"] == "11"
        assert addr["sido_name"] == "서울특별시"
        assert addr["sigungu_name"] == "중구"
        assert addr["road"] == "서울특별시 중구 세종대로 110"
        assert addr["legal"] == "서울특별시 중구 태평로1가 31"
        assert addr["zipcode"] == "04524"
        # 파라미터가 kraddr-geo에 정확히 전달됐는지.
        params = seen[0][1]
        assert seen[0][0] == "/v1/address/reverse"
        assert params["x"] == "126.9779"
        assert params["y"] == "37.5663"
        assert params["type"] == "both"
        assert params["radius_m"] == "200"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_raw_passes_through(restore_httpx_init: object) -> None:
    payload = _reverse_ok_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse/raw?lon=126.9&lat=37.5")
        assert r.status_code == 200
        body = r.json()
        # raw — kraddr-geo 응답 그대로.
        assert body["status"] == "OK"
        assert body["service"]["version"] == "2.0"
        assert len(body["result"]) == 2
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_ok_maps_to_coord(restore_httpx_init: object) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=_geocode_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/geocode?address=%EC%84%9C%EC%9A%B8%20%EC%A4%91%EA%B5%AC&type=road"
        )
        assert r.status_code == 200
        coord = r.json()["coord"]
        assert coord is not None
        assert coord["lon"] == "126.9777"
        assert coord["lat"] == "37.5662"
        assert seen[0][0] == "/v1/address/geocode"
        assert seen[0][1]["type"] == "road"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_min_confidence_filters(restore_httpx_init: object) -> None:
    """x_extension.confidence(0.95) < min_confidence(0.99) → coord None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_geocode_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/geocode?address=test&min_confidence=0.99"
        )
        assert r.status_code == 200
        assert r.json()["coord"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_not_found_returns_null(restore_httpx_init: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "NOT_FOUND", "result": []})

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_max_distance_filter(restore_httpx_init: object) -> None:
    """모든 result의 distance_m가 max_distance_m보다 크면 None."""
    payload = _reverse_ok_payload()
    for item in payload["result"]:  # type: ignore[union-attr]
        item["distance_m"] = 500.0  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/reverse?lon=126.9&lat=37.5&max_distance_m=100"
        )
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_health_ok_when_upstream_200(restore_httpx_init: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/health")
        assert r.status_code == 200
        body = r.json()
        assert body["reachable"] is True
        assert body["upstream_status"] == 200
        assert body["base_url"] == "http://kraddr-geo.test"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_health_unreachable_returns_status_only(restore_httpx_init: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/health")
        assert r.status_code == 200
        body = r.json()
        assert body["reachable"] is False
        assert body["upstream_status"] == 503
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_raw_502_on_upstream_error(restore_httpx_init: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream error")

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse/raw?lon=126.9&lat=37.5")
        assert r.status_code == 502
        assert "kraddr-geo" in r.json()["detail"]
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_raw_passes_address(restore_httpx_init: object) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=_geocode_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/geocode/raw?address=test&type=parcel&fallback=api"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        assert seen[0]["address"] == "test"
        assert seen[0]["type"] == "parcel"
        assert seen[0]["fallback"] == "api"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_routes_registered_in_openapi(restore_httpx_init: object) -> None:
    """OpenAPI 스펙에 5경로 모두 등장."""
    settings = DebugUiSettings(kraddr_geo_base_url="http://x")
    app = create_app(settings)
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for p in (
        "/debug/geocoding/health",
        "/debug/geocoding/reverse",
        "/debug/geocoding/reverse/raw",
        "/debug/geocoding/geocode",
        "/debug/geocoding/geocode/raw",
    ):
        assert p in paths, f"missing path: {p}"
