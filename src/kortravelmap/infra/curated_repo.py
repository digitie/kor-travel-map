"""``feature.curated_*`` repository (T-223c-1).

테마형 큐레이션은 ``feature.features``를 복제하지 않는 overlay다. 본 모듈은
raw SQL만 제공하고, HTTP envelope/DTO는 admin 패키지 라우터에서 담당한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CuratedFeature",
    "CuratedFeaturePage",
    "CuratedSource",
    "CuratedSourceRule",
    "CuratedTheme",
    "CuratedFeatureCandidatesResult",
    "CuratedFeatureStatusSweepResult",
    "CuratedSourceMetadataRefreshResult",
    "CuratedFeatureDetailItem",
    "CuratedFeatureDetailSnapshot",
    "CuratedFeatureDetailSnapshotMaterializeResult",
    "RuleApplyResult",
    "archive_curated_feature",
    "apply_enabled_curated_source_rules",
    "apply_curated_source_rule",
    "create_curated_feature",
    "create_curated_source",
    "create_curated_source_rule",
    "create_curated_theme",
    "get_curated_feature",
    "get_curated_feature_detail_snapshot",
    "list_curated_features",
    "list_curated_source_rules",
    "list_curated_sources",
    "list_curated_themes",
    "materialize_curated_feature_detail_snapshots",
    "refresh_curated_source_metadata",
    "set_curated_feature_status",
    "sweep_curated_feature_status",
    "update_curated_feature",
    "update_curated_source",
    "update_curated_source_rule",
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
    default_curated: bool
    visibility: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CuratedSource:
    """``feature.curated_sources`` projection."""

    source_id: str
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


@dataclass(frozen=True)
class CuratedSourceRule:
    """``feature.curated_source_rules`` projection."""

    rule_id: str
    theme_id: str
    theme_slug: str
    source_id: str
    provider: str
    dataset_key: str
    place_kind: str | None
    category: str | None
    region_scope: dict[str, Any]
    default_action: str
    priority: int
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CuratedFeature:
    """curated overlay + feature/source/theme projection."""

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


@dataclass(frozen=True)
class RuleApplyResult:
    """source rule apply 결과."""

    rule_id: str
    inserted_or_updated: int


@dataclass(frozen=True)
class CuratedSourceMetadataRefreshResult:
    """curated source metadata refresh 결과."""

    sources_checked: int
    sources_with_records: int
    source_records_total: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {
            "sources_checked": self.sources_checked,
            "sources_with_records": self.sources_with_records,
            "source_records_total": self.source_records_total,
        }


@dataclass(frozen=True)
class CuratedFeatureCandidatesResult:
    """enabled curated source rule 적용 결과."""

    rules_applied: int
    inserted_or_updated: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {
            "rules_applied": self.rules_applied,
            "inserted_or_updated": self.inserted_or_updated,
        }


@dataclass(frozen=True)
class CuratedFeatureStatusSweepResult:
    """underlying feature 상태 변화에 따른 curated overlay archive 결과."""

    archived: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {"archived": self.archived}


@dataclass(frozen=True)
class CuratedFeatureDetailSnapshotMaterializeResult:
    """curated feature detail snapshot cache materialize 결과."""

    curated_features_total: int
    snapshots_materialized: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {
            "curated_features_total": self.curated_features_total,
            "snapshots_materialized": self.snapshots_materialized,
        }


_THEME_COLUMNS: Final[str] = (
    "theme_id::text AS theme_id, theme_slug, theme_name, theme_description, "
    "theme_group, default_curated, visibility, metadata, created_at, updated_at"
)
_SOURCE_COLUMNS: Final[str] = (
    "source_id::text AS source_id, provider, dataset_key, source_name, source_url, "
    "source_kind, license, update_cycle, last_source_modified_at, last_checked_at, "
    "next_expected_at, row_count, freshness_note, provider_status, metadata, "
    "created_at, updated_at"
)
_RULE_COLUMNS: Final[str] = (
    "r.rule_id::text AS rule_id, r.theme_id::text AS theme_id, t.theme_slug, "
    "r.source_id::text AS source_id, s.provider, r.dataset_key, r.place_kind, "
    "r.category, r.region_scope, r.default_action, r.priority, r.enabled, "
    "r.metadata, r.created_at, r.updated_at"
)
_FEATURE_COLUMNS: Final[str] = """
    cf.curated_feature_id::text AS curated_feature_id,
    cf.theme_id::text AS theme_id,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    cf.feature_id,
    f.name AS feature_name,
    f.category AS feature_category,
    f.kind AS feature_kind,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    f.detail,
    cf.source_id::text AS source_id,
    s.provider,
    s.dataset_key,
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
_FEATURE_FROM_SQL: Final[str] = """
FROM feature.curated_features AS cf
JOIN feature.curated_themes AS t ON t.theme_id = cf.theme_id
JOIN feature.curated_sources AS s ON s.source_id = cf.source_id
JOIN feature.features AS f ON f.feature_id = cf.feature_id
"""

