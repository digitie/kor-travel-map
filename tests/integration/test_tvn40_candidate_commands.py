"""T-VN-40 typed candidate command actual-LOGIN integration."""

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


async def _seed_candidate(engine: AsyncEngine) -> dict[str, object]:
    suffix = uuid4().hex
    feature_id = f"feature:tvn40-candidate-{suffix}"
    source_entity_key = f"entity:tvn40-candidate-{suffix}"
    source_record_key = f"record:tvn40-candidate-{suffix}"
    actor = f"admin:tvn40-{suffix}"
    async with engine.begin() as connection:
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind,
                      is_active, capabilities
                    ) VALUES (
                      'tvn40-test', :dataset_key, 'T-VN-40 candidate test',
                      'system', true,
                      jsonb_build_object(
                        'schema_version', 1,
                        'produces', '[]'::jsonb,
                        'extensions', '{}'::jsonb
                      )
                    )
                    RETURNING provider_dataset_id
                    """
                ),
                {"dataset_key": f"candidate-{suffix}"},
            )
        )
        seed = {
            "dataset_id": dataset_id,
            "feature_id": feature_id,
            "lineage_key": f"lineage-{suffix}",
            "source_entity_key": source_entity_key,
            "source_record_key": source_record_key,
            "source_hash": "a" * 64,
            "suffix": suffix,
        }
        for statement in (
            """
            INSERT INTO provider_sync.source_entities (
              source_entity_key, provider_dataset_id, source_entity_type,
              source_entity_id, first_seen_at, last_seen_at
            ) VALUES (
              :source_entity_key, :dataset_id, 'candidate-test', :suffix,
              clock_timestamp(), clock_timestamp()
            )
            """,
            """
            INSERT INTO provider_sync.source_records (
              source_record_key, source_entity_key, raw_data,
              raw_payload_hash, fetched_at
            ) VALUES (
              :source_record_key, :source_entity_key,
              jsonb_build_object('name', 'typed candidate'),
              :source_hash, clock_timestamp()
            )
            """,
            """
            INSERT INTO provider_sync.source_entity_heads (
              source_entity_key, current_source_record_key, observed_at, lineage_key
            ) VALUES (
              :source_entity_key, :source_record_key, clock_timestamp(), :lineage_key
            )
            """,
            """
            INSERT INTO feature.features (
              feature_id, kind, name, category, coord, address,
              marker_icon, marker_color
            ) VALUES (
              :feature_id, 'place', 'typed candidate', '01070100',
              x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(126.9780, 37.5665), 4326
              ),
              '{}'::jsonb, 'place', 'P-01'
            )
            """,
            """
            INSERT INTO provider_sync.source_links (
              feature_id, source_entity_key, source_role, match_method, confidence
            ) VALUES (
              :feature_id, :source_entity_key, 'primary', 'exact', 100
            )
            """,
        ):
            await connection.execute(text(statement), seed)
        theme_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                      theme_slug, theme_name, theme_description, theme_group,
                      default_curated, visibility, metadata
                    ) VALUES (
                      :slug, 'typed candidate theme', '', 'test', false,
                      'admin_only', '{}'::jsonb
                    ) RETURNING theme_id
                    """
                ),
                {"slug": f"tvn40-candidate-{suffix}"},
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
                      :dataset_id, 'typed candidate source', 'internal',
                      'unknown', 'implemented', '{}'::jsonb
                    ) RETURNING source_id
                    """
                ),
                {"dataset_id": dataset_id},
            )
        )
        rule_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_source_rules (
                      theme_id, source_id, region_scope, default_action,
                      priority, enabled, metadata
                    ) VALUES (
                      CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                      '{}'::jsonb, 'candidate', 10, true, '{}'::jsonb
                    ) RETURNING rule_id
                    """
                ),
                {"theme_id": theme_id, "source_id": source_id},
            )
        )
        candidate_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.theme_feature_candidates (
                      rule_id, source_entity_key, feature_id, source_record_key,
                      rule_row_revision, rule_input_hash, source_record_hash,
                      candidate_input_hash, review_state, eligibility_present,
                      disposition, rank_score, match_evidence
                    ) VALUES (
                      CAST(:rule_id AS uuid), :source_entity_key, :feature_id,
                      :source_record_key, 1, repeat('b', 64), repeat('a', 64),
                      repeat('c', 64), 'open', true, 'active', 10,
                      jsonb_build_object('schema_version', 1)
                    ) RETURNING candidate_id
                    """
                ),
                {
                    "feature_id": feature_id,
                    "rule_id": rule_id,
                    "source_entity_key": source_entity_key,
                    "source_record_key": source_record_key,
                },
            )
        )
        command_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, 'admin.theme-feature-candidate.reject',
                      x_extension.gen_random_uuid(), repeat('d', 64)
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor},
            )
        )
    return {
        "actor": actor,
        "candidate_id": candidate_id,
        "command_id": command_id,
        "feature_id": feature_id,
    }


async def test_admin_runtime_reject_is_atomic_and_audited(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(migrated_engine)
    runtime = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with runtime.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            result = (
                await connection.execute(
                    text(
                        """
                        CALL feature.reject_theme_feature_candidate(
                          CAST(:candidate_id AS uuid), 1, :command_id,
                          'not_relevant', :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    seeded,
                )
            ).mappings().one()
        assert str(result["o_candidate_id"]) == seeded["candidate_id"]
        assert int(result["o_candidate_revision"]) == 2
        assert int(result["o_transition_id"]) > 0

        async with migrated_engine.connect() as connection:
            candidate = (
                await connection.execute(
                    text(
                        """
                        SELECT review_state, eligibility_present, disposition, row_revision
                        FROM feature.theme_feature_candidates
                        WHERE candidate_id = CAST(:candidate_id AS uuid)
                        """
                    ),
                    seeded,
                )
            ).one()
            transition = (
                await connection.execute(
                    text(
                        """
                        SELECT transition_kind, from_review_state, to_review_state,
                               command_id, actor, reason_code, invoker_role,
                               candidate_procedure_definer, audit_writer_definer
                        FROM feature.theme_feature_candidate_transitions
                        WHERE transition_id = :transition_id
                        """
                    ),
                    {"transition_id": result["o_transition_id"]},
                )
            ).one()
        assert candidate == ("rejected", True, "active", 2)
        assert transition == (
            "admin_reject",
            "open",
            "rejected",
            seeded["command_id"],
            seeded["actor"],
            "not_relevant",
            "ktm_feature_api_runtime",
            "ktm_curation_command_owner",
            "ktm_curation_audit_writer",
        )
    finally:
        await runtime.dispose()


