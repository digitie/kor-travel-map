# T-212a 전체점검 inventory + e2e gap matrix — 2026-06-06

## 1. 기준

- 기준 브랜치: `origin/main` after PR#247 (`T-209e-b` staging cold restore).
- 제외 범위: T-RV 계열은 별도 에이전트 백로그로 유지한다.
- 목적: 최신 코드 기준 route/API/job/sensor/schedule/resource/DB query/UI/e2e 표면을
  재분류하고, T-212b~e에서 바로 구현할 gap을 확정한다.

## 2. REST / OpenAPI inventory

| profile | path 수 | 핵심 표면 |
|---------|---------|-----------|
| admin OpenAPI | 43 | `/debug/*`, `/admin/*`, `/ops/*`, `/features/*`, `/tripmate/*`, public `/health`/`/version` |
| user OpenAPI | 13 | `/categories`, `/features/{search,in-bounds,nearby,weather}`, `/providers/{provider}/last-sync`, `/tripmate/*`, `/health`, `/version` |

### 구현된 admin/debug/ops route

| 영역 | 구현 상태 |
|------|-----------|
| debug | health/version, ETL provider/dataset/preview, MOIS detail |
| admin | features list/deactivate, dedup review, feature update requests, POI cache targets, offline uploads |
| ops | metrics, import jobs, consistency reports/issues, Dagster summary/NUX |
| user/TripMate | feature read/search/nearby/batch/weather, categories, provider last-sync, feature update request |

### API gap

| ID | 우선순위 | gap | 후속 |
|----|----------|-----|------|
| T-212c-API-01 | HIGH | admin 응답 envelope가 `{data, meta}`와 bare/list shape로 섞여 있다(T-DA-15/16). | T-212c |
| T-212c-API-02 | HIGH | `/admin/issues`가 없다. 현재 integrity issue는 `/ops/consistency/issues` 읽기 중심이다. | T-212b/c |
| T-209e-c-API | HIGH | `/admin/backups`, `/admin/restore/{backup_id}`, `/admin/restore/{backup_id}/swap` 미구현. | T-209e-c |
| T-212c-API-03 | MED | `/ops/health-deep`가 없다. public `/health`는 liveness로 DB-free 유지 중이다. | T-212c |
| T-212c-API-04 | MED | provider/API error log, system log, API call log 조회 표면이 아직 없다. | T-212c |

## 3. Frontend inventory

현재 Next.js route는 10개다.

| route | coverage |
|-------|----------|
| `/` | home e2e |
| `/features` | map/list smoke, kind filter, empty detail panel |
| `/etl` | ETL smoke |
| `/admin/dagster` | Dagster page smoke |
| `/admin/dedup-review` | admin/ops smoke |
| `/admin/feature-update-requests` | admin/ops smoke |
| `/admin/offline-uploads` | admin/ops smoke |
| `/admin/poi-cache-targets` | admin/ops smoke |
| `/ops/import-jobs` | admin/ops smoke |
| `/ops/consistency` | admin/ops smoke |

### UI gap

| ID | 우선순위 | gap | 후속 |
|----|----------|-----|------|
| T-212b-UI-01 | HIGH | `/admin/features` 화면이 없다. endpoint는 있지만 운영자용 table CRUD/detail/map review가 `/features` 지도 화면과 분리되어 있지 않다. | T-212b |
| T-212b-UI-02 | HIGH | `/admin/issues` 화면이 없다. integrity issue resolve/ignore/reopen workflow가 없다. | T-212b |
| T-209e-c-UI | HIGH | backup/restore/hot-swap UI가 없다. `T-209e-b` script 기반 staging restore를 운영 UI로 노출해야 한다. | T-209e-c |
| T-212b-UI-03 | MED | weather card는 API가 생겼지만 admin UI에서 feature detail/weather panel로 노출되지 않는다. | T-212b |
| T-212b-UI-04 | MED | offline upload e2e는 화면 smoke 중심이다. preview/validate/load happy path와 error path는 API unit 중심이다. | T-212b/e |
| T-212b-UI-05 | MED | POI cache target의 nearby result와 update request 생성 연계 e2e가 없다. | T-212b/e |

