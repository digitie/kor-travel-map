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

    create_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-source-rule.create"
    )
    no_op_command = await _domain_command(
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
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 1, NULL, NULL, '{}'::jsonb,
                          NULL, 'ignore', 1, true, '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": patch_command, "rule_id": rule_id},
                )
            ).mappings().one()
        assert int(patched["o_rule_revision"]) == 2
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
                          CAST(:rule_id AS uuid), 2, :command_id, 'operator_retired',
                          :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"actor": actor, "command_id": archive_command, "rule_id": rule_id},
                )
            ).mappings().one()
        assert int(archived["o_rule_revision"]) == 3
        assert archived["o_generation_id"] is not None

        async with migrated_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT rule.row_revision, rule.default_action, rule.enabled,
                               rule.archived_at IS NOT NULL,
                               count(operation.operation_id) AS operation_count,
                               count(generation.generation_id) AS generation_count
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
        assert row == (3, "ignore", False, True, 3, 3)

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
