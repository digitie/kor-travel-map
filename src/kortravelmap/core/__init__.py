"""``kortravelmap.core`` — 순수 함수 + 도메인 룰 + 예외 계층.

``core/``는 비즈니스 로직만 (Protocol 의존). DB/HTTP/외부 client 의존 없음.
``infra/``/``providers/``는 core를 import하지만 그 반대는 금지 (ADR-002 의존
방향).

**Sprint 1 PR#19**: ``types.py`` — ``KST``/``kst_now`` (ADR-019).
**Sprint 1 PR#20 (본 PR)**: ``exceptions`` 7종 (ADR backend-package §5) +
``ids.py`` ``make_feature_id`` (ADR-009 결정적 SHA1).
**Sprint 1 PR#21+**: ``ids.py``의 나머지 helper (``make_source_record_key`` /
``make_payload_hash``), ``scoring`` (ADR-016 Coordinate 의존), ``protocols``,
``providers`` (provider 이름 정규화), ``weather`` (build_weather_card),
``infra/crs.py`` (pyproj.Transformer ADR-030 narrow cache).
**Sprint 3 PR (T-201a)**: ``integrity.py`` — F1~F3 (orphan source / detail
누락 / CRS drift).

ADR 참조
--------
- ADR-002 — async-only API (sync 인터페이스 추가 금지)
- ADR-009 — ``feature_id`` 결정적 생성 (``make_feature_id``)
- ADR-016 — Record Linkage 가중치 0.45·name + 0.35·spatial + 0.20·category,
  임계값 0.85/0.65
- ADR-019 — KST aware datetime (``kst_now``)
- ADR-030 — ``functools.cache`` narrow 예외
- ADR-033 — ``feature_consistency_reports`` Phase 1 (F1~F3, Sprint 3)
"""

from __future__ import annotations

from kortravelmap.core.address import (
    BjdParts,
    extract_sido_code,
    extract_sigungu_code,
    is_valid_bjd_code,
    normalize_bjd_code,
    normalize_korean_text,
    normalize_phone_number,
    parse_bjd_code,
)
from kortravelmap.core.exceptions import (
    DuplicateFeatureError,
    FeatureNotFoundError,
    FileStoreError,
    ImportJobConflictError,
    KorTravelMapError,
    ProviderError,
    SourceRecordNotFoundError,
    ValidationError,
)
from kortravelmap.core.geometry import (
    AREA_GEOMETRY_TYPES,
    ROUTE_GEOMETRY_TYPES,
    GeometryError,
    geometry_centroid,
    normalize_geometry,
    parse_wkt,
)
from kortravelmap.core.ids import (
    FEATURE_ID_HASH_LENGTH,
    PAYLOAD_HASH_DEFAULT_LENGTH,
    PRICE_VALUE_KEY_HASH_LENGTH,
    SOURCE_RECORD_KEY_HASH_LENGTH,
    WEATHER_VALUE_KEY_HASH_LENGTH,
    make_feature_id,
    make_payload_hash,
    make_price_value_key,
    make_source_record_key,
    make_weather_value_key,
)
from kortravelmap.core.providers import (
    CANONICAL_PROVIDER_NAMES,
    PROVIDER_ALIASES,
    is_known_provider,
    normalize_provider_name,
)
from kortravelmap.core.scoring import (
    SPATIAL_DECAY_METERS,
    THRESHOLD_AUTO,
    THRESHOLD_MANUAL,
    WEIGHT_CATEGORY,
    WEIGHT_NAME,
    WEIGHT_SPATIAL,
    DedupDecision,
    category_similarity,
    classify_decision,
    haversine_meters,
    name_similarity,
    normalize_kr_place_name,
    score_pair,
    spatial_similarity,
)
from kortravelmap.core.types import KST, kst_now
from kortravelmap.core.weather import (
    filter_by_provider,
    group_by_metric_key,
    latest_by_metric_key,
    pick_nowcast_value,
    pick_timeline_slice,
)

__all__ = [
    # types (PR#19, ADR-019)
    "KST",
    "kst_now",
    # exceptions (PR#20, docs/architecture/backend-package.md §5)
    "KorTravelMapError",
    "ValidationError",
    "FeatureNotFoundError",
    "SourceRecordNotFoundError",
    "DuplicateFeatureError",
    "ImportJobConflictError",
    "ProviderError",
    "FileStoreError",
    # ids (PR#20 ADR-009 / PR#26 source key + payload hash / PR#38 weather /
    # PR#42 price)
    "make_feature_id",
    "make_source_record_key",
    "make_payload_hash",
    "make_weather_value_key",
    "make_price_value_key",
    "FEATURE_ID_HASH_LENGTH",
    "SOURCE_RECORD_KEY_HASH_LENGTH",
    "PAYLOAD_HASH_DEFAULT_LENGTH",
    "WEATHER_VALUE_KEY_HASH_LENGTH",
    "PRICE_VALUE_KEY_HASH_LENGTH",
    # providers (PR#29, ADR-024/028)
    "CANONICAL_PROVIDER_NAMES",
    "PROVIDER_ALIASES",
    "normalize_provider_name",
    "is_known_provider",
    # scoring (PR#29, ADR-016 Record Linkage)
    "WEIGHT_NAME",
    "WEIGHT_SPATIAL",
    "WEIGHT_CATEGORY",
    "THRESHOLD_AUTO",
    "THRESHOLD_MANUAL",
    "SPATIAL_DECAY_METERS",
    "normalize_kr_place_name",
    "name_similarity",
    "spatial_similarity",
    "category_similarity",
    "score_pair",
    "haversine_meters",
    "DedupDecision",
    "classify_decision",
    # address (PR#37, ADR-041 — python-kraddr-base 흡수)
    "BjdParts",
    "normalize_bjd_code",
    "is_valid_bjd_code",
    "parse_bjd_code",
    "extract_sigungu_code",
    "extract_sido_code",
    "normalize_phone_number",
    "normalize_korean_text",
    # weather pure helpers (PR#39, ADR-010)
    "pick_nowcast_value",
    "pick_timeline_slice",
    "group_by_metric_key",
    "filter_by_provider",
    "latest_by_metric_key",
    # geometry (route/area WKT, ADR-012)
    "ROUTE_GEOMETRY_TYPES",
    "AREA_GEOMETRY_TYPES",
    "GeometryError",
    "parse_wkt",
    "geometry_centroid",
    "normalize_geometry",
]
