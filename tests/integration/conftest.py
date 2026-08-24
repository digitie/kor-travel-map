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

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from tests.integration._application_300_bootstrap import (
    _TEST_MIGRATOR_PASSWORD,
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)

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

    from kortravelmap.infra.db import make_async_engine

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
        # 공식 `postgis/postgis:16-3.5-alpine`의 새 cluster에는 extension이 자동
        # 생성되지 않는다. fixture도 production fresh bootstrap과 같은 방향으로
        # `x_extension`에 명시 생성한다. public 등에 이미 존재하는 extension을 여기서
        # drop/repair하면 actual fresh deployment의 precondition을 가리므로 허용하지 않는다.
        existing_extensions = {
            row.extname: row.nspname
            for row in (
                await conn.execute(
                    text(
                        "SELECT e.extname, n.nspname FROM pg_extension e "
                        "JOIN pg_namespace n ON e.extnamespace = n.oid "
                        "WHERE e.extname IN ('postgis','postgis_topology')"
                    )
                )
            )
        }
        misplaced_extensions = {
            name: schema
            for name, schema in existing_extensions.items()
            if schema != "x_extension"
        }
        if misplaced_extensions:
            raise RuntimeError(
                "integration PostGIS fixture requires extensions in x_extension; "
                f"found {misplaced_extensions}"
            )
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
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import event
    from sqlalchemy.engine import make_url

    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    # 같은 컨테이너 기본 DB를 `pg_engine`과 공유한다. 예전에는 그것이 순서 결합을
    # 만들었다 — `pg_engine`은 app schema를 컨테이너 superuser로
    # `CREATE SCHEMA IF NOT EXISTS`하고 이 fixture는 배포 경로
    # (`ktm_feature_migrator` → SET ROLE `ktm_feature_schema_owner`)로 migration을
    # 도는데, `IF NOT EXISTS`는 이미 있는 schema에 AUTHORIZATION을 적용하지 않으므로
    # 먼저 선 쪽이 소유권을 확정했다. 그래서 "알파벳순 첫 파일이 migrated_engine을
    # 먼저 요구하게 한다"는 파일명 규약에 기대고 있었다.
    #
    # 지금은 bootstrap이 `ALTER SCHEMA ... OWNER TO ktm_feature_schema_owner`로
    # 소유권을 **확정**하므로 순서가 무의미하다. DB를 나누지 않는 이유는 CLI 계열
    # 테스트가 컨테이너 기본 DB를 직접 가리키기 때문이다 — 나누면 그쪽이 빈 DB를 본다.
    async_dsn = normalize_async_dsn(raw_dsn)
    migrator_dsn = make_url(async_dsn).set(
        username="ktm_feature_migrator",
        password=_TEST_MIGRATOR_PASSWORD,
    )

    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync path-arith
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", migrator_dsn.render_as_string(hide_password=False))
    await upgrade_head_with_application_300_bootstrap(cfg, async_dsn)

    # Production API entrypoint performs this immediately after Alembic while
    # only the migrator DSN exists.  Keep the shared fixture on that executable
    # path so runtime integration tests never obtain old bootstrap-owner ACLs.
    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

    previous_pg_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrator_dsn.render_as_string(hide_password=False)
    try:
        await reconcile_runtime_privileges()
    finally:
        if previous_pg_dsn is None:
            os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
        else:
            os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous_pg_dsn

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


@pytest.fixture
async def tvn_m01_m05_role_graph(migrated_engine: AsyncEngine) -> None:
    """호환 fixture 이름. `300` bootstrap은 이미 final M01~M05 graph를 만든다."""

    del migrated_engine


@pytest.fixture(scope="session")
async def dagster_runtime_engine(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine]:
    """실제 Dagster LOGIN을 쓰는 integration 전용 engine.

    provider operation command는 ``session_user``가 provider executor
    membership을 가져야만 실행된다. 관리자 seed/assertion engine과 섞지 않고,
    실제 Dagster runtime identity로 client 경로를 검증한다.
    """
    from kortravelmap.infra.db import make_async_engine

    dsn = migrated_engine.url.set(
        username="ktm_feature_dagster_runtime",
        password=_TEST_RUNTIME_PASSWORD,
    ).render_as_string(hide_password=False)
    engine = make_async_engine(dsn, pool_size=1)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
async def api_runtime_engine(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine]:
    """실제 API LOGIN을 쓰는 integration 전용 engine.

    취소 terminal command는 API runtime이 실행하고, 성공한 provider root의
    curation finalizer만 transaction-local cancellation fence로 위임한다.
    root seed engine으로 이 경계를 우회하지 않는다.
    """
    from kortravelmap.infra.db import make_async_engine

    dsn = migrated_engine.url.set(
        username="ktm_feature_api_runtime",
        password=_TEST_RUNTIME_PASSWORD,
    ).render_as_string(hide_password=False)
    engine = make_async_engine(dsn, pool_size=1)
    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def as_dagster_runtime(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """기존 seed transaction에서 provider command만 실제 runtime으로 실행한다."""
    from sqlalchemy import text

    await session.execute(
        text("SET LOCAL SESSION AUTHORIZATION 'ktm_feature_dagster_runtime'")
    )
    try:
        yield session
    except BaseException:
        # 기대한 DB 오류는 caller가 savepoint를 rollback해 복구한다. abort 상태에서
        # RESET을 보내면 원래 SQLSTATE를 25P02로 덮어 쓰므로 여기서는 건드리지 않는다.
        raise
    else:
        await session.execute(text("SET LOCAL SESSION AUTHORIZATION DEFAULT"))


@asynccontextmanager
async def as_api_runtime(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """기존 seed transaction에서 admin command만 실제 API runtime으로 실행한다."""

    from sqlalchemy import text

    await session.execute(
        text("SET LOCAL SESSION AUTHORIZATION 'ktm_feature_api_runtime'")
    )
    try:
        yield session
    except BaseException:
        # savepoint rollback이 LOCAL authorization까지 함께 되돌린다.
        raise
    else:
        await session.execute(text("SET LOCAL SESSION AUTHORIZATION DEFAULT"))
