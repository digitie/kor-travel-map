"""Dagster provider feature operation 영속화 repository.

모든 함수는 주입된 session의 transaction 안에서만 동작하고 commit하지 않는다.
Provider I/O와 Dagster import는 이 모듈 경계 밖에 둔다.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, cast

from sqlalchemy import text

from kortravelmap.core.feature_operation import (
    DAGSTER_FEATURE_RUN_STATUS_VALUES,
    DAGSTER_FEATURE_TERMINAL_STATUS_VALUES,
    FEATURE_OPERATION_MEMBER_KIND,
    FEATURE_OPERATION_ROOT_KIND,
    TRIGGER_KIND_VALUES,
    DagsterFeatureOperation,
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationMember,
    DagsterFeatureOperationMutation,
    DagsterFeatureOperationPage,
    DagsterFeatureRunStatus,
    ExecutionState,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
    TriggerKind,
)
from kortravelmap.infra.jobs_repo import ImportJobEvent, record_import_job_event
from kortravelmap.infra.log_repo import record_system_log
from kortravelmap.infra.pipeline_cancellation_repo import (
    lock_pipeline_cancellation_root,
    lock_pipeline_lineage_mutation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "append_dagster_feature_attempt_event",
    "ensure_dagster_feature_operation",
    "finish_dagster_feature_membership",
    "list_reconcilable_dagster_feature_runs",
    "list_feature_operation_memberships",
    "resolve_feature_operation_memberships",
    "resolve_feature_operation_dataset_membership",
    "reconcile_dagster_feature_run",
    "record_feature_operation_invariant_conflict",
]

_QUEUED_DAGSTER_STATUSES: Final[frozenset[str]] = frozenset(
    {"QUEUED", "NOT_STARTED", "MANAGED", "STARTING"}
)
_RUNNING_DAGSTER_STATUSES: Final[frozenset[str]] = frozenset(
    {"STARTED", "CANCELING"}
)
_MAX_RECONCILE_PAGE_SIZE: Final[int] = 200

_ROOT_COLUMNS = """
root.job_id AS root_job_id,
root.dagster_run_id,
root.status AS root_status,
root.dagster_run_status,
root.progress AS root_progress,
root.current_stage AS root_stage,
root.created_at AS root_created_at,
root.started_at AS root_started_at,
root.finished_at AS root_finished_at,
root.trigger_kind,
root.operation_key AS operation_key,
root.cancellation_id AS root_cancellation_id
"""

_LOCK_ROOT_BY_RUN_SQL = f"""
SELECT {_ROOT_COLUMNS}
FROM ops.import_jobs AS root
WHERE root.kind = '{FEATURE_OPERATION_ROOT_KIND}'
  AND root.dagster_run_id = :dagster_run_id
  AND root.quarantined_at IS NULL
FOR UPDATE
"""

_ROOT_WITH_MEMBERS_SQL = f"""
SELECT
  {_ROOT_COLUMNS},
  child.job_id AS child_job_id,
  child_member.import_job_dataset_id AS child_import_job_dataset_id,
  child_member.provider_dataset_id AS child_provider_dataset_id,
  child_member.sync_scope AS child_sync_scope,
  child_member.operation_key AS child_operation_key,
  child.status AS child_status,
  child.progress AS child_progress,
  child.current_stage AS child_stage,
  child.started_at AS child_started_at,
  child.finished_at AS child_finished_at,
  child.cancellation_id AS child_cancellation_id
FROM ops.import_jobs AS root
LEFT JOIN ops.import_jobs AS child
 ON child.parent_job_id = root.job_id
 AND child.kind = '{FEATURE_OPERATION_MEMBER_KIND}'
 AND child.quarantined_at IS NULL
LEFT JOIN ops.import_job_datasets AS child_member
  ON child_member.job_id = child.job_id
WHERE root.kind = '{FEATURE_OPERATION_ROOT_KIND}'
  AND root.dagster_run_id = :dagster_run_id
  AND root.quarantined_at IS NULL
ORDER BY child_member.provider_dataset_id, child_member.sync_scope,
         child_member.operation_key, child.job_id
"""

_INSERT_ROOT_SQL = f"""
INSERT INTO ops.import_jobs (
  kind, payload, status, progress, current_stage, dagster_run_id,
  dataset_membership_mode, trigger_kind, operation_key, dagster_run_status,
  created_at, started_at, heartbeat_at
) VALUES (
  '{FEATURE_OPERATION_ROOT_KIND}', '{{}}'::jsonb, :status, 0, :stage,
  :dagster_run_id, 'root', :trigger_kind, :operation_key, :dagster_run_status,
  CAST(:created_at AS timestamptz), CAST(:started_at AS timestamptz),
  CAST(:started_at AS timestamptz)
)
ON CONFLICT (dagster_run_id)
  WHERE kind = '{FEATURE_OPERATION_ROOT_KIND}' AND parent_job_id IS NULL
