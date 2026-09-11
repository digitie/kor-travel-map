-- revision vector의 feature 항목이 uuid 컬럼을 text 키와 비교한다.
--
-- T-VN-39의 **다섯 번째** 범위 누락이다. 앞의 넷과 또 다른 이유로 놓쳤다 — 이
-- 프로시저는 feature 식별자를 **인자로 받지 않는다.** 시그니처에도, 인자 이름에도
-- 단서가 없고, 오직 본문 한 줄이 `feature.features.feature_id`(재키 후 uuid)를
-- 호출자가 준 text 키와 비교한다:
--
--     AND core.feature_id = expected.resource_key
--
-- 재키 뒤 이것은 42883 `operator does not exist: uuid = text`이고, curation import
-- plan claim 경로 전량이 거기서 선다.
--
-- 이름도 시그니처도 아닌 **본문**이 오라클이다. 그 눈은
-- `tests/lint/test_routine_bodies_compare_feature_ids_on_one_axis.py`가 갖는다.
--
-- 시그니처가 그대로이므로 `CREATE OR REPLACE`다 — ACL과 소유권이 보존되고 역할 창이
-- 필요 없다. 본문은 head 오라클에서 그대로 떠 왔고 바뀐 것은 위 한 줄뿐이다.
SET ROLE ktm_curation_command_owner;

CREATE OR REPLACE PROCEDURE feature.claim_curation_import_plan_command(IN p_import_plan_id uuid, IN p_plan_sha256 text, IN p_command_id bigint, IN p_principal text, OUT o_content_sha256 text, OUT o_rows jsonb, OUT o_summary jsonb, OUT o_response_rows jsonb, OUT o_expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_plan feature.curation_import_plans%ROWTYPE;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import commit requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import commit requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('curation-import-plan:' || p_import_plan_id::text, 0)
  );
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation.import'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import commit'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_commit_command';
  END IF;
  SELECT plan.* INTO STRICT v_plan
  FROM feature.curation_import_plans AS plan
  WHERE plan.import_plan_id = p_import_plan_id;
  IF v_plan.actor <> p_principal OR v_plan.plan_sha256 <> p_plan_sha256 THEN
    RAISE EXCEPTION 'curation import plan actor or ETag changed'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_etag';
  END IF;
  IF v_plan.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'curation import plan expired'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_expired';
  END IF;
  IF COALESCE((v_plan.summary ->> 'has_errors')::boolean, true) THEN
    RAISE EXCEPTION 'curation import plan contains unresolved validation errors'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_has_errors';
  END IF;
  IF EXISTS (
    SELECT 1 FROM ops.curation_import_plan_commits AS committed
    WHERE committed.import_plan_id = p_import_plan_id
  ) THEN
    RAISE EXCEPTION 'curation import plan already committed'
      USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_import_plan_commit';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM feature.curation_import_plan_revisions AS expected
    LEFT JOIN LATERAL (
      SELECT current_row.row_revision
      FROM (
        SELECT theme.row_revision
        FROM feature.curated_themes AS theme
        WHERE expected.resource_kind = 'theme'
          AND theme.theme_id = expected.resource_key::uuid
          AND theme.archived_at IS NULL
        UNION ALL
        SELECT source.row_revision
        FROM feature.curated_sources AS source
        WHERE expected.resource_kind = 'source'
          AND source.source_id = expected.resource_key::uuid
          AND source.archived_at IS NULL
        UNION ALL
        SELECT collection.row_revision
        FROM feature.curation_collections AS collection
        WHERE expected.resource_kind = 'collection'
          AND collection.collection_key = expected.resource_key
          AND collection.archived_at IS NULL
        UNION ALL
        SELECT item.row_revision
        FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id = item.collection_id
        WHERE expected.resource_kind = 'item'
          AND collection.collection_key = expected.resource_key::jsonb ->> 0
          AND item.external_item_id = expected.resource_key::jsonb ->> 1
          AND item.external_component_id = expected.resource_key::jsonb ->> 2
        UNION ALL
        SELECT core.row_revision
        FROM feature.features AS core
        WHERE expected.resource_kind = 'feature'
          -- T-VN-39: `core.feature_id`는 uuid이고 revision vector의
          -- `resource_key`는 **바깥 계약의 text 키**다(theme/source/collection/
          -- item 넷과 같은 자리). 바깥 이름을 바꾸지 않고 원천만 캐스트한다 —
          -- 반대로 키를 uuid로 캐스트하면 잘못된 키가 '개정 벡터 불일치'가
          -- 아니라 22P02로 죽는다.
          AND CAST(core.feature_id AS text) = expected.resource_key
      ) AS current_row
    ) AS current ON true
    WHERE expected.import_plan_id = p_import_plan_id
      AND current.row_revision IS DISTINCT FROM expected.expected_revision
  ) THEN
    RAISE EXCEPTION 'curation import plan revision vector is stale'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_revision_vector';
  END IF;
  o_content_sha256 := v_plan.content_sha256;
  o_summary := v_plan.summary;
  o_expires_at := v_plan.expires_at;
  SELECT COALESCE(jsonb_agg(row.normalized_payload ORDER BY row.row_number)
                  FILTER (WHERE row.normalized_payload IS NOT NULL), '[]'::jsonb)
  INTO STRICT o_rows
  FROM feature.curation_import_plan_rows AS row
  WHERE row.import_plan_id = p_import_plan_id;
  SELECT COALESCE(jsonb_agg(row.response_payload ORDER BY row.row_number), '[]'::jsonb)
  INTO STRICT o_response_rows
  FROM feature.curation_import_plan_rows AS row
  WHERE row.import_plan_id = p_import_plan_id;
  INSERT INTO ops.curation_import_plan_claims (
    import_plan_id, command_id, plan_sha256
  ) VALUES (
    p_import_plan_id, p_command_id, p_plan_sha256
  );
END
$$;

SET ROLE ktm_feature_schema_owner;
