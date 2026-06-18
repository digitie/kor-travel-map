# resume.md — 현재 진척도와 다음 한 작업

## 2026-06-18 claude 작업 메모 — T-452 OpenAPI problem+json 보강 완료

`T-452-openapi-problem-json`을 종결했다. 생성 OpenAPI가 에러 응답을 problem+json으로 선언한다.

- **구현**: `create_app`의 custom `app.openapi()`가 모든 operation의 4xx/5xx·`default` 응답을
  RFC7807 `application/problem+json`(`ProblemDetail`/`ProblemDetailError`)으로 선언. FastAPI 자동
  422도 problem+json으로 대체, orphan(`HTTPValidationError`) 제거. 핸들러별 `responses=` 대신
  중앙 핸들러(`_error_response`)와 대칭인 중앙 주입 방식.
- **산출물**: `openapi.json`/`openapi.user.json` 재생성 + admin/user-client `gen:types`. e2e mock 1건
  (`change-requests-lifecycle.spec.ts`)을 `ProblemDetail`로 재바인딩.
- **검증(Python 3.13 컨테이너)**: ruff·`mypy --strict -p kortravelmap.api`·api pytest 전수 green,
  `export_openapi.py --check` drift gate OK, admin/user-client `gen:types:check`·type-check OK.
  로컬 venv 부재라 throwaway `python:3.13` Docker로 CI 동등 환경 재현.

**다음 한 작업**: 이 저장소 즉시 실행 가능한 in-repo 트랙 없음. 잔여는 `T-229-buildx`
(배포환경 `GITHUB_TOKEN`)·`T-101`(MV 보류)·`T-AUDIT-0616` F-01 옵션 A(deferred)뿐.

## 2026-06-18 claude 작업 메모 — T-ADMIN-TANSTACK 종결 + item-4(라이브 e2e) 결정

- **T-ADMIN-TANSTACK 종결**: (a) backend-의존 e2e는 2026-06-17 라이브 스택에서 이미 57/0
  통과로 검증됨 — 사용자 결정(이미 검증됨 → 재실행 생략)에 따라 재기동 없이 닫음. (b) bulk 정책
  가드(완료 review 재결정 차단 · curated bulk archive confirm)는 main에 이미 구현됨 확인.
- **item-4 라이브 Docker 결정**: 신규 스택 기본 포트(pg 5432 · rustfs 12101)가 공유 인프라
  (kor-travel-geo-postgres 등)와 충돌하고, repo `.env`가 구 `KRTOUR_MAP_*` prefix(현 코드는
  `KOR_TRAVEL_MAP_*` — 미스매치)라 기존 `python-krtour-map-claude` 스택은 stale/unhealthy다.
  e2e는 이미 라이브 검증(57/0 · 209 passed)됐으므로 공유 인프라 무중단을 위해 재실행하지 않는다.
- **T-AUDIT-0616**: e2e(HIGH)는 라이브 검증 완료로 ✅, 잔여는 F-01 옵션 A(전 feature re-key)
  deferred 1건.

**다음 한 작업**: `T-452-openapi-problem-json`(OpenAPI 에러 본문 RFC7807 problem+json 보강) —
이 저장소 유일 즉시 실행 트랙.

## 2026-06-18 claude 작업 메모 — 외부/보류 task won't-do 종결

