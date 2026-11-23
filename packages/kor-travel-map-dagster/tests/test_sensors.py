"""feature update request Dagster sensor/job 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from dagster import (
    DagsterInstance,
    RunRequest,
    SkipReason,
    build_run_status_sensor_context,
    build_sensor_context,
    resource,
)
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.infra.failure_summary import FailureSummary, summarize_failure
from kortravelmap.infra.feature_update_executor import (
    FeatureUpdateExecutionPlan,
    FeatureUpdateExecutionResult,
    FeatureUpdateRetryOutcome,
    FeatureUpdateTerminalizationFailed,
    FeatureUpdateTransientFailure,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestDataset,
)
from kortravelmap.infra.scope_repo import (
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
)

from kortravelmap.dagster.sensors import (
    FEATURE_UPDATE_REQUEST_GENERATION_TAG,
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
    started: list[dict[str, Any]] = field(default_factory=list)
    fail_raises: Exception | None = None
    execute_raises: Exception | None = None
    advance_generation_on_failure: bool = False
    rescheduled: list[dict[str, Any]] = field(default_factory=list)
    reschedule_outcome: FeatureUpdateRetryOutcome | None = None
    reschedule_raises: list[Exception] = field(default_factory=list)
    terminalized: list[dict[str, Any]] = field(default_factory=list)

    async def peek_next_update_request(self) -> FeatureUpdateRequest | None:
        return self.request

    async def peek_update_requests(self, *, limit: int = 10) -> tuple[FeatureUpdateRequest, ...]:
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
        dagster_run_id: str,
        expected_request_generation: int | None = None,
        sigungu_resolver: object | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        if self.execute_raises is not None:
            raise self.execute_raises
        self.executed.append(
            {
                "request_id": request_id,
                "runner": runner,
                "dagster_run_id": dagster_run_id,
                "expected_request_generation": expected_request_generation,
                "sigungu_resolver": sigungu_resolver,
            }
        )
        return self.result

    async def mark_update_request_started(
        self,
        request_id: str,
        *,
        dagster_run_id: str,
        expected_generation: int,
    ) -> FeatureUpdateRequest | None:
        self.started.append(
            {
                "request_id": request_id,
                "dagster_run_id": dagster_run_id,
                "expected_generation": expected_generation,
            }
        )
        return self.request

    async def fail_update_request(
        self,
        request_id: str,
        *,
        owner_dagster_run_id: str,
        expected_request_generation: int,
        error_message: str | None = None,
        failure_payload: dict[str, Any] | None = None,
    ) -> FeatureUpdateRequest | None:
        if self.fail_raises is not None:
            raise self.fail_raises
        self.failed.append(
            {
                "request_id": request_id,
                "owner_dagster_run_id": owner_dagster_run_id,
                "expected_request_generation": expected_request_generation,
                "error_message": error_message,
                "failure_payload": failure_payload,
            }
        )
        if self.advance_generation_on_failure and self.request is not None:
            self.request = replace(
                self.request,
                generation=expected_request_generation + 1,
            )
        return self.request

    async def reschedule_update_request_after_failure(
        self,
        request_id: str,
        *,
        owner_dagster_run_id: str,
        expected_request_generation: int,
        failure: FailureSummary,
        stage: str | None = None,
        max_retries: int = 5,
    ) -> FeatureUpdateRetryOutcome | None:
        self.rescheduled.append(
            {
                "request_id": request_id,
                "owner_dagster_run_id": owner_dagster_run_id,
                "expected_request_generation": expected_request_generation,
                "failure": failure,
                "stage": stage,
                "max_retries": max_retries,
            }
        )
        if self.reschedule_raises:
            raise self.reschedule_raises.pop(0)
        return self.reschedule_outcome

    async def fail_update_request_after_failure(
        self,
        request_id: str,
        *,
        owner_dagster_run_id: str,
        expected_request_generation: int,
        failure: FailureSummary,
        stage: str | None = None,
    ) -> FeatureUpdateRequest | None:
        self.terminalized.append({"request_id": request_id, "failure": failure, "stage": stage})
        return self.request

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


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
            "provider_dataset_id": 1,
        },
        dataset_membership_mode="single",
        dataset_memberships=(
            FeatureUpdateRequestDataset(
                feature_update_request_dataset_id="membership-1",
                provider_dataset_id=1,
                sync_scope="dataset_wide",
                operation_key="feature_place_transport_fuel_stations_job",
                provider="demo",
                dataset_key="places",
            ),
        ),
        update_policy={"prevent_provider_reactivation": True},
        run_mode=run_mode,
        priority=50,
        status=state,
        matched_scope={},
        job_id="job-1",
        dagster_run_id=None,
        operator="codex",
        reason="unit",
        error_message=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
        generation=1,
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
        provider_datasets=(
            # T-VN-33: scope 해석 결과도 자연키 label 뒤에 exact refresh membership
            # (provider_dataset_id + sync_scope + operation_key)을 그대로 들고 있다.
            ProviderDatasetScope(
                provider="demo",
                dataset_key="places",
                feature_count=1,
                provider_dataset_id=1,
                sync_scope="dataset_wide",
                operation_key="feature_place_transport_fuel_stations_job",
            ),
        ),
    )
    refresh_scope = ProviderDatasetRefreshScope(
        request_id=request.request_id,
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        operation_key="feature_place_transport_fuel_stations_job",
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
                provider_dataset_id=1,
                sync_scope="dataset_wide",
                operation_key="feature_place_transport_fuel_stations_job",
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
    assert result.run_key == f"feature-update:{request.request_id}:1"
    assert result.run_config == {
        "ops": {
            "execute_feature_update_request": {
                "config": {
                    "request_id": request.request_id,
                    "request_generation": 1,
                }
            }
        }
    }
    assert result.tags[FEATURE_UPDATE_REQUEST_ID_TAG] == request.request_id
    assert result.tags[FEATURE_UPDATE_REQUEST_GENERATION_TAG] == "1"
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
        f"feature-update:{first.request_id}:1",
        f"feature-update:{second.request_id}:1",
    ]
    assert [
        item.run_config["ops"]["execute_feature_update_request"]["config"] for item in result
    ] == [
        {
            "request_id": first.request_id,
            "request_generation": 1,
        },
        {
            "request_id": second.request_id,
            "request_generation": 1,
        },
    ]
    assert client.peek_limits == [FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS]


def test_worker_job_executes_configured_request() -> None:
    request = _request()
    client = _Client(request=request, result=_execution_result(request))
    runner = object()

    result = feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {
                        "request_id": request.request_id,
                        "request_generation": 1,
                    }
                }
            }
        },
        resources={"kor_travel_map_client": client, "feature_update_runner": runner},
    )

    assert result.success
    assert client.started == []
    assert client.executed == [
        {
            "request_id": request.request_id,
            "runner": runner,
            "dagster_run_id": result.run_id,
            "expected_request_generation": 1,
            "sigungu_resolver": None,
        }
    ]
    assert result.output_for_node("execute_feature_update_request")["loaded_count"] == 1
    assert result.output_for_node("execute_feature_update_request")[
        "provider_dataset_memberships"
    ] == [
        {
            "provider_dataset_id": 1,
            "sync_scope": "dataset_wide",
            "operation_key": "feature_place_transport_fuel_stations_job",
        }
    ]


def test_worker_job_treats_scope_lock_contention_as_retryable_success() -> None:
    request = _request()
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateLockBusy(lock_key="scope-lock"),
    )

    result = feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {
                        "request_id": request.request_id,
                        "request_generation": 1,
                    }
                }
            }
        },
        resources={
            "kor_travel_map_client": client,
            "feature_update_runner": object(),
        },
    )

    assert result.success
    assert result.output_for_node("execute_feature_update_request") == {
        "request_id": request.request_id,
        "status": "lock_busy",
        "retry_after_seconds": 15,
        "lock_key": "scope-lock",
    }


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
                    "config": {
                        "request_id": request.request_id,
                        "request_generation": 1,
                    }
                }
            }
        },
        tags={
            FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
            FEATURE_UPDATE_REQUEST_GENERATION_TAG: "1",
        },
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
                        "config": {
                            "request_id": request.request_id,
                            "request_generation": 1,
                        }
                    }
                }
            },
            tags={
                FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
                FEATURE_UPDATE_REQUEST_GENERATION_TAG: "1",
            },
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
    [failed] = client.failed
    assert failed["request_id"] == request.request_id
    assert failed["owner_dagster_run_id"] == failed_run.run_id
    assert failed["expected_request_generation"] == 1
    # 실패 원인(실패 step·오류 타입·메시지)이 request 오류 메시지와 event payload에 실린다 —
    # 종전에는 run_id와 request_id뿐이었다(감사 §1.2).
    assert failed["error_message"] == (
        "Dagster feature update worker failed: "
        f"run_id={failed_run.run_id} request_id={request.request_id} — "
        "step execute_feature_update_request: Failure: provider down"
    )
    payload = failed["failure_payload"]
    assert payload["source"] == "dagster_run_failure"
    assert payload["failed_step"] == "execute_feature_update_request"
    assert payload["error_type"] == "Failure"
    assert payload["error"] == "provider down"


def test_failure_sensor_requires_database_client_resource() -> None:
    assert feature_update_request_failure_sensor.required_resource_keys == {"kor_travel_map_client"}


def test_pre_start_failure_advances_generation_and_next_sensor_emits_run() -> None:
    request = _request()
    client = _Client(request=request, advance_generation_on_failure=True)

    @resource
    def broken_feature_update_runner() -> object:
        raise RuntimeError("resource initialization failed")

    with DagsterInstance.ephemeral() as instance:
        failed_run = feature_update_request_worker_job.execute_in_process(
            run_config={
                "ops": {
                    "execute_feature_update_request": {
                        "config": {
                            "request_id": request.request_id,
                            "request_generation": 1,
                        }
                    }
                }
            },
            tags={
                FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
                FEATURE_UPDATE_REQUEST_GENERATION_TAG: "1",
            },
            resources={
                "kor_travel_map_client": _Client(request=request),
                "feature_update_runner": broken_feature_update_runner,
            },
            instance=instance,
            raise_on_error=False,
        )
        assert not failed_run.success
        failure_context = build_run_status_sensor_context(
            sensor_name="feature_update_request_failure_sensor",
            dagster_instance=instance,
            dagster_run=failed_run.dagster_run,
            dagster_event=failed_run.get_run_failure_event(),
            resources={"kor_travel_map_client": client},
        )

        feature_update_request_failure_sensor(failure_context)

    advanced = client.request
    assert advanced is not None
    assert advanced.generation == request.generation + 1
    next_context = build_sensor_context(resources={"kor_travel_map_client": client})
    next_run = feature_update_request_queue_sensor(next_context)

    assert isinstance(next_run, RunRequest)
    assert next_run.run_key == (f"feature-update:{request.request_id}:{advanced.generation}")
    assert next_run.run_key != (f"feature-update:{request.request_id}:{request.generation}")
    assert next_run.tags[FEATURE_UPDATE_REQUEST_GENERATION_TAG] == (str(advanced.generation))


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
                        "config": {
                            "request_id": request.request_id,
                            "request_generation": 1,
                        }
                    }
                }
            },
            tags={
                FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
                FEATURE_UPDATE_REQUEST_GENERATION_TAG: "1",
            },
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
                f"run_id={failed_run.run_id} request_id={request.request_id} — "
                "step execute_feature_update_request: Failure: provider down"
            ),
        }
    ]


def test_worker_job_shares_one_retry_budget_across_the_request_scopes() -> None:
    """큐 run 하나는 scope 여러 개를 돈다 — 그 전부가 run 예산 하나를 나눠 쓴다."""
    from kortravelmap.dagster import upstream_retry

    seen: list[object] = []

    @dataclass
    class _BudgetClient(_Client):
        async def execute_feature_update_request(
            self, request_id: str, **kwargs: Any
        ) -> FeatureUpdateExecutionResult | None:
            seen.append(upstream_retry.active_run_retry_budget())
            return await super().execute_feature_update_request(request_id, **kwargs)

    request = _request()
    client = _BudgetClient(request=request, result=_execution_result(request))
    result = feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {"request_id": request.request_id, "request_generation": 1}
                }
            }
        },
        resources={"kor_travel_map_client": client, "feature_update_runner": object()},
    )
    assert result.success
    [budget] = seen
    assert isinstance(budget, upstream_retry.RetryBudget)


class _LockTimeout(Exception):
    """asyncpg ``LockNotAvailableError``의 모양 — SQLSTATE만 본다."""

    sqlstate = "55P03"


def _transient_outcome(
    request: FeatureUpdateRequest, *, rescheduled: bool
) -> FeatureUpdateRetryOutcome:
    return FeatureUpdateRetryOutcome(
        request=replace(
            request,
            generation=request.generation + 1 if rescheduled else request.generation,
            status="queued" if rescheduled else "failed",
            retry_count=1 if rescheduled else 5,
            next_dispatch_at=_NOW if rescheduled else None,
            error_message=None if rescheduled else "재발행 5회 소진: lock timeout",
        ),
        rescheduled=rescheduled,
        max_retries=5,
    )


def _run_worker(client: _Client) -> Any:
    request = client.request
    assert request is not None
    return feature_update_request_worker_job.execute_in_process(
        run_config={
            "ops": {
                "execute_feature_update_request": {
                    "config": {"request_id": request.request_id, "request_generation": 1}
                }
            }
        },
        resources={"kor_travel_map_client": client, "feature_update_runner": object()},
        raise_on_error=False,
    )


def test_worker_reschedules_a_transient_db_failure_instead_of_failing() -> None:
    """executor가 종결하지 않고 넘긴 일시 DB 실패 → 새 연결로 backoff 재발행, run은 성공."""

    request = _request()
    summary = summarize_failure(_LockTimeout("canceling statement due to lock timeout"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTransientFailure(summary, stage="refreshing:1:dataset_wide"),
        reschedule_outcome=_transient_outcome(request, rescheduled=True),
    )

    result = _run_worker(client)

    assert result.success
    [call] = client.rescheduled
    assert call["request_id"] == request.request_id
    assert call["expected_request_generation"] == 1
    assert call["owner_dagster_run_id"] == result.run_id
    assert call["stage"] == "refreshing:1:dataset_wide"
    assert call["failure"].db_failure == "lock_timeout"
    # provider 갱신을 시작한 뒤의 재발행은 상류를 처음부터 다시 부르므로 2회로 줄인다.
    assert call["max_retries"] == 2
    metadata = result.output_for_node("execute_feature_update_request")
    assert metadata["status"] == "retry_scheduled"
    assert metadata["retry_count"] == 1
    assert metadata["db_failure"] == "lock_timeout"


def test_worker_reschedules_a_transient_db_failure_raised_before_claim() -> None:
    """claim 전(lock 획득·조회)에 난 일시 DB 실패도 같은 길로 간다."""

    request = _request()
    client = _Client(
        request=request,
        execute_raises=_LockTimeout("canceling statement due to lock timeout"),
        reschedule_outcome=_transient_outcome(request, rescheduled=True),
    )

    result = _run_worker(client)

    assert result.success
    [call] = client.rescheduled
    assert call["stage"] is None
    assert call["max_retries"] == 5


def test_worker_fails_the_run_when_retries_are_exhausted() -> None:
    request = _request()
    summary = summarize_failure(_LockTimeout("lock timeout"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTransientFailure(summary, stage=None),
        reschedule_outcome=_transient_outcome(request, rescheduled=False),
    )

    result = _run_worker(client)

    assert not result.success
    assert len(client.rescheduled) == 1


def test_worker_does_not_reschedule_a_deterministic_failure() -> None:
    request = _request()
    client = _Client(request=request, execute_raises=ValueError("bad scope"))

    result = _run_worker(client)

    assert not result.success
    assert client.rescheduled == []


def test_worker_retries_the_reschedule_write_on_transient_db_errors(
    monkeypatch: Any,
) -> None:
    """재발행 기록도 event clock 경합으로 실패할 수 있다 — 짧게 다시 시도한다."""
    from kortravelmap.dagster import sensors as sensors_mod

    monkeypatch.setattr(sensors_mod, "_DB_CALL_RETRY_DELAYS_SECONDS", (0.0, 0.0))
    request = _request()
    summary = summarize_failure(_LockTimeout("lock timeout"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTransientFailure(summary, stage="claim"),
        reschedule_outcome=_transient_outcome(request, rescheduled=True),
        reschedule_raises=[_LockTimeout("lock timeout again")],
    )

    result = _run_worker(client)

    assert result.success
    assert len(client.rescheduled) == 2


def test_worker_marks_its_failure_transient_when_the_reschedule_write_keeps_failing(
    monkeypatch: Any,
) -> None:
    """기록이 끝내 실패하면 run을 실패시키되, failure sensor가 닫지 않고 재발행하게 표시한다."""
    from kortravelmap.dagster import sensors as sensors_mod
    from kortravelmap.dagster.run_failure_detail import run_failure_detail

    monkeypatch.setattr(sensors_mod, "_DB_CALL_RETRY_DELAYS_SECONDS", (0.0, 0.0))
    request = _request()
    summary = summarize_failure(_LockTimeout("lock timeout"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTransientFailure(summary, stage="claim"),
        reschedule_raises=[_LockTimeout("a"), _LockTimeout("b"), _LockTimeout("c")],
    )

    result = _run_worker(client)

    assert not result.success
    assert len(client.rescheduled) == 3
    detail = run_failure_detail(result.get_run_failure_event())
    assert detail["failure_class"] == "transient_db"


def test_worker_closes_with_the_original_cause_when_recording_a_failure_failed() -> None:
    request = _request()
    original = summarize_failure(RuntimeError("provider exploded"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTerminalizationFailed(original, stage="refreshing:1:x"),
    )

    result = _run_worker(client)

    assert not result.success
    assert client.rescheduled == []
    [closed] = client.terminalized
    assert closed["failure"].describe() == "RuntimeError: provider exploded"
    assert closed["stage"] == "refreshing:1:x"


def test_worker_does_not_reschedule_a_failure_raised_while_handling_another() -> None:
    request = _request()
    masked = _LockTimeout("lock timeout during cleanup")
    masked.__context__ = ValueError("the real failure")
    client = _Client(request=request, execute_raises=masked)

    result = _run_worker(client)

    assert not result.success
    assert client.rescheduled == []


def test_worker_treats_a_state_change_during_reschedule_as_success() -> None:
    """그 사이 취소·종결·generation 전진이면 재발행할 것이 없다 — 알림을 부르지 않는다."""
    request = _request()
    summary = summarize_failure(_LockTimeout("lock timeout"))
    client = _Client(
        request=request,
        execute_raises=FeatureUpdateTransientFailure(summary, stage=None),
        reschedule_outcome=None,
    )

    result = _run_worker(client)

    assert result.success
    metadata = result.output_for_node("execute_feature_update_request")
    assert metadata["status"] == "state_changed"
