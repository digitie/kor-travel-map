"""``kortravelmap.infra.dataset_status_repo`` — dataset 상태 화면 조회 (ADR-064).

admin ``/ops/datasets`` 그룹(T-ADM-C2)이 provider×dataset 그리드/상세를 만들 때
필요한 read-only 보조 조회를 둔다. ``ops_repo``가 실행(작업/이벤트/이슈)의 keyset
cursor 목록을 책임진다면, 본 모듈은 화면 join용 집계/일괄 조회 2종을 둔다:

- ``count_open_integrity_issues_by_dataset`` — provider×dataset별 미해결
  (open/acknowledged) data integrity 이슈 카운트. 그리드 이슈 배지 join용.
- ``list_ops_import_jobs_by_ids`` — update request에 연결된 import job들을
  타임스탬프 포함 ``OpsImportJob``으로 일괄 조회(상세의 최근 실행 요약용).
- ``list_latest_dataset_executions`` — event에 canonical provider/dataset이 기록된
  import job과 provider_dataset update request를 한 번에 합쳐 dataset별 최신 실행을
  반환한다. 그리드 행별 detail 조회(N+1)를 금지한다.

raw SQL은 본 모듈에 모으고(ADR-004), commit은 호출자 책임.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.infra.ops_repo import OpsImportJob

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DatasetIntegrityIssueCount",
    "DatasetLatestExecution",
    "count_open_integrity_issues_by_dataset",
    "list_latest_dataset_executions",
    "list_ops_import_jobs_by_ids",
]


@dataclass(frozen=True)
class DatasetIntegrityIssueCount:
    """provider×dataset 1조합의 미해결 integrity 이슈 집계.

    ``dataset_key``가 ``None``이면 provider에만 귀속된 이슈 묶음이다. 서비스는
    이를 dataset-level 집계와 섞지 않고 별도 필드로 노출한다.
    """

    provider: str
    dataset_key: str | None
    open_total: int
    by_severity: dict[str, int]


@dataclass(frozen=True)
class DatasetLatestExecution:
    """provider×dataset의 DB에 기록된 최신 실행 요약.

    schedule/manual Dagster run 전체의 정본은 아니다. import job event 또는
    ``provider_dataset`` update request로 canonical dataset identity가 DB에 남은
    실행만 포함한다(#679가 전체 operation 정본을 별도로 완성한다).
    """

    provider: str
    dataset_key: str
    kind: str
    execution_id: str
    status: str
    status_source: str
    job_status: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    job_id: str | None
    request_id: str | None
    progress: int | None
    current_stage: str | None
    error_message: str | None


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


# open/acknowledged(=아직 사람이 닫지 않은) 이슈만 집계한다 — ``ops_repo``의
# ``get_ops_integrity_issue_counts``(전역 집계)와 같은 "미해결" 기준.
_COUNT_OPEN_ISSUES_SQL: Final[str] = """
WITH open_issues AS (
    SELECT provider, dataset_key, severity
    FROM ops.data_integrity_violations
    WHERE status IN ('open', 'acknowledged')
      AND provider IS NOT NULL
      AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
      AND (
        CAST(:dataset_key AS text) IS NULL
        OR dataset_key = CAST(:dataset_key AS text)
        OR dataset_key IS NULL
      )
),
by_severity AS (
    SELECT provider, dataset_key, severity, count(*) AS n
    FROM open_issues
    GROUP BY provider, dataset_key, severity
)
SELECT
    provider,
    dataset_key,
    CAST(sum(n) AS bigint) AS open_total,
    jsonb_object_agg(severity, n) AS by_severity
FROM by_severity
GROUP BY provider, dataset_key
ORDER BY provider, dataset_key
"""


async def count_open_integrity_issues_by_dataset(
    session: AsyncSession,
    *,
    provider: str | None = None,
    dataset_key: str | None = None,
) -> tuple[DatasetIntegrityIssueCount, ...]:
    """provider×dataset별 미해결 integrity 이슈 카운트(+severity 분해)를 반환한다.

    이슈가 전혀 없는 조합은 행을 만들지 않는다 — 그리드 join 시 미매칭 조합은
    0으로 간주하면 된다. ``dataset_key`` 필터를 주어도 같은 provider의
    provider-level(``dataset_key IS NULL``) 묶음은 함께 반환한다.
    """
    rows = (
        await session.execute(
            text(_COUNT_OPEN_ISSUES_SQL),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).all()
    return tuple(
        DatasetIntegrityIssueCount(
            provider=str(row.provider),
            dataset_key=row.dataset_key,
            open_total=int(row.open_total),
            by_severity={
                str(key): int(value)
                for key, value in _json_dict(row.by_severity).items()
            },
        )
        for row in rows
    )


_LIST_LATEST_EXECUTIONS_SQL: Final[str] = """
WITH RECURSIVE request_job_roots AS (
    SELECT request.request_id, job.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job ON job.job_id = request.job_id

    UNION

    SELECT request.request_id, job.job_id
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job
      ON NULLIF(job.payload->>'request_id', '') = request.request_id::text
),
request_job_lineage AS (
    SELECT
        root.request_id,
        root.job_id,
        0::integer AS depth,
        ARRAY[root.job_id]::uuid[] AS path
    FROM request_job_roots AS root

    UNION ALL

    SELECT
        lineage.request_id,
        child.job_id,
        lineage.depth + 1,
        lineage.path || child.job_id
    FROM request_job_lineage AS lineage
    JOIN ops.import_jobs AS child ON child.parent_job_id = lineage.job_id
    WHERE NOT child.job_id = ANY(lineage.path)
),
request_latest_job AS (
    -- request status/timestamp는 root가 정본이다. job_* projection만 가장 깊은
    -- descendant를 우선하고, 같은 depth에서는 created_at/job_id로 total order한다.
    SELECT DISTINCT ON (lineage.request_id)
        lineage.request_id,
        job.*
    FROM request_job_lineage AS lineage
    JOIN ops.import_jobs AS job ON job.job_id = lineage.job_id
    ORDER BY
        lineage.request_id,
        lineage.depth DESC,
        job.created_at DESC,
        job.job_id DESC
),
job_candidates AS (
    SELECT DISTINCT ON (event.provider, event.dataset_key)
        event.provider,
        event.dataset_key,
        'import_job'::text AS kind,
        job.job_id::text AS execution_id,
        job.status,
        'import_job'::text AS status_source,
        NULL::text AS job_status,
        job.created_at,
        job.started_at,
        job.finished_at,
        job.dagster_run_id,
        job.job_id,
        NULLIF(job.payload->>'request_id', '') AS request_id,
        job.progress,
        job.current_stage,
        job.error_message,
        0::integer AS source_rank
    FROM ops.import_job_events AS event
    JOIN ops.import_jobs AS job ON job.job_id = event.job_id
    WHERE event.provider IS NOT NULL
      AND event.dataset_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1
        FROM request_job_lineage AS lineage
        WHERE lineage.job_id = job.job_id
      )
    ORDER BY
        event.provider,
        event.dataset_key,
        job.created_at DESC,
        job.job_id DESC
),
request_candidates AS (
    SELECT
        request.scope->>'provider' AS provider,
        request.scope->>'dataset_key' AS dataset_key,
        'update_request'::text AS kind,
        request.request_id::text AS execution_id,
        request.status,
        'update_request'::text AS status_source,
        job.status AS job_status,
        request.created_at,
        request.started_at,
        request.finished_at,
        COALESCE(request.dagster_run_id, job.dagster_run_id) AS dagster_run_id,
        job.job_id,
        request.request_id::text AS request_id,
        job.progress,
        job.current_stage,
        COALESCE(request.error_message, job.error_message) AS error_message,
        1::integer AS source_rank
    FROM ops.feature_update_requests AS request
    LEFT JOIN request_latest_job AS job ON job.request_id = request.request_id
    WHERE request.scope_type = 'provider_dataset'
      AND NULLIF(request.scope->>'provider', '') IS NOT NULL
      AND NULLIF(request.scope->>'dataset_key', '') IS NOT NULL
),
ranked AS (
    SELECT
        candidate.*,
        row_number() OVER (
            PARTITION BY candidate.provider, candidate.dataset_key
            ORDER BY
                candidate.created_at DESC,
                candidate.source_rank,
                candidate.execution_id DESC
        ) AS row_number
    FROM (
        SELECT * FROM job_candidates
        UNION ALL
        SELECT * FROM request_candidates
    ) AS candidate
)
SELECT
    provider,
    dataset_key,
    kind,
    execution_id,
    status,
    status_source,
    job_status,
    created_at,
    started_at,
    finished_at,
    dagster_run_id,
    job_id,
    request_id,
    progress,
    current_stage,
    error_message
