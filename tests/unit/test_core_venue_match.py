"""``kortravelmap.core.venue_match`` — 행사 장소 이름 → 좌표 있는 장소 Feature(#1468 D).

prod 2026-11-10 국가유산 행사 장소 문자열과 후보 표기(시도 통합·시군구 하위 구)를 그대로 쓴다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from kortravelmap.core.venue_match import (
    VenueCandidate,
    match_venue,
    same_region,
    sido_family,
    sigungu_root,
    split_venue_names,
    venue_name_key,
)
from kortravelmap.dto import Coordinate

_HERITAGE = "krheritage_heritage_features"


def _cand(
    name: str,
    *,
    sido: str = "경상남도",
    sigungu: str = "진주시",
    lon: str = "128.0817",
    lat: str = "35.1887",
    fid: str = "00000000-0000-7000-8000-000000000001",
    dataset: str | None = _HERITAGE,
) -> VenueCandidate:
    return VenueCandidate(
        feature_id=fid,
        name=name,
        coord=Coordinate(lon=Decimal(lon), lat=Decimal(lat)),
        sido_name=sido,
        sigungu_name=sigungu,
        dataset_key=dataset,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("진주성 일원 및 지역상권", ["진주성"]),
        ("밀양향교, 영남루", ["밀양향교", "영남루"]),
        ("강원감영(공방고지)", ["강원감영"]),
        ("파주 혜음원지(사적)", ["파주 혜음원지"]),
        (
            "군산 동국사 백주년 기념관 또는 군산 근대 교육관",
            ["군산 동국사 백주년 기념관", "군산 근대 교육관"],
        ),
        # 일반 시설 낱말만 남은 조각("기념관", "행사장")은 이름이 아니다.
        ("서울 효창공원, 백범김구\n기념관", ["서울 효창공원", "백범김구"]),
        ("행사장 내", []),
        # 한 글자 수식어는 띄어 쓴 것만 뗀다 — 이름 끝 글자를 먹지 않는다.
        ("광한루 앞", ["광한루"]),
        ("청계천변 성내", ["청계천변 성내"]),
        ("앞", []),
        (None, []),
    ],
)
def test_split_venue_names(raw: str | None, expected: list[str]) -> None:
    assert split_venue_names(raw) == expected


@pytest.mark.parametrize(
    ("value", "family"),
    [
        ("전라남도", "전남"),
        ("광주광역시", "전남"),
        ("전남광주통합특별시", "전남"),
        ("전북특별자치도", "전북"),
        ("전라북도", "전북"),
        ("강원특별자치도", "강원"),
        ("강원도", "강원"),
        ("경상남도", "경남"),
        ("세종특별자치시", "세종"),
        ("", None),
    ],
)
def test_sido_family(value: str, family: str | None) -> None:
    assert sido_family(value) == family


@pytest.mark.parametrize(
    ("value", "root"),
    [
        ("고양시", "고양"),
        ("고양시 덕양구", "고양"),
        ("용인특례시", "용인"),
        ("중구", "중구"),
        ("-", None),
        (None, None),
    ],
)
def test_sigungu_root(value: str | None, root: str | None) -> None:
    assert sigungu_root(value) == root


def test_region_matches_merged_sido_and_sub_district() -> None:
    assert same_region(
        _cand("x", sido="전남광주통합특별시", sigungu="광산구"), "광주광역시", "광산구"
    )
    assert same_region(_cand("x", sido="경기도", sigungu="고양시 덕양구"), "경기도", "고양시")
    assert not same_region(_cand("x", sido="경상북도", sigungu="안동시"), "경상남도", "밀양시")
    # 세종은 시군구가 "-"로 온다 — 시도만 본다.
    assert same_region(_cand("x", sido="세종특별자치시", sigungu=None), "세종특별자치시", "-")


def test_exact_name_in_same_region_matches() -> None:
    match = match_venue("진주성", "경상남도", "진주시", [_cand("진주성")])
    assert match is not None
    assert match.coord == Coordinate(lon=Decimal("128.0817"), lat=Decimal("35.1887"))


def test_leading_region_word_is_ignored_on_either_side() -> None:
    cand = _cand("고양 행주산성", sido="경기도", sigungu="고양시 덕양구")
    assert match_venue("행주산성", "경기도", "고양시", [cand]) is not None
    cand2 = _cand("행주산성", sido="경기도", sigungu="고양시 덕양구")
    assert match_venue("고양 행주산성", "경기도", "고양시", [cand2]) is not None


def test_prefix_or_contains_is_not_a_match() -> None:
    """"정선향교"가 "정선향교 앞 공영주차장"을 가리키면 안 된다."""
    cand = _cand("정선향교 앞 공영주차장", sido="강원특별자치도", sigungu="정선군")
    assert match_venue("정선향교", "강원도", "정선군", [cand]) is None


def test_same_name_in_other_region_is_not_a_match() -> None:
    cand = _cand("도산서원", sido="경상북도", sigungu="안동시")
    assert match_venue("도산서원", "경상남도", "밀양시", [cand]) is None


def test_scattered_same_name_candidates_are_ambiguous() -> None:
    near = _cand("선유도", sido="전북특별자치도", sigungu="군산시", lon="126.40", lat="35.81")
    far = _cand(
        "선유도", sido="전북특별자치도", sigungu="군산시", lon="126.50", lat="35.90",
        fid="00000000-0000-7000-8000-000000000002",
    )
    assert match_venue("선유도", "전라북도", "군산시", [near, far]) is None


def test_close_candidates_prefer_heritage_then_feature_id() -> None:
    museum = _cand("진주성", dataset="datagokr_tourist_attractions",
                   fid="00000000-0000-7000-8000-000000000000", lon="128.0820")
    heritage = _cand("진주성", fid="00000000-0000-7000-8000-000000000009")
    match = match_venue("진주성", "경상남도", "진주시", [museum, heritage],
                        prefer_dataset_key=_HERITAGE)
    assert match is not None
    assert match.feature_id == "00000000-0000-7000-8000-000000000009"
    no_pref = match_venue("진주성", "경상남도", "진주시", [heritage, museum])
    assert no_pref is not None
    assert no_pref.feature_id == "00000000-0000-7000-8000-000000000000"


def test_venue_name_key_keeps_only_letters_and_digits() -> None:
    assert venue_name_key("수덕사 근역성보관") == venue_name_key("수덕사근역성보관")
    assert venue_name_key(" (사)·- ") == "사"
