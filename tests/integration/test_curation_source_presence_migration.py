"""0065 curation source presence schema migration 회귀."""

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

_PRE_REVISION = "0064_price_series_identity"
_TARGET_REVISION = "0065_curation_source_presence"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _schema_state(engine: Any) -> tuple[tuple[Any, ...] | None, dict[str, str]]:
    async with engine.connect() as connection:
        column = (
            await connection.execute(
                text(
                    "SELECT is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'feature' "
                    "AND table_name = 'curation_items' "
                    "AND column_name = 'source_present'"
                )
            )
        ).one_or_none()
        indexes = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'feature' "
                "AND tablename = 'curation_items'"
            )
        )
    return column, {str(name): str(definition) for name, definition in indexes}


async def _seed_pre_0065_identity_conflicts(engine: Any) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'feature:migration-presence', 'place', 'migration fixture',
                    '01070100', '{}'::jsonb, 'active'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group
                    ) VALUES (
                        'migration-presence', 'migration presence', 'test'
                    )
                    RETURNING theme_id
                ), collection AS (
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title
                    )
                    SELECT
                        'migration-presence:2026', theme_id,
                        'migration presence'
                    FROM theme
                    RETURNING collection_id
                )
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, external_item_id, place_name,
                    status, archived_at, updated_at
                )
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved tombstone old',
                    'archived', now() - interval '2 hours',
                    now() - interval '2 hours'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved tombstone newest',
                    'archived', now() - interval '1 hour',
                    now() - interval '1 hour'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved resurrected',
                    'included', NULL, now()
                FROM collection
                UNION ALL
                SELECT
                    collection_id, NULL,
                    'unresolved-conflict', 'unresolved tombstone',
                    'archived', now() - interval '1 hour',
                    now() - interval '1 hour'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, NULL,
                    'unresolved-conflict', 'unresolved resurrected',
                    'included', NULL, now()
                FROM collection
                """
            )
        )


async def test_source_presence_upgrade_downgrade_forward_recovery(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_source_presence_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        before_column, before_indexes = await _schema_state(target_engine)
        assert before_column is None
        assert "source_present" not in (
            before_indexes["idx_curation_items_collection_status_order"]
        )
        await _seed_pre_0065_identity_conflicts(target_engine)

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        upgraded_column, upgraded_indexes = await _schema_state(target_engine)
        assert upgraded_column == ("NO", "true")
        assert "collection_id, source_present, status, sort_order" in (
            upgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "feature_id, source_present, status, collection_id" in (
            upgraded_indexes["idx_curation_items_feature_status_collection"]
        )
        assert "uq_curation_items_active_identity" not in upgraded_indexes
        assert "UNIQUE" in upgraded_indexes["uq_curation_items_identity"]
        assert "NULLS NOT DISTINCT" in upgraded_indexes["uq_curation_items_identity"]
        assert " WHERE " not in upgraded_indexes["uq_curation_items_identity"]
        async with target_engine.begin() as connection:
            normalized = (
                await connection.execute(
                    text(
                        "SELECT external_item_id, count(*) AS total, "
                        "count(*) FILTER (WHERE archived_at IS NULL) AS active, "
                        "max(place_name) FILTER (WHERE archived_at IS NOT NULL) AS kept "
                        "FROM feature.curation_items "
                        "WHERE external_item_id IN "
                        "('resolved-conflict','unresolved-conflict') "
                        "GROUP BY external_item_id ORDER BY external_item_id"
                    )
                )
            ).all()
            assert normalized == [
                ("resolved-conflict", 1, 0, "resolved tombstone newest"),
                ("unresolved-conflict", 1, 0, "unresolved tombstone"),
            ]
            await connection.execute(
                text(
                    "INSERT INTO feature.curation_items ("
                    "collection_id, feature_id, external_item_id, place_name, "
                    "source_present, status"
                    ") SELECT collection_id, NULL, 'source-absent', "
                    "'source absent', false, 'included' "
                    "FROM feature.curation_collections "
                    "WHERE collection_key = 'migration-presence:2026'"
                )
            )

        await target_engine.dispose()
        with pytest.raises(Exception, match="source-absent curation items exist"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert (
                await connection.execute(
                    text(
                        "SELECT version_num FROM alembic_version "
                        "WHERE version_num = :version"
                    ),
                    {"version": _TARGET_REVISION},
                )
            ).scalar_one() == _TARGET_REVISION
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_items "
                    "WHERE external_item_id = 'source-absent'"
                )
            )
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        downgraded_column, downgraded_indexes = await _schema_state(target_engine)
        assert downgraded_column is None
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_feature_status_collection"]
        )
        assert "uq_curation_items_identity" not in downgraded_indexes
        assert " WHERE (archived_at IS NULL)" in (
            downgraded_indexes["uq_curation_items_active_identity"]
        )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        recovered_column, recovered_indexes = await _schema_state(target_engine)
        assert recovered_column == ("NO", "true")
        assert "source_present" in (
            recovered_indexes["idx_curation_items_collection_status_order"]
        )
        assert "uq_curation_items_identity" in recovered_indexes
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
