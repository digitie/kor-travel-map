# SPRINT-2.md — MOIS-독립 작은 provider 4건 + 디버그 UI 첫 라우터

> **상태**: ✅ **완료 (2026-05-26~28)** — provider ①~④ + 디버그 UI 라우터
> + visitkorea enrichment + KMA mid_forecast + **ETL live 11/11 dataset 전부
> wiring** + coverage bar 65 상향 (PR#59). (PR#28~#59 merged.) Sprint 3 진입.
>
> **목적**: ADR-034 9단계의 ①~④ — 축제 / 날씨 / 유가 / 휴게소. MOIS와 dedup
> 가능성 없는 작은 dataset부터 적재해 Record Linkage 룰을 검증한다. 디버그
> UI backend 첫 라우터로 ADR-031 OpenAPI export drift gate 활성화.

## 1. 진입 조건 (Sprint 1 DoD) — ✅ 충족 (PR#27 종료)

- [x] Sprint 1 모든 DoD 충족 (`SPRINT-1.md §7`)
- [x] `src/kortravelmap/` scaffolding (`__init__.py`, `category/`, `dto/`,
      `core/`, `infra/`, `providers/`, `client/`, `settings.py`)
- [x] `category/` 144건 (`PLACE_CATEGORY_DEFINITIONS` + maki + helpers)
- [x] ADR-030 `import-linter` 계약 green
- [x] Coverage bar 50% pass
- [x] testcontainers PostGIS infra green

## 2. 산출물

### 2.1 Provider ① — 축제 (`data.go.kr-standard` 1차 + `python-visitkorea-api` enrichment, ADR-042)

**ADR-042 (2026-05-27)**로 1차 source 변경. 종전 visitkorea TourAPI 단독에서
**전국문화축제표준데이터** primary + visitkorea enrichment 패턴으로 전환.
**1차 source 함수 PR#34 (2026-05-27) merged**.

- **dataset_key**:
  - `datagokr_cultural_festivals` (1차, `data.go.kr-standard` via
    `python-datagokr-api`) — **PR#34 구현 완료**
  - `visitkorea_festival_events` (enrichment — image / 상세 description /
    contentId 매핑, `source_role='enrichment'`) — **PR#51 구현 완료**
    (`festival_to_enrichment_links` + `FestivalMatcher` plug-in)
- **Feature.kind**: `event`
- **detail**: `EventDetail` (festival_kind / event_dates / event_address)
- **category**: `01 TOURISM` 대분류 (festival 자체는 sub-category 없이 EventDetail
  에서 분기)
- **module**:
  - `src/kortravelmap/providers/standard_data.py` — `cultural_festivals_to_bundles`
    (1차)
  - `src/kortravelmap/providers/visitkorea.py` — `festival_to_enrichment_links`
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
  - `kma_mid_forecast` (중기예보, 일 단위) — **PR#52 구현 완료**
    (`mid_land_forecast_to_weather_values` 텍스트 SKY + POP, AM/PM split +
    `mid_temperature_to_weather_values` TMN/TMX)
  - `kma_weather_alerts` (특보, notice kind, region 단위 fan-out) — **PR#46
    `weather_alerts_to_notice_bundles` merged 2026-05-28**
- **Feature.kind**: `weather` (단/초단/중) + `notice` (특보)
- **보조 (날씨 그룹에 같이, 후속 PR)**:
  - `python-airkorea-api` — `airkorea_air_quality` (PM10/PM2.5/CAI, kind=weather)
  - `python-krforest-api` 산악기상 — `krforest_mountain_weather` (kind=weather)
  - `python-khoa-api` 해양지수 — `khoa_coastal_observations` (kind=weather + notice)
- **module**:
  - `src/kortravelmap/providers/kma.py` — PR#38 (`short_forecast_to_weather_
    values` + `KmaShortForecastItem` Protocol + KMA_METRIC_UNITS/NAMES 18종)
  - `src/kortravelmap/providers/airkorea.py` (후속 PR)
  - `src/kortravelmap/providers/krforest_weather.py` (후속 PR)
  - `src/kortravelmap/providers/khoa_weather.py` (후속 PR)
- **fixture**: 3건/provider × 4 provider = 12건 (PR#38은 KMA 8 case 진입)
- **WeatherValue 표 검증**: `docs/etl/weather-feature-normalization.md` §5 timeline
  bucket (nowcast / short / mid). PR#38로 `WeatherValue` DTO + 3 enum
  (`WeatherDomain`/`ForecastStyle`/`TimelineBucket`) + `make_weather_value_key`
  진입.

### 2.3 Provider ③ — 유가 (`python-opinet-api`)

- **dataset_key**: `opinet_fuel_station_details` (place + price)
- **Feature.kind**: `place` + `price` (PriceValue 시계열)
- **detail**: `PlaceDetail.place_kind='gas_station'`
- **category**: `06020000` `TRANSPORT_FUEL`
- **module**: `src/kortravelmap/providers/opinet.py` — **PR#42 merged 2026-05-28**
- **함수**:
  - `prices_to_values(items, *, feature_id, source_record_key=None) -> list[PriceValue]` — **PR#42 구현 완료**
  - `stations_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list[FeatureBundle]` — **PR#43 구현 완료** (gas station Feature(kind=place, category="06020000") + PlaceDetail(place_kind="gas_station") + SourceRecord + SourceLink)
- **DTO foundation** (PR#42): `dto/price.py` `PriceValue` + `PriceDomain`
  enum (5값: opinet_gas_station / rest_area_food / rest_area_fuel / toll_fee /
  admission_fee). `core/ids.py` `make_price_value_key` (`pv_{sha1[:20]}`).
- **OpiNet product code 매핑** (PR#42): B027/D047/B034/C004/K015 → gasoline/
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
- **module**: `src/kortravelmap/providers/krex.py` — **PR#45 merged 2026-05-28**
- **함수** (PR#45 구현 완료):
  - `rest_areas_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list[FeatureBundle]` (place)
  - `rest_area_prices_to_values(items, *, feature_id, source_record_key=None) -> list[PriceValue]` (food/fuel 분기)
  - `rest_area_weather_to_values(items, *, feature_id, source_record_key=None) -> list[WeatherValue]` (forecast_style=observed)
  - `traffic_notices_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list[FeatureBundle]` (notice + NoticeDetail + normalize_notice_type alias)
- **fixture**: 8건 (휴게소 2 + 가격 2 + weather 2 + notice 2) — PR#45 tests
  18 case
- **provider 자체에 4 kind**: 본 라이브러리에서 multi-kind를 올바르게 처리
  하는지 통합 검증 완료 — `multi_kind_pipeline_uses_same_feature_id` test로
  rest_areas → prices/weather 동일 feature_id 흐름 검증.

### 2.5 디버그/관리 UI backend 첫 라우터 (ADR-031 + ADR-035 활성화)

ADR-035 (2026-05-27)로 운영 범위가 "디버그 + admin + 유지보수 + 프로덕션
운영"으로 확장. 라우터 prefix로 시각적 분리.

**PR#35 (2026-05-27, merged)** — 첫 두 라우터 + openapi.json drift gate 활성:
- `packages/kor-travel-map-api/src/kortravelmap/api/app.py` —
  `create_app(settings)` FastAPI factory + 모듈-레벨 `app` instance
- `settings.py` — `ApiSettings` (`KOR_TRAVEL_MAP_API_*` env)
- `routers/health.py` — `GET /debug/health` (정적 200 OK, 의존 없음)
- `routers/version.py` — `GET /debug/version` (debug_ui + kor_travel_map version)
- `packages/kor-travel-map-api/openapi.json` commit (drift gate baseline)
- `.github/workflows/openapi.yml` `--check` drift gate active
  (`continue-on-error: true` 제거)
- `.github/workflows/ci.yml`에 API 패키지 editable install + pytest step 추가
- pyproject `mypy_path = "src:packages/kor-travel-map-api/src"` (PEP 420
  namespace 통합)

**PR#44 (2026-05-28, merged)** — ETL preview 라우터 (`?source=fixture` 활성):
- `routers/etl.py` 3 endpoint (`/debug/etl/providers`/`{provider}/datasets`/
  `{provider}/{dataset}/preview`) + `etl_fixtures.py` registry (PR#46까지
  11 dataset). DB write 없음 — provider raw → DTO 변환 수동 trigger.
- frontend `src/app/etl/page.tsx` — provider/dataset 선택 + Preview 실행
  + JSON 결과 표시.

**PR#47 (2026-05-28, merged)** — ETL preview `?source=live` 활성화 + 8
provider API key 설정:
- `src/kortravelmap/admin/etl_live.py` 신설 (`LiveLoader` + `LIVE_LOADER_
  REGISTRY` + KMA 3 endpoint async httpx wrapper + base_date/base_time 자동
  계산 + Protocol-만족 dataclass adapter).
- KMA 3 dataset (`kma_short_forecast` / `kma_ultra_short_nowcast` / `kma_
  ultra_short_forecast`) **활성** — 실 호출 + 변환 통과.
- 나머지 8 dataset (datagokr 1 + kma_weather_alerts 1 + opinet 2 + krex 4)
  framework 등록만 — 미등록 시 `501 Not Implemented`.
- `settings.py` 8 `SecretStr | None` field 추가 (kma/opinet/datagokr/
  visitkorea/krex/knps/airkorea/krforest).
- 서비스 키 컨벤션: 각 provider repo `.env`의 키 이름 그대로 + prefix
  `KOR_TRAVEL_MAP_API_`만 붙여 디버그 UI `.env`에 옮긴다. 예: `python-kma-
  api/.env`의 `KMA_SERVICE_KEY=...` → 디버그 UI의 `KOR_TRAVEL_MAP_API_KMA_
  SERVICE_KEY=...`.
- `.env.example` (8 key 자리 + 컨벤션 주석) 신설. `pyproject.toml`
  `httpx>=0.27` 추가.
- 응답 매핑: 404 (FIXTURE_REGISTRY 미등록) / 501 (LIVE_LOADER_REGISTRY
  미등록) / 503 (API key 미설정 — `.env` 확인) / 502 (provider 외부 API 실패).
- `openapi.json` drift gate 재생성 (`_DatasetEntry.live_supported: bool` +
  502/503 응답 추가).

**Sprint 2 후반 / Sprint 3 후속 라우터**:
- `routers/features.py` — `GET /features/in-bounds`, `/features/nearby`,
  `/features/{id}` (디버그 read) — `infra/feature_repo.py` raw SQL +
  Sprint 2 적재 후 의미 있는 응답
- `routers/admin_jobs.py` — `GET /admin/jobs`, `POST /admin/jobs/{id}/retry`
  (ADR-035) — `import_jobs` 테이블 + ADR-039 advisory lock 필요
- `routers/ops_consistency.py` — `GET /ops/consistency` (Sprint 3 ADR-033
  Phase 1 진입 시 활성)
- ETL preview live mode 확장 — 나머지 8 dataset (datagokr/opinet 2/krex 4/
  kma_weather_alerts) live loader 등록.
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

- `src/kortravelmap/core/scoring.py` — ADR-016 가중치 0.45·name + 0.35·spatial
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
| `src/kortravelmap/providers/standard_data.py` | 신규 | ADR-042 — `cultural_festivals_to_bundles` |
| `src/kortravelmap/providers/visitkorea.py` | 신규 (역할 축소) | enrichment 변환 함수만 |
| `pyproject.toml` `[providers]` extra | 변경 | `python-datagokr-api` git URL 핀 추가 |
| `packages/kor-travel-map-api/src/.../routers/admin_jobs.py` | 신규 (옵션) | ADR-035 |
| `packages/kor-travel-map-admin/frontend/package.json` | 변경 | `@tanstack/react-query` + `zustand` (ADR-037) |
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

**완료**:
- [x] Provider ①~④ 핵심 변환 함수 + fixture + 단위 테스트 merge
      (datagokr PR#34 / kma PR#38·39·41·46 / opinet PR#42·43 / krex PR#45)
- [x] 디버그 UI backend 첫 라우터 (health/version/etl) + OpenAPI drift gate green
      (PR#35·44·47)
- [x] Coverage bar 65% pass — **실측 96%** (`fail_under` 상향은 잔여 작업 4에서)

**잔여 (Sprint 2 종료 게이트)**:
- [x] 1. visitkorea enrichment — `providers/visitkorea.py`
      `festival_to_enrichment_links` + `FestivalMatcher` plug-in (PR#51, 8 test)
- [x] 2. KMA 중기예보 — `mid_land_forecast_to_weather_values`(SKY 텍스트 + POP,
      AM/PM split) + `mid_temperature_to_weather_values`(TMN/TMX) (PR#52, 11 test)
- [x] 3. ETL live 나머지 8 dataset loader 등록 (`etl_live.LIVE_LOADER_REGISTRY`)
      — **provider repo 로컬(`F:\dev\`) 기준 정확히 wiring** (ADR-044). 8종 전부
      완료 → **11/11 fixture dataset 전부 live 지원**:
      - [x] krex 4 (rest_areas/prices/weather/traffic_notices) — PR#55
        (EX OpenAPI, 순수 adapter + 14 단위 test).
      - [x] opinet 2 (station/prices) — PR#56 (detailById.do `?id=`, KATEC→WGS84
        reproject via 로컬 coords.py proj, 순수 adapter + 10 단위 test).
      - [x] datagokr 1 (cultural_festivals) — PR#57 (로컬 `python-datagokr-api`
        `tn_pubr_public_cltur_fstvl_api`, alias 매핑 + 7 단위 test).
      - [x] kma_weather_alerts 1 — PR#58 (apihub `wrn_now_data` text → 특보구역
        (REG_ID) 단위 행, WRN 코드→notice_type 매핑, 순수 parser/adapter + 8
        단위 test). apihub `authKey`는 data.go.kr serviceKey와 별개 →
        `kma_apihub_key` settings 추가. 컬럼 헤더 표기는 실 응답 후속 검증.
- [x] 4. `pyproject.toml` `fail_under` 50 → 65 상향 (실측 96%라 무위험) +
      `docs/journal.md` Sprint 2 종료 회고 + `docs/resume.md` → Sprint 3 진입 +
      `docs/sprints/SPRINT-3.md` 진입 active + `sprints/README.md` 상태 (PR#59).

> **`/features/*` 라우터 + `infra/feature_repo.py`는 Sprint 2 종료 게이트가
> 아니다** (§2.5 명시 — Sprint 2 후반/Sprint 3 후속). 실제 DB 적재·조회 흐름은
> Sprint 3에서 첫 provider 적재와 함께 연결.
