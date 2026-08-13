"""``docker/postgres-role-bootstrap.sh``를 **데이터가 있는 DB**에 실제로 건다.

이 축이 통째로 비어 있었다. 저장소의 모든 bootstrap 경로는 fresh DB만 쓰는데,
이 스크립트가 존재하는 이유는 정반대다 — **기존 object의 소유권을 넘기는 것**이다.
fresh DB에서는 sweep 대상이 0개라 어떤 결함도 드러나지 않는다.

2026-08-13 prod 리허설(0087 + 실데이터)이 그 공백에서 P0 두 개를 꺼냈다:

1. identity/serial로 테이블에 묶인 시퀀스에 ``ALTER SEQUENCE ... OWNER TO``가 걸려
   ``ON_ERROR_STOP`` 으로 exit 3. 소유권이 **절반만** 이전된 채 남고 재실행해도 같은
   지점에서 다시 죽는다. compose가 api/dagster를 이 스크립트의
   ``service_completed_successfully``에 매달아 두었으므로 스택 전체가 서지 못한다.
2. ``public.alembic_version``이 구 superuser 소유로 남아, ADR-090 경로
   (migrator LOGIN → ``SET ROLE ktm_feature_schema_owner``)가 첫 ``SELECT version_num``
   에서 ``permission denied``. 즉 **단 한 revision도** 적용되지 못한다.

그래서 여기서는 "application relation과 identity 시퀀스와 ``alembic_version``이 이미
있는 DB"를 만들어 놓고 스크립트를 통째로 실행한다. 스크립트가 psql을 직접 부르므로
컨테이너의 host/port로 접속 가능한 DSN이 필요하다.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

if TYPE_CHECKING:
    from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "docker" / "postgres-role-bootstrap.sh"
_DATABASE = "ktm_bootstrap_existing"


def _sync_dsn(raw_dsn: str, database: str) -> str:
    """psql이 그대로 먹을 수 있는 libpq URL."""

    from sqlalchemy.engine import make_url

    url = make_url(raw_dsn).set(drivername="postgresql", database=database)
    return url.render_as_string(hide_password=False)


async def _seed_existing_objects(dsn: str) -> None:
    """소유권 이전 대상이 실제로 존재하는 DB를 만든다.

    identity 시퀀스를 **반드시** 포함해야 한다 — 그것이 P0-1의 실패 대상이다.
    """

    engine = make_async_engine(normalize_async_dsn(dsn), pool_size=1)
    try:
        async with engine.begin() as connection:
            for statement in (
                "CREATE SCHEMA IF NOT EXISTS feature",
                "CREATE SCHEMA IF NOT EXISTS provider_sync",
                "CREATE SCHEMA IF NOT EXISTS ops",
                # identity 컬럼이 만드는 시퀀스는 테이블에 묶여 소유자를 따로 못 바꾼다.
                "CREATE TABLE IF NOT EXISTS ops.legacy_queue ("
                "  queue_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
                "  payload text NOT NULL"
                ")",
                # serial도 같은 부류다(deptype 'a').
                "CREATE TABLE IF NOT EXISTS feature.legacy_rows ("
                "  row_id serial PRIMARY KEY,"
                "  name text NOT NULL"
                ")",
                "CREATE VIEW feature.legacy_view AS SELECT row_id FROM feature.legacy_rows",
                "INSERT INTO ops.legacy_queue (payload) VALUES ('seed')",
                "INSERT INTO feature.legacy_rows (name) VALUES ('seed')",
                # alembic이 이미 돌았던 DB를 흉내낸다 — 소유자는 bootstrap superuser.
                "CREATE TABLE IF NOT EXISTS public.alembic_version ("
                "  version_num varchar(32) NOT NULL PRIMARY KEY"
                ")",
                "INSERT INTO public.alembic_version (version_num) VALUES ('0087_probe')"
                " ON CONFLICT DO NOTHING",
            ):
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def _run_bootstrap(command: list[str]) -> subprocess.CompletedProcess[str]:
    """blocking 실행을 worker thread로 분리한다(ASYNC221)."""

    return subprocess.run(  # noqa: S603 - 저장소 스크립트를 그대로 실행하는 것이 목적이다
        command, check=False, capture_output=True, text=True
    )


async def _owner_of(dsn: str, qualified: str) -> str:
    engine = make_async_engine(normalize_async_dsn(dsn), pool_size=1)
    try:
        async with engine.connect() as connection:
            return str(
                (
                    await connection.execute(
                        text(
                            "SELECT pg_catalog.pg_get_userbyid(relowner) "
                            "FROM pg_catalog.pg_class WHERE oid = CAST(:name AS regclass)"
                        ),
                        {"name": qualified},
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_bootstrap_transfers_ownership_on_a_database_that_already_has_objects(
    pg_container: Any,
) -> None:
    raw_dsn = pg_container.get_connection_url()
    admin_engine = make_async_engine(normalize_async_dsn(raw_dsn), pool_size=1)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)')
            )
            await autocommit.execute(text(f'CREATE DATABASE "{_DATABASE}"'))
    finally:
        await admin_engine.dispose()

    target_dsn = _sync_dsn(raw_dsn, _DATABASE)
    await _seed_existing_objects(target_dsn)

    from sqlalchemy.engine import make_url

    bootstrap_user = make_url(raw_dsn).username
    assert bootstrap_user is not None

    # 스크립트는 ``psql``을 직접 부른다. 테스트 이미지에는 psql이 없으므로 **DB 컨테이너
    # 안에서** 실행한다 — 스크립트 본문은 그대로 쓰고 실행 환경만 옮기는 것이라
    # "저장소 스크립트를 그대로 검증한다"는 성질은 유지된다.
    container_id = pg_container.get_wrapped_container().id
    container_dsn = _sync_dsn(raw_dsn, _DATABASE).replace(
        f":{pg_container.get_exposed_port(5432)}/", ":5432/"
    ).replace(pg_container.get_container_host_ip(), "127.0.0.1")
    await asyncio.to_thread(
        subprocess.run,  # noqa: S603
        ["docker", "cp", str(_SCRIPT), f"{container_id}:/tmp/bootstrap.sh"],
        check=True,
        capture_output=True,
    )
    result = await asyncio.to_thread(
        _run_bootstrap,
        [
            "docker",
            "exec",
            *(
                arg
                for key, value in (
                    ("KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED", "true"),
                    ("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", container_dsn),
                    ("KOR_TRAVEL_MAP_MIGRATOR_PASSWORD", "bootstrap-probe-migrator"),
                    ("KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD", "bootstrap-probe-api"),
                    (
                        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD",
                        "bootstrap-probe-dagster",
                    ),
                    ("KOR_TRAVEL_MAP_POSTGRES_DB", _DATABASE),
                    ("KOR_TRAVEL_MAP_POSTGRES_USER", bootstrap_user),
                    (
                        "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE",
                        _DATABASE,
                    ),
                )
                for arg in ("-e", f"{key}={value}")
            ),
            container_id,
            "sh",
            "/tmp/bootstrap.sh",
        ],
    )
    assert result.returncode == 0, (
        f"bootstrap이 기존 object가 있는 DB에서 실패했다 (exit {result.returncode})\n"
        f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
    )

    # 소유권이 **끝까지** 넘어갔는지 본다. 절반만 넘어간 상태가 P0-1의 증상이었다.
    for qualified in (
        "ops.legacy_queue",
        "feature.legacy_rows",
        "feature.legacy_view",
        # P0-2 — 이것이 안 넘어가면 alembic이 첫 SELECT에서 죽는다.
        "public.alembic_version",
    ):
        assert (
            await _owner_of(target_dsn, qualified) == "ktm_feature_schema_owner"
        ), qualified
