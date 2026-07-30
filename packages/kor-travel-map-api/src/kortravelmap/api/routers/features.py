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

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo``)
- ADR-005 + ADR-035 — public API key/service token + 네트워크 경계 보호.
  본 라우터는 ``/features`` prefix.
- ADR-012 — bbox/좌표는 4326, GIST 인덱스 사용 (술어에 ST_Transform 없음)
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, assert_never

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
    feature_repo,
    observation_repo,
    price_repo,
    weather_repo,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    get_poi_cache_target_by_key,
)
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_admin_frontend, require_service_token
from kortravelmap.api.db import get_session
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.response import ClusterUnit, Meta, ProblemDetail, make_meta
from kortravelmap.api.routers.curations import PublicCurationItemView
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

    feature_id: str
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
    source_version: str | None
    raw_name: str | None
    raw_address: str | None
    raw_longitude: float | None
    raw_latitude: float | None
    raw_data: dict[str, Any]
    raw_payload_hash: str
    fetched_at: datetime
    imported_at: datetime
    record_last_seen_at: datetime
    expires_at: datetime | None
    source_role: str
    match_method: str
    confidence: int
    is_primary_source: bool
    linked_at: datetime
    is_current: bool


class FeatureDetailResponse(BaseModel):
    """feature 단건 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
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


class FeatureBatchFoundItem(BaseModel):
    """공개 feature의 최신 trip_card."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["found"]
    feature_id: str
    row_revision: _PostgresBigintRevision
    trip_card: FeatureTripCard


class FeatureBatchRetiredItem(BaseModel):
    """lifecycle tombstone이 확인된 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["retired"]
    feature_id: str
    row_revision: _PostgresBigintRevision


class FeatureBatchSuppressedItem(BaseModel):
    """존재하지만 현재 공개 projection에 없는 feature."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["suppressed"]
    feature_id: str
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
    return {
        key: value
        for key, value in detail.items()
        if key not in _PUBLIC_DETAIL_STRIPPED_KEYS
    }


