"""C6c cancel-probe fixture의 Map 소유 영속 수명주기 repository.

일반 import-job writer는 이 kind를 절대 다루지 않는다. 이 모듈만
``running`` + no-Dagster-run probe를 만들고, canonical cancellation의 unsafe 결과와
같은 transaction에서 consume하며, 이력을 지우지 않고 terminal로 닫는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

from kortravelmap.core.feature_operation import C6C_CANCEL_PROBE_JOB_KIND

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "C6C_CANCEL_PROBE_CAPABILITY_GENERATION",
    "C6C_CANCEL_PROBE_JOB_KIND",
    "C6cCancelProbeFixture",
    "C6cCancelProbeFixtureConflict",
    "ensure_c6c_cancel_probe_fixture",
    "finalize_c6c_cancel_probe_fixture",
    "get_c6c_cancel_probe_fixture",
    "mark_c6c_cancel_probe_consumed",
]

C6C_CANCEL_PROBE_CAPABILITY_GENERATION: Final[int] = 1
C6cCancelProbeFixtureState = Literal["armed", "consumed", "finalized"]


class C6cCancelProbeFixtureConflict(RuntimeError):
    """요청한 fixture 전이가 현재 durable state와 맞지 않는다."""


@dataclass(frozen=True, slots=True)
class C6cCancelProbeFixture:
    transaction_id: str
    job_id: str
    state: C6cCancelProbeFixtureState
    cancellation_id: str | None
    created_at: datetime
    consumed_at: datetime | None
    finalized_at: datetime | None


_SELECT_FIXTURE_SQL: Final[str] = """
SELECT
    transaction_id, job_id, state, cancellation_id,
    created_at, consumed_at, finalized_at
FROM ops.c6c_cancel_probe_fixtures
WHERE transaction_id = CAST(:transaction_id AS uuid)
"""

_LOCK_TRANSACTION_SQL: Final[str] = """
SELECT pg_advisory_xact_lock(hashtextextended(CAST(:transaction_id AS text), 0))
"""

_CREATE_JOB_SQL: Final[str] = """
INSERT INTO ops.import_jobs (
    kind, payload, status, started_at, heartbeat_at, dagster_run_id
)
VALUES (
    :kind, '{}'::jsonb, 'running', clock_timestamp(), clock_timestamp(), NULL
)
RETURNING job_id
"""

_INSERT_FIXTURE_SQL: Final[str] = """
INSERT INTO ops.c6c_cancel_probe_fixtures (
    transaction_id, job_id, state
)
VALUES (CAST(:transaction_id AS uuid), CAST(:job_id AS uuid), 'armed')
RETURNING
    transaction_id, job_id, state, cancellation_id,
    created_at, consumed_at, finalized_at
"""

_CONSUME_FIXTURE_SQL: Final[str] = """
UPDATE ops.c6c_cancel_probe_fixtures AS fixture
SET state = 'consumed',
    cancellation_id = CAST(:cancellation_id AS uuid),
    consumed_at = clock_timestamp()
FROM ops.pipeline_cancellations AS cancellation
WHERE fixture.job_id = CAST(:job_id AS uuid)
  AND fixture.state = 'armed'
  AND cancellation.cancellation_id = CAST(:cancellation_id AS uuid)
  AND cancellation.root_kind = 'import_job'
  AND cancellation.root_id = fixture.job_id
  AND cancellation.status = 'failed'
  AND cancellation.error ->> 'code' = 'PIPELINE_CANCELLATION_UNSAFE'
  AND EXISTS (
      SELECT 1
      FROM ops.pipeline_cancellation_members AS member
      WHERE member.cancellation_id = cancellation.cancellation_id
        AND member.job_id = fixture.job_id
        AND member.initial_status = 'running'
        AND member.dagster_run_id IS NULL
        AND member.result = 'cancel_failed'
        AND member.error ->> 'code' = 'PIPELINE_CANCELLATION_UNSAFE'
  )
RETURNING
    fixture.transaction_id, fixture.job_id, fixture.state, fixture.cancellation_id,
    fixture.created_at, fixture.consumed_at, fixture.finalized_at
"""

_FINALIZE_JOB_SQL: Final[str] = """
UPDATE ops.import_jobs
SET status = 'failed',
    finished_at = clock_timestamp(),
    error_message = 'C6c cancel-probe finalized after unsafe cancellation'
WHERE job_id = CAST(:job_id AS uuid)
  AND kind = :kind
  AND status = 'running'
  AND dagster_run_id IS NULL
  AND cancellation_id = CAST(:cancellation_id AS uuid)
