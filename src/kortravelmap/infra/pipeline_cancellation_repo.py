"""Pipeline 계층형 취소의 DB-only scope/attempt/member/run repository.

C3b와 같은 lineage CTE를 공유해 request branch와 standalone partition을 한 번만
동결한다. 외부 Dagster 호출과 HTTP 의미는 상위 application 계층 책임이다. 모든
함수는 commit하지 않으며 호출자가 transaction을 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.core.pipeline_cancellation_states import (
    PIPELINE_CANCELLATION_RESULT_VALUES,
    PIPELINE_CANCELLATION_STATUS_VALUES,
    PipelineCancellationMemberKind,
    PipelineCancellationResult,
    PipelineCancellationStatus,
)
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.log_repo import record_system_log
from kortravelmap.infra.pipeline_cancellation_invariants import (
    _FAILED_ERROR_CODES,
    _RETRYABLE_ERROR_CODES,
    _run_base_mapping,
    _structured_error_code,
    _validate_finish_invariants,
)
from kortravelmap.infra.pipeline_cancellation_queries import (
    _ATTEMPT_SQL,
    _CURRENT_ATTEMPT_SQL,
    _FEATURE_RUN_TIMELINE_CONFLICT_SQL,
    _FILL_CANONICAL_STARTS_SQL,
    _FINISH_ATTEMPT_SQL,
    _INSERT_ATTEMPT_SQL,
    _INSERT_MEMBER_SQL,
    _INSERT_RUN_SQL,
    _LOCK_ATTEMPT_SQL,
    _LOCK_JOB_MEMBERS_SQL,
    _LOCK_MEMBER_SQL,
    _LOCK_REQUEST_MEMBERS_SQL,
    _LOCK_RUN_SQL,
    _MARK_JOBS_SQL,
    _MARK_REQUESTS_SQL,
    _MEMBERS_SQL,
    _RESERVE_RUN_TERMINATION_SQL,
    _RESOLVE_SCOPE_SQL,
    _RUNS_SQL,
    _TRANSITION_JOB_MEMBER_SQL,
    _TRANSITION_REQUEST_MEMBER_SQL,
    _UPDATE_MEMBER_SQL,
    _UPDATE_RUN_SQL,
)
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationAttempt,
    PipelineCancellationConflict,
    PipelineCancellationDetail,
    PipelineCancellationInvariantError,
    PipelineCancellationMember,
    PipelineCancellationRun,
    PipelineCancellationScope,
    PipelineCancellationScopeMember,
    PipelineCancellationSummary,
    PipelineCancellationTimelineConflict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

_BASE_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_PIPELINE_LINEAGE_MUTATION_LOCK_KEY = "kortravelmap:pipeline-lineage:mutation"


def _validate_kind(value: str) -> PipelineCancellationMemberKind:
    if value not in {"import_job", "update_request"}:
        raise ValueError("kind must be import_job or update_request")
    return cast(PipelineCancellationMemberKind, value)


def _uuid(value: str) -> str:
    return str(UUID(value))


def _json_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value)


def _attempt(row: Any) -> PipelineCancellationAttempt:
    return PipelineCancellationAttempt(
        cancellation_id=str(row.cancellation_id),
        previous_cancellation_id=(
            str(row.previous_cancellation_id)
            if row.previous_cancellation_id is not None
            else None
        ),
        root_kind=_validate_kind(str(row.root_kind)),
        root_id=str(row.root_id),
        status=cast(PipelineCancellationStatus, str(row.status)),
        requested_by=str(row.requested_by),
        reason=row.reason,
        error=_json_dict(row.error),
        requested_at=row.requested_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )


def _member(row: Any) -> PipelineCancellationMember:
    return PipelineCancellationMember(
        cancellation_id=str(row.cancellation_id),
        member_kind=_validate_kind(str(row.member_kind)),
        member_id=str(row.member_id),
        dagster_run_id=row.dagster_run_id,
        operation_kind=row.operation_kind,
        requires_run_termination=bool(row.requires_run_termination),
        initial_status=str(row.initial_status),
        result=cast(PipelineCancellationResult, str(row.result)),
        terminal_status=row.terminal_status,
        error=_json_dict(row.error),
        updated_at=row.updated_at,
    )


def _run(row: Any) -> PipelineCancellationRun:
    return PipelineCancellationRun(
        cancellation_id=str(row.cancellation_id),
        dagster_run_id=str(row.dagster_run_id),
        initial_status=row.initial_status,
        termination_reserved_at=row.termination_reserved_at,
        result=cast(PipelineCancellationResult, str(row.result)),
        terminal_status=row.terminal_status,
        error=_json_dict(row.error),
        updated_at=row.updated_at,
        engine_started_at=row.engine_started_at,
        engine_finished_at=row.engine_finished_at,
    )


async def _lock_attempt(
    session: AsyncSession,
    cancellation_id: str,
) -> PipelineCancellationAttempt | None:
    """모든 cancellation writer가 가장 먼저 잡는 attempt row lock."""
    row = (
        await session.execute(
            text(_LOCK_ATTEMPT_SQL),
            {"cancellation_id": _uuid(cancellation_id)},
        )
    ).one_or_none()
    return _attempt(row) if row is not None else None


async def _lock_in_progress_attempt(
    session: AsyncSession,
    cancellation_id: str,
) -> PipelineCancellationAttempt | None:
    attempt = await _lock_attempt(session, cancellation_id)
    if attempt is None or attempt.status != "in_progress":
        return None
    return attempt


async def _lock_attempt_after_root(
    session: AsyncSession,
    cancellation_id: str,
) -> PipelineCancellationAttempt | None:
    """lineage-global→root→attempt 순서로 finish/retry source를 잠근다."""
    normalized_id = _uuid(cancellation_id)
    observed_row = (
        await session.execute(
            text(_ATTEMPT_SQL),
            {"cancellation_id": normalized_id},
        )
    ).one_or_none()
    if observed_row is None:
        return None
    observed = _attempt(observed_row)
    await lock_pipeline_lineage_mutation(session)
    await lock_pipeline_cancellation_root(
        session,
        root_kind=observed.root_kind,
        root_id=observed.root_id,
    )
    locked = await _lock_attempt(session, normalized_id)
    if locked is None:
        return None
    if (locked.root_kind, locked.root_id) != (observed.root_kind, observed.root_id):
        raise PipelineCancellationConflict(
            "cancellation root changed before ordered attempt lock"
        )
    return locked


async def _lock_member(
    session: AsyncSession,
    *,
    cancellation_id: str,
    member_kind: str,
    member_id: str,
) -> PipelineCancellationMember | None:
    row = (
        await session.execute(
            text(_LOCK_MEMBER_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_kind": _validate_kind(member_kind),
                "member_id": _uuid(member_id),
            },
        )
    ).one_or_none()
    return _member(row) if row is not None else None


async def _lock_run(
    session: AsyncSession,
    *,
    cancellation_id: str,
    dagster_run_id: str,
) -> PipelineCancellationRun | None:
    row = (
        await session.execute(
            text(_LOCK_RUN_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "dagster_run_id": dagster_run_id,
            },
        )
    ).one_or_none()
    return _run(row) if row is not None else None


def pipeline_cancellation_root_lock_key(*, root_kind: str, root_id: str) -> str:
    """모든 hierarchy mutation이 공유할 canonical root lock key."""
    return f"kortravelmap:pipeline-root:{_validate_kind(root_kind)}:{_uuid(root_id)}"


async def lock_pipeline_cancellation_root(
    session: AsyncSession,
    *,
    root_kind: str,
    root_id: str,
) -> None:
    """transaction 종료까지 canonical root mutation을 직렬화한다."""
    lock_id = advisory_lock_key(
        pipeline_cancellation_root_lock_key(root_kind=root_kind, root_id=root_id)
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )


async def lock_pipeline_lineage_mutation(session: AsyncSession) -> None:
    """scope freeze와 parent/child 변경이 공유하는 transaction lock."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": advisory_lock_key(_PIPELINE_LINEAGE_MUTATION_LOCK_KEY)},
    )


