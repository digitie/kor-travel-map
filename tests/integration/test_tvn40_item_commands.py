"""T-VN-40 canonical item command actual-LOGIN integration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _domain_command(
    engine: AsyncEngine,
    *,
    actor: str,
    operation: str,
) -> int:
    async with engine.begin() as connection:
        return int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation, x_extension.gen_random_uuid(),
                      encode(x_extension.digest(
                        convert_to(x_extension.gen_random_uuid()::text, 'UTF8'),
                        'sha256'
                      ), 'hex')
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation},
            )
        )


async def test_item_commands_preserve_revision_link_audit_and_admin_boundary(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-item-{suffix}"
    feature_id = f"feature-item-{suffix}"
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                      feature_id, kind, name, category, coord, address,
                      marker_icon, marker_color
                    ) VALUES (
                      :feature_id, 'place', 'typed item', '01070100',
                      x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(126.9780, 37.5665), 4326
                      ), '{}'::jsonb, 'place', 'P-01'
                    )
                    """
                ),
                {"feature_id": feature_id},
            )
        theme_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curated-theme.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            theme_id = str(
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.create_curated_theme_command(
                              :slug, 'Item theme', '', 'test', 'admin_only',
                              '{}'::jsonb, :command_id, :actor, NULL, NULL
                            )
                            """
                        ),
                        {
                            "actor": actor,
                            "command_id": theme_command,
                            "slug": f"item-theme-{suffix}",
                        },
                    )
                ).mappings().one()["o_theme_id"]
            )
        collection_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            collection_id = str(
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.create_curation_collection_command(
                              :collection_key, CAST(:theme_id AS uuid), NULL,
                              'Items', '', NULL, 'draft', 'admin_only',
                              '{}'::jsonb, :command_id, :actor, NULL, NULL
                            )
                            """
                        ),
                        {
                            "actor": actor,
                            "collection_key": f"items-{suffix}",
                            "command_id": collection_command,
                            "theme_id": theme_id,
                        },
                    )
                ).mappings().one()["o_collection_id"]
            )

        create_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            created = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curation_item_command(
                          CAST(:collection_id AS uuid), :feature_id, NULL,
                          'manual-1', 'primary', NULL, NULL, 'included', 0,
                          NULL, NULL, 'nearby_option', 'manual_review',
                          '{}'::jsonb, :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": create_command,
                        "feature_id": feature_id,
                    },
                )
            ).mappings().one()
        item_id = str(created["o_curation_item_id"])
        assert int(created["o_item_revision"]) == 1
        assert int(created["o_collection_revision"]) == 2

        no_op_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.patch"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            no_op = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_item_command(
                          CAST(:collection_id AS uuid), CAST(:item_id AS uuid), 1,
                          :feature_id, NULL, 'manual-1', 'primary', 'typed item',
                          NULL, 'included', 0, NULL, NULL, 'nearby_option',
                          'manual_review', '{}'::jsonb, :command_id, :actor,
                          NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": no_op_command,
                        "feature_id": feature_id,
                        "item_id": item_id,
                    },
                )
            ).mappings().one()
        assert int(no_op["o_item_revision"]) == 1
        assert int(no_op["o_collection_revision"]) == 2

        patch_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.patch"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_item_command(
                          CAST(:collection_id AS uuid), CAST(:item_id AS uuid), 1,
                          NULL, NULL, 'manual-1', 'primary', 'typed item', NULL,
                          'rejected', 0, 'operator title', NULL, 'nearby_option',
                          'blocked', '{}'::jsonb, :command_id, :actor,
                          NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": patch_command,
                        "item_id": item_id,
                    },
                )
            ).mappings().one()
        assert int(patched["o_item_revision"]) == 2
        assert int(patched["o_collection_revision"]) == 3

        stale_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.patch"
        )
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_item_command(
                          CAST(:collection_id AS uuid), CAST(:item_id AS uuid), 1,
                          NULL, NULL, 'manual-1', 'primary', 'stale', NULL,
                          'included', 0, NULL, NULL, 'nearby_option',
                          'manual_review', '{}'::jsonb, :command_id, :actor,
                          NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": stale_command,
                        "item_id": item_id,
                    },
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        archive_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.archive"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived = (
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curation_item_command(
                          CAST(:collection_id AS uuid), CAST(:item_id AS uuid), 2,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": archive_command,
                        "item_id": item_id,
                    },
                )
            ).mappings().one()
        assert int(archived["o_item_revision"]) == 3
        assert int(archived["o_collection_revision"]) == 4

        async with migrated_engine.connect() as connection:
            item = (
                await connection.execute(
                    text(
                        """
                        SELECT feature_id, accepted_link_decision_id, status,
                               row_revision
                        FROM feature.curation_items
                        WHERE curation_item_id = CAST(:item_id AS uuid)
                        """
                    ),
                    {"item_id": item_id},
                )
            ).mappings().one()
            assert item["feature_id"] is None
            assert item["accepted_link_decision_id"] is None
            assert item["status"] == "archived"
            assert int(item["row_revision"]) == 3
            assert int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM feature.curation_link_decisions
                        WHERE curation_item_id = CAST(:item_id AS uuid)
                        """
                    ),
                    {"item_id": item_id},
                )
            ) == 2
            assert int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM ops.curation_catalog_command_effects
                        WHERE resource_kind = 'item'
                          AND resource_id = CAST(:item_id AS uuid)
                        """
                    ),
                    {"item_id": item_id},
                )
            ) == 4

        denied_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-item.create"
        )
        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as denied:
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curation_item_command(
                          CAST(:collection_id AS uuid), NULL, NULL, 'denied',
                          'primary', 'denied', NULL, 'included', 0, NULL, NULL,
                          'nearby_option', 'manual_review', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": denied_command,
                    },
                )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()
    finally:
        await api.dispose()
        await dagster.dispose()
