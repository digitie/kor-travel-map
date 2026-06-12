# T-218 — kor-travel-map admin UI 상세 구현 점검 + a11y/e2e 완비 계획 (2026-06-10)

> **목적**: TripMate의 "Claude Sprint 4 PR-C 프론트"(화면별 상세 구현 + E2E 슬라이스,
> TripMate `docs/tasks.md` §"Claude Sprint 4 PR-C 프론트")와 동급의 **화면별 상세 점검 +
> 잔여 갭 완비** 작업을 kor-travel-map admin/ops UI에 대해 정의한다.
> **상태**: 계획서 (정본 task는 `docs/tasks.md` T-218). 코드 변경 없음 — 본 문서는 실행
> 청사진이다.
> **실측 기준**: `origin/main` `1128626`(T-212d 재측정 머지 후), `packages/kor-travel-map-admin/
> frontend/`. admin UI는 **16 route 전부 구현 + e2e 15/16 커버**로 이미 성숙도가 높다
> (T-212b 완료). 따라서 본 task는 신규 화면 구현이 아니라 **일관성·접근성·e2e 완전성의
> 마지막 보강 + 화면별 회귀 점검**이다.

---

## 1. 현재 상태 매트릭스 (16 route × 성숙도/a11y/e2e)

| route | 클라이언트 파일 | 성숙도 | a11y | e2e |
|---|---|---|---|---|
| `/` | `home-client.tsx` | 완전 | 기본 | ✅ home.spec |
| `/features` | `features-client.tsx` | 완전 | 기본+키보드 | ✅ features.spec |
| `/admin/features` | `admin-features-client.tsx` | 완전 | 기본 | ✅ admin-ops.spec |
| `/admin/features/change-requests` | `feature-change-requests-client.tsx` | 완전(13필드 폼) | 기본 | ✅ approve/immediate/update/delete |
| `/admin/issues` | `admin-issues-client.tsx` | 완전(6액션) | 기본 | ✅ 필터/상세(액션 JSON 입력 미터치) |
| `/admin/dedup-reviews` | `dedup-review-client.tsx` | 완전 | 기본 | ✅ smoke |
| `/admin/enrichment-reviews` | `enrichment-review-client.tsx` | 완전 | 기본 | ✅ cursor pagination |
| `/admin/feature-update-requests` | `feature-update-requests-client.tsx` | 완전 | 기본 | ✅ 폼 필드 |
| `/admin/poi-cache-targets` | `poi-cache-targets-client.tsx` | 완전 | 기본 | ✅ upsert→nearby→delete |
| `/admin/offline-uploads` | `offline-uploads-client.tsx` | 완전 | 기본 | ✅ upload→preview→validate→load |
| `/admin/backups` | `backups-client.tsx` | 완전 | 기본 | ❌ **미커버** |
| `/admin/dagster` | `dagster-client.tsx` | 완전 | 기본 | ✅ dagster.spec(smoke) |
| `/ops/import-jobs` | `import-jobs-client.tsx` | 완전 | 기본 | ✅ smoke |
| `/ops/consistency` | `consistency-client.tsx` | 완전 | 기본 | ✅ smoke |
| `/ops/logs` | `logs-client.tsx` | 완전 | 기본 | ✅ tab/filter |
| `/etl` | `etl-client.tsx` | 완전 | 기본 | ✅ etl.spec |

**"기본 a11y"의 의미**: semantic HTML(`<table>`/`<select>`/`<label>`) + ARIA role
(`alert`/`navigation`/`columnheader`) + `Input`/`NativeSelect`의 `aria-invalid` 지원은
있으나, **폼 레벨 wrapper(label↔error `aria-describedby` 자동 연결, 제출 검증 시
`aria-invalid` 토글, 첫 에러 필드 포커스 이동)는 부재**. 공통 `Field`(`ui/field.tsx`)는
`role="group"`/`role="alert"` 컨테이너만 제공하고 각 화면이 수동 조립한다. → TripMate가
`FormField`/`FormSelect`/`FormTextArea`로 일원화한 패턴이 krtour admin에는 없다.

