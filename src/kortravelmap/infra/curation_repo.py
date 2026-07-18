"""큐레이션 collection/item 저장소.

물리 위치와 장소 본문은 ``feature.features``가 소유하고, 이 모듈은 테마형 묶음과
기존 Feature membership만 저장한다. 쿼리는 ADR-004에 따라 raw SQL만 사용한다.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CurationCollection",
    "CurationImportPlan",
    "CurationImportResult",
    "CurationItem",
    "FeatureCurationGroup",
    "FeatureMatch",
    "FeatureMatchRequest",
    "ResolvedCurationImportRow",
    "ResolvedCurationIdentityIssue",
    "add_curation_item",
    "archive_curation_item",
    "archive_curation_collection",
    "create_curation_collection",
    "get_curation_collection",
    "get_curation_item",
    "get_feature_curation_group",
    "import_curation_rows",
    "list_curation_collections",
    "list_curation_items_by_feature_ids",
    "list_feature_curation_groups",
    "preview_curation_import",
    "resolve_feature_match",
    "resolve_feature_matches",
    "upsert_curation_theme",
    "update_curation_item",
    "update_curation_collection",
    "validate_resolved_curation_identities",
]

CollectionStatus = Literal["draft", "published", "archived"]
CollectionVisibility = Literal["admin_only", "public"]
ItemStatus = Literal["candidate", "included", "rejected", "archived"]

_COLLECTION_STATUSES: Final = frozenset({"draft", "published", "archived"})
_VISIBILITIES: Final = frozenset({"admin_only", "public"})
_ITEM_STATUSES: Final = frozenset({"candidate", "included", "rejected", "archived"})
_RELATIONS: Final = frozenset(
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
_REUSE_POLICIES: Final = frozenset({"allowed", "blocked", "manual_review"})
_POSTGRES_INTEGER_MAX: Final = 2_147_483_647


@dataclass(frozen=True)
class CurationCollection:
    collection_id: str
    collection_key: str
    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    source_id: str | None
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    title: str
    edition_key: str
    description: str | None
    status: str
    visibility: str
    metadata: dict[str, Any]
    item_count: int
    public_item_count: int
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class CurationItem:
    curation_item_id: str
    collection_id: str
    collection_key: str
    title: str
    edition_key: str
    theme_slug: str
    theme_name: str
    theme_group: str
    provider: str | None
    dataset_key: str | None
    source_name: str | None
    source_url: str | None
    feature_id: str | None
    feature_name: str | None
    feature_kind: str | None
    feature_category: str | None
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    source_record_key: str | None
    external_item_id: str
    place_name: str
    address_hint: str | None
    status: str
    sort_order: int
    item_title: str | None
    item_summary: str | None
    curation_relation: str
    reuse_policy: str
    metadata: dict[str, Any]
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class FeatureCurationGroup:
    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    status: str
    curations: tuple[CurationItem, ...]


@dataclass(frozen=True)
class FeatureMatch:
    feature_id: str
    name: str
    address: dict[str, Any]
    lon: float | None
    lat: float | None


@dataclass(frozen=True)
class FeatureMatchRequest:
    row_number: int
    feature_id: str | None
    place_name: str | None
    address_hint: str | None


@dataclass(frozen=True)
class ResolvedCurationImportRow:
    row_number: int
    collection_key: str
    theme_slug: str
    theme_name: str
    theme_group: str
    title: str
    edition_key: str
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None
    source_item_key: str
    feature_id: str | None
    place_name: str
    address_hint: str | None
    sort_order: int
    item_title: str | None
    item_summary: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ResolvedCurationIdentityIssue:
    """Feature 해소 뒤 드러난 authoritative item identity 충돌."""

    row_number: int
    code: str
    message: str


@dataclass(frozen=True)
class CurationImportPlan:
    """CSV authoritative replace가 만들 읽기 전용 변경 계획."""

    collections: int
    inserted: int
    updated: int
    removals: tuple[CurationItem, ...]


class CurationImportResult(TypedDict):
    """원자적 CSV replace가 실제 반영한 item 변화."""

    rows: int
    collections: int
    inserted: int
    updated: int
    removed: int
    removals: tuple[CurationItem, ...]


_COLLECTION_SELECT: Final[str] = """
SELECT
    c.collection_id::text AS collection_id,
    c.collection_key,
    c.theme_id::text AS theme_id,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    c.source_id::text AS source_id,
    s.provider,
    s.dataset_key,
    s.source_name,
    s.source_url,
    c.title,
    c.edition_key,
    c.description,
    c.status,
    c.visibility,
    c.metadata,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS count_item
        WHERE count_item.collection_id = c.collection_id
          AND count_item.archived_at IS NULL
    ) AS item_count,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS public_count_item
        WHERE public_count_item.collection_id = c.collection_id
          AND public_count_item.archived_at IS NULL
          AND public_count_item.status = 'included'
    ) AS public_item_count,
    c.created_by,
    c.updated_by,
    c.created_at,
    c.updated_at,
    c.archived_at
FROM feature.curation_collections AS c
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
"""

_ITEM_SELECT_FIELDS: Final[str] = """
    i.curation_item_id::text AS curation_item_id,
    i.collection_id::text AS collection_id,
    c.collection_key,
    c.title,
    c.edition_key,
    t.theme_slug,
    t.theme_name,
    t.theme_group,
    s.provider,
    s.dataset_key,
    s.source_name,
    s.source_url,
    i.feature_id,
    f.name AS feature_name,
    f.kind AS feature_kind,
    f.category AS feature_category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    EXISTS (
        SELECT 1
        FROM feature.public_features AS pf
        WHERE pf.feature_id = i.feature_id
    ) AS linked_feature_is_public,
    i.source_record_key,
    i.external_item_id,
    i.place_name,
    i.address_hint,
    i.status,
    i.sort_order,
    i.item_title,
    i.item_summary,
    i.curation_relation,
    i.reuse_policy,
    i.metadata,
    i.created_by,
    i.updated_by,
    i.created_at,
    i.updated_at,
    i.archived_at
"""

_ITEM_SELECT: Final[str] = (
    """
SELECT
"""
    + _ITEM_SELECT_FIELDS
    + """
FROM feature.curation_items AS i
JOIN feature.curation_collections AS c ON c.collection_id = i.collection_id
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN feature.features AS f ON f.feature_id = i.feature_id
"""
)

_LIST_COLLECTIONS_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE (:include_archived OR c.archived_at IS NULL)
  AND (CAST(:status AS text) IS NULL OR c.status = CAST(:status AS text))
  AND (
      CAST(:visibility AS text) IS NULL
      OR c.visibility = CAST(:visibility AS text)
  )
  AND (
      CAST(:theme_slug AS text) IS NULL
      OR t.theme_slug = CAST(:theme_slug AS text)
  )
  AND (
      CAST(:edition_key AS text) IS NULL
      OR c.edition_key = CAST(:edition_key AS text)
  )
  AND (
      CAST(:provider AS text) IS NULL
      OR s.provider = CAST(:provider AS text)
  )
  AND (
      CAST(:q AS text) IS NULL
      OR c.title ILIKE CAST(:q AS text)
      OR c.collection_key ILIKE CAST(:q AS text)
      OR t.theme_name ILIKE CAST(:q AS text)
  )
  AND (
      CAST(:cursor_updated_at AS timestamptz) IS NULL
      OR (c.updated_at, c.collection_id) < (
          CAST(:cursor_updated_at AS timestamptz),
          CAST(:cursor_collection_id AS uuid)
      )
  )
ORDER BY c.updated_at DESC, c.collection_id DESC
LIMIT :limit
"""
)

