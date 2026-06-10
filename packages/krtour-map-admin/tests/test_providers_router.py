"""``/providers`` 라우터 (T-213g 단건 + T-217g 목록) — DB 무관(repo monkeypatch)."""

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
        assert "python-mois-api" in r.json()["detail"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_providers_freshness_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/providers" in spec["paths"]
    assert "ProvidersFreshnessResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_providers_freshness_empty_is_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.routers import providers as mod

    async def _empty(_s: Any) -> list[SyncState]:
        return []

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _empty)
    _override_session(client)
    try:
        r = client.get("/v1/providers")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["items"] == []
        assert "request_id" in body["meta"]
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_providers_freshness_lists_all_excludes_cursor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from krtour.map_admin.routers import providers as mod

    ok_ts = datetime(2026, 6, 9, 2, 0, tzinfo=UTC)
    fail_ts = datetime(2026, 6, 10, 2, 0, tzinfo=UTC)
    states = [
        SyncState(
            provider="python-kma-api",
            dataset_key="kma_weather_values",
            sync_scope="default",
            status="active",
            cursor={"base_date": "20260609"},
            last_success_at=ok_ts,
            last_failure_at=None,
            consecutive_failures=0,
            next_run_after=None,
        ),
        SyncState(
            provider="python-mois-api",
            dataset_key="mois_license_features_bulk",
            sync_scope="default",
            status="active",
            cursor={},
            last_success_at=ok_ts,
            last_failure_at=fail_ts,
            consecutive_failures=3,
            next_run_after=None,
        ),
    ]

    async def _list_all(_s: Any) -> list[SyncState]:
        return states

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _list_all)
    _override_session(client)
    try:
        r = client.get("/v1/providers")
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert [i["provider"] for i in items] == ["python-kma-api", "python-mois-api"]
        failing = items[1]
        assert failing["consecutive_failures"] == 3
        assert failing["last_failure_at"].startswith("2026-06-10")
        # 내부 cursor는 노출하지 않는다(T-213g와 동일 원칙).
        assert all("cursor" not in i for i in items)
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
        assert len(body["data"]["items"]) == 1
        item = body["data"]["items"][0]
        assert item["dataset_key"] == "mois_license_features_bulk"
        assert item["status"] == "active"
        assert item["last_success_at"].startswith("2026-06-01")
        # 내부 cursor는 노출하지 않는다.
        assert "cursor" not in item
    finally:
        client.app.dependency_overrides.clear()
