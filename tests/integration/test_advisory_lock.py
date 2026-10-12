"""``test_advisory_lock`` — PostgreSQL advisory lock 상호 배제 (ADR-011).

두 독립 ``AsyncSession``(서로 다른 connection)으로 advisory lock의 상호 배제와
release 동작을 검증한다. 테이블이 필요 없으므로 ``pg_engine``(schema/extension만)
fixture를 쓴다.

검증: ① try_advisory_lock 상호 배제(첫 세션 보유 중 둘째는 False) ② context exit
시 release → 재획득 가능 ③ blocking advisory_lock release ④ 다른 키는 독립.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.advisory_lock import advisory_lock, try_advisory_lock

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KEY = "test:advisory:mois-bulk"
_OTHER = "test:advisory:other"
_SNAPSHOT_GC_KEY = "cache-target-snapshot-gc"


async def test_try_lock_mutual_exclusion_and_release(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    # 두 독립 세션 = 두 connection (advisory lock은 connection 단위).
    async with (
        AsyncSession(pg_engine) as s1,
        AsyncSession(pg_engine) as s2,
    ):
        async with try_advisory_lock(s1, _KEY) as acquired1:
            assert acquired1 is True
            # 같은 키 → 둘째 세션은 즉시 False (대기 안 함).
            async with try_advisory_lock(s2, _KEY) as acquired2:
                assert acquired2 is False
            # 다른 키 → 독립적으로 획득 가능.
            async with try_advisory_lock(s2, _OTHER) as acquired_other:
                assert acquired_other is True
        # s1 context exit 후 → s2가 같은 키 재획득 가능 (release 확인).
        async with try_advisory_lock(s2, _KEY) as acquired3:
            assert acquired3 is True


async def test_blocking_lock_releases_on_exit(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with (
        AsyncSession(pg_engine) as s1,
        AsyncSession(pg_engine) as s2,
    ):
        async with advisory_lock(s1, _KEY), try_advisory_lock(s2, _KEY) as acquired:
            # 보유 중 → 둘째 세션 try는 실패.
            assert acquired is False
        # exit 후 release → try 성공.
        async with try_advisory_lock(s2, _KEY) as acquired:
            assert acquired is True


async def test_same_session_reentrant_via_int_key(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.advisory_lock import advisory_lock_key

    lock_id = advisory_lock_key(_KEY)
    # int 키도 동일 동작 (해싱 생략).
    async with (
        AsyncSession(pg_engine) as s1,
        try_advisory_lock(s1, lock_id) as acquired,
    ):
        assert acquired is True


async def test_client_provider_run_lock_excludes_other_process_path(
    pg_engine: AsyncEngine,
) -> None:
    """client 공개 lock이 독립 connection의 동일 provider 실행을 막고 해제한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    key = "provider-run:test-provider"
    client = AsyncKorTravelMapClient(pg_engine)
    async with AsyncSession(pg_engine) as competitor:
        async with (
            client.provider_run_lock(key),
            try_advisory_lock(competitor, key) as acquired,
        ):
            assert acquired is False
        async with try_advisory_lock(competitor, key) as acquired:
            assert acquired is True


async def test_provider_run_lock_body_runs_on_the_dagster_single_connection_pool(
    migrated_engine: AsyncEngine,
    dagster_runtime_engine: AsyncEngine,
) -> None:
    """회귀(prod run ``bfd18ef5``): lock 본문이 pool 두 번째 연결을 기다리지 않는다.

    Dagster ``kor_travel_map_client`` resource는 ``pool_size=1, max_overflow=0``이다
    (ADR-107). 고속도로 돌발 asset은 ``provider_run_lock`` 안에서 첫 DB 호출로
    ``get_notice_snapshot_watermark``를 부르고, 수정 전에는 lock session이 유일한
    연결을 쥔 탓에 그 자리에서 ``QueuePool limit of size 1 overflow 0``으로 죽었다.
    실제 Dagster runtime login으로 같은 pool 모양의 engine을 만들어 그 순서를 재현한다.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from kortravelmap.providers.kor_travel_transport import (
        DATASET_KEY_HIGHWAY_INCIDENTS,
        KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
    )

    key = "provider-run:test:dagster-single-connection"
    engine = create_async_engine(
        dagster_runtime_engine.url,
        pool_size=1,
        max_overflow=0,
        # prod는 30초다. 판정은 같고 회귀 시 실패만 빨라진다.
        pool_timeout=2,
    )
    client = AsyncKorTravelMapClient(engine)
    try:
        # advisory lock은 database 단위다 — 경쟁자는 runtime engine과 같은 DB에 붙는다.
        async with AsyncSession(migrated_engine) as competitor:
            async with client.provider_run_lock(key):
                watermark = await client.get_notice_snapshot_watermark(
                    provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
                    dataset_key=DATASET_KEY_HIGHWAY_INCIDENTS,
                    source_entity_type="traffic_notice",
                )
                assert watermark is None or watermark.utcoffset() is not None
                # 본문이 lock 연결을 빌려 쓰는 동안에도 lock은 유지된다.
                async with try_advisory_lock(competitor, key) as acquired:
                    assert acquired is False
            async with try_advisory_lock(competitor, key) as acquired:
                assert acquired is True
    finally:
        await engine.dispose()


async def test_snapshot_gc_drain_runs_on_the_dagster_single_connection_pool(
    dagster_runtime_engine: AsyncEngine,
) -> None:
    """회귀: GC drain의 batch·관측 session이 lock 연결 외의 연결을 요구하지 않는다.

    ``cache_target_snapshot_gc`` job도 pool 1·추가 0인 Dagster
    ``kor_travel_map_client``를 쓴다(ADR-107). 수정 전에는 lock 연결을 쥔 채 첫 batch
    session이 두 번째 연결을 기다리다 ``QueuePool limit of size 1 overflow 0``으로
    죽었다(고속도로 돌발 ``provider_run_lock``과 같은 결함).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        dagster_runtime_engine.url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
    )
    try:
        result = await AsyncKorTravelMapClient(engine).drain_expired_cache_target_snapshots(
            max_batches=2,
            max_seconds=30,
        )
    finally:
        await engine.dispose()
    assert result.acquired is True
    assert result.skipped is False
    assert result.batches >= 1
    assert result.remaining_items is not None


async def test_snapshot_gc_lock_survives_acquisition_commit_and_skips_overlap(
    pg_engine: AsyncEngine,
) -> None:
    """session lock은 획득 transaction commit 뒤에도 같은 backend에서 유지된다."""
    client = AsyncKorTravelMapClient(pg_engine)
    async with pg_engine.connect() as owner, try_advisory_lock(
        owner,
        _SNAPSHOT_GC_KEY,
    ) as acquired:
        assert acquired
        await owner.commit()
        result = await client.drain_expired_cache_target_snapshots()
        assert result.acquired is False
        assert result.skipped is True
        assert result.remaining_items is None
        assert result.remaining_headers is None
