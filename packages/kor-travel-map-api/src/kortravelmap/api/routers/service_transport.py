"""``/v1/service/transport/*`` — Valkey의 transport 현재 상태 읽기 (ADR-114 1단계).

PinVi 같은 service 소비자가 주유소(최신 유가)·휴게소(휴게소 유가)·고속도로 활성 돌발·공항을
읽는다. 값은 Map Dagster ``transport_state_*`` job이 Valkey에 세대 단위로 교체해 둔
것이고(``infra.valkey_state``), 여기서는 지금 세대를 읽기만 한다. 키·교체·신선도의 정본은 ADR-114
"구현 설계 — 1단계" D2~D6이다.

- 목록: 조건이 없으면 ``feature_id`` 사전순 keyset(``cursor``). cursor는 세대를 품어 순회 도중
  교체돼도 같은 세대로 끝난다. 근처(``lon``·``lat``·``radius_m``)·영역(``min_lon``…``max_lat``)은
  가까운 순 ``limit``건이고 ``truncated``로 상한 도달을 알린다.
- 응답마다 ``freshness``(원천 수집 시각·Map 반영 시각·나이·``stale``)를 싣는다. stale이어도 값은
  준다.
- Valkey 미설정·연결 실패는 이 표면만 503 ``TRANSPORT_STATE_UNAVAILABLE``, 아직 적재 전이면 503
  ``TRANSPORT_STATE_NOT_LOADED``, cursor의 세대가 사라졌으면 409
  ``TRANSPORT_STATE_GENERATION_EXPIRED``.
- 가격 추이는 transport T4에서 요청 시 한 페이지씩 읽어 전한다. transport가 응답하지 않거나 계약이
  어긋나면 현재가는 주고 추이만 ``unavailable``(이유)이다(결정 4). transport의 불투명 cursor를
  그대로 주고받으며, transport 409는 ``reason=cursor_expired``(처음부터 다시)다.
"""

from __future__ import annotations

import base64
import binascii
import logging
import math
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from kortravelmap.dto.transport_state import (
    AirportState,
    FuelPriceState,
    FuelStationState,
    HighwayIncidentState,
    RestAreaFuelPriceState,
    RestAreaState,
)
from kortravelmap.infra.valkey_state import (
    GEO_LAT_LIMIT,
    GenerationMeta,
    StateGenerationExpired,
    StateNotLoaded,
    StateStoreError,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_AIRPORTS,
    DATASET_FUEL_STATIONS,
    DATASET_HIGHWAY_INCIDENTS,
    DATASET_REST_AREA_FUEL_PRICES,
    DATASET_REST_AREAS,
    TRANSPORT_STATE_DATASETS,
    TransportStateDataset,
)
from kortravelmap.providers.opinet import OPINET_PRODUCT_KEY_MAP, OPINET_PRODUCT_NAME_KO
from kortravelmap.settings import KorTravelMapSettings
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from kortravelmap.api.auth import require_service_token
from kortravelmap.api.response import Meta, ProblemDetail, make_meta
from kortravelmap.api.transport_state_service import (
    PriceHistoryUnavailableReason,
    fetch_price_history,
    get_state_store,
    price_history_params,
    state_unavailable,
)

__all__ = ["service_router"]

_LOGGER = logging.getLogger(__name__)

service_router = APIRouter(
    prefix="/service/transport",
    tags=["service-transport-state"],
    dependencies=[Depends(require_service_token)],
)

MAX_LIMIT = 500
DEFAULT_LIMIT = 100
MAX_RADIUS_M = 50_000.0
MAX_BBOX_SIDE_M = 1_000_000.0
_BOX_MARGIN = 1.02
_EARTH_RADIUS_M = 6_372_797.560856
"""Valkey GEO가 쓰는 지구 반지름(m) — 상자 크기 계산을 서버와 같은 구면으로 한다."""

StoreDep = Annotated[ValkeyStateStore, Depends(get_state_store)]


# -- 응답 모델 -----------------------------------------------------------------


