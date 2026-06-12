"""T-200 batch DAG + consistency gate 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.batch_dag import run_batch_dag_consistency_gate
from kortravelmap.infra.jobs_repo import finish_import_job, start_import_job
from kortravelmap.infra.models import SourceRecordRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 4, 12, 0, tzinfo=_KST)


async def test_batch_dag_gate_links_done_child_and_records_mv_refresh_skip(
    migrated_session: AsyncSession,
) -> None:
    child = await start_import_job(
        migrated_session,
        kind="offline_upload_load",
        payload={"upload_id": "00000000-0000-0000-0000-000000000001"},
    )
    child = await finish_import_job(migrated_session, child.job_id, status="done") or child

    result = await run_batch_dag_consistency_gate(
        migrated_session,
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000001",
        consistency_persist=True,
    )

    assert result.state == "done"
    assert result.root_job is not None
    assert result.root_job.status == "done"
    assert result.child_jobs[0].job_id == child.job_id
    assert result.child_jobs[0].load_batch_id == result.load_batch_id
    assert result.child_jobs[0].parent_job_id == result.root_job.job_id
    assert result.consistency_report is not None
    assert result.consistency_report.severity_max == "OK"
    assert result.mv_refresh_job is not None
    assert result.mv_refresh_job.status == "done"
    assert result.mv_refreshes[0].state == "skipped:no_materialized_views"

    persisted = (
        await migrated_session.execute(
            text(
                "SELECT severity_max FROM ops.feature_consistency_reports "
                "WHERE batch_id = :batch_id"
            ),
            {"batch_id": result.load_batch_id},
        )
    ).scalar_one()
    assert persisted == "OK"


async def test_batch_dag_gate_blocks_mv_refresh_on_error(
    migrated_session: AsyncSession,
) -> None:
    child = await start_import_job(migrated_session, kind="feature_event_source_load")
    child = await finish_import_job(migrated_session, child.job_id, status="done") or child
    migrated_session.add(
        SourceRecordRow(
            source_record_key="batch-gate-orphan",
            provider="pytest",
            dataset_key="batch_gate",
            source_entity_type="fixture",
            source_entity_id="orphan-1",
            raw_payload_hash="deadbeef",
            fetched_at=_FETCHED,
        )
    )
    await migrated_session.flush()

    result = await run_batch_dag_consistency_gate(
        migrated_session,
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000002",
        consistency_persist=True,
    )

    assert result.state == "failed"
    assert result.blocked_by_gate is True
    assert result.consistency_report is not None
    assert result.consistency_report.severity_max == "ERROR"
    assert result.mv_refresh_job is None
    assert result.root_job is not None
    assert result.root_job.status == "failed"
    assert result.consistency_job is not None
    assert result.consistency_job.status == "failed"


async def test_batch_dag_gate_fails_when_child_not_done(
    migrated_session: AsyncSession,
) -> None:
    child = await start_import_job(migrated_session, kind="offline_upload_load")

    result = await run_batch_dag_consistency_gate(
        migrated_session,
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000003",
    )

    assert result.state == "failed"
    assert result.error_message is not None
    assert "not done" in result.error_message
    assert result.consistency_job is None
    assert result.root_job is not None
    assert result.root_job.status == "failed"
