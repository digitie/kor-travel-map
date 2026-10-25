-- 미호출430 조각. 5인자 dispatcher/typed seal marker/owner ACL과 같은 migration에서 설치한다.
-- 기존 본문에서 RC/prefix/두 capture call site만 바꾼다. generic legacy aggregate는 dispatcher가 보존한다.
CREATE OR REPLACE FUNCTION ops.lock_provider_feature_tracking_protocol(p_finalizing boolean) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_protocol_held boolean;
    v_protocol_exclusive boolean;
    v_lineage_held boolean;
    v_lock_timeout text := current_setting('lock_timeout');
BEGIN
    IF p_finalizing IS NULL THEN
        RAISE EXCEPTION 'provider tracking prefix mode must not be null'
            USING ERRCODE='22023';
    END IF;
    IF p_finalizing AND current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'provider finalization requires READ COMMITTED transaction'
            USING ERRCODE='25001';
    END IF;
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
    INTO v_protocol_held,v_protocol_exclusive
    FROM pg_catalog.pg_locks
    WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
      AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
      AND classid=1369104691 AND objid=115 AND objsubid=2;
    -- canonical advisory_lock_key('kortravelmap:pipeline-lineage:mutation'):
    -- unsigned BLAKE2b64 - 2^63 = 6832465333779826081; bigint lock subid=1.
    SELECT EXISTS(
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
          AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
          AND classid=1590807301 AND objid=1746797985 AND objsubid=1
          AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF p_finalizing AND v_lineage_held AND NOT v_protocol_exclusive THEN
        RAISE EXCEPTION 'provider finalization cannot acquire protocol after lineage'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_prefix';
    END IF;
    IF NOT p_finalizing AND v_protocol_held
       AND NOT (v_protocol_exclusive AND v_lineage_held) THEN
        RAISE EXCEPTION 'provider leaf cannot acquire lineage after a data writer'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_prefix';
    END IF;
    -- 기존 유한 caller timeout은 보존한다. 미설정 direct SQL의 새 L 대기만 유한화한다.
    IF current_setting('lock_timeout')='0' THEN
        PERFORM set_config('lock_timeout','1s',true);
    END IF;
    IF p_finalizing THEN
        PERFORM ops.lock_scoped_feature_write_protocol(true);
    END IF;
    -- 보유 관측이 session lock이어도 성공 경로에는 항상 xact L을 재확보한다.
    -- 관측만으로 session/xact의 과거 취득 순서를 attest하지 않는다.
    PERFORM pg_advisory_xact_lock(6832465333779826081::bigint);
    PERFORM set_config('lock_timeout',v_lock_timeout,true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('lock_timeout',v_lock_timeout,true);
    RAISE;
END;
$$;

CREATE OR REPLACE PROCEDURE feature.seal_provider_curation_snapshot_receipt(IN p_root_job_id uuid, IN p_provider_dataset_id bigint, IN p_sync_scope text, IN p_operation_key text, IN p_expected_input_member_count bigint, IN p_expected_input_set_hash text, OUT o_source_job_id uuid, OUT o_observed_at timestamp with time zone, OUT o_source_entity_count bigint, OUT o_source_input_set_hash text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $_$
DECLARE
  v_child ops.import_jobs%ROWTYPE;
  v_input_member_count bigint;
  v_last_source_modified_at date;
BEGIN
  PERFORM ops.lock_provider_feature_tracking_protocol(true);
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'provider snapshot seal requires READ COMMITTED transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'provider snapshot seal requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  SELECT child.* INTO STRICT v_child
  FROM ops.import_jobs AS child
  JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
  WHERE child.parent_job_id = p_root_job_id
    AND child.kind = 'provider_feature_load'
    AND child.status IN ('queued','running')
    AND child.cancellation_id IS NULL AND child.quarantined_at IS NULL
    AND member.provider_dataset_id = p_provider_dataset_id
    AND member.sync_scope = p_sync_scope
    AND member.operation_key = p_operation_key
  FOR UPDATE OF child;
  IF NOT EXISTS (
    SELECT 1 FROM ops.import_jobs AS root
    WHERE root.job_id = p_root_job_id
      AND root.kind = 'provider_feature_load_run'
      AND root.status = 'running'
      AND root.dagster_run_status IN ('STARTED','CANCELING')
      AND root.dagster_run_id = v_child.dagster_run_id
      AND root.cancellation_id IS NULL AND root.quarantined_at IS NULL
  ) OR (SELECT count(*) FROM ops.import_job_datasets AS member
        WHERE member.job_id = v_child.job_id) <> 1 THEN
    RAISE EXCEPTION 'provider snapshot seal requires one exact running member'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_member';
  END IF;

  PERFORM 1 FROM provider_sync.source_entities AS entity
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY entity.source_entity_key FOR SHARE;
  PERFORM 1
  FROM provider_sync.source_records AS record
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = record.source_entity_key
   AND head.current_source_record_key = record.source_record_key
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY record.source_entity_key, record.source_record_key
  FOR SHARE OF record;
  PERFORM 1
  FROM provider_sync.source_entity_heads AS head
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = head.source_entity_key
  WHERE entity.provider_dataset_id = p_provider_dataset_id
  ORDER BY head.source_entity_key FOR SHARE OF head;

  o_source_job_id := v_child.job_id;
  o_observed_at := clock_timestamp();
  SELECT input.source_entity_count, input.input_member_count,
         input.last_source_modified_at, input.source_input_set_hash
  INTO STRICT o_source_entity_count, v_input_member_count,
       v_last_source_modified_at, o_source_input_set_hash
  FROM feature._member_provider_curation_input_set(
    p_root_job_id,p_provider_dataset_id,p_sync_scope,p_operation_key,'child'
  ) AS input;
  IF p_expected_input_member_count IS NULL
     OR p_expected_input_set_hash !~ '^[0-9a-f]{64}$'
     OR p_expected_input_member_count <> v_input_member_count
     OR p_expected_input_set_hash <> o_source_input_set_hash THEN
    RAISE EXCEPTION 'provider load input changed before child completion'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_snapshot_load_input';
  END IF;

  INSERT INTO ops.curation_provider_snapshot_receipts (
    source_job_id, root_job_id, provider_dataset_id, sync_scope, operation_key,
    observed_at, source_entity_count, input_member_count,
    last_source_modified_at, source_input_set_hash
  )
  SELECT v_child.job_id, p_root_job_id, p_provider_dataset_id, p_sync_scope,
         p_operation_key, o_observed_at, o_source_entity_count,
         v_input_member_count, v_last_source_modified_at,
         o_source_input_set_hash;
END
$_$;

CREATE OR REPLACE PROCEDURE feature.finalize_provider_curation_root(IN p_root_job_id uuid, OUT o_generation_count bigint, OUT o_generation_set_hash text, OUT o_replayed boolean, OUT o_stale_input boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_root ops.import_jobs%ROWTYPE;
  v_seal ops.curation_provider_root_receipts%ROWTYPE;
  v_child record;
  v_rule record;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_input_hash text;
  v_generation_replayed boolean;
  v_source_id uuid;
  v_source_revision bigint;
  v_observation_revision bigint;
  v_row_count integer;
  v_current_count bigint;
  v_current_member_count bigint;
  v_current_hash text;
  v_child_count bigint;
  v_child_hash text;
BEGIN
  PERFORM ops.lock_provider_feature_tracking_protocol(true);
  PERFORM ops.lock_scoped_feature_write_protocol(true);
  o_stale_input := false;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'provider curation root requires READ COMMITTED transaction'
      USING ERRCODE = '25001';
  END IF;
  IF (
       NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member')
     ) AND NOT (
       session_user = 'ktm_feature_service'
       AND current_setting('ktm.curation_cancellation_root', true)
         = p_root_job_id::text
     ) THEN
    RAISE EXCEPTION 'provider curation root requires the provider executor'
      USING ERRCODE = '42501';
  END IF;
  -- Provider load/retirement/notice/merge와 같은 global fence를 relation
  -- lock보다 먼저 잡아 head→link와 Feature→link 경로의 ABBA를 제거한다.
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
  SELECT root.* INTO STRICT v_root FROM ops.import_jobs AS root
  WHERE root.job_id = p_root_job_id FOR UPDATE;
  IF v_root.kind <> 'provider_feature_load_run' OR v_root.status <> 'done'
     OR v_root.dagster_run_status <> 'SUCCESS'
     OR (
       v_root.cancellation_id IS NOT NULL
       AND NOT EXISTS (
         SELECT 1
         FROM ops.pipeline_cancellation_members AS member
         JOIN ops.pipeline_cancellation_runs AS run
           ON run.cancellation_id = member.cancellation_id
          AND run.dagster_run_id = member.dagster_run_id
         WHERE member.cancellation_id = v_root.cancellation_id
           AND member.job_id = v_root.job_id
           AND member.operation_kind = 'provider_feature_load_run'
           AND member.result = 'already_terminal'
           AND member.terminal_status = 'done'
           AND run.result = 'already_terminal'
           AND run.terminal_status = 'SUCCESS'
       )
     ) OR v_root.quarantined_at IS NOT NULL THEN
    RAISE EXCEPTION 'provider curation root requires a successful terminal root'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root';
  END IF;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           receipt.source_job_id::text, receipt.provider_dataset_id,
           receipt.sync_scope, receipt.operation_key, receipt.input_member_count,
           receipt.source_input_set_hash
         ) ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT v_child_count, v_child_hash
  FROM ops.curation_provider_snapshot_receipts AS receipt
  WHERE receipt.root_job_id = p_root_job_id;

  IF EXISTS (
    SELECT 1
    FROM ops.import_jobs AS child
    JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
    WHERE child.parent_job_id = p_root_job_id
      AND child.kind = 'provider_feature_load'
      AND child.quarantined_at IS NULL
      AND (child.payload ->> 'authoritative_snapshot_complete')::boolean
      AND NOT EXISTS (
        SELECT 1 FROM ops.curation_provider_snapshot_receipts AS receipt
        WHERE receipt.source_job_id = child.job_id
          AND receipt.root_job_id = p_root_job_id
          AND receipt.provider_dataset_id = member.provider_dataset_id
          AND receipt.sync_scope = member.sync_scope
          AND receipt.operation_key = member.operation_key
      )
  ) OR EXISTS (
    SELECT 1 FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
      AND NOT EXISTS (
        SELECT 1
        FROM ops.import_jobs AS child
        JOIN ops.import_job_datasets AS member ON member.job_id = child.job_id
        WHERE child.job_id = receipt.source_job_id
          AND child.parent_job_id = p_root_job_id
          AND child.kind = 'provider_feature_load'
          AND child.status = 'done'
          AND child.quarantined_at IS NULL
          AND (child.payload ->> 'authoritative_snapshot_complete')::boolean
          AND member.provider_dataset_id = receipt.provider_dataset_id
          AND member.sync_scope = receipt.sync_scope
          AND member.operation_key = receipt.operation_key
      )
  ) THEN
    RAISE EXCEPTION 'provider curation root child receipt set is inconsistent'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_child_set';
  END IF;
  IF v_child_count = 0 THEN
    o_generation_count := 0;
    o_generation_set_hash := encode(
      x_extension.digest(convert_to('[]', 'UTF8'), 'sha256'), 'hex'
    );
    o_replayed := false;
    RETURN;
  END IF;

  SELECT root_receipt.* INTO v_seal FROM ops.curation_provider_root_receipts AS root_receipt
  WHERE root_receipt.root_job_id = p_root_job_id;
  IF FOUND THEN
    SELECT count(*)::bigint,
           encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
             generation.rule_id::text, generation.generation_id::text,
             generation.generation_input_set_hash
           ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
           'UTF8'), 'sha256'), 'hex')
    INTO STRICT o_generation_count, o_generation_set_hash
    FROM feature.theme_candidate_generations AS generation
    JOIN ops.curation_provider_snapshot_receipts AS receipt
      ON receipt.source_job_id = generation.source_job_id
    WHERE receipt.root_job_id = p_root_job_id
      AND generation.generation_kind = 'provider_full_snapshot';
    IF v_seal.child_receipt_count <> v_child_count
       OR v_seal.child_receipt_set_hash <> v_child_hash
       OR v_seal.generation_count <> o_generation_count
       OR v_seal.generation_set_hash <> o_generation_set_hash THEN
      RAISE EXCEPTION 'provider curation root replay receipt is inconsistent'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_curation_root_replay';
    END IF;
    o_replayed := true;
    RETURN;
  END IF;

  -- ADR-111: one exclusive gate instead of one lock per touched Feature.  This
  -- transaction already holds feature-curation-write, so it must not queue behind
  -- an admin bulk command and stall provider loads: try once and let the reconcile
  -- sensor retry on its next tick.
  IF NOT pg_try_advisory_xact_lock(hashtextextended('feature-write-all', 0)) THEN
    RAISE EXCEPTION 'feature-write-all gate is busy; provider curation root retries later'
      USING ERRCODE = '55P03';
  END IF;
  PERFORM 1
  FROM provider_sync.source_links AS link
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.provider_dataset_id = entity.provider_dataset_id
  WHERE receipt.root_job_id = p_root_job_id
  ORDER BY link.source_entity_key, link.feature_id
  FOR SHARE OF link;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));

  -- Validate every immutable child seal before the first catalog/candidate DML.
  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    SELECT input.source_entity_count, input.input_member_count,
           input.source_input_set_hash
    INTO STRICT v_current_count, v_current_member_count, v_current_hash
    FROM feature._member_provider_curation_input_set(
      p_root_job_id,v_child.provider_dataset_id,v_child.sync_scope,v_child.operation_key,'root'
    ) AS input;
    IF v_current_count <> v_child.source_entity_count
       OR v_current_member_count <> v_child.input_member_count
       OR v_current_hash <> v_child.source_input_set_hash THEN
      o_generation_count := 0;
      o_generation_set_hash := encode(
        x_extension.digest(convert_to('[]', 'UTF8'), 'sha256'), 'hex'
      );
      o_replayed := false;
      o_stale_input := true;
      RETURN;
    END IF;
  END LOOP;

  FOR v_child IN
    SELECT receipt.* FROM ops.curation_provider_snapshot_receipts AS receipt
    WHERE receipt.root_job_id = p_root_job_id
    ORDER BY receipt.provider_dataset_id, receipt.sync_scope, receipt.operation_key
  LOOP
    IF EXISTS (SELECT 1 FROM feature.curated_sources AS source
               WHERE source.provider_dataset_id = v_child.provider_dataset_id
                 AND source.archived_at IS NULL) THEN
      CALL feature.refresh_curated_source_observation(
        v_child.provider_dataset_id, v_child.source_job_id,
        v_source_id, v_source_revision, v_observation_revision, v_row_count
      );
    END IF;
    FOR v_rule IN
      SELECT rule.rule_id FROM feature.curated_source_rules AS rule
      JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
      JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
      WHERE source.provider_dataset_id = v_child.provider_dataset_id
        AND source.archived_at IS NULL AND theme.archived_at IS NULL
        AND rule.archived_at IS NULL AND rule.enabled
        AND rule.default_action = 'candidate'
      ORDER BY rule.rule_id
    LOOP
      CALL feature.materialize_theme_candidate_generation(
        v_rule.rule_id, 'provider_full_snapshot', v_child.source_job_id,
        NULL, NULL, NULL,
        jsonb_build_object('schema_version', 1, 'sync_scope', v_child.sync_scope,
                           'operation_key', v_child.operation_key),
        v_generation_id, v_observed, v_removed, v_input_hash, v_generation_replayed
      );
    END LOOP;
  END LOOP;

  SELECT count(*)::bigint,
         encode(x_extension.digest(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
           generation.rule_id::text, generation.generation_id::text,
           generation.generation_input_set_hash
         ) ORDER BY generation.rule_id, generation.source_job_id)::text, '[]'),
         'UTF8'), 'sha256'), 'hex')
  INTO STRICT o_generation_count, o_generation_set_hash
  FROM feature.theme_candidate_generations AS generation
  JOIN ops.curation_provider_snapshot_receipts AS receipt
    ON receipt.source_job_id = generation.source_job_id
  WHERE receipt.root_job_id = p_root_job_id
    AND generation.generation_kind = 'provider_full_snapshot';
  INSERT INTO ops.curation_provider_root_receipts (
    root_job_id, child_receipt_count, child_receipt_set_hash,
    generation_count, generation_set_hash
  ) VALUES (p_root_job_id, v_child_count, v_child_hash,
            o_generation_count, o_generation_set_hash);
  o_replayed := false;
