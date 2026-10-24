"""실제 full bootstrap의 7개 직접 CALL이 validation 이전 protocol EX를 잡는지 반증한다.

기존 scalar fixture의 자체 UUID PostGIS만 재사용한다. fixture 모듈의 다른 시험은 실행하지 않는다.
공유 DB/외부 DSN/원천 HTTP/운영 역할에는 연결하지 않는다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines

pytestmark = pytest.mark.integration
_OWNERS = {
    "archive_curation_item_command": "ktm_curation_command_owner",
    "create_curation_item_command": "ktm_curation_command_owner",
    "create_manual_curation_item_with_feature_command": "ktm_curation_command_owner",
    "finalize_provider_curation_root": "ktm_curation_command_owner",
    "patch_curation_item_command": "ktm_curation_command_owner",
    "reclassify_curation_quarantine_command": "ktm_curation_command_owner",
    "register_provider_field_shadow_policy": "ktm_feature_schema_owner",
}
# 외부 superuser인 owned lab login을 유지하므로 manual writer의 session_user 검사는
# 기존 42501을 낸다. grant/역할 체크를 우회하거나 제품 함수를 고치지 않는다.
_VALIDATION = {name: "23514" for name in _OWNERS} | {
    "create_manual_curation_item_with_feature_command": "42501",
    "finalize_provider_curation_root": "P0002",
}
_PROTOCOL = "PERFORM ops.lock_scoped_feature_write_protocol(true);"
_UPGRADE_ERROR = "protocol share to exclusive upgrade requires replan"
_TRY_GLOBAL = text("SELECT pg_try_advisory_xact_lock(hashtextextended('feature-curation-write',0))")


@dataclass(frozen=True)
class Routine:
    name: str
    owner: str
    body: str
    call: str
    public_execute: bool
    runtime_execute: bool
    profile_execute: bool


async def _routine(engine: AsyncEngine, name: str) -> Routine:
    assert name in _OWNERS
    async with engine.connect() as connection:
        await connection.execute(text("SET LOCAL search_path TO pg_catalog"))
        assert await connection.scalar(
            text("SELECT rolsuper FROM pg_roles WHERE rolname=session_user")
        )
        rows = (
            (
                await connection.execute(
                    text("""SELECT procedure.proname,role.rolname AS owner,
            procedure.prosrc,procedure.prokind::text AS kind,procedure.prosecdef,
            ARRAY(SELECT format_type(argument_oid,NULL)
              FROM unnest(COALESCE(procedure.proallargtypes,procedure.proargtypes::oid[]))
                WITH ORDINALITY argument(argument_oid,position) ORDER BY position) AS types,
            EXISTS(SELECT 1 FROM aclexplode(COALESCE(procedure.proacl,
              acldefault('f',procedure.proowner))) acl
              WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE') AS public_execute,
            has_function_privilege('ktm_feature_runtime',procedure.oid,'EXECUTE')
                AS runtime_execute,
            has_function_privilege(CAST(:profile AS name),procedure.oid,'EXECUTE')
                AS profile_execute
            FROM pg_proc procedure
            JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
            JOIN pg_roles role ON role.oid=procedure.proowner
            WHERE namespace.nspname='feature' AND procedure.proname=:name"""),
                    {
                        "name": name,
                        "profile": "ktm_curation_provider_executor"
                        if name == "finalize_provider_curation_root"
                        else "ktm_feature_schema_owner"
                        if name == "register_provider_field_shadow_policy"
                        else "ktm_curation_admin_executor",
                    },
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "p"
    assert row["prosecdef"]
    return Routine(
        name,
        row["owner"],
        row["prosrc"],
        "CALL feature." + name + "(" + ",".join("NULL::" + t for t in row["types"]) + ")",
        bool(row["public_execute"]),
        bool(row["runtime_execute"]),
        bool(row["profile_execute"]),
    )


async def _prepare_call(session: AsyncSession, routine: Routine) -> int:
    # isolation은 첫 SQL 전 선택하고 owner 식별자는 위 고정 whitelist에서만 온다.
    await session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
    await session.execute(text("SET LOCAL statement_timeout='5s'"))
    await session.execute(text("SET LOCAL lock_timeout='3s'"))
    await session.execute(text("SET LOCAL ROLE " + routine.owner))
    assert await session.scalar(text("SELECT current_user")) == routine.owner
    return int(await session.scalar(text("SELECT pg_backend_pid()")))


async def _released(engine: AsyncEngine) -> None:
    async with engine.begin() as observer:
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert await observer.scalar(_TRY_GLOBAL)


@pytest.mark.parametrize("name", sorted(_OWNERS))
async def test_actual_entry_owner_acl_and_first_begin(scalar_engines: Any, name: str) -> None:
    admin, _ = scalar_engines
    routine = await _routine(admin, name)
    assert routine.owner == _OWNERS[name]
    assert routine.body.partition("\nBEGIN\n")[2].lstrip().startswith(_PROTOCOL)
    assert routine.body.count(_PROTOCOL) == 1
    assert not routine.public_execute
    assert not routine.runtime_execute
    assert routine.profile_execute


@pytest.mark.parametrize("name", sorted(_OWNERS))
async def test_shared_to_direct_call_is_rejected_before_validation(
    scalar_engines: Any,
    name: str,
) -> None:
    admin, _ = scalar_engines
    routine = await _routine(admin, name)
    async with AsyncSession(admin) as session:
        await _prepare_call(session, routine)
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        try:
            with pytest.raises(DBAPIError) as failed:
                await session.execute(text(routine.call))
            assert failed.value.orig.sqlstate == "23514"
            assert _UPGRADE_ERROR in str(failed.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


@pytest.mark.parametrize("name", sorted(_OWNERS))
async def test_direct_call_waits_on_protocol_without_taking_old_global(
    scalar_engines: Any,
    name: str,
) -> None:
    admin, runtime = scalar_engines
    routine = await _routine(admin, name)
    async with AsyncSession(runtime) as scoped, AsyncSession(admin) as legacy:
        scoped_pid = int(await scoped.scalar(text("SELECT pg_backend_pid()")))
        await scoped.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        legacy_pid = await _prepare_call(legacy, routine)
        call = asyncio.create_task(legacy.execute(text(routine.call)))
        try:
            async with admin.connect() as observer:
                async with asyncio.timeout(2):
                    while True:
                        blockers = await observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": legacy_pid}
                        )
                        if scoped_pid in blockers:
                            break
                        assert not call.done(), "CALL finished before waiting for protocol"
                        await asyncio.sleep(0.01)
                assert not call.done()
                # observer가 old global을 잡을 수 있어야 protocol-before-oldglobal이다.
                assert await observer.scalar(_TRY_GLOBAL)
                await observer.rollback()
            await scoped.rollback()
            with pytest.raises(DBAPIError) as failed:
                await asyncio.wait_for(call, timeout=3)
            assert failed.value.orig.sqlstate == _VALIDATION[name]
            assert _UPGRADE_ERROR not in str(failed.value.orig)
        finally:
            await scoped.rollback()
            if not call.done():
                call.cancel()
                await asyncio.gather(call, return_exceptions=True)
            await legacy.rollback()
    await _released(admin)