async def resolve_pipeline_cancellation_scope(
    session: AsyncSession,
    *,
    kind: str,
    execution_id: str,
) -> PipelineCancellationScope | None:
    """C3b와 같은 owner branch/standalone partition을 deterministic하게 반환한다."""
    normalized_kind = _validate_kind(kind)
    rows = (
        await session.execute(
            text(_RESOLVE_SCOPE_SQL),
            {"kind": normalized_kind, "execution_id": _uuid(execution_id)},
        )
    ).all()
    if not rows:
        return None
    root_kind = _validate_kind(str(rows[0].root_kind))
    root_id = str(rows[0].root_id)
    members = tuple(
        PipelineCancellationScopeMember(
            member_kind=_validate_kind(str(row.member_kind)),
            member_id=str(row.member_id),
            initial_status=str(row.initial_status),
            dagster_run_id=row.dagster_run_id,
            operation_kind=row.operation_kind,
            cancellation_id=(
                str(row.cancellation_id) if row.cancellation_id is not None else None
            ),
        )
        for row in rows
    )
    return PipelineCancellationScope(
        root_kind=root_kind,
        root_id=root_id,
        members=members,
    )


async def lock_pipeline_hierarchy_for_jobs(
    session: AsyncSession,
    job_ids: Sequence[str],
) -> tuple[PipelineCancellationScope, ...]:
    """attach/enqueue 대상의 현재 canonical roots를 정렬해 xact-lock한다."""
    await lock_pipeline_lineage_mutation(session)
    scopes: dict[tuple[str, str], PipelineCancellationScope] = {}
    for job_id in dict.fromkeys(job_ids):
        scope = await resolve_pipeline_cancellation_scope(
            session,
            kind="import_job",
            execution_id=job_id,
        )
        if scope is not None:
            scopes[(scope.root_kind, scope.root_id)] = scope
    for root_kind, root_id in sorted(scopes):
        await lock_pipeline_cancellation_root(
            session,
            root_kind=root_kind,
            root_id=root_id,
        )
    return tuple(scopes[key] for key in sorted(scopes))


async def _lock_scope_members(
    session: AsyncSession,
    members: Sequence[PipelineCancellationScopeMember],
) -> tuple[PipelineCancellationScopeMember, ...]:
    """request→job 고정 순서로 base rows를 잠그고 최신 marker snapshot을 읽는다."""
    locked: list[PipelineCancellationScopeMember] = []
    for member_kind, statement in (
        ("update_request", _LOCK_REQUEST_MEMBERS_SQL),
        ("import_job", _LOCK_JOB_MEMBERS_SQL),
    ):
        member_ids = sorted(
            member.member_id
            for member in members
            if member.member_kind == member_kind
        )
        if not member_ids:
            continue
        rows = (
            await session.execute(
                text(statement),
                {"member_ids": json.dumps(member_ids)},
            )
        ).all()
        if len(rows) != len(member_ids):
            raise PipelineCancellationConflict(
                "cancellation scope member disappeared while locking"
            )
        locked.extend(
            PipelineCancellationScopeMember(
                member_kind=_validate_kind(str(row.member_kind)),
                member_id=str(row.member_id),
                initial_status=str(row.initial_status),
                dagster_run_id=row.dagster_run_id,
                operation_kind=row.operation_kind,
                cancellation_id=(
                    str(row.cancellation_id)
                    if row.cancellation_id is not None
                    else None
                ),
            )
            for row in rows
        )
    return tuple(sorted(locked, key=lambda item: (item.member_kind, item.member_id)))


