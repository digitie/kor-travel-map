"""``krtour.map.infra.status_repo`` — 운영 현황 카운트 조회 (read-only).

``krtour-map status`` CLI(ADR-039 §read-only, mutex 없음)와 디버그 UI가 쓰는
가벼운 집계. raw SQL ``text()``(ADR-004), 읽기 전용.

집계 대상:
- ``feature.features`` — 활성/비활성/전체 + kind별.
- ``provider_sync.source_records`` — provider별 row 수.
- ``ops.import_jobs`` — state별.
- ``ops.dedup_review_queue`` — status별.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["StatusCounts", "gather_status_counts"]


@dataclass(frozen=True)
class StatusCounts:
    """운영 현황 카운트 스냅샷 (``gather_status_counts`` 결과)."""

    features_total: int = 0
    features_active: int = 0
    features_inactive: int = 0
    features_by_kind: dict[str, int] = field(default_factory=dict)
    source_records_by_provider: dict[str, int] = field(default_factory=dict)
    import_jobs_by_state: dict[str, int] = field(default_factory=dict)
    dedup_queue_by_status: dict[str, int] = field(default_factory=dict)


_FEATURES_SQL: Final[str] = """
SELECT
    count(*) AS total,
    count(*) FILTER (WHERE deleted_at IS NULL) AS active,
    count(*) FILTER (WHERE deleted_at IS NOT NULL) AS inactive
FROM feature.features
"""

_FEATURES_BY_KIND_SQL: Final[str] = """
SELECT kind, count(*) AS n
FROM feature.features
WHERE deleted_at IS NULL
GROUP BY kind
"""

_SOURCE_RECORDS_SQL: Final[str] = """
SELECT provider, count(*) AS n
FROM provider_sync.source_records
GROUP BY provider
"""

_IMPORT_JOBS_SQL: Final[str] = """
SELECT state, count(*) AS n
FROM ops.import_jobs
GROUP BY state
"""

_DEDUP_QUEUE_SQL: Final[str] = """
SELECT status, count(*) AS n
FROM ops.dedup_review_queue
GROUP BY status
"""


async def gather_status_counts(session: AsyncSession) -> StatusCounts:
    """운영 현황 카운트를 한 번에 집계 (read-only, commit 불필요)."""
    feat = (await session.execute(text(_FEATURES_SQL))).one()
    by_kind = {
        row.kind: int(row.n)
        for row in (await session.execute(text(_FEATURES_BY_KIND_SQL))).all()
    }
    by_provider = {
        row.provider: int(row.n)
        for row in (await session.execute(text(_SOURCE_RECORDS_SQL))).all()
    }
    by_state = {
        row.state: int(row.n)
        for row in (await session.execute(text(_IMPORT_JOBS_SQL))).all()
    }
    by_status = {
        row.status: int(row.n)
        for row in (await session.execute(text(_DEDUP_QUEUE_SQL))).all()
    }
    return StatusCounts(
        features_total=int(feat.total),
        features_active=int(feat.active),
        features_inactive=int(feat.inactive),
        features_by_kind=by_kind,
        source_records_by_provider=by_provider,
        import_jobs_by_state=by_state,
        dedup_queue_by_status=by_status,
    )
