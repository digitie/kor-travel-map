"""0071 immutable integrity observation generation migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0070_domain_command_ledger"
_TARGET_REVISION = "0071_integrity_observations"
_TABLES = {
    "integrity_observation_scopes",
    "integrity_observation_runs",
    "integrity_finding_observations",
}


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — `alembic/legacy_versions/README.md`. `versions/`와 함께 담으면 revision이 중복된다.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def test_integrity_observation_generation_upgrade_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"integrity_observation_{uuid4().hex}"
    target_dsn = (
        make_url(admin_dsn)
        .set(database=database)
        .render_as_string(hide_password=False)
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'ops' "
                            "AND table_name = ANY(CAST(:tables AS text[]))"
                        ),
                        {"tables": sorted(_TABLES)},
                    )
                ).scalars()
            )
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.integrity_observation_scopes (
                        provider, dataset_key, latest_generation
                    ) VALUES ('provider', 'dataset', 1)
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.integrity_observation_runs (
                        provider, dataset_key, generation, external_run_id
                    ) VALUES ('provider', 'dataset', 1, 'run-1')
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.integrity_finding_observations (
                        observation_run_id, dedupe_key
                    )
                    SELECT observation_run_id, 'av2_' || repeat('a', 64)
                    FROM ops.integrity_observation_runs
                    WHERE external_run_id = 'run-1'
                    """
                )
            )
        assert tables == _TABLES
        assert revision == _TARGET_REVISION

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            remaining = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'ops' "
                            "AND table_name = ANY(CAST(:tables AS text[]))"
                        ),
                        {"tables": sorted(_TABLES)},
                    )
                ).scalars()
            )
        assert remaining == set()
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