사용자 지시로 백로그의 외부 추적 4건과 보류 1건을 진행하지 않음(won't-do)으로 종결했다.

- **종결(won't-do)**: `T-019`, `T-210b`, `T-210c`, `T-210d`(전부 PinVi repo 외부),
  `T-103`(streaming ETL — 초 단위 latency 요구 provider 증거 없음). `docs/tasks.md` 외부
  추적 섹션 제거 + 보류에서 T-103 제거, `docs/tasks-done.md` 상단 아카이브.
- **유지**: `T-229-buildx`(arm64 buildx, `GITHUB_TOKEN` 배포환경), `T-101`(MV 보류),
  열린 in-repo task `T-452-openapi-problem-json`·`T-ADMIN-TANSTACK`·`T-AUDIT-0616`.

**다음 한 작업**: 이 저장소 즉시 실행 트랙은 `T-452-openapi-problem-json`(OpenAPI problem+json
보강)과 `T-ADMIN-TANSTACK` 잔여(backend-의존 e2e 라이브·bulk 정책 가드). `T-229-buildx`는
배포환경 잔여로 변동 없음.

## 2026-06-18 Codex 작업 메모 — admin frontend StyleSeed 디자인 규칙 적용

사용자 요청에 따라 `https://styleseed-demo.vercel.app/llms.txt` 및 연결된
`llms-full.txt`의 StyleSeed 규칙을 admin frontend 공통 디자인 표면에 반영했다.

- **적용 범위**: `globals.css` design token, `AdminShell`, 홈 KPI/상태 카드,
  공용 `Card`/`Button`/`Badge`/`StatusBadge`/`Table`/`DataTable`/form primitive.
- **핵심 변경**: 단일 brand accent + grayscale surface, 카드 기반 정보 표면,
  낮은 shadow, 명시적 type scale, 숫자+단위 2:1 표시, KPI secondary element 변형,
  모바일 grid overflow 방지.
- **검증**: frontend type-check 통과, ESLint 0 errors(기존 warnings 6), public env
  주입 `next build` 통과, `12705` production 서버 HTTP 200 및 Playwright screenshot
  1280×720/390×844 확인.
- **문서화**: [`docs/architecture/admin-frontend-design-rules.md`](architecture/admin-frontend-design-rules.md)에
  StyleSeed 기반 로컬 admin frontend 규칙을 정리했다.
- **환경 메모**: WSL `/usr/local/bin/node`가 bus error를 내 Windows Node로 검증을
  대체했다. 현재 `http://127.0.0.1:12705/`에 production frontend 서버가 떠 있다.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

## 2026-06-17 Codex 작업 메모 — maplibre-vworld-react 지도 e2e 종결

`T-MAP-VWORLD-03`(#467)을 종결했다. PR #469 merge 후 main 기준으로 WSL dev server +
Windows Playwright 흐름에서 지도 e2e를 다시 실행했고, `features-map-interactions.spec.ts`
**5 passed / 0 failed**를 확인했다.

- **검증 환경**: WSL `0.0.0.0:12706`, Windows `E2E_BASE_URL=http://172.26.51.35:12706`,
  `NEXT_ALLOWED_DEV_ORIGINS=172.26.51.35`.
- **검증 범위**: map/table 탭, bbox fetch, kind 필터 refetch, table 선택→지도 상세 패널,
  error/empty 상태.
- **후속 수정**: 최종 e2e에서 추가 수정할 회귀는 없었다. 정본 리포트는
  `docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

## 2026-06-17 Codex 작업 메모 — admin features 지도 VWorldMapView 전환

`T-MAP-VWORLD-02`(#466)를 구현했다. `features-client.tsx`에서 직접
`new maplibregl.Map()`과 marker 배열을 소유하던 코드를 제거하고,
`src/components/vworld-map-view.tsx`의 `VWorldMapView`/`VWorldMarker` 컴포넌트로
전환했다.

- **유지한 동작**: bbox 동기화, kind 필터 refetch, marker/table 선택 상세 패널,
  VWorld key 미설정 fallback, table/map 상태 공유.
- **e2e 환경 보강**: Windows localhost forwarding이 붙지 않는 경우 WSL IP로 dev 서버에
  접근할 수 있도록 `NEXT_ALLOWED_DEV_ORIGINS`를 `next.config.ts`에 반영했다.
- **검증**: frontend type-check 통과, ESLint 0 errors(기존 warnings 6), vitest
  27 passed, `NEXT_PUBLIC_*` env 주입 build 통과, Windows Playwright 지도 e2e
  `features-map-interactions.spec.ts` 5 passed.

**다음 한 작업**: **T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정**.

## 2026-06-17 Codex 작업 메모 — maplibre-vworld-react 지도 전환 계획 수립

사용자 요청에 따라 admin UI 지도를
[`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react) 기반으로
전환하는 작업을 시작했다. 참조 repo는 2026-06-17 기준 `a7cb0f8`를 확인했고,
정본 계획은 `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`다.

- **GitHub Task 생성**: #465(`T-MAP-VWORLD-01` 계획), #466(`T-MAP-VWORLD-02` 지도 전환),
  #467(`T-MAP-VWORLD-03` e2e/후속 수정).
- **범위 결정**: 전체 외부 모노레포 vendoring이 아니라 admin `features` 지도에 필요한
  `VWorldMapView`/React marker 모델을 얇게 이식한다. 기존 bbox 동기화, kind 필터,
  선택 상세 패널, VWorld key 미설정 fallback은 유지한다.

**다음 한 작업**: **T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환**.

## 2026-06-17 claude 작업 메모 — 문서 구조 정리 (PR 대기)

문서 트리 재배치 + entry 슬림(단일 PR, 코드 동작 무변경): ADR `docs/decisions.md`→`docs/adr/NNN-*.md`(53)
+ 색인, 개발규칙 6건은 SKILL §4로 이전; ETL 17개→`docs/etl/`; architecture/계약/패키징 19개→
`docs/architecture/`; CLAUDE/AGENTS/README/SKILL 중복 제거·단일정본 포인터화·v1 1줄; tasks 작성규약을
`docs/tasks-rule.md`로 분리; Telegram MCP(설정 5 + 런처 + 문서) 제거. 내부 링크/py_compile/JSON 검증 통과.
정본 색인은 [`docs/adr/README.md`](adr/README.md). **다음 한 작업은 아래 T-229-buildx로 변동 없음.**

## 2026-06-17 claude 작업 메모 — admin UI TanStack 테이블 이행 + #452 후속 종결

- **PR #453 머지**: issue #452(Claude Code PR #437~#450 리뷰 취합)의 잔여 조치 일괄 반영 — KHOA
  re-key cleanup 마이그레이션(alembic 0027)·Prometheus path label·geocoder blast radius 문서/테스트·
  REST/의존체인/ServiceToken 정합·ADR-059(벤더링 agent/skill 예외) 등. CI green.
- **PR #454 머지**: admin UI 전 테이블(20파일/~22테이블)을 공용 `DataTable`(@tanstack/react-table v8
  + react-virtual v3)로 이행. 정렬 헤더(aria-sort)·다중선택/bulk(dedup·curated)·`features` 가상화.
  정본 `docs/reports/admin-tanstack-table-migration-2026-06-17.md`. tsc/ESLint/vitest(20)/next build/
  route-mocked Playwright(16)/CI 전부 green. backend-의존 e2e는 role/name 셀렉터라 호환(audit+grep 무변경).

- **admin UI 테이블 backend-의존 e2e 라이브 실행 완료**(2026-06-17): 라이브 Docker 스택(codex
  api :12701/dagster :12702 + 재빌드한 migrated frontend :12705 + playwright host-network 컨테이너)에서
  전 spec 실행 → 최초 54/3 → **PR #458**(offline-uploads `offline-upload-row` testid 복원, 이행 회귀)
  후 55/2 → **PR #459**(required 필드 접근성 이름 정정, 아래) 후 **57 passed / 0 failed**.
- **PR #459(required 필드 접근성 이름)**: `FormField`/`FormSelect`/`FormTextArea`의 `required` 별표
  `<span aria-hidden> *</span>`가 Chromium accname에 누수돼 접근성 이름이 `"name *"`가 되던 문제를
  공용 헬퍼 `requiredFieldAriaLabel`로 명시 `aria-label` 부여해 정정(별표 시각 유지·spec 회귀 0·
  전역 `getByLabel(exact)` 정상화). features-new.spec 2건 green.

**다음 한 작업**: 즉시 실행 가능한 큰 트랙 없음(admin UI 테이블 이행 + 라이브 e2e 전부 green). 잔여는
(1) **arm64 buildx 배포 검증**(`GITHUB_TOKEN` 필요), (2) bulk 동작 정책 가드(완료 review 재결정·
archive confirm, 선택)뿐.

## 2026-06-14 claude 작업 메모 — T-229 curated 오버레이 라이브 검증 완료

T-229(T-225가 분리한 라이브 검증 후속)를 종결했다. 정본 리포트
`docs/reports/t-229-curated-live-verify-2026-06-14.md`.

- **복원 불필요**: T-212e 데이터가 옛 claude postgres(15433)에 그대로 잔존
  (features 1,095,665 / weather 92,923 / source_records 1,111,885) + 격리 복원본
  `krtour_map_restore` 존재. 운영 데이터 무손상 원칙으로 **복원본에만** 검증 수행.
- **(A) curated 오버레이 완전 검증** [AS-01/API-11/12 해소]: `curated_features_refresh`
  4-asset RUN_SUCCESS → `curated_features` **0 → 86,341** 후보(테마 7종, MCST source
  카운트와 정합). admin API가 실제 서빙(예: 원동탁구클럽/레저), 사용자 표면은 미선택
  후보 숨김(선택 게이트 정상), curated-themes/sources 200, tripmate-copy는 선택 시
  생성(설계대로 0). T-212e reload 때 단지 실행되지 않았을 뿐 파이프라인은 정상.
- **(B) `/metrics` 200 검증**, **(C) smoke breadth 전 표면 응답**(200/정상404).
- **유일 잔여: arm64 buildx** — WSL에 `GITHUB_TOKEN` 부재로 이미지 빌드 불가 →
  토큰 있는 배포 환경의 후속(코드/데이터 결함 아님).
- 환경: codex 스택은 사용자 지시대로 강제종료 후 external-infra로 재기동(이미지 재사용).
  worktree 정리(메인 FF + review 잡파일 104개 제거, claude stray 빌드 산출물 제거)도 완료.

**다음 한 작업**: 본 저장소 즉시 실행 가능한 큰 트랙 없음. 잔여는 **arm64 buildx
배포 시점 검증**(GITHUB_TOKEN 필요)뿐. (운영 외 작업: GitHub repo가
`kor-travel-map`으로 rename됨.)

## 2026-06-13 claude 작업 메모 — T-225 T-212e closure 재검증 완료

T-225를 종결했다. 정본 리포트
`docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

- 라이브 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 **문서/코드 증거 대조**로
  닫았다(인수기준 충족). 5개 차원 교차검증 + 각 gap 반증(서브에이전트 18).
- **T-212e closure 유효**: 실패 provider 6건 수정 전부 main에 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 합계 102,121, 이슈 #397/#407/#409 close + 보강 PR
  머지, broken link 없음), identity는 이미 post-rename(#429가 리포트까지 재작성),
  패키지 분리(#430)·#434 포트 재기준은 reload 데이터 closure에 영향 없음.
- 착수 가정이던 "구 이름 drift"는 실재하지 않았다(리포트가 이미 새 identity 기준).
- 남은 것은 **라이브 검증이 미수행된 커버리지 갭**(코드 결함 아님) → 후속 **T-229**로
  분리: (A) curated 오버레이(`curated_features_refresh` + admin/사용자 `curated-*` +
  `tripmate-copy`) 라이브 검증, (B) reload 이후 신규 표면(Prometheus `/metrics`,
  arm64 buildx), (C) smoke breadth(features/batch·by-target, ops/providers, ops 관측,
  governance 리뷰 큐, debug/mois-license).
- 반증되어 갭 아님: ops/consistency API(e2e로 실제 호출), backups/restore API(설계상
  opt-in 래퍼 — 스크립트는 라이브 검증), poi-cache/refresh-policy(T-212e 이전 기능).

**다음 한 작업**: **T-229 — T-212e 후속 라이브 검증**(curated 오버레이 +
post-reload 신규 표면 + smoke breadth). 라이브 Docker 스택 필요.

## 2026-06-13 Codex 작업 메모 — T-108 운영 배포 자동화

pinvi의 `T-108`을 kor-travel-map 운영 범위로 이식했다.

- 사용자 재지시에 따라 streaming replication은 하지 않는 것으로 ADR-056에 명시했다.
- `scripts/docker-buildx.sh` / `npm run docker:buildx`로 N150 16GB(`linux/amd64`)와
  Odroid M1S(`linux/arm64`)용 multi-platform Docker image build/push를 고정했다.
- `.env.example`, `docs/deploy.md`, `docs/runbooks/docker-app.md`, `docs/tasks-done.md`,
  `docs/journal.md`를 같은 기준으로 갱신했다.

**다음 한 작업**: **T-225 — T-212e closure 재검증**.

## 2026-06-13 Codex 작업 메모 — 태스크 문서 정리

태스크 문서의 역할을 다시 분리했다.

- `docs/tasks.md`는 열린 `[ ]` 항목만 남기는 백로그로 축소했다.
- 완료된 `T-RV-*`, `T-200~T-228`, `T-212a~d`, `T-216`, `T-218` 묶음은
  `docs/tasks-done.md`에서 요약 아카이브한다.
- 오래된 Sprint 2/3 미완료 표기와 중복 완료 체크박스가 현재 인수인계에 다시
  노출되지 않게 이 파일을 현재 상태 중심으로 정리했다.

**다음 한 작업**: **T-225 — T-212e closure 재검증**.

## 현재 상태

Sprint 5 운영 진입 마무리다. 핵심 구현과 운영 표면은 대부분 닫혔다.

- `T-212e` 실데이터 full reload 완료: 1,095,665 features, weather values 92,923,
  consistency report `99159eea` OK, offline upload 3포맷 + DELETE lifecycle, Windows
  Playwright 33/33, API smoke 17/17, backup/restore smoke.
- `T-221` admin UI/UX 연결성, `T-222` 공개 해수욕장/축제 뷰 API, `T-223`
  curated feature/PinVi import, `T-224` concierge provider 경계 정리는 완료됐다.
- `T-226` 패키지/runtime identity clean cut, `T-227` Prometheus 메트릭, `T-228`
  API/backend와 admin frontend 패키지 분리도 완료됐다.
- `T-225`(T-212e closure 재검증, 2026-06-13)·`T-229`(curated 오버레이 + post-reload
  표면 라이브 검증, 2026-06-14)는 완료됐다. 본 저장소에서 즉시 실행 가능한 큰 트랙은
  없고, 유일 잔여는 **arm64 multi-arch buildx 배포 검증**(`T-229-buildx`, `GITHUB_TOKEN`이
  주입된 배포 환경 필요)뿐이다. PinVi 쪽 작업(`T-019`/`T-210b`~`d`)과 streaming ETL(`T-103`)은
won't-do로 종결했다(`docs/tasks-done.md`).

## 다음 한 작업

### T-229-buildx — arm64 multi-arch buildx 배포 검증 (T-229 잔여)

T-229의 라이브 검증(curated 오버레이 0→86,341 후보, `/metrics` 200, smoke breadth)은
완료됐다(정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`). 유일 잔여는
T-108/ADR-056의 arm64 multi-arch buildx 이미지 build+boot smoke다.

