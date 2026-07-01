"""``/v1/curated-*`` + ``/v1/admin/curated-*`` API (T-223c-1)."""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable
from datetime import date, datetime
from time import perf_counter
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra import curated_repo
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["admin_router", "router"]

router = APIRouter(tags=["curated"])
admin_router = APIRouter(prefix="/admin", tags=["admin-curated"])

CurationStatus = Literal["candidate", "curated", "rejected", "archived"]
SelectionOrigin = Literal["source_rule", "admin", "external_api"]
CurationRelation = Literal[
    "primary_stop",
    "food_stop",
    "cafe_stop",
    "bookstore_stop",
    "nearby_option",
    "accessibility_support",
    "pet_support",
    "family_support",
    "theme_area_anchor",
]
ReusePolicy = Literal["allowed", "blocked", "manual_review"]
ThemeVisibility = Literal["admin_only", "public"]
SourceKind = Literal["openapi", "filedata", "standard", "internal", "manual"]
UpdateCycle = Literal[
    "realtime",
    "daily",
    "weekly",
    "monthly",
    "annual",
    "one_time",
    "unknown",
]
ProviderStatus = Literal[
    "implemented",
    "provider_needed",
    "manual_only",
    "deprecated",
]
RuleAction = Literal["candidate", "curated", "ignore"]

PLACE_SEARCH_LIMIT = 5
KAKAO_LOCAL_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.primaryTypeDisplayName"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class CuratedThemeView(BaseModel):
    """curated theme view."""

    model_config = ConfigDict(extra="forbid")

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


class CuratedSourceView(BaseModel):
    """curated source metadata view."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None = None
    source_kind: str
    license: str | None = None
    update_cycle: str
    last_source_modified_at: date | None = None
    last_checked_at: datetime | None = None
    next_expected_at: date | None = None
    row_count: int | None = None
    freshness_note: str | None = None
    provider_status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CuratedSourceRuleView(BaseModel):
    """curated source rule view."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    theme_id: str
    theme_slug: str
    source_id: str
    provider: str
    dataset_key: str
    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any]
    default_action: str
    priority: int
    enabled: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CuratedFeatureView(BaseModel):
    """curated feature overlay view."""

    model_config = ConfigDict(extra="forbid")

    curated_feature_id: str
    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    feature_id: str
    feature_name: str
    feature_category: str
    feature_kind: str
    lon: float | None = None
    lat: float | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    legal_dong_code: str | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    source_id: str
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None = None
    source_record_key: str | None = None
    curation_status: str
    selection_origin: str
    selected_by: str | None = None
    selected_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    rank_score: float
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: str
    reuse_policy: str
    content_version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class CuratedThemesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedThemeView]


class CuratedSourcesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedSourceView]


class CuratedSourceRulesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedSourceRuleView]


class CuratedFeaturesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedFeatureView]


class CuratedThemesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedThemesData
    meta: Meta


class CuratedThemeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedThemeView
    meta: Meta


class CuratedSourcesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourcesData
    meta: Meta


class CuratedSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceView
    meta: Meta


class CuratedSourceRulesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceRulesData
    meta: Meta


class CuratedSourceRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceRuleView
    meta: Meta


class CuratedFeaturesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeaturesData
    meta: Meta


class CuratedFeatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeatureView
    meta: Meta


class CuratedFeatureDetailItemView(BaseModel):
    """curated feature detail item."""

    model_config = ConfigDict(extra="forbid")

    curated_feature_item_id: str
    feature_id: str
    relation: str
    sort_order: int
    day_index: int | None = None
    memo: str | None = None
    feature_snapshot: dict[str, Any]
    source_record_key: str | None = None


class CuratedFeatureDetailSnapshotView(BaseModel):
    """curated feature detail snapshot."""

    model_config = ConfigDict(extra="forbid")

    curated_feature_id: str
    version: int
    etag: str
    updated_at: datetime
    theme: dict[str, Any]
    content: dict[str, Any]
    source: dict[str, Any]
    items: list[CuratedFeatureDetailItemView]


class CuratedFeatureDetailSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeatureDetailSnapshotView
    meta: Meta


class PlaceSearchHitView(BaseModel):
    """external place-search normalized hit."""

    model_config = ConfigDict(extra="allow")

    provider: str
    name: str | None = None
    address: str | None = None
    road_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    category: str | None = None


class CuratedPlaceSearchData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    google: list[PlaceSearchHitView]
    kakao: list[PlaceSearchHitView]
    naver: list[PlaceSearchHitView]
    errors: dict[str, str]


class CuratedPlaceSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedPlaceSearchData
    meta: Meta


