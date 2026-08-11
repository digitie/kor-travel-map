"""``/v1/ops/datasets`` 계약/서비스 회귀 (#678)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.dataset_status_repo import (
    DatasetExecutionSnapshot,
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
)
from kortravelmap.infra.pipeline_repo import (
    PipelineExecution,
    PipelineProjectedJob,
    PipelineProviderDatasetIdentity,
)
from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from kortravelmap.infra.sync_state_repo import SyncState

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import OPS_SCOPE_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_schedule import (
    DatasetScheduleIndex,
    DatasetScheduleState,
)
from kortravelmap.api.ops_dataset_schema import (
    OpsDatasetDetailData,
    OpsDatasetEventHistory,
    OpsDatasetFreshness,
    OpsDatasetRunHistory,
    OpsDatasetScheduleSummary,
    OpsDatasetScopeState,
    OpsDatasetsGridData,
    OpsIssueSummary,
)
from kortravelmap.api.ops_dataset_service import (
    OrphanMutationDisabledError,
    ProviderRefreshPolicyRevisionConflict,
    ProviderRefreshPolicyRevisionExhausted,
    ProviderRefreshPolicySourceKindImmutable,
    load_dataset_detail,
    load_datasets_grid,
)
from kortravelmap.api.provider_catalog import (
    ProviderDatasetCatalogEntry,
    ProviderDatasetOperation,
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
    operation_key: str = "mois_refresh",
    last_success_at: datetime | None = _NOW,
    eligible_after: datetime | None = None,
) -> SyncState:
    return SyncState(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="dataset_wide",
        operation_key=operation_key,
        status="active",
        cursor={},
        last_success_at=last_success_at,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=eligible_after,
    )


def _policy(
    *,
    provider_dataset_id: int = 42,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
    stale_after_minutes: int | None = 60,
    enabled: bool = True,
    targeted_policy: str = "allow_targeted",
    revision: int = 1,
) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        source_kind="openapi",
        targeted_policy=targeted_policy,
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
        revision=revision,
        created_at=_NOW,
        updated_at=_NOW,
        stale_after_minutes=stale_after_minutes,
    )


def _preview_catalog_entry(
    *,
    provider: str,
    dataset_key: str,
    has_fixture_preview: bool = True,
    has_refresh_operation: bool = True,
) -> ProviderDatasetCatalogEntry:
    operations: list[ProviderDatasetOperation] = []
    if has_fixture_preview:
        operations.append(
            ProviderDatasetOperation(
                operation_key="fixture_preview",
                operation_kind="preview",
                is_enabled=True,
                config={"handler": "fixture"},
                sync_scopes=(),
            )
        )
    if has_refresh_operation:
        operations.append(
            ProviderDatasetOperation(
                operation_key="fixture_refresh",
                operation_kind="refresh",
                is_enabled=True,
                config={},
                sync_scopes=("dataset_wide",),
            )
        )
    return ProviderDatasetCatalogEntry(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        display_name=dataset_key,
        source_kind="openapi",
        is_active=True,
        capabilities={},
        operations=tuple(operations),
    )


def _refresh_catalog_entry(
    *,
    provider_dataset_id: int,
    provider: str,
    dataset_key: str,
    operation_key: str,
    sync_scopes: tuple[str, ...],
) -> ProviderDatasetCatalogEntry:
    return ProviderDatasetCatalogEntry(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        display_name=dataset_key,
        source_kind="openapi",
        is_active=True,
        capabilities={},
        operations=(
            ProviderDatasetOperation(
                operation_key=operation_key,
                operation_kind="refresh",
                is_enabled=True,
                config={},
                sync_scopes=sync_scopes,
            ),
        ),
    )


def _pipeline_execution(
    *,
    provider: str,
    dataset_key: str,
    execution_id: str,
    created_at: datetime = _NOW,
    status: str = "running",
    operation_key: str = "dataset_refresh",
) -> PipelineExecution:
    job_id = execution_id.replace("11111111", "22222222")
    return PipelineExecution(
        kind="update_request",
        id=execution_id,
        status=status,
        created_at=created_at,
        provider_datasets=(
            PipelineProviderDatasetIdentity(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="dataset_wide",
                operation_key=operation_key,
                operation_member_id=job_id,
                status=status,
            ),
        ),
        progress=None,
        current_stage=None,
        scope_type="provider_dataset",
        priority=50,
        run_mode="queued",
        operator=None,
        error_message=None,
        started_at=_NOW,
        finished_at=None,
        dagster_run_id=f"run-{execution_id[:8]}",
        dagster_run_status=None,
        trigger_kind="update_request",
        operation_key=None,
        requested_job_id=job_id,
        linked_job_count=1,
        projected_job=PipelineProjectedJob(
            id=job_id,
            job_kind="feature_update_request",
            status=status,
            progress=0,
            current_stage=None,
            error_message=None,
            created_at=created_at,
            started_at=_NOW,
            finished_at=None,
            dagster_run_id=f"run-{execution_id[:8]}",
            dagster_run_status=None,
            trigger_kind="update_request",
            operation_key=None,
            load_batch_id=None,
            parent_job_id=None,
            depth=0,
        ),
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
        provider_dataset_id=42,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        catalog_state="canonical",
        orphan_reason=None,
        mutable=True,
        catalog=None,
        scopes=[
            OpsDatasetScopeState(
                sync_scope="dataset_wide",
                operation_key="fixture_refresh",
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
        schedule_source_errors=[],
        refresh_policy=None,
        latest_execution=None,
        active_execution=None,
        execution_coverage="db_recorded_canonical_operations",
        run_history=OpsDatasetRunHistory(
            items=[],
            next_cursor=None,
            canonical_url=(
                "/v1/ops/pipeline/executions?provider_dataset_id=1&"
                "sync_scope=dataset_wide"
            ),
        ),
        event_history=OpsDatasetEventHistory(
            items=[],
            next_cursor=None,
            canonical_url=(
                "/v1/ops/pipeline/events?provider_dataset_id=1&"
                "sync_scope=dataset_wide"
            ),
        ),
        dataset_issues=OpsIssueSummary(open_count=0, severity_counts={}),
    )


@pytest.mark.unit
def test_ops_datasets_openapi_exposes_hardened_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_states = {"queued", "running", "done", "failed", "cancelled"}
    assert "/v1/ops/datasets" in spec["paths"]
    assert "/v1/ops/datasets/{provider_dataset_id}" in spec["paths"]
    assert "/v1/ops/datasets/{provider_dataset_id}/preview" in spec["paths"]
    assert "/v1/ops/datasets/detail" not in spec["paths"]
    assert "/v1/ops/datasets/preview" not in spec["paths"]
    assert "/v1/ops/datasets/refresh-policy" in spec["paths"]
    grid_description = spec["paths"]["/v1/ops/datasets"]["get"]["description"]
    assert "provider_dataset_id" in grid_description
    assert "provider-only issue group은 만들지 않는다" in grid_description
    assert not any(
        "{provider}" in path or "{dataset}" in path
        for path in spec["paths"]
        if path.startswith("/v1/ops/datasets/")
    )
    for method, path in (
        ("get", "/v1/ops/datasets/{provider_dataset_id}"),
        ("post", "/v1/ops/datasets/{provider_dataset_id}/preview"),
        ("put", "/v1/ops/datasets/refresh-policy"),
    ):
        parameters = spec["paths"][path][method]["parameters"]
        expected_parameters = (
            {("provider_dataset_id", "query")}
            if path.endswith("/refresh-policy")
            else {
                ("provider_dataset_id", "path"),
                ("sync_scope", "query"),
                # membership identity는 triple이다(ADR-088). 콘솔이 이 축을 보내는데
                # 서버가 선언하지 않으면 FastAPI가 조용히 버려, operation만 다른 두
                # grid 행이 같은 상세를 반환한다.
                ("operation_key", "query"),
            }
        )
        if method == "get":
            expected_parameters.add((OPS_SCOPE_HEADER, "header"))
        assert {(item["name"], item["in"]) for item in parameters} == (
            expected_parameters
        )
    row = spec["components"]["schemas"]["OpsDatasetGridRow"]
    assert {
        "detail_url",
        "eligible_after",
        "freshness",
        "schedule",
        "latest_execution",
        "active_execution",
        "catalog_state",
        "mutable",
        "dataset_issues",
    } <= set(row["properties"])
    grid_data = spec["components"]["schemas"]["OpsDatasetsGridData"]
    assert "execution_coverage" in grid_data["required"]
    assert "latest_execution_coverage" not in grid_data["properties"]
    preview = spec["components"]["schemas"]["OpsDatasetPreviewData"]
    assert {
        "dataset_key",
        "truncated",
        "total_items",
        "returned_items",
        "budget",
    } <= set(preview["properties"])
    assert "dataset" not in preview["properties"]
    latest = spec["components"]["schemas"]["OpsDatasetExecution"]
    assert {
        "id",
        "detail_url",
        "pair_status",
        "operation_member_id",
        "sync_scope",
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
        "operation_key",
        "error_message",
    } <= set(latest["required"])
    assert latest["properties"]["id"]["format"] == "uuid"
    assert latest["properties"]["operation_member_id"]["format"] == "uuid"
    assert set(latest["properties"]["status"]["enum"]) == operation_states
    assert set(latest["properties"]["pair_status"]["enum"]) == operation_states
    assert "status_source" not in latest["properties"]
    pair = spec["components"]["schemas"]["OpsDatasetProviderDataset"]
    # membership identity는 triple이다(ADR-088) — 셋 다 non-null 필수다.
    assert {
        "provider_dataset_id",
        "sync_scope",
        "operation_key",
        "operation_member_id",
    } <= set(pair["required"])
    assert pair["properties"]["sync_scope"]["type"] == "string"
    assert pair["properties"]["operation_key"]["type"] == "string"
    assert pair["properties"]["operation_member_id"]["format"] == "uuid"
    assert set(pair["properties"]["status"]["enum"]) == operation_states
    assert "status_source" not in pair["properties"]
    scope_refresh = spec["components"]["schemas"][
        "OpsDatasetScopeRefreshCapability"
    ]
    assert {
        "supported",
        "selector",
        "effect",
        "default_sync_scope",
        "allowed_sync_scopes",
        "reason",
    } <= set(scope_refresh["properties"])
    assert {
        "supported",
        "selector",
        "effect",
        "default_sync_scope",
        "allowed_sync_scopes",
    } <= set(scope_refresh["required"])
    catalog = spec["components"]["schemas"]["OpsDatasetCatalogInfo"]
    assert "provider_state_default_scope" in catalog["required"]
    assert "default_sync_scope" not in catalog["properties"]
    projected = spec["components"]["schemas"]["OpsDatasetProjectedJob"]
    assert projected["properties"]["id"]["format"] == "uuid"
    assert set(projected["properties"]["status"]["enum"]) == operation_states
    detail = spec["components"]["schemas"]["OpsDatasetDetailData"]
    assert {
        "execution_coverage",
        "latest_execution",
        "active_execution",
        "run_history",
        "event_history",
    } <= set(detail["properties"])
    assert "detail_url" not in detail["properties"]
    assert {
        "execution_coverage",
        "latest_execution",
        "active_execution",
        "run_history",
        "event_history",
    } <= set(detail["required"])
    assert not {
        "recent_runs_coverage",
        "recent_runs",
        "recent_runs_next_cursor",
        "pipeline_history_url",
        "recent_events",
        "recent_events_next_cursor",
        "event_history_url",
    } & set(detail["properties"])
    run_history = spec["components"]["schemas"]["OpsDatasetRunHistory"]
    event_history = spec["components"]["schemas"]["OpsDatasetEventHistory"]
    assert {"items", "next_cursor", "canonical_url"} == set(
        run_history["properties"]
    )
    assert {"items", "next_cursor", "canonical_url"} == set(
        event_history["properties"]
    )
    cursor_schema = run_history["properties"]["next_cursor"]
    assert {item["type"] for item in cursor_schema["anyOf"]} == {
        "string",
        "null",
    }
    event_schema = spec["components"]["schemas"]["OpsDatasetEventRecord"]
    # 행 자신의 membership 축이다(요청 필터 값이 아니라). member 없는 job-level
    # event는 null이므로 nullable이고, 같은 리소스의 다른 표현
    # (`PipelineJobEventRecord`)과 모양이 같아야 한다. required에는 남는다 —
    # "값이 null일 수 있다"와 "키가 없을 수 있다"는 다르다.
    assert {entry["type"] for entry in event_schema["properties"]["sync_scope"]["anyOf"]} == {
        "string",
        "null",
    }
    assert {
        entry["type"] for entry in event_schema["properties"]["operation_key"]["anyOf"]
    } == {"string", "null"}
    assert {"sync_scope", "operation_key"} <= set(event_schema["required"])


@pytest.mark.unit
def test_ops_datasets_requires_bff_or_ops_principal() -> None:
    client = TestClient(create_app(ApiSettings(admin_proxy_secret="secret")))
    assert client.get("/v1/ops/datasets").status_code == 401


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
            execution_coverage="db_recorded_canonical_operations",
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

    async def _detail(*_args: object, **kwargs: object) -> OpsDatasetDetailData:
        assert kwargs["provider_dataset_id"] == 42
        assert kwargs["sync_scope"] == "external_system:concierge"
        return _empty_detail()

    monkeypatch.setattr(router_module, "load_dataset_detail", _detail)
    response = client.get(
        "/v1/ops/datasets/42",
        params={
            "sync_scope": "external_system:concierge",
        },
    )
    assert response.status_code == 200
    assert (
        response.json()["data"]["execution_coverage"]
        == "db_recorded_canonical_operations"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "sync_scope",
    ["default", "legacy-scope", " external_system:concierge", "external_system:"],
)
def test_detail_rejects_noncanonical_sync_scope(
    client: TestClient,
    sync_scope: str,
) -> None:
    response = client.get(
        "/v1/ops/datasets/42",
        params={
            "sync_scope": sync_scope,
        },
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_removed_natural_dataset_routes_are_not_reintroduced(client: TestClient) -> None:
    assert client.get(
        "/v1/ops/datasets/detail",
        params={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "sync_scope": "dataset_wide",
        },
    ).status_code == 404
    assert client.post(
        "/v1/ops/datasets/preview",
        params={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "sync_scope": "dataset_wide",
        },
        json={"source": "fixture", "max_items": 1},
    ).status_code == 404


@pytest.mark.unit
def test_run_history_emits_one_record_per_membership() -> None:
    """T-VN-33: 형제 operation member는 **각각 한 줄**로 나온다.

    예전에는 root당 1건으로 접고 ``operation_member_id``(UUID) tie-break로 하나를
    골랐다. 그건 형제 operation 중 임의 선택이고, 고른 쪽의 ``operation_key``와
    ``pair_status``만 응답에 실리므로 운영자는 다른 operation이 어떤 상태였는지
    알 방법이 없었다.

    같은 root가 두 membership을 건드렸다면 중복이 아니라 **서로 다른 두 사실**이다.
    identity가 triple이므로 행이 늘어나는 것이 맞고, ``operation_key``가 함께
    실리므로 화면에서 구분된다.
    """
    from kortravelmap.api import ops_dataset_service as service

    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    execution = replace(
        _pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="11111111-1111-4111-8111-111111111111",
            status="done",
        ),
        provider_datasets=(
            PipelineProviderDatasetIdentity(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="dataset_wide",
                operation_key="mois_bulk_refresh",
                operation_member_id="22222222-2222-4222-8222-222222222222",
                status="done",
            ),
            PipelineProviderDatasetIdentity(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="dataset_wide",
                operation_key="mois_sibling_refresh",
                operation_member_id="33333333-3333-4333-8333-333333333333",
                status="done",
            ),
            PipelineProviderDatasetIdentity(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="target_grids",
                operation_key="mois_targeted_refresh",
                operation_member_id="44444444-4444-4444-8444-444444444444",
                status="done",
            ),
        ),
    )

    records = service._run_history_records(
        (execution,),
        provider_dataset_id=42,
        sync_scopes=("dataset_wide",),
        operation_keys=None,
    )

    # 요청한 scope의 member 둘 다 나온다. 정렬은 (sync_scope, operation_key)로
    # 결정적이라 UUID 우연에 기대지 않는다.
    assert len(records) == 2
    assert [record.sync_scope for record in records] == ["dataset_wide"] * 2
    assert [record.operation_key for record in records] == [
        "mois_bulk_refresh",
        "mois_sibling_refresh",
    ]
    assert {str(record.operation_member_id) for record in records} == {
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    }

    # 반대 방향도 못이 박혀야 한다. exact triple을 지목하면 **그 operation만**
    # 나온다 — query는 `dataset_operation_key`로 root를 고르지만 고른 root의
    # membership 목록에는 형제가 그대로 들어 있어, 안 거르면 상세 화면이 옆
    # operation의 실행을 섞어 보여준다(화면 안내문과도 어긋난다).
    narrowed = service._run_history_records(
        (execution,),
        provider_dataset_id=42,
        sync_scopes=("dataset_wide",),
        operation_keys=("mois_sibling_refresh",),
    )
    assert [record.operation_key for record in narrowed] == ["mois_sibling_refresh"]


@pytest.mark.unit
def test_states_keep_each_operation_and_drop_noncanonical_rows() -> None:
    """T-VN-33: 비정규 scope는 감추되, operation별 state는 **접지 않는다**.

    state PK가 (provider_dataset_id, sync_scope, operation_key) triple이므로 같은
    logical scope에 operation만 다른 row가 여러 개 남는다. 예전에는 이것을 "API
    scope resource는 하나여야 한다"며 하나로 접었는데, 그러면 형제 operation의
    상태가 무경고로 사라진다 — 아래 fixture처럼 한쪽이 ``paused``면 운영자는 멈춘
    operation을 영영 못 본다. 접기는 ``default`` alias 시대의 규칙이었고, alias가
    사라진 뒤로는 alias가 아니라 operation을 접고 있었다.

    비정규 scope(``default``/``legacy-scope``)를 숨기는 규칙은 그대로다 — 그건
    API가 표현할 수 없는 값이라서지 중복이라서가 아니다.
    """
    from kortravelmap.api import ops_dataset_service as service

    def state(
        sync_scope: str, *, status: str, operation_key: str = "refresh"
    ) -> SyncState:
        return SyncState(
            provider_dataset_id=42,
            provider="removed-provider",
            dataset_key="removed-dataset",
            sync_scope=sync_scope,
            operation_key=operation_key,
            status=cast(Any, status),
            cursor={},
            last_success_at=None,
            last_failure_at=None,
            consecutive_failures=0,
            next_run_after=None,
        )

    selected = service._states_by_api_membership(
        None,
        (
            state("default", status="paused"),
            state("legacy-scope", status="paused"),
            state("dataset_wide", status="active"),
            state("dataset_wide", status="paused", operation_key="sibling_refresh"),
        ),
    )

    assert set(selected) == {
        ("dataset_wide", "refresh"),
        ("dataset_wide", "sibling_refresh"),
    }
    assert selected[("dataset_wide", "refresh")].status == "active"
    assert selected[("dataset_wide", "sibling_refresh")].status == "paused", (
        "형제 operation의 상태를 접으면 멈춘 operation이 보이지 않는다"
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
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": 41},
        json={
            "expected_revision": "1",
            "source_kind": "openapi",
            "stale_after_minutes": 60,
        },
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

    provider_dataset_id = 42
    provider = "provider/with/slash"
    dataset_key = "dataset/with/slash"

    async def _upsert(*_args: object, **kwargs: object) -> ProviderRefreshPolicy:
        assert kwargs["provider_dataset_id"] == provider_dataset_id
        body = kwargs["body"]
        assert body.stale_after_minutes == 90
        return _policy(
            provider_dataset_id=provider_dataset_id,
            provider=provider,
            dataset_key=dataset_key,
            stale_after_minutes=90,
        )

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": provider_dataset_id},
        json={
            "expected_revision": "1",
            "source_kind": "openapi",
            "stale_after_minutes": 90,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["stale_after_minutes"] == 90
    assert response.json()["data"]["revision"] == "1"


@pytest.mark.unit
def test_policy_revision_conflict_is_typed_and_returns_current_record(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    current = _policy(targeted_policy="disabled", revision=2)

    async def _upsert(*_args: object, **_kwargs: object) -> ProviderRefreshPolicy:
        raise ProviderRefreshPolicyRevisionConflict(
            expected_revision=1,
            current=current,
        )

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": current.provider_dataset_id},
        json={"expected_revision": "1", "source_kind": "openapi"},
    )

    assert response.status_code == 409
    problem = response.json()
    assert problem["code"] == "PROVIDER_REFRESH_POLICY_REVISION_CONFLICT"
    assert problem["details"]["expected_revision"] == "1"
    assert problem["details"]["current_revision"] == "2"
    assert problem["details"]["current_record"]["revision"] == "2"
    assert problem["details"]["current_record"]["targeted_policy"] == "disabled"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            ProviderRefreshPolicyRevisionExhausted(
                current=_policy(revision=9_223_372_036_854_775_807)
            ),
            "PROVIDER_REFRESH_POLICY_REVISION_EXHAUSTED",
        ),
        (
            ProviderRefreshPolicySourceKindImmutable(
                requested_source_kind="manual",
                current=_policy(revision=7),
            ),
            "PROVIDER_REFRESH_POLICY_SOURCE_KIND_IMMUTABLE",
        ),
    ],
)
def test_policy_terminal_conflicts_are_typed_with_current_record(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    code: str,
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _upsert(*_args: object, **_kwargs: object) -> ProviderRefreshPolicy:
        raise error

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    current = cast(Any, error).current
    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": current.provider_dataset_id},
        json={"expected_revision": str(current.revision), "source_kind": "openapi"},
    )

    assert response.status_code == 409
    problem = response.json()
    assert problem["code"] == code
    assert problem["details"]["expected_revision"] == str(current.revision)
    assert problem["details"]["current_revision"] == str(current.revision)
    assert problem["details"]["current_record"]["revision"] == str(
        current.revision
    )


@pytest.mark.unit
def test_revision_decimal_contract_preserves_values_above_javascript_safe_integer(
) -> None:
    from pydantic import ValidationError

    from kortravelmap.api.provider_refresh_schema import (
        ProviderRefreshPolicyConflictDetails,
        ProviderRefreshPolicyUpsertRequest,
        provider_refresh_policy_record,
    )

    large = "9007199254740993"
    request = ProviderRefreshPolicyUpsertRequest(
        expected_revision=large,
        source_kind="openapi",
    )
    details = ProviderRefreshPolicyConflictDetails(
        expected_revision=large,
        current_revision=large,
        current_record=None,
        mutation_disabled_reason=None,
    )
    assert request.expected_revision == large
    assert details.model_dump()["current_revision"] == large
    assert provider_refresh_policy_record(
        _policy(revision=int(large))
    ).revision == large

    with pytest.raises(ValidationError) as excinfo:
        ProviderRefreshPolicyConflictDetails(
            expected_revision="9223372036854775808",
            current_revision="0",
            current_record=None,
            mutation_disabled_reason=None,
        )
    assert {error["loc"] for error in excinfo.value.errors()} == {
        ("expected_revision",),
        ("current_revision",),
    }
    with pytest.raises(ValidationError):
        provider_refresh_policy_record(_policy(revision=9_223_372_036_854_775_808))


@pytest.mark.unit
def test_policy_mutation_rejects_server_owned_rate_limit_provenance(
    client: TestClient,
) -> None:
    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": 42},
        json={
            "expected_revision": None,
            "source_kind": "openapi",
            "rate_limit_source": {"forged": "operator-body"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_fixture_preview_enforces_response_budget(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(
                provider="data.go.kr-standard",
                dataset_key="datagokr_cultural_festivals",
            ),
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
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
def test_live_preview_request_is_typed_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(
                provider="data.go.kr-standard",
                dataset_key="datagokr_cultural_festivals",
            ),
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
        json={"source": "live", "max_items": 1},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_preview_without_fixture_capability_is_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(
                provider="python-mois-api",
                dataset_key="mois_license_features_bulk",
                has_fixture_preview=False,
            ),
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
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

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(
                provider="data.go.kr-standard",
                dataset_key="datagokr_cultural_festivals",
            ),
        )

    monkeypatch.setattr(
        router_module, "run_dataset_fixture_preview", _missing_fixture
    )
    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PREVIEW_REGISTRY_MISMATCH"
    assert response.json()["details"]["capability"] == "fixture"


@pytest.mark.unit
def test_preview_passes_slash_identity_to_service_exactly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import ops_datasets as router_module

    provider = "provider/with/slash"
    dataset_key = "dataset/with/slash"

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(provider=provider, dataset_key=dataset_key),
        )

    async def _preview(
        actual_provider: str,
        actual_dataset_key: str,
        *,
        max_items: int,
    ) -> object:
        assert actual_provider == provider
        assert actual_dataset_key == dataset_key
        assert max_items == 1
        return SimpleNamespace(
            provider=provider,
            dataset=dataset_key,
            variant="slash-identity",
            description="slash identity round-trip",
            items=(),
            total_items=0,
            truncated=False,
            max_items=max_items,
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    monkeypatch.setattr(router_module, "run_dataset_fixture_preview", _preview)

    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"]["provider"] == provider
    assert response.json()["data"]["dataset_key"] == dataset_key


@pytest.mark.unit
async def test_preview_only_dataset_is_not_gated_by_refresh_scopes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """refresh operation이 없는 preview 전용 dataset도 preview가 열려야 한다.

    ``provider_dataset_operation_scopes``에는 CHECK ``operation_kind='refresh'``가
    있어 **preview operation은 scope 행을 가질 수 없다**. 그런데 라우트가
    ``entry.refresh_scopes``로 승인 여부를 정해서, 같은 API가
    ``catalog.preview.supported=true``라 말해 놓고 영구 404를 냈다
    (실측 대상: python-airkorea-api/airkorea_stations. 적대 리뷰 10라운드).

    통합 회귀가 refresh scope를 가진 합성 seed만 써서 이 조합을 전혀 밟지 않았다.
    """
    from kortravelmap.api.routers import ops_datasets as router_module

    provider = "python-airkorea-api"
    dataset_key = "airkorea_stations"

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _preview_catalog_entry(
                provider=provider,
                dataset_key=dataset_key,
                has_refresh_operation=False,
            ),
        )

    async def _preview(
        actual_provider: str,
        actual_dataset_key: str,
        *,
        max_items: int,
    ) -> object:
        return SimpleNamespace(
            provider=actual_provider,
            dataset=actual_dataset_key,
            variant="fixture",
            description="preview-only dataset",
            items=(),
            total_items=0,
            truncated=False,
            max_items=max_items,
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    monkeypatch.setattr(router_module, "run_dataset_fixture_preview", _preview)

    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide"},
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["provider"] == provider

    # 그렇다고 아무 scope나 열리는 것은 아니다 — dataset 단위 preview만 허용한다.
    narrowed = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "target_grids"},
        json={"source": "fixture", "max_items": 1},
    )
    assert narrowed.status_code == 404


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
        provider_dataset_id=state.provider_dataset_id,
        provider=state.provider,
        dataset_key=state.dataset_key,
        open_total=2,
        by_severity={"error": 2},
    )
    active_unscoped = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=state.provider,
        dataset_key=state.dataset_key,
        sync_scope="dataset_wide",
        operation_key="mois_refresh",
        execution=_pipeline_execution(
            provider=state.provider,
            dataset_key=state.dataset_key,
            execution_id="11111111-1111-1111-1111-111111111111",
        ),
        operation_member_id="22222222-2222-2222-2222-222222222222",
        pair_status="running",
    )
    newer_terminal = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=state.provider,
        dataset_key=state.dataset_key,
        sync_scope="dataset_wide",
        operation_key="mois_refresh",
        execution=_pipeline_execution(
            provider=state.provider,
            dataset_key=state.dataset_key,
            execution_id="33333333-3333-4333-8333-333333333333",
            created_at=_NOW + timedelta(minutes=1),
            status="done",
        ),
        operation_member_id="44444444-4444-4444-8444-444444444444",
        pair_status="done",
    )
    schedule_index = DatasetScheduleIndex(
        source_status="ok",
        errors=(),
        by_operation_key={
            "mois_refresh": DatasetScheduleState(
                basis="dagster_definition_tags",
                status="RUNNING",
                schedule_names=("monthly",),
                active_schedule_names=("monthly",),
                next_scheduled_at=next_scheduled_at,
            )
        },
    )
    calls = {"snapshots": 0}

    async def _states(_session: object) -> list[SyncState]:
        return [state]

    async def _policies(
        _session: object,
    ) -> tuple[ProviderRefreshPolicy, ...]:
        return (policy,)

    async def _issues(
        _session: object, **_kwargs: object
    ) -> tuple[DatasetIntegrityIssueCount, ...]:
        return (dataset_issue,)

    async def _snapshots(
        _session: object,
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        calls["snapshots"] += 1
        return (
            DatasetExecutionSnapshot(
                provider_dataset_id=state.provider_dataset_id,
                provider=state.provider,
                dataset_key=state.dataset_key,
                sync_scope="dataset_wide",
                operation_key="mois_refresh",
                latest_terminal=None,
                active=active_unscoped,
            ),
            DatasetExecutionSnapshot(
                provider_dataset_id=state.provider_dataset_id,
                provider=state.provider,
                dataset_key=state.dataset_key,
                sync_scope="dataset_wide",
                operation_key="mois_refresh",
                latest_terminal=newer_terminal,
                active=None,
            ),
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return schedule_index

    async def _catalog(
        _session: object,
    ) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _refresh_catalog_entry(
                provider_dataset_id=state.provider_dataset_id,
                provider=state.provider,
                dataset_key=state.dataset_key,
                operation_key="mois_refresh",
                sync_scopes=("dataset_wide",),
            ),
            _refresh_catalog_entry(
                provider_dataset_id=43,
                provider="python-kma-api",
                dataset_key="kma_short_forecast",
                operation_key="kma_refresh",
                sync_scopes=("target_grids",),
            ),
        )

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _policies)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _issues)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)

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
    assert row.sync_scope == "dataset_wide"
    # 링크가 membership을 주소로 갖는다 — operation을 빼면 형제 operation 행들이
    # 같은 링크를 갖게 돼 어느 행을 눌러도 같은 화면이 열린다.
    assert row.detail_url == (
        "/v1/ops/datasets/42?sync_scope=dataset_wide&operation_key=mois_refresh"
    )
    assert row.schedule.next_scheduled_at == next_scheduled_at
    assert row.freshness.state == "fresh"
    assert row.freshness.due_at == _NOW + timedelta(minutes=60)
    assert row.dataset_issues.open_count == 2
    assert row.latest_execution is not None
    assert row.latest_execution.status == "done"
    assert row.latest_execution.pair_status == "done"
    assert row.latest_execution.sync_scope == "dataset_wide"
    assert str(row.latest_execution.id) == newer_terminal.execution.id
    assert row.active_execution is not None
    assert row.active_execution.status == "running"
    # ``sync_scope``는 non-null이다 — DB 열도 NOT NULL이고 공급 DTO도 ``str``다.
    assert row.active_execution.sync_scope == "dataset_wide"
    assert str(row.active_execution.id) == active_unscoped.execution.id
    assert row.catalog is not None
    assert row.catalog.provider_state_default_scope == "dataset_wide"
    assert row.catalog.scope_refresh.default_sync_scope == "dataset_wide"
    assert row.catalog.scope_refresh.supported is False
    assert row.catalog.scope_refresh.effect == "dataset_wide"
    kma_row = next(
        item
        for item in data.items
        if item.catalog is not None
        and item.catalog.scope_refresh.selector == "poi_cache_targets"
    )
    assert kma_row.catalog is not None
    assert kma_row.catalog.scope_refresh.allowed_sync_scopes == ["target_grids"]
    assert calls["snapshots"] == 1


@pytest.mark.unit
async def test_grid_projects_active_execution_by_exact_sync_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import ops_dataset_service as service

    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    exact_scopes = ("external_system:concierge", "external_system:geo")
    scopes = (*exact_scopes, "external_system:without-exact-run")
    states = [
        SyncState(
            provider_dataset_id=42,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
            operation_key="kma_refresh",
            status="active",
            cursor={},
            last_success_at=_NOW,
            last_failure_at=None,
            consecutive_failures=0,
            next_run_after=None,
        )
        for scope in (*scopes, "legacy-scope")
    ]
    executions = tuple(
        DatasetLatestExecution(
            provider_dataset_id=42,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
            operation_key="kma_refresh",
            execution=_pipeline_execution(
                provider=provider,
                dataset_key=dataset_key,
                execution_id=(
                    f"{index}" * 8 + "-0000-4000-8000-" + f"{index}" * 12
                ),
            ),
            operation_member_id=(
                f"{index}" * 8 + "-0000-4000-8000-" + f"{index}" * 12
            ),
            pair_status="running",
        )
        for index, scope in enumerate(exact_scopes, start=3)
    )
    unscoped = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="dataset_wide",
        operation_key="kma_refresh",
        execution=_pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="99999999-9999-4999-8999-999999999999",
            created_at=_NOW + timedelta(minutes=1),
        ),
        operation_member_id="88888888-8888-4888-8888-888888888888",
        pair_status="running",
    )

    async def _states(_session: object) -> list[SyncState]:
        return states

    async def _empty(_session: object, **_kwargs: object) -> tuple[object, ...]:
        return ()

    async def _snapshots(
        _session: object,
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        return tuple(
            DatasetExecutionSnapshot(
                provider_dataset_id=item.provider_dataset_id,
                provider=item.provider,
                dataset_key=item.dataset_key,
                sync_scope=item.sync_scope,
                operation_key="kma_refresh",
                latest_terminal=None,
                active=item,
            )
            for item in (*executions, unscoped)
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(
            source_status="ok", errors=(), by_operation_key={}
        )

    async def _catalog(
        _session: object,
    ) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _refresh_catalog_entry(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                operation_key="kma_refresh",
                sync_scopes=("target_grids",),
            ),
        )

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _empty)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)

    data = await load_datasets_grid(
        cast(Any, object()),
        settings=ApiSettings(),
        dagster_client=cast(Any, object()),
        now=_NOW,
    )
    rows = {
        row.sync_scope: row
        for row in data.items
        if row.provider == provider and row.dataset_key == dataset_key
    }
    expected_scopes = {
        *scopes,
        "target_grids",
    }
    assert expected_scopes <= rows.keys()
    assert "legacy-scope" not in rows
    assert rows["target_grids"].active_execution is None
    for scope, execution in zip(exact_scopes, executions, strict=True):
        active = rows[scope].active_execution
        assert active is not None
        assert str(active.id) == execution.execution.id
        assert active.sync_scope == scope
        assert rows[scope].latest_execution is None
    assert rows["external_system:without-exact-run"].active_execution is None


@pytest.mark.unit
async def test_detail_materializes_all_catalog_target_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import ops_dataset_service as service

    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    state = SyncState(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
        operation_key="kma_refresh",
        status="active",
        cursor={},
        last_success_at=_NOW,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=None,
    )
    terminal = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
        operation_key="kma_refresh",
        execution=_pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="11111111-1111-4111-8111-111111111111",
            created_at=_NOW + timedelta(minutes=1),
            status="done",
        ),
        operation_member_id="22222222-2222-4222-8222-222222222222",
        pair_status="done",
    )
    active = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
        operation_key="kma_refresh",
        execution=_pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="33333333-3333-4333-8333-333333333333",
        ),
        operation_member_id="44444444-4444-4444-8444-444444444444",
        pair_status="running",
    )

    async def _states(_session: object, **_kwargs: object) -> list[SyncState]:
        return [state]

    async def _none(_session: object, **_kwargs: object) -> None:
        return None

    async def _empty_page(*_args: object, **kwargs: object) -> SimpleNamespace:
        assert kwargs["provider_dataset_id"] == 42
        if "dataset_sync_scopes" in kwargs:
            assert kwargs["dataset_sync_scopes"] == (
                "external_system:concierge",
            )
            return SimpleNamespace(items=(), next_cursor="runs-next")
        if "sync_scope" in kwargs:
            assert kwargs["sync_scope"] == "external_system:concierge"
            return SimpleNamespace(items=(), next_cursor="events-next")
        raise AssertionError(f"unexpected detail page query: {kwargs!r}")

    async def _empty(_session: object, **_kwargs: object) -> tuple[object, ...]:
        return ()

    async def _snapshots(
        _session: object,
        *,
        provider_dataset_id: int,
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        assert provider_dataset_id == 42
        return (
            DatasetExecutionSnapshot(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="external_system:concierge",
                operation_key="kma_refresh",
                latest_terminal=terminal,
                active=active,
            ),
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(
            source_status="ok", errors=(), by_operation_key={}
        )

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (
            _refresh_catalog_entry(
                provider_dataset_id=42,
                provider=provider,
                dataset_key=dataset_key,
                operation_key="kma_refresh",
                sync_scopes=("target_grids",),
            ),
        )

    monkeypatch.setattr(service.sync_state_repo, "list_sync_states_by_dataset_id", _states)
    monkeypatch.setattr(service, "get_provider_refresh_policy", _none)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots_scoped", _snapshots)
    monkeypatch.setattr(service, "list_pipeline_executions", _empty_page)
    monkeypatch.setattr(service, "list_ops_import_job_events", _empty_page)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)

    detail = await load_dataset_detail(
        cast(Any, object()),
        settings=ApiSettings(),
        dagster_client=cast(Any, object()),
        provider_dataset_id=42,
        sync_scope="external_system:concierge",
        now=_NOW,
    )
    scopes = {scope.sync_scope: scope for scope in detail.scopes}
    assert set(scopes) == {
        "target_grids",
        "external_system:concierge",
    }
    assert scopes["target_grids"].status == "never_run"
    assert scopes["external_system:concierge"].status == "active"
    assert detail.run_history.next_cursor == "runs-next"
    assert detail.event_history.next_cursor == "events-next"
    assert detail.latest_execution is not None
    assert str(detail.latest_execution.id) == terminal.execution.id
    assert detail.active_execution is not None
    assert str(detail.active_execution.id) == active.execution.id
    assert detail.event_history.canonical_url == (
        "/v1/ops/pipeline/events?provider_dataset_id=42&"
        "sync_scope=external_system%3Aconcierge"
    )


@pytest.mark.unit
async def test_grid_keeps_invalid_scope_orphan_as_dataset_wide_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import ops_dataset_service as service

    provider = "orphan-provider"
    dataset_key = "orphan-dataset"
    policy_provider = "policy-only-orphan-provider"
    policy_dataset_key = "policy-only-orphan-dataset"
    legacy_scopes = ("legacy:a", "legacy:b")
    states = [
        SyncState(
            provider_dataset_id=42,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
            operation_key="orphan_refresh",
            status="active",
            cursor={},
            last_success_at=_NOW,
            last_failure_at=None,
            consecutive_failures=0,
            next_run_after=None,
        )
        for scope in legacy_scopes
    ]
    unscoped = DatasetLatestExecution(
        provider_dataset_id=42,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="dataset_wide",
        operation_key="orphan_refresh",
        execution=_pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="77777777-7777-4777-8777-777777777777",
        ),
        operation_member_id="66666666-6666-4666-8666-666666666666",
        pair_status="running",
    )
    policy = _policy(
        provider_dataset_id=43,
        provider=policy_provider,
        dataset_key=policy_dataset_key,
    )
    policy_unscoped = DatasetLatestExecution(
        provider_dataset_id=43,
        provider=policy_provider,
        dataset_key=policy_dataset_key,
        sync_scope="dataset_wide",
        operation_key="orphan_refresh",
        execution=_pipeline_execution(
            provider=policy_provider,
            dataset_key=policy_dataset_key,
            execution_id="55555555-5555-4555-8555-555555555555",
        ),
        operation_member_id="44444444-4444-4444-8444-444444444444",
        pair_status="running",
    )

    async def _states(_session: object) -> list[SyncState]:
        return states

    async def _empty(_session: object, **_kwargs: object) -> tuple[object, ...]:
        return ()

    async def _policies(
        _session: object,
    ) -> tuple[ProviderRefreshPolicy, ...]:
        return (policy,)

    async def _snapshots(
        _session: object,
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        return tuple(
            DatasetExecutionSnapshot(
                provider_dataset_id=item.provider_dataset_id,
                provider=item.provider,
                dataset_key=item.dataset_key,
                sync_scope=item.sync_scope,
                operation_key="orphan_refresh",
                latest_terminal=None,
                active=item,
            )
            for item in (unscoped, policy_unscoped)
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(
            source_status="ok", errors=(), by_operation_key={}
        )

    async def _catalog(
        _session: object,
    ) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return ()

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _policies)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)

    data = await load_datasets_grid(
        cast(Any, object()),
        settings=ApiSettings(),
        dagster_client=cast(Any, object()),
        now=_NOW,
    )
    orphan_rows = [
        row
        for row in data.items
        if row.provider == provider and row.dataset_key == dataset_key
    ]
    assert {row.sync_scope for row in orphan_rows} == {"dataset_wide"}
    assert all(row.latest_execution is None for row in orphan_rows)
    assert orphan_rows[0].active_execution is not None
    assert str(orphan_rows[0].active_execution.id) == unscoped.execution.id
    assert orphan_rows[0].orphan_reason == "catalog_missing_with_sync_state"
    policy_row = next(
        row
        for row in data.items
        if row.provider == policy_provider and row.dataset_key == policy_dataset_key
    )
    assert policy_row.sync_scope == "dataset_wide"
    assert policy_row.latest_execution is None
    assert policy_row.active_execution is not None
    assert str(policy_row.active_execution.id) == policy_unscoped.execution.id


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


def _membership_catalog_entry(
    *,
    provider_dataset_id: int = 42,
    provider: str = "python-kma-api",
    dataset_key: str = "kma_short_forecast",
    is_active: bool = True,
) -> ProviderDatasetCatalogEntry:
    """형제 refresh operation을 가진 dataset.

    ``pk_provider_dataset_operation_scopes``가 triple이므로 한 dataset의 한 scope에
    operation이 여럿 결박될 수 있다(0091이 pair PK를 승격한 명시 목적). 그 모양을 만드는
    fixture가 이 파일에 없어서 membership 게이트 축이 무방비였다.
    """
    return ProviderDatasetCatalogEntry(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        display_name=dataset_key,
        source_kind="openapi",
        is_active=is_active,
        capabilities={},
        operations=(
            ProviderDatasetOperation(
                operation_key="fixture_preview",
                operation_kind="preview",
                is_enabled=True,
                config={"handler": "fixture"},
                sync_scopes=(),
            ),
            ProviderDatasetOperation(
                operation_key="op_alpha",
                operation_kind="refresh",
                is_enabled=True,
                config={},
                sync_scopes=("dataset_wide",),
            ),
            ProviderDatasetOperation(
                operation_key="op_beta",
                operation_kind="refresh",
                is_enabled=True,
                config={},
                sync_scopes=("target_grids",),
            ),
            ProviderDatasetOperation(
                operation_key="op_disabled",
                operation_kind="refresh",
                is_enabled=False,
                config={},
                sync_scopes=("dataset_wide",),
            ),
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("operation_key", "expected_status"),
    [
        # 실재하는 membership triple — 통과한다.
        ("op_alpha", 200),
        # 같은 dataset의 형제 operation이지만 이 scope에는 결박돼 있지 않다.
        ("op_beta", 404),
        # 비활성 operation은 실행 membership이 아니다.
        ("op_disabled", 404),
        # 카탈로그에 없는 operation.
        ("op_missing", 404),
    ],
)
def test_preview_operation_key_must_name_a_catalog_membership(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operation_key: str,
    expected_status: int,
) -> None:
    """``operation_key`` 축이 실제로 좁히는지 고정한다.

    감사 변이 스윕(A-4)은 이 게이트를 ``if False:``로 바꿔도 api 게이트가 통과한다고
    보고했다 — 바로 위 ``allowed_preview_scopes`` 게이트(scope 축)만 회귀가 있었고
    operation 축은 무방비였다. 콘솔이 형제 operation을 지목해도 서버가 조용히 무시하던
    상태다. 같은 변이를 다시 심어 이 테스트가 잡는 것을 확인했다.
    """
    from kortravelmap.api.routers import ops_datasets as router_module

    async def _catalog(*_args: object) -> tuple[ProviderDatasetCatalogEntry, ...]:
        return (_membership_catalog_entry(),)

    async def _preview(
        actual_provider: str,
        actual_dataset_key: str,
        *,
        max_items: int,
    ) -> object:
        return SimpleNamespace(
            provider=actual_provider,
            dataset=actual_dataset_key,
            variant="fixture",
            description="membership gate proof",
            items=(),
            total_items=0,
            truncated=False,
            max_items=max_items,
        )

    monkeypatch.setattr(router_module, "list_provider_dataset_catalog", _catalog)
    monkeypatch.setattr(router_module, "run_dataset_fixture_preview", _preview)

    response = client.post(
        "/v1/ops/datasets/42/preview",
        params={"sync_scope": "dataset_wide", "operation_key": operation_key},
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 404:
        assert "등록되지 않은 dataset membership" in response.json()["detail"]
    else:
        assert response.json()["data"]["operation_key"] == operation_key


@pytest.mark.unit
def test_inactive_dataset_policy_mutation_is_409_before_any_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비활성 dataset의 정책 PUT은 typed 409이고 write까지 가지 않는다.

    DB 트리거(``ck_provider_dataset_active_write``)가 이미 같은 규칙을 강제하므로,
    가드가 없으면 catch-all이 이 상태를 **500 INTERNAL_ERROR**로 바꾼다. 이 브랜치가
    넣은 가드인데 서비스·라우터 양쪽 분기가 한 번도 실행되지 않았다.
    """
    from kortravelmap.api import ops_dataset_service as service

    async def _catalog(*_args: object, **_kwargs: object) -> tuple[
        ProviderDatasetCatalogEntry, ...
    ]:
        return (_membership_catalog_entry(is_active=False),)

    async def _must_not_write(*_args: object, **_kwargs: object) -> ProviderRefreshPolicy:
        raise AssertionError("비활성 dataset에는 정책 write가 시도되면 안 된다")

    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)
    monkeypatch.setattr(service, "upsert_provider_refresh_policy", _must_not_write)

    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": 42},
        json={
            "expected_revision": "1",
            "source_kind": "openapi",
            "stale_after_minutes": 60,
        },
    )

    assert response.status_code == 409, response.text
    body = response.json()
    # orphan과 **다른 code**여야 한다 — 운영자가 취할 조치가 정반대다.
    assert body["code"] == "INACTIVE_DATASET_MUTATION_DISABLED"
    assert body["details"]["mutation_disabled_reason"] == "provider_dataset_inactive"


