"""큐레이션 collection/item 저장소.

물리 위치와 장소 본문은 ``feature.features``가 소유하고, 이 모듈은 테마형 묶음과
기존 Feature membership만 저장한다. 쿼리는 ADR-004에 따라 raw SQL만 사용한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from kortravelmap.core.address import normalize_korean_text
from kortravelmap.core.curation_address import (
    CURATION_ADDRESS_RESOLVER_VERSION,
    address_hint_matches,
)
from kortravelmap.infra.feature_repo import public_active_notice_filter_sql

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CurationCollection",
    "CurationImportPlan",
    "CurationImportResult",
    "CurationLinkAudit",
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
    "list_unattributed_curation_links",
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
_FEATURE_MATCH_NAME_CANDIDATE_LIMIT: Final = 100


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
    external_component_id: str
    place_name: str
    address_hint: str | None
    source_present: bool
    status: str
    sort_order: int
    item_title: str | None
    item_summary: str | None
    curation_relation: str
    reuse_policy: str
    metadata: dict[str, Any]
    current_import_row_id: str | None
    accepted_link_decision_id: str | None
    link_match_basis: str | None
    link_resolver_version: str | None
    link_evidence: dict[str, Any]
    link_actor: str | None
    link_decided_at: datetime | None
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
class CurationLinkAudit:
    """승인 근거가 없거나 legacy로만 귀속된 current Feature link."""

    curation_item_id: str
    collection_key: str
    external_item_id: str
    external_component_id: str
    feature_id: str
    place_name: str
    address_hint: str | None
    match_basis: str | None
    resolver_version: str | None
    decided_at: datetime | None


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
    source_component_key: str = "primary"
    provenance: dict[str, Any] | None = None


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
    import_batch_id: str | None


_COLLECTION_COUNT_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql(
    "count_pf"
)
_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL: Final[str] = (
    public_active_notice_filter_sql("public_count_pf")
)
_ITEM_PUBLIC_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql("pf")


def _trusted_link_sql(item_alias: str) -> str:
    return f"""
    EXISTS (
        SELECT 1
        FROM feature.curation_link_decisions AS trusted_decision
        WHERE trusted_decision.decision_id =
                  {item_alias}.accepted_link_decision_id
          AND trusted_decision.curation_item_id =
                  {item_alias}.curation_item_id
          AND trusted_decision.feature_id = {item_alias}.feature_id
          AND trusted_decision.decision_kind = 'accepted'
          AND trusted_decision.match_basis <> 'legacy_unattributed'
    )
    """


_COLLECTION_SELECT: Final[str] = f"""
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
          AND count_item.source_present
          AND (
              NOT CAST(:public_only AS boolean)
              OR count_item.feature_id IS NULL
              OR (
                  {_trusted_link_sql("count_item")}
                  AND EXISTS (
                      SELECT 1
                      FROM feature.public_features AS count_pf
                      WHERE count_pf.feature_id = count_item.feature_id
                      {_COLLECTION_COUNT_NOTICE_FILTER_SQL}
                  )
              )
          )
    ) AS item_count,
    (
        SELECT count(*)::integer
        FROM feature.curation_items AS public_count_item
        WHERE public_count_item.collection_id = c.collection_id
          AND public_count_item.archived_at IS NULL
          AND public_count_item.source_present
          AND public_count_item.status = 'included'
          AND (
              NOT CAST(:public_only AS boolean)
              OR public_count_item.feature_id IS NULL
              OR (
                  {_trusted_link_sql("public_count_item")}
                  AND EXISTS (
                      SELECT 1
                      FROM feature.public_features AS public_count_pf
                      WHERE public_count_pf.feature_id = public_count_item.feature_id
                      {_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL}
                  )
              )
          )
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

_ITEM_SELECT_FIELDS: Final[str] = f"""
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
        {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
    ) AS linked_feature_is_public,
    i.source_record_key,
    i.external_item_id,
    i.external_component_id,
    i.place_name,
    i.address_hint,
    i.source_present,
    i.status,
    i.sort_order,
    i.item_title,
    i.item_summary,
    i.curation_relation,
    i.reuse_policy,
    i.metadata,
    i.current_import_row_id::text AS current_import_row_id,
    i.accepted_link_decision_id::text AS accepted_link_decision_id,
    link_decision.match_basis AS link_match_basis,
    link_decision.resolver_version AS link_resolver_version,
    link_decision.evidence AS link_evidence,
    link_decision.actor AS link_actor,
    link_decision.decided_at AS link_decided_at,
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
LEFT JOIN feature.curation_link_decisions AS link_decision
  ON link_decision.decision_id = i.accepted_link_decision_id
"""
)

_LIST_COLLECTIONS_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE (:include_archived OR c.archived_at IS NULL)
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
      )
  )
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
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
      )
  )
"""
)

_GET_COLLECTION_BY_KEY_SQL: Final[str] = (
    _COLLECTION_SELECT
    + """
WHERE c.collection_key = :collection_key
  AND (:include_archived OR c.archived_at IS NULL)
  AND (
      NOT CAST(:public_only AS boolean)
      OR (
          c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
      )
  )
"""
)

_LIST_COLLECTION_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND (
      :include_archived
      OR (i.archived_at IS NULL AND i.source_present)
  )
  AND (
      NOT CAST(:public_only AS boolean)
      OR i.feature_id IS NULL
      OR (
          {_trusted_link_sql("i")}
          AND EXISTS (
              SELECT 1
              FROM feature.public_features AS pf
              WHERE pf.feature_id = i.feature_id
              {_ITEM_PUBLIC_NOTICE_FILTER_SQL}
          )
      )
  )
ORDER BY i.sort_order, i.curation_item_id
"""
)

_GET_COLLECTION_ITEM_SQL: Final[str] = (
    _ITEM_SELECT
    + """
WHERE i.collection_id = CAST(:collection_id AS uuid)
  AND i.curation_item_id = CAST(:curation_item_id AS uuid)
  AND (
      :include_archived
      OR (i.archived_at IS NULL AND i.source_present)
  )
"""
)

_LIST_FEATURE_ITEMS_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.feature_id = :feature_id
  AND i.archived_at IS NULL
  AND i.source_present
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND {_trusted_link_sql("i")}
      )
  )
ORDER BY c.edition_key DESC, c.title, i.sort_order, i.curation_item_id
"""
)

_LIST_FEATURE_ITEMS_BATCH_SQL: Final[str] = (
    _ITEM_SELECT
    + f"""
