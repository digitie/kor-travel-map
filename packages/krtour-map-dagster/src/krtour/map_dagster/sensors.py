"""feature update request 큐를 Dagster run으로 연결하는 sensor/job."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from dagster import (
    DefaultSensorStatus,
    Failure,
    OpExecutionContext,
    RunFailureSensorContext,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    job,
    op,
    run_failure_sensor,
    sensor,
)

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient
    from krtour.map.infra.feature_update_executor import (
        FeatureUpdateExecutionResult,
        ProviderDatasetRefreshRunner,
    )
    from krtour.map.infra.feature_update_repo import FeatureUpdateRequest
    from krtour.map.infra.scope_repo import SigunguByRadiusResolver

FEATURE_UPDATE_SENSOR_INTERVAL_SECONDS: Final[int] = 15
"""ADR-045 D-6 feature update queue polling interval."""

FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS: Final[int] = 10
"""sensor tick 1회에 요청할 feature update worker run 상한."""

FEATURE_UPDATE_REQUEST_ID_TAG: Final[str] = "krtour_map.feature_update_request_id"
FEATURE_UPDATE_RUN_MODE_TAG: Final[str] = "krtour_map.feature_update_run_mode"
FEATURE_UPDATE_SCOPE_TYPE_TAG: Final[str] = "krtour_map.feature_update_scope_type"

_MISSING: Final = object()
_T = TypeVar("_T")


@op(
    name="execute_feature_update_request",
    required_resource_keys={"krtour_map_client", "feature_update_runner"},
    config_schema={"request_id": str},
)
async def execute_feature_update_request_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """RunRequest가 지정한 feature update request 1건을 실행한다."""
    request_id = str(context.op_config["request_id"])
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    runner = cast(
        "ProviderDatasetRefreshRunner",
        _resource_object(context, "feature_update_runner"),
    )
    sigungu_resolver = cast(
        "SigunguByRadiusResolver | None",
        _resource_object(context, "sigungu_by_radius_resolver", default=None),
    )

    result = await client.execute_feature_update_request(
        request_id,
        runner=runner,
        dagster_run_id=context.run_id,
        sigungu_resolver=sigungu_resolver,
    )
    if result is None:
        raise Failure(description=f"feature update request 없음: {request_id!r}")

    metadata = _execution_metadata(result)
    context.add_output_metadata(metadata)
    if result.status == "failed":
        raise Failure(
            description=result.error_message or "feature update request 실행 실패",
        )
    return metadata


@job(name="feature_update_request_worker")
def feature_update_request_worker_job() -> None:
    """Dagster run 1개가 feature update request 1건을 실행한다."""
    execute_feature_update_request_op()


@sensor(
    name="feature_update_request_queue_sensor",
    job=feature_update_request_worker_job,
    minimum_interval_seconds=FEATURE_UPDATE_SENSOR_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.RUNNING,
    required_resource_keys={"krtour_map_client"},
)
def feature_update_request_queue_sensor(
    context: SensorEvaluationContext,
    krtour_map_client: object | None = None,
) -> RunRequest | list[RunRequest] | SkipReason:
    """queued/now request가 있으면 worker run을 batch로 요청한다."""
    client = cast(
        "AsyncKrtourMapClient",
        krtour_map_client
        if krtour_map_client is not None
        else _resource_object(context, "krtour_map_client"),
    )
    requests = _run_async(
        client.peek_update_requests(limit=FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS)
    )
    if not requests:
        return SkipReason("queued feature update request 없음")

    run_requests = [_run_request_for_request(request) for request in requests]
    return run_requests[0] if len(run_requests) == 1 else run_requests


@run_failure_sensor(
    name="feature_update_request_failure_sensor",
    monitored_jobs=[feature_update_request_worker_job],
    default_status=DefaultSensorStatus.RUNNING,
)
def feature_update_request_failure_sensor(
    context: RunFailureSensorContext,
) -> SkipReason:
    """worker run 실패를 request/import job 상태와 운영 알림 sink에 반영한다."""
    request_id = context.dagster_run.tags.get(FEATURE_UPDATE_REQUEST_ID_TAG)
    message = _failure_message(context)
    _run_async(_handle_failure_side_effects(context, request_id, message))
    context.log.error(message)
    return SkipReason(message)


FEATURE_UPDATE_JOBS: Final = [feature_update_request_worker_job]
"""feature update request queue 실행 job 목록."""

FEATURE_UPDATE_SENSORS: Final = [
    feature_update_request_queue_sensor,
    feature_update_request_failure_sensor,
]
"""feature update request queue 관련 sensor 목록."""


def _run_async(awaitable: Awaitable[_T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await_value(awaitable))
    raise RuntimeError("Dagster sensor 평가는 running event loop 밖에서 호출해야 함.")


async def _await_value(awaitable: Awaitable[_T]) -> _T:
    return await awaitable


def _resource_object(
    context: object,
    name: str,
    *,
    default: object = _MISSING,
) -> object:
    resources = cast(Any, context).resources
    if not hasattr(resources, name):
        if default is not _MISSING:
            return default
        raise AttributeError(f"Dagster resource 없음: {name}")
    return getattr(resources, name)


def _run_config_for_request(request: "FeatureUpdateRequest") -> dict[str, object]:
    return {
        "ops": {
            "execute_feature_update_request": {
                "config": {"request_id": request.request_id}
            }
        }
    }


def _run_request_for_request(request: "FeatureUpdateRequest") -> RunRequest:
    return RunRequest(
        run_key=f"feature-update:{request.request_id}",
        run_config=_run_config_for_request(request),
        tags=_tags_for_request(request),
    )


def _tags_for_request(request: "FeatureUpdateRequest") -> dict[str, str]:
    return {
        FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
        FEATURE_UPDATE_RUN_MODE_TAG: request.run_mode,
        FEATURE_UPDATE_SCOPE_TYPE_TAG: request.scope_type,
    }


def _execution_metadata(
    result: "FeatureUpdateExecutionResult",
) -> dict[str, object]:
    return {
        "request_id": result.request.request_id,
        "status": result.status,
        "scope_type": result.request.scope_type,
        "run_mode": result.request.run_mode,
        "refresh_scope_count": len(result.plan.refresh_scopes),
        "skipped_scope_count": len(result.plan.skipped_scopes),
        "result_count": len(result.results),
        "loaded_count": sum(item.loaded_count for item in result.results),
        "provider_datasets": [
            f"{scope.provider}:{scope.dataset_key}"
            for scope in result.plan.refresh_scopes
        ],
        "error_message": result.error_message,
    }


def _failure_message(context: RunFailureSensorContext) -> str:
    run = context.dagster_run
    request_id = run.tags.get(FEATURE_UPDATE_REQUEST_ID_TAG)
    suffix = f" request_id={request_id}" if request_id else ""
    return f"Dagster feature update worker failed: run_id={run.run_id}{suffix}"


async def _handle_failure_side_effects(
    context: RunFailureSensorContext,
    request_id: str | None,
    message: str,
) -> None:
    if request_id:
        client = cast(
            "AsyncKrtourMapClient | None",
            _resource_object(context, "krtour_map_client", default=None),
        )
        if client is not None:
            try:
                await client.fail_update_request(
                    request_id,
                    dagster_run_id=context.dagster_run.run_id,
                    error_message=message,
                )
            except Exception as exc:
                context.log.error(
                    "feature update request 실패 상태 반영 실패: request_id=%s error=%s",
                    request_id,
                    exc,
                )
    await _notify_failure(context, request_id=request_id, message=message)


async def _notify_failure(
    context: RunFailureSensorContext,
    *,
    request_id: str | None,
    message: str,
) -> None:
    notifier = _resource_object(
        context, "feature_update_failure_notifier", default=None
    )
    if not callable(notifier):
        return
    payload: Mapping[str, str | None] = {
        "request_id": request_id,
        "run_id": context.dagster_run.run_id,
        "job_name": context.dagster_run.job_name,
        "message": message,
    }
    try:
        result = cast(Callable[[Mapping[str, str | None]], object], notifier)(payload)
        if inspect.isawaitable(result):
            await cast(Awaitable[object], result)
    except Exception as exc:
        context.log.error("feature update 실패 알림 전송 실패: %s", exc)
