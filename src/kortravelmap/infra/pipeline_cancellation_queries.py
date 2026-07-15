"""Pipeline cancellation repository의 PostgreSQL query 정본."""

from kortravelmap.infra.pipeline_lineage import PIPELINE_LINEAGE_CTES_SQL

_RESOLVE_SCOPE_SQL = "WITH RECURSIVE\n" + PIPELINE_LINEAGE_CTES_SQL + """,
input_request AS (
    SELECT request.request_id
    FROM ops.feature_update_requests AS request
    WHERE CAST(:kind AS text) = 'update_request'
      AND request.request_id = CAST(:execution_id AS uuid)
),
input_job AS (
    SELECT
        component.job_id,
        component.component_root_id,
        owner.owner_request_id
    FROM job_components AS component
    LEFT JOIN job_owners AS owner ON owner.job_id = component.job_id
    WHERE CAST(:kind AS text) = 'import_job'
      AND component.job_id = CAST(:execution_id AS uuid)
),
canonical_root AS (
    SELECT
        'update_request'::text AS root_kind,
        request.request_id AS root_id
    FROM input_request AS request
    UNION ALL
    SELECT
        CASE WHEN job.owner_request_id IS NULL
          THEN 'import_job'::text ELSE 'update_request'::text END AS root_kind,
        COALESCE(job.owner_request_id, job.component_root_id) AS root_id
    FROM input_job AS job
),
scope_members AS (
    SELECT
        job.job_id,
        job.status AS initial_status,
        job.dagster_run_id,
        CASE WHEN job.kind = btrim(job.kind) AND job.kind <> ''
          THEN job.kind ELSE NULL END AS operation_kind,
        job.cancellation_id
    FROM canonical_root AS root
    JOIN job_owners AS owner
      ON root.root_kind = 'update_request'
     AND owner.owner_request_id = root.root_id
    JOIN ops.import_jobs AS job ON job.job_id = owner.job_id
    UNION ALL
    SELECT
        job.job_id,
        job.status AS initial_status,
        job.dagster_run_id,
        CASE WHEN job.kind = btrim(job.kind) AND job.kind <> ''
          THEN job.kind ELSE NULL END AS operation_kind,
        job.cancellation_id
    FROM canonical_root AS root
    JOIN standalone_jobs AS standalone
      ON root.root_kind = 'import_job'
     AND standalone.component_root_id = root.root_id
    JOIN ops.import_jobs AS job ON job.job_id = standalone.job_id
)
SELECT
    root.root_kind,
    root.root_id,
    member.job_id,
    member.initial_status,
    member.dagster_run_id,
    member.operation_kind,
    member.cancellation_id
FROM canonical_root AS root
JOIN scope_members AS member ON true
ORDER BY member.job_id
"""

_CURRENT_ATTEMPT_SQL = """
SELECT
    attempt.cancellation_id,
    attempt.previous_cancellation_id,
    attempt.root_kind,
    attempt.root_id,
    attempt.status,
    attempt.requested_by,
    attempt.reason,
    attempt.error,
    attempt.requested_at,
    attempt.updated_at,
    attempt.finished_at,
    (
      SELECT COUNT(*)::integer
      FROM ops.pipeline_cancellation_members AS member
      WHERE member.cancellation_id = attempt.cancellation_id
        AND member.result IN ('pending', 'cancel_failed')
    ) AS unresolved_member_count
FROM ops.pipeline_cancellations AS attempt
WHERE attempt.root_kind = CAST(:root_kind AS text)
  AND attempt.root_id = CAST(:root_id AS uuid)
ORDER BY
    (attempt.status = 'in_progress') DESC,
    attempt.requested_at DESC,
    attempt.cancellation_id DESC
LIMIT 1
"""

_ATTEMPT_SQL = """
SELECT
    cancellation_id,
    previous_cancellation_id,
    root_kind,
    root_id,
    status,
    requested_by,
    reason,
    error,
    requested_at,
    updated_at,
    finished_at
FROM ops.pipeline_cancellations
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
"""

_LOCK_ATTEMPT_SQL = _ATTEMPT_SQL + "\nFOR UPDATE"

_MEMBERS_SQL = """
SELECT
    cancellation_id,
    job_id,
    dagster_run_id,
    operation_kind,
    requires_run_termination,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_members
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
ORDER BY job_id
"""

_LOCK_MEMBER_SQL = """
SELECT
    cancellation_id,
    job_id,
    dagster_run_id,
    operation_kind,
    requires_run_termination,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_members
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND job_id = CAST(:job_id AS uuid)
FOR UPDATE
"""

_RUNS_SQL = """
SELECT
    cancellation_id,
    dagster_run_id,
    initial_status,
    termination_reserved_at,
    result,
    terminal_status,
    error,
    engine_started_at,
    engine_finished_at,
    updated_at
FROM ops.pipeline_cancellation_runs
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
ORDER BY dagster_run_id
"""

