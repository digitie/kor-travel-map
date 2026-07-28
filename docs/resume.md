# resume.md — 현재 진척도와 다음 한 작업

## 2026-07-28 (codex) — PR #869 머지 후 task 전면 재감사

**다음 한 작업**: 문서 PR #870의 적대적 리뷰어 2명 검토를 반영하고 문서 검증·보안 감사를
통과시킨 뒤, 사용자 지시에 따라 CI를 기다리지 않고 셀프 머지한다. 이어서 갱신된 Lane B의
첫 작업 `T-VN-45`를 시작한다.

- PR #869는 exact head `c0cd4979`의 GitHub Actions 8개가 모두 green인 뒤 merge commit
  `25e9304b`로 main에 반영됐다.
- Map의 열린 이슈는 #673·#812·#815·#819, 열린 PR은 #814다. PinVi 관련 열린 PR은 #403,
  외부 추적 이슈는 #215이며 docker-manager/geo에는 열린 PR·이슈가 없다.
- Map #814는 main보다 85 commits, PinVi #403은 13 commits 뒤처졌다. Map main에는 유사
  user schema assertion이 이미 있으므로 H07A/B는 rebase 후 중복을 제거하고 residual contract만
  다시 검토하는 landing task로 바꿨다.
- `T-VN-H21`의 실제 `/v2/reverse` 400 body는
  `E0100 query.key: Field required`였다. `lon`/`lat` request schema는 배포 OpenAPI와 일치하므로
  payload drift가 아니라 live test의 credential preflight 누락으로 재분류했다.
- #673과 #819를 각각 `T-VN-H28A/B`, `T-VN-H27`로 승격했다. 큰 frontend/API/curation/Wave 2
  task는 독립 검증 가능한 child task로 분해했다.
- Agent A는 H07 cross-repo 계약→edge/geo/data-quality queue, Agent B는 T-VN-45부터 frontend
  hardening→PinVi 소비 API queue를 순차 소유한다. 두 lane은 병렬 실행하되 migration 번호,
  OpenAPI 정본, compatible pair와 Wave 2 freeze barrier에서만 직렬화한다.
- 이 PR은 문서 전용이므로 destructive Live UI 대상이 아니다. `git diff --check`, task index/detail
  정합, prod redaction과 staged 민감정보 scan을 검증하며 코드/DB/API에는 변경이 없다.

## 2026-07-27 (codex) — T-VN-47 + durable curation + #868 완결

**다음 한 작업**: 본 PR의 CI green·셀프 merge 뒤 전체 열린 task와 실코드·열린 이슈를
재감사한다. 더 작은 실행 단위로 분해하고 의존성 기준으로 Lane A/B 병렬 범위를 다시 배치한
문서 전용 PR을 CI 대기 없이 머지한 뒤, 갱신된 Lane B 순서로 진행한다. 사용자 최신 지시에 따라
그 문서 PR부터 적대적 리뷰어 2명을 운용한다. `T-VN-45`는 그 재감사 전까지 미착수 상태로 유지한다.

- React Doctor full scan은 269개 파일·actionable 진단 0건이다. canonical config와 exact verifier가
  shadow config, command·scope 축소와 package-level 우회를 fail-close한다. runtime correctness
  진단은 근인 수정했고 giant component 19개·reducer 후보 3개는 `T-VN-49`로 이관했다.
- #862의 H13 조건부 upsert를 적대 리뷰한 결과 source 누락 삭제, archived identity 재생성,
  legacy/canonical 단방향 상태, Feature merge의 provider/operator clock 혼합과 parent/item lock
  inversion을 확인했다. migration 0065에서 source/operator revision을 분리하고 archived/NULL
  exact identity를 한 행으로 강제했다.
- `legacy_projection_id`가 projection과 durable item을 명시적으로 연결한다. stable collection key는
  mutable theme slug 대신 theme/source UUID와 title hash를 사용하고 semantic duplicate는
  `:split:<collection_id>`로 보존한다. 0064 slug 재사용으로 탈취된 active/archived projection과
  원 owner 관계는 명시적 `legacy_projection_id`로 복구한다. canonical-only item은 원 projection
  durable link가 없고 external identity도 theme 간 공유될 수 있으므로 자동 owner 복구를 하지
  않는다. upgrade 전 old projection 삭제 여부와 관계없이 모든 legacy-marker collection에서
  `draft/admin_only` quarantine에 보존한다. mutable metadata marker가 지워진 이력은 immutable
  `legacy:` key namespace를 함께 검사한다. exact `legacy:quarantine:<UUID>` key와 immutable
  migration creator가 모두 일치하는 산출물만 재격리하지 않아 정상 `quarantine:` theme slug와
  migration 왕복 identity를 함께 보존한다. mutable quarantine metadata에 `migrated_from`이
  추가돼도 upgrade·downgrade key rewrite에서 같은 결합을 제외한다. 임의 admin key가 base/split/과거 staging
  namespace를 선점해도 upgrade/downgrade가 중단되거나 수동 key를 덮지 않는다.
- `source_record_key IS NULL`인 legacy DELETE→새 UUID 재삽입도 기존 external identity와 operator
  tombstone을 복원한다. cross-title A→B/B→A 동시 이동은 target collection 뒤 source parent를
  잠그지 않고 item만 잠가 교착을 제거했다.
- 단독 적대 리뷰어가 #840 이후 Claude Code 작성 PR 21건과 최신 code SHA를 함께 검토했다.
  migration 왕복·owner repair·오래된 projection의 후속 owner 탈취·null-source tombstone·실제 두
  transaction 교차 이동을 포함한 관련 unit/integration/API 회귀와 외부 geo live 5건을 제외한
  최종 backend 전체 **2,405건**, static·frontend 전체 gate가 통과했다. 격리 실데이터 destructive
  Live UI 결과는 `journal.md`의 같은 날짜 항목을 정본으로 한다. curation exact code `7e2920aa`는 reviewer
  신규 P0–P2 0건·PostgreSQL 46/46이다. Live 기대값 환경화의 빈/공백 입력·exact match·
  중복 identity·runbook checkpoint P2까지 반영한 최종 `f6a50866`에서도 잔여 P0–P2는 0건이다.
- 전체 clone에서 0053이 동일 KMA target-grid legacy queued job 3건을 무차별 거부하는 blocker를
  발견해 `T-VN-H23`으로 등록하고 같은 PR에서 완결했다. queued winner는 runtime dispatch 정렬로
  결정하고 나머지는 감사 가능한 cancelled terminal로 전환한다. running 둘 이상과 cancellation
  marker 중복은 mutation 전에 중단한다. 단독 리뷰어가 cancellation audit 훼손 가능성을 찾아
  보강했으며 exact code `ca313d32`에서 잔여 P0–P2 0건, migration 회귀 5/5·관련 묶음 64/64다.
- `T-VN-H24`는 source item과 펼쳐진 membership component를 분리했다. durable identity는
  `collection + external_item_id + external_component_id`이고 Feature는 nullable·mutable target이다.
  legacy UUID/operator/source/archive 이력을 첫 authoritative import에서 같은 행으로 승계하고,
  모호한 후보와 active Feature 중복은 preview/commit 전에 fail-close한다. 0064→0066 연속
  Alembic transaction은 0065의 지연 FK·trigger event를 0066 DDL 전에 검사·소진한다. 단독
  적대 리뷰어는 exact code `baf40a04`에서 P0–P2 0건을 확인했다. 실제 prod clone의
  0036→0066 연속 migration도 완료돼 이전 pending trigger 오류가 해소됐다. 같은 clone에서
  성공한 migration·build·destructive import를 보존해 실패 단계부터 재개했고, 최종
  `e8d167c5` 기준 공식 collection/item 19/486, component 2/2, operator adoption 2,
  duplicate target 0을 확인했다. prod head `0036`, Feature 1,099,359건, collection 미존재와
  API/UI health는 불변이며 성공 뒤 clone을 삭제했다.
- 작업 중 추가된 `T-VN-H26`/GitHub #868은 main에 이미 있던 canonical
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias를 재확인하고, 남은 수용 조건인 기존
  API-prefixed 이름 fallback을 추가했다. canonical-only/legacy-only/미설정/동시 설정 우선순위와
  잘못된 admin header `403`을 API auth **84건**으로 고정했다. 사용자 지시에 따라 이 변경만
  적대적 리뷰에서 제외했다.
- 작업 중 발견한 giant/reducer 구조 debt는 `T-VN-49`, 실 `kor-travel-geo /v2/reverse` 400
  계약 drift 5건은 `T-VN-H21`, migration quarantine의 admin 재분류 workflow는
  `T-VN-H22`로 등록했다. `T-VN-H23`은 이 PR에서 바로 완료했다. migration head는
  `0066_curation_component_identity`다.

## 2026-07-27 (claude) — 🎯 Lane B b4 대행: H13·H14·H15 완결, H20 진행, H18 예정

**다음 한 작업**: b4 = **H13·H14·H15·H20 완료**, **H18만 보류**(governance — approval 필수화가 self-merge
즉시 차단, repo 소유자가 시점 결정). H18 착수 또는 다른 지시 대기. 사용자 지시로 Lane A가 Lane B b4 대행 완료.

- **H20 완료**: prod admin password/hash 회전 + login 200 검증. 회전 중 compose `$` interpolation으로 UI
  일시 잠김→`$$` escape로 복구(투명). 잔여(사용자): local doc stale 섹션 삭제·session secret 미회전·n150
  .env 백업 정리. 상세 journal/tasks-done 2026-07-27.

