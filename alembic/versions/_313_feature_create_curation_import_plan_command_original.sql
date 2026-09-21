CREATE OR REPLACE PROCEDURE feature.create_curation_import_plan_command(IN p_import_plan_id uuid, IN p_content_sha256 text, IN p_provenance_sha256 text, IN p_plan_sha256 text, IN p_summary jsonb, IN p_rows jsonb, IN p_revisions jsonb, IN p_expires_at timestamp with time zone, IN p_command_id bigint, IN p_principal text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $_$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_row_count integer;
  v_revision_count integer;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import preview requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import preview requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF p_import_plan_id IS NULL OR p_principal IS NULL
     OR p_principal <> btrim(p_principal) OR p_principal = ''
     OR p_content_sha256 !~ '^[0-9a-f]{64}$'
     OR (p_provenance_sha256 IS NOT NULL AND p_provenance_sha256 !~ '^[0-9a-f]{64}$')
     OR p_plan_sha256 !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_summary) <> 'object'
     OR jsonb_typeof(p_rows) <> 'array'
     OR jsonb_typeof(p_revisions) <> 'array'
     OR p_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'curation import preview input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal
     OR v_command.operation <> 'admin.curation-import.preview'
     OR EXISTS (
       SELECT 1 FROM ops.domain_command_results AS result
       WHERE result.command_id = p_command_id
     ) THEN
    RAISE EXCEPTION 'domain command does not match active curation import preview'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_domain_command';
  END IF;
  SELECT count(*)::integer INTO STRICT v_row_count
  FROM jsonb_array_elements(p_rows);
  SELECT count(*)::integer INTO STRICT v_revision_count
  FROM jsonb_array_elements(p_revisions);
  INSERT INTO feature.curation_import_plans (
    import_plan_id, preview_command_id, actor, content_sha256,
    provenance_sha256, plan_sha256, summary, row_count, revision_count,
    expires_at
  ) VALUES (
    p_import_plan_id, p_command_id, p_principal, p_content_sha256,
    p_provenance_sha256, p_plan_sha256, p_summary, v_row_count,
    v_revision_count, p_expires_at
  );
  INSERT INTO feature.curation_import_plan_rows (
    import_plan_id, row_number, normalized_payload, response_payload
  )
  SELECT p_import_plan_id, value.row_number, value.normalized_payload,
         value.response_payload
  FROM jsonb_to_recordset(p_rows) AS value(
    row_number integer, normalized_payload jsonb, response_payload jsonb
  );
  INSERT INTO feature.curation_import_plan_revisions (
    import_plan_id, resource_kind, resource_key, expected_revision
  )
  SELECT p_import_plan_id, value.resource_kind, value.resource_key,
         value.expected_revision
  FROM jsonb_to_recordset(p_revisions) AS value(
    resource_kind text, resource_key text, expected_revision bigint
  );
  IF (SELECT count(*) FROM feature.curation_import_plan_rows AS row
      WHERE row.import_plan_id = p_import_plan_id) <> v_row_count
     OR (SELECT count(*) FROM feature.curation_import_plan_revisions AS revision
         WHERE revision.import_plan_id = p_import_plan_id) <> v_revision_count THEN
    RAISE EXCEPTION 'curation import plan rows or revision vector are not unique'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_unique_set';
  END IF;
END
$_$;
