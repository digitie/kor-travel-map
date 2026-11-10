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

from kortravelmap.core.dedup import DedupPoint
from kortravelmap.core.scoring import MasterCandidate
from kortravelmap.dto import Coordinate, EventDetail
from kortravelmap.infra import feature_identity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DEDUP_REFRESH_DEFAULT_LIMIT",
    "DedupRefreshFeature",
    "DedupRefreshScope",
    "list_dedup_refresh_features",
    "list_route_overlap_pairs",
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
    kind: str
    detail: EventDetail | None

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
            dataset_key=self.dataset_key,
        )


_LIST_DEDUP_FEATURES_SQL: Final[str] = """
WITH ranked AS (
  SELECT
    f.feature_id,
    f.name,
    f.kind,
    e.event_kind, e.starts_on, e.ends_on, e.venue_name,
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
  LEFT JOIN feature.feature_events AS e ON e.feature_id = f.feature_id
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
  -- legacy `deleted_at IS NULL AND status = 'active'`의 3축 등가물은 세 축 전부다
  -- (0095 backfill: draft→draft / hidden→suppressed / broken→quarantined).
  -- publication을 빼면 draft·suppressed feature가 dedup 후보로 올라온다.
  WHERE f.lifecycle_state = 'active'
    AND f.publication_state = 'published'
    AND f.quality_state = 'valid'
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
        CAST(:cursor_feature_id AS uuid)
      )
    )
    -- #1468: 반경 blocking 쌍은 큰 쪽(예: MOIS 음식점 12만 건)을 다른 쪽 feature 반경 안만
    -- 읽는다. 저장된 `coord_5179`와 그 부분 GiST 인덱스를 쓴다(ADR-012 — 술어에
    -- ST_Transform 없음).
    AND (
      CAST(:near_ids AS uuid[]) IS NULL
      OR f.feature_id IN (
        SELECT near_r.feature_id
        FROM feature.features AS near_l
        JOIN feature.features AS near_r
          ON x_extension.ST_DWithin(
               near_r.coord_5179, near_l.coord_5179,
               CAST(:near_radius_m AS double precision)
             )
         AND near_r.lifecycle_state = 'active'
         AND near_r.publication_state = 'published'
         AND near_r.quality_state = 'valid'
        WHERE near_l.feature_id = ANY(CAST(:near_ids AS uuid[]))
      )
    )
)
SELECT
    feature_id,
    name,
    kind, event_kind, starts_on, ends_on, venue_name,
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
    *,
    near_feature_ids: Sequence[str] | None = None,
    near_radius_m: float | None = None,
) -> list[DedupRefreshFeature]:
    """provider/dataset scope의 활성 feature를 dedup 입력으로 조회한다.

    ``near_feature_ids``/``near_radius_m``가 함께 주어지면 그 feature 중 하나와
    ``near_radius_m`` 안에 있는 feature만 읽는다(#1468 반경 blocking). ``limit``은 그
    거름 뒤에 걸린다.
    """
    _validate_scope(scope)
    if (near_feature_ids is None) != (near_radius_m is None):
        raise ValueError("near_feature_ids and near_radius_m must be provided together")
    if near_radius_m is not None and not near_radius_m > 0:
        raise ValueError("near_radius_m must be greater than 0")
    if near_feature_ids is not None and not near_feature_ids:
        return []
    # T-VN-32C PR-2 — 운영자가 응답 UUID를 run config cursor에 붙여넣는 경로.
    # T-VN-39: keyset 축이 uuid가 됐으므로 cursor도 uuid 표기여야 한다.
    # canonical uuid인데 해석 miss면 원문 유지 — 기존 "범위 밖 cursor"
    # semantics(적대 리뷰 F3)가 그대로 남는다. 어떤 Feature도 가리키지 않는
    # cursor는 run config가 깨졌다는 뜻이라 `_validate_scope`와 같은 부류의
    # ValueError로 즉시 멈춘다 — 전에는 22P02로 죽었다.
    cursor_feature_id = await feature_identity.canonical_feature_id_for_filter(
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
                "near_ids": list(near_feature_ids) if near_feature_ids is not None else None,
                "near_radius_m": near_radius_m,
            },
        )
    ).mappings().all()
    return [_row_to_feature(row) for row in rows]


_ROUTE_OVERLAP_SQL: Final[str] = """
WITH left_lines AS MATERIALIZED (
  -- 왼쪽은 id·표시값만 모은다. 선 자체는 아래에서 route geometry GiST 인덱스(`&&`)로 찾는다.
  SELECT f.feature_id, f.name, f.category, f.kind,
         x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat
  FROM feature.features AS f
  JOIN provider_sync.source_links AS sl
    ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
  JOIN provider_sync.source_entities AS se
    ON se.source_entity_key = sl.source_entity_key
  JOIN provider_sync.provider_datasets AS pd
    ON pd.provider_dataset_id = se.provider_dataset_id
  WHERE f.lifecycle_state = 'active'
    AND f.publication_state = 'published'
    AND f.quality_state = 'valid'
    AND pd.provider = :left_provider
    AND (CAST(:left_dataset_key AS text) IS NULL
         OR pd.dataset_key = CAST(:left_dataset_key AS text))
    AND (CAST(:left_categories AS text[]) IS NULL
         OR f.category = ANY(CAST(:left_categories AS text[])))
),
right_zones AS MATERIALIZED (
  -- 오른쪽(원장) 선을 미터 버퍼로 감싼다. 버퍼는 geography로 만들어 4326으로 되돌린다 —
  -- 이 식은 술어가 아니라 한 번 만드는 값이다(ADR-012). 아래 `&&`가 인덱스 술어다.
  SELECT f.feature_id, f.name, f.category, f.kind,
         x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
         x_extension.ST_Buffer(
           g.geom::x_extension.geography, CAST(:buffer_m AS double precision)
         )::x_extension.geometry AS zone
  FROM feature.features AS f
  JOIN feature.feature_route_geometries AS g
    ON g.feature_id = f.feature_id AND g.public_ready
  JOIN provider_sync.source_links AS sl
    ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
  JOIN provider_sync.source_entities AS se
    ON se.source_entity_key = sl.source_entity_key
  JOIN provider_sync.provider_datasets AS pd
    ON pd.provider_dataset_id = se.provider_dataset_id
  WHERE f.lifecycle_state = 'active'
    AND f.publication_state = 'published'
    AND f.quality_state = 'valid'
    AND pd.provider = :right_provider
    AND (CAST(:right_dataset_key AS text) IS NULL
         OR pd.dataset_key = CAST(:right_dataset_key AS text))
    AND (CAST(:right_categories AS text[]) IS NULL
         OR f.category = ANY(CAST(:right_categories AS text[])))
),
overlaps AS (
  SELECT l.feature_id AS left_id, l.name AS left_name, l.category AS left_category,
         l.kind AS left_kind, l.lon AS left_lon, l.lat AS left_lat,
         r.feature_id AS right_id, r.name AS right_name, r.category AS right_category,
         r.kind AS right_kind, r.lon AS right_lon, r.lat AS right_lat,
         x_extension.ST_Length(
           x_extension.ST_Intersection(lg.geom, r.zone)::x_extension.geography
         ) / NULLIF(x_extension.ST_Length(lg.geom::x_extension.geography), 0) AS ratio
  FROM right_zones AS r
  JOIN feature.feature_route_geometries AS lg
    ON lg.public_ready
   AND lg.geom OPERATOR(x_extension.&&) r.zone
  JOIN left_lines AS l
    ON l.feature_id = lg.feature_id
  WHERE l.feature_id <> r.feature_id
)
SELECT DISTINCT ON (left_id)
  left_id, left_name, left_category, left_kind, left_lon, left_lat,
  right_id, right_name, right_category, right_kind, right_lon, right_lat,
  LEAST(ratio, 1.0) AS ratio
FROM overlaps
WHERE ratio >= CAST(:min_ratio AS double precision)
ORDER BY left_id, ratio DESC, right_id
LIMIT CAST(:limit AS integer)
"""


async def list_route_overlap_pairs(
    session: AsyncSession,
    left: DedupRefreshScope,
    right: DedupRefreshScope,
    *,
    buffer_m: float,
    min_overlap_ratio: float,
) -> list[tuple[DedupPoint, DedupPoint, float]]:
    """왼쪽 선 길이 중 오른쪽 선 ``buffer_m`` 버퍼 안 비율이 ``min_overlap_ratio`` 이상인 쌍.

    왼쪽 선마다 가장 많이 겹치는 오른쪽 선 하나만 낸다(#1468 — 국립공원 안 산림청 등산로 ↔
    KNPS 탐방로). 반환은 ``(left, right, overlap_ratio)``. ``left.limit``이 쌍 수 상한이다.
    """
    _validate_scope(left)
    _validate_scope(right)
    if not buffer_m > 0:
        raise ValueError("buffer_m must be greater than 0")
    if not 0 < min_overlap_ratio <= 1:
        raise ValueError("min_overlap_ratio must be in (0, 1]")
    rows = (
        await session.execute(
            text(_ROUTE_OVERLAP_SQL),
            {
                "left_provider": left.provider,
                "left_dataset_key": left.dataset_key,
                "left_categories": _array_or_none(left.categories),
                "right_provider": right.provider,
                "right_dataset_key": right.dataset_key,
                "right_categories": _array_or_none(right.categories),
                "buffer_m": buffer_m,
                "min_ratio": min_overlap_ratio,
                "limit": left.limit,
            },
        )
    ).mappings().all()
    return [
        (
            _route_point(row, "left"),
            _route_point(row, "right"),
            float(row["ratio"]),
        )
        for row in rows
    ]


def _route_point(row: Any, side: str) -> DedupPoint:
    lon = row[f"{side}_lon"]
    lat = row[f"{side}_lat"]
    return DedupPoint(
        feature_id=str(row[f"{side}_id"]),
        name=str(row[f"{side}_name"]),
        coord=(
            Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
            if lon is not None and lat is not None
            else None
        ),
        category=str(row[f"{side}_category"]),
        kind=str(row[f"{side}_kind"]),
    )


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
        kind=str(row["kind"]),
        detail=(
            EventDetail(feature_id=str(row["feature_id"]), event_kind=row["event_kind"],
                        starts_on=row["starts_on"], ends_on=row["ends_on"],
                        venue_name=row["venue_name"])
            if row["event_kind"] is not None else None
        ),
    )
