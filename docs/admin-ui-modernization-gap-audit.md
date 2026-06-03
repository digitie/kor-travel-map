# Admin UI 최신화 gap audit — T-211a/T-211b

작성일: 2026-06-03

## 목적

이 문서는 T-211b admin UI 최신화 구현 전에 필요한 선행 정리다. 기준 문서는
`docs/debug-ui-admin-workflows.md`, `docs/openapi-admin-contract.md`,
`packages/krtour-map-admin/frontend/README.md`이고, 실제 구현 기준은
`packages/krtour-map-admin/src/krtour/map_admin/routers/*`와
`packages/krtour-map-admin/frontend/src/api/*`다.

T-211a의 완료 기준은 다음 두 가지다.

1. 최신 문서가 요구하는 화면과 현재 REST/Dagster 계약의 차이를 명시한다.
2. T-211b 화면 구현이 바로 소비할 수 있는 TanStack Query API module을 먼저 준비한다.

## T-211a에서 보강한 frontend API module

| 파일 | 담당 계약 | 상태 |
|------|-----------|------|
| `src/api/features.ts` | `/features`, `/features/{feature_id}`, `/admin/features`, `/admin/features/{feature_id}/deactivate` | 기존 지도/상세 hook에 admin 목록/비활성화 mutation 추가 |
| `src/api/importJobs.ts` | `/ops/import-jobs`, `/ops/import-jobs/{job_id}` | 신규. 화면 route가 admin navigation 아래여도 backend 정본은 `/ops` |
| `src/api/ops.ts` | `/ops/metrics`, `/ops/consistency/reports`, `/ops/consistency/issues` | 신규. 홈/consistency 화면 공통 summary |
| `src/api/dedup.ts` | `/admin/dedup-review`, `/admin/dedup-review/{review_key}` | 신규. 결정 mutation 후 feature/ops cache 무효화 |
| `src/api/updateRequests.ts` | `/admin/feature-update-requests`, cancel, run-now | 신규. queue polling과 request detail polling 포함 |
| `src/api/poiCacheTargets.ts` | `/admin/poi-cache-targets`, `/features/nearby/by-target` | 신규. 외부 POI target CRUD와 target 기준 주변 feature 조회 |
| `src/api/dagster.ts` | `/ops/dagster/summary` | 기존 구현 유지. 공통 fetch wrapper 사용으로 정리 |

공통 fetch wrapper는 `src/api/client.ts`에서 `getJson`, `postJson`, `putJson`,
`patchJson`, `deleteJson`, `pathWithQuery`를 제공한다. 인증 헤더는 계속 없다
(ADR-005/035).

## Route별 구현 가능성

| UI route | T-211b 구현 가능성 | 사용할 API/hook | 남은 backend gap |
|----------|-------------------|-----------------|------------------|
| `/` | 가능 | `useOpsMetrics`, `useImportJobs`, `useDedupReviews`, `useDagsterSummary` | `/ops/error-logs`는 아직 없음. 홈의 provider 실패는 metrics/import job 실패 중심으로 표시 |
| `/features` | 가능 | `useAdminFeatures`, `useFeaturesInBbox`, `useFeatureDetail`, `useDeactivateAdminFeatureMutation` | 수동 feature 생성/영구 삭제는 후속 audit log/API 필요 |
| `/features/[feature_id]` | 부분 가능 | `useFeatureDetail` | 일반 좌표 기준 `/features/nearby` endpoint 없음. target 기반 주변 조회는 `/features/nearby/by-target`만 사용 가능 |
| `/ops/import-jobs` | 가능 | `useImportJobs`, `useImportJob` | job cancel, events, SSE stream endpoint 없음 |
| `/admin/dedup-review` | 가능 | `useDedupReviews`, `useDedupDecisionMutation` | decision 이유/작성자 UI validation만 프론트에서 보강 |
| `/ops/metrics` | 가능 | `useOpsMetrics` | 없음 |
| `/ops/consistency` | 가능 | `useConsistencyReports`, `useIntegrityIssues` | issue resolve/ignore mutation 없음 |
| `/admin/feature-update-requests` | 가능 | `useFeatureUpdateRequests`, create/cancel/run-now mutation | 실제 Dagster 실행 연결은 T-208e 구현분 사용. provider별 세부 rate-limit UI는 후속 |
| `/admin/poi-cache-targets` | 가능 | `usePoiCacheTargets`, `usePoiCacheTarget`, upsert/delete, `useNearbyFeaturesByTarget` | 없음 |
| `/admin/dagster` | 가능 | `useDagsterSummary`, `DAGSTER_UI_URL` iframe | Dagster NUX seen은 backend best-effort 처리. iframe 차단은 배포 환경 header 설정 영향 |
| `/admin/providers` | 보류 | 없음 | `/admin/providers*` REST 없음 |
| `/admin/provider-refresh-policies` | 보류 | 없음 | `/admin/provider-refresh-policies*` REST 없음 |
| `/admin/offline-imports` | 보류 | 없음 | T-208g에서 `ops.offline_uploads` + Dagster `offline_upload_load`, T-208b 후속에서 RustFS/S3 `offline_upload_store` resource 구현. `/admin/offline-uploads*` REST/UI, validation wizard, CSV/TSV mapping은 후속 |
| `/ops/error-logs` | 보류 | 없음 | `ops.import_job_events`, `/ops/error-logs` 미구현 |