_GET_COLLECTION_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE c.collection_id = CAST(:collection_id AS uuid)
  AND (:include_archived OR c.archived_at IS NULL)
"""
)

_GET_COLLECTION_BY_KEY_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE c.collection_key = :collection_key
  AND (:include_archived OR c.archived_at IS NULL)
"""
)

_LIST_COLLECTION_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND (:include_archived OR i.archived_at IS NULL)
ORDER BY i.sort_order, i.curation_item_id
"""
)

_GET_COLLECTION_ITEM_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND i.curation_item_id = CAST(:curation_item_id AS uuid)
  AND (:include_archived OR i.archived_at IS NULL)
"""
)

_LIST_FEATURE_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.feature_id = :feature_id
  AND i.archived_at IS NULL
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
      )
  )
ORDER BY c.edition_key DESC, c.title, i.sort_order, i.curation_item_id
"""
)

_LIST_FEATURE_ITEMS_BATCH_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.feature_id = ANY(CAST(:feature_ids AS text[]))
  AND i.archived_at IS NULL
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
      )
  )
ORDER BY i.feature_id, c.edition_key DESC, c.title, i.sort_order,
         i.curation_item_id
"""
)

# 공개 큐레이션 group read — feature 공개 여부는 ADR-067
# ``feature.public_features`` projection이 정본이다(T-VN-04, F-1). 과거의
# ``status NOT IN ('deleted','hidden')`` 재구현은 draft/broken/inactive를
# 노출했다. ``:public_only``는 collection/item 상태 필터에만 관여한다.
_LIST_GROUP_KEYS_SQL: Final[str] = """
SELECT f.feature_id
FROM feature.public_features AS f
WHERE (
      NOT CAST(:bbox_enabled AS boolean)
      OR (
          f.coord IS NOT NULL
          AND f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
              :min_lon, :min_lat, :max_lon, :max_lat, 4326
          )
      )
  )
  AND EXISTS (
      SELECT 1
      FROM feature.curation_items AS matched_item
      JOIN feature.curation_collections AS matched_collection
        ON matched_collection.collection_id = matched_item.collection_id
      JOIN feature.curated_themes AS matched_theme
        ON matched_theme.theme_id = matched_collection.theme_id
      LEFT JOIN feature.curated_sources AS matched_source
        ON matched_source.source_id = matched_collection.source_id
      WHERE matched_item.feature_id = f.feature_id
        AND matched_item.archived_at IS NULL
        AND matched_collection.archived_at IS NULL
        AND (
            NOT CAST(:public_only AS boolean)
            OR (
                matched_item.status = 'included'
                AND matched_collection.status = 'published'
                AND matched_collection.visibility = 'public'
            )
        )
        AND (
            CAST(:theme_slug AS text) IS NULL
            OR matched_theme.theme_slug = CAST(:theme_slug AS text)
        )
        AND (
            CAST(:edition_key AS text) IS NULL
            OR matched_collection.edition_key = CAST(:edition_key AS text)
        )
        AND (
            CAST(:provider AS text) IS NULL
            OR matched_source.provider = CAST(:provider AS text)
        )
        AND (
            CAST(:q AS text) IS NULL
            OR f.name ILIKE CAST(:q AS text)
            OR matched_collection.title ILIKE CAST(:q AS text)
            OR matched_theme.theme_name ILIKE CAST(:q AS text)
        )
  )
  AND (
      CAST(:cursor_feature_id AS text) IS NULL
      OR f.feature_id > CAST(:cursor_feature_id AS text)
  )
ORDER BY f.feature_id
LIMIT :limit
"""

_GET_FEATURE_SQL: Final[str] = """
SELECT
    f.feature_id,
    f.name,
    f.kind,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    f.status
FROM feature.public_features AS f
WHERE f.feature_id = :feature_id
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = """
SELECT
    f.feature_id,
    f.name,
    f.kind,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address,
    f.status
FROM feature.public_features AS f
WHERE f.feature_id = ANY(CAST(:feature_ids AS text[]))
"""

_CREATE_COLLECTION_SQL: Final[str] = """
INSERT INTO feature.curation_collections (
    collection_key, theme_id, source_id, title, edition_key, description,
    status, visibility, metadata, created_by, updated_by, updated_at
) VALUES (
    :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
    :title, :edition_key, :description, :status, :visibility,
    CAST(:metadata AS jsonb), :actor, :actor, now()
)
RETURNING collection_id::text
"""

_UPSERT_ITEM_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curation_items (
        collection_id, feature_id, source_record_key, external_item_id,
        place_name, address_hint, status,
        sort_order, item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, updated_at
    ) VALUES (
        CAST(:collection_id AS uuid), :feature_id, :source_record_key,
        :external_item_id, :place_name, :address_hint,
        :status, :sort_order, :item_title, :item_summary,
        :curation_relation, :reuse_policy, CAST(:metadata AS jsonb),
        :actor, :actor, now()
    )
    ON CONFLICT (
        collection_id, external_item_id, feature_id
    ) WHERE archived_at IS NULL
    DO UPDATE SET
        source_record_key = COALESCE(
            EXCLUDED.source_record_key,
            feature.curation_items.source_record_key
        ),
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        status = EXCLUDED.status,
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        curation_relation = EXCLUDED.curation_relation,
        reuse_policy = EXCLUDED.reuse_policy,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        updated_at = now()
    WHERE (
        feature.curation_items.source_record_key,
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.status,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.curation_relation,
        feature.curation_items.reuse_policy,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        COALESCE(EXCLUDED.source_record_key,
                 feature.curation_items.source_record_key),
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        EXCLUDED.status,
        EXCLUDED.sort_order,
        EXCLUDED.item_title,
        EXCLUDED.item_summary,
        EXCLUDED.curation_relation,
        EXCLUDED.reuse_policy,
        EXCLUDED.metadata
    )
    RETURNING curation_item_id::text, (xmax = 0) AS inserted
)
SELECT curation_item_id, inserted FROM written
UNION ALL
SELECT existing.curation_item_id::text, false
FROM feature.curation_items AS existing
WHERE existing.collection_id = CAST(:collection_id AS uuid)
  AND existing.external_item_id = :external_item_id
  AND existing.feature_id IS NOT DISTINCT FROM :feature_id
  AND existing.archived_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_DELETE_IMPORT_REMOVALS_SQL: Final[str] = (
    """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text
    )
), affected_collections AS (
    SELECT DISTINCT CAST(collection_id AS uuid) AS collection_id
    FROM incoming
), deleted AS (
    DELETE FROM feature.curation_items AS existing
    USING affected_collections
    WHERE existing.collection_id = affected_collections.collection_id
      AND existing.archived_at IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM incoming
          WHERE CAST(incoming.collection_id AS uuid) = existing.collection_id
            AND incoming.external_item_id = existing.external_item_id
            AND incoming.feature_id IS NOT DISTINCT FROM existing.feature_id
      )
    RETURNING existing.*
)
SELECT
"""
    + _ITEM_SELECT_FIELDS
    + """