- **완료(b4)**: `T-VN-H13`(#699→#862 curation override 보존) · `T-VN-H14`(#700→#863 KREX bounded-retry) ·
  `T-VN-H15`(#805→#864 c7 IPv6 origin). 각 적대 리뷰 2명 + 회귀 + CI green.
- **진행(H20)**: credential-safe hash 생성 완료(평문→gitignored doc, hash→repo 밖 scratch, 값 비노출).
  잔여 = prod UI env ktdctl 회전(R2) + login 200/기존 401/세션 폐기 검증(사용자 실행).
- **직전 완료(세션)**: T-VN-H19(C2 실증→C6c/T-VN-03 전체 종결)·H12·H16·H17·H06.

- **완료(이번 세션 최근)**: `T-VN-H19` — public API key 양성 production runtime 실증(admin-BFF 임시 key
  발급→valid 200·wrong 401·revoke 200·revoked 401, credential-safe). **경계 매트릭스 14/14 완성 →
  T-VN-03+T-ADM-C6c 전체 완료**(C2 보류 조건 해소).
- **완료(이번 세션)**: `T-VN-H12` — status marker 좌표만 `sha256(RUN_ID)` jitter(`STATUS_MARKER_LON/LAT`) +
  `recenterMapTo`. **n150 c7-v6 live 검증**(map=c8ed6164)에서 status marker 통과. #855(shared base jitter)의
  weather/price seeding desync를 live가 잡아 **#859에서 status-only로 국한 수정**(#858 뒤 rebase, merged
  `baa04c08`). weather/price는 고정 base = LIVE-01 baseline이라 무변경. 상세 journal/tasks-done 2026-07-27.
- **교훈**: 정적 적대검증이 외부 Python seeding helper 좌표 계약을 못 모델링 → cross-process 좌표는 live 필요.
- **직전 완료(세션)**: T-VN-H06·T-ADM-C6c+T-VN-03(#392 close)·T-VN-H16/H17(LIVE-01 후속 7/7 close).

## 2026-07-27 (codex) — T-VN-44 완료 (#858)

T-VN-44는 frontend lint·schedule recovery·가격 identity와 R1 격리 실데이터 Live UI를
완료해 #858로 main에 반영했다.

- frontend full ESLint 기준선 1 error/30 warnings를 0 problem으로 내리고 `npm run lint`와 CI를
  `--max-warnings 0`으로 고정했다. TanStack compiler 경계는 `data-table.tsx` 한 파일·두 함수만
  허용하고 verifier가 module/function directive·legacy `use no forget`·inline disable·
  `.mts`/`.cts`를 포함한 실제 lint 파일 집합 drift를 fail-close한다.
- schedule cron 수정은 effect 내부 동기 state 변경과 render당 sessionStorage scan을 제거했다. mutation
  경계에서 dialog를 닫고 storage scan 완료 전 fail-closed 잠금을 유지한다. PATCH 응답 유실·409·terminal
  audit 실패 후 같은 idempotency key/body 복구와 reload 첫 frame 비활성 상태를 mocked E2E로
  고정했다. 최신 B 목록 scan 뒤 과거 A mutation이 늦게 settle되는 순서도 최신 refresh ref와 B scan 완료 barrier를 둔 controlled-response Chromium 회귀로 잠금 고착을 막았다.
- 가격 identity를 DB·repository·REST/OpenAPI·지도·chart 전체에서
  `provider + price_domain + product_key`로 통일했다. migration 0064는 concurrent DDL 부분 성공 뒤
  Alembic stamp만 실패해 재실행돼도 이미 유일한 유효 index를 먼저 지우지 않는 대칭 복구를 제공한다.
- #840 이후 Claude PR 전문 감사 범위를 #841~#857의 Claude 작성 15건으로 확장했다. #854의
  public-key C2 “등가 충족”은 서로 다른 auth branch를 혼동한 완료 오판이라 되돌리고, credential-safe 직접 실증을 `T-VN-H19`로 열었다.
  #853의 H06 증거는 n150 Linux 24/24로 대체했고 #855 H12 live 잔여와 #856/#857 H16/H17 완료를
  보존했다. 최신 main에 재유입된 C2 전체 완료 오기는 같은 정정으로 제거했다.
- **R1 최종 파괴적 live**: 운영 스키마와 실제 가격 feature 1건·관측 20건을 별도 PostGIS 컨테이너로
  읽기 복사하고 실제 관측 1건을 복제본에서 변경했다. branch API가 0063→0064를 적용한 뒤 run-unique
  API/UI/auth에서 로그인 GET/POST 200+cookie, 공식 admin feature acceptance 2/2를 통과했다. 같은
  product의 provider/domain 두 series는 REST current 2/history 4, 상세 chart 2선·4점, 지도 marker 두
  identity로 실제 Chromium에서 확인했다. 운영 DB fixture 0·head 불변·health 200을 재확인하고 전용
  port/container/network/image/C7 runtime 잔여를 0으로 정리했다.
- local-only prod password와 배포 hash 불일치는 별도 `T-VN-H20`로 등록했다. 비밀값은 tracked 문서에
  기록하지 않았다. T-VN-43은 #851로, H06은 #813+#852 후속 검증으로 완료 이관했다.

## 2026-07-27 (claude) — 🎯 T-VN-H12 landing + T-VN-H16/H17 이슈 재검증(LIVE-01 후속 7/7 close)

**Lane A 다음 작업**: `T-VN-H12` live-lane 실증과 `T-VN-H19` public-key 양성 runtime 실증.
`T-VN-H16`/`T-VN-H17`은 #856/#857로 완료했다. tasks.md 인덱스가 정본.

- **완료(이번 세션)**:
  - `T-VN-H12` — status marker 좌표 `sha256(RUN_ID)` jitter + `recenterMapTo`. PR #855 머지 후
    **n150 c7-v6 live 검증**에서 status marker 통과 + shared-base jitter의 weather/price seeding desync
    (공식 runner latent bug) 발견 → **status-only jitter로 수정(PR #859)**. #859는 #858 머지 뒤 rebase 머지.
  - `T-VN-H16` — LIVE-01 후속 OPEN 7건 재검증 → 6 close(dm#63·#70·map#712·#719·#777·#694, 근거 코멘트).
  - `T-VN-H17` — map#684를 조건 #8 검증범위 축소(write/error UI 엣지=mock, read·URL·freshness+write
    계약=live)로 close. → **LIVE-01 후속 OPEN 7건 전부 종결**.
- **직전 실행**: principal 경계 smoke 13건 PASS와 #392 close. public-key C2는 `T-VN-H19`까지
  미검증이므로 T-ADM-C6c/T-VN-03 전체 완료는 보류한다. T-VN-H06은 완료.

## 2026-07-27 (claude, Codex 정정) — principal 경계 부분 실증 + #392 종결

**Lane A 다음 작업**: `T-VN-H12` live 실증·`T-VN-H16` 이슈 재검증과 함께 `T-VN-H19`의
public-key C2 양성 runtime 실증을 진행한다. tasks.md 인덱스가 정본이다.

- **부분 실증**: n150 production에서 실행한 13건은 모두 PASS했다. 배포=**map c8ed6164 /
  pinvi 6a035695**(둘 다 healthy, production) —
  curated(C1 401·C3/C4 200·C4n 401) · ops 6(O1/O2 401·O3/O6 403·O4/O5 200) · MOIS(M1 404) ·
  PinVi #392(P-R1 ops:read 200·P-R2 no-token 401).
- **접근**: 배포 전 정적 감사 워크플로우(`tvn03-c6c-readiness-audit`, 6차원 병렬+적대 반증) →
  go-with-caveats → credential-safe smoke(값 비출력, status만) → #392 실증.
- **C2(public-key 200)**: DB lookup·hash compare 양성 runtime 분기는 미검증이다. C1/C3/C4와 unit test는
  서로 다른 auth branch라 등가 증거가 아니며, `T-VN-H19` 전까지 T-VN-03/C6c 전체 완료를 보류한다.
- **문서 모순 해소**: 배포 image rev label이 `c8ed6164`임을 실측(incident md의 `b0c95672`는 조상·
  docs-only 차이라 런타임 동일). 증거: reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md.
- **완료 범위**: PinVi issue #392 observation-read principal 종결.

## 2026-07-27 (claude) — 🎯 T-VN-H06 완결: keyset cursor 전환 backend #813 + e2e 검증 #852

**다음 한 작업**: Lane A **`T-ADM-C6c` + `T-VN-03`** — pinvi head(#408 포함, 현 배포 6a035695로
이미 반영) principal 경계 smoke(curated 4 GET·ops 6 GET·MOIS 404)를 n150 production에서 실증하고
PinVi #392 close. (map=c8ed6164/pinvi=6a035695 정식 전진 상태 그대로 사용.)

- **완료(이번 세션)**: `T-VN-H06`(admin 목록 keyset+fingerprint cursor 전환). backend #813(merge
  `9d29606e`, 2차 리뷰 P3 반영·pytest integration green) + e2e 검증 #852(merge `3ce99d75`).
- **e2e 검증**: dedup/enrichment mocked Playwright 14 fail → spec-only 수정으로 **24 GREEN**.
  근인 전부 spec drift(client 무변경): reviewed_by 과다기대 제거 · MultiFilterCombobox Enter 커밋 ·
  deferred provider poll. 상세는 tasks-done.md / journal.md 2026-07-27.
- **검증 환경 주의**: 이 cursor e2e는 mocked·CI 미실행이라 CLAUDE.md 정본 Windows Playwright로 확인.
  task 노트의 "n150 Linux" 편차는 mocked·OS-agnostic이라 채택(tasks-done.md에 명시).
- **머지 게이트**: #851(T-VN-43)·#813 선행 머지 확인 후 #852 CI CLEAN → squash 머지.

## 2026-07-27 (codex) — T-VN-43 구현·실데이터 파괴적 live 검증 완료

**다음 한 작업**: T-VN-43 PR의 CI green·실제 GitHub approval·머지를 완료한 뒤 Lane B b0의
`T-VN-44`(admin frontend full ESLint baseline green)를 진행한다.

- clean `npm ci` 기준 16건(low 2, moderate 7, high 7)을 0건으로 내렸다. Next 16.2.12와
  PostCSS 8.5.23·Sharp 0.35.3을 고정하고 CI에 high gate를 추가했다.
- shadcn CLI/MCP와 사용하지 않던 React Hook Form/resolver/Zod를 제거했다. generated UI source가 쓰는
  Tailwind variant 4개만 프로젝트 CSS가 직접 소유하며, lock graph는 약 1,100 package에서 742 package로
  축소됐다.
- exact npm 10.9.4는 Sharp WASM fallback optional 6개를 `extraneous`로 보고하면서 exit 0을 반환한다.
  T-VN-43은 JSON `problems`의 exact package/version allowlist 밖 문제를 fail-close하고 실제 native
  optimizer를 검증한다. upstream/npm 근인을 없애 allowlist 자체를 제거하는 작업은 T-VN-46으로 유지한다.
- 취약 legacy Next ESLint preset을 제거하고 ESLint 10·typescript-eslint 8.65·React Hooks·React-X/
  React-DOM·Next·import-x·jsx-a11y-x flat config를 직접 구성했다. effective config gate가 canonical
  React Hooks 활성·중복 React-X analyzer 비활성·missing-key/anonymous-export severity를 실제로 계산한다.
  강화된 T-VN-44 기준선은 1 error/30 warnings다.
- `openapi-typescript`의 Redocly 1 제약은 안전한 js-yaml/minimatch로 override하고, 바뀐 minimatch
  API 한 곳을 exact version/content 검사 후 적용하는 fail-close postinstall로 보정한다. frontend와
  C7 Docker context 모두 patch·tree-integrity·Sharp smoke script를 install 전에 포함한다.
- frontend Node 22.23.1/npm 10.9.4를 exact pin하고 C7 browser/client Playwright를 1.60.0으로 맞췄다.
  Next private optimizer를 실제 호출하는 2×2 SVG→WebP smoke로 Sharp ABI까지 검증한다.
- React Doctor 0.9.1 full scan은 262개 파일에서 오류 9건·경고 69건이며 T-VN-47에서 근인으로 해소한다.
- 전체 mocked Playwright 진단은 기존 accessible-name/actor/API route drift 52건을 165번째 spec까지
  재현해 중단했다. T-VN-48로 분리했고, T-VN-43의 CSS·폼·지도·업로드 대표 mocked spec은
  격리 UI/C7 container·workers=1에서 24/24 통과했다.
- #840 이후 Claude Code PR #841~#850(닫힌 PR 포함) 전문 감사 1명과 독립 적대 리뷰어 2명이
  최종 exact diff를 재검토했다. #849/#850 재감사에서 완료 task의 열린 백로그 중복·H12 인덱스/owner
  drift·완료 LIVE-01 future tracker(P3)와 C6c의 이미 끝난 배포/pair 잔여 표기(P2)를 찾아 바로잡았다.
  실제 OPEN 7건은 Lane A `T-VN-H16`으로 분리했고, 반영 뒤 P0~P3 finding 0건을 확인했다.
- 전체 Python gate는 2,355 tests·Ruff·strict mypy·4개 import contract가 모두 통과했다. frontend는
  clean install·audit 0·tree/effective-config/Sharp smoke·OpenAPI/admin/user drift·type-check·227 Vitest·
  production build를 통과했고, exact Docker image에서 대표 mocked E2E 24/24가 통과했다.
- PR #847 R1~R4에 따라 branch API/Dagster/DB migration 없이 UI만 host loopback `12715`에 격리했다.
  실제 관리자 UI로 공식 CSV 5종을 preview·commit하는 파괴적 live E2E 4/4가 통과했고 REST·관리자
  상세·지도에서 19 collections·486 memberships를 확인했다. 전용 UI/browser container 제거 뒤
  C7 active process/lock/journal/runtime 잔여는 모두 0, 운영 UI/API는 healthy다.

## 2026-07-27 (claude) — 🎯 T-VN-LIVE-01 완료: live acceptance lane n150 PASSED @ c8ed6164

**다음 한 작업**: **Lane A `T-ADM-C6c` + `T-VN-03`** — pinvi head(#408 포함, 현 배포는 6a035695로
이미 반영됨) principal 경계 smoke(curated 4 GET·ops 6 GET·MOIS 404) n150 실증 + PinVi #392 close.
그 다음 `T-VN-H06`(#813 merge `9d29606e` 반영 완료, n150 Linux cursor runtime 검증 잔여).

- **완료(이번 세션)**: `T-VN-LIVE-01`(+04A #741·58 #785·15) targeted live acceptance lane을 n150
  production(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행 → **PASSED**(rc=0, phase=passed,
  recovery_attempt=0, leftover 0). #741·#785 closed, tasks-done 이관.
- **규명·수정 연쇄**: helper host-network(#842)·map nav/zoom-contract(#843)·Codex PR 리뷰
  DSN/signal(#844)·검색 pg_trgm 격리(#845)·kind=place 격리(#848). 적대 리뷰어 2명 반영, P2는
  T-VN-H12(run-unique 좌표)로 추적.
- **인시던트+복구**: Codex live 컨테이너가 공유 prod pinvi DB를 0040으로 migration → held e60d1711
  기동 불가 → manifest trap. pinvi를 6a035695(#408)로 재빌드 + map-api base-compose 재생성 +
  deploy 가드 임시 우회(성공 후 원복)로 c8ed6164/6a035695 정식 전진. 재발방지 규율 R1~R4(#847).
- **백로그·이슈 정리**: T-VN-42(#846) done, b4 신설(H12/H13#699/H14#700/H15#805), 이슈 종결 추적(#849);
  11개 이슈에 백로그 코멘트. open PR: #833 머지·#831/#811 닫음.

## 2026-07-26 (codex) — T-VN-42 구현·실데이터 파괴적 live 검증 완료

**다음 한 작업**: T-VN-42의 최종 2인 적대 리뷰와 CI green·실제 GitHub approval·머지를 끝낸 뒤
Lane B b0의 `T-VN-43`(admin frontend npm 보안 취약점 0-high)로 진행한다.

- 두 지도 상세 패널의 MapLibre control-safe 여백과 실제 bounding-box 비겹침 assertion을 공용화하고,
  live 전역 reduced-motion 우회를 제거해 실제 zoom click·motion 종료를 검증했다.
- admin in-bounds query key와 HTTP identity를 원본 bbox·정수 zoom·items/clusters mode로 일치시키고,
  UI/server cluster 경계를 공용 함수로 단일화했다.
- #840 이후 Claude Code PR #841~#845 전문 감사 결과를 반영해 BLOCKED/result v3 exact execution
  identity와 recovery pre-mutation fail-close, clear 신호 경쟁 방지를 구현했다.
- n150 실제 데이터에서 feature panel↔scale 20px 비겹침을 확인했고 공식 CSV 5종을 preview·commit한
  파괴적 live UI E2E가 4/4 통과했다(19 collections·486 memberships·지도 상세 재검증).
- 작업 중 발견한 `T-VN-43`(npm audit), `T-VN-44`(full ESLint), `T-VN-45`(live endpoint/cache drift)를
  백로그에 추가했다.

## 2026-07-26 (claude) — 백로그 전면 감사 + A/B lane 재분배 (codex 7~8 : claude 2~3)

**다음 한 작업**: **Lane A `T-VN-LIVE-01`** — merged targeted live acceptance lane(#792)을 n150
production에 파괴적 실행(WSL SSH, 실데이터), cleanup/audit/evidence 0/완결 증명 →
`T-VN-04A`(#741)·`T-VN-58`(#785)·`T-VN-15` live 인수 일괄 종결 + issue #741/#785 close.

- **감사(11-agent 전수)**: 열린 task 전부를 실코드·GitHub·PinVi/manager 상태와 대조. 완료 확정
  이관: SYNC-02(#790)·T-VN-57(#784)·59(#786)·H02R(#796 close 2026-07-26)·H03R(#798)·H08(#799)·
  H09(#797)·51~56(#816 rebase 후 머지) + SCHEDCHURN·POICAUSAL → `tasks-done.md` 2026-07-26 섹션.
- **C6c 확인(사용자 지시)**: 코드 cutover는 완료(#387/#393, legacy 경로 0건)나 **미완** —
  배포 pinvi(e60d1711)가 hardening #408 미포함, issue #392 open, principal 경계 smoke 미실행
  (C7 read-auth는 admin-BFF만 커버). 잔여를 `T-VN-03`과 통합해 Lane A에 배정.
- **Lane 재분배(2026-07-26, codex:claude≈7:3)**: **A(Claude)** = LIVE-01 실행·종결 →
  C6c/T-VN-03 principal smoke·종결 → H06(#813) 2차 리뷰·머지·검증. **B(codex)** = b0 선행
  하드닝(42→43→44→45) · b1 PinVi 결합(11→12→16→41; 08은 PinVi #409로 완료) · b2 H07
  완결(#814+pinvi#403 머지,
  H07C #812 manifest v5, H07D #815) · b3 Wave 2 구조 전환(31→…→40→39) · 보류 T-101.
  규율: A는 적대 리뷰어 2명+파괴적 live E2E,
  설계 우수성·확장성·성능 우선(prod 보전·호환성·최소수정 비제약 — 서비스 전).

## 2026-07-26 (claude) — 🎯 C7 COMPLETE: 공식 6-spec prod 게이트 full GREEN @ d5693269

**다음 한 작업**: **T-VN 트랙** — `T-VN-SYNC-02`(integration/t-vn → main 최종 합류) 등, C7 종결로 unblock.

- **C7 완결**: poi-cache `@c7-causal` 마지막 blocker까지 수정·머지(#839, main `d5693269`) 후 **재-cut(deploy
  e22b751e→d5693269 + rebind: executor 재빌드·attestation 재생성·self-verify PASS)** → 공식 게이트
  (`run-c7-prod-live-e2e.sh`, KST :41 window) **full GREEN**: `status=0 orchestrator_verified=True`, 6 spec 전부
  passed — kma-active 2/2 · kma-cap 2/2 · kma-empty 2/2 · read-auth 7/7 · schedule-write 2/2 ·
  **poi-cache-causal 2/2**. no BLOCKED. prod 클린(active e2e target 0, weather 복원, 5 runtime healthy @ d5693269).
- **poi-cache 근인(참고)**: backend 아님 — **test-side 2중 버그**: (1) `POI_HEADING` 영문 상수가 개편
  B(`d8818994`) 한국어 h1 통일("POI 캐시 대상") 이후 stale → `gotoPoiTargets` 15s timeout; (2)
  `expectCausalDatasetProjectionUpdate`의 `page.evaluate`가 `connectionId` destructure 누락 →
  `ReferenceError`(cbe133c2 이래 상시 실패, heading 버그가 가림). projection-lag 가설은 오진. 상세
  `docs/journal.md` 2026-07-26.

## 2026-07-26 (claude) — C7 SCHEDCHURN 완료: schedule-write 재편입, gate 5-spec 복원

**다음 한 작업**: T-VN 트랙 — `T-VN-SYNC-02`(integration/t-vn → main 최종 합류) 등, C7 종결로 unblock.

- **완료(이번 세션)**: `T-ADM-C7-SCHEDCHURN` 근인 확정·수정. 직전 세션의 "app-side render churn" 진단은 **오진**.
  진짜 근인 = cron 저장 응답 유실 후 frozen-idempotency 복구가 필요해질 때 cron 수정 dialog(Base UI)가 열린 채
  남아 페이지 전체가 inert가 되어 모든 schedule 컨트롤이 접근 불가가 되던 것. fix=`schedule-panel.tsx`(복구 필요
  순간 dialog close) + spec 하드닝(canReset·robustClick·settle-gate·시작 confirm alertdialog locator). 적대 리뷰어
  2명 반영 → **91b822e2(main+fix)** prod 재배포(rollback-guarded, 4 runtime healthy) 후 verbose-iterate 재검증
  **GREEN(2 passed, 37s)** → `scripts/run-c7-prod-live-e2e.sh` SPECS에 schedule-write 재편입(**C7 gate 5-spec**).
  weather 스케줄 매 run 정확 복원. 상세 `docs/journal.md` 2026-07-26.
- **C6c**: PinVi ops-caller cutover는 이미 완료·머지됨(#387/#393), 적대 리뷰어 2명 재검증(correct + fail-safe).
  잔여는 operational activation(compatible-pair manifest-v4 exact Map+PinVi head + N150 live E2E) + #392 bookkeeping뿐.

## 2026-07-26 (claude) — C7 close: schedule-write descope + #837/#74 머지; 다음 = SchedCHURN 후속

**다음 한 작업**: `T-ADM-C7-SCHEDCHURN` — admin `SchedulePanel`의 cron override 반영 후 ~90s render/refetch
churn 규명·수정(`schedule-panel.tsx`) + UI 재빌드/재배포 → schedule-write를 다시 blocking gate에 편입.
spec 측 6-layer fix 재적용 지침은 `docs/journal.md` 2026-07-26.

- **완료(이번 세션)**: C7 gate를 **4-spec**(read-auth·kma-active/empty/cap-write)으로 확정, schedule-write
  descope(`scripts/run-c7-prod-live-e2e.sh` SPECS). test/deploy 근인 6개 규명·수정(canReset·getSchedule·reload
  timeout·frozen-UI dispatchEvent·robustClick·90s timeout); getSchedule+timeout은 **#74 배포됨(b5375a52 prod)**.
  prod 부수효과 2건(uncertain idempotency claim, KMA hourly cron leftover override→비활성) 복구(cron=20, RUNNING).
- **잔여 = app-side render churn**(deterministic app 버그, test로 우회 불가). fresh 환경 재확인 권장(22회 재현이
  dagster DB bloat로 reload/getSchedule을 느리게 했을 가능성).
- **머지**: #837(map, gate descope) + #74(docker-manager, getSchedule public url + reload timeout).

## 2026-07-24 (claude) — C7 실질 코드 blocker 완료; 다음 = 후반 flaky UI/timing 하드닝

**다음 한 작업**: `T-ADM-C7RUN` — C7 `ops-c7-kma-active-write`의 **후반 active 시나리오 flaky
UI-render/cleanup-timing 하드닝**. `assertDatasetTerminalHistoryUi`(spec:434) 등 후반 UI 어서션·
terminalization·cleanup에 robust wait/polling 추가 → 재cut(`/home/digitie/c7-{deploy-asdigitie,rebind,rerun}-<commit>.sh`
토큰 swap; 현 stack=9492ab2d, prev=713e31c7) → KST :41–:05 창에서 공식 rerun.

- **완료(이번 세션)**: (1) detail `/v1/ops/datasets/detail` O(roots²) timeout → `all_roots` recency 창 +
  window sparse 시 unbounded fallback, snapshot은 scoped EXISTS만(유휴 scope 보존); (2) running-race →
  fast-completion tolerate. 둘 다 fix·2-reviewer·merged(**#829**)·`9492ab2d` 재cut·prod DB/live 검증.
  공식 rerun 43–52s→**142s로 3배 진행**(두 fix 작동 확인). "외부 KMA 502가 유일 blocker" 진단은 **폐기**.
- **잔여**: 후반 active 시나리오 **pre-existing flaky UI/timing**(deterministic 아님 — 백엔드는 정확,
  직전 direct API assertion PASS). official=`cleanup_blocked`, v6=`assertDatasetTerminalHistoryUi` UI static
  header 15s timeout. zero-retry 게이트라 ~50-step flow 중 flake 한 번도 실패 → test-robustness 하드닝
  필요(#829 코드 fix와 별개 작업). 상세: `docs/tasks.md` T-ADM-C7RUN + `docs/journal.md` 최신.
- 사용자 결정으로 이번 세션은 여기서 pause + write-up(실질 코드 blocker 완결 확인 후).

## 2026-07-20 (codex) — T-VN-H11 ops-live close 전달 회귀 보강 중

- #806 수정 배포 뒤 n150 API 직결 Chromium은 ticket 없음과 형식이 유효한 변조
  subprotocol을 모두 data frame 없이 `4401`로 닫았지만, 공개 TLS HAProxy 경계에서는 C7
  인증 거절 spec이 계속 `1006`으로 실패했다.
- 운영과 같은 Uvicorn `websockets-sansio`에서 즉시 `accept`→`close`하면 HTTP 101과 close
  frame이 같은 backend read에 합쳐졌다. 첫 exact TCP 회귀에서는 `asyncio.sleep(0)`도 다시
  합쳐져 scheduler checkpoint만으로는 불충분함을 확인했고, 10ms의 bounded settle window와
  5회 반복 TCP 회귀로 보강했다. 공개 proxy의 `1006`과 이 coalescing의 인과관계는 아직 선행
  가설이며, ASGI가 transport drain 완료를 보장하지 않으므로 로컬 결과만으로 완료를 선언하지 않는다.
- draft PR #810의 첫 적대 리뷰와 재리뷰를 반영해 accept부터 close까지 하나의
  cancellation-safe child task로 수행한다. accept 내부 handoff나 close 대기에서 outer task가
  반복 취소돼도 bounded operation을 끝내고, 성공한 accept에는 close 정확히 1회 후
  `CancelledError`를 재전파하도록 보강했다.
  실제 Uvicorn sansio TCP에서 handshake/close read 경계를 고정하고, accept timeout·예외가
  pre-handshake HTTP 500 fallback으로 끝나는 회귀도 추가했다.
- 단일 적대 리뷰 최종 판정은 P0/P1/P2 0이다. router 회귀 56개와 API 전체 762개, 전체 Ruff,
  API strict mypy 56개 파일이 통과했다.
- **다음 한 작업**: CI green을 확인하고 n150 공개 Chromium strict C7을 반복해 ticket 없음·변조
  모두 `4401`·data frame 0건을 최종 검증한다.

## 2026-07-20 (codex) — T-ADM-C7W browser 4401 수정 검증

- C7 strict의 두 실패는 운영 쓰기 이전 auth probe 경계였고, 실패 증거를 보존한 복구와 residue
  0건 감사를 완료했다. Chromium은 변조 protocol을 서버가 선택하지 않으면 4401 frame을 받기 전
  handshake를 `1006`으로 끝내는 것이 원인이었다.
- PR #807은 형식·단일성·길이 제한을 통과한 요청 candidate만 transport-level로 선택한 뒤,
  인증 성공 context나 nonce claim 없이 즉시 `4401`로 닫는다. 브라우저 C7 기대값은 완화하지 않았다.
- 단일 적대 리뷰 P0~P2 없음, 회귀 49개, API 전체 755개, Ruff와 strict mypy를 통과했다.
- **다음 한 작업**: 최신 main에 rebase하고 CI green 뒤 PR #807을 병합한다. exact Map image와
  compatible-pair/attestation을 재생성한 뒤 n150 strict C7을 다시 실행한다.

## 2026-07-20 (codex agent A) — T-VN-H09 weather collected_at 단조성 구현

- issue #797의 current semantic row는 최신 non-null `collected_at`만 승리하도록 writer를
  제한했다. 오래된 backfill은 no-op, 동률의 실제 변경은 후속 write 승리, 완전히 같은 동률
  재생은 물리 no-op이다.
- full fact-history schema는 correction 시점 재현과 current summary/read cutover가 함께 필요해
  이번 역행 결함의 최소 정본으로 선택하지 않았다. DB migration과 OpenAPI 변경은 없다.
- T1→T2, T2→T1, 동률 변경·동일 replay 회귀와 관련 정본 문서를 구현 diff에 포함했다.
- 첫 단일 적대 리뷰 P1의 source metric metadata 누락을 반영하고 재리뷰에서 P0~P2 없음으로
  승인받았다. draft PR #802를 열었고 unit 24개, PostGIS integration 30개, Ruff, strict mypy,
  import-linter와 docs/redaction gate가 통과했다.
- **다음 한 작업**: PR 코멘트와 GitHub CI를 확인해 green 뒤 병합하고 issue #797을 닫는다.

## 2026-07-20 (codex) — #796 standalone fail-close·backup principal 착수

- `T-VN-H02R`을 독립 PR로 열어 Map compose의 미설정 destructive 값을 `false`로 바꾸고,
  explicit `true`만 opt-in으로 인정한다. Manager production의 exact literal true 강제는 companion
  PR #68과 교차 검증한다.
- backup create/delete/restore/swap registry event actor를 인증된 `AdminProxyContext.actor`에서만
  파생하고, 사용되지 않는 `RestoreSwapRequest.operator`를 clean-cut한다. 기존 event schema가
  principal을 수용하므로 DB migration은 만들지 않는다.
- **다음 한 작업**: 문서-first commit과 draft PR을 공개한 뒤 구현·OpenAPI 산출물을 추가하고,
  단일 적대 리뷰 P0~P2 없음 승인 뒤에만 test·lint·build gate를 실행한다.

## 2026-07-20 (codex) — #798 route wiring·CORS exact 후속 착수

- T-VN-H03 적대 리뷰에서 확인된 두 잔여 경계를 `T-VN-H03R` 독립 PR로 분리했다. 앱 조립 시
  route 분류만 확인하던 경로를 실제 dependency wiring 검증으로 올리고, public CORS preflight가
  모든 method/header wildcard를 광고하지 않도록 route matrix 기반 exact 계약으로 바꾼다.
- public browser 계약은 실제 route method와 `X-Kor-Travel-Map-Api-Key` 및 표준 CORS safelist만
  허용한다. 금지 method/header는 400과 ACAO 부재로 fail-closed하며 service/operator 표면은
  계속 CORS 비노출이다. DB와 OpenAPI schema는 변경하지 않는다.
- **다음 한 작업**: 문서-first commit과 draft PR 뒤 구현을 추가하고, 같은 단일 적대 리뷰어가
  P0~P2 없음으로 승인하기 전에는 test·lint를 실행하지 않는다. 첫 리뷰의 conditional GET header와
  전체 public method 합집합 광고 지적을 반영했고 재리뷰 P0~P2 없음 승인을 받았다. focused 58개와
  API package 전체 746개, Ruff, strict mypy, OpenAPI drift가 통과했다. 이제 CI green 뒤 병합한다.

## 2026-07-20 (codex agent A) — T-VN-H08 Tier-2 p95 nearest-rank 산식 구현

- issue #799를 독립 ext4 `fix/tier2-nearest-rank-p95` branch의 PR 단위 task로 열었다.
- Tier-2 release harness의 percentile을 오름차순 nearest-rank로 단일화했다. 실행시간 p50·p95와
  shared read blocks p95 모두 공용 helper를 사용하며 보간하지 않는다.
- p95 경계 표본 `n=1/20/30/100`의 선택 index와 값을 단위 fixture로 고정했다.
- 구현 diff는 단일 적대 리뷰에서 P0~P2 없이 테스트 승인을 받았다. 대상 unit 15개·integration
  5개, Ruff, strict mypy·본 패키지 mypy, import-linter, `py_compile`, `git diff --check`가
  통과했다.
- 최신 main에 rebase한 draft PR #801을 열고 issue #799를 연결했다.
- **다음 한 작업**: PR 코멘트를 반영하고 CI green 뒤 병합해 #799를 닫는다.

## 2026-07-20 (codex agent B) — #741·#785·T-VN-15 targeted lane 구현·복구 계약 완결

- draft PR #792를 최신 main 계열에 rebase하고, 기존 #741/#785 시나리오에 `T-VN-15`의
  active search fixture 2건, total on/off continuation, query/include_total mismatch,
  payload tamper 422를 결합했다. browser는 same-origin `/api/proxy`만 사용하고 public key
  query는 사용하지 않는다.
- 첫 적대 리뷰의 late `docker compose exec/create` P1을 반영해 direct helper·Playwright
  executor·missing-secret probe를 모두 deterministic labeled standalone container로 바꿨다.
  runner barrier FD를 `setsid` supervisor가 상속하고 PID/PGID/SID/start ticks·intent·CID·terminal을
  fsync한다. runner SIGKILL 뒤 recovery는 supervisor 종결까지 barrier에서 기다리며, terminal이
  없는 cgroup/OOM kill은 자동 clear하지 않는다.
- strict C7 root verifier를 exact C7 snapshot에서 호출해 host attestation v3, compatible-pair v4,
  actual service image/command/env/compose/origin을 mutation 전에 다시 검증한다. Map API cursor
  secret의 production/features/중복/길이/공백/credential 분리와 다른 네 role 부재를 확인하며,
  exact API image의 network-none/read-only missing-secret probe도 추가했다.
- direct cleanup은 ownership fingerprint parent를 `SELECT ... FOR UPDATE`로 잠근 transaction
  안에서 child fingerprint·모든 FK를 audit하고 삭제한다. 이 row lock이 late child insert의
  `KEY SHARE`와 충돌하므로 별도 tombstone이나 DB schema 변경은 필요하지 않다.
- evidence는 normal 6개 operation×8 phase, recovery 3개×8 phase와 direct/report/probe exact
  schema·count·root metadata를 검증하고 전체 file/directory fsync 뒤 result와 BLOCKED clear를
  순서대로 확정한다. 구현/static contract 커밋까지 만들었으며 test·lint·build·parser는 아직
  실행하지 않았다.
- 동일 리뷰어의 재검토 P2 4건도 반영했다. C7 raw output은 container `/tmp` tmpfs로 분리하고
  evidence report subtree는 exact 3 regular files와 JSON/XML/HTML content를 검증한다. helper
  runtime env는 unique memory map→Docker child env와 `--env NAME`만 사용해 disk copy를 없앴다.
  direct cleanup은 parent에 이어 기존 child도 `FOR UPDATE`하며, browser cleanup은 exact search
  `items=[]`, `total=0`, cursor null/absent를 normal/recovery-only 모두에서 확인한다.
- **다음 한 작업**: 보강 exact head를 같은 단일 적대적 리뷰어에게 재제출한다. P0~P3
  없음 승인 뒤에만 gate를 실행하고, CI green·exact 배포 확인 뒤 WSL SSH로 n150 production
  destructive live를 완료해 #741·#785를 닫는다.

## 2026-07-20 (codex agent B) — #741·#785 targeted live 인수 보강 착수

- `main@700c8ccd` 기준으로 두 이슈의 미완료 조건이 n150 live 증거임을 확인했다. strict C7
  runner의 복구 journal에 feature correction mutation을 섞지 않고 별도 serial lane으로
  분리한다.
- #785는 owned Feature의 UI basis raw ETag, 승인된 경쟁 update, stale UI `If-Match` 412,
  dirty draft 보존, 명시적 reload, current-ETag cleanup을 한 흐름으로 증명한다.
- #741은 `draft`·`inactive`·`hidden` owned marker의 admin UI/API 노출과 public active-only
  음성 계약을 증명한다. admin API가 만들 수 없는 weather/price kind는 runner가 mutation 전에
  root-owned BLOCKED/journal을 만든 뒤 전용 helper로 고유 fixture를 넣고, UI panel·non-empty
  card·public 음성 계약을 확인한 뒤 exact ID만 물리 삭제한다.
- **다음 한 작업**: docs-first commit과 draft PR을 공개한 뒤 구현 exact head를 단일 적대
  리뷰어에게 제출한다. 승인 전에는 test·lint·build를 실행하지 않는다.

## 2026-07-20 (codex) — T-ADM-C7F prod topology Alembic check 보강 착수

- n150 최종 main 배포에서 실제 DB를 `0023`에서 `0062_feature_row_revision`까지
  forward migration했고 `current == head`를 확인했다. 대용량 `0060`이 Manager API health
  timeout보다 오래 걸려 exact candidate image의 migration-only 경로로 완료했다.
- 필수 `alembic check`는 app drift가 아니라 infra owner의 `postgis_topology`가 소유한
  `topology.layer`·`topology.topology`를 삭제 대상으로 오인해 실패했다. 빈 DB CI는 migration
  user가 topology extension을 제거하므로 이 production 소유권 배치를 재현하지 못했다.
- `T-ADM-C7F`는 extension-owned `topology` schema만 Alembic 비교에서 제외하고, head 적용 뒤
  topology extension을 다시 설치한 production-equivalent integration gate를 추가한다.
- **다음 한 작업**: docs-first PR을 연 뒤 구현을 추가하고 단일 적대 리뷰 승인 후 테스트·CI를
  통과해 main에 병합한다. 이후 n150 exact image rebuild와 C6c capture를 재개한다.

## 2026-07-20 (claude, n150) — T-VN-H02 destructive admin 기본값 fail-closed 완료

- `admin_destructive_enabled` 기본값을 fail-closed(False)로 내리고, 문서화된 env alias
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`가 실제로 바인딩되도록 `validation_alias`를 추가했다.
  Docker compose는 컨테이너 기본 true를 주입해 기존 배포를 유지한다.
- **배포 전제**: n150 prod와 파괴적 작업이 필요한 배포는 host env로
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true`를 유지해야 한다. 미설정 시 restore/swap·feature
  deactivate·POI/backup/offline delete·file purge가 403.
- **다음 한 작업**: 남은 독립 하드닝(T-VN-H03 surface별 CORS 분리 등)을 이어서 진행한다.

## 2026-07-20 (codex agent B) — T-VN-59 public raw lineage 보강 착수

- T-VN-SYNC-02 적대적 리뷰 blocker를 issue #786·`T-VN-59`로 분리했다. public forecast의
  `source_record_key`, public alert의 원문 payload·lineage·수집 시각, public curation item의
  `source_record_key`·자유형 metadata가 user OpenAPI와 생성 client까지 도달하는 상태다.
- public typed DTO와 operator raw DTO를 상속 없이 분리하고, 공개 응답 schema의 재귀
  reachability를 검사하는 forbidden-field gate로 같은 종류의 누출을 구조적으로 막는다.
- 문서-first commit으로 draft PR #788을 연 뒤 구현과 full/user OpenAPI·admin/user TypeScript
  산출물을 추가했다. DB schema와 저장 repository는 바꾸지 않았고, admin curation 및 새
  admin weather alert raw route가 operator 정보를 보존한다.
- **다음 한 작업**: 구현 exact head를 동일 적대적 리뷰어에게 제출한다. 승인 전에는
  test·lint·build·OpenAPI drift gate를 실행하지 않는다.

## 2026-07-20 (codex) — T-VN-58 correction 편집 기준 ETag 고정 착수

- issue #785를 `integration/t-vn` 기준 독립 task로 열었다. admin 수정·삭제가 submit 직전 최신
  revision을 다시 읽어 stale draft를 최신 기준으로 오인하는 경로를 제거하고, detail snapshot과
  raw strong `ETag`를 불변 `CorrectionBasis`로 고정한다.
- DB·REST/OpenAPI schema는 바꾸지 않는다. 412에서는 draft를 보존하고 운영자의 명시적 reload가
  성공할 때만 최신 detail·basis를 적용한다. update/delete, background refetch 보호, mocked/live
  Playwright cleanup까지 같은 PR에 묶는다.
- draft PR #789에 docs-first commit을 push한 뒤 `/revision`→detail 안정 basis, caller-supplied raw
  ETag mutation, dirty form 보호, 412 explicit reload, update/delete와 live cleanup 회귀를 구현했다.
- 첫 적대 리뷰의 P1 2건/P2 2건에 따라 initial in-flight 전체 draft guard, 실패 reload old-data
  거부, exact 3-pair retry budget, live update/delete baseline ETag 단정을 보강했다.
- 두 번째 적대 리뷰의 P1/P2에 따라 전역 dirty guard를 필드별 dirty overlay로 바꾸고, mutation
  state 초기화를 `action + trimmed feature_id` identity가 실제로 바뀔 때로 제한했다. deferred
  basis의 untouched category/marker baseline 적용과 same-value/공백 Feature ID 편집 뒤 412 제출
  차단을 mocked E2E로 고정했다.
- 세 번째 적대 리뷰의 P1 2건에 따라 nullable marker fallback은 dirty key일 때만 PATCH하고,
  위치 편집창은 dialog-local dirty key만 parent에 반영하며 parent basis의 untouched 필드를 계속
  동기화하도록 보강했다. null marker name-only와 deferred basis 중 좌표-only dialog 회귀가 모두
  marker PATCH 미포함을 단정한다.
- **다음 한 작업**: 이 exact head를 push하고 같은 단일 적대 리뷰어에게 재제출한다. 승인 전에는
  test·lint·build를 실행하지 않는다.

## 2026-07-20 (codex, agent B) — T-VN-57 public security 계약 docs-first 착수

- T-VN-SYNC-02 적대적 리뷰에서 runtime `PUBLIC_KEYED` 29개 GET과 full OpenAPI의 security
  선언을 전수 대조했다. runtime은 전부 `require_public_api_key`를 적용하지만 full spec은
  curated 4개만 `PublicApiKey OR ServiceToken`을 선언해 25개가 누락되고, user spec도 노출한
  27개 중 23개가 누락된다. 최상위 security가 없어 기계 계약상 무인증으로 해석되는 P1이다.
- `USER_OPERATIONS`도 별도 수기 allowlist라 신규 public route의 user 편입 누락을 조용히 허용하는
  P2다. T-VN-57/#784는 `ROUTE_POLICIES`와 조립된 method metadata를 runtime·full/user 계약의
  단일 정본으로 사용하고 양방향 누락·과포함·method/security drift를 막는다.
- CodeGraph는 `ROUTE_POLICIES` 57개, `create_app` 176개 영향 심볼과 route wiring gate caller
  5개를 보고했다. **다음 한 작업**은 docs-first draft PR을 연 뒤 구현 diff를 같은 단일 적대
  리뷰어에게 제출하는 것이다. 승인 전에는 생성 artifact 작성 외 test/lint/build/OpenAPI check를
  실행하지 않는다.
## 2026-07-20 (codex) — vNext integration 구현 병합·최종 cutover 추적 정렬

- T-VN-04A PR #779는 merge commit `21ad4e312b3d2a3e1b8baf1b3103daa6cec15e87`,
  T-VN-15 PR #780은 merge commit `7604fc92585d8f973725f11bf8234a6d22034bc4`,
  T-VN-03 PR #782는 merge commit `226f81c2cb5f89dec9bdd696121f4f8cd60f96c0`로
  `integration/t-vn`에 반영됐다. 세 PR 모두 CI 8개가 green이지만 세 task와 issue #741은
  final n150 live UI 증거 전까지 active다.
- PinVi T-VN-03 소비자 PR #393은 merge commit
  `61820f0ab0a7000948477511b3e92926fe78d1d4`, docker-manager production env PR #64는
  merge commit `3f9973806e8addff96eb1339602f992ed424fb1c`로 각 저장소 main에 반영됐다.
- 완료된 main→integration 동기화 `T-VN-SYNC-01`은 PR #781 merge commit
  `a45bc3ac401e5675811f1031a4592991498d899f` 근거로 완료 이력에 옮겼다. 최종
  integration→main 합류는 독립 `T-VN-SYNC-02`로 추적한다.
- **다음 한 작업**: 문서 추적 PR #783을 최신 integration에 병합한 뒤 `T-VN-SYNC-02`를 수행한다.
  최종 main·PinVi·manager exact 조합으로 C6c manifest v4 capture와 n150 C7 live E2E를 마치기
  전에는 `T-VN-03`·`T-VN-04A`·`T-VN-15`, `T-ADM-C6c`·`T-ADM-C7P`·`T-ADM-C7`를
  아카이브하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-03 교차 리뷰 P2 반영

Map/PinVi 교차 리뷰가 user export allowlist에서 public curated sources/themes 두 GET이
빠진 계약 drift를 확인했다. `USER_OPERATIONS`를 curated 4 GET 전체로 맞추고
`openapi.user.json`과 user TypeScript를 정본 생성기로 다시 만든다. CI E501 한 건은
기계적 줄바꿈으로 함께 고친다. **다음 한 작업**은 새 exact head를 같은 리뷰어에게
재제출하는 것이며, 승인 전 테스트·lint·build는 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-03 Map 구현 head 준비

curated GET 4개에 `require_public_api_key`, ops 관측 GET 6개에
`require_ops_operator`, local-dev MOIS raw debug에 `require_admin_frontend`를 배선하고
route policy exception을 0건으로 줄였다. production은 기존 profile matrix와 compose
기본값으로 debug route를 mount하지 않으며, 새 env/secret/DB migration은 없다. full/user
OpenAPI security와 admin/user 생성 TypeScript, same-origin BFF 회귀를 함께 갱신한다.
CodeGraph는 `create_app` 181개, ops dependency 199개, public dependency 58개, wiring gate
44개 영향 심볼을 보고했다. **다음 한 작업**은 생성물을 포함한 exact Map head와 PinVi
PR #393 exact head를 동일 전문 리뷰어에게 교차 제출하는 것이다. 승인 전에는 테스트·lint·
build를 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-03 route gate docs-first 착수

`integration/t-vn@a45bc3ac` 기준으로 curated GET 4개, ops 관측 GET 6개, MOIS raw debug
GET 1개의 잔여 인증 경계를 inventory했다. PinVi PR #387이 principal 설정은 추가했지만
consistency/log client 네 메서드에 `ops:read`를 보내지 않아 Map gate 선적용 시 403이 되는
cross-repo blocker를 확인했고 PinVi issue #392로 분리했다. 설계 정본은
`docs/reports/t-vn-03-route-gate-cutover-2026-07-19.md`다. **다음 한 작업**은 양 저장소
docs-first draft PR을 연 뒤 구현 head를 동일 전문 리뷰어에게 교차 제출하는 것이다. 승인 전에는
테스트·lint·build를 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-15 구현·생성 계약 준비 완료, 테스트 전 리뷰 대기

`/v1/features/search`의 total opt-in을 repository 실행 계약으로 내리고,
`include_total=false`에서는 COUNT statement를 전혀 실행하지 않도록 고정했다. cursor는 DB table 없는
stateless v1이며, SQL과 같은 정규화 q/filter/sort/page contract fingerprint와 keyset을 전용
server-only secret의 HMAC-SHA256으로 보호한다. production secret 누락/짧음/재사용은 fail-closed,
local-dev만 process-local 난수 fallback이다. malformed, unknown version, tamper, query mismatch는
DB 전에 별도 typed RFC7807 422로 반환한다. repository/client/API, settings/entrypoint/Compose,
admin UI consumer, admin/user OpenAPI와 생성 TypeScript, repository spy·실제 PostgreSQL·runtime
matrix 테스트까지 PR #780에 준비했다. **다음 한 작업**은 최신 `integration/t-vn`에 rebase한 exact
head를 push하고 같은 단일 적대 리뷰어에게 테스트 전 검토를 요청하는 것이다. 승인 전에는
test/lint/build를 실행하지 않는다.
## 2026-07-19 (codex, agent B) — T-VN-04A admin 비공개 Feature 구현·리뷰 대기

- issue #741을 `integration/t-vn` 기준 독립 PR로 분리했다. public projection을 우회하거나
  느슨하게 만들지 않고, base Feature용 admin bbox/cluster와 admin weather/price card를 구현했다.
  지도·테이블·marker 상세·상태 필터가 동일한 admin 경계를 사용하며 공개 active-only 계약은
  유지한다. 카드 target도 `deleted_at`/`user_deleted_at`/`status=deleted`를 제외한다. 기존
  partial GiST가 모든 nondeleted 상태를 포함하므로 DB migration은 만들지 않았다.
- full OpenAPI와 admin TypeScript 타입을 재생성하고 repository/router/frontend/PostGIS·route-mock
  회귀를 작성했다. **다음 한 작업**: 정확한 구현 head를 같은 적대 리뷰어 1명이 테스트 전에
  검토한다. 승인 전 테스트·lint·build는 실행하지 않는다.
## 2026-07-19 (codex) — latest main → integration/t-vn 동기화 리뷰 대기

`integration/t-vn@22bf35a5`에 `main@d2104f15`를 merge하는 전용 sync branch를 만들었다.
main의 C7 manifest v4·4-image attestation과 integration의 vNext DB/API를 한 source tree로
결합하면서 Dockerfile의 OCI revision label과 production profile을 모두 보존했고, 문서 이력과
완료 task 정본을 정리했다. Alembic은 `0058 → 0059 → 0060 → 0061 → 0062` 단일 head다.
**다음 한 작업**은 draft PR의 동일 전문 리뷰어가 코드 conflict 해소를 승인하는 것이다. 승인
전에는 테스트·lint·build를 실행하지 않고, 승인 뒤 integration 대상 CI gate를 수행한다.

## 2026-07-19 (codex) — T-ADM-C7P compatible-pair manifest v4 동기화 착수

- docker-manager C6c provenance를 Map API/UI/Dagster web/Dagster daemon 네 image에 닫으면
  기존 Map C7 attestation의 manifest v3 exact parser와 충돌함을 확인했다.
- issue #777을 추가하고 host attestation version 3과 manager compatible-pair manifest
  version 4를 분리했다. v4 active/rollback은 Map 네 image ID·Map source revision·PinVi
  image/revision·contract generation·recorded time의 exact 9-field pair다.
- **다음 한 작업**: 문서 선행 commit 후 C7 attestation parser·runtime image 비교·음성
  fixture를 v4로 clean-cut하고, manager PR #61과 함께 단일 적대적 리뷰를 받는다.
- **최종 cutover 순서**: C7P 두 PR 병합(미배포) → main을 `integration/t-vn`에
  병합 → 잔여 T-VN blocker 종결 → integration을 main에 병합 → 최종 exact image
  조합 C6c v4 capture → C7 destructive live E2E다. 이로써 `T-VN-03`의 C6c 동일
  배포 조건과 C7 runner v4 조건을 모두 만족한다.

## 2026-07-19 (codex) — Agent A PR #755 summary 가시성 보완

- 단일 전문 리뷰에서 확인한 mocked E2E 가시성 공백을 닫아, summary exact projection
  12개가 DOM에 유일하게 존재하고 실제 사용자에게 보여야 통과하도록 수정했다.
- targeted mocked E2E 3개와 E2E TypeScript, 대상 ESLint가 통과했다.
- **다음 한 작업**: `main` 후속 PR을 CI green으로 병합하고 최근 2일 Agent A PR을
  다시 조회한다.

## 2026-07-19 (codex) — T-ADM-C7H 병합·아카이브

- 단일 전문 리뷰의 4개 finding을 반영해 `*.local.md` Docker context 차단, Playwright
  bridge/private 격리, 전체 상태 auditor preflight, 실패 recovery journal/runtime
  보존을 구현했다.
- 후속 재검토의 P1 두 건을 반영해 auditor를 root-owned 4파일 exact attestation에 포함하고
  INT/TERM 종료를 130/143으로 고정했다. 같은 리뷰어의 최종 판정은 P0~P3 잔여 없음이다.
- 대상 보안/unit 55개와 전체 unit 1,529개, `bash -n`, Ruff, strict mypy,
  import-linter가 통과했다.
- PR #754와 누락된 두 P1을 닫은 PR #762는 PostGIS integration을 포함한 CI 8개를 각각
  모두 통과해 merge commit `b9f23a42`, `bece2c32`로 `main`에 반영됐다. current exact commit의
  immutable executor image build도 성공했다. `T-ADM-C7H`는 완료 이력으로 옮겼다.
- **다음 한 작업**: n150 SSH 경로가 복구되는 즉시 passwordless sudo→backup/PITR→forward-only
  migration→C6c capture→C7 live E2E를 실행하고 #684/#694/#712/#719를 증거와 함께 닫는다.

## 2026-07-19 (codex) — T-ADM-C7H 실행 경계 보강

- C7 실행 전 단일 적대 리뷰에서 실제 배포 pair/DB schema 증거 부재, host npm/Chromium 의존,
  잘못 선언된 Dagster job 이름, preflight 전 `BLOCKED.json`, 실패 evidence 유실을 차단 finding으로
  확정했다. 실제 run-now job은 provider별 KMA job이 아니라 `feature_update_request_worker`다.
- 문서·task를 먼저 갱신하고 `fix/c7-prod-readiness`에서 compatible-pair manifest와 root-owned
  exact-commit orchestrator snapshot 계약,
  5개 service image/command/environment와 compose project, source commits, executor image, Alembic
  current/head/check를 read-only 대조하도록 runner를 보강 중이다. mutation 상태는 모든 preflight 뒤에만
  만들고 spec별 redacted evidence와 별도 감사 도구를 남긴다.
- PR #754 리뷰 후속으로 snapshot/runtime 검증 코어를 import 가능한 모듈로 분리하고, runner가
  root-owned hash를 확인한 동일 bytes를 실행하게 했다. root로 실행하는 runner/helper/module/상태
  감사기 4개를 exact hash에 묶고 INT/TERM을 130/143으로 보존했다. attestation·pair·OCI runtime
  변조와 signal 종료의 실행형 음수 fixture를 포함한 대상 55개, 전체 unit 1,529개를 통과했고
  동일 리뷰어가 P0~P3 잔여 없음으로 승인했다.
- n150은 WSL SSH 41회와 Windows TCP/22 boolean 진단 모두 연결 전에 실패했다. 따라서
  `sudo -n true`는 아직 성공/실패 어느 쪽으로도 판정하지 않았고 원격 mutation도 0건이다.
- **후속 결과**: PR #754와 PR #762로 병합·아카이브했으며 n150 live 실행만 남았다.

## 2026-07-19 (codex) — T-ADM-C7M mocked UI 수용 증거 병합·아카이브

- `/ops/datasets` summary landmark의 exact projection과 오염 negative fixture,
  `/ops/pipeline` 실행·event의 6+6 cursor 주입, 요청 scope·cursor와 전체 DOM identity·정렬·페이지
  경계를 PR #755에서 고정했다.
- 6+6 fixture는 canonical `page_size=50` overflow 증거가 아니라 cursor plumbing 증거로 명시했다.
  실제 51건 이상 continuation과 #694/#719의 최종 live 종결은 열린 `T-ADM-C7` n150 검증에 남긴다.
- 단일 적대적 리뷰 지적을 반영하고 targeted mocked E2E 3건과 CI 8개 게이트를 통과했다.
  PR #755는 merge commit `54150c91`로 `main`에 반영됐으며 `T-ADM-C7M`은 완료 이력으로 옮겼다.
- **다음 한 작업**: PR #754의 C7 production live E2E 실행 경계 보강을 CI green으로 병합한 뒤,
  n150 compatible-pair 배포와 파괴적 live 검증을 수행한다.
## 2026-07-19 (codex) — PR #772 T-VN-13 적대 리뷰 보완 완료

전문 리뷰어 1명의 테스트 전 심층 검토에서 승인 TOCTOU, add overwrite, validator 범위·형식,
migration 원자성, public/Admin/PinVi 소비자 계약 누락을 확인했다. pending 요청은 제출 시
`base_row_revision`을 고정하고 승인 시 row lock 아래서 비교하며, add는 같은 ID를 덮어쓰지 않는다.
public detail ETag/304와 Admin 전용 revision endpoint를 분리했고 bundled frontend와 PinVi client가
revision GET의 raw ETag를 PATCH/DELETE `If-Match`로 전달한다. PinVi는 stale 412를
`PRECONDITION_FAILED`로 노출한다. PinVi 소비자 PR #391은 main에 먼저 병합됐고 원 PR #772가
검증 중 선행 병합되어 보완은 후속 PR #776에 담았다. **다음 한 작업**은 #776 CI green·통합 병합
뒤 C6c/C7 gate를 재확인하고 Agent B lane의 다음 미완 task를 시작하는 것이다.

## 2026-07-19 (codex) — PR #773 2차 적대 리뷰 blocker 구현 완료

- 경계 geometry의 cluster 귀속을 저장 canonical 행정코드 기준 feature당 1회로 확정하고
  문서/교차 bbox fixture에 고정했다. marker 계산은 실제 bbox 교차 부분을 유지한다.
- 공유 `ClusterUnit`을 기준으로 `meta.cluster.cluster_unit`을 필수 enum,
  `drill_down_unit`을 필수 enum|null로 만들고 OpenAPI/TypeScript 산출물을 갱신했다.
- geom-only 대표 분포의 planner-default partial GiST EXPLAIN 회귀까지 추가했다.
- **다음 한 작업**: 같은 적대 리뷰어가 blocker를 재검토한 뒤 승인되면 전체 테스트 게이트를
  실행한다. 재리뷰 전 테스트는 사용자 지시에 따라 미실행 상태다.

## 2026-07-19 (codex) — Agent A PR #763 심층 리뷰 후속 보완 완료

- route/area exact predicate의 centroid 우회를 차단하고 cluster/items 공간 후보를
  일치시켰으며, geometry marker를 bbox 교차 부분에서 계산한다.
  `cluster_unit`/`drill_down_unit`은 `meta.cluster`로 일원화했다.
- 전체 main unit 1,503건, API router 26건, PostGIS/성능/공개 회귀 34건과 OpenAPI·TS·
  Ruff·mypy·import-linter·redaction 게이트가 통과했다.
- **다음 한 작업**: 후속 PR을 CI green 뒤 `integration/t-vn`에 병합한다.
## 2026-07-19 (codex, agent B) — T-VN-05R 공개 curated raw 경계 보강

- issue #765의 우회 경로를 닫기 위해 공개 curated list/detail을 admin
  `CuratedFeatureView`에서 분리한 `PublicCuratedFeatureView` allowlist로 전환했다.
  동일 리뷰어 후속 3건을 반영해 `feature_kind` 판별 7종 union, strict 주소/kind별 detail,
  place 시설·영업시간·전화·리뷰 링크 projector를 완결했다. 실제 concierge
  YouTube/transcript/evidence 미러와 미승인 nested raw를 제거하며 알 수 없는 kind는
  목록 제외/상세 404로 fail-closed한다. 공개 목록의 내부 identity 필터
  `theme_id/source_id/provider/dataset_key`도 제거했다.
- admin `/v1/admin/features/curated*`는 기존 전체 DTO와 raw 감사값을 유지한다. 공개
  list/detail sentinel 회귀와 full/user OpenAPI schema 분리, admin/user 생성 타입 갱신을
  같은 변경에 포함한다.
- **다음 한 작업**: OpenAPI/TypeScript 생성물을 갱신하고 PR #774에 후속 커밋한다. 이번
  커밋은 요청대로 테스트를 실행하지 않고 CI 결과를 후속 확인한다.

## 2026-07-19 (codex, agent B) — T-VN-21R 구현 완료·리뷰 대기

- #767 구현을 `fix/t-vn-21r-benchmark-correctness`에 준비했다. Tier-2 harness는
  seed/skip-seed 모드 모두 DB의 non-notice public ID 200개로 batch를 구성하고,
  terminal LIMIT 전 `matched_rows`와 LIMIT 뒤 `returned_rows`/최소 cardinality를
  분리해 검증한다. shared read는 최상위 Plan 누적값으로 단일화했다.
- seed inactive 규칙·notice 후보 제외·199건 부족·실제 truncation·모든 viewport
  수량·root/child·Append/parallel plan 회귀 테스트를 작성했다. **다음 한 작업**:
  같은 적대적 리뷰어 1명의
  테스트 전 승인을 받고 finding을 반영한 뒤 로컬 gate를 실행한다.

## 2026-07-19 (codex) — 최근 48시간 Claude PR 적대 리뷰 후속 계획

- 단일 전문 리뷰어가 PR #752/#756/#757/#759/#760/#763을 심층 검토했다. #757/#759는
  추가 P0~P3가 없고, public curated raw lineage(#765), weather UNIQUE cutover race(#766),
  release benchmark cardinality·buffer 합산(#767), cluster/items 공간 universe drift(#768)를
  상세 PR 코멘트와 네 이슈로 기록했다.
- 문서를 먼저 갱신해 `T-VN-05R/17R/21R/14R` 네 PR 경계와 agent A/B 병렬 lane을 고정했다.
  #765/#766/#767은 `integration/t-vn` 대상 독립 PR, #768은 열려 있는 PR #763의 후속 커밋이다.
  0060은 호환성보다 원자성을 우선해 dedup+non-concurrent UNIQUE를 한 transaction으로 묶는다.
- `T-VN-17R` 구현은 과거 retry 잔여만 짧은 autocommit DDL로 정리한 뒤 0060이 5초 제한의
  `SHARE ROW EXCLUSIVE`를 얻어 dedup→non-concurrent semantic UNIQUE를 한 transaction에서 commit하도록
  정정했다. main build는 SELECT를 허용한다. VALIDATE에도 session-level 5초 timeout과 RESET을
  적용하고, 기존 제약 위반은 destructive commit 전에 `23514`로 거부하며, downgrade는
  backup/PITR 전용으로 fail-closed한다. 실제 migration
  DELETE 내부를 advisory gate로 멈춘 writer 차단, VALIDATE blocker timeout·재시도, 과거 concurrent
  실패 INVALID index 자동 복구, head→0059 무변경 전역 downgrade 거부 회귀를 추가했으며 두 번째
  단일 리뷰 finding 반영 후 재리뷰 대기다.
- **다음 한 작업**: 문서 PR 병합 직후 네 task를 병렬 구현하고, 같은 리뷰어 1명의 테스트 전
  승인→로컬 gate→CI green→integration 병합→issue close까지 수행한다.

## 2026-07-19 (claude, agent A2) — T-VN-14 지도 in-bounds 완결성 + exact 공간 술어 구현

- `feat/t-vn-14-map-completeness`(base `integration/t-vn`)에서 ADR-073 D-9-3/D-9-4·F-8을
  구현했다. (1) `include_geometry`를 serialization-only로 만들었다 — 경량/geometry bbox SQL의
  WHERE를 단일 후보 술어(`_bbox_candidate_predicate_sql`)로 통일해 membership이 플래그와
  무관하게 동일하고 payload만 다르다(2220→2221 버그 해소). (2) route/area에 exact
  `ST_Intersects`를 적용해 `&&` MBR false positive를 제거(point `&&`는 유지, `ST_Transform`
  없음). (3) in-bounds 응답 DTO에 `mode`/`truncated`/`coverage`/`cluster_key`+drill-down을
  명시하고 `max_items+1`로 truncation을 명시 판정. (4) 공통 attribute 필터를
  `_bbox_attribute_filter_sql`로 단일화해 3변형의 이중 SQL 복제 제거.
- 스코프 준수: bbox/in-bounds/cluster READ SQL + in-bounds DTO만 수정. public_features
  view·weather/price LATERAL·인덱스/모델·write 경로 무수정. OpenAPI 재생성(drift 0).
  검증: 신규 통합 2 + perf-gate tier-1 12 + 회귀 17 = 31 green(WSL testcontainers, 최소 seed),
  router 단위 30 green, ruff/mypy --strict/lint-imports/redaction clean, C: 무증가.
- **후속**: 적대적 리뷰에서 cluster/items 후보 발산과 centroid coord 우회가 확인되어 위
  보완 항목에서 수정했다.

## 2026-07-19 (claude, agent A1) — T-VN-13 Feature row_revision + If-Match/ETag 구현

- `feat/t-vn-13-row-revision`(base `integration/t-vn`, migration head 0061)에서
  `feature.features`에 server-owned monotonic `row_revision`을 추가(migration 0062,
  BEFORE UPDATE 트리거 = 0058 poi lock_version 미러링)하고 correction PATCH/DELETE/approve에
  If-Match(누락 428·형식 422·stale 412·성공 시 새 ETag), admin detail GET에 ETag/304를
  연결했다. #727 policy revision과 합치지 않음(F-2). 낙관적 검사는 repo `expected_row_revision`에
  원자적으로(FOR UPDATE) 넣고 라우터는 사상만 담당. model에 컬럼+CHECK 미러링 → T-VN-19 gate green.
- 검증: 라우터 단위 16 + row_revision 통합 3(WSL testcontainers 1행 seed) + alembic metadata
  정합 gate green, ruff/mypy/lint-imports clean, openapi drift 0, 생성 TS 타입 재생성·frontend
  type-check green.
- **다음 한 작업**: 적대적 리뷰(오케스트레이터) → PR·CI green·머지. **follow-up(별도)**: admin
  frontend가 GET ETag → correction에 If-Match 전송(현재 미전송 시 428), PinVi client 동일 갱신
  (cross-repo). 그리고 아래 **환경 사고**(dev postgres 컨테이너 오삭제) 복구를 사용자가 처리해야 함.

## 2026-07-19 (claude, agent A1) — T-VN-21 3단 성능·DDL gate 인프라 구현

- `feat/t-vn-21-perf-gate`(base `integration/t-vn`)에서 ADR-075 D-12-4의 3단 성능·DDL
  gate를 CI·release 절차에 연결했다. tier-1(매 PR, integration job):
  `tests/integration/test_perf_gate_tier1.py`가 hot public query 9종을 planner-default
  EXPLAIN해 `feature.features` Seq Scan 부재·기대 index·N+1 가드·response-shape 회귀를
  검증(helper·registry·seed는 `tests/integration/perf_gate.py`). tier-2(release, CI 아님):
  `scripts/perf_tier2_release_harness.py`가 100만+ 실분포에서 대표 viewport를
  EXPLAIN(ANALYZE,BUFFERS)로 재고 p95·shared read·bytes를 JSON 기록. tier-3(index PR):
  `measure_index_write_cost` helper + 리뷰 enforce. 정본은 performance.md §8.3.
- 스코프 준수: feature_repo 쿼리/라우터/마이그레이션/모델 무수정. 모든 hot query가
  planner 기본에서 `features` clean(실 perf-bug 없음). tier-1 12 tests green
  (WSL testcontainers), ruff/mypy(신규 파일)/lint-imports/redaction clean, openapi drift 없음.
- **다음 한 작업**: 적대적 리뷰(오케스트레이터) → PR·CI green·머지. tier-2 harness의 실제
  100만행 실분포 측정과 release 리포트 첨부는 실제 cutover 시점 별도 작업.

## 2026-07-19 (claude, agent A1) — T-VN-20 body actor 전면 제거 구현

- `feat/t-vn-20-actor-principal`(base `integration/t-vn`)에서 모든 admin write의 감사
  actor를 인증 principal(`AdminProxyContext.actor`)에서만 파생하도록 완결했다(ADR-066
  D-2, T-VN-07 완성). PinVi `origin/main` client 대조로 결정: PinVi가 보내는 feature/
  issue operator·dedup reviewed_by는 deprecated 수용·무시, 나머지(auth-event/curated/
  enrichment/offline)는 schema 제거(422). admin frontend에서 body actor 전송 제거,
  OpenAPI/TS 재생성, 두 class(principal 기록 + 422/ignored) 테스트. PinVi 전송 중단
  follow-up은 `docs/integration-map.md` §3.3에 성문화.
- **다음 한 작업**: 적대적 리뷰(오케스트레이터) → full gates → PR·CI green·머지. PinVi
  client의 operator/reviewed_by 전송 제거는 PinVi 저장소 별도 PR(cross-repo).

## 2026-07-19 (claude, agent A2) — T-VN-18 중복 GiST 제거 + BRIN 감사 완료

- migration 0061 + models.py `spatial_index=False`로 자동 full GiST 3개를 제거하고
  공개 술어 partial GiST 3개만 유지, weather source-record 지원 index 추가(T-VN-17
  이월), BRIN은 누락 hot 축이 없어 추가 안 함(감사). write-cost 실측 6-GiST vs
  3-partial ≈ 1.18~1.29× 개선(§8.3). 브랜치 `feat/t-vn-18-gist-brin`.
- 게이트: ruff/mypy(main)/lint-imports/redaction green; T-VN-18 통합 5 + metadata
  gate/upgrade 11 + perf-explain/public-view 5 passed. **미완**: 세션 누적으로
  Windows C:가 0 bytes → Docker read-only가 되어 `test_weather_repo.py` 회귀
  미실행(정적으로는 partial index 단언이라 호환). C: 확보 후 재실행 + 최종 rebase
  검증 필요.
- **다음 한 작업**: C: 디스크 확보 → weather 회귀 재실행 → orchestrator 리뷰·PR·머지.
## 2026-07-19 (codex) — Agent A T-VN-19 심층 리뷰 보완

- PR #753의 단일 전문 리뷰에서 metadata 비교 제외 table 8개의 구조 gate 부재와,
  제외 index가 이름만 같으면 잘못된 UNIQUE·키·predicate도 통과하는 S2 두 건을
  확인했다. 전체 column type/nullability, 핵심 constraint/index, 인증·운영 CHECK
  거부 동작과 index 의미를 빈 DB migration 뒤 검증하도록 보완했다.
- 새 ORM mapping이 임시 제외 목록에 남으면 Alembic 시작 시 실패하는 stale-exclusion
  guard도 추가했다. env와 테스트는 schema-qualified 공용 ledger를 사용하며 대체 계약
  집합의 정확한 일치를 검증한다. migration에 없던 curated feature index의
  `NULLS NOT DISTINCT` metadata 옵션은 제거해 일반 Alembic 비교로 복귀시켰다.
- 같은 전문 리뷰어의 재검토 승인을 받았고 변경 대상 통합 테스트 13개, unit 1,503개,
  ruff, mypy strict, import-linter를 통과했다. 전체 integration 재실행은 Docker Desktop의
  containerd metadata filesystem read-only 장애로 중단했으므로 원격 CI에서 재검증한다.
- **다음 한 작업**: 후속 PR을 `integration/t-vn`에만 열어 CI green 뒤 머지하고, Agent A
  PR #754의 갱신 head를 같은 전문 리뷰어로 재검토해 보안 finding을 보완한다.

## 2026-07-19 (claude, agent A1) — T-VN-19 Alembic metadata 정합 CI gate 구현

- `feat/t-vn-19-alembic-check`(base `integration/t-vn`)에서 빈 PostGIS DB의 `alembic
  upgrade head && alembic check` diff 0건 gate를 구현했다(ADR-075 D-12-2, §8.1). env.py
  `include_object`로 PostGIS·미모델 app table 8개·round-trip 불가 index 4개를 이름으로 명시
  제외하고, models.py를 배포 DB에 정합화(String→Text 27컬럼, dagster claim 누락 컬럼/CHECK/
  기본값, source_records·curated_themes 제약명 정정, import_jobs SERIAL 위양성 제거).
  `tests/integration/test_alembic_metadata_consistency.py`가 기존 integration CI에서 상시
  실행하고, 제외 index 4개의 구조 의미는 test_alembic_upgrade.py가 catalog로 단언한다.
  **마이그레이션 없음**(scope guard 준수) — 배포 DB 자체 drift는 발견되지 않았다.
- **다음 한 작업**: 적대적 리뷰(오케스트레이터) → full gates → PR·CI green·머지. 비차단
  후속 관찰(별도 migration task 후보): DB의 varchar/text 혼재 정규화, curated_themes·
  source_records 제약의 naming-convention rename.

## 2026-07-19 (claude, agent A2) — T-VN-17 weather 무결성 제약 완료

- alembic 0060으로 ``feature_weather_values``에 semantic UNIQUE(CONCURRENTLY,
  NULLS NOT DISTINCT) + range/payload CHECK + source FK(NOT VALID→VALIDATE)를
  price 패턴 미러링으로 도입하고, dedup-first + writer ON CONFLICT cutover를 같은
  PR에 담았다(F-7/ADR-072/075). ~30M행 rewrite/STORED 없음. 브랜치
  ``feat/t-vn-17-weather-integrity``.
- 게이트: ruff/mypy(main)/lint-imports green, 신규 통합 테스트(제약 7 + migration
  dedup·왕복 1) + 기존 weather/orchestration 회귀 green, fresh-DB alembic upgrade
  head green. #752가 실수 커밋한 uv.lock 제거.
- **다음 한 작업**: 이 브랜치 orchestrator 리뷰·PR·머지 후 다음 T-VN 배정 task.
  (dagster 통합 테스트는 이 venv에 dagster 미설치라 미실행 — 환경 한계.)
- **후속 정정(#766)**: dedup 뒤 concurrent build 사이 writer race가 확인돼 T-VN-17R에서
  transactional writer-lock cutover로 교체한다. 이 항목의 `CONCURRENTLY` 설명은 당시 구현 이력이다.

## 2026-07-19 (codex) — Agent A T-VN-07 소비자 clean-cut 리뷰 보완

- PR #748의 단일 전문 리뷰에서 삭제된 beach no-op query가 이 저장소의 구현 사양과
  PinVi primary consumer에 남은 S2를 확인했다. `public-views-api` 표를 실제 계약과
  맞추고 PinVi route/client/vendored OpenAPI 후속을 병행한다.
- 같은 리뷰어가 양 저장소 최종 diff를 승인했고, 문서 diff/redaction 및 PinVi 관련
  Python 31개·정적 gate가 통과했다.
- **다음 한 작업**: 문서 PR을 `integration/t-vn`에만 머지하고 PinVi 소비자 PR도 CI
  green으로 머지한다.

## 2026-07-19 (codex) — Agent A T-VN-02 심층 리뷰 보완

- PR #747의 단일 전문 리뷰에서 Prometheus token을 추적 config에 inline하게 하는
  배포 안내(S2)와 비ASCII token의 header/env 인코딩 불일치(S3)를 확인했다.
  `credentials_file` + repository 밖 read-only secret mount를 선행 조건으로 문서를
  고치고, metrics token 설정을 RFC 6750 `b64token` ASCII로 제한했다.
- 같은 리뷰어가 기존 S2/S3 해소를 확인했고, 남은 import 순서 1건은 사용자 지침의
  기계적 변경으로 정리했다. 관련 API unit 87건과 Ruff가 통과했다.

## 2026-07-19 (claude, agent A2) — T-VN-05 공개 raw payload 경계 제거 완료

- 공개 detail/batch에서 raw observation lineage(observations)와 provider raw
  passthrough(detail.payload, MOIS 포함)를 제거하고, raw lineage를 operator 표면
  (신규 `GET /features/{id}/sources` + operator-gated observation history)으로
  이동했다. route_policy 재분류(history PUBLIC_KEYED→OPERATOR, /sources OPERATOR
  신규), user OpenAPI subset에서 제외. service batch는 extra=forbid + typed-only로
  raw opt-in 불가. 브랜치 `feat/t-vn-05-raw-payload`(base `integration/t-vn`).
- 게이트: ruff/mypy(main+api)/lint-imports green, API 657 passed(신규 MOIS strip·
  operator auth 403·404 테스트 포함), OpenAPI drift clean, admin/user types 재생성·
  type-check green, redaction clean.
- **다음 한 작업**: 이 브랜치 orchestrator 리뷰·PR·머지 후 다음 T-VN 배정 task.

## 2026-07-19 (codex) — Agent A T-VN-06 심층 리뷰 보완

- PR #746의 단일 전문 리뷰에서 #745 이후 alias-aware notice 필터 충돌(S1)을 확인해
  공유 helper에 방어 cast를 이식했다. 동시 head 갱신도 같은 리뷰어가 재검토해 문서 정본
  회귀(S2)와 curated 단건·collection count 테스트 공백(S3)을 추가로 확인하고 보완했다.
- **다음 한 작업**: 같은 리뷰어의 최종 승인 후 전체 CI를 통과시키고 PR #746을
  `integration/t-vn`에만 머지한다. 이후 최근 Agent A PR을 다시 검색한다.

## 2026-07-19 (claude, agent A1) — T-VN-07 no-op 옵션 삭제 + actor principal 1차 구현

- `feat/t-vn-07-noop-actor`(base `integration/t-vn@0e0f7fe2`)에서 (1) 무동작 beach
  `include_quality`/`include_forecast` query 옵션을 route/OpenAPI(admin·user)/생성 TS
  타입에서 제거하고(응답 필드는 모델 기본값으로 유지 — D-9-6), (2) auth-event 감사 actor를
  `body.actor or context.actor` → 인증 principal `context.actor`로 좁혔다(D-2·F-4). 옛
  caller no 500, body-actor 위조 차단. openapi/TS drift 0, 게이트 green.
- **다음 한 작업**: 이 브랜치 적대적 리뷰(오케스트레이터) → full gates → PR·CI green·
  `integration/t-vn` 머지. body-actor 필드 전면 제거·`actor` schema 제거는 T-VN-20이
  admin feature/curated/issue/offline/dedup/enrichment와 함께 이어받는다.

## 2026-07-19 (claude, agent A1) — T-VN-02 route policy matrix + /metrics 경계 구현

- `feat/t-vn-02-route-policy`(base `integration/t-vn`, #743·#744 rebase 반영)에 ADR-066
  결정 1의 route policy matrix를 구현했다: `kortravelmap.api.route_policy`의 명시적
  registry가 전 HTTP/WS route를 6개 정책으로 분류하고, 미분류 route는 `create_app`
  구성 검사와 CI가 함께 실패한다. 배선≠정책 gap은 소유 task를 명시한
  `KNOWN_WIRING_EXCEPTIONS` ledger(현재 전부 T-VN-03 소유 — legacy `/v1/curated-*`
  4건, 무의존 `/v1/ops/*` 관측 read 6건)만 허용하며 gap이 닫히면 stale entry가
  실패해 축소를 강제한다. ops-live WS는 #725 ticket 인증을 기록만 하고 재사용.
- ADR-066 결정 4의 `/metrics` scrape identity 경계를 이 task에서 닫았다
  (`KOR_TRAVEL_MAP_API_METRICS_TOKEN` + Bearer 검증, production 필수, compose
  hard-require). **배포 전제**: n150 root `.env`에 metrics token 추가 +
  kor-travel-docker-manager Prometheus scrape_config `authorization`(Bearer) 반영.
- issue #742 합류: ops pair 검증 정본을 settings production matrix로 일원화, entrypoint가
  production+both-empty pair를 migration 전에 동일 문구로 거부, 메시지 lockstep 테스트 추가.
- 리뷰(PASS-WITH-FIXES) 반영 완료: /metrics 배포 문서에 zero-gap 순서 + "docker-manager에
  현재 12701 scrape job 없음(신규 추가 대상)" 정정, production에서 interactive docs UI
  (`/docs`·`/redoc`) off + `debug` 재분류(`/openapi.json`은 유지), metrics 검사 비-ASCII
  헤더 401 fail-closed, ledger GET-only 강제, entrypoint PROFILE `+x` 판정, anti-spoof
  테스트. defer(범위 밖): entrypoint DEBUG_ROUTES_ENABLED 철자 게이트, 기존 auth.py 3곳
  latin-1 TypeError 패턴.
- **다음 한 작업**: 오케스트레이터가 PR을 생성·CI green·`integration/t-vn` 머지한다(본 에이전트는
  PR 생성 안 함). T-VN-03(codex b1)이 ledger의 curated/ops 관측 gap을 닫을 때
  `KNOWN_WIRING_EXCEPTIONS`에서 해당 entry 제거가 강제된다.

## 2026-07-19 (codex) — Agent A T-VN-04 심층 리뷰 보완 완료

- PR #743의 공개 경계를 전문 리뷰어 1명이 재검증해 `admin_only` theme/비공개 overlay,
  복제 장소정보를 가진 비공개 연결 item, 종료·구버전 notice의 우회 노출을 모두 SQL 단계에서
  차단했다. 공개 query parameter 2개와 OpenAPI/생성 타입도 clean-cut 계약으로 동기화했다.
- 승인 뒤 unit/API 70건, PostGIS 15건과 Ruff가 통과했다. 최신 `integration/t-vn` 재배치와 CI
  green 뒤 PR #743을 통합 브랜치에만 머지한다.

## 2026-07-19 (claude, agent A2) — T-VN-06 notice 방어적 cast 완료

- T-VN-04는 #743으로 integration/t-vn에 병합됐다. 이어 T-VN-06:
  ``_ended_notice_hidden_sql``(#745가 curated/curation/collection 공개 표면의
  notice 감산 정본으로 만든 함수)의 valid_end_time 직접 CAST를
  ``pg_input_is_valid`` 가드 CASE로 교체해 오염 row 1건이 전체 공개 read를
  500으로 만들던 F-9를 완화했다(fail-closed 제외, 스키마/migration 0).
  브랜치 ``feat/t-vn-06-notice-cast``(base ``integration/t-vn``).
- 오염 4종 상태 matrix 통합 테스트 + 수정 전 SQL 재현 확인, notice lifecycle/
  public view/perf EXPLAIN 회귀 green. ETL purge·reconcile의 잔여 cast와
  관측(카운터)·typed 재설계는 T-VN-37 소유로 명시.
- **다음 한 작업**: 이 브랜치 전체 게이트·리뷰·PR·머지(오케스트레이터 소관)
  후 다음 T-VN 배정 task를 진행한다.

## 2026-07-19 (claude, agent A2) — T-VN-04 공개 predicate view 단일화 완료

- alembic 0059 `feature.public_features` VIEW로 공개 술어를 단일화하고 모든 공개 read 경로
  (bbox/cluster/search/nearby/in-area/detail/batch/counts/notice/weather anchor/특보 이력/
  public views/curation·curated)를 projection으로 수렴했다. 적대 리뷰 S1(collection item
  연결 feature leak)·S2(특보 이력 base join, admin panel 404 처리, PinVi batch 계약 노트)·S3
  전부 반영. 브랜치 `feat/t-vn-04-public-predicate`(base `integration/t-vn`).
- 소비자 가시 변경: batch 비공개=`missing` 균일화(PinVi false-broken 가능 — resolver T-VN-11,
  `docs/integration-map.md` §3.2), weather/price 카드 404, categories `active_only` 제거,
  특보 응답 `feature_status` 제거. admin 전용 카드 표면은 issue #741로 분리.
- **다음 한 작업**: 이 브랜치 PR 생성·CI green·`integration/t-vn` 머지(오케스트레이터 소관)
  후, T-VN Wave 0의 다음 미착수 task를 `docs/tasks.md`에서 골라 진행한다.

## 2026-07-19 (claude) — T-VN-01 production fail-closed 전환 구현·리뷰 반영

- `feat/t-vn-01-fail-closed`에 `KOR_TRAVEL_MAP_API_PROFILE`(production|local-dev)과 production
  기동 거부 matrix를 구현했다: admin proxy secret(앞뒤 공백 없는 32자 이상), ops surface 활성 시
  read/cancel token, features surface 활성 시 `public_api_key_required=true`+service token(앞뒤
  공백 없는 32자 이상), 인증 없는 `/debug` off. local-dev fallback은 non-production 전용으로
  격리하고 auth dependency도 production에서 방어적으로 닫는다.
- Docker image/compose는 기본 production으로 기동하고 compose가 debug off·public key 필수를
  컨테이너 기본으로 주입한다. 적대 리뷰(PASS-WITH-FIXES)의 S2/S3 — service token 필수화·
  compose hard-require·root/package env 문서화·hermetic 테스트 — 를 반영했다.
- **배포 전제**: n150 다음 배포 전 root `.env`에 admin secret·ops token들과 서로 다른 32자 이상
  `KOR_TRAVEL_MAP_API_SERVICE_TOKEN`을 추가해야 compose가 기동한다.
- **다음 한 작업**: orchestrator가 `feat/t-vn-01-fail-closed`를 `integration/t-vn` 대상 PR로 열어
  CI green 후 머지하고, T-VN-02(route policy matrix)·T-VN-03(잔여 read 게이트)과의 통합 순서를
  진행한다.

## 2026-07-19 (codex) — Agent A PR #744 manual link 재활성화 보완

- 단일 전문 리뷰에서 비활성 manual link가 resolver relation으로 복귀하지 못하고 stale
  active manual로 고착되는 S3를 확인했다. direct upsert와 resolver snapshot SQL을 분리해
  활성 manual만 보존하고, 비활성 row는 resolver가 재분류할 수 있게 수정했다.
- 같은 리뷰어가 수정본을 승인했고, 관련 unit/PostGIS 테스트 30개, Ruff, strict mypy
  115개 소스, import 계약 4개, prod redaction이 통과했다.
- **다음 한 작업**: main 후속 PR을 CI green으로 병합한다.

## 2026-07-19 (claude) — #733~#737 심층 적대 리뷰 후속 수정 (fix/codex-pr-deep-review)

- S2-1 POI target upsert TOCTOU를 lock-first(moved/reject 판정을 `FOR UPDATE` row lock
  아래로) + create 경합 `DO NOTHING`→재판정으로 수정하고 두-세션 blocking 통합 회귀를
  추가했다. S2-2로 ADR-074 ledger 3요소 key와 If-Match 428/412 구분을 복원했다.
- S3 일괄: snapshot sync의 manual link 보존 guard(#699 패턴)+회귀, `E2E_LIVE_WORKERS`
  정수 검증, C7 runner `@c7-causal` 안정 tag grep, OpenAPI OpsToken+OpsScope AND 선언
  +재수출, ADR-066/069/070/071/073/075·performance·integration-map 문서 정합.
- 보류(의존성): #740×#733 ops-pair validation 조정 + production/both-explicit-empty
  entrypoint 테스트는 T-VN-01 profile 개념 병합 후 진행. BLOCKED-sentinel-before-preflight는
  #735 계약 테스트·journal이 의도를 명시해 그대로 둔다.
- **다음 한 작업**: `fix/codex-pr-deep-review` PR 생성·CI green·병합 뒤, T-VN-01 병합
  시점에 보류한 ops-pair validation 조정을 재개한다.

## 2026-07-18 (codex) — T-ADM-C7 n150 실행환경 preflight 보강

- PinVi C6c PR #387은 전체 CI green 뒤 `main@1b833ce`로 병합됐다.
- n150 read-only preflight에서 host는 `python3`만 제공하지만 C7 runner가 `python`을 호출해 시작할 수
  없음을 확인했다. host-side helper를 모두 `python3`로 고정하고 명시적 command preflight를 추가한다.
  Dagster container 내부의 `python` 호출은 container 계약이므로 유지한다.
- root-owned host/origin attestation은 아직 provision 전이고 `BLOCKED.json`·4종 residual은 없다.
  attestation은 민감값을 tracked 파일이나 로그에 남기지 않는 local-only atomic 절차로 배포 직전에
  만든 뒤 runner가 machine/origin hash와 권한을 자체 검증한다.
- 단일 적대적 리뷰의 정적 회귀 P2를 반영해 host `python3` 6곳, container `python` 1곳과 preflight
  순서를 exact 고정했고 재승인을 받았다. `bash -n`, Ruff, targeted pytest `16 passed`가 통과했다.
- **다음 한 작업**: 이 runner 보정을 단일 적대적 리뷰한 뒤 정적 계약 테스트·CI·병합하고, Manager
  C6c merge 후 n150 compatible-pair 배포와 prod live E2E를 실행한다.

## 2026-07-18 (codex) — PR #732 vNext 재설계 정본 전개 (PR #736)

- PR #732의 재설계 보고서 D-1~D-12를 실제 다음 번호 ADR-066~075로 전개하고 기존
  ADR-005·009 supersede, ADR-060·062·063 확장 관계를 연결했다.
- 목표 PostgreSQL schema, typed REST와 PinVi 조건부 cutover, 직교 상태/lineage/subtype/override/
  weather 모델, 3단 성능 gate, write-fence·PITR/journal rollback을 architecture와 tracked runbook에
  반영했다. 구현 전인 목표와 현재 `main` DDL/OpenAPI를 명시적으로 분리했다.
- `tasks.md`에는 `T-VN-00`을 `T-ADM-C6c` 별칭으로만 두고 Wave 0~3과 독립 hardening을
  PR 1개=task 1개로 모두 열었다. 완료된 문서 전개 task checkbox는 남기지 않았다.
- 정본 전개 PR은 #736(`docs/vnext-review-propagation`)이다. 문서 전용이라 적대적 재리뷰·코드
  테스트는 생략하고 링크/경로/tasks 형식과 `git diff --check`만 검증한다.
- **다음 한 작업**: `T-ADM-C6c` compatible pair smoke를 종결한 뒤 `T-ADM-C7` n150 live E2E를
  완료하고, 이어 `T-VN-01`부터 의존성 없는 task를 agent A/B로 병렬 진행한다.

## 2026-07-18 (codex) — T-ADM-C7 live harness 4차 적대 리뷰 반영·재리뷰 대기

- owned target barrier를 500건 cursor 페이지 두 개, 최대 501건까지 완주하도록 강화했다. 각
  continuation의 형식·비반복·비어 있지 않은 페이지와 external-system scope를 검증하고 전체
  key/UUID/ETag 집합이 journal과 exact 일치해야 create와 dispatch를 허용한다.
- preview는 `matched_scope.provider_datasets`의 KMA exact 한 쌍, effective sync scope와 feature
  count까지 검증한다. 실행/event continuation은 응답 identity tuple의 페이지 내부 total order,
  페이지 간 서로소·경계 순서, UI DOM 전체 행의 동일 tuple·동일 순서를 함께 증명한다.
- standalone POI create의 첫 PUT에 서버 commit 후 client 응답만 끊는 결정적 fault injection을
  연결했다. route가 보관한 causal receipt와 exact GET의 body/UUID/ETag/version이 모두 맞을 때만
  응답 유실을 복구하며 route handler 정산 뒤 teardown한다.
- **검증 상태**: fresh 적대 리뷰어 2인 승인 전 실행 금지 규율에 따라 Playwright·test·lint·build·
  외부 호출은 수행하지 않았다. 코드·정적 fixture·문서를 수동 점검하고 `git diff --check`만
  수행한다.
- **다음 한 작업**: fresh 리뷰어 2인의 승인과 차단 finding 반영 뒤 로컬 gate를 실행하고, PR CI
  green·머지 후 n150 prod 파괴적 live runner와 완료 이슈 정리를 수행한다.

## 2026-07-18 (codex) — T-ADM-C7 live harness 3차 적대 리뷰 반영·재리뷰 대기

- 최종 n150 runner에 C7C POI create/update/delete same-socket causal spec와 별도 durable 복구 journal을
  연결했다. PUT intent를 응답 전에 기록하고 UUID/strong ETag/version을 응답 뒤 보강하며, exact GET
  ETag `If-Match` cleanup과 RFC7807 404·external-system 빈 집합을 최종 read-only 단계에서 재검증한다.
- KMA helper도 target intent/identity를 누적 journal에 보존하고, request 전 owned external-system의
  전체 key/UUID/ETag 집합과 실행/event continuation tuple·cursor를 exact 검증한다. `412`나 version
  drift는 다른 쓰기를 지울 수 있으므로 cleanup 재시도 없이 차단한다.
- fixed root-owned host attestation으로 machine-id/hostname/origin을 anchor하고 로그인 POST
  `200 + Set-Cookie`, UI container admin password hash non-empty, route handler settlement를 preflight/
  teardown 계약에 포함했다.
- 같은 자연키 재생성은 새 UUID/ETag/version을 active 소유 객체로 교체하고 과거 객체를 별도 history로
  보존한다. PUT 응답 유실은 exact 재탐색→동일 PUT 1회 재생→조건부 cleanup 순서로 수습하며, identity
  증명이 불가능하면 다른 target을 삭제하지 않고 `restored=false`로 차단한다.
- preview·terminal의 전체 provider scope를 KMA-only로 고정하고 fingerprint/base datetime 형식을
  검증한다. 상태 journal은 temp/final/parent fsync를 포함하며 runner state·lock·BLOCKED는 root-owned
  고정 경로만 사용하고 `XDG_STATE_HOME` override를 거부한다.
- 이전 journal의 restored residue는 현재 scenario state를 합치기 전에 이전 payload만으로 판정하며,
  current key/status를 과거 snapshot으로 덮어쓰지 않는다. KMA dispatch 직전에도 active target 전체
  집합을 재확인하고, recreate current/history UUID의 상호 배타성과 필수 history를 최종 runner에서
  검증한다.
- lock은 no-follow safe open과 regular/root/`0600` fstat 뒤 guard process가 보유한다. standalone POI
  PUT 응답 유실은 exact body 재탐색과 404 single replay만 허용하고 causal receipt가 없거나 identity가
  불확실하면 BLOCKED한다. cursor base datetime도 canonical 필수값으로 강화했다.
- **검증 상태**: 사용자 규율에 따라 두 fresh reviewer 승인 전 Playwright·test·lint·build를 실행하지
  않았다. 코드·정적 fixture·문서 수정 후 `git diff --check`만 수행하고 재리뷰를 기다린다.
- **다음 한 작업**: fresh 적대 리뷰어 2명의 차단 finding을 모두 해소한 뒤 승인된 diff에만 로컬 gate를
  실행하고, PR CI green·머지 후 n150 prod 파괴적 live runner와 완료 이슈 정리를 수행한다.

## 2026-07-18 (codex) — T-ADM-C7C 로컬 종결·PR 준비

- POI target PUT/DELETE transaction 안에서 `dataset_projection` revision을 읽어 mutation 응답의
  필수 causal receipt로 반환하고, Alembic 0058의 server-owned UUID+BIGINT version ETag를
  단건·목록 body와 GET/PUT/DELETE header에 연결했다.
- repository soft-delete는 active natural key `FOR UPDATE` 뒤 UUID+version을 검증하고, no-row를
  READ COMMITTED 새 statement에서 한 번 재확인해 concurrent recreate `412`와 실제 부재 `404`를
  구분한다. executor link sync는 모든 active parent를 UUID 순서로 먼저 `FOR KEY SHARE` 잠근 뒤
  link를 교체해 delete와 parent→link 순서로 직렬화한다.
- DELETE는 `If-Match` 누락/형식 오류/UUID·version 불일치/active 부재를 RFC7807
  `428`/`422`/`412`/`404`로 구분한다. admin UI는 row의 `entity_tag`를 exact `If-Match`로 보내고 BFF는
  요청 `If-Match`와 응답 `ETag`를 allowlist로 보존한다.
- 실제 2-session PUT/delete-recreate/link race와 strict ETag, migration 불변, 같은 기존 socket의
  `update.data.live_revision >= receipt` live E2E 검증 코드를 준비했다. snapshot과 top-level
  fingerprint revision은 causal 증거에서 제외한다.
- admin OpenAPI와 생성 TypeScript 타입을 갱신했고 user OpenAPI hash는 불변이다.
- create/update/delete 각각 같은 기존 socket의 새 frame 구간에서 causal receipt를 검증하고, UI는
  `412` 때 list/nearby/dataset/pipeline을 refetch해 UUID로 선택한 최신 row의 tag를 재사용한다.
- 두 독립 적대 리뷰어가 최종 diff를 승인했다. root unit 1,435건, API 520건, 실제 PostgreSQL
  migration/up-down·경쟁 8건, frontend unit 212건, mocked POI E2E 10건, Ruff, strict mypy
  115+52파일, import 계약 4/4, OpenAPI/생성 타입 drift, type-check·lint와 31-route build가 green이다.
- PR #733 merge commit `a5af45f2` 위에 rebase해 admin/user OpenAPI와 생성 타입을 다시 만들었고,
  `T-ADM-C7C`를 완료 이력으로 옮겼다.
- **다음 한 작업**: 보안 감사 뒤 C7C PR을 게시하고 CI green·승인으로 병합한다. 직후 C7 live
  branch를 rebase해 n150 same-socket causal E2E를 수행한다.

## 2026-07-18 (codex) — T-ADM-C7C causal receipt·조건부 삭제 문서 선행

- C7 live E2E 적대 리뷰에서 mutation 이후 임의 global revision 증가를 causal invalidation으로
  오인하고, GET 소유권 확인과 DELETE 사이 target 재생성 경쟁에서 새 UUID를 삭제할 수 있는 두
  차단 결함을 확인했다.
- 문서 선행 당시 UUID만 ETag version으로 쓰고 schema가 불필요하다고 판단했으나 적대 리뷰에서 같은
  UUID의 concurrent PUT과 link reactivation 경쟁을 놓친 것으로 확인했다. ADR-065의 최종 결정은
  Alembic 0058 BIGINT version/trigger와 parent lock protocol로 교체됐다.
- **다음 한 작업**: T-ADM-C7C를 독립 PR로 구현·2인 적대 리뷰·로컬 gate·CI merge한 뒤 C7 live
  branch를 rebase해 같은 기존 socket의 `update.data.live_revision >= receipt`와 조건부 cleanup을
  증명한다.

## 2026-07-18 (codex, agent B) — T-ADM-C6c map principal 적대 리뷰 반영

- map API에 API-only read/cancel token을 추가했다. read는 canonical datasets/pipeline
  `GET`, cancel은 exact import-job cancel POST 한 곳에만 결박했다. trusted frontend
  BFF는 기존 actor와 전체 operator mutation 권한을 유지하며 service 요청은 서버 고정
  `service:pinvi`를 사용한다.
- typed `401/403/422`, constant-time token 비교, actor 위조 차단, `/v1/admin/*` 권한 격리,
  operation별 OpenAPI AdminBFF/OpsToken 계약과 API-only secret 전달 경계를 테스트 코드로 고정했다.
  production required gate, fixed actor, 전체 whitespace와 admin/service secret 재사용 거부,
  Dagster entrypoint 격리를 적대 리뷰 지적에 따라 보강했다.
- 독립 적대 리뷰 2건을 반영한 최종 diff에서 root unit 1,463건과 API 563건, targeted C6c
  306건, ruff, strict mypy 190파일, import 계약 4/4, admin/user OpenAPI·admin generated type
  drift, frontend type-check·unit 210건·lint(오류 0, 기존 경고 6)·production build가 통과했다.
- PR #733의 Python 3.11~3.13에서 framework별 `route.path` prefix 차이로 exact cancel이 403이
  되는 회귀를 ASGI full path 결박으로 제거했다. update-request·suffix·trailing path는 계속
  fail-closed하고, 별도 적대 리뷰 2인 승인과 집중 API 217건·API 전체 563건을 확인했다.
- 재실행 integration의 구 `403` 기대 1건은 새 `401 OPS_TOKEN_REQUIRED` 계약과 code까지 단언하도록
  시험만 교정했고, 해당 실제 PostgreSQL projection test가 통과했다.
- **다음 한 작업**: PinVi caller와 docker-manager compatible-pair 배포 PR을 병합하고 같은 commit
  조합으로 cross-repo smoke를 수행한다. `T-ADM-C6c`는 그 smoke 전까지 열린 task다.

## 2026-07-18 (codex) — PR #708 정본 최신 코드 2차 재검증 (#730 병합)

- KTM `origin/main@13eb8d40`과 PinVi `origin/main@48085afb`를 기준으로 PR #708 정본을
  #691·#721~#729의 실제 route, migration 0054~0057, actor·인증·멱등 구현과 다시 대조했다.
  feature-update/schedule 도메인 ledger, ops-live ticket, refresh-policy CAS, exact-scope 이력은
  이미 구현된 기준선으로 판정을 좁혔다.
- PR #724가 삭제한 `/v1/ops/dagster/summary`, `/v1/ops/providers*`,
  `/v1/ops/import-jobs*`를 PinVi 최신 main의 admin client·proxy·test가 여전히 호출하고 있음을
  확인했다. 새 canonical ops는 frontend BFF admin gate이므로 경로만 바꿔도 PinVi server는
  인증되지 않는다.
- 재설계 보고서·integration map·tasks를 같은 결론으로 보강했다. 삭제 route나 alias를
  되살리지 않고 PinVi caller와 contract test를 canonical datasets/pipeline으로 옮기며,
  BFF secret 공유가 아닌 최소 service/operator principal을 설치한다.
- 문서 보강은 PR #730의 CI 8개 게이트 통과 후 merge commit `d0609226`으로 `main`에
  반영됐다. 이 항목은 #730 문서 마감 기록이며 C6c 구현 완료를 뜻하지 않는다.
- **다음 한 작업**: `T-ADM-C6c` cross-repo 계약 복구를 양 저장소에서 완료한다. 해당 commit
  조합의 인증·응답 smoke 전에는 `T-ADM-C7` n150 배포와 live E2E를 시작하지 않는다.

## 2026-07-18 (codex, agent B) — T-ADM-C7B-UI 로컬 종결·PR 준비

- datasets UI는 exact tuple을 기준으로 활성 실행과 최근 종료 실행, run/event continuation과
  canonical history URL을 소비한다. 잘못된 deep link와 mutation 불가능 scope는 fail-closed하며
  scope 전환 중 로컬 정책 draft와 CAS 저장 기준을 보존한다.
- pipeline filter는 provider→dataset→scope prerequisite를 강제한다. 상위 축 변경과 불완전 tuple,
  URL Back/Forward에서 stale scope와 cursor를 원자적으로 제거하고 dataset-wide 요청에는
  명시적 scope를 보내지 않는다.
- 독립 적대 리뷰 2인이 P0~P3 잔여 0건으로 승인했다. Vitest 26 files·210 tests, 앱·E2E
  type-check, lint 오류 0건, `git diff --check`와 31-route production build가 green이다.
  Playwright는 최종 n150 live gate에 남겼다.
- **다음 한 작업**: 최신 main rebase와 보안 감사 뒤 C7B-UI PR을 CI green·승인으로 병합한다.
  직후 `T-ADM-C7` n150 prod 파괴적 live E2E를 수행하고 남은 #684/#694/#712/#719를
  증거와 함께 종결한다. 완료된 #682/#686/#718/#720은 2026-07-18 닫았다.

## 2026-07-18 (codex, agent A) — T-ADM-C7B-API 로컬 종결·PR 준비

- Alembic 0057로 `ops.import_job_events.sync_scope`를 추가하고 visible legacy event pair를
  immutable owning job identity로 복구했다. canonical direct update event만 scope를
  backfill하며 trigger·check constraint가 이후 owner pair/scope drift를 막는다.
- exact-scope event는 `(provider,dataset_key,sync_scope,occurred_at DESC,event_id DESC)` partial
  B-tree에서 cursor/LIMIT 전에 제한한다. dataset key는 provider namespace에 속하므로 provider 없는
  dataset-only event filter를 REST와 repository에서 거부하고 dead
  `idx_import_job_events_dataset_time`을 제거했다. downgrade는 0052의 columns/order/partial
  predicate로 단독 index를 정확히 복원한다.
- datasets grid/detail은 같은 snapshot에서 scope별 `active_execution`과 마지막 terminal
  `latest_execution`을 독립 보존한다. run/event history는 `{items,next_cursor,canonical_url}`이고,
  cursor는 전체 filter fingerprint에 묶여 다른 filter 재사용과 non-canonical scope를 DB 전에
  typed `422`로 닫는다.
- DB/API 적대 리뷰어 2인이 최종 변경을 P0/P1/P2/P3 잔여 0건으로 승인했다. 실제 PostgreSQL
  migration/schema·EXPLAIN·repository 순차 gate 81건, root unit/lint 1,430건, API 504건과
  frontend unit 210건을 통과했다. Ruff, strict mypy 167개 소스, frontend type-check·lint,
  admin/user OpenAPI·생성 타입 drift도 모두 green이다.
- **다음 한 작업**: 보안 감사·최신 main rebase 뒤 C7B-API PR을 CI green과 승인으로 병합한다.
  직후 C7B-UI를 최신 main에 rebase해 exact-scope 조작·이력 소비를 완결하며 #712/#719는 최종
  C7 n150 live 증거 뒤 닫는다.

## 2026-07-18 (codex, agent A) — T-ADM-AUD-686 로컬 종결·PR 준비 완료

- direct runner뿐 아니라 정규 Dagster KMA grid asset 3종도 target mapping/dedupe/cap/empty와
  cursor skip 뒤에 public client를 동기 생성하도록 resource를 lazy factory로 바꿨다. credential
  부재·constructor sentinel materialization과 cancellation/close 이중 실패 계약을 보강했다.
- `kma.target_scope_empty` terminal event는 canonical 전이와 같은 transaction에서 한 번만
  기록한다. active duplicate loser, terminal replay, event writer fault rollback, generic KMA·
  grid-limit·다른 provider의 오분류 0건을 회귀 계약으로 고정했다.
- dataset 최근 event는 canonical job/request JOIN의 effective scope를 ORDER/LIMIT 전에 제한하고,
  DTO scope·다음 cursor·history URL과 pipeline events exact filter를 API/UI/OpenAPI/generated
  type에 연결했다. migration은 만들지 않았고 후속 C7B-API 0057 전 join-derived 경계를 문서화했다.
- 두 독립 적대 리뷰어가 제품 SHA `c07259fb`를 S1/S2/S3 0건으로 승인했다. 이후 테스트 import
  격리와 generated type 설명만 기계적으로 동기화한 최종 SHA에서 root unit 1,413건, API 485건,
  Dagster 475건(1 skip), 실제 PostGIS 집중 6건, frontend unit 185건을 통과했다. Ruff,
  strict mypy 115+52+23파일, import 계약 4/4, OpenAPI admin/user·generated type drift,
  frontend type-check·lint(오류 0, 기존 경고 6), 31-route production build도 green이다.
- **다음 한 작업**: 보안 감사 결과와 `Refs #686`을 포함한 PR을 게시해 CI green·승인 후
  병합한다. 이슈 #686은 최종 C7 n150 live 증거를 첨부할 때까지 닫지 않는다.

## 2026-07-18 (codex, agent A) — T-ADM-AUD-718 로컬 종결·PR 준비 완료

- C7A 병합 정본과 Alembic 0055 위에 0056 `provider_refresh_policies.revision` 양수 BIGINT를
  추가했다. create-only는 `expected_revision=null`, update-only는 조회한 revision 일치 시에만
  원자적 `+1`하고, 불일치는 현재 record/revision을 담은 typed `409`로 반환한다.
- HTTP의 BIGINT revision은 JavaScript 정밀도 손실을 피하도록 정규화된 10진 문자열로 고정했다.
  admin UI는 초안 기준 revision과 최신 관측 revision을 분리해 background refetch/충돌에도 입력을
  보존하며, 명시적 3-way 조정 뒤 최신 revision으로 재저장한다.
- 실제 row-lock 경합, BIGINT 소진, `source_kind` 불변, non-problem OpenAPI ref 오인, 탭 상태
  수명·저장 guard·popstate focus와 지연 cache 응답 세대 지적을 반영했다. DB/API와 frontend
  적대 리뷰어는 최종 제품 SHA `b7b600447368d8ed79bc1a8b56772af881104bf3`을 S1/S2/S3 0건으로
  승인했다.
- root unit 1,411건, API 489건, 실제 PostGIS migration/schema 14건·CAS 저장소/API 23건·집중
  10건과 row-lock 경쟁 3회, Ruff, strict mypy 115+52파일, import 계약 4/4가 통과했다. 같은
  SHA의 frontend Vitest 212건, type-check, lint 오류 0건, OpenAPI/admin type drift와 31-route
  production build도 통과했다. local Playwright는 실행하지 않았고 최종 C7 n150 gate에 남겼다.
- **다음 한 작업**: 완료 문서와 보안 감사를 포함한 PR을 올려 CI green·승인 후 병합한다.
  issue #718은 닫지 않고 최종 n150 live 증거를 첨부한 뒤 종결한다.

## 2026-07-17 (codex, agent B) — T-ADM-C7A 로컬 종결·PR 준비 완료

- same-origin ticket BFF, HMAC subprotocol ticket, DB nonce 단일 소비와 60초 lease를 완결했다.
  없음·변조·만료 경계는 각각 `4401`/`4408`로 닫고, malformed·비단조 frame은 오염 socket을
  폐기한 뒤 새 ticket/socket에서 exact 구독을 복원한다.
- Alembic 0055를 `down_revision=0054` 단일 head로 확정했다. provider 상태·정책, schedule
  override·audit·claim resolution, integrity issue·POI cache target의 transaction-coupled revision을
  pipeline/datasets canonical query invalidation에 연결했다.
- backend/DB/security와 frontend 적대 리뷰어 2인이 테스트 전 승인했다. 정확한 제품 SHA
  `c49829f0`에서 root unit 1,411건, API 484건, 실제 PostGIS migration/schema 14건과 C7A 9건,
  frontend unit 185건 및 Ruff, strict mypy, import 계약, OpenAPI/type drift, Compose rendering,
  production build가 모두 통과했다. local Playwright는 실행하지 않았고 최종 n150 gate에 남겼다.
- **다음 한 작업**: 완료 문서를 포함해 보안 감사·최신 main rebase 후 C7A PR을 CI green과
  승인으로 병합한다. 병합 직후 Wave 2의 `T-ADM-AUD-718`/0056과 `T-ADM-AUD-686`을 병렬
  착수한다.

## 2026-07-17 (codex, agent A) — T-ADM-C6b clean-cut 최종 gate·PR #724 병합 완료

- C6A exact commit 위 독립 branch에서 legacy REST operation 28개를 제거했다. 삭제 범위는
  Dagster 9, provider 운영 2, refresh policy 3, import job/event 5, feature update request 6,
  debug ETL 3개다. `/ops/datasets/*`, `/ops/pipeline/*`, `/ops/live`, 관측 read와 public
  provider read 2종은 유지한다.
- public provider read를 운영 결합 로직이 없는 `public_providers.py`로 옮기고 기존 응답 schema
  이름과 cursor 비노출 계약을 보존했다. `etl_live.py`, live adapter tests, API 전용 provider
  credential settings·compose/load-env 주입을 제거했으며 preview catalog는 fixture/none만 가진다.
- migration은 추가하지 않았다. UI 통합 뒤 admin/user OpenAPI와 generated type을 모두
  재생성했고, 삭제된 legacy path가 tracked 계약에 남지 않음을 확인했다.
- 반복 적대 리뷰에서 provider secret 과다 주입, BFF bridge peer 403, raw env inline comment,
  deleted status URL과 문서 drift를 보강했다. API/frontend는 env allowlist, Dagster만 provider
  비밀을 소유하고 bridge는 frontend 고정 `/32`, host는 loopback만 신뢰한다.
- 두 독립 리뷰어가 최종 제품과 테스트 보강을 S1/S2/S3 0건으로 승인했다. root unit 1,410,
  API 450, Dagster 457(1 skip), 실제 PostGIS 92, frontend 142건과 Ruff, strict mypy
  115+51파일, import 4/4, OpenAPI/admin/user type drift, Compose base·host rendering,
  production build를 통과했다. local Playwright는 실행하지 않고 최종 n150 C7 gate에 남겼다.
- 완료 task를 아카이브하고 보안 감사·전체 CI green 뒤 PR #724를 squash merge했다.
## 2026-07-17 (agent B) — T-ADM-C6b UI clean-cut 리뷰 반영 완료

- 구 `/ops/import-jobs*`, `/ops/providers`, `/admin/features/update-requests*`, `/admin/dagster`,
  `/etl` UI와 전용 hook/mock E2E를 redirect 없이 삭제했다. navigation·홈·운영 로그·frontend
  README inventory는 `/ops/pipeline`과 `/ops/datasets` 정본으로 수렴했다.
- 외부 리뷰 B 지적에 따라 홈 Dagster 링크 E2E의 hard-coded 개발 fallback을 제거하고,
  offline validation/load와 POI target upsert/delete의 canonical pipeline/datasets query
  invalidation을 hook+QueryClient spy 단위 계약으로 고정했다. POI mutation도 pipeline
  executions/overview를 직접 무효화한다.
- **다음 한 작업**: backend/API branch와 결합해 OpenAPI/admin type을 재생성하고 최종 통합
  SHA를 적대 리뷰어 2명에게 전달한다. 승인 전에는 테스트를 실행하지 않는다.

## 2026-07-17 (codex, agent B) — T-ADM-C7B-720 리뷰·gate·PR #723 병합 완료

- `/ops/datasets`의 `이슈 있음` 필터·정렬·행 badge를 dataset/provider open issue 합계로
  통일했다. 요약은 dataset과 provider 귀속 단위를 별도 중복 제거해 같은 dataset의 scope
  반복 행이 집계를 부풀리지 않는다.
- provider-only, dataset-only, both, neither를 unit과 mocked E2E 계약으로 고정했다. 두
  적대 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했고 unit 5건, type-check, lint와 production
  build를 통과했다.
- 보안 감사와 전체 CI green 뒤 PR #723을 squash merge했다. mocked/live Playwright 실행과
  issue #720 종결은 최종 C7 n150 증거 뒤 수행한다.

## 2026-07-17 (codex, agent B) — T-ADM-C6a 리뷰·로컬 gate 완료

- C5 exact base 위 독립 branch에서 import job/update request/load batch/provider 엔티티 링크와
  홈·Feature·큐레이션·로그·구 갱신 요청 전환 링크를 `/ops/pipeline`·`/ops/datasets`로
  재배선했다. provider URL은 호출부의 `dataset_key`를 `dataset`으로 번역하면서
  `sync_scope`를 보존한다.
- ops-live 무효화, legacy import-job HATEOAS, live scenario catalog도 canonical
  pipeline/datasets 계약으로 맞췄다. 변경 전 codegraph 영향은 C5 worktree의 최신 인덱스로
  확인했으며 새 worktree에서는 인덱스를 임의 초기화하지 않았다.
- load batch·parent UUID 조회는 partial index에서 member를 먼저 선택한 뒤 component를
  확장한다. 두 적대 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했고 root unit 18건,
  API 140건, 실제 Postgres 통합 22건, frontend unit 27건과 정적·production build gate가
  통과했다.
- **다음 한 작업**: C6a task를 완료 이력으로 옮긴 문서 commit을 만들고 보안 감사 뒤 PR을
  올려 CI green·승인 후 병합한다. 병합 직후 C6b UI를 최신 C6a에 rebase하고 C6b·C7A·
  C7B-720 병렬 wave를 진행한다.

## 2026-07-17 (codex) — admin 감사 후속 5-PR 병렬 wave 문서화

- C5 최신 commit을 기준으로 열린 감사 후속을 PR 다섯 개로 분리했다. C7B-720은 issue
  #720의 dataset/provider 이슈 filter 의미를 맞추는 frontend-only 작업이고, AUD-718은
  #718의 갱신 정책 BIGINT revision CAS, AUD-686은 #686의 KMA 유효 target 0건
  fail-closed, C7B-API/UI는 #712/#719의 active projection·exact-scope 이력 계약과 UI
  소비를 각각 소유한다.
- 병렬 순서는 C6a 뒤 `C6b + C7A/0055 + C7B-720`, C7A 뒤
  `AUD-718/0056 + AUD-686`, 이어 C7B-API/0057, C7B-UI, C7 n150이다. migration은
  `0055 → 0056 → 0057` 단일 head만 허용하며, 각 소유 branch는 직전 migration이 main에
  병합된 뒤 시작한다. migration 없는 병렬 task도 wave 시작·PR 직전·병합 직후 최신 main에
  rebase한다.
- **다음 한 작업**: C5 PR이 main에 병합될 때까지 이 문서 branch를 push하지 않는다. C5
  병합 뒤 최신 main에 rebase해 문서-only PR을 올리고 별도 적대 재리뷰 없이 병합한 다음,
  C6a 병합 여부를 확인해 Wave 1의 C6b·C7A·C7B-720을 agent A/B에 병렬 배정한다.

## 2026-07-17 (codex, agent B) — T-ADM-C5 pipeline 통합·조작 폐루프 완료

- `/ops/pipeline`에 canonical 작업 상태, root 단위 타임라인, Dagster run, 전역 event,
  schedule 상태·audit·claim 해소, feature update 요청을 통합했다. provider/dataset pair와
  request/projected job 상태를 분리하고 URL·자동 갱신·degraded 처리를 단일 계약으로 맞췄다.
- Alembic 0054는 feature update 멱등 ledger와 schedule command audit/claim/resolution을
  append-only로 저장한다. DB clock lease·advisory lock·hard timeout·mutation guard로 동시성과
  응답 유실을 다루며, mutation 뒤 불확실 결과는 명시적 운영 해소 전까지 재실행을 막는다.
- 의미 있는 제품 변경은 backend/UI 적대 리뷰어 2명이 최종 S1/S2/S3 0건으로 승인했다.
  frontend unit·type·lint·production build, Python unit·정적 분석과 실제 PostGIS schedule
  동시성/append-only 회귀를 통과했다.
- **다음 한 작업**: PR #691을 CI green 뒤 병합하고 #693·#716을 닫은 다음, 준비 완료된
  C6a를 최신 main에 rebase해 구 화면 제거 전 모든 존치 링크를 canonical 두 화면으로 옮긴다.

## 2026-07-17 (codex, agent A) — T-ADM-C4R/C4 구현·로컬 gate 완료

- `/ops/datasets`를 provider×dataset×`sync_scope` 3원 그리드와 상세 drawer로 통합했다.
  정책 편집·fixture preview·지금 갱신·scope별 최근 실행을 한 화면에서 조작하며, canonical
  mutable capability와 stale/orphan scope는 fail-closed한다. dataset-wide 기본 state는
  unscoped 실행 이력을 사용하고 external scope 이력은 exact filter로 격리한다.
- pipeline 목록도 선택 scope를 SQL cursor/LIMIT 전에 거르며 datasets detail의 history 링크가
  같은 scope를 보존한다. active operation은 POST 전 선제 재사용하고 200 재사용·409 충돌·terminal
  해제를 같은 인라인 상태로 표시한다. URL 선택은 native History API를 사용해 back/forward와
  focused grid DOM을 보존하며 X/Escape·대상 행 소실 시 초점 복귀를 보장한다.
- API/UI 적대 리뷰 2인이 반복 검토했고 최종 S1/S2/S3는 모두 0건이다. unit 1,398건, API
  534건, 관련 실제 DB 통합 28건, Ruff, strict mypy(main 115/API 55), import 계약 4/4,
  OpenAPI/admin/user type drift, frontend type-check·lint(기존 warning 2)·Vitest 96건,
  production build와 mocked Playwright 47건을 통과했다.
- **다음 한 작업**: PR #698을 최신 main에 rebase하고 보안 감사·CI·승인 뒤 병합한다. 병행
  중인 C5는 2차 적대 리뷰 지적을 수정하고, C7A는 C4/C5 query-key 결선 전 독립 인증/transport
  범위를 유지한다. #684/#686/#712는 C7 n150 live 증거 뒤 닫는다.

## 2026-07-16 (codex, agent A) — T-ADM-C45X-B 구현·로컬 gate 완료

- Alembic 0053으로 direct feature update job의 canonical `sync_scope`와
  `dispatch_requested_at`을 typed 열로 승격했다. active identity는
  `(provider, dataset_key, sync_scope)` partial unique index로 고정하며, 같은 계획은 동일
  request/job을 200 재사용하고 run-now는 새 행 없이 기존 job의 dispatch marker만 멱등 기록한다.
- KMA grid 3종은 typed `target_grids` 또는 exact `external_system:*` 없이는 실행하지 않는다.
  active target subset·membership fingerprint·grid cap을 provider I/O 전에 검증하고, 실패 상태는
  rollback 뒤 scope namespace에 별도 영속한다. datasets grid/detail도 3원 scope별 latest/recent,
  first-run `never_run`, stale/orphan을 구분한다.
- 두 적대 리뷰어가 run-now cancellation 경합, typed scope legacy fallback, Unicode whitespace DB
  drift를 발견해 모두 보강했다. 동시 생성은 전용 0053 DB의 두 AsyncSession barrier로 unique
  collision/retry를 결정적으로 검증한다. 최종 C45X-B 판정은 S1/S2/S3 0건이다. C4R UI의
  `scope_refresh`/재사용 링크와 C7 destructive external scope/fingerprint/cap 증거는
  `docs/tasks.md`의 후속 수용조건으로 고정했다.
- API 530건, Dagster 444건(1 skip), root unit 1,396건, C45X 관련 PostGIS/migration 재검증,
  Ruff, strict mypy(main 115/API 55/Dagster 23), import 계약 4/4, OpenAPI drift, frontend type/lint,
  Vitest 82건, production build, C45X mocked Playwright 27건을 통과했다. raw integration의 live
  5건은 외부 kor-travel-geo `/v2/reverse` HTTP 400이고, 전체 legacy mocked suite는 C4R/C6에서
  교체될 기존 selector 기대가 red라 C45X green과 분리했다.
- **다음 한 작업**: PR #701을 최신 main에 rebase하고 보안 감사·CI·승인 뒤 병합한다. 이후
  Claude Code의 PR #698(C4R/C45X-U)을 적대 리뷰·보강해 #684/#686을 닫고 C4/C5로 진행한다.

## 2026-07-16 (codex) — T-ADM-C3e-I2 n150 운영 종결

- n150 prod를 maintenance drain한 뒤 백업하고 0051/0052를 일방향 적용했다. Alembic은
  `0052_pipeline_projection_access` 단일 head이며 0048 재수렴 변경 0, 예상 밖 exact untyped 0,
  request identity/validation/duplicate/quarantine 불일치 0이다. 최종 DB canonical feature 작업과
  Dagster active run도 모두 0이다.
- tracking sensor 8개와 update queue/failure sensor 2개는 모두 RUNNING이다. reconciliation cursor는
  maintenance anchor `storage_id=5160`에서 `5175`로 전진했고 최근 5개 tick이 observation error 없이
  끝났다. schedule은 배포 전과 같은 34 RUNNING·3 STOPPED로 복원했다.
- 실제 일정·수동·갱신·standalone import 네 실행이 datasets/pipeline 상세에서 같은 canonical
  `(kind,id)` root를 반환했다. prod Playwright 6개 묶음은 138건 통과·전제 미충족 2건 skip이며,
  로그인·오답 인증·파괴적 update/offline upload와 복원까지 확인했다. 전체 증거를 이슈 #679에
  남기고 완료로 닫았으며 #680도 CLOSED 상태를 재확인했다.
- **다음 한 작업**: Claude Code worktree/PR #701(C45X)을 0052 typed identity·scope 정본에 맞춰
  적대적 리뷰하고 DB/API/UI를 보강한다. 이어 #698(C4R)과 #712를 같은 방식으로 개선한 뒤 기존
  C4/C5 작업으로 진행한다.

## 2026-07-16 (codex) — T-ADM-C3e-I1 로컬 gate 완료

- 실제 migration 0001→0052가 적용된 PostGIS에서 B2 public wrapper와 B3 terminal record의
  lifecycle을 통합 테스트 2건으로 연결했다. 단일 provider 성공과 MCST 13-pair 부분 실패 모두
  root/member identity·상태·engine 시각·redacted event 불변식을 보존하며 production 변경은 없다.
- 두 적대 리뷰어의 최종 판정은 각각 S1/S2/S3 0건이다. focused 32건, live 제외 전체
  1,902건(5 deselected), Ruff, strict mypy 136개 소스, import 계약 4/4를 통과했다. raw 전체의
  live 5건은 외부 `kor-travel-geo` reverse HTTP 400으로 실패해 로컬 green과 분리했다.
- **다음 한 작업**: I1 PR을 CI green·승인 뒤 병합하고 `T-ADM-C3e-I2`에서 n150 maintenance
  migration, sensor/cursor readback, 일정/수동/갱신/import 4종 동일-root 증거와 이슈 #679 종결을
  완료한다. C45X/C4R 적대 리뷰와 후속 작업은 그 다음이며 아직 완료하지 않았다.

## 2026-07-16 (agent A) — T-ADM-C3e-B2 로컬 gate 완료

- 모든 live provider resource와 public asset/KMA wrapper가 B1 registry를 기준으로 실제 Dagster
  run record의 job·selection·config·identity/version·trigger를 provider I/O 전에 검증한다.
  resource 초기화와 wrapper의 마지막 ensure가 취소 marker·terminal·runtime drift를 멱등하게
  fail-closed한다.
- wrapper는 자기 exact pair 완료만 소유하고 MCST는 nullable async callback으로 부분 성공을
  보존한다. direct `FeatureUpdateAssetRunner`는 tracking 0이다. 비기본 KNPS point/geometry
  설정은 fetcher와 asset resource가 동일한 `model_copy` snapshot을 사용한다.
- 적대 리뷰어 2명의 최종 판정은 각각 S1/S2/S3 0건이다. focused 260건(1 skip), 실제 PostGIS
  canonical operation 30건, Dagster 전체 428건(1 skip), main unit 1,366건, Ruff, strict mypy
  136개 소스와 import 계약 4/4를 통과했다.
- **다음 한 작업**: B2 PR을 CI green·승인 뒤 병합하고 C3e-I에서 B2→B3 실제 terminal DB 연쇄,
  일정·수동·갱신·import 교차 회귀와 이슈 #679 종결 증거를 확인한다. n150/prod와 C45X/C4R은
  아직 완료하지 않았다.

## 2026-07-16 (agent B) — T-ADM-C3e-B3 로컬 gate 완료

- QUEUED/STARTING/STARTED/CANCELING/SUCCESS/FAILURE/CANCELED를 각각 받는 7개
  `run_status_sensor`와 missed event·NOT_STARTED/MANAGED를 복구하는 periodic sensor를
  기본 RUNNING으로 등록했다. sensor는 provider resource를 열지 않고 DB client만 사용한다.
- Dagster→DB는 public insertion cursor `(storage_id, run_id)`를 사용한다. 페이지를 ID로 먼저
  읽고 300초 settle lag를 만족하는 연속 prefix만 처리해 clock skew가 있는 낮은 ID를 건너뛰지
  않는다. cursor anchor가 삭제·변조됐거나 비어 있지 않은 storage에 초기 cursor가 없으면
  fail-closed한다. scan/list/write 오류는 타입만 기록하고 cursor를 유지한다.
- DB→Dagster active-root keyset은 마지막 page에서 첫 page로 wrap한다. active event는 root/child를
  멱등 ensure하고 terminal event는 pre-resource/direct cancel과 partial success를 원자 reconcile한다.
  trigger·selection 불일치는 active 행을 남기지 않고 같은 transaction에서
  `tracking_invariant`로 닫는다.
- codegraph 영향도와 모든 caller를 확인했고, 적대 리뷰어 2명의 최종 판정은 S1/S2/S3 0건이다.
  focused 101건과 기계적 정리 후 52건, 실제 PostGIS 통합 27건, Dagster 전체 342건(1 skip),
  main unit 1,366건, Ruff, strict mypy 135개 소스, import 계약 4/4를 통과했다. WSL/NTFS pytest
  capture 오류는 실행 0건임을 확인하고 `-s`로 재실행했다.
- **다음 한 작업**: B3 PR을 CI green·승인 뒤 병합하고, B2 병합 후 C3e-I에서 교차 회귀와
  이슈 #679 종결 증거를 확인한다.

## 2026-07-16 (agent B) — T-ADM-C3e-B1 로컬 gate 완료

- 33개 Dagster feature-load job과 asset selection을 canonical exact pair registry로 고정했다.
  MCST는 한 root의 13 pair, KNPS는 launch 시점 settings/run-config/fetcher·asset resource가
  일치하는 runtime singleton, fileData는 job별 고정 singleton이다. possible pair 53개 전체를
  refreshable catalog와 대조하는 회귀를 추가했다.
- registry version과 redacted canonical identity를 job definition에 두고 trigger는 schedule/
  manual/sensor/update/backfill/system launch 신호에서 별도로 판정한다. 등록 identity의 누락·drift는
  fail-closed, 비등록 arbitrary job은 panel-only다. 구 alias/placeholder/pseudo identity와
  feature job의 `schedule_scope=system` tag는 제거했다.
- 적대 리뷰 S1/S2 반영으로 main provider 계층의 canonical manifest digest가 version을 자동
  결정한다. admin schedule 수동 실행은 KNPS와 fileData 4종의 effective config 및 canonical
  manual tag를 GraphQL `runConfigData`/metadata에 영속한다. dataset schedule projection은
  `pipelineName`과 identity job이 같은 validated MCST 13 pair만 같은 상태/next tick으로 펼친다.
  coalescing은 `NOT_STARTED`/`MANAGED`와 exact job/version/identity를 함께 검사한다. KNPS 두
  필드 전용 settings는 공식 env prefix/`.env`를 읽되 unrelated malformed 설정은 검증하지 않는다.
- B1은 manifest compile target과 schedule/admin/projection launch consumer까지만 완결한다.
  실제 provider guard/public wrapper와 비기본 KNPS direct runner의 `settings.model_copy` 수정은
  B2, run-status/reconcile caller는 B3 소유다.
- 적대 리뷰어 2명의 최종 판정은 S1/S2 0건이다. main unit 1,366건, focused 159건,
  API 전체 513건, Dagster 전체 308건(1 skip), Ruff, strict mypy 7개 변경 소스와 import 계약
  4/4를 통과했다. pytest capture의 WSL 임시 파일 오류는 `-s`로 분리했으며 실제 회귀는
  전부 통과했다. 완료 task는 `tasks-done.md`로 옮겼다.
- **다음 한 작업**: C3e-C를 B1 병합 commit 위에 rebase해 CI·merge를 완료하고 B2/B3를
  최신 main에서 병렬 시작한다.

## 2026-07-16 (agent A) — T-ADM-C3e-C 로컬 gate 완료

- 전용 worktree codegraph 동기화 결과는 785 files/19,093 nodes/60,659 edges다. 변경 영향은
  detail route 2개·detail service 5개, preview service 5개, refresh-policy service 10개,
  grid DTO 6개, preview DTO 5개 symbol이며 실제 frontend 호출자는 아직 없고 생성 admin
  OpenAPI type만 확인됐다.
- A2가 완성한 canonical projection은 유지한다. 다만 후속 적대 리뷰가 `/`를 허용하는
  provider/dataset identity와 동적 path segment의 표현 불가능성을 발견해 detail/preview/
  refresh-policy를 고정 path + `provider`/`dataset_key` query 복합키로 원자 전환했다. 구 동적
  route는 호환 shim 없이 삭제하고 grid `detail_url`, preview `dataset_key`, OpenAPI/admin type,
  설정·계약 문서를 함께 갱신했다. 현재 branch에는 실제 C4 frontend caller가 없다. 신규
  integration test는 실제 migrated
  PostgreSQL과 FastAPI dependency를 관통해 `/v1/ops/datasets`, dataset detail,
  `/v1/ops/pipeline/executions`의 canonical root/exact pair 응답을 독립 oracle로 검증한다.
- 별도 seed session이 update request 1개와 feature root 11개를 실제 commit하고 API 요청마다 새
  session을 연다. 같은 `created_at` tie와 10개 cursor 경계를 만든 뒤 detail cursor로 pipeline
  2페이지를 조회해 정렬·무중복·무누락을 확인한다. provider와 dataset이 서로 다른 두 decoy
  member에만 존재하는 최신 root로 exact-pair AND도 증명한다. feature oracle은 caller 입력과
  고정 lifecycle값을 사용하고 mutation에서는 DB 생성 UUID만 취한다. proxy secret/actor 인증,
  tagged schedule과 provider/dataset 양쪽에 `/`가 있는 orphan의 detail/history query 복원을 포함한다.
- 최종 재리뷰의 generated type drift는 canonical OpenAPI에서 `openapi-typescript 7.13.0`을 다시
  실행해 해소했다. `OpsDatasetGridRow.detail_url`만 생성되고 `OpsDatasetDetailData`에는 존재하지
  않으며, OpenAPI 구조 회귀와 기존 `gen:types:check`가 같은 배치를 지킨다. 세 구 동적 URL의
  인증 404를 추가했다. preview는 정적 slash pair가 없어 catalog/fixture 실행 경계만 주입한
  인증 ASGI/query/schema 증거이고, policy는 catalog authorization만 주입한 뒤 실제 service/repo/DB
  transaction과 별도 session SQL로 exact identity·값을 검증한다.
- append-only feature update 행은 trigger를 비활성화하지 않고 기존 integration convention의
  별도 `TRUNCATE ... RESTART IDENTITY CASCADE` transaction으로 정리한다. 이는 현재 disposable
  testcontainer DB의 순차 실행 전제이며, 공유 DB 병렬 실행에는 별도 격리가 필요하다.
- 적대 리뷰어 2명의 최종 판정은 S1/S2 0건이다. API 전체 503건, router focused 13건,
  실제 migration·PostgreSQL/FastAPI 통합 1건을 통과했다. Ruff, strict mypy 4개 변경 소스,
  admin/user OpenAPI drift, admin generated type drift, frontend type-check와 lint(오류 0,
  기존 incompatible-library warning 2)도 통과했고 완료 task를 `tasks-done.md`로 옮겼다.
- B1 병합 뒤 CI가 발견한 구 scalar schedule mock을 실제 MOIS canonical
  job/schedule/`pipelineName`/registry launch tag로 수정했다. 두 추가 적대 리뷰는 S1/S2/S3
  0건이며 실제 migration·PostgreSQL/FastAPI 통합 1건과 Ruff가 다시 통과했다.
- **다음 한 작업**: 수정 head의 PR #710 CI·merge를 완료한다. 이후 B2/B3와 C3e-I 교차 회귀로
  #679를 닫는다.

## 2026-07-16 (codex) — C3e-B 실행 재분할·C3e-C 잔여 범위 확정

- PR #705로 A2가 병합됐고 main·CI가 green임을 확인했다. datasets grid/detail과 pipeline은
  이미 공용 canonical projection·DTO/OpenAPI를 소비하므로 C3e-C는 production 코드를 중복
  수정하지 않고 실제 PostgreSQL/FastAPI REST 교차 통합 증거만 추가한다.
- Claude Code의 C3e-B branch/worktree를 원격 branch, reflog, stash, filesystem blob까지 감사했다.
  C3e-B 고유 구현은 0파일이며 고아 worktree의 의미 있는 파일은 원격 C4R/C45X commit과
  동일했다. 따라서 복구할 코드 없이 최신 main에서 구현한다.
- C3e-B를 `B1` immutable registry/run identity, `B2` provider guard/public wrapper/MCST callback,
  `B3` active·terminal sensor/양방향 reconcile의 독립 PR로 나눴다. B1과 C를 먼저 병렬 진행하고,
  B1 병합 뒤 B2/B3를 병렬 진행한다. 모든 코드·테스트 의미 변경은 테스트 전 적대 리뷰 2인을
  유지하며 변수명/import 정렬 등 비동작 변경은 재리뷰하지 않는다.
- **다음 한 작업**: 이 문서-only 분할 PR을 rebase·CI green 후 추가 적대 리뷰 없이 바로
  병합하고, Agent A가 C3e-C, Agent B가 C3e-B1을 병렬 구현한다.

## 2026-07-16 (codex, agent A) — T-ADM-C3e-A2 구현·로컬 gate 완료(PR #705 병합)

- **공용 projection**: C3b cycle-safe lineage 위에서 canonical root와 exact
  `provider_datasets[]`를 한 번 계산하도록 executions, 단건 detail, overview, datasets latest
  batch/detail recent를 통합했다. 실컬럼 member를 유일한 import identity로 사용하며 direct
  scope와 provider/dataset 배열에서 pair를 재구성하지 않는다. event는
  감사·타임라인 전용으로 projection/filter/latest에서 완전히 분리했다.
- **계약 원자 전환**: feature run의 projected job을 root로 고정하고 raw
  `dagster_run_status`, `trigger_kind`, `operation_registry_version`, authoritative engine 시각과 pair별
  non-null member/status를 노출했다. overview는 canonical root의
  `operations_by_status`/`active_operations`/`failed_operations_24h`로 교체했다.
- **UI clean-cut**: 구 `/admin/feature-update-requests` 목록·상세 redirect route를 삭제했다.
  갱신 요청 client 구현은 정본 `/admin/features/update-requests` route 아래에서만 소유한다.
  n150 격리 checkout의 mocked E2E에서 인증 BFF와 현재 한국어 UI 계약을 함께 검증했다.
- **영향도·회귀 준비**: codegraph 영향 19/7/11/11/9/12/34개 symbol을 확인하고 all-dataset
  latest, timeline/grid/detail 동일 root, feature root 고정, pair 교차곱 금지와
  pair/provider-only/dataset-only identity-index EXPLAIN 회귀를 작성했다. 1차 적대 리뷰에서
  production caller가 사라진 구 request/job 요약 경계를 제거했고, 1,005개 root의 전수
  pagination·latest·overview 일치와 status/latest/detail raw SQL EXPLAIN gate를 추가했다. 2차
  적대 리뷰의 S2를 반영해 request detail scalar identity와 trigger를 root 계약에 맞추고 direct
  scope를 양쪽 JSON string·trim 보존·nonempty인 단일 pair로만 인정했다. DB-boundary 재리뷰와
  사용자 지시에 따라 runtime legacy event fallback은 호환 대상으로 유지하지 않고 제거했다.
  0051의 보수적 일회성 backfill만 event를 읽으며 multi/partial/ambiguous 잔여는 pair로 노출하지
  않는다.
- **최종 성능/계약 보강**: 테스트 후 재리뷰에서 선택 pair/UUID 조회의 전체 graph 선투영,
  pipeline pair 필드 optional 약화, 문서 drift를 발견했다. indexed identity에서 connected
  component/request를 먼저 좁히고 production-like natural-planner EXPLAIN으로 base relation
  `Seq Scan`·과도한 actual row를 차단한다. selective plan은 `import_job_events` relation 접근도
  금지한다. projection seed event index는 제거하고 무필터·provider-only·exact pair event 감사
  조회용 시간순 index와 고정-clause query로 책임을 분리했다. 0057부터 provider 없는
  dataset-only event filter와 단독 인덱스는 제거한다. `provider_datasets`와 nullable pair
  필드는 required로 통일한다. 최종 DB 리뷰의 이중 정본 지적에 따라 0052는 request의 canonical
  job FK를 `NOT NULL/RESTRICT`로 강화하고 jobless·불일치·reserved Dagster kind request를 새
  canonical job으로 재연결한다. direct scope/filter shape와 linked `feature_update_request`
  kind·typed pair 일치, non-direct unpaired shape, import kind/pair 불변성을 DB CHECK/trigger로
  강제하며 filter는 JSONB에서 typed `TEXT[]`로 clean cut하고 direct JSON expression index와
  root fallback을 제거했다. 재리뷰에 따라
  migration 첫 SQL에서 writer table을 잠그고 request/source connected component 전체의
  active/cancellation relink를 중단한다. immutable DB 함수와 main-library 공용 validator가
  OpenAPI와 같은 6종 scope의 exact key/type/문자열/배열/좌표/반경 shape와 provider/dataset
  filter의 32/64개·trimmed string 규칙을 강제하고 기본값과
  nullable field를 canonicalize한다. 실행기에 의미가 없던 `sigungu_by_radius.match` 두 값은 제거해
  `intersects`만 허용한다. write 없는 dry-run은 persisted schema에서 제거하고 201 생성과 200
  preview endpoint로 분리했다. 후속 DB 적대 리뷰에 따라 request↔canonical job은 unique FK와
  양쪽 deferred constraint trigger로 양방향 1:1을 강제한다. 기존 unlinked terminal job의 양방향
  연결 component 전체에는 `quarantined_at`과 고정 사유를 기록하고 원래 `kind`·`payload`는 보존한다.
  모든 projection/generic writer에서 제외하며 runtime 표식 변경, UPDATE/DELETE/event 추가와 새 child
  attach를 거부한다. active/cancellation-protected component는 migration을 중단한다. canonical
  job kind는 generic enqueue/start/claim/finish/cancel/recover/bind/payload/batch 경계에서 reserved로
  차단하고 전용 enqueue/lifecycle/heartbeat만 사용한다.
- **리뷰 보강**: 첫 통합 재리뷰 이후에도 DB/UI clean-cut 변경이 이어졌으므로 과거 승인은
  최종 gate로 사용하지 않는다.
  DB reviewer가 찾은 임의 `update_policy` JSON 저장→typed 목록 500 경로를 repository
  canonicalizer, 0052 preflight, DB CHECK/ORM metadata와 valid/malformed migration 회귀로
  제거했다. 후속 REST 재리뷰가 찾은 boolean coercion과 sparse response의 null 재팽창도
  `total=False` strict policy `TypedDict`와 422/OpenAPI 회귀로 제거했다.
  이어진 DB 리뷰에서는 request/job lifecycle 이중 저장, timestamp generation, NULL owner의 중복
  claim과 MVCC join race를 제거했다. request는 입력/감사·`matched_scope`·정수 `generation`만
  소유하고 canonical job이 lifecycle 단일 정본이다. 모든 실행 mutation은 두 행을 함께 잠근 뒤
  exact generation과 trimmed non-empty Dagster run owner를 CAS하며, cancellation member는
  `job_id` PK/FK 한 종류만 사용한다.
- **테스트 중 발견·수정**: 0052가 SQLAlchemy naming convention의 실제 FK 이름
  `fk_feature_update_requests_job_id_import_jobs`를 사용하도록 맞추고, 새 CHECK 이름에는
  Alembic `op.f(...)`와 ORM `conv(...)`를 적용해 이중 prefix를 제거했다. migration fixture는
  canonical 0051 root/child shape로 고쳤고 active preflight truth table은 source/raw
  Dagster/request/jobless/child 조건을 서로 격리했다. SQLAlchemy text SQL의 `:null` test bind
  해석을 제거하고, direct-exact EXPLAIN seed의 배경 분포도 실제 선택성을 검증하도록 강화했다.
  event 감사 조회는 격리 marker가 부모 join 없이 직접 필터되며, statement-level event clock이
  late commit·rollback·TRUNCATE·zero-job invalidation을 누락 없이 표현한다. 같은 transaction의
  `now()` 동률 event는 인과 최신을 가정하지 않고 heartbeat의 exact code/stage/payload를 검증한다.
- **리뷰·gate 완료**: DB/REST/UI 최종 diff와 이후 로직 수정마다 적대 리뷰 2인의
  S1/S2/S3 0건 승인을 받았다. Ruff, strict mypy(main 112/API 55/Dagster 21), import 계약 4/4,
  OpenAPI/admin type drift, frontend type/lint(오류 0), unit 1,366, API 502, Dagster 270
  (optional `mois.db` 1 skip), non-live integration 518, frontend unit 82, production build를
  통과했다. n150 Linux 격리 checkout의 11개 mocked spec은 **501/501 통과**했고 prod
  checkout/container는 변경하지 않았다. 로컬 reverse geocoder가 400을 반환하는 live 전용 5건은
  C3e-I/C7의 n150 prod gate로 분리했다.
- **병합 결과**: PR #705는 8개 CI gate green 뒤 main에 병합됐고, 사용자 지시에 따라 A2는
  `docs/tasks-done.md`로 이동했다. 이후 C3e-B1/B2/B3/C/I를 진행해 #679를 닫고 C45X/C4R 리뷰·개선으로
  넘어간다. 파괴적 live UI E2E와 prod 최종 검증은 C3e-I/C7에서 수행한다.

## 2026-07-15 (codex, agent A) — T-ADM-C3e-A1 구현·로컬 gate 완료

- **문서 선행 완료**: C3e-D 문서 계약 PR #696이 병합되어 `T-ADM-C3e-D`를 완료
  아카이브했다.
- **A1 구현**: Alembic 0051과 ORM에 canonical provider/dataset/trigger/registry/raw Dagster
  상태, partial unique/index와 parent/identity trigger를 추가했다. main package immutable
  operation DTO와 짧은 transaction client/repository가 ensure, pair 완료, attempt event,
  terminal reconcile, active keyset sweep을 제공한다.
- **writer·취소 경계**: generic writer와 feature-update direct SQL은 reserved kind/parent/target을
  fail-closed하고 offline/MOIS/exact update identity를 실컬럼으로 기록한다. C3d frozen member에
  `operation_kind`/`requires_run_termination`을 저장해 run-backed queued feature operation을
  DB-only 취소에서 제외하고 같은 run terminate/retry/terminal CAS로 처리한다. admin OpenAPI와
  generated type도 같은 계약으로 갱신했다.
- **영향도·적대 리뷰**: codegraph에서 `ImportJobRow` 52개 영향 symbol과
  `AsyncKorTravelMapClient` caller 20개를 확인하고 direct SQL inventory를 보완했다. 테스트 전
  적대 리뷰 2인이 terminal child 보존, same-run 동시 ensure, marker 양방향 barrier,
  engine timestamp drift, queued run-backed retry를 보강한 뒤 S1/S2 0건으로 승인했다.
- **로컬 검증 완료**: 외부 geocoder live 전용 파일을 제외한 전체 1,762건, API 전체
  473건, Dagster 전체 270건(1 skip), frontend unit 82건과 focused
  migration/cancellation 200건이 통과했다. live 전용 5건은 로컬 geocoder HTTP 400으로
  분리했으며 나머지 회귀는 0건이다. Ruff, strict mypy 3패키지, import 계약 4/4,
  OpenAPI/admin type drift, frontend type/lint/build도 통과했다.
- **다음 한 작업**: 최종 diff를 적대 리뷰 2인에게 다시 넘겨 S1/S2 0건을 확인하고,
  보안 감사·PR CI·review approval 뒤 A1을 병합한다. 이후 A2와 B를 main 기준 병렬 진행한다.

## 2026-07-15 (codex) — T-ADM-C3d 종결, T-ADM-C3e 문서 gate 진행

- **C3d 완료**: PR #695가 CI 8/8 green 뒤 merge됐고 이슈 #680도 수용 증거와 함께
  닫혔다. main 기준 merge commit은 `28dfe224`다.
- **C3e 복구 결과**: Claude Code worktree에는 구현 diff가 없고 설계 기록만 있었다. 두
  적대 리뷰에서 C3d 공유-run 취소와 충돌하는 pair별 root, retry 조기 failure,
  datasets 독자 payload SQL, pre-resource failure 누락을 확인해 원안을 반려했다.
- **고정 중인 계약**: Dagster run root 한 건 + exact provider/dataset child,
  `(kind,id)` correlation, QUEUED/STARTED sensor와 provider 선행 guard의 ensure,
  wrapper/callback의 child 성공, terminal/양방향 watermark sensor의 authoritative reconcile이다.
  feature-kind parent/identity trigger와 C3d marker guard를 적용하고 generic claim/stale
  recovery에서 새 kind를 제외한다. registered identity drift는 provider I/O 전 fail-closed하고
  DB→Dagster scan은 sweep 끝에서 wrap한다. raw Dagster status/engine timestamp와 pair 기반 root
  progress를 별도로 보존하며, run-backed queued 취소는 frozen termination/retry 상태기계로
  확장한다. pipeline overview/timeline과 datasets grid/detail은 C3b 공용 lineage projection을
  사용하며 `sync_scope`는 #686/C45X에 남긴다.
- **문서 리뷰 gate**: 두 적대 리뷰어가 최신 전체 diff를 S1/S2 0건으로 승인했고
  `git diff --check`와 prod redaction guard도 통과했다.
- **다음 한 작업**: C3e 문서 PR을 CI green으로 merge한다. 이후
  C3e-A1(schema+frozen client)을 먼저 머지하고
  C3e-A2(projection)와 C3e-B(Dagster)를 병렬 진행한 뒤 C3e-C(API)·C3e-I(통합)로
  #679를 닫는다.

## 2026-07-15 (codex) — T-ADM-C3d PR #695 CI 보강 중

- 최신 main rebase 뒤 focused Python 140건, frontend unit 82건, Ruff, strict mypy
  3패키지, import 계약 4/4, OpenAPI/admin type drift, frontend type/lint를 재통과했다.
- 첫 CI에서 모든 1,299 unit test는 통과했으나 unit-only coverage가 75.24%로 실패했다.
  DB 경로를 제외하거나 80% threshold를 낮추지 않고 Python 3.13 unit+PostGIS integration
  coverage를 합산하도록 workflow와 구조 회귀를 수정했다.
- 최종 적대 리뷰 S2/S3를 반영해 API 70%·Dagster 80% package gate, YAML 구조 기반 artifact
  wiring 회귀, 실패 시 combined XML 보존을 추가했다. 실측은 API 77%, Dagster 82%, 메인
  unit+integration 89.51%다. fresh DB에서 비결정적이던 EXPLAIN index 단언도 transaction-local
  planner 설정으로 목적을 고정했다.
- **다음 한 작업**: 합산 coverage를 로컬·PR CI에서 검증하고 #695를 머지한 뒤 #680을
  증거와 함께 닫는다. 이후 C3e 복구 후보 확정 결과에 따라 별도 PR을 시작한다.

## 2026-07-15 (claude, agent A) — T-ADM-C3c 감사 종결 (전 항목 기충족)

- **T-ADM-C3c 종결**: 착수 전 잔여범위 감사 결과 이슈 #681 수용 기준 전 항목이
  #687(공용 service 경계·pipeline nux-seen 계약 삭제)·#690(strict run 상세 —
  event cursor·page-local failure 구조·404/503/502 RFC7807·OpenAPI/types
  재생성)으로 **이미 main에 머지·충족**되어 추가 구현 없이 tasks.md `[x]` +
  감사 기록으로 닫는다(아래 codex 엔트리의 "다음 한 작업: draft PR"은 #690
  머지로 이행 완료 — stale). 상세 항목별 매핑은 journal 2026-07-15 (claude,
  agent A).
- **다음 한 작업**: 체인 순서상 `T-ADM-C3d`(agent B, #680) 진행 →
  agent A는 `T-ADM-C4R`(#684 — C4 UI 소비 계약 수정, PR #683 재작업) 대기.

## 2026-07-15 (codex, agent A/B) — T-ADM-C3d 구현·적대 리뷰·로컬 검증

- **구현 완료(PR 전)**: canonical root lease, marker/reservation 우선 commit,
  attempt별 at-most-once `SAFE_TERMINATE`, orphan resume, mixed/pending 사실 보존,
  hard backend invalidation과 네 cancel 진입점의 단일 coordinator를 구현했다.
- **feature update 보강**: queue sensor를 peek-only로 바꾸고 request/scope session lease 뒤
  CAS start, scope 경합 원자 requeue, scope data+`matched_scope` checkpoint, marker 우선
  `CancelledError` 처리를 구현했다.
- **적대 리뷰 반영**: 두 리뷰어가 찾은 running 고착, 미영속 checkpoint, CAS loser 409,
  stale ownership snapshot, definitive 오류 덮어쓰기, downgrade TOCTOU, dispatch 오류 분류,
  unlock backend 오염과 기존 UI 422를 수정했다. 최종 재리뷰에서 추가로 확인한 stale
  Dagster failure 세대 덮어쓰기, production asset의 별도 적재 transaction, 취소 operation의
  `Retry-After` OpenAPI 누락, 구 E2E cancel 계약도 수정했다. OpenAPI/admin types는 공용
  cancellation body·response·header 계약으로 다시 생성했다.
- **실행 경계 증거 보강**: failure sensor는 실패한 `dagster_run_id`를 expected generation
  CAS로 넘겨 재큐잉/새 owner를 건드리지 않는다. CAS start 전 resource 초기화 실패는
  `updated_at` generation이 같은 queued/null-run 행만 전진시켜 다음 sensor run key를 만든다.
  request start와 연결 import job owner가 하나라도 어긋나면 둘 다 rollback한다. production
  asset client는 executor scope transaction의 물리 connection에 bind하고 원본 engine 직접
  연결은 fail-closed로 거부한다. hard invalidate 테스트는 원 backend PID 소멸과 경쟁
  connection의 request lease 재획득을 확인한다. 브라우저 오류는 Next BFF allowlist를 포함해
  RFC7807와 `Retry-After`를 보존하고, 409/502/503에서도 연결 member를 모르는 singular 상세
  prefix까지 durable cancellation 상태를 다시 읽는다.
- **#680 근거 재점검**: 이슈 #680과 원인 PR #677, root projection PR #689의 수용 기준을
  다시 대조했다. 별도 marker, frozen canonical scope, authenticated actor/audit, GraphQL 5xx,
  request/job/run CAS, runless running 보존, member별 결과, commit 데이터 비롤백을 현재 구현과
  회귀 목록에 반영했다. #680은 C3d PR merge·CI green 뒤 증거 코멘트와 함께 닫는다.
- **병행 감사 완료**: 리뷰 전문 agent가 최근 2일 Claude Code PR #672, #674, #675,
  #676, #677, #683, #691, #692를 닫힘 여부와 무관하게 상세 검토하고 각 PR에
  코멘트를 남겼다. 후속은 신규 #693·#694와 기존 #682·#684·#685·#686으로 묶었고,
  미완 수용 기준 때문에 #682를 다시 열었다.
- **검증 완료**: 두 적대 리뷰어의 S1/S2 0건 승인 뒤 main unit 1,295건, API 전체
  470건, C3d Python 관련 134건, PostGIS 관련 통합 92건, frontend 전체 unit 82건,
  Dagster 전체 270건(1 skipped), C3d mocked Playwright
  37건을 통과했다. Ruff, strict mypy 3패키지, import 계약, OpenAPI/admin type drift와
  frontend type-check/lint도 green이다. mocked E2E는 새 Next 서버의 현재 빌드에서
  BFF 경유를 강제했으며 36건+실제 HATEOAS mock 수정 뒤 단독 1건으로 전량 확인했다.
- **다음 한 작업**: Dagster 전체와 최종 정적 gate를 닫고 origin/main rebase·보안 감사를
  거쳐 C3d PR을 CI green/review 뒤 merge한다. #680 종료 뒤 Claude Code worktree의 C3e를 회수해
  별도 PR로 완료하고, adm-c5 merge를 확인한 다음 C6a→C6b→C7로 진행한다.

## 2026-07-15 (codex, agent A/B) — T-ADM-C3d coordinator crash 계약 보강

- 두 사전 적대 리뷰에서 요청 단위 session autobegin과 외부 호출 중 transaction 유지,
  process crash 뒤 `in_progress` 고착/중복 terminate dispatch 위험을 확인했다.
- canonical root별 nonblocking session lease와 run별 `termination_reserved_at` CAS를 문서 정본에
  추가했다. lease 획득자는 orphan attempt를 frozen scope 그대로 재개하고, 이미 dispatch CAS가
  commit된 run은 같은 attempt에서 mutation을 다시 호출하지 않는다.
- 두 적대 리뷰어가 S1/S2 없이 문서 우선 gate를 승인했다.
- **다음 한 작업**: application coordinator/Dagster transport와 feature-update connection 고정
  phase를 agent A/B로 병렬 구현한다.

## 2026-07-15 (codex, agent B) — T-ADM-C3d DB phase 2차 적대 리뷰 보강 진행 중

- **진행 중**: queued shared-run 독립 취소, running-only retry, exact retryable과 definitive
  mismatch 실패 분리, 최초 Dagster status 보존, normalized JSON error NULL 차단을 수정했다.
  `cancel_failed`는 frozen running으로 한정하고 exact terminal run의 failure 우회를 막으며,
  definitive run failure는 FAILED 코드가 기록된 `run=cancel_failed`만 인정한다.
- **batch transaction 재수정**: consistency report와 MV side effect는 장기 transaction 안에서
  만들되 종료 직전에만 lineage-global→canonical root lock을 잡고 marker CAS/finalize한다.
  CAS 패배는 내부 sentinel로 장기 transaction 전체를 rollback한 뒤 별도 짧은 read
  transaction에서 cancellation 결과를 reload한다. Tx3/failure는 첫 mutation 전에 잠근다.
- **검증 상태**: 실제 report/side-effect rollback, exact terminal mapping, SQL NULL
  `IntegrityError`, queued/running shared run, authoritative reconcile failure, 반대 row-lock
  순서 회귀를 테스트로 정의했다. MV rollback은 refresh 내부 write와 별도 cancellation
  commit 뒤 post-refresh guard가 전체 write를 되돌리는 경로를 고정한다.
  사용자 지시에 따라 test/Ruff/mypy/import/compile은 실행하지 않았고 재리뷰·게이트도
  남아 있으므로 완료 상태가 아니다.
- **다음 한 작업**: 2차 적대 재리뷰를 통과시키고 허용된 실행 게이트 뒤 C3d 다음 phase로
  진행한다.

## 2026-07-15 (codex, agent B) — T-ADM-C3d 계층형 취소 문서 우선 설계 (#680)

- **계약 고정**: 기존 job/request status CHECK는 유지하고 base marker와 정규화한
  cancellation attempt/member/run을 영속 정본으로 삼는다. scope는 C3b의 request owner
  branch·duplicate non-owner·standalone partition·nested request 경계를 그대로 사용하며,
  terminal root 아래 active descendant도 취소한다. attempt status는 workflow
  `in_progress`/`retryable`/`completed`/`failed`, 실제 취소 결과는 member/run에만 둔다.
- **안전 경계**: marker와 durable audit를 먼저 commit하고 transaction 밖에서 Dagster
  terminate한 뒤 terminal을 재확인한다. queued는 marker CAS, running은 `CANCELED` 확인
  때만 cancelled로 확정하고 exact member-marker-run mapping의 `SUCCESS`/`FAILURE`만
  done/failed로 reconcile한다. timeout 같은 transient 실패는 attempt `retryable`, 권위 있는
  reconcile 불가는 `failed`로 구분하고, 둘 다 허위 cancelled 없이 marker와 대상별 오류를
  남긴다.
  재시도는 이전 frozen scope의 미해결 member만 복사한다.
- **worker/transaction 정본**: status/payload/lineage를 포함한 모든 base-row mutation과
  descendant 생성은 marker CAS/root lock을 요구하며 event/audit append만 허용한다. feature
  update scope별 commit은 전용 `AsyncConnection` 하나에 session advisory lock을 고정하고,
  이미 commit된 데이터는 rollback하지 않는다.
- **다음 한 작업**: 이 문서-only commit의 적대적 재승인을 받는다. 승인 전 source edit은
  0으로 유지하며, 승인 뒤 alembic 0050 → repository/coordinator → Dagster terminate service →
  REST/OpenAPI 순서로 구현한다.

## 2026-07-15 (codex, agent A) — T-ADM-C3c pipeline Dagster run 상세 (#681)

- **구현 완료**: 신규 pipeline run 상세에 opaque event cursor와 page-local failure
  구조를 이식했다. 성공만 200이며 not-found/연결 실패/query 오류를
  404/503/502 RFC7807로 구분하고, 신규 pipeline NUX route는 제거했다.
- **적대적 리뷰 반영**: 허용되지 않은 URL·PythonError 502 회귀를 추가하고,
  빈/불일치 run ID와 잘못된 event pagination payload가 정상 응답으로 승격되지
  않도록 parser를 강화했다. legacy route는 같은 malformed payload를 200
  `status=error`로 보존한다.
- **검증 완료**: 수정 diff 적대적 재리뷰는 S1/S2 0건으로 승인됐다. root unit/lint
  1,289건, API 전체 451건, 관련 Dagster router 82건, 전체 Ruff, strict mypy
  main 104파일/API 51파일, import 계약 4/4, OpenAPI admin/user와 admin TypeScript
  drift가 통과했다. DB/migration 변경이 없어 별도 PostGIS gate는 적용하지 않았다.
- **완료**: PR #690이 CI 8/8 green 뒤 merge됐다.

## 2026-07-15 (codex, agent B) — T-ADM-C3b pipeline root projection (#679)

- **구현 완료**: recursive component와 nearest request anchor로 job을 request branch/
  standalone partition에 단일 귀속했다. root와 대표 job 상태, 다중 identity,
  `lineage_owner` loser 진단, 3-field cursor를 REST/OpenAPI에 반영했다.
- **검증 완료**: root/agent A 적대적 리뷰 2인이 S1/S2 0건으로 승인했다.
  root unit 1,285건, API 전체 416건, 관련 PostGIS/EXPLAIN integration 10건과
  Ruff, strict mypy 155파일, import 계약 4/4, OpenAPI/admin types drift가 통과했다.
- **완료**: PR #689가 보안 감사와 CI 8개 green을 거쳐 merge commit
  `d131c37c858d7fa8f6dda2b434dcae18d6d54b3f`로 main에 반영됐다. 다음 pipeline
  작업은 T-ADM-C3d 문서 우선 설계이며 C3e 전에는 C5를 시작하지 않는다.

## 2026-07-15 (codex, agent A) — T-ADM-C2R datasets 차단 계약 보강 (#678)

- **계약 보강**: 명시적 `stale_after_minutes`만 쓰는 server freshness,
  `eligible_after`와 Dagster 실제 `next_scheduled_at` 분리, 연결 request/job을 root
  request로 접는 최신 실행 batch projection, provider/dataset 이슈 분리, orphan
  mutation 409 reason, fixture-only typed preview budget/truncation을 구현했다.
- **구조 보강**: 800줄대 router를 HTTP router·schema·application service·Dagster
  schedule projection·fixture preview로 분리했다. Alembic 0049는 기존 정책을 NULL
  (`freshness=unknown`)로 보존하는 nullable SLA 컬럼과 양수 CHECK만 추가한다.
  schedule/manual 전체 operation 정본과 원자 취소는 #679로 분리했다.
- **검증 완료**: root/agent B 적대적 리뷰를 거쳐 API 관련 23건·API 전체 416건·
  root unit 1,284건·관련 PostGIS/Alembic integration 20건과 Ruff·strict mypy
  176파일·import-linter 4계약·OpenAPI/admin types drift·단일 migration head를
  통과했다.
- **완료**: PR #688이 보안 감사, 원격 diff 적대적 재리뷰, CI green을 거쳐
  merge됐다. 다음 datasets 작업은 `T-ADM-C4R`이며 pipeline은 `T-ADM-C3b`를
  진행한다.

## 2026-07-15 (codex, agent B) — T-ADM-C3a pipeline 공용 application 경계 구현 완료 (이슈 #682)

- **구현 완료**: `/ops/pipeline`과 legacy router가 함께 쓰는 Dagster schema,
  GraphQL transport/parser, query/schedule application service, feature update
  schema/service를 public 모듈로 추출했다. FastAPI request/exception 변환은 별도 HTTP
  adapter에 한정하고 settings·HTTP client·DB session은 명시적으로 주입한다.
  private router import는 제거했으며 HTTP/OpenAPI 계약은 그대로다.
- **검증 완료**: 적대적 리뷰 2인과 docstring drift 재리뷰를 통과했다. 관련 API unit
  68건, API 전체 421건, root unit 1,282건, schedule override integration 1건,
  Ruff·strict mypy 3패키지·import-linter·OpenAPI admin/user 무변경 검증이 green이다.
- **완료**: PR #687이 CI 8개 green과 원격 diff 적대적 재리뷰를 거쳐 merge됐다.
  다음 pipeline 작업은 `T-ADM-C3b`이며 C3e merge 전에는 C5를 시작하지 않는다.

## 2026-07-14 (claude, agent B) — T-ADM-C3 backend /ops/pipeline 그룹 완료 (PR #677)

- **T-ADM-C3 완료**: `/v1/ops/pipeline/*` 12 endpoint(overview+sensor · executions
  DB-only UNION keyset · `/{kind}/{id}`+cancel · events · dagster-runs ·
  schedules PATCH(cron null=override 삭제)/commands 4종 · requests 6-type scope
  union 승계 · run-now · nux-seen) + `kortravelmap.infra.pipeline_repo` + alembic
  0048(`import_jobs.dagster_run_id` 실컬럼+백필+부분 인덱스) + ops_live 스냅샷
  실컬럼 전환. OpenAPI/admin types 재생성(`openapi.user.json` 불변). **적대적
  리뷰 2인(S3 9건) 반영 포함** — mixed-version 배포 창 COALESCE 폴백(0048
  docstring에 배포 순서·백필 재실행 SQL), UUID 검증 500→422, 감사 필드 구조화
  로그 2건, 409 Retry-After 명문화, A의 `dataset_status_repo`에 `dagster_run_id`
  전파, C5/C6b 전제 tasks.md 명문.
- **다음 한 작업**: PR #677 머지(오케스트레이터) 후 `T-ADM-C5`(frontend
  `/ops/pipeline` 페이지+훅+mock e2e + 홈 위젯 소스 결정, agent B) 착수 —
  tasks.md의 C5 소비 전제(UNION 이중 행 접기·provider 필터·progress 취득처)
  준수. 상대 agent 2일치 PR 적대적 리뷰 규율 유지.

## 2026-07-14 (claude, agent A) — T-ADM-C2 backend /ops/datasets 그룹 완료 (PR #676)

- **T-ADM-C2 완료**: `/v1/ops/datasets/*` 4 endpoint(3원 그리드·scope 배열 상세·
  refresh-policy PUT·ETL preview) + `kortravelmap.infra.dataset_status_repo` +
  live preview opt-in flag(`etl_live_preview_enabled`, 기본 off). admin frontend
  게이트의 자체 include 블록 마운트, OpenAPI/admin types 재생성
  (`openapi.user.json` 불변). **적대적 리뷰 2인 반영 포함** — refresh-policy
  PUT의 SELECT-후-begin 500(S2)을 단일 transaction으로 수정 + 실세션
  integration 회귀(`tests/integration/test_ops_datasets_refresh_policy.py`),
  PUT 허용 집합을 카탈로그∪잔존 sync∪기존 policy로 확장(S3),
  `.env.example` flag 항목(S3).
- **다음 한 작업**: PR #676 머지(오케스트레이터) 후 `T-ADM-C4`(frontend
  `/ops/datasets` 페이지+훅+mock e2e, agent A) 착수. agent B의
  `T-ADM-C3`(#677) rebase 시 `dataset_status_repo._IMPORT_JOB_COLUMNS`에
  `dagster_run_id` 정리 예정(B 담당).

## 2026-07-14 (claude) — admin ops 통합 플랜 확정(ADR-064) + #672 n150 검증 완료

- **#672 배포·검증 완료**: n150 재배포(alembic 0047 head·4컨테이너 healthy·공개
  도메인 로그인 200), endpoint/cursor override 부재 확인 → `changes` 전체 재생
  전환. materialize RUN_SUCCESS — ledger upsert 1,430/철회 0(전파할 철회 없음이
  정답), T-189 재발급으로 980 재-render + 신규 40 적재(active 1,020). 사전 존재
  발견: 410건 `provider_address_mismatch` drop 영구 미적재 → 이슈 **#673** 분리.
- **admin ops 통합 재작성 착수(T-ADM-C1 완료)**: 2페이지(`/ops/pipeline`·
  `/ops/datasets`) 통합 플랜을 적대적 설계 리뷰 2인 반영으로 확정 —
  `docs/reports/admin-ops-consolidation-plan-2026-07-14.md` + ADR-064 +
  `docs/tasks.md` `T-ADM-C1`~`C7`.
- **다음 한 작업**: `T-ADM-C2`(backend datasets, agent A) + `T-ADM-C3`(backend
  pipeline + alembic `dagster_run_id`, agent B) 병렬 착수 — 각 PR에 OpenAPI/types
  재생성 포함, 테스트 전 적대적 리뷰어 2명, 잦은 rebase.

## 2026-07-14 (claude) — concierge export 소비 계약 정렬 완료 (로컬)

- **완료(코드)**: producer(kor-travel-concierge) 7월 검수 개편(soft-delete 제거
  목록·되돌리기·검수 회수·bulk) 반영 — 기본 sync endpoint `snapshot`→`changes`
  (철회 전파 갭 수정), provenance 평면 키 `facility_info.youtube_source_*` 추가,
  되돌리기(tombstone→재-upsert) 재활성화 concierge 경로 통합 테스트 3건 고정.
  wire 계약(envelope·cursor·operation 3종)은 producer diff로 불변 확인. 자세한
  내용은 journal 2026-07-14 (claude).
- **적대적 리뷰 1차 반영**: mid-run 되돌리기 역전 수정
  (`kor_travel_concierge_latest_items` 압축), rejection_reason 문서 오류 정정,
  producer T-189(행정코드 실데이터·schema_version) 미러 반영, cursor 전제 명시.
- **적대적 리뷰 2차(리뷰어 2명) 반영**: S1/S2 0 · S3 6건 반영 — asset 압축 배선
  테스트 2건 신설, 되돌리기 문구 정정(reopen 즉시 tombstone·재확정 시 upsert),
  sido 유도 규칙 legal_dong fallback 병기, 픽스처 schema_version·source_title
  원문화, 배포 체크에 cursor 확인 병기.
- **다음 한 작업**: CI green → PR 머지 → n150 dagster/API 재배포(배포 시 prod
  env의 `..._FEATURE_SYNC_ENDPOINT` override와 `..._FEATURE_CURSOR` **부재**를
  함께 확인 — cursor가 남아 있으면 철회 backfill이 조용히 누락된다) →
  `feature_place_kor_travel_concierge_youtube` materialize로 철회 전파·재활성화
  live 확인 → live UI e2e(저부하 per-file) 완료.

## 2026-07-14 (codex) — notice reconcile 운영 제곱 비용 제거

- **운영 원인**: 0046 첫 KREX 실수집에서 lock 대기가 아닌 reconcile SQL 자체가 6분 이상
  실행됐다. 약 9,700개 동일 scope lineage 각각에 대해 동일 scope 전체를 lateral 비교해
  제곱 비용이 발생했다.
- **수정·보호**: 동일 scope winner는 set 기반 `ranked` 결과를 재사용하고, 다른
  provider/dataset/type 계보를 공유한 Feature만 cross-scope 보호 비교를 수행한다. 다중 lineage와
  cross-provider 생존 통합 테스트는 그대로 통과한다.
- **planner 통계 원인**: 최적화 배포 뒤에도 lifecycle UPDATE가 5분을 넘겨 조사한 결과,
  `feature.features` 실제 1,029,113행을 약 970행으로 오인했고 `last_analyze`가 없었다. 운영
  rollback A/B에서 `ANALYZE` 전 120초 timeout, 후 1.4초를 확인해 Alembic 0047에 관련 join
  table 통계 갱신을 고정했다. `pg_restore`가 통계를 보존하지 않으면서 Alembic revision은
  유지되는 재발 경로는 6월 28일 n150 restore/swap 이력과 일치했다. 일반 restore와 n150
  runner 직후 staged analyze, swap 전 통계 검증으로 같은 전환의 재발을 차단했다.
- **검증**: repository unit 14건, notice lifecycle PostGIS integration 23건, Ruff·strict mypy 통과.
- **적대적 리뷰**: 1차 `S1 0 / S2 0 / S3 1`의 scope `OR`/차원별 검증 지적을 반영했고,
  2차 독립 리뷰는 `S1/S2/S3 0`으로 종료했다.
- **통계 보강 리뷰**: 별도 적대적 리뷰 2회에서 권한 warning-only skip, 일반/n150 restore
  경로 누락, 빈 DB test의 거짓 양성을 찾아 수정했다. 최종 판정은 두 리뷰 모두
  `S1/S2/S3 0`이며, restore unit 10건과 전용 PG16 migration integration 1건을 통과했다.
- **다음 한 작업**: 적대적 리뷰 2회와 CI green 후 n150에 재배포하고, KREX 2회 실행 시간·
  중복 0·동일 snapshot no-op을 확인한 뒤 KMA/OpiNet 및 live UI E2E를 완료한다.

## 2026-07-14 (codex) — notice 계보 수명주기 영속화·원자 적용 완료

- **근본 수정**: Alembic 0046의 scope/member 상태로 KREX authoritative snapshot과 KMA rolling
  event를 분리해 영속화했다. scope-local 부재 집합이나 Feature ID 직접 close 대신 모든
  provider/dataset 구조적 winner 상태를 함께 판단해, 마지막 active 계보가 실제로 사라질 때만
  공지를 닫고 재발표 시 다시 연다. KMA 공급자 예정 종료는 member `valid_until`로 보존하고,
  backfill되지 않은 `unknown` 계보는 오종료 근거로 쓰지 않는다.
- **원자성·순서 방어**: 전역 transaction advisory lock 아래 bundle load→lineage state→dedup→
  Feature lifecycle을 한 transaction으로 반영한다. KREX는 stale/equal-conflict CAS와 exact replay
  self-heal, KMA는 계보별 최신 event와 stale announcement 무시를 적용한다. Dagster preflight도
  scope watermark를 읽되 equal run의 최종 판정은 DB fingerprint CAS에 맡긴다.
- **리뷰·검증**: 적대적 리뷰 1차에서 발견한 신규 lineage state 누락, cross-scope 종료 시각,
  out-of-scope `true`/`unknown` 재개방 의미, false 종료 시각 drift, 예정 종료 삭제, stale KMA
  payload의 source current 역전과 SQL JOIN 오류를 수정했다. 2차에서 정상 발표+동일 계보 해제
  batch와 non-empty 0046 downgrade를 보강했다. 두 리뷰 모두 수정 후 S1/S2/S3 0건이다. core unit
  1,259건, PostGIS integration 308건(`kor-travel-geo` live 5건 제외), Dagster 전체 262건, frontend
  Vitest 78건과 Ruff·core/Dagster strict mypy, import-linter, frontend type-check·lint, Alembic single
  head를 통과했다.
- **다음 한 작업**: PR CI green→merge→
  n150 Alembic 0046 배포·실제 KREX/KMA 수집→notice 중복 0/종료·재등장 확인→live UI E2E를 수행한다.

## 2026-07-13 (codex) — provider soft-delete 재등장 self-heal 로컬 완료

- **운영 발견**: n150 배포 검증에서 KREX 현재 feed 46건 중 5건이 과거 soft-delete 상태에
  남아 비표시되는 것을 확인했다. 해당 행은 provider 소유이고 사용자 편집·재활성화 방지
  override가 없어 역사적 중복 정리 잔존임을 확정했다.
- **수정**: 동일 payload fast-path도 현재 Feature의 lifecycle을 확인해 provider 소유
  ``inactive`` 상태를 한 번만 복구한다. 직접 notice reconcile은 현재 feed의 soft-delete된
  정본을 복구하고, 다중 primary 계보에서는 한 계보라도 winner인 Feature를 보존한 채 active
  winner 계보만으로 종료·재등장을 결정한다.
- **보호·검증**: ``user_request``와 ``prevent_provider_reactivation``은 건드리지 않으며,
  복구 다음 실행은 다시 no-op이다. 관련 통합 33건·unit 12건, Ruff·strict mypy를 통과했다.
- **다음 한 작업**: 적대적 리뷰 2회와 CI green 후 머지·n150 재배포하고, 주입 없는 KREX
  수집에서 현재 feed 전건 활성·중복 0건을 확인한다.

## 2026-07-13 (codex) — Feature bbox JIT 지연 로컬 수정 완료

- **근본 원인**: 고zoom 12 tile 병렬 조회의 SQL 실행 자체는 수십 ms이지만,
  높은 추정 cost가 요청마다 PostgreSQL JIT 컴파일을 유발했다. 운영 읽기
  전용 A/B에서 동일 query가 JIT on 1,844.8ms, off 20.2ms였다.
- **수정·범위**: API asyncpg 연결에만 ``jit=off``를 적용했다.
  ``make_async_engine`` 인자는 optional이므로 Dagster/CLI/기존 사용자 동작은
  변하지 않는다. GeoJSON source 갱신과 marker 조회의 경합으로 개별 marker가
  0개에 머물던 live 회귀는 map ``idle`` 시점 재동기화로 보완했다.
- **검증**: codegraph 영향 127 symbol을 확인했고 관련 unit 13건,
  Ruff, 변경 source strict mypy를 통과했다.
- **다음 한 작업**: 적대적 리뷰 2회와 전체 게이트·CI green 후 머지하고,
  n150 API를 재배포해 실제 12 tile wall time과 live UI cluster 해제를 재검증한다.

## 2026-07-13 (codex) — notice/OpiNet 반복 장애·지도 고zoom 지연 로컬 수정 완료

- **근본 원인 수정**: Dagster 고착 run의 전역 슬롯 고갈, 불완전·역순 KREX snapshot 수용,
  OpiNet 0건/전일·혼합 가격 성공 오인과 scope 무시 targeted 전국 조회를 각각 run monitoring,
  pool+DB lock+coalescing, strict 2회 snapshot, cursor 기반 KST 당일 성공 조건으로 차단했다.
- **사용자 가시 변경**: 종료 공지를 공개 지도·검색·직접 조회에서 제외하고 재등장 시에만
  복원한다. AirKorea/KMA marker를 분리하며 OpiNet 과거 날짜를 지도·목록에 표시하고 가격
  이력의 단일·동시각 점도 렌더한다. Feature/큐레이션 고zoom의 tile fan-out·DOM marker·bbox
  재조회를 줄였다.
- **리뷰**: 독립 적대적 리뷰를 두 차례 수행해 발견한 S1/S2를 모두 수정했고 최종 재검토의
  잔여 S1/S2는 0건이다. KREX 원천 envelope 문제는 provider 저장소 PR #11을 먼저 머지하고
  본 저장소 dependency pin을 갱신했다.
- **검증**: 외부 인증 live marker를 제외한 전체 Python 1,555건, API 354건, Dagster 260건,
  frontend 78건, marker 1건과 Ruff·strict mypy·import-linter·OpenAPI/type drift·production
  build를 통과했다. 로컬 geo live 5건은 미설정 API key 때문에 기존 auth-required 서비스가
  400을 반환한 환경 전제이고, 변경 범위 테스트 실패는 없다.
- **다음 한 작업**: remote push 전 보안 감사를 마친 뒤 PR CI green→merge→n150 backlog
  복구·배포→실제 notice/OpiNet 수집과 live UI E2E를 검증한다.

## 2026-07-13 (codex) — T-230 다중 관측·collection 큐레이션 n150 검증 완료 (#666)

- **구현 완료**: source entity/current record와 immutable payload history 분리,
  collection/item 큐레이션 스키마·repository·REST, 관리자 수동 입력·CSV 양식/preview/import,
  Feature별 grouped 지도·목록·상세 표시를 구현했다. 한 Feature의 여러 primary provider 관측과
  여러 테마·제목·회차 membership을 배열로 모두 반환한다.
- **공식 데이터**: 한국관광 100선 2023~2024·2025~2026, 국가유산 방문 캠페인,
  2026 수목원·정원 스탬프투어, 등대 스탬프투어를 486개 membership 행으로 추가했다.
  n150 resolver 적용 결과는 기존 Feature 연결 225행·미연결 보존 261행이다. 등대 category
  `01050400`(`TOURISM_NATURE_LIGHTHOUSE`)도 추가했다.
- **검증 완료**: 전체 Python/PostGIS/API/frontend/OpenAPI/import-linter 게이트와 적대적 리뷰를
  통과했다. n150 prod를 Alembic 0045로 migration하고 공식 collection 19개·membership 486개를
  적재했다. 두 회차 중첩 Feature 40개, 복수 provider 관측 2개, 동일 CSV 재적재 변경 0건,
  prod live Playwright 4 passed를 확인했다. 최종 적대적 리뷰의 공개 원본 노출·정수 overflow·
  손실성 downgrade와 두 LOW까지 모두 수정해 잔여 지적은 0건이다.
- **다음 한 작업**: PR #666 CI green과 review를 확인해 merge한 뒤 main을 n150에 재배포하고
  0045·19/486·로그인·live smoke를 마지막으로 재확인한다.

## 2026-07-13 (codex) — concierge DB read key 소비 계약 로컬 반영

- **완료(로컬 편집)**: Concierge feature fetcher의 환경변수 이름과 header wire contract는 유지하면서,
  credential 출처를 static `API_KEYS` 공유에서 DB `read` scope 키로 전환했다. resource source env
  metadata와 운영 회전 문서·회귀 테스트를 함께 정렬했다.
- **검증**: n150 Python 3.11 일회성 컨테이너에서 core/lint 1,169개, API 331개, Dagster
  220개 테스트 통과·Dagster 1개 환경성 skip, 전체 Ruff, main/API/Dagster strict mypy, import 계약,
  prod 문서 redaction 검사를 통과했다. 로컬 테스트는 실행하지 않았다.
- **다음 한 작업**: PR/CI green → Concierge scope migration → read 키 주입 후 snapshot/changes
  다중 page·cursor 및 내부/write 403 → BFF/operator admin overlap 회전 → 구 static consumer 키 제거.

## 2026-07-12 (codex) — Feature 목록/상세 polish 로컬 완료

- **완료(로컬)**: Feature 목록 요약 배지를 표 헤더로 옮기고 pagination 테두리를 한 겹 줄였다.
  Feature preview 상세 패널은 별도 "Feature 상세" row 없이 이름/feature_id/편집 버튼을 한 행에
  배치했다. 큐레이션 지도 필터는 PC에서 한 줄 가로 컨트롤바로 유지되도록 보정했다.
- **검수 500 확인**: n150 API 직접 호출과 live 검수 화면에서
  `/v1/admin/features/change-requests?status=pending&page_size=100` 500은 재현되지 않고 200으로 확인됐다.
- **검증**: admin frontend `type-check` 통과, `lint` 0 error(기존 warning 3),
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_*` 로컬값 주입 production build 통과. 배포 전 before 스크린샷
  4장을 `artifacts/ui-e2e-20260712/`에 보관했다.
- **다음 한 작업**: 보안 감사 → PR 생성/CI 확인 → 머지 → n150 UI 배포 → live UI e2e after 스크린샷
  비교.

## 2026-07-12 (codex) — admin 큐레이션/Feature/이슈 화면 밀도 정리 로컬 완료

- **완료(로컬)**: 큐레이션 상세·관리 위치 지도 높이를 키우고 후보 선택 패널에서도 동일 마커가 보이도록
  좌표 정규화/마커 렌더를 정리했다. 큐레이션 화면의 반복 설명 문구를 제거하고, 큐레이션 흐름은
  tooltip + 도움말 다이얼로그로 압축했다. admin Feature 목록/이슈 목록 필터도 한 줄 가로 스크롤 바로
  정리했다.
- **검증**: admin frontend `lint` 0 error(기존 warning 4), `type-check` 통과,
  `NEXT_PUBLIC_*` 로컬값 주입 production build 통과.
- **다음 한 작업**: 필요 시 PR 생성 → CI 확인 → n150 UI 재배포.

## 2026-07-12 (codex) — curated source rule `detail_selector` 500 로컬 수정 완료

- **완료(로컬)**: 운영 요청 ID 기준으로 `/v1/admin/curated-source-rules?limit=200` 500의 원인이
  `CuratedSourceRule.detail_selector`와 API `CuratedSourceRuleView` 계약 drift임을 확인했다.
  API view/create/patch schema와 repo update JSONB 처리, generated admin OpenAPI/types를 정렬했다.
- **검증**: curated routes/repo unit 10 passed, ruff 변경 파일 clean, mypy --strict 변경 source
  2개 clean, OpenAPI drift check 통과.
- **다음 한 작업**: 보안 스캔 → PR/CI → 머지 → n150 api/ui 재빌드 배포 후 같은 endpoint 200 확인.

## 2026-07-10 (codex) — Feature 지도 필터 기본값/초기화 UX 로컬 구현 완료

- **완료(로컬)**: `/features` 지도 kind 필터 기본 선택을 `weather`, `notice`로 바꾸고, `초기화`
  버튼을 상시 표시 + 기본 선택 복원으로 수정했다. 저zoom 클러스터 요청도 선택 kind를
  `/v1/features/in-bounds?kind=...`로 보내는지 mocked/live e2e 단언을 보강했다.
- **검증**: frontend `type-check`, e2e type-check, 변경 파일 ESLint 통과. 로컬 WSL Playwright는
  `ubuntu26.04-x64` 브라우저 다운로드 미지원으로 browser 실행이 막힘.
- **다음 한 작업**: 보안 스캔 → PR/CI → 머지 → n150 배포 → live UI e2e와 스크린샷 검증.

## 2026-07-09 (codex) — feature weather API 경로 정리 로컬 구현 완료

- **완료(로컬)**: 직전 weather history API를 별도 `/v1/weather/*`가 아니라 feature API 하위
  `/v1/features/weather/forecast`, `/v1/features/{feature_id}/weather/forecast`,
  `/v1/features/weather/alerts`로 노출하도록 후속 수정했다. 기존
  `/v1/features/{feature_id}/weather` card API는 유지.
- **검증**: API/OpenAPI unit 7 passed, ruff 변경 Python 파일 clean, mypy --strict API package
  36 source clean, import-linter 4 kept, OpenAPI drift check 통과, admin/user-client
  gen:types:check/type-check 통과, frontend lint 0 errors(기존 warning 4), `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 → PR 생성 → CI green 확인 → 머지.

## 2026-07-09 (codex) — 공개 Weather API와 3년 이력 보존 로컬 구현 완료

- **완료(로컬)**: 3번안 기준으로 외부 시스템용 weather forecast/history API를 추가했다. 좌표/feature
  기준 nearest weather anchor forecast timeline, KMA 기상특보 이력 조회, weather value 3년 보존
  정책(ADR-062), 0043 조회 인덱스, Feature 지도 weather marker 예보 라벨을 반영했다. 기존
  `/v1/features/{feature_id}/weather` card API는 유지.
- **검증**: API unit/OpenAPI 8 passed, weather_repo integration 9 passed, ruff 변경 파일 clean,
  mypy --strict 135 source clean, import-linter 4 kept, OpenAPI drift check 통과, frontend/user-client
  gen:types:check/type-check 통과, frontend lint 0 errors(기존 warning 4).
- **다음 한 작업**: 보안 스캔 후 PR 생성 → CI green 확인 → 머지.

## 2026-07-09 (codex) — Claude Code PR #638 2차 사후 리뷰 후속 완료

- **완료(#656, #655 closed)**: closed/superseded PR(#635~#637) 포함 Claude Code 관리 UI 통합
  PR #638을 2차로 재검토해 `/admin/files` 검색 안내와 backend `q` 검색 범위 불일치를 확인하고
  #655로 이슈화했다. `file_registry.list_managed_files(q=...)`가 `path/provider/dataset_key`를
  함께 검색하도록 수정하고 통합 테스트 케이스를 추가했다. #638에는 2차 리뷰 코멘트를 남겼고
  #656은 CI green 후 squash merge했다.
- **다음 한 작업**: 새 지시 대기.

## 2026-07-09 (claude) — Feature 지도 저zoom 서버측 region 클러스터 완결 (#649, #12 잔여)

- **완료(#653, 배포+라이브 검증)**: 저zoom(≤13) Feature 지도가 기존 `/v1/features/in-bounds`의
  서버측 행정구역 rollup 클러스터를 소비. 백엔드는 이미 완비(zoom 유도), 프론트가 `zoom` 미전송이
  원인이었음 → `useFeatureClustersInBbox` + `VWorldServerClusters` + `clusterMode` 분기 추가.
- **라이브 검증(n150 Playwright)**: z6.5 17 sido("968,624건 집계") → z10 sigungu → z12 읍면동 밴드
  refine, z13.7 초과 시 개별 모드("264건 표시")로 전환. z≤13 `/in-bounds` 1회 vs z>13 tiled `/features`.
  저zoom 968,624건 → 17행 fetch(즉시 로드). #12 잔여 인프라 해소.
- **다음 한 작업**: 사용자 배치(10건) + #12 잔여까지 전량 종료. 새 지시 대기.

## 2026-07-09 (codex) — Claude Code PR 사후 리뷰 후속 수정 로컬 완료

- **완료**: #632~#638(닫힌 #635~#637 포함) current main 사후 리뷰 후 남은 작은 회귀 2건
  (#650, #651)을 수정했다. price card는 stale-only feature에서도 `latest_at`을 history 기준으로
  보존하고, managed file registry는 `orphan→active` 복귀를 `reappeared` 이벤트로 기록한다.
- **검증**: 관련 통합 6 passed, 파일 레지스트리 단위 28 passed, 변경 파일 ruff clean,
  변경 source mypy --strict clean.
- **다음 한 작업**: 리뷰 코멘트/이슈 생성 → PR 생성 → CI green 확인 → 머지.

## 2026-07-09 (claude) — 사용자 버그/기능 배치(10건) 완결

- **완료(9건 코드+배포)**: #10 파일-500(#640) · #18 log enable · #14 키 복사 · #17 curated dedup(#641)
  · #11 feature 지도 dedup(#642) · #19 REST dedup(#643) · #16 title 멀티필터(#644) · #13 마커 좌표(#645)
  · #15 concierge 테마 source(#646/#647, ADR-061). #15는 prod sync 1회 실행 완료 → 31 테마·31 rule·
  1944 curated feature 자동 게시(멱등).
- **완료(#12 클라이언트 개선분)**: `useFeaturesInBbox` outer key viewport 서명 coarsen + staleTime
  정렬로 tile 내부 작은 pan을 순수 cache hit화 (PR 진행 중, base=main).
- **잔여 인프라 과제(#12)**: 필터 적용·대형 pan 지연 = 서버 병목(휴게소 4코어 밀집 bbox tile 조회).
  근본 해법 = 저zoom 서버측 region clustering(`/v1/features` `cluster_unit` 활용) 또는 MV/박스 증설.
  UX(군집 방식) 변경이라 사용자 확인 후 별도 스코프 권장.
- **다음 한 작업**: #12 클라이언트 PR CI green → 머지 → n150 ui 재빌드 배포. 이후 저zoom 서버측
  clustering을 별도 태스크로 착수 여부 결정.

## 2026-07-07 (claude) — 사용자 버그/기능 배치(10건) 진행 중

- **완료**: 파일 관리 목록 500(asyncpg AmbiguousParameterError) root-cause+수정+통합 테스트
  (PR 예정). 라이브 prod 재현·검증.
- **조사 완료(미착수)**: Feature/Curated 지도 중복(fetch dedup은 있음 → 렌더 계층 or curated
  dedup 부재), 지도 응답성(map move/filter debounce 없음), weather 좌표(KMA 격자중심+마커),
  concierge google/naver/kakao 키 복사(필드 존재, 값만 n150 override 필요), 큐레이션 정합성(스코프
  큼 — 사용자 확인 필요), 큐레이션 title 멀티콤보 필터, 운영 log enable
  (`KOR_TRAVEL_MAP_API_API_CALL_LOG_ENABLED=false`→override).
- **다음 한 작업**: 파일-500 PR CI green → 머지 → n150 api 재빌드 배포 → 나머지 배치 항목을
  우선순위대로(퀵윈: curated dedup·debounce·log enable·키 복사; 조사필요: 지도 중복 라이브 디버깅;
  스코프확인: 큐레이션 정합성).

## 2026-07-06 (claude) — 관리 feature 검색 fast-path 로컬 완료

- **완료**: 완전한 feature_id 검색을 `f.feature_id = :q_exact`(PK index) fast-path로 처리
  (14~60s → 즉시). `_feature_id_exact_query` 정규식 감지 + `_admin_features_sql(exact_id=True)`
  조건부 q-절. backend 한정, API 계약 불변. 부분 검색어는 기존 ILIKE 유지.
- **검증**: unit 3건 + t212d EXPLAIN 통합 추가. 로컬 CI-parity(ruff/mypy --strict/lint-imports/
  pytest unit+lint 1168 green). 통합(testcontainers PostGIS)은 CI에서 실행.
- **다음 한 작업**: PR(base=main) CI green → 머지 → n150 api 컨테이너 재빌드 배포
  (`kor-travel-docker-manager` compose) → `/v1/admin/features?q=<full id>` 즉시 응답 확인.

## 2026-07-05 (claude) — 관리 UI 개편 D: 파일 레지스트리·추적 UI 로컬 완료 (PR-B 위 스택)

- **완료**: 파일 레지스트리(`ops.managed_files`+events, 0040) + hook 계측 + 소유권 분리 스캐너
  (api=backup_root, dagster=mois/S3 `managed_file_scan` job) + `/v1/admin/files` API + `/admin/files`
  추적 UI(요약 칩·필터·목록·provenance 상세) + nav(시스템 그룹) + e2e(nav 21·scenario·mocked smoke) + docs.
- **검증**: Python ruff/mypy --strict/lint-imports(4 kept)·dagster defs+21 test·router 7 test green;
  openapi/user·types.ts 재생성; 프론트 type-check·eslint 0 error·vitest 57 green. Playwright 미실행(Windows/n150 런).
- **주의**: 0040이 notice #633의 0040과 충돌 → **최종 통합 시 coordinator가 merge-migration 추가**.
- **다음 한 작업**: PR(base=`feat/admin-overhaul-b-nav`) CI green → A→B→C→D 스택 + notice(#633)·opinet(#632)
  순차 머지 → n150 배포 → docker-playwright live UI e2e 전체 green 확인 후 최종 머지.

## 2026-07-04 (claude) — 관리 UI 개편 A+B 로컬 완료 (PR 스택)

- **완료**: PR-A(공용 컴포넌트 16종+검증 헬퍼+파일럿, #634) 위에 PR-B(nav 4그룹·헤딩 정본·
  크로스링크/딥링크 전체·브레드크럼 4곳·spec 정합화 29파일) 스택 구현.
- **검증**: tsc clean · eslint 0 errors · vitest 57 passed.
- **다음 한 작업**: PR-C(페이지 이관+validation/assist+텍스트 절약) → 통합 브랜치 n150 배포 →
  docker-playwright live e2e 전체 green 확인 → A/B/C + notice(#633) + opinet(#632) 순차 머지.

## 2026-07-03 (claude) — 큐레이션 관리 UX 개편 로컬 구현 완료

- **완료**: 큐레이션 관리 화면을 라이프사이클 스트립(상태 칩=필터)+후보 검토/소스 규칙 탭으로
  재구성하고 채택/채택 해제/보관/결과 적용/규칙 적용 동사 체계·상태 전환 토스트(채택은 필터 점프)·
  행 단위 pending·bulk 집계·서버 q 검색·editor dirty 가드·재사용 정책 opt-out·규칙 적용 confirm을
  구현했다. backend 변경 없음.
- **e2e**: mocked 신규 12 시나리오 + curated 전 스펙(live 포함) locator 이행. live write 스펙의
  기존 stale 영문 헤딩도 수정.
- **검증**: tsc(src+e2e) clean, eslint 변경 파일 0 errors. Playwright 실행은 하지 않음.
- **다음 한 작업**: PR CI green 확인 → n150 배포 → live UI e2e(read-only + E2E_CURATED_WRITE) 실행
  → 결과 확인 후 머지.

## 2026-07-02 (codex) — Notice/Curated Feature 지도 후속 수정 로컬 구현 완료

- **완료(notice)**: KREX notice 자연키/지도 최신값 lineage에서 `series_no`를 제외하고, 원천 시간이
  없으면 최초 probing 시각을 detail 시작 시간으로 저장하도록 바꿨다. payload 변경 재수집은 최초
  probing 시작 시각을 보존한다.
- **완료(Feature 지도)**: bbox/zoom query key와 tile zoom 계산, GeoJSON source data 변경 후 marker
  갱신 예약을 보강해 kind 변경/확대축소 반영성을 높였다.
- **완료(curated 지도)**: `/curated-features` 지도/테이블 화면을 추가했다. 필터는 POI명, 테마명,
  제목, 데이터소스이며 실제 feature 정보를 주 표시로 사용한다.
- **완료(curated 표시)**: 기존 큐레이션 관리 화면과 상세 화면도 `display_title`이 아닌 `feature_name`
  중심으로 보여주도록 정리했다.
- **검증**: KREX/curated repo/routes unit 48 passed, feature_repo notice integration 2 passed,
  전체 ruff, `mypy --strict src`, import-linter, OpenAPI drift check, frontend gen:types:check/type-check,
  user-client gen:types:check/type-check, frontend lint(기존 warning 4건), frontend production build
  통과. mocked Playwright e2e는 WSL Ubuntu 26.04 Chromium install 미지원으로 실행 불가.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지, n150 반영과 live UI e2e를 진행한다.

## 2026-07-02 (codex) — 큐레이션 feature theme/title 편집 로컬 구현 완료

- **완료(기본 제목)**: 정부·공공기관 source rule 후보의 `display_title` 기본값을 provider 이름으로
  채우고, concierge YouTube 후보는 `youtube.source_title`을 우선 쓰도록 테스트를 보강했다.
- **완료(admin 편집)**: curated feature patch API와 Feature 큐레이션 편집 패널에서 `theme_id`와
  `display_title`을 함께 수정할 수 있게 했다. source rule 재적용은 기존 제목을 덮지 않는다.
- **검증**: curated repo unit 6 passed, curated repo integration 7 passed, 전체 pytest 1380 passed,
  전체 ruff, `mypy src/kortravelmap`, import-linter 4 contracts, OpenAPI drift check,
  frontend gen:types:check/type-check/lint(기존 warning 4건), Windows Playwright fallback
  route-mocked curated mutations e2e 21 passed, frontend production build 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지, n150 반영과 live UI e2e를 진행한다.

## 2026-07-02 (codex) — 큐레이션 theme set 확장과 Source rules job 연결 로컬 구현 완료

- **완료(테마 seed)**: 기본 큐레이션 theme set에 계절별 여행지 4종과 지역별 여행지 6종을 추가했다.
  확장 테마는 `public` visibility와 `default_curated=false`로 seed한다.
- **완료(UI)**: Feature 큐레이션 `Source rules` 패널에 `관련 job 실행` 버튼을 추가했다. 버튼은
  `curated_features_refresh_daily_schedule`이 강조된 작업 자동화 화면으로 이동하며, 운영자는 해당
  row의 `즉시 실행`으로 관련 job을 바로 실행한다.
- **완료(검증 보강)**: 확장 테마 seed와 `kor-travel-concierge-youtube/youtube_place_candidates`
  import/curated snapshot 흐름을 통합 테스트에서 함께 확인한다.
- **검증**: curated repo integration 7 passed, Dagster concierge fetcher targeted 5 passed/72 deselected,
  curated refresh schedule 등록 1 passed, 전체 ruff, `mypy src/kortravelmap`, import-linter 4 contracts,
  frontend type-check, frontend lint(기존 warning 4건), frontend build, Windows Playwright targeted e2e
  2 passed. WSL Playwright는 Chromium 바이너리 부재로 실행 전 실패했다.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지, n150 반영과 live UI e2e를 진행한다.

## 2026-07-02 (codex) — Feature 지도 notice 최신 표시/이력화 로컬 구현 완료

- **완료(UI)**: Feature 지도 겹친 점 선택 팝업을 선택 메뉴처럼 보이도록 정리했다. 기존 `겹친 지점 N개`
  텍스트와 선택 흐름은 유지한다.
- **완료(데이터)**: `provider_sync.source_records.last_seen_at`을 추가하고, 동일 source payload 재수집은
  Feature 본문/version을 갱신하지 않고 마지막 확인 시각만 갱신한다.
- **완료(notice)**: KREX 교통공지 notice는 사건 단서 기반 stable key로 같은 사건의 payload 변경을
  같은 Feature에 누적한다. Feature 지도 bbox 조회는 같은 notice lineage의 최신 feature만 표시한다.
- **완료(상세)**: admin feature 상세 API/source row에 `last_seen_at`을 노출하고, notice 상세 화면에
  `Notice History` 표를 추가했다. OpenAPI와 frontend generated types를 갱신했다.
- **검증**: targeted unit/API 63 passed, Dagster runner/load enrichment 11 passed, integration 28 passed,
  perf EXPLAIN 7 passed, frontend type-check/gen:types:check/OpenAPI drift/frontend lint(기존 경고 4건)/
  frontend unit 45 passed, frontend production build 통과(필수 env 로컬값 지정), 전체 pytest 1378 passed,
  전체 ruff, `mypy src/kortravelmap`, import-linter 4 contracts, `git diff --check` 통과.
- **미검증**: mocked Playwright e2e는 WSL Playwright Chromium 미설치 + Ubuntu 26.04 미지원으로 실행 불가.
  Windows Chrome fallback launch도 remote debugging pipe 문제로 실패했다.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 작성 폼 장소 종류 최상위화 로컬 구현 중

- **완료(UI)**: 새 Feature 작성과 변경 요청 작성 화면에서 `장소 종류(place_kind)`를 상세 섹션에서
  기본 정보 섹션으로 올렸다. `Feature 종류`가 `place`일 때만 표시한다.
- **완료(UI)**: `area`/`route` Feature는 수동 생성·수정 대상이 아니므로, 변경 요청 작성 화면에서
  기존 `area`/`route` Feature를 불러오면 경고를 표시하고 요청 생성을 막는다.
- **검증**: frontend type-check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit
  45 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 지도/주소 코드 후속 보강 로컬 구현 완료

- **완료(UI)**: 겹친 Feature 점 마커 선택 팝업이 즉시 닫히지 않도록 마커/클러스터 클릭 이벤트와
  팝업 닫힘 동작을 보정했다.
- **완료(UI)**: 새 Feature 작성과 Feature 변경 요청 작성의 시도/시군구/법정동/행정동 코드 입력을
  같은 자동검색 팝업으로 통일하고, 코드 길이 검증을 추가했다.
- **완료(UI)**: 새 Feature 작성 화면의 좌표 지도 높이를 오른쪽 보조 위젯에 맞춰 늘리고,
  역지오코딩/주소 후보 선택 시 주소 검색 필드와 선택 강조 상태를 갱신한다.
- **검증**: frontend type-check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit
  45 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 운영 경로 일원화 로컬 구현 완료

- **완료(UI)**: Feature 큐레이션/중복 검토/보강 검토/갱신 요청 화면을
  `/admin/features/...` 아래로 이동했고, 기존 경로는 새 경로로 redirect한다.
- **완료(API)**: 관련 admin API를 `/v1/admin/features/...` 하위로 노출하고 OpenAPI 정본은 새
  경로만 포함하도록 했다. 기존 API path는 호환 alias로 남겼다.
- **완료(UI 통일)**: 중복 검토 테이블과 상세 다이얼로그를 보강 검토 화면 기준으로 맞추고,
  완료 row에서도 `detail` 버튼으로 상세 비교를 열 수 있게 했다.
- **검증**: ruff targeted clean, OpenAPI drift check, frontend type-check, frontend
  gen:types:check, frontend lint(기존 경고 4건), frontend unit 45 passed, API router targeted
  35 passed, provider/ops targeted 23 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 작성/변경 요청 폼 공용화 로컬 구현 완료

- **완료(로컬)**: 새 Feature 작성 화면과 변경 요청 작성 화면의 기본 정보·좌표·주소·상세 입력 섹션을
  공용 컴포넌트로 정리했다.
- **완료(UI)**: 변경 요청 작성 화면은 `변경 요청 작성` 카드 바로 아래에 `기본 정보`를 표시한다.
  좌표가 없어도 기본 한국 본토 중심 지도 뷰를 렌더링하고, 지도 아래 빈 안내 영역은 제거했다.
- **완료(UI)**: 변경 요청 작성 화면의 본문 시군구 입력은 새 Feature 작성 화면과 같은 자동검색 필드를
  사용한다. 후보 선택 시 주소·행정코드·좌표를 함께 채운다.
- **검증**: frontend type-check, frontend lint(기존 경고 4건), frontend unit 45 passed,
  production build 통과(`NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` 임시 지정), `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green을 확인한다.

## 2026-07-01 (codex) — route/Feature 지도/OpiNet 유가 회귀 수정 배포 완료

- **완료**: PR #619(`fix/route-marker-price-regressions`)는 CI green 후 main에 머지했고, n150에
  API/UI/Dagster/Dagster daemon을 재빌드·재시작했다.
- **완료(코드)**: KNPS `knps_trails`는 `비매칭코스` 정확 일치뿐 아니라 변형 표기와 매칭 실패 상태값도
  제외한다. Feature 지도 숫자 클러스터는 더 이상 확대되지 않으면 기존 겹침 선택 팝업을 연다.
  OpiNet `low_top_area`는 시도별 시군구 round-robin으로 호출 상한 전 전국 표본을 먼저 확보한다.
- **완료(설정)**: `api`/`dagster`/`dagster-daemon` compose env에 `KOR_TRAVEL_MAP_OPINET_SCOPE_*`
  매핑을 명시했다.
- **검증**: KNPS provider 53 passed, Dagster provider fetcher 75 passed/1 skipped, Docker Dagster
  runtime 9 passed, targeted ruff, frontend type-check, frontend lint(기존 경고 4건), frontend unit
  45 passed, compose config, `git diff --check`.
- **완료(후속 보강)**: n150 수동 유가 materialize 중 OpiNet root area 응답의 invalid 시도 코드가 자식
  조회로 들어가 retry되는 것을 확인했고, PR #620에서 유효 OpiNet 시도 코드만 자식 area 조회 대상으로
  쓰도록 보강했다.
- **완료(배포 검증)**: PR #620도 CI green 후 main에 머지하고 n150에 재배포했다. Alembic head, map
  컨테이너 health, 공개 UI 로그인 POST, Dagster hotfix 코드 반영을 확인했다. OpiNet price asset
  materialize는 `RUN_SUCCESS`, 운영 price feature는 15개 시도 코드/2,624건, 활성 `비매칭` route는
  0건이다.
- **검증(Windows live e2e)**: Feature 지도 마커 렌더와 클러스터 클릭 zoom 증가 targeted live run은
  인증 setup 포함 3 passed. 실제 점 마커 클릭 상세 패널 round-trip 테스트는 운영 타일/응답 대기에서
  5분 timeout이 나 후속 검증 대상으로 남았다.
- **다음 한 작업**: 실제 점 마커 클릭 상세 패널 live round-trip timeout 원인을 별도 조사한다.

## 2026-06-30 (codex) — 세션 개선 요청 후속 반영

- **완료**: PR #615는 문서 복기 PR로 재구성한 뒤 merge commit
  `ecf638701761441b94846350864711ef43f78c69`로 병합됐다.
- **진행 중**: 병합된 `main` 기준 후속 브랜치 `fix/session-improvement-followups`에서 세션 중 요청됐던
  MOIS/Dagster/UI 개선 누락분을 다시 반영했다.
- **완료**: MOIS bulk/resource/feature update runner가 `mois_localdata_source_sync`를 먼저 실행하도록
  연결했고, 고속도로 교통공지 notice schedule은 10분 주기로 바꿨다.
- **완료**: 중복/보강 검토 다중 combobox 필터, 신규 Feature 시군구 자동검색, Dagster 실행 기록
  collapsible/시각 보정/시작·중지 spinner, 적재 작업 한국어화·payload 시각화, 로그 `live live` 중복
  제거, Feature 지도 초기화 버튼을 보강했다.
- **검증**: Dagster 대상 pytest 37 passed, ruff, compose config, frontend type-check, frontend
  lint(기존 경고 4건), frontend unit 45 passed, Dagster mypy 19 source, import-linter 4 contracts kept.
- **다음 한 작업**: 보안 스캔 후 후속 PR을 올리고 CI green을 확인한다. 머지 뒤 n150 반영과 live UI e2e를
  진행한다.
## 2026-06-30 (claude) — MOIS WAL 사고 후속 하드닝 (#614 리뷰 반영)

- **완료**: `mois_source_sync.py` — checkpoint를 AUTOCOMMIT + busy 경고로 관측 가능화, 빈 slug
  fail-fast, `sync_kind` distinct 합산, WAL checkpoint 호출 회귀 spy 테스트 추가.
  (상세: journal 2026-06-30 (claude))
- **다음 한 작업**: MOIS 재가동은 `docs/runbooks/docker-app.md` §MOIS 재가동 체크리스트대로 — fix 배포
  후 source sync 1회 수동 materialize로 `*-wal`·디스크 헤드룸이 bound됨을 확인한 뒤 스케줄 재가동.
  provider(python-mois-api) batch별 commit과 디스크 영구 가드는 별도 후속 이슈.

## 2026-06-30 (codex) — PR #615 보존 브랜치 정리와 복기 문서화

- **완료**: n150 UI image inspect 시각은 UTC임을 runbook에 명시했다. 예:
  `2026-06-30T10:49:30Z`는 `2026-06-30 19:49:30 KST`이며, 이 시각 이후 UI 변경은 별도 rebuild/recreate
  전까지 반영되지 않는다.
- **완료**: UI 최신 여부 확인 절차를 image created/started 시각, 실제 `.next` bundle marker,
  로그인된 public DOM marker, route/cache-buster 확인으로 분리했다.
- **완료**: git worktree metadata가 깨졌을 때 바로 `git add -A`하지 말고 repair → status/stat/name-only
  확인 → 관련 파일 stage 또는 draft 보존 PR로 전환하는 절차를 문서화했다.
- **완료**: PR #615의 기존 보존 스냅샷은 현재 `main` 대비 회귀가 있어 로컬
  `backup/pr615-before-cleanup-20260630`에 남기고, PR head는 현재 `main` 위에 문서 보강만 남기도록
  재구성했다.
- **다음 한 작업**: PR #615의 CI와 리뷰를 확인한다. 머지는 별도 지시 전까지 진행하지 않는다.

## 2026-06-30 (codex) — Feature 변경/작업 자동화 운영 UI n150 배포

- **완료**: `/admin/dagster` 작업 자동화 화면에서 스케줄 cron 수정, 기본값 복귀, 시작/중지, 즉시 실행
  명령을 수행할 수 있게 했다.
- **완료**: Dagster asset 한국어 표기 상수를 추가하고, UI는 한국어명을 우선 표시하며 코드 레벨 이름은
  하단/작은 글씨/말줄임/툴팁으로 표시한다.
- **완료**: Feature 변경 요청 작성 화면과 검수 화면을 분리했다. 작성 화면은 form 중심, 검수 화면은
  목록/필터/상세/승인·반려 중심으로 정리했다.
- **완료**: Admin UI 메뉴명과 live e2e 기대값을 한글 UI에 맞췄고, 모바일 메뉴는 선택 항목이
  중앙으로 오도록 스크롤된다.
- **배포**: n150에서 API/UI/Dagster/Dagster daemon을 재빌드·재시작했고 Alembic head
  `0037_dagster_schedule_overrides`와 UI 로그인 POST를 확인했다.
- **검증**: n150 공식 Playwright Docker image로 Dagster 스케줄 write live spec 3 passed / 1 skipped,
  Feature 변경 write live spec 3 passed, misc live smoke 182 passed를 확인했다.
- **검증**: 로컬 frontend `type-check`, `lint`(기존 경고 4개), 관련 pytest 22건, ruff,
  `git diff --check` 통과.
- **다음 한 작업**: PR 전 보안 스캔과 CI green 확인 후 머지한다.

## 2026-06-29 (codex) — Feature change requests 편집 UX 보강

- **완료**: `/admin/features` detail에서 `편집` 링크로 change request update form을 열고, 대상
  feature detail을 prefill하도록 연결했다.
- **완료**: `/features/[featureId]` Feature 상세의 `수정` 링크도 같은 update prefill 경로로
  연결하고, prefill 시 주소/행정코드/관계 id/좌표 정밀도/전화·행사·URL 값을 개별 필드로 채운다.
- **완료**: change request form을 요청/기본 정보/위치·마커/payload 구조로 정리하고, category,
  marker icon, marker color를 dropdown으로 바꿨다.
- **완료**: 위치/마커 다이얼로그를 추가해 지도 우클릭 좌표 선택, marker icon/color 선택,
  모바일 오래누르기 좌표 선택, `적용`/`취소`, reverse geocoder 기반 시군구 코드·이름 표시를 지원한다.
- **완료**: `sigungu_code` 입력은 숫자 prefix와 한글 검색어 모두 geocoder 후보를 즉시 보여주며,
  실제 코드가 있으면 시군구명을 표시한다.
- **완료**: enrichment/dedup review 상세 다이얼로그 지도는 두 좌표가 모두 보이도록 bounds fit을
  적용했다.
- **완료**: Admin UI 사이드 메뉴를 한글 중심으로 정리했다. Feature 관련 메뉴는 `Feature 지도`,
  `Feature 목록`, `Feature 변경`처럼 같은 접두어로 맞췄다.
- **완료**: Playwright UI/e2e는 WSL에서 실행하지 않고 n150을 1순위, Windows 호스트 브라우저를
  2순위 fallback으로 쓰도록 개발 환경 문서와 config 주석에 명시했다.
- **검증**: frontend `type-check`, `type-check:e2e`, `lint`(기존 경고만), `test` 45건, `build`,
  `git diff --check` 통과. n150 배포 후 targeted live UI e2e는 인증 setup과 read/edit UI 시나리오
  2 passed, write opt-in spec 1 skipped로 통과했다.
- **다음 한 작업**: PR 전 보안 스캔과 CI green 확인 후 머지한다.

## 2026-06-29 (codex) — tasks 백로그 정리

- **완료**: `T-229-buildx`는 사용자 결정에 따라 추가 추적하지 않기로 하고 열린 백로그에서 제거했다.
- **완료**: `T-AUDIT-0616` F-01 옵션 A는 ADR-058의 옵션 B(re-key 없음, geocoder 필수화) 채택으로
  필수 진행 백로그에서 제외했다.
- **완료**: `docs/tasks.md`의 열린 항목은 보류/결정 대기인 `T-101`만 남겼다.
- **다음 한 작업**: 즉시 실행 백로그 없음. `T-101`은 Materialized View 도입 조건이 생길 때 재검토한다.

## 2026-06-29 (codex) — n150 live e2e backup runner tracked 전환

- **진행 중**: n150 local `live-e2e-backup-runner`를 repo tracked 파일로 전환해 다음 배포/rsync에서
  runner가 다시 삭제되지 않게 한다.
- **완료**: runner는 민감정보 없이 API/Dagster 컨테이너 DSN과 host-network PostgreSQL client,
  RustFS volume archive 경로를 사용하도록 작성했다.
- **완료**: `swap.sh`는 자동 hot-swap apply를 거부한다.
- **검증**: `bash -n live-e2e-backup-runner/{backup,restore,swap}.sh` 통과. tracked runner 내용을
  n150에 반영한 뒤 targeted `backups-restore.live.spec.ts`는 8 passed / 1 skipped로 통과.
- **다음 한 작업**: 보안 스캔/CI green 후 PR을 머지하고 n150 untracked runner를 tracked 파일로 치환한다.

## 2026-06-29 (codex) — n150 full admin live e2e 완료

- **완료**: PR #596은 CI green 후 squash merge됐고, n150 운영 디렉터리는 `main@860a987`로
  동기화됐다.
- **완료**: n150 local `live-e2e-backup-runner`를 복구하고 docker-manager 배포 topology에 맞춰
  backup/restore runner를 조정했다. targeted backup/restore live spec은 실제 backup execute와
  staging restore execute 포함 8 passed / 1 skipped로 통과했다.
- **완료**: 최종 full live e2e `playwright-live-full-20260629T054002Z`는 status 0으로 종료했다.
  결과는 1,886 passed / 2 flaky / 22 skipped, 실패 0건이다.
- **메모**: flaky 2건은 full 부하 중 일시적인 `Failed to fetch`/`ERR_NETWORK_CHANGED`였고 둘 다
  retry #1에서 통과했다.
- **다음 한 작업**: 별도 기능 작업 전에는 남은 flaky 2건을 낮은 우선순위 안정화 후보로만 추적한다.

## 2026-06-29 (codex) — feature-update live spec refreshable 계약 정합화

- **완료**: PR #595는 CI green 후 squash merge됐고 n150 운영 디렉터리/컨테이너는 `main@9af83b1`로
  재배포됐다. Alembic head, UI auth hash, 로그인 POST 200 + Set-Cookie를 확인했다.
- **진행 중**: full live e2e 전 점검에서 feature-update live write spec이 PR #595의
  refreshable provider/dataset 검증과 충돌하는 bogus provider 전략을 쓰고 있음을 확인했다.
- **진행 중**: spec을 실제 refreshable pair + 극소 반경 + `request_id` short link row 식별로
  정합화했다. 다중 provider×dataset 가정은 단일 provider의 다중 refreshable dataset 검증으로
  바꿨다.
- **검증**: frontend `type-check:e2e`, `git diff --check` 통과.
- **다음 한 작업**: 이 e2e spec 보정을 PR/CI/머지하고 n150에 반영한 뒤 targeted live smoke와 full
  live e2e를 실행한다.

## 2026-06-29 (codex) — Claude 후속 이슈 #589~#594 정리

- **완료**: feature-update enqueue 경로는 `catalog_refreshable_entries()` 기준으로
  non-refreshable provider/dataset 조합을 422로 거절한다.
- **완료**: dedup/enrichment review list 응답은 `OffsetMeta`로 분리해 `meta.page.next_cursor`
  영구 null 직렬화를 제거했고, OpenAPI/admin generated type을 갱신했다.
- **완료**: backup/restore/swap execute live spec에서 죽은 UI 토글을 제거하고 swap execute도
  `/api/proxy` 직접 POST로 통일했다.
- **완료**: #590/#591/#592의 테스트 스타일·관심사 분리·문서 stale 문구를 반영했다.
- **검증**: 관련 pytest 56건, `ruff`, OpenAPI drift, admin/user generated type drift,
  frontend `type-check`/`type-check:e2e`, 대상 mypy, import-linter 통과. 로컬 mocked Playwright는
  현재 WSL 배포판 미지원으로 Chromium 설치 단계에서 중단.
- **다음 한 작업**: 이 변경과 n150 long-tail e2e 안정화 변경을 PR/CI/머지한 뒤 n150에 반영하고
  full live e2e를 재실행한다.

## 2026-06-29 (codex) — n150 full live e2e long-tail 안정화

- **완료**: PR #588을 CI green 후 머지했고, n150 UI는 새 image로 재빌드/재생성했다.
- **완료**: n150 full live e2e 1차 재실행은 1,869 passed / 12 flaky / 17 skipped / 7 failed /
  5 did not run으로 종료했다.
- **완료**: 실패 7건은 strict duplicate locator, import-jobs navigation `ERR_NETWORK_CHANGED`, ETL
  provider catalog loading wait, enrichment deep pagination response wait로 분해했고 spec 안정화를 적용했다.
- **검증**: 실패 축 targeted 재실행은 12 passed로 통과했다.
- **다음 한 작업**: 안정화 변경을 PR/CI/머지한 뒤 full n150 live e2e를 다시 실행한다.

## 2026-06-29 (codex) — Enrichment review detail live smoke 클릭 안정화

- **완료**: PR #586으로 backup/restore destructive 실행 경로 분리 변경을 CI green 후 머지했다.
- **완료**: n150 targeted backup/restore live spec은 실제 backup execute와 restore execute를 포함해
  8 passed / 1 skipped로 통과했다.
- **완료**: targeted enrichment review live spec은 actions 컬럼 `detail` 버튼을 통해 detail GET과
  상세 다이얼로그/지도 smoke까지 3 passed로 통과했다.
- **다음 한 작업**: UI/spec 변경을 PR/CI/머지한 뒤 full n150 live e2e를 재실행한다.

## 2026-06-29 (codex) — Backup destructive live e2e 실행 경로 분리

- **진행 중**: n150에서 직접 `/api/proxy` backup/restore execute는 200 completed로 통과했지만,
  Playwright UI destructive button 응답 대기만 장시간 닫히지 않는 현상을 확인했다.
- **진행 중**: backup/restore plan은 Admin UI 버튼 경로로 유지하고, 실제 destructive execute는 인증된
  API 요청 후 Admin UI 목록 반영을 확인하는 end-to-end 시나리오로 분리했다.
- **다음 한 작업**: frontend e2e type-check/CI/PR 머지 후 n150 targeted backup/review와 full live e2e를
  재실행한다.

## 2026-06-29 (codex) — Backup live e2e 상태 배지 assertion 안정화

- **진행 중**: n150 targeted backup live e2e에서 `/admin/backups` 기본 옵션 테스트가
  `plan only`/`execute enabled` 상태 배지의 순간 상태를 분기형으로 읽다가 실패했다.
- **진행 중**: 해당 assertion을 현재 렌더링된 두 상태 배지 중 하나를 단일 locator로 확인하도록
  단순화했다.
- **다음 한 작업**: frontend e2e type-check와 CI를 통과시켜 PR 머지 후 n150에 반영하고 backup/review
  targeted live e2e를 재실행한다.

## 2026-06-29 (codex) — n150 live e2e 실패 보강

- **완료**: n150 full live e2e write 실행에서 백업 command 시작 실패와 enrichment review 조회 500을
  재현했고, 두 실패를 각각 API 503 계약화와 거리 점수 clamp로 보강했다.
- **완료**: backup/restore/swap command의 `asyncio.create_subprocess_exec` 시작 실패를
  `BACKUP_COMMAND_UNAVAILABLE` 문제 응답으로 반환한다.
- **완료**: enrichment review 목록/상세 SQL은 35km 이상 후보의 `spatial_score`를 0으로 고정해
  numeric underflow 없이 조회된다.
- **검증**: admin backup router 단위 테스트 12건, enrichment review integration 대상 2건, 변경 파일
  ruff 통과.
- **다음 한 작업**: PR을 올리고 CI green 후 머지한 뒤 n150에 재배포하고 backup/review targeted e2e와
  full live e2e를 다시 실행한다.

## 2026-06-29 (codex) — #572 Enrichment review 지도 비교 surface 일원화

- **완료**: enrichment review 목록의 `mapReviewId` state, 행별 `지도` 버튼, 별도
  `enrichment coordinate map` section을 제거하고 상세 다이얼로그 지도만 남겼다.
- **완료**: mocked/live e2e는 목록 인라인 지도 대신 행 클릭 상세 다이얼로그 지도와 `지도` 버튼 부재를
  검증하도록 갱신했다.
- **검증**: `type-check`, `lint`(기존 6 warnings), production `build`, `git diff --check`,
  Docker Playwright 수동 시나리오(로그인 → enrichment review 목록 mock → 행 클릭 → 상세 다이얼로그 지도)
  통과.
- **다음 한 작업**: PR을 올리고 CI green 후 머지해 #572를 닫는다.

## 2026-06-29 (codex) — #571 Dedup/Enrichment review page-only 계약 정리

- **완료**: `GET /v1/admin/dedup-reviews`와 `GET /v1/admin/enrichment-reviews`의 이중
  pagination 계약을 제거해 `cursor` query parameter 없이 `page`/`page_size`/`meta.page.total`만
  사용하도록 바꿨다.
- **완료**: repository의 review cursor decode/encode 경로, `next_cursor` 산출, UI의 죽은
  `nextCursor` fallback을 삭제했다.
- **검증**: 변경 파일 `ruff`, 대상 mypy 3파일, OpenAPI drift check, frontend `gen:types:check`/
  `type-check`/`lint`(0 errors, 기존 warnings 6개), 대상 pytest 29건을 통과했다.
- **다음 한 작업**: PR을 올리고 CI green 후 머지해 #571을 닫는다.

## 2026-06-29 (codex) — #570 Linux/WSL 개발 실행 정책 문서 정합성 보정

- **진행 중**: `docs/agent-guide.md`의 Windows `git.exe` 예시와 Windows Git 허용 문구를 제거하고,
  Linux/WSL `git`·`gh`·`codegraph` 단일 실행 기준으로 §9를 재작성했다.
- **진행 중**: `CLAUDE.md`와 `docs/debug-ui-admin-workflows.md`의 Windows Playwright 표준 문구를
  n150 Linux 우선, Windows 호스트 브라우저 fallback 기준으로 고쳤다.
- **다음 한 작업**: 문서 내 잔여 `git.exe`/Windows Playwright 표준 문구를 재검색하고 lint 성격의
  whitespace check 후 PR을 올려 CI green 뒤 merge하고 #570을 닫는다.

## 2026-06-29 (codex) — #568 data.go.kr curated fileData 4종 schedule 보강

- **완료**: data.go.kr curated fileData 4개 dataset마다 별도 Dagster monthly schedule을 만들고,
  각 schedule이 `datagokr_file_data_records`와 `datagokr_file_data_dataset_key` resource에 같은
  dataset_key를 주입하도록 했다.
- **완료**: fileData resource는 schedule `run_config` dataset_key를 우선하고, config가 없으면 기존
  `KorTravelMapSettings.datagokr_file_data_dataset_key` 기본값을 유지한다.
- **검증**: Dagster definitions/resource 테스트 22건, feature-update runner 테스트 7건, Dagster package
  mypy를 통과했다.
- **완료(PR)**: PR #579를 squash merge했고 #568은 닫혔다.

## 2026-06-29 (codex) — #567 Enrichment detail source audit-only 계약 명시

- **완료**: enrichment 상세 비교 다이얼로그의 `정리된 datagokr`/`visitkorea` 선택이 적용 데이터를
  바꾸는 것처럼 보이지 않도록 UI 문구를 기록용으로 낮추고, detail/decision API 응답에
  `detail_source_effect: "audit_only"`를 추가했다.
- **완료**: `PATCH /v1/admin/enrichment-reviews/{review_id}` 응답은 요청의
  `selected_detail_source`를 함께 반환해 선택값이 decision reason audit marker로 기록됐는지 확인할 수 있다.
- **완료(PR)**: PR #578을 squash merge했고 #567은 닫혔다.

## 2026-06-29 (codex) — #566 Dedup review count 성능 보강

- **완료**: dedup review 목록 count가 확장 필터 없이 호출될 때 `feature.features`/`provider_sync`
  join을 materialize하지 않고 `ops.dedup_review_queue`만 count하도록 fast path를 추가했다.
- **검증**: 관련 unit 9건, T-212d EXPLAIN 대상 테스트 1건, 변경 파일 ruff와 CI를 통과했다.
- **완료(PR)**: PR #577을 squash merge했고 #566은 닫혔다.

## 2026-06-29 (codex) — PR #564 사후 리뷰 반영

- **진행 중**: #569/#574 반영 브랜치에서 admin live e2e 실제 write spec을 opt-in 게이트 뒤로 옮겼다.
  feature write는 `E2E_ADMIN_FEATURES_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`, Settings write/audit은
  `E2E_SETTINGS_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`일 때만 실행한다.
- **진행 중**: scenario catalog의 13,651건 수치를 실행 커버리지 단언으로 쓰지 않도록 threshold 테스트와
  문서 표현을 정리했다. 대표 route smoke는 catalog의 `live_smoke` 항목을 실제 네비게이션으로 돈다.
- **진행 중**: backup artifact 정리용 `DELETE /v1/admin/backups/{backup_id}` 계약을 추가하고
  `openapi.json`/frontend generated type/API hook을 갱신했다.
- **다음 한 작업**: 로컬 API/frontend 타입·lint·대상 pytest를 통과시킨 뒤 PR을 올리고 CI green 후 머지한다.

## 2026-06-28 (codex) — Admin UI 전체 live e2e 시나리오 평가

- **완료(catalog)**: Admin UI와 public reflection 표면을 24개 surface로 나누고, route smoke/write
  contract/admin feature matrix/features map/detail/curated/logs/reviews/change request/category cross 축을
  합쳐 13,651건의 논리 live e2e surface taxonomy catalog를 추가했다.
- **완료(write 반영)**: `/admin/settings`에서 public API key 생성 → API list 확인 → UI revoke →
  API/UI revoked 확인, API auth audit event 생성 → Settings UI 확인 흐름을 새 serial live spec으로
  추가했다. 2026-06-29 후속 반영 이후 이 실제 write spec은 opt-in일 때만 실행한다.
- **완료(수정)**: n150 live fixture feature id를 현재 active id로 갱신했고, curated 후보 0건 상태에서
  empty-state row를 실제 후보로 오인하던 문제를 candidate row test id로 수정했다. Settings route/nav/문서
  누락도 보강했다.
- **검증(n150)**: full live suite 수정본은 공식 Playwright Docker image + host network에서
  1,828 passed / 5 skipped / 0 failed (34.1분)로 통과했다.
- **검증(로컬)**: `npm -w packages/kor-travel-map-admin/frontend run type-check:e2e`,
  `npm -w packages/kor-travel-map-admin/frontend run lint`(0 errors, 기존 warnings 6개),
  `git diff --check`를 통과했다.
- **다음 한 작업**: PR을 올리고 CI green 및 review 조건을 확인한 뒤 머지한다.

## 2026-06-28 (codex) — Admin features/change requests UI live write e2e

- **완료(e2e)**: `/admin/features/new` → `/admin/features/change-requests` → `/admin/features`를 잇는
  실제 write live spec을 추가했다. add 요청 생성/승인, admin/public 상세 반영, 목록 검색/필터/preview/detail,
  update 승인, update 거절 후 미변경 확인, deactivate, delete 승인, public detail 404까지 직렬로 검증한다.
- **완료(서비스 반영)**: write 동작 뒤에는 UI assertion만 보지 않고 `/api/proxy` admin/public API를
  브라우저 세션으로 조회해 실제 서비스 상태를 확인한다. 실패 시 `finally`에서 테스트 feature 삭제 승인을
  시도하도록 cleanup도 넣었다.
- **n150 실행**: 새 write live spec은 n150의 공식 Playwright Docker image에서 2 passed. admin features
  read-only 목록 suite도 333 passed로 함께 확인했다.
- **cleanup 확인**: n150 DB에서 `user_request::e2e_admin_features::live-*` synthetic feature를 점검해
  모두 `deleted` 상태이며 활성/미삭제 feature가 0건임을 확인했다.
- **다음 한 작업**: 이 branch의 backup/restore live e2e와 admin features/change requests live e2e 변경을
  PR로 올리고, CI green 확인 뒤 머지한다.

## 2026-06-28 (codex) — Backup/restore UI live e2e 실제 실행 시나리오

- **완료(e2e)**: `/admin/backups` live spec을 추가해 실행 옵션 기본값, invalid backup id 오류,
  backup command plan, 실제 backup execute, 생성 artifact 기준 restore plan/execute,
  swap plan, 선택적 swap execute를 직렬 시나리오로 검증한다.
- **안전장치**: 실제 backup/restore는 `E2E_BACKUP_RESTORE_EXECUTE=1`일 때만 돌고, swap command 실행은
  별도 `E2E_BACKUP_RESTORE_EXECUTE_SWAP=1`일 때만 돈다. `swap 즉시 적용`은
  `E2E_BACKUP_RESTORE_EXECUTE_SWAP_APPLY=1`일 때만 켠다.
- **n150 실행**: n150 host에는 Playwright browser runtime deps가 없어 공식 Playwright Docker image
  + host network로 실행했다. 기본 run은 4 passed / 5 skipped, execute/apply run은 9 passed.
- **n150 execute/apply**: n150 API에 backup command enable과 runner mount를 붙여 UI에서 실제
  backup artifact 생성, staging DB/RustFS volume restore, swap `apply=true` 요청까지 통과시켰다.
  apply helper 재기동 뒤 map API/UI/Dagster 컨테이너가 healthy이고, API/Dagster DSN이 restore DB를
  바라보는 것을 확인했다. 배포 후 로그인 POST도 200 + Set-Cookie로 확인했다.
- **다음 한 작업**: n150에 임시로 붙인 backup/restore runner를 정식 배포 모델로 정리한다. 특히
  docker-manager 배포에서 restore swap apply를 API 요청 생명주기 밖 helper로 실행하는 방식을 문서화하고,
  정식 스크립트/compose 설정으로 승격할지 결정한다.

## 2026-06-28 (codex) — Refreshable provider catalog / MOIS detail runner

- **완료(분류)**: `is_feature_load`는 새 `FeatureBundle` 생성 여부로 유지하고, Dagster feature update
  request로 실행 가능한지는 `is_refreshable`로 분리했다.
- **완료(노출)**: `/ops/providers` never-run 목록은 `catalog_refreshable_entries()` 기준으로 바꿔
  OpiNet 가격, KREX 가격/기상, KMA 예보/실황, VisitKorea 축제 보강처럼 `is_feature_load=False`이지만
  runner가 있는 dataset을 운영 실행 목록에 표시한다.
- **완료(MOIS detail)**: `mois_license_detail`을 refreshable로 전환하고, 기존 MOIS Dagster asset runner가
  `dataset_key=mois_license_detail` 요청을 받을 수 있게 했다. 상세 API는 detail source record 우선,
  bulk source record fallback으로 조회한다.
- **유지(전화번호 보강)**: `place_phone_enrichment`는 runner/운영 실행 목록에 추가하지 않았다.
- **검증(로컬)**: refreshable catalog 56개와 runner spec 비교에서 누락 0건,
  `runner_not_in_catalog` 0건 확인. 관련 pytest 32건, 변경 파일 `ruff`, 대상 mypy 통과.
- **다음 한 작업**: PR 생성, CI green 확인 후 머지하고 N150 배포 뒤 `/ops/providers`에서 MOIS detail과
  non-feature-load 실행 대상이 queue/run/done으로 전환되는지 UI e2e로 확인한다.

## 2026-06-28 (codex) — Feature update provider/Dagster 정렬

- **완료(원인)**: AirKorea 실패는 UI/catalog가 `airkorea_stations`를 feature-load 대상으로 노출했지만
  Dagster runner는 `airkorea_air_quality`만 지원해서 발생했다. OpiNet 실패는 Dagster runtime에
  `KOR_TRAVEL_MAP_OPINET_API_KEY`가 비어 있어 provider client 인증 오류가 난 것이었다.
- **완료(수정)**: AirKorea catalog는 `airkorea_air_quality`를 feature-load 대상으로 정렬하고,
  기존 `airkorea_stations` 요청은 같은 asset alias로 실행한다. OpiNet은 key 누락을 runner 단계에서
  명확한 credential 오류로 실패시킨다.
- **완료(누락 Dagster)**: MOIS history/closed, `standard_special_streets`, data.go.kr curated fileData
  4종을 feature update runner에 추가했다. 지역특화거리와 fileData 공용 Dagster asset/resource/schedule을
  추가했다.
- **완료(전체 점검)**: provider catalog의 `is_feature_load=True` 47개와 runner spec을 비교해 runner
  미지원 0건을 확인했고, 이 비교를 회귀 테스트로 고정했다.
- **검증(로컬)**: `ruff check .`, 대상 mypy, Dagster 테스트 199건(1 skipped), API provider
  catalog/router 테스트 19건 통과. API router 테스트는 현재 셸 인증 env 때문에
  `KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=false`를 명시해 실행했다.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고, UI e2e로 feature update 요청이 queue에 들어가고
  Dagster 실행으로 성공 완료되며 반복 작업이 정상 노출/실행되는지 확인한다.

## 2026-06-28 (codex) — Linux/WSL 개발 실행 정책

- **완료(환경 정책)**: `git`/`gh`/`codegraph`를 포함한 모든 개발 명령을 Linux/WSL에서 실행하도록
  `AGENTS.md`, `SKILL.md`, `README.md`, `docs/dev-environment.md`를 정리했다.
- **완료(runbook)**: agent workflow, codegraph worktree, failure patterns, runbook index의 Windows Git
  전제를 제거하고, Windows 경로 기반 worktree metadata 복구 절차를 추가했다.
- **완료(e2e 정책)**: Playwright e2e는 n150 Linux 우선, n150에서 불가할 때만 Windows browser
  fallback으로 실행하도록 frontend README와 Playwright config 주석까지 문서화했다.
- **검증(로컬)**: 문서 변경만 수행했으며 `git diff --check`를 실행했다.
- **다음 한 작업**: PR 생성, CI green 확인 후 머지한다.

## 2026-06-28 (codex) — Review 상세 비교 다이얼로그

- **완료(API)**: `/admin/dedup-reviews/{review_id}`와 `/admin/enrichment-reviews/{review_id}` 상세
  조회 API를 추가했다. 응답은 양쪽 feature/source 상세, raw payload, 좌표, 기간, 거리/score를 포함한다.
- **완료(UI)**: Dedup review와 Enrichment review 테이블 행 클릭 시 상세 비교 다이얼로그를 열고,
  두 자료의 핵심 필드/detail/raw JSON과 하나의 지도에 표시한 두 좌표를 보여준다.
- **완료(Enrichment 선택)**: 축제 enrichment 상세에서 `정리된 datagokr`와 `visitkorea` 중 사용할
  상세 source를 고를 수 있다. 정리된 target detail이 없으면 VisitKorea가 기본 선택되며, accept 요청에
  선택값을 기록한다.
- **검증(로컬)**: 전체 pytest 1367건, 전체 `ruff`, `mypy src/kortravelmap`, import-linter,
  OpenAPI drift check, admin frontend `type-check`/대상 ESLint/`gen:types:check`,
  Windows Playwright mocked review e2e 23건 통과.
- **다음 한 작업**: PR 생성/CI green 후 머지하고, N150 배포 뒤 운영 데이터에서 dedup/enrichment 행
  클릭 상세와 enrichment 선택 fallback을 smoke 확인한다.

## 2026-06-28 (codex) — Feature update request queue 실행 복구

- **완료(Dagster)**: `feature_update_runner` 기본 resource를 등록해
  `feature_update_request_worker`가 missing resource 대신 실제 provider/dataset asset dispatcher를
  받도록 했다.
- **완료(실행 경로)**: run-now/queued request는 기존 queue/sensor/worker 구조를 유지하면서,
  OpiNet·KREX·KMA·AirKorea 등 live fetcher가 있는 provider dataset을 lazy resource로 실행한다.
- **완료(테스트)**: runner dispatch 단위 테스트와 Definitions 기본 resource 등록 회귀 테스트를 추가했다.
- **검증(로컬)**: `pytest` targeted 21건, 변경 파일 `ruff`, `mypy --python-version 3.12` 3파일 통과.
  기본 mypy 실행은 현 환경의 `numpy` stub/Python version 설정 충돌로 중단된다.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고, update requests에서 KMA weather 또는 OpiNet price
  run-now 요청이 `running`/`done`으로 전환되는지 Dagster run과 admin UI에서 확인한다.

## 2026-06-28 (codex) — Review 테이블 페이지네이션 상/하단 보강

- **완료(API)**: dedup/enrichment review 목록에 `page` 쿼리와 `meta.page.total`을 추가했다.
  기존 `cursor`는 호환용으로 유지한다.
- **완료(UI)**: Dedup review와 Enrichment review 테이블의 바로 위/아래에 동일한 페이지바를 배치했다.
  첫/이전/다음/마지막 페이지 이동과 `현재 페이지 / 총 페이지`, 총 아이템 수, 현재 페이지 아이템 수를
  표시한다.
- **완료(e2e)**: mocked review e2e는 page 번호 전진, 상/하단 버튼 2벌, 마지막 페이지 버튼,
  빈 목록 비활성 상태를 검증한다. admin review smoke도 페이지바 2벌을 확인한다.
- **검증(로컬)**: targeted ruff, mypy 3파일, router/unit pytest 20건, SQL integration 2건,
  OpenAPI drift check, admin frontend type-check/lint, mocked review e2e 21건, review smoke e2e 2건 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live review e2e로 운영 화면을 확인한다.

## 2026-06-27 (codex) — Enrichment/Dedup review 검수 UX 보강

- **완료(API)**: enrichment review 목록에 대상/source 좌표·기간, 거리(`distance_m`), 거리 기반
  유사도(`spatial_score`)를 추가했다. VisitKorea enrichment source record도 TourAPI 좌표를 보존한다.
- **완료(UI)**: enrichment/dedup review 테이블에 검색, 상태/성격별 필터, score band, page size,
  cursor pagination을 추가했다. enrichment 테이블은 시작-종료 날짜와 거리 컬럼을 표시하고, 좌표가
  있는 행은 하나의 VWorld 지도에 datagokr/visitkorea 마커와 이름을 함께 보여준다.
- **완료(e2e)**: mocked review e2e에 enrichment 필터·페이지네이션·지도와 dedup 전용
  필터·페이지네이션 회귀 테스트를 추가했다. N150 live spec에도 두 review 화면의 필터/페이지네이션/
  지도 smoke를 추가했다.
- **검증(로컬)**: Python unit 1109건, enrichment repository integration 9건, API/router targeted
  28건, ruff, mypy, import-linter, admin frontend lint/type-check/gen:types, Vitest 45건, mocked review
  e2e 21건 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150에 배포하고 live review e2e로 운영 화면을
  평가한다.

## 2026-06-27 (codex) — Curated place-search 반영 정책 수정

- **완료(UI)**: `/admin/curated-features`의 place-search 결과 `반영`이 `display_title`과
  metadata만 저장하던 문제를 고쳐, `reuse_policy=allowed`도 함께 PATCH하도록 했다.
- **완료(e2e)**: manual_review 후보에서 검색 결과를 반영하면 PATCH body, REUSE 행 badge,
  editor select가 모두 `allowed`로 바뀌는 mocked Playwright 회귀 테스트를 추가했다.
- **검증(로컬)**: admin frontend type-check, 변경 파일 ESLint, curated mutations mocked e2e 21건,
  `git diff --check` 통과.
- **다음 한 작업**: N150 배포 뒤 운영 데이터에서 manual_review 후보 1건으로 place-search 반영 smoke를
  확인한다.

## 2026-06-27 (codex) — Feature update request UI live e2e

- **완료(UI/e2e)**: `/admin/feature-update-requests` live Playwright spec을 추가했다. form controls,
  validation errors, 실제 API dry-run preview, `/features` 지도 화면의 `Update` 링크 이동을 확인한다.
- **완료(에러 케이스)**: mocked update request e2e에 lon 필수, lat 범위, radius 최소값, create API
  422 alert 케이스를 추가했다.
- **완료(지도 반영)**: update request create/run-now와 ops-live `feature_update_requests` 이벤트가
  `features`/`feature`/`admin-features` query를 invalidate해 feature 지도와 상세/목록이 재조회되도록
  연결했다.
- **검증(로컬/live)**: admin frontend type-check, 변경 파일 ESLint, mocked update request e2e 8건,
  live update request e2e 5건, `git diff --check` 통과. Vitest unit은 WSL `node_modules`의
  `@vitejs/plugin-react` 누락 및 NTFS 권한 문제로 실행하지 못했다.
- **다음 한 작업**: WSL Node 의존성 설치 상태를 복구한 뒤 `src/api/live.test.ts`를 포함한 frontend
  unit test를 재실행하고, 필요하면 features map WebGL 초기화 실패 원인을 별도 점검한다.

## 2026-06-27 (codex) — Curated place search provider 직접 호출

- **완료(API)**: admin curated feature 주소/POI 검색은 kor-travel-concierge를 경유하지 않고 Kakao
  Local, NAVER Search, Google Places API를 직접 호출한다. provider별 키 누락/호출 실패는 `errors`
  필드에 담아 반환한다.
- **완료(설정)**: `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY`,
  `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID`, `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET`,
  `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY`를 settings/env 예시에 추가했고, 기존 짧은 env 이름은
  load-env/compose에서 매핑한다.
- **검증(로컬)**: `tests/unit/test_curated_routes.py` 3건과 변경 파일 ruff 통과.
- **다음 한 작업**: 실제 운영 env에 위 provider 키가 들어간 상태로 API 컨테이너를 재배포하고,
  curated feature detail에서 검색 결과가 provider별로 표시되는지 smoke 확인한다.

## 2026-06-27 (codex) — Admin 후속 보강: curated/detail/OpiNet/Dagster

- **완료(UI)**: curated feature place 검색 자동 실행/누적을 끊고 명시 검색으로 변경했다. 화면의
  `concierge` 표시명은 중립 라벨로 바꿨고, 해당 provider 선택 시 source rule의 실제 theme으로
  filter가 이동한다.
- **완료(상세/지도)**: admin curated feature 전용 상세 화면을 추가했다. admin features 목록 우측
  preview와 `/features/{feature_id}` 상세에는 지도 패널을 추가했고, 목록 `detail` 버튼은 상세
  route로 바로 이동한다.
- **완료(Dagster/OpiNet)**: OpiNet `low_top_area` no-data 예외 처리와 호출 상한 이후 fallback을
  추가했다. Dagster feature load schedule은 누락된 krforest/standard/khoa/krairport/airkorea/
  visitkorea asset까지 포함하고, admin Dagster 화면은 asset을 4개로 자르지 않는다.
- **검증(로컬)**: admin frontend type-check/e2e type-check, 변경 파일 ESLint, Dagster/API targeted
  pytest 84 passed/1 skipped, ruff, OpenAPI export drift test 통과.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고 OpiNet price job과 누락 Dagster schedule/job
  노출, curated 상세/검색 UI를 운영 데이터로 smoke 확인한다.

## 2026-06-27 (codex) — Admin live review 데이터/표시 보강

- **완료(원인 확인)**: N150에서 KMA `TMP` weather 값은 존재한다. price feature는 OpiNet 부분 응답
  처리 때문에 여전히 제주/완도권에 머물렀고, enrichment/dedup review queue와 ops log table은 0건,
  provider sync state는 KMA만 기록되어 있었다.
- **완료(코드)**: OpiNet `low_top_area` 부분 응답에도 전국 fallback을 타게 했고, VisitKorea
  enrichment Dagster asset은 review queue refresh 경로를 호출하게 했다. feature load asset은 성공
  provider sync state를 기록한다.
- **완료(UI)**: curated review 우측에 위치 지도/상세/place-search 반영 패널을 추가했다.
  admin features/curated/logs table pagination 정보와 MOIS place 특화 상세 패널을 보강했다.
- **검증(로컬/live)**: Dagster/API targeted pytest와 ruff, admin frontend type-check/e2e type-check,
  변경 파일 ESLint, `git diff --check`, `/admin/enrichment-reviews` live Playwright 34건 통과.
- **다음 한 작업**: PR 생성/CI green 후 N150에 배포하고 OpiNet price, VisitKorea enrichment,
  dedup refresh, concierge curated source 적재 job을 재실행해 운영 DB row 수와 UI 표시를 재확인한다.

## 2026-06-26 (codex) — OpiNet fallback 도심 anchor hotfix

- **운영 확인**: N150에서 `low_top_area` 배포 후 `feature_price_opinet_stations_job`은 성공했지만
  price feature는 295건 그대로였고, 좌표 범위도 제주권에 머물렀다. 최근 `PriceValue` 갱신도 0건이었다.
- **진행 중**: `lowTop10` 빈 응답 fallback이 기존 sparse grid만 쓰던 문제를 보강해, 전국 주요 도심
  anchor를 먼저 `aroundAll`로 조회한 뒤 기존 grid를 보조로 사용하게 한다.
- **다음 한 작업**: targeted pytest/ruff/mypy 통과 후 PR을 만들고, CI green이면 머지·N150 재배포·
  OpiNet price job 재실행으로 price 좌표 범위가 제주권 밖으로 확장되는지 확인한다.

## 2026-06-26 (codex) — Feature별 상세 패널 + 좌측 메뉴/Dagster 보강

- **완료(API)**: area 포함 feature 조회 API(`/v1/features/{feature_id}/contained-features`)를 추가하고,
  weather marker용 현재기온 summary와 area 면적 필드를 OpenAPI에 반영했다.
- **완료(UI)**: feature 상세 패널을 kind별로 분리했다. weather는 weather feature에서만 표시하고,
  price는 이력 그래프, event는 기간/장소, area는 포함 feature, route는 구간 메타를 보여준다.
- **완료(지도/메뉴)**: weather marker에 현재기온을 표시하고, `/features` 지도 화면에도 좌측 메뉴를
  노출했다. 데스크톱 sidebar는 접기/펼치기 상태를 저장한다.
- **완료(Dagster)**: feature load schedule을 weather 시간당 1회, 유가 일 2회, 기타 월 1회로
  정리하고, run 상세에 실패 원인/stack 요약을 추가했다.
- **검증(로컬)**: 전체 pytest 1,357건, 전체 ruff, import-linter, strict mypy, admin frontend
  type-check/lint, OpenAPI generated type drift check, production build, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live smoke를 완료한다.

## 2026-06-26 (codex) — OpiNet price 제주 bbox 원인 + low-top/fallback 전국 모드

- **원인 확인**: N150 운영 env가 OpiNet scope를 제주/완도권 bbox
  `126.15,33.19,126.98,34.21`로 고정하고 있어 좌표 있는 active price feature 196건이 해당
  권역에만 존재했다. KREX price 99건은 좌표가 없어 지도 marker에 표시되지 않는다.
- **결정**: OpiNet 전국 bbox 격자 수집은 `aroundAll` 1만 회 이상 호출로 일일 한도 위험이 있어
  바로 쓰지 않는다.
- **진행 중**: `OPINET_SCOPE_MODE=low_top_area`를 추가했다. 시군구별 `lowTop10`을
  휘발유/경유/고급휘발유 3종으로 호출하고, 운영 `areaCode`/`lowTop10`이 빈 응답이면 전국 샘플
  그리드의 `aroundAll`로 fallback한다.
- **검증**: OpiNet provider unit, Dagster provider fetcher, Dagster definitions targeted pytest,
  수정 파일 ruff, strict mypy 통과.
- **다음 한 작업**: fallback PR 생성/CI green/머지 후 N150을 재배포하고 OpiNet price asset을
  재실행해 전국 분포 smoke를 확인한다.

## 2026-06-26 (codex) — Admin price feature 표시 + Dagster 주기 정리

- **완료(API)**: `/v1/features/{feature_id}/price`를 추가해 제품별 최신 가격(`current`)과 최근
  가격 이력(`history`)을 반환한다. `/v1/features` summary에는 price feature용
  `price_summary`를 붙여 지도 marker가 추가 호출 없이 최신 유가를 표시할 수 있게 했다.
- **완료(UI)**: admin `/features` 지도 marker가 `price` feature에 대해 휘발유/경유/고급휘발유
  최신 가격을 표시한다. `price` feature 선택/상세 화면은 `FeaturePricePanel`로 가격 요약과
  history 표를 보여준다. 가격 history 그래프는 후속 PR 범위다.
- **완료(Dagster)**: OpiNet/KREX price Feature schedule은 일 2회(`06/18시`)로 조정했고,
  KMA/KREX weather 관련 schedule은 시간당 1회 기준으로 정렬했다.
- **완료(OpenAPI/types)**: admin/user OpenAPI와 admin/user TypeScript generated types를 재생성했다.
- **검증(로컬)**: API targeted pytest 20건, Dagster definitions 10건, OpenAPI drift check,
  admin frontend type-check, user-client type-check, admin frontend lint(기존 warning 7건), targeted
  ruff, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 후속 UI PR을 진행한다. 후속 범위는 feature
  kind별 우측 메뉴 분기(price history 그래프, weather는 weather feature 전용, event 기간 표시,
  route 구간 상세 표시)와 로그인 후 좌측 메뉴의 전 화면 노출/접기 기능이다.

## 2026-06-25 (codex) — 가격 시계열 테이블 설계 + OpiNet/KREX 유가 적재

- **완료(로컬 설계/코드)**: `feature.feature_price_values`를 추가하고 price anchor
  `FeatureBundle` + `PriceValue`를 한 transaction으로 적재하는 client/repository 경로를 구현했다.
- **완료(provider)**: OpiNet station detail 중첩 가격과 KREX 휴게소 유가 snapshot을 각각
  `kind=price` feature + 제품별 `PriceValue`로 변환한다.
- **완료(Dagster)**: `feature_price_opinet_stations`, `feature_price_krex_rest_areas` asset/job/schedule과
  live resource를 추가했다.
- **완료(문서)**: `data-model.md`, `postgres-schema.md`, 성능/ETL 문서를 실제
  `feature_price_values` 설계로 갱신했다.
- **완료(Alembic graph)**: main hotfix의 `0035_merge_price_and_curated`와 N150 선배포의
  `0035_merge_curated_price`를 모두 보존하고, `0036_merge_price_merge_aliases` no-op merge
  revision으로 최종 단일 head를 만든다.
- **완료(N150 배포/적재)**: API/Dagster/UI 재빌드·재기동 후 KREX/OpiNet price job을 재실행했다.
  운영 DB Alembic revision은 `0036_merge_price_merge_aliases`이고, 최종 active price feature 295건,
  `feature.feature_price_values` 1,132건
  (`python-opinet-api/opinet_gas_station` 874건, `python-krex-api/rest_area_fuel` 258건).
- **완료(live smoke)**: N150 `/health` 200, trusted admin proxy read-only `/v1/features`
  `kind=price` bbox 조회 200, UI `/login` 200, API/UI/Dagster healthy 확인.
- **완료(로그인/UI live e2e)**: Windows Playwright live config로 N150 공개 prod URL admin 로그인 setup
  1건 통과. 같은 인증 세션으로 `features-list`/`features-map`의 `price` 대상 16건 통과.
- **검증(로컬)**: provider/Dagster unit, Alembic+Dagster 통합, ruff, strict mypy,
  import-linter, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지를 완료한다.

## 2026-06-25 (codex) — Alembic curated 배포 체인 hotfix

- **완료(원인 확인)**: N150 운영 DB의 `alembic_version`이 `0034_feature_price_values`인데 main
  코드에 해당 리비전 파일이 없어 API 부팅 중 `alembic upgrade head`가 실패했다.
- **완료(체인 수정)**: 운영 DB의 `feature.feature_price_values` 스키마와 동일한
  `0034_feature_price_values` 리비전을 복원하고, 기존 `0034_generic_curated_contract`와
  `0035_merge_price_and_curated` no-op merge 리비전으로 합쳤다.
- **다음 한 작업**: hotfix PR 생성, CI green 확인, 머지 후 N150 API/Dagster/UI를 재기동하고
  live schema/API smoke를 완료한다.

## 2026-06-25 (codex) — Curated API 범용 계약 정리

- **완료(API 정책)**: public curated API는 임의 외부 사용자가 curated feature 목록/상세를 조회하는
  범용 계약으로 정리했다. user OpenAPI profile에는 `/v1/curated-features`와
  `/v1/curated-features/{curated_feature_id}`만 남긴다.
- **완료(DB/API rename)**: curated 재사용 속성은 `curation_relation`/`reuse_policy`/
  `content_version`, snapshot table은 `feature.curated_feature_detail_snapshots`로 정리했다.
  source rule metadata, snapshot JSON, admin UI preview API도 같은 범용 명칭으로 migration한다.
- **완료(POI metadata)**: POI cache target metadata의 외부 POI 식별자는 `external_poi_id`로만
  저장·노출한다.
- **완료(검증)**: targeted curated/POI API 21건, curated/POI/schema integration 14건, OpenAPI
  drift, generated type drift, admin/user type-check, frontend unit 43건, curated mocked e2e 22건,
  ruff, strict mypy, import-linter 통과. 전체 pytest는 1,345건 통과, 외부 `kor-travel-geo`
  live reverse geocoder 400으로 5건 실패.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live smoke를 완료한다.

## 2026-06-25 (codex) — KNPS 비매칭코스 제외 + N150 재검증

- **완료(코드)**: KNPS `knps_trails` 변환에서 `비매칭코스`/`Nonmatching Course`를 공식 route로
  적재하지 않도록 제외했다. 한글 raw name과 영문 raw name을 모두 확인한다.
- **완료(회귀 테스트)**: `tests/unit/test_providers_knps.py`에 단건 skip과 배치 내 정상 route 유지
  케이스를 추가했다.
- **완료(N150)**: 수정 provider를 배포하고 기존 active `비매칭코스` route 1건을 soft delete했다.
  최종 active unmatched route 0건, active route 617건을 확인했다.
- **완료(OpiNet/env)**: 로컬 `python-opinet-api`의 키를 N150 `.env`에
  `KOR_TRAVEL_MAP_OPINET_API_KEY`로 저장하고 bbox scope도 `KOR_TRAVEL_MAP_OPINET_SCOPE_*`로
  저장했다. OpiNet station job 재실행 후 source record 196건, active place feature 196건을
  확인했다.
- **완료(N150 rename)**: 운영 DB/role/env/compose의 잔여 `krtour_map`/`KRTOUR_MAP*`을 최신
  `kor_travel_map`/`KOR_TRAVEL_MAP*` 기준으로 정리했고 API/Dagster healthy를 확인했다.
- **완료(live e2e)**: UI live Playwright `features-map` 118건, `features-list`/`features-detail`/
  `providers-consistency` 753건, 나머지 live 묶음 896건을 검증했다. 남은 묶음 중 모바일 reviews
  1건은 최초 묶음 실행에서 실패했지만 단독 재실행 2건 통과했다.
- **다음 한 작업**: 로컬 전체 게이트 실행 후 PR 생성, CI green 확인, 머지를 완료한다.

## 2026-06-25 (codex) — Concierge curated source + curated 계약 보강

- **완료(map 코드)**: concierge YouTube 장소 후보 provider/dataset을 `media-places` curated source rule로
  seed하고, rule apply가 기본 `curated` 상태와 source title 기반 `display_title`을 만들도록 보강했다.
- **완료(DB/API rename)**: curated 재사용 계약은 제품명 없는 detail snapshot 계약으로 정리한다.
  POI cache target metadata의 외부 POI 식별자도 범용 key로 표현한다.
- **완료(concierge 연동)**: concierge export payload에 source target type/value/search query와
  `youtube.source_title`을 추가해 채널명·플레이리스트명·보정 검색어명을 map이 title로 쓸 수 있게 했다.
- **검증 진행**: map targeted unit/API/Dagster/integration, OpenAPI drift, frontend/user type-check,
  ruff, strict mypy, import-linter 통과. concierge targeted backend 26건 통과.
- **다음 한 작업**: 전체/확장 게이트 후 양쪽 PR 생성, CI green 확인, 머지, N150 배포와 live smoke를 완료한다.

## 2026-06-25 (codex) — KNPS protected area 한글명 보정 + N150 재적재

- **완료(번역)**: N150 active `area` 중 KNPS `knps_protected_areas` 영어/로마자 source name을 모아
  Gemini 2.5 Flash에 JSON 입력/출력으로 일괄 번역했다. `kor-travel-concierge`의
  `GEMINI_API_KEY`/`gemini-2.5-flash`/JSON schema/retry 패턴을 참고했고, 런타임에는 Gemini를
  호출하지 않는 정적 한글명 테이블 1,431건으로 반영했다.
- **완료(코드)**: KNPS protected area 이름 결정 로직이 raw 한글 복구 후 번역 테이블을 사용한다.
  라틴 문자와 손상 한글 음절이 섞인 raw `ORIG_NAME`은 정상 한글 후보로 보지 않도록 보강했다.
- **완료(N150)**: API/Dagster/daemon 이미지를 재빌드·재기동하고 `knps_protected_areas` 1,516건을
  재적재했다. 기존 `f_global_*` 중복은 inactive 처리했고, geocoder fallback으로 현재도 global이
  정본인 130건은 active 유지했다.
- **완료(검증)**: 최종 N150 active `area`는 `knps_park_boundaries` 23건,
  `knps_protected_areas` 1,516건이며 active area 라틴 이름은 0건이다. 공식 UI live Playwright
  2개 smoke와 커스텀 BFF/UI smoke(1,516건 전체 cursor 순회, 라틴 이름 0건, console error 0건)가
  통과했다.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-25 (codex) — Admin 로그인 submit 보강 + N150 area live smoke

- **완료(코드)**: 로그인 form submit이 React state 대신 현재 `FormData` 값을 읽어 username/password를
  전송한다. 자동입력/테스트 입력 경로에서 DOM value와 React state가 어긋나도 빈 password가
  전송되지 않도록 input `name` 속성과 회귀 테스트를 추가했다.
- **완료(N150)**: 수정 frontend를 N150 production에 반영하고 `kor-travel-map-ui`를 재빌드·재기동했다.
  UI/API 컨테이너 모두 healthy 상태다.
- **완료(live e2e)**: 공식 live Playwright 인증 setup + `/features` 지도 smoke 통과. 추가 계측 smoke에서
  로그인 POST 200, 낮은 줌 area `include_geometry=false`/cluster 25개/partial 없음, 높은 줌
  `보성` area `include_geometry=true`/geometry source 및 area layer 렌더를 확인했다.
- **검증**: `npm run test -- src/components/login-form.test.tsx`, `npm run type-check`, 대상 ESLint,
  `git diff --check`, N150 Next production build 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-24 (codex) — Admin area 클러스터링 + KNPS protected area 한글명 보정

- **완료(코드)**: 낮은 줌의 admin feature 지도에서는 `area` geometry를 요청하지 않고 centroid
  marker를 cluster source에 포함한다. 줌 14 이상에서만 area polygon/label geometry를 요청·표시하며,
  query 전환 중 이전 데이터를 유지해 지도 flicker를 줄인다.
- **완료(성능)**: area/route 중심 필터에서는 tile별 `page_size` 분할을 끄고, area-only 지도 조회가
  전체 bbox를 과도하게 잘라 false partial을 만들지 않도록 tile zoom을 한 단계 더 잘게 보정했다.
  tile별 `next_cursor`가 남는 경우 이어 받아 낮은 줌 area 누락 가능성을 줄인다.
- **완료(KNPS)**: `knps_protected_areas`는 raw 한글 후보(`ORIG_NAME` 등)를 우선하고,
  CP949로 잘못 decode된 recoverable UTF-8 문자열은 한글명으로 복구한다. 원문 byte가 이미 손상된
  값이나 repair 실패 후 CJK mojibake가 남는 값은 영어 fallback을 유지한다.
- **검증**: KNPS unit test, frontend type-check/build, 수정 frontend ESLint, `ruff check .`,
  `python -m mypy --strict src/kortravelmap`, import-linter, `git diff --check` 통과.
- **다음 한 작업**: PR 생성 후 CI green/머지, N150 prod 배포, 운영 area live smoke를 완료한다.

## 2026-06-24 (codex) — KNPS area 이름 복구 + N150 feature 화면 확인

- **완료(운영 확인)**: N150 `/features`에서 로그인 후 `area` 필터를 켜면 `203건 표시`,
  maplibre marker 203개, 테이블 `AREA active` 행이 표시된다. 운영 DB 기준 active `area`는
  KNPS 1,539건이고, geometry 없는 `krheritage` area 1,178건은 inactive 상태다.
- **완료(코드)**: KNPS `knps_park_boundaries`/`knps_protected_areas`는 provider normalized
  `name`이 비어도 raw 속성(`NPK_NM`, `NAME` 등)에서 이름을 복구해 area bundle을 만든다.
  이름 없는 trail/route record는 기존처럼 skip한다.
- **완료(N150)**: 수정 provider 파일을 N150에 반영하고 map API/Dagster/daemon을
  재빌드·재기동했다. 배포 후 API/Dagster 이미지의 반영과 `/features` area UI smoke를 확인했다.
- **검증**: `tests/unit/test_providers_knps.py` 45건 통과, `ruff check .` 통과,
  `python -m mypy --strict src/kortravelmap` 통과, import-linter 4계약 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-24 (codex) — krheritage area 보정 + concierge 적재/N150 live 검증

- **완료(코드)**: `krheritage` provider는 Polygon/MultiPolygon 경계 geometry가 있을 때만
  `area` feature를 만들고, 좌표만 있는 유산은 `place`로 적재한다. 실제 면 geometry가 있을 때만
  centroid 좌표, 면적, `AreaDetail`을 기록한다.
- **완료(DB 정리 경로)**: 특정 provider source에서 생성된 active geometryless `area` feature를
  inactive 처리하는 repository/client 메서드를 추가했고, `krheritage_heritage_features` asset 적재
  후 자동 정리하도록 연결했다.
- **완료(provider 점검)**: 현재 `area` 생성 provider는 `knps`와 `krheritage`뿐이다. `knps`는 기존부터
  polygon geometry gate가 있고, `krforest`는 현재 point place dataset만 적재한다.
- **완료(N150)**: 수정 파일을 N150 `~/kor-travel-map`에 반영하고 map API/Dagster를 재빌드/재기동했다.
  `kor-travel-concierge-youtube/youtube_place_candidates` snapshot 79건을 active `place`로 적재했다.
  기존 `krheritage` active geometryless `area` 1,178건은 inactive 처리했고, 최종 active
  geometryless `area`는 0건이다.
- **검증**: 로컬 targeted unit/integration pytest, 수정 파일 ruff, 수정 Python strict mypy 통과.
  N150 API live e2e 통과. N150 UI live e2e는 admin 로그인 세션으로 features list/map smoke 4건과
  실제 concierge feature detail smoke 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-23 (codex) — Admin 로그인 + public API key 관리

- **완료(코드)**: Next.js admin frontend에 `/login`, HttpOnly 세션, logout, `/api/proxy`
  BFF를 추가했다. 기존 REST client는 `/api/proxy`를 기본 base로 사용한다.
- **완료(API/DB)**: `ops.admin_auth_events`, `ops.public_api_keys` migration과 repo/router를
  추가했다. FastAPI admin router는 proxy secret 설정 시 trusted frontend proxy header를 요구하고,
  public REST surface는 `key` query 검증을 지원한다.
- **완료(env)**: gitignored `.env`에 `admin/ad.min`의 PBKDF2-SHA256 hash, session secret,
  admin proxy secret을 저장했다. 예시 env에는 placeholder만 추가했다. `kor-travel-geo` v2 key는
  현재 VWorld key와 동일하게 쓰도록 설정했다. Docker/env scripts도 VWorld key를
  `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` / `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`로 같은 값
  매핑하고, `$` 포함 secret을 보존하도록 raw dotenv 로딩으로 보강했다.
- **완료(PR#399 리뷰 반영)**: XFF/X-Real-IP 기본 불신, username mismatch PBKDF2 수행,
  proxy-secret deny 테스트, 401 로그인 리다이렉트, 로그인 실패 a11y, clipboard fallback,
  invalid UUID revoke 404화, Alembic revision id 32자 제한 대응을 반영했다.
- **검증**: `pytest -q` 1326 passed, `ruff check .` passed, `mypy --strict` 142 files passed,
  import-linter 4 contracts kept, admin frontend `npm run test` 37 passed, `npm run type-check`
  passed, `npm run lint` 0 errors / 기존 warnings 6, OpenAPI/type drift check passed,
  user-client typegen/type-check passed, compose config + shell syntax check passed.
- **prod smoke**: N150 production 서버에 반영했고, geo v2 `POST /v2/reverse`는 key 없이 `400`,
  VWorld와 같은 key로 `200`을 반환했다. map API `/v1/categories`도 key 없이 `401`, public key로
  `200`을 반환했다. map API 컨테이너 내부 `KorTravelGeoRestClient(api_key=...)` reverse 호출은
  `status=OK`, 후보 11건, 주소/법정동 코드 포함으로 성공했다.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-23 (codex) — Admin 지도 route/area 렌더링 + N150 prod 반영

- **완료(코드)**: admin Feature 지도에 `marker_icon`/`marker_color` 기반 maki 마커를 적용하고,
  `weather` feature는 날씨 아이콘 대신 단순 색상 마커로 표시한다. `route`는 GeoJSON 선+이름
  라벨, `area`는 면+외곽선+이름·면적 라벨로 표시한다.
- **완료(API/DB)**: `/v1/features`와 `/v1/features/in-bounds`에 선택적
  `include_geometry`를 추가해 route/area `geometry`, area `area_square_meters`를 반환한다.
  낮은 축척 bbox SQL에서 `MATERIALIZED` CTE를 제거해 prod 109만 건 기준 큰 bbox plan을
  약 2.4초에서 약 3ms 수준으로 낮췄다. route/area 지도용 GeoJSON은 표시용 단순화와
  좌표 정밀도 제한을 적용해 대형 route 응답 크기를 줄였다. admin frontend는 viewport를
  WebMercator tile bbox로 나눠 tile별 react-query 캐시를 쓰도록 바꿨고, tile별
  `page_size` 자동 조정으로 낮은 축척 응답 총량을 제한한다.
- **완료(prod)**: N150 production 서버(`<prod-host-alias>`, `<prod-host-ip>`)의 기존 map
  컨테이너를 내리고 `~/kor-travel-map` rsync + docker-manager compose 재빌드/재기동으로
  직접 반영했다.
- **검증**: API 단위 테스트 `13 passed`, 신규 PostGIS geometry 통합 테스트 `1 passed`,
  admin `type-check`, ESLint 0 errors(기존 warnings 8), 수정 Python ruff 통과. WSL
  Playwright는 Chromium binary 미설치로 실행 불가.
- **다음 한 작업**: PR 생성/머지 흐름으로 정식 main 반영 후, 필요하면 서버 측 vector tile/MVT
  엔드포인트까지 확장할지 결정한다.

## 2026-06-23 (claude) — KMA 날씨 복제 제거 마이그레이션 + krex 휴게소 관측 기상 weather source

- **완료**: prod DB의 KMA 복제 날씨(30.3M행/15GB)를 batched DELETE + VACUUM FULL로 제거 →
  디스크 24G 회수, 60격자 anchor로 KMA 재적재(`feature_weather_values=66,766`, 복제 0).
- **완료(코드, PR 진행)**: krex 고속도로 휴게소 관측 기상을 weather-kind Feature로 적재
  (`feature_weather_krex_rest_areas` asset + `fetch_krex_rest_area_weather` + provider 변환
  `rest_area_weather_records_to_{bundles,values}`). `temperature→T1H`로 KMA 기온 빈틈 보강.
  CI-parity 통과(ruff/mypy×3/lint-imports/pytest). 자세한 내용은 journal 2026-06-23.
- **다음 한 작업**: PR 머지 후 prod dagster 이미지 재배포 → `feature_weather_krex_rest_areas`
  materialize → 휴게소 weather feature 생성 + 기온 nearest 커버리지(울진/태안 등 gap) 검증.
  EX key는 기존 `KEX_GO_API_KEY` 재사용(신규 env 불필요).

## 2026-06-21 Codex 작업 메모 — UI live e2e 재실행

사용자 지시에 따라 live UI e2e를 재실행했다. 정본 보고서:
[`docs/reports/ui-live-e2e-rerun-2026-06-21.md`](reports/ui-live-e2e-rerun-2026-06-21.md).

- live stack health 확인: API `:12701`, admin/user UI `:12705`, Dagster `:12702`.
- 1차 전체 suite: 629 passed / 1 failed.
- 실패는 제품 기능이 아니라 `home-density-matrix.spec.ts`의 `page.goto("/")`가 full `load`를
  기다리던 하네스 민감도 문제였다.
- `T-UI-E2E-LIVE-20260621`로 잡고 `gotoHome()`을
  `waitUntil: "domcontentloaded"`로 조정했다.
- 재검증: `npm run type-check:e2e` passed, 실패 케이스 단독 passed,
  리베이스 후 현재 브랜치 별도 live stack(`api :12711`, `admin/user UI :12715`,
  `dagster :12712`)에서 전체 live UI e2e `631 passed`.

## 2026-06-21 Codex 작업 메모 — UI e2e 테스트 3배 확장

사용자 지시에 따라 UI e2e를 기존 209개에서 631개로 확장했다. 정본 보고서:
[`docs/reports/ui-e2e-density-expansion-2026-06-21.md`](reports/ui-e2e-density-expansion-2026-06-21.md).

- 신규 `home-density-matrix.spec.ts` 422개 추가:
  - 공용 shell/nav 18개 항목의 href/icon/same-tab/a11y name/mobile/viewport matrix
  - 홈 metric count 포맷, import job/dedup summary, Backend/Dagster 상태 badge
  - endpoint 실패 노출/비노출 정책, 새로고침 refetch
- 검증:
  - `npm run type-check:e2e` passed
  - 신규 spec 단독 `422 passed`
  - 전체 Playwright e2e `631 passed`

## 2026-06-21 Codex 작업 메모 — 사용자/admin UI live e2e dev/prod green

사용자 지시에 따라 dev에서 사용자/admin UI live e2e를 먼저 평가했다. 정본 보고서:
[`docs/reports/ui-live-e2e-dev-prod-copy-2026-06-21.md`](reports/ui-live-e2e-dev-prod-copy-2026-06-21.md).

- WSL dev stack: API `:12701`, Dagster `:12702`, admin/user UI `:12705` ready.
- 안정화:
  - `run-admin-stack.sh`가 깨진 Dagster console-script shebang을 현재 venv Python entrypoint로
    fallback 한다.
  - Next 16 dev server는 e2e 스택에서 `next dev --webpack`으로 띄워 Turbopack panic을 우회한다.
  - Playwright artifact/report는 OS temp로 이동해 Next watcher 간섭을 제거한다.
  - mock e2e의 `/_next/` 정적 자산 passthrough, `home-nav` deep-link 안정화,
    feature-update-request 폴링 race gate를 반영했다.
- 검증:
  - unmocked live spec 6개/19 tests passed
  - 전체 admin e2e `209 passed`
  - `npm run type-check:e2e`, `bash -n scripts/run-admin-stack.sh`, `git diff --check` passed
- prod 복사/검증:
  - dev 변경과 `.env` 계열 설정을 `F:\dev\kor-travel-map` prod worktree로 복사했다.
  - 기존 `.env`는 `.backup-20260621-115048`로 백업했고, 최종 재복사 전
    `.backup-20260621-122939`도 추가로 남겼다.
  - prod stack을 새 `.env` 기준으로 재기동한 뒤 전체 admin e2e `209 passed`를 다시 확인했다.

## 2026-06-21 Codex 작업 메모 — concierge/geo prod API 계약 재점검

사용자 지시에 따라 형제 repo를 로컬에서 다시 읽고 prod live smoke를 수행했다. 정본 보고서:
[`docs/reports/prod-api-live-contract-check-2026-06-21.md`](reports/prod-api-live-contract-check-2026-06-21.md).

- `kor-travel-concierge`는 `origin/main` `bec63ad2ab39` 기준 export 계약
  (`/api/v1/features/{snapshot,changes}`, `X-API-Key`, `{items,next_cursor,has_more}`,
  `limit<=500`, provider/dataset/source identity)이 현재 Dagster fetcher와 provider
  loader에 맞았다. prod env에서 snapshot/changes `limit=1` 200, fetcher 첫 item read,
  live item → `FeatureBundle` 변환 성공.
- `kor-travel-geo`는 `origin/main` `8b7efbe20e92` 기준 v2 후보 좌표가
  `PointV2{lon,lat}` 정본이다. `kortravelmap.geocoding`의 REST 파서가 구 `x/y`만
  읽던 drift를 수정해 `lon/lat` 우선 + `x/y` fallback으로 맞췄다.
- live smoke: geo geocode/reverse/regions-within-radius 통과, concierge export/loader
  read-only smoke 통과. DB write나 Dagster materialize는 실행하지 않았다.
- 검증: `test_geocoding.py` 58 passed, 관련 ruff passed,
  `test_providers_kor_travel_concierge.py` + Dagster `test_provider_fetchers.py`
  71 passed / 1 skipped(`mois.db` optional).

**다음 한 작업은 기존과 동일하게 T-229-buildx**(GITHUB_TOKEN이 있는 배포 환경에서
arm64 multi-arch buildx 검증)이다.

## 2026-06-20 Codex 작업 메모 — Claude PR #481~#484 리뷰 후속

사용자 요청으로 2026-06-19 00:00 KST 이후 Claude Code가 올린 merged/closed PR #481~#484를
확인했다. 기존 리뷰 스레드는 없었고, closed PR #481/#482/#483에 리뷰 코멘트를 남긴 뒤 세
결함과 full-run 검증 중 드러난 logging 격리 결함을 하나의 후속 브랜치에서 수정했다.

- **#481 후속**: 직접 `docker compose` 실행 또는 `KOR_TRAVEL_MAP_ADMIN_WEB_PORT` 커스텀 포트에서
  API CORS fallback이 `12705`로 고정되던 문제를 고쳤다.
- **#482 후속**: live `kor-travel-geo` v2 응답의 `point: {lon, lat}`를 기존 `{x, y}` 전용
  파서가 처리하지 못하던 문제를 고쳤다. geocode/reverse 경로 모두 `x/y`와 `lon/lat`를 수용한다.
- **#483 후속**: host network override가 bridge용 `KOR_TRAVEL_MAP_DOCKER_*` 기본값을 물어
  `dagster`/`rustfs` 주소를 유지하거나 external Postgres 포트/DSN override를 덮던 문제를 고쳤다.
  host 모드는 `127.0.0.1:<12xxx>`를 기본으로 렌더하고, 명시 external override를 보존한다.
- **검증 후속**: Alembic migration logging 설정이 기존 `kortravelmap.*` logger를 disable해
  full-run 순서에서 `caplog` 테스트가 실패하던 문제를 `disable_existing_loggers=False`로 고쳤다.
- **검증**: `docker compose config`로 default/host/external 렌더와 커스텀 admin port CORS를 확인하고,
  geocoding 단위 테스트에 `point.lon/lat` 케이스를 추가했다.

**다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
(`GITHUB_TOKEN` 필요).

## 2026-06-19 Codex 작업 메모 — admin frontend stack 문서 정합성 정리

사용자 요청으로 architecture 계열 문서의 frontend stack 표현을 현재 구현 기준으로
정리했다.

- **지도**: admin frontend는 `maplibre-vworld-js`/`maplibre-vworld` dependency를 쓰지 않고,
  `maplibre-vworld-react` web/core 모델을 내부 포팅한 MapLibre GL + VWorld 구현을 쓴다고
  정정했다.
- **테이블**: 운영 목록/검토 화면은 공용 `DataTable`
  (`@tanstack/react-table` v8 + `@tanstack/react-virtual` v3) 기반이며,
  shadcn `Table`은 표시 primitive라고 명시했다.
- **정리 대상**: `architecture.md`, `debug-ui-package.md`, OpenAPI/frontend workflow 문서,
  ADR index/ADR-045, Sprint 문서, VWorld key 문서.

**다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
(`GITHUB_TOKEN` 필요).

## 2026-06-18 Codex 작업 메모 — README 진입 문서 정리 PR 대기

사용자 요청으로 루트 README를 현재 운영 모델 기준의 짧은 진입 문서로 정리했다.

- **정리 범위**: 소개/운영 모델/책임 범위/빠른 시작/저장소 구조/핵심 규칙/검증/문서 길찾기.
- **중복 제거**: 긴 provider·ETL·문서 세부 목록은 `docs/etl/`, `docs/architecture/`,
  `docs/runbooks/`, `docs/adr/README.md` 등 정본 문서로 포인터화했다.
- **다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
  (`GITHUB_TOKEN` 필요).

## 2026-06-18 claude 작업 메모 — PR #476 리뷰 + admin e2e 라이브 검증

- **#476 리뷰**: LOW 1건(`frontend.yml` stale 주석 — 제거된 maplibre-vworld git dep 참조) 정정,
  코드 결함 없음.
- **admin e2e 라이브**: Windows dev server :12706 + Playwright chromium으로 route-mock 전 spec
  **197 passed / 0 failed**. WSL은 win32-only `@next/swc` node_modules라 `next dev` 불가 → Windows 실행.
  backend-의존 4 spec(curated-features·features-new·dagster·etl)은 제외(Docker 미기동, 기결정).
- **라이브가 잡은 #471 잠복 회귀 정정**: `home.spec.ts`(Backend/Dagster heading → `서비스 상태` +
  service-backend/dagster testid), `features-list.spec.ts`(`bg-primary` → `bg-brand`). #477 home-nav
  수정도 라이브 green 확인.

**다음 한 작업**: in-repo 즉시 실행 트랙 없음(잔여 `T-229-buildx` 배포환경 · `T-101` 보류 ·
`T-AUDIT-0616` F-01 옵션 A deferred).

## 2026-06-18 Codex 작업 메모 — T-MAP-VWORLD-04 dependency 제거 완료

사용자 요청으로 GitHub Task #475(`T-MAP-VWORLD-04`)를 만들고,
`digitie/maplibre-vworld-react` `a7cb0f8` 기반 admin web 지도 정리를 완료했다.

- **제거**: admin frontend와 `@kor-travel-map/map-marker-react`에서
  `maplibre-vworld`(`digitie/maplibre-vworld-js`) dependency/peer/devDependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언 제거. lockfile에서도
  `maplibre-vworld`와 전용 transitive 제거.
- **보강**: `vworld-style.ts`를 `vworld-map-core`식 tile URL/style/maxZoom/redaction
  경계로 정리하고, `VWorldMapView`에 maxZoom clamp, redacted error logging, stable marker
  click callback을 반영. VWorld key 미설정 fallback 계약은 유지.
- **검증**: admin type-check, marker typecheck/build, admin vitest 27 passed,
  ESLint 0 errors(기존 warnings 6), Next build, Windows Playwright 지도 e2e
  `features-map-interactions.spec.ts` 5 passed.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

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
  (kor-travel-geo-postgres 등)와 충돌하고, 로컬(Claude worktree) ignored `.env`가 구
  `KRTOUR_MAP_*` prefix(현 코드는 `KOR_TRAVEL_MAP_*` — 미스매치)라 기존
  `python-krtour-map-claude` 스택은 stale/unhealthy다.
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

- provider repo(`python-*-api`)가 2026-06-22부로 전부 public 전환되어 `GITHUB_TOKEN`
  없이도 `.[providers]`를 빌드할 수 있다. arm64 빌더(QEMU/네이티브)만 있으면 수행 가능하다.

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
