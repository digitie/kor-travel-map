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
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'feature:migration-external-api', 'place',
                    'migration external api fixture',
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
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items
                SET curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    updated_by = 'migration-tombstone-operator'
                WHERE place_name IN (
                    'resolved tombstone newest',
                    'unresolved tombstone'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items
                SET metadata = '{"provider_revision": "latest"}'::jsonb
                WHERE place_name IN (
                    'resolved resurrected',
                    'unresolved resurrected'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'migration-provider', 'migration-dataset',
                        'migration source', 'manual', 'unknown',
                        'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id
                ), theme AS (
                    SELECT theme_id
                    FROM feature.curated_themes
                    WHERE theme_slug = 'migration-presence'
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, selected_by, display_title,
                    curation_relation, reuse_policy
                )
                SELECT
                    theme.theme_id, 'feature:migration-presence',
                    source.source_id, 'curated', 'external_api',
                    'external-principal', 'migration legacy override',
                    'nearby_option', 'manual_review'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id, 'feature:migration-external-api',
                    source.source_id, 'curated', 'external_api',
                    'external-principal', 'migration external provenance',
                    'nearby_option', 'manual_review'
                FROM theme CROSS JOIN source
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), themes AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES
                        (
                            'migration-legacy-duplicate',
                            'migration legacy duplicate',
                            'test',
                            'public'
                        ),
                        (
                            'migration-status-only-archive',
                            'migration status-only archive',
                            'test',
                            'public'
                        )
                    RETURNING theme_id, theme_slug
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, display_title, archived_at, updated_at
                )
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'archived', 'source_rule',
                    'migration legacy duplicate',
                    now() - interval '2 hours',
                    now() - interval '2 hours'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-legacy-duplicate'
                UNION ALL
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'curated', 'source_rule',
                    'migration legacy duplicate', NULL, now()
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-legacy-duplicate'
                UNION ALL
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'archived', 'source_rule',
                    'migration status-only archive', NULL, now()
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-status-only-archive'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET external_item_id = 'migration-legacy-duplicate'
                FROM feature.curated_features AS legacy
                WHERE legacy.display_title = 'migration legacy duplicate'
                  AND item.curation_item_id = legacy.curated_feature_id
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET status = 'archived',
                    archived_at = now(),
                    updated_by = 'canonical-tombstone-drift',
                    updated_at = clock_timestamp()
                FROM feature.curated_features AS legacy
                WHERE legacy.display_title = 'migration legacy duplicate'
                  AND legacy.curation_status = 'curated'
                  AND item.curation_item_id = legacy.curated_feature_id
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET status = 'rejected',
                    curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    updated_by = 'canonical-operator',
                    updated_at = clock_timestamp()
                FROM feature.curated_features AS legacy
                WHERE legacy.feature_id = 'feature:migration-presence'
                  AND legacy.display_title = 'migration legacy override'
                  AND item.curation_item_id = legacy.curated_feature_id
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
        async with target_engine.connect() as connection:
            provenance_columns = {
                (str(table_name), str(column_name))
                for table_name, column_name in (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name "
                            "FROM information_schema.columns "
                            "WHERE table_schema = 'feature' "
                            "AND table_name IN ('curated_features','curation_items') "
                            "AND column_name IN ("
                            "'source_updated_at',"
                            "'legacy_projection_id',"
                            "'operator_updated_by','operator_updated_at'"
                            ")"
                        )
                    )
                ).all()
            }
            legacy_provenance = (
                await connection.execute(
                    text(
                        "SELECT display_title, operator_updated_by, "
                        "operator_updated_at IS NOT NULL "
                        "FROM feature.curated_features "
                        "WHERE display_title IN ("
                        "'migration external provenance',"
                        "'migration legacy override'"
                        ") "
                        "ORDER BY display_title"
                    )
                )
            ).all()
            canonical_provenance = (
                await connection.execute(
                    text(
                        "SELECT feature_id, status, curation_relation, "
                        "reuse_policy, operator_updated_by, "
                        "operator_updated_at IS NOT NULL "
                        "FROM feature.curation_items "
                        "WHERE feature_id IN ("
                        "'feature:migration-presence',"
                        "'feature:migration-external-api'"
                        ") AND metadata ->> 'legacy_selection_origin' = 'external_api' "
                        "ORDER BY feature_id"
                    )
                )
            ).all()
            projection_fk = (
                await connection.execute(
                    text(
                        """
                        SELECT condeferrable, condeferred
                        FROM pg_constraint
                        WHERE conname =
                            'fk_curation_items_legacy_projection_id_curated_features'
                        """
                    )
                )
            ).one()
            mapped_projection_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_items AS item
                        JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.legacy_projection_id
                        """
                    )
                )
            ).scalar_one()
        assert provenance_columns == {
            ("curated_features", "operator_updated_by"),
            ("curated_features", "operator_updated_at"),
            ("curation_items", "legacy_projection_id"),
            ("curation_items", "source_updated_at"),
            ("curation_items", "operator_updated_by"),
            ("curation_items", "operator_updated_at"),
        }
        assert projection_fk == (True, True)
        assert mapped_projection_count > 0
        assert legacy_provenance == [
            ("migration external provenance", "external-principal", True),
            ("migration legacy override", "external-principal", True),
        ]
        assert canonical_provenance == [
            (
                "feature:migration-external-api",
                "included",
                "nearby_option",
                "manual_review",
                "external-principal",
                True,
            ),
            (
                "feature:migration-presence",
                "rejected",
                "primary_stop",
                "blocked",
                "canonical-operator",
                True,
            ),
        ]
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
        assert "UNIQUE" in upgraded_indexes["uq_curation_items_legacy_projection_id"]
        assert "legacy_projection_id IS NOT NULL" in (
            upgraded_indexes["uq_curation_items_legacy_projection_id"]
        )
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
            reconciled_axes = (
                await connection.execute(
                    text(
                        "SELECT external_item_id, curation_relation, "
                        "reuse_policy, operator_updated_by, metadata "
                        "FROM feature.curation_items "
                        "WHERE external_item_id IN "
                        "('resolved-conflict','unresolved-conflict') "
                        "ORDER BY external_item_id"
                    )
                )
            ).all()
            assert normalized == [
                ("resolved-conflict", 1, 0, "resolved resurrected"),
                ("unresolved-conflict", 1, 0, "unresolved resurrected"),
            ]
            assert reconciled_axes == [
                (
                    "resolved-conflict",
                    "primary_stop",
                    "blocked",
                    "migration-tombstone-operator",
                    {"provider_revision": "latest"},
                ),
                (
                    "unresolved-conflict",
                    "primary_stop",
                    "blocked",
                    "migration-tombstone-operator",
                    {"provider_revision": "latest"},
                ),
            ]
            migrated_legacy = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                            ),
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                                  AND legacy.archived_at IS NULL
                            ),
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                                  AND legacy.metadata @>
                                      '{"merge_projection_detached": true}'::jsonb
                            ),
                            bool_and(legacy.archived_at IS NOT NULL)
                                FILTER (
                                    WHERE legacy.display_title =
                                        'migration status-only archive'
                                ),
                            bool_and(legacy.selection_origin = 'admin')
                                FILTER (
                                    WHERE legacy.display_title =
                                        'migration status-only archive'
                                )
                        FROM feature.curated_features AS legacy
                        WHERE legacy.display_title IN (
                            'migration legacy duplicate',
                            'migration status-only archive'
                        )
                        """
                    )
                )
            ).one()
            assert migrated_legacy == (2, 0, 1, True, True)
            migrated_canonical = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE item.external_item_id =
                                    'migration-legacy-duplicate'
                            ),
                            bool_and(
                                item.status = 'archived'
                                AND item.archived_at IS NOT NULL
                            )
                        FROM feature.curation_items AS item
                        LEFT JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.curation_item_id
                        WHERE item.external_item_id =
                                'migration-legacy-duplicate'
                           OR legacy.display_title =
                                'migration status-only archive'
                        """
                    )
                )
            ).one()
            assert migrated_canonical[0] == 1
            assert migrated_canonical[1] is True
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
        with pytest.raises(Exception, match="durable curation state exists"):
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
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE feature.curation_items "
                    "SET operator_updated_by = NULL, operator_updated_at = NULL"
                )
            )
            await connection.execute(
                text(
                    "UPDATE feature.curated_features "
                    "SET operator_updated_by = NULL, operator_updated_at = NULL"
                )
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_items AS item "
                    "USING feature.curated_features AS legacy "
                    "WHERE legacy.display_title = 'migration legacy override' "
                    "AND item.curation_item_id = legacy.curated_feature_id"
                )
            )
            await connection.execute(
                text(
                    "UPDATE feature.curated_features "
                    "SET feature_id = 'feature:migration-external-api', "
                    "curation_status = 'archived', "
                    "metadata = metadata || "
                    "'{\"merge_projection_detached\": true}'::jsonb, "
                    "archived_at = now(), "
                    "updated_at = clock_timestamp() "
                    "WHERE display_title = 'migration legacy override'"
                )
            )
        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_features "
                    "WHERE metadata @> "
                    "'{\"merge_projection_detached\": true}'::jsonb"
                )
            )
            non_direct_relations = (
                await connection.execute(
                    text(
                        """
                        UPDATE feature.curation_items AS item
                        SET curation_item_id = x_extension.gen_random_uuid()
                        FROM feature.curated_features AS legacy
                        WHERE legacy.display_title =
                              'migration external provenance'
                          AND item.legacy_projection_id =
                              legacy.curated_feature_id
                        RETURNING item.curation_item_id
                        """
                    )
                )
            ).all()
            assert len(non_direct_relations) == 1
        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items
                    SET curation_item_id = legacy_projection_id
                    WHERE legacy_projection_id IS NOT NULL
                      AND legacy_projection_id <> curation_item_id
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
        downgraded_column, downgraded_indexes = await _schema_state(target_engine)
        assert downgraded_column is None
        async with target_engine.connect() as connection:
            remaining_provenance_columns = (
                await connection.execute(
                    text(
                        "SELECT count(*) "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'feature' "
                        "AND table_name IN ('curated_features','curation_items') "
                        "AND column_name IN ("
                        "'source_updated_at',"
                        "'legacy_projection_id',"
                        "'operator_updated_by','operator_updated_at'"
                        ")"
                    )
                )
            ).scalar_one()
        assert remaining_provenance_columns == 0
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_feature_status_collection"]
        )
        assert "uq_curation_items_identity" not in downgraded_indexes
        assert "uq_curation_items_legacy_projection_id" not in downgraded_indexes
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
        assert "uq_curation_items_legacy_projection_id" in recovered_indexes
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
