"""kor-travel-transport export 소비(ADR-106) — 엄격 파서·Protocol 결박·변환."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.dto import Address, FeatureKind, PriceDomain
from kortravelmap.providers import kor_travel_transport as transport
from kortravelmap.providers.krairport import AirportMetadataItem, airports_to_bundles
from kortravelmap.providers.krex import (
    KrexRestAreaFuelPriceRecord,
    KrexRestAreaItem,
    KrexTrafficNoticeItem,
    rest_area_fuel_price_records_to_features_and_values,
    rest_area_place_locator_from_rows,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from kortravelmap.providers.opinet import (
    OpinetStationItem,
    OpinetStationPriceRow,
    OpinetStationWithPrices,
    fuel_station_place_locator_from_rows,
    station_prices_to_features_and_values,
    stations_to_bundles,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "tests" / "unit" / "golden" / "kor-travel-transport"
FETCHED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


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


@pytest.mark.parametrize(
    ("collection", "message"),
    [
        ({"last_success_at": None}, "이력"),
        ({"failed": True}, "실패"),
        ({"stale": True}, "stale"),
    ],
)
def test_a_page_whose_collection_is_not_current_is_refused(
    collection: dict[str, Any], message: str
) -> None:
    """transport가 200을 주더라도 플래그가 서 있으면 그 집합으로 reconcile하지 않는다(M1)."""
    body = _golden("rest-areas.json")
    page = transport.parse_export_page(
        {**body, "collection": {**body["collection"], **collection}}, where="rest-areas"
    )
    with pytest.raises(transport.TransportExportNotCurrent, match=message) as raised:
        transport.require_current_collection(page.collection, where="rest-areas")
    assert raised.value.failure_kind == "transport_not_current"


def test_a_collection_without_flags_is_a_contract_violation() -> None:
    body = _golden("rest-areas.json")
    flagless = {key: value for key, value in body["collection"].items() if key != "stale"}
    with pytest.raises(transport.TransportExportContractError, match="stale"):
        transport.parse_export_page({**body, "collection": flagless}, where="rest-areas")


def test_incident_set_age_is_measured_on_the_map_side() -> None:
    """transport의 503에만 기대지 않는다(M2) — 30분 넘은 집합은 종료 판단 근거가 아니다."""
    active = transport.parse_active_incident_set(_golden("highway-incidents-active.json"))
    collected = active.collected_at
    transport.require_fresh_incident_set(active, now=collected + timedelta(minutes=30))
    with pytest.raises(transport.TransportExportNotCurrent, match="지났다"):
        transport.require_fresh_incident_set(
            active, now=collected + timedelta(minutes=30, seconds=1)
        )
    with pytest.raises(transport.TransportExportNotCurrent, match="미래"):
        transport.require_fresh_incident_set(active, now=collected - timedelta(hours=1))
    failed = transport.parse_active_incident_set(
        {
            **_golden("highway-incidents-active.json"),
            "collection": {
                **_golden("highway-incidents-active.json")["collection"],
                "failed": True,
            },
        }
    )
    with pytest.raises(transport.TransportExportNotCurrent):
        transport.require_fresh_incident_set(failed, now=collected)


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
        transport.parse_airports({"items": None})


def test_an_empty_airport_list_is_its_own_failure() -> None:
    """공항 0건은 계약 위반이 아니라 "빈 완전 snapshot"이다 — 다른 export와 같은 분류로 실패한다."""
    with pytest.raises(transport.TransportExportEmpty) as raised:
        transport.parse_airports({"items": []})
    assert raised.value.failure_kind == "transport_empty"


def test_failure_classes_declare_whether_a_step_retry_can_help() -> None:
    """분류 선언만 본다. 이 선언으로 asset 경계가 실제로 step 재시도를 끄는지는 dagster
    ``test_quota_exhaustion_stops_step_retries.py``의 transport 경계 테스트가 확인한다."""
    assert transport.TransportExportNotCurrent("503").retryable is True
    assert transport.TransportExportNotCurrent("503").failure_kind == "transport_not_current"
    for terminal in (
        transport.TransportExportHidden("404"),
        transport.TransportExportEmpty("0"),
        transport.TransportExportContractError("shape"),
        transport.TransportExportMalformed("<html>"),
    ):
        assert terminal.retryable is False, type(terminal).__name__
    assert transport.TransportExportMalformed("x").failure_kind == "transport_malformed_upstream"


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
    # 가격 적재는 place를 다시 만들지 않는다 — 이미 적재된 place의 locator로 부모를 찾는다(M5).
    locator = fuel_station_place_locator_from_rows(
        (bundle.feature.provider_natural_key, bundle.feature.feature_id, 0.0, 0.0, Address())
        for bundle in places
    )
    price_bundles, values = station_prices_to_features_and_values(
        stations, fetched_at=FETCHED_AT, place_locator=locator
    )
    assert price_bundles
    assert values
    assert {bundle.feature.kind for bundle in price_bundles} == {FeatureKind.PRICE}
    assert {bundle.source_record.dataset_key for bundle in price_bundles} == {
        "transport_fuel_prices"
    }
    parent_ids = {bundle.feature.feature_id for bundle in places}
    assert all(bundle.feature.parent_feature_id in parent_ids for bundle in price_bundles)
    assert all(bundle.feature.coord is not None for bundle in price_bundles)
    # place가 아직 없는 주유소는 부모 없이 적재된다(다음 실행에서 붙는다).
    orphans, _ = station_prices_to_features_and_values(
        stations, fetched_at=FETCHED_AT, place_locator={}
    )
    assert {bundle.feature.parent_feature_id for bundle in orphans} == {None}
    assert {value.price_domain for value in values} == {PriceDomain.OPINET_GAS_STATION}
    # 판매가가 null인 유종은 값을 만들지 않는다.
    priced = sum(1 for station in stations for row in station.prices if row.price is not None)
    assert len(values) == priced
    assert all(isinstance(value.value_number, Decimal) for value in values)


def test_fuel_price_observed_at_is_the_last_confirmation_not_the_price_change() -> None:
    """M3: ``observed_at``은 transport가 그 값을 현재가로 마지막 확인한 시각(``collected_at``)이다.

    오피넷 갱신시각(``*_DT``)은 가격을 **바꾼** 때라 며칠씩 묵는다 — 그것을 쓰면 가격을 유지 중인
    주유소가 현재가 지평선(4일) 밖으로 밀려 사라진다. 갱신시각은 payload에 보존한다.
    """
    item = json.loads(json.dumps(_golden("fuel-stations.json")["items"][0]))
    changed = "2026-09-20T08:00:00Z"
    confirmed = "2026-10-02T07:34:44Z"
    for row in item["prices"]:
        row.update(provider_updated_at=changed, observed_at=changed, collected_at=confirmed)
    station = transport.parse_fuel_station(item)
    _, values = station_prices_to_features_and_values(
        [station], fetched_at=FETCHED_AT, place_locator={}
    )
    assert values
    assert {value.observed_at for value in values} == {
        datetime(2026, 10, 2, 7, 34, 44, tzinfo=UTC)
    }
    assert {value.payload["provider_updated_at"] for value in values} == {
        "2026-09-20T08:00:00+00:00"
    }


def test_fuel_price_feature_keeps_the_place_region_codes() -> None:
    """가격 feature는 옛 OpiNet 경로처럼 주유소 place의 bjd·시군구·시도 코드를 가진다.

    transport export에는 지역 코드가 없다. 가격 job은 역지오코딩하지 않으므로(M5) 이미 적재된
    place(역지오코딩 보강을 거친 것)의 코드를 locator로 받는다.
    """
    station = transport.parse_fuel_station(_golden("fuel-stations.json")["items"][0])
    region = Address(
        admin="충청남도 태안군 근흥면",
        bjd_code="4482534000",
        sigungu_code="44825",
        sido_code="44",
    )
    locator = fuel_station_place_locator_from_rows(
        [(station.uni_id, "place-1", 126.19, 36.69, region)]
    )
    [bundle], _ = station_prices_to_features_and_values(
        [station], fetched_at=FETCHED_AT, place_locator=locator
    )
    address = bundle.feature.address
    assert (address.bjd_code, address.sigungu_code, address.sido_code) == (
        "4482534000",
        "44825",
        "44",
    )
    assert address.admin == "충청남도 태안군 근흥면"
    assert address.road == station.address_road
    assert bundle.feature.parent_feature_id == "place-1"


def test_rest_area_price_feature_keeps_the_place_region_codes() -> None:
    record = transport.parse_rest_area_fuel_price(
        _golden("rest-area-fuel-prices.json")["items"][0]
    )
    region = Address(bjd_code="4427010100", sigungu_code="44270", sido_code="44")
    locator = rest_area_place_locator_from_rows(
        [("행담도::서해안선::목포", "place-ra", 126.78, 36.95, region)]
    )
    [bundle], _ = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=FETCHED_AT, place_locator=locator
    )
    assert bundle.feature.parent_feature_id == "place-ra"
    address = bundle.feature.address
    assert (address.bjd_code, address.sigungu_code, address.sido_code) == (
        "4427010100",
        "44270",
        "44",
    )


def test_fuel_price_rows_require_the_confirmation_time() -> None:
    item = json.loads(json.dumps(_golden("fuel-stations.json")["items"][0]))
    del item["prices"][0]["collected_at"]
    with pytest.raises(transport.TransportExportContractError, match="collected_at"):
        transport.parse_fuel_station(item)


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