_LIST_THEMES_SQL: Final[str] = f"""
SELECT {_THEME_COLUMNS}
FROM feature.curated_themes
WHERE (CAST(:visibility AS text) IS NULL OR visibility = CAST(:visibility AS text))
  AND (CAST(:theme_group AS text) IS NULL OR theme_group = CAST(:theme_group AS text))
ORDER BY theme_group, theme_slug
LIMIT :limit
"""

_LIST_SOURCES_SQL: Final[str] = f"""
SELECT {_SOURCE_COLUMNS}
FROM feature.curated_sources
WHERE (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR dataset_key = CAST(:dataset_key AS text)
  )
  AND (
    CAST(:provider_status AS text) IS NULL
    OR provider_status = CAST(:provider_status AS text)
  )
ORDER BY provider, dataset_key
LIMIT :limit
"""

_LIST_RULES_SQL: Final[str] = f"""
SELECT {_RULE_COLUMNS}
FROM feature.curated_source_rules AS r
JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
JOIN feature.curated_sources AS s ON s.source_id = r.source_id
WHERE (CAST(:theme_id AS uuid) IS NULL OR r.theme_id = CAST(:theme_id AS uuid))
  AND (
    CAST(:theme_slug AS text) IS NULL
    OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
  AND (CAST(:provider AS text) IS NULL OR s.provider = CAST(:provider AS text))
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR r.dataset_key = CAST(:dataset_key AS text)
  )
  AND (CAST(:enabled AS boolean) IS NULL OR r.enabled = CAST(:enabled AS boolean))
ORDER BY t.theme_slug, s.provider, r.dataset_key, r.priority DESC, r.rule_id
LIMIT :limit
"""

_LIST_FEATURES_SQL: Final[str] = f"""
SELECT {_FEATURE_COLUMNS}
{_FEATURE_FROM_SQL}
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
  AND (CAST(:provider AS text) IS NULL OR s.provider = CAST(:provider AS text))
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR s.dataset_key = CAST(:dataset_key AS text)
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
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (
      cf.updated_at,
      cf.curated_feature_id
    ) < (
      CAST(:cursor_updated_at AS timestamptz),
      CAST(:cursor_curated_feature_id AS uuid)
    )
  )
ORDER BY cf.updated_at DESC, cf.curated_feature_id DESC
LIMIT :limit
"""

_GET_FEATURE_SQL: Final[str] = f"""
SELECT {_FEATURE_COLUMNS}
{_FEATURE_FROM_SQL}
WHERE cf.curated_feature_id = CAST(:curated_feature_id AS uuid)
  AND (CAST(:include_archived AS boolean) OR cf.archived_at IS NULL)
"""

_CREATE_FEATURE_SQL: Final[str] = """
INSERT INTO feature.curated_features (
    theme_id, feature_id, source_id, source_record_key, curation_status,
    selection_origin, selected_by, selected_at, rejected_by, rejected_at,
    rejection_reason, rank_score, display_title, display_summary,
    curation_relation, reuse_policy, metadata, updated_at
) VALUES (
    CAST(:theme_id AS uuid), :feature_id, CAST(:source_id AS uuid),
    CAST(:source_record_key AS text), :curation_status, :selection_origin,
    :selected_by,
    CASE WHEN CAST(:selected_now AS boolean) THEN now() ELSE NULL END,
    :rejected_by,
    CASE WHEN CAST(:rejected_now AS boolean) THEN now() ELSE NULL END,
    :rejection_reason,
    :rank_score, :display_title, :display_summary, :curation_relation,
    :reuse_policy, CAST(:metadata_json AS jsonb), now()
)
RETURNING curated_feature_id::text
"""

