"""``kortravelmap.category`` 단위 테스트 (PR#18 - ADR-023 이전 + ADR-027 적용).

검증 항목:
- 총 144건 (원본 141 + ADR-027 3건)
- depth별 통계 (sentinel 1 / Tier1 7 / Tier2 34 / Tier3 73 / Tier4 29)
- Tier 1 enum 8개 (00 sentinel + 01~07)
- ADR-027 신규 3건 (LODGING_MOUNTAIN_SHELTER + KNPS + KFS)
- ADR-027 maki = ``shelter`` (3건 모두)
- ``get_category`` ``@cache`` 적용 (ADR-030 narrow 예외)
- helper 함수 동작
"""

from __future__ import annotations

import pytest

from kortravelmap.category import (
    PLACE_CATEGORY_BY_CODE,
    PLACE_CATEGORY_DEFINITIONS,
    PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES,
    PLACE_CATEGORY_TIER2_NAMES_BY_TIER1,
    PlaceCategoryCode,
    PlaceCategoryTier1Code,
    category_label,
    category_path,
    format_category_tree,
    get_category,
    is_known_category_code,
    iter_categories,
    mapbox_maki_icon_for_category,
    mapbox_maki_icon_or_none,
)

# ── 144 카탈로그 ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_total_definitions_count() -> None:
    """원본 141 + ADR-027 3건 = 144."""
    assert len(PLACE_CATEGORY_DEFINITIONS) == 144


@pytest.mark.unit
def test_depth_distribution() -> None:
    """depth별 통계 (`docs/category.md §4.3`)."""
    depth_counts: dict[int, int] = {}
    for category in PLACE_CATEGORY_DEFINITIONS:
        depth_counts[category.depth] = depth_counts.get(category.depth, 0) + 1

    assert depth_counts == {
        0: 1,   # sentinel UNCLASSIFIED
        1: 7,   # Tier 1 (01~07, 00 제외)
        2: 34,  # Tier 2 (원본 33 + ADR-027 1)
        3: 73,  # Tier 3 (원본 71 + ADR-027 2)
        4: 29,  # Tier 4
    }


@pytest.mark.unit
def test_tier1_enum_count() -> None:
    """`PlaceCategoryTier1Code` 8개 (00 UNCLASSIFIED + 01~07). ADR-027에서
    Tier 1 enum 추가 없음."""
    tier1_codes = [code.value for code in PlaceCategoryTier1Code]
    assert sorted(tier1_codes) == ["00", "01", "02", "03", "04", "05", "06", "07"]


@pytest.mark.unit
def test_unique_codes() -> None:
    """144건 모두 고유한 code."""
    codes = [c.code for c in PLACE_CATEGORY_DEFINITIONS]
    assert len(codes) == len(set(codes)) == 144


@pytest.mark.unit
def test_by_code_lookup() -> None:
    """`PLACE_CATEGORY_BY_CODE` lookup 144 entries."""
    assert len(PLACE_CATEGORY_BY_CODE) == 144
    for category in PLACE_CATEGORY_DEFINITIONS:
        assert PLACE_CATEGORY_BY_CODE[category.code] is category


# ── ADR-027 신규 3건 ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_adr027_lodging_mountain_shelter_enum() -> None:
    """ADR-027 신규 enum 3건 존재."""
    assert PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER.value == "03080000"
    assert PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS.value == "03080100"
    assert PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KFS.value == "03080200"


@pytest.mark.unit
def test_adr027_lodging_mountain_shelter_tier2() -> None:
    """`03.08 대피소·산장` Tier 2 정의 (depth=2, parent=03)."""
    shelter = get_category("03080000")
    assert shelter.depth == 2
    assert shelter.tier1_name == "숙박"
    assert shelter.tier2_name == "대피소·산장"
    assert shelter.tier3_name is None
    assert shelter.parent_code == "03000000"  # LODGING


@pytest.mark.unit
def test_adr027_lodging_mountain_shelter_knps() -> None:
    """`03.08.01 국립공원 대피소` Tier 3 정의."""
    knps = get_category(PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS)
    assert knps.depth == 3
    assert knps.tier3_name == "국립공원 대피소"
    assert knps.parent_code == "03080000"
    assert knps.label == "숙박 > 대피소·산장 > 국립공원 대피소"


@pytest.mark.unit
def test_adr027_lodging_mountain_shelter_kfs() -> None:
    """`03.08.02 산림청 산장` Tier 3 정의."""
    kfs = get_category("03080200")
    assert kfs.depth == 3
    assert kfs.tier3_name == "산림청 산장"
    assert kfs.parent_code == "03080000"