DO NOTHING
RETURNING job_id
"""

_INSERT_MEMBER_SQL = f"""
WITH child AS (
  INSERT INTO ops.import_jobs (
    kind, parent_job_id, payload, status, progress, current_stage,
    dagster_run_id, dataset_membership_mode, created_at, started_at, heartbeat_at
  ) VALUES (
    '{FEATURE_OPERATION_MEMBER_KIND}', CAST(:root_job_id AS uuid), '{{}}'::jsonb,
    :status, 0, :stage, :dagster_run_id, 'single',
    CAST(:created_at AS timestamptz), CAST(:started_at AS timestamptz),
    CAST(:started_at AS timestamptz)
  )
  RETURNING job_id
), membership AS (
  INSERT INTO ops.import_job_datasets (
    job_id, provider_dataset_id, sync_scope, operation_key
  )
  SELECT child.job_id, CAST(:provider_dataset_id AS bigint), :sync_scope, :operation_key
  FROM child
  RETURNING job_id
)
SELECT child.job_id FROM child JOIN membership USING (job_id)
"""

_ADVANCE_ROOT_SQL = """
UPDATE ops.import_jobs
SET status = 'running',
    current_stage = 'loading',
    dagster_run_status = :dagster_run_status,
    started_at = COALESCE(started_at, CAST(:started_at AS timestamptz)),
    heartbeat_at = COALESCE(CAST(:started_at AS timestamptz), heartbeat_at)
WHERE job_id = CAST(:root_job_id AS uuid)
  AND kind = 'provider_feature_load_run'
  AND status = 'queued'
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
RETURNING job_id
"""

_ADVANCE_MEMBERS_SQL = """
UPDATE ops.import_jobs
SET status = 'running',
    current_stage = 'loading',
    started_at = COALESCE(started_at, CAST(:started_at AS timestamptz)),
    heartbeat_at = COALESCE(CAST(:started_at AS timestamptz), heartbeat_at)
WHERE parent_job_id = CAST(:root_job_id AS uuid)
  AND kind = 'provider_feature_load'
  AND status = 'queued'
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
RETURNING job_id
"""

_ADVANCE_RAW_QUEUED_STATUS_SQL = """
UPDATE ops.import_jobs
SET dagster_run_status = :dagster_run_status
WHERE job_id = CAST(:root_job_id AS uuid)
  AND kind = 'provider_feature_load_run'
  AND status = 'queued'
  AND dagster_run_status IN ('QUEUED','NOT_STARTED','MANAGED')
  AND :dagster_run_status = 'STARTING'
  AND quarantined_at IS NULL
RETURNING job_id
"""

_ADVANCE_RAW_CANCELING_STATUS_SQL = """
UPDATE ops.import_jobs
SET dagster_run_status = 'CANCELING'
WHERE job_id = CAST(:root_job_id AS uuid)
  AND kind = 'provider_feature_load_run'
  AND status = 'running'
  AND dagster_run_status = 'STARTED'
  AND :dagster_run_status = 'CANCELING'
  AND quarantined_at IS NULL
RETURNING job_id
"""

_FINISH_MEMBERSHIP_SQL = """
UPDATE ops.import_jobs
SET status = 'done',
    progress = 100,
    current_stage = 'completed',
    finished_at = COALESCE(finished_at, now()),
    heartbeat_at = now(),
    error_message = NULL
WHERE parent_job_id = CAST(:root_job_id AS uuid)
  AND kind = 'provider_feature_load'
  AND EXISTS (
    SELECT 1 FROM ops.import_job_datasets AS member
    WHERE member.job_id = ops.import_jobs.job_id
      AND member.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
      AND member.sync_scope = :sync_scope
      AND member.operation_key = :operation_key
  )
  AND status IN ('queued','running')
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
RETURNING job_id
"""

_UPDATE_ROOT_PROGRESS_SQL = """
WITH counts AS (
  SELECT
    count(*)::integer AS total,
    count(*) FILTER (WHERE status = 'done')::integer AS done
  FROM ops.import_jobs
  WHERE parent_job_id = CAST(:root_job_id AS uuid)
    AND kind = 'provider_feature_load'
    AND quarantined_at IS NULL
)
UPDATE ops.import_jobs AS root
SET progress = CASE WHEN counts.total = 0 THEN 0
                    ELSE floor(100.0 * counts.done / counts.total)::integer END
FROM counts
WHERE root.job_id = CAST(:root_job_id AS uuid)
  AND root.quarantined_at IS NULL
RETURNING root.job_id
"""

_ACTIVE_ROOTS_PAGE_SQL = f"""
SELECT root.dagster_run_id
FROM ops.import_jobs AS root
WHERE root.kind = '{FEATURE_OPERATION_ROOT_KIND}'
  AND root.parent_job_id IS NULL
  AND root.status IN ('queued','running')
  AND root.cancellation_id IS NULL
  AND root.quarantined_at IS NULL
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (root.created_at, root.job_id) > (
      CAST(:cursor_created_at AS timestamptz), CAST(:cursor_root_job_id AS uuid)
    )
  )
ORDER BY root.created_at ASC, root.job_id ASC
LIMIT :limit_plus_one
"""

_OPERATION_MEMBERSHIPS_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE operation.operation_key = :operation_key
  AND operation.operation_kind = 'refresh'
  AND operation.is_enabled
  AND dataset.is_active
ORDER BY scope.provider_dataset_id, scope.sync_scope
"""

