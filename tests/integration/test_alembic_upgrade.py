"""``test_alembic_upgrade`` — `alembic upgrade head` 적용 후 schema 검증.

PR#28 (Sprint 2 prep) — Alembic 첫 revision (0001 + 0002)이 testcontainers
PostGIS에서 깨끗하게 적용되는지 확인 + 4 schema / 3 extension / 4 신규 테이블
존재 확인.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


pytestmark = pytest.mark.integration


async def _run_alembic_upgrade(dsn: str) -> None:
    """``alembic.command.upgrade(cfg, "head")``를 worker thread에서 실행.

    alembic은 sync API + 자체 asyncio.run(env.py)을 호출하므로 현재 pytest
    event loop과 충돌. ``asyncio.to_thread``로 별도 thread에서 alembic의
    asyncio 호출이 자기 event loop을 만들도록 분리.

    env.py는 ``Config.get_main_option("sqlalchemy.url")``을 우선 사용하므로
    여기서 박은 DSN이 적용됨 (KRTOUR_MAP_PG_DSN env var 불필요).
    """
    import asyncio
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync IO is trivial path-arith here
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest.fixture(scope="session")
async def pg_engine_with_migrations(pg_container: object) -> object:
    """``pg_engine``과 동일하지만 alembic 적용 후 yield.

    ``pg_engine``의 schema/extension 직접 생성 fixture를 우회 — alembic가
    혼자 만들어내는지 확인하기 위함.
    """
    from krtour.map.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    async_dsn = normalize_async_dsn(raw_dsn)

    # alembic은 본인이 schema/extension 생성하므로 pg_engine의 setup은 건너뛴다.
    await _run_alembic_upgrade(async_dsn)

    engine = make_async_engine(async_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_alembic_creates_4_schemas(pg_engine_with_migrations: AsyncEngine) -> None:
    """0001 revision이 4 schema 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('feature','provider_sync','ops','x_extension') "
                "ORDER BY nspname"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["feature", "ops", "provider_sync", "x_extension"]


async def test_alembic_creates_3_extensions_in_x_extension(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0001 revision이 3 extension을 ``x_extension``에 격리 생성 (ADR-008)."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT e.extname, n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname IN ('postgis','pg_trgm','pgcrypto') "
                "ORDER BY e.extname"
            )
        )
        rows = list(result)
    assert len(rows) == 3
    for ext_name, schema in rows:
        assert schema == "x_extension", (
            f"{ext_name} in {schema}, expected x_extension (ADR-008)"
        )


async def test_alembic_creates_features_table(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0002 revision이 ``feature.features`` 테이블 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "ORDER BY ordinal_position"
            )
        )
        columns = [row[0] for row in result]
    # 핵심 컬럼 존재 확인.
    for required in (
        "feature_id", "kind", "name", "category", "coord", "coord_5179",
        "geom", "address", "detail", "status", "created_at", "updated_at",
    ):
        assert required in columns, f"missing column: {required}"


async def test_alembic_coord_5179_is_generated_stored(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """ADR-012 — ``coord_5179``는 STORED generated column."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "AND column_name='coord_5179'"
            )
        )
        row = result.one()
    assert row.is_generated == "ALWAYS"
    # PostgreSQL은 generation_expression을 재파싱하며 함수명을 소문자 +
    # 스키마 한정으로 정규화한다 (예: ``x_extension.st_transform(coord, 5179)``).
    # 따라서 대소문자 무시하고 ``st_transform`` 참조만 확인 (ADR-008 + ADR-012).
    assert "st_transform" in (row.generation_expression or "").lower()


async def test_alembic_creates_source_tables(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0002 revision이 source_records / source_links / provider_sync_state 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='provider_sync' "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result]
    assert tables == ["provider_sync_state", "source_links", "source_records"]


async def test_alembic_features_indexes_exist(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """핵심 GIST/GIN/partial 인덱스 존재."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='feature' AND tablename='features'"
            )
        )
        idx = {row[0] for row in result}
    required = {
        "idx_features_coord_gist",
        "idx_features_coord_5179_gist",
        "idx_features_geom_gist",
        "idx_features_kind_category",
        "idx_features_name_trgm",
    }
    missing = required - idx
    assert not missing, f"missing indexes: {missing}"


async def test_alembic_creates_feature_merge_history(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0007 revision이 ``ops.feature_merge_history`` 생성 (ADR-016)."""
    async with pg_engine_with_migrations.connect() as conn:
        exists = (
            await conn.execute(
                text("SELECT to_regclass('ops.feature_merge_history')")
            )
        ).scalar_one()
    assert exists is not None
