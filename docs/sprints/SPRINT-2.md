# SPRINT-2.md — MOIS-독립 작은 provider 4건 + 디버그 UI 첫 라우터

> **상태**: proposed (Sprint 1 종료 후 Sprint 2 진입 PR로 accepted 전환)
>
> **목적**: ADR-034 9단계의 ①~④ — 축제 / 날씨 / 유가 / 휴게소. MOIS와 dedup
> 가능성 없는 작은 dataset부터 적재해 Record Linkage 룰을 검증한다. 디버그
> UI backend 첫 라우터로 ADR-031 OpenAPI export drift gate 활성화.

## 1. 진입 조건 (Sprint 1 DoD)

- [ ] Sprint 1 모든 DoD 충족 (`SPRINT-1.md §7`)
- [ ] `src/krtour/map/` scaffolding (`__init__.py`, `category/`, `dto/`,
      `core/`, `infra/`, `providers/`, `client/`, `settings.py`)
- [ ] `category/` 144건 (`PLACE_CATEGORY_DEFINITIONS` + maki + helpers)
- [ ] ADR-030 `import-linter` 계약 green
- [ ] Coverage bar 50% pass
- [ ] testcontainers PostGIS infra green

## 2. 산출물

### 2.1 Provider ① — 축제 (`python-visitkorea-api`)

- **dataset_key**: `visitkorea_festival_events`
- **Feature.kind**: `event`
- **detail**: `EventDetail` (festival_kind / event_dates / event_address)
- **category**: `01 TOURISM` 대분류 (festival 자체는 sub-category 없이 EventDetail
  에서 분기)
- **module**: `src/krtour/map/providers/visitkorea.py`
- **함수**:
  - `festival_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list[FeatureBundle]`
- **fixture**: 5건 (좌표 있음 3 + 좌표 nullable 2, ADR-019 KST aware)
- **EXPLAIN 검증**: bbox 검색 (`features_in_bounds`) + 시간 범위
  (`valid_start_time` BRIN)

### 2.2 Provider ② — 날씨 (`python-kma-api` + 보조)

- **datasets**:
  - `kma_short_forecast` (단기예보, 3시간 단위, weather kind)
  - `kma_ultra_short_nowcast` (초단기실황, 분 단위)
  - `kma_mid_forecast` (중기예보, 일 단위)
  - `kma_weather_alerts` (특보, notice kind, `notice_type='weather_alert'`
    등 기존 NOTICE_TYPES 사용)
- **Feature.kind**: `weather` (단/초단/중) + `notice` (특보)
- **보조 (날씨 그룹에 같이)**:
  - `python-airkorea-api` — `airkorea_air_quality` (PM10/PM2.5/CAI, kind=weather)
  - `python-krforest-api` 산악기상 — `krforest_mountain_weather` (kind=weather)
  - `python-khoa-api` 해양지수 — `khoa_coastal_observations` (kind=weather + notice)
- **module**:
  - `src/krtour/map/providers/kma.py`
  - `src/krtour/map/providers/airkorea.py`
  - `src/krtour/map/providers/krforest_weather.py`
  - `src/krtour/map/providers/khoa_weather.py`
- **fixture**: 3건/provider × 4 provider = 12건
- **WeatherValue 표 검증**: `docs/weather-feature-normalization.md` §5 timeline
  bucket (nowcast / short / mid)

### 2.3 Provider ③ — 유가 (`python-opinet-api`)

- **dataset_key**: `opinet_fuel_station_details` (place + price)
- **Feature.kind**: `place` + `price` (PriceValue 시계열)
- **detail**: `PlaceDetail.place_kind='gas_station'`
- **category**: `06020000` `TRANSPORT_FUEL`
- **module**: `src/krtour/map/providers/opinet.py`
- **함수**:
  - `stations_to_bundles(items, *, fetched_at, reverse_geocoder) -> list[FeatureBundle]`
  - `prices_to_values(items, *, fetched_at) -> list[PriceValue]`
- **검증**: BRIN 인덱스 (`price_values.observed_at`) ADR-014 + bulk insert
  `psycopg.copy_*` 안전 마진 30k (ADR-013)
- **fixture**: 5건 (장유/일반/주유소 종류별)

### 2.4 Provider ④ — 휴게소 (`python-krex-api`)

