"""``kortravelmap.infra.feature_repo`` — Feature 적재/조회 raw SQL repository.

``FeatureBundle`` (provider 변환 출력)을 ``feature.features`` / ``provider_sync.
source_records`` / ``provider_sync.source_links`` 3 테이블에 한 transaction으로
upsert하는 **첫 DB write 경로** (ADR-004 raw SQL, ORM은 매핑만).

T-VN-35 / ADR-086 — kind별 typed subtype
----------------------------------------

kind별 상세와 geometry의 **정본은 subtype 5종**(``feature_places``/
``feature_events``/``feature_notices``/``feature_routes``/``feature_areas``)이다.
core ``feature.features``에는 ``detail`` JSONB도 ``geom``도 없다(alembic 0084~0086).

- **write**: ``upsert_feature``가 core upsert 직후 같은 트랜잭션에서
  ``feature_subtype.subtype_upsert_sql``을 실행한다. 파생 detail 쓰기는 없다.
- **read**: 공개 조회는 ``feature.public_features``, 비공개 상세는 code-level
  typed core+subtype 명시 조립을 사용한다. private read view는 없다.
- **공간 술어만 예외**: view의 ``geom``은 조인 산출 컬럼이라 인덱스가 없으므로
  bbox 후보 판정은 GiST가 있는 subtype 테이블을 직접 참조한다
  (``_bbox_candidate_predicate_sql``).

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
- ADR-018 — ``Feature.detail``은 kind에 맞는 모델
- ADR-086 — kind별 typed subtype이 상세·geometry 정본, core는 공통 축만
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
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.exceptions import (
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)
from kortravelmap.infra.feature_identity import (
    candidate_feature_uuid,
    verify_feature_uuid,
)
from kortravelmap.infra.feature_projection import (
    TYPED_FEATURE_DETAIL_COLUMNS_SQL,
    typed_feature_detail_joins_sql,
)
from kortravelmap.infra.feature_subtype import write_subtype

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
    "ProviderFeatureState",
    "load_source_record_links",
    "upsert_feature",
    "upsert_source_record",
    "upsert_source_link",
    "load_bundle",
    "load_bundles",
    "load_authoritative_notice_snapshot",
    "load_notice_event_bundles",
    "retire_features_absent_from_snapshot",
    "retire_features_by_source_entity_ids",
    "retire_geometryless_area_features_by_source",
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
    "public_active_notice_feature_identities",
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


@dataclass(frozen=True)
class ProviderFeatureState:
    """Provider conversion이 확정한 procedure 전용 3축 상태."""

    lifecycle_state: Literal["active", "retired"]
    publication_state: Literal["draft", "published", "suppressed"]
    quality_state: Literal["valid", "quarantined"]


def _provider_feature_state(feature: Feature) -> ProviderFeatureState:
    """Provider conversion가 명시한 3축을 state procedure에 전달한다."""
    return ProviderFeatureState(
        lifecycle_state=cast(Literal["active", "retired"], feature.lifecycle_state),
        publication_state=cast(
            Literal["draft", "published", "suppressed"], feature.publication_state
        ),
        quality_state=cast(Literal["valid", "quarantined"], feature.quality_state),
    )


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

# T-VN-34: base INSERT와 세 상태축 쓰기는 procedure만 수행한다.
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

# procedure의 existing-row branch는 상태를 절대 바꾸지 않는다. provider 본문 갱신은
# state 축이 아닌 core 컬럼만 갱신하며, user-request whole-row fence와 subtype fence
# 판단은 실제 저장값으로 유지한다. final T-VN-34C는 이 legacy provenance 열을 별도
# materialization 뒤 제거한다.
_UPDATE_PROVIDER_FEATURE_CORE_SQL: Final[str] = """
UPDATE feature.features AS f
SET
    kind = :kind,
    name = :name,
    category = :category,
    coord = CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
        ELSE x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(CAST(:lon AS double precision),
                CAST(:lat AS double precision)), 4326)
        END,
    coord_precision_digits = :coord_precision_digits,
    address = CAST(:address AS jsonb),
    legal_dong_code = :legal_dong_code,
    road_name_code = :road_name_code,
    road_address_management_no = :road_address_management_no,
    admin_dong_code = :admin_dong_code,
    sido_code = :sido_code,
    sigungu_code = :sigungu_code,
    urls = CAST(:urls AS jsonb),
    marker_icon = :marker_icon,
    marker_color = :marker_color,
    parent_feature_id = :parent_feature_id,
    sibling_group_id = :sibling_group_id,
    raw_refs = CAST(:raw_refs AS jsonb),
    updated_at = :updated_at
WHERE f.feature_id = :feature_id
  AND NOT (f.data_origin = 'user_request' AND f.data_version > 0)
RETURNING
    CAST(f.feature_uuid AS text) AS feature_uuid
"""


# notice ``valid_start_time`` 최초 관측 보존 (종전 core ``detail`` upsert의
# ``valid_start_origin='first_probe'`` 분기). provider가 "처음 관측한 시각"을
# 발효 시각으로 추정해 보내는 계보는 재적재마다 시작 시각이 앞뒤로 흔들리므로,
# 이미 저장된 값이 있으면 그것을 정본으로 유지한다.
#
# 종전에는 core upsert 한 문장 안의 ``ON CONFLICT`` CASE였다. detail이 사라지고
# 판정 대상이 subtype typed 컬럼으로 옮겨진 뒤에는 subtype upsert가 공용 헬퍼
# (``feature_subtype.subtype_upsert_sql``)에서 생성되므로 kind 전용 분기를 그 안에
# 넣지 않고, **같은 트랜잭션에서 행 잠금을 잡고 직전 값을 읽어** 파라미터로 넘긴다.
# ``FOR UPDATE``가 동시 writer를 직렬화하므로 read-then-write 경합이 없다(행이
# 없으면 잠글 것도 없고 뒤이은 INSERT의 유니크 인덱스가 직렬화한다).
_MATERIALIZE_PROVIDER_VERSION_SQL: Final[str] = """
CALL feature.materialize_provider_feature_version(CAST(:feature_id AS text))
"""

# provider entity는 DB dataset identity 아래 payload version과 독립적으로 한 행을 유지한다.
_UPSERT_SOURCE_ENTITY_SQL: Final[str] = """
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id,
    source_entity_type, source_entity_id,
    first_seen_at, last_seen_at
) VALUES (
    :source_entity_key, :provider_dataset_id,
    :source_entity_type, :source_entity_id,
    :observed_at, :observed_at
)
ON CONFLICT (source_entity_key) DO UPDATE SET
    first_seen_at = LEAST(provider_sync.source_entities.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at = GREATEST(
        provider_sync.source_entities.last_seen_at,
        EXCLUDED.last_seen_at
    )
"""

# source_records는 immutable raw snapshot이다. 재관측은 head만 갱신한다(ADR-087).
_UPSERT_SOURCE_RECORD_SQL: Final[str] = """
WITH inserted AS (
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash,
    fetched_at, imported_at
) VALUES (
    :source_record_key, :source_entity_key, CAST(:raw_data AS jsonb), :raw_payload_hash,
    :fetched_at, :imported_at
)
ON CONFLICT (source_entity_key, raw_payload_hash) DO NOTHING
RETURNING source_record_key, true AS inserted
), canonical AS (
    SELECT source_record_key, inserted FROM inserted
    UNION ALL
    SELECT existing.source_record_key, false AS inserted
    FROM provider_sync.source_records AS existing
    WHERE existing.source_entity_key = :source_entity_key
      AND existing.raw_payload_hash = :raw_payload_hash
      AND NOT EXISTS (SELECT 1 FROM inserted)
)
SELECT source_record_key, inserted
FROM canonical
"""

_UPSERT_SOURCE_ENTITY_HEAD_SQL: Final[str] = """
WITH prior AS MATERIALIZED (
    -- ``FOR UPDATE``를 걸면 **안 된다**. 같은 문장의 ``upserted``가 이 행을
    -- 갱신하므로 lock 획득이 그 갱신을 따라가며 행을 못 보고, ``prior``가 빈
    -- 결과가 된다 — 그러면 ``NOT EXISTS (prior)``가 항상 참이라 재관측마다
    -- ``became_current``가 참이 되어 feature 본문이 매번 재기록된다(실측:
    -- 같은 record 재적재에서 features_updated>0). 동시성은 ON CONFLICT의 행
    -- 잠금이 이미 담당한다 — 여기서 필요한 것은 **문장 이전 값**을 읽는 것뿐이다.
    SELECT current_source_record_key
    FROM provider_sync.source_entity_heads
    WHERE source_entity_key = :source_entity_key
), upserted AS (
    INSERT INTO provider_sync.source_entity_heads (
        source_entity_key, current_source_record_key, observed_at, expires_at
    ) VALUES (
        :source_entity_key, :source_record_key, :observed_at, :expires_at
    )
    ON CONFLICT (source_entity_key) DO UPDATE SET
        current_source_record_key = EXCLUDED.current_source_record_key,
        observed_at = EXCLUDED.observed_at,
        expires_at = EXCLUDED.expires_at,
        updated_at = clock_timestamp()
    WHERE (EXCLUDED.observed_at, EXCLUDED.current_source_record_key)
          > (
              provider_sync.source_entity_heads.observed_at,
              provider_sync.source_entity_heads.current_source_record_key
          )
    RETURNING current_source_record_key
)
SELECT EXISTS (SELECT 1 FROM upserted)
       AND (
           NOT EXISTS (SELECT 1 FROM prior)
           OR (SELECT current_source_record_key FROM prior)
              IS DISTINCT FROM :source_record_key
       ) AS became_current
"""

_UPSERT_SOURCE_LINK_SQL: Final[str] = """
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role,
    match_method, confidence, created_at
) VALUES (
    :feature_id,
    (SELECT source_entity_key
     FROM provider_sync.source_records
    WHERE source_record_key = :source_record_key),
    :source_role,
    :match_method, :confidence, :created_at
)
ON CONFLICT (feature_id, source_entity_key) DO UPDATE SET
    source_role = EXCLUDED.source_role,
    match_method = EXCLUDED.match_method,
    confidence = EXCLUDED.confidence
RETURNING (xmax = 0) AS inserted
"""

_PUBLIC_FEATURE_ROW_COLUMNS_SQL: Final[str] = """
    feature_id, CAST(feature_uuid AS text) AS feature_uuid, kind, name, category,
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
    marker_icon, marker_color,
    parent_feature_id, sibling_group_id,
    created_at, updated_at,
    row_revision
"""

_NONPUBLIC_FEATURE_ROW_COLUMNS_SQL: Final[str] = f"""
    f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid,
    f.kind, f.name, f.category,
    f.lifecycle_state, f.publication_state, f.quality_state,
    x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
    f.coord_precision_digits,
    CASE
      WHEN f.kind = 'area' AND a.geom IS NOT NULL
      THEN x_extension.ST_Area(CAST(a.geom AS x_extension.geography))
      ELSE NULL
    END AS area_square_meters,
    x_extension.ST_SRID(f.coord_5179) AS coord_5179_srid,
    f.address, {TYPED_FEATURE_DETAIL_COLUMNS_SQL}, f.urls, f.raw_refs,
    f.legal_dong_code, f.road_name_code, f.road_address_management_no,
    f.admin_dong_code, f.sido_code, f.sigungu_code,
    f.marker_icon, f.marker_color,
    f.parent_feature_id, f.sibling_group_id,
    f.created_at, f.updated_at, f.row_revision
"""

_GET_FEATURE_SQL: Final[str] = f"""
SELECT {_NONPUBLIC_FEATURE_ROW_COLUMNS_SQL}
FROM feature.features AS f
{typed_feature_detail_joins_sql("f")}
WHERE f.feature_id = :feature_id
"""

_GET_FEATURES_BY_IDS_SQL: Final[str] = f"""
SELECT {_NONPUBLIC_FEATURE_ROW_COLUMNS_SQL}
FROM feature.features AS f
{typed_feature_detail_joins_sql("f")}
WHERE f.feature_id = ANY(CAST(:feature_ids AS text[]))
"""

# 공개 단건/batch — ADR-067 단일 공개 projection(``feature.public_features``,
# alembic 0096)만 조회한다. 3축 공개 술어(active/published/valid)는 VIEW 한 곳에만
# 정의되어 있고 여기서는 재구현하지 않는다.
_GET_PUBLIC_FEATURE_SQL: Final[str] = f"""
SELECT {_PUBLIC_FEATURE_ROW_COLUMNS_SQL}
FROM feature.public_features
WHERE feature_id = :feature_id
"""

_GET_PUBLIC_FEATURES_BY_IDS_SQL: Final[str] = f"""
SELECT {_PUBLIC_FEATURE_ROW_COLUMNS_SQL}
FROM feature.public_features
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
"""

_FEATURE_LOAD_STATE_SQL: Final[str] = """
SELECT
    f.feature_id IS NOT NULL AS feature_exists,
    f.lifecycle_state,
    f.publication_state,
    f.quality_state,
    f.row_revision,
    f.data_origin,
    f.data_version,
    COALESCE(EXISTS (
        SELECT 1
        FROM ops.feature_overrides AS fo
        WHERE fo.feature_id = f.feature_id
          AND fo.field_path = 'lifecycle_state'
          AND fo.status = 'active'
          AND fo.override_value = '"retired"'::jsonb
          AND fo.prevent_provider_reactivation
    ), false) AS has_provider_reactivation_override
