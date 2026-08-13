"""T-VN-40B server-derived rule reconcile generation.

Revision ID: 0108_tvn40_rule_generation
Revises: 0107_tvn40_candidate_promotion

The runtime caller supplies only an immutable reconcile operation identity.
PostgreSQL derives the complete current match set, writes the immutable receipt
first, materializes observations/candidates, and removes eligibility only after
the same locked set has been proven complete.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Frozen PostgreSQL procedure text intentionally exceeds Python line length.
# ruff: noqa: E501

revision: str = "0108_tvn40_rule_generation"
down_revision: str | Sequence[str] | None = "0107_tvn40_candidate_promotion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MATERIALIZE_PROCEDURE_SQL = r"""
CREATE PROCEDURE feature.materialize_theme_candidate_generation(
  IN p_rule_id uuid,
  IN p_generation_kind text,
  IN p_source_job_id uuid,
  IN p_reconcile_operation_id uuid,
  IN p_command_id bigint,
  IN p_generation_key text,
  IN p_context jsonb,
  OUT o_generation_id uuid,
  OUT o_observed_candidate_count bigint,
  OUT o_eligibility_removed_candidate_count bigint,
  OUT o_generation_input_set_hash text,
  OUT o_replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, feature, provider_sync, ops, x_extension
AS $command$
DECLARE
  v_rule_hint feature.curated_source_rules%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
  v_operation ops.curation_rule_reconcile_operations%ROWTYPE;
  v_source_job ops.import_jobs%ROWTYPE;
  v_existing_generation feature.theme_candidate_generations%ROWTYPE;
  v_candidate feature.theme_feature_candidates%ROWTYPE;
  v_expected record;
  v_feature_id text;
  v_provider_dataset_id bigint;
  v_rule_input jsonb;
  v_rule_input_hash text;
  v_expected_generation_key text;
  v_scope_member_count bigint;
  v_scope_members_hash text;
  v_expected_scope_member_count bigint;
  v_expected_candidate_count bigint;
  v_expected_removed_count bigint;
  v_candidate_id uuid;
  v_candidate_revision bigint;
  v_transition_kind text;
  v_reason_code text;
  v_actor text;
  v_is_provider boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'candidate generation requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  v_is_provider := p_generation_kind = 'provider_full_snapshot';
  IF NOT (
       (v_is_provider
        AND p_source_job_id IS NOT NULL
        AND p_reconcile_operation_id IS NULL
        AND p_command_id IS NULL)
       OR
       (p_generation_kind = 'rule_reconcile'
        AND p_source_job_id IS NULL
        AND p_reconcile_operation_id IS NOT NULL)
     ) THEN
    RAISE EXCEPTION 'generation origin does not match its typed receipt'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_generation_kind';
  END IF;
  IF (v_is_provider AND (
        NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
        OR pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
      )) OR (NOT v_is_provider AND (
        NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
        OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
      )) THEN
    RAISE EXCEPTION 'generation receipt is not executable by this runtime principal'
      USING ERRCODE = '42501';
  END IF;
  IF p_context IS NULL OR jsonb_typeof(p_context) <> 'object' THEN
    RAISE EXCEPTION 'generation context must be an object'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_generation_context';
  END IF;

  -- These are discovery reads only.  No relation lock is taken before the
  -- complete touched Feature set has acquired the common sorted advisory fence.
  SELECT rule.* INTO STRICT v_rule_hint
  FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id;
  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_sources AS source
  WHERE source.source_id = v_rule_hint.source_id;

  FOR v_feature_id IN
    SELECT touched.feature_id
    FROM (
      SELECT candidate.feature_id
      FROM feature.theme_feature_candidates AS candidate
      WHERE candidate.rule_id = p_rule_id
        AND candidate.disposition = 'active'
      UNION
      SELECT link.feature_id
      FROM provider_sync.source_entities AS entity
      JOIN provider_sync.source_links AS link
        ON link.source_entity_key = entity.source_entity_key
      WHERE entity.provider_dataset_id = v_provider_dataset_id
    ) AS touched
    ORDER BY touched.feature_id
  LOOP
    PERFORM pg_advisory_xact_lock(
      hashtextextended('feature-write:' || v_feature_id, 0)
    );
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  -- Common order after every Feature advisory fence: catalog → source evidence
  -- → link → Feature → candidate.
  SELECT rule.* INTO STRICT v_rule
  FROM feature.curated_source_rules AS rule
  WHERE rule.rule_id = p_rule_id
  FOR SHARE;
  PERFORM 1 FROM feature.curated_themes AS theme
  WHERE theme.theme_id = v_rule.theme_id FOR SHARE;
  SELECT source.* INTO STRICT v_source
  FROM feature.curated_sources AS source
  WHERE source.source_id = v_rule.source_id
  FOR SHARE;
  v_provider_dataset_id := v_source.provider_dataset_id;
  PERFORM 1 FROM provider_sync.provider_datasets AS dataset
  WHERE dataset.provider_dataset_id = v_provider_dataset_id FOR SHARE;
  PERFORM 1 FROM provider_sync.source_entities AS entity
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY entity.source_entity_key FOR SHARE;
  PERFORM 1 FROM provider_sync.source_entity_heads AS head
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY head.source_entity_key FOR SHARE OF head;
  PERFORM 1 FROM provider_sync.source_records AS record
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = record.source_entity_key
   AND head.current_source_record_key = record.source_record_key
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY record.source_entity_key, record.source_record_key FOR SHARE OF record;
  PERFORM 1 FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  WHERE entity.provider_dataset_id = v_provider_dataset_id
  ORDER BY link.source_entity_key, link.feature_id FOR SHARE OF link;
  PERFORM 1 FROM feature.features AS core
  WHERE core.feature_id IN (
    SELECT candidate.feature_id
    FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  )
  ORDER BY core.feature_id FOR SHARE;
  PERFORM 1 FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.rule_id = p_rule_id
  ORDER BY candidate.feature_id, candidate.candidate_id FOR UPDATE;

  IF NOT v_is_provider THEN
    SELECT operation.* INTO STRICT v_operation
    FROM ops.curation_rule_reconcile_operations AS operation
    WHERE operation.operation_id = p_reconcile_operation_id
    FOR SHARE;
    IF v_operation.rule_id <> p_rule_id
     OR v_operation.after_rule_revision <> v_rule.row_revision
     OR v_operation.command_id IS DISTINCT FROM p_command_id THEN
    RAISE EXCEPTION 'reconcile operation does not match the locked rule/command'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reconcile_operation';
    END IF;
    IF p_command_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM ops.domain_commands AS command_receipt
    WHERE command_receipt.command_id = p_command_id
      AND command_receipt.actor = v_operation.actor
    ) THEN
      RAISE EXCEPTION 'reconcile command actor does not match its operation receipt'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reconcile_command';
    END IF;
    v_actor := v_operation.actor;

    SELECT count(*), encode(
    x_extension.digest(
      COALESCE(
        string_agg(
          convert_to(member.member_kind, 'UTF8') || decode('00', 'hex') ||
          convert_to(member.member_key, 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(member.before_identity_hash, ''), 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(member.after_identity_hash, ''), 'UTF8') ||
          convert_to(E'\n', 'UTF8'),
          ''::bytea ORDER BY member.member_kind, member.member_key
        ),
        ''::bytea
      ),
      'sha256'
    ),
    'hex'
  )
  INTO STRICT v_scope_member_count, v_scope_members_hash
  FROM ops.curation_rule_reconcile_scope_members AS member
  WHERE member.operation_id = p_reconcile_operation_id;
    IF v_scope_member_count <> v_operation.scope_member_count
     OR v_scope_members_hash <> v_operation.scope_members_hash THEN
    RAISE EXCEPTION 'reconcile operation scope receipt is not sealed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reconcile_scope_hash';
    END IF;

    SELECT count(*) INTO STRICT v_expected_scope_member_count
  FROM (
    SELECT 'source_entity'::text AS member_kind, entity.source_entity_key AS member_key
    FROM provider_sync.source_entities AS entity
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    UNION
    SELECT 'feature'::text, link.feature_id
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS expected_scope;
    IF v_expected_scope_member_count <> v_scope_member_count
     OR EXISTS (
       (SELECT member.member_kind, member.member_key
        FROM ops.curation_rule_reconcile_scope_members AS member
        WHERE member.operation_id = p_reconcile_operation_id
        EXCEPT
        SELECT expected.member_kind, expected.member_key
        FROM (
          SELECT 'source_entity'::text AS member_kind,
                 entity.source_entity_key AS member_key
          FROM provider_sync.source_entities AS entity
          WHERE entity.provider_dataset_id = v_provider_dataset_id
          UNION
          SELECT 'feature'::text, link.feature_id
          FROM provider_sync.source_entities AS entity
          JOIN provider_sync.source_links AS link
            ON link.source_entity_key = entity.source_entity_key
          WHERE entity.provider_dataset_id = v_provider_dataset_id
        ) AS expected)
       UNION ALL
       (SELECT expected.member_kind, expected.member_key
        FROM (
          SELECT 'source_entity'::text AS member_kind,
                 entity.source_entity_key AS member_key
          FROM provider_sync.source_entities AS entity
          WHERE entity.provider_dataset_id = v_provider_dataset_id
          UNION
          SELECT 'feature'::text, link.feature_id
          FROM provider_sync.source_entities AS entity
          JOIN provider_sync.source_links AS link
            ON link.source_entity_key = entity.source_entity_key
          WHERE entity.provider_dataset_id = v_provider_dataset_id
        ) AS expected
        EXCEPT
        SELECT member.member_kind, member.member_key
        FROM ops.curation_rule_reconcile_scope_members AS member
        WHERE member.operation_id = p_reconcile_operation_id)
     ) THEN
    RAISE EXCEPTION 'reconcile operation scope does not equal the DB-derived scope'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reconcile_scope_set';
    END IF;
  ELSE
    SELECT job.* INTO STRICT v_source_job
    FROM ops.import_jobs AS job
    WHERE job.job_id = p_source_job_id
    FOR SHARE;
    IF v_source_job.kind <> 'provider_feature_load'
       OR v_source_job.status <> 'done'
       OR v_source_job.parent_job_id IS NULL
       OR v_source_job.cancellation_id IS NOT NULL
       OR v_source_job.quarantined_at IS NOT NULL
       OR COALESCE(
         (v_source_job.payload ->> 'authoritative_snapshot_complete')::boolean,
         false
       ) IS NOT TRUE
       OR NOT EXISTS (
         SELECT 1
         FROM ops.import_jobs AS root
         WHERE root.job_id = v_source_job.parent_job_id
           AND root.kind = 'provider_feature_load_run'
           AND root.dagster_run_id = v_source_job.dagster_run_id
           AND root.cancellation_id IS NULL
           AND root.quarantined_at IS NULL
       )
       OR (SELECT count(*) FROM ops.import_job_datasets AS member
           WHERE member.job_id = p_source_job_id) <> 1
       OR NOT EXISTS (
         SELECT 1
         FROM ops.import_job_datasets AS member
         WHERE member.job_id = p_source_job_id
           AND member.provider_dataset_id = v_provider_dataset_id
           AND member.sync_scope = 'dataset_wide'
       ) THEN
      RAISE EXCEPTION 'provider generation requires an authoritative done single-member dataset snapshot'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_provider_job';
    END IF;
    v_actor := 'provider:' || v_provider_dataset_id::text;
  END IF;

  v_rule_input := feature.current_curation_rule_input(p_rule_id);
  IF v_rule_input IS NULL THEN
    RAISE EXCEPTION 'locked rule input could not be materialized'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_rule_input';
  END IF;
  v_rule_input_hash := encode(
    x_extension.digest(convert_to(v_rule_input::text, 'UTF8'), 'sha256'), 'hex'
  );
  IF NOT v_is_provider
     AND v_operation.after_rule_input_hash <> v_rule_input_hash THEN
    RAISE EXCEPTION 'reconcile operation rule hash is stale'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_reconcile_rule_hash';
  END IF;

  SELECT count(*), encode(
    x_extension.digest(
      convert_to(
        COALESCE(
          jsonb_agg(
            jsonb_build_array(
              expected.source_entity_key,
              expected.source_record_key,
              expected.source_record_hash,
              expected.feature_id,
              expected.candidate_input_hash
            ) ORDER BY expected.source_entity_key, expected.feature_id
          )::text,
          '[]'
        ),
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  )
  INTO STRICT v_expected_candidate_count, o_generation_input_set_hash
  FROM (
    SELECT entity.source_entity_key, snapshot.source_record_key,
           snapshot.source_record_hash, link.feature_id,
           snapshot.candidate_input_hash
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
      p_rule_id, entity.source_entity_key, link.feature_id
    ) AS snapshot
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS expected;

  v_expected_generation_key := CASE
    WHEN v_is_provider THEN 'provider-full-snapshot:'
    ELSE 'rule-reconcile:'
  END || encode(
    x_extension.digest(
      convert_to(
        p_rule_id::text || ':' ||
        COALESCE(p_source_job_id::text, p_reconcile_operation_id::text) || ':' ||
        v_rule.row_revision::text || ':' || v_rule_input_hash || ':' ||
        o_generation_input_set_hash,
        'UTF8'
      ),
      'sha256'
    ),
    'hex'
  );
  IF p_generation_key IS NOT NULL
     AND p_generation_key <> v_expected_generation_key THEN
    RAISE EXCEPTION 'generation key is not the server-derived operation key'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_generation_key';
  END IF;

  SELECT generation.* INTO v_existing_generation
  FROM feature.theme_candidate_generations AS generation
  WHERE generation.rule_id = p_rule_id
    AND (
      (v_is_provider AND generation.source_job_id = p_source_job_id)
      OR
      (NOT v_is_provider
       AND generation.reconcile_operation_id = p_reconcile_operation_id)
    );
  IF FOUND THEN
    IF v_existing_generation.generation_kind <> p_generation_kind
       OR v_existing_generation.source_job_id IS DISTINCT FROM p_source_job_id
       OR v_existing_generation.reconcile_operation_id
          IS DISTINCT FROM p_reconcile_operation_id
       OR v_existing_generation.command_id IS DISTINCT FROM p_command_id
       OR v_existing_generation.generation_key <> v_expected_generation_key
       OR v_existing_generation.rule_row_revision <> v_rule.row_revision
       OR v_existing_generation.rule_input_hash <> v_rule_input_hash
       OR v_existing_generation.rule_input <> v_rule_input
       OR v_existing_generation.generation_input_set_hash <> o_generation_input_set_hash
       OR v_existing_generation.observed_candidate_count <> v_expected_candidate_count
       OR EXISTS (
         (SELECT candidate.candidate_id, candidate.source_entity_key,
                 candidate.feature_id, candidate.source_record_key,
                 candidate.candidate_input_hash
          FROM provider_sync.source_entities AS entity
          JOIN provider_sync.source_links AS link
            ON link.source_entity_key = entity.source_entity_key
          CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
            p_rule_id, entity.source_entity_key, link.feature_id
          ) AS snapshot
          JOIN feature.theme_feature_candidates AS candidate
            ON candidate.rule_id = p_rule_id
           AND candidate.source_entity_key = entity.source_entity_key
           AND candidate.feature_id = link.feature_id
          WHERE entity.provider_dataset_id = v_provider_dataset_id
          EXCEPT
          SELECT observation.candidate_id, observation.source_entity_key,
                 observation.feature_id, observation.source_record_key,
                 observation.candidate_input_hash
          FROM feature.theme_candidate_generation_observations AS observation
          WHERE observation.generation_id = v_existing_generation.generation_id)
         UNION ALL
         (SELECT observation.candidate_id, observation.source_entity_key,
                 observation.feature_id, observation.source_record_key,
                 observation.candidate_input_hash
          FROM feature.theme_candidate_generation_observations AS observation
          WHERE observation.generation_id = v_existing_generation.generation_id
          EXCEPT
          SELECT candidate.candidate_id, candidate.source_entity_key,
                 candidate.feature_id, candidate.source_record_key,
                 candidate.candidate_input_hash
          FROM provider_sync.source_entities AS entity
          JOIN provider_sync.source_links AS link
            ON link.source_entity_key = entity.source_entity_key
          CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
            p_rule_id, entity.source_entity_key, link.feature_id
          ) AS snapshot
          JOIN feature.theme_feature_candidates AS candidate
            ON candidate.rule_id = p_rule_id
           AND candidate.source_entity_key = entity.source_entity_key
           AND candidate.feature_id = link.feature_id
          WHERE entity.provider_dataset_id = v_provider_dataset_id)
       ) OR EXISTS (
         SELECT 1
         FROM feature.theme_feature_candidates AS candidate
         WHERE candidate.rule_id = p_rule_id
           AND candidate.disposition = 'active'
           AND candidate.eligibility_present
           AND NOT EXISTS (
             SELECT 1
             FROM provider_sync.source_entities AS entity
             JOIN provider_sync.source_links AS link
               ON link.source_entity_key = entity.source_entity_key
             CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
               p_rule_id, entity.source_entity_key, link.feature_id
             ) AS snapshot
             WHERE entity.provider_dataset_id = v_provider_dataset_id
               AND entity.source_entity_key = candidate.source_entity_key
               AND link.feature_id = candidate.feature_id
           )
       ) THEN
      RAISE EXCEPTION 'generation replay no longer matches current canonical input'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_generation_replay';
    END IF;
    o_generation_id := v_existing_generation.generation_id;
    o_observed_candidate_count := v_existing_generation.observed_candidate_count;
    o_eligibility_removed_candidate_count :=
      v_existing_generation.eligibility_removed_candidate_count;
    o_replayed := true;
    RETURN;
  END IF;

  SELECT count(*) INTO STRICT v_expected_removed_count
  FROM feature.theme_feature_candidates AS candidate
  WHERE candidate.rule_id = p_rule_id
    AND candidate.disposition = 'active'
    AND candidate.eligibility_present
    AND NOT EXISTS (
      SELECT 1
      FROM provider_sync.source_entities AS entity
      JOIN provider_sync.source_links AS link
        ON link.source_entity_key = entity.source_entity_key
      CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
        p_rule_id, entity.source_entity_key, link.feature_id
      ) AS snapshot
      WHERE entity.provider_dataset_id = v_provider_dataset_id
        AND entity.source_entity_key = candidate.source_entity_key
        AND link.feature_id = candidate.feature_id
    );

  o_generation_id := x_extension.gen_random_uuid();
  INSERT INTO feature.theme_candidate_generations (
    generation_id, rule_id, rule_row_revision, generation_kind,
    source_job_id, reconcile_operation_id, command_id, generation_key,
    rule_input_hash, rule_input, generation_input_set_hash,
    observed_candidate_count, eligibility_removed_candidate_count
  ) VALUES (
    o_generation_id, p_rule_id, v_rule.row_revision, p_generation_kind,
    p_source_job_id, p_reconcile_operation_id, p_command_id,
    v_expected_generation_key,
    v_rule_input_hash, v_rule_input, o_generation_input_set_hash,
    v_expected_candidate_count, v_expected_removed_count
  );

  FOR v_expected IN
    SELECT entity.source_entity_key, link.feature_id,
           snapshot.rule_row_revision, snapshot.rule_input_hash,
           snapshot.source_record_key, snapshot.source_record_hash,
           snapshot.candidate_input_hash, snapshot.match_evidence
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
      p_rule_id, entity.source_entity_key, link.feature_id
    ) AS snapshot
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    ORDER BY entity.source_entity_key, link.feature_id
  LOOP
    SELECT candidate.* INTO v_candidate
    FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id
      AND candidate.source_entity_key = v_expected.source_entity_key
      AND candidate.feature_id = v_expected.feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
      v_candidate_id := x_extension.gen_random_uuid();
      INSERT INTO feature.theme_feature_candidates (
        candidate_id, rule_id, source_entity_key, feature_id,
        source_record_key, rule_row_revision, rule_input_hash,
        source_record_hash, candidate_input_hash, review_state,
        eligibility_present, disposition, rank_score, match_evidence,
        row_revision
      ) VALUES (
        v_candidate_id, p_rule_id, v_expected.source_entity_key,
        v_expected.feature_id, v_expected.source_record_key,
        v_expected.rule_row_revision, v_expected.rule_input_hash,
        v_expected.source_record_hash, v_expected.candidate_input_hash,
        'open', true, 'active', v_rule.priority,
        v_expected.match_evidence, 1
      );
      v_candidate_revision := 1;
      PERFORM feature.append_theme_feature_candidate_transition(
        v_candidate_id, NULL, v_expected.feature_id, p_rule_id,
        v_expected.source_entity_key, NULL, 'open', NULL, true,
        NULL, 'active', NULL, 'eligibility_materialize',
        v_candidate_revision, v_rule.row_revision, v_rule_input_hash,
        v_expected.candidate_input_hash, o_generation_id,
        v_provider_dataset_id, v_expected.source_record_key,
        v_expected.source_record_hash, NULL, NULL, NULL,
        v_actor, 'rule_match',
        jsonb_strip_nulls(jsonb_build_object(
          'schema_version', 1,
          'generation_kind', p_generation_kind,
          'source_job_id', p_source_job_id::text,
          'reconcile_operation_id', p_reconcile_operation_id::text
        ))
      );
    ELSE
      IF v_candidate.disposition <> 'active' THEN
        RAISE EXCEPTION 'generation cannot reactivate a merged candidate tombstone'
          USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_active_generation';
      END IF;
      v_candidate_id := v_candidate.candidate_id;
      v_candidate_revision := v_candidate.row_revision;
      IF NOT v_candidate.eligibility_present
         OR v_candidate.rule_input_hash <> v_expected.rule_input_hash
         OR v_candidate.source_record_key <> v_expected.source_record_key
         OR v_candidate.source_record_hash <> v_expected.source_record_hash
         OR v_candidate.candidate_input_hash <> v_expected.candidate_input_hash THEN
        v_transition_kind := CASE
          WHEN v_candidate.eligibility_present THEN 'eligibility_refresh'
          ELSE 'eligibility_restore'
        END;
        UPDATE feature.theme_feature_candidates AS candidate
        SET source_record_key = v_expected.source_record_key,
            rule_row_revision = v_expected.rule_row_revision,
            rule_input_hash = v_expected.rule_input_hash,
            source_record_hash = v_expected.source_record_hash,
            candidate_input_hash = v_expected.candidate_input_hash,
            eligibility_present = true,
            rank_score = v_rule.priority,
            match_evidence = v_expected.match_evidence,
            row_revision = candidate.row_revision + 1,
            updated_at = clock_timestamp()
        WHERE candidate.candidate_id = v_candidate.candidate_id
        RETURNING candidate.row_revision INTO STRICT v_candidate_revision;
        PERFORM feature.append_theme_feature_candidate_transition(
          v_candidate.candidate_id, v_candidate.feature_id,
          v_candidate.feature_id, p_rule_id, v_candidate.source_entity_key,
          v_candidate.review_state, v_candidate.review_state,
          v_candidate.eligibility_present, true,
          v_candidate.disposition, v_candidate.disposition, NULL,
          v_transition_kind, v_candidate_revision, v_rule.row_revision,
          v_rule_input_hash, v_expected.candidate_input_hash,
          o_generation_id, v_provider_dataset_id,
          v_expected.source_record_key, v_expected.source_record_hash,
          NULL, NULL, NULL, v_actor, 'rule_match',
          jsonb_strip_nulls(jsonb_build_object(
            'schema_version', 1,
            'generation_kind', p_generation_kind,
            'source_job_id', p_source_job_id::text,
            'reconcile_operation_id', p_reconcile_operation_id::text
          ))
        );
      END IF;
    END IF;

    INSERT INTO feature.theme_candidate_generation_observations (
      generation_id, candidate_id, source_entity_key, feature_id,
      source_record_key, candidate_input_hash
    ) VALUES (
      o_generation_id, v_candidate_id, v_expected.source_entity_key,
      v_expected.feature_id, v_expected.source_record_key,
      v_expected.candidate_input_hash
    );
  END LOOP;

  FOR v_candidate IN
    SELECT candidate.*
    FROM feature.theme_feature_candidates AS candidate
    WHERE candidate.rule_id = p_rule_id
      AND candidate.disposition = 'active'
      AND candidate.eligibility_present
      AND NOT EXISTS (
        SELECT 1
        FROM provider_sync.source_entities AS entity
        JOIN provider_sync.source_links AS link
          ON link.source_entity_key = entity.source_entity_key
        CROSS JOIN LATERAL feature.current_theme_candidate_snapshot(
          p_rule_id, entity.source_entity_key, link.feature_id
        ) AS snapshot
        WHERE entity.provider_dataset_id = v_provider_dataset_id
          AND entity.source_entity_key = candidate.source_entity_key
          AND link.feature_id = candidate.feature_id
      )
    ORDER BY candidate.feature_id, candidate.candidate_id
    FOR UPDATE
  LOOP
    v_reason_code := CASE
      WHEN NOT v_rule.enabled OR v_rule.default_action <> 'candidate'
        OR v_rule.archived_at IS NOT NULL
      THEN 'rule_disabled'
      ELSE 'rule_no_match'
    END;
    UPDATE feature.theme_feature_candidates AS candidate
    SET eligibility_present = false,
        row_revision = candidate.row_revision + 1,
        updated_at = clock_timestamp()
    WHERE candidate.candidate_id = v_candidate.candidate_id
    RETURNING candidate.row_revision INTO STRICT v_candidate_revision;
    PERFORM feature.append_theme_feature_candidate_transition(
      v_candidate.candidate_id, v_candidate.feature_id,
      v_candidate.feature_id, p_rule_id, v_candidate.source_entity_key,
      v_candidate.review_state, v_candidate.review_state,
      true, false, v_candidate.disposition, v_candidate.disposition, NULL,
      'eligibility_remove', v_candidate_revision, v_rule.row_revision,
      v_rule_input_hash, v_candidate.candidate_input_hash,
      o_generation_id, v_provider_dataset_id,
      v_candidate.source_record_key, v_candidate.source_record_hash,
      NULL, NULL, NULL, v_actor, v_reason_code,
      jsonb_strip_nulls(jsonb_build_object(
        'schema_version', 1,
        'generation_kind', p_generation_kind,
        'source_job_id', p_source_job_id::text,
        'reconcile_operation_id', p_reconcile_operation_id::text
      ))
    );
  END LOOP;

  IF (SELECT count(*)
      FROM feature.theme_candidate_generation_observations AS observation
      WHERE observation.generation_id = o_generation_id)
       <> v_expected_candidate_count
     OR EXISTS (
       SELECT 1
       FROM feature.theme_feature_candidates AS candidate
       WHERE candidate.rule_id = p_rule_id
         AND candidate.disposition = 'active'
         AND candidate.eligibility_present
         AND NOT EXISTS (
           SELECT 1
           FROM feature.theme_candidate_generation_observations AS observation
           WHERE observation.generation_id = o_generation_id
             AND observation.candidate_id = candidate.candidate_id
         )
     ) THEN
    RAISE EXCEPTION 'generation observation set is not complete'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_theme_candidate_generation_complete';
  END IF;

  o_observed_candidate_count := v_expected_candidate_count;
  o_eligibility_removed_candidate_count := v_expected_removed_count;
  o_replayed := false;
