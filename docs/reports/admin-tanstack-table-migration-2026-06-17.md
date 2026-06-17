# admin UI 테이블 → TanStack React Table + React Virtual 마이그레이션 계획 (2026-06-17)

`packages/kor-travel-map-admin/frontend`의 모든 테이블을 공용 headless `DataTable`
(@tanstack/react-table v8 + @tanstack/react-virtual v3) 기반으로 교체한다. 본 문서는
변경 범위·아키텍처 결정·테이블별 계획·**세분화된 e2e 테스트 플랜**의 단일 정본이다.

## 1. 결정 사항 (사용자 확정 2026-06-17)

1. **가상화 범위**: 모든 테이블을 react-table headless 모델로 통일하되, `react-virtual`은
   **대용량/무한 목록에만** 적용한다(소형 server-paged 테이블은 semantic markup 유지 →
   a11y·기존 Playwright 셀렉터 보존). 가상화 OFF가 기본, `virtualized` opt-in.
2. **동작**: 기존 동작 보존 **+ UX 개선** — 데이터 계층이 허용하는 곳에 클릭형 정렬 헤더
   (`aria-sort`, 접근성 이름은 헤더 텍스트 그대로) 추가, opt-in 다중 행 선택 + bulk action 툴바.
3. **e2e 실행**: 본 머신은 frontend 툴체인만 있고 Python venv/DB 없음. route-mocked spec
   (feature-detail · import-job-detail · feature-update-request-detail)만 Windows frontend로
   라이브 실행하고, backend 의존 spec(curated · features-new · admin-ops)은 별도 환경에 위임.

## 2. 버전 (PIN)

- `@tanstack/react-table` `^8.21.3` (STABLE v8). **v9 alpha/beta 금지**(useTable/tableFeatures
  API는 미출시). `@tanstack/react-virtual` `^3.14.3`(peerDeps react ^19). react-query는 기존 ^5.

## 3. 아키텍처 — 공용 `DataTable` (`src/components/ui/data-table.tsx`)

- 기본 경로: semantic shadcn `Table/TableHeader/TableRow/TableHead/TableCell`로 `flexRender` →
  `role=table/columnheader/row/cell` 보존.
- 가상화 경로(`virtualized`): `display:grid` + sticky `thead`(z-10) + absolute rows +
  `useVirtualizer`(measureElement, Firefox guard) + **명시 ARIA**(role + `aria-rowcount`/
  `aria-rowindex`) + 컬럼 `getSize()` 폭.
- 데이터 연산은 기본 server-side: `manualSorting` 등으로 react-query가 cursor 페이징/필터/정렬을
  계속 담당, DataTable은 `data`만 받는다. 완전 client 목록만 `manualSorting={false}`로 client 정렬.
- 기능: 정렬 헤더(`DataTableColumnHeader`, glyph `aria-hidden`), 로딩(skeleton)/에러(alert)/
  empty(colSpan row) 내장, `onRowClick`+`isRowActive`(detail pane `data-state="selected"`),
  opt-in 선택(`enableRowSelection` → 체크박스 컬럼 `__select__` + `renderBulkActions`).
- 페이지의 필터/검색/cursor pager/page-size 컨트롤은 **테이블 바깥에 그대로 유지**(forward-only
  cursor 계약 보존). DataTable은 표 자체 + 상태 + 선택/정렬만 담당한다.

## 4. 대상 테이블 (≈22) 과 위험도

server-side cursor 페이징·필터, 정렬은 대부분 헤더 비클릭(admin-features만 서버 sort dropdown,
features map은 client ko 정렬). 행 선택/bulk 없음(전부 form checkbox), per-row action 버튼 +
row-click detail-pane만 존재.

| 파일 | 테이블 | 위험 | virtual | 정렬 헤더 | 선택/bulk |
|---|---|---|---|---|---|
| backups-client | 백업 목록 | low | no | created_at/size | – |
| feature-update-requests-client | 요청 목록 | low | no | created_at/status | – |
| ops/providers | provider dataset(정책 헤더 보존) | low | no | freshness | – |
| admin/dagster | run 목록 | low | no | 시작시각 | – |
| home dashboard | 최근 import jobs | low | no | – | – |
| ops/import-jobs | job 목록 | low | no | created_at | – |
| import-job-detail | events | low | no | – | – |
| dedup-reviews | 중복 후보(merge picker→row expand) | med | no | score/distance | accept/reject bulk |
| enrichment-reviews | 보강 매칭(cursor) | med | no | name_score | – |
| poi-cache-targets(+nearby) | 타깃 목록 | med | no | updated_at | delete bulk(opt) |
| ops/logs ×3 | system/API/job-events | med | API/logs는 옵션 | created_at | – |
| ops/consistency ×2 | reports + integrity | med | no | created_at/severity | – |
| admin/features/change-requests | 변경 요청 | med | no | created_at | – |
| admin/features/new(nearby preview) | 근접 미리보기 | med | no | distance | – |
| **curated-features ×3** | 후보+rules+tripmate preview | high | 후보 large 시 | updated_at | **select/archive bulk** |
| **admin-issues** | 무결성 이슈(detail pane) | high | no | severity/created_at | resolve bulk(opt) |
| **offline-uploads(+preview)** | 업로드 목록 + CSV preview | high | no | created_at | – |
| **admin-features** | feature 목록(서버 sort→헤더, ≤500행) | high | yes(대용량) | AdminFeatureSort 키 | deactivate bulk(opt) |
| **features map list** | bbox 무한 목록(client ko 정렬) | high | yes | name(ko) | – |

