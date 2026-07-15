"""T-200 batch DAG + consistency gate 통합 테스트."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import kortravelmap.client as client_module
import kortravelmap.infra.batch_dag as batch_module
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.batch_dag import (
    BatchDagCancellationWon,
    BatchDagMvPrepared,
    BatchDagPrepared,
    BatchDagRequest,
    BatchDagRunResult,
    MaterializedViewRefreshResult,
    fail_batch_dag_phase,
    make_batch_dag_request,
    prepare_batch_dag,
    run_batch_consistency_phase,
    start_batch_mv_phase,
)
from kortravelmap.infra.consistency import ConsistencyReport
from kortravelmap.infra.jobs_repo import finish_import_job, start_import_job
from kortravelmap.infra.models import SourceEntityRow, SourceRecordRow
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    lock_pipeline_lineage_mutation,
    resolve_pipeline_cancellation_scope,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 4, 12, 0, tzinfo=_KST)


@pytest.fixture(autouse=True)
async def _cleanup_committed_batch_state(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[None]:
    """전용 connection 테스트가 commit한 행을 모듈 테스트 뒤 제거한다."""
    async with AsyncSession(migrated_engine) as snapshot:
        job_ids = set(
            await snapshot.scalars(text("SELECT job_id FROM ops.import_jobs"))
        )
        cancellation_ids = set(
            await snapshot.scalars(
                text("SELECT cancellation_id FROM ops.pipeline_cancellations")
            )
        )
        report_ids = set(
            await snapshot.scalars(
                text("SELECT report_id FROM ops.feature_consistency_reports")
            )
        )
        system_log_ids = set(
            await snapshot.scalars(text("SELECT system_log_id FROM ops.system_log"))
        )
    try:
        yield
    finally:
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_job_events "
                    "WHERE job_id <> ALL(CAST(:job_ids AS uuid[]))"
                ),
                {"job_ids": list(job_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.import_jobs "
                    "WHERE job_id <> ALL(CAST(:job_ids AS uuid[]))"
                ),
                {"job_ids": list(job_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellation_members "
                    "WHERE cancellation_id <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(cancellation_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellation_runs "
                    "WHERE cancellation_id <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(cancellation_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.pipeline_cancellations "
                    "WHERE cancellation_id <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(cancellation_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.feature_consistency_reports "
                    "WHERE report_id <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(report_ids)},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM ops.system_log "
                    "WHERE system_log_id <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"ids": list(system_log_ids)},
            )
            await cleanup.execute(
                text(
                    "UPDATE provider_sync.source_entities "
                    "SET current_source_record_key = NULL "
                    "WHERE source_entity_key = 'batch-gate-orphan-entity'"
                )
            )
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.source_records "
                    "WHERE source_entity_key = 'batch-gate-orphan-entity'"
                )
            )
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.source_entities "
                    "WHERE source_entity_key = 'batch-gate-orphan-entity'"
                )
            )


async def test_batch_dag_gate_links_done_child_and_records_mv_refresh_skip(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(
            setup,
            kind="offline_upload_load",
            payload={"upload_id": "00000000-0000-0000-0000-000000000001"},
        )
        child = await finish_import_job(setup, child.job_id, status="done") or child
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
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

    async with AsyncSession(migrated_engine) as verify:
        persisted = (
            await verify.execute(
                text(
                    "SELECT severity_max FROM ops.feature_consistency_reports "
                    "WHERE batch_id = :batch_id"
                ),
                {"batch_id": result.load_batch_id},
            )
        ).scalar_one()
    assert persisted == "OK"


async def test_batch_dag_gate_blocks_mv_refresh_on_error(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="feature_event_source_load")
        child = await finish_import_job(setup, child.job_id, status="done") or child
        setup.add(
            SourceEntityRow(
                source_entity_key="batch-gate-orphan-entity",
                provider="pytest",
                dataset_key="batch_gate",
                source_entity_type="fixture",
                source_entity_id="orphan-1",
                current_source_record_key=None,
                first_seen_at=_FETCHED,
                last_seen_at=_FETCHED,
            )
        )
        await setup.flush()
        setup.add(
            SourceRecordRow(
                source_record_key="batch-gate-orphan",
                source_entity_key="batch-gate-orphan-entity",
                provider="pytest",
                dataset_key="batch_gate",
                source_entity_type="fixture",
                source_entity_id="orphan-1",
                raw_payload_hash="deadbeef",
                fetched_at=_FETCHED,
            )
        )
        await setup.flush()
        entity = await setup.get(SourceEntityRow, "batch-gate-orphan-entity")
        assert entity is not None
        entity.current_source_record_key = "batch-gate-orphan"
        await setup.flush()
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
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
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000003",
    )

    assert result.state == "failed"
    assert result.error_message is not None
    assert "not done" in result.error_message
    assert result.consistency_job is None
    assert result.root_job is not None
    assert result.root_job.status == "failed"


async def test_batch_phases_keep_one_backend_but_release_lineage_xact_lock(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")
    backend_pids: list[int] = []
    original_prepare = client_module.prepare_batch_dag
    original_consistency = client_module.run_batch_consistency_phase
    original_start_mv = client_module.start_batch_mv_phase
    original_finish_mv = client_module.finish_batch_mv_phase

    async def capture_prepare(
        session: AsyncSession, request: BatchDagRequest
    ) -> BatchDagPrepared | BatchDagRunResult:
        backend_pids.append(int(await session.scalar(text("SELECT pg_backend_pid()"))))
        return await original_prepare(session, request)

    async def fake_consistency(
        session: AsyncSession, prepared: BatchDagPrepared
    ) -> ConsistencyReport | BatchDagRunResult:
        backend_pids.append(int(await session.scalar(text("SELECT pg_backend_pid()"))))
        async with AsyncSession(migrated_engine) as probe, probe.begin():
            acquired = await probe.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {
                    "lock_id": advisory_lock_key(
                        "kortravelmap:pipeline-lineage:mutation"
                    )
                },
            )
            assert acquired is True
        return await original_consistency(session, prepared)

    async def capture_start_mv(
        session: AsyncSession,
        prepared: BatchDagPrepared,
        report: ConsistencyReport,
    ) -> BatchDagMvPrepared | BatchDagRunResult:
        backend_pids.append(int(await session.scalar(text("SELECT pg_backend_pid()"))))
        return await original_start_mv(session, prepared, report)

    async def capture_finish_mv(
        session: AsyncSession, phase: BatchDagMvPrepared
    ) -> BatchDagRunResult:
        backend_pids.append(int(await session.scalar(text("SELECT pg_backend_pid()"))))
        return await original_finish_mv(session, phase)

    monkeypatch.setattr(client_module, "prepare_batch_dag", capture_prepare)
    monkeypatch.setattr(client_module, "run_batch_consistency_phase", fake_consistency)
    monkeypatch.setattr(client_module, "start_batch_mv_phase", capture_start_mv)
    monkeypatch.setattr(client_module, "finish_batch_mv_phase", capture_finish_mv)
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000004",
    )

    assert result.state == "done"
    assert len(set(backend_pids)) == 1


@pytest.mark.parametrize("same_batch", [True, False])
async def test_batch_session_mutex_serializes_only_same_batch(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    same_batch: bool,
) -> None:
    active = 0
    max_active = 0

    async def fake_prepare(
        _session: AsyncSession, request: BatchDagRequest
    ) -> BatchDagRunResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return BatchDagRunResult(
            load_batch_id=request.load_batch_id,
            state="failed",
        )

    monkeypatch.setattr(client_module, "prepare_batch_dag", fake_prepare)
    first_id = "aaaaaaaa-0000-0000-0000-000000000005"
    second_id = (
        first_id if same_batch else "aaaaaaaa-0000-0000-0000-000000000006"
    )
    first = AsyncKorTravelMapClient(migrated_engine)
    second = AsyncKorTravelMapClient(migrated_engine)
    await asyncio.gather(
        first.run_batch_dag_consistency_gate(load_batch_id=first_id),
        second.run_batch_dag_consistency_gate(load_batch_id=second_id),
    )

    assert max_active == (1 if same_batch else 2)


async def test_mv_phase_exception_rolls_back_before_durable_failure_record(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")

    async def fail_after_write(
        session: AsyncSession, phase: BatchDagMvPrepared
    ) -> BatchDagRunResult:
        await session.execute(
            text(
                "UPDATE ops.import_jobs SET payload = '{\"transient\":true}'::jsonb "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": phase.prepared.root_job.job_id},
        )
        raise RuntimeError("mv exploded")

    monkeypatch.setattr(client_module, "finish_batch_mv_phase", fail_after_write)
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
        child_job_ids=[child.job_id],
        load_batch_id="aaaaaaaa-0000-0000-0000-000000000007",
    )

    assert result.state == "failed"
    assert result.root_job is not None
    assert result.root_job.status == "failed"
    async with AsyncSession(migrated_engine) as verify:
        payload = await verify.scalar(
            text(
                "SELECT payload FROM ops.import_jobs "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": result.root_job.job_id},
        )
    assert payload.get("transient") is None


async def test_cancellation_marker_wins_mv_phase_without_status_overwrite(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")
    batch_id = "aaaaaaaa-0000-0000-0000-000000000008"
    refresh_calls: list[tuple[tuple[str, ...], str]] = []

    async def refresh_then_cancel(
        session: AsyncSession,
        materialized_views: tuple[str, ...],
        *,
        strategy: str,
    ) -> tuple[MaterializedViewRefreshResult, ...]:
        refresh_calls.append((materialized_views, strategy))
        await session.execute(
            text(
                "INSERT INTO ops.system_log "
                "(level, source, event, message, detail) VALUES "
                "('info','pytest','batch.mv.transient','must rollback','{}'::jsonb)"
            )
        )
        async with AsyncSession(migrated_engine) as cancellation, cancellation.begin():
            root_id = await cancellation.scalar(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE load_batch_id = CAST(:batch_id AS uuid) "
                    "AND kind = 'full_load_batch'"
                ),
                {"batch_id": batch_id},
            )
            assert root_id is not None
            scope = await resolve_pipeline_cancellation_scope(
                cancellation, kind="import_job", execution_id=str(root_id)
            )
            assert scope is not None
            await create_pipeline_cancellation_attempt(
                cancellation,
                scope=scope,
                requested_by="admin:test",
                reason="batch phase race",
            )
        return (
            MaterializedViewRefreshResult(
                view_name="",
                strategy=strategy,
                state="sentinel:must_rollback",
            ),
        )

    monkeypatch.setattr(batch_module, "refresh_materialized_views", refresh_then_cancel)
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
        child_job_ids=[child.job_id],
        load_batch_id=batch_id,
    )

    assert result.state == "cancelled"
    assert result.root_job is not None
    assert result.root_job.status == "running"
    assert result.root_job.cancellation_id is not None
    assert refresh_calls == [((), "swap")]
    assert result.mv_refreshes == ()
    async with AsyncSession(migrated_engine) as verify:
        transient = await verify.scalar(
            text(
                "SELECT COUNT(*) FROM ops.system_log "
                "WHERE event = 'batch.mv.transient'"
            )
        )
    assert transient == 0


async def test_cancellation_rolls_back_consistency_report_and_transient_write(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")
    original_checks = batch_module.run_consistency_checks

    async def cancel_after_consistency(
        session: AsyncSession,
        *,
        batch_id: str,
        persist: bool,
        sample_limit: int,
        dedup_pending_threshold: int,
    ) -> ConsistencyReport:
        report = await original_checks(
            session,
            batch_id=batch_id,
            persist=persist,
            sample_limit=sample_limit,
            dedup_pending_threshold=dedup_pending_threshold,
        )
        await session.execute(
            text(
                "INSERT INTO ops.system_log "
                "(level, source, event, message, detail) VALUES "
                "('info','pytest','batch.consistency.transient','must rollback','{}'::jsonb)"
            )
        )
        async with AsyncSession(migrated_engine) as cancellation, cancellation.begin():
            root_id = await cancellation.scalar(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE load_batch_id = CAST(:batch_id AS uuid) "
                    "AND kind = 'full_load_batch'"
                ),
                {"batch_id": batch_id},
            )
            assert root_id is not None
            scope = await resolve_pipeline_cancellation_scope(
                cancellation,
                kind="import_job",
                execution_id=str(root_id),
            )
            assert scope is not None
            await create_pipeline_cancellation_attempt(
                cancellation,
                scope=scope,
                requested_by="admin:test",
                reason="consistency race",
            )
        return report

    monkeypatch.setattr(batch_module, "run_consistency_checks", cancel_after_consistency)
    batch_id = "aaaaaaaa-0000-0000-0000-000000000009"
    result = await AsyncKorTravelMapClient(migrated_engine).run_batch_dag_consistency_gate(
        child_job_ids=[child.job_id],
        load_batch_id=batch_id,
        consistency_persist=True,
    )

    assert result.state == "cancelled"
    async with AsyncSession(migrated_engine) as verify:
        report_count = await verify.scalar(
            text(
                "SELECT COUNT(*) FROM ops.feature_consistency_reports "
                "WHERE batch_id = CAST(:batch_id AS uuid)"
            ),
            {"batch_id": batch_id},
        )
        transient_count = await verify.scalar(
            text(
                "SELECT COUNT(*) FROM ops.system_log "
                "WHERE event = 'batch.consistency.transient'"
            )
        )
    assert report_count == transient_count == 0


async def test_prepare_batch_persists_explicit_dagster_run_identity(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        child = await start_import_job(session, kind="offline_upload_load")
        await finish_import_job(session, child.job_id, status="done")
        prepared = await prepare_batch_dag(
            session,
            make_batch_dag_request(
                child_job_ids=[child.job_id],
                load_batch_id="aaaaaaaa-0000-0000-0000-000000000011",
                dagster_run_id="batch-dagster-run-identity",
            ),
        )
        assert isinstance(prepared, BatchDagPrepared)
        stored = (
            await session.execute(
                text(
                    "SELECT dagster_run_id, payload->>'dagster_run_id' AS payload_run_id "
                    "FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": prepared.root_job.job_id},
            )
        ).one()

    assert prepared.root_job.dagster_run_id == "batch-dagster-run-identity"
    assert stored.dagster_run_id == "batch-dagster-run-identity"
    assert stored.payload_run_id == "batch-dagster-run-identity"


async def test_phase_row_lock_first_can_commit_before_cancellation_progresses(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")
        prepared = await prepare_batch_dag(
            setup,
            make_batch_dag_request(
                child_job_ids=[child.job_id],
                load_batch_id="aaaaaaaa-0000-0000-0000-000000000010",
            ),
        )
        assert isinstance(prepared, BatchDagPrepared)

    async with AsyncSession(migrated_engine) as phase:
        await phase.begin()
        await phase.execute(text("SET LOCAL lock_timeout = '1s'"))
        await phase.execute(
            text(
                "SELECT job_id FROM ops.import_jobs "
                "WHERE job_id = CAST(:job_id AS uuid) FOR UPDATE"
            ),
            {"job_id": prepared.consistency_job.job_id},
        )

        async def cancel_scope() -> None:
            async with AsyncSession(migrated_engine) as cancellation, cancellation.begin():
                await cancellation.execute(text("SET LOCAL lock_timeout = '2s'"))
                scope = await resolve_pipeline_cancellation_scope(
                    cancellation,
                    kind="import_job",
                    execution_id=prepared.root_job.job_id,
                )
                assert scope is not None
                await create_pipeline_cancellation_attempt(
                    cancellation,
                    scope=scope,
                    requested_by="admin:test",
                    reason="row lock order",
                )

        cancellation_task = asyncio.create_task(cancel_scope())
        await asyncio.sleep(0.05)
        assert cancellation_task.done() is False
        await phase.commit()
        await cancellation_task


@pytest.mark.parametrize("phase_name", ["start_mv", "failure"])
@pytest.mark.parametrize("first_owner", ["phase", "cancellation"])
async def test_tx3_and_failure_have_no_bidirectional_deadlock(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    phase_name: str,
    first_owner: str,
) -> None:
    suffix = {
        ("start_mv", "phase"): "11",
        ("start_mv", "cancellation"): "12",
        ("failure", "phase"): "13",
        ("failure", "cancellation"): "14",
    }[(phase_name, first_owner)]
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        child = await start_import_job(setup, kind="offline_upload_load")
        await finish_import_job(setup, child.job_id, status="done")
        prepared = await prepare_batch_dag(
            setup,
            make_batch_dag_request(
                child_job_ids=[child.job_id],
                load_batch_id=f"aaaaaaaa-0000-0000-0000-0000000000{suffix}",
            ),
        )
        assert isinstance(prepared, BatchDagPrepared)
    report: ConsistencyReport | None = None
    if phase_name == "start_mv":
        async with AsyncSession(migrated_engine) as consistency, consistency.begin():
            consistency_result = await run_batch_consistency_phase(
                consistency, prepared
            )
            assert isinstance(consistency_result, ConsistencyReport)
            report = consistency_result

    original_lock = batch_module.lock_pipeline_hierarchy_for_jobs
    phase_lock_attempted = asyncio.Event()
    phase_lock_acquired = asyncio.Event()
    release_phase = asyncio.Event()

    async def observed_phase_lock(
        session: AsyncSession,
        job_ids: tuple[str, ...],
    ) -> object:
        phase_lock_attempted.set()
        scopes = await original_lock(session, job_ids)
        phase_lock_acquired.set()
        if first_owner == "phase":
            await release_phase.wait()
        return scopes

    monkeypatch.setattr(
        batch_module,
        "lock_pipeline_hierarchy_for_jobs",
        observed_phase_lock,
    )

    async def run_phase() -> None:
        async with AsyncSession(migrated_engine) as phase, phase.begin():
            await phase.execute(text("SET LOCAL lock_timeout = '2s'"))
            if phase_name == "start_mv":
                assert report is not None
                await start_batch_mv_phase(phase, prepared, report)
            else:
                await fail_batch_dag_phase(
                    phase,
                    prepared,
                    message="forced failure",
                )

    if first_owner == "phase":
        phase_task = asyncio.create_task(run_phase())
        await phase_lock_acquired.wait()

        async def cancel_after_phase() -> None:
            async with AsyncSession(migrated_engine) as cancellation, cancellation.begin():
                await cancellation.execute(text("SET LOCAL lock_timeout = '2s'"))
                scope = await resolve_pipeline_cancellation_scope(
                    cancellation,
                    kind="import_job",
                    execution_id=prepared.root_job.job_id,
                )
                assert scope is not None
                await create_pipeline_cancellation_attempt(
                    cancellation,
                    scope=scope,
                    requested_by="admin:test",
                    reason="phase-first barrier",
                )

        cancellation_task = asyncio.create_task(cancel_after_phase())
        await asyncio.sleep(0.05)
        assert cancellation_task.done() is False
        release_phase.set()
        await phase_task
        await cancellation_task
    else:
        async with AsyncSession(migrated_engine) as cancellation:
            await cancellation.begin()
            await cancellation.execute(text("SET LOCAL lock_timeout = '2s'"))
            scope = await resolve_pipeline_cancellation_scope(
                cancellation,
                kind="import_job",
                execution_id=prepared.root_job.job_id,
            )
            assert scope is not None
            await lock_pipeline_lineage_mutation(cancellation)
            phase_task = asyncio.create_task(run_phase())
            await phase_lock_attempted.wait()
            await create_pipeline_cancellation_attempt(
                cancellation,
                scope=scope,
                requested_by="admin:test",
                reason="cancellation-first barrier",
            )
            await cancellation.commit()
        with pytest.raises(BatchDagCancellationWon):
            await phase_task
