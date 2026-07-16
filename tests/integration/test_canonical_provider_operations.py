"""C3e-A1 canonical provider operation lifecycle 통합 회귀."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from dagster import AssetKey, DagsterRunStatus
from kortravelmap.dagster.feature_operation_sensors import (
    FeatureOperationReconcileCursor,
    _apply_run_record,
    _reconcile_tick,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import (
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationKey,
)
from kortravelmap.infra.feature_operation_repo import (
    append_dagster_feature_attempt_event,
    ensure_dagster_feature_operation,
    finish_dagster_feature_pair,
    list_reconcilable_dagster_feature_runs,
    reconcile_dagster_feature_run,
)
from kortravelmap.infra.jobs_repo import (
    claim_next_import_job,
    enqueue_unpaired_import_job,
    heartbeat_import_job,
    record_import_job_event,
    recover_stale_running_jobs,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    cancel_queued_pipeline_cancellation_member,
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationInvariantError,
)
from kortravelmap.providers.feature_operation_registry import (
    feature_operation_launch_tags,
    resolve_feature_operation_launch,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _delete_committed_feature_tree(
    engine: AsyncEngine,
    *,
    root_id: str,
    cancellation_id: str | None = None,
) -> None:
    async with AsyncSession(engine) as cleanup, cleanup.begin():
        await cleanup.execute(
            text(
                "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                "cancellation_reason=NULL "
                "WHERE job_id=CAST(:root_id AS uuid) "
                "OR parent_job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )
        if cancellation_id is not None:
            for statement in (
                "DELETE FROM ops.pipeline_cancellation_members "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
                "DELETE FROM ops.pipeline_cancellation_runs "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
                "DELETE FROM ops.pipeline_cancellations "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
            ):
                await cleanup.execute(
                    text(statement),
                    {"cancellation_id": cancellation_id},
                )
        await cleanup.execute(
            text(
                "DELETE FROM ops.import_jobs "
                "WHERE parent_job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM ops.import_jobs WHERE job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )


def _tracking_record(
    *,
    job_name: str,
    run_id: str,
    status: DagsterRunStatus,
    created_at: datetime,
    started_at: datetime | None,
    finished_at: datetime | None,
    storage_id: int = 1,
) -> Any:
    launch = resolve_feature_operation_launch(job_name=job_name)
    assert launch is not None
    identity, run_config = launch
    return SimpleNamespace(
        storage_id=storage_id,
        dagster_run=SimpleNamespace(
            run_id=run_id,
            job_name=job_name,
            status=status,
            run_config=run_config,
            tags=feature_operation_launch_tags(
                identity, trigger_kind="schedule"
            ),
            asset_selection=frozenset(
                AssetKey.from_user_string(key) for key in identity.asset_keys
            ),
        ),
        create_timestamp=created_at,
        start_time=started_at.timestamp() if started_at is not None else None,
        end_time=finished_at.timestamp() if finished_at is not None else None,
    )


class _PeriodicDagsterInstance:
    def __init__(self, records: list[Any]) -> None:
        self._records = {
            record.dagster_run.run_id: record for record in records
        }

    def get_run_record_by_id(self, run_id: str) -> Any | None:
        return self._records.get(run_id)

    def get_run_records(self, **_kwargs: Any) -> list[Any]:
        return []


class _PeriodicLog:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)


class _PeriodicContext:
    def __init__(self, records: list[Any]) -> None:
        self.instance = _PeriodicDagsterInstance(records)
        self.cursor = FeatureOperationReconcileCursor().to_json()
        self.log = _PeriodicLog()
        self.updated_cursors: list[str] = []

    def update_cursor(self, cursor: str) -> None:
        self.updated_cursors.append(cursor)


async def test_feature_operation_lifecycle_is_idempotent_and_never_reverses(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=2)
    finished_at = started_at + timedelta(seconds=3)
    pairs = (
        ProviderDatasetOperationKey("python-kma-api", "forecast"),
        ProviderDatasetOperationKey("python-mcst-api", "museum"),
    )

    queued = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-lifecycle",
        trigger_kind="schedule",
        selected_pairs=pairs,
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert queued.outcome == "applied"
    assert queued.operation.status == "queued"
    assert len(queued.operation.members) == 2

    started = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-lifecycle",
        trigger_kind="schedule",
        selected_pairs=tuple(reversed(pairs)),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    assert started.operation.status == "running"
    assert started.operation.dagster_run_status == "STARTED"
    assert {member.status for member in started.operation.members} == {"running"}

    late_queued = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-lifecycle",
        trigger_kind="schedule",
        selected_pairs=pairs,
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert late_queued.outcome == "noop"
    assert late_queued.operation.status == "running"
    assert late_queued.operation.dagster_run_status == "STARTED"

    for pair in pairs:
        completed = await finish_dagster_feature_pair(
            migrated_session,
            dagster_run_id="run-c3e-lifecycle",
            pair=pair,
        )
    assert completed.operation.progress == 100

    terminal = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id="run-c3e-lifecycle",
        trigger_kind="schedule",
        terminal_status="SUCCESS",
        selected_pairs=pairs,
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=finished_at,
        error=None,
    )
    assert terminal.operation.status == "done"
    assert terminal.operation.progress == 100
    assert terminal.operation.finished_at == finished_at


async def test_selection_conflict_rolls_back_without_attaching_pair(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    original = ProviderDatasetOperationKey("python-knps-api", "park")
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-conflict",
        trigger_kind="manual",
        selected_pairs=(original,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )

    with pytest.raises(FeatureOperationInvariantConflict):
        await ensure_dagster_feature_operation(
            migrated_session,
            dagster_run_id="run-c3e-conflict",
            trigger_kind="manual",
            selected_pairs=(
                original,
                ProviderDatasetOperationKey("python-knps-api", "trail"),
            ),
            registry_version="registry-v1",
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    child_count = await migrated_session.scalar(
        text(
            """
            SELECT count(*) FROM ops.import_jobs AS child
            JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
            WHERE root.dagster_run_id = 'run-c3e-conflict'
              AND child.kind = 'provider_feature_load'
            """
        )
    )
    assert child_count == 1


async def test_same_run_concurrent_ensure_creates_one_complete_tree(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-concurrent-{uuid4()}"
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    pairs = tuple(
        ProviderDatasetOperationKey("provider", f"dataset-{index}")
        for index in range(3)
    )
    start = asyncio.Event()

    async def ensure_once() -> Any:
        await start.wait()
        async with AsyncSession(migrated_engine) as session, session.begin():
            return await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="sensor",
                selected_pairs=tuple(reversed(pairs)),
                registry_version="registry-v1",
                engine_created_at=created_at,
                engine_started_at=None,
                observed_status="QUEUED",
            )

    tasks = (asyncio.create_task(ensure_once()), asyncio.create_task(ensure_once()))
    start.set()
    first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    root_id = first.operation.root_job_id
    try:
        assert second.operation.root_job_id == root_id
        assert {first.outcome, second.outcome} == {"applied", "noop"}
        async with AsyncSession(migrated_engine) as probe:
            counts = (
                await probe.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE parent_job_id IS NULL) AS roots, "
                        "count(*) FILTER (WHERE parent_job_id IS NOT NULL) AS children "
                        "FROM ops.import_jobs WHERE dagster_run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).one()
        assert int(counts.roots) == 1
        assert int(counts.children) == len(pairs)
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


@pytest.mark.parametrize("winner", ["marker", "started_ensure"])
async def test_started_ensure_and_cancellation_marker_barrier_has_no_escape(
    migrated_engine: AsyncEngine,
    winner: str,
) -> None:
    run_id = f"run-c3e-marker-race-{winner}-{uuid4()}"
    created_at = datetime(2026, 7, 15, 3, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    pairs = (
        ProviderDatasetOperationKey("provider", "first"),
        ProviderDatasetOperationKey("provider", "second"),
    )
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        queued = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_pairs=pairs,
            registry_version="registry-v1",
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    root_id = queued.operation.root_job_id
    first_write_done = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def mark_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            scope = await resolve_pipeline_cancellation_scope(
                session, kind="import_job", execution_id=root_id
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:race",
                reason=winner,
            )
            first_write_done.set()
            await release_first.wait()
            return detail

    async def start_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            mutation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="manual",
                selected_pairs=pairs,
                registry_version="registry-v1",
                engine_created_at=created_at,
                engine_started_at=started_at,
                observed_status="STARTED",
            )
            first_write_done.set()
            await release_first.wait()
            return mutation

    if winner == "marker":
        first_task = asyncio.create_task(mark_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(start_and_hold(entered=second_entered))
    else:
        first_task = asyncio.create_task(start_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(mark_and_hold(entered=second_entered))
    await second_entered.wait()
    await asyncio.sleep(0)
    assert not second_task.done()
    release_first.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task), timeout=5
    )
    if winner == "marker":
        detail, mutation = first_result, second_result
        assert mutation.outcome == "blocked"
        assert mutation.block_reason == "cancellation"
        expected_status = "queued"
    else:
        mutation, detail = first_result, second_result
        assert mutation.operation.status == "running"
        expected_status = "running"

    cancellation_id = detail.attempt.cancellation_id
    try:
        assert len(detail.members) == len(pairs) + 1
        assert {member.initial_status for member in detail.members} == {
            expected_status
        }
        assert all(member.requires_run_termination for member in detail.members)
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert len(rows) == len(pairs) + 1
        assert {row.status for row in rows} == {expected_status}
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_direct_cancel_is_idempotent_with_real_client(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-sensor-direct-cancel-{uuid4()}"
    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    record = _tracking_record(
        job_name="feature_place_mois_licenses_job",
        run_id=run_id,
        status=DagsterRunStatus.CANCELED,
        created_at=created_at,
        started_at=None,
        finished_at=finished_at,
    )
    client = AsyncKorTravelMapClient(migrated_engine)

    first = await _apply_run_record(record, client)
    second = await _apply_run_record(record, client)

    async with AsyncSession(migrated_engine) as probe:
        rows = (
            await probe.execute(
                text(
                    "SELECT job_id, parent_job_id, status, current_stage, "
                    "dagster_run_status, finished_at "
                    "FROM ops.import_jobs WHERE dagster_run_id=:run_id "
                    "ORDER BY parent_job_id NULLS FIRST, job_id"
                ),
                {"run_id": run_id},
            )
        ).all()
    root_id = str(rows[0].job_id)
    try:
        assert first == "applied"
        assert second == "blocked"
        assert len(rows) == 2
        assert {row.status for row in rows} == {"cancelled"}
        assert {row.current_stage for row in rows} == {"cancelled"}
        assert rows[0].dagster_run_status == "CANCELED"
        assert {row.finished_at for row in rows} == {finished_at}
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_terminal_sensor_respects_existing_cancellation_marker(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-sensor-marker-{uuid4()}"
    created_at = datetime(2026, 7, 16, 2, tzinfo=UTC)
    launch = resolve_feature_operation_launch(
        job_name="feature_place_mois_licenses_job"
    )
    assert launch is not None
    identity, _ = launch
    client = AsyncKorTravelMapClient(migrated_engine)
    queued = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_pairs=identity.pairs,
        registry_version=identity.registry_version,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = queued.operation.root_job_id
    async with AsyncSession(migrated_engine) as marker_session, marker_session.begin():
        scope = await resolve_pipeline_cancellation_scope(
            marker_session,
            kind="import_job",
            execution_id=root_id,
        )
        assert scope is not None
        detail = await create_pipeline_cancellation_attempt(
            marker_session,
            scope=scope,
            requested_by="admin:sensor-test",
            reason="marker must own terminal",
        )
    cancellation_id = detail.attempt.cancellation_id
    record = _tracking_record(
        job_name="feature_place_mois_licenses_job",
        run_id=run_id,
        status=DagsterRunStatus.CANCELED,
        created_at=created_at,
        started_at=None,
        finished_at=created_at + timedelta(seconds=1),
    )

    outcome = await _apply_run_record(record, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, current_stage, dagster_run_status, "
                        "cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert outcome == "blocked"
        assert len(rows) == len(identity.pairs) + 1
        assert {row.status for row in rows} == {"queued"}
        assert {row.current_stage for row in rows} == {"queued"}
        assert rows[0].dagster_run_status == "QUEUED"
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_preserves_partial_success_and_duplicate_delivery(
    migrated_engine: AsyncEngine,
) -> None:
    job_name = "feature_place_mcst_culture_job"
    run_id = f"run-c3e-sensor-partial-{uuid4()}"
    created_at = datetime(2026, 7, 16, 3, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=2)
    launch = resolve_feature_operation_launch(job_name=job_name)
    assert launch is not None
    identity, _ = launch
    client = AsyncKorTravelMapClient(migrated_engine)
    await _apply_run_record(
        _tracking_record(
            job_name=job_name,
            run_id=run_id,
            status=DagsterRunStatus.STARTED,
            created_at=created_at,
            started_at=started_at,
            finished_at=None,
        ),
        client,
    )
    first_pair = identity.pairs[0]
    completed = await client.finish_dagster_feature_pair(
        dagster_run_id=run_id,
        pair=first_pair,
    )
    root_id = completed.operation.root_job_id
    terminal_record = _tracking_record(
        job_name=job_name,
        run_id=run_id,
        status=DagsterRunStatus.FAILURE,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )

    first = await _apply_run_record(terminal_record, client)
    second = await _apply_run_record(terminal_record, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT parent_job_id, provider, dataset_key, status, progress, "
                        "current_stage, dagster_run_status FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, provider, dataset_key"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        root = rows[0]
        children = rows[1:]
        assert first == "applied"
        assert second == "blocked"
        assert len(children) == len(identity.pairs)
        assert root.status == "failed"
        assert root.dagster_run_status == "FAILURE"
        assert root.progress == 100 // len(identity.pairs)
        assert [row.status for row in children].count("done") == 1
        assert [row.status for row in children].count("failed") == (
            len(identity.pairs) - 1
        )
        done = next(row for row in children if row.status == "done")
        assert (done.provider, done.dataset_key) == (
            first_pair.provider,
            first_pair.dataset_key,
        )
        assert done.current_stage == "completed"
        assert {row.current_stage for row in children if row.status == "failed"} == {
            "failed"
        }
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_periodic_reconcile_real_client_closes_partial_active_page_and_commits_cursor(
    migrated_engine: AsyncEngine,
) -> None:
    job_name = "feature_place_mcst_culture_job"
    run_id = f"run-c3e-periodic-partial-{uuid4()}"
    created_at = datetime(2026, 7, 15, 5, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=2)
    launch = resolve_feature_operation_launch(job_name=job_name)
    assert launch is not None
    identity, _ = launch
    client = AsyncKorTravelMapClient(migrated_engine)
    started = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_pairs=identity.pairs,
        registry_version=identity.registry_version,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    root_id = started.operation.root_job_id
    first_pair = identity.pairs[0]
    await client.finish_dagster_feature_pair(
        dagster_run_id=run_id,
        pair=first_pair,
    )
    context = _PeriodicContext(
        [
            _tracking_record(
                job_name=job_name,
                run_id=run_id,
                status=DagsterRunStatus.FAILURE,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
            )
        ]
    )

    await _reconcile_tick(context, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT parent_job_id, provider, dataset_key, status, progress, "
                        "current_stage, dagster_run_status FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, provider, dataset_key"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        root = rows[0]
        children = rows[1:]
        committed = FeatureOperationReconcileCursor.from_json(
            context.updated_cursors[0]
        )
        assert root.status == "failed"
        assert root.dagster_run_status == "FAILURE"
        assert root.progress == 100 // len(identity.pairs)
        assert [row.status for row in children].count("done") == 1
        assert [row.status for row in children].count("failed") == (
            len(identity.pairs) - 1
        )
        done = next(row for row in children if row.status == "done")
        assert (done.provider, done.dataset_key) == (
            first_pair.provider,
            first_pair.dataset_key,
        )
        assert len(context.updated_cursors) == 1
        assert committed.database is None
        assert context.log.errors == []
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_periodic_reconcile_marker_after_page_read_preserves_base(
    migrated_engine: AsyncEngine,
) -> None:
    job_name = "feature_place_mois_licenses_job"
    run_id = f"run-c3e-periodic-marker-race-{uuid4()}"
    created_at = datetime(2026, 7, 15, 6, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    launch = resolve_feature_operation_launch(job_name=job_name)
    assert launch is not None
    identity, _ = launch

    class MarkerAfterPageClient(AsyncKorTravelMapClient):
        cancellation_id: str | None = None

        async def list_reconcilable_dagster_feature_runs(
            self,
            *,
            cursor: Any,
            page_size: int = 200,
        ) -> Any:
            page = await super().list_reconcilable_dagster_feature_runs(
                cursor=cursor,
                page_size=page_size,
            )
            if self.cancellation_id is None:
                async with AsyncSession(migrated_engine) as session, session.begin():
                    scope = await resolve_pipeline_cancellation_scope(
                        session,
                        kind="import_job",
                        execution_id=root_id,
                    )
                    assert scope is not None
                    detail = await create_pipeline_cancellation_attempt(
                        session,
                        scope=scope,
                        requested_by="admin:periodic-race",
                        reason="marker wins after active page read",
                    )
                    self.cancellation_id = detail.attempt.cancellation_id
            return page

    client = MarkerAfterPageClient(migrated_engine)
    queued = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_pairs=identity.pairs,
        registry_version=identity.registry_version,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = queued.operation.root_job_id
    context = _PeriodicContext(
        [
            _tracking_record(
                job_name=job_name,
                run_id=run_id,
                status=DagsterRunStatus.CANCELED,
                created_at=created_at,
                started_at=None,
                finished_at=finished_at,
            )
        ]
    )

    await _reconcile_tick(context, client)

    try:
        assert client.cancellation_id is not None
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, current_stage, dagster_run_status, "
                        "cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert {row.status for row in rows} == {"queued"}
        assert {row.current_stage for row in rows} == {"queued"}
        assert rows[0].dagster_run_status == "QUEUED"
        assert {str(row.cancellation_id) for row in rows} == {
            client.cancellation_id
        }
        assert len(context.updated_cursors) == 1
        assert context.log.errors == []
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=client.cancellation_id,
        )


@pytest.mark.parametrize("winner", ["marker", "terminal"])
async def test_terminal_reconcile_and_marker_race_has_single_lock_order_winner(
    migrated_engine: AsyncEngine,
    winner: str,
) -> None:
    run_id = f"run-c3e-terminal-marker-race-{winner}-{uuid4()}"
    created_at = datetime(2026, 7, 15, 7, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    pair = ProviderDatasetOperationKey("provider", "terminal-marker-race")
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        queued = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="schedule",
            selected_pairs=(pair,),
            registry_version="registry-v1",
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    root_id = queued.operation.root_job_id
    first_write_done = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def mark_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            scope = await resolve_pipeline_cancellation_scope(
                session,
                kind="import_job",
                execution_id=root_id,
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:terminal-race",
                reason=winner,
            )
            first_write_done.set()
            await release_first.wait()
            return detail

    async def terminal_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            mutation = await reconcile_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                terminal_status="CANCELED",
                selected_pairs=(pair,),
                registry_version="registry-v1",
                engine_created_at=created_at,
                engine_started_at=None,
                engine_finished_at=finished_at,
                error={"kind": "terminal-marker-race"},
            )
            first_write_done.set()
            await release_first.wait()
            return mutation

    if winner == "marker":
        first_task = asyncio.create_task(mark_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(
            terminal_and_hold(entered=second_entered)
        )
    else:
        first_task = asyncio.create_task(terminal_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(mark_and_hold(entered=second_entered))
    await second_entered.wait()
    await asyncio.sleep(0)
    assert not second_task.done()
    release_first.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task),
        timeout=5,
    )
    if winner == "marker":
        detail, mutation = first_result, second_result
        assert mutation.outcome == "blocked"
        assert mutation.block_reason == "cancellation"
        expected_status = "queued"
        expected_raw_status = "QUEUED"
    else:
        mutation, detail = first_result, second_result
        assert mutation.outcome == "applied"
        expected_status = "cancelled"
        expected_raw_status = "CANCELED"
    cancellation_id = detail.attempt.cancellation_id

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, dagster_run_status, cancellation_id "
                        "FROM ops.import_jobs WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert len(rows) == 2
        assert {row.status for row in rows} == {expected_status}
        assert rows[0].dagster_run_status == expected_raw_status
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_selection_mismatch_closes_active_tree(
    migrated_engine: AsyncEngine,
) -> None:
    job_name = "feature_place_mois_licenses_job"
    run_id = f"run-c3e-sensor-selection-mismatch-{uuid4()}"
    created_at = datetime(2026, 7, 16, 4, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    launch = resolve_feature_operation_launch(job_name=job_name)
    assert launch is not None
    identity, _ = launch
    client = AsyncKorTravelMapClient(migrated_engine)
    stored = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_pairs=(
            ProviderDatasetOperationKey(
                identity.pairs[0].provider,
                "sensor-selection-drift",
            ),
        ),
        registry_version=identity.registry_version,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="NOT_STARTED",
    )
    root_id = stored.operation.root_job_id

    outcome = await _apply_run_record(
        _tracking_record(
            job_name=job_name,
            run_id=run_id,
            status=DagsterRunStatus.SUCCESS,
            created_at=created_at,
            started_at=None,
            finished_at=finished_at,
        ),
        client,
    )

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT parent_job_id, status, current_stage, "
                        "dagster_run_status FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
            tracking_log_count = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.system_log "
                    "WHERE event='feature_operation.tracking_invariant' "
                    "AND detail->>'dagster_run_id'=:run_id"
                ),
                {"run_id": run_id},
            )
        assert outcome == "applied"
        assert len(rows) == 2
        assert {row.status for row in rows} == {"failed"}
        assert {row.current_stage for row in rows} == {"tracking_invariant"}
        assert rows[0].dagster_run_status == "SUCCESS"
        assert int(tracking_log_count or 0) == 1
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_generic_claim_and_stale_recovery_ignore_feature_operations(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 3, tzinfo=UTC)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-owned",
        trigger_kind="sensor",
        selected_pairs=(ProviderDatasetOperationKey("python-kma-api", "forecast"),),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert await claim_next_import_job(migrated_session) is None

    started_at = created_at + timedelta(seconds=1)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-owned",
        trigger_kind="sensor",
        selected_pairs=(ProviderDatasetOperationKey("python-kma-api", "forecast"),),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    assert await recover_stale_running_jobs(migrated_session, stale_after=None) == 0


async def test_active_root_sweep_uses_keyset_and_wraps_at_end(
    migrated_session: AsyncSession,
) -> None:
    for index in range(2):
        await ensure_dagster_feature_operation(
            migrated_session,
            dagster_run_id=f"run-c3e-page-{index}",
            trigger_kind="system",
            selected_pairs=(ProviderDatasetOperationKey("provider", f"dataset-{index}"),),
            registry_version="registry-v1",
            engine_created_at=datetime(2026, 7, 15, 4 + index, tzinfo=UTC),
            engine_started_at=None,
            observed_status="QUEUED",
        )
    first = await list_reconcilable_dagster_feature_runs(
        migrated_session, cursor=None, page_size=1
    )
    assert len(first.items) == 1
    assert first.next_cursor is not None
    second = await list_reconcilable_dagster_feature_runs(
        migrated_session, cursor=first.next_cursor, page_size=1
    )
    assert len(second.items) == 1
    assert second.next_cursor is None


async def test_reserved_feature_tree_rejects_generic_writers(
    migrated_session: AsyncSession,
) -> None:
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-reserved",
        trigger_kind="manual",
        selected_pairs=(ProviderDatasetOperationKey("provider", "dataset"),),
        registry_version="registry-v1",
        engine_created_at=datetime(2026, 7, 15, 6, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = operation.operation.root_job_id
    child = operation.operation.members[0]

    with pytest.raises(FeatureOperationInvariantConflict):
        await enqueue_unpaired_import_job(
            migrated_session,
            kind="generic_child",
            parent_job_id=root_id,
        )
    with pytest.raises(FeatureOperationInvariantConflict):
        await heartbeat_import_job(migrated_session, root_id, progress=10)
    with pytest.raises(FeatureOperationInvariantConflict):
        await record_import_job_event(
            migrated_session,
            child.job_id,
            level="info",
            message="mismatched pair",
            provider="other-provider",
            dataset_key="other-dataset",
        )


async def test_attempt_event_inherits_pair_without_mutating_member_identity(
    migrated_session: AsyncSession,
) -> None:
    pair = ProviderDatasetOperationKey("provider", "dataset")
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-attempt-audit",
        trigger_kind="manual",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=datetime(2026, 7, 15, 6, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    job_id = operation.operation.members[0].job_id

    event = await append_dagster_feature_attempt_event(
        migrated_session,
        dagster_run_id="run-c3e-attempt-audit",
        pair=pair,
        attempt_number=1,
        outcome="retryable_failure",
        error={"code": "timeout"},
    )
    stored = (
        await migrated_session.execute(
            text(
                "SELECT provider, dataset_key FROM ops.import_jobs "
                "WHERE job_id=CAST(:job_id AS uuid)"
            ),
            {"job_id": job_id},
        )
    ).one()

    assert (event.provider, event.dataset_key) == (pair.provider, pair.dataset_key)
    assert (stored.provider, stored.dataset_key) == (pair.provider, pair.dataset_key)


async def test_run_backed_queued_cancellation_freezes_one_run_and_all_pairs(
    migrated_session: AsyncSession,
) -> None:
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-queued-cancel",
        trigger_kind="manual",
        selected_pairs=(
            ProviderDatasetOperationKey("provider", "dataset-a"),
            ProviderDatasetOperationKey("provider", "dataset-b"),
        ),
        registry_version="registry-v1",
        engine_created_at=datetime(2026, 7, 15, 7, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=operation.operation.root_job_id,
    )
    assert scope is not None
    assert len(scope.members) == 3
    assert all(member.requires_run_termination for member in scope.members)

    detail = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:test",
        reason="queued feature cancellation",
    )
    assert len(detail.runs) == 1
    assert detail.runs[0].result == "pending"
    assert all(member.requires_run_termination for member in detail.members)

    with pytest.raises(PipelineCancellationInvariantError):
        await cancel_queued_pipeline_cancellation_member(
            migrated_session,
            cancellation_id=detail.attempt.cancellation_id,
            job_id=detail.members[0].job_id,
        )


async def test_feature_identity_trigger_blocks_update_delete_and_bad_parent(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 8, tzinfo=UTC)
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-identity-trigger",
        trigger_kind="manual",
        selected_pairs=(ProviderDatasetOperationKey("provider", "dataset"),),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = operation.operation.root_job_id
    child_id = operation.operation.members[0].job_id

    statements = (
        (
            "UPDATE ops.import_jobs SET trigger_kind='system' "
            "WHERE job_id=CAST(:id AS uuid)",
            root_id,
        ),
        (
            "UPDATE ops.import_jobs SET dataset_key='other' "
            "WHERE job_id=CAST(:id AS uuid)",
            child_id,
        ),
        (
            "DELETE FROM ops.import_jobs WHERE job_id=CAST(:id AS uuid)",
            root_id,
        ),
    )
    for statement, target_id in statements:
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(text(statement), {"id": target_id})

    for bad_run_id, bad_created_at in (
        ("other-run", created_at),
        ("run-c3e-identity-trigger", created_at + timedelta(seconds=1)),
    ):
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, parent_job_id, payload, status, dagster_run_id,
                          provider, dataset_key, created_at
                        ) VALUES (
                          'provider_feature_load', CAST(:root_id AS uuid), '{}'::jsonb,
                          'queued', :run_id, 'provider', :dataset_key,
                          CAST(:created_at AS timestamptz)
                        )
                        """
                    ),
                    {
                        "root_id": root_id,
                        "run_id": bad_run_id,
                        "dataset_key": f"bad-{bad_run_id}",
                        "created_at": bad_created_at,
                    },
                )


