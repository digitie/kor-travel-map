# journal.md — 작업 일지 (역시간순)

가장 위가 가장 최근. 새 엔트리는 위에 append.

## 2026-05-25 07:00 (claude)

**작업**: PR#12 — `python-knps-api` (외부 repo scaffold 완료) 통합 반영 +
ADR-028 (proposed). knps-api 측 PR#1 (maki icon 정정) 동시 진행.

**컨텍스트**: 사용자가 `digitie/python-knps-api` 저장소를 push 완료
(`6e36990 Initial KNPS API client scaffold`). 본 라이브러리 통합 작업
+ knps-api 측 발견 이슈는 upstream PR로 직접 수정 정책 (ADR-025 사용자
보강 2차 패턴 미러).

**upstream knps-api repo 상태 (`6e36990`)**:
- 공개 API: `KnpsClient`, `KnpsConfig`, `ApiEndpoint`, `FileDataset`,
  `CatalogEntry`, `Page`, `PROVIDER_NAME="python-knps-api"`, 예외 7종
  (`KnpsApiError`/`KnpsAuthError`/...), helper 5종 (`api_endpoint`,
  `api_endpoints`, `catalog_entries`, `file_dataset`, `file_datasets`).
- catalog: API 3건 (`knps_visitor_statistics`, `knps_access_restrictions`,
  `knps_fire_alerts`) + 파일 11건 (forest §11.3 7건 + §11.4 4건 추가:
  campgrounds/shelters/recommended_courses/park_photos/visitor_statistics).
- 인증: `KNPS_SERVICE_KEY` 우선, `DATA_GO_KR_SERVICE_KEY` 폴백
  (`knps.config.KnpsConfig.from_env`).
- HTTP: `KnpsHttp` (httpx async + token bucket 5 RPS + `_decode_payload` +
  `_normalize_payload` data.go.kr envelope 자동 정규화 + service_key
  auto-redact in `CallContext.request_params`).
- 파일: `client.files.download(key)` — `download_url` 검증된 dataset만.
- SHP/GeoJSON parser: `[geo]` extra (`pyproj`, `pyshp`) — placeholder, 본
  라이브러리 측에서 처리 권고 (ADR-006 정신).

**knps-api 측 PR#1 (https://github.com/digitie/python-knps-api/pull/1)**:
- `docs/knps-feature-etl.md §4` maki icon 2건 정정:
  - 대피소: `lodging` → `shelter` (본 라이브러리 ADR-027의
    `PLACE_CATEGORY_MAPBOX_MAKI_ICONS[LODGING_MOUNTAIN_SHELTER]` 정합)
  - 위험지역: `danger` → `barrier` (Maki 표준에 `danger` 없음)
- 표 아래 downstream 정합 명기.

**본 라이브러리 PR#12 변경 파일**:
- `docs/decisions.md` — **ADR-028 (proposed)** 신설 (~110줄):
  - provider 등록 6항목 (canonical name / import / module / dataset prefix
    / 인증 env / pyproject extras).
  - SHP/GeoJSON 파싱 책임 분리 (본 라이브러리 권고).
  - ADR-027 코드 적용 시기 정렬 (T-018 동시).
  - 양방향 PR 워크플로 (D, maplibre-vworld-js 패턴 미러).
  - 본 라이브러리 신설 `docs/knps-feature-etl.md`.
  - 14 dataset_key 카탈로그 (API 3 + 파일 11).
- `docs/forest-feature-etl.md §11`:
  - "데이터 통합 계획" → "데이터 통합" (현재형, scaffold 완료 반영).
  - §11.1 옵션 B "권고" → "채택 ✅".
  - §11.1.1 신설 — 외부 라이브러리 공개 API 표면 + 특이사항 (현 구현 상태).
- `docs/knps-feature-etl.md` 신설 (~220줄):
  - feature 적재 계약 (upstream knps-feature-etl.md와 정합).
  - dataset 매핑 14건 (API 3 + 파일 11).
  - cultural_resources RESOURCE_TYPE 분기.
  - 매핑 룰 (area / route / place / weather / notice / timeseries+media).
  - category 매핑 검증 표 (shelter / barrier 정합).
  - 핵심 함수 시그니처 후보 (Sprint 2).
  - Dagster asset 12종.
  - 검증 (fixture / EXPLAIN / 정합성 / upstream verification).
- `docs/provider-contract.md`:
  - §2 `CANONICAL_PROVIDER_NAMES`에 `python-knps-api` 추가.
  - §3 dataset_key 표에 14건 추가.
  - §4 책임 매트릭스에 한 줄 추가.
- `docs/external-apis.md`:
  - §2 환경변수 카탈로그에 `KNPS_SERVICE_KEY` 추가.
  - §3.8.1 신설 — KNPS API key 발급 절차.
- `pyproject.toml` — `providers` extras에 `python-knps-api` git URL 주석.

**SHP/GeoJSON parsing 위치 결정 (잠정)**:
- 본 라이브러리 `krtour.map.providers.knps`에서 파싱 권고 — provider
  라이브러리는 raw bytes/page만, 변환은 본 라이브러리 책임 (ADR-006 정신).
- Sprint 2 진입 시 cost/benefit 재평가 후 최종 결정. knps-api `[geo]` extra
  가 이미 있으므로 양쪽 모두 가능.

**다음**: PR#12 commit + push + open. PR#10/PR#11과 forest-feature-etl.md /
journal.md / resume.md / tasks.md 충돌 가능 — append 위주라 resolvable.
knps-api PR#1 merge 후 본 라이브러리 `docs/knps-feature-etl.md` 동기.

---

## 2026-05-25 06:00 (claude)

**작업**: ADR-025 2차 사용자 보강 — frontend 빌드 도구 **Vite → Next.js**
정정. PR#11.

**컨텍스트**: 사용자 한 줄 지시 "디버그 ui는 next.js 기반임." 1차 결정 시
"React + Vite"로 박았던 것이 잠정 가설이었고, `kraddr-geo-ui`와 TripMate
`apps/web` 모두 Next.js이므로 stack 통일을 위해 Next.js로 정정.

**변경 파일**:
- `docs/decisions.md`:
  - ADR-025 §컨텍스트 후보 옵션 — "Next.js/Vite SSR 지원" → "Next.js App
    Router 지원" 정정.
  - ADR-025 §결정 — "React + Vite + TypeScript" → "Next.js 15 (App Router)
    + React 19 + TypeScript".
  - ADR-025 §결정 — 빌드/개발/env 설명 Next.js로 변경.
  - ADR-025 §근거 — kraddr-geo-ui 일관 + TripMate `apps/web` 동일 stack
    명기.
  - ADR-025 §결과(긍정/부정) — Vite → Next.js로 정정.
  - **ADR-025 §사용자 보강 (2026-05-25, 2차) — 빌드 도구 정정** 신설:
    `next dev --port 8610`, App Router, `NEXT_PUBLIC_*` env, `@krtour/
    map-marker-react` transpilePackages, 운영 옵션 3가지 (standalone /
    proxy / export).
  - §후속 — Vite skeleton → Next.js로 본 PR#11에서 전환 명기.