FROM (VALUES (CAST(:feature_id AS text))) AS wanted(feature_id)
LEFT JOIN feature.features AS f
  ON f.feature_id = wanted.feature_id
"""


def _lineage_sql(head_alias: str, *, entity_alias: str) -> str:
    """유효 계보 key — ``source_entity_heads``에 물화된 값을 읽는다 (ADR-087/088).

    T-VN-37이 계보 key를 물화했고, T-VN-33이 그 자리를 record에서 **head**로
    옮겼다. record는 payload **이력 전체**를 담지만 한 계보에서 실제로 경쟁하는
    것은 entity당 current 하나뿐이라, head에 두면 탐색이 계보 깊이에 무관해진다.

    **유효 계보를 통째로** 저장한다 — out-of-scope도 entity id가 값으로 들어간다.
    읽는 쪽이 ``COALESCE(head.lineage_key, entity.source_entity_id)``로 물러나면
    두 테이블에 걸친 식이 되어 어떤 단일 인덱스도 받지 못한다(실측으로 확인했다).
    ``entity_alias``는 서명 호환을 위해 남기고 쓰지 않는다.
    """

    del entity_alias
    return f"{head_alias}.lineage_key"


def _notice_lineage_sql(
    record_alias: str, *, entity_alias: str, dataset_alias: str
) -> str:
    """raw payload에서 계보를 **재계산**한다 (backfill·검증 전용).

    현행 read 경로는 ``_lineage_sql``로 물화된 값을 읽는다. 이 재계산은 값이
    맞는지 대조할 때와 컬럼이 없던 세대를 재생할 때만 쓴다.
    """

    return f"""
    CASE
      WHEN {dataset_alias}.provider = 'python-krex-api'
       AND {dataset_alias}.dataset_key = 'krex_traffic_notices'
       AND {entity_alias}.source_entity_type = 'traffic_notice'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(lower(btrim({record_alias}.raw_data->>'occurred_date')), ''),
            NULLIF(lower(btrim({record_alias}.raw_data->>'occurred_time')), ''),
            NULLIF(lower(btrim({record_alias}.raw_data->>'route_no')), ''),
            NULLIF(lower(btrim({record_alias}.raw_data->>'direction')), ''),
            NULLIF(lower(btrim({record_alias}.raw_data->>'point_name')), ''),
            NULLIF(lower(btrim({record_alias}.raw_data->>'incident_type_code')), '')
          ),
          ''
        ),
        {entity_alias}.source_entity_id
      )
      WHEN {dataset_alias}.provider = 'python-kma-api'
       AND {dataset_alias}.dataset_key = 'kma_weather_alerts'
       AND {entity_alias}.source_entity_type = 'weather_alert'
      THEN COALESCE(
        NULLIF(
          concat_ws(
            '::',
            NULLIF(btrim({record_alias}.raw_data->>'region_code'), ''),
            NULLIF(
              btrim(
                COALESCE(
                  {record_alias}.raw_data->>'phenomenon',
                  {record_alias}.raw_data->>'alert_type'
                )
              ),
              ''
            )
          ),
          ''
        ),
        {entity_alias}.source_entity_id
      )
      ELSE {entity_alias}.source_entity_id
    END
    """


def _canonical_notice_feature_sql(
    feature_alias: str,
    record_alias: str,
    *,
    entity_alias: str,
    dataset_alias: str,
    lineage: str | None = None,
) -> str:
    """현재 사건 단위 identity로 만든 notice feature인지 판정하는 SQL.

    KREX/KMA의 현 identity는 모두 ``bjd_code=None``과 고정 category를 사용하고,
    ``source_natural_key``는 ``_notice_lineage_sql`` 결과와 같다. 따라서 같은
    source record가 구/신 feature 양쪽에 연결된 identity 이행 동률에서도 현재
    ``make_feature_id`` 결과를 정확히 알아낼 수 있다. 그 외 provider는 근거가
    없으므로 ``false``로 두고 stable ``feature_id`` tie-break에 맡긴다.
    """
    # 물화된 계보를 넘기면 그것을 쓴다. 안 넘기면 재계산인데, read 경로에서는
    # raw_data JSON 추출이 행마다 붙어 T-VN-37이 없앤 비용이 되살아난다.
    lineage_sql = lineage or _notice_lineage_sql(
        record_alias,
        entity_alias=entity_alias,
        dataset_alias=dataset_alias,
    )
    return f"""
    CASE
      WHEN (
        ({dataset_alias}.provider = 'python-krex-api'
         AND {dataset_alias}.dataset_key = 'krex_traffic_notices'
         AND {entity_alias}.source_entity_type = 'traffic_notice')
        OR
        ({dataset_alias}.provider = 'python-kma-api'
         AND {dataset_alias}.dataset_key = 'kma_weather_alerts'
         AND {entity_alias}.source_entity_type = 'weather_alert')
      )
      THEN {feature_alias}.feature_id = (
        'f_global_n_' || left(
          encode(
            x_extension.digest(
              'global|notice|99000000|'
              || {dataset_alias}.provider || ':' || {dataset_alias}.dataset_key || '|'
              || {lineage_sql} || '|',
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
# T-VN-35D(ADR-086) — **typed timestamptz 비교**. 종전에는 free-form jsonb
# ``detail->>'valid_end_time'``을 문자열로 읽어 CAST했고, 오염된 한 행(빈 문자열·
# garbage·잘못된 timezone)이 이 함수를 공유하는 **모든** 공개 read를 500으로
# 만들 수 있어 ``pg_input_is_valid`` 가드를 덧대야 했다(report §2 D-9-7 / T-VN-06).
# ``feature_notices.valid_end_time``은 timestamptz 컬럼이라 파싱 불가 값이 애초에
# 존재할 수 없다 — 가드도, 문자열 파싱도 사라진다. 이것이 35D의 최대 실익이다.
#
# 필터 shape은 유지한다: 이 fragment는 alias 하나만 받아 WHERE/ON에 그대로 덧붙는
# **자립형**이어야 한다(#745 이후 curated/curation/collection이 임의 alias로 공유 —
# ``curated_repo``/``curation_repo``). 따라서 LEFT JOIN이 아니라 상관 서브쿼리로
# subtype을 참조한다. 호출자의 FROM 절을 바꾸지 않으므로 감산 정본이 한 곳에 남는다.
# subtype 행이 없거나 ``valid_end_time``이 NULL이면 "종료시각 없음 = 활성"으로
# 종전 의미를 유지한다. 인덱스는 ``idx_feature_notices_validity``(0085).
def _ended_notice_hidden_sql(feature_alias: str) -> str:
    """종료된 notice를 숨기는 SQL fragment를 feature alias에 맞춰 만든다."""

    return f"""
  AND (
    {feature_alias}.kind <> 'notice'
    OR NOT EXISTS (
      SELECT 1
      FROM feature.feature_notices AS ended_notice
      WHERE ended_notice.feature_id = {feature_alias}.feature_id
        AND ended_notice.valid_end_time IS NOT NULL
        AND ended_notice.valid_end_time <= now()
    )
  )
"""


# 한 feature에 여러 계보의 primary entity가 연결될 수 있다. 각 계보의 실제 최신 row를
# 고른 뒤 **모든 계보에서 밀린 feature만** 숨긴다. 한 계보라도 winner면 feature 전체를
# 보존하며, current primary source가 없는 notice도 기존처럼 표시한다.
def _latest_notice_only_sql(feature_alias: str) -> str:
    """구버전 notice를 숨기는 SQL fragment를 feature alias에 맞춰 만든다."""

    current_lineage_sql = _lineage_sql("cur_head", entity_alias="cur_se")
    current_canonical_sql = _canonical_notice_feature_sql(
        feature_alias,
        "cur_sr",
        entity_alias="cur_se",
        dataset_alias="cur_pd",
        lineage=current_lineage_sql,
    )
    other_lineage_sql = _lineage_sql("other_head", entity_alias="other_se")
    other_canonical_sql = _canonical_notice_feature_sql(
        "other_f",
        "other_sr",
        entity_alias="other_se",
        dataset_alias="other_pd",
        lineage=other_lineage_sql,
    )
    rivals = f"""            FROM provider_sync.source_entities AS other_se
            JOIN provider_sync.provider_datasets AS other_pd
              ON other_pd.provider_dataset_id = other_se.provider_dataset_id
            JOIN provider_sync.source_entity_heads AS other_head
              ON other_head.source_entity_key = other_se.source_entity_key
            JOIN provider_sync.source_records AS other_sr
              ON other_sr.source_record_key = other_head.current_source_record_key
            JOIN provider_sync.source_links AS other_sl
              ON other_sl.source_entity_key = other_se.source_entity_key
             AND other_sl.source_role = 'primary'
            JOIN feature.features AS other_f
              ON other_f.feature_id = other_sl.feature_id
            WHERE {other_lineage_sql} = current_notice.lineage_key
              AND other_pd.provider = current_notice.provider
              AND other_pd.dataset_key = current_notice.dataset_key
              AND other_se.source_entity_type = current_notice.source_entity_type
              AND other_f.feature_id <> {feature_alias}.feature_id
              AND other_f.kind = 'notice'
              AND other_f.lifecycle_state = 'active'"""
    return f"""
  AND (
    {feature_alias}.kind <> 'notice'
    OR NOT EXISTS (
      SELECT 1
      FROM (
        SELECT DISTINCT ON (
            cur_pd.provider,
            cur_pd.dataset_key,
            cur_se.source_entity_type,
            {current_lineage_sql}
        )
            cur_pd.provider,
            cur_pd.dataset_key,
            cur_se.source_entity_type,
            {current_lineage_sql} AS lineage_key,
            cur_head.observed_at AS seen_at,
            cur_sr.source_record_key,
            {current_canonical_sql} AS canonical_identity
        FROM provider_sync.source_links AS cur_sl
        JOIN provider_sync.source_entities AS cur_se
          ON cur_se.source_entity_key = cur_sl.source_entity_key
        JOIN provider_sync.provider_datasets AS cur_pd
          ON cur_pd.provider_dataset_id = cur_se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS cur_head
          ON cur_head.source_entity_key = cur_se.source_entity_key
        JOIN provider_sync.source_records AS cur_sr
          ON cur_sr.source_record_key = cur_head.current_source_record_key
        WHERE cur_sl.feature_id = {feature_alias}.feature_id
          AND cur_sl.source_role = 'primary'
        ORDER BY
            cur_pd.provider,
            cur_pd.dataset_key,
            cur_se.source_entity_type,
            {current_lineage_sql},
            cur_head.observed_at DESC,
            cur_sr.source_record_key DESC
      ) AS current_notice
      LEFT JOIN LATERAL (
        -- "나보다 나은 현재 head가 있나"를 **두 EXISTS로 나눈다**(ADR-087).
        -- 한 술어 안에 OR로 두면 Postgres가 순서 조건을 Index Cond로 밀지 못하고
        -- Filter로 남겨, 계보 전수를 훑는다. 나누면 앞쪽은 순수 행 비교라
        -- idx_source_entity_heads_lineage의 범위가 되고, 뒤쪽은 동률(= 같은 head를
        -- 두 feature가 공유하는 identity 이행)일 때만 돈다. 사전식 비교라 값은
        -- 종전 3분기와 동일하다.
        SELECT 1 AS better_exists
        WHERE EXISTS (
            SELECT 1{rivals}
              AND (other_head.observed_at, other_sr.source_record_key)
                  > (current_notice.seen_at, current_notice.source_record_key)
            LIMIT 1
        )
        OR EXISTS (
            SELECT 1{rivals}
              AND (other_head.observed_at, other_sr.source_record_key)
                  = (current_notice.seen_at, current_notice.source_record_key)
              AND (
                (
                  {other_canonical_sql}
                  AND NOT current_notice.canonical_identity
                )
                OR (
                  {other_canonical_sql}
                    = current_notice.canonical_identity
                  AND other_f.feature_id < {feature_alias}.feature_id
                )
              )
            LIMIT 1
        )
      ) AS better ON true
      HAVING bool_and(better.better_exists IS NOT NULL)
    )
  )
"""


# ─── H35 고정 세대(0063~0079) replay 전용 ────────────────────────────────
# 그 세대에는 provider_datasets도 source_entity_heads도 없다. 현행 필터를
# 재사용하면 리허설이 존재하지 않는 테이블을 참조한다 — merge에서 실제로
# 그 상태가 됐다. 당시 SQL을 글자 그대로 보존한다.
def _frozen_h35_notice_lineage_sql(alias: str) -> str:
    """``source_records`` 행에서 계보 key를 **재계산**하는 SQL."""

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



# 유효 계보 key — 현행 스키마에서 계보를 읽는 **유일한 방법**이다 (ADR-087).
#
# ``lineage_key``는 notice 전용 규칙이 있는 scope에만 채워지고(그 밖은 NULL),
# 나머지는 ``source_entity_id``가 그대로 계보다. 전 행에 사본을 물화하지 않는
# 이유는 실측이다: 73만 행 중 계보 규칙이 적용되는 것은 744행(0.10%)뿐인데,
# 전 행 backfill은 heap을 826MB → 1,700MB로 **영구히** 부풀리고(VACUUM으로도
# OS에 반환되지 않는다) 그 두 배의 WAL과 2분짜리 ACCESS EXCLUSIVE lock을 낸다.
#
# 0079 세대의 유효 계보 — 그 시절엔 source_records가 계보 key를 직접 들고 있었다.
def _frozen_h35_lineage_sql(alias: str) -> str:
    """``source_records`` alias의 유효 계보 key SQL (고정 세대 전용)."""

    return f"COALESCE({alias}.lineage_key, {alias}.source_entity_id)"


def _frozen_h35_canonical_notice_feature_sql(
    feature_alias: str, source_alias: str, *, lineage: str | None = None
) -> str:
    """현재 사건 단위 identity로 만든 notice feature인지 판정하는 SQL.

    KREX/KMA의 현 identity는 모두 ``bjd_code=None``과 고정 category를 사용하고,
    ``source_natural_key``는 계보 key와 같다. 따라서 같은 source record가 구/신
    feature 양쪽에 연결된 identity 이행 동률에서도 현재 ``make_feature_id`` 결과를
    정확히 알아낼 수 있다. 그 외 provider는 근거가 없으므로 ``false``로 두고
    stable ``feature_id`` tie-break에 맡긴다.

    ``lineage``: 계보 key SQL 식. 기본값은 저장 컬럼이고, 컬럼이 없는 H35 고정
    세대 replay만 재계산 식을 넘긴다.
    """
    lineage = _frozen_h35_lineage_sql(source_alias) if lineage is None else lineage
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
              || {lineage} || '|',
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


def _frozen_h35_latest_notice_only_sql(feature_alias: str) -> str:
    """0079 고정 스키마 세대의 "구버전 notice 숨김" 판정 (역사 표면 **바이트** 보존).

    그 세대에는 ``source_records.lineage_key``가 없다. 리허설의 존재 이유가 "그때
    그 표면을 그대로 재생한다"이므로, 동등해 보이는 재작성도 두지 않고 당시 SQL을
    글자 그대로 남긴다 — ``_frozen_h35_ended_notice_hidden_sql``과 같은 규약이다.
    현행 코드가 이 형태를 되살리는 것을 막기 위해 이 함수 안에만 존재한다.
    """

    lineage_cur = _frozen_h35_notice_lineage_sql("cur_sr")
    canonical_cur = _frozen_h35_canonical_notice_feature_sql(
        feature_alias, "cur_sr", lineage=lineage_cur
    )
    canonical_other = _frozen_h35_canonical_notice_feature_sql(
        "other_f", "other_sr", lineage=_frozen_h35_notice_lineage_sql("other_sr")
    )
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
            {lineage_cur}
        )
            cur_sr.provider,
            cur_sr.dataset_key,
            cur_sr.source_entity_type,
            {lineage_cur} AS lineage_key,
            COALESCE(
                cur_sr.last_seen_at, cur_sr.imported_at, cur_sr.fetched_at
            ) AS seen_at,
            cur_sr.source_record_key,
            {canonical_cur} AS canonical_identity
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
            {lineage_cur},
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
         AND {_frozen_h35_notice_lineage_sql("other_sr")} = current_notice.lineage_key
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
                  {canonical_other}
                  AND NOT current_notice.canonical_identity
                )
                OR (
                  {canonical_other}
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
# 판정(``_LATEST_NOTICE_ONLY_SQL``의 active lifecycle competitor)은 reconcile
# 의미론(T-VN-06/37 소유)이라 T-VN-04에서 view로 바꾸지 않았다 — 비공개 신규
# feature가 구 feature를 계속 밀어내는 현행 동작 유지.
def public_active_notice_filter_sql(
    feature_alias: str, *, frozen_h35_schema: bool = False
) -> str:
    """모든 공개 read가 공유하는 active/latest notice 감산 SQL을 반환한다.

    호출자는 신뢰된 정적 SQL alias만 넘긴다. 공개 여부의 기본 집합은
    ``feature.public_features``이고, 이 fragment는 종료·구버전 notice만 추가로
    제외한다.

    ``frozen_h35_schema``: H35 cutover 리허설 전용. 그 경로는 **0079로 고정된
    과거 스키마**를 재생하므로 0085가 신설한 ``feature.feature_notices``가
    존재하지 않는다 — 그 세대의 판정(``detail`` 문자열 + 방어 cast)을 그대로
    쓴다. 현행 표면은 typed 비교만 쓴다(T-VN-35, ADR-086).
    """

    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    if frozen_h35_schema:
        return _frozen_h35_ended_notice_hidden_sql(
            feature_alias
        ) + _frozen_h35_latest_notice_only_sql(feature_alias)
    return _ended_notice_hidden_sql(feature_alias) + _latest_notice_only_sql(feature_alias)


def _frozen_h35_ended_notice_hidden_sql(feature_alias: str) -> str:
    """0079 고정 스키마 세대의 "종료 notice 숨김" 판정 (역사 표면 **바이트** 보존).

    ``detail->>'valid_end_time'``를 방어 cast(``pg_input_is_valid``)와 함께 읽던
    당시 규칙을 **글자 그대로** 옮긴 것이다. 리허설의 존재 이유가 "그때 그 표면을
    그대로 재생한다"이므로 동등해 보이는 재작성도 두지 않는다 — 실제로 안 같다:
    NULL end_time과 cast 불가 문자열에서 판정이 갈린다(원본은 전자를 보이게,
    후자를 숨기게 한다). 현행 코드가 이 형태를 되살리는 것을 막기 위해 이 함수
    안에만 존재한다.
    """

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


_PUBLIC_ACTIVE_NOTICE_FILTER_SQL: Final[str] = public_active_notice_filter_sql("f")


# service batch는 공개 payload와 base-table lifecycle 판정을 한 snapshot에서 읽는다.
# ``feature.public_features``가 payload의 유일한 출처이고 base row는 존재·lifecycle
# state와 ``row_revision``만 제공한다(ADR-067). notice 종료/계보 감산도 다른 공개
# read와 같은 fragment를 사용한다.
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
    CAST(base.feature_uuid AS text) AS feature_uuid,
    CASE
      WHEN base.feature_id IS NULL THEN 'missing'
      WHEN base.lifecycle_state = 'retired' THEN 'retired'
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
    - **route/area geometry**: ``&&`` MBR prefilter만으로는 false positive가 실재하므로
      (F-8) subtype GiST(``idx_feature_routes_geom_gist``/``idx_feature_areas_geom_gist``)를
      ``&&``로 구동한 뒤 exact ``ST_Intersects``를 덧대 실제 envelope 교차만 남긴다.
      ``ST_Transform``을 술어에 넣지 않는다(ADR-012).

    T-VN-35D(ADR-086) 재작성 — geometry 정본이 subtype으로 옮겨졌다. **공간 술어만은
    조립 projection을 쓸 수 없다**: projection의
    ``geom``은 ``COALESCE(routes.geom, areas.geom)`` 산출 컬럼이라 인덱스가 없고,
    그대로 술어에 넣으면 features 730k행 seq scan이 된다(T-VN-21 tier-1 gate 위반).
    그래서 GiST가 붙어 있는 subtype 테이블을 직접 참조하되, 두 arm이 모두
    ``{feature_alias}`` 한 테이블에 대한 indexable 술어로 남는 형태를 고른다:

    - geometry 교차 후보는 **비상관 ``ARRAY(SELECT ...)``**(InitPlan — 쿼리당 1회
      평가, bbox로 이미 좁혀진 작은 집합)로 뽑아 ``feature_id = ANY(...)``로 건다.
      PK 인덱스를 타므로 planner가 coord GiST arm과 **BitmapOr**로 결합할 수 있다
      (상관 서브쿼리를 OR 아래 두면 semi-join으로 승격되지 않아 seq scan이 된다).
      route/area의 state는 parent에 있으므로, 여기서는 DB 소유 cache ``public_ready``를
      명시해 subtype partial GiST의 predicate를 만족시킨다. outer public view는 여전히
      3축 membership의 최종 fence다.
    - coord arm은 route/area를 **kind로** 배제한다. 0086 이후 geometry 없는
      route/area는 표현 불가능하고(subtype geom이 NOT NULL, 마이그레이션 preflight가
      기존 행을 fail-close로 거른다) DTO도 구성 시점에 막으므로, 종전의
      "subtype 행이 없으면 coord로 잡는다" 분기는 존재할 수 없는 상태를 위한
      행별 EXISTS 두 번이었다. admin 쪽 같은 술어와도 이제 모양이 같다.
    """
    if not feature_alias.isidentifier():
        raise ValueError("feature alias must be a SQL identifier")
    env = _bbox_envelope_sql()
    return f"""(
    (
      {feature_alias}.coord IS NOT NULL
      AND {feature_alias}.coord OPERATOR(x_extension.&&) {env}
      AND {feature_alias}.kind NOT IN ('route', 'area')
    )
    OR {feature_alias}.feature_id = ANY (
      ARRAY(
        SELECT bbox_hit_route.feature_id
        FROM feature.feature_routes AS bbox_hit_route
        WHERE bbox_hit_route.public_ready
          AND bbox_hit_route.geom OPERATOR(x_extension.&&) {env}
          AND x_extension.ST_Intersects(bbox_hit_route.geom, {env})
        UNION ALL
        SELECT bbox_hit_area.feature_id
        FROM feature.feature_areas AS bbox_hit_area
        WHERE bbox_hit_area.public_ready
          AND bbox_hit_area.geom OPERATOR(x_extension.&&) {env}
          AND x_extension.ST_Intersects(bbox_hit_area.geom, {env})
      )
    )
  )"""


def _bbox_attribute_filter_sql(feature_alias: str) -> str:
    """kind/category/provider 공통 속성 필터 (items 경량/geometry + cluster 공유).

    세 변형이 같은 SQL을 재사용해 이중 복제를 제거한다(ADR-073 D-9-4). NULL 배열이면
    술어가 단락(short-circuit)돼 인덱스 기반 조회에 영향이 없다. provider 필터는
    primary source(``source_role = 'primary'``) 기준 EXISTS다.
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
      JOIN provider_sync.provider_datasets AS pd
        ON pd.provider_dataset_id = pr.provider_dataset_id
      WHERE pl.feature_id = {feature_alias}.feature_id
        AND pl.source_role = 'primary'
        AND pd.provider = ANY(CAST(:providers AS text[]))
    )
  )
"""


# notice lineage 가시성 read — T-VN-32B dual: feature 참조를 legacy id와 UUID
# 정본 쌍으로 병행 반환한다(0080이 view에 feature_uuid를 노출).
_PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL: Final[str] = f"""
SELECT f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid
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
# (``feature.public_features``)만 조인한다. caller(mois_detail)는 public-only를
# 기대하므로 suppression/retirement/quality 판정을 따로 재구현하지 않는다.
#
# 정합성(issue #509 Problem B): 같은 안정 식별자에 구/신 feature가 둘 다 primary
# link로 남을 수 있다(re-key 정리 직전/직후). view가 non-active를 제거한 뒤에도
# active 동률이 남을 수 있으므로 결정적 ``ORDER BY``(imported_at 최신 → feature_id)
# 후 LIMIT 1로 deterministic하게 반환한다.
_GET_PRIMARY_SOURCE_DETAIL_SQL: Final[str] = """
SELECT
    f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid,
    f.kind, f.name, f.category,
    core.lifecycle_state, core.publication_state, core.quality_state,
    x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
    f.address, f.detail,
    sr.source_record_key, pd.provider, pd.dataset_key,
    se.source_entity_type, se.source_entity_id,
    sr.raw_data, sr.fetched_at, sr.imported_at, head.observed_at, head.expires_at
FROM provider_sync.source_entities AS se
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = se.source_entity_key
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = head.current_source_record_key
JOIN provider_sync.source_links AS sl
  ON sl.source_entity_key = se.source_entity_key
JOIN feature.public_features AS f
  ON f.feature_id = sl.feature_id
JOIN feature.features AS core
  ON core.feature_id = f.feature_id
WHERE pd.provider = :provider
  AND pd.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
  AND se.source_entity_id = :source_entity_id
  AND sl.source_role = 'primary'
ORDER BY head.observed_at DESC, sr.imported_at DESC, f.feature_id
LIMIT 1
"""

# bbox 조회 — ADR-012: 입력 bbox는 4326, GIST(coord) 인덱스 사용. 공개 여부는
# ADR-067 단일 projection(``feature.public_features``)이 결정한다 — 이 파일의
# 공개 read SQL은 술어를 재구현하지 않는다. view의 3축 공개 predicate와 일치하는
# partial index가 이 hot path를 받는다.
# kinds 필터는 NULL이면 전체 (asyncpg ARRAY 바인딩). 경량 표현(좌표 + 표시 메타).
_CURRENT_MAP_SUMMARY_CTES: Final[str] = """
price_points AS (
    SELECT
        candidate.feature_id,
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
    FROM candidates AS candidate
    JOIN feature.current_price_summary AS summary
      ON summary.feature_id = candidate.feature_id
    JOIN feature.feature_price_values AS fact
      ON fact.price_value_key = summary.price_value_key
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = fact.provider_dataset_id
     AND dataset.is_active
    WHERE candidate.kind = 'price'
      AND (
        CAST(:price_stale_hide_days AS integer) IS NULL
        OR fact.observed_at >= now()
             - make_interval(days => CAST(:price_stale_hide_days AS integer))
      )
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
                  WHEN 'gasoline' THEN 10
                  WHEN 'diesel' THEN 20
                  WHEN 'premium_gasoline' THEN 30
                  WHEN 'lpg' THEN 40
                  ELSE 100
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
        candidate.feature_id,
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
            PARTITION BY candidate.feature_id
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
    FROM candidates AS candidate
    JOIN feature.current_weather_summary AS summary
      ON summary.feature_id = candidate.feature_id
    JOIN feature.feature_weather_values AS fact
      ON fact.weather_value_key = summary.weather_value_key
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = fact.provider_dataset_id
     AND dataset.is_active
    WHERE candidate.kind = 'weather'
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
"""

_FEATURES_IN_BBOX_SQL: Final[str] = f"""
WITH candidates AS MATERIALIZED (
    SELECT
        f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind, f.name, f.category,
        x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
        f.marker_icon, f.marker_color
    FROM feature.public_features AS f
    WHERE {_bbox_candidate_predicate_sql("f")}
    {_bbox_attribute_filter_sql("f")}
      AND (
        CAST(:cursor_feature_id AS text) IS NULL
        OR f.feature_id > CAST(:cursor_feature_id AS text)
      )
    {_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
    ORDER BY f.feature_id ASC
    LIMIT :limit
),
{_CURRENT_MAP_SUMMARY_CTES}
SELECT
    candidate.feature_id, candidate.feature_uuid,
    candidate.kind, candidate.name, candidate.category,
    candidate.lon, candidate.lat,
    candidate.marker_icon, candidate.marker_color,
    price_summaries.price_summary,
    weather_summaries.weather_summary
FROM candidates AS candidate
LEFT JOIN price_summaries USING (feature_id)
LEFT JOIN weather_summaries USING (feature_id)
ORDER BY candidate.feature_id ASC
"""

_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL: Final[str] = f"""
WITH candidates AS MATERIALIZED (
    SELECT
        f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind, f.name, f.category,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        f.marker_icon, f.marker_color,
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
    WHERE {_bbox_candidate_predicate_sql("f")}
    {_bbox_attribute_filter_sql("f")}
      AND (
        CAST(:cursor_feature_id AS text) IS NULL
        OR f.feature_id > CAST(:cursor_feature_id AS text)
      )
    {_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
    ORDER BY f.feature_id ASC
    LIMIT :limit
),
{_CURRENT_MAP_SUMMARY_CTES}
SELECT
    candidate.feature_id, candidate.feature_uuid,
    candidate.kind, candidate.name, candidate.category,
    candidate.lon, candidate.lat,
    candidate.marker_icon, candidate.marker_color,
    price_summaries.price_summary,
    weather_summaries.weather_summary,
    candidate.geometry,
    candidate.area_square_meters
FROM candidates AS candidate
LEFT JOIN price_summaries USING (feature_id)
LEFT JOIN weather_summaries USING (feature_id)
ORDER BY candidate.feature_id ASC
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
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        f.marker_icon,
        f.marker_color,
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
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
        f.coord,
        f.marker_icon,
        f.marker_color,
        x_extension.similarity(f.name, CAST(:q AS text)) AS score
    FROM feature.public_features AS f
    WHERE f.name OPERATOR(x_extension.%) CAST(:q AS text)
{_PUBLIC_ACTIVE_NOTICE_FILTER_SQL}
),
candidates AS (
    SELECT
        feature_id,
        feature_uuid,
        kind,
        name,
        category,
        x_extension.ST_X(coord) AS lon,
        x_extension.ST_Y(coord) AS lat,
        marker_icon,
        marker_color,
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
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
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
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
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
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
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
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
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

# snapshot retirement — 주어진 (provider, dataset_key, source_entity_type)의
# **primary source**로 적재된 feature 중, snapshot source_entity_id 집합에 없는
# 것을 lifecycle ``retired`` + publication ``suppressed``로 전이한다. 전체 snapshot
# 적재 후 호출해 "이번 snapshot에서 사라진" feature를 비활성화한다 (Step A bulk,
# ADR-017 — place는 무기한 유지). 이미 retired이면 건너뛴다.
# source entity→dataset natural identity join을 사용한다. ``:keys`` 빈 배열이면 전체
# 비활성화(snapshot이 비었음을 의미).
_SOFT_DELETE_NOT_IN_SNAPSHOT_SQL: Final[str] = """
SELECT DISTINCT f.feature_id, pd.provider_dataset_id
FROM feature.features AS f
JOIN provider_sync.source_links AS sl ON sl.feature_id = f.feature_id
JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd ON pd.provider_dataset_id = se.provider_dataset_id
WHERE f.lifecycle_state = 'active'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND sl.source_role = 'primary'
  AND pd.provider = :provider
  AND pd.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
  AND NOT (se.source_entity_id = ANY(CAST(:keys AS text[])))
"""


# Step C 폐업/취소 — snapshot 부재 retirement의 inverse. 주어진 source_entity_id
# 집합에 **속하는** primary-source feature를 retired/suppressed로 전이(폐업/취소된
# 인허가). ADR-017 — place는 무기한 유지, 이미 retired이면 건너뛴다.
# ``:keys`` 빈 배열이면 아무 것도 비활성화하지 않는다(폐업 목록이 비었음).
_INACTIVATE_BY_ENTITY_IDS_SQL: Final[str] = """
SELECT DISTINCT f.feature_id, pd.provider_dataset_id
FROM feature.features AS f
JOIN provider_sync.source_links AS sl ON sl.feature_id = f.feature_id
JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd ON pd.provider_dataset_id = se.provider_dataset_id
WHERE f.lifecycle_state = 'active'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND sl.source_role = 'primary'
  AND pd.provider = :provider
  AND pd.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
  AND se.source_entity_id = ANY(CAST(:keys AS text[]))
"""


# 과거 보정 — kind='area'인데 경계 geometry가 없는 provider feature만
# retired/suppressed 전이.
# 새 place row와 같은 source_entity_id를 공유할 수 있으므로 entity-id 기반 폐업 메서드를
# 재사용하지 않고 feature kind/geometry 조건을 직접 건다.
#
# **0086 이후 write가 선차단한다** — geometry 없는 area/route bundle은
# ``upsert_feature``가 ``ValueError``로 거부하므로 이 상태는 새로 생기지 않는다.
# 남은 역할은 0086 이전에 적재된 잔재를 한 번 정리하는 것뿐이며, "geometry 없음"은
# 이제 ``features.geom IS NULL``이 아니라 **``feature_areas`` 행 부재**로 판정한다.
_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL: Final[str] = """
SELECT DISTINCT f.feature_id, pd.provider_dataset_id
FROM feature.features AS f
JOIN provider_sync.source_links AS sl ON sl.feature_id = f.feature_id
JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd ON pd.provider_dataset_id = se.provider_dataset_id
WHERE f.lifecycle_state = 'active'
  AND f.kind = 'area'
  AND NOT EXISTS (
    SELECT 1 FROM feature.feature_areas AS a WHERE a.feature_id = f.feature_id
  )
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND sl.source_role = 'primary'
  AND pd.provider = :provider
  AND pd.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
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
    """service batch의 상태 판정과 공개 ``trip_card`` projection.

    ``feature_uuid``는 T-VN-32B UUID 정본 병행 노출(additive) — base row가 있는
    상태(found/retired/suppressed/unchanged)에서 채워지고 missing이면 ``None``.
    """

    feature_id: str
    state: FeatureBatchItemState
    row_revision: int | None
    trip_card: dict[str, Any] | None
    feature_uuid: str | None = None


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
    """외부 POI/cache target 주변 feature summary row.

    ``feature_uuid``는 T-VN-32B UUID 정본 병행 노출(additive).
    """

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float
    lat: float
    distance_m: float
    primary_provider: str | None
    primary_dataset_key: str | None
    last_updated_at: datetime
    feature_uuid: str | None = None


@dataclass(frozen=True)
class FeatureSearchRow:
    """사용자 feature 검색 결과 summary row.

    ``feature_uuid``는 T-VN-32B UUID 정본 병행 노출(additive).
    """

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None
    lat: float | None
    marker_icon: str | None
    marker_color: str | None
    score: float | None = None
    score_cursor: str | None = None
    feature_uuid: str | None = None


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


#: geometry가 필수인 kind — subtype ``geom``이 NOT NULL이라 WKT 없이는 행을
#: 만들 수 없다(0086). ``feature_subtype._GEOM_EXPR``와 같은 집합이다.
def _feature_params(feature: Feature) -> dict[str, Any]:
    """``Feature`` DTO → procedure/non-axis core bind params.

    ``geom_wkt``은 core 컬럼이 아니라 route/area **subtype** upsert의 바인딩이다
    (``feature_subtype.subtype_upsert_sql``이 같은 이름의 파라미터를 쓴다).
    """
    coord = feature.coord
    addr = feature.address
    return {
        "feature_id": feature.feature_id,
        # T-VN-32C 정본 generator — 비파생 UUIDv7 후보. ON CONFLICT 경로에서는
        # 버려지고 기존 저장값이 정본(0083, feature_identity 모듈 docstring).
        "feature_uuid": candidate_feature_uuid(),
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
        "raw_refs": _dump_raw_refs(feature),
        "created_at": feature.created_at,
        "updated_at": feature.updated_at,
    }


def _provider_feature_payload(params: Mapping[str, Any]) -> str:
    """Create procedure에 넘길 provider core payload JSON을 만든다.

    세 축은 state procedure의 별도 인자이며 core payload에 넣지 않는다.
    ``geom_wkt``도 typed subtype 전용 바인딩이라 core
    procedure payload가 아니다.
    """
    payload = {
        key: (
            json.loads(value)
            if key in {"address", "urls", "raw_refs"} and isinstance(value, str)
            else value
        )
        for key, value in params.items()
        if key
        not in {
            "geom_wkt",
            "data_origin",
            "data_version",
            "created_at",
            "updated_at",
        }
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _provider_state_context(
    *,
    provider_dataset_id: int,
    reason_code: str,
    source_membership: _ProviderSourceMembership,
    transition_kind: Literal["provider_sync"] = "provider_sync",
) -> str:
    """DB가 검증할 provider source membership을 포함한 audit context를 만든다."""
    return json.dumps(
        {
            "transition_kind": transition_kind,
            "reason_code": reason_code,
            "provider_dataset_id": provider_dataset_id,
            "source_entity_key": source_membership.source_entity_key,
            "source_record_key": source_membership.source_record_key,
        },
        ensure_ascii=False,
    )


def _dump_raw_refs(feature: Feature) -> str:
    """``feature.raw_refs`` (list[RawDataRef]) → JSONB array 문자열."""
    import json

    return json.dumps(
        [ref.model_dump(mode="json") for ref in feature.raw_refs],
        ensure_ascii=False,
    )


def _source_record_params(
    record: SourceRecord, *, provider_dataset_id: int
) -> dict[str, Any]:
    import json

    return {
        "source_record_key": record.source_record_key,
        "source_entity_key": _make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        ),
        "provider_dataset_id": provider_dataset_id,
        "provider": record.provider,
        "dataset_key": record.dataset_key,
        "source_entity_type": record.source_entity_type,
        "source_entity_id": record.source_entity_id,
        "raw_data": json.dumps(record.raw_data, ensure_ascii=False, default=str),
        "raw_payload_hash": record.raw_payload_hash,
        "fetched_at": record.fetched_at,
        "imported_at": record.imported_at,
        "observed_at": record.imported_at,
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
        "created_at": link.created_at,
    }


async def _upsert_feature_subtype(
    session: AsyncSession,
    feature: Feature,
    *,
    stored_feature_uuid: str,
    geom_wkt: str | None,
) -> None:
    """kind별 typed subtype upsert (core upsert와 **같은 트랜잭션**).

    ``feature_uuid``는 core upsert의 RETURNING 값을 그대로 쓴다. conflict-update
    경로에서 정본은 이미 저장돼 있던 UUID이므로 후보를 재계산하면 identity 사본
    FK(``fk_*_identity_pair``)가 깨진다 — 파생 계산 금지.
    """
    await write_subtype(
        session,
        feature_id=feature.feature_id,
        feature_uuid=stored_feature_uuid,
        kind=feature.kind.value,
        detail=feature.detail,
        geom_wkt=geom_wkt,
    )


async def upsert_feature(
    session: AsyncSession,
    feature: Feature,
    *,
    provider_dataset_id: int,
    source_membership: _ProviderSourceMembership,
) -> bool:
    """provider Feature를 procedure와 typed subtype으로 적재한다.

    ``coord_5179``는 STORED generated이라 INSERT/UPDATE 대상에서 제외 (ADR-012).

    T-VN-32C(0083): ``feature_uuid``는 writer가 비파생 UUIDv7 후보를 명시
    INSERT하고(fill 트리거는 raw SQL 경로 안전망), RETURNING 관측값을
    fail-close 검증한다 — 신규 insert면 보낸 후보와 동일해야 하고(generator
    이원화 차단), conflict-update면 기존 저장값이 정본이다
    (``FeatureIdentityInvariantError``).

    T-VN-35(ADR-086): core는 kind 공통 축만 쓰고 kind별 상세·geometry는 subtype이
    정본이다. 두 write는 **한 트랜잭션**이며 순서가 강제된다 — subtype의
    ``(feature_id, kind)``/``(feature_id, feature_uuid)`` FK가 core 행을 먼저
    요구하기 때문이다(commit 경계는 종전처럼 호출자 책임).

    base INSERT와 3축 initial state는 ``create_feature_with_initial_state``만
    수행한다. existing row의 provider 본문 갱신은 상태 축을 전혀 건드리지 않는
    별도 UPDATE이며, provider의 retire/reingest state transition은 source evidence를
    확보한 ``load_bundle``이 뒤에서 procedure로 수행한다.

    **geometry 없는 route/area는 여기 오지 않는다** — ``Feature`` DTO가 구성
    시점에 거부한다(ADR-086). 종전 geometryless-area retirement 보정은 더 이상
    필요한 상태를 만들 수 없다.
    """
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id는 양의 정수여야 합니다.")

    params = _feature_params(feature)
    geom_wkt = cast("str | None", params.pop("geom_wkt"))
    initial_state = _provider_feature_state(feature)
    create_row = (
        await session.execute(
            text(_CREATE_FEATURE_WITH_INITIAL_STATE_SQL),
            {
                "feature_payload": _provider_feature_payload(params),
                "lifecycle_state": initial_state.lifecycle_state,
                "publication_state": initial_state.publication_state,
                "quality_state": initial_state.quality_state,
                "state_context": _provider_state_context(
                    provider_dataset_id=provider_dataset_id,
                    reason_code="provider_initial",
                    source_membership=source_membership,
                ),
            },
        )
    ).mappings().one()
    inserted = bool(create_row["o_inserted"])
    stored_feature_uuid = str(create_row["o_feature_uuid"])
    user_fenced = False
    if not inserted:
        updated = (
            await session.execute(text(_UPDATE_PROVIDER_FEATURE_CORE_SQL), params)
        ).mappings().one_or_none()
        if updated is None:
            user_fenced = True
        else:
            stored_feature_uuid = str(updated["feature_uuid"])
    verify_feature_uuid(
        feature.feature_id,
        stored_feature_uuid,
        sent_feature_uuid=params["feature_uuid"],
        inserted=inserted,
    )
    if not user_fenced:
        await _upsert_feature_subtype(
            session,
            feature,
            stored_feature_uuid=stored_feature_uuid,
            geom_wkt=geom_wkt,
        )
        # ``feature_versions.version=0``은 마지막 provider baseline이다. whole-row
        # user fence가 core/subtype write를 막은 경우 current detailed row는 user
        # effective payload이므로 provider label의 snapshot으로 다시 쓰면 안 된다.
        # 새 raw source record는 별도로 immutable 보존되며, baseline/effective
        # lineage의 재물화는 T-VN-36이 소유한다.
        await session.execute(
            text(_MATERIALIZE_PROVIDER_VERSION_SQL),
            {"feature_id": feature.feature_id},
        )
    return inserted


@dataclass(frozen=True)
class _SourceRecordUpsertState:
    inserted: bool
    became_current: bool
    provider_dataset_id: int
    source_entity_key: str
    source_record_key: str


@dataclass(frozen=True)
class _ProviderSourceMembership:
    """Provider procedure가 검증할 immutable source record membership proof."""

    source_entity_key: str
    source_record_key: str


async def _provider_source_membership_for_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    provider_dataset_id: int,
) -> _ProviderSourceMembership:
    """현재 primary source link에서 procedure proof를 fail-close로 만든다.

    snapshot tombstone/notice reconcile처럼 SourceRecord DTO를 다시 갖고 있지 않은
    provider retire 경로도 있다. 이 경우에는 연결된 entity의 current immutable
    record만 proof로 택한다. link가 없거나 다른 dataset이면 procedure 호출 자체를
    만들지 않는다.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT
                    entity.source_entity_key,
                    record.source_record_key
                FROM provider_sync.source_links AS link
                JOIN provider_sync.source_entities AS entity
                  ON entity.source_entity_key = link.source_entity_key
                JOIN provider_sync.source_entity_heads AS head
                  ON head.source_entity_key = entity.source_entity_key
                JOIN provider_sync.source_records AS record
                  ON record.source_record_key = head.current_source_record_key
                WHERE link.feature_id = :feature_id
                  AND link.source_role = 'primary'
                  AND entity.provider_dataset_id = :provider_dataset_id
                ORDER BY head.observed_at DESC, record.imported_at DESC,
                         entity.source_entity_key, record.source_record_key
                LIMIT 1
                """
            ),
            {
                "feature_id": feature_id,
                "provider_dataset_id": provider_dataset_id,
            },
        )
    ).mappings().one_or_none()
    if row is None:
        raise RuntimeError(
            "provider state transition requires a current primary source membership: "
            f"feature={feature_id!r}, dataset_id={provider_dataset_id}"
        )
    return _ProviderSourceMembership(
        source_entity_key=str(row["source_entity_key"]),
        source_record_key=str(row["source_record_key"]),
    )