## 2. 식별된 갭 (우선순위)

| ID | 갭 | 우선 | 근거 |
|---|---|---|---|
| G-1 | **공통 폼 a11y wrapper 부재** — 16화면 중 폼 보유 화면(change-requests 13필드, issues 액션 JSON, feature-update-requests, poi-cache-targets, offline-uploads, etl)이 label/error/포커스를 수동 처리 | P0 | `ui/field.tsx`는 컨테이너만; `Input`은 라벨 없이 `aria-label`/placeholder만(예: admin-features 검색) |
| G-2 | **`/admin/backups` e2e 미커버** — 유일한 e2e 공백 화면, restore/restore-swap은 위험 액션이라 회귀 보호 필요 | P0 | e2e 스펙 부재(15/16) |
| G-3 | **위험 액션 폼 검증 e2e 공백** — issues의 manual_override(address/coord JSON 파싱), change-requests의 payload JSON 등 "잘못된 입력→에러 표시" 경로가 e2e에 없음 | P1 | admin-ops.spec가 정상 경로 위주 |
| G-4 | **focus 관리** — 상세 패널(drawer) open/close 시 focus trap·복원, 액션 confirm 후 포커스 이동 미실장 | P1 | drawer는 onClick 상태 토글만 |
| G-5 | **aria-live 부재** — 목록 로딩/액션 성공·실패가 `Alert`로 표시되나 `aria-live`/`aria-busy`가 없어 스크린리더가 갱신을 못 읽음 | P1 | `Alert` 정적 role=alert만 |
| G-6 | **화면별 상세 회귀 점검 미정리** — 각 화면의 필터·정렬·cursor·빈상태·에러상태·권한(kill-switch)·envelope(meta.page) 소비를 화면 단위 체크리스트로 고정한 문서가 없음 | P2 | T-212b는 구현 중심, 점검 체크리스트 부재 |

## 3. 작업 분해 (PR-C 미러 — 화면별 슬라이스 + 게이트)

> 각 sub-task는 1-PR 단위. 검증 게이트(전 PR 공통): `npm run gen:types:check`(drift 0)
> + `npm run type-check`(tsc, e2e tsconfig 포함) + `npm run lint` + env 명시
> `npm run build` + Windows 호스트 Playwright(`E2E_BASE_URL=http://127.0.0.1:9014 npm -w
> packages/kor-travel-map-admin/frontend run e2e`). a11y 변경 PR은 변경 화면 e2e에 라벨/에러/
> 포커스 단언을 함께 추가한다.

### T-218a — 공통 폼 a11y wrapper 도입 (G-1, P0)
- `ui/`에 `FormField`(label↔input `htmlFor`/`id`, `aria-describedby`→error, 제출 검증 시
  `aria-invalid` 토글, `forwardRef`로 첫 에러 포커스) + `FormSelect`(NativeSelect 기반) +
  `FormTextArea`(JSON payload 입력용) 추가. 기존 `Field`/`Input`/`NativeSelect` 위에 얇게.
- 클라이언트측 `validateForm(schema, values)` util(필드별 메시지 + 첫 에러 필드 키) —
  TripMate `lib/formValidation.ts` 패턴 차용(라이브러리 추가 없이).
- 회귀 안전: 시각 스타일 불변(기존 `labelClassName` 보존), testid 보존.

### T-218b — 폼 화면 a11y 적용 (G-1 후속, P0)
화면별로 FormField/FormSelect/FormTextArea 적용 + 해당 e2e에 "라벨로 입력 접근(getByLabel)
/ 필수 누락 시 에러+aria-invalid+포커스" 단언 추가:
- `/admin/features/change-requests`(13필드, JSON payload는 FormTextArea)
- `/admin/issues` manual_override(address/coord JSON) + 액션 사유
- `/admin/feature-update-requests`(coord/radius/providers/dataset_keys)
- `/admin/poi-cache-targets`(external_system/target_key/coord/radius/scope_mode)
- `/admin/offline-uploads`(provider/dataset_key/sync_scope/created_by)
- `/etl`(provider/dataset/source select)

