"""``krtour.map.infra.jobs_repo`` — ``ops.import_jobs`` 작업 큐 repository (ADR-011).

ETL 적재 작업 상태를 영속화해 프로세스 재시작 안전성과 다중 워커 직렬화를
제공한다 (data-model.md §9.1). ``infra/feature_repo.py``와 같은 설계 — raw SQL
``text()``(ADR-004), commit은 호출자 책임.

워커 흐름
---------
1. ``enqueue_import_job(kind, payload)`` — ``state='queued'`` 행 INSERT.
2. ``claim_next_import_job()`` — advisory lock(큐 슬롯)으로 동시 claim 직렬화 후
   ``SELECT ... FOR UPDATE SKIP LOCKED``로 가장 오래된 ``queued`` 1건을 잡아
   ``state='running'`` + ``started_at``/``heartbeat_at``으로 전이. 없으면 ``None``.
3. ``heartbeat_import_job(job_id, progress, current_stage)`` — 진행 중 갱신.
4. ``finish_import_job(job_id, state, error_message)`` — ``done``/``failed``/
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
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from krtour.map.infra.advisory_lock import try_advisory_lock

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ImportJob",
    "IMPORT_QUEUE_ADVISORY_KEY",
    "DEFAULT_STALE_AFTER",
    "enqueue_import_job",
    "start_import_job",
    "claim_next_import_job",
    "heartbeat_import_job",
    "finish_import_job",
    "recover_stale_running_jobs",
]

# import_jobs 큐 claim 직렬화용 advisory lock 키 (ADR-011 ADVISORY_SLOT_IMPORT_QUEUE).
IMPORT_QUEUE_ADVISORY_KEY: Final[str] = "krtour.map:import_jobs:claim"

# heartbeat가 이 시간 이상 갱신 안 되면 stale running으로 간주 (lifespan 복구).
DEFAULT_STALE_AFTER: Final[timedelta] = timedelta(minutes=5)

_FINISHED_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})

_RETURN_COLUMNS: Final[str] = (
    "job_id, kind, payload, state, progress, current_stage, source_checksum, "
    "error_message, started_at, finished_at, heartbeat_at, created_at"
)


@dataclass(frozen=True)
class ImportJob:
    """``ops.import_jobs`` 행 표현 (repo 반환). DTO 매핑은 상위 책임."""

    job_id: str
    kind: str
    payload: dict[str, Any]
    state: str
    progress: int
    current_stage: str | None
    source_checksum: str | None
    error_message: str | None


def _row_to_job(row: Any) -> ImportJob:
    payload = row.payload
    if isinstance(payload, str):  # asyncpg가 JSONB를 str로 돌려주는 경우
        payload = json.loads(payload)
    return ImportJob(
        job_id=str(row.job_id),
        kind=row.kind,
        payload=dict(payload) if payload else {},
        state=row.state,
        progress=row.progress,
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
    )


_INSERT_JOB_SQL: Final[str] = f"""
INSERT INTO ops.import_jobs (kind, payload, source_checksum)
VALUES (:kind, CAST(:payload AS jsonb), :source_checksum)
RETURNING {_RETURN_COLUMNS}
"""

# self-driven 작업 — queue를 거치지 않고 곧바로 running으로 INSERT (호출자가 직접
# 수행하는 inline job, 예: advisory lock 보유 중인 단일 워커 적재).
_START_JOB_SQL: Final[str] = f"""
INSERT INTO ops.import_jobs (kind, payload, source_checksum, state, started_at, heartbeat_at)
VALUES (:kind, CAST(:payload AS jsonb), :source_checksum, 'running', now(), now())
RETURNING {_RETURN_COLUMNS}
"""

# 가장 오래된 queued 1건을 running으로 전이 (FOR UPDATE SKIP LOCKED — row 경합 회피).
_CLAIM_JOB_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET state = 'running', started_at = now(), heartbeat_at = now()
WHERE job_id = (
    SELECT job_id FROM ops.import_jobs
    WHERE state = 'queued'
    ORDER BY created_at
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
WHERE job_id = :job_id AND state = 'running'
RETURNING {_RETURN_COLUMNS}
"""

