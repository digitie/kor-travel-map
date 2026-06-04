"""``krtour.map.infra.feature_repo`` — Feature 적재/조회 raw SQL repository.

``FeatureBundle`` (provider 변환 출력)을 ``feature.features`` / ``provider_sync.
source_records`` / ``provider_sync.source_links`` 3 테이블에 한 transaction으로
upsert하는 **첫 DB write 경로** (ADR-004 raw SQL, ORM은 매핑만).

설계 원칙
---------
- **raw SQL ``text()``만** (ADR-004) — `_SQL` 상수로 모아 EXPLAIN 검증 친화.
- **commit은 호출자 책임** — 본 repo는 ``session.execute``만, transaction 경계는
  ``AsyncKrtourMapClient.load_feature_bundles`` 또는 호출자가 잡는다 (단위 of work).
- **idempotent** — 모든 upsert는 ``ON CONFLICT ... DO UPDATE`` (재적재 안전,
  test-strategy §4.4). source_records는 payload_hash가 PK 구성요소라
  ``DO NOTHING`` (이력 보존, ADR-017).
- **coord_5179는 건드리지 않음** (ADR-012 STORED generated) — ``coord``만 INSERT.
- **ST_Transform을 술어에 쓰지 않음** (ADR-012) — 좌표 INSERT는
  ``x_extension.ST_SetSRID(x_extension.ST_MakePoint(lon,lat),4326)``.
- **PostGIS 함수는 ``x_extension.`` 스키마 한정** (ADR-008) — raw SQL은 DML 실행
  connection의 search_path에 의존하지 않도록 명시 qualify (asyncpg pool 연결마다
  search_path 보장이 어려움 → ``function st_makepoint does not exist`` 회피).

ADR 참조
--------
- ADR-002 — async-only
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL ``text()``
- ADR-012 — ``coord``(4326)만 저장, ``coord_5179``는 generated, ``ST_Transform`` 술어 금지
- ADR-017 — source_record 이력 보존 (DO NOTHING)
- ADR-018 — ``Feature.detail``은 kind에 맞는 모델 (JSONB 직렬화)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.dto import Feature, FeatureBundle, SourceLink, SourceRecord

__all__ = [
    "FeatureLoadResult",
    "FeatureSearchPage",
    "FeatureSearchRow",
    "NearbyFeaturePage",
    "NearbyFeatureRow",
    "upsert_feature",
    "upsert_source_record",
    "upsert_source_link",
    "load_bundle",
    "load_bundles",
    "soft_delete_features_not_in_snapshot",
    "inactivate_features_by_source_entity_ids",
    "get_feature_row",
    "get_feature_rows_by_ids",
    "get_primary_source_detail",
    "find_place_features_without_phone",
    "set_feature_phones",
    "features_in_bbox",
    "search_features",
    "features_nearby_poi_cache_target",
]


# ─── SQL 상수 (EXPLAIN 검증 대상, test-strategy §4.2) ────────────────────────

# coord_5179는 STORED generated (ADR-012) — INSERT 컬럼에서 제외.
_UPSERT_FEATURE_SQL: Final[str] = """
INSERT INTO feature.features (
    feature_id, kind, name, category,
    coord, coord_precision_digits, geom,
    address, legal_dong_code, road_name_code, road_address_management_no,
    admin_dong_code, sido_code, sigungu_code,
    urls, marker_icon, marker_color,
    parent_feature_id, sibling_group_id,
    detail, raw_refs, status,
    created_at, updated_at, deleted_at
) VALUES (
    :feature_id, :kind, :name, :category,
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE x_extension.ST_SetSRID(
             x_extension.ST_MakePoint(CAST(:lon AS double precision),
                          CAST(:lat AS double precision)), 4326) END,
    :coord_precision_digits,
    CASE WHEN CAST(:geom_wkt AS text) IS NULL THEN NULL
         ELSE x_extension.ST_SetSRID(
             x_extension.ST_GeomFromText(CAST(:geom_wkt AS text)), 4326) END,
    CAST(:address AS jsonb), :legal_dong_code, :road_name_code,
    :road_address_management_no, :admin_dong_code, :sido_code, :sigungu_code,
    CAST(:urls AS jsonb), :marker_icon, :marker_color,
    :parent_feature_id, :sibling_group_id,
    CAST(:detail AS jsonb), CAST(:raw_refs AS jsonb), :status,
    :created_at, :updated_at, :deleted_at
)
ON CONFLICT (feature_id) DO UPDATE SET
    kind = EXCLUDED.kind,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    coord = EXCLUDED.coord,
    coord_precision_digits = EXCLUDED.coord_precision_digits,
    geom = EXCLUDED.geom,
    address = EXCLUDED.address,
    legal_dong_code = EXCLUDED.legal_dong_code,
    road_name_code = EXCLUDED.road_name_code,
    road_address_management_no = EXCLUDED.road_address_management_no,
    admin_dong_code = EXCLUDED.admin_dong_code,
    sido_code = EXCLUDED.sido_code,
    sigungu_code = EXCLUDED.sigungu_code,
    urls = EXCLUDED.urls,
    marker_icon = EXCLUDED.marker_icon,
    marker_color = EXCLUDED.marker_color,
    parent_feature_id = EXCLUDED.parent_feature_id,
    sibling_group_id = EXCLUDED.sibling_group_id,
    detail = EXCLUDED.detail,
    raw_refs = EXCLUDED.raw_refs,
    status = CASE
        WHEN EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS fo
            WHERE fo.feature_id = EXCLUDED.feature_id
              AND fo.field_path = 'status'
              AND fo.status = 'active'
              AND fo.prevent_provider_reactivation
        )
        THEN features.status
        ELSE EXCLUDED.status
    END,
    updated_at = EXCLUDED.updated_at,
    deleted_at = CASE
        WHEN EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS fo
            WHERE fo.feature_id = EXCLUDED.feature_id
              AND fo.field_path = 'status'
              AND fo.status = 'active'
              AND fo.prevent_provider_reactivation
        )
        THEN features.deleted_at
        ELSE EXCLUDED.deleted_at
    END