END
$$;

CREATE OR REPLACE PROCEDURE feature.purge_manual_feature(IN p_feature_id uuid, IN p_reason_code text, IN p_release_identity boolean, IN p_actor text, IN p_command_id bigint, OUT o_purge_id uuid, OUT o_outcome text, OUT o_captured_relation_count integer, OUT o_captured_row_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
    v_legacy_feature_id text;
    v_command ops.domain_commands%ROWTYPE;
    v_blockers text;
    v_relation text;
    v_predicate text;
    v_rows jsonb;
    v_captured jsonb := '{}'::jsonb;
    v_relation_count integer := 0;
    v_row_count integer := 0;
    v_existing feature.manual_feature_purge_records%ROWTYPE;
BEGIN
    IF p_feature_id IS NULL
       OR p_reason_code NOT IN ('mistaken_creation', 'erasure_required')
       OR p_release_identity IS NULL
       OR coalesce(btrim(p_actor), '') = ''
       OR p_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature purge has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    PERFORM ops.lock_scoped_feature_write_protocol(true);
    SELECT * INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.manual-feature.purge.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_command_id
       ) THEN
        RAISE EXCEPTION 'manual Feature purge command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = p_feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target has no manual identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    IF v_claim.purged_by_command_id IS NOT NULL THEN
        SELECT * INTO v_existing
        FROM feature.manual_feature_purge_records AS record
        WHERE record.feature_id = p_feature_id;
        o_purge_id := v_existing.purge_id;
        o_outcome := 'already_purged';
        o_captured_relation_count := v_existing.captured_relation_count;
        o_captured_row_count := v_existing.captured_row_count;
        RETURN;
    END IF;

    PERFORM 1
    FROM feature.features AS feature
    WHERE feature.feature_id = p_feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target Feature does not exist'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    -- T-VN-39 뒤 legacy `f_*` 문자열은 `feature.features`에 남아 있지 않다. 유일한
    -- 잔존처인 alias map에서 읽어 purge 증거의 `legacy_feature_id`에 남긴다.
    --
    -- **계약 선결조건**: `feature.manual_feature_purge_records.legacy_feature_id`는
    -- nullable이어야 한다. legacy alias 발급이 멎은 뒤 태어난 Feature에는 legacy id가
    -- 애초에 없고 그것은 결손이 아니라 참이다. 개명하며 NOT NULL을 함께 끌고 오면
    -- 그런 Feature의 purge가 evidence INSERT에서 23502로 죽고,
    -- `manual_feature_purge_repo._raise_purge_error`는 `{23514, 42501}` 밖 sqlstate를
    -- 그대로 re-raise하므로 catch-all 500이 된다.
    --
    -- `alias <> p_feature_id::text`는 `feature.ensure_features_legacy_alias`가 재키
    -- 뒤에도 살아남아 `alias = <uuid 문자열>` 행을 새로 심는 경우를 배제한다 — uuid를
    -- `legacy_feature_id`로 적재하면 append-only 증거가 영구히 오염된다. 캐스트는
    -- 파라미터에 붙으므로 `idx_feature_aliases_feature` 탐색은 그대로다.
    --
    -- `ck_feature_aliases_legacy_identity`(alias = feature_id)는 text=uuid가 되어
    -- 재키와 함께 사라진다. 그러면 한 Feature에 legacy alias가 둘 이상일 수 있고
    -- `SELECT ... INTO`는 다중 행에서 에러 없이 임의의 한 행을 고르므로 순서를 못 박는다.
    SELECT legacy.alias INTO v_legacy_feature_id
    FROM feature.feature_aliases AS legacy
    WHERE legacy.feature_id = p_feature_id
      AND legacy.alias_kind = 'legacy_feature_id'
      AND legacy.alias <> p_feature_id::text
    ORDER BY legacy.alias
    LIMIT 1;

    SELECT string_agg(blocked.relation_name || '=' || blocked.tally::text, ', '
                      ORDER BY blocked.relation_name)
    INTO v_blockers
    FROM (
        SELECT feature.qualified_relation_name(constraint_row.conrelid) AS relation_name,
               count(*) AS tally
        FROM pg_catalog.pg_constraint AS constraint_row
        CROSS JOIN LATERAL (
            SELECT format(
                'SELECT count(*) FROM %s AS child WHERE (%s) IN'
                ' (SELECT %s FROM feature.features WHERE feature_id = %L)',
                feature.qualified_relation_name(constraint_row.conrelid),
                (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = position.attnum),
                (SELECT string_agg(format('%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.confrelid
                  AND attribute.attnum = position.attnum),
                p_feature_id
            ) AS statement
        ) AS built
        CROSS JOIN LATERAL feature.count_rows_dynamic(built.statement) AS counted(tally)
        WHERE constraint_row.confrelid = 'feature.features'::regclass
          AND constraint_row.contype = 'f'
          -- **`'a'`(NO ACTION)도 막는다.** 지연되지 않은 FK에서 NO ACTION은 RESTRICT와
          -- 똑같이 삭제를 거부한다. `'r'`만 보면 그런 참조자가 probe를 통과한 뒤
          -- DELETE에서 raw 23503으로 죽고, 그러면 "이름을 대는 거부"라는 이 설계의
          -- 요지가 그 경로에서만 조용히 무효가 된다.
          --
          -- 지금 그런 FK는 정확히 하나다 — `ops.feature_requests.resolved_feature_id`.
          -- 그리고 그것은 **M04 승인으로 태어난 manual Feature 전부**에 달린다
          -- (`approve_feature_request_with_initial_state`가 claim을 심고 같은
          -- 트랜잭션에서 `resolved_feature_id`를 세운다). 즉 드문 경로가 아니다.
          AND constraint_row.confdeltype IN ('r', 'a')
          AND counted.tally > 0
        GROUP BY constraint_row.conrelid
    ) AS blocked;

    IF v_blockers IS NOT NULL THEN
        RAISE EXCEPTION 'purge target is bound by immutable evidence: %', v_blockers
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_evidence_bound';
    END IF;

    IF p_reason_code = 'mistaken_creation' THEN
        FOR v_relation, v_predicate IN
            SELECT feature.qualified_relation_name(constraint_row.conrelid),
                   string_agg(
                       format(
                           '(%s) IN (SELECT %s FROM feature.features WHERE feature_id = %L)',
                           (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.conrelid
                             AND attribute.attnum = position.attnum),
                           (SELECT string_agg(format('%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.confrelid
                             AND attribute.attnum = position.attnum),
                           p_feature_id
                       ),
                       ' OR '
                   )
            FROM pg_catalog.pg_constraint AS constraint_row
            WHERE constraint_row.confrelid = 'feature.features'::regclass
              AND constraint_row.contype = 'f'
              -- **`'n'`(SET NULL)도 담는다.** cascade는 행을 지우고 SET NULL은 행을
              -- 고치지만, 복구점의 관점에서는 둘 다 "이 삭제가 되돌릴 수 없게 바꾸는
              -- 것"이다. 담지 않으면 어느 행의 어느 컬럼이 NULL이 됐는지 알 수 없다.
              AND constraint_row.confdeltype IN ('c', 'n')
            GROUP BY constraint_row.conrelid
            ORDER BY feature.qualified_relation_name(constraint_row.conrelid)
        LOOP
            EXECUTE format(
                'SELECT coalesce(jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text), ''[]''::jsonb)'
                ' FROM %s AS child WHERE %s',
                v_relation, v_predicate
            ) INTO v_rows;
            IF jsonb_array_length(v_rows) > 0 THEN
                v_captured := v_captured || jsonb_build_object(v_relation, v_rows);
                v_relation_count := v_relation_count + 1;
                v_row_count := v_row_count + jsonb_array_length(v_rows);
            END IF;
        END LOOP;
        v_captured := v_captured || jsonb_build_object(
            'feature.features',
            (SELECT jsonb_build_array(to_jsonb(feature))
             FROM feature.features AS feature
             WHERE feature.feature_id = p_feature_id)
        );
        v_relation_count := v_relation_count + 1;
        v_row_count := v_row_count + 1;
    END IF;

    UPDATE feature.manual_feature_identity_claims
    SET purged_by_command_id = p_command_id,
        purged_at = clock_timestamp(),
        identity_released = p_release_identity
    WHERE feature_id = p_feature_id;

    INSERT INTO feature.manual_feature_purge_records (
        feature_id, legacy_feature_id, reason_code, identity_released,
        purged_by_command_id, purged_by_actor, captured_rows,
        captured_relation_count, captured_row_count, captured_sha256
    ) VALUES (
        p_feature_id, v_legacy_feature_id, p_reason_code, p_release_identity,
        p_command_id, p_actor,
        CASE WHEN p_reason_code = 'mistaken_creation' THEN v_captured ELSE NULL END,
        v_relation_count, v_row_count,
        encode(
            x_extension.digest(
                convert_to(
                    CASE WHEN p_reason_code = 'mistaken_creation'
                         THEN v_captured::text
                         ELSE p_feature_id::text
                    END,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    ) RETURNING purge_id INTO o_purge_id;

    DELETE FROM feature.features WHERE feature_id = p_feature_id;

    o_outcome := 'purged';
    o_captured_relation_count := v_relation_count;
    o_captured_row_count := v_row_count;
END
$$;
