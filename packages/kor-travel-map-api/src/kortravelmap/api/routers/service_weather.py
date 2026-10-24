"""``/v1/service/weather/*`` — Valkey의 weather 현재·예보·세 구간 요약 읽기 (ADR-114 2단계).

PinVi 같은 service 소비자가 장소 하나에 날씨를 붙이는 흐름(좌표 → 가까운 weather 위치 → 관측·예보·
요약)을 요청 하나로 끝내게 한다. 값은 Map Dagster ``weather_state_*`` job이 Valkey에 세대 단위로
교체해 둔 것이고(``infra.valkey_state``), 여기서는 지금 세대를 읽기만 한다. 설계 정본은 ADR-114
"구현 설계 — 2단계" W5·W7.

- ``/locations``: 위치 목록(keyset cursor)·근처·영역. ``include_current=true``면 최신 관측을 붙인다.
- ``/locations/{feature_id}``: 위치 하나의 **묶음**(위치 + 관측 + 예보 + 세 구간 요약).
- ``/nearest``: 좌표 근처의 위치 후보(가까운 순 최대 :data:`NEAREST_CANDIDATES`곳)에서
  **부분마다** 그 부분의 데이터가 실제로 있는 가장 가까운 위치를 고른다 — 가장 가까운 지점이
  대기질 측정소처럼 예보가 없는 위치여도 예보는 다음으로 가까운 예보 위치에서 온다. 부분마다
  출처 위치와 거리를 싣는다.
- ``POST /locations/batch``: ``feature_id``·weather ``location_id``로 최대 :data:`MAX_BATCH`곳의
  묶음.
- 각 부분은 자기 데이터셋의 ``status``·``freshness``를 갖고, 한 데이터셋 장애가 묶음을 막지
  않는다. 묶음의 데이터셋 읽기는 Valkey 왕복 두 번으로 한다(``ValkeyStateStore.read_many``).
- 예보는 **읽을 때** 지금(또는 ``from``)보다 이른 ``target_at``과 ``to`` 뒤를 뗀다(W5). 세 구간
  요약은 읽는 시각으로 ``partial``을 다시 계산하고, 끝난 구간끼리만 전날 대비 차이
  (``vs_previous_day``)를 싣는다.
- 위치 데이터셋이 없거나 Valkey가 죽었으면 503, cursor 세대가 사라졌으면 409, 위치가 없으면 404.
  다른 Map 기능과 ``/ops/health-deep``은 Valkey를 보지 않는다.

이 표면은 ADR-105(Map은 weather를 서빙하지 않는다)의 **유일한 예외**다(ADR-114가 부분 대체) —
``tests/test_api_serves_no_weather.py``가 이 접두사만 빼고 계속 지킨다. weather 특보는 범위 밖이다
(PinVi가 weather를 직접 부른다).
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Final, Literal, TypeVar

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
    daily_slot_bounds,
)
from kortravelmap.infra.valkey_state import (
    GEO_LAT_LIMIT,
    DatasetRead,
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
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from kortravelmap.api.auth import require_service_token
from kortravelmap.api.response import Meta, ProblemDetail, make_meta
from kortravelmap.api.routers.service_transport import bbox_search_box
from kortravelmap.api.transport_state_service import shared_state_store

__all__ = ["service_router"]

_LOGGER = logging.getLogger(__name__)

service_router = APIRouter(
    prefix="/service/weather",
    tags=["service-weather-state"],
    dependencies=[Depends(require_service_token)],
)

MAX_LIMIT: Final = 500
DEFAULT_LIMIT: Final = 100
MAX_RADIUS_M: Final = 100_000.0
"""weather 근처 검색 반경 상한. PinVi는 20 → 50 → 100 km로 넓혀 찾는다(transport는 50 km)."""
MAX_BBOX_SIDE_M: Final = 1_000_000.0
_BOX_MARGIN: Final = 1.02
DEFAULT_NEAREST_RADIUS_M: Final = 20_000.0
NEAREST_CANDIDATES: Final = 10
"""``/nearest``가 부분마다 데이터를 찾아 보는 가까운 위치 수의 상한."""
MAX_BATCH: Final = 50


def _problem(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, "details": {}}
    )


def _unavailable(message: str) -> HTTPException:
    return _problem(status.HTTP_503_SERVICE_UNAVAILABLE, "WEATHER_STATE_UNAVAILABLE", message)


def _invalid(message: str) -> HTTPException:
    return _problem(422, "VALIDATION_ERROR", message)


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
        description=(
            "weather가 알린 집합 상태. stale = weather가 마지막 성공 집합을 그대로 줬다. "
            "null = 해당 없음 — 원천이 집합 상태를 알리지 않는 데이터셋(위치 roster: weather W1은 "
            "카탈로그 수집 시각을 알 수 없어 언제나 stale을 보낸다)이라 Map이 싣지 않는다."
        )
    )
    loaded_at: AwareDatetime = Field(description="Map이 이 세대로 교체한 시각.")
    checked_at: AwareDatetime | None = Field(
        description="weather가 304(바뀌지 않음)로 답해 교체 없이 다시 확인한 마지막 시각."
    )
    age_seconds: int = Field(
        description="source_collected_at(없으면 checked_at, 그것도 없으면 loaded_at)부터 지금까지."
    )
    max_age_seconds: int
    stale: bool = Field(description="age_seconds > max_age_seconds. stale이어도 값은 준다.")
    item_count: int


SectionStatus = Literal["ok", "not_loaded", "unavailable", "no_data"]
_SECTION_STATUS_DOC = (
    "ok · not_loaded(데이터셋이 아직 한 번도 적재 전) · unavailable(그 데이터셋을 읽지 못했거나 "
    "저장 값이 깨짐) · no_data(데이터셋은 있으나 후보 위치에 항목이 없음)."
)


class WeatherSectionSource(BaseModel):
    """이 부분의 값이 온 위치."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    location_id: str
    distance_m: float | None = Field(description="/nearest일 때 요청 좌표에서의 거리.")


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
    source: WeatherSectionSource | None = Field(description="값이 온 위치(값이 없으면 null).")
    freshness: WeatherStateFreshness | None
    observations: list[WeatherObservationState]


class WeatherForecastSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus = Field(description=_SECTION_STATUS_DOC)
    source: WeatherSectionSource | None = Field(description="값이 온 위치(값이 없으면 null).")
    freshness: WeatherStateFreshness | None
    groups: list[WeatherForecastGroupState] = Field(
        description=(
            "provider별 묶음. 지금(또는 from)보다 이른 target_at·to 뒤 target_at과 그 자리 값은 "
            "뗐다(ADR-114 W5)."
        )
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
            "전날 같은 구간과 비교. 전날 구간이 없거나, 둘 중 하나가 sample_count=0이거나, "
            "둘 중 하나가 partial(읽는 시각 기준으로 아직 끝나지 않았거나 덜 계산된 구간 — 끝난 "
            "구간과 비교하면 왜곡된다)이면 null. partial은 읽는 시각으로 다시 계산한 값이다."
        ),
    )


class WeatherDailySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus = Field(description=_SECTION_STATUS_DOC)
    source: WeatherSectionSource | None = Field(description="값이 온 위치(값이 없으면 null).")
    freshness: WeatherStateFreshness | None
    slots: list[WeatherDailySlotOut] = Field(description="(date, slot) 오름차순.")


class WeatherBundleData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: WeatherLocationOut = Field(
        description="요청 위치(/nearest면 가장 가까운 위치). 부분의 값은 source 위치에서 온다."
    )
    location_freshness: WeatherStateFreshness
    current: WeatherCurrentSection | None = Field(description="sections에 없으면 null.")
    forecasts: WeatherForecastSections = Field(description="forecast_styles에 든 style만 채운다.")
    daily_summaries: WeatherDailySection | None = Field(description="sections에 없으면 null.")


class WeatherBundleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: WeatherBundleData
    meta: Meta


Section = Literal["current", "forecasts", "daily_summaries"]


