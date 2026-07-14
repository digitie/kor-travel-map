"""``ops.import_jobs.dagster_run_id`` 실컬럼 기록 경로 통합 테스트 (ADR-064).

jobs_repo의 INSERT/UPDATE 경로가 payload의 ``dagster_run_id``(레거시 ``run_id``
fallback)를 실컬럼으로 승격하는지, `/ops/live` dagster 스냅샷 SQL이 실컬럼으로
동작하는지 검증한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.jobs_repo import (
    enqueue_import_job,
    start_import_job,
    update_import_job_payload,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


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


async def test_enqueue_promotes_payload_dagster_run_id(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_import_job(
        migrated_session,
        kind="provider_load",
        payload={"provider": "python-kma-api", "dagster_run_id": "run-enqueue"},
    )

    assert job.dagster_run_id == "run-enqueue"
    assert await _column_value(migrated_session, job.job_id) == "run-enqueue"


async def test_start_promotes_legacy_run_id_key(
    migrated_session: AsyncSession,
) -> None:
    job = await start_import_job(
        migrated_session,
        kind="provider_load",
        payload={"run_id": "run-legacy"},
    )

    assert job.dagster_run_id == "run-legacy"
    assert await _column_value(migrated_session, job.job_id) == "run-legacy"


async def test_enqueue_without_run_id_leaves_column_null(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_import_job(
        migrated_session,
        kind="provider_load",
        payload={"provider": "python-kma-api"},
    )

    assert job.dagster_run_id is None
    assert await _column_value(migrated_session, job.job_id) is None


async def test_update_payload_sets_and_keeps_run_id(
    migrated_session: AsyncSession,
) -> None:
    job = await start_import_job(
        migrated_session,
        kind="offline_upload_load",
        payload={"upload_id": "u-1"},
    )
    assert job.dagster_run_id is None

    # offline_upload 경로처럼 실행 도중 payload에 run id가 추가되는 케이스.
    updated = await update_import_job_payload(
        migrated_session,
        job.job_id,
        payload={"upload_id": "u-1", "dagster_run_id": "run-late"},
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

    linked = await start_import_job(
        migrated_session,
        kind="provider_load",
        payload={"dagster_run_id": "run-live"},
    )
    await start_import_job(
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
