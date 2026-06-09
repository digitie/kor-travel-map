"""``GET /providers/{provider}/last-sync`` 라우터 (T-213g) — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.sync_state_repo import SyncState

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(AdminSettings()))


def _override_session(client: TestClient) -> None:
    from krtour.map_admin.db import get_session

    async def _fake() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake


@pytest.mark.unit
def test_providers_last_sync_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/providers/{provider}/last-sync" in spec["paths"]
    assert "ProviderLastSyncResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_provider_last_sync_404_when_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.routers import providers as mod

    async def _empty(_s: Any, **_kw: Any) -> list[SyncState]:
        return []

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _empty)
    _override_session(client)
    try:
        r = client.get("/v1/providers/python-mois-api/last-sync")
        assert r.status_code == 404
        assert "python-mois-api" in r.json()["error"]["message"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_provider_last_sync_200_excludes_cursor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.routers import providers as mod

    ts = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    state = SyncState(
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="default",
        status="active",
        cursor={"last_modified_date": "2026-06-01"},
        last_success_at=ts,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=None,
    )

    async def _list(_s: Any, **_kw: Any) -> list[SyncState]:
        return [state]

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _list)
    _override_session(client)
    try:
        r = client.get("/v1/providers/python-mois-api/last-sync")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["provider"] == "python-mois-api"
        assert body["data"]["count"] == 1
        item = body["data"]["items"][0]
        assert item["dataset_key"] == "mois_license_features_bulk"
        assert item["status"] == "active"
        assert item["last_success_at"].startswith("2026-06-01")
        # 내부 cursor는 노출하지 않는다.
        assert "cursor" not in item
    finally:
        client.app.dependency_overrides.clear()
