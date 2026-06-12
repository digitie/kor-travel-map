"""``test_jobs_repo`` — ops.import_jobs 작업 큐 lifecycle (ADR-011).

enqueue → claim(SKIP LOCKED + advisory lock) → heartbeat → finish + lifespan
복구를 testcontainers PostGIS(migrated_session, 0006 적용)로 검증한다.

검증: ① enqueue queued ② claim FIFO + running 전이 ③ 빈 큐 claim None
④ heartbeat progress/stage ⑤ finish done(progress=100)/failed ⑥ 종료 후
재finish None ⑦ recover_stale running→failed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.jobs_repo import (
    attach_import_jobs_to_batch,
    cancel_import_job,
    claim_next_import_job,
    enqueue_import_job,
    finish_import_job,
    heartbeat_import_job,
    list_import_jobs_by_ids,
    record_import_job_event,
    recover_stale_running_jobs,
    start_import_job,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _state(session: AsyncSession, job_id: str) -> str:
    return (
        await session.execute(
            text("SELECT status FROM ops.import_jobs WHERE job_id = :id"),
            {"id": job_id},
        )
    ).scalar_one()


async def _event_codes(session: AsyncSession, job_id: str) -> list[str | None]:
    rows = (
        await session.execute(
            text(
                """
                SELECT code
                FROM ops.import_job_events
                WHERE job_id = :id
                ORDER BY occurred_at, event_id
                """
            ),
            {"id": job_id},
        )
    ).all()
    return [row.code for row in rows]


async def test_enqueue_creates_queued_job(migrated_session: AsyncSession) -> None:
    job = await enqueue_import_job(
        migrated_session,
        kind="mois_license_full_update",
        payload={"dataset_key": "mois_license_features_bulk"},
        source_checksum="abc123",
    )
    assert job.status == "queued"
    assert job.kind == "mois_license_full_update"
    assert job.payload == {"dataset_key": "mois_license_features_bulk"}
    assert job.progress == 0
    assert await _state(migrated_session, job.job_id) == "queued"
    assert await _event_codes(migrated_session, job.job_id) == ["job.queued"]


async def test_batch_columns_preserved_across_start_enqueue_and_claim(
    migrated_session: AsyncSession,
) -> None:
    batch_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    root = await start_import_job(
        migrated_session,
        kind="full_load_batch",
        payload={"mode": "full"},
        load_batch_id=batch_id,
    )
    child = await enqueue_import_job(
        migrated_session,
        kind="feature_event_visitkorea_festivals",
        payload={"provider": "python-visitkorea-api"},
        load_batch_id=batch_id,
        parent_job_id=root.job_id,
    )
    await migrated_session.flush()

    assert root.load_batch_id == batch_id
    assert root.parent_job_id is None
    assert child.load_batch_id == batch_id
    assert child.parent_job_id == root.job_id

    claimed = await claim_next_import_job(migrated_session)
    assert claimed is not None
    assert claimed.job_id == child.job_id
    assert claimed.load_batch_id == batch_id
    assert claimed.parent_job_id == root.job_id

    listed = await list_import_jobs_by_ids(migrated_session, [child.job_id])
    assert listed[0].load_batch_id == batch_id
    assert listed[0].parent_job_id == root.job_id


async def test_attach_existing_jobs_to_batch(
    migrated_session: AsyncSession,
) -> None:
    batch_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    root = await start_import_job(
        migrated_session,
        kind="full_load_batch",
        payload={"mode": "full"},
        load_batch_id=batch_id,
    )
    child = await start_import_job(
        migrated_session,
        kind="offline_upload_load",
        payload={"upload_id": "u1"},
    )
    child = await finish_import_job(migrated_session, child.job_id, status="done") or child

    attached = await attach_import_jobs_to_batch(
        migrated_session,
        [child.job_id],
        load_batch_id=batch_id,
        parent_job_id=root.job_id,
    )

    assert attached[0].job_id == child.job_id
    assert attached[0].status == "done"
    assert attached[0].load_batch_id == batch_id
    assert attached[0].parent_job_id == root.job_id


async def test_claim_fifo_and_transition_running(migrated_session: AsyncSession) -> None:
    j1 = await enqueue_import_job(migrated_session, kind="k", payload={"n": 1})
    j2 = await enqueue_import_job(migrated_session, kind="k", payload={"n": 2})
    await migrated_session.flush()

    claimed1 = await claim_next_import_job(migrated_session)
    assert claimed1 is not None
    assert claimed1.job_id == j1.job_id  # FIFO (created_at order)
    assert claimed1.status == "running"
    assert await _state(migrated_session, j1.job_id) == "running"

    claimed2 = await claim_next_import_job(migrated_session)
    assert claimed2 is not None
    assert claimed2.job_id == j2.job_id


async def test_claim_empty_queue_returns_none(migrated_session: AsyncSession) -> None:
    assert await claim_next_import_job(migrated_session) is None


async def test_heartbeat_updates_progress_and_stage(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)
    updated = await heartbeat_import_job(
        migrated_session, job.job_id, progress=42, current_stage="loading"
    )
    assert updated is not None
    assert updated.progress == 42
    assert updated.current_stage == "loading"
    # queued 작업엔 heartbeat 안 먹음(running만).
    other = await enqueue_import_job(migrated_session, kind="k")
    assert await heartbeat_import_job(migrated_session, other.job_id) is None


async def test_finish_done_sets_progress_100(migrated_session: AsyncSession) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)
    done = await finish_import_job(migrated_session, job.job_id, status="done")
    assert done is not None
    assert done.status == "done"
    assert done.progress == 100
    # 종료 후 재finish는 None(running 아님).
    assert await finish_import_job(migrated_session, job.job_id, status="failed") is None


async def test_finish_failed_records_error(migrated_session: AsyncSession) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)
    failed = await finish_import_job(
        migrated_session, job.job_id, status="failed", error_message="boom"
    )
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_message == "boom"
    assert "job.failed" in await _event_codes(migrated_session, job.job_id)


async def test_record_import_job_event_defaults_context(
    migrated_session: AsyncSession,
) -> None:
    job = await start_import_job(
        migrated_session,
        kind="feature_update_request",
        payload={
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
    )
    await heartbeat_import_job(
        migrated_session, job.job_id, progress=12, current_stage="fetching"
    )

    event = await record_import_job_event(
        migrated_session,
        job.job_id,
        level="warning",
        code="provider.retry",
        message="provider retry scheduled",
        payload={"attempt": 2},
    )

    assert event is not None
    assert event.provider == "python-mois-api"
    assert event.dataset_key == "mois_license_features_bulk"
    assert event.stage == "fetching"
    assert event.payload == {"attempt": 2}


async def test_cancel_import_job_transitions_active_job(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")

    cancelled = await cancel_import_job(
        migrated_session,
        job.job_id,
        operator="local-admin",
        reason="wrong scope",
    )

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert await _state(migrated_session, job.job_id) == "cancelled"
    assert "job.cancelled" in await _event_codes(migrated_session, job.job_id)


async def test_finish_invalid_status_raises(migrated_session: AsyncSession) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)
    with pytest.raises(ValueError, match="status must be one of"):
        await finish_import_job(migrated_session, job.job_id, status="running")


async def test_recover_stale_running_all(migrated_session: AsyncSession) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)
    assert await _state(migrated_session, job.job_id) == "running"

    # stale_after=None → 모든 running 복구(재시작 가정).
    recovered = await recover_stale_running_jobs(migrated_session, stale_after=None)
    assert recovered == 1
    assert await _state(migrated_session, job.job_id) == "failed"


async def test_recover_stale_respects_fresh_heartbeat(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_import_job(migrated_session, kind="k")
    await claim_next_import_job(migrated_session)  # heartbeat_at = now()
    # 5분 cutoff → 방금 claim한 fresh 행은 복구 대상 아님.
    recovered = await recover_stale_running_jobs(
        migrated_session, stale_after=timedelta(minutes=5)
    )
    assert recovered == 0
    assert await _state(migrated_session, job.job_id) == "running"
