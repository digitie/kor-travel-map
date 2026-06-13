"""``kortravelmap.admin.db`` — FastAPI DB 세션 의존성.

메인 라이브러리 ``KorTravelMapSettings.pg_dsn``로 async engine을 만들어 라우터에
``AsyncSession``을 주입한다. ADR-004(쿼리는 raw SQL)/ADR-007(asyncpg) 준수 —
본 모듈은 engine/session 생성만, 쿼리는 ``kortravelmap.infra.feature_repo``.

engine은 lazy singleton (모듈 레벨) — ADR-030의 in-memory **데이터** 캐시 금지와
무관 (engine은 connection pool 핸들이지 mutable 데이터 캐시가 아님). 테스트는
``set_engine_for_test``로 testcontainer engine을 주입한다.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from kortravelmap.infra.db import make_async_engine
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy import event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from kortravelmap.admin.prometheus import PrometheusMetrics

__all__ = [
    "configure_prometheus_metrics",
    "get_session",
    "set_engine_for_test",
    "reset_engine",
]


_engine: AsyncEngine | None = None
_prometheus_metrics: PrometheusMetrics | None = None
_instrumented_sync_engine_ids: set[int] = set()


def _get_engine() -> AsyncEngine:
    """모듈 레벨 async engine (lazy). DSN은 ``KOR_TRAVEL_MAP_PG_DSN``."""
    global _engine
    if _engine is None:
        settings = KorTravelMapSettings()
        _engine = make_async_engine(settings.pg_dsn)
    _instrument_engine_if_needed(_engine)
    return _engine


def configure_prometheus_metrics(metrics: PrometheusMetrics | None) -> None:
    """Configure optional SQLAlchemy engine instrumentation."""
    global _prometheus_metrics
    _prometheus_metrics = metrics
    if _engine is not None:
        _instrument_engine_if_needed(_engine)


def set_engine_for_test(engine: AsyncEngine) -> None:
    """테스트가 testcontainer engine을 주입 (의존성 override 대신 단순화)."""
    global _engine
    _engine = engine
    _instrument_engine_if_needed(_engine)


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


def _instrument_engine_if_needed(engine: AsyncEngine) -> None:
    if _prometheus_metrics is None:
        return
    sync_engine = engine.sync_engine
    sync_engine_id = id(sync_engine)
    if sync_engine_id in _instrumented_sync_engine_ids:
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(sync_engine, "handle_error", _handle_error)
    _instrumented_sync_engine_ids.add(sync_engine_id)


def _before_cursor_execute(
    _conn: Any,
    _cursor: Any,
    _statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    context._kor_travel_map_started_at = perf_counter()


def _after_cursor_execute(
    _conn: Any,
    _cursor: Any,
    statement: str,
    _parameters: Any,
    context: Any,
    _executemany: bool,
) -> None:
    _record_query_metric(
        statement=statement,
        context=context,
        status="ok",
    )


def _handle_error(exception_context: Any) -> None:
    context = getattr(exception_context, "execution_context", None)
    statement = getattr(exception_context, "statement", "") or ""
    _record_query_metric(
        statement=statement,
        context=context,
        status="error",
    )


def _record_query_metric(*, statement: str, context: Any, status: str) -> None:
    metrics = _prometheus_metrics
    if metrics is None or context is None:
        return
    started_at = getattr(context, "_kor_travel_map_started_at", None)
    if not isinstance(started_at, float):
        return
    metrics.observe_db_query(
        statement=statement,
        duration_seconds=perf_counter() - started_at,
        status=status,
    )
