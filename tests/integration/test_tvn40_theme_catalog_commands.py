"""T-VN-40 retained theme catalog command actual-LOGIN integration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn34-test-only-service-password"


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


async def _rule_hashes(engine: AsyncEngine, *, theme_id: str) -> list[str]:
    async with engine.connect() as connection:
        return list(
            (
                await connection.execute(
                    text(
                        """
                        SELECT encode(x_extension.digest(convert_to(
                          feature.current_curation_rule_input(rule.rule_id)::text,
                          'UTF8'
                        ), 'sha256'), 'hex')
                        FROM feature.curated_source_rules AS rule
                        WHERE rule.theme_id = CAST(:theme_id AS uuid)
                        ORDER BY rule.rule_id
                        """
                    ),
                    {"theme_id": theme_id},
                )
            ).scalars()
        )


async def test_runtime_logins_cannot_bypass_retained_catalog_commands(
    migrated_engine: AsyncEngine,
) -> None:
    """단일 service LOGIN은 catalog read만 가능하고 raw writer는 모두 42501이다.

    ADR-100 이전에는 API/Dagster 두 login으로 각각 돌았다. 하나로 합쳐졌으므로 한 번만
    돈다 — 같은 이름을 두 번 도는 것은 순회처럼 보이는 중복일 뿐이다.
    """

    for login in ("ktm_feature_service",):
        runtime = _runtime_engine(migrated_engine, login=login)
        try:
            async with runtime.connect() as connection:
                for relation in (
                    "curated_themes",
                    "curated_sources",
                    "curated_source_rules",
                ):
                    for statement in (
                        f"INSERT INTO feature.{relation} DEFAULT VALUES",
                        f"UPDATE feature.{relation} SET updated_at = updated_at WHERE false",
                        f"DELETE FROM feature.{relation} WHERE false",
                    ):
                        transaction = await connection.begin()
                        with pytest.raises(DBAPIError) as denied:
                            await connection.execute(text(statement))
                        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                        await transaction.rollback()
        finally:
            await runtime.dispose()


async def test_theme_commands_separate_display_revision_from_rule_semantics(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    actor = f"admin:tvn40-theme-{suffix}"
    create_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.create"
    )
    patch_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.patch"
    )
    stale_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.patch"
    )
    archive_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.archive"
    )
    provider_patch_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.patch"
    )
    provider_archive_command = await _domain_command(
        migrated_engine, actor=actor, operation="admin.curated-theme.archive"
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_service")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_service")
    try:
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            created = (
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curated_theme_command(
                          :slug, 'Theme display', 'before', 'test', 'admin_only',
                          '{}'::jsonb, :command_id, :actor, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": create_command,
                        "slug": f"theme-{suffix}",
                    },
                )
            ).mappings().one()
        theme_id = str(created["o_theme_id"])
        assert int(created["o_theme_revision"]) == 1

        async with migrated_engine.begin() as connection:
            provider_theme_dataset_id = int(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO provider_sync.provider_datasets (
                          provider, dataset_key, display_name, source_kind,
                          is_active, capabilities
                        ) VALUES (
                          'tvn40-provider-theme', :dataset_key, 'Provider theme owner',
                          'system', true, jsonb_build_object(
                            'schema_version', 1, 'produces', '[]'::jsonb,
                            'extensions', '{}'::jsonb
                          )
                        ) RETURNING provider_dataset_id
                        """
                    ),
                    {"dataset_key": f"provider-theme-{suffix}"},
                )
            )
            provider_theme_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO feature.curated_themes (
                          theme_slug, theme_name, theme_description, theme_group,
                          default_curated, visibility, metadata, owner_kind,
                          owner_provider_dataset_id
                        ) VALUES (
                          :slug, 'provider theme', '', 'test', false,
                          'admin_only', '{}'::jsonb, 'provider_dataset', :dataset_id
                        ) RETURNING theme_id
                        """
                    ),
                    {
                        "dataset_id": provider_theme_dataset_id,
                        "slug": f"provider-theme-{suffix}",
                    },
                )
            )
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as forbidden_owner:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_theme_command(
                          CAST(:theme_id AS uuid), 1, :slug, 'provider theme',
                          '', 'test', 'admin_only', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": provider_patch_command,
                        "slug": f"provider-theme-{suffix}",
                        "theme_id": provider_theme_id,
                    },
                )
            assert getattr(forbidden_owner.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as forbidden_archive:
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curated_theme_command(
                          CAST(:theme_id AS uuid), 1, :command_id,
                          'operator_retired', :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": provider_archive_command,
                        "theme_id": provider_theme_id,
                    },
                )
            assert getattr(forbidden_archive.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()

        async with migrated_engine.begin() as connection:
            dataset_id = int(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO provider_sync.provider_datasets (
                          provider, dataset_key, display_name, source_kind,
                          is_active, capabilities
                        ) VALUES (
                          'tvn40-theme', :dataset_key, 'Theme source', 'manual',
                          true, jsonb_build_object(
                            'schema_version', 1,
                            'produces', '[]'::jsonb,
                            'extensions', '{}'::jsonb
                          )
                        ) RETURNING provider_dataset_id
                        """
                    ),
                    {"dataset_key": f"theme-{suffix}"},
                )
            )
            source_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO feature.curated_sources (
                          provider_dataset_id, source_name, source_kind,
                          provider_status
                        ) VALUES (
                          :dataset_id, 'Theme source', 'manual', 'implemented'
                        ) RETURNING source_id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
            )

        for priority in (1, 2):
            command_id = await _domain_command(
                migrated_engine,
                actor=actor,
                operation="admin.curated-source-rule.create",
            )
            async with api.begin() as connection:
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                )
                await connection.execute(
                    text(
                        """
                        CALL feature.create_curated_source_rule_command(
                          CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                          NULL, NULL, '{}'::jsonb, NULL, 'candidate', :priority,
                          true, '{}'::jsonb, :command_id, :actor,
                          NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": command_id,
                        "priority": priority,
                        "source_id": source_id,
                        "theme_id": theme_id,
                    },
                )

        before_hashes = await _rule_hashes(migrated_engine, theme_id=theme_id)
        assert len(before_hashes) == 2
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            patched = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_theme_command(
                          CAST(:theme_id AS uuid), 1, :slug, 'Theme display',
                          'after', 'test', 'admin_only',
                          '{"display_note":"changed"}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": patch_command,
                        "slug": f"theme-{suffix}",
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        assert int(patched["o_theme_revision"]) == 2
        assert int(patched["o_generation_count"]) == 0
        assert await _rule_hashes(migrated_engine, theme_id=theme_id) == before_hashes

        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_theme_command(
                          CAST(:theme_id AS uuid), 1, :slug, 'Theme display',
                          'stale', 'test', 'admin_only', '{}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": stale_command,
                        "slug": f"theme-{suffix}",
                        "theme_id": theme_id,
                    },
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            archived = (
                await connection.execute(
                    text(
                        """
                        CALL feature.archive_curated_theme_command(
                          CAST(:theme_id AS uuid), 2, :command_id,
                          'operator_retired', :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "actor": actor,
                        "command_id": archive_command,
                        "theme_id": theme_id,
                    },
                )
            ).mappings().one()
        assert int(archived["o_theme_revision"]) == 3
        assert int(archived["o_generation_count"]) == 2
        assert await _rule_hashes(migrated_engine, theme_id=theme_id) != before_hashes

        async with migrated_engine.connect() as connection:
            assert int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM ops.curation_rule_reconcile_operations AS operation
                        JOIN feature.curated_source_rules AS rule
                          ON rule.rule_id = operation.rule_id
                        WHERE rule.theme_id = CAST(:theme_id AS uuid)
                        """
                    ),
                    {"theme_id": theme_id},
                )
            ) == 4
        # ADR-100: LOGIN이 하나뿐이라 `session_user`로는 "다른 쪽은 못 한다"를 못 잰다 —
        # 통합 login은 admin/provider executor 양쪽의 inheriting member라 두 술어가 같은
        # 값이 된다. executor 층은 ADR-100이 건드리지 않았으므로 그 층에서 잰다: 이
        # procedure의 grant는 admin executor 하나뿐이어야 하고 적재 쪽으로 새면 안 된다.
        # 양성 대조(admin_side)가 없으면 grant가 통째로 사라진 경우도 초록이 된다.
        async with dagster.connect() as connection:
            grantees = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          has_function_privilege(
                            'ktm_curation_provider_executor', oid, 'EXECUTE'
                          ) AS provider_side,
                          has_function_privilege(
                            'ktm_curation_admin_executor', oid, 'EXECUTE'
                          ) AS admin_side
                        FROM pg_catalog.pg_proc
                        WHERE pronamespace = 'feature'::regnamespace
                          AND proname = 'patch_curated_theme_command'
                        """
                    )
                )
            ).mappings().one()
            assert grantees == {"provider_side": False, "admin_side": True}
    finally:
        await api.dispose()
        await dagster.dispose()
