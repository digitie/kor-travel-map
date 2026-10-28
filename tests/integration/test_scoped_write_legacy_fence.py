"""기존 Python writer의 protocol-first 순서를 실제 두 PG 세션으로 반증한다.

435(ADR-117)부터 P는 배타 전용이다. 434까지 blocker로 쓰던 P SH는 P EX로 바꿨고, "SH caller의
fence는 승격 거부" 사례는 SH 요청 자체가 23514로 거부되는 사례로 바꿨다.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from kortravelmap.infra.feature_repo import lock_feature_curation_write

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PROTOCOL_SHARE = text("SELECT ops.lock_scoped_feature_write_protocol(false)")
_PROTOCOL_EXCLUSIVE = text("SELECT ops.lock_scoped_feature_write_protocol(true)")
_TRY_PROTOCOL_SHARE = text("SELECT pg_try_advisory_xact_lock_shared(1369104691,115)")
_TRY_GLOBAL = text(
    "SELECT pg_try_advisory_xact_lock(hashtextextended('feature-curation-write',0))"
)


async def _can_take(engine: AsyncEngine, statement: TextClause) -> bool:
    async with AsyncSession(engine) as session:
        try:
            return bool(await session.scalar(statement))
        finally:
            await session.rollback()


async def _wait_until_lock_wait(engine: AsyncEngine, pid: int) -> None:
    async def observe() -> None:
        # observer의 transaction도 매번 끝내 pg_stat snapshot을 재사용하지 않는다.
        while True:
            async with AsyncSession(engine) as observer:
                waiting = await observer.scalar(
                    text(
                        "SELECT wait_event_type='Lock' FROM pg_stat_activity "
                        "WHERE pid=:pid AND state='active'"
                    ),
                    {"pid": pid},
                )
            if waiting:
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(observe(), timeout=10)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_legacy_fence_excludes_shared_protocol_until_root_ends(
    migrated_engine: AsyncEngine, finish: str
) -> None:
    async with AsyncSession(migrated_engine) as writer:
        await lock_feature_curation_write(writer)
        # 같은 TX 재진입 최적화가 두 잠금 중 하나를 일찍 놓아서는 안 된다.
        await lock_feature_curation_write(writer)
        assert not await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
        assert not await _can_take(migrated_engine, _TRY_GLOBAL)
        await getattr(writer, finish)()
    assert await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
    assert await _can_take(migrated_engine, _TRY_GLOBAL)


async def test_protocol_wait_precedes_global_lock(
    migrated_engine: AsyncEngine,
) -> None:
    async with (
        AsyncSession(migrated_engine) as scoped,
        AsyncSession(migrated_engine) as legacy,
    ):
        await scoped.execute(_PROTOCOL_EXCLUSIVE)
        pid = int(await legacy.scalar(text("SELECT pg_backend_pid()")))
        task = asyncio.create_task(lock_feature_curation_write(legacy))
        try:
            await _wait_until_lock_wait(migrated_engine, pid)
            # CTE보다 기존 fence를 먼저 얻었다면 이 검사에서 실패한다.
            assert await _can_take(migrated_engine, _TRY_GLOBAL)
            assert not task.done()
            await scoped.rollback()
            await asyncio.wait_for(task, timeout=10)
            assert not await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
            assert not await _can_take(migrated_engine, _TRY_GLOBAL)
        finally:
            await scoped.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await legacy.rollback()
    assert await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
    assert await _can_take(migrated_engine, _TRY_GLOBAL)


async def test_retired_shared_request_requires_rollback_then_replan(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session:
        with pytest.raises(DBAPIError) as exc:
            await session.execute(_PROTOCOL_SHARE)
        assert getattr(exc.value.orig, "sqlstate", None) == "23514"
        assert "shared protocol mode was retired (ADR-117)" in str(exc.value.orig)
        await session.rollback()
        # 실패한 gate를 cache해 재사용하지 않는다.
        await lock_feature_curation_write(session)
        assert not await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
        await session.rollback()
    assert await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)


async def test_savepoint_rollback_releases_both_and_reentry_reacquires(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        savepoint = await session.begin_nested()
        await lock_feature_curation_write(session)
        assert not await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
        await savepoint.rollback()
        assert await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
        assert await _can_take(migrated_engine, _TRY_GLOBAL)
        await lock_feature_curation_write(session)
        assert not await _can_take(migrated_engine, _TRY_PROTOCOL_SHARE)
        assert not await _can_take(migrated_engine, _TRY_GLOBAL)
        await session.rollback()
