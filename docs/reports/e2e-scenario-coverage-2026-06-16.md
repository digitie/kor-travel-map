# E2E 시나리오 커버리지 — 촘촘 매트릭스 (2026-06-16, claude)

전체 코드+문서 감사(`full-consistency-audit-2026-06-16.md`)의 **e2e 시나리오 부분 정본**.
admin frontend Playwright e2e의 페이지/플로별 **커버된 시나리오 vs 빠진 시나리오**를
촘촘하게 정리한다. 본 문서는 **커버리지 갭의 정본 기록**이며, 실제 spec 추가는 backlog
(`docs/tasks.md`)로 분리한다(본 패스는 docs-only).

- **기준**: `packages/kor-travel-map-admin/frontend/e2e/*.spec.ts` (origin/main).
- **실행 모델**(`playwright.config.ts`): debug UI는 WSL 기동(backend `:12701`, frontend
  `:12705`), **Playwright는 Windows 호스트에서 실행**(ADR-23 예외). `webServer` 없음(외부
  기동 가정), baseURL `http://127.0.0.1:12705`(`E2E_BASE_URL` override), chromium 단독,
  timeout 30s/expect 15s.

## 0. 현재 e2e 인벤토리

| spec | tests | 성격 | 비고 |
|------|-------|------|------|
| `admin-ops.spec.ts` | 22 (1449 lines) | admin/ops **상호작용**(mutation flow 다수) | 13개 route를 `goto` |
| `dagster.spec.ts` | 1 | **render-only** smoke | 상호작용 0 |
| `etl.spec.ts` | 3 | preview happy-path | fixture 2종 |
| `features.spec.ts` | 4 | 지도 smoke + 필터 | 마커 클릭 없음 |
| `home.spec.ts` | 3 | shell + nav + metric 카드 | 값 검증 없음 |
| **합계** | **33** | | **22개 페이지 중 5개 ZERO 커버** |

> "Windows Playwright 33/33"류 표기는 **현재 spec이 모두 통과**한다는 뜻이지 UI 표면을
> 촘촘히 덮는다는 뜻이 아니다(`test-strategy.md`에 이 단서 추가 — 감사 C-03 연계).

## 1. ZERO 커버리지 페이지 (HIGH — spec 자체가 없음)

아래 5개 페이지는 **e2e spec도 screen-checklist row도 없다**. curated/manual-create는
1000줄 이상의 mutation 콘솔이고, 3개 detail 페이지는 cancel/run-now/WS 라이브 갱신 등
핵심 액션을 가진다.

### 1.1 `/admin/curated-features` (1192-line mutation 콘솔) — **priority HIGH**
커버: **없음**(API 라우터 레벨 test도 mount/openapi presence만).
추가할 시나리오:
- render: heading + 필터(theme/provider/dataset/status) + 테이블
- status 필터: candidate/curated/rejected/archived
- select/unselect mutation + optimistic update(`useSelect/UnselectCuratedFeatureMutation`)
- patch curated feature(`usePatchCuratedFeatureMutation`)
- archive + confirm 가드(`useArchiveCuratedFeatureMutation`)
- source-rule patch + apply(`usePatch/ApplyCuratedSourceRuleMutation`)
- TripMate copy snapshot preview(`useTripmateCopySnapshot`)
- copy-policy / relation select
- pagination 25/50/100/200, empty state, error alert(`role=alert`), deeplink

### 1.2 `/admin/features/new` (1097-line 수동 생성 폼) — **priority HIGH**
커버: **없음**.
추가할 시나리오:
- render: 폼 섹션(기본/위치/주소/상세/출처)
- kind/category/status 필드
- lon/lat + map-click + geocode + reverse-geocode
- Address DTO 필드 + bjd 자동 채움
- kind별 detail 폼(Place/Event/Notice/Route/Area)
- `provider='manual'` 강제
- 검증(required, 좌표 한국 범위)
- submit → `POST /admin/features` → dedup_candidates/issues 노출
- 422/409 에러, nearby preview

### 1.3 `/admin/feature-update-requests/[requestId]` (detail) — **priority HIGH**
커버: **없음**(목록만 admin-ops가 1건).
시나리오: render detail / scope·matched-scope·job·Dagster-run 표시 / cancel mutation(non-terminal) /
run-now(`useRunFeatureUpdateRequestNowMutation`) / WS `dagster_runs` 라이브 invalidation /
terminal 상태 액션 비활성 / 404 / error.

