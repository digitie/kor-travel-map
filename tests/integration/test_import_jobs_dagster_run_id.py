"""``ops.import_jobs.dagster_run_id`` 실컬럼 기록 경로 통합 테스트 (ADR-064).

jobs_repo의 명시적 ``dagster_run_id``/bind 경로와 `/ops/live` Dagster snapshot
실컬럼 조회를 검증한다. payload는 신규 writer의 실행 identity가 아니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.jobs_repo import (
    ImportJobDatasetTarget,
    bind_import_job_dagster_run,
    enqueue_provider_dataset_import_job,
    enqueue_unpaired_import_job,
    record_import_job_event,
    start_unpaired_import_job,
    update_import_job_payload,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _canonical_membership(session: AsyncSession) -> ImportJobDatasetTarget:
    """catalog에서 활성 refresh triple 하나를 골라 job membership으로 만든다.

    T-VN-33 이후 job identity는 ``provider_dataset_id + sync_scope + operation_key``
    뿐이다 — provider/dataset_key 사본은 ``ops.import_jobs``에서 사라졌고 membership은
    ``ops.import_job_datasets``가 든다(ADR-088). 0089가 catalog를 seed하므로 실제 행을
    읽어 쓴다.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                WHERE dataset.is_active AND operation.is_enabled
                  AND scope.operation_kind = 'refresh'
                ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
                LIMIT 1
                """
            )
        )
    ).one()
    return ImportJobDatasetTarget(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


async def _column_value(session: AsyncSession, job_id: str) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT dagster_run_id FROM ops.import_jobs "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": job_id},
        )
    ).scalar_one()


async def test_enqueue_writes_explicit_dagster_run_id(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="provider_load",
        payload={"provider": "python-kma-api", "dagster_run_id": "run-enqueue"},
        dagster_run_id="run-enqueue",
    )

    assert job.dagster_run_id == "run-enqueue"
    assert await _column_value(migrated_session, job.job_id) == "run-enqueue"


async def test_generic_exact_membership_is_stored_and_inherited_by_events(
    migrated_session: AsyncSession,
) -> None:
    membership = await _canonical_membership(migrated_session)
    job = await enqueue_provider_dataset_import_job(
        migrated_session,
        kind="provider_load",
        dataset_membership=membership,
        trigger_kind="manual",
    )
    assert job.dataset_membership_mode != "root"
    assert [
        (member.provider_dataset_id, member.sync_scope, member.operation_key)
        for member in job.dataset_memberships
    ] == [
        (
            membership.provider_dataset_id,
            membership.sync_scope,
            membership.operation_key,
        )
    ]
    stored = job.dataset_memberships[0]

    event = await record_import_job_event(
        migrated_session,
        job.job_id,
        level="info",
        message="identity inherited",
        import_job_dataset_id=stored.import_job_dataset_id,
    )

    assert job.trigger_kind == "manual"
    assert event is not None
    assert event.import_job_dataset_id == stored.import_job_dataset_id
    # event가 실제로 job membership triple을 상속했는지 DB에서 재확인한다.
    assert (
        await migrated_session.execute(
            text(
                "SELECT member.provider_dataset_id, member.sync_scope, "
                "       member.operation_key "
                "FROM ops.import_job_events AS event "
                "JOIN ops.import_job_datasets AS member "
                "  ON member.import_job_dataset_id = event.import_job_dataset_id "
                "WHERE event.event_id = CAST(:event_id AS uuid)"
            ),
            {"event_id": event.event_id},
        )
    ).one() == (
        membership.provider_dataset_id,
        membership.sync_scope,
        membership.operation_key,
    )


async def test_start_does_not_infer_legacy_payload_run_id(
    migrated_session: AsyncSession,
) -> None:
    job = await start_unpaired_import_job(
        migrated_session,
        kind="provider_load",
        payload={"run_id": "run-legacy"},
    )

    assert job.dagster_run_id is None
    assert await _column_value(migrated_session, job.job_id) is None


async def test_enqueue_without_run_id_leaves_column_null(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="provider_load",
        payload={"provider": "python-kma-api"},
    )

    assert job.dagster_run_id is None
    assert await _column_value(migrated_session, job.job_id) is None


async def test_explicit_bind_sets_and_payload_update_keeps_run_id(
    migrated_session: AsyncSession,
) -> None:
    job = await start_unpaired_import_job(
        migrated_session,
        kind="offline_upload_load",
        payload={"upload_id": "u-1"},
    )
    assert job.dagster_run_id is None

    # offline_upload preclaim처럼 실행 도중 명시적으로 run id를 연결하는 케이스.
    updated = await bind_import_job_dagster_run(
        migrated_session,
        job.job_id,
        dagster_run_id="run-late",
    )
    assert updated is not None
    assert updated.dagster_run_id == "run-late"

    # run id 없는 payload로 교체해도 기존 컬럼 값은 유지한다.
    replaced = await update_import_job_payload(
        migrated_session,
        job.job_id,
        payload={"upload_id": "u-1", "summary": {"rows": 3}},
    )
    assert replaced is not None
    assert replaced.dagster_run_id == "run-late"
    assert await _column_value(migrated_session, job.job_id) == "run-late"


async def test_ops_live_dagster_snapshots_use_real_column(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.api.routers.ops_live import (
        _dagster_run_snapshot,
        _dagster_runs_snapshot,
    )

    linked = await start_unpaired_import_job(
        migrated_session,
        kind="provider_load",
        payload={"dagster_run_id": "run-live"},
        dagster_run_id="run-live",
    )
    await start_unpaired_import_job(
        migrated_session,
        kind="provider_load",
        payload={"provider": "python-kma-api"},
    )

    runs = await _dagster_runs_snapshot(migrated_session)
    # 같은 session-scope DB를 쓰는 다른 통합 테스트의 잔존 커밋에 견고하도록
    # 포함 여부로 검증한다.
    assert "run-live" in runs["run_ids"]
    assert runs["linked_job_count"] >= 1

    run = await _dagster_run_snapshot(migrated_session, "run-live")
    assert [job["job_id"] for job in run["linked_jobs"]] == [linked.job_id]


async def test_ops_live_snapshots_fall_back_to_payload_in_deploy_window(
    migrated_session: AsyncSession,
) -> None:
    """mixed-version 창 견고화 — 구 dagster 이미지가 0048 migration **이후**에 쓴
    payload-only row(실컬럼 NULL)도 COALESCE 폴백으로 스냅샷에 잡힌다."""
    from kortravelmap.api.routers.ops_live import (
        _dagster_run_snapshot,
        _dagster_runs_snapshot,
    )

    # 구 jobs_repo INSERT(dagster_run_id 컬럼 미기록)를 raw SQL로 재현한다.
    window_job_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.import_jobs (kind, payload)
                VALUES ('provider_load',
                        '{"dagster_run_id": "run-window"}'::jsonb)
                RETURNING job_id::text
                """
            )
        )
    ).scalar_one()
    assert await _column_value(migrated_session, window_job_id) is None

    runs = await _dagster_runs_snapshot(migrated_session)
    assert "run-window" in runs["run_ids"]

    run = await _dagster_run_snapshot(migrated_session, "run-window")
    assert [job["job_id"] for job in run["linked_jobs"]] == [window_job_id]