## 4. Dagster inventory

| 종류 | 구현 표면 |
|------|-----------|
| assets | festival, opinet stations, KREX rest areas/traffic, krheritage items/events, MOIS licenses, KNPS point/geometry |
| jobs | offline upload load, full load batch consistency gate, consistency/dedup refresh, feature update request worker |
| sensors | feature update request queue sensor, run failure sensor |
| schedules | provider asset materialization schedule, consistency/dedup maintenance schedule |
| resources | krtour-map client, offline upload store, provider live resource placeholders |

### Dagster gap

| ID | 우선순위 | gap | 후속 |
|----|----------|-----|------|
| T-212b-DAG-01 | MED | `/admin/dagster`는 summary/embed 중심이며 schedule/sensor tick history와 failure detail drilldown은 제한적이다. | T-212b |
| T-212c-DAG-01 | MED | run failure/system log를 krtour-map API 표면으로 조회하는 contract가 없다. | T-212c |
| T-212e-DAG-01 | MED | full reload 후 provider asset materialization 결과를 한 리포트로 묶는 검증 절차가 없다. | T-212e |

## 5. DB / 성능 inventory

현재 통합 테스트는 PostGIS migration, feature load/search/nearby, bbox clustering,
weather repo, provider sync state, feature update request, offline upload load,
consistency report, batch DAG, Dagster maintenance를 포함한다.

### 성능 gap

| ID | 우선순위 | gap | 후속 |
|----|----------|-----|------|
| T-212d-PERF-01 | HIGH | `/features/search`, `/features/in-bounds`, `/features/nearby`, `/admin/features`, import jobs, dedup refresh의 EXPLAIN baseline이 한 문서에 모여 있지 않다. | T-212d |
| T-212d-PERF-02 | MED | frontend table/map의 긴 목록 렌더링, hydration/console error, layout shift 측정 기록이 없다. | T-212d |
| T-212d-PERF-03 | MED | consistency F6/F8 같은 운영 점검 쿼리의 대량 데이터 비용 baseline이 없다. | T-212d |

## 6. E2E coverage matrix

| workflow | 현재 coverage | gap |
|----------|---------------|-----|
| home/navigation | `home.spec.ts` | 주요 admin route deep link 권한/404 smoke 없음 |
| feature map/list | `features.spec.ts` | search/nearby/weather detail interaction 부족 |
| ETL preview | `etl.spec.ts` | live provider credential 없는 failure UX만 부분 확인 |
| admin/ops tables | `admin-ops.spec.ts` | CRUD mutation happy/error path 대부분 API unit 중심 |
| Dagster page | `dagster.spec.ts` | sensor tick/failure detail drilldown 없음 |
| backup/restore | 없음 | T-209e-c에서 UI/API 추가 후 e2e 필요 |
| full reload | 없음 | T-212e에서 실데이터 리포트 필요 |

## 7. 다음 PR 추천 순서

1. **T-209e-c** — backup/restore admin router + hot-swap UI. `T-209e-b` staging restore
   script를 호출/감시하는 관리 표면을 만들고, destructive swap은 별도 명시 확인으로
   잠근다.
2. **T-212b-1** — `/admin/features` + feature detail/weather panel. 운영자 table CRUD와
   지도 화면을 분리한다.
3. **T-212b-2 / T-212c-1** — `/admin/issues` + integrity issue resolve/ignore/reopen API.
4. **T-212c-2** — admin envelope/error/log contract 정렬.
5. **T-212d** — EXPLAIN/React Doctor/Playwright 성능 baseline.
6. **T-212e** — DB 초기화 후 full reload + 실데이터 최종 검증 리포트.
