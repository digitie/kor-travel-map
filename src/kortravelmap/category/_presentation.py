"""category 분류 체계에서 유도한 검색 순위·표시 이름 규칙.

둘 다 **카탈로그에서 유도한다** — 8자리 코드를 하나씩 박지 않는다.

- 검색 순위 그룹: Tier 1 코드(앞 2자리)마다 하나. 관광(국가유산·문화시설 포함) → 숙박·온천
  → 식음 → 그 밖(편의·교통·의료·미분류)이다. Tier 1만 있는 코드(예: ``01000000``)는 같은
  그룹 안에서 하위 분류가 있는 코드보다 덜 구체적인 것으로 본다(``PlaceCategory.depth == 1``).
  ``feature_repo``의 검색 SQL이 이 표로 ``CASE``를 만든다.
- 표시 이름: 주차장(``06.01``) Feature는 공공 주차장 데이터셋이 관광지 이름만 싣는 경우가 많다
  ("도산서원", "고씨굴(강변)"). 이름에 "주차"가 없으면 Tier 2 표시명("주차장")을 붙여 보여 준다.
  저장된 이름은 그대로다 — 공개 read 응답에서만 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from ._definitions import (
    PLACE_CATEGORY_TIER2_NAMES_BY_TIER1,
    PlaceCategoryCode,
    PlaceCategoryTier1Code,
)

__all__ = [
    "PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1",
    "PLACE_CATEGORY_SEARCH_GROUP_FALLBACK",
    "category_search_group",
    "is_tier1_only_category_code",
    "is_parking_category_code",
    "public_feature_display_name",
]

#: Tier 1 코드 → 검색 순위 그룹(작을수록 앞). 모든 ``PlaceCategoryTier1Code``가 있어야 한다
#: (``tests/unit/test_category_presentation.py``가 강제한다).
PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1: Final[Mapping[str, int]] = MappingProxyType(
    {
        PlaceCategoryTier1Code.TOURISM.value: 0,
        PlaceCategoryTier1Code.LODGING.value: 1,
        PlaceCategoryTier1Code.HOT_SPRING_SPA.value: 1,
        PlaceCategoryTier1Code.FOOD.value: 2,
        PlaceCategoryTier1Code.CONVENIENCE.value: 3,
        PlaceCategoryTier1Code.TRANSPORT.value: 3,
        PlaceCategoryTier1Code.MEDICAL.value: 3,
        PlaceCategoryTier1Code.UNCLASSIFIED.value: 3,
    }
)

#: 카탈로그 밖 코드(예: notice의 ``99000000``)의 그룹 — 맨 뒤 그룹과 같다.
PLACE_CATEGORY_SEARCH_GROUP_FALLBACK: Final[int] = max(
    PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.values()
)

_TIER1_ONLY_SUFFIX: Final[str] = "000000"
_PARKING_CODE: Final[str] = PlaceCategoryCode.TRANSPORT_PARKING.value
_PARKING_PREFIX: Final[str] = _PARKING_CODE[:4]
_PARKING_LABEL: Final[str] = PLACE_CATEGORY_TIER2_NAMES_BY_TIER1[_PARKING_CODE[:2]][
    _PARKING_CODE[2:4]
]
#: 이미 주차 시설임을 말하는 이름("공영주차장", "주차타워", "노상주차")은 그대로 둔다.
_PARKING_NAME_MARKER: Final[str] = _PARKING_LABEL[:2]


def category_search_group(code: str | None) -> int:
    """검색 순위 그룹. 모르는 코드·``None``은 ``PLACE_CATEGORY_SEARCH_GROUP_FALLBACK``."""

    if code is None:
        return PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    return PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.get(
        str(code)[:2], PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    )


def is_tier1_only_category_code(code: str | None) -> bool:
    """Tier 1만 있는 8자리 코드(``XX000000``)인가 — 같은 그룹 안에서 덜 구체적인 분류."""

    return code is not None and len(code) == 8 and code[2:] == _TIER1_ONLY_SUFFIX


def is_parking_category_code(code: str | None) -> bool:
    """주차장(``06.01``) 또는 그 하위 분류인가."""

    return code is not None and len(code) == 8 and code.startswith(_PARKING_PREFIX)


def public_feature_display_name(name: str, category: str | None) -> str:
    """공개 응답에 보일 이름. 주차장인데 이름에 "주차"가 없으면 "<이름> 주차장"이다.

    저장 값은 바꾸지 않는다. 결과에 "주차"가 들어가므로 두 번 적용해도 같다.
    """

    if not is_parking_category_code(category):
        return name
    stripped = name.strip()
    if not stripped or _PARKING_NAME_MARKER in stripped:
        return name
    return f"{stripped} {_PARKING_LABEL}"