RETURNING (xmax = 0) AS inserted
"""

# source_records는 payload_hash가 UNIQUE 구성요소 → 이력 보존 (ADR-017).
# 같은 source_record_key 재적재는 DO NOTHING (idempotent).
_UPSERT_SOURCE_RECORD_SQL: Final[str] = """
INSERT INTO provider_sync.source_records (
    source_record_key, provider, dataset_key,
    source_entity_type, source_entity_id, source_version,
    raw_name, raw_address, raw_longitude, raw_latitude,
    raw_data, raw_payload_hash, fetched_at, imported_at, expires_at
) VALUES (
    :source_record_key, :provider, :dataset_key,
    :source_entity_type, :source_entity_id, :source_version,
    :raw_name, :raw_address, :raw_longitude, :raw_latitude,
    CAST(:raw_data AS jsonb), :raw_payload_hash, :fetched_at, :imported_at,
    :expires_at
)
ON CONFLICT (source_record_key) DO NOTHING
RETURNING source_record_key
"""

_UPSERT_SOURCE_LINK_SQL: Final[str] = """
INSERT INTO provider_sync.source_links (
    feature_id, source_record_key, source_role,
    match_method, confidence, is_primary_source, created_at
) VALUES (
    :feature_id, :source_record_key, :source_role,
    :match_method, :confidence, :is_primary_source, :created_at
)
ON CONFLICT (feature_id, source_record_key) DO UPDATE SET
    source_role = EXCLUDED.source_role,
    match_method = EXCLUDED.match_method,
    confidence = EXCLUDED.confidence,
    is_primary_source = EXCLUDED.is_primary_source
RETURNING (xmax = 0) AS inserted
"""

_GET_FEATURE_SQL: Final[str] = """
SELECT
    feature_id, kind, name, category,
    x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat,
    coord_precision_digits,
    x_extension.ST_SRID(coord_5179) AS coord_5179_srid,
    address, detail, urls, raw_refs,
    legal_dong_code, sido_code, sigungu_code,
    marker_icon, marker_color, status,
    parent_feature_id, sibling_group_id,
    created_at, updated_at, deleted_at
FROM feature.features
WHERE feature_id = :feature_id
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = """
SELECT
    feature_id, kind, name, category,
    x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat,
    coord_precision_digits,
    x_extension.ST_SRID(coord_5179) AS coord_5179_srid,
    address, detail, urls, raw_refs,
    legal_dong_code, sido_code, sigungu_code,
    marker_icon, marker_color, status,
    parent_feature_id, sibling_group_id,
    created_at, updated_at, deleted_at
FROM feature.features
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
  AND deleted_at IS NULL
"""

# primary source 1건의 on-demand 상세 — source_record raw_data(원본 provider payload)
# + 연결 feature core. Step D(on-demand detail) 등 단건 조회용. ``source_entity_id``로
# 매칭(provider/dataset/entity_type 한정). primary link 1개만(LIMIT 1).
_GET_PRIMARY_SOURCE_DETAIL_SQL: Final[str] = """
SELECT
    f.feature_id, f.kind, f.name, f.category, f.status,
    x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
    f.address, f.detail,
    sr.source_record_key, sr.provider, sr.dataset_key,
    sr.source_entity_type, sr.source_entity_id,
    sr.raw_name, sr.raw_address, sr.raw_data,
    sr.fetched_at, sr.imported_at
FROM provider_sync.source_records AS sr
JOIN provider_sync.source_links AS sl
  ON sl.source_record_key = sr.source_record_key
JOIN feature.features AS f
  ON f.feature_id = sl.feature_id
WHERE sr.provider = :provider
  AND sr.dataset_key = :dataset_key
  AND sr.source_entity_type = :source_entity_type
  AND sr.source_entity_id = :source_entity_id
  AND sl.is_primary_source
LIMIT 1
"""

# bbox 조회 — ADR-012: 입력 bbox는 4326, GIST(coord) 인덱스 사용. deleted_at 제외.
# kinds 필터는 NULL이면 전체 (asyncpg ARRAY 바인딩). 경량 표현(좌표 + 표시 메타).
_FEATURES_IN_BBOX_SQL: Final[str] = """
SELECT
    feature_id, kind, name, category,
    x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat,
    marker_icon, marker_color, status
FROM feature.features
WHERE deleted_at IS NULL
  AND coord IS NOT NULL
  AND coord && x_extension.ST_MakeEnvelope(
        CAST(:min_lon AS double precision), CAST(:min_lat AS double precision),
        CAST(:max_lon AS double precision), CAST(:max_lat AS double precision), 4326)
  AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
  AND (
    CAST(:categories AS text[]) IS NULL
    OR category = ANY(CAST(:categories AS text[]))
  )
ORDER BY feature_id
LIMIT :limit
"""

