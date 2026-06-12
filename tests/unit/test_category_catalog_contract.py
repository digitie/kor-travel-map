"""카탈로그 self-consistency + ``@kor-travel-map/map-marker-react`` maki 교차 점검 (T-213f).

- Python 카탈로그(144건)의 maki icon이 자기 일관적인지(ADR-027).
- marker-react ``maki.ts``의 maki name이 valid kebab-case이고, provider가 자주
  emit하는 핵심 maki는 글리프로 커버되는지(미지정 maki는 첫 글자 fallback이라 전부
  커버할 필요는 없음 — ADR-029의 category↔TS 1:1 게이트는 name→glyph 구조에 맞춰
  완화된 형태로 적용한다).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kortravelmap.category import (
    PLACE_CATEGORY_DEFINITIONS,
    PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES,
    mapbox_maki_icon_for_category,
)

pytestmark = pytest.mark.unit

_MAKI_TS = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "map-marker-react"
    / "src"
    / "maki.ts"
)


def test_catalog_count_and_maki_self_consistency() -> None:
    assert len(PLACE_CATEGORY_DEFINITIONS) == 144
    values = set(PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES)
    for cat in PLACE_CATEGORY_DEFINITIONS:
        assert cat.mapbox_maki_icon in values
        assert mapbox_maki_icon_for_category(cat.code) == cat.mapbox_maki_icon


def _ts_known_maki_names() -> set[str]:
    text = _MAKI_TS.read_text(encoding="utf-8")
    # MAKI_GLYPH 객체의 `"name": "..."` 키만 추출.
    return set(re.findall(r'"([a-z0-9][a-z0-9-]*)":\s*"', text))


def test_marker_react_maki_names_are_valid_kebab() -> None:
    names = _ts_known_maki_names()
    assert names, "maki.ts에서 maki name을 추출하지 못했다"
    for name in names:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), name


def test_marker_react_covers_core_provider_maki() -> None:
    # 미지정 maki는 TS가 첫 글자 fallback으로 처리하므로 55+개 전부 커버할 필요는
    # 없다. 단 provider가 자주 emit하는 핵심 maki는 글리프 커버가 깨지면 안 된다.
    ts_names = _ts_known_maki_names()
    core = {"fuel", "restaurant", "cafe", "park", "monument", "shelter", "star", "marker"}
    missing = core - ts_names
    assert not missing, f"marker-react maki.ts에 핵심 maki 글리프 누락: {sorted(missing)}"
