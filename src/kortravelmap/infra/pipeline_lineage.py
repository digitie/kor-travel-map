"""C3b root projection과 계층형 취소가 공유하는 lineage CTE 정본."""

from __future__ import annotations

from typing import Final

PIPELINE_LINEAGE_CTES_SQL: Final[str] = """
job_ancestry AS (
    SELECT
        job_id AS leaf_job_id,
        job_id AS ancestor_job_id,
        parent_job_id,
        0 AS depth,
        ARRAY[job_id]::uuid[] AS path,
        false AS cycle
    FROM ops.import_jobs
    UNION ALL
    SELECT
        walk.leaf_job_id,
        parent.job_id,
        parent.parent_job_id,
        walk.depth + 1,
        walk.path || parent.job_id,
        parent.job_id = ANY(walk.path)
    FROM job_ancestry AS walk
    JOIN ops.import_jobs AS parent ON parent.job_id = walk.parent_job_id
    WHERE NOT walk.cycle
),
cycle_roots AS (
    SELECT DISTINCT ON (cycle_row.leaf_job_id)
        cycle_row.leaf_job_id,
        member AS component_root_id
    FROM job_ancestry AS cycle_row
    CROSS JOIN LATERAL unnest(
        cycle_row.path[
            array_position(cycle_row.path, cycle_row.ancestor_job_id)
            : array_length(cycle_row.path, 1) - 1
        ]
    ) AS cycle_members(member)
    WHERE cycle_row.cycle
    ORDER BY cycle_row.leaf_job_id, member
),
terminal_roots AS (
    SELECT DISTINCT ON (walk.leaf_job_id)
        walk.leaf_job_id,
        walk.ancestor_job_id AS component_root_id
    FROM job_ancestry AS walk
    LEFT JOIN ops.import_jobs AS parent ON parent.job_id = walk.parent_job_id
    WHERE NOT walk.cycle
      AND parent.job_id IS NULL
    ORDER BY walk.leaf_job_id, walk.depth DESC
),
job_component_roots AS (
    SELECT
        job.job_id,
        COALESCE(cycle.component_root_id, terminal.component_root_id, job.job_id)
            AS component_root_id
    FROM ops.import_jobs AS job
    LEFT JOIN cycle_roots AS cycle ON cycle.leaf_job_id = job.job_id
    LEFT JOIN terminal_roots AS terminal ON terminal.leaf_job_id = job.job_id
),
job_components AS (
    SELECT
        root.job_id,
        root.component_root_id,
        MIN(walk.depth)::integer AS depth
    FROM job_component_roots AS root
    JOIN job_ancestry AS walk
      ON walk.leaf_job_id = root.job_id
     AND walk.ancestor_job_id = root.component_root_id
    GROUP BY root.job_id, root.component_root_id
),
anchor_request_candidates AS (
    SELECT
        request.request_id,
        request.job_id AS anchor_job_id,
        component.component_root_id,
        request.created_at,
        ROW_NUMBER() OVER (
            PARTITION BY request.job_id
            ORDER BY request.created_at ASC, request.request_id ASC
        ) AS owner_rank
    FROM ops.feature_update_requests AS request
    JOIN job_components AS component ON component.job_id = request.job_id
),
anchor_requests AS (
    SELECT request_id, anchor_job_id, component_root_id, created_at
    FROM anchor_request_candidates
    WHERE owner_rank = 1
),
job_anchor_candidates AS (
    SELECT
        walk.leaf_job_id AS job_id,
        anchor.request_id AS owner_request_id,
        anchor.anchor_job_id,
        anchor.component_root_id,
        walk.depth::integer AS anchor_depth,
        ROW_NUMBER() OVER (
            PARTITION BY walk.leaf_job_id
            ORDER BY
                walk.depth ASC,
                anchor.created_at ASC,
                anchor.request_id ASC
        ) AS ownership_rank
    FROM job_ancestry AS walk
    JOIN anchor_requests AS anchor
      ON anchor.anchor_job_id = walk.ancestor_job_id
),
job_owners AS (
    SELECT
        job_id,
        owner_request_id,
        anchor_job_id,
        component_root_id,
        anchor_depth
    FROM job_anchor_candidates
    WHERE ownership_rank = 1
),
standalone_jobs AS (
    SELECT
        component.job_id,
        component.component_root_id,
        component.depth,
        job.kind,
        job.status,
        job.progress,
        job.current_stage,
        job.error_message,
        job.created_at,
        job.started_at,
        job.finished_at,
        job.dagster_run_id,
        job.load_batch_id,
        job.parent_job_id
    FROM job_components AS component
    JOIN ops.import_jobs AS job ON job.job_id = component.job_id
    LEFT JOIN job_owners AS owner ON owner.job_id = component.job_id
    WHERE owner.job_id IS NULL
)
"""

__all__ = ["PIPELINE_LINEAGE_CTES_SQL"]
