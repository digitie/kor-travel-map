"""provider_run_lock 본문이 Dagster DB pool(연결 1·추가 0)에서 죽지 않는다.

2026-10-12 prod run ``bfd18ef5``(``feature_notice_transport_highway_incidents_job``)은
4회 시도가 모두 시작 30초 만에 ``QueuePool limit of size 1 overflow 0 reached``로
죽었다. ``provider_run_lock``이 advisory lock용 session 하나로 pool의 유일한 연결을
쥔 채, 본문의 첫 client 호출(``get_notice_snapshot_watermark``)이 새 session으로 두
번째 연결을 기다렸기 때문이다.

자산 테스트(``test_notice_assets.py``)의 fake client는 lock이 연결을 쥐지 않으므로 이
결함을 보지 못했다. 여기서는 **실제** ``AsyncKorTravelMapClient``를 Dagster resource와
같은 pool 모양(``pool_size=1, max_overflow=0``)의 engine 위에서 돌린다. PostgreSQL
전용인 ``pg_advisory_lock`` SQL만 연결을 실제로 checkout하는 대역으로 바꾼다 — 대역도
lock이 연결을 쥐는 성질은 그대로 지킨다(그것이 결함의 원인이므로).
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from kortravelmap.client import AsyncKorTravelMapClient
from sqlalchemy import event, text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from kortravelmap import client as client_module

# `kortravelmap.infra`가 같은 이름의 함수를 재노출하므로 모듈은 이름으로 가져온다.
advisory_lock_module = importlib.import_module("kortravelmap.infra.advisory_lock")

_KEY = "provider-run:test:single-connection"

# prod 30초를 그대로 기다리면 회귀 시 테스트가 느려질 뿐 판정은 같다.
_POOL_TIMEOUT_SECONDS = 0.5


def _single_connection_engine(db_path: Path) -> AsyncEngine:
    """Dagster ``kor_travel_map_client_resource``와 같은 pool 모양의 engine."""
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
    )


@pytest.fixture
def lock_events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """PostgreSQL 전용 lock SQL을 연결을 실제로 쥐는 SQLite 대역으로 바꾼다.

    수정 후 경로는 ``connection_advisory_lock``이 부르는 infra의 획득·해제 한 문장을,
    수정 전 경로(그리고 큐 결합 경로)는 ``advisory_lock``을 쓴다 — 둘 다 바꿔야 수정
    전 코드에서도 같은 pool timeout이 재현된다. 대역도 lock 문장을 executor에서
    실행하므로 session이면 그 순간 pool에서 연결을 꺼내 lock 구간 내내 쥔다.
    """
    events: list[str] = []

    async def _acquire(executor: Any, key: str | int) -> None:
        await executor.execute(text("SELECT 1"))
        events.append(f"lock:{key}")

    async def _release(executor: Any, key: str | int) -> None:
        await executor.execute(text("SELECT 1"))
        events.append(f"unlock:{key}")

    @asynccontextmanager
    async def _holding_lock(executor: Any, key: str | int) -> AsyncIterator[None]:
        await _acquire(executor, key)
        try:
            yield
        finally:
            await _release(executor, key)

    monkeypatch.setattr(advisory_lock_module, "acquire_session_advisory_lock", _acquire)
    monkeypatch.setattr(advisory_lock_module, "release_session_advisory_lock", _release)
    monkeypatch.setattr(client_module, "advisory_lock", _holding_lock)
    return events


async def test_locked_body_db_calls_reuse_the_single_pooled_connection(
    tmp_path: Path,
    lock_events: list[str],
) -> None:
    """회귀: lock 본문의 DB 호출이 pool 두 번째 연결을 기다리지 않는다."""
    engine = _single_connection_engine(tmp_path / "single.db")
    observer = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'single.db'}")
    try:
        client = AsyncKorTravelMapClient(engine)
        async with client.provider_run_lock(_KEY):
            # 자산 본문처럼 단계마다 새 session을 열고 commit한다.
            async with client._session_factory() as session, session.begin():
                await session.execute(text("CREATE TABLE marker (v INTEGER)"))
            async with client._session_factory() as session, session.begin():
                await session.execute(text("INSERT INTO marker (v) VALUES (1)"))
            # 단계 commit은 lock이 끝나기 전에 실제로 반영된다(바깥 transaction에
            # 갇히지 않는다).
            async with observer.connect() as conn:
                assert (await conn.execute(text("SELECT v FROM marker"))).scalar_one() == 1
        assert lock_events == [f"lock:{_KEY}", f"unlock:{_KEY}"]

        # lock 밖에서는 원래 engine-bound factory로 돌아온다.
        async with client._session_factory() as session:
            assert (await session.execute(text("SELECT count(*) FROM marker"))).scalar_one() == 1
    finally:
        await observer.dispose()
        await engine.dispose()


async def test_locked_body_failure_discards_the_lock_connection(
    tmp_path: Path,
    lock_events: list[str],
) -> None:
    """본문이 실패·취소되면 lock 연결을 pool로 돌려보내지 않고 버린다.

    session-level lock은 rollback으로 풀리지 않고 pool reset도 ROLLBACK만 한다.
    망가졌을 수 있는 연결에 unlock을 시도하지 않고 invalidate해 server가 lock을
    풀게 한다 — 원래 예외는 가려지지 않는다.
    """
    engine = _single_connection_engine(tmp_path / "fail.db")
    try:
        client = AsyncKorTravelMapClient(engine)
        unpinned = client._session_factory
        leaked: list[Any] = []
        invalidated: list[object] = []
        event.listen(engine.sync_engine, "invalidate", lambda *_a: invalidated.append(1))

        class _BodyFailed(RuntimeError):
            pass

        async def _fail_inside_lock() -> None:
            async with client.provider_run_lock(_KEY):
                session = client._session_factory()
                leaked.append(session)
                await session.execute(text("SELECT 1"))
                # session을 닫지 않고 transaction을 연 채로 실패한다.
                raise _BodyFailed

        with pytest.raises(_BodyFailed):
            await _fail_inside_lock()

        assert client._session_factory is unpinned
        assert lock_events == [f"lock:{_KEY}"]
        assert invalidated == [1]
        # 버린 자리에 새 연결이 생긴다 — 막혀 있으면 pool timeout으로 죽는다.
        async with client._session_factory() as again:
            assert (await again.execute(text("SELECT 1"))).scalar_one() == 1
        await leaked[0].close()
    finally:
        await engine.dispose()


async def test_lock_release_failure_discards_the_connection_and_raises(
    tmp_path: Path,
    lock_events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unlock이 실패하면 lock을 쥐었을 수 있는 연결을 버리고 실패를 올린다."""
    engine = _single_connection_engine(tmp_path / "release.db")
    try:
        client = AsyncKorTravelMapClient(engine)
        invalidated: list[object] = []
        event.listen(engine.sync_engine, "invalidate", lambda *_a: invalidated.append(1))

        class _UnlockFailed(RuntimeError):
            pass

        async def _failing_release(_executor: Any, _key: str | int) -> None:
            raise _UnlockFailed

        monkeypatch.setattr(
            advisory_lock_module, "release_session_advisory_lock", _failing_release
        )

        async def _run() -> None:
            # 두 번째 context는 lock 진입 뒤에 평가된다 — lock 연결에 묶인 factory다.
            async with client.provider_run_lock(_KEY), client._session_factory() as session:
                await session.execute(text("SELECT 1"))

        with pytest.raises(_UnlockFailed):
            await _run()
        assert invalidated == [1]
        async with client._session_factory() as again:
            assert (await again.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_second_connection_really_is_unavailable_in_this_pool(
    tmp_path: Path,
) -> None:
    """전제 검사: 이 engine에서 연결 둘을 동시에 쥐면 pool timeout으로 죽는다.

    이 전제가 깨지면(pool 모양이 바뀌면) 위 회귀 테스트는 결함이 있어도 초록이 된다.
    """
    engine = _single_connection_engine(tmp_path / "premise.db")
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            with pytest.raises(PoolTimeoutError):
                async with engine.connect() as second:
                    await second.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
