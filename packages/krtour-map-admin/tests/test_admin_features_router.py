"""``/admin/features`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.admin_feature_repo import (
    AdminFeaturePage,
    AdminFeatureRow,
    FeatureDeactivateResult,
    FeatureOverride,
)

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(AdminSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _feature_row() -> AdminFeatureRow:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return AdminFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="광화문",
        category="01070300",
        status="active",
        lon=126.9769,
        lat=37.5759,
        address_label="서울특별시 종로구",
        primary_provider="python-mois-api",
        primary_dataset_key="mois_license_features_bulk",
        issue_count=1,
        issues=(
            {
                "violation_key": "issue-1",
                "violation_type": "missing_address",
                "severity": "warning",
                "message": "주소 누락",
                "detected_at": now,
            },
        ),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
def test_admin_features_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/admin/features" in spec["paths"]
    assert "/admin/features/{feature_id}/deactivate" in spec["paths"]
    assert "AdminFeatureRecord" in spec["components"]["schemas"]


@pytest.mark.unit
def test_list_admin_features_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _list(_session: Any, **kwargs: Any) -> AdminFeaturePage:
        assert kwargs["q"] == "광화문"
        assert kwargs["kinds"] == ["place"]
        assert kwargs["statuses"] == ["inactive"]
        assert kwargs["providers"] == ["python-mois-api"]
        assert kwargs["page_size"] == 25
        assert kwargs["sort"] == "issue_count"
        assert kwargs["order"] == "desc"
        return AdminFeaturePage(items=(_feature_row(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_admin_features", _list)

    response = client.get(
        "/admin/features",
        params={
            "q": "광화문",
            "kind": "place",
            "status": "inactive",
            "provider": "python-mois-api",
            "page_size": "25",
            "sort": "issue_count",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["feature_id"] == "feature-1"
    assert body["data"]["next_cursor"] == "next"
    assert body["meta"]["order"] == "desc"


@pytest.mark.unit
def test_deactivate_feature_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    now = datetime(2026, 6, 3, tzinfo=UTC)

    async def _deactivate(_session: Any, feature_id: str, **kwargs: Any) -> Any:
        assert feature_id == "feature-1"
        assert kwargs["reason"] == "운영상 제외"
        assert kwargs["operator"] == "local-admin"
        assert kwargs["prevent_provider_reactivation"] is True
        return FeatureDeactivateResult(
            feature_id="feature-1",
            previous_status="active",
            status="inactive",
            override_created=True,
            override=FeatureOverride(
                override_key="override-1",
                feature_id="feature-1",
                field_path="status",
                override_value="inactive",
                prevent_provider_reactivation=True,
                reason="운영상 제외",
                created_by="local-admin",
                created_at=now,
            ),
        )

    monkeypatch.setattr(router_mod, "deactivate_feature", _deactivate)

    response = client.post(
        "/admin/features/feature-1/deactivate",
        json={
            "reason": "운영상 제외",
            "operator": "local-admin",
            "prevent_provider_reactivation": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["override_created"] is True
    assert session.begin_count == 1


@pytest.mark.unit
def test_deactivate_missing_feature_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_features as router_mod

    async def _missing(_session: Any, _feature_id: str, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(router_mod, "deactivate_feature", _missing)

    response = client.post(
        "/admin/features/missing/deactivate",
        json={"reason": "없음"},
    )

    assert response.status_code == 404