@pytest.mark.unit
def test_active_dataset_policy_mutation_reaches_the_repo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """위 가드의 대조군 — 활성 dataset은 그대로 write까지 간다.

    이것이 없으면 ``if not entry.is_active``를 ``if True``로 바꿔도 통과한다.
    """
    from kortravelmap.api import ops_dataset_service as service

    calls: list[int] = []

    async def _catalog(*_args: object, **_kwargs: object) -> tuple[
        ProviderDatasetCatalogEntry, ...
    ]:
        return (_membership_catalog_entry(is_active=True),)

    async def _upsert(*_args: object, **kwargs: object) -> ProviderRefreshPolicy:
        calls.append(int(kwargs["provider_dataset_id"]))
        return _policy(provider_dataset_id=42)

    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)
    monkeypatch.setattr(service, "upsert_provider_refresh_policy", _upsert)

    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": 42},
        json={
            "expected_revision": "1",
            "source_kind": "openapi",
            "stale_after_minutes": 60,
        },
    )

    assert response.status_code == 200, response.text
    assert calls == [42]


@pytest.mark.unit
def test_unknown_dataset_policy_mutation_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """카탈로그에 없는 id는 409가 아니라 404다(활성 가드보다 앞선 분기)."""
    from kortravelmap.api import ops_dataset_service as service

    async def _catalog(*_args: object, **_kwargs: object) -> tuple[
        ProviderDatasetCatalogEntry, ...
    ]:
        return (_membership_catalog_entry(provider_dataset_id=41),)

    monkeypatch.setattr(service, "list_provider_dataset_catalog", _catalog)

    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider_dataset_id": 42},
        json={
            "expected_revision": "1",
            "source_kind": "openapi",
            "stale_after_minutes": 60,
        },
    )

    assert response.status_code == 404, response.text
