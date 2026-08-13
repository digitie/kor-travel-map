"""``feature.curated_*`` repository (T-223c-1).

테마형 큐레이션은 ``feature.features``를 복제하지 않는 overlay다. 본 모듈은
raw SQL만 제공하고, HTTP envelope/DTO는 admin 패키지 라우터에서 담당한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

from kortravelmap.infra.feature_projection import (
    TYPED_FEATURE_DETAIL_COLUMNS_SQL,
    typed_feature_detail_joins_sql,
)
from kortravelmap.infra.feature_repo import public_active_notice_filter_sql

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CuratedFeature",
    "CuratedFeaturePage",
    "CuratedSource",
    "CuratedSourceRule",
    "CuratedTheme",
    "CuratedFeatureDetailItem",
    "CuratedFeatureDetailSnapshot",
    "archive_curated_feature",
    "create_curated_feature",
    "create_curated_source",
    "create_curated_source_rule",
    "create_curated_source_rule_command",
    "create_curated_theme",
    "get_curated_feature",
    "get_curated_feature_detail_snapshot",
    "get_curated_source_rule",
    "list_curated_features",
    "list_curated_source_rules",
    "list_curated_sources",
    "list_curated_themes",
    "set_curated_feature_status",
    "update_curated_feature",
    "update_curated_source",
    "update_curated_source_rule",
    "patch_curated_source_rule_command",
    "archive_curated_source_rule_command",
    "update_curated_theme",
]

CursorKind = Literal["curated_features"]

_CURATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"candidate", "curated", "rejected", "archived"}
)
_SELECTION_ORIGINS: Final[frozenset[str]] = frozenset(
    {"source_rule", "admin", "external_api"}
)
_CURATION_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "primary_stop",
        "food_stop",
        "cafe_stop",
        "bookstore_stop",
        "nearby_option",
        "accessibility_support",
        "pet_support",
        "family_support",
        "theme_area_anchor",
    }
)
_REUSE_POLICIES: Final[frozenset[str]] = frozenset(
    {"allowed", "blocked", "manual_review"}
)
_THEME_VISIBILITIES: Final[frozenset[str]] = frozenset(
    {"admin_only", "public"}
)
_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"openapi", "filedata", "standard", "internal", "manual"}
)
_UPDATE_CYCLES: Final[frozenset[str]] = frozenset(
    {"realtime", "daily", "weekly", "monthly", "annual", "one_time", "unknown"}
)
_PROVIDER_STATUSES: Final[frozenset[str]] = frozenset(
    {"implemented", "provider_needed", "manual_only", "deprecated"}
)
_RULE_ACTIONS: Final[frozenset[str]] = frozenset(
    {"candidate", "curated", "ignore"}
)
_TYPED_RULE_ACTIONS: Final[frozenset[str]] = frozenset({"candidate", "ignore"})
_MAX_PAGE_SIZE: Final[int] = 200
_MAX_LIST_LIMIT: Final[int] = 500
_CONCIERGE_PROVIDER: Final[str] = "kor-travel-concierge-youtube"
_CONCIERGE_DATASET_KEY: Final[str] = "youtube_place_candidates"
_PROVIDER_TITLE_SOURCE_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "data.go.kr-standard",
        "python-airkorea-api",
        "python-datagokr-api",
        "python-kasi-api",
        "python-khoa-api",
        "python-kma-api",
        "python-knps-api",
        "python-krairport-api",
        "python-krex-api",
        "python-krforest-api",
        "python-krheritage-api",
        "python-mcst-api",
        "python-mois-api",
        "python-opinet-api",
        "python-visitkorea-api",
    }
)


@dataclass(frozen=True)
class CuratedTheme:
    """``feature.curated_themes`` projection."""

    theme_id: str
    theme_slug: str
    theme_name: str
    theme_description: str
    theme_group: str
    visibility: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    archived_at: datetime | None = None
    owner_kind: str | None = None
    owner_provider_dataset_id: int | None = None


@dataclass(frozen=True)
class CuratedSource:
    """``feature.curated_sources`` projection."""

    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None
    source_kind: str
    license: str | None
    update_cycle: str
    last_source_modified_at: date | None
    last_checked_at: datetime | None
    next_expected_at: date | None
    row_count: int | None
    freshness_note: str | None
    provider_status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    observation_revision: int = 1
    archived_at: datetime | None = None


@dataclass(frozen=True)
class CuratedSourceRule:
    """``feature.curated_source_rules`` projection."""

    rule_id: str
    theme_id: str
    theme_slug: str
    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    place_kind: str | None
    category: str | None
    region_scope: dict[str, Any]
    detail_selector: dict[str, Any] | None
    default_action: str
    priority: int
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: int = 1
    archived_at: datetime | None = None
    owner_kind: str | None = None
    owner_provider_dataset_id: int | None = None


@dataclass(frozen=True)
class CuratedFeature:
    """curated overlay + feature/source/theme projection.

    ``feature_uuid``는 T-VN-32C UUID 정본 병행 노출(additive) — read projection
    전용이며 detail snapshot 물질화 payload에는 넣지 않는다(별도 단계).
    """

    curated_feature_id: str
    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    feature_id: str
    feature_name: str
    feature_category: str
    feature_kind: str
    lon: float | None
    lat: float | None
    sido_code: str | None
    sigungu_code: str | None
    legal_dong_code: str | None
    address: dict[str, Any]
    detail: dict[str, Any]
    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None
    source_record_key: str | None
    curation_status: str
    selection_origin: str
    selected_by: str | None
    selected_at: datetime | None
    rejected_by: str | None
    rejected_at: datetime | None
    rejection_reason: str | None
    rank_score: float
    display_title: str | None
    display_summary: str | None
    curation_relation: str
    reuse_policy: str
    content_version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    feature_uuid: str | None = None


@dataclass(frozen=True)
class CuratedFeaturePage:
    """curated feature keyset page."""

    items: tuple[CuratedFeature, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class CuratedFeatureDetailItem:
    """curated feature detail item."""

    curated_feature_item_id: str
    feature_id: str
    relation: str
    sort_order: int
    day_index: int | None
    memo: str | None
    feature_snapshot: dict[str, Any]
    source_record_key: str | None


@dataclass(frozen=True)
class CuratedFeatureDetailSnapshot:
    """curated feature detail payload projection."""

    curated_feature_id: str
    version: int
    etag: str
    updated_at: datetime
    theme: dict[str, Any]
    content: dict[str, Any]
    source: dict[str, Any]
    items: tuple[CuratedFeatureDetailItem, ...]



_THEME_COLUMNS: Final[str] = (
    "theme_id::text AS theme_id, theme_slug, theme_name, theme_description, "
    "theme_group, visibility, metadata, created_at, updated_at, row_revision, "
    "archived_at, owner_kind, owner_provider_dataset_id"
)
_SOURCE_COLUMNS: Final[str] = (
    "s.source_id::text AS source_id, s.provider_dataset_id, pd.provider, pd.dataset_key, "
    "s.source_name, s.source_url, s.source_kind, s.license, s.update_cycle, "
    "s.last_source_modified_at, s.last_checked_at, s.next_expected_at, s.row_count, "
    "s.freshness_note, s.provider_status, s.metadata, s.created_at, s.updated_at, "
    "s.row_revision, s.observation_revision, s.archived_at"
)
_RULE_COLUMNS: Final[str] = (
    "r.rule_id::text AS rule_id, r.theme_id::text AS theme_id, t.theme_slug, "
    "r.source_id::text AS source_id, s.provider_dataset_id, pd.provider, pd.dataset_key, "
    "r.place_kind, "
    "r.category, r.region_scope, r.detail_selector, r.default_action, "
    "r.priority, r.enabled, r.metadata, r.created_at, r.updated_at, "
    "r.row_revision, r.archived_at, r.owner_kind, r.owner_provider_dataset_id"
)
_FEATURE_COLUMNS: Final[str] = """
    cf.curated_feature_id::text AS curated_feature_id,
    cf.theme_id::text AS theme_id,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    cf.feature_id,
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.name AS feature_name,
    f.category AS feature_category,
    f.kind AS feature_kind,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    typed.detail,
    cf.source_id::text AS source_id,
    s.provider_dataset_id,
    pd.provider,
    pd.dataset_key,
    s.source_name,
    s.source_url,
    cf.source_record_key,
    cf.curation_status,
    cf.selection_origin,
    cf.selected_by,
    cf.selected_at,
    cf.rejected_by,
    cf.rejected_at,
    cf.rejection_reason,
    cf.rank_score,
    cf.display_title,
    cf.display_summary,
    cf.curation_relation,
    cf.reuse_policy,
    cf.content_version,
    cf.metadata,
    cf.created_at,
    cf.updated_at,
    cf.archived_at