_FEATURE_SEARCH_CTE_SQL: Final[str] = """
WITH candidates AS (
    SELECT
        feature_id,
        kind,
        name,
        category,
        x_extension.ST_X(coord) AS lon,
        x_extension.ST_Y(coord) AS lat,
        marker_icon,
        marker_color,
        status,
        CASE
            WHEN CAST(:q AS text) IS NULL THEN NULL
            ELSE x_extension.similarity(name, CAST(:q AS text))
        END AS score
    FROM feature.features
    WHERE deleted_at IS NULL
      AND (
        CAST(:q AS text) IS NULL
        OR name % CAST(:q AS text)
      )
      AND (
        CAST(:bbox_enabled AS boolean) IS FALSE
        OR (
          coord IS NOT NULL
          AND coord && x_extension.ST_MakeEnvelope(
            CAST(:min_lon AS double precision),
            CAST(:min_lat AS double precision),
            CAST(:max_lon AS double precision),
            CAST(:max_lat AS double precision),
            4326
          )
        )
      )
      AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR category = ANY(CAST(:categories AS text[]))
      )
)
"""

_FEATURE_SEARCH_BY_SCORE_SQL: Final[str] = (
    _FEATURE_SEARCH_CTE_SQL
    + """
SELECT candidates.*, score::text AS score_cursor
FROM candidates
WHERE (
    CAST(:cursor_score AS text) IS NULL
    OR (-score, feature_id) > (
        -CAST(:cursor_score AS double precision),
        CAST(:cursor_feature_id AS text)
    )
)
ORDER BY score DESC, feature_id ASC
LIMIT :limit_plus_one
"""
)

_FEATURE_SEARCH_BY_ID_SQL: Final[str] = (
    _FEATURE_SEARCH_CTE_SQL
    + """
SELECT *
FROM candidates
WHERE (
    CAST(:cursor_feature_id AS text) IS NULL
    OR feature_id > CAST(:cursor_feature_id AS text)
)
ORDER BY feature_id ASC
LIMIT :limit_plus_one
"""
)

_NEARBY_TARGET_CTE_SQL: Final[str] = """
WITH target AS (
    SELECT target_id, coord_5179,
           COALESCE(CAST(:radius_km AS double precision), radius_km) * 1000.0
             AS radius_m
    FROM ops.poi_cache_targets
    WHERE target_id::text = :target_id
      AND deleted_at IS NULL
      AND coord_5179 IS NOT NULL
),
candidates AS (
    SELECT
        f.feature_id,
        f.kind,
        f.name,
        f.category,
        f.status,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        x_extension.ST_Distance(f.coord_5179, t.coord_5179)::double precision
            AS distance_m,
        ps.provider AS primary_provider,
        ps.dataset_key AS primary_dataset_key,
        f.updated_at AS last_updated_at
    FROM target AS t
    JOIN feature.features AS f
      ON f.deleted_at IS NULL
     AND f.coord IS NOT NULL
     AND f.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(f.coord_5179, t.coord_5179, t.radius_m)
    LEFT JOIN LATERAL (
        SELECT sr.provider, sr.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = sl.source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.is_primary_source
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
      )
      AND (
        CAST(:statuses AS text[]) IS NULL
        OR f.status = ANY(CAST(:statuses AS text[]))
      )
      AND (
        CAST(:providers AS text[]) IS NULL
        OR ps.provider = ANY(CAST(:providers AS text[]))
      )
)
"""

_NEARBY_DISTANCE_SQL: Final[str] = (
    _NEARBY_TARGET_CTE_SQL
    + """
SELECT *
FROM candidates
WHERE (
    CAST(:cursor_distance_m AS double precision) IS NULL
    OR (distance_m, feature_id) > (
        CAST(:cursor_distance_m AS double precision),
        CAST(:cursor_feature_id AS text)
    )
)
ORDER BY distance_m ASC, feature_id ASC
LIMIT :limit_plus_one
"""
)

_NEARBY_NAME_SQL: Final[str] = (
    _NEARBY_TARGET_CTE_SQL
    + """
SELECT *
FROM candidates
WHERE (
    CAST(:cursor_name AS text) IS NULL
    OR (name, feature_id) > (
        CAST(:cursor_name AS text),
        CAST(:cursor_feature_id AS text)
    )
)
ORDER BY name ASC, feature_id ASC
LIMIT :limit_plus_one
"""
)

_NEARBY_UPDATED_SQL: Final[str] = (
    _NEARBY_TARGET_CTE_SQL
    + """
SELECT *
FROM candidates
WHERE (
    CAST(:cursor_last_updated_at AS timestamptz) IS NULL
    OR (last_updated_at, feature_id) < (
        CAST(:cursor_last_updated_at AS timestamptz),
        CAST(:cursor_feature_id AS text)
    )
)
ORDER BY last_updated_at DESC, feature_id DESC
LIMIT :limit_plus_one
"""
)

