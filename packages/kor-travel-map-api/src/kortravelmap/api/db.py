"""``kortravelmap.api.db`` — FastAPI DB 세션 의존성.

메인 라이브러리 ``KorTravelMapSettings.pg_dsn``로 async engine을 만들어 라우터에
``AsyncSession``을 주입한다. ADR-004(쿼리는 raw SQL)/ADR-007(asyncpg) 준수 —
본 모듈은 engine/session 생성만, 쿼리는 ``kortravelmap.infra.feature_repo``.

engine은 lazy singleton (모듈 레벨) — ADR-030의 in-memory **데이터** 캐시 금지와
무관 (engine은 connection pool 핸들이지 mutable 데이터 캐시가 아님). 테스트는
``set_engine_for_test``로 testcontainer engine을 주입한다.

관측(T-READ-02). cursor 이벤트는 지표 flag와 무관하게 engine에 걸린다 — 요청마다 문장 수·DB
시간을 ``request_timing``의 누산기에 더해 느린 요청 로그가 쓰게 한다. pool은 체크아웃 대기를
재는 ``TimedAsyncQueuePool``이다(크기·overflow·timeout 의미는 기본 pool과 같다). 세션 의존성은
지금처럼 첫 문장에서야 연결을 꺼낸다 — 이 모듈은 연결을 미리 꺼내지 않는다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.public_read_budget import (
    PUBLIC_READ_DEADLINE_INFO_KEY,
    ReadBudgetExceeded,
    public_read_statement_timeout_ms,
)
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.util import queue as sqla_queue
from sqlalchemy.util import safe_reraise

from kortravelmap.api.request_timing import current_request_db_timing

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.orm import Session, SessionTransaction
    from sqlalchemy.pool import ConnectionPoolEntry

    from kortravelmap.api.prometheus import PrometheusMetrics

__all__ = [
    "configure_prometheus_metrics",
    "get_engine",
    "get_session",
    "get_read_snapshot_session",
    "get_locking_read_snapshot_session",
    "get_public_api_key_session",
    "set_engine_for_test",
    "reset_engine",
    "TimedAsyncQueuePool",
    "pool_status",
    "PoolBusy",
    "PUBLIC_READ_BUDGET_STATE",
    "get_public_read_session",
    "get_public_read_snapshot_session",
    "get_public_read_slow_snapshot_session",
]

PUBLIC_READ_BUDGET_STATE = "public_read_budget_ms"
"""``request.state``의 표시.

