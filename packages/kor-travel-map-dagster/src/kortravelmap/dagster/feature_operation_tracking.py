"""Dagster Feature asset의 DB operation-key 기반 실행 추적 경계.

**실행 manifest 불변식** — run root에 frozen되는 member 집합은 "이 operation이
실행할 수 있는 scope 전부"가 아니라 **이 run이 실제로 실행하는 scope 전부**다.
두 집합은 다르다: ``provider_dataset_operation_scopes``는 operation의 *실행 가능*
scope child(ADR-088 §결정 2)이고, ``ops.import_job_datasets``는 *이 run의 작업
목록*이다. DB가 이미 후자를 요구한다 — ``reconcile_dagster_feature_run``은
terminal ``SUCCESS``인데 frozen member 중 ``done``이 아닌 게 하나라도 있으면
operation 전체를 ``failed``/``tracking_invariant``로 떨어뜨린다.

그래서 manifest는 run 자신이 선언한다(``kor_travel_map.execution_scopes`` tag).
tag가 있으면 그 자연키를 canonical resolver로 triple로 바꾸고, 없으면 operation의
실행 가능 scope 전체가 manifest다. run tag는 guard(실행 중)와 reconcile
sensor(실행 밖)가 **같은 값을 보는 유일한 채널**이므로, 둘이 서로 다른 selection을
DB에 들이밀어 identity conflict를 내는 일이 없다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
EXECUTION_SCOPES_TAG = "kor_travel_map.execution_scopes"
"""run이 실행할 scope를 자연키로 선언하는 tag. 없으면 operation 전체가 manifest다."""


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


@dataclass(frozen=True, slots=True, order=True)
class DeclaredExecutionScope:
    """run tag가 자연키로 선언한 실행 대상 1건.

    자연키는 여기서 **해석 입력으로만** 쓰인다. DB에 저장되는 identity는 언제나
    resolver가 돌려준 triple이다(ADR-088 §결정 2).
    """

    provider: str
    dataset_key: str
    sync_scope: str


@dataclass(frozen=True, slots=True)
class FeatureOperationExecutionGuard:
    """실행 시작 시 DB에서 snapshot한 operation key와 canonical member.

    ``memberships``는 이 run의 **실행 manifest**다 — operation이 실행 가능한 scope
    전체가 아니라 이 run이 완료시킬 member 전부. ``declared_scopes``는 그 manifest를
    만든 tag 선언이며, I/O 직전 재검증에서 run tag가 그대로인지 대조하는 데 쓴다.
    """

    client: AsyncKorTravelMapClient
    instance: Any
    operation_key: str | None
    memberships: tuple[ProviderDatasetOperationMembership, ...]
    dagster_run_id: str
    trigger_kind: TriggerKind | None
    declared_scopes: tuple[DeclaredExecutionScope, ...] | None = None

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


def declared_execution_scopes(
    tags: Mapping[str, object],
    *,
    boundary: str,
) -> tuple[DeclaredExecutionScope, ...] | None:
    """run tag의 실행 manifest 선언을 parse한다.

    tag가 없으면 ``None``(= operation의 실행 가능 scope 전체가 manifest). tag가
    있는데 모양이 틀리면 조용히 전체로 넓히지 않고 죽는다 — 넓히면 실행하지 않을
    member까지 running으로 만들어 놓고 run이 끝나 tracking invariant가 깨진다.
    """
    raw = tags.get(EXECUTION_SCOPES_TAG)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="execution_scopes_tag_malformed",
        )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="execution_scopes_tag_malformed",
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="execution_scopes_tag_malformed",
        )
    scopes: list[DeclaredExecutionScope] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="execution_scopes_tag_malformed",
            )
        values = [entry.get("provider"), entry.get("dataset_key"), entry.get("sync_scope")]
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in values
        ):
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="execution_scopes_tag_malformed",
            )
        provider, dataset_key, sync_scope = cast(list[str], values)
        scopes.append(
            DeclaredExecutionScope(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
            )
        )
    if len(set(scopes)) != len(scopes):
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="execution_scopes_tag_duplicated",
        )
    return tuple(scopes)


def encode_execution_scopes(scopes: Sequence[DeclaredExecutionScope]) -> str:
    """실행 manifest 선언을 run tag 값으로 직렬화한다."""
    return json.dumps(
        [
            {
                "provider": scope.provider,
                "dataset_key": scope.dataset_key,
                "sync_scope": scope.sync_scope,
            }
            for scope in scopes
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def resolve_run_execution_manifest(
    client: AsyncKorTravelMapClient,
    *,
    operation_key: str,
    declared: Sequence[DeclaredExecutionScope] | None,
    boundary: str,
) -> tuple[ProviderDatasetOperationMembership, ...]:
    """run이 실행할 member를 확정한다 — guard와 sensor가 공유하는 단일 해석.

    선언이 없으면 operation의 실행 가능 scope 전체가 manifest다(1:1 operation은
    이 경로로 그대로 남는다). 선언이 있으면 각 자연키를 canonical resolver로 triple
    로 바꾸고 실행 가능 집합 안에 있는지 확인한다 — 선언은 좁히기만 할 수 있고
    카탈로그에 없는 대상을 만들어낼 수 없다.
    """
    executable = await client.resolve_feature_operation_memberships(
        operation_key=operation_key,
    )
    if not executable:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="operation_has_no_enabled_memberships",
        )
    if declared is None:
        return executable
    resolved: list[ProviderDatasetOperationMembership] = []
    for scope in declared:
        try:
            membership = await client.resolve_feature_operation_dataset_membership(
                operation_key=operation_key,
                provider=scope.provider,
                dataset_key=scope.dataset_key,
                sync_scope=scope.sync_scope,
            )
        except Exception as exc:
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="execution_scope_not_in_catalog",
            ) from exc
        if membership not in executable:
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="execution_scope_not_executable",
            )
        resolved.append(membership)
    # ensure/reconcile은 selection을 정렬·중복제거한 형태로 비교한다
    # (`_memberships`). guard가 같은 형태를 들고 있어야 두 번째 ensure에서
    # identity conflict가 나지 않는다.
    return tuple(sorted(set(resolved)))


def _context_job_name(context: Any) -> str | None:
    job_name = getattr(context, "job_name", None)
    if not isinstance(job_name, str):
        job_name = getattr(getattr(context, "run", None), "job_name", None)
    return job_name if isinstance(job_name, str) and job_name.strip() else None


def _context_run_id(context: Any) -> str | None:
    """run id를 얻되, 없으면 ``None``.

    예외를 부재로 접는 이유는 ``.run`` 때문이다. 직접 호출된 asset
    context(``build_asset_context()``)에서 ``.run``은 ``AttributeError``가 아니라
    ``DagsterInvalidPropertyError``를 던지므로 ``getattr`` 기본값으로는 잡히지 않고,
    "없으면 None"이라는 이 함수의 계약이 깨진다.

    ``.run_id``는 다르다 — 같은 context에서 예외 없이 문자열 ``"EPHEMERAL"``을
    돌려준다(pinned dagster 실측). 그래서 이 함수는 직접 호출 context에서 ``None``이
    아니라 ``"EPHEMERAL"``을 돌려주며, ``require_feature_operation_guard``의
    run 일치 검사도 그 값으로 성립한다. 패키지 테스트가 그 계약을 상수로 들고 있다
    (``test_kma_weather._DIRECT_INVOCATION_RUN_ID``,
    ``test_notice_assets._DIRECT_INVOCATION_RUN_ID``).
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
    if declared_execution_scopes(tags, boundary=boundary) != guard.declared_scopes:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="execution_scopes_mismatch",
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
    declared = declared_execution_scopes(tags, boundary="resource_init")
    memberships = await resolve_run_execution_manifest(
        client,
        operation_key=operation_key,
        declared=declared,
        boundary="resource_init",
    )
    return FeatureOperationExecutionGuard(
        client=client,
        instance=context.instance,
        operation_key=operation_key,
        memberships=memberships,
        dagster_run_id=run.run_id,
        trigger_kind=trigger_kind,
        declared_scopes=declared,
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
    """run 1회에 dataset 1개를 적재하는 asset의 member를 고른다.

    여기서 요구하는 "1개"는 **operation이 실행 가능한 scope가 1개**라는 뜻이 아니라
    **이 run의 manifest가 1개**라는 뜻이다. 그래서 dataset 여러 개를 묶은
    operation(KNPS point 5, KNPS geometry 5)도 run이 manifest를 1건으로 선언하면
    이 경로를 그대로 쓴다. asset 본문이 선언과 다른 dataset을 적재하면
    ``_load`` 안의 ``_exact_sync_membership``이 manifest 밖 member로 판정해 죽는다 —
    선언과 실행의 일치는 그쪽에서 검증된다.
    """
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
        authoritative_snapshot_complete=bool(
            getattr(
                getattr(result, "observation_receipt", None),
                "authoritative_snapshot_complete",
                False,
            )
        ),
        curation_input_member_count=getattr(
            getattr(result, "load", None), "curation_input_member_count", None
        ),
        curation_input_set_hash=getattr(
            getattr(result, "load", None), "curation_input_set_hash", None
        ),
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
    *,
    authoritative_snapshot_complete: bool = False,
    curation_input_member_count: int | None = None,
    curation_input_set_hash: str | None = None,
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
        authoritative_snapshot_complete=authoritative_snapshot_complete,
        curation_input_member_count=curation_input_member_count,
        curation_input_set_hash=curation_input_set_hash,
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
    "EXECUTION_SCOPES_TAG",
    "DeclaredExecutionScope",
    "FeatureOperationExecutionBlocked",
    "FeatureOperationExecutionGuard",
    "FeatureOperationGuardUnavailable",
    "append_failed_multi_member_attempt",
    "declared_execution_scopes",
    "encode_execution_scopes",
    "resolve_run_execution_manifest",
    "ensure_authoritative_feature_operation_guard",
    "ensure_feature_operation_guard_for_provider",
    "ensure_tracked_multi_member_asset",
    "feature_operation_guard_resource",
    "finish_tracked_feature_membership",
    "require_feature_operation_guard",
    "run_tracked_feature_asset",
]