WHERE i.feature_id = ANY(CAST(:feature_ids AS text[]))
  AND i.archived_at IS NULL
  AND i.source_present
  AND c.archived_at IS NULL
  AND (
      :public_only = false
      OR (
          i.status = 'included'
          AND c.status = 'published'
          AND c.visibility = 'public'
          AND t.visibility = 'public'
          AND {_trusted_link_sql("i")}
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
_LIST_GROUP_KEYS_SQL: Final[str] = f"""
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
        AND matched_item.source_present
        AND matched_collection.archived_at IS NULL
        AND (
            NOT CAST(:public_only AS boolean)
            OR (
                matched_item.status = 'included'
                AND matched_collection.status = 'published'
                AND matched_collection.visibility = 'public'
                AND matched_theme.visibility = 'public'
                AND {_trusted_link_sql("matched_item")}
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
  {public_active_notice_filter_sql("f")}
ORDER BY f.feature_id
LIMIT :limit
"""

_GET_FEATURE_SQL: Final[str] = f"""
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
{public_active_notice_filter_sql("f")}
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = f"""
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
{public_active_notice_filter_sql("f")}
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
        external_component_id,
        place_name, address_hint, source_present, source_updated_at, status,
        sort_order, item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, operator_updated_by,
        operator_updated_at, updated_at
    ) VALUES (
        CAST(:collection_id AS uuid), :feature_id, :source_record_key,
        :external_item_id, :external_component_id,
        :place_name, :address_hint, true, clock_timestamp(),
        :status, :sort_order, :item_title, :item_summary,
        :curation_relation, :reuse_policy, CAST(:metadata AS jsonb),
        :actor, :actor, :actor, clock_timestamp(), now()
    )
    ON CONFLICT (
        collection_id, external_item_id, external_component_id
    )
    DO UPDATE SET
        feature_id = EXCLUDED.feature_id,
        source_record_key = COALESCE(
            EXCLUDED.source_record_key,
            feature.curation_items.source_record_key
        ),
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        status = EXCLUDED.status,
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        curation_relation = EXCLUDED.curation_relation,
        reuse_policy = EXCLUDED.reuse_policy,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        operator_updated_by = EXCLUDED.operator_updated_by,
        operator_updated_at = clock_timestamp(),
        updated_at = now()
    WHERE (
        feature.curation_items.feature_id,
        feature.curation_items.source_record_key,
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.source_present,
        feature.curation_items.status,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.curation_relation,
        feature.curation_items.reuse_policy,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        EXCLUDED.feature_id,
        COALESCE(EXCLUDED.source_record_key,
                 feature.curation_items.source_record_key),
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        true,
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
  AND existing.external_component_id = :external_component_id
  AND existing.archived_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM written)
LIMIT 1
"""

_MARK_IMPORT_REMOVALS_SQL: Final[str] = (
    """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text
    )
), affected_collections AS (
    SELECT DISTINCT CAST(collection_id AS uuid) AS collection_id
    FROM incoming
), candidates AS MATERIALIZED (
    SELECT existing.*
    FROM feature.curation_items AS existing
    JOIN affected_collections
      ON affected_collections.collection_id = existing.collection_id
    WHERE existing.archived_at IS NULL
      AND existing.source_present
      AND NOT EXISTS (
          SELECT 1
          FROM incoming
          WHERE CAST(incoming.collection_id AS uuid) = existing.collection_id
            AND incoming.external_item_id = existing.external_item_id
            AND (
                incoming.external_component_id = existing.external_component_id
                OR (
                    incoming.feature_id IS NOT NULL
                    AND existing.feature_id = incoming.feature_id
                    AND existing.external_component_id LIKE 'legacy:%'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM feature.curation_items AS exact_identity
                        WHERE exact_identity.collection_id =
                            existing.collection_id
                          AND exact_identity.external_item_id =
                              incoming.external_item_id
                          AND exact_identity.external_component_id =
                              incoming.external_component_id
                    )
                )
            )
      )
    FOR UPDATE OF existing
), marked AS (
    UPDATE feature.curation_items AS existing
    SET source_present = false,
        source_updated_at = clock_timestamp(),
        updated_by = :actor,
        updated_at = now()
    FROM candidates
    WHERE existing.curation_item_id = candidates.curation_item_id
    RETURNING candidates.*
)
SELECT
"""
    + _ITEM_SELECT_FIELDS
    + """
FROM marked AS i
JOIN feature.curation_collections AS c ON c.collection_id = i.collection_id
JOIN feature.curated_themes AS t ON t.theme_id = c.theme_id
LEFT JOIN feature.curated_sources AS s ON s.source_id = c.source_id
LEFT JOIN feature.features AS f ON f.feature_id = i.feature_id
LEFT JOIN feature.curation_link_decisions AS link_decision
  ON link_decision.decision_id = i.accepted_link_decision_id
ORDER BY c.collection_key, i.sort_order, i.curation_item_id
"""
)

_LEGACY_IMPORT_ADOPTION_CONFLICTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_key text,
        feature_id text,
        external_item_id text,
        external_component_id text
    )
), conflicts AS (
    SELECT
        incoming.collection_key,
        incoming.external_item_id,
        incoming.external_component_id,
        incoming.feature_id,
        array_agg(
            legacy.curation_item_id::text || ':' ||
            legacy.external_component_id || ':' ||
            CASE
                WHEN legacy.archived_at IS NULL THEN 'active'
                ELSE 'archived'
            END
            ORDER BY
                legacy.archived_at DESC NULLS LAST,
                legacy.curation_item_id
        ) AS candidates
    FROM incoming
    JOIN feature.curation_collections AS collection
      ON collection.collection_key = incoming.collection_key
    JOIN feature.curation_items AS legacy
      ON legacy.collection_id = collection.collection_id
     AND legacy.external_item_id = incoming.external_item_id
     AND legacy.feature_id = incoming.feature_id
     AND legacy.external_component_id LIKE 'legacy:%'
    WHERE incoming.feature_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS exact_identity
          WHERE exact_identity.collection_id = legacy.collection_id
            AND exact_identity.external_item_id = legacy.external_item_id
            AND exact_identity.external_component_id =
                incoming.external_component_id
      )
    GROUP BY
        incoming.collection_key,
        incoming.external_item_id,
        incoming.external_component_id,
        incoming.feature_id
    HAVING count(*) > 1
)
SELECT *
FROM conflicts
ORDER BY
    collection_key,
    external_item_id,
    external_component_id,
    feature_id
LIMIT 1
"""