async def test_candidate_command_acl_and_cas_fail_closed(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(migrated_engine)
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with api.connect() as connection:
            audit_acl = (
                await connection.execute(
                    text(
                        """
                        SELECT session_user::text, current_user::text,
                               pg_get_userbyid(proc.proowner), proc.proacl,
                               has_function_privilege(
                                 session_user,
                                 to_regprocedure(:audit_signature),
                                 'EXECUTE'
                               )
                        FROM pg_catalog.pg_proc AS proc
                        WHERE proc.oid = to_regprocedure(:audit_signature)
                        """
                    ),
                    {
                        "audit_signature": (
                            "feature.append_theme_feature_candidate_transition("
                            "uuid,text,text,uuid,text,text,text,boolean,boolean,text,text,"
                            "uuid,text,bigint,bigint,text,text,uuid,bigint,text,text,uuid,"
                            "uuid,bigint,text,text,jsonb)"
                        )
                    },
                )
            ).one()
            assert not audit_acl[4], audit_acl
            await connection.rollback()
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.reject_theme_feature_candidate(
                          CAST(:candidate_id AS uuid), 2, :command_id,
                          'stale', :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    seeded,
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        async with dagster.connect() as connection:
            assert not await connection.scalar(
                text(
                    """
                    SELECT has_function_privilege(
                      session_user,
                      'feature.reject_theme_feature_candidate(uuid,bigint,bigint,text,text)'::regprocedure,
                      'EXECUTE'
                    )
                    """
                )
            )
    finally:
        await api.dispose()
        await dagster.dispose()