FROM ranked
WHERE row_number = 1
ORDER BY provider, dataset_key
"""


async def list_latest_dataset_executions(
    session: AsyncSession,
) -> tuple[DatasetLatestExecution, ...]:
    """dataset별 최신 DB 실행을 단일 batch query로 반환한다.

    import job은 자유 JSON payload가 아니라 ``import_job_events``의 canonical
    ``provider``/``dataset_key``를 사용한다. update request는 identity가 명확한
    ``provider_dataset`` scope만 포함해 다중 배열의 잘못된 조합을 만들지 않는다.
    """
    rows = (await session.execute(text(_LIST_LATEST_EXECUTIONS_SQL))).all()
    return tuple(
        DatasetLatestExecution(
            provider=str(row.provider),
            dataset_key=str(row.dataset_key),
            kind=str(row.kind),
            execution_id=str(row.execution_id),
            status=str(row.status),
            status_source=str(row.status_source),
            job_status=str(row.job_status) if row.job_status is not None else None,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            dagster_run_id=row.dagster_run_id,
            job_id=str(row.job_id) if row.job_id is not None else None,
            request_id=(
                str(row.request_id) if row.request_id is not None else None
            ),
            progress=int(row.progress) if row.progress is not None else None,
            current_stage=row.current_stage,
            error_message=row.error_message,
        )
        for row in rows
    )


_IMPORT_JOB_COLUMNS: Final[str] = (
    "job_id, kind, load_batch_id, parent_job_id, payload, status, progress, "
    "current_stage, source_checksum, error_message, dagster_run_id, created_at, "
    "started_at, finished_at, heartbeat_at"
)

# uuid 배열 바인딩은 ``jobs_repo._LIST_JOBS_BY_IDS_SQL``과 동일하게 jsonb 텍스트
# 배열 → uuid 캐스팅으로 우회한다(driver별 uuid[] 인코딩 차이 회피).
_LIST_JOBS_BY_IDS_SQL: Final[str] = f"""
WITH ids AS (
    SELECT value::uuid AS job_id
    FROM jsonb_array_elements_text(CAST(:job_ids AS jsonb))
)
SELECT {_IMPORT_JOB_COLUMNS}
FROM ops.import_jobs
WHERE job_id IN (SELECT job_id FROM ids)
ORDER BY created_at DESC, job_id DESC
"""


def _row_to_import_job(row: Any) -> OpsImportJob:
    return OpsImportJob(
        job_id=str(row.job_id),
        kind=str(row.kind),
        load_batch_id=str(row.load_batch_id) if row.load_batch_id else None,
        parent_job_id=str(row.parent_job_id) if row.parent_job_id else None,
        payload=_json_dict(row.payload),
        status=str(row.status),
        progress=int(row.progress),
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        dagster_run_id=row.dagster_run_id,
    )


async def list_ops_import_jobs_by_ids(
    session: AsyncSession,
    job_ids: Sequence[str],
) -> tuple[OpsImportJob, ...]:
    """``job_ids``에 해당하는 import job들을 최신순으로 일괄 조회한다.

    빈 입력이면 DB를 치지 않고 빈 tuple. 존재하지 않는 id는 조용히 빠진다 —
    호출자(라우터)가 ``job_id`` 매핑 dict를 만들어 요약에 붙이는 용도.
    """
    unique_ids = sorted({str(job_id) for job_id in job_ids if job_id})
    if not unique_ids:
        return ()
    rows = (
        await session.execute(
            text(_LIST_JOBS_BY_IDS_SQL),
            {"job_ids": json.dumps(unique_ids)},
        )
    ).all()
    return tuple(_row_to_import_job(row) for row in rows)
