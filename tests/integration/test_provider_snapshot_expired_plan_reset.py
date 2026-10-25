"""미호출430 typed reset의 canonical 등록·계획·경합 source. 공유 fixture를 바꾸지 않는다."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_strict_sh_data_guards import strict_engines as strict_engines

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_RESET = """SELECT ops.reset_expired_provider_snapshot_plan(
    CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
    CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest)"""
_BIND = """SELECT ops.bind_provider_snapshot_plan(
    CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
    CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest,:input)"""


async def _bounded(session):
    await session.execute(text("SET LOCAL statement_timeout='3000ms'"))
    await session.execute(text("SET LOCAL lock_timeout='900ms'"))


@pytest.fixture(autouse=True)
async def _release_this_case_ready_plans(scalar_engines):
    """이 testcase가 생성한 ready plan만 정본 cancel로 해제한다. lease 대기를 하지 않는다."""
    admin, runtime = scalar_engines
    query = text("""SELECT attempt_id,owner FROM ops.feature_write_attempts
        WHERE idempotency_key LIKE 'reset-plan:%' AND status='ready'""")
    async with AsyncSession(admin) as observer:
        before = {row.attempt_id for row in (await observer.execute(query)).all()}
    yield
    async with AsyncSession(admin) as observer:
        created = [
            row for row in (await observer.execute(query)).all() if row.attempt_id not in before
        ]
    for attempt, owner in created:
        async with AsyncSession(runtime) as session, session.begin():
            await _bounded(session)
            assert await session.scalar(
                text("SELECT ops.cancel_scoped_feature_write(:attempt,:owner)"),
                {"attempt": attempt, "owner": owner},
            )


async def _ready(session, dataset):
    args = dict(attempt=str(uuid4()), owner=str(uuid4()), input="a" * 64)
    await session.execute(
        text("""SELECT ops.claim_scoped_feature_write(
        CAST(:attempt AS uuid),CAST(:owner AS uuid),:dataset,:key,'[]',:input,0,60,false)"""),
        dict(args, dataset=dataset, key="reset-plan:" + args["attempt"]),
    )
    args["manifest"] = await session.scalar(
        text(
            "SELECT ops.seal_scoped_feature_write_manifest"
            "(CAST(:attempt AS uuid),CAST(:owner AS uuid))"
        ),
        args,
    )
    return args


async def _registered(engines):
    # Root 합성 뒤의 실제 등록 source와 codec만 사용한다. 누락 시 inline 설치/가짜 artifact로
    # 대체하지 않는다. current base에는 등록 source가 아직 없으므로 실행 수용은 하지 않는다.
    from tests.integration.test_provider_snapshot_registration import _SQL, _prepare, _wire

    admin, runtime = engines
    dataset, run, _, registration = await _prepare(admin, runtime)
    registration.update(await _wire(run))
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        row = (await session.execute(text(_SQL), registration)).one()
        assert row.created is True
        args = dict(
            snapshot=str(row.snapshot_id),
            generation=row.generation,
            fence=str(row.fence),
            artifact_sha=hashlib.sha256(registration["payload"]).hexdigest(),
        )
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        args.update(await _ready(session, dataset))
        await session.execute(text(_BIND), args)
    return dataset, args


async def _expire(admin, dataset, args):
    # 관리자의 정확 한 attempt lease fault injection. kernel owner/epoch/result는 바꾸지 않는다.
    async with AsyncSession(admin) as session, session.begin():
        await _bounded(session)
        await session.execute(
            text("SELECT ops._lock_scoped_feature_write_scope(:dataset,'[]',false)"),
            {"dataset": dataset},
        )
        await session.execute(
            text("""UPDATE ops.feature_write_attempts
            SET lease_until=clock_timestamp()-interval '1 second'
            WHERE attempt_id=CAST(:attempt AS uuid)"""),
            args,
        )


async def _state(admin, args):
    async with AsyncSession(admin) as session:
        return (
            await session.execute(
                text("""SELECT to_jsonb(attempt),to_jsonb(control)-'updated_at'
                FROM ops.feature_write_attempts attempt
                CROSS JOIN ops.provider_snapshot_controls control
                WHERE attempt.attempt_id=CAST(:attempt AS uuid)
                  AND control.snapshot_id=CAST(:snapshot AS uuid)"""),
                args,
            )
        ).one()


async def test_expired_plan_reset_then_new_immutable_owner_binding(scalar_engines):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    await _expire(admin, dataset, args)
    before_attempt, before_control = await _state(admin, args)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "reset"
    attempt, control = await _state(admin, args)
    assert attempt["status"] == "cancelled"
    for field in (
        "owner",
        "dataset_epoch",
        "region_epochs",
        "input_digest",
        "manifest_digest",
        "result_digest",
    ):
        assert attempt[field] == before_attempt[field]
    for field in ("attempt_id", "attempt_owner", "manifest_digest"):
        assert control[field] is None
    for field in set(before_control) - {"attempt_id", "attempt_owner", "manifest_digest"}:
        assert control[field] == before_control[field]
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        new_plan = await _ready(session, dataset)
        assert new_plan["owner"] != args["owner"]
        assert new_plan["attempt"] != args["attempt"]
        await session.execute(text(_BIND), dict(args, **new_plan))
    _, control = await _state(admin, args)
    assert control["attempt_id"] == new_plan["attempt"]
    assert control["attempt_owner"] == new_plan["owner"]
    assert control["status"] == "prepared"
    assert control["applied_result"] is None


@pytest.mark.parametrize("broken", ["generation", "fence", "owner", "manifest", "live"])
async def test_reset_stale_cas_or_live_plan_has_no_changes(scalar_engines, broken):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    if broken != "live":
        await _expire(admin, dataset, args)
    before = await _state(admin, args)
    changed = dict(args)
    if broken == "generation":
        changed["generation"] += 1
    elif broken in ("fence", "owner"):
        changed[broken] = str(uuid4())
    elif broken == "manifest":
        changed["manifest"] = "0" * 64
    async with AsyncSession(runtime) as session:
        await session.begin()
        await _bounded(session)
        with pytest.raises(DBAPIError) as caught:
            await session.scalar(text(_RESET), changed)
        assert caught.value.orig.sqlstate == ("55P03" if broken == "live" else "40001")
        await session.rollback()
    assert await _state(admin, args) == before


async def test_reset_rollback_and_unknown_response_needs_read(scalar_engines):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    await _expire(admin, dataset, args)
    before = await _state(admin, args)
    async with AsyncSession(runtime) as session:
        await session.begin()
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "reset"
        await session.rollback()
    assert await _state(admin, args) == before
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "reset"
    after = await _state(admin, args)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "needs_read"
    assert await _state(admin, args) == after


async def test_applying_holder_blocks_reset_then_rollback_allows_expired_reset(strict_engines):
    admin, runtime = strict_engines
    dataset, args = await _registered(strict_engines)
    holder = AsyncSession(runtime)
    await holder.begin()
    task = None
    try:
        await _bounded(holder)
        pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await holder.execute(
            text("""SELECT ops.begin_provider_snapshot_apply(
            CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
            CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest,:artifact_sha)"""),
            args,
        )
        waiter_ready = asyncio.Event()
        waiter_pid = None

        async def reset_waiter():
            nonlocal waiter_pid
            async with AsyncSession(runtime) as session:
                await session.begin()
                await _bounded(session)
                waiter_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                waiter_ready.set()
                try:
                    with pytest.raises(DBAPIError) as caught:
                        await session.scalar(text(_RESET), args)
                    assert caught.value.orig.sqlstate == "55P03"
                finally:
                    await session.rollback()

        task = asyncio.create_task(reset_waiter())
        await asyncio.wait_for(waiter_ready.wait(), 2)
        assert waiter_pid != pid
        observed = False
        async with AsyncSession(admin) as observer:
            await _bounded(observer)
            for _ in range(30):
                if pid in await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid}
                ):
                    observed = True
                    break
                await asyncio.sleep(0.01)
        assert observed
        await asyncio.wait_for(task, 2)
    finally:
        await holder.rollback()
        await holder.close()
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
    await _expire(admin, dataset, args)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "reset"
    attempt, control = await _state(admin, args)
    assert attempt["status"] == "cancelled"
    assert control["attempt_id"] is None


async def test_exact_cancelled_binding_reset_preserves_other_attempt_scope_owner(scalar_engines):
    admin, runtime = scalar_engines
    dataset, args = await _registered(scalar_engines)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(
            text(
                "SELECT ops.cancel_scoped_feature_write"
                "(CAST(:attempt AS uuid),CAST(:owner AS uuid))"
            ),
            args,
        )
        replacement = await _ready(session, dataset)
    async with AsyncSession(admin) as observer:
        before = await observer.scalar(
            text(
                "SELECT owner FROM ops.feature_write_dataset_scopes "
                "WHERE provider_dataset_id=:dataset"
            ),
            {"dataset": dataset},
        )
    assert str(before) == replacement["attempt"]
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), args) == "reset"
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text(
                    "SELECT owner FROM ops.feature_write_dataset_scopes "
                    "WHERE provider_dataset_id=:dataset"
                ),
                {"dataset": dataset},
            )
            == before
        )
    _, control_before = await _state(admin, args)
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(text(_RESET), dict(args, **replacement)) == "needs_read"
    _, control_after = await _state(admin, args)
    assert control_after == control_before
    async with AsyncSession(runtime) as session, session.begin():
        await _bounded(session)
        assert await session.scalar(
            text(
                "SELECT ops.cancel_scoped_feature_write"
                "(CAST(:attempt AS uuid),CAST(:owner AS uuid))"
            ),
            replacement,
        )
