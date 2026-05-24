# category.md — `krtour.map.category` 모듈 사양

본 문서는 `krtour.map.category` 모듈의 사양 reference다. 해당 모듈은
`python-kraddr-base`의 `kraddr.base.categories` 모듈을 이전해 온 것이다 (ADR-023).

> **현재 상태**: v2 설계 단계. 본 문서는 모듈 사양을 박아두는 contract이며,
> 실제 코드 이전은 코드 작성 단계 진입 시 별도 PR로 수행한다 (ADR-023 §후속).

## 1. 목적

지도 marker용 카테고리 분류 + Mapbox Maki icon 매핑을 제공한다. TripMate 지도의
모든 marker는 이 카테고리 체계로 분류되고, frontend는 `marker_icon` (maki id) +
`marker_color` (`P-01` ~ `P-16`, v2 frontend 팔레트) 조합으로 렌더링한다.

## 2. import 경로

```python
from krtour.map.category import (
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

8자리 코드 `AABBCCDD` 형식. 총 141개 enum member.

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
| `PLACE_CATEGORY_DEFINITIONS` | `tuple[PlaceCategory, ...]` | 141개 정의 |
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
| `mapbox_maki_icon_for_category(code) -> str` | maki icon name, fallback `"marker"` |
| `mapbox_maki_icon_or_none(code) -> str \| None` | unknown 코드 시 None |
| `format_category_tree(root_code=None, include_codes=True, active_only=True) -> str` | 트리 문자열 |
| `print_category_tree(...)` | 위 결과 print |

## 4. 의존 계층 위치

본 모듈은 의존 계층의 **최하단**이다 (다른 어떤 내부 모듈도 import 안 함):

```
krtour.map.category   ← 본 모듈 (외부 의존: pydantic 또는 stdlib만)
  ↑
krtour.map.dto        ← Feature.category 검증/정규화에서 import
  ↑
krtour.map.core
  ↑
... (이하 ADR-002 계층)
```

`import-linter` 계약 (`pyproject.toml`)에 `krtour.map.category`가 layered
contract의 가장 낮은 layer로 등록되어 있다 (ADR-023 §결정).

## 5. Feature.category 와의 연계

`dto/feature.py`의 `Feature.category`는 `str`로 저장되지만 `PlaceCategoryCode`
value로 정규화된다:

```python
from pydantic import BaseModel, Field, field_validator
from krtour.map.category import (
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

- **Python 상수**: `src/krtour/map/category/__init__.py` (또는 `definitions.py` 분리)
  — `PLACE_CATEGORY_DEFINITIONS` tuple과 maki icon dict.
- **JSON/YAML 데이터 파일은 없다** — 모두 Python 상수로 박는다 (변경 시 PR
  diff가 명확).
- 변경은 ADR + 단위 테스트 + PR (ADR-021).

## 7. 라이선스와 derivation

- 본 모듈은 `python-kraddr-base` (GPL-3.0-or-later)의 `kraddr.base.categories`
  모듈을 derivation한다.
- `python-krtour-map`도 GPL-3.0-or-later → **호환**.
- 파일 상단 주석에 origin 표기:

```python
"""krtour.map.category — 지도 marker용 카테고리 분류 + Mapbox Maki icon 매핑.

Origin: python-kraddr-base의 kraddr.base.categories 모듈 (GPL-3.0-or-later).
ADR-023 결정으로 본 저장소에 이전. 변경 이력은 git log 참조.
"""
```

- LICENSE / NOTICE: 본 저장소 LICENSE에 origin 참조 추가 (코드 작성 단계).

## 8. 단위 테스트 (이전 대상)

`tests/unit/test_category.py` (코드 작성 단계에서 추가):

- 141개 seed의 결정성: `PLACE_CATEGORY_DEFINITIONS` 길이 + `PLACE_CATEGORY_BY_CODE`
  key 집합 일치.
- `category_path("01050100")` → `("관광", "자연", "해변", ...)`
- `mapbox_maki_icon_for_category` fallback (unknown → "marker")
- `iter_categories(depth=2, active_only=True)` 필터 결과
- `is_known_category_code("99999999")` → False
- `format_category_tree(root_code="01")` 출력 형식 회귀
- property-based: `code in PLACE_CATEGORY_BY_CODE` ↔ `is_known_category_code(code)`

## 9. 이전 절차 (코드 작성 단계 진입 시)

별도 PR로 수행한다 (ADR-021):

1. `src/krtour/map/category/__init__.py` 생성
   - `kraddr.base.categories`의 전 내용을 복사 + origin 주석 추가
   - import 경로 정리 (`from kraddr.base import ...` 같은 자기 참조 제거)
2. `tests/unit/test_category.py` 추가 (kraddr-base의 `test_categories.py` 포팅)
3. `dto/feature.py`의 import를 `from krtour.map.category import ...`로 변경
4. `pyproject.toml`의 `dependencies`는 `python-kraddr-base`를 유지 — 단,
   category 외 (address/coordinate)만 사용한다는 주석 추가
5. `import-linter` 계약에 `krtour.map.category`를 최하 layer로 등록
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