class TransportFreshness(BaseModel):
    """세대 하나의 신선도(ADR-114 D5)."""

    model_config = ConfigDict(extra="forbid")

    dataset: str
    generation: str
    source_collected_at: AwareDatetime | None = Field(
        description="원천(transport) 수집 시각. 공항처럼 원천이 주지 않으면 null."
    )
    loaded_at: AwareDatetime = Field(description="Map이 이 세대로 교체한 시각.")
    age_seconds: int = Field(description="source_collected_at(없으면 loaded_at)부터 지금까지.")
    max_age_seconds: int
    stale: bool = Field(description="age_seconds > max_age_seconds. stale이어도 값은 준다.")
    item_count: int


class FuelStationOut(FuelStationState):
    distance_m: float | None = Field(default=None, description="근처 검색일 때 중심에서의 거리.")


class RestAreaOut(RestAreaState):
    distance_m: float | None = Field(default=None, description="근처 검색일 때 중심에서의 거리.")
    fuel_prices: RestAreaFuelPriceState | None = Field(
        default=None, description="휴게소 주유소 최신 유가(매칭이 없거나 아직 적재 전이면 null)."
    )


class HighwayIncidentOut(HighwayIncidentState):
    distance_m: float | None = Field(default=None, description="근처 검색일 때 중심에서의 거리.")


class AirportOut(AirportState):
    distance_m: float | None = Field(default=None, description="근처 검색일 때 중심에서의 거리.")


_OutT = TypeVar("_OutT", FuelStationOut, RestAreaOut, HighwayIncidentOut, AirportOut)


class FuelStationListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FuelStationOut]
    truncated: bool = Field(description="근처·영역 검색이 limit에 닿았다(더 있을 수 있다).")
    freshness: TransportFreshness


class RestAreaListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RestAreaOut]
    truncated: bool
    freshness: TransportFreshness
    fuel_price_freshness: TransportFreshness | None = Field(
        description="휴게소 유가 데이터셋의 신선도. 아직 적재 전이면 null."
    )


class HighwayIncidentListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HighwayIncidentOut]
    truncated: bool
    freshness: TransportFreshness


class AirportListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AirportOut]
    truncated: bool
    freshness: TransportFreshness


class FuelStationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: FuelStationListData
    meta: Meta


class RestAreaListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: RestAreaListData
    meta: Meta


class HighwayIncidentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: HighwayIncidentListData
    meta: Meta


class AirportListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: AirportListData
    meta: Meta


class FuelStationDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: FuelStationOut
    freshness: TransportFreshness


class RestAreaDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: RestAreaOut
    freshness: TransportFreshness
    fuel_price_freshness: TransportFreshness | None


class HighwayIncidentDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: HighwayIncidentOut
    freshness: TransportFreshness


class AirportDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: AirportOut
    freshness: TransportFreshness


class FuelStationDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: FuelStationDetailData
    meta: Meta


class RestAreaDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: RestAreaDetailData
    meta: Meta


class HighwayIncidentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: HighwayIncidentDetailData
    meta: Meta


class AirportDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: AirportDetailData
    meta: Meta


class PriceHistoryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_key: str
    product_code: str
    product_name: str | None
    price: float | None = Field(description="원/L. null이면 그때 판매하지 않았다(그대로 전한다).")
    provider_updated_at: AwareDatetime | None = Field(
        description="원천이 행마다 주지 않아 현재 항상 null이다(다른 시각으로 채우지 않는다)."
    )
    observed_at: AwareDatetime = Field(description="오피넷 갱신시각(없으면 처음 본 수집 시각).")
    collected_at: AwareDatetime | None = Field(
        description=(
            "원천이 행마다 주지 않아 현재 항상 null이다(응답 생성 시각으로 채우지 않는다). 페이지의 "
            "수집 시각은 history.source_collected_at이다."
        )
    )


class PriceHistoryBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable"]
    reason: PriceHistoryUnavailableReason | None = Field(
        description=(
            "unavailable일 때 이유. disabled(Map 설정이 끔)·not_configured(transport 주소·토큰 "
            "없음) — 이 둘은 transport를 부르지 않았다. upstream_not_found(transport 404 — 없는 "
            "주유소·옛 버전·토큰·접속 주소)·upstream_unsupported(501)·cursor_expired(transport 409 — "
            "수집 revision이 바뀌었거나 cursor가 만료됐다. 이미 받은 페이지를 버리고 cursor 없이 "
            "처음부터 다시 읽는다)·request_rejected(transport 422 — 조회 창 366일 초과·미래 until·"
            "변조되었거나 다른 조건의 cursor)·upstream_timeout(timeout)·upstream_unavailable(5xx·"
            "연결 실패)·upstream_rejected(그 밖의 비-200)·upstream_contract(응답 모양이 다름 — 다른 "
            "주유소의 station_key 포함)."
        )
    )
    generated_at: AwareDatetime | None = Field(description="transport가 이 페이지를 만든 시각.")
    source_collected_at: AwareDatetime | None = Field(
        description=(
            "이 페이지 이력의 실제 수집 시각 중 가장 이른 값(빈 범위면 transport 마지막 성공 수집)."
        )
    )
    source_status: Literal["ok", "stale", "failed"] | None = Field(
        description="transport 유가 수집 상태. stale이어도 기존 이력은 준다. unavailable이면 null."
    )
    has_more: bool = Field(description="다음 페이지가 있다(next_cursor로 읽는다).")
    next_cursor: str | None = Field(
        description=(
            "다음 페이지 cursor(불투명, transport 발급·첫 페이지부터 15분 유효). 같은 product_code·"
            "since·until과 함께 cursor 인자로 보낸다. meta.page.next_cursor와 같다."
        )
    )
    truncated: bool = Field(
        description="호환용 — has_more와 같다(deprecated, has_more·next_cursor를 쓴다)."
    )
    items: list[PriceHistoryPoint] = Field(
        description="observed_at 내림차순, 유종 합계 최대 limit행."
    )


class FuelStationPriceHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    natural_key: str
    current_prices: list[FuelPriceState]
    history: PriceHistoryBlock
    freshness: TransportFreshness


class FuelStationPriceHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: FuelStationPriceHistoryData
    meta: Meta


class TransportDatasetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    loaded: bool
    freshness: TransportFreshness | None
    error: str | None = Field(
        default=None, description="이 데이터셋만 읽지 못했을 때 이유(나머지는 그대로 보인다)."
    )


class TransportStatusData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store: Literal["ok"]
    datasets: list[TransportDatasetStatus]


class TransportStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: TransportStatusData
    meta: Meta


_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ProblemDetail,
        "description": (
            "TRANSPORT_STATE_GENERATION_EXPIRED — cursor의 세대가 사라졌다. 처음부터 다시."
        ),
    },
    503: {
        "model": ProblemDetail,
        "description": (
            "TRANSPORT_STATE_UNAVAILABLE(Valkey 미설정·연결 실패) 또는 "
            "TRANSPORT_STATE_NOT_LOADED(아직 적재 전)."
        ),
    },
}
_DETAIL_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "NOT_FOUND — 지금 세대에 그 feature_id가 없다."},
    503: _ERROR_RESPONSES[503],
}


# -- 공통 ----------------------------------------------------------------------


def _problem(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, "details": {}}
    )


@asynccontextmanager
async def _state_errors() -> AsyncIterator[None]:
    """store 예외 → 이 표면의 HTTP 오류."""
    try:
        yield
    except StateNotLoaded as exc:
        raise _problem(
            status.HTTP_503_SERVICE_UNAVAILABLE, "TRANSPORT_STATE_NOT_LOADED", str(exc)
        ) from exc
    except StateGenerationExpired as exc:
        raise _problem(
            status.HTTP_409_CONFLICT, "TRANSPORT_STATE_GENERATION_EXPIRED", str(exc)
        ) from exc
    except StateStoreError as exc:
        raise state_unavailable(str(exc)) from exc


