"""category 분류 체계에서 유도한 검색 순위·표시 이름 규칙.

둘 다 **카탈로그에서 유도한다** — 8자리 코드를 하나씩 박지 않는다.

- 검색 순위 그룹(작을수록 앞): 관광(국가유산·문화시설 포함) 0 → 숙박·온천 1 → 식음 2 →
  편의·교통·의료·미분류 3(소유자 결정 2026-11-02). 기본은 Tier 1 코드(앞 2자리)마다 하나다.
  예외는 교통 가운데 **이름으로 찾아가는 목적지** — 기차역·지하철역(Tier 3), 휴게소·공항·
  여객선터미널(Tier 2)
  — 과 전통시장(편의 Tier 2)만 숙박과 같은 1이다. "서울역"·"김포공항"·"남대문시장"을 찾을 때 그
  시설이 "…서울역점" 음식점이나 시장 안 점포보다 뒤로 밀리지 않게 한다(적대 리뷰 2026-11-02,
  2026-11-10 운영 검색 점검). 버스 정류장·택시 승강장·주차·주유는 3 그대로다.
  이 접두 예외(**고유 이름 목적지**)는 이름이 검색어와 정확히 같으면 관광과 같은 그룹 0으로 본다
  (``destination_exact_search_group``) — "서울역"·"자갈치시장"을 찾으면 역·시장 자체가 같은 이름의
  Tier 1만 있는 관광 행(촬영지 목록·영상 후보의 ``01000000``)보다 앞이다. 숙박은 그대로 1이다 —
  관광지 이름을 상호로 쓴 숙소가 그 관광지를 넘지 않는다.
  Tier 1만 있는 코드(예: ``01000000``)는 같은 그룹 안에서 하위 분류가 있는 코드보다 덜
  구체적인 것으로 본다. ``feature_repo``의 검색 SQL이 이 표로 ``CASE``를 만든다.
- 표시 이름: 주차장(``06.01``) Feature는 공공 주차장 데이터셋이 관광지 이름만 싣는 경우가 많다
  ("도산서원", "고씨굴(강변)"). 이름에 "주차"가 없으면 Tier 2 표시명("주차장")을 붙여 보여 준다.
  저장된 이름은 그대로다 — 공개 read 응답과 검색의 이름 비교(포함·일치 단계)에서 쓴다.
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
    "PARKING_CATEGORY_PREFIX",
    "PARKING_DISPLAY_LABEL",
    "PARKING_NAME_MARKER",
    "PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1",
    "PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES",
    "PLACE_CATEGORY_SEARCH_GROUP_FALLBACK",
    "SEARCH_DESTINATION_GROUP_MAX",
    "SEARCH_NAMED_DESTINATION_EXACT_GROUP",
    "category_search_group",
    "destination_exact_search_group",
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


def _category_prefix(code: PlaceCategoryCode) -> str:
    """코드에서 끝의 ``00`` 단계를 뗀 접두(``06040000`` → ``0604``, ``06030300`` → ``060303``)."""

    value = code.value
    while value.endswith("00") and len(value) > 2:
        value = value[:-2]
    return value


#: 분류 접두(4·6자리) → 그룹 예외. Tier 1 표보다 먼저, **긴 접두부터** 본다. 교통 가운데 이름으로
#: 찾아가는 목적지와 전통시장만 숙박과 같은 1로 올린다. 키는 카탈로그 코드에서 유도한다. 이 표의
#: 분류가 **고유 이름 목적지**다(``destination_exact_search_group``).
PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES: Final[Mapping[str, int]] = MappingProxyType(
    {
        _category_prefix(PlaceCategoryCode.TRANSPORT_STOP_SUBWAY): 1,
        _category_prefix(PlaceCategoryCode.TRANSPORT_STOP_TRAIN): 1,
        _category_prefix(PlaceCategoryCode.TRANSPORT_REST_AREA): 1,
        _category_prefix(PlaceCategoryCode.TRANSPORT_AIRPORT): 1,
        _category_prefix(PlaceCategoryCode.TRANSPORT_FERRY_TERMINAL): 1,
        _category_prefix(PlaceCategoryCode.CONVENIENCE_TRADITIONAL_MARKET): 1,
    }
)

#: 카탈로그 밖 코드(예: notice의 ``99000000``)의 그룹 — 맨 뒤 그룹과 같다.
PLACE_CATEGORY_SEARCH_GROUP_FALLBACK: Final[int] = max(
    PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.values()
)

#: 이름으로 찾아가는 **목적지** 그룹의 상한(관광 0, 숙박·온천·역·휴게소·공항·여객선터미널 1).
#: 검색에서 이름이 검색어와 정확히 같은 목적지는 분류 그룹보다 앞이다(ADR-120) — 식음·편의·주차는
#: 이름이 같아도 그룹 뒤에서만 가른다.
SEARCH_DESTINATION_GROUP_MAX: Final[int] = 1

#: 고유 이름 목적지(접두 예외 표의 분류 — 역·휴게소·공항·여객선터미널·전통시장)의 이름이 검색어와
#: 정확히 같을 때의 그룹. 관광(0)과 같다 — 같은 이름의 관광 행과는 분류 구체성으로 가른다.
SEARCH_NAMED_DESTINATION_EXACT_GROUP: Final[int] = 0

_TIER1_ONLY_SUFFIX: Final[str] = "000000"
_PARKING_CODE: Final[str] = PlaceCategoryCode.TRANSPORT_PARKING.value
#: 주차장 분류 접두(Tier 1+2, ``0601``). 하위 분류도 같은 접두를 갖는다.
PARKING_CATEGORY_PREFIX: Final[str] = _PARKING_CODE[:4]
#: 주차장 Tier 2 표시명("주차장") — 표시 이름에 덧붙이는 말.
PARKING_DISPLAY_LABEL: Final[str] = PLACE_CATEGORY_TIER2_NAMES_BY_TIER1[_PARKING_CODE[:2]][
    _PARKING_CODE[2:4]
]
#: 이미 주차 시설임을 말하는 이름("공영주차장", "주차타워", "노상주차")은 그대로 둔다.
PARKING_NAME_MARKER: Final[str] = PARKING_DISPLAY_LABEL[:2]


def category_search_group(code: str | None) -> int:
    """검색 순위 그룹. 모르는 코드·``None``은 ``PLACE_CATEGORY_SEARCH_GROUP_FALLBACK``."""

    if code is None:
        return PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    text_code = str(code)
    for prefix in sorted(PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES, key=len, reverse=True):
        if text_code.startswith(prefix):
            return PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES[prefix]
    return PLACE_CATEGORY_SEARCH_GROUP_BY_TIER1.get(
        text_code[:2], PLACE_CATEGORY_SEARCH_GROUP_FALLBACK
    )


def _named_destination_prefix(code: str) -> str | None:
    for prefix in sorted(PLACE_CATEGORY_SEARCH_GROUP_PREFIX_OVERRIDES, key=len, reverse=True):
        if code.startswith(prefix):
            return prefix
    return None


def destination_exact_search_group(code: str | None) -> int:
    """이름이 검색어와 정확히 같은 목적지 행의 검색 그룹.

    고유 이름 목적지(접두 예외 표의 분류)는 ``SEARCH_NAMED_DESTINATION_EXACT_GROUP``, 그 밖은
    ``category_search_group``과 같다. 검색 SQL의 ``_search_destination_exact_group_sql``이 짝이다.
    """

    if code is not None and _named_destination_prefix(str(code)) is not None:
        return SEARCH_NAMED_DESTINATION_EXACT_GROUP
    return category_search_group(code)


def is_tier1_only_category_code(code: str | None) -> bool:
    """Tier 1만 있는 8자리 코드(``XX000000``)인가 — 같은 그룹 안에서 덜 구체적인 분류."""

    return code is not None and len(code) == 8 and code[2:] == _TIER1_ONLY_SUFFIX


def is_parking_category_code(code: str | None) -> bool:
    """주차장(``06.01``) 또는 그 하위 분류인가."""

    return code is not None and len(code) == 8 and code.startswith(PARKING_CATEGORY_PREFIX)


def public_feature_display_name(name: str, category: str | None) -> str:
    """공개 응답에 보일 이름. 주차장인데 이름에 "주차"가 없으면 "<이름> 주차장"이다.

    저장 값은 바꾸지 않는다. 결과에 "주차"가 들어가므로 두 번 적용해도 같다. 검색 SQL의
    ``_search_display_name_sql``이 같은 규칙을 SQL로 쓴다(공백만인 이름은 양쪽 다 그대로 두고,
    앞뒤 공백 처리만 다르다 — 검색 SQL은 비교 키를 만들기 전에 공백을 걷으므로 순위에는 같다).
    """

    if not is_parking_category_code(category):
        return name
    stripped = name.strip()
    if not stripped or PARKING_NAME_MARKER in stripped:
        return name
    return f"{stripped} {PARKING_DISPLAY_LABEL}"
