"""``kortravelmap.api.routers.features`` — feature 조회 API (``/features``).

적재된 feature를 운영자/frontend 지도가 조회한다 (ADR-035 운영 범위). 쿼리는
``kortravelmap.infra.feature_repo``의 raw SQL(ADR-004) — 본 라우터는 HTTP 표면 +
DTO 매핑만, SQL 미보유.

엔드포인트:
- ``GET /features`` — bbox 안 feature 경량 표현 list (지도 뷰포트 로드).
- ``GET /features/in-bounds`` — user용 bbox envelope 응답.
- ``GET /features/search`` — user용 이름/bbox 검색.
- ``GET /features/{feature_id}`` — feature 단건 상세.
- ``POST /features/batch`` — N+1 방지 batch 상세(service read, ServiceToken).
- ``POST /features/weather/batch`` — bitemporal weather batch(service read, ServiceToken).

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo``)
- ADR-005 + ADR-035 — public API key/service token + 네트워크 경계 보호.
  본 라우터는 ``/features`` prefix.
- ADR-012 — bbox/좌표는 4326, GIST 인덱스 사용 (술어에 ST_Transform 없음)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, Literal, assert_never

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from kortravelmap.core.exceptions import (
    FeatureSearchCursorError,
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)
from kortravelmap.core.sync_scope import MAX_EXTERNAL_SYSTEM_NAME_LENGTH
from kortravelmap.infra import (
    curation_repo,
    feature_identity,
    feature_repo,
    observation_repo,
    price_repo,
    weather_repo,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    get_poi_cache_target_by_key,
)
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    model_validator,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_admin_frontend, require_service_token
from kortravelmap.api.db import get_session
from kortravelmap.api.feature_ref import resolve_feature_ref_or_error
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.identity_projection import response_feature_id, uuid_substituted_row
from kortravelmap.api.response import ClusterUnit, Meta, ProblemDetail, make_meta
from kortravelmap.api.routers.curations import (
    PublicCurationItemView,
    curation_item_response_feature_id,
)
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "FeatureSummary",
    "FeaturesInBboxResponse",
    "FeaturesInBoundsResponse",
    "FeatureDetailResponse",
    "FeatureDetailEnvelopeResponse",
    "FeatureBatchRequest",
    "FeatureBatchResponse",
    "WeatherBatchRequest",
    "WeatherBatchResponse",
    "FeatureSearchResponse",
    "FeatureSearchProblem",
    "FeatureSourcesResponse",
    "FeaturesNearbyByTargetResponse",
]

# T-VN-05 (ADR-073 / D-9-1 · F-3): 공개 read에서 제거하는 provider raw 경계.
# ``detail.payload``는 kind-discriminated typed DTO의 자유형 provider passthrough라
# (예: MOIS PlaceDetail.payload의 mng_no/status_code/detail_status_*/opn_authority_code
# /epsg5174) 공개 표면에 노출하지 않는다. DB 컬럼·ETL은 건드리지 않고 **공개 read
# projection에서만** 벗겨낸다. raw observation lineage(raw_data/raw_payload_hash/
# source_record_key)는 operator 표면으로 이동한다.
_PUBLIC_DETAIL_STRIPPED_KEYS: frozenset[str] = frozenset({"payload"})


router = APIRouter(prefix="/features", tags=["features"])
NearbySort = Literal["distance", "name", "last_updated_at"]


def _search_cursor_signing_key(request: Request) -> bytes:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, ApiSettings):
        raise RuntimeError("ApiSettings is not configured on the application")
    return settings.cursor_signing_key


def _search_cursor_http_error(exc: FeatureSearchCursorError) -> HTTPException:
    if isinstance(exc, FeatureSearchCursorVersionUnsupportedError):
        code = "FEATURE_SEARCH_CURSOR_VERSION_UNSUPPORTED"
        message = "지원하지 않는 feature search cursor version입니다."
    elif isinstance(exc, FeatureSearchCursorTamperedError):
        code = "FEATURE_SEARCH_CURSOR_TAMPERED"
        message = "Feature search cursor 무결성 검증에 실패했습니다."
    elif isinstance(exc, FeatureSearchCursorQueryMismatchError):
        code = "CURSOR_QUERY_MISMATCH"
        message = "Feature search cursor가 현재 검색 조건과 일치하지 않습니다."
    elif isinstance(exc, FeatureSearchCursorInvalidError):
        code = "FEATURE_SEARCH_CURSOR_INVALID"
        message = "Feature search cursor 형식이 올바르지 않습니다."
    else:
        code = "FEATURE_SEARCH_CURSOR_INVALID"
        message = "Feature search cursor를 사용할 수 없습니다."
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code, "message": message, "details": {}},
    )


# ── 응답 schema ────────────────────────────────────────────────────────


class PricePointOut(BaseModel):
    """provider/price_domain/product series의 가격 관측 1건."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    price_domain: str
    product_key: str
    product_name: str | None = None
    source_product_key: str | None = None
    source_product_name: str | None = None
    value_number: float
    unit: str
    observed_at: datetime


class WeatherSummaryOut(BaseModel):
    """지도 marker용 weather 값 요약."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    weather_domain: str | None = None
    forecast_style: str | None = None
    metric_key: str
    metric_name: str | None = None
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    observed_at: datetime | None = None


class FeatureSummary(BaseModel):
    """지도/목록용 경량 feature 표현 (bbox 조회 결과 1건)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        description=(
            "feature 참조 (opaque string). T-VN-32C 값 전환 이후 UUID 정본 "
            "문자열을 담는다 — 형식(legacy f_*/UUID)에 의존하지 말 것."
        ),
    )
    feature_uuid: str | None = Field(
        default=None,
        description=(
            "UUID 정본 identity 명시 필드 (ADR-068). T-VN-32C 이후 "
            "feature_id와 같은 값이다."
        ),
    )
    kind: str
    name: str
    category: str
    lon: float | None = Field(description="경도 (WGS84). coord 없으면 null.")
    lat: float | None = Field(description="위도 (WGS84).")
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str
    geometry: dict[str, Any] | None = Field(
        default=None,
        description="include_geometry=true일 때 route/area용 GeoJSON geometry.",
    )
    area_square_meters: float | None = Field(
        default=None,
        description="include_geometry=true이고 kind=area일 때 면적(m²).",
    )
    price_summary: list[PricePointOut] | None = Field(
        default=None,
        description="kind=price일 때 provider/domain/product series별 최신 가격 요약.",
    )
    weather_summary: WeatherSummaryOut | None = Field(
        default=None,
        description="kind=weather일 때 현재/예보 marker 요약.",
    )


class FeaturesInBboxData(BaseModel):
    """``GET /features`` data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureSummary]


class FeaturesInBboxResponse(BaseModel):
    """``GET /features`` 응답 — bbox 안 feature 목록."""

    model_config = ConfigDict(extra="forbid")

    data: FeaturesInBboxData
    meta: Meta


class FeatureObservationView(BaseModel):
    """한 제공기관 entity의 현재 또는 과거 payload 관측값."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    source_entity_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    first_seen_at: datetime
    entity_last_seen_at: datetime
    source_record_key: str
    raw_data: dict[str, Any]
    raw_payload_hash: str
    fetched_at: datetime
    imported_at: datetime
    observed_at: datetime
    expires_at: datetime | None
    source_role: str
    match_method: str
    confidence: int
    linked_at: datetime
    is_current: bool


