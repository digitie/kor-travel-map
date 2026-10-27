"""격리 기준선의 **판정**만 공용 ``pg_container`` 안의 전용 DB에서 빠르게 본다.

시간·CPU·RSS·WAL 측정(전용 PostGIS container, case마다 PG 재시작, 3회 반복)은 필수 CI가
아니다. 수치는 assert하지 않는 관측값이라 required lane에서 매번 container를 다시 띄울
이유가 없었다. 측정은 저장소 루트에서 수동으로 돈다::

    python -m scripts.scoped_write_baseline --run --output <새 파일>.json

여기서는 그 측정이 전제하던 불변식만 실제 PostgreSQL에서 확인한다. 이 모듈은 세션 공유
DB(``migrated_engine``)를 쓰지 않는다 — commit한 synthetic Feature·dataset이 뒤따르는 검사의
세계를 바꾼다(첫 시도에서 ``test_sibling_dedup``이 그 장소 14건을 읽었다). 같은 container 안에
이 모듈만의 DB를 만들어 head까지 올리고 끝나면 지운다(``test_feature_write_gate_lock_budget``과
같은 방식).

- 현재 global fence 아래 두 writer의 DML 구간이 겹치지 않는다(``dml_overlap == 0``).
- 같은 artifact replay(warm)는 effective 값과 alias 관계를 바꾸지 않는다(cold/warm hash 동일).
- Feature·current source head·alias 개수와 seal membership이 고정 fixture와 같다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from kortravelmap.infra.db import (
    assert_runtime_db_privilege_boundary,
    make_async_engine,
    normalize_async_dsn,
)
from scripts._scoped_write_baseline_pg import _prepare_runtime_acl, _seed, _state, _writer
from scripts.scoped_write_baseline import Fixture, interval_overlap, load_fixture
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]


@pytest.fixture
async def baseline_engines(
    pg_container: Any,
) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """(owner, runtime) — 이 모듈만의 head DB. 끝나면 DB째 지운다."""
    from alembic.config import Config

    raw_dsn = pg_container.get_connection_url()
    database = f"cwrite_baseline_{uuid4().hex}"
    server_dsn = (
        make_url(raw_dsn).set(drivername="postgresql", database="postgres").render_as_string(False)
    )
    with psycopg.connect(server_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
        )
    admin_dsn = normalize_async_dsn(
        make_url(raw_dsn).set(database=database).render_as_string(False)
    )
    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    engines: list[AsyncEngine] = []
    try:
        await upgrade_head_with_application_300_bootstrap(config, admin_dsn)
        runtime_dsn = (
            make_url(admin_dsn)
            .set(username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD)
            .render_as_string(hide_password=False)
        )
        await _prepare_runtime_acl(runtime_dsn)
        budgets = {"statement_timeout": "15000", "lock_timeout": "5000"}
        engines.append(make_async_engine(admin_dsn, pool_size=1, server_settings=budgets))
        # 두 writer가 동시에 붙는 실제 runtime LOGIN. 예산은 측정 runner와 같다.
        engines.append(
            make_async_engine(runtime_dsn, pool_size=2, max_overflow=0, server_settings=budgets)
        )
        yield engines[0], engines[1]
    finally:
        for engine in engines:
            await engine.dispose()
        with psycopg.connect(server_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )


async def _phase(
    owner: AsyncEngine, runtime: AsyncEngine, case: str, fixture: Fixture
) -> dict[str, Any]:
    async with asyncio.timeout(60), asyncio.TaskGroup() as group:
        barrier = asyncio.Barrier(2)
        tasks = [
            group.create_task(_writer(runtime, case, writer, fixture, barrier))
            for writer in ("left", "right")
        ]
    writers = [task.result() for task in tasks]
    return {
        "writers": writers,
        "dml_overlap_seconds": interval_overlap(
            [(writer["dml_started"], writer["dml_ended"]) for writer in writers]
        ),
        "state": await _state(owner, case, fixture),
    }


async def test_global_fence_serializes_writers_and_replay_keeps_effective_state(
    baseline_engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    owner, runtime = baseline_engines
    fixture = load_fixture()
    points = len(fixture.points)
    await assert_runtime_db_privilege_boundary(runtime, expected_login="ktm_feature_service")
    await _seed(owner, runtime, fixture)

    for case in ("independent", "shared"):
        cold = await _phase(owner, runtime, case, fixture)
        warm = await _phase(owner, runtime, case, fixture)

        assert cold["state"]["effective_sha256"] == warm["state"]["effective_sha256"]
        assert cold["state"]["alias_sha256"] == warm["state"]["alias_sha256"]
        expected_features = points * (2 if case == "independent" else 1)
        for phase in (cold, warm):
            assert phase["dml_overlap_seconds"] == 0
            assert phase["state"]["feature_count"] == expected_features
            assert phase["state"]["source_count"] == 2 * points
            assert phase["state"]["alias_count"] == 2 * points
            assert len({writer["backend_pid"] for writer in phase["writers"]}) == 2
            assert all(
                writer["session_login"] == writer["effective_login"] == "ktm_feature_service"
                for writer in phase["writers"]
            )
            assert all(writer["seal_member_count"] == points for writer in phase["writers"])
            assert all(writer["seal_sha256"] for writer in phase["writers"])
        assert all(
            writer["load"]["source_records_inserted"] == points for writer in cold["writers"]
        )
        assert all(writer["load"]["source_records_inserted"] == 0 for writer in warm["writers"])
        assert all(writer["load"]["features_updated"] == 0 for writer in warm["writers"])
