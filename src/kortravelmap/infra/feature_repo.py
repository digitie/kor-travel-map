"""``kortravelmap.infra.feature_repo`` — Feature 적재/조회 raw SQL repository.

``FeatureBundle`` (provider 변환 출력)을 ``feature.features`` / ``provider_sync.
source_records`` / ``provider_sync.source_links`` 3 테이블에 한 transaction으로
upsert하는 **첫 DB write 경로** (ADR-004 raw SQL, ORM은 매핑만).

설계 원칙
---------
- **raw SQL ``text()``만** (ADR-004) — `_SQL` 상수로 모아 EXPLAIN 검증 친화.
- **commit은 호출자 책임** — 본 repo는 ``session.execute``만, transaction 경계는
  ``AsyncKorTravelMapClient.load_feature_bundles`` 또는 호출자가 잡는다 (단위 of work).
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
import binascii
import hashlib
import hmac
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from sqlalchemy import text

from kortravelmap.core.exceptions import (
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import Feature, FeatureBundle, SourceLink, SourceRecord

__all__ = [
    "AirQualityLoadResult",
    "DEFAULT_PRICE_STALE_HIDE_DAYS",
    "EnrichmentLoadResult",
    "FeatureLoadResult",
    "FeatureBatchItemRow",
    "FeatureSearchPage",
    "FeatureSearchRow",
    "NearbyFeaturePage",
    "NearbyFeatureRow",
    "load_source_record_links",
    "upsert_feature",
    "upsert_source_record",
    "upsert_source_link",
    "load_bundle",
    "load_bundles",
    "load_authoritative_notice_snapshot",
    "load_notice_event_bundles",
    "soft_delete_features_not_in_snapshot",
    "inactivate_features_by_source_entity_ids",
    "inactivate_geometryless_area_features_by_source",
    "NoticeReconcileResult",
    "NoticeFeatureLoadResult",
    "close_notice_features",
    "get_notice_snapshot_watermark",
    "supersede_stale_notice_features",
    "purge_expired_notices",
    "get_feature_row",
    "get_feature_rows_by_ids",
    "get_public_feature_row",
    "get_public_feature_rows_by_ids",
    "get_service_feature_batch_items",
    "public_active_notice_filter_sql",
    "public_active_notice_feature_ids",
    "list_active_place_coords",
    "list_primary_place_locator",
    "get_primary_source_detail",
    "find_place_features_without_phone",
    "set_feature_phones",
    "features_in_bbox",
    "features_contained_in_area",
    "encode_bbox_cursor",
    "search_features",
    "features_nearby_poi_cache_target",
]


def _price_stale_hide_days_default() -> int:
    """현재가 표시 제외 지평선(일) 기본값 — env 우선, 최소 1일.

    repo 계층은 primitive 인자만 받는 설계라 pydantic settings를 만들지 않고
    (필수 env 없이도 import 가능해야 함) env를 import 시 한 번 읽는다. 기본 4일
    = OpiNet 시군 윈도 로테이션 전체 주기 — 이보다 오래된 관측은 "현재 가격"이
    아니라 이력으로만 취급한다(값 보존, 표시만 제외).
    """
    raw = os.environ.get("KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS", "")
    try:
        parsed = int(raw)
    except ValueError:
        return 4
    return max(parsed, 1)


DEFAULT_PRICE_STALE_HIDE_DAYS: Final[int] = _price_stale_hide_days_default()
"""repository ``price_summary`` 기본 표시 제외 지평선(일).

env ``KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS`` (기본 4 = OpiNet 로테이션 1주기).
지도 API는 오래된 관측도 날짜와 함께 표시하기 위해 이 기본값을 ``None``으로 override한다."""


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
    data_origin, data_version, user_change_kind, user_change_status,
    user_change_request_id, user_deleted_at, user_deleted_by, user_change_reason,
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
    'provider', 0, NULL, NULL, NULL, NULL, NULL, NULL,
    :created_at, :updated_at, :deleted_at
)
ON CONFLICT (feature_id) DO UPDATE SET
    kind = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.kind ELSE EXCLUDED.kind END,
    name = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.name ELSE EXCLUDED.name END,
    category = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.category ELSE EXCLUDED.category END,
    coord = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.coord ELSE EXCLUDED.coord END,
    coord_precision_digits = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.coord_precision_digits ELSE EXCLUDED.coord_precision_digits END,
    geom = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.geom ELSE EXCLUDED.geom END,
    address = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.address ELSE EXCLUDED.address END,
    legal_dong_code = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.legal_dong_code ELSE EXCLUDED.legal_dong_code END,
    road_name_code = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.road_name_code ELSE EXCLUDED.road_name_code END,
    road_address_management_no = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.road_address_management_no ELSE EXCLUDED.road_address_management_no END,
    admin_dong_code = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.admin_dong_code ELSE EXCLUDED.admin_dong_code END,
    sido_code = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.sido_code ELSE EXCLUDED.sido_code END,
    sigungu_code = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.sigungu_code ELSE EXCLUDED.sigungu_code END,
    urls = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.urls ELSE EXCLUDED.urls END,
    marker_icon = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.marker_icon ELSE EXCLUDED.marker_icon END,
    marker_color = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.marker_color ELSE EXCLUDED.marker_color END,
    parent_feature_id = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.parent_feature_id ELSE EXCLUDED.parent_feature_id END,
    sibling_group_id = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.sibling_group_id ELSE EXCLUDED.sibling_group_id END,
    detail = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.detail
        WHEN features.kind = 'notice'
          AND EXCLUDED.kind = 'notice'
          AND EXCLUDED.detail #>> '{payload,valid_start_origin}' = 'first_probe'
          AND features.detail ? 'valid_start_time'
          AND features.detail -> 'valid_start_time' <> 'null'::jsonb
        THEN jsonb_set(
            EXCLUDED.detail,
            '{valid_start_time}',
            features.detail -> 'valid_start_time',
            true
        )
        ELSE EXCLUDED.detail END,
    raw_refs = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.raw_refs ELSE EXCLUDED.raw_refs END,
    status = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.status
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
    data_origin = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.data_origin ELSE 'provider' END,
    data_version = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.data_version ELSE 0 END,
    user_change_kind = features.user_change_kind,
    user_change_status = features.user_change_status,
    user_change_request_id = features.user_change_request_id,
    user_deleted_at = features.user_deleted_at,
    user_deleted_by = features.user_deleted_by,
    user_change_reason = features.user_change_reason,
    updated_at = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.updated_at ELSE EXCLUDED.updated_at END,
    deleted_at = CASE
        WHEN features.data_origin = 'user_request' AND features.data_version > 0
        THEN features.deleted_at
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

_UPSERT_PROVIDER_VERSION_SQL: Final[str] = """
INSERT INTO feature.feature_versions (
    feature_id, version, origin, change_kind, payload, request_id, created_by
) VALUES (
    :feature_id, 0, 'provider', 'load', CAST(:payload AS jsonb), NULL, 'provider'
)
ON CONFLICT (feature_id, version) DO UPDATE SET
    payload = EXCLUDED.payload,
    origin = EXCLUDED.origin,
    change_kind = EXCLUDED.change_kind,
    created_by = EXCLUDED.created_by,
    created_at = now()
"""

# provider entity는 payload version과 독립적으로 한 행을 유지한다(ADR-063).
_UPSERT_SOURCE_ENTITY_SQL: Final[str] = """
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    :source_entity_key, :provider, :dataset_key,
    :source_entity_type, :source_entity_id,
    LEAST(
        CAST(:fetched_at AS timestamptz),
        CAST(:imported_at AS timestamptz)
    ),
    GREATEST(
        CAST(:fetched_at AS timestamptz),
        CAST(:imported_at AS timestamptz)
    )
)
ON CONFLICT (source_entity_key) DO UPDATE SET
    first_seen_at = LEAST(
        provider_sync.source_entities.first_seen_at,
        EXCLUDED.first_seen_at
    ),
    last_seen_at = GREATEST(
        provider_sync.source_entities.last_seen_at,
        EXCLUDED.last_seen_at
    )
RETURNING current_source_record_key
"""

# source_records는 payload_hash가 UNIQUE 구성요소 → 이력 보존 (ADR-017).
# 같은 source_record_key 재적재는 원문을 건드리지 않고 마지막 확인 시각만 갱신한다.
_UPSERT_SOURCE_RECORD_SQL: Final[str] = """
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, provider, dataset_key,
    source_entity_type, source_entity_id, source_version,
    raw_name, raw_address, raw_longitude, raw_latitude,
    raw_data, raw_payload_hash, fetched_at, imported_at, expires_at
) VALUES (
    :source_record_key, :source_entity_key, :provider, :dataset_key,
    :source_entity_type, :source_entity_id, :source_version,
    :raw_name, :raw_address, :raw_longitude, :raw_latitude,
    CAST(:raw_data AS jsonb), :raw_payload_hash, :fetched_at, :imported_at,
    :expires_at
)
ON CONFLICT (source_record_key) DO UPDATE SET
    last_seen_at = GREATEST(
        provider_sync.source_records.last_seen_at,
        clock_timestamp()
    )
RETURNING (xmax = 0) AS inserted
"""

_REFRESH_SOURCE_ENTITY_CURRENT_SQL: Final[str] = """
WITH ranked AS (
    SELECT source_record_key
    FROM provider_sync.source_records
    WHERE source_entity_key = :source_entity_key
    ORDER BY
        last_seen_at DESC,
        fetched_at DESC,
        imported_at DESC,
        source_record_key DESC
    LIMIT 1
), bounds AS (
    SELECT
        min(least(fetched_at, last_seen_at, imported_at)) AS first_seen_at,
        max(greatest(fetched_at, last_seen_at, imported_at)) AS last_seen_at
    FROM provider_sync.source_records
    WHERE source_entity_key = :source_entity_key
)
UPDATE provider_sync.source_entities AS se
SET current_source_record_key = ranked.source_record_key,
    first_seen_at = LEAST(se.first_seen_at, bounds.first_seen_at),
    last_seen_at = GREATEST(se.last_seen_at, bounds.last_seen_at)
FROM ranked, bounds
WHERE se.source_entity_key = :source_entity_key
RETURNING se.current_source_record_key
"""

_UPSERT_SOURCE_LINK_SQL: Final[str] = """
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role,
    match_method, confidence, is_primary_source, created_at
) VALUES (
    :feature_id,
    (SELECT source_entity_key
     FROM provider_sync.source_records
     WHERE source_record_key = :source_record_key),
    :source_role,
    :match_method, :confidence, :is_primary_source, :created_at
)
ON CONFLICT (feature_id, source_entity_key) DO UPDATE SET
    source_role = EXCLUDED.source_role,
    match_method = EXCLUDED.match_method,
    confidence = EXCLUDED.confidence,
    is_primary_source = EXCLUDED.is_primary_source
RETURNING (xmax = 0) AS inserted
"""

# feature 상세 row projection — raw read(``feature.features``)와 공개
# read(``feature.public_features``, ADR-067)가 같은 컬럼 목록을 공유한다.
_FEATURE_ROW_COLUMNS_SQL: Final[str] = """
    feature_id, kind, name, category,
    x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat,
    coord_precision_digits,
    CASE
      WHEN kind = 'area' AND geom IS NOT NULL
      THEN x_extension.ST_Area(CAST(geom AS x_extension.geography))
      ELSE NULL
    END AS area_square_meters,
    x_extension.ST_SRID(coord_5179) AS coord_5179_srid,
    address, detail, urls, raw_refs,
    legal_dong_code, sido_code, sigungu_code,
    marker_icon, marker_color, status,
    parent_feature_id, sibling_group_id,
    created_at, updated_at, deleted_at,
    row_revision
"""

_GET_FEATURE_SQL: Final[str] = f"""
SELECT {_FEATURE_ROW_COLUMNS_SQL}
FROM feature.features
WHERE feature_id = :feature_id
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = f"""
SELECT {_FEATURE_ROW_COLUMNS_SQL}
FROM feature.features
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
"""

# 공개 단건/batch — ADR-067 단일 공개 projection(``feature.public_features``,
# alembic 0059)만 조회한다. 술어(status='active' AND deleted_at IS NULL)는
# VIEW 한 곳에만 정의되어 있고 여기서는 재구현하지 않는다.
_GET_PUBLIC_FEATURE_SQL: Final[str] = f"""
SELECT {_FEATURE_ROW_COLUMNS_SQL}
FROM feature.public_features
WHERE feature_id = :feature_id
"""

_GET_PUBLIC_FEATURES_BY_IDS_SQL: Final[str] = f"""
SELECT {_FEATURE_ROW_COLUMNS_SQL}
FROM feature.public_features
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
"""

_FEATURE_LOAD_STATE_SQL: Final[str] = """
SELECT
    f.feature_id IS NOT NULL AS feature_exists,
    COALESCE(
        f.status = 'inactive'
        AND COALESCE(f.data_origin, 'provider') <> 'user_request'
        AND NOT EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS fo
            WHERE fo.feature_id = f.feature_id
              AND fo.field_path = 'status'
              AND fo.status = 'active'
              AND fo.prevent_provider_reactivation
        ),
        false
    ) AS needs_provider_reactivation
FROM (VALUES (CAST(:feature_id AS text))) AS wanted(feature_id)
LEFT JOIN feature.features AS f
  ON f.feature_id = wanted.feature_id
"""


def _notice_lineage_sql(alias: str) -> str:
    return f"""
    CASE
      WHEN {alias}.provider = 'python-krex-api'
       AND {alias}.dataset_key = 'krex_traffic_notices'
       AND {alias}.source_entity_type = 'traffic_notice'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(lower(btrim({alias}.raw_data->>'occurred_date')), ''),
            NULLIF(lower(btrim({alias}.raw_data->>'occurred_time')), ''),
            NULLIF(lower(btrim({alias}.raw_data->>'route_no')), ''),
            NULLIF(lower(btrim({alias}.raw_data->>'direction')), ''),
            NULLIF(lower(btrim({alias}.raw_data->>'point_name')), ''),
            NULLIF(lower(btrim({alias}.raw_data->>'incident_type_code')), '')
          ),
          ''
        ),
        {alias}.source_entity_id
      )
      WHEN {alias}.provider = 'python-kma-api'
       AND {alias}.dataset_key = 'kma_weather_alerts'
       AND {alias}.source_entity_type = 'weather_alert'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(btrim({alias}.raw_data->>'region_code'), ''),
            NULLIF(
              btrim(
                COALESCE(
                  {alias}.raw_data->>'phenomenon',
                  {alias}.raw_data->>'alert_type'
                )
              ),
              ''
            )
          ),
          ''
        ),
        {alias}.source_entity_id
      )
      ELSE {alias}.source_entity_id
    END
    """


def _canonical_notice_feature_sql(feature_alias: str, source_alias: str) -> str:
    """현재 사건 단위 identity로 만든 notice feature인지 판정하는 SQL.

    KREX/KMA의 현 identity는 모두 ``bjd_code=None``과 고정 category를 사용하고,
    ``source_natural_key``는 ``_notice_lineage_sql`` 결과와 같다. 따라서 같은
    source record가 구/신 feature 양쪽에 연결된 identity 이행 동률에서도 현재
    ``make_feature_id`` 결과를 정확히 알아낼 수 있다. 그 외 provider는 근거가
    없으므로 ``false``로 두고 stable ``feature_id`` tie-break에 맡긴다.
    """
    return f"""
    CASE
      WHEN (
        ({source_alias}.provider = 'python-krex-api'
         AND {source_alias}.dataset_key = 'krex_traffic_notices'
         AND {source_alias}.source_entity_type = 'traffic_notice')
        OR
        ({source_alias}.provider = 'python-kma-api'
         AND {source_alias}.dataset_key = 'kma_weather_alerts'
         AND {source_alias}.source_entity_type = 'weather_alert')
      )
      THEN {feature_alias}.feature_id = (
        'f_global_n_' || left(
          encode(
            x_extension.digest(
              'global|notice|99000000|'
              || {source_alias}.provider || ':' || {source_alias}.dataset_key || '|'
              || {_notice_lineage_sql(source_alias)} || '|',
              'sha1'
            ),
            'hex'
          ),
          16
        )
      )
      ELSE false
    END
    """


