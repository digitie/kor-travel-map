"""``/v1/ops/datasets`` 계약/서비스 회귀 (#678)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
)
from kortravelmap.infra.pipeline_repo import PipelineExecution, PipelineProjectedJob
from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from kortravelmap.infra.sync_state_repo import SyncState

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_schedule import (
    DatasetScheduleIndex,
    DatasetScheduleState,
)
from kortravelmap.api.ops_dataset_schema import (
    OpsDatasetDetailData,
    OpsDatasetFreshness,
    OpsDatasetScheduleSummary,
    OpsDatasetScopeState,
    OpsDatasetsGridData,
    OpsIssueSummary,
)
from kortravelmap.api.ops_dataset_service import (
    OrphanMutationDisabledError,
    load_datasets_grid,
)
from kortravelmap.api.settings import ApiSettings

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def begin(self) -> _Tx:
        return _Tx()


@pytest.fixture
def client() -> TestClient:
    app = create_app(ApiSettings())

    async def _session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def _state(
    *,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
    last_success_at: datetime | None = _NOW,
    eligible_after: datetime | None = None,
) -> SyncState:
    return SyncState(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="default",
        status="active",
        cursor={},
        last_success_at=last_success_at,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=eligible_after,
    )


def _policy(
    *,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
    stale_after_minutes: int | None = 60,
    enabled: bool = True,
) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
        provider=provider,
        dataset_key=dataset_key,
        source_kind="openapi",
        targeted_policy="allow_targeted",
        system_interval_seconds=3600,
        optimal_interval_seconds=None,
        min_interval_seconds=60,
        max_requests_per_minute=60,
        max_requests_per_hour=None,
        max_requests_per_day=None,
        max_concurrent=1,
        burst_size=None,
        rate_limit_source={},
        config_source="db",
        enabled=enabled,
        created_at=_NOW,
        updated_at=_NOW,
        stale_after_minutes=stale_after_minutes,
    )


def _empty_detail() -> OpsDatasetDetailData:
    freshness = OpsDatasetFreshness(
        state="never_run",
        basis="unknown",
        sla_seconds=None,
        due_at=None,
        is_overdue=False,
        overdue_by_seconds=0,
    )
    return OpsDatasetDetailData(
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        catalog_state="canonical",
        orphan_reason=None,
        mutable=True,
        catalog=None,
        scopes=[
            OpsDatasetScopeState(
                sync_scope="default",
                status="never_run",
                cursor={},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                eligible_after=None,
                freshness=freshness,
            )
        ],
        schedule=OpsDatasetScheduleSummary(
            basis="not_scheduled",
            status=None,
            schedule_names=[],
            active_schedule_names=[],
            next_scheduled_at=None,
        ),
        schedule_source_status="ok",
        refresh_policy=None,
        recent_runs=[],
        recent_runs_next_cursor=None,
        pipeline_history_url=(
            "/v1/ops/pipeline/executions?provider=python-mois-api&"
            "dataset_key=mois_license_features_bulk"
        ),
        recent_events=[],
        dataset_issues=OpsIssueSummary(open_count=0, severity_counts={}),
        provider_issues=OpsIssueSummary(open_count=0, severity_counts={}),
    )


@pytest.mark.unit
def test_ops_datasets_openapi_exposes_hardened_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_states = {"queued", "running", "done", "failed", "cancelled"}
    assert "/v1/ops/datasets" in spec["paths"]
    row = spec["components"]["schemas"]["OpsDatasetGridRow"]
    assert {
        "eligible_after",
        "freshness",
        "schedule",
        "latest_execution",
        "catalog_state",
        "mutable",
        "dataset_issues",
        "provider_issues",
    } <= set(row["properties"])
    preview = spec["components"]["schemas"]["OpsDatasetPreviewData"]
    assert {"truncated", "total_items", "returned_items", "budget"} <= set(
        preview["properties"]
    )
    latest = spec["components"]["schemas"]["OpsDatasetLatestExecution"]
    assert {
        "id",
        "detail_url",
        "pair_status",
        "operation_member_id",
        "provider_datasets",
        "projected_job",
        "cancellation",
    } <= set(latest["properties"])
    assert {"operation_member_id", "projected_job", "cancellation"} <= set(
        latest["required"]
    )
    assert {
        "started_at",
        "finished_at",
        "dagster_run_id",
        "dagster_run_status",
        "trigger_kind",
        "operation_registry_version",
        "error_message",
    } <= set(latest["required"])
    assert latest["properties"]["id"]["format"] == "uuid"
    assert latest["properties"]["operation_member_id"]["format"] == "uuid"
    assert set(latest["properties"]["status"]["enum"]) == operation_states
    assert set(latest["properties"]["pair_status"]["enum"]) == operation_states
    assert "status_source" not in latest["properties"]
    pair = spec["components"]["schemas"]["OpsDatasetProviderDataset"]
    assert "operation_member_id" in pair["required"]
    assert pair["properties"]["operation_member_id"]["format"] == "uuid"
    assert set(pair["properties"]["status"]["enum"]) == operation_states
    assert "status_source" not in pair["properties"]
    projected = spec["components"]["schemas"]["OpsDatasetProjectedJob"]
    assert projected["properties"]["id"]["format"] == "uuid"
    assert set(projected["properties"]["status"]["enum"]) == operation_states
    detail = spec["components"]["schemas"]["OpsDatasetDetailData"]
    assert {"recent_runs_next_cursor", "pipeline_history_url"} <= set(
        detail["properties"]
    )
    assert "recent_runs_next_cursor" in detail["required"]
    cursor_schema = detail["properties"]["recent_runs_next_cursor"]
    assert {item["type"] for item in cursor_schema["anyOf"]} == {
        "string",
        "null",
    }


@pytest.mark.unit
def test_ops_datasets_requires_admin_gate() -> None:
    client = TestClient(create_app(ApiSettings(admin_proxy_secret="secret")))
    assert client.get("/v1/ops/datasets").status_code == 403


@pytest.mark.unit
def test_grid_endpoint_uses_application_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _grid(_session: object, **_kwargs: object) -> OpsDatasetsGridData:
        return OpsDatasetsGridData(
            items=[],
            schedule_source_status="unavailable",
            schedule_source_errors=["dagster down"],
        )

    monkeypatch.setattr(router_module, "load_datasets_grid", _grid)
    response = client.get("/v1/ops/datasets")
    assert response.status_code == 200
    assert response.json()["data"]["schedule_source_status"] == "unavailable"


@pytest.mark.unit
def test_detail_endpoint_uses_application_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _detail(*_args: object, **_kwargs: object) -> OpsDatasetDetailData:
        return _empty_detail()

    monkeypatch.setattr(router_module, "load_dataset_detail", _detail)
    response = client.get(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk"
    )
    assert response.status_code == 200
    assert (
        response.json()["data"]["recent_runs_coverage"]
        == "db_recorded_canonical_operations"
    )


@pytest.mark.unit
def test_orphan_policy_mutation_is_409_with_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _upsert(*_args: object, **_kwargs: object) -> ProviderRefreshPolicy:
        raise OrphanMutationDisabledError("catalog_missing_with_policy")

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    response = client.put(
        "/v1/ops/datasets/legacy/removed/refresh-policy",
        json={"source_kind": "openapi", "stale_after_minutes": 60},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ORPHAN_MUTATION_DISABLED"
    assert (
        response.json()["details"]["mutation_disabled_reason"]
        == "catalog_missing_with_policy"
    )


@pytest.mark.unit
def test_policy_mutation_accepts_explicit_stale_sla(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _upsert(*_args: object, **kwargs: object) -> ProviderRefreshPolicy:
        body = kwargs["body"]
        assert body.stale_after_minutes == 90
        return _policy(stale_after_minutes=90)

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    response = client.put(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/refresh-policy",
        json={"source_kind": "openapi", "stale_after_minutes": 90},
    )
    assert response.status_code == 200
    assert response.json()["data"]["stale_after_minutes"] == 90


@pytest.mark.unit
def test_fixture_preview_enforces_response_budget(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/data.go.kr-standard/"
        "datagokr_cultural_festivals/preview",
        json={"source": "fixture", "max_items": 1},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["returned_items"] == 1
    assert data["total_items"] >= 1
    assert data["truncated"] is (data["total_items"] > 1)
    assert data["budget"] == {
        "max_items": 1,
        "timeout_seconds": 5.0,
        "external_call_budget": 0,
    }


@pytest.mark.unit
def test_live_preview_request_is_typed_422(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/data.go.kr-standard/"
        "datagokr_cultural_festivals/preview",
        json={"source": "live", "max_items": 1},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_preview_without_fixture_capability_is_409(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/preview",
        json={"source": "fixture", "max_items": 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PREVIEW_NOT_SUPPORTED"
    assert response.json()["details"]["capability"] == "none"


@pytest.mark.unit
def test_fixture_registry_mismatch_is_structured_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _missing_fixture(*_args: object, **_kwargs: object) -> object:
        raise KeyError("fixture missing")

    monkeypatch.setattr(
        router_module, "run_dataset_fixture_preview", _missing_fixture
    )
    response = client.post(
        "/v1/ops/datasets/data.go.kr-standard/"
        "datagokr_cultural_festivals/preview",
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PREVIEW_REGISTRY_MISMATCH"
    assert response.json()["details"]["capability"] == "fixture"


@pytest.mark.unit
async def test_grid_calculates_freshness_and_keeps_time_meanings_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import ops_dataset_service as service

    eligible_after = _NOW + timedelta(minutes=10)
    next_scheduled_at = _NOW + timedelta(minutes=20)
    state = _state(eligible_after=eligible_after)
    policy = _policy(stale_after_minutes=60)
    dataset_issue = DatasetIntegrityIssueCount(
        provider=state.provider,
        dataset_key=state.dataset_key,
        open_total=2,
        by_severity={"error": 2},
    )
    provider_issue = DatasetIntegrityIssueCount(
        provider=state.provider,
        dataset_key=None,
        open_total=1,
        by_severity={"warning": 1},
    )
    latest = DatasetLatestExecution(
        provider=state.provider,
        dataset_key=state.dataset_key,
        execution=PipelineExecution(
            kind="update_request",
            id="11111111-1111-1111-1111-111111111111",
            status="running",
            created_at=_NOW,
            providers=(state.provider,),
            dataset_keys=(state.dataset_key,),
            provider_datasets=(),
            progress=None,
            current_stage=None,
            scope_type="provider_dataset",
            priority=50,
            run_mode="queued",
            operator=None,
            error_message=None,
            started_at=_NOW,
            finished_at=None,
            dagster_run_id="run-1",
            dagster_run_status=None,
            trigger_kind="update_request",
            operation_registry_version=None,
            requested_job_id="22222222-2222-2222-2222-222222222222",
            linked_job_count=1,
            projected_job=PipelineProjectedJob(
                id="22222222-2222-2222-2222-222222222222",
                job_kind="feature_update_request",
                status="running",
                progress=0,
                current_stage=None,
                error_message=None,
                created_at=_NOW,
                started_at=_NOW,
                finished_at=None,
                dagster_run_id="run-1",
                dagster_run_status=None,
                trigger_kind="update_request",
                operation_registry_version=None,
                load_batch_id=None,
                parent_job_id=None,
                depth=0,
            ),
        ),
        operation_member_id="22222222-2222-2222-2222-222222222222",
        pair_status="running",
    )
    schedule_index = DatasetScheduleIndex(
        source_status="ok",
        errors=(),
        by_dataset={
            (state.provider, state.dataset_key): DatasetScheduleState(
                basis="dagster_definition_tags",
                status="RUNNING",
                schedule_names=("monthly",),
                active_schedule_names=("monthly",),
                next_scheduled_at=next_scheduled_at,
            )
        },
    )
    calls = {"latest": 0}

    async def _states(_session: object) -> list[SyncState]:
        return [state]

    async def _policies(
        _session: object,
    ) -> tuple[ProviderRefreshPolicy, ...]:
        return (policy,)

    async def _issues(
        _session: object, **_kwargs: object
    ) -> tuple[DatasetIntegrityIssueCount, ...]:
        return (dataset_issue, provider_issue)

    async def _latest(
        _session: object,
    ) -> tuple[DatasetLatestExecution, ...]:
        calls["latest"] += 1
        return (latest,)

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return schedule_index

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _policies)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _issues)
    monkeypatch.setattr(service, "list_latest_dataset_executions", _latest)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)

    data = await load_datasets_grid(
        cast(Any, object()),
        settings=ApiSettings(),
        dagster_client=cast(Any, object()),
        now=_NOW + timedelta(minutes=30),
    )
    row = next(
        item
        for item in data.items
        if (item.provider, item.dataset_key) == (state.provider, state.dataset_key)
    )
    assert row.eligible_after == eligible_after
    assert row.schedule.next_scheduled_at == next_scheduled_at
    assert row.freshness.state == "fresh"
    assert row.freshness.due_at == _NOW + timedelta(minutes=60)
    assert row.dataset_issues.open_count == 2
    assert row.provider_issues.open_count == 1
    assert row.latest_execution is not None
    assert row.latest_execution.status == "running"
    assert row.latest_execution.pair_status == "running"
    assert calls["latest"] == 1


@pytest.mark.unit
def test_freshness_unknown_without_explicit_sla_and_disabled_precedes_never_run() -> None:
    from kortravelmap.api.ops_dataset_service import _freshness

    unknown = _freshness(_state(), _policy(stale_after_minutes=None), now=_NOW)
    assert unknown.state == "unknown"
    assert unknown.basis == "unknown"
    disabled = _freshness(
        _state(last_success_at=None),
        _policy(stale_after_minutes=60, enabled=False),
        now=_NOW,
    )
    assert disabled.state == "disabled"

    due = _freshness(
        _state(last_success_at=_NOW),
        _policy(stale_after_minutes=60),
        now=_NOW + timedelta(minutes=60),
    )
    assert due.state == "overdue"
    assert due.is_overdue is True
    assert due.overdue_by_seconds == 0
