"""T-VN-40A curation receipt/candidate/audit trust-boundary integration."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_NEW_RELATIONS = (
    "ops.curation_cutover_identity_mappings",
    "ops.curation_rule_reconcile_operations",
    "ops.curation_rule_reconcile_scope_members",
    "feature.theme_candidate_generations",
    "feature.theme_candidate_generation_observations",
    "feature.theme_feature_candidates",
    "feature.theme_feature_candidate_transitions",
)


async def test_tvn40_receipt_spine_has_exact_revision_and_scope_columns(
    migrated_session: AsyncSession,
) -> None:
    """expand migration은 nullable legacy ownership과 immutable receipt proof를 만든다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT table_schema, table_name, column_name, is_nullable
                FROM information_schema.columns
                WHERE (table_schema, table_name, column_name) IN (
                  ('feature','curated_themes','row_revision'),
                  ('feature','curated_themes','owner_kind'),
                  ('feature','curated_sources','observation_revision'),
                  ('feature','curated_source_rules','row_revision'),
                  ('feature','curated_source_rules','owner_provider_dataset_id'),
                  ('feature','curation_collections','row_revision'),
                  ('feature','curation_items','row_revision'),
                  ('ops','curation_rule_reconcile_operations','operation_kind'),
                  ('ops','curation_rule_reconcile_operations','scope_member_count'),
                  ('ops','curation_rule_reconcile_operations','scope_members_hash')
                )
                ORDER BY table_schema, table_name, column_name
                """
            )
        )
    ).all()
    assert len(rows) == 10
    nullable = {(row.table_name, row.column_name): row.is_nullable for row in rows}
    assert nullable[("curated_themes", "owner_kind")] == "YES"
    assert nullable[("curated_source_rules", "owner_provider_dataset_id")] == "YES"
    assert nullable[("curation_rule_reconcile_operations", "operation_kind")] == "NO"
    assert nullable[("curation_rule_reconcile_operations", "scope_member_count")] == "NO"
    assert nullable[("curation_rule_reconcile_operations", "scope_members_hash")] == "NO"

    revision_shape = await migrated_session.scalar(
        text(
            """
            SELECT pg_get_constraintdef(con.oid)
            FROM pg_catalog.pg_constraint AS con
            JOIN pg_catalog.pg_class AS relation ON relation.oid = con.conrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'ops'
              AND relation.relname = 'curation_rule_reconcile_operations'
              AND con.conname = 'ck_curation_rule_reconcile_operation_revision_shape'
            """
        )
    )
    assert revision_shape is not None
    assert "operation_kind = 'create'::text" in revision_shape
    assert "before_rule_revision IS NULL" in revision_shape
    assert "operation_kind = ANY" in revision_shape


async def test_tvn40_owner_shape_constraints_are_validated_at_head(
    migrated_session: AsyncSession,
) -> None:
    """expand용 NOT VALID owner fence를 최종 head에는 남기지 않는다."""

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT relation.relname, constraint_.conname,
                       constraint_.convalidated
                FROM pg_catalog.pg_constraint AS constraint_
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = constraint_.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'feature'
                  AND (relation.relname, constraint_.conname) IN (
                    ('curated_themes', 'ck_curated_themes_owner_shape'),
                    ('curated_source_rules', 'ck_curated_source_rules_owner_shape')
                  )
                ORDER BY relation.relname
                """
            )
        )
    ).all()
    assert rows == [
        ("curated_source_rules", "ck_curated_source_rules_owner_shape", True),
        ("curated_themes", "ck_curated_themes_owner_shape", True),
    ]


