"""전역 fence의 같은 transaction 재진입만 줄인다. 실제 PG의 잠금 수명으로 반증한다."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, SAWarning
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.feature_repo import (
    arm_feature_curation_write_wait,
    lock_feature_curation_write,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_TRY = text(
    "SELECT pg_try_advisory_xact_lock(hashtextextended('feature-curation-write', 0))"
)


@pytest.fixture
def fence_calls(pg_engine: AsyncEngine) -> Iterator[list[str]]:
    calls: list[str] = []

    def before(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if "pg_advisory_xact_lock(" in statement and "feature-curation-write" in statement:
            calls.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", before)
    try:
        yield calls
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", before)


async def _free(engine: AsyncEngine) -> bool:
    async with AsyncSession(engine) as probe, probe.begin():
        return bool(await probe.scalar(_TRY))


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_one_sql_per_root_and_no_reuse_across_transactions(
    pg_engine: AsyncEngine, fence_calls: list[str], finish: str
) -> None:
    async with AsyncSession(pg_engine) as session:
        for _ in range(50):
            await lock_feature_curation_write(session)
        assert len(fence_calls) == 1
        assert not await _free(pg_engine)
        await getattr(session, finish)()
        assert await _free(pg_engine)
        await lock_feature_curation_write(session)
        assert len(fence_calls) == 2
        assert not await _free(pg_engine)
        await session.rollback()
    assert await _free(pg_engine)


async def test_root_acquisition_survives_unrelated_savepoint_rollback(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with AsyncSession(pg_engine) as session, session.begin():
        await lock_feature_curation_write(session)
        savepoint = await session.begin_nested()
        await lock_feature_curation_write(session)
        await savepoint.rollback()
        await lock_feature_curation_write(session)
        assert len(fence_calls) == 1
        assert not await _free(pg_engine)
    assert await _free(pg_engine)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_acquisition_inside_savepoint_is_rechecked_after_it_ends(
    pg_engine: AsyncEngine, fence_calls: list[str], finish: str
) -> None:
    async with AsyncSession(pg_engine) as session, session.begin():
        savepoint = await session.begin_nested()
        await lock_feature_curation_write(session)
        await lock_feature_curation_write(session)
        assert len(fence_calls) == 2  # nested 획득은 조상 수명을 입증할 수 없어 캐시하지 않는다.
        await getattr(savepoint, finish)()
        # rollback은 savepoint에서 얻은 xact advisory를 실제로 놓는다.
        assert await _free(pg_engine) is (finish == "rollback")
        await lock_feature_curation_write(session)
        assert len(fence_calls) == 3
        assert not await _free(pg_engine)
    assert await _free(pg_engine)


async def test_external_connection_transaction_end_never_reuses_old_fence(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with pg_engine.connect() as connection:
        external = await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="rollback_only") as session:
            await lock_feature_curation_write(session)
            assert not await _free(pg_engine)
            await external.commit()
            assert await _free(pg_engine)
            await lock_feature_curation_write(session)
            assert len(fence_calls) == 2
            assert not await _free(pg_engine)
            # 외부에서 먼저 끝낸 SessionTransaction을 정리하는 SQLAlchemy 경고는 예상된다.
            with pytest.warns(SAWarning, match="transaction already deassociated"):
                await session.rollback()
            await connection.rollback()
    assert await _free(pg_engine)


async def test_failed_acquisition_does_not_cache_and_next_transaction_locks(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with AsyncSession(pg_engine) as holder, holder.begin():
        await lock_feature_curation_write(holder)
        async with AsyncSession(pg_engine) as waiter:
            await waiter.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError):
                await lock_feature_curation_write(waiter)
            await waiter.rollback()
            await holder.commit()
            await lock_feature_curation_write(waiter)
            assert len(fence_calls) == 3
            assert not await _free(pg_engine)
            await waiter.rollback()
    assert await _free(pg_engine)


async def test_cancelled_wait_does_not_cache(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with AsyncSession(pg_engine) as holder, holder.begin():
        await lock_feature_curation_write(holder)
        async with AsyncSession(pg_engine) as waiter:
            await waiter.execute(text("SET LOCAL lock_timeout = '1s'"))
            arm_feature_curation_write_wait(waiter, 3000)
            sent = asyncio.Event()

            def mark_sent(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                if "pg_advisory_xact_lock(" in statement:
                    sent.set()

            event.listen(pg_engine.sync_engine, "before_cursor_execute", mark_sent)
            task = asyncio.create_task(lock_feature_curation_write(waiter))
            try:
                await asyncio.wait_for(sent.wait(), timeout=5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                event.remove(pg_engine.sync_engine, "before_cursor_execute", mark_sent)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await waiter.rollback()
            await holder.commit()
            await lock_feature_curation_write(waiter)
            assert len(fence_calls) == 3
            assert not await _free(pg_engine)
            await waiter.rollback()
    assert await _free(pg_engine)


async def test_external_ancestor_savepoint_rollback_never_reuses_child_fence(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with pg_engine.connect() as connection:
        await connection.begin()
        parent = await connection.begin_nested()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            await lock_feature_curation_write(session)
            assert not await _free(pg_engine)
            with pytest.warns(SAWarning, match="nested transaction already deassociated"):
                await parent.rollback()
            assert await _free(pg_engine)
            # SQLAlchemy 자식 is_active는 true여도 실제 PG 잠금은 해제됐다.
            await lock_feature_curation_write(session)
            assert len(fence_calls) == 2
            assert not await _free(pg_engine)
        finally:
            # 의도적으로 ancestor를 먼저 끝낸 fault fixture의 잘못된 자식 SAVEPOINT는
            # 다시 rollback하지 않고 연결을 폐기한다. 운영 세션을 건드리지 않는다.
            await session.invalidate()
    assert await _free(pg_engine)


async def test_caught_core_sql_error_invalidates_success_proof_before_rollback(
    pg_engine: AsyncEngine, fence_calls: list[str]
) -> None:
    async with AsyncSession(pg_engine) as session:
        await lock_feature_curation_write(session)
        with pytest.raises(DBAPIError) as original:
            await session.execute(text("SELECT 1 / 0"))
        assert getattr(original.value.orig, "sqlstate", None) == "22012"
        assert session.sync_session.get_transaction().is_active
        assert await _free(pg_engine)  # PG abort는 xact advisory lock을 이미 해제했다.
        with pytest.raises(DBAPIError) as aborted:
            await lock_feature_curation_write(session)
        assert getattr(aborted.value.orig, "sqlstate", None) == "25P02"
        assert len(fence_calls) == 2
        await session.rollback()
        await lock_feature_curation_write(session)
        assert len(fence_calls) == 3
        assert not await _free(pg_engine)
        await session.rollback()
    assert await _free(pg_engine)