_UPDATE_FEATURE_BASE_SQL: Final[str] = """
UPDATE feature.curated_features
SET {set_clause}
WHERE curated_feature_id = CAST(:curated_feature_id AS uuid)
RETURNING curated_feature_id::text
"""

_APPLY_RULE_SQL: Final[str] = """
WITH rule AS (
    SELECT
        r.rule_id,
        r.theme_id,
        r.source_id,
        r.dataset_key,
        r.place_kind,
        r.category,
        r.region_scope,
        r.default_action,
        r.priority,
        COALESCE(
            r.metadata ->> 'curation_relation',
            'nearby_option'
        ) AS relation,
        COALESCE(
            r.metadata ->> 'reuse_policy',
            'manual_review'
        ) AS reuse_policy
    FROM feature.curated_source_rules AS r
    WHERE r.rule_id = CAST(:rule_id AS uuid)
      AND r.enabled
      AND r.default_action IN ('candidate','curated')
),
upserted AS (
    INSERT INTO feature.curated_features (
        theme_id, feature_id, source_id, source_record_key, curation_status,
        selection_origin, selected_at, rank_score, display_title,
        curation_relation, reuse_policy, metadata, updated_at
    )
    SELECT DISTINCT ON (f.feature_id)
        rule.theme_id,
        f.feature_id,
        rule.source_id,
        sr.source_record_key,
        rule.default_action,
        'source_rule',
        CASE WHEN rule.default_action = 'curated' THEN now() ELSE NULL END,
        rule.priority,
        CASE
            WHEN s.provider = 'kor-travel-concierge-youtube'
             AND s.dataset_key = 'youtube_place_candidates'
            THEN NULLIF(BTRIM(COALESCE(
                NULLIF(f.detail #>> '{payload,kor_travel_concierge,youtube,source_title}', ''),
                NULLIF(f.detail #>> '{payload,kor_travel_concierge,youtube,playlist_title}', ''),
                NULLIF(f.detail #>> '{payload,kor_travel_concierge,youtube,channel_title}', ''),
                NULLIF(
                    f.detail #>> '{payload,kor_travel_concierge,youtube,source_search_query}',
                    ''
                ),
                NULLIF(
                    f.detail #>> '{payload,kor_travel_concierge,youtube,corrected_search_query}',
                    ''
                ),
                NULLIF(f.detail #>> '{payload,kor_travel_concierge,youtube,search_query}', ''),
                NULLIF(f.detail #>> '{facility_info,youtube_playlist_title}', ''),
                NULLIF(f.detail #>> '{facility_info,youtube_channel_title}', '')
            )), '')
            WHEN s.provider IN (
                'data.go.kr-standard',
                'python-airkorea-api',
                'python-datagokr-api',
                'python-kasi-api',
                'python-khoa-api',
                'python-kma-api',
                'python-knps-api',
                'python-krairport-api',
                'python-krex-api',
                'python-krforest-api',
                'python-krheritage-api',
                'python-mcst-api',
                'python-mois-api',
                'python-opinet-api',
                'python-visitkorea-api'
            ) THEN s.provider
            ELSE NULL
        END,
        CASE
            WHEN rule.relation IN (
                'primary_stop','food_stop','cafe_stop','bookstore_stop',
                'nearby_option','accessibility_support','pet_support',
                'family_support','theme_area_anchor'
            ) THEN rule.relation
            ELSE 'nearby_option'
        END,
        CASE
            WHEN rule.reuse_policy IN ('allowed','blocked','manual_review')
            THEN rule.reuse_policy
            ELSE 'manual_review'
        END,
        jsonb_build_object('rule_id', rule.rule_id::text, 'applied_by', 'source_rule'),
        now()
    FROM rule
    JOIN feature.curated_sources AS s ON s.source_id = rule.source_id
    JOIN provider_sync.source_records AS sr
      ON sr.provider = s.provider
     AND sr.dataset_key = s.dataset_key
    JOIN provider_sync.source_links AS sl
      ON sl.source_record_key = sr.source_record_key
    JOIN feature.features AS f ON f.feature_id = sl.feature_id
    WHERE f.deleted_at IS NULL
      AND f.status = 'active'
      AND (
        rule.place_kind IS NULL
        OR f.detail ->> 'place_kind' = rule.place_kind
        OR f.detail ->> 'event_kind' = rule.place_kind
      )
      AND (rule.category IS NULL OR f.category = rule.category)
      AND (
        rule.region_scope = '{}'::jsonb
        OR (
          (NOT rule.region_scope ? 'sido_code'
           OR f.sido_code = rule.region_scope ->> 'sido_code')
          AND (NOT rule.region_scope ? 'sigungu_code'
           OR f.sigungu_code = rule.region_scope ->> 'sigungu_code')
        )
      )
      AND NOT EXISTS (
        SELECT 1
        FROM feature.curated_features AS old_cf
        WHERE old_cf.theme_id = rule.theme_id
          AND old_cf.feature_id = f.feature_id
          AND old_cf.curation_status IN ('rejected','archived')
      )
    ORDER BY f.feature_id, sl.is_primary_source DESC, sr.imported_at DESC
    ON CONFLICT (theme_id, feature_id) WHERE archived_at IS NULL
    DO UPDATE SET
        source_id = EXCLUDED.source_id,
        source_record_key = EXCLUDED.source_record_key,
        rank_score = GREATEST(feature.curated_features.rank_score, EXCLUDED.rank_score),
        display_title = COALESCE(
            feature.curated_features.display_title,
            EXCLUDED.display_title
        ),
        curation_relation = EXCLUDED.curation_relation,
        reuse_policy = EXCLUDED.reuse_policy,
        metadata = feature.curated_features.metadata || EXCLUDED.metadata,
        updated_at = now(),
        content_version = feature.curated_features.content_version + 1
    WHERE feature.curated_features.curation_status NOT IN ('rejected','archived')
    RETURNING curated_feature_id
)
SELECT count(*)::int AS affected_count FROM upserted
"""