class FeatureDetailResponse(BaseModel):
    """feature 단건 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        description=(
            "feature 참조 (opaque string). T-VN-32C 값 전환 이후 UUID 정본 "
            "문자열을 담는다 — 형식(legacy f_*/UUID)에 의존하지 말 것."
        ),
    )
    feature_uuid: str | None = Field(
        default=None,
        description=(
            "UUID 정본 identity 명시 필드 (ADR-068). T-VN-32C 이후 "
            "feature_id와 같은 값이다."
        ),
    )
    kind: str
    name: str
    category: str
    lon: float | None = None
    lat: float | None = None
    area_square_meters: float | None = Field(
        default=None,
        description="kind=area이고 geometry가 있으면 면적(m²).",
    )
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str
    row_revision: int = Field(
        ge=1,
        description="server-owned feature revision. ETag과 같은 값이다.",
    )
    updated_at: datetime
    curations: list[PublicCurationItemView] = Field(
        default_factory=list,
        description="이 Feature가 속한 공개 큐레이션 membership 전부.",
    )
    # T-VN-05: raw observation lineage는 공개 detail에서 제거하고 operator 표면
    # (``GET /features/{id}/sources``·observation history)으로 이동했다.


class FeatureSourcesData(BaseModel):
    """``GET /features/{feature_id}/sources`` data payload (operator, raw lineage)."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    observations: list[FeatureObservationView]


class FeatureSourcesResponse(BaseModel):
    """``GET /features/{feature_id}/sources`` 응답 (operator 전용 raw lineage)."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureSourcesData
    meta: Meta


class FeatureObservationHistoryData(BaseModel):
    """provider entity별 immutable payload history data."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureObservationView]


class FeatureObservationHistoryResponse(BaseModel):
    """관측 payload history cursor 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureObservationHistoryData
    meta: Meta


InBoundsMode = Literal["items", "clusters"]

# cluster drill-down 순서 (ADR-073 D-9-2). 각 rollup 단위에서 한 단계 더 확대(zoom-in)
# 할 때 소비자가 다음에 요청할 단위. ``eupmyeondong``의 다음은 개별 feature(items)이므로
# ``None``이다. cluster_key(행정코드) + 이 단위로 결정적(deterministic) drill-down이 된다.
_CLUSTER_DRILL_DOWN: dict[ClusterUnit, ClusterUnit | None] = {
    "sido": "sigungu",
    "sigungu": "eupmyeondong",
    "eupmyeondong": None,
}


class ClusterSummary(BaseModel):
    """행정구역 rollup 클러스터 1건 (T-213c)."""

    model_config = ConfigDict(extra="forbid")

    cluster_key: str
    feature_count: int
    lon: float
    lat: float


class InBoundsCoverage(BaseModel):
    """in-bounds 응답 완결성 기술자 (F-8 silent truncation 해소, ADR-073 D-9-2).

    ``returned``는 이 응답에 실린 항목 수(items 또는 clusters), ``limit``은 이 조회에
    적용된 ``max_items`` 상한이다. ``returned == limit`` 이고 상위 ``truncated`` 가
    참이면 경계 안에 더 많은 후보가 있으니 소비자는 zoom-in(cluster drill-down)하거나
    더 좁은 bbox로 다시 조회해야 한다.
    """

    model_config = ConfigDict(extra="forbid")

    returned: int
    limit: int


class PublicFeatureListData(BaseModel):
    """public feature 목록 data payload (ADR-073 D-9-2 지도 완결성 계약).

    ``mode``가 ``items``면 개별 feature(``items``), ``clusters``면 행정구역
    rollup(``clusters``)을 채운다(T-213c). ``truncated``는 결과가 ``max_items``
    상한에서 잘렸는지를 **명시**한다(F-8: silent truncation 해소). cluster 모드는
    결정적 ``cluster_key``(행정코드)를 노출한다. payload 해석용
    ``cluster_unit``/``drill_down_unit``은 envelope 불변식에 따라 ``meta.cluster``에
    일원화한다.
    """

    model_config = ConfigDict(extra="forbid")

    mode: InBoundsMode
    items: list[FeatureSummary] = []
    clusters: list[ClusterSummary] = []
    truncated: bool = Field(
        description="결과가 max_items 상한에서 잘렸으면 true(더 많은 후보 존재).",
    )
    coverage: InBoundsCoverage


class FeaturesInBoundsResponse(BaseModel):
    """``GET /features/in-bounds`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicFeatureListData
    meta: Meta


class FeatureDetailEnvelopeResponse(BaseModel):
    """``GET /features/{feature_id}`` public envelope 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureDetailResponse
    meta: Meta


class PriceCardData(BaseModel):
    """``GET /features/{feature_id}/price`` data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    asof: datetime | None = None
    current: list[PricePointOut] = Field(
        description="provider/price_domain/product series별 최신 관측 1건."
    )
    history: list[PricePointOut] = Field(
        description="series를 합쳐 observed_at 내림차순으로 자른 최근 관측."
    )
    latest_at: datetime | None = None
    is_stale: bool


class FeaturePriceResponse(BaseModel):
    """``GET /features/{feature_id}/price`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PriceCardData
    meta: Meta


_POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
_PostgresBigintRevision = Annotated[
    int,
    Field(ge=1, le=_POSTGRES_BIGINT_MAX),
    WithJsonSchema(
        {
            "type": "integer",
            "format": "int64",
            "minimum": 1,
        }
    ),
]


class FeatureBatchRequestItem(BaseModel):
    """feature batch 요청 1건."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(min_length=1)
    known_row_revision: _PostgresBigintRevision | None = Field(
        default=None,
        description=(
            "소비자가 보유한 trip_card의 PostgreSQL bigint row_revision"
            "(최대 9223372036854775807). 일치하면 unchanged."
        ),
    )


class FeatureBatchRequest(BaseModel):
    """5-state feature batch 조회 요청 (service read)."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureBatchRequestItem] = Field(min_length=1, max_length=200)
    projection: Literal["trip_card"] = Field(
        default="trip_card",
        description="서버 정의 고정 projection. raw/detail projection은 선택할 수 없다.",
    )

    @model_validator(mode="after")
    def feature_ids_must_be_unique(self) -> FeatureBatchRequest:
        feature_ids = [item.feature_id for item in self.items]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("items의 feature_id는 중복될 수 없습니다.")
        return self


class FeatureTripCard(BaseModel):
    """여행 일정 POI 표시에 필요한 공개-안전 고정 projection."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    marker_icon: str | None
    marker_color: str | None


_FeatureUuidField = Field(
    default=None,
    description="UUID 정본 identity 병행 노출 (ADR-068, T-VN-32B additive).",
)


class FeatureBatchFoundItem(BaseModel):
    """공개 feature의 최신 trip_card."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["found"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField
    row_revision: _PostgresBigintRevision
    trip_card: FeatureTripCard


