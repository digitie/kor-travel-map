"""실제 session/xact 혼용·savepoint·timeout에서 EX 재진입 경계와 공유 모드 퇴역을 검증한다.

435(ADR-117)부터 P는 배타 전용이다. ``ops.lock_scoped_feature_write_protocol(false)``는 23514로
거부되고, 434까지 SH holder로 만들던 대기는 EX holder로 만든다.
"""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import scalar_engines as scalar_engines
from tests.integration.test_admin_override_protocol_entry import _wait_protocol_blocker
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]


def _load(name: str, filename: str):
    spec = spec_from_file_location(name, Path(__file__).resolve().parents[2] / filename)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_migration = _load("_integration_417", "alembic/versions/417_protocol_ex_reentry.py")
_retirement = _load("_integration_435", "alembic/versions/435_retire_sh_snapshot_path.py")
_GATE = "SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"
_KEY = "1369104691,115"
_RETIRED = "shared protocol mode was retired (ADR-117)"


async def _gate(session, exclusive=True):
    await session.execute(text(_GATE), dict(exclusive=exclusive))


async def _timeout_with_blocker(admin, runtime, holder, *, other_key=False):
    """다른 backend의 P EX 요청이 ``holder`` 뒤에서 실제로 기다리다 55P03으로 끝나는가."""
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
                await _gate(session)
            assert caught.value.orig.sqlstate == "55P03"
            await session.rollback()

    task = asyncio.create_task(wait())
    try:
        pid = await asyncio.wait_for(started, 3)
        await _wait_protocol_blocker(admin, pid, blocker)
        await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_definition_is_the_exclusive_only_body_and_acl_is_preserved(scalar_engines):
    """435가 417 본문을 배타 전용 사이드카로 통째로 바꿨다. 소유자·config·ACL은 그대로다."""
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
        planned = _retirement._ROUTINES["ops.lock_scoped_feature_write_protocol"].replacement
        assert row["prosrc"] == planned
        assert row["prosrc"].count(_RETIRED) == 1
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
        await _timeout_with_blocker(admin, runtime, holder)
    async with AsyncSession(runtime) as s, s.begin():
        await _gate(s)


async def test_session_ex_is_promoted_to_xact_ownership_before_fast_return(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as holder:
        try:
            await holder.execute(text(f"SELECT pg_advisory_lock({_KEY})"))
            await _gate(holder)
            assert await holder.scalar(text(f"SELECT pg_advisory_unlock({_KEY})"))
            # session lock을 풀어도 helper가 남긴 xact EX 때문에 B는 끝까지 기다린다.
            await _timeout_with_blocker(admin, runtime, holder)
        finally:
            await holder.rollback()
            await holder.execute(text(f"SELECT pg_advisory_unlock({_KEY})"))
            await holder.rollback()
    async with AsyncSession(runtime) as s, s.begin():
        await _gate(s)


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


async def test_shared_mode_is_retired_and_null_still_fails_and_rollback_recovers(scalar_engines):
    """ADR-117 §4-3: 공유 모드는 23514로 거부되고 아무 잠금도 남기지 않는다.

    434까지는 SH를 얻은 뒤의 EX 승격이 23514였다. 이제 SH 자체를 얻을 수 없으므로 승격도 없다.
    """
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as s:
        with pytest.raises(DBAPIError) as caught:
            await _gate(s, False)
        assert caught.value.orig.sqlstate == "23514"
        assert _RETIRED in str(caught.value.orig)
        # 거부된 호출은 P를 SH로도 잡지 않았다 — 다른 backend가 EX를 곧바로 얻는다.
        async with AsyncSession(admin) as observer, observer.begin():
            assert await observer.scalar(text(f"SELECT pg_try_advisory_xact_lock({_KEY})"))
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
        await _gate(holder)
        await _timeout_with_blocker(admin, runtime, holder, other_key=True)
