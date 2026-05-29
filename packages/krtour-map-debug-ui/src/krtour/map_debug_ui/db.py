"""``krtour.map_debug_ui.db`` — FastAPI DB 세션 의존성.

메인 라이브러리 ``KrtourMapSettings.pg_dsn``로 async engine을 만들어 라우터에
``AsyncSession``을 주입한다. ADR-004(쿼리는 raw SQL)/ADR-007(asyncpg) 준수 —
본 모듈은 engine/session 생성만, 쿼리는 ``krtour.map.infra.feature_repo``.

engine은 lazy singleton (모듈 레벨) — ADR-030의 in-memory **데이터** 캐시 금지와
무관 (engine은 connection pool 핸들이지 mutable 데이터 캐시가 아님). 테스트는
``set_engine_for_test``로 testcontainer engine을 주입한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from krtour.map.infra.db import make_async_engine
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

__all__ = ["get_session", "set_engine_for_test", "reset_engine"]


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    """모듈 레벨 async engine (lazy). DSN은 ``KRTOUR_MAP_PG_DSN``."""
    global _engine
    if _engine is None:
        settings = KrtourMapSettings()
        _engine = make_async_engine(settings.pg_dsn)
    return _engine


def set_engine_for_test(engine: AsyncEngine) -> None:
    """테스트가 testcontainer engine을 주입 (의존성 override 대신 단순화)."""
    global _engine
    _engine = engine


def reset_engine() -> None:
    """모듈 engine 참조 해제 (테스트 teardown)."""
    global _engine
    _engine = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성 — 요청 단위 ``AsyncSession`` (read-only 조회용).

    조회 라우터 전용이라 commit하지 않는다 (적재는 ``client.load_feature_bundles``).
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(_get_engine(), expire_on_commit=False) as session:
        yield session
