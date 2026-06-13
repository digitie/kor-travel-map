"""``/providers`` 라우터 (T-213g 단건 + T-217g 목록) — DB 무관(repo monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
)
from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from kortravelmap.infra.sync_state_repo import SyncState

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ApiSettings()))


def _override_session(client: TestClient) -> None:
    from kortravelmap.api.db import get_session

    async def _fake() -> AsyncIterator[Any]:
        yield object()

    client.app.dependency_overrides[get_session] = _fake


def _policy(
    *,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
) -> ProviderRefreshPolicy:
    now = datetime(2026, 6, 12, tzinfo=UTC)
    return ProviderRefreshPolicy(
        provider=provider,
        dataset_key=dataset_key,
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
        rate_limit_source={"provider_repo": "F:/dev/python-mois-api"},
        config_source="db",
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def _update_request() -> FeatureUpdateRequest:
    now = datetime(2026, 6, 12, tzinfo=UTC)
    return FeatureUpdateRequest(
        request_id="11111111-1111-1111-1111-111111111111",
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
        providers=(),
        dataset_keys=(),
        update_policy={},
        run_mode="queued",
        priority=50,
        status="queued",
        dry_run=False,
        matched_scope={"feature_count": 0},
        job_id="22222222-2222-2222-2222-222222222222",
        dagster_run_id=None,
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )


@pytest.mark.unit
def test_providers_last_sync_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/providers/{provider}/last-sync" in spec["paths"]
    assert "ProviderLastSyncResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_provider_last_sync_404_when_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import providers as mod

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
    assert "/v1/ops/providers" in spec["paths"]
    assert "/v1/ops/providers/{provider}" in spec["paths"]
    assert "ProvidersFreshnessResponse" in spec["components"]["schemas"]
    assert "OpsProviderDetailResponse" in spec["components"]["schemas"]


@pytest.mark.unit
def test_providers_freshness_empty_is_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import providers as mod

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
    from kortravelmap.api.routers import providers as mod

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
    from kortravelmap.api.routers import providers as mod

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


@pytest.mark.unit
def test_ops_providers_list_combines_sync_state_and_policy_only_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import providers as mod

    ts = datetime(2026, 6, 12, 1, 0, tzinfo=UTC)
    state = SyncState(
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="default",
        status="active",
        cursor={"hidden": True},
        last_success_at=ts,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=ts,
    )

    async def _states(_s: Any) -> list[SyncState]:
        return [state]

    async def _policies(_s: Any, **_kw: Any) -> tuple[ProviderRefreshPolicy, ...]:
        return (
            _policy(),
            _policy(provider="python-kma-api", dataset_key="kma_weather_values"),
        )

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(mod, "list_provider_refresh_policies", _policies)
    _override_session(client)
    try:
        response = client.get("/v1/ops/providers")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert [item["provider"] for item in items] == [
            "python-mois-api",
            "python-kma-api",
        ]
        assert items[0]["refresh_policy"]["targeted_policy"] == "allow_targeted"
        assert "cursor" not in items[0]
        assert items[1]["status"] == "not_synced"
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_ops_provider_detail_includes_cursor_policy_and_recent_requests(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import providers as mod

    ts = datetime(2026, 6, 12, 1, 0, tzinfo=UTC)
    state = SyncState(
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope="kr",
        status="active",
        cursor={"last_modified": "2026-06-12"},
        last_success_at=ts,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=ts,
    )

    async def _states(_s: Any, **kwargs: Any) -> list[SyncState]:
        assert kwargs["provider"] == "python-mois-api"
        return [state]

    async def _policies(_s: Any, **kwargs: Any) -> tuple[ProviderRefreshPolicy, ...]:
        assert kwargs["provider"] == "python-mois-api"
        return (_policy(),)

    async def _requests(_s: Any, **kwargs: Any) -> FeatureUpdateRequestPage:
        assert kwargs["provider"] == "python-mois-api"
        assert kwargs["dataset_key"] == "mois_license_features_bulk"
        assert kwargs["scope_type"] == "provider_dataset"
        return FeatureUpdateRequestPage(items=(_update_request(),), next_cursor=None)

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _states)
    monkeypatch.setattr(mod, "list_provider_refresh_policies", _policies)
    monkeypatch.setattr(mod, "list_update_requests", _requests)
    _override_session(client)
    try:
        response = client.get("/v1/ops/providers/python-mois-api")
        assert response.status_code == 200
        data = response.json()["data"]
        dataset = data["datasets"][0]
        assert dataset["sync_states"][0]["cursor"] == {
            "last_modified": "2026-06-12"
        }
        assert dataset["refresh_policy"]["max_concurrent"] == 2
        assert dataset["recent_update_requests"][0]["request_id"].startswith(
            "11111111"
        )
        assert {
            link["rel"] for link in dataset["links"]
        } >= {
            "feature_update_requests",
            "create_feature_update_request",
            "refresh_policy",
        }
    finally:
        client.app.dependency_overrides.clear()
