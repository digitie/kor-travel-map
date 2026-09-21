CREATE OR REPLACE FUNCTION ops.fill_provider_cancellation_starts_command(p_cancellation_id uuid, p_dagster_run_id text, p_engine_started_at timestamp with time zone) RETURNS TABLE(expected_count bigint, owned_count bigint, updated_job_ids uuid[])
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
BEGIN
  IF session_user <> 'ktm_feature_api_runtime'
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RAISE EXCEPTION 'provider cancellation command requires API runtime'
      USING ERRCODE = '42501';
  END IF;
  IF p_engine_started_at IS NULL OR p_dagster_run_id IS NULL OR btrim(p_dagster_run_id) = '' THEN
    RAISE EXCEPTION 'invalid provider cancellation start command'
      USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM ops.pipeline_cancellations AS attempt
    JOIN ops.pipeline_cancellation_runs AS run
      ON run.cancellation_id = attempt.cancellation_id
     AND run.dagster_run_id = p_dagster_run_id
    WHERE attempt.cancellation_id = p_cancellation_id
      AND attempt.status = 'in_progress'
      AND run.result IN ('cancelled','already_terminal')
      AND run.engine_started_at = p_engine_started_at
    FOR UPDATE OF attempt, run
  ) THEN
    RAISE EXCEPTION 'provider cancellation start proof is not current'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_provider_cancellation_start_proof';
  END IF;
  RETURN QUERY
  WITH canonical_jobs AS (
    SELECT job.job_id, job.cancellation_id, job.started_at
    FROM ops.pipeline_cancellation_members AS member
    JOIN ops.import_jobs AS job ON job.job_id = member.job_id
    WHERE member.cancellation_id = p_cancellation_id
      AND member.dagster_run_id = p_dagster_run_id
      AND member.operation_kind IN ('provider_feature_load_run','provider_feature_load')
  ),
  updated AS (
    UPDATE ops.import_jobs AS job
    SET started_at = p_engine_started_at
    FROM canonical_jobs AS candidate
    WHERE job.job_id = candidate.job_id
      AND candidate.cancellation_id = p_cancellation_id
      AND job.cancellation_id = p_cancellation_id
      AND job.started_at IS NULL
    RETURNING job.job_id
  )
  SELECT
    (SELECT count(*) FROM canonical_jobs),
    (SELECT count(*) FROM canonical_jobs WHERE cancellation_id = p_cancellation_id),
    COALESCE((SELECT array_agg(job_id ORDER BY job_id) FROM updated), '{}'::uuid[]);
END
$$;
