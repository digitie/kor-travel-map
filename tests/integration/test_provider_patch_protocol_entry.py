"""426 direct public patch의 P-first 경계. 고유 synthetic PG이며 운영/SDK 증거가 아니다.

435(ADR-117)부터 P는 배타 전용이다. blocker는 P EX holder이고, 434의 "SH caller 안의 patch는
승격 거부" 사례는 SH 자체를 얻을 수 없으므로 지웠다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.application_schema_head import application_schema_head
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_provider_base_update_first import _base, _patch, _seed, _snapshot
from tests.integration.test_tvn36_override_lineage_spine import _constraint_name

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[2]
_PROTOCOL_CLASS = 1369104691
_PROTOCOL_OBJECT = 115
_EXPECTED_BODY = (
    (_ROOT / "alembic/versions/_426_provider_patch_protocol_entry.sql").read_text().split("$$")[1]
)


@pytest.fixture(autouse=True)
async def _no_scalar_policy_world(scalar_engines):
    # 435(ADR-117): 활성 정책 표와 epoch가 사라져 patch는 정책 OFF 경로 하나뿐이다.
    admin, _ = scalar_engines
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text("SELECT to_regclass('feature.provider_field_active_policies')")
            )
            is None
        )


async def _caps(session, lock="1s"):
    await session.execute(text("SET LOCAL statement_timeout='3s'"))
    await session.execute(text("SELECT set_config('lock_timeout',:value,true)"), {"value": lock})


async def _lineage(engine, seed):
    async with AsyncSession(engine) as session:
        return (
            await session.execute(
                text("""SELECT to_jsonb(entity),to_jsonb(head),to_jsonb(record),to_jsonb(link)
                FROM provider_sync.source_entities entity
                JOIN provider_sync.source_entity_heads head USING(source_entity_key)
                JOIN provider_sync.source_records record
                  ON record.source_record_key=head.current_source_record_key
                JOIN provider_sync.source_links link
                  ON link.source_entity_key=entity.source_entity_key
                WHERE entity.source_entity_key=:entity
                  AND link.feature_id=CAST(:feature AS uuid)"""),
                seed,
            )
        ).one()


async def _runtime_clean(admin, runtime, pids):
    assert runtime.pool.checkedout() == 0
    async with runtime.connect() as connection:
        actual = (
            await connection.execute(text("SELECT pg_backend_pid(),session_user,current_user"))
        ).one()
        assert tuple(actual[1:]) == ("ktm_feature_service", "ktm_feature_service")
        pids.add(actual[0])
    assert runtime.pool.checkedout() == 0
    async with AsyncSession(admin) as observer:
        assert (
            await observer.scalar(
                text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=ANY(:pids)"),
                {"pids": sorted(pids)},
            )
            == 0
        )
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM pg_locks
            WHERE locktype='advisory' AND pid IN (
              SELECT pid FROM pg_stat_activity WHERE datname=current_database()
              AND usename='ktm_feature_service')""")
            )
            == 0
        )
        assert (
            await observer.scalar(
                text("""SELECT count(*) FROM pg_stat_activity
            WHERE datname=current_database() AND usename='ktm_feature_service'
            AND state LIKE 'idle in transaction%'""")
            )
            == 0
        )


async def _wait_for_protocol(admin, task, waiter, holder):
    async with asyncio.timeout(0.8), AsyncSession(admin) as observer:
        await _caps(observer, "200ms")
        while True:
            if task.done():
                await task  # 예상 밖 조기 실패를 timeout으로 숨기지 않는다.
                raise AssertionError("patch completed before protocol wait observation")
            row = (
                await observer.execute(
                    text("""SELECT count(*) FILTER (WHERE NOT granted),
                    count(*) FILTER (WHERE granted)
                    FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                    AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                    AND classid=:class AND objid=:object AND objsubid=2
                    AND mode='ExclusiveLock'"""),
                    {"pid": waiter, "class": _PROTOCOL_CLASS, "object": _PROTOCOL_OBJECT},
                )
            ).one()
            if tuple(row) == (1, 0):
                assert holder in await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
                )
                return
            await asyncio.sleep(0.005)


