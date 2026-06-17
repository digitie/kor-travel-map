# ADR-027: forest 카테고리 확장 (대피소 PlaceCategory, hazard_zone area, 일반화된 notice_type)

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (notice_type 일반화)
- **컨텍스트**: `docs/etl/forest-feature-etl.md §11` (KNPS data.go.kr 통합)에서
  7건의 분류 확장 후보가 도출됨 (대피소 / 위험지역 / 산악관측소 / 식생서식지 /
  area_kind=hazard_zone / 입산통제 / 산불경보). 각 후보는 PlaceCategory /
  area_kind / notice_type 어디에 속하느냐, 위치가 어디여야 하느냐가 미정.
  코드 작성 단계 진입 전에 분류 정책을 박지 않으면 T-018(`python-knps-api`
  provider 등록) 시점에 매 케이스마다 재협상.

  사용자 결정 (2026-05-25): 입산통제/산불경보를 forest 도메인에 묶지 말고
  **일반화** — 산림(KNPS/산림청) 외 해변(KHOA), 도로(KREX), 도시(공사현장)
  등에서도 재사용 가능한 generic notice_type으로.

- **결정**:

  **A. 신규 PlaceCategory** — `LODGING_MOUNTAIN_SHELTER` 1건 (Tier 2 신설):

  | 코드 | enum name | 한국어 | maki icon |
  |------|-----------|--------|-----------|
  | `03080000` | `LODGING_MOUNTAIN_SHELTER` | 대피소·산장 | `shelter` |
  | `03080100` | `LODGING_MOUNTAIN_SHELTER_KNPS` | 국립공원 대피소 | `shelter` |
  | `03080200` | `LODGING_MOUNTAIN_SHELTER_KFS` | 산림청 산장 | `shelter` |

  - Tier 1 enum (`PlaceCategoryTier1Code`)은 그대로 8개 유지 — Tier 1 신설
    없음.
  - `03 LODGING` 하위 새 Tier 2 (휴양림 `03.03`과 의미 분리 — 휴양림은
    휴양 목적, 대피소는 안전/일시 휴식).
  - maki icon: `shelter` (Maki 표준에 존재).

  **B. 신규 `area_kind`** — `hazard_zone` 1건:

  ```python
  # AreaDetail.area_kind enum 확장 (feature-model.md §9)
  area_kind: Literal[
      "area", "national_park", "provincial_park", "recreation_forest",
      "tourism_district", "beach", "campsite", "heritage_area",
      "natural_heritage_area", "buried_heritage_area",
      "hazard_zone",                        # NEW (ADR-027)
      "other",
  ]
  ```

  - 위험지역(낙석/급류/멧돼지 출몰 등)은 시설(place)이 아닌 **지역(area)**.
    Feature `kind=area`, AreaDetail.area_kind=`'hazard_zone'` +
    `payload.hazard_type` (e.g. `'rockfall'`, `'flash_flood'`, `'wildlife'`)
    + polygon geometry.
  - 별도 PlaceCategory(`SAFETY_*` 또는 Tier 1 `08 SAFETY`) 신설 **하지
    않는다** (B-1 사용자 거부 사유: 새 Tier 1은 광범위 영향 — 모든 ETL/UI
    매핑 변경 필요, 위험지역은 area로 표현이 본질적으로 정확).

  **C. 신규 `notice_type`** — `access_restriction` + `fire_alert` 2건
  (**generic 명명**, 사용자 결정):

  ```python
  # docs/etl/notice-feature-etl.md §3 NOTICE_TYPES 확장
  NOTICE_TYPE_ACCESS_RESTRICTION = "access_restriction"   # NEW (ADR-027)
  NOTICE_TYPE_FIRE_ALERT         = "fire_alert"           # NEW (ADR-027)
  ```

  - `access_restriction`: 입산통제(KNPS) / 해수욕장 폐장(KHOA) / 공원 폐쇄
    / 공사 통제 / 등산로 통제 등 **출입 제한** 통칭.
  - `fire_alert`: 산불경보(KNPS/산림청) + 향후 화재 관련 일반 경보.
  - 명칭에서 `forest_` prefix 제거 — 산림 외 적용 가능. provider 출처/세부
    구분은 `payload`에 (`payload.domain='forest'`, `'beach'`, `'urban'` 등).
  - `normalize_notice_type` alias 추가:
    | 입력 | 출력 |
    |------|------|
    | `"입산통제"`, `"입산제한"`, `"forest_access"` | `access_restriction` |
    | `"해수욕장폐장"`, `"beach_closure"` | `access_restriction` |
    | `"공사구간"`, `"construction_zone"` | `access_restriction` (선택, road_closure와 구분) |
    | `"산불경보"`, `"forest_fire"`, `"fire"` | `fire_alert` |
    | `"화재경보"` | `fire_alert` |

  **D. 거부/연기**:

  - **`SAFETY_*` PlaceCategory 신설**: 거부 (B 결정으로 area_kind으로 대체).
  - **`WEATHER_MOUNTAIN_STATION` PlaceCategory 신설**: 거부. `kind=weather`
    feature 자체가 분류 역할 + meta `station_type='mountain'` 충분. 디버그
    UI에서 maki icon dispatch는 fallback `viewpoint` 또는 `observation-tower`
    매핑으로 처리.
  - **`NATURE_ECOLOGY` PlaceCategory 신설**: 연기 (v2 1차 범위 밖). 식생/
    서식지 학술 데이터는 TripMate 사용자 노출 가치 낮음. 향후 분석 도구에서
    KNPS 원본 dataset 직접 사용 권고.

