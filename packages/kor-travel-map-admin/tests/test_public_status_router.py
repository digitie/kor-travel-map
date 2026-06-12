"""``GET /health`` / ``GET /version`` 라우터 테스트 (T-213h) — DB 무관."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kortravelmap.admin.app import create_app
from kortravelmap.admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(AdminSettings()))


@pytest.mark.unit
def test_public_status_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/health" in spec["paths"]
    assert "/version" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "PublicHealthResponse" in schemas
    assert "PublicVersionResponse" in schemas


@pytest.mark.unit
def test_public_health_liveness(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "kor-travel-map"
    assert "duration_ms" in body["meta"]


@pytest.mark.unit
def test_public_version(client: TestClient) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data["version"], str)
    assert data["version"]
    assert isinstance(data["kor_travel_map_version"], str)
    assert data["kor_travel_map_version"]
    assert data["openapi_version"]
    assert "commit" in data  # 미설정이면 None


@pytest.mark.unit
def test_public_version_commit_from_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_GIT_COMMIT", "abc1234")
    r = client.get("/version")
    assert r.json()["data"]["commit"] == "abc1234"


@pytest.mark.unit
def test_public_status_mounted_without_features() -> None:
    # liveness/version은 features_routes_enabled=False(DB 없는 부팅)에서도 떠야 한다.
    c = TestClient(create_app(AdminSettings(features_routes_enabled=False)))
    assert c.get("/health").status_code == 200
    assert c.get("/version").status_code == 200
