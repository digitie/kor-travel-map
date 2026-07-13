"""0047 notice reconcile planner 통계 migration 검증."""

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


def _run_alembic(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


async def test_notice_reconcile_statistics_refresh_populated_feature_table(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"notice_reconcile_stats_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    expected_tables = {
        ("feature", "features"),
        ("provider_sync", "source_entities"),
        ("provider_sync", "source_records"),
        ("provider_sync", "source_links"),
        ("provider_sync", "notice_lifecycle_scopes"),
        ("provider_sync", "notice_lineage_states"),
    }
    feature_count = 256
    try:
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            "0046_notice_snapshot_state",
        )
        async with target_engine.begin() as connection:
            # 전용 DB와 autovacuum 비활성화로 다른 테스트나 background analyze가
            # 0047 누락을 가리는 거짓 양성을 막는다.
            await connection.execute(
                text(
                    "ALTER TABLE feature.features "
                    "SET (autovacuum_enabled = false)"
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category
                    )
                    SELECT
                        'feature:notice-stats:' || value,
                        'notice',
                        '통계 회귀 ' || value,
                        '03010000'
                    FROM generate_series(1, :feature_count) AS value
                    """
                ),
                {"feature_count": feature_count},
            )

        async with target_engine.connect() as connection:
            before = (
                await connection.execute(
                    text(
                        """
                        SELECT relation.reltuples::bigint, stats.last_analyze
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        LEFT JOIN pg_stat_user_tables AS stats
                          ON stats.relid = relation.oid
                        WHERE namespace.nspname = 'feature'
                          AND relation.relname = 'features'
                        """
                    )
                )
            ).one()
        assert before.last_analyze is None
        assert before.reltuples < feature_count

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            "0047_notice_reconcile_stats",
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            stats.schemaname,
                            stats.relname,
                            stats.last_analyze,
                            relation.reltuples::bigint AS reltuples
                        FROM pg_stat_user_tables AS stats
                        JOIN pg_class AS relation ON relation.oid = stats.relid
                        WHERE (
                            stats.schemaname = 'feature'
                            AND stats.relname = 'features'
                        ) OR (
                            stats.schemaname = 'provider_sync'
                            AND stats.relname IN (
                                'source_entities',
                                'source_records',
                                'source_links',
                                'notice_lifecycle_scopes',
                                'notice_lineage_states'
                            )
                        )
                        """
                    )
                )
            ).all()

        assert {(row.schemaname, row.relname) for row in rows} == expected_tables
        assert all(row.last_analyze is not None for row in rows)
        feature_row = next(row for row in rows if row.relname == "features")
        assert feature_row.reltuples == feature_count
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