_OPERATION_DATASET_MEMBERSHIP_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE operation.operation_key = :operation_key
  AND operation.operation_kind = 'refresh'
  AND operation.is_enabled
  AND dataset.is_active
  AND dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND (
    CAST(:sync_scope AS text) IS NULL
    OR scope.sync_scope = CAST(:sync_scope AS text)
  )
ORDER BY scope.sync_scope
"""


def _aware(
    value: datetime | None,
    *,
    name: str,
    dagster_run_id: str,
) -> datetime:
    if value is None:
        raise FeatureOperationInvariantConflict(
            f"{name} is required",
            dagster_run_id=dagster_run_id,
            details={"timestamp": name, "reason": "missing"},
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureOperationInvariantConflict(
            f"{name} must be timezone-aware",
            dagster_run_id=dagster_run_id,
            details={"timestamp": name, "reason": "timezone_naive"},
        )
    return value


def _run_id(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("dagster_run_id must be trimmed and non-empty")
    return value


def _operation_key(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("operation_key must be trimmed and non-empty")
    return value


def _validate_engine_timeline(
    *,
    dagster_run_id: str,
    created_at: datetime,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> None:
    if started_at is not None and started_at < created_at:
        raise FeatureOperationInvariantConflict(
            "Dagster engine start time precedes create time",
            dagster_run_id=dagster_run_id,
            details={
                "engine_created_at": created_at.isoformat(),
                "engine_started_at": started_at.isoformat(),
            },
        )
    if finished_at is not None and finished_at < created_at:
        raise FeatureOperationInvariantConflict(
            "Dagster engine finish time precedes create time",
            dagster_run_id=dagster_run_id,
            details={
                "engine_created_at": created_at.isoformat(),
                "engine_finished_at": finished_at.isoformat(),
            },
        )
    if (
        started_at is not None
        and finished_at is not None
        and finished_at < started_at
    ):
        raise FeatureOperationInvariantConflict(
            "Dagster engine finish time precedes start time",
            dagster_run_id=dagster_run_id,
            details={
                "engine_started_at": started_at.isoformat(),
                "engine_finished_at": finished_at.isoformat(),
            },
        )


def _memberships(
    values: Sequence[ProviderDatasetOperationMembership],
) -> tuple[ProviderDatasetOperationMembership, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized:
        raise ValueError("selected_memberships must not be empty")
    return normalized


def _require_operation_memberships(
    memberships: Sequence[ProviderDatasetOperationMembership],
    *,
    operation_key: str,
) -> tuple[ProviderDatasetOperationMembership, ...]:
    """run root의 operation과 member snapshot을 같은 exact key로 묶는다."""
    normalized = _memberships(memberships)
    mismatched = [
        member
        for member in normalized
        if member.operation_key != operation_key
    ]
    if mismatched:
        raise ValueError("selected_memberships must use the root operation_key")
    return normalized


def _validate_trigger(value: str) -> TriggerKind:
    if value not in TRIGGER_KIND_VALUES:
        raise ValueError(f"invalid trigger_kind: {value}")
    return value


def _validate_run_status(value: str) -> DagsterFeatureRunStatus:
    if value not in DAGSTER_FEATURE_RUN_STATUS_VALUES:
        raise ValueError(f"invalid Dagster feature run status: {value}")
    return value


async def list_feature_operation_memberships(
    session: AsyncSession,
    *,
    operation_key: str,
) -> tuple[ProviderDatasetOperationMembership, ...]:
    """enabled DB operation key의 canonical member snapshot을 읽는다."""
    rows = (
        await session.execute(
            text(_OPERATION_MEMBERSHIPS_SQL),
            {"operation_key": _operation_key(operation_key)},
        )
    ).all()
    return tuple(
        ProviderDatasetOperationMembership(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        )
        for row in rows
    )


async def resolve_feature_operation_memberships(
    session: AsyncSession,
    *,
    operation_key: str,
) -> tuple[ProviderDatasetOperationMembership, ...]:
    """scheduled dispatch 전에 active operation의 exact membership을 고정한다.

    반환값은 provider/dataset 표시 자연키가 아닌
    ``provider_dataset_id + sync_scope + operation_key``뿐이다. 호출자는 이
    snapshot을 resource로 주입한 뒤 sync-state write와 handler dispatch에 그대로
    사용해야 하며, 실행 중 자연키를 다시 해석해서는 안 된다.
    """
    return await list_feature_operation_memberships(
        session,
        operation_key=operation_key,
    )


async def resolve_feature_operation_dataset_membership(
    session: AsyncSession,
    *,
    operation_key: str,
    provider: str,
    dataset_key: str,
    sync_scope: str | None = None,
) -> ProviderDatasetOperationMembership:
    """runtime source key를 frozen canonical member로 해석한다.

    이 lookup은 provider callback 경계에서만 사용하며, 자연키를 operation event나
    root/child identity에 저장하지 않는다.

    ``sync_scope``를 주지 않으면 ``(operation_key, provider, dataset_key)``가 정확히
    한 scope 행으로 떨어져야 한다. 그 전제는 카탈로그의 일반 성질이 아니다 —
    ``0089_tvn33_expand_seed``는 ``target_grids`` dataset에 ``dataset_wide``까지
    함께 seed하므로 KMA 격자 dataset 3종은 dataset당 scope가 2개다. 그런 dataset을
    지목하려면 triple의 남은 축인 ``sync_scope``까지 넘겨야 하며, 그때만 exact
    lookup이 성립한다.
    """
    rows = (
        await session.execute(
            text(_OPERATION_DATASET_MEMBERSHIP_SQL),
            {
                "operation_key": _operation_key(operation_key),
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    ).all()
    if len(rows) != 1:
        raise FeatureOperationInvariantConflict(
            "runtime dataset does not resolve to exactly one operation membership",
            dagster_run_id="unknown",
            details={
                "operation_key": operation_key,
                "sync_scope": sync_scope,
                "match_count": len(rows),
            },
        )
    row = rows[0]
    return ProviderDatasetOperationMembership(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


def _operation(rows: Sequence[Any]) -> DagsterFeatureOperation:
    if not rows:
        raise FeatureOperationInvariantConflict(
            "provider feature operation disappeared",
            dagster_run_id="unknown",
        )
    root = rows[0]
    members = tuple(
        DagsterFeatureOperationMember(
            job_id=str(row.child_job_id),
            import_job_dataset_id=str(row.child_import_job_dataset_id),
            membership=ProviderDatasetOperationMembership(
                provider_dataset_id=int(row.child_provider_dataset_id),
                sync_scope=str(row.child_sync_scope),
                operation_key=str(row.child_operation_key),
            ),
            status=cast(ExecutionState, str(row.child_status)),
            progress=int(row.child_progress),
            current_stage=row.child_stage,
            started_at=row.child_started_at,
            finished_at=row.child_finished_at,
        )
        for row in rows
        if row.child_job_id is not None
    )
    return DagsterFeatureOperation(
        root_job_id=str(root.root_job_id),
        dagster_run_id=str(root.dagster_run_id),
        status=cast(ExecutionState, str(root.root_status)),
        dagster_run_status=_validate_run_status(str(root.dagster_run_status)),
        progress=int(root.root_progress),
        current_stage=root.root_stage,
        created_at=root.root_created_at,
        started_at=root.root_started_at,
        finished_at=root.root_finished_at,
        trigger_kind=_validate_trigger(str(root.trigger_kind)),
        operation_key=str(root.operation_key),
        members=members,
    )


async def _load_operation(
    session: AsyncSession, dagster_run_id: str
) -> DagsterFeatureOperation:
    rows = (
        await session.execute(
            text(_ROOT_WITH_MEMBERS_SQL), {"dagster_run_id": dagster_run_id}
        )
    ).all()
    if not rows:
        raise FeatureOperationInvariantConflict(
            "provider feature operation root is missing",
            dagster_run_id=dagster_run_id,
        )
    return _operation(rows)


def _raise_identity_conflict(
    operation: DagsterFeatureOperation,
    *,
    trigger_kind: TriggerKind,
    operation_key: str,
    selected_memberships: tuple[ProviderDatasetOperationMembership, ...],
    engine_created_at: datetime,
    engine_started_at: datetime | None,
) -> None:
    stored_memberships = tuple(member.membership for member in operation.members)
    mismatches: dict[str, Any] = {}
    if operation.trigger_kind != trigger_kind:
        mismatches["trigger_kind"] = {
            "expected": trigger_kind,
            "actual": operation.trigger_kind,
        }
    if operation.operation_key != operation_key:
        mismatches["operation_key"] = {
            "expected": operation_key,
            "actual": operation.operation_key,
        }
    if operation.created_at != engine_created_at:
        mismatches["engine_created_at"] = {
            "expected": engine_created_at.isoformat(),
            "actual": operation.created_at.isoformat(),
        }
    if (
        engine_started_at is not None
        and operation.started_at is not None
        and operation.started_at != engine_started_at
    ):
        mismatches["engine_started_at"] = {
            "expected": engine_started_at.isoformat(),
            "actual": operation.started_at.isoformat(),
        }
    if stored_memberships != selected_memberships:
        mismatches["selected_memberships"] = {
            "expected": [
                {
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                }
                for member in selected_memberships
            ],
            "actual": [
                {
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                }
                for member in stored_memberships
            ],
        }
    if mismatches:
        raise FeatureOperationInvariantConflict(
            "provider feature operation identity/selection changed",
            dagster_run_id=operation.dagster_run_id,
            root_job_id=operation.root_job_id,
            details=mismatches,
        )


async def ensure_dagster_feature_operation(
    session: AsyncSession,
    *,
    dagster_run_id: str,
    trigger_kind: str,
    selected_memberships: Sequence[ProviderDatasetOperationMembership],
    operation_key: str,
    engine_created_at: datetime,
    engine_started_at: datetime | None,
    observed_status: str,
) -> DagsterFeatureOperationMutation:
    """권위 있는 run selection 전체를 한 transaction에서 생성/전진한다."""
    normalized_run_id = _run_id(dagster_run_id)
    normalized_trigger = _validate_trigger(trigger_kind)
    normalized_operation_key = _operation_key(operation_key)
    normalized_memberships = _require_operation_memberships(
        selected_memberships,
        operation_key=normalized_operation_key,
    )
    created_at = _aware(
        engine_created_at,
        name="engine_created_at",
        dagster_run_id=normalized_run_id,
    )
    started_at = (
        _aware(
            engine_started_at,
            name="engine_started_at",
            dagster_run_id=normalized_run_id,
        )
        if engine_started_at is not None
        else None
    )
    status = _validate_run_status(observed_status)
    if status in DAGSTER_FEATURE_TERMINAL_STATUS_VALUES:
        raise ValueError("ensure only accepts non-terminal observed_status")
    if status in _RUNNING_DAGSTER_STATUSES and started_at is None:
        raise FeatureOperationInvariantConflict(
            "running observed_status requires engine_started_at",
            dagster_run_id=normalized_run_id,
            details={"timestamp": "engine_started_at", "reason": "missing"},
        )
    _validate_engine_timeline(
        dagster_run_id=normalized_run_id,
        created_at=created_at,
        started_at=started_at,
        finished_at=None,
    )

    await lock_pipeline_lineage_mutation(session)
    root_row = (
        await session.execute(
            text(_LOCK_ROOT_BY_RUN_SQL), {"dagster_run_id": normalized_run_id}
        )
    ).one_or_none()
    inserted = False
    if root_row is None:
        base_status = "queued" if status in _QUEUED_DAGSTER_STATUSES else "running"
        stage = "queued" if base_status == "queued" else "loading"
        row = (
            await session.execute(
                text(_INSERT_ROOT_SQL),
                {
                    "status": base_status,
                    "stage": stage,
                    "dagster_run_id": normalized_run_id,
                    "trigger_kind": normalized_trigger,
                    "operation_key": normalized_operation_key,
                    "dagster_run_status": status,
                    "created_at": created_at,
                    "started_at": started_at if base_status == "running" else None,
                },
            )
        ).one_or_none()
        inserted = row is not None
        root_row = (
            await session.execute(
                text(_LOCK_ROOT_BY_RUN_SQL), {"dagster_run_id": normalized_run_id}
            )
        ).one_or_none()
        if root_row is None:
            raise FeatureOperationInvariantConflict(
                "Dagster run belongs to a quarantined provider feature operation",
                dagster_run_id=normalized_run_id,
                details={"reason": "quarantined"},
            )
    root_job_id = str(root_row.root_job_id)
    await lock_pipeline_cancellation_root(
        session, root_kind="import_job", root_id=root_job_id
    )

    if inserted:
        member_status = "queued" if status in _QUEUED_DAGSTER_STATUSES else "running"
        member_stage = "queued" if member_status == "queued" else "loading"
        for membership in normalized_memberships:
            await session.execute(
                text(_INSERT_MEMBER_SQL),
                {
                    "root_job_id": root_job_id,
                    "status": member_status,
                    "stage": member_stage,
                    "dagster_run_id": normalized_run_id,
                    "provider_dataset_id": membership.provider_dataset_id,
                    "sync_scope": membership.sync_scope,
                    "operation_key": membership.operation_key,
                    "created_at": created_at,
                    "started_at": started_at if member_status == "running" else None,
                },
            )

    operation = await _load_operation(session, normalized_run_id)
    _raise_identity_conflict(
        operation,
        trigger_kind=normalized_trigger,
        operation_key=normalized_operation_key,
        selected_memberships=normalized_memberships,
        engine_created_at=created_at,
        engine_started_at=started_at,
    )
    if root_row.root_cancellation_id is not None or any(
        row.cancellation_id is not None
        for row in (await session.execute(
            text(
                "SELECT cancellation_id FROM ops.import_jobs "
                "WHERE parent_job_id = CAST(:root_job_id AS uuid) "
                "AND quarantined_at IS NULL"
            ),
            {"root_job_id": root_job_id},
        )).all()
    ):
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="cancellation"
        )
    if operation.status in {"done", "failed", "cancelled"}:
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="terminal"
        )

    changed = inserted
    if status in _RUNNING_DAGSTER_STATUSES and operation.status == "queued":
        root_changed = (
            await session.execute(
                text(_ADVANCE_ROOT_SQL),
                {
                    "root_job_id": root_job_id,
                    "dagster_run_status": status,
                    "started_at": started_at,
                },
            )
        ).one_or_none()
        members_changed = (
            await session.execute(
                text(_ADVANCE_MEMBERS_SQL),
                {"root_job_id": root_job_id, "started_at": started_at},
            )
        ).all()
        changed = root_changed is not None or bool(members_changed) or changed
    elif status in _QUEUED_DAGSTER_STATUSES and operation.status == "queued":
        raw_changed = (
            await session.execute(
                text(_ADVANCE_RAW_QUEUED_STATUS_SQL),
                {"root_job_id": root_job_id, "dagster_run_status": status},
            )
        ).one_or_none()
        changed = raw_changed is not None or changed
    elif status == "CANCELING" and operation.status == "running":
        raw_changed = (
            await session.execute(
                text(_ADVANCE_RAW_CANCELING_STATUS_SQL),
                {"root_job_id": root_job_id, "dagster_run_status": status},
            )
        ).one_or_none()
        changed = raw_changed is not None or changed
    operation = await _load_operation(session, normalized_run_id)
    if (
        started_at is not None
        and operation.started_at is not None
        and operation.started_at != started_at
    ):
        raise FeatureOperationInvariantConflict(
            "Dagster engine start time changed during ensure",
            dagster_run_id=normalized_run_id,
            root_job_id=root_job_id,
            details={
                "engine_started_at": {
                    "expected": started_at.isoformat(),
                    "actual": operation.started_at.isoformat(),
                }
            },
        )
    return DagsterFeatureOperationMutation(
        outcome="applied" if changed else "noop", operation=operation
    )


async def finish_dagster_feature_membership(
    session: AsyncSession,
    *,
    dagster_run_id: str,
    membership: ProviderDatasetOperationMembership,
) -> DagsterFeatureOperationMutation:
    normalized_run_id = _run_id(dagster_run_id)
    await lock_pipeline_lineage_mutation(session)
    root = (
        await session.execute(
            text(_LOCK_ROOT_BY_RUN_SQL), {"dagster_run_id": normalized_run_id}
        )
    ).one_or_none()
    if root is None:
        raise FeatureOperationInvariantConflict(
            "provider feature operation root is missing",
            dagster_run_id=normalized_run_id,
        )
    root_job_id = str(root.root_job_id)
    await lock_pipeline_cancellation_root(
        session, root_kind="import_job", root_id=root_job_id
    )
    operation = await _load_operation(session, normalized_run_id)
    if root.root_cancellation_id is not None:
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="cancellation"
        )
    if operation.status in {"done", "failed", "cancelled"}:
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="terminal"
        )
    selected = {member.membership: member for member in operation.members}
    member = selected.get(membership)
    if member is None:
        raise FeatureOperationInvariantConflict(
            "membership is not part of the frozen run selection",
            dagster_run_id=normalized_run_id,
            root_job_id=root_job_id,
            details={
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
        )
    if member.status == "done":
        return DagsterFeatureOperationMutation(outcome="noop", operation=operation)
    changed = (
        await session.execute(
            text(_FINISH_MEMBERSHIP_SQL),
            {
                "root_job_id": root_job_id,
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
        )
    ).one_or_none()
    if changed is None:
        raise FeatureOperationInvariantConflict(
            "membership cannot be completed from its current state",
            dagster_run_id=normalized_run_id,
            root_job_id=root_job_id,
        )
    await session.execute(
        text(_UPDATE_ROOT_PROGRESS_SQL), {"root_job_id": root_job_id}
    )
    return DagsterFeatureOperationMutation(
        outcome="applied",
        operation=await _load_operation(session, normalized_run_id),
    )


async def append_dagster_feature_attempt_event(
    session: AsyncSession,
    *,
    dagster_run_id: str,
    membership: ProviderDatasetOperationMembership,
    attempt_number: int,
    outcome: str,
    error: Mapping[str, Any] | None,
) -> ImportJobEvent:
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    operation = await _load_operation(session, _run_id(dagster_run_id))
    member = next(
        (item for item in operation.members if item.membership == membership), None
    )
    if member is None:
        raise FeatureOperationInvariantConflict(
            "attempt membership is not part of the frozen run selection",
            dagster_run_id=operation.dagster_run_id,
            root_job_id=operation.root_job_id,
        )
    event = await record_import_job_event(
        session,
        member.job_id,
        level="error" if error is not None else "info",
        code="feature_operation.attempt",
        message="provider feature operation attempt recorded",
        payload={
            "attempt_number": attempt_number,
            "outcome": outcome,
            "error": dict(error) if error is not None else None,
            "provider_dataset_id": membership.provider_dataset_id,
            "sync_scope": membership.sync_scope,
            "operation_key": membership.operation_key,
        },
        import_job_dataset_id=member.import_job_dataset_id,
        stage=member.current_stage,
    )
    if event is None:
        raise FeatureOperationInvariantConflict(
            "attempt member disappeared",
            dagster_run_id=operation.dagster_run_id,
            root_job_id=operation.root_job_id,
        )
    return event


async def reconcile_dagster_feature_run(
    session: AsyncSession,
    *,
    dagster_run_id: str,
    trigger_kind: str,
    terminal_status: str,
    selected_memberships: Sequence[ProviderDatasetOperationMembership],
    operation_key: str,
    engine_created_at: datetime,
    engine_started_at: datetime | None,
    engine_finished_at: datetime,
    error: Mapping[str, Any] | None,
) -> DagsterFeatureOperationMutation:
    normalized_run_id = _run_id(dagster_run_id)
    normalized_trigger = _validate_trigger(trigger_kind)
    terminal = _validate_run_status(terminal_status)
    if terminal not in DAGSTER_FEATURE_TERMINAL_STATUS_VALUES:
        raise ValueError("terminal_status must be SUCCESS, FAILURE, or CANCELED")
    created_at = _aware(
        engine_created_at,
        name="engine_created_at",
        dagster_run_id=normalized_run_id,
    )
    started_at = (
        _aware(
            engine_started_at,
            name="engine_started_at",
            dagster_run_id=normalized_run_id,
        )
        if engine_started_at is not None
        else None
    )
    finished_at = _aware(
        engine_finished_at,
        name="engine_finished_at",
        dagster_run_id=normalized_run_id,
    )
    normalized_operation_key = _operation_key(operation_key)
    normalized_memberships = _require_operation_memberships(
        selected_memberships,
        operation_key=normalized_operation_key,
    )
    _validate_engine_timeline(
        dagster_run_id=normalized_run_id,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )

    await lock_pipeline_lineage_mutation(session)
    root = (
        await session.execute(
            text(_LOCK_ROOT_BY_RUN_SQL), {"dagster_run_id": normalized_run_id}
        )
    ).one_or_none()
    if root is None:
        raise FeatureOperationInvariantConflict(
            "terminal reconcile requires an ensured operation root",
            dagster_run_id=normalized_run_id,
        )
    root_job_id = str(root.root_job_id)
    await lock_pipeline_cancellation_root(
        session, root_kind="import_job", root_id=root_job_id
    )
    operation = await _load_operation(session, normalized_run_id)
    if root.root_cancellation_id is not None:
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="cancellation"
        )
    if operation.status in {"done", "failed", "cancelled"}:
        return DagsterFeatureOperationMutation(
            outcome="blocked", operation=operation, block_reason="terminal"
        )
    stored_memberships = tuple(member.membership for member in operation.members)
    mismatches: dict[str, Any] = {}
    if operation.trigger_kind != normalized_trigger:
        mismatches["trigger_kind"] = {
            "expected": normalized_trigger,
            "actual": operation.trigger_kind,
        }
    if operation.operation_key != normalized_operation_key:
        mismatches["operation_key"] = {
            "expected": normalized_operation_key,
            "actual": operation.operation_key,
        }
    if operation.created_at != created_at:
        mismatches["engine_created_at"] = {
            "expected": created_at.isoformat(),
            "actual": operation.created_at.isoformat(),
        }
    if stored_memberships != normalized_memberships:
        mismatches["selected_memberships"] = {
            "expected": [
                {
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                }
                for member in normalized_memberships
            ],
            "actual": [
                {
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                }
                for member in stored_memberships
            ],
        }
    all_stored_starts = (
        operation.started_at,
        *(member.started_at for member in operation.members),
    )
    stored_start_times = tuple(value for value in all_stored_starts if value is not None)
    stored_start_values = set(stored_start_times)
    stored_start_drift = len(stored_start_values) > 1
    incoming_start_drift = started_at is not None and any(
        value != started_at for value in stored_start_times
    )
    if stored_start_drift or incoming_start_drift:
        mismatches["engine_started_at"] = {
            "expected": started_at.isoformat() if started_at is not None else None,
            "actual": [
                value.isoformat() if value is not None else None
                for value in all_stored_starts
            ],
        }
    effective_started_at = (
        started_at
        if started_at is not None
        else next(iter(stored_start_values), None)
    )
    latest_stored_start = max(stored_start_times, default=None)
    finished_before_effective_start = effective_started_at is not None and any(
        member.finished_at is not None and member.finished_at < effective_started_at
        for member in operation.members
    )
    timestamp_conflict = (
        finished_at < operation.created_at
        or (started_at is not None and started_at < operation.created_at)
        or (latest_stored_start is not None and finished_at < latest_stored_start)
        or stored_start_drift
        or incoming_start_drift
        or finished_before_effective_start
    )
    if finished_at < operation.created_at:
        mismatches["engine_finished_at"] = {
            "expected_not_before": operation.created_at.isoformat(),
            "actual": finished_at.isoformat(),
        }
    elif latest_stored_start is not None and finished_at < latest_stored_start:
        mismatches["engine_finished_at"] = {
            "expected_not_before": latest_stored_start.isoformat(),
            "actual": finished_at.isoformat(),
        }
    if started_at is not None and started_at < operation.created_at:
        mismatches.setdefault(
            "engine_started_at",
            {
                "expected_not_before": operation.created_at.isoformat(),
                "actual": started_at.isoformat(),
            },
        )
    if finished_before_effective_start:
        assert effective_started_at is not None
        mismatches["member_finished_at"] = {
            "expected_not_before": effective_started_at.isoformat(),
            "actual": [
                {
                    "job_id": member.job_id,
                    "finished_at": member.finished_at.isoformat(),
                }
                for member in operation.members
                if member.finished_at is not None
                and member.finished_at < effective_started_at
            ],
        }
    persisted_started_at = None if timestamp_conflict else effective_started_at
    persisted_finished_at = None if timestamp_conflict else finished_at
    identity_conflict = bool(mismatches)
    incomplete_members = tuple(
        member for member in operation.members if member.status != "done"
    )
    if identity_conflict or (terminal == "SUCCESS" and incomplete_members):
        target_status = "failed"
        stage = "tracking_invariant"
        error_message = "provider feature operation tracking invariant failed"
    elif terminal == "SUCCESS":
        target_status = "done"
        stage = "completed"
        error_message = None
    elif terminal == "FAILURE":
        target_status = "failed"
        stage = "failed"
        error_message = json.dumps(dict(error), ensure_ascii=False) if error else None
    else:
        target_status = "cancelled"
        stage = "cancelled"
        error_message = json.dumps(dict(error), ensure_ascii=False) if error else None

    if persisted_started_at is not None:
        await session.execute(
            text(
                """
                UPDATE ops.import_jobs
                SET started_at = COALESCE(started_at, CAST(:started_at AS timestamptz))
                WHERE parent_job_id = CAST(:root_job_id AS uuid)
                  AND kind = 'provider_feature_load'
                  AND cancellation_id IS NULL
                  AND quarantined_at IS NULL
                """
            ),
            {
                "started_at": persisted_started_at,
                "root_job_id": root_job_id,
            },
        )
    if terminal != "SUCCESS" or identity_conflict or incomplete_members:
        await session.execute(
            text(
                """
                UPDATE ops.import_jobs
                SET status = :target_status,
                    current_stage = :stage,
                    error_message = COALESCE(:error_message, error_message),
                    finished_at = COALESCE(finished_at, CAST(:finished_at AS timestamptz)),
                    started_at = COALESCE(started_at, CAST(:started_at AS timestamptz)),
                    heartbeat_at = COALESCE(CAST(:finished_at AS timestamptz), heartbeat_at)
                WHERE parent_job_id = CAST(:root_job_id AS uuid)
                  AND kind = 'provider_feature_load'
                  AND status IN ('queued','running')
                  AND cancellation_id IS NULL
                  AND quarantined_at IS NULL
                """
            ),
            {
                "target_status": target_status,
                "stage": stage,
                "error_message": error_message,
                "finished_at": persisted_finished_at,
                "started_at": persisted_started_at,
                "root_job_id": root_job_id,
            },
        )
    await session.execute(
        text(_UPDATE_ROOT_PROGRESS_SQL), {"root_job_id": root_job_id}
    )
    await session.execute(
        text(
            """
            UPDATE ops.import_jobs
            SET status = :target_status,
                dagster_run_status = :dagster_run_status,
                current_stage = :stage,
                error_message = COALESCE(:error_message, error_message),
                progress = CASE WHEN :target_status = 'done' THEN 100 ELSE progress END,
                started_at = COALESCE(started_at, CAST(:started_at AS timestamptz)),
                finished_at = COALESCE(finished_at, CAST(:finished_at AS timestamptz)),
                heartbeat_at = COALESCE(CAST(:finished_at AS timestamptz), heartbeat_at)
            WHERE job_id = CAST(:root_job_id AS uuid)
              AND kind = 'provider_feature_load_run'
              AND status IN ('queued','running')
              AND cancellation_id IS NULL
              AND quarantined_at IS NULL
            """
        ),
        {
            "target_status": target_status,
            "dagster_run_status": terminal,
            "stage": stage,
            "error_message": error_message,
            "started_at": persisted_started_at,
            "finished_at": persisted_finished_at,
            "root_job_id": root_job_id,
        },
    )
    if identity_conflict or (terminal == "SUCCESS" and incomplete_members):
        if terminal == "SUCCESS" and incomplete_members:
            mismatches["non_done_members"] = {
                "expected": 0,
                "actual": [
                    {
                        "job_id": member.job_id,
                        "provider_dataset_id": member.membership.provider_dataset_id,
                        "sync_scope": member.membership.sync_scope,
                        "operation_key": member.membership.operation_key,
                        "status": member.status,
                    }
                    for member in incomplete_members
                ],
            }
        await record_system_log(
            session,
            level="error",
            source="feature_operation",
            event="feature_operation.tracking_invariant",
            message="terminal Dagster run failed canonical tracking invariants",
            detail={
                "dagster_run_id": normalized_run_id,
                "root_job_id": root_job_id,
                "terminal_status": terminal,
                "mismatches": mismatches,
            },
        )
    return DagsterFeatureOperationMutation(
        outcome="applied",
        operation=await _load_operation(session, normalized_run_id),
    )


async def list_reconcilable_dagster_feature_runs(
    session: AsyncSession,
    *,
    cursor: DagsterFeatureOperationCursor | None,
    page_size: int,
) -> DagsterFeatureOperationPage:
    limit = max(1, min(int(page_size), _MAX_RECONCILE_PAGE_SIZE))
    rows = (
        await session.execute(
            text(_ACTIVE_ROOTS_PAGE_SQL),
            {
                "cursor_created_at": cursor.created_at if cursor else None,
                "cursor_root_job_id": cursor.root_job_id if cursor else None,
                "limit_plus_one": limit + 1,
            },
        )
    ).all()
    has_more = len(rows) > limit
    selected = rows[:limit]
    items = tuple(
        [await _load_operation(session, str(row.dagster_run_id)) for row in selected]
    )
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = DagsterFeatureOperationCursor(
            created_at=last.created_at, root_job_id=last.root_job_id
        )
    return DagsterFeatureOperationPage(items=items, next_cursor=next_cursor)


async def record_feature_operation_invariant_conflict(
    session: AsyncSession,
    conflict: FeatureOperationInvariantConflict,
) -> None:
    """rollback된 invariant conflict를 별도 짧은 transaction에 남긴다."""
    await record_system_log(
        session,
        level="error",
        source="feature_operation",
        event="feature_operation.invariant_conflict",
        message=str(conflict),
        detail={
            "code": conflict.code,
            "dagster_run_id": conflict.dagster_run_id,
            "root_job_id": conflict.root_job_id,
            "details": conflict.details,
        },
    )
