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
    targeted_policy: str = "allow_targeted",
    revision: int = 1,
) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
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


def _pipeline_execution(
    *,
    provider: str,
    dataset_key: str,
    execution_id: str,
    created_at: datetime = _NOW,
    status: str = "running",
) -> PipelineExecution:
    job_id = execution_id.replace("11111111", "22222222")
    return PipelineExecution(
        kind="update_request",
        id=execution_id,
        status=status,
        created_at=created_at,
        providers=(provider,),
        dataset_keys=(dataset_key,),
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
        dagster_run_id=f"run-{execution_id[:8]}",
        dagster_run_status=None,
        trigger_kind="update_request",
        operation_registry_version=None,
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
            operation_registry_version=None,
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
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        catalog_state="canonical",
        orphan_reason=None,
        mutable=True,
        catalog=None,
        scopes=[
            OpsDatasetScopeState(
                sync_scope="dataset_wide",
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
                "/v1/ops/pipeline/executions?provider=python-mois-api&"
                "dataset_key=mois_license_features_bulk&sync_scope=dataset_wide"
            ),
        ),
        event_history=OpsDatasetEventHistory(
            items=[],
            next_cursor=None,
            canonical_url=(
                "/v1/ops/pipeline/events?provider=python-mois-api&"
                "dataset_key=mois_license_features_bulk&sync_scope=dataset_wide"
            ),
        ),
        dataset_issues=OpsIssueSummary(open_count=0, severity_counts={}),
        provider_issues=OpsIssueSummary(open_count=0, severity_counts={}),
    )


@pytest.mark.unit
def test_ops_datasets_openapi_exposes_hardened_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_states = {"queued", "running", "done", "failed", "cancelled"}
    assert "/v1/ops/datasets" in spec["paths"]
    assert "/v1/ops/datasets/detail" in spec["paths"]
    assert "/v1/ops/datasets/preview" in spec["paths"]
    assert "/v1/ops/datasets/refresh-policy" in spec["paths"]
    assert not any(
        "{provider}" in path or "{dataset}" in path
        for path in spec["paths"]
        if path.startswith("/v1/ops/datasets/")
    )
    for method, path in (
        ("get", "/v1/ops/datasets/detail"),
        ("post", "/v1/ops/datasets/preview"),
        ("put", "/v1/ops/datasets/refresh-policy"),
    ):
        parameters = spec["paths"][path][method]["parameters"]
        expected_parameters = {
            ("provider", "query"),
            ("dataset_key", "query"),
        }
        if path.endswith("/detail"):
            expected_parameters.add(("sync_scope", "query"))
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
        "provider_issues",
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
    assert event_schema["properties"]["sync_scope"]["type"] == "string"
    assert "sync_scope" in event_schema["required"]


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

    provider = "provider/with/slash"
    dataset_key = "dataset/with/slash"

    async def _detail(*_args: object, **kwargs: object) -> OpsDatasetDetailData:
        assert kwargs["provider"] == provider
        assert kwargs["dataset_key"] == dataset_key
        assert kwargs["sync_scope"] == "external_system:concierge"
        return _empty_detail()

    monkeypatch.setattr(router_module, "load_dataset_detail", _detail)
    response = client.get(
        "/v1/ops/datasets/detail",
        params={
            "provider": provider,
            "dataset_key": dataset_key,
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
        "/v1/ops/datasets/detail",
        params={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "sync_scope": sync_scope,
        },
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_run_history_emits_one_record_per_root_for_dataset_wide_aliases() -> None:
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
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=None,
                operation_member_id="22222222-2222-4222-8222-222222222222",
                status="done",
            ),
            PipelineProviderDatasetIdentity(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="dataset_wide",
                operation_member_id="33333333-3333-4333-8333-333333333333",
                status="done",
            ),
        ),
    )

    records = service._run_history_records(
        (execution,),
        provider=provider,
        dataset_key=dataset_key,
        sync_scopes=("dataset_wide", None),
    )

    assert len(records) == 1
    assert records[0].sync_scope == "dataset_wide"
    assert str(records[0].operation_member_id) == (
        "33333333-3333-4333-8333-333333333333"
    )


