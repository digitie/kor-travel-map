"""Dagster Feature asset의 DB operation-key 기반 실행 추적 경계."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import (
    TRIGGER_KIND_VALUES,
    DagsterFeatureOperationMutation,
    DagsterFeatureRunStatus,
    ProviderDatasetOperationMembership,
    TriggerKind,
)

from dagster import InitResourceContext, resource

_T = TypeVar("_T")
_MISSING = object()
_OPERATION_KEY_TAG = "kor_travel_map.operation_key"
_TRIGGER_KIND_TAG = "kor_travel_map.trigger_kind"
_ADMIN_MANUAL_TRIGGER_TAG = "kor_travel_map.admin_manual_trigger"


class FeatureOperationExecutionBlocked(RuntimeError):
    """취소 marker 또는 terminal root가 선점한 operation 실행 차단."""

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
            f"Feature operation guard unavailable: boundary={boundary!r}, reason={reason!r}"
        )
        self.boundary = boundary
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FeatureOperationExecutionGuard:
    """실행 시작 시 DB에서 snapshot한 operation key와 canonical member."""

    client: AsyncKorTravelMapClient
    instance: Any
    operation_key: str | None
    memberships: tuple[ProviderDatasetOperationMembership, ...]
    dagster_run_id: str
    trigger_kind: TriggerKind | None

    async def ensure(self) -> DagsterFeatureOperationMutation | None:
        """frozen member snapshot으로 authoritative lifecycle을 전진한다."""
        if self.operation_key is None or self.trigger_kind is None:
            return None
        created_at, started_at, observed_status = _run_record_snapshot(
            self.instance,
            dagster_run_id=self.dagster_run_id,
        )
        mutation = await self.client.ensure_dagster_feature_operation(
            dagster_run_id=self.dagster_run_id,
            trigger_kind=self.trigger_kind,
            selected_memberships=self.memberships,
            operation_key=self.operation_key,
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


def _operation_key(tags: Mapping[str, object]) -> str | None:
    value = tags.get(_OPERATION_KEY_TAG)
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value


def _trigger_kind(tags: Mapping[str, object]) -> TriggerKind | None:
    raw = tags.get(_TRIGGER_KIND_TAG)
    if raw in TRIGGER_KIND_VALUES:
        return raw
    if tags.get(_ADMIN_MANUAL_TRIGGER_TAG) == "admin-ui":
        return "manual"
    return "schedule" if _operation_key(tags) is not None else None


def _context_job_name(context: Any) -> str | None:
    job_name = getattr(context, "job_name", None)
    if not isinstance(job_name, str):
        job_name = getattr(getattr(context, "run", None), "job_name", None)
    return job_name if isinstance(job_name, str) and job_name.strip() else None


def _context_run_id(context: Any) -> str | None:
    """run id를 얻되, 없으면 ``None``.

    직접 호출된 asset context에서 ``.run``/``.run_id``는 ``AttributeError``가 아니라
    ``DagsterInvalidPropertyError``를 던진다. ``getattr`` 기본값으로는 잡히지 않아
    "없으면 None"이라는 이 함수의 계약이 깨졌다 — 예외도 부재로 본다.
    """

    def _probe(target: Any, name: str) -> Any:
        try:
            return getattr(target, name, None)
        except Exception:  # noqa: BLE001 - 부재 신호가 예외로 오는 경로가 있다
            return None

    run_id = _probe(_probe(context, "run"), "run_id")
    if not isinstance(run_id, str):
        run_id = _probe(context, "run_id")
    return run_id if isinstance(run_id, str) and run_id.strip() else None


def _run_record(instance: Any, *, dagster_run_id: str) -> Any:
    if instance is None:
        raise RuntimeError("feature_operation_guard에는 Dagster instance가 필요함")
    record = instance.get_run_record_by_id(dagster_run_id)
    if record is None:
        raise RuntimeError(
            f"feature_operation_guard가 Dagster run record를 찾지 못함: {dagster_run_id!r}"
        )
    return record


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureOperationGuardUnavailable(
            boundary="run_record",
            reason="naive_timestamp",
        )
    return value.astimezone(UTC)


def _run_record_snapshot(
    instance: Any,
    *,
    dagster_run_id: str,
) -> tuple[datetime, datetime | None, DagsterFeatureRunStatus]:
    record = _run_record(instance, dagster_run_id=dagster_run_id)
    created_at = _aware_datetime(record.create_timestamp)
    started_at = (
        datetime.fromtimestamp(record.start_time, tz=UTC) if record.start_time is not None else None
    )
    return (
        created_at,
        started_at,
        cast(DagsterFeatureRunStatus, record.dagster_run.status.value),
    )


def require_feature_operation_guard(
    context: Any,
    *,
    boundary: str,
) -> FeatureOperationExecutionGuard:
    """public wrapper/provider resource에서 guard 존재와 run 일치를 검증한다."""
    value = getattr(getattr(context, "resources", None), "feature_operation_guard", _MISSING)
    if not isinstance(value, FeatureOperationExecutionGuard):
        reason = "missing" if value is _MISSING else "wrong_type"
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason=reason)
    run_id = _context_run_id(context)
    if run_id is not None and value.dagster_run_id != run_id:
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason="run_id_mismatch")
    client = getattr(getattr(context, "resources", None), "kor_travel_map_client", None)
    if client is not None and client is not value.client:
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason="client_mismatch")
    return value


async def ensure_authoritative_feature_operation_guard(
    context: Any,
    *,
    boundary: str,
) -> FeatureOperationExecutionGuard:
    """I/O 직전 실제 Dagster run tag가 frozen operation key와 같은지 확인한다."""
    guard = require_feature_operation_guard(context, boundary=boundary)
    if guard.operation_key is None:
        return guard
    run_id = _context_run_id(context)
    if run_id is None:
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason="context_run_id_missing")
    try:
        run = _run_record(guard.instance, dagster_run_id=run_id).dagster_run
    except RuntimeError as exc:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="run_record_missing",
        ) from exc
    tags = cast(Mapping[str, object], run.tags)
    if _operation_key(tags) != guard.operation_key:
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason="operation_key_mismatch")
    if _trigger_kind(tags) != guard.trigger_kind:
        raise FeatureOperationGuardUnavailable(boundary=boundary, reason="trigger_mismatch")
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
                ensure_authoritative_feature_operation_guard(context, boundary=boundary)
            ),
        )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(ensure_authoritative_feature_operation_guard(context, boundary=boundary))
    raise FeatureOperationGuardUnavailable(boundary=boundary, reason="event_loop_missing")


async def _guard_from_context_async(
    context: InitResourceContext,
) -> FeatureOperationExecutionGuard:
    context_run = context.run
    if context_run is None:
        raise RuntimeError("feature_operation_guard는 실제 Dagster run 안에서만 사용할 수 있음")
    record = _run_record(context.instance, dagster_run_id=context_run.run_id)
    run = record.dagster_run
    client = cast(AsyncKorTravelMapClient, context.resources.kor_travel_map_client)
    tags = cast(Mapping[str, object], run.tags)
    operation_key = _operation_key(tags)
    trigger_kind = _trigger_kind(tags)
    if operation_key is None or trigger_kind is None:
        return FeatureOperationExecutionGuard(
            client=client,
            instance=context.instance,
            operation_key=None,
            memberships=(),
            dagster_run_id=run.run_id,
            trigger_kind=None,
        )
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key,
    )
    if not memberships:
        raise FeatureOperationGuardUnavailable(
            boundary="resource_init",
            reason="operation_has_no_enabled_memberships",
        )
    return FeatureOperationExecutionGuard(
        client=client,
        instance=context.instance,
        operation_key=operation_key,
        memberships=memberships,
        dagster_run_id=run.run_id,
        trigger_kind=trigger_kind,
    )


@resource(
    required_resource_keys={"kor_travel_map_client"},
    description="DB operation key와 canonical membership을 snapshot하고 실행을 guard한다.",
)
def feature_operation_guard_resource(
    context: InitResourceContext,
) -> FeatureOperationExecutionGuard:
    """provider resource보다 먼저 DB operation membership을 확정한다."""
    if context.event_loop is None:
        raise RuntimeError("feature_operation_guard에는 Dagster execution event loop가 필요함")
    guard = context.event_loop.run_until_complete(_guard_from_context_async(context))
    if guard.operation_key is not None:
        context.event_loop.run_until_complete(guard.ensure())
    return guard


def _single_membership_for_asset(
    guard: FeatureOperationExecutionGuard,
) -> ProviderDatasetOperationMembership:
    if len(guard.memberships) != 1:
        raise FeatureOperationGuardUnavailable(
            boundary="single_asset",
            reason="operation_requires_exactly_one_membership",
        )
    return guard.memberships[0]


async def _append_failed_attempt(
    context: Any,
    guard: FeatureOperationExecutionGuard,
    membership: ProviderDatasetOperationMembership,
    error: Exception,
) -> None:
    await guard.client.append_dagster_feature_attempt_event(
        dagster_run_id=guard.dagster_run_id,
        membership=membership,
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
    """single-member public wrapper의 attempt와 completion을 소유한다."""
    guard = await ensure_authoritative_feature_operation_guard(
        context,
        boundary="public_wrapper",
    )
    if guard.operation_key is None:
        return await run(context)
    membership = _single_membership_for_asset(guard)
    try:
        result = await run(context)
    except Exception as exc:
        await _append_failed_attempt(context, guard, membership, exc)
        raise
    mutation = await guard.client.finish_dagster_feature_membership(
        dagster_run_id=guard.dagster_run_id,
        membership=membership,
    )
    _raise_if_blocked(guard.dagster_run_id, mutation)
    return result


async def ensure_tracked_multi_member_asset(
    context: Any,
) -> FeatureOperationExecutionGuard | None:
    """multi-member asset의 last ensure를 수행한다."""
    guard = await ensure_authoritative_feature_operation_guard(
        context,
        boundary="public_wrapper",
    )
    return guard if guard.operation_key is not None else None


async def finish_tracked_feature_membership(
    guard: FeatureOperationExecutionGuard,
    membership: ProviderDatasetOperationMembership,
) -> None:
    """multi-member callback이 성공한 canonical member만 완료한다."""
    if membership not in guard.memberships:
        raise FeatureOperationGuardUnavailable(
            boundary="multi_member_callback",
            reason="membership_not_in_frozen_selection",
        )
    mutation = await guard.client.finish_dagster_feature_membership(
        dagster_run_id=guard.dagster_run_id,
        membership=membership,
    )
    _raise_if_blocked(guard.dagster_run_id, mutation)


async def append_failed_multi_member_attempt(
    context: Any,
    guard: FeatureOperationExecutionGuard,
    membership: ProviderDatasetOperationMembership,
    error: Exception,
) -> None:
    """multi-member 후반 실패를 현재 canonical member event로 남긴다."""
    await _append_failed_attempt(context, guard, membership, error)


__all__ = [
    "FeatureOperationExecutionBlocked",
    "FeatureOperationExecutionGuard",
    "FeatureOperationGuardUnavailable",
    "append_failed_multi_member_attempt",
    "ensure_authoritative_feature_operation_guard",
    "ensure_feature_operation_guard_for_provider",
    "ensure_tracked_multi_member_asset",
    "feature_operation_guard_resource",
    "finish_tracked_feature_membership",
    "require_feature_operation_guard",
    "run_tracked_feature_asset",
]
