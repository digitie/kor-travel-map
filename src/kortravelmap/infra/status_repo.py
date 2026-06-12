"""``kortravelmap.infra.status_repo`` — 운영 현황 카운트 조회 (read-only).

``ktmctl status`` CLI(ADR-039 §read-only, mutex 없음)와 디버그 UI가 쓰는
가벼운 집계. raw SQL ``text()``(ADR-004), 읽기 전용.

집계 대상:
- ``feature.features`` — 활성/비활성/전체 + kind별.
- ``provider_sync.source_records`` — provider별 row 수.
- ``ops.import_jobs`` — status별.
- ``ops.dedup_review_queue`` — status별.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "StatusCounts",
    "gather_status_counts",
    "DedupQueueFpStats",
    "dedup_fp_stats",
]


@dataclass(frozen=True)
class StatusCounts:
    """운영 현황 카운트 스냅샷 (``gather_status_counts`` 결과)."""

    features_total: int = 0
    features_active: int = 0
    features_inactive: int = 0
    features_by_kind: dict[str, int] = field(default_factory=dict)
    source_records_by_provider: dict[str, int] = field(default_factory=dict)
    import_jobs_by_status: dict[str, int] = field(default_factory=dict)
    dedup_queue_by_status: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DedupQueueFpStats:
    """dedup 검토 큐의 **운영자 결정** 기반 실 false-positive 통계 (ADR-016 후속).

    `dedup-fp-measurement` 리포트(2026-06-01)의 대표 평가셋 측정을, 실제 운영자
    accept/reject 누적분으로 교체하기 위한 측정 도구. 운영자가 `dedup-merge`로
    병합(merged)하거나 accept한 후보는 **진짜 중복**(confirmed), reject한 후보는
    **false positive**, ignore는 판단 불가(precision 계산 제외).

    - ``resolved`` = confirmed + rejected (판단된 후보).
    - ``precision`` = confirmed / resolved (운영 정밀도). resolved=0이면 None.
    - ``fp_rate`` = rejected / resolved (운영 FP율). resolved=0이면 None.
    """

    resolved: int
    confirmed: int
    rejected: int
    ignored: int
    pending: int
    precision: float | None
    fp_rate: float | None


def dedup_fp_stats(by_status: dict[str, int]) -> DedupQueueFpStats:
    """dedup_review_queue status별 카운트 → 운영자 결정 기반 FP 통계.

    confirmed = merged + accepted, false positive = rejected, ignored/pending은
    precision 계산에서 제외. resolved(confirmed+rejected)=0이면 precision/fp_rate는
    ``None``(아직 검토 완료 후보 없음).
    """
    confirmed = by_status.get("merged", 0) + by_status.get("accepted", 0)
    rejected = by_status.get("rejected", 0)
    resolved = confirmed + rejected
    precision = (confirmed / resolved) if resolved else None
    fp_rate = (rejected / resolved) if resolved else None
    return DedupQueueFpStats(
        resolved=resolved,
        confirmed=confirmed,
        rejected=rejected,
        ignored=by_status.get("ignored", 0),
        pending=by_status.get("pending", 0),
        precision=precision,
        fp_rate=fp_rate,
    )


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
SELECT status, count(*) AS n
FROM ops.import_jobs
GROUP BY status
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
    by_job_status = {
        row.status: int(row.n)
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
        import_jobs_by_status=by_job_status,
        dedup_queue_by_status=by_status,
    )
