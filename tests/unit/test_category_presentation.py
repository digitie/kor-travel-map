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
    SEARCH_DESTINATION_GROUP_MAX,
    SEARCH_NAME_SUFFIX_GROUPS,
    SEARCH_NAME_SUFFIX_PATTERNS,
    SEARCH_NAMED_DESTINATION_EXACT_GROUP,
    PlaceCategoryCode,
    PlaceCategoryTier1Code,
    category_search_group,
    destination_exact_search_group,
    get_category,
    is_parking_category_code,
    is_tier1_only_category_code,
    public_feature_display_name,
    search_effective_group,
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
        PlaceCategoryCode.TRANSPORT_FERRY_TERMINAL,
        PlaceCategoryCode.CONVENIENCE_TRADITIONAL_MARKET,
    ):
        assert group(destination) == lodging, destination
        # 이름이 검색어와 같으면 분류 그룹보다 앞서는 목적지 그룹이다(ADR-120).
        assert group(destination) <= SEARCH_DESTINATION_GROUP_MAX, destination
    assert heritage <= SEARCH_DESTINATION_GROUP_MAX < food
    for rest in (
        PlaceCategoryCode.TRANSPORT_STOP,
        PlaceCategoryCode.TRANSPORT_STOP_BUS,
        PlaceCategoryCode.TRANSPORT_STOP_TAXI,
        PlaceCategoryCode.MEDICAL_HOSPITAL_GENERAL,
    ):
        assert group(rest) == parking, rest
    # 접두 예외 표의 키는 카탈로그 코드의 교통 접두와 전통시장 접두(4·6·8자리 — SQL 빌더가 받는
    # 길이)다.
    market_prefix = PlaceCategoryCode.CONVENIENCE_TRADITIONAL_MARKET.value[:4]
    for prefix in PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES:
        assert len(prefix) in (4, 6, 8)
        assert prefix.ljust(8, "0") in PLACE_CATEGORY_CODES
        assert prefix.startswith(PlaceCategoryTier1Code.TRANSPORT.value) or prefix == market_prefix
    # 카탈로그 밖 코드(notice의 99000000)와 None은 맨 뒤 그룹이다.
    assert category_search_group("99000000") == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    assert category_search_group(None) == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK


def test_named_destination_exact_match_joins_the_tourism_group() -> None:
    """이름이 검색어와 같은 고유 이름 목적지(역·휴게소·공항·여객선터미널·전통시장)는 관광과 같은
    그룹이다(2026-11-10 운영 점검). 숙박·식음·주차는 이름이 같아도 제 그룹 그대로다."""

    tourism = category_search_group(PlaceCategoryCode.TOURISM.value)
    assert tourism == SEARCH_NAMED_DESTINATION_EXACT_GROUP
    for named in (
        PlaceCategoryCode.TRANSPORT_STOP_TRAIN,
        PlaceCategoryCode.TRANSPORT_STOP_SUBWAY,
        PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY_EX,
        PlaceCategoryCode.TRANSPORT_AIRPORT,
        PlaceCategoryCode.TRANSPORT_FERRY_TERMINAL,
        PlaceCategoryCode.CONVENIENCE_TRADITIONAL_MARKET,
    ):
        assert destination_exact_search_group(named.value) == tourism, named
    for other in (
        PlaceCategoryCode.TOURISM,
        PlaceCategoryCode.LODGING_HOTEL,
        PlaceCategoryCode.FOOD_RESTAURANT_KOREAN,
        PlaceCategoryCode.TRANSPORT_PARKING,
        PlaceCategoryCode.CONVENIENCE_MART,
    ):
        assert destination_exact_search_group(other.value) == category_search_group(
            other.value
        ), other
    assert destination_exact_search_group(None) == PLACE_CATEGORY_SEARCH_GROUP_FALLBACK


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
        ("\u3000", "\u3000"),
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


@pytest.mark.parametrize(
    ("code", "name", "expected"),
    [
        # prod 2026-11-11 실측 — MCST가 관광으로 넣은 숙박·식당·지점.
        ("01000000", "저어새펜션", 1),
        ("01080400", "신선지어깨동무펜션", 1),
        ("01000000", "씨마크 호텔", 1),
        # 끝말만 본다 — 이름 가운데의 "호텔"은 그대로 관광이다.
        ("01000000", "롯데호텔 서울", 0),
        ("01000000", "강화 펜션 (강화)", 1),
        ("01000000", "호야막창", 2),
        ("01000000", "남대문시장 전주식당", 2),
        ("01000000", "을왕리빵판다카페", 2),
        ("01000000", "만석닭강정 중앙시장점", 3),
        ("01040000", "롯데마트 김포공항점", 3),
        ("00000000", "하늘 민박", 1),
        # 관광지 이름 — 그대로 관광.
        ("01000000", "춘천 명동 닭갈비 골목", 0),
        ("01000000", "안목해변 커피거리", 0),
        ("01070300", "경복궁", 0),
        ("01000000", "올레 1코스 시작점", 0),
        ("01000000", "펜션밴드", 0),
        # 관광·미분류가 아닌 저장 분류는 그대로다(이름이 무엇이든).
        ("02010100", "호미곶 펜션", 2),
        ("03050200", "호미곶민박", 1),
        ("06050000", "양양국제공항호텔", 1),
        ("05070000", "자갈치 회센터 본점", 1),  # 전통시장(고유 이름 목적지) 그룹 그대로
        (None, "저어새펜션", PLACE_CATEGORY_SEARCH_GROUP_FALLBACK),
    ],
)
def test_search_effective_group_reads_lodging_food_branch_suffixes(
    code: str | None, name: str, expected: int
) -> None:
    assert search_effective_group(code, name) == expected


def test_search_effective_group_without_a_name_is_the_category_group() -> None:
    for code in ("01000000", "00000000", "03010000"):
        assert search_effective_group(code, None) == category_search_group(code)


def test_search_name_suffix_groups_are_known_groups_and_patterns_derive_from_them() -> None:
    groups = set(PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.values())
    assert set(SEARCH_NAME_SUFFIX_GROUPS) <= groups
    assert set(SEARCH_NAME_SUFFIX_PATTERNS) == set(SEARCH_NAME_SUFFIX_GROUPS)
    for group, suffixes in SEARCH_NAME_SUFFIX_GROUPS.items():
        for suffix in suffixes:
            assert suffix in SEARCH_NAME_SUFFIX_PATTERNS[group]
