"""``kortravelmap.infra.jobs_repo`` — ``ops.import_jobs`` 작업 큐 repository (ADR-011).

ETL 적재 작업 상태를 영속화해 프로세스 재시작 안전성과 다중 워커 직렬화를
제공한다 (data-model.md §9.1). ``infra/feature_repo.py``와 같은 설계 — raw SQL
``text()``(ADR-004), commit은 호출자 책임.

워커 흐름
---------
1. ``enqueue_unpaired_import_job(kind, payload)`` — ``status='queued'`` 행 INSERT.
2. ``claim_next_import_job()`` — advisory lock(큐 슬롯)으로 동시 claim 직렬화 후
   ``SELECT ... FOR UPDATE SKIP LOCKED``로 가장 오래된 ``queued`` 1건을 잡아
   ``status='running'`` + ``started_at``/``heartbeat_at``으로 전이. 없으면 ``None``.
3. ``heartbeat_import_job(job_id, progress, current_stage)`` — 진행 중 갱신.
4. ``finish_import_job(job_id, status, error_message)`` — ``done``/``failed``/
   ``cancelled`` 종료 전이 + ``finished_at``.
5. ``recover_stale_running_jobs()`` — lifespan startup 복구. heartbeat 만료(또는
   전부)인 ``running`` 잔존 행을 ``failed``로 정리 (재시작 가정).

advisory lock은 ``pg_try_advisory_lock``(``infra/advisory_lock.py``)으로 같은
큐를 여러 워커가 동시에 훑어 race하지 않도록 한다. ``SKIP LOCKED``는 row 단위
경합을 한 번 더 회피.

ADR 참조
--------
- ADR-002 — async-only
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-011 — 작업 큐 ``ops.import_jobs`` 영속화 + advisory lock + SKIP LOCKED
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias, cast

from sqlalchemy import text

from kortravelmap.core.feature_operation import (
    C6C_CANCEL_PROBE_JOB_KIND,
    FEATURE_OPERATION_RESERVED_KINDS,
    FEATURE_UPDATE_REQUEST_JOB_KIND,
    TRIGGER_KIND_VALUES,
    FeatureOperationInvariantConflict,
    TriggerKind,
)
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationConflict,
    lock_pipeline_hierarchy_for_jobs,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ImportJob",
    "ImportJobDataset",
    "ImportJobDatasetTarget",
    "ImportJobEvent",
    "IMPORT_QUEUE_ADVISORY_KEY",
    "DEFAULT_STALE_AFTER",
    "enqueue_unpaired_import_job",
    "enqueue_provider_dataset_import_job",
    "enqueue_import_job",
    "enqueue_feature_update_request_job",
    "start_unpaired_import_job",
    "start_provider_dataset_import_job",
    "start_import_job",
    "get_import_job",
    "record_import_job_event",
    "update_import_job_payload",
    "bind_import_job_dagster_run",
    "assert_generic_import_job_targets",
    "claim_next_import_job",
    "heartbeat_import_job",
    "attach_import_jobs_to_batch",
    "list_import_jobs_by_ids",
    "cancel_import_job",
    "finish_import_job",
    "recover_stale_running_jobs",
]

# import_jobs 큐 claim 직렬화용 advisory lock 키 (ADR-011 ADVISORY_SLOT_IMPORT_QUEUE).
IMPORT_QUEUE_ADVISORY_KEY: Final[str] = "kortravelmap:import_jobs:claim"

# heartbeat가 이 시간 이상 갱신 안 되면 stale running으로 간주 (lifespan 복구).
DEFAULT_STALE_AFTER: Final[timedelta] = timedelta(minutes=5)

_FINISHED_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
_EVENT_LEVELS: Final[frozenset[str]] = frozenset({"debug", "info", "warning", "error", "critical"})
_GENERIC_IMPORT_RESERVED_KINDS: Final[frozenset[str]] = FEATURE_OPERATION_RESERVED_KINDS | {
    FEATURE_UPDATE_REQUEST_JOB_KIND,
    C6C_CANCEL_PROBE_JOB_KIND,
}

ImportJobDatasetMembershipMode: TypeAlias = Literal["root", "single", "multiple"]

_RETURN_COLUMNS: Final[str] = (
    "job_id, kind, load_batch_id, parent_job_id, payload, status, progress, "
    "current_stage, source_checksum, error_message, dagster_run_id, "
    "dataset_membership_mode, trigger_kind, operation_key, "
    "dagster_run_status, dispatch_requested_at, "
    "cancellation_id, quarantined_at, quarantine_reason, "
    "cancellation_requested_at, cancellation_requested_by, cancellation_reason, "
    "started_at, finished_at, heartbeat_at, created_at"
)
# Membership projection joins add their own lifecycle columns.  Keep the
# base job projection fully qualified instead of relying on a single prefix
# before the comma-separated return list.
_JOB_SELECT_COLUMNS: Final[str] = ", ".join(
    f"job.{column}" for column in _RETURN_COLUMNS.split(", ")
)

_EVENT_RETURN_COLUMNS: Final[str] = (
    "event_id, job_id, import_job_dataset_id, feature_id, stage, level, code, "
    "message, payload, occurred_at"
)

_MEMBER_RETURN_COLUMNS: Final[str] = (
    "import_job_dataset_id, provider_dataset_id, sync_scope, operation_key"
)
_MEMBER_SELECT_COLUMNS: Final[str] = (
    "member.import_job_dataset_id, member.provider_dataset_id, member.sync_scope, "
    "member.operation_key"
)


@dataclass(frozen=True, order=True)
class ImportJobDatasetTarget:
    """새 job이 보유할 canonical dataset+scope 입력.

    모든 dataset member는 immutable operation snapshot을 함께 보관한다.
    operation이 없는 generic job은 dataset member가 아닌 root job으로 표현한다.
    """

    provider_dataset_id: int
    sync_scope: str
    operation_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_dataset_id, int)
            or isinstance(self.provider_dataset_id, bool)
            or self.provider_dataset_id <= 0
        ):
            raise ValueError("provider_dataset_id must be a positive integer")
        parse_canonical_sync_scope(self.sync_scope)
        if (
            not isinstance(self.operation_key, str)
            or not self.operation_key
            or self.operation_key != self.operation_key.strip()
        ):
            raise ValueError("operation_key must be a trimmed non-empty string")


@dataclass(frozen=True, order=True)
class ImportJobDataset:
    """이미 job에 결박된 immutable canonical dataset-operation membership.

    모든 dataset member가 exact operation key를 가진다.
    """

    import_job_dataset_id: str
    provider_dataset_id: int
    sync_scope: str
    operation_key: str


@dataclass(frozen=True)
class ImportJob:
    """``ops.import_jobs`` 행 표현 (repo 반환). DTO 매핑은 상위 책임."""

    job_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    progress: int
    current_stage: str | None
    source_checksum: str | None
    error_message: str | None
    load_batch_id: str | None = None
    parent_job_id: str | None = None
    dagster_run_id: str | None = None
    dataset_membership_mode: ImportJobDatasetMembershipMode = "root"
    dataset_memberships: tuple[ImportJobDataset, ...] = ()
    trigger_kind: TriggerKind | None = None
    operation_key: str | None = None
    dagster_run_status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime | None = None
    cancellation_id: str | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_requested_by: str | None = None
    cancellation_reason: str | None = None
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
    dispatch_requested_at: datetime | None = None


@dataclass(frozen=True)
class ImportJobEvent:
    """``ops.import_job_events`` 행 표현."""

    event_id: str
    job_id: str
    import_job_dataset_id: str | None
    feature_id: str | None
    stage: str | None
    level: str
    code: str | None
    message: str
    payload: dict[str, Any]
    occurred_at: datetime


def _row_to_job(row: Any) -> ImportJob:
    payload = row.payload
    if isinstance(payload, str):  # asyncpg가 JSONB를 str로 돌려주는 경우
        payload = json.loads(payload)
    return ImportJob(
        job_id=str(row.job_id),
        kind=row.kind,
        load_batch_id=str(row.load_batch_id) if row.load_batch_id else None,
        parent_job_id=str(row.parent_job_id) if row.parent_job_id else None,
        payload=dict(payload) if payload else {},
        status=row.status,
        progress=row.progress,
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
        dagster_run_id=row.dagster_run_id,
        dataset_membership_mode=cast(
            ImportJobDatasetMembershipMode, row.dataset_membership_mode
        ),
        trigger_kind=(
            cast(TriggerKind, row.trigger_kind) if row.trigger_kind is not None else None
        ),
        operation_key=row.operation_key,
        dagster_run_status=row.dagster_run_status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        created_at=row.created_at,
        cancellation_id=(str(row.cancellation_id) if row.cancellation_id is not None else None),
        cancellation_requested_at=row.cancellation_requested_at,
        cancellation_requested_by=row.cancellation_requested_by,
        cancellation_reason=row.cancellation_reason,
        quarantined_at=row.quarantined_at,
        quarantine_reason=row.quarantine_reason,
        dispatch_requested_at=row.dispatch_requested_at,
    )


def _row_to_event(row: Any) -> ImportJobEvent:
    payload = row.payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ImportJobEvent(
        event_id=str(row.event_id),
        job_id=str(row.job_id),
        import_job_dataset_id=(
            str(row.import_job_dataset_id)
            if row.import_job_dataset_id is not None
            else None
        ),
        feature_id=row.feature_id,
        stage=row.stage,
        level=str(row.level),
        code=row.code,
        message=str(row.message),
        payload=dict(payload) if payload else {},
        occurred_at=row.occurred_at,
    )


def _row_to_dataset(row: Any) -> ImportJobDataset | None:
    if row.import_job_dataset_id is None:
        return None
    return ImportJobDataset(
        import_job_dataset_id=str(row.import_job_dataset_id),
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


def _rows_to_job(rows: Sequence[Any]) -> ImportJob:
    if not rows:
        raise ValueError("expected an import job row")
    memberships = tuple(
        member for row in rows if (member := _row_to_dataset(row)) is not None
    )
    return replace(_row_to_job(rows[0]), dataset_memberships=memberships)


def _rows_to_jobs(rows: Sequence[Any]) -> tuple[ImportJob, ...]:
    rows_by_job: dict[str, list[Any]] = {}
    for row in rows:
        rows_by_job.setdefault(str(row.job_id), []).append(row)
    return tuple(_rows_to_job(job_rows) for job_rows in rows_by_job.values())


_INSERT_JOB_SQL: Final[str] = f"""
WITH inserted_job AS (
    INSERT INTO ops.import_jobs (
        kind, payload, source_checksum, load_batch_id, parent_job_id, dagster_run_id,
        dataset_membership_mode, trigger_kind, dispatch_requested_at
    )
    SELECT
        :kind, CAST(:payload AS jsonb), :source_checksum,
        CAST(:load_batch_id AS uuid), CAST(:parent_job_id AS uuid),
        :dagster_run_id, :dataset_membership_mode, :trigger_kind,
        CASE WHEN CAST(:dispatch_requested AS boolean) THEN clock_timestamp() END
    WHERE CAST(:parent_job_id AS uuid) IS NULL
       OR EXISTS (
          SELECT 1
          FROM ops.import_jobs AS parent
          WHERE parent.job_id = CAST(:parent_job_id AS uuid)
            AND parent.cancellation_id IS NULL
            AND parent.quarantined_at IS NULL
       )
    RETURNING *
),
inserted_members AS (
    INSERT INTO ops.import_job_datasets (
        job_id, provider_dataset_id, sync_scope, operation_key
    )
    SELECT
        job.job_id, member.provider_dataset_id, member.sync_scope, member.operation_key
    FROM inserted_job AS job
    CROSS JOIN LATERAL jsonb_to_recordset(CAST(:dataset_memberships AS jsonb)) AS member(
        provider_dataset_id bigint,
        sync_scope text,
        operation_key text
    )
    RETURNING {_MEMBER_RETURN_COLUMNS}
)
SELECT {_JOB_SELECT_COLUMNS}, {_MEMBER_SELECT_COLUMNS}
FROM inserted_job AS job
LEFT JOIN inserted_members AS member ON TRUE
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