async def resolve_active_provider_dataset_id(
    session: AsyncSession, *, provider: str, dataset_key: str, lock: bool = False
) -> int:
    """활성 ``provider_datasets`` 행의 대리 키를 찾는다 (T-VN-33, ADR-088).

    문자열 pair를 받는 **경계**(공개 facade·admin 입력·provider 변환)에서만 쓴다.
    내부 경로는 ``provider_dataset_id``를 그대로 들고 다닌다 — 그래야 record마다
    조회가 붙지 않는다.

    inactive이거나 seed되지 않았으면 ``LookupError``다. 조용히 NULL로 넘기면
    cutover 뒤 첫 write가 ``ck_provider_dataset_active_write``로 죽는데, 그때는
    어느 pair가 문제인지 알 수 없다.
    """
    lock_clause = "FOR SHARE" if lock else ""
    provider_dataset_id = (
        await session.execute(
            text(
                f"""
                SELECT provider_dataset_id
                FROM provider_sync.provider_datasets
                WHERE provider = :provider
                  AND dataset_key = :dataset_key
                  AND is_active
                {lock_clause}
                """
            ),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).scalar_one_or_none()
    if provider_dataset_id is None:
        raise LookupError(
            f"no active provider dataset is seeded for {provider!r}/{dataset_key!r}"
        )
    return int(provider_dataset_id)


async def _upsert_source_record_state(
    session: AsyncSession, record: SourceRecord
) -> _SourceRecordUpsertState:
    provider_dataset_id = await resolve_active_provider_dataset_id(
        session, provider=record.provider, dataset_key=record.dataset_key, lock=True
    )

    params = _source_record_params(record, provider_dataset_id=provider_dataset_id)
    await session.execute(text(_UPSERT_SOURCE_ENTITY_SQL), params)
    row = (await session.execute(text(_UPSERT_SOURCE_RECORD_SQL), params)).mappings().one()
    inserted = bool(row["inserted"])
    # conflict 경로의 DTO key는 current immutable record key와 다를 수 있다.
    # head/link writer는 항상 DB가 확정한 canonical key만 사용해야 한다.
    params["source_record_key"] = str(row["source_record_key"])
    became_current = bool(
        (
            await session.execute(text(_UPSERT_SOURCE_ENTITY_HEAD_SQL), params)
        ).scalar_one()
    )
    return _SourceRecordUpsertState(
        inserted=inserted,
        became_current=became_current,
        provider_dataset_id=provider_dataset_id,
        source_entity_key=str(params["source_entity_key"]),
        source_record_key=str(params["source_record_key"]),
    )


async def upsert_source_record(session: AsyncSession, record: SourceRecord) -> bool:
    """``provider_sync.source_records`` insert. 신규면 ``True``, 이미 있으면 ``False``.

    payload hash가 entity 안에서 유일하므로 payload 변경은 새 immutable row를 남긴다.
    재관측은 raw row를 갱신하지 않고 entity head의 ``observed_at``만 전진시킨다.
    """
    return (await _upsert_source_record_state(session, record)).inserted


@dataclass(frozen=True)
class _FeatureLoadState:
    exists: bool
    lifecycle_state: str | None
    publication_state: str | None
    quality_state: str | None
    row_revision: int | None
    has_provider_reactivation_override: bool
    data_origin: str | None = None
    data_version: int | None = None

    @property
    def provider_write_fenced(self) -> bool:
        """현재 row가 immutable user-request version인지 여부."""

        return self.data_origin == "user_request" and (self.data_version or 0) > 0


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
        lifecycle_state=row["lifecycle_state"],
        publication_state=row["publication_state"],
        quality_state=row["quality_state"],
        row_revision=(int(row["row_revision"]) if row["row_revision"] is not None else None),
        data_origin=(str(row["data_origin"]) if row["data_origin"] is not None else None),
        data_version=(int(row["data_version"]) if row["data_version"] is not None else None),
        has_provider_reactivation_override=bool(
            row["has_provider_reactivation_override"]
        ),
    )


