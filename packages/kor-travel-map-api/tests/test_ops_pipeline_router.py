"""``/v1/ops/pipeline/*`` 라우터 단위 테스트 (ADR-064 T-ADM-C3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJob,
    OpsImportJobEvent,
    OpsImportJobEventPage,
)
from kortravelmap.infra.pipeline_repo import (
    PipelineExecution,
    PipelineExecutionPage,
    PipelineProjectedJob,
    PipelineProviderDatasetIdentity,
    PipelineStatusCounts,
)
from kortravelmap.providers.mois import DATASET_KEY_BULK
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME

from kortravelmap.api import dagster_graphql as dagster_mod
from kortravelmap.api import dagster_query_service as dagster_query
from kortravelmap.api import dagster_schedule_service as dagster_schedule
from kortravelmap.api import feature_update_service as fur_mod
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import ops_pipeline as pipeline_mod
from kortravelmap.api.settings import ApiSettings

_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)

_PIPELINE_PATHS = [
    "/v1/ops/pipeline/overview",
    "/v1/ops/pipeline/executions",
    "/v1/ops/pipeline/executions/{kind}/{execution_id}",
    "/v1/ops/pipeline/executions/{kind}/{execution_id}/cancel",
    "/v1/ops/pipeline/events",
    "/v1/ops/pipeline/dagster-runs",
    "/v1/ops/pipeline/schedules",
    "/v1/ops/pipeline/schedules/{schedule_name}",
    "/v1/ops/pipeline/schedules/{schedule_name}/commands",
    "/v1/ops/pipeline/requests",
    "/v1/ops/pipeline/requests/{request_id}/run-now",
    "/v1/ops/pipeline/nux-seen",
]


class _FakeBegin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _FakeBegin:
        self.begin_count += 1
        return _FakeBegin()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            dagster_url="http://dagster.example:12302",
            dagster_allowed_hosts=["dagster.example"],
            dagster_request_timeout_seconds=1.0,
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _job(
    job_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    status: str = "running",
    payload: dict[str, Any] | None = None,
    dagster_run_id: str | None = "run-1",
) -> OpsImportJob:
    return OpsImportJob(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id=None,
        parent_job_id=None,
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
    )


def _update_request(
    request_id: str = "22222222-2222-2222-2222-222222222222",
    *,
    status: str = "queued",
) -> FeatureUpdateRequest:
    return FeatureUpdateRequest(
        request_id=request_id,
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
        status=status,
        dry_run=False,
        matched_scope={"feature_count": 1},
        job_id="11111111-1111-1111-1111-111111111111",
        dagster_run_id="run-1",
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
        updated_at=_NOW,
    )


def _event(
    event_id: str = "55555555-5555-5555-5555-555555555555",
) -> OpsImportJobEvent:
    return OpsImportJobEvent(
        event_id=event_id,
        job_id="11111111-1111-1111-1111-111111111111",
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BULK,
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
) -> PipelineExecution:
    return PipelineExecution(
        kind=kind,
        id=execution_id,
        status="running",
        created_at=_NOW,
        providers=(MOIS_PROVIDER_NAME,),
        dataset_keys=(DATASET_KEY_BULK,),
        provider_dataset=(
            None
            if kind == "import_job"
            else PipelineProviderDatasetIdentity(
                provider=MOIS_PROVIDER_NAME,
                dataset_key=DATASET_KEY_BULK,
                sync_scope="default",
            )
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
        requested_job_id=(None if kind == "import_job" else "11111111-1111-1111-1111-111111111111"),
        lineage_owner=None if kind == "import_job" else True,
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
            load_batch_id=None,
            parent_job_id=None,
            depth=0,
        ),
    )


def _counts() -> PipelineStatusCounts:
    return PipelineStatusCounts(
        import_jobs_by_status={"queued": 2, "running": 1, "failed": 3},
        update_requests_by_status={"queued": 4, "done": 7},
        failed_import_jobs_24h=3,
        failed_update_requests_24h=1,
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
                            "pipelineName": "kma_short_forecast_job",
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
    for path in _PIPELINE_PATHS:
        assert path in spec["paths"], path
    # kind는 enum 경로 파라미터다 (import_job|update_request).
    detail_params = spec["paths"]["/v1/ops/pipeline/executions/{kind}/{execution_id}"]["get"][
        "parameters"
    ]
    kind_param = next(p for p in detail_params if p["name"] == "kind")
    assert kind_param["schema"]["enum"] == ["import_job", "update_request"]
    # 갱신 요청 생성은 기존 6-type scope union 계약을 그대로 공유한다.
    request_schema = spec["components"]["schemas"]["FeatureUpdateRequestCreateRequest"]
    assert len(request_schema["properties"]["scope"]["oneOf"]) == 6
    # commands body는 4종 enum이다.
    command_schema = spec["components"]["schemas"]["PipelineScheduleCommandRequest"]
    assert command_schema["properties"]["command"]["enum"] == [
        "run",
        "start",
        "stop",
        "reset",
    ]


@pytest.mark.unit
def test_pipeline_routes_require_admin_frontend_when_secret_set(
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

    assert response.status_code == 403


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
    assert data["import_jobs_by_status"] == {"queued": 2, "running": 1, "failed": 3}
    assert data["active_import_jobs"] == 3
    assert data["active_update_requests"] == 4
    assert data["failed_import_jobs_24h"] == 3
    assert data["failed_update_requests_24h"] == 1
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
    assert data["import_jobs_by_status"] == {"queued": 2, "running": 1, "failed": 3}


@pytest.mark.unit
def test_executions_list_passes_filters_and_maps_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_list(_session: Any, **kwargs: Any) -> PipelineExecutionPage:
        captured.update(kwargs)
        return PipelineExecutionPage(
            items=(
                _execution(kind="import_job"),
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
            "created_from": "2026-07-01T00:00:00Z",
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    assert captured["kind"] == "import_job"
    assert captured["status"] == "running"
    assert captured["provider"] == MOIS_PROVIDER_NAME
    assert captured["dataset_key"] == DATASET_KEY_BULK
    assert captured["limit"] == 2
    body = response.json()
    assert body["meta"]["page"]["next_cursor"] == "cursor-next"
    items = body["data"]["items"]
    assert [item["kind"] for item in items] == ["import_job", "update_request"]
    assert items[0]["detail_url"] == (
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111"
    )
    assert items[0]["providers"] == [MOIS_PROVIDER_NAME]
    assert items[0]["linked_job_count"] == 1
    assert items[0]["projected_job"]["detail_url"] == (
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111"
    )
    assert items[1]["requested_job_id"] == ("11111111-1111-1111-1111-111111111111")
    assert items[1]["provider_dataset"] == {
        "provider": MOIS_PROVIDER_NAME,
        "dataset_key": DATASET_KEY_BULK,
        "sync_scope": "default",
    }
    assert items[1]["lineage_owner"] is True
    assert items[1]["dagster_run_id"] == "run-1"


@pytest.mark.unit
def test_executions_list_invalid_cursor_maps_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(_session: Any, **_kwargs: Any) -> PipelineExecutionPage:
        raise ValueError("invalid pipeline_executions cursor")

    monkeypatch.setattr(pipeline_mod, "list_pipeline_executions", _fake_list)

    response = client.get("/v1/ops/pipeline/executions?cursor=broken")

    assert response.status_code == 422


@pytest.mark.unit
def test_execution_detail_import_job_links_request_and_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_job(_session: Any, job_id: str) -> OpsImportJob | None:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        return _job()

    async def _get_request(_session: Any, request_id: str) -> FeatureUpdateRequest | None:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request()

    async def _events(
        _session: Any, job_id: str | None = None, **kwargs: Any
    ) -> OpsImportJobEventPage:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        assert kwargs["level"] == "error"
        return OpsImportJobEventPage(items=(_event(),), next_cursor="ev-cursor")

    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)

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

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "list_ops_import_job_events", _events)

    response = client.get(
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution"]["kind"] == "update_request"
    assert data["execution"]["provider"] == MOIS_PROVIDER_NAME
    assert data["import_job"]["status"] == "running"
    assert data["events_next_cursor"] is None


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
def test_cancel_import_job_running(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = iter(["running", "cancelled", "cancelled"])

    async def _get_job(_session: Any, _job_id: str) -> OpsImportJob:
        return _job(status=next(states))

    async def _cancel(_session: Any, job_id: str, **kwargs: Any) -> Any:
        assert job_id == "11111111-1111-1111-1111-111111111111"
        assert kwargs["error_message"] == "혼잡 시간대 회피"
        assert kwargs["operator"] == "tester"
        return object()

    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)
    monkeypatch.setattr(pipeline_mod, "cancel_import_job", _cancel)

    response = client.post(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
        json={"operator": "tester", "reason": "혼잡 시간대 회피"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    assert session.begin_count == 1


@pytest.mark.unit
def test_cancel_import_job_terminal_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_job(_session: Any, _job_id: str) -> OpsImportJob:
        return _job(status="done")

    monkeypatch.setattr(pipeline_mod, "get_ops_import_job", _get_job)

    response = client.post(
        "/v1/ops/pipeline/executions/import_job/11111111-1111-1111-1111-111111111111/cancel",
        json={},
    )

    assert response.status_code == 409


@pytest.mark.unit
def test_cancel_update_request_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _cancel(
        _session: Any, _request_id: str, **_kwargs: Any
    ) -> FeatureUpdateRequest | None:
        return None

    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return None

    monkeypatch.setattr(pipeline_mod, "cancel_update_request", _cancel)
    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)

    response = client.post(
        "/v1/ops/pipeline/executions/update_request/aaaaaaaa-0000-4000-8000-000000000000/cancel",
        json={},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_cancel_update_request_returns_record_and_logs_operator(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _cancel(_session: Any, request_id: str, **kwargs: Any) -> FeatureUpdateRequest:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        assert kwargs["error_message"] == "잘못된 scope"
        return _update_request(status="cancelled")

    monkeypatch.setattr(pipeline_mod, "cancel_update_request", _cancel)

    with caplog.at_level("INFO", logger=pipeline_mod.__name__):
        response = client.post(
            "/v1/ops/pipeline/executions/update_request/"
            "22222222-2222-2222-2222-222222222222/cancel",
            json={"operator": "tester", "reason": "잘못된 scope"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kind"] == "update_request"
    assert data["status"] == "cancelled"
    # 감사: 계약이 받은 operator/reason이 조용히 버려지지 않는다(구조화 로그).
    audit = [
        record.getMessage()
        for record in caplog.records
        if "feature update request 취소" in record.getMessage()
    ]
    assert len(audit) == 1
    assert "operator=tester" in audit[0]
    assert "잘못된 scope" in audit[0]


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
            "page_size": 10,
        },
    )

    assert response.status_code == 200
    assert captured["job_id"] is None
    assert captured["level"] == "error"
    assert captured["provider"] == MOIS_PROVIDER_NAME
    assert captured["dataset_key"] == DATASET_KEY_BULK
    assert captured["limit"] == 10
    body = response.json()
    assert body["meta"]["page"]["next_cursor"] == "ev-next"
    assert body["data"]["items"][0]["code"] == "provider.timeout"


@pytest.mark.unit
def test_events_non_uuid_job_id_is_422(client: TestClient) -> None:
    response = client.get("/v1/ops/pipeline/events", params={"job_id": "not-a-uuid"})

    assert response.status_code == 422


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
    assert {sensor["name"] for sensor in data["sensors"]} == {
        "feature_update_request_queue_sensor",
        "feature_update_request_failure_sensor",
    }


@pytest.mark.unit
def test_patch_schedule_upserts_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
            "operator": "tester",
            "reason": "휴가철 증차",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "update"
    assert data["cron_schedule"] == "40 * * * *"
    assert data["reloaded"] is True
    assert upserts == [
        {
            "schedule_name": "feature_weather_kma_short_forecast_hourly_schedule",
            "cron_schedule": "40 * * * *",
            "operator": "tester",
            "reason": "휴가철 증차",
        }
    ]


@pytest.mark.unit
def test_patch_schedule_null_cron_clears_override(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
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
                }
            }
        }

    async def _delete(_session: Any, *, schedule_name: str) -> None:
        deletes.append(schedule_name)

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)
    monkeypatch.setattr(dagster_schedule, "delete_schedule_override", _delete)

    with caplog.at_level("INFO", logger=pipeline_mod.__name__):
        response = client.patch(
            "/v1/ops/pipeline/schedules/feature_weather_kma_short_forecast_hourly_schedule",
            json={
                "cron_schedule": None,
                "operator": "tester",
                "reason": "기본 주기 복귀",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "clear_override"
    assert deletes == ["feature_weather_kma_short_forecast_hourly_schedule"]
    # 감사: override 삭제 경로도 operator/reason을 버리지 않는다(구조화 로그).
    audit = [
        record.getMessage()
        for record in caplog.records
        if "cron override 삭제" in record.getMessage()
    ]
    assert len(audit) == 1
    assert "operator=tester" in audit[0]
    assert "기본 주기 복귀" in audit[0]


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

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["errors"]


@pytest.mark.unit
def test_schedule_command_requires_known_enum(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/pipeline/schedules/some_schedule/commands",
        json={"command": "default"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_schedule_command_start_mutates_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
        json={"command": "start"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "start"
    assert data["schedule_status"] == "RUNNING"


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
                        "jobName": "kma_short_forecast_job",
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
        json={"command": "run", "operator": "tester", "reason": "재적재"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["command"] == "run"
    assert data["run_id"] == "run-99"
    assert data["run_status"] == "QUEUED"
    assert len(launches) == 1


@pytest.mark.unit
def test_create_request_dry_run_returns_preview(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequestPreview:
        assert kwargs["dry_run"] is True
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

    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _enqueue)

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

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["status"] == "dry_run"
    assert body["data"]["request_id"] is None
    assert session.begin_count == 0


@pytest.mark.unit
def test_create_request_persists_with_new_status_url(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["dry_run"] is False
        assert kwargs["operator"] == "tester"
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
            "operator": "tester",
            "reason": "stale 복구",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["status_url"] == (
        "/v1/ops/pipeline/executions/update_request/22222222-2222-2222-2222-222222222222"
    )
    assert session.begin_count == 1


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
def test_run_now_requeues_as_new_request(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get_request(_session: Any, request_id: str) -> FeatureUpdateRequest | None:
        assert request_id == "22222222-2222-2222-2222-222222222222"
        return _update_request()

    async def _enqueue(_session: Any, **kwargs: Any) -> FeatureUpdateRequest:
        assert kwargs["run_mode"] == "now"
        assert kwargs["reason"] == ("run-now from 22222222-2222-2222-2222-222222222222")
        return _update_request(request_id="33333333-3333-3333-3333-333333333333")

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)
    monkeypatch.setattr(fur_mod, "enqueue_feature_update_request", _enqueue)

    response = client.post(
        "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
        json={},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["request_id"] == "33333333-3333-3333-3333-333333333333"
    assert body["data"]["status_url"] == (
        "/v1/ops/pipeline/executions/update_request/33333333-3333-3333-3333-333333333333"
    )
    assert session.begin_count == 1


@pytest.mark.unit
def test_run_now_conflicts_for_running_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return _update_request(status="running")

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)

    response = client.post(
        "/v1/ops/pipeline/requests/22222222-2222-2222-2222-222222222222/run-now",
        json={},
    )

    assert response.status_code == 409


@pytest.mark.unit
def test_run_now_missing_request_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get_request(_session: Any, _request_id: str) -> FeatureUpdateRequest | None:
        return None

    monkeypatch.setattr(pipeline_mod, "get_update_request", _get_request)

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
def test_nux_seen_delegates_to_dagster_mutation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == dagster_query._DAGSTER_SET_NUX_SEEN_MUTATION
        return {"data": {"setNuxSeen": True}}

    monkeypatch.setattr(dagster_mod, "post_graphql", _fake_post_graphql)

    response = client.post("/v1/ops/pipeline/nux-seen")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["seen"] is True
