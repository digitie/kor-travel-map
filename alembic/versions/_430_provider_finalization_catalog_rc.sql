-- 기존 catalog 내부 SD의 RC provider-finalizer 진입만 추가한다. SER/admin 의미·권한은 유지한다.

CREATE OR REPLACE PROCEDURE feature.refresh_curated_source_observation(IN p_provider_dataset_id bigint, IN p_import_job_id uuid, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_row_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops'
    AS $$
DECLARE
  v_source feature.curated_sources%ROWTYPE;
  v_snapshot ops.curation_provider_snapshot_receipts%ROWTYPE;
  v_receipt ops.curation_source_observation_receipts%ROWTYPE;
  v_latest_receipt ops.curation_source_observation_receipts%ROWTYPE;
BEGIN
  -- 기존 SER은 그대로다. RC는 정본 finalizer가 이미 취득한 actual P EX+L만 관측한다.
  -- pg_locks는 session/xact의 과거 순서를 attest하지 않는다. 새 잠금/승격은 없다.
  IF current_setting('transaction_isolation') <> 'serializable' AND NOT (
    current_setting('transaction_isolation') = 'read committed'
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1369104691 AND objid=115 AND objsubid=2 AND mode='ExclusiveLock'
    )
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1590807301 AND objid=1746797985 AND objsubid=1 AND mode='ExclusiveLock'
    )
  ) THEN
    RAISE EXCEPTION 'source observation requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF (
       NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     ) AND NOT (
       session_user = 'ktm_feature_service'
       AND current_setting('ktm.curation_cancellation_root', true) IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'source observation requires the provider executor' USING ERRCODE = '42501';
  END IF;
  SELECT snapshot.* INTO STRICT v_snapshot
  FROM ops.curation_provider_snapshot_receipts AS snapshot
  WHERE snapshot.source_job_id = p_import_job_id
    AND snapshot.provider_dataset_id = p_provider_dataset_id;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS child
    JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
    WHERE child.job_id = p_import_job_id AND child.status = 'done'
      AND root.job_id = v_snapshot.root_job_id AND root.status = 'done'
      AND root.dagster_run_status = 'SUCCESS'
      AND child.quarantined_at IS NULL AND root.quarantined_at IS NULL
      AND (
        (child.cancellation_id IS NULL AND root.cancellation_id IS NULL)
        OR (
          session_user = 'ktm_feature_service'
          AND root.job_id::text = current_setting(
            'ktm.curation_cancellation_root', true
          )
          AND child.cancellation_id = root.cancellation_id
          AND EXISTS (
            SELECT 1
            FROM ops.pipeline_cancellation_members AS member
            JOIN ops.pipeline_cancellation_runs AS run
              ON run.cancellation_id = member.cancellation_id
             AND run.dagster_run_id = member.dagster_run_id
            WHERE member.cancellation_id = root.cancellation_id
              AND member.job_id = root.job_id
              AND member.result = 'already_terminal'
              AND member.terminal_status = 'done'
              AND run.result = 'already_terminal'
              AND run.terminal_status = 'SUCCESS'
          )
        )
      )
  ) THEN
    RAISE EXCEPTION 'source observation requires a sealed terminal root member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_job';
  END IF;
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id FOR UPDATE;
  SELECT receipt.* INTO v_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id AND receipt.import_job_id = p_import_job_id;
  IF FOUND THEN
    o_source_id := v_receipt.source_id;
    o_source_revision := v_receipt.source_revision;
    o_observation_revision := v_receipt.observation_revision;
    o_row_count := v_receipt.row_count;
    RETURN;
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'archived source cannot receive new observations'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  SELECT receipt.* INTO v_latest_receipt
  FROM ops.curation_source_observation_receipts AS receipt
  WHERE receipt.source_id = v_source.source_id
  ORDER BY receipt.observed_at DESC, receipt.import_job_id DESC LIMIT 1;
  IF FOUND AND (v_snapshot.observed_at, p_import_job_id)
       <= (v_latest_receipt.observed_at, v_latest_receipt.import_job_id) THEN
    RAISE EXCEPTION 'source observation job is older than the current receipt'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_observation_order';
  END IF;
  IF v_snapshot.source_entity_count > 2147483647 THEN
    RAISE EXCEPTION 'source observation row count exceeds the catalog range'
      USING ERRCODE = '22003';
  END IF;
  o_row_count := v_snapshot.source_entity_count::integer;
  UPDATE feature.curated_sources AS source
  SET last_checked_at = v_snapshot.observed_at, row_count = o_row_count,
      last_source_modified_at = v_snapshot.last_source_modified_at,
      next_expected_at = CASE source.update_cycle
        WHEN 'realtime' THEN v_snapshot.observed_at::date
        WHEN 'daily' THEN v_snapshot.observed_at::date + 1
        WHEN 'weekly' THEN v_snapshot.observed_at::date + 7
        WHEN 'monthly' THEN (v_snapshot.observed_at + interval '1 month')::date
        WHEN 'annual' THEN (v_snapshot.observed_at + interval '1 year')::date
        ELSE NULL END,
      observation_revision = source.observation_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = v_source.source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  INSERT INTO ops.curation_source_observation_receipts (
    source_id, import_job_id, observed_at, source_revision,
    observation_revision, row_count, last_source_modified_at, source_input_set_hash
  ) VALUES (
    o_source_id, p_import_job_id, v_snapshot.observed_at, o_source_revision,
    o_observation_revision, o_row_count, v_snapshot.last_source_modified_at,
    v_snapshot.source_input_set_hash
  );
