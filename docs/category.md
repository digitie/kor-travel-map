# category.md — `kortravelmap.category` 모듈 사양

본 문서는 `kortravelmap.category` 모듈의 사양 reference다. 해당 모듈은
`python-kraddr-base`의 `kraddr.base.categories` 모듈을 이전해 온 것이다 (ADR-023).

> **현재 상태**: Sprint 1에서 `src/kortravelmap/category/` 이전 완료 (PR#18).
> 본 문서는 현행 category 모듈의 계약 reference다. 신규 카테고리/마커 매핑
> 변경은 ADR과 테스트를 함께 갱신한다.

## 1. 목적

지도 marker용 카테고리 분류 + Mapbox Maki icon 매핑을 제공한다. TripMate 지도의
모든 marker는 이 카테고리 체계로 분류되고, frontend는 `marker_icon` (maki id) +
`marker_color` (`P-01` ~ `P-16`, v2 frontend 팔레트) 조합으로 렌더링한다.

## 2. import 경로

```python
from kortravelmap.category import (
    # Enum
    PlaceCategoryCode, PlaceCategoryTier1Code,
    # Dataclass
    PlaceCategory,
    # 상수
    PLACE_CATEGORY_DEFINITIONS,
    PLACE_CATEGORY_BY_CODE,
    PLACE_CATEGORY_CODES,
    PLACE_CATEGORY_TIER1_NAMES,
    PLACE_CATEGORY_TIER2_NAMES_BY_TIER1,
    PLACE_CATEGORY_MAPBOX_MAKI_ICONS,
    PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES,
    # 함수
    get_category, is_known_category_code, iter_categories,
    category_path, category_label,
    mapbox_maki_icon_for_category, mapbox_maki_icon_or_none,
    format_category_tree, print_category_tree,
)
```

## 3. 데이터 구조

### 3.1 `PlaceCategoryCode` (StrEnum)

8자리 코드 `AABBCCDD` 형식. 총 144개 enum member (원본 141 + ADR-027 신규 3).

```
AA — Tier 1 (대분류, 예: "01" 관광, "02" 음식, "03" 숙박)
BB — Tier 2 (중분류, 예: "01" 자연관광, "02" 역사관광)
CC — Tier 3 (소분류)
DD — Tier 4 (세분류, 보통 "00")
```

예: `"01050100"` = 관광 / 자연 / 해변 / 일반.

`"00000000"`은 루트 (분류 미지정).

### 3.2 `PlaceCategoryTier1Code` (StrEnum)

2자리 Tier 1 코드. `"00"` ~ `"07"` (현재 8개 분류).

### 3.3 `PlaceCategory` (dataclass)

```python
@dataclass(frozen=True)
class PlaceCategory:
    code: PlaceCategoryCode
    tier1_code: PlaceCategoryTier1Code
    tier1_name: str
    tier2_code: str | None
    tier2_name: str | None
    tier3_code: str | None
    tier3_name: str | None
    tier4_code: str | None
    tier4_name: str | None
    depth: int            # 1~4
    parent_code: PlaceCategoryCode | None
    sort_order: int
    is_active: bool = True

    @property
    def path(self) -> tuple[str, ...]:
        """Non-None tier names tuple (e.g., ('관광', '자연', '해변'))."""

    @property
    def label(self, separator: str = " > ") -> str:
        """' > '.join(self.path)"""
```

### 3.4 상수

| 이름 | 타입 | 의미 |
|------|------|------|
| `PLACE_CATEGORY_DEFINITIONS` | `tuple[PlaceCategory, ...]` | 144개 정의 |
| `PLACE_CATEGORY_BY_CODE` | `dict[PlaceCategoryCode, PlaceCategory]` | 코드 → 정의 |
| `PLACE_CATEGORY_CODES` | `tuple[PlaceCategoryCode, ...]` | 모든 코드 (sort_order 순) |
| `PLACE_CATEGORY_TIER1_NAMES` | `dict[PlaceCategoryTier1Code, str]` | 예: `"01"→"관광"` |
| `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1` | `dict[PlaceCategoryTier1Code, dict[str, str]]` | nested |
| `PLACE_CATEGORY_MAPBOX_MAKI_ICONS` | `dict[PlaceCategoryCode, str]` | 코드 → maki icon name |
| `PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES` | `tuple[str, ...]` | 정렬된 unique icon names |

### 3.5 함수

| 시그니처 | 의미 |
|---------|------|
| `get_category(code) -> PlaceCategory` | code → PlaceCategory. unknown이면 KeyError. |
| `is_known_category_code(code) -> bool` | 알려진 코드인지 |
| `iter_categories(*, depth=None, active_only=True) -> Iterator[PlaceCategory]` | 필터 순회 |
| `category_path(code) -> tuple[str, ...]` | `PlaceCategory.path` 단축 |
| `category_label(code, separator=" > ") -> str` | `PlaceCategory.label` 단축 |
| `mapbox_maki_icon_for_category(code) -> str` | maki icon name. unknown 코드면 `KeyError` (strict, `get_category` 일치) |
| `mapbox_maki_icon_or_none(code) -> str \| None` | unknown 코드면 `None` (lenient) |
| `format_category_tree(root_code=None, include_codes=True, active_only=True) -> str` | 트리 문자열 |
| `print_category_tree(...)` | 위 결과 print |

## 4. Tier 1~4 카탈로그 (144건 전체)

> 소스: `python-kraddr-base/src/kraddr/base/categories.py` (sync date
> `2026-05-12`, ADR-023으로 본 저장소 이전 완료 PR#18). 총 **144건** = sentinel 1 +
> Tier 1 7개 + Tier 2 34개 + Tier 3 73개 + Tier 4 29개 (원본 141 + ADR-027 신규 3:
> `03.08 LODGING_MOUNTAIN_SHELTER` + `03.08.01/02`). depth별 정확한 통계는 §4.3.

### 4.1 Tier 1 (대분류, 8개)

| Tier 1 코드 | enum name | 한국어 | 본 라이브러리 주 적재 source |
|------------|-----------|--------|---------------------------|
| `00` | `UNCLASSIFIED` | 미분류 | sentinel — 모든 provider의 fallback |
| `01` | `TOURISM` | 관광 | VisitKorea TourAPI, 국가유산, KHOA, 산림청, KNPS, 표준데이터 |
| `02` | `FOOD` | 식음 | MOIS 인허가 (식음 슬러그), 표준데이터, place-phone 보강 |
| `03` | `LODGING` | 숙박 | MOIS 인허가 (숙박 슬러그), 산림청 휴양림, 표준데이터 |
| `04` | `HOT_SPRING_SPA` | 온천·스파 | MOIS 인허가 (목욕장업) |
| `05` | `CONVENIENCE` | 편의 | 표준데이터 (주차장은 교통에), 공중화장실 |
| `06` | `TRANSPORT` | 교통 | OpiNet (주유소), KREX (휴게소), 표준데이터 (주차장), 공항 |
| `07` | `MEDICAL` | 의료 | MOIS 인허가 (의료 슬러그, 후속 검토) |

`PlaceCategoryTier1Code` enum이 위 8개 코드를 정의. `PLACE_CATEGORY_TIER1_NAMES`
dict가 한국어 라벨 제공.

**`99000000` sentinel 관례 (place 아님 anchor)**: 날씨 특보(kma)·교통 notice
(krex)·대기질(airkorea)처럼 place가 아닌 anchor Feature는 카탈로그 밖 코드
`"99000000"`을 `Feature.category` placeholder로 쓴다. 이 코드는
`PlaceCategoryCode` enum에 없으며 `is_known_category_code("99000000")`는 False다
(카테고리 트리에 notice/weather/air-quality 도메인이 등록될 때까지 임시). 사용
provider는 `kma`(기상특보)·`airkorea`(대기질 측정소)·`krex`(교통 notice).

### 4.2 전체 카테고리 트리 (들여쓰기 뷰)

```
00 미분류 (UNCLASSIFIED) [maki: marker]

01 관광 (TOURISM) [maki: attraction]
  01.01 테마파크 (TOURISM_THEME_PARK) [maki: amusement-park]
    01.01.01 놀이공원 (TOURISM_THEME_PARK_AMUSEMENT) [maki: amusement-park]
      01.01.01.01 대형 테마파크 (..._LARGE) [maki: amusement-park]
      01.01.01.02 중소형 놀이공원 (..._SMALL) [maki: amusement-park]
    01.01.02 워터파크 (TOURISM_THEME_PARK_WATER) [maki: swimming]
    01.01.03 동물원·수족관 (TOURISM_THEME_PARK_ZOO_AQUARIUM) [maki: zoo]
      01.01.03.01 동물원 (..._ZOO) [maki: zoo]
      01.01.03.02 수족관 (..._AQUARIUM) [maki: aquarium]
    01.01.04 체험형 테마파크 (TOURISM_THEME_PARK_EXPERIENCE) [maki: attraction]
  01.02 자연경관 (TOURISM_NATURAL_LANDSCAPE) [maki: natural]
    01.02.01 산·계곡 (..._MOUNTAIN_VALLEY) [maki: mountain]
      01.02.01.01 국립공원 (..._NATIONAL_PARK) [maki: park]
      01.02.01.02 도립·군립공원 (..._LOCAL_PARK) [maki: park]
      01.02.01.03 산림욕장 (..._FOREST_TRAIL) [maki: park]
    01.02.02 강·호수 (..._RIVER_LAKE) [maki: water]
    01.02.03 해안·섬 (..._COAST_ISLAND) [maki: beach]
    01.02.04 폭포·동굴 (..._WATERFALL_CAVE) [maki: natural]
  01.03 수목원·식물원 (TOURISM_BOTANICAL) [maki: garden]
    01.03.01 수목원 (..._GARDEN) [maki: garden]
      01.03.01.01 국립수목원 (..._NATIONAL) [maki: garden]
      01.03.01.02 공립수목원 (..._PUBLIC) [maki: garden]
      01.03.01.03 사립수목원 (..._PRIVATE) [maki: garden]
    01.03.02 식물원 (..._PLANT_GARDEN) [maki: garden]
    01.03.03 정원 (..._THEME_GARDEN) [maki: garden]
  01.04 문화시설 (TOURISM_CULTURAL_FACILITY) [maki: museum]
    01.04.01 박물관 (..._MUSEUM) [maki: museum]
      01.04.01.01 국공립 박물관 (..._PUBLIC) [maki: museum]
      01.04.01.02 사립 박물관 (..._PRIVATE) [maki: museum]
      01.04.01.03 테마 박물관 (..._THEMED) [maki: museum]
    01.04.02 미술관·갤러리 (..._ART) [maki: art-gallery]
      01.04.02.01 미술관 (..._MUSEUM) [maki: art-gallery]
      01.04.02.02 갤러리 (..._GALLERY) [maki: art-gallery]
    01.04.03 공연장 (..._PERFORMANCE_HALL) [maki: theatre]
      01.04.03.01 일반 공연장 (..._GENERAL) [maki: theatre]
      01.04.03.02 관광공연장 (..._TOURISM) [maki: theatre]
    01.04.04 영화관 (..._CINEMA) [maki: cinema]
    01.04.05 도서관 (..._LIBRARY) [maki: library]
    01.04.06 지방문화원 (..._CULTURE_CENTER) [maki: town-hall]
  01.05 자연명소 (TOURISM_NATURE) [maki: natural]
    01.05.01 해수욕장 (TOURISM_NATURE_BEACH) [maki: beach]    ← KHOA 해수욕장 (코드 01050100, DA-D-07)
    01.05.02 공원·광장 (TOURISM_NATURE_PARK) [maki: park]
    01.05.03 전망대 (TOURISM_NATURE_OBSERVATORY) [maki: viewpoint]
  01.06 관광안내 (TOURISM_INFORMATION) [maki: information]
    01.06.01 관광안내소 (..._CENTER) [maki: information]
      01.06.01.01 공공 관광안내소 (..._PUBLIC) [maki: information]
      01.06.01.02 민간 관광안내소 (..._PRIVATE) [maki: information]
  01.07 국가유산 (TOURISM_HERITAGE) [maki: monument]    ← krheritage
    01.07.01 전통사찰 (..._TEMPLE) [maki: religious-buddhist]
    01.07.02 궁궐·왕릉 (..._PALACE_ROYAL_TOMB) [maki: castle]
    01.07.03 사적·기념물 (..._HISTORIC_SITE) [maki: monument]
    01.07.04 한옥·민속마을 (..._HANOK_FOLK_VILLAGE) [maki: village]
  01.08 액티비티 (TOURISM_ACTIVITY) [maki: attraction]
    01.08.01 골프장 (..._GOLF) [maki: golf]
    01.08.02 관광궤도 (..._RAIL_CABLE) [maki: rail]
    01.08.03 관광유람선 (..._CRUISE) [maki: ferry]
    01.08.04 레저스포츠 (..._LEISURE_SPORTS) [maki: pitch]
    01.08.05 트레킹·둘레길 (..._TREKKING) [maki: park]

02 식음 (FOOD) [maki: restaurant]
  02.01 음식점 (FOOD_RESTAURANT) [maki: restaurant]
    02.01.01 한식 (..._KOREAN) [maki: restaurant]
    02.01.02 양식 (..._WESTERN) [maki: restaurant]
    02.01.03 일식 (..._JAPANESE) [maki: restaurant-sushi]
    02.01.04 중식 (..._CHINESE) [maki: restaurant]
    02.01.05 아시안 (..._ASIAN) [maki: restaurant]
    02.01.06 패스트푸드 (..._FAST_FOOD) [maki: fast-food]
    02.01.07 뷔페 (..._BUFFET) [maki: restaurant]
    02.01.08 주점 (..._BAR) [maki: bar]
    02.01.09 분식 (..._SNACK) [maki: fast-food]
    02.01.10 베이커리 (..._BAKERY) [maki: bakery]
  02.02 카페 (FOOD_CAFE) [maki: cafe]
    02.02.01 커피전문점 (..._COFFEE) [maki: cafe]
      02.02.01.01 프랜차이즈 카페 (..._FRANCHISE) [maki: cafe]
      02.02.01.02 개인 카페 (..._INDEPENDENT) [maki: cafe]
    02.02.02 디저트 카페 (..._DESSERT) [maki: cafe]
    02.02.03 베이커리 카페 (..._BAKERY) [maki: bakery]

03 숙박 (LODGING) [maki: lodging]
  03.01 호텔 (LODGING_HOTEL) [maki: lodging]
    03.01.01 관광호텔 (..._TOURIST) [maki: lodging]    ← MOIS tourist_accommodations
    03.01.02 비즈니스호텔 (..._BUSINESS) [maki: lodging]
    03.01.03 한옥호텔 (..._HANOK) [maki: lodging]
  03.02 리조트 (LODGING_RESORT) [maki: lodging]
    03.02.01 휴양콘도미니엄 (..._CONDO) [maki: lodging]
    03.02.02 종합휴양업 (..._COMPLEX) [maki: lodging]
  03.03 휴양림 (LODGING_RECREATION_FOREST) [maki: park]   ← 산림청 휴양림
    03.03.01 국립휴양림 (..._NATIONAL) [maki: park]
      03.03.01.01 산림청 운영 (..._KFS) [maki: park]
    03.03.02 공립휴양림 (..._PUBLIC) [maki: park]
      03.03.02.01 지자체 운영 (..._LOCAL) [maki: park]
    03.03.03 사립휴양림 (..._PRIVATE) [maki: park]
      03.03.03.01 민간 운영 (..._OPERATOR) [maki: park]
  03.04 모텔 (LODGING_MOTEL) [maki: lodging]
    03.04.01 일반 모텔 (..._GENERAL) [maki: lodging]
  03.05 펜션 (LODGING_PENSION) [maki: home]
    03.05.01 관광펜션 (..._TOURISM) [maki: home]    ← MOIS tourist_pensions
    03.05.02 농어촌민박 (..._RURAL) [maki: home]    ← MOIS rural_homestays
    03.05.03 민박 (..._PRIVATE_STAY) [maki: home]
  03.06 캠핑장 (LODGING_CAMPGROUND) [maki: campsite]
    03.06.01 오토캠핑장 (..._AUTO) [maki: campsite]    ← MOIS auto_campgrounds
      03.06.01.01 일반 사이트 (..._GENERAL_SITE) [maki: campsite]
      03.06.01.02 카라반·캠핑카 사이트 (..._CARAVAN_SITE) [maki: campsite]
    03.06.02 글램핑·카라반 (..._GLAMPING_CARAVAN) [maki: campsite]
      03.06.02.01 글램핑 (..._GLAMPING) [maki: campsite]
      03.06.02.02 카라반 대여 (..._RENTAL) [maki: campsite]
  03.07 게스트하우스 (LODGING_GUESTHOUSE) [maki: lodging]
    03.07.01 게스트하우스 (..._GENERAL) [maki: lodging]    ← MOIS foreigner_city_homestays
    03.07.02 한옥체험업 (..._HANOK) [maki: lodging]    ← MOIS hanok_experience
  03.08 대피소·산장 (LODGING_MOUNTAIN_SHELTER) [maki: shelter]   ← ADR-027 신설
    03.08.01 국립공원 대피소 (..._KNPS) [maki: shelter]    ← KNPS knps_shelters
    03.08.02 산림청 산장 (..._KFS) [maki: shelter]

04 온천·스파 (HOT_SPRING_SPA) [maki: hot-spring]
  04.01 온천 (HOT_SPRING_SPA_HOT_SPRING) [maki: hot-spring]
    04.01.01 온천시설 (..._FACILITY) [maki: hot-spring]
  04.02 찜질방·사우나 (HOT_SPRING_SPA_SAUNA) [maki: hot-spring]
    04.02.01 목욕장업 (..._BATHHOUSE) [maki: hot-spring]    ← MOIS public_baths
  04.03 스파·테라피 (HOT_SPRING_SPA_THERAPY) [maki: hot-spring]
    04.03.01 스파 (..._SPA) [maki: hot-spring]

05 편의 (CONVENIENCE) [maki: convenience]
  05.01 편의점 (..._STORE) [maki: convenience]
  05.02 은행 (..._BANK) [maki: bank]
  05.03 마트 (..._MART) [maki: grocery]
  05.04 슈퍼마켓 (..._SUPERMARKET) [maki: shop]
  05.05 백화점 (..._DEPARTMENT_STORE) [maki: clothing-store]
  05.06 공중화장실 (..._TOILET) [maki: toilet]

06 교통 (TRANSPORT) [maki: car]
  06.01 주차장 (TRANSPORT_PARKING) [maki: parking]    ← 표준데이터 parking_lots
  06.02 주유소 (TRANSPORT_FUEL) [maki: fuel]    ← OpiNet
  06.03 정류장 (TRANSPORT_STOP) [maki: bus]
    06.03.01 버스정류장 (..._BUS) [maki: bus]
    06.03.02 지하철역 (..._SUBWAY) [maki: rail-metro]
    06.03.03 기차역 (..._TRAIN) [maki: rail]
    06.03.04 택시승강장 (..._TAXI) [maki: taxi]
  06.04 휴게소 (TRANSPORT_REST_AREA) [maki: highway-rest-area]
    06.04.01 고속도로휴게소 (..._HIGHWAY) [maki: highway-rest-area]
      06.04.01.01 한국도로공사 휴게소 (..._EX) [maki: highway-rest-area]    ← KREX
  06.05 공항 (TRANSPORT_AIRPORT) [maki: airport]

07 의료 (MEDICAL) [maki: hospital]
  07.01 병원 (MEDICAL_HOSPITAL) [maki: hospital]
    07.01.01 종합병원 (..._GENERAL) [maki: hospital]
    07.01.02 의원 (..._CLINIC) [maki: doctor]
    07.01.03 치과 (..._DENTAL) [maki: dentist]
  07.02 약국 (MEDICAL_PHARMACY) [maki: pharmacy]
    07.02.01 일반 약국 (..._GENERAL) [maki: pharmacy]
```

### 4.3 표 형식 (전체 144 rows)

전체 표는 `src/kortravelmap/category/_definitions.py`의 `PLACE_CATEGORY_DEFINITIONS`
tuple에서 자동 생성된다 (ADR-023으로 본 라이브러리로 이전, PR#18). depth별
통계 (실측):

| depth | 건수 | 비고 |
|-------|----:|-----|
| 0 (sentinel) | 1 | `UNCLASSIFIED` |
| 1 (Tier 1 대분류) | 7 | `01 TOURISM` ~ `07 MEDICAL` — `00 UNCLASSIFIED`는 depth 0 sentinel로 분리 |
| 2 (Tier 2 중분류) | 34 | 원본 33 + ADR-027 `03.08 LODGING_MOUNTAIN_SHELTER` |
| 3 (Tier 3 소분류) | 73 | 원본 71 + ADR-027 `03.08.01/02` |
| 4 (Tier 4 세분류) | 29 | ADR-027에서 추가 없음 |
| **합계** | **144** | 원본 141 + ADR-027 신규 3 |

`PlaceCategoryTier1Code` enum은 `00 UNCLASSIFIED` 포함 **8개** (depth 0 +
depth 1 = 1 + 7). Tier 1 enum 자체는 ADR-027에서 변경 없음.

자세한 행별 표는 코드(`format_category_tree()` 출력) 또는 `tests/unit/test_category.py`
의 snapshot에 박는다 (코드 작성 단계 진입 시).

### 4.4 maki icon 분포

`PLACE_CATEGORY_MAPBOX_MAKI_ICONS` (57 unique icons → 144 rows):

> 본 표의 사용 코드 수는 손으로 유지하는 값이라 자동 생성 dict와 drift할 수
> 있다. 정확한 분포는 코드(`PLACE_CATEGORY_MAPBOX_MAKI_ICONS`)를 정본으로 본다.

| maki icon | 사용 코드 수 | 주 사용 카테고리 |
|-----------|------------:|-----------------|
| `park` | 12 | 휴양림 전체, 공원·광장, 트레킹 |
| `lodging` | 13 | 호텔/리조트/모텔/게스트하우스 |
| `shelter` | 3 | 대피소·산장 전체 (ADR-027, `03.08.*`) |
| `garden` | 7 | 수목원·식물원 전체 |
| `hot-spring` | 7 | 온천·스파 전체 |
| `campsite` | 7 | 캠핑장 전체 |
| `restaurant` | 7 | 한식/양식/중식/아시안/뷔페/parent |
| `museum` | 5 | 박물관 전체 + 문화시설 부모 |
| `cafe` | 5 | 카페 부모/커피전문점/디저트 등 |
| `information` | 4 | 관광안내 전체 |
| `home` | 4 | 펜션 전체 |
| `attraction` | 4 | TOURISM 부모, 체험형, 액티비티 부모 |
| `amusement-park` | 4 | 테마파크/놀이공원 |
| `highway-rest-area` | 3 | 휴게소 전체 |
| `natural` | 3 | 자연경관/폭포·동굴/자연명소 부모 |
| `art-gallery` | 3 | 미술관·갤러리 전체 |
| `theatre` | 3 | 공연장 전체 |
| `hospital` | 3 | 의료 부모, 병원 부모, 종합병원 |
| `pharmacy` | 2 | 약국 부모, 일반 약국 |
| `beach` | 2 | 해수욕장, 해안·섬 |
| `fast-food` | 2 | 패스트푸드, 분식 |
| `bakery` | 2 | 음식점 베이커리, 카페 베이커리 |
| `zoo` | 2 | 동물원·수족관 부모, 동물원 |
| `bus` | 2 | 정류장 부모, 버스정류장 |
| `rail` | 2 | 관광궤도, 기차역 |
| `monument` | 2 | 국가유산 부모, 사적·기념물 |
| `convenience` | 2 | 편의 부모, 편의점 |
| 기타 (1씩) | 29 | swimming, aquarium, mountain, water, viewpoint, cinema, library, town-hall, religious-buddhist, castle, village, golf, ferry, pitch, restaurant-sushi, bar, bank, grocery, shop, clothing-store, toilet, car, parking, fuel, rail-metro, taxi, airport, doctor, dentist, marker |

`PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES`는 정렬된 unique icon name tuple
(`("airport", "amusement-park", "aquarium", ...)` 형태).

### 4.5 본 라이브러리 provider별 주된 카테고리

| Provider / dataset | 매핑되는 카테고리 (대표) | docs reference |
|--------------------|-------------------------|----------------|
| `python-visitkorea-api` (축제) | (이벤트는 카테고리 외 — `EventDetail.event_kind`) | event-feature-etl.md |
| `python-mois-api` (식음 슬러그) | `02010100` ~ `02011000`, `02020100` (카페) | mois-feature-etl.md §6.1 |
| `python-mois-api` (숙박 슬러그) | `03010100`, `03050100`, `03050200`, `03060100`, `03060200`, `03070200` 등 | mois-feature-etl.md §6.1 |
| `python-mois-api` (관광 슬러그) | `01070100` 전통사찰, `01080300` 관광유람선, `01040100` 박물관 등 | mois-feature-etl.md §6.1 |
| `python-mois-api` (목욕장업) | `04020100` HOT_SPRING_SPA_SAUNA_BATHHOUSE | mois-feature-etl.md §6.1 |
| `python-opinet-api` | `06020000` TRANSPORT_FUEL | opinet-place-price-etl.md |
| `python-krex-api` (휴게소) | `06040101` TRANSPORT_REST_AREA_HIGHWAY_EX | krex-rest-area-feature-etl.md |
| `python-khoa-api` (해수욕장) | `01050100` TOURISM_NATURE_BEACH (전용 해수욕장 코드, DA-D-07 확정 2026-06-16) | khoa-beach-info-etl.md |
| `python-krheritage-api` | `01070100` ~ `01070400` (사찰/궁궐/사적/한옥) | krheritage-feature-etl.md |
| `python-krforest-api` (휴양림) | `03030000` LODGING_RECREATION_FOREST | forest-feature-etl.md |
| `python-krforest-api` (수목원) | `01030000` TOURISM_BOTANICAL | forest-feature-etl.md |
| `python-krforest-api` (숲길/탐방로) | `01020103` 산림욕장, `01080500` 트레킹 | forest-feature-etl.md |
| KNPS (data.go.kr, 후속) | `01020101` 국립공원 + 보조 (안내소/위험지역/화장실 등) | forest-feature-etl.md §11 |
| `data.go.kr-standard` (박물관) | `01040101` ~ `01040103` | standard-data-feature-etl.md |
| `data.go.kr-standard` (주차장) | `06010000` TRANSPORT_PARKING | standard-data-feature-etl.md |
| `data.go.kr-standard` (관광지) | `01000000` 트리 다양 (provider 매핑별) | standard-data-feature-etl.md |
| `data.go.kr-standard` (관광길) | route — `RouteDetail.route_type`으로 분류, category는 보조 | standard-data-feature-etl.md |
| 공중화장실 (후속) | `05060000` CONVENIENCE_TOILET | (별도 dataset) |
| `python-kma-api` (기상특보) | `99000000` sentinel (place 아님 — weather anchor) | kma-weather-etl.md |
| `python-airkorea-api` (대기질 측정소) | `99000000` sentinel (place 아님 — air-quality anchor) | airkorea-feature-etl.md |
| `python-krex-api` (교통 notice) | `99000000` sentinel (place 아님 — notice anchor) | notice-feature-etl.md |

위 매핑은 v2 1차 기준. 새 provider 추가 시 본 표 갱신 + ADR.

## 5. 의존 계층 위치

본 모듈은 의존 계층의 **최하단**이다 (다른 어떤 내부 모듈도 import 안 함):

```
kortravelmap.category   ← 본 모듈 (외부 의존: pydantic 또는 stdlib만)
  ↑
kortravelmap.dto        ← Feature.category 검증/정규화에서 import
  ↑
kortravelmap.core
  ↑
... (이하 ADR-002 계층)
```

`import-linter` 계약 (`pyproject.toml`)에 `kortravelmap.category`가 layered
contract의 가장 낮은 layer로 등록되어 있다 (ADR-023 §결정).

## 5. Feature.category 와의 연계

`dto/feature.py`의 `Feature.category`는 `str`로 저장되지만 `PlaceCategoryCode`
value로 정규화된다:

```python
from pydantic import BaseModel, Field, field_validator
from kortravelmap.category import (
    PlaceCategoryCode, is_known_category_code,
    PlaceCategory, get_category,
    mapbox_maki_icon_or_none,
)

class Feature(BaseModel):
    category: str = Field(min_length=1)
    # ...
    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value):
        if isinstance(value, PlaceCategoryCode):
            return value.value
        return str(value)

    @property
    def category_info(self) -> PlaceCategory | None:
        return get_category(self.category) if is_known_category_code(self.category) else None
```

`marker_icon` 자동 추론 helper (선택):

```python
def suggest_marker_icon(category_code: str) -> str | None:
    return mapbox_maki_icon_or_none(category_code)
```

## 6. 데이터 저장 위치

- **Python 상수**: `src/kortravelmap/category/__init__.py` (또는 `definitions.py` 분리)
  — `PLACE_CATEGORY_DEFINITIONS` tuple과 maki icon dict.
- **JSON/YAML 데이터 파일은 없다** — 모두 Python 상수로 박는다 (변경 시 PR
  diff가 명확).
- 변경은 ADR + 단위 테스트 + PR (ADR-021).

## 7. 라이선스와 derivation

- 본 모듈은 `python-kraddr-base` (GPL-3.0-or-later)의 `kraddr.base.categories`
  모듈을 derivation한다.
- `kor-travel-map`도 GPL-3.0-or-later → **호환**.
- 파일 상단 주석에 origin 표기:

```python
"""kortravelmap.category — 지도 marker용 카테고리 분류 + Mapbox Maki icon 매핑.

Origin: python-kraddr-base의 kraddr.base.categories 모듈 (GPL-3.0-or-later).
ADR-023 결정으로 본 저장소에 이전. 변경 이력은 git log 참조.
"""
```

- LICENSE / NOTICE: 본 저장소 LICENSE에 origin 참조 추가 (코드 작성 단계).

## 8. 단위 테스트 (이전 대상)

`tests/unit/test_category.py` (코드 작성 단계에서 추가):

- 144개 seed의 결정성: `PLACE_CATEGORY_DEFINITIONS` 길이 + `PLACE_CATEGORY_BY_CODE`
  key 집합 일치.
- `category_path("01050100")` → `("관광", "자연", "해변", ...)`
- `mapbox_maki_icon_for_category` fallback (unknown → "marker")
- `iter_categories(depth=2, active_only=True)` 필터 결과
- `is_known_category_code("99999999")` → False
- `format_category_tree(root_code="01")` 출력 형식 회귀
- property-based: `code in PLACE_CATEGORY_BY_CODE` ↔ `is_known_category_code(code)`

## 9. 이전 절차 (코드 작성 단계 진입 시)

별도 PR로 수행한다 (ADR-021):

1. `src/kortravelmap/category/__init__.py` 생성
   - `kraddr.base.categories`의 전 내용을 복사 + origin 주석 추가
   - import 경로 정리 (`from kraddr.base import ...` 같은 자기 참조 제거)
2. `tests/unit/test_category.py` 추가 (kraddr-base의 `test_categories.py` 포팅)
3. `dto/feature.py`의 import를 `from kortravelmap.category import ...`로 변경
4. `pyproject.toml`의 `dependencies`는 `python-kraddr-base`를 유지 — 단,
   category 외 (address/coordinate)만 사용한다는 주석 추가
5. `import-linter` 계약에 `kortravelmap.category`를 최하 layer로 등록
6. `docs/feature-model.md`의 category 부분을 본 모듈 import로 갱신
7. PR description에 ADR-023 링크 + kraddr-base 원본 commit sha 명기

## 10. kraddr-base 측 후속

- `python-kraddr-base`의 `kraddr.base.categories` 모듈은 그쪽 ADR로 deprecation
  또는 그대로 유지를 결정한다 — **본 저장소 책임 아님**.
- 본 저장소는 자체 copy를 정본으로 본다. kraddr-base에서 category 모듈이 변경
  되어도 자동 따라가지 않는다 (변경이 의미 있으면 ADR로 평가 후 cherry-pick).

## 11. 향후 확장 후보

- 카테고리 → 지역/계절 가중치 매핑 (TripMate 추천 시스템에서 사용 시).
- 다국어 라벨 (현재 한국어만 — i18n 도입 시 ko/en 분리).
- 사용자 정의 카테고리 (TripMate POI 도메인에 둘 가능성 있어 본 저장소는 표준
  카테고리만 책임).

위 확장은 ADR + PR로 진행.
