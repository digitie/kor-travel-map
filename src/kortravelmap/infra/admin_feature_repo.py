"""``admin_feature_repo`` — admin feature review/deactivate/dedup SQL.

``/admin/features``와 ``/admin/dedup-review``가 쓰는 운영자용 read/write 쿼리다.
ORM 모델에는 비즈니스 로직을 두지 않고, 본 모듈의 raw SQL로 처리한다(ADR-004).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, NoReturn

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra.feature_identity import (
    candidate_feature_uuid,
    verify_feature_uuid,
)
from kortravelmap.infra.feature_projection import (
    TYPED_FEATURE_DETAIL_COLUMNS_SQL,
    typed_feature_detail_joins_sql,
)
from kortravelmap.infra.feature_subtype import subtype_params, write_subtype
from kortravelmap.infra.feature_update_active_repo import _driver_constraint_identity
from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeNotFoundError,
    MergeOutcome,
    apply_feature_merge,
    merge_from_review,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "AdminFeaturePage",
    "AdminFeatureRow",
    "AdminFeatureDetail",
    "AdminFeatureDetailFeature",
    "AdminFeatureDetailFile",
    "AdminFeatureDetailIssue",
    "AdminFeatureDetailOverride",
    "AdminFeatureDetailSource",
    "AdminFeatureStateTransitionAudit",
    "AdminFeatureStateTransitionAuditPage",
    "AdminFeatureStateConflict",
    "AdminFeatureStateNotFound",
    "AdminFeatureStatePreconditionFailed",
    "AdminFeatureStateValidationError",
    "DedupReviewPage",
    "DedupReviewRow",
    "DedupReviewDetail",
    "DedupFeatureSummary",
    "EnrichmentReviewPage",
    "EnrichmentReviewRow",
    "EnrichmentReviewDetail",
    "ReviewFeatureDetail",
    "ReviewSourceDetail",
    "AdminFeatureStateTransition",
    "FeatureOverride",
    "FeatureFieldOverrideCommand",
    "FeatureFieldOverrideNotFound",
    "FeatureFieldOverridePreconditionFailed",
    "FeatureFieldOverrideValidationError",
    "transition_admin_feature_state",
    "reactivate_admin_feature_state",
    "author_admin_feature_field_overrides",
    "revoke_admin_feature_field_overrides",
    "create_admin_feature_with_field_overrides",
    "patch_admin_feature_with_field_overrides",
    "get_admin_feature_detail",
    "list_admin_feature_state_transitions",
    "admin_feature_card_target_exists",
    "get_feature_row_revision",
    "get_dedup_review_detail",
    "get_enrichment_review_detail",
    "admin_features_in_bbox",
    "cluster_admin_features_in_bbox",
    "list_admin_features",
    "list_dedup_reviews",
    "list_enrichment_reviews",
    "merge_dedup_review",
    "set_dedup_review_decision",
]

AdminFeatureSort = Literal[
    "name",
    "updated_at",
    "created_at",
    "kind",
    "provider",
    "issue_count",
]
SortOrder = Literal["asc", "desc"]
DedupDecision = Literal["accepted", "rejected", "ignored"]


@dataclass(frozen=True)
class AdminFeatureRow:
    """``GET /admin/features`` item.

    ``feature_uuid``는 T-VN-32B UUID 정본 병행 노출(additive).
    """

    feature_id: str
    kind: str
    name: str
    category: str
    lifecycle_state: str
    publication_state: str
    quality_state: str
    lon: float | None
    lat: float | None
    address_label: str
    primary_provider: str | None
    primary_dataset_key: str | None
    issue_count: int
    issues: tuple[dict[str, Any], ...]
    created_at: datetime
    updated_at: datetime
    feature_uuid: str | None = None


@dataclass(frozen=True)
class AdminFeaturePage:
    """Admin feature keyset page."""

    items: tuple[AdminFeatureRow, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class AdminFeatureDetailFeature:
    """Admin feature 상세의 feature core snapshot.

    ``feature_uuid``는 T-VN-32B UUID 정본 병행 노출(additive).
    """

    feature_id: str
    kind: str
    name: str
    category: str
    lifecycle_state: str
    publication_state: str
    quality_state: str
    lon: float | None
    lat: float | None
    coord_precision_digits: int | None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    raw_refs: list[dict[str, Any]]
    legal_dong_code: str | None
    road_name_code: str | None
    road_address_management_no: str | None
    admin_dong_code: str | None
    sido_code: str | None
    sigungu_code: str | None
    marker_icon: str | None
    marker_color: str | None
    parent_feature_id: str | None
    sibling_group_id: str | None
    row_revision: int
    created_at: datetime
    updated_at: datetime
    area_square_meters: float | None = None
    feature_uuid: str | None = None


@dataclass(frozen=True)
class AdminFeatureDetailSource:
    """Feature에 연결된 현재 SourceEntity head + SourceLink."""

    source_entity_key: str
    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    source_role: str
    match_method: str
    confidence: int
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: datetime
    imported_at: datetime
    observed_at: datetime
    expires_at: datetime | None
    linked_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetailIssue:
    """Feature 상세 issue row."""

    issue_id: str
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True)
class AdminFeatureDetailOverride:
    """Feature 상세 override row."""

    override_id: str
    source_record_key: str | None
    field_path: str
    source_value: Any
    override_value: Any
    prevent_provider_reactivation: bool
    status: str
    reason: str | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetailFile:
    """Feature file metadata row.

    ``feature.feature_files``는 아직 모든 DB head에 존재하지 않는다. 상세 API는 테이블이
    있으면 이 모델로 반환하고, 없으면 빈 tuple을 반환한다.
    """

    file_id: str
    file_type: str
    storage_backend: str
    bucket: str
    object_key: str
    source_url: str | None
    public_url: str | None
    content_type: str | None
    byte_size: int | None
    checksum_sha256: str | None
    width: int | None
    height: int | None
    role: str
    display_order: int
    alt_text: str | None
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetail:
    """Admin feature 상세 aggregate."""

    feature: AdminFeatureDetailFeature
    sources: tuple[AdminFeatureDetailSource, ...]
    issues: tuple[AdminFeatureDetailIssue, ...]
    overrides: tuple[AdminFeatureDetailOverride, ...]
    files: tuple[AdminFeatureDetailFile, ...]
    state_transitions: tuple[AdminFeatureStateTransitionAudit, ...]


@dataclass(frozen=True)
class FeatureOverride:
    """생성/갱신된 feature override summary."""

    override_id: str
    feature_id: str
    field_path: str
    override_value: Any
    prevent_provider_reactivation: bool
    reason: str | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class FeatureFieldOverrideCommand:
    """typed field override procedure의 exact commit receipt."""

    feature_id: str
    row_revision: int
    command_id: int
    applied_field_count: int
    feature_uuid: str | None = None


@dataclass(frozen=True)
class AdminFeatureStateTransition:
    """Admin state command가 원자적으로 남긴 상태·revision·감사 식별자."""

    feature_id: str
    lifecycle_state: str
    publication_state: str
    quality_state: str
    row_revision: int
    audit_transition_id: int


@dataclass(frozen=True)
class AdminFeatureStateTransitionAudit:
    """Append-only state audit timeline의 한 행.

    Legacy ``status``/tombstone을 재구성하지 않는다. 요청자가 실제로 바꾼
    before/after tuple과 DB가 확정한 provenance를 그대로 반환한다.
    """

    transition_id: int
    from_lifecycle_state: str | None
    from_publication_state: str | None
    from_quality_state: str | None
    to_lifecycle_state: str
    to_publication_state: str
    to_quality_state: str
    transition_kind: str
    reason_code: str
    principal: str
    causation_ref: str | None
    provider_dataset_id: int | None
    source_entity_key: str | None
    source_record_key: str | None
    occurred_at: datetime
    row_revision: int


@dataclass(frozen=True)
class AdminFeatureStateTransitionAuditPage:
    """Newest-first audit keyset page."""

    items: tuple[AdminFeatureStateTransitionAudit, ...]
    next_cursor: int | None


class AdminFeatureStateConflict(ValueError):
    """DB-owned state command가 현재 tuple/provenance와 충돌할 때의 domain 오류."""


class AdminFeatureStateNotFound(ValueError):
    """State command target 또는 required current source evidence가 없을 때의 오류."""


class AdminFeatureStatePreconditionFailed(ValueError):
    """Stored procedure가 expected revision이 stale함을 확인했을 때의 오류."""

    def __init__(self, *, feature_id: str, expected: int) -> None:
        self.feature_id = feature_id
        self.expected = expected
        super().__init__(
            f"feature {feature_id!r} If-Match 불일치: expected row_revision={expected}"
        )


class AdminFeatureStateValidationError(ValueError):
    """Stored procedure가 command tuple/no-op을 reject했을 때의 422 domain 오류."""


class FeatureFieldOverrideNotFound(ValueError):
    """field override command의 Feature 또는 active override가 없을 때 발생."""


class FeatureFieldOverridePreconditionFailed(ValueError):
    """field override command의 expected revision이 stale일 때 발생."""

    def __init__(self, *, feature_id: str, expected: int) -> None:
        self.feature_id = feature_id
        self.expected = expected
        super().__init__(
            f"feature {feature_id!r} If-Match revision이 변경되었습니다: "
            f"expected={expected}"
        )


class FeatureFieldOverrideValidationError(ValueError):
    """registry/receipt/값 contract를 만족하지 않는 field override command."""


@dataclass(frozen=True)
class DedupFeatureSummary:
    """Dedup 후보의 feature 한쪽 summary.

    ``feature_uuid``는 T-VN-32C UUID 정본 병행 노출(additive).
    """

    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None
    lat: float | None
    provider: str | None
    dataset_key: str | None
    feature_uuid: str | None = None


@dataclass(frozen=True)
class DedupReviewRow:
    """``GET /admin/dedup-review`` item."""

    review_id: str
    status: str
    total_score: float
    name_score: float
    spatial_score: float
    category_score: float
    feature_a: DedupFeatureSummary
    feature_b: DedupFeatureSummary
    distance_m: float | None
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class DedupReviewPage:
    """Dedup review keyset page."""

    items: tuple[DedupReviewRow, ...]
    total_count: int
    next_cursor: str | None = None


@dataclass(frozen=True)
class ReviewSourceDetail:
    """Review 상세 비교에 표시할 source record/link snapshot."""

    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: Any
    imported_at: Any
    observed_at: Any | None = None
    source_role: str | None = None
    match_method: str | None = None
    confidence: int | None = None
    linked_at: datetime | None = None


@dataclass(frozen=True)
class ReviewFeatureDetail:
    """Review 상세 비교에 표시할 feature core + source 목록.

    ``feature_uuid``는 T-VN-32C UUID 정본 병행 노출(additive).
    """

    feature_id: str
    kind: str
    name: str
    category: str
    lifecycle_state: str
    publication_state: str
    quality_state: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    raw_refs: list[dict[str, Any]]
    marker_icon: str | None
    marker_color: str | None
    created_at: datetime
    updated_at: datetime
    sources: tuple[ReviewSourceDetail, ...]
    feature_uuid: str | None = None


@dataclass(frozen=True)
class DedupReviewDetail:
    """Dedup review 상세 비교 aggregate."""

    review_id: str
    status: str
    total_score: float
    name_score: float
    spatial_score: float
    category_score: float
    distance_m: float | None
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    feature_a: ReviewFeatureDetail
    feature_b: ReviewFeatureDetail


_ADMIN_FEATURE_SORT_COLUMNS: Final[dict[str, str]] = {
    "name": "sort_name",
    "updated_at": "updated_at",
    "created_at": "created_at",
    "kind": "kind",
    "provider": "sort_provider",
    "issue_count": "issue_count",
}
_TEXT_SORTS: Final[set[str]] = {"name", "kind", "provider"}
_DATETIME_SORTS: Final[set[str]] = {"updated_at", "created_at"}


def _admin_bbox_envelope_sql() -> str:
    """WGS84 bbox envelope SQL. 입력 geometry는 상수로 한 번만 만든다."""

    return (
        "x_extension.ST_MakeEnvelope("
        ":min_lon, :min_lat, :max_lon, :max_lat, 4326)"
    )


def _admin_geometry_hits_sql() -> str:
    """bbox와 실제로 교차한 route/area subtype geometry (T-VN-35, ADR-086).

    geometry 정본이 ``feature_routes``/``feature_areas``로 옮겨졌으므로(0086)
    bbox 술어를 **subtype 쪽에서 먼저** 평가한다 — 각 subtype의 GiST 인덱스
    (``idx_feature_routes_geom_gist``/``idx_feature_areas_geom_gist``)에
    ``&&``가 그대로 내려간다. core를 LEFT JOIN한 뒤 ``COALESCE(geom)``에
    술어를 걸면 인덱스를 못 쓰므로 이 형태가 정본이다.

    두 subtype은 상호 배타(``(feature_id, kind)`` 복합 FK + kind 상수 CHECK)
    이므로 ``UNION ALL``이 ``feature_id`` 유일성을 유지한다 — LEFT JOIN이
    행을 증식시키지 않는다.
    """

    envelope = _admin_bbox_envelope_sql()
    return f"""
  SELECT feature_id, geom
  FROM feature.feature_routes
  WHERE geom OPERATOR(x_extension.&&) {envelope}
    AND x_extension.ST_Intersects(geom, {envelope})
  UNION ALL
  SELECT feature_id, geom
  FROM feature.feature_areas
  WHERE geom OPERATOR(x_extension.&&) {envelope}
    AND x_extension.ST_Intersects(geom, {envelope})
"""


def _admin_bbox_coord_where_sql(alias: str) -> str:
    """route/area가 **아닌** kind의 coord bbox 후보 술어.

    T-VN-35 이후 route/area는 geometry NOT NULL인 subtype 행으로만 존재하므로
    (0086) 종전의 "geometry 없는 route/area는 coord로 잡는다"(``geom IS NULL``
    분기)는 표현 불가능한 상태를 위한 우회였고 여기서 사라진다.
    """

    if not alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    return f"""
  {alias}.coord IS NOT NULL
  AND {alias}.kind NOT IN ('route', 'area')
  AND {alias}.coord OPERATOR(x_extension.&&) {_admin_bbox_envelope_sql()}"""


def _admin_bbox_filters_sql(alias: str) -> str:
    """Admin-any item/cluster 공통 축·속성 필터.

    Admin은 공개 predicate를 재사용하지 않는다. 세 축 filter는 각각 같은 축 안에서는
    OR, 축 사이는 AND로 결합하므로 draft/suppressed/quarantined 검토 대상을 빠뜨리지
    않는다.
    """

    if not alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    return f"""
  AND (
    CAST(:lifecycle_states AS text[]) IS NULL
    OR {alias}.lifecycle_state = ANY(CAST(:lifecycle_states AS text[]))
  )
  AND (
    CAST(:publication_states AS text[]) IS NULL
    OR {alias}.publication_state = ANY(CAST(:publication_states AS text[]))
  )
  AND (
    CAST(:quality_states AS text[]) IS NULL
    OR {alias}.quality_state = ANY(CAST(:quality_states AS text[]))
  )
  AND (
    CAST(:kinds AS text[]) IS NULL
    OR {alias}.kind = ANY(CAST(:kinds AS text[]))
  )
  AND (
    CAST(:categories AS text[]) IS NULL
    OR {alias}.category = ANY(CAST(:categories AS text[]))
  )
  AND (
    CAST(:providers AS text[]) IS NULL
    OR EXISTS (
      SELECT 1
      FROM provider_sync.source_links AS sl
      JOIN provider_sync.source_entities AS se
        ON se.source_entity_key = sl.source_entity_key
      JOIN provider_sync.provider_datasets AS pd
        ON pd.provider_dataset_id = se.provider_dataset_id
      WHERE sl.feature_id = {alias}.feature_id
        AND sl.source_role = 'primary'
        AND pd.provider = ANY(CAST(:providers AS text[]))
    )
  )