"""
# 공개 read는 ADR-067 단일 공개 projection(``feature.public_features``)만 조인해
# 비공개(draft/broken/hidden/inactive/soft-deleted) feature의 큐레이션 노출을 막는다
# (T-VN-04, F-1). admin read는 기존대로 base table을 조인해 전 상태를 본다 —
# legacy overlay 상태와 무관하게 공개 read가 새지 않는다.
# admin reader는 core와 모든 typed subtype을 직접 LEFT JOIN해 detail을 조립한다.
# public reader도 같은 ``typed`` alias를 제공해 두 select의 projection을 공유한다.
_FEATURE_FROM_SQL: Final[str] = f"""
FROM feature.curated_features AS cf
JOIN feature.curated_themes AS t ON t.theme_id = cf.theme_id
JOIN feature.curated_sources AS s ON s.source_id = cf.source_id
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
JOIN feature.features AS f ON f.feature_id = cf.feature_id
{typed_feature_detail_joins_sql()}
CROSS JOIN LATERAL (
    SELECT {TYPED_FEATURE_DETAIL_COLUMNS_SQL}
) AS typed
"""

_PUBLIC_FEATURE_FROM_SQL: Final[str] = """
FROM feature.curated_features AS cf
JOIN feature.curated_themes AS t ON t.theme_id = cf.theme_id
JOIN feature.curated_sources AS s ON s.source_id = cf.source_id
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
JOIN feature.public_features AS f ON f.feature_id = cf.feature_id
CROSS JOIN LATERAL (SELECT f.detail) AS typed
"""

_PUBLIC_FEATURE_FILTERS_SQL: Final[str] = (
    """
  AND t.visibility = 'public'
  AND t.archived_at IS NULL
  AND s.archived_at IS NULL
  AND cf.curation_status = 'curated'
  AND cf.archived_at IS NULL
  AND NOT cf.metadata @> '{"merge_projection_detached": true}'::jsonb
"""
    + public_active_notice_filter_sql("f")
)

_LIST_THEMES_SQL: Final[str] = f"""
SELECT {_THEME_COLUMNS}
FROM feature.curated_themes
WHERE (CAST(:include_archived AS boolean) OR archived_at IS NULL)
  AND (CAST(:visibility AS text) IS NULL OR visibility = CAST(:visibility AS text))
  AND (CAST(:theme_group AS text) IS NULL OR theme_group = CAST(:theme_group AS text))
ORDER BY theme_group, theme_slug
LIMIT :limit
"""

_LIST_SOURCES_SQL: Final[str] = f"""
SELECT {_SOURCE_COLUMNS}
FROM feature.curated_sources AS s
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE (
    CAST(:include_archived AS boolean) OR s.archived_at IS NULL
)
  AND (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
)
  AND (
    CAST(:provider_status AS text) IS NULL
    OR provider_status = CAST(:provider_status AS text)
  )
