"""T-VN-40 typed candidate command actual-LOGIN integration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra import curation_candidate_repo
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
    reconcile_dagster_feature_run,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
    set_pipeline_cancellation_run_result,
    transition_pipeline_cancellation_member,
)

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _current_provider_curation_input_set(
    engine: AsyncEngine, *, provider_dataset_id: int
) -> dict[str, object]:
    """sealed command의 caller payload를 만들기 위한 관리자-side test probe."""
    async with engine.connect() as connection:
        return dict(
            (
                await connection.execute(
                    text(
                        """
                        SELECT input_member_count, source_input_set_hash
                        FROM feature.current_provider_curation_input_set(:dataset_id)
                        """
                    ),
                    {"dataset_id": provider_dataset_id},
                )
            )
            .mappings()
            .one()
        )


async def _seed_candidate(
    engine: AsyncEngine,
    *,
    operation: str = "admin.theme-feature-candidate.reject",
    create_candidate: bool = True,
    provider: str = "tvn40-test",
    dataset_key: str | None = None,
    place_kind: str = "attraction",
    place_payload: str = "{}",
) -> dict[str, object]:
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
                    WITH inserted AS (
                      INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                      ) VALUES (
                        :provider, :dataset_key, 'T-VN-40 candidate test',
                        'system', true,
                        jsonb_build_object(
                          'schema_version', 1,
                          'produces', '[]'::jsonb,
                          'extensions', '{}'::jsonb
                        )
                      ) ON CONFLICT (provider, dataset_key) DO NOTHING
                      RETURNING provider_dataset_id
                    )
                    SELECT provider_dataset_id FROM inserted
                    UNION ALL
                    SELECT provider_dataset_id
                    FROM provider_sync.provider_datasets
                    WHERE provider = :provider AND dataset_key = :dataset_key
                    LIMIT 1
                    """
                ),
                {
                    "dataset_key": dataset_key or f"candidate-{suffix}",
                    "provider": provider,
                },
            )
        )
        seed = {
            "dataset_id": dataset_id,
            "feature_id": feature_id,
            "lineage_key": f"lineage-{suffix}",
            "source_entity_key": source_entity_key,
            "source_record_key": source_record_key,
            "source_hash": "a" * 64,
            "place_payload": place_payload,
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
        await connection.execute(
            text(
                """
                INSERT INTO feature.feature_places (
                  feature_id, feature_uuid, kind, place_kind,
                  facility_info, reviews_link, payload
                )
                SELECT
                  feature_id, feature_uuid, kind, :place_kind,
                  jsonb_build_object('wheelchair', true), '{}'::jsonb,
                  CAST(:place_payload AS jsonb)
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {**seed, "place_kind": place_kind},
        )
        theme_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                      theme_slug, theme_name, theme_description, theme_group,
                      default_curated, visibility, metadata, owner_kind
                    ) VALUES (
                      :slug, 'typed candidate theme', '', 'test', false,
                      'admin_only', '{}'::jsonb, 'operator'
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
                    WITH inserted AS (
                      INSERT INTO feature.curated_sources (
                        provider_dataset_id, source_name, source_kind,
                        update_cycle, provider_status, metadata
                      ) VALUES (
                        :dataset_id, 'typed candidate source', 'internal',
                        'unknown', 'implemented', '{}'::jsonb
                      ) ON CONFLICT (provider_dataset_id) DO NOTHING
                      RETURNING source_id
                    )
                    SELECT source_id FROM inserted
                    UNION ALL
                    SELECT source_id FROM feature.curated_sources
                    WHERE provider_dataset_id = :dataset_id
                    LIMIT 1
                    """
                ),
                {"dataset_id": dataset_id},
            )
        )
        collection_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                      collection_key, theme_id, source_id, title, status,
                      visibility, metadata
                    ) VALUES (
                      :collection_key, CAST(:theme_id AS uuid),
                      CAST(:source_id AS uuid), 'typed candidate collection',
                      'draft', 'admin_only', '{}'::jsonb
                    ) RETURNING collection_id
                    """
                ),
                {
                    "collection_key": f"tvn40-candidate-{suffix}",
                    "source_id": source_id,
                    "theme_id": theme_id,
                },
            )
        )
        rule_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_source_rules (
                      theme_id, source_id, region_scope, default_action,
                      priority, enabled, metadata, owner_kind
                    ) VALUES (
                      CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                      '{}'::jsonb, 'candidate', 10, true, '{}'::jsonb, 'operator'
                    ) RETURNING rule_id
                    """
                ),
                {"theme_id": theme_id, "source_id": source_id},
            )
        )
        candidate_id: str | None = None
        if create_candidate:
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
            await connection.execute(
                text(
                    """
                UPDATE feature.theme_feature_candidates AS candidate
                SET rule_row_revision = snapshot.rule_row_revision,
                    rule_input_hash = snapshot.rule_input_hash,
                    source_record_key = snapshot.source_record_key,
                    source_record_hash = snapshot.source_record_hash,
                    candidate_input_hash = snapshot.candidate_input_hash,
                    match_evidence = snapshot.match_evidence
                FROM feature.current_theme_candidate_snapshot(
                  CAST(:rule_id AS uuid), :source_entity_key, :feature_id
                ) AS snapshot
                WHERE candidate.candidate_id = CAST(:candidate_id AS uuid)
                    """
                ),
                {
                    "candidate_id": candidate_id,
                    "feature_id": feature_id,
                    "rule_id": rule_id,
                    "source_entity_key": source_entity_key,
                },
            )
        command_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation,
                      x_extension.gen_random_uuid(), repeat('d', 64)
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation},
            )
        )
    return {
        "actor": actor,
        "candidate_id": candidate_id,
        "command_id": command_id,
        "collection_id": collection_id,
        "dataset_id": dataset_id,
        "feature_id": feature_id,
        "rule_id": rule_id,
        "source_entity_key": source_entity_key,
        "source_record_key": source_record_key,
        "suffix": suffix,
    }


def _scope_hash(members: list[tuple[str, str, str | None, str | None]]) -> str:
    payload = b"".join(
        kind.encode()
        + b"\0"
        + key.encode()
        + b"\0"
        + (before or "").encode()
        + b"\0"
        + (after or "").encode()
        + b"\n"
        for kind, key, before, after in sorted(members)
    )
    return hashlib.sha256(payload).hexdigest()