- `docs/debug-ui-package.md` §14 전체 갱신:
  - §14.1 기술 스택 — Framework Next.js 15 (App Router) 추가, 빌드 도구
    Vite 행 삭제, 공통 마커 `@krtour/map-marker-react` (ADR-029) 추가.
  - §14.2 환경변수 — `VITE_*` → `NEXT_PUBLIC_*` 일괄 정정.
  - §14.3 기동 — Next.js dev 명령 + 운영 옵션 3가지 (standalone / FastAPI
    reverse proxy / static export).
  - §2 디렉토리 트리 — `vite.config.ts`/`index.html`/`src/main.tsx`/`pages/`
    삭제, `next.config.js`/`src/app/` (App Router) 추가, categoryMaki/
    markerColor는 `@krtour/map-marker-react`로 이전 명기.
  - §9 테스트 — Playwright + Vitest (Next.js 공식 가이드 미러).
  - §10 외부 노출 — `Vite` → `Next.js dev/standalone` 정정.
- `docs/external-apis.md` — VWorld 항목 `VITE_VWORLD_API_KEY` →
  `NEXT_PUBLIC_VWORLD_API_KEY` 정정.
- `docs/tripmate-integration.md` §14.5:
  - Next.js 명기 (두 UI 동일 stack).
  - `@krtour/map-marker-react` 사용 명기.
  - 작업 분담에 "Next.js 그대로 유지, 마커 import만 교체" 명기.
- `packages/krtour-map-debug-ui/README.md`:
  - "React + Vite + maplibre-vworld" → "Next.js + React 19 + maplibre-vworld"
  - 운영 배포 옵션 3가지 명기.
  - Backend env 표의 "Vite dev 서버" → "Next.js dev 서버".
  - Frontend env 표 `VITE_*` → `NEXT_PUBLIC_*`.
- `packages/krtour-map-debug-ui/frontend/package.json` — 전체 교체:
  - `vite`/`@vitejs/plugin-react`/`vitest` → `next`/`eslint-config-next`/
    `@types/node`.
  - scripts: `vite` → `next dev/build/start/lint`.
  - dependencies: `next`/`@krtour/map-marker-react` (workspace) 추가.
- `packages/krtour-map-debug-ui/frontend/.env.example`:
  - `VITE_*` → `NEXT_PUBLIC_*`.
  - 주석에 Next.js env 규약 (NEXT_PUBLIC_ vs server-only) 명기.
- `packages/krtour-map-debug-ui/frontend/.gitignore`:
  - `dist/` 삭제, `.next/`/`out/`/`next-env.d.ts` 추가, `.vite/` 삭제.
- `packages/krtour-map-debug-ui/frontend/README.md`:
  - 기술 스택 표 Next.js 행 추가, Vite 삭제, env `NEXT_PUBLIC_*`.
  - 개발 명령 `next dev --port 8610`.
  - 빌드 / 운영 옵션 3가지 추가.
  - 페이지 표를 App Router route (`/features/[id]` 등)로 변경.
  - categoryMaki 매핑은 `@krtour/map-marker-react` 사용 (ADR-029) 명기.
- `packages/krtour-map-debug-ui/frontend/next.config.js` 신설:
  - reactStrictMode + transpilePackages (`@krtour/map-marker-react`)
  - 운영 옵션(`output: 'standalone'/'export'`, `basePath`, `rewrites`)은
    주석 처리 — 운영자 결정 후 활성화.
- `docs/tasks.md` — §폐기/재해석 — T-100 "Next.js 미채택" 기록은 잘못됨
  명기, ADR-025 2차 보강으로 채택 확정.

**핵심 인사이트**: kraddr-geo-ui = Next.js이고 TripMate `apps/web` = Next.js
이므로 디버그 UI도 Next.js가 자연. 1차에서 Vite로 박았던 것은 SPA의 단순함
가정에서 비롯됐으나, 운영 일관성 (학습 곡선 통일 + `@krtour/map-marker-react`
transpilePackages 단일 설정) 가치가 더 큼.

**다음**: PR#11 commit + push + open. PR#10과 충돌 가능 (양쪽이 frontend
README/package.json 일부 영역 수정) — 작은 충돌, resolvable.

---

## 2026-05-25 05:00 (claude)

**작업**: PR#10 — T-012~T-018 진행 + ADR-029 (proposed) + T-101~103 상세
분석 + 명명 일치화 + 코딩 (`pyproject.toml` 강제 + scripts skeleton).

**컨텍스트**: 사용자 지시 5건 동시 진행:
1. PR#9 rebase → 다시 PR (완료).
2. T-101~103 상세 의견을 문서에 반영.
3. T-012~T-018 진행 + ADR-029 작성 + tasks.md 갱신.
4. 필요한 코딩 (사용자가 "필요한 코딩도 할 것"으로 명시 허용 — 제한된
   scope, scaffolding/policy 강제 위주).
5. `python-krmois-api` → `python-mois-api` 일괄 + 비슷한 명명 일치화.
6. `digitie/python-knps-api` 모니터링 (외부에서 1시간 내 개발 완료 예정) →
   반영. 현 시점 repo 상태: empty, size=0. 백그라운드 agent 모니터링 시도
   했으나 권한 거부 — 본 세션에서 주기 체크 후 후속 PR로 반영 예정.

**결정 / 신규 ADR**:
- **ADR-029 (proposed)**: `@krtour/map-marker-react` npm 패키지 추출. MIT
  라이선스 (TripMate proprietary 호환). monorepo `packages/map-marker-react/`.
  본 라이브러리 PR에서 Python 카테고리/notice 변경과 동시에 TypeScript
  매핑 변경 → drift 0. 게시는 공개 npm.

**상세 분석 문서화 (T-101~103)**:
- `docs/performance.md §9.3` (T-101 MV): 도입 장점 (7-way JOIN → single
  table scan), 조건 (read >> write, REFRESH lag 허용, 디스크 ×2, 정합성
  게이트 선행), 부작용 (DDL 무거움, stale 혼동), 절차 (시범 → 1주 운영
  → ADR 신설).
- `docs/performance.md §9.4` (T-103 streaming): 시나리오 (산불경보/특보
  초 단위), 라이브러리 위치 (consumer는 TripMate, 본 라이브러리는 함수
  만). `pyproject.toml`에 `kafka`/`aiokafka`/`confluent_kafka`/`faust`
  import 차단 계약 추가.
- `docs/performance.md §9.5` (T-102 pg_prewarm): 장점 (cold-start cliff
  제거), 조건 (P99 SLO + 재배포 빈도 + shared_buffers fit), 절차
  (`autoprewarm = on` background + `/health` 표시).

**명명 일치화 (잔존 krmois 정리)**:
- `docs/forest-feature-etl.md:173` 컨벤션 예시: `python-krmois-api` →
  `python-mois-api`.
- `docs/mois-license-feature-etl.md:115` 예시 payload: `krmois_admin_address`
  → `mois_admin_address`.
- `docs/journal.md:151` 컨벤션 예시: `krmois/krheritage/krforest` →
  `mois/krheritage/krforest`.
- `docs/journal.md:475` 옛 provider 목록: `krmois` → `mois (구 krmois)`.
- ADR-024 migration 본문 / journal ADR-024 narrative / mois-feature-etl.md
  v1→v2 마이그레이션 표 등 *역사 기록* 컨텍스트의 krmois 표기는 유지
  (rename 사건 자체를 기록).

