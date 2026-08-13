"""T-VN-40 typed candidate command actual-LOGIN integration."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _seed_candidate(
    engine: AsyncEngine,
    *,
    operation: str = "admin.theme-feature-candidate.reject",
    create_candidate: bool = True,
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
        await connection.execute(
            text(
                """
                INSERT INTO feature.feature_places (
                  feature_id, feature_uuid, kind, place_kind,
                  facility_info, reviews_link, payload
                )
                SELECT
                  feature_id, feature_uuid, kind, 'attraction',
                  jsonb_build_object('wheelchair', true), '{}'::jsonb, '{}'::jsonb
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            seed,
        )
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


async def test_provider_full_snapshot_requires_exact_authoritative_job_and_replays(
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
        params = {**seeded, "source_job_id": source_job_id}

        async with dagster.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            with pytest.raises(IntegrityError) as invalid:
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
            assert getattr(invalid.value.orig, "sqlstate", None) == "23514"
            await transaction.rollback()

        async with dagster.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            first = (
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
                    params,
                )
            ).mappings().one()
        assert first["o_replayed"] is False
        assert int(first["o_observed_candidate_count"]) == 1

        async with dagster.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            )
            replay = (
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
                    params,
                )
            ).mappings().one()
        assert replay["o_replayed"] is True
        assert replay["o_generation_id"] == first["o_generation_id"]

        async with migrated_engine.connect() as connection:
            actor, source_job, causation_job = (
                await connection.execute(
                    text(
                        """
                        SELECT transition.actor, generation.source_job_id::text,
                               transition.causation_ref ->> 'source_job_id'
                        FROM feature.theme_feature_candidate_transitions AS transition
                        JOIN feature.theme_candidate_generations AS generation
                          ON generation.generation_id = transition.generation_id
                        WHERE generation.generation_id = CAST(:generation_id AS uuid)
                        """
                    ),
                    {"generation_id": first["o_generation_id"]},
                )
            ).one()
        assert actor == f"provider:{seeded['dataset_id']}"
        assert source_job == source_job_id
        assert causation_job == source_job_id
    finally:
        await dagster.dispose()
