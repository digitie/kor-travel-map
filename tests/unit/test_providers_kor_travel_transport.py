"""kor-travel-transport export 계약(ADR-106) — 파서·Protocol 결박·변환·vendored 계약 핀."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.dto import FeatureKind, PriceDomain
from kortravelmap.providers import kor_travel_transport as transport
from kortravelmap.providers.krairport import AirportMetadataItem, airports_to_bundles
from kortravelmap.providers.krex import (
    KrexRestAreaFuelPriceRecord,
    KrexRestAreaItem,
    KrexTrafficNoticeItem,
    rest_area_fuel_price_records_to_features_and_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from kortravelmap.providers.opinet import (
    OpinetStationItem,
    OpinetStationPriceRow,
    OpinetStationWithPrices,
    station_prices_to_features_and_values,
    stations_to_bundles,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = ROOT / "contracts" / "kor-travel-transport"
GOLDEN_DIR = CONTRACT_DIR / "golden"
FETCHED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


# -- vendored 계약 핀 ---------------------------------------------------------


def test_vendored_openapi_matches_its_pin() -> None:
    """vendored OpenAPI가 PIN.json의 SHA-256과 같다 — 손으로 고치면 빨개진다."""
    pin = json.loads((CONTRACT_DIR / "PIN.json").read_text(encoding="utf-8"))
    body = (CONTRACT_DIR / "openapi.json").read_bytes()
    assert hashlib.sha256(body).hexdigest() == pin["openapi_sha256"]
    assert len(pin["transport_revision"]) == 40


def test_vendored_openapi_declares_every_export_path_map_reads() -> None:
    spec = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))
    paths = set(spec["paths"])
    for path in (
        transport.EXPORT_PATH_FUEL_STATIONS,
        transport.EXPORT_PATH_REST_AREAS,
        transport.EXPORT_PATH_REST_AREA_FUEL_PRICES,
        transport.EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE,
        transport.EXPORT_PATH_AIRPORTS,
    ):
        assert path in paths, path


def test_golden_items_carry_every_field_the_vendored_schema_requires() -> None:
    """golden fixture가 vendored schema의 required 필드를 모두 가진다(계약과 fixture의 결박)."""
    schemas = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))["components"][
        "schemas"
    ]
    pairs = [
        ("fuel-stations.json", "ExportFuelStation"),
        ("rest-areas.json", "ExportRestArea"),
        ("rest-area-fuel-prices.json", "ExportRestAreaFuelPrice"),
        ("highway-incidents-active.json", "ExportHighwayIncident"),
        ("airports.json", "ExportAirport"),
    ]
    for file_name, schema_name in pairs:
        required = set(schemas[schema_name].get("required", []))
        for item in _golden(file_name)["items"]:
            assert required <= set(item), (file_name, required - set(item))


# -- 파서 -------------------------------------------------------------------


def test_fuel_station_golden_parses_into_the_opinet_protocols() -> None:
    page = transport.parse_export_page(_golden("fuel-stations.json"), where="fuel-stations")
    stations = [transport.parse_fuel_station(item) for item in page.items]
    assert stations
    station = stations[0]
    assert isinstance(station, OpinetStationItem)
    assert isinstance(station, OpinetStationWithPrices)
    assert all(isinstance(row, OpinetStationPriceRow) for row in station.prices)
    assert station.uni_id == page.items[0]["natural_key"]


def test_lpg_flag_follows_the_k015_price_row() -> None:
    item = _golden("fuel-stations.json")["items"][0]
    with_lpg = {**item, "prices": [*item["prices"], {**item["prices"][0], "product_code": "K015"}]}
    without_price = {
        **item,
        "prices": [*item["prices"], {**item["prices"][0], "product_code": "K015", "price": None}],
    }
    no_row = {**item, "prices": [row for row in item["prices"] if row["product_code"] != "K015"]}
    assert transport.parse_fuel_station(with_lpg).lpg_yn is True
    assert transport.parse_fuel_station(without_price).lpg_yn is False
    assert transport.parse_fuel_station(no_row).lpg_yn is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.pop("natural_key"), "natural_key"),
        (lambda item: item.update(prices="B027"), "prices"),
        (lambda item: item.update(latitude="37.5"), "latitude"),
        (lambda item: item.update(last_seen_at="2026-10-02T09:00:00"), "timezone"),
        (lambda item: item.update(is_self="Y"), "is_self"),
    ],
)
def test_fuel_station_contract_violations_fail_loudly(mutation: Any, message: str) -> None:
    item = json.loads(json.dumps(_golden("fuel-stations.json")["items"][0]))
    mutation(item)
    with pytest.raises(transport.TransportExportContractError, match=message):
        transport.parse_fuel_station(item)


def test_page_with_more_but_no_cursor_is_a_contract_violation() -> None:
    page = {**_golden("rest-areas.json"), "has_more": True, "next_cursor": None}
    with pytest.raises(transport.TransportExportContractError, match="next_cursor"):
        transport.parse_export_page(page, where="rest-areas")


def test_rest_area_and_price_golden_parse_into_the_krex_protocols() -> None:
    areas = [transport.parse_rest_area(item) for item in _golden("rest-areas.json")["items"]]
    prices = [
        transport.parse_rest_area_fuel_price(item)
        for item in _golden("rest-area-fuel-prices.json")["items"]
    ]
    assert areas
    assert prices
    assert all(isinstance(area, KrexRestAreaItem) for area in areas)
    assert all(isinstance(price, KrexRestAreaFuelPriceRecord) for price in prices)


def test_active_incident_set_parses_and_requires_raw_rows() -> None:
    body = _golden("highway-incidents-active.json")
    active = transport.parse_active_incident_set(body)
    assert active.items
    assert all(isinstance(item, KrexTrafficNoticeItem) for item in active.items)
    stripped = {**body, "items": [{**body["items"][0], "raw": None}]}
    with pytest.raises(transport.TransportExportContractError, match="raw"):
        transport.parse_active_incident_set(stripped)


def test_airports_golden_parses_into_the_airport_protocol() -> None:
    airports = transport.parse_airports(_golden("airports.json"))
    assert {airport.code for airport in airports} >= {"ICN", "KPO"}
    assert all(isinstance(airport, AirportMetadataItem) for airport in airports)
    with pytest.raises(transport.TransportExportContractError):
        transport.parse_airports({"items": []})


# -- 변환: provider 정체성과 자연키 ---------------------------------------------


async def test_fuel_station_place_and_price_use_the_transport_identity() -> None:
    page = transport.parse_export_page(_golden("fuel-stations.json"), where="fuel-stations")
    stations = [transport.parse_fuel_station(item) for item in page.items]
    places = await stations_to_bundles(stations, fetched_at=FETCHED_AT)
    assert {bundle.source_record.provider for bundle in places} == {"kor-travel-transport"}
    assert {bundle.source_record.dataset_key for bundle in places} == {"transport_fuel_stations"}
    assert [bundle.feature.provider_natural_key for bundle in places] == [
        station.uni_id for station in stations
    ]
    parents, price_bundles, values = await station_prices_to_features_and_values(
        stations, fetched_at=FETCHED_AT
    )
    assert price_bundles
    assert values
    assert {bundle.feature.kind for bundle in price_bundles} == {FeatureKind.PRICE}
    assert {bundle.source_record.dataset_key for bundle in price_bundles} == {
        "transport_fuel_prices"
    }
    parent_ids = {bundle.feature.feature_id for bundle in parents}
    assert all(bundle.feature.parent_feature_id in parent_ids for bundle in price_bundles)
    assert {value.price_domain for value in values} == {PriceDomain.OPINET_GAS_STATION}
    # 판매가가 null인 유종은 값을 만들지 않는다.
    priced = sum(1 for station in stations for row in station.prices if row.price is not None)
    assert len(values) == priced
    assert all(isinstance(value.value_number, Decimal) for value in values)


async def test_rest_area_natural_key_must_match_the_transport_key() -> None:
    items = [transport.parse_rest_area(item) for item in _golden("rest-areas.json")["items"]]
    bundles = await rest_areas_to_bundles(items, fetched_at=FETCHED_AT)
    assert [bundle.feature.provider_natural_key for bundle in bundles] == [
        item.natural_key for item in items
    ]
    assert {bundle.source_record.provider for bundle in bundles} == {"kor-travel-transport"}
    broken = transport.parse_rest_area(
        {**_golden("rest-areas.json")["items"][0], "natural_key": "다른::키::값"}
    )
    with pytest.raises(ValueError, match="자연키 불일치"):
        await rest_areas_to_bundles([broken], fetched_at=FETCHED_AT)


def test_rest_area_price_observed_at_is_the_transport_collection_time() -> None:
    records = [
        transport.parse_rest_area_fuel_price(item)
        for item in _golden("rest-area-fuel-prices.json")["items"]
    ]
    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        records, fetched_at=FETCHED_AT
    )
    assert bundles
    assert values
    assert {value.observed_at for value in values} == {record.observed_at for record in records}
    assert {bundle.source_record.dataset_key for bundle in bundles} == {
        "transport_rest_area_fuel_prices"
    }


async def test_incidents_and_airports_use_the_transport_identity() -> None:
    active = transport.parse_active_incident_set(_golden("highway-incidents-active.json"))
    notices = await traffic_notices_to_bundles(active.items, fetched_at=FETCHED_AT)
    assert {bundle.source_record.dataset_key for bundle in notices} == {
        "transport_highway_incidents"
    }
    airports = await airports_to_bundles(
        transport.parse_airports(_golden("airports.json")), fetched_at=FETCHED_AT
    )
    assert {bundle.source_record.dataset_key for bundle in airports} == {"transport_airports"}
    assert {bundle.feature.provider_natural_key for bundle in airports} >= {"ICN", "KPO"}