def _freshness(dataset: TransportStateDataset, meta: GenerationMeta) -> TransportFreshness:
    reference = meta.source_collected_at or meta.loaded_at
    age = max(0, int((datetime.now(UTC) - reference).total_seconds()))
    max_age = int(dataset.max_age.total_seconds())
    return TransportFreshness(
        dataset=dataset.name,
        generation=meta.generation,
        source_collected_at=meta.source_collected_at,
        loaded_at=meta.loaded_at,
        age_seconds=age,
        max_age_seconds=max_age,
        stale=age > max_age,
        item_count=meta.count,
    )


def _encode_cursor(dataset: str, generation: str, after: str) -> str:
    raw = f"{dataset}|{generation}|{after}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, dataset: str) -> tuple[str, str]:
    """cursor → ``(세대, 마지막 id)``. 다른 데이터셋의 cursor는 422다."""
    invalid = _problem(422, "VALIDATION_ERROR", "cursor가 올바르지 않다.")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        owner, generation, after = decoded.decode().split("|", 2)
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise invalid from exc
    if owner != dataset or not generation or not after:
        raise invalid
    return generation, after


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
        float | None, Query(gt=0, le=MAX_RADIUS_M, description="근처 검색 반경(m, 최대 50 km).")
    ] = None,
    min_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    min_lat: Annotated[float | None, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT)] = None,
    max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    max_lat: Annotated[float | None, Query(ge=-GEO_LAT_LIMIT, le=GEO_LAT_LIMIT)] = None,
) -> _Query:
    near = (lon, lat, radius_m)
    box = (min_lon, min_lat, max_lon, max_lat)
    if any(v is not None for v in near) and not all(v is not None for v in near):
        raise _problem(422, "VALIDATION_ERROR", "근처 검색에는 lon·lat·radius_m이 모두 필요하다.")
    if any(v is not None for v in box) and not all(v is not None for v in box):
        raise _problem(
            422,
            "VALIDATION_ERROR",
            "영역 검색에는 min_lon·min_lat·max_lon·max_lat이 모두 필요하다.",
        )
    if lon is not None and min_lon is not None:
        raise _problem(422, "VALIDATION_ERROR", "근처 검색과 영역 검색은 함께 쓸 수 없다.")
    if cursor is not None and (lon is not None or min_lon is not None):
        raise _problem(
            422, "VALIDATION_ERROR", "cursor는 목록 순회에만 쓴다(근처·영역 검색은 cursor가 없다)."
        )
    if min_lon is not None:
        assert min_lat is not None
        assert max_lon is not None
        assert max_lat is not None
        if min_lon > max_lon or min_lat > max_lat:
            raise _problem(422, "VALIDATION_ERROR", "영역은 min ≤ max여야 한다.")
        # 크기 검사도 store를 건드리기 전에 한다 — Valkey가 꺼져 있어도 잘못된 요청은 422다.
        _, _, width, height = bbox_search_box(min_lon, min_lat, max_lon, max_lat)
        if width > MAX_BBOX_SIDE_M * _BOX_MARGIN or height > MAX_BBOX_SIDE_M * _BOX_MARGIN:
            raise _problem(422, "VALIDATION_ERROR", "영역 한 변은 1,000 km 이하여야 한다.")
    return _Query(cursor, limit, lon, lat, radius_m, min_lon, min_lat, max_lon, max_lat)