async def upsert_source_link(session: AsyncSession, link: SourceLink) -> bool:
    """``provider_sync.source_links`` upsert. 신규 INSERT면 ``True``, 갱신이면 ``False``."""
    result = await session.execute(text(_UPSERT_SOURCE_LINK_SQL), _source_link_params(link))
    return bool(result.scalar_one())


async def _transition_provider_lifecycle_if_needed(
    session: AsyncSession,
    *,
    feature_id: str,
    desired_state: ProviderFeatureState,
    provider_dataset_id: int,
    source_membership: _ProviderSourceMembership | None,
) -> bool:
    """provider retire/reingest만 procedure로 직렬화한다.

    Provider는 publication/quality를 existing feature에서 바꾸지 않는다. retire는
    publication을 suppressed로 만들고, reingest는 현재 publication을 자동 복원하지
    않는다. active lifecycle override가 있으면 호출 전에도 피하고, procedure가
    경합 시에도 같은 fence를 재검증한다.
    """
    current = await _feature_load_state(session, feature_id)
    return await _transition_provider_lifecycle_from_state(
        session,
        feature_id=feature_id,
        desired_state=desired_state,
        provider_dataset_id=provider_dataset_id,
        source_membership=source_membership,
        current=current,
        retry_on_serialization=True,
    )


