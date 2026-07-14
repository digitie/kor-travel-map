"""Pipeline 계층형 취소의 DB-only scope/attempt/member/run repository.

C3b와 같은 lineage CTE를 공유해 request branch와 standalone partition을 한 번만
동결한다. 외부 Dagster 호출과 HTTP 의미는 상위 application 계층 책임이다. 모든
함수는 commit하지 않으며 호출자가 transaction을 소유한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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
from kortravelmap.infra.pipeline_lineage import PIPELINE_LINEAGE_CTES_SQL

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

_BASE_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_PIPELINE_LINEAGE_MUTATION_LOCK_KEY = "kortravelmap:pipeline-lineage:mutation"


@dataclass(frozen=True)
class PipelineCancellationSummary:
    """목록 root에 붙는 current cancellation DB overlay."""

    cancellation_id: str
    status: PipelineCancellationStatus
    requested_at: datetime
    requested_by: str
    reason: str | None
    retryable: bool
    unresolved_member_count: int


@dataclass(frozen=True)
class PipelineCancellationAttempt:
    """``ops.pipeline_cancellations`` attempt 1행."""

    cancellation_id: str
    previous_cancellation_id: str | None
    root_kind: PipelineCancellationMemberKind
    root_id: str
    status: PipelineCancellationStatus
    requested_by: str
    reason: str | None
    error: dict[str, Any] | None
    requested_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @property
    def retryable(self) -> bool:
        return self.status == "retryable"


@dataclass(frozen=True)
class PipelineCancellationMember:
    """frozen request/job 대상과 대상별 결과."""

    cancellation_id: str
    member_kind: PipelineCancellationMemberKind
    member_id: str
    dagster_run_id: str | None
    initial_status: str
    result: PipelineCancellationResult
    terminal_status: str | None
    error: dict[str, Any] | None
    updated_at: datetime


@dataclass(frozen=True)
class PipelineCancellationRun:
    """attempt당 한 번만 처리할 Dagster run."""

    cancellation_id: str
    dagster_run_id: str
    initial_status: str | None
    result: PipelineCancellationResult
    terminal_status: str | None
    error: dict[str, Any] | None
    updated_at: datetime


@dataclass(frozen=True)
class PipelineCancellationDetail:
    """reload 가능한 current attempt + member/run 전체 결과."""

    attempt: PipelineCancellationAttempt
    members: tuple[PipelineCancellationMember, ...]
    runs: tuple[PipelineCancellationRun, ...]

    @property
    def unresolved_member_count(self) -> int:
        return sum(
            member.result in {"pending", "cancel_failed"}
            for member in self.members
        )


@dataclass(frozen=True)
class PipelineCancellationScopeMember:
    """marker 직전 C3b parity scope의 base row snapshot."""

    member_kind: PipelineCancellationMemberKind
    member_id: str
    initial_status: str
    dagster_run_id: str | None
    cancellation_id: str | None

    @property
    def active(self) -> bool:
        return self.initial_status in {"queued", "running"}


@dataclass(frozen=True)
class PipelineCancellationScope:
    """canonical root와 deterministic frozen member 목록."""

    root_kind: PipelineCancellationMemberKind
    root_id: str
    members: tuple[PipelineCancellationScopeMember, ...]

    @property
    def active_members(self) -> tuple[PipelineCancellationScopeMember, ...]:
        return tuple(member for member in self.members if member.active)


class PipelineCancellationConflict(RuntimeError):
    """marker 또는 current attempt CAS가 더 이상 일치하지 않는다."""


class PipelineCancellationInvariantError(RuntimeError):
    """attempt workflow/result 불변식을 만족하지 않는다."""


_RESOLVE_SCOPE_SQL = "WITH RECURSIVE\n" + PIPELINE_LINEAGE_CTES_SQL + """,
input_request AS (
    SELECT request.request_id
    FROM ops.feature_update_requests AS request
    WHERE CAST(:kind AS text) = 'update_request'
      AND request.request_id = CAST(:execution_id AS uuid)
),
input_job AS (
    SELECT
        component.job_id,
        component.component_root_id,
        owner.owner_request_id
    FROM job_components AS component
    LEFT JOIN job_owners AS owner ON owner.job_id = component.job_id
    WHERE CAST(:kind AS text) = 'import_job'
      AND component.job_id = CAST(:execution_id AS uuid)
),
canonical_root AS (
    SELECT
        'update_request'::text AS root_kind,
        request.request_id AS root_id
    FROM input_request AS request
    UNION ALL
    SELECT
        CASE WHEN job.owner_request_id IS NULL
          THEN 'import_job'::text ELSE 'update_request'::text END AS root_kind,
        COALESCE(job.owner_request_id, job.component_root_id) AS root_id
    FROM input_job AS job
),
scope_members AS (
    SELECT
        'update_request'::text AS member_kind,
        request.request_id AS member_id,
        request.status AS initial_status,
        request.dagster_run_id,
        request.cancellation_id
    FROM canonical_root AS root
    JOIN ops.feature_update_requests AS request
      ON root.root_kind = 'update_request'
     AND request.request_id = root.root_id
    UNION ALL
    SELECT
        'import_job'::text AS member_kind,
        job.job_id AS member_id,
        job.status AS initial_status,
        job.dagster_run_id,
        job.cancellation_id
    FROM canonical_root AS root
    JOIN job_owners AS owner
      ON root.root_kind = 'update_request'
     AND owner.owner_request_id = root.root_id
    JOIN ops.import_jobs AS job ON job.job_id = owner.job_id
    UNION ALL
    SELECT
        'import_job'::text AS member_kind,
        job.job_id AS member_id,
        job.status AS initial_status,
        job.dagster_run_id,
        job.cancellation_id
    FROM canonical_root AS root
    JOIN standalone_jobs AS standalone
      ON root.root_kind = 'import_job'
     AND standalone.component_root_id = root.root_id
    JOIN ops.import_jobs AS job ON job.job_id = standalone.job_id
)
SELECT
    root.root_kind,
    root.root_id,
    member.member_kind,
    member.member_id,
    member.initial_status,
    member.dagster_run_id,
    member.cancellation_id
