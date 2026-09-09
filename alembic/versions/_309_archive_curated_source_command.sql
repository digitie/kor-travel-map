SET ROLE ktm_curation_command_owner;

DROP PROCEDURE feature.archive_curated_source_command(uuid, bigint, bigint, text, text);

CREATE PROCEDURE feature.archive_curated_source_command(IN p_source_id uuid, IN p_expected_source_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_generation_count bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_source feature.curated_sources%ROWTYPE;
  v_rule_id uuid;
  v_rule_revision bigint;
  -- 셋 다 재키 후 uuid를 담는다. text로 둬도 plpgsql 대입이 I/O 캐스트로 살려주지만,
  -- 형제 `_309_materialize_theme_candidate_generation.sql`이 같은 UNION을 도는
  -- 루프 변수를 uuid로 옮겼다 — 이 파일만 text로 남으면 다음 사람이 둘 중
  -- 어느 쪽이 규칙인지 묻게 된다. lock 키는 `text || anynonarray`가 uuid의
  -- canonical 표기를 내므로 바이트 단위로 같다.
  v_feature_id uuid;
  v_prelock_features uuid[];
  v_current_features uuid[];
  v_before_hashes jsonb := '{}'::jsonb;
  v_before_hash text;
  v_after_input jsonb;
  v_after_hash text;
  v_operation_id uuid;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_set_hash text;
  v_replayed boolean;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'source command requires SERIALIZABLE transaction' USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'source command requires the admin executor' USING ERRCODE = '42501';
  END IF;
  IF p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_reason_code IS NULL OR p_reason_code <> btrim(p_reason_code) OR p_reason_code = '' THEN
    RAISE EXCEPTION 'source archive input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_archive_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curated-source.archive' THEN
    RAISE EXCEPTION 'domain command does not match source archive'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_domain_command';
  END IF;
  SELECT COALESCE(array_agg(scope.feature_id ORDER BY scope.feature_id), ARRAY[]::uuid[])
  INTO STRICT v_prelock_features
  FROM (
    SELECT candidate.feature_id FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM feature.curated_sources AS source
    JOIN provider_sync.source_entities AS entity ON entity.provider_dataset_id = source.provider_dataset_id
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE source.source_id = p_source_id
  ) AS scope;
  FOREACH v_feature_id IN ARRAY v_prelock_features LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));
  SELECT source.* INTO STRICT v_source FROM feature.curated_sources AS source
  WHERE source.source_id = p_source_id FOR UPDATE;
  IF v_source.row_revision <> p_expected_source_revision THEN
    RAISE EXCEPTION 'source revision mismatch'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_expected_revision';
  END IF;
  IF v_source.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'source is already archived'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_source_active';
  END IF;
  PERFORM feature.claim_curation_catalog_command_effect(
    p_command_id, v_command.operation, 'source', v_source.source_id
  );
  PERFORM 1 FROM feature.curated_source_rules AS rule
  WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL
  ORDER BY rule.rule_id FOR SHARE;
  SELECT COALESCE(array_agg(scope.feature_id ORDER BY scope.feature_id), ARRAY[]::uuid[])
  INTO STRICT v_current_features
  FROM (
    SELECT candidate.feature_id FROM feature.curated_source_rules AS rule
    JOIN feature.theme_feature_candidates AS candidate ON candidate.rule_id = rule.rule_id
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL AND candidate.disposition = 'active'
    UNION
    SELECT link.feature_id FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link ON link.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_source.provider_dataset_id
  ) AS scope;
  IF v_current_features <> v_prelock_features THEN
    RAISE EXCEPTION 'source archive scope changed while acquiring the catalog lock' USING ERRCODE = '40001';
  END IF;
  FOR v_rule_id IN SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    v_before_hashes := v_before_hashes || jsonb_build_object(
      v_rule_id::text, encode(x_extension.digest(convert_to(
        feature.current_curation_rule_input(v_rule_id)::text, 'UTF8'
      ), 'sha256'), 'hex')
    );
  END LOOP;
  UPDATE feature.curated_sources AS source
  SET archived_at = clock_timestamp(), row_revision = source.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE source.source_id = p_source_id
  RETURNING source.source_id, source.row_revision, source.observation_revision
    INTO STRICT o_source_id, o_source_revision, o_observation_revision;
  o_generation_count := 0;
  FOR v_rule_id IN SELECT rule.rule_id FROM feature.curated_source_rules AS rule
    WHERE rule.source_id = p_source_id AND rule.archived_at IS NULL ORDER BY rule.rule_id
  LOOP
    SELECT rule.row_revision INTO STRICT v_rule_revision
    FROM feature.curated_source_rules AS rule WHERE rule.rule_id = v_rule_id;
    v_before_hash := v_before_hashes ->> v_rule_id::text;
    v_after_input := feature.current_curation_rule_input(v_rule_id);
    v_after_hash := encode(x_extension.digest(convert_to(v_after_input::text, 'UTF8'), 'sha256'), 'hex');
    v_operation_id := feature.create_curation_rule_reconcile_receipt(
      v_rule_id, 'archive', v_rule_revision, v_rule_revision,
      v_before_hash, v_after_hash, p_command_id, p_principal
    );
    CALL feature.materialize_theme_candidate_generation(
      v_rule_id, 'rule_reconcile', NULL, v_operation_id, p_command_id, NULL,
      jsonb_build_object('schema_version', 1, 'catalog_action', 'source_archive',
        'source_id', p_source_id::text, 'reason_code', p_reason_code),
      v_generation_id, v_observed, v_removed, v_set_hash, v_replayed
    );
    o_generation_count := o_generation_count + 1;
  END LOOP;
END
$$;

ALTER PROCEDURE feature.archive_curated_source_command(IN p_source_id uuid, IN p_expected_source_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_generation_count bigint) OWNER TO ktm_curation_command_owner;

REVOKE ALL ON PROCEDURE feature.archive_curated_source_command(IN p_source_id uuid, IN p_expected_source_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_generation_count bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.archive_curated_source_command(IN p_source_id uuid, IN p_expected_source_revision bigint, IN p_command_id bigint, IN p_reason_code text, IN p_principal text, OUT o_source_id uuid, OUT o_source_revision bigint, OUT o_observation_revision bigint, OUT o_generation_count bigint) TO ktm_curation_admin_executor;

SET ROLE ktm_feature_schema_owner;
