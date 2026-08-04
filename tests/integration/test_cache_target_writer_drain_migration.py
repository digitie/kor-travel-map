"""T-VN-41D writer-drain durable schema 회귀."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra.models import (
    CacheTargetWriterDrainInstigationRow,
    CacheTargetWriterDrainLeaseRow,
    CacheTargetWriterDrainRunRow,
)
from kortravelmap.infra.writer_drain_repo import (
    create_writer_drain_lease,
    get_writer_drain_lease,
    get_writer_drain_runs,
    mark_writer_drain_run_outcome_uncertain,
    refresh_writer_drain_receipt,
    reserve_writer_drain_run_cancel,
    reset_writer_drain_begin_receipt,
    set_writer_drain_receipt,
    upsert_writer_drain_run,
)

pytestmark = pytest.mark.integration


async def test_writer_drain_schema_is_mapped_and_allows_only_one_active_lease(
    migrated_session,
) -> None:
    """정규화한 three relations와 global partial unique index가 head에 존재한다."""

    assert CacheTargetWriterDrainLeaseRow.__table__.schema == "ops"
    assert CacheTargetWriterDrainInstigationRow.__table__.schema == "ops"
    assert CacheTargetWriterDrainRunRow.__table__.schema == "ops"
    lease_checks = {
        str(constraint.name)
        for constraint in CacheTargetWriterDrainLeaseRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_cache_target_writer_drain_leases_state" in lease_checks
    assert "ck_cache_target_writer_drain_leases_snapshot_sha256" in lease_checks

    owner_one = uuid4()
    owner_two = uuid4()
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.cache_target_writer_drain_leases (
              owner_kind, owner_id, state, snapshot_sha256
            ) VALUES (
              'diagnostic', CAST(:owner_id AS uuid), 'draining', :snapshot_sha256
            )
            """
        ),
        {"owner_id": str(owner_one), "snapshot_sha256": "a" * 64},
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.cache_target_writer_drain_leases (
                      owner_kind, owner_id, state, snapshot_sha256
                    ) VALUES (
                      'cutover', CAST(:owner_id AS uuid), 'drained', :snapshot_sha256
                    )
                    """
                ),
                {"owner_id": str(owner_two), "snapshot_sha256": "b" * 64},
            )

    indexes = (
        (
            await migrated_session.execute(
                text(
                    """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'cache_target_writer_drain_leases'
                  AND indexname = 'uq_cache_target_writer_drain_leases_active'
                """
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(indexes) == 1
    assert "UNIQUE" in indexes[0]
    assert "(1)" in indexes[0]
    assert "draining" in indexes[0]
    assert "restoring" in indexes[0]


async def test_writer_drain_run_cancel_reservation_is_one_shot(migrated_session) -> None:
    """crash resume가 terminal cancel mutation을 다시 dispatch하지 않게 CAS로 고정한다."""

    lease = await create_writer_drain_lease(
        migrated_session,
        owner_kind="diagnostic",
        owner_id=uuid4(),
        snapshot_sha256="a" * 64,
        instigations=(),
    )
    await upsert_writer_drain_run(
        migrated_session,
        lease_id=lease.lease_id,
        dagster_run_id="run-1",
        initial_status="STARTED",
    )
    assert await reserve_writer_drain_run_cancel(
        migrated_session,
        lease_id=lease.lease_id,
        dagster_run_id="run-1",
    )
    assert not await reserve_writer_drain_run_cancel(
        migrated_session,
        lease_id=lease.lease_id,
        dagster_run_id="run-1",
    )
    await mark_writer_drain_run_outcome_uncertain(
        migrated_session,
        lease_id=lease.lease_id,
        dagster_run_id="run-1",
    )
    (run,) = await get_writer_drain_runs(migrated_session, lease_id=lease.lease_id)
    assert run.cancel_result == "outcome_uncertain"
    assert run.cancel_reserved_at is not None
    assert run.cancel_dispatched_at is None


async def test_writer_drain_begin_receipt_can_restart_after_lost_attest_response(
    migrated_session,
) -> None:
    """Manager의 phase fsync 전 응답 유실은 동일 owner chain으로 회복한다."""

    lease = await create_writer_drain_lease(
        migrated_session,
        owner_kind="cutover",
        owner_id=uuid4(),
        snapshot_sha256="a" * 64,
        instigations=(),
    )
    assert await set_writer_drain_receipt(
        migrated_session,
        lease_id=lease.lease_id,
        state="drained",
        receipt_sha256="b" * 64,
        operation="begin",
        prior_receipt_sha256=None,
    )
    assert await reset_writer_drain_begin_receipt(
        migrated_session,
        lease_id=lease.lease_id,
        expected_receipt_sha256="b" * 64,
        receipt_sha256="c" * 64,
    )
    assert await refresh_writer_drain_receipt(
        migrated_session,
        lease_id=lease.lease_id,
        receipt_sha256="d" * 64,
        operation="attest",
        prior_receipt_sha256="c" * 64,
    )
    assert await reset_writer_drain_begin_receipt(
        migrated_session,
        lease_id=lease.lease_id,
        expected_receipt_sha256="d" * 64,
        receipt_sha256="e" * 64,
    )
    replayed = await get_writer_drain_lease(
        migrated_session,
        lease_id=lease.lease_id,
    )
    assert replayed is not None
    assert replayed.state == "drained"
    assert replayed.receipt_operation == "begin"
    assert replayed.receipt_prior_sha256 is None
    assert replayed.receipt_sha256 == "e" * 64