FROM canonical_root AS root
JOIN scope_members AS member ON true
ORDER BY member.member_kind, member.member_id
"""

_CURRENT_ATTEMPT_SQL = """
SELECT
    attempt.cancellation_id,
    attempt.previous_cancellation_id,
    attempt.root_kind,
    attempt.root_id,
    attempt.status,
    attempt.requested_by,
    attempt.reason,
    attempt.error,
    attempt.requested_at,
    attempt.updated_at,
    attempt.finished_at,
    (
      SELECT COUNT(*)::integer
      FROM ops.pipeline_cancellation_members AS member
      WHERE member.cancellation_id = attempt.cancellation_id
        AND member.result IN ('pending', 'cancel_failed')
    ) AS unresolved_member_count
FROM ops.pipeline_cancellations AS attempt
WHERE attempt.root_kind = CAST(:root_kind AS text)
  AND attempt.root_id = CAST(:root_id AS uuid)
ORDER BY
    (attempt.status = 'in_progress') DESC,
    attempt.requested_at DESC,
    attempt.cancellation_id DESC
LIMIT 1
"""

_ATTEMPT_SQL = """
SELECT
    cancellation_id,
    previous_cancellation_id,
    root_kind,
    root_id,
    status,
    requested_by,
    reason,
    error,
    requested_at,
    updated_at,
    finished_at
FROM ops.pipeline_cancellations
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
"""

_MEMBERS_SQL = """
SELECT
    cancellation_id,
    member_kind,
    member_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_members
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
ORDER BY member_kind, member_id
"""

_RUNS_SQL = """
SELECT
    cancellation_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_runs
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
ORDER BY dagster_run_id
"""

_INSERT_ATTEMPT_SQL = """
INSERT INTO ops.pipeline_cancellations (
    cancellation_id,
    previous_cancellation_id,
    root_kind,
    root_id,
    status,
    requested_by,
    reason,
    finished_at
) VALUES (
    CAST(:cancellation_id AS uuid),
    CAST(:previous_cancellation_id AS uuid),
    :root_kind,
    CAST(:root_id AS uuid),
    :status,
    :requested_by,
    :reason,
    CASE WHEN :status = 'in_progress' THEN NULL ELSE now() END
)
"""

_INSERT_RUN_SQL = """
INSERT INTO ops.pipeline_cancellation_runs (
    cancellation_id,
    dagster_run_id,
    result
) VALUES (
    CAST(:cancellation_id AS uuid),
    :dagster_run_id,
    :result
)
"""

_INSERT_MEMBER_SQL = """
INSERT INTO ops.pipeline_cancellation_members (
    cancellation_id,
    member_kind,
    member_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status
) VALUES (
    CAST(:cancellation_id AS uuid),
    :member_kind,
    CAST(:member_id AS uuid),
    :dagster_run_id,
    :initial_status,
    :result,
    :terminal_status
)
"""

_MARK_JOBS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
UPDATE ops.import_jobs AS job
SET cancellation_id = CAST(:cancellation_id AS uuid),
    cancellation_requested_at = now(),
    cancellation_requested_by = :requested_by,
    cancellation_reason = :reason
WHERE job.job_id IN (SELECT member_id FROM members)
  AND (
    (CAST(:expected_cancellation_id AS uuid) IS NULL AND job.cancellation_id IS NULL)
    OR job.cancellation_id = CAST(:expected_cancellation_id AS uuid)
  )
RETURNING job.job_id
"""

