"""휴게소 먹거리 표면(ADR-127) — 휴게소·주유소 상세와 관리자 검토 목록을 가짜 Valkey로 잰다.

실제 Valkey 교체·GEO는 ``tests/integration/test_valkey_transport_state.py``가 소유한다.
여기서는 응답 모양,
주유소 짝 규칙 적용(자동/검토), 데이터셋 미적재·읽기 실패 때 상세가 그대로 나가는지를 본다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.dto.transport_state import (
    FuelStationState,
    RestAreaFoodState,
    RestAreaMenuItemState,
    RestAreaState,
    RestAreaStationPairState,
    StateAddress,
    StateCoordinate,
)
from kortravelmap.infra.valkey_state import GenerationMeta, StateNotLoaded, StateStoreError

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import ROUTE_POLICIES, RoutePolicy
from kortravelmap.api.settings import ApiSettings
from kortravelmap.api.transport_state_service import get_state_store, set_state_store_for_test

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)
_REST_DOWN = "f_global_p_rest_down"
_REST_UP = "f_global_p_rest_up"
_REST_FAR = "f_global_p_rest_nofood"
_STATION_DOWN = "f_global_p_station_down"
_STATION_LOCAL = "f_global_p_station_local"


def _rest(feature_id: str, name: str) -> RestAreaState:
    return RestAreaState(
        feature_id=feature_id, category="06040101", marker_icon="fast-food", marker_color="P-06",
        name=name, natural_key=f"{feature_id}::::", coord=StateCoordinate(lon=128.2, lat=36.4),
        address=StateAddress(),
    )


def _food(
    feature_id: str,
    name: str,
    direction: Any,
    stations: list[RestAreaStationPairState] | None = None,
) -> RestAreaFoodState:
    return RestAreaFoodState(
        feature_id=feature_id, rest_area_name=name, natural_key=f"{feature_id}::::",
        coord=StateCoordinate(lon=128.2, lat=36.4), std_rest_code="000101", ex_name=name,
        route_code="0010", route_name="경부선", direction_code=direction, link_method="name_exact",
        link_confidence=1.0, menu_count=2, price_min=4500, price_median=4500, price_max=9000,
        featured=[
            RestAreaMenuItemState(name="소떡소떡", price=4500, tags=["best"], season="all_year")
        ],
        seasonal=[], menu_updated_on=date(2026, 1, 9), source_collected_at=_NOW,
        stations=stations or [],
    )


def _pair(feature_id: str, name: str, distance: float, confidence: float, method: str) -> Any:
    return RestAreaStationPairState(
        feature_id=feature_id, name=name, distance_m=distance, confidence=confidence,
        method=method, automatic=confidence >= 0.8,
    )


def _station(feature_id: str, name: str) -> FuelStationState:
    return FuelStationState(
        feature_id=feature_id, category="06010101", marker_icon="fuel", marker_color="P-08",
        name=name, natural_key=feature_id, coord=StateCoordinate(lon=128.2001, lat=36.4001),
        address=StateAddress(), prices=[], source_last_seen_at=_NOW,
    )


_VALUES: dict[str, dict[str, str]] = {
    "transport.rest_areas": {
        _REST_DOWN: _rest(_REST_DOWN, "사천휴게소(부산방향)").model_dump_json(),
        _REST_UP: _rest(_REST_UP, "사천휴게소(순천방향)").model_dump_json(),
        _REST_FAR: _rest(_REST_FAR, "없는휴게소(서울방향)").model_dump_json(),
    },
    "transport.rest_area_food": {
        _REST_DOWN: _food(
            _REST_DOWN, "사천휴게소(부산방향)", "down",
            [
                _pair(_STATION_DOWN, "YM21유통 사천(하)주유소/충전소", 14.0, 0.85,
                      "name_updown_nearest"),
                _pair(_STATION_LOCAL, "상서현대셀프", 190.0, 0.3, "distance_only"),
            ],
        ).model_dump_json(),
        _REST_UP: _food(_REST_UP, "사천휴게소(순천방향)", "up").model_dump_json(),
    },
    "transport.fuel_stations": {
        _STATION_DOWN: _station(_STATION_DOWN, "YM21유통 사천(하)주유소/충전소").model_dump_json(),
        _STATION_LOCAL: _station(_STATION_LOCAL, "상서현대셀프").model_dump_json(),
    },
}
_LOOKUP = {"transport.rest_area_food": {_STATION_DOWN: _REST_DOWN}}


class _FakeStore:
    fail: dict[str, type[Exception]] = {}

    async def current_meta(self, dataset: str) -> GenerationMeta:
        if dataset in self.fail:
            raise self.fail[dataset](dataset)
        return GenerationMeta(
            dataset=dataset, generation="g-1", count=len(_VALUES.get(dataset, {})), geo_count=0,
            lookup_count=0, duplicates=0, source_collected_at=_NOW, loaded_at=_NOW, run_id=None,
            guard_override=False,
        )

    async def get_values(self, dataset: str, generation: str, ids: list[str]) -> list[str | None]:
        return [_VALUES.get(dataset, {}).get(key) for key in ids]

    async def lookup(self, dataset: str, generation: str, keys: list[str]) -> list[str | None]:
        return [_LOOKUP.get(dataset, {}).get(key) for key in keys]

    async def generation_items(self, dataset: str, generation: str) -> dict[str, bytes]:
        return {key: value.encode() for key, value in _VALUES.get(dataset, {}).items()}


@pytest.fixture
def client() -> Iterator[TestClient]:
    set_state_store_for_test(None)
    _FakeStore.fail = {}
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    app.dependency_overrides[get_state_store] = _FakeStore
    yield TestClient(app)
    set_state_store_for_test(None)


def test_rest_area_detail_carries_the_food_summary(client: TestClient) -> None:
    response = client.get(f"/v1/service/transport/rest-areas/{_REST_DOWN}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["food"]["std_rest_code"] == "000101"
    assert data["food"]["featured"][0] == {
        "name": "소떡소떡", "price": 4500, "tags": ["best"], "season": "all_year",
    }
    assert data["food"]["attribution"] == "한국도로공사"
    assert data["food_freshness"]["dataset"] == "transport.rest_area_food"
    # 검토 짝(automatic=false)은 서비스 응답에 싣지 않는다.
    assert [entry["automatic"] for entry in data["food"]["stations"]] == [True]


def test_rest_area_without_a_link_or_dataset_keeps_the_detail(client: TestClient) -> None:
    far = client.get(f"/v1/service/transport/rest-areas/{_REST_FAR}").json()["data"]
    assert far["food"] is None
    _FakeStore.fail = {"transport.rest_area_food": StateNotLoaded}
    body = client.get(f"/v1/service/transport/rest-areas/{_REST_DOWN}").json()["data"]
    assert body["food"] is None
    assert body["food_freshness"] is None
    _FakeStore.fail = {"transport.rest_area_food": StateStoreError}
    assert client.get(f"/v1/service/transport/rest-areas/{_REST_DOWN}").status_code == 200


def test_fuel_station_detail_pairs_the_same_direction_rest_area(client: TestClient) -> None:
    data = client.get(f"/v1/service/transport/fuel-stations/{_STATION_DOWN}").json()["data"]
    paired = data["rest_area_food"]
    assert paired["rest_area"]["feature_id"] == _REST_DOWN
    assert paired["method"] == "name_updown_nearest"
    assert paired["confidence"] >= 0.8
    assert paired["distance_m"] == 14.0


def test_an_uncertain_pair_is_not_shown(client: TestClient) -> None:
    data = client.get(f"/v1/service/transport/fuel-stations/{_STATION_LOCAL}").json()["data"]
    assert data["rest_area_food"] is None
    assert data["food_freshness"]["dataset"] == "transport.rest_area_food"


def test_review_lists_unlinked_rest_areas_and_uncertain_pairs(client: TestClient) -> None:
    assert ROUTE_POLICIES["/v1/ops/rest-area-food/review"] is RoutePolicy.OPERATOR
    response = client.get("/v1/ops/rest-area-food/review")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["rest_area_count"] == 3
    assert data["linked_count"] == 2
    assert [area["feature_id"] for area in data["unlinked_rest_areas"]] == [_REST_FAR]
    assert data["station_count"] == 2
    assert data["automatic_count"] == 1
    assert [pair["station_feature_id"] for pair in data["station_pairs"]] == [_STATION_LOCAL]
    everything = client.get(
        "/v1/ops/rest-area-food/review", params={"include_automatic": "true"}
    ).json()["data"]["station_pairs"]
    assert {pair["station_feature_id"] for pair in everything} == {_STATION_DOWN, _STATION_LOCAL}


def test_review_is_503_when_a_dataset_is_missing(client: TestClient) -> None:
    _FakeStore.fail = {"transport.rest_area_food": StateNotLoaded}
    assert client.get("/v1/ops/rest-area-food/review").status_code == 503
