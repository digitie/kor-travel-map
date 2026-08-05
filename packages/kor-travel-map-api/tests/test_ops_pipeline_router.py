"""``/v1/ops/pipeline/*`` 라우터 단위 테스트 (ADR-064 T-ADM-C3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_update_active_repo import FeatureUpdateDispatchConflict
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestIdempotency,
    FeatureUpdateRequestPreview,
)
from kortravelmap.infra.ops_repo import (
    OpsCursorFilterMismatch,
    OpsImportJob,
    OpsImportJobEvent,
    OpsImportJobEventPage,
)
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationAttempt,
    PipelineCancellationDetail,
    PipelineCancellationMember,
    PipelineCancellationRun,
    PipelineCancellationSummary,
)
from kortravelmap.infra.pipeline_repo import (
    PipelineCursorFilterMismatch,
    PipelineExecution,
    PipelineExecutionPage,
    PipelineProjectedJob,
    PipelineProviderDatasetIdentity,
    PipelineStatusCounts,
)
from kortravelmap.providers.datagokr_file_data import DATAGOKR_FILEDATA_DATASETS
from kortravelmap.providers.feature_operation_registry import (
    ADMIN_MANUAL_TRIGGER_TAG,
    FEATURE_OPERATION_TRIGGER_TAG,
    parse_feature_operation_identity_tags,
    validate_feature_operation_identity,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    MOIS_SOURCE_SYNC_COVERAGE_TAG,
    MOIS_SOURCE_SYNC_FULL_COVERAGE,
)
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME

from kortravelmap.api import dagster_graphql as dagster_mod
from kortravelmap.api import dagster_query_service as dagster_query
from kortravelmap.api import dagster_schedule_service as dagster_schedule
from kortravelmap.api import feature_update_service as fur_mod
from kortravelmap.api import mois_source_precheck
from kortravelmap.api.app import create_app
from kortravelmap.api.auth import (
    ADMIN_ACTOR_HEADER,
    ADMIN_PROXY_SECRET_HEADER,
    OPS_SCOPE_HEADER,
    OPS_TOKEN_HEADER,
)
from kortravelmap.api.dagster_schema import DagsterScheduleClaimResolution
from kortravelmap.api.db import get_engine, get_session
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationDetailRecord,
    PipelineCancellationRootRecord,
)
from kortravelmap.api.routers import ops_pipeline as pipeline_mod
from kortravelmap.api.settings import ApiSettings

_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
_OPS_READ_TOKEN = "read-token-00000000000000000000000000000000"
_OPS_CANCEL_TOKEN = "cancel-token-000000000000000000000000000000"

_PIPELINE_PATHS = [
    "/v1/ops/pipeline/overview",
    "/v1/ops/pipeline/executions",
    "/v1/ops/pipeline/executions/{kind}/{execution_id}",
    "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel",
    "/v1/ops/pipeline/executions/update_request/{execution_id}/cancel",
    "/v1/ops/pipeline/events",
    "/v1/ops/pipeline/dagster-runs",
    "/v1/ops/pipeline/dagster-runs/{run_id}",
    "/v1/ops/pipeline/prechecks/mois-source-sync",
    "/v1/ops/pipeline/schedules",
    "/v1/ops/pipeline/schedules/{schedule_name}",
    "/v1/ops/pipeline/schedules/{schedule_name}/commands",
    "/v1/ops/pipeline/schedules/{schedule_name}/claims/{command_id}/resolve",
    "/v1/ops/pipeline/requests",
    "/v1/ops/pipeline/requests/preview",
    "/v1/ops/pipeline/requests/{request_id}/run-now",
]


@pytest.mark.unit
def test_api_settings_mois_precheck_ttl_uses_core_source_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS", "3")
    monkeypatch.setenv("KOR_TRAVEL_MAP_API_MOIS_SOURCE_SYNC_TTL_HOURS", "99")

    settings = ApiSettings(_env_file=None)

    assert settings.mois_source_sync_ttl_hours == 3


class _FakeBegin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0
        self.schedule_audit_events: list[dict[str, object]] = []

    def begin(self) -> _FakeBegin:
        self.begin_count += 1
        return _FakeBegin()

    def begin_nested(self) -> _FakeBegin:
        return _FakeBegin()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
            dagster_request_timeout_seconds=1.0,
            mois_source_sync_ttl_hours=7,
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _no_cancellation(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _canonical_root(
        _session: Any,
        *,
        kind: str,
        execution_id: str,
    ) -> PipelineExecution:
        return _execution(kind=kind, execution_id=execution_id)

    async def _no_active_request(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _lock_idempotency(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _no_idempotency(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _record_idempotency(
        *_args: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestIdempotency:
        return FeatureUpdateRequestIdempotency(
            idempotency_key=kwargs["idempotency_key"],
            fingerprint_version=1,
            request_fingerprint=kwargs["request_fingerprint"],
            request_id=kwargs["request_id"],
            actor=kwargs["actor"],
            reused_active_request=kwargs["reused_active_request"],
            created_at=_NOW,
        )

    async def _empty_schedule_overrides(_session: Any) -> dict[str, str]:
        return {}

    async def _ready_mois_source_sync(
        _resolved_pairs: frozenset[tuple[str, str]],
        **_kwargs: Any,
    ) -> None:
        return None

    async def _audit_schedule_command(
        audit_session: _FakeSession,
        *,
        schedule_name: str,
        command: str,
        actor: str,
        reason: str | None,
        request_details: dict[str, object],
        command_id: UUID,
        operation: Any,
    ) -> Any:
        base = {
            "schedule_name": schedule_name,
            "command": command,
            "actor": actor,
            "reason": reason,
        }
        assert command_id == UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        audit_session.schedule_audit_events.append(
            {**base, "phase": "requested", "details": request_details}
        )

        async def _mutation_guard() -> None:
            return None

        try:
            response = await operation(_mutation_guard)
        except Exception:
            audit_session.schedule_audit_events.append({**base, "phase": "failed"})
            raise
        response.data.audit_command_id = command_id
        audit_session.schedule_audit_events.append(
            {
                **base,
                "phase": "succeeded" if response.data.status == "ok" else "failed",
            }
        )
        return response

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(
        pipeline_mod,
        "get_current_pipeline_cancellation_detail",
        _no_cancellation,
    )
    monkeypatch.setattr(
        fur_mod,
        "find_active_provider_dataset_request",
        _no_active_request,
    )
    monkeypatch.setattr(
        fur_mod,
        "lock_feature_update_request_idempotency",
        _lock_idempotency,
    )
    monkeypatch.setattr(
        fur_mod,
        "get_feature_update_request_idempotency",
        _no_idempotency,
    )
    monkeypatch.setattr(
        fur_mod,
        "create_feature_update_request_idempotency",
        _record_idempotency,
    )
    monkeypatch.setattr(pipeline_mod, "get_pipeline_execution", _canonical_root)
    monkeypatch.setattr(
        dagster_schedule,
        "schedule_overrides",
        _empty_schedule_overrides,
    )
    monkeypatch.setattr(
        dagster_schedule,
        "execute_audited_schedule_command",
        _audit_schedule_command,
    )
    monkeypatch.setattr(
        mois_source_precheck,
        "ensure_mois_source_sync_for_plan",
        _ready_mois_source_sync,
    )
    return TestClient(
        app,
        headers={"Idempotency-Key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
    )


def _malformed_run_detail_payload(case: str) -> dict[str, Any]:
    event_connection: object = {
        "cursor": None,
        "hasMore": False,
        "events": [],
    }
    run: dict[str, Any] = {
        "__typename": "Run",
        "runId": "run-1",
        "status": "SUCCESS",
        "tags": [],
        "eventConnection": event_connection,
    }
    if case == "missing_run_id":
        run.pop("runId")
    elif case == "empty_run_id":
        run["runId"] = ""
    elif case == "mismatched_run_id":
        run["runId"] = "other-run"
    elif case == "non_object_connection":
        run["eventConnection"] = []
    elif case == "missing_events":
        assert isinstance(event_connection, dict)
        event_connection.pop("events")
    elif case == "non_boolean_has_more":
        assert isinstance(event_connection, dict)
        event_connection["hasMore"] = "false"
    elif case == "non_list_events":
        assert isinstance(event_connection, dict)
        event_connection["events"] = {}
    elif case == "non_string_cursor":
        assert isinstance(event_connection, dict)
        event_connection["cursor"] = 1
    elif case == "missing_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection["hasMore"] = True
    elif case == "empty_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection.update({"cursor": "", "hasMore": True})
    elif case == "oversized_next_cursor":
        assert isinstance(event_connection, dict)
        event_connection.update({"cursor": "c" * 2049, "hasMore": True})
    else:  # pragma: no cover - 테스트 파라미터 오타 방어
        raise AssertionError(f"unknown malformed case: {case}")
    return {"data": {"runOrError": run}}


def _job(
    job_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    status: str = "running",
    payload: dict[str, Any] | None = None,
    dagster_run_id: str | None = "run-1",
    provider: str | None = MOIS_PROVIDER_NAME,
    dataset_key: str | None = DATASET_KEY_BULK,
) -> OpsImportJob:
    return OpsImportJob(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id=None,
        parent_job_id=None,
        update_request_id="22222222-2222-2222-2222-222222222222",
        payload=(
            payload
            if payload is not None
            else {
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
                "request_id": "22222222-2222-2222-2222-222222222222",
            }
        ),
        status=status,
        progress=40,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=_NOW,
        started_at=_NOW,
        finished_at=None,
        heartbeat_at=_NOW,
        dagster_run_id=dagster_run_id,
        provider=provider,
        dataset_key=dataset_key,
    )


def _update_request(
    request_id: str = "22222222-2222-2222-2222-222222222222",
    *,
    job_id: str = "11111111-1111-1111-1111-111111111111",
    status: str = "queued",
    dispatch_requested_at: datetime | None = None,
    operator: str = "tester",
    reason: str | None = "unit",
    priority: int = 50,
) -> FeatureUpdateRequest:
    return FeatureUpdateRequest(
        request_id=request_id,
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "dataset_wide",
        },
        providers=(),
        dataset_keys=(),
        update_policy={},
        run_mode="queued",
        priority=priority,
        status=status,
        matched_scope={"feature_count": 1},
        job_id=job_id,
        dagster_run_id="run-1",
        operator=operator,
        reason=reason,
        error_message=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
        generation=1,
        effective_sync_scope="dataset_wide",
        dispatch_requested_at=dispatch_requested_at,
    )


def _cancellation_detail(
    *,
    root_kind: str = "import_job",
    root_id: str = "11111111-1111-1111-1111-111111111111",
) -> PipelineCancellationDetailRecord:
    return PipelineCancellationDetailRecord.model_validate(
        {
            "cancellation_id": "77777777-7777-4777-8777-777777777777",
            "previous_cancellation_id": None,
            "root": {"kind": root_kind, "id": root_id},
            "status": "completed",
            "requested_at": _NOW,
            "requested_by": "local-dev",
            "reason": "혼잡 시간대 회피",
            "error": None,
            "updated_at": _NOW,
            "finished_at": _NOW,
            "retryable": False,
            "unresolved_member_count": 0,
            "members": [
                {
                    "job_id": "11111111-1111-1111-1111-111111111111",
                    "dagster_run_id": "run-1",
                    "operation_kind": None,
                    "requires_run_termination": True,
                    "initial_status": "running",
                    "result": "cancelled",
                    "terminal_status": "cancelled",
                    "error": None,
                    "updated_at": _NOW,
                }
            ],
            "dagster_runs": [
                {
                    "dagster_run_id": "run-1",
                    "engine_started_at": _NOW,
                    "engine_finished_at": _NOW,
                    "initial_status": "STARTED",
                    "termination_reserved_at": _NOW,
                    "result": "cancelled",
                    "terminal_status": "CANCELED",
                    "error": None,
                    "updated_at": _NOW,
                }
            ],
            "committed_data_rolled_back": False,
            "warnings": ["이미 commit된 scope 데이터는 rollback하지 않습니다."],
        }
    )


def _cancellation_domain_detail() -> PipelineCancellationDetail:
    return PipelineCancellationDetail(
        attempt=PipelineCancellationAttempt(
            cancellation_id="77777777-7777-4777-8777-777777777777",
            previous_cancellation_id=None,
            root_kind="import_job",
            root_id="11111111-1111-1111-1111-111111111111",
            status="completed",
            requested_by="local-dev",
            reason="혼잡 시간대 회피",
            error=None,
            requested_at=_NOW,
            updated_at=_NOW,
            finished_at=_NOW,
        ),
        members=(
            PipelineCancellationMember(
                cancellation_id="77777777-7777-4777-8777-777777777777",
                job_id="11111111-1111-1111-1111-111111111111",
                dagster_run_id="run-1",
                operation_kind=None,
                requires_run_termination=True,
                initial_status="running",
                result="cancelled",
                terminal_status="cancelled",
                error=None,
                updated_at=_NOW,
            ),
        ),
        runs=(
            PipelineCancellationRun(
                cancellation_id="77777777-7777-4777-8777-777777777777",
                dagster_run_id="run-1",
                initial_status="STARTED",
                termination_reserved_at=_NOW,
                result="cancelled",
                terminal_status="CANCELED",
                error=None,
                updated_at=_NOW,
            ),
        ),
    )


def _event(
    event_id: str = "55555555-5555-5555-5555-555555555555",
) -> OpsImportJobEvent:
    return OpsImportJobEvent(
        event_id=event_id,
        job_id="11111111-1111-1111-1111-111111111111",
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BULK,
        sync_scope="dataset_wide",
        feature_id=None,
        stage="loading",
        level="error",
        code="provider.timeout",
        message="boom",
        payload={},
        occurred_at=_NOW,
    )


def _execution(
    *,
    kind: str = "import_job",
    execution_id: str = "11111111-1111-1111-1111-111111111111",
    status: str = "running",
    cancellation: PipelineCancellationSummary | None = None,
) -> PipelineExecution:
    return PipelineExecution(
        kind=kind,
        id=execution_id,
        status=status,
        created_at=_NOW,
        providers=(MOIS_PROVIDER_NAME,),
        dataset_keys=(DATASET_KEY_BULK,),
        provider_datasets=(
            PipelineProviderDatasetIdentity(
                provider=MOIS_PROVIDER_NAME,
                dataset_key=DATASET_KEY_BULK,
                sync_scope="dataset_wide",
                operation_member_id="11111111-1111-1111-1111-111111111111",
                status="running",
            ),
        ),
        progress=40 if kind == "import_job" else None,
        current_stage="loading" if kind == "import_job" else None,
        scope_type=None if kind == "import_job" else "provider_dataset",
        priority=None if kind == "import_job" else 50,
        run_mode=None if kind == "import_job" else "queued",
        operator=None if kind == "import_job" else "tester",
        error_message=None,
        started_at=_NOW,
        finished_at=None,
        dagster_run_id="run-1",
        dagster_run_status=None,
        trigger_kind="update_request" if kind == "update_request" else "manual",
        operation_registry_version=None,
        requested_job_id=(None if kind == "import_job" else "11111111-1111-1111-1111-111111111111"),
        linked_job_count=1,
        projected_job=PipelineProjectedJob(
            id="11111111-1111-1111-1111-111111111111",
            job_kind="feature_update_request",
            status="running",
            progress=40,
            current_stage="loading",
            error_message=None,
            created_at=_NOW,
            started_at=_NOW,
            finished_at=None,
            dagster_run_id="run-1",
            dagster_run_status=None,
            trigger_kind="manual",
            operation_registry_version=None,
            load_batch_id=None,
            parent_job_id=None,
            depth=0,
        ),
        cancellation=cancellation,
    )


def _counts() -> PipelineStatusCounts:
    return PipelineStatusCounts(
        operations_by_status={"queued": 6, "running": 1, "failed": 3, "done": 7},
        active_operations=7,
        failed_operations_24h=4,
    )


_SCHEDULES_GRAPHQL_PAYLOAD: dict[str, Any] = {
    "data": {
        "repositoriesOrError": {
            "__typename": "RepositoryConnection",
            "nodes": [
                {
                    "name": "__repository__",
                    "location": {"name": "kortravelmap.dagster.definitions"},
                    "schedules": [
                        {
                            "name": ("feature_weather_kma_short_forecast_hourly_schedule"),
                            "cronSchedule": "20 * * * *",
                            "pipelineName": "feature_weather_kma_short_forecast_job",
                            "mode": "default",
                            "executionTimezone": "Asia/Seoul",
                            "defaultStatus": "RUNNING",
                            "canReset": True,
                            "scheduleState": {
                                "id": "state-1::selector",
                                "selectorId": "sel-1",
                                "status": "RUNNING",
                                "repositoryName": "__repository__",
                                "repositoryLocationName": ("kortravelmap.dagster.definitions"),
                                "ticks": [],
                            },
                        }
                    ],
                    "sensors": [
                        {
                            "name": "feature_update_request_queue_sensor",
                            "sensorState": {"status": "RUNNING", "ticks": []},
                        },
                        {
                            "name": "feature_update_request_failure_sensor",
                            "sensorState": {"status": "STOPPED", "ticks": []},
                        },
                    ],
                }
            ],
        }
    }
}


def _single_schedule_payload(schedule_name: str, job_name: str) -> dict[str, Any]:
    return {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [
                    {
                        "name": "__repository__",
                        "location": {"name": "kortravelmap.dagster.definitions"},
                        "schedules": [
                            {
                                "name": schedule_name,
                                "cronSchedule": "0 0 * * *",
                                "pipelineName": job_name,
                                "mode": "default",
                                "executionTimezone": "Asia/Seoul",
                                "defaultStatus": "STOPPED",
                                "canReset": True,
                                "scheduleState": {
                                    "status": "STOPPED",
                                    "repositoryName": "__repository__",
                                    "repositoryLocationName": ("kortravelmap.dagster.definitions"),
                                },
                            }
                        ],
                    }
                ],
            }
        }
    }


_RUNS_GRAPHQL_PAYLOAD: dict[str, Any] = {
    "data": {
        "version": "1.13.7",
        "repositoriesOrError": _SCHEDULES_GRAPHQL_PAYLOAD["data"]["repositoriesOrError"],
        "runsOrError": {
            "__typename": "Runs",
            "results": [
                {
                    "runId": "run-1",
                    "jobName": "kma_short_forecast_job",
                    "status": "FAILURE",
                    "startTime": 1.0,
                    "endTime": 2.0,
                    "updateTime": 2.0,
                    "tags": [{"key": "dagster/job", "value": "x"}],
                },
                {
                    "runId": "run-2",
                    "jobName": "kma_short_forecast_job",
                    "status": "SUCCESS",
                    "startTime": 3.0,
                    "endTime": 4.0,
                    "updateTime": 4.0,
                    "tags": [],
                },
            ],
        },
    }
}


@pytest.mark.unit
def test_pipeline_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_states = {"queued", "running", "done", "failed", "cancelled"}
    for path in _PIPELINE_PATHS:
        assert path in spec["paths"], path
    # kind는 enum 경로 파라미터다 (import_job|update_request).
    detail_params = spec["paths"]["/v1/ops/pipeline/executions/{kind}/{execution_id}"]["get"][
        "parameters"
    ]
    kind_param = next(p for p in detail_params if p["name"] == "kind")
    assert kind_param["schema"]["enum"] == ["import_job", "update_request"]
    event_params = spec["paths"]["/v1/ops/pipeline/events"]["get"]["parameters"]
    assert "sync_scope" in {parameter["name"] for parameter in event_params}
    event_record = spec["components"]["schemas"]["PipelineJobEventRecord"]
    assert "sync_scope" in event_record["required"]
    assert "canonical_url" in spec["components"]["schemas"][
        "PipelineExecutionsData"
    ]["required"]
    assert "canonical_url" in spec["components"]["schemas"][
        "PipelineEventsData"
    ]["required"]
    # 갱신 요청 생성은 기존 6-type scope union 계약을 그대로 공유한다.
    request_schema = spec["components"]["schemas"]["FeatureUpdateRequestCreateRequest"]
    assert len(request_schema["properties"]["scope"]["oneOf"]) == 6
    create_response = spec["paths"]["/v1/ops/pipeline/requests"]["post"]["responses"]["201"][
        "content"
    ]["application/json"]["schema"]
    assert create_response["$ref"].endswith("/FeatureUpdateRequestCreateResponse")
    reused_response = spec["paths"]["/v1/ops/pipeline/requests"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert reused_response["$ref"].endswith("/FeatureUpdateRequestCreateResponse")
    create_operation = spec["paths"]["/v1/ops/pipeline/requests"]["post"]
    idempotency_header = next(
        parameter
        for parameter in create_operation["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )
    assert idempotency_header["required"] is True
    assert idempotency_header["schema"]["format"] == "uuid"
    assert (
        "idempotent_replay"
        in spec["components"]["schemas"]["FeatureUpdateRequestCreateResponse"]["required"]
    )
    create_responses = spec["paths"]["/v1/ops/pipeline/requests"]["post"]["responses"]
    for code in ("409", "502", "503"):
        schema = create_responses[code]["content"]["application/problem+json"]["schema"]
        assert schema["$ref"].endswith("/ProblemDetail")
    preview_response = spec["paths"]["/v1/ops/pipeline/requests/preview"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert preview_response["$ref"].endswith("/FeatureUpdateRequestPreviewResponse")
    run_now_response = spec["paths"]["/v1/ops/pipeline/requests/{request_id}/run-now"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert run_now_response["$ref"].endswith("/FeatureUpdateRequestMutationResponse")
    schemas = spec["components"]["schemas"]
    for schema_name in (
        "PipelineExecutionRecord",
        "PipelineExecutionRootRecord",
        "PipelineProjectedJobRecord",
    ):
        schema = schemas[schema_name]
        assert schema["properties"]["id"]["format"] == "uuid"
        assert set(schema["properties"]["status"]["enum"]) == operation_states
        assert {
            "dagster_run_status",
            "trigger_kind",
            "operation_registry_version",
        } <= set(schema["required"])
    root_schema = schemas["PipelineExecutionRootRecord"]
    assert {"projected_job", "cancellation"} <= set(root_schema["required"])
    assert "lineage_owner" not in root_schema["properties"]
    pair_schema = schemas["PipelineProviderDatasetIdentityRecord"]
    assert pair_schema["properties"]["operation_member_id"]["format"] == "uuid"
    assert set(pair_schema["properties"]["status"]["enum"]) == operation_states
    import_job_schema = schemas["PipelineImportJobRecord"]
    assert import_job_schema["properties"]["job_id"]["format"] == "uuid"
    assert import_job_schema["properties"]["load_batch_id"]["anyOf"][0]["format"] == "uuid"
    assert import_job_schema["properties"]["parent_job_id"]["anyOf"][0]["format"] == "uuid"
    assert set(import_job_schema["properties"]["status"]["enum"]) == operation_states
    assert {
        "trigger_kind",
        "operation_registry_version",
        "dagster_run_status",
    } <= set(import_job_schema["required"])
    # commands body는 4종 enum이다.
    command_schema = spec["components"]["schemas"]["PipelineScheduleCommandRequest"]
    assert command_schema["properties"]["command"]["enum"] == [
        "run",
        "start",
        "stop",
        "reset",
    ]
    assert set(command_schema["properties"]) == {"command", "reason"}
    update_schema = spec["components"]["schemas"]["PipelineScheduleUpdateRequest"]
    assert set(update_schema["properties"]) == {"cron_schedule", "reason"}
    schedule_schema = spec["components"]["schemas"]["DagsterSchedule"]
    assert {
        "effective_cron_schedule",
        "override_saved",
        "override_effective",
        "can_run_now",
        "disabled_reason",
    } <= set(schedule_schema["required"])
    command_result_schema = spec["components"]["schemas"]["PipelineScheduleCommandData"]
    assert {
        "effective_cron_schedule",
        "save_status",
        "reload_status",
        "effective_status",
        "audit_status",
    } <= set(command_result_schema["required"])
    assert "audit_command_id" in command_result_schema["properties"]
    assert command_result_schema["properties"]["outcome_certainty"]["enum"] == [
        "confirmed",
        "uncertain",
    ]
    assert "reloaded" not in command_result_schema["properties"]
    resolution_schema = spec["components"]["schemas"]["PipelineScheduleClaimResolutionRequest"]
    assert resolution_schema["properties"]["resolution"]["enum"] == [
        "confirmed_applied",
        "confirmed_not_applied",
    ]
    assert set(resolution_schema["required"]) == {"resolution", "reason"}
    resolution_result_schema = spec["components"]["schemas"]["DagsterScheduleClaimResolution"]
    assert "replayed" in resolution_result_schema["required"]
    schedule_patch = spec["paths"]["/v1/ops/pipeline/schedules/{schedule_name}"]["patch"]
    assert any(
        parameter.get("name") == "Idempotency-Key" and parameter.get("required") is True
        for parameter in schedule_patch["parameters"]
    )
    for method, path in (
        ("patch", "/v1/ops/pipeline/schedules/{schedule_name}"),
        ("post", "/v1/ops/pipeline/schedules/{schedule_name}/commands"),
    ):
        responses = spec["paths"][path][method]["responses"]
        assert {"409", "422", "500", "502", "503"} <= set(responses)
        for code in ("409", "422", "500", "502", "503"):
            schema = responses[code]["content"]["application/problem+json"]["schema"]
            assert schema["$ref"].endswith("/ProblemDetail")
    resolution_operation = spec["paths"][
        "/v1/ops/pipeline/schedules/{schedule_name}/claims/{command_id}/resolve"
    ]["post"]
    assert {"404", "409", "422", "503"} <= set(resolution_operation["responses"])
    precheck_description = spec["paths"]["/v1/ops/pipeline/prechecks/mois-source-sync"]["get"][
        "description"
    ]
    assert "full-coverage" in precheck_description
    assert "endTime" in precheck_description
    assert "미래" in precheck_description
    detail_operation = spec["paths"]["/v1/ops/pipeline/dagster-runs/{run_id}"]["get"]
    assert {"200", "404", "422", "502", "503", "default"} <= set(detail_operation["responses"])
    assert "/v1/ops/pipeline/nux-seen" not in spec["paths"]
    assert "/v1/ops/dagster/nux-seen" not in spec["paths"]
    detail_schema = spec["components"]["schemas"]["DagsterRunDetailData"]
    assert "현재 event page" in detail_schema["properties"]["failure_reason"]["description"]
    assert "현재 event page" in detail_schema["properties"]["failure_events"]["description"]
    cancel_operation = spec["paths"][
        "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel"
    ]["post"]
    assert {"200", "404", "409", "422", "502", "503", "default"} <= set(
        cancel_operation["responses"]
    )
    for status_code in ("409", "502", "503"):
        assert cancel_operation["responses"][status_code]["headers"]["Retry-After"]["schema"] == {
            "type": "integer"
        }
    update_cancel_operation = spec["paths"][
        "/v1/ops/pipeline/executions/update_request/{execution_id}/cancel"
    ]["post"]
    assert update_cancel_operation["security"] == [{"AdminBFF": []}]
    cancel_request = spec["components"]["schemas"]["PipelineCancellationRequest"]
    assert set(cancel_request["properties"]) == {"reason"}
    cancel_run = spec["components"]["schemas"]["PipelineCancellationRunRecord"]
    assert "termination_reserved_at" in cancel_run["properties"]
    cancellation_root = schemas["PipelineCancellationRootRecord"]
    cancellation_summary = schemas["PipelineCancellationSummaryRecord"]
    cancellation_detail = schemas["PipelineCancellationDetailRecord"]
    assert cancellation_root["properties"]["id"]["format"] == "uuid"
    assert cancellation_summary["properties"]["cancellation_id"]["format"] == "uuid"
    assert cancellation_detail["properties"]["cancellation_id"]["format"] == "uuid"
    assert (
        cancellation_detail["properties"]["previous_cancellation_id"]["anyOf"][0]["format"]
        == "uuid"
    )
    root = spec["components"]["schemas"]["PipelineExecutionRootRecord"]
    assert "provider_datasets" in root["properties"]
    assert "provider_datasets" in root["required"]
    assert "provider_dataset" not in root["properties"]
    pair = spec["components"]["schemas"]["PipelineProviderDatasetIdentityRecord"]
    assert {"sync_scope", "operation_member_id"} <= set(pair["required"])
    assert pair["properties"]["operation_member_id"]["type"] == "string"
    assert "status_source" not in pair["properties"]
    assert {"dagster_run_status", "trigger_kind", "operation_registry_version"} <= set(
        root["properties"]
    )
    overview = spec["components"]["schemas"]["PipelineOverviewData"]
    assert {
        "operations_by_status",
        "active_operations",
        "failed_operations_24h",
    } <= set(overview["properties"])
    assert "import_jobs_by_status" not in overview["properties"]
    event_schema = schemas["PipelineJobEventRecord"]
    assert event_schema["properties"]["event_id"]["format"] == "uuid"
    assert event_schema["properties"]["job_id"]["format"] == "uuid"
    for path in (
        "/v1/ops/pipeline/requests",
        "/v1/ops/pipeline/requests/{request_id}/run-now",
    ):
        conflict = spec["paths"][path]["post"]["responses"]["409"]
        assert "headers" not in conflict


@pytest.mark.unit
def test_pipeline_routes_require_bff_or_ops_principal_when_secret_set(
    session: _FakeSession,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret="pipeline-secret",
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    gated_client = TestClient(app)

    response = gated_client.get("/v1/ops/pipeline/executions")

    assert response.status_code == 401


@pytest.mark.unit
def test_cancel_execution_uses_authenticated_proxy_actor(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret="pipeline-secret",
            admin_trusted_proxy_cidrs=["127.0.0.0/8"],
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
        )
    )
    captured: dict[str, Any] = {}

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _fake_engine() -> Any:
        return object()

    async def _cancel(**kwargs: Any) -> PipelineCancellationDetailRecord:
        captured.update(kwargs)
        return _cancellation_detail()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_engine] = _fake_engine
    monkeypatch.setattr(
        pipeline_mod.pipeline_cancellation_service,
        "cancel_pipeline_execution",
        _cancel,
    )
    gated_client = TestClient(app, client=("127.0.0.1", 50000))

    response = gated_client.post(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
        headers={
            ADMIN_PROXY_SECRET_HEADER: "pipeline-secret",
            ADMIN_ACTOR_HEADER: "admin:reviewer",
        },
        json={"reason": "operator request"},
    )

    assert response.status_code == 200
    assert captured["requested_by"] == "admin:reviewer"


@pytest.mark.unit
def test_exact_import_job_cancel_uses_server_actor_and_cancel_token(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            ops_read_token=_OPS_READ_TOKEN,
            ops_cancel_token=_OPS_CANCEL_TOKEN,
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
        )
    )
    captured: dict[str, Any] = {}

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _fake_engine() -> Any:
        return object()

    async def _cancel(**kwargs: Any) -> PipelineCancellationDetailRecord:
        captured.update(kwargs)
        return _cancellation_detail()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_engine] = _fake_engine
    monkeypatch.setattr(
        pipeline_mod.pipeline_cancellation_service,
        "cancel_pipeline_execution",
        _cancel,
    )
    service_client = TestClient(app, client=("198.51.100.10", 50000))
    path = (
        "/v1/ops/pipeline/executions/import_job/"
        "11111111-1111-1111-1111-111111111111/cancel"
    )

    response = service_client.post(
        path,
        headers={
            ADMIN_ACTOR_HEADER: "spoofed",
            OPS_SCOPE_HEADER: "ops:cancel",
            OPS_TOKEN_HEADER: _OPS_CANCEL_TOKEN,
        },
        json={"reason": "service request"},
    )

    assert response.status_code == 200
    assert captured["requested_by"] == "service:pinvi"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "scope", "token"),
    [
        (
            "put",
            "/v1/ops/datasets/refresh-policy",
            "ops:cancel",
            _OPS_CANCEL_TOKEN,
        ),
        (
            "patch",
            "/v1/ops/pipeline/schedules/example",
            "ops:cancel",
            _OPS_CANCEL_TOKEN,
        ),
        (
            "post",
            "/v1/ops/pipeline/requests",
            "ops:cancel",
            _OPS_CANCEL_TOKEN,
        ),
        (
            "post",
            "/v1/ops/pipeline/executions/update_request/"
            "11111111-1111-1111-1111-111111111111/cancel",
            "ops:cancel",
            _OPS_CANCEL_TOKEN,
        ),
        (
            "post",
            "/v1/ops/pipeline/executions/import_job/"
            "11111111-1111-1111-1111-111111111111/cancel",
            "ops:read",
            _OPS_READ_TOKEN,
        ),
    ],
)
def test_service_principal_rejects_non_bound_mutations(
    method: str,
    path: str,
    scope: str,
    token: str,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            ops_read_token=_OPS_READ_TOKEN,
            ops_cancel_token=_OPS_CANCEL_TOKEN,
        )
    )
    service_client = TestClient(app, client=("198.51.100.10", 50000))

    response = service_client.request(
        method,
        path,
        headers={OPS_SCOPE_HEADER: scope, OPS_TOKEN_HEADER: token},
        json={},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "OPS_SCOPE_FORBIDDEN"


@pytest.mark.unit
def test_overview_combines_db_counts_and_dagster(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_counts(_session: Any) -> PipelineStatusCounts:
        return _counts()

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == pipeline_mod._PIPELINE_OVERVIEW_QUERY
        assert kwargs["variables"] == {"limit": 5}
        return _RUNS_GRAPHQL_PAYLOAD

    monkeypatch.setattr(pipeline_mod, "get_pipeline_status_counts", _fake_counts)
    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/overview?run_limit=5")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["operations_by_status"] == {
        "queued": 6,
        "running": 1,
        "failed": 3,
        "done": 7,
    }
    assert data["active_operations"] == 7
    assert data["failed_operations_24h"] == 4
    dagster = data["dagster"]
    assert dagster["status"] == "ok"
    assert dagster["version"] == "1.13.7"
    assert dagster["run_counts"] == {"FAILURE": 1, "SUCCESS": 1}
    assert dagster["schedule_count"] == 1
    assert dagster["sensor_count"] == 2
    sensor_status = {sensor["name"]: sensor["status"] for sensor in dagster["sensors"]}
    assert sensor_status == {
        "feature_update_request_queue_sensor": "RUNNING",
        "feature_update_request_failure_sensor": "STOPPED",
    }


@pytest.mark.unit
def test_overview_dagster_unavailable_keeps_db_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_counts(_session: Any) -> PipelineStatusCounts:
        return _counts()

    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("dagster down")

    monkeypatch.setattr(pipeline_mod, "get_pipeline_status_counts", _fake_counts)
    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/overview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dagster"]["status"] == "unavailable"
    assert data["dagster"]["errors"] == ["dagster down"]
    assert data["operations_by_status"] == {
        "queued": 6,
        "running": 1,
        "failed": 3,
        "done": 7,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/ops/pipeline/overview",
        "/v1/ops/pipeline/dagster-runs",
        "/v1/ops/pipeline/schedules",
    ],
)
def test_pipeline_projections_redact_invalid_dagster_url_secrets(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            dagster_url="http://dagster.example:12302",
            dagster_graphql_url=(
                "http://user:super-secret@dagster.example:12302/graphql?token=secret"
            ),
            dagster_allowed_hosts=["dagster.example"],
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    async def _fake_counts(_session: Any) -> PipelineStatusCounts:
        return _counts()

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(pipeline_mod, "get_pipeline_status_counts", _fake_counts)

    with TestClient(app) as test_client:
        response = test_client.get(path)

    assert response.status_code == 200
    data = response.json()["data"]
    projection = data["dagster"] if path.endswith("/overview") else data
    assert projection["status"] == "error"
    assert projection["dagster_url"] == ""
    assert projection["graphql_url"] == ""
    assert "super-secret" not in response.text
    assert "token=secret" not in response.text


@pytest.mark.unit
def test_executions_list_passes_filters_and_maps_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_list(_session: Any, **kwargs: Any) -> PipelineExecutionPage:
        captured.update(kwargs)
        return PipelineExecutionPage(
            items=(
                _execution(
                    kind="import_job",
                    cancellation=PipelineCancellationSummary(
                        cancellation_id="77777777-7777-4777-8777-777777777777",
                        status="retryable",
                        requested_at=_NOW,
                        requested_by="admin:test",
                        reason="timeout",
                        retryable=True,
                        unresolved_member_count=1,
                    ),
                ),
                _execution(
                    kind="update_request",
                    execution_id="22222222-2222-2222-2222-222222222222",
                ),
            ),
            next_cursor="cursor-next",
        )

    monkeypatch.setattr(pipeline_mod, "list_pipeline_executions", _fake_list)

    response = client.get(
        "/v1/ops/pipeline/executions",
        params={
            "kind": "import_job",
            "status": "running",
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "dataset_wide",
            "load_batch_id": "33333333-3333-3333-3333-333333333333",
            "parent_job_id": "44444444-4444-4444-4444-444444444444",
            "created_from": "2026-07-01T00:00:00Z",
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    assert captured["kind"] == "import_job"
    assert captured["status"] == "running"
    assert captured["provider"] == MOIS_PROVIDER_NAME
    assert captured["dataset_key"] == DATASET_KEY_BULK
    assert captured["dataset_sync_scopes"] == (
        "dataset_wide",
        None,
    )
    assert captured["load_batch_id"] == "33333333-3333-3333-3333-333333333333"
    assert captured["parent_job_id"] == "44444444-4444-4444-4444-444444444444"
    assert captured["limit"] == 2
    body = response.json()
    assert body["meta"]["page"]["next_cursor"] == "cursor-next"
    assert body["data"]["canonical_url"] == (
        "/v1/ops/pipeline/executions?kind=import_job&status=running&"
        f"provider={MOIS_PROVIDER_NAME}&dataset_key={DATASET_KEY_BULK}&"
        "sync_scope=dataset_wide&"
        "load_batch_id=33333333-3333-3333-3333-333333333333&"
        "parent_job_id=44444444-4444-4444-4444-444444444444&"
        "created_from=2026-07-01T00%3A00%3A00%2B00%3A00"
    )
    items = body["data"]["items"]
    assert [item["kind"] for item in items] == ["import_job", "update_request"]
    assert items[0]["detail_url"] == (
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111"
    )
    assert items[0]["providers"] == [MOIS_PROVIDER_NAME]
    assert items[0]["linked_job_count"] == 1
    assert items[0]["status"] == "running"
    assert items[0]["cancellation"]["status"] == "retryable"
    assert items[0]["cancellation"]["unresolved_member_count"] == 1
    assert items[0]["projected_job"]["detail_url"] == (
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111"
    )
    assert items[1]["requested_job_id"] == ("11111111-1111-1111-1111-111111111111")
    assert items[1]["provider_datasets"] == [
        {
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "dataset_wide",
            "operation_member_id": "11111111-1111-1111-1111-111111111111",
            "status": "running",
        }
    ]
    assert items[1]["projected_job"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert items[1]["dagster_run_id"] == "run-1"


@pytest.mark.unit
def test_executions_list_invalid_cursor_maps_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(_session: Any, **_kwargs: Any) -> PipelineExecutionPage:
        raise PipelineCursorFilterMismatch("pipeline cursor filter mismatch")

    monkeypatch.setattr(pipeline_mod, "list_pipeline_executions", _fake_list)

    response = client.get("/v1/ops/pipeline/executions?cursor=broken")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_executions_list_scope_requires_provider_and_dataset(client: TestClient) -> None:
    response = client.get(
        "/v1/ops/pipeline/executions",
        params={"provider": MOIS_PROVIDER_NAME, "sync_scope": "dataset_wide"},
    )

    assert response.status_code == 422
    assert "sync_scope requires both provider and dataset_key" in response.text


@pytest.mark.unit
@pytest.mark.parametrize(
    "params",
    [
        {"dataset_key": DATASET_KEY_BULK},
        {
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "default",
        },
        {
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": " external_system:x",
        },
    ],
)
def test_executions_list_rejects_incomplete_or_noncanonical_tuple(
    client: TestClient,
    params: dict[str, str],
) -> None:
    response = client.get("/v1/ops/pipeline/executions", params=params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.unit
def test_executions_provider_only_returns_canonical_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty(_session: Any, **_kwargs: Any) -> PipelineExecutionPage:
        return PipelineExecutionPage(items=(), next_cursor=None)

    monkeypatch.setattr(pipeline_mod, "list_pipeline_executions", _empty)
    response = client.get(
        "/v1/ops/pipeline/executions",
        params={"provider": "provider/with slash"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["canonical_url"] == (
        "/v1/ops/pipeline/executions?provider=provider%2Fwith%20slash"
    )


@pytest.mark.unit
def test_execution_detail_import_job_links_request_and_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_job(_session: Any, job_id: str) -> OpsImportJob | None:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        return _job()

    async def _root(*_args: Any, **_kwargs: Any) -> PipelineExecution:
        return _execution(
            kind="update_request",
            execution_id="22222222-2222-2222-2222-222222222222",
        )

    async def _get_request(_session: Any, request_id: str) -> FeatureUpdateRequest | None:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request()

    async def _events(
        _session: Any, job_id: str | None = None, **kwargs: Any
    ) -> OpsImportJobEventPage:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        assert kwargs["level"] == "error"
        return OpsImportJobEventPage(items=(_event(),), next_cursor="ev-cursor")

    async def _current_cancellation(
        _session: Any,
        **kwargs: Any,
    ) -> PipelineCancellationDetail:
        assert kwargs == {
            "kind": "update_request",
            "execution_id": "22222222-2222-2222-2222-222222222222",
        }
        return _cancellation_domain_detail()

    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "get_pipeline_execution", _root)
    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)
    monkeypatch.setattr(
        pipeline_mod,
        "get_current_pipeline_cancellation_detail",
        _current_cancellation,
    )

    response = client.get(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111?level=error"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution"]["kind"] == "import_job"
    assert data["execution"]["dagster_run_id"] == "run-1"
    assert data["import_job"]["job_id"] == "11111111-1111-1111-1111-111111111111"
    assert data["import_job"]["dagster_run_id"] == "run-1"
    assert data["update_request"]["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert data["update_request"]["status_url"] == (
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )
    assert [event["event_id"] for event in data["events"]] == [
        "55555555-5555-5555-5555-555555555555"
    ]
    assert data["events_next_cursor"] == "ev-cursor"
    assert data["execution"]["status"] == "running"
    assert data["cancellation"]["status"] == "completed"
    assert data["cancellation"]["dagster_runs"][0]["termination_reserved_at"]


@pytest.mark.unit
def test_execution_detail_update_request_links_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_request(_session: Any, request_id: str) -> FeatureUpdateRequest | None:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request()

    async def _get_job(_session: Any, job_id: str) -> OpsImportJob | None:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        return _job()

    async def _events(
        _session: Any, job_id: str | None = None, **_kwargs: Any
    ) -> OpsImportJobEventPage:
        return OpsImportJobEventPage(items=(_event(),), next_cursor=None)

    async def _root(*_args: Any, **_kwargs: Any) -> PipelineExecution:
        return _execution(
            kind="update_request",
            execution_id="22222222-2222-2222-2222-222222222222",
            status="queued",
        )

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)
    monkeypatch.setattr(pipeline_mod, "get_pipeline_execution", _root)

    response = client.get(
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    execution = data["execution"]
    root = data["root"]
    assert execution["kind"] == root["kind"] == "update_request"
    assert execution["id"] == root["id"]
    assert execution["status"] == root["status"] == "queued"
    assert execution["provider"] == root["provider_datasets"][0]["provider"]
    assert execution["dataset_key"] == root["provider_datasets"][0]["dataset_key"]
    assert execution["trigger_kind"] == root["trigger_kind"] == "update_request"
    assert data["import_job"]["status"] == "running"
    assert data["cancellation"] is None
    assert data["events_next_cursor"] is None


@pytest.mark.unit
def test_execution_detail_non_exact_request_keeps_arrays_on_root_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(
        _update_request(),
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-1"]},
        providers=("provider-a", "provider-b"),
        dataset_keys=("dataset-a", "dataset-b"),
    )
    root = replace(
        _execution(
            kind="update_request",
            execution_id=request.request_id,
            status=request.status,
        ),
        providers=request.providers,
        dataset_keys=request.dataset_keys,
        provider_datasets=(),
        scope_type=request.scope_type,
    )

    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return request

    async def _get_job(_session: Any, _job_id: str) -> OpsImportJob | None:
        return _job(provider=None, dataset_key=None)

    async def _events(
        _session: Any, _job_id: str | None = None, **_kwargs: Any
    ) -> OpsImportJobEventPage:
        return OpsImportJobEventPage(items=(), next_cursor=None)

    async def _root(*_args: Any, **_kwargs: Any) -> PipelineExecution:
        return root

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)
    monkeypatch.setattr(pipeline_mod, "get_pipeline_execution", _root)

    response = client.get(f"/v1/ops/pipeline/executions/update_request/{request.request_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution"]["provider"] is None
    assert data["execution"]["dataset_key"] is None
    assert data["execution"]["trigger_kind"] == "update_request"
    assert data["root"]["providers"] == ["provider-a", "provider-b"]
    assert data["root"]["dataset_keys"] == ["dataset-a", "dataset-b"]
    assert data["root"]["provider_datasets"] == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scope_type", "scope", "job_provider", "job_dataset_key"),
    [
        (
            "feature_ids",
            {"type": "feature_ids", "feature_ids": ["feature-1"]},
            None,
            None,
        ),
        (
            "provider_dataset",
            {
                "type": "provider_dataset",
                "provider": "typed-provider",
                "dataset_key": "typed-dataset",
            },
            "typed-provider",
            "typed-dataset",
        ),
    ],
)
def test_request_execution_scalar_identity_uses_linked_typed_job(
    scope_type: str,
    scope: dict[str, Any],
    job_provider: str | None,
    job_dataset_key: str | None,
) -> None:
    request = replace(
        _update_request(),
        scope_type=scope_type,
        scope=scope,
        providers=("provider-array",),
        dataset_keys=("dataset-array",),
    )

    execution = pipeline_mod._execution_from_request(
        request,
        _job(provider=job_provider, dataset_key=job_dataset_key),
    )

    assert execution.provider == job_provider
    assert execution.dataset_key == job_dataset_key
    assert execution.trigger_kind == "update_request"


@pytest.mark.unit
def test_execution_detail_unknown_kind_is_422(client: TestClient) -> None:
    response = client.get("/v1/ops/pipeline/executions/dagster_run/run-1")

    assert response.status_code == 422


@pytest.mark.unit
def test_execution_detail_missing_import_job_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_job(_session: Any, _job_id: str) -> OpsImportJob | None:
        return None

    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)

    response = client.get(
        "/v1/ops/pipeline/executions/import_job/aaaaaaaa-0000-4000-8000-000000000000"
    )

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/v1/ops/pipeline/executions/import_job/not-a-uuid",
        "/v1/ops/pipeline/executions/update_request/12345",
    ],
)
def test_execution_detail_non_uuid_id_is_422(client: TestClient, path: str) -> None:
    # 비-UUID id는 DB uuid CAST(500)까지 가지 않고 경로 검증에서 422로 떨어진다.
    response = client.get(path)

    assert response.status_code == 422


@pytest.mark.unit
def test_cancel_execution_non_uuid_id_is_422(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/executions/import_job/not-a-uuid/cancel",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_cancel_import_job_uses_authenticated_actor_and_coordinator(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _cancel(**kwargs: Any) -> PipelineCancellationDetailRecord:
        calls.append(kwargs)
        return _cancellation_detail()

    monkeypatch.setattr(
        pipeline_mod.pipeline_cancellation_service,
        "cancel_pipeline_execution",
        _cancel,
    )

    response = client.post(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
        json={"reason": "혼잡 시간대 회피"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"
    assert response.json()["data"]["dagster_runs"][0]["termination_reserved_at"]
    assert len(calls) == 1
    assert calls[0]["kind"] == "import_job"
    assert calls[0]["execution_id"] == "11111111-1111-1111-1111-111111111111"
    assert calls[0]["requested_by"] == "local-dev"
    assert calls[0]["reason"] == "혼잡 시간대 회피"
    assert calls[0]["engine"] is not None
    assert isinstance(calls[0]["settings"], ApiSettings)
    assert calls[0]["http_client"] is not None


@pytest.mark.unit
def test_cancel_execution_rejects_actor_in_body(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
        json={"operator": "spoofed"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_cancel_execution_maps_typed_failures_to_problem_details(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = PipelineCancellationRootRecord(
        kind="import_job",
        id="11111111-1111-1111-1111-111111111111",
    )
    detail = _cancellation_detail()
    cases = (
        (
            pipeline_mod.pipeline_cancellation_service.PipelineExecutionNotFound(
                "missing execution"
            ),
            404,
            "PIPELINE_EXECUTION_NOT_FOUND",
            None,
        ),
        (
            pipeline_mod.pipeline_cancellation_service.PipelineCancellationInProgress(
                "coordinator busy",
                root=root,
                detail=detail,
                retry_after_seconds=7,
            ),
            409,
            "PIPELINE_CANCELLATION_IN_PROGRESS",
            "7",
        ),
        (
            pipeline_mod.pipeline_cancellation_service.DagsterTerminateFailed(
                "terminate rejected",
                root=root,
                detail=detail,
                retry_after_seconds=7,
            ),
            502,
            "DAGSTER_TERMINATE_FAILED",
            "7",
        ),
        (
            pipeline_mod.pipeline_cancellation_service.DagsterUnavailable(
                "dagster unavailable",
                root=root,
                detail=detail,
                retry_after_seconds=7,
            ),
            503,
            "DAGSTER_UNAVAILABLE",
            "7",
        ),
    )

    for error, expected_status, expected_code, retry_after in cases:

        async def _cancel(
            _error: Exception = error,
            **_kwargs: Any,
        ) -> PipelineCancellationDetailRecord:
            raise _error

        monkeypatch.setattr(
            pipeline_mod.pipeline_cancellation_service,
            "cancel_pipeline_execution",
            _cancel,
        )
        response = client.post(
            "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
            json={"reason": "operator request"},
        )

        assert response.status_code == expected_status
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == expected_code
        assert response.headers.get("retry-after") == retry_after
        if expected_status != 404:
            assert response.json()["details"]["cancellation_id"] == str(detail.cancellation_id)


@pytest.mark.unit
def test_cancel_update_request_uses_same_coordinator(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _cancel(**kwargs: Any) -> PipelineCancellationDetailRecord:
        calls.append(kwargs)
        return _cancellation_detail(
            root_kind="update_request",
            root_id="22222222-2222-2222-2222-222222222222",
        )

    monkeypatch.setattr(
        pipeline_mod.pipeline_cancellation_service,
        "cancel_pipeline_execution",
        _cancel,
    )

    response = client.post(
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222/cancel",
        json={"reason": "잘못된 scope"},
    )

    assert response.status_code == 200
    assert calls[0]["kind"] == "update_request"
    assert calls[0]["execution_id"] == "22222222-2222-2222-2222-222222222222"
    assert calls[0]["requested_by"] == "local-dev"
    assert calls[0]["reason"] == "잘못된 scope"


@pytest.mark.unit
def test_events_global_list_passes_filters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _events(
        _session: Any, job_id: str | None = None, **kwargs: Any
    ) -> OpsImportJobEventPage:
        captured["job_id"] = job_id
        captured.update(kwargs)
        return OpsImportJobEventPage(items=(_event(),), next_cursor="ev-next")

    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)

    response = client.get(
        "/v1/ops/pipeline/events",
        params={
            "level": "error",
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "dataset_wide",
            "page_size": 10,
        },
    )

    assert response.status_code == 200
    assert captured["job_id"] is None
    assert captured["level"] == "error"
    assert captured["provider"] == MOIS_PROVIDER_NAME
    assert captured["dataset_key"] == DATASET_KEY_BULK
    assert captured["sync_scope"] == "dataset_wide"
    assert captured["limit"] == 10
    body = response.json()
    assert body["meta"]["page"]["next_cursor"] == "ev-next"
    assert body["data"]["canonical_url"] == (
        "/v1/ops/pipeline/events?level=error&"
        f"provider={MOIS_PROVIDER_NAME}&dataset_key={DATASET_KEY_BULK}&"
        "sync_scope=dataset_wide"
    )
    assert body["data"]["items"][0]["code"] == "provider.timeout"
    assert body["data"]["items"][0]["sync_scope"] == "dataset_wide"


@pytest.mark.unit
def test_events_non_uuid_job_id_is_422(client: TestClient) -> None:
    response = client.get("/v1/ops/pipeline/events", params={"job_id": "not-a-uuid"})

    assert response.status_code == 422


@pytest.mark.unit
def test_events_sync_scope_without_provider_dataset_pair_is_422(
    client: TestClient,
) -> None:
    response = client.get(
        "/v1/ops/pipeline/events",
        params={"sync_scope": "target_grids"},
    )

    assert response.status_code == 422
    assert "requires both provider and dataset_key" in response.text


@pytest.mark.unit
@pytest.mark.parametrize(
    "params",
    [
        {"dataset_key": DATASET_KEY_BULK},
        {
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "default",
        },
        {
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
            "sync_scope": "external_system:",
        },
    ],
)
def test_events_reject_incomplete_or_noncanonical_tuple(
    client: TestClient,
    params: dict[str, str],
) -> None:
    response = client.get("/v1/ops/pipeline/events", params=params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.unit
def test_events_filter_bound_cursor_mismatch_is_typed_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _events(*_args: Any, **_kwargs: Any) -> OpsImportJobEventPage:
        raise OpsCursorFilterMismatch("import_job_events cursor filter mismatch")

    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)
    response = client.get(
        "/v1/ops/pipeline/events",
        params={"provider": MOIS_PROVIDER_NAME, "cursor": "different-filter"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_dagster_runs_panel_parses_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == pipeline_mod._PIPELINE_DAGSTER_RUNS_QUERY
        assert kwargs["variables"] == {"limit": 5}
        return {"data": {"runsOrError": _RUNS_GRAPHQL_PAYLOAD["data"]["runsOrError"]}}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs?limit=5")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["run_counts"] == {"FAILURE": 1, "SUCCESS": 1}
    assert [run["run_id"] for run in data["runs"]] == ["run-1", "run-2"]


@pytest.mark.unit
def test_dagster_runs_panel_degrades_to_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("dagster down")

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "unavailable"
    assert data["runs"] == []


@pytest.mark.unit
def test_dagster_run_detail_returns_page_local_structured_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        calls.append({"query": kwargs["query"], "variables": kwargs["variables"]})
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "run-1",
                    "jobName": "provider_job",
                    "status": "FAILURE",
                    "tags": [],
                    "eventConnection": {
                        "cursor": "event-next",
                        "hasMore": True,
                        "events": [
                            {
                                "__typename": "RunFailureEvent",
                                "message": "run failed",
                                "timestamp": "1710000030.0",
                                "level": "ERROR",
                                "stepKey": None,
                                "eventType": "RUN_FAILURE",
                                "error": {
                                    "message": "boom",
                                    "stack": ["traceback"],
                                    "className": "RuntimeError",
                                },
                            }
                        ],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get(
        "/v1/ops/pipeline/dagster-runs/%20run-1%20",
        params={"page_size": 5, "after": "event-before"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["run"]["status"] == "FAILURE"
    assert data["event_cursor"] == "event-next"
    assert data["event_has_more"] is True
    assert data["failure_reason"] == "RuntimeError: boom"
    assert data["failure_events"][0]["error"]["class_name"] == "RuntimeError"
    assert calls == [
        {
            "query": dagster_query._DAGSTER_RUN_DETAIL_QUERY,
            "variables": {
                "runId": "run-1",
                "eventLimit": 5,
                "afterCursor": "event-before",
            },
        }
    ]


@pytest.mark.unit
def test_dagster_run_detail_not_found_is_problem_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return {
            "data": {
                "runOrError": {
                    "__typename": "RunNotFoundError",
                    "message": "Run not found",
                    "runId": "missing-run",
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs/missing-run")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "DAGSTER_RUN_NOT_FOUND"
    assert problem["details"] == {
        "run_id": "missing-run",
        "errors": ["Run not found"],
    }


@pytest.mark.unit
def test_dagster_run_detail_round_trips_encoded_opaque_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs["variables"])
        return {
            "data": {
                "runOrError": {
                    "__typename": "Run",
                    "runId": "typed/run id",
                    "jobName": "provider_job",
                    "status": "SUCCESS",
                    "tags": [],
                    "eventConnection": {
                        "cursor": None,
                        "hasMore": False,
                        "events": [],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    href = f"/v1/ops/pipeline/dagster-runs/{quote('typed/run id', safe='')}"
    assert href == "/v1/ops/pipeline/dagster-runs/typed%2Frun%20id"

    response = client.get(href)

    assert response.status_code == 200
    assert response.json()["data"]["run"]["run_id"] == "typed/run id"
    assert captured["runId"] == "typed/run id"


@pytest.mark.unit
def test_dagster_run_detail_unavailable_is_problem_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("dagster down")

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs/run-1")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_UNAVAILABLE"
    assert response.json()["details"]["errors"] == ["dagster down"]


@pytest.mark.unit
def test_dagster_run_detail_query_error_is_problem_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return {"errors": [{"message": "query failed", "path": ["runOrError"]}]}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs/run-1")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_QUERY_FAILED"
    assert response.json()["details"]["errors"] == ["query failed"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure_kind",
    ["http_status", "invalid_json", "python_error", "disallowed_url"],
)
def test_dagster_run_detail_upstream_response_error_is_problem_502(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    calls = 0

    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if failure_kind == "http_status":
            request = httpx.Request("POST", "http://dagster.example:12302/graphql")
            response = httpx.Response(502, request=request)
            raise httpx.HTTPStatusError(
                "Dagster upstream HTTP 502",
                request=request,
                response=response,
            )
        if failure_kind == "python_error":
            return {
                "data": {
                    "runOrError": {
                        "__typename": "PythonError",
                        "message": "Dagster resolver failed",
                    }
                }
            }
        if failure_kind == "disallowed_url":
            raise AssertionError("disallowed Dagster URL must not be requested")
        raise ValueError("Dagster JSON decode failed")

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    if failure_kind == "disallowed_url":

        def _unexpected_http_client(_request: object, _settings: object) -> httpx.AsyncClient:
            raise AssertionError("disallowed Dagster URL must not create an HTTP client")

        monkeypatch.setattr(
            pipeline_mod,
            "_http_client_from_request",
            _unexpected_http_client,
        )

    dagster_url = (
        "http://disallowed.example:12302"
        if failure_kind == "disallowed_url"
        else "http://dagster.example:12302"
    )
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            dagster_url=dagster_url,
            dagster_allowed_hosts=["dagster.example"],
        )
    )
    with TestClient(app) as test_client:
        response = test_client.get("/v1/ops/pipeline/dagster-runs/run-1")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_QUERY_FAILED"
    assert calls == (0 if failure_kind == "disallowed_url" else 1)


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    [
        "missing_run_id",
        "empty_run_id",
        "mismatched_run_id",
        "non_object_connection",
        "missing_events",
        "non_boolean_has_more",
        "non_list_events",
        "non_string_cursor",
        "missing_next_cursor",
        "empty_next_cursor",
        "oversized_next_cursor",
    ],
)
def test_dagster_run_detail_rejects_malformed_run_as_problem_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return _malformed_run_detail_payload(case)

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/dagster-runs/run-1")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "DAGSTER_QUERY_FAILED"
    assert problem["details"]["run_id"] == "run-1"
    assert problem["details"]["errors"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/ops/pipeline/dagster-runs/%20%20", {}),
        (f"/v1/ops/pipeline/dagster-runs/{'r' * 256}", {}),
        ("/v1/ops/pipeline/dagster-runs/run-1", {"after": ""}),
        ("/v1/ops/pipeline/dagster-runs/run-1", {"after": "c" * 2049}),
        ("/v1/ops/pipeline/dagster-runs/run-1", {"page_size": 201}),
    ],
)
def test_dagster_run_detail_rejects_invalid_path_and_query(
    client: TestClient,
    path: str,
    params: dict[str, object],
) -> None:
    response = client.get(path, params=params)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_mois_source_sync_precheck_filters_exact_job_and_checks_fresh_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == mois_source_precheck._QUERY
        assert kwargs["variables"] == {"filter": {"pipelineName": "mois_localdata_source_sync"}}
        now = datetime.now(UTC).timestamp()
        return {
            "data": {
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "mois-source-run-1",
                            "jobName": "mois_localdata_source_sync",
                            "status": "SUCCESS",
                            "startTime": now - 120,
                            "endTime": now - 60,
                            "updateTime": now - 60,
                            "tags": [
                                {
                                    "key": MOIS_SOURCE_SYNC_COVERAGE_TAG,
                                    "value": MOIS_SOURCE_SYNC_FULL_COVERAGE,
                                }
                            ],
                        }
                    ],
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.get("/v1/ops/pipeline/prechecks/mois-source-sync")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_name"] == "mois_localdata_source_sync"
    assert data["ready"] is True
    assert data["latest_run"]["run_id"] == "mois-source-run-1"
    assert data["max_age_hours"] == 7
    assert data["age_hours"] < 1
    assert data["disabled_reason"] is None


@pytest.mark.unit
def test_mois_source_sync_precheck_transport_failure_is_problem_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("dagster down")

    monkeypatch.setattr(dagster_mod, "post_graphql", _raise_post_graphql)

    response = client.get("/v1/ops/pipeline/prechecks/mois-source-sync")

    assert response.status_code == 503
    assert response.json()["code"] == "DAGSTER_UNAVAILABLE"


@pytest.mark.unit
def test_schedules_merges_overrides_and_returns_sensors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == pipeline_mod._PIPELINE_SCHEDULES_QUERY
        return _SCHEDULES_GRAPHQL_PAYLOAD

    async def _overrides(_session: Any) -> dict[str, str]:
        return {"feature_weather_kma_short_forecast_hourly_schedule": "40 * * * *"}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "schedule_overrides", _overrides)

    response = client.get("/v1/ops/pipeline/schedules")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    schedule = data["schedules"][0]
    assert schedule["name"] == "feature_weather_kma_short_forecast_hourly_schedule"
    assert schedule["override_cron_schedule"] == "40 * * * *"
    assert schedule["default_cron_schedule"] == "20 * * * *"
    assert schedule["effective_cron_schedule"] == "20 * * * *"
    assert schedule["override_saved"] is True
    assert schedule["override_effective"] is False
    assert schedule["can_run_now"] is True
    assert schedule["disabled_reason"] is None
    assert {sensor["name"] for sensor in data["sensors"]} == {
        "feature_update_request_queue_sensor",
        "feature_update_request_failure_sensor",
    }


@pytest.mark.unit
def test_patch_schedule_upserts_override(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
) -> None:
    upserts: list[dict[str, Any]] = []

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_RELOAD_LOCATION_MUTATION
        return {
            "data": {
                "reloadRepositoryLocation": {
                    "__typename": "WorkspaceLocationEntry",
                    "id": "loc-1",
                    "name": "kortravelmap.dagster.definitions",
                    "loadStatus": "LOADED",
                    "locationOrLoadError": {
                        "__typename": "RepositoryLocation",
                        "name": "kortravelmap.dagster.definitions",
                    },
                }
            }
        }

    async def _upsert(_session: Any, **kwargs: Any) -> None:
        upserts.append(kwargs)

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "upsert_schedule_override", _upsert)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={
            "cron_schedule": "40 * * * *",
            "reason": "휴가철 증차",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "update"
    assert data["cron_schedule"] == "40 * * * *"
    assert data["save_status"] == "saved"
    assert data["reload_status"] == "succeeded"
    assert data["effective_status"] == "pending_verification"
    assert upserts == [
        {
            "schedule_name": "feature_weather_kma_short_forecast_hourly_schedule",
            "cron_schedule": "40 * * * *",
            "actor": "local-dev",
            "reason": "휴가철 증차",
        }
    ]
    assert session.schedule_audit_events == [
        {
            "schedule_name": "feature_weather_kma_short_forecast_hourly_schedule",
            "command": "update",
            "actor": "local-dev",
            "reason": "휴가철 증차",
            "phase": "requested",
            "details": {"cron_schedule": "40 * * * *"},
        },
        {
            "schedule_name": "feature_weather_kma_short_forecast_hourly_schedule",
            "command": "update",
            "actor": "local-dev",
            "reason": "휴가철 증차",
            "phase": "succeeded",
        },
    ]


@pytest.mark.unit
def test_patch_schedule_null_cron_clears_override(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
) -> None:
    deletes: list[str] = []

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        return {
            "data": {
                "reloadRepositoryLocation": {
                    "__typename": "WorkspaceLocationEntry",
                    "id": "loc-1",
                    "name": "kortravelmap.dagster.definitions",
                    "loadStatus": "LOADED",
                    "locationOrLoadError": {
                        "__typename": "RepositoryLocation",
                        "name": "kortravelmap.dagster.definitions",
                    },
                }
            }
        }

    async def _delete(_session: Any, *, schedule_name: str) -> None:
        deletes.append(schedule_name)

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "delete_schedule_override", _delete)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={
            "cron_schedule": None,
            "reason": "기본 주기 복귀",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "clear_override"
    assert deletes == ["feature_weather_kma_short_forecast_hourly_schedule"]
    assert data["save_status"] == "cleared"
    assert session.schedule_audit_events[-1] == {
        "schedule_name": "feature_weather_kma_short_forecast_hourly_schedule",
        "command": "default",
        "actor": "local-dev",
        "reason": "기본 주기 복귀",
        "phase": "succeeded",
    }


@pytest.mark.unit
def test_patch_schedule_clear_override_failure_uses_canonical_command_name(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_RELOAD_LOCATION_MUTATION
        return {
            "data": {
                "reloadRepositoryLocation": {
                    "__typename": "PythonError",
                    "message": "reload failed",
                    "stack": ["trace"],
                    "className": "DagsterReloadError",
                }
            }
        }

    async def _delete(_session: Any, *, schedule_name: str) -> None:
        assert schedule_name == "feature_weather_kma_short_forecast_hourly_schedule"

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "delete_schedule_override", _delete)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={"cron_schedule": None, "reason": "clear partial"},
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["code"] == "DAGSTER_SCHEDULE_COMMAND_FAILED"
    assert problem["details"]["command"] == "clear_override"
    assert problem["details"]["save_status"] == "cleared"
    assert problem["details"]["reload_status"] == "failed"


@pytest.mark.unit
def test_patch_schedule_rejects_high_frequency_cron(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return _SCHEDULES_GRAPHQL_PAYLOAD

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={"cron_schedule": "*/5 * * * *"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INVALID_SCHEDULE_COMMAND"


@pytest.mark.unit
def test_patch_schedule_rejects_client_owned_actor(client: TestClient) -> None:
    response = client.patch(
        "/v1/ops/pipeline/schedules/some_schedule",
        json={"cron_schedule": "0 * * * *", "operator": "spoofed"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_schedule_storage_failure_stops_before_remote_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graphql_calls = 0

    async def _storage_unavailable(_session: Any) -> dict[str, str]:
        raise dagster_schedule.DagsterScheduleStorageUnavailable("db unavailable")

    async def _unexpected_graphql(**_kwargs: Any) -> dict[str, Any]:
        nonlocal graphql_calls
        graphql_calls += 1
        raise AssertionError("storage failure 뒤 remote mutation을 호출하면 안 됩니다.")

    monkeypatch.setattr(dagster_schedule, "schedule_overrides", _storage_unavailable)
    monkeypatch.setattr(dagster_mod, "post_graphql", _unexpected_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/some_schedule/commands",
        json={"command": "start"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DAGSTER_SCHEDULE_STORAGE_UNAVAILABLE"
    assert graphql_calls == 0


@pytest.mark.unit
def test_patch_schedule_reload_transport_failure_reports_saved_partial_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_RELOAD_LOCATION_MUTATION
        raise httpx.ConnectError("dagster reload transport down")

    async def _upsert(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "upsert_schedule_override", _upsert)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={"cron_schedule": "40 * * * *", "reason": "partial result"},
    )

    assert response.status_code == 503
    problem = response.json()
    assert problem["code"] == "DAGSTER_SCHEDULE_UNAVAILABLE"
    assert problem["details"]["save_status"] == "saved"
    assert problem["details"]["reload_status"] == "failed"
    assert problem["details"]["effective_status"] == "mismatch"


@pytest.mark.unit
def test_patch_schedule_reload_location_load_error_is_problem_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_RELOAD_LOCATION_MUTATION
        return {
            "data": {
                "reloadRepositoryLocation": {
                    "__typename": "WorkspaceLocationEntry",
                    "id": "loc-1",
                    "name": "kortravelmap.dagster.definitions",
                    "loadStatus": "LOADED",
                    "locationOrLoadError": {
                        "__typename": "PythonError",
                        "message": "schedule override DB unavailable",
                        "stack": ["trace"],
                        "className": "DagsterUserCodeLoadError",
                    },
                }
            }
        }

    async def _upsert(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "upsert_schedule_override", _upsert)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={"cron_schedule": "40 * * * *", "reason": "load failure"},
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["code"] == "DAGSTER_SCHEDULE_COMMAND_FAILED"
    assert problem["details"]["save_status"] == "saved"
    assert problem["details"]["reload_status"] == "failed"
    assert problem["details"]["outcome_certainty"] == "confirmed"
    assert "DagsterUserCodeLoadError" in problem["detail"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "reload_result",
    [
        None,
        [],
        {},
        {"__typename": ""},
        {"__typename": "FutureReloadResult"},
        {
            "__typename": "WorkspaceLocationEntry",
            "locationOrLoadError": {
                "__typename": "RepositoryLocation",
                "name": "kortravelmap.dagster.definitions",
            },
        },
        {
            "__typename": "WorkspaceLocationEntry",
            "loadStatus": "   ",
            "locationOrLoadError": {
                "__typename": "RepositoryLocation",
                "name": "kortravelmap.dagster.definitions",
            },
        },
        {
            "__typename": "WorkspaceLocationEntry",
            "loadStatus": "LOADED",
            "locationOrLoadError": None,
        },
        {
            "__typename": "WorkspaceLocationEntry",
            "loadStatus": "LOADED",
            "locationOrLoadError": {"__typename": "FutureLocation"},
        },
        {
            "__typename": "WorkspaceLocationEntry",
            "loadStatus": "LOADED",
            "locationOrLoadError": {
                "__typename": "RepositoryLocation",
                "name": " ",
            },
        },
    ],
    ids=[
        "null-union",
        "non-object-union",
        "empty-union",
        "blank-typename",
        "unknown-union",
        "missing-load-status",
        "blank-load-status",
        "null-location",
        "unknown-location",
        "blank-location-name",
    ],
)
def test_patch_schedule_unknown_reload_shape_is_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reload_result: object,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_RELOAD_LOCATION_MUTATION
        return {"data": {"reloadRepositoryLocation": reload_result}}

    async def _upsert(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "upsert_schedule_override", _upsert)

    response = client.patch(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
        json={"cron_schedule": "40 * * * *", "reason": "reload shape"},
    )

    assert response.status_code == 502
    assert response.json()["details"]["outcome_certainty"] == "uncertain"


@pytest.mark.unit
def test_schedule_command_requires_known_enum(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/schedules/some_schedule/commands",
        json={"command": "default"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_schedule_command_rejects_client_owned_actor(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/schedules/some_schedule/commands",
        json={"command": "run", "operator": "spoofed"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.unit
def test_schedule_command_start_mutates_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_START_SCHEDULE_MUTATION
        return {
            "data": {
                "startSchedule": {
                    "__typename": "ScheduleStateResult",
                    "scheduleState": {
                        "id": "state-1::selector",
                        "selectorId": "sel-1",
                        "status": "RUNNING",
                        "repositoryName": "__repository__",
                        "repositoryLocationName": ("kortravelmap.dagster.definitions"),
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "start", "reason": "운영 재개"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "start"
    assert data["schedule_status"] == "RUNNING"
    assert session.schedule_audit_events[0]["actor"] == "local-dev"
    assert session.schedule_audit_events[0]["reason"] == "운영 재개"


@pytest.mark.unit
def test_schedule_graphql_error_is_problem_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        return {
            "data": {
                "startSchedule": {
                    "__typename": "UnauthorizedError",
                    "message": "dagster denied",
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "start", "reason": "재개"},
    )

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_SCHEDULE_COMMAND_FAILED"
    assert response.json()["details"]["outcome_certainty"] == "confirmed"
    assert response.json()["details"]["audit_status"] == "recorded"
    assert session.schedule_audit_events[-1]["phase"] == "failed"


@pytest.mark.unit
def test_schedule_transport_error_is_problem_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("dagster down")

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/some_schedule/commands",
        json={"command": "start"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_SCHEDULE_UNAVAILABLE"


@pytest.mark.unit
def test_schedule_mutation_response_loss_is_marked_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_START_SCHEDULE_MUTATION
        raise httpx.ReadTimeout("response lost after mutation POST")

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "start"},
    )

    assert response.status_code == 503
    problem = response.json()
    assert problem["code"] == "DAGSTER_SCHEDULE_UNAVAILABLE"
    assert problem["details"]["outcome_certainty"] == "uncertain"
    assert problem["details"]["audit_command_id"] == ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.mark.unit
def test_schedule_uncertain_claim_resolution_uses_authenticated_actor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _resolve(_session: Any, **kwargs: Any) -> DagsterScheduleClaimResolution:
        captured.update(kwargs)
        return DagsterScheduleClaimResolution(
            resolution_id=42,
            command_id=kwargs["command_id"],
            schedule_name=kwargs["schedule_name"],
            resolution=kwargs["resolution"],
            actor=kwargs["actor"],
            reason=kwargs["reason"],
            resolved_at=_NOW,
            replayed=False,
        )

    monkeypatch.setattr(dagster_schedule, "resolve_schedule_active_claim", _resolve)
    command_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    response = client.post(
        f"/v1/ops/pipeline/schedules/some_schedule/claims/{command_id}/resolve",
        json={
            "resolution": "confirmed_not_applied",
            "reason": "Dagster 실행 목록에서 미반영 확인",
            "actor": "spoofed",
        },
    )
    assert response.status_code == 422

    response = client.post(
        f"/v1/ops/pipeline/schedules/some_schedule/claims/{command_id}/resolve",
        json={
            "resolution": "confirmed_not_applied",
            "reason": "Dagster 실행 목록에서 미반영 확인",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["resolution_id"] == 42
    assert response.json()["data"]["replayed"] is False
    assert captured == {
        "schedule_name": "some_schedule",
        "command_id": UUID(command_id),
        "resolution": "confirmed_not_applied",
        "actor": "local-dev",
        "reason": "Dagster 실행 목록에서 미반영 확인",
    }


@pytest.mark.unit
def test_schedule_claim_resolution_replay_is_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _resolve(_session: Any, **kwargs: Any) -> DagsterScheduleClaimResolution:
        return DagsterScheduleClaimResolution(
            resolution_id=43,
            command_id=kwargs["command_id"],
            schedule_name=kwargs["schedule_name"],
            resolution=kwargs["resolution"],
            actor="first-operator",
            reason=kwargs["reason"].strip(),
            resolved_at=_NOW,
            replayed=True,
        )

    monkeypatch.setattr(dagster_schedule, "resolve_schedule_active_claim", _resolve)
    command_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

    response = client.post(
        f"/v1/ops/pipeline/schedules/some_schedule/claims/{command_id}/resolve",
        json={
            "resolution": "confirmed_applied",
            "reason": " Dagster schedule 상태에서 반영 확인 ",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "resolution_id": 43,
        "command_id": command_id,
        "schedule_name": "some_schedule",
        "resolution": "confirmed_applied",
        "actor": "first-operator",
        "reason": "Dagster schedule 상태에서 반영 확인",
        "resolved_at": _NOW.isoformat().replace("+00:00", "Z"),
        "replayed": True,
    }


@pytest.mark.unit
def test_schedule_claim_resolution_not_found_is_problem(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_found(*_args: Any, **_kwargs: Any) -> None:
        raise dagster_schedule.DagsterScheduleClaimNotFound("claim 없음")

    monkeypatch.setattr(
        dagster_schedule,
        "resolve_schedule_active_claim",
        _not_found,
    )
    command_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    response = client.post(
        f"/v1/ops/pipeline/schedules/some_schedule/claims/{command_id}/resolve",
        json={
            "resolution": "confirmed_applied",
            "reason": "Dagster schedule 상태에서 반영 확인",
        },
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DAGSTER_SCHEDULE_CLAIM_NOT_FOUND"


@pytest.mark.unit
def test_schedule_mutation_rejects_malformed_success_as_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_START_SCHEDULE_MUTATION
        return {
            "data": {
                "startSchedule": {
                    "__typename": "ScheduleStateResult",
                    "scheduleState": {},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "start"},
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["details"]["outcome_certainty"] == "uncertain"
    assert "scheduleState.status" in problem["detail"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation_result",
    [
        None,
        [],
        {},
        {"__typename": ""},
        {"__typename": "FutureScheduleMutationResult"},
        {
            "__typename": "ScheduleStateResult",
            "scheduleState": {"status": "   "},
        },
        {
            "__typename": "ScheduleStateResult",
            "scheduleState": [],
        },
    ],
    ids=[
        "null-union",
        "non-object-union",
        "empty-union",
        "blank-typename",
        "unknown-union",
        "blank-status",
        "non-object-state",
    ],
)
def test_schedule_mutation_unknown_union_is_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mutation_result: object,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_START_SCHEDULE_MUTATION
        return {"data": {"startSchedule": mutation_result}}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "start"},
    )

    assert response.status_code == 502
    assert response.json()["details"]["outcome_certainty"] == "uncertain"


@pytest.mark.unit
def test_schedule_run_rejects_success_without_run_id_as_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_LAUNCH_RUN_MUTATION
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"status": "QUEUED"},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "run"},
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["details"]["outcome_certainty"] == "uncertain"
    assert "run.runId" in problem["detail"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "launch_result",
    [
        None,
        [],
        {},
        {"__typename": ""},
        {"__typename": "FutureLaunchResult"},
        {
            "__typename": "LaunchRunSuccess",
            "run": {"runId": "   ", "status": "QUEUED"},
        },
        {"__typename": "LaunchRunSuccess", "run": []},
    ],
    ids=[
        "null-union",
        "non-object-union",
        "empty-union",
        "blank-typename",
        "unknown-union",
        "blank-run-id",
        "non-object-run",
    ],
)
def test_schedule_run_unknown_union_is_uncertain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    launch_result: object,
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_LAUNCH_RUN_MUTATION
        return {"data": {"launchRun": launch_result}}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "run"},
    )

    assert response.status_code == 502
    assert response.json()["details"]["outcome_certainty"] == "uncertain"


@pytest.mark.unit
def test_schedule_command_run_launches_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches: list[dict[str, Any]] = []

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _SCHEDULES_GRAPHQL_PAYLOAD
        assert kwargs["query"] == dagster_schedule._DAGSTER_LAUNCH_RUN_MUTATION
        launches.append(kwargs["variables"])
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {
                        "runId": "run-99",
                        "status": "QUEUED",
                        "jobName": "feature_weather_kma_short_forecast_job",
                        "startTime": None,
                        "endTime": None,
                        "updateTime": None,
                        "tags": [],
                    },
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule/commands",
        json={"command": "run", "reason": "재적재"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "run"
    assert data["run_id"] == "run-99"
    assert data["run_status"] == "QUEUED"
    assert len(launches) == 1
    execution_params = launches[0]["executionParams"]
    tags = {tag["key"]: tag["value"] for tag in execution_params["executionMetadata"]["tags"]}
    assert tags[FEATURE_OPERATION_TRIGGER_TAG] == "manual"
    assert tags[ADMIN_MANUAL_TRIGGER_TAG] == "admin-ui"
    assert tags["kor_travel_map.operator"] == "local-dev"
    assert tags["kor_travel_map.reason"] == "재적재"
    assert "kor_travel_map.trigger" not in tags
    identity = parse_feature_operation_identity_tags(tags)
    assert identity is not None
    assert identity.job_name == "feature_weather_kma_short_forecast_job"
    assert (
        validate_feature_operation_identity(
            job_name=identity.job_name,
            selected_asset_keys=identity.asset_keys,
            run_config=execution_params["runConfigData"],
            tags=tags,
        )
        == identity
    )


@pytest.mark.unit
def test_schedule_command_knps_manual_launch_persists_resolved_config_and_tags(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_name = "feature_place_knps_points_monthly_schedule"
    job_name = "feature_place_knps_points_job"
    launches: list[dict[str, Any]] = []
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY",
        "knps_restrooms",
    )

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _single_schedule_payload(schedule_name, job_name)
        launches.append(kwargs["variables"])
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"runId": "run-knps", "status": "QUEUED"},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        f"/v1/ops/pipeline/schedules/{schedule_name}/commands",
        json={"command": "run", "reason": "수동 재적재"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert len(launches) == 1
    execution_params = launches[0]["executionParams"]
    run_config = execution_params["runConfigData"]
    assert run_config == {
        "resources": {
            "knps_point_dataset_key": {"config": {"dataset_key": "knps_restrooms"}},
            "knps_point_records": {"config": {"dataset_key": "knps_restrooms"}},
        }
    }
    tags = {tag["key"]: tag["value"] for tag in execution_params["executionMetadata"]["tags"]}
    identity = parse_feature_operation_identity_tags(tags)
    assert identity is not None
    assert identity.pairs[0].dataset_key == "knps_restrooms"
    assert (
        validate_feature_operation_identity(
            job_name=job_name,
            selected_asset_keys=identity.asset_keys,
            run_config=run_config,
            tags=tags,
        )
        == identity
    )


@pytest.mark.unit
@pytest.mark.parametrize("dataset_key", tuple(DATAGOKR_FILEDATA_DATASETS))
def test_schedule_command_filedata_manual_launch_persists_exact_config_and_tags(
    dataset_key: str,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_name = f"feature_place_{dataset_key}_monthly_schedule"
    job_name = f"feature_place_{dataset_key}_job"
    launches: list[dict[str, Any]] = []

    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        if kwargs["query"] == dagster_schedule._DAGSTER_SCHEDULES_QUERY:
            return _single_schedule_payload(schedule_name, job_name)
        assert kwargs["query"] == dagster_schedule._DAGSTER_LAUNCH_RUN_MUTATION
        launches.append(kwargs["variables"])
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"runId": "run-filedata", "status": "QUEUED"},
                }
            }
        }

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post(
        f"/v1/ops/pipeline/schedules/{schedule_name}/commands",
        json={"command": "run"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert len(launches) == 1
    execution_params = launches[0]["executionParams"]
    run_config = execution_params["runConfigData"]
    assert run_config == {
        "resources": {
            "datagokr_file_data_dataset_key": {"config": {"dataset_key": dataset_key}},
            "datagokr_file_data_records": {"config": {"dataset_key": dataset_key}},
        }
    }
    tags = {tag["key"]: tag["value"] for tag in execution_params["executionMetadata"]["tags"]}
    assert tags[FEATURE_OPERATION_TRIGGER_TAG] == "manual"
    assert tags[ADMIN_MANUAL_TRIGGER_TAG] == "admin-ui"
    identity = parse_feature_operation_identity_tags(tags)
    assert identity is not None
    assert identity.job_name == job_name
    assert identity.pairs[0].dataset_key == dataset_key
    assert (
        validate_feature_operation_identity(
            job_name=job_name,
            selected_asset_keys=identity.asset_keys,
            run_config=run_config,
            tags=tags,
        )
        == identity
    )


@pytest.mark.unit
def test_preview_request_returns_preview(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPreview:
        return FeatureUpdateRequestPreview(
            scope_type="provider_dataset",
            scope={
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            providers=(),
            dataset_keys=(),
            update_policy={},
            run_mode="queued",
            priority=50,
            matched_scope={"feature_count": 3},
        )

    monkeypatch.setattr(fur_mod, "preview_feature_update_request_repo", _enqueue)

    response = client.post(
        "/v1/ops/pipeline/requests/preview",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["result_kind"] == "preview"
    assert {
        "request_id",
        "job_id",
        "created_at",
        "generation",
        "status_url",
    }.isdisjoint(body["data"])
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_request_rejects_dry_run_flag(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_request_requires_uuid_idempotency_key(client: TestClient) -> None:
    del client.headers["Idempotency-Key"]

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            }
        },
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_create_request_idempotency_replays_and_rejects_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping: FeatureUpdateRequestIdempotency | None = None
    terminal = _update_request(status="done", operator="local-dev", reason="same")

    async def _enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        return _update_request(operator="local-dev", reason="same")

    async def _get_mapping(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequestIdempotency | None:
        return mapping

    async def _insert_mapping(
        *_args: Any,
        **kwargs: Any,
    ) -> FeatureUpdateRequestIdempotency:
        nonlocal mapping
        mapping = FeatureUpdateRequestIdempotency(
            idempotency_key=kwargs["idempotency_key"],
            fingerprint_version=1,
            request_fingerprint=kwargs["request_fingerprint"],
            request_id=kwargs["request_id"],
            actor=kwargs["actor"],
            reused_active_request=kwargs["reused_active_request"],
            created_at=_NOW,
        )
        return mapping

    async def _get_request(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        return terminal

    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _enqueue)
    monkeypatch.setattr(fur_mod, "get_feature_update_request_idempotency", _get_mapping)
    monkeypatch.setattr(fur_mod, "create_feature_update_request_idempotency", _insert_mapping)
    monkeypatch.setattr(fur_mod, "get_update_request", _get_request)

    body = {
        "scope": {
            "type": "provider_dataset",
            "provider": MOIS_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_BULK,
        },
        "reason": "same",
    }
    first = client.post("/v1/ops/pipeline/requests", json=body)
    replay = client.post("/v1/ops/pipeline/requests", json=body)
    mismatch = client.post(
        "/v1/ops/pipeline/requests",
        json={**body, "reason": "different"},
    )

    assert first.status_code == 201
    assert first.json()["idempotent_replay"] is False
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["data"]["status"] == "done"
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "FEATURE_UPDATE_IDEMPOTENCY_CONFLICT"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "update_policy": {"surprise": True},
            },
        ),
        (
            "/v1/ops/pipeline/requests/preview",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "update_policy": {"include_inactive": "false"},
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {
                    "type": "cache_target_keys",
                    "external_system": "pinvi",
                    "target_keys": ["poi:e\u0301"],
                }
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {
                    "type": "cache_target_keys",
                    "external_system": " pinvi ",
                    "target_keys": ["poi-1"],
                }
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {
                    "type": "cache_target_keys",
                    "external_system": "pinvi",
                    "target_keys": ["x" * 513],
                }
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {
                    "type": "center_radius",
                    "center": {"lon": "127.0", "lat": 37.0},
                    "radius_km": 5,
                }
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "priority": "75",
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "reason": "   ",
            },
        ),
        (
            "/v1/ops/pipeline/requests/preview",
            {
                "scope": {
                    "type": "cache_target_keys",
                    "external_system": "pinvi",
                    "target_keys": ["poi-1", "poi-1"],
                }
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {
                    "type": "provider_dataset",
                    "provider": MOIS_PROVIDER_NAME,
                    "dataset_key": DATASET_KEY_BULK,
                },
                "providers": [MOIS_PROVIDER_NAME],
                "dataset_keys": [DATASET_KEY_BULK],
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "providers": [f"python-provider-{index}-api" for index in range(33)],
            },
        ),
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": ["feature-1"]},
                "providers": [MOIS_PROVIDER_NAME, MOIS_PROVIDER_NAME],
            },
        ),
    ],
)
def test_feature_update_contract_rejects_invalid_runtime_payloads(
    client: TestClient,
    session: _FakeSession,
    path: str,
    body: dict[str, Any],
) -> None:
    response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    ["/v1/ops/pipeline/requests", "/v1/ops/pipeline/requests/preview"],
)
def test_feature_ids_scope_rejects_unresolved_uuid_ref(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """T-VN-32C 회귀 (S1) — scope.feature_ids의 미해석 UUID 참조는 422 fail-close.

    해석 없이 통과하면 matched_feature_count=0 요청이 영속 생성되고 job이 빈
    scope로 성공 종료한다(조용한 no-op). 미해석 참조는 등록/미리보기 양쪽에서
    FEATURE_REF_UNRESOLVED로 거부돼야 한다.
    """
    from kortravelmap.infra import feature_identity

    async def _resolve_none(
        _session: Any, refs: Any
    ) -> dict[str, feature_identity.FeatureIdentity]:
        for ref in refs:
            feature_identity.validate_feature_ref(ref)
        return {}

    monkeypatch.setattr(
        feature_identity, "resolve_feature_identities_bulk", _resolve_none
    )

    response = client.post(
        path,
        json={
            "scope": {
                "type": "feature_ids",
                "feature_ids": ["0f9d3c6e-5a41-4b2e-9c77-2b8a1d4e6f30"],
            }
        },
    )

    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "FEATURE_REF_UNRESOLVED"
    assert problem["details"]["unresolved"] == [
        "0f9d3c6e-5a41-4b2e-9c77-2b8a1d4e6f30"
    ]
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_request_persists_with_new_status_url(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["operator"] == "local-dev"
        assert kwargs["reason"] == "stale 복구"
        return _update_request()

    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "reason": "stale 복구",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["status_url"] == (
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )
    assert body["data"]["generation"] == 1
    assert session.begin_count == 1


@pytest.mark.unit
def test_create_request_enforces_mois_precheck_at_canonical_write_boundary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guarded_pairs: list[frozenset[tuple[str, str]]] = []

    async def _blocked(
        resolved_pairs: frozenset[tuple[str, str]],
        **_kwargs: Any,
    ) -> None:
        guarded_pairs.append(resolved_pairs)
        raise mois_source_precheck.MoisSourceSyncRequired(
            mois_source_precheck.MoisSourceSyncPrecheck(
                job_name=mois_source_precheck.MOIS_SOURCE_SYNC_JOB_NAME,
                ready=False,
                checked_at=_NOW,
                max_age_hours=7,
                age_hours=None,
                latest_run=None,
                disabled_reason="MOIS source sync 실행 이력이 없습니다.",
            )
        )

    async def _unexpected_enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("precheck 실패 뒤 request를 enqueue하면 안 됩니다")

    monkeypatch.setattr(
        mois_source_precheck,
        "ensure_mois_source_sync_for_plan",
        _blocked,
    )
    monkeypatch.setattr(
        fur_mod,
        "enqueue_feature_update_request",
        _unexpected_enqueue,
    )

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            }
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "MOIS_SOURCE_SYNC_REQUIRED"
    assert guarded_pairs == [frozenset({(MOIS_PROVIDER_NAME, DATASET_KEY_BULK)})]


@pytest.mark.unit
def test_create_request_rejects_non_refreshable_pair(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": "not-a-provider",
                "dataset_key": "nope",
            }
        },
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_create_request_rejects_sync_scope_for_dataset_wide_catalog_entry(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
                "sync_scope": "target_grids",
            }
        },
    )

    assert response.status_code == 422
    assert "sync_scope 선택을 지원하지 않습니다" in response.json()["detail"]


@pytest.mark.unit
def test_create_request_reuses_same_active_effective_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _update_request(operator="local-dev", reason="same")

    async def _active(*_args: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["sync_scope"] == "dataset_wide"
        return existing

    async def _unexpected_enqueue(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise AssertionError("same active request must be reused")

    monkeypatch.setattr(fur_mod, "find_active_provider_dataset_request", _active)
    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _unexpected_enqueue)

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "reason": "same",
        },
    )

    assert response.status_code == 200
    assert response.json()["reused_active_request"] is True
    assert response.json()["data"]["request_id"] == existing.request_id


@pytest.mark.unit
def test_create_request_rejects_different_plan_on_active_effective_scope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _update_request(operator="local-dev", reason="same", priority=50)

    async def _active(*_args: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        return existing

    monkeypatch.setattr(fur_mod, "find_active_provider_dataset_request", _active)

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "priority": 51,
            "reason": "same",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ACTIVE_SCOPE_CONFLICT"
    assert response.json()["details"]["request_id"] == existing.request_id


@pytest.mark.unit
def test_create_request_scope_lock_busy_maps_to_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _enqueue(_session: Any, **_kwargs: Any) -> FeatureUpdateRequest:
        raise FeatureUpdateLockBusy(lock_key="scope-key")

    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/ops/pipeline/requests",
        json={
            "scope": {
                "type": "provider_dataset",
                "provider": MOIS_PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
            },
            "run_mode": "now",
        },
    )

    assert response.status_code == 409
    assert response.headers["Retry-After"] == "15"
    assert response.json()["code"] == "LOCK_BUSY"


@pytest.mark.unit
def test_run_now_dispatches_same_canonical_request(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get_request(_session: Any, request_id: str) -> FeatureUpdateRequest | None:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request()

    async def _dispatch(_session: Any, request_id: str) -> FeatureUpdateRequest:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request(
            dispatch_requested_at=datetime(2026, 7, 14, 9, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(fur_mod, "get_update_request", _get_request)
    monkeypatch.setattr(fur_mod, "request_feature_update_dispatch", _dispatch)

    response = client.post(
        "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["request_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["data"]["job_id"] == _update_request().job_id
    assert body["data"]["dispatch_requested_at"] is not None
    assert body["data"]["generation"] == 1
    assert body["data"]["status_url"] == (
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )
    assert session.begin_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/v1/ops/pipeline/requests",
            {
                "scope": {"type": "feature_ids", "feature_ids": []},
                "operator": "spoofed",
            },
        ),
        (
            "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
            {"operator": "spoofed"},
        ),
    ],
)
def test_pipeline_request_mutations_reject_operator_override(
    client: TestClient,
    path: str,
    body: dict[str, Any],
) -> None:
    response = client.post(path, json=body)

    assert response.status_code == 422


@pytest.mark.unit
def test_run_now_returns_running_request_idempotently(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return _update_request(status="running")

    monkeypatch.setattr(fur_mod, "get_update_request", _get_request)

    response = client.post(
        "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "running"


@pytest.mark.unit
def test_run_now_dispatch_race_rejects_cancellation_requested(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = iter(
        (
            _update_request(status="queued"),
            replace(
                _update_request(status="running"),
                cancellation_id="77777777-7777-4777-8777-777777777777",
            ),
        )
    )

    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return next(requests)

    async def _dispatch(_session: Any, request_id: str) -> FeatureUpdateRequest:
        raise FeatureUpdateDispatchConflict(
            request_id=request_id,
            current_status="running",
        )

    monkeypatch.setattr(fur_mod, "get_update_request", _get_request)
    monkeypatch.setattr(fur_mod, "request_feature_update_dispatch", _dispatch)

    response = client.post(
        "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
        json={},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "REQUEST_NOT_DISPATCHABLE"
    assert response.json()["details"]["status"] == "cancellation_requested"


@pytest.mark.unit
def test_run_now_missing_request_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return None

    monkeypatch.setattr(fur_mod, "get_update_request", _get_request)

    response = client.post(
        "/v1/ops/pipeline/requests/aaaaaaaa-0000-4000-8000-000000000000/run-now",
        json={},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_run_now_non_uuid_request_id_is_422(client: TestClient) -> None:
    response = client.post("/v1/ops/pipeline/requests/not-a-uuid/run-now", json={})

    assert response.status_code == 422


@pytest.mark.unit
def test_pipeline_nux_seen_route_is_removed(client: TestClient) -> None:
    response = client.post("/v1/ops/pipeline/nux-seen")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
