"""``test_cli_mutex`` — CLI mutex 상호 배제 (ADR-039).

``mutex_lock``/``try_mutex_lock``이 ``infra.advisory_lock`` 위에서 같은 CLI lock
키로 중복 실행을 직렬화하는지 두 세션으로 검증한다. 테이블 불필요 → ``pg_engine``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.cli import (
    import_lock_key,
    mutex_lock,
    try_mutex_lock,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KEY = import_lock_key("python-mois-api", "mois_license_features_bulk")


async def test_try_mutex_excludes_concurrent_run(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with (
        AsyncSession(pg_engine) as s1,
        AsyncSession(pg_engine) as s2,
    ):
        async with try_mutex_lock(s1, _KEY) as acquired1:
            assert acquired1 is True
            # 같은 import 키 → 둘째 실행은 즉시 skip.
            async with try_mutex_lock(s2, _KEY) as acquired2:
                assert acquired2 is False
        # 첫 실행 종료 후 재획득 가능.
        async with try_mutex_lock(s2, _KEY) as acquired3:
            assert acquired3 is True


async def test_blocking_mutex_releases(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with (
        AsyncSession(pg_engine) as s1,
        AsyncSession(pg_engine) as s2,
    ):
        async with mutex_lock(s1, _KEY), try_mutex_lock(s2, _KEY) as held:
            assert held is False
        async with try_mutex_lock(s2, _KEY) as freed:
            assert freed is True


async def test_distinct_keys_independent(pg_engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    other = import_lock_key("python-knps-api", "bulk")
    async with (
        AsyncSession(pg_engine) as s1,
        try_mutex_lock(s1, _KEY) as a,
        try_mutex_lock(s1, other) as b,
    ):
        # 다른 키는 같은 세션이어도 독립 획득.
        assert a is True
        assert b is True
