"""T-VN-40 import/quarantine collection command actual-LOGIN gate."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kortravelmap.infra.curation_repo import (
    CurationImportResult,
    CurationImportRevisionExpectation,
    ResolvedCurationImportRow,
    build_curation_import_revision_vector,
    claim_curation_import_plan_command,
    complete_curation_import_plan_command,
    confirm_curation_quarantine_standalone,
    create_curation_import_plan_command,
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
        unclaimed_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation.import"
        )
        async with session_factory() as session:
            transaction = await session.begin()
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as unclaimed:
                await import_curation_rows(
                    session,
                    rows=(row,),
                    actor=actor,
                    batch_kind="normalized_rows",
                    command_id=unclaimed_command,
                )
            assert getattr(unclaimed.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        first, first_command, _first_plan = await _import_with_plan(
            migrated_engine,
            session_factory=session_factory,
            rows=(row,),
            actor=actor,
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
        second, second_command, second_plan = await _import_with_plan(
            migrated_engine,
            session_factory=session_factory,
            rows=(changed_row,),
            actor=actor,
            complete=False,
        )
        assert second["updated"] == 1
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 2

        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as duplicate_touch:
                await connection.execute(
                    text(
                        "CALL feature.touch_curation_import_collection_command("
                        "CAST(:collection_id AS uuid), :command_id, :actor, NULL)"
                    ),
                    {
                        "actor": actor,
                        "collection_id": collection_id,
                        "command_id": second_command,
                    },
                )
            assert getattr(duplicate_touch.value.orig, "sqlstate", None) == "23505"
            await transaction.rollback()
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 2
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await complete_curation_import_plan_command(
                session,
                import_plan_id=second_plan,
                command_id=second_command,
                import_batch_id=str(second["import_batch_id"]),
                result_payload={"updated": second["updated"]},
                principal=actor,
            )

        third, third_command, _third_plan = await _import_with_plan(
            migrated_engine,
            session_factory=session_factory,
            rows=(changed_row,),
            actor=actor,
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

        item_revision_before = int(
            await _item_scalar(
                migrated_engine,
                row.collection_key,
                row.source_item_key,
                "item.row_revision",
            )
        )
        provenance_row = ResolvedCurationImportRow(
            **{
                **changed_row.__dict__,
                "provenance": {"source": "reviewed"},
            }
        )
        provenance_result, _provenance_command, _provenance_plan = (
            await _import_with_plan(
                migrated_engine,
                session_factory=session_factory,
                rows=(provenance_row,),
                actor=actor,
            )
        )
        assert provenance_result["updated"] == 1
        assert int(
            await _item_scalar(
                migrated_engine,
                row.collection_key,
                row.source_item_key,
                "item.row_revision",
            )
        ) == item_revision_before + 1
        assert await _collection_scalar(
            migrated_engine, row.collection_key, "row_revision"
        ) == 3

        preview_command = await _domain_command(
            migrated_engine,
            actor=actor,
            operation="admin.curation-import.preview",
        )
        import_plan_id = str(uuid4())
        stored_payload = {
            "row_number": changed_row.row_number,
            "collection_key": changed_row.collection_key,
            "metadata": changed_row.metadata,
        }
        plan_sha256 = hashlib.sha256(
            json.dumps(stored_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        revisions = await _revision_vector(
            session_factory,
            rows=(changed_row,),
        )
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await create_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                content_sha256="a" * 64,
                provenance_sha256=None,
                plan_sha256=plan_sha256,
                summary={"has_errors": False, "valid": 1},
                rows=(changed_row,),
                response_rows=({"row_number": 2, "valid": True},),
                revisions=revisions,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                command_id=preview_command,
                principal=actor,
            )
        plan_command = await _domain_command(
            migrated_engine, actor=actor, operation="admin.curation.import"
        )
        content_sha256: str
        stored_rows: tuple[ResolvedCurationImportRow, ...]
        summary: dict[str, object]
        response_rows: tuple[dict[str, object], ...]
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            content_sha256, stored_rows, summary, response_rows, _expires_at = (
                await claim_curation_import_plan_command(
                    session,
                    import_plan_id=import_plan_id,
                    plan_sha256=plan_sha256,
                    command_id=plan_command,
                    principal=actor,
                )
            )
            assert stored_rows == (changed_row,)
            assert summary == {"has_errors": False, "valid": 1}
            assert response_rows == ({"row_number": 2, "valid": True},)

        invalid_row_sets = (
            (
                ResolvedCurationImportRow(
                    **{**changed_row.__dict__, "item_title": "caller-tampered"}
                ),
            ),
            (),
            (
                changed_row,
                ResolvedCurationImportRow(
                    **{
                        **changed_row.__dict__,
                        "row_number": changed_row.row_number + 1,
                        "source_component_key": "caller-extra",
                    }
                ),
            ),
        )
        for invalid_rows in invalid_row_sets:
            async with session_factory() as session:
                transaction = await session.begin()
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                with pytest.raises(DBAPIError) as tampered:
                    await import_curation_rows(
                        session,
                        rows=invalid_rows,
                        actor=actor,
                        source_content_sha256=content_sha256,
                        batch_kind="csv_upload",
                        command_id=plan_command,
                    )
                assert getattr(tampered.value.orig, "sqlstate", None) == "23514"
                await transaction.rollback()

        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            imported = await import_curation_rows(
                session,
                rows=stored_rows,
                actor=actor,
                source_content_sha256=content_sha256,
                batch_kind="csv_upload",
                command_id=plan_command,
            )
            savepoint = await session.begin_nested()
            with pytest.raises(DBAPIError) as wrong_batch:
                await complete_curation_import_plan_command(
                    session,
                    import_plan_id=import_plan_id,
                    command_id=plan_command,
                    import_batch_id=str(first["import_batch_id"]),
                    result_payload={"summary": summary, "rows": list(response_rows)},
                    principal=actor,
                )
            assert getattr(wrong_batch.value.orig, "sqlstate", None) == "P0002"
            await savepoint.rollback()
            await complete_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                command_id=plan_command,
                import_batch_id=str(imported["import_batch_id"]),
                result_payload={"summary": summary, "rows": list(response_rows)},
                principal=actor,
            )
        async with migrated_engine.connect() as connection:
            stored_commit = (
                await connection.execute(
                    text(
                        "SELECT result_payload FROM ops.curation_import_plan_commits "
                        "WHERE import_plan_id = CAST(:plan_id AS uuid) "
                        "AND command_id = :command_id"
                    ),
                    {"command_id": plan_command, "plan_id": import_plan_id},
                )
            ).scalar_one()
            assert stored_commit["db_receipt"] == {
                "import_batch_id": str(imported["import_batch_id"]),
                "command_id": plan_command,
                "content_sha256": content_sha256,
                "row_count": 1,
            }

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


async def _revision_vector(
    session_factory: async_sessionmaker,
    *,
    rows: tuple[ResolvedCurationImportRow, ...],
) -> tuple[CurationImportRevisionExpectation, ...]:
    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        return await build_curation_import_revision_vector(session, rows=rows)


async def _import_with_plan(
    engine: AsyncEngine,
    *,
    session_factory: async_sessionmaker,
    rows: tuple[ResolvedCurationImportRow, ...],
    actor: str,
    complete: bool = True,
) -> tuple[CurationImportResult, int, str]:
    preview_command = await _domain_command(
        engine,
        actor=actor,
        operation="admin.curation-import.preview",
    )
    import_plan_id = str(uuid4())
    content_sha256 = uuid4().hex + uuid4().hex
    plan_sha256 = uuid4().hex + uuid4().hex
    revisions = await _revision_vector(session_factory, rows=rows)
    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        await create_curation_import_plan_command(
            session,
            import_plan_id=import_plan_id,
            content_sha256=content_sha256,
            provenance_sha256=None,
            plan_sha256=plan_sha256,
            summary={"has_errors": False, "valid": len(rows)},
            rows=rows,
            response_rows=tuple(
                {"row_number": row.row_number, "valid": True} for row in rows
            ),
            revisions=revisions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            command_id=preview_command,
            principal=actor,
        )
    command_id = await _domain_command(
        engine,
        actor=actor,
        operation="admin.curation.import",
    )
    async with session_factory() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        claimed_content_sha256, stored_rows, _summary, _response, _expires = (
            await claim_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                plan_sha256=plan_sha256,
                command_id=command_id,
                principal=actor,
            )
        )
        result = await import_curation_rows(
            session,
            rows=stored_rows,
            actor=actor,
            source_content_sha256=claimed_content_sha256,
            batch_kind="normalized_rows",
            command_id=command_id,
        )
        if complete:
            import_batch_id = result["import_batch_id"]
            assert import_batch_id is not None
            await complete_curation_import_plan_command(
                session,
                import_plan_id=import_plan_id,
                command_id=command_id,
                import_batch_id=import_batch_id,
                result_payload={"inserted": result["inserted"], "updated": result["updated"]},
                principal=actor,
            )
    return result, command_id, import_plan_id


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


async def _item_scalar(
    engine: AsyncEngine,
    collection_key: str,
    external_item_id: str,
    expression: str,
) -> object:
    async with engine.connect() as connection:
        return await connection.scalar(
            text(
                f"SELECT {expression} "
                "FROM feature.curation_items AS item "
                "JOIN feature.curation_collections AS collection "
                "ON collection.collection_id = item.collection_id "
                "WHERE collection.collection_key = :collection_key "
                "AND item.external_item_id = :external_item_id"
            ),
            {
                "collection_key": collection_key,
                "external_item_id": external_item_id,
            },
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
