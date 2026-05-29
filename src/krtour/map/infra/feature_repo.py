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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.dto import Feature, FeatureBundle, SourceLink, SourceRecord

__all__ = [
    "FeatureLoadResult",
    "upsert_feature",
    "upsert_source_record",
    "upsert_source_link",
    "load_bundle",
    "load_bundles",
    "get_feature_row",
]


# ─── SQL 상수 (EXPLAIN 검증 대상, test-strategy §4.2) ────────────────────────

# coord_5179는 STORED generated (ADR-012) — INSERT 컬럼에서 제외.
_UPSERT_FEATURE_SQL: Final[str] = """
INSERT INTO feature.features (
    feature_id, kind, name, category,
    coord,
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
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at,
    deleted_at = EXCLUDED.deleted_at
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
    x_extension.ST_SRID(coord_5179) AS coord_5179_srid,
    address, detail, urls, raw_refs,
    legal_dong_code, sido_code, sigungu_code,
    marker_icon, marker_color, status,
    parent_feature_id, sibling_group_id,
    created_at, updated_at, deleted_at
FROM feature.features
WHERE feature_id = :feature_id
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
        r = await load_bundle(session, bundle)
        total = FeatureLoadResult(
            bundles_total=total.bundles_total + r.bundles_total,
            features_inserted=total.features_inserted + r.features_inserted,
            features_updated=total.features_updated + r.features_updated,
            source_records_inserted=(
                total.source_records_inserted + r.source_records_inserted
            ),
            source_links_inserted=total.source_links_inserted + r.source_links_inserted,
            source_links_updated=total.source_links_updated + r.source_links_updated,
        )
    return total


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