# 종료 전이 — done이면 progress=100. running 행만 종료(이미 종료된 행 보존).
_FINISH_SQL: Final[str] = f"""
UPDATE ops.import_jobs
SET state = :state,
    finished_at = now(),
    error_message = :error_message,
    progress = CASE WHEN :state = 'done' THEN 100 ELSE progress END
WHERE job_id = :job_id AND state = 'running'
RETURNING {_RETURN_COLUMNS}
"""

# lifespan 복구 — heartbeat 만료(또는 :stale_seconds NULL=전부)인 running 행을
# failed로. cutoff는 DB 시계 기준 now() - make_interval(secs)로 계산(클라이언트
# 시계 회피). :stale_seconds가 NULL이면 모든 running 행 복구.
_RECOVER_STALE_SQL: Final[str] = """
UPDATE ops.import_jobs
SET state = 'failed',
    finished_at = now(),
    error_message = COALESCE(error_message, 'recovered: stale running on startup')
WHERE state = 'running'
  AND (
    CAST(:stale_seconds AS double precision) IS NULL
    OR heartbeat_at IS NULL
    OR heartbeat_at < now()
        - (CAST(:stale_seconds AS double precision) * INTERVAL '1 second')
  )
RETURNING job_id
"""


async def enqueue_import_job(
    session: AsyncSession,
    *,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
) -> ImportJob:
    """``state='queued'`` 작업 1건 INSERT. commit은 호출자 책임."""
    result = await session.execute(
        text(_INSERT_JOB_SQL),
        {
            "kind": kind,
            "payload": json.dumps(dict(payload) if payload else {}),
            "source_checksum": source_checksum,
        },
    )
    return _row_to_job(result.one())


async def start_import_job(
    session: AsyncSession,
    *,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    source_checksum: str | None = None,
) -> ImportJob:
    """곧바로 ``state='running'``인 작업 1건 INSERT (self-driven inline job).

    queue를 거치지 않고 호출자가 직접 수행하는 작업 추적용 — 보통 advisory lock을
    보유한 단일 워커가 적재 전에 호출하고, 종료 시 ``finish_import_job``으로 닫는다.
    queue-worker 경로는 ``enqueue_import_job`` + ``claim_next_import_job`` 사용.
    commit은 호출자 책임.
    """
    result = await session.execute(
        text(_START_JOB_SQL),
        {
            "kind": kind,
            "payload": json.dumps(dict(payload) if payload else {}),
            "source_checksum": source_checksum,
        },
    )
    return _row_to_job(result.one())


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
        return _row_to_job(row) if row is not None else None


async def heartbeat_import_job(
    session: AsyncSession,
    job_id: str,
    *,
    progress: int | None = None,
    current_stage: str | None = None,
) -> ImportJob | None:
    """running 작업의 ``heartbeat_at``(+ 선택 progress/stage) 갱신. 없으면 ``None``."""
    result = await session.execute(
        text(_HEARTBEAT_SQL),
        {"job_id": job_id, "progress": progress, "current_stage": current_stage},
    )
    row = result.one_or_none()
    return _row_to_job(row) if row is not None else None


async def finish_import_job(
    session: AsyncSession,
    job_id: str,
    *,
    state: str = "done",
    error_message: str | None = None,
) -> ImportJob | None:
    """running 작업을 ``done``/``failed``/``cancelled``로 종료 전이. 없으면 ``None``.

    ``done``이면 ``progress=100``. 이미 종료된 작업(running 아님)은 건드리지 않고
    ``None``을 반환한다(idempotent-safe).
    """
    if state not in _FINISHED_STATES:
        raise ValueError(
            f"state must be one of {sorted(_FINISHED_STATES)}, got {state!r}."
        )
    result = await session.execute(
        text(_FINISH_SQL),
        {"job_id": job_id, "state": state, "error_message": error_message},
    )
    row = result.one_or_none()
    return _row_to_job(row) if row is not None else None


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
    result = await session.execute(
        text(_RECOVER_STALE_SQL), {"stale_seconds": stale_seconds}
    )
    return len(result.fetchall())