async def _lock_detail_base_members(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
) -> dict[tuple[str, str], PipelineCancellationScopeMember]:
    requested = tuple(
        PipelineCancellationScopeMember(
            member_kind=member.member_kind,
            member_id=member.member_id,
            initial_status=member.initial_status,
            dagster_run_id=member.dagster_run_id,
            operation_kind=member.operation_kind,
            cancellation_id=detail.attempt.cancellation_id,
        )
        for member in detail.members
    )
    locked = await _lock_scope_members(session, requested)
    base_by_key: dict[tuple[str, str], PipelineCancellationScopeMember] = {
        (member.member_kind, member.member_id): member for member in locked
    }
    if len(base_by_key) != len(detail.members):
        raise PipelineCancellationInvariantError(
            "frozen cancellation member/base cardinality diverged"
        )
    return base_by_key


async def get_pipeline_cancellation_detail(
    session: AsyncSession,
    cancellation_id: str,
) -> PipelineCancellationDetail | None:
    """attempt id로 정규화 attempt/member/run을 DB에서 복원한다."""
    normalized_id = _uuid(cancellation_id)
    attempt_row = (
        await session.execute(
            text(_ATTEMPT_SQL),
            {"cancellation_id": normalized_id},
        )
    ).one_or_none()
    if attempt_row is None:
        return None
    member_rows = (
        await session.execute(
            text(_MEMBERS_SQL),
            {"cancellation_id": normalized_id},
        )
    ).all()
    run_rows = (
        await session.execute(
            text(_RUNS_SQL),
            {"cancellation_id": normalized_id},
        )
    ).all()
    return PipelineCancellationDetail(
        attempt=_attempt(attempt_row),
        members=tuple(_member(row) for row in member_rows),
        runs=tuple(_run(row) for row in run_rows),
    )


async def get_current_pipeline_cancellation_summary(
    session: AsyncSession,
    *,
    root_kind: str,
    root_id: str,
) -> PipelineCancellationSummary | None:
    """active 우선, 아니면 최신 attempt summary를 조회한다."""
    row = (
        await session.execute(
            text(_CURRENT_ATTEMPT_SQL),
            {
                "root_kind": _validate_kind(root_kind),
                "root_id": _uuid(root_id),
            },
        )
    ).one_or_none()
    if row is None:
        return None
    status = cast(PipelineCancellationStatus, str(row.status))
    return PipelineCancellationSummary(
        cancellation_id=str(row.cancellation_id),
        status=status,
        requested_at=row.requested_at,
        requested_by=str(row.requested_by),
        reason=row.reason,
        retryable=status == "retryable",
        unresolved_member_count=int(row.unresolved_member_count),
    )


async def get_current_pipeline_cancellation_detail(
    session: AsyncSession,
    *,
    kind: str,
    execution_id: str,
) -> PipelineCancellationDetail | None:
    """execution을 canonicalize한 뒤 current attempt 상세를 DB-only로 조회한다."""
    scope = await resolve_pipeline_cancellation_scope(
        session,
        kind=kind,
        execution_id=execution_id,
    )
    if scope is None:
        return None
    summary = await get_current_pipeline_cancellation_summary(
        session,
        root_kind=scope.root_kind,
        root_id=scope.root_id,
    )
    if summary is None:
        return None
    return await get_pipeline_cancellation_detail(session, summary.cancellation_id)


async def _insert_pipeline_cancellation_attempt(
    session: AsyncSession,
    *,
    scope: PipelineCancellationScope,
    requested_by: str,
    reason: str | None,
    previous_cancellation_id: str | None = None,
) -> PipelineCancellationDetail:
    """이미 잠긴 frozen scope를 attempt/member/run/marker로 같은 tx에 기록한다."""
    if not requested_by.strip():
        raise ValueError("requested_by must not be empty")
    if not scope.members:
        raise PipelineCancellationInvariantError("cancellation scope must not be empty")
    cancellation_id = str(uuid4())
    no_active_members = not scope.active_members
    attempt_status: PipelineCancellationStatus = (
        "completed" if no_active_members else "in_progress"
    )
    previous_id = (
        _uuid(previous_cancellation_id)
        if previous_cancellation_id is not None
        else None
    )
    await session.execute(
        text(_INSERT_ATTEMPT_SQL),
        {
            "cancellation_id": cancellation_id,
            "previous_cancellation_id": previous_id,
            "root_kind": scope.root_kind,
            "root_id": scope.root_id,
            "status": attempt_status,
            "requested_by": requested_by,
            "reason": reason,
        },
    )

    member_results: dict[tuple[str, str], PipelineCancellationResult] = {
        (member.member_kind, member.member_id): (
            "already_terminal"
            if member.initial_status in _BASE_TERMINAL_STATUSES
            else "pending"
        )
        for member in scope.members
    }
    run_has_active_member: dict[str, bool] = {}
    for member in scope.members:
        if member.dagster_run_id is None:
            continue
        run_has_active_member[member.dagster_run_id] = (
            run_has_active_member.get(member.dagster_run_id, False)
            or member.requires_run_termination
        )
    run_results: dict[str, PipelineCancellationResult] = {
        dagster_run_id: "pending" if has_active_member else "already_terminal"
        for dagster_run_id, has_active_member in run_has_active_member.items()
    }
    for dagster_run_id in sorted(run_results):
        await session.execute(
            text(_INSERT_RUN_SQL),
            {
                "cancellation_id": cancellation_id,
                "dagster_run_id": dagster_run_id,
                "result": run_results[dagster_run_id],
            },
        )
    for member in scope.members:
        result = member_results[(member.member_kind, member.member_id)]
        await session.execute(
            text(_INSERT_MEMBER_SQL),
            {
                "cancellation_id": cancellation_id,
                "member_kind": member.member_kind,
                "member_id": member.member_id,
                "dagster_run_id": member.dagster_run_id,
                "operation_kind": member.operation_kind,
                "initial_status": member.initial_status,
                "requires_run_termination": member.requires_run_termination,
                "result": result,
                "terminal_status": (
                    member.initial_status if result == "already_terminal" else None
                ),
            },
        )

    for member_kind, statement in (
        ("import_job", _MARK_JOBS_SQL),
        ("update_request", _MARK_REQUESTS_SQL),
    ):
        ids = [
            member.member_id
            for member in scope.members
            if member.member_kind == member_kind
        ]
        if not ids:
            continue
        marked = (
            await session.execute(
                text(statement),
                {
                    "member_ids": json.dumps(ids),
                    "cancellation_id": cancellation_id,
                    "expected_cancellation_id": previous_id,
                    "requested_by": requested_by,
                    "reason": reason,
                },
            )
        ).all()
        if len(marked) != len(ids):
            raise PipelineCancellationConflict(
                f"{member_kind} marker CAS changed while freezing cancellation scope"
            )

    await record_system_log(
        session,
        level="warning",
        source="pipeline_cancellation",
        event="pipeline.cancellation.requested",
        message="pipeline cancellation scope frozen",
        detail={
            "cancellation_id": cancellation_id,
            "previous_cancellation_id": previous_id,
            "root_kind": scope.root_kind,
            "root_id": scope.root_id,
            "status": attempt_status,
            "requested_by": requested_by,
            "reason": reason,
            "member_count": len(scope.members),
        },
    )
    detail = await get_pipeline_cancellation_detail(session, cancellation_id)
    if detail is None:
        raise PipelineCancellationInvariantError("created cancellation attempt is missing")
    return detail