# 종료된 notice 숨김 — valid_end_time이 지난 notice는 지도/검색에서 제외한다
# (§9 "활성 notice만 표시", #632). KREX feed 소멸 reconcile·KMA 해제가 채운
# valid_end_time이 이 필터로 즉시 반영된다.
#
# 방어적 cast (report §2 D-9-7 (+ T-VN-06 row)): detail->>'valid_end_time'은
# free-form jsonb라 오염된 한 행(빈 문자열·garbage·잘못된 timezone)이 직접
# CAST에서 예외를 던지면 이 함수를 공유하는 **모든** 공개 read가 500이 된다.
# #745가 이 함수를 curated/curation/collection 표면의 notice 감산 정본으로
# 만들었으므로, 여기 한 곳의 가드가 그 표면들까지 동시에 보호한다.
# pg_input_is_valid(PG16+, 배포/테스트 이미지 모두 16 고정)로 가드하고,
# 파싱 불가면 fail-closed로 그 notice를 제외한다(ELSE false — 노출 아님).
# JSON null/키 부재는 기존 의미 유지(종료시각 없음 = 활성). CASE는 THEN이
# WHEN 참일 때만 평가되는 것을 보장한다(AND/OR는 평가 순서 미보장).
# typed notice 재설계·관측(카운터)은 T-VN-37 소유.
def _ended_notice_hidden_sql(feature_alias: str) -> str:
    """종료된 notice를 숨기는 SQL fragment를 feature alias에 맞춰 만든다."""

    return f"""
  AND (
    {feature_alias}.kind <> 'notice'
    OR ({feature_alias}.detail ->> 'valid_end_time') IS NULL
    OR CASE
         WHEN pg_input_is_valid({feature_alias}.detail ->> 'valid_end_time', 'timestamptz')
         THEN CAST({feature_alias}.detail ->> 'valid_end_time' AS timestamptz) > now()
         ELSE false
       END
  )
"""


# 한 feature에 여러 계보의 primary entity가 연결될 수 있다. 각 계보의 실제 최신 row를
# 고른 뒤 **모든 계보에서 밀린 feature만** 숨긴다. 한 계보라도 winner면 feature 전체를
# 보존하며, current primary source가 없는 notice도 기존처럼 표시한다.
def _latest_notice_only_sql(feature_alias: str) -> str:
    """구버전 notice를 숨기는 SQL fragment를 feature alias에 맞춰 만든다."""

    return f"""
  AND (
    {feature_alias}.kind <> 'notice'
    OR NOT EXISTS (
      SELECT 1
      FROM (
        SELECT DISTINCT ON (
            cur_sr.provider,
            cur_sr.dataset_key,
            cur_sr.source_entity_type,
            {_notice_lineage_sql("cur_sr")}
        )
            cur_sr.provider,
            cur_sr.dataset_key,
            cur_sr.source_entity_type,
            {_notice_lineage_sql("cur_sr")} AS lineage_key,
            COALESCE(
                cur_sr.last_seen_at, cur_sr.imported_at, cur_sr.fetched_at
            ) AS seen_at,
            cur_sr.source_record_key,
            {_canonical_notice_feature_sql(feature_alias, "cur_sr")} AS canonical_identity
        FROM provider_sync.source_links AS cur_sl
        JOIN provider_sync.source_entities AS cur_se
          ON cur_se.source_entity_key = cur_sl.source_entity_key
        JOIN provider_sync.source_records AS cur_sr
          ON cur_sr.source_record_key = cur_se.current_source_record_key
        WHERE cur_sl.feature_id = {feature_alias}.feature_id
          AND cur_sl.is_primary_source
        ORDER BY
            cur_sr.provider,
            cur_sr.dataset_key,
            cur_sr.source_entity_type,
            {_notice_lineage_sql("cur_sr")},
            COALESCE(
                cur_sr.last_seen_at, cur_sr.imported_at, cur_sr.fetched_at
            ) DESC,
            cur_sr.source_record_key DESC
      ) AS current_notice
      LEFT JOIN LATERAL (
        SELECT 1 AS better_exists
        FROM provider_sync.source_entities AS other_se
        JOIN provider_sync.source_records AS other_sr
          ON other_sr.source_record_key = other_se.current_source_record_key
         AND {_notice_lineage_sql("other_sr")} = current_notice.lineage_key
        JOIN provider_sync.source_links AS other_sl
          ON other_sl.source_entity_key = other_se.source_entity_key
        JOIN feature.features AS other_f
          ON other_f.feature_id = other_sl.feature_id
        WHERE other_se.provider = current_notice.provider
          AND other_se.dataset_key = current_notice.dataset_key
          AND other_se.source_entity_type = current_notice.source_entity_type
          AND other_sl.is_primary_source
          AND other_f.feature_id <> {feature_alias}.feature_id
          AND other_f.kind = 'notice'
          AND other_f.deleted_at IS NULL
          AND (
            COALESCE(
                other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
            ) > current_notice.seen_at
            OR (
              COALESCE(
                  other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
              ) = current_notice.seen_at
              AND other_sr.source_record_key > current_notice.source_record_key
            )
            OR (
              COALESCE(
                  other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
              ) = current_notice.seen_at
              AND other_sr.source_record_key = current_notice.source_record_key
              AND (
                (
                  {_canonical_notice_feature_sql("other_f", "other_sr")}
                  AND NOT current_notice.canonical_identity
                )
                OR (
                  {_canonical_notice_feature_sql("other_f", "other_sr")}
                    = current_notice.canonical_identity
                  AND other_f.feature_id < {feature_alias}.feature_id
                )
              )
            )
          )
        LIMIT 1
      ) AS better ON true
      HAVING bool_and(better.better_exists IS NOT NULL)
    )
  )
"""

# 사용자 활성 조회용 결합 필터 — 계보별 latest만 + 종료 notice 숨김(#632).
# 지도 bbox뿐 아니라 cluster/search/nearby/area/count에도 같은 술어를 적용해야
# legacy/current feature가 동시에 남은 기간에 목록·집계별 노출 결과가 어긋나지 않는다.
# infra raw 단건/다건과 admin 감사 목록만 과거 계보/종료 notice 추적을 위해 제외한다.
#
# 공개 여부 자체는 ADR-067 ``feature.public_features`` projection이 정본이고, 이
# 필터는 그 위에 겹치는 notice 전용 **추가 감산**이다(노출 확대 불가). 경쟁자 후보
# 판정(``_LATEST_NOTICE_ONLY_SQL``의 ``other_f.deleted_at IS NULL``)은 reconcile
# 의미론(T-VN-06/37 소유)이라 T-VN-04에서 view로 바꾸지 않았다 — 비공개 신규
# feature가 구 feature를 계속 밀어내는 현행 동작 유지.
def public_active_notice_filter_sql(feature_alias: str) -> str:
    """모든 공개 read가 공유하는 active/latest notice 감산 SQL을 반환한다.

    호출자는 신뢰된 정적 SQL alias만 넘긴다. 공개 여부의 기본 집합은
    ``feature.public_features``이고, 이 fragment는 종료·구버전 notice만 추가로
    제외한다.
    """

    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    return _ended_notice_hidden_sql(feature_alias) + _latest_notice_only_sql(feature_alias)


_PUBLIC_ACTIVE_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql("f")


# service batch는 공개 payload와 base-table 상태 판정을 한 snapshot에서 읽는다.
# ``feature.public_features``가 payload의 유일한 출처이고 base row는 state와
# ``row_revision``만 제공한다(ADR-067). notice 종료/계보 감산도 다른 공개 read와
# 같은 fragment를 사용한다.
_SERVICE_FEATURE_BATCH_SQL: Final[str] = f"""
WITH requested AS (
    SELECT
        item.feature_id,
        item.known_row_revision,
        item.ordinality
    FROM unnest(
        CAST(:feature_ids AS text[]),
        CAST(:known_row_revisions AS bigint[])
    ) WITH ORDINALITY AS item(feature_id, known_row_revision, ordinality)
)
SELECT
    requested.feature_id,
    CASE
      WHEN base.feature_id IS NULL THEN 'missing'
      WHEN base.deleted_at IS NOT NULL OR base.status = 'deleted' THEN 'retired'
      WHEN visible.feature_id IS NULL THEN 'suppressed'
      WHEN requested.known_row_revision = visible.row_revision THEN 'unchanged'
      ELSE 'found'
    END AS state,
    base.row_revision,
    visible.kind,
    visible.name,
    visible.category,
    x_extension.ST_X(visible.coord) AS lon,
    x_extension.ST_Y(visible.coord) AS lat,
    visible.address,
    visible.marker_icon,
    visible.marker_color
FROM requested
LEFT JOIN feature.features AS base
  ON base.feature_id = requested.feature_id
LEFT JOIN feature.public_features AS visible
  ON visible.feature_id = requested.feature_id
{public_active_notice_filter_sql("visible")}
ORDER BY requested.ordinality
"""


# ─── in-bounds 후보 술어 단일화 (F-8 / ADR-073 D-9-3·D-9-4) ──────────────────
# bbox in-bounds 조회는 세 변형(경량 items / geometry items / cluster rollup)이
# 있고, 이전에는 각자 WHERE 절에 같은 attribute 필터를 복제했으며 include_geometry
# 만 route/area geom을 후보에 넣어 **결과집합**이 달라졌다(EXPLAIN 재현 2220→2221행).
# 아래 두 fragment로 후보 술어를 한 곳에 정의해 재사용한다:
#   - ``_bbox_candidate_predicate_sql`` : items(경량/geometry) 공유 공간 후보 술어.
#   - ``_bbox_attribute_filter_sql``    : kind/category/provider 공통 속성 필터(3변형 공유).


def _bbox_envelope_sql() -> str:
    """4326 입력 bbox envelope (ADR-012 — 술어에 ST_Transform 없음)."""
    return """x_extension.ST_MakeEnvelope(
        CAST(:min_lon AS double precision), CAST(:min_lat AS double precision),
        CAST(:max_lon AS double precision), CAST(:max_lat AS double precision), 4326)"""


def _bbox_candidate_predicate_sql(feature_alias: str) -> str:
    """items in-bounds 단일 후보 술어 (F-8 / ADR-073 D-9-3).

    ``include_geometry`` 유무와 **무관하게 동일한** 후보 집합을 만든다 — 플래그는
    응답 직렬화(SELECT projection)만 제어하고 membership은 바꾸지 않는다.

    - **point/legacy 좌표(``coord``)**: ``&&`` MBR 술어는 점-envelope 교차에서 이미
      정확하다(점의 MBR = 점 자신). route/area에 geometry가 있으면 이 arm을 타지 않고
      아래 exact geometry arm만 사용하며, geometry가 없는 legacy route/area만 coord로
      fallback한다.
    - **route/area ``geom``**: ``&&`` MBR prefilter만으로는 false positive가 실재하므로
      (F-8) partial GiST(``idx_features_geom_gist``)를 ``&&``로 구동한 뒤 exact
      ``ST_Intersects``를 덧대 실제 envelope 교차만 남긴다. ``ST_Transform``을 술어에
      넣지 않는다(ADR-012). 두 arm은 각각 index 가능해 planner가 BitmapOr로 결합한다
      (features base-table seq scan 없음 — T-VN-21 tier-1 gate).
    """
    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    env = _bbox_envelope_sql()
    return f"""(
    (
      {feature_alias}.coord IS NOT NULL
      AND (
        {feature_alias}.kind NOT IN ('route', 'area')
        OR {feature_alias}.geom IS NULL
      )
      AND {feature_alias}.coord OPERATOR(x_extension.&&) {env}
    )
    OR (
      {feature_alias}.kind IN ('route', 'area')
      AND {feature_alias}.geom IS NOT NULL
      AND {feature_alias}.geom OPERATOR(x_extension.&&) {env}
      AND x_extension.ST_Intersects({feature_alias}.geom, {env})
    )
  )"""


def _bbox_attribute_filter_sql(feature_alias: str) -> str:
    """kind/category/provider 공통 속성 필터 (items 경량/geometry + cluster 공유).

    세 변형이 같은 SQL을 재사용해 이중 복제를 제거한다(ADR-073 D-9-4). NULL 배열이면
    술어가 단락(short-circuit)돼 인덱스 기반 조회에 영향이 없다. provider 필터는
    primary source(``provider_sync.is_primary_source``) 기준 EXISTS다.
    """
    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    return f"""
  AND (CAST(:kinds AS text[]) IS NULL OR {feature_alias}.kind = ANY(CAST(:kinds AS text[])))
  AND (
    CAST(:categories AS text[]) IS NULL
    OR {feature_alias}.category = ANY(CAST(:categories AS text[]))
  )
  AND (
    CAST(:providers AS text[]) IS NULL
    OR EXISTS (
      SELECT 1
      FROM provider_sync.source_links AS pl
      JOIN provider_sync.source_entities AS pr
        ON pr.source_entity_key = pl.source_entity_key
      WHERE pl.feature_id = {feature_alias}.feature_id
        AND pl.is_primary_source
        AND pr.provider = ANY(CAST(:providers AS text[]))
    )
  )
"""


_PUBLIC_ACTIVE_NOTICE_IDS_SQL: Final[str] = f"""
SELECT f.feature_id
FROM feature.public_features AS f
WHERE f.feature_id = ANY(CAST(:feature_ids AS text[]))
  AND f.kind = 'notice'
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
"""

# primary source 1건의 on-demand 상세 — source_record raw_data(원본 provider payload)
# + 연결 feature core. Step D(on-demand detail) 등 단건 조회용. ``source_entity_id``로
# 매칭(provider/dataset/entity_type 한정). primary link 1개만(LIMIT 1).
#
# 공개 표면(`/v1/mois/licenses/...`)이 소비하므로 ADR-067 공개 projection
# (``feature.public_features``)만 조인한다 — 과거에는 ``deleted_at IS NULL``만
# 요구하고 ``ORDER BY (status='active') DESC``로 active를 우선했을 뿐이라, active
# 후보가 없으면 draft/inactive feature가 그대로 노출됐다(F-1). caller(mois_detail)는
# 원래 active-only를 기대한다(test_mois_loader가 status='active' 단언).
#
# 정합성(issue #509 Problem B): 같은 안정 식별자에 구/신 feature가 둘 다 primary
# link로 남을 수 있다(re-key 정리 직전/직후). view가 non-active를 제거한 뒤에도
# active 동률이 남을 수 있으므로 결정적 ``ORDER BY``(imported_at 최신 → feature_id)
# 후 LIMIT 1로 deterministic하게 반환한다.
_GET_PRIMARY_SOURCE_DETAIL_SQL: Final[str] = """
SELECT
    f.feature_id, f.kind, f.name, f.category, f.status,
    x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
    f.address, f.detail,
    sr.source_record_key, sr.provider, sr.dataset_key,
    sr.source_entity_type, sr.source_entity_id,
    sr.raw_name, sr.raw_address, sr.raw_data,
    sr.fetched_at, sr.imported_at
FROM provider_sync.source_entities AS se
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = se.current_source_record_key
JOIN provider_sync.source_links AS sl
  ON sl.source_entity_key = se.source_entity_key
JOIN feature.public_features AS f
  ON f.feature_id = sl.feature_id
WHERE sr.provider = :provider
  AND sr.dataset_key = :dataset_key
  AND sr.source_entity_type = :source_entity_type
  AND sr.source_entity_id = :source_entity_id
  AND sl.is_primary_source
ORDER BY sr.imported_at DESC NULLS LAST, f.feature_id
LIMIT 1
"""

