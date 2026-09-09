-- 이 사이드카는 자기 역할 창을 스스로 연다 — 소유자는 alembic/head-schema.sql이
-- 정본이다. 바깥에서 `SET ROLE`로 묶으면 순서에 결박되고, 자기 창을 가진 사이드카가
-- 끝에서 스키마 소유자로 되돌리는 순간 뒤따르는 파일이 엉뚱한 롤로 실행된다.
-- 이 파일은 소유권을 바꾸지 않으므로 `ALTER ... OWNER TO`가 없다. 그래도 `CREATE OR
-- REPLACE`와 `DROP`은 소유자만 할 수 있고 롤은 NOINHERIT라 창이 필요하다.
SET ROLE ktm_curation_command_owner;

CREATE OR REPLACE FUNCTION feature.create_curation_rule_reconcile_receipt(p_rule_id uuid, p_operation_kind text, p_before_rule_revision bigint, p_after_rule_revision bigint, p_before_rule_input_hash text, p_after_rule_input_hash text, p_command_id bigint, p_actor text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_operation_id uuid := x_extension.gen_random_uuid();
  v_provider_dataset_id bigint;
  v_scope_member_count bigint;
  v_scope_members_hash text;
BEGIN
  SELECT source.provider_dataset_id INTO STRICT v_provider_dataset_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  WHERE rule.rule_id = p_rule_id;

  WITH scope AS (
    SELECT 'source_entity'::text AS member_kind,
           entity.source_entity_key AS member_key,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             entity.source_entity_key, head.current_source_record_key
           )::text, 'UTF8'), 'sha256'), 'hex') AS identity_hash
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    UNION
    SELECT 'feature'::text, link.feature_id::text,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             link.feature_id, core.row_revision,
             core.lifecycle_state, core.publication_state, core.quality_state
           )::text, 'UTF8'), 'sha256'), 'hex')
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS core ON core.feature_id = link.feature_id
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ), framed AS (
    SELECT member_kind, member_key,
           CASE WHEN p_operation_kind = 'create' THEN NULL ELSE identity_hash END
             AS before_identity_hash,
           identity_hash AS after_identity_hash
    FROM scope
  )
  SELECT count(*), encode(
    x_extension.digest(
      COALESCE(
        string_agg(
          convert_to(member_kind, 'UTF8') || decode('00', 'hex') ||
          convert_to(member_key, 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(before_identity_hash, ''), 'UTF8') || decode('00', 'hex') ||
          convert_to(COALESCE(after_identity_hash, ''), 'UTF8') ||
          convert_to(E'\n', 'UTF8'),
          ''::bytea ORDER BY member_kind, member_key
        ),
        ''::bytea
      ),
      'sha256'
    ),
    'hex'
  ) INTO STRICT v_scope_member_count, v_scope_members_hash
  FROM framed;

  INSERT INTO ops.curation_rule_reconcile_operations (
    operation_id, rule_id, operation_kind,
    before_rule_revision, after_rule_revision,
    before_rule_input_hash, after_rule_input_hash,
    command_id, system_operation_key, actor,
    scope_member_count, scope_members_hash
  ) VALUES (
    v_operation_id, p_rule_id, p_operation_kind,
    p_before_rule_revision, p_after_rule_revision,
    p_before_rule_input_hash, p_after_rule_input_hash,
    p_command_id, NULL, p_actor,
    v_scope_member_count, v_scope_members_hash
  );

  INSERT INTO ops.curation_rule_reconcile_scope_members (
    operation_id, member_kind, member_key,
    before_identity_hash, after_identity_hash
  )
  SELECT v_operation_id, scope.member_kind, scope.member_key,
         CASE WHEN p_operation_kind = 'create' THEN NULL ELSE scope.identity_hash END,
         scope.identity_hash
  FROM (
    SELECT 'source_entity'::text AS member_kind,
           entity.source_entity_key AS member_key,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             entity.source_entity_key, head.current_source_record_key
           )::text, 'UTF8'), 'sha256'), 'hex') AS identity_hash
    FROM provider_sync.source_entities AS entity
    LEFT JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    WHERE entity.provider_dataset_id = v_provider_dataset_id
    UNION
    SELECT 'feature'::text, link.feature_id::text,
           encode(x_extension.digest(convert_to(jsonb_build_array(
             link.feature_id, core.row_revision,
             core.lifecycle_state, core.publication_state, core.quality_state
           )::text, 'UTF8'), 'sha256'), 'hex')
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS core ON core.feature_id = link.feature_id
    WHERE entity.provider_dataset_id = v_provider_dataset_id
  ) AS scope
  ORDER BY scope.member_kind, scope.member_key;

  RETURN v_operation_id;
END
$$;

SET ROLE ktm_feature_schema_owner;