목표:

- `scripts/docker-buildx.sh`로 `linux/arm64`(Odroid M1S) 이미지를 빌드하고 단일
  platform 부팅 smoke를 통과시킨다.

전제:

- private provider pin 빌드에 `GITHUB_TOKEN`이 필요하므로 **토큰이 주입된 배포
  환경**에서만 수행 가능하다(코드/데이터 결함 아님).

완료 시:

- arm64 빌드+부팅 smoke 결과 또는 불가 사유를 `docs/reports/`에 기록한다.
- `docs/tasks.md`에서 `T-229-buildx`를 제거하고 `docs/tasks-done.md`로 이동한다.
- `docs/journal.md`에 역시간순 엔트리를 추가한다.

## 열린 작업 요약

즉시(in-repo): 없음 (`T-452` 종결).

배포환경 잔여:

- `T-229-buildx` — arm64 multi-arch buildx 배포 검증 (`GITHUB_TOKEN` 필요).

보류 / deferred:

- `T-101` — Materialized View 도입 검토.
- `T-AUDIT-0616` — 잔여 = F-01 옵션 A(전 feature DB re-key, big-bang) 1건뿐, 별도 시점 결정.

종결 (2026-06-18):

- won't-do: `T-019` · `T-210b`~`d`(PinVi 외부) · `T-103`(streaming ETL).
- `T-ADMIN-TANSTACK`: (a) 라이브 e2e 57/0 검증 · (b) bulk 가드 main 구현.
- `T-452-openapi-problem-json`: OpenAPI 4xx/5xx problem+json 선언 — 상세 `docs/tasks-done.md`.

