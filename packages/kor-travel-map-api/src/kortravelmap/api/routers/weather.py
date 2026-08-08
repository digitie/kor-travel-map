"""``/v1/features/*`` — feature 하위 weather forecast/history API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from kortravelmap.infra import weather_repo
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.feature_ref import resolve_feature_ref_or_error
from kortravelmap.api.identity_projection import response_feature_id
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "AdminWeatherAlertHistoryResponse",
    "PublicWeatherAlertHistoryResponse",
    "PublicWeatherForecastResponse",
    "admin_router",
    "router",
]

router = APIRouter(prefix="/features", tags=["features"])
admin_router = APIRouter(prefix="/admin/features", tags=["admin-features"])


class WeatherAnchorOut(BaseModel):
    """예보/관측값을 제공한 weather anchor feature."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    lon: float | None = None
    lat: float | None = None
    distance_m: float | None = None


class PublicWeatherValueItem(BaseModel):
    """weather timeline row 1건."""

    model_config = ConfigDict(extra="forbid")

    weather_value_key: str
    feature_id: str
    provider_dataset_id: int
    dataset_key: str
    dataset_display_name: str
    provider: str
    weather_domain: str
    forecast_style: str
    timeline_bucket: str | None = None
    metric_key: str
    metric_name: str | None = None
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    severity: str | None = None
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None
    known_at: datetime


class PublicWeatherForecastData(BaseModel):
    """``GET /features/.../weather/forecast`` data payload."""

    model_config = ConfigDict(extra="forbid")

    target_feature_id: str | None = None
    # T-VN-32C 리뷰 F2 — 경계 해석 결과의 UUID 정본 병행 노출 (additive,
    # feature 참조 variant에서만 채워진다).
    target_feature_uuid: str | None = None
    target_lon: float | None = None
    target_lat: float | None = None
    radius_m: float
    history_from: datetime
    anchor: WeatherAnchorOut | None = None
    items: list[PublicWeatherValueItem]


class PublicWeatherForecastResponse(BaseModel):
    """공개 weather forecast timeline 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicWeatherForecastData
    meta: Meta


class PublicWeatherAlertHistoryItem(BaseModel):
    """공개 KMA 기상특보 typed 이력 row 1건."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str | None = None
    feature_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    phenomenon: str | None = None
    alert_type: str | None = None
    level: str | None = None
    title: str | None = None
    description: str | None = None
    issued_at: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source_agency: str | None = None


class PublicWeatherAlertHistoryData(BaseModel):
    """``GET /features/weather/alerts`` data payload."""

    model_config = ConfigDict(extra="forbid")

    history_from: datetime
    items: list[PublicWeatherAlertHistoryItem]


class PublicWeatherAlertHistoryResponse(BaseModel):
    """공개 KMA 기상특보 typed 이력 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PublicWeatherAlertHistoryData
    meta: Meta


class AdminWeatherAlertHistoryItem(BaseModel):
    """operator KMA 기상특보 raw lineage row 1건."""

    model_config = ConfigDict(extra="forbid")

    source_record_key: str
    feature_id: str | None = None
    feature_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    phenomenon: str | None = None
    alert_type: str | None = None
    level: str | None = None
    title: str | None = None
    description: str | None = None
    issued_at: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source_agency: str | None = None
    fetched_at: datetime | None = None
    imported_at: datetime | None = None
    last_seen_at: datetime | None = None
    payload: dict[str, Any]


class AdminWeatherAlertHistoryData(BaseModel):
    """operator ``GET /admin/features/weather/alerts`` data payload."""

    model_config = ConfigDict(extra="forbid")

    history_from: datetime
    items: list[AdminWeatherAlertHistoryItem]


class AdminWeatherAlertHistoryResponse(BaseModel):
    """operator KMA 기상특보 raw lineage 이력 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminWeatherAlertHistoryData
    meta: Meta


def _float_decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _anchor_out(anchor: weather_repo.WeatherAnchor | None) -> WeatherAnchorOut | None:
    if anchor is None:
        return None
    # T-VN-32C PR-2 — 응답 feature_id 값은 UUID 정본 (결측은 projection 버그).
    return WeatherAnchorOut(
        feature_id=response_feature_id(anchor),
        name=anchor.name,
        lon=anchor.lon,
        lat=anchor.lat,
        distance_m=anchor.distance_m,
    )


