"""0066 curation component identity schema migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0065_curation_source_presence"
_TARGET_REVISION = "0066_curation_component_identity"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _seed_pre_0066(engine: Any) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES
                    ('feature:component-a', 'place', 'component A',
                     '01070100', '{}'::jsonb, 'active'),
                    ('feature:component-b', 'place', 'component B',
                     '01070100', '{}'::jsonb, 'active')
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
                        'component-migration', 'component migration', 'test'
                    )
                    RETURNING theme_id
                ), collection AS (
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title
                    )
                    SELECT
                        'component-migration:2026', theme_id,
                        'component migration'
                    FROM theme
                    RETURNING collection_id
                )
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, external_item_id, place_name
                )
                SELECT
                    collection_id, 'feature:component-a',
                    'compound-item', 'component A'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'feature:component-b',
                    'compound-item', 'component B'
                FROM collection
                """
            )
        )


async def _seed_pre_0065_legacy_projection(engine: Any) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'feature:component-chain', 'place',
                    'component chain fixture', '01070100',
                    '{}'::jsonb, 'active'
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
                        'component-chain', 'component chain', 'test'
                    )
                    RETURNING theme_id
                ), source AS (
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'component-chain-provider', 'component-chain-dataset',
                        'component chain source', 'manual', 'unknown',
                        'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, display_title
                )
                SELECT
                    theme.theme_id,
                    'feature:component-chain',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'component chain projection'
                FROM theme CROSS JOIN source
                """
            )
        )


async def test_component_identity_contiguous_upgrade_flushes_deferred_events(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_component_chain_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, "0064_price_series_identity")
        await _seed_pre_0065_legacy_projection(target_engine)
        await target_engine.dispose()

        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            component = (
                await connection.execute(
                    text(
                        """
                        SELECT item.external_component_id
                        FROM feature.curation_items AS item
                        JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.legacy_projection_id
                        WHERE legacy.display_title =
                              'component chain projection'
                        """
                    )
                )
            ).scalar_one()
            assert revision == _TARGET_REVISION
            assert component.startswith("legacy:")
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()


async def test_component_identity_upgrade_and_fail_closed_downgrade(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_component_identity_{uuid4().hex}"
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
        await _seed_pre_0066(target_engine)
        await target_engine.dispose()

        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            column = (
                await connection.execute(
                    text(
                        """
                        SELECT is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'feature'
                          AND table_name = 'curation_items'
                          AND column_name = 'external_component_id'
                        """
                    )
                )
            ).one()
            assert column == ("NO", "'primary'::text")

            migrated = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            curation_item_id::text,
                            external_component_id
                        FROM feature.curation_items
                        WHERE external_item_id = 'compound-item'
                        ORDER BY curation_item_id
                        """
                    )
                )
            ).all()
            assert len(migrated) == 2
            assert len({row.external_component_id for row in migrated}) == 2
            assert all(
                row.external_component_id == f"legacy:{row.curation_item_id}"
                for row in migrated
            )

            collection_id = (
                await connection.execute(
                    text(
                        """
                        SELECT collection_id::text
                        FROM feature.curation_collections
                        WHERE collection_key = 'component-migration:2026'
                        """
                    )
                )
            ).scalar_one()
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, external_item_id,
                        external_component_id, place_name
                    ) VALUES
                        (CAST(:collection_id AS uuid), NULL, 'unresolved-item',
                         'component-01', 'unresolved A'),
                        (CAST(:collection_id AS uuid), NULL, 'unresolved-item',
                         'component-02', 'unresolved B')
                    """
                ),
                {"collection_id": collection_id},
            )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO feature.curation_items (
                                collection_id, feature_id, external_item_id,
                                external_component_id, place_name
                            ) VALUES (
                                CAST(:collection_id AS uuid),
                                'feature:component-a', 'compound-item',
                                'duplicate-target', 'duplicate target'
                            )
                            """
                        ),
                        {"collection_id": collection_id},
                    )
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items
                    SET source_present = false
                    WHERE collection_id = CAST(:collection_id AS uuid)
                      AND external_item_id = 'compound-item'
                      AND feature_id = 'feature:component-a'
                    """
                ),
                {"collection_id": collection_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, external_item_id,
                        external_component_id, place_name
                    ) VALUES (
                        CAST(:collection_id AS uuid),
                        'feature:component-a', 'compound-item',
                        'component-01', 'component A'
                    )
                    """
                ),
                {"collection_id": collection_id},
            )
            source_versions = (
                await connection.execute(
                    text(
                        """
                        SELECT source_present, external_component_id
                        FROM feature.curation_items
                        WHERE collection_id = CAST(:collection_id AS uuid)
                          AND external_item_id = 'compound-item'
                          AND feature_id = 'feature:component-a'
                        ORDER BY source_present, external_component_id
                        """
                    ),
                    {"collection_id": collection_id},
                )
            ).all()
            assert len(source_versions) == 2
            assert source_versions[0].source_present is False
            assert source_versions[1] == (True, "component-01")
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            """
                            INSERT INTO feature.curation_items (
                                collection_id, feature_id, external_item_id,
                                external_component_id, place_name
                            ) VALUES (
                                CAST(:collection_id AS uuid), NULL,
                                'whitespace-component', ' primary ',
                                'whitespace component'
                            )
                            """
                        ),
                        {"collection_id": collection_id},
                    )

        await target_engine.dispose()
        with pytest.raises(RuntimeError, match="cannot represent multiple source components"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )

        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == _TARGET_REVISION
            await connection.execute(
                text(
                    """
                    DELETE FROM feature.curation_items
                    WHERE (
                            external_item_id = 'unresolved-item'
                            AND external_component_id = 'component-02'
                        )
                       OR (
                           external_item_id = 'compound-item'
                           AND external_component_id = 'component-01'
                       )
                    """
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
        async with target_engine.connect() as connection:
            column_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM information_schema.columns
                        WHERE table_schema = 'feature'
                          AND table_name = 'curation_items'
                          AND column_name = 'external_component_id'
                        """
                    )
                )
            ).scalar_one()
            assert column_count == 0
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