async def _transition_provider_lifecycle_from_state(
    session: AsyncSession,
    *,
    feature_id: str,
    desired_state: ProviderFeatureState,
    provider_dataset_id: int,
    source_membership: _ProviderSourceMembership | None,
    current: _FeatureLoadState,
    retry_on_serialization: bool,
) -> bool:
    """한 optimistic revision에서 provider lifecycle procedure를 실행한다."""
    if not current.exists:
        return False
    if current.provider_write_fenced:
        return False
    assert current.row_revision is not None
    assert current.publication_state is not None
    assert current.quality_state is not None

    target_lifecycle: str | None = None
    target_publication: str | None = None
    reason_code: str | None = None
    if desired_state.lifecycle_state == "retired" and current.lifecycle_state == "active":
        target_lifecycle = "retired"
        target_publication = "suppressed"
        reason_code = "provider_retire"
    elif (
        desired_state.lifecycle_state == "active"
        and current.lifecycle_state == "retired"
        and not current.has_provider_reactivation_override
    ):
        target_lifecycle = "active"
        target_publication = current.publication_state
        reason_code = "provider_reingest"
    if target_lifecycle is None or target_publication is None or reason_code is None:
        return False
    if source_membership is None:
        source_membership = await _provider_source_membership_for_feature(
            session,
            feature_id=feature_id,
            provider_dataset_id=provider_dataset_id,
        )

    params = {
        "feature_id": feature_id,
        "lifecycle_state": target_lifecycle,
        "publication_state": target_publication,
        "quality_state": current.quality_state,
        "expected_row_revision": current.row_revision,
        "state_context": _provider_state_context(
            provider_dataset_id=provider_dataset_id,
            reason_code=reason_code,
            source_membership=source_membership,
        ),
    }
    try:
        # procedure는 expected revision 불일치를 SQLSTATE 40001로 fail-close한다.
        # PostgreSQL error 뒤에도 같은 outer load transaction에서 현재 tuple을 다시
        # 읽어 한 번만 재시도하려면 procedure call을 savepoint로 감싸야 한다.
        async with session.begin_nested():
            await session.execute(text(_TRANSITION_FEATURE_STATE_SQL), params)
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        error_text = str(exc.orig)
        if (
            sqlstate == "23514"
            and (
                "ck_feature_provider_reactivation_override" in error_text
                # SQLAlchemy asyncpg adapter가 native constraint_name을 문자열에서
                # 누락시키는 경우에도, procedure의 단일 고정 violation 문구는
                # 보존한다. 같은 SQLSTATE의 다른 validation error는 삼키지 않는다.
                or "provider reactivation is fenced by lifecycle override" in error_text
            )
        ):
            # Override 작성과 provider reingest가 맞물린 경우다. procedure가 audit
            # 없는 no-op을 거부한 뒤 repository가 provider load를 정상 완료시킨다.
            return False
        if sqlstate != "40001" or not retry_on_serialization:
            raise
        refreshed = await _feature_load_state(session, feature_id)
        return await _transition_provider_lifecycle_from_state(
            session,
            feature_id=feature_id,
            desired_state=desired_state,
            provider_dataset_id=provider_dataset_id,
            source_membership=source_membership,
            current=refreshed,
            retry_on_serialization=False,
        )
    return True


