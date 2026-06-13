"""``/v1/public/*`` — 공개 해수욕장/축제 view API (T-222b).

TripMate 등 downstream 서비스가 그대로 소비하기 좋은 domain view를 제공한다.
원천 Feature 상세와 달리 provider/raw/debug 필드는 숨기고, 공개 화면에 필요한
projection만 닫힌 schema로 노출한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra import public_views_repo
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "router",
    "BeachPublicView",
    "FestivalPublicView",
    "PublicBeachListResponse",
    "PublicFestivalMonthlyResponse",
    "PublicMapMarkerLayerResponse",
]

router = APIRouter(prefix="/public", tags=["public"])

_KST = ZoneInfo("Asia/Seoul")


class BeachPublicView(BaseModel):
    """해수욕장 공개 상세/목록 view."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    display_name: str
    lon: float | None = None
    lat: float | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    legal_dong_code: str | None = None
    address: dict[str, Any]
    road_address: str | None = None
    jibun_address: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    beach_kind: str | None = None
    beach_width_m: float | None = None
    beach_length_m: float | None = None
    beach_material: str | None = None
    emergency_contact: str | None = None
    homepage_url: str | None = None
    image_url: str | None = None
    latest_water_quality: dict[str, Any] | None = None
    upcoming_index_forecasts: list[dict[str, Any]] = Field(default_factory=list)
    latest_weather: dict[str, Any] | None = None
    source_providers: list[str]
    updated_at: datetime


class FestivalPublicView(BaseModel):
    """축제 공개 상세/목록 view."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    festival_name: str
    venue_name: str | None = None
    event_start_date: date | None = None
    event_end_date: date | None = None
    event_status: Literal["scheduled", "ongoing", "ended", "unknown"]
    lon: float | None = None
    lat: float | None = None
    address: dict[str, Any]
    road_address: str | None = None
    jibun_address: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    festival_content: str | None = None
    organizer_name: str | None = None
    provider_org_name: str | None = None
    auspc_instt_name: str | None = None
    suprt_instt_name: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    reference_date: date | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    source_providers: list[str]
    updated_at: datetime


class PublicMapMarker(BaseModel):
    """공개 지도 layer marker 1건."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    lon: float
    lat: float
    sigungu_code: str | None = None


class PublicMapMarkerLayerData(BaseModel):
    """공개 지도 layer marker data payload."""

    model_config = ConfigDict(extra="forbid")

    layer_key: Literal["beach", "festival"]
    display_name: str
    marker_icon: str
    marker_color: str
    items: list[PublicMapMarker]


class PublicMapMarkerLayerResponse(BaseModel):
    """공개 지도 layer marker 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicMapMarkerLayerData
    meta: Meta


class PublicBeachListData(BaseModel):
    """해수욕장 공개 목록 data payload."""

    model_config = ConfigDict(extra="forbid")

    items: list[BeachPublicView]


class PublicBeachListResponse(BaseModel):
    """``GET /public/beaches`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicBeachListData
    meta: Meta


class PublicBeachDetailResponse(BaseModel):
    """``GET /public/beaches/{feature_id}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: BeachPublicView
    meta: Meta


class PublicFestivalMonth(BaseModel):
    """월별 축제 count summary."""

    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    count: int


class PublicFestivalMonthlyData(BaseModel):
    """월별 축제 공개 목록 data payload."""

    model_config = ConfigDict(extra="forbid")

    months: list[PublicFestivalMonth]
    items: list[FestivalPublicView]


class PublicFestivalMonthlyResponse(BaseModel):
    """``GET /public/festivals/monthly`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicFestivalMonthlyData
    meta: Meta