# snapshot soft-delete — 주어진 (provider, dataset_key, source_entity_type)의
# **primary source**로 적재된 feature 중, snapshot source_entity_id 집합에 없는
# 것을 soft-delete (status='inactive' + deleted_at). 전체 snapshot 적재 후 호출해
# "이번 snapshot에서 사라진" feature를 비활성화한다 (Step A bulk, ADR-017 — place는
# 무기한 유지하되 status만 inactive). 이미 deleted_at IS NOT NULL이면 건너뛴다.
# source_entity_id 매칭은 BRIN/B-tree 인덱스(idx_source_records_provider_dataset_entity)
# 사용. ``:keys`` 빈 배열이면 전체 비활성화(snapshot이 비었음을 의미).
_SOFT_DELETE_NOT_IN_SNAPSHOT_SQL: Final[str] = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.feature_id IN (
    SELECT sl.feature_id
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = sl.source_record_key
    WHERE sl.is_primary_source
      AND sr.provider = :provider
      AND sr.dataset_key = :dataset_key
      AND sr.source_entity_type = :source_entity_type
      AND NOT (sr.source_entity_id = ANY(CAST(:keys AS text[])))
  )
RETURNING f.feature_id
"""


# Step C 폐업/취소 — soft_delete_not_in_snapshot의 inverse. 주어진 source_entity_id
# 집합에 **속하는** primary-source feature를 inactive로 전환(폐업/취소된 인허가).
# ADR-017 — place는 무기한 유지, status만 inactive. 이미 비활성이면 건너뛴다.
# ``:keys`` 빈 배열이면 아무 것도 비활성화하지 않는다(폐업 목록이 비었음).
_INACTIVATE_BY_ENTITY_IDS_SQL: Final[str] = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.feature_id IN (
    SELECT sl.feature_id
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = sl.source_record_key
    WHERE sl.is_primary_source
      AND sr.provider = :provider
      AND sr.dataset_key = :dataset_key
      AND sr.source_entity_type = :source_entity_type
      AND sr.source_entity_id = ANY(CAST(:keys AS text[]))
  )
RETURNING f.feature_id
"""


@dataclass(frozen=True)
class FeatureLoadResult:
    """``load_bundles`` 적재 결과 카운트 (docs/backend-package.md §1.3).

    - ``features_inserted`` / ``features_updated`` — feature upsert 신규/갱신.
    - ``source_records_inserted`` — 신규 source_record (재적재 시 0).
    - ``source_links_inserted`` / ``source_links_updated`` — link upsert.
    - ``bundles_total`` — 입력 bundle 수.
    """

    bundles_total: int = 0
    features_inserted: int = 0
    features_updated: int = 0
    source_records_inserted: int = 0
    source_links_inserted: int = 0
    source_links_updated: int = 0

    def merge(self, other: FeatureLoadResult) -> FeatureLoadResult:
        """두 결과 카운트를 합산 (streaming 배치 적재 누적용)."""
        return FeatureLoadResult(
            bundles_total=self.bundles_total + other.bundles_total,
            features_inserted=self.features_inserted + other.features_inserted,
            features_updated=self.features_updated + other.features_updated,
            source_records_inserted=(
                self.source_records_inserted + other.source_records_inserted
            ),
            source_links_inserted=(
                self.source_links_inserted + other.source_links_inserted
            ),
            source_links_updated=(
                self.source_links_updated + other.source_links_updated
            ),
        )


@dataclass(frozen=True)
class NearbyFeatureRow:
    """외부 POI/cache target 주변 feature summary row."""

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float
    lat: float
    distance_m: float
    primary_provider: str | None
    primary_dataset_key: str | None
    last_updated_at: datetime


@dataclass(frozen=True)
class FeatureSearchRow:
    """사용자 feature 검색 결과 summary row."""

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None
    lat: float | None
    marker_icon: str | None
    marker_color: str | None
    status: str
    score: float | None = None
    score_cursor: str | None = None


@dataclass(frozen=True)
class FeatureSearchPage:
    """사용자 feature 검색 keyset page."""

    items: tuple[FeatureSearchRow, ...]
    next_cursor: str | None
    total_count: int | None = None


@dataclass(frozen=True)
class NearbyFeaturePage:
    """주변 feature keyset page."""

    items: tuple[NearbyFeatureRow, ...]
    next_cursor: str | None


def _feature_params(feature: Feature) -> dict[str, Any]:
    """``Feature`` DTO → ``_UPSERT_FEATURE_SQL`` bind params."""
    coord = feature.coord
    addr = feature.address
    return {
        "feature_id": feature.feature_id,
        "kind": feature.kind.value,
        "name": feature.name,
        "category": feature.category,
        "lon": float(coord.lon) if coord is not None else None,
        "lat": float(coord.lat) if coord is not None else None,
        "coord_precision_digits": feature.coord_precision_digits,
        "geom_wkt": feature.geom,
        "address": addr.model_dump_json(),
        "legal_dong_code": addr.bjd_code,
        "road_name_code": addr.road_name_code,
        "road_address_management_no": addr.road_address_management_no,
        "admin_dong_code": addr.admin_dong_code,
        "sido_code": addr.sido_code,
        "sigungu_code": addr.sigungu_code,
        "urls": feature.urls.model_dump_json(),
        "marker_icon": feature.marker_icon,
        "marker_color": feature.marker_color,
        "parent_feature_id": feature.parent_feature_id,
        "sibling_group_id": feature.sibling_group_id,
        "detail": (
            feature.detail.model_dump_json() if feature.detail is not None else "{}"
        ),
        "raw_refs": _dump_raw_refs(feature),
        "status": feature.status.value,
        "created_at": feature.created_at,
        "updated_at": feature.updated_at,
        "deleted_at": feature.deleted_at,
    }


