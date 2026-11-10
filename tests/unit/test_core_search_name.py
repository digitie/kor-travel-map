"""``core.search_name`` — 이름 끝 라틴 괄호 변형(#1466 후속)."""

from __future__ import annotations

import doctest

import pytest

from kortravelmap.core import search_name
from kortravelmap.core.search_name import latin_bracket_name_parts


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "JW 메리어트 호텔 서울 (JW Marriott Hotel Seoul)",
            ("JW 메리어트 호텔 서울", "JW Marriott Hotel Seoul"),
        ),
        ("그랜드 하얏트 서울（Grand Hyatt Seoul）", ("그랜드 하얏트 서울", "Grand Hyatt Seoul")),
        ("  롯데호텔 (Lotte Hotel) ", ("롯데호텔", "Lotte Hotel")),
        # 앞쪽 괄호는 한글 이름의 일부다 — 끝 괄호 하나만 뗀다.
        ("A(1) 호텔 (B&B Hotel)", ("A(1) 호텔", "B&B Hotel")),
        ("호텔신라 ( The Shilla )", ("호텔신라", "The Shilla")),
        # PostgreSQL ARE의 ``.``처럼 줄바꿈도 맞춘다(SQL 짝과 같은 뜻).
        ("호텔\n본관 (Hotel Annex)", ("호텔\n본관", "Hotel Annex")),
    ],
)
def test_trailing_latin_bracket_splits_korean_and_english_names(
    name: str, expected: tuple[str, str]
) -> None:
    assert latin_bracket_name_parts(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "라한호텔(경주)",  # 한글 메모 괄호(지점·지역)는 변형이 아니다
        "스타벅스 (강남점)",
        "CU (씨유)",  # 괄호 안에 한글이 있으면 영문 이름이 아니다
        "Cafe (Seoul)",  # 한글 이름이 없다
        "호텔 (Hotel) 본관",  # 괄호가 끝에 있지 않다
        "(Hotel)",
        "호텔 (123)",  # 라틴 글자가 없다
        "JW 메리어트 호텔 서울",
        "",
    ],
)
def test_names_without_a_safe_trailing_latin_bracket_have_no_variants(name: str) -> None:
    assert latin_bracket_name_parts(name) is None


def test_bracket_candidate_like_pattern_needs_three_compact_chars_and_escapes() -> None:
    from kortravelmap.infra.feature_repo import search_bracket_like_pattern

    assert search_bracket_like_pattern("롯데호텔") == "%롯데호텔%"
    assert search_bracket_like_pattern(" 50%_off ") == "%50\\%\\_off%"
    # 공백을 지우면 2글자 — trigram이 거르지 못하므로 팔이 없다.
    assert search_bracket_like_pattern("카 페") is None


def test_doctests() -> None:
    assert doctest.testmod(search_name).failed == 0