ORDER BY pd.provider, pd.dataset_key
LIMIT :limit
"""

_GET_SOURCE_SQL: Final[str] = f"""
SELECT {_SOURCE_COLUMNS}
FROM feature.curated_sources AS s
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE s.source_id = CAST(:source_id AS uuid)
"""

_LIST_RULES_SQL: Final[str] = f"""
SELECT {_RULE_COLUMNS}
FROM feature.curated_source_rules AS r
JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
JOIN feature.curated_sources AS s ON s.source_id = r.source_id
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = s.provider_dataset_id
WHERE (CAST(:theme_id AS uuid) IS NULL OR r.theme_id = CAST(:theme_id AS uuid))
  AND (
    CAST(:include_archived AS boolean)
    OR (r.archived_at IS NULL AND t.archived_at IS NULL AND s.archived_at IS NULL)
  )
  AND (
    CAST(:theme_slug AS text) IS NULL
    OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
  AND (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  )
  AND (CAST(:enabled AS boolean) IS NULL OR r.enabled = CAST(:enabled AS boolean))
ORDER BY t.theme_slug, pd.provider, pd.dataset_key, r.priority DESC, r.rule_id
LIMIT :limit
"""

# 필터(커서 제외) — 일반/dedup 두 변형이 공유한다.
_FEATURE_FILTERS_SQL: Final[str] = """
WHERE (CAST(:include_archived AS boolean) OR cf.archived_at IS NULL)
  AND (
    CAST(:curation_status AS text) IS NULL
    OR cf.curation_status = CAST(:curation_status AS text)
  )
  AND (CAST(:theme_id AS uuid) IS NULL OR cf.theme_id = CAST(:theme_id AS uuid))
  AND (
    CAST(:theme_slug AS text) IS NULL
    OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (CAST(:source_id AS uuid) IS NULL OR cf.source_id = CAST(:source_id AS uuid))
  AND (
    CAST(:provider_dataset_id AS bigint) IS NULL
    OR s.provider_dataset_id = CAST(:provider_dataset_id AS bigint)
  )
  AND (
    CAST(:region_code AS text) IS NULL
    OR f.sido_code = CAST(:region_code AS text)
    OR f.sigungu_code = CAST(:region_code AS text)
    OR f.legal_dong_code LIKE CAST(:region_code AS text) || '%'
  )
  AND (CAST(:sido_code AS text) IS NULL OR f.sido_code = CAST(:sido_code AS text))
  AND (
    CAST(:sigungu_code AS text) IS NULL
    OR f.sigungu_code = CAST(:sigungu_code AS text)
  )
  AND (
    NOT CAST(:bbox_enabled AS boolean)
    OR (
      f.coord IS NOT NULL
      AND f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
          CAST(:min_lon AS double precision),
          CAST(:min_lat AS double precision),
          CAST(:max_lon AS double precision),
          CAST(:max_lat AS double precision),
          4326
      )
    )
  )
  AND (
    CAST(:q_pattern AS text) IS NULL
    OR f.name ILIKE CAST(:q_pattern AS text)
    OR COALESCE(cf.display_title, '') ILIKE CAST(:q_pattern AS text)
    OR COALESCE(cf.display_summary, '') ILIKE CAST(:q_pattern AS text)
  )
  AND (
    CAST(:feature_name_pattern AS text) IS NULL
    OR f.name ILIKE CAST(:feature_name_pattern AS text)
  )
  AND (
    CAST(:display_title AS text) IS NULL
    OR COALESCE(cf.display_title, '') = CAST(:display_title AS text)
  )
  AND (
    CAST(:display_titles AS text[]) IS NULL
    OR cf.display_title = ANY(CAST(:display_titles AS text[]))
  )
"""

# keyset 커서 — 일반 변형(원본 cf 컬럼, uuid 비교).
_FEATURE_CURSOR_SQL: Final[str] = """
  AND (
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (
      cf.updated_at,
      cf.curated_feature_id
    ) < (
      CAST(:cursor_updated_at AS timestamptz),
      CAST(:cursor_curated_feature_id AS uuid)
    )
  )
"""


def _list_features_sql(*, public_only: bool) -> str:
    return f"""
SELECT {_FEATURE_COLUMNS}
{_PUBLIC_FEATURE_FROM_SQL if public_only else _FEATURE_FROM_SQL}
{_FEATURE_FILTERS_SQL}
{_PUBLIC_FEATURE_FILTERS_SQL if public_only else ""}
{_FEATURE_CURSOR_SQL}
ORDER BY cf.updated_at DESC, cf.curated_feature_id DESC
LIMIT :limit
"""

# 물리 feature당 1행 dedup 변형(지도 경로). 같은 feature가 여러 테마로 큐레이션되면
# `/v1/admin/features/curated`가 같은 feature_id를 테마 수만큼 반환한다(부분 UNIQUE 인덱스가
# (theme_id, feature_id)만 강제 → cross-theme 중복 허용). 지도는 물리 feature당 마커 1개여야
# 하므로, feature_id별로 rank_score 최고(동점 시 최신 updated_at) 큐레이션 1건만 남긴다.
# DISTINCT ON은 서브쿼리 안에서 (feature_id, rank_score DESC …)로 수행하고, 바깥에서 keyset
# 커서 정렬을 적용해 페이지네이션 정합성을 유지한다(curated_feature_id는 서브쿼리에서 text로
# alias돼 있어 커서 비교도 text — 표준 uuid는 text 정렬이 uuid 정렬과 일치).
# 관리자 per-curation 목록은 이 변형을 쓰지 않아 모든 큐레이션을 그대로 본다.
def _list_features_distinct_sql(*, public_only: bool) -> str:
    return f"""
SELECT * FROM (
    SELECT DISTINCT ON (cf.feature_id) {_FEATURE_COLUMNS}
    {_PUBLIC_FEATURE_FROM_SQL if public_only else _FEATURE_FROM_SQL}
    {_FEATURE_FILTERS_SQL}
    {_PUBLIC_FEATURE_FILTERS_SQL if public_only else ""}
    ORDER BY cf.feature_id, cf.rank_score DESC NULLS LAST,
             cf.updated_at DESC, cf.curated_feature_id DESC
) AS d
WHERE (
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (
      d.updated_at,
      d.curated_feature_id
    ) < (
      CAST(:cursor_updated_at AS timestamptz),
      CAST(:cursor_curated_feature_id AS text)
    )
)
ORDER BY d.updated_at DESC, d.curated_feature_id DESC
LIMIT :limit
"""


def _get_feature_sql(*, public_only: bool) -> str:
    return f"""
SELECT {_FEATURE_COLUMNS}
{_PUBLIC_FEATURE_FROM_SQL if public_only else _FEATURE_FROM_SQL}
WHERE cf.curated_feature_id = CAST(:curated_feature_id AS uuid)
  AND (CAST(:include_archived AS boolean) OR cf.archived_at IS NULL)
{_PUBLIC_FEATURE_FILTERS_SQL if public_only else ""}
"""

_CREATE_FEATURE_SQL: Final[str] = """
INSERT INTO feature.curated_features (
    theme_id, feature_id, source_id, source_record_key, curation_status,
    selection_origin, selected_by, selected_at, rejected_by, rejected_at,
    rejection_reason, rank_score, display_title, display_summary,
    curation_relation, reuse_policy, metadata,
    operator_updated_by, operator_updated_at, updated_at, archived_at
) VALUES (
    CAST(:theme_id AS uuid), :feature_id, CAST(:source_id AS uuid),
    CAST(:source_record_key AS text), :curation_status, :selection_origin,
    :selected_by,
    CASE WHEN CAST(:selected_now AS boolean) THEN now() ELSE NULL END,
    :rejected_by,
    CASE WHEN CAST(:rejected_now AS boolean) THEN now() ELSE NULL END,
    :rejection_reason,
    :rank_score, :display_title, :display_summary, :curation_relation,
    :reuse_policy, CAST(:metadata_json AS jsonb), :operator_updated_by,
    CASE WHEN CAST(:operator_updated AS boolean) THEN clock_timestamp() ELSE NULL END,
    now(),
    CASE WHEN :curation_status = 'archived' THEN now() ELSE NULL END
)
RETURNING curated_feature_id::text
"""

_UPDATE_FEATURE_BASE_SQL: Final[str] = """
UPDATE feature.curated_features
SET {set_clause}
WHERE curated_feature_id = CAST(:curated_feature_id AS uuid)
  AND NOT metadata @> '{{"merge_projection_detached": true}}'::jsonb
RETURNING curated_feature_id::text
"""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _json_dumps(value: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(value) if value else {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decimal_to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _validate_choice(value: str, allowed: frozenset[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")


def _safe_limit(limit: int, max_limit: int = _MAX_LIST_LIMIT) -> int:
    return max(1, min(limit, max_limit))


def _q_pattern(q: str | None) -> str | None:
    stripped = _text(q)
    return f"%{stripped}%" if stripped else None


def _bbox_params(
    *,
    min_lon: float | None,
    min_lat: float | None,
    max_lon: float | None,
    max_lat: float | None,
) -> dict[str, Any]:
    values = (min_lon, min_lat, max_lon, max_lat)
    if all(value is None for value in values):
        return {
            "bbox_enabled": False,
            "min_lon": None,
            "min_lat": None,
            "max_lon": None,
            "max_lat": None,
        }
    if any(value is None for value in values):
        raise ValueError("bbox requires min_lon, min_lat, max_lon, max_lat")
    assert min_lon is not None
    assert min_lat is not None
    assert max_lon is not None
    assert max_lat is not None
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("bbox min values must be smaller than max values")
    return {
        "bbox_enabled": True,
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
    }


def _decode_cursor(cursor: str | None, *, kind: CursorKind) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curated feature cursor") from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        raise ValueError("invalid curated feature cursor")
    if not isinstance(payload.get("curated_feature_id"), str):
        raise ValueError("invalid curated feature cursor")
    if not isinstance(payload.get("updated_at"), str):
        raise ValueError("invalid curated feature cursor")
    return payload


def _encode_cursor(*, curated_feature_id: str, updated_at: datetime) -> str:
    payload = {
        "kind": "curated_features",
        "curated_feature_id": curated_feature_id,
        "updated_at": updated_at.isoformat(),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _decode_cursor(cursor, kind="curated_features")
    if not payload:
        return {"cursor_updated_at": None, "cursor_curated_feature_id": None}
    try:
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
    except ValueError as exc:
        raise ValueError("invalid curated feature cursor") from exc
    return {
        "cursor_updated_at": updated_at,
        "cursor_curated_feature_id": payload["curated_feature_id"],
    }


def _theme(row: Any) -> CuratedTheme:
    return CuratedTheme(
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_description=str(row["theme_description"]),
        theme_group=str(row["theme_group"]),
        visibility=str(row["visibility"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row["row_revision"]),
        archived_at=row["archived_at"],
        owner_kind=_text(row["owner_kind"]),
        owner_provider_dataset_id=(
            int(row["owner_provider_dataset_id"])
            if row["owner_provider_dataset_id"] is not None
            else None
        ),
    )


def _source(row: Any) -> CuratedSource:
    return CuratedSource(
        source_id=str(row["source_id"]),
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_name=str(row["source_name"]),
        source_url=row["source_url"],
        source_kind=str(row["source_kind"]),
        license=row["license"],
        update_cycle=str(row["update_cycle"]),
        last_source_modified_at=row["last_source_modified_at"],
        last_checked_at=row["last_checked_at"],
        next_expected_at=row["next_expected_at"],
        row_count=row["row_count"],
        freshness_note=row["freshness_note"],
        provider_status=str(row["provider_status"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row["row_revision"]),
        observation_revision=int(row["observation_revision"]),
        archived_at=row["archived_at"],
    )


def _rule(row: Any) -> CuratedSourceRule:
    return CuratedSourceRule(
        rule_id=str(row["rule_id"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        source_id=str(row["source_id"]),
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        place_kind=row["place_kind"],
        category=row["category"],
        region_scope=_json_object(row["region_scope"]),
        detail_selector=(
            _json_object(row["detail_selector"])
            if row["detail_selector"] is not None
            else None
        ),
        default_action=str(row["default_action"]),
        priority=int(row["priority"]),
        enabled=bool(row["enabled"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        row_revision=int(row.get("row_revision", 1)),
        archived_at=row.get("archived_at"),
        owner_kind=_text(row.get("owner_kind")),
        owner_provider_dataset_id=(
            int(row["owner_provider_dataset_id"])
            if row.get("owner_provider_dataset_id") is not None
            else None
        ),
    )


def _feature(row: Any) -> CuratedFeature:
    lon = row["lon"]
    lat = row["lat"]
    feature_uuid = row.get("feature_uuid")
    return CuratedFeature(
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
        curated_feature_id=str(row["curated_feature_id"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_group=str(row["theme_group"]),
        feature_id=str(row["feature_id"]),
        feature_name=str(row["feature_name"]),
        feature_category=str(row["feature_category"]),
        feature_kind=str(row["feature_kind"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        legal_dong_code=row["legal_dong_code"],
        address=_json_object(row["address"]),
        detail=_json_object(row["detail"]),
        source_id=str(row["source_id"]),
        provider_dataset_id=int(row["provider_dataset_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_name=str(row["source_name"]),
        source_url=row["source_url"],
        source_record_key=row["source_record_key"],
        curation_status=str(row["curation_status"]),
        selection_origin=str(row["selection_origin"]),
        selected_by=row["selected_by"],
        selected_at=row["selected_at"],
        rejected_by=row["rejected_by"],
        rejected_at=row["rejected_at"],
        rejection_reason=row["rejection_reason"],
        rank_score=_decimal_to_float(row["rank_score"]),
        display_title=row["display_title"],
        display_summary=row["display_summary"],
        curation_relation=str(row["curation_relation"]),
        reuse_policy=str(row["reuse_policy"]),
        content_version=int(row["content_version"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _snapshot_feature_ref(feature: CuratedFeature) -> str:
    """snapshot payload의 feature 참조 값 — UUID 정본 (T-VN-32C PR-2).

    legacy cached snapshot은 T-VN-40 final cutover에서 제거한다. uuid 결측은
    projection 누락이므로 legacy 값을 조용히 쓰지 않고 fail-close한다.
    """
    if not feature.feature_uuid:
        raise ValueError(
            "CuratedFeature.feature_uuid 결측 — read projection 누락 (T-VN-32C)"
        )
    return feature.feature_uuid


def _feature_snapshot(feature: CuratedFeature) -> dict[str, Any]:
    return {
        "feature_id": _snapshot_feature_ref(feature),
        "name": feature.feature_name,
        "category": feature.feature_category,
        "kind": feature.feature_kind,
        "lon": feature.lon,
        "lat": feature.lat,
        "sido_code": feature.sido_code,
        "sigungu_code": feature.sigungu_code,
        "legal_dong_code": feature.legal_dong_code,
        "address": feature.address,
        "detail": feature.detail,
    }


def _feature_detail_snapshot(feature: CuratedFeature) -> CuratedFeatureDetailSnapshot:
    title = feature.display_title or _default_source_title(feature) or feature.feature_name
    summary = feature.display_summary
    if summary is None:
        summary = feature.metadata.get("summary")
        if not isinstance(summary, str):
            summary = None
    content = {
        "title": title,
        "summary": summary,
        "destination_name": _destination_name(feature),
        "region_code": feature.sigungu_code or feature.sido_code,
        "category": feature.theme_group,
        "curation_status": feature.curation_status,
        "reuse_policy": feature.reuse_policy,
    }
    item = CuratedFeatureDetailItem(
        curated_feature_item_id=feature.curated_feature_id,
        feature_id=_snapshot_feature_ref(feature),
        relation=feature.curation_relation,
        sort_order=1,
        day_index=None,
        memo=summary,
        feature_snapshot=_feature_snapshot(feature),
        source_record_key=feature.source_record_key,
    )
    theme = {
        "theme_slug": feature.theme_slug,
        "theme_name": feature.theme_name,
    }
    source = {
        "provider": feature.provider,
        "dataset_key": feature.dataset_key,
        "source_name": feature.source_name,
        "source_url": feature.source_url,
    }
    payload = {
        "curated_feature_id": feature.curated_feature_id,
        "version": feature.content_version,
        "updated_at": feature.updated_at.isoformat(),
        "theme": theme,
        "content": content,
        "source": source,
        "items": [
            {
                "curated_feature_item_id": item.curated_feature_item_id,
                "feature_id": item.feature_id,
                "relation": item.relation,
                "sort_order": item.sort_order,
                "day_index": item.day_index,
                "memo": item.memo,
                "feature_snapshot": item.feature_snapshot,
                "source_record_key": item.source_record_key,
            }
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    etag = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return CuratedFeatureDetailSnapshot(
        curated_feature_id=feature.curated_feature_id,
        version=feature.content_version,
        etag=etag,
        updated_at=feature.updated_at,
        theme=theme,
        content=content,
        source=source,
        items=(item,),
    )



def _destination_name(feature: CuratedFeature) -> str | None:
    for key in ("admin", "road", "legal"):
        value = feature.address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if feature.sigungu_code:
        return feature.sigungu_code
    return feature.sido_code


def _nested_text(payload: dict[str, Any], *path: str) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _text(current)


def _concierge_source_title(feature: CuratedFeature) -> str | None:
    if (
        feature.provider != _CONCIERGE_PROVIDER
        or feature.dataset_key != _CONCIERGE_DATASET_KEY
    ):
        return None
    for path in (
        ("payload", "kor_travel_concierge", "youtube", "source_title"),
        ("payload", "kor_travel_concierge", "youtube", "playlist_title"),
        ("payload", "kor_travel_concierge", "youtube", "channel_title"),
        ("payload", "kor_travel_concierge", "youtube", "source_search_query"),
        ("payload", "kor_travel_concierge", "youtube", "corrected_search_query"),
        ("payload", "kor_travel_concierge", "youtube", "search_query"),
        ("facility_info", "youtube_playlist_title"),
        ("facility_info", "youtube_channel_title"),
    ):
        title = _nested_text(feature.detail, *path)
        if title is not None:
            return title
    return None


def _default_source_title(feature: CuratedFeature) -> str | None:
    title = _concierge_source_title(feature)
    if title is not None:
        return title
    if feature.provider in _PROVIDER_TITLE_SOURCE_PROVIDERS:
        return feature.provider
    return None


async def list_curated_themes(
    session: AsyncSession,
    *,
    visibility: str | None = None,
    theme_group: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedTheme, ...]:
    """curated theme 목록을 조회한다."""

    if visibility is not None:
        _validate_choice(visibility, _THEME_VISIBILITIES, "visibility")
    rows = (
        await session.execute(
            text(_LIST_THEMES_SQL),
            {
                "visibility": visibility,
                "theme_group": theme_group,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_theme(row) for row in rows)


async def get_curated_theme(
    session: AsyncSession,
    *,
    theme_id: str,
) -> CuratedTheme | None:
    """retained theme 단건을 revision/owner 축과 함께 조회한다."""

    row = (
        await session.execute(
            text(
                f"""
                SELECT {_THEME_COLUMNS}
                FROM feature.curated_themes
                WHERE theme_id = CAST(:theme_id AS uuid)
                """
            ),
            {"theme_id": theme_id},
        )
    ).mappings().first()
    return _theme(row) if row is not None else None


async def list_curated_sources(
    session: AsyncSession,
    *,
    provider_dataset_id: int | None = None,
    provider_status: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedSource, ...]:
    """curated source metadata 목록을 조회한다."""

    if provider_status is not None:
        _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    rows = (
        await session.execute(
            text(_LIST_SOURCES_SQL),
            {
                "provider_dataset_id": provider_dataset_id,
                "provider_status": provider_status,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_source(row) for row in rows)


async def get_curated_source(
    session: AsyncSession, *, source_id: str
) -> CuratedSource | None:
    """retained source 단건을 operator/observation revision과 함께 조회한다."""

    row = (
        await session.execute(text(_GET_SOURCE_SQL), {"source_id": source_id})
    ).mappings().first()
    return _source(row) if row is not None else None


async def list_curated_source_rules(
    session: AsyncSession,
    *,
    theme_id: str | None = None,
    theme_slug: str | None = None,
    source_id: str | None = None,
    provider_dataset_id: int | None = None,
    enabled: bool | None = None,
    include_archived: bool = False,
    limit: int = 200,
) -> tuple[CuratedSourceRule, ...]:
    """curated source rule 목록을 조회한다."""

    rows = (
        await session.execute(
            text(_LIST_RULES_SQL),
            {
                "theme_id": theme_id,
                "theme_slug": theme_slug,
                "source_id": source_id,
                "provider_dataset_id": provider_dataset_id,
                "enabled": enabled,
                "include_archived": include_archived,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_rule(row) for row in rows)


async def get_curated_source_rule(
    session: AsyncSession,
    *,
    rule_id: str,
) -> CuratedSourceRule | None:
    """retained source rule 단건을 조회한다."""

    return await _get_rule(session, rule_id)


async def list_curated_features(
    session: AsyncSession,
    *,
    theme_id: str | None = None,
    theme_slug: str | None = None,
    source_id: str | None = None,
    provider_dataset_id: int | None = None,
    curation_status: str | None = "curated",
    region_code: str | None = None,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    q: str | None = None,
    feature_name: str | None = None,
    display_title: str | None = None,
    display_titles: list[str] | None = None,
    include_archived: bool = False,
    page_size: int = 50,
    cursor: str | None = None,
    distinct_by_feature: bool = False,
    public_only: bool = False,
) -> CuratedFeaturePage:
    """curated feature 목록을 keyset으로 조회한다.

    ``distinct_by_feature=True``면 물리 feature당 rank_score 최고 큐레이션 1건만
    반환한다(지도 경로 — cross-theme 중복 제거). 관리자 per-curation 목록은 기본값
    False로 모든 큐레이션을 그대로 본다.

    ``public_only=True``(공개 `/v1/curated-features` 표면)면 공개 theme의
    ``curated`` overlay와 active/latest underlying feature만 반환한다. 기본 공개
    집합은 ADR-067 ``feature.public_features`` projection, notice 추가 감산은
    ``public_active_notice_filter_sql`` 정본을 공유한다. 관리자 표면은 기본값
    False로 전 상태를 그대로 본다.
    """

    if curation_status is not None:
        _validate_choice(curation_status, _CURATION_STATUSES, "curation_status")
    safe_page_size = _safe_limit(page_size, _MAX_PAGE_SIZE)
    list_sql = (
        _list_features_distinct_sql(public_only=public_only)
        if distinct_by_feature
        else _list_features_sql(public_only=public_only)
    )
    rows = (
        await session.execute(
            text(list_sql),
            {
                "theme_id": theme_id,
                "theme_slug": theme_slug,
                "source_id": source_id,
                "provider_dataset_id": provider_dataset_id,
                "curation_status": curation_status,
                "region_code": region_code,
                "sido_code": sido_code,
                "sigungu_code": sigungu_code,
                "q_pattern": _q_pattern(q),
                "feature_name_pattern": _q_pattern(feature_name),
                "display_title": _text(display_title),
                "display_titles": (
                    [str(title) for title in display_titles] if display_titles else None
                ),
                "include_archived": include_archived,
                **_bbox_params(
                    min_lon=min_lon,
                    min_lat=min_lat,
                    max_lon=max_lon,
                    max_lat=max_lat,
                ),
                **_cursor_params(cursor),
                "limit": safe_page_size + 1,
            },
        )
    ).mappings().all()
    items = tuple(_feature(row) for row in rows[:safe_page_size])
    next_cursor = (
        _encode_cursor(
            curated_feature_id=items[-1].curated_feature_id,
            updated_at=items[-1].updated_at,
        )
        if len(rows) > safe_page_size and items
        else None
    )
    return CuratedFeaturePage(items=items, next_cursor=next_cursor)


async def get_curated_feature(
    session: AsyncSession,
    *,
    curated_feature_id: str,
    include_archived: bool = False,
    public_only: bool = False,
) -> CuratedFeature | None:
    """curated feature 단건을 조회한다.

    ``public_only=True``(공개 표면)면 theme/overlay/underlying feature가 모두
    공개 계약을 통과할 때만 반환한다. 종료·구버전 notice도 ``None``이다.
    """

    row = (
        await session.execute(
            text(_get_feature_sql(public_only=public_only)),
            {
                "curated_feature_id": curated_feature_id,
                "include_archived": include_archived,
            },
        )
    ).mappings().first()
    return _feature(row) if row is not None else None


async def get_curated_feature_detail_snapshot(
    session: AsyncSession,
    *,
    curated_feature_id: str,
) -> CuratedFeatureDetailSnapshot | None:
    """curated feature detail용 닫힌 snapshot을 만든다."""

    feature = await get_curated_feature(
        session,
        curated_feature_id=curated_feature_id,
        include_archived=False,
    )
    return _feature_detail_snapshot(feature) if feature is not None else None


def _selected_fields_for_status(
    *,
    curation_status: str,
    actor: str | None,
    reason: str | None,
) -> dict[str, Any]:
    now_expr = "__NOW__"
    if curation_status == "curated":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "selected_by": actor,
            "selected_at": now_expr,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "archived_at": None,
        }
    if curation_status == "rejected":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "rejected_by": actor,
            "rejected_at": now_expr,
            "rejection_reason": reason,
            "archived_at": None,
        }
    if curation_status == "candidate":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "archived_at": None,
        }
    if curation_status == "archived":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "archived_at": now_expr,
        }
    return {"curation_status": curation_status, "selection_origin": "admin"}


async def create_curated_feature(
    session: AsyncSession,
    *,
    theme_id: str,
    feature_id: str,
    source_id: str,
    source_record_key: str | None = None,
    curation_status: str = "candidate",
    selection_origin: str = "admin",
    selected_by: str | None = None,
    rejected_by: str | None = None,
    rejection_reason: str | None = None,
    rank_score: float = 0.0,
    display_title: str | None = None,
    display_summary: str | None = None,
    curation_relation: str = "nearby_option",
    reuse_policy: str = "manual_review",
    metadata: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> CuratedFeature:
    """curated feature overlay 1건을 생성한다. commit은 호출자 책임."""

    if metadata is not None and "merge_projection_detached" in metadata:
        raise ValueError("merge_projection_detached metadata는 내부 전용입니다.")
    _validate_choice(curation_status, _CURATION_STATUSES, "curation_status")
    _validate_choice(selection_origin, _SELECTION_ORIGINS, "selection_origin")
    _validate_choice(curation_relation, _CURATION_RELATIONS, "curation_relation")
    _validate_choice(reuse_policy, _REUSE_POLICIES, "reuse_policy")
    active_feature = (
        await session.execute(
            text(
                "SELECT feature_id FROM feature.features "
                # legacy `status NOT IN ('deleted','hidden')`의 등가물.
                # deleted→retired, hidden→(active, suppressed)이므로 suppressed만
                # 배제한다. draft와 quarantined는 legacy가 허용했으므로 유지한다.
                "WHERE feature_id = :feature_id "
                "AND lifecycle_state = 'active' "
                "AND publication_state <> 'suppressed' "
                "FOR KEY SHARE"
            ),
            {"feature_id": feature_id},
        )
    ).first()
    if active_feature is None:
        raise ValueError("feature_id must reference a selectable Feature")
    row = (
        await session.execute(
            text(_CREATE_FEATURE_SQL),
            {
                "theme_id": theme_id,
                "feature_id": feature_id,
                "source_id": source_id,
                "source_record_key": source_record_key,
                "curation_status": curation_status,
                "selection_origin": selection_origin,
                "selected_by": selected_by,
                "selected_now": curation_status == "curated",
                "rejected_by": rejected_by,
                "rejected_now": curation_status == "rejected",
                "rejection_reason": rejection_reason,
                "rank_score": rank_score,
                "display_title": display_title,
                "display_summary": display_summary,
                "curation_relation": curation_relation,
                "reuse_policy": reuse_policy,
                "metadata_json": _json_dumps(metadata),
                "operator_updated_by": (
                    actor or rejected_by or selected_by
                    if selection_origin in {"admin", "external_api"}
                    else None
                ),
                "operator_updated": selection_origin in {"admin", "external_api"},
            },
        )
    ).mappings().one()
    feature = await get_curated_feature(
        session,
        curated_feature_id=str(row["curated_feature_id"]),
        include_archived=True,
    )
    if feature is None:
        raise RuntimeError("created curated feature could not be read")
    return feature


async def update_curated_feature(
    session: AsyncSession,
    *,
    curated_feature_id: str,
    updates: Mapping[str, Any],
    actor: str | None = None,
) -> CuratedFeature | None:
    """curated feature overlay를 부분 수정한다."""

    allowed = {
        "curation_status",
        "theme_id",
        "source_record_key",
        "rank_score",
        "display_title",
        "display_summary",
        "curation_relation",
        "reuse_policy",
        "metadata",
    }
    set_parts: list[str] = []
    params: dict[str, Any] = {"curated_feature_id": curated_feature_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported curated_feature update field: {key}")
        if key == "curation_status":
            _validate_choice(str(value), _CURATION_STATUSES, key)
            for status_key, status_value in _selected_fields_for_status(
                curation_status=str(value),
                actor=actor,
                reason=None,
            ).items():
                if status_value == "__NOW__":
                    set_parts.append(f"{status_key} = now()")
                else:
                    set_parts.append(f"{status_key} = :{status_key}")
                    params[status_key] = status_value
            continue
        if key == "curation_relation":
            _validate_choice(str(value), _CURATION_RELATIONS, key)
        if key == "reuse_policy":
            _validate_choice(str(value), _REUSE_POLICIES, key)
        if key == "metadata":
            if not isinstance(value, Mapping):
                raise ValueError("curated feature metadata must be an object")
            if "merge_projection_detached" in value:
                raise ValueError("merge_projection_detached metadata는 내부 전용입니다.")
            set_parts.append("metadata = CAST(:metadata_json AS jsonb)")
            params["metadata_json"] = _json_dumps(value)
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    if not set_parts:
        current = await get_curated_feature(
            session,
            curated_feature_id=curated_feature_id,
            include_archived=True,
        )
        if current is not None and current.metadata.get("merge_projection_detached") is True:
            return None
        return current
    operator_owned_changed = bool(
        {"curation_status", "curation_relation", "reuse_policy"} & updates.keys()
    )
    if operator_owned_changed:
        if "curation_status" not in updates:
            set_parts.append("selection_origin = 'admin'")
        set_parts.extend(
            [
                "operator_updated_by = COALESCE(:actor, operator_updated_by)",
                "operator_updated_at = clock_timestamp()",
            ]
        )
    set_parts.extend(
        [
            "updated_at = now()",
            "content_version = content_version + 1",
        ]
    )
    params["actor"] = actor
    row = (
        await session.execute(
            text(_UPDATE_FEATURE_BASE_SQL.format(set_clause=", ".join(set_parts))),
            params,
        )
    ).mappings().first()
    if row is None:
        return None
    return await get_curated_feature(
        session,
        curated_feature_id=str(row["curated_feature_id"]),
        include_archived=True,
    )


async def set_curated_feature_status(
    session: AsyncSession,
    *,
    curated_feature_id: str,
    curation_status: str,
    actor: str | None = None,
    reason: str | None = None,
) -> CuratedFeature | None:
    """curated feature status를 운영자 action으로 변경한다."""

    _validate_choice(curation_status, _CURATION_STATUSES, "curation_status")
    updates = _selected_fields_for_status(
        curation_status=curation_status,
        actor=actor,
        reason=reason,
    )
    set_parts: list[str] = []
    params: dict[str, Any] = {"curated_feature_id": curated_feature_id}
    for key, value in updates.items():
        if value == "__NOW__":
            set_parts.append(f"{key} = now()")
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    set_parts.extend(
        [
            "operator_updated_by = :operator_updated_by",
            "operator_updated_at = clock_timestamp()",
            "updated_at = now()",
            "content_version = content_version + 1",
        ]
    )
    params["operator_updated_by"] = actor
    row = (
        await session.execute(
            text(_UPDATE_FEATURE_BASE_SQL.format(set_clause=", ".join(set_parts))),
            params,
        )
    ).mappings().first()
    if row is None:
        return None
    return await get_curated_feature(
        session,
        curated_feature_id=str(row["curated_feature_id"]),
        include_archived=True,
    )


async def archive_curated_feature(
    session: AsyncSession,
    *,
    curated_feature_id: str,
    actor: str | None = None,
) -> CuratedFeature | None:
    """curated feature를 soft archive한다."""

    return await set_curated_feature_status(
        session,
        curated_feature_id=curated_feature_id,
        curation_status="archived",
        actor=actor,
    )



async def create_curated_theme(
    session: AsyncSession,
    *,
    theme_slug: str,
    theme_name: str,
    theme_description: str = "",
    theme_group: str,
    default_curated: bool = False,
    visibility: str = "admin_only",
    metadata: Mapping[str, Any] | None = None,
) -> CuratedTheme:
    """curated theme를 생성한다."""

    _validate_choice(visibility, _THEME_VISIBILITIES, "visibility")
    row = (
        await session.execute(
            text(
                f"""
                INSERT INTO feature.curated_themes (
                    theme_slug, theme_name, theme_description, theme_group,
                    default_curated, visibility, metadata, updated_at
                ) VALUES (
                    :theme_slug, :theme_name, :theme_description, :theme_group,
                    :default_curated, :visibility, CAST(:metadata_json AS jsonb), now()
                )
                RETURNING {_THEME_COLUMNS}
                """
            ),
            {
                "theme_slug": theme_slug,
                "theme_name": theme_name,
                "theme_description": theme_description,
                "theme_group": theme_group,
                "default_curated": default_curated,
                "visibility": visibility,
                "metadata_json": _json_dumps(metadata),
            },
        )
    ).mappings().one()
    return _theme(row)


async def update_curated_theme(
    session: AsyncSession,
    *,
    theme_id: str,
    updates: Mapping[str, Any],
) -> CuratedTheme | None:
    """curated theme를 부분 수정한다."""

    allowed = {
        "theme_slug",
        "theme_name",
        "theme_description",
        "theme_group",
        "default_curated",
        "visibility",
        "metadata",
    }
    row = await _update_simple(
        session,
        table="feature.curated_themes",
        id_column="theme_id",
        id_value=theme_id,
        updates=updates,
        allowed=allowed,
        choice_fields={"visibility": _THEME_VISIBILITIES},
        returning=_THEME_COLUMNS,
    )
    return _theme(row) if row is not None else None


async def create_curated_theme_command(
    session: AsyncSession,
    *,
    theme_slug: str,
    theme_name: str,
    theme_description: str,
    theme_group: str,
    visibility: str,
    metadata: Mapping[str, Any] | None,
    command_id: int,
    principal: str,
) -> CuratedTheme:
    """domain command에 결박된 retained theme create를 실행한다."""

    _validate_choice(visibility, _THEME_VISIBILITIES, "visibility")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_theme_command(
                  :theme_slug, :theme_name, :theme_description, :theme_group,
                  :visibility, CAST(:metadata_json AS jsonb), :command_id,
                  :principal, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "metadata_json": _json_dumps(metadata),
                "principal": principal,
                "theme_description": theme_description,
                "theme_group": theme_group,
                "theme_name": theme_name,
                "theme_slug": theme_slug,
                "visibility": visibility,
            },
        )
    ).mappings().one()
    theme = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if theme is None:
        raise RuntimeError("created curated theme could not be read")
    return theme


async def patch_curated_theme_command(
    session: AsyncSession,
    *,
    theme_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedTheme | None:
    """현재 theme를 full desired input으로 만들어 strong CAS patch한다."""

    allowed = {
        "theme_slug",
        "theme_name",
        "theme_description",
        "theme_group",
        "visibility",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await get_curated_theme(session, theme_id=theme_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "theme_slug": current.theme_slug,
        "theme_name": current.theme_name,
        "theme_description": current.theme_description,
        "theme_group": current.theme_group,
        "visibility": current.visibility,
        "metadata": current.metadata,
    }
    desired.update(updates)
    for field_name in (
        "theme_slug",
        "theme_name",
        "theme_description",
        "theme_group",
        "visibility",
        "metadata",
    ):
        if desired[field_name] is None:
            raise ValueError(f"{field_name} must not be null")
    _validate_choice(str(desired["visibility"]), _THEME_VISIBILITIES, "visibility")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_theme_command(
                  CAST(:theme_id AS uuid), :expected_revision, :theme_slug,
                  :theme_name, :theme_description, :theme_group, :visibility,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "metadata_json": _json_dumps(desired["metadata"]),
                "principal": principal,
                "theme_description": desired["theme_description"],
                "theme_group": desired["theme_group"],
                "theme_id": theme_id,
                "theme_name": desired["theme_name"],
                "theme_slug": desired["theme_slug"],
                "visibility": desired["visibility"],
            },
        )
    ).mappings().one()
    updated = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if updated is None:
        raise RuntimeError("patched curated theme could not be read")
    return updated


async def archive_curated_theme_command(
    session: AsyncSession,
    *,
    theme_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedTheme | None:
    """retained theme를 archive하고 affected rule을 원자 reconcile한다."""

    if await get_curated_theme(session, theme_id=theme_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_theme_command(
                  CAST(:theme_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
                "reason_code": reason_code,
                "theme_id": theme_id,
            },
        )
    ).mappings().one()
    archived = await get_curated_theme(session, theme_id=str(result["o_theme_id"]))
    if archived is None:
        raise RuntimeError("archived curated theme could not be read")
    return archived


async def create_curated_source(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    source_name: str,
    source_url: str | None = None,
    source_kind: str,
    license: str | None = None,
    update_cycle: str = "unknown",
    last_source_modified_at: date | None = None,
    last_checked_at: datetime | None = None,
    next_expected_at: date | None = None,
    row_count: int | None = None,
    freshness_note: str | None = None,
    provider_status: str = "implemented",
    metadata: Mapping[str, Any] | None = None,
) -> CuratedSource:
    """curated source metadata를 생성한다."""

    _validate_choice(source_kind, _SOURCE_KINDS, "source_kind")
    _validate_choice(update_cycle, _UPDATE_CYCLES, "update_cycle")
    _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    row = (
        await session.execute(
            text(
                """
                INSERT INTO feature.curated_sources (
                    provider_dataset_id, source_name, source_url, source_kind,
                    license, update_cycle, last_source_modified_at, last_checked_at,
                    next_expected_at, row_count, freshness_note, provider_status,
                    metadata, updated_at
                ) VALUES (
                    :provider_dataset_id, :source_name, :source_url, :source_kind,
                    :license, :update_cycle, :last_source_modified_at, :last_checked_at,
                    :next_expected_at, :row_count, :freshness_note, :provider_status,
                    CAST(:metadata_json AS jsonb), now()
                )
                RETURNING source_id::text AS source_id
                """
            ),
            {
                "provider_dataset_id": provider_dataset_id,
                "source_name": source_name,
                "source_url": source_url,
                "source_kind": source_kind,
                "license": license,
                "update_cycle": update_cycle,
                "last_source_modified_at": last_source_modified_at,
                "last_checked_at": last_checked_at,
                "next_expected_at": next_expected_at,
                "row_count": row_count,
                "freshness_note": freshness_note,
                "provider_status": provider_status,
                "metadata_json": _json_dumps(metadata),
            },
        )
    ).mappings().one()
    created = await get_curated_source(session, source_id=str(row["source_id"]))
    if created is None:
        raise RuntimeError("created curated source could not be read")
    return created


async def update_curated_source(
    session: AsyncSession,
    *,
    source_id: str,
    updates: Mapping[str, Any],
) -> CuratedSource | None:
    """curated source metadata를 부분 수정한다."""

    allowed = {
        "source_name",
        "source_url",
        "source_kind",
        "license",
        "update_cycle",
        "last_source_modified_at",
        "last_checked_at",
        "next_expected_at",
        "row_count",
        "freshness_note",
        "provider_status",
        "metadata",
    }
    row = await _update_simple(
        session,
        table="feature.curated_sources",
        id_column="source_id",
        id_value=source_id,
        updates=updates,
        allowed=allowed,
        choice_fields={
            "source_kind": _SOURCE_KINDS,
            "update_cycle": _UPDATE_CYCLES,
            "provider_status": _PROVIDER_STATUSES,
        },
        returning="source_id::text AS source_id",
    )
    return (
        await get_curated_source(session, source_id=str(row["source_id"]))
        if row is not None
        else None
    )


async def create_curated_source_command(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    source_name: str,
    source_url: str | None = None,
    source_kind: str,
    license: str | None = None,
    update_cycle: str = "unknown",
    freshness_note: str | None = None,
    provider_status: str = "implemented",
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CuratedSource:
    """operator source catalog row를 typed command로 생성한다."""

    _validate_choice(source_kind, _SOURCE_KINDS, "source_kind")
    _validate_choice(update_cycle, _UPDATE_CYCLES, "update_cycle")
    _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_source_command(
                  :provider_dataset_id, :source_name, :source_url, :source_kind,
                  :license, :update_cycle, :freshness_note, :provider_status,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "freshness_note": freshness_note,
                "license": license,
                "metadata_json": _json_dumps(metadata),
                "principal": principal,
                "provider_dataset_id": provider_dataset_id,
                "provider_status": provider_status,
                "source_kind": source_kind,
                "source_name": source_name,
                "source_url": source_url,
                "update_cycle": update_cycle,
            },
        )
    ).mappings().one()
    created = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if created is None:
        raise RuntimeError("created curated source could not be read")
    return created


async def patch_curated_source_command(
    session: AsyncSession,
    *,
    source_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedSource | None:
    """operator source fields만 CAS patch하고 observation 필드는 보존한다."""

    allowed = {
        "source_name",
        "source_url",
        "source_kind",
        "license",
        "update_cycle",
        "freshness_note",
        "provider_status",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await get_curated_source(session, source_id=source_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "source_name": current.source_name,
        "source_url": current.source_url,
        "source_kind": current.source_kind,
        "license": current.license,
        "update_cycle": current.update_cycle,
        "freshness_note": current.freshness_note,
        "provider_status": current.provider_status,
        "metadata": current.metadata,
    }
    desired.update(updates)
    _validate_choice(str(desired["source_kind"]), _SOURCE_KINDS, "source_kind")
    _validate_choice(str(desired["update_cycle"]), _UPDATE_CYCLES, "update_cycle")
    _validate_choice(
        str(desired["provider_status"]), _PROVIDER_STATUSES, "provider_status"
    )
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_source_command(
                  CAST(:source_id AS uuid), :expected_revision,
                  :source_name, :source_url, :source_kind, :license,
                  :update_cycle, :freshness_note, :provider_status,
                  CAST(:metadata_json AS jsonb), :command_id, :principal,
                  NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "freshness_note": desired["freshness_note"],
                "license": desired["license"],
                "metadata_json": _json_dumps(desired["metadata"]),
                "principal": principal,
                "provider_status": desired["provider_status"],
                "source_id": source_id,
                "source_kind": desired["source_kind"],
                "source_name": desired["source_name"],
                "source_url": desired["source_url"],
                "update_cycle": desired["update_cycle"],
            },
        )
    ).mappings().one()
    patched = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if patched is None:
        raise RuntimeError("patched curated source could not be read")
    return patched


async def archive_curated_source_command(
    session: AsyncSession,
    *,
    source_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedSource | None:
    """source archive와 dependent candidate reconcile을 원자 수행한다."""

    if await get_curated_source(session, source_id=source_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_source_command(
                  CAST(:source_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "command_id": command_id,
                "expected_revision": expected_revision,
                "principal": principal,
                "reason_code": reason_code,
                "source_id": source_id,
            },
        )
    ).mappings().one()
    archived = await get_curated_source(
        session, source_id=str(result["o_source_id"])
    )
    if archived is None:
        raise RuntimeError("archived curated source could not be read")
    return archived


async def create_curated_source_rule(
    session: AsyncSession,
    *,
    theme_id: str,
    source_id: str,
    place_kind: str | None = None,
    category: str | None = None,
    region_scope: Mapping[str, Any] | None = None,
    detail_selector: Mapping[str, Any] | None = None,
    default_action: str = "candidate",
    priority: int = 0,
    enabled: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> CuratedSourceRule:
    """curated source rule을 생성한다."""

    _validate_choice(default_action, _RULE_ACTIONS, "default_action")
    row = (
        await session.execute(
            text(
                """
                INSERT INTO feature.curated_source_rules (
                    theme_id, source_id, place_kind, category,
                    region_scope, detail_selector, default_action, priority,
                    enabled, metadata, updated_at
                ) VALUES (
                    CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                    :place_kind, :category, CAST(:region_scope_json AS jsonb),
                    CAST(:detail_selector_json AS jsonb),
                    :default_action, :priority, :enabled,
                    CAST(:metadata_json AS jsonb), now()
                )
                RETURNING rule_id::text AS rule_id
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "place_kind": place_kind,
                "category": category,
                "region_scope_json": _json_dumps(region_scope),
                "detail_selector_json": (
                    _json_dumps(detail_selector) if detail_selector else None
                ),
                "default_action": default_action,
                "priority": priority,
                "enabled": enabled,
                "metadata_json": _json_dumps(metadata),
            },
        )
    ).mappings().one()
    rules = await list_curated_source_rules(
        session,
        limit=1,
    )
    created = [rule for rule in rules if rule.rule_id == str(row["rule_id"])]
    if created:
        return created[0]
    refreshed = await _get_rule(session, str(row["rule_id"]))
    if refreshed is None:
        raise RuntimeError("created curated source rule could not be read")
    return refreshed


