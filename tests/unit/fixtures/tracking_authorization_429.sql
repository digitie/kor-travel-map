-- 430 tracking owner/typed authorization tail 역비교용 원429 정의. 실행하지 않는 시험 자료.
-- 출처: e1734f9365cbccbd5ebb45d09784c72994f6c175:alembic/head-schema.sql
-- 원 dump SHA256: 893e61bb8532bc1dd0c9c4d56aeec7941af33eac649a32bd9ca40ea305b3175f

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
       AND session_user = 'ktm_feature_service'
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

CREATE FUNCTION ops.reject_provider_feature_membership_raw_dml() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
DECLARE
  v_job_id uuid;
BEGIN
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  IF EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = v_job_id
      AND job.kind = 'provider_feature_load'
  ) OR (TG_OP = 'UPDATE' AND EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = OLD.job_id
      AND job.kind = 'provider_feature_load'
  )) THEN
    RAISE EXCEPTION 'provider feature memberships require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_membership_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
