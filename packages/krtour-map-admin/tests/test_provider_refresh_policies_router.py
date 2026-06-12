"""``/v1/admin/provider-refresh-policies`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.provider_refresh_policy_repo import ProviderRefreshPolicy

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


def _policy(
    *,
    enabled: bool = True,
) -> ProviderRefreshPolicy:
    now = datetime(2026, 6, 12, tzinfo=UTC)
    return ProviderRefreshPolicy(
        provider="python-kma-api",
        dataset_key="kma_weather_values",
        source_kind="openapi",
        targeted_policy="allow_targeted",
        system_interval_seconds=3600,
        optimal_interval_seconds=1800,
        min_interval_seconds=60,
        max_requests_per_minute=60,
        max_requests_per_hour=None,
        max_requests_per_day=None,
        max_concurrent=2,
        burst_size=5,
        rate_limit_source={"provider_repo": "F:/dev/python-kma-api"},
        config_source="db",
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
def test_provider_refresh_policy_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/provider-refresh-policies" in spec["paths"]
    assert (
        "/v1/admin/provider-refresh-policies/{provider}/{dataset_key}"
        in spec["paths"]
    )
    assert "ProviderRefreshPolicyResponse" in spec["components"]["schemas"]
    assert "ProviderRefreshPolicyUpsertRequest" in spec["components"]["schemas"]


@pytest.mark.unit
def test_list_provider_refresh_policies(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import provider_refresh_policies as mod

    async def _list(_session: Any, **kwargs: Any) -> tuple[ProviderRefreshPolicy, ...]:
        assert kwargs == {"provider": "python-kma-api", "enabled": True, "limit": 20}
        return (_policy(),)

    monkeypatch.setattr(mod, "list_provider_refresh_policies", _list)

    response = client.get(
        "/v1/admin/provider-refresh-policies"
        "?provider=python-kma-api&enabled=true&limit=20"
    )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["provider"] == "python-kma-api"
    assert item["targeted_policy"] == "allow_targeted"


@pytest.mark.unit
def test_get_provider_refresh_policy_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import provider_refresh_policies as mod

    async def _missing(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(mod, "get_provider_refresh_policy", _missing)

    response = client.get(
        "/v1/admin/provider-refresh-policies/python-kma-api/kma_weather_values"
    )

    assert response.status_code == 404
    assert "python-kma-api" in response.json()["detail"]


@pytest.mark.unit
def test_upsert_provider_refresh_policy(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import provider_refresh_policies as mod

    async def _upsert(_session: Any, **kwargs: Any) -> ProviderRefreshPolicy:
        assert kwargs["provider"] == "python-kma-api"
        assert kwargs["dataset_key"] == "kma_weather_values"
        assert kwargs["source_kind"] == "openapi"
        assert kwargs["system_interval_seconds"] == 3600
        assert kwargs["max_concurrent"] == 2
        return _policy(enabled=kwargs["enabled"])

    monkeypatch.setattr(mod, "upsert_provider_refresh_policy", _upsert)

    response = client.put(
        "/v1/admin/provider-refresh-policies/python-kma-api/kma_weather_values",
        json={
            "source_kind": "openapi",
            "targeted_policy": "allow_targeted",
            "system_interval_seconds": 3600,
            "optimal_interval_seconds": 1800,
            "min_interval_seconds": 60,
            "max_requests_per_minute": 60,
            "max_concurrent": 2,
            "burst_size": 5,
            "rate_limit_source": {"provider_repo": "F:/dev/python-kma-api"},
            "enabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
    assert session.begin_count == 1


@pytest.mark.unit
def test_upsert_rejects_rate_limit_exceeding_interval(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.put(
        "/v1/admin/provider-refresh-policies/python-kma-api/kma_weather_values",
        json={
            "source_kind": "openapi",
            "targeted_policy": "allow_targeted",
            "system_interval_seconds": 1,
            "max_requests_per_minute": 10,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0