- **datasets**:
  - `krex_rest_areas` (place, 카테고리 `06040101` `TRANSPORT_REST_AREA_HIGHWAY_EX`)
  - `krex_rest_area_prices` (price 시계열)
  - `krex_rest_area_weather` (weather)
  - `krex_traffic_notices` (notice)
- **Feature.kind**: `place` + `price` + `weather` + `notice` — **multi-kind
  검증**
- **module**: `src/krtour/map/providers/krex.py`
- **fixture**: 6건 (휴게소 2 + 가격 2 + weather 1 + notice 1)
- **provider 자체에 4 kind**: 본 라이브러리에서 multi-kind FeatureBundle을
  올바르게 처리하는지 통합 테스트 베이스.

### 2.5 디버그 UI backend 첫 라우터 (ADR-031 활성화)

- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/app.py` 신설
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/routers/`:
  - `health.py` — `/health`
  - `version.py` — `/version`
  - `features.py` — `/features/in-bounds`, `/features/nearby`, `/features/{id}`
- `packages/krtour-map-debug-ui/scripts/export_openapi.py` 실효 가동
- `packages/krtour-map-debug-ui/openapi.json` 저장소 commit
- `.github/workflows/openapi.yml` `--check` drift gate green
- (frontend 코드는 별도 Sprint 또는 Sprint 2 끝 옵션)

### 2.6 Record Linkage scoring (첫 검증)

- `src/krtour/map/core/scoring.py` — ADR-016 가중치 0.45·name + 0.35·spatial
  + 0.20·category, 임계값 0.85/0.65
- 축제와 휴게소 간 dedup 비교는 거의 없음 — 휴게소 내부 (동일 휴게소
  방향별) sibling group 우선 검증.

### 2.7 `dto/` 100% branch (ADR-032)

- Sprint 2부터 `dto/` 모듈 coverage 100% branch (validator + Literal 분기
  + Pydantic field validation 전부).

## 3. Sprint 2 ADR/T 항목 진척

| 항목 | 상태 (진입 시) | DoD (Sprint 2 종료) |
|------|---------------|---------------------|
| ADR-031 (OpenAPI export) | accepted (Sprint 1) | drift gate green + frontend `gen:types` 대상 spec |
| ADR-016 (Record Linkage) | accepted | scoring 함수 + 4 provider 통합 테스트 |
| ADR-013 (bulk insert 30k) | accepted | opinet price BRIN bulk 적재 검증 |
| ADR-019 (KST aware datetime) | accepted | 4 provider 모두 naive datetime ValidationError |

## 4. Coverage 목표 (ADR-032 Sprint 2)

| 계층 | Sprint 2 bar |
|------|------|
| 전체 (branch) | 65% |
| `core/` | 75% |
| `providers/` | 55% |
| `infra/`/`client/`/`api/` | 60% |
| `dto/` | **100% branch (항상)** |

## 5. 비목표 (Sprint 2)

- KNPS / krheritage provider (Sprint 3)
- MOIS provider (Sprint 4)
- 휴양림/수목원 / 박물관 (Sprint 5)
- `feature_consistency_reports` 스키마 (Sprint 3, ADR-033 Phase 1)
- dedup_review_queue 운영 (Sprint 4 MOIS 진입 후)
- materialize view / pg_prewarm / streaming (T-101/102/103)

## 6. 위험 / 차단 사유

- **provider rate limit**: KMA / OpiNet은 분당 한도 있음. `ConcurrencyConfig`
  TripMate 측, 본 라이브러리는 page 단위 sleep만 ETL doc에 명기.
- **좌표 nullable**: visitkorea festival은 좌표 없는 경우 다수. 좌표 없는
  feature는 적재하되 `coord_5179`는 NULL → `features_in_bounds` 쿼리에서
  자연히 제외.

## 7. 종료 조건 (Sprint 2 → Sprint 3)

- [ ] Provider ①~④ 모듈 + fixture + 통합 테스트 모두 merge
- [ ] 디버그 UI backend 첫 라우터 + OpenAPI drift gate green
- [ ] Coverage bar 65% pass
- [ ] `docs/journal.md` Sprint 2 종료 회고 entry
- [ ] `docs/resume.md` "다음 한 작업" → Sprint 3 진입 갱신
- [ ] `docs/sprints/SPRINT-3.md` 진입 PR 준비
