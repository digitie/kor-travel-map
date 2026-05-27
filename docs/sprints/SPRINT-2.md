# SPRINT-2.md — MOIS-독립 작은 provider 4건 + 디버그 UI 첫 라우터

> **상태**: accepted (시기 대기 — Sprint 1 종료 후 Sprint 2 진입 PR)
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

### 2.1 Provider ① — 축제 (`data.go.kr-standard` 1차 + `python-visitkorea-api` enrichment, ADR-042)

**ADR-042 (2026-05-27)**로 1차 source 변경. 종전 visitkorea TourAPI 단독에서
**전국문화축제표준데이터** primary + visitkorea enrichment 패턴으로 전환.
**1차 source 함수 PR#34 (2026-05-27) merged**.

- **dataset_key**:
  - `datagokr_cultural_festivals` (1차, `data.go.kr-standard` via
    `python-datagokr-api`) — **PR#34 구현 완료**
  - `visitkorea_festival_events` (enrichment — image / 상세 description /
    contentId 매핑, `source_role='enrichment'`) — Sprint 2 끝물 별도 PR
- **Feature.kind**: `event`
- **detail**: `EventDetail` (festival_kind / event_dates / event_address)
- **category**: `01 TOURISM` 대분류 (festival 자체는 sub-category 없이 EventDetail
  에서 분기)
- **module**:
  - `src/krtour/map/providers/standard_data.py` — `cultural_festivals_to_bundles`
    (1차)
  - `src/krtour/map/providers/visitkorea.py` — `festival_to_enrichment_links`
    (enrichment, 2차 PR로)
- **함수 시그니처**:
  - `cultural_festivals_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list[FeatureBundle]`
- **fixture**: 5건 datagokr 표준데이터 (좌표 있음 3 + 좌표 nullable 2, ADR-019
  KST aware) + 2건 visitkorea enrichment fixture (Sprint 2 끝물 별도 PR).
- **EXPLAIN 검증**: bbox 검색 (`features_in_bounds`) + 시간 범위
  (`valid_start_time` BRIN).
- **`python-datagokr-api`**: `pyproject.toml` `[providers]` extra git URL 핀
  (Sprint 2 진입 시 추가, commit sha는 client 안정화 후 결정).

### 2.2 Provider ② — 날씨 (`python-kma-api` + 보조)

- **datasets**:
  - `kma_short_forecast` (단기예보, 3시간 단위, weather kind) — **PR#38 1차
    `short_forecast_to_weather_values` merged 2026-05-28**
  - `kma_ultra_short_nowcast` (초단기실황, 1시간 단위 관측) — **PR#39
    `ultra_short_nowcast_to_weather_values` merged 2026-05-28**
  - `kma_ultra_short_forecast` (초단기예보, 30분 단위 6시간) — **PR#41
    `ultra_short_forecast_to_weather_values` merged 2026-05-28**
  - `kma_mid_forecast` (중기예보, 일 단위) — 후속 PR
  - `kma_weather_alerts` (특보, notice kind, `notice_type='weather_alert'`
    등 기존 NOTICE_TYPES 사용) — 후속 PR
- **Feature.kind**: `weather` (단/초단/중) + `notice` (특보)
- **보조 (날씨 그룹에 같이, 후속 PR)**:
  - `python-airkorea-api` — `airkorea_air_quality` (PM10/PM2.5/CAI, kind=weather)
  - `python-krforest-api` 산악기상 — `krforest_mountain_weather` (kind=weather)
  - `python-khoa-api` 해양지수 — `khoa_coastal_observations` (kind=weather + notice)
- **module**:
  - `src/krtour/map/providers/kma.py` — PR#38 (`short_forecast_to_weather_
    values` + `KmaShortForecastItem` Protocol + KMA_METRIC_UNITS/NAMES 18종)
  - `src/krtour/map/providers/airkorea.py` (후속 PR)
  - `src/krtour/map/providers/krforest_weather.py` (후속 PR)
  - `src/krtour/map/providers/khoa_weather.py` (후속 PR)
- **fixture**: 3건/provider × 4 provider = 12건 (PR#38은 KMA 8 case 진입)
- **WeatherValue 표 검증**: `docs/weather-feature-normalization.md` §5 timeline
  bucket (nowcast / short / mid). PR#38로 `WeatherValue` DTO + 3 enum
  (`WeatherDomain`/`ForecastStyle`/`TimelineBucket`) + `make_weather_value_key`
  진입.

### 2.3 Provider ③ — 유가 (`python-opinet-api`)

- **dataset_key**: `opinet_fuel_station_details` (place + price)
- **Feature.kind**: `place` + `price` (PriceValue 시계열)
- **detail**: `PlaceDetail.place_kind='gas_station'`
- **category**: `06020000` `TRANSPORT_FUEL`
- **module**: `src/krtour/map/providers/opinet.py` — **PR#42 merged 2026-05-28**
- **함수**:
  - `prices_to_values(items, *, feature_id, source_record_key=None) -> list[PriceValue]` — **PR#42 구현 완료**
  - `stations_to_bundles(items, *, fetched_at, reverse_geocoder) -> list[FeatureBundle]` — 후속 PR (gas station feature)
- **DTO foundation** (PR#42): `dto/price.py` `PriceValue` + `PriceDomain`
  enum (5값: opinet_gas_station / rest_area_food / rest_area_fuel / toll_fee /
  admission_fee). `core/ids.py` `make_price_value_key` (`pv_{sha1[:20]}`).
- **OpiNet product code 매핑** (PR#42): B027/D047/B034/K015/C004 → gasoline/
  diesel/premium_gasoline/kerosene/lpg + 한글 이름.
- **검증**: BRIN 인덱스 (`price_values.observed_at`) ADR-014 + bulk insert
  `psycopg.copy_*` 안전 마진 30k (ADR-013) — 적재 PR에서 검증.
- **fixture**: 5건 (장유/일반/주유소 종류별) — PR#42에서 가격 시계열 8건
  진입.

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

### 2.5 디버그/관리 UI backend 첫 라우터 (ADR-031 + ADR-035 활성화)

ADR-035 (2026-05-27)로 운영 범위가 "디버그 + admin + 유지보수 + 프로덕션
운영"으로 확장. 라우터 prefix로 시각적 분리.

**PR#35 (2026-05-27, merged)** — 첫 두 라우터 + openapi.json drift gate 활성:
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/app.py` —
  `create_app(settings)` FastAPI factory + 모듈-레벨 `app` instance
