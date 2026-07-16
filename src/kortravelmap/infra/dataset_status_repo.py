"""``kortravelmap.infra.dataset_status_repo`` — dataset 상태 화면 조회 (ADR-064).

admin ``/ops/datasets`` 그룹(T-ADM-C2)이 provider×dataset 그리드/상세를 만들 때
필요한 read-only 보조 조회를 둔다. ``ops_repo``가 실행(작업/이벤트/이슈)의 keyset
cursor 목록을 책임진다면, 본 모듈은 화면 join용 집계/일괄 조회 2종을 둔다:

- ``count_open_integrity_issues_by_dataset`` — provider×dataset별 미해결
  (open/acknowledged) data integrity 이슈 카운트. 그리드 이슈 배지 join용.
- ``list_latest_dataset_executions`` — ``pipeline_repo``의 공용 canonical root
  projection으로 dataset별 최신 실행을 한 번에 반환한다. 그리드 행별 detail
  조회(N+1)를 금지한다.

raw SQL은 본 모듈에 모으고(ADR-004), commit은 호출자 책임.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.infra.pipeline_repo import (
    PipelineExecution,
    list_latest_dataset_pipeline_executions,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DatasetIntegrityIssueCount",
    "DatasetLatestExecution",
    "count_open_integrity_issues_by_dataset",
    "list_latest_dataset_executions",
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
    """provider×dataset×scope의 최신 canonical root와 exact pair 상태."""

    provider: str
    dataset_key: str
    sync_scope: str | None
    execution: PipelineExecution
    operation_member_id: str
    pair_status: str


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


async def list_latest_dataset_executions(
    session: AsyncSession,
) -> tuple[DatasetLatestExecution, ...]:
    """공용 pipeline root projection으로 dataset별 최신 실행을 반환한다."""
    rows = await list_latest_dataset_pipeline_executions(session)
    return tuple(
        DatasetLatestExecution(
            provider=row.provider,
            dataset_key=row.dataset_key,
            sync_scope=row.sync_scope,
            execution=row.execution,
            operation_member_id=row.operation_member_id,
            pair_status=row.pair_status,
        )
        for row in rows
    )