QueryDep = Annotated[_Query, Depends(_query)]


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bbox_search_box(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> tuple[float, float, float, float]:
    """bbox를 덮는 ``BYBOX`` 상자 ``(center_lon, center_lat, width_m, height_m)``(ADR-114 D6).

    폭은 적도에 가장 가까운 bbox 위도에서 잰다(경도 1도가 그 위도에서 가장 넓다) — 중심 위도에서
    재면 적도 쪽 모서리가 상자 밖으로 빠진다. 높이는 위도 차. 둘 다 2% 여유를 둔다.
    """
    widest_lat = 0.0 if min_lat <= 0.0 <= max_lat else min(abs(min_lat), abs(max_lat))
    width = _haversine_m(min_lon, widest_lat, max_lon, widest_lat)
    height = _haversine_m(min_lon, min_lat, min_lon, max_lat)
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2
    return center_lon, center_lat, max(width * _BOX_MARGIN, 1.0), max(height * _BOX_MARGIN, 1.0)


def _parse_values(
    model: type[_OutT], ids: Sequence[str], raw: Sequence[bytes | None]
) -> list[_OutT]:
    items: list[_OutT] = []
    for feature_id, value in zip(ids, raw, strict=True):
        if value is None:
            # 세대 키는 불변이다 — id 목록에 있고 값이 없으면 저장소가 깨졌다.
            raise state_unavailable(f"상태 값이 없다: {feature_id}")
        try:
            items.append(model.model_validate_json(value))
        except ValidationError as exc:
            raise state_unavailable(f"상태 값 모양이 다르다: {feature_id}") from exc
    return items


def _in_box(item: _OutT, query: _Query) -> bool:
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


@dataclass(frozen=True, slots=True)
class _Listing(Generic[_OutT]):
    items: list[_OutT]
    truncated: bool
    next_cursor: str | None
    meta: GenerationMeta


async def _list(
    store: ValkeyStateStore,
    dataset: TransportStateDataset,
    model: type[_OutT],
    query: _Query,
) -> _Listing[_OutT]:
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
            items = _parse_values(model, ids, await store.get_values(dataset.name, generation, ids))
            items = [
                item.model_copy(update={"distance_m": round(distance, 1)})
                for item, (_, distance) in zip(items, hits, strict=True)
            ]
            return _Listing(items, truncated, None, meta)
        if query.min_lon is not None:
            assert query.min_lat is not None
            assert query.max_lon is not None
            assert query.max_lat is not None
            center_lon, center_lat, width, height = bbox_search_box(
                query.min_lon, query.min_lat, query.max_lon, query.max_lat
            )
            ids = await store.within_box(
                dataset.name,
                generation,
                center_lon=center_lon,
                center_lat=center_lat,
                width_m=width,
                height_m=height,
                count=query.limit + 1,
            )
            truncated = len(ids) > query.limit
            ids = ids[: query.limit]
            items = _parse_values(model, ids, await store.get_values(dataset.name, generation, ids))
            return _Listing([item for item in items if _in_box(item, query)], truncated, None, meta)
        ids, has_more = await store.page_ids(
            dataset.name, generation, after=after or None, limit=query.limit
        )
        raw_values = await store.get_values(dataset.name, generation, ids)
        if query.cursor is not None:
            # 읽는 사이 grace가 끝나 세대가 사라졌으면 빈 페이지가 "끝"으로, 빠진 값이 "저장소 깨짐"
            # 으로 보인다 — 값을 풀기 전에 세대를 다시 확인해 409로 알린다.
            await store.generation_meta(dataset.name, generation)
        items = _parse_values(model, ids, raw_values)
        next_cursor = (
            _encode_cursor(dataset.name, generation, ids[-1]) if has_more and ids else None
        )
        return _Listing(items, False, next_cursor, meta)


async def _detail(
    store: ValkeyStateStore,
    dataset: TransportStateDataset,
    model: type[_OutT],
    feature_id: str,
) -> tuple[_OutT, GenerationMeta]:
    async with _state_errors():
        meta = await store.current_meta(dataset.name)
        raw = await store.get_values(dataset.name, meta.generation, [feature_id])
    if raw[0] is None:
        raise _problem(404, "NOT_FOUND", f"{dataset.name}에 {feature_id}가 없다.")
    return _parse_values(model, [feature_id], raw)[0], meta


async def _attach_rest_area_prices(
    store: ValkeyStateStore, areas: list[RestAreaOut]
) -> tuple[list[RestAreaOut], TransportFreshness | None]:
    """휴게소에 휴게소 유가를 붙인다(D1).

    유가 데이터셋이 없거나 읽지 못하면 휴게소는 그대로 주고 유가만 비운다(D6 — 휴게소 응답을 막지
    않는다).
    """
    dataset = DATASET_REST_AREA_FUEL_PRICES
    try:
        meta = await store.current_meta(dataset.name)
        keys = [area.natural_key for area in areas]
        price_ids = await store.lookup(dataset.name, meta.generation, keys)
        wanted = [price_id for price_id in price_ids if price_id is not None]
        values = await store.get_values(dataset.name, meta.generation, wanted)
    except StateNotLoaded:
        return areas, None
    except StateStoreError:
        _LOGGER.warning("휴게소 유가 데이터셋을 읽지 못해 유가 없이 응답한다.")
        return areas, None
    prices: dict[str, RestAreaFuelPriceState] = {}
    for price_id, value in zip(wanted, values, strict=True):
        if value is None:
            continue
        try:
            prices[price_id] = RestAreaFuelPriceState.model_validate_json(value)
        except ValidationError:
            _LOGGER.warning("휴게소 유가 값 모양이 다르다: %s", price_id)
    attached = [
        area.model_copy(update={"fuel_prices": prices.get(price_id)}) if price_id else area
        for area, price_id in zip(areas, price_ids, strict=True)
    ]
    return attached, _freshness(dataset, meta)


FeatureIdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")]


# -- 주유소 --------------------------------------------------------------------


@service_router.get(
    "/fuel-stations",
    response_model=FuelStationListResponse,
    summary="주유소 + 유종별 최신가 (목록·근처·영역)",
    responses=_ERROR_RESPONSES,
)
async def list_fuel_stations(
    request: Request, query: QueryDep, store: StoreDep
) -> FuelStationListResponse:
    started_at = perf_counter()
    listing = await _list(store, DATASET_FUEL_STATIONS, FuelStationOut, query)
    return FuelStationListResponse(
        data=FuelStationListData(
            items=listing.items,
            truncated=listing.truncated,
            freshness=_freshness(DATASET_FUEL_STATIONS, listing.meta),
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=query.limit, next_cursor=listing.next_cursor
        ),
    )


@service_router.get(
    "/fuel-stations/{feature_id}",
    response_model=FuelStationDetailResponse,
    summary="주유소 한 곳",
    responses=_DETAIL_RESPONSES,
)
async def get_fuel_station(
    request: Request, store: StoreDep, feature_id: FeatureIdPath
) -> FuelStationDetailResponse:
    started_at = perf_counter()
    item, meta = await _detail(store, DATASET_FUEL_STATIONS, FuelStationOut, feature_id)
    return FuelStationDetailResponse(
        data=FuelStationDetailData(item=item, freshness=_freshness(DATASET_FUEL_STATIONS, meta)),
        meta=make_meta(request, started_at=started_at),
    )


@service_router.get(
    "/fuel-stations/{feature_id}/price-history",
    response_model=FuelStationPriceHistoryResponse,
    summary="주유소 현재가 + 가격 추이(transport에서 요청 시 읽음)",
    responses=_DETAIL_RESPONSES,
)
async def get_fuel_station_price_history(
    request: Request,
    store: StoreDep,
    feature_id: FeatureIdPath,
    product_code: Annotated[
        str | None,
        Query(
            min_length=1, max_length=20, description="오피넷 유종 코드(B027·D047·B034·C004·K015)."
        ),
    ] = None,
    since: Annotated[
        AwareDatetime | None,
        Query(description="이 시각 이상(observed_at). 없으면 until(또는 지금) 30일 전."),
    ] = None,
    until: Annotated[
        AwareDatetime | None,
        Query(description="이 시각 이하(observed_at). 없으면 지금. 미래·366일 넘는 창은 거부된다."),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="한 페이지의 전체 행 수(유종 합계).")
    ] = 200,
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=4096,
            description=(
                "이전 응답의 history.next_cursor(불투명). 같은 product_code·since·until로 보낸다. "
                "history.reason=cursor_expired면 받은 페이지를 버리고 cursor 없이 다시 시작한다."
            ),
        ),
    ] = None,
) -> FuelStationPriceHistoryResponse:
    started_at = perf_counter()
    if since is not None and until is not None and since > until:
        raise _problem(422, "VALIDATION_ERROR", "since는 until보다 늦을 수 없다.")
    item, meta = await _detail(store, DATASET_FUEL_STATIONS, FuelStationOut, feature_id)
    outcome = await fetch_price_history(
        KorTravelMapSettings(),
        item.natural_key,
        params=price_history_params(
            product_code=product_code, since=since, until=until, limit=limit, cursor=cursor
        ),
    )
    if outcome.history is not None:
        points = [
            PriceHistoryPoint(
                product_key=OPINET_PRODUCT_KEY_MAP.get(
                    point.product_code, point.product_code.lower()
                ),
                product_code=point.product_code,
                product_name=OPINET_PRODUCT_NAME_KO.get(
                    OPINET_PRODUCT_KEY_MAP.get(point.product_code, "")
                ),
                price=float(point.price) if point.price is not None else None,
                provider_updated_at=point.provider_updated_at,
                observed_at=point.observed_at,
                collected_at=point.collected_at,
            )
            for point in outcome.history.items
        ]
        history = PriceHistoryBlock(
            status="available",
            reason=None,
            generated_at=outcome.history.generated_at,
            source_collected_at=outcome.history.source_collected_at,
            source_status=outcome.history.source_status,
            has_more=outcome.history.has_more,
            next_cursor=outcome.history.next_cursor,
            truncated=outcome.history.has_more,
            items=points,
        )
    else:
        history = PriceHistoryBlock(
            status="unavailable",
            reason=outcome.reason,
            generated_at=None,
            source_collected_at=None,
            source_status=None,
            has_more=False,
            next_cursor=None,
            truncated=False,
            items=[],
        )
    return FuelStationPriceHistoryResponse(
        data=FuelStationPriceHistoryData(
            feature_id=item.feature_id,
            natural_key=item.natural_key,
            current_prices=list(item.prices),
            history=history,
            freshness=_freshness(DATASET_FUEL_STATIONS, meta),
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=limit, next_cursor=history.next_cursor
        ),
    )


