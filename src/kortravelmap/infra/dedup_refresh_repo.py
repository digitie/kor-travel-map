"""``kortravelmap.infra.dedup_refresh_repo`` — DB 기준 dedup refresh 입력 조회.

Dagster 운영 job이 provider 적재 후 이미 DB에 들어간 ``feature.features``를 다시
읽어 ``core.dedup`` 입력으로 넘길 수 있게 하는 read-only raw SQL repository다.
후보 산출과 큐 upsert는 client orchestration에서 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.scoring import MasterCandidate
from kortravelmap.dto import Coordinate
from kortravelmap.infra import feature_identity

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
    cursor_updated_at: datetime | None = None
    cursor_feature_id: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata/문서화를 위한 직렬화 가능한 표현."""
        metadata: dict[str, object] = {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "kinds": list(self.kinds),
            "categories": list(self.categories),
            "limit": self.limit,
        }
        if self.cursor_updated_at is not None:
            metadata["cursor_updated_at"] = self.cursor_updated_at.isoformat()
        if self.cursor_feature_id is not None:
            metadata["cursor_feature_id"] = self.cursor_feature_id
        return metadata


@dataclass(frozen=True)
class DedupRefreshFeature:
    """DB row를 ``core.dedup.DedupInput`` Protocol로 감싼 값 객체."""

    feature_id: str
    name: str
    coord: Coordinate | None
    coord_precision_digits: int | None
    category: str
    provider: str
    dataset_key: str
    updated_at: datetime

    @property
    def has_coord(self) -> bool:
        """ADR-016 master 선정 입력으로 쓰는 좌표 보유 신호."""
        return self.coord is not None

    def as_master_candidate(self) -> MasterCandidate:
        """``core.scoring.select_master``에 넘길 수 있는 master 선정 입력."""
        return MasterCandidate(
            feature_id=self.feature_id,
            has_coord=self.has_coord,
            updated_at=self.updated_at,
            provider=self.provider,
        )


_LIST_DEDUP_FEATURES_SQL: Final[str] = """
WITH ranked AS (
  SELECT
    f.feature_id,
    f.name,
    f.category,
    f.updated_at,
    f.coord_precision_digits,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    pd.provider,
    pd.dataset_key,
    row_number() OVER (
      PARTITION BY f.feature_id
      ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
    ) AS rn
  FROM feature.features AS f
  JOIN provider_sync.source_links AS sl
    ON sl.feature_id = f.feature_id
   AND sl.source_role = 'primary'
  JOIN provider_sync.source_entities AS se
    ON se.source_entity_key = sl.source_entity_key
  JOIN provider_sync.provider_datasets AS pd
    ON pd.provider_dataset_id = se.provider_dataset_id
  -- 정렬축(``sr.imported_at``)은 **현재** record의 것이다 — head를 거쳐 도달한다.
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = se.source_entity_key
  JOIN provider_sync.source_records AS sr
    ON sr.source_record_key = head.current_source_record_key
  WHERE f.deleted_at IS NULL
    AND f.status = 'active'
    AND f.coord IS NOT NULL
    AND pd.provider = :provider
    AND (
      CAST(:dataset_key AS text) IS NULL
      OR pd.dataset_key = CAST(:dataset_key AS text)
    )
    AND (
      CAST(:kinds AS text[]) IS NULL
      OR f.kind = ANY(CAST(:kinds AS text[]))
    )
    AND (
      CAST(:categories AS text[]) IS NULL
      OR f.category = ANY(CAST(:categories AS text[]))
    )
    AND (
      CAST(:cursor_updated_at AS timestamptz) IS NULL
      OR (f.updated_at, f.feature_id) < (
        CAST(:cursor_updated_at AS timestamptz),
        CAST(:cursor_feature_id AS text)
      )
    )
)
SELECT
    feature_id,
    name,
    category,
    updated_at,
    coord_precision_digits,
    lon,
    lat,
    provider,
    dataset_key
FROM ranked
WHERE rn = 1
ORDER BY updated_at DESC, feature_id DESC
LIMIT CAST(:limit AS integer)
"""


async def list_dedup_refresh_features(
    session: AsyncSession,
    scope: DedupRefreshScope,
) -> list[DedupRefreshFeature]:
    """provider/dataset scope의 활성 feature를 dedup 입력으로 조회한다."""
    _validate_scope(scope)
    # T-VN-32C PR-2 — 운영자가 응답 UUID를 run config cursor에 붙여넣는 경로:
    # keyset은 legacy text 축이므로 UUID 표기는 legacy 키로 정규화한다
    # (miss는 원문 유지 — 기존 "범위 밖 cursor" semantics, 적대 리뷰 F3).
    cursor_feature_id = await feature_identity.legacy_id_for_filter(
        session, scope.cursor_feature_id
    )
    rows = (
        await session.execute(
            text(_LIST_DEDUP_FEATURES_SQL),
            {
                "provider": scope.provider,
                "dataset_key": scope.dataset_key,
                "kinds": _array_or_none(scope.kinds),
                "categories": _array_or_none(scope.categories),
                "limit": scope.limit,
                "cursor_updated_at": scope.cursor_updated_at,
                "cursor_feature_id": cursor_feature_id,
            },
        )
    ).mappings().all()
    return [_row_to_feature(row) for row in rows]


def _validate_scope(scope: DedupRefreshScope) -> None:
    if scope.limit <= 0:
        raise ValueError("dedup refresh scope.limit must be greater than 0")
    if (scope.cursor_updated_at is None) != (scope.cursor_feature_id is None):
        raise ValueError(
            "cursor_updated_at and cursor_feature_id must be provided together"
        )


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
        coord_precision_digits=(
            int(row["coord_precision_digits"])
            if row["coord_precision_digits"] is not None
            else None
        ),
        category=str(row["category"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        updated_at=row["updated_at"],
    )
