"""``/v1/service/weather/*`` — Valkey의 weather 현재·예보·세 구간 요약 읽기 (ADR-114 2단계).

PinVi 같은 service 소비자가 장소 하나에 날씨를 붙이는 흐름(좌표 → 가까운 weather 위치 → 관측·예보·
요약)을 요청 하나로 끝내게 한다. 값은 Map Dagster ``weather_state_*`` job이 Valkey에 세대 단위로
교체해 둔 것이고(``infra.valkey_state``), 여기서는 지금 세대를 읽기만 한다. 설계 정본은 ADR-114
"구현 설계 — 2단계" W5·W7.

- ``/locations``: 위치 목록(keyset cursor)·근처·영역. ``include_current=true``면 최신 관측을 붙인다.
- ``/locations/{feature_id}``·``/nearest``: 위치 하나의 **묶음**(위치 + 관측 + 예보 + 세 구간 요약).
  각 부분은 자기 데이터셋의 ``status``·``freshness``를 갖고, 한 데이터셋 장애가 묶음을 막지 않는다.
- 예보는 **읽을 때** 지금보다 이른 ``target_at``을 뗀다(W5). 세 구간 요약은 전날 같은 구간 대비
  차이(``vs_previous_day``)를 싣는다.
- 위치 데이터셋이 없거나 Valkey가 죽었으면 503, cursor 세대가 사라졌으면 409, 위치가 없으면 404.
  다른 Map 기능과 ``/ops/health-deep``은 Valkey를 보지 않는다.

이 표면은 ADR-105(Map은 weather를 서빙하지 않는다)의 **유일한 예외**다(ADR-114가 부분 대체) —
``tests/test_api_serves_no_weather.py``가 이 접두사만 빼고 계속 지킨다.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from kortravelmap.dto.weather_state import (
    WeatherCurrentState,
    WeatherDailySlotState,
    WeatherDailySummaryState,
    WeatherForecastGroupState,
    WeatherForecastState,
    WeatherForecastStyle,
    WeatherLocationState,
    WeatherObservationState,
)
from kortravelmap.infra.valkey_state import (
    GEO_LAT_LIMIT,
    GenerationMeta,
    StateGenerationExpired,
    StateNotLoaded,
    StateStoreError,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_CURRENT,
    DATASET_DAILY_SUMMARIES,
    DATASET_LOCATIONS,
    FORECAST_DATASETS,
    WEATHER_STATE_DATASETS,
    WeatherStateDataset,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from kortravelmap.api.auth import require_service_token
from kortravelmap.api.response import Meta, ProblemDetail, make_meta
from kortravelmap.api.routers.service_transport import (
    MAX_RADIUS_M,
    QueryDep,
    _decode_cursor,
    _encode_cursor,
    _Query,
    bbox_search_box,
)
from kortravelmap.api.transport_state_service import shared_state_store

__all__ = ["service_router"]

service_router = APIRouter(
    prefix="/service/weather",
    tags=["service-weather-state"],
    dependencies=[Depends(require_service_token)],
)

DEFAULT_NEAREST_RADIUS_M = 20_000.0


def _problem(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, "details": {}}
    )


def _unavailable(message: str) -> HTTPException:
    return _problem(status.HTTP_503_SERVICE_UNAVAILABLE, "WEATHER_STATE_UNAVAILABLE", message)


async def get_weather_state_store() -> ValkeyStateStore:
    """FastAPI 의존성 — transport 표면과 같은 프로세스 단위 store. 설정이 없으면 503."""
    try:
        return shared_state_store()
    except StateStoreError as exc:
        raise _unavailable(str(exc)) from exc


StoreDep = Annotated[ValkeyStateStore, Depends(get_weather_state_store)]


@asynccontextmanager
async def _state_errors() -> AsyncIterator[None]:
    try:
        yield
    except StateNotLoaded as exc:
        raise _problem(
            status.HTTP_503_SERVICE_UNAVAILABLE, "WEATHER_STATE_NOT_LOADED", str(exc)
        ) from exc
    except StateGenerationExpired as exc:
        raise _problem(
            status.HTTP_409_CONFLICT, "WEATHER_STATE_GENERATION_EXPIRED", str(exc)
        ) from exc
    except StateStoreError as exc:
        raise _unavailable(str(exc)) from exc


# -- 응답 모델 -----------------------------------------------------------------


class WeatherStateFreshness(BaseModel):
    """세대 하나의 신선도(ADR-114 W4)."""

    model_config = ConfigDict(extra="forbid")

    dataset: str
    generation: str
    source_collected_at: AwareDatetime | None = Field(
        description="weather 원천 수집 시각(페이지 중 가장 이른 값). 위치 roster는 언제나 null."
    )
    source_status: Literal["ok", "stale"] | None = Field(
        description="weather가 알린 집합 상태. stale = weather가 마지막 성공 집합을 그대로 줬다."
    )
    loaded_at: AwareDatetime = Field(description="Map이 이 세대로 교체한 시각.")
    age_seconds: int = Field(description="source_collected_at(없으면 loaded_at)부터 지금까지.")
    max_age_seconds: int
    stale: bool = Field(description="age_seconds > max_age_seconds. stale이어도 값은 준다.")
    item_count: int


SectionStatus = Literal["ok", "not_loaded", "unavailable", "no_data"]
_SECTION_STATUS_DOC = (
    "ok · not_loaded(데이터셋이 아직 한 번도 적재 전) · unavailable(그 데이터셋만 읽지 못함) · "
    "no_data(데이터셋은 있으나 이 위치 항목이 없음)."
)


class WeatherLocationOut(WeatherLocationState):
    distance_m: float | None = Field(default=None, description="근처 검색일 때 중심에서의 거리.")
    observations: list[WeatherObservationState] | None = Field(
        default=None,
        description=(
            "include_current=true일 때 최신 관측(관측 데이터셋이 없거나 항목이 없으면 null)."
        ),
    )


class WeatherLocationListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WeatherLocationOut]
    truncated: bool = Field(description="근처·영역 검색이 limit에 닿았다(더 있을 수 있다).")
    freshness: WeatherStateFreshness
    current_freshness: WeatherStateFreshness | None = Field(
        default=None, description="include_current=true일 때 관측 데이터셋 신선도(적재 전 null)."
    )


class WeatherLocationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: WeatherLocationListData
    meta: Meta


class WeatherCurrentSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus = Field(description=_SECTION_STATUS_DOC)
    freshness: WeatherStateFreshness | None
    observations: list[WeatherObservationState]


class WeatherForecastSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus = Field(description=_SECTION_STATUS_DOC)
    freshness: WeatherStateFreshness | None
    groups: list[WeatherForecastGroupState] = Field(
        description="provider별 묶음. 지금보다 이른 target_at과 그 자리 값은 뗐다(ADR-114 W5)."
    )


class WeatherForecastSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ultra_short: WeatherForecastSection | None = None
    short: WeatherForecastSection | None = None
    mid: WeatherForecastSection | None = None
    external: WeatherForecastSection | None = None


class WeatherSlotDelta(BaseModel):
    """전날 같은 구간 대비 차이(이쪽 − 전날). 둘 중 하나가 없으면 그 값은 null."""

    model_config = ConfigDict(extra="forbid")

    previous_date: dt.date
    temp_min_delta: float | None
    temp_max_delta: float | None
    temp_avg_delta: float | None
    humidity_avg_delta: float | None


class WeatherDailySlotOut(WeatherDailySlotState):
    vs_previous_day: WeatherSlotDelta | None = Field(
        default=None,
        description=(
            "전날 같은 구간과 비교. 전날 구간이 없거나 둘 중 하나가 sample_count=0이면 null."
        ),
    )


class WeatherDailySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus = Field(description=_SECTION_STATUS_DOC)
    freshness: WeatherStateFreshness | None
    slots: list[WeatherDailySlotOut] = Field(description="(date, slot) 오름차순.")


class WeatherBundleData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: WeatherLocationOut
    location_freshness: WeatherStateFreshness
    current: WeatherCurrentSection | None = Field(description="sections에 없으면 null.")
    forecasts: WeatherForecastSections = Field(description="forecast_styles에 든 style만 채운다.")
    daily_summaries: WeatherDailySection | None = Field(description="sections에 없으면 null.")


class WeatherBundleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: WeatherBundleData
    meta: Meta


class WeatherDatasetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    loaded: bool
    freshness: WeatherStateFreshness | None
    error: str | None = Field(
        default=None, description="이 데이터셋만 읽지 못했을 때 이유(나머지는 그대로 보인다)."
    )


class WeatherStatusData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store: Literal["ok"]
    datasets: list[WeatherDatasetStatus]


class WeatherStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: WeatherStatusData
    meta: Meta


_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ProblemDetail,
        "description": (
            "WEATHER_STATE_GENERATION_EXPIRED — cursor의 세대가 사라졌다. 처음부터 다시."
        ),
    },
    503: {
        "model": ProblemDetail,
        "description": (
            "WEATHER_STATE_UNAVAILABLE(Valkey 미설정·연결 실패) 또는 "
            "WEATHER_STATE_NOT_LOADED(위치 데이터셋이 아직 적재 전)."
        ),
    },
}
_DETAIL_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "NOT_FOUND — 지금 세대에 그 위치가 없다."},
    503: _ERROR_RESPONSES[503],
}


# -- 공통 ----------------------------------------------------------------------


def _freshness(dataset: WeatherStateDataset, meta: GenerationMeta) -> WeatherStateFreshness:
    reference = meta.source_collected_at or meta.loaded_at
    age = max(0, int((datetime.now(UTC) - reference).total_seconds()))
    max_age = int(dataset.max_age.total_seconds())
    source_status: Literal["ok", "stale"] | None = None
    if meta.source_status == "ok":
        source_status = "ok"
    elif meta.source_status == "stale":
        source_status = "stale"
    return WeatherStateFreshness(
        dataset=dataset.name,
        generation=meta.generation,
        source_collected_at=meta.source_collected_at,
        source_status=source_status,
        loaded_at=meta.loaded_at,
        age_seconds=age,
        max_age_seconds=max_age,
        stale=age > max_age,
        item_count=meta.count,
    )


_ModelT = TypeVar(
    "_ModelT",
    WeatherLocationOut,
    WeatherCurrentState,
    WeatherForecastState,
    WeatherDailySummaryState,
)


def _parse_values(
    model: type[_ModelT], ids: Sequence[str], raw: Sequence[bytes | None]
) -> list[_ModelT]:
    items: list[_ModelT] = []
    for feature_id, value in zip(ids, raw, strict=True):
        if value is None:
            raise _unavailable(f"상태 값이 없다: {feature_id}")
        try:
            items.append(model.model_validate_json(value))
        except ValidationError as exc:
            raise _unavailable(f"상태 값 모양이 다르다: {feature_id}") from exc
    return items


@dataclass(frozen=True, slots=True)
class _Joined:
    """다른 데이터셋에서 같은 위치 id로 읽은 결과."""

    status: SectionStatus
    meta: GenerationMeta | None
    values: dict[str, bytes]


async def _join(
    store: ValkeyStateStore, dataset: WeatherStateDataset, ids: Sequence[str]
) -> _Joined:
    """``dataset``의 지금 세대에서 ``ids``를 읽는다. 그 데이터셋 장애는 status로만 알린다."""
    try:
        meta = await store.current_meta(dataset.name)
        raw = await store.get_values(dataset.name, meta.generation, ids)
    except StateNotLoaded:
        return _Joined("not_loaded", None, {})
    except StateStoreError:
        return _Joined("unavailable", None, {})
    values = {feature_id: value for feature_id, value in zip(ids, raw, strict=True) if value}
    return _Joined("ok", meta, values)


def _decode(model: type[_ModelT], value: bytes | None) -> _ModelT | None:
    if value is None:
        return None
    try:
        return model.model_validate_json(value)
    except ValidationError:
        return None


def future_groups(
    groups: Sequence[WeatherForecastGroupState], now: datetime
) -> list[WeatherForecastGroupState]:
    """지금보다 이른 ``target_at``과 그 자리의 metric 값을 뗀다. 남는 시각이 없는 묶음은 뺀다."""
    kept: list[WeatherForecastGroupState] = []
    for group in groups:
        keep = [index for index, target in enumerate(group.target_at) if target >= now]
        if not keep:
            continue
        if len(keep) == len(group.target_at):
            kept.append(group)
            continue
        kept.append(
            group.model_copy(
                update={
                    "target_at": [group.target_at[i] for i in keep],
                    "metrics": {
                        name: [values[i] for i in keep] for name, values in group.metrics.items()
                    },
                }
            )
        )
    return kept


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def with_previous_day(slots: Sequence[WeatherDailySlotState]) -> list[WeatherDailySlotOut]:
    """구간마다 전날 같은 구간과의 차이를 붙인다(ADR-114 W7)."""
    by_key = {(slot.date, slot.slot): slot for slot in slots}
    out: list[WeatherDailySlotOut] = []
    for slot in slots:
        previous_date = slot.date - dt.timedelta(days=1)
        previous = by_key.get((previous_date, slot.slot))
        delta: WeatherSlotDelta | None = None
        if previous is not None and previous.sample_count > 0 and slot.sample_count > 0:
            delta = WeatherSlotDelta(
                previous_date=previous_date,
                temp_min_delta=_delta(slot.temp_min, previous.temp_min),
                temp_max_delta=_delta(slot.temp_max, previous.temp_max),
                temp_avg_delta=_delta(slot.temp_avg, previous.temp_avg),
                humidity_avg_delta=_delta(slot.humidity_avg, previous.humidity_avg),
            )
        out.append(WeatherDailySlotOut(**slot.model_dump(), vs_previous_day=delta))
    return out


FeatureIdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")]

Section = Literal["current", "forecasts", "daily_summaries"]
SectionsQuery = Annotated[
    list[Section] | None,
    Query(description="묶음에 담을 부분(반복 가능). 없으면 전부."),
]
StylesQuery = Annotated[
    list[WeatherForecastStyle] | None,
    Query(description="담을 예보 style(반복 가능). 없으면 네 가지 전부."),
]


async def _bundle(
    store: ValkeyStateStore,
    location: WeatherLocationOut,
    location_meta: GenerationMeta,
    *,
    sections: list[Section] | None,
    styles: list[WeatherForecastStyle] | None,
) -> WeatherBundleData:
    wanted = set(sections or ("current", "forecasts", "daily_summaries"))
    wanted_styles = set(styles or ("ultra_short", "short", "mid", "external"))
    ids = [location.feature_id]
    now = datetime.now(UTC)

    current: WeatherCurrentSection | None = None
    if "current" in wanted:
        joined = await _join(store, DATASET_CURRENT, ids)
        value = _decode(WeatherCurrentState, joined.values.get(location.feature_id))
        current = WeatherCurrentSection(
            status=_status(joined, value),
            freshness=_freshness(DATASET_CURRENT, joined.meta) if joined.meta else None,
            observations=list(value.observations) if value else [],
        )

    forecasts = WeatherForecastSections()
    if "forecasts" in wanted:
        sections_by_style: dict[str, WeatherForecastSection] = {}
        for dataset in FORECAST_DATASETS:
            assert dataset.style is not None
            if dataset.style not in wanted_styles:
                continue
            joined = await _join(store, dataset, ids)
            forecast = _decode(WeatherForecastState, joined.values.get(location.feature_id))
            groups = future_groups(forecast.groups, now) if forecast else []
            sections_by_style[dataset.style] = WeatherForecastSection(
                status=_status(joined, forecast),
                freshness=_freshness(dataset, joined.meta) if joined.meta else None,
                groups=groups,
            )
        forecasts = WeatherForecastSections(**sections_by_style)

    daily: WeatherDailySection | None = None
    if "daily_summaries" in wanted:
        joined = await _join(store, DATASET_DAILY_SUMMARIES, ids)
        summary = _decode(WeatherDailySummaryState, joined.values.get(location.feature_id))
        daily = WeatherDailySection(
            status=_status(joined, summary),
            freshness=_freshness(DATASET_DAILY_SUMMARIES, joined.meta) if joined.meta else None,
            slots=with_previous_day(summary.slots) if summary else [],
        )

    return WeatherBundleData(
        location=location,
        location_freshness=_freshness(DATASET_LOCATIONS, location_meta),
        current=current,
        forecasts=forecasts,
        daily_summaries=daily,
    )


def _status(joined: _Joined, value: object | None) -> SectionStatus:
    if joined.status != "ok":
        return joined.status
    return "ok" if value is not None else "no_data"


# -- 위치 목록 ----------------------------------------------------------------------


@service_router.get(
    "/locations",
    response_model=WeatherLocationListResponse,
    summary="weather 위치 (목록·근처·영역, 선택적으로 최신 관측)",
    responses=_ERROR_RESPONSES,
)
async def list_weather_locations(
    request: Request,
    query: QueryDep,
    store: StoreDep,
    include_current: Annotated[
        bool, Query(description="true면 각 위치에 최신 관측을 붙인다(지도 마커용).")
    ] = False,
) -> WeatherLocationListResponse:
    started_at = perf_counter()
    dataset = DATASET_LOCATIONS
    next_cursor: str | None = None
    truncated = False
    async with _state_errors():
        if query.cursor is not None:
            generation, after = _decode_cursor(query.cursor, dataset=dataset.name)
            meta = await store.readable_meta(dataset.name, generation)
        else:
            meta = await store.current_meta(dataset.name)
            generation, after = meta.generation, ""
        if query.lon is not None:
            assert query.lat is not None
            assert query.radius_m is not None
            hits = await store.nearby(
                dataset.name,
                generation,
                lon=query.lon,
                lat=query.lat,
                radius_m=query.radius_m,
                count=query.limit + 1,
            )
            truncated = len(hits) > query.limit
            hits = hits[: query.limit]
            ids = [feature_id for feature_id, _ in hits]
            items = _parse_values(
                WeatherLocationOut, ids, await store.get_values(dataset.name, generation, ids)
            )
            items = [
                item.model_copy(update={"distance_m": round(distance, 1)})
                for item, (_, distance) in zip(items, hits, strict=True)
            ]
        elif query.min_lon is not None:
            items, truncated = await _within_box(store, generation, query)
        else:
            ids, has_more = await store.page_ids(
                dataset.name, generation, after=after or None, limit=query.limit
            )
            raw = await store.get_values(dataset.name, generation, ids)
            if query.cursor is not None:
                await store.generation_meta(dataset.name, generation)
            items = _parse_values(WeatherLocationOut, ids, raw)
            if has_more and ids:
                next_cursor = _encode_cursor(dataset.name, generation, ids[-1])
    current_freshness: WeatherStateFreshness | None = None
    if include_current and items:
        joined = await _join(store, DATASET_CURRENT, [item.feature_id for item in items])
        current_freshness = (
            _freshness(DATASET_CURRENT, joined.meta) if joined.meta is not None else None
        )
        attached: list[WeatherLocationOut] = []
        for item in items:
            value = _decode(WeatherCurrentState, joined.values.get(item.feature_id))
            attached.append(
                item.model_copy(update={"observations": list(value.observations)})
                if value is not None
                else item
            )
        items = attached
    return WeatherLocationListResponse(
        data=WeatherLocationListData(
            items=items,
            truncated=truncated,
            freshness=_freshness(dataset, meta),
            current_freshness=current_freshness,
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=query.limit, next_cursor=next_cursor
        ),
    )


async def _within_box(
    store: ValkeyStateStore, generation: str, query: _Query
) -> tuple[list[WeatherLocationOut], bool]:
    assert query.min_lon is not None
    assert query.min_lat is not None
    assert query.max_lon is not None
    assert query.max_lat is not None
    center_lon, center_lat, width, height = bbox_search_box(
        query.min_lon, query.min_lat, query.max_lon, query.max_lat
    )
    ids = await store.within_box(
        DATASET_LOCATIONS.name,
        generation,
        center_lon=center_lon,
        center_lat=center_lat,
        width_m=width,
        height_m=height,
        count=query.limit + 1,
    )
    truncated = len(ids) > query.limit
    ids = ids[: query.limit]
    items = _parse_values(
        WeatherLocationOut, ids, await store.get_values(DATASET_LOCATIONS.name, generation, ids)
    )
    return [item for item in items if _in_box(item, query)], truncated


def _in_box(item: WeatherLocationOut, query: _Query) -> bool:
    coord = item.coord
    assert query.min_lon is not None
    assert query.max_lon is not None
    assert query.min_lat is not None
    assert query.max_lat is not None
    return (
        coord is not None
        and query.min_lon <= coord.lon <= query.max_lon
        and query.min_lat <= coord.lat <= query.max_lat
    )


# -- 묶음 ----------------------------------------------------------------------------


@service_router.get(
    "/locations/{feature_id}",
    response_model=WeatherBundleResponse,
    summary="weather 위치 하나의 관측·예보·세 구간 요약 묶음",
    responses=_DETAIL_RESPONSES,
)
async def get_weather_location(
    request: Request,
    store: StoreDep,
    feature_id: FeatureIdPath,
    sections: SectionsQuery = None,
    forecast_styles: StylesQuery = None,
) -> WeatherBundleResponse:
    started_at = perf_counter()
    async with _state_errors():
        meta = await store.current_meta(DATASET_LOCATIONS.name)
        raw = await store.get_values(DATASET_LOCATIONS.name, meta.generation, [feature_id])
    if raw[0] is None:
        raise _problem(404, "NOT_FOUND", f"{DATASET_LOCATIONS.name}에 {feature_id}가 없다.")
    location = _parse_values(WeatherLocationOut, [feature_id], raw)[0]
    data = await _bundle(store, location, meta, sections=sections, styles=forecast_styles)
    return WeatherBundleResponse(data=data, meta=make_meta(request, started_at=started_at))


@service_router.get(
    "/nearest",
    response_model=WeatherBundleResponse,
    summary="좌표에서 가장 가까운 weather 위치의 묶음(거리 포함)",
    responses=_DETAIL_RESPONSES,
)
async def get_nearest_weather(
    request: Request,
    store: StoreDep,
    lon: Annotated[float, Query(ge=-180, le=180, description="경도.")],
    lat: Annotated[float, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT, description="위도.")],
    radius_m: Annotated[
        float, Query(gt=0, le=MAX_RADIUS_M, description="찾는 반경(m, 기본 20 km, 최대 50 km).")
    ] = DEFAULT_NEAREST_RADIUS_M,
    sections: SectionsQuery = None,
    forecast_styles: StylesQuery = None,
) -> WeatherBundleResponse:
    started_at = perf_counter()
    async with _state_errors():
        meta = await store.current_meta(DATASET_LOCATIONS.name)
        hits = await store.nearby(
            DATASET_LOCATIONS.name, meta.generation, lon=lon, lat=lat, radius_m=radius_m, count=1
        )
        if not hits:
            raise _problem(404, "NOT_FOUND", f"반경 {radius_m:.0f} m 안에 weather 위치가 없다.")
        feature_id, distance = hits[0]
        raw = await store.get_values(DATASET_LOCATIONS.name, meta.generation, [feature_id])
    location = _parse_values(WeatherLocationOut, [feature_id], raw)[0].model_copy(
        update={"distance_m": round(distance, 1)}
    )
    data = await _bundle(store, location, meta, sections=sections, styles=forecast_styles)
    return WeatherBundleResponse(data=data, meta=make_meta(request, started_at=started_at))


# -- 상태 ----------------------------------------------------------------------------


@service_router.get(
    "/status",
    response_model=WeatherStatusResponse,
    summary="Valkey 연결과 weather 데이터셋별 신선도",
    responses={503: _ERROR_RESPONSES[503]},
)
async def get_weather_state_status(request: Request, store: StoreDep) -> WeatherStatusResponse:
    started_at = perf_counter()
    datasets: list[WeatherDatasetStatus] = []
    async with _state_errors():
        await store.ping()
        for dataset in WEATHER_STATE_DATASETS:
            try:
                meta = await store.current_meta(dataset.name)
            except StateNotLoaded:
                datasets.append(
                    WeatherDatasetStatus(dataset=dataset.name, loaded=False, freshness=None)
                )
                continue
            except StateStoreError as exc:
                datasets.append(
                    WeatherDatasetStatus(
                        dataset=dataset.name, loaded=False, freshness=None, error=str(exc)
                    )
                )
                continue
            datasets.append(
                WeatherDatasetStatus(
                    dataset=dataset.name, loaded=True, freshness=_freshness(dataset, meta)
                )
            )
    return WeatherStatusResponse(
        data=WeatherStatusData(store="ok", datasets=datasets),
        meta=make_meta(request, started_at=started_at),
    )
