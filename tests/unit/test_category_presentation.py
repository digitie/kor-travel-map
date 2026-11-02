"""분류 체계에서 유도한 검색 순위 그룹·공개 표시 이름 규칙.

대상: ``kortravelmap.category._presentation``.
"""

from __future__ import annotations

import pytest

from kortravelmap.category import (
    PLACE_CATEGORY_CODES,
    PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1,
    PLACE_CATEGORY_SEARCH_GROUP_FALLBACK,
    PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES,
    PLACE_CATEGORY_TIER2_NAMES_BY_TIER1,
    PlaceCategoryCode,
    PlaceCategoryTier1Code,
    category_search_group,
    get_category,
    is_parking_category_code,
    is_tier1_only_category_code,
    public_feature_display_name,
)

pytestmark = pytest.mark.unit


def test_every_tier1_code_has_a_search_group() -> None:
    assert set(PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1) == {
        code.value for code in PlaceCategoryTier1Code
    }
    highest = max(PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.values())
    assert highest == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK


def test_search_groups_order_tourism_then_lodging_then_food_then_the_rest() -> None:
    """소유자 결정(2026-11-02): 관광(국가유산·문화 포함) > 숙박 > 식음 > 주차·편의.

    교통 가운데 이름으로 찾아가는 목적지(기차역·지하철역·휴게소·공항)만 숙박과 같은 그룹이다 —
    "서울역"이 "…서울역점" 음식점보다 뒤로 밀리지 않게(적대 리뷰 2026-11-02). 버스 정류장·택시·
    주차·주유·의료는 맨 뒤 그대로다(소유자 순서를 넘어 넓히지 않는다).
    """

    def group(code: PlaceCategoryCode) -> int:
        return category_search_group(code.value)

    heritage = group(PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE)
    culture = group(PlaceCategoryCode.TOURISM_CULTURAL_FACILITY)
    lodging = group(PlaceCategoryCode.LODGING_HOTEL)
    spa = group(PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING)
    food = group(PlaceCategoryCode.FOOD_RESTAURANT_KOREAN)
    parking = group(PlaceCategoryCode.TRANSPORT_PARKING)
    fuel = group(PlaceCategoryCode.TRANSPORT_FUEL)
    convenience = group(PlaceCategoryCode.CONVENIENCE_STORE)
    assert heritage == culture < lodging == spa < food < parking == fuel == convenience
    for destination in (
        PlaceCategoryCode.TRANSPORT_STOP_TRAIN,
        PlaceCategoryCode.TRANSPORT_STOP_SUBWAY,
        PlaceCategoryCode.TRANSPORT_REST_AREA,
        PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY_EX,
        PlaceCategoryCode.TRANSPORT_AIRPORT,
    ):
        assert group(destination) == lodging, destination
    for rest in (
        PlaceCategoryCode.TRANSPORT_STOP,
        PlaceCategoryCode.TRANSPORT_STOP_BUS,
        PlaceCategoryCode.TRANSPORT_STOP_TAXI,
        PlaceCategoryCode.MEDICAL_HOSPITAL_GENERAL,
    ):
        assert group(rest) == parking, rest
    # 접두 예외 표의 키는 카탈로그 코드의 교통 접두(4·6자리)다.
    for prefix in PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES:
        assert len(prefix) in (4, 6)
        assert prefix.ljust(8, "0") in PLACE_CATEGORY_CODES
        assert prefix.startswith(PlaceCategoryTier1Code.TRANSPORT.value)
    # 카탈로그 밖 코드(notice의 99000000)와 None은 맨 뒤 그룹이다.
    assert category_search_group("99000000") == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    assert category_search_group(None) == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK


def test_tier1_only_codes_match_catalog_depth_one() -> None:
    """``XX000000`` 판정이 카탈로그의 depth ≤ 1과 정확히 같다(분류 체계가 정본).

    depth 0은 sentinel ``00000000``(미분류) 하나다 — 그것도 하위 분류가 없는 코드다.
    """

    for code in PLACE_CATEGORY_CODES:
        expected = get_category(code).depth <= 1
        assert is_tier1_only_category_code(code) is expected, code
    assert get_category(PlaceCategoryCode.UNCLASSIFIED.value).depth == 0
    assert not is_tier1_only_category_code(None)
    assert not is_tier1_only_category_code("01")


def test_parking_codes_are_the_parking_subtree() -> None:
    parking_codes = {
        code for code in PLACE_CATEGORY_CODES if is_parking_category_code(code)
    }
    assert PlaceCategoryCode.TRANSPORT_PARKING.value in parking_codes
    for code in parking_codes:
        category = get_category(code)
        assert category.tier1_code == "06"
        assert category.tier2_name == PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["06"]["01"]
    assert not is_parking_category_code(PlaceCategoryCode.TRANSPORT_FUEL.value)
    assert not is_parking_category_code(None)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("도산서원", "도산서원 주차장"),
        ("고씨굴", "고씨굴 주차장"),
        ("고씨굴(강변)", "고씨굴(강변) 주차장"),
        ("하회마을관광지", "하회마을관광지 주차장"),
        (" 와부 제5공영 ", "와부 제5공영 주차장"),
        # 이미 주차 시설임을 말하는 이름은 그대로다.
        ("소수서원 주차장", "소수서원 주차장"),
        ("부석사 공영주차장", "부석사 공영주차장"),
        ("시청 주차타워", "시청 주차타워"),
        ("", ""),
    ],
)
def test_parking_display_name_appends_label_when_missing(name: str, expected: str) -> None:
    assert public_feature_display_name(name, PlaceCategoryCode.TRANSPORT_PARKING.value) == expected


def test_display_name_is_idempotent_and_leaves_other_categories_alone() -> None:
    parking = PlaceCategoryCode.TRANSPORT_PARKING.value
    once = public_feature_display_name("도산서원", parking)
    assert public_feature_display_name(once, parking) == once
    for code in (
        PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE.value,
        PlaceCategoryCode.TRANSPORT_FUEL.value,
        PlaceCategoryCode.FOOD_RESTAURANT_KOREAN.value,
        "99000000",
        None,
    ):
        assert public_feature_display_name("도산서원", code) == "도산서원"
