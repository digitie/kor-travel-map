"""feature update request 큐를 Dagster run으로 연결하는 sensor/job."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from kortravelcommon.dagster import RecoveryPolicy
from kortravelmap.infra.failure_summary import FailureSummary, summarize_failure
from kortravelmap.infra.feature_update_executor import FeatureUpdateTransientFailure
from kortravelmap.infra.feature_update_repo import FeatureUpdateLockBusy

from dagster import (
    DefaultSensorStatus,
    Failure,
    OpExecutionContext,
    ResourceParam,
    RunFailureSensorContext,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    job,
    op,
    run_failure_sensor,
    sensor,
)

from .run_failure_detail import failure_detail_text, run_failure_detail
from .upstream_retry import sharing_run_retry_budget

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.infra.feature_update_executor import (
        FeatureUpdateExecutionResult,
        ProviderDatasetRefreshRunner,
    )
    from kortravelmap.infra.feature_update_repo import FeatureUpdateRequest
    from kortravelmap.infra.scope_repo import SigunguByRadiusResolver

FEATURE_UPDATE_SENSOR_INTERVAL_SECONDS: Final[int] = 15
"""ADR-045 D-6 feature update queue polling interval."""

FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS: Final[int] = 10
"""sensor tick 1회에 요청할 feature update worker run 상한."""

FEATURE_UPDATE_REQUEST_GENERATION_TAG: Final[str] = (
    "kor_travel_map.feature_update_request_generation"
)
FEATURE_UPDATE_REQUEST_ID_TAG: Final[str] = "kor_travel_map.feature_update_request_id"
FEATURE_UPDATE_RUN_MODE_TAG: Final[str] = "kor_travel_map.feature_update_run_mode"
FEATURE_UPDATE_SCOPE_TYPE_TAG: Final[str] = "kor_travel_map.feature_update_scope_type"

_MISSING: Final = object()
_T = TypeVar("_T")


@op(
    name="execute_feature_update_request",
    required_resource_keys={"kor_travel_map_client", "feature_update_runner"},
    config_schema={"request_id": str, "request_generation": int},
)
async def execute_feature_update_request_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """RunRequest가 지정한 feature update request 1건을 실행한다."""
    request_id = str(context.op_config["request_id"])
    request_generation = _parse_request_generation(context.op_config["request_generation"])
    if request_generation is None:
        raise Failure(description="feature update request generation이 유효하지 않음")
    client = cast(
        "AsyncKorTravelMapClient",
        _resource_object(context, "kor_travel_map_client"),
    )
    runner = cast(
        "ProviderDatasetRefreshRunner",
        _resource_object(context, "feature_update_runner"),
    )
    sigungu_resolver = cast(
        "SigunguByRadiusResolver | None",
        _resource_object(context, "sigungu_by_radius_resolver", default=None),
    )

    try:
        # request 하나는 scope 여러 개를 차례로 돈다. 그 전부가 재시도 예산 하나를 나눠 쓴다
        # (scope별 runner는 이 예산을 그대로 쓴다 — `sharing_run_retry_budget`).
        with sharing_run_retry_budget():
            result = await client.execute_feature_update_request(
                request_id,
                runner=runner,
                dagster_run_id=context.run_id,
                expected_request_generation=request_generation,
                sigungu_resolver=sigungu_resolver,
            )
    except FeatureUpdateLockBusy as exc:
        metadata: dict[str, object] = {
            "request_id": request_id,
            "status": "lock_busy",
            "retry_after_seconds": exc.retry_after_seconds,
            "lock_key": exc.lock_key,
        }
        context.add_output_metadata(metadata)
        return metadata
    except FeatureUpdateTransientFailure as exc:
        # executor가 종결하지 않고 넘긴 일시 DB 실패(lock timeout·serialization·deadlock·연결).
        return await _reschedule_after_transient_failure(
            context, client, request_id, request_generation, exc.summary, stage=exc.stage
        )
    except Exception as exc:
        # claim 전(request lock·scope lock 획득, request 조회)에 난 일시 DB 실패도 같은 길로 간다.
        # 결정적 실패는 종전처럼 run을 실패시킨다 — failure sensor가 request를 닫는다.
        summary = summarize_failure(exc)
        if summary.failure_class != "transient_db":
            raise
        return await _reschedule_after_transient_failure(
            context, client, request_id, request_generation, summary, stage=None
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


@job(
    name="feature_update_request_worker",
    tags=RecoveryPolicy(max_runtime_seconds=21_600).tags(
        project="map", job_name="feature_update_request_worker"
    ),
)
def feature_update_request_worker_job() -> None:
    """Dagster run 1개가 feature update request 1건을 실행한다."""
    execute_feature_update_request_op()


@sensor(
    name="feature_update_request_queue_sensor",
    job=feature_update_request_worker_job,
    minimum_interval_seconds=FEATURE_UPDATE_SENSOR_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.RUNNING,
    required_resource_keys={"kor_travel_map_client"},
)
def feature_update_request_queue_sensor(
    context: SensorEvaluationContext,
    kor_travel_map_client: object | None = None,
) -> RunRequest | list[RunRequest] | SkipReason:
    """queued/now request가 있으면 worker run을 batch로 요청한다."""
    client = cast(
        "AsyncKorTravelMapClient",
        kor_travel_map_client
        if kor_travel_map_client is not None
        else _resource_object(context, "kor_travel_map_client"),
    )
    requests = _run_async(client.peek_update_requests(limit=FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS))
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
    kor_travel_map_client: ResourceParam[object],
) -> SkipReason:
    """worker run 실패를 request/import job 상태와 운영 알림 sink에 반영한다."""
    request_id = context.dagster_run.tags.get(FEATURE_UPDATE_REQUEST_ID_TAG)
    request_generation = context.dagster_run.tags.get(FEATURE_UPDATE_REQUEST_GENERATION_TAG)
    detail = _failure_detail(context)
    message = _failure_message(context, detail)
    _run_async(
        _handle_failure_side_effects(
            context,
            kor_travel_map_client,
            request_id,
            request_generation,
            message,
            detail,
        )
    )
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
                "config": {
                    "request_id": request.request_id,
                    "request_generation": _request_generation(request),
                }
            }
        }
    }


def _run_request_for_request(request: "FeatureUpdateRequest") -> RunRequest:
    return RunRequest(
        run_key=_run_key_for_request(request),
        run_config=_run_config_for_request(request),
        tags=_tags_for_request(request),
    )


def _run_key_for_request(request: "FeatureUpdateRequest") -> str:
    return f"feature-update:{request.request_id}:{_request_generation(request)}"


def _request_generation(request: "FeatureUpdateRequest") -> int:
    return request.generation


def _parse_request_generation(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _tags_for_request(request: "FeatureUpdateRequest") -> dict[str, str]:
    return {
        FEATURE_UPDATE_REQUEST_ID_TAG: request.request_id,
        FEATURE_UPDATE_REQUEST_GENERATION_TAG: str(_request_generation(request)),
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
        "provider_dataset_memberships": [
            {
                "provider_dataset_id": scope.provider_dataset_id,
                "sync_scope": scope.sync_scope,
                "operation_key": scope.operation_key,
            }
            for scope in result.plan.refresh_scopes
        ],
        "error_message": result.error_message,
    }


async def _reschedule_after_transient_failure(
    context: OpExecutionContext,
    client: "AsyncKorTravelMapClient",
    request_id: str,
    request_generation: int,
    summary: FailureSummary,
    *,
    stage: str | None,
) -> dict[str, object]:
    """일시 DB 실패를 backoff 재발행으로 바꾼다. 상한을 넘었으면 종결하고 run을 실패시킨다.

    재발행에 성공하면 run은 **성공**으로 끝난다 — 할 일을 미뤘을 뿐 실패가 아니고, 실패 run은
    failure sensor·알림을 부른다. 원인과 다음 발행 시각은 Map DB import job event
    (``FEATURE_UPDATE_RETRY_SCHEDULED``)와 이 op의 output metadata에 남는다.
    """
    outcome = await client.reschedule_update_request_after_failure(
        request_id,
        owner_dagster_run_id=context.run_id,
        expected_request_generation=request_generation,
        failure=summary,
        stage=stage,
    )
    failure_metadata: dict[str, str | int | None] = {
        "request_id": request_id,
        "failure_class": summary.failure_class,
        "db_failure": summary.db_failure,
        "stage": stage,
        "error": summary.describe(),
    }
    if outcome is None:
        raise Failure(
            description=(
                "일시 DB 실패 뒤 request 상태가 재발행·종결 대상이 아니었다(이미 종결·취소됐다): "
                f"{summary.describe()}"
            ),
            metadata=failure_metadata,
        )
    if not outcome.rescheduled:
        raise Failure(
            description=outcome.request.error_message or summary.describe(),
            metadata={**failure_metadata, "retry_count": outcome.request.retry_count},
        )
    next_at = outcome.request.next_dispatch_at
    metadata: dict[str, object] = {
        **failure_metadata,
        "status": "retry_scheduled",
        "retry_count": outcome.request.retry_count,
        "next_dispatch_at": next_at.isoformat() if next_at is not None else None,
    }
    context.log.warning(
        "feature update request 일시 실패 — 재발행 예약: request_id=%s retry=%s next=%s error=%s",
        request_id,
        outcome.request.retry_count,
        metadata["next_dispatch_at"],
        summary.describe(),
    )
    context.add_output_metadata(metadata)
    return metadata


def _failure_detail(context: RunFailureSensorContext) -> dict[str, str]:
    return run_failure_detail(getattr(context, "failure_event", None))


def _failure_message(
    context: RunFailureSensorContext, detail: dict[str, str] | None = None
) -> str:
    """Dagster가 남긴 실패 원인(실패 step·오류 타입·메시지)을 담은 한 줄.

    종전에는 ``run_id``와 ``request_id``만 실었다 — 큐 요청의 ``error_message``가 원인 없이 그 한
    줄로
    남았다(감사 §1.2). 원인은 ``RUN_FAILURE`` 이벤트의 ``first_step_failure_event``에서 storage를
    다시
    읽지 않고 꺼낸다(:mod:`.run_failure_detail`).
    """
    run = context.dagster_run
    request_id = run.tags.get(FEATURE_UPDATE_REQUEST_ID_TAG)
    suffix = f" request_id={request_id}" if request_id else ""
    detail = _failure_detail(context) if detail is None else detail
    head = f"Dagster feature update worker failed: run_id={run.run_id}{suffix}"
    body = failure_detail_text(detail)
    return f"{head} — {body}" if body else head


async def _handle_failure_side_effects(
    context: RunFailureSensorContext,
    kor_travel_map_client: object,
    request_id: str | None,
    request_generation: str | None,
    message: str,
    detail: dict[str, str] | None = None,
) -> None:
    if request_id:
        client = cast("AsyncKorTravelMapClient", kor_travel_map_client)
        try:
            expected_generation = (
                _parse_request_generation(request_generation)
                if request_generation is not None
                else None
            )
            if expected_generation is None:
                raise ValueError("feature update failure run에 request generation tag가 없음")
            await client.fail_update_request(
                request_id,
                owner_dagster_run_id=context.dagster_run.run_id,
                expected_request_generation=expected_generation,
                error_message=message,
                failure_payload={"source": "dagster_run_failure", **(detail or {})},
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
    notifier = _resource_object(context, "feature_update_failure_notifier", default=None)
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
