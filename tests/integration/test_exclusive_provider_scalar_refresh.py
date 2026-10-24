"""같은 후보 의미의 EX 진입과 SH 경합·rollback을 owned PG로 검증한다."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import scoped_provider_refresh as native
from tests.integration.test_scoped_native_scalar_refresh import _bundle, _plan, _read, _seed
from tests.integration.test_scoped_native_scalar_refresh import (
    scalar_container as scalar_container,
)
from tests.integration.test_scoped_native_scalar_refresh import scalar_engines as scalar_engines

pytestmark = pytest.mark.integration


async def _semantics(admin, feature, entity):
    async with AsyncSession(admin) as session:
        projection = tuple(
            (
                await session.execute(
                    text("""
            SELECT f.name,p.phones,h.observed_at,r.raw_data,r.raw_payload_hash
            FROM feature.features f JOIN feature.feature_places p USING(feature_id)
            CROSS JOIN provider_sync.source_entity_heads h
            JOIN provider_sync.source_records r
              ON r.source_record_key=h.current_source_record_key
            WHERE f.feature_id=:feature AND h.source_entity_key=:entity
        """),
                    {"feature": feature, "entity": entity},
                )
            ).one()
        )
        candidates = (
            await session.execute(
                text("""
            SELECT field_path,value_json,availability,reason,value_source_hash,
                   validated_source_hash,value_observed_at,validated_at,normalizer_revision
            FROM feature.provider_field_shadow_candidates
            WHERE feature_id=:feature ORDER BY field_path
        """),
                {"feature": feature},
            )
        ).all()
        return projection, [tuple(row) for row in candidates]


async def test_ex_and_sh_preserve_same_candidate_head_and_projection(scalar_engines):
    admin, runtime = scalar_engines
    states = []
    for exclusive in (False, True):
        feature, dataset, entity, identity = await _seed(admin)
        bundle = _bundle(identity, "same-result")
        plan = await _plan(runtime, feature, dataset, bundle, exclusive_protocol=exclusive)
        apply = (
            native.refresh_exclusive_provider_scalars
            if exclusive
            else native.refresh_scoped_provider_scalars
        )
        async with AsyncSession(runtime) as session, session.begin():
            receipt = await apply(session, bundle, **plan)
            assert receipt["status"] == "completed"
            assert receipt["exclusive_protocol"] is exclusive
            modes = (
                (
                    await session.execute(
                        text("""
                SELECT mode FROM pg_catalog.pg_locks WHERE pid=pg_backend_pid()
                AND locktype='advisory' AND classid=1369104691 AND objid=115
                AND objsubid=2 AND granted
            """)
                    )
                )
                .scalars()
                .all()
            )
            assert "ExclusiveLock" in modes if exclusive else modes == ["ShareLock"]
            global_held = await session.scalar(
                text("""
                SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks
                WHERE pid=pg_backend_pid() AND locktype='advisory' AND objsubid=1
                AND mode='ExclusiveLock' AND granted
                AND (classid::bigint << 32 | objid::bigint)
                    = hashtextextended('feature-curation-write',0))
            """)
            )
            assert global_held is exclusive
        states.append(await _semantics(admin, feature, entity))
    assert states[0] == states[1]


async def test_ex_blocks_independent_sh_until_transaction_ends(scalar_engines):
    admin, runtime = scalar_engines
    first, second = await _seed(admin), await _seed(admin)
    a, b = _bundle(first[3], "exclusive"), _bundle(second[3], "shared")
    pa = await _plan(runtime, first[0], first[1], a, exclusive_protocol=True)
    pb = await _plan(runtime, second[0], second[1], b)
    started = asyncio.Event()
    pid = None

    async def apply_shared():
        nonlocal pid
        async with AsyncSession(runtime) as session, session.begin():
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            return await native.refresh_scoped_provider_scalars(session, b, **pb)

    task = None
    try:
        async with AsyncSession(runtime) as session, session.begin():
            owner_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await native.refresh_exclusive_provider_scalars(session, a, **pa)
            task = asyncio.create_task(apply_shared())
            await asyncio.wait_for(started.wait(), 1)
            for _ in range(50):
                async with AsyncSession(admin) as observer:
                    blocked = await observer.scalar(
                        text("""
                        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks
                        WHERE pid=:pid AND locktype='advisory' AND NOT granted
                        AND classid=1369104691 AND objid=115 AND objsubid=2
                        AND mode='ShareLock' AND :owner=ANY(pg_blocking_pids(:pid)))
                    """),
                        {"pid": pid, "owner": owner_pid},
                    )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked
            assert not task.done()
            assert await _read(admin, second[0], second[2]) == (
                "before",
                _bundle(second[3], "before", hours=-24).source_record.source_record_key,
            )
        assert (await asyncio.wait_for(task, 2))["status"] == "completed"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert (await _read(admin, second[0], second[2]))[0] == "shared"


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_ex_rollback_recovers_same_artifact_and_replays_without_dml(
    scalar_engines, monkeypatch, failure
):
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    before = await _semantics(admin, feature, entity)
    bundle = _bundle(identity, "recovered")
    plan = await _plan(runtime, feature, dataset, bundle, exclusive_protocol=True)
    original = native._upsert_source_record_state

    async def fail_after_dml(session, record):
        await original(session, record)
        raise failure("after actual source DML")

    with monkeypatch.context() as patch:
        patch.setattr(native, "_upsert_source_record_state", fail_after_dml)
        with pytest.raises(failure):
            async with AsyncSession(runtime) as session, session.begin():
                await native.refresh_exclusive_provider_scalars(session, bundle, **plan)
    assert await _semantics(admin, feature, entity) == before
    async with AsyncSession(runtime) as session, session.begin():
        receipt = await native.refresh_exclusive_provider_scalars(session, bundle, **plan)
    after = await _semantics(admin, feature, entity)

    async def forbidden_dml(*args, **kwargs):
        pytest.fail("completed EX replay repeated source DML")

    monkeypatch.setattr(native, "_upsert_source_record_state", forbidden_dml)
    async with AsyncSession(runtime) as session, session.begin():
        replay = await native.refresh_exclusive_provider_scalars(session, bundle, **plan)
    assert receipt["result_digest"] == replay["result_digest"]
    assert await _semantics(admin, feature, entity) == after


async def test_modes_cannot_be_substituted_and_original_plan_recovers(scalar_engines):
    admin, runtime = scalar_engines
    for exclusive in (False, True):
        feature, dataset, entity, identity = await _seed(admin)
        bundle = _bundle(identity, "recovered")
        before = await _semantics(admin, feature, entity)
        plan = await _plan(runtime, feature, dataset, bundle, exclusive_protocol=exclusive)
        wrong = (
            native.refresh_scoped_provider_scalars
            if exclusive
            else native.refresh_exclusive_provider_scalars
        )
        with pytest.raises(DBAPIError if exclusive else ValueError) as error:
            async with AsyncSession(runtime) as session, session.begin():
                await wrong(session, bundle, **plan)
        if exclusive:
            assert getattr(error.value.orig, "sqlstate", None) == "23514"
        else:
            assert "does not match" in str(error.value)
        assert await _semantics(admin, feature, entity) == before
        correct = (
            native.refresh_exclusive_provider_scalars
            if exclusive
            else native.refresh_scoped_provider_scalars
        )
        async with AsyncSession(runtime) as session, session.begin():
            assert (await correct(session, bundle, **plan))["status"] == "completed"


async def test_ex_lock_timeout_keeps_old_head_and_retry_succeeds(scalar_engines):
    admin, runtime = scalar_engines
    feature, dataset, entity, identity = await _seed(admin)
    before = await _semantics(admin, feature, entity)
    bundle = _bundle(identity, "after-timeout")
    plan = await _plan(runtime, feature, dataset, bundle, exclusive_protocol=True)
    async with AsyncSession(runtime) as blocker, blocker.begin():
        await blocker.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        with pytest.raises(DBAPIError) as error:
            async with AsyncSession(runtime) as session, session.begin():
                await native.refresh_exclusive_provider_scalars(session, bundle, **plan)
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"
    assert await _semantics(admin, feature, entity) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert (await native.refresh_exclusive_provider_scalars(session, bundle, **plan))[
            "status"
        ] == "completed"
    assert (await _read(admin, feature, entity))[0] == "after-timeout"
