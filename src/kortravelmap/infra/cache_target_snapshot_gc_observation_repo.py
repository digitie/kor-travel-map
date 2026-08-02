"""Cache-target snapshot GC의 referenced 보존 추세 관측 저장소."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CacheTargetSnapshotGcObservation",
    "record_cache_target_snapshot_gc_observation",
]

_PRUNE_SQL = """
DELETE FROM ops.poi_cache_target_snapshot_gc_observations
WHERE observed_at < transaction_timestamp() - make_interval(days => :retention_days)
  AND dagster_run_id <> :dagster_run_id
"""

_INSERT_SQL = """
WITH current_clock AS MATERIALIZED (
  SELECT transaction_timestamp() AS observed_at
), baseline AS MATERIALIZED (
  SELECT dagster_run_id, observed_at, referenced_items, referenced_headers
  FROM ops.poi_cache_target_snapshot_gc_observations
  WHERE growth_baseline_eligible
    AND dagster_run_id <> :dagster_run_id
  ORDER BY observation_id DESC
  LIMIT 1
), previous AS MATERIALIZED (
  SELECT dagster_run_id, observed_at, referenced_items, referenced_headers
  FROM ops.poi_cache_target_snapshot_gc_observations
  WHERE dagster_run_id <> :dagster_run_id
  ORDER BY observation_id DESC
  LIMIT 1
)
INSERT INTO ops.poi_cache_target_snapshot_gc_observations (
  dagster_run_id,
  observed_at,
  referenced_items,
  referenced_headers,
  previous_observation_run_id,
  previous_observed_at,
  previous_referenced_items,
  previous_referenced_headers,
  growth_baseline_run_id,
  growth_baseline_observed_at,
  growth_baseline_referenced_items,
  growth_baseline_referenced_headers,
  growth_baseline_eligible,
  growth_min_interval_seconds
)
SELECT :dagster_run_id,
       current_clock.observed_at,
       :referenced_items,
       :referenced_headers,
       previous.dagster_run_id,
       previous.observed_at,
       previous.referenced_items,
       previous.referenced_headers,
       baseline.dagster_run_id,
       baseline.observed_at,
       baseline.referenced_items,
       baseline.referenced_headers,
       (previous.dagster_run_id IS NULL
        OR current_clock.observed_at > previous.observed_at)
       AND (
         baseline.dagster_run_id IS NULL OR (
           current_clock.observed_at > baseline.observed_at
           AND extract(epoch FROM current_clock.observed_at - baseline.observed_at)
               >= :growth_min_interval_seconds
         )
       ),
       :growth_min_interval_seconds
FROM current_clock
LEFT JOIN baseline ON true
LEFT JOIN previous ON true
WHERE NOT EXISTS (
  SELECT 1
  FROM ops.poi_cache_target_snapshot_gc_observations
  WHERE dagster_run_id = :dagster_run_id
)
ON CONFLICT (dagster_run_id) DO NOTHING
"""

_CURRENT_SQL = """
SELECT observation_id,
       dagster_run_id,
       observed_at,
       referenced_items,
       referenced_headers,
       previous_observation_run_id,
       previous_observed_at,
       previous_referenced_items,
       previous_referenced_headers,
       growth_baseline_run_id,
       growth_baseline_observed_at,
       growth_baseline_referenced_items,
       growth_baseline_referenced_headers,
       growth_baseline_eligible,
       growth_min_interval_seconds
FROM ops.poi_cache_target_snapshot_gc_observations
WHERE dagster_run_id = :dagster_run_id
"""


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotGcObservation:
    """현재 run, 직전 acquired 관측과 직전 적격 증가율 baseline."""

    observation_id: int
    dagster_run_id: str
    observed_at: datetime
    referenced_items: int
    referenced_headers: int
    previous_observation_run_id: str | None
    previous_observed_at: datetime | None
    previous_referenced_items: int | None
    previous_referenced_headers: int | None
    growth_baseline_run_id: str | None
    growth_baseline_observed_at: datetime | None
    growth_baseline_referenced_items: int | None
    growth_baseline_referenced_headers: int | None
    growth_baseline_eligible: bool
    growth_min_interval_seconds: int


async def record_cache_target_snapshot_gc_observation(
    session: AsyncSession,
    *,
    dagster_run_id: str,
    referenced_items: int,
    referenced_headers: int,
    retention_days: int,
    growth_min_interval_seconds: int,
) -> CacheTargetSnapshotGcObservation:
    """run별 count, 직전 acquired 관측과 적격 baseline을 멱등 기록한다.

    최소 간격 미달 또는 비전진 DB 시각인 관측은 현재 baseline을 복사하지만 다음
    baseline으로 승격하지 않는다. 따라서 짧은 재실행이 그 뒤의 첫 평가 가능한 증가를
    흡수하지 않는다. 같은 Dagster run retry는 최초 관측·분류를 그대로 반환한다.
    """
    run_id = dagster_run_id.strip()
    if run_id != dagster_run_id or not run_id or len(run_id) > 255:
        raise ValueError("dagster_run_id는 trim된 1~255자 문자열이어야 합니다.")
    if referenced_items < 0 or referenced_headers < 0:
        raise ValueError("referenced count는 0 이상이어야 합니다.")
    if not 1 <= retention_days <= 3_650:
        raise ValueError("retention_days는 1 이상 3650 이하여야 합니다.")
    if not 1 <= growth_min_interval_seconds <= 86_400:
        raise ValueError(
            "growth_min_interval_seconds는 1 이상 86400 이하여야 합니다."
        )

    await session.execute(
        text(_PRUNE_SQL),
        {"retention_days": retention_days, "dagster_run_id": run_id},
    )
    await session.execute(
        text(_INSERT_SQL),
        {
            "dagster_run_id": run_id,
            "referenced_items": referenced_items,
            "referenced_headers": referenced_headers,
            "growth_min_interval_seconds": growth_min_interval_seconds,
        },
    )
    values = (
        await session.execute(text(_CURRENT_SQL), {"dagster_run_id": run_id})
    ).one()._mapping
    return CacheTargetSnapshotGcObservation(
        observation_id=int(values["observation_id"]),
        dagster_run_id=str(values["dagster_run_id"]),
        observed_at=values["observed_at"],
        referenced_items=int(values["referenced_items"]),
        referenced_headers=int(values["referenced_headers"]),
        previous_observation_run_id=(
            str(values["previous_observation_run_id"])
            if values["previous_observation_run_id"] is not None
            else None
        ),
        previous_observed_at=values["previous_observed_at"],
        previous_referenced_items=(
            int(values["previous_referenced_items"])
            if values["previous_referenced_items"] is not None
            else None
        ),
        previous_referenced_headers=(
            int(values["previous_referenced_headers"])
            if values["previous_referenced_headers"] is not None
            else None
        ),
        growth_baseline_run_id=(
            str(values["growth_baseline_run_id"])
            if values["growth_baseline_run_id"] is not None
            else None
        ),
        growth_baseline_observed_at=values["growth_baseline_observed_at"],
        growth_baseline_referenced_items=(
            int(values["growth_baseline_referenced_items"])
            if values["growth_baseline_referenced_items"] is not None
            else None
        ),
        growth_baseline_referenced_headers=(
            int(values["growth_baseline_referenced_headers"])
            if values["growth_baseline_referenced_headers"] is not None
            else None
        ),
        growth_baseline_eligible=bool(values["growth_baseline_eligible"]),
        growth_min_interval_seconds=int(values["growth_min_interval_seconds"]),
    )
