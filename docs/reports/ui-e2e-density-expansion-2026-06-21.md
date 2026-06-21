# UI e2e 테스트 3배 확장

## 범위

- 대상: `packages/kor-travel-map-admin/frontend/e2e`
- 기존 전체 Playwright e2e: 209 tests
- 확장 후 전체 Playwright e2e: 631 tests
- 증가분: 422 tests

## 추가 파일

- `home-density-matrix.spec.ts`

## 커버리지 보강 축

- 공용 `AdminShell` nav 18개 항목:
  - desktop/mobile visible
  - exact href
  - icon 존재
  - same-tab 링크 정책
  - accessible name uniqueness
  - 내부 path 정책
  - 390/768/1440 viewport 유지
- 홈 화면 운영 metric:
  - feature total/active/inactive count 포맷
  - import job status 합산
  - dedup queue count/pending 설명
  - data integrity issue open count
- 홈 import job summary table:
  - queued/running/done/failed/cancelled/blocked status
  - progress/kind/status/progress column 유지
- 홈 dedup pending:
  - 후보명 조합
  - score rounding
  - `/admin/dedup-reviews` 링크
  - empty state
- Backend/Dagster 상태 카드:
  - admin/map version badge
  - Dagster `ok`/`unavailable`/`error` enum
  - assets/schedules count 포맷
- 실패/복구 정책:
  - health/metrics/dagster/importJobs 실패 시 HTTP status 노출
  - dedup/version 실패 시 shell 유지 및 비노출 정책
  - 새로고침 버튼의 6개 endpoint refetch

## 검증

- `npm run type-check:e2e` → passed
- `npx playwright test e2e/home-density-matrix.spec.ts --workers=1 --reporter=list`
  → 422 passed
- `npx playwright test --workers=1 --reporter=dot` → 631 passed
