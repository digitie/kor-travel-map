"""provider 적재가 다른 적재의 쓰기 단계 뒤에서 30초 넘게 기다린다(T-LOAD-LOCK-WAIT).

2026-10-22 n150에서 동시 적재 다섯이 ``feature-curation-write``를 30초(Dagster 엔진
``lock_timeout=30000``) 안에 못 얻고 55P03으로 실패했다. 이 모듈은 **Dagster 엔진과 같은
server_settings**로 실제 client 적재 경로(``load_enrichment_links`` — 빈 입력도 fence를 잡는다)를
돌린다.

- 무장한 적재는 holder가 30초 넘게 쥐어도 기다렸다가 성공한다.
- 같은 순간 대기를 끈(``0``) 적재는 종전처럼 30초에 55P03 — 전제(엔진 30초)가 이 환경에서
  실제로 성립함을 같은 실행에서 보인다.
- 같은 순간 API 단건 writer 모양(``lock_timeout`` 5초)은 여전히 몇 초 만에 55P03이다 —
  무장은 그 session에만 걸린다.
- 잡은 뒤에는 timeout이 되돌아와, 같은 transaction의 다른 잠금은 짧은 상한을 쓴다.

세션 공유 DB(``migrated_engine``)를 쓰지만 행을 쓰지 않는다(advisory lock만).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from kortravelcommon.pg_errors import pg_error_info
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.db import make_async_engine, make_async_session_factory
from kortravelmap.infra.feature_repo import (
    arm_feature_curation_write_wait,
    lock_feature_curation_write,
)
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_DAGSTER_SERVER_SETTINGS = {"statement_timeout": "600000", "lock_timeout": "30000"}
"""``kortravelmap.dagster.resources.kor_travel_map_client_resource``와 같은 값."""

_CURRENT_TIMEOUTS_SQL = (
    "SELECT current_setting('lock_timeout'), current_setting('statement_timeout'),"
    " current_setting('client_connection_check_interval')"
)

_HOLD_SECONDS = 40.0
"""holder가 fence를 쥐는 시간 — 엔진 lock_timeout(30초)보다 길다."""


def _sqlstate(error: BaseException) -> str | None:
    info = pg_error_info(error)
    return info.sqlstate if info is not None else None


@pytest.fixture
async def dagster_like_engines(
    dagster_runtime_engine: AsyncEngine,
) -> AsyncIterator[list[AsyncEngine]]:
    """Dagster runtime LOGIN + Dagster server_settings 엔진 셋(holder·무장·대조)."""
    dsn = dagster_runtime_engine.url.render_as_string(hide_password=False)
    engines = [
        make_async_engine(
            dsn, pool_size=1, max_overflow=0, server_settings=_DAGSTER_SERVER_SETTINGS
        )
        for _ in range(3)
    ]
    try:
        yield engines
    finally:
        for engine in engines:
            await engine.dispose()


def _client(engine: AsyncEngine, wait_seconds: int) -> AsyncKorTravelMapClient:
    settings = KorTravelMapSettings(feature_load_curation_lock_wait_seconds=wait_seconds)
    return AsyncKorTravelMapClient(engine, settings=settings)


async def test_a_load_waits_past_the_engine_lock_timeout_and_api_writers_do_not(
    dagster_like_engines: list[AsyncEngine],
    api_runtime_engine: AsyncEngine,
) -> None:
    holder_engine, armed_engine, control_engine = dagster_like_engines
    holding = asyncio.Event()

    async def _hold() -> None:
        async with make_async_session_factory(holder_engine)() as session, session.begin():
            await lock_feature_curation_write(session)
            holding.set()
            await asyncio.sleep(_HOLD_SECONDS)

    async def _timed(coro: object) -> tuple[float, BaseException | None]:
        began = time.monotonic()
        try:
            await coro  # type: ignore[misc]
        except DBAPIError as exc:
            return time.monotonic() - began, exc
        return time.monotonic() - began, None

    async def _api_single_writer() -> None:
        # API 단건 writer는 루틴 설정 ``lock_timeout=5s``(ADR-111)로 기다린다. 같은 상한을
        # 같은 fence에 건다 — 무장한 적재가 줄을 서 있어도 이 session은 5초에 끝나야 한다.
        async with make_async_session_factory(api_runtime_engine)() as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await lock_feature_curation_write(session)

    hold_task = asyncio.create_task(_hold())
    try:
        await asyncio.wait_for(holding.wait(), timeout=30)
        armed, control, api = await asyncio.gather(
            _timed(_client(armed_engine, 120).load_enrichment_links([])),
            _timed(_client(control_engine, 0).load_enrichment_links([])),
            _timed(_api_single_writer()),
        )
        await hold_task
    finally:
        # 어디서 실패하든 holder를 끝내야 세션 공유 DB에 fence가 남지 않는다.
        if not hold_task.done():
            hold_task.cancel()
        await asyncio.gather(hold_task, return_exceptions=True)

    armed_elapsed, armed_error = armed
    assert armed_error is None, f"무장한 적재가 실패했다: {armed_error!r}"
    assert armed_elapsed > 32.0, f"무장한 적재가 {armed_elapsed:.1f}초만 기다렸다"

    control_elapsed, control_error = control
    # 전제: 대기를 끈 적재는 엔진 30초에 55P03으로 끝난다(이 환경에서 실제로).
    assert control_error is not None
    assert _sqlstate(control_error) == "55P03"
    assert 25.0 < control_elapsed < 38.0

    api_elapsed, api_error = api
    assert api_error is not None
    assert _sqlstate(api_error) == "55P03"
    assert api_elapsed < 10.0, f"API 단건 writer가 {api_elapsed:.1f}초 기다렸다"


async def test_after_acquiring_the_short_timeouts_come_back(
    dagster_runtime_engine: AsyncEngine,
) -> None:
    """잡은 뒤 같은 transaction의 다른 잠금은 엔진 상한(여기 2초)으로 끝난다 — 15분이 아니다."""
    dsn = dagster_runtime_engine.url.render_as_string(hide_password=False)
    short = make_async_engine(
        dsn,
        pool_size=1,
        max_overflow=0,
        server_settings={"statement_timeout": "600000", "lock_timeout": "2000"},
    )
    other_key = "t-load-lock-wait-other"
    try:
        async with dagster_runtime_engine.connect() as holder:
            await holder.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": other_key}
            )
            await holder.commit()
            observed: list[tuple[object, ...]] = []
            began: list[float] = []

            async def _armed_then_other_lock() -> None:
                async with make_async_session_factory(short)() as session, session.begin():
                    arm_feature_curation_write_wait(session, 60_000)
                    await lock_feature_curation_write(session)
                    row = (await session.execute(text(_CURRENT_TIMEOUTS_SQL))).one()
                    observed.append(tuple(row))
                    began.append(time.monotonic())
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                        {"k": other_key},
                    )

            try:
                with pytest.raises(DBAPIError) as caught:
                    await _armed_then_other_lock()
                elapsed = time.monotonic() - began[0]
            finally:
                await holder.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": other_key}
                )
                await holder.commit()
    finally:
        await short.dispose()
    assert observed == [("2s", "10min", "0")]
    assert _sqlstate(caught.value) == "55P03"
    assert elapsed < 10.0
