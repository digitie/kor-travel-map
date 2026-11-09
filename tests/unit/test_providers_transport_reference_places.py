"""transport 철도역·항구 기준정보 → place Feature (ADR-120) — 엄격 파서·묶음·표시 이름."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.category import category_search_group
from kortravelmap.dto import Address, Coordinate, FeatureKind
from kortravelmap.providers import kor_travel_transport as transport
from kortravelmap.providers.transport_reference_places import (
    FERRY_PORT_CATEGORY,
    RAIL_STATION_SUBWAY_CATEGORY,
    RAIL_STATION_TRAIN_CATEGORY,
    ferry_port_display_name,
    ferry_ports_to_bundles,
    rail_station_display_name,
    rail_station_name_key,
    rail_stations_to_bundles,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "tests" / "unit" / "golden" / "kor-travel-transport"
FETCHED_AT = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)


def _golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


def _rail(**overrides: Any) -> transport.TransportRailStation:
    item = {**_golden("rail-stations.json")["items"][2], **overrides}
    return transport.parse_rail_station(item)


# -- envelope ---------------------------------------------------------------


def test_reference_page_golden_parses() -> None:
    page = transport.parse_reference_page(_golden("rail-stations.json"), where="rail-stations")
    assert page.total_count == 3
    assert page.meta.item_count == len(page.items) == 3
    assert page.meta.source_status == "ok"
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.snapshot_id == "3f2b6c1e-6a2d-4c55-9a1b-7f0e9d6a1c01"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda body: body["meta"].update(source_status="failed"), "source_status"),
        (lambda body: body["meta"].update(source_status=None), "source_status"),
        (lambda body: body["meta"].update(source_collected_at=None), "source_collected_at"),
        (lambda body: body["meta"].update(item_count=2), "item_count"),
        (lambda body: body["meta"].update(item_count=True), "item_count"),
        (lambda body: body.update(total_count=-1), "total_count"),
        (lambda body: body.pop("snapshot_id"), "snapshot_id"),
        (lambda body: body.update(has_more=True), "next_cursor"),
        (lambda body: body.update(next_cursor="c1"), "next_cursor"),
        (lambda body: body.update(items={}), "items"),
    ],
)
def test_reference_page_contract_violations_fail_loudly(mutation: Any, message: str) -> None:
    body = _golden("rail-stations.json")
    mutation(body)
    with pytest.raises(transport.TransportExportContractError, match=message):
        transport.parse_reference_page(body, where="rail-stations")


def test_stale_reference_page_is_accepted_as_the_last_complete_set() -> None:
    body = _golden("ferry-ports.json")
    body["meta"]["source_status"] = "stale"
    assert transport.parse_reference_page(body, where="ferry-ports").meta.source_status == "stale"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.pop("natural_key"), "natural_key"),
        (lambda item: item.update(name="  "), "name"),
        (lambda item: item.update(latitude=None), "latitude"),
        (lambda item: item.update(longitude="127.4"), "longitude"),
        (lambda item: item.update(admin="서울"), "admin"),
        (lambda item: item.update(operator_name=3), "operator_name"),
    ],
)
def test_rail_station_contract_violations_fail_loudly(mutation: Any, message: str) -> None:
    item = _golden("rail-stations.json")["items"][2]
    mutation(item)
    with pytest.raises(transport.TransportExportContractError, match=message):
        transport.parse_rail_station(item)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.update(natural_key="other:INC"), "natural_key"),
        (lambda item: item.pop("port_id"), "port_id"),
        (lambda item: item.update(latitude=None), "latitude"),
    ],
)
def test_ferry_port_contract_violations_fail_loudly(mutation: Any, message: str) -> None:
    item = _golden("ferry-ports.json")["items"][0]
    mutation(item)
    with pytest.raises(transport.TransportExportContractError, match=message):
        transport.parse_ferry_port(item)


# -- 표시 이름 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "display"),
    [("중앙", "중앙역"), ("서울역", "서울역"), (" 대전 ", "대전역"), ("역", "역")],
)
def test_rail_station_display_name_appends_the_station_suffix_once(
    name: str, display: str
) -> None:
    assert rail_station_display_name(name) == display
    assert rail_station_display_name(display) == display


def test_rail_station_name_key_ignores_spacing_and_the_station_suffix() -> None:
    assert rail_station_name_key("서울역") == rail_station_name_key("서울") == "서울"
    assert rail_station_name_key("디지털 미디어시티") == "디지털미디어시티"
    assert rail_station_name_key("역") == "역"


@pytest.mark.parametrize(
    ("name", "display"),
    [
        ("인천항", "인천항"),
        ("성산포항 종합여객터미널", "성산포항 종합여객터미널"),
        ("삼목선착장", "삼목선착장"),
        ("백령도", "백령도 여객선터미널"),
        ("인천", "인천 여객선터미널"),
    ],
)
def test_ferry_port_display_name_says_it_is_a_ferry_terminal(name: str, display: str) -> None:
    assert ferry_port_display_name(name) == display
    assert ferry_port_display_name(display) == display


# -- 철도역 묶음 ---------------------------------------------------------------


async def test_lines_of_one_station_become_one_feature() -> None:
    page = transport.parse_reference_page(_golden("rail-stations.json"), where="rail-stations")
    stations = [transport.parse_rail_station(item) for item in page.items]
    bundles = await rail_stations_to_bundles(stations, fetched_at=FETCHED_AT)
    by_name = {bundle.feature.name: bundle for bundle in bundles}
    assert sorted(by_name) == ["대전역", "서울역"]
    seoul = by_name["서울역"]
    assert seoul.feature.kind is FeatureKind.PLACE
    # 국가철도(한국철도공사) 노선이 있으면 기차역이다.
    assert seoul.feature.category == RAIL_STATION_TRAIN_CATEGORY
    assert seoul.feature.marker_icon == "rail"
    # 자연키는 anchor(자연키가 가장 작은 행)의 것 — ``|``는 ``::``로.
    assert seoul.feature.provider_natural_key == "서울교통공사::1호선::133::서울역"
    assert seoul.source_record.source_entity_id == seoul.feature.provider_natural_key
    assert seoul.source_record.dataset_key == transport.DATASET_KEY_RAIL_STATIONS
    assert seoul.feature.detail is not None
    facility = seoul.feature.detail.facility_info
    assert facility["line_count"] == 2
    assert facility["lines"] == ["1호선", "경의중앙선"]
    # 지하철만 있는 역은 지하철역이다.
    daejeon = by_name["대전역"]
    assert daejeon.feature.category == RAIL_STATION_SUBWAY_CATEGORY
    assert daejeon.feature.marker_icon == "rail-metro"
    for bundle in bundles:
        assert category_search_group(bundle.feature.category) == 1


async def test_station_grouping_does_not_depend_on_input_order() -> None:
    stations = [
        _rail(natural_key=f"운영사{i}|{i}호선|{i}|중앙", name="중앙", latitude=35.87 + i * 0.001)
        for i in range(4)
    ]
    expected = [
        b.source_record.raw_payload_hash
        for b in await rail_stations_to_bundles(stations, fetched_at=FETCHED_AT)
    ]
    shuffled = list(stations)
    random.Random(7).shuffle(shuffled)
    again = [
        b.source_record.raw_payload_hash
        for b in await rail_stations_to_bundles(shuffled, fetched_at=FETCHED_AT)
    ]
    assert again == expected
    assert len(expected) == 1  # 네 행 모두 anchor에서 500 m 안이다.


async def test_a_new_line_does_not_re_mint_an_existing_station() -> None:
    """환승역에 자연키가 더 작은 노선이 새로 들어와도 이미 적재된 자연키가 anchor로 남는다."""
    old = _rail(natural_key="서울교통공사|1호선|133|서울역", name="서울역",
                latitude=37.5546, longitude=126.9706)
    [first] = await rail_stations_to_bundles([old], fetched_at=FETCHED_AT)
    new_line = _rail(natural_key="공항철도|공항철도|A01|서울역", name="서울역",
                     latitude=37.5536, longitude=126.9698)
    without_history = await rail_stations_to_bundles([old, new_line], fetched_at=FETCHED_AT)
    assert without_history[0].feature.provider_natural_key == "공항철도::공항철도::A01::서울역"
    [kept] = await rail_stations_to_bundles(
        [old, new_line],
        fetched_at=FETCHED_AT,
        existing_natural_keys={first.feature.provider_natural_key},
    )
    assert kept.feature.provider_natural_key == first.feature.provider_natural_key
    assert kept.feature.detail is not None
    assert kept.feature.detail.facility_info["line_count"] == 2


async def test_a_member_within_the_radius_of_any_member_joins_the_station() -> None:
    """반경은 anchor 한 점이 아니라 묶음의 어느 구성원에서든 잰다 — 큰 환승역이 갈리지 않는다."""
    rows = [
        _rail(natural_key=f"운영사{i}|{i}호선|{i}|김포공항", name="김포공항",
              latitude=37.5620, longitude=126.8010 + i * 0.004)
        for i in range(3)  # 이웃 사이 약 350 m, 양 끝 약 700 m
    ]
    bundles = await rail_stations_to_bundles(rows, fetched_at=FETCHED_AT)
    assert len(bundles) == 1


async def test_same_name_stations_far_apart_stay_separate() -> None:
    # 2호선 신촌과 경의중앙선 신촌 — 약 700 m 떨어진 별개 역.
    line2 = _rail(
        natural_key="서울교통공사|2호선|240|신촌", name="신촌",
        operator_name="서울교통공사", latitude=37.5552, longitude=126.9369,
    )
    gyeongui = _rail(
        natural_key="한국철도공사|경의중앙선|P312|신촌", name="신촌",
        operator_name="한국철도공사", latitude=37.5598, longitude=126.9425,
    )
    bundles = await rail_stations_to_bundles([line2, gyeongui], fetched_at=FETCHED_AT)
    assert len(bundles) == 2
    assert {b.feature.name for b in bundles} == {"신촌역"}
    assert {b.feature.category for b in bundles} == {
        RAIL_STATION_TRAIN_CATEGORY,
        RAIL_STATION_SUBWAY_CATEGORY,
    }


async def test_coordless_station_rows_make_no_feature() -> None:
    coordless = _rail(natural_key="운영사|1호선|1|좌표없음", name="좌표없음", latitude=None,
                      longitude=None)
    outside = _rail(natural_key="운영사|1호선|2|범위밖", name="범위밖", latitude=10.0,
                    longitude=10.0)
    assert await rail_stations_to_bundles([coordless, outside], fetched_at=FETCHED_AT) == []


async def test_duplicate_station_identity_fails_instead_of_guessing() -> None:
    station = _rail()
    with pytest.raises(ValueError, match="중복"):
        await rail_stations_to_bundles([station, station], fetched_at=FETCHED_AT)


async def test_station_address_comes_from_map_reverse_geocoding() -> None:
    calls: list[Coordinate] = []

    async def geocoder(coord: Coordinate) -> Address | None:
        calls.append(coord)
        return Address(bjd_code="3011010100", admin="대전광역시 동구 정동")

    bundles = await rail_stations_to_bundles(
        [_rail()], fetched_at=FETCHED_AT, reverse_geocoder=geocoder
    )
    assert len(calls) == 1
    address = bundles[0].feature.address
    assert address is not None
    assert address.bjd_code == "3011010100"
    assert address.sido_code == "30"
    assert address.sigungu_code == "30110"


# -- 항구 --------------------------------------------------------------------


async def test_ferry_ports_become_ferry_terminal_places() -> None:
    page = transport.parse_reference_page(_golden("ferry-ports.json"), where="ferry-ports")
    ports = [transport.parse_ferry_port(item) for item in page.items]
    bundles = await ferry_ports_to_bundles(ports, fetched_at=FETCHED_AT)
    # 좌표 없는 항구(가이드라인 한 점 → transport가 null로 낸다)는 Feature를 만들지 않는다.
    assert [b.feature.name for b in bundles] == ["백령도 여객선터미널", "인천항"]
    for bundle in bundles:
        assert bundle.feature.category == FERRY_PORT_CATEGORY
        assert bundle.feature.marker_icon == "ferry"
        assert bundle.source_record.dataset_key == transport.DATASET_KEY_FERRY_PORTS
        assert category_search_group(bundle.feature.category) == 1
    assert bundles[1].feature.provider_natural_key == "datagokr_maritime:INC"


async def test_duplicate_ferry_port_fails_instead_of_guessing() -> None:
    port = transport.parse_ferry_port(_golden("ferry-ports.json")["items"][0])
    with pytest.raises(ValueError, match="중복"):
        await ferry_ports_to_bundles([port, port], fetched_at=FETCHED_AT)
