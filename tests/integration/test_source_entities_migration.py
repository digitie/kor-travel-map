"""0044 source entity backfill, link folding, downgrade 통합 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_repo import _make_source_entity_key

pytestmark = pytest.mark.integration


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    cfg.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


async def test_source_entity_migration_backfills_and_guards_lossy_downgrade(
    pg_container: Any,
) -> None:
    raw_dsn = pg_container.get_connection_url()
    admin_dsn = normalize_async_dsn(raw_dsn)
    db_name = f"source_entity_migration_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=db_name).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)

    async with admin_engine.connect() as conn:
        autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{db_name}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, "0043_weather_history_idx")
        first = datetime(2026, 7, 13, 1, 0, tzinfo=UTC)
        second = first + timedelta(hours=1)
        later_seen = second + timedelta(hours=1)
        async with target_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category
                    ) VALUES (
                        'feature:migration-1', 'place', 'migration', '01070100'
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_records (
                        source_record_key, provider, dataset_key,
                        source_entity_type, source_entity_id,
                        raw_payload_hash, raw_data,
                        fetched_at, imported_at, last_seen_at
                    ) VALUES
                    (
                        'sr_old', 'python-mcst-api', 'migration-test',
                        'place', 'entity-1', 'hash-old', '{"edition":"2023"}',
                        :first, :first, :later_seen
                    ),
                    (
                        'sr_current', 'python-mcst-api', 'migration-test',
                        'place', 'entity-1', 'hash-current', '{"edition":"2025"}',
                        :second, :second, :second
                    )
                    """
                ),
                {"first": first, "second": second, "later_seen": later_seen},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_links (
                        feature_id, source_record_key, source_role,
                        match_method, confidence, is_primary_source, created_at
                    ) VALUES
                    (
                        'feature:migration-1', 'sr_old', 'primary',
                        'natural_key', 100, true, :first
                    ),
                    (
                        'feature:migration-1', 'sr_current', 'primary',
                        'natural_key', 100, true, :second
                    )
                    """
                ),
                {"first": first, "second": second},
            )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, "0044_source_entities")
        target_engine = make_async_engine(target_dsn)

        expected_entity_key = _make_source_entity_key(
            provider="python-mcst-api",
            dataset_key="migration-test",
            source_entity_type="place",
            source_entity_id="entity-1",
        )
        async with target_engine.connect() as conn:
            entity = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM provider_sync.source_entities "
                            "WHERE source_entity_key = :key"
                        ),
                        {"key": expected_entity_key},
                    )
                )
                .mappings()
                .one()
            )
            record_entity_keys = (
                (
                    await conn.execute(
                        text("SELECT DISTINCT source_entity_key FROM provider_sync.source_records")
                    )
                )
                .scalars()
                .all()
            )
            links = (
                await conn.execute(
                    text("SELECT feature_id, source_entity_key FROM provider_sync.source_links")
                )
            ).all()

        assert entity["current_source_record_key"] == "sr_old"
        assert entity["first_seen_at"] == first
        assert entity["last_seen_at"] == later_seen
        assert record_entity_keys == [expected_entity_key]
        assert links == [("feature:migration-1", expected_entity_key)]

        await target_engine.dispose()
        with pytest.raises(DBAPIError, match="0044 downgrade refused"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                "0043_weather_history_idx",
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as conn:
            revision = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == "0044_source_entities"
            await conn.execute(
                text(
                    "DELETE FROM provider_sync.source_records "
                    "WHERE source_record_key = 'sr_current'"
                )
            )

        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            "0043_weather_history_idx",
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as conn:
            entity_table = (
                await conn.execute(text("SELECT to_regclass('provider_sync.source_entities')"))
            ).scalar_one()
            record_link = (
                await conn.execute(
                    text(
                        "SELECT source_record_key "
                        "FROM provider_sync.source_links "
                        "WHERE feature_id = 'feature:migration-1'"
                    )
                )
            ).scalar_one()
            entity_column_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'provider_sync' "
                        "AND table_name = 'source_records' "
                        "AND column_name = 'source_entity_key'"
                    )
                )
            ).scalar_one()

        assert entity_table is None
        assert record_link == "sr_old"
        assert entity_column_count == 0
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as conn:
            autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()
