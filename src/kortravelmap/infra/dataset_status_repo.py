"""``kortravelmap.infra.dataset_status_repo`` — dataset 상태 화면 조회 (ADR-064).

admin ``/ops/datasets`` 그룹(T-ADM-C2)이 provider×dataset 그리드/상세를 만들 때
필요한 read-only 보조 조회를 둔다. ``ops_repo``가 실행(작업/이벤트/이슈)의 keyset
cursor 목록을 책임진다면, 본 모듈은 화면 join용 집계/일괄 조회 2종을 둔다:

- ``count_open_integrity_issues_by_dataset`` — provider×dataset별 미해결
  (open/acknowledged) data integrity 이슈 카운트. 그리드 이슈 배지 join용.
- ``list_ops_import_jobs_by_ids`` — update request에 연결된 import job들을
  타임스탬프 포함 ``OpsImportJob``으로 일괄 조회(상세의 최근 실행 요약용).

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

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DatasetIntegrityIssueCount",
    "count_open_integrity_issues_by_dataset",
    "list_ops_import_jobs_by_ids",
]


@dataclass(frozen=True)
class DatasetIntegrityIssueCount:
    """provider×dataset 1조합의 미해결 integrity 이슈 집계.

    ``dataset_key``가 ``None``이면 provider에만 귀속된 이슈 묶음이다(라우터가
    dataset 행에 join할 때는 exact key 매칭만 쓰고, provider-level 묶음은 상세
    화면 판단에 맡긴다).
    """

    provider: str
    dataset_key: str | None
    open_total: int
    by_severity: dict[str, int]


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
    0으로 간주하면 된다. ``provider``/``dataset_key``로 좁힐 수 있다(상세 화면).
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


_IMPORT_JOB_COLUMNS: Final[str] = (
    "job_id, kind, load_batch_id, parent_job_id, payload, status, progress, "
    "current_stage, source_checksum, error_message, created_at, started_at, "
    "finished_at, heartbeat_at"
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
