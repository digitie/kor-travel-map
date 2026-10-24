"""실제 session/xact 혼용·savepoint·승격·timeout에서 EX 재진입 경계를 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_admin_override_protocol_entry import _wait_protocol_blocker
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_spec = spec_from_file_location(
    "_integration_417",
    Path(__file__).resolve().parents[2] / "alembic/versions/417_protocol_ex_reentry.py",
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)
_GATE = "SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"
_KEY = "1369104691,115"


async def _gate(session, exclusive=True):
    await session.execute(text(_GATE), dict(exclusive=exclusive))


async def _timeout_with_blocker(admin, runtime, holder, *, exclusive=True, other_key=False):
    started = asyncio.get_running_loop().create_future()
    blocker = await holder.scalar(text("SELECT pg_backend_pid()"))

    async def wait():
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='250ms'"))
            if other_key:
                await session.execute(text("SELECT pg_advisory_xact_lock(1369104691,116)"))
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            started.set_result(pid)
            with pytest.raises(DBAPIError) as caught:
                await _gate(session, exclusive)
            assert caught.value.orig.sqlstate == "55P03"
            await session.rollback()

    task = asyncio.create_task(wait())
    try:
        pid = await asyncio.wait_for(started, 3)
        if exclusive:
            await _wait_protocol_blocker(admin, pid, blocker)
        else:
            async with asyncio.timeout(3):
                while True:
                    async with admin.connect() as observer:
                        found = await observer.scalar(
                            text("""SELECT EXISTS(SELECT 1 FROM pg_locks
                            WHERE pid=:pid AND locktype='advisory'
                            AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
                            AND mode='ShareLock' AND NOT granted)
                            AND :blocker=ANY(pg_blocking_pids(:pid))"""),
                            dict(pid=pid, blocker=blocker),
                        )
                    if found:
                        break
                    await asyncio.sleep(0.005)
        await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_original_definition_except_fastpath_and_acl_are_preserved(scalar_engines):
    admin, _ = scalar_engines
    async with admin.connect() as c:
        row = (
            (
                await c.execute(
                    text("""SELECT p.prosrc,p.proconfig,r.rolname,p.prosecdef,
            has_function_privilege('ktm_feature_runtime',p.oid,'EXECUTE') AS runtime,
            EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0) AS public
            FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid='ops.lock_scoped_feature_write_protocol(boolean)'::regprocedure""")
                )
            )
            .mappings()
            .one()
        )
        assert (
            hashlib.sha256(
                row["prosrc"].replace(_migration._FAST_REENTRY, "", 1).encode()
            ).hexdigest()
            == _migration._EXPECTED_BODY_SHA256
        )
        assert row["prosrc"].count(_migration._FAST_REENTRY) == 1
        assert row["proconfig"] == ["search_path=pg_catalog"]
        assert row["rolname"] == _migration._OWNER
        assert row["prosecdef"]
        assert row["runtime"]
        assert not row["public"]
        assert not await c.scalar(
            text("SELECT has_schema_privilege('ktm_feature_state_procedure_owner','ops','CREATE')")
        )


@pytest.mark.parametrize("lock_setting", ["0", "17ms"])
async def test_ex_reentry_preserves_gucs_and_outer_savepoint_lock(scalar_engines, lock_setting):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(
            text("SELECT set_config('lock_timeout',:value,true)"), dict(value=lock_setting)
        )
        before = await holder.scalar(text("SHOW lock_timeout"))
        await _gate(holder)
        nested = await holder.begin_nested()
        await _gate(holder)
        await nested.rollback()
        await _gate(holder)
        assert await holder.scalar(text("SHOW lock_timeout")) == before
        await _timeout_with_blocker(admin, runtime, holder, exclusive=False)
    async with AsyncSession(runtime) as s, s.begin():
        await _gate(s, False)


async def test_session_ex_is_promoted_to_xact_ownership_before_fast_return(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as holder:
        try:
            await holder.execute(text(f"SELECT pg_advisory_lock({_KEY})"))
            await _gate(holder)
            assert await holder.scalar(text(f"SELECT pg_advisory_unlock({_KEY})"))
            # session lock을 풀어도 helper가 남긴 xact EX 때문에 B는 끝까지 기다린다.
            await _timeout_with_blocker(admin, runtime, holder, exclusive=False)
        finally:
            await holder.rollback()
            await holder.execute(text(f"SELECT pg_advisory_unlock({_KEY})"))
            await holder.rollback()
    async with AsyncSession(runtime) as s, s.begin():
        await _gate(s, False)


async def test_savepoint_only_ex_is_released_and_other_pid_or_key_cannot_fast_return(
    scalar_engines,
):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as s, s.begin():
        nested = await s.begin_nested()
        await _gate(s)
        await nested.rollback()
        async with AsyncSession(runtime) as holder, holder.begin():
            await _gate(holder)
            # runtime pool의 서로 다른 두 backend가 실제로 경합한다.
            await s.execute(text("SET LOCAL lock_timeout='100ms'"))
            await s.execute(text("SELECT pg_advisory_xact_lock(1369104691,116)"))
            with pytest.raises(DBAPIError) as caught:
                await _gate(s)
            assert caught.value.orig.sqlstate == "55P03"
            await s.rollback()
    async with AsyncSession(runtime) as s, s.begin():
        await _gate(s)


async def test_shared_upgrade_and_null_still_fail_and_rollback_recovers(scalar_engines):
    _, runtime = scalar_engines
    async with AsyncSession(runtime) as s:
        await _gate(s, False)
        with pytest.raises(DBAPIError) as caught:
            await _gate(s)
        assert caught.value.orig.sqlstate == "23514"
        await s.rollback()
        with pytest.raises(DBAPIError) as caught:
            await _gate(s, None)
        assert caught.value.orig.sqlstate == "23514"
        await s.rollback()
        await _gate(s)
        await s.rollback()


async def test_first_ex_keeps_existing_timeout_and_exact_other_pid_blocker(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as holder, holder.begin():
        await _gate(holder, False)
        await _timeout_with_blocker(admin, runtime, holder, other_key=True)