class RuleApplyData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    inserted_or_updated: int


class RuleApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RuleApplyData
    meta: Meta


class CuratedThemeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_slug: str = Field(min_length=1, max_length=128)
    theme_name: str = Field(min_length=1, max_length=200)
    theme_description: str = ""
    theme_group: str = Field(min_length=1, max_length=64)
    default_curated: bool = False
    visibility: ThemeVisibility = "admin_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedThemePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_slug: str | None = Field(default=None, min_length=1, max_length=128)
    theme_name: str | None = Field(default=None, min_length=1, max_length=200)
    theme_description: str | None = None
    theme_group: str | None = Field(default=None, min_length=1, max_length=64)
    default_curated: bool | None = None
    visibility: ThemeVisibility | None = None
    metadata: dict[str, Any] | None = None


class CuratedSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=128)
    dataset_key: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str | None = None
    source_kind: SourceKind
    license: str | None = None
    update_cycle: UpdateCycle = "unknown"
    last_source_modified_at: date | None = None
    last_checked_at: datetime | None = None
    next_expected_at: date | None = None
    row_count: int | None = Field(default=None, ge=0)
    freshness_note: str | None = None
    provider_status: ProviderStatus = "implemented"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedSourcePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str | None = Field(default=None, min_length=1, max_length=200)
    source_url: str | None = None
    source_kind: SourceKind | None = None
    license: str | None = None
    update_cycle: UpdateCycle | None = None
    last_source_modified_at: date | None = None
    last_checked_at: datetime | None = None
    next_expected_at: date | None = None
    row_count: int | None = Field(default=None, ge=0)
    freshness_note: str | None = None
    provider_status: ProviderStatus | None = None
    metadata: dict[str, Any] | None = None


class CuratedSourceRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str
    source_id: str
    dataset_key: str = Field(min_length=1, max_length=200)
    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any] = Field(default_factory=dict)
    default_action: RuleAction = "candidate"
    priority: int = 0
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedSourceRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_key: str | None = Field(default=None, min_length=1, max_length=200)
    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any] | None = None
    default_action: RuleAction | None = None
    priority: int | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class CuratedFeatureCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str
    feature_id: str = Field(min_length=1)
    source_id: str
    source_record_key: str | None = None
    curation_status: CurationStatus = "candidate"
    selection_origin: SelectionOrigin = "admin"
    selected_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    rank_score: float = 0.0
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: CurationRelation = "nearby_option"
    reuse_policy: ReusePolicy = "manual_review"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedFeaturePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_status: CurationStatus | None = None
    source_record_key: str | None = None
    rank_score: float | None = None
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: CurationRelation | None = None
    reuse_policy: ReusePolicy | None = None
    metadata: dict[str, Any] | None = None


class CuratedFeatureStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str | None = None
    reason: str | None = None


def _theme_view(row: curated_repo.CuratedTheme) -> CuratedThemeView:
    return CuratedThemeView(**row.__dict__)


def _source_view(row: curated_repo.CuratedSource) -> CuratedSourceView:
    return CuratedSourceView(**row.__dict__)


def _rule_view(row: curated_repo.CuratedSourceRule) -> CuratedSourceRuleView:
    return CuratedSourceRuleView(**row.__dict__)


def _feature_view(row: curated_repo.CuratedFeature) -> CuratedFeatureView:
    return CuratedFeatureView(**row.__dict__)


def _snapshot_view(
    row: curated_repo.CuratedFeatureDetailSnapshot,
) -> CuratedFeatureDetailSnapshotView:
    return CuratedFeatureDetailSnapshotView(
        curated_feature_id=row.curated_feature_id,
        version=row.version,
        etag=row.etag,
        updated_at=row.updated_at,
        theme=row.theme,
        content=row.content,
        source=row.source,
        items=[CuratedFeatureDetailItemView(**item.__dict__) for item in row.items],
    )


def _integrity_error(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"curated row constraint violation: {exc.orig}",
    )


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _clean_place_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = html.unescape(_HTML_TAG_RE.sub("", value)).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _naver_wgs84_coord(value: Any) -> float | None:
    coord = _float_or_none(value)
    if coord is None:
        return None
    if abs(coord) > 180:
        return coord / 10_000_000
    return coord


def _google_display_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return _clean_place_text(value.get("text"))
    return _clean_place_text(value)