**코딩 (사용자 명시 허용)**:
- `CHANGELOG.md` 확장 — [Unreleased] §결정 (PR#6~PR#10 시기) + 문서 확장
  + 명명 일치화 + 코드 변경 모두 inline.
- `pyproject.toml`:
  - `[tool.coverage.report]` ADR-032 Sprint 1~5 schedule 주석 inline.
  - `[[tool.importlinter.contracts]]` `cachetools`/`async_lru`/`aiocache`/
    `diskcache` 차단 (ADR-030).
  - `[[tool.importlinter.contracts]]` `kafka`/`aiokafka`/`confluent_kafka`/
    `faust` 차단 (T-103/ADR-103 후보).
- `packages/krtour-map-debug-ui/scripts/export_openapi.py` 신설 — ADR-031
  CLI skeleton. `--check` drift gate. 코드 작성 단계 진입 전에는 module
  not found 가이드 출력.
- `packages/map-marker-react/` skeleton 신설 (`package.json` / `README.md`
  / `vite.config.ts` / `.gitignore`) — ADR-029 placeholder.
- `docs/sprints/` 신설 — `README.md` (Sprint 1~5 표) + `SPRINT-1.md` 초안
  (진입 조건 + 산출물 + DoD + Sprint 2 진입 조건).

**문서 갱신**:
- `docs/tasks.md` — T-012/013/017/018 상태 갱신, T-013 [x], T-101~103 상세
  내용 inline + 도입 조건/절차, "ADR 번호 가이드" proposed/후보 분류.
- `docs/resume.md` — "코드 작성 단계 진입 전" + "다음 ADR" 갱신.

**python-knps-api 모니터링 상태**:
- 현재 (2026-05-25 05:00 시점) `digitie/python-knps-api` repo는 size=0
  empty.
- 백그라운드 agent 실행 실패 (Bash/PowerShell/WebFetch 권한 거부).
- 본 세션에서 주기 체크 (~30분마다) → 콘텐츠 발견 시 후속 PR로 반영.
  반영 대상: ADR-028 본문 초안, `docs/forest-feature-etl.md §11` 갱신,
  새 `docs/knps-feature-etl.md` (필요 시).

**다음**: PR#10 commit + push + open. 사용자 review → merge → T-014 PR로
Sprint 1 진입.

---

## 2026-05-25 04:00 (claude)

**작업**: ADR-027 (proposed) — forest 카테고리/notice_type 확장 결정. 사용자
가 forest §11.6 candidates에 대한 의견 요청 + 입산통제/산불경보를 generic
notice_type으로 일반화 지시.

**컨텍스트**: forest §11.6에 7건 candidates가 있었고, 사용자가 그 중
입산통제/산불경보를 `forest_*` prefix 없이 generic 이름으로 일반화 결정.
나머지(대피소 / hazard_zone / 거부 항목)는 claude 제안 그대로 채택.

**결정 요약** (decisions.md ADR-027):
- ✅ `LODGING_MOUNTAIN_SHELTER` (Tier 2 `03.08` + Tier 3 `03.08.01` KNPS /
     `03.08.02` KFS, maki=`shelter`)
- ✅ `AreaDetail.area_kind='hazard_zone'` 신설 (PlaceCategory 미신설)
- ✅ `notice_type='access_restriction'` (generic, 입산통제/해수욕장폐장/
     공원폐쇄 등 통칭, payload.domain으로 출처 구분)
- ✅ `notice_type='fire_alert'` (generic, 산불경보 + 화재 일반)
- ❌ `WEATHER_MOUNTAIN_STATION` PlaceCategory (kind=weather 자체로 충분)
- ❌ `NATURE_ECOLOGY` PlaceCategory (v2 1차 범위 밖)
- ❌ `SAFETY_*` PlaceCategory / Tier 1 `08 SAFETY` (area_kind으로 대체,
     Tier 1 enum 변경 회피)

**변경 파일**:
- `docs/decisions.md`: ADR-027 (proposed) 추가 (~120줄).
- `docs/category.md`:
  - §4.2 트리 — `03.08` Tier 2 + Tier 3 두 행 추가.
  - §4.3 depth 통계 — Tier 2 29→30, Tier 3 71→73, 합계 141→144.
  - §4.4 maki icon 분포 — `shelter` 3건 추가.
- `docs/notice-feature-etl.md`:
  - §3 NOTICE_TYPES — `access_restriction` / `fire_alert` 추가.
  - §3 normalize_notice_type alias 표 — 입산통제/해수욕장폐장/산불경보 등
    한/영 alias 추가.
  - §7 마커 스타일 표 — 두 신규 type 매핑 추가 (maki `barrier`/`fire-station`).
- `docs/feature-model.md` §9: AreaDetail.area_kind에 `hazard_zone` 추가
  + payload 예시 주석.
- `docs/data-model.md` §6.3: `feature_area_details.area_kind` 컬럼 주석에
  `hazard_zone` 명기 + payload 주석.
- `docs/forest-feature-etl.md`:
  - §11.4 추가 발굴 후보 표 — `knps_shelters` (LODGING_MOUNTAIN_SHELTER_KNPS),
    `knps_access_restrictions` (generic notice_type), `knps_fire_alerts`
    (generic notice_type), 식생/서식지 (v2 범위 밖) 명기.
  - §11.6 후보 표 → ADR-027 결정 요약 표로 대체 (✅/❌ 분류).
  - §11.8 후속 작업 — ADR-027 proposed → accepted 전환 명기.
- `docs/resume.md`: "다음 ADR 후보"의 ADR-027 항목을 proposed로 명기 +
  사용자 결정 내용 inline.
- `docs/tasks.md`:
  - T-018 — ADR-027 proposed 결정 완료 명기 + accepted 전환 시점 = T-018
    실행 시점.
  - §"ADR 번호 가이드" — proposed 섹션 신설 (ADR-027).

**작성 시기 의도**: T-018 (`python-knps-api` provider 등록) 시점에 코드와
함께 accepted 전환. 지금 proposed로 박는 이유는 KNPS dataset이 확정되기
전이라도 *분류 정책*은 명확히 박혀 있어 작업 협상 비용 0.

**다음**: 사용자 review → accepted 전환 또는 추가 조정. PR#8 (ADR-030~033
proposed)과 텍스트 충돌 가능 (resume.md/tasks.md) — 머지 순서에 따라 한
쪽이 rebase 필요.

---

## 2026-05-25 03:00 (claude)

**작업**: ADR-030/031/032/033 `proposed` 작성 — 사용자가 의견 요청한 4건을
공식 ADR로 박음 + 관련 docs 교차 링크.

**컨텍스트**: 사용자가 ADR-030/033 → ADR-031/032 순으로 의견 요청. 의견을
지속 기록으로 남기지 않으면 다음 conversation에서 다시 협상해야 함 →
`proposed` ADR로 정식 박음. T-014(코드 작성 단계 진입 결정)에서 시기 의존
ADR(032/033)은 Sprint 일정 확정과 함께 accepted 전환.

