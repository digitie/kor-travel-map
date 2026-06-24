"""``kortravelmap.api.routers.features`` — feature 조회 API (``/features``).

적재된 feature를 운영자/frontend 지도가 조회한다 (ADR-035 운영 범위). 쿼리는
``kortravelmap.infra.feature_repo``의 raw SQL(ADR-004) — 본 라우터는 HTTP 표면 +
DTO 매핑만, SQL 미보유.

엔드포인트:
- ``GET /features`` — bbox 안 feature 경량 표현 list (지도 뷰포트 로드).
- ``GET /features/in-bounds`` — TripMate/user용 bbox envelope 응답.
- ``GET /features/search`` — TripMate/user용 이름/bbox 검색.
- ``GET /features/{feature_id}`` — feature 단건 상세.
- ``POST /features/batch`` — N+1 방지 batch 상세(service read, ServiceToken).

ADR 참조
--------
- ADR-004 — 쿼리는 raw SQL (``feature_repo``)
- ADR-005 + ADR-035 — 인증 없음, 운영 범위. 본 라우터는 ``/features`` prefix.
- ADR-012 — bbox/좌표는 4326, GIST 인덱스 사용 (술어에 ST_Transform 없음)
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra import feature_repo, weather_repo
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    get_poi_cache_target_by_key,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_service_token
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

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
    "FeaturesNearbyByTargetResponse",
]


router = APIRouter(prefix="/features", tags=["features"])
NearbySort = Literal["distance", "name", "last_updated_at"]


# ── 응답 schema ────────────────────────────────────────────────────────


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


class FeaturesInBboxData(BaseModel):
    """``GET /features`` data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureSummary]


class FeaturesInBboxResponse(BaseModel):
    """``GET /features`` 응답 — bbox 안 feature 목록."""

    model_config = ConfigDict(extra="forbid")

    data: FeaturesInBboxData
    meta: Meta


class FeatureDetailResponse(BaseModel):
    """feature 단건 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    legal_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    status: str
    updated_at: datetime


ClusterUnit = Literal["sido", "sigungu", "eupmyeondong"]


class ClusterSummary(BaseModel):
    """행정구역 rollup 클러스터 1건 (T-213c)."""

    model_config = ConfigDict(extra="forbid")

    cluster_key: str
    feature_count: int
    lon: float
    lat: float


class PublicFeatureListData(BaseModel):
    """public feature 목록 data payload.

    ``cluster_unit``이 None이면 ``items``(개별 feature), 아니면 ``clusters``
    (행정구역 rollup)를 채운다(T-213c).
    """

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureSummary]
    clusters: list[ClusterSummary] = []


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


class FeatureBatchRequest(BaseModel):
    """feature batch 상세 조회 요청 (service read)."""

    model_config = ConfigDict(extra="forbid")

    feature_ids: list[str] = Field(min_length=1, max_length=200)


class FeatureBatchData(BaseModel):
    """feature batch 상세 data payload."""

    model_config = ConfigDict(extra="forbid")

    found: dict[str, FeatureDetailResponse]
    missing: list[str]


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


def _resolve_cluster_unit(
    cluster_unit: ClusterUnit | None, zoom: int | None
) -> ClusterUnit | None:
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


def _detail_from_row(row: dict[str, Any]) -> FeatureDetailResponse:
    return FeatureDetailResponse(
        feature_id=row["feature_id"],
        kind=row["kind"],
        name=row["name"],
        category=row["category"],
        lon=row["lon"],
        lat=row["lat"],
        address=row["address"],
        detail=row["detail"],
        urls=row["urls"],
        legal_dong_code=row["legal_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        status=row["status"],
        updated_at=row["updated_at"],
    )


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=FeaturesInBboxResponse,
    summary="bbox 안 feature 목록 (지도 뷰포트)",
    description=(
        "주어진 경계 상자(WGS84) 안의 feature 경량 표현 list. ``coord``의 GIST "
        "인덱스를 사용하는 공간 조회 (ADR-012). ``kind`` 반복 파라미터로 종류 "
        "필터 (예: ``?kind=place&kind=event``). 삭제된 feature 제외."
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
            limit=page_size + 1,
            cursor=cursor,
            include_geometry=include_geometry,
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
    summary="bbox 안 feature 목록 (TripMate/public envelope)",
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
        clusters_raw = await feature_repo.cluster_features_in_bbox(
            session,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            cluster_unit=resolved_unit,
            kinds=kind,
            categories=category,
            limit=max_items,
        )
        clusters = [ClusterSummary(**c) for c in clusters_raw]
        return FeaturesInBoundsResponse(
            data=PublicFeatureListData(
                items=[],
                clusters=clusters,
            ),
            meta=make_meta(
                request,
                started_at=started_at,
                cluster_unit=resolved_unit,
            ),
        )
    rows = await feature_repo.features_in_bbox(
        session,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        kinds=kind,
        categories=category,
        limit=max_items,
        include_geometry=include_geometry,
    )
    items = [FeatureSummary(**row) for row in rows]
    return FeaturesInBoundsResponse(
        data=PublicFeatureListData(
            items=items,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/search",
    response_model=FeatureSearchResponse,
    summary="feature 검색 (이름 trgm + bbox)",
    responses={422: {"description": "검색 범위 또는 cursor 오류"}},
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
    if (
        min_lon is not None
        and min_lat is not None
        and max_lon is not None
        and max_lat is not None
    ):
        bbox = (min_lon, min_lat, max_lon, max_lat)
    try:
        page = await feature_repo.search_features(
            session,
            q=q,
            bbox=bbox,
            kinds=kind,
            categories=category,
            limit=page_size,
            cursor=cursor,
        )
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
            total=page.total_count if include_total else None,
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
        Query(alias="status", description="feature status 반복 필터. 기본 active."),
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
    external_system: Annotated[str, Query(description="외부 시스템 이름. 예: tripmate")],
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
        Query(alias="status", description="feature status 반복 필터. 기본 active."),
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
    responses={404: {"description": "feature_id 없음"}},
)
async def get_feature(
    request: Request,
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureDetailEnvelopeResponse:
    started_at = perf_counter()
    row = await feature_repo.get_feature_row(session, feature_id)
    if row is None or row["deleted_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    return FeatureDetailEnvelopeResponse(
        data=_detail_from_row(row),
        meta=make_meta(request, started_at=started_at),
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
    card = await weather_repo.build_weather_card(
        session, feature_id=feature_id, asof=asof
    )
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


@router.post(
    "/batch",
    response_model=FeatureBatchResponse,
    summary="feature 상세 batch 조회 (service read)",
    dependencies=[Depends(require_service_token)],
    responses={422: {"description": "feature_ids 1~200개 필요"}},
)
async def get_features_batch(
    request: Request,
    body: FeatureBatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureBatchResponse:
    started_at = perf_counter()
    feature_ids = list(dict.fromkeys(body.feature_ids))
    rows = await feature_repo.get_feature_rows_by_ids(session, feature_ids)
    items = {
        feature_id: _detail_from_row(rows[feature_id])
        for feature_id in feature_ids
        if feature_id in rows
    }
    missing = [feature_id for feature_id in feature_ids if feature_id not in rows]
    return FeatureBatchResponse(
        data=FeatureBatchData(found=items, missing=missing),
        meta=make_meta(request, started_at=started_at),
    )