class WeatherBatchRequest(BaseModel):
    """``feature_ids``나 weather ``location_ids`` 중 하나로 최대 50곳."""

    model_config = ConfigDict(extra="forbid")

    feature_ids: list[str] = Field(default_factory=list, max_length=MAX_BATCH)
    location_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_BATCH,
        description="weather 위치 id(PinVi가 가진 weather location_id). Map이 feature_id로 바꾼다.",
    )
    sections: list[Section] | None = None
    forecast_styles: list[WeatherForecastStyle] | None = None
    forecast_from: AwareDatetime | None = Field(
        default=None, description="예보 target_at 하한(지금보다 이르면 지금)."
    )
    forecast_to: AwareDatetime | None = Field(default=None, description="예보 target_at 상한.")

    @model_validator(mode="after")
    def _one_kind(self) -> WeatherBatchRequest:
        total = len(self.feature_ids) + len(self.location_ids)
        if total == 0 or total > MAX_BATCH:
            raise ValueError(f"feature_ids·location_ids 합이 1~{MAX_BATCH}개여야 한다.")
        if len(set(self.feature_ids)) != len(self.feature_ids) or len(
            set(self.location_ids)
        ) != len(self.location_ids):
            raise ValueError("같은 id가 두 번 있다.")
        if (
            self.forecast_from is not None
            and self.forecast_to is not None
            and self.forecast_from > self.forecast_to
        ):
            raise ValueError("forecast_from은 forecast_to보다 늦을 수 없다.")
        return self


class WeatherBatchMissing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str | None
    location_id: str | None


class WeatherBatchData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WeatherBundleData]
    missing: list[WeatherBatchMissing] = Field(description="지금 세대에 없는 id(요청 순서).")


class WeatherBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: WeatherBatchData
    meta: Meta


class WeatherDatasetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    loaded: bool
    freshness: WeatherStateFreshness | None
    error: str | None = Field(
        default=None,
        description=(
            "이 데이터셋만 읽지 못했을 때 안정 코드(failure_kind). 원 메시지는 싣지 않는다."
        ),
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
    reference = meta.source_collected_at or meta.checked_at or meta.loaded_at
    age = max(0, int((datetime.now(UTC) - reference).total_seconds()))
    max_age = int(dataset.max_age.total_seconds())
    source_status: Literal["ok", "stale"] | None = None
    if not dataset.reports_source_status:
        source_status = None
    elif meta.source_status == "ok":
        source_status = "ok"
    elif meta.source_status == "stale":
        source_status = "stale"
    return WeatherStateFreshness(
        dataset=dataset.name,
        generation=meta.generation,
        source_collected_at=meta.source_collected_at,
        source_status=source_status,
        loaded_at=meta.loaded_at,
        checked_at=meta.checked_at,
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


class _BrokenValue:
    """저장 값이 모델과 맞지 않는다 — 그 부분은 ``unavailable``이다(없음과 구분한다)."""


_BROKEN: Final = _BrokenValue()


def _decode(model: type[_ModelT], value: bytes | None) -> _ModelT | _BrokenValue | None:
    """값 하나를 푼다. 없으면 ``None``, 모양이 틀리면 :data:`_BROKEN`.

    위치 값의 :func:`_parse_values`가 503인 것과 같은 판정이다 — 깨진 값을 빈 데이터
    (``no_data``)로 꾸미지 않는다.
    """
    if value is None:
        return None
    try:
        return model.model_validate_json(value)
    except ValidationError:
        _LOGGER.warning("weather 상태 값 모양이 다르다: %s", model.__name__)
        return _BROKEN


def future_groups(
    groups: Sequence[WeatherForecastGroupState],
    now: datetime,
    *,
    until: datetime | None = None,
) -> list[WeatherForecastGroupState]:
    """``now``보다 이른·``until``보다 늦은 ``target_at``과 그 자리 metric 값을 뗀다.

    남는 시각이 없는 묶음은 뺀다.
    """
    kept: list[WeatherForecastGroupState] = []
    for group in groups:
        keep = [
            index
            for index, target in enumerate(group.target_at)
            if target >= now and (until is None or target <= until)
        ]
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


def slot_is_partial(slot: WeatherDailySlotState, now: datetime) -> bool:
    """읽는 시각 기준 ``partial``(ADR-114 W7).

    구간이 아직 끝나지 않았으면(KST ``[시작, 끝)``의 끝 전) 언제나 partial이다 — 적재 시각의 값은
    시간이 지나며 틀린다. 끝난 구간이어도 weather가 적재 때 partial로 줬으면 그대로 partial이다:
    그 세대의 요약은 구간 도중에 계산된 것이라 다음 교체 전까지 실제로 덜 모인 값이다.
    """
    _, end = daily_slot_bounds(slot.date, slot.slot)
    return now < end or slot.partial


def with_previous_day(
    slots: Sequence[WeatherDailySlotState], now: datetime
) -> list[WeatherDailySlotOut]:
    """구간마다 ``partial``을 다시 계산하고 전날 같은 구간과의 차이를 붙인다(ADR-114 W7).

    partial인 구간은 차이를 내지 않는다 — 06:30의 아침 구간(1시간 반)을 끝난 어제 아침(6시간)과
    비교하면 "어제보다 춥다"가 거짓이 될 수 있다.
    """
    partial = {(slot.date, slot.slot): slot_is_partial(slot, now) for slot in slots}
    by_key = {(slot.date, slot.slot): slot for slot in slots}
    out: list[WeatherDailySlotOut] = []
    for slot in slots:
        previous_date = slot.date - dt.timedelta(days=1)
        previous = by_key.get((previous_date, slot.slot))
        delta: WeatherSlotDelta | None = None
        if (
            previous is not None
            and previous.sample_count > 0
            and slot.sample_count > 0
            and not partial[(slot.date, slot.slot)]
            and not partial[(previous_date, slot.slot)]
        ):
            delta = WeatherSlotDelta(
                previous_date=previous_date,
                temp_min_delta=_delta(slot.temp_min, previous.temp_min),
                temp_max_delta=_delta(slot.temp_max, previous.temp_max),
                temp_avg_delta=_delta(slot.temp_avg, previous.temp_avg),
                humidity_avg_delta=_delta(slot.humidity_avg, previous.humidity_avg),
            )
        fields = {**slot.model_dump(), "partial": partial[(slot.date, slot.slot)]}
        out.append(WeatherDailySlotOut(**fields, vs_previous_day=delta))
    return out


# -- 질의 -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Query:
    cursor: str | None
    limit: int
    lon: float | None
    lat: float | None
    radius_m: float | None
    min_lon: float | None
    min_lat: float | None
    max_lon: float | None
    max_lat: float | None


def _query(
    cursor: Annotated[
        str | None,
        Query(min_length=1, max_length=256, description="직전 페이지 meta.page.next_cursor."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    lon: Annotated[float | None, Query(ge=-180, le=180, description="근처 검색 중심 경도.")] = None,
    lat: Annotated[
        float | None,
        Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT, description="근처 검색 중심 위도."),
    ] = None,
    radius_m: Annotated[
        float | None,
        Query(gt=0, le=MAX_RADIUS_M, description="근처 검색 반경(m, 최대 100 km)."),
    ] = None,
    min_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    min_lat: Annotated[float | None, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT)] = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    max_lat: Annotated[float | None, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT)] = None,
) -> _Query:
    near = (lon, lat, radius_m)
    box = (min_lon, min_lat, max_lon, max_lat)
    if any(v is not None for v in near) and not all(v is not None for v in near):
        raise _invalid("근처 검색에는 lon·lat·radius_m이 모두 필요하다.")
    if any(v is not None for v in box) and not all(v is not None for v in box):
        raise _invalid("영역 검색에는 min_lon·min_lat·max_lon·max_lat이 모두 필요하다.")
    if lon is not None and min_lon is not None:
        raise _invalid("근처 검색과 영역 검색은 함께 쓸 수 없다.")
    if cursor is not None and (lon is not None or min_lon is not None):
        raise _invalid("cursor는 목록 순회에만 쓴다(근처·영역 검색은 cursor가 없다).")
    if min_lon is not None:
        assert min_lat is not None
        assert max_lon is not None
        assert max_lat is not None
        if min_lon > max_lon or min_lat > max_lat:
            raise _invalid("영역은 min ≤ max여야 한다.")
        _, _, width, height = bbox_search_box(min_lon, min_lat, max_lon, max_lat)
        if width > MAX_BBOX_SIDE_M * _BOX_MARGIN or height > MAX_BBOX_SIDE_M * _BOX_MARGIN:
            raise _invalid("영역 한 변은 1,000 km 이하여야 한다.")
    return _Query(cursor, limit, lon, lat, radius_m, min_lon, min_lat, max_lon, max_lat)


QueryDep = Annotated[_Query, Depends(_query)]


def _encode_cursor(generation: str, after: str) -> str:
    raw = f"{DATASET_LOCATIONS.name}|{generation}|{after}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    """cursor → ``(세대, 마지막 id)``. 다른 표면(예: transport)의 cursor는 422다."""
    invalid = _invalid("cursor가 올바르지 않다.")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        owner, generation, after = decoded.decode().split("|", 2)
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise invalid from exc
    if owner != DATASET_LOCATIONS.name or not generation or not after:
        raise invalid
    return generation, after


@dataclass(frozen=True, slots=True)
class _ForecastWindow:
    since: datetime | None
    until: datetime | None


FeatureIdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")]
SectionsQuery = Annotated[
    list[Section] | None,
    Query(description="묶음에 담을 부분(반복 가능). 없으면 전부."),
]
StylesQuery = Annotated[
    list[WeatherForecastStyle] | None,
    Query(description="담을 예보 style(반복 가능). 없으면 네 가지 전부."),
]
FromQuery = Annotated[
    AwareDatetime | None,
    Query(alias="from", description="예보 target_at 하한(지금보다 이르면 지금). 기본 지금."),
]
ToQuery = Annotated[
    AwareDatetime | None, Query(alias="to", description="예보 target_at 상한. 기본 끝까지.")
]


def _window(since: datetime | None, until: datetime | None) -> _ForecastWindow:
    if since is not None and until is not None and since > until:
        raise _invalid("from은 to보다 늦을 수 없다.")
    return _ForecastWindow(since, until)


# -- 묶음 ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Candidate:
    location: WeatherLocationOut
    distance_m: float | None


def _source(candidate: _Candidate) -> WeatherSectionSource:
    return WeatherSectionSource(
        feature_id=candidate.location.feature_id,
        location_id=candidate.location.location_id,
        distance_m=candidate.distance_m,
    )


def _pick(
    read: DatasetRead,
    candidates: Sequence[_Candidate],
    model: type[_ModelT],
    usable: Callable[[Any], Any],
) -> tuple[SectionStatus, _Candidate | None, Any]:
    """후보를 가까운 순으로 보며 ``usable(value)``가 값을 내는 첫 위치를 고른다.

    값이 깨진 후보는 건너뛰되, 끝내 쓸 값이 없고 깨진 후보가 있었으면 ``unavailable``이다.
    """
    if read.status == "not_loaded":
        return "not_loaded", None, None
    if read.status != "ok":
        return "unavailable", None, None
    broken = False
    for candidate, raw in zip(candidates, read.values, strict=True):
        value = _decode(model, raw)
        if isinstance(value, _BrokenValue):
            broken = True
            continue
        if value is None:
            continue
        picked = usable(value)
        if picked is not None:
            return "ok", candidate, picked
    return ("unavailable" if broken else "no_data"), None, None


async def _bundles(
    store: ValkeyStateStore,
    groups: Sequence[tuple[Sequence[_Candidate], GenerationMeta]],
    *,
    sections: list[Section] | None,
    styles: list[WeatherForecastStyle] | None,
    window: _ForecastWindow,
) -> list[WeatherBundleData]:
    """후보 묶음마다 부분을 채운다. 데이터셋 읽기는 모든 후보를 합쳐 Valkey 왕복 두 번이다."""
    wanted = set(sections or ("current", "forecasts", "daily_summaries"))
    wanted_styles = set(styles or ("ultra_short", "short", "mid", "external"))
    now = datetime.now(UTC)
    since = max(now, window.since) if window.since is not None else now
    datasets: list[WeatherStateDataset] = []
    if "current" in wanted:
        datasets.append(DATASET_CURRENT)
    if "forecasts" in wanted:
        datasets.extend(d for d in FORECAST_DATASETS if d.style in wanted_styles)
    if "daily_summaries" in wanted:
        datasets.append(DATASET_DAILY_SUMMARIES)
    ids = list(dict.fromkeys(c.location.feature_id for cands, _ in groups for c in cands))
    async with _state_errors():
        reads = await store.read_many([(dataset.name, ids) for dataset in datasets])
    by_dataset: dict[str, tuple[DatasetRead, dict[str, bytes | None]]] = {
        read.dataset: (read, dict(zip(ids, read.values, strict=True))) for read in reads
    }

    def read_for(dataset: WeatherStateDataset, cands: Sequence[_Candidate]) -> DatasetRead:
        read, values = by_dataset[dataset.name]
        return DatasetRead(
            read.dataset, read.status, read.meta, [values.get(c.location.feature_id) for c in cands]
        )

    out: list[WeatherBundleData] = []
    for candidates, location_meta in groups:
        current: WeatherCurrentSection | None = None
        if "current" in wanted:
            read = read_for(DATASET_CURRENT, candidates)
            state, chosen, observations = _pick(
                read,
                candidates,
                WeatherCurrentState,
                lambda v: list(v.observations) or None,
            )
            current = WeatherCurrentSection(
                status=state,
                source=_source(chosen) if chosen else None,
                freshness=_freshness(DATASET_CURRENT, read.meta) if read.meta else None,
                observations=observations or [],
            )
        forecast_sections: dict[str, WeatherForecastSection] = {}
        for dataset in FORECAST_DATASETS:
            if "forecasts" not in wanted or dataset.style not in wanted_styles:
                continue
            read = read_for(dataset, candidates)
            state, chosen, groups_kept = _pick(
                read,
                candidates,
                WeatherForecastState,
                lambda v: future_groups(v.groups, since, until=window.until) or None,
            )
            assert dataset.style is not None
            forecast_sections[dataset.style] = WeatherForecastSection(
                status=state,
                source=_source(chosen) if chosen else None,
                freshness=_freshness(dataset, read.meta) if read.meta else None,
                groups=groups_kept or [],
            )
        daily: WeatherDailySection | None = None
        if "daily_summaries" in wanted:
            read = read_for(DATASET_DAILY_SUMMARIES, candidates)
            state, chosen, slots = _pick(
                read,
                candidates,
                WeatherDailySummaryState,
                lambda v: with_previous_day(v.slots, now) or None,
            )
            daily = WeatherDailySection(
                status=state,
                source=_source(chosen) if chosen else None,
                freshness=_freshness(DATASET_DAILY_SUMMARIES, read.meta) if read.meta else None,
                slots=slots or [],
            )
        nearest = candidates[0]
        location = nearest.location
        if nearest.distance_m is not None:
            location = location.model_copy(update={"distance_m": nearest.distance_m})
        out.append(
            WeatherBundleData(
                location=location,
                location_freshness=_freshness(DATASET_LOCATIONS, location_meta),
                current=current,
                forecasts=WeatherForecastSections(**forecast_sections),
                daily_summaries=daily,
            )
        )
    return out


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
            generation, after = _decode_cursor(query.cursor)
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
                next_cursor = _encode_cursor(generation, ids[-1])
        current_freshness: WeatherStateFreshness | None = None
        if include_current and items:
            (read,) = await store.read_many(
                [(DATASET_CURRENT.name, [item.feature_id for item in items])]
            )
            if read.meta is not None:
                current_freshness = _freshness(DATASET_CURRENT, read.meta)
            attached: list[WeatherLocationOut] = []
            for item, raw_value in zip(items, read.values, strict=True):
                value = _decode(WeatherCurrentState, raw_value)
                attached.append(
                    item.model_copy(update={"observations": list(value.observations)})
                    if isinstance(value, WeatherCurrentState)
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


# -- 묶음 route --------------------------------------------------------------------------


@service_router.post(
    "/locations/batch",
    response_model=WeatherBatchResponse,
    summary="weather 위치 여러 곳(feature_id·weather location_id, 최대 50)의 묶음",
    responses={503: _ERROR_RESPONSES[503]},
)
async def batch_weather_locations(
    request: Request, store: StoreDep, body: WeatherBatchRequest
) -> WeatherBatchResponse:
    started_at = perf_counter()
    async with _state_errors():
        meta = await store.current_meta(DATASET_LOCATIONS.name)
        resolved = await store.lookup(DATASET_LOCATIONS.name, meta.generation, body.location_ids)
        wanted: list[tuple[str | None, str | None]] = [(fid, None) for fid in body.feature_ids]
        wanted += list(zip(resolved, body.location_ids, strict=True))
        ids = [fid for fid, _ in wanted if fid is not None]
        raw = await store.get_values(DATASET_LOCATIONS.name, meta.generation, ids)
    values = dict(zip(ids, raw, strict=True))
    missing: list[WeatherBatchMissing] = []
    found: list[str] = []
    for fid, location_id in wanted:
        if fid is None or values.get(fid) is None:
            missing.append(WeatherBatchMissing(feature_id=fid, location_id=location_id))
        elif fid not in found:
            found.append(fid)
    locations = _parse_values(WeatherLocationOut, found, [values[fid] for fid in found])
    items = await _bundles(
        store,
        [([_Candidate(location, None)], meta) for location in locations],
        sections=body.sections,
        styles=body.forecast_styles,
        window=_window(body.forecast_from, body.forecast_to),
    )
    return WeatherBatchResponse(
        data=WeatherBatchData(items=items, missing=missing),
        meta=make_meta(request, started_at=started_at),
    )


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
    forecast_from: FromQuery = None,
    forecast_to: ToQuery = None,
) -> WeatherBundleResponse:
    started_at = perf_counter()
    window = _window(forecast_from, forecast_to)
    async with _state_errors():
        meta = await store.current_meta(DATASET_LOCATIONS.name)
        raw = await store.get_values(DATASET_LOCATIONS.name, meta.generation, [feature_id])
    if raw[0] is None:
        raise _problem(404, "NOT_FOUND", f"{DATASET_LOCATIONS.name}에 {feature_id}가 없다.")
    location = _parse_values(WeatherLocationOut, [feature_id], raw)[0]
    (data,) = await _bundles(
        store,
        [([_Candidate(location, None)], meta)],
        sections=sections,
        styles=forecast_styles,
        window=window,
    )
    return WeatherBundleResponse(data=data, meta=make_meta(request, started_at=started_at))


@service_router.get(
    "/nearest",
    response_model=WeatherBundleResponse,
    summary="좌표 근처 weather 위치들에서 부분마다 데이터가 있는 가장 가까운 위치의 묶음",
    responses=_DETAIL_RESPONSES,
)
async def get_nearest_weather(
    request: Request,
    store: StoreDep,
    lon: Annotated[float, Query(ge=-180, le=180, description="경도.")],
    lat: Annotated[float, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT, description="위도.")],
    radius_m: Annotated[
        float, Query(gt=0, le=MAX_RADIUS_M, description="찾는 반경(m, 기본 20 km, 최대 100 km).")
    ] = DEFAULT_NEAREST_RADIUS_M,
    sections: SectionsQuery = None,
    forecast_styles: StylesQuery = None,
    forecast_from: FromQuery = None,
    forecast_to: ToQuery = None,
) -> WeatherBundleResponse:
    started_at = perf_counter()
    window = _window(forecast_from, forecast_to)
    async with _state_errors():
        meta = await store.current_meta(DATASET_LOCATIONS.name)
        hits = await store.nearby(
            DATASET_LOCATIONS.name,
            meta.generation,
            lon=lon,
            lat=lat,
            radius_m=radius_m,
            count=NEAREST_CANDIDATES,
        )
        if not hits:
            raise _problem(404, "NOT_FOUND", f"반경 {radius_m:.0f} m 안에 weather 위치가 없다.")
        ids = [feature_id for feature_id, _ in hits]
        raw = await store.get_values(DATASET_LOCATIONS.name, meta.generation, ids)
    locations = _parse_values(WeatherLocationOut, ids, raw)
    candidates = [
        _Candidate(location, round(distance, 1))
        for location, (_, distance) in zip(locations, hits, strict=True)
    ]
    (data,) = await _bundles(
        store, [(candidates, meta)], sections=sections, styles=forecast_styles, window=window
    )
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
                _LOGGER.warning("weather 상태 %s를 읽지 못했다: %s", dataset.name, exc)
                datasets.append(
                    WeatherDatasetStatus(
                        dataset=dataset.name, loaded=False, freshness=None, error=exc.failure_kind
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