_MARK_REQUESTS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
UPDATE ops.feature_update_requests AS request
SET cancellation_id = CAST(:cancellation_id AS uuid),
    cancellation_requested_at = now(),
    cancellation_requested_by = :requested_by,
    cancellation_reason = :reason
WHERE request.request_id IN (SELECT member_id FROM members)
  AND (
    (CAST(:expected_cancellation_id AS uuid) IS NULL
      AND request.cancellation_id IS NULL)
    OR request.cancellation_id = CAST(:expected_cancellation_id AS uuid)
  )
RETURNING request.request_id
"""

_UPDATE_MEMBER_SQL = """
UPDATE ops.pipeline_cancellation_members
SET result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND member_kind = :member_kind
  AND member_id = CAST(:member_id AS uuid)
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
"""

_UPDATE_RUN_SQL = """
UPDATE ops.pipeline_cancellation_runs
SET initial_status = COALESCE(:initial_status, initial_status),
    result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND dagster_run_id = :dagster_run_id
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
"""

_FINISH_ATTEMPT_SQL = """
UPDATE ops.pipeline_cancellations AS attempt
SET status = :status,
    error = CAST(:error AS jsonb),
    updated_at = now(),
    finished_at = now()
WHERE attempt.cancellation_id = CAST(:cancellation_id AS uuid)
  AND attempt.status = 'in_progress'
  AND (
    :status <> 'completed'
    OR (
      NOT EXISTS (
        SELECT 1
        FROM ops.pipeline_cancellation_members AS member
        WHERE member.cancellation_id = attempt.cancellation_id
          AND member.result NOT IN ('cancelled', 'already_terminal')
      )
      AND NOT EXISTS (
        SELECT 1
        FROM ops.pipeline_cancellation_runs AS run
        WHERE run.cancellation_id = attempt.cancellation_id
          AND run.result NOT IN ('cancelled', 'already_terminal')
      )
    )
  )
RETURNING attempt.cancellation_id
"""

_LOCK_REQUEST_MEMBERS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
SELECT
    'update_request'::text AS member_kind,
    request.request_id AS member_id,
    request.status AS initial_status,
    request.dagster_run_id,
    request.cancellation_id
FROM ops.feature_update_requests AS request
WHERE request.request_id IN (SELECT member_id FROM members)
ORDER BY request.request_id
FOR UPDATE
"""

_LOCK_JOB_MEMBERS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
SELECT
    'import_job'::text AS member_kind,
    job.job_id AS member_id,
    job.status AS initial_status,
    job.dagster_run_id,
    job.cancellation_id
FROM ops.import_jobs AS job
WHERE job.job_id IN (SELECT member_id FROM members)
ORDER BY job.job_id
FOR UPDATE
"""

_TRANSITION_REQUEST_MEMBER_SQL = """
UPDATE ops.feature_update_requests
SET status = :target_status,
    error_message = COALESCE(:error_message, error_message),
    finished_at = now(),
    updated_at = now()
WHERE request_id = CAST(:member_id AS uuid)
  AND cancellation_id = CAST(:cancellation_id AS uuid)
  AND status = :expected_status
  AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
RETURNING request_id
"""

_TRANSITION_JOB_MEMBER_SQL = """
UPDATE ops.import_jobs
SET status = :target_status,
    error_message = COALESCE(:error_message, error_message),
    finished_at = now(),
    heartbeat_at = CASE WHEN status = 'running' THEN now() ELSE heartbeat_at END,
    progress = CASE WHEN :target_status = 'done' THEN 100 ELSE progress END
WHERE job_id = CAST(:member_id AS uuid)
  AND cancellation_id = CAST(:cancellation_id AS uuid)
  AND status = :expected_status
  AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