- `settings.py` — `DebugUiSettings` (`KRTOUR_MAP_DEBUG_UI_*` env)
- `routers/health.py` — `GET /debug/health` (정적 200 OK, 의존 없음)
- `routers/version.py` — `GET /debug/version` (debug_ui + krtour_map version)
- `packages/krtour-map-debug-ui/openapi.json` commit (drift gate baseline)
- `.github/workflows/openapi.yml` `--check` drift gate active
  (`continue-on-error: true` 제거)
- `.github/workflows/ci.yml`에 debug-ui editable install + pytest step 추가
- pyproject `mypy_path = "src:packages/krtour-map-debug-ui/src"` (PEP 420
  namespace 통합)

**Sprint 2 후반 / Sprint 3 후속 라우터**:
- `routers/features.py` — `GET /features/in-bounds`, `/features/nearby`,
  `/features/{id}` (디버그 read) — `infra/feature_repo.py` raw SQL +
  Sprint 2 적재 후 의미 있는 응답
- `routers/admin_jobs.py` — `GET /admin/jobs`, `POST /admin/jobs/{id}/retry`
  (ADR-035) — `import_jobs` 테이블 + ADR-039 advisory lock 필요
- `routers/ops_consistency.py` — `GET /ops/consistency` (Sprint 3 ADR-033
  Phase 1 진입 시 활성)
- **frontend** (PR#36, 2026-05-27 merged — skeleton 진입):
  - Next.js 15 App Router + React 19 + maplibre-vworld (ADR-025) +
    **TanStack Query + Zustand (ADR-037)**
  - `src/api/{client,queries}.ts` — `useHealth` / `useVersion` hook 첫 통합
  - `src/state/map.ts` — Zustand map viewport store (lon/lat/zoom + 카테고리
    filter + 선택된 feature)
  - `src/providers/query-client-provider.tsx` — `QueryClientProvider`
  - `src/app/{layout,page.tsx}` — root + landing page (health/version smoke
    display)
  - `packages/map-marker-react/package.json` `"private": true` 박음 — ADR-043
    npm 게시 보류 (workspace 내부 git share만)
  - 실제 지도 + `/features/*` wiring은 후속 PR (`infra/feature_repo.py` +
    `routers/features.py` 진입 후)

### 2.6 Record Linkage scoring (첫 검증)

- `src/krtour/map/core/scoring.py` — ADR-016 가중치 0.45·name + 0.35·spatial
  + 0.20·category, 임계값 0.85/0.65
- 축제와 휴게소 간 dedup 비교는 거의 없음 — 휴게소 내부 (동일 휴게소
  방향별) sibling group 우선 검증.

### 2.7 `dto/` 100% branch (ADR-032)

- Sprint 2부터 `dto/` 모듈 coverage 100% branch (validator + Literal 분기
  + Pydantic field validation 전부).

### 2.8 신규 결정 사항 반영 (ADR-035~043, 2026-05-27)

Sprint 2 진행 중 다음 ADR들의 1차 implementation 점진 도입:

- **ADR-035** 운영 라우터 prefix 분리 (`/debug`/`/admin`/`/ops`) — §2.5 참조.
- **ADR-036** `maplibre-vworld-js` 라이브러리 분리 — frontend 본격 시작 시점
  검토, Sprint 3 후반 PR로 v0.1.0 release.
- **ADR-037** Frontend TanStack Query + Zustand — §2.5 frontend 옵션과 함께.
- **ADR-038** GitHub Actions CI/CD 재활성화 — Sprint 2 진입 직후 즉시
  branch protection rules 설정 (사용자 측 GitHub Settings).
- **ADR-042** datagokr 표준데이터 — §2.1 축제 1차 source 변경 반영.
- ADR-039 CLI mutex / ADR-040 Backup/Restore / ADR-041 kraddr-base 흡수는
  Sprint 4~5에 본격 implement (Sprint 2~3 prep 문서만).

### 2.9 Sprint 2 신규 산출물 추가 (요약)

| 항목 | 신규/변경 | 비고 |
|------|----------|------|
| `src/krtour/map/providers/standard_data.py` | 신규 | ADR-042 — `cultural_festivals_to_bundles` |
| `src/krtour/map/providers/visitkorea.py` | 신규 (역할 축소) | enrichment 변환 함수만 |
| `pyproject.toml` `[providers]` extra | 변경 | `python-datagokr-api` git URL 핀 추가 |
| `packages/krtour-map-debug-ui/src/.../routers/admin_jobs.py` | 신규 (옵션) | ADR-035 |
| `packages/krtour-map-debug-ui/frontend/package.json` | 변경 | `@tanstack/react-query` + `zustand` (ADR-037) |
| `packages/map-marker-react/package.json` | 변경 | `"private": true` (ADR-043) |
| `.github/workflows/*.yml` | 변경 (사용자 측) | branch protection 활성 (ADR-038) |

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