async def update_curated_source_rule(
    session: AsyncSession,
    *,
    rule_id: str,
    updates: Mapping[str, Any],
) -> CuratedSourceRule | None:
    """curated source rule을 부분 수정한다."""

    allowed = {
        "place_kind",
        "category",
        "region_scope",
        "detail_selector",
        "default_action",
        "priority",
        "enabled",
        "metadata",
    }
    row = await _update_simple(
        session,
        table="feature.curated_source_rules",
        id_column="rule_id",
        id_value=rule_id,
        updates=updates,
        allowed=allowed,
        choice_fields={"default_action": _RULE_ACTIONS},
        returning="rule_id::text AS rule_id",
    )
    if row is None:
        return None
    return await _get_rule(session, str(row["rule_id"]))


async def create_curated_source_rule_command(
    session: AsyncSession,
    *,
    theme_id: str,
    source_id: str,
    place_kind: str | None = None,
    category: str | None = None,
    region_scope: Mapping[str, Any] | None = None,
    detail_selector: Mapping[str, Any] | None = None,
    default_action: str = "candidate",
    priority: int = 0,
    enabled: bool = True,
    metadata: Mapping[str, Any] | None = None,
    command_id: int,
    principal: str,
) -> CuratedSourceRule:
    """domain command에 결박된 retained source rule create를 실행한다."""

    _validate_choice(default_action, _TYPED_RULE_ACTIONS, "default_action")
    result = (
        await session.execute(
            text(
                """
                CALL feature.create_curated_source_rule_command(
                  CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
                  :place_kind, :category, CAST(:region_scope_json AS jsonb),
                  CAST(:detail_selector_json AS jsonb), :default_action,
                  :priority, :enabled, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "place_kind": place_kind,
                "category": category,
                "region_scope_json": _json_dumps(region_scope),
                "detail_selector_json": (
                    _json_dumps(detail_selector)
                    if detail_selector is not None
                    else None
                ),
                "default_action": default_action,
                "priority": priority,
                "enabled": enabled,
                "metadata_json": _json_dumps(metadata),
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    rule = await _get_rule(session, str(result["o_rule_id"]))
    if rule is None:
        raise RuntimeError("created curated source rule could not be read")
    return rule


async def patch_curated_source_rule_command(
    session: AsyncSession,
    *,
    rule_id: str,
    expected_revision: int,
    updates: Mapping[str, Any],
    command_id: int,
    principal: str,
) -> CuratedSourceRule | None:
    """현재 row를 full desired command input으로 만든 뒤 CAS patch한다."""

    allowed = {
        "place_kind",
        "category",
        "region_scope",
        "detail_selector",
        "default_action",
        "priority",
        "enabled",
        "metadata",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")
    current = await _get_rule(session, rule_id)
    if current is None:
        return None
    desired: dict[str, Any] = {
        "place_kind": current.place_kind,
        "category": current.category,
        "region_scope": current.region_scope,
        "detail_selector": current.detail_selector,
        "default_action": current.default_action,
        "priority": current.priority,
        "enabled": current.enabled,
        "metadata": current.metadata,
    }
    desired.update(updates)
    default_action = desired["default_action"]
    if not isinstance(default_action, str):
        raise ValueError("default_action must not be null")
    _validate_choice(default_action, _TYPED_RULE_ACTIONS, "default_action")
    result = (
        await session.execute(
            text(
                """
                CALL feature.patch_curated_source_rule_command(
                  CAST(:rule_id AS uuid), :expected_revision,
                  :place_kind, :category, CAST(:region_scope_json AS jsonb),
                  CAST(:detail_selector_json AS jsonb), :default_action,
                  :priority, :enabled, CAST(:metadata_json AS jsonb),
                  :command_id, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "rule_id": rule_id,
                "expected_revision": expected_revision,
                "place_kind": desired["place_kind"],
                "category": desired["category"],
                "region_scope_json": _json_dumps(desired["region_scope"]),
                "detail_selector_json": (
                    _json_dumps(desired["detail_selector"])
                    if desired["detail_selector"] is not None
                    else None
                ),
                "default_action": default_action,
                "priority": desired["priority"],
                "enabled": desired["enabled"],
                "metadata_json": _json_dumps(desired["metadata"]),
                "command_id": command_id,
                "principal": principal,
            },
        )
    ).mappings().one()
    updated = await _get_rule(session, str(result["o_rule_id"]))
    if updated is None:
        raise RuntimeError("patched curated source rule could not be read")
    return updated


async def archive_curated_source_rule_command(
    session: AsyncSession,
    *,
    rule_id: str,
    expected_revision: int,
    command_id: int,
    reason_code: str,
    principal: str,
) -> CuratedSourceRule | None:
    """retained source rule을 CAS archive하고 candidate reconcile을 완료한다."""

    if await _get_rule(session, rule_id) is None:
        return None
    result = (
        await session.execute(
            text(
                """
                CALL feature.archive_curated_source_rule_command(
                  CAST(:rule_id AS uuid), :expected_revision, :command_id,
                  :reason_code, :principal, NULL, NULL, NULL
                )
                """
            ),
            {
                "rule_id": rule_id,
                "expected_revision": expected_revision,
                "command_id": command_id,
                "reason_code": reason_code,
                "principal": principal,
            },
        )
    ).mappings().one()
    archived = await _get_rule(session, str(result["o_rule_id"]))
    if archived is None:
        raise RuntimeError("archived curated source rule could not be read")
    return archived


async def _get_rule(session: AsyncSession, rule_id: str) -> CuratedSourceRule | None:
    rows = (
        await session.execute(
            text(
                f"""
                SELECT {_RULE_COLUMNS}
                FROM feature.curated_source_rules AS r
                JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
                JOIN feature.curated_sources AS s ON s.source_id = r.source_id
                JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = s.provider_dataset_id
                WHERE r.rule_id = CAST(:rule_id AS uuid)
                """
            ),
            {"rule_id": rule_id},
        )
    ).mappings().first()
    return _rule(rows) if rows is not None else None


async def _update_simple(
    session: AsyncSession,
    *,
    table: str,
    id_column: str,
    id_value: str,
    updates: Mapping[str, Any],
    allowed: set[str],
    choice_fields: Mapping[str, frozenset[str]],
    returning: str,
) -> Any | None:
    set_parts: list[str] = []
    params: dict[str, Any] = {"id_value": id_value}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported update field: {key}")
        if key in choice_fields:
            _validate_choice(str(value), choice_fields[key], key)
        if key in {"metadata", "region_scope", "detail_selector"}:
            param_name = f"{key}_json"
            set_parts.append(f"{key} = CAST(:{param_name} AS jsonb)")
            params[param_name] = (
                None
                if key == "detail_selector" and value is None
                else _json_dumps(value)
            )
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    if not set_parts:
        return None
    set_parts.append("updated_at = now()")
    return (
        await session.execute(
            text(
                f"""
                UPDATE {table}
                SET {", ".join(set_parts)}
                WHERE {id_column} = CAST(:id_value AS uuid)
                RETURNING {returning}
                """
            ),
            params,
        )
    ).mappings().first()
