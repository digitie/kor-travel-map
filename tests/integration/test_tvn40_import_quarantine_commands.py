"""T-VN-40 import/quarantine collection command actual-LOGIN gate."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kortravelmap.infra.curation_repo import (
    ResolvedCurationImportRow,
    confirm_curation_quarantine_standalone,
    import_curation_rows,
    move_curation_quarantine_items,
)
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


async def test_import_and_quarantine_advance_collection_revision_once(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-import-{suffix}"
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    session_factory = async_sessionmaker(api, expire_on_commit=False)
    try:
        async with migrated_engine.begin() as connection:
            dataset_id = int(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO provider_sync.provider_datasets (
                          provider, dataset_key, display_name, source_kind,
                          is_active, capabilities
                        ) VALUES (
                              'tvn40-import-test', :dataset_key, 'T-VN-40 import',
                              'manual', true,
                              CAST(:capabilities AS jsonb)
                        ) RETURNING provider_dataset_id
                        """
                    ),
                    {
                        "dataset_key": f"import-{suffix}",
                        "capabilities": '{"schema_version":1,"produces":[],"extensions":{}}',
                    },
                )
            )
            theme_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO feature.curated_themes (
                          theme_slug, theme_name, theme_group, visibility,
                          metadata, owner_kind
                        ) VALUES (
                          :slug, 'Import theme', 'test', 'admin_only',
                          '{}'::jsonb, 'operator'
                        ) RETURNING theme_id
                        """
                    ),
                    {"slug": f"import-theme-{suffix}"},
                )
            )
            source_id = str(
                await connection.scalar(
                    text(
                        """
                            INSERT INTO feature.curated_sources (
                              provider_dataset_id, source_name, source_kind,
                              update_cycle, provider_status, metadata
                            ) VALUES (
                              :dataset_id, 'Import source', 'manual', 'unknown',
                              'manual_only', '{}'::jsonb
                        ) RETURNING source_id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
            )

        row = ResolvedCurationImportRow(
            row_number=2,
            collection_key=f"import-collection-{suffix}",
            theme_slug=f"import-theme-{suffix}",
            theme_name="Import theme",
            theme_group="test",
            title="Import collection",
            edition_key="2026",
            provider_dataset_id=dataset_id,
            source_name="Import source",
            source_url=None,
            source_item_key="item-1",
            feature_id=None,
            place_name="Import place",
            address_hint=None,
            sort_order=0,
            item_title=None,
            item_summary=None,
            metadata={"version": 1},
        )
        first_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation.import"
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            first = await import_curation_rows(
                session,
                rows=(row,),
                actor=actor,
                batch_kind="normalized_rows",
                command_id=first_command,
            )
        assert first["inserted"] == 1
        collection_id = str(
            await _collection_scalar(
                migrated_engine,
                row.collection_key,
                "collection_id::text",
            )
        )
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 1

        changed_row = ResolvedCurationImportRow(
            **{
                **row.__dict__,
                "item_title": "changed",
                "metadata": {"version": 2},
            }
        )
        second_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation.import"
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            second = await import_curation_rows(
                session,
                rows=(changed_row,),
                actor=actor,
                batch_kind="normalized_rows",
                command_id=second_command,
            )
        assert second["updated"] == 1
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 2

        third_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation.import"
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            third = await import_curation_rows(
                session,
                rows=(changed_row,),
                actor=actor,
                batch_kind="normalized_rows",
                command_id=third_command,
            )
        assert third["updated"] == 0
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 2
        async with migrated_engine.connect() as connection:
            assert int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM feature.curation_import_batches "
                        "WHERE command_id = ANY(CAST(:ids AS bigint[]))"
                    ),
                    {"ids": [first_command, second_command, third_command]},
                )
            ) == 3

        target_id, quarantine_id, quarantine_item_id = await _seed_quarantine(
            migrated_engine,
            theme_id=theme_id,
            source_id=source_id,
            suffix=suffix,
        )
        move_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation-quarantine.reclassify",
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            moved, deleted = await move_curation_quarantine_items(
                session,
                collection_id=quarantine_id,
                expected_collection_revision=1,
                target_collection_id=target_id,
                expected_target_revision=1,
                item_ids=(quarantine_item_id,),
                command_id=move_command,
                actor=actor,
            )
        assert moved == (quarantine_item_id,)
        assert deleted is True
        async with migrated_engine.connect() as connection:
            moved_state = (
                await connection.execute(
                    text(
                        """
                        SELECT item.collection_id::text, item.row_revision,
                               collection.row_revision
                        FROM feature.curation_items AS item
                        JOIN feature.curation_collections AS collection
                          ON collection.collection_id = item.collection_id
                        WHERE item.curation_item_id = CAST(:item_id AS uuid)
                        """
                    ),
                    {"item_id": quarantine_item_id},
                )
            ).one()
        assert tuple(moved_state) == (target_id, 2, 2)

        standalone_id = await _seed_standalone_quarantine(
            migrated_engine,
            theme_id=theme_id,
            source_id=source_id,
            suffix=suffix,
        )
        standalone_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation-quarantine.reclassify",
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            confirmed = await confirm_curation_quarantine_standalone(
                session,
                collection_id=standalone_id,
                expected_collection_revision=1,
                collection_key=f"standalone-{suffix}",
                title="Standalone",
                command_id=standalone_command,
                actor=actor,
            )
        assert confirmed == (standalone_id, f"standalone-{suffix}")
        assert await _collection_scalar(
            migrated_engine, f"standalone-{suffix}", "row_revision"
        ) == 2

        stale_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation-collection.patch",
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
                          CAST(:source_id AS uuid), 'stale', '2026', NULL,
                          'published', 'public', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": stale_command,
                        "source_id": source_id,
                        "theme_id": theme_id,
                    },
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()
    finally:
        await api.dispose()


