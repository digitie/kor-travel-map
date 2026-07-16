"""Pipeline 실행 identity 불변식과 선택 조회 인덱스를 추가한다.

Revision ID: 0052_pipeline_projection_access
Revises: 0051_canonical_provider_ops
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence
from time import sleep

import sqlalchemy as sa

from alembic import op

revision: str = "0052_pipeline_projection_access"
down_revision: str | Sequence[str] | None = "0051_canonical_provider_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_JOB_FK = "fk_feature_update_requests_job_id_import_jobs"
_IDENTITY_LOCK_RETRIES = 600
_IDENTITY_LOCK_RETRY_SECONDS = 0.05


def _lock_identity_writers() -> None:
    """repair와 제약 설치 사이에 구 writer가 끼어들지 못하게 한다."""
    # runtime writer 순서(attempt→member→run→request→job→event→clock)를 그대로 잡는다.
    # migration이 첫 lock을 보유한 채 뒤 lock을 기다리면 deadlock cycle이
    # 가능하다. savepoint 안에서 전체 lock을 NOWAIT로 시도해
    # 하나라도 경합하면 부분 lock을 모두 풀고 제한적으로 재시도한다.
    connection = op.get_bind()
    clock_exists = bool(
        connection.scalar(
            sa.text("SELECT to_regclass('ops.import_job_event_clock') IS NOT NULL")
        )
    )
    relations = (
        "ops.pipeline_cancellations, "
        "ops.pipeline_cancellation_members, "
        "ops.pipeline_cancellation_runs, "
        "ops.feature_update_requests, ops.import_jobs, "
        "ops.import_job_events"
    )
    if clock_exists:
        relations = f"{relations}, ops.import_job_event_clock"
    for attempt in range(_IDENTITY_LOCK_RETRIES):
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    f"LOCK TABLE {relations} IN ACCESS EXCLUSIVE MODE NOWAIT"
                )
            )
        except sa.exc.DBAPIError as exc:
            savepoint.rollback()
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig,
                "pgcode",
                None,
            )
            if sqlstate != "55P03":
                raise
            if attempt + 1 == _IDENTITY_LOCK_RETRIES:
                raise RuntimeError(
                    "0052 identity writer lock could not be acquired within 30 seconds"
                ) from exc
            sleep(_IDENTITY_LOCK_RETRY_SECONDS)
        else:
            savepoint.commit()
            return

    raise AssertionError("unreachable identity lock retry state")


def _create_scope_validation_function() -> None:
    """OpenAPI로 정규화된 여섯 scope의 완전한 저장 shape를 검증한다."""
    op.execute(
        """
        CREATE FUNCTION ops.is_valid_feature_update_scope(
          p_scope_type text,
          p_scope jsonb
        ) RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
        DECLARE
          item jsonb;
          center_value jsonb;
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF jsonb_typeof(p_scope) IS DISTINCT FROM 'object'
             OR jsonb_typeof(p_scope->'type') IS DISTINCT FROM 'string'
             OR p_scope->>'type' IS DISTINCT FROM p_scope_type THEN
            RETURN false;
          END IF;

          CASE p_scope_type
            WHEN 'feature_ids' THEN
              IF p_scope - ARRAY['type', 'feature_ids']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'feature_ids') IS DISTINCT FROM 'array' THEN
                RETURN false;
              END IF;
              IF jsonb_array_length(p_scope->'feature_ids') > 1000 THEN
                RETURN false;
              END IF;
              FOR item IN SELECT value FROM jsonb_array_elements(p_scope->'feature_ids')
              LOOP
                IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
                  RETURN false;
                END IF;
                text_value := item #>> '{}';
                IF text_value <> btrim(text_value, canonical_whitespace)
                   OR text_value = ''
                   OR char_length(text_value) > 256 THEN
                  RETURN false;
                END IF;
                IF text_value = ANY(seen_values) THEN
                  RETURN false;
                END IF;
                seen_values := array_append(seen_values, text_value);
              END LOOP;
              RETURN true;

            WHEN 'center_radius' THEN
              IF p_scope - ARRAY['type', 'center', 'radius_km']::text[]
                   <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'center') IS DISTINCT FROM 'object'
                 OR jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              center_value := p_scope->'center';
              IF center_value - ARRAY['lon', 'lat']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(center_value->'lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(center_value->'lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (center_value->>'lon')::numeric BETWEEN -180 AND 180
                 AND (center_value->>'lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'radius_km')::numeric > 0
                 AND (p_scope->>'radius_km')::numeric <= 500;

            WHEN 'sigungu_by_radius' THEN
              IF p_scope - ARRAY['type', 'center', 'radius_km', 'match']::text[]
                   <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'center') IS DISTINCT FROM 'object'
                 OR jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'match') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              center_value := p_scope->'center';
              IF center_value - ARRAY['lon', 'lat']::text[] <> '{}'::jsonb
                 OR jsonb_typeof(center_value->'lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(center_value->'lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (center_value->>'lon')::numeric BETWEEN -180 AND 180
                 AND (center_value->>'lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'radius_km')::numeric > 0
                 AND (p_scope->>'radius_km')::numeric <= 500
                 AND p_scope->>'match' = 'intersects';

            WHEN 'bbox' THEN
              IF p_scope - ARRAY[
                   'type', 'min_lon', 'min_lat', 'max_lon', 'max_lat'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'min_lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'min_lat') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'max_lon') IS DISTINCT FROM 'number'
                 OR jsonb_typeof(p_scope->'max_lat') IS DISTINCT FROM 'number' THEN
                RETURN false;
              END IF;
              RETURN (p_scope->>'min_lon')::numeric BETWEEN -180 AND 180
                 AND (p_scope->>'max_lon')::numeric BETWEEN -180 AND 180
                 AND (p_scope->>'min_lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'max_lat')::numeric BETWEEN -90 AND 90
                 AND (p_scope->>'min_lon')::numeric <= (p_scope->>'max_lon')::numeric
                 AND (p_scope->>'min_lat')::numeric <= (p_scope->>'max_lat')::numeric;

            WHEN 'provider_dataset' THEN
              IF p_scope - ARRAY[
                   'type', 'provider', 'dataset_key', 'sync_scope'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'provider') IS DISTINCT FROM 'string'
                 OR jsonb_typeof(p_scope->'dataset_key') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              IF p_scope->>'provider' <>
                   btrim(p_scope->>'provider', canonical_whitespace)
                 OR p_scope->>'provider' = ''
                 OR char_length(p_scope->>'provider') > 128
                 OR p_scope->>'dataset_key' <>
                      btrim(p_scope->>'dataset_key', canonical_whitespace)
                 OR p_scope->>'dataset_key' = ''
                 OR char_length(p_scope->>'dataset_key') > 128 THEN
                RETURN false;
              END IF;
              IF p_scope ? 'sync_scope' THEN
                IF jsonb_typeof(p_scope->'sync_scope') IS DISTINCT FROM 'string'
                   OR p_scope->>'sync_scope' <>
                        btrim(p_scope->>'sync_scope', canonical_whitespace)
                   OR p_scope->>'sync_scope' = ''
                   OR char_length(p_scope->>'sync_scope') > 128 THEN
                  RETURN false;
                END IF;
              END IF;
              RETURN true;

            WHEN 'cache_target_keys' THEN
              IF p_scope - ARRAY[
                   'type', 'external_system', 'target_keys', 'radius_km', 'scope_mode'
                 ]::text[] <> '{}'::jsonb
                 OR jsonb_typeof(p_scope->'external_system') IS DISTINCT FROM 'string'
                 OR jsonb_typeof(p_scope->'target_keys') IS DISTINCT FROM 'array'
                 OR jsonb_typeof(p_scope->'scope_mode') IS DISTINCT FROM 'string' THEN
                RETURN false;
              END IF;
              IF jsonb_array_length(p_scope->'target_keys') > 500 THEN
                RETURN false;
              END IF;
              IF p_scope->>'external_system' <>
                   btrim(p_scope->>'external_system', canonical_whitespace)
                 OR p_scope->>'external_system' = ''
                 OR char_length(p_scope->>'external_system') > 128
                 OR p_scope->>'scope_mode' NOT IN ('center_radius', 'sigungu_by_radius') THEN
                RETURN false;
              END IF;
              IF p_scope ? 'radius_km' THEN
                IF jsonb_typeof(p_scope->'radius_km') IS DISTINCT FROM 'number' THEN
                  RETURN false;
                END IF;
                IF (p_scope->>'radius_km')::numeric <= 0
                   OR (p_scope->>'radius_km')::numeric > 500 THEN
                  RETURN false;
                END IF;
              END IF;
              FOR item IN SELECT value FROM jsonb_array_elements(p_scope->'target_keys')
              LOOP
                IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
                  RETURN false;
                END IF;
                text_value := item #>> '{}';
                IF text_value <> btrim(text_value, canonical_whitespace)
                   OR text_value = ''
                   OR char_length(text_value) > 256 THEN
                  RETURN false;
                END IF;
                IF text_value = ANY(seen_values) THEN
                  RETURN false;
                END IF;
                seen_values := array_append(seen_values, text_value);
              END LOOP;
              RETURN true;
            ELSE
              RETURN false;
          END CASE;
        END;
        $$
        """
    )


def _create_filter_validation_functions() -> None:
    """Legacy JSONB를 점검·변환하고 영속 TEXT[] shape를 검증하는 함수를 만든다."""
    op.execute(
        """
        CREATE FUNCTION ops.is_valid_feature_update_filter_jsonb(
          p_values jsonb,
          p_max_items integer
        ) RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
        DECLARE
          item jsonb;
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF p_max_items < 0
             OR jsonb_typeof(p_values) IS DISTINCT FROM 'array' THEN
            RETURN false;
          END IF;
          IF jsonb_array_length(p_values) > p_max_items THEN
            RETURN false;
          END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(p_values)
          LOOP
            IF jsonb_typeof(item) IS DISTINCT FROM 'string' THEN
              RETURN false;
            END IF;
            text_value := item #>> '{}';
            IF text_value <> btrim(text_value, canonical_whitespace)
               OR text_value = ''
               OR char_length(text_value) > 128 THEN
              RETURN false;
            END IF;
            IF text_value = ANY(seen_values) THEN
              RETURN false;
            END IF;
            seen_values := array_append(seen_values, text_value);
          END LOOP;
          RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.is_valid_feature_update_filter_array(
          p_values text[],
          p_max_items integer
        ) RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
        DECLARE
          text_value text;
          seen_values text[] := ARRAY[]::text[];
          canonical_whitespace text := ' '
            || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)
            || chr(28) || chr(29) || chr(30) || chr(31) || chr(133)
            || chr(160) || chr(5760) || chr(8192) || chr(8193) || chr(8194)
            || chr(8195) || chr(8196) || chr(8197) || chr(8198) || chr(8199)
            || chr(8200) || chr(8201) || chr(8202) || chr(8232) || chr(8233)
            || chr(8239) || chr(8287) || chr(12288);
        BEGIN
          IF p_max_items < 0
             OR COALESCE(array_ndims(p_values), 1) <> 1
             OR cardinality(p_values) > p_max_items
             OR (
               cardinality(p_values) > 0
               AND array_lower(p_values, 1) IS DISTINCT FROM 1
             ) THEN
            RETURN false;
          END IF;
          FOREACH text_value IN ARRAY p_values
          LOOP
            IF text_value IS NULL
               OR text_value <> btrim(text_value, canonical_whitespace)
               OR text_value = ''
               OR char_length(text_value) > 128 THEN
              RETURN false;
            END IF;
            IF text_value = ANY(seen_values) THEN
              RETURN false;
            END IF;
            seen_values := array_append(seen_values, text_value);
          END LOOP;
          RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.feature_update_filter_jsonb_to_array(p_values jsonb)
        RETURNS text[]
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
          SELECT COALESCE(
            array_agg(item.value ORDER BY item.ordinality),
            ARRAY[]::text[]
          )
          FROM jsonb_array_elements_text(p_values)
            WITH ORDINALITY AS item(value, ordinality)
        $$
        """
    )


def _create_update_policy_validation_function() -> None:
    """FeatureUpdatePolicy와 동일한 key/type의 canonical JSONB를 검증한다."""
    op.execute(
        """
        CREATE FUNCTION ops.is_valid_feature_update_policy(p_policy jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
        DECLARE
          boolean_key text;
        BEGIN
          IF jsonb_typeof(p_policy) IS DISTINCT FROM 'object'
             OR p_policy - ARRAY[
               'mode',
               'include_inactive',
               'force_provider_call',
               'dedup_after_load',
               'consistency_check_after_load',
               'prevent_provider_reactivation'
             ]::text[] <> '{}'::jsonb THEN
            RETURN false;
          END IF;

          IF p_policy ? 'mode'
             AND (
               jsonb_typeof(p_policy->'mode') IS DISTINCT FROM 'string'
               OR p_policy->>'mode' IS DISTINCT FROM 'refresh_existing'
             ) THEN
            RETURN false;
          END IF;

          FOREACH boolean_key IN ARRAY ARRAY[
            'include_inactive',
            'force_provider_call',
            'dedup_after_load',
            'consistency_check_after_load',
            'prevent_provider_reactivation'
          ]::text[]
          LOOP
            IF p_policy ? boolean_key
               AND jsonb_typeof(p_policy->boolean_key) IS DISTINCT FROM 'boolean' THEN
              RETURN false;
            END IF;
          END LOOP;
          RETURN true;
        END;
        $$
        """
    )


def _convert_filter_columns_to_arrays() -> None:
    """검증을 마친 legacy JSONB filter를 typed TEXT[]로 clean cut한다."""
    for column_name in ("providers", "dataset_keys"):
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} DROP DEFAULT"
        )
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} TYPE text[] "
            f"USING ops.feature_update_filter_jsonb_to_array({column_name})"
        )
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} SET DEFAULT '{{}}'::text[]"
        )
    op.execute("DROP FUNCTION ops.feature_update_filter_jsonb_to_array(jsonb)")
    op.execute("DROP FUNCTION ops.is_valid_feature_update_filter_jsonb(jsonb, integer)")


def _convert_filter_columns_to_jsonb() -> None:
    """downgrade에서 0051의 JSONB filter column을 복원한다."""
    for column_name in ("providers", "dataset_keys"):
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} DROP DEFAULT"
        )
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} TYPE jsonb USING to_jsonb({column_name})"
        )
        op.execute(
            f"ALTER TABLE ops.feature_update_requests "
            f"ALTER COLUMN {column_name} SET DEFAULT '[]'::jsonb"
        )


def _merge_request_cancellation_lifecycle() -> None:
    """legacy request member/marker를 1:1 canonical import job으로 병합한다."""
    connection = op.get_bind()
    conflicts = (
        connection.execute(
            sa.text(
                """
                SELECT request.request_id::text
                FROM ops.feature_update_requests AS request
                JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE request.cancellation_id IS NOT NULL
                  AND job.cancellation_id IS NOT NULL
                  AND job.cancellation_id <> request.cancellation_id
                UNION
                SELECT member.member_id::text
                FROM ops.pipeline_cancellation_members AS member
                JOIN ops.pipeline_cancellations AS attempt
                  ON attempt.cancellation_id = member.cancellation_id
                LEFT JOIN ops.feature_update_requests AS request
                  ON member.member_kind = 'update_request'
                 AND request.request_id = member.member_id
                LEFT JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE member.member_kind = 'update_request'
                  AND (
                    request.request_id IS NULL
                    OR job.job_id IS NULL
                    OR (
                      attempt.status IN ('in_progress','retryable')
                      AND member.dagster_run_id
                          IS DISTINCT FROM job.dagster_run_id
                    )
                    OR (
                      member.result IN ('cancelled','already_terminal')
                      AND job.status IN ('queued','running')
                    )
                    OR (
                      member.result IN ('pending','cancel_failed')
                      AND job.status IN ('done','failed','cancelled')
                    )
                    OR (
                      member.result = 'cancelled'
                      AND job.status <> 'cancelled'
                    )
                    OR (
                      member.result = 'already_terminal'
                      AND member.terminal_status IS DISTINCT FROM job.status
                    )
                    OR (
                      attempt.status IN ('in_progress','retryable')
                      AND request.cancellation_id
                          IS DISTINCT FROM member.cancellation_id
                      AND job.cancellation_id
                          IS DISTINCT FROM member.cancellation_id
                    )
                    OR (
                      attempt.status = 'completed'
                      AND member.result IN ('pending','cancel_failed')
                    )
                    OR EXISTS (
                      SELECT 1
                      FROM ops.pipeline_cancellation_runs AS canonical_run
                      WHERE canonical_run.cancellation_id = member.cancellation_id
                        AND canonical_run.dagster_run_id = job.dagster_run_id
                        AND canonical_run.result IS DISTINCT FROM (
                          CASE
                            WHEN member.result = 'cancelled'
                              AND job.status = 'cancelled' THEN 'cancelled'
                            WHEN job.status IN ('done','failed','cancelled')
                              THEN 'already_terminal'
                            ELSE member.result
                          END
                        )
                    )
                  )
                ORDER BY 1
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if conflicts:
        raise RuntimeError(
            "0052 cannot merge conflicting request/job cancellation lifecycle; "
            f"request_ids={conflicts!r}"
        )

    # request marker가 있거나 active request member만 있던 경우에도 canonical
    # job이 current attempt을 소유하게 한다. 한 request가 두 current marker를
    # 가리키는 경우는 위 preflight에서 거부된다.
    connection.execute(
        sa.text(
            """
            WITH marker_candidates AS (
              SELECT
                request.job_id,
                request.cancellation_id,
                request.cancellation_requested_at AS requested_at,
                request.cancellation_requested_by AS requested_by,
                request.cancellation_reason AS reason,
                0 AS precedence
              FROM ops.feature_update_requests AS request
              WHERE request.cancellation_id IS NOT NULL
              UNION ALL
              SELECT
                request.job_id,
                member.cancellation_id,
                attempt.requested_at,
                attempt.requested_by,
                attempt.reason,
                1 AS precedence
              FROM ops.pipeline_cancellation_members AS member
              JOIN ops.pipeline_cancellations AS attempt
                ON attempt.cancellation_id = member.cancellation_id
               AND attempt.status = 'in_progress'
              JOIN ops.feature_update_requests AS request
                ON member.member_kind = 'update_request'
               AND request.request_id = member.member_id
            ),
            current_markers AS (
              SELECT DISTINCT ON (job_id)
                job_id, cancellation_id, requested_at, requested_by, reason
              FROM marker_candidates
              ORDER BY job_id, precedence, requested_at DESC, cancellation_id DESC
            )
            UPDATE ops.import_jobs AS job
               SET cancellation_id = marker.cancellation_id,
                   cancellation_requested_at = COALESCE(
                     job.cancellation_requested_at,
                     marker.requested_at
                   ),
                   cancellation_requested_by = COALESCE(
                     job.cancellation_requested_by,
                     marker.requested_by
                   ),
                   cancellation_reason = COALESCE(
                     job.cancellation_reason,
                     marker.reason
                   )
              FROM current_markers AS marker
             WHERE job.job_id = marker.job_id
               AND (
                 job.cancellation_id IS NULL
                 OR job.cancellation_id = marker.cancellation_id
               )
            """
        )
    )

    # request member와 다른 run을 쓰는 canonical job으로 변환해도 FK가
    # 끊어지지 않도록 attempt/run row를 먼저 보충한다.
    connection.execute(
        sa.text(
            """
            INSERT INTO ops.pipeline_cancellation_runs (
              cancellation_id, dagster_run_id, result, terminal_status, error
            )
            SELECT DISTINCT
              member.cancellation_id,
              job.dagster_run_id,
              CASE
                WHEN member.result = 'cancelled' AND job.status = 'cancelled'
                  THEN 'cancelled'
                WHEN job.status IN ('done','failed','cancelled')
                  THEN 'already_terminal'
                ELSE member.result
              END,
              CASE
                WHEN member.result = 'cancelled' AND job.status = 'cancelled'
                  THEN 'CANCELED'
                ELSE NULL
              END,
              CASE
                WHEN member.result = 'cancel_failed'
                  AND job.status IN ('queued','running') THEN member.error
                ELSE NULL
              END
            FROM ops.pipeline_cancellation_members AS member
            JOIN ops.feature_update_requests AS request
              ON member.member_kind = 'update_request'
             AND request.request_id = member.member_id
            JOIN ops.import_jobs AS job ON job.job_id = request.job_id
            WHERE job.dagster_run_id IS NOT NULL
            ON CONFLICT (cancellation_id, dagster_run_id) DO NOTHING
            """
        )
    )

    # 이미 frozen job member가 있으면 그 행이 권위 있는 정보이므로
    # request mirror를 제거한다. 없으면 canonical job snapshot으로 clean cut한다.
    connection.execute(
        sa.text(
            """
            DELETE FROM ops.pipeline_cancellation_members AS request_member
            USING ops.feature_update_requests AS request,
                  ops.pipeline_cancellation_members AS job_member
            WHERE request_member.member_kind = 'update_request'
              AND request.request_id = request_member.member_id
              AND job_member.cancellation_id = request_member.cancellation_id
              AND job_member.member_kind = 'import_job'
              AND job_member.member_id = request.job_id
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE ops.pipeline_cancellation_members AS member
               SET member_kind = 'import_job',
                   member_id = job.job_id,
                   dagster_run_id = job.dagster_run_id,
                   operation_kind = CASE
                     WHEN job.kind = btrim(job.kind) AND job.kind <> ''
                     THEN job.kind
                     ELSE NULL
                   END,
                   requires_run_termination = (
                     job.dagster_run_id IS NOT NULL
                     AND (
                       job.status = 'running'
                       OR (
                         job.status = 'queued'
                         AND job.kind IN (
                           'provider_feature_load_run',
                           'provider_feature_load'
                         )
                       )
                     )
                   ),
                   initial_status = job.status,
                   result = CASE
                     WHEN member.result = 'cancelled'
                       AND job.status = 'cancelled' THEN 'cancelled'
                     WHEN job.status IN ('done','failed','cancelled')
                       THEN 'already_terminal'
                     ELSE member.result
                   END,
                   terminal_status = CASE
                     WHEN member.result = 'cancelled'
                       AND job.status = 'cancelled' THEN 'cancelled'
                     WHEN job.status IN ('done','failed','cancelled')
                       THEN job.status
                     ELSE NULL
                   END,
                   error = CASE
                     WHEN job.status IN ('done','failed','cancelled') THEN NULL
                     ELSE member.error
                   END,
                   updated_at = now()
              FROM ops.feature_update_requests AS request
              JOIN ops.import_jobs AS job ON job.job_id = request.job_id
             WHERE member.member_kind = 'update_request'
               AND request.request_id = member.member_id
            """
        )
    )

    active_orphan_members = (
        connection.execute(
            sa.text(
                """
                SELECT
                  member.cancellation_id::text || ':' || member.member_id::text
                FROM ops.pipeline_cancellation_members AS member
                JOIN ops.pipeline_cancellations AS attempt
                  ON attempt.cancellation_id = member.cancellation_id
                LEFT JOIN ops.import_jobs AS job
                  ON member.member_kind = 'import_job'
                 AND job.job_id = member.member_id
                WHERE member.member_kind = 'import_job'
                  AND job.job_id IS NULL
                  AND attempt.status IN ('in_progress','retryable')
                ORDER BY member.cancellation_id, member.member_id
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if active_orphan_members:
        raise RuntimeError(
            "0052 cannot discard active/retryable orphan cancellation members; "
            f"cancellation_members={active_orphan_members!r}"
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM ops.pipeline_cancellation_members AS member
            USING ops.pipeline_cancellations AS attempt
            WHERE attempt.cancellation_id = member.cancellation_id
              AND member.member_kind = 'import_job'
              AND attempt.status IN ('completed','failed')
              AND NOT EXISTS (
                SELECT 1
                FROM ops.import_jobs AS job
                WHERE job.job_id = member.member_id
              )
            """
        )
    )

    active_orphan_runs = (
        connection.execute(
            sa.text(
                """
                SELECT
                  run.cancellation_id::text || ':' || run.dagster_run_id
                FROM ops.pipeline_cancellation_runs AS run
                JOIN ops.pipeline_cancellations AS attempt
                  ON attempt.cancellation_id = run.cancellation_id
                WHERE attempt.status IN ('in_progress','retryable')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ops.pipeline_cancellation_members AS member
                    WHERE member.cancellation_id = run.cancellation_id
                      AND member.dagster_run_id = run.dagster_run_id
                  )
                ORDER BY run.cancellation_id, run.dagster_run_id
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if active_orphan_runs:
        raise RuntimeError(
            "0052 cannot discard active/retryable orphan cancellation runs; "
            f"cancellation_runs={active_orphan_runs!r}"
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM ops.pipeline_cancellation_runs AS run
            USING ops.pipeline_cancellations AS attempt
            WHERE attempt.cancellation_id = run.cancellation_id
              AND attempt.status IN ('completed','failed')
              AND NOT EXISTS (
                SELECT 1
                FROM ops.pipeline_cancellation_members AS member
                WHERE member.cancellation_id = run.cancellation_id
                  AND member.dagster_run_id = run.dagster_run_id
              )
            """
        )
    )


def _repair_request_job_identity() -> None:
    """기존 request마다 scope shape와 일치하는 canonical job을 보장한다."""
    connection = op.get_bind()
    persisted_dry_runs = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE dry_run
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if persisted_dry_runs:
        raise RuntimeError(
            f"0052 cannot migrate persisted dry-run requests; request_ids={persisted_dry_runs!r}"
        )

    malformed = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE NOT ops.is_valid_feature_update_scope(scope_type, scope)
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if malformed:
        raise RuntimeError(
            f"0052 cannot repair malformed feature update request scope; request_ids={malformed!r}"
        )

    malformed_filters = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE NOT ops.is_valid_feature_update_filter_jsonb(providers, 32)
               OR NOT ops.is_valid_feature_update_filter_jsonb(dataset_keys, 64)
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if malformed_filters:
        raise RuntimeError(
            "0052 cannot repair malformed feature update request filters; "
            f"request_ids={malformed_filters!r}"
        )

    mismatched_direct_filters = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE scope_type = 'provider_dataset'
              AND (
                providers NOT IN (
                  '[]'::jsonb,
                  jsonb_build_array(scope->>'provider')
                )
                OR dataset_keys NOT IN (
                  '[]'::jsonb,
                  jsonb_build_array(scope->>'dataset_key')
                )
              )
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if mismatched_direct_filters:
        raise RuntimeError(
            "0052 cannot repair provider_dataset requests with conflicting filters; "
            f"request_ids={mismatched_direct_filters!r}"
        )
    connection.execute(
        sa.text(
            """
            UPDATE ops.feature_update_requests
               SET providers = '[]'::jsonb,
                   dataset_keys = '[]'::jsonb
             WHERE scope_type = 'provider_dataset'
               AND (providers <> '[]'::jsonb OR dataset_keys <> '[]'::jsonb)
            """
        )
    )
    invalid_priorities = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE priority NOT BETWEEN 0 AND 1000
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if invalid_priorities:
        raise RuntimeError(
            "0052 cannot migrate feature update requests with invalid priority; "
            f"request_ids={invalid_priorities!r}"
        )

    invalid_reasons = (
        connection.execute(
            sa.text(
                """
                SELECT request_id::text
                FROM ops.feature_update_requests
                WHERE reason IS NOT NULL
                  AND (
                    reason = ''
                    OR reason <> btrim(reason)
                    OR reason ~ '^[[:space:]]|[[:space:]]$'
                    OR char_length(reason) > 500
                  )
                ORDER BY request_id
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if invalid_reasons:
        raise RuntimeError(
            "0052 cannot migrate malformed feature update request reasons; "
            f"request_ids={invalid_reasons!r}"
        )

    malformed_policies = (
        connection.execute(
            sa.text(
                """
            SELECT request_id::text
            FROM ops.feature_update_requests
            WHERE NOT ops.is_valid_feature_update_policy(update_policy)
            ORDER BY request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if malformed_policies:
        raise RuntimeError(
            "0052 cannot migrate malformed feature update policy values; "
            f"request_ids={malformed_policies!r}"
        )

    invalid_execution_owners = (
        connection.execute(
            sa.text(
                """
                SELECT request.request_id::text
                FROM ops.feature_update_requests AS request
                LEFT JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE (
                    request.dagster_run_id IS NOT NULL
                    AND (
                      request.dagster_run_id <> btrim(request.dagster_run_id)
                      OR request.dagster_run_id = ''
                    )
                  )
                   OR (request.status = 'queued' AND request.dagster_run_id IS NOT NULL)
                   OR (request.status = 'running' AND request.dagster_run_id IS NULL)
                   OR (
                     job.kind = 'feature_update_request'
                     AND (
                       (
                         job.dagster_run_id IS NOT NULL
                         AND (
                           job.dagster_run_id <> btrim(job.dagster_run_id)
                           OR job.dagster_run_id = ''
                         )
                       )
                       OR (job.status = 'queued' AND job.dagster_run_id IS NOT NULL)
                       OR (job.status = 'running' AND job.dagster_run_id IS NULL)
                     )
                   )
                ORDER BY request.request_id
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if invalid_execution_owners:
        raise RuntimeError(
            "0052 cannot migrate invalid feature update execution owners; "
            f"request_ids={invalid_execution_owners!r}"
        )

    frozen_cancellation_requests = (
        connection.execute(
            sa.text(
                """
            WITH RECURSIVE requests_to_relink AS MATERIALIZED (
                SELECT
                    request.request_id,
                    request.job_id AS source_job_id,
                    request.cancellation_id AS request_cancellation_id
                FROM ops.feature_update_requests AS request
                LEFT JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE job.job_id IS NULL
                   OR EXISTS (
                     SELECT 1
                     FROM ops.feature_update_requests AS peer
                     WHERE peer.job_id = request.job_id
                       AND (peer.created_at, peer.request_id)
                           < (request.created_at, request.request_id)
                       AND (
                         (
                           peer.scope_type = 'provider_dataset'
                           AND job.provider IS NOT DISTINCT FROM peer.scope->>'provider'
                           AND job.dataset_key IS NOT DISTINCT FROM peer.scope->>'dataset_key'
                         )
                         OR (
                           peer.scope_type <> 'provider_dataset'
                           AND job.provider IS NULL
                           AND job.dataset_key IS NULL
                         )
                       )
                   )
                   OR job.kind IS DISTINCT FROM 'feature_update_request'
                   OR (
                     job.kind = 'feature_update_request'
                     AND (
                       job.parent_job_id IS NOT NULL
                       OR job.load_batch_id IS NOT NULL
                       OR job.trigger_kind IS DISTINCT FROM 'update_request'
                       OR job.operation_registry_version IS NOT NULL
                       OR job.dagster_run_status IS NOT NULL
                     )
                   )
                   OR (
                     request.scope_type = 'provider_dataset'
                     AND (
                       job.provider IS DISTINCT FROM request.scope->>'provider'
                       OR job.dataset_key IS DISTINCT FROM request.scope->>'dataset_key'
                     )
                   )
                   OR (
                     request.scope_type <> 'provider_dataset'
                     AND (job.provider IS NOT NULL OR job.dataset_key IS NOT NULL)
                   )
            ),
            connected_jobs AS (
                SELECT
                    candidate.request_id,
                    job.job_id,
                    job.parent_job_id,
                    job.cancellation_id
                FROM requests_to_relink AS candidate
                JOIN ops.import_jobs AS job
                  ON job.job_id = candidate.source_job_id
                UNION
                SELECT
                    branch.request_id,
                    neighbor.job_id,
                    neighbor.parent_job_id,
                    neighbor.cancellation_id
                FROM connected_jobs AS branch
                JOIN ops.import_jobs AS neighbor
                  ON neighbor.parent_job_id = branch.job_id
                  OR neighbor.job_id = branch.parent_job_id
            )
            SELECT candidate.request_id::text
            FROM requests_to_relink AS candidate
            WHERE candidate.request_cancellation_id IS NOT NULL
              AND EXISTS (
                SELECT 1
                FROM connected_jobs AS branch
                WHERE branch.request_id = candidate.request_id
                  AND branch.cancellation_id IS NOT NULL
                  AND branch.cancellation_id
                      <> candidate.request_cancellation_id
              )
            ORDER BY candidate.request_id
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if frozen_cancellation_requests:
        raise RuntimeError(
            "0052 cannot merge conflicting request/job cancellation markers; "
            f"request_ids={frozen_cancellation_requests!r}"
        )

    active_source_requests = (
        connection.execute(
            sa.text(
                """
            WITH RECURSIVE requests_to_relink AS MATERIALIZED (
                SELECT
                    request.request_id,
                    request.job_id AS source_job_id,
                    request.status AS request_status,
                    job.job_id AS existing_job_id
                FROM ops.feature_update_requests AS request
                LEFT JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE job.job_id IS NULL
                   OR EXISTS (
                     SELECT 1
                     FROM ops.feature_update_requests AS peer
                     WHERE peer.job_id = request.job_id
                       AND (peer.created_at, peer.request_id)
                           < (request.created_at, request.request_id)
                       AND (
                         (
                           peer.scope_type = 'provider_dataset'
                           AND job.provider IS NOT DISTINCT FROM peer.scope->>'provider'
                           AND job.dataset_key IS NOT DISTINCT FROM peer.scope->>'dataset_key'
                         )
                         OR (
                           peer.scope_type <> 'provider_dataset'
                           AND job.provider IS NULL
                           AND job.dataset_key IS NULL
                         )
                       )
                   )
                   OR job.kind IS DISTINCT FROM 'feature_update_request'
                   OR (
                     job.kind = 'feature_update_request'
                     AND (
                       job.parent_job_id IS NOT NULL
                       OR job.load_batch_id IS NOT NULL
                       OR job.trigger_kind IS DISTINCT FROM 'update_request'
                       OR job.operation_registry_version IS NOT NULL
                       OR job.dagster_run_status IS NOT NULL
                     )
                   )
                   OR (
                     request.scope_type = 'provider_dataset'
                     AND (
                       job.provider IS DISTINCT FROM request.scope->>'provider'
                       OR job.dataset_key IS DISTINCT FROM request.scope->>'dataset_key'
                     )
                   )
                   OR (
                     request.scope_type <> 'provider_dataset'
                     AND (job.provider IS NOT NULL OR job.dataset_key IS NOT NULL)
                   )
            ),
            connected_jobs AS (
                SELECT
                    candidate.request_id,
                    job.job_id,
                    job.parent_job_id,
                    job.status,
                    job.dagster_run_status
                FROM requests_to_relink AS candidate
                JOIN ops.import_jobs AS job
                  ON job.job_id = candidate.source_job_id
                UNION
                SELECT
                    branch.request_id,
                    neighbor.job_id,
                    neighbor.parent_job_id,
                    neighbor.status,
                    neighbor.dagster_run_status
                FROM connected_jobs AS branch
                JOIN ops.import_jobs AS neighbor
                  ON neighbor.parent_job_id = branch.job_id
                  OR neighbor.job_id = branch.parent_job_id
            )
            SELECT DISTINCT candidate.request_id::text
            FROM requests_to_relink AS candidate
            LEFT JOIN connected_jobs AS branch
              ON branch.request_id = candidate.request_id
            WHERE candidate.request_status = 'running'
               OR EXISTS (
                 SELECT 1
                 FROM ops.feature_update_requests AS peer
                 WHERE peer.job_id = candidate.source_job_id
                   AND peer.request_id <> candidate.request_id
                   AND peer.status = 'running'
               )
               OR branch.status IN ('queued', 'running')
               OR branch.dagster_run_status IN (
                 'QUEUED', 'NOT_STARTED', 'MANAGED', 'STARTING', 'STARTED',
                 'CANCELING'
               )
            ORDER BY candidate.request_id::text
            LIMIT 20
            """
            )
        )
        .scalars()
        .all()
    )
    if active_source_requests:
        raise RuntimeError(
            "0052 cannot relink feature update requests with an active source branch; "
            f"request_ids={active_source_requests!r}"
        )

    connection.execute(
        sa.text(
            """
            WITH requests_to_relink AS MATERIALIZED (
                SELECT
                    request.request_id,
                    request.job_id AS source_job_id,
                    request.scope_type,
                    request.scope,
                    request.status,
                    request.error_message,
                    request.dagster_run_id,
                    request.started_at,
                    request.finished_at,
                    request.created_at
                FROM ops.feature_update_requests AS request
                LEFT JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE job.job_id IS NULL
                   OR EXISTS (
                     SELECT 1
                     FROM ops.feature_update_requests AS peer
                     WHERE peer.job_id = request.job_id
                       AND (peer.created_at, peer.request_id)
                           < (request.created_at, request.request_id)
                       AND (
                         (
                           peer.scope_type = 'provider_dataset'
                           AND job.provider IS NOT DISTINCT FROM peer.scope->>'provider'
                           AND job.dataset_key IS NOT DISTINCT FROM peer.scope->>'dataset_key'
                         )
                         OR (
                           peer.scope_type <> 'provider_dataset'
                           AND job.provider IS NULL
                           AND job.dataset_key IS NULL
                         )
                       )
                   )
                   OR job.kind IS DISTINCT FROM 'feature_update_request'
                   OR (
                     job.kind = 'feature_update_request'
                     AND (
                       job.parent_job_id IS NOT NULL
                       OR job.load_batch_id IS NOT NULL
                       OR job.trigger_kind IS DISTINCT FROM 'update_request'
                       OR job.operation_registry_version IS NOT NULL
                       OR job.dagster_run_status IS NOT NULL
                     )
                   )
                   OR (
                     request.scope_type = 'provider_dataset'
                     AND (
                       job.provider IS DISTINCT FROM request.scope->>'provider'
                       OR job.dataset_key IS DISTINCT FROM request.scope->>'dataset_key'
                     )
                   )
                   OR (
                     request.scope_type <> 'provider_dataset'
                     AND (job.provider IS NOT NULL OR job.dataset_key IS NOT NULL)
                   )
            ),
            prepared_jobs AS MATERIALIZED (
                SELECT
                    x_extension.gen_random_uuid() AS job_id,
                    request.*
                FROM requests_to_relink AS request
            ),
            inserted_jobs AS (
                INSERT INTO ops.import_jobs (
                    job_id,
                    kind,
                    payload,
                    status,
                    progress,
                    error_message,
                    dagster_run_id,
                    provider,
                    dataset_key,
                    trigger_kind,
                    started_at,
                    finished_at,
                    created_at
                )
                SELECT
                    request.job_id,
                    'feature_update_request',
                    '{}'::jsonb,
                    request.status,
                    CASE WHEN request.status = 'done' THEN 100 ELSE 0 END,
                    request.error_message,
                    request.dagster_run_id,
                    CASE WHEN request.scope_type = 'provider_dataset'
                      THEN request.scope->>'provider' END,
                    CASE WHEN request.scope_type = 'provider_dataset'
                      THEN request.scope->>'dataset_key' END,
                    'update_request',
                    request.started_at,
                    request.finished_at,
                    request.created_at
                FROM prepared_jobs AS request
                RETURNING job_id
            ),
            updated_requests AS (
                UPDATE ops.feature_update_requests AS request
                   SET job_id = prepared.job_id
                  FROM prepared_jobs AS prepared
                  JOIN inserted_jobs AS inserted ON inserted.job_id = prepared.job_id
                 WHERE request.request_id = prepared.request_id
                RETURNING request.request_id, request.job_id
            )
            INSERT INTO ops.import_job_events (
                job_id, level, code, message, payload, occurred_at
            )
            SELECT
                updated.job_id,
                'info',
                'migration.feature_update_request_relinked',
                '0052에서 canonical feature update job을 재생성함',
                jsonb_strip_nulls(jsonb_build_object(
                    'source_job_id', prepared.source_job_id::text
                )),
                now()
            FROM updated_requests AS updated
            JOIN prepared_jobs AS prepared
              ON prepared.request_id = updated.request_id
            """
        )
    )
    _merge_request_cancellation_lifecycle()
    protected_orphan_jobs = (
        connection.execute(
            sa.text(
                """
                WITH RECURSIVE orphan_roots AS MATERIALIZED (
                  SELECT job.job_id
                  FROM ops.import_jobs AS job
                  WHERE job.kind = 'feature_update_request'
                    AND NOT EXISTS (
                      SELECT 1
                      FROM ops.feature_update_requests AS request
                      WHERE request.job_id = job.job_id
                    )
                ),
                connected_jobs AS (
                  SELECT
                    root.job_id AS root_job_id,
                    job.job_id,
                    job.parent_job_id,
                    job.status,
                    job.dagster_run_status,
                    job.cancellation_id
                  FROM orphan_roots AS root
                  JOIN ops.import_jobs AS job ON job.job_id = root.job_id
                  UNION
                  SELECT
                    branch.root_job_id,
                    neighbor.job_id,
                    neighbor.parent_job_id,
                    neighbor.status,
                    neighbor.dagster_run_status,
                    neighbor.cancellation_id
                  FROM connected_jobs AS branch
                  JOIN ops.import_jobs AS neighbor
                    ON neighbor.parent_job_id = branch.job_id
                    OR neighbor.job_id = branch.parent_job_id
                )
                SELECT DISTINCT branch.root_job_id::text
                FROM connected_jobs AS branch
                WHERE branch.status IN ('queued', 'running')
                   OR branch.dagster_run_status IN (
                     'QUEUED', 'NOT_STARTED', 'MANAGED', 'STARTING', 'STARTED',
                     'CANCELING'
                   )
                   OR branch.cancellation_id IS NOT NULL
                   OR EXISTS (
                    SELECT 1
                    FROM ops.pipeline_cancellation_members AS member
                    JOIN connected_jobs AS member_job
                      ON member_job.root_job_id = branch.root_job_id
                     AND member.member_kind = 'import_job'
                     AND member.member_id = member_job.job_id
                  )
                   OR EXISTS (
                     SELECT 1
                     FROM ops.feature_update_requests AS request
                     JOIN connected_jobs AS request_job
                       ON request_job.root_job_id = branch.root_job_id
                      AND request.job_id = request_job.job_id
                  )
                ORDER BY branch.root_job_id::text
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if protected_orphan_jobs:
        raise RuntimeError(
            "0052 cannot quarantine active, request-linked, or cancellation-protected "
            "orphan feature "
            f"update jobs; job_ids={protected_orphan_jobs!r}"
        )
    connection.execute(
        sa.text(
            """
            WITH RECURSIVE orphan_roots AS MATERIALIZED (
              SELECT job.job_id
              FROM ops.import_jobs AS job
              WHERE job.kind = 'feature_update_request'
                AND NOT EXISTS (
                  SELECT 1
                  FROM ops.feature_update_requests AS request
                  WHERE request.job_id = job.job_id
                )
            ),
            connected_jobs AS (
              SELECT root.job_id AS root_job_id, job.job_id, job.parent_job_id
              FROM orphan_roots AS root
              JOIN ops.import_jobs AS job ON job.job_id = root.job_id
              UNION
              SELECT branch.root_job_id, neighbor.job_id, neighbor.parent_job_id
              FROM connected_jobs AS branch
              JOIN ops.import_jobs AS neighbor
                ON neighbor.parent_job_id = branch.job_id
                OR neighbor.job_id = branch.parent_job_id
            ),
            quarantine_ids AS MATERIALIZED (
              SELECT DISTINCT job_id
              FROM connected_jobs
            )
            UPDATE ops.import_jobs AS job
               SET quarantined_at = now(),
                   quarantine_reason = 'unlinked_feature_update_component'
              FROM quarantine_ids AS quarantine
             WHERE job.job_id = quarantine.job_id
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE ops.import_jobs
               SET payload = '{}'::jsonb
             WHERE kind = 'feature_update_request'
               AND quarantined_at IS NULL
               AND payload <> '{}'::jsonb
            """
        )
    )


def _validate_request_lifecycle_mirror() -> None:
    """활성/취소 연계 request와 canonical job의 중복 lifecycle drift를 거부한다."""
    inconsistent = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT request.request_id::text
                FROM ops.feature_update_requests AS request
                JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                WHERE (
                    request.status IN ('queued','running')
                    OR job.status IN ('queued','running')
                    OR request.cancellation_id IS NOT NULL
                    OR job.cancellation_id IS NOT NULL
                )
                  AND (
                    request.status IS DISTINCT FROM job.status
                    OR request.dagster_run_id IS DISTINCT FROM job.dagster_run_id
                    OR request.cancellation_id IS DISTINCT FROM job.cancellation_id
                    OR request.cancellation_requested_at
                       IS DISTINCT FROM job.cancellation_requested_at
                    OR request.cancellation_requested_by
                       IS DISTINCT FROM job.cancellation_requested_by
                    OR request.cancellation_reason IS DISTINCT FROM job.cancellation_reason
                    OR request.error_message IS DISTINCT FROM job.error_message
                    OR request.started_at IS DISTINCT FROM job.started_at
                    OR request.finished_at IS DISTINCT FROM job.finished_at
                  )
                ORDER BY request.request_id
                LIMIT 20
                """
            )
        )
        .scalars()
        .all()
    )
    if inconsistent:
        raise RuntimeError(
            "0052 cannot remove divergent active/cancellation-linked request lifecycle; "
            f"request_ids={inconsistent!r}"
        )


def _simplify_cancellation_member_identity() -> None:
    """constant kind를 제거하고 import job FK identity로 clean cut한다."""
    op.drop_index(
        "idx_pipeline_cancellation_members_member",
        table_name="pipeline_cancellation_members",
        schema="ops",
    )
    op.drop_constraint(
        op.f("pk_pipeline_cancellation_members"),
        "pipeline_cancellation_members",
        schema="ops",
        type_="primary",
    )
    # member_kind를 참조하는 legacy kind/operation_kind CHECK는 column 제거와
    # 함께 정리한다. 과거 naming convention으로 잘린 이름에 의존하지 않는다.
    op.drop_column("pipeline_cancellation_members", "member_kind", schema="ops")
    op.alter_column(
        "pipeline_cancellation_members",
        "member_id",
        new_column_name="job_id",
        schema="ops",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_primary_key(
        op.f("pk_pipeline_cancellation_members"),
        "pipeline_cancellation_members",
        ["cancellation_id", "job_id"],
        schema="ops",
    )
    op.create_foreign_key(
        op.f("fk_pipeline_cancellation_members_job"),
        "pipeline_cancellation_members",
        "import_jobs",
        ["job_id"],
        ["job_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_pipeline_cancellation_members_operation_kind"),
        "pipeline_cancellation_members",
        "operation_kind IS NULL OR (operation_kind = btrim(operation_kind) "
        "AND operation_kind <> '')",
        schema="ops",
    )
    op.create_index(
        "idx_pipeline_cancellation_members_job",
        "pipeline_cancellation_members",
        ["job_id", sa.text("updated_at DESC"), sa.text("cancellation_id DESC")],
        schema="ops",
    )


def _restore_cancellation_member_identity() -> None:
    """downgrade에서 0051의 composite member identity를 복원한다."""
    op.drop_index(
        "idx_pipeline_cancellation_members_job",
        table_name="pipeline_cancellation_members",
        schema="ops",
    )
    for constraint_name, constraint_type in (
        ("ck_pipeline_cancellation_members_operation_kind", "check"),
        ("fk_pipeline_cancellation_members_job", "foreignkey"),
        ("pk_pipeline_cancellation_members", "primary"),
    ):
        op.drop_constraint(
            op.f(constraint_name),
            "pipeline_cancellation_members",
            schema="ops",
            type_=constraint_type,
        )
    op.alter_column(
        "pipeline_cancellation_members",
        "job_id",
        new_column_name="member_id",
        schema="ops",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.add_column(
        "pipeline_cancellation_members",
        sa.Column(
            "member_kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'import_job'"),
        ),
        schema="ops",
    )
    op.alter_column(
        "pipeline_cancellation_members",
        "member_kind",
        schema="ops",
        server_default=None,
    )
    op.create_primary_key(
        op.f("pk_pipeline_cancellation_members"),
        "pipeline_cancellation_members",
        ["cancellation_id", "member_kind", "member_id"],
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_pipeline_cancellation_members_kind"),
        "pipeline_cancellation_members",
        "member_kind IN ('import_job','update_request')",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_pipeline_cancellation_members_operation_kind"),
        "pipeline_cancellation_members",
        "operation_kind IS NULL OR (member_kind = 'import_job' "
        "AND operation_kind = btrim(operation_kind) AND operation_kind <> '')",
        schema="ops",
    )
    op.create_index(
        "idx_pipeline_cancellation_members_member",
        "pipeline_cancellation_members",
        [
            "member_kind",
            "member_id",
            sa.text("updated_at DESC"),
            sa.text("cancellation_id DESC"),
        ],
        schema="ops",
    )


def _create_identity_invariants() -> None:
    op.create_check_constraint(
        op.f("ck_import_jobs_update_request_shape"),
        "import_jobs",
        "kind <> 'feature_update_request' OR quarantined_at IS NOT NULL OR "
        "(parent_job_id IS NULL AND load_batch_id IS NULL "
        "AND trigger_kind = 'update_request' "
        "AND operation_registry_version IS NULL AND dagster_run_status IS NULL "
        "AND payload = '{}'::jsonb "
        "AND (dagster_run_id IS NULL OR (dagster_run_id = btrim(dagster_run_id) "
        "AND dagster_run_id <> '')) "
        "AND (status <> 'queued' OR dagster_run_id IS NULL) "
        "AND (status <> 'running' OR dagster_run_id IS NOT NULL))",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_quarantine_shape"),
        "import_jobs",
        "(quarantined_at IS NULL AND quarantine_reason IS NULL) OR "
        "(quarantined_at IS NOT NULL AND "
        "quarantine_reason = 'unlinked_feature_update_component')",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_scope_shape"),
        "feature_update_requests",
        "ops.is_valid_feature_update_scope(scope_type, scope)",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_providers_shape"),
        "feature_update_requests",
        "ops.is_valid_feature_update_filter_array(providers, 32)",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_dataset_keys_shape"),
        "feature_update_requests",
        "ops.is_valid_feature_update_filter_array(dataset_keys, 64)",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_update_policy_shape"),
        "feature_update_requests",
        "ops.is_valid_feature_update_policy(update_policy)",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_direct_filters_empty"),
        "feature_update_requests",
        "scope_type <> 'provider_dataset' OR "
        "(cardinality(providers) = 0 AND cardinality(dataset_keys) = 0)",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_priority_range"),
        "feature_update_requests",
        "priority BETWEEN 0 AND 1000",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_generation_positive"),
        "feature_update_requests",
        "generation > 0",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_matched_scope_object"),
        "feature_update_requests",
        "jsonb_typeof(matched_scope) = 'object'",
        schema="ops",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_reason_shape"),
        "feature_update_requests",
        "reason IS NULL OR (reason <> '' AND reason = btrim(reason) "
        "AND reason !~ '^[[:space:]]|[[:space:]]$' AND char_length(reason) <= 500)",
        schema="ops",
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_import_job_identity_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NEW.kind IS DISTINCT FROM OLD.kind
             OR NEW.provider IS DISTINCT FROM OLD.provider
             OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key
             OR (
               OLD.kind = 'feature_update_request'
               AND NEW.payload IS DISTINCT FROM OLD.payload
             ) THEN
            RAISE EXCEPTION
              'import job kind/provider/dataset/payload identity is immutable for job %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_identity_immutable
        BEFORE UPDATE OF kind, provider, dataset_key, payload ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_canonical_feature_update_job_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF OLD.kind = 'feature_update_request' THEN
            RAISE EXCEPTION 'canonical feature update job is append-only: %', OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_feature_update_append_only
        BEFORE DELETE ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_canonical_feature_update_job_delete()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_import_job_quarantine_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.quarantined_at IS NOT NULL OR NEW.quarantine_reason IS NOT NULL THEN
              RAISE EXCEPTION
                'import job quarantine markers are migration-owned: %', NEW.job_id
                USING ERRCODE = 'check_violation';
            END IF;
          ELSIF OLD.quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION 'quarantined import job is immutable: %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          ELSIF TG_OP = 'UPDATE'
             AND (
               NEW.quarantined_at IS DISTINCT FROM OLD.quarantined_at
               OR NEW.quarantine_reason IS DISTINCT FROM OLD.quarantine_reason
             ) THEN
            RAISE EXCEPTION
              'import job quarantine markers are migration-owned: %', OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          IF NEW.parent_job_id IS NOT NULL AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS parent
            WHERE parent.job_id = NEW.parent_job_id
              AND parent.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot attach a job to quarantined import job: %',
              NEW.parent_job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_jobs_quarantine_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON ops.import_jobs
        FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_quarantine_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_quarantined_import_job_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP = 'INSERT' AND NEW.quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION
              'import job event quarantine marker is migration-owned: %', NEW.event_id
              USING ERRCODE = 'check_violation';
          ELSIF TG_OP = 'UPDATE'
             AND NEW.quarantined_at IS DISTINCT FROM OLD.quarantined_at THEN
            RAISE EXCEPTION
              'import job event quarantine marker is migration-owned: %', OLD.event_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP <> 'INSERT' AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = OLD.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'events of a quarantined import job are immutable: %',
              OLD.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP <> 'DELETE' AND EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot append an event to quarantined import job: %',
              NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_events_quarantine_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_events
        FOR EACH ROW EXECUTE FUNCTION ops.reject_quarantined_import_job_event_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.guard_import_job_event_clock_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'import job event clock singleton cannot be %', TG_OP
              USING ERRCODE = 'check_violation';
          END IF;
          IF pg_trigger_depth() < 2
             OR NEW.clock_id IS DISTINCT FROM OLD.clock_id
             OR NEW.revision IS DISTINCT FROM OLD.revision + 1 THEN
            RAISE EXCEPTION
              'import job event clock is event-trigger-owned: revision % -> %',
              OLD.revision, NEW.revision
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_event_clock_mutation_guard
        BEFORE UPDATE OR DELETE ON ops.import_job_event_clock
        FOR EACH ROW EXECUTE FUNCTION ops.guard_import_job_event_clock_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_event_clock_truncate_guard
        BEFORE TRUNCATE ON ops.import_job_event_clock
        FOR EACH STATEMENT EXECUTE FUNCTION ops.guard_import_job_event_clock_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.bump_import_job_event_clock()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          INSERT INTO ops.import_job_event_clock AS clock (
            clock_id, revision, updated_at
          ) VALUES (
            TRUE, 1, clock_timestamp()
          )
          ON CONFLICT (clock_id) DO UPDATE
             SET revision = clock.revision + 1,
                 updated_at = clock_timestamp();
          RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_job_events_clock
        AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON ops.import_job_events
        FOR EACH STATEMENT EXECUTE FUNCTION ops.bump_import_job_event_clock()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.reject_quarantined_cancellation_member()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
              AND job.quarantined_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'cannot cancel a quarantined import job: %', NEW.job_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_pipeline_cancellation_members_reject_quarantine
        BEFORE INSERT OR UPDATE OF job_id ON ops.pipeline_cancellation_members
        FOR EACH ROW EXECUTE FUNCTION ops.reject_quarantined_cancellation_member()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.enforce_feature_update_request_job_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          linked_kind text;
          linked_provider text;
          linked_dataset_key text;
          linked_quarantined_at timestamptz;
        BEGIN
          SELECT job.kind, job.provider, job.dataset_key, job.quarantined_at
            INTO linked_kind, linked_provider, linked_dataset_key, linked_quarantined_at
            FROM ops.import_jobs AS job
           WHERE job.job_id = NEW.job_id
           FOR KEY SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'feature update request job does not exist: %', NEW.job_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          IF linked_kind IS DISTINCT FROM 'feature_update_request' THEN
            RAISE EXCEPTION
              'feature update request must link a canonical feature_update_request job'
              USING ERRCODE = 'check_violation';
          END IF;

          IF linked_quarantined_at IS NOT NULL THEN
            RAISE EXCEPTION
              'feature update request cannot link a quarantined import job'
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.scope_type = 'provider_dataset' THEN
            IF linked_provider IS DISTINCT FROM NEW.scope->>'provider'
               OR linked_dataset_key IS DISTINCT FROM NEW.scope->>'dataset_key' THEN
              RAISE EXCEPTION
                'provider_dataset request scope must equal linked job identity'
                USING ERRCODE = 'check_violation';
            END IF;
          ELSIF linked_provider IS NOT NULL OR linked_dataset_key IS NOT NULL THEN
            RAISE EXCEPTION
              'non-provider_dataset request must link an unpaired import job'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_update_requests_job_identity
        BEFORE INSERT
        ON ops.feature_update_requests
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_feature_update_request_job_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.guard_feature_update_request_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          linked_status text;
          linked_cancellation_id uuid;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'feature update request is append-only: %', OLD.request_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.request_id IS DISTINCT FROM OLD.request_id
             OR NEW.job_id IS DISTINCT FROM OLD.job_id
             OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
             OR NEW.scope IS DISTINCT FROM OLD.scope
             OR NEW.providers IS DISTINCT FROM OLD.providers
             OR NEW.dataset_keys IS DISTINCT FROM OLD.dataset_keys
             OR NEW.update_policy IS DISTINCT FROM OLD.update_policy
             OR NEW.run_mode IS DISTINCT FROM OLD.run_mode
             OR NEW.priority IS DISTINCT FROM OLD.priority
             OR NEW.operator IS DISTINCT FROM OLD.operator
             OR NEW.reason IS DISTINCT FROM OLD.reason
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'feature update request input/audit identity is immutable: %',
              OLD.request_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.generation IS DISTINCT FROM OLD.generation
             AND NEW.generation <> OLD.generation + 1 THEN
            RAISE EXCEPTION 'feature update request generation must increase by exactly one: %',
              OLD.request_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.matched_scope IS DISTINCT FROM OLD.matched_scope
             OR NEW.generation IS DISTINCT FROM OLD.generation THEN
            SELECT job.status, job.cancellation_id
              INTO linked_status, linked_cancellation_id
              FROM ops.import_jobs AS job
             WHERE job.job_id = OLD.job_id
             FOR UPDATE;
            IF NOT FOUND
               OR linked_status NOT IN ('queued','running')
               OR linked_cancellation_id IS NOT NULL THEN
              RAISE EXCEPTION
                'feature update request mutable fields require active unmarked job: %',
                OLD.request_id
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_feature_update_requests_mutation_guard
        BEFORE UPDATE OR DELETE ON ops.feature_update_requests
        FOR EACH ROW EXECUTE FUNCTION ops.guard_feature_update_request_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.assert_feature_update_job_pair(candidate_job_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
          job_kind text;
          job_quarantined_at timestamptz;
        BEGIN
          SELECT job.kind, job.quarantined_at
            INTO job_kind, job_quarantined_at
            FROM ops.import_jobs AS job
           WHERE job.job_id = candidate_job_id;
          IF NOT FOUND
             OR job_kind IS DISTINCT FROM 'feature_update_request'
             OR job_quarantined_at IS NOT NULL THEN
            RETURN;
          END IF;

          PERFORM 1
            FROM ops.feature_update_requests AS request
           WHERE request.job_id = candidate_job_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'non-quarantined canonical feature update job must have exactly one request: %',
              candidate_job_id
              USING ERRCODE = 'check_violation';
          END IF;

        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ops.enforce_feature_update_job_pair()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          PERFORM ops.assert_feature_update_job_pair(NEW.job_id);
          RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_import_jobs_feature_update_pair
        AFTER INSERT ON ops.import_jobs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ops.enforce_feature_update_job_pair()
        """
    )


def upgrade() -> None:
    _lock_identity_writers()
    _create_scope_validation_function()
    _create_filter_validation_functions()
    _create_update_policy_validation_function()
    op.add_column(
        "import_jobs",
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    op.add_column(
        "import_jobs",
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        schema="ops",
    )
    op.add_column(
        "import_job_events",
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )
    op.create_table(
        "import_job_event_clock",
        sa.Column(
            "clock_id",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "clock_id",
            name=op.f("ck_import_job_event_clock_singleton"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_import_job_event_clock_revision_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "clock_id",
            name=op.f("pk_import_job_event_clock"),
        ),
        schema="ops",
    )
    op.execute(
        """
        INSERT INTO ops.import_job_event_clock (clock_id, revision, updated_at)
        VALUES (TRUE, 0, clock_timestamp())
        """
    )
    _repair_request_job_identity()
    op.execute(
        """
        UPDATE ops.import_job_events AS event
           SET quarantined_at = job.quarantined_at
          FROM ops.import_jobs AS job
         WHERE job.job_id = event.job_id
           AND job.quarantined_at IS NOT NULL
        """
    )
    _validate_request_lifecycle_mirror()
    op.add_column(
        "feature_update_requests",
        sa.Column(
            "generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_status_priority",
        table_name="feature_update_requests",
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_created",
        table_name="feature_update_requests",
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_requests_cancellation_id",
        table_name="feature_update_requests",
        schema="ops",
    )
    # PostgreSQL은 참조 column을 제거할 때 해당 CHECK도 함께 제거한다. 과거
    # naming convention으로 잘린 실제 constraint 이름에 의존하지 않는다.
    op.drop_constraint(
        "fk_feature_update_requests_cancellation",
        "feature_update_requests",
        schema="ops",
        type_="foreignkey",
    )
    for column_name in (
        "status",
        "dagster_run_id",
        "cancellation_id",
        "cancellation_requested_at",
        "cancellation_requested_by",
        "cancellation_reason",
        "error_message",
        "started_at",
        "finished_at",
        "updated_at",
    ):
        op.drop_column("feature_update_requests", column_name, schema="ops")
    _simplify_cancellation_member_identity()
    _convert_filter_columns_to_arrays()
    op.drop_column("feature_update_requests", "dry_run", schema="ops")
    op.drop_constraint(
        _REQUEST_JOB_FK,
        "feature_update_requests",
        schema="ops",
        type_="foreignkey",
    )
    op.alter_column(
        "feature_update_requests",
        "job_id",
        schema="ops",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        _REQUEST_JOB_FK,
        "feature_update_requests",
        "import_jobs",
        ["job_id"],
        ["job_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        op.f("uq_feature_update_requests_job_id"),
        "feature_update_requests",
        ["job_id"],
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_job",
        table_name="feature_update_requests",
        schema="ops",
    )
    _create_identity_invariants()

    op.create_index(
        "idx_import_jobs_quarantined",
        "import_jobs",
        [sa.text("quarantined_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("quarantined_at IS NOT NULL"),
    )

    for index_name in (
        "idx_import_job_events_job_time",
        "idx_import_job_events_provider_time",
        "idx_import_job_events_level_time",
    ):
        op.drop_index(
            index_name,
            table_name="import_job_events",
            schema="ops",
        )
    op.create_index(
        "idx_import_job_events_time",
        "import_job_events",
        [sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text("quarantined_at IS NULL"),
    )
    op.create_index(
        "idx_import_job_events_job_time",
        "import_job_events",
        ["job_id", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text("quarantined_at IS NULL"),
    )
    op.create_index(
        "idx_import_job_events_provider_time",
        "import_job_events",
        ["provider", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text(
            "provider IS NOT NULL AND quarantined_at IS NULL"
        ),
    )
    op.create_index(
        "idx_import_job_events_dataset_time",
        "import_job_events",
        ["dataset_key", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text(
            "dataset_key IS NOT NULL AND quarantined_at IS NULL"
        ),
    )
    op.create_index(
        "idx_import_job_events_provider_dataset_time",
        "import_job_events",
        [
            "provider",
            "dataset_key",
            sa.text("occurred_at DESC"),
            sa.text("event_id DESC"),
        ],
        schema="ops",
        postgresql_where=sa.text(
            "provider IS NOT NULL AND dataset_key IS NOT NULL "
            "AND quarantined_at IS NULL"
        ),
    )
    op.create_index(
        "idx_import_job_events_level_time",
        "import_job_events",
        ["level", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text("quarantined_at IS NULL"),
    )
    op.create_index(
        "idx_feature_update_providers_gin",
        "feature_update_requests",
        ["providers"],
        schema="ops",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_feature_update_dataset_keys_gin",
        "feature_update_requests",
        ["dataset_keys"],
        schema="ops",
        postgresql_using="gin",
    )
    op.create_index(
        "idx_feature_update_priority",
        "feature_update_requests",
        [sa.text("priority DESC"), "created_at", "request_id"],
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_created",
        "feature_update_requests",
        [sa.text("created_at DESC"), sa.text("request_id DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_import_jobs_feature_update_queue",
        "import_jobs",
        ["job_id"],
        schema="ops",
        postgresql_where=sa.text(
            "kind = 'feature_update_request' AND status = 'queued' "
            "AND cancellation_id IS NULL"
        ),
    )


def _restore_request_lifecycle_for_downgrade() -> None:
    op.add_column(
        "feature_update_requests",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        schema="ops",
    )
    for column in (
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("cancellation_id", sa.UUID(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_by", sa.Text(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("feature_update_requests", column, schema="ops")
    op.add_column(
        "feature_update_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="ops",
    )
    op.execute(
        """
        UPDATE ops.feature_update_requests AS request
           SET status = job.status,
               dagster_run_id = job.dagster_run_id,
               cancellation_id = job.cancellation_id,
               cancellation_requested_at = job.cancellation_requested_at,
               cancellation_requested_by = job.cancellation_requested_by,
               cancellation_reason = job.cancellation_reason,
               error_message = job.error_message,
               started_at = job.started_at,
               finished_at = job.finished_at,
               updated_at = COALESCE(
                 job.finished_at, job.heartbeat_at, job.started_at, job.created_at
               )
          FROM ops.import_jobs AS job
         WHERE job.job_id = request.job_id
        """
    )
    op.create_check_constraint(
        op.f("ck_feature_update_status"),
        "feature_update_requests",
        "status IN ('queued','running','done','failed','cancelled')",
        schema="ops",
    )
    op.create_foreign_key(
        "fk_feature_update_requests_cancellation",
        "feature_update_requests",
        "pipeline_cancellations",
        ["cancellation_id"],
        ["cancellation_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_feature_update_requests_cancellation_marker"),
        "feature_update_requests",
        "(cancellation_id IS NULL AND cancellation_requested_at IS NULL "
        "AND cancellation_requested_by IS NULL AND cancellation_reason IS NULL) OR "
        "(cancellation_id IS NOT NULL AND cancellation_requested_at IS NOT NULL "
        "AND cancellation_requested_by IS NOT NULL)",
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_status_priority",
        "feature_update_requests",
        ["status", sa.text("priority DESC"), "created_at"],
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_created",
        "feature_update_requests",
        [sa.text("created_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_feature_update_requests_cancellation_id",
        "feature_update_requests",
        ["cancellation_id"],
        schema="ops",
    )


def downgrade() -> None:
    _lock_identity_writers()
    op.execute(
        "DROP TRIGGER trg_pipeline_cancellation_members_reject_quarantine "
        "ON ops.pipeline_cancellation_members"
    )
    op.execute("DROP FUNCTION ops.reject_quarantined_cancellation_member()")
    _restore_cancellation_member_identity()
    op.drop_index(
        "idx_import_jobs_feature_update_queue",
        table_name="import_jobs",
        schema="ops",
    )
    op.drop_index(
        "idx_import_jobs_quarantined",
        table_name="import_jobs",
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_priority",
        table_name="feature_update_requests",
        schema="ops",
    )
    op.drop_index(
        "idx_feature_update_created",
        table_name="feature_update_requests",
        schema="ops",
    )
    op.execute(
        "DROP TRIGGER trg_feature_update_requests_mutation_guard "
        "ON ops.feature_update_requests"
    )
    op.execute("DROP FUNCTION ops.guard_feature_update_request_mutation()")
    op.execute(
        "DROP TRIGGER trg_import_job_events_quarantine_immutable "
        "ON ops.import_job_events"
    )
    op.execute("DROP FUNCTION ops.reject_quarantined_import_job_event_mutation()")
    op.execute(
        "DROP TRIGGER trg_import_job_events_clock ON ops.import_job_events"
    )
    op.execute("DROP FUNCTION ops.bump_import_job_event_clock()")
    op.execute(
        "DROP TRIGGER trg_import_job_event_clock_truncate_guard "
        "ON ops.import_job_event_clock"
    )
    op.execute(
        "DROP TRIGGER trg_import_job_event_clock_mutation_guard "
        "ON ops.import_job_event_clock"
    )
    op.execute("DROP FUNCTION ops.guard_import_job_event_clock_mutation()")
    op.execute(
        "DROP TRIGGER trg_import_jobs_feature_update_append_only ON ops.import_jobs"
    )
    op.execute("DROP FUNCTION ops.reject_canonical_feature_update_job_delete()")
    op.execute(
        "DROP TRIGGER trg_import_jobs_quarantine_immutable "
        "ON ops.import_jobs"
    )
    op.execute("DROP FUNCTION ops.reject_import_job_quarantine_mutation()")
    _restore_request_lifecycle_for_downgrade()
    for index_name in (
        "idx_feature_update_dataset_keys_gin",
        "idx_feature_update_providers_gin",
    ):
        op.drop_index(
            index_name,
            table_name="feature_update_requests",
            schema="ops",
        )
    for index_name in (
        "idx_import_job_events_provider_dataset_time",
        "idx_import_job_events_dataset_time",
        "idx_import_job_events_provider_time",
        "idx_import_job_events_level_time",
        "idx_import_job_events_job_time",
        "idx_import_job_events_time",
    ):
        op.drop_index(
            index_name,
            table_name="import_job_events",
            schema="ops",
        )
    op.create_index(
        "idx_import_job_events_job_time",
        "import_job_events",
        ["job_id", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_import_job_events_provider_time",
        "import_job_events",
        ["provider", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
        postgresql_where=sa.text("provider IS NOT NULL"),
    )
    op.create_index(
        "idx_import_job_events_level_time",
        "import_job_events",
        ["level", sa.text("occurred_at DESC"), sa.text("event_id DESC")],
        schema="ops",
    )
    op.drop_column("import_job_events", "quarantined_at", schema="ops")
    op.drop_table("import_job_event_clock", schema="ops")
    op.execute("DROP TRIGGER trg_import_jobs_feature_update_pair ON ops.import_jobs")
    op.execute("DROP FUNCTION ops.enforce_feature_update_job_pair()")
    op.execute("DROP FUNCTION ops.assert_feature_update_job_pair(uuid)")
    op.execute(
        "DROP TRIGGER trg_feature_update_requests_job_identity ON ops.feature_update_requests"
    )
    op.execute("DROP FUNCTION ops.enforce_feature_update_request_job_identity()")
    op.drop_constraint(
        op.f("ck_import_jobs_update_request_shape"),
        "import_jobs",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_import_jobs_quarantine_shape"),
        "import_jobs",
        schema="ops",
        type_="check",
    )
    op.drop_column("import_jobs", "quarantine_reason", schema="ops")
    op.drop_column("import_jobs", "quarantined_at", schema="ops")
    op.execute("DROP TRIGGER trg_import_jobs_identity_immutable ON ops.import_jobs")
    op.execute("DROP FUNCTION ops.reject_import_job_identity_change()")
    op.drop_constraint(
        op.f("ck_feature_update_requests_reason_shape"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_priority_range"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_generation_positive"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_matched_scope_object"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_column("feature_update_requests", "generation", schema="ops")
    op.drop_constraint(
        op.f("ck_feature_update_requests_direct_filters_empty"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_update_policy_shape"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_dataset_keys_shape"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_providers_shape"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_feature_update_requests_scope_shape"),
        "feature_update_requests",
        schema="ops",
        type_="check",
    )
    op.execute("DROP FUNCTION ops.is_valid_feature_update_filter_array(text[], integer)")
    op.execute("DROP FUNCTION ops.is_valid_feature_update_policy(jsonb)")
    _convert_filter_columns_to_jsonb()
    op.execute("DROP FUNCTION ops.is_valid_feature_update_scope(text, jsonb)")
    op.drop_constraint(
        _REQUEST_JOB_FK,
        "feature_update_requests",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_feature_update_requests_job_id"),
        "feature_update_requests",
        schema="ops",
        type_="unique",
    )
    op.alter_column(
        "feature_update_requests",
        "job_id",
        schema="ops",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        _REQUEST_JOB_FK,
        "feature_update_requests",
        "import_jobs",
        ["job_id"],
        ["job_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_feature_update_job",
        "feature_update_requests",
        ["job_id"],
        schema="ops",
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )
    op.add_column(
        "feature_update_requests",
        sa.Column(
            "dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="ops",
    )