"""


# 후보 두 갈래를 **OR가 아니라 UNION ALL**로 합친다 (T-VN-35 성능 정본).
#
# geometry가 core 컬럼이던 시절에는 두 갈래가 같은 relation이라 planner가
# bbox 밀도에 따라 계획을 골랐다 — 조밀 bbox는 PK walk + early exit, 희소
# bbox는 GiST bitmap. subtype 분리 후 이 술어를 그대로 OR로 옮기면 조건이
# **두 relation에 걸쳐** 있어 그 선택지가 통째로 사라지고 항상 전건 PK walk가
# 된다(실측 희소 bbox 1.78s). 반대로 후보를 id 집합으로 미리 모아도 조밀
# bbox에서 early exit을 잃는다(실측 1.46s).
#
# 갈래마다 자기 ``ORDER BY … LIMIT``을 주면 각 갈래에서 planner가 다시
# 고르고, 두 갈래가 kind로 배타라 UNION ALL이 중복을 만들지 않는다. 각
# 갈래의 선두 :limit만 모아 다시 :limit을 취하는 것은 전역 선두 :limit과
# 같다(양쪽 모두 feature_id 오름차순).
#
# 부수 효과로 "route/area냐"를 묻던 CASE들이 사라진다 — coord 갈래는
# geometry가 없고 geo 갈래는 항상 있다(subtype NOT NULL).
_ADMIN_FEATURES_IN_BBOX_SQL: Final[str] = f"""
WITH geo_hits AS ({_admin_geometry_hits_sql()}),
candidates AS (
  (
    SELECT
        f.feature_id,
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
        f.marker_icon,
        f.marker_color,
        f.lifecycle_state,
        f.publication_state,
        f.quality_state,
        f.coord AS marker_coord,
        CAST(NULL AS jsonb) AS geometry,
        CAST(NULL AS double precision) AS area_square_meters
    FROM feature.features AS f
    WHERE {_admin_bbox_coord_where_sql("f")}
{_admin_bbox_filters_sql("f")}
    ORDER BY f.feature_id
    LIMIT :limit
  )
  UNION ALL
  (
    SELECT
        f.feature_id,
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
        f.marker_icon,
        f.marker_color,
        f.lifecycle_state,
        f.publication_state,
        f.quality_state,
        x_extension.ST_PointOnSurface(
          x_extension.ST_Intersection(fg.geom, {_admin_bbox_envelope_sql()})
        ) AS marker_coord,
        CASE
          WHEN NOT CAST(:include_geometry AS boolean) THEN NULL
          WHEN f.kind = 'route'
          THEN CAST(
            x_extension.ST_AsGeoJSON(x_extension.ST_Simplify(fg.geom, 0.0001), 6)
            AS jsonb
          )
          ELSE CAST(
            x_extension.ST_AsGeoJSON(
              x_extension.ST_SimplifyPreserveTopology(fg.geom, 0.0001), 6
            ) AS jsonb
          )
        END AS geometry,
        CASE
          WHEN CAST(:include_geometry AS boolean) AND f.kind = 'area'
          THEN x_extension.ST_Area(CAST(fg.geom AS x_extension.geography))
          ELSE NULL
        END AS area_square_meters
    FROM geo_hits AS fg
    JOIN feature.features AS f ON f.feature_id = fg.feature_id
    WHERE TRUE
{_admin_bbox_filters_sql("f")}
    ORDER BY f.feature_id
    LIMIT :limit
  )
  ORDER BY feature_id
  LIMIT :limit
),
price_points AS (
  SELECT
      c.feature_id,
      fact.provider_dataset_id,
      dataset.dataset_key,
      dataset.display_name AS dataset_display_name,
      dataset.provider,
      fact.price_domain,
      fact.product_key,
      fact.product_name,
      fact.source_product_key,
      fact.source_product_name,
      fact.value_number,
      fact.unit,
      fact.observed_at,
      fact.known_at
  FROM candidates AS c
  JOIN feature.current_price_summary AS summary
    ON summary.feature_id = c.feature_id
  JOIN feature.feature_price_values AS fact
    ON fact.price_value_key = summary.price_value_key
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = fact.provider_dataset_id
   AND dataset.is_active
  WHERE c.kind = 'price'
),
price_summaries AS (
  SELECT
      feature_id,
      jsonb_agg(
        jsonb_build_object(
          'provider_dataset_id', provider_dataset_id,
          'dataset_key', dataset_key,
          'dataset_display_name', dataset_display_name,
          'provider', provider,
          'price_domain', price_domain,
          'product_key', product_key,
          'product_name', product_name,
          'source_product_key', source_product_key,
          'source_product_name', source_product_name,
          'value_number', value_number,
          'unit', unit,
          'observed_at', observed_at,
          'known_at', known_at
        )
        ORDER BY
          CASE product_key
            WHEN 'gasoline' THEN 10 WHEN 'diesel' THEN 20
            WHEN 'premium_gasoline' THEN 30 WHEN 'lpg' THEN 40 ELSE 100
          END,
          product_name NULLS LAST,
          product_key,
          provider_dataset_id,
          price_domain
      ) AS price_summary
  FROM price_points
  GROUP BY feature_id
),
weather_ranked AS (
  SELECT
      c.feature_id,
      fact.provider_dataset_id,
      dataset.dataset_key,
      dataset.display_name AS dataset_display_name,
      dataset.provider,
      fact.weather_domain,
      fact.forecast_style,
      fact.metric_key,
      fact.metric_name,
      fact.value_number,
      fact.value_text,
      fact.unit,
      fact.issued_at,
      fact.valid_at,
      fact.observed_at,
      fact.known_at,
      summary.refresh_after,
      row_number() OVER (
        PARTITION BY c.feature_id
        ORDER BY
          CASE fact.metric_key
            WHEN 'T1H' THEN 10 WHEN 'TMP' THEN 20 WHEN 'TMN' THEN 30
            WHEN 'TMX' THEN 40 WHEN 'POP' THEN 50 WHEN 'SKY' THEN 60
            WHEN 'REH' THEN 70 WHEN 'PTY' THEN 80 WHEN 'PCP' THEN 90
            WHEN 'PM10' THEN 110 WHEN 'PM2_5' THEN 120 WHEN 'CAI' THEN 130
            WHEN 'O3' THEN 140 WHEN 'NO2' THEN 150 WHEN 'SO2' THEN 160
            WHEN 'CO' THEN 170 ELSE 100
          END,
          CASE fact.forecast_style
            WHEN 'observed' THEN 10 WHEN 'nowcast' THEN 20
            WHEN 'ultra_short' THEN 30 WHEN 'short' THEN 40 WHEN 'mid' THEN 50
            ELSE 100
          END,
          CASE WHEN fact.target_at >= now() THEN 0 ELSE 1 END,
          abs(extract(epoch FROM (fact.target_at - now()))),
          fact.known_at DESC,
          fact.weather_value_key DESC
      ) AS rank
  FROM candidates AS c
  JOIN feature.current_weather_summary AS summary
    ON summary.feature_id = c.feature_id
  JOIN feature.feature_weather_values AS fact
    ON fact.weather_value_key = summary.weather_value_key
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = fact.provider_dataset_id
   AND dataset.is_active
  WHERE c.kind = 'weather'
    AND summary.refresh_after > clock_timestamp()
    AND fact.metric_key IN (
      'T1H', 'TMP', 'TMN', 'TMX', 'POP', 'SKY', 'REH', 'PTY', 'PCP',
      'PM10', 'PM2_5', 'CAI', 'O3', 'NO2', 'SO2', 'CO'
    )
),
weather_summaries AS (
  SELECT
      feature_id,
      jsonb_build_object(
        'provider_dataset_id', provider_dataset_id,
        'dataset_key', dataset_key,
        'dataset_display_name', dataset_display_name,
        'provider', provider,
        'weather_domain', weather_domain,
        'forecast_style', forecast_style,
        'metric_key', metric_key,
        'metric_name', metric_name,
        'value_number', value_number,
        'value_text', value_text,
        'unit', unit,
        'issued_at', issued_at,
        'valid_at', valid_at,
        'observed_at', observed_at,
        'known_at', known_at,
        'refresh_after', refresh_after
      ) AS weather_summary
  FROM weather_ranked
  WHERE rank = 1
)
SELECT
    c.feature_id,
    c.feature_uuid,
    c.kind,
    c.name,
    c.category,
    x_extension.ST_X(c.marker_coord) AS lon,
    x_extension.ST_Y(c.marker_coord) AS lat,
    c.marker_icon,
    c.marker_color,
    c.lifecycle_state,
    c.publication_state,
    c.quality_state,
    c.geometry,
    c.area_square_meters,
    price_summaries.price_summary,
    weather_summaries.weather_summary
FROM candidates AS c
LEFT JOIN price_summaries USING (feature_id)
LEFT JOIN weather_summaries USING (feature_id)
ORDER BY c.feature_id
"""


_ADMIN_CLUSTER_CODE_COLUMNS: Final[dict[str, str]] = {
    "sido": "sido_code",
    "sigungu": "sigungu_code",
    "eupmyeondong": "legal_dong_code",
}


def _admin_cluster_bbox_sql(code_column: str) -> str:
    envelope = _admin_bbox_envelope_sql()
    return f"""
WITH geo_hits AS ({_admin_geometry_hits_sql()}),
candidates AS (
  SELECT
      f.{code_column} AS cluster_key,
      f.coord AS marker_coord
  FROM feature.features AS f
  WHERE f.{code_column} IS NOT NULL
    AND {_admin_bbox_coord_where_sql("f")}
{_admin_bbox_filters_sql("f")}
  UNION ALL
  SELECT
      f.{code_column} AS cluster_key,
      x_extension.ST_PointOnSurface(
        x_extension.ST_Intersection(fg.geom, {envelope})
      ) AS marker_coord
  FROM geo_hits AS fg
  JOIN feature.features AS f ON f.feature_id = fg.feature_id
  WHERE f.{code_column} IS NOT NULL
{_admin_bbox_filters_sql("f")}
)
SELECT
    cluster_key,
    count(*) AS feature_count,
    avg(x_extension.ST_X(marker_coord)) AS lon,
    avg(x_extension.ST_Y(marker_coord)) AS lat
