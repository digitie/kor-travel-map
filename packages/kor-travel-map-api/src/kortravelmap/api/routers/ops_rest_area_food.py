"""``GET /v1/ops/rest-area-food/review`` — 휴게소 먹거리 연결·주유소 짝 검토 목록 (ADR-127).

휴게소 ↔ 한국도로공사 표준 코드 연결과 고속도로 주유소 ↔ 휴게소 짝은 규칙으로 자동 판정한다
(``providers.rest_area_food``). 자동으로 쓰지 않는 것만 여기서 본다 — 고치는 길은 규칙(코드)이고,
사람이
값을 덮어쓰는 저장소는 두지 않는다(소유자 결정 2026-11-27: "decide simply").

- ``unlinked_rest_areas``: 휴게소 상태(``transport.rest_areas``)에 있는데 먹거리 상태
  (``transport.rest_area_food``)에 없는 휴게소. 이름이 한국도로공사 표기와 다르거나 같은 이름이 둘
  이상이다.
- ``station_pairs``: 휴게소 400 m 안 주유소마다 고른 짝과 신뢰도. ``automatic=false``가 검토
  대상이다
  (PinVi에는 보이지 않는다). ``include_automatic=true``면 자동 짝도 함께 준다.

값은 Valkey 지금 세대만 읽는다(PG를 읽지 않는다).
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from kortravelmap.dto.transport_state import FuelStationState, RestAreaFoodState, RestAreaState
from kortravelmap.infra.valkey_state import StateNotLoaded, StateStoreError, ValkeyStateStore
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_FUEL_STATIONS,
    DATASET_REST_AREA_FOOD,
    DATASET_REST_AREAS,
)
from kortravelmap.providers.rest_area_food import (
    STATION_PAIR_AUTO_CONFIDENCE,
    STATION_PAIR_RADIUS_M,
    StationPairCandidate,
    pair_station,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.transport_state_service import get_state_store, state_unavailable

__all__ = ["router"]

router = APIRouter(prefix="/ops/rest-area-food", tags=["ops"])

StoreDep = Annotated[ValkeyStateStore, Depends(get_state_store)]
ModelT = TypeVar("ModelT", bound=BaseModel)


class UnlinkedRestArea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_id: str
    name: str
    natural_key: str


class StationPairReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_feature_id: str
    station_name: str
    rest_area_feature_id: str
    rest_area_name: str
    distance_m: float
    confidence: float
    method: str
    automatic: bool


class RestAreaFoodReviewData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rest_area_count: int
    linked_count: int
    unlinked_rest_areas: list[UnlinkedRestArea]
    station_count: int = Field(description="휴게소 400 m 안 주유소 수(짝 후보가 있는 주유소).")
    automatic_count: int
    auto_confidence: float = Field(description="자동 하한. 이 미만은 PinVi에 보이지 않는다.")
    station_pairs: list[StationPairReview]


class RestAreaFoodReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: RestAreaFoodReviewData
    meta: Meta


@router.get(
    "/review",
    response_model=RestAreaFoodReviewResponse,
    summary="휴게소 먹거리 연결·주유소 짝 검토 목록 (ADR-127)",
)
async def rest_area_food_review(
    request: Request,
    store: StoreDep,
    include_automatic: Annotated[
        bool, Query(description="자동으로 쓰는 짝도 함께 준다.")
    ] = False,
) -> RestAreaFoodReviewResponse:
    started_at = perf_counter()
    try:
        areas = await _all(store, DATASET_REST_AREAS.name, RestAreaState)
        foods = await _all(store, DATASET_REST_AREA_FOOD.name, RestAreaFoodState)
        stations_meta = await store.current_meta(DATASET_FUEL_STATIONS.name)
        located = [food for food in foods.values() if food.coord is not None]
        # 휴게소 약 215곳 × GEOSEARCH 한 번. 관리자 화면 한 번의 읽기라 묶지 않는다.
        hits_by_area = [
            await store.nearby(
                DATASET_FUEL_STATIONS.name,
                stations_meta.generation,
                lon=coord.lon,
                lat=coord.lat,
                radius_m=STATION_PAIR_RADIUS_M,
                count=20,
            )
            for food in located
            if (coord := food.coord) is not None
        ]
        candidates: dict[str, list[StationPairCandidate]] = {}
        for food, hits in zip(located, hits_by_area, strict=True):
            for station_id, distance in hits:
                candidates.setdefault(station_id, []).append(StationPairCandidate(
                    key=food.feature_id,
                    rest_area_name=food.rest_area_name,
                    direction_code=food.direction_code,
                    distance_m=distance,
                ))
        station_ids = sorted(candidates)
        raw_stations = await store.get_values(
            DATASET_FUEL_STATIONS.name, stations_meta.generation, station_ids
        )
    except StateNotLoaded as exc:
        raise state_unavailable(str(exc)) from exc
    except StateStoreError as exc:
        raise state_unavailable(str(exc)) from exc
    pairs: list[StationPairReview] = []
    for station_id, raw in zip(station_ids, raw_stations, strict=True):
        if raw is None:
            continue
        try:
            station = FuelStationState.model_validate_json(raw)
        except ValidationError:
            continue
        pair = pair_station(station.name, candidates[station_id])
        if pair is None:
            continue
        pairs.append(StationPairReview(
            station_feature_id=station_id,
            station_name=station.name,
            rest_area_feature_id=pair.key,
            rest_area_name=foods[pair.key].rest_area_name,
            distance_m=round(pair.distance_m, 1),
            confidence=pair.confidence,
            method=pair.method,
            automatic=pair.automatic,
        ))
    automatic = sum(1 for pair in pairs if pair.automatic)
    shown = pairs if include_automatic else [pair for pair in pairs if not pair.automatic]
    shown.sort(key=lambda pair: (pair.automatic, pair.confidence, pair.station_name))
    unlinked = [
        UnlinkedRestArea(feature_id=area.feature_id, name=area.name, natural_key=area.natural_key)
        for area in sorted(areas.values(), key=lambda area: area.name)
        if area.feature_id not in foods
    ]
    return RestAreaFoodReviewResponse(
        data=RestAreaFoodReviewData(
            rest_area_count=len(areas),
            linked_count=len(areas) - len(unlinked),
            unlinked_rest_areas=unlinked,
            station_count=len(pairs),
            automatic_count=automatic,
            auto_confidence=STATION_PAIR_AUTO_CONFIDENCE,
            station_pairs=shown,
        ),
        meta=make_meta(request, started_at=started_at),
    )


async def _all(
    store: ValkeyStateStore, dataset: str, model: type[ModelT]
) -> dict[str, ModelT]:
    meta = await store.current_meta(dataset)
    out: dict[str, ModelT] = {}
    for key, raw in (await store.generation_items(dataset, meta.generation)).items():
        try:
            out[key] = model.model_validate_json(raw)
        except ValidationError:
            continue
    return out