async def create_pipeline_cancellation_attempt(
    session: AsyncSession,
    *,
    scope: PipelineCancellationScope,
    requested_by: str,
    reason: str | None,
    previous_cancellation_id: str | None = None,
) -> PipelineCancellationDetail:
    """C3b parity scope를 다시 고정하고 최초 cancellation attempt를 생성한다.

    ``previous_cancellation_id``는 내부 테스트와 coordinator 복구를 위한 marker CAS
    입력이다. retryable attempt 재시도는 hierarchy를 다시 읽지 않는
    :func:`retry_pipeline_cancellation_attempt`를 사용해야 한다.
    """
    await lock_pipeline_lineage_mutation(session)
    await lock_pipeline_cancellation_root(
        session,
        root_kind=scope.root_kind,
        root_id=scope.root_id,
    )
    refreshed = await resolve_pipeline_cancellation_scope(
        session,
        kind=scope.root_kind,
        execution_id=scope.root_id,
    )
    if (
        refreshed is None
        or refreshed.root_kind != scope.root_kind
        or refreshed.root_id != scope.root_id
    ):
        raise PipelineCancellationConflict(
            "canonical cancellation root changed before scope freeze"
        )
    locked_members = await _lock_scope_members(session, refreshed.members)
    frozen_scope = PipelineCancellationScope(
        root_kind=refreshed.root_kind,
        root_id=refreshed.root_id,
        members=locked_members,
    )
    return await _insert_pipeline_cancellation_attempt(
        session,
        scope=frozen_scope,
        requested_by=requested_by,
        reason=reason,
        previous_cancellation_id=previous_cancellation_id,
    )


async def retry_pipeline_cancellation_attempt(
    session: AsyncSession,
    *,
    previous_cancellation_id: str,
    requested_by: str,
    reason: str | None,
) -> PipelineCancellationDetail:
    """이전 retryable attempt의 미해결 frozen member만 새 attempt로 복사한다."""
    previous_id = _uuid(previous_cancellation_id)
    locked_attempt = await _lock_attempt_after_root(session, previous_id)
    if locked_attempt is None:
        raise PipelineCancellationConflict("retry source cancellation attempt is missing")
    if locked_attempt.status != "retryable":
        raise PipelineCancellationConflict("only retryable cancellation can be retried")
    previous = await get_pipeline_cancellation_detail(session, previous_id)
    if previous is None:
        raise PipelineCancellationConflict("retry source cancellation attempt is missing")
    base_by_key = await _lock_detail_base_members(session, previous)
    _validate_finish_invariants(
        previous,
        base_by_key,
        status="retryable",
        error=previous.attempt.error,
    )
    unresolved = tuple(
        member
        for member in previous.members
        if member.requires_run_termination and member.result == "cancel_failed"
    )
    if not unresolved:
        raise PipelineCancellationInvariantError(
            "retryable cancellation has no unresolved members"
        )

    current = await get_current_pipeline_cancellation_summary(
        session,
        root_kind=previous.attempt.root_kind,
        root_id=previous.attempt.root_id,
    )
    if current is None or current.cancellation_id != previous_id:
        raise PipelineCancellationConflict(
            "retry source is no longer the current cancellation attempt"
        )

    locked_members: list[PipelineCancellationScopeMember] = []
    for prior in unresolved:
        base = base_by_key[(prior.member_kind, prior.member_id)]
        if base.cancellation_id != previous_id:
            raise PipelineCancellationConflict(
                "retry member marker no longer references the source attempt"
            )
        if base.dagster_run_id != prior.dagster_run_id:
            raise PipelineCancellationConflict(
                "retry member Dagster run mapping changed after scope freeze"
            )
        locked_members.append(
            PipelineCancellationScopeMember(
                member_kind=prior.member_kind,
                member_id=prior.member_id,
                initial_status=prior.initial_status,
                dagster_run_id=prior.dagster_run_id,
                operation_kind=prior.operation_kind,
                cancellation_id=previous_id,
            )
        )

    frozen_scope = PipelineCancellationScope(
        root_kind=previous.attempt.root_kind,
        root_id=previous.attempt.root_id,
        members=tuple(locked_members),
    )
    return await _insert_pipeline_cancellation_attempt(
        session,
        scope=frozen_scope,
        requested_by=requested_by,
        reason=reason,
        previous_cancellation_id=previous_id,
    )