async def _seed_rule_reconcile_operation(
    engine: AsyncEngine,
    seeded: dict[str, object],
    *,
    include_feature: bool = True,
) -> str:
    async with engine.begin() as connection:
        snapshot = (
            await connection.execute(
                text(
                    """
                    SELECT rule_input_hash, candidate_input_hash
                    FROM feature.current_theme_candidate_snapshot(
                      CAST(:rule_id AS uuid), :source_entity_key, :feature_id
                    )
                    """
                ),
                seeded,
            )
        ).one()
        members = [
            (
                "source_entity",
                str(seeded["source_entity_key"]),
                None,
                "a" * 64,
            )
        ]
        if include_feature:
            members.append(
                (
                    "feature",
                    str(seeded["feature_id"]),
                    None,
                    str(snapshot.candidate_input_hash),
                )
            )
        operation_id = str(uuid4())
        await connection.execute(
            text(
                """
                INSERT INTO ops.curation_rule_reconcile_operations (
                  operation_id, rule_id, operation_kind,
                  before_rule_revision, after_rule_revision,
                  before_rule_input_hash, after_rule_input_hash,
                  command_id, system_operation_key, actor,
                  scope_member_count, scope_members_hash
                ) VALUES (
                  CAST(:operation_id AS uuid), CAST(:rule_id AS uuid), 'create',
                  NULL, 1, NULL, :rule_input_hash,
                  :command_id, NULL, :actor, :member_count, :members_hash
                )
                """
            ),
            {
                **seeded,
                "operation_id": operation_id,
                "rule_input_hash": snapshot.rule_input_hash,
                "member_count": len(members),
                "members_hash": _scope_hash(members),
            },
        )
        for kind, key, before, after in members:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.curation_rule_reconcile_scope_members (
                      operation_id, member_kind, member_key,
                      before_identity_hash, after_identity_hash
                    ) VALUES (
                      CAST(:operation_id AS uuid), :kind, :key, :before, :after
                    )
                    """
                ),
                {
                    "after": after,
                    "before": before,
                    "key": key,
                    "kind": kind,
                    "operation_id": operation_id,
                },
            )
    return operation_id


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
            privileges = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          has_function_privilege(
                            session_user,
                            'feature.reject_theme_feature_candidate(uuid,bigint,bigint,text,text)'::regprocedure,
                            'EXECUTE'
                          ),
                          has_function_privilege(
                            session_user,
                            'feature.promote_theme_feature_candidate(uuid,uuid,text,text,text,text,text,text,integer,text,text,text,bigint,bigint,bigint,bigint,text,text)'::regprocedure,
                            'EXECUTE'
                          )
                        """
                    )
                )
            ).one()
            assert privileges == (False, False)
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_admin_runtime_promotion_is_one_trusted_membership_transaction(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.theme-feature-candidate.promote",
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with migrated_engine.begin() as connection:
            metadata_command_id = int(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO ops.domain_commands (
                          actor, operation, idempotency_key, request_fingerprint
                        ) VALUES (
                          :actor, 'admin.curated-source-rule.patch',
                          x_extension.gen_random_uuid(), repeat('e', 64)
                        ) RETURNING command_id
                        """
                    ),
                    seeded,
                )
            )

        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            metadata_only = (
                await connection.execute(
                    text(
                        """
                        CALL feature.patch_curated_source_rule_command(
                          CAST(:rule_id AS uuid), 1, NULL, NULL, '{}'::jsonb,
                          NULL, 'candidate', 10, true,
                          '{"display_note":"operator-only"}'::jsonb,
                          :command_id, :actor, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seeded, "command_id": metadata_command_id},
                )
            ).mappings().one()
        assert int(metadata_only["o_rule_revision"]) == 2
        assert metadata_only["o_generation_id"] is None

        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            result = (
                await connection.execute(
                    text(
                        """
                        CALL feature.promote_theme_feature_candidate(
                          CAST(:candidate_id AS uuid), CAST(:collection_id AS uuid),
                          'external-item-1', 'primary', '승격 장소', '서울',
                          '승격 제목', '승격 요약', 10, 'primary_stop', 'allowed',
                          'included', 1, 1, NULL, :command_id, 'admin_review',
                          :actor, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    seeded,
                )
            ).mappings().one()

        assert str(result["o_candidate_id"]) == seeded["candidate_id"]
        assert int(result["o_candidate_revision"]) == 2
        assert int(result["o_curation_item_revision"]) == 1
        assert int(result["o_transition_id"]) > 0

        async with migrated_engine.connect() as connection:
            item = (
                await connection.execute(
                    text(
                        """
                        SELECT item.feature_id, item.source_record_key, item.status,
                               item.row_revision, decision.decision_kind,
                               decision.match_basis, decision.resolver_version,
                               decision.actor, decision.evidence ->> 'candidate_id'
                        FROM feature.curation_items AS item
                        JOIN feature.curation_link_decisions AS decision
                          ON decision.decision_id = item.accepted_link_decision_id
                         AND decision.curation_item_id = item.curation_item_id
                         AND decision.feature_id = item.feature_id
                        WHERE item.curation_item_id = CAST(:curation_item_id AS uuid)
                        """
                    ),
                    {"curation_item_id": result["o_curation_item_id"]},
                )
            ).one()
            transition = (
                await connection.execute(
                    text(
                        """
                        SELECT transition_kind, from_review_state, to_review_state,
                               collection_id::text, curation_item_id::text,
                               command_id, actor
                        FROM feature.theme_feature_candidate_transitions
                        WHERE transition_id = :transition_id
                        """
                    ),
                    {"transition_id": result["o_transition_id"]},
                )
            ).one()
        assert item == (
            seeded["feature_id"],
            seeded["source_record_key"],
            "included",
            1,
            "accepted",
            "admin_review",
            "tvn40-candidate-promotion-v1",
            seeded["actor"],
            seeded["candidate_id"],
        )
        assert transition == (
            "admin_promote",
            "open",
            "promoted",
            seeded["collection_id"],
            str(result["o_curation_item_id"]),
            seeded["command_id"],
            seeded["actor"],
        )
    finally:
        await api.dispose()


async def test_promotion_stale_collection_rolls_back_every_surface(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.theme-feature-candidate.promote",
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.promote_theme_feature_candidate(
                          CAST(:candidate_id AS uuid), CAST(:collection_id AS uuid),
                          'external-item-1', 'primary', '승격 장소', NULL,
                          NULL, NULL, 0, 'nearby_option', 'manual_review',
                          'candidate', 1, 2, NULL, :command_id, 'admin_review',
                          :actor, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    seeded,
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        async with migrated_engine.connect() as connection:
            assert await connection.scalar(
                text(
                    """
                    SELECT (review_state, row_revision) = ('open', 1)
                    FROM feature.theme_feature_candidates
                    WHERE candidate_id = CAST(:candidate_id AS uuid)
                    """
                ),
                seeded,
            )
            assert (
                await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_items
                        WHERE collection_id = CAST(:collection_id AS uuid)
                        """
                    ),
                    seeded,
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.theme_feature_candidate_transitions
                        WHERE candidate_id = CAST(:candidate_id AS uuid)
                        """
                    ),
                    seeded,
                )
                == 0
            )
    finally:
        await api.dispose()


async def test_promotion_rejects_stale_typed_feature_detail(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.theme-feature-candidate.promote",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE feature.feature_places
                SET facility_info = jsonb_build_object('wheelchair', false)
                WHERE feature_id = :feature_id
                """
            ),
            seeded,
        )

    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as stale:
                await connection.execute(
                    text(
                        """
                        CALL feature.promote_theme_feature_candidate(
                          CAST(:candidate_id AS uuid), CAST(:collection_id AS uuid),
                          'external-item-1', 'primary', '승격 장소', NULL,
                          NULL, NULL, 0, 'nearby_option', 'manual_review',
                          'candidate', 1, 1, NULL, :command_id, 'admin_review',
                          :actor, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    seeded,
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            assert "candidate proof is stale" in str(stale.value.orig)
            await transaction.rollback()

        async with migrated_engine.connect() as connection:
            state = (
                await connection.execute(
                    text(
                        """
                        SELECT candidate.review_state, candidate.row_revision,
                               count(item.curation_item_id),
                               count(transition.transition_id)
                        FROM feature.theme_feature_candidates AS candidate
                        LEFT JOIN feature.curation_items AS item
                          ON item.collection_id = CAST(:collection_id AS uuid)
                        LEFT JOIN feature.theme_feature_candidate_transitions AS transition
                          ON transition.candidate_id = candidate.candidate_id
                        WHERE candidate.candidate_id = CAST(:candidate_id AS uuid)
                        GROUP BY candidate.review_state, candidate.row_revision
                        """
                    ),
                    seeded,
                )
            ).one()
        assert state == ("open", 1, 0, 0)
    finally:
        await api.dispose()


async def test_notice_candidate_detail_excludes_internal_validity_range(
    migrated_engine: AsyncEngine,
) -> None:
    """admin candidate detail은 generated 내부 range를 공개 shape에 넣지 않는다."""
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.theme-feature-candidate.reject",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM feature.feature_places WHERE feature_id = :feature_id"
            ),
            seeded,
        )
        await connection.execute(
            text(
                "UPDATE feature.features SET kind = 'notice' "
                "WHERE feature_id = :feature_id"
            ),
            seeded,
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.feature_notices (
                    feature_id, feature_uuid, kind, notice_type, severity,
                    valid_start_time, valid_end_time, source_agency, payload
                )
                SELECT feature_id, feature_uuid, kind, 'traffic', 2,
                       CAST(:valid_start AS timestamptz),
                       CAST(:valid_end AS timestamptz),
                       'test-agency', '{}'::jsonb
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {
                **seeded,
                "valid_start": datetime(2026, 8, 1, tzinfo=UTC),
                "valid_end": datetime(2026, 8, 2, tzinfo=UTC),
            },
        )

    async with async_sessionmaker(migrated_engine, expire_on_commit=False)() as session:
        await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        candidate_utc = await curation_candidate_repo.get_theme_candidate(
            session,
            candidate_id=str(seeded["candidate_id"]),
        )

    async with async_sessionmaker(migrated_engine, expire_on_commit=False)() as session:
        await session.execute(text("SET LOCAL TIME ZONE 'Asia/Seoul'"))
        candidate = await curation_candidate_repo.get_theme_candidate(
            session,
            candidate_id=str(seeded["candidate_id"]),
        )

    assert candidate_utc is not None
    assert candidate is not None
    assert candidate_utc.feature_detail == candidate.feature_detail
    assert candidate.feature_kind == "notice"
    assert candidate.feature_detail["notice_type"] == "traffic"
    assert candidate.feature_detail["valid_start_time"] == "2026-08-01T09:00:00+09:00"
    assert candidate.feature_detail["valid_end_time"] == "2026-08-02T09:00:00+09:00"
    assert "valid_during" not in candidate.feature_detail


async def test_rule_reconcile_generation_is_server_derived_and_replay_safe(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
    )
    operation_id = await _seed_rule_reconcile_operation(migrated_engine, seeded)
    params = {**seeded, "operation_id": operation_id}
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            first = (
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_theme_candidate_generation(
                          CAST(:rule_id AS uuid), 'rule_reconcile', NULL,
                          CAST(:operation_id AS uuid), :command_id, NULL,
                          '{}'::jsonb, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    params,
                )
            ).mappings().one()
        assert int(first["o_observed_candidate_count"]) == 1
        assert int(first["o_eligibility_removed_candidate_count"]) == 0
        assert len(str(first["o_generation_input_set_hash"])) == 64
        assert first["o_replayed"] is False

        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            replay = (
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_theme_candidate_generation(
                          CAST(:rule_id AS uuid), 'rule_reconcile', NULL,
                          CAST(:operation_id AS uuid), :command_id, NULL,
                          '{}'::jsonb, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    params,
                )
            ).mappings().one()
        assert replay["o_generation_id"] == first["o_generation_id"]
        assert replay["o_generation_input_set_hash"] == (
            first["o_generation_input_set_hash"]
        )
        assert replay["o_replayed"] is True

        async with migrated_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT candidate.review_state,
                               candidate.eligibility_present,
                               candidate.disposition,
                               candidate.row_revision,
                               generation.generation_kind,
                               generation.command_id,
                               count(observation.candidate_id),
                               count(transition.transition_id)
                        FROM feature.theme_feature_candidates AS candidate
                        JOIN feature.theme_candidate_generations AS generation
                          ON generation.generation_id = CAST(:generation_id AS uuid)
                        LEFT JOIN feature.theme_candidate_generation_observations AS observation
                          ON observation.generation_id = generation.generation_id
                         AND observation.candidate_id = candidate.candidate_id
                        LEFT JOIN feature.theme_feature_candidate_transitions AS transition
                          ON transition.candidate_id = candidate.candidate_id
                         AND transition.generation_id = generation.generation_id
                        WHERE candidate.rule_id = CAST(:rule_id AS uuid)
                          AND candidate.source_entity_key = :source_entity_key
                          AND candidate.feature_id = :feature_id
                        GROUP BY candidate.review_state,
                                 candidate.eligibility_present,
                                 candidate.disposition,
                                 candidate.row_revision,
                                 generation.generation_kind,
                                 generation.command_id
                        """
                    ),
                    {**seeded, "generation_id": first["o_generation_id"]},
                )
            ).one()
        assert row == (
            "open",
            True,
            "active",
            1,
            "rule_reconcile",
            seeded["command_id"],
            1,
            1,
        )
    finally:
        await api.dispose()


