"""T-VN-40 retained source catalog/observation actual-LOGIN gate."""

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


async def test_source_operator_cas_and_provider_observation_are_disjoint(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-source-{suffix}"
    async with migrated_engine.begin() as connection:
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind,
                      is_active, capabilities
                    ) VALUES (
                      'tvn40-source-test', :dataset_key, 'T-VN-40 source test',
                      'system', true,
                      jsonb_build_object(
                        'schema_version', 1,
                        'produces', '[]'::jsonb,
                        'extensions', '{}'::jsonb
                      )
                    ) RETURNING provider_dataset_id
                    """
                ),
                {"dataset_key": f"source-{suffix}"},
            )
        )
        seed = {
            "actor": actor,
            "dataset_id": dataset_id,
            "feature_id": f"feature:tvn40-source-{suffix}",
            "source_entity_key": f"entity:tvn40-source-{suffix}",
            "source_record_key": f"record:tvn40-source-{suffix}",
            "suffix": suffix,
        }
        for statement in (
            """
            INSERT INTO provider_sync.source_entities (
              source_entity_key, provider_dataset_id, source_entity_type,
              source_entity_id, first_seen_at, last_seen_at
            ) VALUES (
              :source_entity_key, :dataset_id, 'source-test', :suffix,
              clock_timestamp(), clock_timestamp()
            )
            """,
            """
            INSERT INTO provider_sync.source_records (
              source_record_key, source_entity_key, raw_data,
              raw_payload_hash, fetched_at
            ) VALUES (
              :source_record_key, :source_entity_key, '{}'::jsonb,
              repeat('a', 64), clock_timestamp()
            )
            """,
            """
            INSERT INTO provider_sync.source_entity_heads (
              source_entity_key, current_source_record_key, observed_at, lineage_key
            ) VALUES (
              :source_entity_key, :source_record_key, clock_timestamp(), :suffix
            )
            """,
            """
            INSERT INTO feature.features (
              feature_id, kind, name, category, coord, address,
              marker_icon, marker_color
            ) VALUES (
              :feature_id, 'place', 'source candidate', '01070100',
              x_extension.ST_SetSRID(x_extension.ST_MakePoint(126.978,37.5665),4326),
              '{}'::jsonb, 'place', 'P-01'
            )
            """,
            """
            INSERT INTO provider_sync.source_links (
              feature_id, source_entity_key, source_role, match_method, confidence
            ) VALUES (:feature_id, :source_entity_key, 'primary', 'exact', 100)
            """,
            """
            INSERT INTO feature.feature_places (
              feature_id, feature_uuid, kind, place_kind,
              facility_info, reviews_link, payload
            ) SELECT feature_id, feature_uuid, kind, 'attraction',
                     '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
              FROM feature.features WHERE feature_id = :feature_id
            """,
        ):
            await connection.execute(text(statement), seed)
        operations = (
            "admin.curated-source.create",
            "admin.curated-source.patch",
            "admin.curated-source.patch",
            "admin.curated-source.archive",
            "admin.curated-source.patch",
        )
        command_ids: list[int] = []
        for operation in operations:
            command_ids.append(
                int(
                    await connection.scalar(
                        text(
                            """
                            INSERT INTO ops.domain_commands (
                              actor, operation, idempotency_key, request_fingerprint
                            ) VALUES (
                              :actor, :operation, x_extension.gen_random_uuid(), repeat('d',64)
                            ) RETURNING command_id
                            """
                        ),
                        {"actor": actor, "operation": operation},
                    )
                )
            )
        await connection.execute(
            text(
                """
                INSERT INTO ops.domain_command_results (
                  command_id, response_status, response_body
                ) VALUES (:command_id, 200, '{}'::jsonb)
                """
            ),
            {"command_id": command_ids[4]},
        )
        root_job_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, payload, status, progress, current_stage,
                      dagster_run_id, dataset_membership_mode, trigger_kind,
                      operation_key, dagster_run_status, created_at
                    ) VALUES (
                      'provider_feature_load_run', '{}'::jsonb, 'done', 100,
                      'completed', :run_id, 'root', 'schedule', 'load', 'SUCCESS',
                      clock_timestamp() - interval '2 hours'
                    ) RETURNING job_id
                    """
                ),
                {"run_id": f"tvn40-source-{suffix}"},
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                  provider_dataset_id, operation_key, operation_kind,
                  is_enabled, config
                ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
                """
            ),
            seed,
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                  provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                """
            ),
            seed,
        )
        source_job_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, parent_job_id, payload, status, progress,
                      current_stage, dagster_run_id, dataset_membership_mode,
                      finished_at, created_at
                    ) VALUES (
                      'provider_feature_load', CAST(:root_job_id AS uuid),
                      jsonb_build_object(
                        'authoritative_snapshot_complete', true,
                        'source_observation', jsonb_build_object(
                          'schema_version', 1,
                          'row_count', 1,
                          'last_source_modified_at', current_date::text,
                          'input_set_hash', repeat('e', 64)
                        )
                      ),
                      'done', 100, 'completed', :run_id, 'single', clock_timestamp(),
                      (SELECT created_at FROM ops.import_jobs
                       WHERE job_id = CAST(:root_job_id AS uuid))
                    ) RETURNING job_id
                    """
                ),
                {
                    "root_job_id": root_job_id,
                    "run_id": f"tvn40-source-{suffix}",
                },
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO ops.import_job_datasets (
                  job_id, provider_dataset_id, sync_scope, operation_key
                ) VALUES (
                  CAST(:job_id AS uuid), :dataset_id, 'dataset_wide', 'load'
                )
                """
            ),
            {"dataset_id": dataset_id, "job_id": source_job_id},
        )
        old_source_job_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, parent_job_id, payload, status, progress,
                      current_stage, dagster_run_id, dataset_membership_mode,
                      finished_at, created_at
                    ) VALUES (
                      'provider_feature_load', CAST(:root_job_id AS uuid),
                      jsonb_build_object(
                        'authoritative_snapshot_complete', true,
                        'source_observation', jsonb_build_object(
                          'schema_version', 1,
                          'row_count', 1,
                          'last_source_modified_at', current_date::text,
                          'input_set_hash', repeat('f', 64)
                        )
                      ),
                      'done', 100, 'completed', :run_id, 'single',
                      clock_timestamp() - interval '1 hour',
                      (SELECT created_at FROM ops.import_jobs
                       WHERE job_id = CAST(:root_job_id AS uuid))
                    ) RETURNING job_id
                    """
                ),
                {
                    "root_job_id": root_job_id,
                    "run_id": f"tvn40-source-{suffix}",
                },
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO ops.import_job_datasets (
                  job_id, provider_dataset_id, sync_scope, operation_key
                ) VALUES (
                  CAST(:job_id AS uuid), :dataset_id, 'dataset_wide', 'load'
                )
                """
            ),
            {"dataset_id": dataset_id, "job_id": old_source_job_id},
        )

    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            created = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curated_source_command(
                          :dataset_id, 'source catalog', NULL, 'internal', NULL,
                          'daily', NULL, 'implemented', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[0]},
                )
            ).mappings().one()
        source_id = str(created["o_source_id"])
        assert (int(created["o_source_revision"]), int(created["o_observation_revision"])) == (1, 1)

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            no_op = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_command(
                          CAST(:source_id AS uuid), 1, 'source catalog', NULL,
                          'internal', NULL, 'daily', NULL, 'implemented', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[1], "source_id": source_id},
                )
            ).mappings().one()
        assert int(no_op["o_source_revision"]) == 1

        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as reused:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_command(
                          CAST(:source_id AS uuid), 1, 'second effect', NULL,
                          'internal', NULL, 'daily', NULL, 'implemented', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[1], "source_id": source_id},
                )
            assert getattr(reused.value.orig, "sqlstate", None) == "23505"
            await transaction.rollback()

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_command(
                          CAST(:source_id AS uuid), 1, 'source catalog renamed', NULL,
                          'internal', NULL, 'daily', NULL, 'implemented', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[2], "source_id": source_id},
                )
            ).mappings().one()
        assert (int(patched["o_source_revision"]), int(patched["o_observation_revision"])) == (2, 1)

        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as terminal:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_command(
                          CAST(:source_id AS uuid), 2, 'terminal reuse', NULL,
                          'internal', NULL, 'daily', NULL, 'implemented', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[4], "source_id": source_id},
                )
            assert getattr(terminal.value.orig, "sqlstate", None) == "23514"
            assert "already terminal" in str(terminal.value.orig)
            await transaction.rollback()

        async with dagster.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            observed = (
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"dataset_id": dataset_id, "job_id": source_job_id},
                )
            ).mappings().one()
        assert (
            int(observed["o_source_revision"]),
            int(observed["o_observation_revision"]),
            int(observed["o_row_count"]),
        ) == (2, 2, 1)

        async with dagster.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            replayed_observation = (
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"dataset_id": dataset_id, "job_id": source_job_id},
                )
            ).mappings().one()
        assert dict(replayed_observation) == dict(observed)

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as out_of_order:
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"dataset_id": dataset_id, "job_id": old_source_job_id},
                )
            assert getattr(out_of_order.value.orig, "sqlstate", None) == "23514"
            assert "older than the current receipt" in str(out_of_order.value.orig)
            await transaction.rollback()

        async with migrated_engine.connect() as connection:
            receipt = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*) AS receipt_count,
                               min(receipt.observed_at) AS observed_at,
                               min(job.finished_at) AS finished_at,
                               min(source.last_checked_at) AS last_checked_at
                        FROM ops.curation_source_observation_receipts AS receipt
                        JOIN ops.import_jobs AS job ON job.job_id = receipt.import_job_id
                        JOIN feature.curated_sources AS source
                          ON source.source_id = receipt.source_id
                        WHERE receipt.source_id = CAST(:source_id AS uuid)
                          AND receipt.import_job_id = CAST(:job_id AS uuid)
                        """
                    ),
                    {"source_id": source_id, "job_id": source_job_id},
                )
            ).mappings().one()
        assert int(receipt["receipt_count"]) == 1
        assert receipt["observed_at"] == receipt["finished_at"] == receipt["last_checked_at"]

        async with migrated_engine.begin() as connection:
            for index in range(2):
                theme_id = str(
                    await connection.scalar(
                        text(
                            """
                            INSERT INTO feature.curated_themes (
                              theme_slug, theme_name, theme_description, theme_group,
                              default_curated, visibility, metadata, owner_kind
                            ) VALUES (
                              :slug, 'source archive theme', '', 'test', false,
                              'admin_only', '{}'::jsonb, 'operator'
                            ) RETURNING theme_id
                            """
                        ),
                        {"slug": f"source-archive-{suffix}-{index}"},
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO feature.curated_source_rules (
                          theme_id, source_id, region_scope, default_action,
                          priority, enabled, metadata, owner_kind
                        ) VALUES (
                          CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                          '{}'::jsonb, 'candidate', 0, true, '{}'::jsonb, 'operator'
                        )
                        """
                    ),
                    {"source_id": source_id, "theme_id": theme_id},
                )

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived = (
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curated_source_command(
                          CAST(:source_id AS uuid), 2, :command_id,
                          'operator_retired', :actor, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seed, "command_id": command_ids[3], "source_id": source_id},
                )
            ).mappings().one()
        assert (
            int(archived["o_source_revision"]),
            int(archived["o_observation_revision"]),
            int(archived["o_generation_count"]),
        ) == (3, 2, 2)

        async with dagster.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived_replay = (
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"dataset_id": dataset_id, "job_id": source_job_id},
                )
            ).mappings().one()
        assert dict(archived_replay) == dict(observed)

        async with api.connect() as connection:
            tx = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as forbidden:
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"dataset_id": dataset_id, "job_id": source_job_id},
                )
            assert getattr(forbidden.value.orig, "sqlstate", None) == "42501"
            await tx.rollback()
        async with migrated_engine.connect() as connection:
            assert int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM ops.curation_catalog_command_effects
                        WHERE resource_kind = 'source' AND resource_id = CAST(:source_id AS uuid)
                        """
                    ),
                    {"source_id": source_id},
                )
            ) == 4
        async with api.connect() as connection:
            transaction = await connection.begin()
            with pytest.raises(DBAPIError) as forged_effect:
                await connection.execute(
                    text(
                        """
                        INSERT INTO ops.curation_catalog_command_effects (
                          command_id, operation, resource_kind, resource_id
                        ) VALUES (
                          :command_id, 'admin.curated-source.patch', 'source',
                          CAST(:source_id AS uuid)
                        )
                        """
                    ),
                    {"command_id": command_ids[2], "source_id": source_id},
                )
            assert getattr(forged_effect.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()
    finally:
        await api.dispose()
        await dagster.dispose()
