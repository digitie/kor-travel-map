"""새 typed reset의 실제 잠금·owner·취소 경계. 소유 격리 PG 외 실행은 없다."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_expired_plan_reset import (
    _BIND,
    _bounded,
    _ready,
    _registered,
)
from tests.integration.test_provider_snapshot_expired_plan_reset import (
    _release_this_case_ready_plans as _release_this_case_ready_plans,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_strict_sh_data_guards import strict_engines as strict_engines

pytestmark = [pytest.mark.integration, pytest.mark.timeout(50)]
_RESET = """SELECT ops.reset_ready_provider_snapshot_plan(
    CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
    CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest)"""


async def _exact_state(admin, args):
    # payload 전량/다른 dataset 없이 정확한 세 작은 원장 행과 timestamp까지 비교한다.
    async with AsyncSession(admin) as session:
        await _bounded(session)
        return (
            await session.execute(
                text("""SELECT to_jsonb(a),to_jsonb(c),to_jsonb(s)
                FROM ops.feature_write_attempts a
                JOIN ops.feature_write_dataset_scopes s USING(provider_dataset_id)
                CROSS JOIN ops.provider_snapshot_controls c
                WHERE a.attempt_id=CAST(:attempt AS uuid)
                  AND c.snapshot_id=CAST(:snapshot AS uuid)"""),
                args,
            )
        ).one()


async def _reset(runtime, args):
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        return await session.scalar(text(_RESET), args)


async def test_ready_reset_unknown_ack_needs_read_preserves_all_durable_rows(scalar_engines):
    admin, runtime = scalar_engines
    _, args = await _registered(scalar_engines)
    assert await _reset(runtime, args) == "reset"
    before = await _exact_state(admin, args)
    assert before[0]["status"] == "cancelled"
    assert before[1]["attempt_id"] is None
    assert before[2]["owner"] is None
    assert await _reset(runtime, args) == "needs_read"
    assert await _exact_state(admin, args) == before
    # 같은 helper의 INSERT ON CONFLICT DO NOTHING 문장과 영속 row 변경0은 구분한다.


@pytest.mark.parametrize("broken", ["generation", "fence", "owner", "manifest"])
async def test_ready_reset_wrong_executor_or_original_binding_is_rollback_only(
    scalar_engines, broken
):
    admin, runtime = scalar_engines
    _, args = await _registered(scalar_engines)
    before = await _exact_state(admin, args)
    changed = dict(args)
    changed[broken] = (
        args["generation"] + 1
        if broken == "generation"
        else "0" * 64
        if broken == "manifest"
        else str(uuid4())
    )
    with pytest.raises(DBAPIError) as caught:
        await _reset(runtime, changed)
    assert caught.value.orig.sqlstate == "40001"
    assert await _exact_state(admin, args) == before


async def test_ready_reset_expired_executor_cannot_use_live_kernel_lease(scalar_engines):
    admin, runtime = scalar_engines
    _, args = await _registered(scalar_engines)
    async with AsyncSession(admin) as session, session.begin():
        await _bounded(session)
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("""UPDATE ops.provider_snapshot_controls
            SET lease_expires_at=clock_timestamp()-interval '1 second'
            WHERE snapshot_id=CAST(:snapshot AS uuid)
              AND executor_generation=:generation AND executor_fence=CAST(:fence AS uuid)"""),
            args,
        )
    before = await _exact_state(admin, args)
    with pytest.raises(DBAPIError) as caught:
        await _reset(runtime, args)
    assert caught.value.orig.sqlstate == "40001"
    assert caught.value.orig.__cause__.message == "snapshot executor fence is stale"
    assert await _exact_state(admin, args) == before


async def test_ready_reset_after_canonical_root_cancel_keeps_kernel_and_artifact(scalar_engines):
    admin, runtime = scalar_engines
    _, args = await _registered(scalar_engines)
    async with AsyncSession(admin) as session, session.begin():
        await _bounded(session)
        root = await session.scalar(
            text("""SELECT root_job_id FROM ops.provider_snapshot_artifacts
            WHERE snapshot_id=CAST(:snapshot AS uuid)"""),
            args,
        )
        scope = await resolve_pipeline_cancellation_scope(
            session, kind="import_job", execution_id=str(root)
        )
        assert scope is not None
        cancelled = await create_pipeline_cancellation_attempt(
            session, scope=scope, requested_by="owned:ready-reset", reason="격리 취소 경쟁"
        )
        assert cancelled.attempt.status == "in_progress"
    before = await _exact_state(admin, args)
    with pytest.raises(DBAPIError) as caught:
        await _reset(runtime, args)
    assert caught.value.orig.sqlstate == "23514"
    assert caught.value.orig.__cause__.constraint_name == "ck_provider_snapshot_member_binding"
    assert await _exact_state(admin, args) == before


async def test_ready_reset_original_plan_cannot_cancel_fresh_replacement_binding(scalar_engines):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    assert await _reset(runtime, args) == "reset"
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        new = await _ready(session, dataset)
        replacement = dict(args, **new)
        await session.execute(text(_BIND), replacement)
    old_before = await _exact_state(admin, args)
    new_before = await _exact_state(admin, replacement)
    assert new_before[2]["owner"] == new["attempt"]
    with pytest.raises(DBAPIError) as caught:
        await _reset(runtime, args)
    assert caught.value.orig.sqlstate == "40001"
    assert caught.value.orig.__cause__.message == "snapshot reset binding changed"
    assert await _exact_state(admin, args) == old_before
    assert await _exact_state(admin, replacement) == new_before


async def test_ready_reset_foreign_scope_epoch_and_owner_are_not_reclaimed(scalar_engines):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    # 정확한 두 lease만 만료시킨 뒤 public claim으로 새 owner/epoch를 만든다.
    # 임의의 가짜 owner/epoch를 SQL로 주입하거나 다른 scope를 건드리지 않는다.
    async with AsyncSession(admin) as session, session.begin():
        await _bounded(session)
        await session.execute(
            text("SELECT ops._lock_scoped_feature_write_scope(:dataset,'[]',false)"),
            {"dataset": dataset},
        )
        assert (
            await session.scalar(
                text("""UPDATE ops.feature_write_attempts
            SET lease_until=clock_timestamp()-interval '1 second'
            WHERE attempt_id=CAST(:attempt AS uuid) RETURNING attempt_id"""),
                args,
            )
            is not None
        )
        assert (
            await session.scalar(
                text("""UPDATE ops.feature_write_dataset_scopes
            SET lease_until=clock_timestamp()-interval '1 second'
            WHERE provider_dataset_id=:dataset AND owner=CAST(:attempt AS uuid)
            RETURNING provider_dataset_id"""),
                dict(args, dataset=dataset),
            )
            == dataset
        )
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        replacement = dict(args, **await _ready(session, dataset))
    old_before = await _exact_state(admin, args)
    new_before = await _exact_state(admin, replacement)
    assert old_before[0]["status"] == "ready"
    assert new_before[2]["owner"] == replacement["attempt"]
    with pytest.raises(DBAPIError) as caught:
        await _reset(runtime, args)
    assert caught.value.orig.sqlstate == "40001"
    assert caught.value.orig.__cause__.message == "snapshot ready plan scope changed"
    assert await _exact_state(admin, args) == old_before
    assert await _exact_state(admin, replacement) == new_before


async def test_ready_reset_live_apply_waits_then_rollback_allows_current_owner_reset(
    strict_engines,
):
    admin, runtime = strict_engines
    _, args = await _registered(strict_engines)
    before = await _exact_state(admin, args)
    holder = AsyncSession(runtime)
    await holder.begin()
    task = None
    primary = None
    try:
        await _bounded(holder)
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await holder.execute(
            text("""SELECT ops.begin_provider_snapshot_apply(
            CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
            CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest,:artifact_sha)"""),
            args,
        )
        ready = asyncio.Event()
        waiter_pid = None

        async def blocked_reset():
            nonlocal waiter_pid
            async with AsyncSession(runtime) as session:
                await session.begin()
                await _bounded(session)
                waiter_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                ready.set()
                try:
                    with pytest.raises(DBAPIError) as caught:
                        await session.scalar(text(_RESET), args)
                    assert caught.value.orig.sqlstate == "55P03"
                finally:
                    await session.rollback()

        task = asyncio.create_task(blocked_reset())
        await asyncio.wait_for(ready.wait(), 2)
        assert waiter_pid != holder_pid
        observed = False
        async with AsyncSession(admin) as observer:
            await _bounded(observer)
            for _ in range(30):
                if holder_pid in await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid}
                ):
                    observed = True
                    break
                await asyncio.sleep(0.01)
        assert observed
        await asyncio.wait_for(task, 2)
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_errors = []
        for cleanup in (holder.rollback, holder.close):
            try:
                await cleanup()
            except BaseException as error:
                cleanup_errors.append(error)
        if task is not None and not task.done():
            task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            if primary is None:
                raise cleanup_errors[0]
            for error in cleanup_errors:
                primary.add_note("owned cleanup failed: " + type(error).__name__)
    assert await _exact_state(admin, args) == before
    async with AsyncSession(admin) as observer:
        await _bounded(observer)
        assert (
            await observer.scalar(
                text("""SELECT lease_until>clock_timestamp() FROM ops.feature_write_attempts
            WHERE attempt_id=CAST(:attempt AS uuid)"""),
                args,
            )
            is True
        )
    assert await _reset(runtime, args) == "reset"
