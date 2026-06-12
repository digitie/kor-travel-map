"""``kortravelmap.infra.db`` — SQLAlchemy 2 async engine + session factory.

라이브러리 자체는 engine instance를 만들지 않는다. 호출자(TripMate / debug-ui /
테스트)가 ``KorTravelMapSettings.pg_dsn``으로 engine을 만들고 client/repo에
주입한다 (ADR-003 함수 라이브러리 + ADR-004 raw SQL).

본 모듈은 두 헬퍼만 제공한다:

- ``make_async_engine(dsn)`` — DSN → ``AsyncEngine`` (asyncpg driver 강제).
- ``make_async_session_factory(engine)`` — ``AsyncEngine`` →
  ``async_sessionmaker[AsyncSession]``.

ADR 참조
--------
- ADR-002 — async-only API
- ADR-003 — TripMate는 함수 직접 호출 (engine 주입)
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-007 — PostgreSQL 16 + SQLAlchemy 2 async + asyncpg
- ADR-008 — extension은 ``x_extension`` schema 격리

Sprint 1 scope
--------------
본 PR(#21)은 engine/session factory + testcontainers conftest. ORM 모델
(``infra/models.py``)과 repository(``infra/feature_repo.py``)는 Sprint 2
첫 provider 적재 직전 PR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

__all__ = [
    "make_async_engine",
    "make_async_session_factory",
    "normalize_async_dsn",
]


_ASYNCPG_PREFIX: str = "postgresql+asyncpg://"
"""SQLAlchemy 2 async DSN scheme — asyncpg driver 강제."""


def normalize_async_dsn(dsn: str) -> str:
    """raw ``postgresql://`` / ``postgres://`` / ``psycopg2``-style DSN을
    SQLAlchemy ``postgresql+asyncpg://`` 형태로 정규화한다.

    testcontainers의 ``get_connection_url()``은 보통 ``postgresql+psycopg2://``
    또는 ``postgresql://``를 반환하므로 본 함수로 변환한다 (ADR-007 asyncpg).

    Parameters
    ----------
    dsn
        DSN. 예: ``postgresql://user:pw@host:5432/db``,
        ``postgresql+psycopg2://...``, 이미 ``postgresql+asyncpg://...``.

    Returns
    -------
    str
        ``postgresql+asyncpg://...`` 형태.

    Raises
    ------
    ValueError
        DSN이 PostgreSQL scheme이 아닌 경우.
    """
    if not dsn:
        raise ValueError("dsn은 비어 있을 수 없음.")
    if dsn.startswith(_ASYNCPG_PREFIX):
        return dsn
    if dsn.startswith("postgresql+psycopg2://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql+psycopg2://") :]
    if dsn.startswith("postgresql+psycopg://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql+psycopg://") :]
    if dsn.startswith("postgresql://"):
        return _ASYNCPG_PREFIX + dsn[len("postgresql://") :]
    if dsn.startswith("postgres://"):
        return _ASYNCPG_PREFIX + dsn[len("postgres://") :]
    raise ValueError(
        f"dsn={dsn!r}은 PostgreSQL scheme이 아님 "
        f"(postgresql:// 또는 postgresql+asyncpg:// 필요)."
    )


def make_async_engine(
    dsn: str | SecretStr,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """``AsyncEngine`` 인스턴스를 만든다 (asyncpg driver).

    Parameters
    ----------
    dsn
        DSN. ``str`` 또는 Pydantic ``SecretStr`` (``KorTravelMapSettings.pg_dsn``).
        자동으로 ``postgresql+asyncpg://``로 정규화.
    echo
        SQL echo (디버그용). 운영에선 ``False``.
    pool_size
        connection pool 기본 크기.
    max_overflow
        pool 초과 허용량.
    pool_pre_ping
        체크아웃 시 ``SELECT 1`` 확인 (idle 끊김 방지). 운영 권장 ``True``.

    Returns
    -------
    AsyncEngine
        호출자가 ``await engine.dispose()`` 책임을 진다.
    """
    raw_dsn = dsn.get_secret_value() if hasattr(dsn, "get_secret_value") else str(dsn)
    normalized = normalize_async_dsn(raw_dsn)
    return create_async_engine(
        normalized,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )


def make_async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """``AsyncEngine`` → ``async_sessionmaker``.

    호출 측은 ``async with session_factory() as session:`` 패턴으로 사용한다.
    ``expire_on_commit=False`` — commit 후에도 ORM 인스턴스가 stale 되지 않게
    (단, 본 라이브러리는 raw SQL 위주이므로 거의 영향 없음).

    Parameters
    ----------
    engine
        ``make_async_engine``의 결과.

    Returns
    -------
    async_sessionmaker[AsyncSession]
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
