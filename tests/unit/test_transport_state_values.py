"""ADR-114 D1 — transport export 행 → Valkey 상태 값.

id는 PG 변환과 같은 규칙(``bjd_code=None``)이다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from kortravelmap.dto.transport_state import (
    AirportState,
    FuelStationState,
    HighwayIncidentState,
    RestAreaFuelPriceState,
    RestAreaState,
)
from kortravelmap.providers import kor_travel_transport as transport
from kortravelmap.providers.kor_travel_transport_state import (
    airport_state,
    fuel_station_state,
    highway_incident_state,
    rest_area_fuel_price_state,
    rest_area_state,
    state_coordinate,
    to_state_item,
)
from kortravelmap.providers.krairport import airports_to_bundles
from kortravelmap.providers.krex import (
    rest_area_fuel_price_records_to_features_and_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from kortravelmap.providers.opinet import stations_to_bundles

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).resolve().parent / "golden" / "kor-travel-transport"
FETCHED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _golden(name: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((GOLDEN / name).read_text(encoding="utf-8")))


def _stations() -> list[transport.TransportFuelStation]:
    page = transport.parse_export_page(_golden("fuel-stations.json"), where="fuel-stations")
    return [transport.parse_fuel_station(item) for item in page.items]


def _rest_areas() -> list[transport.TransportRestArea]:
    page = transport.parse_export_page(_golden("rest-areas.json"), where="rest-areas")
    return [transport.parse_rest_area(item) for item in page.items]


def _rest_area_prices() -> list[transport.TransportRestAreaFuelPrice]:
    page = transport.parse_export_page(
        _golden("rest-area-fuel-prices.json"), where="rest-area-fuel-prices"
    )
    return [transport.parse_rest_area_fuel_price(item) for item in page.items]


def _incidents() -> tuple[transport.TransportHighwayIncident, ...]:
    return transport.parse_active_incident_set(_golden("highway-incidents-active.json")).items


def _airports() -> tuple[transport.TransportAirport, ...]:
    return transport.parse_airports(_golden("airports.json"))


# -- id가 PG 변환(bjd_code=None 경로)과 같다 ----------------------------------------


async def test_fuel_station_id_is_the_pg_place_id_without_bjd() -> None:
    stations = _stations()
    bundles = await stations_to_bundles(cast("Any", stations), fetched_at=FETCHED_AT)
    assert [fuel_station_state(s).feature_id for s in stations] == [
        b.feature.feature_id for b in bundles
    ]
    assert all(fuel_station_state(s).feature_id.startswith("f_global_p_") for s in stations)


async def test_rest_area_id_is_the_pg_place_id_without_bjd() -> None:
    areas = _rest_areas()
    bundles = await rest_areas_to_bundles(cast("Any", areas), fetched_at=FETCHED_AT)
    assert [rest_area_state(a).feature_id for a in areas] == [
        b.feature.feature_id for b in bundles
    ]


def test_rest_area_fuel_price_id_is_the_pg_price_id() -> None:
    records = _rest_area_prices()
    bundles, _ = rest_area_fuel_price_records_to_features_and_values(
        cast("Any", records), fetched_at=FETCHED_AT
    )
    assert [rest_area_fuel_price_state(r).feature_id for r in records] == [
        b.feature.feature_id for b in bundles
    ]


async def test_highway_incident_id_and_title_match_the_pg_notice() -> None:
    incidents = _incidents()
    bundles = await traffic_notices_to_bundles(cast("Any", incidents), fetched_at=FETCHED_AT)
    states = [highway_incident_state(i) for i in incidents]
    assert [s.feature_id for s in states] == [b.feature.feature_id for b in bundles]
    assert [s.title for s in states] == [b.feature.name for b in bundles]
    assert states[0].occurred_at is not None
    assert states[0].occurred_at.utcoffset() is not None


async def test_airport_id_is_the_pg_place_id_without_bjd() -> None:
    airports = _airports()
    bundles = await airports_to_bundles(cast("Any", airports), fetched_at=FETCHED_AT)
    states = [airport_state(a) for a in airports]
    assert [s.feature_id for s in states] == [b.feature.feature_id for b in bundles]
    assert [s.marker_icon for s in states] == [b.feature.marker_icon for b in bundles]


def test_ids_do_not_depend_on_a_later_admin_block() -> None:
    """VWorld 행정 블록이 실려도(결정 6) id는 바뀌지 않는다 — bjd는 id 입력이 아니다."""
    station = _stations()[0]
    moved = replace(station, address_road="전혀 다른 주소", lat=37.0, lon=127.0)
    assert fuel_station_state(moved).feature_id == fuel_station_state(station).feature_id


# -- 값 ----------------------------------------------------------------------------


def test_fuel_station_value_carries_location_and_latest_prices() -> None:
    station = _stations()[0]
    value = fuel_station_state(station)
    assert value.natural_key == station.uni_id
    assert value.coord is not None
    assert {p.product_code for p in value.prices} == {p.product_code for p in station.prices}
    assert all(p.collected_at.utcoffset() is not None for p in value.prices)
    assert value.address.bjd_code is None
    roundtrip = FuelStationState.model_validate_json(value.model_dump_json())
    assert roundtrip == value


def test_rest_area_natural_key_mismatch_is_a_contract_error() -> None:
    area = _rest_areas()[0]
    with pytest.raises(transport.TransportExportContractError, match="자연키"):
        rest_area_state(replace(area, natural_key="다른::키::값"))


def test_rest_area_price_carries_the_match_key_of_its_rest_area() -> None:
    area = rest_area_state(_rest_areas()[0])
    record = _rest_area_prices()[0]
    price = rest_area_fuel_price_state(
        replace(
            record,
            service_area_name=_rest_areas()[0].name,
            route_name=_rest_areas()[0].route_name,
            direction=_rest_areas()[0].direction,
        )
    )
    assert price.match_key == area.natural_key
    item = to_state_item(price, lookup_keys=(price.match_key or "",))
    assert item.lookup_keys == (area.natural_key,)
    assert item.coord is None


@pytest.mark.parametrize(
    ("lon", "lat", "kept"),
    [
        (127.0, 37.5, True),
        (0.0, 0.0, False),
        (127.0, None, False),
        (-73.9, 40.7, False),
        (127.0, 89.0, False),
        (float("nan"), 37.0, False),
    ],
)
def test_coordinates_outside_korea_are_dropped(
    lon: float | None, lat: float | None, kept: bool
) -> None:
    assert (state_coordinate(lon, lat) is not None) is kept


def test_state_item_carries_id_value_and_geo_coordinate() -> None:
    value = airport_state(_airports()[0])
    item = to_state_item(value)
    assert item.id == value.feature_id
    assert AirportState.model_validate_json(item.value) == value
    if value.coord is not None:
        assert item.coord == (value.coord.lon, value.coord.lat)


def test_values_reject_unknown_fields() -> None:
    """값 모델은 extra=forbid — 저장된 JSON과 모델이 갈라지면 읽기가 실패해야 한다(503)."""
    value = rest_area_state(_rest_areas()[0])
    data = json.loads(value.model_dump_json())
    data["surprise"] = 1
    with pytest.raises(ValueError, match="surprise"):
        RestAreaState.model_validate(data)
    for model in (HighwayIncidentState, RestAreaFuelPriceState):
        assert model.model_config.get("extra") == "forbid"
