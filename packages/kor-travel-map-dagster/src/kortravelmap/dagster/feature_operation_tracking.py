"""Dagster public Feature asset의 canonical operation guard와 tracking 경계."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import (
    DagsterFeatureOperationMutation,
    DagsterFeatureRunStatus,
    ProviderDatasetOperationKey,
    TriggerKind,
)
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_REGISTRY_BY_JOB,
    FeatureOperationIdentity,
    FeatureOperationRegistryError,
    resolve_feature_operation_launch,
    resolve_feature_operation_runtime_snapshot,
    resolve_feature_operation_trigger,
    validate_feature_operation_identity,
)

from dagster import InitResourceContext, resource

_T = TypeVar("_T")
_MISSING = object()


class FeatureOperationExecutionBlocked(RuntimeError):
    """취소 marker 또는 terminal root가 선점한 Feature operation 실행 차단."""

    def __init__(self, *, dagster_run_id: str, reason: str) -> None:
        super().__init__(
            "Dagster Feature operation 실행이 canonical DB 상태에 의해 차단됨: "
            f"run_id={dagster_run_id!r}, reason={reason!r}"
        )
        self.dagster_run_id = dagster_run_id
        self.reason = reason


class FeatureOperationGuardUnavailable(RuntimeError):
    """public/provider 경계에 canonical guard 값이 없거나 오형식임."""

    code = "FEATURE_OPERATION_GUARD_UNAVAILABLE"

    def __init__(self, *, boundary: str, reason: str) -> None:
        super().__init__(
            "Feature operation guard unavailable: "
            f"boundary={boundary!r}, reason={reason!r}"
        )
        self.boundary = boundary
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FeatureOperationExecutionGuard:
    """resource init과 public wrapper가 공유하는 검증 완료 run identity."""

    client: AsyncKorTravelMapClient
    instance: Any
    identity: FeatureOperationIdentity | None
    dagster_run_id: str
    trigger_kind: TriggerKind | None

    async def ensure(self) -> DagsterFeatureOperationMutation | None:
        """등록 run의 authoritative lifecycle을 재조회해 ensure한다."""
        if self.identity is None or self.trigger_kind is None:
            return None
        created_at, started_at, observed_status = _run_record_snapshot(
            self.instance,
            dagster_run_id=self.dagster_run_id,
        )
        mutation = await self.client.ensure_dagster_feature_operation(
            dagster_run_id=self.dagster_run_id,
            trigger_kind=self.trigger_kind,
            selected_pairs=self.identity.pairs,
            registry_version=self.identity.registry_version,
            engine_created_at=created_at,
            engine_started_at=started_at,
            observed_status=observed_status,
        )
        _raise_if_blocked(self.dagster_run_id, mutation)
        return mutation


def _raise_if_blocked(
    dagster_run_id: str,
    mutation: DagsterFeatureOperationMutation,
) -> None:
    if mutation.outcome != "blocked":
        return
    raise FeatureOperationExecutionBlocked(
        dagster_run_id=dagster_run_id,
        reason=mutation.block_reason or "unknown",
    )


def require_feature_operation_guard(
    context: Any,
    *,
    boundary: str,
) -> FeatureOperationExecutionGuard:
    """public wrapper/provider resource에서 guard 값 자체를 fail-closed한다."""
    resources = getattr(context, "resources", None)
    value = getattr(resources, "feature_operation_guard", _MISSING)
    if value is _MISSING:
        reason = "missing"
    elif value is None:
        reason = "none"
    elif not isinstance(value, FeatureOperationExecutionGuard):
        reason = "wrong_type"
    else:
        job_name = getattr(context, "job_name", None)
        if not isinstance(job_name, str):
            run = getattr(context, "run", None)
            job_name = getattr(run, "job_name", None)
        if isinstance(job_name, str):
            registered = job_name in FEATURE_OPERATION_REGISTRY_BY_JOB
            if registered and value.identity is None:
                reason = "registered_identity_missing"
            elif (
                registered
                and value.identity is not None
                and value.identity.job_name != job_name
            ):
                reason = "registered_identity_mismatch"
            elif not registered and value.identity is not None:
                reason = "panel_identity_unexpected"
            else:
                return value
        else:
            return value
    raise FeatureOperationGuardUnavailable(boundary=boundary, reason=reason)


def _asset_key_string(value: object) -> str:
    to_user_string = getattr(value, "to_user_string", None)
    if callable(to_user_string):
        return str(to_user_string())
    path = getattr(value, "path", None)
    if isinstance(path, Sequence) and not isinstance(path, (str, bytes)):
        return "/".join(str(part) for part in path)
    return str(value)


def _selected_asset_keys(run: Any) -> tuple[str, ...]:
    """실제 run selection을 읽고 fixed full-selection만 registry로 복구한다."""
    asset_selection = run.asset_selection
    if asset_selection:
        return tuple(sorted(_asset_key_string(key) for key in asset_selection))
    resolved_op_selection = run.resolved_op_selection
    if resolved_op_selection:
        return tuple(sorted(str(key) for key in resolved_op_selection))
    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(str(run.job_name))
    return entry.asset_keys if entry is not None else ()


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureOperationGuardUnavailable(
            boundary="run_record",
            reason="naive_timestamp",
        )
    return value.astimezone(UTC)


def _run_record(
    instance: Any,
    *,
    dagster_run_id: str,
) -> Any:
    if instance is None:
        raise RuntimeError("feature_operation_guard에는 Dagster instance가 필요함")
    record = instance.get_run_record_by_id(dagster_run_id)
    if record is None:
        raise RuntimeError(
            f"feature_operation_guard가 Dagster run record를 찾지 못함: {dagster_run_id!r}"
        )
    return record


def _run_record_snapshot(
    instance: Any,
    *,
    dagster_run_id: str,
) -> tuple[datetime, datetime | None, DagsterFeatureRunStatus]:
    record = _run_record(instance, dagster_run_id=dagster_run_id)
    created_at = _aware_datetime(record.create_timestamp)
    started_at = (
        datetime.fromtimestamp(record.start_time, tz=UTC)
        if record.start_time is not None
        else None
    )
    observed_status = cast(DagsterFeatureRunStatus, record.dagster_run.status.value)
    return created_at, started_at, observed_status


def _effective_run_config(
    run: Any,
    *,
    selected_asset_keys: tuple[str, ...],
) -> Mapping[str, object]:
    """ConfigMapping이 생략한 dynamic resource default만 canonical하게 확장한다."""
    run_config = cast(Mapping[str, object], run.run_config)
    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(str(run.job_name))
    if entry is None or entry.snapshot_kind == "static":
        return run_config
    if entry.snapshot_kind == "datagokr_file_data":
        resource_names = (
            "datagokr_file_data_dataset_key",
            "datagokr_file_data_records",
        )
    elif entry.snapshot_kind == "knps_point":
        resource_names = ("knps_point_dataset_key", "knps_point_records")
    else:
        resource_names = ("knps_geometry_dataset_key", "knps_geometry_records")
    resources = run_config.get("resources")
    if "resources" in run_config and not isinstance(resources, Mapping):
        return run_config
    if isinstance(resources, Mapping) and any(
        name in resources for name in resource_names
    ):
        return run_config
    launch = resolve_feature_operation_launch(
        job_name=run.job_name,
        selected_asset_keys=selected_asset_keys,
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(),
    )
    if launch is None:
        return run_config
    _identity, canonical_run_config = launch
    canonical_resources = cast(Mapping[str, object], canonical_run_config["resources"])
    return {
        **run_config,
        "resources": {
            **(resources if isinstance(resources, Mapping) else {}),
            **canonical_resources,
        },
    }


def _context_job_name(context: Any) -> str | None:
    job_name = getattr(context, "job_name", None)
    if not isinstance(job_name, str):
        job_name = getattr(getattr(context, "run", None), "job_name", None)
    return job_name if isinstance(job_name, str) and job_name else None


def _context_run_id(context: Any) -> str | None:
    run_id = getattr(getattr(context, "run", None), "run_id", None)
    if not isinstance(run_id, str):
        run_id = getattr(context, "run_id", None)
    return run_id if isinstance(run_id, str) and run_id else None


async def ensure_authoritative_feature_operation_guard(
    context: Any,
    *,
    boundary: str,
) -> FeatureOperationExecutionGuard:
    """I/O 직전 actual run과 guard의 exact identity를 재검증하고 ensure한다."""
    guard = require_feature_operation_guard(context, boundary=boundary)
    context_job_name = _context_job_name(context)
    context_run_id = _context_run_id(context)
    if context_job_name is None:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="context_job_missing",
        )
    if context_run_id is None:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="context_run_id_missing",
        )
    if guard.dagster_run_id != context_run_id:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="run_id_mismatch",
        )

    client = getattr(
        getattr(context, "resources", None),
        "kor_travel_map_client",
        None,
    )
    if guard.client is not client:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="client_mismatch",
        )
    if guard.instance is not getattr(context, "instance", None):
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="instance_mismatch",
        )

    entry = FEATURE_OPERATION_REGISTRY_BY_JOB.get(context_job_name)
    if entry is None:
        if guard.identity is not None or guard.trigger_kind is not None:
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="panel_guard_invalid",
            )
        return guard

    try:
        record = _run_record(context.instance, dagster_run_id=context_run_id)
    except RuntimeError as exc:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="run_record_missing",
        ) from exc
    run = record.dagster_run
    if run.run_id != context_run_id or run.job_name != context_job_name:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="authoritative_run_mismatch",
        )
    selected_asset_keys = _selected_asset_keys(run)
    try:
        identity = validate_feature_operation_identity(
            job_name=run.job_name,
            selected_asset_keys=selected_asset_keys,
            run_config=_effective_run_config(
                run,
                selected_asset_keys=selected_asset_keys,
            ),
            tags=cast(Mapping[str, str], run.tags),
        )
        trigger_kind = resolve_feature_operation_trigger(identity, run.tags)
    except FeatureOperationRegistryError as exc:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="registry_conflict",
        ) from exc
    if identity is None or guard.identity != identity:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="identity_mismatch",
        )
    if trigger_kind is None or guard.trigger_kind != trigger_kind:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="trigger_mismatch",
        )
    await guard.ensure()
    return guard


def ensure_feature_operation_guard_for_provider(
    context: Any,
    *,
    boundary: str,
) -> FeatureOperationExecutionGuard:
    """sync provider resource에서 authoritative async verifier를 실행한다."""
    event_loop = getattr(context, "event_loop", None)
    if event_loop is not None:
        return cast(
            FeatureOperationExecutionGuard,
            event_loop.run_until_complete(
                ensure_authoritative_feature_operation_guard(
                    context,
                    boundary=boundary,
                )
            ),
        )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            ensure_authoritative_feature_operation_guard(
                context,
                boundary=boundary,
            )
        )
    raise FeatureOperationGuardUnavailable(
        boundary=boundary,
        reason="event_loop_missing",
    )


def _guard_from_context(context: InitResourceContext) -> FeatureOperationExecutionGuard:
    context_run = context.run
    if context_run is None:
        raise RuntimeError("feature_operation_guard는 실제 Dagster run 안에서만 사용할 수 있음")
    record = _run_record(context.instance, dagster_run_id=context_run.run_id)
    run = record.dagster_run
    client = cast(
        AsyncKorTravelMapClient,
        context.resources.kor_travel_map_client,
    )
    selected_asset_keys = _selected_asset_keys(run)
    try:
        identity = validate_feature_operation_identity(
            job_name=run.job_name,
            selected_asset_keys=selected_asset_keys,
            run_config=_effective_run_config(
                run,
                selected_asset_keys=selected_asset_keys,
            ),
            tags=cast(Mapping[str, str], run.tags),
        )
        trigger_kind = resolve_feature_operation_trigger(identity, run.tags)
    except FeatureOperationRegistryError as exc:
        if context.log is not None:
            context.log.error(
                "Feature operation registry validation failed: "
                "code=%s job=%s reason=%s",
                exc.code,
                exc.job_name,
                exc.reason,
            )
        raise

    return FeatureOperationExecutionGuard(
        client=client,
        instance=context.instance,
        identity=identity,
        dagster_run_id=run.run_id,
        trigger_kind=trigger_kind,
    )


@resource(
    required_resource_keys={"kor_travel_map_client"},
    description=(
        "실제 Dagster run identity를 registry와 대조하고 provider I/O 전에 "
        "canonical DB operation을 ensure하는 guard."
    ),
)
def feature_operation_guard_resource(
    context: InitResourceContext,
) -> FeatureOperationExecutionGuard:
    """provider resource보다 먼저 registry/marker를 검증한다."""
    guard = _guard_from_context(context)
    if guard.identity is None:
        if context.log is not None:
            context.log.info(
                "비등록 Dagster job은 canonical DB tracking 없이 panel-only로 실행함: %s",
                context.run.job_name if context.run is not None else "<unknown>",
            )
        return guard
    if context.event_loop is None:
        raise RuntimeError(
            "feature_operation_guard에는 Dagster execution event loop가 필요함"
        )
    context.event_loop.run_until_complete(guard.ensure())
    return guard


def _single_pair_for_asset(
    context: Any,
    guard: FeatureOperationExecutionGuard,
) -> ProviderDatasetOperationKey:
    identity = guard.identity
    if identity is None:
        raise AssertionError("비등록 operation에는 exact pair가 없음")
    selected = tuple(
        sorted(_asset_key_string(key) for key in context.selected_asset_keys)
    )
    if context.job_name != identity.job_name or selected != identity.asset_keys:
        raise FeatureOperationRegistryError(
            "public wrapper context identity/selection drift",
            job_name=context.job_name,
        )
    asset_key = _asset_key_string(context.asset_key)
    if asset_key not in identity.asset_keys:
        raise FeatureOperationRegistryError(
            "public wrapper asset이 frozen selection에 없음",
            job_name=context.job_name,
        )
    if len(identity.pairs) != 1:
        raise FeatureOperationRegistryError(
            "single-pair wrapper가 multi-pair identity를 받음",
            job_name=context.job_name,
        )
    return identity.pairs[0]


async def _append_failed_attempt(
    context: Any,
    guard: FeatureOperationExecutionGuard,
    pair: ProviderDatasetOperationKey,
    error: Exception,
) -> None:
    await guard.client.append_dagster_feature_attempt_event(
        dagster_run_id=guard.dagster_run_id,
        pair=pair,
        attempt_number=int(context.retry_number) + 1,
        outcome="failed",
        error={
            "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
            "type": type(error).__name__,
        },
    )


async def run_tracked_feature_asset(
    context: Any,
    run: Callable[[Any], Awaitable[_T]],
) -> _T:
    """single-pair public wrapper의 last ensure, attempt, success를 소유한다."""
    guard = await ensure_authoritative_feature_operation_guard(
        context,
        boundary="public_wrapper",
    )
    if guard.identity is None:
        return await run(context)
    pair = _single_pair_for_asset(context, guard)
    try:
        result = await run(context)
    except Exception as exc:
        await _append_failed_attempt(context, guard, pair, exc)
        raise
    mutation = await guard.client.finish_dagster_feature_pair(
        dagster_run_id=guard.dagster_run_id,
        pair=pair,
    )
    _raise_if_blocked(guard.dagster_run_id, mutation)
    return result


async def ensure_tracked_multi_pair_asset(
    context: Any,
) -> FeatureOperationExecutionGuard | None:
    """MCST 같은 multi-pair public wrapper의 last ensure를 수행한다."""
    guard = await ensure_authoritative_feature_operation_guard(
        context,
        boundary="public_wrapper",
    )
    if guard.identity is None:
        return None
    identity = guard.identity
    selected = tuple(
        sorted(_asset_key_string(key) for key in context.selected_asset_keys)
    )
    if context.job_name != identity.job_name or selected != identity.asset_keys:
        raise FeatureOperationRegistryError(
            "multi-pair wrapper context identity/selection drift",
            job_name=context.job_name,
        )
    return guard


async def finish_tracked_feature_pair(
    guard: FeatureOperationExecutionGuard,
    pair: ProviderDatasetOperationKey,
) -> None:
    """multi-pair raw callback이 성공한 자기 pair만 완료한다."""
    identity = guard.identity
    if identity is None or pair not in identity.pairs:
        raise FeatureOperationRegistryError(
            "multi-pair callback pair가 frozen selection에 없음",
            job_name=identity.job_name if identity is not None else "<unknown>",
        )
    mutation = await guard.client.finish_dagster_feature_pair(
        dagster_run_id=guard.dagster_run_id,
        pair=pair,
    )
    _raise_if_blocked(guard.dagster_run_id, mutation)


async def append_failed_multi_pair_attempt(
    context: Any,
    guard: FeatureOperationExecutionGuard,
    pair: ProviderDatasetOperationKey,
    error: Exception,
) -> None:
    """MCST 후반 실패를 아직 완료되지 않은 현재 pair event로 남긴다."""
    await _append_failed_attempt(context, guard, pair, error)


__all__ = [
    "FeatureOperationExecutionBlocked",
    "FeatureOperationExecutionGuard",
    "FeatureOperationGuardUnavailable",
    "append_failed_multi_pair_attempt",
    "ensure_authoritative_feature_operation_guard",
    "ensure_feature_operation_guard_for_provider",
    "ensure_tracked_multi_pair_asset",
    "feature_operation_guard_resource",
    "finish_tracked_feature_pair",
    "require_feature_operation_guard",
    "run_tracked_feature_asset",
]