- **근거**:
  - **kind 분리 정신 (feature-model.md)**: 시설은 place, 지역은 area, 안내는
    notice. SAFETY를 PlaceCategory에 넣는 건 이 정신 위배.
  - **Tier 1 변경 회피**: PlaceCategoryTier1Code는 enum + maki + 모든 ETL
    매핑 + 디버그 UI에 광범위 영향. Tier 2 추가는 한 행 추가로 마무리.
  - **generic notice_type**: 산림 외 도메인(해변/도로/도시)에서 동일 의미를
    표현해야 할 때 `forest_access_restriction`은 잘못된 이름. `payload.
    domain`으로 출처 구분이 정확.
  - **사용자 직접 결정 (일반화)**: 사용자가 forest prefix 제거를 명시
    지시 — provider별 prefix 없는 generic notice_type 패턴은 기존
    `road_closure` / `heavy_rain_warning` / `coastal_isolation` 등과
    일관.

- **결과 (긍정)**:
  - 대피소가 PlaceCategory로 명확히 분류 → 디버그 UI 마커 + 검색 필터 자연.
  - 위험지역이 area로 표현 → polygon geometry + radius 검색 자연 (place
    point보다 정확).
  - generic notice_type → 향후 새 provider(해변 폐장/도시 공사 등) 추가 시
    이름 재협상 0회.
  - Tier 1 enum 그대로 → 기존 매핑/디버그 UI 영향 0.

- **결과 (부정)**:
  - `LODGING_MOUNTAIN_SHELTER`는 03.03 (휴양림)과 인접 → "산림 시설" 묶음
    인지 차원에서 약간 혼동 여지. category.md에 의미 차이 명기로 완화.
  - `access_restriction`은 기존 `road_closure`와 의미 일부 겹침 — road_closure
    는 *도로*, access_restriction은 *지역/시설* 접근 제한. category.md /
    notice-feature-etl.md에 사용 가이드 명기.

- **후속**:
  - `docs/architecture/category.md` §4: `03.08` Tier 2 + Tier 3 두 행 추가 (Tier 1 표는
    변경 없음).
  - `docs/etl/notice-feature-etl.md` §3: `NOTICE_TYPE_ACCESS_RESTRICTION` /
    `NOTICE_TYPE_FIRE_ALERT` 추가 + `normalize_notice_type` alias 표 확장
    + §7 마커 스타일 표에 maki icon/color 추가.
  - `docs/architecture/feature-model.md` §9: AreaDetail.area_kind에 `hazard_zone` 추가.
  - `docs/architecture/data-model.md` §3: `feature_area_details.area_kind` CHECK 제약
    (있다면) 갱신.
  - `docs/etl/forest-feature-etl.md` §11.6: 본 ADR 링크 + Phase별 결정 사항으로
    정리 (현재의 "후보" 표 정리).
  - 코드 작성 단계에서:
    - `PLACE_CATEGORY_DEFINITIONS`에 3행 추가 + `PLACE_CATEGORY_MAPBOX_MAKI_ICONS`
      에 매핑.
    - `NOTICE_TYPES` tuple + `normalize_notice_type` validator + 마커
      스타일 helper 갱신.
    - `AreaDetail.area_kind` Literal 확장 + DB CHECK 제약 갱신 (alembic).
  - T-018 (`python-knps-api` provider 등록, ADR-028 후보)와 한 sprint
    안에서 함께 진행 권고.