async def _probe_unlocked_rows(admin, seed):
    # pg_locks에서 보유 tuple이 안 보이는 것만으로 미선점을 단정하지 않는다.
    # 다른 실제 backend의 NOWAIT 획득과 rollback으로 source/head/link/Feature를 증명한다.
    async with AsyncSession(admin) as probe, probe.begin():
        await _caps(probe, "100ms")
        for table, predicate in [
            ("provider_sync.source_entities", "source_entity_key=:entity"),
            ("provider_sync.source_records", "source_record_key=:record"),
            ("provider_sync.source_entity_heads", "source_entity_key=:entity"),
            (
                "provider_sync.source_links",
                "source_entity_key=:entity AND feature_id=CAST(:feature AS uuid)",
            ),
            ("feature.features", "feature_id=CAST(:feature AS uuid)"),
        ]:
            # 관계/조건은 위 고정 상수만 사용한다.
            assert (
                await probe.execute(
                    text(f"SELECT 1 FROM {table} WHERE {predicate} FOR UPDATE NOWAIT"), seed
                )
            ).scalar_one() == 1
        await probe.rollback()


async def test_direct_patch_waits_before_source_and_feature_then_succeeds(scalar_engines, request):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    source_before = await _lineage(admin, seed)
    ready = asyncio.get_running_loop().create_future()
    pids = set()

    async def writer():
        async with AsyncSession(runtime) as session, session.begin():
            await _caps(session, "2s")
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            ready.set_result(pid)
            out = await _patch(session, seed, {"core.name": "direct426"}, expected=1)
            assert await session.scalar(text("SHOW lock_timeout")) == "2s"
            return dict(out)

    async with AsyncSession(runtime) as holder:
        await holder.begin()
        await _caps(holder)
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        pids.add(holder_pid)
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        task = asyncio.create_task(writer())
        try:
            try:
                waiter = await asyncio.wait_for(asyncio.shield(ready), 1)
            except TimeoutError:
                if task.done():
                    await task
                raise
            pids.add(waiter)
            assert waiter != holder_pid
            await _wait_for_protocol(admin, task, waiter, holder_pid)
            await _probe_unlocked_rows(admin, seed)
            assert not task.done()
            request.node.user_properties.extend(
                [("holder_pid", holder_pid), ("waiter_pid", waiter), ("nowait_rows", 5)]
            )
            await holder.rollback()
            out = await asyncio.wait_for(task, 3)
            assert out["o_row_revision"] == 2
            assert out["o_applied_field_count"] == 1
        finally:
            await holder.rollback()
            if not task.done():
                task.cancel()
            # 정리 때의 부수 예외가 본래 probe/writer 실패를 덮지 않게 한다.
            await asyncio.gather(task, return_exceptions=True)
    assert await _lineage(admin, seed) == source_before
    row = (await _base(admin, seed))["core.name"]
    assert row["source_record_key"] == seed["record"]
    assert row["source_entity_key"] == seed["entity"]
    assert row["source_raw_payload_hash"] == seed["hash"]
    assert row["base_revision"] == 2
    await _runtime_clean(admin, runtime, pids)


@pytest.mark.parametrize(("lock", "restored"), [("250ms", "250ms"), ("0", "0")])
async def test_timeout_restores_caller_guc_and_fresh_retry(scalar_engines, lock, restored):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    before = await _snapshot(admin, seed)
    lineage = await _lineage(admin, seed)
    pids = set()
    async with AsyncSession(runtime) as holder, AsyncSession(runtime) as waiter:
        await holder.begin()
        await waiter.begin()
        try:
            await _caps(holder)
            await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            await _caps(waiter, lock)
            pids.update(
                [
                    await holder.scalar(text("SELECT pg_backend_pid()")),
                    await waiter.scalar(text("SELECT pg_backend_pid()")),
                ]
            )
            async with asyncio.timeout(2):
                with pytest.raises(DBAPIError) as caught:
                    async with waiter.begin_nested():
                        await _patch(waiter, seed, {"core.name": "timeout426"}, expected=1)
            assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
            assert await waiter.scalar(text("SHOW lock_timeout")) == restored
            assert await waiter.scalar(text("SHOW statement_timeout")) == "3s"
        finally:
            await waiter.rollback()
            await holder.rollback()
    assert await _snapshot(admin, seed) == before
    assert await _lineage(admin, seed) == lineage
    await _runtime_clean(admin, runtime, pids)
    async with AsyncSession(runtime) as fresh, fresh.begin():
        await _caps(fresh)
        out = await _patch(fresh, seed, {"core.name": "retry426"}, expected=1)
        assert out["o_row_revision"] == 2
    assert await _lineage(admin, seed) == lineage
    await _runtime_clean(admin, runtime, pids)


