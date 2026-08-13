"""T-VN-40 canonical collection command actual-LOGIN integration."""

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


async def test_collection_commands_are_revisioned_idempotent_and_admin_only(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-collection-{suffix}"
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
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
                              :slug, 'Collection theme', '', 'test', 'admin_only',
                              '{}'::jsonb, :command_id, :actor, NULL, NULL
                            )
                            """
                        ),
                        {
                            "actor": actor,
                            "command_id": theme_command,
                            "slug": f"collection-theme-{suffix}",
                        },
                    )
                ).mappings().one()["o_theme_id"]
            )

        create_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.create"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            created = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curation_collection_command(
                          :collection_key, CAST(:theme_id AS uuid), NULL,
                          'Collection', '', NULL, 'draft', 'admin_only',
                          '{}'::jsonb, :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_key": f"collection-{suffix}",
                        "command_id": create_command,
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        collection_id = str(created["o_collection_id"])
        assert int(created["o_collection_revision"]) == 1

        no_op_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.patch"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            no_op = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_collection_command(
                          CAST(:collection_id AS uuid), 1, CAST(:theme_id AS uuid),
                          NULL, 'Collection', '', NULL, 'draft', 'admin_only',
                          '{}'::jsonb, :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": no_op_command,
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        assert int(no_op["o_collection_revision"]) == 1

        patch_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.patch"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_collection_command(
                          CAST(:collection_id AS uuid), 1, CAST(:theme_id AS uuid),
                          NULL, 'Collection revised', '2026', NULL, 'published',
                          'public', CAST(:metadata AS jsonb), :command_id, :actor,
                          NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": patch_command,
                        "metadata": '{"version":2}',
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        assert int(patched["o_collection_revision"]) == 2

        stale_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.patch"
        )
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curation_collection_command(
                          CAST(:collection_id AS uuid), 1, CAST(:theme_id AS uuid),
                          NULL, 'stale', '', NULL, 'draft', 'admin_only',
                          '{}'::jsonb, :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": stale_command,
                        "theme_id": theme_id,
                    },
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        archive_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.archive"
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived = (
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curation_collection_command(
                          CAST(:collection_id AS uuid), 2, :command_id, :actor,
                          NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": archive_command,
                    },
                )
            ).mappings().one()
        assert int(archived["o_collection_revision"]) == 3

        async with migrated_engine.connect() as connection:
            assert int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM ops.curation_catalog_command_effects
                        WHERE resource_kind = 'collection'
                          AND resource_id = CAST(:collection_id AS uuid)
                        """
                    ),
                    {"collection_id": collection_id},
                )
            ) == 4

        denied_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation-collection.create"
        )
        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as denied:
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curation_collection_command(
                          :collection_key, CAST(:theme_id AS uuid), NULL,
                          'Denied', '', NULL, 'draft', 'admin_only', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_key": f"denied-{suffix}",
                        "command_id": denied_command,
                        "theme_id": theme_id,
                    },
                )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()

        for runtime in (api, dagster):
            for statement, params in (
                (
                    """
                    INSERT INTO feature.curation_collections (
                      collection_key, theme_id, title, edition_key, status,
                      visibility, metadata
                    ) VALUES (
                      :key, CAST(:theme_id AS uuid), 'raw bypass', '', 'draft',
                      'admin_only', '{}'::jsonb
                    )
                    """,
                    {"key": f"raw-{uuid4().hex}", "theme_id": theme_id},
                ),
                (
                    "UPDATE feature.curation_collections SET row_revision = 99 "
                    "WHERE collection_id = CAST(:collection_id AS uuid)",
                    {"collection_id": collection_id},
                ),
                (
                    "DELETE FROM feature.curation_collections "
                    "WHERE collection_id = CAST(:collection_id AS uuid)",
                    {"collection_id": collection_id},
                ),
            ):
                async with runtime.connect() as connection:
                    transaction = await connection.begin()
                    with pytest.raises(DBAPIError) as raw_denied:
                        await connection.execute(text(statement), params)
                    assert getattr(raw_denied.value.orig, "sqlstate", None) == "42501"
                    await transaction.rollback()
    finally:
        await api.dispose()
        await dagster.dispose()