# bbox 조회 — ADR-012: 입력 bbox는 4326, GIST(coord) 인덱스 사용. 공개 여부는
# ADR-067 단일 projection(``feature.public_features``)이 결정한다 — 이 파일의
# 공개 read SQL은 술어를 재구현하지 않는다. view 술어가 ``deleted_at IS NULL``을
# 함의하므로 partial GiST 인덱스는 그대로 사용된다.
# kinds 필터는 NULL이면 전체 (asyncpg ARRAY 바인딩). 경량 표현(좌표 + 표시 메타).
_FEATURES_IN_BBOX_SQL: Final[str] = f"""
SELECT
    f.feature_id, f.kind, f.name, f.category,
    x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
    f.marker_icon, f.marker_color, f.status,
    ps.price_summary,
    ws.weather_summary
FROM feature.public_features AS f
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'provider', provider,
            'price_domain', price_domain,
            'product_key', product_key,
            'product_name', product_name,
            'source_product_key', source_product_key,
            'source_product_name', source_product_name,
            'value_number', value_number,
            'unit', unit,
            'observed_at', observed_at
        )
        ORDER BY
            CASE product_key
              WHEN 'gasoline' THEN 10
              WHEN 'diesel' THEN 20
              WHEN 'premium_gasoline' THEN 30
              WHEN 'lpg' THEN 40
              ELSE 100
            END,
            product_name NULLS LAST,
            product_key,
            provider,
            price_domain
    ) AS price_summary
    FROM (
        SELECT DISTINCT ON (provider, price_domain, product_key)
            provider, price_domain, product_key, product_name,
            source_product_key, source_product_name,
            value_number, unit, observed_at
        FROM feature.feature_price_values AS pv
        WHERE pv.feature_id = f.feature_id
          -- 신선도 지평선: 로테이션 주기 밖 관측은 현재가 마커에서 제외(이력 보존).
          AND (
            CAST(:price_stale_hide_days AS integer) IS NULL
            OR pv.observed_at >= now()
                 - make_interval(days => CAST(:price_stale_hide_days AS integer))
          )
        ORDER BY provider DESC, price_domain DESC, product_key DESC, observed_at DESC
    ) AS latest_price
) AS ps ON f.kind = 'price'
LEFT JOIN LATERAL (
    SELECT jsonb_build_object(
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
        'observed_at', observed_at
    ) AS weather_summary
    FROM feature.feature_weather_values AS w
    WHERE w.feature_id = f.feature_id
      AND w.metric_key IN (
        'T1H', 'TMP', 'TMN', 'TMX', 'POP', 'SKY', 'REH', 'PTY', 'PCP',
        'PM10', 'PM2_5', 'CAI', 'O3', 'NO2', 'SO2', 'CO'
      )
    ORDER BY
        CASE w.metric_key
          WHEN 'T1H' THEN 10
          WHEN 'TMP' THEN 20
          WHEN 'TMN' THEN 30
          WHEN 'TMX' THEN 40
          WHEN 'POP' THEN 50
          WHEN 'SKY' THEN 60
          WHEN 'REH' THEN 70
          WHEN 'PTY' THEN 80
          WHEN 'PCP' THEN 90
          WHEN 'PM10' THEN 110
          WHEN 'PM2_5' THEN 120
          WHEN 'CAI' THEN 130
          WHEN 'O3' THEN 140
          WHEN 'NO2' THEN 150
          WHEN 'SO2' THEN 160
          WHEN 'CO' THEN 170
          ELSE 100
        END,
        CASE w.forecast_style
          WHEN 'observed' THEN 10
          WHEN 'nowcast' THEN 20
          WHEN 'ultra_short' THEN 30
          WHEN 'short' THEN 40
          WHEN 'mid' THEN 50
          ELSE 100
        END,
        CASE
          WHEN COALESCE(w.valid_at, w.observed_at, w.issued_at) >= now() THEN 0
          ELSE 1
        END,
        abs(
          extract(
            epoch FROM (COALESCE(w.valid_at, w.observed_at, w.issued_at) - now())
          )
        ) ASC NULLS LAST,
        COALESCE(w.observed_at, w.valid_at, w.issued_at) DESC NULLS LAST
    LIMIT 1
) AS ws ON f.kind = 'weather'
WHERE {_bbox_candidate_predicate_sql("f")}
{_bbox_attribute_filter_sql("f")}
  AND (
    CAST(:cursor_feature_id AS text) IS NULL
    OR f.feature_id > CAST(:cursor_feature_id AS text)
  )
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
ORDER BY f.feature_id ASC
LIMIT :limit
"""

_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL: Final[str] = f"""
SELECT
    f.feature_id, f.kind, f.name, f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.marker_icon, f.marker_color, f.status,
    ps.price_summary,
    ws.weather_summary,
    CASE
      WHEN f.kind = 'route' AND f.geom IS NOT NULL
      THEN CAST(x_extension.ST_AsGeoJSON(x_extension.ST_Simplify(f.geom, 0.0001), 6) AS jsonb)
      WHEN f.kind = 'area' AND f.geom IS NOT NULL
      THEN CAST(
        x_extension.ST_AsGeoJSON(x_extension.ST_SimplifyPreserveTopology(f.geom, 0.0001), 6)
        AS jsonb
      )
      ELSE NULL
    END AS geometry,
    CASE
      WHEN f.kind = 'area' AND f.geom IS NOT NULL
      THEN x_extension.ST_Area(CAST(f.geom AS x_extension.geography))
      ELSE NULL
    END AS area_square_meters
FROM feature.public_features AS f
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'provider', provider,
            'price_domain', price_domain,
            'product_key', product_key,
            'product_name', product_name,
            'source_product_key', source_product_key,
            'source_product_name', source_product_name,
            'value_number', value_number,
            'unit', unit,
            'observed_at', observed_at
        )
        ORDER BY
            CASE product_key
              WHEN 'gasoline' THEN 10
              WHEN 'diesel' THEN 20
              WHEN 'premium_gasoline' THEN 30
              WHEN 'lpg' THEN 40
              ELSE 100
            END,
            product_name NULLS LAST,
            product_key,
            provider,
            price_domain
    ) AS price_summary
    FROM (
        SELECT DISTINCT ON (provider, price_domain, product_key)
            provider, price_domain, product_key, product_name,
            source_product_key, source_product_name,
            value_number, unit, observed_at
        FROM feature.feature_price_values AS pv
        WHERE pv.feature_id = f.feature_id
          -- 신선도 지평선: 로테이션 주기 밖 관측은 현재가 마커에서 제외(이력 보존).
          AND (
            CAST(:price_stale_hide_days AS integer) IS NULL
            OR pv.observed_at >= now()
                 - make_interval(days => CAST(:price_stale_hide_days AS integer))
          )
        ORDER BY provider DESC, price_domain DESC, product_key DESC, observed_at DESC
    ) AS latest_price
) AS ps ON f.kind = 'price'
LEFT JOIN LATERAL (
    SELECT jsonb_build_object(
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
        'observed_at', observed_at
    ) AS weather_summary
    FROM feature.feature_weather_values AS w
    WHERE w.feature_id = f.feature_id
      AND w.metric_key IN (
        'T1H', 'TMP', 'TMN', 'TMX', 'POP', 'SKY', 'REH', 'PTY', 'PCP',
        'PM10', 'PM2_5', 'CAI', 'O3', 'NO2', 'SO2', 'CO'
      )
    ORDER BY
        CASE w.metric_key
          WHEN 'T1H' THEN 10
          WHEN 'TMP' THEN 20
          WHEN 'TMN' THEN 30
          WHEN 'TMX' THEN 40
          WHEN 'POP' THEN 50
          WHEN 'SKY' THEN 60
          WHEN 'REH' THEN 70
          WHEN 'PTY' THEN 80
          WHEN 'PCP' THEN 90
          WHEN 'PM10' THEN 110
          WHEN 'PM2_5' THEN 120
          WHEN 'CAI' THEN 130
          WHEN 'O3' THEN 140
          WHEN 'NO2' THEN 150
          WHEN 'SO2' THEN 160
          WHEN 'CO' THEN 170
          ELSE 100
        END,
        CASE w.forecast_style
          WHEN 'observed' THEN 10
          WHEN 'nowcast' THEN 20
          WHEN 'ultra_short' THEN 30
          WHEN 'short' THEN 40
          WHEN 'mid' THEN 50
          ELSE 100
        END,
        CASE
          WHEN COALESCE(w.valid_at, w.observed_at, w.issued_at) >= now() THEN 0
          ELSE 1
        END,
        abs(
          extract(
            epoch FROM (COALESCE(w.valid_at, w.observed_at, w.issued_at) - now())
          )
        ) ASC NULLS LAST,
        COALESCE(w.observed_at, w.valid_at, w.issued_at) DESC NULLS LAST
    LIMIT 1
) AS ws ON f.kind = 'weather'
WHERE {_bbox_candidate_predicate_sql("f")}
{_bbox_attribute_filter_sql("f")}
  AND (
    CAST(:cursor_feature_id AS text) IS NULL
    OR f.feature_id > CAST(:cursor_feature_id AS text)
  )
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
ORDER BY f.feature_id ASC
LIMIT :limit
"""


# bbox 내 region rollup 클러스터링 (T-213c). cluster_unit → 고정 canonical 행정코드
# 컬럼(allowlist — SQL injection 불가). 경계를 가로지르는 geometry도 선택 단위의 저장
# 코드 하나에만 귀속한다. 공간 교차 지점별로 여러 cluster에 복제하지 않으므로 cluster
# feature_count 합계가 code 보강된 items 후보 수와 일치한다. items와 같은 exact 후보
# 술어를 사용해 mode 전환이 공간 후보 universe를 바꾸지 않게 한다
# (ADR-073 D-9-2·D-9-4). point/legacy 후보의
# 대표 좌표는 coord, geometry 후보의 대표 좌표는 bbox와 실제 교차한 부분 위의 점이다.
# 따라서 centroid가 bbox 밖인 route/area도 count와 지도 마커에 빠지지 않으며 반환
# marker는 bbox 내부에 있다. ``ST_Transform``은 술어에 넣지 않는다(ADR-012).
def _cluster_bbox_sql(code_col: str) -> str:
    env = _bbox_envelope_sql()
    return f"""
WITH bbox_candidates AS (
  SELECT
      f.{code_col} AS cluster_key,
      CASE
        WHEN f.kind IN ('route', 'area') AND f.geom IS NOT NULL
          THEN x_extension.ST_PointOnSurface(
            x_extension.ST_Intersection(f.geom, {env})
          )
        ELSE f.coord
      END AS marker_coord
  FROM feature.public_features AS f
  WHERE f.{code_col} IS NOT NULL
    AND {_bbox_candidate_predicate_sql("f")}
{_bbox_attribute_filter_sql("f")}
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
)
SELECT
    cluster_key,
    count(*) AS feature_count,
    avg(x_extension.ST_X(marker_coord)) AS lon,
    avg(x_extension.ST_Y(marker_coord)) AS lat
FROM bbox_candidates
WHERE marker_coord IS NOT NULL
GROUP BY cluster_key
ORDER BY feature_count DESC, cluster_key
LIMIT :limit
"""


# cluster_unit → 행정코드 컬럼 (allowlist).
_CLUSTER_CODE_COL: Final[dict[str, str]] = {
    "sido": "sido_code",
    "sigungu": "sigungu_code",
    "eupmyeondong": "legal_dong_code",
}
_CLUSTER_BBOX_SQL_BY_UNIT: Final[dict[str, str]] = {
    unit: _cluster_bbox_sql(col) for unit, col in _CLUSTER_CODE_COL.items()
}


