"""``krtour.map.infra.dedup_refresh_repo`` — DB 기준 dedup refresh 입력 조회.

Dagster 운영 job이 provider 적재 후 이미 DB에 들어간 ``feature.features``를 다시
읽어 ``core.dedup`` 입력으로 넘길 수 있게 하는 read-only raw SQL repository다.
후보 산출과 큐 upsert는 client orchestration에서 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from krtour.map.dto import Coordinate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DEDUP_REFRESH_DEFAULT_LIMIT",
    "DedupRefreshFeature",
    "DedupRefreshScope",
    "list_dedup_refresh_features",
]

DEDUP_REFRESH_DEFAULT_LIMIT: Final[int] = 5000
"""운영 refresh 1 scope당 기본 feature 상한."""


@dataclass(frozen=True)
class DedupRefreshScope:
    """DB에서 dedup 후보 생성 입력을 읽을 provider/dataset scope."""

    provider: str
    dataset_key: str | None = None
    kinds: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    limit: int = DEDUP_REFRESH_DEFAULT_LIMIT

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata/문서화를 위한 직렬화 가능한 표현."""
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "kinds": list(self.kinds),
            "categories": list(self.categories),
            "limit": self.limit,
        }


@dataclass(frozen=True)
class DedupRefreshFeature:
    """DB row를 ``core.dedup.DedupInput`` Protocol로 감싼 값 객체."""

    feature_id: str
    name: str
    coord: Coordinate | None
    category: str
    provider: str
    dataset_key: str


_LIST_DEDUP_FEATURES_SQL: Final[str] = """
SELECT DISTINCT ON (f.feature_id)
    f.feature_id,
    f.name,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    sr.provider,
    sr.dataset_key
FROM feature.features AS f
JOIN provider_sync.source_links AS sl
  ON sl.feature_id = f.feature_id
 AND sl.is_primary_source
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
WHERE f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.coord IS NOT NULL
  AND sr.provider = :provider
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR sr.dataset_key = CAST(:dataset_key AS text)
  )
  AND (
    CAST(:kinds AS text[]) IS NULL
    OR f.kind = ANY(CAST(:kinds AS text[]))
  )
  AND (
    CAST(:categories AS text[]) IS NULL
    OR f.category = ANY(CAST(:categories AS text[]))
  )
ORDER BY f.feature_id, sr.imported_at DESC NULLS LAST, sr.source_record_key
LIMIT :limit
"""


async def list_dedup_refresh_features(
    session: AsyncSession,
    scope: DedupRefreshScope,
) -> list[DedupRefreshFeature]:
    """provider/dataset scope의 활성 feature를 dedup 입력으로 조회한다."""
    rows = (
        await session.execute(
            text(_LIST_DEDUP_FEATURES_SQL),
            {
                "provider": scope.provider,
                "dataset_key": scope.dataset_key,
                "kinds": _array_or_none(scope.kinds),
                "categories": _array_or_none(scope.categories),
                "limit": scope.limit,
            },
        )
    ).mappings().all()
    return [_row_to_feature(row) for row in rows]


def _array_or_none(values: Sequence[str]) -> list[str] | None:
    return list(values) if values else None


def _row_to_feature(row: Any) -> DedupRefreshFeature:
    lon = row["lon"]
    lat = row["lat"]
    coord = (
        Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
        if lon is not None and lat is not None
        else None
    )
    return DedupRefreshFeature(
        feature_id=str(row["feature_id"]),
        name=str(row["name"]),
        coord=coord,
        category=str(row["category"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
    )