**변경 파일**:
- `docs/decisions.md`:
  - **ADR-030 (proposed)**: 라이브러리 in-memory 캐시 금지. `functools.cache`
    한정 narrow 예외 (PlaceCategoryCode 카탈로그, `pyproj.Transformer`
    singleton). `import-linter` 계약으로 `cachetools`/`async_lru`/`aiocache`/
    `diskcache` 의존 차단.
  - **ADR-031 (proposed)**: 디버그 패키지 OpenAPI export 첫 FastAPI 라우터
    등장 PR부터 즉시 활성화. `openapi.json` 저장소 커밋 + CI `--check` gate.
    frontend 도입 전부터 drift gate 가동 → type drift 부채 0.
  - **ADR-032 (proposed, 시기 의존)**: Coverage 단계적 상향 일정 (Sprint 1
    50% → Sprint 4 80%). `dto/`는 Sprint 2부터 100% branch 항상 강제.
    T-014에 묶어 accepted 전환.
  - **ADR-033 (proposed, 시기 의존)**: `feature_consistency_reports` 두 단계
    분할 도입. Phase 1 (Sprint 3~4) = 스키마 + F1~F3 (orphan source / detail
    누락 / CRS drift, severity=ERROR, 게이트 미적용). Phase 2 (Sprint 5) =
    F4~F8 + Dagster 게이트 + swap 차단. T-014에 묶어 accepted 전환.
- `docs/resume.md`: "다음 ADR 후보" → "다음 ADR (proposed / 후보)" 재분류.
  ADR-030/031/032/033을 proposed로 명기.
- `docs/tasks.md`: T-012 항목을 `proposed` 4건으로 갱신. §"ADR 번호 가이드"에
  proposed 섹션 추가.
- `docs/performance.md §9.1`: ADR-030 링크 + narrow 예외 + import-linter
  계약 명기.
- `docs/test-strategy.md §2`: ADR-032 link + Sprint별 coverage schedule 표
  inline.
- `docs/dagster-boundary.md §12`: ADR-033 link + Phase 1/Phase 2 분할 명기.
- `docs/debug-ui-package.md §8`: ADR-031 link + 활성화 시점 명기.

**다음**: 사용자 review → ADR-030/031은 accepted 전환 가능 (코드 작성 단계
독립). ADR-032/033은 T-014 시점에 Sprint 일정 확정 후 accepted 전환.

---

## 2026-05-25 02:00 (claude)

**작업**: 사용자의 4건 의사결정 반영 — (1) VWorld key 공유, (2) TripMate
사용자 UI도 maplibre-vworld 통일, (3) frontend 코드는 별도 PR, (4)
maplibre-vworld-js upstream 적극 수정.

**컨텍스트**: PR#6 (ADR-025)의 결과(부정) 두 항목 — "VWorld key 별도 발급
vs 공유 미정" + "provider 라이브러리 stability 모니터링 필요" — 에 사용자가
명시 결정을 내림.

**변경 파일**:
- `docs/decisions.md`:
  - ADR-025 §결과(부정) 정리 — 공유 정책 확정으로 부정 항목 1개 흡수.
  - ADR-025 §사용자 보강(2026-05-25) 신규 — 1. key 공유 / 2. upstream 직접 PR.
  - ADR-025 §후속 — forest §11.6 후보 번호 ADR-026 → ADR-027 (ADR-026이
    TripMate UI 통일에 선점).
  - **ADR-026 신규**: TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8
    v8_3 supersede). 두 UI 단일 stack, Kakao Maps JS SDK 제거. 공통 maki
    npm 패키지 추출은 후속 ADR.
- `docs/external-apis.md`:
  - 환경변수 카탈로그에 `KRADDR_GEO_VWORLD_API_KEY` 항목 추가 (공유 키 명기).
  - §8 비용 관리에서 Kakao Maps JS SDK 항목 → "미사용 (ADR-026)" 처리.
  - VWorld 항목에 ADR-025 보강 + ADR-026 사용처 추가.
- `docs/debug-ui-package.md`:
  - §14.2 환경변수 — VITE_VWORLD_API_KEY 설명을 "공유 키" 명기, 운영자
    주입 절차 박음. TripMate UI 공유 명기.
  - §14.8 외부 노출 안전 — referrer 화이트리스트에 backend + TripMate 호스트.
  - §15 핵심 메시지 — 공유 정책 + upstream 적극 수정 정책 박음.
- `docs/tripmate-integration.md`:
  - §14.5 신설 — TripMate 사용자 UI 지도 stack (ADR-026), Kakao 제거, 공유 키.
- `docs/forest-feature-etl.md`:
  - §11.6 heading + 본문 2곳: "ADR-026 후보" → "ADR-027 후보".
  - §11.8 후속 ADR-026/027 → ADR-027/028.
- `docs/resume.md`:
  - 진척도에 ADR-025 보강 + ADR-026 추가 (둘 다 [x] 완료).
  - "다음 ADR 후보" 정리 — 이미 accepted된 ADR-021~024 항목 제거, 후보 번호
    ADR-027부터 재배열 (027 카테고리 확장, 028 KNPS provider, 029 공통 maki
    npm 패키지, 030 캐시, 031 OpenAPI, 032 coverage, 033 정합성).
- `packages/krtour-map-debug-ui/frontend/.env.example`:
  - VITE_VWORLD_API_KEY 주석 — "= $KRADDR_GEO_VWORLD_API_KEY 값과 동일" 박음.
- `packages/krtour-map-debug-ui/frontend/README.md`:
  - 환경변수 표 — 공유 정책 명기 + TripMate UI 공유 박음.

**커밋 메시지 후보**: `ADR-025 보강 + ADR-026: VWorld key 공유 + TripMate UI 통일`

**다음**: PR#6에 본 커밋 추가 push → 사용자 검토 → merge. 머지 후 ADR-029
(공통 maki npm 패키지 추출) 검토 시점에 다시 결정.

---

## 2026-05-25 01:00 (claude)

**작업**: 디버그 UI frontend 기술 결정 — `maplibre-vworld-js` 채택 (ADR-025).

**변경 파일**:
- `docs/decisions.md`:
  - **ADR-025 신설** — 디버그 UI frontend는 React + Vite + TS + `maplibre-vworld`
    + `maplibre-gl` + `zod`. Kakao Maps SDK 사용 안 함. VWorld 1차.
  - ADR-023 orphan duplicate (line 657~717) 정리 (이전 편집 사고 잔재).
- `docs/debug-ui-package.md` §2 디렉토리 + §14 신설 (~120 lines):
  - frontend 디렉토리 추가 (Vite, src/components/api/lib)
  - §14.1 기술 스택 (maplibre-vworld v1.0.0, ISC license, React 19, Vite,
    포트 8610)
  - §14.2 환경변수 (`VITE_VWORLD_API_KEY`, `VITE_KRTOUR_MAP_DEBUG_UI_API`)
  - §14.3 기동 (backend uvicorn 8600 + frontend Vite 8610)
  - §14.4 핵심 컴포넌트 매핑 (`<VWorldMap>`, `<MakiMarker>`, `<MarkerClusterer>`, etc.)
  - §14.5 category → maki icon 매핑 (`categoryMaki.ts`)
  - §14.6 OpenAPI → TypeScript 동기 (kraddr-geo ADR-015 미러)
  - §14.7~14.8 e2e + 외부 노출 안전
- `packages/krtour-map-debug-ui/README.md` — Frontend 절 추가 + env 표 분리
  (Backend / Frontend)