_REFRESH_SOURCE_METADATA_SQL: Final[str] = """
WITH source_scope AS (
    SELECT source_id, provider, dataset_key
    FROM feature.curated_sources
    WHERE (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
      AND (
        CAST(:dataset_key AS text) IS NULL
        OR dataset_key = CAST(:dataset_key AS text)
      )
),
counted AS (
    SELECT
        s.source_id,
        count(sr.source_record_key)::int AS record_count,
        max(sr.imported_at) AS last_imported_at
    FROM source_scope AS s
    LEFT JOIN provider_sync.source_records AS sr
      ON sr.provider = s.provider
     AND sr.dataset_key = s.dataset_key
    GROUP BY s.source_id
),
updated AS (
    UPDATE feature.curated_sources AS s
    SET
        last_checked_at = now(),
        row_count = CASE
            WHEN c.record_count > 0 THEN c.record_count
            ELSE s.row_count
        END,
        metadata = s.metadata || jsonb_build_object(
            'source_record_count', c.record_count,
            'last_record_imported_at', c.last_imported_at
        ),
        updated_at = now()
    FROM counted AS c
    WHERE s.source_id = c.source_id
    RETURNING c.record_count
)
SELECT
    count(*)::int AS sources_checked,
    count(*) FILTER (WHERE record_count > 0)::int AS sources_with_records,
    COALESCE(sum(record_count), 0)::int AS source_records_total
FROM updated
"""

_SWEEP_CURATED_STATUS_SQL: Final[str] = """
WITH archived AS (
    UPDATE feature.curated_features AS cf
    SET
        curation_status = 'archived',
        archived_at = COALESCE(cf.archived_at, now()),
        updated_at = now(),
        content_version = cf.content_version + 1,
        metadata = cf.metadata || jsonb_build_object(
            'status_sweep', 'underlying_feature_inactive_or_deleted'
        )
    FROM feature.features AS f
    WHERE cf.feature_id = f.feature_id
      AND cf.archived_at IS NULL
      AND cf.curation_status IN ('candidate','curated')
      AND (f.deleted_at IS NOT NULL OR f.status <> 'active')
    RETURNING cf.curated_feature_id
)
SELECT count(*)::int AS archived_count FROM archived
"""

