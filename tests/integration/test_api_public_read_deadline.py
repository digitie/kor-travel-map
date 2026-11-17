"""T-READ-03 — 공개 읽기 요청 마감(실제 PostgreSQL).

- 요청 마감은 **요청** 단위다: 문장 둘이 각각 예산 가까이 걸리면 두 번째가 남은 시간으로 잘려
  요청 전체가 예산 + 0.5초 안에 503 ``READ_TIMEOUT``이고, 그 연결은 pool로 돌아온다.
- pool을 다 쓴 상태의 공개 읽기는 대기 상한 + 0.5초 안에 503 ``POOL_BUSY``이고 체크아웃 수가
  원래대로 돌아온다(연결 누수 없음). 같은 상태의 ``get_session`` route는 종전처럼 기다린다.
- 긴 예산 의존성(축제 월별)은 짧은 예산을 넘는 질의도 통과시킨다.
- batch route의 57014는 ``FEATURE_BATCH_UNAVAILABLE``이 아니라 ``READ_TIMEOUT``이다.
- 마감이 없는 세션(Dagster·CLI·admin)은 ``statement_timeout``을 바꾸지 않는다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.public_read_budget import apply_public_read_budget

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def one_conn_engine(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
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
        api_db.reset_engine()
        await engine.dispose()


def _app(**overrides: Any) -> FastAPI:
    values: dict[str, Any] = {
        "_env_file": None,
        "features_routes_enabled": True,
        "admin_routes_enabled": False,
        "debug_routes_enabled": False,
        "ops_routes_enabled": False,
        "api_call_log_enabled": False,
        "prometheus_metrics_enabled": False,
        "public_api_key_required": False,
        "vworld_api_key": None,
        "service_token": None,
        "slow_request_log_ms": 0,
    }
    values.update(overrides)
    app = create_app(ApiSettings(**values))

    async def two_slow_statements(
        session: Annotated[AsyncSession, Depends(api_db.get_public_read_snapshot_session)],
    ) -> dict[str, str]:
        await session.execute(text("SELECT pg_sleep(0.6)"))
        await apply_public_read_budget(session)  # search_features가 본 질의 앞에서 하는 것
        await session.execute(text("SELECT pg_sleep(0.6)"))
        return {"ok": "yes"}

    async def public_plain(
        session: Annotated[AsyncSession, Depends(api_db.get_public_read_session)],
    ) -> dict[str, int]:
        return {"value": int((await session.execute(text("SELECT 1"))).scalar_one())}

    async def slow_budget_sleep(
        session: Annotated[
            AsyncSession, Depends(api_db.get_public_read_slow_snapshot_session)
        ],
    ) -> dict[str, str]:
        await session.execute(text("SELECT pg_sleep(1.0)"))
        return {"ok": "yes"}

    async def normal_budget_sleep(
        session: Annotated[AsyncSession, Depends(api_db.get_public_read_snapshot_session)],
    ) -> dict[str, str]:
        await session.execute(text("SELECT pg_sleep(1.0)"))
        return {"ok": "yes"}

    async def plain_session_timeout(
        session: Annotated[AsyncSession, Depends(api_db.get_session)],
    ) -> dict[str, str]:
        value = (await session.execute(text("SHOW statement_timeout"))).scalar_one()
        return {"statement_timeout": str(value)}

    for path, endpoint in (
        ("/v1/features/__t03/two-slow", two_slow_statements),
        ("/v1/features/__t03/plain", public_plain),
        ("/v1/features/__t03/slow-budget", slow_budget_sleep),
        ("/v1/features/__t03/normal-budget", normal_budget_sleep),
        ("/v1/features/__t03/legacy-session", plain_session_timeout),
    ):
        app.add_api_route(path, endpoint, methods=["GET"])
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://map.test")


def _checked_out(engine: AsyncEngine) -> int:
    return int(engine.sync_engine.pool.checkedout())  # type: ignore[attr-defined]


async def test_request_deadline_spans_statements_and_returns_connection(
    one_conn_engine: AsyncEngine,
) -> None:
    app = _app(public_read_budget_ms=1000)
    async with _client(app) as client:
        started = monotonic()
        response = await client.get("/v1/features/__t03/two-slow")
        elapsed = monotonic() - started
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "READ_TIMEOUT"
        assert elapsed < 1.0 + 0.5
        assert _checked_out(one_conn_engine) == 0
        follow_up = await client.get("/v1/features/__t03/plain")
    assert follow_up.status_code == 200
    assert follow_up.json() == {"value": 1}


async def test_pool_exhaustion_is_pool_busy_without_leaking_and_legacy_route_waits(
    one_conn_engine: AsyncEngine,
) -> None:
    app = _app(public_read_budget_ms=4500, public_read_pool_wait_ms=300)
    async with _client(app) as client:
        holder = await one_conn_engine.connect()
        try:
            started = monotonic()
            busy = await client.get("/v1/features/__t03/plain")
            elapsed = monotonic() - started
            assert busy.status_code == 503, busy.text
            assert busy.json()["code"] == "POOL_BUSY"
            assert elapsed < 0.3 + 0.5

            # get_session route는 종전처럼 pool_timeout(30초)까지 기다린다 — 연결을 돌려주면 통과.
            legacy = asyncio.create_task(client.get("/v1/features/__t03/legacy-session"))
            await asyncio.sleep(0.6)
            assert not legacy.done()
        finally:
            await holder.close()
        legacy_response = await legacy
        assert legacy_response.status_code == 200
        assert _checked_out(one_conn_engine) == 0
        after = await client.get("/v1/features/__t03/plain")
    assert after.status_code == 200
    assert _checked_out(one_conn_engine) == 0


async def test_slow_budget_dependency_allows_longer_query(one_conn_engine: AsyncEngine) -> None:
    app = _app(public_read_budget_ms=500, public_read_slow_budget_ms=3000)
    async with _client(app) as client:
        slow = await client.get("/v1/features/__t03/slow-budget")
        normal = await client.get("/v1/features/__t03/normal-budget")
    assert slow.status_code == 200, slow.text
    assert normal.status_code == 503
    assert normal.json()["code"] == "READ_TIMEOUT"


async def test_zero_budget_restores_previous_behaviour(one_conn_engine: AsyncEngine) -> None:
    app = _app(public_read_budget_ms=0)
    async with _client(app) as client:
        response = await client.get("/v1/features/__t03/normal-budget")
    assert response.status_code == 200, response.text


async def test_legacy_session_route_has_no_statement_timeout(
    one_conn_engine: AsyncEngine,
) -> None:
    async with one_conn_engine.connect() as connection:
        expected = (await connection.execute(text("SHOW statement_timeout"))).scalar_one()
    app = _app(public_read_budget_ms=1000)
    async with _client(app) as client:
        # 연결이 하나뿐이다 — 공개 읽기가 건 statement_timeout이 그 연결에 남지 않아야 한다.
        assert (await client.get("/v1/features/__t03/plain")).status_code == 200
        response = await client.get("/v1/features/__t03/legacy-session")
    assert response.status_code == 200
    assert response.json()["statement_timeout"] == str(expected)


async def test_public_search_route_runs_under_budget(one_conn_engine: AsyncEngine) -> None:
    # 검색의 SET LOCAL 둘이 set_config 한 문장(+ statement_timeout)으로 바뀐 경로가 실제로 돈다.
    app = _app(public_read_budget_ms=4500)
    async with _client(app) as client:
        response = await client.get("/v1/features/search", params={"q": "서울 맛집"})
    assert response.status_code == 200, response.text
    assert _checked_out(one_conn_engine) == 0


async def test_batch_statement_cancel_is_read_timeout(
    one_conn_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import features as features_router

    async def _resolve(_session: AsyncSession, _refs: object) -> dict[str, object]:
        return {}

    async def _slow_batch(session: AsyncSession, _items: object) -> list[object]:
        await session.execute(text("SELECT pg_sleep(2)"))
        return []

    monkeypatch.setattr(
        features_router.feature_identity, "resolve_feature_identities_bulk", _resolve
    )
    monkeypatch.setattr(
        features_router.feature_repo, "get_service_feature_batch_items", _slow_batch
    )
    app = _app(public_read_budget_ms=600)
    async with _client(app) as client:
        response = await client.post(
            "/v1/features/batch",
            json={"items": [{"feature_id": "00000000-0000-0000-0000-000000000001"}]},
        )
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "READ_TIMEOUT"


async def test_search_features_without_deadline_keeps_statement_timeout(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.infra import feature_repo

    before = (await migrated_session.execute(text("SHOW statement_timeout"))).scalar_one()
    assert await apply_public_read_budget(migrated_session) is None
    await feature_repo.search_features(
        migrated_session, q="서울 맛집", page_size=5, cursor_signing_key=b"k" * 32
    )
    after = (await migrated_session.execute(text("SHOW statement_timeout"))).scalar_one()
    assert after == before


async def test_batch_deadline_spans_resolve_and_items(
    one_conn_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """참조 해석이 쓴 시간이 본 질의 상한에서 빠진다 — 요청 전체가 예산 + 0.5초 안이다."""
    from kortravelmap.api.routers import features as features_router

    async def _slow_resolve(session: AsyncSession, _refs: object) -> dict[str, object]:
        await session.execute(text("SELECT pg_sleep(0.5)"))
        return {}

    async def _slow_batch(session: AsyncSession, _items: object) -> list[object]:
        await session.execute(text("SELECT pg_sleep(0.6)"))
        return []

    monkeypatch.setattr(
        features_router.feature_identity, "resolve_feature_identities_bulk", _slow_resolve
    )
    monkeypatch.setattr(
        features_router.feature_repo, "get_service_feature_batch_items", _slow_batch
    )
    app = _app(public_read_budget_ms=1000)
    async with _client(app) as client:
        started = monotonic()
        response = await client.post(
            "/v1/features/batch",
            json={"items": [{"feature_id": "00000000-0000-0000-0000-000000000001"}]},
        )
        elapsed = monotonic() - started
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "READ_TIMEOUT"
    assert elapsed < 1.0 + 0.5