_LOCK_RUN_SQL = """
SELECT
    cancellation_id,
    dagster_run_id,
    initial_status,
    termination_reserved_at,
    result,
    terminal_status,
    error,
    engine_started_at,
    engine_finished_at,
    updated_at
FROM ops.pipeline_cancellation_runs
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND dagster_run_id = :dagster_run_id
FOR UPDATE
"""

_INSERT_ATTEMPT_SQL = """
INSERT INTO ops.pipeline_cancellations (
    cancellation_id,
    previous_cancellation_id,
    root_kind,
    root_id,
    status,
    requested_by,
    reason,
    finished_at
) VALUES (
    CAST(:cancellation_id AS uuid),
    CAST(:previous_cancellation_id AS uuid),
    :root_kind,
    CAST(:root_id AS uuid),
    :status,
    :requested_by,
    :reason,
    CASE WHEN :status = 'in_progress' THEN NULL ELSE now() END
)
"""

_INSERT_RUN_SQL = """
INSERT INTO ops.pipeline_cancellation_runs (
    cancellation_id,
    dagster_run_id,
    result
) VALUES (
    CAST(:cancellation_id AS uuid),
    :dagster_run_id,
    :result
)
"""

_INSERT_MEMBER_SQL = """
INSERT INTO ops.pipeline_cancellation_members (
    cancellation_id,
    job_id,
    dagster_run_id,
    operation_kind,
    initial_status,
    requires_run_termination,
    result,
    terminal_status
) VALUES (
    CAST(:cancellation_id AS uuid),
    CAST(:job_id AS uuid),
    :dagster_run_id,
    :operation_kind,
    :initial_status,
    :requires_run_termination,
    :result,
    :terminal_status
)
"""

_MARK_JOBS_SQL = """
WITH jobs AS (
    SELECT value::uuid AS job_id
    FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
)
UPDATE ops.import_jobs AS job
SET cancellation_id = CAST(:cancellation_id AS uuid),
    cancellation_requested_at = now(),
    cancellation_requested_by = :requested_by,
    cancellation_reason = :reason
WHERE job.job_id IN (SELECT job_id FROM jobs)
  AND (
    (CAST(:expected_cancellation_id AS uuid) IS NULL AND job.cancellation_id IS NULL)
    OR job.cancellation_id = CAST(:expected_cancellation_id AS uuid)
  )
RETURNING job.job_id
"""

_UPDATE_MEMBER_SQL = """
UPDATE ops.pipeline_cancellation_members
SET result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND job_id = CAST(:job_id AS uuid)
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
"""

_UPDATE_RUN_SQL = """
UPDATE ops.pipeline_cancellation_runs
SET initial_status = COALESCE(initial_status, :initial_status),
    result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    engine_started_at = :engine_started_at,
    engine_finished_at = :engine_finished_at,
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND dagster_run_id = :dagster_run_id
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
"""

_FEATURE_RUN_TIMELINE_CONFLICT_SQL = """
WITH canonical_jobs AS (
  SELECT job.created_at, job.started_at, job.finished_at, job.cancellation_id
  FROM ops.pipeline_cancellation_members AS member
  JOIN ops.import_jobs AS job
    ON job.job_id = member.job_id
  WHERE member.cancellation_id = CAST(:cancellation_id AS uuid)
    AND member.dagster_run_id = :dagster_run_id
    AND member.operation_kind IN (
      'provider_feature_load_run','provider_feature_load'
    )
)
SELECT
  count(*) AS expected_count,
  count(*) FILTER (
    WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  ) AS owned_count,
  COALESCE(
    CAST(:engine_started_at AS timestamptz), min(started_at)
  ) AS effective_started_at,
  count(*) > 0 AND (
    count(DISTINCT started_at) > 1
    OR (
      CAST(:engine_started_at AS timestamptz) IS NOT NULL
      AND bool_or(
        started_at IS NOT NULL
        AND started_at <> CAST(:engine_started_at AS timestamptz)
      )
    )
    OR CAST(:engine_finished_at AS timestamptz) IS NULL
    OR bool_or(
      created_at > CAST(:engine_finished_at AS timestamptz)
      OR started_at > CAST(:engine_finished_at AS timestamptz)
    )
    OR bool_or(
      COALESCE(
        CAST(:engine_started_at AS timestamptz),
        (SELECT min(started_at) FROM canonical_jobs)
      ) IS NOT NULL
      AND (
        created_at > COALESCE(
          CAST(:engine_started_at AS timestamptz),
          (SELECT min(started_at) FROM canonical_jobs)
        )
        OR finished_at < COALESCE(
          CAST(:engine_started_at AS timestamptz),
          (SELECT min(started_at) FROM canonical_jobs)
        )
      )
    )
  ) AS has_conflict
FROM canonical_jobs
"""