async def cluster_features_in_bbox(
    session: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    cluster_unit: str,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    providers: Sequence[str] | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """bbox 내 feature를 행정구역(``cluster_unit``) 단위로 rollup한다 (T-213c).

    ``cluster_unit`` ∈ {sido, sigungu, eupmyeondong} → 각 region code별
    ``{cluster_key, feature_count, lon, lat}``(lon/lat=region 내 feature 평균 좌표).
    point/legacy coord와 route/area geometry의 exact 후보 술어는 items 조회와 같다.
    geometry 후보의 대표 마커는 bbox 교차 부분 위의 점을 사용하되, cluster 귀속은
    geometry가 걸친 공간이 아니라 저장된 canonical 행정코드 하나로 결정한다. 따라서
    경계를 가로지르는 feature도 선택 단위에서 정확히 한 번만 집계된다. region code가
    없는 feature는 rollup할 수 없어 제외된다(주소 미보강 등).
    """
    if cluster_unit not in _CLUSTER_BBOX_SQL_BY_UNIT:
        raise ValueError("cluster_unit must be one of sido, sigungu, eupmyeondong")
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("invalid bbox")
    rows = (
        (
            await session.execute(
                text(_CLUSTER_BBOX_SQL_BY_UNIT[cluster_unit]),
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "kinds": _normalized_filter(kinds),
                    "categories": _normalized_filter(categories),
                    "providers": _normalized_filter(providers),
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "cluster_key": str(row["cluster_key"]),
            "feature_count": int(row["feature_count"]),
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
        }
        for row in rows
    ]


_FEATURE_SEARCH_CTE_SQL: Final[str] = f"""
WITH candidates AS (
    SELECT
        f.feature_id,
        f.kind,
        f.name,
        f.category,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        f.marker_icon,
        f.marker_color,
        f.status,
        CASE
            WHEN CAST(:q AS text) IS NULL THEN NULL
            ELSE x_extension.similarity(f.name, CAST(:q AS text))
        END AS score
    FROM feature.public_features AS f
    WHERE (
        CAST(:q AS text) IS NULL
        OR f.name OPERATOR(x_extension.%) CAST(:q AS text)
      )
      AND (
        CAST(:bbox_enabled AS boolean) IS FALSE
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
      AND (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
      )
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
)
"""

_FEATURE_SEARCH_SCORE_CTE_SQL: Final[str] = f"""
WITH name_candidates AS MATERIALIZED (
    SELECT
        f.feature_id,
        f.kind,
        f.name,
        f.category,
        f.coord,
        f.marker_icon,
        f.marker_color,
        f.status,
        x_extension.similarity(f.name, CAST(:q AS text)) AS score
    FROM feature.public_features AS f
    WHERE f.name OPERATOR(x_extension.%) CAST(:q AS text)
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
),
candidates AS (
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
        score
    FROM name_candidates
    WHERE (
        CAST(:bbox_enabled AS boolean) IS FALSE
        OR (
          coord IS NOT NULL
          AND coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
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
    _FEATURE_SEARCH_SCORE_CTE_SQL
    + """
SELECT candidates.*, score::text AS score_cursor
FROM candidates
WHERE (
    CAST(:cursor_score AS text) IS NULL
    OR (-score, feature_id) > (
        -- score 컬럼은 x_extension.similarity(...) = real(float4). cursor_score는
        -- score::text 왕복값이므로 real로 캐스팅해야 경계값이 정확히 일치하고, 동점 시
        -- feature_id tiebreak로 넘어가 커서 행 자신이 다음 페이지에 재등장(같은 feature_id
        -- 중복)하는 float8 정밀도 버그를 막는다.
        -CAST(:cursor_score AS real),
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

_FEATURE_SEARCH_COUNT_SQL: Final[str] = (
    _FEATURE_SEARCH_CTE_SQL
    + """
SELECT count(*) AS total_count
FROM candidates
"""
)

_FEATURE_SEARCH_SCORE_COUNT_SQL: Final[str] = (
    _FEATURE_SEARCH_SCORE_CTE_SQL
    + """
SELECT count(*) AS total_count
FROM candidates
"""
)

_NEARBY_TARGET_CTE_SQL: Final[str] = f"""
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
    JOIN feature.public_features AS f
      ON f.coord IS NOT NULL
     AND f.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(f.coord_5179, t.coord_5179, t.radius_m)
    LEFT JOIN LATERAL (
        SELECT se.provider, se.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = se.current_source_record_key
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
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
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

# 좌표 기준 nearby (T-213b) — target CTE 대신 입력 좌표(4326)를 5179로 **CTE에서
# 1회만** 변환해 상수로 굳히고(ADR-012), 술어는 STORED ``coord_5179``에 직접
# ``ST_DWithin``한다. candidates 컬럼/cursor/정렬은 by-target nearby와 동일하므로
# ``_nearby_row``/``_nearby_cursor_params``/``_encode_nearby_cursor``를 그대로 재사용한다.
_NEARBY_COORD_CTE_SQL: Final[str] = f"""
WITH origin AS (
    SELECT
        x_extension.ST_Transform(
            x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(
                    CAST(:lon AS double precision), CAST(:lat AS double precision)
                ),
                4326
            ),
            5179
        ) AS pt_5179,
        CAST(:radius_m AS double precision) AS radius_m
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
        x_extension.ST_Distance(f.coord_5179, o.pt_5179)::double precision
            AS distance_m,
        ps.provider AS primary_provider,
        ps.dataset_key AS primary_dataset_key,
        f.updated_at AS last_updated_at
    FROM origin AS o
    JOIN feature.public_features AS f
      ON f.coord IS NOT NULL
     AND f.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(f.coord_5179, o.pt_5179, o.radius_m)
    LEFT JOIN LATERAL (
        SELECT se.provider, se.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = se.current_source_record_key
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
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
)
"""

_NEARBY_COORD_DISTANCE_SQL: Final[str] = (
    _NEARBY_COORD_CTE_SQL
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

_NEARBY_COORD_NAME_SQL: Final[str] = (
    _NEARBY_COORD_CTE_SQL
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

_NEARBY_COORD_UPDATED_SQL: Final[str] = (
    _NEARBY_COORD_CTE_SQL
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

_NEARBY_COORD_SQL_BY_SORT: Final[dict[str, str]] = {
    "distance": _NEARBY_COORD_DISTANCE_SQL,
    "name": _NEARBY_COORD_NAME_SQL,
    "last_updated_at": _NEARBY_COORD_UPDATED_SQL,
}

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
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND f.feature_id IN (
    SELECT sl.feature_id
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_entities AS sr
      ON sr.source_entity_key = sl.source_entity_key
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
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND f.feature_id IN (
    SELECT sl.feature_id
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_entities AS sr
      ON sr.source_entity_key = sl.source_entity_key
    WHERE sl.is_primary_source
      AND sr.provider = :provider
      AND sr.dataset_key = :dataset_key
      AND sr.source_entity_type = :source_entity_type
      AND sr.source_entity_id = ANY(CAST(:keys AS text[]))
  )
RETURNING f.feature_id
"""


# 과거 보정 — kind='area'인데 경계 geometry가 없는 provider feature만 inactive 전환.
# 새 place row와 같은 source_entity_id를 공유할 수 있으므로 entity-id 기반 폐업 메서드를
# 재사용하지 않고 feature kind/geom 조건을 직접 건다.
_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL: Final[str] = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.kind = 'area'
  AND f.geom IS NULL
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND f.feature_id IN (
    SELECT sl.feature_id
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_entities AS sr
      ON sr.source_entity_key = sl.source_entity_key
    WHERE sl.is_primary_source
      AND sr.provider = :provider
      AND sr.dataset_key = :dataset_key
      AND sr.source_entity_type = :source_entity_type
  )
RETURNING f.feature_id
"""


@dataclass(frozen=True)
class FeatureLoadResult:
    """``load_bundles`` 적재 결과 카운트 (docs/architecture/backend-package.md §1.3).

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
            source_records_inserted=(self.source_records_inserted + other.source_records_inserted),
            source_links_inserted=(self.source_links_inserted + other.source_links_inserted),
            source_links_updated=(self.source_links_updated + other.source_links_updated),
        )


FeatureBatchItemState = Literal[
    "found",
    "retired",
    "suppressed",
    "missing",
    "unchanged",
]


@dataclass(frozen=True)
class FeatureBatchItemRow:
    """service batch의 상태 판정과 공개 ``trip_card`` projection."""

    feature_id: str
    state: FeatureBatchItemState
    row_revision: int | None
    trip_card: dict[str, Any] | None


@dataclass(frozen=True)
class AirQualityLoadResult:
    """``client.load_air_quality`` 결과 — 측정소 feature + 측정값 적재 카운트(T-RV-55d).

    - ``stations`` — 측정소 weather feature ``FeatureLoadResult``.
    - ``weather_values`` — ``feature_weather_values``에 upsert된 air_quality 값 수.
    """

    stations: FeatureLoadResult
    weather_values: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {
            "stations_total": self.stations.bundles_total,
            "stations_features_inserted": self.stations.features_inserted,
            "stations_features_updated": self.stations.features_updated,
            "weather_values_loaded": self.weather_values,
        }


@dataclass(frozen=True)
class EnrichmentLoadResult:
    """enrichment(``SourceRecord`` + ``SourceLink``) 적재 카운트.

    feature를 만들지 않는 2차 enrichment(visitkorea 등)용. ``load_bundles``의
    ``FeatureLoadResult``와 달리 feature 카운트가 없다.
    """

    enrichments_total: int = 0
    source_records_inserted: int = 0
    source_links_inserted: int = 0
    source_links_updated: int = 0

    def merge(self, other: EnrichmentLoadResult) -> EnrichmentLoadResult:
        return EnrichmentLoadResult(
            enrichments_total=self.enrichments_total + other.enrichments_total,
            source_records_inserted=(self.source_records_inserted + other.source_records_inserted),
            source_links_inserted=(self.source_links_inserted + other.source_links_inserted),
            source_links_updated=(self.source_links_updated + other.source_links_updated),
        )


async def load_source_record_links(
    session: AsyncSession,
    pairs: Iterable[tuple[SourceRecord, SourceLink]],
) -> EnrichmentLoadResult:
    """``(SourceRecord, SourceLink)`` 쌍을 적재한다(enrichment 등 — feature 미생성).

    각 쌍은 ``upsert_source_record`` → ``upsert_source_link`` 순. ``source_link``의
    ``feature_id`` FK가 **이미 존재**해야 한다(1차 source가 먼저 적재돼 있어야 함).
    commit/rollback은 호출자(`AsyncKorTravelMapClient.load_enrichment_links`) 책임.
    """
    result = EnrichmentLoadResult()
    for record, link in pairs:
        record_inserted = await upsert_source_record(session, record)
        link_inserted = await upsert_source_link(session, link)
        result = result.merge(
            EnrichmentLoadResult(
                enrichments_total=1,
                source_records_inserted=int(record_inserted),
                source_links_inserted=int(link_inserted),
                source_links_updated=int(not link_inserted),
            )
        )
    return result


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
        "detail": (feature.detail.model_dump_json() if feature.detail is not None else "{}"),
        "raw_refs": _dump_raw_refs(feature),
        "status": feature.status.value,
        "created_at": feature.created_at,
        "updated_at": feature.updated_at,
        "deleted_at": feature.deleted_at,
    }


def _feature_snapshot(feature: Feature) -> str:
    """``feature.feature_versions`` version 0 payload용 canonical JSON."""
    return json.dumps(feature.model_dump(mode="json"), ensure_ascii=False, default=str)


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
        "source_entity_key": _make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        ),
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


def _make_source_entity_key(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
) -> str:
    """Migration과 동일한 provider entity 결정키(``se_`` + SHA-256)."""

    raw = f"{provider}|{dataset_key}|{source_entity_type}|{source_entity_id}"
    return "se_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    inserted = bool(result.scalar_one())
    await session.execute(
        text(_UPSERT_PROVIDER_VERSION_SQL),
        {"feature_id": feature.feature_id, "payload": _feature_snapshot(feature)},
    )
    return inserted


@dataclass(frozen=True)
class _SourceRecordUpsertState:
    inserted: bool
    became_current: bool


async def _upsert_source_record_state(
    session: AsyncSession, record: SourceRecord
) -> _SourceRecordUpsertState:
    params = _source_record_params(record)
    previous_current = (
        await session.execute(text(_UPSERT_SOURCE_ENTITY_SQL), params)
    ).scalar_one()
    result = await session.execute(text(_UPSERT_SOURCE_RECORD_SQL), params)
    inserted = bool(result.scalar_one())
    current = (
        await session.execute(text(_REFRESH_SOURCE_ENTITY_CURRENT_SQL), params)
    ).scalar_one()
    return _SourceRecordUpsertState(
        inserted=inserted,
        became_current=(
            current == record.source_record_key and previous_current != current
        ),
    )


async def upsert_source_record(session: AsyncSession, record: SourceRecord) -> bool:
    """``provider_sync.source_records`` insert. 신규면 ``True``, 이미 있으면 ``False``.

    payload_hash가 UNIQUE 구성요소라 payload 변경은 새 row로 이력을 남긴다.
    동일 key 재적재는 raw payload를 갱신하지 않고 ``last_seen_at``만 갱신한다.
    """
    return (await _upsert_source_record_state(session, record)).inserted


@dataclass(frozen=True)
class _FeatureLoadState:
    exists: bool
    needs_provider_reactivation: bool


async def _feature_load_state(
    session: AsyncSession, feature_id: str
) -> _FeatureLoadState:
    row = (
        await session.execute(
            text(_FEATURE_LOAD_STATE_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    return _FeatureLoadState(
        exists=bool(row["feature_exists"]),
        needs_provider_reactivation=bool(row["needs_provider_reactivation"]),
    )


async def upsert_source_link(session: AsyncSession, link: SourceLink) -> bool:
    """``provider_sync.source_links`` upsert. 신규 INSERT면 ``True``, 갱신이면 ``False``."""
    result = await session.execute(text(_UPSERT_SOURCE_LINK_SQL), _source_link_params(link))
    return bool(result.scalar_one())


async def load_bundle(session: AsyncSession, bundle: FeatureBundle) -> FeatureLoadResult:
    """``FeatureBundle`` 하나를 적재 (source_record → feature → source_link 순).

    동일 source_record_key 재수집이면 원문 내용은 이미 같은 payload라는 뜻이므로
    feature 본문/version은 갱신하지 않고 ``source_records.last_seen_at``만 갱신한다.
    단, source_record만 있고 feature가 없는 비정상 상태는 생성하고, provider가
    다시 보낸 active feature가 과거 정리/비활성화로 ``inactive`` 상태라면 복구한다.
    ``user_request`` feature와 provider 재활성화 방지 override는 복구하지 않는다.
    commit은 호출자 책임.
    """
    record_state = await _upsert_source_record_state(
        session, bundle.source_record
    )
    record_inserted = record_state.inserted
    feature_inserted = False
    feature_updated = False
    feature_missing = False
    needs_provider_reactivation = False
    if not record_inserted:
        feature_state = await _feature_load_state(session, bundle.feature.feature_id)
        feature_missing = not feature_state.exists
        needs_provider_reactivation = (
            feature_state.needs_provider_reactivation
            and bundle.feature.status.value == "active"
            and bundle.feature.deleted_at is None
        )
    if (
        record_state.became_current
        or feature_missing
        or needs_provider_reactivation
    ):
        feature_inserted = await upsert_feature(session, bundle.feature)
        feature_updated = not feature_inserted
    link_inserted = await upsert_source_link(session, bundle.source_link)
    return FeatureLoadResult(
        bundles_total=1,
        features_inserted=int(feature_inserted),
        features_updated=int(feature_updated),
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


async def inactivate_geometryless_area_features_by_source(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
) -> int:
    """provider source에 연결된 ``area`` 중 경계 geometry가 없는 feature를 비활성화.

    기존에 좌표만 있는 record를 ``Feature.kind='area'``로 적재했던 provider를
    재정렬할 때 쓰는 one-way 보정이다. 같은 source entity가 새 ``place`` feature로
    재적재될 수 있으므로 source_entity_id 집합 기반 전환은 쓰지 않는다.
    commit은 호출자 책임.
    """
    result = await session.execute(
        text(_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
        },
    )
    return len(result.fetchall())


# ── notice 라이프사이클 (#632 — 사건 단위 identity + 중복 정리) ─────────────

_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL: Final[str] = """
SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('kortravelmap:notice-snapshot-reconcile', 0)
)
"""

_GET_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
SELECT mode, applied_at, state_fingerprint
FROM provider_sync.notice_lifecycle_scopes
WHERE provider = :provider
  AND dataset_key = :dataset_key
  AND source_entity_type = :source_entity_type
"""

_INSERT_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
INSERT INTO provider_sync.notice_lifecycle_scopes (
    provider, dataset_key, source_entity_type,
    mode, applied_at, state_fingerprint
) VALUES (
    :provider, :dataset_key, :source_entity_type,
    :mode, CAST(:applied_at AS timestamptz), :state_fingerprint
)
"""

_UPDATE_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
UPDATE provider_sync.notice_lifecycle_scopes
SET applied_at = CAST(:applied_at AS timestamptz),
    state_fingerprint = :state_fingerprint
WHERE provider = :provider
  AND dataset_key = :dataset_key
  AND source_entity_type = :source_entity_type
"""

_UPSERT_NOTICE_EVENT_SCOPE_SQL: Final[str] = """
INSERT INTO provider_sync.notice_lifecycle_scopes (
    provider, dataset_key, source_entity_type,
    mode, applied_at, state_fingerprint
) VALUES (
    :provider, :dataset_key, :source_entity_type,
    'event', CAST(:applied_at AS timestamptz), :state_fingerprint
)
ON CONFLICT (provider, dataset_key, source_entity_type)
DO UPDATE SET
    applied_at = GREATEST(
        provider_sync.notice_lifecycle_scopes.applied_at,
        EXCLUDED.applied_at
    ),
    state_fingerprint = CASE
        WHEN EXCLUDED.applied_at
             >= provider_sync.notice_lifecycle_scopes.applied_at
        THEN EXCLUDED.state_fingerprint
        ELSE provider_sync.notice_lifecycle_scopes.state_fingerprint
    END
"""


def _sync_notice_lineage_states_sql() -> str:
    """알려진 scope 계보의 present 전이만 changed_at과 함께 저장한다."""
    return f"""
WITH known_lineages AS (
    SELECT DISTINCT {_notice_lineage_sql("sr")} AS lineage_key
    FROM provider_sync.source_entities AS se
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = se.current_source_record_key
    WHERE se.provider = :provider
      AND se.dataset_key = :dataset_key
      AND se.source_entity_type = :source_entity_type
    UNION
    SELECT lineage_key
    FROM provider_sync.notice_lineage_states
    WHERE provider = :provider
      AND dataset_key = :dataset_key
      AND source_entity_type = :source_entity_type
    UNION
    SELECT unnest(CAST(:active_keys AS text[]))
), desired AS (
    SELECT
        lineage_key,
        lineage_key = ANY(CAST(:active_keys AS text[])) AS present,
        CAST(NULL AS timestamptz) AS valid_until
    FROM known_lineages
)
INSERT INTO provider_sync.notice_lineage_states (
    provider, dataset_key, source_entity_type,
    lineage_key, present, changed_at, valid_until
)
SELECT
    :provider, :dataset_key, :source_entity_type,
    lineage_key, present, CAST(:closed_at AS timestamptz), valid_until
FROM desired
ON CONFLICT (provider, dataset_key, source_entity_type, lineage_key)
DO UPDATE SET
    present = EXCLUDED.present,
    changed_at = EXCLUDED.changed_at,
    valid_until = EXCLUDED.valid_until
WHERE provider_sync.notice_lineage_states.present IS DISTINCT FROM EXCLUDED.present
   OR provider_sync.notice_lineage_states.valid_until
      IS DISTINCT FROM EXCLUDED.valid_until
"""


def _notice_snapshot_fingerprint(active_lineage_keys: Sequence[str]) -> str:
    canonical = json.dumps(
        sorted(set(active_lineage_keys)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "snapshot:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _advance_notice_snapshot_scope(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    mode: str,
    checked_at: datetime,
    fingerprint: str,
) -> bool:
    """scope watermark를 전진한다. exact replay면 ``False``를 반환한다."""
    params = {
        "provider": provider,
        "dataset_key": dataset_key,
        "source_entity_type": source_entity_type,
        "mode": mode,
        "applied_at": checked_at,
        "state_fingerprint": fingerprint,
    }
    current = (
        await session.execute(text(_GET_NOTICE_SNAPSHOT_SCOPE_SQL), params)
    ).mappings().one_or_none()
    if current is not None:
        if current["mode"] != mode:
            raise ValueError("notice lifecycle scope mode conflict")
        current_checked_at = current["applied_at"]
        if checked_at < current_checked_at:
            raise ValueError("stale authoritative notice snapshot watermark")
        if checked_at == current_checked_at:
            if fingerprint != current["state_fingerprint"]:
                raise ValueError(
                    "conflicting authoritative notice snapshot at equal watermark"
                )
            return False
        await session.execute(text(_UPDATE_NOTICE_SNAPSHOT_SCOPE_SQL), params)
    else:
        await session.execute(text(_INSERT_NOTICE_SNAPSHOT_SCOPE_SQL), params)
    return True


async def _persist_notice_snapshot_state(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_lineage_keys: Sequence[str],
    checked_at: datetime,
) -> None:
    """scope watermark를 검증·전진하고 lineage 상태 전이만 영속화한다."""
    fingerprint = _notice_snapshot_fingerprint(active_lineage_keys)
    params = {
        "provider": provider,
        "dataset_key": dataset_key,
        "source_entity_type": source_entity_type,
        "active_keys": list(active_lineage_keys),
        "closed_at": checked_at,
    }
    await _advance_notice_snapshot_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        mode="snapshot",
        checked_at=checked_at,
        fingerprint=fingerprint,
    )
    # exact replay도 이 동기화를 실행한다. 이전 버전의 부분 반영이나 load 뒤
    # 처음 알려진 lineage 누락을 같은 snapshot 재시도로 self-heal한다.
    await session.execute(text(_sync_notice_lineage_states_sql()), params)


_NOTICE_LINEAGE_EVENT_CONFLICT_SQL: Final[str] = """
WITH incoming AS (
    SELECT lineage_key, present, changed_at, valid_until
    FROM jsonb_to_recordset(CAST(:lineage_events AS jsonb)) AS event(
        lineage_key text,
        present boolean,
        changed_at timestamptz,
        valid_until timestamptz
    )
)
SELECT EXISTS (
    SELECT 1
    FROM incoming
    JOIN provider_sync.notice_lineage_states AS state
      ON state.provider = :provider
     AND state.dataset_key = :dataset_key
     AND state.source_entity_type = :source_entity_type
     AND state.lineage_key = incoming.lineage_key
    WHERE state.changed_at = incoming.changed_at
      AND (
          state.present IS DISTINCT FROM incoming.present
          OR state.valid_until IS DISTINCT FROM incoming.valid_until
      )
)
"""

_UPSERT_NOTICE_LINEAGE_EVENTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT lineage_key, present, changed_at, valid_until
    FROM jsonb_to_recordset(CAST(:lineage_events AS jsonb)) AS event(
        lineage_key text,
        present boolean,
        changed_at timestamptz,
        valid_until timestamptz
    )
)
INSERT INTO provider_sync.notice_lineage_states (
    provider, dataset_key, source_entity_type,
    lineage_key, present, changed_at, valid_until
)
SELECT
    :provider, :dataset_key, :source_entity_type,
    lineage_key, present, changed_at, valid_until
FROM incoming
ON CONFLICT (provider, dataset_key, source_entity_type, lineage_key)
DO UPDATE SET
    present = EXCLUDED.present,
    changed_at = EXCLUDED.changed_at,
    valid_until = EXCLUDED.valid_until
WHERE provider_sync.notice_lineage_states.changed_at < EXCLUDED.changed_at
"""

_ACCEPTED_PRESENT_NOTICE_EVENTS_SQL: Final[str] = """
WITH incoming AS (
    SELECT lineage_key, present, changed_at, valid_until
    FROM jsonb_to_recordset(CAST(:lineage_events AS jsonb)) AS event(
        lineage_key text,
        present boolean,
        changed_at timestamptz,
        valid_until timestamptz
    )
)
SELECT incoming.lineage_key
FROM incoming
JOIN provider_sync.notice_lineage_states AS state
  ON state.provider = :provider
 AND state.dataset_key = :dataset_key
 AND state.source_entity_type = :source_entity_type
 AND state.lineage_key = incoming.lineage_key
WHERE incoming.present
  AND state.present
  AND state.changed_at = incoming.changed_at
  AND state.valid_until IS NOT DISTINCT FROM incoming.valid_until
"""


def _notice_lineage_events_fingerprint(
    lineage_events: Mapping[str, tuple[bool, datetime, datetime | None]],
) -> str:
    canonical_events = [
        [
            lineage_key,
            present,
            changed_at.astimezone(UTC).isoformat(),
            valid_until.astimezone(UTC).isoformat()
            if valid_until is not None
            else None,
        ]
        for lineage_key, (present, changed_at, valid_until) in sorted(
            lineage_events.items()
        )
    ]
    canonical = json.dumps(
        canonical_events,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "events:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _persist_notice_lineage_events(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    lineage_events: Mapping[str, tuple[bool, datetime, datetime | None]],
    observed_at: datetime,
) -> frozenset[str]:
    """계보별 최신 event를 저장하고 load 가능한 current-present key를 반환한다."""
    fingerprint = _notice_lineage_events_fingerprint(lineage_events)
    scope_params = {
        "provider": provider,
        "dataset_key": dataset_key,
        "source_entity_type": source_entity_type,
        "applied_at": observed_at,
        "state_fingerprint": fingerprint,
    }
    current_scope = (
        await session.execute(text(_GET_NOTICE_SNAPSHOT_SCOPE_SQL), scope_params)
    ).mappings().one_or_none()
    if current_scope is not None and current_scope["mode"] != "event":
        raise ValueError("notice lifecycle scope mode conflict")
    await session.execute(text(_UPSERT_NOTICE_EVENT_SCOPE_SQL), scope_params)
    if not lineage_events:
        return frozenset()
    payload = [
        {
            "lineage_key": lineage_key,
            "present": present,
            "changed_at": changed_at.isoformat(),
            "valid_until": (
                valid_until.isoformat() if valid_until is not None else None
            ),
        }
        for lineage_key, (present, changed_at, valid_until) in sorted(
            lineage_events.items()
        )
    ]
    params = {
        "provider": provider,
        "dataset_key": dataset_key,
        "source_entity_type": source_entity_type,
        "lineage_events": json.dumps(payload, ensure_ascii=False),
    }
    conflict = bool(
        (
            await session.execute(
                text(_NOTICE_LINEAGE_EVENT_CONFLICT_SQL),
                params,
            )
        ).scalar_one()
    )
    if conflict:
        raise ValueError("conflicting notice lineage event at equal event time")
    await session.execute(text(_UPSERT_NOTICE_LINEAGE_EVENTS_SQL), params)
    accepted = await session.execute(
        text(_ACCEPTED_PRESENT_NOTICE_EVENTS_SQL),
        params,
    )
    return frozenset(str(row.lineage_key) for row in accepted)


def _supersede_stale_notice_sql(close_missing: bool) -> str:
    """notice 정리 SQL 2종 — 계보별 latest 아닌 feature soft-delete(+snapshot 동기화).

    ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``(read 필터)과 동일 계보/최신 판정을
    write 시점에 set 기반으로 적용한다. ``close_missing=True``면 soft-delete 대신
    현재 feed에 없는 latest 계보를 닫고, 다시 나타난 latest 계보는 이전
    ``valid_end_time``을 지워 활성 상태로 복구한다. feature·계보별 후보는
    ``seen_at``/``source_record_key``를 따로 집계하지 않고 실제 최신 row 하나를
    선택해 read와 winner가 어긋나지 않게 한다. 호출 scope에서 밀린 feature도
    다른 provider/dataset의 primary 계보 winner라면 feature 전체를 삭제하지 않고,
    그 계보로 열린 공유 feature를 현재 scope의 snapshot 부재로 닫지 않는다. 호출
    scope 자체의 winner는 ``ranked``에서 이미 계산하므로 cross-scope 보호 CTE에서
    다시 전수 비교하지 않는다.
    """
    candidate_lifecycle = (
        """
      AND (
        f.deleted_at IS NULL
        OR f.status = 'inactive'
      )
"""
        if close_missing
        else "      AND f.deleted_at IS NULL\n"
    )
    lineage_cte = f"""
WITH lineage_candidates AS (
    SELECT
        f.feature_id,
        {_notice_lineage_sql("sr")} AS lineage_key,
        COALESCE(sr.last_seen_at, sr.imported_at, sr.fetched_at) AS seen_at,
        sr.source_record_key AS tiebreak,
        {_canonical_notice_feature_sql("f", "sr")} AS canonical_identity,
        lineage_state.present AS snapshot_present,
        lineage_state.changed_at AS snapshot_changed_at,
        lineage_state.valid_until AS snapshot_valid_until
    FROM feature.features AS f
    JOIN provider_sync.source_links AS sl
      ON sl.feature_id = f.feature_id
     AND sl.is_primary_source
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = se.current_source_record_key
    LEFT JOIN provider_sync.notice_lineage_states AS lineage_state
      ON lineage_state.provider = sr.provider
     AND lineage_state.dataset_key = sr.dataset_key
     AND lineage_state.source_entity_type = sr.source_entity_type
     AND lineage_state.lineage_key = {_notice_lineage_sql("sr")}
    WHERE f.kind = 'notice'
      AND COALESCE(f.data_origin, 'provider') <> 'user_request'
      AND sr.provider = :provider
      AND sr.dataset_key = :dataset_key
      AND sr.source_entity_type = :source_entity_type
{candidate_lifecycle}
),
lineage AS (
    SELECT DISTINCT ON (feature_id, lineage_key)
        feature_id,
        lineage_key,
        seen_at,
        tiebreak,
        canonical_identity,
        snapshot_present,
        snapshot_changed_at,
        snapshot_valid_until
    FROM lineage_candidates
    ORDER BY feature_id, lineage_key, seen_at DESC, tiebreak DESC
),
ranked AS (
    SELECT
        feature_id,
        lineage_key,
        snapshot_present,
        snapshot_changed_at,
        snapshot_valid_until,
        row_number() OVER (
            PARTITION BY lineage_key
            ORDER BY
                seen_at DESC,
                tiebreak DESC,
                canonical_identity DESC,
                feature_id ASC
        ) AS rn
    FROM lineage
),
scoped_feature_ids AS (
    SELECT DISTINCT feature_id
    FROM ranked
),
out_of_scope_feature_lineages AS (
    SELECT DISTINCT ON (
        f.feature_id,
        sr.provider,
        sr.dataset_key,
        sr.source_entity_type,
        {_notice_lineage_sql("sr")}
    )
        f.feature_id,
        sr.provider,
        sr.dataset_key,
        sr.source_entity_type,
        {_notice_lineage_sql("sr")} AS lineage_key,
        COALESCE(sr.last_seen_at, sr.imported_at, sr.fetched_at) AS seen_at,
        sr.source_record_key AS tiebreak,
        {_canonical_notice_feature_sql("f", "sr")} AS canonical_identity,
        lineage_state.present AS snapshot_present,
        lineage_state.changed_at AS snapshot_changed_at,
        lineage_state.valid_until AS snapshot_valid_until
    FROM scoped_feature_ids AS scoped
    JOIN feature.features AS f
      ON f.feature_id = scoped.feature_id
    JOIN provider_sync.source_links AS sl
      ON sl.feature_id = f.feature_id
     AND sl.is_primary_source
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = se.current_source_record_key
    LEFT JOIN provider_sync.notice_lineage_states AS lineage_state
      ON lineage_state.provider = sr.provider
     AND lineage_state.dataset_key = sr.dataset_key
     AND lineage_state.source_entity_type = sr.source_entity_type
     AND lineage_state.lineage_key = {_notice_lineage_sql("sr")}
    WHERE f.kind = 'notice'
      AND (
        sr.provider <> :provider
        OR sr.dataset_key <> :dataset_key
        OR sr.source_entity_type <> :source_entity_type
      )
    ORDER BY
        f.feature_id,
        sr.provider,
        sr.dataset_key,
        sr.source_entity_type,
        {_notice_lineage_sql("sr")},
        COALESCE(sr.last_seen_at, sr.imported_at, sr.fetched_at) DESC,
        sr.source_record_key DESC
),
global_feature_wins AS (
    SELECT
        current_notice.feature_id,
        bool_or(better.better_exists IS NULL) AS wins_any_lineage,
        bool_or(
            better.better_exists IS NULL
            AND NOT (
                current_notice.provider = :provider
                AND current_notice.dataset_key = :dataset_key
                AND current_notice.source_entity_type = :source_entity_type
            )
        ) AS wins_out_of_scope_lineage,
        bool_or(
            better.better_exists IS NULL
            AND NOT (
                current_notice.provider = :provider
                AND current_notice.dataset_key = :dataset_key
                AND current_notice.source_entity_type = :source_entity_type
            )
            AND current_notice.snapshot_present IS TRUE
        ) AS has_present_out_of_scope_winning_lineage,
        bool_or(
            better.better_exists IS NULL
            AND NOT (
                current_notice.provider = :provider
                AND current_notice.dataset_key = :dataset_key
                AND current_notice.source_entity_type = :source_entity_type
            )
            AND current_notice.snapshot_present IS TRUE
            AND current_notice.snapshot_valid_until IS NULL
        ) AS has_open_present_out_of_scope_winning_lineage,
        max(current_notice.snapshot_valid_until) FILTER (
            WHERE better.better_exists IS NULL
              AND NOT (
                  current_notice.provider = :provider
                  AND current_notice.dataset_key = :dataset_key
                  AND current_notice.source_entity_type = :source_entity_type
              )
              AND current_notice.snapshot_present IS TRUE
        ) AS max_present_valid_until_out_of_scope,
        bool_or(
            better.better_exists IS NULL
            AND NOT (
                current_notice.provider = :provider
                AND current_notice.dataset_key = :dataset_key
                AND current_notice.source_entity_type = :source_entity_type
            )
            AND current_notice.snapshot_present IS NULL
        ) AS has_unknown_out_of_scope_winning_lineage,
        max(current_notice.snapshot_changed_at) FILTER (
            WHERE better.better_exists IS NULL
              AND current_notice.snapshot_present IS FALSE
        ) AS last_inactive_winner_changed_at
    FROM out_of_scope_feature_lineages AS current_notice
    LEFT JOIN LATERAL (
        SELECT 1 AS better_exists
        FROM provider_sync.source_entities AS other_se
        JOIN provider_sync.source_records AS other_sr
          ON other_sr.source_record_key = other_se.current_source_record_key
         AND {_notice_lineage_sql("other_sr")} = current_notice.lineage_key
        JOIN provider_sync.source_links AS other_sl
          ON other_sl.source_entity_key = other_se.source_entity_key
        JOIN feature.features AS other_f
          ON other_f.feature_id = other_sl.feature_id
        WHERE other_se.provider = current_notice.provider
          AND other_se.dataset_key = current_notice.dataset_key
          AND other_se.source_entity_type = current_notice.source_entity_type
          AND other_sl.is_primary_source
          AND other_f.feature_id <> current_notice.feature_id
          AND other_f.kind = 'notice'
          AND other_f.deleted_at IS NULL
          AND (
            COALESCE(
                other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
            ) > current_notice.seen_at
            OR (
              COALESCE(
                  other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
              ) = current_notice.seen_at
              AND other_sr.source_record_key > current_notice.tiebreak
            )
            OR (
              COALESCE(
                  other_sr.last_seen_at, other_sr.imported_at, other_sr.fetched_at
              ) = current_notice.seen_at
              AND other_sr.source_record_key = current_notice.tiebreak
              AND (
                (
                  {_canonical_notice_feature_sql("other_f", "other_sr")}
                  AND NOT current_notice.canonical_identity
                )
                OR (
                  {_canonical_notice_feature_sql("other_f", "other_sr")}
                    = current_notice.canonical_identity
                  AND other_f.feature_id < current_notice.feature_id
                )
              )
            )
          )
        LIMIT 1
    ) AS better ON true
    GROUP BY current_notice.feature_id
)
"""
    if close_missing:
        return (
            lineage_cte
            + """
, feature_snapshot AS (
    SELECT
        feature_id,
        bool_or(rn = 1) AS wins_any_lineage,
        bool_or(
            rn = 1 AND snapshot_present IS TRUE
        ) AS has_present_winning_lineage,
        bool_or(
            rn = 1
            AND snapshot_present IS TRUE
            AND snapshot_valid_until IS NULL
        ) AS has_open_present_winning_lineage,
        max(snapshot_valid_until) FILTER (
            WHERE rn = 1 AND snapshot_present IS TRUE
        ) AS max_present_valid_until,
        bool_or(
            rn = 1 AND snapshot_present IS NULL
        ) AS has_unknown_winning_lineage,
        max(snapshot_changed_at) FILTER (
            WHERE rn = 1 AND snapshot_present IS FALSE
        ) AS inactive_changed_at
    FROM ranked
    GROUP BY feature_id
), feature_lifecycle AS (
    SELECT
        s.feature_id,
        (
            s.has_present_winning_lineage
            OR COALESCE(
                global_wins.has_present_out_of_scope_winning_lineage,
                false
            )
        ) AS has_present_winning_lineage,
        (
            s.has_open_present_winning_lineage
            OR COALESCE(
                global_wins.has_open_present_out_of_scope_winning_lineage,
                false
            )
        ) AS has_open_present_winning_lineage,
        (
            s.has_unknown_winning_lineage
            OR COALESCE(
                global_wins.has_unknown_out_of_scope_winning_lineage,
                false
            )
        ) AS has_unknown_winning_lineage,
        COALESCE(
            GREATEST(
                s.max_present_valid_until,
                global_wins.max_present_valid_until_out_of_scope
            ),
            s.max_present_valid_until,
            global_wins.max_present_valid_until_out_of_scope
        ) AS max_present_valid_until,
        COALESCE(
            GREATEST(
                global_wins.last_inactive_winner_changed_at,
                s.inactive_changed_at
            ),
            global_wins.last_inactive_winner_changed_at,
            s.inactive_changed_at,
            CAST(:closed_at AS timestamptz)
        ) AS inactive_changed_at
    FROM feature_snapshot AS s
    LEFT JOIN global_feature_wins AS global_wins
      ON global_wins.feature_id = s.feature_id
    WHERE s.wins_any_lineage
       OR COALESCE(global_wins.wins_out_of_scope_lineage, false)
), lifecycle_desired AS (
    SELECT
        f.feature_id,
        f.status AS old_status,
        f.deleted_at AS old_deleted_at,
        CAST(f.detail ->> 'valid_end_time' AS timestamptz) AS old_valid_end_time,
        lifecycle.has_present_winning_lineage,
        lifecycle.has_unknown_winning_lineage,
        CASE
          WHEN lifecycle.has_present_winning_lineage
           AND lifecycle.has_open_present_winning_lineage
          THEN NULL
          WHEN lifecycle.has_unknown_winning_lineage
          THEN CASE
            WHEN lifecycle.has_present_winning_lineage
            THEN CASE
              WHEN f.status = 'active'
               AND f.deleted_at IS NULL
               AND (
                   (f.detail ->> 'valid_end_time') IS NULL
                   OR CAST(f.detail ->> 'valid_end_time' AS timestamptz)
                      > CAST(:evaluated_at AS timestamptz)
               )
              THEN CASE
                WHEN (f.detail ->> 'valid_end_time') IS NULL
                THEN NULL
                ELSE GREATEST(
                    lifecycle.max_present_valid_until,
                    CAST(f.detail ->> 'valid_end_time' AS timestamptz)
                )
              END
              ELSE lifecycle.max_present_valid_until
            END
            ELSE CAST(f.detail ->> 'valid_end_time' AS timestamptz)
          END
          WHEN lifecycle.has_present_winning_lineage
          THEN lifecycle.max_present_valid_until
          ELSE lifecycle.inactive_changed_at
        END AS desired_valid_end_time,
        EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS fo
            WHERE fo.feature_id = f.feature_id
              AND fo.field_path = 'status'
              AND fo.status = 'active'
              AND fo.prevent_provider_reactivation
        ) AS reactivation_blocked
    FROM feature.features AS f
    JOIN feature_lifecycle AS lifecycle
      ON lifecycle.feature_id = f.feature_id
), lifecycle_targets AS (
    SELECT
        desired.*,
        (
            desired.has_present_winning_lineage
            AND NOT desired.reactivation_blocked
            AND (
                desired.desired_valid_end_time IS NULL
                OR desired.desired_valid_end_time
                   > CAST(:evaluated_at AS timestamptz)
            )
        ) AS should_activate,
        (
            desired.old_status = 'active'
            AND desired.old_deleted_at IS NULL
            AND (
                desired.old_valid_end_time IS NULL
                OR desired.old_valid_end_time
                   > CAST(:evaluated_at AS timestamptz)
            )
        ) AS was_visible
    FROM lifecycle_desired AS desired
), lifecycle_changes AS (
    SELECT
        target.*,
        (
            (
                target.should_activate
                OR (
                    target.old_status = 'active'
                    AND target.old_deleted_at IS NULL
                )
            )
            AND (
                target.desired_valid_end_time IS NULL
                OR target.desired_valid_end_time
                   > CAST(:evaluated_at AS timestamptz)
            )
        ) AS will_be_visible
    FROM lifecycle_targets AS target
)
UPDATE feature.features AS f
SET detail = jsonb_set(
        f.detail,
        '{valid_end_time}',
        CASE
          WHEN target.desired_valid_end_time IS NULL
          THEN 'null'::jsonb
          ELSE to_jsonb(
              CAST(target.desired_valid_end_time AS text)
          )
        END,
        true
    ),
    status = CASE
      WHEN target.should_activate
      THEN 'active'
      ELSE f.status
    END,
    deleted_at = CASE
      WHEN target.should_activate
      THEN NULL
      ELSE f.deleted_at
    END,
    updated_at = now()
FROM lifecycle_changes AS target
WHERE f.feature_id = target.feature_id
  AND (
      target.old_valid_end_time
        IS DISTINCT FROM target.desired_valid_end_time
      OR (
          target.should_activate
          AND (
              target.old_deleted_at IS NOT NULL
              OR target.old_status <> 'active'
          )
      )
  )
RETURNING
    f.feature_id,
    (NOT target.was_visible AND target.will_be_visible) AS reopened,
    (target.was_visible AND NOT target.will_be_visible) AS closed
"""
        )
    return (
        lineage_cte
        + """
, feature_rank AS (
    SELECT
        feature_id,
        bool_or(rn = 1) AS wins_any_lineage,
        bool_or(rn > 1) AS loses_any_lineage
    FROM ranked
    GROUP BY feature_id
)
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
FROM feature_rank AS r
LEFT JOIN global_feature_wins AS global_wins
  ON global_wins.feature_id = r.feature_id
WHERE f.feature_id = r.feature_id
  AND r.loses_any_lineage
  AND NOT r.wins_any_lineage
  AND NOT COALESCE(global_wins.wins_any_lineage, false)
  AND f.deleted_at IS NULL
RETURNING f.feature_id
"""
    )


@dataclass(frozen=True)
class NoticeReconcileResult:
    """notice 정리 결과 — 중복 제거 / 계보 소멸 닫기 / 재등장 복구 건수."""

    superseded: int = 0
    closed: int = 0
    reopened: int = 0


@dataclass(frozen=True)
class NoticeFeatureLoadResult:
    """notice bundle 원자 적재와 영속 lifecycle materialize 결과."""

    load: FeatureLoadResult
    reconcile: NoticeReconcileResult


async def load_authoritative_notice_snapshot(
    session: AsyncSession,
    *,
    bundles: Sequence[FeatureBundle],
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_lineage_keys: Collection[str],
    observed_at: datetime,
) -> NoticeFeatureLoadResult:
    """full snapshot 적재·state CAS·Feature lifecycle을 한 transaction에서 수행."""
    await session.execute(text(_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL))
    normalized_active_keys = sorted(set(active_lineage_keys))
    fingerprint = _notice_snapshot_fingerprint(normalized_active_keys)
    # scope CAS는 적재 전에 수행해 stale/conflicting snapshot이 Feature를
    # 건드리지 못하게 한다. lineage 동기화는 적재 뒤에 수행해야 이번 snapshot에
    # 처음 등장한 source lineage까지 known set에 포함된다.
    await _advance_notice_snapshot_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        mode="snapshot",
        checked_at=observed_at,
        fingerprint=fingerprint,
    )
    loaded = await load_bundles(session, bundles)
    await _persist_notice_snapshot_state(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        active_lineage_keys=normalized_active_keys,
        checked_at=observed_at,
    )
    reconciled = await _reconcile_persisted_notice_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        closed_at=observed_at,
    )
    return NoticeFeatureLoadResult(load=loaded, reconcile=reconciled)


async def load_notice_event_bundles(
    session: AsyncSession,
    *,
    bundles: Sequence[FeatureBundle],
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    lineage_events: Mapping[str, tuple[bool, datetime, datetime | None]],
    observed_at: datetime,
) -> NoticeFeatureLoadResult:
    """event notice 적재·member 전이·Feature lifecycle을 한 transaction에서 수행."""
    bundle_lineage_keys: list[str] = []
    seen_bundle_lineage_keys: set[str] = set()
    duplicate_lineage_keys: set[str] = set()
    for bundle in bundles:
        lineage_key = bundle.source_record.source_entity_id
        bundle_lineage_keys.append(lineage_key)
        if lineage_key in seen_bundle_lineage_keys:
            duplicate_lineage_keys.add(lineage_key)
        seen_bundle_lineage_keys.add(lineage_key)
    if duplicate_lineage_keys:
        raise ValueError(
            "notice event batch contains multiple bundles for one lineage: "
            + ", ".join(sorted(duplicate_lineage_keys))
        )
    invalid_bundle_lineage_keys = sorted(
        lineage_key
        for lineage_key in bundle_lineage_keys
        if lineage_key not in lineage_events
    )
    if invalid_bundle_lineage_keys:
        raise ValueError(
            "notice event bundle requires a matching lineage event: "
            + ", ".join(invalid_bundle_lineage_keys)
        )
    await session.execute(text(_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL))
    accepted_present = await _persist_notice_lineage_events(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events=lineage_events,
        observed_at=observed_at,
    )
    accepted_bundles = [
        bundle
        for bundle in bundles
        if bundle.source_record.source_entity_id in accepted_present
    ]
    materialized_at = datetime.now(UTC)
    active_bundles: list[FeatureBundle] = []
    expired_bundles: list[FeatureBundle] = []
    for bundle in accepted_bundles:
        valid_until = lineage_events[
            bundle.source_record.source_entity_id
        ][2]
        target = (
            active_bundles
            if valid_until is None or valid_until > materialized_at
            else expired_bundles
        )
        target.append(bundle)
    loaded = await load_bundles(session, active_bundles)
    # 만료된 rolling-window 발표도 SourceRecord 감사 이력은 남긴다. 다만 일반
    # bundle load의 provider reactivation을 거치면 soft-delete/purge된 Feature가
    # 과거 사건으로 되살아나므로 Feature/source_link는 만들거나 갱신하지 않는다.
    for bundle in expired_bundles:
        source_record_inserted = await upsert_source_record(
            session, bundle.source_record
        )
        loaded = loaded.merge(
            FeatureLoadResult(
                bundles_total=1,
                source_records_inserted=int(source_record_inserted),
            )
        )
    reconciled = await _reconcile_persisted_notice_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        closed_at=max(
            (changed_at for _, changed_at, _ in lineage_events.values()),
            default=observed_at,
        ),
        evaluated_at=materialized_at,
    )
    return NoticeFeatureLoadResult(load=loaded, reconcile=reconciled)


async def get_notice_snapshot_watermark(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
) -> datetime | None:
    """해당 authoritative notice scope의 최근 적용 watermark를 반환한다."""
    result = await session.execute(
        text(_GET_NOTICE_SNAPSHOT_SCOPE_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
        },
    )
    row = result.mappings().one_or_none()
    return None if row is None else row["applied_at"]


async def close_notice_features(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    closures: Mapping[str, datetime],
    announcements: Mapping[str, datetime] | None = None,
) -> int:
    """계보별 발표/해제를 영속화하고 공유 notice Feature lifecycle을 재계산한다.

    key는 모두 사건 ``lineage_key``다. 최신 announcement는 ``present=true``,
    lift는 ``present=false`` 전이이며, 같은 Feature의 다른 scope winner가
    present면 실제 close를 미룬다. commit은 호출자 책임.
    """
    lineage_events: dict[str, tuple[bool, datetime, datetime | None]] = {}
    for present, events in ((True, announcements or {}), (False, closures)):
        for lineage_key, changed_at in events.items():
            current = lineage_events.get(lineage_key)
            if current is None or changed_at > current[1]:
                lineage_events[lineage_key] = (present, changed_at, None)
            elif changed_at == current[1] and present != current[0]:
                raise ValueError("conflicting notice lineage event at equal event time")
    if not lineage_events:
        return 0
    await session.execute(text(_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL))
    await _persist_notice_lineage_events(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        lineage_events=lineage_events,
        observed_at=max(
            changed_at for _, changed_at, _ in lineage_events.values()
        ),
    )
    result = await _reconcile_persisted_notice_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        closed_at=max(
            changed_at for _, changed_at, _ in lineage_events.values()
        ),
    )
    return result.closed


async def supersede_stale_notice_features(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    active_lineage_keys: Collection[str] | None = None,
    closed_at: datetime | None = None,
) -> NoticeReconcileResult:
    """notice 중복/소멸 정리 — 적재 직후 호출하는 write-시점 reconciliation(#632).

    1. **중복 정리**: 같은 계보(``_notice_lineage_sql``)에 feature가 2개 이상이면
       latest(최근 확인 시각) 1개만 남기고 나머지를 soft-delete
       (``status='inactive'`` + ``deleted_at``, ADR-017). identity 스킴 변경으로
       재키잉된 구세대 feature가 신세대에 밀려나는 경로다.
    2. **snapshot 상태 동기화** (``active_lineage_keys``/``closed_at`` 제공 시):
       현재 feed에 없는 latest 계보는 ``valid_end_time=closed_at``으로 닫고,
       다시 나타난 latest 계보는 기존 ``valid_end_time``을 지운다. transient
       feed(KREX 실시간 돌발)의 소멸과 재등장을 모두 self-heal한다.

    commit은 호출자 책임.
    """
    snapshot_params: dict[str, object] | None = None
    if active_lineage_keys is not None and closed_at is not None:
        # snapshot 상태 갱신과 공유 Feature lifecycle 판정을 scope 간 직렬화한다.
        # transaction advisory lock이므로 caller commit/rollback까지 유지된다.
        await session.execute(text(_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL))
        normalized_active_keys = sorted(set(active_lineage_keys))
        snapshot_params = {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "active_keys": normalized_active_keys,
            "closed_at": closed_at,
        }
        await _persist_notice_snapshot_state(
            session,
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            active_lineage_keys=normalized_active_keys,
            checked_at=closed_at,
        )

    return await _reconcile_persisted_notice_scope(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        closed_at=closed_at if snapshot_params is not None else None,
    )


async def _reconcile_persisted_notice_scope(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    closed_at: datetime | None,
    evaluated_at: datetime | None = None,
) -> NoticeReconcileResult:
    """영속 lineage state로 scope의 dedup과 Feature lifecycle을 재계산한다."""
    lifecycle_evaluated_at = evaluated_at or datetime.now(UTC)
    result = await session.execute(
        text(_supersede_stale_notice_sql(close_missing=False)),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
        },
    )
    superseded = len(result.fetchall())
    closed = 0
    reopened = 0
    if closed_at is not None:
        result = await session.execute(
            text(_supersede_stale_notice_sql(close_missing=True)),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "closed_at": closed_at,
                "evaluated_at": lifecycle_evaluated_at,
            },
        )
        snapshot_updates = result.mappings().all()
        reopened = sum(bool(row["reopened"]) for row in snapshot_updates)
        closed = sum(bool(row["closed"]) for row in snapshot_updates)
        # soft-delete됐던 winner를 복구하면서 같은 계보의 legacy active feature와
        # 다시 공존할 수 있다. 복구가 실제 발생한 경우에만 한 번 더 정리해
        # transaction 밖으로 중복 active feature가 노출되지 않게 한다.
        if reopened:
            result = await session.execute(
                text(_supersede_stale_notice_sql(close_missing=False)),
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "source_entity_type": source_entity_type,
                },
            )
            superseded += len(result.fetchall())
    return NoticeReconcileResult(
        superseded=superseded,
        closed=closed,
        reopened=reopened,
    )


