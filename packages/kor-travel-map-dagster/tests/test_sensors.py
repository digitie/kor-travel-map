"""feature update request Dagster sensor/job 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dagster import (
    DagsterInstance,
    RunRequest,
    SkipReason,
    build_run_status_sensor_context,
    build_sensor_context,
)
from kortravelmap.infra.feature_update_executor import (
    FeatureUpdateExecutionPlan,
    FeatureUpdateExecutionResult,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.infra.feature_update_repo import FeatureUpdateRequest
from kortravelmap.infra.scope_repo import (
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
)

from kortravelmap.dagster.sensors import (
    FEATURE_UPDATE_REQUEST_ID_TAG,
    FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS,
    feature_update_request_failure_sensor,
    feature_update_request_queue_sensor,
    feature_update_request_worker_job,
)

_NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


@dataclass
class _Client:
    request: FeatureUpdateRequest | None = None
    requests: tuple[FeatureUpdateRequest, ...] | None = None
    result: FeatureUpdateExecutionResult | None = None
    executed: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    peek_limits: list[int] = field(default_factory=list)
    fail_raises: Exception | None = None

    async def peek_next_update_request(self) -> FeatureUpdateRequest | None:
        return self.request

    async def peek_update_requests(
        self, *, limit: int = 10
    ) -> tuple[FeatureUpdateRequest, ...]:
        self.peek_limits.append(limit)
        if self.requests is not None:
            return self.requests[:limit]
        if self.request is None:
            return ()
        return (self.request,)

    async def execute_feature_update_request(
        self,
        request_id: str,
        *,
        runner: object,
        dagster_run_id: str | None = None,
        sigungu_resolver: object | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        self.executed.append(
            {
                "request_id": request_id,
                "runner": runner,
                "dagster_run_id": dagster_run_id,
                "sigungu_resolver": sigungu_resolver,
            }
        )
        return self.result

    async def fail_update_request(
        self,
        request_id: str,
        *,
        dagster_run_id: str | None = None,
        error_message: str | None = None,
    ) -> FeatureUpdateRequest | None:
        if self.fail_raises is not None:
            raise self.fail_raises
        self.failed.append(
            {
                "request_id": request_id,
                "dagster_run_id": dagster_run_id,
                "error_message": error_message,
            }
        )
        return self.request


def _request(
    *,
    request_id: str = "11111111-1111-4111-8111-111111111111",
    run_mode: str = "queued",
    state: str = "queued",
) -> FeatureUpdateRequest:
    return FeatureUpdateRequest(
        request_id=request_id,
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": "demo",
            "dataset_key": "places",
        },
        providers=("demo",),
        dataset_keys=("places",),
        update_policy={"prevent_provider_reactivation": True},
        run_mode=run_mode,
        priority=50,
        status=state,
        dry_run=False,
        matched_scope={},
        job_id="job-1",
        dagster_run_id=None,
        operator="codex",
        reason="unit",
        error_message=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
        updated_at=_NOW,
    )


def _execution_result(
    request: FeatureUpdateRequest,
    *,
    state: str = "done",
    error_message: str | None = None,
) -> FeatureUpdateExecutionResult:
    resolution = ScopeResolution(
        scope_type="provider_dataset",
        features=(FeatureScopeRow("feature-1"),),
        provider_datasets=(ProviderDatasetScope("demo", "places", 1),),
    )
    refresh_scope = ProviderDatasetRefreshScope(
        request_id=request.request_id,
        provider="demo",
        dataset_key="places",
        scope_type=request.scope_type,
        request_scope=request.scope,
        update_policy=request.update_policy,
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
    )
    plan = FeatureUpdateExecutionPlan(
        request=request,
        resolution=resolution,
        refresh_scopes=(refresh_scope,),
        skipped_scopes=(),
        matched_scope=resolution.matched_scope(),
    )
    results: tuple[ProviderDatasetRefreshResult, ...] = ()
    if state == "done":
        results = (
            ProviderDatasetRefreshResult(
                provider="demo",
                dataset_key="places",
                loaded_feature_ids=("feature-1",),
                loaded_count=1,
            ),
        )
    return FeatureUpdateExecutionResult(
        request=request,
        plan=plan,
        results=results,
        status=state,
        error_message=error_message,
    )


def test_queue_sensor_skips_empty_queue() -> None:
    client = _Client()
    context = build_sensor_context(resources={"kor_travel_map_client": client})

    result = feature_update_request_queue_sensor(context)

    assert isinstance(result, SkipReason)
    assert result.skip_message == "queued feature update request 없음"
    assert client.peek_limits == [FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS]


def test_queue_sensor_emits_request_run_config_and_tags() -> None:
    request = _request(run_mode="now")
    client = _Client(request)
    context = build_sensor_context(resources={"kor_travel_map_client": client})

    result = feature_update_request_queue_sensor(context)

    assert isinstance(result, RunRequest)
    assert result.run_key == f"feature-update:{request.request_id}"
    assert result.run_config == {
        "ops": {
            "execute_feature_update_request": {
                "config": {"request_id": request.request_id}
            }
        }
    }
    assert result.tags[FEATURE_UPDATE_REQUEST_ID_TAG] == request.request_id
    assert result.tags["kor_travel_map.feature_update_run_mode"] == "now"
    assert client.peek_limits == [FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS]


def test_queue_sensor_emits_batch_run_requests() -> None:
    first = _request(request_id="11111111-1111-4111-8111-111111111111")
    second = _request(request_id="22222222-2222-4222-8222-222222222222")
    client = _Client(requests=(first, second))
    context = build_sensor_context(resources={"kor_travel_map_client": client})

    result = feature_update_request_queue_sensor(context)

    assert isinstance(result, list)
    assert [item.run_key for item in result] == [
        f"feature-update:{first.request_id}",
        f"feature-update:{second.request_id}",
    ]
    assert [
        item.run_config["ops"]["execute_feature_update_request"]["config"][
            "request_id"
        ]
        for item in result
    ] == [first.request_id, second.request_id]
    assert client.peek_limits == [FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS]


def test_worker_job_executes_configured_request() -> None:
    request = _request()
    client = _Client(request=request, result=_execution_result(request))
    runner = object()

    result = feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {"request_id": request.request_id}
                }
            }
        },
        resources={"kor_travel_map_client": client, "feature_update_runner": runner},
    )

    assert result.success
    assert client.executed == [
        {
            "request_id": request.request_id,
            "runner": runner,
            "dagster_run_id": result.run_id,
            "sigungu_resolver": None,
        }
    ]
    assert result.output_for_node("execute_feature_update_request")["loaded_count"] == 1


def test_worker_job_raises_failure_for_failed_request_result() -> None:
    request = _request()
    client = _Client(
        request=request,
        result=_execution_result(request, state="failed", error_message="provider down"),
    )

    result = feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {"request_id": request.request_id}
                }
            }
        },
        tags={FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id},
        resources={"kor_travel_map_client": client, "feature_update_runner": object()},
        raise_on_error=False,
    )

    assert not result.success


def test_failure_sensor_marks_request_failed() -> None:
    request = _request()
    client = _Client(request=request)
    with DagsterInstance.ephemeral() as instance:
        failed_run = feature_update_request_worker_job.execute_in_process(
            run_config={
                "ops": {
                    "execute_feature_update_request": {
                        "config": {"request_id": request.request_id}
                    }
                }
            },
            tags={FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id},
            resources={
                "kor_travel_map_client": _Client(
                    request=request,
                    result=_execution_result(
                        request, state="failed", error_message="provider down"
                    ),
                ),
                "feature_update_runner": object(),
            },
            instance=instance,
            raise_on_error=False,
        )
        assert not failed_run.success

        context = build_run_status_sensor_context(
            sensor_name="feature_update_request_failure_sensor",
            dagster_instance=instance,
            dagster_run=failed_run.dagster_run,
            dagster_event=failed_run.get_run_failure_event(),
            resources={"kor_travel_map_client": client},
        )

        result = feature_update_request_failure_sensor(context)

    assert isinstance(result, SkipReason)
    assert client.failed == [
        {
            "request_id": request.request_id,
            "dagster_run_id": failed_run.run_id,
            "error_message": (
                "Dagster feature update worker failed: "
                f"run_id={failed_run.run_id} request_id={request.request_id}"
            ),
        }
    ]


def test_failure_sensor_notifies_even_when_fail_update_request_fails() -> None:
    request = _request()
    client = _Client(request=request, fail_raises=RuntimeError("db unavailable"))
    notifications: list[dict[str, str | None]] = []

    def notifier(payload: dict[str, str | None]) -> None:
        notifications.append(dict(payload))

    with DagsterInstance.ephemeral() as instance:
        failed_run = feature_update_request_worker_job.execute_in_process(
            run_config={
                "ops": {
                    "execute_feature_update_request": {
                        "config": {"request_id": request.request_id}
                    }
                }
            },
            tags={FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id},
            resources={
                "kor_travel_map_client": _Client(
                    request=request,
                    result=_execution_result(
                        request, state="failed", error_message="provider down"
                    ),
                ),
                "feature_update_runner": object(),
            },
            instance=instance,
            raise_on_error=False,
        )
        assert not failed_run.success

        context = build_run_status_sensor_context(
            sensor_name="feature_update_request_failure_sensor",
            dagster_instance=instance,
            dagster_run=failed_run.dagster_run,
            dagster_event=failed_run.get_run_failure_event(),
            resources={
                "kor_travel_map_client": client,
                "feature_update_failure_notifier": notifier,
            },
        )

        result = feature_update_request_failure_sensor(context)

    assert isinstance(result, SkipReason)
    assert client.failed == []
    assert notifications == [
        {
            "request_id": request.request_id,
            "run_id": failed_run.run_id,
            "job_name": "feature_update_request_worker",
            "message": (
                "Dagster feature update worker failed: "
                f"run_id={failed_run.run_id} request_id={request.request_id}"
            ),
        }
    ]