FROM deleted AS i
JOIN feature.curation_collections AS c ON c.collection_id = i.collection_id
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN feature.features AS f ON f.feature_id = i.feature_id
ORDER BY c.collection_key, i.sort_order, i.curation_item_id
"""
)

_BULK_UPSERT_ITEMS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), written AS (
    INSERT INTO feature.curation_items (
        collection_id, feature_id, external_item_id, place_name, address_hint,
        status, sort_order,
        item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, updated_at
    )
    SELECT
        CAST(collection_id AS uuid), feature_id, external_item_id,
        place_name, address_hint, 'included', sort_order,
        item_title, item_summary, 'nearby_option',
        'manual_review', metadata, :actor, :actor, now()
    FROM incoming
    ON CONFLICT (
        collection_id, external_item_id, feature_id
    ) WHERE archived_at IS NULL
    DO UPDATE SET
        status = EXCLUDED.status,
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        curation_relation = EXCLUDED.curation_relation,
        reuse_policy = EXCLUDED.reuse_policy,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        updated_at = now()
    WHERE (
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.status,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.curation_relation,
        feature.curation_items.reuse_policy,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        EXCLUDED.status,
        EXCLUDED.sort_order,
        EXCLUDED.item_title,
        EXCLUDED.item_summary,
        EXCLUDED.curation_relation,
        EXCLUDED.reuse_policy,
        EXCLUDED.metadata
    )
    RETURNING (xmax = 0) AS inserted
)
SELECT
    count(*) FILTER (WHERE inserted)::integer AS inserted,
    count(*) FILTER (WHERE NOT inserted)::integer AS updated
FROM written
"""

_PREVIEW_IMPORT_COUNTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_key text,
        feature_id text,
        external_item_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), classified AS (
    SELECT
        existing.curation_item_id IS NOT NULL AS already_exists,
        existing.curation_item_id IS NOT NULL
        AND (
            existing.place_name,
            existing.address_hint,
            existing.status,
            existing.sort_order,
            existing.item_title,
            existing.item_summary,
            existing.curation_relation,
            existing.reuse_policy,
            existing.metadata
        ) IS DISTINCT FROM (
            incoming.place_name,
            incoming.address_hint,
            'included'::text,
            incoming.sort_order,
            incoming.item_title,
            incoming.item_summary,
            'nearby_option'::text,
            'manual_review'::text,
            incoming.metadata
        ) AS needs_update
    FROM incoming
    LEFT JOIN feature.curation_collections AS collection
      ON collection.collection_key = incoming.collection_key
    LEFT JOIN feature.curation_items AS existing
      ON existing.collection_id = collection.collection_id
     AND existing.external_item_id = incoming.external_item_id
     AND existing.feature_id IS NOT DISTINCT FROM incoming.feature_id
     AND existing.archived_at IS NULL
)
SELECT
    count(*) FILTER (WHERE NOT already_exists)::integer AS inserted,
    count(*) FILTER (WHERE needs_update)::integer AS updated
FROM classified
"""

_PREVIEW_IMPORT_REMOVALS_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.archived_at IS NULL
  AND EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text
      )
      WHERE incoming.collection_key = c.collection_key
  )
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text
      )
      WHERE incoming.collection_key = c.collection_key
        AND incoming.external_item_id = i.external_item_id
        AND incoming.feature_id IS NOT DISTINCT FROM i.feature_id
  )
ORDER BY c.collection_key, i.sort_order, i.curation_item_id
"""
)

_UPSERT_THEME_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curated_themes (
        theme_slug, theme_name, theme_description, theme_group,
        default_curated, visibility, metadata, updated_at
    ) VALUES (
        :theme_slug, :theme_name, '', :theme_group, false, 'public',
        '{}'::jsonb, now()
    )
    ON CONFLICT (theme_slug) DO UPDATE SET
        theme_name = EXCLUDED.theme_name,
        theme_group = EXCLUDED.theme_group,
        updated_at = now()
    WHERE (
        feature.curated_themes.theme_name,
        feature.curated_themes.theme_group
    ) IS DISTINCT FROM (EXCLUDED.theme_name, EXCLUDED.theme_group)
    RETURNING theme_id::text
)
SELECT theme_id FROM written
UNION ALL
SELECT existing.theme_id::text
FROM feature.curated_themes AS existing
WHERE existing.theme_slug = :theme_slug
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_UPSERT_SOURCE_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curated_sources (
        provider, dataset_key, source_name, source_url, source_kind,
        update_cycle, provider_status, metadata, updated_at
    ) VALUES (
        :provider, :dataset_key, :source_name, :source_url, 'manual',
        'unknown', 'manual_only', '{}'::jsonb, now()
    )
    ON CONFLICT (provider, dataset_key) DO UPDATE SET
        source_name = EXCLUDED.source_name,
        source_url = COALESCE(
            EXCLUDED.source_url,
            feature.curated_sources.source_url
        ),
        updated_at = now()
    WHERE (
        feature.curated_sources.source_name,
        feature.curated_sources.source_url
    ) IS DISTINCT FROM (
        EXCLUDED.source_name,
        COALESCE(EXCLUDED.source_url, feature.curated_sources.source_url)
    )
    RETURNING source_id::text
)
SELECT source_id FROM written
UNION ALL
SELECT existing.source_id::text
FROM feature.curated_sources AS existing
WHERE existing.provider = :provider
  AND existing.dataset_key = :dataset_key
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_UPSERT_COLLECTION_SQL: Final[str] = """
WITH written AS (
    INSERT INTO feature.curation_collections (
        collection_key, theme_id, source_id, title, edition_key, status,
        visibility, metadata, created_by, updated_by, updated_at
    ) VALUES (
        :collection_key, CAST(:theme_id AS uuid), CAST(:source_id AS uuid),
        :title, :edition_key, 'published', 'public', '{}'::jsonb,
        :actor, :actor, now()
    )
    ON CONFLICT (collection_key) DO UPDATE SET
        theme_id = EXCLUDED.theme_id,
        source_id = EXCLUDED.source_id,
        title = EXCLUDED.title,
        edition_key = EXCLUDED.edition_key,
        status = 'published',
        visibility = 'public',
        updated_by = EXCLUDED.updated_by,
        updated_at = now(),
        archived_at = NULL
    WHERE (
        feature.curation_collections.theme_id,
        feature.curation_collections.source_id,
        feature.curation_collections.title,
        feature.curation_collections.edition_key,
        feature.curation_collections.status,
        feature.curation_collections.visibility,
        feature.curation_collections.archived_at IS NULL
    ) IS DISTINCT FROM (
        EXCLUDED.theme_id,
        EXCLUDED.source_id,
        EXCLUDED.title,
        EXCLUDED.edition_key,
        'published'::text,
        'public'::text,
        true
    )
    RETURNING collection_id::text
)
SELECT collection_id FROM written
UNION ALL
SELECT existing.collection_id::text
FROM feature.curation_collections AS existing
WHERE existing.collection_key = :collection_key
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_GET_THEME_ID_BY_SLUG_SQL: Final[str] = """
SELECT theme_id::text
FROM feature.curated_themes
WHERE theme_slug = :theme_slug
"""

_GET_SOURCE_ID_BY_KEY_SQL: Final[str] = """
SELECT source_id::text
FROM feature.curated_sources
WHERE provider = :provider
  AND dataset_key = :dataset_key
