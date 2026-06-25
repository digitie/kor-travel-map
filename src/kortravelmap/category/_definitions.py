"""PinVi 장소 카테고리 체계 (``kortravelmap.category`` 내부 데이터).

이 모듈은 PinVi 장소 카테고리 코드 체계를 Python enum/dataclass로 반영한다.
provider adapter는 ingestion 코드 곳곳에 8자리 문자열을 직접 흩뿌리지 않고 이
모듈의 enum/dataclass 기반 데이터를 참조한다.

본 모듈은 ``python-kraddr-base/src/kraddr/base/categories.py`` (2026-05-12
sync)를 **ADR-023**에 따라 본 라이브러리(``kortravelmap.category``)로 이전한
사본이다. 추가로 **ADR-027**에 따라 다음 3건이 신규 추가되었다:

* ``PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER = "03080000"``
* ``PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS = "03080100"``
* ``PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KFS = "03080200"``

새 Tier 2 ``03.08 대피소·산장``는 ``PLACE_CATEGORY_TIER2_NAMES_BY_TIER1``의
``"03"`` 하위에도 추가되었다. Maki icon은 ``shelter``로 매핑된다
(``PLACE_CATEGORY_MAPBOX_MAKI_ICONS``).

PinVi category code는 ``AABBCCDD`` 형식이다.

* ``AA``: Tier 1
* ``BB``: Tier 2
* ``CC``: Tier 3
* ``DD``: Tier 4

없는 단계는 ``00``으로 채운다. 예를 들어 ``01050100``은
``관광 > 자연명소 > 해수욕장``이며 Tier 4 값은 없다.

자세한 사양은 ``docs/architecture/category.md`` + ``docs/adr/README.md`` ADR-023 / ADR-027.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum  # Python 3.11+ stdlib (requires-python>=3.11)
from functools import cache  # ADR-030 narrow 예외 (immutable 카탈로그)
from typing import Final, TextIO

PLACE_CATEGORY_SOURCE: Final = (
    "python-kraddr-base/src/kraddr/base/categories.py (ADR-023 이전) + "
    "ADR-027 LODGING_MOUNTAIN_SHELTER 3건 추가"
)
PLACE_CATEGORY_SCHEMA_DOC: Final = "docs/architecture/category.md"
PLACE_CATEGORY_SYNCED_ON: Final = "2026-05-25"  # ADR-023 + ADR-027 적용 시점


class PlaceCategoryTier1Code(StrEnum):
    """``place-schema.md``에서 가져온 PinVi Tier 1 category code."""

    UNCLASSIFIED = "00"
    TOURISM = "01"
    FOOD = "02"
    LODGING = "03"
    HOT_SPRING_SPA = "04"
    CONVENIENCE = "05"
    TRANSPORT = "06"
    MEDICAL = "07"


class PlaceCategoryCode(StrEnum):
    """현재 구현된 PinVi 8자리 category code.

    enum 값은 PinVi place schema의 ``AABBCCDD`` 계층과 현재 운영 seed를 함께
    반영한다. provider mapping의 대상 category가 확정되어 있으면 enum member를
    사용하고, DB row, config file, upstream source에서 문자열 code가 들어오면
    아래 lookup helper를 사용한다.
    """

    UNCLASSIFIED = "00000000"
    TOURISM = "01000000"
    TOURISM_THEME_PARK = "01010000"
    TOURISM_THEME_PARK_AMUSEMENT = "01010100"
    TOURISM_THEME_PARK_AMUSEMENT_LARGE = "01010101"
    TOURISM_THEME_PARK_AMUSEMENT_SMALL = "01010102"
    TOURISM_THEME_PARK_WATER = "01010200"
    TOURISM_THEME_PARK_ZOO_AQUARIUM = "01010300"
    TOURISM_THEME_PARK_ZOO = "01010301"
    TOURISM_THEME_PARK_AQUARIUM = "01010302"
    TOURISM_THEME_PARK_EXPERIENCE = "01010400"
    TOURISM_NATURAL_LANDSCAPE = "01020000"
    TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY = "01020100"
    TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK = "01020101"
    TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_LOCAL_PARK = "01020102"
    TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL = "01020103"
    TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE = "01020200"
    TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND = "01020300"
    TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE = "01020400"
    TOURISM_BOTANICAL = "01030000"
    TOURISM_BOTANICAL_GARDEN = "01030100"
    TOURISM_BOTANICAL_GARDEN_NATIONAL = "01030101"
    TOURISM_BOTANICAL_GARDEN_PUBLIC = "01030102"
    TOURISM_BOTANICAL_GARDEN_PRIVATE = "01030103"
    TOURISM_BOTANICAL_PLANT_GARDEN = "01030200"
    TOURISM_BOTANICAL_THEME_GARDEN = "01030300"
    TOURISM_NATURE = "01050000"
    TOURISM_NATURE_BEACH = "01050100"
    TOURISM_NATURE_PARK = "01050200"
    TOURISM_NATURE_OBSERVATORY = "01050300"
    TOURISM_INFORMATION = "01060000"
    TOURISM_INFORMATION_CENTER = "01060100"
    TOURISM_INFORMATION_CENTER_PUBLIC = "01060101"
    TOURISM_INFORMATION_CENTER_PRIVATE = "01060102"
    TOURISM_CULTURAL_FACILITY = "01040000"
    TOURISM_CULTURAL_FACILITY_MUSEUM = "01040100"
    TOURISM_CULTURAL_FACILITY_MUSEUM_PUBLIC = "01040101"
    TOURISM_CULTURAL_FACILITY_MUSEUM_PRIVATE = "01040102"
    TOURISM_CULTURAL_FACILITY_MUSEUM_THEMED = "01040103"
    TOURISM_CULTURAL_FACILITY_ART = "01040200"
    TOURISM_CULTURAL_FACILITY_ART_MUSEUM = "01040201"
    TOURISM_CULTURAL_FACILITY_ART_GALLERY = "01040202"
    TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL = "01040300"
    TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_GENERAL = "01040301"
    TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM = "01040302"
    TOURISM_CULTURAL_FACILITY_CINEMA = "01040400"
    TOURISM_CULTURAL_FACILITY_LIBRARY = "01040500"
    TOURISM_CULTURAL_FACILITY_CULTURE_CENTER = "01040600"
    TOURISM_HERITAGE = "01070000"
    TOURISM_HERITAGE_TEMPLE = "01070100"
    TOURISM_HERITAGE_PALACE_ROYAL_TOMB = "01070200"
    TOURISM_HERITAGE_HISTORIC_SITE = "01070300"
    TOURISM_HERITAGE_HANOK_FOLK_VILLAGE = "01070400"
    TOURISM_ACTIVITY = "01080000"
    TOURISM_ACTIVITY_GOLF = "01080100"
    TOURISM_ACTIVITY_RAIL_CABLE = "01080200"
    TOURISM_ACTIVITY_CRUISE = "01080300"
    TOURISM_ACTIVITY_LEISURE_SPORTS = "01080400"
    TOURISM_ACTIVITY_TREKKING = "01080500"
    FOOD = "02000000"
    FOOD_RESTAURANT = "02010000"
    FOOD_RESTAURANT_KOREAN = "02010100"
    FOOD_RESTAURANT_WESTERN = "02010200"
    FOOD_RESTAURANT_JAPANESE = "02010300"
    FOOD_RESTAURANT_CHINESE = "02010400"
    FOOD_RESTAURANT_ASIAN = "02010500"
    FOOD_RESTAURANT_FAST_FOOD = "02010600"
    FOOD_RESTAURANT_BUFFET = "02010700"
    FOOD_RESTAURANT_BAR = "02010800"
    FOOD_RESTAURANT_SNACK = "02010900"
    FOOD_RESTAURANT_BAKERY = "02011000"
    FOOD_CAFE = "02020000"
    FOOD_CAFE_COFFEE = "02020100"
    FOOD_CAFE_COFFEE_FRANCHISE = "02020101"
    FOOD_CAFE_COFFEE_INDEPENDENT = "02020102"
    FOOD_CAFE_DESSERT = "02020200"
    FOOD_CAFE_BAKERY = "02020300"
    LODGING = "03000000"
    LODGING_HOTEL = "03010000"
    LODGING_HOTEL_TOURIST = "03010100"
    LODGING_HOTEL_BUSINESS = "03010200"
    LODGING_HOTEL_HANOK = "03010300"
    LODGING_RESORT = "03020000"
    LODGING_RESORT_CONDO = "03020100"
    LODGING_RESORT_COMPLEX = "03020200"
    LODGING_RECREATION_FOREST = "03030000"
    LODGING_RECREATION_FOREST_NATIONAL = "03030100"
    LODGING_RECREATION_FOREST_NATIONAL_KFS = "03030101"
    LODGING_RECREATION_FOREST_PUBLIC = "03030200"
    LODGING_RECREATION_FOREST_PUBLIC_LOCAL = "03030201"
    LODGING_RECREATION_FOREST_PRIVATE = "03030300"
    LODGING_RECREATION_FOREST_PRIVATE_OPERATOR = "03030301"
    LODGING_CAMPGROUND = "03060000"
    LODGING_CAMPGROUND_AUTO = "03060100"
    LODGING_CAMPGROUND_AUTO_GENERAL_SITE = "03060101"
    LODGING_CAMPGROUND_AUTO_CARAVAN_SITE = "03060102"
    LODGING_CAMPGROUND_GLAMPING_CARAVAN = "03060200"
    LODGING_CAMPGROUND_GLAMPING = "03060201"
    LODGING_CAMPGROUND_CARAVAN_RENTAL = "03060202"
    LODGING_MOTEL = "03040000"
    LODGING_MOTEL_GENERAL = "03040100"
    LODGING_PENSION = "03050000"
    LODGING_PENSION_TOURISM = "03050100"
    LODGING_PENSION_RURAL = "03050200"
    LODGING_PENSION_PRIVATE_STAY = "03050300"
    LODGING_GUESTHOUSE = "03070000"
    LODGING_GUESTHOUSE_GENERAL = "03070100"
    LODGING_GUESTHOUSE_HANOK = "03070200"
    # ADR-027: 신규 Tier 2 `03.08 대피소·산장`. KNPS/KFS Tier 3 분기.
    LODGING_MOUNTAIN_SHELTER = "03080000"
    LODGING_MOUNTAIN_SHELTER_KNPS = "03080100"
    LODGING_MOUNTAIN_SHELTER_KFS = "03080200"
    HOT_SPRING_SPA = "04000000"
    HOT_SPRING_SPA_HOT_SPRING = "04010000"
    HOT_SPRING_SPA_HOT_SPRING_FACILITY = "04010100"
    HOT_SPRING_SPA_SAUNA = "04020000"
    HOT_SPRING_SPA_SAUNA_BATHHOUSE = "04020100"
    HOT_SPRING_SPA_THERAPY = "04030000"
    HOT_SPRING_SPA_THERAPY_SPA = "04030100"
    CONVENIENCE = "05000000"
    CONVENIENCE_STORE = "05010000"
    CONVENIENCE_BANK = "05020000"
    CONVENIENCE_MART = "05030000"
    CONVENIENCE_SUPERMARKET = "05040000"
    CONVENIENCE_DEPARTMENT_STORE = "05050000"
    CONVENIENCE_TOILET = "05060000"
    TRANSPORT = "06000000"
    TRANSPORT_PARKING = "06010000"
    TRANSPORT_FUEL = "06020000"
    TRANSPORT_STOP = "06030000"
    TRANSPORT_STOP_BUS = "06030100"
    TRANSPORT_STOP_SUBWAY = "06030200"
    TRANSPORT_STOP_TRAIN = "06030300"
    TRANSPORT_STOP_TAXI = "06030400"
    TRANSPORT_REST_AREA = "06040000"
    TRANSPORT_REST_AREA_HIGHWAY = "06040100"
    TRANSPORT_REST_AREA_HIGHWAY_EX = "06040101"
    TRANSPORT_AIRPORT = "06050000"
    MEDICAL = "07000000"
    MEDICAL_HOSPITAL = "07010000"
    MEDICAL_HOSPITAL_GENERAL = "07010100"
    MEDICAL_HOSPITAL_CLINIC = "07010200"
    MEDICAL_HOSPITAL_DENTAL = "07010300"
    MEDICAL_PHARMACY = "07020000"
    MEDICAL_PHARMACY_GENERAL = "07020100"


@dataclass(frozen=True, slots=True)
class PlaceCategory:
    """PinVi category seed 한 행.

    속성:
        code: 전체 8자리 ``AABBCCDD`` PinVi category code.
        tier1_code: 2자리 Tier 1 구간.
        tier2_code: 2자리 Tier 2 구간. 없으면 ``"00"``.
        tier3_code: 2자리 Tier 3 구간. 없으면 ``"00"``.
        tier4_code: 2자리 Tier 4 구간. 없으면 ``"00"``.
        tier1_name: 필수 Tier 1 표시명.
        tier2_name: 선택 Tier 2 표시명.
        tier3_name: 선택 Tier 3 표시명.
        tier4_name: 선택 Tier 4 표시명.
        depth: category 깊이. ``0``은 미분류 sentinel이고 ``1``부터 ``4``까지는
            일반 계층이다.
        parent_code: 부모 8자리 category code. root면 ``None``.
        sort_order: PinVi seed 정렬값.
        is_active: PinVi에서 활성 category인지 여부.

    ``path``와 ``label``은 UI text, log, mapping review output에서 쓰는 편의
    property다.
    """

    code: str
    tier1_code: str
    tier2_code: str
    tier3_code: str
    tier4_code: str
    tier1_name: str
    tier2_name: str | None
    tier3_name: str | None
    tier4_name: str | None
    depth: int
    parent_code: str | None
    sort_order: int
    is_active: bool = True

    @property
    def path(self) -> tuple[str, ...]:
        """비어 있지 않은 한국어 category path를 반환한다."""

        return tuple(
            part
            for part in (self.tier1_name, self.tier2_name, self.tier3_name, self.tier4_name)
            if part
        )

    @property
    def label(self) -> str:
        """사람이 읽기 쉬운 `` > `` 연결 category path를 반환한다."""

        return " > ".join(self.path)

    @property
    def mapbox_maki_icon(self) -> str:
        """이 category에 대응하는 Mapbox Maki icon 이름을 반환한다."""

        return mapbox_maki_icon_for_category(self.code)

    def as_dict(self) -> dict[str, object]:
        """이 category를 DB seed와 호환되는 dict로 반환한다."""

        return {
            "category_code": self.code,
            "tier1_code": self.tier1_code,
            "tier2_code": self.tier2_code,
            "tier3_code": self.tier3_code,
            "tier4_code": self.tier4_code,
            "tier1_name": self.tier1_name,
            "tier2_name": self.tier2_name,
            "tier3_name": self.tier3_name,
            "tier4_name": self.tier4_name,
            "depth": self.depth,
            "parent_category_code": self.parent_code,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
        }


PLACE_CATEGORY_TIER1_NAMES: Final[dict[str, str]] = {
    "00": "미분류",
    "01": "관광",
    "02": "식음",
    "03": "숙박",
    "04": "온천·스파",
    "05": "편의",
    "06": "교통",
    "07": "의료",
}
"""``place-schema.md``에서 가져온 PinVi Tier 1 표시명."""


PLACE_CATEGORY_TIER2_NAMES_BY_TIER1: Final[dict[str, dict[str, str]]] = {
    "01": {
        "01": "테마파크",
        "02": "자연경관",
        "03": "수목원·식물원",
        "04": "문화시설",
        "05": "자연명소",
        "06": "관광안내",
        "07": "국가유산",
        "08": "액티비티",
    },
    "02": {"01": "음식점", "02": "카페"},
    "03": {
        "01": "호텔",
        "02": "리조트",
        "03": "휴양림",
        "04": "모텔",
        "05": "펜션",
        "06": "캠핑장",
        "07": "게스트하우스",
        "08": "대피소·산장",  # ADR-027
    },
    "04": {"01": "온천", "02": "찜질방·사우나", "03": "스파·테라피"},
    "05": {
        "01": "편의점",
        "02": "은행",
        "03": "마트",
        "04": "슈퍼마켓",
        "05": "백화점",
        "06": "공중화장실",
    },
    "06": {"01": "주차장", "02": "주유소", "03": "정류장", "04": "휴게소", "05": "공항"},
    "07": {"01": "병원", "02": "약국"},
}
"""``place-schema.md``에서 가져온 PinVi Tier 2 표시명."""


def _category(
    code: PlaceCategoryCode,
    tier1_name: str,
    tier2_name: str | None,
    tier3_name: str | None,
    tier4_name: str | None,
    depth: int,
    parent_code: PlaceCategoryCode | None,
    sort_order: int,
) -> PlaceCategory:
    return PlaceCategory(
        code=code.value,
        tier1_code=code.value[0:2],
        tier2_code=code.value[2:4],
        tier3_code=code.value[4:6],
        tier4_code=code.value[6:8],
        tier1_name=tier1_name,
        tier2_name=tier2_name,
        tier3_name=tier3_name,
        tier4_name=tier4_name,
        depth=depth,
        parent_code=parent_code.value if parent_code else None,
        sort_order=sort_order,
    )


PLACE_CATEGORY_DEFINITIONS: Final[tuple[PlaceCategory, ...]] = tuple(
    sorted(
        (
            _category(PlaceCategoryCode.UNCLASSIFIED, "미분류", None, None, None, 0, None, 0),
            _category(PlaceCategoryCode.TOURISM, "관광", None, None, None, 1, None, 10),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK,
                "관광",
                "테마파크",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                10,
            ),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT,
                "관광",
                "테마파크",
                "놀이공원",
                None,
                3,
                PlaceCategoryCode.TOURISM_THEME_PARK,
                11,
            ),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_LARGE,
                "관광",
                "테마파크",
                "놀이공원",
                "대형 테마파크",
                4,
                PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT,
                111,
            ),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_SMALL,
                "관광",
                "테마파크",
                "놀이공원",
                "중소형 놀이공원",
                4,
                PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT,
                112,
            ),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK_WATER,
                "관광",
                "테마파크",
                "워터파크",
                None,
                3,
                PlaceCategoryCode.TOURISM_THEME_PARK,
                12,
            ),
            _category(
            PlaceCategoryCode.TOURISM_THEME_PARK_ZOO_AQUARIUM,
            "관광",
            "테마파크",
            "동물원·수족관",
            None,
            3,
            PlaceCategoryCode.TOURISM_THEME_PARK,
                13,
            ),
            _category(
            PlaceCategoryCode.TOURISM_THEME_PARK_ZOO,
            "관광",
            "테마파크",
            "동물원·수족관",
            "동물원",
            4,
            PlaceCategoryCode.TOURISM_THEME_PARK_ZOO_AQUARIUM,
                131,
            ),
            _category(
            PlaceCategoryCode.TOURISM_THEME_PARK_AQUARIUM,
            "관광",
            "테마파크",
            "동물원·수족관",
            "수족관",
            4,
            PlaceCategoryCode.TOURISM_THEME_PARK_ZOO_AQUARIUM,
            132,
            ),
            _category(
                PlaceCategoryCode.TOURISM_THEME_PARK_EXPERIENCE,
                "관광",
                "테마파크",
                "체험형 테마파크",
                None,
                3,
                PlaceCategoryCode.TOURISM_THEME_PARK,
                14,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE,
                "관광",
                "자연경관",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                20,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,
                "관광",
                "자연경관",
                "산·계곡",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE,
                21,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK,
                "관광",
                "자연경관",
                "산·계곡",
                "국립공원",
                4,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,
                211,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_LOCAL_PARK,
                "관광",
                "자연경관",
                "산·계곡",
                "도립·군립공원",
                4,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,
                212,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL,
                "관광",
                "자연경관",
                "산·계곡",
                "산림욕장",
                4,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,
                213,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE,
                "관광",
                "자연경관",
                "강·호수",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE,
                22,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND,
                "관광",
                "자연경관",
                "해안·섬",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE,
                23,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE,
                "관광",
                "자연경관",
                "폭포·동굴",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE,
                24,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL,
                "관광",
                "수목원·식물원",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                30,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN,
                "관광",
                "수목원·식물원",
                "수목원",
                None,
                3,
                PlaceCategoryCode.TOURISM_BOTANICAL,
                31,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_NATIONAL,
                "관광",
                "수목원·식물원",
                "수목원",
                "국립수목원",
                4,
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN,
                311,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_PUBLIC,
                "관광",
                "수목원·식물원",
                "수목원",
                "공립수목원",
                4,
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN,
                312,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_PRIVATE,
                "관광",
                "수목원·식물원",
                "수목원",
                "사립수목원",
                4,
                PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN,
                313,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_PLANT_GARDEN,
                "관광",
                "수목원·식물원",
                "식물원",
                None,
                3,
                PlaceCategoryCode.TOURISM_BOTANICAL,
                32,
            ),
            _category(
                PlaceCategoryCode.TOURISM_BOTANICAL_THEME_GARDEN,
                "관광",
                "수목원·식물원",
                "정원",
                None,
                3,
                PlaceCategoryCode.TOURISM_BOTANICAL,
                33,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURE,
                "관광",
                "자연명소",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                50,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURE_BEACH,
                "관광",
                "자연명소",
                "해수욕장",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURE,
                51,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURE_PARK,
                "관광",
                "자연명소",
                "공원·광장",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURE,
                52,
            ),
            _category(
                PlaceCategoryCode.TOURISM_NATURE_OBSERVATORY,
                "관광",
                "자연명소",
                "전망대",
                None,
                3,
                PlaceCategoryCode.TOURISM_NATURE,
                53,
            ),
            _category(
                PlaceCategoryCode.TOURISM_INFORMATION,
                "관광",
                "관광안내",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                60,
            ),
            _category(
                PlaceCategoryCode.TOURISM_INFORMATION_CENTER,
                "관광",
                "관광안내",
                "관광안내소",
                None,
                3,
                PlaceCategoryCode.TOURISM_INFORMATION,
                61,
            ),
            _category(
                PlaceCategoryCode.TOURISM_INFORMATION_CENTER_PUBLIC,
                "관광",
                "관광안내",
                "관광안내소",
                "공공 관광안내소",
                4,
                PlaceCategoryCode.TOURISM_INFORMATION_CENTER,
                611,
            ),
            _category(
                PlaceCategoryCode.TOURISM_INFORMATION_CENTER_PRIVATE,
                "관광",
                "관광안내",
                "관광안내소",
                "민간 관광안내소",
                4,
                PlaceCategoryCode.TOURISM_INFORMATION_CENTER,
                612,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                "관광",
                "문화시설",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                40,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM,
                "관광",
                "문화시설",
                "박물관",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                41,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_PUBLIC,
                "관광",
                "문화시설",
                "박물관",
                "국공립 박물관",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM,
                411,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_PRIVATE,
                "관광",
                "문화시설",
                "박물관",
                "사립 박물관",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM,
                412,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_THEMED,
                "관광",
                "문화시설",
                "박물관",
                "테마 박물관",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM,
                413,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART,
                "관광",
                "문화시설",
                "미술관·갤러리",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                42,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_MUSEUM,
                "관광",
                "문화시설",
                "미술관·갤러리",
                "미술관",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART,
                421,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_GALLERY,
                "관광",
                "문화시설",
                "미술관·갤러리",
                "갤러리",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART,
                422,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,
                "관광",
                "문화시설",
                "공연장",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                43,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_GENERAL,
                "관광",
                "문화시설",
                "공연장",
                "일반 공연장",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,
                431,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM,
                "관광",
                "문화시설",
                "공연장",
                "관광공연장",
                4,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,
                432,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CINEMA,
                "관광",
                "문화시설",
                "영화관",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                44,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY,
                "관광",
                "문화시설",
                "도서관",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                45,
            ),
            _category(
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CULTURE_CENTER,
                "관광",
                "문화시설",
                "지방문화원",
                None,
                3,
                PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
                46,
            ),
            _category(
                PlaceCategoryCode.TOURISM_HERITAGE,
                "관광",
                "국가유산",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                70,
            ),
            _category(
                PlaceCategoryCode.TOURISM_HERITAGE_TEMPLE,
                "관광",
                "국가유산",
                "전통사찰",
                None,
                3,
                PlaceCategoryCode.TOURISM_HERITAGE,
                71,
            ),
            _category(
                PlaceCategoryCode.TOURISM_HERITAGE_PALACE_ROYAL_TOMB,
                "관광",
                "국가유산",
                "궁궐·왕릉",
                None,
                3,
                PlaceCategoryCode.TOURISM_HERITAGE,
                72,
            ),
            _category(
                PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE,
                "관광",
                "국가유산",
                "사적·기념물",
                None,
                3,
                PlaceCategoryCode.TOURISM_HERITAGE,
                73,
            ),
            _category(
                PlaceCategoryCode.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE,
                "관광",
                "국가유산",
                "한옥·민속마을",
                None,
                3,
                PlaceCategoryCode.TOURISM_HERITAGE,
                74,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY,
                "관광",
                "액티비티",
                None,
                None,
                2,
                PlaceCategoryCode.TOURISM,
                80,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY_GOLF,
                "관광",
                "액티비티",
                "골프장",
                None,
                3,
                PlaceCategoryCode.TOURISM_ACTIVITY,
                81,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY_RAIL_CABLE,
                "관광",
                "액티비티",
                "관광궤도",
                None,
                3,
                PlaceCategoryCode.TOURISM_ACTIVITY,
                82,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY_CRUISE,
                "관광",
                "액티비티",
                "관광유람선",
                None,
                3,
                PlaceCategoryCode.TOURISM_ACTIVITY,
                83,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS,
                "관광",
                "액티비티",
                "레저스포츠",
                None,
                3,
                PlaceCategoryCode.TOURISM_ACTIVITY,
                84,
            ),
            _category(
                PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING,
                "관광",
                "액티비티",
                "트레킹·둘레길",
                None,
                3,
                PlaceCategoryCode.TOURISM_ACTIVITY,
                85,
            ),
            _category(PlaceCategoryCode.FOOD, "식음", None, None, None, 1, None, 200),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT,
                "식음",
                "음식점",
                None,
                None,
                2,
                PlaceCategoryCode.FOOD,
                210,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_KOREAN,
                "식음",
                "음식점",
                "한식",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                211,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_WESTERN,
                "식음",
                "음식점",
                "양식",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                212,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_JAPANESE,
                "식음",
                "음식점",
                "일식",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                213,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_CHINESE,
                "식음",
                "음식점",
                "중식",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                214,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_ASIAN,
                "식음",
                "음식점",
                "아시안",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                215,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_FAST_FOOD,
                "식음",
                "음식점",
                "패스트푸드",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                216,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_BUFFET,
                "식음",
                "음식점",
                "뷔페",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                217,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_BAR,
                "식음",
                "음식점",
                "주점",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                218,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_SNACK,
                "식음",
                "음식점",
                "분식",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                219,
            ),
            _category(
                PlaceCategoryCode.FOOD_RESTAURANT_BAKERY,
                "식음",
                "음식점",
                "베이커리",
                None,
                3,
                PlaceCategoryCode.FOOD_RESTAURANT,
                2110,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE,
                "식음",
                "카페",
                None,
                None,
                2,
                PlaceCategoryCode.FOOD,
                220,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE_COFFEE,
                "식음",
                "카페",
                "커피전문점",
                None,
                3,
                PlaceCategoryCode.FOOD_CAFE,
                221,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE_COFFEE_FRANCHISE,
                "식음",
                "카페",
                "커피전문점",
                "프랜차이즈 카페",
                4,
                PlaceCategoryCode.FOOD_CAFE_COFFEE,
                2211,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE_COFFEE_INDEPENDENT,
                "식음",
                "카페",
                "커피전문점",
                "개인 카페",
                4,
                PlaceCategoryCode.FOOD_CAFE_COFFEE,
                2212,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE_DESSERT,
                "식음",
                "카페",
                "디저트 카페",
                None,
                3,
                PlaceCategoryCode.FOOD_CAFE,
                222,
            ),
            _category(
                PlaceCategoryCode.FOOD_CAFE_BAKERY,
                "식음",
                "카페",
                "베이커리 카페",
                None,
                3,
                PlaceCategoryCode.FOOD_CAFE,
                223,
            ),
            _category(PlaceCategoryCode.LODGING, "숙박", None, None, None, 1, None, 300),
            _category(
                PlaceCategoryCode.LODGING_HOTEL,
                "숙박",
                "호텔",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                310,
            ),
            _category(
                PlaceCategoryCode.LODGING_HOTEL_TOURIST,
                "숙박",
                "호텔",
                "관광호텔",
                None,
                3,
                PlaceCategoryCode.LODGING_HOTEL,
                311,
            ),
            _category(
                PlaceCategoryCode.LODGING_HOTEL_BUSINESS,
                "숙박",
                "호텔",
                "비즈니스호텔",
                None,
                3,
                PlaceCategoryCode.LODGING_HOTEL,
                312,
            ),
            _category(
                PlaceCategoryCode.LODGING_HOTEL_HANOK,
                "숙박",
                "호텔",
                "한옥호텔",
                None,
                3,
                PlaceCategoryCode.LODGING_HOTEL,
                313,
            ),
            _category(
                PlaceCategoryCode.LODGING_RESORT,
                "숙박",
                "리조트",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                320,
            ),
            _category(
                PlaceCategoryCode.LODGING_RESORT_CONDO,
                "숙박",
                "리조트",
                "휴양콘도미니엄",
                None,
                3,
                PlaceCategoryCode.LODGING_RESORT,
                321,
            ),
            _category(
                PlaceCategoryCode.LODGING_RESORT_COMPLEX,
                "숙박",
                "리조트",
                "종합휴양업",
                None,
                3,
                PlaceCategoryCode.LODGING_RESORT,
                322,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST,
                "숙박",
                "휴양림",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                330,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_NATIONAL,
                "숙박",
                "휴양림",
                "국립휴양림",
                None,
                3,
                PlaceCategoryCode.LODGING_RECREATION_FOREST,
                331,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_NATIONAL_KFS,
                "숙박",
                "휴양림",
                "국립휴양림",
                "산림청 운영",
                4,
                PlaceCategoryCode.LODGING_RECREATION_FOREST_NATIONAL,
                3311,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PUBLIC,
                "숙박",
                "휴양림",
                "공립휴양림",
                None,
                3,
                PlaceCategoryCode.LODGING_RECREATION_FOREST,
                332,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PUBLIC_LOCAL,
                "숙박",
                "휴양림",
                "공립휴양림",
                "지자체 운영",
                4,
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PUBLIC,
                3321,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PRIVATE,
                "숙박",
                "휴양림",
                "사립휴양림",
                None,
                3,
                PlaceCategoryCode.LODGING_RECREATION_FOREST,
                333,
            ),
            _category(
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PRIVATE_OPERATOR,
                "숙박",
                "휴양림",
                "사립휴양림",
                "민간 운영",
                4,
                PlaceCategoryCode.LODGING_RECREATION_FOREST_PRIVATE,
                3331,
            ),
            _category(
                PlaceCategoryCode.LODGING_MOTEL,
                "숙박",
                "모텔",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                340,
            ),
            _category(
                PlaceCategoryCode.LODGING_MOTEL_GENERAL,
                "숙박",
                "모텔",
                "일반 모텔",
                None,
                3,
                PlaceCategoryCode.LODGING_MOTEL,
                341,
            ),
            _category(
                PlaceCategoryCode.LODGING_PENSION,
                "숙박",
                "펜션",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                350,
            ),
            _category(
                PlaceCategoryCode.LODGING_PENSION_TOURISM,
                "숙박",
                "펜션",
                "관광펜션",
                None,
                3,
                PlaceCategoryCode.LODGING_PENSION,
                351,
            ),
            _category(
                PlaceCategoryCode.LODGING_PENSION_RURAL,
                "숙박",
                "펜션",
                "농어촌민박",
                None,
                3,
                PlaceCategoryCode.LODGING_PENSION,
                352,
            ),
            _category(
                PlaceCategoryCode.LODGING_PENSION_PRIVATE_STAY,
                "숙박",
                "펜션",
                "민박",
                None,
                3,
                PlaceCategoryCode.LODGING_PENSION,
                353,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND,
                "숙박",
                "캠핑장",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                360,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_AUTO,
                "숙박",
                "캠핑장",
                "오토캠핑장",
                None,
                3,
                PlaceCategoryCode.LODGING_CAMPGROUND,
                361,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_AUTO_GENERAL_SITE,
                "숙박",
                "캠핑장",
                "오토캠핑장",
                "일반 사이트",
                4,
                PlaceCategoryCode.LODGING_CAMPGROUND_AUTO,
                3611,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_AUTO_CARAVAN_SITE,
                "숙박",
                "캠핑장",
                "오토캠핑장",
                "카라반·캠핑카 사이트",
                4,
                PlaceCategoryCode.LODGING_CAMPGROUND_AUTO,
                3612,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING_CARAVAN,
                "숙박",
                "캠핑장",
                "글램핑·카라반",
                None,
                3,
                PlaceCategoryCode.LODGING_CAMPGROUND,
                362,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING,
                "숙박",
                "캠핑장",
                "글램핑·카라반",
                "글램핑",
                4,
                PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING_CARAVAN,
                3621,
            ),
            _category(
                PlaceCategoryCode.LODGING_CAMPGROUND_CARAVAN_RENTAL,
                "숙박",
                "캠핑장",
                "글램핑·카라반",
                "카라반 대여",
                4,
                PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING_CARAVAN,
                3622,
            ),
            _category(
                PlaceCategoryCode.LODGING_GUESTHOUSE,
                "숙박",
                "게스트하우스",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                370,
            ),
            _category(
                PlaceCategoryCode.LODGING_GUESTHOUSE_GENERAL,
                "숙박",
                "게스트하우스",
                "게스트하우스",
                None,
                3,
                PlaceCategoryCode.LODGING_GUESTHOUSE,
                371,
            ),
            _category(
                PlaceCategoryCode.LODGING_GUESTHOUSE_HANOK,
                "숙박",
                "게스트하우스",
                "한옥체험업",
                None,
                3,
                PlaceCategoryCode.LODGING_GUESTHOUSE,
                372,
            ),
            # ADR-027: 신규 Tier 2 `03.08 대피소·산장` + KNPS/KFS Tier 3.
            _category(
                PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER,
                "숙박",
                "대피소·산장",
                None,
                None,
                2,
                PlaceCategoryCode.LODGING,
                380,
            ),
            _category(
                PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS,
                "숙박",
                "대피소·산장",
                "국립공원 대피소",
                None,
                3,
                PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER,
                381,
            ),
            _category(
                PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KFS,
                "숙박",
                "대피소·산장",
                "산림청 산장",
                None,
                3,
                PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER,
                382,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA,
                "온천·스파",
                None,
                None,
                None,
                1,
                None,
                400,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING,
                "온천·스파",
                "온천",
                None,
                None,
                2,
                PlaceCategoryCode.HOT_SPRING_SPA,
                410,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING_FACILITY,
                "온천·스파",
                "온천",
                "온천시설",
                None,
                3,
                PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING,
                411,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_SAUNA,
                "온천·스파",
                "찜질방·사우나",
                None,
                None,
                2,
                PlaceCategoryCode.HOT_SPRING_SPA,
                420,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_SAUNA_BATHHOUSE,
                "온천·스파",
                "찜질방·사우나",
                "목욕장업",
                None,
                3,
                PlaceCategoryCode.HOT_SPRING_SPA_SAUNA,
                421,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_THERAPY,
                "온천·스파",
                "스파·테라피",
                None,
                None,
                2,
                PlaceCategoryCode.HOT_SPRING_SPA,
                430,
            ),
            _category(
                PlaceCategoryCode.HOT_SPRING_SPA_THERAPY_SPA,
                "온천·스파",
                "스파·테라피",
                "스파",
                None,
                3,
                PlaceCategoryCode.HOT_SPRING_SPA_THERAPY,
                431,
            ),
            _category(PlaceCategoryCode.CONVENIENCE, "편의", None, None, None, 1, None, 500),
            _category(
                PlaceCategoryCode.CONVENIENCE_STORE,
                "편의",
                "편의점",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                510,
            ),
            _category(
                PlaceCategoryCode.CONVENIENCE_BANK,
                "편의",
                "은행",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                520,
            ),
            _category(
                PlaceCategoryCode.CONVENIENCE_MART,
                "편의",
                "마트",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                530,
            ),
            _category(
                PlaceCategoryCode.CONVENIENCE_SUPERMARKET,
                "편의",
                "슈퍼마켓",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                540,
            ),
            _category(
                PlaceCategoryCode.CONVENIENCE_DEPARTMENT_STORE,
                "편의",
                "백화점",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                550,
            ),
            _category(
                PlaceCategoryCode.CONVENIENCE_TOILET,
                "편의",
                "공중화장실",
                None,
                None,
                2,
                PlaceCategoryCode.CONVENIENCE,
                560,
            ),
            _category(PlaceCategoryCode.TRANSPORT, "교통", None, None, None, 1, None, 600),
            _category(
                PlaceCategoryCode.TRANSPORT_PARKING,
                "교통",
                "주차장",
                None,
                None,
                2,
                PlaceCategoryCode.TRANSPORT,
                610,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_FUEL,
                "교통",
                "주유소",
                None,
                None,
                2,
                PlaceCategoryCode.TRANSPORT,
                620,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_STOP,
                "교통",
                "정류장",
                None,
                None,
                2,
                PlaceCategoryCode.TRANSPORT,
                630,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_STOP_BUS,
                "교통",
                "정류장",
                "버스정류장",
                None,
                3,
                PlaceCategoryCode.TRANSPORT_STOP,
                631,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_STOP_SUBWAY,
                "교통",
                "정류장",
                "지하철역",
                None,
                3,
                PlaceCategoryCode.TRANSPORT_STOP,
                632,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_STOP_TRAIN,
                "교통",
                "정류장",
                "기차역",
                None,
                3,
                PlaceCategoryCode.TRANSPORT_STOP,
                633,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_STOP_TAXI,
                "교통",
                "정류장",
                "택시승강장",
                None,
                3,
                PlaceCategoryCode.TRANSPORT_STOP,
                634,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_REST_AREA,
                "교통",
                "휴게소",
                None,
                None,
                2,
                PlaceCategoryCode.TRANSPORT,
                640,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY,
                "교통",
                "휴게소",
                "고속도로휴게소",
                None,
                3,
                PlaceCategoryCode.TRANSPORT_REST_AREA,
                641,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY_EX,
                "교통",
                "휴게소",
                "고속도로휴게소",
                "한국도로공사 휴게소",
                4,
                PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY,
                6411,
            ),
            _category(
                PlaceCategoryCode.TRANSPORT_AIRPORT,
                "교통",
                "공항",
                None,
                None,
                2,
                PlaceCategoryCode.TRANSPORT,
                650,
            ),
            _category(PlaceCategoryCode.MEDICAL, "의료", None, None, None, 1, None, 700),
            _category(
                PlaceCategoryCode.MEDICAL_HOSPITAL,
                "의료",
                "병원",
                None,
                None,
                2,
                PlaceCategoryCode.MEDICAL,
                710,
            ),
            _category(
                PlaceCategoryCode.MEDICAL_HOSPITAL_GENERAL,
                "의료",
                "병원",
                "종합병원",
                None,
                3,
                PlaceCategoryCode.MEDICAL_HOSPITAL,
                711,
            ),
            _category(
                PlaceCategoryCode.MEDICAL_HOSPITAL_CLINIC,
                "의료",
                "병원",
                "의원",
                None,
                3,
                PlaceCategoryCode.MEDICAL_HOSPITAL,
                712,
            ),
            _category(
                PlaceCategoryCode.MEDICAL_HOSPITAL_DENTAL,
                "의료",
                "병원",
                "치과",
                None,
                3,
                PlaceCategoryCode.MEDICAL_HOSPITAL,
                713,
            ),
            _category(
                PlaceCategoryCode.MEDICAL_PHARMACY,
                "의료",
                "약국",
                None,
                None,
                2,
                PlaceCategoryCode.MEDICAL,
                720,
            ),
            _category(
                PlaceCategoryCode.MEDICAL_PHARMACY_GENERAL,
                "의료",
                "약국",
                "일반 약국",
                None,
                3,
                PlaceCategoryCode.MEDICAL_PHARMACY,
                721,
            ),
        ),
        key=lambda category: category.code,
    )
)
"""PinVi에 현재 구현된 place category 정의 row."""


PLACE_CATEGORY_BY_CODE: Final[dict[str, PlaceCategory]] = {
    category.code: category for category in PLACE_CATEGORY_DEFINITIONS
}
"""8자리 PinVi category code를 key로 쓰는 조회용 table."""


PLACE_CATEGORY_CODES: Final[tuple[str, ...]] = tuple(
    category.code for category in PLACE_CATEGORY_DEFINITIONS
)
"""현재 구현된 모든 PinVi category code. 순서는 정의 table 순서를 따른다."""


MAPBOX_MAKI_ICON_SOURCE: Final = "https://github.com/mapbox/maki/tree/main/icons"
"""Mapbox Maki icon filename 기준 source."""


PLACE_CATEGORY_MAPBOX_MAKI_ICONS: Final[dict[str, str]] = {
    PlaceCategoryCode.UNCLASSIFIED.value: "marker",
    PlaceCategoryCode.TOURISM.value: "attraction",
    PlaceCategoryCode.TOURISM_THEME_PARK.value: "amusement-park",
    PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT.value: "amusement-park",
    PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_LARGE.value: "amusement-park",
    PlaceCategoryCode.TOURISM_THEME_PARK_AMUSEMENT_SMALL.value: "amusement-park",
    PlaceCategoryCode.TOURISM_THEME_PARK_WATER.value: "swimming",
    PlaceCategoryCode.TOURISM_THEME_PARK_ZOO_AQUARIUM.value: "zoo",
    PlaceCategoryCode.TOURISM_THEME_PARK_ZOO.value: "zoo",
    PlaceCategoryCode.TOURISM_THEME_PARK_AQUARIUM.value: "aquarium",
    PlaceCategoryCode.TOURISM_THEME_PARK_EXPERIENCE.value: "attraction",
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE.value: "natural",
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY.value: "mountain",
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK.value: ("park"),
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_LOCAL_PARK.value: ("park"),
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL.value: ("park"),
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE.value: "water",
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND.value: "beach",
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE.value: "natural",
    PlaceCategoryCode.TOURISM_BOTANICAL.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_NATIONAL.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_PUBLIC.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN_PRIVATE.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_PLANT_GARDEN.value: "garden",
    PlaceCategoryCode.TOURISM_BOTANICAL_THEME_GARDEN.value: "garden",
    PlaceCategoryCode.TOURISM_NATURE.value: "natural",
    PlaceCategoryCode.TOURISM_NATURE_BEACH.value: "beach",
    PlaceCategoryCode.TOURISM_NATURE_PARK.value: "park",
    PlaceCategoryCode.TOURISM_NATURE_OBSERVATORY.value: "viewpoint",
    PlaceCategoryCode.TOURISM_INFORMATION.value: "information",
    PlaceCategoryCode.TOURISM_INFORMATION_CENTER.value: "information",
    PlaceCategoryCode.TOURISM_INFORMATION_CENTER_PUBLIC.value: "information",
    PlaceCategoryCode.TOURISM_INFORMATION_CENTER_PRIVATE.value: "information",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value: "museum",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM.value: "museum",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_PUBLIC.value: "museum",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_PRIVATE.value: "museum",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM_THEMED.value: "museum",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART.value: "art-gallery",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_MUSEUM.value: "art-gallery",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_GALLERY.value: "art-gallery",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL.value: "theatre",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_GENERAL.value: ("theatre"),
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM.value: ("theatre"),
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CINEMA.value: "cinema",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY.value: "library",
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_CULTURE_CENTER.value: "town-hall",
    PlaceCategoryCode.TOURISM_HERITAGE.value: "monument",
    PlaceCategoryCode.TOURISM_HERITAGE_TEMPLE.value: "religious-buddhist",
    PlaceCategoryCode.TOURISM_HERITAGE_PALACE_ROYAL_TOMB.value: "castle",
    PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE.value: "monument",
    PlaceCategoryCode.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE.value: "village",
    PlaceCategoryCode.TOURISM_ACTIVITY.value: "attraction",
    PlaceCategoryCode.TOURISM_ACTIVITY_GOLF.value: "golf",
    PlaceCategoryCode.TOURISM_ACTIVITY_RAIL_CABLE.value: "rail",
    PlaceCategoryCode.TOURISM_ACTIVITY_CRUISE.value: "ferry",
    PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS.value: "pitch",
    PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING.value: "park",
    PlaceCategoryCode.FOOD.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_KOREAN.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_WESTERN.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_JAPANESE.value: "restaurant-sushi",
    PlaceCategoryCode.FOOD_RESTAURANT_CHINESE.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_ASIAN.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_FAST_FOOD.value: "fast-food",
    PlaceCategoryCode.FOOD_RESTAURANT_BUFFET.value: "restaurant",
    PlaceCategoryCode.FOOD_RESTAURANT_BAR.value: "bar",
    PlaceCategoryCode.FOOD_RESTAURANT_SNACK.value: "fast-food",
    PlaceCategoryCode.FOOD_RESTAURANT_BAKERY.value: "bakery",
    PlaceCategoryCode.FOOD_CAFE.value: "cafe",
    PlaceCategoryCode.FOOD_CAFE_COFFEE.value: "cafe",
    PlaceCategoryCode.FOOD_CAFE_COFFEE_FRANCHISE.value: "cafe",
    PlaceCategoryCode.FOOD_CAFE_COFFEE_INDEPENDENT.value: "cafe",
    PlaceCategoryCode.FOOD_CAFE_DESSERT.value: "cafe",
    PlaceCategoryCode.FOOD_CAFE_BAKERY.value: "bakery",
    PlaceCategoryCode.LODGING.value: "lodging",
    PlaceCategoryCode.LODGING_HOTEL.value: "lodging",
    PlaceCategoryCode.LODGING_HOTEL_TOURIST.value: "lodging",
    PlaceCategoryCode.LODGING_HOTEL_BUSINESS.value: "lodging",
    PlaceCategoryCode.LODGING_HOTEL_HANOK.value: "lodging",
    PlaceCategoryCode.LODGING_RESORT.value: "lodging",
    PlaceCategoryCode.LODGING_RESORT_CONDO.value: "lodging",
    PlaceCategoryCode.LODGING_RESORT_COMPLEX.value: "lodging",
    PlaceCategoryCode.LODGING_RECREATION_FOREST.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_NATIONAL.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_NATIONAL_KFS.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_PUBLIC.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_PUBLIC_LOCAL.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_PRIVATE.value: "park",
    PlaceCategoryCode.LODGING_RECREATION_FOREST_PRIVATE_OPERATOR.value: "park",
    PlaceCategoryCode.LODGING_CAMPGROUND.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_AUTO.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_AUTO_GENERAL_SITE.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_AUTO_CARAVAN_SITE.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING_CARAVAN.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_GLAMPING.value: "campsite",
    PlaceCategoryCode.LODGING_CAMPGROUND_CARAVAN_RENTAL.value: "campsite",
    PlaceCategoryCode.LODGING_MOTEL.value: "lodging",
    PlaceCategoryCode.LODGING_MOTEL_GENERAL.value: "lodging",
    PlaceCategoryCode.LODGING_PENSION.value: "home",
    PlaceCategoryCode.LODGING_PENSION_TOURISM.value: "home",
    PlaceCategoryCode.LODGING_PENSION_RURAL.value: "home",
    PlaceCategoryCode.LODGING_PENSION_PRIVATE_STAY.value: "home",
    PlaceCategoryCode.LODGING_GUESTHOUSE.value: "lodging",
    PlaceCategoryCode.LODGING_GUESTHOUSE_GENERAL.value: "lodging",
    PlaceCategoryCode.LODGING_GUESTHOUSE_HANOK.value: "lodging",
    # ADR-027: 신규 대피소·산장 Tier 2/3 (maki = shelter, Maki 표준 존재).
    PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER.value: "shelter",
    PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS.value: "shelter",
    PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KFS.value: "shelter",
    PlaceCategoryCode.HOT_SPRING_SPA.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_HOT_SPRING_FACILITY.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_SAUNA.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_SAUNA_BATHHOUSE.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_THERAPY.value: "hot-spring",
    PlaceCategoryCode.HOT_SPRING_SPA_THERAPY_SPA.value: "hot-spring",
    PlaceCategoryCode.CONVENIENCE.value: "convenience",
    PlaceCategoryCode.CONVENIENCE_STORE.value: "convenience",
    PlaceCategoryCode.CONVENIENCE_BANK.value: "bank",
    PlaceCategoryCode.CONVENIENCE_MART.value: "grocery",
    PlaceCategoryCode.CONVENIENCE_SUPERMARKET.value: "shop",
    PlaceCategoryCode.CONVENIENCE_DEPARTMENT_STORE.value: "clothing-store",
    PlaceCategoryCode.CONVENIENCE_TOILET.value: "toilet",
    PlaceCategoryCode.TRANSPORT.value: "car",
    PlaceCategoryCode.TRANSPORT_PARKING.value: "parking",
    PlaceCategoryCode.TRANSPORT_FUEL.value: "fuel",
    PlaceCategoryCode.TRANSPORT_STOP.value: "bus",
    PlaceCategoryCode.TRANSPORT_STOP_BUS.value: "bus",
    PlaceCategoryCode.TRANSPORT_STOP_SUBWAY.value: "rail-metro",
    PlaceCategoryCode.TRANSPORT_STOP_TRAIN.value: "rail",
    PlaceCategoryCode.TRANSPORT_STOP_TAXI.value: "taxi",
    PlaceCategoryCode.TRANSPORT_REST_AREA.value: "highway-rest-area",
    PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY.value: "highway-rest-area",
    PlaceCategoryCode.TRANSPORT_REST_AREA_HIGHWAY_EX.value: "highway-rest-area",
    PlaceCategoryCode.TRANSPORT_AIRPORT.value: "airport",
    PlaceCategoryCode.MEDICAL.value: "hospital",
    PlaceCategoryCode.MEDICAL_HOSPITAL.value: "hospital",
    PlaceCategoryCode.MEDICAL_HOSPITAL_GENERAL.value: "hospital",
    PlaceCategoryCode.MEDICAL_HOSPITAL_CLINIC.value: "doctor",
    PlaceCategoryCode.MEDICAL_HOSPITAL_DENTAL.value: "dentist",
    PlaceCategoryCode.MEDICAL_PHARMACY.value: "pharmacy",
    PlaceCategoryCode.MEDICAL_PHARMACY_GENERAL.value: "pharmacy",
}
"""PinVi category code를 Mapbox Maki icon 이름으로 매핑한 table."""


PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES: Final[tuple[str, ...]] = tuple(
    sorted(set(PLACE_CATEGORY_MAPBOX_MAKI_ICONS.values()))
)
"""현재 category mapping에서 사용하는 Mapbox Maki icon 이름."""


@cache
def get_category(code: str | PlaceCategoryCode) -> PlaceCategory:
    """8자리 code에 해당하는 PinVi category를 반환한다.

    ADR-030 narrow ``functools.cache`` 예외 — ``PLACE_CATEGORY_DEFINITIONS``는
    릴리스 단위 immutable이므로 cache가 stale될 일이 없다. ``PLACE_CATEGORY_BY_CODE``
    dict lookup은 cheap이지만 변환 (StrEnum → str) 비용 + 빈번한 호출 회피를
    위해 캐시.

    예외:
        KeyError: ``code``가 현재 구현된 PinVi seed 집합에 없을 때 발생한다.
    """

    text_code = code.value if isinstance(code, PlaceCategoryCode) else str(code)
    return PLACE_CATEGORY_BY_CODE[text_code]


def is_known_category_code(code: str | PlaceCategoryCode) -> bool:
    """``code``가 현재 PinVi seed 집합에 있으면 ``True``를 반환한다."""

    text_code = code.value if isinstance(code, PlaceCategoryCode) else str(code)
    return text_code in PLACE_CATEGORY_BY_CODE


def mapbox_maki_icon_for_category(code: str | PlaceCategoryCode) -> str:
    """``code``에 대응하는 Mapbox Maki icon 이름을 반환한다.

    반환값은 Maki SVG 파일명에서 ``.svg``를 뺀 값이다. 예를 들어 ``"beach"``는
    Mapbox Maki의 ``beach.svg`` icon을 뜻한다.
    """

    category = get_category(code)
    return PLACE_CATEGORY_MAPBOX_MAKI_ICONS[category.code]


def mapbox_maki_icon_or_none(code: str | PlaceCategoryCode) -> str | None:
    """알 수 없는 category code면 ``None``을 반환하는 Maki icon lookup helper."""

    text_code = code.value if isinstance(code, PlaceCategoryCode) else str(code)
    return PLACE_CATEGORY_MAPBOX_MAKI_ICONS.get(text_code)


def iter_categories(
    *,
    depth: int | None = None,
    active_only: bool = True,
) -> Iterator[PlaceCategory]:
    """PinVi category를 seed 순서대로 순회한다.

    인자:
        depth: 선택 category depth filter. 예를 들어 ``4``를 넘기면 현재 Tier 4로
            정의된 leaf category만 순회한다.
        active_only: 비활성 category를 건너뛸지 여부. 현재 PinVi seed row는 모두
            활성 상태지만, 이후 category가 제거되지 않고 deprecate될 때 provider
            코드를 안정적으로 유지하기 위한 flag다.
    """

    for category in PLACE_CATEGORY_DEFINITIONS:
        if depth is not None and category.depth != depth:
            continue
        if active_only and not category.is_active:
            continue
        yield category


def _category_node_name(category: PlaceCategory) -> str:
    if category.depth == 0:
        return category.tier1_name
    if category.depth == 1:
        return category.tier1_name
    if category.depth == 2:
        return category.tier2_name or category.label
    if category.depth == 3:
        return category.tier3_name or category.label
    if category.depth == 4:
        return category.tier4_name or category.label
    return category.label


def _category_node_label(category: PlaceCategory, *, include_codes: bool) -> str:
    name = _category_node_name(category)
    if not include_codes:
        return name
    return f"{name} [{category.code}]"


def _iter_category_tree_lines(
    parent_code: str | None,
    *,
    children_by_parent: dict[str | None, list[PlaceCategory]],
    prefix: str,
    include_codes: bool,
) -> Iterator[str]:
    children = children_by_parent.get(parent_code, [])

    for index, category in enumerate(children):
        is_last = index == len(children) - 1
        connector = "" if parent_code is None else ("└── " if is_last else "├── ")
        yield f"{prefix}{connector}{_category_node_label(category, include_codes=include_codes)}"

        child_prefix = prefix
        if parent_code is not None:
            child_prefix += "    " if is_last else "│   "
        yield from _iter_category_tree_lines(
            category.code,
            children_by_parent=children_by_parent,
            prefix=child_prefix,
            include_codes=include_codes,
        )


def format_category_tree(
    *,
    root_code: str | PlaceCategoryCode | None = None,
    include_codes: bool = True,
    active_only: bool = True,
) -> str:
    """PinVi category 전체 또는 일부를 트리 문자열로 반환한다.

    인자:
        root_code: 특정 category를 root로 삼아 하위 트리만 보고 싶을 때 넘긴다.
            ``None``이면 현재 구현된 모든 root category를 출력한다.
        include_codes: 각 node label에 8자리 category code를 함께 표시할지 여부.
        active_only: 비활성 category를 제외할지 여부.
    """

    categories = list(iter_categories(active_only=active_only))
    children_by_parent: dict[str | None, list[PlaceCategory]] = {}
    for category in categories:
        children_by_parent.setdefault(category.parent_code, []).append(category)

    for children in children_by_parent.values():
        children.sort(key=lambda category: (category.sort_order, category.code))

    if root_code is None:
        return "\n".join(
            _iter_category_tree_lines(
                None,
                children_by_parent=children_by_parent,
                prefix="",
                include_codes=include_codes,
            )
        )

    root = get_category(root_code)
    if active_only and not root.is_active:
        return ""

    lines = [_category_node_label(root, include_codes=include_codes)]
    lines.extend(
        _iter_category_tree_lines(
            root.code,
            children_by_parent=children_by_parent,
            prefix="",
            include_codes=include_codes,
        )
    )
    return "\n".join(lines)


def print_category_tree(
    *,
    root_code: str | PlaceCategoryCode | None = None,
    include_codes: bool = True,
    active_only: bool = True,
    stream: TextIO | None = None,
) -> None:
    """PinVi category tree를 출력한다.

    출력 문자열이 필요한 코드나 테스트에서는 ``format_category_tree``를 사용한다.
    """

    target = stream if stream is not None else sys.stdout
    print(
        format_category_tree(
            root_code=root_code,
            include_codes=include_codes,
            active_only=active_only,
        ),
        file=target,
    )


def category_path(code: str | PlaceCategoryCode) -> tuple[str, ...]:
    """``code``에 해당하는 한국어 category path를 반환한다."""

    return get_category(code).path


def category_label(code: str | PlaceCategoryCode, *, separator: str = " > ") -> str:
    """``code``의 category path를 ``separator``로 연결한 label로 반환한다."""

    return separator.join(category_path(code))