RETURNING job_id
"""


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
        result=cast(PipelineCancellationResult, str(row.result)),
        terminal_status=row.terminal_status,
        error=_json_dict(row.error),
        updated_at=row.updated_at,
    )


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
                cancellation_id=(
                    str(row.cancellation_id)
                    if row.cancellation_id is not None
                    else None
                ),
            )
            for row in rows
        )
    return tuple(sorted(locked, key=lambda item: (item.member_kind, item.member_id)))


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

    member_results = {
        (member.member_kind, member.member_id): cast(
            PipelineCancellationResult,
            "already_terminal"
            if member.initial_status in _BASE_TERMINAL_STATUSES
            else "pending",
        )
        for member in scope.members
    }
    run_results: dict[str, PipelineCancellationResult] = {}
    for member in scope.members:
        if member.dagster_run_id is None:
            continue
        result = member_results[(member.member_kind, member.member_id)]
        if result == "pending":
            run_results[member.dagster_run_id] = "pending"
        else:
            run_results.setdefault(member.dagster_run_id, "already_terminal")
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
                "initial_status": member.initial_status,
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
    previous = await get_pipeline_cancellation_detail(session, previous_id)
    if previous is None:
        raise PipelineCancellationConflict("retry source cancellation attempt is missing")
    if previous.attempt.status != "retryable":
        raise PipelineCancellationConflict("only retryable cancellation can be retried")
    unresolved = tuple(
        member
        for member in previous.members
        if member.result in {"pending", "cancel_failed"}
    )
    if not unresolved:
        raise PipelineCancellationInvariantError(
            "retryable cancellation has no unresolved members"
        )

    await lock_pipeline_lineage_mutation(session)
    await lock_pipeline_cancellation_root(
        session,
        root_kind=previous.attempt.root_kind,
        root_id=previous.attempt.root_id,
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

    requested_members = tuple(
        PipelineCancellationScopeMember(
            member_kind=member.member_kind,
            member_id=member.member_id,
            initial_status=member.initial_status,
            dagster_run_id=member.dagster_run_id,
            cancellation_id=previous_id,
        )
        for member in unresolved
    )
    locked_members = await _lock_scope_members(session, requested_members)
    previous_by_key = {
        (member.member_kind, member.member_id): member for member in unresolved
    }
    for member in locked_members:
        prior = previous_by_key[(member.member_kind, member.member_id)]
        if member.cancellation_id != previous_id:
            raise PipelineCancellationConflict(
                "retry member marker no longer references the source attempt"
            )
        if member.dagster_run_id != prior.dagster_run_id:
            raise PipelineCancellationConflict(
                "retry member Dagster run mapping changed after scope freeze"
            )

    frozen_scope = PipelineCancellationScope(
        root_kind=previous.attempt.root_kind,
        root_id=previous.attempt.root_id,
        members=locked_members,
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
    return cast(PipelineCancellationResult, result)


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
    """동일 attempt의 member 결과를 CAS 갱신하고 같은 tx에 감사를 남긴다."""
    normalized_result = _validate_result(result)
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
    expected_results: Sequence[str] = ("pending", "cancel_failed"),
) -> bool:
    """attempt/run PK로 terminate 결과를 한 번만 CAS 갱신한다."""
    normalized_result = _validate_result(result)
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
) -> bool:
    """marker/run mapping이 정확할 때만 base terminal 상태와 member 결과를 CAS한다."""
    if expected_status not in {"queued", "running"}:
        raise ValueError("expected_status must be queued or running")
    if target_status not in _BASE_TERMINAL_STATUSES:
        raise ValueError("target_status must be done, failed, or cancelled")
    normalized_result = _validate_result(result)
    if normalized_result not in {"cancelled", "already_terminal"}:
        raise ValueError(
            "successful base transition result must be cancelled or already_terminal"
        )
    normalized_kind = _validate_kind(member_kind)
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
                "expected_status": expected_status,
                "target_status": target_status,
                "error_message": error_message,
            },
        )
    ).one_or_none()
    if row is None:
        return False
    updated = await set_pipeline_cancellation_member_result(
        session,
        cancellation_id=cancellation_id,
        member_kind=normalized_kind,
        member_id=member_id,
        result=normalized_result,
        terminal_status=target_status,
        error=None,
    )
    if not updated:
        raise PipelineCancellationInvariantError(
            "base member transitioned but normalized member result CAS failed"
        )
    return True


async def finish_pipeline_cancellation_attempt(
    session: AsyncSession,
    *,
    cancellation_id: str,
    status: str,
    error: Mapping[str, Any] | None,
) -> PipelineCancellationDetail:
    """attempt를 completed/retryable/failed로 닫고 completed invariant를 DB에서 강제한다."""
    if status not in PIPELINE_CANCELLATION_STATUS_VALUES or status == "in_progress":
        raise ValueError("terminal attempt status must be retryable, completed, or failed")
    normalized_status = cast(PipelineCancellationStatus, status)
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
        raise PipelineCancellationInvariantError(
            "attempt status CAS failed or completed attempt has unresolved results"
        )
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
    "PipelineCancellationMember",
    "PipelineCancellationRun",
    "PipelineCancellationScope",
    "PipelineCancellationScopeMember",
    "PipelineCancellationSummary",
    "create_pipeline_cancellation_attempt",
    "finish_pipeline_cancellation_attempt",
    "get_current_pipeline_cancellation_detail",
    "get_current_pipeline_cancellation_summary",
    "get_pipeline_cancellation_detail",
    "lock_pipeline_cancellation_root",
    "lock_pipeline_hierarchy_for_jobs",
    "lock_pipeline_lineage_mutation",
    "pipeline_cancellation_root_lock_key",
    "resolve_pipeline_cancellation_scope",
    "retry_pipeline_cancellation_attempt",
    "set_pipeline_cancellation_member_result",
    "set_pipeline_cancellation_run_result",
    "transition_pipeline_cancellation_member",
]
