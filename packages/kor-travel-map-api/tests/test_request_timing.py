"""요청 도착 시각·요청별 DB 누산기·느린 요청 로그 (읽기 성능 계획 T-READ-02).

DB 없이 cursor 이벤트 hook을 직접 불러 누산을 확인한다. 실제 PostgreSQL 문장 수·pool 대기는
``tests/integration/test_api_request_timing.py``가 본다.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.request_timing import (
    SLOW_REQUEST_LOGGER_NAME,
    RequestDbTiming,
    format_slow_request_line,
)
from kortravelmap.api.settings import ApiSettings

pytestmark = pytest.mark.unit

_PROBE_ROUTE = "/v1/features/__timing_probe/{item}"


def _app(*, slow_ms: int, metrics: bool = False) -> FastAPI:
    app = create_app(
        ApiSettings(
            features_routes_enabled=False,
            prometheus_metrics_enabled=metrics,
            slow_request_log_ms=slow_ms,
        )
    )

    async def probe(item: str, request: Request) -> dict[str, object]:
        # 문장 두 개를 흉내 낸다 — 실제 engine이 부르는 것과 같은 hook이다.
        for _ in range(2):
            context = SimpleNamespace()
            api_db._before_cursor_execute(None, None, "SELECT 1", None, context, False)
            await asyncio.sleep(0.005)
            api_db._after_cursor_execute(None, None, "SELECT 1", None, context, False)
        await asyncio.sleep(0.02)
        return {"started": request.state.started_monotonic, "item": item}

    app.add_api_route(_PROBE_ROUTE, probe, methods=["GET"])
    return app


def _slow_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == SLOW_REQUEST_LOGGER_NAME
    ]


def test_middleware_records_request_arrival_monotonic() -> None:
    client = TestClient(_app(slow_ms=0))
    before = monotonic()

    response = client.get("/v1/features/__timing_probe/a")

    assert response.status_code == 200
    started = response.json()["started"]
    assert isinstance(started, float)
    assert before <= started <= monotonic()


def test_slow_request_line_without_metrics_has_route_template_and_db_totals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(slow_ms=10, metrics=False))
    caplog.set_level(logging.WARNING, logger=SLOW_REQUEST_LOGGER_NAME)

    response = client.get(
        "/v1/features/__timing_probe/secret-item?lat=37.5665&lon=126.978&key=abc",
        headers={"X-Request-ID": "probe-req-1", "X-API-Key": "should-not-appear"},
    )

    assert response.status_code == 200
    lines = _slow_lines(caplog)
    assert len(lines) == 1, lines
    line = lines[0]
    assert line.startswith("slow_request ")
    assert f"route={_PROBE_ROUTE}" in line
    assert "method=GET" in line
    assert "status=200" in line
    assert "db_statements=2" in line
    assert "request_id=probe-req-1" in line
    duration_ms = int(line.split("duration_ms=")[1].split()[0])
    db_ms = int(line.split("db_ms=")[1].split()[0])
    assert duration_ms >= 10
    assert 0 < db_ms <= duration_ms
    for leaked in ("37.5665", "126.978", "lat=", "key=abc", "secret-item", "should-not-appear"):
        assert leaked not in line


def test_fast_request_and_zero_threshold_do_not_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=SLOW_REQUEST_LOGGER_NAME)

    assert TestClient(_app(slow_ms=60_000)).get("/v1/features/__timing_probe/a").status_code == 200
    assert TestClient(_app(slow_ms=0)).get("/v1/features/__timing_probe/a").status_code == 200

    assert _slow_lines(caplog) == []


def test_db_events_outside_a_request_are_not_accumulated() -> None:
    # 요청 밖(Dagster·lifespan)의 문장은 누산기가 없으므로 아무 데도 더하지 않는다.
    from kortravelmap.api.request_timing import current_request_db_timing

    assert current_request_db_timing() is None
    context = SimpleNamespace()
    api_db._before_cursor_execute(None, None, "SELECT 1", None, context, False)
    api_db._after_cursor_execute(None, None, "SELECT 1", None, context, False)
    assert not getattr(context, "_kor_travel_map_counted", False)


def test_error_and_success_hooks_count_one_execution_once() -> None:
    from kortravelmap.api.request_timing import (
        bind_request_db_timing,
        reset_request_db_timing,
    )

    timing = RequestDbTiming()
    token = bind_request_db_timing(timing)
    try:
        context = SimpleNamespace()
        api_db._before_cursor_execute(None, None, "SELECT 1", None, context, False)
        api_db._after_cursor_execute(None, None, "SELECT 1", None, context, False)
        api_db._handle_error(SimpleNamespace(execution_context=context, statement="SELECT 1"))
    finally:
        reset_request_db_timing(token)

    assert timing.statements == 1


def test_slow_line_drops_unsafe_request_id() -> None:
    line = format_slow_request_line(
        method="GET",
        route="/v1/features/in-bounds",
        status_code=503,
        duration_seconds=1.5,
        timing=RequestDbTiming(statements=3, db_seconds=1.2),
        request_id="evil status=200 injected",
    )

    assert "request_id=-" in line
    assert "injected" not in line
    assert line.count("status=") == 1
    assert "duration_ms=1500" in line
    assert "db_ms=1200" in line


def test_metrics_expose_pool_wait_histogram_and_checkout_gauges() -> None:
    client = TestClient(_app(slow_ms=0, metrics=True))

    body = client.get("/metrics").text

    assert "kor_travel_map_db_pool_wait_seconds_bucket" in body
    assert "kor_travel_map_db_pool_checked_out " in body
    assert "kor_travel_map_db_pool_overflow " in body
