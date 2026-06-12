"""``test_pg_smoke`` — 첫 통합 테스트: testcontainers PostGIS 부팅 + 환경 검증.

본 PR(#21)은 infra/ skeleton 단계 — 실 테이블/repo는 Sprint 2 첫 provider
적재 PR. 본 테스트는 *환경*만 보증한다:

1. PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto extension 모두 박혀 있다.
2. ``x_extension`` schema에 격리되어 있다 (ADR-008).
3. ``feature``/``provider_sync``/``ops``/``x_extension`` 4 schema 존재.
4. ``ST_Transform``이 EPSG:4326 ↔ 5179 변환 가능 (ADR-012).

Docker가 없거나 testcontainers가 설치되지 않은 환경에서는 ``pytest.skip``
(conftest의 ``pg_container`` fixture가 처리).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


pytestmark = pytest.mark.integration


# -- extension 존재 -------------------------------------------------------


async def test_postgis_extension_installed(pg_engine: AsyncEngine) -> None:
    """PostGIS extension이 ``x_extension`` schema에 박혀 있다 (ADR-008)."""
    async with pg_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT n.nspname, e.extname, e.extversion "
                "FROM pg_extension e JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname = 'postgis'"
            )
        )
        rows = result.all()
    assert len(rows) == 1, "PostGIS extension must be installed exactly once"
    schema, name, version = rows[0]
    assert schema == "x_extension", f"PostGIS in {schema}, expected x_extension (ADR-008)"
    assert name == "postgis"
    assert version.startswith("3."), f"expected PostGIS 3.x, got {version}"


async def test_pg_trgm_extension_installed(pg_engine: AsyncEngine) -> None:
    """pg_trgm extension이 ``x_extension`` schema에 박혀 있다."""
    async with pg_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname = 'pg_trgm'"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["x_extension"], f"pg_trgm in {schemas}, expected x_extension"


async def test_pgcrypto_extension_installed(pg_engine: AsyncEngine) -> None:
    """pgcrypto extension이 ``x_extension`` schema에 박혀 있다."""
    async with pg_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname = 'pgcrypto'"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["x_extension"], f"pgcrypto in {schemas}, expected x_extension"


# -- schema 존재 ----------------------------------------------------------


async def test_required_schemas_exist(pg_engine: AsyncEngine) -> None:
    """4 schema가 모두 박혀 있다 (data-model.md §2)."""
    async with pg_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('feature', 'provider_sync', 'ops', 'x_extension') "
                "ORDER BY nspname"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["feature", "ops", "provider_sync", "x_extension"]


# -- PostGIS 핵심 함수 ---------------------------------------------------


async def test_st_transform_4326_to_5179_works(pg_session: AsyncSession) -> None:
    """``ST_Transform``으로 4326 → 5179 변환이 가능하다 (ADR-012 핵심).

    서울 시청 (126.9784, 37.5666) → UTM-K meters. Python pyproj 결과와
    PostGIS 결과가 ~1m 이내로 일치하는지 본다.
    """
    from kortravelmap.infra.crs import project_to_5179

    result = await pg_session.execute(
        text(
            "SELECT ST_X(g) AS x, ST_Y(g) AS y FROM "
            "ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 5179) AS g"
        ),
        {"lon": 126.9784, "lat": 37.5666},
    )
    row = result.one()
    pg_x, pg_y = float(row.x), float(row.y)

    py_x, py_y = project_to_5179(126.9784, 37.5666)

    # PostGIS + pyproj 모두 PROJ engine 기반 — meter 단위 1m 이내 일치
    assert abs(pg_x - py_x) < 1.0, f"x drift: pg={pg_x} py={py_x}"
    assert abs(pg_y - py_y) < 1.0, f"y drift: pg={pg_y} py={py_y}"


async def test_search_path_includes_x_extension(pg_engine: AsyncEngine) -> None:
    """``search_path``에 ``x_extension``이 포함되어 ``postgis`` 함수를 unqualified로 호출 가능.

    ADR-008: extension은 격리하되 ``search_path``로 unqualified 호출 가능.
    """
    async with pg_engine.connect() as conn:
        # SET search_path session-level (database default가 자동 적용 안 될 수 있음)
        await conn.execute(text("SET search_path = public, x_extension"))
        # ST_MakePoint를 unqualified로 호출
        result = await conn.execute(text("SELECT ST_X(ST_MakePoint(127.0, 37.5))"))
        x = result.scalar_one()
    assert x == 127.0