def _public_value_out(
    value: weather_repo.WeatherValueTimelineRow,
    *,
    anchor_feature_uuid: str,
) -> PublicWeatherValueItem:
    # timeline row SQL은 feature 테이블을 join하지 않는다 — 전 row가 anchor
    # feature 소속이므로 anchor의 UUID 정본을 그대로 쓴다 (T-VN-32C PR-2).
    return PublicWeatherValueItem(
        weather_value_key=value.weather_value_key,
        feature_id=anchor_feature_uuid,
        provider_dataset_id=_require_provider_dataset_id(value),
        dataset_key=_require_dataset_key(value),
        dataset_display_name=_require_dataset_display_name(value),
        provider=value.provider,
        weather_domain=value.weather_domain,
        forecast_style=value.forecast_style,
        timeline_bucket=value.timeline_bucket,
        metric_key=value.metric_key,
        metric_name=value.metric_name,
        value_number=_float_decimal(value.value_number),
        value_text=value.value_text,
        unit=value.unit,
        severity=value.severity,
        issued_at=value.issued_at,
        valid_at=value.valid_at,
        valid_from=value.valid_from,
        valid_until=value.valid_until,
        observed_at=value.observed_at,
        known_at=value.known_at or value.collected_at,
    )


def _require_provider_dataset_id(value: weather_repo.WeatherValueTimelineRow) -> int:
    if value.provider_dataset_id is None:
        raise ValueError("weather timeline row에 provider_dataset_id가 없습니다")
    return value.provider_dataset_id


def _require_dataset_key(value: weather_repo.WeatherValueTimelineRow) -> str:
    if not value.dataset_key:
        raise ValueError("weather timeline row에 dataset_key가 없습니다")
    return value.dataset_key


def _require_dataset_display_name(value: weather_repo.WeatherValueTimelineRow) -> str:
    if not value.dataset_display_name:
        raise ValueError("weather timeline row에 dataset_display_name이 없습니다")
    return value.dataset_display_name


def _alert_response_feature_id(value: weather_repo.WeatherAlertHistoryRow) -> str | None:
    """alert row의 응답 feature 참조 — 연결 feature 없으면 None (LEFT JOIN).

    feature_id가 있는데 feature_uuid가 없으면 projection 결함이므로 fail-close.
    """
    if value.feature_id is None:
        return None
    if not value.feature_uuid:
        raise ValueError(
            "weather alert row에 feature_uuid가 없습니다 — projection 누락 (T-VN-32C)"
        )
    return value.feature_uuid


def _public_alert_out(
    value: weather_repo.WeatherAlertHistoryRow,
) -> PublicWeatherAlertHistoryItem:
    return PublicWeatherAlertHistoryItem(
        feature_id=_alert_response_feature_id(value),
        feature_name=value.feature_name,
        region_code=value.region_code,
        region_name=value.region_name,
        phenomenon=value.phenomenon,
        alert_type=value.alert_type,
        level=value.level,
        title=value.title,
        description=value.description,
        issued_at=value.issued_at,
        effective_from=value.effective_from,
        effective_until=value.effective_until,
        source_agency=value.source_agency,
    )


def _admin_alert_out(
    value: weather_repo.WeatherAlertHistoryRow,
) -> AdminWeatherAlertHistoryItem:
    return AdminWeatherAlertHistoryItem(
        source_record_key=value.source_record_key,
        feature_id=_alert_response_feature_id(value),
        feature_name=value.feature_name,
        region_code=value.region_code,
        region_name=value.region_name,
        phenomenon=value.phenomenon,
        alert_type=value.alert_type,
        level=value.level,
        title=value.title,
        description=value.description,
        issued_at=value.issued_at,
        effective_from=value.effective_from,
        effective_until=value.effective_until,
        source_agency=value.source_agency,
        fetched_at=value.fetched_at,
        imported_at=value.imported_at,
        last_seen_at=value.last_seen_at,
        payload=value.payload,
    )