async def test_rule_reconcile_scope_omission_and_cross_executor_fail_closed(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
    )
    operation_id = await _seed_rule_reconcile_operation(
        migrated_engine,
        seeded,
        include_feature=False,
    )
    params = {**seeded, "operation_id": operation_id}
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with api.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as omitted:
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_theme_candidate_generation(
                          CAST(:rule_id AS uuid), 'rule_reconcile', NULL,
                          CAST(:operation_id AS uuid), :command_id, NULL,
                          '{}'::jsonb, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    params,
                )
            assert getattr(omitted.value.orig, "sqlstate", None) == "23514"
            assert "DB-derived scope" in str(omitted.value.orig)
            await transaction.rollback()

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as crossed:
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_theme_candidate_generation(
                          CAST(:rule_id AS uuid), 'rule_reconcile', NULL,
                          CAST(:operation_id AS uuid), :command_id, NULL,
                          '{}'::jsonb, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    params,
                )
            assert getattr(crossed.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()

        async with migrated_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.theme_candidate_generations
                        WHERE reconcile_operation_id = CAST(:operation_id AS uuid)
                        """
                    ),
                    params,
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.theme_feature_candidates
                        WHERE rule_id = CAST(:rule_id AS uuid)
                        """
                    ),
                    params,
                )
                == 0
            )
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_provider_generation_primitives_require_internal_finalizer(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
    )
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with migrated_engine.begin() as connection:
            root_job_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, payload, status, progress, current_stage,
                          dagster_run_id, dataset_membership_mode, trigger_kind,
                          operation_key, dagster_run_status
                        ) VALUES (
                          'provider_feature_load_run', '{}'::jsonb, 'running', 0,
                          'loading', :run_id, 'root', 'schedule', 'load', 'STARTED'
                        ) RETURNING job_id
                        """
                    ),
                    {"run_id": f"tvn40-provider-{seeded['suffix']}"},
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
                seeded,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_dataset_operation_scopes (
                      provider_dataset_id, sync_scope, operation_key, operation_kind
                    ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                    """
                ),
                seeded,
            )
            source_job_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, parent_job_id, payload, status, progress,
                          current_stage, dagster_run_id, dataset_membership_mode,
                          finished_at
                        ) VALUES (
                          'provider_feature_load', CAST(:root_job_id AS uuid),
                          jsonb_build_object('authoritative_snapshot_complete', true),
                          'done', 100, 'completed', :run_id, 'single', clock_timestamp()
                        ) RETURNING job_id
                        """
                    ),
                    {
                        "root_job_id": root_job_id,
                        "run_id": f"tvn40-provider-{seeded['suffix']}",
                    },
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_datasets (
                      job_id, provider_dataset_id, sync_scope, operation_key
                    ) VALUES (
                      CAST(:source_job_id AS uuid), :dataset_id,
                      'dataset_wide', 'load'
                    )
                    """
                ),
                {**seeded, "source_job_id": source_job_id},
            )
            invalid_root_job_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, payload, status, progress, current_stage,
                          dagster_run_id, dataset_membership_mode, trigger_kind,
                          operation_key, dagster_run_status
                        ) VALUES (
                          'provider_feature_load_run', '{}'::jsonb, 'running', 0,
                          'loading', :run_id, 'root', 'schedule', 'load', 'STARTED'
                        ) RETURNING job_id
                        """
                    ),
                    {"run_id": f"tvn40-provider-invalid-{seeded['suffix']}"},
                )
            )
            invalid_source_job_id = str(
                await connection.scalar(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, parent_job_id, payload, status, progress,
                          current_stage, dagster_run_id, dataset_membership_mode,
                          finished_at
                        ) VALUES (
                          'provider_feature_load', CAST(:root_job_id AS uuid),
                          jsonb_build_object('authoritative_snapshot_complete', false),
                          'done', 100, 'completed', :run_id, 'single', clock_timestamp()
                        ) RETURNING job_id
                        """
                    ),
                    {
                        "root_job_id": invalid_root_job_id,
                        "run_id": f"tvn40-provider-invalid-{seeded['suffix']}",
                    },
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.import_job_datasets (
                      job_id, provider_dataset_id, sync_scope, operation_key
                    ) VALUES (
                      CAST(:source_job_id AS uuid), :dataset_id,
                      'dataset_wide', 'load'
                    )
                    """
                ),
                {**seeded, "source_job_id": invalid_source_job_id},
            )
        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as invalid:
                await connection.execute(
                    text(
                        """
                        CALL feature.materialize_theme_candidate_generation(
                          CAST(:rule_id AS uuid), 'provider_full_snapshot',
                          CAST(:source_job_id AS uuid), NULL, NULL, NULL,
                          '{}'::jsonb, NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seeded, "source_job_id": invalid_source_job_id},
                )
            assert getattr(invalid.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(DBAPIError) as observation:
                await connection.execute(
                    text(
                        """
                        CALL feature.refresh_curated_source_observation(
                          :dataset_id, CAST(:source_job_id AS uuid),
                          NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seeded, "source_job_id": invalid_source_job_id},
                )
            assert getattr(observation.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()

        for table_name in (
            "curation_provider_snapshot_receipts",
            "curation_provider_root_receipts",
        ):
            async with dagster.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(DBAPIError) as forged_receipt:
                    await connection.execute(
                        text(f"DELETE FROM ops.{table_name} WHERE false")
                    )
                assert (
                    getattr(forged_receipt.value.orig, "sqlstate", None) == "42501"
                )
                await transaction.rollback()
    finally:
        await dagster.dispose()


@pytest.mark.parametrize("drift_after_seal", [False, True])
async def test_provider_root_success_atomically_observes_generates_and_seals(
    migrated_engine: AsyncEngine,
    drift_after_seal: bool,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
    )
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    run_id = f"tvn40-provider-terminal-{seeded['suffix']}"
    created_at = datetime(2026, 8, 13, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=1)
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                  provider_dataset_id, operation_key, operation_kind,
                  is_enabled, config
                ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
                """
            ),
            seeded,
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                  provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                """
            ),
            seeded,
        )

    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    session_factory = async_sessionmaker(dagster, expire_on_commit=False)
    source_job_id = ""
    try:
        seal = await _current_provider_curation_input_set(
            migrated_engine,
            provider_dataset_id=membership.provider_dataset_id,
        )
        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=created_at,
                engine_started_at=started_at,
                observed_status="STARTED",
            )
            finished = await finish_dagster_feature_membership(
                session,
                dagster_run_id=run_id,
                membership=membership,
                authoritative_snapshot_complete=True,
                curation_input_member_count=int(seal["input_member_count"]),
                curation_input_set_hash=str(seal["source_input_set_hash"]),
            )
            source_job_id = finished.operation.members[0].job_id
        async with migrated_engine.connect() as connection:
            assert await connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM ops.curation_provider_snapshot_receipts
                      WHERE source_job_id = CAST(:job_id AS uuid)
                    ) AND NOT EXISTS (
                      SELECT 1 FROM ops.curation_provider_root_receipts
                      WHERE root_job_id = (
                        SELECT parent_job_id FROM ops.import_jobs
                        WHERE job_id = CAST(:job_id AS uuid)
                      )
                    )
                    """
                ),
                {"job_id": source_job_id},
            ) is True

        if drift_after_seal:
            async with migrated_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE provider_sync.source_links
                        SET confidence = 99
                        WHERE source_entity_key = :source_entity_key
                          AND feature_id = :feature_id
                        """
                    ),
                    seeded,
                )

        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            terminal = await reconcile_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                terminal_status="SUCCESS",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=created_at,
                engine_started_at=started_at,
                engine_finished_at=finished_at,
                error=None,
            )
            assert terminal.operation.status == (
                "failed" if drift_after_seal else "done"
            )
    finally:
        await dagster.dispose()

    async with migrated_engine.connect() as connection:
        receipt = (
            await connection.execute(
                text(
                    """
                    SELECT root_receipt.generation_count AS generations,
                      snapshot.source_input_set_hash AS input_set_hash,
                      (SELECT count(*)
                       FROM ops.curation_source_observation_receipts
                       WHERE import_job_id = job.job_id) AS observations,
                      (SELECT count(*)
                       FROM feature.theme_candidate_generations
                       WHERE source_job_id = job.job_id) AS generation_rows
                    FROM ops.import_jobs AS job
                    JOIN ops.curation_provider_snapshot_receipts AS snapshot
                      ON snapshot.source_job_id = job.job_id
                    JOIN ops.curation_provider_root_receipts AS root_receipt
                      ON root_receipt.root_job_id = job.parent_job_id
                    WHERE job.job_id = CAST(:job_id AS uuid)
                    """
                ),
                {"job_id": source_job_id},
            )
        ).one_or_none()
    if drift_after_seal:
        assert receipt is None
        async with migrated_engine.connect() as connection:
            terminal = (
                await connection.execute(
                    text(
                        """
                        SELECT root.status, root.current_stage,
                               count(root_receipt.root_job_id) AS receipts
                        FROM ops.import_jobs AS child
                        JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
                        LEFT JOIN ops.curation_provider_root_receipts AS root_receipt
                          ON root_receipt.root_job_id = root.job_id
                        WHERE child.job_id = CAST(:job_id AS uuid)
                        GROUP BY root.status, root.current_stage
                        """
                    ),
                    {"job_id": source_job_id},
                )
            ).one()
        assert (terminal.status, terminal.current_stage, terminal.receipts) == (
            "failed",
            "stale_input",
            0,
        )
    else:
        assert receipt is not None
        assert receipt.generations == 1
        assert len(receipt.input_set_hash) == 64
        assert (receipt.observations, receipt.generation_rows) == (1, 1)


@pytest.mark.parametrize(
    "mutation_sql",
    [
        """
        UPDATE provider_sync.source_links SET match_method = 'manual', confidence = 55
        WHERE source_entity_key = :source_entity_key AND feature_id = :feature_id
        """,
        """
        UPDATE feature.feature_places
        SET payload = jsonb_build_object('semantic-drift', true)
        WHERE feature_id = :feature_id
        """,
    ],
)
async def test_provider_child_rejects_post_load_semantic_commit(
    migrated_engine: AsyncEngine,
    mutation_sql: str,
) -> None:
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
    )
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                  provider_dataset_id, operation_key, operation_kind,
                  is_enabled, config
                ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
                """
            ),
            seeded,
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                  provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                """
            ),
            seeded,
        )
        a_seal = (
            await connection.execute(
                text(
                    """
                    SELECT input_member_count, source_input_set_hash
                    FROM feature.current_provider_curation_input_set(:dataset_id)
                    """
                ),
                seeded,
            )
        ).mappings().one()
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(mutation_sql),
            seeded,
        )

    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    session_factory = async_sessionmaker(dagster, expire_on_commit=False)
    try:
        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await ensure_dagster_feature_operation(
                session,
                dagster_run_id=f"tvn40-causal-gap-{seeded['suffix']}",
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=datetime(2026, 8, 13, 2, tzinfo=UTC),
                engine_started_at=datetime(2026, 8, 13, 2, 0, 1, tzinfo=UTC),
                observed_status="STARTED",
            )
            with pytest.raises(DBAPIError) as stale:
                await finish_dagster_feature_membership(
                    session,
                    dagster_run_id=f"tvn40-causal-gap-{seeded['suffix']}",
                    membership=membership,
                    authoritative_snapshot_complete=True,
                    curation_input_member_count=int(a_seal["input_member_count"]),
                    curation_input_set_hash=str(a_seal["source_input_set_hash"]),
                )
            assert getattr(stale.value.orig, "sqlstate", None) == "23514"
            assert "load input changed" in str(stale.value.orig)
    finally:
        await dagster.dispose()


async def test_concierge_catalog_is_db_derived_inside_terminal_root(
    migrated_engine: AsyncEngine,
) -> None:
    dataset_key = "youtube_place_candidates"
    seeded = await _seed_candidate(
        migrated_engine,
        operation="admin.curation-rule.create",
        create_candidate=False,
        provider="kor-travel-concierge-youtube",
        dataset_key=dataset_key,
        place_kind="youtube_place_candidate",
        place_payload=json.dumps(
            {
                "kor_travel_concierge": {
                    "youtube": {
                        "channel_id": "channel-a",
                        "channel_title": "채널 A",
                        "playlist_id": "playlist-a",
                        "playlist_title": "목록 A",
                    }
                }
            }
        ),
    )
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    async with migrated_engine.begin() as connection:
        for statement in (
            """
            INSERT INTO provider_sync.provider_dataset_operations (
              provider_dataset_id, operation_key, operation_kind, is_enabled, config
            ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
            ON CONFLICT (provider_dataset_id, operation_key) DO NOTHING
            """,
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
              provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
            ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING
            """,
        ):
            await connection.execute(text(statement), seeded)

    run_id = f"tvn40-concierge-{seeded['suffix']}"
    created_at = datetime(2026, 8, 13, 3, tzinfo=UTC)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    session_factory = async_sessionmaker(dagster, expire_on_commit=False)
    try:
        seal = await _current_provider_curation_input_set(
            migrated_engine,
            provider_dataset_id=membership.provider_dataset_id,
        )
        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=created_at,
                engine_started_at=created_at + timedelta(seconds=1),
                observed_status="STARTED",
            )
            await finish_dagster_feature_membership(
                session,
                dagster_run_id=run_id,
                membership=membership,
                authoritative_snapshot_complete=True,
                curation_input_member_count=int(seal["input_member_count"]),
                curation_input_set_hash=str(seal["source_input_set_hash"]),
            )
        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            terminal = await reconcile_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                terminal_status="SUCCESS",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=created_at,
                engine_started_at=created_at + timedelta(seconds=1),
                engine_finished_at=created_at + timedelta(seconds=2),
                error=None,
            )
            assert terminal.operation.status == "done"

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as direct:
                await connection.execute(
                    text(
                        """
                        CALL feature.sync_concierge_theme_catalog(
                          :dataset_id, CAST(:job_id AS uuid),
                          NULL, NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {**seeded, "job_id": str(uuid4())},
                )
            assert getattr(direct.value.orig, "sqlstate", None) == "42501"
            await transaction.rollback()
    finally:
        await dagster.dispose()

    async with migrated_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT theme.theme_slug, rule.default_action, rule.enabled,
                           rule.archived_at IS NULL AS rule_active,
                           count(candidate.candidate_id) AS candidates
                    FROM feature.curated_themes AS theme
                    JOIN feature.curated_source_rules AS rule ON rule.theme_id = theme.theme_id
                    LEFT JOIN feature.theme_feature_candidates AS candidate
                      ON candidate.rule_id = rule.rule_id
                     AND candidate.disposition = 'active'
                     AND candidate.eligibility_present
                    WHERE theme.owner_kind = 'provider_dataset'
                      AND theme.owner_provider_dataset_id = :dataset_id
                    GROUP BY theme.theme_slug, rule.default_action, rule.enabled,
                             rule.archived_at
                    ORDER BY theme.theme_slug
                    """
                ),
                seeded,
            )
        ).all()
    assert [row.theme_slug for row in rows] == [
        "concierge-pl-playlist-a",
        "concierge-yt-channel-a",
    ]
    assert all(
        (row.default_action, row.enabled, row.rule_active, row.candidates)
        == ("candidate", True, True, 1)
        for row in rows
    )