def _validate_result(result: str) -> PipelineCancellationResult:
    if result not in PIPELINE_CANCELLATION_RESULT_VALUES:
        raise ValueError(f"invalid pipeline cancellation result: {result}")
    return result


async def set_pipeline_cancellation_member_result(
    session: AsyncSession,
    *,
    cancellation_id: str,
    member_kind: str,
    member_id: str,
    result: str,
    terminal_status: str | None,
    error: Mapping[str, Any] | None,
    expected_results: Sequence[str] = ("pending", "cancel_failed"),
) -> bool:
    """외부 terminate 실패만 기록한다.

    성공 결과는 base 상태와 Dagster run 결과를 함께 검증해야 하므로 이 setter로
    기록할 수 없다.
    """
    normalized_result = _validate_result(result)
    if normalized_result != "cancel_failed":
        raise ValueError("member result setter only accepts cancel_failed")
    if terminal_status is not None:
        raise ValueError("cancel_failed member cannot have a terminal status")
    error_code = _structured_error_code(error)
    if set(expected_results) - {"pending", "cancel_failed"}:
        raise ValueError("member failure CAS only accepts unresolved expected results")
    if await _lock_in_progress_attempt(session, cancellation_id) is None:
        return False
    member = await _lock_member(
        session,
        cancellation_id=cancellation_id,
        member_kind=member_kind,
        member_id=member_id,
    )
    if member is None or member.result not in set(expected_results):
        return False
    if member.initial_status != "running" and not member.requires_run_termination:
        raise PipelineCancellationInvariantError(
            "cancel_failed is restricted to running or run-backed active members"
        )
    run = None
    if member.dagster_run_id is not None:
        run = await _lock_run(
            session,
            cancellation_id=cancellation_id,
            dagster_run_id=member.dagster_run_id,
        )
        if run is None:
            raise PipelineCancellationInvariantError("matching cancellation run is missing")
    base = (
        await _lock_scope_members(
            session,
            (
                PipelineCancellationScopeMember(
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                    initial_status=member.initial_status,
                    dagster_run_id=member.dagster_run_id,
                    operation_kind=member.operation_kind,
                    cancellation_id=cancellation_id,
                ),
            ),
        )
    )[0]
    expected_base_statuses = (
        {"queued", "running"}
        if member.initial_status == "queued"
        else {member.initial_status}
    )
    base_matches = (
        base.cancellation_id == _uuid(cancellation_id)
        and base.initial_status in expected_base_statuses
        and base.dagster_run_id == member.dagster_run_id
        and base.operation_kind == member.operation_kind
    )
    if error_code in _RETRYABLE_ERROR_CODES:
        if not member.requires_run_termination:
            raise PipelineCancellationInvariantError(
                "retryable member failure requires a frozen Dagster run"
            )
        if not base_matches:
            raise PipelineCancellationConflict(
                "retryable member failure requires the exact frozen running base"
            )
        if run is None or run.result != "cancel_failed":
            raise PipelineCancellationInvariantError(
                "retryable member failure requires the matching run failure first"
            )
    elif error_code in _FAILED_ERROR_CODES:
        if member.dagster_run_id is not None and base_matches:
            if run is None or run.result != "cancel_failed":
                raise PipelineCancellationInvariantError(
                    "exact definitive failure requires an authoritative run failure"
                )
            _structured_error_code(run.error, allowed_codes=_FAILED_ERROR_CODES)
    else:
        raise PipelineCancellationInvariantError(
            "member failure code does not match retryable or definitive policy"
        )
    row = (
        await session.execute(
            text(_UPDATE_MEMBER_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_kind": _validate_kind(member_kind),
                "member_id": _uuid(member_id),
                "result": normalized_result,
                "terminal_status": terminal_status,
                "error": json.dumps(dict(error)) if error is not None else None,
                "expected_results": list(expected_results),
            },
        )
    ).one_or_none()
    if row is None:
        return False
    await record_system_log(
        session,
        level="warning" if normalized_result == "cancel_failed" else "info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.member_result",
        message="pipeline cancellation member result updated",
        detail={
            "cancellation_id": cancellation_id,
            "member_kind": member_kind,
            "member_id": member_id,
            "result": normalized_result,
            "terminal_status": terminal_status,
        },
    )
    return True


