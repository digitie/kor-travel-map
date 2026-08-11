"""``kortravelmap.infra.dataset_status_repo`` — dataset 상태 화면 조회 (ADR-064).

admin ``/ops/datasets`` 그룹(T-ADM-C2)이 canonical dataset ID 그리드/상세를 만들 때
필요한 read-only 보조 조회를 둔다. ``ops_repo``가 실행(작업/이벤트/이슈)의 keyset
cursor 목록을 책임진다면, 본 모듈은 화면 join용 집계/일괄 조회 2종을 둔다:

- ``count_open_integrity_issues_by_dataset`` — canonical dataset별 미해결
  (open/acknowledged) data integrity 이슈 카운트. provider/dataset 표시는 catalog
  projection일 뿐 집계 identity는 ``provider_dataset_id``다.
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
    PipelineDatasetLatestExecution,
    list_dataset_pipeline_execution_snapshots,
    list_dataset_pipeline_execution_snapshots_scoped,
    list_latest_dataset_pipeline_executions,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.pipeline_repo import PipelineExecution

__all__ = [
    "DatasetIntegrityIssueCount",
    "DatasetExecutionSnapshot",
    "DatasetLatestExecution",
    "count_open_integrity_issues_by_dataset",
    "list_dataset_execution_snapshots",
    "list_dataset_execution_snapshots_scoped",
    "list_latest_dataset_executions",
]


@dataclass(frozen=True)
class DatasetIntegrityIssueCount:
    """catalog display projection 1건의 미해결 integrity 이슈 집계.

    위반 원본의 identity는 ``provider_dataset_id`` FK다. 전역/미귀속 위반은
    dataset 화면 집계에 억지로 귀속하지 않는다.
    """

    provider_dataset_id: int
    provider: str
    dataset_key: str
    open_total: int
    by_severity: dict[str, int]


@dataclass(frozen=True)
class DatasetLatestExecution:
    """exact membership triple의 최신 canonical root와 그 member 상태."""

    provider: str
    dataset_key: str
    sync_scope: str
    operation_key: str
    execution: PipelineExecution
    operation_member_id: str
    pair_status: str
    provider_dataset_id: int


@dataclass(frozen=True)
class DatasetExecutionSnapshot:
    """exact membership triple의 최신 종료 실행과 현재 활성 실행."""

    provider: str
    dataset_key: str
    sync_scope: str
    operation_key: str
    latest_terminal: DatasetLatestExecution | None
    active: DatasetLatestExecution | None
    provider_dataset_id: int


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


# open/acknowledged(=아직 사람이 닫지 않은) 이슈만 집계한다 — ``ops_repo``의
# ``get_ops_integrity_issue_counts``(전역 집계)와 같은 "미해결" 기준.
_COUNT_OPEN_ISSUES_SQL: Final[str] = """
WITH open_issues AS (
    SELECT
        violation.provider_dataset_id,
        dataset.provider,
        dataset.dataset_key,
        violation.severity
    FROM ops.data_integrity_violations AS violation
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = violation.provider_dataset_id
    WHERE violation.status IN ('open', 'acknowledged')
      AND (
        CAST(:provider_dataset_id AS bigint) IS NULL
        OR violation.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
      )
),
by_severity AS (
    SELECT provider_dataset_id, provider, dataset_key, severity, count(*) AS n
    FROM open_issues
    GROUP BY provider_dataset_id, provider, dataset_key, severity
)
SELECT
    provider_dataset_id,
    provider,
    dataset_key,
    CAST(sum(n) AS bigint) AS open_total,
    jsonb_object_agg(severity, n) AS by_severity
FROM by_severity
GROUP BY provider_dataset_id, provider, dataset_key
ORDER BY provider_dataset_id
"""


async def count_open_integrity_issues_by_dataset(
    session: AsyncSession,
    *,
    provider_dataset_id: int | None = None,
) -> tuple[DatasetIntegrityIssueCount, ...]:
    """catalog projection별 미해결 integrity 이슈 카운트(+severity 분해)를 반환한다.

    이슈가 전혀 없는 조합은 행을 만들지 않는다 — 그리드 join 시 미매칭 조합은
    0으로 간주하면 된다. 필터도 canonical ``provider_dataset_id``만 받는다.
    provider_dataset_id가 없는 전역 위반은 이 dataset 집계의 대상이 아니다.
    """
    rows = (
        await session.execute(
            text(_COUNT_OPEN_ISSUES_SQL),
            {"provider_dataset_id": provider_dataset_id},
        )
    ).all()
    return tuple(
        DatasetIntegrityIssueCount(
            provider_dataset_id=int(row.provider_dataset_id),
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
            operation_key=row.operation_key,
            execution=row.execution,
            operation_member_id=row.operation_member_id,
            pair_status=row.pair_status,
            provider_dataset_id=row.provider_dataset_id,
        )
        for row in rows
    )


def _dataset_execution(
    row: PipelineDatasetLatestExecution | None,
) -> DatasetLatestExecution | None:
    if row is None:
        return None
    return DatasetLatestExecution(
        provider=row.provider,
        dataset_key=row.dataset_key,
        sync_scope=row.sync_scope,
        operation_key=row.operation_key,
        execution=row.execution,
        operation_member_id=row.operation_member_id,
        pair_status=row.pair_status,
        provider_dataset_id=row.provider_dataset_id,
    )


async def list_dataset_execution_snapshots(
    session: AsyncSession,
) -> tuple[DatasetExecutionSnapshot, ...]:
    """공용 pipeline projection의 종료/활성 실행을 한 DB snapshot으로 반환한다."""
    rows = await list_dataset_pipeline_execution_snapshots(session)
    return tuple(
        DatasetExecutionSnapshot(
            provider=row.provider,
            dataset_key=row.dataset_key,
            sync_scope=row.sync_scope,
            operation_key=row.operation_key,
            latest_terminal=_dataset_execution(row.latest_terminal),
            active=_dataset_execution(row.active),
            provider_dataset_id=row.provider_dataset_id,
        )
        for row in rows
    )


async def list_dataset_execution_snapshots_scoped(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
) -> tuple[DatasetExecutionSnapshot, ...]:
    """단일 (provider, dataset_key)로 좁힌 종료/활성 실행 snapshot.

    ``load_dataset_detail``처럼 한 dataset만 필요한 경로 전용. 전체 파이프라인
    히스토리를 스캔하는 unscoped 버전의 O(roots^2) 비용을 scoped EXISTS 필터로
    피한다. latest_terminal/active는 유휴 scope에서도 반환해야 하므로 recency
    window는 두지 않는다.
    """
    rows = await list_dataset_pipeline_execution_snapshots_scoped(
        session,
        provider_dataset_id=provider_dataset_id,
    )
    return tuple(
        DatasetExecutionSnapshot(
            provider=row.provider,
            dataset_key=row.dataset_key,
            sync_scope=row.sync_scope,
            operation_key=row.operation_key,
            latest_terminal=_dataset_execution(row.latest_terminal),
            active=_dataset_execution(row.active),
            provider_dataset_id=row.provider_dataset_id,
        )
        for row in rows
    )