### 1.4 `/ops/import-jobs/[jobId]` (detail) — **priority HIGH**
커버: **없음**(목록만 1건).
시나리오: payload+progress+stage render / relation 링크(events/dagster_run/parent/batch) /
event timeline(`useImportJobEvents`) / cancel 폼(canCancel non-terminal, `useCancelImportJobMutation`) /
WS `import_job_events:{id}` 라이브 invalidation / terminal→polling 정지 / 404 / error.

### 1.5 `/features/[featureId]` (detail) — **priority HIGH**
커버: **없음**(`/features` 지도만).
시나리오: 8개 detail 섹션(header/위치/상세/주소/원천/파일/이슈/이력) render / map+nearby /
AddressMatchReport / reverse·geocode 재검증 / raw JSON 토글 / 404 / error.

## 2. 얇은 커버리지 페이지 (render-smoke만 — mutation/error/pagination 누락)

### 2.1 `/admin/features` (목록) — admin-ops 1 smoke — **MED**
커버: heading + 6 필터 + 7 컬럼 + placeholder.
빠짐: q 검색 query 반영 / sort·order 토글 / cursor pagination(next/exhaust, `meta.page.next_cursor=null`) /
empty-state / error alert(problem+json) / deactivate kill-switch / row→`/features/[id]` deeplink / has_issue 필터.

### 2.2 `/admin/features/change-requests` — admin-ops 5 tests — **MED**
커버: render + 15 폼 라벨 + 7 컬럼 / detail-JSON array→클라 검증 에러(T-218d) / approve 워크플로 /
immediate-create / update+delete + action 필터.
빠짐: **reject lifecycle**(approve만 테스트됨) / 서버 4xx·409 error alert / cursor pagination / empty / q 실제 필터.

### 2.3 `/admin/issues` — admin-ops 1 test — **MED**
커버: render + 8 필터 + 8 컬럼 / missing_address 필터→manual_override 빈입력 검증·focus.
빠짐: **7/8 액션**(resolve/ignore/reopen/retry_geocode/retry_reverse_geocode/apply_kor_travel_geo_address —
manual_override 음성 경로만 테스트) / map view + 좌표없음 side list / cursor pagination / error alert / severity-marker.

### 2.4 `/admin/dedup-reviews` — admin-ops 1 smoke — **MED**
커버: heading + status 필터 + 5 컬럼.
빠짐: **accept/reject/ignore/merge 4 결정 전부** / split-view compare / master_feature_id 선택 /
merge mutex(ADR-039) / cursor pagination / empty / error.

### 2.5 `/admin/enrichment-reviews` — admin-ops 1 test — **MED**
커버: heading + status 필터 + 5 컬럼 + cursor prev/next 노출.
빠짐: accept/reject/ignore 액션 / cursor 실제 전진 / 1차·2차 compare 패널 / empty / error.

### 2.6 `/admin/feature-update-requests` (목록) — admin-ops 1 test — **MED**
커버: render + 5 폼 + run-mode + dry-run checked + status + lon-empty 검증·focus.
빠짐: 실제 생성 submit 성공 / dry-run vs run-now kill-switch / cursor / empty / error / row→detail deeplink.

### 2.7 `/ops/import-jobs` (목록) — admin-ops 1 smoke — **MED**
커버: heading + status·kind 필터 + 5 컬럼.
빠짐: cursor pagination / empty / error / load_batch_id·parent_job_id 필터 / row→`/[jobId]` deeplink.

### 2.8 `/ops/providers` — admin-ops 1 test (T-217g) — **MED**
커버: render + freshness 9 컬럼 + summary 뱃지 + failing alert + detail 기본선택.
빠짐: **refresh-policy edit**(T-221d PUT, `useUpsertProviderRefreshPolicyMutation`) / recent update-request 링크 /
sync cursor 표시 / provider detail 이동 / empty / error.

### 2.9 `/admin/poi-cache-targets` — admin-ops 3 tests — **LOW**
커버: render + upsert→nearby→delete flow + target_key 검증·복구(T-218b).
빠짐: cursor / empty / error / on_conflict=move / refresh_policy·provider_overrides edit.