async def set_pipeline_cancellation_run_result(
    session: AsyncSession,
    *,
    cancellation_id: str,
    dagster_run_id: str,
    result: str,
    initial_status: str | None,
    terminal_status: str | None,
    error: Mapping[str, Any] | None,
    engine_started_at: datetime | None = None,
    engine_finished_at: datetime | None = None,
    expected_results: Sequence[str] = ("pending", "cancel_failed"),
) -> bool:
    """attempt/run PK로 terminate 결과를 한 번만 CAS 갱신한다."""
    normalized_result = _validate_result(result)
    if normalized_result == "pending":
        raise ValueError("run result setter cannot write pending")
    if normalized_result == "cancelled":
        if terminal_status != "CANCELED" or error is not None:
            raise PipelineCancellationInvariantError(
                "cancelled run requires Dagster CANCELED and no error"
            )
    elif normalized_result == "already_terminal":
        if terminal_status not in {"SUCCESS", "FAILURE"} or error is not None:
            raise PipelineCancellationInvariantError(
                "already_terminal run requires Dagster SUCCESS or FAILURE"
            )
    elif normalized_result == "cancel_failed":
        if terminal_status is not None:
            raise PipelineCancellationInvariantError(
                "cancel_failed run cannot have a terminal status"
            )
        _structured_error_code(error)
    if normalized_result == "cancel_failed" and (
        engine_started_at is not None or engine_finished_at is not None
    ):
        raise PipelineCancellationInvariantError(
            "failed run cannot persist authoritative terminal timestamps"
        )
    if engine_started_at is not None and engine_finished_at is None:
        raise PipelineCancellationInvariantError(
            "engine_started_at requires an authoritative engine_finished_at"
        )
    if engine_started_at is not None and (
        engine_started_at.tzinfo is None or engine_started_at.utcoffset() is None
    ):
        raise ValueError("engine_started_at must be timezone-aware")
    if engine_finished_at is not None and (
        engine_finished_at.tzinfo is None or engine_finished_at.utcoffset() is None
    ):
        raise ValueError("engine_finished_at must be timezone-aware")
    if (
        engine_started_at is not None
        and engine_finished_at is not None
        and engine_started_at > engine_finished_at
    ):
        raise ValueError("engine_started_at must not follow engine_finished_at")
    if set(expected_results) - {"pending", "cancel_failed"}:
        raise ValueError("run CAS only accepts unresolved expected results")
    if await _lock_in_progress_attempt(session, cancellation_id) is None:
        return False
    run = await _lock_run(
        session,
        cancellation_id=cancellation_id,
        dagster_run_id=dagster_run_id,
    )
    if run is None or run.result not in set(expected_results):
        return False
    if normalized_result in {"cancelled", "already_terminal"}:
        timeline = (
            await session.execute(
                text(_FEATURE_RUN_TIMELINE_CONFLICT_SQL),
                {
                    "cancellation_id": _uuid(cancellation_id),
                    "dagster_run_id": dagster_run_id,
                    "engine_started_at": engine_started_at,
                    "engine_finished_at": engine_finished_at,
                },
            )
        ).one()
        if int(timeline.expected_count) != int(timeline.owned_count):
            raise PipelineCancellationConflict(
                "canonical terminal run lost the frozen cancellation marker"
            )
        if timeline.has_conflict:
            raise PipelineCancellationTimelineConflict(
                "canonical feature terminal time precedes its frozen DB timeline"
            )
        engine_started_at = timeline.effective_started_at
    row = (
        await session.execute(
            text(_UPDATE_RUN_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "dagster_run_id": dagster_run_id,
                "result": normalized_result,
                "initial_status": initial_status,
                "terminal_status": terminal_status,
                "error": json.dumps(dict(error)) if error is not None else None,
                "engine_started_at": engine_started_at,
                "engine_finished_at": engine_finished_at,
                "expected_results": list(expected_results),
            },
        )
    ).one_or_none()
    if row is None:
        return False
    await record_system_log(
        session,
        level="warning" if normalized_result == "cancel_failed" else "info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.run_result",
        message="pipeline cancellation run result updated",
        detail={
            "cancellation_id": cancellation_id,
            "dagster_run_id": dagster_run_id,
            "result": normalized_result,
            "terminal_status": terminal_status,
        },
    )
    return True


async def mark_pipeline_cancellation_run_termination_reserved(
    session: AsyncSession,
    *,
    cancellation_id: str,
    dagster_run_id: str,
    initial_status: str,
) -> bool:
    """첫 active 관측과 attempt별 terminate dispatch 예약을 원자적으로 기록한다."""
    normalized_status = initial_status.strip().upper()
    if not normalized_status:
        raise ValueError("initial_status must not be empty")
    if normalized_status in {"CANCELED", "SUCCESS", "FAILURE"}:
        raise ValueError("terminal Dagster status cannot reserve termination")
    if await _lock_in_progress_attempt(session, cancellation_id) is None:
        return False
    run = await _lock_run(
        session,
        cancellation_id=cancellation_id,
        dagster_run_id=dagster_run_id,
    )
    if run is None or run.result != "pending":
        return False
    if run.termination_reserved_at is not None:
        return False
    row = (
        await session.execute(
            text(_RESERVE_RUN_TERMINATION_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "dagster_run_id": dagster_run_id,
                "initial_status": normalized_status,
            },
        )
    ).one_or_none()
    if row is None:
        return False
    await record_system_log(
        session,
        level="info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.run_termination_reserved",
        message="Dagster terminate dispatch reserved for this cancellation attempt",
        detail={
            "cancellation_id": cancellation_id,
            "dagster_run_id": dagster_run_id,
            "initial_status": normalized_status,
        },
    )
    return True


async def fill_pipeline_cancellation_canonical_starts(
    session: AsyncSession,
    *,
    cancellation_id: str,
    dagster_run_id: str,
    engine_started_at: datetime,
) -> tuple[str, ...]:
    """frozen canonical member의 누락 start를 권위 있는 run start로 보충한다."""
    if engine_started_at.tzinfo is None or engine_started_at.utcoffset() is None:
        raise ValueError("engine_started_at must be timezone-aware")
    row = (
        await session.execute(
            text(_FILL_CANONICAL_STARTS_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "dagster_run_id": dagster_run_id,
                "engine_started_at": engine_started_at,
            },
        )
    ).one()
    if int(row.expected_count) != int(row.owned_count):
        raise PipelineCancellationConflict(
            "canonical start fill lost the frozen cancellation marker"
        )
    return tuple(str(job_id) for job_id in row.updated_job_ids)


