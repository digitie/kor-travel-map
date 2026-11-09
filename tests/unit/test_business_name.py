"""인허가 상호 → 표시 이름 (``core.business_name``) — 실측 상호와 과잉 제거 가드.

기대값은 2026-11-09 MOIS 원천(``lodgings``·``tourist_accommodations``)에서 본 실제 사업장명이다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.core.business_name import (
    CURATED_BRAND_SEARCH_ALIASES,
    business_name_key,
    normalize_business_name,
)
from kortravelmap.infra.feature_repo import search_alias_key


@pytest.mark.parametrize(
    ("legal", "display"),
    [
        ("(주)호텔롯데 롯데시티호텔대전", "롯데시티호텔대전"),
        ("주식회사라한호텔전주", "라한호텔전주"),
        ("주식회사 라한호텔 울산", "라한호텔 울산"),
        ("주식회사 라한호텔(경주)", "라한호텔(경주)"),
        ("(주)라한호텔목포", "라한호텔목포"),
        ("(주)조선호텔앤리조트 조선팰리스강남", "조선팰리스강남"),
        ("(주)조선호텔앤리조트 조선팰리스강남 1914", "조선팰리스강남 1914"),
        ("(주)이랜드파크켄싱턴호텔설악(스타)", "켄싱턴호텔설악(스타)"),
        ("(주)이랜드파크 그랜드 켄싱턴 설악비치", "그랜드 켄싱턴 설악비치"),
        ("(주) 동승 JW메리어트 동대문 스퀘어 서울", "JW메리어트 동대문 스퀘어 서울"),
        ("JW메리어트호텔서울", "JW메리어트호텔서울"),
        ("호텔신라", "호텔신라"),
        ("㈜신라모텔", "신라모텔"),
        ("롯데호텔(주)", "롯데호텔"),
        ("(유)바다모텔", "바다모텔"),
        ("유한회사 바다모텔", "바다모텔"),
    ],
)
def test_legal_markers_and_curated_parent_prefixes_are_stripped(legal: str, display: str) -> None:
    name = normalize_business_name(legal)
    assert name is not None
    assert name.display == display
    assert name.legal == legal.replace("㈜", "(주)")  # NFKC


@pytest.mark.parametrize(
    "legal",
    ["페어필드 바이 메리어트 서울(Fairfield by Marriott-Seoul)", "스타벅스(STARBUCKS)", "모텔(M)"],
)
def test_latin_bracket_stays_in_the_name(legal: str) -> None:
    """검색은 이름만 trigram으로 본다 — 라틴 괄호를 떼면 영문 검색이 후보를 잃는다(리뷰 MED)."""
    for expand in (False, True):
        name = normalize_business_name(legal, expand_trailing_bracket=expand)
        assert name is not None
        assert name.display == legal
        assert not name.changed


def test_hangul_bracket_expands_only_when_asked() -> None:
    plain = normalize_business_name("베이커리(본점)")
    assert plain is not None
    assert plain.display == "베이커리(본점)"
    assert not plain.changed
    expanded = normalize_business_name("주식회사 라한호텔(경주)", expand_trailing_bracket=True)
    assert expanded is not None
    assert expanded.display == "라한호텔 경주"


@pytest.mark.parametrize(
    "legal",
    [
        "(주)",  # 법인 표기뿐 — 지우면 빈 이름
        "주식회사",
        "호텔롯데",  # 모회사 이름 자체가 상호
        "(주)호텔롯데",
        "호텔롯데 부산",  # 접두 뒤가 지역명뿐 — "부산"이 되면 안 된다
        "동승한식당",  # 일반 낱말 접두는 법인 표기·공백이 둘 다 있어야 뗀다
        "(주)동승한식당",
        "풀빌라한가",
        "주식회사신라",  # 남는 이름 2자 — 허용 하한
    ],
)
def test_over_stripping_is_guarded(legal: str) -> None:
    name = normalize_business_name(legal)
    assert name is not None
    assert len(name.display.replace(" ", "")) >= 2, name
    assert name.display not in {"부산", "한식당", "", "(주)호텔"}


def test_parent_prefix_without_marker_or_space_is_kept() -> None:
    name = normalize_business_name("호텔롯데월드점")
    assert name is not None
    assert name.display == "호텔롯데월드점"
    assert not name.changed


def test_unchanged_names_report_unchanged() -> None:
    for legal in ("신라스테이 광화문", "AC호텔 바이 메리어트 서울 강남", "한옥 게스트하우스"):
        name = normalize_business_name(legal)
        assert name is not None
        assert not name.changed


def test_empty_input_is_none() -> None:
    assert normalize_business_name(None) is None
    assert normalize_business_name("   ") is None
    assert business_name_key(None) is None


def test_name_key_ignores_spacing_and_legal_markers() -> None:
    assert business_name_key("(주)이랜드파크 켄싱턴호텔 설악(스타)") == business_name_key(
        "(주)이랜드파크켄싱턴호텔설악(스타)"
    )
    assert business_name_key("JW메리어트호텔서울") == "jw메리어트호텔서울"


@pytest.mark.parametrize("entry", CURATED_BRAND_SEARCH_ALIASES, ids=lambda e: e.query)
def test_curated_aliases_point_at_names_the_loader_produces(entry: object) -> None:
    from kortravelmap.core.business_name import BrandSearchAlias

    assert isinstance(entry, BrandSearchAlias)
    # 별칭은 숙박 Feature를 가리킨다 — 숙박 업종의 이름 규칙(괄호 펴기 켬)으로 만든다.
    produced = normalize_business_name(entry.source_name, expand_trailing_bracket=True)
    assert produced is not None
    assert produced.display == entry.canonical_name, "별칭 대상 이름이 적재 이름과 다르면 죽는다"
    assert search_alias_key(entry.query) != search_alias_key(entry.canonical_name)


def _migration_442() -> Any:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "442_mois_brand_search_aliases.py"
    )
    spec = importlib.util.spec_from_file_location("_m442_brand_aliases", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_migration_442_seeds_exactly_the_curated_dictionary() -> None:
    module = _migration_442()
    seeded = {(alias, name) for alias, name, _note in module.BRAND_ALIASES}
    curated = {
        (search_alias_key(entry.query), entry.canonical_name)
        for entry in CURATED_BRAND_SEARCH_ALIASES
    }
    assert seeded == curated
    for alias, name, _note in module.BRAND_ALIASES:
        assert alias == search_alias_key(alias), "별칭 키는 436 CHECK 형식(공백 없음·소문자)"
        assert name == name.strip()
    assert "ON CONFLICT (alias) DO NOTHING" in module._SEED_ALIASES_SQL, "덧붙이기만 한다"
    assert module._SEED_ALIASES_SQL in module._UPGRADE_STATEMENTS