class FeatureBatchRetiredItem(BaseModel):
    """lifecycle tombstone이 확인된 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["retired"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField
    row_revision: _PostgresBigintRevision


class FeatureBatchSuppressedItem(BaseModel):
    """존재하지만 현재 공개 projection에 없는 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["suppressed"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField
    row_revision: _PostgresBigintRevision


class FeatureBatchMissingItem(BaseModel):
    """저장소에 존재하지 않는 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["missing"]
    feature_id: str


class FeatureBatchUnchangedItem(BaseModel):
    """소비자 revision과 동일한 공개 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["unchanged"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField
    row_revision: _PostgresBigintRevision


FeatureBatchItem = Annotated[
    FeatureBatchFoundItem
    | FeatureBatchRetiredItem
    | FeatureBatchSuppressedItem
    | FeatureBatchMissingItem
    | FeatureBatchUnchangedItem,
    Field(discriminator="state"),
]


class FeatureBatchData(BaseModel):
    """feature batch 5-state data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureBatchItem]


class FeatureBatchResponse(BaseModel):
    """``POST /features/batch`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureBatchData
    meta: Meta


class FeatureSearchData(BaseModel):
    """사용자 feature 검색 data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureSummary]


class FeatureSearchResponse(BaseModel):
    """``GET /features/search`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureSearchData
    meta: Meta


FeatureSearchErrorCode = Literal[
    "VALIDATION_ERROR",
    "FEATURE_SEARCH_CURSOR_INVALID",
    "FEATURE_SEARCH_CURSOR_VERSION_UNSUPPORTED",
    "FEATURE_SEARCH_CURSOR_TAMPERED",
    "CURSOR_QUERY_MISMATCH",
]


class FeatureSearchProblem(ProblemDetail):
    """Feature search request/cursor typed RFC7807 422."""

    code: FeatureSearchErrorCode


class AreaContainedFeaturesData(BaseModel):
    """``GET /features/{feature_id}/contained-features`` data payload."""

    model_config = ConfigDict(extra="forbid")

    area_feature_id: str
    area_square_meters: float | None = None
    items: list[FeatureSummary]


class AreaContainedFeaturesResponse(BaseModel):
    """area feature 안에 포함된 point feature 목록 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AreaContainedFeaturesData
    meta: Meta


class NearbyTargetSummary(BaseModel):
    """주변 조회 기준 public target summary."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    target_key: str
    lon: float
    lat: float


class NearbyFeatureSummary(BaseModel):
    """POI/cache target 주변 public feature summary."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    feature_uuid: str | None = Field(
        default=None,
        description="UUID 정본 identity 병행 노출 (ADR-068, T-VN-32B additive).",
    )
    kind: str
    name: str
    category: str
    status: str
    lon: float
    lat: float
    distance_m: float


class FeaturesNearbyByTargetData(BaseModel):
    """``GET /features/nearby/by-target`` data payload."""

    model_config = ConfigDict(extra="forbid")

    target: NearbyTargetSummary
    items: list[NearbyFeatureSummary]


class FeaturesNearbyByTargetResponse(BaseModel):
    """``GET /features/nearby/by-target`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeaturesNearbyByTargetData
    meta: Meta


class NearbyOriginSummary(BaseModel):
    """좌표 기준 주변 조회 origin summary (입력 echo, T-213b)."""

    model_config = ConfigDict(extra="forbid")

    lon: float
    lat: float
    radius_m: float


class FeaturesNearbyData(BaseModel):
    """``GET /features/nearby`` data payload."""

    model_config = ConfigDict(extra="forbid")

    origin: NearbyOriginSummary
    items: list[NearbyFeatureSummary]


class FeaturesNearbyResponse(BaseModel):
    """``GET /features/nearby`` 응답 (좌표 중심 반경)."""

    model_config = ConfigDict(extra="forbid")

    data: FeaturesNearbyData
    meta: Meta


def _nearby_target(target: PoiCacheTarget) -> NearbyTargetSummary:
    return NearbyTargetSummary(
        external_system=target.external_system,
        target_key=target.target_key,
        lon=target.lon,
        lat=target.lat,
    )


def _resolve_cluster_unit(cluster_unit: ClusterUnit | None, zoom: int | None) -> ClusterUnit | None:
    """명시 ``cluster_unit``이 우선. 없으면 ``zoom``으로 유도(T-213c).

    zoom ≤7=sido / ≤10=sigungu / ≤13=eupmyeondong / ≥14=개별 feature(None).
    """
    if cluster_unit is not None:
        return cluster_unit
    if zoom is None:
        return None
    if zoom <= 7:
        return "sido"
    if zoom <= 10:
        return "sigungu"
    if zoom <= 13:
        return "eupmyeondong"
    return None


def _public_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """공개 detail projection — provider raw passthrough(``payload``)를 벗겨낸다.

    T-VN-05: kind-discriminated typed DTO의 공개-안전 필드만 남기고, 자유형
    provider raw subset(MOIS ``payload`` 등)은 공개 표면에서 제외한다. DB 컬럼과
    ETL이 쓰는 값은 그대로 두고 **읽기 projection에서만** 제거한다.
    """
    return {key: value for key, value in detail.items() if key not in _PUBLIC_DETAIL_STRIPPED_KEYS}


def _detail_from_row(row: dict[str, Any]) -> FeatureDetailResponse:
    # T-VN-32C PR-2 — 응답 feature_id 값은 UUID 정본. 내부 키는 호출부가 치환
    # 전 row의 legacy 값을 쓴다.
    return FeatureDetailResponse(
        feature_id=response_feature_id(row),
        feature_uuid=row.get("feature_uuid"),
        kind=row["kind"],
        name=row["name"],
        category=row["category"],
        lon=row["lon"],
        lat=row["lat"],
        area_square_meters=row.get("area_square_meters"),
        address=row["address"],
        detail=_public_detail(row["detail"]),
        urls=row["urls"],
        legal_dong_code=row["legal_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        status=row["status"],
        row_revision=row["row_revision"],
        updated_at=row["updated_at"],
    )


def _wellformed_refs(refs: Sequence[str]) -> list[str]:
    """형식 계약을 통과하는 참조만 남긴다 — batch per-item 격리용 (리뷰 M1).

    형식 위반(공백 패딩/길이 초과) 참조는 해석 대상에서 빠져 원문 그대로
    조회에 흘러가고, 종전과 동일하게 해당 item만 missing/no_data가 된다.
    """
    valid: list[str] = []
    for ref in refs:
        try:
            feature_identity.validate_feature_ref(ref)
        except feature_identity.FeatureIdentityRefError:
            continue
        valid.append(ref)
    return valid


def _batch_item_from_row(
    row: feature_repo.FeatureBatchItemRow,
    *,
    echo_feature_id: str | None = None,
) -> FeatureBatchItem:
    # T-VN-32C — batch item feature_id는 **요청 표기 echo**다. 조회는 경계
    # 해석된 legacy 키로 하되, 응답 키는 소비자(PinVi)가 보낸 문자열을
    # 그대로 되돌린다(identity_projection 모듈 docstring의 echo 예외).
    feature_id = echo_feature_id if echo_feature_id is not None else row.feature_id
    if row.state == "missing":
        return FeatureBatchMissingItem(state="missing", feature_id=feature_id)
    if row.row_revision is None:
        raise RuntimeError(f"{row.state} batch item has no row_revision")
    if row.state == "found":
        if row.trip_card is None:
            raise RuntimeError("found batch item has no trip_card")
        # trip_card.feature_id도 item echo와 정렬한다 — PinVi가
        # `trip_card.feature_id == item.feature_id` 등식을 런타임 강제하므로
        # (kor_travel_map.py _decode_feature_trip_card) legacy 잔존 시 UUID
        # 참조 요청이 계약 오류로 파손된다 (적대 리뷰 F1).
        trip_card = dict(row.trip_card)
        trip_card["feature_id"] = feature_id
        return FeatureBatchFoundItem(
            state="found",
            feature_id=feature_id,
            feature_uuid=row.feature_uuid,
            row_revision=row.row_revision,
            trip_card=FeatureTripCard.model_validate(trip_card),
        )
    if row.state == "retired":
        return FeatureBatchRetiredItem(
            state="retired",
            feature_id=feature_id,
            feature_uuid=row.feature_uuid,
            row_revision=row.row_revision,
        )
    if row.state == "suppressed":
        return FeatureBatchSuppressedItem(
            state="suppressed",
            feature_id=feature_id,
            feature_uuid=row.feature_uuid,
            row_revision=row.row_revision,
        )
    if row.state == "unchanged":
        return FeatureBatchUnchangedItem(
            state="unchanged",
            feature_id=feature_id,
            feature_uuid=row.feature_uuid,
            row_revision=row.row_revision,
        )
    assert_never(row.state)


async def _public_feature_row(
    session: AsyncSession,
    feature_id: str,
) -> dict[str, Any] | None:
    """공개 feature row 1건 — ADR-067 단일 공개 projection + notice 계보 조건.

    공개 여부 술어는 ``feature.public_features`` VIEW(alembic 0059) 한 곳에만
    있고 본 라우터는 재구현하지 않는다(F-1 재발 방지). notice는 추가로
    active/latest 계보 조건(``public_active_notice_feature_identities`` —
    T-VN-32B dual: legacy id·UUID 정본 쌍 반환)을 통과해야 한다. 비공개면
    ``None``.
    """
    row = await feature_repo.get_public_feature_row(session, feature_id)
    if row is None:
        return None
    if row.get("kind") != "notice":
        return row
    visible_identities = await feature_repo.public_active_notice_feature_identities(
        session,
        [str(row["feature_id"])],
    )
    if str(row["feature_id"]) not in visible_identities:
        return None
    return row


async def _public_feature_row_or_404(
    session: AsyncSession,
    feature_id: str,
    *,
    display_ref: str | None = None,
) -> dict[str, Any]:
    """공개 row 조회 또는 404. ``display_ref``는 404 메시지에 노출할 원본 참조.

    T-VN-32B 경계 해석 뒤 내부 전달은 정본 키(``feature_id``)로 하되, 오류
    메시지는 소비자가 보낸 참조 문자열을 그대로 되돌려준다.
    """
    row = await _public_feature_row(session, feature_id)
    if row is None:
        shown = display_ref if display_ref is not None else feature_id
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {shown!r}",
        )
    return row




def _curation_item_view(row: curation_repo.CurationItem) -> PublicCurationItemView:
    # T-VN-32C PR-2 — curations.py 공개 표면과 같은 뷰 모델: feature 참조를
    # UUID 정본으로 통일해 상세/목록 혼합 포맷을 막는다 (원자 릴리스 게이트).
    view = PublicCurationItemView.model_validate(row, from_attributes=True)
    return view.model_copy(update={"feature_id": curation_item_response_feature_id(row)})


def _observation_view(
    row: observation_repo.FeatureObservation,
) -> FeatureObservationView:
    return FeatureObservationView.model_validate(row, from_attributes=True)


def _price_point_out(point: price_repo.PricePoint) -> PricePointOut:
    return PricePointOut(
        provider=point.provider,
        price_domain=point.price_domain,
        product_key=point.product_key,
        product_name=point.product_name,
        source_product_key=point.source_product_key,
        source_product_name=point.source_product_name,
        value_number=float(point.value_number),
        unit=point.unit,
        observed_at=point.observed_at,
    )


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=FeaturesInBboxResponse,
    summary="bbox 안 feature 목록 (지도 뷰포트)",
    description=(
        "주어진 경계 상자(WGS84) 안의 feature 경량 표현 list. ``coord``의 GIST "
        "인덱스를 사용하는 공간 조회 (ADR-012). ``kind`` 반복 파라미터로 종류 "
        "필터 (예: ``?kind=place&kind=event``). 공개 feature만 반환한다 "
        "(ADR-067 ``public_features`` projection — 비공개/삭제 feature 제외)."
    ),
)
async def list_features_in_bbox(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float, Query(description="bbox 최소 경도 (WGS84).")],
    min_lat: Annotated[float, Query(description="bbox 최소 위도.")],
    max_lon: Annotated[float, Query(description="bbox 최대 경도.")],
    max_lat: Annotated[float, Query(description="bbox 최대 위도.")],
    kind: Annotated[
        list[str] | None,
        Query(description="feature kind 필터 (반복 가능). 미지정 시 전체."),
    ] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 필터 (반복 가능). 미지정 시 전체."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(
            description=(
                "primary provider(소스) 필터 (반복 가능). 미지정 시 전체. "
                "source_role='primary' 기준."
            ),
        ),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=500, description="페이지 크기.")] = 100,
    cursor: Annotated[str | None, Query()] = None,
    include_geometry: Annotated[
        bool,
        Query(description="route/area 지도 표시용 GeoJSON geometry 포함 여부."),
    ] = False,
) -> FeaturesInBboxResponse:
    started_at = perf_counter()
    if min_lon > max_lon or min_lat > max_lat:
        # 422 (Unprocessable) — starlette 버전별 상수명 변경 회피 위해 정수 리터럴.
        raise HTTPException(
            status_code=422,
            detail="bbox min 좌표가 max보다 큽니다 (min_lon≤max_lon, min_lat≤max_lat).",
        )
    try:
        rows = await feature_repo.features_in_bbox(
            session,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            kinds=kind,
            categories=category,
            providers=provider,
            limit=page_size + 1,
            cursor=cursor,
            include_geometry=include_geometry,
            # 지도에서는 오래된 가격도 숨기지 않고 observed_at과 함께 내려 UI가
            # KST 날짜 기준으로 명확히 "과거" 표시한다. 값 은폐는 갱신 장애를
            # 다시 보이지 않게 만들므로 price card의 current 지평선과 분리한다.
            price_stale_hide_days=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    page_rows = rows[:page_size]
    # cursor는 치환 전 legacy feature_id 축 — keyset 술어와 같은 축이어야 한다.
    next_cursor = (
        feature_repo.encode_bbox_cursor(page_rows[-1]["feature_id"])
        if len(rows) > page_size and page_rows
        else None
    )
    items = [FeatureSummary(**uuid_substituted_row(row)) for row in page_rows]
    return FeaturesInBboxResponse(
        data=FeaturesInBboxData(items=items),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=next_cursor,
        ),
    )


@router.get(
    "/in-bounds",
    response_model=FeaturesInBoundsResponse,
    summary="bbox 안 feature 목록 (public envelope)",
)
async def list_public_features_in_bounds(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float, Query(description="bbox 최소 경도 (WGS84).")],
    min_lat: Annotated[float, Query(description="bbox 최소 위도.")],
    max_lon: Annotated[float, Query(description="bbox 최대 경도.")],
    max_lat: Annotated[float, Query(description="bbox 최대 위도.")],
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(
            description=(
                "primary provider(소스) 반복 필터. 개별 feature 응답과 클러스터 "
                "rollup 응답 모두에 적용된다(미지정 시 술어 단락 — bbox 인덱스 조회 "
                "무영향)."
            ),
        ),
    ] = None,
    zoom: Annotated[int | None, Query(ge=0, le=24)] = None,
    cluster_unit: Annotated[
        ClusterUnit | None,
        Query(description="행정구역 rollup 단위. 미지정 시 zoom으로 유도."),
    ] = None,
    max_items: Annotated[int, Query(ge=1, le=2000)] = 1000,
    include_geometry: Annotated[
        bool,
        Query(
            description=(
                "route/area 지도 표시용 GeoJSON geometry 포함 여부. 개별 feature "
                "응답(non-clustered)에만 적용되며, cluster_unit이 해석되면(zoom으로 "
                "유도 포함) 클러스터 응답에는 무시된다."
            )
        ),
    ] = False,
) -> FeaturesInBoundsResponse:
    started_at = perf_counter()
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(
            status_code=422,
            detail="bbox min 좌표가 max보다 큽니다 (min_lon≤max_lon, min_lat≤max_lat).",
        )
    resolved_unit = _resolve_cluster_unit(cluster_unit, zoom)
    if resolved_unit is not None:
        # max_items+1을 요청해 상한 초과 여부(truncated)를 명시적으로 판정한다
        # (F-8: silent truncation 해소). 초과분은 결정적 ORDER BY(feature_count
        # DESC, cluster_key)로 잘라 상위 max_items개만 남긴다.
        clusters_raw = await feature_repo.cluster_features_in_bbox(
            session,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            cluster_unit=resolved_unit,
            kinds=kind,
            categories=category,
            providers=provider,
            limit=max_items + 1,
        )
        truncated = len(clusters_raw) > max_items
        clusters = [ClusterSummary(**c) for c in clusters_raw[:max_items]]
        return FeaturesInBoundsResponse(
            data=PublicFeatureListData(
                mode="clusters",
                items=[],
                clusters=clusters,
                truncated=truncated,
                coverage=InBoundsCoverage(returned=len(clusters), limit=max_items),
            ),
            meta=make_meta(
                request,
                started_at=started_at,
                cluster_unit=resolved_unit,
                cluster_drill_down_unit=_CLUSTER_DRILL_DOWN[resolved_unit],
            ),
        )
    # items 모드도 max_items+1로 truncated를 판정한다. include_geometry는
    # membership을 바꾸지 않고 geometry 직렬화만 제어한다(F-8 / ADR-073 D-9-3).
    rows = await feature_repo.features_in_bbox(
        session,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        kinds=kind,
        categories=category,
        providers=provider,
        limit=max_items + 1,
        include_geometry=include_geometry,
        price_stale_hide_days=None,
    )
    truncated = len(rows) > max_items
    items = [FeatureSummary(**uuid_substituted_row(row)) for row in rows[:max_items]]
    return FeaturesInBoundsResponse(
        data=PublicFeatureListData(
            mode="items",
            items=items,
            truncated=truncated,
            coverage=InBoundsCoverage(returned=len(items), limit=max_items),
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/search",
    response_model=FeatureSearchResponse,
    summary="feature 검색 (이름 trgm + bbox)",
    responses={
        422: {
            "model": FeatureSearchProblem,
            "description": "검색 범위 또는 typed cursor 오류",
        }
    },
)
async def search_public_features(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(description="name pg_trgm 검색어.")] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    min_lon: Annotated[float | None, Query(description="bbox 최소 경도 (WGS84).")] = None,
    min_lat: Annotated[float | None, Query(description="bbox 최소 위도.")] = None,
    max_lon: Annotated[float | None, Query(description="bbox 최대 경도.")] = None,
    max_lat: Annotated[float | None, Query(description="bbox 최대 위도.")] = None,
    page_size: Annotated[int, Query(ge=1, le=200, description="페이지 크기.")] = 50,
    cursor: Annotated[str | None, Query()] = None,
    include_total: Annotated[bool, Query()] = False,
) -> FeatureSearchResponse:
    started_at = perf_counter()
    bbox_parts = (min_lon, min_lat, max_lon, max_lat)
    none_count = sum(1 for p in bbox_parts if p is None)
    if none_count not in (0, 4):
        raise HTTPException(
            status_code=422,
            detail="bbox는 min_lon/min_lat/max_lon/max_lat 4개를 모두 지정해야 합니다.",
        )
    bbox: tuple[float, float, float, float] | None = None
    if min_lon is not None and min_lat is not None and max_lon is not None and max_lat is not None:
        bbox = (min_lon, min_lat, max_lon, max_lat)
    try:
        page = await feature_repo.search_features(
            session,
            q=q,
            bbox=bbox,
            kinds=kind,
            categories=category,
            page_size=page_size,
            cursor=cursor,
            include_total=include_total,
            cursor_signing_key=_search_cursor_signing_key(request),
        )
    except FeatureSearchCursorError as exc:
        raise _search_cursor_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        FeatureSummary(
            feature_id=response_feature_id(item),
            feature_uuid=item.feature_uuid,
            kind=item.kind,
            name=item.name,
            category=item.category,
            lon=item.lon,
            lat=item.lat,
            marker_icon=item.marker_icon,
            marker_color=item.marker_color,
            status=item.status,
        )
        for item in page.items
    ]
    return FeatureSearchResponse(
        data=FeatureSearchData(
            items=items,
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
            total=page.total_count,
        ),
    )


@router.get(
    "/nearby",
    response_model=FeaturesNearbyResponse,
    summary="좌표 중심 반경 주변 feature 목록",
    responses={422: {"description": "cursor/sort/radius/좌표 오류"}},
)
async def list_features_nearby(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    lon: Annotated[float, Query(ge=-180, le=180, description="중심 경도(4326).")],
    lat: Annotated[float, Query(ge=-90, le=90, description="중심 위도(4326).")],
    radius_m: Annotated[
        float,
        Query(gt=0, le=100000, description="반경(m). 최대 100km."),
    ],
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    feature_status: Annotated[
        list[str] | None,
        Query(
            alias="status",
            description=(
                "feature status 반복 필터. 기본 active. 공개 projection"
                "(feature.public_features)과 교집합으로만 동작하므로 active 외"
                " 값은 빈 결과를 반환한다 (T-VN-04; 파라미터 정리는 T-VN-11/34)."
            ),
        ),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터."),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
    sort: Annotated[NearbySort, Query()] = "distance",
) -> FeaturesNearbyResponse:
    started_at = perf_counter()
    try:
        page = await feature_repo.features_nearby(
            session,
            lon=lon,
            lat=lat,
            radius_m=radius_m,
            kinds=kind,
            categories=category,
            statuses=feature_status if feature_status is not None else ("active",),
            providers=provider,
            sort=sort,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        NearbyFeatureSummary(
            feature_id=response_feature_id(item),
            feature_uuid=item.feature_uuid,
            kind=item.kind,
            name=item.name,
            category=item.category,
            status=item.status,
            lon=item.lon,
            lat=item.lat,
            distance_m=item.distance_m,
        )
        for item in page.items
    ]
    return FeaturesNearbyResponse(
        data=FeaturesNearbyData(
            origin=NearbyOriginSummary(lon=lon, lat=lat, radius_m=radius_m),
            items=items,
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/nearby/by-target",
    response_model=FeaturesNearbyByTargetResponse,
    summary="외부 POI/cache target key 기준 주변 feature 목록",
    responses={
        404: {"description": "target 없음"},
        422: {"description": "cursor/sort/radius 오류"},
    },
)
async def list_features_nearby_by_target(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    external_system: Annotated[
        str,
        Query(
            min_length=1,
            max_length=MAX_EXTERNAL_SYSTEM_NAME_LENGTH,
            description="외부 시스템 이름. 예: external-app",
        ),
    ],
    target_key: Annotated[str, Query(description="외부 POI 고유 key.")],
    radius_km: Annotated[
        float | None,
        Query(gt=0, le=100, description="미지정 시 target 기본 radius 사용."),
    ] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    feature_status: Annotated[
        list[str] | None,
        Query(
            alias="status",
            description=(
                "feature status 반복 필터. 기본 active. 공개 projection"
                "(feature.public_features)과 교집합으로만 동작하므로 active 외"
                " 값은 빈 결과를 반환한다 (T-VN-04; 파라미터 정리는 T-VN-11/34)."
            ),
        ),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터."),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
    sort: Annotated[NearbySort, Query()] = "distance",
) -> FeaturesNearbyByTargetResponse:
    started_at = perf_counter()
    target = await get_poi_cache_target_by_key(
        session,
        external_system=external_system,
        target_key=target_key,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
        )
    try:
        page = await feature_repo.features_nearby_poi_cache_target(
            session,
            target_id=target.target_id,
            radius_km=radius_km,
            kinds=kind,
            categories=category,
            statuses=feature_status if feature_status is not None else ("active",),
            providers=provider,
            sort=sort,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        NearbyFeatureSummary(
            feature_id=response_feature_id(item),
            feature_uuid=item.feature_uuid,
            kind=item.kind,
            name=item.name,
            category=item.category,
            status=item.status,
            lon=item.lon,
            lat=item.lat,
            distance_m=item.distance_m,
        )
        for item in page.items
    ]
    return FeaturesNearbyByTargetResponse(
        data=FeaturesNearbyByTargetData(
            target=_nearby_target(target),
            items=items,
        ),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{feature_id}",
    response_model=FeatureDetailEnvelopeResponse,
    summary="feature 단건 상세",
    description=(
        "feature 참조는 legacy `f_*` id와 UUID 정본(canonical hyphenated) "
        "양쪽을 수용한다 (ADR-068 경계 alias 해석, T-VN-32B dual). 응답의 "
        "`feature_id` 값은 UUID 정본이다 (T-VN-32C 값 전환). `feature_uuid`는 "
        "같은 값의 명시 필드로 병행 노출된다. feature_id는 opaque string이며 "
        "형식(legacy/UUID)에 의존하지 말 것."
    ),
    responses={
        404: {"description": "feature 참조 해석 불가 또는 비공개"},
        304: {"description": "If-None-Match row_revision 일치 (본문 없음)"},
        422: {
            "description": (
                "feature 참조 형식 오류(빈 문자열/공백 패딩/길이 초과) 또는 "
                "If-None-Match가 canonical strong ETag가 아님"
            )
        },
        200: {
            "headers": {
                "ETag": {
                    "description": "현재 feature row_revision strong entity tag.",
                    "schema": {"type": "string"},
                }
            }
        },
    },
)
async def get_feature(
    request: Request,
    response: Response,
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureDetailEnvelopeResponse | Response:
    started_at = perf_counter()
    # T-VN-32B 경계 alias 해석 — legacy/UUID 참조를 정본 키 쌍으로 해석하고,
    # 이후 내부 조회·조인은 해석된 키로만 한다 (ADR-068 결정 3).
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    row = await _public_feature_row_or_404(
        session, canonical_id, display_ref=feature_id
    )
    revision = int(row["row_revision"])
    expected = parse_revision_header(
        request,
        "If-None-Match",
        required=False,
    )
    etag = revision_etag(revision)
    if expected == revision:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    curations = await curation_repo.list_curation_items_by_feature_ids(
        session, feature_ids=[canonical_id], public_only=True
    )
    detail = _detail_from_row(row).model_copy(
        update={
            "feature_uuid": identity.feature_uuid,
            "curations": [
                _curation_item_view(item) for item in curations.get(canonical_id, ())
            ],
        }
    )
    response.headers["ETag"] = etag
    return FeatureDetailEnvelopeResponse(
        data=detail,
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/sources",
    response_model=FeatureSourcesResponse,
    summary="feature 제공기관 raw 관측 lineage (operator)",
    dependencies=[Depends(require_admin_frontend)],
    responses={404: {"description": "feature 없음"}},
)
async def get_feature_sources(
    request: Request,
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureSourcesResponse:
    """operator 전용 — feature에 연결된 모든 제공기관 entity의 현재 raw 관측값.

    T-VN-05: raw lineage(raw_data/raw_payload_hash/source_record_key)는 공개 detail에서
    제거하고 이 operator 표면으로 이동했다. 비공개/종료 feature도 감사 대상이다 —
    경계 해석(T-VN-32B) 성공이 raw row 존재를 함의하므로 별도 존재 확인이 없다.
    """
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    observations = await observation_repo.get_current_observations(session, canonical_id)
    return FeatureSourcesResponse(
        data=FeatureSourcesData(
            feature_id=canonical_id,
            observations=[_observation_view(item) for item in observations],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/observations/{source_entity_key}/history",
    response_model=FeatureObservationHistoryResponse,
    summary="feature 제공기관 payload 관측 이력 (operator)",
    dependencies=[Depends(require_admin_frontend)],
    responses={
        404: {"description": "feature 또는 observation 없음"},
        422: {"description": "cursor 또는 page_size 오류"},
    },
)
async def get_feature_observation_history(
    request: Request,
    feature_id: str,
    source_entity_key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> FeatureObservationHistoryResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    try:
        page = await observation_repo.get_observation_history(
            session,
            feature_id=identity.feature_id,
            source_entity_key=source_entity_key,
            cursor=cursor,
            limit=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not page.items and cursor is None:
        raise HTTPException(status_code=404, detail="feature observation 없음")
    return FeatureObservationHistoryResponse(
        data=FeatureObservationHistoryData(items=[_observation_view(item) for item in page.items]),
        meta=make_meta(
            request,
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


class WeatherMetricOut(BaseModel):
    """weather card metric 1건 (forecast_style × metric_key 최신값, T-213e)."""

    model_config = ConfigDict(extra="forbid")

    forecast_style: str
    metric_key: str
    metric_name: str | None = None
    timeline_bucket: str | None = None
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    severity: str | None = None
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    provider: str | None = None
    weather_domain: str | None = None


def _weather_metric_out(metric: weather_repo.WeatherMetric) -> WeatherMetricOut:
    return WeatherMetricOut(
        forecast_style=metric.forecast_style,
        metric_key=metric.metric_key,
        metric_name=metric.metric_name,
        timeline_bucket=metric.timeline_bucket,
        value_number=(float(metric.value_number) if metric.value_number is not None else None),
        value_text=metric.value_text,
        unit=metric.unit,
        severity=metric.severity,
        issued_at=metric.issued_at,
        valid_at=metric.valid_at,
        valid_from=metric.valid_from,
        valid_until=metric.valid_until,
        observed_at=metric.observed_at,
        effective_at=metric.effective_at,
        provider=metric.provider,
        weather_domain=metric.weather_domain,
    )


class WeatherCardData(BaseModel):
    """``GET /features/{feature_id}/weather`` data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    asof: datetime | None = None
    source_styles: list[str]
    metrics: list[WeatherMetricOut]
    latest_at: datetime | None = None
    is_stale: bool


class FeatureWeatherResponse(BaseModel):
    """``GET /features/{feature_id}/weather`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: WeatherCardData
    meta: Meta


def _weather_target_at_within_timeline(value: datetime) -> datetime:
    try:
        value + timedelta(days=weather_repo.WEATHER_BATCH_TIMELINE_DAYS)
    except OverflowError as exc:
        raise ValueError(
            "weather target 시각은 timeline 지평선을 계산할 수 있어야 합니다."
        ) from exc
    return value


_WeatherTargetAt = Annotated[
    AwareDatetime,
    AfterValidator(_weather_target_at_within_timeline),
]


class WeatherBatchTargetRequest(BaseModel):
    """한 시각에 실제로 필요한 Feature ID 집합."""

    model_config = ConfigDict(extra="forbid")

    target_at: _WeatherTargetAt = Field(
        description="예보·관측이 설명해야 하는 시각(UTC offset 필수)."
    )
    feature_ids: list[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=weather_repo.WEATHER_BATCH_MAX_FEATURE_ID_LENGTH,
            ),
        ]
    ] = Field(
        min_length=1,
        max_length=weather_repo.WEATHER_BATCH_MAX_FEATURE_IDS_PER_TARGET,
        json_schema_extra={"uniqueItems": True},
    )

    @model_validator(mode="after")
    def feature_ids_must_be_unique(self) -> WeatherBatchTargetRequest:
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("target의 feature_ids는 중복될 수 없습니다.")
        return self