_FILL_CANONICAL_STARTS_SQL = """
WITH canonical_jobs AS (
  SELECT job.job_id, job.cancellation_id, job.started_at
  FROM ops.pipeline_cancellation_members AS member
  JOIN ops.import_jobs AS job ON job.job_id = member.job_id
  WHERE member.cancellation_id = CAST(:cancellation_id AS uuid)
    AND member.dagster_run_id = :dagster_run_id
    AND member.operation_kind IN (
      'provider_feature_load_run','provider_feature_load'
    )
),
updated AS (
  UPDATE ops.import_jobs AS job
  SET started_at = CAST(:engine_started_at AS timestamptz)
  FROM canonical_jobs AS candidate
  WHERE job.job_id = candidate.job_id
    AND candidate.cancellation_id = CAST(:cancellation_id AS uuid)
    AND job.cancellation_id = CAST(:cancellation_id AS uuid)
    AND job.started_at IS NULL
  RETURNING job.job_id
)
SELECT
  (SELECT count(*) FROM canonical_jobs) AS expected_count,
  (SELECT count(*) FROM canonical_jobs
   WHERE cancellation_id = CAST(:cancellation_id AS uuid)) AS owned_count,
  COALESCE((SELECT array_agg(job_id::text ORDER BY job_id) FROM updated), '{}')
    AS updated_job_ids
"""

_RESERVE_RUN_TERMINATION_SQL = """
UPDATE ops.pipeline_cancellation_runs
SET initial_status = COALESCE(initial_status, :initial_status),
    termination_reserved_at = now(),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND dagster_run_id = :dagster_run_id
  AND result = 'pending'
  AND termination_reserved_at IS NULL
RETURNING cancellation_id
"""

_FINISH_ATTEMPT_SQL = """
UPDATE ops.pipeline_cancellations AS attempt
SET status = :status,
    error = CAST(:error AS jsonb),
    updated_at = now(),
    finished_at = now()
WHERE attempt.cancellation_id = CAST(:cancellation_id AS uuid)
  AND attempt.status = 'in_progress'
RETURNING attempt.cancellation_id
"""

_LOCK_JOB_MEMBERS_SQL = """
WITH members AS (
    SELECT value::uuid AS job_id
    FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
)
SELECT
    job.job_id,
    job.status AS initial_status,
    job.dagster_run_id,
    CASE WHEN job.kind = btrim(job.kind) AND job.kind <> ''
      THEN job.kind ELSE NULL END AS operation_kind,
    job.cancellation_id
FROM ops.import_jobs AS job
WHERE job.job_id IN (SELECT job_id FROM members)
ORDER BY job.job_id
FOR UPDATE
"""

_TRANSITION_JOB_MEMBER_SQL = """
UPDATE ops.import_jobs
SET status = :target_status,
    error_message = COALESCE(:error_message, error_message),
    finished_at = CASE
      WHEN kind IN ('provider_feature_load_run','provider_feature_load') THEN
        CAST(:engine_finished_at AS timestamptz)
      ELSE COALESCE(CAST(:engine_finished_at AS timestamptz), now())
    END,
    started_at = COALESCE(started_at, CAST(:engine_started_at AS timestamptz)),
    heartbeat_at = CASE
      WHEN kind IN ('provider_feature_load_run','provider_feature_load') THEN
        CAST(:engine_finished_at AS timestamptz)
      WHEN status = 'running' THEN
        COALESCE(CAST(:engine_finished_at AS timestamptz), now())
      ELSE heartbeat_at
    END,
    progress = CASE WHEN :target_status = 'done' THEN 100 ELSE progress END,
    current_stage = CASE
      WHEN kind IN ('provider_feature_load_run','provider_feature_load') THEN
        CASE :target_status
          WHEN 'done' THEN 'completed'
          WHEN 'failed' THEN
            CASE WHEN :success_tracking_invariant
              THEN 'tracking_invariant' ELSE 'failed' END
          WHEN 'cancelled' THEN 'cancelled'
          ELSE current_stage
        END
      ELSE current_stage
    END,
    dagster_run_status = CASE
      WHEN kind = 'provider_feature_load_run' THEN :dagster_terminal_status
      ELSE dagster_run_status
    END
WHERE job_id = CAST(:job_id AS uuid)
  AND cancellation_id = CAST(:cancellation_id AS uuid)
  AND status = ANY(CAST(:expected_statuses AS text[]))
  AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
  AND (
    kind NOT IN ('provider_feature_load_run','provider_feature_load')
    OR (
      CAST(:engine_finished_at AS timestamptz) IS NOT NULL
      AND created_at <= CAST(:engine_finished_at AS timestamptz)
      AND (
        CAST(:engine_started_at AS timestamptz) IS NULL
        OR created_at <= CAST(:engine_started_at AS timestamptz)
      )
      AND (started_at IS NULL OR started_at <= CAST(:engine_finished_at AS timestamptz))
      AND (
        CAST(:engine_started_at AS timestamptz) IS NULL
        OR started_at IS NULL
        OR started_at = CAST(:engine_started_at AS timestamptz)
      )
    )
  )
RETURNING job_id
"""