def _dump_raw_refs(feature: Feature) -> str:
    """``feature.raw_refs`` (list[RawDataRef]) → JSONB array 문자열."""
    import json

    return json.dumps(
        [ref.model_dump(mode="json") for ref in feature.raw_refs],
        ensure_ascii=False,
    )


def _source_record_params(record: SourceRecord) -> dict[str, Any]:
    import json

    return {
        "source_record_key": record.source_record_key,
        "provider": record.provider,
        "dataset_key": record.dataset_key,
        "source_entity_type": record.source_entity_type,
        "source_entity_id": record.source_entity_id,
        "source_version": record.source_version,
        "raw_name": record.raw_name,
        "raw_address": record.raw_address,
        "raw_longitude": record.raw_longitude,
        "raw_latitude": record.raw_latitude,
        "raw_data": json.dumps(record.raw_data, ensure_ascii=False, default=str),
        "raw_payload_hash": record.raw_payload_hash,
        "fetched_at": record.fetched_at,
        "imported_at": record.imported_at,
        "expires_at": record.expires_at,
    }


def _source_link_params(link: SourceLink) -> dict[str, Any]:
    return {
        "feature_id": link.feature_id,
        "source_record_key": link.source_record_key,
        "source_role": link.source_role.value,
        "match_method": link.match_method,
        "confidence": link.confidence,
        "is_primary_source": link.is_primary_source,
        "created_at": link.created_at,
    }


async def upsert_feature(session: AsyncSession, feature: Feature) -> bool:
    """``feature.features`` upsert. 신규 INSERT면 ``True``, 갱신이면 ``False``.

    ``coord_5179``는 STORED generated이라 INSERT/UPDATE 대상에서 제외 (ADR-012).
    """
    result = await session.execute(text(_UPSERT_FEATURE_SQL), _feature_params(feature))
    return bool(result.scalar_one())


async def upsert_source_record(session: AsyncSession, record: SourceRecord) -> bool:
    """``provider_sync.source_records`` insert. 신규면 ``True``, 이미 있으면 ``False``.

    payload_hash가 UNIQUE 구성요소라 동일 key 재적재는 ``DO NOTHING`` (ADR-017
    이력 보존).
    """
    result = await session.execute(
        text(_UPSERT_SOURCE_RECORD_SQL), _source_record_params(record)
    )
    return result.first() is not None


async def upsert_source_link(session: AsyncSession, link: SourceLink) -> bool:
    """``provider_sync.source_links`` upsert. 신규 INSERT면 ``True``, 갱신이면 ``False``."""
    result = await session.execute(
        text(_UPSERT_SOURCE_LINK_SQL), _source_link_params(link)
    )
    return bool(result.scalar_one())


async def load_bundle(session: AsyncSession, bundle: FeatureBundle) -> FeatureLoadResult:
    """``FeatureBundle`` 하나를 적재 (feature → source_record → source_link 순).

    FK 순서: feature와 source_record가 먼저 있어야 source_link INSERT 가능
    (source_links → features / source_records FK). commit은 호출자 책임.
    """
    feature_inserted = await upsert_feature(session, bundle.feature)
    record_inserted = await upsert_source_record(session, bundle.source_record)
    link_inserted = await upsert_source_link(session, bundle.source_link)
    return FeatureLoadResult(
        bundles_total=1,
        features_inserted=int(feature_inserted),
        features_updated=int(not feature_inserted),
        source_records_inserted=int(record_inserted),
        source_links_inserted=int(link_inserted),
        source_links_updated=int(not link_inserted),
    )


async def load_bundles(
    session: AsyncSession, bundles: Iterable[FeatureBundle]
) -> FeatureLoadResult:
    """``FeatureBundle`` 다수를 같은 session(transaction)에서 순차 적재.

    commit은 호출자 책임 (단위 of work — 하나라도 실패하면 호출자가 rollback).
    bulk COPY 최적화(ADR-013)는 후속 — 본 함수는 정확성 우선 순차 upsert.
    """
    total = FeatureLoadResult()
    for bundle in bundles:
        total = total.merge(await load_bundle(session, bundle))
    return total


async def soft_delete_features_not_in_snapshot(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    snapshot_source_entity_ids: set[str],
) -> int:
    """주어진 primary source의 feature 중 snapshot에 없는 것을 soft-delete.

    전체 snapshot 적재 후 호출 — 이번 snapshot에서 사라진(폐업/제외) feature를
    ``status='inactive'`` + ``deleted_at``으로 비활성화한다 (Step A bulk,
    ADR-017 — place는 무기한 유지, status만 inactive). 이미 비활성(deleted_at IS
    NOT NULL)인 feature는 건드리지 않는다. commit은 호출자 책임.

    Parameters
    ----------
    provider, dataset_key, source_entity_type
        대상 primary source 식별자 (예: ``python-mois-api`` /
        ``mois_license_features_bulk`` / ``license_place``).
    snapshot_source_entity_ids
        이번 snapshot에 포함된 ``source_entity_id`` 집합. 비어 있으면 해당
        source의 모든 활성 feature가 비활성화된다.

    Returns
    -------
    int
        soft-delete된 feature 수.
    """
    result = await session.execute(
        text(_SOFT_DELETE_NOT_IN_SNAPSHOT_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "keys": sorted(snapshot_source_entity_ids),
        },
    )
    return len(result.fetchall())