공개 읽기 예산 아래의 요청만 57014를 503 ``READ_TIMEOUT``으로 바꾼다.
"""


class PoolBusy(Exception):
    """공개 읽기가 pool 대기 상한 안에 연결을 얻지 못했다(503 ``POOL_BUSY``)."""


#: 공개 읽기 요청의 pool 체크아웃 상한(초)과 넘었을 때 올릴 예외. 공개 읽기 의존성이 걸고
#: ``TimedAsyncQueuePool``이 읽는다. 다른 요청·Dagster·admin에는 ``None``이다.
_CHECKOUT_LIMIT: ContextVar[tuple[float, type[Exception]] | None] = ContextVar(
    "kor_travel_map_public_checkout_limit", default=None
)

_engine: AsyncEngine | None = None
_prometheus_metrics: PrometheusMetrics | None = None


class TimedAsyncQueuePool(AsyncAdaptedQueuePool):
    """체크아웃 대기 시간을 재는 ``AsyncAdaptedQueuePool``.

    ``_do_get``(빈 연결을 기다리거나 새로 여는 구간)만 감싼다. 동작은 부모와 같다 — 대기·
    timeout·overflow 판정을 바꾸지 않고 시간만 잰다. 실패(``pool_timeout`` 초과)도 잰다.
    """

    def _do_get(self) -> ConnectionPoolEntry:
        started_at = perf_counter()
        try:
            limit = _CHECKOUT_LIMIT.get()
            if limit is None:
                return super()._do_get()
            seconds, error = limit
            return self._do_get_within(min(seconds, self._timeout), error)
        finally:
            _record_pool_wait(perf_counter() - started_at)

    def _do_get_within(self, timeout: float, error: type[Exception]) -> ConnectionPoolEntry:
        """``QueuePool._do_get``(SQLAlchemy 2.0.54)과 같은 판정을 짧은 대기 상한으로(T-READ-03).

        대기만 짧다 — overflow·연결 생성 판정은 부모와 같다. 상한을 넘으면 ``error``(``PoolBusy``
        또는 ``ReadBudgetExceeded``)를 올린다. 요청을 취소하지 않으므로 연결이 새지 않는다.
        """
        use_overflow = self._max_overflow > -1
        wait = use_overflow and self._overflow >= self._max_overflow
        try:
            return self._pool.get(wait, timeout)
        except sqla_queue.Empty:
            pass
        if use_overflow and self._overflow >= self._max_overflow:
            if not wait:
                return self._do_get_within(timeout, error)
            raise error
        if self._inc_overflow():
            try:
                return self._create_connection()
            except:  # noqa: E722 — 부모와 같이 어떤 실패든 overflow를 되돌리고 다시 던진다
                with safe_reraise():
                    self._dec_overflow()
                raise
        return self._do_get_within(timeout, error)


def pool_status() -> tuple[int, int] | None:
    """(사용 중 연결 수, 현재 overflow) — engine이 아직 없거나 queue pool이 아니면 ``None``.

    scrape 때 읽는다. 연결을 꺼내지 않는다.
    """
    engine = _engine
    if engine is None:
        return None
    pool = engine.sync_engine.pool
    checkedout = getattr(pool, "checkedout", None)
    overflow = getattr(pool, "overflow", None)
    if not callable(checkedout) or not callable(overflow):
        return None
    return int(checkedout()), int(overflow())


def _get_engine() -> AsyncEngine:
    """모듈 레벨 async engine (lazy). DSN은 ``KOR_TRAVEL_MAP_PG_DSN``."""
    global _engine
    if _engine is None:
        settings = KorTravelMapSettings()
        if settings.pg_dsn is None:
            raise RuntimeError(
                "KOR_TRAVEL_MAP_PG_DSN runtime DSN is required; no application DSN fallback exists"
            )
        # bbox 지도 조회는 결과 50건을 찾는 실행은 수십 ms이지만, notice
        # 계보·weather 상관 subplan의 높은 추정 cost가 JIT를 켜 요청당
        # 수 초의 컴파일을 발생시켰다. 짧은 OLTP 요청만 수행하는 API
        # 연결에서 끄고, 장기 배치인 Dagster/CLI 연결은 기본값을 유지한다.
        _engine = make_async_engine(
            settings.pg_dsn,
            server_settings={"jit": "off"},
            poolclass=TimedAsyncQueuePool,
        )
    _instrument_engine_if_needed(_engine)
    return _engine


async def get_engine() -> AsyncEngine:
    """장기 phase를 직접 소유하는 application service용 async engine dependency."""

    return _get_engine()


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
    """FastAPI 의존성 — 일반 요청 세션. 쓰기/복합 phase의 transaction도 받는다.

    이 의존성 자체는 commit하지 않는다. handler가 쓰기 transaction을 소유하며,
    단일 image가 필요한 순수 조회는 ``get_read_snapshot_session``을 쓴다.
    """
    async with AsyncSession(_get_engine(), expire_on_commit=False) as session:
        yield session


async def get_public_api_key_session() -> AsyncIterator[AsyncSession]:
    """공개 key 인증 전용 세션. handler/쓰기 세션과 dependency cache를 공유하지 않는다.

    ``require_public_api_key``가 조회 직후 context를 닫아 snapshot reader가 같은
    pool의 유일한 connection도 이어 쓸 수 있게 한다. 의존성 종료의 close는 멱등이다.
    """
    async with AsyncSession(_get_engine(), expire_on_commit=False) as session:
        yield session


async def get_read_snapshot_session() -> AsyncIterator[AsyncSession]:
    """순수 조회 응답 전체를 최초 SELECT 전 read-only REPEATABLE READ로 묶는다.

    auth/쓰기용 ``get_session``과 세션을 공유하지 않는다. 이미 autobegin된
    transaction의 isolation을 바꾸지 않으며, 성공/예외 모두 context 종료 시
    connection을 pool에 반환한다. 여러 HTTP page 사이의 snapshot은 약속하지 않는다.
    """
    engine = _get_engine().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    )
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        yield session


async def get_locking_read_snapshot_session() -> AsyncIterator[AsyncSession]:
    """FOR SHARE가 필요한 조회 전용 phase. 기존 read-write 권한 안에서 RR만 보장한다.

    PostgreSQL은 READ ONLY transaction에서 행 잠금을 금지한다. 순수 SELECT reader는
    기존 ``get_read_snapshot_session``을 유지하며, 이 dependency는 행 잠금 guard를
    제거하거나 mutation에 쓰기 권한을 새로 주기 위한 경로가 아니다.
    """
    engine = _get_engine().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=False
    )
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        yield session


# ── 공개 읽기 요청 마감 (T-READ-03) ─────────────────────────────────────────
#
# 새 의존성은 기존 의존성을 **감싼다** — 격리 수준·세션 수명은 ``get_session``·
# ``get_read_snapshot_session``이 지금처럼 정하고, 여기서는 (1) 첫 연결 획득을 pool 대기 상한
# 안에서 하고 (2) 요청 도착에서 센 마감을 ``session.info``에 싣고 (3) 남은 시간을 그
# transaction의 ``statement_timeout``으로 건다. 엔진의 ``pool_timeout``은 바꾸지 않는다(엔진이
# 하나라 admin·ops·쓰기까지 걸린다). 예산이 0이면 감싸기만 하고 아무것도 하지 않는다.


async def get_public_read_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[AsyncSession]:
    """공개 읽기 — ``get_session``과 같은 격리에 요청 마감(기본 4.5초)을 건다."""
    async with _public_read_budget(request, session, slow=False):
        yield session


async def get_public_read_snapshot_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_read_snapshot_session)],
) -> AsyncIterator[AsyncSession]:
    """공개 읽기 — ``get_read_snapshot_session``과 같은 격리에 요청 마감(기본 4.5초)을 건다."""
    async with _public_read_budget(request, session, slow=False):
        yield session


async def get_public_read_slow_snapshot_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_read_snapshot_session)],
) -> AsyncIterator[AsyncSession]:
    """``GET /v1/public/festivals/monthly`` 전용 — PinVi가 이 route만 15초 기다린다(기본 14초)."""
    async with _public_read_budget(request, session, slow=True):
        yield session


@asynccontextmanager
async def _public_read_budget(
    request: Request, session: AsyncSession, *, slow: bool
) -> AsyncIterator[None]:
    """마감을 세션에 싣고, 연결·문장 상한은 **첫 문장 때** 건다.

    의존성 안에서는 DB에 닿지 않는다 — 검증 오류(422)로 끝나는 요청은 연결을 꺼내지 않는다.
    """
    settings = getattr(request.app.state, "settings", None)
    budget_ms = 0
    pool_wait_ms = 0
    if settings is not None:
        budget_ms = settings.public_read_slow_budget_ms if slow else settings.public_read_budget_ms
        pool_wait_ms = settings.public_read_pool_wait_ms
    # 시험 대역(가짜 세션)에는 걸 곳이 없다 — 진짜 AsyncSession에만 건다.
    if budget_ms <= 0 or not isinstance(session, AsyncSession):
        yield
        return
    started = getattr(request.state, "started_monotonic", None)
    if not isinstance(started, float):
        started = monotonic()
    deadline = started + budget_ms / 1000.0
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ReadBudgetExceeded
    setattr(request.state, PUBLIC_READ_BUDGET_STATE, budget_ms)
    session.info[PUBLIC_READ_DEADLINE_INFO_KEY] = deadline
    pool_wait = pool_wait_ms / 1000.0 if 0 < pool_wait_ms / 1000.0 < remaining else None
    limit: tuple[float, type[Exception]] = (
        (pool_wait, PoolBusy) if pool_wait is not None else (remaining, ReadBudgetExceeded)
    )
    token = _CHECKOUT_LIMIT.set(limit)
    event.listen(session.sync_session, "after_begin", _apply_budget_on_begin)
    try:
        yield
    finally:
        event.remove(session.sync_session, "after_begin", _apply_budget_on_begin)
        session.info.pop(PUBLIC_READ_DEADLINE_INFO_KEY, None)
        try:
            _CHECKOUT_LIMIT.reset(token)
        except ValueError:  # 의존성 정리가 다른 context에서 돌면 되돌릴 token이 없다
            _CHECKOUT_LIMIT.set(None)


def _apply_budget_on_begin(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    """transaction이 연결을 얻은 직후 남은 시간을 ``statement_timeout``으로 건다(왕복 1)."""
    timeout_ms = public_read_statement_timeout_ms(session)  # type: ignore[arg-type]
    if timeout_ms is None:
        return
    connection.execute(
        text("SELECT set_config('statement_timeout', :timeout, true)"),
        {"timeout": f"{timeout_ms}ms"},
    )


def _instrument_engine_if_needed(engine: AsyncEngine) -> None:
    # 지표 flag와 무관하게 건다 — 느린 요청 로그의 문장 수·DB 시간이 이 이벤트에서 온다.
    # 지표가 꺼져 있으면 ``_record_query_metric``이 요청 누산기에만 더한다.
    sync_engine = engine.sync_engine
    # id() 집합은 해제된 engine의 id를 새 engine이 물려받으면 건너뛴다 — engine 자신에게 묻는다.
    if event.contains(sync_engine, "before_cursor_execute", _before_cursor_execute):
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(sync_engine, "handle_error", _handle_error)


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
    if context is None:
        return
    started_at = getattr(context, "_kor_travel_map_started_at", None)
    if not isinstance(started_at, float):
        return
    duration_seconds = perf_counter() - started_at
    # 요청 누산기는 한 실행을 한 번만 센다(실행 뒤 fetch 오류가 handle_error로 다시 올 수 있다).
    # 지표는 종전처럼 두 이벤트를 다 기록한다.
    timing = current_request_db_timing()
    if timing is not None and not getattr(context, "_kor_travel_map_counted", False):
        context._kor_travel_map_counted = True
        timing.add_statement(duration_seconds)
    metrics = _prometheus_metrics
    if metrics is None:
        return
    metrics.observe_db_query(
        statement=statement,
        duration_seconds=duration_seconds,
        status=status,
    )


def _record_pool_wait(duration_seconds: float) -> None:
    timing = current_request_db_timing()
    if timing is not None:
        timing.add_pool_wait(duration_seconds)
    metrics = _prometheus_metrics
    if metrics is not None:
        metrics.observe_db_pool_wait(duration_seconds)
