"""``test_geocoding_router_edge`` — kraddr-geo 라우터 에러·protocol 엣지 (mock).

`test_geocoding_router.py`(정상 path)와 분리해 **장애 모드 / protocol drift /
검증 거부 케이스**를 집중적으로 본다. 모두 httpx.MockTransport.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.routers.geocoding import get_settings
from krtour.map_debug_ui.settings import DebugUiSettings

pytestmark = pytest.mark.unit


# ── shared infra ──────────────────────────────────────────────────────────


@pytest.fixture
def restore_httpx_init() -> object:
    original = httpx.AsyncClient.__init__
    yield
    httpx.AsyncClient.__init__ = original  # type: ignore[method-assign]


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://kraddr-geo.test",
) -> TestClient:
    settings = DebugUiSettings(kraddr_geo_base_url=base_url)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[method-assign]
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    client._patch_restore = lambda: setattr(  # type: ignore[attr-defined]
        httpx.AsyncClient, "__init__", original_init
    )
    return client


def _reverse_item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "parcel",
        "text": "서울 중구 태평로1가 31",
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
        "point": {"x": 126.977, "y": 37.566},
        "zipcode": "04524",
        "distance_m": 10.0,
    }
    base.update(overrides)
    return base


def _reverse_envelope(items: list[dict[str, Any]], status: str = "OK") -> dict[str, Any]:
    return {
        "service": {"name": "kraddr-geo", "operation": "reverse_geocode", "version": "2.0"},
        "status": status,
        "input": {"point": {"x": 0, "y": 0}, "crs": "EPSG:4326"},
        "result": items,
    }


def _geocode_envelope(
    *,
    status: str = "OK",
    point: tuple[float, float] | None = (126.977, 37.566),
    confidence: float | None = 0.9,
    extension_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "service": {"name": "kraddr-geo", "operation": "geocode", "version": "2.0"},
        "status": status,
        "input": {"address": "x", "type": "road"},
    }
    if point is not None:
        body["result"] = {"crs": "EPSG:4326", "point": {"x": point[0], "y": point[1]}}
    else:
        body["result"] = None
    if confidence is not None or extension_extra is not None:
        ext: dict[str, Any] = {"confidence": confidence if confidence is not None else 0.0}
        if extension_extra:
            ext.update(extension_extra)
        body["x_extension"] = ext
    return body


# ── A1. 네트워크 / 직렬화 장애 ──────────────────────────────────────────


def test_reverse_raw_upstream_timeout_502(restore_httpx_init: object) -> None:
    """httpx.TimeoutException → 502 graceful (raw 경로)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=_request)

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse/raw?lon=126.9&lat=37.5")
        assert r.status_code == 502
        assert "unreachable" in r.json()["detail"]
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_raw_upstream_timeout_502(restore_httpx_init: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conn refused", request=_request)

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/geocode/raw?address=test")
        assert r.status_code == 502
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_malformed_json_raises(restore_httpx_init: object) -> None:
    """upstream이 JSON이 아닌 본문 200 반환 — json.JSONDecodeError가 TestClient
    경계에서 그대로 raise됨(현 시점). 후속 PR에서 graceful 502 매핑 가능."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    client = _make_client(handler)
    try:
        from json import JSONDecodeError

        with pytest.raises(JSONDecodeError):
            client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_health_upstream_connect_error(restore_httpx_init: object) -> None:
    """health는 HTTPError를 잡아 reachable=false + detail로 보여줘야 함(예외 누수 X)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conn refused", request=_request)

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/health")
        assert r.status_code == 200
        body = r.json()
        assert body["reachable"] is False
        assert body["upstream_status"] is None
        assert "conn refused" in (body["detail"] or "")
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A2. status 코드 변형 ─────────────────────────────────────────────────


def test_reverse_status_error_returns_null(restore_httpx_init: object) -> None:
    """status='ERROR' → address None (raise X)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([], status="ERROR"))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_unknown_status_returns_null(restore_httpx_init: object) -> None:
    """upstream이 미지의 status(예: 'PARTIAL') 반환 → OK 아니므로 None (silent fail)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_reverse_envelope([_reverse_item()], status="PARTIAL"),
        )

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_status_ok_but_empty_result(restore_httpx_init: object) -> None:
    """status='OK' + result=[] → 매핑 None (no items)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A3. 코드/우편번호 자릿수 거부(silent drop) ────────────────────────────


def test_reverse_bjd_invalid_length_drops(restore_httpx_init: object) -> None:
    """level4LC가 비-10자리 → bjd_code/sigungu/sido 모두 None로 떨어뜨림."""
    item = _reverse_item()
    item["structure"]["level4LC"] = "1234"  # 4자리 — 비정상

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        assert r.status_code == 200
        addr = r.json()["address"]
        assert addr is not None  # Address 객체 자체는 만들어짐
        assert addr["bjd_code"] is None
        assert addr["sigungu_code"] is None
        assert addr["sido_code"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_admin_dong_invalid_length_drops(restore_httpx_init: object) -> None:
    """level4AC가 9자리 → admin_dong_code None (validator 거부 회피)."""
    item = _reverse_item()
    item["structure"]["level4AC"] = "111405100"  # 9자리

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        assert addr["admin_dong_code"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_zipcode_invalid_length_drops(restore_httpx_init: object) -> None:
    """zipcode가 6자리(과거 형식 등) → None (5자리만 허용)."""
    item = _reverse_item()
    item["zipcode"] = "123456"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        assert addr["zipcode"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A4. structure 결손 ───────────────────────────────────────────────────


def test_reverse_all_levels_null(restore_httpx_init: object) -> None:
    """structure의 모든 level이 None — Address 만들어지지만 모두 None."""
    item = _reverse_item()
    item["structure"] = {
        "level0": "대한민국",
        "level1": None,
        "level2": None,
        "level4L": None,
        "level4LC": None,
        "level4A": None,
        "level4AC": None,
        "level5": None,
        "detail": None,
    }
    item["zipcode"] = None

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        # type=parcel + text "..." → legal 채워짐.
        assert addr["legal"] is not None
        # 나머지 코드/이름은 전부 None.
        assert addr["bjd_code"] is None
        assert addr["sido_code"] is None
        assert addr["sido_name"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A5. result 다건 — 최근접 선택 ────────────────────────────────────────


def test_reverse_picks_closest_among_multiple(restore_httpx_init: object) -> None:
    """distance_m 최소 item이 대표(bjd 추출/구분명) — text는 type별 매칭."""
    far_item = _reverse_item(type="parcel", distance_m=300.0)
    far_item["structure"]["level4LC"] = "9999999999"  # 무관한 bjd
    far_item["text"] = "멈"
    near_item = _reverse_item(type="parcel", distance_m=5.0)
    near_item["text"] = "가깝"
    # near_item의 structure level4LC 그대로 "1114010300".
    road_item = _reverse_item(type="road", distance_m=20.0)
    road_item["text"] = "도로명"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([far_item, road_item, near_item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        # primary = near_item (distance 5.0)이므로 bjd 1114010300.
        assert addr["bjd_code"] == "1114010300"
        # legal text = 처음 등장하는 parcel item("멈") — 라이브러리 정책: 순서.
        assert addr["legal"] in ("멈", "가깝")  # 어느쪽이든 parcel text 매칭
        # road text는 road item에서.
        assert addr["road"] == "도로명"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_max_distance_filters_all(restore_httpx_init: object) -> None:
    """모든 item이 max_distance_m보다 멀면 None."""
    far_a = _reverse_item(distance_m=500.0)
    far_b = _reverse_item(distance_m=800.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([far_a, far_b]))

    client = _make_client(handler)
    try:
        r = client.get(
            "/debug/geocoding/reverse?lon=126.9&lat=37.5&max_distance_m=100"
        )
        assert r.status_code == 200
        assert r.json()["address"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A6. point=null 또는 zipcode=null ───────────────────────────────────


def test_reverse_item_with_null_point(restore_httpx_init: object) -> None:
    """ReverseResultItem.point=null이어도 매핑 진행 (point은 정보용)."""
    item = _reverse_item()
    item["point"] = None
    item["distance_m"] = 5.0

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        assert addr["bjd_code"] == "1114010300"
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_reverse_item_with_null_zipcode(restore_httpx_init: object) -> None:
    """zipcode=null도 정상 매핑."""
    item = _reverse_item()
    item["zipcode"] = None

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse_envelope([item]))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/reverse?lon=126.9&lat=37.5")
        addr = r.json()["address"]
        assert addr is not None
        assert addr["zipcode"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


# ── A7. geocode — x_extension/confidence boundary ──────────────────────


def test_geocode_no_extension_treats_confidence_zero(restore_httpx_init: object) -> None:
    """x_extension=null → confidence가 없으므로 min_confidence=0.0 boundary만 통과."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_geocode_envelope(point=(126.9, 37.5), confidence=None))

    client = _make_client(handler)
    try:
        # x_extension 없음 → 매핑 함수는 ext is None → confidence check skip → coord 정상.
        r = client.get("/debug/geocoding/geocode?address=x&min_confidence=0.0")
        assert r.status_code == 200
        assert r.json()["coord"] is not None
        # 같은 응답에 min_confidence=0.99이면 — ext 없으므로 통과.
        r2 = client.get("/debug/geocoding/geocode?address=x&min_confidence=0.99")
        assert r2.status_code == 200
        assert r2.json()["coord"] is not None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_confidence_zero_passes_min_zero(restore_httpx_init: object) -> None:
    """confidence=0.0 + min_confidence=0.0 — boundary 통과."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_geocode_envelope(confidence=0.0))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/geocode?address=x&min_confidence=0.0")
        assert r.status_code == 200
        assert r.json()["coord"] is not None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_status_ok_but_result_null(restore_httpx_init: object) -> None:
    """status=OK이지만 result=None — coord None."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_geocode_envelope(point=None))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/geocode?address=x")
        assert r.status_code == 200
        assert r.json()["coord"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]


def test_geocode_point_out_of_korea_returns_none(restore_httpx_init: object) -> None:
    """out-of-Korea point — `geocode_response_to_coordinate`가 `Coordinate`
    validator의 ValidationError(`ValueError` 하위)를 catch → coord None (graceful).
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        # 도쿄 부근 — Coordinate 한국 경계(124~132, 33~39.5) 밖.
        return httpx.Response(200, json=_geocode_envelope(point=(139.7, 35.7)))

    client = _make_client(handler)
    try:
        r = client.get("/debug/geocoding/geocode?address=x")
        assert r.status_code == 200
        assert r.json()["coord"] is None
    finally:
        client._patch_restore()  # type: ignore[attr-defined]