# -- 휴게소 --------------------------------------------------------------------


@service_router.get(
    "/rest-areas",
    response_model=RestAreaListResponse,
    summary="고속도로 휴게소 + 휴게소 유가 (목록·근처·영역)",
    responses=_ERROR_RESPONSES,
)
async def list_rest_areas(
    request: Request, query: QueryDep, store: StoreDep
) -> RestAreaListResponse:
    started_at = perf_counter()
    listing = await _list(store, DATASET_REST_AREAS, RestAreaOut, query)
    items, price_freshness = await _attach_rest_area_prices(store, listing.items)
    return RestAreaListResponse(
        data=RestAreaListData(
            items=items,
            truncated=listing.truncated,
            freshness=_freshness(DATASET_REST_AREAS, listing.meta),
            fuel_price_freshness=price_freshness,
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=query.limit, next_cursor=listing.next_cursor
        ),
    )


@service_router.get(
    "/rest-areas/{feature_id}",
    response_model=RestAreaDetailResponse,
    summary="휴게소 한 곳",
    responses=_DETAIL_RESPONSES,
)
async def get_rest_area(
    request: Request, store: StoreDep, feature_id: FeatureIdPath
) -> RestAreaDetailResponse:
    started_at = perf_counter()
    item, meta = await _detail(store, DATASET_REST_AREAS, RestAreaOut, feature_id)
    items, price_freshness = await _attach_rest_area_prices(store, [item])
    return RestAreaDetailResponse(
        data=RestAreaDetailData(
            item=items[0],
            freshness=_freshness(DATASET_REST_AREAS, meta),
            fuel_price_freshness=price_freshness,
        ),
        meta=make_meta(request, started_at=started_at),
    )


