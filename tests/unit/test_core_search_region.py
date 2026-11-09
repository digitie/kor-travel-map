"""``kortravelmap.core.search_region`` — 검색어 지역 토큰 해석(#1459 §7).

표본은 prod 2026-11-09 실측 형태다(시군구 이름 "수원시 장안구", 2026 ``전남광주통합특별시`` 12xxx가
옛 광주광역시 29xxx와 함께 있다).
"""

from __future__ import annotations

import pytest

from kortravelmap.core.search_region import (
    SUBAREA_ALIASES,
    SearchRegionEntry,
    build_region_token_index,
    search_keyword_category_codes,
    split_region_query,
)

pytestmark = pytest.mark.unit

_E = SearchRegionEntry
_ENTRIES = (
    _E("51150", "강원특별자치도", "강릉시"),
    _E("51110", "강원특별자치도", "춘천시"),
    _E("51820", "강원특별자치도", "고성군"),
    _E("48820", "경상남도", "고성군"),
    _E("50110", "제주특별자치도", "제주시"),
    _E("50130", "제주특별자치도", "서귀포시"),
    _E("41111", "경기도", "수원시 장안구"),
    _E("41113", "경기도", "수원시 권선구"),
    _E("41590", "경기도", "화성시"),
    _E("41610", "경기도", "광주시"),
    _E("26350", "부산광역시", "해운대구"),
    _E("26500", "부산광역시", "수영구"),
    _E("26110", "부산광역시", "중구"),
    _E("11140", "서울특별시", "중구"),
    _E("27110", "대구광역시", "중구"),
    _E("29110", "광주광역시", "동구"),
    _E("12210", "전남광주통합특별시", "동구"),
    _E("47130", "경상북도", "경주시"),
)


@pytest.fixture(scope="module")
def index() -> dict[str, frozenset[str]]:
    return build_region_token_index(_ENTRIES)


@pytest.mark.parametrize(
    ("q", "label", "codes", "remainder"),
    [
        ("강릉 호텔", "강릉", ("51150",), "호텔"),
        ("춘천 닭갈비", "춘천", ("51110",), "닭갈비"),
        ("애월 카페", "애월", ("50110",), "카페"),
        ("우도 천진항", "우도", ("50110",), "천진항"),
        ("광안리 맛집", "광안리", ("26500",), "맛집"),
        ("부산 해운대 호텔", "부산 해운대", ("26350",), "호텔"),
        ("강원 고성 맛집", "강원 고성", ("51820",), "맛집"),
        ("제주 서귀포 펜션", "제주 서귀포", ("50130",), "펜션"),
        ("수원 호텔", "수원", ("41111", "41113"), "호텔"),
        # 뒤쪽 지역 토큰.
        ("신라호텔 서울", "서울", ("11140",), "신라호텔"),
        # 첫 지역 토큰과 교집합이 없는 지역 이름(화성시)은 나머지 검색어로 남는다.
        ("수원 화성", "수원", ("41111", "41113"), "화성"),
        # 시도와 시군구 이름이 겹치면 모두(광주광역시·전남광주통합특별시·경기 광주시).
        ("광주 송정역", "광주", ("12210", "29110", "41610"), "송정역"),
        ("고성 천진항", "고성", ("48820", "51820"), "천진항"),
        ("경주  한옥", "경주", ("47130",), "한옥"),
    ],
)
def test_split_region_query(
    index: dict[str, frozenset[str]],
    q: str,
    label: str,
    codes: tuple[str, ...],
    remainder: str,
) -> None:
    region = split_region_query(q, index)
    assert region is not None
    assert (region.region_label, region.sigungu_codes, region.remainder) == (
        label,
        codes,
        remainder,
    )


@pytest.mark.parametrize(
    "q",
    [
        "강릉",  # 나머지가 없다 — 이름 검색 그대로.
        "춘천닭갈비",  # 낱말 하나.
        "팔공산",
        "남산 둘레길",  # 지역 토큰 없음.
        "지리산 천왕봉",
        "",
    ],
)
def test_split_region_query_leaves_non_region_queries_alone(
    index: dict[str, frozenset[str]],
    q: str,
) -> None:
    assert split_region_query(q, index) is None


def test_empty_index_never_resolves() -> None:
    assert split_region_query("강릉 호텔", {}) is None


def test_suffix_strip_keeps_single_syllable_gu_names(index: dict[str, frozenset[str]]) -> None:
    # "중구" → "중"으로 떼지 않는다(한 글자 토큰은 거의 모든 검색어와 부딪힌다).
    assert "중" not in index
    assert index["중구"] == frozenset({"11140", "26110", "27110"})


def test_majority_sample_names_win_over_one_bad_row() -> None:
    entries = [
        _E("51150", "강원특별자치도", "강릉시"),
        _E("51150", "강원특별자치도", "강릉시"),
        _E("51150", "경기도", "동해시"),  # 주소 오류 한 행
    ]
    index = build_region_token_index(entries)
    assert index["강릉"] == frozenset({"51150"})
    assert "동해" not in index


def test_invalid_codes_are_ignored() -> None:
    index = build_region_token_index([_E("5115", "강원특별자치도", "강릉시")])
    assert index == {}


def test_subarea_aliases_resolve_only_when_both_tokens_exist(
    index: dict[str, frozenset[str]],
) -> None:
    assert index["애월"] == frozenset({"50110"})
    assert index["광안리"] == frozenset({"26500"})
    # 표본에 없는 시군구(평창군)를 가리키는 하위 지역은 색인에 없다.
    assert SUBAREA_ALIASES["대관령"][1] == "평창군"
    assert "대관령" not in index


@pytest.mark.parametrize(
    ("keyword", "expected_member", "unexpected_member"),
    [
        ("호텔", "03010100", "02020000"),
        ("카페", "02020102", "03010000"),
        ("펜션", "03050300", "03010000"),
        ("캠핑", "03060201", "03050000"),  # 앞부분 일치 — 캠핑장
        ("캠핑장", "03060000", "03050000"),
        ("게스트하우스", "03070200", "03050000"),
        ("한옥", "03070200", "03050000"),  # 한옥체험업·한옥호텔·한옥·민속마을
        ("해변", "01050100", "01020300"),  # 동의어 → 해수욕장
        ("맛집", "02010100", "02020000"),  # 동의어 → 음식점
        ("숙박", "03080200", "02010000"),  # Tier 1
    ],
)
def test_keyword_category_codes(
    keyword: str,
    expected_member: str,
    unexpected_member: str,
) -> None:
    codes = search_keyword_category_codes(keyword)
    assert expected_member in codes
    assert unexpected_member not in codes
    assert list(codes) == sorted(codes)


@pytest.mark.parametrize("keyword", ["닭갈비", "막창", "천진항", "역", "", "신라 호텔", "미분류"])
def test_keyword_without_category(keyword: str) -> None:
    assert search_keyword_category_codes(keyword) == ()


def test_region_search_carries_category_codes(index: dict[str, frozenset[str]]) -> None:
    region = split_region_query("강릉 호텔", index)
    assert region is not None
    assert region.category_codes == search_keyword_category_codes("호텔")
    region = split_region_query("춘천 닭갈비", index)
    assert region is not None
    assert region.category_codes == ()
