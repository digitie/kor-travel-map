"""고유 PostGIS에서 tracking 진입 순서·직접 SD·롤백 경계를 반증한다."""

from __future__ import annotations

import asyncio
import hashlib
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_spec = spec_from_file_location(
    "_integration_424",
    Path(__file__).resolve().parents[2] / "alembic/versions/424_tracking_protocol_prefix.py",
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)
_FINAL = sorted(n for n, item in _migration._EXPECTED.items() if item["finalizing"])
_LEAF = sorted(n for n, item in _migration._EXPECTED.items() if not item["finalizing"])
_L = 6832465333779826081
_P = "SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"
_GOLDEN = (Path(__file__).resolve().parents[2] / "alembic/head-schema.sql").read_text()


async def _direct(session, name):
    item = _migration._EXPECTED[name]
    modes = item["modes"] or ["i"] * len(item["types"])
    # procedure OUT에는 typed NULL이 필요하고 FUNCTION TABLE 출력은 인수가 아니다.
    args = [
        "NULL::" + kind
        for kind, mode in zip(item["types"], modes, strict=True)
        if item["kind"] == "p" or mode in ("i", "b", "v")
    ]
    command = "CALL " if item["kind"] == "p" else "SELECT * FROM "
    await session.execute(text(command + name + "(" + ",".join(args) + ")"))


async def _owner(session):
    await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
    await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
    await session.execute(text("SET LOCAL lock_timeout='700ms'"))
    await session.execute(text("SET LOCAL statement_timeout='3s'"))
    return int(await session.scalar(text("SELECT pg_backend_pid()")))


async def _released(admin):
    async with admin.begin() as observer:
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _L})


@pytest.mark.parametrize("name", sorted(_migration._EXPECTED))
async def test_catalog_original_body_owner_acl_and_prefix(scalar_engines, name):
    admin, _ = scalar_engines
    async with admin.connect() as observer:
        row = (
            (await observer.execute(text(_migration._CATALOG_SQL), {"names": [name]}))
            .mappings()
            .one()
        )
        helper = (
            await observer.execute(
                text("""SELECT r.rolname,p.prosecdef,p.proconfig,
          has_function_privilege('ktm_feature_runtime',p.oid,'EXECUTE'),
          EXISTS(SELECT 1 FROM aclexplode(p.proacl) WHERE grantee=0)
          FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
          WHERE p.oid='ops.lock_provider_feature_tracking_protocol(boolean)'::regprocedure""")
            )
        ).one()
    item = _migration._EXPECTED[name]
    entry = (
        "  PERFORM ops.lock_provider_feature_tracking_protocol("
        + str(item["finalizing"]).lower()
        + ");\n"
    )
    assert row["body"].partition("\nBEGIN\n")[2].startswith(entry)
    assert row["body"].count(entry) == 1
    if name in {
        "feature.finalize_provider_curation_root",
        "feature.seal_provider_curation_snapshot_receipt",
        "ops.finish_provider_feature_membership_command",
    }:
        # 430이 의도적으로 바꾼 세 본문은 실제 fresh430 공식 dump와 전부 대조한다.
        bodies = re.findall(
            rf"CREATE (?:FUNCTION|PROCEDURE) {re.escape(name)}\(.*?AS (\$[A-Za-z0-9_]*\$)(.*?)\1;",
            _GOLDEN,
            re.DOTALL,
        )
        assert len(bodies) == 1
        assert row["body"] == bodies[0][1]
    else:
        assert (
            hashlib.sha256(row["body"].replace(entry, "", 1).encode()).hexdigest()
            == item["body_sha256"]
        )
    assert row["owner"] == "ktm_curation_command_owner"
    assert row["config"] == item["config"]
    assert row["names"] == item["names"]
    assert row["modes"] == item["modes"]
    assert row["types"] == item["types"]
    assert tuple(helper) == (
        "ktm_curation_command_owner",
        True,
        ["search_path=pg_catalog"],
        True,
        False,
    )


@pytest.mark.parametrize("name", _FINAL)
async def test_final_l_only_rejects_before_protocol_or_input(scalar_engines, name):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await _owner(session)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _L})
        try:
            with pytest.raises(DBAPIError) as caught:
                await _direct(session, name)
            assert caught.value.orig.sqlstate == "23514"
            assert "cannot acquire protocol after lineage" in str(caught.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


@pytest.mark.parametrize("name", _LEAF)
@pytest.mark.parametrize("exclusive", [False, True])
async def test_leaf_p_without_l_refuses_new_blocking_l(scalar_engines, name, exclusive):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await _owner(session)
        await session.execute(text(_P), {"exclusive": exclusive})
        try:
            with pytest.raises(DBAPIError) as caught:
                await _direct(session, name)
            assert caught.value.orig.sqlstate == "23514"
            assert "leaf cannot acquire lineage" in str(caught.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


@pytest.mark.parametrize("name", _FINAL)
async def test_final_waits_on_exact_protocol_pid_before_lineage(scalar_engines, name):
    admin, runtime = scalar_engines
    ready = asyncio.get_running_loop().create_future()
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text(_P), {"exclusive": False})
        blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))

        async def call():
            async with AsyncSession(admin) as session:
                pid = await _owner(session)
                ready.set_result(pid)
                try:
                    with pytest.raises(DBAPIError) as caught:
                        await _direct(session, name)
                    assert caught.value.orig.sqlstate == "55P03"
                finally:
                    await session.rollback()

        task = asyncio.create_task(call())
        try:
            pid = await asyncio.wait_for(ready, 3)
            async with asyncio.timeout(2):
                while True:
                    if task.done():
                        await task
                        raise AssertionError("call ended before protocol blocker observation")
                    async with admin.connect() as observer:
                        found = await observer.scalar(
                            text("""SELECT EXISTS(
                          SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                          AND database=(SELECT oid FROM pg_database
                                        WHERE datname=current_database())
                          AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
                          AND mode='ExclusiveLock' AND NOT granted)
                          AND :blocker=ANY(pg_blocking_pids(:pid))"""),
                            {"pid": pid, "blocker": blocker},
                        )
                    if found:
                        break
                    await asyncio.sleep(0.005)
            async with admin.begin() as observer:
                assert await observer.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _L}
                )
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    await _released(admin)


async def test_null_mode_and_reentry_preserve_settings(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        try:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("SELECT ops.lock_provider_feature_tracking_protocol(NULL)")
                )
            assert caught.value.orig.sqlstate == "22023"
        finally:
            await session.rollback()
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='17ms'"))
        original = await session.scalar(text("SELECT current_user"))
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(false)"))
        assert await session.scalar(text("SHOW lock_timeout")) == "17ms"
        assert await session.scalar(text("SELECT current_user")) == original
    await _released(admin)