### T-218c — `/admin/backups` e2e 신설 (G-2, P0)
- Playwright route mock으로 backup 목록 렌더 → 행 선택 → manifest/restore target 상세 →
  **create**(POST) / **restore**(staging, execute opt-in) / **restore-swap**(hot-swap 승인
  경계) 요청 고정. 위험 액션은 confirm 단계 + 성공/실패 alert까지 단언.

### T-218d — 위험 액션 폼 검증 e2e (G-3, P1)
- 잘못된 JSON(payload/address/coord) 입력 → 클라이언트 검증 에러 표시(서버 미호출) 단언.
- 배치/캡 경계(offline upload 행 수, change-request 필수 필드 누락) 음성 경로 e2e.

### T-218e — focus 관리 + aria-live (G-4/G-5, P1)
- 상세 drawer open 시 첫 포커스 이동·Escape 닫기·복원(trigger 행으로). 액션 confirm 모달
  focus trap.
- 목록/액션 상태 영역에 `aria-live="polite"`(로딩/성공) + `aria-busy`. `Alert`는 유지.
- 변경 화면 e2e에 키보드 흐름(Tab/Escape) 단언 추가.

### T-218f — 화면별 상세 회귀 점검 체크리스트 (G-6, P2)
- 16 route 각각에 대해 [필터 조합 / 정렬 / keyset cursor 첫·다음·소진(null) / 빈 상태 /
  에러 상태(503·problem+json) / kill-switch 비활성 시 액션 버튼 차단 / `meta.page` 소비 /
  weather·nearby 등 보조 API] 체크리스트를 `docs/runbooks/`(예: `admin-ui-screen-checklist.md`)
  로 고정하고, 각 항목의 e2e 커버 여부를 매핑. 미커버 항목은 T-218b~e 또는 후속으로 환원.

## 4. 의존·순서·범위 경계

- **순서**: T-218a(wrapper) → T-218b(적용)·T-218c(backups e2e) 병렬 → T-218d·T-218e →
  T-218f(점검 문서). a11y wrapper가 폼 화면 e2e 단언의 토대이므로 T-218a 선행.
- **T-212e와의 관계**: T-212e는 **실데이터 full reload/적재 검증**(백엔드·운영), T-218은
  **UI 일관성·접근성·e2e 완전성**(프론트). 독립 — 병렬 가능. 단 envelope/`meta.page`
  실제 응답 확인은 T-212e seed를 재사용하면 좋다.
- **R&R**: 본 task는 kor-travel-map admin/ops UI **전용**. 사용자 대면 `/features` 지도의
  제품 UX는 TripMate 책임이며 여기서는 admin 관점의 smoke 유지만 한다.
- **금지룰 준수**: 신규 라이브러리 추가 없이 기존 `@base-ui`/`ui/*` 위에 구성. provider
  변환·feature 정규화는 건드리지 않는다(프론트 표현 계층만).

## 5. 완료 기준 (DoD)

- [ ] 폼 보유 전 화면이 FormField/FormSelect/FormTextArea로 일원화 + label/error/포커스 e2e 단언.
- [ ] e2e 커버리지 16/16 (backups 포함), 위험 액션 음성 경로 포함.
- [ ] focus trap/복원 + aria-live가 drawer·액션 상태에 적용.
- [ ] `docs/runbooks/admin-ui-screen-checklist.md`로 화면별 점검 항목·e2e 매핑 고정.
- [ ] 전 PR 게이트(gen:types:check/type-check/lint/build/Windows Playwright) green.