@pytest.mark.unit
def test_state_aliases_emit_one_logical_scope_and_prefer_canonical_row() -> None:
    from kortravelmap.api import ops_dataset_service as service

    def state(sync_scope: str, *, status: str) -> SyncState:
        return SyncState(
            provider="removed-provider",
            dataset_key="removed-dataset",
            sync_scope=sync_scope,
            status=cast(Any, status),
            cursor={},
            last_success_at=None,
            last_failure_at=None,
            consecutive_failures=0,
            next_run_after=None,
        )

    selected = service._states_by_api_scope(
        None,
        (
            state("default", status="paused"),
            state("dataset_wide", status="active"),
        ),
    )

    assert set(selected) == {"dataset_wide"}
    assert selected["dataset_wide"].sync_scope == "dataset_wide"
    assert selected["dataset_wide"].status == "active"


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
        params={"provider": "legacy", "dataset_key": "removed"},
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

    provider = "provider/with/slash"
    dataset_key = "dataset/with/slash"

    async def _upsert(*_args: object, **kwargs: object) -> ProviderRefreshPolicy:
        assert kwargs["provider"] == provider
        assert kwargs["dataset_key"] == dataset_key
        body = kwargs["body"]
        assert body.stale_after_minutes == 90
        return _policy(
            provider=provider,
            dataset_key=dataset_key,
            stale_after_minutes=90,
        )

    monkeypatch.setattr(router_module, "upsert_dataset_refresh_policy", _upsert)
    response = client.put(
        "/v1/ops/datasets/refresh-policy",
        params={"provider": provider, "dataset_key": dataset_key},
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
        params={"provider": current.provider, "dataset_key": current.dataset_key},
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
        params={"provider": current.provider, "dataset_key": current.dataset_key},
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
        params={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
        json={
            "expected_revision": None,
            "source_kind": "openapi",
            "rate_limit_source": {"forged": "operator-body"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_fixture_preview_enforces_response_budget(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/preview",
        params={
            "provider": "data.go.kr-standard",
            "dataset_key": "datagokr_cultural_festivals",
        },
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
        "/v1/ops/datasets/preview",
        params={
            "provider": "data.go.kr-standard",
            "dataset_key": "datagokr_cultural_festivals",
        },
        json={"source": "live", "max_items": 1},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_preview_without_fixture_capability_is_409(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/preview",
        params={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
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
        "/v1/ops/datasets/preview",
        params={
            "provider": "data.go.kr-standard",
            "dataset_key": "datagokr_cultural_festivals",
        },
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

    def _entry(actual_provider: str, actual_dataset_key: str) -> object:
        assert actual_provider == provider
        assert actual_dataset_key == dataset_key
        return SimpleNamespace(preview="fixture")

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

    monkeypatch.setattr(router_module, "find_catalog_entry", _entry)
    monkeypatch.setattr(router_module, "run_dataset_fixture_preview", _preview)

    response = client.post(
        "/v1/ops/datasets/preview",
        params={"provider": provider, "dataset_key": dataset_key},
        json={"source": "fixture", "max_items": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"]["provider"] == provider
    assert response.json()["data"]["dataset_key"] == dataset_key


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
    active_unscoped = DatasetLatestExecution(
        provider=state.provider,
        dataset_key=state.dataset_key,
        sync_scope=None,
        execution=_pipeline_execution(
            provider=state.provider,
            dataset_key=state.dataset_key,
            execution_id="11111111-1111-1111-1111-111111111111",
        ),
        operation_member_id="22222222-2222-2222-2222-222222222222",
        pair_status="running",
    )
    newer_terminal = DatasetLatestExecution(
        provider=state.provider,
        dataset_key=state.dataset_key,
        sync_scope="dataset_wide",
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
        return (dataset_issue, provider_issue)

    async def _snapshots(
        _session: object,
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        calls["snapshots"] += 1
        return (
            DatasetExecutionSnapshot(
                provider=state.provider,
                dataset_key=state.dataset_key,
                sync_scope=None,
                latest_terminal=None,
                active=active_unscoped,
            ),
            DatasetExecutionSnapshot(
                provider=state.provider,
                dataset_key=state.dataset_key,
                sync_scope="dataset_wide",
                latest_terminal=newer_terminal,
                active=None,
            ),
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return schedule_index

    async def _external_systems(_session: object) -> tuple[str, ...]:
        return ("concierge", "geo")

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _policies)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _issues)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(
        service,
        "list_active_poi_cache_target_external_systems",
        _external_systems,
    )

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
    assert row.detail_url == (
        "/v1/ops/datasets/detail?provider=python-mois-api&"
        "dataset_key=mois_license_features_bulk&sync_scope=dataset_wide"
    )
    assert row.schedule.next_scheduled_at == next_scheduled_at
    assert row.freshness.state == "fresh"
    assert row.freshness.due_at == _NOW + timedelta(minutes=60)
    assert row.dataset_issues.open_count == 2
    assert row.provider_issues.open_count == 1
    assert row.latest_execution is not None
    assert row.latest_execution.status == "done"
    assert row.latest_execution.pair_status == "done"
    assert row.latest_execution.sync_scope == "dataset_wide"
    assert str(row.latest_execution.id) == newer_terminal.execution.id
    assert row.active_execution is not None
    assert row.active_execution.status == "running"
    assert row.active_execution.sync_scope is None
    assert str(row.active_execution.id) == active_unscoped.execution.id
    assert row.catalog is not None
    assert row.catalog.provider_state_default_scope == "default"
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
    assert kma_row.catalog.scope_refresh.allowed_sync_scopes == [
        "target_grids",
        "external_system:concierge",
        "external_system:geo",
    ]
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
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
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
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
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
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=None,
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
                provider=item.provider,
                dataset_key=item.dataset_key,
                sync_scope=item.sync_scope,
                latest_terminal=None,
                active=item,
            )
            for item in (*executions, unscoped)
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(source_status="ok", errors=(), by_dataset={})

    async def _external_systems(_session: object) -> tuple[str, ...]:
        return ("concierge", "geo", "new")

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _empty)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(
        service,
        "list_active_poi_cache_target_external_systems",
        _external_systems,
    )

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
        "external_system:new",
    }
    assert expected_scopes <= rows.keys()
    assert "legacy-scope" not in rows
    assert rows["target_grids"].active_execution is None
    assert rows["external_system:new"].active_execution is None
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
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
        status="active",
        cursor={},
        last_success_at=_NOW,
        last_failure_at=None,
        consecutive_failures=0,
        next_run_after=None,
    )
    terminal = DatasetLatestExecution(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
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
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
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
    ) -> tuple[DatasetExecutionSnapshot, ...]:
        return (
            DatasetExecutionSnapshot(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="external_system:concierge",
                latest_terminal=terminal,
                active=active,
            ),
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(source_status="ok", errors=(), by_dataset={})

    async def _external_systems(_session: object) -> tuple[str, ...]:
        return ("concierge", "geo")

    monkeypatch.setattr(service.sync_state_repo, "list_sync_states", _states)
    monkeypatch.setattr(service, "get_provider_refresh_policy", _none)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "list_pipeline_executions", _empty_page)
    monkeypatch.setattr(service, "list_ops_import_job_events", _empty_page)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(
        service,
        "list_active_poi_cache_target_external_systems",
        _external_systems,
    )

    detail = await load_dataset_detail(
        cast(Any, object()),
        settings=ApiSettings(),
        dagster_client=cast(Any, object()),
        provider=provider,
        dataset_key=dataset_key,
        sync_scope="external_system:concierge",
        now=_NOW,
    )
    scopes = {scope.sync_scope: scope for scope in detail.scopes}
    assert set(scopes) == {
        "target_grids",
        "external_system:concierge",
        "external_system:geo",
    }
    assert scopes["target_grids"].status == "never_run"
    assert scopes["external_system:concierge"].status == "active"
    assert scopes["external_system:geo"].status == "never_run"
    assert detail.run_history.next_cursor == "runs-next"
    assert detail.event_history.next_cursor == "events-next"
    assert detail.latest_execution is not None
    assert str(detail.latest_execution.id) == terminal.execution.id
    assert detail.active_execution is not None
    assert str(detail.active_execution.id) == active.execution.id
    assert detail.event_history.canonical_url == (
        "/v1/ops/pipeline/events?provider=python-kma-api&"
        "dataset_key=kma_short_forecast&"
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
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=scope,
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
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=None,
        execution=_pipeline_execution(
            provider=provider,
            dataset_key=dataset_key,
            execution_id="77777777-7777-4777-8777-777777777777",
        ),
        operation_member_id="66666666-6666-4666-8666-666666666666",
        pair_status="running",
    )
    policy = _policy(
        provider=policy_provider,
        dataset_key=policy_dataset_key,
    )
    policy_unscoped = DatasetLatestExecution(
        provider=policy_provider,
        dataset_key=policy_dataset_key,
        sync_scope=None,
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
                provider=item.provider,
                dataset_key=item.dataset_key,
                sync_scope=item.sync_scope,
                latest_terminal=None,
                active=item,
            )
            for item in (unscoped, policy_unscoped)
        )

    async def _schedules(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(source_status="ok", errors=(), by_dataset={})

    monkeypatch.setattr(service.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(service, "list_all_provider_refresh_policies", _policies)
    monkeypatch.setattr(service, "count_open_integrity_issues_by_dataset", _empty)
    monkeypatch.setattr(service, "list_dataset_execution_snapshots", _snapshots)
    monkeypatch.setattr(service, "load_dataset_schedule_index", _schedules)
    monkeypatch.setattr(
        service,
        "list_active_poi_cache_target_external_systems",
        _empty,
    )

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