_ADOPT_LEGACY_IMPORT_IDENTITIES_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), matched AS MATERIALIZED (
    SELECT
        legacy.curation_item_id,
        incoming.external_component_id,
        incoming.place_name,
        incoming.address_hint,
        incoming.sort_order,
        incoming.item_title,
        incoming.item_summary,
        incoming.metadata,
        legacy.archived_at
    FROM incoming
    JOIN feature.curation_items AS legacy
      ON legacy.collection_id = CAST(incoming.collection_id AS uuid)
     AND legacy.external_item_id = incoming.external_item_id
     AND legacy.feature_id = incoming.feature_id
     AND legacy.external_component_id LIKE 'legacy:%'
    WHERE incoming.feature_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM feature.curation_items AS exact_identity
          WHERE exact_identity.collection_id = legacy.collection_id
            AND exact_identity.external_item_id = legacy.external_item_id
            AND exact_identity.external_component_id =
                incoming.external_component_id
      )
    FOR UPDATE OF legacy
), written AS (
    UPDATE feature.curation_items AS legacy
    SET external_component_id = matched.external_component_id,
        place_name = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.place_name
            ELSE legacy.place_name
        END,
        address_hint = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.address_hint
            ELSE legacy.address_hint
        END,
        source_present = CASE
            WHEN matched.archived_at IS NULL
            THEN true
            ELSE legacy.source_present
        END,
        source_updated_at = CASE
            WHEN matched.archived_at IS NULL
            THEN clock_timestamp()
            ELSE legacy.source_updated_at
        END,
        sort_order = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.sort_order
            ELSE legacy.sort_order
        END,
        item_title = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.item_title
            ELSE legacy.item_title
        END,
        item_summary = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.item_summary
            ELSE legacy.item_summary
        END,
        metadata = CASE
            WHEN matched.archived_at IS NULL
            THEN matched.metadata
            ELSE legacy.metadata
        END,
        updated_by = :actor,
        updated_at = now()
    FROM matched
    WHERE legacy.curation_item_id = matched.curation_item_id
    RETURNING legacy.curation_item_id
)
SELECT count(*)::integer AS updated
FROM written
"""

_BULK_UPSERT_ITEMS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_id text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), written AS (
    INSERT INTO feature.curation_items (
        collection_id, feature_id, external_item_id, external_component_id,
        place_name, address_hint,
        source_present, source_updated_at, status, sort_order,
        item_title, item_summary, curation_relation, reuse_policy,
        metadata, created_by, updated_by, updated_at
    )
    SELECT
        CAST(incoming.collection_id AS uuid), incoming.feature_id,
        incoming.external_item_id, incoming.external_component_id,
        incoming.place_name, incoming.address_hint,
        true, clock_timestamp(), 'included', incoming.sort_order,
        incoming.item_title, incoming.item_summary, 'nearby_option',
        'manual_review', incoming.metadata, :actor, :actor, now()
    FROM incoming
    WHERE NOT EXISTS (
        SELECT 1
        FROM feature.curation_items AS tombstone
        WHERE tombstone.collection_id = CAST(incoming.collection_id AS uuid)
          AND tombstone.external_item_id = incoming.external_item_id
          AND tombstone.external_component_id = incoming.external_component_id
          AND tombstone.archived_at IS NOT NULL
    )
    ON CONFLICT (
        collection_id, external_item_id, external_component_id
    )
    -- status/curation_relation/reuse_policy는 CSV에 없는 하드코딩 default이며
    -- 운영자가 admin PATCH로 조정하는 override 필드다. authoritative 재적재가 이를
    -- 무조건 EXCLUDED default로 되돌리면 수동 큐레이션이 리셋되므로(#699), CONFLICT
    -- 경로에서는 이 3개를 갱신·비교에서 제외해 기존(운영자) 값을 보존한다.
    -- 반대로 제공자 파생 필드(place_name/address_hint/sort_order/item_title/item_summary/
    -- metadata)는 CSV가 정본이므로 운영자가 PATCH로 편집했더라도 재적재로 덮어쓴다(의도된 경계).
    DO UPDATE SET
        feature_id = EXCLUDED.feature_id,
        place_name = EXCLUDED.place_name,
        address_hint = EXCLUDED.address_hint,
        source_present = true,
        source_updated_at = clock_timestamp(),
        sort_order = EXCLUDED.sort_order,
        item_title = EXCLUDED.item_title,
        item_summary = EXCLUDED.item_summary,
        metadata = EXCLUDED.metadata,
        updated_by = EXCLUDED.updated_by,
        updated_at = now()
    WHERE (
        feature.curation_items.feature_id,
        feature.curation_items.source_present,
        feature.curation_items.place_name,
        feature.curation_items.address_hint,
        feature.curation_items.sort_order,
        feature.curation_items.item_title,
        feature.curation_items.item_summary,
        feature.curation_items.metadata
    ) IS DISTINCT FROM (
        EXCLUDED.feature_id,
        true,
        EXCLUDED.place_name,
        EXCLUDED.address_hint,
        EXCLUDED.sort_order,
        EXCLUDED.item_title,
        EXCLUDED.item_summary,
        EXCLUDED.metadata
    )
    RETURNING (xmax = 0) AS inserted
)
SELECT
    count(*) FILTER (WHERE inserted)::integer AS inserted,
    count(*) FILTER (WHERE NOT inserted)::integer AS updated
FROM written
"""

_INSERT_IMPORT_BATCH_SQL: Final[str] = """
INSERT INTO feature.curation_import_batches (
    content_sha256, batch_kind, row_count, actor, metadata
) VALUES (
    :content_sha256, :batch_kind, :row_count, :actor, CAST(:metadata AS jsonb)
)
RETURNING import_batch_id::text
"""

_IMPORT_ITEM_IDENTITIES_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        row_number integer,
        collection_key text,
        external_item_id text,
        external_component_id text
    )
)
SELECT
    incoming.row_number,
    item.curation_item_id::text AS curation_item_id,
    item.feature_id,
    item.accepted_link_decision_id::text AS accepted_link_decision_id,
    previous_decision.feature_id AS previous_decision_feature_id
FROM incoming
JOIN feature.curation_collections AS collection
  ON collection.collection_key = incoming.collection_key
JOIN feature.curation_items AS item
  ON item.collection_id = collection.collection_id
 AND item.external_item_id = incoming.external_item_id
 AND item.external_component_id = incoming.external_component_id
LEFT JOIN feature.curation_link_decisions AS previous_decision
  ON previous_decision.decision_id = item.accepted_link_decision_id
ORDER BY incoming.row_number
"""

_INSERT_IMPORT_ROWS_SQL: Final[str] = """
INSERT INTO feature.curation_import_rows (
    import_row_id, import_batch_id, curation_item_id, row_number,
    source_row_sha256, row_payload, provenance
)
SELECT
    CAST(value.import_row_id AS uuid),
    CAST(:import_batch_id AS uuid),
    CAST(value.curation_item_id AS uuid),
    value.row_number,
    value.source_row_sha256,
    value.row_payload,
    value.provenance
FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS value(
    import_row_id text,
    curation_item_id text,
    row_number integer,
    source_row_sha256 text,
    row_payload jsonb,
    provenance jsonb
)
"""

_INSERT_LINK_DECISIONS_SQL: Final[str] = """
INSERT INTO feature.curation_link_decisions (
    decision_id, curation_item_id, feature_id, import_row_id,
    decision_kind, match_basis, resolver_version, evidence, actor,
    supersedes_decision_id
)
SELECT
    CAST(value.decision_id AS uuid),
    CAST(value.curation_item_id AS uuid),
    value.feature_id,
    CAST(value.import_row_id AS uuid),
    value.decision_kind,
    value.match_basis,
    value.resolver_version,
    value.evidence,
    :actor,
    CAST(value.supersedes_decision_id AS uuid)
FROM jsonb_to_recordset(CAST(:decisions AS jsonb)) AS value(
    decision_id text,
    curation_item_id text,
    feature_id text,
    import_row_id text,
    decision_kind text,
    match_basis text,
    resolver_version text,
    evidence jsonb,
    supersedes_decision_id text
)
"""

_ADVANCE_IMPORT_POINTERS_SQL: Final[str] = """
WITH pointers AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:pointers AS jsonb)) AS value(
        curation_item_id text,
        import_row_id text,
        accepted_link_decision_id text
    )
)
UPDATE feature.curation_items AS item
SET current_import_row_id = CAST(pointers.import_row_id AS uuid),
    accepted_link_decision_id =
        CAST(pointers.accepted_link_decision_id AS uuid)