END
$$;

CREATE OR REPLACE PROCEDURE feature.materialize_theme_candidate_generation(IN p_rule_id uuid, IN p_generation_kind text, IN p_source_job_id uuid, IN p_reconcile_operation_id uuid, IN p_command_id bigint, IN p_generation_key text, IN p_context jsonb, OUT o_generation_id uuid, OUT o_observed_candidate_count bigint, OUT o_eligibility_removed_candidate_count bigint, OUT o_generation_input_set_hash text, OUT o_replayed boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_rule_hint feature.curated_source_rules%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
  v_operation ops.curation_rule_reconcile_operations%ROWTYPE;
  v_source_job ops.import_jobs%ROWTYPE;
  v_existing_generation feature.theme_candidate_generations%ROWTYPE;
  v_candidate feature.theme_feature_candidates%ROWTYPE;
  v_expected record;
  v_feature_id uuid;
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
  -- 기존 SER은 그대로다. RC는 정본 finalizer가 이미 취득한 actual P EX+L만 관측한다.
  -- pg_locks는 session/xact의 과거 순서를 attest하지 않는다. 새 잠금/승격은 없다.
  IF current_setting('transaction_isolation') <> 'serializable' AND NOT (
    current_setting('transaction_isolation') = 'read committed'
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1369104691 AND objid=115 AND objsubid=2 AND mode='ExclusiveLock'
    )
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1590807301 AND objid=1746797985 AND objsubid=1 AND mode='ExclusiveLock'
    )
    AND p_generation_kind IS NOT DISTINCT FROM 'provider_full_snapshot'
  ) THEN
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
        (
          NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
        ) AND NOT (
          session_user = 'ktm_feature_service'
          AND EXISTS (
            SELECT 1 FROM ops.import_jobs AS source_job
            WHERE source_job.job_id = p_source_job_id
              AND source_job.parent_job_id::text = current_setting(
                'ktm.curation_cancellation_root', true
              )
          )
        )
      )) OR (NOT v_is_provider AND (
        NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
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

  -- ADR-111: one exclusive gate instead of one lock per touched Feature.
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));
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
    SELECT 'feature'::text, link.feature_id::text
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
          SELECT 'feature'::text, link.feature_id::text
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
          SELECT 'feature'::text, link.feature_id::text
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
       OR (
         v_source_job.cancellation_id IS NOT NULL
         AND NOT (
           session_user = 'ktm_feature_service'
           AND v_source_job.parent_job_id::text = current_setting(
             'ktm.curation_cancellation_root', true
           )
           AND EXISTS (
             SELECT 1
             FROM ops.import_jobs AS root
             JOIN ops.pipeline_cancellation_members AS cancellation_member
               ON cancellation_member.cancellation_id = root.cancellation_id
              AND cancellation_member.job_id = root.job_id
             JOIN ops.pipeline_cancellation_runs AS cancellation_run
               ON cancellation_run.cancellation_id = cancellation_member.cancellation_id
              AND cancellation_run.dagster_run_id = cancellation_member.dagster_run_id
             WHERE root.job_id = v_source_job.parent_job_id
               AND root.cancellation_id = v_source_job.cancellation_id
               AND cancellation_member.result = 'already_terminal'
               AND cancellation_member.terminal_status = 'done'
               AND cancellation_run.result = 'already_terminal'
               AND cancellation_run.terminal_status = 'SUCCESS'
           )
         )
       )
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
           AND (
             root.cancellation_id IS NULL
             OR (
               session_user = 'ktm_feature_service'
               AND root.job_id::text = current_setting(
                 'ktm.curation_cancellation_root', true
               )
               AND root.cancellation_id = v_source_job.cancellation_id
             )
           )
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
       )
       OR (
         v_source_job.payload ? 'candidate_generation_sealed_at'
         AND NOT EXISTS (
           SELECT 1
           FROM feature.theme_candidate_generations AS generation
           WHERE generation.rule_id = p_rule_id
             AND generation.source_job_id = p_source_job_id
             AND generation.generation_kind = 'provider_full_snapshot'
         )
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
$$;

CREATE OR REPLACE PROCEDURE feature.sync_concierge_theme_catalog(IN p_provider_dataset_id bigint, IN p_import_job_id uuid, OUT o_themes_created bigint, OUT o_themes_updated bigint, OUT o_rules_created bigint, OUT o_rules_updated bigint, OUT o_rules_archived bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_source_id uuid;
  v_group record;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_input_hash text;
  v_replayed boolean;
  v_metadata jsonb;
  v_selector jsonb;
BEGIN
  -- 기존 SER은 그대로다. RC는 정본 finalizer가 이미 취득한 actual P EX+L만 관측한다.
  -- pg_locks는 session/xact의 과거 순서를 attest하지 않는다. 새 잠금/승격은 없다.
  IF current_setting('transaction_isolation') <> 'serializable' AND NOT (
    current_setting('transaction_isolation') = 'read committed'
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1369104691 AND objid=115 AND objsubid=2 AND mode='ExclusiveLock'
    )
    AND EXISTS (
      SELECT 1 FROM pg_catalog.pg_locks
      WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
        AND classid=1590807301 AND objid=1746797985 AND objsubid=1 AND mode='ExclusiveLock'
    )
  ) THEN
    RAISE EXCEPTION 'concierge catalog sync requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF current_user <> 'ktm_curation_command_owner'
     OR NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'concierge catalog sync is an internal provider command'
      USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = receipt.provider_dataset_id
    WHERE receipt.source_job_id = p_import_job_id
      AND receipt.provider_dataset_id = p_provider_dataset_id
      AND dataset.provider = 'kor-travel-concierge-youtube'
      AND dataset.dataset_key = 'youtube_place_candidates'
  ) THEN
    o_themes_created := 0;
    o_themes_updated := 0;
    o_rules_created := 0;
    o_rules_updated := 0;
    o_rules_archived := 0;
    RETURN;
  END IF;

  SELECT source.source_id INTO STRICT v_source_id
  FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id
    AND source.archived_at IS NULL
  FOR UPDATE;

  CREATE TEMPORARY TABLE IF NOT EXISTS pg_temp.tvn40_concierge_groups (
    grouping_kind text NOT NULL,
    grouping_id text NOT NULL,
    grouping_title text NOT NULL,
    theme_slug text NOT NULL,
    detail_selector jsonb NOT NULL,
    feature_count bigint NOT NULL,
    PRIMARY KEY (grouping_kind, grouping_id),
    UNIQUE (theme_slug)
  ) ON COMMIT DROP;
  TRUNCATE pg_temp.tvn40_concierge_groups;

  INSERT INTO pg_temp.tvn40_concierge_groups (
    grouping_kind, grouping_id, grouping_title, theme_slug,
    detail_selector, feature_count
  )
  WITH current_features AS (
    SELECT DISTINCT feature.feature_id, place.payload
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS record
      ON record.source_entity_key = head.source_entity_key
     AND record.source_record_key = head.current_source_record_key
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS feature ON feature.feature_id = link.feature_id
    JOIN feature.feature_places AS place ON place.feature_id = feature.feature_id
    WHERE entity.provider_dataset_id = p_provider_dataset_id
      AND feature.lifecycle_state = 'active'
      AND feature.publication_state = 'published'
      AND feature.quality_state = 'valid'
  ), expanded AS (
    SELECT feature_id, 'channel'::text AS grouping_kind,
           payload #>> '{kor_travel_concierge,youtube,channel_id}' AS grouping_id,
           payload #>> '{kor_travel_concierge,youtube,channel_title}' AS grouping_title,
           'concierge-yt-'::text AS slug_prefix,
           ARRAY['payload','kor_travel_concierge','youtube','channel_id']::text[] AS selector_path
    FROM current_features
    UNION ALL
    SELECT feature_id, 'playlist'::text,
           payload #>> '{kor_travel_concierge,youtube,playlist_id}',
           payload #>> '{kor_travel_concierge,youtube,playlist_title}',
           'concierge-pl-'::text,
           ARRAY['payload','kor_travel_concierge','youtube','playlist_id']::text[]
    FROM current_features
  )
  SELECT grouping_kind, grouping_id,
         COALESCE(max(NULLIF(btrim(grouping_title), '')), min(slug_prefix) || grouping_id),
         min(slug_prefix) || grouping_id,
         jsonb_build_object('path', min(selector_path), 'value', grouping_id),
         count(DISTINCT feature_id)::bigint
  FROM expanded
  WHERE NULLIF(btrim(grouping_id), '') IS NOT NULL
  GROUP BY grouping_kind, grouping_id;

  -- Only exact legacy rows produced by the retired synchronizer may acquire
  -- provider ownership.  A manually-created prefix collision remains fatal.
  UPDATE feature.curated_themes AS theme
  SET owner_kind = 'provider_dataset',
      owner_provider_dataset_id = p_provider_dataset_id,
      row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.owner_kind IS NULL
    AND theme.owner_provider_dataset_id IS NULL
    AND EXISTS (
      SELECT 1 FROM ops.curation_concierge_legacy_owner_manifest AS manifest
      WHERE manifest.entity_kind = 'theme' AND manifest.entity_id = theme.theme_id
        AND manifest.before_row_revision = theme.row_revision
        AND manifest.before_input_hash = encode(x_extension.digest(convert_to(
          jsonb_build_array(theme.theme_id::text, theme.row_revision,
                            theme.theme_slug, theme.metadata)::text,
          'UTF8'), 'sha256'), 'hex')
    );
  UPDATE feature.curated_source_rules AS rule
  SET owner_kind = 'provider_dataset',
      owner_provider_dataset_id = p_provider_dataset_id,
      row_revision = rule.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE rule.owner_kind IS NULL
    AND rule.owner_provider_dataset_id IS NULL
    AND rule.source_id = v_source_id
    AND EXISTS (
      SELECT 1 FROM ops.curation_concierge_legacy_owner_manifest AS manifest
      WHERE manifest.entity_kind = 'rule' AND manifest.entity_id = rule.rule_id
        AND manifest.before_row_revision = rule.row_revision
        AND manifest.before_input_hash = encode(x_extension.digest(convert_to(
          jsonb_build_array(rule.rule_id::text, rule.row_revision,
                            rule.theme_id::text, rule.source_id::text,
                            rule.metadata)::text,
          'UTF8'), 'sha256'), 'hex')
    )
    AND EXISTS (
      SELECT 1 FROM feature.curated_themes AS theme
      WHERE theme.theme_id = rule.theme_id
        AND theme.owner_kind = 'provider_dataset'
        AND theme.owner_provider_dataset_id = p_provider_dataset_id
    );

  o_themes_created := 0;
  o_themes_updated := 0;
  o_rules_created := 0;
  o_rules_updated := 0;
  o_rules_archived := 0;
  FOR v_group IN
    SELECT * FROM pg_temp.tvn40_concierge_groups
    ORDER BY grouping_kind, grouping_id
  LOOP
    v_metadata := jsonb_build_object(
      'concierge_kind', v_group.grouping_kind,
      'concierge_value', v_group.grouping_id,
      'poi_count', v_group.feature_count,
      'seed', 'sync_concierge_themes'
    );
    v_selector := v_group.detail_selector;
    SELECT theme.* INTO v_theme
    FROM feature.curated_themes AS theme
    WHERE theme.theme_slug = v_group.theme_slug
    FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO feature.curated_themes (
        theme_slug, theme_name, theme_description, theme_group,
        default_curated, visibility, metadata, row_revision, archived_at,
        owner_kind, owner_provider_dataset_id, updated_at
      ) VALUES (
        v_group.theme_slug, v_group.grouping_title, '', 'media', false, 'public',
        v_metadata, 1, NULL, 'provider_dataset', p_provider_dataset_id,
        clock_timestamp()
      ) RETURNING * INTO STRICT v_theme;
      o_themes_created := o_themes_created + 1;
    ELSE
      IF v_theme.owner_kind IS DISTINCT FROM 'provider_dataset'
         OR v_theme.owner_provider_dataset_id IS DISTINCT FROM p_provider_dataset_id THEN
        RAISE EXCEPTION 'concierge theme slug collides with another owner: %', v_group.theme_slug
          USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_theme_owner';
      END IF;
      IF (v_theme.theme_name, v_theme.theme_group, v_theme.visibility,
          v_theme.metadata, v_theme.archived_at IS NULL)
         IS DISTINCT FROM
         (v_group.grouping_title, 'media'::text, 'public'::text,
          v_metadata, true) THEN
        UPDATE feature.curated_themes AS theme
        SET theme_name = v_group.grouping_title,
            theme_group = 'media', visibility = 'public', metadata = v_metadata,
            archived_at = NULL, row_revision = theme.row_revision + 1,
            updated_at = clock_timestamp()
        WHERE theme.theme_id = v_theme.theme_id
        RETURNING * INTO STRICT v_theme;
        o_themes_updated := o_themes_updated + 1;
      END IF;
    END IF;

    IF (SELECT count(*) FROM feature.curated_source_rules AS rule
        WHERE rule.theme_id = v_theme.theme_id AND rule.source_id = v_source_id) > 1 THEN
      RAISE EXCEPTION 'concierge theme has ambiguous source rules: %', v_theme.theme_id
        USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_theme_rule';
    END IF;
    SELECT rule.* INTO v_rule
    FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = v_theme.theme_id AND rule.source_id = v_source_id
    FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO feature.curated_source_rules (
        theme_id, source_id, place_kind, category, region_scope,
        detail_selector, default_action, priority, enabled, metadata,
        row_revision, archived_at, owner_kind, owner_provider_dataset_id, updated_at
      ) VALUES (
        v_theme.theme_id, v_source_id, 'youtube_place_candidate', NULL, '{}'::jsonb,
        v_selector, 'candidate',
        LEAST(v_group.feature_count, 2147483647)::integer, true,
        jsonb_build_object('curation_relation', 'theme_area_anchor'),
        1, NULL, 'provider_dataset', p_provider_dataset_id, clock_timestamp()
      ) RETURNING * INTO STRICT v_rule;
      o_rules_created := o_rules_created + 1;
    ELSE
      IF v_rule.owner_kind IS DISTINCT FROM 'provider_dataset'
         OR v_rule.owner_provider_dataset_id IS DISTINCT FROM p_provider_dataset_id THEN
        RAISE EXCEPTION 'concierge rule collides with another owner: %', v_rule.rule_id
          USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_rule_owner';
      END IF;
      IF (v_rule.place_kind, v_rule.category, v_rule.region_scope,
          v_rule.detail_selector, v_rule.default_action, v_rule.priority,
          v_rule.enabled, v_rule.archived_at IS NULL)
         IS DISTINCT FROM
         ('youtube_place_candidate'::text, NULL::text, '{}'::jsonb,
          v_selector, 'candidate'::text,
          LEAST(v_group.feature_count, 2147483647)::integer,
          true, true) THEN
        UPDATE feature.curated_source_rules AS rule
        SET place_kind = 'youtube_place_candidate', category = NULL,
            region_scope = '{}'::jsonb, detail_selector = v_selector,
            default_action = 'candidate',
            priority = LEAST(v_group.feature_count, 2147483647)::integer,
            enabled = true, archived_at = NULL,
            row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
        WHERE rule.rule_id = v_rule.rule_id;
        o_rules_updated := o_rules_updated + 1;
      END IF;
    END IF;
  END LOOP;

  -- Removed authoritative groups first materialize an empty expected set so
  -- candidate eligibility is audited before their catalog rows are archived.
  FOR v_rule IN
    SELECT rule.*
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
    WHERE rule.source_id = v_source_id
      AND rule.owner_kind = 'provider_dataset'
      AND rule.owner_provider_dataset_id = p_provider_dataset_id
      AND rule.archived_at IS NULL
      AND theme.owner_kind = 'provider_dataset'
      AND theme.owner_provider_dataset_id = p_provider_dataset_id
      AND NOT EXISTS (
        SELECT 1 FROM pg_temp.tvn40_concierge_groups AS desired
        WHERE desired.theme_slug = theme.theme_slug
      )
    ORDER BY rule.rule_id
  LOOP
    CALL feature.materialize_theme_candidate_generation(
      v_rule.rule_id, 'provider_full_snapshot', p_import_job_id,
      NULL, NULL, NULL, jsonb_build_object(
        'schema_version', 1, 'reason_code', 'catalog_archived'
      ), v_generation_id, v_observed, v_removed, v_input_hash, v_replayed
    );
    UPDATE feature.curated_source_rules AS rule
    SET enabled = false, archived_at = clock_timestamp(),
        row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
    WHERE rule.rule_id = v_rule.rule_id;
    o_rules_archived := o_rules_archived + 1;
  END LOOP;
  UPDATE feature.curated_themes AS theme
  SET archived_at = clock_timestamp(), row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.owner_kind = 'provider_dataset'
    AND theme.owner_provider_dataset_id = p_provider_dataset_id
    AND theme.archived_at IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM pg_temp.tvn40_concierge_groups AS desired
      WHERE desired.theme_slug = theme.theme_slug
    );
END
$$;
