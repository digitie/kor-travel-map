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
    from sqlalchemy import event, text

    from krtour.map.infra.db import make_async_engine

    raw_dsn = pg_container.get_connection_url()
    engine = make_async_engine(raw_dsn)

    # 모든 새 connection의 search_path를 ADR-008 격리 schema 포함으로 설정.
    # `ALTER DATABASE ... SET search_path`는 새 connection에만 적용되고
    # SQLAlchemy connection pool은 기존 connection을 재사용하므로, connect 이벤트
    # 훅으로 명시 설정 → unqualified ``ST_*`` 함수 호출 가능.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_conn: Any, _conn_record: Any) -> None:
        # asyncpg adapter는 sync cursor를 제공 (DBAPI 호환 wrapper).
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SET search_path = public, x_extension")
        finally:
            cursor.close()

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
        # connect-event의 session-level ``SET search_path``는 asyncpg pool이
        # connection을 reset(RESET ALL)하면 지워질 수 있다 — 다른 테스트가 bare
        # ``AsyncSession``으로 connection을 recycle하면 다음 unqualified ``ST_*``
        # 호출이 깨진다. role 레벨로 못박아 reset 후에도 유지 (migrated_engine과
        # 동일 방어, ADR-008).
        await conn.execute(
            text("ALTER ROLE CURRENT_USER SET search_path = public, x_extension")
        )

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test ``AsyncSession`` + 자동 rollback.

    각 테스트는 transaction 안에서 실행되며 종료 시 rollback — 테스트 간
    데이터 격리 보장. 실 commit이 필요한 케이스는 별도 fixture를 만든다.

    ``search_path``는 ``pg_engine``의 ``connect`` 이벤트 훅이 모든 새 connection에
    설정 — pool에서 재사용되는 connection도 마찬가지. 따라서 unqualified
    ``ST_*`` 함수 호출 가능 (ADR-008).
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(pg_engine, expire_on_commit=False) as session, session.begin():
        yield session
        await session.rollback()


@pytest.fixture(scope="session")
async def migrated_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """`alembic upgrade head` 적용된 async engine (DB 적재 round-trip 테스트용).

    `pg_engine`(직접 schema/extension 생성)과 달리 실 DDL(Alembic 0001/0002)로
    테이블까지 만든 엔진. search_path에 ``x_extension`` 포함 → unqualified ST_*
    (GeoAlchemy2 INSERT의 ``ST_GeomFromEWKT`` 등) 호출 가능 (ADR-008/012).
    """
    import asyncio
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import event

    from alembic import command
    from krtour.map.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    async_dsn = normalize_async_dsn(raw_dsn)

    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync path-arith
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = make_async_engine(async_dsn)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_conn: Any, _conn_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SET search_path = public, x_extension")
        finally:
            cursor.close()

    # asyncpg connection pool은 connect 이벤트의 ``SET search_path``가 모든
    # 체크아웃 연결에 일관 적용된다는 보장이 약하다 (pool 재사용/타이밍). GeoAlchemy2가
    # INSERT 시 emit하는 unqualified ``ST_GeomFromEWKT`` 등 PostGIS 함수가 어느
    # 연결에서도 해석되도록 role 레벨로 search_path를 못박는다 (ADR-008).
    # connect-listener는 신규 연결 즉시 보강용으로 유지.
    from sqlalchemy import text as _text

    async with engine.begin() as _conn:
        await _conn.execute(
            _text("ALTER ROLE CURRENT_USER SET search_path = public, x_extension")
        )

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_session(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """migrated_engine per-test ``AsyncSession`` + 자동 rollback (테스트 간 격리).

    INSERT 후 ``flush``하면 STORED generated column(coord_5179)이 DB에서 계산되어
    같은 transaction 내에서 재조회 가능. teardown에서 rollback.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        yield session
        await session.rollback()