_UPSERT_FEATURE_DETAIL_SNAPSHOT_SQL: Final[str] = """
INSERT INTO feature.curated_feature_detail_snapshots (
    curated_feature_id, content_version, etag, snapshot, materialized_at, updated_at
) VALUES (
    CAST(:curated_feature_id AS uuid), :content_version, :etag,
    CAST(:snapshot_json AS jsonb), now(), :updated_at
)
ON CONFLICT (curated_feature_id)
DO UPDATE SET
    content_version = EXCLUDED.content_version,
    etag = EXCLUDED.etag,
    snapshot = EXCLUDED.snapshot,
    materialized_at = now(),
    updated_at = EXCLUDED.updated_at
WHERE feature.curated_feature_detail_snapshots.content_version IS DISTINCT FROM
      EXCLUDED.content_version
   OR feature.curated_feature_detail_snapshots.etag IS DISTINCT FROM EXCLUDED.etag
RETURNING curated_feature_id::text AS curated_feature_id
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
        default_curated=bool(row["default_curated"]),
        visibility=str(row["visibility"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _source(row: Any) -> CuratedSource:
    return CuratedSource(
        source_id=str(row["source_id"]),
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
    )


def _rule(row: Any) -> CuratedSourceRule:
    return CuratedSourceRule(
        rule_id=str(row["rule_id"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        source_id=str(row["source_id"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        place_kind=row["place_kind"],
        category=row["category"],
        region_scope=_json_object(row["region_scope"]),
        default_action=str(row["default_action"]),
        priority=int(row["priority"]),
        enabled=bool(row["enabled"]),
        metadata=_json_object(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _feature(row: Any) -> CuratedFeature:
    lon = row["lon"]
    lat = row["lat"]
    return CuratedFeature(
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


def _feature_snapshot(feature: CuratedFeature) -> dict[str, Any]:
    return {
        "feature_id": feature.feature_id,
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
        feature_id=feature.feature_id,
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


def _feature_detail_snapshot_payload(
    snapshot: CuratedFeatureDetailSnapshot,
) -> dict[str, Any]:
    return {
        "curated_feature_id": snapshot.curated_feature_id,
        "version": snapshot.version,
        "etag": snapshot.etag,
        "updated_at": snapshot.updated_at.isoformat(),
        "theme": snapshot.theme,
        "content": snapshot.content,
        "source": snapshot.source,
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
            for item in snapshot.items
        ],
    }


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
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_theme(row) for row in rows)


async def list_curated_sources(
    session: AsyncSession,
    *,
    provider: str | None = None,
    dataset_key: str | None = None,
    provider_status: str | None = None,
    limit: int = 200,
) -> tuple[CuratedSource, ...]:
    """curated source metadata 목록을 조회한다."""

    if provider_status is not None:
        _validate_choice(provider_status, _PROVIDER_STATUSES, "provider_status")
    rows = (
        await session.execute(
            text(_LIST_SOURCES_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "provider_status": provider_status,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_source(row) for row in rows)


async def list_curated_source_rules(
    session: AsyncSession,
    *,
    theme_id: str | None = None,
    theme_slug: str | None = None,
    source_id: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    enabled: bool | None = None,
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
                "provider": provider,
                "dataset_key": dataset_key,
                "enabled": enabled,
                "limit": _safe_limit(limit),
            },
        )
    ).mappings().all()
    return tuple(_rule(row) for row in rows)


async def list_curated_features(
    session: AsyncSession,
    *,
    theme_id: str | None = None,
    theme_slug: str | None = None,
    source_id: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
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
    include_archived: bool = False,
    page_size: int = 50,
    cursor: str | None = None,
) -> CuratedFeaturePage:
    """curated feature 목록을 keyset으로 조회한다."""

    if curation_status is not None:
        _validate_choice(curation_status, _CURATION_STATUSES, "curation_status")
    safe_page_size = _safe_limit(page_size, _MAX_PAGE_SIZE)
    rows = (
        await session.execute(
            text(_LIST_FEATURES_SQL),
            {
                "theme_id": theme_id,
                "theme_slug": theme_slug,
                "source_id": source_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "curation_status": curation_status,
                "region_code": region_code,
                "sido_code": sido_code,
                "sigungu_code": sigungu_code,
                "q_pattern": _q_pattern(q),
                "feature_name_pattern": _q_pattern(feature_name),
                "display_title": _text(display_title),
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
) -> CuratedFeature | None:
    """curated feature 단건을 조회한다."""

    row = (
        await session.execute(
            text(_GET_FEATURE_SQL),
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
        }
    if curation_status == "rejected":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "rejected_by": actor,
            "rejected_at": now_expr,
            "rejection_reason": reason,
        }
    if curation_status == "candidate":
        return {
            "curation_status": curation_status,
            "selection_origin": "admin",
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
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
) -> CuratedFeature:
    """curated feature overlay 1건을 생성한다. commit은 호출자 책임."""

    _validate_choice(curation_status, _CURATION_STATUSES, "curation_status")
    _validate_choice(selection_origin, _SELECTION_ORIGINS, "selection_origin")
    _validate_choice(curation_relation, _CURATION_RELATIONS, "curation_relation")
    _validate_choice(reuse_policy, _REUSE_POLICIES, "reuse_policy")
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
        if key == "curation_relation":
            _validate_choice(str(value), _CURATION_RELATIONS, key)
        if key == "reuse_policy":
            _validate_choice(str(value), _REUSE_POLICIES, key)
        if key == "metadata":
            set_parts.append("metadata = CAST(:metadata_json AS jsonb)")
            params["metadata_json"] = _json_dumps(value)
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    if not set_parts:
        return await get_curated_feature(
            session,
            curated_feature_id=curated_feature_id,
            include_archived=True,
        )
    set_parts.extend(["updated_at = now()", "content_version = content_version + 1"])
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
    set_parts.extend(["updated_at = now()", "content_version = content_version + 1"])
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


async def apply_curated_source_rule(
    session: AsyncSession,
    *,
    rule_id: str,
) -> RuleApplyResult:
    """source rule을 현재 feature/source link에 적용한다."""

    row = (
        await session.execute(text(_APPLY_RULE_SQL), {"rule_id": rule_id})
    ).mappings().one()
    return RuleApplyResult(
        rule_id=rule_id,
        inserted_or_updated=int(row["affected_count"]),
    )


async def refresh_curated_source_metadata(
    session: AsyncSession,
    *,
    provider: str | None = None,
    dataset_key: str | None = None,
) -> CuratedSourceMetadataRefreshResult:
    """source_records 기준으로 curated source metadata를 갱신한다."""

    row = (
        await session.execute(
            text(_REFRESH_SOURCE_METADATA_SQL),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).mappings().one()
    return CuratedSourceMetadataRefreshResult(
        sources_checked=int(row["sources_checked"]),
        sources_with_records=int(row["sources_with_records"]),
        source_records_total=int(row["source_records_total"]),
    )


async def apply_enabled_curated_source_rules(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> CuratedFeatureCandidatesResult:
    """enabled curated source rule을 현재 feature/source link에 적용한다."""

    rules = await list_curated_source_rules(
        session,
        enabled=True,
        limit=limit,
    )
    total = 0
    for rule in rules:
        result = await apply_curated_source_rule(session, rule_id=rule.rule_id)
        total += result.inserted_or_updated
    return CuratedFeatureCandidatesResult(
        rules_applied=len(rules),
        inserted_or_updated=total,
    )


async def sweep_curated_feature_status(
    session: AsyncSession,
) -> CuratedFeatureStatusSweepResult:
    """inactive/deleted feature가 가리키는 curated overlay를 archive한다."""

    row = (
        await session.execute(text(_SWEEP_CURATED_STATUS_SQL))
    ).mappings().one()
    return CuratedFeatureStatusSweepResult(archived=int(row["archived_count"]))


async def materialize_curated_feature_detail_snapshots(
    session: AsyncSession,
    *,
    theme_slug: str | None = None,
    limit: int = 500,
) -> CuratedFeatureDetailSnapshotMaterializeResult:
    """curated feature detail snapshot을 cache table에 materialize한다."""

    safe_limit = _safe_limit(limit)
    cursor: str | None = None
    features_seen = 0
    snapshots_materialized = 0
    while features_seen < safe_limit:
        page_size = min(_MAX_PAGE_SIZE, safe_limit - features_seen)
        page = await list_curated_features(
            session,
            theme_slug=theme_slug,
            curation_status="curated",
            page_size=page_size,
            cursor=cursor,
        )
        if not page.items:
            break
        for feature in page.items:
            snapshot = _feature_detail_snapshot(feature)
            row = (
                await session.execute(
                    text(_UPSERT_FEATURE_DETAIL_SNAPSHOT_SQL),
                    {
                        "curated_feature_id": snapshot.curated_feature_id,
                        "content_version": snapshot.version,
                        "etag": snapshot.etag,
                        "snapshot_json": json.dumps(
                            _feature_detail_snapshot_payload(snapshot),
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        ),
                        "updated_at": snapshot.updated_at,
                    },
                )
            ).mappings().first()
            if row is not None:
                snapshots_materialized += 1
        features_seen += len(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return CuratedFeatureDetailSnapshotMaterializeResult(
        curated_features_total=features_seen,
        snapshots_materialized=snapshots_materialized,
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


async def create_curated_source(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
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
                f"""
                INSERT INTO feature.curated_sources (
                    provider, dataset_key, source_name, source_url, source_kind,
                    license, update_cycle, last_source_modified_at, last_checked_at,
                    next_expected_at, row_count, freshness_note, provider_status,
                    metadata, updated_at
                ) VALUES (
                    :provider, :dataset_key, :source_name, :source_url, :source_kind,
                    :license, :update_cycle, :last_source_modified_at, :last_checked_at,
                    :next_expected_at, :row_count, :freshness_note, :provider_status,
                    CAST(:metadata_json AS jsonb), now()
                )
                RETURNING {_SOURCE_COLUMNS}
                """
            ),
            {
                "provider": provider,
                "dataset_key": dataset_key,
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
    return _source(row)


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
        returning=_SOURCE_COLUMNS,
    )
    return _source(row) if row is not None else None


async def create_curated_source_rule(
    session: AsyncSession,
    *,
    theme_id: str,
    source_id: str,
    dataset_key: str,
    place_kind: str | None = None,
    category: str | None = None,
    region_scope: Mapping[str, Any] | None = None,
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
                    theme_id, source_id, dataset_key, place_kind, category,
                    region_scope, default_action, priority, enabled, metadata,
                    updated_at
                ) VALUES (
                    CAST(:theme_id AS uuid), CAST(:source_id AS uuid), :dataset_key,
                    :place_kind, :category, CAST(:region_scope_json AS jsonb),
                    :default_action, :priority, :enabled,
                    CAST(:metadata_json AS jsonb), now()
                )
                RETURNING rule_id::text AS rule_id
                """
            ),
            {
                "theme_id": theme_id,
                "source_id": source_id,
                "dataset_key": dataset_key,
                "place_kind": place_kind,
                "category": category,
                "region_scope_json": _json_dumps(region_scope),
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
        "dataset_key",
        "place_kind",
        "category",
        "region_scope",
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


async def _get_rule(session: AsyncSession, rule_id: str) -> CuratedSourceRule | None:
    rows = (
        await session.execute(
            text(
                f"""
                SELECT {_RULE_COLUMNS}
                FROM feature.curated_source_rules AS r
                JOIN feature.curated_themes AS t ON t.theme_id = r.theme_id
                JOIN feature.curated_sources AS s ON s.source_id = r.source_id
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
        if key in {"metadata", "region_scope"}:
            param_name = f"{key}_json"
            set_parts.append(f"{key} = CAST(:{param_name} AS jsonb)")
            params[param_name] = _json_dumps(value)
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
