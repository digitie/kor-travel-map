"""T-READ-02 — 실제 PostgreSQL에서 요청별 문장 수·DB 시간·pool 대기를 본다.

- 느린 요청 로그의 ``db_statements``가 handler가 보낸 문장 수와 **같다** — 계측이 요청당 DB
  왕복을 더하지 않는다(pre-ping·BEGIN·ROLLBACK은 cursor 문장이 아니다).
- pool 크기 1에서 공개 key 인증 세션과 읽기 snapshot 세션이 차례로 동작한다 — 세션 의존성이
  연결을 미리 꺼내지 않고, 체크아웃을 재는 pool이 연결을 쥐고 있지 않다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.prometheus import PrometheusMetrics
from kortravelmap.api.request_timing import SLOW_REQUEST_LOGGER_NAME
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.db import make_async_engine

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def timed_engine(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    engine = make_async_engine(
        migrated_engine.url.render_as_string(hide_password=False),
        pool_size=1,
        max_overflow=0,
        server_settings={"jit": "off"},
        poolclass=api_db.TimedAsyncQueuePool,
    )
    api_db.set_engine_for_test(engine)
    try:
        yield engine
    finally:
        api_db.configure_prometheus_metrics(None)
        api_db.reset_engine()
        await engine.dispose()


async def test_slow_request_line_counts_exactly_the_handler_statements(
    timed_engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(
        ApiSettings(
            _env_file=None,
            features_routes_enabled=False,
            admin_routes_enabled=False,
            debug_routes_enabled=False,
            ops_routes_enabled=False,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            slow_request_log_ms=50,
        )
    )

    async def probe() -> dict[str, int]:
        async with AsyncSession(api_db._get_engine()) as session:
            await session.execute(text("SELECT pg_sleep(0.08)"))
            value = (await session.execute(text("SELECT 1"))).scalar_one()
        return {"value": int(value)}

    app.add_api_route("/v1/features/__timing_probe", probe, methods=["GET"])
    caplog.set_level(logging.WARNING, logger=SLOW_REQUEST_LOGGER_NAME)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://map.test"
    ) as client:
        response = await client.get("/v1/features/__timing_probe?lat=37.5665&lon=126.978")

    assert response.status_code == 200, response.text
    lines = [r.getMessage() for r in caplog.records if r.name == SLOW_REQUEST_LOGGER_NAME]
    assert len(lines) == 1, lines
    line = lines[0]
    assert "route=/v1/features/__timing_probe" in line
    assert "db_statements=2" in line
    assert "pool_waits=1" in line
    assert int(line.split("db_ms=")[1].split()[0]) >= 80
    assert "37.5665" not in line and "lat=" not in line
    assert timed_engine.sync_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


async def test_pool_of_one_serves_auth_then_snapshot_session_and_records_waits(
    timed_engine: AsyncEngine,
) -> None:
    metrics = PrometheusMetrics(service_name="test", version="0")
    api_db.configure_prometheus_metrics(metrics)
    metrics.bind_db_pool_status(api_db.pool_status)

    auth_sessions = api_db.get_public_api_key_session()
    auth = await anext(auth_sessions)
    assert (await auth.execute(text("SELECT 1"))).scalar_one() == 1
    await auth.close()
    await auth_sessions.aclose()

    read_sessions = api_db.get_read_snapshot_session()
    read = await anext(read_sessions)
    assert (await read.execute(text("SELECT 2"))).scalar_one() == 2
    assert api_db.pool_status() == (1, 0)  # pool 1개가 이 세션에 나가 있다
    await read_sessions.aclose()

    assert api_db.pool_status() == (0, 0)
    body = metrics.response().body.decode()
    count_line = next(
        line
        for line in body.splitlines()
        if line.startswith("kor_travel_map_db_pool_wait_seconds_count")
    )
    assert float(count_line.split()[-1]) >= 2.0