# -- 돌발 ----------------------------------------------------------------------


@service_router.get(
    "/highway-incidents",
    response_model=HighwayIncidentListResponse,
    summary="고속도로 활성 돌발 (목록·근처·영역)",
    responses=_ERROR_RESPONSES,
)
async def list_highway_incidents(
    request: Request, query: QueryDep, store: StoreDep
) -> HighwayIncidentListResponse:
    started_at = perf_counter()
    listing = await _list(store, DATASET_HIGHWAY_INCIDENTS, HighwayIncidentOut, query)
    return HighwayIncidentListResponse(
        data=HighwayIncidentListData(
            items=listing.items,
            truncated=listing.truncated,
            freshness=_freshness(DATASET_HIGHWAY_INCIDENTS, listing.meta),
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=query.limit, next_cursor=listing.next_cursor
        ),
    )


@service_router.get(
    "/highway-incidents/{feature_id}",
    response_model=HighwayIncidentDetailResponse,
    summary="활성 돌발 한 건",
    responses=_DETAIL_RESPONSES,
)
async def get_highway_incident(
    request: Request, store: StoreDep, feature_id: FeatureIdPath
) -> HighwayIncidentDetailResponse:
    started_at = perf_counter()
    item, meta = await _detail(store, DATASET_HIGHWAY_INCIDENTS, HighwayIncidentOut, feature_id)
    return HighwayIncidentDetailResponse(
        data=HighwayIncidentDetailData(
            item=item, freshness=_freshness(DATASET_HIGHWAY_INCIDENTS, meta)
        ),
        meta=make_meta(request, started_at=started_at),
    )


