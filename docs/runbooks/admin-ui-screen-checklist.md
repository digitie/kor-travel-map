# admin UI 화면별 점검 체크리스트 (T-218f)

`krtour-map-admin` frontend(Next.js, 포트 9012)의 route 전수(현재 17)를 **운영 회귀·
a11y·e2e 커버 관점에서 점검**하기 위한 체크리스트다. T-218(admin UI 상세 점검 + a11y/e2e 완비)의
점검 항목을 화면 단위로 고정하고, 현재 e2e 커버 상태를 매핑한다.

> 정본 계획: `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`.
> e2e 실행: **서버=WSL(`npm run dev` :9012), Playwright=Windows**(`docs/dev-environment.md`,
> `playwright.config.ts` 머리말). admin/ops 스펙은 route-mock 기반이라 backend 없이도
> 돈다. `/etl`만 실 backend(:9011, `/debug/etl`) 필요.
> 검증 게이트(프론트 PR): `gen:types:check`(drift 0) · `type-check` · `lint` ·
> env 명시 `build` · Windows Playwright e2e.

## 1. 점검 항목 정의

각 화면을 아래 공통 축으로 점검한다(해당 없으면 `—`).

- **목록/필터**: 필터 조합·검색(`q`) 입력이 쿼리에 반영되는가.
- **정렬**: sort/order 파라미터가 동작하는가(목록 화면).
- **cursor**: keyset cursor 첫·다음·소진(`meta.page.next_cursor=null`) 처리가 맞는가.
- **빈 상태**: 0건일 때 안내 문구가 뜨는가.
- **에러 상태**: 5xx/`problem+json`에서 `role=alert`(assertive) 배너가 뜨는가(T-218e).
- **kill-switch**: 위험 액션이 서버 `admin_destructive_enabled`/`command_enabled`에 따라
  plan-only로 안전하게 동작하는가(create/restore/swap/run-now/load 등).
- **a11y**: 폼 입력이 `<label htmlFor>`로 연결되고(필요 시 `aria-invalid`/`aria-describedby`),
  성공 결과는 `role=status`(polite)로 안내되는가(T-218b/e).
- **e2e**: Playwright 스펙 커버 여부(파일).

## 2. 화면별 매트릭스 (16 route)

| route | 목록/필터 | 정렬 | cursor | 빈 상태 | 에러 | kill-switch | a11y(폼) | e2e |
|---|---|---|---|---|---|---|---|---|
| `/` (홈 대시보드) | 메트릭/최근 job | — | — | ✓ | ✓ | — | — | `home.spec` |
| `/features` (지도) | kind 필터 | — | — | ✓ | ✓ | — | — | `features.spec` |
| `/admin/features` | q/kind/status/has_issue | ✓ sort/order | ✓ | ✓ | ✓ | deactivate | 필터 라벨 | `admin-ops` |
| `/admin/features/change-requests` | status/action/q | — | — | ✓ | ✓ | review_mode·approve/reject | ✓ `<label htmlFor>`(기존) | `admin-ops`(+음성 JSON, T-218d) |
| `/admin/issues` | q/status/severity/type/provider/dataset/bbox | — | ✓ | ✓ | ✓ | manual_override | ✓ manual-override FormField(T-218b-3) | `admin-ops`(+검증/포커스) |
| `/admin/dedup-reviews` | status/kind | — | ✓ | ✓ | ✓ | accept/reject/ignore/merge | — | `admin-ops`(smoke) |
| `/admin/enrichment-reviews` | status/kind | — | ✓ | ✓ | ✓ | accept/reject/ignore | — | `admin-ops`(cursor) |
| `/admin/feature-update-requests` | status | — | — | ✓ | ✓ | dry-run/run-now | ✓ FormField+검증(T-218b-1) | `admin-ops`(+검증/포커스) |
| `/admin/poi-cache-targets` | external_system | — | ✓ | ✓ | ✓ | upsert/delete | ✓ FormField+검증(T-218b-1) | `admin-ops`(+검증/포커스) |
| `/admin/offline-uploads` | status/provider/dataset | — | ✓ | ✓ | ✓ | upload→validate→load(Dagster) | ✓ FormField(T-218b-2) | `admin-ops`(mutation flow) |
| `/admin/backups` | command_enabled 배지 | — | — | ✓ | ✓ | create/restore/swap(plan-only 기본) | label(기존) | `admin-ops`(T-218c, 렌더+액션) |
| `/admin/dagster` | run/tick 목록 | — | — | ✓ | ✓ | nux-seen | — | `dagster.spec`(smoke) |
| `/ops/import-jobs` | status/kind | — | ✓ | ✓ | ✓ | — | 필터 라벨 | `admin-ops`(smoke) |
| `/ops/providers` (T-217g) | 요약 배지(failing/stale) | — | —(bounded) | ✓ | ✓ | — | — | `admin-ops`(렌더+실패 경고) |
| `/ops/consistency` | status | — | — | ✓ | ✓ | — | — | `admin-ops`(smoke) |
| `/ops/logs` | system/api tab + level/source/method/path/min_status | — | ✓ | ✓ | ✓ | — | 필터 라벨 | `admin-ops`(tab/filter) |
| `/etl` | provider/dataset/source | — | — | ✓ | ✓ | preview only(DB write 없음) | ✓ RHF+zodResolver+Field(기존) | `etl.spec`(실 backend) |

범례: ✓=확인/적용, `—`=해당 없음. e2e 열의 `admin-ops`는 `e2e/admin-ops.spec.ts`.

## 3. T-218 적용 결과 요약

- **a11y(G-1) 갭 해소**: bare `aria-label`(visible 라벨 부재) 4개 폼 — `poi-cache-targets`,
  `feature-update-requests`, `offline-uploads`, `issues` manual-override — 전부 `FormField`/
  `FormSelect`/`FormTextArea`로 전환(`<label htmlFor>` + `aria-describedby` + `aria-invalid` +
  첫 에러 포커스). `change-requests`·`/etl`은 이미 a11y 완비라 비대상.
- **e2e 커버**: admin/ops 16 route 전부 e2e 커버(직전 미커버였던 `/admin/backups`를 T-218c로
  채움). 폼 음성 경로(JSON·필수·좌표) e2e 4폼(T-218d).
- **안내(T-218e)**: `Alert`가 variant별 live-region — 에러=`role=alert`(assertive),
  성공/정보=`role=status`(polite).
- **모달 focus trap 비해당**: 본 admin UI는 오버레이 모달/드로어가 없는 **인라인 사이드
  패널** 구조라 modal focus trap은 적용 대상이 아니다. 폼 제출 시 첫 에러 필드 포커스
  이동은 적용됨(T-218b).

## 4. 신규 화면/폼 추가 시 점검 절차

1. 폼 입력은 `ui/form-field.tsx`의 `FormField`/`FormSelect`/`FormTextArea`를 쓴다(bare
   `aria-label` Input 금지). 제출 검증은 `lib/form-validation.ts`의 `validateForm` +
   `firstErrorField`로 첫 에러 포커스.
2. 성공/정보 결과는 기본 `Alert`(=`role=status` polite), 에러는 `Alert variant="destructive"`
   (=`role=alert` assertive)로 표시.
3. 목록은 `meta.page.next_cursor` keyset cursor를 소비(`data.next_cursor` 사용 금지 —
   ADR-048).
4. e2e: `e2e/admin-ops.spec.ts`에 route-mock(생성 OpenAPI `components["schemas"]` 바인딩)
   + 렌더/필터/액션/음성 경로 단언을 추가하고, 본 표에 행을 채운다.
5. 위 §1 게이트 전수 통과 후 PR.