async def test_provider_operation_rows_require_typed_dagster_commands(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(migrated_engine, create_candidate=False)
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    async with migrated_engine.begin() as connection:
        for statement in (
            """
            INSERT INTO provider_sync.provider_dataset_operations (
              provider_dataset_id, operation_key, operation_kind, is_enabled, config
            ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
            """,
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
              provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
            """,
        ):
            await connection.execute(text(statement), seeded)

    run_id = f"tvn40-provider-command-{seeded['suffix']}"
    created_at = datetime(2026, 8, 13, 4, tzinfo=UTC)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    session_factory = async_sessionmaker(dagster, expire_on_commit=False)
    try:
        async with session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            operation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=created_at,
                engine_started_at=created_at + timedelta(seconds=1),
                observed_status="STARTED",
            )
            root_job_id = operation.operation.root_job_id
            child_job_id = operation.operation.members[0].job_id

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            with pytest.raises(DBAPIError) as missing_seal:
                await connection.execute(
                    text(
                        """
                        CALL ops.finish_provider_feature_membership_command(
                          CAST(:root_job_id AS uuid), :dataset_id,
                          'dataset_wide', 'load', true, clock_timestamp(), NULL
                        )
                        """
                    ),
                    {**seeded, "root_job_id": root_job_id},
                )
            assert getattr(missing_seal.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        for statement in (
            """
            UPDATE ops.import_jobs
            SET payload = jsonb_build_object('forged', true)
            WHERE job_id = CAST(:root_job_id AS uuid)
            """,
            """
            UPDATE ops.import_job_datasets AS member
            SET sync_scope = member.sync_scope
            FROM ops.import_jobs AS child
            WHERE child.parent_job_id = CAST(:root_job_id AS uuid)
              AND child.job_id = member.job_id
            """,
            """
            INSERT INTO ops.import_jobs (
              kind, payload, status, progress, current_stage, dagster_run_id,
              dataset_membership_mode, trigger_kind, operation_key,
              dagster_run_status
            ) VALUES (
              'provider_feature_load_run', '{}'::jsonb, 'queued', 0, 'queued',
              :forged_run_id, 'root', 'schedule', 'load', 'QUEUED'
            )
            """,
            """
            INSERT INTO ops.import_job_events (
              job_id, import_job_dataset_id, stage, level, code, message, payload
            ) SELECT child.job_id, member.import_job_dataset_id, child.current_stage,
                     'error', 'feature_operation.attempt', 'forged', '{}'::jsonb
              FROM ops.import_jobs AS child
              JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
             WHERE child.job_id = CAST(:child_job_id AS uuid)
            """,
        ):
            async with dagster.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(DBAPIError) as denied:
                    await connection.execute(
                        text(statement),
                        {
                            "forged_run_id": f"forged-{seeded['suffix']}",
                            "root_job_id": root_job_id,
                            "child_job_id": child_job_id,
                        },
                    )
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                await transaction.rollback()
    finally:
        await dagster.dispose()

    # API runtime도 frozen cancellation receipt 없는 provider row를 raw 변경할 수 없다.
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        for statement in (
            """
            UPDATE ops.import_jobs
            SET status = 'done', dagster_run_status = 'SUCCESS',
                current_stage = 'completed', progress = 100
            WHERE job_id = CAST(:root_job_id AS uuid)
            """,
            """
            INSERT INTO ops.import_job_events (
              job_id, import_job_dataset_id, stage, level, code, message, payload
            ) SELECT child.job_id, member.import_job_dataset_id, child.current_stage,
                     'error', 'feature_operation.attempt', 'forged', '{}'::jsonb
              FROM ops.import_jobs AS child
              JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
             WHERE child.job_id = CAST(:child_job_id AS uuid)
            """,
        ):
            async with api.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(DBAPIError) as denied:
                    await connection.execute(
                        text(statement),
                        {"root_job_id": root_job_id, "child_job_id": child_job_id},
                    )
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                await transaction.rollback()
    finally:
        await api.dispose()

    terminal_dagster = _runtime_engine(
        migrated_engine, login="ktm_feature_dagster_runtime"
    )
    try:
        terminal_session_factory = async_sessionmaker(
            terminal_dagster, expire_on_commit=False
        )
        async with terminal_session_factory.begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await session.execute(
                text(
                    """
                    CALL ops.finish_provider_feature_membership_command(
                      CAST(:root_job_id AS uuid), :dataset_id,
                      'dataset_wide', 'load', false, clock_timestamp(), NULL
                    )
                    """
                ),
                {**seeded, "root_job_id": root_job_id},
            )
            await session.execute(
                text(
                    """
                    CALL ops.transition_provider_feature_operation_terminal_command(
                      CAST(:root_job_id AS uuid), 'done', 'SUCCESS', 'completed', NULL,
                      clock_timestamp(), clock_timestamp(), false, NULL
                    )
                    """
                ),
                {"root_job_id": root_job_id},
            )
            result = (
                await session.execute(
                    text(
                        """
                        CALL feature.finalize_provider_curation_root(
                          CAST(:root_job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"root_job_id": root_job_id},
                )
            ).mappings().one()
            assert result["o_generation_count"] == 0
            assert result["o_replayed"] is False
    finally:
        await terminal_dagster.dispose()
    async with migrated_engine.connect() as connection:
        assert (
            await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM ops.curation_provider_root_receipts
                    WHERE root_job_id = CAST(:root_job_id AS uuid)
                    """
                ),
                {"root_job_id": root_job_id},
            )
        ) == 0


async def test_provider_cancellation_lifecycle_requires_typed_api_command(
    migrated_engine: AsyncEngine,
) -> None:
    seeded = await _seed_candidate(migrated_engine, create_candidate=False)
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                  provider_dataset_id, operation_key, operation_kind, is_enabled, config
                ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
                """
            ),
            seeded,
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                  provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                """
            ),
            seeded,
        )

    run_id = f"tvn40-cancellation-{seeded['suffix']}"
    started_at = datetime(2026, 8, 13, 5, tzinfo=UTC)
    finished_at = started_at + timedelta(seconds=3)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with async_sessionmaker(dagster, expire_on_commit=False).begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            operation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=started_at - timedelta(seconds=1),
                engine_started_at=started_at,
                observed_status="STARTED",
            )
        member_ids = (
            operation.operation.root_job_id,
            operation.operation.members[0].job_id,
        )

        async with async_sessionmaker(api, expire_on_commit=False).begin() as session:
            scope = await resolve_pipeline_cancellation_scope(
                session,
                kind="import_job",
                execution_id=operation.operation.root_job_id,
            )
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:tvn40-cancellation",
                reason="typed cancellation boundary regression",
            )
        cancellation_id = detail.attempt.cancellation_id

        for raw_update in (
            "started_at = started_at - interval '1 hour'",
            "status = 'done', dagster_run_status = 'SUCCESS', "
            "finished_at = clock_timestamp(), progress = 100, current_stage = 'completed'",
        ):
            async with api.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(DBAPIError) as denied:
                    await connection.execute(
                        text(
                            f"UPDATE ops.import_jobs SET {raw_update} "  # noqa: S608
                            "WHERE job_id = CAST(:job_id AS uuid)"
                        ),
                        {"job_id": operation.operation.root_job_id},
                    )
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                await transaction.rollback()

        async with async_sessionmaker(api, expire_on_commit=False).begin() as session:
            assert await set_pipeline_cancellation_run_result(
                session,
                cancellation_id=cancellation_id,
                dagster_run_id=run_id,
                result="cancelled",
                initial_status="STARTED",
                terminal_status="CANCELED",
                error=None,
                engine_started_at=started_at,
                engine_finished_at=finished_at,
            )
            for job_id in member_ids:
                assert await transition_pipeline_cancellation_member(
                    session,
                    cancellation_id=cancellation_id,
                    job_id=job_id,
                    dagster_run_id=run_id,
                    expected_status="running",
                    target_status="cancelled",
                    result="cancelled",
                    dagster_terminal_status="CANCELED",
                    engine_started_at=started_at,
                    engine_finished_at=finished_at,
                )
            assert await finish_pipeline_cancellation_attempt(
                session,
                cancellation_id=cancellation_id,
                status="completed",
                error=None,
            ) is not None

        async with migrated_engine.connect() as connection:
            terminal = (
                await connection.execute(
                    text(
                        """
                        SELECT job_id::text, status, dagster_run_status, progress,
                               current_stage, started_at, finished_at
                        FROM ops.import_jobs
                        WHERE job_id = ANY(CAST(:job_ids AS uuid[]))
                        ORDER BY job_id
                        """
                    ),
                    {"job_ids": list(member_ids)},
                )
            ).all()
        assert len(terminal) == 2
        assert all(row.status == "cancelled" for row in terminal)
        assert {row.dagster_run_status for row in terminal} == {None, "CANCELED"}
        assert all(row.current_stage == "cancelled" for row in terminal)
        assert all(
            row.started_at == started_at and row.finished_at == finished_at
            for row in terminal
        )
    finally:
        await api.dispose()
        await dagster.dispose()


@pytest.mark.parametrize("drift_after_seal", [False, True])
async def test_provider_cancellation_success_finalizes_authoritative_root(
    migrated_engine: AsyncEngine,
    drift_after_seal: bool,
) -> None:
    seeded = await _seed_candidate(migrated_engine, create_candidate=False)
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=int(seeded["dataset_id"]),
        sync_scope="dataset_wide",
        operation_key="load",
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operations (
                  provider_dataset_id, operation_key, operation_kind, is_enabled, config
                ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
                """
            ),
            seeded,
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.provider_dataset_operation_scopes (
                  provider_dataset_id, sync_scope, operation_key, operation_kind
                ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
                """
            ),
            seeded,
        )

    run_id = (
        f"tvn40-cancellation-success-{int(drift_after_seal)}-{seeded['suffix']}"
    )
    started_at = datetime(2026, 8, 13, 6, tzinfo=UTC)
    finished_at = started_at + timedelta(seconds=3)
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        seal = await _current_provider_curation_input_set(
            migrated_engine,
            provider_dataset_id=membership.provider_dataset_id,
        )
        async with async_sessionmaker(dagster, expire_on_commit=False).begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                selected_memberships=(membership,),
                operation_key="load",
                engine_created_at=started_at - timedelta(seconds=1),
                engine_started_at=started_at,
                observed_status="STARTED",
            )
            completed = await finish_dagster_feature_membership(
                session,
                dagster_run_id=run_id,
                membership=membership,
                authoritative_snapshot_complete=True,
                curation_input_member_count=int(seal["input_member_count"]),
                curation_input_set_hash=str(seal["source_input_set_hash"]),
            )
            root_job_id = completed.operation.root_job_id

        async with async_sessionmaker(api, expire_on_commit=False).begin() as session:
            scope = await resolve_pipeline_cancellation_scope(
                session,
                kind="import_job",
                execution_id=root_job_id,
            )
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:tvn40-cancellation",
                reason="SUCCESS finalizer regression",
            )
        cancellation_id = detail.attempt.cancellation_id

        if drift_after_seal:
            async with migrated_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE provider_sync.source_links
                        SET match_method = 'manual', confidence = 55
                        WHERE source_entity_key = :source_entity_key
                          AND feature_id = :feature_id
                        """
                    ),
                    seeded,
                )

        async with async_sessionmaker(api, expire_on_commit=False).begin() as session:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            assert await set_pipeline_cancellation_run_result(
                session,
                cancellation_id=cancellation_id,
                dagster_run_id=run_id,
                result="already_terminal",
                initial_status="STARTED",
                terminal_status="SUCCESS",
                error=None,
                engine_started_at=started_at,
                engine_finished_at=finished_at,
            )
            assert await transition_pipeline_cancellation_member(
                session,
                cancellation_id=cancellation_id,
                job_id=root_job_id,
                dagster_run_id=run_id,
                expected_status="running",
                target_status="done",
                result="already_terminal",
                dagster_terminal_status="SUCCESS",
                engine_started_at=started_at,
                engine_finished_at=finished_at,
            )
            finished = await finish_pipeline_cancellation_attempt(
                session,
                cancellation_id=cancellation_id,
                status="completed",
                error=None,
            )
            assert finished is not None
            assert finished.attempt.status == "completed"

        async with migrated_engine.connect() as connection:
            root = (
                await connection.execute(
                    text(
                        """
                        SELECT status, current_stage FROM ops.import_jobs
                        WHERE job_id = CAST(:root_job_id AS uuid)
                        """
                    ),
                    {"root_job_id": root_job_id},
                )
            ).one()
            member_terminal = await connection.scalar(
                text(
                    """
                    SELECT terminal_status FROM ops.pipeline_cancellation_members
                    WHERE cancellation_id = CAST(:cancellation_id AS uuid)
                      AND job_id = CAST(:root_job_id AS uuid)
                    """
                ),
                {"cancellation_id": cancellation_id, "root_job_id": root_job_id},
            )
            receipt_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM ops.curation_provider_root_receipts
                    WHERE root_job_id = CAST(:root_job_id AS uuid)
                    """
                ),
                {"root_job_id": root_job_id},
            )
            attempt_status = await connection.scalar(
                text(
                    """
                    SELECT status FROM ops.pipeline_cancellations
                    WHERE cancellation_id = CAST(:cancellation_id AS uuid)
                    """
                ),
                {"cancellation_id": cancellation_id},
            )
        assert attempt_status == "completed"
        if drift_after_seal:
            assert root == ("failed", "stale_input")
            assert member_terminal == "failed"
            assert receipt_count == 0
        else:
            assert root == ("done", "completed")
            assert member_terminal == "done"
            assert receipt_count == 1
    finally:
        await api.dispose()
        await dagster.dispose()