- **NEW**: `packages/krtour-map-debug-ui/frontend/`:
  - `package.json` (의존성 placeholder)
  - `.env.example` (VITE_VWORLD_API_KEY)
  - `.gitignore`
  - `README.md`
- `docs/external-apis.md` — VWorld API key 항목 추가 (디버그 UI용).
- `docs/forest-feature-etl.md` §11.6 — ADR-025 후보 → ADR-026 후보 renumber
  (카테고리 확장은 향후 ADR-026, knps provider 등록은 ADR-027).
- `docs/resume.md` — 후보 ADR 번호 재정렬 (ADR-026/027/028+).

**결정**:
- **ADR-025** — 디버그 UI frontend는 `maplibre-vworld-js` 채택.
  - VWorld 지도 (국토교통부 공식) — 한국 행정구역/도로명주소와 정합.
  - WebGL 60fps + MakiMarker + MarkerClusterer 내장 → 10만+ feature 처리.
  - 선언형 React → 상태 동기 단순.
  - `kraddr-geo-ui`와 동일 stack (React + Vite + TS) → 운영 일관.
  - Kakao Maps SDK 사용 안 함 (디버그 UI 측만).
  - 디렉토리: `packages/krtour-map-debug-ui/frontend/`.
  - 의존: `maplibre-vworld` v1.0.0 (ISC), `maplibre-gl` (BSD-3), `zod`, React 19.
  - VWorld API key는 `python-kraddr-geo`의 `KRADDR_GEO_VWORLD_API_KEY` 공유
    또는 별도 `VITE_VWORLD_API_KEY`.

**의사결정 (사용자 위임 — 검토 부탁)**:
- VWorld API key 발급 정책: `python-kraddr-geo`와 공유 vs 디버그 UI 전용 별도
  발급 (운영자 결정).
- TripMate 사용자 UI는 SPEC V8 v8_3 그대로 Kakao Maps SDK 유지 — 본 ADR은
  디버그 UI에만 해당.
- frontend 코드 작성은 별도 PR (코드 작성 단계 진입 시).

**발견**:
- `maplibre-vworld-js` (`digitie/maplibre-vworld-js`)는 npm `maplibre-vworld`
  v1.0.0, React/TypeScript, ISC license. 본 사용자 운영 저장소라 의존성 리스크
  낮음.
- 라이선스 호환성: ISC + BSD-3 + GPL-3.0 모두 호환 (GPL-3.0이 가장 strict이라
  배포 시 GPL 준수).
- `kraddr-geo-ui` Next.js 패턴과 비교했을 때 디버그 UI는 SPA로 충분 (Vite 만
  사용, Next.js SSR 불필요).

**다음**: PR push + 사용자 검토. PR merge 후 backlog T-200/T-201 + ADR-026/027
(카테고리 확장 + KNPS provider).

---

## 2026-05-25 00:30 (claude)

**작업**: outdoor → forest rename + 모든 feature에 category 명시 + KNPS
국립공원공단 datasets 카탈로그 + category.md Tier 1~4 상세 테이블.

**변경 파일**:
- **rename**: `docs/outdoor-feature-etl.md` → `docs/forest-feature-etl.md` (git mv)
- **신규 섹션**:
  - `docs/category.md` §4 — Tier 1~4 전체 141건 카탈로그 (트리 뷰 + maki icon 분포 표 + provider별 주된 카테고리 매핑 표)
  - `docs/forest-feature-etl.md` §11 — KNPS (국립공원공단) 데이터 통합 계획
    (provider 옵션 A/B/C 비교 + 권고, 핵심 dataset 7건 정밀 정리, 추가 발굴
    8건, Dagster asset 11종, 카테고리 확장 후보 7건)
- **갱신** (모든 ETL doc에 명시적 category code 추가):
  - `docs/forest-feature-etl.md` §4 — 8개 카테고리 (`03030101` 국립휴양림,
    `01030102` 수목원 등) 명시
  - `docs/khoa-beach-info-etl.md` — `01050100` `TOURISM_NATURE_BEACH`
  - `docs/opinet-place-price-etl.md` — `06020000` `TRANSPORT_FUEL`
  - `docs/krex-rest-area-feature-etl.md` — `06040101` `TRANSPORT_REST_AREA_HIGHWAY_EX`
  - `docs/event-feature-etl.md` — `TOURISM` 대분류 + EventDetail.event_kind
  - `docs/krheritage-feature-etl.md` §4-pre — `01070100~400` 4개 매핑 표
  - `docs/mois-feature-etl.md` §6.1 — 42 슬러그 → 정확한 카테고리 코드 매핑
    (식음/숙박/관광/문화 모두 실 카테고리 트리 기준)
  - `docs/standard-data-feature-etl.md` §2 — 5종 dataset에 category 추가
  - `docs/notice-feature-etl.md` §2.5 — notice는 카테고리 비움 / notice_type
    분류
  - `docs/kma-weather-etl.md` §1 — weather-only anchor 카테고리 규약
  - `docs/place-phone-enrichment.md` §1 — enrichment는 카테고리 변경 X
  - `README.md` — 문서 지도에 forest-feature-etl 갱신
  - `docs/resume.md` — outdoor → forest

**의사결정 (사용자 위임, 검토 부탁)**:
- **KNPS provider 옵션 B 권고** — 별도 `python-knps-api` 신설.
  - 이유: 1기관 1라이브러리 컨벤션 (mois/krheritage/krforest 등과 동일).
    KNPS는 환경부 산하, 산림청은 농림식품부 — 별도 기관. file dataset(SHP/
    GeoJSON) 처리 모듈 응집.
  - dataset_key prefix: `knps_*` (13개 + 추가 후보).
- **사용자 명시 7건 + 추가 8건** dataset 카탈로그 작성. data.go.kr ID는 web
  access 차단으로 **확인 필요** 표시 (15084538~15084545 추정).
- **카테고리 확장 후보 (ADR-025 후보)**:
  - `SAFETY_HAZARD_ZONE` (위험지역)
  - `LODGING_MOUNTAIN_SHELTER` (산장)
  - `WEATHER_MOUNTAIN_STATION` (관측소 anchor)
  - `NATURE_ECOLOGY` (식생/서식지)
  - `notice_type=forest_access_restriction` / `forest_fire_alert`
  - `area_kind=hazard_zone`
- **MOIS 식음 매핑은 부모 카테고리로 default** — `02010100` 한식 또는
  `02010000` 부모. provider가 세부 업태 자동 분류 데이터 미제공이라 보수적.
  세부 분류는 향후 ADR.

**발견**:
- `python-kraddr-base/src/kraddr/base/categories.py`는 총 141건 (Tier 0
  sentinel 1 + Tier 1 7 + Tier 2 29 + Tier 3 71 + Tier 4 33).
- maki icon 55종 unique 사용. `park` 11회 (휴양림/공원/트레킹), `lodging` 11회
  (호텔/리조트/모텔/게스트하우스) 등.
- KNPS 위험지역/관측소/산장 같은 카테고리가 현재 트리에 없음 → 카테고리 확장
  필요 (사용자 검토 후 ADR-025 작성).
- v1 `outdoor-feature-etl.md`에 KNPS dataset 단서는 없었음 — 본 §11이 v2의
  첫 정밀 카탈로그.

