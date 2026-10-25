"""실제 등록을 aged fixture로 옮겨 terminal GC의 보존·ledger·rollback만 검증한다."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_registration import _SQL, _prepare, _quotas, _wire
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_GC = "SELECT ops.collect_expired_provider_snapshots(:limit)"


async def _aged_snapshot(engines, *, protect=None):
    admin, runtime = engines
    dataset, run, _, args = await _prepare(admin, runtime)
    args.update(await _wire(run))
    async with AsyncSession(runtime) as session, session.begin():
        row = (await session.execute(text(_SQL), args)).one()
        assert row.created is True
        snapshot = row.snapshot_id
    now = datetime.now(UTC)
    old = now - timedelta(days=8)
    async with admin.begin() as connection:
        await connection.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        # 시계를 위조하지 않는다. 소유 fixture만 원 bytes/identity 그대로 재INSERT한다.
        # UPDATE 금지 제품 계약을 유지하며 GC의 경과 시간만 구성한다.
        records = []
        for table in ("artifacts", "controls", "quota_reservations"):
            record = dict(
                (
                    await connection.execute(
                        text(f"SELECT * FROM ops.provider_snapshot_{table} WHERE snapshot_id=:id"),
                        {"id": snapshot},
                    )
                )
                .mappings()
                .one()
            )
            records.append((table, record))
        for table in ("controls", "quota_reservations", "artifacts"):
            await connection.execute(
                text(f"DELETE FROM ops.provider_snapshot_{table} WHERE snapshot_id=:id"),
                {"id": snapshot},
            )
        for table, record in records:
            for generated in ("artifact_sha256", "context_sha256", "result_sha256"):
                record.pop(generated, None)
            if table == "artifacts":
                record["created_at"] = now if protect == "fresh-artifact" else old
            elif table == "controls":
                record["updated_at"] = now if protect == "fresh-control" else old
                record["lease_expires_at"] = (
                    now + timedelta(minutes=1) if protect == "live-lease" else old
                )
            columns = ",".join(record)
            values = ",".join(":" + column for column in record)
            await connection.execute(
                text(f"INSERT INTO ops.provider_snapshot_{table}({columns}) VALUES({values})"),
                record,
            )
        for is_root, job in ((True, args["root"]), (False, args["source"])):
            running = protect == ("running-root" if is_root else "running-child")
            fresh = protect == ("fresh-root-finish" if is_root else "fresh-child-finish")
            await connection.execute(
                text("""UPDATE ops.import_jobs SET status=:status,current_stage=:status,
                created_at=:old,started_at=:old,finished_at=:finished,
                dagster_run_status=CASE WHEN kind='provider_feature_load_run'
                    THEN :engine ELSE NULL END,
                quarantined_at=:quarantined,quarantine_reason=:reason WHERE job_id=:job"""),
                {
                    "job": job,
                    "status": "running" if running else "failed",
                    "old": old,
                    "finished": None if running else now if fresh else old,
                    "engine": "STARTED" if protect == "live-engine" else "FAILURE",
                    "quarantined": now if is_root and protect == "quarantined" else None,
                    "reason": "unlinked_feature_update_component"
                    if is_root and protect == "quarantined"
                    else None,
                },
            )
    return dataset, snapshot, args


async def _exists(admin, snapshot):
    async with admin.connect() as connection:
        return await connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM ops.provider_snapshot_artifacts WHERE snapshot_id=:id)"
            ),
            {"id": snapshot},
        )


async def _quota_state(admin, dataset):
    async with AsyncSession(admin) as session:
        return await _quotas(session, dataset)


async def test_terminal_gc_returns_exact_quota_and_rollback_preserves_original_rows(scalar_engines):
    admin, runtime = scalar_engines
    dataset, snapshot, args = await _aged_snapshot(scalar_engines)
    before = await _quota_state(admin, dataset)
    async with admin.connect() as observer:
        reserved = await observer.scalar(
            text(
                "SELECT reserved_bytes FROM ops.provider_snapshot_quota_reservations "
                "WHERE snapshot_id=:id"
            ),
            {"id": snapshot},
        )
        jobs = (
            await observer.execute(
                text(
                    "SELECT job_id,to_jsonb(j) FROM ops.import_jobs j "
                    "WHERE job_id IN (:root,:source) ORDER BY job_id"
                ),
                args,
            )
        ).all()
    async with AsyncSession(runtime) as session:
        assert await session.scalar(text(_GC), {"limit": 1}) == 1
        await session.rollback()
    assert await _exists(admin, snapshot) is True
    assert await _quota_state(admin, dataset) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 1}) == 1
    assert await _exists(admin, snapshot) is False
    assert await _quota_state(admin, dataset) == [
        (key, used_bytes - reserved, used_rows - 1) for key, used_bytes, used_rows in before
    ]
    async with admin.connect() as observer:
        assert (
            await observer.execute(
                text(
                    "SELECT job_id,to_jsonb(j) FROM ops.import_jobs j "
                    "WHERE job_id IN (:root,:source) ORDER BY job_id"
                ),
                args,
            )
        ).all() == jobs
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 16}) == 0


@pytest.mark.parametrize(
    "protect",
    [
        "fresh-artifact",
        "fresh-control",
        "live-lease",
        "running-root",
        "running-child",
        "live-engine",
        "quarantined",
        "fresh-root-finish",
        "fresh-child-finish",
    ],
)
async def test_terminal_gc_preserves_active_or_unsettled_input(scalar_engines, protect):
    admin, runtime = scalar_engines
    dataset, snapshot, _ = await _aged_snapshot(scalar_engines, protect=protect)
    before = await _quota_state(admin, dataset)
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 16}) == 0
    assert await _exists(admin, snapshot) is True
    assert await _quota_state(admin, dataset) == before


@pytest.mark.parametrize("limit", [0, 17, None])
async def test_terminal_gc_rejects_unbounded_requests(scalar_engines, limit):
    _, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        with pytest.raises(DBAPIError) as caught:
            await session.execute(text(_GC), {"limit": limit})
        assert caught.value.orig.sqlstate == "22023"
        await session.rollback()


async def test_terminal_gc_rejects_serializable_before_effects(scalar_engines):
    _, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        with pytest.raises(DBAPIError) as caught:
            await session.execute(text(_GC), {"limit": 1})
        assert caught.value.orig.sqlstate == "25001"
        await session.rollback()


async def test_terminal_gc_obeys_batch_limit_with_multiple_eligible_inputs(scalar_engines):
    admin, runtime = scalar_engines
    first = await _aged_snapshot(scalar_engines)
    second = await _aged_snapshot(scalar_engines)
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 1}) == 1
    remaining = [await _exists(admin, item[1]) for item in (first, second)]
    assert sum(remaining) == 1
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 16}) == 1
    assert not any([await _exists(admin, item[1]) for item in (first, second)])


async def test_terminal_gc_inconsistent_quota_never_deletes_input(scalar_engines):
    admin, runtime = scalar_engines
    dataset, snapshot, _ = await _aged_snapshot(scalar_engines)
    before = await _quota_state(admin, dataset)
    # 관리 fixture에서 ledger만 고장낸다. 삭제 함수/권한/원 입력은 바꾸지 않는다.
    async with admin.begin() as connection:
        await connection.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await connection.execute(
            text("UPDATE ops.provider_snapshot_quota_limits SET used_rows=0 WHERE quota_key=0")
        )
    try:
        async with AsyncSession(runtime) as session:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(text(_GC), {"limit": 16})
            assert caught.value.orig.sqlstate == "23514"
            await session.rollback()
        assert await _exists(admin, snapshot) is True
    finally:
        async with admin.begin() as connection:
            await connection.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            await connection.execute(
                text(
                    "UPDATE ops.provider_snapshot_quota_limits SET used_rows=:count "
                    "WHERE quota_key=0"
                ),
                {"count": next(row[2] for row in before if row[0] == 0)},
            )
    assert await _quota_state(admin, dataset) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(text(_GC), {"limit": 16}) == 1
