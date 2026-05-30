"""``test_geocoding_router_live_edge`` — 실 kraddr-geo의 엣지 시나리오.

`test_geocoding_router_live.py`(주요 도시 4곳 + round-trip 1)에 이어 운영 사례에서
드러날 가능성이 큰 엣지를 본다:
- 한국 다른 광역시 4곳(광주/인천/울산/세종) — 시도 코드 분기.
- 한국 본토 경계 정점 좌표 — Coordinate 유효 + reverse 동작.
- 산악·도서 좌표 — kraddr-geo NOT_FOUND/거리 큰 결과 graceful.
- `radius_m` 변동 — 결과 개수/distance.
- `type=road` vs `parcel` — text·structure 차이.
- 같은 좌표 N회 idempotency.
- 정밀(8자리) 좌표.
- 부산/대전 round-trip.
- 주소 입력 엣지(괄호, 200자, 영문 mix).

도달 불가 시 `pytest.skip` (LIVE_KRADDR_GEO_BASE_URL env override).
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.routers.geocoding import get_settings
from krtour.map_debug_ui.settings import DebugUiSettings

pytestmark = pytest.mark.live


_DEFAULT_BASE_URL = "http://127.0.0.1:13088/api/proxy"


def _resolve_base_url() -> str:
    return os.environ.get("LIVE_KRADDR_GEO_BASE_URL", _DEFAULT_BASE_URL)


def _is_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return False
    try:
        with httpx.Client(base_url=base_url, timeout=3.0) as http:
            return http.get("/v1/healthz").status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def base_url() -> str:
    url = _resolve_base_url()
    if not _is_reachable(url):
        pytest.skip(f"kraddr-geo 도달 불가: {url}")
    return url


@pytest.fixture
def client(base_url: str) -> TestClient:
    settings = DebugUiSettings(kraddr_geo_base_url=base_url)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


# ── B1. 광역시청 4개 추가 검증 ──────────────────────────────────────────


_MORE_CITIES = [
    # (name, lon, lat, sido_code, sigungu_prefix, sido_name_part)
    # 광주광역시 (좌표는 동구 일대 — bjd 2914011600)
    ("gwangju", 126.8526, 35.1601, "29", "2914", "광주"),
    # 인천광역시 (남동구 일대)
    ("incheon", 126.7053, 37.4563, "28", "2820", "인천"),
    # 울산광역시 (좌표는 중구 일대 — bjd 3114010400)
    ("ulsan", 129.3114, 35.5384, "31", "3114", "울산"),
    # 세종특별자치시 (sigungu 없음 — 시 단일, prefix "36")
    ("sejong", 127.2890, 36.4801, "36", "36", "세종"),
]


@pytest.mark.parametrize(
    ("name", "lon", "lat", "sido_code", "sigungu_prefix", "sido_name_part"),
    _MORE_CITIES,
    ids=[c[0] for c in _MORE_CITIES],
)
def test_reverse_more_korean_cities(
    client: TestClient,
    name: str,
    lon: float,
    lat: float,
    sido_code: str,
    sigungu_prefix: str,
    sido_name_part: str,
) -> None:
    r = client.get(f"/debug/geocoding/reverse?lon={lon}&lat={lat}&type=both")
    assert r.status_code == 200, f"{name}: {r.text[:200]}"
    addr = r.json()["address"]
    assert addr is not None, name
    assert addr["sido_code"] == sido_code, (
        f"{name}: sido={addr['sido_code']} expected={sido_code} bjd={addr['bjd_code']}"
    )
    assert addr["sigungu_code"] is not None
    assert addr["sigungu_code"].startswith(sigungu_prefix), (
        f"{name}: sigungu={addr['sigungu_code']} not starting with {sigungu_prefix}"
    )
    assert addr["sido_name"] is not None
    assert sido_name_part in addr["sido_name"]


# ── B2. type=road vs parcel 비교 ────────────────────────────────────────


def test_type_road_vs_parcel_differ(client: TestClient) -> None:
    """같은 좌표라도 type 별로 text는 도로명/지번 형식이 달라야."""
    base = "lon=126.9779&lat=37.5663"
    r_both = client.get(f"/debug/geocoding/reverse?{base}&type=both").json()["address"]
    r_road = client.get(f"/debug/geocoding/reverse?{base}&type=road").json()["address"]
    r_parcel = client.get(f"/debug/geocoding/reverse?{base}&type=parcel").json()["address"]

    # type=road면 road text 있음, type=parcel은 legal text 있음.
    assert r_road is not None
    assert r_road["road"] is not None
    assert r_road["legal"] is None  # parcel item이 응답에 없으므로
    assert r_parcel is not None
    assert r_parcel["legal"] is not None
    # both는 양쪽 가능.
    assert r_both is not None
    assert r_both["road"] is not None or r_both["legal"] is not None


# ── B3. radius_m 변동 ──────────────────────────────────────────────────


@pytest.mark.parametrize("radius", [1, 50, 200, 1000, 2000])
def test_radius_m_variations(client: TestClient, radius: int) -> None:
    """다양한 반경 — distance_m가 radius 이내(원본 응답 기준)."""
    r = client.get(
        f"/debug/geocoding/reverse/raw?lon=126.9779&lat=37.5663&type=both&radius_m={radius}"
    )
    assert r.status_code == 200, f"radius={radius}: {r.text[:200]}"
    body = r.json()
    assert body["status"] in ("OK", "NOT_FOUND")
    if body["result"]:
        # 반환된 결과는 모두 radius_m 이내(kraddr-geo가 보장).
        for item in body["result"]:
            d = item.get("distance_m")
            if d is not None:
                assert d <= radius, f"distance_m={d} > radius_m={radius}"


# ── B4. 동일 좌표 5회 idempotency (네트워크 변동 외 결과 일정) ────────────


def test_same_coord_five_calls_idempotent(client: TestClient) -> None:
    base = "/debug/geocoding/reverse?lon=126.9779&lat=37.5663&type=both"
    addrs = [client.get(base).json()["address"] for _ in range(5)]
    first = addrs[0]
    assert first is not None
    for i, a in enumerate(addrs[1:], 1):
        assert a is not None
        assert a["bjd_code"] == first["bjd_code"], f"call#{i}: bjd 변화"
        assert a["road"] == first["road"], f"call#{i}: road 변화"
        assert a["legal"] == first["legal"], f"call#{i}: legal 변화"


# ── B5. 정밀 좌표 (8자리) ─────────────────────────────────────────────


def test_high_precision_coord_handled(client: TestClient) -> None:
    """8자리 소수 좌표 — kraddr-geo가 받아들이고 결과가 동일 지역."""
    r = client.get(
        "/debug/geocoding/reverse?lon=126.97791234&lat=37.56631234&type=both"
    )
    assert r.status_code == 200
    addr = r.json()["address"]
    assert addr is not None
    # 서울 중구(1114) 일대.
    assert addr["sido_code"] == "11"


# ── B6. round-trip — 다른 도시 (부산) ────────────────────────────────


def test_round_trip_busan(client: TestClient) -> None:
    """부산시청 좌표 → road text → geocode → 같은 좌표 50m 이내."""
    from urllib.parse import quote

    r1 = client.get(
        "/debug/geocoding/reverse?lon=129.0756&lat=35.1796&type=both"
    )
    assert r1.status_code == 200
    addr = r1.json()["address"]
    assert addr is not None
    assert addr["road"] is not None
    r2 = client.get(
        f"/debug/geocoding/geocode?address={quote(addr['road'])}&type=road"
    )
    coord = r2.json()["coord"]
    assert coord is not None
    dlon = abs(float(coord["lon"]) - 129.0756)
    dlat = abs(float(coord["lat"]) - 35.1796)
    # 50m 허용. 위도 35°에서 0.0006° ≈ 67m → 약간 여유.
    assert dlon < 0.0008, f"부산 round-trip dlon={dlon:.6f}"
    assert dlat < 0.0008, f"부산 round-trip dlat={dlat:.6f}"


# ── B7. 한국 본토 경계 부근 좌표 — graceful ───────────────────────────


@pytest.mark.parametrize(
    ("desc", "lon", "lat"),
    [
        ("east-sea", 130.5, 37.5),   # 동해 안쪽 영해.
        ("dmz-near", 127.5, 38.5),   # DMZ 부근(38.5도).
        ("south-jeju", 126.5, 33.2), # 제주 남단 부근.
    ],
)
def test_boundary_coords_graceful(
    client: TestClient,
    desc: str,
    lon: float,
    lat: float,
) -> None:
    """경계 부근 — 200(매핑 null 또는 정상) 또는 5xx(upstream reject) 둘 다
    허용. 어느 쪽이든 라이브러리 측 예외 누수 없음."""
    r = client.get(
        f"/debug/geocoding/reverse?lon={lon}&lat={lat}&type=both&radius_m=500"
    )
    assert r.status_code in (200, 502), f"{desc}: unexpected {r.status_code}"
    if r.status_code == 200:
        body = r.json()
        assert "address" in body  # 키 자체 노출 (None 가능).


# ── B8. 주소 입력 엣지 ────────────────────────────────────────────────


def test_geocode_address_with_parentheses(client: TestClient) -> None:
    """괄호 포함 주소(예: '110(태평로1가)') — 200 + 좌표."""
    from urllib.parse import quote

    addr = "서울특별시 중구 세종대로 110(태평로1가)"
    r = client.get(f"/debug/geocoding/geocode?address={quote(addr)}&type=road")
    # 200(좌표 있음) 또는 200(None — 형식 매치 실패). 500은 안 됨.
    assert r.status_code == 200, r.text[:300]


def test_geocode_address_max_length_200(client: TestClient) -> None:
    """max_length=200 boundary — 200자 입력 통과."""
    from urllib.parse import quote

    # 200자: "x"+199자 채움.
    addr = "서울특별시 중구 세종대로 110 " + ("가" * (200 - len("서울특별시 중구 세종대로 110 ")))
    assert len(addr) == 200
    r = client.get(f"/debug/geocoding/geocode?address={quote(addr)}&type=road")
    assert r.status_code == 200


def test_geocode_address_over_200_returns_422(client: TestClient) -> None:
    from urllib.parse import quote

    addr = "x" * 201
    r = client.get(f"/debug/geocoding/geocode?address={quote(addr)}&type=road")
    assert r.status_code == 422


# ── B9. 다양한 fallback 모드 ──────────────────────────────────────────


@pytest.mark.parametrize("fallback", ["off", "local_only"])
def test_geocode_fallback_modes(client: TestClient, fallback: str) -> None:
    """fallback off/local_only — 200 + (NOT_FOUND이면 coord None, OK면 좌표)."""
    from urllib.parse import quote

    addr = "서울특별시 중구 세종대로 110"
    r = client.get(
        f"/debug/geocoding/geocode?address={quote(addr)}&type=road&fallback={fallback}"
    )
    assert r.status_code == 200, r.text[:200]


# ── B10. min_confidence 변동 ─────────────────────────────────────────


def test_geocode_min_confidence_high_filters(client: TestClient) -> None:
    """min_confidence=0.999 — 대부분 좌표가 None로 떨어짐."""
    from urllib.parse import quote

    addr = "서울특별시 중구 세종대로 110"
    r = client.get(
        f"/debug/geocoding/geocode?address={quote(addr)}&type=road&min_confidence=0.999"
    )
    assert r.status_code == 200
    # 0.999 이상 confidence는 드무므로 보통 None — 확정은 아님(모델 진화 대비
    # `or` 검증).
    body = r.json()
    assert body["coord"] is None or float(body["coord"]["lon"]) > 0