FROM candidates
WHERE marker_coord IS NOT NULL
GROUP BY cluster_key
ORDER BY feature_count DESC, cluster_key
LIMIT :limit
"""


_ADMIN_CLUSTER_BBOX_SQL_BY_UNIT: Final[dict[str, str]] = {
    unit: _admin_cluster_bbox_sql(column)
    for unit, column in _ADMIN_CLUSTER_CODE_COLUMNS.items()
}


def _normalize_values(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = [str(value) for value in values if str(value)]
    return normalized or None


def _normalize_query(q: str | None) -> str | None:
    if q is None:
        return None
    normalized = unicodedata.normalize("NFKC", q).strip()
    return normalized or None


# 완전한 ``feature_id``(``f_{bjd}_{kind}_{sha1[:16]}``, core.ids.make_feature_id)
# 형태의 검색어를 감지한다. 이 경우 PK 등가 fast-path로 ILIKE 전체 스캔 +
# source_records 상관 서브쿼리(1M feature 대상 14~60s)를 건너뛴다.
_FEATURE_ID_QUERY_RE: Final = re.compile(r"^f_[^_]+_[a-z]_[0-9a-f]{16}$")

# canonical UUID(lowercase hyphenated 36자) 검색어 — T-VN-32C 값 전환 후 응답
# feature_id가 UUID라 운영자가 그 값을 그대로 검색한다. ``uq_features_feature_uuid``
# 인덱스 등가 fast-path로 처리하지 않으면 ILIKE 풀스캔(#639 회귀)이 된다.
_FEATURE_UUID_QUERY_RE: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _feature_id_exact_query(normalized_q: str | None) -> str | None:
    """정규화된 검색어가 완전한 ``feature_id`` 형태면 그대로, 아니면 ``None``."""
    if normalized_q is None:
        return None
    return normalized_q if _FEATURE_ID_QUERY_RE.match(normalized_q) else None


def _feature_uuid_exact_query(normalized_q: str | None) -> str | None:
    """검색어가 UUID 형태면 canonical lowercase로, 아니면 ``None``.

    경계 해석(``_parse_canonical_uuid``)·batch echo가 대문자 표기를 수용하므로
    검색어도 대소문자 무관하게 fast-path에 태운다 — 소문자 전용이면 대문자
    UUID 검색이 ILIKE 풀스캔(#639 계열)으로 회귀한다 (적대 리뷰 F2).
    """
    if normalized_q is None:
        return None
    lowered = normalized_q.lower()
    return lowered if _FEATURE_UUID_QUERY_RE.match(lowered) else None


def _json_array(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            return json.loads(value)
    return value


def _json_object(value: Any) -> dict[str, Any]:
    value = _json_value(value)
    return dict(value) if isinstance(value, dict) else {}


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    value = _json_value(value)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cursor_payload(cursor: str | None, *, sort: str, order: str) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid admin features cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("sort") != sort
        or payload.get("order") != order
    ):
        raise ValueError("invalid admin features cursor")
    feature_id = payload.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid admin features cursor")
    return payload


def _encode_cursor(item: AdminFeatureRow, *, sort: str, order: str) -> str:
    sort_value: Any
    if sort == "name":
        sort_value = item.name
    elif sort == "updated_at":
        sort_value = item.updated_at.isoformat()
    elif sort == "created_at":
        sort_value = item.created_at.isoformat()
    elif sort == "kind":
        sort_value = item.kind
    elif sort == "provider":
        sort_value = item.primary_provider or ""
    elif sort == "issue_count":
        sort_value = item.issue_count
    else:  # pragma: no cover - sort whitelist가 선행한다.
        raise ValueError("unsupported admin features sort")
    raw = json.dumps(
        {
            "sort": sort,
            "order": order,
            "feature_id": item.feature_id,
            "value": sort_value,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_params(cursor: str | None, *, sort: str, order: str) -> dict[str, Any]:
    payload = _cursor_payload(cursor, sort=sort, order=order)
    params: dict[str, Any] = {
        "cursor_feature_id": None,
        "cursor_text": None,
        "cursor_dt": None,
        "cursor_int": None,
    }
    if not payload:
        return params
    params["cursor_feature_id"] = payload["feature_id"]
    value = payload.get("value")
    if sort in _TEXT_SORTS:
        if not isinstance(value, str):
            raise ValueError("invalid admin features cursor")
        params["cursor_text"] = value
    elif sort in _DATETIME_SORTS:
        try:
            params["cursor_dt"] = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("invalid admin features cursor") from exc
    elif sort == "issue_count":
        if not isinstance(value, str | int | float):
            raise ValueError("invalid admin features cursor")
        try:
            params["cursor_int"] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid admin features cursor") from exc
    return params


def _keyset_condition(*, sort: str, order: str) -> str:
    column = _ADMIN_FEATURE_SORT_COLUMNS[sort]
    op = ">" if order == "asc" else "<"
    if sort in _TEXT_SORTS:
        return (
            "(CAST(:cursor_feature_id AS text) IS NULL OR "
            f"({column}, feature_id) {op} "
            "(CAST(:cursor_text AS text), CAST(:cursor_feature_id AS text)))"
        )
    if sort in _DATETIME_SORTS:
        return (
            "(CAST(:cursor_feature_id AS text) IS NULL OR "
            f"({column}, feature_id) {op} "
            "(CAST(:cursor_dt AS timestamptz), CAST(:cursor_feature_id AS text)))"
        )
    return (
        "(CAST(:cursor_feature_id AS text) IS NULL OR "
        f"({column}, feature_id) {op} "
        "(CAST(:cursor_int AS integer), CAST(:cursor_feature_id AS text)))"
    )


# ── review 목록 keyset cursor (T-VN-H06) ──────────────────────────────────
# dedup/enrichment admin 목록의 stable total-order keyset + filter fingerprint cursor.
# 운영자 전용 표면이므로 list_admin_features와 같은 unsigned base64 방식이다(공개 search의
# HMAC 서명은 hostile client의 cursor 위조 방어용 — T-VN-15 — 이라 same-origin operator
# 트래픽에는 불필요하고, 3개 admin 목록 중 2개만 서명하면 표면 일관성이 깨진다). cursor에
# 전체 filter set의 sha256 fingerprint를 실어 필터가 바뀐 stale cursor를 거부하며, keyset은
# (score DESC, review_id DESC) total order다.
#
# 주의(적대 리뷰 P3-1): 정렬 키 score는 insert/delete/status 변경에는 안정적이나 **불변은
# 아니다** — 재스캔 job이 pending row의 total_score/name_score를 upsert(ON CONFLICT DO UPDATE)
# 하므로, 운영자가 페이지를 넘기는 도중 재스캔이 돌면 score가 cursor 경계를 넘어 이동해 드물게
# 한 row가 건너뛰어지거나 두 번 보일 수 있다. 결정 endpoint는 멱등(WHERE status='pending' 가드 +
# merge advisory lock)이라 이중 병합은 불가능하고 새로고침으로 복구되므로 data corruption은
# 없다. 엄격한 no-skip이 필요해지면 불변 tuple(created_at, review_id) 정렬로 바꾸거나 pending
# 스냅샷을 쓴다 — 교체 대상인 OFFSET은 매 insert/delete마다 skip/dup했으므로 여전히 엄격히 우월.
_REVIEW_CURSOR_VERSION: Final[int] = 1


def _review_filter_fingerprint(kind: str, filters: Mapping[str, Any]) -> str:
    """정규화된 filter set의 canonical sha256 fingerprint.

    set 성격의 list 필터(providers·kinds 등)는 정렬해 값 순서와 무관하게 같은
    fingerprint를 낸다 — keyset order는 이 필터들과 독립이므로 multi-select 재정렬이
    cursor를 깨선 안 된다. SQL param 배열 순서는 바꾸지 않고 fingerprint 계산에서만
    정렬한다.
    """

    canonical_filters = {
        key: (sorted(value) if isinstance(value, list) else value)
        for key, value in filters.items()
    }
    canonical = json.dumps(
        {"kind": kind, "v": _REVIEW_CURSOR_VERSION, "filters": canonical_filters},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _encode_review_cursor(
    *, kind: str, fingerprint: str, review_id: str, score: str
) -> str:
    raw = json.dumps(
        {
            "v": _REVIEW_CURSOR_VERSION,
            "kind": kind,
            "fp": fingerprint,
            "keyset": {"review_id": review_id, "score": score},
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _review_cursor_params(
    cursor: str | None, *, kind: str, fingerprint: str
) -> dict[str, Any]:
    """cursor를 검증해 keyset SQL 파라미터로 변환한다.

    fingerprint 불일치(필터 변경)·형식 오류는 모두 ``ValueError``로 fail-closed한다
    (``_cursor_payload``와 동일한 단일 예외 계약). 실제 uuid/numeric 유효성은 DB CAST가
    최종 검증하지만 명백한 형식 오류는 선제 차단한다.
    """

    params: dict[str, Any] = {"cursor_review_id": None, "cursor_score": None}
    if cursor is None:
        return params
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {kind} cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != _REVIEW_CURSOR_VERSION
        or payload.get("kind") != kind
        or payload.get("fp") != fingerprint
    ):
        raise ValueError(f"invalid {kind} cursor")
    keyset = payload.get("keyset")
    if not isinstance(keyset, dict):
        raise ValueError(f"invalid {kind} cursor")
    review_id = keyset.get("review_id")
    score = keyset.get("score")
    if not isinstance(review_id, str) or not review_id:
        raise ValueError(f"invalid {kind} cursor")
    if not isinstance(score, str) or not score:
        raise ValueError(f"invalid {kind} cursor")
    try:
        score_decimal = Decimal(score)
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"invalid {kind} cursor") from exc
    if not score_decimal.is_finite():
        # Postgres numeric는 NaN/Infinity를 받아들이고 NaN이 최대로 정렬돼 keyset이
        # 조용히 top으로 리셋되므로 명시적으로 거부한다.
        raise ValueError(f"invalid {kind} cursor")
    try:
        uuid.UUID(review_id)
    except ValueError as exc:
        # 유효 fingerprint를 통과한 비-UUID review_id는 CAST(:cursor_review_id AS uuid)
        # 에서 DataError(→500)로 새므로 list_admin_features처럼 Python 측에서 fail-closed.
        raise ValueError(f"invalid {kind} cursor") from exc
    params["cursor_review_id"] = review_id
    params["cursor_score"] = score
    return params


# 완전한 feature_id fast-path: PK 등가로 ILIKE 전체 스캔 + source_records EXISTS를 건너뛴다.
_ADMIN_FEATURES_Q_EXACT_CLAUSE: Final = "AND f.feature_id = CAST(:q_exact AS text)"

# canonical UUID fast-path: ``uq_features_feature_uuid`` 인덱스 등가 (T-VN-32C).
_ADMIN_FEATURES_Q_EXACT_UUID_CLAUSE: Final = (
    "AND f.feature_uuid = CAST(:q_exact_uuid AS uuid)"
)

# 부분 검색: feature_id/name/address + source_records 상관 서브쿼리 ILIKE.
_ADMIN_FEATURES_Q_LIKE_CLAUSE: Final = """AND (
        CAST(:q_like AS text) IS NULL
        OR f.feature_id ILIKE CAST(:q_like AS text)
        OR f.name ILIKE CAST(:q_like AS text)
        OR f.address::text ILIKE CAST(:q_like AS text)
        OR EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS qsl
            JOIN provider_sync.source_entities AS qse
              ON qse.source_entity_key = qsl.source_entity_key
            JOIN provider_sync.source_entity_heads AS qhead
              ON qhead.source_entity_key = qse.source_entity_key
            JOIN provider_sync.source_records AS qsr
              ON qsr.source_entity_key = qse.source_entity_key
             AND qsr.source_record_key = qhead.current_source_record_key
            WHERE qsl.feature_id = f.feature_id
              AND (
                qsr.source_record_key ILIKE CAST(:q_like AS text)
                OR qse.source_entity_id ILIKE CAST(:q_like AS text)
                OR qsr.raw_data::text ILIKE CAST(:q_like AS text)
              )
        )
      )"""


def _admin_features_sql(
    *, sort: str, order: str, exact_id: bool = False, exact_uuid: bool = False
) -> str:
    column = _ADMIN_FEATURE_SORT_COLUMNS[sort]
    order_sql = "ASC" if order == "asc" else "DESC"
    if exact_id:
        q_clause = _ADMIN_FEATURES_Q_EXACT_CLAUSE
    elif exact_uuid:
        q_clause = _ADMIN_FEATURES_Q_EXACT_UUID_CLAUSE
    else:
        q_clause = _ADMIN_FEATURES_Q_LIKE_CLAUSE
    return f"""
WITH base AS (
    SELECT
        f.feature_id,
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        lower(f.name) AS sort_name,
        f.category,
        f.lifecycle_state,
        f.publication_state,
        f.quality_state,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        COALESCE(
            NULLIF(f.address ->> 'road', ''),
            NULLIF(f.address ->> 'legal', ''),
            NULLIF(f.address ->> 'admin', ''),
            ''
        ) AS address_label,
        ps.provider AS primary_provider,
        ps.dataset_key AS primary_dataset_key,
        COALESCE(ps.provider, '') AS sort_provider,
        COALESCE(issue.issue_count, 0)::integer AS issue_count,
        COALESCE(issue.issues, '[]'::jsonb) AS issues,
        f.created_at,
        f.updated_at
    FROM feature.features AS f
    LEFT JOIN LATERAL (
        SELECT pd.provider_dataset_id, pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            count(*)::integer AS issue_count,
            jsonb_agg(
                jsonb_build_object(
                    'issue_id', v.issue_id::text,
                    'violation_type', v.violation_type,
                    'severity', v.severity,
                    'message', v.message,
                    'detected_at', v.detected_at
                )
                ORDER BY v.detected_at DESC
            ) AS issues
        FROM ops.data_integrity_violations AS v
        WHERE v.feature_id = f.feature_id
          AND v.status = 'open'
          AND (
            CAST(:issue_types AS text[]) IS NULL
            OR v.violation_type = ANY(CAST(:issue_types AS text[]))
          )
    ) AS issue ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        -- T-VN-35(0086): valid_end_time은 free-form jsonb가 아니라
        -- ``feature_notices.valid_end_time timestamptz``다. 오염 문자열이
        -- 표현 불가능해졌으므로 종전의 pg_input_is_valid 방어 cast
        -- (report §2 D-9-7 + T-VN-06)가 통째로 사라진다. keyset/fast-path
        -- 계획 축을 건드리지 않도록 join이 아니라 semi-join으로 둔다.
        CAST(:include_ended AS boolean)
        OR NOT EXISTS (
          SELECT 1
          FROM feature.feature_notices AS fn
          WHERE fn.feature_id = f.feature_id
            AND fn.valid_end_time IS NOT NULL
            AND fn.valid_end_time <= now()
        )
      )
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
      )
      AND (
        CAST(:lifecycle_states AS text[]) IS NULL
        OR f.lifecycle_state = ANY(CAST(:lifecycle_states AS text[]))
      )
      AND (
        CAST(:publication_states AS text[]) IS NULL
        OR f.publication_state = ANY(CAST(:publication_states AS text[]))
      )
      AND (
        CAST(:quality_states AS text[]) IS NULL
        OR f.quality_state = ANY(CAST(:quality_states AS text[]))
      )
      AND (
        CAST(:provider_dataset_id AS bigint) IS NULL
        OR ps.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
      )
      AND (
        CAST(:has_coord AS boolean) IS NULL
        OR (CAST(:has_coord AS boolean) AND f.coord IS NOT NULL)
        OR (NOT CAST(:has_coord AS boolean) AND f.coord IS NULL)
      )
      AND (
        CAST(:updated_from AS timestamptz) IS NULL
        OR f.updated_at >= CAST(:updated_from AS timestamptz)
      )
      AND (
        CAST(:updated_to AS timestamptz) IS NULL
        OR f.updated_at <= CAST(:updated_to AS timestamptz)
      )
      {q_clause}
)
SELECT *
FROM base
WHERE (
    CAST(:has_issue AS boolean) IS NULL
    OR (CAST(:has_issue AS boolean) AND issue_count > 0)
    OR (NOT CAST(:has_issue AS boolean) AND issue_count = 0)
)
  AND {_keyset_condition(sort=sort, order=order)}
ORDER BY {column} {order_sql}, feature_id {order_sql}
LIMIT :limit_plus_one
"""


def _admin_feature_row(row: Any) -> AdminFeatureRow:
    feature_uuid = row.get("feature_uuid")
    return AdminFeatureRow(
        feature_id=str(row["feature_id"]),
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        lifecycle_state=str(row["lifecycle_state"]),
        publication_state=str(row["publication_state"]),
        quality_state=str(row["quality_state"]),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        address_label=str(row["address_label"] or ""),
        primary_provider=row["primary_provider"],
        primary_dataset_key=row["primary_dataset_key"],
        issue_count=int(row["issue_count"]),
        issues=_json_array(row["issues"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_ADMIN_FEATURE_DETAIL_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.kind,
    f.name,
    f.category,
    f.lifecycle_state,
    f.publication_state,
    f.quality_state,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.coord_precision_digits,
    CASE
      WHEN f.kind = 'area' AND a.geom IS NOT NULL
      THEN x_extension.ST_Area(CAST(a.geom AS x_extension.geography))
      ELSE NULL
    END AS area_square_meters,
    f.address,
    {TYPED_FEATURE_DETAIL_COLUMNS_SQL},
    f.urls,
    f.raw_refs,
    f.legal_dong_code,
    f.road_name_code,
    f.road_address_management_no,
    f.admin_dong_code,
    f.sido_code,
    f.sigungu_code,
    f.marker_icon,
    f.marker_color,
    f.parent_feature_id,
    f.sibling_group_id::text AS sibling_group_id,
    f.row_revision,
    f.created_at,
    f.updated_at
FROM feature.features AS f
{typed_feature_detail_joins_sql("f")}
WHERE f.feature_id = :feature_id
"""

_ADMIN_FEATURE_SOURCES_SQL: Final[str] = """
SELECT
    se.source_entity_key,
    sr.source_record_key,
    pd.provider,
    pd.dataset_key,
    se.source_entity_type,
    se.source_entity_id,
    sl.source_role,
    sl.match_method,
    sl.confidence,
    sr.raw_payload_hash,
    sr.raw_data,
    sr.fetched_at,
    sr.imported_at,
    head.observed_at,
    head.expires_at,
    sl.created_at AS linked_at
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = se.source_entity_key
JOIN provider_sync.source_records AS sr
  ON sr.source_entity_key = se.source_entity_key
 AND sr.source_record_key = head.current_source_record_key
WHERE sl.feature_id = :feature_id
ORDER BY (sl.source_role = 'primary') DESC, head.observed_at DESC,
         sr.imported_at DESC NULLS LAST,
         sl.created_at DESC, sr.source_record_key
"""

_ADMIN_FEATURE_ISSUES_SQL: Final[str] = """
SELECT
    violation.issue_id::text AS issue_id,
    -- provider/dataset_key는 violation 행에서 사라졌다. 표시용 projection이므로
    -- catalog에서 읽는다 (identity는 provider_dataset_id다).
    dataset.provider,
    dataset.dataset_key,
    violation.source_record_key,
    violation.violation_type,
    violation.severity,
    violation.message,
    violation.payload,
    violation.status,
    violation.detected_at,
    violation.resolved_at
FROM ops.data_integrity_violations AS violation
LEFT JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = violation.provider_dataset_id
WHERE violation.feature_id = :feature_id
ORDER BY (violation.status = 'open') DESC, violation.detected_at DESC,
         violation.issue_id DESC
LIMIT 100
"""

