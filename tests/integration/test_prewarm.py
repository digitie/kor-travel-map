"""pg_prewarm 부팅 후 warm-up 통합 테스트 (T-102, PostGIS testcontainers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from krtour.map.infra.prewarm import (
    DEFAULT_HOT_RELATIONS,
    prewarm_extension_available,
    prewarm_relations,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_pg_prewarm_extension_installed(migrated_session: AsyncSession) -> None:
    """migration 0022로 pg_prewarm 확장이 x_extension 스키마에 설치된다."""
    assert await prewarm_extension_available(migrated_session) is True


async def test_prewarm_relations_warms_features(
    migrated_session: AsyncSession,
) -> None:
    """`feature.features`는 warm 대상에 포함되고 block count(≥0)를 돌려준다."""
    warmed = await prewarm_relations(migrated_session)
    assert "feature.features" in warmed
    assert warmed["feature.features"] >= 0
    # 결과 키는 전부 요청한 relation의 부분집합(존재하지 않는 이름은 skip).
    assert set(warmed).issubset(set(DEFAULT_HOT_RELATIONS))


async def test_prewarm_relations_skips_missing(
    migrated_session: AsyncSession,
) -> None:
    """존재하지 않는 relation은 조용히 건너뛴다(에러 없음)."""
    warmed = await prewarm_relations(
        migrated_session, relations=("feature.features", "feature.does_not_exist")
    )
    assert "feature.features" in warmed
    assert "feature.does_not_exist" not in warmed