async def _collection_scalar(
    engine: AsyncEngine,
    collection_key: str,
    expression: str,
) -> object:
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                f"SELECT {expression} FROM feature.curation_collections "
                "WHERE collection_key = :collection_key"
            ),
            {"collection_key": collection_key},
        )


async def _seed_quarantine(
    engine: AsyncEngine,
    *,
    theme_id: str,
    source_id: str,
    suffix: str,
) -> tuple[str, str, str]:
    async with engine.begin() as connection:
        target_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                      collection_key, theme_id, source_id, title, edition_key,
                      status, visibility, metadata, row_revision
                    ) VALUES (
                      :key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                      'Target', '', 'draft', 'admin_only', '{}'::jsonb, 1
                    ) RETURNING collection_id
                    """
                ),
                {"key": f"target-{suffix}", "source_id": source_id, "theme_id": theme_id},
            )
        )
        quarantine_id = str(uuid4())
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_collections (
                  collection_id, collection_key, theme_id, source_id, title,
                  edition_key, status, visibility, metadata, created_by,
                  row_revision
                ) VALUES (
                  CAST(:id AS uuid), :key, CAST(:theme_id AS uuid),
                  CAST(:source_id AS uuid), 'Quarantine', '', 'draft',
                  'admin_only', jsonb_build_object(
                      'migration_quarantine', '0065',
                      'original_collection_id', CAST(:target_id AS text)
                  ), 'migration:0065', 1
                )
                """
            ),
            {
                "id": quarantine_id,
                "key": f"quarantine-{suffix}",
                "source_id": source_id,
                "target_id": target_id,
                "theme_id": theme_id,
            },
        )
        item_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curation_items (
                      collection_id, external_item_id, external_component_id,
                      place_name, status, sort_order, curation_relation,
                      reuse_policy, metadata, row_revision
                    ) VALUES (
                      CAST(:collection_id AS uuid), 'q-item', 'primary',
                      'Quarantined', 'included', 0, 'nearby_option',
                      'manual_review', '{}'::jsonb, 1
                    ) RETURNING curation_item_id
                    """
                ),
                {"collection_id": quarantine_id},
            )
        )
    return target_id, quarantine_id, item_id


async def _seed_standalone_quarantine(
    engine: AsyncEngine,
    *,
    theme_id: str,
    source_id: str,
    suffix: str,
) -> str:
    async with engine.begin() as connection:
        return str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                      collection_key, theme_id, source_id, title, edition_key,
                      status, visibility, metadata, created_by, row_revision
                    ) VALUES (
                      :key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                      'Quarantine standalone', '', 'draft', 'admin_only',
                      '{"migration_quarantine":"0065"}'::jsonb,
                      'migration:0065', 1
                    ) RETURNING collection_id
                    """
                ),
                {
                    "key": f"standalone-quarantine-{suffix}",
                    "source_id": source_id,
                    "theme_id": theme_id,
                },
            )
        )
