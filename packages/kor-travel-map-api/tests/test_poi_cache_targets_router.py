"""POI/cache target admin API와 by-target feature 조회 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_repo import NearbyFeaturePage, NearbyFeatureRow
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    PoiCacheTargetPage,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


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
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            service_token=None,
            admin_destructive_enabled=True,
            public_api_key_required=False,
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _target(*, target_key: str = "poi-1") -> PoiCacheTarget:
    now = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    return PoiCacheTarget(
        target_id="target-1",
        external_system="external-app",
        target_key=target_key,
        name="서울시청",
        lon=126.978,
        lat=37.5665,
        coord_precision_digits=6,
        coord_key="126.978000:37.566500:p6",
        radius_km=5.0,
        scope_mode="center_radius",
        update_enabled=True,
        refresh_policy="provider_default",
        provider_overrides={},
        metadata={"external_poi_id": target_key},
        last_seen_at=now,
        last_requested_at=None,
        last_refreshed_at=None,
        last_failed_at=None,
        next_eligible_refresh_at=None,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )


def _nearby_row() -> NearbyFeatureRow:
    now = datetime(2026, 6, 3, 12, 5, tzinfo=UTC)
    return NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="주변 주유소",
        category="06020000",
        status="active",
        lon=126.98,
        lat=37.56,
        distance_m=320.5,
        primary_provider="python-opinet-api",
        primary_dataset_key="opinet_stations",
        last_updated_at=now,
    )


@pytest.mark.unit
def test_poi_cache_target_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/poi-cache-targets" in spec["paths"]
    assert "/v1/admin/poi-cache-targets/{external_system}/{target_key}" in spec["paths"]
    assert "/v1/features/nearby/by-target" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "PoiCacheTargetUpsertRequest" in schemas
    assert "FeaturesNearbyByTargetResponse" in schemas
    assert set(schemas["PoiCacheTargetListResponse"]["properties"]) == {"data", "meta"}
    assert "next_cursor" not in schemas["PoiCacheTargetListData"]["properties"]
    upsert_props = schemas["PoiCacheTargetUpsertRequest"]["properties"]
    assert "metadata" in upsert_props
    assert "metadata_" not in upsert_props
    assert upsert_props["provider_overrides"]["maxProperties"] == 64


@pytest.mark.unit
def test_put_poi_cache_target_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _upsert(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        assert kwargs["lon"] == 126.978
        assert kwargs["on_conflict"] == "reject"
        assert kwargs["provider_overrides"] == {
            "python-kma-api:kma_weather_alerts": {
                "targeted_policy": "allow_targeted",
                "min_interval_seconds": 300,
            }
        }
        assert kwargs["metadata"] == {
            "external_poi_id": "poi-1",
            "labels": ["city"],
        }
        return _target()

    monkeypatch.setattr(router_mod, "upsert_poi_cache_target", _upsert)

    response = client.put(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        json={
            "coord": {"lon": 126.978, "lat": 37.5665},
            "radius_km": 5.0,
            "provider_overrides": {
                "python-kma-api:kma_weather_alerts": {
                    "targeted_policy": "allow_targeted",
                    "min_interval_seconds": 300,
                }
            },
            "metadata": {"external_poi_id": "poi-1", "labels": ["city"]},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["coord_key"] == "126.978000:37.566500:p6"
    assert response.json()["data"]["metadata"] == {"external_poi_id": "poi-1"}
    assert session.begin_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"unknown": True}},
        {"provider_overrides": {"python-a-api": {"unknown": True}}},
        {
            "provider_overrides": {
                f"python-provider-{index}": {"targeted_policy": "allow_targeted"}
                for index in range(65)
            }
        },
    ],
)
def test_put_poi_cache_target_rejects_unbounded_payloads_before_transaction(
    client: TestClient,
    session: _FakeSession,
    payload: dict[str, Any],
) -> None:
    body: dict[str, Any] = {"coord": {"lon": 126.978, "lat": 37.5665}}
    body.update(payload)

    response = client.put("/v1/admin/poi-cache-targets/external-app/poi-1", json=body)

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_put_poi_cache_target_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _conflict(_session: Any, **_kwargs: Any) -> PoiCacheTarget:
        raise PoiCacheTargetConflict("coord conflict")

    monkeypatch.setattr(router_mod, "upsert_poi_cache_target", _conflict)

    response = client.put(
        "/v1/admin/poi-cache-targets/external-app/poi-1",
        json={"coord": {"lon": 126.978, "lat": 37.5665}},
    )

    assert response.status_code == 409
    assert "coord conflict" in response.json()["detail"]


@pytest.mark.unit
def test_list_poi_cache_targets_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _list(_session: Any, **kwargs: Any) -> PoiCacheTargetPage:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["update_enabled"] is True
        assert kwargs["include_deleted"] is False
        assert kwargs["limit"] == 25
        assert kwargs["cursor"] == "cursor-1"
        return PoiCacheTargetPage(items=(_target(),), next_cursor="cursor-2")

    monkeypatch.setattr(router_mod, "list_poi_cache_targets", _list)

    response = client.get(
        "/v1/admin/poi-cache-targets",
        params={
            "external_system": "external-app",
            "update_enabled": "true",
            "page_size": "25",
            "cursor": "cursor-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "cursor-2",
        "total": None,
    }
    assert body["data"]["items"][0]["target_key"] == "poi-1"


@pytest.mark.unit
def test_list_poi_cache_targets_rejects_invalid_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _list(_session: Any, **_kwargs: Any) -> PoiCacheTargetPage:
        raise ValueError("invalid poi cache target cursor")

    monkeypatch.setattr(router_mod, "list_poi_cache_targets", _list)

    response = client.get("/v1/admin/poi-cache-targets", params={"cursor": "bad"})

    assert response.status_code == 422
    assert "invalid poi cache target cursor" in response.json()["detail"]


@pytest.mark.unit
def test_get_poi_cache_target_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _missing(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(router_mod, "get_poi_cache_target_by_key", _missing)

    response = client.get("/v1/admin/poi-cache-targets/external-app/missing")

    assert response.status_code == 404


@pytest.mark.unit
def test_delete_poi_cache_target_uses_transaction(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import poi_cache_targets as router_mod

    async def _delete(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        return _target()

    monkeypatch.setattr(router_mod, "delete_poi_cache_target", _delete)

    response = client.delete("/v1/admin/poi-cache-targets/external-app/poi-1")

    assert response.status_code == 200
    assert response.json()["data"]["target_id"] == "target-1"
    assert session.begin_count == 1


@pytest.mark.unit
def test_features_nearby_by_target_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import features as features_mod

    async def _get_target(_session: Any, **kwargs: Any) -> PoiCacheTarget:
        assert kwargs["external_system"] == "external-app"
        assert kwargs["target_key"] == "poi-1"
        return _target()

    async def _nearby(_session: Any, **kwargs: Any) -> NearbyFeaturePage:
        assert kwargs["target_id"] == "target-1"
        assert kwargs["radius_km"] == 3.0
        assert kwargs["kinds"] == ["place"]
        assert kwargs["categories"] == ["06020000"]
        assert kwargs["statuses"] == ["active"]
        assert kwargs["providers"] == ["python-opinet-api"]
        assert kwargs["sort"] == "distance"
        assert kwargs["limit"] == 10
        return NearbyFeaturePage(items=(_nearby_row(),), next_cursor="next")

    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _get_target)
    monkeypatch.setattr(
        features_mod.feature_repo,
        "features_nearby_poi_cache_target",
        _nearby,
    )

    response = client.get(
        "/v1/features/nearby/by-target",
        params=[
            ("external_system", "external-app"),
            ("target_key", "poi-1"),
            ("radius_km", "3.0"),
            ("kind", "place"),
            ("category", "06020000"),
            ("status", "active"),
            ("provider", "python-opinet-api"),
            ("page_size", "10"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["target"]["target_key"] == "poi-1"
    assert set(body["data"]["target"]) == {
        "external_system",
        "target_key",
        "lon",
        "lat",
    }
    assert body["data"]["items"][0]["distance_m"] == 320.5
    assert "primary_provider" not in body["data"]["items"][0]
    assert "primary_dataset_key" not in body["data"]["items"][0]
    assert body["meta"]["page"] == {
        "page_size": 10,
        "next_cursor": "next",
        "total": None,
    }


@pytest.mark.unit
def test_features_nearby_by_target_404_when_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import features as features_mod

    async def _missing(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(features_mod, "get_poi_cache_target_by_key", _missing)

    response = client.get(
        "/v1/features/nearby/by-target",
        params={"external_system": "external-app", "target_key": "missing"},
    )

    assert response.status_code == 404
