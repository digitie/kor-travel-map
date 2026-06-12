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

from kortravelmap.infra.advisory_lock import advisory_lock, try_advisory_lock

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KEY = "test:advisory:mois-bulk"
_OTHER = "test:advisory:other"


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
