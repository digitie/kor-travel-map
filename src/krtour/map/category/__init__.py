"""``krtour.map.category`` — PlaceCategoryCode 카탈로그 144건 (ADR-023 + 027).

본 모듈은 ``python-kraddr-base/src/kraddr/base/categories.py``에서 이전된
카테고리 분류 체계를 제공한다. ADR-023에 따라 본 라이브러리로 이전, ADR-027
에 따라 ``LODGING_MOUNTAIN_SHELTER`` Tier 2 + KNPS/KFS Tier 3 (3행) 추가.

총 144건 (sentinel 1 + Tier 1 7 + Tier 2 34 + Tier 3 73 + Tier 4 29).

ADR 참조
--------
- ADR-023 — ``python-kraddr-base``의 category 모듈을 본 라이브러리로 이전
- ADR-027 — forest 카테고리/notice_type 확장 (``LODGING_MOUNTAIN_SHELTER``
  3행 추가, Tier 1 8개 유지)
- ADR-030 — narrow ``functools.cache`` 예외 (``get_category``는 immutable
  카탈로그라 모듈 레벨 ``@cache`` 허용)

자세히는 ``docs/category.md``.

사용 예시:
    >>> from krtour.map.category import (
    ...     PlaceCategoryCode, get_category, mapbox_maki_icon_for_category,
    ... )
    >>> get_category(PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS).label
    '숙박 > 대피소·산장 > 국립공원 대피소'
    >>> mapbox_maki_icon_for_category("03080100")
    'shelter'
"""

from __future__ import annotations

from ._definitions import (
    PLACE_CATEGORY_BY_CODE,
    PLACE_CATEGORY_CODES,
    PLACE_CATEGORY_DEFINITIONS,
    PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES,
    PLACE_CATEGORY_MAPBOX_MAKI_ICONS,
    PLACE_CATEGORY_SCHEMA_DOC,
    PLACE_CATEGORY_SOURCE,
    PLACE_CATEGORY_SYNCED_ON,
    PLACE_CATEGORY_TIER1_NAMES,
    PLACE_CATEGORY_TIER2_NAMES_BY_TIER1,
    PlaceCategory,
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
    print_category_tree,
)

__all__ = [
    # 메타
    "PLACE_CATEGORY_SOURCE",
    "PLACE_CATEGORY_SCHEMA_DOC",
    "PLACE_CATEGORY_SYNCED_ON",
    # enum / dataclass
    "PlaceCategory",
    "PlaceCategoryCode",
    "PlaceCategoryTier1Code",
    # tier 표시명
    "PLACE_CATEGORY_TIER1_NAMES",
    "PLACE_CATEGORY_TIER2_NAMES_BY_TIER1",
    # 카탈로그 (144건)
    "PLACE_CATEGORY_DEFINITIONS",
    "PLACE_CATEGORY_BY_CODE",
    "PLACE_CATEGORY_CODES",
    # maki icon 매핑
    "PLACE_CATEGORY_MAPBOX_MAKI_ICONS",
    "PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES",
    # helper
    "get_category",
    "is_known_category_code",
    "iter_categories",
    "category_path",
    "category_label",
    "mapbox_maki_icon_for_category",
    "mapbox_maki_icon_or_none",
    "format_category_tree",
    "print_category_tree",
]