# self-driven 작업 — queue를 거치지 않고 곧바로 running으로 INSERT (호출자가 직접
# 수행하는 inline job, 예: advisory lock 보유 중인 단일 워커 적재).
_START_JOB_SQL: Final[str] = f"""
WITH inserted_job AS (
    INSERT INTO ops.import_jobs (
        kind, payload, source_checksum, load_batch_id, parent_job_id, dagster_run_id,
        dataset_membership_mode, trigger_kind, status, started_at, heartbeat_at
    )
    SELECT
        :kind, CAST(:payload AS jsonb), :source_checksum,
        CAST(:load_batch_id AS uuid), CAST(:parent_job_id AS uuid),
        :dagster_run_id, :dataset_membership_mode, :trigger_kind,
        'running', now(), now()
    WHERE CAST(:parent_job_id AS uuid) IS NULL
       OR EXISTS (
          SELECT 1
          FROM ops.import_jobs AS parent
          WHERE parent.job_id = CAST(:parent_job_id AS uuid)
            AND parent.cancellation_id IS NULL
            AND parent.quarantined_at IS NULL
       )
    RETURNING *
),
inserted_members AS (
    INSERT INTO ops.import_job_datasets (
        job_id, provider_dataset_id, sync_scope, operation_key
    )
    SELECT
        job.job_id, member.provider_dataset_id, member.sync_scope, member.operation_key
    FROM inserted_job AS job
    CROSS JOIN LATERAL jsonb_to_recordset(CAST(:dataset_memberships AS jsonb)) AS member(
        provider_dataset_id bigint,
        sync_scope text,
        operation_key text
    )
    RETURNING {_MEMBER_RETURN_COLUMNS}
)
SELECT {_JOB_SELECT_COLUMNS}, {_MEMBER_SELECT_COLUMNS}
FROM inserted_job AS job
LEFT JOIN inserted_members AS member ON TRUE
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

_GET_JOB_SQL: Final[str] = f"""
SELECT {_JOB_SELECT_COLUMNS}, {_MEMBER_SELECT_COLUMNS}
FROM ops.import_jobs AS job
LEFT JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
WHERE job.job_id = CAST(:job_id AS uuid)
  AND job.quarantined_at IS NULL
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

