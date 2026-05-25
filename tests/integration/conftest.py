"""``tests/integration/conftest.py`` — testcontainers PostGIS 통합 테스트 베이스.

``docs/test-strategy.md §4.1`` 명세 구현:

- ``pg_container`` — session-scope ``postgis/postgis:16-3.5-alpine``.
- ``pg_engine`` — session-scope ``AsyncEngine`` + 4 schema + 3 extension 생성.
- ``feature_schema`` — session-scope (현재는 placeholder, Sprint 2 실 DDL 박힘).
- ``pg_session`` — per-test ``AsyncSession`` + 자동 rollback.

Docker가 없거나 testcontainers가 설치되지 않은 환경에서는 모든 통합 테스트가
``pytest.skip``된다 (CI에서 Docker 보장 시 정상 실행).

ADR 참조
--------
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- ADR-008 — extension은 ``x_extension`` schema 격리
- ADR-002 — async-only (asyncpg driver)
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


# 4 schema (data-model.md §2 + ADR-008)
_SCHEMAS: tuple[str, ...] = ("feature", "provider_sync", "ops", "x_extension")

# 3 extension (postgres-schema.md §1)
_EXTENSIONS: tuple[str, ...] = ("postgis", "pg_trgm", "pgcrypto")

# Docker image (docs/test-strategy.md §4.1)
_POSTGIS_IMAGE: str = "postgis/postgis:16-3.5-alpine"


def _import_testcontainers() -> Any | None:
    """testcontainers가 설치된 경우 import, 아니면 None.

    Docker가 없거나 dev extras가 설치되지 않은 환경에서 본 conftest가
    collect 단계에서 실패하지 않도록 동적 import.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None
    return PostgresContainer


@pytest.fixture(scope="session")
def pg_container() -> Iterator[Any]:
    """PostGIS 컨테이너 (session-scope).

    Docker / testcontainers 미설치 환경에서는 ``pytest.skip``.
    """
    container_cls = _import_testcontainers()
    if container_cls is None:
        pytest.skip(
            "testcontainers not installed — `pip install -e .[dev]` to enable "
            "integration tests."
        )
    try:
        container = container_cls(_POSTGIS_IMAGE)
    except Exception as exc:  # pragma: no cover — Docker not available
        pytest.skip(f"PostgresContainer init failed (Docker?): {exc}")
    with container:
        yield container


@pytest.fixture(scope="session")
async def pg_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """Async engine + 4 schema + 3 extension 생성 (session-scope).

    extension은 모두 ``x_extension`` schema에 격리 (ADR-008). 본 fixture
    이후 모든 통합 테스트는 schema/extension 이미 박혀 있다고 가정.
    """
    from sqlalchemy import text

    from krtour.map.infra.db import make_async_engine

    raw_dsn = pg_container.get_connection_url()
    engine = make_async_engine(raw_dsn)

    async with engine.begin() as conn:
        for schema in _SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        # postgis/postgis Docker image는 initdb 단계에서 postgis + postgis_topology를
        # `public` schema에 자동 설치한다. ADR-008에 따라 `x_extension` schema로
        # 재배치 — DROP CASCADE 후 재생성 (테스트 시작 시점이므로 안전).
        await conn.execute(text("DROP EXTENSION IF EXISTS postgis_topology CASCADE"))
        await conn.execute(text("DROP EXTENSION IF EXISTS postgis CASCADE"))
        for ext in _EXTENSIONS:
            await conn.execute(
                text(f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA x_extension")
            )
        # 모든 세션 default search_path는 본 라이브러리 가정 (data-model.md §1)
        await conn.execute(text("ALTER DATABASE test SET search_path = public, x_extension"))

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test ``AsyncSession`` + 자동 rollback.

    각 테스트는 transaction 안에서 실행되며 종료 시 rollback — 테스트 간
    데이터 격리 보장. 실 commit이 필요한 케이스는 별도 fixture를 만든다.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(pg_engine, expire_on_commit=False) as session, session.begin():
        yield session
        await session.rollback()
