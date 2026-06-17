# ADR-023: `python-kraddr-base`의 category 모듈을 `kortravelmap.category`로 이전

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: v1까지는 `python-kraddr-base`의 `kraddr.base.categories`
  (`PlaceCategory`, `PlaceCategoryCode`, `get_category`, `iter_categories`,
  `mapbox_maki_icon_for_category` 등 ~2,072 줄)를 의존성으로 import해 사용했다.
  사용자가 본 category 코드/문서를 `kor-travel-map`으로 이전하라고 지시.
  근거:
  - category 데이터(141 enum + maki icon 매핑)는 TripMate 지도 도메인에 직접
    종속 — `kor-travel-map`이 1차 소비자.
  - 다른 라이브러리(`kor-travel-geo` 등)는 category에 의존하지 않음 — 분리
    시 영향 없음.
  - kraddr-base는 주소/좌표/CRS 핵심에 집중되는 게 자연스럽다.
- **결정**:
  - `kraddr.base.categories` 모듈 전체를 본 저장소로 이전 → `kortravelmap.category`
    (top-level subpackage, 다른 `dto`/`core`/`infra`와 sibling).
  - 공개 식별자 (전부 그대로 유지):
    - `PlaceCategory`, `PlaceCategoryCode`, `PlaceCategoryTier1Code`
    - `PLACE_CATEGORY_DEFINITIONS`, `PLACE_CATEGORY_BY_CODE`,
      `PLACE_CATEGORY_CODES`, `PLACE_CATEGORY_TIER1_NAMES`,
      `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1`,
      `PLACE_CATEGORY_MAPBOX_MAKI_ICONS`, `PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES`
    - `get_category`, `is_known_category_code`, `iter_categories`,
      `category_path`, `category_label`,
      `mapbox_maki_icon_for_category`, `mapbox_maki_icon_or_none`,
      `format_category_tree`, `print_category_tree`
  - `dto/feature.py`의 `Feature.category` 검증·정규화는 `kortravelmap.category`를
    import해서 사용.
  - 의존 계층(`import-linter`)에 `kortravelmap.category`를 `dto`보다 낮은 계층
    으로 추가 (`category → dto → core → infra → providers → client → cli`).
  - `python-kraddr-base`는 `Address`, `PlaceCoordinate`, `AddressRegion`,
    `Wgs84Point`, CRS 상수 등 **주소/좌표/CRS만** 제공 (그쪽에서 category 모듈은
    별도 deprecation cycle을 두든 그대로 두든 그쪽 결정 — 본 저장소는 자체
    구현).
  - 라이선스: kraddr-base와 본 저장소 모두 GPL-3.0-or-later → 호환. 이전 시
    파일 상단에 derivation 주석 + LICENSE에 origin 표기.
  - 단위 테스트(141 seed 검증)도 함께 이전 (`tests/unit/test_category.py`).
- **근거**:
  - 단일 소비자 패턴 — 코드/데이터를 사용자 위치에 두는 게 응집도 높음.
  - kraddr-base의 책임 축소 (주소/좌표만).
  - 본 라이브러리의 의존 그래프에서 외부 dep 1개 제거 (kraddr-base는 여전히
    필요하지만 category 모듈은 자체 보유).
- **결과 (긍정)**:
  - category 변경이 본 저장소 PR 단위로 통제.
  - 추가 dep 제거 (kraddr-base의 category-only path 끊김).
- **결과 (부정)**:
  - 코드 중복(전환 기간) — kraddr-base가 이전 즉시 본 모듈을 폐기하지 않으면
    잠시 두 copy 존재. 본 저장소는 자체 copy를 정본으로 본다.
  - kraddr-base release 변경 시 본 저장소도 동기 release 검토.
- **후속**:
  - 실제 코드 이전은 **코드 작성 단계 진입 시** 수행 (현 단계는 docs/계약만).
    별도 PR로 `kortravelmap.category` 모듈 + 테스트 추가.
  - `docs/architecture/category.md` 신설 — 모듈 사양 + 라이선스/derivation 명기.
  - `docs/architecture/feature-model.md`, `docs/architecture/provider-contract.md`의 category 참조를
    `kortravelmap.category`로 갱신.
  - `pyproject.toml`의 `dependencies`에서 kraddr-base는 유지 (주소/좌표 사용
    중) — 단, category submodule은 본 저장소가 정본.
  - `python-kraddr-base`에 대한 category 폐기/유지 결정은 그쪽 저장소 ADR로
    분리.