_INSERT_EVENT_SQL: Final[str] = f"""
INSERT INTO ops.import_job_events (
    job_id, import_job_dataset_id, feature_id, stage, level, code, message, payload
)
SELECT
    job.job_id,
    CAST(:import_job_dataset_id AS uuid),
    COALESCE(CAST(:feature_id AS text), job.payload ->> 'feature_id'),
    COALESCE(CAST(:stage AS text), job.current_stage),
    :level,
    CAST(:code AS text),
    :message,
    CAST(:event_payload AS jsonb)
FROM ops.import_jobs AS job
WHERE job.job_id = CAST(:job_id AS uuid)
  AND job.quarantined_at IS NULL
  AND job.kind <> 'c6c_cancel_probe'
  AND (
    (job.dataset_membership_mode = 'root'
        AND CAST(:import_job_dataset_id AS uuid) IS NULL)
    OR (
        job.dataset_membership_mode <> 'root'
        AND EXISTS (
            SELECT 1
            FROM ops.import_job_datasets AS member
            WHERE member.job_id = job.job_id
              AND member.import_job_dataset_id = CAST(:import_job_dataset_id AS uuid)
        )
    )
  )
RETURNING {_EVENT_RETURN_COLUMNS}
"""

_LIST_JOBS_BY_IDS_SQL: Final[str] = f"""
WITH ids AS (
    SELECT value::uuid AS job_id
    FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
)
SELECT {_JOB_SELECT_COLUMNS}, {_MEMBER_SELECT_COLUMNS}
FROM ops.import_jobs AS job
LEFT JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
WHERE job.job_id IN (SELECT job_id FROM ids)
  AND job.quarantined_at IS NULL
ORDER BY job.created_at, job.job_id, member.provider_dataset_id, member.sync_scope,
         member.operation_key
"""