class PublicFestivalDetailResponse(BaseModel):
    """``GET /public/festivals/{feature_id}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FestivalPublicView
    meta: Meta


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text is not None:
            return text
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if cleaned.endswith("m"):
                cleaned = cleaned[:-1].strip()
            if not cleaned:
                continue
            try:
                return float(cleaned)
            except ValueError:
                continue
    return None


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _event_status(
    starts_on: date | None,
    ends_on: date | None,
    *,
    today: date | None = None,
) -> Literal["scheduled", "ongoing", "ended", "unknown"]:
    if starts_on is None or ends_on is None:
        return "unknown"
    pivot = today or datetime.now(_KST).date()
    if starts_on <= pivot <= ends_on:
        return "ongoing"
    if starts_on > pivot:
        return "scheduled"
    return "ended"


def _month_range(year: int | None, month: int | None) -> tuple[date, date, int, int]:
    today = datetime.now(_KST).date()
    resolved_year = year if year is not None else today.year
    resolved_month = month if month is not None else today.month
    start = date(resolved_year, resolved_month, 1)
    if resolved_month == 12:
        next_start = date(resolved_year + 1, 1, 1)
    else:
        next_start = date(resolved_year, resolved_month + 1, 1)
    return start, next_start - timedelta(days=1), resolved_year, resolved_month


def _validate_bbox(
    *,
    min_lon: float | None,
    min_lat: float | None,
    max_lon: float | None,
    max_lat: float | None,
) -> None:
    values = (min_lon, min_lat, max_lon, max_lat)
    if any(value is None for value in values) and not all(
        value is None for value in values
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="bbox는 min_lon/min_lat/max_lon/max_lat를 모두 지정해야 합니다.",
        )
    if (
        min_lon is not None
        and min_lat is not None
        and max_lon is not None
        and max_lat is not None
        and (min_lon > max_lon or min_lat > max_lat)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="bbox min 값은 max 값보다 클 수 없습니다.",
        )


def _beach_view(
    row: public_views_repo.PublicBeachRow,
    *,
    include_quality: bool,
    include_forecast: bool,
) -> BeachPublicView:
    address = row.address
    detail = row.detail
    facility = _nested_dict(detail.get("facility_info"))
    phones = detail.get("phones")
    first_phone = phones[0] if isinstance(phones, list) and phones else None
    source_raw = row.source_raw_data
    return BeachPublicView(
        feature_id=row.feature_id,
        display_name=row.display_name,
        lon=row.lon,
        lat=row.lat,
        sido_code=row.sido_code,
        sigungu_code=row.sigungu_code,
        legal_dong_code=row.legal_dong_code,
        address=address,
        road_address=_text(address.get("road")),
        jibun_address=_text(address.get("legal")),
        marker_icon=row.marker_icon,
        marker_color=row.marker_color,
        beach_kind=_first_text(facility.get("beach_kind"), source_raw.get("beach_kind")),
        beach_width_m=_first_number(
            facility.get("beach_width_m"),
            facility.get("beachWid"),
            source_raw.get("beach_width_m"),
            source_raw.get("beachWid"),
        ),
        beach_length_m=_first_number(
            facility.get("beach_length_m"),
            facility.get("beachLen"),
            source_raw.get("beach_length_m"),
            source_raw.get("beachLen"),
        ),
        beach_material=_first_text(
            facility.get("beach_material"),
            facility.get("beach_type"),
            source_raw.get("beach_material"),
            source_raw.get("beach_type"),
        ),
        emergency_contact=_first_text(
            first_phone,
            facility.get("emergency_contact"),
            source_raw.get("emergency_contact"),
        ),
        homepage_url=_text(row.urls.get("homepage")),
        image_url=_first_text(facility.get("image_url"), source_raw.get("image_url")),
        latest_water_quality=None if include_quality else None,
        upcoming_index_forecasts=[] if include_forecast else [],
        latest_weather=None if include_forecast else None,
        source_providers=list(row.source_providers),
        updated_at=row.updated_at,
    )


def _festival_view(row: public_views_repo.PublicFestivalRow) -> FestivalPublicView:
    address = row.address
    detail = row.detail
    payload = _nested_dict(detail.get("payload"))
    source_raw = row.source_raw_data
    starts_on = _date_value(detail.get("starts_on"))
    ends_on = _date_value(detail.get("ends_on"))
    return FestivalPublicView(
        feature_id=row.feature_id,
        festival_name=row.festival_name,
        venue_name=_text(detail.get("venue_name")),
        event_start_date=starts_on,
        event_end_date=ends_on,
        event_status=_event_status(starts_on, ends_on),
        lon=row.lon,
        lat=row.lat,
        address=address,
        road_address=_text(address.get("road")),
        jibun_address=_text(address.get("legal")),
        sido_code=row.sido_code,
        sigungu_code=row.sigungu_code,
        festival_content=_first_text(source_raw.get("fstvl_co"), payload.get("content")),
        organizer_name=_first_text(payload.get("organizer_name"), source_raw.get("mnnst_nm")),
        provider_org_name=_first_text(
            payload.get("provider_org_name"), source_raw.get("instt_nm")
        ),
        auspc_instt_name=_text(source_raw.get("auspc_instt_nm")),
        suprt_instt_name=_text(source_raw.get("suprt_instt_nm")),
        phone_number=_text(detail.get("tel")),
        homepage_url=_first_text(row.urls.get("homepage"), source_raw.get("homepage_url")),
        reference_date=_date_value(source_raw.get("reference_date")),
        marker_icon=row.marker_icon,
        marker_color=row.marker_color,
        source_providers=list(row.source_providers),
        updated_at=row.updated_at,
    )


def _marker_view(row: public_views_repo.PublicMapMarkerRow) -> PublicMapMarker:
    return PublicMapMarker(
        feature_id=row.feature_id,
        name=row.name,
        lon=row.lon,
        lat=row.lat,
        sigungu_code=row.sigungu_code,
    )


@router.get("/beaches", response_model=PublicBeachListResponse)
async def list_public_beaches(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    sido_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    sigungu_code: Annotated[str | None, Query(min_length=5, max_length=5)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
    include_quality: bool = False,
    include_forecast: bool = False,
) -> PublicBeachListResponse:
    """해수욕장 공개 목록 view."""

    started = perf_counter()
    try:
        page = await public_views_repo.list_public_beaches(
            session,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            q=q,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicBeachListResponse(
        data=PublicBeachListData(
            items=[
                _beach_view(
                    row,
                    include_quality=include_quality,
                    include_forecast=include_forecast,
                )
                for row in page.items
            ]
        ),
        meta=make_meta(
            request,
            started_at=started,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get("/beaches/map-markers", response_model=PublicMapMarkerLayerResponse)
async def list_public_beach_markers(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    min_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    max_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    sido_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    sigungu_code: Annotated[str | None, Query(min_length=5, max_length=5)] = None,
    max_items: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> PublicMapMarkerLayerResponse:
    """해수욕장 공개 지도 marker layer."""

    started = perf_counter()
    _validate_bbox(
        min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
    )
    try:
        rows = await public_views_repo.list_public_beach_markers(
            session,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            max_items=max_items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicMapMarkerLayerResponse(
        data=PublicMapMarkerLayerData(
            layer_key="beach",
            display_name="해수욕장",
            marker_icon="beach",
            marker_color="P-07",
            items=[_marker_view(row) for row in rows],
        ),
        meta=make_meta(request, started_at=started),
    )


@router.get("/beaches/{feature_id}", response_model=PublicBeachDetailResponse)
async def get_public_beach(
    feature_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    include_quality: bool = False,
    include_forecast: bool = False,
) -> PublicBeachDetailResponse:
    """해수욕장 공개 상세 view."""

    started = perf_counter()
    row = await public_views_repo.get_public_beach(session, feature_id=feature_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"beach not found: {feature_id}")
    return PublicBeachDetailResponse(
        data=_beach_view(
            row,
            include_quality=include_quality,
            include_forecast=include_forecast,
        ),
        meta=make_meta(request, started_at=started),
    )


@router.get("/festivals/monthly", response_model=PublicFestivalMonthlyResponse)
async def list_public_festivals_monthly(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    year: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    sido_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    sigungu_code: Annotated[str | None, Query(min_length=5, max_length=5)] = None,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
    cursor: str | None = None,
    include_months: bool = True,
) -> PublicFestivalMonthlyResponse:
    """월별 활성 축제 공개 view."""

    started = perf_counter()
    month_start, month_end, _, _ = _month_range(year, month)
    try:
        page = await public_views_repo.list_public_festivals_monthly(
            session,
            month_start=month_start,
            month_end=month_end,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            page_size=page_size,
            cursor=cursor,
            include_months=include_months,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicFestivalMonthlyResponse(
        data=PublicFestivalMonthlyData(
            months=[
                PublicFestivalMonth(
                    year=month_summary.year,
                    month=month_summary.month,
                    count=month_summary.count,
                )
                for month_summary in page.months
            ],
            items=[_festival_view(row) for row in page.items],
        ),
        meta=make_meta(
            request,
            started_at=started,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get("/festivals/map-markers", response_model=PublicMapMarkerLayerResponse)
async def list_public_festival_markers(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    year: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    min_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    min_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    max_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    max_items: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> PublicMapMarkerLayerResponse:
    """축제 공개 지도 marker layer."""

    started = perf_counter()
    _validate_bbox(
        min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
    )
    month_start, month_end, _, _ = _month_range(year, month)
    try:
        rows = await public_views_repo.list_public_festival_markers(
            session,
            month_start=month_start,
            month_end=month_end,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            max_items=max_items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicMapMarkerLayerResponse(
        data=PublicMapMarkerLayerData(
            layer_key="festival",
            display_name="축제",
            marker_icon="star",
            marker_color="P-11",
            items=[_marker_view(row) for row in rows],
        ),
        meta=make_meta(request, started_at=started),
    )


@router.get("/festivals/{feature_id}", response_model=PublicFestivalDetailResponse)
async def get_public_festival(
    feature_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PublicFestivalDetailResponse:
    """축제 공개 상세 view."""

    started = perf_counter()
    row = await public_views_repo.get_public_festival(session, feature_id=feature_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"festival not found: {feature_id}")
    return PublicFestivalDetailResponse(
        data=_festival_view(row),
        meta=make_meta(request, started_at=started),
    )