async def _retire_provider_candidates(
    session: AsyncSession,
    rows: Sequence[RowMapping],
    *,
    reason_code: str,
) -> int:
    """candidate SELECT 결과를 provider retirement procedure로 전환한다."""
    retired = 0
    desired_state = ProviderFeatureState(
        lifecycle_state="retired",
        publication_state="suppressed",
        quality_state="valid",
    )
    for row in rows:
        changed = await _transition_provider_lifecycle_if_needed(
            session,
            feature_id=str(row["feature_id"]),
            desired_state=desired_state,
            provider_dataset_id=int(row["provider_dataset_id"]),
            source_membership=None,
        )
        retired += int(changed)
    return retired


async def load_bundle(session: AsyncSession, bundle: FeatureBundle) -> FeatureLoadResult:
    """``FeatureBundle`` 하나를 적재 (source_record → feature → source_link 순).

    동일 source record 재수집이면 원문은 immutable로 유지하고 entity head의 관측만
    전진시킨다. current record가 달라진 경우에만 feature 본문/version을 갱신한다.
    단, source_record만 있고 feature가 없는 비정상 상태는 생성하고, provider가
    다시 보낸 active feature가 과거 retirement 상태라면 복구한다.
    ``user_request`` feature와 provider 재활성화 방지 override는 복구하지 않는다.
    commit은 호출자 책임.
    """
    record_state = await _upsert_source_record_state(
        session, bundle.source_record
    )
    record_inserted = record_state.inserted
    feature_inserted = False
    feature_updated = False
    feature_state = await _feature_load_state(session, bundle.feature.feature_id)
    feature_missing = not feature_state.exists
    if record_state.became_current or feature_missing:
        feature_inserted = await upsert_feature(
            session,
            bundle.feature,
            provider_dataset_id=record_state.provider_dataset_id,
            source_membership=_ProviderSourceMembership(
                source_entity_key=record_state.source_entity_key,
                source_record_key=record_state.source_record_key,
            ),
        )
        feature_updated = not feature_inserted and not feature_state.provider_write_fenced
    link_inserted = await upsert_source_link(session, bundle.source_link)
    state_updated = await _transition_provider_lifecycle_if_needed(
        session,
        feature_id=bundle.feature.feature_id,
        desired_state=_provider_feature_state(bundle.feature),
        provider_dataset_id=record_state.provider_dataset_id,
        source_membership=_ProviderSourceMembership(
            source_entity_key=record_state.source_entity_key,
            source_record_key=record_state.source_record_key,
        ),
    )
    return FeatureLoadResult(
        bundles_total=1,
        features_inserted=int(feature_inserted),
        features_updated=int(feature_updated or state_updated),
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


async def retire_features_absent_from_snapshot(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    snapshot_source_entity_ids: set[str],
) -> int:
    """주어진 primary source의 feature 중 snapshot에 없는 것을 retired 전이.

    전체 snapshot 적재 후 호출 — 이번 snapshot에서 사라진(폐업/제외) feature를
    lifecycle ``retired`` + publication ``suppressed``로 전이한다 (Step A bulk,
    ADR-017 — place는 무기한 유지). 이미 retired인 feature는 건드리지 않는다.
    commit은 호출자 책임.

    Parameters
    ----------
    provider, dataset_key, source_entity_type
        대상 primary source 식별자 (예: ``python-mois-api`` /
        ``mois_license_features_bulk`` / ``license_place``).
    snapshot_source_entity_ids
        이번 snapshot에 포함된 ``source_entity_id`` 집합. 비어 있으면 해당
        source의 모든 선택 가능 feature가 retired 전이된다.

    Returns
    -------
    int
        retired 전이된 feature 수.
    """
    candidates = (
        await session.execute(
            text(_SOFT_DELETE_NOT_IN_SNAPSHOT_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "keys": sorted(snapshot_source_entity_ids),
            },
        )
    ).mappings().all()
    return await _retire_provider_candidates(
        session,
        candidates,
        reason_code="provider_snapshot_absent",
    )


async def retire_features_by_source_entity_ids(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_ids: set[str],
) -> int:
    """주어진 ``source_entity_id`` 집합에 **속하는** primary-source feature를 retired 전이.

    Step C 폐업/취소 — provider가 ``closed``/``cancelled``로 통지한 인허가에 대응하는
    feature를 lifecycle ``retired`` + publication ``suppressed``로 전이한다
    (ADR-017 — place는 무기한 유지). snapshot 부재 retirement의
    inverse (snapshot 부재분이 아니라 명시 폐업분)다. 이미 retired인 feature·집합
    밖 feature는 건드리지 않는다. 빈 집합이면 no-op(0). commit은 호출자 책임.

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
        retired 전이된 feature 수.
    """
    if not source_entity_ids:
        return 0
    candidates = (
        await session.execute(
            text(_INACTIVATE_BY_ENTITY_IDS_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "keys": sorted(source_entity_ids),
            },
        )
    ).mappings().all()
    return await _retire_provider_candidates(
        session,
        candidates,
        reason_code="provider_tombstone",
    )


async def retire_geometryless_area_features_by_source(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
) -> int:
    """provider source에 연결된 ``area`` 중 경계 geometry가 없는 feature를 retired 전이.

    기존에 좌표만 있는 record를 ``Feature.kind='area'``로 적재했던 provider를
    재정렬할 때 쓰는 one-way 보정이다. 같은 source entity가 새 ``place`` feature로
    재적재될 수 있으므로 source_entity_id 집합 기반 전환은 쓰지 않는다.
    commit은 호출자 책임.
    """
    candidates = (
        await session.execute(
            text(_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
            },
        )
    ).mappings().all()
    return await _retire_provider_candidates(
        session,
        candidates,
        reason_code="provider_invalid_geometry",
    )


# ── notice 라이프사이클 (#632 — 사건 단위 identity + 중복 정리) ─────────────

_NOTICE_SNAPSHOT_RECONCILE_LOCK_SQL: Final[str] = """
SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('kortravelmap:notice-snapshot-reconcile', 0)
)
"""

_GET_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
SELECT scope.notice_lifecycle_scope_id, scope.mode, scope.applied_at, scope.state_fingerprint
FROM provider_sync.notice_lifecycle_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.source_entity_type = :source_entity_type
"""

_INSERT_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
INSERT INTO provider_sync.notice_lifecycle_scopes (
    provider_dataset_id, source_entity_type,
    mode, applied_at, state_fingerprint
) SELECT dataset.provider_dataset_id, :source_entity_type,
    :mode, CAST(:applied_at AS timestamptz), :state_fingerprint
FROM provider_sync.provider_datasets AS dataset
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
"""

_UPDATE_NOTICE_SNAPSHOT_SCOPE_SQL: Final[str] = """
UPDATE provider_sync.notice_lifecycle_scopes
SET applied_at = CAST(:applied_at AS timestamptz),
    state_fingerprint = :state_fingerprint
FROM provider_sync.provider_datasets AS dataset
WHERE dataset.provider_dataset_id = provider_sync.notice_lifecycle_scopes.provider_dataset_id
  AND dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND provider_sync.notice_lifecycle_scopes.source_entity_type = :source_entity_type
"""

_UPSERT_NOTICE_EVENT_SCOPE_SQL: Final[str] = """
INSERT INTO provider_sync.notice_lifecycle_scopes (
    provider_dataset_id, source_entity_type,
    mode, applied_at, state_fingerprint
) SELECT dataset.provider_dataset_id, :source_entity_type,
    'event', CAST(:applied_at AS timestamptz), :state_fingerprint
FROM provider_sync.provider_datasets AS dataset
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
ON CONFLICT (provider_dataset_id, source_entity_type)
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
    lineage_sql = _notice_lineage_sql(
        "sr", entity_alias="se", dataset_alias="dataset"
    )
    return f"""
WITH known_lineages AS (
    SELECT DISTINCT {lineage_sql} AS lineage_key
    FROM provider_sync.source_entities AS se
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = se.provider_dataset_id
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = se.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = head.current_source_record_key
    WHERE dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND se.source_entity_type = :source_entity_type
    UNION
    SELECT lineage_key
    FROM provider_sync.notice_lineage_states AS state
    JOIN provider_sync.notice_lifecycle_scopes AS scope
      ON scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND scope.source_entity_type = :source_entity_type
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
    notice_lifecycle_scope_id, lineage_key, present, changed_at, valid_until
)
SELECT
    scope.notice_lifecycle_scope_id,
    desired.lineage_key, desired.present, CAST(:closed_at AS timestamptz), desired.valid_until
FROM desired
JOIN provider_sync.notice_lifecycle_scopes AS scope
  ON scope.source_entity_type = :source_entity_type
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
 AND dataset.provider = :provider
 AND dataset.dataset_key = :dataset_key
ON CONFLICT (notice_lifecycle_scope_id, lineage_key)
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
      ON state.lineage_key = incoming.lineage_key
    JOIN provider_sync.notice_lifecycle_scopes AS scope
      ON scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = scope.provider_dataset_id
    WHERE dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND scope.source_entity_type = :source_entity_type
      AND state.changed_at = incoming.changed_at
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
    notice_lifecycle_scope_id, lineage_key, present, changed_at, valid_until
)
SELECT
    scope.notice_lifecycle_scope_id,
    incoming.lineage_key, incoming.present, incoming.changed_at, incoming.valid_until
FROM incoming
JOIN provider_sync.notice_lifecycle_scopes AS scope
  ON scope.source_entity_type = :source_entity_type
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
 AND dataset.provider = :provider
 AND dataset.dataset_key = :dataset_key
ON CONFLICT (notice_lifecycle_scope_id, lineage_key)
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
  ON state.lineage_key = incoming.lineage_key