async def test_tvn40_relations_are_closed_to_runtime_and_owned_by_schema_owner(
    migrated_session: AsyncSession,
) -> None:
    """새 relation은 runtime broad ops fallback과 table-owner trigger bypass를 모두 피한다."""

    owners = dict(
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT namespace.nspname || '.' || relation.relname,
                           owner.rolname
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_roles AS owner ON owner.oid = relation.relowner
                    WHERE namespace.nspname || '.' || relation.relname
                      = ANY(CAST(:relations AS text[]))
                    ORDER BY 1
                    """
                ),
                {"relations": list(_NEW_RELATIONS)},
            )
        ).all()
    )
    assert owners == {relation: "ktm_feature_schema_owner" for relation in _NEW_RELATIONS}

    for relation in _NEW_RELATIONS:
        assert not await migrated_session.scalar(
            text("SELECT has_table_privilege('ktm_feature_runtime', :relation, 'SELECT')"),
            {"relation": relation},
        )
        assert not await migrated_session.scalar(
            text("SELECT has_table_privilege('ktm_feature_runtime', :relation, 'INSERT')"),
            {"relation": relation},
        )

    assert await migrated_session.scalar(
        text(
            "SELECT has_table_privilege('ktm_curation_command_owner', "
            "'feature.theme_feature_candidates', 'UPDATE')"
        )
    )
    assert not await migrated_session.scalar(
        text(
            "SELECT has_table_privilege('ktm_curation_command_owner', "
            "'feature.theme_feature_candidates', 'DELETE')"
        )
    )
    assert await migrated_session.scalar(
        text(
            "SELECT has_table_privilege('ktm_curation_audit_writer', "
            "'feature.theme_feature_candidate_transitions', 'INSERT')"
        )
    )
    assert await migrated_session.scalar(
        text(
            "SELECT has_table_privilege('ktm_curation_audit_writer', "
            "'feature.theme_feature_candidate_transitions', 'SELECT')"
        )
    )
    assert not await migrated_session.scalar(
        text(
            "SELECT has_table_privilege('ktm_curation_command_owner', "
            "'feature.theme_feature_candidate_transitions', 'INSERT')"
        )
    )


async def test_tvn40_transition_audit_rejects_owner_update(
    migrated_session: AsyncSession,
) -> None:
    """audit writer도 append 뒤 transition row를 고치거나 지울 수 없다."""

    command_id = await migrated_session.scalar(
        text(
            """
            INSERT INTO ops.domain_commands (
              actor, operation, idempotency_key, request_fingerprint
            ) VALUES (
              'admin:test', 'admin.theme-feature-candidate.reject',
              x_extension.gen_random_uuid(), repeat('c', 64)
            )
            RETURNING command_id
            """
        )
    )
    assert command_id is not None
    await migrated_session.execute(text("SET ROLE ktm_curation_audit_writer"))
    try:
        transition_id = await migrated_session.scalar(
            text(
                """
                INSERT INTO feature.theme_feature_candidate_transitions (
                  candidate_id, from_feature_id, to_feature_id, rule_id,
                  source_entity_key, from_review_state, to_review_state,
                  from_eligibility_present, to_eligibility_present,
                  from_disposition, to_disposition, transition_kind,
                  candidate_row_revision, rule_row_revision, rule_input_hash,
                  candidate_input_hash, actor, reason_code, command_id,
                  invoker_role, candidate_procedure_definer, audit_writer_definer
                ) VALUES (
                      '00000000-0000-4000-8000-000000000040'::uuid,
                      'feature:old', 'feature:new',
                      '00000000-0000-4000-8000-000000000041'::uuid,
                      'entity:test', 'open', 'rejected',
                  true, true, 'active', 'active', 'admin_reject', 1, 1,
                  repeat('a', 64), repeat('b', 64), 'admin:test', 'reviewed',
                  :command_id,
                  'ktm_feature_api_runtime', 'ktm_curation_command_owner',
                  'ktm_curation_audit_writer'
                )
                RETURNING transition_id
                """
            ),
            {"command_id": command_id},
        )
        assert transition_id is not None
        savepoint = await migrated_session.begin_nested()
        with pytest.raises(DBAPIError) as exc_info:
            await migrated_session.execute(
                text(
                    "UPDATE feature.theme_feature_candidate_transitions "
                    "SET reason_code = 'forged' WHERE transition_id = :transition_id"
                ),
                {"transition_id": transition_id},
            )
        assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"
        await savepoint.rollback()
    finally:
        await migrated_session.rollback()
