"""스트리밍 snapshot 적재는 받는 동안 ``feature-curation-write``를 쥐지 않는다(ADR-113).

2026-10-22 prod: ``feature_place_standard_parking_lots``가 batch마다 upstream fetch·역지오코딩을
열린 적재 transaction 안에서 해 fence를 2.5시간 넘게 쥐었다(대부분 ``idle in transaction``).
여기서는 느린 stream(받기 중간에 멈춘다)으로 실제 client 적재 경로를 돌려

- 받기가 멈춰 있는 동안 다른 연결이 fence를 **몇 초 안에** 잡는다(종전에는 첫 batch가 이미 fence를
  쥐어 55P03),
- 그 연결이 fence를 쥐는 동안 쓰기는 기다린다 — 쓰기 단계는 여전히 fence 아래다,
- 적재 결과의 seal은 commit된 image에서 다시 읽은 seal과 같다(한 DB image 계약),
- 큐 경로처럼 executor transaction에 결합한 client도 받는 동안 fence를 쥐지 않는다

를 보인다. Dagster와 같은 ``server_settings``(``lock_timeout=30000``) 엔진을 쓴다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.dagster.feature_update_runner import _bind_client_to_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.db import make_async_engine, make_async_session_factory
from kortravelmap.infra.feature_repo import (
    capture_provider_curation_input,
    lock_feature_curation_write,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration.test_client_orchestration import _canonical_uuid_for_alias, _Festival

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_DAGSTER_SERVER_SETTINGS = {"statement_timeout": "600000", "lock_timeout": "30000"}
"""``kortravelmap.dagster.resources.kor_travel_map_client_resource``와 같은 값."""

_OTHER_WRITER_LOCK_TIMEOUT = "3s"
"""다른 writer가 fence를 기다리는 상한 — 받기 중이면 즉시 잡혀야 한다."""

_TRUNCATE_SQL = (
    "TRUNCATE feature.features, "
    "provider_sync.source_entities, provider_sync.source_entity_heads, "
    "provider_sync.source_records, "
    "provider_sync.source_links RESTART IDENTITY CASCADE"
)

_TRY_FENCE_SQL = text(
    "SELECT pg_catalog.pg_try_advisory_xact_lock("
    "pg_catalog.hashtextextended('feature-curation-write', 0))"
)


@pytest.fixture
async def dagster_like_engine(
    dagster_runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine]:
    dsn = dagster_runtime_engine.url.render_as_string(hide_password=False)
    engine = make_async_engine(
        dsn, pool_size=1, max_overflow=0, server_settings=_DAGSTER_SERVER_SETTINGS
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def _bundles(*seeds: str) -> list[FeatureBundle]:
    items = [
        _Festival(
            fstvl_nm="스풀 검증 축제",
            opar="여의도공원",
            fstvl_start_date=date(2026, 4, 5),
            fstvl_end_date=date(2026, 4, 12),
            rdnmadr=f"서울특별시 영등포구 여의공원로 120 ({seed})",
            lnmadr="서울특별시 영등포구 여의도동 8",
            latitude=37.5263,
            longitude=126.9239,
            reference_date=date(2026, 3, 1),
            instt_nm="서울특별시 영등포구",
        )
        for seed in seeds
    ]
    return await cultural_festivals_to_bundles(
        items,  # type: ignore[arg-type]
        fetched_at=datetime(2026, 10, 22, 12, 0, tzinfo=_KST),
    )


class _PausingStream:
    """첫 batch를 내준 뒤 ``proceed``까지 멈춘다 — upstream fetch·지오코딩 공백의 대역."""

    def __init__(self, first: Sequence[FeatureBundle], rest: Sequence[FeatureBundle]) -> None:
        self.first = list(first)
        self.rest = list(rest)
        self.paused = asyncio.Event()
        self.proceed = asyncio.Event()

    async def __call__(self) -> AsyncIterator[Sequence[FeatureBundle]]:
        yield self.first
        self.paused.set()
        await self.proceed.wait()
        yield self.rest


class _OtherWriter:
    """다른 연결의 fence writer(단건 writer·root 완결 모양).

    짧게 기다려 잡고 ``release``까지 쥔다.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self.holding = asyncio.Event()
        self.release = asyncio.Event()
        self.waited: float | None = None

    async def run(self) -> None:
        async with make_async_session_factory(self._engine)() as session, session.begin():
            await session.execute(text(f"SET LOCAL lock_timeout = '{_OTHER_WRITER_LOCK_TIMEOUT}'"))
            began = time.monotonic()
            await lock_feature_curation_write(session)
            self.waited = time.monotonic() - began
            self.holding.set()
            await self.release.wait()