@pytest.mark.unit
def test_adr027_tier2_names_03_includes_shelter() -> None:
    """`PLACE_CATEGORY_TIER2_NAMES_BY_TIER1['03']`에 `08 대피소·산장` 추가."""
    tier2_03 = PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["03"]
    assert tier2_03["08"] == "대피소·산장"


# ── maki icon 매핑 ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_adr027_maki_is_shelter() -> None:
    """ADR-027 신규 3건 모두 maki = ``shelter`` (Maki 표준)."""
    assert mapbox_maki_icon_for_category("03080000") == "shelter"
    assert mapbox_maki_icon_for_category("03080100") == "shelter"
    assert mapbox_maki_icon_for_category("03080200") == "shelter"


@pytest.mark.unit
def test_maki_for_unknown_code_raises() -> None:
    """strict: unknown code는 ``KeyError`` (``get_category`` semantics 일치).
    fallback이 필요하면 ``mapbox_maki_icon_or_none`` 사용."""
    with pytest.raises(KeyError):
        mapbox_maki_icon_for_category("99999999")


@pytest.mark.unit
def test_maki_or_none_for_unknown_code() -> None:
    """lenient: unknown code는 ``None`` (None-form helper)."""
    assert mapbox_maki_icon_or_none("99999999") is None
    assert mapbox_maki_icon_or_none("03080100") == "shelter"


@pytest.mark.unit
def test_shelter_in_maki_values() -> None:
    """`shelter`가 `PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES` tuple에 포함."""
    assert "shelter" in PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES


# ── helper 함수 ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_known_category_code() -> None:
    """알려진 code = True / 모르는 code = False."""
    assert is_known_category_code("03080100") is True
    assert is_known_category_code(PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER) is True
    assert is_known_category_code("99999999") is False


@pytest.mark.unit
def test_category_path_and_label() -> None:
    """``path`` tuple + ``label`` string."""
    assert category_path("03080100") == ("숙박", "대피소·산장", "국립공원 대피소")
    assert category_label("03080100") == "숙박 > 대피소·산장 > 국립공원 대피소"
    assert category_label("03080100", separator=" / ") == "숙박 / 대피소·산장 / 국립공원 대피소"


@pytest.mark.unit
def test_iter_categories_all() -> None:
    """`iter_categories()` 기본은 active_only=True (144건 모두 active)."""
    all_categories = list(iter_categories())
    assert len(all_categories) == 144


@pytest.mark.unit
def test_iter_categories_by_depth() -> None:
    """`iter_categories(depth=3)` Tier 3만 (73건)."""
    tier3 = list(iter_categories(depth=3))
    assert len(tier3) == 73
    for c in tier3:
        assert c.depth == 3


@pytest.mark.unit
def test_format_category_tree_smoke() -> None:
    """`format_category_tree()` 비어 있지 않은 string 반환."""
    tree = format_category_tree()
    assert isinstance(tree, str)
    assert len(tree) > 0
    # ADR-027 신규 노드가 트리에 포함
    assert "대피소·산장" in tree


# ── ADR-030 narrow @cache ──────────────────────────────────────────────


@pytest.mark.unit
def test_get_category_cache_applied() -> None:
    """`get_category`에 ``functools.cache`` 적용 (ADR-030 narrow 예외)."""
    # functools.cache 데코레이터는 `cache_info()` / `cache_clear()` 노출
    assert hasattr(get_category, "cache_info")
    assert hasattr(get_category, "cache_clear")

    # 동일 code 두 번 호출하면 cache hit
    get_category.cache_clear()
    _ = get_category("03080100")
    _ = get_category("03080100")
    info = get_category.cache_info()
    assert info.hits >= 1


# ── PlaceCategory dataclass ──────────────────────────────────────────────


@pytest.mark.unit
def test_place_category_as_dict() -> None:
    """`PlaceCategory.as_dict()`는 DB seed 호환 dict."""
    cat = get_category("03080100")
    d = cat.as_dict()
    assert d["category_code"] == "03080100"
    assert d["tier1_code"] == "03"
    assert d["tier2_code"] == "08"
    assert d["tier3_code"] == "01"
    assert d["tier4_code"] == "00"
    assert d["depth"] == 3
    assert d["parent_category_code"] == "03080000"
    assert d["is_active"] is True


@pytest.mark.unit
def test_place_category_frozen() -> None:
    """`PlaceCategory`는 frozen dataclass (immutable)."""
    cat = get_category("03080100")
    # dataclass frozen 위반은 dataclasses.FrozenInstanceError (AttributeError 서브클래스).
    with pytest.raises((AttributeError, TypeError)):
        cat.code = "modified"  # type: ignore[misc]