_ADMIN_FEATURE_OVERRIDES_SQL: Final[str] = """
SELECT
    override_id::text AS override_id,
    source_record_key,
    field_path,
    source_value,
    override_value,
    prevent_provider_reactivation,
    status,
    reason,
    created_by,
    created_at
FROM ops.feature_overrides
WHERE feature_id = :feature_id
ORDER BY (status = 'active') DESC, created_at DESC, override_id DESC
LIMIT 100
"""

_FEATURE_FILES_TABLE_EXISTS_SQL: Final[str] = """
SELECT to_regclass('feature.feature_files') IS NOT NULL AS exists
"""

_ADMIN_FEATURE_FILES_SQL: Final[str] = """
SELECT
    file_id,
    file_type,
    storage_backend,
    bucket,
    object_key,
    source_url,
    public_url,
    content_type,
    byte_size,
    checksum_sha256,
    width,
    height,
    role,
    display_order,
    alt_text,
    provider,
    dataset_key,
    source_record_key,
    payload,
    created_at,
    updated_at
FROM feature.feature_files
WHERE feature_id = :feature_id
ORDER BY display_order ASC, file_id ASC
LIMIT 100
"""


def _admin_feature_detail_feature(row: Any) -> AdminFeatureDetailFeature:
    feature_uuid = row.get("feature_uuid")
    return AdminFeatureDetailFeature(
        feature_id=str(row["feature_id"]),
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        lifecycle_state=str(row["lifecycle_state"]),
        publication_state=str(row["publication_state"]),
        quality_state=str(row["quality_state"]),
        lon=_float_or_none(row["lon"]),
        lat=_float_or_none(row["lat"]),
        coord_precision_digits=(
            int(row["coord_precision_digits"])
            if row["coord_precision_digits"] is not None
            else None
        ),
        area_square_meters=_float_or_none(row.get("area_square_meters")),
        address=_json_object(row["address"]),
        detail=_json_object(row["detail"]),
        urls=_json_object(row["urls"]),
        raw_refs=_json_object_list(row["raw_refs"]),
        legal_dong_code=row["legal_dong_code"],
        road_name_code=row["road_name_code"],
        road_address_management_no=row["road_address_management_no"],
        admin_dong_code=row["admin_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        parent_feature_id=row["parent_feature_id"],
        sibling_group_id=row["sibling_group_id"],
        row_revision=int(row["row_revision"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _admin_feature_detail_source(row: Any) -> AdminFeatureDetailSource:
    return AdminFeatureDetailSource(
        source_entity_key=str(row["source_entity_key"]),
        source_record_key=str(row["source_record_key"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_entity_type=str(row["source_entity_type"]),
        source_entity_id=str(row["source_entity_id"]),
        source_role=str(row["source_role"]),
        match_method=str(row["match_method"]),
        confidence=int(row["confidence"]),
        raw_payload_hash=str(row["raw_payload_hash"]),
        raw_data=_json_object(row["raw_data"]),
        fetched_at=row["fetched_at"],
        imported_at=row["imported_at"],
        observed_at=row["observed_at"],
        expires_at=row["expires_at"],
        linked_at=row["linked_at"],
    )


def _admin_feature_detail_issue(row: Any) -> AdminFeatureDetailIssue:
    return AdminFeatureDetailIssue(
        issue_id=str(row["issue_id"]),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_record_key=row["source_record_key"],
        violation_type=str(row["violation_type"]),
        severity=str(row["severity"]),
        message=str(row["message"]),
        payload=_json_object(row["payload"]),
        status=str(row["status"]),
        detected_at=row["detected_at"],
        resolved_at=row["resolved_at"],
    )


def _admin_feature_detail_override(row: Any) -> AdminFeatureDetailOverride:
    return AdminFeatureDetailOverride(
        override_id=str(row["override_id"]),
        source_record_key=row["source_record_key"],
        field_path=str(row["field_path"]),
        source_value=_json_value(row["source_value"]),
        override_value=_json_value(row["override_value"]),
        prevent_provider_reactivation=bool(row["prevent_provider_reactivation"]),
        status=str(row["status"]),
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _admin_feature_detail_file(row: Any) -> AdminFeatureDetailFile:
    return AdminFeatureDetailFile(
        file_id=str(row["file_id"]),
        file_type=str(row["file_type"]),
        storage_backend=str(row["storage_backend"]),
        bucket=str(row["bucket"]),
        object_key=str(row["object_key"]),
        source_url=row["source_url"],
        public_url=row["public_url"],
        content_type=row["content_type"],
        byte_size=int(row["byte_size"]) if row["byte_size"] is not None else None,
        checksum_sha256=row["checksum_sha256"],
        width=int(row["width"]) if row["width"] is not None else None,
        height=int(row["height"]) if row["height"] is not None else None,
        role=str(row["role"]),
        display_order=int(row["display_order"]),
        alt_text=row["alt_text"],
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_record_key=row["source_record_key"],
        payload=_json_object(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _feature_files_table_exists(session: AsyncSession) -> bool:
    row = (
        await session.execute(text(_FEATURE_FILES_TABLE_EXISTS_SQL), {})
    ).mappings().one()
    return bool(row["exists"])


async def _list_admin_feature_files(
    session: AsyncSession, feature_id: str
) -> tuple[AdminFeatureDetailFile, ...]:
    if not await _feature_files_table_exists(session):
        return ()
    rows = (
        await session.execute(text(_ADMIN_FEATURE_FILES_SQL), {"feature_id": feature_id})
    ).mappings().all()
    return tuple(_admin_feature_detail_file(row) for row in rows)


async def get_admin_feature_detail(
    session: AsyncSession, feature_id: str
) -> AdminFeatureDetail | None:
    """Admin 상세 화면용 feature aggregate를 조회한다."""
    feature_row = (
        await session.execute(
            text(_ADMIN_FEATURE_DETAIL_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    if feature_row is None:
        return None

    sources = (
        await session.execute(
            text(_ADMIN_FEATURE_SOURCES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    issues = (
        await session.execute(
            text(_ADMIN_FEATURE_ISSUES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    overrides = (
        await session.execute(
            text(_ADMIN_FEATURE_OVERRIDES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    return AdminFeatureDetail(
        feature=_admin_feature_detail_feature(feature_row),
        sources=tuple(_admin_feature_detail_source(row) for row in sources),
        issues=tuple(_admin_feature_detail_issue(row) for row in issues),
        overrides=tuple(_admin_feature_detail_override(row) for row in overrides),
        files=await _list_admin_feature_files(session, feature_id),
        state_transitions=(
            await list_admin_feature_state_transitions(session, feature_id, limit=50)
        ).items,
    )


_ADMIN_FEATURE_STATE_TRANSITIONS_SQL: Final[str] = """
SELECT
    transition_id,
    from_lifecycle_state,
    from_publication_state,
    from_quality_state,
    to_lifecycle_state,
    to_publication_state,
    to_quality_state,
    transition_kind,
    reason_code,
    principal,
    causation_ref,
    provider_dataset_id,
    source_entity_key,
    source_record_key,
    occurred_at,
    row_revision
FROM feature.feature_state_transitions
WHERE feature_id = :feature_id
  AND (
    CAST(:before_transition_id AS bigint) IS NULL
    OR transition_id < CAST(:before_transition_id AS bigint)
  )
ORDER BY transition_id DESC
LIMIT :limit_plus_one
"""


def _admin_feature_state_transition_audit(
    row: Any,
) -> AdminFeatureStateTransitionAudit:
    return AdminFeatureStateTransitionAudit(
        transition_id=int(row["transition_id"]),
        from_lifecycle_state=row["from_lifecycle_state"],
        from_publication_state=row["from_publication_state"],
        from_quality_state=row["from_quality_state"],
        to_lifecycle_state=str(row["to_lifecycle_state"]),
        to_publication_state=str(row["to_publication_state"]),
        to_quality_state=str(row["to_quality_state"]),
        transition_kind=str(row["transition_kind"]),
        reason_code=str(row["reason_code"]),
        principal=str(row["principal"]),
        causation_ref=row["causation_ref"],
        provider_dataset_id=(
            int(row["provider_dataset_id"])
            if row["provider_dataset_id"] is not None
            else None
        ),
        source_entity_key=row["source_entity_key"],
        source_record_key=row["source_record_key"],
        occurred_at=row["occurred_at"],
        row_revision=int(row["row_revision"]),
    )


async def list_admin_feature_state_transitions(
    session: AsyncSession,
    feature_id: str,
    *,
    limit: int = 50,
    before_transition_id: int | None = None,
) -> AdminFeatureStateTransitionAuditPage:
    """Feature별 append-only audit를 newest-first identity keyset으로 읽는다."""

    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    if before_transition_id is not None and before_transition_id <= 0:
        raise ValueError("before_transition_id must be positive")
    effective_limit = min(limit, 200)
    rows = (
        await session.execute(
            text(_ADMIN_FEATURE_STATE_TRANSITIONS_SQL),
            {
                "feature_id": feature_id,
                "before_transition_id": before_transition_id,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).mappings().all()
    items = tuple(
        _admin_feature_state_transition_audit(row)
        for row in rows[:effective_limit]
    )
    next_cursor = (
        items[-1].transition_id if len(rows) > effective_limit and items else None
    )
    return AdminFeatureStateTransitionAuditPage(
        items=items,
        next_cursor=next_cursor,
    )


def _review_source_detail(row: AdminFeatureDetailSource) -> ReviewSourceDetail:
    return ReviewSourceDetail(
        source_record_key=row.source_record_key,
        provider=row.provider,
        dataset_key=row.dataset_key,
        source_entity_type=row.source_entity_type,
        source_entity_id=row.source_entity_id,
        source_role=row.source_role,
        match_method=row.match_method,
        confidence=row.confidence,
        raw_payload_hash=row.raw_payload_hash,
        raw_data=row.raw_data,
        fetched_at=row.fetched_at,
        imported_at=row.imported_at,
        observed_at=row.observed_at,
        linked_at=row.linked_at,
    )


def _review_source_from_queued_row(row: Any) -> ReviewSourceDetail:
    return ReviewSourceDetail(
        source_record_key=str(row["source_record_key"]),
        provider=str(row["source_provider"]),
        dataset_key=str(row["source_dataset_key"]),
        source_entity_type=str(row["source_entity_type"]),
        source_entity_id=str(row["source_entity_id"]),
        raw_payload_hash=str(row["raw_payload_hash"]),
        raw_data=_json_object(row["raw_data"]),
        fetched_at=row["fetched_at"],
        imported_at=row["imported_at"],
    )


def _review_feature_detail(row: AdminFeatureDetail) -> ReviewFeatureDetail:
    feature = row.feature
    return ReviewFeatureDetail(
        feature_id=feature.feature_id,
        feature_uuid=feature.feature_uuid,
        kind=feature.kind,
        name=feature.name,
        category=feature.category,
        lifecycle_state=feature.lifecycle_state,
        publication_state=feature.publication_state,
        quality_state=feature.quality_state,
        lon=feature.lon,
        lat=feature.lat,
        address=feature.address,
        detail=feature.detail,
        urls=feature.urls,
        raw_refs=feature.raw_refs,
        marker_icon=feature.marker_icon,
        marker_color=feature.marker_color,
        created_at=feature.created_at,
        updated_at=feature.updated_at,
        sources=tuple(_review_source_detail(source) for source in row.sources),
    )


async def _get_review_feature_detail(
    session: AsyncSession, feature_id: str
) -> ReviewFeatureDetail | None:
    detail = await get_admin_feature_detail(session, feature_id)
    return _review_feature_detail(detail) if detail is not None else None


async def admin_features_in_bbox(
    session: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    lifecycle_states: Sequence[str] | None = None,
    publication_states: Sequence[str] | None = None,
    quality_states: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    providers: Sequence[str] | None = None,
    include_geometry: bool = False,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Admin-any base Feature를 bbox에서 조회한다.

    공개 projection을 사용하지 않으며 draft/suppressed/quarantined/retired를
    축 filter로 찾을 수 있다. route/area는 bbox MBR 후보 뒤 exact
    ``ST_Intersects``를 적용하고, ``include_geometry``는 payload만 제어한다.
    """

    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("invalid bbox")
    rows = (
        await session.execute(
            text(_ADMIN_FEATURES_IN_BBOX_SQL),
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "lifecycle_states": _normalize_values(lifecycle_states),
                "publication_states": _normalize_values(publication_states),
                "quality_states": _normalize_values(quality_states),
                "kinds": _normalize_values(kinds),
                "categories": _normalize_values(categories),
                "providers": _normalize_values(providers),
                "include_geometry": include_geometry,
                "limit": max(1, limit),
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def cluster_admin_features_in_bbox(
    session: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    cluster_unit: str,
    lifecycle_states: Sequence[str] | None = None,
    publication_states: Sequence[str] | None = None,
    quality_states: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    providers: Sequence[str] | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Admin base Feature를 canonical 행정코드 단위로 bbox rollup한다."""

    if cluster_unit not in _ADMIN_CLUSTER_BBOX_SQL_BY_UNIT:
        raise ValueError("cluster_unit must be one of sido, sigungu, eupmyeondong")
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("invalid bbox")
    rows = (
        await session.execute(
            text(_ADMIN_CLUSTER_BBOX_SQL_BY_UNIT[cluster_unit]),
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "lifecycle_states": _normalize_values(lifecycle_states),
                "publication_states": _normalize_values(publication_states),
                "quality_states": _normalize_values(quality_states),
                "kinds": _normalize_values(kinds),
                "categories": _normalize_values(categories),
                "providers": _normalize_values(providers),
                "limit": max(1, limit),
            },
        )
    ).mappings().all()
    return [
        {
            "cluster_key": str(row["cluster_key"]),
            "feature_count": int(row["feature_count"]),
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
        }
        for row in rows
    ]


async def list_admin_features(
    session: AsyncSession,
    *,
    q: str | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    lifecycle_states: Sequence[str] | None = None,
    publication_states: Sequence[str] | None = None,
    quality_states: Sequence[str] | None = None,
    provider_dataset_id: int | None = None,
    has_coord: bool | None = None,
    has_issue: bool | None = None,
    issue_types: Sequence[str] | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    include_ended: bool = False,
    page_size: int = 50,
    cursor: str | None = None,
    sort: AdminFeatureSort = "name",
    order: SortOrder = "asc",
) -> AdminFeaturePage:
    """Admin feature 목록을 keyset cursor로 조회한다.

    ``include_ended``: 기본 ``False`` — 수집 feed에서 사라져 종료된(valid_end_time
    채워진) notice는 감사 목록에서도 기본 제외한다(#632, 사용자 요구: 수집에 없는
    notice는 과거 자료로 노출하지 않음). 감사가 필요하면 ``True``로 명시 조회.
    """
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    q_exact = _feature_id_exact_query(normalized_q)
    q_exact_uuid = None if q_exact is not None else _feature_uuid_exact_query(normalized_q)
    params = {
        "q_like": (
            None
            if q_exact is not None or q_exact_uuid is not None
            else (f"%{normalized_q}%" if normalized_q is not None else None)
        ),
        "q_exact": q_exact,
        "q_exact_uuid": q_exact_uuid,
        "kinds": _normalize_values(kinds),
        "categories": _normalize_values(categories),
        "lifecycle_states": _normalize_values(lifecycle_states),
        "publication_states": _normalize_values(publication_states),
        "quality_states": _normalize_values(quality_states),
        "provider_dataset_id": provider_dataset_id,
        "has_coord": has_coord,
        "has_issue": has_issue,
        "issue_types": _normalize_values(issue_types),
        "updated_from": updated_from,
        "updated_to": updated_to,
        "include_ended": include_ended,
        "limit_plus_one": effective_limit + 1,
        **_cursor_params(cursor, sort=sort, order=order),
    }
    rows = (
        await session.execute(
            text(
                _admin_features_sql(
                    sort=sort,
                    order=order,
                    exact_id=q_exact is not None,
                    exact_uuid=q_exact_uuid is not None,
                )
            ),
            params,
        )
    ).mappings().all()
    items = tuple(_admin_feature_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_cursor(items[-1], sort=sort, order=order)
        if len(rows) > effective_limit and items
        else None
    )
    return AdminFeaturePage(items=items, next_cursor=next_cursor)


_TRANSITION_FEATURE_STATE_SQL: Final[str] = """
CALL feature.transition_feature_state(
    CAST(:feature_id AS text),
    CAST(:lifecycle_state AS text),
    CAST(:publication_state AS text),
    CAST(:quality_state AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:state_context AS jsonb),
    NULL, NULL
)
"""

_AUTHOR_LIFECYCLE_OVERRIDE_SQL: Final[str] = """
CALL feature.author_lifecycle_override(
    CAST(:feature_id AS text),
    CAST(:source_lifecycle_state AS text),
    CAST(:override_lifecycle_state AS text),
    CAST(:prevent_provider_reactivation AS boolean),
    CAST(:reason AS text),
    CAST(:operator AS text),
    CAST(:expected_row_revision AS bigint),
    NULL
)
"""

_GET_ACTIVE_LIFECYCLE_OVERRIDE_SQL: Final[str] = """
SELECT
    override_id::text,
    feature_id,
    field_path,
    override_value,
    prevent_provider_reactivation,
    reason,
    created_by,
    created_at
FROM ops.feature_overrides
WHERE feature_id = :feature_id
  AND field_path = 'lifecycle_state'
  AND status = 'active'
"""


def _feature_override(row: Any) -> FeatureOverride:
    value = row["override_value"]
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            value = json.loads(value)
    return FeatureOverride(
        override_id=str(row["override_id"]),
        feature_id=str(row["feature_id"]),
        field_path=str(row["field_path"]),
        override_value=value,
        prevent_provider_reactivation=bool(row["prevent_provider_reactivation"]),
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


_TRANSITION_ADMIN_FEATURE_STATE_SQL: Final[str] = """
CALL feature.transition_admin_feature_state(
    CAST(:feature_id AS text),
    CAST(:lifecycle_state AS text),
    CAST(:publication_state AS text),
    CAST(:quality_state AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:reason_code AS text),
    CAST(:operator AS text),
    CAST(:action AS text),
    NULL, NULL, NULL
)
"""

_REACTIVATE_ADMIN_FEATURE_STATE_SQL: Final[str] = """
CALL feature.reactivate_admin_feature_state(
    CAST(:feature_id AS text),
    CAST(:provider_dataset_id AS bigint),
    CAST(:source_entity_key AS text),
    CAST(:source_record_key AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:reason_code AS text),
    CAST(:operator AS text),
    NULL, NULL, NULL
)
"""

_ADMIN_STATE_TRANSITION_RESULT_SQL: Final[str] = """
SELECT feature_id, lifecycle_state, publication_state, quality_state, row_revision
FROM feature.features
WHERE feature_id = :feature_id
  AND row_revision = :row_revision
"""


def _validated_operator_and_reason_code(*, operator: str, reason_code: str) -> None:
    if not operator.strip():
        raise ValueError("admin state transition에는 authenticated operator가 필요합니다.")
    if not reason_code.strip():
        raise ValueError("admin state transition에는 non-empty reason_code가 필요합니다.")


# asyncpg에서 constraint 이름은 ``error.orig``가 아니라 그 **__cause__**(원본
# asyncpg 예외)에 있다. ``error.orig``는 SQLAlchemy가 만든 DBAPI 래퍼라
# ``sqlstate``는 갖지만 ``constraint_name``도 ``diag``도 갖지 않는다. 예전
# ``_pg_error_attribute``는 ``orig``만 봐서 constraint가 **항상 None**이었고, 그래서
# 아래 두 집합의 이름이 하나도 매칭되지 않았다 — 매핑 전체가 죽은 코드였고
# 모든 23514가 라우터의 except 사슬을 통과해 catch-all 500이 됐다(2026-08-12 적대
# 리뷰 실측). 저장소에는 이미 예외 사슬을 순회하는 올바른 추출기가 있으므로
# 두 벌을 두지 않고 그것을 쓴다.


# 현재 tuple과 **충돌**하는 요청 — 요청 자체는 형식이 맞고, 지금 상태에서만 불가능하다.
_ADMIN_STATE_CONFLICT_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {
        "ck_feature_provider_source_provenance",
        "ck_feature_provider_reactivation_override",
        "ck_feature_admin_reactivation",
        # retired feature에 published/draft를 요구하는 patch. 요청 axis 값 자체는
        # 유효하고 현재 lifecycle과의 조합만 불가능하므로 위 reactivation 충돌과
        # 같은 부류다. 이 이름이 빠져 있는 동안 raw IntegrityError가 라우터의 except를
        # 전부 통과해 catch-all 500이 됐다 — 선언된 응답 집합에도 없는 상태였다.
        "ck_features_state_tuple",
    }
)

# 요청 자체가 성립하지 않는다 — 현재 상태와 무관하게 거부된다.
_ADMIN_STATE_VALIDATION_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {
        "ck_feature_admin_state_command",
        "ck_feature_state_transition_non_noop",
        "ck_feature_state_expected_revision",
        # axis enum. API schema가 먼저 걸러내지만, schema와 DDL이 갈리는 순간
        # 500으로 새지 않게 2차 방어를 둔다.
        "ck_features_lifecycle_state",
        "ck_features_publication_state",
        "ck_features_quality_state",
    }
)


def _raise_admin_state_procedure_error(
    error: DBAPIError,
    *,
    feature_id: str,
    expected_row_revision: int,
) -> NoReturn:
    """0097 state procedure의 DB contract를 HTTP-domain 오류로 보존한다.

    매핑에 없는 23514는 raw로 다시 던진다 — 조용히 도메인 오류로 바꾸면 진짜
    불변식 위반(=버그)이 정상 응답처럼 보인다. 대신 이름이 실제 DDL에 존재하는지는
    ``test_admin_state_error_mapping_names_exist_in_ddl``이 fail-close로 지킨다.
    """

    sqlstate, constraint = _driver_constraint_identity(error)
    if sqlstate == "P0002":
        raise AdminFeatureStateNotFound(f"feature/source evidence 없음: {feature_id!r}") from error
    if sqlstate == "40001":
        raise AdminFeatureStatePreconditionFailed(
            feature_id=feature_id,
            expected=expected_row_revision,
        ) from error
    if sqlstate == "23514":
        if constraint in _ADMIN_STATE_CONFLICT_CONSTRAINTS:
            raise AdminFeatureStateConflict(str(error.orig)) from error
        if constraint in _ADMIN_STATE_VALIDATION_CONSTRAINTS:
            raise AdminFeatureStateValidationError(str(error.orig)) from error
    raise error


async def _admin_state_transition_result(
    session: AsyncSession,
    *,
    transition: Any,
) -> AdminFeatureStateTransition:
    """Procedure OUT identity와 현재 tuple을 같은 revision으로 결합한다.

    ``transition_id``를 "latest audit row"의 느슨한 정렬로 재조회하지 않는다.
    security-definer procedure가 반환한 exact identity와 exact revision을 함께
    사용하므로 다른 writer가 같은 Feature를 갱신해도 audit receipt가 바뀌지 않는다.
    """

    feature_id = str(transition["o_feature_id"])
    row_revision = int(transition["o_row_revision"])
    row = (
        await session.execute(
            text(_ADMIN_STATE_TRANSITION_RESULT_SQL),
            {"feature_id": feature_id, "row_revision": row_revision},
        )
    ).mappings().one()
    return AdminFeatureStateTransition(
        feature_id=str(row["feature_id"]),
        lifecycle_state=str(row["lifecycle_state"]),
        publication_state=str(row["publication_state"]),
        quality_state=str(row["quality_state"]),
        row_revision=int(row["row_revision"]),
        audit_transition_id=int(transition["o_transition_id"]),
    )


async def transition_admin_feature_state(
    session: AsyncSession,
    feature_id: str,
    *,
    lifecycle_state: str | None = None,
    publication_state: str | None = None,
    quality_state: str | None = None,
    expected_row_revision: int,
    reason_code: str,
    operator: str,
    action: Literal["patch", "retire"],
) -> AdminFeatureStateTransition:
    """Admin state command를 DB-owned atomic procedure로 실행한다.

    ``patch``는 publication/quality 중 하나 이상만 받고 lifecycle은 건드리지
    않는다. ``retire``는 어떤 axis도 받지 않으며 DB가 current quality를 보존해
    `(retired, suppressed, current quality)`와 lifecycle override를 한 revision으로
    만든다. reason code는 append-only audit에 그대로 보존된다.
    """

    _validated_operator_and_reason_code(
        operator=operator, reason_code=reason_code
    )
    if action == "patch":
        if lifecycle_state is not None:
            raise ValueError("admin state patch는 lifecycle_state를 변경할 수 없습니다.")
        if publication_state is None and quality_state is None:
            raise ValueError(
                "admin state patch에는 publication_state 또는 quality_state가 필요합니다."
            )
    else:
        if any(
            value is not None
            for value in (lifecycle_state, publication_state, quality_state)
        ):
            raise ValueError("admin retire action은 state axis를 함께 받을 수 없습니다.")

    try:
        transition = (
            await session.execute(
                text(_TRANSITION_ADMIN_FEATURE_STATE_SQL),
                {
                    "feature_id": feature_id,
                    "lifecycle_state": lifecycle_state,
                    "publication_state": publication_state,
                    "quality_state": quality_state,
                    "expected_row_revision": expected_row_revision,
                    "reason_code": reason_code,
                    "operator": operator,
                    "action": action,
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_admin_state_procedure_error(
            error,
            feature_id=feature_id,
            expected_row_revision=expected_row_revision,
        )
    return await _admin_state_transition_result(session, transition=transition)


async def reactivate_admin_feature_state(
    session: AsyncSession,
    feature_id: str,
    *,
    expected_row_revision: int,
    reason_code: str,
    operator: str,
    provider_dataset_id: int,
    source_entity_key: str,
    source_record_key: str,
) -> AdminFeatureStateTransition:
    """검증된 current source evidence로만 retired Feature를 재활성화한다."""

    _validated_operator_and_reason_code(
        operator=operator, reason_code=reason_code
    )
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id must be positive")
    if not source_entity_key.strip() or not source_record_key.strip():
        raise ValueError("reactivation에는 current source entity/record evidence가 필요합니다.")
    try:
        transition = (
            await session.execute(
                text(_REACTIVATE_ADMIN_FEATURE_STATE_SQL),
                {
                    "feature_id": feature_id,
                    "provider_dataset_id": provider_dataset_id,
                    "source_entity_key": source_entity_key,
                    "source_record_key": source_record_key,
                    "expected_row_revision": expected_row_revision,
                    "reason_code": reason_code,
                    "operator": operator,
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_admin_state_procedure_error(
            error,
            feature_id=feature_id,
            expected_row_revision=expected_row_revision,
        )
    return await _admin_state_transition_result(session, transition=transition)


_AUTHOR_ADMIN_FEATURE_FIELD_OVERRIDES_SQL: Final[str] = """
CALL feature.author_feature_field_overrides(
    CAST(:feature_id AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:principal AS text),
    CAST(:reason_code AS text),
    CAST(:command_id AS bigint),
    CAST(:values AS jsonb),
    CAST(:geometry_wkt AS jsonb),
    NULL, NULL, NULL, NULL
)
"""

_REVOKE_ADMIN_FEATURE_FIELD_OVERRIDES_SQL: Final[str] = """
CALL feature.revoke_feature_field_overrides(
    CAST(:feature_id AS text),
    CAST(:expected_row_revision AS bigint),
    CAST(:principal AS text),
    CAST(:reason_code AS text),
    CAST(:command_id AS bigint),
    CAST(:field_paths AS text[]),
    NULL, NULL, NULL, NULL
)
"""


def _raise_field_override_procedure_error(
    error: DBAPIError,
    *,
    feature_id: str,
    expected_row_revision: int,
) -> NoReturn:
    """typed field override procedure 오류를 route-level contract로 보존한다."""

    sqlstate = _pg_error_attribute(error, "sqlstate")
    if sqlstate == "P0002":
        raise FeatureFieldOverrideNotFound(
            f"feature 또는 active field override 없음: {feature_id!r}"
        ) from error
    if sqlstate == "40001":
        raise FeatureFieldOverridePreconditionFailed(
            feature_id=feature_id,
            expected=expected_row_revision,
        ) from error
    if sqlstate == "23514":
        raise FeatureFieldOverrideValidationError(str(error.orig)) from error
    raise error


async def author_admin_feature_field_overrides(
    session: AsyncSession,
    feature_id: str,
    *,
    expected_row_revision: int,
    reason_code: str,
    operator: str,
    command_id: int,
    values: Mapping[str, Any],
    geometry_wkt: Mapping[str, str | None],
) -> FeatureFieldOverrideCommand:
    """admin ledger command으로 registry-typed override를 원자 author한다."""

    _validated_operator_and_reason_code(operator=operator, reason_code=reason_code)
    if command_id < 1:
        raise ValueError("field override에는 open domain command receipt가 필요합니다.")
    if not values and not geometry_wkt:
        raise ValueError("field override에는 적어도 하나의 field 값이 필요합니다.")
    if set(values) & set(geometry_wkt):
        raise ValueError("scalar와 geometry field path는 겹칠 수 없습니다.")
    try:
        row = (
            await session.execute(
                text(_AUTHOR_ADMIN_FEATURE_FIELD_OVERRIDES_SQL),
                {
                    "feature_id": feature_id,
                    "expected_row_revision": expected_row_revision,
                    "principal": operator,
                    "reason_code": reason_code,
                    "command_id": command_id,
                    "values": json.dumps(values, ensure_ascii=False, default=str),
                    "geometry_wkt": json.dumps(
                        geometry_wkt, ensure_ascii=False, default=str
                    ),
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_field_override_procedure_error(
            error,
            feature_id=feature_id,
            expected_row_revision=expected_row_revision,
        )
    return FeatureFieldOverrideCommand(
        feature_id=str(row["o_feature_id"]),
        row_revision=int(row["o_row_revision"]),
        command_id=int(row["o_command_id"]),
        applied_field_count=int(row["o_applied_field_count"]),
    )


async def revoke_admin_feature_field_overrides(
    session: AsyncSession,
    feature_id: str,
    *,
    expected_row_revision: int,
    reason_code: str,
    operator: str,
    command_id: int,
    field_paths: Sequence[str],
) -> FeatureFieldOverrideCommand:
    """admin ledger command으로 active override를 base 값으로 되돌린다."""

    _validated_operator_and_reason_code(operator=operator, reason_code=reason_code)
    normalized_paths = tuple(path.strip() for path in field_paths if path.strip())
    if command_id < 1:
        raise ValueError("field override에는 open domain command receipt가 필요합니다.")
    if not normalized_paths or len(normalized_paths) != len(set(normalized_paths)):
        raise ValueError("revoke에는 중복 없는 하나 이상의 field_path가 필요합니다.")
    try:
        row = (
            await session.execute(
                text(_REVOKE_ADMIN_FEATURE_FIELD_OVERRIDES_SQL),
                {
                    "feature_id": feature_id,
                    "expected_row_revision": expected_row_revision,
                    "principal": operator,
                    "reason_code": reason_code,
                    "command_id": command_id,
                    "field_paths": list(normalized_paths),
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_field_override_procedure_error(
            error,
            feature_id=feature_id,
            expected_row_revision=expected_row_revision,
        )
    return FeatureFieldOverrideCommand(
        feature_id=str(row["o_feature_id"]),
        row_revision=int(row["o_row_revision"]),
        command_id=int(row["o_command_id"]),
        applied_field_count=int(row["o_applied_field_count"]),
    )


async def create_admin_feature_with_field_overrides(
    session: AsyncSession,
    *,
    feature_id: str,
    payload: Mapping[str, Any],
    lifecycle_state: str,
    publication_state: str,
    quality_state: str,
    reason_code: str,
    operator: str,
    command_id: int,
) -> FeatureFieldOverrideCommand:
    """user-created Feature를 initial state와 explicit field overrides로 생성한다.

    core initial insert는 identity/subtype 생성에만 쓰고, operator-owned business
    fields는 즉시 registry command로 다시 materialize한다. 따라서 provider base가
    없는 user-created row도 field별 ownership을 남긴다.
    """

    _validated_operator_and_reason_code(operator=operator, reason_code=reason_code)
    if command_id < 1:
        raise ValueError("feature create에는 open domain command receipt가 필요합니다.")
    kind = str(payload["kind"])
    if kind not in {"place", "event"}:
        raise ValueError("admin create는 place 또는 event kind만 지원합니다.")
    initial_payload = {
        key: value
        for key, value in payload.items()
        if key != "detail"
    }
    initial_payload["feature_id"] = feature_id
    initial_payload["feature_uuid"] = candidate_feature_uuid()
    try:
        inserted = (
            await session.execute(
                text(_CREATE_FEATURE_WITH_INITIAL_STATE_SQL),
                {
                    "feature_payload": json.dumps(
                        initial_payload, ensure_ascii=False, default=str
                    ),
                    "lifecycle_state": lifecycle_state,
                    "publication_state": publication_state,
                    "quality_state": quality_state,
                    "state_context": json.dumps(
                        {
                            "transition_kind": "initial",
                            "reason_code": "admin_feature_create",
                            "principal": operator,
                            "causation_ref": f"domain-command:{command_id}",
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_field_override_procedure_error(
            error,
            feature_id=feature_id,
            expected_row_revision=1,
        )
    if not bool(inserted["o_inserted"]):
        raise FeatureFieldOverrideValidationError(
            f"feature가 이미 존재합니다: {feature_id!r}"
        )
    feature_uuid = str(inserted["o_feature_uuid"])
    verify_feature_uuid(
        feature_id,
        feature_uuid,
        sent_feature_uuid=str(initial_payload["feature_uuid"]),
        inserted=True,
    )
    await write_subtype(
        session,
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        detail=payload.get("detail"),
    )
    values, geometry_wkt = _override_payload_for_change(
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        payload=dict(payload),
        include_required_create_fields=True,
    )
    command = await author_admin_feature_field_overrides(
        session,
        feature_id,
        expected_row_revision=int(inserted["o_row_revision"]),
        reason_code=reason_code,
        operator=operator,
        command_id=command_id,
        values=values,
        geometry_wkt=geometry_wkt,
    )
    return FeatureFieldOverrideCommand(
        feature_id=command.feature_id,
        row_revision=command.row_revision,
        command_id=command.command_id,
        applied_field_count=command.applied_field_count,
        feature_uuid=feature_uuid,
    )


async def patch_admin_feature_with_field_overrides(
    session: AsyncSession,
    feature_id: str,
    *,
    payload: Mapping[str, Any],
    expected_row_revision: int,
    reason_code: str,
    operator: str,
    command_id: int,
) -> FeatureFieldOverrideCommand:
    """기존 Feature의 admin patch를 field registry command로만 materialize한다."""

    state = await _state_for_conflict(session, feature_id)
    if state is None:
        raise FeatureFieldOverrideNotFound(f"feature 없음: {feature_id!r}")
    if int(state["row_revision"]) != expected_row_revision:
        raise FeatureFieldOverridePreconditionFailed(
            feature_id=feature_id,
            expected=expected_row_revision,
        )
    values, geometry_wkt = _override_payload_for_change(
        feature_id=feature_id,
        feature_uuid=str(state["feature_uuid"]),
        kind=str(state["kind"]),
        payload=dict(payload),
        include_required_create_fields=False,
    )
    return await author_admin_feature_field_overrides(
        session,
        feature_id,
        expected_row_revision=expected_row_revision,
        reason_code=reason_code,
        operator=operator,
        command_id=command_id,
        values=values,
        geometry_wkt=geometry_wkt,
    )


# feature_uuid는 T-VN-32C(0083) 정본 generator — 비파생 UUIDv7 후보를 명시
# INSERT하고 fill 트리거는 raw SQL 안전망으로 유지한다. ON CONFLICT DO NOTHING
# 이므로 RETURNING 행 존재 = 신규 insert — 관측값은 보낸 후보와 같아야 한다
# (generator 이원화 fail-close, 적대 리뷰 1 M1).
# T-VN-35(0086): core에 ``detail``/``geom`` 컬럼이 없다. kind별 값은
# subtype(``feature_places``/``feature_events``)이 **유일한 정본**이며 core
# INSERT 직후 같은 트랜잭션에서 ``feature_subtype.write_subtype``이 쓴다. admin mutation은
# ``kind IN ('place','event')``(API Literal)이라 geometry는 애초에 대상이
# 아니다 — geometry가 필수인 kind는 route/area뿐이고 그 값은 subtype 컬럼에
# NOT NULL로 산다.
_CREATE_FEATURE_WITH_INITIAL_STATE_SQL: Final[str] = """
CALL feature.create_feature_with_initial_state(
    CAST(:feature_payload AS jsonb),
    CAST(:lifecycle_state AS text),
    CAST(:publication_state AS text),
    CAST(:quality_state AS text),
    CAST(:state_context AS jsonb),
    NULL, NULL, NULL, NULL
)
"""

_GET_FEATURE_ROW_REVISION_SQL: Final[str] = """
SELECT row_revision
FROM feature.features
WHERE feature_id = :feature_id
"""

_ADMIN_FEATURE_CARD_TARGET_EXISTS_SQL: Final[str] = """
SELECT EXISTS (
  SELECT 1
  FROM feature.features
  WHERE feature_id = :feature_id
)
"""

_CORE_OVERRIDE_PATHS: Final[dict[str, str]] = {
    "name": "core.name",
    "category": "core.category",
    "address": "core.address",
    "legal_dong_code": "core.legal_dong_code",
    "road_name_code": "core.road_name_code",
    "road_address_management_no": "core.road_address_management_no",
    "admin_dong_code": "core.admin_dong_code",
    "sido_code": "core.sido_code",
    "sigungu_code": "core.sigungu_code",
    "urls": "core.urls",
    "marker_icon": "core.marker_icon",
    "marker_color": "core.marker_color",
    "parent_feature_id": "core.parent_feature_id",
    "sibling_group_id": "core.sibling_group_id",
    "raw_refs": "core.raw_refs",
}
_SUBTYPE_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset(
    {"feature_id", "feature_uuid", "kind"}
)
_SUBTYPE_JSON_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "business_hours",
        "facility_info",
        "reviews_link",
        "payload",
        "opening_hours",
    }
)
_NON_OPERATOR_WRITABLE_SUBTYPE_FIELDS: Final[dict[str, frozenset[str]]] = {
    # registry의 ``operator_writable=false``와 같은 allow-list를 writer에서도
    # 명시한다. provider raw/source identity를 admin detail 통교체에 섞어
    # 조용히 덮는 것은 허용하지 않는다.
    "place": frozenset({"payload"}),
    "event": frozenset({"content_id", "content_type_id", "payload"}),
    "notice": frozenset({"payload"}),
    "route": frozenset({"geometry_source", "payload"}),
    "area": frozenset({"boundary_source", "payload"}),
}


def _override_payload_for_change(
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    payload: Mapping[str, Any],
    include_required_create_fields: bool,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """승인된 user request를 registry-keyed field input으로 바꾼다.

    ``detail``은 부분 JSON merge가 아니라 typed subtype 전체 교체다. 따라서
    detail이 들어온 경우 subtype의 모든 column을 override로 남겨, 이후 provider
    patch가 운영자가 명시하지 않은 path만 materialize할 수 있다.
    """

    values: dict[str, Any] = {}
    geometry_wkt: dict[str, str | None] = {}
    for payload_key, field_path in _CORE_OVERRIDE_PATHS.items():
        if payload_key in payload:
            values[field_path] = payload[payload_key]

    if "coord" in payload:
        coord = payload["coord"]
        if coord is None:
            geometry_wkt["core.coord"] = None
            values["core.coord_precision_digits"] = None
        elif isinstance(coord, Mapping):
            lon = coord.get("lon")
            lat = coord.get("lat")
            if lon is None or lat is None:
                raise ValueError("coord override에는 lon과 lat이 모두 필요합니다.")
            geometry_wkt["core.coord"] = f"POINT({lon} {lat})"
            values["core.coord_precision_digits"] = payload.get(
                "coord_precision_digits", 6
            )
        else:
            raise ValueError("coord override는 object 또는 null이어야 합니다.")
    elif "coord_precision_digits" in payload:
        raise ValueError("coord_precision_digits는 coord와 함께만 바꿀 수 있습니다.")

    if include_required_create_fields:
        # create boundary는 네 core field의 존재를 이미 검증한다. user-created
        # Feature에도 provider base와 독립적인 per-field ownership을 남긴다.
        for payload_key in ("name", "category", "marker_icon", "marker_color"):
            values[_CORE_OVERRIDE_PATHS[payload_key]] = payload[payload_key]

    # 생성 때 detail을 생략하면 ``write_subtype``가 kind DTO의 안전한 기본값만
    # materialize한다. 그 기본값까지 operator override로 만들면 (특히 nullable
    # subtype field의 JSON ``null``) registry type fence를 통과하지 못하고, 이후
    # provider가 실제 base를 제공할 길도 막는다. 명시된 detail만 ownership receipt로
    # 남긴다.
    if "detail" in payload:
        detail_input = payload.get("detail")
        if isinstance(detail_input, Mapping):
            forbidden = sorted(
                set(detail_input)
                & _NON_OPERATOR_WRITABLE_SUBTYPE_FIELDS.get(kind, frozenset())
            )
            if forbidden:
                raise ValueError(
                    "operator가 provider-owned detail field를 바꿀 수 없습니다: "
                    + ", ".join(forbidden)
                )
        params = subtype_params(
            feature_id=feature_id,
            feature_uuid=feature_uuid,
            kind=kind,
            detail=payload.get("detail"),
        )
        if params is not None:
            for column, raw_value in params.items():
                if column in _SUBTYPE_IDENTITY_FIELDS:
                    continue
                if column in _NON_OPERATOR_WRITABLE_SUBTYPE_FIELDS.get(
                    kind, frozenset()
                ):
                    continue
                value = raw_value
                if column in _SUBTYPE_JSON_FIELDS and isinstance(value, str):
                    value = json.loads(value)
                values[f"{kind}.{column}"] = value

    if not values and not geometry_wkt:
        raise ValueError("field override에는 최소 하나의 실제 변경 field가 필요합니다.")
    return values, geometry_wkt


async def _state_for_conflict(
    session: AsyncSession, feature_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT feature_id, CAST(feature_uuid AS text) AS feature_uuid, kind,
                       lifecycle_state, publication_state, quality_state, row_revision
                FROM feature.features
                WHERE feature_id = :feature_id
                FOR UPDATE
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


async def get_feature_row_revision(
    session: AsyncSession, feature_id: str
) -> int | None:
    """feature의 현재 server-owned ``row_revision``. 없으면 None (T-VN-13 ETag)."""
    revision = (
        await session.execute(
            text(_GET_FEATURE_ROW_REVISION_SQL),
            {"feature_id": feature_id},
        )
    ).scalar_one_or_none()
    return int(revision) if revision is not None else None


async def admin_feature_card_target_exists(
    session: AsyncSession, feature_id: str
) -> bool:
    """Admin weather/price card의 target 존재를 admin-any로 검사한다."""

    return bool(
        (
            await session.execute(
                text(_ADMIN_FEATURE_CARD_TARGET_EXISTS_SQL),
                {"feature_id": feature_id},
            )
        ).scalar_one()
    )


_DEDUP_REVIEW_SQL: Final[str] = """
WITH reviews AS MATERIALIZED (
    SELECT
        q.review_id,
        q.status,
        q.total_score,
        q.name_score,
        q.spatial_score,
        q.category_score,
        q.feature_id_a,
        q.feature_id_b,
        q.decision_reason,
        q.reviewed_by,
        q.reviewed_at,
        q.created_at
    FROM ops.dedup_review_queue AS q
    WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.total_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.total_score <= CAST(:max_score AS numeric)
      )
      AND (
        CAST(:cursor_review_id AS uuid) IS NULL
        OR (q.total_score, q.review_id)
           < (CAST(:cursor_score AS numeric), CAST(:cursor_review_id AS uuid))
      )
    ORDER BY q.total_score DESC, q.review_id DESC
),
expanded AS (
    SELECT
        r.*,
        CAST(fa.feature_uuid AS text) AS feature_uuid_a,
        fa.name AS name_a,
        fa.kind AS kind_a,
        fa.category AS category_a,
        x_extension.ST_X(fa.coord) AS lon_a,
        x_extension.ST_Y(fa.coord) AS lat_a,
        psa.provider AS provider_a,
        psa.dataset_key AS dataset_key_a,
        CAST(fb.feature_uuid AS text) AS feature_uuid_b,
        fb.name AS name_b,
        fb.kind AS kind_b,
        fb.category AS category_b,
        x_extension.ST_X(fb.coord) AS lon_b,
        x_extension.ST_Y(fb.coord) AS lat_b,
        psb.provider AS provider_b,
        psb.dataset_key AS dataset_key_b,
        CASE
            WHEN fa.coord_5179 IS NULL OR fb.coord_5179 IS NULL THEN NULL
            ELSE x_extension.ST_Distance(fa.coord_5179, fb.coord_5179)::double precision
        END AS distance_m
    FROM reviews AS r
    JOIN feature.features AS fa ON fa.feature_id = r.feature_id_a
    JOIN feature.features AS fb ON fb.feature_id = r.feature_id_b
    LEFT JOIN LATERAL (
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = fa.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS psa ON TRUE
    LEFT JOIN LATERAL (
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = fb.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS psb ON TRUE
)
SELECT *
FROM expanded
WHERE (
    CAST(:q_like AS text) IS NULL
    OR feature_id_a ILIKE CAST(:q_like AS text)
    OR feature_id_b ILIKE CAST(:q_like AS text)
    OR name_a ILIKE CAST(:q_like AS text)
    OR name_b ILIKE CAST(:q_like AS text)
)
  AND (
    CAST(:providers AS text[]) IS NULL
    OR provider_a = ANY(CAST(:providers AS text[]))
    OR provider_b = ANY(CAST(:providers AS text[]))
  )
  AND (
    CAST(:dataset_keys AS text[]) IS NULL
    OR dataset_key_a = ANY(CAST(:dataset_keys AS text[]))
    OR dataset_key_b = ANY(CAST(:dataset_keys AS text[]))
  )
  AND (
    CAST(:kinds AS text[]) IS NULL
    OR kind_a = ANY(CAST(:kinds AS text[]))
    OR kind_b = ANY(CAST(:kinds AS text[]))
  )
  AND (
    CAST(:categories AS text[]) IS NULL
    OR category_a = ANY(CAST(:categories AS text[]))
    OR category_b = ANY(CAST(:categories AS text[]))
  )
ORDER BY total_score DESC, review_id DESC
LIMIT :limit_plus_one
"""


_DEDUP_REVIEW_COUNT_SQL: Final[str] = """
WITH reviews AS MATERIALIZED (
    SELECT
        q.review_id,
        q.feature_id_a,
        q.feature_id_b
    FROM ops.dedup_review_queue AS q
    WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.total_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.total_score <= CAST(:max_score AS numeric)
      )
),
expanded AS (
    SELECT
        r.*,
        fa.name AS name_a,
        fa.kind AS kind_a,
        fa.category AS category_a,
        psa.provider AS provider_a,
        psa.dataset_key AS dataset_key_a,
        fb.name AS name_b,
        fb.kind AS kind_b,
        fb.category AS category_b,
        psb.provider AS provider_b,
        psb.dataset_key AS dataset_key_b
    FROM reviews AS r
    JOIN feature.features AS fa ON fa.feature_id = r.feature_id_a
    JOIN feature.features AS fb ON fb.feature_id = r.feature_id_b
    LEFT JOIN LATERAL (
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = fa.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS psa ON TRUE
    LEFT JOIN LATERAL (
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_entity_key = se.source_entity_key
         AND sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = fb.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS psb ON TRUE
)
SELECT count(*)::integer AS total_count
FROM expanded
WHERE (
    CAST(:q_like AS text) IS NULL
    OR feature_id_a ILIKE CAST(:q_like AS text)
    OR feature_id_b ILIKE CAST(:q_like AS text)
    OR name_a ILIKE CAST(:q_like AS text)
    OR name_b ILIKE CAST(:q_like AS text)
)
  AND (
    CAST(:providers AS text[]) IS NULL
    OR provider_a = ANY(CAST(:providers AS text[]))
    OR provider_b = ANY(CAST(:providers AS text[]))
  )
  AND (
    CAST(:dataset_keys AS text[]) IS NULL
    OR dataset_key_a = ANY(CAST(:dataset_keys AS text[]))
    OR dataset_key_b = ANY(CAST(:dataset_keys AS text[]))
  )
  AND (
    CAST(:kinds AS text[]) IS NULL
    OR kind_a = ANY(CAST(:kinds AS text[]))
    OR kind_b = ANY(CAST(:kinds AS text[]))
  )
  AND (
    CAST(:categories AS text[]) IS NULL
    OR category_a = ANY(CAST(:categories AS text[]))
    OR category_b = ANY(CAST(:categories AS text[]))
  )
"""


_DEDUP_REVIEW_FAST_COUNT_SQL: Final[str] = """
SELECT count(*)::integer AS total_count
FROM ops.dedup_review_queue AS q
WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
  AND (
    CAST(:min_score AS numeric) IS NULL
    OR q.total_score >= CAST(:min_score AS numeric)
  )
  AND (
    CAST(:max_score AS numeric) IS NULL
    OR q.total_score <= CAST(:max_score AS numeric)
  )
"""


_DEDUP_REVIEW_DETAIL_SQL: Final[str] = """
SELECT
    q.review_id::text AS review_id,
    q.status,
    q.total_score,
    q.name_score,
    q.spatial_score,
    q.category_score,
    q.feature_id_a,
    q.feature_id_b,
    q.decision_reason,
    q.reviewed_by,
    q.reviewed_at,
    q.created_at,
    CASE
        WHEN fa.coord_5179 IS NULL OR fb.coord_5179 IS NULL THEN NULL
        ELSE x_extension.ST_Distance(fa.coord_5179, fb.coord_5179)::double precision
    END AS distance_m
FROM ops.dedup_review_queue AS q
JOIN feature.features AS fa ON fa.feature_id = q.feature_id_a
JOIN feature.features AS fb ON fb.feature_id = q.feature_id_b
WHERE q.review_id = :review_id
"""


def _dedup_review_count_sql(params: Mapping[str, Any]) -> str:
    """필터 확장이 필요 없으면 queue table만 세는 count SQL을 고른다."""

    if all(
        params[key] is None
        for key in ("providers", "dataset_keys", "kinds", "categories", "q_like")
    ):
        return _DEDUP_REVIEW_FAST_COUNT_SQL
    return _DEDUP_REVIEW_COUNT_SQL


def _score(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _dedup_feature(row: Any, suffix: str) -> DedupFeatureSummary:
    feature_uuid = row[f"feature_uuid_{suffix}"]
    return DedupFeatureSummary(
        feature_id=str(row[f"feature_id_{suffix}"]),
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
        name=str(row[f"name_{suffix}"]),
        kind=str(row[f"kind_{suffix}"]),
        category=str(row[f"category_{suffix}"]),
        lon=float(row[f"lon_{suffix}"]) if row[f"lon_{suffix}"] is not None else None,
        lat=float(row[f"lat_{suffix}"]) if row[f"lat_{suffix}"] is not None else None,
        provider=row[f"provider_{suffix}"],
        dataset_key=row[f"dataset_key_{suffix}"],
    )


def _dedup_review_row(row: Any) -> DedupReviewRow:
    return DedupReviewRow(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        total_score=_score(row["total_score"]),
        name_score=_score(row["name_score"]),
        spatial_score=_score(row["spatial_score"]),
        category_score=_score(row["category_score"]),
        feature_a=_dedup_feature(row, "a"),
        feature_b=_dedup_feature(row, "b"),
        distance_m=(
            float(row["distance_m"]) if row["distance_m"] is not None else None
        ),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
    )


async def list_dedup_reviews(
    session: AsyncSession,
    *,
    statuses: Sequence[str] | None = ("pending",),
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    q: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> DedupReviewPage:
    """Dedup review 목록을 점수 내림차순 keyset cursor로 조회한다.

    OFFSET이 아니라 ``(total_score DESC, review_id DESC)`` keyset으로 페이지 경계를
    고정해 페이지 사이 삽입·삭제에도 중복·누락이 없다. cursor는 필터 fingerprint를 실어
    필터가 바뀌면 거부한다(``_review_cursor_params``). ``total_count``는 페이지네이션과
    독립인 전체 필터 집합의 건수다.
    """
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    params: dict[str, Any] = {
        "statuses": _normalize_values(statuses),
        "providers": _normalize_values(providers),
        "dataset_keys": _normalize_values(dataset_keys),
        "kinds": _normalize_values(kinds),
        "categories": _normalize_values(categories),
        "min_score": min_score,
        "max_score": max_score,
        "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
    }
    fingerprint = _review_filter_fingerprint(
        "dedup_review",
        {
            "statuses": params["statuses"],
            "providers": params["providers"],
            "dataset_keys": params["dataset_keys"],
            "kinds": params["kinds"],
            "categories": params["categories"],
            "min_score": None if min_score is None else str(min_score),
            "max_score": None if max_score is None else str(max_score),
            "q": normalized_q,
            "page_size": effective_limit,
        },
    )
    cursor_params = _review_cursor_params(
        cursor, kind="dedup_review", fingerprint=fingerprint
    )
    total_count = int(
        (
            await session.execute(
                text(_dedup_review_count_sql(params)),
                params,
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            text(_DEDUP_REVIEW_SQL),
            {
                **params,
                **cursor_params,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).mappings().all()
    has_more = len(rows) > effective_limit
    page_rows = rows[:effective_limit]
    items = tuple(_dedup_review_row(row) for row in page_rows)
    next_cursor = (
        _encode_review_cursor(
            kind="dedup_review",
            fingerprint=fingerprint,
            review_id=str(page_rows[-1]["review_id"]),
            score=str(page_rows[-1]["total_score"]),
        )
        if has_more and page_rows
        else None
    )
    return DedupReviewPage(
        items=items,
        total_count=total_count,
        next_cursor=next_cursor,
    )


async def get_dedup_review_detail(
    session: AsyncSession, review_id: str
) -> DedupReviewDetail | None:
    """Dedup review 상세 비교 데이터를 조회한다."""
    row = (
        await session.execute(text(_DEDUP_REVIEW_DETAIL_SQL), {"review_id": review_id})
    ).mappings().first()
    if row is None:
        return None

    feature_a = await _get_review_feature_detail(session, str(row["feature_id_a"]))
    feature_b = await _get_review_feature_detail(session, str(row["feature_id_b"]))
    if feature_a is None or feature_b is None:
        return None

    return DedupReviewDetail(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        total_score=_score(row["total_score"]),
        name_score=_score(row["name_score"]),
        spatial_score=_score(row["spatial_score"]),
        category_score=_score(row["category_score"]),
        distance_m=_float_or_none(row["distance_m"]),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
        feature_a=feature_a,
        feature_b=feature_b,
    )


_SET_DEDUP_DECISION_SQL: Final[str] = """
UPDATE ops.dedup_review_queue
SET status = :decision,
    reviewed_at = now(),
    reviewed_by = :reviewed_by,
    decision_reason = COALESCE(:decision_reason, decision_reason)
WHERE review_id = :review_id
  AND status = 'pending'
  AND :decision = ANY(CAST(ARRAY['accepted','rejected','ignored'] AS text[]))
RETURNING review_id::text
"""

_SELECT_DEDUP_PAIR_SQL: Final[str] = """
SELECT feature_id_a, feature_id_b, total_score, status
FROM ops.dedup_review_queue
WHERE review_id = :review_id
FOR UPDATE
"""


async def set_dedup_review_decision(
    session: AsyncSession,
    review_id: str,
    *,
    decision: DedupDecision,
    reviewed_by: str | None = None,
    decision_reason: str | None = None,
) -> bool:
    """pending dedup review를 accepted/rejected/ignored로 전이한다."""
    row = (
        await session.execute(
            text(_SET_DEDUP_DECISION_SQL),
            {
                "review_id": review_id,
                "decision": decision,
                "reviewed_by": reviewed_by,
                "decision_reason": decision_reason,
            },
        )
    ).first()
    return row is not None


async def merge_dedup_review(
    session: AsyncSession,
    review_id: str,
    *,
    master_feature_id: str | None = None,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """dedup review를 병합한다. ``master_feature_id``가 없으면 기존 자동 선정."""
    if master_feature_id is None:
        return await merge_from_review(
            session, review_id, merged_by=merged_by, reason=reason
        )

    row = (
        await session.execute(text(_SELECT_DEDUP_PAIR_SQL), {"review_id": review_id})
    ).one_or_none()
    if row is None:
        raise MergeNotFoundError(f"review_id 없음 — {review_id!r}")
    if row.status != "pending":
        raise MergeConflictError(
            f"이미 검토된 후보(status={row.status!r}) — {review_id!r}"
        )
    if master_feature_id == row.feature_id_a:
        loser_id = row.feature_id_b
    elif master_feature_id == row.feature_id_b:
        loser_id = row.feature_id_a
    else:
        raise MergeConflictError(
            "master_feature_id가 review 후보 쌍에 없음 — "
            f"{master_feature_id!r}"
        )
    return await apply_feature_merge(
        session,
        master_id=master_feature_id,
        loser_id=loser_id,
        score=float(row.total_score) if row.total_score is not None else None,
        review_id=review_id,
        merged_by=merged_by,
        reason=reason,
    )


# =============================================================================
# 축제 enrichment review (T-RV-52c) — ops.enrichment_review_queue 조회
# =============================================================================


@dataclass(frozen=True)
class EnrichmentReviewRow:
    """``GET /admin/enrichment-review`` item.

    enrichment은 두 번째 feature/병합이 없어 dedup보다 단순하다 — 1차(target) feature를
    join해 표시하고, source(2차, visitkorea)는 큐에 보관된 식별/이름만 노출한다.
    """

    review_id: str
    status: str
    name_score: float
    target_feature_id: str
    target_name: str
    target_kind: str | None
    target_category: str | None
    target_lon: float | None
    target_lat: float | None
    target_start_date: str | None
    target_end_date: str | None
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    source_lon: float | None
    source_lat: float | None
    source_start_date: str | None
    source_end_date: str | None
    distance_m: float | None
    spatial_score: float | None
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    # T-VN-32C UUID 정본 병행 노출(additive) — target join(f) 산출.
    target_feature_uuid: str | None = None


@dataclass(frozen=True)
class EnrichmentReviewPage:
    """Enrichment review keyset page."""

    items: tuple[EnrichmentReviewRow, ...]
    total_count: int
    next_cursor: str | None = None


@dataclass(frozen=True)
class EnrichmentReviewDetail:
    """Enrichment review 상세 비교 aggregate."""

    review_id: str
    status: str
    name_score: float
    target_feature_id: str
    target_name: str
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    source_lon: float | None
    source_lat: float | None
    target_start_date: str | None
    target_end_date: str | None
    source_start_date: str | None
    source_end_date: str | None
    distance_m: float | None
    spatial_score: float | None
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    target: ReviewFeatureDetail
    source: ReviewSourceDetail
    target_detail_available: bool
    default_detail_source: str
    # T-VN-32C UUID 정본 병행 노출(additive) — target join(f) 산출.
    target_feature_uuid: str | None = None


_ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER: Final[str] = """
    WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
"""

_ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER: Final[str] = """
    WHERE q.status = ANY(CAST(:statuses AS text[]))
"""

_ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER: Final[str] = """
    WHERE q.status = CAST(:status AS text)
"""

_ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER: Final[str] = """
      AND (
        CAST(:providers AS text[]) IS NULL
        OR pd.provider = ANY(CAST(:providers AS text[]))
      )
"""

_ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER: Final[str] = """
      AND pd.provider = ANY(CAST(:providers AS text[]))
"""

_ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER: Final[str] = """
      AND pd.provider = CAST(:provider AS text)
"""


def _enrichment_review_sql(status_filter: str, provider_filter: str) -> str:
    return f"""
WITH reviews AS MATERIALIZED (
    SELECT
        q.review_id,
        q.status,
        q.name_score,
        q.target_feature_id,
        q.target_name,
        q.source_name,
        q.source_record_key,
        pd.provider AS source_provider,
        pd.dataset_key AS source_dataset_key,
        se.source_entity_type,
        se.source_entity_id,
        sr.raw_data AS source_raw_data,
        q.decision_reason,
        q.reviewed_by,
        q.reviewed_at,
        q.created_at
    FROM ops.enrichment_review_queue AS q
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = q.source_entity_key
    JOIN provider_sync.provider_datasets AS pd
      ON pd.provider_dataset_id = se.provider_dataset_id
    JOIN provider_sync.source_records AS sr
      ON sr.source_entity_key = q.source_entity_key
     AND sr.source_record_key = q.source_record_key
{status_filter.rstrip()}
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.name_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.name_score <= CAST(:max_score AS numeric)
      )
{provider_filter.rstrip()}
      AND (
        CAST(:q_like AS text) IS NULL
        OR q.target_feature_id ILIKE CAST(:q_like AS text)
        OR q.target_name ILIKE CAST(:q_like AS text)
        OR q.source_name ILIKE CAST(:q_like AS text)
        OR se.source_entity_id ILIKE CAST(:q_like AS text)
      )
      AND (
        CAST(:cursor_review_id AS uuid) IS NULL
        OR (q.name_score, q.review_id)
           < (CAST(:cursor_score AS numeric), CAST(:cursor_review_id AS uuid))
      )
    ORDER BY q.name_score DESC, q.review_id DESC
    LIMIT :limit_plus_one
)
SELECT
    q.review_id,
    q.status,
    q.name_score,
    q.target_feature_id,
    CAST(f.feature_uuid AS text) AS target_feature_uuid,
    q.target_name,
    q.source_provider,
    q.source_dataset_key,
    q.source_entity_id,
    q.source_name,
    q.decision_reason,
    q.reviewed_by,
    q.reviewed_at,
    q.created_at,
    f.kind AS target_kind,
    f.category AS target_category,
    x_extension.ST_X(f.coord) AS target_lon,
    x_extension.ST_Y(f.coord) AS target_lat,
    event.starts_on::text AS target_start_date,
    event.ends_on::text AS target_end_date,
    src.source_lon,
    src.source_lat,
    src.source_start_date,
    src.source_end_date,
    dist.distance_m,
    CASE
        WHEN dist.distance_m IS NULL THEN NULL
        WHEN dist.distance_m >= 35000.0 THEN 0.0::double precision
        ELSE (
            exp(-(dist.distance_m / 50.0::double precision))
            * 100.0::double precision
        )::double precision
    END AS spatial_score
FROM reviews AS q
LEFT JOIN feature.features AS f ON f.feature_id = q.target_feature_id
LEFT JOIN feature.feature_events AS event ON event.feature_id = f.feature_id
LEFT JOIN LATERAL (
    SELECT
        CASE
            WHEN raw.source_lon_text ~ '^-?[0-9]+(\\.[0-9]+)?$'
            THEN raw.source_lon_text::double precision
            ELSE NULL
        END AS source_lon,
        CASE
            WHEN raw.source_lat_text ~ '^-?[0-9]+(\\.[0-9]+)?$'
            THEN raw.source_lat_text::double precision
            ELSE NULL
        END AS source_lat,
        COALESCE(
            q.source_raw_data ->> 'event_start_date',
            q.source_raw_data ->> 'eventstartdate',
            q.source_raw_data ->> 'start_date'
        ) AS source_start_date,
        COALESCE(
            q.source_raw_data ->> 'event_end_date',
            q.source_raw_data ->> 'eventenddate',
            q.source_raw_data ->> 'end_date'
        ) AS source_end_date
    FROM (
        SELECT
            NULLIF(
                COALESCE(
                    q.source_raw_data ->> 'map_x',
                    q.source_raw_data ->> 'mapx',
                    q.source_raw_data ->> 'longitude'
                ),
                ''
            ) AS source_lon_text,
            NULLIF(
                COALESCE(
                    q.source_raw_data ->> 'map_y',
                    q.source_raw_data ->> 'mapy',
                    q.source_raw_data ->> 'latitude'
                ),
                ''
            ) AS source_lat_text
    ) AS raw
) AS src ON TRUE
LEFT JOIN LATERAL (
    SELECT
        CASE
            WHEN f.coord_5179 IS NULL
              OR src.source_lon IS NULL
              OR src.source_lat IS NULL
            THEN NULL
            ELSE x_extension.ST_Distance(
                f.coord_5179,
                x_extension.ST_Transform(
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(src.source_lon, src.source_lat),
                        4326
                    ),
                    5179
                )
            )::double precision
        END AS distance_m
) AS dist ON TRUE
ORDER BY q.name_score DESC, q.review_id DESC
LIMIT :limit_plus_one
"""


def _enrichment_review_count_sql(status_filter: str, provider_filter: str) -> str:
    return f"""
SELECT count(*)::integer AS total_count
FROM ops.enrichment_review_queue AS q
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = q.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
{status_filter.rstrip()}
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.name_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.name_score <= CAST(:max_score AS numeric)
      )
{provider_filter.rstrip()}
      AND (
        CAST(:q_like AS text) IS NULL
        OR q.target_feature_id ILIKE CAST(:q_like AS text)
        OR q.target_name ILIKE CAST(:q_like AS text)
        OR q.source_name ILIKE CAST(:q_like AS text)
        OR se.source_entity_id ILIKE CAST(:q_like AS text)
      )
"""


_ENRICHMENT_REVIEW_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER
)
_ENRICHMENT_REVIEW_STATUS_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER
)
_ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
    _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER,
    _ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_COUNT_SQL: Final[str] = _enrichment_review_count_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_STATUS_COUNT_SQL: Final[str] = _enrichment_review_count_sql(
    _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_PROVIDER_COUNT_SQL: Final[str] = _enrichment_review_count_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_STATUS_PROVIDER_COUNT_SQL: Final[str] = (
    _enrichment_review_count_sql(
        _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
        _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER,
    )
)
_ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_COUNT_SQL: Final[str] = (
    _enrichment_review_count_sql(
        _ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER,
        _ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER,
    )
)

_ENRICHMENT_REVIEW_DETAIL_SQL: Final[str] = """
SELECT
    q.review_id::text AS review_id,
    q.status,
    q.name_score,
    q.target_feature_id,
    CAST(f.feature_uuid AS text) AS target_feature_uuid,
    q.target_name,
    q.source_record_key,
    pd.provider AS source_provider,
    pd.dataset_key AS source_dataset_key,
    se.source_entity_type,
    se.source_entity_id,
    q.source_name,
    sr.raw_payload_hash,
    sr.raw_data,
    sr.fetched_at,
    sr.imported_at,
    q.decision_reason,
    q.reviewed_by,
    q.reviewed_at,
    q.created_at,
    event.starts_on::text AS target_start_date,
    event.ends_on::text AS target_end_date,
    src.source_lon,
    src.source_lat,
    src.source_start_date,
    src.source_end_date,
    dist.distance_m,
    CASE
        WHEN dist.distance_m IS NULL THEN NULL
        WHEN dist.distance_m >= 35000.0 THEN 0.0::double precision
        ELSE (
            exp(-(dist.distance_m / 50.0::double precision))
            * 100.0::double precision
        )::double precision
    END AS spatial_score
FROM ops.enrichment_review_queue AS q
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = q.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
JOIN provider_sync.source_records AS sr
  ON sr.source_entity_key = q.source_entity_key
 AND sr.source_record_key = q.source_record_key
LEFT JOIN feature.features AS f ON f.feature_id = q.target_feature_id
LEFT JOIN feature.feature_events AS event ON event.feature_id = f.feature_id
LEFT JOIN LATERAL (
    SELECT
        CASE
            WHEN raw.source_lon_text ~ '^-?[0-9]+(\\.[0-9]+)?$'
            THEN raw.source_lon_text::double precision
            ELSE NULL
        END AS source_lon,
        CASE
            WHEN raw.source_lat_text ~ '^-?[0-9]+(\\.[0-9]+)?$'
            THEN raw.source_lat_text::double precision
            ELSE NULL
        END AS source_lat,
        COALESCE(
            sr.raw_data ->> 'event_start_date',
            sr.raw_data ->> 'eventstartdate',
            sr.raw_data ->> 'start_date'
        ) AS source_start_date,
        COALESCE(
            sr.raw_data ->> 'event_end_date',
            sr.raw_data ->> 'eventenddate',
            sr.raw_data ->> 'end_date'
        ) AS source_end_date
    FROM (
        SELECT
            NULLIF(
                COALESCE(
                    sr.raw_data ->> 'map_x',
                    sr.raw_data ->> 'mapx',
                    sr.raw_data ->> 'longitude'
                ),
                ''
            ) AS source_lon_text,
            NULLIF(
                COALESCE(
                    sr.raw_data ->> 'map_y',
                    sr.raw_data ->> 'mapy',
                    sr.raw_data ->> 'latitude'
                ),
                ''
            ) AS source_lat_text
    ) AS raw
) AS src ON TRUE
LEFT JOIN LATERAL (
    SELECT
        CASE
            WHEN f.coord_5179 IS NULL
              OR src.source_lon IS NULL
              OR src.source_lat IS NULL
            THEN NULL
            ELSE x_extension.ST_Distance(
                f.coord_5179,
                x_extension.ST_Transform(
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(src.source_lon, src.source_lat),
                        4326
                    ),
                    5179
                )
            )::double precision
        END AS distance_m
) AS dist ON TRUE
WHERE q.review_id = :review_id
"""


def _has_review_detail(value: dict[str, Any]) -> bool:
    return any(item not in (None, "", [], {}) for item in value.values())


def _enrichment_review_row(row: Any) -> EnrichmentReviewRow:
    target_feature_uuid = row["target_feature_uuid"]
    return EnrichmentReviewRow(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        name_score=_score(row["name_score"]),
        target_feature_id=str(row["target_feature_id"]),
        target_feature_uuid=(
            str(target_feature_uuid) if target_feature_uuid is not None else None
        ),
        target_name=str(row["target_name"]),
        target_kind=row["target_kind"],
        target_category=row["target_category"],
        target_lon=(
            float(row["target_lon"]) if row["target_lon"] is not None else None
        ),
        target_lat=(
            float(row["target_lat"]) if row["target_lat"] is not None else None
        ),
        target_start_date=row["target_start_date"],
        target_end_date=row["target_end_date"],
        source_provider=str(row["source_provider"]),
        source_dataset_key=str(row["source_dataset_key"]),
        source_entity_id=str(row["source_entity_id"]),
        source_name=str(row["source_name"]),
        source_lon=(
            float(row["source_lon"]) if row["source_lon"] is not None else None
        ),
        source_lat=(
            float(row["source_lat"]) if row["source_lat"] is not None else None
        ),
        source_start_date=row["source_start_date"],
        source_end_date=row["source_end_date"],
        distance_m=(
            float(row["distance_m"]) if row["distance_m"] is not None else None
        ),
        spatial_score=(
            float(row["spatial_score"]) if row["spatial_score"] is not None else None
        ),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
    )


async def list_enrichment_reviews(
    session: AsyncSession,
    *,
    statuses: Sequence[str] | None = ("pending",),
    providers: Sequence[str] | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    q: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> EnrichmentReviewPage:
    """축제 enrichment review 목록을 name_score 내림차순 keyset cursor로 조회한다.

    ``(name_score DESC, review_id DESC)`` keyset으로 페이지 경계를 고정한다(OFFSET 미사용).
    cursor는 필터 fingerprint를 실어 필터가 바뀌면 거부한다. SQL variant 선택은 내부
    최적화일 뿐 fingerprint는 논리 필터 집합으로만 계산해 variant와 무관하게 안정적이다.
    """
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    status_values = _normalize_values(statuses)
    provider_values = _normalize_values(providers)
    status_value = (
        status_values[0] if status_values and len(status_values) == 1 else None
    )
    provider_value = (
        provider_values[0] if provider_values and len(provider_values) == 1 else None
    )
    review_sql = _ENRICHMENT_REVIEW_SQL
    count_sql = _ENRICHMENT_REVIEW_COUNT_SQL
    if status_value is not None and provider_value is not None:
        review_sql = _ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL
        count_sql = _ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_COUNT_SQL
    elif status_values is not None and provider_values is not None:
        review_sql = _ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL
        count_sql = _ENRICHMENT_REVIEW_STATUS_PROVIDER_COUNT_SQL
    elif status_values is not None:
        review_sql = _ENRICHMENT_REVIEW_STATUS_SQL
        count_sql = _ENRICHMENT_REVIEW_STATUS_COUNT_SQL
    elif provider_values is not None:
        review_sql = _ENRICHMENT_REVIEW_PROVIDER_SQL
        count_sql = _ENRICHMENT_REVIEW_PROVIDER_COUNT_SQL
    params: dict[str, Any] = {
        "statuses": status_values,
        "status": status_value,
        "providers": provider_values,
        "provider": provider_value,
        "min_score": min_score,
        "max_score": max_score,
        "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
    }
    fingerprint = _review_filter_fingerprint(
        "enrichment_review",
        {
            "statuses": status_values,
            "providers": provider_values,
            "min_score": None if min_score is None else str(min_score),
            "max_score": None if max_score is None else str(max_score),
            "q": normalized_q,
            "page_size": effective_limit,
        },
    )
    cursor_params = _review_cursor_params(
        cursor, kind="enrichment_review", fingerprint=fingerprint
    )
    total_count = int(
        (
            await session.execute(
                text(count_sql),
                params,
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            text(review_sql),
            {
                **params,
                **cursor_params,
                "limit_plus_one": effective_limit + 1,
            },
        )
    ).mappings().all()
    has_more = len(rows) > effective_limit
    page_rows = rows[:effective_limit]
    items = tuple(_enrichment_review_row(row) for row in page_rows)
    next_cursor = (
        _encode_review_cursor(
            kind="enrichment_review",
            fingerprint=fingerprint,
            review_id=str(page_rows[-1]["review_id"]),
            score=str(page_rows[-1]["name_score"]),
        )
        if has_more and page_rows
        else None
    )
    return EnrichmentReviewPage(
        items=items,
        total_count=total_count,
        next_cursor=next_cursor,
    )


async def get_enrichment_review_detail(
    session: AsyncSession, review_id: str
) -> EnrichmentReviewDetail | None:
    """축제 enrichment review 상세 비교 데이터를 조회한다."""
    row = (
        await session.execute(
            text(_ENRICHMENT_REVIEW_DETAIL_SQL),
            {"review_id": review_id},
        )
    ).mappings().first()
    if row is None:
        return None

    target = await _get_review_feature_detail(session, str(row["target_feature_id"]))
    if target is None:
        return None

    source = _review_source_from_queued_row(row)
    target_detail_available = _has_review_detail(target.detail)
    target_feature_uuid = row["target_feature_uuid"]
    return EnrichmentReviewDetail(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        name_score=_score(row["name_score"]),
        target_feature_id=str(row["target_feature_id"]),
        target_feature_uuid=(
            str(target_feature_uuid) if target_feature_uuid is not None else None
        ),
        target_name=str(row["target_name"]),
        source_provider=str(row["source_provider"]),
        source_dataset_key=str(row["source_dataset_key"]),
        source_entity_id=str(row["source_entity_id"]),
        source_name=str(row["source_name"]),
        source_lon=_float_or_none(row["source_lon"]),
        source_lat=_float_or_none(row["source_lat"]),
        target_start_date=row["target_start_date"],
        target_end_date=row["target_end_date"],
        source_start_date=row["source_start_date"],
        source_end_date=row["source_end_date"],
        distance_m=_float_or_none(row["distance_m"]),
        spatial_score=_float_or_none(row["spatial_score"]),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
        target=target,
        source=source,
        target_detail_available=target_detail_available,
        default_detail_source=(
            "target" if target_detail_available else "visitkorea"
        ),
    )