FROM pointers
WHERE item.curation_item_id = CAST(pointers.curation_item_id AS uuid)
"""

_INSERT_MANUAL_LINK_DECISION_SQL: Final[str] = """
INSERT INTO feature.curation_link_decisions (
    curation_item_id, feature_id, decision_kind, match_basis,
    resolver_version, evidence, actor, supersedes_decision_id
) VALUES (
    CAST(:curation_item_id AS uuid),
    :feature_id,
    :decision_kind,
    :match_basis,
    :resolver_version,
    CAST(:evidence AS jsonb),
    :actor,
    CAST(:supersedes_decision_id AS uuid)
)
RETURNING decision_id::text
"""

_LIST_UNATTRIBUTED_LINKS_SQL: Final[str] = """
SELECT
    item.curation_item_id::text AS curation_item_id,
    collection.collection_key,
    item.external_item_id,
    item.external_component_id,
    item.feature_id,
    item.place_name,
    item.address_hint,
    decision.match_basis,
    decision.resolver_version,
    decision.decided_at
FROM feature.curation_items AS item
JOIN feature.curation_collections AS collection
  ON collection.collection_id = item.collection_id
LEFT JOIN feature.curation_link_decisions AS decision
  ON decision.decision_id = item.accepted_link_decision_id
WHERE item.feature_id IS NOT NULL
  AND item.archived_at IS NULL
  AND item.source_present
  AND (
      decision.decision_id IS NULL
      OR decision.decision_kind <> 'accepted'
      OR decision.match_basis = 'legacy_unattributed'
  )
ORDER BY collection.collection_key, item.external_item_id,
         item.external_component_id, item.curation_item_id
LIMIT :limit
"""

_PREVIEW_IMPORT_COUNTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS value(
        collection_key text,
        feature_id text,
        external_item_id text,
        external_component_id text,
        place_name text,
        address_hint text,
        sort_order integer,
        item_title text,
        item_summary text,
        metadata jsonb
    )
), classified AS (
    SELECT
        (
            existing.curation_item_id IS NOT NULL
            OR EXISTS (
                SELECT 1
                FROM feature.curation_items AS tombstone
                WHERE tombstone.collection_id = collection.collection_id
                  AND tombstone.external_item_id = incoming.external_item_id
                  AND tombstone.external_component_id =
                      incoming.external_component_id
                  AND tombstone.archived_at IS NOT NULL
            )
        ) AS already_exists,
        existing.curation_item_id IS NOT NULL
        -- 실제 upsert가 CONFLICT에서 status/curation_relation/reuse_policy를 보존하므로
        -- (#699) dry-run preview도 이 3개를 needs_update 비교에서 제외해 "updated" 카운트를
        -- 실제 동작과 일치시킨다(운영자 편집만 다른 행을 updated로 오표시하지 않음).
        AND (
            existing.external_component_id IS DISTINCT FROM
                incoming.external_component_id
            OR existing.feature_id IS DISTINCT FROM incoming.feature_id
            OR NOT existing.source_present
            OR (
                existing.place_name,
                existing.address_hint,
                existing.sort_order,
                existing.item_title,
                existing.item_summary,
                existing.metadata
            ) IS DISTINCT FROM (
                incoming.place_name,
                incoming.address_hint,
                incoming.sort_order,
                incoming.item_title,
                incoming.item_summary,
                incoming.metadata
            )
        ) AS needs_update
    FROM incoming
    LEFT JOIN feature.curation_collections AS collection
      ON collection.collection_key = incoming.collection_key
    LEFT JOIN LATERAL (
        SELECT candidate.*
        FROM feature.curation_items AS candidate
        WHERE candidate.collection_id = collection.collection_id
          AND candidate.external_item_id = incoming.external_item_id
          AND (
              (
                  candidate.external_component_id =
                      incoming.external_component_id
                  AND candidate.archived_at IS NULL
              )
              OR (
                  incoming.feature_id IS NOT NULL
                  AND candidate.feature_id = incoming.feature_id
                  AND candidate.external_component_id LIKE 'legacy:%'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM feature.curation_items AS exact_identity
                      WHERE exact_identity.collection_id =
                          collection.collection_id
                        AND exact_identity.external_item_id =
                            incoming.external_item_id
                        AND exact_identity.external_component_id =
                            incoming.external_component_id
                  )
              )
          )
        ORDER BY
            (
                candidate.external_component_id =
                incoming.external_component_id
            ) DESC
        LIMIT 1
    ) AS existing ON true
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
  AND i.source_present
  AND EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text,
          external_component_id text
      )
      WHERE incoming.collection_key = c.collection_key
  )
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS incoming(
          collection_key text,
          feature_id text,
          external_item_id text,
          external_component_id text
      )
      WHERE incoming.collection_key = c.collection_key
        AND incoming.external_item_id = i.external_item_id
        AND (
            incoming.external_component_id = i.external_component_id
            OR (
                incoming.feature_id IS NOT NULL
                AND i.feature_id = incoming.feature_id
                AND i.external_component_id LIKE 'legacy:%'
                AND NOT EXISTS (
                    SELECT 1
                    FROM feature.curation_items AS exact_identity
                    WHERE exact_identity.collection_id = i.collection_id
                      AND exact_identity.external_item_id =
                          incoming.external_item_id
                      AND exact_identity.external_component_id =
                          incoming.external_component_id
                )
            )
        )
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
    matched.lat,
    matched.name_candidate_count
FROM requested
CROSS JOIN LATERAL (
    (
        SELECT
            f.feature_id,
            f.name,
            f.address,
            x_extension.ST_X(f.coord) AS lon,
            x_extension.ST_Y(f.coord) AS lat,
            1::bigint AS name_candidate_count
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
            x_extension.ST_Y(f.coord) AS lat,
            count(*) OVER () AS name_candidate_count
        FROM feature.features AS f
        WHERE requested.feature_id IS NULL
          AND requested.place_name IS NOT NULL
          AND lower(f.name) = lower(requested.place_name)
          AND f.deleted_at IS NULL
          AND f.status NOT IN ('deleted', 'hidden')
        ORDER BY f.feature_id
        LIMIT 101
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
        external_component_id=str(row["external_component_id"]),
        place_name=str(row["place_name"]),
        address_hint=row["address_hint"],
        source_present=bool(row["source_present"]),
        status=str(row["status"]),
        sort_order=int(row["sort_order"]),
        item_title=row["item_title"],
        item_summary=row["item_summary"],
        curation_relation=str(row["curation_relation"]),
        reuse_policy=str(row["reuse_policy"]),
        metadata=_object(row["metadata"]),
        current_import_row_id=(
            str(value) if (value := row.get("current_import_row_id")) else None
        ),
        accepted_link_decision_id=(
            str(value)
            if (value := row.get("accepted_link_decision_id"))
            else None
        ),
        link_match_basis=(
            str(value) if (value := row.get("link_match_basis")) else None
        ),
        link_resolver_version=(
            str(value) if (value := row.get("link_resolver_version")) else None
        ),
        link_evidence=_object(row.get("link_evidence")),
        link_actor=str(value) if (value := row.get("link_actor")) else None,
        link_decided_at=row.get("link_decided_at"),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
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
    public_only: bool = False,
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
                    "public_only": public_only,
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
                {
                    "collection_id": collection_id,
                    "include_archived": include_archived,
                    "public_only": public_only,
                },
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
                {
                    "collection_id": collection_id,
                    "include_archived": include_archived,
                    "public_only": public_only,
                },
            )
        )
        .mappings()
        .all()
    )
    return _collection(row), tuple(_item(item_row) for item_row in item_rows)


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


async def _lock_collection_keys(
    session: AsyncSession,
    collection_keys: Sequence[str],
) -> None:
    """아직 생성되지 않은 collection까지 stable key 순서로 직렬화한다."""

    normalized_keys = sorted(set(collection_keys))
    if not normalized_keys:
        return
    await session.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended(
                    'kortravelmap:curation-collection:' || collection_key,
                    0
                )
            )
            FROM unnest(CAST(:collection_keys AS text[]))
                AS requested(collection_key)
            ORDER BY collection_key
            """
        ),
        {"collection_keys": normalized_keys},
    )


