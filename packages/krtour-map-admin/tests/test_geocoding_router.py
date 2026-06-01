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

from krtour.map_admin.app import create_app
from krtour.map_admin.routers.geocoding import get_settings
from krtour.map_admin.settings import AdminSettings

pytestmark = pytest.mark.unit


# ── kraddr-geo mock 응답 빌더 ──────────────────────────────────────────────


def _reverse_ok_payload() -> dict[str, object]:
    """kraddr-geo ``POST /v2/reverse`` OK — road + parcel candidate 2건."""
    region = {
        "sig_cd": "11140",
        "bjd_cd": "1114010300",
        "sido": "서울특별시",
        "sigungu": "중구",
        "legal_dong": "태평로1가",
        "admin_dong": "명동",
    }
    return {
        "status": "OK",
        "candidates": [
            {
                "confidence": 0.66,
                "match_kind": "road",
                "address": {
                    "full": "서울특별시 중구 세종대로 110",
                    "road_address": "서울특별시 중구 세종대로 110",
                    "parcel_address": None,
                    "postal_code": "04524",
                    "legal_dong_code": "1114010300",
                    "admin_dong_code": "1114055000",
                    "road_name": "세종대로",
                    "road_name_code": "11140RD01",
                },
                "point": {"x": 126.97770, "y": 37.56620},
                "distance_m": 20.0,
                "region": region,
            },
            {
                "confidence": 0.6,
                "match_kind": "parcel",
                "address": {
                    "full": "서울특별시 중구 태평로1가 31",
                    "road_address": None,
                    "parcel_address": "서울특별시 중구 태평로1가 31",
                    "postal_code": "04524",
                    "legal_dong_code": "1114010300",
                    "admin_dong_code": "1114055000",
                    "road_name": None,
                    "road_name_code": None,
                },
                "point": {"x": 126.97770, "y": 37.56620},
                "distance_m": 20.0,
                "region": region,
            },
        ],
    }


def _geocode_ok_payload() -> dict[str, object]:
    """kraddr-geo ``POST /v2/geocode`` OK — road candidate 1건 (confidence 0.95)."""
    return {
        "status": "OK",
        "candidates": [
            {
                "confidence": 0.95,
                "match_kind": "road",
                "address": {
                    "full": "서울특별시 중구 세종대로 110",
                    "road_address": "서울특별시 중구 세종대로 110",
                    "parcel_address": None,
                    "postal_code": "04524",
                    "legal_dong_code": "1114010300",
                    "admin_dong_code": "1114055000",
                    "road_name": "세종대로",
                    "road_name_code": "11140RD01",
                },
                "point": {"x": 126.9777, "y": 37.5662},
                "distance_m": None,
                "region": None,
            }
        ],
    }


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str | None = "http://kraddr-geo.test",
) -> TestClient:
    """app + kraddr-geo URL 주입 + 본 lib client의 httpx를 MockTransport로 교체."""
    settings = AdminSettings(kraddr_geo_base_url=base_url)

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
    settings = AdminSettings(kraddr_geo_base_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
    assert r.status_code == 503
    assert "kraddr-geo" in r.json()["detail"]


def test_geocode_503_when_base_url_unset(restore_httpx_init: object) -> None:
    settings = AdminSettings(kraddr_geo_base_url=None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    r = client.get("/debug/geocoding/geocode?address=test")
    assert r.status_code == 503


def test_health_no_base_url(restore_httpx_init: object) -> None:
    settings = AdminSettings(kraddr_geo_base_url=None)
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
    import json as _json

    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/v1/healthz":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=_reverse_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/reverse?lon=126.9779&lat=37.5663&radius_m=200"
        )
        assert r.status_code == 200
        addr = r.json()["address"]
        assert addr is not None
        # bjd 10자리 → bjd_code + sigungu_code(5) + sido_code(2) 파생.
        assert addr["bjd_code"] == "1114010300"
        assert addr["sigungu_code"] == "11140"
        assert addr["sido_code"] == "11"
        assert addr["sido_name"] == "서울특별시"
        assert addr["sigungu_name"] == "중구"
        assert addr["road"] == "서울특별시 중구 세종대로 110"
        assert addr["legal"] == "서울특별시 중구 태평로1가 31"
        assert addr["zipcode"] == "04524"
        # v2: POST /v2/reverse + JSON body(lon/lat/radius_m).
        method, path, body = seen[0]
        assert method == "POST"
        assert path == "/v2/reverse"
        assert body["lon"] == 126.9779
        assert body["lat"] == 37.5663
        assert body["radius_m"] == 200
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
        # raw — kraddr-geo v2 응답 그대로.
        assert body["status"] == "OK"
        assert len(body["candidates"]) == 2
        assert body["candidates"][0]["match_kind"] == "road"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_ok_maps_to_coord(restore_httpx_init: object) -> None:
    import json as _json

    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body))
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
        # v2: POST /v2/geocode + road_address(JSON body), fallback 기본 none.
        method, path, body = seen[0]
        assert method == "POST"
        assert path == "/v2/geocode"
        assert body["road_address"] == "서울 중구"
        assert body["fallback"] == "none"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_min_confidence_filters(restore_httpx_init: object) -> None:
    """candidate.confidence(0.95) < min_confidence(0.99) → coord None."""

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
        return httpx.Response(200, json={"status": "NOT_FOUND", "candidates": []})

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
    for cand in payload["candidates"]:  # type: ignore[union-attr]
        cand["distance_m"] = 500.0  # type: ignore[index]

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
    import json as _json

    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body))
        return httpx.Response(200, json=_geocode_ok_payload())

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/geocode/raw?address=test&type=parcel&fallback=api"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        # v2: type=parcel → jibun_address(JSON body), fallback 그대로 전달.
        method, path, sent = seen[0]
        assert method == "POST"
        assert path == "/v2/geocode"
        assert sent["jibun_address"] == "test"
        assert sent["fallback"] == "api"
        assert "road_address" not in sent
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_routes_registered_in_openapi(restore_httpx_init: object) -> None:
    """OpenAPI 스펙에 5경로 모두 등장."""
    settings = AdminSettings(kraddr_geo_base_url="http://x")
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