async def inactivate_features_by_source_entity_ids(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_ids: set[str],
) -> int:
    """주어진 ``source_entity_id`` 집합에 **속하는** primary-source feature를 비활성화.

    Step C 폐업/취소 — provider가 ``closed``/``cancelled``로 통지한 인허가에 대응하는
    feature를 ``status='inactive'`` + ``deleted_at``으로 전환한다 (ADR-017 — place는
    무기한 유지, status만 inactive). ``soft_delete_features_not_in_snapshot``의 inverse
    (snapshot 부재분이 아니라 명시 폐업분). 이미 비활성인 feature·집합 밖 feature는
    건드리지 않는다. 빈 집합이면 no-op(0). commit은 호출자 책임.

    Parameters
    ----------
    provider, dataset_key, source_entity_type
        feature가 적재된 **primary source** 식별자 (예: ``python-mois-api`` /
        ``mois_license_features_bulk`` / ``license_place``). 폐업 dataset이 아니라
        feature가 실제 사는 dataset을 가리킨다.
    source_entity_ids
        폐업/취소된 ``source_entity_id`` 집합. 비어 있으면 no-op.

    Returns
    -------
    int
        inactive로 전환된 feature 수.
    """
    if not source_entity_ids:
        return 0
    result = await session.execute(
        text(_INACTIVATE_BY_ENTITY_IDS_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "keys": sorted(source_entity_ids),
        },
    )
    return len(result.fetchall())


# JSONB 컬럼 — raw ``text()`` 쿼리는 driver에 따라 str(asyncpg)로 돌려줄 수 있어
# (typed 컬럼이 없으면 SQLAlchemy JSON 디시리얼라이저 미작동) 명시적으로 파싱한다.
_JSONB_COLUMNS: Final[tuple[str, ...]] = ("address", "detail", "urls", "raw_refs")


async def get_feature_row(
    session: AsyncSession, feature_id: str
) -> dict[str, Any] | None:
    """``feature.features`` 단건 조회 (raw row dict). 없으면 ``None``.

    좌표는 ``lon``/``lat`` (4326)으로 분해해서 반환. ``coord_5179_srid``로
    generated column이 5179로 채워졌는지 확인 가능 (ADR-012). JSONB 컬럼
    (``address``/``detail``/``urls``/``raw_refs``)은 dict/list로 디시리얼라이즈해서
    반환 — driver(asyncpg)가 str로 돌려줘도 일관성 보장. DTO 매핑은 상위(client)
    책임 — 본 repo는 raw row만.
    """
    import json

    result = await session.execute(
        text(_GET_FEATURE_SQL), {"feature_id": feature_id}
    )
    row = result.mappings().first()
    if row is None:
        return None
    data = dict(row)
    for col in _JSONB_COLUMNS:
        value = data.get(col)
        if isinstance(value, str):
            data[col] = json.loads(value)
    return data


def _deserialize_feature_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    for col in _JSONB_COLUMNS:
        value = data.get(col)
        if isinstance(value, str):
            data[col] = json.loads(value)
    return data