JOIN provider_sync.notice_lifecycle_scopes AS scope
  ON scope.notice_lifecycle_scope_id = state.notice_lifecycle_scope_id
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.source_entity_type = :source_entity_type
  AND incoming.present
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
    """notice 정리 SQL 2종 — 계보별 latest 아닌 feature retire 후보(+snapshot 동기화).

    ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``(read 필터)과 동일 계보/최신 판정을
    write 시점에 set 기반으로 적용한다. ``close_missing=True``면 retire 대신
    현재 feed에 없는 latest 계보를 닫고, 다시 나타난 latest 계보는 이전
    ``valid_end_time``을 지워 활성 상태로 복구한다. feature·계보별 후보는
    ``seen_at``/``source_record_key``를 따로 집계하지 않고 실제 최신 row 하나를
    선택해 read와 winner가 어긋나지 않게 한다. 호출 scope에서 밀린 feature도
    다른 provider/dataset의 primary 계보 winner라면 feature 전체를 삭제하지 않고,
    그 계보로 열린 공유 feature를 현재 scope의 snapshot 부재로 닫지 않는다. 호출
    scope 자체의 winner는 ``ranked``에서 이미 계산하므로 cross-scope 보호 CTE에서
    다시 전수 비교하지 않는다.

    ``close_missing=True``는 ``:hidden_before``(적재 이전에 안 보이던 feature_id
    배열)를 추가로 요구한다 — 같은 statement에서 읽는 상태는 이미 이번 적재가
    지나간 뒤라 "직전 가시성"을 스스로 관측할 수 없기 때문이다
    (``_hidden_notice_features``).
    """
    candidate_lifecycle = (
        """
      AND (
        f.lifecycle_state IN ('active', 'retired')
      )
"""
        if close_missing
        else "      AND f.lifecycle_state = 'active'\n"
    )
    lineage_sql = _lineage_sql("head", entity_alias="se")
    canonical_sql = _canonical_notice_feature_sql(
        "f",
        "sr",
        entity_alias="se",
        dataset_alias="dataset",
        lineage=lineage_sql,
    )
    other_lineage_sql = _lineage_sql("other_head", entity_alias="other_se")
    other_canonical_sql = _canonical_notice_feature_sql(
        "other_f",
        "other_sr",
        entity_alias="other_se",
        dataset_alias="other_dataset",
        lineage=other_lineage_sql,
    )
    lineage_cte = f"""
WITH lineage_candidates AS (
    SELECT
        f.feature_id,
        dataset.provider_dataset_id,
        {lineage_sql} AS lineage_key,
        head.observed_at AS seen_at,
        sr.source_record_key AS tiebreak,
        {canonical_sql} AS canonical_identity,
        lineage_state.present AS snapshot_present,
        lineage_state.changed_at AS snapshot_changed_at,
        lineage_state.valid_until AS snapshot_valid_until
    FROM feature.features AS f
    JOIN provider_sync.source_links AS sl
      ON sl.feature_id = f.feature_id
     AND sl.source_role = 'primary'
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = se.provider_dataset_id
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = se.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = head.current_source_record_key
    LEFT JOIN provider_sync.notice_lifecycle_scopes AS lifecycle_scope
      ON lifecycle_scope.provider_dataset_id = se.provider_dataset_id
     AND lifecycle_scope.source_entity_type = se.source_entity_type
    LEFT JOIN provider_sync.notice_lineage_states AS lineage_state
      ON lineage_state.notice_lifecycle_scope_id = lifecycle_scope.notice_lifecycle_scope_id
     AND lineage_state.lineage_key = {lineage_sql}
    WHERE f.kind = 'notice'
      AND COALESCE(f.data_origin, 'provider') <> 'user_request'
      AND dataset.provider = :provider
      AND dataset.dataset_key = :dataset_key
      AND se.source_entity_type = :source_entity_type
{candidate_lifecycle}
),
lineage AS (
    SELECT DISTINCT ON (feature_id, lineage_key)
        feature_id,
        provider_dataset_id,
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
        provider_dataset_id,
        lineage_key,
        tiebreak,
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
out_of_scope_feature_lineages AS MATERIALIZED (
    -- MATERIALIZED가 없으면 Postgres가 이 CTE를 갱신 대상 feature마다 다시
    -- 실행한다(T-VN-37 실측: 3,045 notice에서 loops=2,900 → 87.9초). 계보 승패는
    -- 질의당 한 번이면 되는 집합 연산이라 여기서 최적화 장벽을 세운다.
    SELECT DISTINCT ON (
        f.feature_id,
        dataset.provider,
        dataset.dataset_key,
        se.source_entity_type,
        {lineage_sql}
    )
        f.feature_id,
        dataset.provider,
        dataset.dataset_key,
        se.source_entity_type,
        {lineage_sql} AS lineage_key,
        head.observed_at AS seen_at,
        sr.source_record_key AS tiebreak,
        {canonical_sql} AS canonical_identity,
        lineage_state.present AS snapshot_present,
        lineage_state.changed_at AS snapshot_changed_at,
        lineage_state.valid_until AS snapshot_valid_until
    FROM scoped_feature_ids AS scoped
    JOIN feature.features AS f
      ON f.feature_id = scoped.feature_id
    JOIN provider_sync.source_links AS sl
      ON sl.feature_id = f.feature_id
     AND sl.source_role = 'primary'
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = se.provider_dataset_id
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = se.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = head.current_source_record_key
    LEFT JOIN provider_sync.notice_lifecycle_scopes AS lifecycle_scope
      ON lifecycle_scope.provider_dataset_id = se.provider_dataset_id
     AND lifecycle_scope.source_entity_type = se.source_entity_type
    LEFT JOIN provider_sync.notice_lineage_states AS lineage_state
      ON lineage_state.notice_lifecycle_scope_id = lifecycle_scope.notice_lifecycle_scope_id
     AND lineage_state.lineage_key = {lineage_sql}
    WHERE f.kind = 'notice'
      AND (
        dataset.provider <> :provider
        OR dataset.dataset_key <> :dataset_key
        OR se.source_entity_type <> :source_entity_type
      )
    ORDER BY
        f.feature_id,
        dataset.provider,
        dataset.dataset_key,
        se.source_entity_type,
        {lineage_sql},
        head.observed_at DESC,
        sr.source_record_key DESC
),
global_feature_wins AS MATERIALIZED (
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
        JOIN provider_sync.provider_datasets AS other_dataset
          ON other_dataset.provider_dataset_id = other_se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS other_head
          ON other_head.source_entity_key = other_se.source_entity_key
        JOIN provider_sync.source_records AS other_sr
          ON other_sr.source_record_key = other_head.current_source_record_key
         AND {other_lineage_sql} = current_notice.lineage_key
        JOIN provider_sync.source_links AS other_sl
          ON other_sl.source_entity_key = other_se.source_entity_key
        JOIN feature.features AS other_f
          ON other_f.feature_id = other_sl.feature_id
        WHERE other_dataset.provider = current_notice.provider
          AND other_dataset.dataset_key = current_notice.dataset_key
          AND other_se.source_entity_type = current_notice.source_entity_type
          AND other_sl.source_role = 'primary'
          AND other_f.feature_id <> current_notice.feature_id
          AND other_f.kind = 'notice'
          AND other_f.lifecycle_state = 'active'
          AND (
            other_head.observed_at > current_notice.seen_at
            OR (
              other_head.observed_at = current_notice.seen_at
              AND other_sr.source_record_key > current_notice.tiebreak
            )
            OR (
              other_head.observed_at = current_notice.seen_at
              AND other_sr.source_record_key = current_notice.tiebreak
              AND (
                (
                  {other_canonical_sql}
                  AND NOT current_notice.canonical_identity
                )
                OR (
                  {other_canonical_sql}
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
        min(provider_dataset_id) AS provider_dataset_id,
        max(tiebreak) FILTER (WHERE rn = 1) AS source_record_key,
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
        s.provider_dataset_id,
        s.source_record_key,
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
        lifecycle.provider_dataset_id,
        lifecycle.source_record_key,
        f.lifecycle_state AS old_lifecycle_state,
        n.valid_end_time AS old_valid_end_time,
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
              WHEN f.lifecycle_state = 'active'
               AND (
                   n.valid_end_time IS NULL
                   OR n.valid_end_time > CAST(:evaluated_at AS timestamptz)
               )
              THEN CASE
                WHEN n.valid_end_time IS NULL
                THEN NULL
                ELSE GREATEST(
                    lifecycle.max_present_valid_until,
                    n.valid_end_time
                )
              END
              ELSE lifecycle.max_present_valid_until
            END
            ELSE n.valid_end_time
          END
          WHEN lifecycle.has_present_winning_lineage
          THEN lifecycle.max_present_valid_until
          ELSE lifecycle.inactive_changed_at
        END AS desired_valid_end_time,
        EXISTS (
            SELECT 1
            FROM ops.feature_overrides AS fo
            WHERE fo.feature_id = f.feature_id
              AND fo.field_path = 'lifecycle_state'
              AND fo.status = 'active'
              AND fo.override_value = '"retired"'::jsonb
              AND fo.prevent_provider_reactivation
        ) AS reactivation_blocked
    FROM feature.features AS f
    JOIN feature_lifecycle AS lifecycle
      ON lifecycle.feature_id = f.feature_id
    LEFT JOIN feature.feature_notices AS n
      ON n.feature_id = f.feature_id
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
            -- 이 statement가 읽는 core/subtype 상태는 **이미 이번 적재가 지나간
            -- 뒤**다. 같은 계보가 다시 나타나면 bundle 적재가 notice subtype을
            -- 통째로 다시 써서(``valid_end_time = EXCLUDED.valid_end_time``,
            -- KREX DTO는 NULL) 닫혀 있던 feature가 여기 도달하기 전에 이미
            -- 열린다. 그러면 "직전에 안 보였다"가 관측 불가라 재등장 집계가
            -- 구조적으로 항상 0이 된다(실측: 적재 전 valid_end=03:20 → 적재 후
            -- NULL → reconcile 반환행 0건). 그래서 **적재 이전** 가시성은
            -- 호출자가 재어 ``:hidden_before``로 넘긴다 — 적재가 없는 경로
            -- (close/supersede)는 빈 배열이라 종전 판정 그대로다.
            NOT (desired.feature_id = ANY(CAST(:hidden_before AS text[])))
            AND desired.old_lifecycle_state = 'active'
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
                    target.old_lifecycle_state = 'active'
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
-- T-VN-35(ADR-086): 효력 종료 시각의 정본은 ``feature_notices.valid_end_time``
-- (timestamptz)이다. lifecycle 전이는 procedure 호출자가 처리하고, 시각 갱신은
-- 같은 문장의 data-modifying CTE가 typed 컬럼에 직접 쓴다 — 종전
-- ``jsonb_set(detail, '{valid_end_time}', to_jsonb(text))`` 왕복(문자열화 →
-- 재파싱)이 사라진다. CTE는 **한 statement·한 snapshot**으로 notice 후보와 시각을
-- 함께 확정한다. 마지막 SELECT는 outcome CTE만 읽지만 data-modifying CTE는
-- 참조 여부와 무관하게 항상 완주하므로(PostgreSQL 계약) notice 갱신이 누락되지
-- 않고, subtype 행이 없는 feature도 RETURNING 집계에서 빠지지 않는다.
--
-- 미래 발효 공고가 발효 전에 feed에서 사라지면 ``valid_end_time``(철회시각)이
-- ``valid_start_time``보다 이르다 — "발효 전 철회"라는 정당한 상태이므로 0085는
-- 순서 CHECK를 두지 않는다(KREX notice ETL에서 실측). read 필터는
-- ``valid_end_time <= now()``라 이 공고는 즉시 숨겨진다.
, lifecycle_outcomes AS (
    SELECT
        target.feature_id,
        target.provider_dataset_id,
        target.source_record_key,
        target.desired_valid_end_time,
        target.should_activate
          AND target.old_lifecycle_state = 'retired' AS reactivate,
        (NOT target.was_visible AND target.will_be_visible) AS reopened,
        (target.was_visible AND NOT target.will_be_visible) AS closed
    FROM lifecycle_changes AS target
    WHERE (
          target.old_valid_end_time
            IS DISTINCT FROM target.desired_valid_end_time
          OR (
              target.should_activate
              AND target.old_lifecycle_state = 'retired'
          )
          -- 적재가 먼저 되살린 재등장은 여기 도달했을 때 core/subtype이 이미
          -- 최종 상태다(갱신할 컬럼이 없다). 그래도 RETURNING에 실어야 재등장
          -- 집계가 잡히므로 전이 자체를 갱신 조건에 포함한다. ``was_visible``이
          -- ``:hidden_before``로 고정되는 경로에서만 참이 되므로, 적재가 이미
          -- 손댄 행 외에는 추가 갱신이 생기지 않는다.
          OR (
              NOT target.was_visible
              AND target.will_be_visible
          )
      )
), notice_update AS (
    UPDATE feature.feature_notices AS n
    SET valid_end_time = lifecycle_outcomes.desired_valid_end_time
    FROM lifecycle_outcomes
    WHERE n.feature_id = lifecycle_outcomes.feature_id
      AND n.valid_end_time IS DISTINCT FROM lifecycle_outcomes.desired_valid_end_time
    RETURNING n.feature_id
)
SELECT feature_id, provider_dataset_id, source_record_key, reactivate, reopened, closed
FROM lifecycle_outcomes
"""
        )
    return (
        lineage_cte
        + """
, feature_rank AS (
    SELECT
        feature_id,
        min(provider_dataset_id) AS provider_dataset_id,
        bool_or(rn = 1) AS wins_any_lineage,
        bool_or(rn > 1) AS loses_any_lineage
    FROM ranked
    GROUP BY feature_id
)
SELECT r.feature_id, r.provider_dataset_id
FROM feature_rank AS r
JOIN feature.features AS f
  ON f.feature_id = r.feature_id
LEFT JOIN global_feature_wins AS global_wins
  ON global_wins.feature_id = r.feature_id
WHERE r.loses_any_lineage
  AND NOT r.wins_any_lineage
  AND NOT COALESCE(global_wins.wins_any_lineage, false)
  AND f.lifecycle_state = 'active'
"""
    )


# 적재 **이전** 가시성 관측 — ``was_visible``의 정본 입력.
#
# ``_supersede_stale_notice_sql(close_missing=True)``의 판정과 글자 그대로 같은
# 술어의 부정이다(lifecycle_state/valid_end_time + 같은 ``evaluated_at``).
# subtype 행이 아직 없는 신규 feature는 LEFT JOIN으로 ``valid_end_time IS NULL``
# 이 되지만 features 행 자체가 없으므로 결과에 들어오지 않는다 — 처음 적재되는
# 공고를 "재등장"으로 세지 않기 위해 필요한 성질이다.
_HIDDEN_NOTICE_FEATURES_SQL: Final[str] = """
SELECT f.feature_id
FROM feature.features AS f
LEFT JOIN feature.feature_notices AS n
  ON n.feature_id = f.feature_id
WHERE f.feature_id = ANY(CAST(:feature_ids AS text[]))
  AND NOT (
      f.lifecycle_state = 'active'
      AND (
          n.valid_end_time IS NULL
          OR n.valid_end_time > CAST(:evaluated_at AS timestamptz)
      )
  )
"""


