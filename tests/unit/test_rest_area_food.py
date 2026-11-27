"""휴게소 먹거리 연결·요약·주유소 짝 규칙 (ADR-127).

이름 표본은 2026-11-27 운영 Map 휴게소·오피넷 주유소와 한국도로공사 0615/0502 실응답에서 가져왔다.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.dto.transport_state import FuelStationState, StateAddress, StateCoordinate
from kortravelmap.providers import kor_travel_transport as transport
from kortravelmap.providers.kor_travel_transport import (
    TransportRestArea,
    TransportRestAreaFood,
    TransportRestAreaFoodMenu,
)
from kortravelmap.providers.kor_travel_transport_state import (
    rest_area_food_state_item,
    rest_area_food_states,
    rest_area_state,
)
from kortravelmap.providers.krex import rest_areas_to_bundles
from kortravelmap.providers.rest_area_food import (
    STATION_PAIR_AUTO_CONFIDENCE,
    RestAreaPoint,
    StationPairCandidate,
    StationPoint,
    link_rest_areas,
    name_key,
    pair_station,
    pair_stations,
    summarize_menus,
    with_rest_area_links,
)

GOLDEN = Path(__file__).parent / "golden" / "kor-travel-transport" / "rest-area-food.json"


def _area(name: str) -> TransportRestArea:
    return TransportRestArea(
        natural_key=f"{name.lower()}::::", name=name, route_name=None, direction=None,
        lon=127.0, lat=37.0, phone_number=None, has_gas_station=True, has_lpg_station=None,
        has_ev_charger=None, raw={},
    )


def _food(
    code: str,
    name: str,
    *,
    cls: Any = "rest_area",
    direction: Any = "down",
    menus: tuple[TransportRestAreaFoodMenu, ...] = (),
) -> TransportRestAreaFood:
    return TransportRestAreaFood(
        std_rest_code=code, name=name, facility_class=cls, direction=direction,
        route_code="0010", route_name="경부선", menus=menus,
    )


def _menu(
    seq: str,
    name: str,
    price: int | None,
    *,
    best: bool = False,
    premium: bool = False,
    recommended: bool = False,
    season: Any = "all_year",
    updated: date | None = date(2026, 1, 9),
) -> TransportRestAreaFoodMenu:
    return TransportRestAreaFoodMenu(
        seq=seq, name=name, price=price, is_best=best, is_premium=premium,
        is_recommended=recommended, season=season, menu_updated_on=updated,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("칠서(양평)", ("칠서", "양평")),
        ("칠서휴게소(양평방향)", ("칠서", "양평")),
        ("칠서(양평)휴게소", ("칠서", "양평")),
        ("서울만남(부산)휴게소", ("서울만남", "부산")),
        ("덕평휴게소", ("덕평", None)),
        ("덕평", ("덕평", None)),
        ("문의청남대 (청주)", ("문의청남대", "청주")),
    ],
)
def test_name_key_reads_both_source_spellings(name: str, expected: tuple[str, str | None]) -> None:
    assert name_key(name) == expected


def test_golden_rest_area_food_parses() -> None:
    body = json.loads(GOLDEN.read_text("utf-8"))
    page = transport.parse_export_page(body, where="rest-area-food")
    foods = [transport.parse_rest_area_food(item) for item in page.items]
    assert [food.std_rest_code for food in foods] == ["000341", "000368"]
    assert foods[0].facility_class == "rest_area"
    assert foods[0].direction == "up"
    assert foods[0].menus[3].is_best is True
    assert foods[0].menus[0].menu_updated_on == date(2026, 1, 9)
    assert foods[1].facility_class == "gas_station"
    assert foods[1].menus == ()


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"menus": None}, "menus"),
        ({"facility_class": "toilet"}, "facility_class"),
        ({"direction": "left"}, "direction"),
        ({"std_rest_code": ""}, "std_rest_code"),
    ],
)
def test_rest_area_food_contract_is_strict(change: dict[str, Any], match: str) -> None:
    item = json.loads(GOLDEN.read_text("utf-8"))["items"][0]
    with pytest.raises(transport.TransportExportContractError, match=match):
        transport.parse_rest_area_food({**item, **change})


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"season": "spring"}, "season"),
        ({"price": "7000"}, "price"),
        ({"menu_updated_on": "x"}, "YYYY"),
    ],
)
def test_rest_area_food_menu_contract_is_strict(change: dict[str, Any], match: str) -> None:
    item = json.loads(GOLDEN.read_text("utf-8"))["items"][0]
    menu = {**item["menus"][0], **change}
    with pytest.raises(transport.TransportExportContractError, match=match):
        transport.parse_rest_area_food({**item, "menus": [menu]})


def test_link_by_normalized_name_and_skip_gas_stations() -> None:
    foods = [
        _food("000001", "서울만남(부산)휴게소"),
        _food("000002", "서울만남(부산)주유소", cls="gas_station"),
        _food("000341", "행담도휴게소", direction="up"),
    ]
    areas = [("a", "서울만남(부산)"), ("b", "행담도휴게소"), ("c", "없는(곳)")]
    links = link_rest_areas(areas, foods)
    assert links["a"].linked
    assert links["a"].food is not None
    assert links["a"].food.std_rest_code == "000001"
    assert links["a"].method == "name_exact"
    assert links["b"].food is not None
    assert links["b"].food.std_rest_code == "000341"
    assert not links["c"].linked
    assert links["c"].method == "no_match"


def test_a_menu_only_code_is_merged_into_the_single_classified_code() -> None:
    """2026-11-27 함양: 0615는 000551, 0502 메뉴는 000161에 있다."""
    foods = [
        _food("000551", "함양(대전)휴게소"),
        _food(
            "000161", "함양(대전)휴게소", cls=None, direction=None,
            menus=(_menu("1", "국밥", 9000), _menu("2", "국밥", 9000)),
        ),
    ]
    link = link_rest_areas([("h", "함양(대전)")], foods)["h"]
    assert link.linked
    assert link.method == "name_merged"
    assert link.confidence == 0.95
    assert link.food is not None
    assert link.food.std_rest_code == "000551"
    assert [menu.name for menu in link.food.menus] == ["국밥"]
    assert link.candidates == ("000161", "000551")


def test_ambiguous_names_and_shared_codes_are_not_linked() -> None:
    foods = [_food("000010", "죽전(서울)휴게소"), _food("000011", "죽전(서울)휴게소")]
    assert link_rest_areas([("a", "죽전(서울)")], foods)["a"].method == "ambiguous"
    shared = link_rest_areas(
        [("a", "죽전(서울)"), ("b", "죽전휴게소(서울방향)")], [_food("000010", "죽전(서울)휴게소")]
    )
    assert {link.method for link in shared.values()} == {"shared_code"}
    assert not any(link.linked for link in shared.values())


def test_with_rest_area_links_keeps_the_natural_key() -> None:
    area = _area("서울만남(부산)")
    [linked] = with_rest_area_links([area], [_food("000001", "서울만남(부산)휴게소")])
    assert linked.natural_key == area.natural_key
    assert (linked.route_name, linked.direction) == (None, None)
    assert linked.ex_std_rest_code == "000001"
    assert (linked.ex_route_name, linked.ex_direction_code) == ("경부선", "down")


def test_summarize_menus_is_deterministic() -> None:
    menus = (
        _menu("1", "우동", 7000),
        _menu("2", "소떡소떡", 4500, best=True),
        _menu("3", "한우국밥", 13000, premium=True),
        _menu("4", "돈까스", 9500, recommended=True, best=True),
        _menu("5", "냉면", 9000, season="summer", updated=date(2026, 6, 1)),
        _menu("6", "어묵탕", 6000, season="winter"),
        _menu("7", "시가", None),
        _menu("8", "물", 0),
    )
    summary = summarize_menus(menus)
    assert summary == summarize_menus(tuple(reversed(menus)))
    assert summary.menu_count == 8
    # 0원 행은 대표에 넣지 않는다.
    zero = summarize_menus((_menu("9", "자율식당", 0, best=True), _menu("1", "우동", 7000)))
    assert zero.featured == ()
    assert zero.menu_count == 2
    assert (summary.price_min, summary.price_median, summary.price_max) == (4500, 7000, 13000)
    assert [item.name for item in summary.featured] == ["소떡소떡", "돈까스", "한우국밥"]
    assert summary.featured[1].tags == ("best", "recommended")
    assert [(item.name, item.season) for item in summary.seasonal] == [
        ("냉면", "summer"), ("어묵탕", "winter"),
    ]
    assert summary.menu_updated_on == date(2026, 6, 1)
    empty = summarize_menus(())
    assert (empty.price_min, empty.price_median, empty.featured) == (None, None, ())


def _candidate(key: str, name: str, distance: float, direction: Any = None) -> StationPairCandidate:
    return StationPairCandidate(
        key=key, rest_area_name=name, direction_code=direction, distance_m=distance
    )


@pytest.mark.parametrize(
    ("station", "candidates", "expected_key", "method"),
    [
        # 행선지가 이름에 있다("<이름>주유소(<행선지>방향)", "<이름>(<행선지>)주유소").
        (
            "서부산주유소(순천방향)",
            [_candidate("x", "서부산휴게소(순천방향)", 55)],
            "x",
            "name_direction",
        ),
        (
            "(주)한라석유 논공(광주)주유소",
            [
                _candidate("g", "논공휴게소(광주방향)", 64),
                _candidate("d", "논공휴게소(대구방향)", 213),
            ],
            "g",
            "name_direction",
        ),
        # 이름이 거리보다 앞선다(원천 좌표가 상하행이 바뀐 사례).
        (
            "에스제이오일(주) 밀양(함양방향)주유소",
            [
                _candidate("u", "밀양영남루휴게소(울산방향)", 92),
                _candidate("h", "밀양영남루휴게소(함양방향)", 271),
            ],
            "h",
            "name_direction",
        ),
        # (상)/(하)는 한국도로공사 상하행과 같고 그 후보가 더 가까울 때만 자동이다.
        (
            "YM21유통 사천(하)주유소/충전소",
            [
                _candidate("down", "사천휴게소(부산방향)", 14, "down"),
                _candidate("up", "사천휴게소(순천방향)", 268, "up"),
            ],
            "down",
            "name_updown_nearest",
        ),
        # 이름 바로 뒤의 행선지("홍천서울").
        (
            "키다리식품(주)홍천서울주유소/충전소",
            [
                _candidate("s", "홍천휴게소(서울방향)", 100),
                _candidate("y", "홍천휴게소(양양방향)", 255),
            ],
            "s",
            "name_direction",
        ),
        # 양방향 휴게소.
        (
            "(주)고삼하이파크 고삼(세종)주유소",
            [_candidate("b", "고삼호수휴게소", 203)],
            "b",
            "name_bidirectional",
        ),
    ],
)
def test_pair_station_automatic_cases(
    station: str, candidates: list[StationPairCandidate], expected_key: str, method: str
) -> None:
    pair = pair_station(station, candidates)
    assert pair is not None
    assert (pair.key, pair.method) == (expected_key, method)
    assert pair.confidence >= STATION_PAIR_AUTO_CONFIDENCE
    assert pair.automatic


@pytest.mark.parametrize(
    ("station", "candidates", "method"),
    [
        # 휴게소 이름이 없는 동네 주유소.
        ("상서현대셀프", [_candidate("s", "신탄진휴게소(서울방향)", 192)], "distance_only"),
        # 휴게소는 맞는데 행선지 표기가 달라(마산 ↔ 창원·양평) 방향을 모른다.
        (
            "괴산(마산)주유소/충전소",
            [
                _candidate("c", "괴산휴게소(창원방향)", 132),
                _candidate("y", "괴산휴게소(양평방향)", 218),
            ],
            "name_conflict",
        ),
        # 2026-11-27 중부내륙선: 오피넷 (하)가 KREX 상행 쪽 — (상)/(하) 기준이 노선마다 다르다.
        # 이름이 가리키는 방향 후보가 더 멀면 자동으로 보지 않는다.
        (
            "(주)서원문경(하)주유소/충전소",
            [
                _candidate("c", "문경휴게소(창원방향)", 61, "up"),
                _candidate("y", "문경휴게소(양평방향)", 196, "down"),
            ],
            "name_conflict",
        ),
        # 이름의 행선지가 하나뿐인 후보와 어긋난다.
        ("오창(통영)주유소", [_candidate("o", "오창휴게소(남이방향)", 86)], "name_conflict"),
        # 행선지가 회사명 속에 든 것은 행선지가 아니다(부분 문자열 금지).
        (
            "부산에너지 서부산주유소",
            [
                _candidate("a", "서부산휴게소(순천방향)", 60),
                _candidate("b", "서부산휴게소(부산방향)", 70),
            ],
            "name_only",
        ),
    ],
)
def test_pair_station_review_cases(
    station: str, candidates: list[StationPairCandidate], method: str
) -> None:
    pair = pair_station(station, candidates)
    assert pair is not None
    assert pair.method == method
    assert not pair.automatic


def test_pair_station_single_named_candidate_empty_and_blank_name() -> None:
    pair = pair_station("경산I.C주유소", [_candidate("o", "경산휴게소(서울방향)", 289)])
    assert pair is not None
    assert pair.method == "name_single"
    assert pair.automatic  # 혼자 보면 자동 — 일대일 다듬기(pair_stations)가 내린다.
    assert pair_station("아무주유소", []) is None
    # 휴게소 이름이 비면 이름 근거가 없다(빈 문자열은 어디에나 들어 있다).
    blank = pair_station("아무주유소(양방향)", [_candidate("z", "휴게소", 50)])
    assert blank is not None
    assert blank.method == "distance_only"


def test_pair_stations_keeps_only_the_strongest_pair_per_rest_area() -> None:
    """2026-11-27 운영 오짝: 휴게소 지명이 든 근처 일반 주유소가 약한 근거로 붙었다."""
    areas = [
        RestAreaPoint("gs-up", "경산휴게소(서울방향)", "up", 128.7400, 35.8200),
        RestAreaPoint("gs-down", "경산휴게소(부산방향)", "down", 128.7440, 35.8200),
    ]
    stations = [
        StationPoint("s1", "(주)나이스디앤에스 경산(서울방향)주유소/충전", 128.7402, 35.8210),
        StationPoint("s2", "경산I.C주유소", 128.7380, 35.8225),
        StationPoint("s3", "아무주유소", 128.9, 35.9),
    ]
    pairs = pair_stations(stations, areas)
    assert set(pairs) == {"s1", "s2"}
    assert (pairs["s1"].key, pairs["s1"].automatic) == ("gs-up", True)
    assert pairs["s2"].key == "gs-up"
    assert pairs["s2"].method == "name_single_weaker"
    assert not pairs["s2"].automatic


def test_pair_stations_keeps_two_same_evidence_stations_on_a_bidirectional_rest_area() -> None:
    areas = [RestAreaPoint("an", "안산휴게소", None, 126.8, 37.3)]
    stations = [
        StationPoint("k", "안산주유소(강릉방향)", 126.8010, 37.3005),
        StationPoint("i", "안산주유소(인천방향)", 126.7990, 37.2995),
    ]
    pairs = pair_stations(stations, areas)
    assert {key: pair.automatic for key, pair in pairs.items()} == {"k": True, "i": True}


def test_rest_area_food_states_link_and_summarize() -> None:
    collected = datetime(2026, 11, 27, 18, 50, tzinfo=UTC)
    areas = [_area("서울만남(부산)"), _area("없는(곳)")]
    menus = (_menu("2", "소떡소떡", 4500, best=True),)
    foods = [_food("000001", "서울만남(부산)휴게소", menus=menus)]
    [state] = rest_area_food_states(areas, foods, collected_at=collected)
    assert state.feature_id == rest_area_state(areas[0]).feature_id
    assert state.rest_area_name == "서울만남휴게소(부산방향)"
    assert state.std_rest_code == "000001"
    assert state.direction_code == "down"
    assert state.featured[0].name == "소떡소떡"
    assert state.featured[0].tags == ["best"]
    assert state.source_collected_at == collected
    assert state.attribution == "한국도로공사"
    assert state.stations == []


def test_rest_area_food_state_item_looks_up_only_automatic_stations() -> None:
    collected = datetime(2026, 11, 27, 18, 50, tzinfo=UTC)
    area = _area("서울만남(부산)")
    foods = [_food("000001", "서울만남(부산)휴게소", menus=(_menu("1", "우동", 7000),))]
    near = [
        FuelStationState(
            feature_id=key, category="06010101", marker_icon="fuel", marker_color="P-08",
            name=name, natural_key=key, coord=StateCoordinate(lon=lon, lat=37.0),
            address=StateAddress(), prices=[], source_last_seen_at=collected,
        )
        for key, name, lon in (
            ("auto", "서울만남(부산)주유소", 127.0005),
            ("review", "근처셀프주유소", 127.001),
            ("far", "서울만남(부산)주유소", 127.2),
        )
    ]
    [state] = rest_area_food_states([area], foods, near, collected_at=collected)
    assert [(s.feature_id, s.automatic) for s in state.stations] == [
        ("auto", True), ("review", False),
    ]
    item = rest_area_food_state_item(state)
    assert item.lookup_keys == ("auto",)


async def test_pg_rest_area_feature_carries_the_link_and_fills_route_direction() -> None:
    area = _area("서울만남(부산)")
    [linked] = with_rest_area_links([area], [_food("000001", "서울만남(부산)휴게소")])
    fetched = datetime(2026, 11, 27, tzinfo=UTC)
    [bundle] = await rest_areas_to_bundles([linked], fetched_at=fetched)
    assert bundle.feature.detail is not None
    info = bundle.feature.detail.facility_info
    assert info["highway_name"] == "경부선"
    assert info["direction"] == "부산방향"
    assert info["ex_link"] == {
        "std_rest_code": "000001", "route_code": "0010", "route_name": "경부선",
        "direction_code": "down", "method": "name_exact", "confidence": 1.0,
    }
    assert bundle.source_record.raw_data["ex_link"]["std_rest_code"] == "000001"
    # 연결이 없으면 ex_link가 없고, 행선지는 원천 이름에서 채운다.
    [plain] = await rest_areas_to_bundles([area], fetched_at=fetched)
    assert plain.feature.detail is not None
    assert "ex_link" not in plain.feature.detail.facility_info
    assert plain.feature.detail.facility_info["direction"] == "부산방향"
    assert plain.feature.feature_id == bundle.feature.feature_id