### 2.10 `/admin/offline-uploads` — admin-ops 3 tests — **LOW**
커버: render + 업로드→preview→validate→load(Dagster STARTED)→delete flow(#397) + re-upload.
빠짐: validation_failed 분기 / 413 oversize(§16.3) / JSON·JSONL·TSV(CSV만) / cursor / CP949 인코딩 표시.

### 2.11 `/admin/backups` — admin-ops 2 tests — **LOW**
커버: render + manifest detail + create/restore(staging)/swap + role=status live region(T-218c/e).
빠짐: command_enabled=true 실행 분기(plan-only만) / restore 확인 가드 / empty / error.

### 2.12 `/admin/dagster` — dagster.spec 1 test — **LOW**
커버: heading + Dagster열기 링크 + Code locations + Recent runs + Run detail + webserver embed.
빠짐: run/tick 실패 drilldown / nux-seen POST / empty runs / embed-fail fallback / run-detail 선택.

### 2.13 `/ops/consistency` — admin-ops 1 smoke — **LOW**
커버: heading + Open issues + Reports + Integrity issues + status 필터.
빠짐: report drilldown / issue-queue 액션 / severity_max 뱃지 / empty / error.

### 2.14 `/ops/logs` — admin-ops 1 test — **LOW**
커버: System logs 6 컬럼 + API call logs 7 컬럼 + 필터.
빠짐: **import_job_events stream 탭**(§13의 3 source 중 system+api만) / cursor / 필터 실제 적용 / job deeplink / empty / error.

### 2.15 `/ (home)` — home.spec 3 tests — **MED**
커버: shell + 9 nav 링크 + 7 metric 카드 + 최근 import jobs + nav 2개.
빠짐: **나머지 8개 nav 링크 단언**(admin-shell 17개 중 9개만) / metric 5xx empty·error state / loading skeleton / 전 nav deeplink.

### 2.16 `/features` (지도) — features.spec 4 tests — **MED**
커버: render+map+header / home→features nav / kind 필터 7칩 토글·초기화 / 미선택시 detail 숨김.
빠짐: 마커 클릭→detail 패널 open / pan·zoom bbox refetch(§7.1) / map↔table 토글+URL/Zustand sync(view=map/table) /
fetch 5xx error / count=0 명시 단언.

### 2.17 `/etl` (debug preview) — etl.spec 3 tests — **LOW**
커버: provider 로드 + krex fixture→place + 4 provider 존재 + datagokr→event.
빠짐: error/4xx / empty provider list / live source(fixture만) / provider별 전 dataset(디버그 표면이라 LOW).

## 3. 우선순위 요약 (spec 추가 backlog 권장 순서)

1. **HIGH (ZERO 커버 + 핵심 mutation)**: curated-features, features/new, 3개 detail 페이지(`[requestId]`/`[jobId]`/`[featureId]`).
2. **MED (mutation/lifecycle 누락)**: features 목록 deactivate, change-requests **reject 경로**, issues 7액션, dedup/enrichment 결정 액션, providers refresh-policy edit, import-jobs cursor, home nav 완전화, features 마커클릭.
3. **LOW (depth/edge)**: backups 실행분기, offline-uploads 포맷·413, dagster 상호작용, consistency·logs drilldown.

## 4. 공통 누락 패턴 (전 페이지 적용)
대부분 페이지가 **render-smoke만** 있고 아래가 빠져 있다 — spec 추가 시 페이지마다 체크:
- **mutation + optimistic update + 성공/실패 토스트**
- **error alert**(`role=alert`, RFC7807 problem+json 4xx/5xx)
- **empty state**(count=0)
- **cursor pagination**(next 전진 / 소진시 `meta.page.next_cursor=null`)
- **filter/search 실제 query 반영**
- **loading/skeleton**
- **kill-switch/permission 비활성**(dry-run, command_enabled)
- **deeplink/navigation**(목록→detail row)
- **WS 라이브 invalidation**(import_job_events / dagster_runs) — detail 페이지

## 5. 비-갭(정상 — 혼동 방지)
- ETL preview backend는 fixture provider **정확히 4종** 등록 → etl.spec 단언과 일치(의도).
- `/features`가 DB 비어도 200(count=0) → 마커 미렌더는 적재 환경 별도 검증(spec 주석 명시).
- admin-ops.spec(23 tests)은 backups/offline-uploads/poi-cache-targets/change-requests에서 **실 mutation flow**를 덮음 — 이들은 depth만 부족.
