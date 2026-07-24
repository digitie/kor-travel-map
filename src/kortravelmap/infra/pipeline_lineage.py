"""C3b root projection과 계층형 취소가 공유하는 lineage CTE 정본.

ADR-077: root/component 멤버십은 ``import_jobs.root_id``/``root_kind``로 저장된다
(DB 트리거가 parent에서 파생, ≤2단계 lock). 따라서 과거의 재귀 ``job_ancestry``/
component 파생은 제거하고, ``anchor_requests``/``job_components``/``job_owners``/
``standalone_jobs``를 ``root_id`` 직접 조회로 만든다. 다운스트림(``_PIPELINE_ROOT_BODY_SQL``의
ranked/summaries/roots/members/pairs 및 pipeline_cancellation_queries)은 이 네 CTE의
출력 컬럼만 알므로 그대로 둔다.

``PIPELINE_LINEAGE_BODY_SQL``은 payload를 포함하지 않는 ``pipeline_jobs``와
``pipeline_requests`` source CTE를 입력으로 받는다. 전역 조회는 전역 source를 붙인
``PIPELINE_LINEAGE_CTES_SQL``을, scoped 조회는 ``root_id``로 좁힌 source를 공급한다.
scoped source의 ``pipeline_jobs``도 ``root_id``/``root_kind``를 반드시 투영해야 한다.
"""

from __future__ import annotations

from typing import Final

PIPELINE_LINEAGE_SOURCE_SQL: Final[str] = """
pipeline_jobs AS MATERIALIZED (
    SELECT
        job_id,
        kind,
        load_batch_id,
        parent_job_id,
        root_id,
        root_kind,
        status,
        progress,
        current_stage,
        error_message,
        dagster_run_id,
        provider,
        dataset_key,
        trigger_kind,
        operation_registry_version,
        dagster_run_status,
        started_at,
        finished_at,
        created_at
    FROM ops.import_jobs
    WHERE quarantined_at IS NULL
),
pipeline_requests AS MATERIALIZED (
    SELECT
        request_id,
        scope_type,
        scope,
        providers,
        dataset_keys,
        run_mode,
        priority,
        identity_job.status,
        request.job_id,
        identity_job.sync_scope AS effective_sync_scope,
        identity_job.dagster_run_id,
        request.operator,
        identity_job.error_message,
        identity_job.started_at,
        identity_job.finished_at,
        request.created_at
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS identity_job
      ON identity_job.job_id = request.job_id
     AND identity_job.quarantined_at IS NULL
)
"""

# root_id가 저장돼 있으므로 lineage는 재귀 없이 직접 조회다. depth는 ≤2단계라
# root면 0, 자식이면 1(``job_id = root_id`` 여부). 출력 컬럼/의미는 과거 재귀 버전과
# 동일하다(다운스트림 불변).
#   - anchor_requests: 각 request의 anchor job이 곧 root(component_root_id = job_id).
#   - job_components: 모든 job → 자신의 component root(= root_id).
#   - job_owners: root_kind='update_request' job은 그 root(=anchor job)의 request가 소유.
#   - standalone_jobs: root_kind='import_job' job(= request가 소유하지 않는 component).
PIPELINE_LINEAGE_BODY_SQL: Final[str] = """
anchor_requests AS (
    SELECT
        request.request_id,
        request.job_id AS anchor_job_id,
        request.job_id AS component_root_id,
        request.created_at
    FROM pipeline_requests AS request
),
job_components AS (
    SELECT
        job.job_id,
        job.root_id AS component_root_id,
        CASE WHEN job.job_id = job.root_id THEN 0 ELSE 1 END AS depth
    FROM pipeline_jobs AS job
),
job_owners AS (
    SELECT
        job.job_id,
        request.request_id AS owner_request_id,
        job.root_id AS anchor_job_id,
        job.root_id AS component_root_id,
        CASE WHEN job.job_id = job.root_id THEN 0 ELSE 1 END AS anchor_depth
    FROM pipeline_jobs AS job
    JOIN pipeline_requests AS request ON request.job_id = job.root_id
    WHERE job.root_kind = 'update_request'
),
standalone_jobs AS (
    SELECT
        job.job_id,
        job.root_id AS component_root_id,
        CASE WHEN job.job_id = job.root_id THEN 0 ELSE 1 END AS depth,
        job.kind,
        job.status,
        job.progress,
        job.current_stage,
        job.error_message,
        job.created_at,
        job.started_at,
        job.finished_at,
        job.dagster_run_id,
        job.provider,
        job.dataset_key,
        job.trigger_kind,
        job.operation_registry_version,
        job.dagster_run_status,
        job.load_batch_id,
        job.parent_job_id
    FROM pipeline_jobs AS job
    WHERE job.root_kind = 'import_job'
)
"""

PIPELINE_LINEAGE_CTES_SQL: Final[str] = (
    PIPELINE_LINEAGE_SOURCE_SQL + ",\n" + PIPELINE_LINEAGE_BODY_SQL
)

__all__ = [
    "PIPELINE_LINEAGE_BODY_SQL",
    "PIPELINE_LINEAGE_CTES_SQL",
    "PIPELINE_LINEAGE_SOURCE_SQL",
]
