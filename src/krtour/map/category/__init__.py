"""``krtour.map.category`` — PlaceCategoryCode 카탈로그 (ADR-023).

본 모듈은 ``python-kraddr-base/src/kraddr/base/categories.py``에서 이전된
카테고리 분류 체계를 제공한다 (ADR-023 + ADR-027 적용 후 144건).

**Sprint 1 PR#18에서 실제 코드 이전 예정** — 본 PR#17은 PEP 420 패키지
구조만 박는 placeholder.

ADR 참조
--------
- ADR-023 — ``python-kraddr-base``의 category 모듈을 본 라이브러리로 이전
- ADR-027 — forest 카테고리/notice_type 확장 (``LODGING_MOUNTAIN_SHELTER``
  3행 추가, Tier 1 8개 유지)
- ADR-030 — narrow ``functools.cache`` 예외 (PlaceCategoryCode 카탈로그는
  immutable이라 모듈 레벨 ``@cache`` 허용)

자세히는 ``docs/category.md``.
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 1 PR#18에서 채워질 예정:
#   - PlaceCategory, PlaceCategoryCode, PlaceCategoryTier1Code (typed)
#   - PLACE_CATEGORY_DEFINITIONS (144건 tuple)
#   - PLACE_CATEGORY_BY_CODE, PLACE_CATEGORY_TIER1_NAMES,
#     PLACE_CATEGORY_TIER2_NAMES_BY_TIER1
#   - PLACE_CATEGORY_MAPBOX_MAKI_ICONS, PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES
#   - get_category, is_known_category_code, iter_categories,
#     category_path, category_label, mapbox_maki_icon_for_category,
#     mapbox_maki_icon_or_none, format_category_tree, print_category_tree
