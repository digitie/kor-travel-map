"""``test_routers`` — admin 첫 라우터 health/version (PR#35, ADR-031/035).

본 PR 테스트 범위:
- ``GET /debug/health`` 정적 200 OK + schema 정합
- ``GET /debug/version`` admin + krtour_map version 응답
- ``debug_routes_enabled=False`` 시 라우터 unregister 검증
- ``features_routes_enabled=False`` 시 DB 의존 features/admin/ops unregister 검증
- ``app.openapi()``가 ``HealthResponse`` + ``VersionResponse`` 스키마를 노출
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from krtour.map import __version__ as KRTOUR_MAP_VERSION

from krtour.map_admin import __version__ as ADMIN_VERSION
from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    """기본 settings로 만든 client (debug routes 활성)."""
    app = create_app(AdminSettings())
    return TestClient(app)


@pytest.mark.unit
def test_health_returns_ok(client: TestClient) -> None:
    """``GET /debug/health`` 200 + ``status='ok'`` + service 식별자."""
    response = client.get("/debug/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "service": "krtour-map-admin"}


@pytest.mark.unit
def test_health_extra_fields_rejected_on_response_schema(client: TestClient) -> None:
    """응답 schema가 ``extra='forbid'`` — 응답 키가 정확히 status/service만."""
    response = client.get("/debug/health")
    body = response.json()
    assert set(body.keys()) == {"status", "service"}


@pytest.mark.unit
def test_version_returns_both_versions(client: TestClient) -> None:
    """``GET /debug/version`` — admin + krtour_map version 모두 응답."""
    response = client.get("/debug/version")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "admin": ADMIN_VERSION,
        "krtour_map": KRTOUR_MAP_VERSION,
    }
    # 둘 다 비어 있지 않다.
    assert body["admin"]
    assert body["krtour_map"]


@pytest.mark.unit
def test_debug_routes_disabled_unmounts_health_and_version() -> None:
    """``debug_routes_enabled=False``면 ``/debug/*`` 라우터 unmounted → 404."""
    app = create_app(AdminSettings(debug_routes_enabled=False))
    client = TestClient(app)
    assert client.get("/debug/health").status_code == 404
    assert client.get("/debug/version").status_code == 404


@pytest.mark.unit
def test_db_dependent_routes_follow_features_gate_by_default() -> None:
    """DB 없는 부팅 검증 모드에서는 features/admin/ops surface를 함께 닫는다."""
    app = create_app(AdminSettings(features_routes_enabled=False))
    client = TestClient(app)
    spec = client.get("/openapi.json").json()

    assert "/features" not in spec["paths"]
    assert "/admin/features" not in spec["paths"]
    assert "/admin/offline-uploads" not in spec["paths"]
    assert "/ops/import-jobs" not in spec["paths"]
    assert "/ops/dagster/summary" not in spec["paths"]
    assert client.get("/admin/offline-uploads").status_code == 404
    assert client.get("/ops/import-jobs").status_code == 404


@pytest.mark.unit
def test_admin_ops_route_gates_can_be_enabled_explicitly() -> None:
    """features를 닫아도 명시 flag로 admin/ops 라우터만 다시 열 수 있다."""
    app = create_app(
        AdminSettings(
            features_routes_enabled=False,
            admin_routes_enabled=True,
            ops_routes_enabled=True,
        )
    )
    spec = app.openapi()

    assert "/features" not in spec["paths"]
    assert "/admin/features" in spec["paths"]
    assert "/admin/offline-uploads" in spec["paths"]
    assert "/ops/import-jobs" in spec["paths"]
    assert "/ops/dagster/summary" in spec["paths"]


@pytest.mark.unit
def test_openapi_lists_health_and_version_routes(client: TestClient) -> None:
    """``GET /openapi.json``에 두 라우터 + 두 schema 노출."""
    spec = client.get("/openapi.json").json()
    assert "/debug/health" in spec["paths"]
    assert "/debug/version" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "HealthResponse" in schemas
    assert "VersionResponse" in schemas


@pytest.mark.unit
def test_openapi_title_and_version_match_package() -> None:
    """``app.openapi()``의 ``info.title``/``info.version``이 본 패키지 식별과 일치."""
    app = create_app(AdminSettings())
    spec = app.openapi()
    assert spec["info"]["title"] == "krtour-map-admin"
    assert spec["info"]["version"] == ADMIN_VERSION
