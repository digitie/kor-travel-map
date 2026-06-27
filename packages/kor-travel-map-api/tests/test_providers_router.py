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
        # sync-state row 먼저, 그 다음 policy-only row — 순서/필드 보존. (never-run
        # 카탈로그 row는 그 뒤에 붙으므로 prefix만 검증한다.)
        assert [item["provider"] for item in items[:2]] == [
            "python-mois-api",
            "python-kma-api",
        ]
        assert items[0]["refresh_policy"]["targeted_policy"] == "allow_targeted"
        assert "cursor" not in items[0]
        # policy-only row(state 없음)는 not_synced — 기존 동작 보존.
        assert items[1]["status"] == "not_synced"
        # 카탈로그 never-run row가 추가로 붙는다 (kma_weather_values는 카탈로그에
        # 없는 합성 dataset이므로 policy-only로 남고, 실제 카탈로그 dataset이
        # never_run으로 나온다).
        statuses = {item["status"] for item in items}
        assert "never_run" in statuses
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_ops_providers_list_includes_never_run_catalog_providers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sync state·policy가 전혀 없어도 카탈로그 feature-load provider는 노출된다.

    이전엔 provider_sync_state row가 있는 provider만 나와 mois/knps/krheritage가
    빠졌다. 이제는 never-run dataset이 status='never_run' + null timestamp로 나온다.
    """
    from kortravelmap.api.routers import providers as mod

    async def _empty_states(_s: Any) -> list[SyncState]:
        return []

    async def _empty_policies(_s: Any, **_kw: Any) -> tuple[ProviderRefreshPolicy, ...]:
        return ()

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _empty_states)
    monkeypatch.setattr(mod, "list_provider_refresh_policies", _empty_policies)
    _override_session(client)
    try:
        response = client.get("/v1/ops/providers")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        by_key = {(i["provider"], i["dataset_key"]): i for i in items}
        # 이전엔 누락되던 provider들이 never_run으로 나온다.
        for provider, dataset_key in (
            ("python-mois-api", "mois_license_features_bulk"),
            ("python-knps-api", "knps_visitor_centers"),
            ("python-krheritage-api", "krheritage_heritage_features"),
            ("python-mcst-api", "mcst_world_restaurants_csv"),
        ):
            row = by_key[(provider, dataset_key)]
            assert row["status"] == "never_run"
            assert row["last_success_at"] is None
            assert row["last_failure_at"] is None
            assert row["consecutive_failures"] == 0
            # never-run이어도 운영 링크는 보존.
            assert {link["rel"] for link in row["links"]} >= {
                "feature_update_requests",
                "refresh_policy",
            }
        # 가격 시계열(PriceValue, is_feature_load=False)은 never-run 목록에 없다.
        assert ("python-opinet-api", "opinet_gas_station_prices") not in by_key
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.unit
def test_ops_providers_list_preserves_synced_rows_alongside_never_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sync state가 있는 row는 기존 필드/값을 그대로 유지하면서 never-run과 공존한다."""
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
        return ()

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(mod, "list_provider_refresh_policies", _policies)
    _override_session(client)
    try:
        response = client.get("/v1/ops/providers")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        by_key = {(i["provider"], i["dataset_key"]): i for i in items}
        synced = by_key[("python-mois-api", "mois_license_features_bulk")]
        assert synced["status"] == "active"
        assert synced["last_success_at"].startswith("2026-06-12")
        assert "cursor" not in synced
        # 같은 provider의 다른 dataset(closed)은 never-run으로 나온다.
        closed = by_key[("python-mois-api", "mois_license_features_closed")]
        assert closed["status"] == "never_run"
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
        assert dataset["sync_states"][0]["cursor"] == {"last_modified": "2026-06-12"}
        assert dataset["refresh_policy"]["max_concurrent"] == 2
        assert dataset["recent_update_requests"][0]["request_id"].startswith("11111111")
        assert {link["rel"] for link in dataset["links"]} >= {
            "feature_update_requests",
            "create_feature_update_request",
            "refresh_policy",
        }
    finally:
        client.app.dependency_overrides.clear()