async def get_feature_rows_by_ids(
    session: AsyncSession, feature_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """여러 feature 상세 row를 한 번에 조회한다.

    ``feature_ids`` 순서는 반환 dict에서 보장하지 않는다. 호출자는 입력 순서와
    key 존재 여부를 비교해 missing 목록을 만든다. public/TripMate batch 응답은
    soft-deleted feature를 missing으로 취급하므로 ``deleted_at IS NULL``만 반환한다.
    """
    normalized = _normalized_filter(feature_ids)
    if normalized is None:
        return {}
    result = await session.execute(
        text(_GET_FEATURES_BY_IDS_SQL), {"feature_ids": normalized}
    )
    rows = result.mappings().all()
    return {
        str(row["feature_id"]): _deserialize_feature_row(row)
        for row in rows
    }


async def get_primary_source_detail(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
) -> dict[str, Any] | None:
    """primary source 1건의 on-demand 상세 (feature core + source_record raw_data).

    ``source_entity_id``(provider/dataset/entity_type 한정)로 primary link 1건을 찾아
    원본 provider payload(``raw_data``) + 연결 feature의 핵심 필드를 묶어 반환한다.
    Step D(on-demand detail) 등 단건 조회용 — **읽기 전용**(적재 없음). 없으면
    ``None``. JSONB(``address``/``detail``/``raw_data``)는 dict로 디시리얼라이즈.
    """
    import json

    result = await session.execute(
        text(_GET_PRIMARY_SOURCE_DETAIL_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
        },
    )
    row = result.mappings().first()
    if row is None:
        return None
    data = dict(row)
    for col in ("address", "detail", "raw_data"):
        value = data.get(col)
        if isinstance(value, str):
            data[col] = json.loads(value)
    return data


_FIND_PLACE_NO_PHONE_SQL: Final[str] = """
SELECT f.feature_id, f.name, f.address, sr.source_entity_id
FROM feature.features f
JOIN provider_sync.source_links sl
  ON sl.feature_id = f.feature_id AND sl.is_primary_source
JOIN provider_sync.source_records sr
  ON sr.source_record_key = sl.source_record_key
WHERE f.deleted_at IS NULL
  AND f.kind = 'place'
  AND sr.provider = :provider
  AND sr.dataset_key = :dataset_key
  AND sr.source_entity_type = :source_entity_type
  AND jsonb_array_length(COALESCE(f.detail -> 'phones', '[]'::jsonb)) = 0
ORDER BY f.feature_id
LIMIT :limit
"""

_SET_FEATURE_PHONES_SQL: Final[str] = """
UPDATE feature.features
SET detail = jsonb_set(detail, '{phones}', CAST(:phones AS jsonb)),
    updated_at = now()
WHERE feature_id = :feature_id
RETURNING feature_id
"""


async def find_place_features_without_phone(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """전화번호 없는 place feature 후보 list (phone enrichment 대상, 읽기 전용).

    primary source가 ``(provider, dataset_key, source_entity_type)``인 place 중
    ``detail.phones``가 빈 배열인 feature를 반환한다(`feature_id`/`name`/`address`/
    `source_entity_id`). 외부 phone lookup(kakao/naver/google)은 호출자 책임(ADR-006).
    """
    import json

    rows = (
        await session.execute(
            text(_FIND_PLACE_NO_PHONE_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "limit": limit,
            },
        )
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        addr = data.get("address")
        if isinstance(addr, str):
            data["address"] = json.loads(addr)
        out.append(data)
    return out


async def set_feature_phones(
    session: AsyncSession, feature_id: str, phones: list[str]
) -> bool:
    """feature의 ``detail.phones`` 배열을 통째로 교체. 갱신되면 ``True``.

    phone enrichment가 정규화·dedup·max3을 적용한 최종 배열을 넘긴다. commit은
    호출자 책임.
    """
    import json

    result = await session.execute(
        text(_SET_FEATURE_PHONES_SQL),
        {"feature_id": feature_id, "phones": json.dumps(phones)},
    )
    return result.first() is not None


async def features_in_bbox(
    session: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    kinds: list[str] | None = None,
    categories: Sequence[str] | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """bbox 안의 feature 경량 표현 list (지도/목록용). 좌표는 ``lon``/``lat`` (4326).

    ADR-012 — 입력 bbox는 4326, ``coord``의 GIST 인덱스(``idx_features_coord_gist``)를
    사용하는 ``&&`` 연산. ``deleted_at IS NULL`` + ``coord IS NOT NULL``만. ``kinds``가
    ``None``이면 전체 kind. DTO 매핑은 상위(client) 책임 — 본 repo는 raw row만.
    """
    rows = (
        await session.execute(
            text(_FEATURES_IN_BBOX_SQL),
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "kinds": kinds,
                "categories": _normalized_filter(categories),
                "limit": limit,
            },
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def _search_cursor_payload(cursor: str | None, *, q_enabled: bool) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid feature search cursor") from exc
    if not isinstance(payload, dict) or bool(payload.get("q_enabled")) != q_enabled:
        raise ValueError("invalid feature search cursor")
    feature_id = payload.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid feature search cursor")
    return payload


def _search_cursor_params(cursor: str | None, *, q_enabled: bool) -> dict[str, Any]:
    payload = _search_cursor_payload(cursor, q_enabled=q_enabled)
    params: dict[str, Any] = {
        "cursor_score": None,
        "cursor_feature_id": None,
    }
    if not payload:
        return params
    params["cursor_feature_id"] = payload["feature_id"]
    if q_enabled:
        try:
            score = str(payload["score"])
            float(score)
            params["cursor_score"] = score
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid feature search cursor") from exc
    return params


def _encode_search_cursor(item: FeatureSearchRow, *, q_enabled: bool) -> str:
    payload: dict[str, Any] = {
        "q_enabled": q_enabled,
        "feature_id": item.feature_id,
    }
    if q_enabled:
        payload["score"] = (
            item.score_cursor
            if item.score_cursor is not None
            else str(item.score)
        )
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _search_row(row: Any) -> FeatureSearchRow:
    lon = row["lon"]
    lat = row["lat"]
    score = row["score"]
    score_cursor = row.get("score_cursor")
    return FeatureSearchRow(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        status=str(row["status"]),
        score=float(score) if score is not None else None,
        score_cursor=str(score_cursor) if score_cursor is not None else None,
    )


async def search_features(
    session: AsyncSession,
    *,
    q: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> FeatureSearchPage:
    """사용자 feature 검색.

    ``q`` 또는 ``bbox`` 중 하나는 필수다. ``q``는 pg_trgm ``%`` 연산자를 사용하고,
    threshold는 현재 transaction에만 ``SET LOCAL``로 적용한다(ADR-004/성능 가이드).
    bbox 술어는 stored ``coord`` 컬럼과 ``ST_MakeEnvelope``만 사용한다.
    """
    normalized_q = q.strip() if q is not None else None
    if normalized_q == "":
        normalized_q = None
    if normalized_q is None and bbox is None:
        raise ValueError("q 또는 bbox 중 하나는 필요합니다")
    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    min_lon: float | None
    min_lat: float | None
    max_lon: float | None
    max_lat: float | None
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        if min_lon > max_lon or min_lat > max_lat:
            raise ValueError("invalid bbox")
    else:
        min_lon = min_lat = max_lon = max_lat = None

    q_enabled = normalized_q is not None
    if q_enabled:
        await session.execute(
            text("SET LOCAL pg_trgm.similarity_threshold = 0.2")
        )
    effective_limit = min(limit, 200)
    rows = (
        await session.execute(
            text(_FEATURE_SEARCH_BY_SCORE_SQL if q_enabled else _FEATURE_SEARCH_BY_ID_SQL),
            {
                "q": normalized_q,
                "bbox_enabled": bbox is not None,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "kinds": _normalized_filter(kinds),
                "categories": _normalized_filter(categories),
                "limit_plus_one": effective_limit + 1,
                **_search_cursor_params(cursor, q_enabled=q_enabled),
            },
        )
    ).mappings().all()
    items = tuple(_search_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_search_cursor(items[-1], q_enabled=q_enabled)
        if len(rows) > effective_limit and items
        else None
    )
    return FeatureSearchPage(items=items, next_cursor=next_cursor)


_NEARBY_SQL_BY_SORT: Final[dict[str, str]] = {
    "distance": _NEARBY_DISTANCE_SQL,
    "name": _NEARBY_NAME_SQL,
    "last_updated_at": _NEARBY_UPDATED_SQL,
}


def _nearby_cursor_payload(cursor: str | None, *, sort: str) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid nearby cursor") from exc
    if not isinstance(payload, dict) or payload.get("sort") != sort:
        raise ValueError("invalid nearby cursor")
    feature_id = payload.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid nearby cursor")
    return payload


def _nearby_cursor_params(cursor: str | None, *, sort: str) -> dict[str, Any]:
    payload = _nearby_cursor_payload(cursor, sort=sort)
    params: dict[str, Any] = {
        "cursor_distance_m": None,
        "cursor_name": None,
        "cursor_last_updated_at": None,
        "cursor_feature_id": None,
    }
    if not payload:
        return params

    params["cursor_feature_id"] = payload["feature_id"]
    if sort == "distance":
        try:
            params["cursor_distance_m"] = float(payload["distance_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid nearby cursor") from exc
    elif sort == "name":
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("invalid nearby cursor")
        params["cursor_name"] = name
    elif sort == "last_updated_at":
        try:
            params["cursor_last_updated_at"] = datetime.fromisoformat(
                str(payload["last_updated_at"])
            )
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid nearby cursor") from exc
    return params


def _encode_nearby_cursor(item: NearbyFeatureRow, *, sort: str) -> str:
    payload: dict[str, Any] = {
        "sort": sort,
        "feature_id": item.feature_id,
    }
    if sort == "distance":
        payload["distance_m"] = item.distance_m
    elif sort == "name":
        payload["name"] = item.name
    elif sort == "last_updated_at":
        payload["last_updated_at"] = item.last_updated_at.isoformat()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _nearby_row(row: Any) -> NearbyFeatureRow:
    return NearbyFeatureRow(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        status=str(row["status"]),
        lon=float(row["lon"]),
        lat=float(row["lat"]),
        distance_m=float(row["distance_m"]),
        primary_provider=row["primary_provider"],
        primary_dataset_key=row["primary_dataset_key"],
        last_updated_at=row["last_updated_at"],
    )


def _normalized_filter(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = [str(value) for value in values if str(value)]
    return normalized or None


async def features_nearby_poi_cache_target(
    session: AsyncSession,
    *,
    target_id: str,
    radius_km: float | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    statuses: Sequence[str] | None = ("active",),
    providers: Sequence[str] | None = None,
    sort: str = "distance",
    limit: int = 100,
    cursor: str | None = None,
) -> NearbyFeaturePage:
    """POI/cache target 주변 feature summary를 keyset cursor로 조회한다.

    ADR-012: 반경 술어는 target과 feature의 STORED ``coord_5179`` 컬럼에 직접
    적용한다. 입력 좌표 변환이나 ``ST_Transform``은 WHERE 술어에 두지 않는다.
    """
    if sort not in _NEARBY_SQL_BY_SORT:
        raise ValueError("sort must be one of distance, name, last_updated_at")
    if radius_km is not None and radius_km <= 0:
        raise ValueError("radius_km must be greater than 0")
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    effective_limit = min(limit, 500)
    rows = (
        await session.execute(
            text(_NEARBY_SQL_BY_SORT[sort]),
            {
                "target_id": target_id,
                "radius_km": radius_km,
                "kinds": _normalized_filter(kinds),
                "categories": _normalized_filter(categories),
                "statuses": _normalized_filter(statuses),
                "providers": _normalized_filter(providers),
                "limit_plus_one": effective_limit + 1,
                **_nearby_cursor_params(cursor, sort=sort),
            },
        )
    ).mappings().all()
    items = tuple(_nearby_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_nearby_cursor(items[-1], sort=sort)
        if len(rows) > effective_limit and items
        else None
    )
    return NearbyFeaturePage(items=items, next_cursor=next_cursor)