_UPDATE_PAYLOAD_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET payload = CAST(:payload AS jsonb)
WHERE job_id = CAST(:job_id AS uuid)
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
RETURNING {_RETURN_COLUMNS}
"""

_BIND_DAGSTER_RUN_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET dagster_run_id = :dagster_run_id
WHERE job_id = CAST(:job_id AS uuid)
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
  AND status IN ('queued','running')
  AND (dagster_run_id IS NULL OR dagster_run_id = :dagster_run_id)
RETURNING {_RETURN_COLUMNS}
"""

_ATTACH_BATCH_SQL: Final[str] = f"""
WITH ids AS (
    SELECT value::uuid AS job_id
    FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
),
eligible AS (
    SELECT
      (SELECT COUNT(*) FROM ops.import_jobs WHERE job_id IN (SELECT job_id FROM ids))
        = (SELECT COUNT(*) FROM ids)
      AND NOT EXISTS (
        SELECT 1
        FROM ops.import_jobs
        WHERE job_id IN (SELECT job_id FROM ids)
          AND cancellation_id IS NOT NULL
      )
      AND NOT EXISTS (
        SELECT 1
        FROM ops.import_jobs
        WHERE job_id IN (SELECT job_id FROM ids)
          AND quarantined_at IS NOT NULL
      )
      AND NOT EXISTS (
        SELECT 1
        FROM ops.import_jobs
        WHERE job_id IN (SELECT job_id FROM ids)
          AND kind IN (
            'provider_feature_load_run','provider_feature_load','feature_update_request',
            'c6c_cancel_probe'
          )
      )
      AND EXISTS (
        SELECT 1
        FROM ops.import_jobs AS parent
        WHERE parent.job_id = CAST(:parent_job_id AS uuid)
          AND parent.cancellation_id IS NULL
          AND parent.quarantined_at IS NULL
          AND parent.kind NOT IN (
            'provider_feature_load_run','provider_feature_load','feature_update_request',
            'c6c_cancel_probe'
          )
      ) AS allowed
)
UPDATE ops.import_jobs
SET load_batch_id = CAST(:load_batch_id AS uuid),
    parent_job_id = CAST(:parent_job_id AS uuid)
WHERE job_id IN (SELECT job_id FROM ids)
  AND (SELECT allowed FROM eligible)
RETURNING {_RETURN_COLUMNS}
"""