"""

_GET_COLLECTION_ID_BY_KEY_SQL: Final[str] = """
SELECT collection_id::text
FROM feature.curation_collections
WHERE collection_key = :collection_key
"""

_RESOLVE_FEATURES_BATCH_SQL: Final[str] = """
WITH requested AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:requests AS jsonb)) AS value(
        row_number integer,
        feature_id text,
        place_name text,
        address_hint text
    )
)
SELECT
    requested.row_number,
    matched.feature_id,
    matched.name,
    matched.address,
    matched.lon,
    matched.lat
FROM requested
CROSS JOIN LATERAL (
    (
        SELECT
            f.feature_id,
            f.name,
            f.address,
            x_extension.ST_X(f.coord) AS lon,
            x_extension.ST_Y(f.coord) AS lat
        FROM feature.features AS f
        WHERE requested.feature_id IS NOT NULL
          AND f.feature_id = requested.feature_id
          AND f.deleted_at IS NULL
          AND f.status NOT IN ('deleted', 'hidden')
    )
    UNION ALL
    (
        SELECT
            f.feature_id,
            f.name,
            f.address,
            x_extension.ST_X(f.coord) AS lon,
            x_extension.ST_Y(f.coord) AS lat
        FROM feature.features AS f
        WHERE requested.feature_id IS NULL
          AND requested.place_name IS NOT NULL
          AND lower(f.name) = lower(requested.place_name)
          AND f.deleted_at IS NULL
          AND f.status NOT IN ('deleted', 'hidden')
          AND (
              requested.address_hint IS NULL
              OR f.address::text ILIKE '%' || requested.address_hint || '%'
          )
        ORDER BY f.feature_id
        LIMIT 3
    )
) AS matched
ORDER BY requested.row_number, matched.feature_id
"""


async def _upsert_id_with_fallback(
    session: AsyncSession,
    *,
    upsert_sql: str,
    lookup_sql: str,
    params: Mapping[str, Any],
    entity: str,
) -> str:
    """동시 insert가 현재 statement snapshot에 없을 때 새 snapshot으로 재조회한다."""

    value = (await session.execute(text(upsert_sql), dict(params))).scalar_one_or_none()
    if value is None:
        # PostgreSQL ON CONFLICT는 statement 시작 뒤 commit된 conflict row를 처리할 수
        # 있지만, 같은 statement의 UNION SELECT snapshot에서는 그 row가 안 보인다.
        value = (await session.execute(text(lookup_sql), dict(params))).scalar_one_or_none()
    if value is None:
        raise RuntimeError(f"concurrent {entity} upsert row disappeared")
    return str(value)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _collection(row: RowMapping | Mapping[str, Any]) -> CurationCollection:
    return CurationCollection(
        collection_id=str(row["collection_id"]),
        collection_key=str(row["collection_key"]),
        theme_id=str(row["theme_id"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_group=str(row["theme_group"]),
        source_id=str(row["source_id"]) if row["source_id"] else None,
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        title=str(row["title"]),
        edition_key=str(row["edition_key"]),
        description=row["description"],
        status=str(row["status"]),
        visibility=str(row["visibility"]),
        metadata=_object(row["metadata"]),
        item_count=int(row["item_count"]),
        public_item_count=int(row["public_item_count"]),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _item(row: RowMapping | Mapping[str, Any]) -> CurationItem:
    return CurationItem(
        curation_item_id=str(row["curation_item_id"]),
        collection_id=str(row["collection_id"]),
        collection_key=str(row["collection_key"]),
        title=str(row["title"]),
        edition_key=str(row["edition_key"]),
        theme_slug=str(row["theme_slug"]),
        theme_name=str(row["theme_name"]),
        theme_group=str(row["theme_group"]),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        feature_id=str(row["feature_id"]) if row["feature_id"] else None,
        feature_name=str(row["feature_name"]) if row["feature_name"] else None,
        feature_kind=str(row["feature_kind"]) if row["feature_kind"] else None,
        feature_category=(str(row["feature_category"]) if row["feature_category"] else None),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        address=_object(row["address"]),
        source_record_key=row["source_record_key"],
        external_item_id=str(row["external_item_id"]),
        place_name=str(row["place_name"]),
        address_hint=row["address_hint"],
        status=str(row["status"]),
        sort_order=int(row["sort_order"]),
        item_title=row["item_title"],
        item_summary=row["item_summary"],
        curation_relation=str(row["curation_relation"]),
        reuse_policy=str(row["reuse_policy"]),
        metadata=_object(row["metadata"]),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _public_item(row: RowMapping | Mapping[str, Any]) -> CurationItem:
    """비공개 Feature 연결은 공식 미연결 item처럼 투영해 장소 정보 노출을 막는다."""

    item = _item(row)
    # 공개 여부 판정은 feature.public_features view가 단일 정본이다 (ADR-067 /
    # T-VN-04). 여기서 status/deleted_at을 다시 조합하지 말 것.
    feature_is_public = bool(row.get("linked_feature_is_public"))
    if item.feature_id is None or feature_is_public:
        return item
    return replace(
        item,
        feature_id=None,
        feature_name=None,
        feature_kind=None,
        feature_category=None,
        lon=None,
        lat=None,
        address={},
        source_record_key=None,
    )


def _feature_match(row: RowMapping | Mapping[str, Any]) -> FeatureMatch:
    return FeatureMatch(
        feature_id=str(row["feature_id"]),
        name=str(row["name"]),
        address=_object(row["address"]),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
    )


def encode_collection_cursor(updated_at: datetime, collection_id: str) -> str:
    raw = json.dumps(
        {"updated_at": updated_at.isoformat(), "collection_id": collection_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_collection_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        updated_at = payload.get("updated_at")
        collection_id = payload.get("collection_id")
        if not isinstance(updated_at, str) or not isinstance(collection_id, str):
            raise ValueError
        parsed_updated_at = datetime.fromisoformat(updated_at)
        if parsed_updated_at.tzinfo is None:
            raise ValueError
        UUID(collection_id)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation collection cursor") from exc
    if not updated_at or not collection_id:
        raise ValueError("invalid curation collection cursor")
    return parsed_updated_at, collection_id


def encode_group_cursor(feature_id: str) -> str:
    raw = json.dumps({"feature_id": feature_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_group_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid curation group cursor") from exc
    feature_id = payload.get("feature_id") if isinstance(payload, dict) else None
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid curation group cursor")
    return feature_id


async def list_curation_collections(
    session: AsyncSession,
    *,
    status: str | None = None,
    visibility: str | None = None,
    theme_slug: str | None = None,
    edition_key: str | None = None,
    provider: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
    cursor: str | None = None,
) -> tuple[tuple[CurationCollection, ...], str | None]:
    if status is not None and status not in _COLLECTION_STATUSES:
        raise ValueError("invalid curation collection status")
    if visibility is not None and visibility not in _VISIBILITIES:
        raise ValueError("invalid curation collection visibility")
    decoded_cursor = decode_collection_cursor(cursor)
    effective_limit = max(1, min(limit, 500))
    rows = (
        (
            await session.execute(
                text(_LIST_COLLECTIONS_SQL),
                {
                    "status": status,
                    "visibility": visibility,
                    "theme_slug": theme_slug,
                    "edition_key": edition_key,
                    "provider": provider,
                    "q": f"%{q.strip()}%" if q and q.strip() else None,
                    "include_archived": include_archived,
                    "cursor_updated_at": decoded_cursor[0] if decoded_cursor else None,
                    "cursor_collection_id": (decoded_cursor[1] if decoded_cursor else None),
                    "limit": effective_limit + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    page = tuple(_collection(row) for row in rows[:effective_limit])
    next_cursor = (
        encode_collection_cursor(page[-1].updated_at, page[-1].collection_id)
        if len(rows) > effective_limit and page
        else None
    )
    return page, next_cursor


async def get_curation_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    include_archived: bool = False,
    public_only: bool = False,
) -> tuple[CurationCollection, tuple[CurationItem, ...]] | None:
    row = (
        (
            await session.execute(
                text(_GET_COLLECTION_SQL),
                {"collection_id": collection_id, "include_archived": include_archived},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    item_rows = (
        (
            await session.execute(
                text(_LIST_COLLECTION_ITEMS_SQL),
                {"collection_id": collection_id, "include_archived": include_archived},
            )
        )
        .mappings()
        .all()
    )
    item_factory = _public_item if public_only else _item
    return _collection(row), tuple(item_factory(item_row) for item_row in item_rows)


async def get_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    include_archived: bool = False,
) -> CurationItem | None:
    row = (
        (
            await session.execute(
                text(_GET_COLLECTION_ITEM_SQL),
                {
                    "collection_id": collection_id,
                    "curation_item_id": curation_item_id,
                    "include_archived": include_archived,
                },
            )
        )
        .mappings()
        .first()
    )
    return _item(row) if row is not None else None


async def _lock_collection(session: AsyncSession, collection_id: str) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_id = CAST(:collection_id AS uuid) FOR UPDATE"
            ),
            {"collection_id": collection_id},
        )
    ).first()
    return row is not None


async def _touch_collection(
    session: AsyncSession, *, collection_id: str, actor: str | None
) -> None:
    await session.execute(
        text(
            "UPDATE feature.curation_collections "
            "SET updated_by = :actor, updated_at = now() "
            "WHERE collection_id = CAST(:collection_id AS uuid)"
        ),
        {"collection_id": collection_id, "actor": actor},
    )


async def create_curation_collection(
    session: AsyncSession,
    *,
    collection_key: str,
    theme_id: str,
    source_id: str | None,
    title: str,
    edition_key: str = "",
    description: str | None = None,
    status: str = "draft",
    visibility: str = "admin_only",
    metadata: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> CurationCollection:
    if status not in _COLLECTION_STATUSES or visibility not in _VISIBILITIES:
        raise ValueError("invalid curation collection state")
    if not collection_key.strip() or not title.strip():
        raise ValueError("collection_key and title are required")
    collection_id = str(
        (
            await session.execute(
                text(_CREATE_COLLECTION_SQL),
                {
                    "collection_key": collection_key.strip(),
                    "theme_id": theme_id,
                    "source_id": source_id,
                    "title": title.strip(),
                    "edition_key": edition_key.strip(),
                    "description": description,
                    "status": status,
                    "visibility": visibility,
                    "metadata": json.dumps(dict(metadata or {})),
                    "actor": actor,
                },
            )
        ).scalar_one()
    )
    result = await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    )
    assert result is not None
    return result[0]


async def update_curation_collection(
    session: AsyncSession,
    *,
    collection_id: str,
    updates: Mapping[str, Any],
) -> CurationCollection | None:
    allowed = {
        "theme_id",
        "source_id",
        "title",
        "edition_key",
        "description",
        "status",
        "visibility",
        "metadata",
        "updated_by",
    }
    clauses: list[str] = []
    params: dict[str, Any] = {"collection_id": collection_id}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported curation collection field: {key}")
        if key == "status" and value not in _COLLECTION_STATUSES:
            raise ValueError("invalid curation collection status")
        if key == "visibility" and value not in _VISIBILITIES:
            raise ValueError("invalid curation collection visibility")
        if key in {"theme_id", "source_id"}:
            clauses.append(f"{key} = CAST(:{key} AS uuid)")
        elif key == "metadata":
            clauses.append("metadata = CAST(:metadata AS jsonb)")
            value = json.dumps(dict(value))
        else:
            clauses.append(f"{key} = :{key}")
        params[key] = value
    if not clauses:
        current = await get_curation_collection(
            session, collection_id=collection_id, include_archived=True
        )
        return current[0] if current else None
    clauses.extend(
        [
            "updated_at = now()",
            (
                "archived_at = CASE WHEN :archive THEN now() "
                "WHEN :unarchive THEN NULL ELSE archived_at END"
            ),
        ]
    )
    params["archive"] = updates.get("status") == "archived"
    params["unarchive"] = "status" in updates and updates.get("status") != "archived"
    sql = f"""
    UPDATE feature.curation_collections
    SET {", ".join(clauses)}
    WHERE collection_id = CAST(:collection_id AS uuid)
    RETURNING collection_id::text
    """
    row = (await session.execute(text(sql), params)).first()
    if row is None:
        return None
    current = await get_curation_collection(
        session, collection_id=collection_id, include_archived=True
    )
    assert current is not None
    return current[0]


async def archive_curation_collection(
    session: AsyncSession, *, collection_id: str, actor: str | None = None
) -> CurationCollection | None:
    return await update_curation_collection(
        session,
        collection_id=collection_id,
        updates={"status": "archived", "updated_by": actor},
    )


async def add_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    feature_id: str | None,
    external_item_id: str,
    place_name: str | None = None,
    address_hint: str | None = None,
    source_record_key: str | None = None,
    status: str = "included",
    sort_order: int = 0,
    item_title: str | None = None,
    item_summary: str | None = None,
    curation_relation: str = "nearby_option",
    reuse_policy: str = "manual_review",
    metadata: Mapping[str, Any] | None = None,
    actor: str | None = None,
) -> tuple[CurationItem, bool]:
    if status not in _ITEM_STATUSES:
        raise ValueError("invalid curation item status")
    if curation_relation not in _RELATIONS or reuse_policy not in _REUSE_POLICIES:
        raise ValueError("invalid curation item policy")
    if not 0 <= sort_order <= _POSTGRES_INTEGER_MAX or not external_item_id.strip():
        raise ValueError("invalid curation item identity")
    if not await _lock_collection(session, collection_id):
        raise LookupError("curation collection 없음")
    resolved_place_name = place_name.strip() if place_name else ""
    if feature_id is not None:
        feature_name = (
            await session.execute(
                text(
                    "SELECT name FROM feature.features "
                    "WHERE feature_id = :id AND deleted_at IS NULL "
                    "AND status NOT IN ('deleted','hidden')"
                ),
                {"id": feature_id},
            )
        ).scalar_one_or_none()
        if feature_name is None:
            raise ValueError("feature_id must reference an active Feature")
        if not resolved_place_name:
            resolved_place_name = str(feature_name)
    if not resolved_place_name:
        raise ValueError("place_name or an existing feature_id is required")
    if feature_id is not None:
        unresolved_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND feature_id IS NULL AND archived_at IS NULL"
                ),
                {
                    "collection_id": collection_id,
                    "external_item_id": external_item_id.strip(),
                },
            )
        ).scalar_one_or_none()
        if unresolved_exists is not None:
            raise ValueError(
                "같은 외부 항목 ID의 미연결 항목이 이미 존재합니다. PATCH로 Feature를 연결하세요."
            )
    else:
        resolved_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND feature_id IS NOT NULL AND archived_at IS NULL"
                ),
                {
                    "collection_id": collection_id,
                    "external_item_id": external_item_id.strip(),
                },
            )
        ).scalar_one_or_none()
        if resolved_exists is not None:
            raise ValueError("같은 외부 항목 ID의 Feature 연결 항목이 이미 존재합니다.")
    row = (
        (
            await session.execute(
                text(_UPSERT_ITEM_SQL),
                {
                    "collection_id": collection_id,
                    "feature_id": feature_id,
                    "source_record_key": source_record_key,
                    "external_item_id": external_item_id.strip(),
                    "place_name": resolved_place_name,
                    "address_hint": address_hint.strip() if address_hint else None,
                    "status": status,
                    "sort_order": sort_order,
                    "item_title": item_title,
                    "item_summary": item_summary,
                    "curation_relation": curation_relation,
                    "reuse_policy": reuse_policy,
                    "metadata": json.dumps(dict(metadata or {})),
                    "actor": actor,
                },
            )
        )
        .mappings()
        .one()
    )
    item_id = str(row["curation_item_id"])
    item_row = (
        (
            await session.execute(
                text(_ITEM_SELECT + " WHERE i.curation_item_id = CAST(:id AS uuid)"),
                {"id": item_id},
            )
        )
        .mappings()
        .one()
    )
    await _touch_collection(session, collection_id=collection_id, actor=actor)
    return _item(item_row), bool(row["inserted"])


async def update_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    updates: Mapping[str, Any],
    actor: str | None = None,
) -> CurationItem | None:
    """단일 membership을 부분 수정한다. 명시적 ``feature_id=null``도 보존한다."""

    if not await _lock_collection(session, collection_id):
        return None
    current = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
    )
    if current is None:
        return None

    allowed = {
        "feature_id",
        "source_record_key",
        "external_item_id",
        "place_name",
        "address_hint",
        "status",
        "sort_order",
        "item_title",
        "item_summary",
        "curation_relation",
        "reuse_policy",
        "metadata",
    }
    normalized: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"unsupported curation item field: {key}")
        if key == "status" and value not in _ITEM_STATUSES:
            raise ValueError("invalid curation item status")
        if key == "curation_relation" and value not in _RELATIONS:
            raise ValueError("invalid curation item relation")
        if key == "reuse_policy" and value not in _REUSE_POLICIES:
            raise ValueError("invalid curation item reuse policy")
        if key == "sort_order" and (
            not isinstance(value, int) or not 0 <= value <= _POSTGRES_INTEGER_MAX
        ):
            raise ValueError("invalid curation item sort order")
        if key in {"external_item_id", "place_name"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must not be empty")
            value = value.strip()
        if key == "address_hint" and isinstance(value, str):
            value = value.strip() or None
        if key == "metadata":
            if not isinstance(value, Mapping):
                raise ValueError("curation item metadata must be an object")
            value = json.dumps(dict(value))
        normalized[key] = value

    feature_id = normalized.get("feature_id", current.feature_id)
    if "feature_id" in normalized and feature_id is not None:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.features "
                    "WHERE feature_id = :feature_id AND deleted_at IS NULL "
                    "AND status NOT IN ('deleted','hidden')"
                ),
                {"feature_id": feature_id},
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ValueError("feature_id에 해당하는 Feature가 없습니다.")

    target_external_item_id = str(normalized.get("external_item_id", current.external_item_id))
    opposite_exists = (
        await session.execute(
            text(
                "SELECT 1 FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND curation_item_id <> CAST(:curation_item_id AS uuid) "
                "AND external_item_id = :external_item_id "
                "AND archived_at IS NULL "
                "AND ((CAST(:feature_id AS text) IS NULL "
                "AND feature_id IS NOT NULL) "
                "OR (CAST(:feature_id AS text) IS NOT NULL "
                "AND feature_id IS NULL))"
            ),
            {
                "collection_id": collection_id,
                "curation_item_id": curation_item_id,
                "external_item_id": target_external_item_id,
                "feature_id": feature_id,
            },
        )
    ).scalar_one_or_none()
    if opposite_exists is not None:
        raise ValueError("같은 외부 항목 ID에 Feature 연결/미연결 항목을 함께 둘 수 없습니다.")

    if not normalized:
        return current
    clauses: list[str] = []
    params: dict[str, Any] = {
        "collection_id": collection_id,
        "curation_item_id": curation_item_id,
        "actor": actor,
    }
    for key, value in normalized.items():
        if key == "metadata":
            clauses.append("metadata = CAST(:metadata AS jsonb)")
        else:
            clauses.append(f"{key} = :{key}")
        params[key] = value
    clauses.extend(["updated_by = :actor", "updated_at = now()"])
    if normalized.get("status") == "archived":
        clauses.append("archived_at = now()")
    row = (
        await session.execute(
            text(
                f"""
                UPDATE feature.curation_items
                SET {", ".join(clauses)}
                WHERE collection_id = CAST(:collection_id AS uuid)
                  AND curation_item_id = CAST(:curation_item_id AS uuid)
                  AND archived_at IS NULL
                RETURNING curation_item_id::text
                """
            ),
            params,
        )
    ).first()
    if row is None:
        return None
    await _touch_collection(session, collection_id=collection_id, actor=actor)
    return await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    )


async def archive_curation_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
    actor: str | None = None,
) -> CurationItem | None:
    return await update_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        updates={"status": "archived"},
        actor=actor,
    )


async def get_feature_curation_group(
    session: AsyncSession, *, feature_id: str, public_only: bool = True
) -> FeatureCurationGroup | None:
    """feature 1건의 큐레이션 group을 조회한다.

    feature 자체의 공개 여부는 ``public_only``와 무관하게 항상 ADR-067
    ``feature.public_features`` projection을 따른다(공개 표면 전용 read).
    ``public_only``는 collection/item 상태(published·included·public) 필터만
    제어한다.
    """
    feature = (
        (await session.execute(text(_GET_FEATURE_SQL), {"feature_id": feature_id}))
        .mappings()
        .first()
    )
    if feature is None:
        return None
    item_rows = (
        (
            await session.execute(
                text(_LIST_FEATURE_ITEMS_SQL),
                {"feature_id": feature_id, "public_only": public_only},
            )
        )
        .mappings()
        .all()
    )
    if not item_rows:
        return None
    return FeatureCurationGroup(
        feature_id=str(feature["feature_id"]),
        name=str(feature["name"]),
        kind=str(feature["kind"]),
        category=str(feature["category"]),
        lon=float(feature["lon"]) if feature["lon"] is not None else None,
        lat=float(feature["lat"]) if feature["lat"] is not None else None,
        address=_object(feature["address"]),
        status=str(feature["status"]),
        curations=tuple(_item(row) for row in item_rows),
    )


async def list_curation_items_by_feature_ids(
    session: AsyncSession,
    *,
    feature_ids: Sequence[str],
    public_only: bool = True,
) -> dict[str, tuple[CurationItem, ...]]:
    if not feature_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(_LIST_FEATURE_ITEMS_BATCH_SQL),
                {
                    "feature_ids": list(dict.fromkeys(feature_ids)),
                    "public_only": public_only,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[str, list[CurationItem]] = {}
    for row in rows:
        item = _item(row)
        if item.feature_id is not None:
            grouped.setdefault(item.feature_id, []).append(item)
    return {feature_id: tuple(items) for feature_id, items in grouped.items()}


async def list_feature_curation_groups(
    session: AsyncSession,
    *,
    public_only: bool = True,
    theme_slug: str | None = None,
    edition_key: str | None = None,
    provider: str | None = None,
    q: str | None = None,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    page_size: int = 100,
    cursor: str | None = None,
) -> tuple[tuple[FeatureCurationGroup, ...], str | None]:
    bbox_values = (min_lon, min_lat, max_lon, max_lat)
    bbox_enabled = all(value is not None for value in bbox_values)
    if any(value is not None for value in bbox_values) and not bbox_enabled:
        raise ValueError("bbox coordinates must be provided together")
    cursor_feature_id = decode_group_cursor(cursor)
    effective_size = max(1, min(page_size, 500))
    key_rows = (
        (
            await session.execute(
                text(_LIST_GROUP_KEYS_SQL),
                {
                    "public_only": public_only,
                    "theme_slug": theme_slug,
                    "edition_key": edition_key,
                    "provider": provider,
                    "q": f"%{q.strip()}%" if q and q.strip() else None,
                    "bbox_enabled": bbox_enabled,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "cursor_feature_id": cursor_feature_id,
                    "limit": effective_size + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    page_keys = [str(row["feature_id"]) for row in key_rows[:effective_size]]
    feature_rows = (
        (await session.execute(text(_GET_FEATURES_BY_IDS_SQL), {"feature_ids": page_keys}))
        .mappings()
        .all()
        if page_keys
        else []
    )
    features = {str(row["feature_id"]): row for row in feature_rows}
    grouped_items = await list_curation_items_by_feature_ids(
        session, feature_ids=page_keys, public_only=public_only
    )
    groups = []
    for feature_id in page_keys:
        feature = features.get(feature_id)
        if feature is None:
            continue
        groups.append(
            FeatureCurationGroup(
                feature_id=feature_id,
                name=str(feature["name"]),
                kind=str(feature["kind"]),
                category=str(feature["category"]),
                lon=float(feature["lon"]) if feature["lon"] is not None else None,
                lat=float(feature["lat"]) if feature["lat"] is not None else None,
                address=_object(feature["address"]),
                status=str(feature["status"]),
                curations=grouped_items.get(feature_id, ()),
            )
        )
    next_cursor = (
        encode_group_cursor(page_keys[-1]) if len(key_rows) > effective_size and page_keys else None
    )
    return tuple(groups), next_cursor


async def resolve_feature_match(
    session: AsyncSession,
    *,
    feature_id: str | None,
    place_name: str | None,
    address_hint: str | None,
) -> tuple[FeatureMatch, ...]:
    matches = await resolve_feature_matches(
        session,
        requests=(
            FeatureMatchRequest(
                row_number=0,
                feature_id=feature_id,
                place_name=place_name,
                address_hint=address_hint,
            ),
        ),
    )
    return matches.get(0, ())


async def resolve_feature_matches(
    session: AsyncSession,
    *,
    requests: Sequence[FeatureMatchRequest],
) -> dict[int, tuple[FeatureMatch, ...]]:
    """CSV 전체의 exact Feature/name 후보를 한 번의 parameterized query로 찾는다."""

    if not requests:
        return {}
    payload = [
        {
            "row_number": request.row_number,
            "feature_id": request.feature_id.strip() if request.feature_id else None,
            "place_name": request.place_name.strip() if request.place_name else None,
            "address_hint": (request.address_hint.strip() if request.address_hint else None),
        }
        for request in requests
    ]
    rows = (
        (
            await session.execute(
                text(_RESOLVE_FEATURES_BATCH_SQL),
                {"requests": json.dumps(payload, ensure_ascii=False)},
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[int, list[FeatureMatch]] = {request.row_number: [] for request in requests}
    for row in rows:
        grouped[int(row["row_number"])].append(_feature_match(row))
    return {row_number: tuple(items) for row_number, items in grouped.items()}


async def upsert_curation_theme(
    session: AsyncSession,
    *,
    theme_slug: str,
    theme_name: str,
    theme_group: str,
) -> str:
    """수동 입력/CSV가 공유하는 theme 안정키 upsert."""

    if not theme_slug.strip() or not theme_name.strip() or not theme_group.strip():
        raise ValueError("theme_slug, theme_name and theme_group are required")
    params = {
        "theme_slug": theme_slug.strip(),
        "theme_name": theme_name.strip(),
        "theme_group": theme_group.strip(),
    }
    return await _upsert_id_with_fallback(
        session,
        upsert_sql=_UPSERT_THEME_SQL,
        lookup_sql=_GET_THEME_ID_BY_SLUG_SQL,
        params=params,
        entity="curation theme",
    )


def validate_resolved_curation_identities(
    rows: Sequence[ResolvedCurationImportRow],
) -> tuple[ResolvedCurationIdentityIssue, ...]:
    """실제 Feature 해소 결과의 혼합·중복 item identity를 찾는다."""

    by_source_item: dict[tuple[str, str], list[ResolvedCurationImportRow]] = {}
    by_membership: dict[tuple[str, str, str | None], list[ResolvedCurationImportRow]] = {}
    for row in rows:
        by_source_item.setdefault((row.collection_key, row.source_item_key), []).append(row)
        by_membership.setdefault(
            (row.collection_key, row.source_item_key, row.feature_id), []
        ).append(row)

    issues: dict[tuple[int, str], ResolvedCurationIdentityIssue] = {}
    for grouped_rows in by_source_item.values():
        modes = {row.feature_id is None for row in grouped_rows}
        if len(modes) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="mixed_resolved_identity",
                    message=(
                        "Feature 해소 후 같은 source_item_key에 연결 항목과 "
                        "미연결 항목이 함께 남습니다."
                    ),
                )
                issues[(issue.row_number, issue.code)] = issue
    for grouped_rows in by_membership.values():
        if len(grouped_rows) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="duplicate_resolved_identity",
                    message=(
                        "Feature 해소 후 collection/source_item_key/feature_id "
                        "membership이 중복됩니다."
                    ),
                )
                issues[(issue.row_number, issue.code)] = issue
    return tuple(issues[key] for key in sorted(issues, key=lambda value: (value[0], value[1])))


def _ensure_resolved_curation_identities(
    rows: Sequence[ResolvedCurationImportRow],
) -> None:
    if any(not 0 <= row.sort_order <= _POSTGRES_INTEGER_MAX for row in rows):
        raise ValueError("curation item sort_order is outside the PostgreSQL integer range")
    issues = validate_resolved_curation_identities(rows)
    if issues:
        raise ValueError(issues[0].message)


async def preview_curation_import(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
) -> CurationImportPlan:
    """write 없이 CSV 항목 upsert와 authoritative removal을 정확히 예측한다."""

    _ensure_resolved_curation_identities(rows)
    if not rows:
        return CurationImportPlan(collections=0, inserted=0, updated=0, removals=())
    values = [
        {
            "collection_key": row.collection_key,
            "feature_id": row.feature_id,
            "external_item_id": row.source_item_key,
            "place_name": row.place_name,
            "address_hint": row.address_hint,
            "sort_order": row.sort_order,
            "item_title": row.item_title,
            "item_summary": row.item_summary,
            "metadata": row.metadata,
        }
        for row in rows
    ]
    payload = json.dumps(values, ensure_ascii=False)
    counts = (
        (await session.execute(text(_PREVIEW_IMPORT_COUNTS_SQL), {"items": payload}))
        .mappings()
        .one()
    )
    removal_rows = (
        (await session.execute(text(_PREVIEW_IMPORT_REMOVALS_SQL), {"items": payload}))
        .mappings()
        .all()
    )
    return CurationImportPlan(
        collections=len({row.collection_key for row in rows}),
        inserted=int(counts["inserted"] or 0),
        updated=int(counts["updated"] or 0),
        removals=tuple(_item(row) for row in removal_rows),
    )


async def import_curation_rows(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
    actor: str | None = None,
) -> CurationImportResult:
    """검증·Feature 해소가 끝난 CSV 행을 한 transaction에서 멱등 upsert한다."""
    _ensure_resolved_curation_identities(rows)
    collections: dict[str, str] = {}
    item_values: list[dict[str, Any]] = []
    if rows:
        # 서로 다른 CSV가 theme/source/collection lock을 역순으로 잡는 deadlock과
        # 같은 collection의 authoritative replace 경합을 하나의 write 경계로 직렬화한다.
        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0))"
            )
        )

    representatives: dict[str, ResolvedCurationImportRow] = {}
    for row in rows:
        representatives.setdefault(row.collection_key, row)
    for collection_key in sorted(representatives):
        row = representatives[collection_key]
        theme_id = await upsert_curation_theme(
            session,
            theme_slug=row.theme_slug,
            theme_name=row.theme_name,
            theme_group=row.theme_group,
        )
        source_params = {
            "provider": row.provider,
            "dataset_key": row.dataset_key,
            "source_name": row.source_name,
            "source_url": row.source_url,
        }
        source_id = await _upsert_id_with_fallback(
            session,
            upsert_sql=_UPSERT_SOURCE_SQL,
            lookup_sql=_GET_SOURCE_ID_BY_KEY_SQL,
            params=source_params,
            entity="curation source",
        )
        collection_params = {
            "collection_key": collection_key,
            "theme_id": theme_id,
            "source_id": source_id,
            "title": row.title,
            "edition_key": row.edition_key,
            "actor": actor,
        }
        collections[collection_key] = await _upsert_id_with_fallback(
            session,
            upsert_sql=_UPSERT_COLLECTION_SQL,
            lookup_sql=_GET_COLLECTION_ID_BY_KEY_SQL,
            params=collection_params,
            entity="curation collection",
        )
    for row in rows:
        item_values.append(
            {
                "collection_id": collections[row.collection_key],
                "collection_key": row.collection_key,
                "feature_id": row.feature_id,
                "external_item_id": row.source_item_key,
                "place_name": row.place_name,
                "address_hint": row.address_hint,
                "sort_order": row.sort_order,
                "item_title": row.item_title,
                "item_summary": row.item_summary,
                "metadata": row.metadata,
            }
        )
    counts = {"inserted": 0, "updated": 0, "removed": 0}
    removals: tuple[CurationItem, ...] = ()
    if item_values:
        collection_ids = sorted(collections.values())
        await session.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_id = ANY(CAST(:collection_ids AS uuid[])) "
                "ORDER BY collection_id FOR UPDATE"
            ),
            {"collection_ids": collection_ids},
        )
        items_payload = json.dumps(item_values, ensure_ascii=False)
        removed_rows = (
            (await session.execute(text(_DELETE_IMPORT_REMOVALS_SQL), {"items": items_payload}))
            .mappings()
            .all()
        )
        removals = tuple(_item(row) for row in removed_rows)
        count_row = (
            (
                await session.execute(
                    text(_BULK_UPSERT_ITEMS_SQL),
                    {
                        "items": items_payload,
                        "actor": actor,
                    },
                )
            )
            .mappings()
            .one()
        )
        counts = {
            "inserted": int(count_row["inserted"] or 0),
            "updated": int(count_row["updated"] or 0),
            "removed": len(removals),
        }
        if any(counts.values()):
            await session.execute(
                text(
                    "UPDATE feature.curation_collections "
                    "SET updated_by = :actor, updated_at = now() "
                    "WHERE collection_id = ANY(CAST(:collection_ids AS uuid[]))"
                ),
                {"collection_ids": collection_ids, "actor": actor},
            )
    return {
        "rows": len(rows),
        "collections": len(collections),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "removals": removals,
    }