**다음**: PR#3 push + 사용자 검토. PR 일괄 merge 후 backlog T-200/T-201 (Sprint
5 batch DAG + consistency_reports), ADR-025 (카테고리 확장 — 사용자 결정 후).

---

## 2026-05-24 23:30 (claude)

**작업**: `python-mois-api` 활용 feature 적재 full lifecycle 문서화 + canonical
name 정정 (`python-krmois-api` → `python-mois-api`, ADR-024) + 일괄 rename.

**변경 파일**:
- **신규**:
  - `docs/mois-feature-etl.md` — 4 step lifecycle (A: source DB sync,
    B: 영업중 승격, C: 이력조회 incremental, D: on-demand detail) +
    195 슬러그 카탈로그 + PROMOTED 42종 (식음/숙박/관광/문화/MICE/스포츠/레저) +
    EXCLUDED 분류 + dataset_key 4종 (`mois_license_features_bulk` /
    `_history` / `_closed` / `mois_license_detail`) + PROMOTED_PLACE_KIND_BY_SLUG
    매핑 + Dagster asset 5종.
- **갱신**:
  - `docs/decisions.md` — **ADR-024** 신설 (canonical name 정정 +
    `LEGACY_PROVIDER_ALIASES` `krmois`/`pykrmois`/`python-krmois-api` 추가).
    중간 편집 사고로 일시 삭제된 ADR-023 복원.
  - `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
    (git mv) + 내용 정정 (Step B 좁은 가이드로 재포지셔닝, KRMOIS → MOIS).
  - `docs/provider-contract.md` — canonical name list + dataset_key 표
    (`mois_license_features_bulk/_history/_closed/detail` 4종) + 카탈로그 표.
  - `docs/dagster-boundary.md` — asset 이름 (`feature_place_mois_licenses`) +
    cron 표 (MOIS bulk + incremental 분리).
  - `docs/architecture.md`, `docs/backend-package.md`, `docs/data-model.md`,
    `docs/feature-files-rustfs.md`, `docs/feature-opening-hours.md`,
    `docs/address-geocoding.md`, `docs/debug-fixture-workflow.md`,
    `docs/khoa-beach-info-etl.md`, `docs/test-strategy.md`,
    `docs/windows-reinstall-recovery.md` — `krmois`/`KRMOIS` → `mois`/`MOIS`
    targeted 갱신.
  - `README.md` — 의존 스택 표, 문서 지도 (`mois-feature-etl.md` + `-license-`
    두 항목 별도 링크).
  - `AGENTS.md` — dev 데이터 경로 `KRMOIS localdata zip` → `MOIS`.
  - `pyproject.toml` — provider extras 주석 `python-krmois-api` → `python-mois-api`.
  - `docs/resume.md`, `docs/tasks.md` — 진척도/완료 항목 갱신.

**결정** (ADR-024):
- 외부 라이브러리 실제 이름 검증: PyPI `python-mois-api`, import `mois`,
  GitHub `digitie/python-mois-api`. `python-krmois-api`는 v1 내부 alias였을 뿐
  실제 라이브러리에는 존재하지 않음.
- canonical provider name을 `python-mois-api`로 정정.
- legacy aliases (`krmois`, `mois`, `pykrmois`, `python-krmois-api`)는
  `LEGACY_PROVIDER_ALIASES`에 추가 — v1 호환.
- import 경로 `krtour.map.providers.mois`, loader `krtour.map.mois`, dataset_key
  prefix `mois_*`.

**의사결정 (사용자 위임 사항, 검토 부탁)**:
- **PROMOTED slug 42종** — 식음 6 + 숙박 8 + 관광/문화 9 + 테마파크 5 + MICE 2
  + 스포츠/레저 9 + 쇼핑/도시여가 3. 보수적으로 선정 (TripMate 1차 범위).
- **dataset_key 4분리** — bulk + history + closed + detail. Step별 분리로
  Dagster asset 매핑 명확.
- **mois-license-feature-etl.md 유지** — Step B 좁은 가이드로 재포지셔닝.
  `mois-feature-etl.md`가 full lifecycle (상위 doc). 둘이 충돌하면 full이
  정답이라고 mois-feature-etl.md §1에 명시.
- **legacy alias `python-krmois-api`도 통과** — 본 라이브러리 적재된 기존 feature의
  `provider` 컬럼 마이그레이션은 별도 작업으로 분리.
- **org 이름**: `KRMOIS` → `MOIS`로 일괄. 라이브러리 import 이름과 일치.

**발견**:
- `mois-api` README/AGENTS는 PyPI distribution을 `python-mois-api`라고 명시.
- mois-api 195 업종 카탈로그가 `OPENAPI_SERVICES`/`FILE_DOWNLOADS`/
  `INCREMENTAL_OPENAPI_ENDPOINTS`/`RESPONSE_FIELDS` 정적 dict로 박혀있어
  본 라이브러리에서 그대로 import 가능.
- mois-api의 `mois.db` 모듈이 SQLite/SpatiaLite source DB 적재 + 영업중/폐업
  iterator를 완비 → 본 라이브러리는 reconcile만.

**다음**: PR#3 push + 사용자 검토. PR#1/2/3 모두 merge 후 backlog T-200/T-201
(Sprint 5 운영 진입 전 batch DAG + consistency_reports).

---

## 2026-05-24 22:00 (claude)

**작업**: T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전. 총 14개 신규 docs.

**변경 파일** (모두 신규):
- `docs/weather-feature-normalization.md` (T-002) — forecast_style + timeline_bucket
  + 표준 metric_key 30종 + provider 매핑 + build_weather_card helper.
- `docs/feature-files-rustfs.md` (T-003) — S3 호환 객체저장소 + FeatureFileSource
  → FeatureFile 흐름 + boto3 backend swap (ADR-015).
- `docs/feature-opening-hours.md` (T-004) — Google Places 호환 DTO + DB tables
  + 24/7 표기 + 자정 넘는 period.
- `docs/kraddr-base-types.md` (T-005a) — `python-kraddr-base` 주소/좌표/CRS 사용
  기준. category는 ADR-023으로 본 저장소 이전 명시.
- `docs/address-geocoding.md` (T-005b) — reverse geocoder callable + AddressMatchReport
  match_level 13종.
- `docs/dagster-boundary.md` (T-007) — 라이브러리 vs TripMate 책임 매트릭스 +
  표준 asset 패턴 + Dagster 없이도 호출 가능 (단위 테스트).
- `docs/postgres-schema.md` (T-008) — 4 schema × 20 table reference 카탈로그 +
  CHECK + FK CASCADE + 보관 정책 SQL + Alembic 가이드.
- `docs/debug-fixture-workflow.md` (T-009) — fixture JSON 스키마 + 민감정보 자동
  마스킹 + payload_hash drift 감지 + provider별 ≥3 케이스.
- `docs/feature-db-initialization.md` (T-010) — schema 부트스트랩 + Alembic +
  KrtourMapSettings + AsyncKrtourMapClient 생성 + healthz.
- `docs/tripmate-integration.md` (T-011) — TripMate가 본 라이브러리 import해서
  쓰는 패턴 + Dagster asset + FastAPI router + Admin + 권한/인증 경계.
- `docs/event-feature-etl.md` (T-006a, VisitKorea 축제)
- `docs/mois-license-feature-etl.md` (T-006b, KRMOIS 인허가)
- `docs/opinet-place-price-etl.md` (T-006c, OpiNet 주유소+유가)
- `docs/khoa-beach-info-etl.md` (T-006d, KHOA 해수욕장)
- `docs/krheritage-feature-etl.md` (T-006e, 국가유산청 place/area/event)
- `docs/outdoor-feature-etl.md` (T-006f, 산림청 outdoor)
- `docs/krex-rest-area-feature-etl.md` (T-006g, 도로공사 휴게소+유가+기상)
- `docs/standard-data-feature-etl.md` (T-006h, data.go.kr 표준데이터 5종)
- `docs/notice-feature-etl.md` (T-006i, 4 provider 통합 notice)
- `docs/kma-weather-etl.md` (T-006j, KMA 4종 weather endpoint)
- `docs/place-phone-enrichment.md` (T-006k, Kakao/Naver/Google 전화번호 보강)
- `README.md` — 새 docs 14개 링크 추가.

**결정**: 14개 docs는 v1 패턴을 v2 기준 (krtour.map namespace, async-only, 함수
라이브러리, FastAPI 없음, kraddr-base category 이전)으로 일관 재작성. v1
원문 식별자(`*_DATASET_KEY`, `*_full_scan_job_spec`, `load_*`)는 그대로 유지해
TripMate import 변경 비용 최소화.

**발견**:
- 모든 provider ETL이 같은 패턴: collect → upload → load → sync_state.
  Dagster asset이 동일 5단계 (`docs/dagster-boundary.md` §2).
- v1 산출물은 충실히 검증되어 있고 v2는 namespace + async + 함수 라이브러리
  3 요소만 일관 적용하면 자동으로 정합.
- `notice-feature-etl.md`는 4 provider 통합 단일 doc — provider별 분리 안 함
  (notice_type 정규화가 공통).

**다음**: feature branch `docs/v1-to-v2-feature-ports` push + PR 작성 (PR#1 위
stacked). 사용자 검토 후 squash merge.

---

## 2026-05-24 20:30 (claude)

**작업**: PR-only 룰 추가 + namespace 재명명 (`krtour_map` → `krtour.map`) +
kraddr-base category 모듈 이전 결정 + kraddr-geo 패턴 보강.

**변경 파일**:
- `docs/decisions.md` — ADR-021 (PR-only), ADR-022 (`krtour` namespace),
  ADR-023 (category 이전) 3건 추가.
- `AGENTS.md` — 식별자 표 (Python import → `krtour.map`, category 모듈 출처
  추가), DO NOT #17/#18/#19 추가 (PR-only, flat import 금지, `src/krtour/
  __init__.py` 금지) → 19개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도, DO NOT #19/#20/#21 추가 → 22개 룰.
- `CLAUDE.md` — 5 절대금지를 가장 중요한 5개로 재구성 (PR-only, namespace 1·2위).
- `README.md` — Python import 경로, 디렉토리(`src/krtour/map/` + namespace
  설명), 문서 지도에 `docs/category.md` 추가.
- `pyproject.toml` — `packages.find` (`krtour.map*` + `namespaces=true`),
  `package-data`, `import-linter` root_package + layers + forbidden 계약 갱신,
  coverage source.
- `packages/krtour-map-debug-ui/pyproject.toml` + `README.md` — namespace 정합.
- 일괄 docs 갱신 (rename script): `architecture`, `backend-package`, `decisions`,
  `test-strategy`, `windows-reinstall-recovery`, `dev-environment`, `external-apis`,
  `provider-contract`, `debug-ui-package`, `feature-model`, `resume`, `journal`,
  `CHANGELOG`.
- `docs/category.md` (신규) — `krtour.map.category` 모듈 사양서 11절.
- `docs/agent-guide.md` — §7.5 PR 워크플로 신설 (브랜치 명명, commit format,
  PR 본문 표준 포맷, branch protection, 핸드오프).
- `docs/tasks.md` — Sprint 5 진입 직전 항목 5개 추가 (T-200~T-204: batch DAG,
  consistency_reports, pre-commit hook, CI 워크플로, branch protection 가이드).

**결정**:
- **ADR-021** main 직접 push 금지 — 모든 변경은 feature branch + PR. main에 직접
  들어간 `fc8145f`/`304f2a9`는 ex post facto 인정, 본 ADR 이후 모든 변경은 PR.
- **ADR-022** `krtour` PEP 420 implicit namespace 채택 — `python-krtour-map`은
  `krtour.map`으로 import, `krtour-map-debug-ui`는 `krtour.map_debug_ui`로
  import. 같은 namespace를 share. `src/krtour/__init__.py` 금지.
- **ADR-023** kraddr-base의 category 모듈 (`kraddr.base.categories`, ~2072줄,
  141 enum)을 `krtour.map.category`로 이전. 코드 이전은 코드 작성 단계 진입 시
  별도 PR. 라이선스 호환 (둘 다 GPL-3.0-or-later).

**발견**:
- kraddr-geo ADR-015도 `kraddr` implicit namespace 채택 → 패턴 정합.
- kraddr-geo의 batch DAG + consistency_reports 패턴(ADR-017)이 본 라이브러리의
  Sprint 5 운영에 유용 → T-200/T-201로 백로그 추가.
- 변수 이름 `krtour_map_client`(snake_case)는 변경 안 함 — Python 식별자 명명
  규약과 import path는 별개.

**다음**: feature branch `chore/pr-workflow-namespace-rename-category-migration`
push → PR 작성 (ADR-021 첫 적용 사례). 사용자 리뷰 후 squash merge.

---

## 2026-05-24 19:30 (claude)

**작업**: 디버그 UI를 별도 Python 패키지로 분리 — ADR-020 추가 + 관련 문서/구조
일괄 갱신.

**변경 파일**:
- `docs/decisions.md` — ADR-020 추가. ADR-005 상태에 "위치 부분 superseded" 명시.
- `docs/architecture.md` — 큰 그림 도식에 별도 패키지 블록 추가. `§4 디버그 REST
  API`를 별도 패키지 형태로 재작성. §7 모듈 표에 디버그 패키지 모듈 추가. §8
  ADR-020 추가. §9 v1↔v2 표 갱신.
- `docs/backend-package.md` — 디버그 API 절을 축약하고 `docs/debug-ui-package.md`
  reference로 redirect.
- `docs/debug-ui-package.md` (신규) — 본 패키지 사양서 14절 (정체성/디렉토리/
  의존방향/settings/기동/엔드포인트/응답/OpenAPI/테스트/운영주의/비책임/확장/배포/
  핵심 메시지).
- `AGENTS.md` — 식별자 표 (별도 Python 패키지 명시), TripMate 경계 갱신,
  디버그 API 정책 절 재작성, DO NOT #14 갱신 + #15 신규 (메인 라이브러리 FastAPI
  import 금지) → 총 16개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도 (메인 + 별도 패키지 2 block), DO NOT
  목록에 신규 룰 #15 추가 → 총 19개 룰.
- `CLAUDE.md` — 패키지 분리 1줄 요약 + DO NOT 5개 중 #2/#5 갱신.
- `README.md` — TripMate 연계 문구, 빠른 시작 (디버그 UI 별도 install), 의존
  스택 표 (FastAPI는 별도 패키지로 표시), 디렉토리 (monorepo 2 패키지), 문서 지도.
- `pyproject.toml` — `[api]` extra 제거 (ADR-020 §후속). `import-linter`에 두
  번째 계약 추가 (`krtour_map`에서 fastapi/uvicorn/starlette import 금지).
- `.env.example` — `KRTOUR_MAP_DEBUG_API_*` → `KRTOUR_MAP_DEBUG_UI_*` 갱신 +
  주석.
- `docs/test-strategy.md` — e2e 코드 예시의 `from krtour.map.api.app import ...`
  → `from krtour.map_debug_ui.app import ...`.
- `packages/krtour-map-debug-ui/pyproject.toml` (신규) — 별도 패키지 pyproject.
- `packages/krtour-map-debug-ui/README.md` (신규) — 패키지 README.

**결정**: **ADR-020** — 디버그 UI는 별도 Python 패키지 `krtour-map-debug-ui`로
분리. monorepo 안 `packages/krtour-map-debug-ui/`에 위치. 메인 라이브러리에서
FastAPI/Uvicorn 의존성 제거. ADR-005의 위치 부분(`krtour.map.api`)은 본 ADR로
superseded; 인증 없음 + 내부망 전용 정책은 그대로 유지.

**발견**:
- 메인 라이브러리가 FastAPI 의존을 짊어지면 TripMate에 불필요한 의존성이
  딸려간다. 분리로 install footprint 축소.
- `import-linter`의 `forbidden` 계약으로 메인 패키지의 FastAPI import를 CI에서
  자동 차단 가능.
- v1의 `packages/krtour-map-debug-ui/` 디렉토리 패턴(monorepo Python 서브패키지)
  과 일관됨.

**다음**: 사용자 검토 후 commit + push. T-002(weather-feature-normalization.md
v1→v2 정리)로 복귀.

---

## 2026-05-24 19:00 (claude)

**작업**: v2 설계 단계 진입 — main을 orphan으로 새로 시작하고 핵심 문서 일괄 작성.

**변경 파일**:
- 루트:
  - `AGENTS.md` (지시 우선순위, DO NOT 18개, TripMate 함수 라이브러리 경계, 디버그 API 인증 없음)
  - `README.md` (정체성, 빠른 시작, 의존 스택 표, 문서 지도)
  - `SKILL.md` (DO NOT 18개 + 도메인 어휘 + 자주 묻는 작업)
  - `CLAUDE.md` (1쪽 진입 요약)
  - `LICENSE` (GPL-3.0-or-later)
  - `.gitignore`, `.gitattributes`, `.env.example`
  - `pyproject.toml` (스택 placeholder + ruff/mypy/pytest 설정 + import-linter 계약 박힘)
- `docs/`:
  - `architecture.md` (의존 방향 + 데이터 흐름 + 모듈 표 + v1 대비 변경)
  - `decisions.md` (ADR-001 ~ ADR-019)
  - `data-model.md` (4 schema × 16 table 전체 DDL + 인덱스 + CHECK)
  - `performance.md` (인덱스 설계 + 공간 쿼리 가이드 + bulk + 안티패턴 매트릭스)
  - `test-strategy.md` (4단계 테스트 + Fake repo + EXPLAIN 검증 + Coverage 목표)
  - `backend-package.md` (라이브러리 진입점 + 디버그 REST API + 사용 시나리오)
  - `agent-guide.md` (첫 5분 + ADR 형식 + 변경 분류별 체크리스트)
  - `dev-environment.md` (WSL ext4/NTFS + Docker PostGIS + 초기 셋업)
  - `windows-reinstall-recovery.md` (세션 복구 + PR handoff 노트 포맷)
  - `feature-model.md` (Feature DTO + 5 detail + opening hours + weather/price)
  - `provider-contract.md` (wrapper 금지 + canonical name + dataset_key 표 + 변환 함수 골격)
  - `external-apis.md` (provider별 API 키 발급/호출 + 비용 + 모니터링)
  - `tasks.md`, `resume.md`, `journal.md` (운영 docs 초기)

**결정**:
- ADR-001 ~ ADR-019 19건 박음. 핵심:
  - **ADR-003** TripMate ↔ 라이브러리는 함수 직접 호출 (REST 없음).
  - **ADR-005** 디버그 REST API는 인증 없음, 내부망 전용.
  - **ADR-006** provider adapter/wrapper 신규 생성 금지.
  - **ADR-007** 의존 스택 — kraddr-geo와 동일.
  - **ADR-008** PostGIS는 `x_extension` schema 격리.
  - **ADR-012** 공간 쿼리 1회 변환 + `coord_5179` 컬럼.
  - **ADR-013** bulk insert는 `psycopg.copy_*` 우선 (30k 안전 마진).
  - **ADR-014** 4단계 테스트 + Coverage 목표 (core 90+ / infra 80+ / 전체 80+).
  - **ADR-018** `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기).
  - **ADR-019** KST aware datetime만 허용.