async def _search_kakao_places(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.get(
        KAKAO_LOCAL_KEYWORD_URL,
        headers={"Authorization": f"KakaoAK {api_key}"},
        params={"query": query, "size": PLACE_SEARCH_LIMIT},
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        hits.append(
            PlaceSearchHitView(
                provider="kakao",
                name=_clean_place_text(item.get("place_name")),
                address=_clean_place_text(item.get("address_name")),
                road_address=_clean_place_text(item.get("road_address_name")),
                latitude=_float_or_none(item.get("y")),
                longitude=_float_or_none(item.get("x")),
                category=_clean_place_text(item.get("category_name")),
            )
        )
    return hits


async def _search_naver_places(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.get(
        NAVER_LOCAL_SEARCH_URL,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
        params={"query": query, "display": PLACE_SEARCH_LIMIT},
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        hits.append(
            PlaceSearchHitView(
                provider="naver",
                name=_clean_place_text(item.get("title")),
                address=_clean_place_text(item.get("address")),
                road_address=_clean_place_text(item.get("roadAddress")),
                latitude=_naver_wgs84_coord(item.get("mapy")),
                longitude=_naver_wgs84_coord(item.get("mapx")),
                category=_clean_place_text(item.get("category")),
            )
        )
    return hits


async def _search_google_places(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.post(
        GOOGLE_PLACES_TEXT_SEARCH_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
        },
        json={
            "textQuery": query,
            "languageCode": "ko",
            "regionCode": "KR",
            "maxResultCount": PLACE_SEARCH_LIMIT,
        },
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        location = item.get("location")
        primary_type = item.get("primaryTypeDisplayName")
        hits.append(
            PlaceSearchHitView(
                provider="google",
                name=_google_display_text(item.get("displayName")),
                address=_clean_place_text(item.get("formattedAddress")),
                road_address=None,
                latitude=_float_or_none(location.get("latitude"))
                if isinstance(location, dict)
                else None,
                longitude=_float_or_none(location.get("longitude"))
                if isinstance(location, dict)
                else None,
                category=_google_display_text(primary_type),
            )
        )
    return hits


async def _capture_place_search(
    provider: str,
    awaitable: Awaitable[list[PlaceSearchHitView]],
) -> tuple[str, list[PlaceSearchHitView], str | None]:
    try:
        return provider, await awaitable, None
    except httpx.HTTPStatusError as exc:
        return provider, [], f"HTTP {exc.response.status_code}"
    except httpx.HTTPError:
        return provider, [], "호출 실패"
    except ValueError:
        return provider, [], "응답 파싱 실패"


async def _direct_place_search(query: str) -> CuratedPlaceSearchData:
    settings = KorTravelMapSettings()
    google_key = _secret_value(settings.google_places_api_key)
    kakao_key = _secret_value(settings.kakao_local_rest_api_key)
    naver_client_id = _secret_value(settings.naver_search_client_id)
    naver_client_secret = _secret_value(settings.naver_search_client_secret)

    google: list[PlaceSearchHitView] = []
    kakao: list[PlaceSearchHitView] = []
    naver: list[PlaceSearchHitView] = []
    errors: dict[str, str] = {}

    if google_key is None:
        errors["google"] = "KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY env가 없습니다."
    if kakao_key is None:
        errors["kakao"] = "KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY env가 없습니다."
    if naver_client_id is None or naver_client_secret is None:
        errors["naver"] = (
            "KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID/SECRET env가 없습니다."
        )

    tasks: list[Awaitable[tuple[str, list[PlaceSearchHitView], str | None]]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        if google_key is not None:
            tasks.append(
                _capture_place_search(
                    "google",
                    _search_google_places(client, api_key=google_key, query=query),
                )
            )
        if kakao_key is not None:
            tasks.append(
                _capture_place_search(
                    "kakao",
                    _search_kakao_places(client, api_key=kakao_key, query=query),
                )
            )
        if naver_client_id is not None and naver_client_secret is not None:
            tasks.append(
                _capture_place_search(
                    "naver",
                    _search_naver_places(
                        client,
                        client_id=naver_client_id,
                        client_secret=naver_client_secret,
                        query=query,
                    ),
                )
            )
        results = await asyncio.gather(*tasks) if tasks else []

    for provider, hits, error in results:
        if error is not None:
            errors[provider] = error
        elif provider == "google":
            google = hits
        elif provider == "kakao":
            kakao = hits
        elif provider == "naver":
            naver = hits

    return CuratedPlaceSearchData(
        query=query,
        google=google,
        kakao=kakao,
        naver=naver,
        errors=errors,
    )


async def _feature_or_404(
    session: AsyncSession,
    curated_feature_id: str,
    *,
    include_archived: bool = False,
) -> curated_repo.CuratedFeature:
    row = await curated_repo.get_curated_feature(
        session,
        curated_feature_id=curated_feature_id,
        include_archived=include_archived,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return row


@router.get("/curated-themes", response_model=CuratedThemesResponse)
async def list_curated_themes_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    visibility: Annotated[ThemeVisibility | None, Query()] = None,
    theme_group: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedThemesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_themes(
        session,
        visibility=visibility,
        theme_group=theme_group,
        limit=limit,
    )
    return CuratedThemesResponse(
        data=CuratedThemesData(items=[_theme_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@router.get("/curated-sources", response_model=CuratedSourcesResponse)
async def list_curated_sources_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    provider_status: Annotated[ProviderStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourcesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_sources(
        session,
        provider=provider,
        dataset_key=dataset_key,
        provider_status=provider_status,
        limit=limit,
    )
    return CuratedSourcesResponse(
        data=CuratedSourcesData(items=[_source_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@router.get("/curated-features", response_model=CuratedFeaturesResponse)
async def list_curated_features_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_id: Annotated[str | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    source_id: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    curation_status: Annotated[CurationStatus | None, Query()] = "curated",
    region_code: Annotated[str | None, Query()] = None,
    sido_code: Annotated[str | None, Query()] = None,
    sigungu_code: Annotated[str | None, Query()] = None,
    min_lon: Annotated[float | None, Query()] = None,
    min_lat: Annotated[float | None, Query()] = None,
    max_lon: Annotated[float | None, Query()] = None,
    max_lat: Annotated[float | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> CuratedFeaturesResponse:
    started_at = perf_counter()
    try:
        page = await curated_repo.list_curated_features(
            session,
            theme_id=theme_id,
            theme_slug=theme_slug,
            source_id=source_id,
            provider=provider,
            dataset_key=dataset_key,
            curation_status=curation_status,
            region_code=region_code,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            q=q,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedFeaturesResponse(
        data=CuratedFeaturesData(items=[_feature_view(row) for row in page.items]),
        meta=make_meta(started_at=started_at, next_cursor=page.next_cursor),
    )


@router.get(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
async def get_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    row = await _feature_or_404(session, curated_feature_id)
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/features/curated", response_model=CuratedFeaturesResponse)
@admin_router.get(
    "/curated-features",
    response_model=CuratedFeaturesResponse,
    include_in_schema=False,
)
async def list_admin_curated_features_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_id: Annotated[str | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    source_id: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    curation_status: Annotated[CurationStatus | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> CuratedFeaturesResponse:
    started_at = perf_counter()
    try:
        page = await curated_repo.list_curated_features(
            session,
            theme_id=theme_id,
            theme_slug=theme_slug,
            source_id=source_id,
            provider=provider,
            dataset_key=dataset_key,
            curation_status=curation_status,
            include_archived=include_archived,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedFeaturesResponse(
        data=CuratedFeaturesData(items=[_feature_view(row) for row in page.items]),
        meta=make_meta(started_at=started_at, next_cursor=page.next_cursor),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.get(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def get_admin_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    row = await _feature_or_404(session, curated_feature_id, include_archived=True)
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}/detail-snapshot",
    response_model=CuratedFeatureDetailSnapshotResponse,
)
@admin_router.get(
    "/curated-features/{curated_feature_id}/detail-snapshot",
    response_model=CuratedFeatureDetailSnapshotResponse,
    include_in_schema=False,
)
async def get_admin_curated_feature_detail_snapshot_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureDetailSnapshotResponse:
    started_at = perf_counter()
    row = await curated_repo.get_curated_feature_detail_snapshot(
        session,
        curated_feature_id=curated_feature_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureDetailSnapshotResponse(
        data=_snapshot_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}/place-search",
    response_model=CuratedPlaceSearchResponse,
)
@admin_router.get(
    "/curated-features/{curated_feature_id}/place-search",
    response_model=CuratedPlaceSearchResponse,
    include_in_schema=False,
)
async def search_admin_curated_feature_places_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(min_length=1)] = None,
) -> CuratedPlaceSearchResponse:
    started_at = perf_counter()
    feature = await _feature_or_404(session, curated_feature_id, include_archived=True)
    query = (
        q
        or feature.display_title
        or feature.feature_name
        or feature.source_name
    ).strip()
    if not query:
        raise HTTPException(status_code=400, detail="검색어 q가 필요합니다")
    data = await _direct_place_search(query)
    return CuratedPlaceSearchResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@admin_router.post("/features/curated", response_model=CuratedFeatureResponse)
@admin_router.post(
    "/curated-features",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def create_admin_curated_feature_route(
    body: CuratedFeatureCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.create_curated_feature(
                session,
                **body.model_dump(),
            )
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.patch(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def patch_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeaturePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.update_curated_feature(
                session,
                curated_feature_id=curated_feature_id,
                updates=body.model_dump(exclude_unset=True),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.delete(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.delete(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def delete_admin_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with session.begin():
        row = await curated_repo.archive_curated_feature(
            session,
            curated_feature_id=curated_feature_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/features/curated/{curated_feature_id}/select",
    response_model=CuratedFeatureResponse,
)
@admin_router.post(
    "/curated-features/{curated_feature_id}/select",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def select_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeatureStatusRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with session.begin():
        row = await curated_repo.set_curated_feature_status(
            session,
            curated_feature_id=curated_feature_id,
            curation_status="curated",
            actor=body.actor,
            reason=body.reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/features/curated/{curated_feature_id}/unselect",
    response_model=CuratedFeatureResponse,
)
@admin_router.post(
    "/curated-features/{curated_feature_id}/unselect",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def unselect_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeatureStatusRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with session.begin():
        row = await curated_repo.set_curated_feature_status(
            session,
            curated_feature_id=curated_feature_id,
            curation_status="rejected",
            actor=body.actor,
            reason=body.reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/curated-themes", response_model=CuratedThemesResponse)
async def list_admin_curated_themes_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    visibility: Annotated[ThemeVisibility | None, Query()] = None,
    theme_group: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedThemesResponse:
    return await list_curated_themes_route(
        session=session,
        visibility=visibility,
        theme_group=theme_group,
        limit=limit,
    )


@admin_router.post("/curated-themes", response_model=CuratedThemeResponse)
async def create_admin_curated_theme_route(
    body: CuratedThemeCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.create_curated_theme(session, **body.model_dump())
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch("/curated-themes/{theme_id}", response_model=CuratedThemeResponse)
async def patch_admin_curated_theme_route(
    theme_id: str,
    body: CuratedThemePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.update_curated_theme(
                session,
                theme_id=theme_id,
                updates=body.model_dump(exclude_unset=True),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated theme 없음")
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/curated-sources", response_model=CuratedSourcesResponse)
async def list_admin_curated_sources_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    provider_status: Annotated[ProviderStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourcesResponse:
    return await list_curated_sources_route(
        session=session,
        provider=provider,
        dataset_key=dataset_key,
        provider_status=provider_status,
        limit=limit,
    )


@admin_router.post("/curated-sources", response_model=CuratedSourceResponse)
async def create_admin_curated_source_route(
    body: CuratedSourceCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.create_curated_source(session, **body.model_dump())
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedSourceResponse(
        data=_source_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/curated-sources/{source_id}",
    response_model=CuratedSourceResponse,
)
async def patch_admin_curated_source_route(
    source_id: str,
    body: CuratedSourcePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.update_curated_source(
                session,
                source_id=source_id,
                updates=body.model_dump(exclude_unset=True),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source 없음")
    return CuratedSourceResponse(
        data=_source_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/curated-source-rules",
    response_model=CuratedSourceRulesResponse,
)
async def list_admin_curated_source_rules_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_id: Annotated[str | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    source_id: Annotated[str | None, Query()] = None,
    provider: Annotated[str | None, Query()] = None,
    dataset_key: Annotated[str | None, Query()] = None,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourceRulesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_source_rules(
        session,
        theme_id=theme_id,
        theme_slug=theme_slug,
        source_id=source_id,
        provider=provider,
        dataset_key=dataset_key,
        enabled=enabled,
        limit=limit,
    )
    return CuratedSourceRulesResponse(
        data=CuratedSourceRulesData(items=[_rule_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/curated-source-rules",
    response_model=CuratedSourceRuleResponse,
)
async def create_admin_curated_source_rule_route(
    body: CuratedSourceRuleCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.create_curated_source_rule(
                session,
                **body.model_dump(),
            )
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/curated-source-rules/{rule_id}",
    response_model=CuratedSourceRuleResponse,
)
async def patch_admin_curated_source_rule_route(
    rule_id: str,
    body: CuratedSourceRulePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            row = await curated_repo.update_curated_source_rule(
                session,
                rule_id=rule_id,
                updates=body.model_dump(exclude_unset=True),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source rule 없음")
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/curated-source-rules/{rule_id}/apply",
    response_model=RuleApplyResponse,
)
async def apply_admin_curated_source_rule_route(
    rule_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RuleApplyResponse:
    started_at = perf_counter()
    async with session.begin():
        result = await curated_repo.apply_curated_source_rule(session, rule_id=rule_id)
    return RuleApplyResponse(
        data=RuleApplyData(
            rule_id=result.rule_id,
            inserted_or_updated=result.inserted_or_updated,
        ),
        meta=make_meta(started_at=started_at),
    )
