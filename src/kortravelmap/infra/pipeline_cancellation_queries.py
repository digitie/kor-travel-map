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
        'update_request'::text AS member_kind,
        request.request_id AS member_id,
        request.status AS initial_status,
        request.dagster_run_id,
        request.cancellation_id
    FROM canonical_root AS root
    JOIN ops.feature_update_requests AS request
      ON root.root_kind = 'update_request'
     AND request.request_id = root.root_id
    UNION ALL
    SELECT
        'import_job'::text AS member_kind,
        job.job_id AS member_id,
        job.status AS initial_status,
        job.dagster_run_id,
        job.cancellation_id
    FROM canonical_root AS root
    JOIN job_owners AS owner
      ON root.root_kind = 'update_request'
     AND owner.owner_request_id = root.root_id
    JOIN ops.import_jobs AS job ON job.job_id = owner.job_id
    UNION ALL
    SELECT
        'import_job'::text AS member_kind,
        job.job_id AS member_id,
        job.status AS initial_status,
        job.dagster_run_id,
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
    member.member_kind,
    member.member_id,
    member.initial_status,
    member.dagster_run_id,
    member.cancellation_id
FROM canonical_root AS root
JOIN scope_members AS member ON true
ORDER BY member.member_kind, member.member_id
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
    member_kind,
    member_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_members
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
ORDER BY member_kind, member_id
"""

_LOCK_MEMBER_SQL = """
SELECT
    cancellation_id,
    member_kind,
    member_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status,
    error,
    updated_at
FROM ops.pipeline_cancellation_members
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND member_kind = :member_kind
  AND member_id = CAST(:member_id AS uuid)
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
    member_kind,
    member_id,
    dagster_run_id,
    initial_status,
    result,
    terminal_status
) VALUES (
    CAST(:cancellation_id AS uuid),
    :member_kind,
    CAST(:member_id AS uuid),
    :dagster_run_id,
    :initial_status,
    :result,
    :terminal_status
)
"""

_MARK_JOBS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
UPDATE ops.import_jobs AS job
SET cancellation_id = CAST(:cancellation_id AS uuid),
    cancellation_requested_at = now(),
    cancellation_requested_by = :requested_by,
    cancellation_reason = :reason
WHERE job.job_id IN (SELECT member_id FROM members)
  AND (
    (CAST(:expected_cancellation_id AS uuid) IS NULL AND job.cancellation_id IS NULL)
    OR job.cancellation_id = CAST(:expected_cancellation_id AS uuid)
  )
RETURNING job.job_id
"""

_MARK_REQUESTS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
UPDATE ops.feature_update_requests AS request
SET cancellation_id = CAST(:cancellation_id AS uuid),
    cancellation_requested_at = now(),
    cancellation_requested_by = :requested_by,
    cancellation_reason = :reason
WHERE request.request_id IN (SELECT member_id FROM members)
  AND (
    (CAST(:expected_cancellation_id AS uuid) IS NULL
      AND request.cancellation_id IS NULL)
    OR request.cancellation_id = CAST(:expected_cancellation_id AS uuid)
  )
RETURNING request.request_id
"""

_UPDATE_MEMBER_SQL = """
UPDATE ops.pipeline_cancellation_members
SET result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND member_kind = :member_kind
  AND member_id = CAST(:member_id AS uuid)
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
"""

_UPDATE_RUN_SQL = """
UPDATE ops.pipeline_cancellation_runs
SET initial_status = COALESCE(initial_status, :initial_status),
    result = :result,
    terminal_status = :terminal_status,
    error = CAST(:error AS jsonb),
    updated_at = now()
WHERE cancellation_id = CAST(:cancellation_id AS uuid)
  AND dagster_run_id = :dagster_run_id
  AND result = ANY(CAST(:expected_results AS text[]))
RETURNING cancellation_id
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

_LOCK_REQUEST_MEMBERS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
SELECT
    'update_request'::text AS member_kind,
    request.request_id AS member_id,
    request.status AS initial_status,
    request.dagster_run_id,
    request.cancellation_id
FROM ops.feature_update_requests AS request
WHERE request.request_id IN (SELECT member_id FROM members)
ORDER BY request.request_id
FOR UPDATE
"""

_LOCK_JOB_MEMBERS_SQL = """
WITH members AS (
    SELECT value::uuid AS member_id
    FROM jsonb_array_elements_text(CAST(:member_ids AS jsonb))
)
SELECT
    'import_job'::text AS member_kind,
    job.job_id AS member_id,
    job.status AS initial_status,
    job.dagster_run_id,
    job.cancellation_id
FROM ops.import_jobs AS job
WHERE job.job_id IN (SELECT member_id FROM members)
ORDER BY job.job_id
FOR UPDATE
"""

_TRANSITION_REQUEST_MEMBER_SQL = """
UPDATE ops.feature_update_requests
SET status = :target_status,
    error_message = COALESCE(:error_message, error_message),
    finished_at = now(),
    updated_at = now()
WHERE request_id = CAST(:member_id AS uuid)
  AND cancellation_id = CAST(:cancellation_id AS uuid)
  AND status = :expected_status
  AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
RETURNING request_id
"""

_TRANSITION_JOB_MEMBER_SQL = """
UPDATE ops.import_jobs
SET status = :target_status,
    error_message = COALESCE(:error_message, error_message),
    finished_at = now(),
    heartbeat_at = CASE WHEN status = 'running' THEN now() ELSE heartbeat_at END,
    progress = CASE WHEN :target_status = 'done' THEN 100 ELSE progress END
WHERE job_id = CAST(:member_id AS uuid)
  AND cancellation_id = CAST(:cancellation_id AS uuid)
  AND status = :expected_status
  AND dagster_run_id IS NOT DISTINCT FROM CAST(:dagster_run_id AS text)
RETURNING job_id
"""