가상화는 **features map list / admin-features(고 page-size) / curated 후보(large)** 에 우선 적용.
정렬 헤더는 서버 허용 컬럼(AdminFeatureSort) 또는 fully-loaded client 테이블에만 `enableSorting`.

## 5. 세분화된 e2e 테스트 플랜

원칙: **헤더 텍스트(`columnheader` 접근성 이름)·empty/placeholder 문구·필터/페이저 라벨은
그대로 보존**. 정렬 버튼은 헤더 텍스트를 라벨로(글리프 `aria-hidden`)→ `getByRole('columnheader',
{name})` 유지. 선택 컬럼이 추가되는 테이블은 cell 개수/인덱스 기반 단언을 보정. 가상화 테이블은
off-screen 행이 DOM에 없으므로 `scrollToIndex`/scroll-into-view 후 `row.click`/`getByText`.

### 5.1 기존 spec 보정 (위험순)

- **admin-ops.spec.ts** (최대): `getByRole('columnheader',{name})` 12개 테이블 — 헤더 텍스트 보존
  검증. row-click→마지막 cell 버튼 워크플로(admin-features detail/deactivate, providers 필터 후
  특정 dataset row `getByText`) — 선택 컬럼 추가 시 마지막-cell 가정 점검, 정렬 헤더 버튼이 row-click과
  충돌하지 않는지(헤더는 thead). delete 후 `toHaveCount(0)` — 비가상 테이블이라 안전, 가상 전환 시 보정.
- **curated-features.spec.ts** (라이브 smoke): 헤더/필터 aria-label 보존. select/archive **bulk
  툴바** 추가 시 신규 단언. row 선택 체크박스 aria-label("행 선택")·전체선택("전체 선택").
- **features-new.spec.ts** (라이브 smoke): nearby preview 테이블 헤더 보존(backend 의존 → 위임).
- **feature-detail.spec.ts / import-job-detail.spec.ts / feature-update-request-detail.spec.ts**
  (route-mocked, **본 머신 라이브 실행 대상**): detail 내 sub-table(sources/issues/overrides/history/
  files, import-job events) 헤더·empty('event가 없습니다.') 보존. testid·heading 유지.

### 5.2 신규 spec

- **data-table-sort.spec.ts**: 정렬 헤더 클릭 → `aria-sort` ascending/descending 토글 +
  (client 테이블) 행 순서 변화. 헤더 접근성 이름 불변.
- **data-table-selection.spec.ts**: 행 체크박스 선택 → bulk 툴바 "N개 선택됨" 노출 → bulk action 호출.
  전체선택 indeterminate.
- **data-table-virtualized.spec.ts** (seeded >200행, backend 환경 위임): 초기 DOM 행 수 < 전체,
  `scrollToIndex`/스크롤 후 하단 행 등장, `aria-rowcount` == 전체, sticky 헤더 가시.

### 5.3 component(vitest) — Task #3

jsdom + @testing-library/react 추가. DataTable 단위: semantic role 렌더, 정렬 헤더 aria-sort 토글+
콜백, 로딩/empty/에러, 선택+bulk, onRowClick vs cell stopPropagation, 가상화 윈도잉+aria-rowcount.

### 5.4 실행 게이트

`gen:types:check` → `tsc`(+`type-check:e2e`) → `eslint .` → `vitest run` → (Windows) route-mocked
Playwright. backend 의존 spec·seeded 가상화 spec은 venv+DB 환경에서 별도 실행(#449 연장).

## 6. 작업 분해 (tasks #1~#11)

#1 deps(완료) · #2 DataTable(완료) · #3 vitest component · #4 본 문서 · #5 low-risk · #6 med-risk ·
#7 high-risk(+virtual) · #8 e2e 보정/신규 · #9 로컬 게이트 · #10 route-mocked Playwright · #11 PR.
실행 순서: 2→(3,5,6,7 병렬, 파일 disjoint)→8→9→10→11. 마이그레이션은 파일 단위로 frontend-developer
서브에이전트에 분배(공용 DataTable 계약 고정 후).
