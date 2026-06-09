"""``test_routers`` — app 라우터 mount/gate 검증.

본 테스트 범위:
- ``/debug/health``·``/debug/version`` **제거** 검증(T-214h/ADR-048 clean cut) — 공용
  liveness는 ``/health``·``/version``(public_status, `test_public_status_router`) +
  ``/ops/health-deep``으로 수렴.
- ``debug_routes_enabled=False`` 시 ``/debug/*``(etl) unregister.
- ``features_routes_enabled=False`` 시 DB 의존 features/admin/ops unregister.
- ``app.openapi()`` info.title/version 정합.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from krtour.map_admin import __version__ as ADMIN_VERSION
from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    """기본 settings로 만든 client (debug routes 활성)."""
    app = create_app(AdminSettings())
    return TestClient(app)


@pytest.mark.unit
def test_debug_health_version_removed(client: TestClient) -> None:
    """``/debug/health``·``/debug/version``은 제거됐다 (404 + openapi 미노출)."""
    assert client.get("/debug/health").status_code == 404
    assert client.get("/debug/version").status_code == 404
    spec = client.get("/openapi.json").json()
    assert "/debug/health" not in spec["paths"]
    assert "/debug/version" not in spec["paths"]
    # 공용 liveness는 비버저닝 /health·/version으로 수렴.
    assert "/health" in spec["paths"]
    assert "/version" in spec["paths"]


@pytest.mark.unit
def test_debug_routes_disabled_unmounts_etl() -> None:
    """``debug_routes_enabled=False``면 ``/debug/*``(etl) unmounted → 404."""
    app = create_app(AdminSettings(debug_routes_enabled=False))
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    assert not any(p.startswith("/debug/") for p in spec["paths"])


@pytest.mark.unit
def test_db_dependent_routes_follow_features_gate_by_default() -> None:
    """DB 없는 부팅 검증 모드에서는 features/admin/ops surface를 함께 닫는다."""
    app = create_app(AdminSettings(features_routes_enabled=False))
    client = TestClient(app)
    spec = client.get("/openapi.json").json()

    assert "/v1/features" not in spec["paths"]
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

    assert "/v1/features" not in spec["paths"]
    assert "/admin/features" in spec["paths"]
    assert "/admin/offline-uploads" in spec["paths"]
    assert "/ops/import-jobs" in spec["paths"]
    assert "/ops/dagster/summary" in spec["paths"]


@pytest.mark.unit
def test_openapi_title_and_version_match_package() -> None:
    """``app.openapi()``의 ``info.title``/``info.version``이 본 패키지 식별과 일치."""
    app = create_app(AdminSettings())
    spec = app.openapi()
    assert spec["info"]["title"] == "krtour-map-admin"
    assert spec["info"]["version"] == ADMIN_VERSION