## 고정 기준값

- 배포명: `kor-travel-map`.
- Python import root: `kortravelmap`, 권장 예시 `import kortravelmap as ktm`.
- REST API backend: `kor-travel-map-api`, import `kortravelmap.api`,
  위치 `packages/kor-travel-map-api/`.
- Admin UI frontend: `kor-travel-map-admin`,
  위치 `packages/kor-travel-map-admin/frontend/`.
- CLI: `ktmctl`.
- Env prefix: `KOR_TRAVEL_MAP_*`, API package prefix `KOR_TRAVEL_MAP_API_*`,
  frontend API base `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`.
- DB: `kor_travel_map`, Dagster metadata DB: `kor_travel_map_dagster`.
- 로컬 고정 포트(docker-manager 기준): API `12701`, admin UI `12705`,
  Dagster `12702`, RustFS S3 `12101`, RustFS console `12105`,
  kor-travel-geo API `12501`.
- PinVi 연동: OpenAPI HTTP. 직접 import와 DB 직접 접근 없음.

## 참고 위치

- 백로그: `docs/tasks.md`.
- 완료/아카이브: `docs/tasks-done.md`.
- 작업 일지: `docs/journal.md`.
- Sprint 계획: `docs/sprints/`.
- REST 단일 정본: `docs/architecture/rest-api.md`.
- Cross-repo 정본: `docs/integration-map.md`.