class WeatherBatchRequest(BaseModel):
    """여러 시각을 한 snapshot statement로 읽는 sparse weather 요청."""

    model_config = ConfigDict(extra="forbid")

    targets: list[WeatherBatchTargetRequest] = Field(
        min_length=1,
        max_length=weather_repo.WEATHER_BATCH_MAX_TARGETS,
        description=(
            "target_at 오름차순 group. 전체 target×feature pair는 "
            f"{weather_repo.WEATHER_BATCH_MAX_PAIRS}개 이하이고, "
            "pairs + "
            f"{weather_repo.WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT}"
            "×전체 고유 Feature 수는 "
            f"{weather_repo.WEATHER_BATCH_MAX_PLANNING_WORK} 이하."
        ),
    )
    known_at: AwareDatetime = Field(description="소비자가 허용하는 지식 cutoff(UTC offset 필수).")

    @model_validator(mode="after")
    def targets_must_be_canonical_and_bounded(self) -> WeatherBatchRequest:
        target_ats = [target.target_at for target in self.targets]
        if any(right <= left for left, right in zip(target_ats, target_ats[1:], strict=False)):
            raise ValueError("targets는 중복 없이 target_at 오름차순이어야 합니다.")
        pair_count = sum(len(target.feature_ids) for target in self.targets)
        if pair_count > weather_repo.WEATHER_BATCH_MAX_PAIRS:
            raise ValueError(
                "targets의 전체 target_at×feature_id pair 수가 "
                f"{weather_repo.WEATHER_BATCH_MAX_PAIRS}개를 넘을 수 없습니다."
            )
        unique_feature_count = len(
            {
                feature_id
                for target in self.targets
                for feature_id in target.feature_ids
            }
        )
        planning_work = (
            pair_count
            + weather_repo.WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT
            * unique_feature_count
        )
        if planning_work > weather_repo.WEATHER_BATCH_MAX_PLANNING_WORK:
            raise ValueError(
                "targets의 planning work(pairs + "
                f"{weather_repo.WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT}"
                "×전체 고유 Feature 수)가 "
                f"{weather_repo.WEATHER_BATCH_MAX_PLANNING_WORK}를 넘을 수 없습니다."
            )
        return self


