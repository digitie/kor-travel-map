"""``test_db`` — ``kortravelmap.infra.db`` async engine + DSN 정규화.

실 DB 없이 DSN 정규화 + engine 객체 타입만 확인 (실 connection은
``tests/integration/`` 책임). 엔진 생성 테스트는 ``asyncpg`` 미설치 환경에서
skip — pyproject.toml 본 의존이므로 CI/실 사용 환경에선 항상 통과.
"""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kortravelmap.infra.db import (
    make_async_engine,
    make_async_session_factory,
    normalize_async_dsn,
)

_HAS_ASYNCPG = importlib.util.find_spec("asyncpg") is not None
_skip_no_asyncpg = pytest.mark.skipif(
    not _HAS_ASYNCPG,
    reason="asyncpg not installed (`pip install asyncpg`)",
)


# -- normalize_async_dsn ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # asyncpg는 그대로
        (
            "postgresql+asyncpg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # postgresql → asyncpg
        (
            "postgresql://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # postgres (alias) → asyncpg
        (
            "postgres://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # psycopg2 → asyncpg (testcontainers 기본)
        (
            "postgresql+psycopg2://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        # psycopg3 → asyncpg
        (
            "postgresql+psycopg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
    ],
)
def test_normalize_async_dsn_converts_to_asyncpg(raw: str, expected: str) -> None:
    """모든 PostgreSQL DSN을 ``postgresql+asyncpg://``로 통일."""
    assert normalize_async_dsn(raw) == expected


def test_normalize_async_dsn_empty_raises() -> None:
    """빈 DSN은 ValueError."""
    with pytest.raises(ValueError, match="비어"):
        normalize_async_dsn("")


def test_normalize_async_dsn_non_postgres_raises() -> None:
    """PostgreSQL이 아닌 scheme은 ValueError."""
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_async_dsn("mysql://u:p@h/d")


# -- make_async_engine -----------------------------------------------------


@_skip_no_asyncpg
def test_make_async_engine_returns_async_engine() -> None:
    """``AsyncEngine`` 인스턴스를 반환한다 (실 connection 시도 없음)."""
    engine = make_async_engine("postgresql://u:p@localhost:5432/test")
    assert isinstance(engine, AsyncEngine)
    # asyncpg driver가 박혔는지 확인
    assert "asyncpg" in str(engine.url)


@_skip_no_asyncpg
def test_make_async_engine_accepts_secretstr() -> None:
    """``KorTravelMapSettings.pg_dsn`` (SecretStr)를 그대로 받는다."""
    secret = SecretStr("postgresql://u:p@localhost:5432/test")
    engine = make_async_engine(secret)
    assert isinstance(engine, AsyncEngine)
    assert "asyncpg" in str(engine.url)


@_skip_no_asyncpg
def test_make_async_engine_respects_echo_flag() -> None:
    """``echo`` 옵션이 engine에 전달된다."""
    engine_off = make_async_engine("postgresql://u:p@h/d", echo=False)
    engine_on = make_async_engine("postgresql://u:p@h/d", echo=True)
    assert engine_off.echo is False
    assert engine_on.echo is True


# -- make_async_session_factory -------------------------------------------


@_skip_no_asyncpg
def test_session_factory_is_async_sessionmaker() -> None:
    """``async_sessionmaker`` 인스턴스를 반환한다."""
    engine = make_async_engine("postgresql://u:p@h/d")
    factory = make_async_session_factory(engine)
    assert isinstance(factory, async_sessionmaker)
