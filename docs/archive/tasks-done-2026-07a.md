# tasks-done-2026-07a.md — tasks-done.md 아카이브 (2026-07-27 ~ 2026-07-31)

> `docs/tasks-done.md`에서 2026-08-31 분리(규약 §8). 읽기 전용 이력.

## 2026-07-31 — T-VN-CI-PG 임의 ref PostGIS 수동 gate

- [x] **T-VN-CI-PG — workflow_dispatch 전용 PostGIS integration 경로**

  `.github/workflows/postgis-only.yml`은 GitHub UI의 branch/tag 선택기 또는
  `gh workflow run postgis-only.yml --ref <ref>`로 지정한 ref를 checkout한다. Python
  3.13에서 메인·REST API·Dagster 패키지를 editable로 설치하고 Docker testcontainers 기반
  `pytest tests/integration -q --no-cov`만 실행한다. `contents: read` 최소 권한과 30분 timeout을
  고정했으며 기존 `ci.yml`의 Python matrix·coverage 합산·fixture replay는 변경하지 않았다.
  pinned `actionlint 1.7.7` 검증과 diff check를 통과했다.

## 2026-07-31 — T-VN-12A/B/C/D domain command idempotency

- [x] **T-VN-12A/B/C/D — 재시도 가능한 write command의 단일 ledger 전환 (PR #906)**

  정적 registry가 55개 write route의 retryability와 ledger 등록 완전성을 검사하고,
  Feature·curation·review와 import·offline·backup/restore command를 actor-scoped
  `Idempotency-Key`, canonical body fingerprint, terminal replay와 `409` conflict로 통일했다.
  migration `0070_domain_command_ledger`는 DB-only transaction과 외부 효과 execution을
  분리하고, backup/restore/swap의 immutable effect token·Docker fence·secure marker·수동
  reconciliation 경계를 정본으로 만든다. Admin UI는 actor 경계에서 stable command key를
  생성·폐기하며 body surrogate dedupe를 제거했다.

  단일 적대 리뷰어의 최종 exact head `b2169512` 판정은 P0/P1/P2 0건이었다. Python
  3.11/3.12/3.13, lint, OpenAPI drift, fixture replay, frontend build와 PostGIS integration
  8개 check가 모두 성공했고, PR #906은 merge commit `01aa335f`로 `main`에 반영됐다.

## 2026-07-31 — T-VN-H31R curation 주소·행별 provenance fail-close

- [x] **T-VN-H31R — DB/REST/admin 경계의 curation provenance 완결 (#909, PR #910)**

  주소 후보를 구조화 field·Unicode literal hierarchy·versioned alias로 제한하고
  `address_hint` 단독 자동 링크를 제거했다. migration `0072_curation_provenance`는
  import batch/row/link decision을 append-only 정규화하며 DB immutable trigger,
  batch→row `RESTRICT`, same-item composite FK와 exact current pointer를 강제한다.
  official 등대 import는 sidecar를 hard-require해 행별 durable provenance를 저장하고,
  batch/current-row 조회와 stable cursor link audit를 REST/OpenAPI/admin type으로 제공한다.

  Feature merge는 trusted accepted link만 재승인한다. external item별 canonical
  survivor/provider/operator winner를 결정적으로 하나만 고르고 loser current를 coalesce한다.
  source-absent component history는 legacy 정본 동기화 뒤 master로 옮겨 active unique와
  projection/current pointer를 함께 보존한다. 단일 적대 리뷰의 최초 P1 2건·P2 3건·P3 1건과
  재리뷰 신규 P2 1건을 모두 닫았고 exact `e69f8926` 최종 판정은 P0/P1/P2/P3 0건이다.
  관련 unit/API/실 PostgreSQL 195건, merge 29건, legacy projection clean DB 5회 반복,
  admin frontend 286건과 정적/OpenAPI/보안 gate가 통과했다.

## 2026-07-31 — PR #732 설계 결정의 현재 정본 반영

- [x] **T-VN-DOC-732 — 인증·canonical ops·C6c/C7 문서 정합성**

  닫힌 미병합 PR #808의 오래된 task snapshot은 가져오지 않고, PR #732가 확인한
  header-only public 인증, principal-only actor, canonical datasets/pipeline과
  compatible-pair 설계를 최신 main에 선택적으로 반영했다. ADR-060·076, REST 카탈로그,
  cross-repo 통합 지도, 성능 문서와 C7 runbook이 현재 OpenAPI 및 완료된 production
  cutover를 같은 상태로 설명한다.

  C6c/C7 관련 Map·Manager·PinVi issue를 다시 대조해 완료 이슈는 모두 closed임을
  확인했다. 남은 Map #819는 외부 HAProxy `timeout tunnel` 운영 설정이 필요한 별도 보류
  항목이므로 이 문서 task에서 닫지 않는다. 코드·DB·runtime 변경과 새 live 실행은 없다.

## 2026-07-30 — Lane B b1 T-VN-16C sparse weather 생산자·소비자

- [x] **T-VN-16C Map 생산자 — sparse 다중 날짜 weather batch**

  `POST /v1/features/weather/batch`를 날짜별 실제 Feature만 받는
  `targets[{target_at, feature_ids}]` 계약으로 전환했다. 고유 parent의 spatial 후보를
  한 번 계산하고 target별 bitemporal fact로 source를 고른 뒤 target-local
  `card_key`·`cards[]`로 metric 반복을 제거했다. planning/source-series/metric/payload와
  PostgreSQL `statement_timeout`을 독립 제한하며 timeout은 DB 취소 완료 뒤 503으로
  변환한다.

  실데이터 40 target × 5 Feature는 200 pair·공유 card 40개·11,763 metric을 5.77초에
  반환했다. 적대 리뷰어 2명의 최종 finding은 P0/P1/P2 0건이며, 보존
  `ktm-tvn45-db`의 sparse found·401·422·`active→hidden→retired`·cleanup/audit 0을
  파괴적 API Live로 검증했다.

  PinVi PR #421은 Trip view를 sparse batch 단 한 번으로 소비하고 31일
  `not_requested`·worker fan-out을 제거했다. target/card strict ordering과 7-state
  projection을 owner/shared Web 경로에 함께 적용하고 vendored OpenAPI를 Map #902와
  맞췄다. 장기 여행 파괴적 Live UI와 전체 gate를 통과한 뒤 merge commit
  `e79a09d46e5500437418be29e0df341dcad139bd`로 병합됐다.

## 2026-07-30 — Lane B b1 T-VN-16B PinVi weather batch 소비

- [x] **T-VN-16B — PinVi weather batch 소비 cutover** (PinVi PR #420)

  Trip 상세/공유 view의 단건 weather N+1을 날짜별 Map batch projection으로 전환했다.
  `found|no_data|retired|suppressed|missing|unavailable|not_requested`를 day-scoped
  union으로 구분하고, 고유 날짜 31개·worker 4개·view 전체 10초 budget과 부모 request
  취소 전파로 outbound를 제한했다. Web은 서버 view만 렌더하며 단건 weather를 호출하지
  않는다.

  적대 리뷰어 2명의 최종 finding은 P0/P1/P2 0건이었다. 재사용
  `ktm-tvn45-db`에서 실제 parent 여섯 상태, weather found/no_data/retired,
  weather-only 503→복구, 단건 요청 0회와 활성 Trip 잔존 0건을 파괴적 Live UI로
  통과했다. PinVi PR #420은 전체 CI green 뒤 squash merge됐고 merge commit은
  `9eb95c6f0e02eeec11ff7b49a4ca8ab2654758c2`다. 날짜 fan-out과 31일 상한 제거는
  `T-VN-16C`로 분리했다.

## 2026-07-30 — Lane B b1 T-VN-16A set-based weather batch

- [x] **T-VN-16A — Map set-based weather batch**

  service-token 전용 `POST /v1/features/weather/batch`가 중복 없는 Feature ID 1~200개를
  한 PostgreSQL statement에서 순서 보존 조회한다. `target_at`/`known_at` snapshot,
  `current`/24시간 `timeline`, `found|no_data|retired`를 구분하고 단건 weather도 같은
  repository를 재사용한다. metric은 provider/domain과 원래 유효 구간·선택
  `effective_at`을 보존하며, 만료 range와 known-at 이후 forecast를 current에서 제외한다.

migration `0069_weather_series_catalog`는 physical-series registry, series exact-prefix
effective-time index와 공개 `kind='weather'` 전용 partial GiST를 한 번만 만든다. 후속 DDL
실패 재시도는 valid index를 재사용하고 invalid 잔재만 다시 만든다. 실데이터 clone에서
단건 17.8ms, 200건 1.27s, weather fact Seq Scan 0을 확인했다.

큰 delta 적대 리뷰어 2명이 range 만료, provider/domain 동률 결정성, 대형 index 이중 build와
재시도 rebuild를 찾아 회귀와 함께 닫았고 최종 P0/P1/P2는 모두 0이었다. 파괴적 Live에서 새
series FK를 helper가 모르던 실패를 해당 지점에서 재현해 exact fingerprint/parent lock/FK
audit를 추가했다. main·recovery가 모두 통과하고 소유 Feature/change request/weather/price/
series 잔여는 0이다. 새 clone·dump·checkpoint·downgrade 없이 `ktm-tvn45-db`를 head
`0069_weather_series_catalog`, healthy 상태로 보존했다.

## 2026-07-30 — Lane B b1 T-VN-H39 schedule pending barrier

- [x] **T-VN-H39 — Mocked schedule command pending barrier**

  workers=8에서 600ms 응답 지연보다 pending 단언이 늦게 시작하던 schedule command
  테스트를 `scheduleActionResponseGate`로 전환했다. route가 `commandBodies`를 기록해 요청
  도달을 증명한 뒤 테스트가 응답을 잡아두고, `finally`에서 반드시 해제한다. pending과
  release 뒤에 같은 5개 control(사유·즉시 실행·시작/중지·기본값 복귀·cron)을 각각
  disabled/enabled로 대칭 검증하며 timeout은 늘리지 않았다.

격리 포트에서 실패 spec은 setup 포함 **2/2**, frontend Vitest **278 passed**,
TypeScript·ESLint가 통과했다. exact production image checkpoint D workers=8은
**276/276**, manifest 일치, child exit 0·reporter gate true로 끝났고 owned
container/network/image는 모두 0건이다.

작은 delta 적대 리뷰어 1명은 release 뒤 cron/stop만 복원 확인해 나머지 control의
sticky-disabled 회귀를 놓치는 P2를 찾아, 동일 locator 집합의 대칭 상태 helper로 고정했다.
DB는 사용하지 않았고 보존 `ktm-tvn45-db`는 healthy·`0068_integrity_last_seen`라 다음 DB
작업에 재사용한다.

## 2026-07-30 — Lane B b1 T-VN-H38 failure fingerprint 완전성

- [x] **T-VN-H38 — Mocked failure manifest retry/error fingerprint 완전성**

  reporter는 deterministic failure와 expected flaky의 모든 non-passed retry, 모든
  `TestResult.errors`와 각 오류의 중첩 `cause`, result에 없는 leaf/parent step error를 각각
  검증한다. `failed`와 실제 Playwright test timeout인 `timedOut`만 실패 증거로 인정하고,
  `skipped`·`interrupted`와 expected failure의 passed-only 결과는 원인 증거 누락으로
  fail-closed한다.

  Playwright timeout은 ANSI를 제거한 exact generic envelope, 같은 timeout 값, 같은 hook의
  strict descendant result leaf를 함께 만족할 때만 wrapper를 제외한다. path 없는 test-body
  envelope도 같은 timeout leaf가 실제 result에 있을 때만 제외해, caught locator 뒤 별도
  hang·beforeEach 뒤 독립 afterEach timeout·soft assertion 뒤 별도 body hang을 숨기지 않는다.
  result에 직접 있는 parent error뿐 아니라 result에 없는 step-only parent도 자체 stage로
  검사한다. Playwright 1.60은 boxed propagation과 boxed 내부의 독립 재투척을 reporter
  metadata로 구별할 수 없으므로, descendant stage를 빌려주는 추론을 금지하고 fail-closed한다.

retry/error 합성 회귀 **28 passed**, frontend Vitest 전체 **278 passed**, TypeScript·ESLint가
통과했다. exact production image checkpoint D workers=4는 **276/276**, manifest 일치,
child exit 0·reporter gate true로 끝났고 owned container/network/image는 모두 0건이다.
report에는 retry·실제 result error index·cause depth·status·category·source
basename/line만 남기며 error text와 `TestStep.title`의 실제 입력값은 기록하지 않는다.

적대 리뷰어 2명은 skipped retry와 expected flaky 누락, `timedOut`/unexpected-pass false-red·
false-green, boxed propagation/독립 재투척의 식별 불가능성, hook/body/afterEach envelope
인과, ANSI title 비밀 노출을 실제 Playwright 1.60 probe와 합성 반례로 찾아 모두 회귀로
고정했다.
workers=8 exact D에서 600ms 지연보다 pending 단언이 늦게 시작한 schedule command 1건은
제품 회귀가 아닌 별도 동기화 결함으로 분리해 `T-VN-H39`로 등록했다. DB는 사용하지 않아
`ktm-tvn45-db`를 clone·restore·migration·downgrade 없이 보존했다.

## 2026-07-30 — Lane B b1 T-VN-H37 Mocked checkpoint 결정성

- [x] **T-VN-H37 — Mocked checkpoint 종료 판정·고병렬 flaky 진단**

  checkpoint runner는 reporter의 원래 `result.status`·gate 판정·발견 test 수와 Playwright
  child exit status/signal, 실행 전후 postcondition, cleanup 실패를 서로 다른 redacted
  issue code로 남긴다. manifest가 일치해도 child가 nonzero면
  `playwright_child_nonzero`로 실패하며 원인 없는 exit가 되지 않는다. cleanup은 1초 Docker
  client 종료코드 대신 exact 소유 container/network/image가 실제로 사라졌는지를 제한
  polling해, daemon 정리가 늦은 정상 상태와 실제 잔존을 구분한다.

  workers=8에서 재현된 change review 목록은 BFF 응답 완료를 기다린 뒤 row를 단언하고,
  pipeline create pending 검증은 700ms 시간 지연 대신 테스트가 직접 해제하는 response
  barrier를 쓴다. 단순 timeout 증가는 없다.

합성 종료 판정 회귀 **4 passed**, checkpoint 격리 회귀 포함 **13 passed**, 배포 자동화
단위 **8 passed**, frontend Vitest 전체 **259 passed**, TypeScript·ESLint가 통과했다.
exact production image checkpoint D는 동일 SHA에서 workers=8과 workers=4가 각각
**276/276**, manifest 일치, child exit 0·reporter gate true로 끝났고 매 실행 뒤 owned
container/network/image는 모두 0건이다. 이 task는 DB를 사용하지 않아
`ktm-tvn45-db`를 clone·restore·migration·downgrade 없이 그대로 보존했다.

적대 리뷰에서 child signal을 test failure로 분류하던 P2를 infrastructure failure(exit 2)로
정정하고, assertion 실패 시에도 response gate를 `finally`에서 해제하며 filesystem cleanup
실패 뒤 Docker cleanup을 계속하도록 보강했다. reporter가 첫 retry/error fingerprint만
검사하는 기존 잔여 위험은 범위 확장 규칙에 따라 `T-VN-H38`로 분리했다.

## 2026-07-30 — Lane B b1 T-VN-11A/B service batch 5상태 호환 쌍

- [x] **T-VN-11A — Map 5-state batch projection**

  service-token 전용 `POST /v1/features/batch`가 최대 200개 ID를 순서 보존 set-based
  snapshot으로 조회한다. `found|retired|suppressed|missing|unchanged` 각 arm은 PostgreSQL
  `bigint` 범위 revision을 가지며 `found`만 고정 `trip_card` projection을 반환한다. 중복 ID와
  범위 밖 validator는 422, upstream DB 실패는 503이다. 200개 planner gate는 PK index와
  frozen response shape를 검증한다.

- [x] **T-VN-11B — PinVi typed consumer cutover**

  PinVi는 같은 OpenAPI snapshot을 vendor해 다섯 arm을 exhaustively decode한다. 최대 200개
  chunk, generation/revision fence를 가진 bounded LRU cache, transport-only `unverified`
  fallback, Web·Map·Mobile 공용 상태 resolver와 canonical `coord` snapshot을 사용한다. 서로
  다른 저장소라 하나의 GitHub PR 대신 생산자·소비자 호환 PR 쌍으로 검증하고 Map → PinVi
  순서로 landing한다.

적대 리뷰에서 지도 좌표 shape 불일치, out-of-order cache rollback, 동일 revision 상태 복구를
막는 negative fence, chunk 상한·revision 범위, 실제 실패한 planner-default gate, DB 장애의
500 누출, 문서 drift를 찾아 모두 수정했다. service perf target **3 passed**, DB 장애 503
OpenAPI/단위 회귀를 고정했다. 재사용 `ktm-tvn45-db`에서 다섯 상태와 강제
503·복구를 파괴적 Live UI로 검증했고 지도 포인트 4곳도 확인했다. fixture는 원복하고 전용
container/listener는 제거했으며 clone은 healthy `0068_integrity_last_seen`로 보존했다.

## 2026-07-30 — Lane B b0 T-VN-49A/B/C/D React 구조 debt 완결

사용자 지시에 따라 네 단계는 브랜치와 PR을 나누지 않고 한 번에 구현·검증했다. 이 완료
아카이브도 H49 코드와 같은 merge commit으로만 `main`에 들어간다.

- [x] **T-VN-49A — Feature·review admin 상태기계 분해**

  dedup/enrichment/admin features/change requests/new feature를 query·mutation·form·panel
  책임으로 나눴다. dedup/new feature의 결합 상태는 reducer로 옮겼다.

- [x] **T-VN-49B — admin data-ops 상태기계 분해**

  curation collections/files/issues/offline uploads/POI cache targets를 분해하고 issues의
  결합 상태를 reducer로 옮겼다. offline upload form은 파일·form·create mutation을 직접
  소유해 상위 controller의 거대 prop 전달을 제거했다.

- [x] **T-VN-49C — public map·home 분해**

  curated feature map/features map/home에서 domain state와 표현 section을 분리했다.
  지도 adapter나 단순 전달 wrapper를 새로 만들지 않았다.

- [x] **T-VN-49D — ops pipeline·datasets 분해와 구조 예외 제거**

  datasets/logs/execution detail/timeline/request/schedule을 분해했다. request dialog는
  scope·target·execution form 경계와 좁은 memoized section으로 재구성했고 render 중
  상태 변경을 파생 상태로 대체했다. `no-giant-component` 19개와
  `prefer-useReducer` 3개 exact 예외는 모두 제거했다. 실제 transport lifecycle인
  `live.ts`와 외부 event effect인 datasets의 규칙별 최소 예외만 남겼으며 verifier가
  그 exact 목록을 고정한다.

적대 리뷰어 2명이 authored 전체 delta를 검토했다. 늦은 geocode/reverse 응답이 최신 입력을
덮는 문제, reset 뒤 stale 응답 재유입, request/offline-upload의 flat prop-bag 우회,
enrichment callback identity churn을 찾아 모두 수정했고 전체 재검토 P0~P2는 0건이다.
지연 geocode가 사용자가 나중에 바꾼 도로명 코드를 보존하는 Playwright 회귀도 추가했다.

검증은 React Doctor **280 files, 0 issues**, Vitest **254 passed**, TypeScript·ESLint·production
build green이다. Mocked checkpoint D는 serial과 workers=4에서 각각 **275/275**, expected/
actual failure·flake·skip과 종료 자원 모두 0이다. 보존 clone을 새로 복제하거나 복원하지 않고
`ktm-tvn45-db`를 재사용한 파괴적 Live UI는 main/recovery 각각 **2/2**, `complete/passed`다.
active acceptance Feature·nonterminal request·FK와 runner container/network/image/listener/
BLOCKED는 모두 0이고 clone은 healthy다. 기존 v5 checkpoint가 정상 soft-delete audit 6행
때문에 더는 exact하지 않아 현 상태로 baseline만 다시 서명했으며 Alembic downgrade와 full
restore는 실행하지 않았다.

## 2026-07-30 — Lane A a1 T-VN-H30A/H33/H36: curation 오링크 해소와 자동링크 금지

PR #888(H30A) · PR #890(H33/H36). 세 task 모두 적대 리뷰로 **결론이 되돌아간** 이력이
본문에 남아 있다 — 특히 H33은 `[x]` → `[~]` → `[x]`로 두 번 움직였고, 그 원인이
"측정 도구의 산물을 데이터의 성질로 읽은 것"이었다. 그 기록을 지우지 않고 옮긴다.

- [x] T-VN-H30A — **검증 finding을 `ops.data_integrity_violations`에 durable 기록**

  migration `0067_integrity_dedupe_key` + `0068_integrity_last_seen`,
  `sync_integrity_findings()`와 `record_address_validation_findings()`로 구현한다.
  PR #888 사후 감사에서 확인된 결함까지 현재 Lane B PR에서 보강했다.

  - `jsonb ||`는 shallow merge라 재실행 시 `EXCLUDED`의 null이 1회차 증거를 덮어썼다
    (durable ledger 안에서 증거 소실). `jsonb_strip_nulls`로 차단.
  - key는 `source_record_key`나 원천 id 문자열을 직접 싣지 않는다.
    provider/dataset/`source_entity_type`/`source_entity_id`/violation code 전체의
    `av2_<sha256>`(68 bytes)로 고정해 payload 변경·entity type 재사용·B-tree 행 크기 한계를
    함께 차단한다.
  - `ops.data_integrity_violations`에 statement 트리거가 있어(실측) finding당 INSERT가
    `ops_live` revision 단일 행에 배타 락을 잡고 트랜잭션 끝까지 유지했다 — admin 쓰기 차단·
    동시 run 직렬화·데드락. `dedupe_key` 정렬 후 `unnest` 단일 statement로 접어
    트리거 1회·잠금 순서 1개로 고정한다.
  - recurrence는 최초 `detected_at`을 보존하고 별도 `last_seen_at`을 갱신한다.
    `/admin/issues` cursor도 최신 관측 시각을 쓴다. FK target은 최신 recurrence로 갱신하고,
    Feature 삭제는 `ON DELETE SET NULL`이라 ledger 행을 지우지 않는다.
  - client 결과는 `observed/unique/upserted`를 구분해 내부 중복을 미기록으로 오산하지 않는다.
    DB 기록 실패는 typed error이며 strict 경로는 validation `Failure` 전에 fail-closed한다.

  > **자동 close는 없다** — 배치마다 sweep하면 같은 run의 다른 batch finding을 닫고,
  > 부분 unique index 밖으로 밀린 행이 다음 run에 다시 생성되며, 빈 bundle sentinel이 큐를
  > 전부 닫는다. `T-VN-H32`에서 run marker 기반으로 별도 설계한다.

- [x] T-VN-H33 — **curation_items 오링크 3건 정리 (H25B 파생)**

  **`[x]` → `[~]` → `[x]`로 두 번 움직였다.** 처음 닫은 근거("import가 재링크하지 않는다")가
  적대 리뷰 실측으로 반증돼 되돌렸고(아래 "철회"), `T-VN-H36`이 그 재링크 경로를 실제로
  막은 뒤에야 닫았다. **지금 닫는 근거는 "안 될 것이다"가 아니라 "막았고 측정했다"다** —
  `T-VN-H36`이 커밋 CSV 486행 전수 재생으로 이 3건이 자동 링크 대상에서 빠지는 것을
  확인했다(`reports/h36-link-impact-2026-07-29.json`).

  `scripts/h33_unlink_mislinks.py` (dry-run 기본, `--apply`로 쓰기).
  - **노출 실증** — 해제 전 남이섬 feature(서울 중구 사무소)에 한국관광100선 **2건**,
    청남대 feature(전남 영암)에 **1건**이 붙어 응답에 나왔다.
    표면은 `/v1/curations/*`이며 **익명 공개가 아니라 `RoutePolicy.PUBLIC_KEYED`** —
    public API key 보유자에게 열린 표면이라는 한정 아래 읽어야 한다.

    > **🔴 철회 — "해제 후 0건"의 근거가 반증 불가능했다.**
    > 초안 확인 스크립트는 `/v1/curations/features/{feature_id}`만 호출했는데, 이 엔드포인트는
    > curation이 없으면 200+빈 배열이 아니라 **404**를 낸다. 스크립트가 `curl -s`로 status를
    > 버리고 에러 본문을 파싱해 "0건"을 출력했으므로, **존재하지 않는 feature_id를 넣어도
    > 같은 출력이 나온다**(리뷰 실측). 오타·삭제·401이 전부 "해소됨"으로 읽혔다.
    > 이 세션에서 반복된 "측정 도구의 산물을 데이터의 성질로 읽기"와 같은 형태다.
    >
    > 대체 증거는 `scripts/h33_verify_public_exposure.py`다 — negative control(없는 id)과
    > 구별되지 않으면 **스스로 경고**하고, 반증 가능한 표면을 근거로 쓴다:
    > 컬렉션 상세가 200으로 item 110·114건을 돌려주고 그 안의 대상 3건이 `feature_id=null`,
    > `q=남이섬` 검색은 5 group을 내놓는 **양성 대조**를 가지며 그 안에 오링크 feature가 없다.
    > 즉 **item은 공개 응답에 그대로 있고 feature 링크만 끊겼다** — 해제이지 삭제가 아니다.
    > 부수로 e2e 기대값도 확인된다: 공식 19개 컬렉션 public membership 합계 **486 유지**
    > (`item_count`가 미연결 item도 세므로 unlink가 기대값을 깨지 않는다).
  - **탐지기 재실행** ([after 산출물](../reports/h33-mislink-after-2026-07-29.json)) —
    `db_linked_rows` **3269→3266**, `db_region_codeable` **112→109**, `db_sido_mismatch` 3→0.

    > **"3→0"만 인용하면 안 된다.** 탐지기 모집단은 `ci.feature_id is not null` inner join이라
    > **링크를 끊으면 그 행이 모집단에서 빠진다** — 0은 관측이 아니라 정의다(리뷰 지적).
    > 엉뚱한 행을 끊었어도, item을 지웠어도 0이 나온다. 정보를 가진 숫자는 오히려
    > `3269→3266`·`112→109`, 즉 **정확히 대상 3행만 빠졌다**는 사실이다.
  - **ledger 방출** — `ops.data_integrity_violations`에 `curation_feature_region_mismatch`
    3건. **`open`이다**(초안은 `resolved`였으나 철회 — 아래). `feature_id` 컬럼은 비우고
    payload에만 남긴다: 이 FK가 `ON DELETE CASCADE`라 문제의 feature를 지우면 "잘못
    링크돼 있었다"는 기록까지 같이 사라진다.
  - **재실행 안전** — `--apply` 재실행은 "이미 해제" 3건으로 끝나고 finding만 갱신한다.
    지목한 오링크 `feature_id`를 가진 행만 대상으로 하며, 형제 행(같은 item의 다른
    component)은 정상으로 보고 경보를 울리지 않는다.

  > **🔴 철회 — "재링크되지 않는다"는 틀렸다.**
  > 초안은 *"공식 CSV import가 `feature_id = EXCLUDED.feature_id`로 덮어쓰는데 이 3행은
  > CSV가 비어 있으니 다시 링크되지 않는다"*고 적고 그 근거로 task를 닫았다.
  > **적대 리뷰가 prod에서 실측으로 반증했다.** `EXCLUDED.feature_id`까지만 읽고 거기
  > 무엇이 들어오는지 보지 않은 것이다 — 빈 `feature_id`는 링크를 막는 게 아니라
  > `curation_repo._RESOLVE_FEATURES_BATCH_SQL`의 **이름 자동매칭을 켠다**
  > (`WHERE requested.feature_id IS NULL AND lower(f.name) = lower(requested.place_name)`,
  > `address_hint`도 비어 있어 주소 필터는 건너뛴다). 단일 매칭이면 그 id가 그대로
  > `EXCLUDED.feature_id`가 된다.
  > **커밋된 CSV의 빈 264행 중 단일 매칭으로 해석되는 건 정확히 이 3행뿐이고, 전부 방금
  > 끊은 그 feature로 되돌아간다** — prod에 `남이섬`·`청남대`라는 이름의 live feature가
  > 각각 하나뿐이고 그게 바로 틀린 그 feature이기 때문이다.
  > 게다가 import는 `metadata = EXCLUDED.metadata`로 무조건 덮으므로 위에서 남긴 사유도
  > 지워진다. 그래서 finding을 `resolved`가 아니라 `open`으로 되돌렸다.
  > 지금 당장 되살아나지는 않는다 — prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이
  > 없어 import 자체가 실패한다. **`T-VN-H35`가 마이그레이션을 적용하는 순간 되살아나므로
  > H36이 H35보다 먼저여야 한다.**
  >
  > **덧붙인 정정 — 나는 배포되지 않은 코드로 prod 동작을 주장했다.** 위 인용
  > (`feature_id = EXCLUDED.feature_id`)은 **브랜치 코드**다. 배포 중인 이미지
  > (`kor-travel-map-api-latest`, revision `c8ed6164`, 2026-07-27)의 `_UPSERT_ITEM_SQL`은
  > `ON CONFLICT (collection_id, external_item_id, feature_id) WHERE archived_at IS NULL`이고
  > **SET 절에 `feature_id`가 아예 없다** — 그 코드에서는 재링크가 안 일어난다.
  > 즉 "지금 prod는 안전하다"는 맞지만 **내가 댄 이유는 prod에 존재하지 않는 코드였다.**
  > 같은 커밋에서 "머지 ≠ 배포"를 교훈으로 적어 놓고 마이그레이션에만 적용하고
  > **코드 주장에는 적용하지 않았다**(리뷰 지적).

  > **부수 발견 — prod가 마이그레이션 4개 뒤처져 있다.** ledger 방출을 붙이다가
  > `ON CONFLICT`가 두 번 실패했다. 원인은 코드가 아니라 **prod alembic head가
  > `0063_pipeline_root_id`**라는 것이었다 — H30A가 만든 dedupe 부분 유니크 인덱스(`0067`)가
  > **prod에 존재하지 않는다**. H30A의 dedupe 효과는 현재 prod에서 작동하지 않는다.
  > → `T-VN-H35`로 분리한다. 또 `source_record_key`에는 `provider_sync.source_records`
  > FK가 걸려 있어 curation 키를 넣을 수 없다(ledger가 provider 적재 전제로 설계됨).

- [x] T-VN-H36 — **curation import가 이름만으로 자동 링크한다 (H33 파생, H35보다 선행)**

  **완료(2026-07-29)**. `_adopted_match`로 **CSV `feature_id`가 빈 행은 후보 수와 무관하게
  링크하지 않는다**. 후보는 버리지 않고 `candidates`로 계속 노출하므로 운영자가 preview에서
  보고 admin에서 직접 링크할 수 있다 — 자동으로 붙는 것만 없앴다.

  **AC 결과**

  | AC | 결과 |
  | --- | --- |
  | H33의 3건이 import 후에도 미연결 | ✅ 막히는 자동링크가 **정확히 그 3건** |
  | 정당한 링크 손실 수치 | ✅ **0건**. 막히는 3건 전부 region 불일치(강원→서울 ×2, 충북→전남) |
  | 미연결 사유 구분 | ✅ `unmatched`(후보 없음) vs `name_only_match`(이름만 맞는 후보 있음). 사유 문장에 후보 소재 시도명이 들어간다 |
  | e2e 기대값 | ✅ 486 불변 — `item_count`가 미연결 item도 세므로(실측) 링크가 줄어도 membership은 안 바뀐다. 기대값 갱신 불필요 |
  | 반증 가능성 | ✅ 아래 |
  | 배포 순서 | ✅ **H35 이미지에 반드시 포함**. 아래 |

  근거 산출물: [`reports/h36-link-impact-2026-07-29.json`](../reports/h36-link-impact-2026-07-29.json)
  (`scripts/h36_link_impact.py`, 커밋 CSV 486행 전수 + prod 리졸버 SQL 재생, 읽기 전용).
  빈 264행의 후보 분포는 **0건 256 / 2건 이상 5 / 1건 3**이다.

  **반증 가능성** — 이 세션에서 반복해 무너진 지점이라 명시한다.
  - 변경이 아무것도 안 막았다면 `blocked_autolinks`가 0으로 나온다.
  - 링크를 통째로 껐다면 `csv_specified`(222)가 0이 된다 — 이 값은 리졸버가 아니라
    **CSV 파일**에서 오므로 두 숫자가 같이 움직이지 않는다.
  - 리졸버 조회가 죽었다면 후보 분포가 전부 0이 된다.
  - 테스트에도 대조를 넣었다: **음성 대조**(후보 0건은 여전히 `unmatched` — 리졸버가 통째로
    죽은 것과 구분), **양성 대조**(CSV가 `feature_id`를 적은 행은 그대로 링크 — "링크 기능을
    껐다"면 실패). 대조 없이 "전부 미연결"만 보면 성공과 고장이 구별되지 않는다.

  **배포 순서 — 이 변경은 `T-VN-H35` 이미지에 포함돼야 한다.**
  H35의 인수에는 commit 모드 import 실행이 들어간다(live spec의 `palaceComponents`
  단언은 `0066` backfill이 `legacy:<uuid>`로 채우는 값을 실제 import로 덮어야 성립한다).
  그 실행 시점에 이 게이트가 이미지에 없으면 3건이 그 자리에서 되살아난다.

  **표면 비용 0** — SQL·DTO·openapi·마이그레이션 무변경. `code`는 openapi에서 자유
  문자열(`CurationImportIssueView.code: str`)이라 새 코드를 늘려도 생성 타입·프런트
  수기 union·배지 맵이 안 바뀐다. `ImportRowStatus`(enum) 확장은 그 5지점 연쇄를 부르므로
  **일부러 피했다**. 후보 시도명은 `FeatureMatch.address` jsonb에 이미 있어(리졸버가 이미
  SELECT한다) 리졸버 SQL을 넓히지 않았다.
  기존 테스트 **23건 무손상**(27 passed) — 라우터 import 테스트 중 비어 있지 않은 후보를
  돌려주는 것은 하나뿐이고 그건 `feature_id` 명시 경로다.

  <details><summary>원래 정의 (완료 전)</summary>

  `curation_repo._RESOLVE_FEATURES_BATCH_SQL`은 CSV `feature_id`가 비면
  `lower(f.name) = lower(place_name)` 단독으로 후보를 찾고, 단일 매칭이면 그대로 링크한다.
  `address_hint`가 비면 주소 필터도 걸리지 않는다. **지역 교차검증이 없다.**
  H33이 끊은 3건이 정확히 이 경로로 되살아난다(prod 실측: 빈 264행 중 단일 매칭 3행 =
  H33 대상 3건, 전부 틀린 feature로 복귀).
  또 `metadata = EXCLUDED.metadata`가 무조건 덮어써서 "링크 금지" 사유를 남길 자리도 없다.

  선택지: (a) 리졸버에 시도/시군구 교차검증 추가, (b) import가 존중하는 명시적 "링크 금지"
  표식, (c) 이름 단독 매칭 시 자동 링크 대신 `review`로 떨어뜨리기.
  **H35(마이그레이션 적용)보다 먼저 해야 한다** — 지금은 prod가 `0063`이라 import 자체가
  실패해 우연히 막혀 있을 뿐이다.

  **당시 AC(역사 기록 — 열린 task checkbox 아님)**
  - 이름 단독 일치만으로는 자동 링크되지 않는다. H33이 끊은 3건이 import 후에도
        미연결로 남는 것을 **실데이터로** 확인한다(preview 경로로, prod 쓰기 없이).
  - 정당한 링크를 과도하게 잃지 않는다 — 현재 링크 222건 중 이 변경으로
        재현되지 않는 건이 몇 건인지 **수치로** 제시한다. 0이 아니어도 되지만 밝혀야 한다.
  - 자동 링크되지 않은 행에 **왜**가 남는다(import 리포트 issue 또는 metadata).
        운영자가 "그냥 안 붙었다"와 "지역이 어긋나 막았다"를 구분할 수 있어야 한다.
  - e2e 라이브 기대값(공식 19컬렉션 membership 486, `OFFICIAL_FILES` 행 수)에 대한
        영향을 밝힌다. 바뀐다면 기대값도 같은 PR에서 갱신한다.
  - 검증이 **반증 가능**하다 — 변경이 실패했다면 다른 결과가 나오는 측정인지
        (negative control / 양성 대조) 명시한다. 이 세션에서 반복된 실수다.
  - 배포 순서: prod가 `0063`/이미지 `c8ed6164`라는 사실이 이 변경의 적용 순서에
        미치는 영향을 기록하고, H35와의 선후를 확정한다.

  **비목표**: 미연결 264건을 사람이 링크하는 작업 자체(그건 `T-VN-H34`/`T-VN-H31`).
  여기서는 **잘못 붙는 것을 막는 것**까지만 한다.

  </details>

  > **부수 정정 — "prod는 import 자체가 실패한다"는 틀렸다.** H33 작업 중 나는
  > *prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이 없어 import가 실패하므로 3건이
  > 당장 되살아나지는 않는다*고 적었다. 조사 결과 **배포된 이미지(`c8ed6164`)의 import
  > 코드에는 `source_present`/`external_component_id` 참조가 0건**이라 prod 스키마와
  > 정합하며 **오늘도 정상 동작한다**. 또 CSV import는 `_UPSERT_ITEM_SQL`이 아니라
  > `_BULK_UPSERT_ITEMS_SQL`을 탄다(전자는 admin 단건 POST 전용). 즉 "HEAD 코드를 prod
  > 스키마에 돌리면 실패한다"가 참일 뿐, 내가 그걸 "prod에서 import가 실패한다"로 옮겨
  > 적은 것이다. **또 배포되지 않은 코드를 prod 동작으로 읽었다.**

## 2026-07-29 — Lane B b0 T-VN-48 mocked drift·격리 clone Live 완료

- [x] **T-VN-48A~C** — 최초 273-test baseline의 deterministic drift 89건을
  Feature·검토 15건, ops 5건, auth/shell 69건으로 고정하고 단계별로 제거했다.
- [x] **T-VN-48D** — checkpoint D를 exact `823ba52b`에서 serial과 workers=4로 각각
  **274/274** 통과했다. expected/actual failure·flake·skip은 모두 0이고, 종료 뒤 self-owned
  container/network/image와 loopback listener도 0건이다.
  - [x] **D.1~D.3** — restore 전용 owner를 정규화하되 원본 owner invariant는 별도 검증하고,
    fail-closed dump를 정확히 하나일 때만 재사용하며, PostGIS `extconfig` OID를 안정적인
    schema+relation identity로 바꿨다. 실제 schema-only restore에서 extension digest
    동등성을 확인했다.
  - [x] **D.4** — 경량 v5 baseline과 선택적 full restore certification을 분리했다. v5는
    custom archive 구조·dump SHA256·clone snapshot·write fence를 서명하고
    `full_restore_verified=false`를 명시한다. 이번 최종 gate는 migration/schema/복구 계약이
    바뀌지 않아 이미 보유한 dump와 clone을 재사용하고 전체 restore를 반복하지 않았다.
  - [x] **D.5~D.6** — Feature 승인으로 정상 증가한
    `ops.ops_live_topic_revisions.dataset_projection` 한 행을 시작값으로 정규화하되,
    서명 dump의 직전 행을 대입한 전체 digest가 checkpoint와 정확히 같고 revision이 `+1`인
    경우만 허용했다. `direct-cleanup-running → recovery-resource-finalizing`의 정확한
    forward-recovery만 인정해 UI·fixture를 반복하지 않고 기존 evidence에서 완료했다.
  - [x] **D.7** — production MapLibre의 늦은 실제 `idle` event가 raster `sourcedata`
    계측에 섞이던 Mocked race를 repaint+idle+rAF barrier로 제거했다. 최초 serial은 이 한 건만
    실패한 273/274였고, 실패 spec 수정 뒤 같은 gate를 재개해 serial/parallel 모두 통과했다.
  - [x] **D.8** — PR CI가 `record_address_validation_findings()`의 typed
    `IntegrityFindingSyncResult` 계약과 Dagster asset 테스트 double 12개의 구 `int` 반환
    drift를 세 Python 버전에서 공통 검출했다. 모든 double을 실제 결과 타입으로 맞추고 Dagster
    package 전체 **510 passed, 1 skipped**, coverage **83.66%**와 Ruff를 통과했다.
- [x] **파괴적 Live** — 보존 clone의 본 acceptance와 recovery-only가 각각 **2/2**다.
  result는 `complete/recovered`, raw→normalized 전체 content 증명과 topic revision `+1`을
  기록했다. active acceptance Feature·pending change request·direct weather/price/FK,
  BLOCKED/quiescence/scratch/temp DB·role, runner container/network/image는 전부 0이다.
  v5 custom dump는 다음 task 재사용 판정 대상으로 보존했다.
- [x] **리뷰·감사** — branch-authored delta는 적대 리뷰 2인과 국소 후속 검토에서 P0~P2
  0건이며, 규칙 변경 전에 완료한 issue #881의 Claude Code PR #888 사후 감사 수정도 같은
  변경 집합에 포함했다.

## 2026-07-29 — Lane A a1 T-VN-H28A/B: #673 주소 검증 규칙 교체 (한 PR)

> **정정 (적대 리뷰 반영)** — 아래 "payload 행정코드 == geo 행정코드이므로 전부 오탐"이라는
> 근거는 **무효**다. concierge의 payload 코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로
> 호출한 캐시본이라 자기 자신과의 비교였다. 결론(380건 좌표 오류 아님)은 유지되지만 근거는
> 독립 축(provider 원천 텍스트 + 정지오코딩)으로 다시 세웠다 — 375건은 텍스트에 행정구역
> 토큰이 없어 좌표와 무관하게 통과 불가, 4건은 축약·단계 차이, 1건은 143 m 경계.
> 이름 축은 **삭제하지 않고** 결함만 고쳐 warning으로 유지한다(전 provider 적용).
> 상세: docs/reports/concierge-address-mismatch-evidence-2026-07-29.md

- [x] **T-VN-H28A** — 운영과 동일한 코드 경로(live concierge export → 실 geo reverse 주입 변환
  → `validate_feature_bundles_address`)로 재기준화했다. 증거:
  [`reports/concierge-address-mismatch-evidence-2026-07-29.md`](../reports/concierge-address-mismatch-evidence-2026-07-29.md).
  - 1,430/410 → **1,477/380** (현상 유효).
  - drop 380건이 **전부 오탐**: payload 시군구코드 == geo 시군구코드 380/380. 진짜 불일치 **0건**.
    후보 전체(1,477)로 넓혀도 코드 불일치 0건.
  - 380/380이 payload에 시군구·법정동 코드를 **모두** 보유 — 권위 축이 있는데 규칙이 안 썼다.
  - 실패의 365/380은 `부산 기장 조방국밥`처럼 **행정구역명이 없는 짧은 주소**. 규칙이 잰 것은
    좌표-주소 일치가 아니라 provider 주소 문자열의 완전성이었다.
  - reverse 최근접 거리 `<10m` 210 / `<100m` 136 / `<1km` 34 — 좌표는 정확했다.
- [x] **T-VN-H28B** — 이름 축을 판정에서 제거하고 행정코드 교차검증으로 교체했다.
  - `AdminEvidence`(신규 DTO): 판정 두 축(좌표 reverse 코드 / payload 선언 코드)을 `Address`로
    **병합하기 전에** 보존한다. 병합 후에는 출처를 알 수 없어 교차검증이 원천 불가능했다.
  - 규칙: 코드 대 코드 접두 비교. 두 축이 모두 있을 때만 판정하고 없으면 **'통과'가 아니라
    '증거 없음'**으로 집계(`evidence_grade`). 리(8:10)는 `_bjd_code_from_emd_code`가 합성할 수
    있어 비교하지 않는다(8자리 캡).
  - **drop을 severity가 아니라 code allowlist로 전환**. 새 error 규칙이 추가돼도
    `DROPPABLE_ISSUE_CODES`를 명시적으로 고치기 전에는 영구 손실이 구조적으로 불가능하다.
    (`provider_address_mismatch`가 바로 그 방식으로 380건을 조용히 파괴했다.)
  - **batch 전멸 위험 제거**: payload에 `sigungu_code`만 있고 `legal_dong_code`가 없으면
    `Address._check_code_consistency`가 `ValidationError`를 던져 **1건이 1,477건 전체를**
    죽일 수 있었다(건별 격리 없음). `_address()`가 bjd에서만 유도하도록 바꿔 구조적으로
    불가능하게 하고, 건별 격리 옵션도 추가했다.
  - **회복 검증(live)**: 같은 export를 새 코드로 → **380 drop → 0, 1,477/1,477 적재, 손실 0.**
    교차검증 성립 1,372/1,477(92%), 행정코드 불일치 0건.
  - **replay 장치는 만들지 않았다** — 코드로 확인한 결과 불필요하다. drop은 적재 **전** 단계라
    dropped 후보는 `source_entities`에 행이 없고, concierge cursor는 영속화되지 않아 매
    materialize가 ledger 전량을 재생한다. 규칙만 고치면 자동 회복된다.
  - 검증: n150 CI-parity — ruff / mypy --strict(core 117·dagster 23) / dagster 494 passed +
    1 skipped / 관련 unit 179 passed. 신규 회귀 25건.
## 2026-07-29 — issue #881: Claude Code PR #882~#884 사후 감사

- [x] **PR #884 geo 인증·오류 계약 재감사** — backend가 VWorld public key를 URL query로
  계속 전송해 httpx INFO URL과 traceback frame에서 비밀이 노출될 수 있던 구조를 제거했다.
  Map API/Dagster/CLI는 geo public endpoint에 `X-KTG-API-Key` header만 사용하며
  credential은 `SecretStr`로 보관한다. admin trusted-proxy principal을 위임하지 않고
  transport/status 원본 예외도 연결하지 않는다.
- [x] **typed problem code 보존** — `GeoAuthNotConfiguredError`와 `GeoRequestError`가
  `/admin/issues`, offline-upload validation, feature-update HTTP adapter를 지나도 각각
  `GEO_AUTH_NOT_CONFIGURED`(503), `PROVIDER_ERROR`(502)로 유지되게 중앙 handler와 경계별
  problem+json 회귀 테스트를 추가했다.
- [x] **PR #882/#883 문서·계약 재감사** — PinVi가 읽지 않는
  `openapi-sha256.json`은 탐지력 없는 파생 산출물이므로 export/test/file을 제거했다.
  소비자 freshness는 실제 핀 commit의 spec/subset 비교만 정본으로 유지한다.
  완료된 H07C/H07D/H21/H29는 active backlog에서 제거하고 H27은 OPNsense 운영자 작업과
  quiet 2주기 검증 한 경로로만 정리했다.

## 2026-07-29 — Lane A a1 T-VN-H21: geo 인증 결선 검증·비밀 유출 차단

- [x] **T-VN-H21** — kor-travel-geo live 인증 결선을 검증 가능하게 만들고, 그 과정에서 드러난
  API key 유출 경로를 막았다. dedup 5건은 **브랜치 코드로** 실서비스에서 재통과(5 passed).
  후속 issue #881 감사에서 URL query 자체가 남긴 2차 유출 경로를 확인해 위 trusted proxy
  header 계약으로 교체했다. 아래는 PR #884 최초 landing 당시의 검증 이력이다.
  - 열린 질문이었던 "인증 뒤 runtime drift"는 **없음**으로 종결: 실 geo에 대해 reverse
    (status=OK, cand=11)·geocode(status=OK, conf=1.000) 응답이 기존 Pydantic 모델로 무손실
    파싱됐고, 배포된 Map api 컨테이너의 key가 geo 컨테이너 `KTG_VWORLD_API_KEY`와 동일함을 확인했다.
    → 원래 blocker는 배포 결선 결함이 아니라 **ad-hoc/CLI 실행 환경에 값이 없던 것**이었다.
  - **설계 전환(적대 리뷰 2명 합치)**: 호출 지점마다 preflight를 붙이는 최초 구현은 7곳 중 1곳만
    보호해 사실상 장식이었고, 이를 막으려 둔 AST 스캐너조차 같은 모듈 내 동명 변수 mutation으로
    우회됨이 **실제로 시연**됐다. `require_api_key` 기본 `True`로 **생성 시점** 검증에 옮겨
    CLI/API/Dagster/live test 4경로가 별도 조치 없이 보호된다(ADR-060 결과 절에 반영).
  - **오분류 수정**: 결선 누락을 `ValueError`로 던지면 기존 `except ValueError` 사다리에 걸려
    `/admin/issues`는 422, offline-upload는 409, feature-update는 422로 나갔다 — 없애려던
    좌표-vs-결선 오진을 API 안에서 재생산하는 상태였다. `GeoAuthNotConfiguredError` → 503
    (base_url 미설정과 동일 등급)으로 정정.
  - **비밀 유출 차단**: `str(httpx.HTTPStatusError)`가 `?key=<SECRET>` URL을 담고 그 문자열이
    502 detail·로그로 나갔다. query 제거한 `GeoRequestError`로 wrap. 회귀 테스트가 곧바로
    2차 결함을 잡아냄 — `from None`은 `__cause__`만 지우고 `__context__`에 원본이 남는다.
    except 블록 **밖에서** 던져 chaining 자체를 만들지 않게 고쳤고, 실 401 응답으로 확인했다.
  - 그 밖에: 128자 초과 key 사전 차단, CLI는 traceback(exit 1) 대신 stderr + `_EXIT_INVALID`(2),
    과장된 주석("요구한다" 무조건 / "route 처리 전에") 정정.
  - 검증: n150 CI-parity green — ruff / mypy --strict ×3(core·api·dagster) / lint-imports 4 kept,
    unit 1675 passed(잔여 3건은 main과 동일한 docker 바이너리 부재), api 792 passed,
    dagster 477 passed. live: 결선 차단·정상 좌표·오류 좌표·잘못된 키 4분기 + dedup 5 passed.

## 2026-07-29 — Lane A a1 T-VN-H29: 통합검색 map-import POI 좌표 null 복구

- [x] **T-VN-H29** (PinVi PR #418) — kor-travel-map curated import POI가 GET /search에서만 좌표
  null이던 실제 사용자 가시 버그를 고쳤다. 발견 경위는 T-VN-H07D 적대 리뷰의 소비자 전수 감사.
  - 근인: search.py::_snapshot_coord가 중첩 feature_snapshot["coord"]만 읽었는데, Map
    CuratedFeatureDetailFeatureSnapshotView는 extra=forbid이고 coord property가 아예 없어
    (H07D typed view) 좌표는 top-level lon/lat으로 온다 → 구조적으로 항상 None.
  - 비대칭이 힌트: 같은 payload를 admin_pois/kasi는 정상 해석해, admin·일출입 화면은 좌표가
    보이는데 통합검색만 null이었다.
  - 수정: 다섯 번째 추출기를 만들지 않고 정본 extract_feature_coord에 위임(기존 동작의 상위집합).
  - 회귀 위험 실증(리뷰어 2명): 비-map snapshot은 전부 중첩 coord이고 top-level
    x/y/geometry/location payload는 0건. 응답 계약도 기존 _coord/_float가 이미 처리. 같은 컬럼에
    admin/trips.py가 이미 같은 추출기를 써 표면 간 해석이 오히려 일치하게 됐다.
  - 리뷰 반영: 계약 게이트 주석·통합 문서의 "알려진 열화" 서술이 이 PR로 거짓이 되어 해소 기록으로
    정정. 커버리지도 배선(결과 dict→PlaceSearchResult.coord)·nullable lon/lat·0.0 좌표 보존까지 확장.
  - 검증: n150 CI-parity green(ruff/format/mypy), 신규 회귀 10 passed, 전체 unit 685 passed.

## 2026-07-29 — Lane A a0 T-VN-H07C: v5 승격 기각으로 종결 (a0 완료)

- [x] **T-VN-H07C** (#812) — 배포 compatible-pair에 pinned OpenAPI SHA를 넣는 v5 승격을 양
  저장소에 구현하고 테스트를 baseline까지 맞춘 뒤, 적대 리뷰 2명의 실증으로 **기각**했다
  (ADR-079). manifest는 v4 유지.
  - 근거 1: 제안 필드는 map_source_revision의 순수 함수라 추가 탐지력이 0이다. attestation은
    이미 그 revision을 운영자 제시 commit과 배포 이미지 OCI revision 라벨에 결박한다.
  - 근거 2: v5 전환 즉시 rollback이 무력화되고, 기존 프로덕션 이미지 revision에는 digest 파일
    blob이 없어 capture 자체가 불가능하다 — 운영자가 manifest 없는 상태에 갇힌다.
  - 유지: Map per-surface digest manifest(map#880, 207a6364)는 소비자 freshness 용도로 남는다.
    PinVi가 독립 사본과 대조하므로 그쪽에서는 실질 탐지력이 있다(H07B/H07D).
  - 폐기: docker-manager v5 브랜치, Map attestation v5 브랜치. 운영 문서·런북 무변경.
  - 규율 정정: OpenAPI 변경 완료 조건에서 재-capture/attestation 제거, per-surface digest 갱신 +
    소비자 스냅샷 재-vendor로 대체.

## 2026-07-28 — Lane A a0 T-VN-H07D: admin detail-snapshot 계약 + freshness 게이트 실효화

- [x] **T-VN-H07D** (#815 close) — cross-repo 2 PR. **① Map** PR #878(`5c0e0cae`), **② PinVi**
  PR #416(`8ea83358`).
  - **문제**: PinVi 큐레이션 import 런타임이 소비하는 admin detail-snapshot의 계약이 **OpenAPI로
    표현조차 되지 않았다**. PinVi가 읽는 plan-level 필드가 전부 free-form `dict[str, Any]`
    (`theme`/`content`/`source`/`feature_snapshot`) 안이라 스펙에 `{"type":"object"}`로만 나왔고,
    PinVi가 호출하는 경로는 `include_in_schema=False` 숨은 alias라 스펙 기반 게이트가 볼 수 없었다.
  - **① Map**: 생성부가 고정 key로 만드는 payload를 **typed view 4종**으로 전환.
    **etag는 repo payload dict 기준이라 그 dict을 손대지 않아 etag·캐시 계약 불변.**
    계약 게이트 9건(필드 핀 / 컨테이너 `$ref` 결합 / **alias 라우트 등록** / 생성부↔view 정합
    populated·all-null / **endpoint HTTP** 문서경로·alias × populated·all-null).
    `openapi.json` + frontend `types.ts` 동시 재생성.
  - **② PinVi**: 경로·응답 스키마의 **전이적 폐포 + securityScheme**만 결정적으로 추출한 subset
    (19 KB, full 1.1 MB 대비)을 vendor하고, 실제 소비 필드의 consumer 계약과 admin 인증 헤더
    header-only 계약을 고정. exact property 집합은 producer 소유라 중복 고정하지 않는다.
  - **freshness(핵심)**: 기존 live-compare는 sibling 체크아웃 부재로 skip되어 CI에서 항상
    green이었다. `contract-pin-consistency`(차단, `aggregate-ci.yml` required check 등록)가 Map을
    **핀 커밋**으로 체크아웃해 user는 byte, admin은 재추출로 **실제 비교**한다. 핀 자체의 뒤처짐은
    매일 도는 비차단 `contract-staleness`가 Map main과 비교해 알린다(H07B의 174-commit 사례).
  - **적대 리뷰 각 2명**. Map: 재생성 산출물 `types.ts` 누락(머지 blocker)과 `feature_snapshot`
    소비 여부 오판을 잡아 네 번째 typed view로 확장. PinVi: **"차단"이라던 job이 required check에
    없어 실제로는 아무것도 막지 못하던 것**을 잡아 실효화하고, job 이름을 증명 대상에 맞게
    `contract-pin-consistency`로 정정, `continue-on-error`가 죽이던 예약 알림 경로 복구,
    subset의 securityScheme 누락 보완, 계약상 불가능해진 e2e fixture 교정.
  - **검증**: 양쪽 n150 CI-parity green(Map api 790 passed / PinVi unit 675 passed),
    freshness 양쪽 실증, PinVi integration을 testcontainers로 실제 실행(1 passed),
    실제 CI에서 신규 게이트 pass(9s) 확인.
  - **파생 등록**: `T-VN-H29`(PinVi 통합검색의 map-import POI 좌표 null — `_snapshot_coord`가
    `coord`만 읽는데 Map view에 `coord`가 없어 구조적으로 항상 None).

## 2026-07-28 — Lane A a0 T-VN-H07B: PinVi consumer contract landing

- [x] **T-VN-H07B** — 오래 열린 PinVi #403(base 13 commits 뒤)을 재감사해 residual만 남기고
  **PinVi PR #415**로 landing했다(#403은 대체·종결). 재감사 핵심: #403은 Map producer 테스트를
  복사해 **공개 curated 표면**을 고정했으나 PinVi user client는 그 경로를 호출하지 않는다
  (`_CLIENT_PATHS`에 curated 없음, ADR-049/Map PR #533이 public `*-copy` 폐지, 큐레이션 런타임
  표면은 admin `/v1/admin/curated-features/{id}/detail-snapshot` = H07D 소유, producer exact
  고정은 H07A 소유). curated pin을 전량 제거하고 **PinVi가 실제로 읽는 필드**의 typed consumer
  contract(21 schema)로 대체했다.
  - **스냅샷 재동기화**: H07A의 실제 user OpenAPI SHA와 대조해 vendored 핀이 stale임을 확인
    (`91b30f40`@`cf1f0bba`, Map main보다 174 commits 뒤) → Map main `8880c29b`(H07A `259a9ec5`
    포함)/`0a7f1684`로 갱신. 실제 drift는 구조 1건(`external_component_id`, Map 0066) + 설명
    3건뿐이고 PinVi 소비 스키마는 구조 변화 0건.
  - **사슬 전체 고정**: 경로→컨테이너(`_ENDPOINT_DATA_SCHEMAS` 13경로 + `_CLIENT_PATHS` 일치
    가드) → 컨테이너→item(`items.$ref`)·map value(`found`→`FeatureDetailResponse`) → 필드
    type/format/enum/required/nullable. envelope `meta`(`Meta`/`ClusterMeta`/`PageMeta`)도
    client가 `data`로 re-projection해 소비하므로 함께 고정. `/v1/public/*`는 `model_validate`로
    객체 전체를 검증해 `app/schemas/public.py` `model_fields` ⊆ 계약을 강제(자기참조 검사 제거).
    `_SCHEMA_FIELDS`는 계약 표에서 파생. **exact property 집합은 의도적으로 비고정**(consumer가
    producer의 additive 변경에 false-red 나면 안 됨 — 0066이 실제 사례).
  - **검증**: n150 CI-parity clean clone `74b199d` — ruff/ruff format(343)/mypy --strict(196)
    green, 계약 11 passed, 전체 unit **665 passed**(base 661 대비 +4; 실패 20건은 base
    `417da20`에서 동일 실증된 기존 docker 의존 실패). **변이 테스트 30건 전부 검출**.
  - **리뷰**: 적대 2명 → 재리뷰 → 최종 확인(block) → 해제 확인(cleared). 최종 확인이 잡은 오기
    (`data.get("cluster_unit")`을 "항상 None인 잠재 버그"로 기록)를 정정 — client가
    `meta.cluster.cluster_unit`을 의도적으로 re-projection하며 기존 green 테스트가 non-None을
    단언한다. 같은 오독으로 빠졌던 meta 필드도 함께 고정했다.
  - PinVi 문서(`docs/integrations/kor-travel-map-rest-api.md` §8)는 같은 PR에 포함.

## 2026-07-28 — Lane B T-VN-46 npm optional tree 무결성 완결

- [x] **T-VN-46** — npm 10.9.4가 제외된 FreeBSD/WASM optional parent의 자식 6개를
  root `extraneous`로 남기는 Arborist 현상을 동일 lockfile에서 재현했다. npm 12.0.1과
  지원 Node 하한 22.22.2로 전환해 direct dependency 추가나 `npm ls` 출력 필터 없이
  `problems` 0건으로 만들고 기존 6-package allowlist를 제거했다.
- root `allowScripts`는 실제 install script가 필요한 `esbuild@0.28.1`과
  `unrs-resolver@1.12.2`만 exact version으로 허용한다. `.npmrc`의
  `strict-allow-scripts=true`와 `engine-strict=true`가 신규 script와 미지원 Node/npm을
  fail-close한다. workflow와 frontend/C7 Docker image도 같은 npm 12.0.1 계약을 사용한다.
- n150 clean install에서 audit 0, unreviewed install script 0, npm tree 0 problems,
  ESLint·React Doctor 0 diagnostics, Sharp SVG→WebP, admin/user OpenAPI codegen drift,
  두 type-check와 production build를 통과했다. npm 12 package-lock-only 재실행 drift도 0이다.
- 적대 리뷰어 2명이 exact 구현 head `378c6524`를 검토해 stale unit/doc, bare
  `allowScripts`, 과도하게 넓은 Node engine을 보강했고 최종 P0/P1/P2 0건을 확인했다.
- 재사용 실데이터 clone에서 candidate API/UI/C7 image로 파괴적 admin Feature acceptance를
  인증 setup 포함 **2/2, 37.9초** 통과했다. API-owned non-deleted Feature와 pending change
  request, weather/price fixture는 모두 0건이다. clone은
  `0066_curation_component_identity`, health 정상이고 다음 task 재사용 판정 전까지 보존한다.
  Playwright 상태/cookie·raw trace·screenshot·민감 로그·임시 env/session secret과 candidate
  container는 실행 직후 폐기했다.

## 2026-07-28 — Lane A a0 T-VN-H07A: Map #814 residual contract landing

- [x] **T-VN-H07A** — 오래 열린 Map #814(base 95 commits behind)를 최신 main 위 residual로
  재감사·landing했다(squash @ 259a9ec5). stale `docs/tasks.md` commit 2건과 main T-VN-05R가
  이미 소유한 union discriminator/mapping/oneOf 구조 assertion을 제거하고, main에 없는
  field-level 잔여만 남겼다: PinVi가 REST로 소비하는 curated feature variant 7·detail 5·
  PublicCuratedAddress·PublicCurationCollection/Item/CurationFeature/FeatureCurationGroup
  schema의 exact property/required 집합, 필드별 JSON type/format/enum/discriminator const/$ref
  대상을 생성 OpenAPI 기준으로 고정. n150 CI-parity가 base drift(migration 0066
  `external_component_id` required 추가)를 검출해 현행 계약으로 재조정했다. 적대적 리뷰어 2명
  (tautology·redundancy / contract-fidelity)이 전 schema를 실제 pydantic 생성 스키마·
  `openapi.user.json`과 대조해 land 판정했고, phones array element type 고정(nit)을 반영했다.
  n150 pytest 11 green + GitHub CI(lint/mypy/lint-imports·openapi-drift·pytest matrix·
  integration PostGIS) green. test-only OpenAPI 계약이라 admin-UI 표면 없음 — live 검증은 n150
  게이트가 실제 생성 OpenAPI에 대해 계약을 실행하는 것으로 갈음. PR #814.

## 2026-07-28 — PR #869 후 task 전면 재감사

- [x] **T-VN-REAUDIT-0728** — `tasks.md`·완료 이력·실코드와 Map/PinVi/
  docker-manager/geo의 열린 PR·이슈를 대조하고, 큰 task를 독립 PR·검증 단위로 분해했다.
  Agent A/B 소유 경계, migration·OpenAPI·frontend 충돌 barrier, Wave 2 freeze/join/final
  cutover 순서와 실패 지점 재개 규율을 고정했다. 적대적 리뷰어 2명이 legacy 조기 물리 삭제,
  compatible-pair 재-capture, idempotency·frontend ordering, H21 첫 blocker 표현과 문서 예외
  범위를 바로잡은 뒤 잔여 P0/P1/P2 0건을 확인했다.

## 2026-07-28 — Lane B T-VN-45 features map Live 라운드트립 완결

- [x] **T-VN-45 (#871)** — `/features` 실데이터 input-roundtrip을 실제
  `/v1/admin/features/in-bounds`의 `items`/`clusters` 계약으로 전환했다. 모든 새 query key의
  요청 bbox·kind·zoom과 성공 응답 본문을 검증하고, 취소된 요청도 URL 계약 검사를 건너뛰지
  않는다. cache hit는 새 HTTP 응답을 강제하지 않고 map idle 뒤 마지막 성공 응답의 전체
  point `feature_id` 집합·server cluster key/count/centroid와 실제 DOM이 일치할 때만
  수렴한다.
- **false-green 제거**: point marker, server cluster, coincident popup row에 각각
  `data-feature-id`/`data-cluster-key`를 노출했다. 식별자가 없는 marker도 빈 값으로 exact
  비교에 남겨 실패시키고, cluster는 표시 count와 MapLibre projection 기준 DOM 중심 좌표를
  1.5px 이내로 검증한다. 상세 클릭은 선택한 ID의
  `/v1/admin/features/{feature_id}`와 `AdminFeatureDetailResponse.data.feature`만 허용한다.
- **파괴적 Live UI**: n150 격리 prod clone에서 지도 저배율 cluster·서울/부산 items·kind
  필터·상세 클릭을 실패 지점별로 재개해 통과했다. 별도 write workflow는 실제 add 승인,
  update 승인, update 거절, 비활성화, delete 승인을 모두 수행해 인증 setup 포함 **2/2**
  (**48.3초**)를 통과했다. 최신 합성 Feature는 `deleted`이고 `deleted_at`/
  `user_deleted_at`가 모두 채워졌으며, 전체 합성 감사 범위는 non-deleted Feature **0건**,
  pending change request **0건**이다.
- **Live spec 동반 복구**: 파괴적 검증 중 확인한 ADR-066 이전 `operator` 입력, 접힌 고급
  JSON 섹션, 구 create/review/preview 접근성 이름과 번역 상태, 동시 필터 변경의 비결정적
  이름 검색을 현행 UI 계약에 맞췄다. admin 목록은 필터·정렬을 먼저 확정한 뒤 exact
  `feature_id` PK 검색 응답 본문과 row를 함께 단언한다. 적대 리뷰 뒤 update nested field
  보존, 비기본 `marker_icon=park`의 unchanged PATCH omission/결과 보존과 inactive exact 목록
  요청/응답까지 추가로 고정했다.
- **재개용 resource**: clone `ktm-tvn45-db`, dump와 redacted checkpoint는 PR 머지 뒤 다음
  task 착수 전 재사용 판정을 위해 보존했다. Playwright 인증 상태/cookie·raw trace·실데이터
  screenshot·민감 로그·임시 env/session secret은 재사용하지 않고 Live 종료 직후 폐기했다.
  `PGPASSWORD` metadata가 남아 있던 중지 상태의 clone transient container 8개도 제거했다.
  clone migration head는
  `0063_pipeline_root_id`, Feature **1,030,469건**, POI cache target **90건**이며 파괴적
  실행 후 clone health는 정상이다. 호환성·오염·디스크 판정 결과는 다음
  `resume.md`/`journal.md` 갱신에 기록한다.

## 2026-07-27 — Lane B T-VN-47 React Doctor + durable curation 완결

- [x] **T-VN-47** — React Doctor full scan을 269개 파일·actionable 진단 0건으로 만들었다.
  WebSocket cleanup·nested updater 부수효과·반복 helper·상태 파생·접근성 진단을 근인으로
  정리했다. frontend root의 `doctor.config.json`과 exact verifier가 shadow config·ignore,
  command/scope 축소와 package-level 우회를 거부한다. giant component 19개·reducer 후보 3개는
  별도 구조 설계가 필요해 exact scoped debt `T-VN-49`로 이관했다.
- [x] **T-VN-H13 후속 완결** — #862의 조건부 upsert를 source 누락·삭제→재등장·Feature merge까지
  확장했다. migration 0065가 `source_present`/`source_updated_at`과
  `operator_updated_by`/`operator_updated_at`을 분리하고 archived/NULL까지 포함한 exact identity
  unique를 강제한다. legacy projection은 `legacy_projection_id`로 durable item과 연결하며, stable
  collection key는 mutable slug 대신 theme/source UUID와 title hash를 사용한다. 중복 semantic
  collection은 `:split:<collection_id>`로 보존하고 임의 admin key 충돌도 migration 양방향에서
  덮어쓰지 않는다.
- **과거 drift 복구**: 0064 theme slug 재사용으로 collection owner가 탈취된 active/archived
  projection은 명시적 `legacy_projection_id`로 원 theme에 복구한다. canonical-only item은 원
  projection durable link가 없고 external identity도 theme 간 공유될 수 있으므로 자동 owner
  복구를 하지 않는다. upgrade 전 old projection 삭제 여부와 관계없이 모든 legacy-marker
  collection에서 `draft/admin_only` quarantine에 보존한다. admin PATCH로 mutable marker가 지워진
  이력도 immutable `legacy:` key namespace로 판별한다. exact `legacy:quarantine:<UUID>` key와
  immutable migration creator가 모두 일치하는 산출물만 재격리하지 않아 정상 `quarantine:` theme
  slug와 migration 왕복 identity를 함께 보존한다. mutable quarantine metadata에
  `migrated_from`이 추가돼도 upgrade·downgrade key rewrite에서 같은 결합을 제외한다.
  `source_record_key IS NULL`인 DELETE→새 UUID 재삽입도 기존 external identity와 operator
  tombstone을 재사용한다. legacy cross-title 이동은 target collection 뒤 source parent를
  잠그지 않고 item만 잠가 A→B/B→A 교착을 제거한다.
- **리뷰·검증**: 사용자 지시에 따라 단독 적대 리뷰어 1명이 PR840 이후 Claude Code 작성 PR
  #841~#845·#847~#850·#852~#857·#859~#864와 이번 exact code를 함께 감사했다. migration
  upgrade→downgrade→re-upgrade, 수동 base/split/staging key 선점, archived owner repair,
  canonical-only owner 증거 부재, 오래된 projection의 후속 owner 탈취, owner 간 동일 external identity,
  upgrade 전 old projection 삭제, metadata marker 제거, 정상 `quarantine:` theme slug,
  mutable quarantine metadata와 왕복 identity, null-source tombstone, 실제 두
  transaction 교차 이동을 포함한 관련 unit/integration/API 144건과 외부 geo live 5건을 제외한
  backend 전체 2,392건이 통과했다. static·frontend 전체 gate와 격리 실데이터 destructive Live UI
  근거는 같은 날짜 `journal.md` 항목을 정본으로 한다. curation exact code `7e2920aa`의 최종
  리뷰는 신규 P0–P2 0건·reviewer PostgreSQL 46/46이다.
- [x] **T-VN-H23** — T-VN-47 전체 실데이터 clone에서 발견한 0053 legacy active scope 중복
  blocker를 같은 PR에서 해결했다. 동일 scope의 queued job은 실제 dispatch 정렬로 winner 하나를
  보존하고 나머지를 기존 오류 문맥과 winner ID가 남는 `cancelled` terminal 상태로 전환한다.
  running 하나는 우선 보존하되 running 둘 이상 또는 cancellation audit marker가 걸린 중복은
  mutation 전에 fail-close한다. 실데이터와 같은 queued/now/now, running+queued, multiple-running,
  cancellation attempt/member 원자 보존과 downgrade/re-upgrade를 PostgreSQL 회귀로 고정했다.
  같은 단독 적대 리뷰어가 cancellation audit 훼손 가능성을 찾아 보강했으며 exact code
  `ca313d32`에서 잔여 P0–P2 0건을 확인했다.
- [x] **T-VN-H24** — 복합 공식 source item의 durable identity를 Feature target과 분리했다.
  `(collection_id, external_item_id, external_component_id)`가 membership을 식별하고
  `feature_id`는 nullable·mutable target으로만 둔다. CSV/API/UI/OpenAPI에 component key를
  전파하고 legacy UUID·operator/source/archive 이력을 첫 authoritative import에서 같은 행으로
  승계한다. 모호한 legacy 후보와 같은 source item의 active Feature 중복은 mutation 전에
  fail-close한다. 0064→0066 연속 업그레이드는 0065의 지연 FK·trigger event를 0066 첫 DDL 전에
  명시적으로 검사·소진해 단일 Alembic transaction에서도 안전하게 전진한다. n150 prod 격리
  clone에서 0036→0066 forward migration, 실제 UI CSV preview/commit과 REST/admin/지도 검증,
  공식 19 collections·486 source-present memberships, component 2/2, operator adoption 2,
  duplicate target 0, prod 불변을 확인했다. 실패 시 clone/build/import checkpoint를 보존해
  처음부터 반복하지 않고 실패 단계부터 재개했으며 성공 뒤 clone을 삭제했다.
- [x] **T-VN-H26 / #868** — main에 이미 반영된 c6c canonical
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias와 회귀를 재확인했다. 남은 수용 조건인 기존
  `KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET` fallback을 추가했다. 두 값이 함께 있으면 canonical이
  우선하며, 어느 값도 없으면 `None`, canonical로 로드된 secret에 잘못된 admin 헤더는 `403`이다.
  사용자 지시에 따라 이 추가 작업만 적대적 리뷰 예외로 처리했다.

## 2026-07-27 — Lane B T-VN-44 frontend lint·schedule recovery·가격 identity

- [x] **T-VN-44 (#858)** — frontend full ESLint를 0 warning gate로 고정하고 schedule 응답 유실
  복구, 가격 series identity `provider + price_domain + product_key`, migration 0064와 격리
  실데이터 Live UI를 완료했다. 세부 구현·검증은 같은 날짜 `journal.md` 항목과 CHANGELOG를 따른다.

## 2026-07-27 — T-VN-H20 prod admin credential 회전 완료 (login 200 검증)

- [x] **T-VN-H20** — prod admin password/hash 회전. credential-safe 스크립트(auth.ts와 동일 pbkdf2_sha256
  310k iter/256bit 파생)로 새 강한 password 생성 — 평문→gitignored `docs/prod-access.local.md`, hash→repo
  밖 scratch, stdout엔 경로·길이만(값 비노출). prod `.env`의 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH`를
  base-compose로 UI만 recreate(R2: `-f docker-compose.yml --no-deps --force-recreate`, override 배제)해
  회전. **검증**: 새 pw→login 200 + 오키/기존→401, 배포 컨테이너 hash 87자, UI healthy.
  - **인시던트+복구(투명)**: 최초 회전에서 hash를 `.env`에 raw로 써서 docker-compose가 `$310000$salt$hash`의
    `$<salt>`/`$<hash>`를 변수 interpolation→salt/hash 소거(배포 20자)→admin UI 일시 로그인 불가.
    python diag(.env 87 vs container 20 MISMATCH)로 규명→`$`→`$$` escape 재작성→recreate→87자 복원→200 확인.
    매 단계 `.env` 타임스탬프 백업(롤백 가능). **교훈**: compose `.env`의 `$` 포함 값은 `$$` escape 필수.
  - 잔여(사용자 판단): local doc stale 섹션(초기 미배포 gen) 삭제, session secret 미회전(기존 세션 만료까지
    유효 — 완전 폐기 시 별도 회전), n150 `.env.h20-*bak.*` 롤백 백업 정리.

## 2026-07-27 — Lane B b4 하드닝 3건 완결 (H13·H14·H15)

각 항목 적대 리뷰어 2명(blocker 0) + 회귀 테스트 + CI green(pytest/dagster/PostGIS) 후 머지.
(Lane A가 Lane B b4를 사용자 지시로 순차 대행.)

- [x] **T-VN-H13** — curation authoritative 재적재가 운영자 override 보존 (#699 → PR #862).
  `_BULK_UPSERT_ITEMS_SQL` ON CONFLICT DO UPDATE·WHERE + `_PREVIEW_IMPORT_COUNTS_SQL` 비교에서
  status/curation_relation/reuse_policy 제거 → CSV 재적재가 운영자 admin PATCH 편집을 리셋하지 않고
  provider 파생 필드만 갱신. 회귀 테스트(편집 보존 + provider 갱신 + preview/removed 카운트).
- [x] **T-VN-H14** — KREX traffic notice snapshot bounded retry self-heal (#700 → PR #863).
  연속 2 snapshot 완전일치 즉시-실패 → sliding bounded-retry(상한 4, 총 최대 5 snapshot, inter-retry
  delay 0.5s) + typed `KrexTrafficNoticeSnapshotUnstable`. 휘발성 feed 일시 불일치를 self-heal해 run
  반복 실패·notice 신선도 정체 완화. 안정 feed는 2 snapshot 즉시 yield(무변경). 테스트 3종(transient/
  persistent/exact-boundary).
- [x] **T-VN-H15** — c7 attestation IPv6 public origin bracket 정규화 + zone-id 거부 (#805 → PR #864).
  `_public_origin`이 IPv6 host를 bracket 없이 `f"{host}{port}"`로 재구성(모호)하고 zone-id 미거부하던
  것을 `[address.compressed]` bracket+canonical + `"%"` scope 거부로 수정. `run-c7-prod-live-e2e.sh`의
  병렬 canonicalizer도 동일 미러링(divergence 방지). domain/IPv4 무변경(기존 해시 보존).

## 2026-07-27 — T-VN-H19 public API key 양성 production runtime 실증 (C2 갭 종결)

- [x] **T-VN-H19** — #854에서 "등가 충족"으로 처리했던 C2(public-key→curated 200)의 DB lookup+hash
  compare 양성 분기를 n150 production(map=c8ed6164)에서 credential-safe 직접 실증. admin-BFF
  `POST /v1/admin/public-api-keys`로 임시 key 발급(평문 1회, 값 비출력) → **valid key 200 PASS**,
  wrong key **401 PASS**, `POST .../{id}/revoke` **200**, 폐기 후 same key **401 PASS**(revoke lifecycle).
  key 값은 출력·기록 안 하고 key_id·status만 증거. → **경계 매트릭스 14/14, T-VN-03+T-ADM-C6c 전체
  완료**("C2 전까지 완료 금지" 조건 해소). 증거: reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md §1 C2.

## 2026-07-27 — T-VN-H12 live acceptance status marker 좌표 run-unique jitter (live 검증 완료)

- [x] **T-VN-H12** — `admin-feature-acceptance-write.live.spec.ts`의 status marker 좌표를 `sha256(RUN_ID)`
  ±0.25° run-unique jitter(`STATUS_MARKER_LON/LAT`) + `recenterMapTo`로 전환해 죽은 run leftover의
  supercluster 병합(marker aria-label 소실, P2)을 제거. base `LON`/`LAT`는 127.5/36.5 고정 유지
  (weather/price/correction/search는 seeding helper `admin_feature_live_fixture.py` `_LON`/`_LAT` 고정과
  좌표 동기 필요 — featureId/query 단언이라 supercluster 무관).
  - **경과**: #855(shared base jitter, merged) → **n150 c7-v6 live 검증에서 weather/price seeding desync
    발견**(공식 runner latent bug: helper 고정 seed vs spec jitter 조회) → #859에서 **status-only jitter로
    국한 수정**(rebase over #858, merged `baa04c08`).
  - **검증**: n150 c7-v6 live(map=c8ed6164/pinvi=6a035695) status marker 단계 통과(recenter 실증) +
    e2e type-check + 4각도 적대 정적검증. weather/price는 고정 base = LIVE-01 통과 baseline이라 무변경
    (full official-lane 재검증 불필요 — behavioral 변경은 status marker에 국한). cleanup featureId 기반이라
    leftover 0.
  - **교훈**(journal 2026-07-27): 정적 적대검증이 이 회귀를 놓친 이유 = 외부 Python seeding helper의 좌표
    계약을 정적 모델에 못 넣음. cross-process 좌표 계약은 live 검증 필요.

## 2026-07-27 — T-VN-H17 map#684 조건 #8 검증범위 축소 후 종결 (LIVE-01 후속 7/7 close)

- [x] **T-VN-H17** — H16에서 keep-open된 map#684를 **조건 #8 검증범위 명시 축소**로 종결(사용자 결정:
  조건 축소). #684 조건 1~7 + owner 후속은 코드+mock+live로 충족. 조건 #8("mock e2e와 n150 live e2e에서
  검증")을 다음으로 확정: **live(n150)** = read/freshness/URL-복원/invalid-fail-closed
  (`ops-c7-read-auth.live.spec.ts`) + datasets **write 계약**(effective-scope refresh POST·active projection·
  reused_active_request, `ops-c7-kma-active-write.live.spec.ts`, T-ADM-C7 GREEN); **mock** = write-path
  **UI 엣지 전이 2건**(refresh done-terminal freshness invalidation `ops-datasets.spec.ts:1817`,
  polling 404/503 재시도 `:2440`). 근거: 반복 done-terminal은 prod Dagster refresh quota 소모 파괴적,
  404/503은 prod 인위 유발 곤란한 client-state 엣지 — write **계약**은 이미 C7 live 실증이라 UI 엣지는
  mock 적정. map#684 close. → **LIVE-01 후속 OPEN 7건 전부 종결**.

## 2026-07-27 — T-VN-H16 LIVE-01 후속 OPEN 이슈 7건 재검증 → 6 close / 1 keep

- [x] **T-VN-H16** — LIVE-01 후속 OPEN 7건의 독립 완료조건을 현재 main/배포·smoke 증거로 재검증
  (이슈당 1 에이전트 병렬 + 회의적 기본값). **6건 close, 1건 keep-open**:
  - **close**: `dm#70`(features routes 플래그 compose 명시, C6c smoke 교차확인) · `dm#63`(prod API env
    결선 PR #64, creds SET) · `map#777`(C7 attestation manifest v4 exact 강제 `c7_prod_attestation.py:423`) ·
    `map#712`(datasets fail-closed S2 active projection + 회귀 테스트 + C7 n150 live) · `map#719`(exact-scope
    이력 PR #728 filter-before-limit + continuation) · `map#694`(live E2E 의미 단언, PR #724 결함 surface 제거).
    각 이슈에 근거(file:line/PR/smoke) 포함 종결 코멘트 게재.
  - **keep-open**: `map#684` — 조건 1~7 충족이나 조건 #8의 write-path **live** 전이 2건(refresh done-terminal
    freshness invalidation·execution polling 404/503 재시도 UI)이 mock e2e에만 존재, n150 live lane 미구동
    → `T-VN-H17`로 잔여 구체화.

## 2026-07-27 — principal 경계 부분 실증 + PinVi #392 종결

- [x] **PinVi #392 observation-read principal** — PinVi 관측 caller가 ops:read로 200에 도달하고
  no-token은 401로 거부됨을 production에서 직접 실증했다. 배포=**map c8ed6164 / pinvi 6a035695**
  (둘 다 healthy, production profile).
- **부분 증거(T-VN-03/T-ADM-C6c 전체 완료 아님)**: 실행한 경계 smoke 13건은 모두 PASS했다.
  - curated: C1 keyless→401 · C3 service→200 · C4 admin-bff→200 · C4n secret-no-actor→401.
    C2 public-key→200은 DB lookup·hash compare 양성 runtime 분기를 직접 실행하지 않았으므로 미검증이다.
  - ops 6: O1 keyless→401 · O2 service-only→401 · O3 cancel-token→403 · O4 admin-bff→200 ·
    O5 ops:read→200 · O6 invalid→403.
  - MOIS: M1 production unmount→404.
  - 배포 전 정적 감사(워크플로우 `tvn03-c6c-readiness-audit`, 6차원 병렬+적대 반증): route policy
    exception 0, curated/ops/MOIS wiring, OpenAPI full/user 계약 일치 확인.
  - 증거: [t-vn-03-c6c-boundary-smoke-2026-07-27.md](../reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md).
  - C2는 열린 `T-VN-H19`에서 credential-safe 임시 key로 직접 실증한다. 그 전까지
    T-VN-03/T-ADM-C6c를 완료로 이관하지 않는다.

## 2026-07-27 — Lane B b0 T-VN-43 admin frontend npm 보안 0건 전환

- [x] **T-VN-43 (#851, merge `d0e7077ffb0cee4139997b8143371b1418bfd784`)** — clean npm audit의
  low 2·moderate 7·high 7을 모두 제거하고 Node/npm·Next/PostCSS/Sharp·Playwright를 exact pin했다.
  사용하지 않는 shadcn CLI/MCP·form graph를 제거하고 npm tree/effective ESLint/Redocly patch/실제
  Next-Sharp optimizer를 fail-close gate로 고정했다. Python 2,355 tests와 frontend type/build/Vitest,
  격리 Docker mocked 24/24, 운영 API에 연결한 공식 CSV 5종 파괴적 Live UI 4/4를 n150에서 통과했다.
  #840 이후 Claude PR 전문 감사 1명과 독립 적대 리뷰어 2명의 최종 finding은 P0~P3 0건이었다. 상세
  `docs/journal.md` 2026-07-27(codex).

## 2026-07-27 — T-VN-H06 admin 목록 keyset 런타임 검증 완결

- [x] **T-VN-H06** — admin dedup/enrichment 목록을 OFFSET → keyset+fingerprint cursor로 전환.
  - **backend**(#813, merge `9d29606e`): `admin_feature_repo.py` keyset 술어
    `(total_score, review_id) < (:cursor_score::numeric, :cursor_review_id::uuid)`,
    `_REVIEW_CURSOR_VERSION` fingerprint, composite index `idx_dedup_status_score`/
    `idx_enrichment_review_status_score`. 2차 적대 리뷰 P3 반영(가변 score 재스캔 재정렬 tradeoff
    docstring + active-cursor EXPLAIN 케이스 `test_t212d_perf_explain.py`, seq-scan 회귀 가드).
    CI `pytest integration (PostGIS)` green.
  - **e2e 검증**(#852 + 후속 Codex 보강): 현행 UI에 맞춘 spec drift 수정에 더해 네 deferred filter의
    원자적 수렴과 decision PATCH의 `reviewed_by` 비전송을 전 경로에서 음성 단언했다. n150 Linux
    Playwright에서 dedup 14 + enrichment 9 + auth setup 1, 합계 **24/24**를 통과해 기존 Windows-only
    증거를 대체했다. network-mocked 목록 검증이라 task의 파괴적 live 예외를 적용하며, keyset 실백엔드
    동작은 #813의 pytest integration(PostGIS) EXPLAIN 가드가 커버한다.

## 2026-07-27 — T-VN-LIVE-01 targeted live acceptance lane n150 PASSED (04A/58/15 종결)

- [x] **T-VN-LIVE-01 (+T-VN-04A #741·T-VN-58 #785·T-VN-15)** — targeted admin-feature live
  acceptance lane(#792 구현)을 n150 production(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행 →
  **PASSED**(rc=0, phase=passed, recovery_attempt=0, BLOCKED/ACTIVE 없음, active leftover 0).
  검증 범위: inactive/draft/hidden marker + hidden weather/price 카드 + public 비누출 + T-VN-15
  search total/continuation/CURSOR_QUERY_MISMATCH·FEATURE_SEARCH_CURSOR_TAMPERED 422 + #785 stale
  raw If-Match 412·dirty draft 보존·명시적 reload. **규명·수정 연쇄**(비-redact c7-v6 재현):
  helper host-network(#842) · map nav/zoom-contract·panel(#843) · Codex PR 리뷰 DSN/signal(#844) ·
  검색 pg_trgm 격리 32-hex(#845) · kind=place 격리(#848, cross-kind seed weather cluster). 인시던트
  복구(공유 pinvi DB migration → manifest trap) 후 c8ed6164로 재-cut. issue #741·#785 closed.
  적대 리뷰어 2명 반영(#848 P3 정정·P2→T-VN-H12 추적). 상세 `docs/journal.md` 2026-07-27.

## 2026-07-27 — Lane B b0 T-VN-42 지도 control·query identity·live recovery 하드닝

- [x] **T-VN-42 (#846)** — `/features`·`/curated-features` 상세 패널의 bottom-right `ScaleControl`
  비겹침 계약(공용 Playwright bounding-box assertion), live 전역 `reducedMotion` 제거 후 MapLibre
  `moveend`까지 클릭마다 대기하는 zoom helper, items/clusters in-bounds query key를 HTTP와 동일한
  정수 zoom·원본 bbox·명시적 mode로 통일, 서버 정수 zoom 기준과 UI cluster/items 분기 단일 함수화.
  #840 이후 Claude Code PR(#841~#845) 재감사로 #844 BLOCKED clear 신호 경쟁과 #845 cross-version
  recovery 가능성을 BLOCKED v3(source commit·API/Playwright image·pair·attestation hash 기록 +
  recovery runtime exact 대조로 mutation 전 cross-version cleanup 거부) 계약으로 차단. 상세
  `docs/journal.md` 2026-07-26(codex).

## 2026-07-26 전면 감사 정리 — C7 종결 + vNext Wave 0/1 합류 + 독립 하드닝 + Wave 3 측정

11-agent 전수 감사(2026-07-26)로 실코드 기준 완료 확정한 항목. C7 COMPLETE @ d5693269
(공식 6-spec prod gate full GREEN, `docs/journal.md` 2026-07-26).
- [x] **T-VN-08 — PinVi false-broken 수정** — PinVi PR #409(merge `423a8a3`): 외부 Feature
  해석을 `found|missing|unverified|not_linked`로 분리하고 transport·typed Map 실패는 마지막 snapshot을
  유지하는 `unverified`로 처리했다. opaque feature ID를 그대로 strict batch 계약에 전달해 구분자
  parsing을 제거했다. n150 실데이터 파괴적 live UI E2E는 web Map popup의 연결 장애→복구를
  검증했고, mobile 소비자는 TypeScript/type-check로 계약을 검증했다. 적대 리뷰어 2명 P0/P1/P2
  없음, CI 6-check green 후 squash merge. 5-state producer 계약은 별도 `T-VN-11`로 계속한다.

- [x] **T-ADM-C7-SCHEDCHURN** — 근인은 render churn이 아니라(오진), cron 저장 응답 유실 후
  frozen-idempotency 복구가 필요해질 때 cron 수정 dialog(Base UI)가 열린 채 남아 페이지 전체가
  inert가 되어 모든 schedule 컨트롤이 접근 불가가 되던 것. fix=`schedule-panel.tsx`(복구 필요
  순간 dialog close) + spec 하드닝(canReset·robustClick·settle-gate·시작 confirm alertdialog
  locator). 적대 리뷰어 2명 반영 → prod 재배포 후 재검증 GREEN → schedule-write blocking gate
  재편입. PR #838. 상세 `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7-POICAUSAL** — C7 게이트가 항상 poi-cache `@c7-causal`에서 red였던 원인은
  backend가 아니라 test-side 2중 버그: (1) `POI_HEADING` 영문 상수가 개편 B(`d8818994`) 한국어
  h1 통일 이후 stale → `gotoPoiTargets` 15s timeout; (2) `expectCausalDatasetProjectionUpdate`의
  `page.evaluate` 콜백 `connectionId` destructure 누락 → 상시 `ReferenceError`(cbe133c2 이래,
  heading 버그가 가림). PR #839(main d5693269) → 재-cut → 공식 게이트 full GREEN(6 spec 전부
  passed). **C7 COMPLETE at d5693269.**
- [x] **T-VN-SYNC-02 — integration/t-vn → main 최종 합류** — PR #790(2026-07-19, merge commit
  d93cb16e, base=main/head=integration/t-vn ancestry 보존, CI 8-check green). T-VN-57(#787) 선행
  머지 gate 준수. compatible-pair v4 activation은 2026-07-26 C7 재-cut으로 완결(map=d5693269 /
  pinvi=e60d1711, attestation self-verify PASS, 공식 6-spec gate GREEN). `integration/t-vn`
  통합 브랜치 규율은 본 합류로 폐지(이후 base=main).
- [x] **T-VN-57 — public route policy·OpenAPI security·user surface 단일 정본** (#784 closed) —
  PR #787: `_PUBLIC_CURATED_PATHS`/`USER_OPERATIONS` 수기 정본 제거, `build_route_policy_matrix`
  단일 정본화, runtime↔full↔user 양방향 전수 대조 CI(`test_export_openapi.py` — drift는
  ValueError로 거부), PUBLIC_KEYED=[PublicApiKey,ServiceToken]/PUBLIC_UNAUTHENTICATED=[]/
  SERVICE=[ServiceToken] 정확 선언, user-client TS 재생성.
- [x] **T-VN-59 — public weather·curation raw lineage 계약 분리** (#786 closed) — PR #788:
  public/operator DTO 분리(`PublicWeatherAlertHistoryItem` vs `AdminWeatherAlertHistoryItem`,
  `PublicCurationItemView` vs `AdminCurationItemView` — 상속 없음), user OpenAPI 재귀
  reachable-schema 금지 게이트(`USER_RESPONSE_FORBIDDEN_PROPERTIES` fail-closed, cycle/allOf/
  oneOf negative 테스트 포함), 수기 public curation client 동시 갱신.
- [x] **T-VN-H02R — standalone destructive fail-close·backup principal 감사 완결** (#796
  closed 2026-07-26) — PR #804 + companion docker-manager #68: compose 기본
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED:-false`, backup create/delete/restore/swap actor =
  `AdminProxyContext.actor`만, `RestoreSwapRequest.operator` 제거(+422 회귀), principal별
  registry 이벤트·resolved-compose default false/explicit true 회귀. migration 없음(요구대로).
- [x] **T-VN-H03R — route wiring startup gate·public CORS exact preflight 완결** (#798 closed) —
  PR #803: `create_app()`에서 `assert_route_policy_wiring()` fail-closed, `PUBLIC_CORS_REQUEST_HEADERS`
  닫힌 allowlist(CORS safelist + If-None-Match + X-Kor-Travel-Map-Api-Key), route별 exact-method
  CORS, 비허용 preflight 400 + ACAO 미방출, `KNOWN_WIRING_EXCEPTIONS == ()` 회귀.
- [x] **T-VN-H08 — Tier-2 p95 nearest-rank 산식 정확화** (#799 closed) — PR #801:
  `_nearest_rank_percentile` = `sorted(values)[ceil(p×n)-1]` 공용 helper(실행시간·shared read
  blocks 공용), n=1/20/30/100 fixture로 index·값 고정. release evidence 재생성은 이전 evidence가
  존재하지 않아 vacuous — 실제 1M+ 실분포 측정은 cutover(T-VN-39) 시 release 리포트로 수행.
- [x] **T-VN-H09 — weather semantic upsert collected_at 단조성** (#797 closed) — PR #802:
  `weather_repo.py` upsert `WHERE EXCLUDED.collected_at >= … AND ROW(…) IS DISTINCT FROM ROW(…)`
  (ADR-072 0060 승자 규칙 정합), current-row 선택 근거 ADR-072에 기록, NULL(비허용)/동률(내용
  다르면 later-write wins)/no-op(동일 replay 물리 UPDATE 없음) 정책 문서화, T1→T2/T2→T1/동률/
  backfill 통합 회귀.
- [x] **T-VN-51~56 — Wave 3 도입-조건 측정** — PR #816: 여섯 확장 후보(MVT/범용 batch/cursor
  rotation/weather partition·hypertable/물리 listener/대규모 fixture 주기) 전부 측정·판정 완료.
  T-VN-51~55는 명시 트리거로 유예, T-VN-56은 현행 2계층(per-PR tier-1 + release tier-2) 확정.
  정본 `performance.md` §8.4 + `reports/t-vn-51-56-adoption-measurement-2026-07-21.md`.

## C7 prod-live 게이트 확정 · schedule-write descope (2026-07-26, `T-ADM-C7`·`T-ADM-C7RUN`)

- [x] **T-ADM-C7 — live e2e 재작성 + n150 prod-live 검증 완결.** C7 prod-live 게이트를
  **read-auth·kma-active-write·kma-empty-write·kma-cap-write 4-spec**로 확정(green)하고 n150
  production에 대해 파괴적 live로 실행했다(현 prod: cron=20, RUNNING; 실행 부수효과 2건 복구 완료).
  WS 인증 close saga(C7W/X/Y/Z, read-auth 7/7), kma-write 계약(C7PV/C7PW), detail perf·running-race
  (#829)까지 실 코드 blocker를 모두 해결·머지했다. `ops-c7-schedule-write`는 app-side render churn
  때문에 blocking gate에서 **descope**했다(후속 열린 task `T-ADM-C7-SCHEDCHURN`). Map PR #837 +
  docker-manager PR #74 squash-merge. 상세: `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7RUN — 공식 러너 GREEN 확정 (2026-07-26 CLOSED).** "외부 data.go.kr KMA 502가 유일
  blocker" 진단은 폐기(오류)됐고, verbose-iterate(non-redacting reporter + browserFetch DIAG 계측)로
  masked blocker를 순차 규명·수정했다: preview provider_dataset 노출(#824), create-body `update_policy`
  과명세(#825), detail `/v1/ops/datasets/detail` O(roots²) timeout recency-bound(#828/#829),
  running-race fast-completion tolerate(#829), root_id lineage(#834), gate restructure(#835),
  empty-write queue-sensor UI-gate flake 하드닝(#837). 후반 flaky UI/timing까지 통과 확정. Map PR #837
  + docker-manager PR #74 머지.

## C7 kma-write live 계약 수정 (2026-07-22~23, `T-ADM-C7PV`·`T-ADM-C7PW`)

- [x] **T-ADM-C7PV — kma-active-write preview provider_dataset WYSIWYG(sync_scope)** (PR #824) —
  preview가 0-feature dataset(`kma_ultra_short_nowcast`)에서 `matched_scope.provider_datasets`를
  생략해 C7 `assertExactKmaPreviewBody`가 throw + 다음 UI `toContainText(sync_scope)`도 실패했다.
  `scope_repo` provider_dataset 브랜치가 요청 pair를 0-feature 포함 항상, 요청 `sync_scope`와 함께
  노출하도록 executor `_provider_dataset_scopes`와 parity를 맞췄다. verbose-iterate live harness로 검증.
- [x] **T-ADM-C7PW — kma-active-write create-body update_policy 테스트 과-명세** (PR #825) —
  UI는 create body에 `update_policy`를 안 보내는데(계약상 optional, absent≡{}) 테스트가 `{}` 기대 →
  `_ops-c7-admin-api.ts` `buildKmaRequest`의 `update_policy: {},` 삭제. clean v6 harness가
  kma-active-write 전 flow(create→run-now→terminal→grids→fingerprint→overflow×49) 통과 검증(2 passed).

## C7 ops-live WS 인증 close saga (2026-07-20~22, `T-ADM-C7W`·`T-ADM-C7X`·`T-ADM-C7Y`·`T-ADM-C7Z`·`T-VN-H11`)

- [x] **T-ADM-C7W — Chromium ops-live 인증 거절 close code 4401 복구** (#806 closed · PR #807) —
  변조된 subprotocol을 제시한 실제 Chromium이 handshake 실패 `1006` 대신 application close `4401`을
  관측하도록 transport-level subprotocol selector를 두고, 인증·nonce·application loop 미진입 상태로
  data frame 없이 `4401` close. selector 없음/단일/복수/길이초과 회귀 고정.
- [x] **T-ADM-C7X — ops-live subscribe-after-hello로 만료 ticket 4408 clean 전달** (#817 closed · PR #818).
- [x] **T-ADM-C7Y — ops-live reject-close accept↔close settle env-tunable 0.25s** (PR #821).
- [x] **T-ADM-C7Z — C7 live e2e 복구-leg passthrough를 route.continue로 (Sec-Fetch 보존)** (PR #823).
- [x] **T-VN-H11 — ops-live 인증 close의 proxy 전달 경계 분리** (#809 closed · PR #807/#810) —
  Uvicorn accept 101과 close frame coalescing에 대해 accept 성공 뒤 bounded settle window(배포 조합
  한정 best-effort)와 accept~close 단일 bounded child task 보호를 두었다. 위 4개 WS auth saga와 함께
  공식 러너 `ops-c7-read-auth` 7/7 통과로 검증. 별건 HAProxy WS 백엔드 `timeout tunnel` 미설정
  운영버그는 issue #819로 분리 등록.

## C7 manifest v4 provenance · PostGIS topology check 오탐 (2026-07-19, `T-ADM-C7P`·`T-ADM-C7F`)

- [x] **T-ADM-C7P — C6c manifest v4·Map 4-image C7 provenance 동기화** (issue #777 · PR #778,
  `d2104f15`) — compatible-pair manifest를 v4로 clean-cut하고 active/rollback pair에 Map API·UI·
  Dagster web·daemon 네 immutable image ID와 하나의 Map source revision을 결박했다. C7 attestation이
  네 Map image ID를 실제 compose runtime role과 각각 exact 비교하고, manager manifest v3는 거부한다.
  2026-07-26 C7 prod-live 게이트 green(runtime attestation 통과)으로 활성 검증됨.
- [x] **T-ADM-C7F — prod PostGIS topology 객체의 Alembic check 오탐 제거** (PR #791, `6fa914c2`) —
  shared Postgres infra owner의 `postgis_topology`(`topology.layer`·`topology.topology`)를
  `include_schemas=True` autogenerate가 삭제 대상으로 오인하던 `alembic check` 오탐을, extension-owned
  객체만 명시 제외하고 head migration 뒤 topology extension을 설치한 production-equivalent integration
  gate로 함께 고정했다.

## vNext 독립 하드닝 — public API key header 전환 (2026-07-20, `T-VN-H01`, integration/t-vn)

- [x] **T-VN-H01 public API key를 URL query에서 header로 이동** (#794) — 공개 REST API key를
  `?key=` 쿼리에서 clean-cut하고 `X-Kor-Travel-Map-Api-Key` 헤더로만 받는다(access log·Referer
  유출 차단, breaking change). OpenAPI `PublicApiKey` security scheme을 apiKey-in-header로 바꾸고
  `openapi.json`/`openapi.user.json`과 admin·user-client `types.ts`를 재생성했다. route policy
  분류(PUBLIC_KEYED)는 불변. PinVi·admin consumer는 헤더 전송으로 전환해야 한다(cross-repo
  coordination — T-VN-20 PinVi 패턴).

## destructive admin 기본값 fail-closed (2026-07-20, `T-VN-H02`)

- [x] **T-VN-H02 — destructive admin 기본값 fail-closed.** `admin_destructive_enabled`
  기본값을 `True`→`False`(fail-closed)로 내리고, 문서화된 env alias
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`가 실제로 바인딩되도록 `validation_alias`를 추가했다.
  Docker compose는 컨테이너 기본 true를 주입해 기존 배포를 유지한다(배포 전제: 파괴적 작업이
  필요한 배포는 host env로 이 값을 유지). PR #793.
  이후 standalone compose까지 default false로 닫는 `T-VN-H02R`(#796)이 이 배포 예외를
  clean-cut으로 대체한다.

## surface별 CORS 분리 (2026-07-20, `T-VN-H03`)

- [x] **T-VN-H03 — surface별 CORS를 표면 정책으로 분리.** route policy matrix(T-VN-02)의
  분류를 재사용해 browser-facing public 표면(public-unauthenticated·public-keyed)에만 CORS를
  적용하고, service(server-to-server token)·operator(admin BFF same-origin proxy)·metrics·debug
  표면은 `Access-Control-Allow-Origin`을 내보내지 않는다. app-global `CORSMiddleware`를 route
  policy로 게이트하는 표면 범위 미들웨어(`kortravelmap.api.cors.SurfaceScopedCORSMiddleware`)로
  구현했고, 경로 판정은 비-public 매칭 시 무조건 제외하는 security-safe 규칙을 쓴다. CORS는
  미들웨어라 OpenAPI spec 무관(drift 없음). PR #795.

## coord_5179 PROJ pin · INVALID index 복구 runbook (2026-07-20, `T-VN-H04`·`T-VN-H05`)

- [x] **T-VN-H04 — `coord_5179` PROJ 버전 고정·drift 검사·REINDEX runbook.** `docs/runbooks/coord-5179-proj-pin.md` 추가 — PROJ-bound STORED generated 컬럼의 drift 탐지 SQL(저장 `coord_5179` vs 현재 PROJ `ST_Transform(coord,5179)` 비교), `SET coord=coord` keyset batch 재계산, `REINDEX INDEX CONCURRENTLY idx_features_coord_5179_gist`. image tag `postgis/postgis:16-3.5-alpine`가 PROJ를 pin. performance.md §7.1·postgres-schema.md §4.1·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.
- [x] **T-VN-H05 — CONCURRENTLY 실패 INVALID index 탐지·drop runbook.** `docs/runbooks/invalid-index-recovery.md` 추가 — `pg_index.indisvalid=false` 탐지 SQL(pg_class/pg_namespace join으로 index·table 이름), `DROP INDEX CONCURRENTLY IF EXISTS` + 원 DDL 재실행, 0061 self-heal·0060 non-concurrent 원자성 맥락. performance.md §8.3(§6.6 dangling ref 대체)·postgres-schema.md §8.2·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.

## vNext main 동기화 (2026-07-20, `T-VN-SYNC-01`)

- [x] **T-VN-SYNC-01 — latest main을 integration/t-vn에 동기화.**
  `main@d2104f15`를 `integration/t-vn@22bf35a5` 위 전용 branch에서 merge하고, 양쪽 문서 이력,
  API image OCI revision label과 production profile, 완료/미완 task 정본을 함께 보존했다.
- [x] **migration과 CI 계약 확인.** Alembic `0058 → 0059 → 0060 → 0061 → 0062` 단일 chain을
  유지했고 lint, OpenAPI drift, Python 3.11/3.12/3.13, fixture replay, PostGIS integration,
  frontend type-check/build의 CI 8개를 모두 통과했다.
- [x] **PR #781 병합 완료.** PR head `aa976f13ae747d75fe67318d9c41fb2bddfddb04`를 merge commit
  `a45bc3ac401e5675811f1031a4592991498d899f`로 `integration/t-vn`에 반영했다. 이후 최종
  integration→main 합류는 열린 `T-VN-SYNC-02`가 담당한다.

## C7 prod runner attestation·복구 경계 (2026-07-19, `T-ADM-C7H`)

- [x] **T-ADM-C7H — 파괴적 live 실행 전 runtime을 exact attestation에 결박.** C6c compatible-pair,
  clean source commit과 OCI revision, Map API/UI/Dagster web·daemon/PinVi API의 실제
  image·command·environment, compose project, 단일 Alembic head/check, UI login을 read-only로
  대조한 뒤에만 `BLOCKED.json`과 mutation journal을 만든다.
- [x] **root 실행 파일과 복구 증거를 fail-closed로 고정.** runner/helper/attestation 모듈/상태
  감사기 네 파일을 exact Git archive와 root-owned SHA-256에 묶었다. 실패·signal 경로는
  runtime/journal/sentinel을 보존하고 INT/TERM은 130/143으로 종료한다. Playwright container는
  bridge/private IPC, durable creator/outcome/CID와 별도 검증형 stop 도구만 사용한다.
- [x] **단일 적대 리뷰와 실행형 gate 완료.** 최종 P0~P3 잔여 없음 판정 뒤 C7 대상 55건,
  전체 unit 1,529건, Ruff, strict mypy, import 계약, exact-commit immutable executor build를
  통과했다. PR #754와 보안 후속 PR #762는 각각 CI 8개가 모두 성공한 뒤 merge commit
  `b9f23a42`, `bece2c32`로 `main`에 반영됐다. 실제 배포·파괴적 browser 증거는 열린
  `T-ADM-C7` n150 gate가 담당한다.

## C7 mocked UI projection·pagination 수용 증거 (2026-07-19, `T-ADM-C7M`)

- [x] **T-ADM-C7M — datasets summary를 이름 있는 영역의 exact projection으로 검증.**
  `/ops/datasets` mocked E2E는 행·실패·SLA 초과·미실행·이슈 요약을 summary landmark 안에서
  검증한다. 같은 문자열로 표 행을 오염해도 summary 영역에 잘못 투영되지 않는 negative fixture를
  포함해 페이지 전역 문자열 검색으로 생기는 거짓 양성을 차단했다.
- [x] **pipeline continuation의 요청·응답·DOM 경계를 함께 고정.** 실행과 전역 event를 각각
  6+6 두 페이지로 주입하고 exact provider/dataset/scope/page size와 null/expected cursor 요청,
  페이지별 전체 DOM identity 배열, 전체 정렬, 페이지 간 서로소와 마지막 continuation 종료를
  검증한다.
- [x] **mock 증거와 live 수용 범위를 분리.** 6+6 fixture는 `page_size=50`의 실제 overflow가 아니라
  cursor plumbing 증거다. canonical page size를 넘는 51건 이상의 실제 continuation은 열린
  `T-ADM-C7` n150 live E2E가 담당한다.
- [x] **PR #755 병합 완료.** 단일 적대적 리뷰의 query-scope 지적을 exact validator와 cursor 관측
  검증으로 반영한 뒤 targeted mocked E2E 3건을 통과했다. 문구·fixture 설명 후속까지 포함한
  PR #755는 CI 8개 게이트가 모두 통과한 뒤 merge commit `54150c91`로 `main`에 반영됐다.

## vNext 재설계 Wave 0~1 (2026-07-19, `T-VN-*`, integration/t-vn)

> C7 종결 전까지 `integration/t-vn` 통합 브랜치에 누적. 각 task는 적대 리뷰(실전 결함 반영)
> + GitHub CI + n150 CI-parity 게이트를 거쳐 병합. 세부는 각 PR diff와 journal.

- [x] **T-VN-01 production fail-closed** (#740) — production profile secret 누락 시 기동 거부.
- [x] **T-VN-02 route policy matrix + 미분류 CI gate + /metrics 경계** (#747, +#742 수렴).
- [x] **T-VN-04 공개 predicate 단일화** (#743) — `feature.public_features` view, F-1 양방향 봉인.
- [x] **T-VN-05 raw payload 경계 제거** (#752) — 공개 DTO raw/lineage를 operator 표면으로.
- [x] **T-VN-06 notice 방어적 cast** (#746) — 오염 timestamp의 공개 read 500 차단.
- [x] **T-VN-07 no-op 옵션 삭제 + actor principal 1차** (#748).
- [x] **T-VN-13 Feature row_revision + If-Match/ETag** (#772, 리뷰 후속 #776) — 낙관적 동시성(428/412/304).
- [x] **T-VN-14 지도 completeness + exact ST_Intersects** (#763) — mode/truncated/coverage.
- [x] **T-VN-17 weather 무결성 제약** (#756) — semantic UNIQUE와 writer cutover 기반 도입.
- [x] **T-VN-18 중복 GiST 제거 + BRIN 감사** (#759) — write 1.2~1.3x 개선 실측.
- [x] **T-VN-19 Alembic metadata 정합 CI** (#753) — 빈 DB upgrade→check 게이트.
- [x] **T-VN-20 principal actor 전면 전환** (#757) — body actor 위조 경로 제거.
- [x] **T-VN-21 3단 성능 gate** (#760) — planner-default EXPLAIN·N+1·shape 회귀.
- codex 후속 병합: #745(curation), #749(metrics), #750(beach doc), #751(manual-link, main).

## vNext 적대 리뷰 후속 (2026-07-19, `T-VN-*R`, integration/t-vn)

- [x] **T-VN-05R public curated raw lineage 우회 차단** (#774, issue #765) — 공개 전용
  allowlist DTO/projection과 strict kind별 detail로 admin raw 계약과 공개 계약을 분리했다.
- [x] **T-VN-14R cluster/items exact 후보집합 단일화** (#773, issue #768) — PR #763 후속으로
  교차 geometry의 cluster count/items universe와 canonical 행정코드 귀속을 일치시켰다.
- [x] **T-VN-17R weather UNIQUE writer race 봉인** (#771, issue #766) — migration 0060을
  transactional non-concurrent UNIQUE cutover로 정정해 dedup과 writer fence를 원자화했다.
- [x] **T-VN-21R release benchmark 측정 정확성** (#775, issue #767) — 실제 public batch
  cardinality, matched/returned 구분과 top-level shared read 단일 합산을 고정했다.

## POI target causal receipt·조건부 삭제 (2026-07-18, `T-ADM-C7C`)

- [x] **T-ADM-C7C — mutation과 live invalidation을 transaction-coupled receipt로 결박.** POI target
  PUT/DELETE는 원본 transaction에서 증가한 `dataset_projection_revision`을 반환한다. C7 live
  E2E는 같은 기존 socket의 새 update frame에서 `live_revision >= receipt`만 causal 증거로 인정하며
  snapshot·top-level fingerprint revision은 제외한다.
- [x] **server-owned version과 exact `If-Match`로 재생성 경쟁을 차단.** Alembic 0058의 양수
  BIGINT `lock_version` trigger와 target UUID로 strong `ETag`/body `entity_tag`를 만든다. DELETE는
  누락 `428`, weak·wildcard·결합/중복/malformed `422`, stale UUID/version `412`, 실제 부재 `404`를
  구분하고 active natural-key row lock 뒤 UUID+version이 모두 같은 행만 soft-delete한다.
- [x] **parent→link lock order와 UI retry를 완결.** executor는 모든 active parent를 UUID 순서로
  `FOR KEY SHARE` 잠근 뒤 link를 교체한다. UI/BFF는 `If-Match`/`ETag`를 보존하고 stale `412`에서
  list·nearby·datasets·pipeline을 refetch해 같은 target UUID의 최신 tag로만 재시도한다.
- [x] **적대 리뷰·로컬 gate 완료.** 두 독립 리뷰어가 최종 기능 diff를 승인했다. root unit
  1,435건, API 520건, 실제 PostgreSQL migration/up-down·2-session 경쟁 8건, frontend unit
  212건, mocked POI E2E 10건을 통과했다. Ruff, strict mypy 115+52파일, import 계약 4/4,
  admin/user OpenAPI·생성 타입 drift, type-check·lint(오류 0)와 31-route production build도 green이다.
  실제 same-socket causal 증거와 destructive cleanup은 최종 `T-ADM-C7` n150 live E2E에서 수행한다.

## Admin exact-scope 조작·이력 UI 소비 (2026-07-18, `T-ADM-C7B-UI`)

- [x] **T-ADM-C7B-UI — exact provider/dataset/scope를 조작과 이력의 단일 정본으로 소비.**
  `/ops/datasets`는 잘못되거나 사라진 dataset/scope deep link를 다른 행으로 폴백하지 않고
  fail-closed한다. provider-only URL은 실제 선택 tuple로 canonicalize한 뒤에만 갱신·정책
  mutation을 허용한다.
- [x] **활성 실행·최근 종료·이력 continuation을 독립 표시.** `active_execution`과 최근 terminal
  `latest_execution`을 분리하고, exact scope의 `run_history`·`event_history`와 서버가 반환한
  `canonical_url`을 그대로 사용한다. scope 전환 중 정책 draft를 보존하며 orphan 또는
  `mutable=false` 행은 draft를 표시하되 저장을 차단한다.
- [x] **pipeline filter를 URL controlled state로 완결.** provider/dataset tuple이 불완전해지거나
  상위 축이 바뀌면 stale dataset/scope와 cursor를 같은 전이에서 제거한다. browser
  Back/Forward도 exact filter state에 반영하며 dataset-wide capability에는 명시적
  `sync_scope` 입력을 막고 서버 정규화에 맡긴다.
- [x] **적대 리뷰와 frontend gate 완료.** 독립 리뷰어 2인이 P0/P1/P2/P3 잔여 0건으로 승인했다.
  Vitest 26 files·210 tests, 앱·E2E type-check, lint 오류 0건과 31-route production build를
  통과했다. Playwright와 issue #712/#719 종결은 최종 `T-ADM-C7` n150 live E2E에 남긴다.

## Admin active projection·exact-scope 이력 API (2026-07-18, `T-ADM-C7B-API`)

- [x] **T-ADM-C7B-API — 활성 실행과 마지막 종료 실행을 독립 projection으로 완결.**
  datasets grid/detail은 같은 DB statement snapshot에서 exact
  `(provider,dataset_key,sync_scope)`별 queued/running `active_execution`과 최근 terminal
  `latest_execution`을 각각 선택한다. 논리 `dataset_wide`는 typed scope와 과거 NULL scope를
  같은 total order로 비교하고, `target_grids`·`external_system:*`에는 unscoped 실행을 추측하지
  않는다.
- [x] **Alembic 0057로 event identity와 exact-scope access path를 고정.** visible event의
  provider/dataset을 immutable owning job에서 복구하고 canonical direct update event에만 typed
  `sync_scope`를 backfill한다. INSERT trigger와 check constraint가 owner pair/scope를
  복사·불변화하며, `(provider,dataset_key,sync_scope,occurred_at DESC,event_id DESC)` partial
  index가 scope 조건을 cursor·`ORDER BY`·`LIMIT` 전에 적용한다. provider namespace 밖에서 의미가
  없는 dataset-only event filter는 REST/repository에서 `422`/`ValueError`로 거부하고, 읽기 경로가
  사라진 `idx_import_job_events_dataset_time`은 제거했다.
- [x] **실행·event continuation 계약을 typed cursor로 완결.** dataset detail은 `run_history`와
  `event_history`를 각각 `{items,next_cursor,canonical_url}`로 반환하고 pipeline 목록·event stream도
  같은 canonical URL을 사용한다. run/event cursor는 전체 filter fingerprint에 묶어 다른
  job/level/provider/dataset/scope에서 재사용하면 DB 조회 전에 typed `422`로 닫고, strict parser가
  거부하는 scope와 불완전한 provider/dataset tuple도 fail-closed한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API 적대 리뷰어 2인이 테스트 전에 최종 변경을 검토해
  P0/P1/P2/P3 잔여 0건으로 승인했다. migration 0057·수정 EXPLAIN·pipeline/jobs/dataset
  projection·feature executor·ORM metadata/repository의 실제 PostgreSQL 순차 gate 81건,
  root unit/lint 1,430건, API 504건과 frontend unit 210건을 모두 통과했다. Ruff, strict
  mypy 167개 소스, frontend type-check·lint, admin/user OpenAPI·생성 타입 drift도 green이다.
  issue #712/#719는 최종 `T-ADM-C7` n150 live 증거 뒤 종결한다.

## Admin 갱신 정책 동시성 완결 (2026-07-18, `T-ADM-AUD-718`)

- [x] **T-ADM-AUD-718 — BIGINT revision CAS를 DB부터 UI까지 완결.** Alembic 0056으로
  `ops.provider_refresh_policies.revision`을 양수 BIGINT로 추가했다. 신규 생성은
  `expected_revision=null`, 기존 갱신은 정확한 revision 일치가 필수이며 성공할 때만 원자적으로
  1 증가한다. `source_kind`는 생성 뒤 불변이고 최댓값은 overflow 전에 typed 소진 `409`로 닫는다.
- [x] **충돌 복구와 JavaScript 정밀도 경계를 고정.** HTTP revision은 정규화된 10진 문자열이며
  불일치 응답은 현재 정책과 revision을 포함한다. UI는 작성 기준·최신 관측값·지연 응답 세대를
  분리해 background refetch와 다른 scope cache가 초안을 덮지 못하게 하고, 명시적 3-way 조정 뒤
  최신 revision으로만 다시 저장한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API와 frontend 리뷰어가 최종 제품 SHA
  `b7b600447368d8ed79bc1a8b56772af881104bf3`을 S1/S2/S3 0건으로 승인했다. root unit
  1,411건, API 489건, 실제 PostGIS migration/schema 14건·CAS 저장소/API 23건·집중 10건과
  독립 row-lock 경쟁 3회, Ruff, strict mypy 115+52파일, import 계약 4/4를 통과했다. 같은 SHA의
  frontend Vitest 212건, type-check, lint 오류 0건, OpenAPI/admin type drift와 31-route production
  build도 통과했다. issue #718은 PR #727의 수용조건과 CI를 재확인한 뒤 2026-07-18 닫았다.

## KMA 빈 target fail-closed·exact-scope event (2026-07-18, `T-ADM-AUD-686`)

- [x] **T-ADM-AUD-686 — 유효 target 0건을 provider I/O 전에 종결.** 직접 runner와 정규
  Dagster KMA grid asset 3종은 target mapping·dedupe·cap·cursor preflight를 통과한 뒤에만
  credential·provider import·public client를 사용한다. 유효 target이 없으면 feature/weather와
  provider sync state를 변경하지 않고 canonical operation을 실패시키며, 같은 transaction에
  `kma.target_scope_empty` event를 정확히 한 번 기록한다.
- [x] **원자성·이력 경계를 회귀 계약으로 고정.** active duplicate loser와 terminal replay는
  operation/event를 늘리지 않고, event 기록 실패는 request/job/event 전체를 rollback한다.
  dataset event는 canonical event→job→request JOIN에서 effective `sync_scope`를
  cursor·`ORDER BY`·`LIMIT` 전에 제한하며 다음 cursor와 canonical history URL을 반환한다.
  migration은 추가하지 않았고 이 join-derived 경계는 후속 C7B-API/0057이 승계한다.
- [x] **적대 리뷰와 로컬 gate 완료.** 두 독립 리뷰어가 제품 SHA `c07259fb`를 S1/S2/S3
  0건으로 승인했다. 테스트 격리·generated type 동기화를 반영한 최종 SHA에서 root unit
  1,413건, API 485건, Dagster 475건(1 skip), 실제 PostGIS 집중 6건, frontend Vitest
  185건을 통과했다. Ruff, strict mypy 115+52+23파일, import 계약 4/4,
  OpenAPI admin/user·generated type drift, frontend type-check·lint(오류 0, 기존 경고 6),
  31-route production build도 통과했다. #686은 #701/#726/#728/#729의 전체 수용조건과
  CI를 재확인한 뒤 2026-07-18 닫았다.