class WeatherBatchFoundItem(BaseModel):
    """공개 parent와 target의 공유 weather card 참조."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["found"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField
    card_key: str


class WeatherBatchCardOut(BaseModel):
    """한 target 안에서 같은 source bundle을 공유하는 weather card."""

    model_config = ConfigDict(extra="forbid")

    card_key: str
    source_styles: list[str]
    current: list[WeatherMetricOut]
    timeline: list[WeatherMetricOut]
    latest_at: datetime | None = None
    is_stale: bool


class WeatherBatchNoDataItem(BaseModel):
    """공개 parent는 있으나 cutoff에 맞는 weather가 없는 item."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["no_data"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField


class WeatherBatchRetiredItem(BaseModel):
    """현재 공개 parent가 아니어서 weather를 제공할 수 없는 item.

    parent가 저장소에 아예 없으면 ``feature_uuid``도 ``None``이다.
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["retired"]
    feature_id: str
    feature_uuid: str | None = _FeatureUuidField


WeatherBatchItemOut = Annotated[
    WeatherBatchFoundItem | WeatherBatchNoDataItem | WeatherBatchRetiredItem,
    Field(discriminator="state"),
]


class WeatherBatchTargetData(BaseModel):
    """target 시각 하나의 weather snapshot."""

    model_config = ConfigDict(extra="forbid")

    target_at: datetime
    timeline_until: datetime
    items: list[WeatherBatchItemOut]
    cards: list[WeatherBatchCardOut]


class WeatherBatchData(BaseModel):
    """한 DB snapshot에서 계산한 다중 target weather batch data."""

    model_config = ConfigDict(extra="forbid")

    known_at: datetime
    targets: list[WeatherBatchTargetData]


class WeatherBatchResponse(BaseModel):
    """``POST /features/weather/batch`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: WeatherBatchData
    meta: Meta


def _weather_batch_item_out(
    item: weather_repo.WeatherBatchItem,
    feature_uuid_map: Mapping[str, str],
    *,
    echo_feature_id: str | None = None,
) -> WeatherBatchItemOut:
    # T-VN-32C — item feature_id는 요청 표기 echo (조회는 해석된 legacy 키).
    feature_id = echo_feature_id if echo_feature_id is not None else item.feature_id
    feature_uuid = feature_uuid_map.get(item.feature_id)
    if item.state == "found":
        if item.card_key is None:
            raise RuntimeError("found weather batch item has no card key")
        return WeatherBatchFoundItem(
            state="found",
            feature_id=feature_id,
            feature_uuid=feature_uuid,
            card_key=item.card_key,
        )
    if item.state == "no_data":
        return WeatherBatchNoDataItem(
            state="no_data",
            feature_id=feature_id,
            feature_uuid=feature_uuid,
        )
    if item.state == "retired":
        return WeatherBatchRetiredItem(
            state="retired",
            feature_id=feature_id,
            feature_uuid=feature_uuid,
        )
    assert_never(item.state)


def _weather_batch_card_out(
    card: weather_repo.WeatherBatchCard,
) -> WeatherBatchCardOut:
    return WeatherBatchCardOut(
        card_key=card.card_key,
        source_styles=card.source_styles,
        current=[_weather_metric_out(metric) for metric in card.current],
        timeline=[_weather_metric_out(metric) for metric in card.timeline],
        latest_at=card.latest_at,
        is_stale=card.is_stale,
    )


_WEATHER_BATCH_READ_EXCEPTIONS = (
    weather_repo.WeatherBatchMetricLimitExceededError,
    weather_repo.WeatherBatchWorkLimitExceededError,
    weather_repo.WeatherBatchPayloadLimitExceededError,
    weather_repo.WeatherBatchQueryTimeoutError,
    SQLAlchemyError,
)


def _weather_batch_http_exception(
    exc: weather_repo.WeatherBatchMetricLimitExceededError
    | weather_repo.WeatherBatchWorkLimitExceededError
    | weather_repo.WeatherBatchPayloadLimitExceededError
    | weather_repo.WeatherBatchQueryTimeoutError
    | SQLAlchemyError,
) -> HTTPException:
    """공용 weather repository 실패를 단건/batch의 같은 HTTP 계약으로 변환한다."""

    if isinstance(exc, weather_repo.WeatherBatchMetricLimitExceededError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
                "message": "weather batch 결과가 metric row 예산을 초과했습니다.",
                "details": {"actual": exc.actual, "limit": exc.limit},
            },
        )
    if isinstance(exc, weather_repo.WeatherBatchWorkLimitExceededError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
                "message": "weather batch 요청이 source-series 작업량 예산을 초과했습니다.",
                "details": {
                    "actual_series_work": exc.actual,
                    "limit_series_work": exc.limit,
                },
            },
        )
    if isinstance(exc, weather_repo.WeatherBatchPayloadLimitExceededError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED",
                "message": "weather batch 결과가 payload byte 예산을 초과했습니다.",
                "details": {
                    "actual_bytes": exc.actual,
                    "limit_bytes": exc.limit,
                },
            },
        )
    if isinstance(exc, weather_repo.WeatherBatchQueryTimeoutError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "WEATHER_BATCH_UNAVAILABLE",
                "message": "weather batch query가 시간 예산을 초과했습니다.",
                "details": {},
            },
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "WEATHER_BATCH_UNAVAILABLE",
            "message": "weather batch 저장소를 사용할 수 없습니다.",
            "details": {},
        },
    )


@router.post(
    "/weather/batch",
    response_model=WeatherBatchResponse,
    summary="feature weather bitemporal batch 조회 (service read)",
    dependencies=[Depends(require_service_token)],
    responses={
        413: {
            "model": ProblemDetail,
            "description": (
                "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED — source-series 작업량, "
                "metric row 또는 payload byte 예산 초과"
            ),
        },
        422: {
            "description": (
                "target 1~366개, target별 고유 Feature ID 1~200개, "
                "Feature ID 256자 이하, 전체 pair 2,000개·planning work 2,500 이하와 "
                "aware datetime 필요"
            )
        },
        503: {
            "model": ProblemDetail,
            "description": "WEATHER_BATCH_UNAVAILABLE — weather 저장소 연결/조회 실패",
        },
    },
)
async def get_feature_weather_batch(
    request: Request,
    body: WeatherBatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeatherBatchResponse:
    started_at = perf_counter()
    # T-VN-32C PR-2 — target feature 참조를 경계 해석해 legacy 키로 조회하되
    # (미해석 참조는 정당한 no_data/retired 계열), 응답 item feature_id는
    # 요청 표기 echo를 유지한다. 같은 target 안에서 서로 다른 표기가 같은
    # feature로 해석되면 조회는 1회, echo는 표기별로 낸다. 형식 위반 참조는
    # per-item 격리 유지(해당 item만 no_data — 리뷰 M1).
    all_refs = [ref for target in body.targets for ref in target.feature_ids]
    resolved_refs = await feature_identity.resolve_feature_identities_bulk(
        session, _wellformed_refs(all_refs)
    )

    def _lookup_id(ref: str) -> str:
        identity = resolved_refs.get(ref)
        return identity.feature_id if identity is not None else ref

    try:
        snapshots = await weather_repo.get_weather_batch_snapshots(
            session,
            targets=tuple(
                weather_repo.WeatherBatchTarget(
                    target_at=target.target_at,
                    feature_ids=tuple(
                        dict.fromkeys(_lookup_id(ref) for ref in target.feature_ids)
                    ),
                )
                for target in body.targets
            ),
            known_at=body.known_at,
        )
    except _WEATHER_BATCH_READ_EXCEPTIONS as exc:
        raise _weather_batch_http_exception(exc) from exc
    # T-VN-32B additive — weather batch 조회 SQL을 재작성하지 않고 item feature
    # 참조에 UUID 정본을 병행 노출한다(존재하지 않는 parent는 map에서 빠져 None).
    item_feature_ids = sorted(
        {item.feature_id for snapshot in snapshots for item in snapshot.items}
    )
    feature_uuid_map = await feature_identity.get_feature_uuid_map(
        session, item_feature_ids
    )

    def _target_items_out(
        snapshot: weather_repo.WeatherBatchSnapshot,
        requested: Sequence[str],
    ) -> list[WeatherBatchItemOut]:
        by_id = {item.feature_id: item for item in snapshot.items}
        items_out: list[WeatherBatchItemOut] = []
        for ref in requested:
            item = by_id.get(_lookup_id(ref))
            if item is None:
                raise RuntimeError("weather batch snapshot이 요청 target을 누락했습니다")
            items_out.append(
                _weather_batch_item_out(item, feature_uuid_map, echo_feature_id=ref)
            )
        return items_out

    return WeatherBatchResponse(
        data=WeatherBatchData(
            known_at=body.known_at,
            targets=[
                WeatherBatchTargetData(
                    target_at=snapshot.target_at,
                    timeline_until=snapshot.target_at
                    + timedelta(days=weather_repo.WEATHER_BATCH_TIMELINE_DAYS),
                    items=_target_items_out(snapshot, target.feature_ids),
                    cards=[_weather_batch_card_out(card) for card in snapshot.cards],
                )
                for snapshot, target in zip(snapshots, body.targets, strict=True)
            ],
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/weather",
    response_model=FeatureWeatherResponse,
    summary="feature weather card (forecast_style별 최신값 + freshness)",
    responses={
        404: {"description": "공개 feature 없음"},
        413: {
            "model": ProblemDetail,
            "description": (
                "WEATHER_BATCH_RESULT_LIMIT_EXCEEDED — source-series 작업량, "
                "metric row 또는 payload byte 예산 초과"
            ),
        },
        503: {
            "model": ProblemDetail,
            "description": "WEATHER_BATCH_UNAVAILABLE — weather 저장소 연결/조회 실패",
        },
    },
)
async def get_feature_weather(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=weather_repo.WEATHER_BATCH_MAX_FEATURE_ID_LENGTH,
        ),
    ],
    asof: Annotated[
        _WeatherTargetAt | None,
        Query(description="이 시점 이하 weather만(미래 예보 제외)."),
    ] = None,
) -> FeatureWeatherResponse:
    started_at = perf_counter()
    # T-VN-32B 경계 alias 해석 — 해석 실패는 404, 이후 판정은 정본 키로.
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    known_at = datetime.now(UTC)
    target_at = asof or known_at
    # 단건도 batch의 parent/no-data 판정과 bitemporal cutoff를 그대로 재사용한다.
    try:
        snapshots = await weather_repo.get_weather_batch_snapshots(
            session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=target_at,
                    feature_ids=(canonical_id,),
                ),
            ),
            known_at=known_at,
        )
    except _WEATHER_BATCH_READ_EXCEPTIONS as exc:
        raise _weather_batch_http_exception(exc) from exc
    item = snapshots[0].items[0]
    if item.state == "retired":
        raise HTTPException(status_code=404, detail="공개 feature 없음")
    card = None
    if item.card_key is not None:
        card = next(
            (
                candidate
                for candidate in snapshots[0].cards
                if candidate.card_key == item.card_key
            ),
            None,
        )
        if card is None:
            raise RuntimeError("weather batch item references a missing card")
    metrics = [] if card is None else [_weather_metric_out(metric) for metric in card.current]
    return FeatureWeatherResponse(
        data=WeatherCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본 값.
            feature_id=identity.feature_uuid,
            asof=asof,
            source_styles=(
                []
                if card is None
                else sorted({metric.forecast_style for metric in card.current})
            ),
            metrics=metrics,
            latest_at=None if card is None else card.latest_at,
            is_stale=True if card is None else card.is_stale,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/contained-features",
    response_model=AreaContainedFeaturesResponse,
    summary="area feature 안에 포함된 point feature 목록",
    responses={
        404: {"description": "feature_id 없음"},
        422: {"description": "area feature가 아님"},
    },
)
async def get_area_contained_features(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
    kind: Annotated[
        list[str] | None,
        Query(description="포함 feature kind 필터 (반복 가능). 미지정 시 전체."),
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AreaContainedFeaturesResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    area_row = await _public_feature_row_or_404(
        session, canonical_id, display_ref=feature_id
    )
    if area_row["kind"] != "area":
        raise HTTPException(
            status_code=422,
            detail=f"area feature가 아닙니다: {feature_id!r}",
        )
    rows = await feature_repo.features_contained_in_area(
        session,
        feature_id=canonical_id,
        kinds=kind,
        limit=page_size,
    )
    return AreaContainedFeaturesResponse(
        data=AreaContainedFeaturesData(
            area_feature_id=identity.feature_uuid,
            area_square_meters=area_row.get("area_square_meters"),
            items=[FeatureSummary(**uuid_substituted_row(row)) for row in rows],
        ),
        meta=make_meta(request, started_at=started_at, page_size=page_size),
    )


@router.get(
    "/{feature_id}/price",
    response_model=FeaturePriceResponse,
    summary="feature price card (provider/domain/product series별 최신 가격 + 최근 이력)",
    responses={404: {"description": "공개 feature 없음"}},
)
async def get_feature_price(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
    asof: Annotated[
        datetime | None,
        Query(description="이 시점 이하 price만 조회."),
    ] = None,
    history_limit: Annotated[
        int,
        Query(ge=1, le=500, description="최근 price history 반환 개수."),
    ] = 100,
) -> FeaturePriceResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    # parent feature 공개 검사 (ADR-067) — 비공개/미존재 feature의 price payload
    # 노출 금지. detail 단건과 동일한 404 계약.
    await _public_feature_row_or_404(session, canonical_id, display_ref=feature_id)
    card = await price_repo.build_price_card(
        session,
        feature_id=canonical_id,
        asof=asof,
        history_limit=history_limit,
    )
    return FeaturePriceResponse(
        data=PriceCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본 값.
            feature_id=identity.feature_uuid,
            asof=card.asof,
            current=[_price_point_out(point) for point in card.current],
            history=[_price_point_out(point) for point in card.history],
            latest_at=card.latest_at,
            is_stale=card.is_stale,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.post(
    "/batch",
    response_model=FeatureBatchResponse,
    summary="feature 5-state trip_card batch 조회 (service read)",
    dependencies=[Depends(require_service_token)],
    responses={
        422: {"description": "서로 다른 item 1~200개 필요"},
        503: {
            "model": ProblemDetail,
            "description": "FEATURE_BATCH_UNAVAILABLE — feature 저장소 연결/조회 실패",
        },
    },
)
async def get_features_batch(
    request: Request,
    body: FeatureBatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureBatchResponse:
    started_at = perf_counter()
    # T-VN-32C PR-2 — 값 전환 후 소비자(PinVi)가 UUID 참조를 보낸다. 경계
    # 해석으로 legacy 키 조회를 보장하되(미해석 참조는 정당한 missing),
    # 응답 item feature_id는 요청 표기 echo를 유지한다. 형식 위반 참조는
    # per-item 상태 기계 격리를 지키기 위해 해석에서 제외하고 원문 그대로
    # 조회에 흘린다(종전과 동일하게 해당 item만 missing — 리뷰 M1).
    refs = [item.feature_id for item in body.items]
    resolved = await feature_identity.resolve_feature_identities_bulk(
        session, _wellformed_refs(refs)
    )
    try:
        rows = await feature_repo.get_service_feature_batch_items(
            session,
            tuple(
                (
                    resolved[item.feature_id].feature_id
                    if item.feature_id in resolved
                    else item.feature_id,
                    item.known_row_revision,
                )
                for item in body.items
            ),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_BATCH_UNAVAILABLE",
                "message": "feature batch 저장소를 사용할 수 없습니다.",
                "details": {},
            },
        ) from exc
    return FeatureBatchResponse(
        data=FeatureBatchData(
            items=[
                _batch_item_from_row(row, echo_feature_id=ref)
                for row, ref in zip(rows, refs, strict=True)
            ]
        ),
        meta=make_meta(request, started_at=started_at),
    )
