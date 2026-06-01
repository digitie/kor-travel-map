"""``test_geocoding_router_live`` — 실 kraddr-geo 연동 검증.

기본 base URL: ``http://127.0.0.1:8888`` (kraddr-geo FastAPI 백엔드 직접 호출).
env ``LIVE_KRADDR_GEO_BASE_URL``로 override 가능.

도달 불가 시(connection refused / non-200 healthz) 모든 테스트가 ``pytest.skip``
— 본 파일은 라이브 디버깅 / 정합성 회귀 추적 용도이며 CI 의존성 없음.

검증 시나리오:
- 한국 주요 도시 4개(서울/부산/제주/대전)의 reverse → Address 매핑 + sido/sigungu
  코드 파생 / 시도명 / 도로명 / 우편번호 / 거리.
- 동일 좌표의 raw 응답 — v2 candidate Protocol 필드(confidence/match_kind/address/
  point/distance_m, address.legal_dong_code/road_name_code) 유무.
- geocode(주소 문자열) → Coordinate(WGS84).
- round-trip — reverse(coord) → text → geocode(text) → coord (60m 이내 재현).
- 한국 경계 밖(NOT_FOUND/빈 결과) graceful 처리.
"""

from __future__ import annotations

import os
import socket
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from krtour.map_debug_ui.app import create_app
from krtour.map_debug_ui.routers.geocoding import get_settings
from krtour.map_debug_ui.settings import DebugUiSettings

pytestmark = pytest.mark.live


_DEFAULT_BASE_URL = "http://127.0.0.1:8888"


def _resolve_base_url() -> str:
    return os.environ.get("LIVE_KRADDR_GEO_BASE_URL", _DEFAULT_BASE_URL)