END
$command$;
"""


_SIGNATURE = (
    "feature.materialize_theme_candidate_generation("
    "uuid,text,uuid,uuid,bigint,text,jsonb)"
)


def upgrade() -> None:
    op.execute(_MATERIALIZE_PROCEDURE_SQL)
    op.execute(f"ALTER PROCEDURE {_SIGNATURE} OWNER TO ktm_curation_command_owner")
    op.execute(
        "GRANT SELECT ON TABLE ops.curation_rule_reconcile_operations, "
        "ops.curation_rule_reconcile_scope_members, ops.import_jobs, "
        "ops.import_job_datasets TO ktm_curation_command_owner"
    )
    for relation, column in (
        ("feature.curated_themes", "row_revision"),
        ("ops.curation_rule_reconcile_operations", "operation_id"),
        ("ops.import_jobs", "job_id"),
    ):
        op.execute(
            f"GRANT UPDATE ({column}) ON TABLE {relation} "
            "TO ktm_curation_command_owner"
        )
    op.execute("SET ROLE ktm_curation_command_owner")
    op.execute(
        f"REVOKE ALL ON PROCEDURE {_SIGNATURE} FROM PUBLIC, "
        "ktm_feature_runtime, ktm_feature_api_runtime, "
        "ktm_feature_dagster_runtime"
    )
    op.execute(
        f"GRANT EXECUTE ON PROCEDURE {_SIGNATURE} "
        "TO ktm_curation_admin_executor, ktm_curation_provider_executor"
    )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError("0108 is forward-only; rebuild with the T-VN-40 release head")