def _detail_from_row(row: dict[str, Any]) -> FeatureDetailResponse:
    return FeatureDetailResponse(
        feature_id=row["feature_id"],
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


def _batch_item_from_row(row: feature_repo.FeatureBatchItemRow) -> FeatureBatchItem:
    if row.state == "missing":
        return FeatureBatchMissingItem(state="missing", feature_id=row.feature_id)
    if row.row_revision is None:
        raise RuntimeError(f"{row.state} batch item has no row_revision")
    if row.state == "found":
        if row.trip_card is None:
            raise RuntimeError("found batch item has no trip_card")
        return FeatureBatchFoundItem(
            state="found",
            feature_id=row.feature_id,
            row_revision=row.row_revision,
            trip_card=FeatureTripCard.model_validate(row.trip_card),
        )
    if row.state == "retired":
        return FeatureBatchRetiredItem(
            state="retired",
            feature_id=row.feature_id,
            row_revision=row.row_revision,
        )
    if row.state == "suppressed":
        return FeatureBatchSuppressedItem(
            state="suppressed",
            feature_id=row.feature_id,
            row_revision=row.row_revision,
        )
    if row.state == "unchanged":
        return FeatureBatchUnchangedItem(
            state="unchanged",
            feature_id=row.feature_id,
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
    active/latest 계보 조건(``public_active_notice_feature_ids``)을 통과해야 한다.
    비공개면 ``None``.
    """
    row = await feature_repo.get_public_feature_row(session, feature_id)
    if row is None:
        return None
    if row.get("kind") != "notice":
        return row
    visible_ids = await feature_repo.public_active_notice_feature_ids(
        session,
        [str(row["feature_id"])],
    )
    if str(row["feature_id"]) not in visible_ids:
        return None
    return row


async def _public_feature_row_or_404(
    session: AsyncSession,
    feature_id: str,
) -> dict[str, Any]:
    row = await _public_feature_row(session, feature_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    return row


async def _operator_feature_or_404(
    session: AsyncSession,
    feature_id: str,
) -> None:
    """operator raw lineage 표면용 존재 확인 — 공개 가시성 gate를 적용하지 않는다.

    T-VN-05: raw lineage는 operator 전용이므로 비공개/종료 feature도 감사 대상이다.
    공개 projection이 아니라 raw row 존재만으로 404를 판정한다(없으면 404).
    """
    row = await feature_repo.get_feature_row(session, feature_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )


def _curation_item_view(row: curation_repo.CurationItem) -> PublicCurationItemView:
    return PublicCurationItemView.model_validate(row, from_attributes=True)


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
                "primary source(provider_sync.is_primary_source) 기준."
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
    next_cursor = (
        feature_repo.encode_bbox_cursor(page_rows[-1]["feature_id"])
        if len(rows) > page_size and page_rows
        else None
    )
    items = [FeatureSummary(**row) for row in page_rows]
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
    items = [FeatureSummary(**row) for row in rows[:max_items]]
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
            feature_id=item.feature_id,
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
            feature_id=item.feature_id,
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
            feature_id=item.feature_id,
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
    responses={
        404: {"description": "feature_id 없음"},
        304: {"description": "If-None-Match row_revision 일치 (본문 없음)"},
        422: {"description": "If-None-Match가 canonical strong ETag가 아님"},
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
    row = await _public_feature_row_or_404(session, feature_id)
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
        session, feature_ids=[feature_id], public_only=True
    )
    detail = _detail_from_row(row).model_copy(
        update={
            "curations": [_curation_item_view(item) for item in curations.get(feature_id, ())],
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
    제거하고 이 operator 표면으로 이동했다. 비공개/종료 feature도 감사 대상이라
    공개 가시성 gate 없이 raw row 존재만 확인한다.
    """
    started_at = perf_counter()
    await _operator_feature_or_404(session, feature_id)
    observations = await observation_repo.get_current_observations(session, feature_id)
    return FeatureSourcesResponse(
        data=FeatureSourcesData(
            feature_id=feature_id,
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
    await _operator_feature_or_404(session, feature_id)
    try:
        page = await observation_repo.get_observation_history(
            session,
            feature_id=feature_id,
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
    observed_at: datetime | None = None


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


@router.get(
    "/{feature_id}/weather",
    response_model=FeatureWeatherResponse,
    summary="feature weather card (forecast_style별 최신값 + freshness)",
    responses={404: {"description": "공개 feature 없음"}},
)
async def get_feature_weather(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
    asof: Annotated[
        datetime | None,
        Query(description="이 시점 이하 weather만(미래 예보 제외)."),
    ] = None,
) -> FeatureWeatherResponse:
    started_at = perf_counter()
    # parent feature 공개 검사 (ADR-067) — 비공개/미존재 feature의 weather payload
    # 노출 금지. detail 단건과 동일한 404 계약.
    await _public_feature_row_or_404(session, feature_id)
    card = await weather_repo.build_weather_card(session, feature_id=feature_id, asof=asof)
    metrics = [
        WeatherMetricOut(
            forecast_style=m.forecast_style,
            metric_key=m.metric_key,
            metric_name=m.metric_name,
            timeline_bucket=m.timeline_bucket,
            value_number=float(m.value_number) if m.value_number is not None else None,
            value_text=m.value_text,
            unit=m.unit,
            severity=m.severity,
            issued_at=m.issued_at,
            valid_at=m.valid_at,
            observed_at=m.observed_at,
        )
        for m in card.metrics
    ]
    return FeatureWeatherResponse(
        data=WeatherCardData(
            feature_id=card.feature_id,
            asof=card.asof,
            source_styles=card.source_styles,
            metrics=metrics,
            latest_at=card.latest_at,
            is_stale=card.is_stale,
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
    area_row = await _public_feature_row_or_404(session, feature_id)
    if area_row["kind"] != "area":
        raise HTTPException(
            status_code=422,
            detail=f"area feature가 아닙니다: {feature_id!r}",
        )
    rows = await feature_repo.features_contained_in_area(
        session,
        feature_id=feature_id,
        kinds=kind,
        limit=page_size,
    )
    return AreaContainedFeaturesResponse(
        data=AreaContainedFeaturesData(
            area_feature_id=feature_id,
            area_square_meters=area_row.get("area_square_meters"),
            items=[FeatureSummary(**row) for row in rows],
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
    # parent feature 공개 검사 (ADR-067) — 비공개/미존재 feature의 price payload
    # 노출 금지. detail 단건과 동일한 404 계약.
    await _public_feature_row_or_404(session, feature_id)
    card = await price_repo.build_price_card(
        session,
        feature_id=feature_id,
        asof=asof,
        history_limit=history_limit,
    )
    return FeaturePriceResponse(
        data=PriceCardData(
            feature_id=card.feature_id,
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
    responses={422: {"description": "서로 다른 item 1~200개 필요"}},
)
async def get_features_batch(
    request: Request,
    body: FeatureBatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureBatchResponse:
    started_at = perf_counter()
    rows = await feature_repo.get_service_feature_batch_items(
        session,
        tuple((item.feature_id, item.known_row_revision) for item in body.items),
    )
    return FeatureBatchResponse(
        data=FeatureBatchData(items=[_batch_item_from_row(row) for row in rows]),
        meta=make_meta(request, started_at=started_at),
    )