# 만료 notice purge (docs/etl/notice-feature-etl.md §9) — 종료일(없으면 발표일)
# +1년 지난 notice를 soft-delete. maintenance job에서 주기 실행(#632).
_PURGE_EXPIRED_NOTICES_SQL: Final[str] = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.kind = 'notice'
  AND f.deleted_at IS NULL
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND COALESCE(
        CAST(f.detail ->> 'valid_end_time' AS timestamptz),
        CAST(f.detail ->> 'valid_start_time' AS timestamptz)
      ) < now() - CAST(CAST(:retention AS text) AS interval)
RETURNING f.feature_id
"""


async def purge_expired_notices(session: AsyncSession, *, retention: str = "1 year") -> int:
    """보존 기간이 지난 notice를 soft-delete한다 (§9 보관 정책, #632).

    ``valid_end_time``(없으면 ``valid_start_time``) + ``retention`` 경과분.
    commit은 호출자 책임.
    """
    result = await session.execute(text(_PURGE_EXPIRED_NOTICES_SQL), {"retention": retention})
    return len(result.fetchall())


# JSONB 컬럼 — raw ``text()`` 쿼리는 driver에 따라 str(asyncpg)로 돌려줄 수 있어
# (typed 컬럼이 없으면 SQLAlchemy JSON 디시리얼라이저 미작동) 명시적으로 파싱한다.
_JSONB_COLUMNS: Final[tuple[str, ...]] = ("address", "detail", "urls", "raw_refs")


async def get_feature_row(session: AsyncSession, feature_id: str) -> dict[str, Any] | None:
    """``feature.features`` 단건 조회 (raw row dict). 없으면 ``None``.

    좌표는 ``lon``/``lat`` (4326)으로 분해해서 반환. ``coord_5179_srid``로
    generated column이 5179로 채워졌는지 확인 가능 (ADR-012). JSONB 컬럼
    (``address``/``detail``/``urls``/``raw_refs``)은 dict/list로 디시리얼라이즈해서
    반환 — driver(asyncpg)가 str로 돌려줘도 일관성 보장. DTO 매핑은 상위(client)
    책임 — 본 repo는 raw row만.
    """
    import json

    result = await session.execute(text(_GET_FEATURE_SQL), {"feature_id": feature_id})
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
    key 존재 여부를 비교해 missing 목록을 만든다. **admin/감사·내부 파이프라인용
    raw read** — soft-deleted/inactive feature도 status와 함께 반환한다(단건
    ``get_feature_row``와 동일 정책). 공개/서비스 read는 ADR-067 projection을 쓰는
    ``get_public_feature_rows_by_ids``를 사용한다.
    """
    normalized = _normalized_filter(feature_ids)
    if normalized is None:
        return {}
    result = await session.execute(text(_GET_FEATURES_BY_IDS_SQL), {"feature_ids": normalized})
    rows = result.mappings().all()
    return {str(row["feature_id"]): _deserialize_feature_row(row) for row in rows}


async def get_public_feature_row(
    session: AsyncSession, feature_id: str
) -> dict[str, Any] | None:
    """공개 feature 단건 조회 — ADR-067 ``feature.public_features`` projection.

    공개 API 단건 상세가 사용한다. 비공개(draft/broken/hidden/inactive/soft-deleted)
    row는 존재하지 않는 것으로 취급되어 ``None``을 반환한다 — 공개 술어는 VIEW
    (alembic 0059) 한 곳에만 정의되어 있고 여기서 재구현하지 않는다(F-1 재발 방지).
    row shape은 ``get_feature_row``와 동일하다. admin/감사용 raw read는 기존
    ``get_feature_row``를 그대로 사용한다.
    """
    result = await session.execute(text(_GET_PUBLIC_FEATURE_SQL), {"feature_id": feature_id})
    row = result.mappings().first()
    if row is None:
        return None
    return _deserialize_feature_row(row)


async def get_public_feature_rows_by_ids(
    session: AsyncSession, feature_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """여러 공개 feature 상세 row를 한 번에 조회한다 (ADR-067 projection).

    공개/service batch read가 사용한다. 반환 dict에 없는 ID는 "공개 row 없음"
    (미존재·retired·suppressed 구분 없이)이며, 상태 구분이 필요한 service batch
    item-state 계약은 T-VN-11에서 이 projection과 base 상태를 조합해 구현한다.
    row shape·순서 계약은 ``get_feature_rows_by_ids``와 동일하다.
    """
    normalized = _normalized_filter(feature_ids)
    if normalized is None:
        return {}
    result = await session.execute(
        text(_GET_PUBLIC_FEATURES_BY_IDS_SQL), {"feature_ids": normalized}
    )
    rows = result.mappings().all()
    return {str(row["feature_id"]): _deserialize_feature_row(row) for row in rows}


async def get_service_feature_batch_items(
    session: AsyncSession,
    items: Sequence[tuple[str, int | None]],
) -> tuple[FeatureBatchItemRow, ...]:
    """service batch 5-state item을 요청 순서대로 한 SQL snapshot에서 반환한다.

    base table은 존재/lifecycle 상태와 ``row_revision`` 판정에만 사용한다.
    ``trip_card``는 반드시 ``feature.public_features``에서만 만들며 retired,
    suppressed, missing item에는 비공개 payload를 싣지 않는다.
    """
    if not items:
        return ()

    result = await session.execute(
        text(_SERVICE_FEATURE_BATCH_SQL),
        {
            "feature_ids": [feature_id for feature_id, _revision in items],
            "known_row_revisions": [revision for _feature_id, revision in items],
        },
    )
    batch: list[FeatureBatchItemRow] = []
    valid_states: frozenset[str] = frozenset(
        {"found", "retired", "suppressed", "missing", "unchanged"}
    )
    for raw_row in result.mappings().all():
        row = _deserialize_feature_row(raw_row)
        state = str(row["state"])
        if state not in valid_states:
            raise RuntimeError(f"unexpected feature batch state: {state}")
        revision = int(row["row_revision"]) if row["row_revision"] is not None else None
        trip_card = None
        if state == "found":
            trip_card = {
                "feature_id": str(row["feature_id"]),
                "kind": str(row["kind"]),
                "name": str(row["name"]),
                "category": str(row["category"]),
                "lon": float(row["lon"]) if row["lon"] is not None else None,
                "lat": float(row["lat"]) if row["lat"] is not None else None,
                "address": row["address"],
                "marker_icon": row["marker_icon"],
                "marker_color": row["marker_color"],
            }
        batch.append(
            FeatureBatchItemRow(
                feature_id=str(row["feature_id"]),
                state=cast(FeatureBatchItemState, state),
                row_revision=revision,
                trip_card=trip_card,
            )
        )
    return tuple(batch)


async def public_active_notice_feature_ids(
    session: AsyncSession,
    feature_ids: Sequence[str],
) -> set[str]:
    """public 단건/batch에서 노출 가능한 active/latest notice ID만 반환한다.

    목록·검색·nearby와 같은 ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``을 공유해 종료된
    notice와 같은 계보의 구버전 feature가 ID 직접 조회로 다시 노출되지 않게 한다.
    일반 ``get_feature_row(s)``는 admin/감사용 raw read 계약을 유지한다.
    """
    normalized = _normalized_filter(feature_ids)
    if normalized is None:
        return set()
    result = await session.execute(
        text(_PUBLIC_ACTIVE_NOTICE_IDS_SQL),
        {"feature_ids": normalized},
    )
    return {str(row.feature_id) for row in result}


_LIST_ACTIVE_PLACE_COORDS_SQL: Final[str] = """
SELECT
    feature_id,
    x_extension.ST_X(coord) AS lon,
    x_extension.ST_Y(coord) AS lat
FROM feature.features
WHERE kind = 'place'
  AND deleted_at IS NULL
  AND coord IS NOT NULL
ORDER BY feature_id
"""


async def list_active_place_coords(
    session: AsyncSession,
) -> list[tuple[str, float, float]]:
    """active place feature의 ``(feature_id, lon, lat)`` 전량 (T-219a).

    KMA weather 격자→feature 매핑(옵션 B — `docs/etl/kma-weather-etl.md` §3)용.
    호출자(Dagster asset)가 좌표를 KMA 격자로 변환해 대상 격자와 일치하는
    feature에 weather 값을 적재한다. 좌표 3컬럼만 조회하므로 수만 행에도 가볍고,
    정렬은 결정적(feature_id).
    """
    rows = (await session.execute(text(_LIST_ACTIVE_PLACE_COORDS_SQL))).all()
    return [(str(row.feature_id), float(row.lon), float(row.lat)) for row in rows]


_LIST_PRIMARY_PLACE_LOCATOR_SQL: Final[str] = """
SELECT
    sr.source_entity_id,
    f.feature_id,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat
FROM feature.features f
JOIN provider_sync.source_links sl
  ON sl.feature_id = f.feature_id AND sl.is_primary_source
JOIN provider_sync.source_entities sr
  ON sr.source_entity_key = sl.source_entity_key
WHERE f.deleted_at IS NULL
  AND f.kind = 'place'
  AND f.coord IS NOT NULL
  AND sr.provider = :provider
  AND sr.dataset_key = :dataset_key
  AND sr.source_entity_type = :source_entity_type
ORDER BY f.feature_id
"""


async def list_primary_place_locator(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
) -> list[tuple[str, str, float, float]]:
    """primary place feature의 ``(source_entity_id, feature_id, lon, lat)`` 전량 (#547).

    primary source가 ``(provider, dataset_key, source_entity_type)``이고 좌표가 있는
    place feature를 ``source_entity_id``(provider 파생 자연키)와 함께 반환한다. 좌표가
    없는 row나 미존재 매핑은 제외된다.

    호출자(Dagster 휴게소 유가 asset)는 이 목록으로 휴게소명·노선·방향 자연키 →
    (place feature_id, 좌표) locator를 구성해, lon/lat가 없는 유가 record가 place
    좌표·``parent_feature_id``를 상속하게 한다 — geocoding 계층을 거치지 않고
    이미 적재된 place feature를 좌표 출처로 쓴다(레이어 규칙 준수).
    """
    rows = (
        await session.execute(
            text(_LIST_PRIMARY_PLACE_LOCATOR_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
            },
        )
    ).all()
    return [
        (str(row.source_entity_id), str(row.feature_id), float(row.lon), float(row.lat))
        for row in rows
    ]


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
JOIN provider_sync.source_entities sr
  ON sr.source_entity_key = sl.source_entity_key
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
        (
            await session.execute(
                text(_FIND_PLACE_NO_PHONE_SQL),
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "source_entity_type": source_entity_type,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        addr = data.get("address")
        if isinstance(addr, str):
            data["address"] = json.loads(addr)
        out.append(data)
    return out


async def set_feature_phones(session: AsyncSession, feature_id: str, phones: list[str]) -> bool:
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
    providers: Sequence[str] | None = None,
    limit: int = 1000,
    cursor: str | None = None,
    include_geometry: bool = False,
    price_stale_hide_days: int | None = DEFAULT_PRICE_STALE_HIDE_DAYS,
) -> list[dict[str, Any]]:
    """bbox 안의 feature 경량 표현 list (지도/목록용). 좌표는 ``lon``/``lat`` (4326).

    ADR-012 — 입력 bbox는 4326, ``coord``의 GIST 인덱스(``idx_features_coord_gist``)를
    사용하는 ``&&`` 연산. 공개 여부는 ADR-067 ``feature.public_features`` projection
    (``status='active' AND deleted_at IS NULL``)이 결정한다. ``kinds``가
    ``None``이면 전체 kind. DTO 매핑은 상위(client) 책임 — 본 repo는 raw row만.

    **``include_geometry``는 직렬화(serialization)만 제어한다** (F-8 / ADR-073 D-9-3):
    후보 술어는 두 변형이 **동일**하다 — point ``coord``가 bbox에 들거나 route/area
    ``geom``이 bbox와 exact ``ST_Intersects``하면 후보다(``include_geometry`` 무관).
    ``include_geometry=true``이면 그 후보 중 route/area의 GeoJSON geometry + 면적을
    응답 payload에 **추가로 직렬화**할 뿐, 반환되는 feature id 집합(membership)은
    바꾸지 않는다. ``providers``가 주어지면 primary source
    provider 기준(``provider_sync.source_links.is_primary_source``)으로 추가 필터한다
    — ``None``이면 술어가 단락(short-circuit)돼 인덱스 기반 bbox 조회에 영향이 없다.
    ``price_stale_hide_days``보다 오래된 price 관측은 ``price_summary``에서 제외한다
    (로테이션 주기 밖 옛 가격이 현재가 마커로 보이지 않게, ``None``이면 끔).
    """
    result = await session.execute(
        text(_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL if include_geometry else _FEATURES_IN_BBOX_SQL),
        {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
            "kinds": kinds,
            "categories": _normalized_filter(categories),
            "providers": _normalized_filter(providers),
            "limit": limit,
            "cursor_feature_id": _bbox_cursor_feature_id(cursor),
            "price_stale_hide_days": price_stale_hide_days,
        },
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


_FEATURES_CONTAINED_IN_AREA_SQL: Final[str] = f"""
WITH area_feature AS (
    SELECT feature_id, geom
    FROM feature.public_features
    WHERE feature_id = :feature_id
      AND kind = 'area'
      AND geom IS NOT NULL
)
SELECT
    f.feature_id,
    f.kind,
    f.name,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.marker_icon,
    f.marker_color,
    f.status
FROM area_feature AS a
JOIN feature.public_features AS f
  ON f.feature_id <> a.feature_id
 AND f.coord IS NOT NULL
 AND a.geom OPERATOR(x_extension.&&) f.coord
 AND x_extension.ST_Covers(a.geom, f.coord)
WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
ORDER BY f.kind ASC, f.name ASC, f.feature_id ASC
LIMIT :limit
"""


async def features_contained_in_area(
    session: AsyncSession,
    *,
    feature_id: str,
    kinds: Sequence[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """area feature polygon이 포함하는 point feature 목록.

    ADR-012/성능 원칙에 맞춰 area ``geom``과 point ``coord``를 둘 다 4326
    geometry로 비교하고, ``geom && coord`` bbox prefilter 뒤 ``ST_Covers``를
    적용한다. ``ST_Transform``을 공간 술어에 넣지 않는다.
    """
    rows = (
        (
            await session.execute(
                text(_FEATURES_CONTAINED_IN_AREA_SQL),
                {
                    "feature_id": feature_id,
                    "kinds": _normalized_filter(kinds),
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _bbox_cursor_feature_id(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid feature bbox cursor") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "features_bbox":
        raise ValueError("invalid feature bbox cursor")
    feature_id = payload.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid feature bbox cursor")
    return feature_id


def encode_bbox_cursor(feature_id: str) -> str:
    """Return opaque cursor for ``features_in_bbox`` keyset pagination."""

    raw = json.dumps(
        {"kind": "features_bbox", "feature_id": feature_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


_SEARCH_CURSOR_KIND: Final[str] = "feature_search"
_SEARCH_CURSOR_VERSION: Final[int] = 1
_SEARCH_CURSOR_MAX_LENGTH: Final[int] = 2048
_SEARCH_CURSOR_DOMAIN: Final[bytes] = b"kor-travel-map:feature-search-cursor:v1\0"


@dataclass(frozen=True)
class _FeatureSearchContract:
    q: str | None
    bbox: tuple[float, float, float, float] | None
    kinds: tuple[str, ...] | None
    categories: tuple[str, ...] | None
    page_size: int
    include_total: bool

    @property
    def q_enabled(self) -> bool:
        return self.q is not None

    @property
    def sort(self) -> str:
        return "score_desc_feature_id_asc" if self.q_enabled else "feature_id_asc"

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "q": self.q,
                "bbox": self.bbox,
                "kinds": self.kinds,
                "categories": self.categories,
                "sort": self.sort,
                "page_size": self.page_size,
                "include_total": self.include_total,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _normalize_search_filter(values: Sequence[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    return tuple(normalized) or None


def _feature_search_contract(
    *,
    q: str | None,
    bbox: tuple[float, float, float, float] | None,
    kinds: Sequence[str] | None,
    categories: Sequence[str] | None,
    page_size: int,
    include_total: bool,
) -> _FeatureSearchContract:
    normalized_q = q.strip() if q is not None else None
    if normalized_q == "":
        normalized_q = None
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")

    normalized_bbox: tuple[float, float, float, float] | None = None
    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError("invalid bbox")
        normalized_bbox = (
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )
        if not all(math.isfinite(value) for value in normalized_bbox):
            raise ValueError("invalid bbox")
        min_lon, min_lat, max_lon, max_lat = normalized_bbox
        if (
            min_lon < -180
            or max_lon > 180
            or min_lat < -90
            or max_lat > 90
            or min_lon > max_lon
            or min_lat > max_lat
        ):
            raise ValueError("invalid bbox")
        normalized_bbox = (
            0.0 if min_lon == 0.0 else min_lon,
            0.0 if min_lat == 0.0 else min_lat,
            0.0 if max_lon == 0.0 else max_lon,
            0.0 if max_lat == 0.0 else max_lat,
        )
    if normalized_q is None and normalized_bbox is None:
        raise ValueError("q 또는 bbox 중 하나는 필요합니다")

    return _FeatureSearchContract(
        q=normalized_q,
        bbox=normalized_bbox,
        kinds=_normalize_search_filter(kinds),
        categories=_normalize_search_filter(categories),
        page_size=min(page_size, 200),
        include_total=include_total,
    )


def _search_cursor_signing_key(signing_key: bytes) -> bytes:
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("feature search cursor signing key must be at least 32 bytes")
    return signing_key


def _cursor_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _cursor_b64decode(segment: str) -> bytes:
    if not segment or "=" in segment:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    try:
        decoded = base64.b64decode(
            segment + "=" * (-len(segment) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor") from exc
    if _cursor_b64encode(decoded) != segment:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    return decoded


def _sign_search_cursor_payload(payload_segment: str, *, signing_key: bytes) -> bytes:
    return hmac.new(
        _search_cursor_signing_key(signing_key),
        _SEARCH_CURSOR_DOMAIN + payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()


def _encode_search_cursor_payload(payload: Mapping[str, Any], *, signing_key: bytes) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    payload_segment = _cursor_b64encode(raw)
    signature = _sign_search_cursor_payload(payload_segment, signing_key=signing_key)
    return f"{payload_segment}.{_cursor_b64encode(signature)}"


def _search_cursor_payload(
    cursor: str | None,
    *,
    contract: _FeatureSearchContract,
    signing_key: bytes,
) -> dict[str, Any]:
    _search_cursor_signing_key(signing_key)
    if cursor is None:
        return {}
    if len(cursor) > _SEARCH_CURSOR_MAX_LENGTH or cursor.count(".") != 1:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    payload_segment, signature_segment = cursor.split(".", 1)
    raw_payload = _cursor_b64decode(payload_segment)
    actual_signature = _cursor_b64decode(signature_segment)
    if len(actual_signature) != hashlib.sha256().digest_size:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    expected_signature = _sign_search_cursor_payload(
        payload_segment,
        signing_key=signing_key,
    )
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise FeatureSearchCursorTamperedError("feature search cursor signature mismatch")
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor") from exc
    if not isinstance(payload, dict) or set(payload) != {"v", "kind", "query", "keyset"}:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    try:
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor") from exc
    if raw_payload != canonical_payload:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    if type(payload["v"]) is not int:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    if payload["v"] != _SEARCH_CURSOR_VERSION:
        raise FeatureSearchCursorVersionUnsupportedError(
            "unsupported feature search cursor version"
        )
    if not isinstance(payload["kind"], str) or payload["kind"] != _SEARCH_CURSOR_KIND:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    query_fingerprint = payload["query"]
    if (
        not isinstance(query_fingerprint, str)
        or len(query_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in query_fingerprint)
    ):
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    if query_fingerprint != contract.fingerprint:
        raise FeatureSearchCursorQueryMismatchError(
            "feature search cursor does not match the current query"
        )
    if not isinstance(payload["keyset"], dict):
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    return payload


def _search_cursor_params(
    cursor: str | None,
    *,
    contract: _FeatureSearchContract,
    signing_key: bytes,
) -> dict[str, Any]:
    payload = _search_cursor_payload(
        cursor,
        contract=contract,
        signing_key=signing_key,
    )
    params: dict[str, Any] = {
        "cursor_score": None,
        "cursor_feature_id": None,
    }
    if not payload:
        return params
    keyset = payload["keyset"]
    expected_keys = {"feature_id", "score"} if contract.q_enabled else {"feature_id"}
    if set(keyset) != expected_keys:
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    feature_id = keyset["feature_id"]
    if (
        not isinstance(feature_id, str)
        or not feature_id
        or feature_id != feature_id.strip()
    ):
        raise FeatureSearchCursorInvalidError("invalid feature search cursor")
    params["cursor_feature_id"] = feature_id
    if contract.q_enabled:
        try:
            score = keyset["score"]
            if not isinstance(score, str) or not math.isfinite(float(score)):
                raise ValueError("score must be a finite string")
            params["cursor_score"] = score
        except (KeyError, TypeError, ValueError) as exc:
            raise FeatureSearchCursorInvalidError("invalid feature search cursor") from exc
    return params


def _encode_search_cursor(
    item: FeatureSearchRow,
    *,
    contract: _FeatureSearchContract,
    signing_key: bytes,
) -> str:
    keyset: dict[str, Any] = {"feature_id": item.feature_id}
    if contract.q_enabled:
        score = item.score_cursor if item.score_cursor is not None else str(item.score)
        if not math.isfinite(float(score)):
            raise ValueError("feature search score cursor must be finite")
        keyset["score"] = score
    payload: dict[str, Any] = {
        "v": _SEARCH_CURSOR_VERSION,
        "kind": _SEARCH_CURSOR_KIND,
        "query": contract.fingerprint,
        "keyset": keyset,
    }
    return _encode_search_cursor_payload(payload, signing_key=signing_key)


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
    page_size: int = 50,
    cursor: str | None = None,
    include_total: bool = False,
    cursor_signing_key: bytes,
) -> FeatureSearchPage:
    """사용자 feature 검색.

    ``q`` 또는 ``bbox`` 중 하나는 필수다. ``q``는 pg_trgm ``%`` 연산자를 사용하고,
    threshold는 현재 transaction에만 ``SET LOCAL``로 적용한다(ADR-004/성능 가이드).
    bbox 술어는 stored ``coord`` 컬럼과 ``ST_MakeEnvelope``만 사용한다.
    """
    contract = _feature_search_contract(
        q=q,
        bbox=bbox,
        kinds=kinds,
        categories=categories,
        page_size=page_size,
        include_total=include_total,
    )
    cursor_params = _search_cursor_params(
        cursor,
        contract=contract,
        signing_key=cursor_signing_key,
    )
    min_lon: float | None
    min_lat: float | None
    max_lon: float | None
    max_lat: float | None
    if contract.bbox is not None:
        min_lon, min_lat, max_lon, max_lat = contract.bbox
    else:
        min_lon = min_lat = max_lon = max_lat = None

    q_enabled = contract.q_enabled
    if q_enabled:
        await session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.2"))
    effective_limit = contract.page_size
    rows = (
        (
            await session.execute(
                text(_FEATURE_SEARCH_BY_SCORE_SQL if q_enabled else _FEATURE_SEARCH_BY_ID_SQL),
                {
                    "q": contract.q,
                    "bbox_enabled": contract.bbox is not None,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "kinds": list(contract.kinds) if contract.kinds is not None else None,
                    "categories": (
                        list(contract.categories)
                        if contract.categories is not None
                        else None
                    ),
                    "limit_plus_one": effective_limit + 1,
                    **cursor_params,
                },
            )
        )
        .mappings()
        .all()
    )
    total_count: int | None = None
    if contract.include_total:
        count_result = await session.execute(
            text(_FEATURE_SEARCH_SCORE_COUNT_SQL if q_enabled else _FEATURE_SEARCH_COUNT_SQL),
            {
                "q": contract.q,
                "bbox_enabled": contract.bbox is not None,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "kinds": list(contract.kinds) if contract.kinds is not None else None,
                "categories": (
                    list(contract.categories)
                    if contract.categories is not None
                    else None
                ),
            },
        )
        total_count = int(count_result.scalar_one())
    items = tuple(_search_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_search_cursor(
            items[-1],
            contract=contract,
            signing_key=cursor_signing_key,
        )
        if len(rows) > effective_limit and items
        else None
    )
    return FeatureSearchPage(
        items=items,
        next_cursor=next_cursor,
        total_count=total_count,
    )


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

    공개 read이므로 ADR-067 ``feature.public_features`` projection 안에서만
    조회한다. ``statuses``는 그 projection과 **교집합**으로만 동작한다 —
    projection에는 ``status='active'`` row만 있으므로 active 외 값을 넘기면
    빈 결과가 된다(비공개 status 노출 금지, F-1).
    """
    if sort not in _NEARBY_SQL_BY_SORT:
        raise ValueError("sort must be one of distance, name, last_updated_at")
    if radius_km is not None and radius_km <= 0:
        raise ValueError("radius_km must be greater than 0")
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    effective_limit = min(limit, 500)
    rows = (
        (
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
        )
        .mappings()
        .all()
    )
    items = tuple(_nearby_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_nearby_cursor(items[-1], sort=sort)
        if len(rows) > effective_limit and items
        else None
    )
    return NearbyFeaturePage(items=items, next_cursor=next_cursor)


async def features_nearby(
    session: AsyncSession,
    *,
    lon: float,
    lat: float,
    radius_m: float,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    statuses: Sequence[str] | None = ("active",),
    providers: Sequence[str] | None = None,
    sort: str = "distance",
    limit: int = 100,
    cursor: str | None = None,
) -> NearbyFeaturePage:
    """일반 좌표(``lon``/``lat``, 4326) 중심 반경 ``radius_m`` 안 feature summary.

    사용자 현재 위치/추천 흐름용(T-213b). ADR-012: 입력 좌표는 ``origin`` CTE에서
    한 번만 5179로 변환해 상수로 굳히고, 술어는 STORED ``feature.features.coord_5179``에
    직접 ``ST_DWithin``/``ST_Distance``를 적용한다(GiST ``idx_features_coord_5179_gist``).
    cursor/정렬/응답 shape는 ``features_nearby_poi_cache_target``과 동일
    (``NearbyFeaturePage``). ``sort`` ∈ {distance, name, last_updated_at}.
    공개 read이므로 ADR-067 ``feature.public_features`` projection 안에서만
    조회하고, ``statuses``는 projection과 교집합으로만 동작한다(위 함수와 동일).
    """
    if sort not in _NEARBY_COORD_SQL_BY_SORT:
        raise ValueError("sort must be one of distance, name, last_updated_at")
    if radius_m <= 0:
        raise ValueError("radius_m must be greater than 0")
    if limit <= 0:
        raise ValueError("limit must be greater than 0")

    effective_limit = min(limit, 500)
    rows = (
        (
            await session.execute(
                text(_NEARBY_COORD_SQL_BY_SORT[sort]),
                {
                    "lon": lon,
                    "lat": lat,
                    "radius_m": radius_m,
                    "kinds": _normalized_filter(kinds),
                    "categories": _normalized_filter(categories),
                    "statuses": _normalized_filter(statuses),
                    "providers": _normalized_filter(providers),
                    "limit_plus_one": effective_limit + 1,
                    **_nearby_cursor_params(cursor, sort=sort),
                },
            )
        )
        .mappings()
        .all()
    )
    items = tuple(_nearby_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_nearby_cursor(items[-1], sort=sort)
        if len(rows) > effective_limit and items
        else None
    )
    return NearbyFeaturePage(items=items, next_cursor=next_cursor)


_CATEGORY_FEATURE_COUNTS_SQL: Final[str] = f"""
SELECT f.category, count(*) AS n
FROM feature.public_features AS f
WHERE TRUE
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
GROUP BY f.category
"""


async def category_feature_counts(session: AsyncSession) -> dict[str, int]:
    """category code → 공개 feature 수 (ADR-067 ``public_features`` projection).

    ``GET /categories?include_counts``(T-213f)에서 정적 카탈로그(144건)에 현재 DB
    분포를 합쳐 보여주기 위한 집계. 공개 표면이므로 비공개(draft/broken/hidden/
    inactive/soft-deleted) feature는 집계에 포함하지 않는다 — 과거의
    ``active_only`` 스위치는 비공개 분포를 공개 counts로 노출했기에 제거됐다
    (T-VN-04, F-1). 카탈로그에 없는(미지정/legacy) category code도 그대로
    반환하므로 호출자가 카탈로그와 교차한다.
    """
    rows = (await session.execute(text(_CATEGORY_FEATURE_COUNTS_SQL))).all()
    return {str(row[0]): int(row[1]) for row in rows}