async def _hidden_notice_features(
    session: AsyncSession,
    *,
    feature_ids: Collection[str],
    evaluated_at: datetime,
) -> frozenset[str]:
    """``feature_ids`` 중 지금 시점에 **보이지 않는** feature 집합."""
    if not feature_ids:
        return frozenset()
    rows = await session.execute(
        text(_HIDDEN_NOTICE_FEATURES_SQL),
        {
            "feature_ids": sorted(set(feature_ids)),
            "evaluated_at": evaluated_at,
        },
    )
    return frozenset(str(row.feature_id) for row in rows)


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
    # 적재는 notice subtype을 통째로 다시 쓰므로(``valid_end_time``까지) 닫혀
    # 있던 feature가 여기서 이미 열린다. lifecycle 판정이 "직전에 안 보였다"를
    # 잃지 않도록 적재 **이전**에 재고, 같은 시각 기준을 lifecycle에도 넘긴다.
    evaluated_at = datetime.now(UTC)
    hidden_before = await _hidden_notice_features(
        session,
        feature_ids=[bundle.feature.feature_id for bundle in bundles],
        evaluated_at=evaluated_at,
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
        evaluated_at=evaluated_at,
        hidden_before=hidden_before,
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
    # snapshot 경로와 같은 이유로 적재 이전 가시성을 먼저 잰다.
    hidden_before = await _hidden_notice_features(
        session,
        feature_ids=[bundle.feature.feature_id for bundle in active_bundles],
        evaluated_at=materialized_at,
    )
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
        hidden_before=hidden_before,
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
       latest(최근 확인 시각) 1개만 남기고 나머지를 lifecycle retire한다. identity 스킴 변경으로
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
    hidden_before: Collection[str] = (),
) -> NoticeReconcileResult:
    """영속 lineage state로 scope의 dedup과 Feature lifecycle을 재계산한다.

    ``hidden_before``는 **이번 적재 이전에** 보이지 않던 feature_id다. 이 함수가
    읽는 상태는 적재가 지나간 뒤라 재등장 feature가 이미 열려 있으므로, 적재를
    앞세우는 호출자(``load_*_notice_*``)는 ``_hidden_notice_features``로 잰 값을
    반드시 넘겨야 재등장/종료 집계가 맞는다. 적재가 없는 호출자는 생략한다.
    """
    lifecycle_evaluated_at = evaluated_at or datetime.now(UTC)
    result = await session.execute(
        text(_supersede_stale_notice_sql(close_missing=False)),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
        },
    )
    superseded = await _retire_provider_candidates(
        session,
        result.mappings().all(),
        reason_code="provider_notice_superseded",
    )
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
                "hidden_before": sorted(set(hidden_before)),
            },
        )
        snapshot_updates = result.mappings().all()
        for row in snapshot_updates:
            if not bool(row["reactivate"]):
                continue
            await _transition_provider_lifecycle_if_needed(
                session,
                feature_id=str(row["feature_id"]),
                desired_state=ProviderFeatureState(
                    lifecycle_state="active",
                    publication_state="published",
                    quality_state="valid",
                ),
                provider_dataset_id=int(row["provider_dataset_id"]),
                source_membership=None,
            )
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
            superseded += await _retire_provider_candidates(
                session,
                result.mappings().all(),
                reason_code="provider_notice_superseded",
            )
    return NoticeReconcileResult(
        superseded=superseded,
        closed=closed,
        reopened=reopened,
    )


# 만료 notice purge (docs/etl/notice-feature-etl.md §9) — 종료일(없으면 발표일)
# +1년 지난 notice를 retired/suppressed 전이. maintenance job에서 주기 실행(#632).
#
# T-VN-35D(ADR-086): 효력 기간을 typed 컬럼에서 읽는다. ``kind = 'notice'`` 술어도
# 따로 걸지 않는다 — ``feature_notices`` 조인 자체가 kind 필터다(kind 상수 CHECK +
# ``(feature_id, kind)`` FK). 종전에는 free-form ``detail`` 문자열을 무방비로
# CAST해서, 파싱 불가 값 한 행이면 purge job 전체가 실패했다.
_PURGE_EXPIRED_NOTICES_SQL: Final[str] = """
SELECT DISTINCT ON (f.feature_id)
    f.feature_id,
    entity.provider_dataset_id
FROM feature.features AS f
JOIN feature.feature_notices AS n
  ON n.feature_id = f.feature_id
JOIN provider_sync.source_links AS link
  ON link.feature_id = f.feature_id
 AND link.source_role = 'primary'
JOIN provider_sync.source_entities AS entity
  ON entity.source_entity_key = link.source_entity_key
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = entity.provider_dataset_id
 AND dataset.is_active
WHERE f.lifecycle_state = 'active'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND COALESCE(n.valid_end_time, n.valid_start_time)
      < now() - CAST(CAST(:retention AS text) AS interval)
ORDER BY f.feature_id, entity.provider_dataset_id
"""


async def purge_expired_notices(session: AsyncSession, *, retention: str = "1 year") -> int:
    """보존 기간이 지난 notice를 retired/suppressed 전이한다 (§9 보관 정책, #632).

    ``valid_end_time``(없으면 ``valid_start_time``) + ``retention`` 경과분.
    commit은 호출자 책임.
    """
    result = await session.execute(
        text(_PURGE_EXPIRED_NOTICES_SQL), {"retention": retention}
    )
    return await _retire_provider_candidates(
        session,
        result.mappings().all(),
        reason_code="provider_notice_retention_expired",
    )


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
    raw read** — retired/suppressed feature도 세 상태축과 함께 반환한다(단건
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

    공개 API 단건 상세가 사용한다. public view 밖(비공개 publication 또는
    quarantined quality, retired lifecycle) row는 존재하지 않는 것으로 취급되어
    ``None``을 반환한다 — 공개 술어는 VIEW(alembic 0096) 한 곳에만 정의되어 있고
    여기서 재구현하지 않는다(F-1 재발 방지).
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
        feature_uuid = row.get("feature_uuid")
        batch.append(
            FeatureBatchItemRow(
                feature_id=str(row["feature_id"]),
                state=cast(FeatureBatchItemState, state),
                row_revision=revision,
                trip_card=trip_card,
                feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
            )
        )
    return tuple(batch)


async def public_active_notice_feature_identities(
    session: AsyncSession,
    feature_ids: Sequence[str],
) -> dict[str, str]:
    """public에서 노출 가능한 active/latest notice의 ``{feature_id: feature_uuid}``.

    notice lineage read의 T-VN-32B dual 표면 — 같은 감산 술어를 쓰되 feature
    참조를 legacy id와 UUID 정본 쌍으로 병행 반환한다. 목록·검색·nearby와 같은
    ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``을 공유해 종료된 notice와 같은 계보의
    구버전 feature가 ID 직접 조회로 다시 노출되지 않게 한다. 일반
    ``get_feature_row(s)``는 admin/감사용 raw read 계약을 유지한다.
    """
    normalized = _normalized_filter(feature_ids)
    if normalized is None:
        return {}
    result = await session.execute(
        text(_PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL),
        {"feature_ids": normalized},
    )
    return {str(row.feature_id): str(row.feature_uuid) for row in result}


_LIST_ACTIVE_PLACE_COORDS_SQL: Final[str] = """
SELECT
    feature_id,
    x_extension.ST_X(coord) AS lon,
    x_extension.ST_Y(coord) AS lat
FROM feature.features
WHERE kind = 'place'
  AND lifecycle_state = 'active'
  AND quality_state = 'valid'
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
    se.source_entity_id,
    f.feature_id,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat
FROM feature.features f
JOIN provider_sync.source_links sl
  ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
JOIN provider_sync.source_entities se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets dataset
  ON dataset.provider_dataset_id = se.provider_dataset_id
WHERE f.lifecycle_state = 'active'
  AND f.quality_state = 'valid'
  AND f.kind = 'place'
  AND f.coord IS NOT NULL
  AND dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
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


# T-VN-35(ADR-086): 전화번호 정본은 ``feature_places.phones``(text[])다.
# ``feature_places`` 조인이 곧 ``kind = 'place'`` 필터이며, "번호 없음"은
# jsonb 배열 길이가 아니라 배열 기수로 판정한다.
_FIND_PLACE_NO_PHONE_SQL: Final[str] = """
SELECT f.feature_id, f.name, f.address, se.source_entity_id
FROM feature.features f
JOIN feature.feature_places p
  ON p.feature_id = f.feature_id
JOIN provider_sync.source_links sl
  ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
JOIN provider_sync.source_entities se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets dataset
  ON dataset.provider_dataset_id = se.provider_dataset_id
WHERE f.lifecycle_state = 'active'
  AND f.quality_state = 'valid'
  AND dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND se.source_entity_type = :source_entity_type
  AND cardinality(p.phones) = 0
ORDER BY f.feature_id
LIMIT :limit
"""

# phones 쓰기는 subtype 한 곳이고, core는 표시 캐시 무효화용 ``updated_at``만
# 따라 움직인다(한 statement — 두 CTE는 같은 snapshot). place subtype 행이 없으면
# 아무것도 쓰지 않고 ``False``를 돌려준다(종전에는 kind와 무관하게 detail에
# ``phones``를 밀어넣을 수 있었다).
_SET_FEATURE_PHONES_SQL: Final[str] = """
WITH place AS (
    UPDATE feature.feature_places AS p
    SET phones = ARRAY(SELECT jsonb_array_elements_text(CAST(:phones AS jsonb)))
    WHERE p.feature_id = :feature_id
    RETURNING p.feature_id
), core AS (
    UPDATE feature.features AS f
    SET updated_at = now()
    FROM place
    WHERE f.feature_id = place.feature_id
    RETURNING f.feature_id
)
SELECT feature_id FROM place
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
    ``feature_places.phones``가 빈 배열인 feature를 반환한다(`feature_id`/`name`/
    `address`/`source_entity_id`). 외부 phone lookup(kakao/naver/google)은 호출자
    책임(ADR-006).
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
    """place feature의 ``feature_places.phones`` 배열을 통째로 교체. 갱신되면 ``True``.

    phone enrichment가 정규화·dedup·max3을 적용한 최종 배열을 넘긴다. place가 아닌
    feature(또는 subtype 행이 없는 feature)는 아무것도 쓰지 않고 ``False``.
    commit은 호출자 책임.
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
    (active lifecycle + published publication + valid quality)이 결정한다. ``kinds``가
    ``None``이면 전체 kind. DTO 매핑은 상위(client) 책임 — 본 repo는 raw row만.

    **``include_geometry``는 직렬화(serialization)만 제어한다** (F-8 / ADR-073 D-9-3):
    후보 술어는 두 변형이 **동일**하다 — point ``coord``가 bbox에 들거나 route/area
    ``geom``이 bbox와 exact ``ST_Intersects``하면 후보다(``include_geometry`` 무관).
    ``include_geometry=true``이면 그 후보 중 route/area의 GeoJSON geometry + 면적을
    응답 payload에 **추가로 직렬화**할 뿐, 반환되는 feature id 집합(membership)은
    바꾸지 않는다. ``providers``가 주어지면 primary source
    provider 기준(``source_role = 'primary'``)으로 추가 필터한다
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
    CAST(f.feature_uuid AS text) AS feature_uuid,
    f.kind,
    f.name,
    f.category,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.marker_icon,
    f.marker_color
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
    feature_uuid = row.get("feature_uuid")
    return FeatureSearchRow(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        score=float(score) if score is not None else None,
        score_cursor=str(score_cursor) if score_cursor is not None else None,
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
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
    feature_uuid = row.get("feature_uuid")
    return NearbyFeatureRow(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        lon=float(row["lon"]),
        lat=float(row["lat"]),
        distance_m=float(row["distance_m"]),
        primary_provider=row["primary_provider"],
        primary_dataset_key=row["primary_dataset_key"],
        last_updated_at=row["last_updated_at"],
        feature_uuid=str(feature_uuid) if feature_uuid is not None else None,
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
    providers: Sequence[str] | None = None,
    sort: str = "distance",
    limit: int = 100,
    cursor: str | None = None,
) -> NearbyFeaturePage:
    """POI/cache target 주변 feature summary를 keyset cursor로 조회한다.

    ADR-012: 반경 술어는 target과 feature의 STORED ``coord_5179`` 컬럼에 직접
    적용한다. 입력 좌표 변환이나 ``ST_Transform``은 WHERE 술어에 두지 않는다.

    공개 read이므로 ADR-067 ``feature.public_features`` projection 안에서만
    조회한다.
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
    조회한다.
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
    분포를 합쳐 보여주기 위한 집계. 공개 표면이므로 active/published/valid 이외의
    3축 tuple은 집계에 포함하지 않는다. 카탈로그에 없는(미지정/legacy) category
    code도 그대로 반환하므로 호출자가 카탈로그와 교차한다.
    """
    rows = (await session.execute(text(_CATEGORY_FEATURE_COUNTS_SQL))).all()
    return {str(row[0]): int(row[1]) for row in rows}
