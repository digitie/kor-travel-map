CREATE FUNCTION ops.reject_provider_feature_operation_raw_dml() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
DECLARE
  v_kind text;
BEGIN
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_kind := CASE WHEN TG_OP = 'DELETE' THEN OLD.kind ELSE NEW.kind END;
  IF v_kind IN ('provider_feature_load_run', 'provider_feature_load')
     OR (TG_OP = 'UPDATE' AND OLD.kind IN (
       'provider_feature_load_run', 'provider_feature_load'
     )) THEN
    IF TG_OP = 'UPDATE'
       AND session_user = 'ktm_feature_api_runtime'
       AND NEW.cancellation_id IS NOT NULL
       AND EXISTS (
         SELECT 1
         FROM ops.pipeline_cancellation_members AS member
         JOIN ops.pipeline_cancellations AS attempt
           ON attempt.cancellation_id = member.cancellation_id
         WHERE member.cancellation_id = NEW.cancellation_id
           AND member.job_id = NEW.job_id
           AND attempt.status = 'in_progress'
       )
       AND to_jsonb(NEW) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[]
       = to_jsonb(OLD) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[] THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'provider feature operations require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_operation_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