## 문서 정정 사항

과거 문서에는 import job 화면을 `/admin/import-jobs`와 `/admin/import-jobs/{job_id}`로
표기한 부분이 남아 있었다. 현재 backend/OpenAPI 정본은
`/ops/import-jobs`, `/ops/import-jobs/{job_id}`다. Admin UI navigation 안에서는
Jobs 그룹으로 노출할 수 있지만, API module과 문서의 기본 API 표기는 `/ops`로 맞춘다.

또한 현재 구현된 주변 feature endpoint는 `/features/nearby/by-target`뿐이다.
일반 좌표 중심 `/features/nearby`는 문서의 초기 제안이었고 아직 REST 계약이 없다.
T-211b에서는 target 기반 화면에서만 주변 feature를 표시하고, feature 상세의 일반
주변 feature table은 별도 backend task 없이는 구현하지 않는다.

## T-211b 구현 결과

T-211b는 아래 범위를 구현했다.

- 전역 `AdminShell` navigation과 공통 상태/format helper.
- 운영 홈 dashboard: metrics, 최근 import jobs, backend/version, Dagster summary,
  dedup pending 카드.
- `/admin/dagster`: Dagster webserver embed 유지, asset groups/recent runs/
  schedules/sensors 자체 summary UI 보강.
- `/ops/import-jobs`: state/kind filter가 있는 read-only job table.
- `/ops/consistency`: metrics, consistency reports, integrity issue queue 조회.
- `/admin/dedup-review`: 상태 filter와 accepted/rejected/ignored 결정 mutation.
- `/admin/feature-update-requests`: center radius 기반 request 생성, dry-run,
  cancel, run-now, request 상태 목록.
- `/admin/poi-cache-targets`: 외부 POI target upsert/delete와 target 기준 주변 feature
  조회.
- `/features`: 기존 지도/테이블 workflow 유지, 운영 화면 quick link 추가.

Playwright e2e는 새 home dashboard와 신규 admin/ops route smoke 기준으로 갱신했다.
React Doctor는 exit code 0이며 남은 optional warning은 기존 shadcn/ui primitive 구조와
Dagster iframe sandbox rule false positive다.

## T-211b 우선 구현 순서 (완료 기준)

1. 전역 app shell/navigation을 최신 route matrix에 맞춘다.
2. 홈 dashboard를 `ops`/Dagster/import job/dedup summary 중심으로 교체한다.
3. `/admin/dagster`를 Dagster iframe + 자체 summary cards/tables/run list로 보강한다.
4. `/features`는 기존 map/table workflow를 유지하고 운영 화면 quick link를 추가한다.
5. `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
   `/admin/feature-update-requests`, `/admin/poi-cache-targets`를 신규 route로 추가한다.
6. React Doctor, ESLint, type-check, 필요한 Playwright e2e를 실행하고 결과를
   `docs/journal.md`와 PR 본문에 남긴다.