RETURNING job_id
"""

_FINALIZE_FIXTURE_SQL: Final[str] = """
UPDATE ops.c6c_cancel_probe_fixtures
SET state = 'finalized', finalized_at = clock_timestamp()
WHERE transaction_id = CAST(:transaction_id AS uuid)
  AND state = 'consumed'
  AND cancellation_id = CAST(:cancellation_id AS uuid)
RETURNING
    transaction_id, job_id, state, cancellation_id,
    created_at, consumed_at, finalized_at
"""


def _fixture_from_row(row: Any) -> C6cCancelProbeFixture:
    return C6cCancelProbeFixture(
        transaction_id=str(row.transaction_id),
        job_id=str(row.job_id),
        state=row.state,
        cancellation_id=(str(row.cancellation_id) if row.cancellation_id is not None else None),
        created_at=row.created_at,
        consumed_at=row.consumed_at,
        finalized_at=row.finalized_at,
    )


async def get_c6c_cancel_probe_fixture(
    session: AsyncSession,
    *,
    transaction_id: str,
) -> C6cCancelProbeFixture | None:
    """transaction ID의 current fixture receipt를 읽는다."""

    row = (
        await session.execute(text(_SELECT_FIXTURE_SQL), {"transaction_id": transaction_id})
    ).one_or_none()
    return _fixture_from_row(row) if row is not None else None


async def ensure_c6c_cancel_probe_fixture(
    session: AsyncSession,
    *,
    transaction_id: str,
) -> C6cCancelProbeFixture:
    """transaction ID별 armed fixture를 멱등 생성한다.

    호출자는 transaction을 소유한다. transaction-scoped advisory lock은 동시 ensure가
    같은 ID에 orphan job을 만들지 못하게 한다.
    """

    await session.execute(text(_LOCK_TRANSACTION_SQL), {"transaction_id": transaction_id})
    existing = await get_c6c_cancel_probe_fixture(
        session,
        transaction_id=transaction_id,
    )
    if existing is not None:
        return existing
    job_row = (
        await session.execute(text(_CREATE_JOB_SQL), {"kind": C6C_CANCEL_PROBE_JOB_KIND})
    ).one()
    row = (
        await session.execute(
            text(_INSERT_FIXTURE_SQL),
            {"transaction_id": transaction_id, "job_id": str(job_row.job_id)},
        )
    ).one()
    return _fixture_from_row(row)


async def mark_c6c_cancel_probe_consumed(
    session: AsyncSession,
    *,
    job_id: str,
    cancellation_id: str,
) -> C6cCancelProbeFixture | None:
    """canonical unsafe cancellation과 같은 transaction에서 armed fixture를 consume한다.

    non-fixture cancellation에는 row가 없으므로 no-op이다. 이 함수는 cancellation의
    member/error 정합성을 SQL에서 재확인해 다른 unsafe 409가 fixture receipt로 둔갑하지
    못하게 한다.
    """

    row = (
        await session.execute(
            text(_CONSUME_FIXTURE_SQL),
            {"job_id": job_id, "cancellation_id": cancellation_id},
        )
    ).one_or_none()
    return _fixture_from_row(row) if row is not None else None


async def finalize_c6c_cancel_probe_fixture(
    session: AsyncSession,
    *,
    transaction_id: str,
    cancellation_id: str,
) -> C6cCancelProbeFixture:
    """consumed fixture를 cancellation history 보존 상태로 terminal 처리한다."""

    await session.execute(text(_LOCK_TRANSACTION_SQL), {"transaction_id": transaction_id})
    fixture = await get_c6c_cancel_probe_fixture(
        session,
        transaction_id=transaction_id,
    )
    if fixture is None:
        raise C6cCancelProbeFixtureConflict("cancel-probe fixture does not exist")
    if fixture.cancellation_id != cancellation_id:
        raise C6cCancelProbeFixtureConflict("fixture cancellation_id does not match")
    if fixture.state == "finalized":
        return fixture
    if fixture.state != "consumed":
        raise C6cCancelProbeFixtureConflict("fixture is not ready to finalize")

    job_row = (
        await session.execute(
            text(_FINALIZE_JOB_SQL),
            {
                "job_id": fixture.job_id,
                "cancellation_id": cancellation_id,
                "kind": C6C_CANCEL_PROBE_JOB_KIND,
            },
        )
    ).one_or_none()
    if job_row is None:
        raise C6cCancelProbeFixtureConflict(
            "fixture job is not the expected active cancellation member"
        )
    row = (
        await session.execute(
            text(_FINALIZE_FIXTURE_SQL),
            {
                "transaction_id": transaction_id,
                "cancellation_id": cancellation_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise C6cCancelProbeFixtureConflict("fixture state changed while finalizing")
    return _fixture_from_row(row)