- git: 현재 작업 모두 commit 후 `v1` 브랜치 생성 + origin push, main orphan 재시작
  + force-push origin/main.

**발견**:
- `python-krtour-map-spec.docx` (저장소 루트, 약 80쪽)는 v1 산출물 + SPEC V8 정합 +
  kraddr-geo 디시플린 종합 reference로 유용.
- 사용자가 명시: TripMate 연계는 함수 라이브러리 형태, REST는 디버그 UI + 향후
  내부 활용 (인증 없음). 이를 ADR-003/ADR-005로 박음.
- 사용자 강조: 속도 최적화는 설계 단계부터, 테스트는 촘촘하게.
  → `docs/performance.md` (인덱스 설계 + 안티패턴), `docs/test-strategy.md`
    (4단계 + EXPLAIN 검증)으로 박음.
- kraddr-geo와 동일 스택 (PostgreSQL + PostGIS + SQLAlchemy 2 async + GeoAlchemy2
  + GeoPandas)을 ADR-007로 명시.

**다음**: T-002 — `docs/weather-feature-normalization.md` 작성. v1 docs를
v2 기준으로 정리해 옮긴다.

---

## 2026-05-24 18:00 (claude)

**작업**: v1 작업 보존 — 현재 main의 모든 작업(provider ETL, 디버그 UI,
docs, spec docx)을 `v1` 브랜치로 commit하고 origin/v1로 push.

**변경 파일**: 56 files changed, 2858 insertions(+), 490 deletions(-)
- providers: visitkorea, mois (구 krmois), krheritage, opinet, krex, krforest, khoa,
  datagokr (standard 5 + extras), notices
- DB 스키마, RustFS file 메타, 전화번호 보강
- Debug UI 패키지 (packages/krtour-map-debug-ui)
- Extensive docs 수정
- `python-krtour-map-spec.docx` (AI 에이전트용 사양 80쪽)

**결정**: 사용자 요청 — v1 보존, main 재시작, orphan 히스토리, origin force-push.

**발견**: `~$python-krtour-map-spec.docx` Word lock 파일을 `.gitignore`에 추가.

**다음**: 새 main(orphan) 시작 후 v2 설계 문서 일괄 작성.