# -- 공항 ----------------------------------------------------------------------


@service_router.get(
    "/airports",
    response_model=AirportListResponse,
    summary="국내 운영 공항 (목록·근처·영역)",
    responses=_ERROR_RESPONSES,
)
async def list_airports(request: Request, query: QueryDep, store: StoreDep) -> AirportListResponse:
    started_at = perf_counter()
    listing = await _list(store, DATASET_AIRPORTS, AirportOut, query)
    return AirportListResponse(
        data=AirportListData(
            items=listing.items,
            truncated=listing.truncated,
            freshness=_freshness(DATASET_AIRPORTS, listing.meta),
        ),
        meta=make_meta(
            request, started_at=started_at, page_size=query.limit, next_cursor=listing.next_cursor
        ),
    )


@service_router.get(
    "/airports/{feature_id}",
    response_model=AirportDetailResponse,
    summary="공항 한 곳",
    responses=_DETAIL_RESPONSES,
)
async def get_airport(
    request: Request, store: StoreDep, feature_id: FeatureIdPath
) -> AirportDetailResponse:
    started_at = perf_counter()
    item, meta = await _detail(store, DATASET_AIRPORTS, AirportOut, feature_id)
    return AirportDetailResponse(
        data=AirportDetailData(item=item, freshness=_freshness(DATASET_AIRPORTS, meta)),
        meta=make_meta(request, started_at=started_at),
    )


# -- 상태 ----------------------------------------------------------------------


@service_router.get(
    "/status",
    response_model=TransportStatusResponse,
    summary="Valkey 연결과 데이터셋별 신선도",
    responses={503: _ERROR_RESPONSES[503]},
)
async def get_transport_state_status(
    request: Request, store: StoreDep
) -> TransportStatusResponse:
    started_at = perf_counter()
    datasets: list[TransportDatasetStatus] = []
    async with _state_errors():
        await store.ping()
        for dataset in TRANSPORT_STATE_DATASETS:
            try:
                meta = await store.current_meta(dataset.name)
            except StateNotLoaded:
                datasets.append(
                    TransportDatasetStatus(dataset=dataset.name, loaded=False, freshness=None)
                )
                continue
            except StateStoreError as exc:
                datasets.append(
                    TransportDatasetStatus(
                        dataset=dataset.name, loaded=False, freshness=None, error=str(exc)
                    )
                )
                continue
            datasets.append(
                TransportDatasetStatus(
                    dataset=dataset.name, loaded=True, freshness=_freshness(dataset, meta)
                )
            )
    return TransportStatusResponse(
        data=TransportStatusData(store="ok", datasets=datasets),
        meta=make_meta(request, started_at=started_at),
    )