async def transition_pipeline_cancellation_member(
    session: AsyncSession,
    *,
    cancellation_id: str,
    member_kind: str,
    member_id: str,
    dagster_run_id: str | None,
    expected_status: str,
    target_status: str,
    result: str,
    error_message: str | None = None,
    dagster_terminal_status: str | None = None,
    engine_started_at: datetime | None = None,
    engine_finished_at: datetime | None = None,
    success_tracking_invariant: bool = False,
) -> bool:
    """종결된 Dagster run과 정확히 매핑되는 running base/member를 함께 전이한다."""
    if expected_status not in {"queued", "running"}:
        raise ValueError("run-backed transition requires queued or running status")
    normalized_result = _validate_result(result)
    if dagster_run_id is None:
        raise PipelineCancellationInvariantError(
            "running member transition requires a Dagster run"
        )
    normalized_kind = _validate_kind(member_kind)
    if await _lock_in_progress_attempt(session, cancellation_id) is None:
        return False
    member = await _lock_member(
        session,
        cancellation_id=cancellation_id,
        member_kind=normalized_kind,
        member_id=member_id,
    )
    if member is None or member.result not in {"pending", "cancel_failed"}:
        return False
    if not member.requires_run_termination or member.dagster_run_id != dagster_run_id:
        raise PipelineCancellationConflict(
            "run-backed member frozen status/run mapping diverged"
        )
    if member.operation_kind in {
        "provider_feature_load_run",
        "provider_feature_load",
    }:
        if engine_finished_at is None:
            raise PipelineCancellationInvariantError(
                "canonical feature terminal transition requires engine_finished_at"
            )
        if (
            engine_finished_at.tzinfo is None
            or engine_finished_at.utcoffset() is None
        ):
            raise ValueError("engine_finished_at must be timezone-aware")
        if engine_started_at is not None and (
            engine_started_at.tzinfo is None
            or engine_started_at.utcoffset() is None
        ):
            raise ValueError("engine_started_at must be timezone-aware")
        if (
            engine_started_at is not None
            and engine_started_at > engine_finished_at
        ):
            raise ValueError("engine_started_at must not follow engine_finished_at")
    if member.initial_status != expected_status:
        raise PipelineCancellationConflict(
            "run-backed member frozen status changed before transition"
        )
    run = await _lock_run(
        session,
        cancellation_id=cancellation_id,
        dagster_run_id=dagster_run_id,
    )
    if run is None:
        raise PipelineCancellationInvariantError("matching cancellation run is missing")
    mapping = _run_base_mapping(run)
    if mapping is None:
        raise PipelineCancellationInvariantError(
            "member cannot transition before its Dagster run is terminal"
        )
    expected_target, expected_result = mapping
    if success_tracking_invariant:
        frozen_non_done_pair_exists = bool(
            await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM ops.pipeline_cancellation_members
                      WHERE cancellation_id = CAST(:cancellation_id AS uuid)
                        AND dagster_run_id = :dagster_run_id
                        AND operation_kind = 'provider_feature_load'
                        AND initial_status <> 'done'
                    )
                    """
                ),
                {
                    "cancellation_id": _uuid(cancellation_id),
                    "dagster_run_id": dagster_run_id,
                },
            )
        )
        if not (
            normalized_kind == "import_job"
            and member.operation_kind
            in {"provider_feature_load_run", "provider_feature_load"}
            and run.result == "already_terminal"
            and run.terminal_status == "SUCCESS"
            and target_status == "failed"
            and normalized_result == "already_terminal"
            and frozen_non_done_pair_exists
        ):
            raise PipelineCancellationInvariantError(
                "SUCCESS tracking invariant override requires a canonical active member"
            )
        expected_target = "failed"
    if (target_status, normalized_result) != (expected_target, expected_result):
        raise PipelineCancellationInvariantError(
            "requested base/member result does not match Dagster terminal result"
        )
    base = (
        await _lock_scope_members(
            session,
            (
                PipelineCancellationScopeMember(
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                    initial_status=member.initial_status,
                    dagster_run_id=member.dagster_run_id,
                    operation_kind=member.operation_kind,
                    cancellation_id=cancellation_id,
                ),
            ),
        )
    )[0]
    expected_statuses = (
        ("queued", "running")
        if member.initial_status == "queued"
        else ("running",)
    )
    if (
        base.cancellation_id != _uuid(cancellation_id)
        or base.initial_status not in expected_statuses
        or base.dagster_run_id != dagster_run_id
        or base.operation_kind != member.operation_kind
    ):
        raise PipelineCancellationConflict(
            "running base marker/status/run mapping diverged"
        )
    statement = (
        _TRANSITION_JOB_MEMBER_SQL
        if normalized_kind == "import_job"
        else _TRANSITION_REQUEST_MEMBER_SQL
    )
    row = (
        await session.execute(
            text(statement),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_id": _uuid(member_id),
                "dagster_run_id": dagster_run_id,
                "expected_statuses": list(expected_statuses),
                "target_status": target_status,
                "error_message": error_message,
                "dagster_terminal_status": dagster_terminal_status,
                "engine_started_at": engine_started_at,
                "engine_finished_at": engine_finished_at,
                "success_tracking_invariant": success_tracking_invariant,
            },
        )
    ).one_or_none()
    if row is None:
        return False
    updated = (
        await session.execute(
            text(_UPDATE_MEMBER_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_kind": normalized_kind,
                "member_id": _uuid(member_id),
                "result": normalized_result,
                "terminal_status": target_status,
                "error": None,
                "expected_results": [member.result],
            },
        )
    ).one_or_none()
    if updated is None:
        raise PipelineCancellationInvariantError(
            "base member transitioned but normalized member result CAS failed"
        )
    await record_system_log(
        session,
        level="info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.member_transitioned",
        message="Dagster terminal result reconciled to the frozen member",
        detail={
            "cancellation_id": cancellation_id,
            "member_kind": normalized_kind,
            "member_id": member_id,
            "dagster_run_id": dagster_run_id,
            "target_status": target_status,
            "result": normalized_result,
        },
    )
    return True


async def cancel_queued_pipeline_cancellation_member(
    session: AsyncSession,
    *,
    cancellation_id: str,
    member_kind: str,
    member_id: str,
) -> bool:
    """외부 terminate 호출 없이 queued base/member를 같은 tx에서 취소한다."""
    normalized_kind = _validate_kind(member_kind)
    if await _lock_in_progress_attempt(session, cancellation_id) is None:
        return False
    member = await _lock_member(
        session,
        cancellation_id=cancellation_id,
        member_kind=normalized_kind,
        member_id=member_id,
    )
    if member is None or member.result != "pending":
        return False
    if member.initial_status != "queued":
        raise PipelineCancellationInvariantError(
            "explicit DB-only cancellation only accepts queued members"
        )
    if member.requires_run_termination:
        raise PipelineCancellationInvariantError(
            "run-backed queued member requires authoritative Dagster termination"
        )
    base = (
        await _lock_scope_members(
            session,
            (
                PipelineCancellationScopeMember(
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                    initial_status=member.initial_status,
                    dagster_run_id=member.dagster_run_id,
                    operation_kind=member.operation_kind,
                    cancellation_id=cancellation_id,
                ),
            ),
        )
    )[0]
    if (
        base.cancellation_id != _uuid(cancellation_id)
        or base.initial_status != "queued"
        or base.dagster_run_id != member.dagster_run_id
        or base.operation_kind != member.operation_kind
    ):
        raise PipelineCancellationConflict(
            "queued base marker/status/run mapping diverged"
        )
    statement = (
        _TRANSITION_JOB_MEMBER_SQL
        if normalized_kind == "import_job"
        else _TRANSITION_REQUEST_MEMBER_SQL
    )
    transitioned = (
        await session.execute(
            text(statement),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_id": _uuid(member_id),
                "dagster_run_id": member.dagster_run_id,
                "expected_statuses": ["queued"],
                "target_status": "cancelled",
                "error_message": None,
                "dagster_terminal_status": None,
                "engine_started_at": None,
                "engine_finished_at": None,
                "success_tracking_invariant": False,
            },
        )
    ).one_or_none()
    if transitioned is None:
        return False
    updated = (
        await session.execute(
            text(_UPDATE_MEMBER_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "member_kind": normalized_kind,
                "member_id": _uuid(member_id),
                "result": "cancelled",
                "terminal_status": "cancelled",
                "error": None,
                "expected_results": ["pending"],
            },
        )
    ).one_or_none()
    if updated is None:
        raise PipelineCancellationInvariantError(
            "queued base transitioned but normalized member result CAS failed"
        )
    await record_system_log(
        session,
        level="info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.queued_member_cancelled",
        message="queued frozen member cancelled without an external terminate call",
        detail={
            "cancellation_id": cancellation_id,
            "member_kind": normalized_kind,
            "member_id": member_id,
        },
    )
    return True


async def finish_pipeline_cancellation_attempt(
    session: AsyncSession,
    *,
    cancellation_id: str,
    status: str,
    error: Mapping[str, Any] | None,
) -> PipelineCancellationDetail | None:
    """잠근 frozen detail/base 전체를 검증한 뒤 attempt를 종결한다."""
    if status not in PIPELINE_CANCELLATION_STATUS_VALUES or status == "in_progress":
        raise ValueError("terminal attempt status must be retryable, completed, or failed")
    normalized_status = cast(PipelineCancellationStatus, status)
    locked_attempt = await _lock_attempt_after_root(session, cancellation_id)
    if locked_attempt is None or locked_attempt.status != "in_progress":
        return None
    detail = await get_pipeline_cancellation_detail(session, cancellation_id)
    if detail is None:
        raise PipelineCancellationInvariantError("cancellation attempt disappeared")
    base_by_key = await _lock_detail_base_members(session, detail)
    _validate_finish_invariants(
        detail,
        base_by_key,
        status=normalized_status,
        error=error,
    )
    row = (
        await session.execute(
            text(_FINISH_ATTEMPT_SQL),
            {
                "cancellation_id": _uuid(cancellation_id),
                "status": normalized_status,
                "error": json.dumps(dict(error)) if error is not None else None,
            },
        )
    ).one_or_none()
    if row is None:
        return None
    await record_system_log(
        session,
        level="error" if normalized_status == "failed" else "info",
        source="pipeline_cancellation",
        event="pipeline.cancellation.finished",
        message="pipeline cancellation attempt finished",
        detail={
            "cancellation_id": cancellation_id,
            "status": normalized_status,
        },
    )
    detail = await get_pipeline_cancellation_detail(session, cancellation_id)
    if detail is None:
        raise PipelineCancellationInvariantError("finished cancellation attempt is missing")
    return detail


__all__ = [
    "PipelineCancellationAttempt",
    "PipelineCancellationConflict",
    "PipelineCancellationDetail",
    "PipelineCancellationInvariantError",
    "PipelineCancellationTimelineConflict",
    "PipelineCancellationMember",
    "PipelineCancellationRun",
    "PipelineCancellationScope",
    "PipelineCancellationScopeMember",
    "PipelineCancellationSummary",
    "cancel_queued_pipeline_cancellation_member",
    "create_pipeline_cancellation_attempt",
    "finish_pipeline_cancellation_attempt",
    "fill_pipeline_cancellation_canonical_starts",
    "get_current_pipeline_cancellation_detail",
    "get_current_pipeline_cancellation_summary",
    "get_pipeline_cancellation_detail",
    "lock_pipeline_cancellation_root",
    "lock_pipeline_hierarchy_for_jobs",
    "lock_pipeline_lineage_mutation",
    "mark_pipeline_cancellation_run_termination_reserved",
    "pipeline_cancellation_root_lock_key",
    "resolve_pipeline_cancellation_scope",
    "retry_pipeline_cancellation_attempt",
    "set_pipeline_cancellation_member_result",
    "set_pipeline_cancellation_run_result",
    "transition_pipeline_cancellation_member",
]