# 가장 오래된 queued 1건을 running으로 전이 (FOR UPDATE SKIP LOCKED — row 경합 회피).
_CLAIM_JOB_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET status = 'running', started_at = now(), heartbeat_at = now()
WHERE job_id = (
    SELECT job_id FROM ops.import_jobs
    WHERE status = 'queued'
      AND cancellation_id IS NULL
      AND quarantined_at IS NULL
      AND kind NOT IN (
        'provider_feature_load_run','provider_feature_load','feature_update_request',
        'c6c_cancel_probe'
      )
    ORDER BY created_at, queue_sequence
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING {_RETURN_COLUMNS}
"""

_HEARTBEAT_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET heartbeat_at = now(),
    progress = COALESCE(:progress, progress),
    current_stage = COALESCE(:current_stage, current_stage)
WHERE job_id = :job_id
  AND status = 'running'
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
RETURNING {_RETURN_COLUMNS}
"""

# 종료 전이 — done이면 progress=100. running 행만 종료(이미 종료된 행 보존).
_FINISH_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET status = :status,
    finished_at = now(),
    error_message = :error_message,
    progress = CASE WHEN :status = 'done' THEN 100 ELSE progress END
WHERE job_id = :job_id
  AND status = 'running'
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
RETURNING {_RETURN_COLUMNS}
"""

_CANCEL_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET status = 'cancelled',
    finished_at = now(),
    error_message = COALESCE(:error_message, error_message, 'cancelled by admin API')
WHERE job_id = CAST(:job_id AS uuid)
  AND status IN ('queued', 'running')
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
RETURNING {_RETURN_COLUMNS}
"""

# lifespan 복구 — heartbeat 만료(또는 :stale_seconds NULL=전부)인 running 행을
# failed로. cutoff는 DB 시계 기준 now() - make_interval(secs)로 계산(클라이언트
# 시계 회피). :stale_seconds가 NULL이면 모든 running 행 복구.
_RECOVER_STALE_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = 'failed',
    finished_at = now(),
    error_message = COALESCE(error_message, 'recovered: stale running on startup')
WHERE status = 'running'
  AND cancellation_id IS NULL
  AND quarantined_at IS NULL
  AND kind NOT IN (
    'provider_feature_load_run','provider_feature_load','feature_update_request',
    'c6c_cancel_probe'
  )
  AND (
    CAST(:stale_seconds AS double precision) IS NULL
    OR heartbeat_at IS NULL
    OR heartbeat_at < now()
        - (CAST(:stale_seconds AS double precision) * INTERVAL '1 second')
  )
RETURNING job_id
"""

_TARGET_KINDS_SQL: Final[str] = """
WITH ids AS (
  SELECT value::uuid AS job_id
  FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
)
SELECT job_id, kind
FROM ops.import_jobs
WHERE job_id IN (SELECT job_id FROM ids)
  AND (
    kind IN (
      'provider_feature_load_run','provider_feature_load','feature_update_request',
      'c6c_cancel_probe'
    )
    OR quarantined_at IS NOT NULL
  )
LIMIT 1
"""


def _validate_generic_kind(kind: str) -> None:
    if kind in _GENERIC_IMPORT_RESERVED_KINDS:
        raise FeatureOperationInvariantConflict(
            "reserved feature operation kind requires the tracking repository",
            dagster_run_id="unknown",
            details={"kind": kind},
        )


def _normalized_dataset_memberships(
    values: Sequence[ImportJobDatasetTarget],
) -> tuple[ImportJobDatasetTarget, ...]:
    """입력의 canonical membership을 검증하고 exact 중복을 거부한다."""
    memberships = tuple(values)
    if len(set(memberships)) != len(memberships):
        raise ValueError("dataset memberships must not contain duplicate dataset operations")
    return memberships


def _membership_mode(
    memberships: Sequence[ImportJobDatasetTarget],
) -> ImportJobDatasetMembershipMode:
    if not memberships:
        return "root"
    if len(memberships) == 1:
        return "single"
    return "multiple"


def _job_params(
    *,
    memberships: Sequence[ImportJobDatasetTarget],
    trigger_kind: TriggerKind | None,
) -> dict[str, str | None]:
    if trigger_kind is not None and trigger_kind not in TRIGGER_KIND_VALUES:
        raise ValueError(f"invalid trigger_kind: {trigger_kind}")
    return {
        "dataset_membership_mode": _membership_mode(memberships),
        "trigger_kind": trigger_kind,
    }


def _optional_dagster_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip():
        raise ValueError("dagster_run_id must be trimmed and non-empty")
    return value


async def assert_generic_import_job_targets(session: AsyncSession, job_ids: Sequence[str]) -> None:
    if not job_ids:
        return
    row = (
        await session.execute(
            text(_TARGET_KINDS_SQL), {"job_ids": json.dumps(list(dict.fromkeys(job_ids)))}
        )
    ).one_or_none()
    if row is not None:
        raise FeatureOperationInvariantConflict(
            "generic import writer cannot mutate a reserved feature operation",
            dagster_run_id="unknown",
            root_job_id=str(row.job_id),
            details={"kind": str(row.kind)},
        )


async def enqueue_unpaired_import_job(
    session: AsyncSession,
    *,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    dagster_run_id: str | None = None,
    trigger_kind: TriggerKind | None = None,
) -> ImportJob:
    """Dataset membership이 없는 root orchestration 작업을 ``queued``로 만든다."""
    return await enqueue_import_job(
        session,
        kind=kind,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dispatch_requested=False,
        dataset_memberships=(),
    )


async def enqueue_provider_dataset_import_job(
    session: AsyncSession,
    *,
    kind: str,
    dataset_membership: ImportJobDatasetTarget,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    dagster_run_id: str | None = None,
    trigger_kind: TriggerKind | None = None,
) -> ImportJob:
    """하나의 canonical membership을 가진 작업을 ``queued``로 만든다."""
    return await enqueue_import_job(
        session,
        kind=kind,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dispatch_requested=False,
        dataset_memberships=(dataset_membership,),
    )


async def enqueue_import_job(
    session: AsyncSession,
    *,
    kind: str,
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    dagster_run_id: str | None = None,
    trigger_kind: TriggerKind | None = None,
    dispatch_requested: bool = False,
) -> ImportJob:
    """Canonical membership snapshot과 함께 queued import job을 원자 생성한다."""
    _validate_generic_kind(kind)
    return await _insert_import_job(
        session,
        sql=_INSERT_JOB_SQL,
        kind=kind,
        dataset_memberships=dataset_memberships,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dispatch_requested=dispatch_requested,
    )


async def enqueue_feature_update_request_job(
    session: AsyncSession,
    *,
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    dispatch_requested: bool,
) -> ImportJob:
    """전용 request writer가 같은 transaction에서 연결할 canonical job을 만든다.

    이 함수만 reserved ``feature_update_request`` kind를 생성할 수 있다. transaction을
    request INSERT 없이 commit하면 DB의 deferred 양방향 constraint trigger가 거부한다.
    """
    memberships = _normalized_dataset_memberships(dataset_memberships)
    if not memberships:
        raise ValueError("feature update job requires at least one canonical dataset membership")
    return await _insert_import_job(
        session,
        sql=_INSERT_JOB_SQL,
        kind=FEATURE_UPDATE_REQUEST_JOB_KIND,
        dataset_memberships=memberships,
        payload={},
        source_checksum=None,
        load_batch_id=None,
        parent_job_id=None,
        dagster_run_id=None,
        trigger_kind="update_request",
        dispatch_requested=dispatch_requested,
    )


async def _insert_import_job(
    session: AsyncSession,
    *,
    sql: str,
    kind: str,
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    payload: Mapping[str, Any] | None,
    source_checksum: str | None,
    load_batch_id: str | None,
    parent_job_id: str | None,
    dagster_run_id: str | None,
    trigger_kind: TriggerKind | None,
    dispatch_requested: bool,
) -> ImportJob:
    memberships = _normalized_dataset_memberships(dataset_memberships)
    normalized_run_id = _optional_dagster_run_id(dagster_run_id)
    job_params = _job_params(memberships=memberships, trigger_kind=trigger_kind)
    if parent_job_id is not None:
        await assert_generic_import_job_targets(session, (parent_job_id,))
        await lock_pipeline_hierarchy_for_jobs(session, (parent_job_id,))
    result = await session.execute(
        text(sql),
        {
            "kind": kind,
            "payload": json.dumps(dict(payload) if payload else {}),
            "source_checksum": source_checksum,
            "load_batch_id": load_batch_id,
            "parent_job_id": parent_job_id,
            "dagster_run_id": normalized_run_id,
            "dispatch_requested": dispatch_requested,
            "dataset_memberships": json.dumps(
                [
                    {
                        "provider_dataset_id": membership.provider_dataset_id,
                        "sync_scope": membership.sync_scope,
                        "operation_key": membership.operation_key,
                    }
                    for membership in memberships
                ]
            ),
            **job_params,
        },
    )
    rows = result.all()
    if not rows:
        raise PipelineCancellationConflict(
            "cancel-marked parent cannot accept a new import job child"
        )
    job = _rows_to_job(rows)
    await _record_lifecycle_event(
        session,
        job,
        code="job.queued" if job.status == "queued" else "job.started",
        message="import job queued" if job.status == "queued" else "import job started",
        payload={"status": job.status, "progress": job.progress},
        stage=job.current_stage,
    )
    return job


async def start_unpaired_import_job(
    session: AsyncSession,
    *,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    dagster_run_id: str | None = None,
    trigger_kind: TriggerKind | None = None,
) -> ImportJob:
    """Pair가 없는 orchestration 작업을 곧바로 ``running``으로 INSERT한다.

    queue를 거치지 않고 호출자가 직접 수행하는 작업 추적용 — 보통 advisory lock을
    보유한 단일 워커가 적재 전에 호출하고, 종료 시 ``finish_import_job``으로 닫는다.
    queue-worker 경로는 ``enqueue_unpaired_import_job`` + ``claim_next_import_job`` 사용.
    commit은 호출자 책임.
    """
    return await start_import_job(
        session,
        kind=kind,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dataset_memberships=(),
    )


async def start_provider_dataset_import_job(
    session: AsyncSession,
    *,
    kind: str,
    dataset_membership: ImportJobDatasetTarget,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    dagster_run_id: str | None = None,
    trigger_kind: TriggerKind | None = None,
) -> ImportJob:
    """하나의 canonical membership 작업을 곧바로 ``running``으로 만든다."""
    return await start_import_job(
        session,
        kind=kind,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dataset_memberships=(dataset_membership,),
    )


async def start_import_job(
    session: AsyncSession,
    *,
    kind: str,
    dataset_memberships: Sequence[ImportJobDatasetTarget],
    payload: Mapping[str, Any] | None,
    source_checksum: str | None,
    load_batch_id: str | None,
    parent_job_id: str | None,
    dagster_run_id: str | None,
    trigger_kind: TriggerKind | None,
) -> ImportJob:
    _validate_generic_kind(kind)
    return await _insert_import_job(
        session,
        sql=_START_JOB_SQL,
        kind=kind,
        dataset_memberships=dataset_memberships,
        payload=payload,
        source_checksum=source_checksum,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
        dagster_run_id=dagster_run_id,
        trigger_kind=trigger_kind,
        dispatch_requested=False,
    )


async def get_import_job(session: AsyncSession, job_id: str) -> ImportJob | None:
    """``job_id``로 import job을 조회한다."""
    result = await session.execute(text(_GET_JOB_SQL), {"job_id": job_id})
    rows = result.all()
    return _rows_to_job(rows) if rows else None


async def record_import_job_event(
    session: AsyncSession,
    job_id: str,
    *,
    level: str = "info",
    code: str | None = None,
    message: str,
    payload: Mapping[str, Any] | None = None,
    import_job_dataset_id: str | None = None,
    feature_id: str | None = None,
    stage: str | None = None,
) -> ImportJobEvent | None:
    """``ops.import_job_events``에 구조화 event 1건을 기록한다.

    root job은 member 없이, non-root job은 해당 job에 속하는 exact
    ``import_job_dataset_id``와 함께만 event를 쓴다. stage를 생략하면 job의
    ``current_stage``를 사용한다. 없거나 격리된 ``job_id``면 ``None``을 반환한다.
    commit은 호출자 책임이다.
    """
    if level not in _EVENT_LEVELS:
        raise ValueError(f"level must be one of {sorted(_EVENT_LEVELS)}, got {level!r}.")
    job = await get_import_job(session, job_id)
    if job is None or job.kind == C6C_CANCEL_PROBE_JOB_KIND:
        return None
    result = await session.execute(
        text(_INSERT_EVENT_SQL),
        {
            "job_id": job_id,
            "import_job_dataset_id": import_job_dataset_id,
            "feature_id": feature_id,
            "stage": stage,
            "level": level,
            "code": code,
            "message": message,
            "event_payload": json.dumps(dict(payload) if payload else {}),
        },
    )
    row = result.one_or_none()
    if row is None:
        raise FeatureOperationInvariantConflict(
            "event requires the exact canonical import job membership",
            dagster_run_id=job.dagster_run_id or "unknown",
            root_job_id=job_id,
            details={"reason": "missing_or_mismatched_job_membership"},
        )
    return _row_to_event(row)


async def _record_lifecycle_event(
    session: AsyncSession,
    job: ImportJob,
    *,
    code: str,
    message: str,
    payload: Mapping[str, Any],
    stage: str | None = None,
    level: str = "info",
) -> None:
    """Job lifecycle event를 root 또는 각 exact member에 대응시켜 기록한다."""
    if job.kind == C6C_CANCEL_PROBE_JOB_KIND:
        return
    member_ids: tuple[str | None, ...]
    if job.dataset_membership_mode == "root":
        member_ids = (None,)
    else:
        member_ids = tuple(
            membership.import_job_dataset_id for membership in job.dataset_memberships
        )
    for import_job_dataset_id in member_ids:
        await record_import_job_event(
            session,
            job.job_id,
            level=level,
            code=code,
            message=message,
            payload=payload,
            import_job_dataset_id=import_job_dataset_id,
            stage=stage,
        )


async def _hydrate_job_memberships(session: AsyncSession, job: ImportJob) -> ImportJob:
    hydrated = await get_import_job(session, job.job_id)
    if hydrated is None:
        raise FeatureOperationInvariantConflict(
            "import job vanished while hydrating canonical memberships",
            dagster_run_id=job.dagster_run_id or "unknown",
            root_job_id=job.job_id,
        )
    return hydrated


async def list_import_jobs_by_ids(
    session: AsyncSession,
    job_ids: Sequence[str],
) -> tuple[ImportJob, ...]:
    """``job_ids``에 해당하는 import job 목록을 조회한다.

    DB 반환 순서는 보장하지 않으므로 호출자가 필요 시 입력 순서로 재정렬한다.
    """
    if not job_ids:
        return ()
    result = await session.execute(
        text(_LIST_JOBS_BY_IDS_SQL),
        {"job_ids": json.dumps(list(job_ids))},
    )
    return _rows_to_jobs(result.all())


async def update_import_job_payload(
    session: AsyncSession,
    job_id: str,
    *,
    payload: Mapping[str, Any],
) -> ImportJob | None:
    """import job payload를 교체한다. validation summary 보존에 사용한다."""
    await assert_generic_import_job_targets(session, (job_id,))
    result = await session.execute(
        text(_UPDATE_PAYLOAD_SQL),
        {"job_id": job_id, "payload": json.dumps(dict(payload))},
    )
    row = result.one_or_none()
    return await _hydrate_job_memberships(session, _row_to_job(row)) if row is not None else None


async def bind_import_job_dagster_run(
    session: AsyncSession,
    job_id: str,
    *,
    dagster_run_id: str,
) -> ImportJob:
    """active generic job에 run id를 연결한다. terminal row는 재결합하지 않는다."""
    normalized_run_id = _optional_dagster_run_id(dagster_run_id)
    assert normalized_run_id is not None
    await assert_generic_import_job_targets(session, (job_id,))
    row = (
        await session.execute(
            text(_BIND_DAGSTER_RUN_SQL),
            {"job_id": job_id, "dagster_run_id": normalized_run_id},
        )
    ).one_or_none()
    if row is None:
        raise PipelineCancellationConflict(
            "import job Dagster run binding was rejected by marker or frozen run id"
        )
    return await _hydrate_job_memberships(session, _row_to_job(row))


async def attach_import_jobs_to_batch(
    session: AsyncSession,
    job_ids: Sequence[str],
    *,
    load_batch_id: str,
    parent_job_id: str,
) -> tuple[ImportJob, ...]:
    """기존 import job들을 T-200 load batch root 아래 child로 연결한다."""
    if not job_ids:
        return ()
    normalized_job_ids = tuple(dict.fromkeys(job_ids))
    await assert_generic_import_job_targets(session, (*normalized_job_ids, parent_job_id))
    await lock_pipeline_hierarchy_for_jobs(
        session,
        (*normalized_job_ids, parent_job_id),
    )
    result = await session.execute(
        text(_ATTACH_BATCH_SQL),
        {
            "job_ids": json.dumps(normalized_job_ids),
            "load_batch_id": load_batch_id,
            "parent_job_id": parent_job_id,
        },
    )
    jobs: list[ImportJob] = []
    for row in result:
        jobs.append(await _hydrate_job_memberships(session, _row_to_job(row)))
    return tuple(jobs)


async def claim_next_import_job(session: AsyncSession) -> ImportJob | None:
    """가장 오래된 ``queued`` 작업 1건을 ``running``으로 claim (없으면 ``None``).

    advisory lock으로 동시 claim을 직렬화하고, 다른 워커가 이미 큐를 훑는 중이면
    대기하지 않고 ``None``을 반환한다 (``SKIP LOCKED``로 row 경합도 회피).
    commit은 호출자 책임 — claim 후 작업 수행, 종료 시 ``finish_import_job``.
    """
    async with try_advisory_lock(session, IMPORT_QUEUE_ADVISORY_KEY) as acquired:
        if not acquired:
            return None
        result = await session.execute(text(_CLAIM_JOB_SQL))
        row = result.one_or_none()
        if row is None:
            return None
        job = await _hydrate_job_memberships(session, _row_to_job(row))
        await _record_lifecycle_event(
            session,
            job,
            code="job.claimed",
            message="import job claimed",
            payload={"status": job.status, "progress": job.progress},
            stage=job.current_stage,
        )
        return job


async def heartbeat_import_job(
    session: AsyncSession,
    job_id: str,
    *,
    progress: int | None = None,
    current_stage: str | None = None,
) -> ImportJob | None:
    """running 작업의 ``heartbeat_at``(+ 선택 progress/stage) 갱신. 없으면 ``None``."""
    await assert_generic_import_job_targets(session, (job_id,))
    result = await session.execute(
        text(_HEARTBEAT_SQL),
        {"job_id": job_id, "progress": progress, "current_stage": current_stage},
    )
    row = result.one_or_none()
    if row is None:
        return None
    job = await _hydrate_job_memberships(session, _row_to_job(row))
    if progress is not None or current_stage is not None:
        await _record_lifecycle_event(
            session,
            job,
            code="job.heartbeat",
            message="import job heartbeat",
            payload={"status": job.status, "progress": job.progress},
            stage=job.current_stage,
        )
    return job


async def cancel_import_job(
    session: AsyncSession,
    job_id: str,
    *,
    error_message: str | None = "cancelled by admin API",
    operator: str | None = None,
    reason: str | None = None,
) -> ImportJob | None:
    """queued/running import job을 ``cancelled``로 전이한다.

    이미 terminal 상태인 행은 건드리지 않고 ``None``을 반환한다. 실행 중인 외부
    프로세스를 강제 종료하지는 못하므로 event payload에 best-effort 한계를 남긴다.
    """
    await assert_generic_import_job_targets(session, (job_id,))
    result = await session.execute(
        text(_CANCEL_SQL),
        {"job_id": job_id, "error_message": error_message or reason},
    )
    row = result.one_or_none()
    if row is None:
        return None
    job = await _hydrate_job_memberships(session, _row_to_job(row))
    await _record_lifecycle_event(
        session,
        job,
        code="job.cancelled",
        level="warning",
        message=error_message or reason or "import job cancelled",
        payload={
            "status": job.status,
            "progress": job.progress,
            "operator": operator,
            "reason": reason,
            "best_effort": True,
        },
        stage=job.current_stage,
    )
    return job


async def finish_import_job(
    session: AsyncSession,
    job_id: str,
    *,
    status: str = "done",
    error_message: str | None = None,
) -> ImportJob | None:
    """running 작업을 ``done``/``failed``/``cancelled``로 종료 전이. 없으면 ``None``.

    ``done``이면 ``progress=100``. 이미 종료된 작업(running 아님)은 건드리지 않고
    ``None``을 반환한다(idempotent-safe).
    """
    if status not in _FINISHED_STATES:
        raise ValueError(f"status must be one of {sorted(_FINISHED_STATES)}, got {status!r}.")
    await assert_generic_import_job_targets(session, (job_id,))
    result = await session.execute(
        text(_FINISH_SQL),
        {"job_id": job_id, "status": status, "error_message": error_message},
    )
    row = result.one_or_none()
    if row is None:
        return None
    job = await _hydrate_job_memberships(session, _row_to_job(row))
    await _record_lifecycle_event(
        session,
        job,
        code=f"job.{status}",
        level="error" if status == "failed" else "info",
        message=error_message or f"import job {status}",
        payload={"status": job.status, "progress": job.progress},
        stage=job.current_stage,
    )
    return job


async def recover_stale_running_jobs(
    session: AsyncSession,
    *,
    stale_after: timedelta | None = DEFAULT_STALE_AFTER,
) -> int:
    """lifespan startup 복구 — heartbeat 만료 ``running`` 행을 ``failed``로 정리.

    ``stale_after``가 ``None``이면 모든 ``running`` 행을 복구한다 (재시작 시 진행
    중이던 작업은 모두 실패로 간주). 그렇지 않으면 ``heartbeat_at``이 ``now() -
    stale_after`` 이전이거나 NULL인 행만. cutoff는 Python에서 계산하지 않고
    ``now()`` 기준 SQL 비교를 위해 ``None``/timestamp로 넘긴다.

    Returns
    -------
    int
        복구(failed 전환)된 작업 수.
    """
    stale_seconds = None if stale_after is None else stale_after.total_seconds()
    result = await session.execute(text(_RECOVER_STALE_SQL), {"stale_seconds": stale_seconds})
    return len(result.fetchall())