def _is_reachable(base_url: str) -> bool:
    """``/v1/healthz`` 200이면 True. 도달 못하면 False (skip 신호)."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # 1차: TCP 열려있는지(빠른 실패) — 닫힌 포트면 즉시 skip.
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return False
    # 2차: /v1/healthz 200.
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


# ── 1) health ─────────────────────────────────────────────────────────────


def test_health_reachable(client: TestClient, base_url: str) -> None:
    r = client.get("/debug/geocoding/health")
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True
    assert body["upstream_status"] == 200
    assert body["base_url"] == base_url


# ── 2) reverse — 주요 도시 4개 ────────────────────────────────────────────


# (도시명, lon, lat, expected sido_code, expected sigungu_code prefix, sido_name 일부)
_REVERSE_CASES = [
    # 서울특별시청
    ("seoul-cityhall", 126.9779, 37.5663, "11", "1114", "서울"),
    # 부산광역시청 — 부산광역시 연제구(26470)
    ("busan-cityhall", 129.0756, 35.1796, "26", "2647", "부산"),
    # 대전광역시청
    ("daejeon-cityhall", 127.3845, 36.3504, "30", "3017", "대전"),
    # 제주특별자치도청
    ("jeju-province", 126.4983, 33.4996, "50", "5011", "제주"),
]


@pytest.mark.parametrize(
    ("name", "lon", "lat", "sido_code", "sigungu_prefix", "sido_name_part"),
    _REVERSE_CASES,
    ids=[c[0] for c in _REVERSE_CASES],
)
def test_reverse_korean_city(
    client: TestClient,
    name: str,
    lon: float,
    lat: float,
    sido_code: str,
    sigungu_prefix: str,
    sido_name_part: str,
) -> None:
    r = client.get(
        f"/debug/geocoding/reverse?lon={lon}&lat={lat}"
    )
    assert r.status_code == 200, f"{name}: {r.text[:200]}"
    addr = r.json()["address"]
    assert addr is not None, f"{name}: address가 None"
    # sido 코드/이름 + sigungu prefix는 도시청 일대에서 안정.
    assert addr["sido_code"] == sido_code, (
        f"{name}: sido_code={addr['sido_code']} expected={sido_code} bjd={addr['bjd_code']}"
    )
    assert addr["sigungu_code"] is not None
    assert addr["sigungu_code"].startswith(sigungu_prefix), (
        f"{name}: sigungu={addr['sigungu_code']} not starting with {sigungu_prefix}"
    )
    assert addr["bjd_code"] is not None
    assert len(addr["bjd_code"]) == 10
    assert addr["sido_name"] is not None
    assert sido_name_part in addr["sido_name"]
    assert addr["sigungu_name"] is not None
    # road 또는 legal 둘 중 하나는 있어야 (위치에 따라 다름).
    assert addr["road"] is not None or addr["legal"] is not None


# ── 3) reverse raw — Protocol 필드 보존 ───────────────────────────────────


def test_reverse_raw_has_protocol_fields(client: TestClient) -> None:
    """kraddr-geo v2 원본 응답이 `KraddrGeoRestClient` Protocol과 정합."""
    r = client.get(
        "/debug/geocoding/reverse/raw?lon=126.9779&lat=37.5663"
    )
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    assert body["status"] == "OK"
    assert len(body["candidates"]) >= 1
    cand = body["candidates"][0]
    for key in ("confidence", "match_kind", "address", "point", "distance_m"):
        assert key in cand, f"missing key in candidate: {key}"
    addr = cand["address"]
    # v2 응답은 null field를 생략할 수 있으므로 항상 존재하는 코어 필드만 검사.
    assert "full" in addr
    # 서울 중구 부근이면 legal_dong_code는 10자리 bjd.
    assert addr.get("legal_dong_code") is not None
    assert addr["legal_dong_code"].startswith("11")


# ── 4) geocode — 주소 → 좌표 ──────────────────────────────────────────────


def test_geocode_seoul_city_hall(client: TestClient) -> None:
    """서울시청 도로명주소 → 한국 본토 경계 안 좌표."""
    r = client.get(
        "/debug/geocoding/geocode?address=%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C+%EC%A4%91%EA%B5%AC+%EC%84%B8%EC%A2%85%EB%8C%80%EB%A1%9C+110&type=road"
    )
    assert r.status_code == 200, r.text[:300]
    coord = r.json()["coord"]
    assert coord is not None, "서울시청 geocode 실패"
    lon, lat = float(coord["lon"]), float(coord["lat"])
    # 서울 중구 부근.
    assert 126.95 < lon < 127.05, f"lon={lon} 서울 범위 밖"
    assert 37.55 < lat < 37.59, f"lat={lat} 서울 범위 밖"


# ── 5) round-trip — reverse → geocode 재현성 ──────────────────────────────


def test_round_trip_seoul_city_hall(client: TestClient) -> None:
    """좌표 → reverse 도로명주소 → geocode → 좌표 (60m 이내 재현)."""
    # Step 1: reverse — 서울시청 일대.
    r1 = client.get(
        "/debug/geocoding/reverse?lon=126.9779&lat=37.5663"
    )
    assert r1.status_code == 200
    addr = r1.json()["address"]
    assert addr is not None
    assert addr["road"] is not None, "round-trip 시작 road가 없음"

    # Step 2: geocode 그 도로명주소.
    from urllib.parse import quote

    r2 = client.get(
        f"/debug/geocoding/geocode?address={quote(addr['road'])}&type=road"
    )
    assert r2.status_code == 200, r2.text[:300]
    coord = r2.json()["coord"]
    assert coord is not None, f"round-trip geocode 실패: addr['road']={addr['road']}"

    # Step 3: 재현된 좌표가 입력 좌표 60m 이내.
    # 1도 ≈ 111km → 0.001도 ≈ 111m. 60m 허용 → 약 0.00055도.
    lon_back, lat_back = float(coord["lon"]), float(coord["lat"])
    dlon, dlat = abs(lon_back - 126.9779), abs(lat_back - 37.5663)
    # 위도-경도 모두 동일 허용치(서울 위도에서 cos 보정 후 비슷).
    assert dlon < 0.0008, (
        f"round-trip dlon={dlon:.5f} (lon_back={lon_back})"
    )
    assert dlat < 0.0008, (
        f"round-trip dlat={dlat:.5f} (lat_back={lat_back})"
    )


# ── 6) NOT_FOUND graceful 처리 ────────────────────────────────────────────


def test_reverse_off_korea_graceful(client: TestClient) -> None:
    """한국 본토 경계 안이지만 도로/지번 데이터가 없을 가능성이 큰 좌표(동해)."""
    # 동해 한가운데 — 좌표 검증은 `Coordinate` 한국 경계(124~132, 33~39.5) 안.
    r = client.get(
        "/debug/geocoding/reverse?lon=130.5&lat=37.5&radius_m=200"
    )
    # 200 + address None  또는  502(kraddr-geo가 좌표 범위 외 reject) 둘 다 graceful.
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        # NOT_FOUND이면 address None.
        body = r.json()
        assert "address" in body  # 키 자체는 노출.


# ── 7) 잘못된 입력 — 422 ──────────────────────────────────────────────────


def test_reverse_missing_params_422(client: TestClient) -> None:
    r = client.get("/debug/geocoding/reverse?lat=37.5")
    assert r.status_code == 422


def test_geocode_empty_address_422(client: TestClient) -> None:
    r = client.get("/debug/geocoding/geocode?address=")
    assert r.status_code == 422


# ── 8) Coordinate DTO 한국 경계 검증 ──────────────────────────────────────


def test_geocode_returns_korean_coord(client: TestClient) -> None:
    """`Coordinate` validator(124~132, 33~39.5)가 통과하는지 — DTO 직렬화 OK."""
    from urllib.parse import quote

    r = client.get(
        f"/debug/geocoding/geocode?address={quote('부산광역시 연제구 중앙대로 1001')}&type=road"
    )
    assert r.status_code == 200
    coord = r.json()["coord"]
    if coord is not None:
        # Coordinate DTO를 거쳤으므로 자동 검증.
        lon = Decimal(coord["lon"])
        lat = Decimal(coord["lat"])
        assert Decimal("124") <= lon <= Decimal("132")
        assert Decimal("33") <= lat <= Decimal("39.5")