async def _lock_curation_write_boundary(session: AsyncSession) -> None:
    """Theme·collection·Feature 순서가 다른 공식/수동 writer를 직렬화한다."""

    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('kortravelmap:curation-import', 0))"
        )
    )


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


async def _lock_legacy_projections_for_item(
    session: AsyncSession,
    *,
    collection_id: str,
    curation_item_id: str,
) -> bool:
    """Legacy-backed item은 legacy→collection→item 순서로 직렬화한다."""

    rows = (
        await session.execute(
            text(
                """
                SELECT legacy.curated_feature_id
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id = item.legacy_projection_id
                WHERE item.collection_id = CAST(:collection_id AS uuid)
                  AND item.curation_item_id = CAST(:curation_item_id AS uuid)
                  AND legacy.archived_at IS NULL
                  AND NOT legacy.metadata
                      @> '{"merge_projection_detached": true}'::jsonb
                ORDER BY legacy.curated_feature_id
                FOR UPDATE OF legacy
                """
            ),
            {
                "collection_id": collection_id,
                "curation_item_id": curation_item_id,
            },
        )
    ).all()
    return bool(rows)


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
    normalized_collection_key = collection_key.strip()
    await _lock_curation_write_boundary(session)
    await _lock_collection_keys(session, (normalized_collection_key,))
    collection_id = str(
        (
            await session.execute(
                text(_CREATE_COLLECTION_SQL),
                {
                    "collection_key": normalized_collection_key,
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
    external_component_id: str = "primary",
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
    if (
        not 0 <= sort_order <= _POSTGRES_INTEGER_MAX
        or not external_item_id.strip()
        or not external_component_id.strip()
    ):
        raise ValueError("invalid curation item identity")
    resolved_place_name = place_name.strip() if place_name else ""
    if feature_id is not None:
        feature_name = (
            await session.execute(
                text(
                    "SELECT name FROM feature.features "
                    "WHERE feature_id = :id AND deleted_at IS NULL "
                    "AND status NOT IN ('deleted','hidden') "
                    "FOR KEY SHARE"
                ),
                {"id": feature_id},
            )
        ).scalar_one_or_none()
        if feature_name is None:
            raise ValueError("feature_id must reference an active Feature")
        if not resolved_place_name:
            resolved_place_name = str(feature_name)
    if not await _lock_collection(session, collection_id):
        raise LookupError("curation collection 없음")
    if not resolved_place_name:
        raise ValueError("place_name or an existing feature_id is required")
    archived_identity_exists = (
        await session.execute(
            text(
                "SELECT 1 FROM feature.curation_items "
                "WHERE collection_id = CAST(:collection_id AS uuid) "
                "AND external_item_id = :external_item_id "
                "AND external_component_id = :external_component_id "
                "AND archived_at IS NOT NULL"
            ),
            {
                "collection_id": collection_id,
                "external_item_id": external_item_id.strip(),
                "external_component_id": external_component_id.strip(),
            },
        )
    ).scalar_one_or_none()
    if archived_identity_exists is not None:
        raise ValueError("archive된 curation item identity는 재사용할 수 없습니다.")
    if feature_id is not None:
        duplicate_feature_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND external_component_id <> :external_component_id "
                    "AND feature_id = :feature_id "
                    "AND source_present "
                    "AND archived_at IS NULL"
                ),
                {
                    "collection_id": collection_id,
                    "external_item_id": external_item_id.strip(),
                    "external_component_id": external_component_id.strip(),
                    "feature_id": feature_id,
                },
            )
        ).scalar_one_or_none()
        if duplicate_feature_exists is not None:
            raise ValueError(
                "같은 외부 항목의 다른 component가 이미 이 Feature를 참조합니다."
            )
    row = (
        (
            await session.execute(
                text(_UPSERT_ITEM_SQL),
                {
                    "collection_id": collection_id,
                    "feature_id": feature_id,
                    "source_record_key": source_record_key,
                    "external_item_id": external_item_id.strip(),
                    "external_component_id": external_component_id.strip(),
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
    previous_decision = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        item.accepted_link_decision_id::text AS decision_id,
                        decision.feature_id
                    FROM feature.curation_items AS item
                    LEFT JOIN feature.curation_link_decisions AS decision
                      ON decision.decision_id =
                         item.accepted_link_decision_id
                    WHERE item.curation_item_id =
                          CAST(:curation_item_id AS uuid)
                    """
                ),
                {"curation_item_id": item_id},
            )
        )
        .mappings()
        .one()
    )
    previous_decision_id = (
        str(previous_decision["decision_id"])
        if previous_decision["decision_id"]
        else None
    )
    if feature_id is not None:
        await _record_manual_link_decision(
            session,
            curation_item_id=item_id,
            feature_id=feature_id,
            decision_kind="accepted",
            actor=actor,
            supersedes_decision_id=previous_decision_id,
            evidence={
                "operation": "add_curation_item",
                "requested_feature_id": feature_id,
            },
        )
    elif previous_decision_id is not None:
        await _record_manual_link_decision(
            session,
            curation_item_id=item_id,
            feature_id=str(previous_decision["feature_id"]),
            decision_kind="revoked",
            actor=actor,
            supersedes_decision_id=previous_decision_id,
            evidence={
                "operation": "add_curation_item",
                "reason": "명시적 feature_id=null",
            },
        )
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

    allowed = {
        "feature_id",
        "source_record_key",
        "external_item_id",
        "external_component_id",
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
        if key in {"external_item_id", "external_component_id", "place_name"}:
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

    if not normalized:
        if not await _lock_collection(session, collection_id):
            return None
        current = await get_curation_item(
            session,
            collection_id=collection_id,
            curation_item_id=curation_item_id,
            include_archived=True,
        )
        return current if current is not None and current.archived_at is None else None

    source_owned_changed = bool(
        {
            "feature_id",
            "source_record_key",
            "external_item_id",
            "external_component_id",
            "place_name",
            "address_hint",
            "sort_order",
            "item_title",
            "item_summary",
            "metadata",
        }
        & normalized.keys()
    )
    target_feature_id = normalized.get("feature_id")
    if target_feature_id is not None:
        target_is_active = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.features "
                    "WHERE feature_id = :feature_id AND deleted_at IS NULL "
                    "AND status NOT IN ('deleted','hidden') "
                    "FOR KEY SHARE"
                ),
                {"feature_id": target_feature_id},
            )
        ).scalar_one_or_none()
        if target_is_active is None:
            raise ValueError("feature_id에 해당하는 Feature가 없습니다.")

    legacy_backed = await _lock_legacy_projections_for_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
    )
    if legacy_backed and source_owned_changed:
        raise ValueError(
            "legacy projection 기반 curation item의 source 필드는 "
            "legacy writer에서 수정해야 합니다."
        )
    if not await _lock_collection(session, collection_id):
        return None
    current = await get_curation_item(
        session,
        collection_id=collection_id,
        curation_item_id=curation_item_id,
        include_archived=True,
    )
    if current is None or current.archived_at is not None:
        return None

    feature_id = normalized.get("feature_id", current.feature_id)
    if {
        "feature_id",
        "external_item_id",
        "external_component_id",
    } & normalized.keys():
        target_external_item_id = str(
            normalized.get("external_item_id", current.external_item_id)
        )
        target_external_component_id = str(
            normalized.get(
                "external_component_id",
                current.external_component_id,
            )
        )
        archived_identity_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM feature.curation_items "
                    "WHERE collection_id = CAST(:collection_id AS uuid) "
                    "AND curation_item_id <> CAST(:curation_item_id AS uuid) "
                    "AND external_item_id = :external_item_id "
                    "AND external_component_id = :external_component_id "
                    "AND archived_at IS NOT NULL"
                ),
                {
                    "collection_id": collection_id,
                    "curation_item_id": curation_item_id,
                    "external_item_id": target_external_item_id,
                    "external_component_id": target_external_component_id,
                },
            )
        ).scalar_one_or_none()
        if archived_identity_exists is not None:
            raise ValueError("archive된 curation item identity는 재사용할 수 없습니다.")

        if current.source_present and feature_id is not None:
            duplicate_feature_exists = (
                await session.execute(
                    text(
                        "SELECT 1 FROM feature.curation_items "
                        "WHERE collection_id = CAST(:collection_id AS uuid) "
                        "AND curation_item_id <> CAST(:curation_item_id AS uuid) "
                        "AND external_item_id = :external_item_id "
                        "AND feature_id = :feature_id "
                        "AND source_present "
                        "AND archived_at IS NULL"
                    ),
                    {
                        "collection_id": collection_id,
                        "curation_item_id": curation_item_id,
                        "external_item_id": target_external_item_id,
                        "feature_id": feature_id,
                    },
                )
            ).scalar_one_or_none()
            if duplicate_feature_exists is not None:
                raise ValueError(
                    "같은 외부 항목의 다른 component가 이미 이 Feature를 참조합니다."
                )
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
    operator_owned_changed = bool(
        {"status", "curation_relation", "reuse_policy"} & normalized.keys()
    )
    if source_owned_changed:
        clauses.append("source_updated_at = clock_timestamp()")
    if operator_owned_changed:
        clauses.extend(
            [
                "operator_updated_by = :actor",
                "operator_updated_at = clock_timestamp()",
            ]
        )
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
    if "feature_id" in normalized:
        requested_feature_id = normalized["feature_id"]
        if requested_feature_id is not None:
            await _record_manual_link_decision(
                session,
                curation_item_id=curation_item_id,
                feature_id=str(requested_feature_id),
                decision_kind="accepted",
                actor=actor,
                supersedes_decision_id=current.accepted_link_decision_id,
                evidence={
                    "operation": "update_curation_item",
                    "previous_feature_id": current.feature_id,
                    "requested_feature_id": requested_feature_id,
                },
            )
        elif current.feature_id is not None:
            await _record_manual_link_decision(
                session,
                curation_item_id=curation_item_id,
                feature_id=current.feature_id,
                decision_kind="revoked",
                actor=actor,
                supersedes_decision_id=current.accepted_link_decision_id,
                evidence={
                    "operation": "update_curation_item",
                    "previous_feature_id": current.feature_id,
                    "reason": "명시적 feature_id=null",
                },
            )
    if operator_owned_changed:
        target_status = str(normalized.get("status", current.status))
        target_relation = str(
            normalized.get("curation_relation", current.curation_relation)
        )
        target_reuse_policy = str(
            normalized.get("reuse_policy", current.reuse_policy)
        )
        await session.execute(
            text(
                """
                UPDATE feature.curated_features AS legacy
                SET curation_status = :legacy_status,
                    selection_origin = 'admin',
                    selected_by = CASE
                        WHEN :legacy_status = 'curated' THEN :actor
                        ELSE selected_by
                    END,
                    selected_at = CASE
                        WHEN :legacy_status = 'curated' THEN now()
                        ELSE selected_at
                    END,
                    rejected_by = CASE
                        WHEN :legacy_status = 'rejected' THEN :actor
                        WHEN :legacy_status IN ('curated', 'candidate') THEN NULL
                        ELSE rejected_by
                    END,
                    rejected_at = CASE
                        WHEN :legacy_status = 'rejected' THEN now()
                        WHEN :legacy_status IN ('curated', 'candidate') THEN NULL
                        ELSE rejected_at
                    END,
                    rejection_reason = CASE
                        WHEN :legacy_status IN ('curated', 'candidate') THEN NULL
                        ELSE rejection_reason
                    END,
                    curation_relation = :curation_relation,
                    reuse_policy = :reuse_policy,
                    operator_updated_by = :actor,
                    operator_updated_at = clock_timestamp(),
                    archived_at = CASE
                        WHEN :legacy_status = 'archived' THEN now()
                        ELSE NULL
                    END,
                    updated_at = now(),
                    content_version = content_version + 1
                FROM feature.curation_items AS item
                WHERE item.collection_id = CAST(:collection_id AS uuid)
                  AND item.curation_item_id =
                      CAST(:curation_item_id AS uuid)
                  AND item.legacy_projection_id =
                      legacy.curated_feature_id
                  AND legacy.archived_at IS NULL
                """
            ),
            {
                "curation_item_id": curation_item_id,
                "collection_id": collection_id,
                "legacy_status": (
                    "curated" if target_status == "included" else target_status
                ),
                "curation_relation": target_relation,
                "reuse_policy": target_reuse_policy,
                "actor": actor,
            },
        )
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


async def list_unattributed_curation_links(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> tuple[CurationLinkAudit, ...]:
    """공개 승인에 쓸 수 없는 provenance-less/legacy current link를 나열한다."""

    effective_limit = max(1, min(limit, 10_000))
    rows = (
        (
            await session.execute(
                text(_LIST_UNATTRIBUTED_LINKS_SQL),
                {"limit": effective_limit},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        CurationLinkAudit(
            curation_item_id=str(row["curation_item_id"]),
            collection_key=str(row["collection_key"]),
            external_item_id=str(row["external_item_id"]),
            external_component_id=str(row["external_component_id"]),
            feature_id=str(row["feature_id"]),
            place_name=str(row["place_name"]),
            address_hint=row["address_hint"],
            match_basis=(
                str(row["match_basis"]) if row["match_basis"] else None
            ),
            resolver_version=(
                str(row["resolver_version"])
                if row["resolver_version"]
                else None
            ),
            decided_at=row["decided_at"],
        )
        for row in rows
    )


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
    """CSV 전체의 exact Feature/name 후보를 한 번의 parameterized query로 찾는다.

    DB는 ``lower(name)`` index로 후보만 좁힌다. 주소는 JSON serialization/SQL pattern을
    전혀 사용하지 않고 Python의 구조화 literal matcher로 판정한다.
    """

    if not requests:
        return {}
    payload = [
        {
            "row_number": request.row_number,
            "feature_id": request.feature_id.strip() if request.feature_id else None,
            "place_name": normalize_korean_text(request.place_name),
            "address_hint": normalize_korean_text(request.address_hint),
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
    requests_by_row = {request.row_number: request for request in requests}
    grouped: dict[int, list[FeatureMatch]] = {request.row_number: [] for request in requests}
    for row in rows:
        row_number = int(row["row_number"])
        request = requests_by_row[row_number]
        if (
            request.feature_id is None
            and int(row["name_candidate_count"]) > _FEATURE_MATCH_NAME_CANDIDATE_LIMIT
        ):
            # 상한 밖 후보를 보지 않고 "유일"로 오판하지 않는다.
            grouped[row_number].clear()
            continue
        match = _feature_match(row)
        normalized_hint = normalize_korean_text(request.address_hint)
        if (
            request.feature_id is None
            and normalized_hint is not None
            and not address_hint_matches(match.address, normalized_hint)
        ):
            continue
        grouped[row_number].append(match)
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
    await _lock_curation_write_boundary(session)
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
    """실제 Feature 해소 결과의 component·target identity 충돌을 찾는다."""

    by_component: dict[tuple[str, str, str], list[ResolvedCurationImportRow]] = {}
    by_feature: dict[tuple[str, str, str], list[ResolvedCurationImportRow]] = {}
    for row in rows:
        by_component.setdefault(
            (row.collection_key, row.source_item_key, row.source_component_key),
            [],
        ).append(row)
        if row.feature_id is not None:
            by_feature.setdefault(
                (row.collection_key, row.source_item_key, row.feature_id),
                [],
            ).append(row)

    issues: dict[tuple[int, str], ResolvedCurationIdentityIssue] = {}
    for grouped_rows in by_component.values():
        if len(grouped_rows) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="duplicate_component_identity",
                    message=(
                        "Feature 해소 후 collection/source_item_key/"
                        "source_component_key identity가 중복됩니다."
                    ),
                )
                issues[(issue.row_number, issue.code)] = issue
    for grouped_rows in by_feature.values():
        if len(grouped_rows) > 1:
            for row in grouped_rows:
                issue = ResolvedCurationIdentityIssue(
                    row_number=row.row_number,
                    code="duplicate_resolved_feature",
                    message=(
                        "같은 collection/source_item_key의 component가 "
                        "동일 Feature를 중복 참조합니다."
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


def _canonical_import_row_payload(
    row: ResolvedCurationImportRow,
) -> dict[str, Any]:
    return {
        "row_number": row.row_number,
        "collection_key": row.collection_key,
        "theme_slug": row.theme_slug,
        "theme_name": row.theme_name,
        "theme_group": row.theme_group,
        "title": row.title,
        "edition_key": row.edition_key,
        "provider": row.provider,
        "dataset_key": row.dataset_key,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_item_key": row.source_item_key,
        "source_component_key": row.source_component_key,
        "feature_id": row.feature_id,
        "place_name": row.place_name,
        "address_hint": row.address_hint,
        "sort_order": row.sort_order,
        "item_title": row.item_title,
        "item_summary": row.item_summary,
        "metadata": row.metadata,
    }


def _canonical_json_sha256(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _validated_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("content_sha256는 lowercase SHA-256 hex여야 합니다.")
    return normalized


async def _record_import_provenance(
    session: AsyncSession,
    *,
    rows: Sequence[ResolvedCurationImportRow],
    actor: str | None,
    source_content_sha256: str | None,
    batch_kind: str | None,
) -> str:
    """current item을 exact immutable import row/decision으로 전진시킨다."""

    effective_actor = (actor or "system:curation-import").strip()
    if not effective_actor:
        raise ValueError("curation import actor는 비어 있을 수 없습니다.")
    canonical_rows = [_canonical_import_row_payload(row) for row in rows]
    effective_content_sha256 = (
        _validated_sha256(source_content_sha256)
        if source_content_sha256 is not None
        else _canonical_json_sha256(canonical_rows)
    )
    effective_kind = batch_kind or (
        "csv_upload" if source_content_sha256 is not None else "normalized_rows"
    )
    if effective_kind not in {
        "csv_upload",
        "normalized_rows",
        "forward_recovery",
    }:
        raise ValueError("지원하지 않는 curation import batch_kind입니다.")

    import_batch_id = str(
        (
            await session.execute(
                text(_INSERT_IMPORT_BATCH_SQL),
                {
                    "content_sha256": effective_content_sha256,
                    "batch_kind": effective_kind,
                    "row_count": len(rows),
                    "actor": effective_actor,
                    "metadata": json.dumps(
                        {
                            "schema_version": 1,
                            "address_resolver": CURATION_ADDRESS_RESOLVER_VERSION,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        ).scalar_one()
    )
    if not rows:
        return import_batch_id

    identity_payload = json.dumps(
        [
            {
                "row_number": row.row_number,
                "collection_key": row.collection_key,
                "external_item_id": row.source_item_key,
                "external_component_id": row.source_component_key,
            }
            for row in rows
        ],
        ensure_ascii=False,
    )
    identity_rows = (
        (
            await session.execute(
                text(_IMPORT_ITEM_IDENTITIES_SQL),
                {"items": identity_payload},
            )
        )
        .mappings()
        .all()
    )
    identities = {int(row["row_number"]): row for row in identity_rows}
    if set(identities) != {row.row_number for row in rows}:
        raise RuntimeError("import row를 current curation item에 exact 결박하지 못했습니다.")

    import_rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    pointers: list[dict[str, Any]] = []
    for row, row_payload in zip(rows, canonical_rows, strict=True):
        identity = identities[row.row_number]
        current_feature_id = (
            str(identity["feature_id"]) if identity["feature_id"] else None
        )
        if current_feature_id != row.feature_id:
            raise RuntimeError("import 직후 item Feature가 normalized row와 다릅니다.")
        import_row_id = str(uuid4())
        source_row_sha256 = _canonical_json_sha256(row_payload)
        import_rows.append(
            {
                "import_row_id": import_row_id,
                "curation_item_id": str(identity["curation_item_id"]),
                "row_number": row.row_number,
                "source_row_sha256": source_row_sha256,
                "row_payload": row_payload,
                "provenance": row.provenance or {},
            }
        )
        previous_decision_id = (
            str(identity["accepted_link_decision_id"])
            if identity["accepted_link_decision_id"]
            else None
        )
        accepted_decision_id: str | None = None
        if row.feature_id is not None:
            accepted_decision_id = str(uuid4())
            decisions.append(
                {
                    "decision_id": accepted_decision_id,
                    "curation_item_id": str(identity["curation_item_id"]),
                    "feature_id": row.feature_id,
                    "import_row_id": import_row_id,
                    "decision_kind": "accepted",
                    "match_basis": "csv_explicit_feature_id",
                    "resolver_version": "explicit-feature-id-v1",
                    "evidence": {
                        "source_row_sha256": source_row_sha256,
                        "requested_feature_id": row.feature_id,
                        "normalized_place_name": normalize_korean_text(
                            row.place_name
                        ),
                        "normalized_address_hint": normalize_korean_text(
                            row.address_hint
                        ),
                    },
                    "supersedes_decision_id": previous_decision_id,
                }
            )
        elif previous_decision_id is not None:
            previous_feature_id = str(identity["previous_decision_feature_id"])
            decisions.append(
                {
                    "decision_id": str(uuid4()),
                    "curation_item_id": str(identity["curation_item_id"]),
                    "feature_id": previous_feature_id,
                    "import_row_id": import_row_id,
                    "decision_kind": "revoked",
                    "match_basis": "csv_explicit_feature_id",
                    "resolver_version": "explicit-feature-id-v1",
                    "evidence": {
                        "source_row_sha256": source_row_sha256,
                        "previous_feature_id": previous_feature_id,
                        "reason": "authoritative import row에 feature_id가 없음",
                    },
                    "supersedes_decision_id": previous_decision_id,
                }
            )
        pointers.append(
            {
                "curation_item_id": str(identity["curation_item_id"]),
                "import_row_id": import_row_id,
                "accepted_link_decision_id": accepted_decision_id,
            }
        )

    await session.execute(
        text(_INSERT_IMPORT_ROWS_SQL),
        {
            "import_batch_id": import_batch_id,
            "rows": json.dumps(import_rows, ensure_ascii=False),
        },
    )
    if decisions:
        await session.execute(
            text(_INSERT_LINK_DECISIONS_SQL),
            {
                "actor": effective_actor,
                "decisions": json.dumps(decisions, ensure_ascii=False),
            },
        )
    await session.execute(
        text(_ADVANCE_IMPORT_POINTERS_SQL),
        {"pointers": json.dumps(pointers, ensure_ascii=False)},
    )
    return import_batch_id


async def _record_manual_link_decision(
    session: AsyncSession,
    *,
    curation_item_id: str,
    feature_id: str,
    decision_kind: Literal["accepted", "revoked"],
    actor: str | None,
    supersedes_decision_id: str | None,
    evidence: Mapping[str, Any],
) -> str:
    effective_actor = (actor or "system:curation-admin").strip()
    if not effective_actor:
        raise ValueError("curation link decision actor는 비어 있을 수 없습니다.")
    decision_id = str(
        (
            await session.execute(
                text(_INSERT_MANUAL_LINK_DECISION_SQL),
                {
                    "curation_item_id": curation_item_id,
                    "feature_id": feature_id,
                    "decision_kind": decision_kind,
                    "match_basis": "admin_review",
                    "resolver_version": "manual-admin-v1",
                    "evidence": json.dumps(dict(evidence), ensure_ascii=False),
                    "actor": effective_actor,
                    "supersedes_decision_id": supersedes_decision_id,
                },
            )
        ).scalar_one()
    )
    await session.execute(
        text(
            """
            UPDATE feature.curation_items
            SET accepted_link_decision_id =
                    CASE
                        WHEN :decision_kind = 'accepted'
                        THEN CAST(:decision_id AS uuid)
                        ELSE NULL
                    END
            WHERE curation_item_id = CAST(:curation_item_id AS uuid)
            """
        ),
        {
            "curation_item_id": curation_item_id,
            "decision_id": decision_id,
            "decision_kind": decision_kind,
        },
    )
    return decision_id


async def _ensure_unambiguous_legacy_import_adoptions(
    session: AsyncSession,
    *,
    payload: str,
) -> None:
    conflict = (
        (
            await session.execute(
                text(_LEGACY_IMPORT_ADOPTION_CONFLICTS_SQL),
                {"items": payload},
            )
        )
        .mappings()
        .first()
    )
    if conflict is not None:
        raise ValueError(
            "legacy component identity 승계 후보가 모호합니다: "
            f"collection={conflict['collection_key']}, "
            f"item={conflict['external_item_id']}, "
            f"component={conflict['external_component_id']}, "
            f"feature={conflict['feature_id']}, "
            f"candidates={list(conflict['candidates'])!r}"
        )


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
            "external_component_id": row.source_component_key,
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
    await _ensure_unambiguous_legacy_import_adoptions(session, payload=payload)
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
    source_content_sha256: str | None = None,
    batch_kind: str | None = None,
) -> CurationImportResult:
    """검증·Feature 해소가 끝난 CSV 행을 한 transaction에서 멱등 upsert한다."""
    _ensure_resolved_curation_identities(rows)
    collections: dict[str, str] = {}
    item_values: list[dict[str, Any]] = []
    if rows:
        # 서로 다른 CSV가 theme/source/collection lock을 역순으로 잡는 deadlock과
        # 같은 collection의 authoritative replace 경합을 하나의 write 경계로 직렬화한다.
        await _lock_curation_write_boundary(session)
        collection_keys = sorted({row.collection_key for row in rows})
        await _lock_collection_keys(session, collection_keys)
        feature_ids = sorted(
            {str(row.feature_id) for row in rows if row.feature_id is not None}
        )
        if feature_ids:
            active_feature_ids = set(
                (
                    await session.execute(
                        text(
                            "SELECT feature_id FROM feature.features "
                            "WHERE feature_id = ANY(CAST(:feature_ids AS text[])) "
                            "AND deleted_at IS NULL "
                            "AND status NOT IN ('deleted', 'hidden') "
                            "ORDER BY feature_id FOR UPDATE"
                        ),
                        {"feature_ids": feature_ids},
                    )
                )
                .scalars()
                .all()
            )
            if active_feature_ids != set(feature_ids):
                raise ValueError(
                    "큐레이션 반영 중 Feature lifecycle이 변경되었습니다. 다시 preview하세요."
                )
        await session.execute(
            text(
                "SELECT collection_id FROM feature.curation_collections "
                "WHERE collection_key = ANY(CAST(:collection_keys AS text[])) "
                "ORDER BY collection_id FOR UPDATE"
            ),
            {"collection_keys": collection_keys},
        )
        legacy_adoption_payload = json.dumps(
            [
                {
                    "collection_key": row.collection_key,
                    "feature_id": row.feature_id,
                    "external_item_id": row.source_item_key,
                    "external_component_id": row.source_component_key,
                }
                for row in rows
            ],
            ensure_ascii=False,
        )
        await _ensure_unambiguous_legacy_import_adoptions(
            session,
            payload=legacy_adoption_payload,
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
                "external_component_id": row.source_component_key,
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
            (
                await session.execute(
                    text(_MARK_IMPORT_REMOVALS_SQL),
                    {"items": items_payload, "actor": actor},
                )
            )
            .mappings()
            .all()
        )
        removals = tuple(_item(row) for row in removed_rows)
        adopted = int(
            (
                await session.execute(
                    text(_ADOPT_LEGACY_IMPORT_IDENTITIES_SQL),
                    {"items": items_payload, "actor": actor},
                )
            ).scalar_one()
        )
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
            "updated": adopted + int(count_row["updated"] or 0),
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
    import_batch_id = await _record_import_provenance(
        session,
        rows=rows,
        actor=actor,
        source_content_sha256=source_content_sha256,
        batch_kind=batch_kind,
    )
    return {
        "rows": len(rows),
        "collections": len(collections),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "removed": counts["removed"],
        "removals": removals,
        "import_batch_id": import_batch_id,
    }
