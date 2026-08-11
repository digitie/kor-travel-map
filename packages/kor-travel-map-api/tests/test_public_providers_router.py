"""공개 provider 신선도 계약 회귀."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.sync_state_repo import SyncState

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _override_session(client: TestClient) -> None:
    async def _fake() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake


def _state(
    *,
    provider: str = "python-mois-api",
    provider_dataset_id: int = 1,
) -> SyncState:
    return SyncState(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key="mois_license_features_bulk",
        sync_scope="dataset_wide",
        operation_key="feature_place_mois_licenses_job",
        status="active",
        cursor={"internal": "cursor"},
        last_success_at=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=None,
    )


@pytest.mark.unit
def test_public_provider_openapi_contains_only_two_provider_paths(
    client: TestClient,
) -> None:
    spec = client.get("/openapi.json").json()
    provider_paths = {path for path in spec["paths"] if path.startswith("/v1/providers")}
    assert provider_paths == {
        "/v1/providers",
        "/v1/providers/{provider}/last-sync",
    }
    assert "ProvidersFreshnessResponse" in spec["components"]["schemas"]
    assert "ProviderLastSyncResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_public_provider_list_is_bounded_and_hides_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import public_providers as module

    async def _list_all(_session: Any) -> list[SyncState]:
        return [_state(provider="python-kma-api", provider_dataset_id=2), _state()]

    monkeypatch.setattr(module.sync_state_repo, "list_all_sync_states", _list_all)
    _override_session(client)
    response = client.get("/v1/providers")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["provider"] for item in items] == [
        "python-kma-api",
        "python-mois-api",
    ]
    assert all("cursor" not in item for item in items)


@pytest.mark.unit
def test_public_provider_list_returns_empty_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import public_providers as module

    async def _empty(_session: Any) -> list[SyncState]:
        return []

    monkeypatch.setattr(module.sync_state_repo, "list_all_sync_states", _empty)
    _override_session(client)
    response = client.get("/v1/providers")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


@pytest.mark.unit
def test_public_provider_last_sync_forwards_exact_filters_and_hides_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import public_providers as module

    async def _list(_session: Any, **kwargs: Any) -> list[SyncState]:
        assert kwargs == {
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "sync_scope": "dataset_wide",
            # 실행 membership identity는 triple이다(ADR-088) — operation_key도
            # 그대로 repo까지 전달돼야 한다.
            "operation_key": "feature_place_mois_licenses_job",
        }
        return [_state()]

    monkeypatch.setattr(module.sync_state_repo, "list_sync_states", _list)
    _override_session(client)
    response = client.get(
        "/v1/providers/python-mois-api/last-sync"
        "?dataset_key=mois_license_features_bulk&sync_scope=dataset_wide"
        "&operation_key=feature_place_mois_licenses_job"
    )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["dataset_key"] == "mois_license_features_bulk"
    assert item["sync_scope"] == "dataset_wide"
    assert item["operation_key"] == "feature_place_mois_licenses_job"
    assert "cursor" not in item


@pytest.mark.unit
def test_public_provider_last_sync_returns_404_when_empty(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import public_providers as module

    async def _empty(_session: Any, **_kwargs: Any) -> list[SyncState]:
        return []

    monkeypatch.setattr(module.sync_state_repo, "list_sync_states", _empty)
    _override_session(client)
    response = client.get("/v1/providers/python-mois-api/last-sync")

    assert response.status_code == 404
    assert "python-mois-api" in response.json()["detail"]