async def _finish(*tasks: asyncio.Task[Any]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


_FENCE_WAITERS_SQL = text(
    "SELECT count(*) FROM pg_catalog.pg_locks "
    "WHERE locktype = 'advisory' AND NOT granted AND objsubid = 1 "
    "AND ((classid::bigint << 32) | objid::bigint) = "
    "pg_catalog.hashtextextended('feature-curation-write', 0)"
)


async def _a_fence_waiter_appears(engine: AsyncEngine, within_seconds: float = 30.0) -> bool:
    """``feature-curation-write`` 미부여 대기가 ``within_seconds`` 안에 보이는가."""
    deadline = time.monotonic() + within_seconds
    while time.monotonic() < deadline:
        async with AsyncSession(engine) as session:
            if int((await session.execute(_FENCE_WAITERS_SQL)).scalar_one()):
                return True
        await asyncio.sleep(0.2)
    return False


async def _seal_of_committed_image(engine: AsyncEngine, provider: str, dataset_key: str) -> str:
    async with AsyncSession(engine) as session, session.begin():
        sealed = await capture_provider_curation_input(
            session, provider=provider, dataset_key=dataset_key
        )
    assert sealed.curation_input_set_hash is not None
    return sealed.curation_input_set_hash


async def test_fence_is_free_while_the_stream_is_fetching_and_held_while_writing(
    dagster_like_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    bundles = await _bundles("SPOOL-A", "SPOOL-B", "SPOOL-C")
    record = bundles[0].source_record
    stream = _PausingStream(bundles[:1], bundles[1:])
    client = AsyncKorTravelMapClient(
        dagster_like_engine,
        settings=KorTravelMapSettings(feature_load_curation_lock_wait_seconds=120),
    )
    other = _OtherWriter(migrated_engine)

    load_task = asyncio.create_task(
        client.load_feature_bundle_batches(
            stream(), curation_dataset=(record.provider, record.dataset_key)
        )
    )
    other_task: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(stream.paused.wait(), timeout=30)
        # 받기가 첫 batch 뒤에서 멈춰 있다. 종전 코드는 여기서 이미 첫 batch를 쓰며 fence를 쥐었다.
        other_task = asyncio.create_task(other.run())
        holding = asyncio.create_task(other.holding.wait())
        await asyncio.wait({holding, other_task}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
        if other_task.done():
            # 종전 코드: 첫 batch를 쓴 적재가 fence를 쥐어 다른 writer가 3초 만에 55P03.
            other_task.result()
        holding.cancel()
        assert other.holding.is_set(), "다른 writer가 15초 안에 fence를 잡지 못했다"
        assert other.waited is not None
        assert other.waited < 2.0, f"받는 동안 다른 writer가 fence를 {other.waited:.1f}초 기다렸다"

        # 받기를 끝낸다. 쓰기는 다른 writer가 fence를 놓을 때까지 기다려야 한다 — "아직 안 끝났다"가
        # 아니라 **잠금 대기 중**임을 pg_locks에서 본다(느린 runner에서의 거짓 초록 방지).
        stream.proceed.set()
        assert await _a_fence_waiter_appears(migrated_engine), "쓰기 단계가 fence를 기다리지 않았다"
        assert not load_task.done()

        other.release.set()
        await other_task
        result = await asyncio.wait_for(load_task, timeout=120)
    finally:
        await _finish(load_task, *([other_task] if other_task is not None else []))

    assert result.bundles_total == 3
    for bundle in bundles:
        assert await _canonical_uuid_for_alias(migrated_engine, bundle.feature.feature_id)
    # seal은 commit된 image의 seal과 같다(일관성 확인).
    # 끼어들기 차단 자체는 위의 잠금 대기가 보인다.
    assert result.curation_input_set_hash == await _seal_of_committed_image(
        migrated_engine, record.provider, record.dataset_key
    )
    assert result.curation_input_member_count is not None
    assert result.curation_input_member_count >= 3


async def test_queue_bound_client_does_not_hold_the_fence_while_fetching(
    dagster_like_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    """큐 경로: executor transaction에 결합한 client도 받는 동안 fence가 비어 있다."""
    bundles = await _bundles("SPOOL-Q1", "SPOOL-Q2")
    stream = _PausingStream(bundles[:1], bundles[1:])
    client = AsyncKorTravelMapClient(
        dagster_like_engine,
        settings=KorTravelMapSettings(feature_load_curation_lock_wait_seconds=120),
    )

    async def _probe_fence_free() -> bool:
        async with make_async_session_factory(migrated_engine)() as session, session.begin():
            return bool((await session.execute(_TRY_FENCE_SQL)).scalar_one())

    async with make_async_session_factory(dagster_like_engine)() as executor:
        async with executor.begin():
            # executor의 scope transaction(heartbeat 등)이 열려 있는 모양.
            await executor.execute(text("SELECT 1"))
            bound = await _bind_client_to_session(client, executor)
            load_task = asyncio.create_task(bound.load_feature_bundle_batches(stream()))
            try:
                await asyncio.wait_for(stream.paused.wait(), timeout=30)
                assert await _probe_fence_free(), "받는 동안 executor transaction이 fence를 쥐었다"
                stream.proceed.set()
                result = await asyncio.wait_for(load_task, timeout=120)
            finally:
                await _finish(load_task)
            # 쓴 뒤에는 executor transaction이 commit할 때까지 fence를 쥔다(종전과 같은 원자성).
            assert not await _probe_fence_free()
        assert await _probe_fence_free()

    assert result.bundles_total == 2
    for bundle in bundles:
        assert await _canonical_uuid_for_alias(migrated_engine, bundle.feature.feature_id)