async def test_existing_exclusive_is_reentrant_and_preserves_zero_timeout(scalar_engines):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    pids = set()
    async with AsyncSession(runtime) as session, session.begin():
        await _caps(session, "0")
        pids.add(await session.scalar(text("SELECT pg_backend_pid()")))
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        out = await _patch(session, seed, {"core.name": "reentrant426"}, expected=1)
        assert out["o_row_revision"] == 2
        assert await session.scalar(text("SHOW lock_timeout")) == "0"
    await _runtime_clean(admin, runtime, pids)


@pytest.mark.parametrize(
    ("mode", "code", "constraint"),
    [
        ("source", "23514", "ck_feature_provider_source_provenance"),
        ("revision", "40001", None),
        ("field", "23514", "ck_feature_provider_field_path"),
        ("value", "23514", None),
    ],
)
async def test_existing_validation_and_rollback_survive_prefix(
    scalar_engines, mode, code, constraint
):
    admin, runtime = scalar_engines
    seed = await _seed(admin)
    before = await _snapshot(admin, seed)
    lineage = await _lineage(admin, seed)
    pids = set()
    async with AsyncSession(runtime) as session, session.begin():
        await _caps(session)
        pids.add(await session.scalar(text("SELECT pg_backend_pid()")))
        target = {**seed, "record": "sr_" + "f" * 20} if mode == "source" else seed
        values = (
            {"core.not_registered": "x"}
            if mode in {"source", "field"}
            else {"core.name": 12 if mode == "value" else "x"}
        )
        with pytest.raises(DBAPIError) as caught:
            async with session.begin_nested():
                await _patch(session, target, values, expected=99 if mode == "revision" else 1)
        assert getattr(caught.value.orig, "sqlstate", None) == code
        if constraint is not None:
            assert _constraint_name(caught.value) == constraint
    assert await _snapshot(admin, seed) == before
    assert await _lineage(admin, seed) == lineage
    await _runtime_clean(admin, runtime, pids)


async def test_actual_owner_acl_body_and_service_login(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(admin) as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            == application_schema_head()
        )
        row = (
            await session.execute(
                text("""SELECT p.prosrc,p.prokind::text,p.prosecdef,
            p.provolatile::text,p.proconfig,r.rolname,
            ARRAY(SELECT role.rolname FROM aclexplode(p.proacl) acl
                  LEFT JOIN pg_roles role ON role.oid=acl.grantee ORDER BY role.rolname)
            FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid=to_regprocedure(
              'feature.apply_provider_feature_field_patch(uuid,bigint,text,text,bigint,jsonb,jsonb)')""")
            )
        ).one()
        assert row[0] == _EXPECTED_BODY
        assert tuple(row[1:6]) == (
            "p",
            True,
            "v",
            ["search_path=pg_catalog"],
            "ktm_feature_state_procedure_owner",
        )
        assert row[6] == ["ktm_feature_runtime", "ktm_feature_state_procedure_owner"]
        assert (
            await session.scalar(
                text(
                    "SELECT has_schema_privilege("
                    "'ktm_feature_state_procedure_owner','feature','CREATE')"
                )
            )
            is True  # 정본 fresh bootstrap의 owner CREATE를 회수하지 않는다.
        )
    async with AsyncSession(runtime) as session:
        assert (
            await session.scalar(
                text("SELECT has_schema_privilege(current_user,'feature','CREATE')")
            )
            is False
        )
        assert tuple((await session.execute(text("SELECT session_user,current_user"))).one()) == (
            "ktm_feature_service",
            "ktm_feature_service",
        )