async def _forecast_response(
    request: Request,
    session: AsyncSession,
    *,
    target_feature_id: str | None,
    target_feature_uuid: str | None,
    target_lon: float | None,
    target_lat: float | None,
    anchor: weather_repo.WeatherAnchor | None,
    radius_m: float,
    history_from: datetime,
    forecast_style: list[str] | None,
    weather_domain: list[str] | None,
    metric_key: list[str] | None,
    issued_from: datetime | None,
    issued_to: datetime | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
    limit: int,
    started_at: float,
) -> PublicWeatherForecastResponse:
    items: list[PublicWeatherValueItem] = []
    if anchor is not None:
        rows = await weather_repo.list_weather_values(
            session,
            feature_id=anchor.feature_id,
            forecast_styles=forecast_style,
            weather_domains=weather_domain,
            metric_keys=metric_key,
            history_from=history_from,
            issued_from=issued_from,
            issued_to=issued_to,
            valid_from=valid_from,
            valid_to=valid_to,
            limit=limit,
        )
        anchor_uuid = response_feature_id(anchor)
        items = [_public_value_out(row, anchor_feature_uuid=anchor_uuid) for row in rows]
    return PublicWeatherForecastResponse(
        data=PublicWeatherForecastData(
            target_feature_id=target_feature_id,
            target_feature_uuid=target_feature_uuid,
            target_lon=target_lon,
            target_lat=target_lat,
            radius_m=radius_m,
            history_from=history_from,
            anchor=_anchor_out(anchor),
            items=items,
        ),
        meta=make_meta(request, started_at=started_at, page_size=limit),
    )


