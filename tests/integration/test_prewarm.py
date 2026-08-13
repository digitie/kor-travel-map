"""pg_prewarm 부팅 후 warm-up 통합 테스트 (T-102, PostGIS testcontainers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.prewarm import (
    DEFAULT_HOT_RELATIONS,
    prewarm_extension_available,
    prewarm_relations,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_CREATE_PG_PREWARM = "CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension"


async def _pg_prewarm_module_available(session: AsyncSession) -> bool:
    """서버에 pg_prewarm contrib 모듈이 깔려 있는지(설치 여부가 아니라 설치 가능 여부)."""
    return (
        await session.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_prewarm'")
        )
    ).scalar_one_or_none() is not None


@pytest.fixture
async def prewarm_ready_session(
    migrated_session: AsyncSession,
) -> AsyncSession:
    """pg_prewarm이 설치된 세션 — 배포의 **superuser bootstrap 단계**를 재현한다.

    ADR-090 이후 alembic은 NOSUPERUSER ``ktm_feature_migrator``로만 돈다. migration
    ``0022``는 "current_user가 superuser일 때만 CREATE EXTENSION"이라 그 principal
    아래에서는 영구 no-op이고, pg_prewarm은 trusted extension이 아니어서 schema owner로도
    만들 수 없다. 실제 설치 지점은 ``docker/postgres-role-bootstrap.sh``의 dedicated
    superuser connection 하나뿐이다(이번에 그 한 줄이 빠져 있어 채웠다).

    통합 테스트 DB를 만드는 공유 helper(``_tvn34_migration_bootstrap``)는 아직
    postgis/pg_trgm/pgcrypto만 심는다. 그래서 여기서 같은 superuser 단계를 재현한다 —
    ``migrated_session``은 컨테이너 superuser로 열린 per-test 트랜잭션이고 CREATE
    EXTENSION은 트랜잭션 안에서 되돌려지므로, session-scope DB를 오염시키지 않는다.
    (teardown은 그 rollback이 전부라 이 fixture 자체는 정리할 것이 없다.)
    """
    if not await _pg_prewarm_module_available(migrated_session):
        pytest.skip("pg_prewarm contrib module not available on this server")
    await migrated_session.execute(text(_CREATE_PG_PREWARM))
    return migrated_session


async def test_pg_prewarm_extension_available_tracks_installation(
    migrated_session: AsyncSession,
) -> None:
    """확장 판정이 카탈로그 실재와 일치하고, 미설치면 warm은 조용히 no-op이다.

    원래 이 테스트는 "migration 0022가 확장을 설치한다"를 단언했는데, ADR-090의
    restricted migrator 아래에서 0022는 no-op이라 그 명제 자체가 더 이상 참이 아니다.
    지금 지켜야 할 계약은 두 가지다 — ① 판정 helper가 카탈로그와 어긋나지 않을 것,
    ② 확장이 없으면 에러가 아니라 빈 결과로 degrade할 것(opt-in/best-effort).
    설치 주체(superuser bootstrap)가 제 몫을 하면 판정이 True로 뒤집히는 것까지 본다.
    """
    installed = (
        await migrated_session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm'")
        )
    ).scalar_one_or_none() is not None
    assert await prewarm_extension_available(migrated_session) is installed

    if not installed:
        assert await prewarm_relations(migrated_session) == {}

    if not await _pg_prewarm_module_available(migrated_session):
        pytest.skip("pg_prewarm contrib module not available on this server")
    await migrated_session.execute(text(_CREATE_PG_PREWARM))
    assert await prewarm_extension_available(migrated_session) is True


async def test_prewarm_relations_warms_features(
    prewarm_ready_session: AsyncSession,
) -> None:
    """`feature.features`는 warm 대상에 포함되고 block count(≥0)를 돌려준다."""
    warmed = await prewarm_relations(prewarm_ready_session)
    assert "feature.features" in warmed
    assert warmed["feature.features"] >= 0
    # 결과 키는 전부 요청한 relation의 부분집합(존재하지 않는 이름은 skip).
    assert set(warmed).issubset(set(DEFAULT_HOT_RELATIONS))


async def test_prewarm_relations_skips_missing(
    prewarm_ready_session: AsyncSession,
) -> None:
    """존재하지 않는 relation은 조용히 건너뛴다(에러 없음)."""
    warmed = await prewarm_relations(
        prewarm_ready_session, relations=("feature.features", "feature.does_not_exist")
    )
    assert "feature.features" in warmed
    assert "feature.does_not_exist" not in warmed