@pytest.mark.parametrize("terminal_status", ["SUCCESS", "FAILURE", "CANCELED"])
async def test_every_terminal_identity_mismatch_closes_tracking_invariant(
    migrated_session: AsyncSession,
    terminal_status: str,
) -> None:
    created_at = datetime(2026, 7, 15, 9, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=f"run-c3e-mismatch-{terminal_status.lower()}",
        trigger_kind="sensor",
        selected_pairs=(ProviderDatasetOperationKey("provider", "actual"),),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    result = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=operation.operation.dagster_run_id,
        trigger_kind="manual",
        terminal_status=terminal_status,
        selected_pairs=(ProviderDatasetOperationKey("provider", "expected"),),
        registry_version="registry-v2",
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=started_at + timedelta(seconds=1),
        error=None,
    )

    assert result.operation.status == "failed"
    assert result.operation.current_stage == "tracking_invariant"
    assert result.operation.dagster_run_status == terminal_status
    assert {member.status for member in result.operation.members} == {"failed"}
    log = (
        await migrated_session.execute(
            text(
                """
                SELECT detail FROM ops.system_log
                WHERE event = 'feature_operation.tracking_invariant'
                  AND detail->>'dagster_run_id' = :run_id
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"run_id": operation.operation.dagster_run_id},
        )
    ).scalar_one()
    expected_mismatch_keys = {
        "registry_version",
        "selected_pairs",
        "trigger_kind",
    }
    if terminal_status == "SUCCESS":
        expected_mismatch_keys.add("non_done_members")
    assert set(log["mismatches"]) == expected_mismatch_keys
    assert log["mismatches"]["registry_version"] == {
        "expected": "registry-v2",
        "actual": "registry-v1",
    }
    assert log["mismatches"]["trigger_kind"] == {
        "expected": "manual",
        "actual": "sensor",
    }


async def test_terminal_finish_cannot_precede_stored_engine_start(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 10, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=10)
    pair = ProviderDatasetOperationKey("provider", "dataset")
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-invalid-finish",
        trigger_kind="manual",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id="run-c3e-invalid-finish",
        trigger_kind="manual",
        terminal_status="FAILURE",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        engine_finished_at=created_at + timedelta(seconds=5),
        error=None,
    )
    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.started_at == started_at
    assert reconciled.operation.finished_at is None
    assert {member.status for member in reconciled.operation.members} == {"failed"}
    assert all(member.finished_at is None for member in reconciled.operation.members)


async def test_terminal_created_time_drift_closes_without_invented_finish(
    migrated_session: AsyncSession,
) -> None:
    stored_created_at = datetime(2026, 7, 15, 11, tzinfo=UTC)
    pair = ProviderDatasetOperationKey("provider", "dataset")
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-created-time-drift",
        trigger_kind="sensor",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=stored_created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="CANCELED",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=stored_created_at - timedelta(hours=1),
        engine_started_at=None,
        engine_finished_at=stored_created_at - timedelta(minutes=30),
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.dagster_run_status == "CANCELED"
    assert reconciled.operation.started_at is None
    assert reconciled.operation.finished_at is None
    assert {member.status for member in reconciled.operation.members} == {"failed"}
    active_count = await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.import_jobs "
            "WHERE (job_id = CAST(:root_id AS uuid) "
            "OR parent_job_id = CAST(:root_id AS uuid)) "
            "AND status IN ('queued','running')"
        ),
        {"root_id": ensured.operation.root_job_id},
    )
    assert int(active_count) == 0


async def test_terminal_detects_divergent_root_and_child_start_times(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    incoming_started_at = created_at + timedelta(seconds=10)
    stored_child_started_at = created_at + timedelta(seconds=12)
    pair = ProviderDatasetOperationKey("provider", "dataset")
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-divergent-child-start",
        trigger_kind="sensor",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    child_id = ensured.operation.members[0].job_id
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET started_at = :started_at "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": child_id, "started_at": stored_child_started_at},
    )

    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="FAILURE",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=incoming_started_at,
        engine_finished_at=created_at + timedelta(seconds=13),
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.started_at is None
    assert reconciled.operation.finished_at is None
    assert reconciled.operation.members[0].started_at == stored_child_started_at
    assert reconciled.operation.members[0].finished_at is None


@pytest.mark.parametrize("stored_child_status", ["failed", "cancelled"])
async def test_success_preserves_terminal_non_done_child_and_fails_root_tracking(
    migrated_session: AsyncSession,
    stored_child_status: str,
) -> None:
    created_at = datetime(2026, 7, 15, 13, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = created_at + timedelta(seconds=5)
    pair = ProviderDatasetOperationKey("provider", stored_child_status)
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=f"run-c3e-success-{stored_child_status}",
        trigger_kind="sensor",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    child_id = ensured.operation.members[0].job_id
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs "
            "SET status=:status, current_stage=:status, finished_at=:finished_at "
            "WHERE job_id=CAST(:job_id AS uuid)"
        ),
        {
            "job_id": child_id,
            "status": stored_child_status,
            "finished_at": finished_at,
        },
    )

    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="SUCCESS",
        selected_pairs=(pair,),
        registry_version="registry-v1",
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=finished_at,
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.dagster_run_status == "SUCCESS"
    assert reconciled.operation.finished_at == finished_at
    assert reconciled.operation.members[0].status == stored_child_status
    assert reconciled.operation.members[0].finished_at == finished_at