@router.get(
    "/weather/forecast",
    response_model=PublicWeatherForecastResponse,
    summary="좌표 기반 weather forecast timeline",
)
async def get_weather_forecast_by_coordinate(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    lon: Annotated[float, Query(ge=-180, le=180, description="경도(WGS84).")],
    lat: Annotated[float, Query(ge=-90, le=90, description="위도(WGS84).")],
    radius_m: Annotated[
        float,
        Query(ge=100, le=100_000, description="nearest weather anchor 탐색 반경(m)."),
    ] = 50_000,
    forecast_style: Annotated[
        list[str] | None,
        Query(description="forecast_style 필터. 반복 지정 가능."),
    ] = None,
    weather_domain: Annotated[
        list[str] | None,
        Query(description="weather_domain 필터. 반복 지정 가능."),
    ] = None,
    metric_key: Annotated[
        list[str] | None,
        Query(description="metric_key 필터. 반복 지정 가능."),
    ] = None,
    issued_from: Annotated[datetime | None, Query(description="발표시각 시작.")] = None,
    issued_to: Annotated[datetime | None, Query(description="발표시각 종료.")] = None,
    valid_from: Annotated[datetime | None, Query(description="예보 유효시각 시작.")] = None,
    valid_to: Annotated[datetime | None, Query(description="예보 유효시각 종료.")] = None,
    history_days: Annotated[
        int,
        Query(ge=1, le=weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS),
    ] = weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> PublicWeatherForecastResponse:
    started_at = perf_counter()
    history_from = weather_repo.weather_history_floor(retention_days=history_days)
    anchor = await weather_repo.nearest_weather_feature_for_coordinate(
        session,
        lon=lon,
        lat=lat,
        radius_m=radius_m,
    )
    return await _forecast_response(
        request,
        session,
        target_feature_id=None,
        target_feature_uuid=None,
        target_lon=lon,
        target_lat=lat,
        anchor=anchor,
        radius_m=radius_m,
        history_from=history_from,
        forecast_style=forecast_style,
        weather_domain=weather_domain,
        metric_key=metric_key,
        issued_from=issued_from,
        issued_to=issued_to,
        valid_from=valid_from,
        valid_to=valid_to,
        limit=limit,
        started_at=started_at,
    )


@router.get(
    "/{feature_id}/weather/forecast",
    response_model=PublicWeatherForecastResponse,
    summary="feature 기준 nearest weather forecast timeline",
)
async def get_weather_forecast_by_feature(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
    radius_m: Annotated[
        float,
        Query(ge=100, le=100_000, description="nearest weather anchor 탐색 반경(m)."),
    ] = 50_000,
    forecast_style: Annotated[
        list[str] | None,
        Query(description="forecast_style 필터. 반복 지정 가능."),
    ] = None,
    weather_domain: Annotated[
        list[str] | None,
        Query(description="weather_domain 필터. 반복 지정 가능."),
    ] = None,
    metric_key: Annotated[
        list[str] | None,
        Query(description="metric_key 필터. 반복 지정 가능."),
    ] = None,
    issued_from: Annotated[datetime | None, Query(description="발표시각 시작.")] = None,
    issued_to: Annotated[datetime | None, Query(description="발표시각 종료.")] = None,
    valid_from: Annotated[datetime | None, Query(description="예보 유효시각 시작.")] = None,
    valid_to: Annotated[datetime | None, Query(description="예보 유효시각 종료.")] = None,
    history_days: Annotated[
        int,
        Query(ge=1, le=weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS),
    ] = weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> PublicWeatherForecastResponse:
    started_at = perf_counter()
    # T-VN-32C 리뷰 F2 — 같은 `/features/{feature_id}` 계열의 경계 해석 규칙 통일:
    # legacy·UUID 양형식 수용, 형식 오류 422, 미존재 404. 내부 전달은 정본 legacy 키.
    identity = await resolve_feature_ref_or_error(session, feature_id)
    history_from = weather_repo.weather_history_floor(retention_days=history_days)
    anchor = await weather_repo.nearest_weather_feature_for_feature(
        session,
        feature_id=identity.feature_id,
        radius_m=radius_m,
    )
    return await _forecast_response(
        request,
        session,
        # T-VN-32C PR-2 — 응답의 feature 참조 값은 UUID 정본(echo 예외 아님).
        target_feature_id=str(identity.feature_uuid),
        target_feature_uuid=str(identity.feature_uuid),
        target_lon=None,
        target_lat=None,
        anchor=anchor,
        radius_m=radius_m,
        history_from=history_from,
        forecast_style=forecast_style,
        weather_domain=weather_domain,
        metric_key=metric_key,
        issued_from=issued_from,
        issued_to=issued_to,
        valid_from=valid_from,
        valid_to=valid_to,
        limit=limit,
        started_at=started_at,
    )


@router.get(
    "/weather/alerts",
    response_model=PublicWeatherAlertHistoryResponse,
    summary="KMA 기상특보 이력",
)
async def list_weather_alert_history(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    region_code: Annotated[
        str | None,
        Query(description="KMA 특보 구역 코드 필터."),
    ] = None,
    phenomenon: Annotated[
        str | None,
        Query(description="현상 토큰 필터(예: 호우, 폭염, weather_alert)."),
    ] = None,
    level: Annotated[
        str | None,
        Query(description="특보 등급 필터(예: 주의보, 경보)."),
    ] = None,
    issued_from: Annotated[datetime | None, Query(description="발표시각 시작.")] = None,
    issued_to: Annotated[datetime | None, Query(description="발표시각 종료.")] = None,
    history_days: Annotated[
        int,
        Query(ge=1, le=weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS),
    ] = weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS,
    limit: Annotated[int, Query(ge=1, le=5000)] = 200,
) -> PublicWeatherAlertHistoryResponse:
    started_at = perf_counter()
    history_from = weather_repo.weather_history_floor(retention_days=history_days)
    rows = await weather_repo.list_kma_weather_alert_history(
        session,
        region_code=region_code,
        phenomenon=phenomenon,
        level=level,
        history_from=history_from,
        issued_from=issued_from,
        issued_to=issued_to,
        limit=limit,
    )
    return PublicWeatherAlertHistoryResponse(
        data=PublicWeatherAlertHistoryData(
            history_from=history_from,
            items=[_public_alert_out(row) for row in rows],
        ),
        meta=make_meta(request, started_at=started_at, page_size=limit),
    )


@admin_router.get(
    "/weather/alerts",
    response_model=AdminWeatherAlertHistoryResponse,
    summary="KMA 기상특보 raw lineage 이력",
)
async def list_admin_weather_alert_history(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    region_code: Annotated[
        str | None,
        Query(description="KMA 특보 구역 코드 필터."),
    ] = None,
    phenomenon: Annotated[
        str | None,
        Query(description="현상 토큰 필터(예: 호우, 폭염, weather_alert)."),
    ] = None,
    level: Annotated[
        str | None,
        Query(description="특보 등급 필터(예: 주의보, 경보)."),
    ] = None,
    issued_from: Annotated[datetime | None, Query(description="발표시각 시작.")] = None,
    issued_to: Annotated[datetime | None, Query(description="발표시각 종료.")] = None,
    history_days: Annotated[
        int,
        Query(ge=1, le=weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS),
    ] = weather_repo.DEFAULT_WEATHER_HISTORY_RETENTION_DAYS,
    limit: Annotated[int, Query(ge=1, le=5000)] = 200,
) -> AdminWeatherAlertHistoryResponse:
    started_at = perf_counter()
    history_from = weather_repo.weather_history_floor(retention_days=history_days)
    rows = await weather_repo.list_kma_weather_alert_history(
        session,
        region_code=region_code,
        phenomenon=phenomenon,
        level=level,
        history_from=history_from,
        issued_from=issued_from,
        issued_to=issued_to,
        limit=limit,
    )
    return AdminWeatherAlertHistoryResponse(
        data=AdminWeatherAlertHistoryData(
            history_from=history_from,
            items=[_admin_alert_out(row) for row in rows],
        ),
        meta=make_meta(request, started_at=started_at, page_size=limit),
    )
