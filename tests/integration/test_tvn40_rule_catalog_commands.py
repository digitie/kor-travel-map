"""T-VN-40 retained rule catalog command actual-LOGIN integration."""

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


def _constraint_name(error: DBAPIError) -> str | None:
    candidate: BaseException | None = error.orig
    while candidate is not None:
        constraint_name = getattr(candidate, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name
        candidate = candidate.__cause__
    return None


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


async def test_rule_create_patch_archive_is_cas_bound_and_reconciled(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-rule-{suffix}"
    feature_id = f"tvn40:rule:{suffix}"
    source_entity_keys = [
        f"tvn40:rule:entity-a:{suffix}",
        f"tvn40:rule:entity-b:{suffix}",
    ]
    async with migrated_engine.begin() as connection:
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind,
                      is_active, capabilities
                    ) VALUES (
                      'tvn40-rule', :dataset_key, 'T-VN-40 rule', 'manual',
                      true,
                      jsonb_build_object(
                        'schema_version', 1,
                        'produces', '[]'::jsonb,
                        'extensions', '{}'::jsonb
                      )
                    ) RETURNING provider_dataset_id
                    """
                ),
                {"dataset_key": f"dataset-{suffix}"},
            )
        )
        theme_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                      theme_slug, theme_name, theme_group, visibility,
                      owner_kind
                    ) VALUES (:slug, 'Rule test', 'test', 'admin_only', 'operator')
                    RETURNING theme_id
                    """
                ),
                {"slug": f"rule-test-{suffix}"},
            )
        )
        source_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                      provider_dataset_id, source_name, source_kind,
                      provider_status
                    ) VALUES (:dataset_id, 'Rule source', 'manual', 'implemented')
                    RETURNING source_id
                    """
                ),
                {"dataset_id": dataset_id},
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                  feature_id, kind, name, category, coord, address,
                  marker_icon, marker_color
                ) VALUES (
                  :feature_id, 'place', 'N:M rule receipt', '01070100',
                  x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(126.9780, 37.5665), 4326
                  ), '{}'::jsonb, 'place', 'P-01'
                )
                """
            ),
            {"feature_id": feature_id},
        )
        for index, source_entity_key in enumerate(source_entity_keys):
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_entities (
                      source_entity_key, provider_dataset_id, source_entity_type,
                      source_entity_id, first_seen_at, last_seen_at
                    ) VALUES (
                      :source_entity_key, :dataset_id, 'rule-receipt',
                      :source_entity_id, clock_timestamp(), clock_timestamp()
                    )
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "feature_id": feature_id,
                    "source_entity_id": f"entity-{index}-{suffix}",
                    "source_entity_key": source_entity_key,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_links (
                      feature_id, source_entity_key, source_role,
                      match_method, confidence
                    ) VALUES (
                      :feature_id, :source_entity_key, 'enrichment', 'exact', 100
                    )
                    """
                ),
                {"feature_id": feature_id, "source_entity_key": source_entity_key},
            )

    create_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.create"
    )
    no_op_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.patch"
    )
    metadata_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.patch"
    )
    patch_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.patch"
    )
    stale_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.patch"
    )
    archive_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.archive"
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
                        CALL feature.create_curated_source_rule_command(
                          CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                          NULL, NULL, '{}'::jsonb, NULL, 'candidate', 0, true,
                          '{}'::jsonb, :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": create_command,
                        "source_id": source_id,
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        rule_id = str(created["o_rule_id"])
        assert int(created["o_rule_revision"]) == 1
        assert created["o_generation_id"] is not None

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            no_op = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 1, NULL, NULL, '{}'::jsonb,
                          NULL, 'candidate', 0, true, '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": no_op_command, "rule_id": rule_id},
                )
            ).mappings().one()
        assert int(no_op["o_rule_revision"]) == 1
        assert no_op["o_generation_id"] is None

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            metadata_only = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 1, NULL, NULL, '{}'::jsonb,
                          NULL, 'candidate', 0, true,
                          '{"display_note":"operator-only"}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": metadata_command,
                        "rule_id": rule_id,
                    },
                )
            ).mappings().one()
        assert int(metadata_only["o_rule_revision"]) == 2
        assert metadata_only["o_generation_id"] is None

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 2, NULL, NULL, '{}'::jsonb,
                          NULL, 'ignore', 1, true,
                          '{"display_note":"operator-only"}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": patch_command, "rule_id": rule_id},
                )
            ).mappings().one()
        assert int(patched["o_rule_revision"]) == 3
        assert patched["o_generation_id"] is not None

        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 1, NULL, NULL, '{}'::jsonb,
                          NULL, 'candidate', 0, true, '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": stale_command, "rule_id": rule_id},
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            assert _constraint_name(stale.value) == "ck_tvn40_expected_revision"
            await transaction.rollback()

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived = (
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 3, :command_id, 'operator_retired',
                          :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": archive_command, "rule_id": rule_id},
                )
            ).mappings().one()
        assert int(archived["o_rule_revision"]) == 4
        assert archived["o_generation_id"] is not None

        async with migrated_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT rule.row_revision, rule.default_action, rule.enabled,
                               rule.archived_at IS NOT NULL,
                               count(DISTINCT operation.operation_id) AS operation_count,
                               count(DISTINCT generation.generation_id) AS generation_count,
                               min(operation.scope_member_count) AS min_scope_count,
                               max(operation.scope_member_count) AS max_scope_count
                        FROM feature.curated_source_rules AS rule
                        LEFT JOIN ops.curation_rule_reconcile_operations AS operation
                          ON operation.rule_id = rule.rule_id
                        LEFT JOIN feature.theme_candidate_generations AS generation
                          ON generation.reconcile_operation_id = operation.operation_id
                        WHERE rule.rule_id = CAST(:rule_id AS uuid)
                        GROUP BY rule.rule_id
                        """
                    ),
                    {"rule_id": rule_id},
                )
            ).one()
        assert row == (4, "ignore", False, True, 3, 3, 3, 3)

        async with dagster.connect() as connection:
            assert not bool(
                await connection.scalar(
                    text(
                        """
                        SELECT has_function_privilege(
                          session_user,
                          'feature.patch_curated_source_rule_command(uuid,bigint,text,text,jsonb,jsonb,text,integer,boolean,jsonb,bigint,text)'::regprocedure,
                          'EXECUTE'
                        )
                        """
                    )
                )
            )
    finally:
        await api.dispose()
        await dagster.dispose()
