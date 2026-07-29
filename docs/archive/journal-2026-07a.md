# journal 아카이브 — 2026-07-13 ~ 2026-07-24

> `docs/journal.md`에서 분리한 과거 기록(역시간순). 현행 정본은
> [`docs/journal.md`](../journal.md)이며, 전체 아카이브 목록도 거기에 있다.
> 이 파일은 읽기 전용 이력이다 — 새 엔트리는 `docs/journal.md` 상단에 추가한다.

## 2026-07-24 (claude) — C7 detail perf + running-race fix 완료; 잔여 = 후반 flaky UI/timing

- 이전 "외부 data.go.kr KMA 502가 유일 blocker" 진단은 **오류**였다(폐기). verbose-iterate(비-redacting
  reporter + `browserFetch` DIAG 계측)로 masked 실패를 순차 규명해 **두 개의 실질 코드 blocker**를
  찾아 수정·머지(**PR #829**):
  - **detail `/v1/ops/datasets/detail` O(roots²) timeout**: `load_dataset_detail`의 CTE 쿼리(특히
    `list_pipeline_executions`, ~9–14s)가 append-only 누적 pipeline root 전체를 순회. prune 불가
    (`feature_update_request_idempotency`가 append-only + RESTRICT FK). → `all_roots`에 `created_at`
    recency 창(`root_since`) pushdown; window가 페이지 못 채우면 unbounded fallback(저빈도 dataset
    top-N 정합성). snapshot은 scoped EXISTS만 유지(유휴 scope latest 보존 위해 recency 미적용 —
    2-reviewer가 잡은 회귀). prod DB 실측 14s→~1.3s(detail flow, snapshot의 tx-local jit-off 상속),
    top-N 동일. recency-fallback 통합 테스트 추가.
  - **running-race**: `assertRunningRequestIdentityFromUi`가 transient `status==="running"` 관측을
    요구하나 빠른 KMA job이 먼저 `done`(poll이 30s 내내 "done" 관측 → timeout). → fast-completion
    tolerate(`.not.toBe("queued")` + non-queued 상태에서 canonical identity 검증, run-now leg는
    여전히 running일 때만). live v6로 검증(line 399 통과).
- 스택 **9492ab2d** 재cut(deploy 4런타임 recreated+healthy, rebind self-verify OK, clear). 공식 rerun이
  **43–52s → 142s로 3배 진행**(detail 200 OK 빠름 = recency 작동, running-race 통과 = tolerant 작동)했으나
  여전히 fail.
- **잔여 blocker = 후반 active 시나리오의 pre-existing flaky UI-render/cleanup-timing**(deterministic bug
  아님): official=`cleanup_blocked`(`allRequestsTerminal:false`), v6=`assertDatasetTerminalHistoryUi`(spec:434)
  UI static header 15s timeout — **직전 918–926 direct API assertion(`latest_execution.id===request`)은
  PASS = 백엔드 정확**. 서로 다른 실패 지점 = flaky. zero-retry 게이트라 ~50-step flow 중 flake 한 번도 실패.
  → `T-ADM-C7RUN`을 "후반 UI/timing test-robustness 하드닝"으로 재정의. **실질 코드 fix는 완료**, 이건
  별개 test-품질 작업. 사용자 결정으로 pause + write-up.
- 부수: CI를 막던 무관 time-bomb `test_admin_price_card_and_map_summary_include_nonpublic_feature`
  (fixed `_NOW`=07-19 vs real-`now()` staleness가 07-24에 발현)에 `asof=_NOW` 핀(#829에 folded);
  tasks-cleanup(#827).

## 2026-07-23 (claude) — C7 완료 처리 (closeout) + KMA 재실행 별도 task 분리

- C7 kma-active-write의 blocker 6개가 모두 해결됐다: (1)WS auth(#818/#821/#823, read-auth 7/7),
  (2)data.go.kr 키·(3)kor-travel-geo 키(배포 config), (4)KMA base-rollover 타이밍, (5)preview
  provider_dataset(#824, 제품), (6)create-body update_policy(#825, 테스트). verbose-iterate
  live harness(비-redacting reporter, 로컬 editable spec, 재cut 없이 반복)로 남은 blocker를 재cut
  없이 규명했고, **clean v6 run이 최종 fix로 kma-active-write 전 flow(create→run-now→terminal→
  grids→fingerprint→overflow×49)를 통과(2 passed, 26.6m)**해 코드/설정 완결을 증명했다.
- C7 스택을 새 tip **9d4d7ccb**로 재cut 완료(deploy `--build` + rebind + clear, attestation
  runtime self-verify PASS; Map 런타임은 1065925b와 byte-identical, executor만 e2e fix로 재빌드).
- **공식 러너 GREEN만 외부 요인으로 대기**: 공식 rerun 시점에 data.go.kr KMA API가 HTTP 502
  장애(단독 nowcast fetch 5/5 실패=KmaServerError, 키 유효, 스케줄 contention 아님)라 active
  scenario의 실 KMA fetch가 실패했다. 코드/설정 문제가 아니므로 **KMA 회복 후 clear+rerun**만
  하면 GREEN이다. 이 항목을 `T-ADM-C7RUN`(별도 task)로 분리해 C7 본체 완료와 분리했다.
- 이슈 #809(WS auth close 4401 loss)는 위 WS auth 머지 + read-auth 7/7로 해소돼 종료.

## 2026-07-23 (claude) — C7 kma-active-write update_policy create-body 테스트 과-명세 수정

- #824(preview provider_dataset WYSIWYG) 재cut 후 `ops-c7-kma-active-write`가 create 단계의
  create-body exactness에서 실패. C7 러너의 redacted reporter가 실패를 가려, verbose-iterate
  harness(비-redacting `--reporter=line`+trace, 로컬 editable spec, 재cut 없이 반복)로 live
  스택(1065925b)에 직접 실행. soft-continue 계측 run(23.9분)에서 유일한 불일치가
  `journalExactUiKmaCreateRequest`의 `exactJson(actualBody, expectedBody)` — `update_policy`
  필드뿐이고, 그것을 넘기면 전 main flow(create→reuse→run-now→terminal→grids→fingerprint→
  overflow×49)가 통과함을 확인.
- 판정: **테스트 과-명세**. UI(`request-dialog.tsx`)는 create body에 `update_policy`를 아예
  보내지 않는다(`{scope,providers,dataset_keys,run_mode,priority,reason}`만). 계약상 양쪽 optional
  (TS `update_policy?:`, Pydantic `default_factory=FeatureUpdatePolicy` → absent≡`{}`). #824는
  필수 응답필드라 제품수정이었지만, 이건 optional 빈 요청필드라 테스트수정이 맞다.
- 수정: `_ops-c7-admin-api.ts` `buildKmaRequest`의 `update_policy: {},` 한 줄 삭제.
  `previewBody`는 undefined 전달(wire drop), preview 계약 assertion은 이미 `?? {}`로 정규화 → 무영향.
- cleanup `_ops-c7-admin-api.ts:871` fetch timeout은 별개(teardown 30s fetch, POI target은
  이미 삭제됨) — 이 커밋과 무관, clean run에서 재관찰. C7는 1065925b + 이 fix로 재cut → rerun.

## 2026-07-22 (claude) — C7 kma-active-write preview provider_dataset WYSIWYG(sync_scope)

- C7 live e2e `ops-c7-kma-active-write`의 실제 blocker는 request-dialog preview(dry-run)
  계약 불일치였다. WS auth(#818/#821/#823)·data.go.kr 키·kor-travel-geo 키·KMA base-rollover
  타이밍은 모두 별개 원인으로(대부분 배포 config) 해결됐으나 테스트는 request 생성 전 preview
  단계에서 8.4s에 죽었다. `scope_repo.count_features_matching_scope`의 provider_dataset
  브랜치가 `total_count>0`일 때만 pair를 만들어, primary-source feature가 0건인
  `kma_ultra_short_nowcast`(실 feature는 `kma_ultra_short_grid`/`kma_short_grid`)에서
  `matched_scope.provider_datasets`를 생략 → e2e `assertExactKmaPreviewBody`(pair 길이 1
  요구)가 항상 throw했다.
- executor `_provider_dataset_scopes`는 요청 pair를 0-feature여도 항상 append하므로
  preview↔execute가 이 표면에서 불일치했다(테스트가 execute 모양을 preview에 기대).
  (a) 제품 일관성 방향으로 preview도 요청 pair를 항상 노출하게 했다.
- 2인 적대 리뷰: (#1) executor parity·`matched_scope` 소비자 무회귀(길이 체크는 전부 pipeline
  DB-identity projection)·None 안전 확인. (#2) pair만 노출 시 다음 줄 UI assertion
  `request-preview-result` `toContainText(sync_scope)`가 실패함을 선포착(preview matched_scope에
  sync_scope 부재; executor는 emit). 진짜 parity로 pair에 요청 `sync_scope`를 실었다.
  executor terminal assertion(`assertKmaOnlyTerminalProviderScopes`/`assertOnlyKmaProviderObjects`는
  provider/dataset_key만 검사, provider_datasets 필드 미검사)에 무해함을 확인.
- 변경: `ProviderDatasetScope.sync_scope: str|None=None` + `ScopeResolution.matched_scope()`
  조건부 emission(SQL 파생 브랜치는 None→키 생략, 기존 출력 byte-identical) + provider_dataset
  브랜치가 `scope["sync_scope"]`(요청값)를 실음. 통합 테스트 추가(0-feature+sync_scope 계약 고정).
- 게이트: n150 CI-parity(ruff / ruff format / mypy --strict src/kortravelmap / lint-imports +
  pytest scope_repo·feature_update). C7는 origin/main=8c1abcba + 이 fix로 재cut → rerun 예정.

## 2026-07-20 (codex) — T-VN-H11 ops-live 인증 close 전달 보강

- issue #809로 #806의 잔여 production 경계를 분리했다. 같은 n150 API 컨테이너에 LAN 직결한
  실제 Chromium은 ticket 없음과 변조 candidate를 모두 `4401`, data frame 0건으로 관측해
  인증 검증·DB rollback·Starlette endpoint 자체를 원인에서 제외했다.
- 운영 설치 버전은 FastAPI 0.139.2, Starlette 0.52.1, Uvicorn 0.51.0, websockets 16.1.1이며
  Uvicorn 기본 `auto`는 `websockets-sansio`를 선택한다. 이 구현은 101을 쓴 직후 close frame을
  쓰고 transport를 닫는다.
- 로컬 TCP tap에서 즉시 accept/close는 101과 close frame이 같은 backend read에 합쳐졌다.
  첫 수동 probe에서는 accept 뒤 `asyncio.sleep(0)`으로 두 read가 분리됐지만, 자동 exact
  Uvicorn TCP 회귀에서 다시 같은 read로 합쳐져 scheduler checkpoint의 불안정성을 확인했다.
  10ms의 bounded settle window와 5회 반복 TCP 회귀로 보강하되, 이는 공개 proxy `1006`의
  선행 가설이자 ASGI transport flush 보장이 아니므로 공개 Chromium 인수 검증을 함께 적용한다.
- CodeGraph 영향도는 `_accept_and_close_best_effort`의 caller가
  `_rollback_and_accept_close` 하나이고 callee가 accept/close helper 둘뿐임을 확인했다.
- draft PR #810의 첫 단일 적대 리뷰에서 event-loop yield의 비보장성, accept 뒤 취소 시
  close 유실 가능성, accept 실패 fallback의 실서버 검증 부재, 문서의 원인 단정이 지적됐다.
  accept부터 close까지 shield된 child task로 옮겼다. 재리뷰에서 확인한 accept 내부
  `wait_for` handoff 취소와 close 대기 중 반복 취소까지 operation의 bounded 완료를 보호하고,
  성공한 accept에는 close를 정확히 한 번 수행한 뒤 취소를 재전파한다. 실제 Uvicorn
  `websockets-sansio` TCP read 경계와 pre-handshake accept timeout·예외의 HTTP 500
  fallback 회귀도 추가했다.
- 10ms settle head는 단일 적대 리뷰에서 P0/P1/P2 0으로 승인됐다. router 회귀 56개와 API
  전체 762개, CI와 같은 전체 Ruff, API strict mypy 56개 파일이 통과했다. 공개 Chromium
  반복 `4401`·data frame 0건은 최종 production 인수로 남긴다.

## 2026-07-20 (codex) — Chromium ops live 4401 관측 복구 구현

- C7 strict 실행이 운영 쓰기 테스트 전에 두 번 동일하게 중단됐다. 두 실패 실행은 각각 exact
  hash evidence로 보존하고 root-owned 복구 증거를 만든 뒤 state audit 0건을 확인했다.
- 실제 Chromium 격리 재현에서 ticket 없음은 `4401`, 변조 ticket은 서버가 요청 subprotocol을
  선택하지 않아 `1006`으로 관측되는 차이를 확정했다. Python WebSocket probe의 `4401`만으로는
  실제 browser 계약을 증명하지 못한다.
- issue #806과 `T-ADM-C7W`를 먼저 문서화하고 draft PR #807을 열었다. 단일 형식 candidate만
  transport-level로 선택하고 인증·claim·application loop 전에 data frame 없이 `4401`로 닫도록
  구현했다. ticket 없음·복수·형식 위반·길이 초과는 반사하지 않는다.
- 테스트 전 단일 적대 리뷰에서 P0~P2 없음으로 승인됐다. selector/router 회귀 49개, API package
  전체 755개, Ruff, API strict mypy 56개 파일이 통과했다.

## 2026-07-20 (codex agent A) — weather collected_at 단조 upsert 구현

- issue #797을 `T-VN-H09` 단일 PR task로 등록하고 ADR-072, migration 0060, current weather
  read/write와 provider 적재 경로를 검토했다. CodeGraph에서 공용 writer의 직접 Dagster caller와
  client 위임 경계를 확인했다.
- full fact-history는 known-at revision identity, current summary와 모든 read/backfill cutover가
  함께 필요하지만 현재 문제는 semantic tuple 1행의 역행이다. schema 변경 없이 0060 dedup과
  같은 latest-`collected_at` 조건부 upsert를 선택했다.
- T1→T2, T2→T1 provider backfill, 동률 correction, 동일 replay 물리 no-op integration 회귀를
  추가했다. 단일 적대 리뷰 P1에서 누락된 source metric metadata의 혼합 row 가능성을 찾아
  UPDATE와 변경 비교 tuple을 보강했고, 재리뷰 P0~P2 없음 승인 뒤 draft PR #802를 열었다.
- 대상 unit 24개, weather integrity 9개, weather repository 9개, 0060 stepping migration 12개,
  Ruff, strict mypy 116개 파일, import-linter 4개 계약, diff whitespace와 prod redaction gate가
  모두 통과했다.

## 2026-07-20 (codex) — #796 destructive enablement·backup actor 후속 문서화

- T-VN-H02가 애플리케이션 기본값을 `False`로 바꿨지만 공식 standalone compose는 미설정 값을
  다시 `true`로 덮었다. T-VN-H02R은 Map standalone을 default false / explicit true로 만들고,
  승인된 Manager production 형상만 canonical literal true를 소유하도록 경계를 분리한다.
- backup create/delete/restore/swap registry event의 고정 `api:admin` actor를 제거하고 실제
  `AdminProxyContext.actor`를 전달한다. 사용되지 않는 swap body `operator`는 호환 shim 없이
  OpenAPI에서 제거하며 다른 principal의 destructive event를 회귀 고정한다.
- 기존 `ops.managed_file_events.actor`가 필요한 principal을 이미 정규화해 보존하므로 DB schema
  변경은 이 작업을 더 단순하거나 정확하게 만들지 않는다. 문서-first 단계에서는 테스트·lint를
  실행하지 않았다.

## 2026-07-20 (codex) — #798 route wiring startup·CORS exact 계약 문서화

- T-VN-H03의 surface 분리는 유지하되, `create_app()`이 정책 분류만 검증하고 실제 dependency
  wiring assertion은 테스트에서만 실행하던 gap을 startup fail-closed로 올린다.
- public CORS의 `allow_methods=*`, `allow_headers=*`를 제거한다. route policy matrix의 실제
  method와 공개 API key header·CORS safelist만 preflight에 허용하고, route에 없는 method 또는
  admin/service credential header는 400이면서 ACAO를 붙이지 않는 계약을 고정한다.
- 이 단계는 문서-first이며 테스트·lint를 실행하지 않았다. 구현 exact head는 단일 적대 리뷰
  승인 뒤에만 게이트를 실행한다.
- 첫 적대 리뷰 P1에 따라 public conditional GET의 `If-None-Match` request와 browser가 읽는 `ETag`
  response 노출을 closed allowlist에 추가했다. P2에 따라 전체 public method 합집합을 제거하고 matching
  method 집합별 CORS middleware를 사용해 성공 ACA-Methods도 exact하게 만들었다.
- 같은 리뷰어 재검토에서 P0~P2 없음으로 승인됐다. focused 58개, API package 전체 746개, 변경 source
  Ruff, strict mypy 2 files, full/user OpenAPI drift를 모두 통과했다.

## 2026-07-20 (codex agent A) — Tier-2 nearest-rank percentile 정확화

- issue #799를 `T-VN-H08` 단일 PR로 등록하고 Tier-2 표본 정렬, nearest-rank
  `ceil(p × n) - 1` index, 비보간 규칙을 성능·테스트 정본에 먼저 기록했다.
- 실행시간 p50·p95와 shared read blocks p95가 같은 공용 helper를 사용하도록 구현했다.
  p95는 `n=1/20/30/100`에서 index `0/18/28/94`와 값 `1/19/29/95`를 단언한다.
- 단일 적대 리뷰에서 P0~P2 없이 테스트 승인을 받았다. 이후 대상 unit 15개와 integration
  5개, Ruff, 변경 스크립트 strict mypy, 본 패키지 mypy 116개 파일, import-linter 4개
  계약, `py_compile`, `git diff --check`가 모두 통과했다.
- 최신 main 기준 draft PR #801을 열었으며 issue #799를 병합 시 자동 종료하도록 연결했다.

## 2026-07-20 (codex agent B) — targeted production lane 적대 리뷰 보강

- PR #792의 첫 적대 리뷰 P1/P2 다섯 건을 반영했다. runner process가 죽은 뒤 늦은 Docker
  create/exec가 recovery clear를 추월하는 창을 없애기 위해 `docker compose exec`를 폐기하고,
  inherited flock과 `setsid` supervisor가 create/start/wait/remove/terminal 전체를 소유하게 했다.
  permanent tombstone은 남기지 않는다. supervisor까지 terminal 없이 죽은 상태만 운영자 확인이
  필요한 fail-closed BLOCKED로 유지한다.
- caller/OCI self-label 비교 대신 root-owned strict C7 attestation verifier를 exact snapshot에서
  재사용한다. host/origin/compose project, compatible-pair v4 active image, command/env hash,
  source revision을 actual runtime과 비교하고, cursor signing secret이 Map API에 정확히 한 번만
  존재하며 다른 credential과 다르고 네 다른 role에는 없는지 음수 테스트로 고정했다.
- exact API image를 network-none/read-only로 생성해 cursor secret 누락 시 migration 전에 exit 1과
  generic message로 닫히는 probe를 추가했다. probe/container raw identity나 stderr는 evidence에
  남기지 않고 enum 결과와 hash lifecycle만 보존한다.
- #741 public bbox는 좁은 좌표 범위에서 items/non-truncated/non-full 조건을 선행 단언한다.
  cleanup은 owned parent를 `FOR UPDATE`로 잠근 transaction 안에서 fingerprint·FK audit·delete를
  수행한다. 이는 PostgreSQL child FK insert의 `KEY SHARE`와 경합하므로 late child를 막는다.
- `T-VN-15`는 같은 검색어의 active place 2건과 Feature-ID-derived idempotency key를 사용한다.
  BFF search의 total on/off 두 page, query/include_total mismatch, payload 한 글자 tamper와 cursor
  비반사를 production live 계약에 포함했다.
- lifecycle/evidence exact file set·phase·count·schema·root mode와 fsync-before-result/clear를 정적
  계약으로 고정했다. 구현/static contract 커밋 시점에는 정책에 따라 테스트·lint·build·parser를
  실행하지 않았다.
- 동일 리뷰어 재검토의 P2 4건에 따라 report subtree를 JSON/XML/HTML exact 3-file allowlist로
  닫고 raw Playwright output을 evidence bind 밖 container `/tmp`로 옮겼다. API runtime env는
  on-disk 파일 없이 unique memory map과 Docker child env·name-only argv로만 전달한다. 기존
  weather/price child도 `FOR UPDATE`하고, normal/recovery cleanup 끝에서 unique search fixture가
  items 0·total 0·cursor 없음인지 다시 단언한다. 관련 strict C7/static·env parser 음수 회귀를
  추가했으며 테스트 실행 금지는 유지했다.

## 2026-07-20 (codex agent B) — #741·#785 live 인수 경계 문서화

- issue #741·#785의 구현은 main에 있지만 production browser가 보낸 stale raw
  `If-Match`와 비공개 status marker를 owned fixture로 끝까지 증명하는 live lane이 없었다.
- strict C7 runner에는 새 feature mutation을 넣지 않는다. 별도 opt-in·serial lane에서 실행별
  고유 user-request Feature만 만들고, 모든 종료 경로는 직전 revision header의 raw ETag로
  delete 요청을 만든 뒤 승인·삭제 확인까지 실패를 전파한다.
- #785 competing write는 승인된 change request로 만들어 실제 revision을 전진시킨다. UI가
  최초 basis ETag로 412를 받은 뒤 dirty draft를 유지하고 명시적 reload 전 자동 rebase하지
  않는 것을 wire와 DOM에서 함께 단언한다.
- #741은 draft/inactive/hidden 세 owned marker를 admin bbox·지도에서 확인하고 public
  active-only 경계의 404/미포함을 함께 단언한다. weather/price는 admin API가 kind 생성을
  지원하지 않으므로 root-owned BLOCKED/journal과 recovery-only 경계를 먼저 만든 뒤 exact
  owned ID의 non-empty value fixture만 직접 만들고 UI panel·admin card·public 음성을 검증한다.
- 이 문서 단계에서는 테스트·lint·build를 실행하지 않았다.

## 2026-07-20 (codex) — n150 0062 전환과 PostGIS topology check 오탐 발견

- 최종 main·PinVi·Manager exact clone과 fresh root-owned backup을 확인하고 C6c capture를
  시작했다. 오래된 Geo env에서 host source와 container path가 뒤섞인 문제를 실제 n150
  source bind와 `/data/juso`로 분리해, 원천 파일 156개와 핵심 테이블 3개의 non-empty
  검증을 통과시켰다.
- Map DB는 예상된 0058이 아니라 실제 0023이었다. capture의 API health timeout보다
  `0060_weather_integrity`가 오래 걸려 transaction이 안전하게 rollback된 뒤, exact revision
  candidate API image로 migration-only를 실행해 0062 head까지 forward migration했다.
- `alembic check`는 app 객체가 아닌 shared Postgres infra owner의 `postgis_topology`가 만든
  `topology.layer`·`topology.topology`를 제거 대상으로 오인했다. production 소유권 배치를
  integration gate에 재현하고 extension-owned schema만 제외하는 `T-ADM-C7F`로 분리했다.
- CodeGraph에서 `_include_object`의 앱 caller가 없고 Alembic callback으로만 소비됨을 확인했다.
  DB schema나 migration revision은 추가하지 않는다. 구현은 단일 적대 리뷰 전 테스트하지 않는다.

## 2026-07-20 (claude, n150) — T-VN-H02 destructive admin 기본값 fail-closed

- `admin_destructive_enabled` 기본값을 `True`에서 `False`(fail-closed)로 내렸다. env
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true`를 명시하지 않으면 파괴적 `/admin`
  작업(restore/swap·feature deactivate·POI cache target·backup·offline upload delete·managed
  file purge)이 403을 반환한다.
- 문서·`.env.example`이 참조하던 env 이름이 실제로는 필드에 바인딩되지 않던 잠복 버그를 함께
  고쳤다. env prefix 규칙상 `KOR_TRAVEL_MAP_API_ADMIN_DESTRUCTIVE_ENABLED`만 동작하고 문서화된
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`는 무시됐다 — `validation_alias`로 문서화된 이름을
  정본으로 고정했다.
- BREAKING 배포 변경: Docker compose에 컨테이너 기본 `true`를 주입해 기존 Docker 배포는 그대로
  동작한다(PUBLIC_API_KEY_REQUIRED·PROFILE와 같은 T-VN-01 패턴). n150 prod는 host env로 이 값을
  유지해야 파괴적 admin 작업이 계속 동작한다. 읽기/관측 전용 배포는 기본값 그대로 둔다.
- 기본 True에 의존하던 router 테스트(admin_files purge, admin_backups delete/restore/swap,
  offline upload delete, admin_features deactivate) fixture에 `admin_destructive_enabled=True`를
  명시했다. test_auth에 기본값 False→403, env enable→통과를 단정하는 테스트 2건을 추가했다.
- n150 CI-parity docker(python:3.13)에서 ruff·대상 pytest·redaction guard를 실행했다.

## 2026-07-20 (codex agent B) — T-VN-59 public weather·curation raw lineage 계약 문서화

- 기준 `integration/t-vn@f5cdeeaa`에서 static/CodeGraph 영향도를 확인했다. weather public
  router는 저장소 timeline/source-record row를 `WeatherValueItem`과
  `WeatherAlertHistoryItem`으로 직접 투영하고, curation public/admin DTO는
  `CurationItemView` 상속을 공유한다. 그 결과 user OpenAPI와 생성 client가 raw lineage에
  도달한다.
- 공개 DTO는 도메인 표현에 필요한 typed 필드만 소유하고 operator raw DTO는 별도로
  정의한다. public curation item의 자유형 metadata는 제거하되 admin UI의 source record와
  metadata 조작·표시는 유지한다. weather alert raw payload와 ingestion timestamp도 admin
  BFF 표면으로 이동한다.
- 단일 component 이름만 검사하지 않고 user operation response에서 `$ref`, array,
  `allOf`/`anyOf`/`oneOf`, object property를 재귀 순회하는 forbidden reachable-schema gate를
  완료 조건으로 고정했다. 이번 문서 단계에서는 테스트·lint·build를 실행하지 않았다.
- draft PR #788 위에 public/admin curation DTO를 상속 없는 타입으로 분리하고 public weather
  DTO도 명시적 이름으로 clean-cut했다. alert 원문은 `/v1/admin/features/weather/alerts`에서
  기존 repository row를 raw operator DTO로 투영한다.
- exporter의 response-root 재귀 gate와 회귀 fixture를 추가하고 full/user OpenAPI,
  admin/user TypeScript, 수기 public curation 타입을 생성·갱신했다. 이는 구현 산출물 생성이며
  적대적 리뷰 승인 전 test·lint·build·OpenAPI `--check`는 아직 실행하지 않았다.

## 2026-07-20 (codex) — T-VN-58 correction 편집 기준 ETag 설계 고정

- issue #785의 stale correction 경로를 ADR-074의 lost-update 원칙으로 구체화했다. 편집 시작 시
  `/revision`과 detail의 같은 `row_revision`을 확인하고 feature ID·raw strong `ETag`·snapshot을
  불변 `CorrectionBasis`로 묶으며, mutation 직전 최신 revision 자동 rebasing을 금지한다.
- `412 Precondition Failed`에서는 작성 중인 draft를 보존하고 자동 재시도하지 않는다. 명시적
  reload 성공 뒤에만 최신 detail과 basis를 적용하며 update와 delete는 각 선택 feature basis를
  사용한다. DB와 REST/OpenAPI schema는 변경하지 않는다.
- 전용 worktree codegraph를 완성한 결과 `fetchFeatureRevisionEtag` caller는 PATCH/DELETE 두 함수,
  mutation hook caller는 `FeatureChangeRequestsClient` 하나로 확인됐다. file-level TypeScript impact의
  저해상도 결과는 직접 symbol inventory로 보완해 API client/hook, change-request component,
  mocked/live Playwright 경계를 고정했다.
- `/revision`→detail 안정 snapshot 재시도, caller-supplied ETag mutation, background refetch 차단,
  412 draft 보존·명시적 reload, delete basis와 live cleanup ETag를 구현하고 API/hook/mocked/live
  회귀 fixture를 작성했다. **다음 한 작업**은 exact head의 단일 적대 리뷰이며, 승인 전에는
  test·lint·build를 실행하지 않는다.
- 첫 적대 리뷰가 최초 basis in-flight draft 덮어쓰기, 실패한 explicit reload의 old data 오인,
  전역 query retry로 인한 3-pair budget 중복, live UI mutation ETag 미단정을 차단했다. edit-session
  dirty guard, refetch error/fetchStatus gate, hook `retry=false`, update/delete baseline raw ETag exact
  assertion과 deferred/500 음성 fixture로 네 건을 보강했다. 새 exact head 재리뷰 전에는
  test·lint·build를 실행하지 않는다.
- 두 번째 적대 리뷰에서 전역 dirty boolean이 basis 전체 적용을 건너뛰어 untouched category/marker에
  add 기본값이 남는 문제와, 의미가 같은 Feature ID 공백 편집이 412 mutation state를 초기화하는
  문제를 확인했다. 필드별 dirty overlay와 `action + trimmed feature_id` 편집 세션 identity로
  교체하고, baseline과 다른 category/marker fixture의 PATCH 미포함 및 동일 identity의 mutation
  횟수 불변 회귀를 추가했다. 명시적 reload 성공은 dirty set 전체를 초기화한다.
- 세 번째 적대 리뷰에서 nullable marker baseline의 표시 fallback이 name-only PATCH에 섞이는 경로와
  deferred basis 중 열린 위치 편집창이 stale marker 기본값까지 parent dirty로 만드는 경로를
  확인했다. PATCH의 category/marker는 해당 form key를 실제 편집한 경우에만 포함하고, 위치 편집창은
  local dirty key만 parent에 적용하며 basis 변경 시 untouched draft만 동기화한다. null marker 및
  dialog 좌표-only deferred fixture로 marker 미포함을 고정했다. `kind`/`status`는 update PATCH
  계약에 없어 다른 non-null add 기본값 ingress가 없음을 함께 확인했다.

## 2026-07-20 (codex, agent B) — T-VN-57 public route 계약 단일 정본 설계

- T-VN-SYNC-02 적대적 리뷰에서 production runtime은 public-keyed GET 29개를 모두
  `require_public_api_key`로 닫지만 full OpenAPI는 curated 4개만
  `PublicApiKey OR ServiceToken`으로 선언하는 P1 drift를 확인했다. full 25개, user 23개
  operation이 기계 계약상 무인증으로 기술된다.
- 원인은 `app.py`의 `_PUBLIC_CURATED_PATHS`와 OpenAPI customizer, user export의
  `USER_OPERATIONS`가 route policy와 별도 수기 정본인 구조다. `ROUTE_POLICIES`와 조립된
  method metadata에서 full/user surface와 security를 파생하고 양방향 전수 비교로 회귀를 막는다.
- DB schema·경로·DTO·runtime 인증 동작은 바꾸지 않는다. CodeGraph 영향도는
  `ROUTE_POLICIES` 57개, `create_app` 176개, route wiring gate caller 5개다. 문서 선행 PR 뒤
  구현을 추가하고 동일 단일 적대 리뷰 승인 전에는 테스트·lint·build·OpenAPI check를 실행하지
  않는다.
## 2026-07-20 (codex) — vNext integration 병합·cross-repo cutover 상태 정리

- main→integration 동기화 PR #781은 CI 8개 green 뒤 merge commit
  `a45bc3ac401e5675811f1031a4592991498d899f`로 병합됐다. `T-VN-SYNC-01`을 완료 이력으로 옮기고
  최종 integration→main PR 단위 `T-VN-SYNC-02`를 active backlog에 추가했다.
- admin 비공개 Feature PR #779는 merge commit
  `21ad4e312b3d2a3e1b8baf1b3103daa6cec15e87`, search total·HMAC cursor PR #780은 merge commit
  `7604fc92585d8f973725f11bf8234a6d22034bc4`, route 인증 gate PR #782는 merge commit
  `226f81c2cb5f89dec9bdd696121f4f8cd60f96c0`로 `integration/t-vn`에 반영됐다. 세 PR 모두
  lint·OpenAPI drift·Python 3버전·fixture replay·PostGIS·frontend를 포함한 CI 8개가 green이다.
- PinVi ops principal PR #393은 merge commit `61820f0ab0a7000948477511b3e92926fe78d1d4`,
  docker-manager production env PR #64는 merge commit
  `3f9973806e8addff96eb1339602f992ed424fb1c`로 각 저장소 main에 반영됐다. 구현 병합과 운영 완료를
  분리해 T-VN-03/04A/15와 T-ADM-C6c/C7P/C7은 final n150 live 증거 전까지 active로 둔다.
- 다음 순서는 이 문서 PR을 integration에 병합 → T-VN-SYNC-02 integration→main → exact
  compatible-pair v4 capture → n150 파괴적 live UI E2E다. T-VN-53 rotation 운영 측정은 별도
  active task로 유지한다.

## 2026-07-19 (codex, agent B) — T-VN-03 교차 리뷰 P2 수정

- 적대적 교차 리뷰에서 runtime/full OpenAPI에는 존재하는 curated sources/themes가
  `USER_OPERATIONS`에 없어 user OpenAPI와 `@kor-travel-map/map-user-client`에서 누락된
  P2를 확인했다.
- public curated 계약을 feature list/detail, sources, themes 네 GET으로 고정하고 user
  allowlist/export 회귀/생성 타입을 함께 갱신한다. `settings.py` E501은 의미 변화 없는
  줄바꿈으로 처리한다.
- docker-manager production env mapping P1은 manager PR이 소유하므로 Map diff에 섞지 않는다.
  같은 리뷰어 재승인 전에는 테스트·lint·build를 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-03 Map route gate 구현

- public curated 4경로를 public key dependency에 포함하고, ops metrics/log/
  consistency/deep-health 6경로는 BFF 또는 read token+`ops:read`로 닫았다. MOIS raw는
  local-dev mount에서도 BFF를 요구하며 production에는 mount하지 않는다.
- route policy registry의 MOIS를 operator로 옮기고 T-VN-03 wiring exception 10개를
  모두 삭제했다. 삭제 route·alias·legacy header fallback·새 env·DB migration은 없다.
- OpenAPI full에는 curated `PublicApiKey OR ServiceToken`, ops 관측
  `AdminBFF OR (OpsToken AND OpsScope)`, MOIS `AdminBFF`를 선언한다. user subset은 ops/debug를
  제외하고 public scheme만 유지하며 admin/user TypeScript를 같은 spec에서 재생성한다.
- same-origin admin UI BFF가 관측 read에도 actor+proxy secret을 주입하는 회귀와 Python auth/
  route-policy/OpenAPI 회귀를 추가했다. PinVi issue #392의 구현 PR #393과 이 Map exact head는
  C6c manifest v4 exact source pair로만 활성화한다.
- CodeGraph 영향도는 `create_app` 181개, `require_ops_operator` 199개,
  `require_public_api_key` 58개, `assert_route_policy_wiring` 44개 심볼이다. 사용자 지시에 따라
  동일 리뷰어 승인 전 테스트·lint·build는 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-03 route gate docs-first

- 최신 `integration/t-vn@a45bc3ac`에서 curated public GET 4개, ops 관측 GET 6개,
  MOIS raw debug GET 1개의 현행 mount와 route policy를 대조했다.
- ops는 기존 `require_ops_operator`, curated는 `require_public_api_key`, MOIS raw는 production
  unmount를 유지하면서 local-dev mount에도 `require_admin_frontend`를 적용하는 clean-cut을 정했다.
  새 secret/env, DB migration, alias, 삭제 route 복원은 없다.
- PinVi PR #387의 관측 client 네 메서드가 `_ops_headers("ops:read")`를 사용하지 않는 blocker를
  확인해 issue #392를 만들었다. Map+PinVi exact heads는 C6c manifest v4 source pair에 함께
  결박해야 한다.
- CodeGraph 영향도는 Map `app.py` 38 symbols, ops dependency caller 10개, public dependency
  caller 3개, route wiring gate caller 5개다. 동일 리뷰어의 양 저장소 교차 승인 전에는
  테스트·lint·build를 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-15 search total·HMAC cursor 구현 준비

- `/v1/features/search`는 `include_total=false`에서 COUNT SQL을 만들거나 실행하지 않고,
  `true`에서만 같은 filter COUNT를 한 번 실행한다. items/keyset은 total opt-in과 무관하다.
- cursor v1은 정규화 q/bbox/kind/category/sort/page_size/include_total의 SHA-256 fingerprint와
  keyset을 canonical payload에 담고 전용 server-only secret으로 HMAC-SHA256 서명한다.
  malformed/unknown version/tamper/query mismatch는 DB 전에 네 typed RFC7807 422로 분리한다.
- cursor는 stateless REST 상태이므로 schema/migration을 추가하지 않는다. production은 feature
  surface 활성 시 전용 32자 이상 secret을 기동 전에 요구하고, local-dev만 process-local 난수
  fallback을 허용한다. 테스트/lint/build는 동일 단일 적대 리뷰어 승인 뒤 실행한다.
- repository/client/API와 typed RFC7807 매핑, API-only settings·Compose·entrypoint·launcher,
  admin UI consumer, admin/user OpenAPI·생성 TypeScript를 같은 계약으로 갱신했다. cursor secret은
  public/admin/service/ops/metrics 경계와 재사용할 수 없고 실제 값은 코드·문서에 기록하지 않는다.
- repository statement spy와 실제 PostgreSQL COUNT 관측, query mismatch DB 0회, 변조·unknown
  version·malformed/keyset 회귀, production/runtime env matrix, API error code와 UI request builder
  테스트를 작성했다. 이 단계에서는 리뷰 정책에 따라 아직 실행하지 않았다.
## 2026-07-19 — T-VN-04A admin 비공개 Feature 공간·카드 구현 (codex agent B)

- issue #741의 두 회귀를 한 PR 경계로 확정했다. admin `/features` 지도는 공개 bbox/cluster를
  호출하지 않고 `feature.features` 기반 admin in-bounds API로 전환하며, 반복 `status` 필터로
  `inactive`·`draft`·`hidden`을 포함한 운영 상태를 찾는다.
- admin weather/price subresource는 base Feature 존재 여부를 검사한다. 특히 weather의 근접
  anchor 탐색도 admin projection을 사용해 비공개 target의 카드가 공개 view 때문에 비는 경로를
  닫는다. public API의 active-only 계약은 그대로 유지한다.
- schema 변경은 불필요하다고 판단했다. 기존 base table과 coord/geom 인덱스로 요구를 충족하며,
  신규 호환 shim이나 provider wrapper를 만들지 않는다.
- repository/API/UI를 구현하고 full OpenAPI·admin TypeScript 타입을 재생성했다. admin 지도
  route-mock과 base/public 분리 PostGIS 회귀도 작성했다. 사용자 지시에 따라 구현 테스트·lint·
  build는 정확한 diff의 적대 리뷰 승인 뒤에만 실행한다.
- 첫 정적 리뷰의 soft-delete finding을 반영해 admin weather/price target 존재 판정을
  row revision 조회에서 삭제 전 base predicate로 분리했다. inactive/draft/hidden은 유지하고
  `deleted_at`·`user_deleted_at`·`status=deleted`와 실제 미존재는 404로 닫는다.
- 테스트 단계의 frontend type-check가 드러낸 계약 모호성을 제거했다. admin request의 `zoom`은
  호출부에서 명시하고, in-bounds `items`/`clusters`는 양 mode 모두 필수 배열로 고정해 사용하지
  않는 쪽을 `[]`로 반환한다. optional cast나 non-null assertion은 추가하지 않았다.
## 2026-07-19 (codex) — latest main → integration/t-vn 동기화 PR 준비

- `integration/t-vn@22bf35a5`에서 전용 branch `chore/t-vn-sync-main`을 만들고
  `main@d2104f15`를 merge했다. 공유 integration branch 자체는 rebase하지 않는다.
- `CHANGELOG.md`, `docs/journal.md`, `docs/resume.md`, `docs/tasks-done.md`는 main의 더 최신
  기록 뒤에 integration 기록을 이어 양쪽 역시간 이력을 보존했다. API Dockerfile은 main의
  OCI revision `ARG`/`LABEL`과 integration의 production profile fail-closed 기본값을 함께 유지했다.
- 완료된 T-VN Wave 0~1과 `T-VN-05R/14R/17R/21R`을 완료 정본으로 옮기고 active backlog에서
  제거했다. 실제 미완 `T-VN-03`, `T-VN-04A`(#741), `T-VN-15`는 유지했으며 migration은
  `0058 → 0059 → 0060 → 0061 → 0062` 단일 chain을 확인했다.
- 코드 충돌을 포함한 sync이므로 동일 전문 리뷰어 승인 전 테스트·lint·build는 실행하지 않는다.
  정적 conflict marker, merge tree, 비밀·prod redaction 검증 뒤 draft PR로 제출한다.

## 2026-07-19 (codex) — T-ADM-C7P manifest v4 교차 계약 착수

- 승인된 local-only n150 SSH target에서 passwordless sudo를 재확인했고, C6c
  capture 실패의 직접 원인이 cAdvisor listen 포트와 image에 상속된
  healthcheck 포트의 drift임을 확인했다.
- docker-manager PR #61 적대적 리뷰에서 Map API만 compatible pair에 기록하면
  UI·Dagster web·daemon의 `development` image가 남을 수 있는 교차 사각지를
  blocker로 확정했다. manager는 Map 네 image ID를 모두 결박하는 manifest v4로
  clean-cut한다.
- Map C7 attestation은 manager manifest v3과 API/PinVi image ID만 exact 허용해 v4를
  즉시 거부한다. issue #777·T-ADM-C7P는 manifest v4의 9-field pair와 네 Map
  runtime role를 동기화하는 독립 PR 단위다.
- `T-VN-03=C6c 동일 배포`와 `C7 이후 integration→main`을 동시에 적용하면
  순환 의존이 된다. C7P code를 main에 먼저 병합하되 활성화하지 않고,
  main→integration 동기화→잔여 T-VN 종결→integration→main→C6c capture→C7 live
  순서로 순환을 제거한다.

## 2026-07-19 (codex) — Agent A PR #755 심층 리뷰 후속

- 단일 전문 리뷰에서 `/ops/datasets` summary projection이 exact count만 확인해
  `hidden`/`display:none` 회귀도 통과할 수 있는 S3를 확인했다.
- positive·오염 negative fixture의 12개 exact projection을 각각 유일성 확인 뒤
  `toBeVisible()`로 검증하도록 보완했다.
- Next dev server를 별도 기동한 targeted mocked E2E 3개와 E2E TypeScript,
  대상 ESLint가 통과했다.

## 2026-07-19 (codex) — Agent A PR #754 심층 리뷰 보안 후속

- 단일 전문 리뷰에서 local-only 배포 문서의 Docker context 유입, 실패 뒤 recovery
  runtime 삭제, Playwright container의 host network/IPC 공유, 제한된 residue glob만
  쓰는 preflight를 S2/S3로 확인했다.
- `*.local.md`를 build context에서 제외하고 executor를 bridge/private 경계로 줄였다.
  전체 상태 auditor가 unsafe·unexpected·active·recovery residue를 거부한 뒤에만 lock과
  mutation 상태를 만들며, 실패 경로는 `BLOCKED.json`과 journal/runtime을 보존한다.
- 같은 리뷰어의 재검토에서 root로 실행하는 auditor가 3파일 attestation 밖에 있던 문제와
  INT/TERM이 active child 없는 구간에서 성공으로 정리될 수 있던 문제를 P1으로 확인했다.
  auditor를 4파일 exact snapshot/hash에 포함하고 signal 종료를 130/143으로 고정한 뒤
  P0~P3 잔여 없음으로 승인받았다.
- Linux `/tmp` 기준 대상 보안/unit 55개와 전체 unit 1,529개, `bash -n`, Ruff,
  strict mypy, import-linter를 통과했다.
- PR #754와 네 파일 attestation·signal 종료 후속 PR #762는 PostGIS integration을 포함한
  CI 8개를 각각 통과해 merge commit `b9f23a42`, `bece2c32`로 `main`에 반영됐다. 현재
  exact commit Git archive 기반 immutable executor build도 성공했으며 `T-ADM-C7H`를 완료
  이력으로 옮겼다.

## 2026-07-19 (codex) — C7 prod readiness 차단 리뷰 반영

- 단일 적대 리뷰에서 배포 pair·DB schema·실제 service runtime attestation 부재, host npm/Chromium
  의존, 잘못된 Dagster job 선언, preflight 이전 sentinel, 실패 증거 삭제를 P1/P2로 판정했다.
  실제 실행 job `feature_update_request_worker`의 repository cardinality와 terminal run/tag identity를
  파괴적 mutation 전에 검증하도록 계약을 바로잡았다.
- `docs/runbooks/c7-prod-live-e2e.md`와 `T-ADM-C7H`를 먼저 작성했다. host runner/helper는 exact
  commit의 root-owned Git archive snapshot과 attested SHA-256에서만 실행한다. runner는
  C6c v3 manifest(source revision 포함), compose project, Map API/UI/Dagster web·daemon/PinVi API
  runtime hash, 단일 Alembic
  head/check와 UI login을 모두 read-only 검증한 뒤에만 root state와 `BLOCKED.json`을 만든다.
- PR #754 리뷰의 정적 계약 테스트 한계를 반영해 snapshot/runtime 검증 코어를 import 가능한
  `c7_prod_attestation.py`로 분리했다. runner bootstrap은 검증한 동일 module bytes를 실행하며
  root로 실행하는 runner/helper/module/상태 감사기 4개의 hash, owner/mode/ancestor와
  compatible-pair·OCI/runtime metadata 변조를 실행형 음수 fixture로 고정했다. INT/TERM은
  각각 130/143으로 종료해 신호 중단을 성공 정리로 오인하지 않는다. 같은 단일 리뷰어의
  최종 판정은 P0~P3 잔여 없음이며 대상 55개와 전체 unit 1,529개가 통과했다.
- Playwright는 고정 official digest 기반의 commit-labelled executor image ID로만 실행한다. spec별
  redacted JUnit/HTML/JSON과 journal을 root-owned evidence에 fsync하며 screenshot, auth storage와 trace ZIP은
  제외한다. `audit-c7-prod-live-state.py`는 값·UUID 없이 partial restore, active lock, unsafe residue를
  보고하고 자동 clear는 제공하지 않는다.
- executor container는 durable creator PID/PGID/start ticks와 atomic create outcome을 먼저 기록하고
  `docker create --pull=never` 결과 CID/identity를 검증한 뒤에만 start한다. create 완료 여부가 불명확하면
  stop 도구도 ref를 지우지 않아 late container를 감사 범위 밖으로 보내지 않는다.
- n150 접속 감시 10분 41회가 모두 인증 전에 `No route to host`로 끝났고 별도 Windows TCP/22 진단도
  실패했다. passwordless sudo는 미확인으로 남겼으며 원격 변경은 하지 않았다.

## 2026-07-19 (codex) — T-ADM-C7M mocked UI projection·pagination 병합

- `/ops/datasets` mocked E2E가 이름 있는 summary landmark 안에서 행·실패·SLA 초과·미실행·이슈를
  exact 검증하고, 같은 문자열로 표 행을 오염한 negative fixture로 page-global text 거짓 양성을
  차단하도록 보강했다.
- `/ops/pipeline`은 실행과 전역 event 각각 6+6 두 페이지를 주입해 exact
  provider/dataset/scope/page size, null/expected cursor 요청, 페이지별 전체 DOM identity 배열,
  total order, 페이지 간 서로소와 continuation 종료를 함께 검증한다.
- 단일 적대적 리뷰에서 느슨한 query route를 확인해 exact query validator와 관측 cursor set을
  반영했다. 6+6은 실제 `page_size=50` overflow가 아닌 cursor plumbing 증거로 문서화했고,
  51건 이상 실제 continuation은 `T-ADM-C7` n150 live E2E에 유지했다.
- targeted mocked E2E 3건과 CI 8개 게이트가 통과했다. PR #755는 merge commit `54150c91`로
  `main`에 반영됐으며 `T-ADM-C7M`을 완료 아카이브로 이동했다.
## 2026-07-19 (codex) — PR #772 T-VN-13 단일 적대 리뷰 보완

- 전문 리뷰어 1명이 테스트 전에 PR 전체를 심층 검토해 pending 승인 TOCTOU, add의 기존 feature
  덮어쓰기, aggregate detail의 잘못된 validator, public ETag 누락, 느슨한/중복 ETag 허용,
  migration partial-state 위험, Admin·PinVi 소비자 미배선을 확인했다.
- pending update/delete는 제출 시 `base_row_revision`을 저장하고 승인 transaction의 row lock 아래서
  다시 비교한다. add는 `ON CONFLICT DO NOTHING` 뒤 충돌 처리해 중간 insert를 보존한다. PATCH/DELETE는
  정확히 한 개의 canonical strong `If-Match`만 받고 missing/stale/invalid를 404/412/422/428로 구분한다.
- public detail에 ETag/304를 제공하고 Admin에는 feature row만 대표하는 revision endpoint를 분리했다.
  bundled frontend와 PinVi client는 revision GET→raw ETag 전달을 수행하며 PinVi는 412를
  `PRECONDITION_FAILED`로 보존한다. OpenAPI와 생성 TypeScript 타입도 같은 계약으로 갱신했다.
- 리뷰 후 Map 라우터 단위 46건, 실제 PostgreSQL migration·repository 경쟁 14건, Ruff,
  strict mypy(main 115/API 54), import 계약 4개, OpenAPI·생성 타입 drift와 frontend 앱/E2E
  typecheck를 통과했다. PinVi 쪽은 Admin client 단위 110건과 412/no-audit 통합 1건,
  Ruff·strict mypy 188개 소스를 통과했다.
- 원 PR #772가 검증 중 먼저 병합되어 보완은 후속 PR #776으로 `integration/t-vn`에 반영한다.

## 2026-07-19 (codex) — PR #773 2차 적대 리뷰 blocker 구현

- 행정 경계를 가로지르는 route/area도 선택 단위의 **저장 canonical 행정코드 하나에 1회
  귀속**하는 규칙을 `rest-api.md` 정본과 repository docstring에 명시했다. geometry 교차
  부분은 bbox 내부 marker 위치에만 쓰고 cluster 귀속을 바꾸지 않는다.
- `ClusterUnit` literal을 공통 response 모듈로 옮기고 `ClusterMeta`의 현재 단위를 필수
  enum, drill-down을 필수 enum|null로 좁혔다. OpenAPI admin/user와 두 TypeScript 타입을
  다시 생성했다.
- 서로 다른 저장 코드를 가진 교차 route/area가 각 단계에서 정확히 한 번씩 집계되는 통합
  fixture, strict schema 단위 회귀, coord 없는 route/area 대표 분포에서 partial geom GiST를
  planner 기본 설정으로 고정하는 EXPLAIN 회귀를 추가했다.
- 사용자 지시에 따라 적대적 재리뷰 전 테스트는 실행하지 않는다. 다음 단계는 같은 리뷰어의
  blocker 재검토이며, 승인 뒤 테스트 게이트를 실행한다.

## 2026-07-19 (codex) — Agent A PR #763 심층 리뷰 후속 보완

- route/area exact predicate의 centroid coord 우회를 차단하고, cluster도 items와 같은 exact
  공간 후보 술어를 공유하게 했다. geometry 후보의 cluster marker는 bbox와 실제 교차한
  부분 위에서 계산한다.
- ADR-048 envelope 불변식 위반을 닫아 `cluster_unit`/`drill_down_unit`을 data에서 제거하고
  `meta.cluster` 한 곳으로 이동했다. OpenAPI admin/user와 두 TypeScript client type도 이
  정본에서 다시 생성한다.
- geometric centroid가 bbox 안이지만 polygon hole이 bbox를 포함하는 음수 fixture와
  coord 없는 교차 geometry가 cluster count/marker에 포함되는 회귀 검증을 추가했다.
- #763이 검증 중 먼저 `integration/t-vn`에 병합되어, 수정은 같은 통합 브랜치 대상 후속
  PR로 반영한다(`main` 직접 병합 없음).
- 검증: 전체 main unit 1,503건, API router 26건, exact membership/cluster 통합 3건,
  cluster EXPLAIN 2건, tier-1 성능 12건, public view/cluster 회귀 17건이 통과했다.
  OpenAPI admin/user drift, admin/user TypeScript type-check, E2E ESLint, Ruff, main strict
  mypy, 변경 API strict mypy, import-linter 4계약, redaction도 통과했다.
## 2026-07-19 (codex, agent B) — T-VN-05R public curated allowlist

- PR #752의 T-VN-05가 feature detail/batch에서 제거한 raw 경계를 public curated
  list/detail이 기존 admin DTO 재사용으로 우회하던 issue #765를 구현했다.
- 공개 전용 DTO와 명시 mapper를 추가해 표시·위치·큐레이션·출처 표시 필드만
  직렬화한다. 동일 리뷰어 지적을 반영해 공개 모델을 `feature_kind` 판별 7종 union으로
  구체화하고 주소·kind별 detail·place 시설/영업시간/전화/리뷰 링크를 strict 중첩 DTO와
  명시 projector로 닫았다. 알 수 없는 kind는 목록 제외/상세 404다.
- 실제 concierge YouTube/transcript/evidence 평면 미러와 중첩 raw sentinel을 주입해
  공개 list/detail에서 제거되는 회귀, admin raw 보존,
  full/user OpenAPI의 public/admin schema 분리와 user generated type drift를 함께 고정했다.
  공개 query의 `theme_id/source_id/provider/dataset_key`도 제거해 표시·위치 탐색과 admin
  identity 탐색을 분리했다. 요청에 따라 이 커밋에서는 테스트를 실행하지 않는다.

## 2026-07-19 (codex, agent B) — T-VN-21R release benchmark 측정 정확성

- #767 finding을 하나의 release evidence 정확성 경계로 묶었다. `--skip-seed`는
  `feature.public_features` 실제 non-notice ID를 정렬해 200건 batch를 구성하고,
  seed 모드도 과거 `perf:f:*` 고정 ID와 다른 prefix를 적재한 뒤 DB 선택 경로를
  공유한다. seed의 매 29번째 inactive 규칙을 selector 기대값에도 반영한다.
- 대표 viewport별 최소 반환 행(일반 1, batch 200)을 못 채우거나 EXPLAIN
  최상위 Plan 행과 실제 `returned_rows`가 다르면 JSON 성공 report를 남기지 않는다.
  terminal LIMIT 전 별도 count를 `matched_rows`로 기록해 truncation을 보존하고,
  shared read는 최상위 Plan 누적값만 써 child 중복 합산을 제거했다.
- seed/skip-seed의 고정 ID 부재, public 199건 fail-closed, 모든 viewport
  cardinality·notice 후보 제외·실제 truncation, root/child·Append/parallel plan shape
  회귀 테스트를 작성했다.
  현재 단일 적대적 리뷰 전이므로 테스트는 실행하지 않았다.

## 2026-07-19 (codex) — 최근 48시간 Claude PR 단일 적대 리뷰

- 닫힘 여부와 무관하게 PR #752/#756/#757/#759/#760/#763을 전문 리뷰어 1명이 재검토했다.
  기존 상세 리뷰 완료·리뷰 반영 전용·문서/기계적 PR은 사용자 지시에 따라 중복 리뷰하지 않았다.
- PR #752의 public curated raw lineage 우회(#765), PR #756의 dedup→UNIQUE writer race(#766),
  PR #760의 0행 실데이터 batch와 EXPLAIN buffer 중복 합산(#767), PR #763의 cluster/items 공간
  후보집합 불일치(#768)를 상세 코멘트하고 아이템별 이슈로 묶었다. #757/#759는 잔여 finding이 없다.
- `T-VN-05R/17R/21R/14R`를 독립 PR 경계로 추가했다. 0060은 아직 main cutover 전이므로
  transactional non-concurrent UNIQUE로 직접 정정하고, #768은 열린 PR #763에 후속 커밋한다.
- T-VN-17R은 retry 잔여가 있을 때만 동명 index/constraint를 5초 제한의 짧은 autocommit DDL로
  먼저 정리한다. main transaction은 `SHARE ROW EXCLUSIVE`로 SELECT를 허용하고 weather DML만
  차단한 채 dedup, non-concurrent UNIQUE, NOT VALID 제약 추가를 commit한 뒤 VALIDATE한다.
  실제 migration DELETE를 advisory gate로 멈춰 두 번째 connection INSERT가 막히는 회귀와
  과거 concurrent 실패가 남긴 INVALID index를 새 migration이 교체하는 회귀를 작성했다.
- 첫 단일 적대 리뷰의 P1/P2를 반영해 autocommit VALIDATE에도 session-level 5초 lock timeout과
  `RESET`을 보장하고, range/payload/FK 기존 오염은 첫 commit 전에 SQLSTATE `23514`로 거부한다.
  VALIDATE blocker를 실제로 선점시킨 timeout·partial-state 재시도 회귀를 추가했으며, 실패한
  `asyncio.to_thread` migration은 backend terminate 후 bounded join한다. 0060 downgrade는 dedup loser와
  semantic writer를 함께 복원할 수 없어 backup/PITR+구 image 동시 복구만 허용한다. Alembic env의
  destination guard가 현재 head에서 0060 아래 target을 descendant DDL 실행 전에 전역 거부한다.

## 2026-07-19 (claude, agent A2) — T-VN-14 지도 in-bounds 완결성 + exact 공간 술어

- ADR-073 D-9-3/D-9-4 / F-8: `include_geometry`가 응답이 아니라 **결과집합**을 바꾸던
  버그(2220→2221행)를 고쳤다. `_FEATURES_IN_BBOX_SQL`(경량)과
  `_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL`(geometry)의 WHERE를 **동일한 단일 후보 술어**로
  통일했다 — 두 SQL의 WHERE가 문자적으로 같아졌고(import 검증), 차이는 SELECT projection
  (route/area GeoJSON + 면적 직렬화)뿐이다. membership은 안정, payload만 다르다.
- exact 공간 술어: 후보 술어의 route/area arm에 `&& envelope AND ST_Intersects(geom,
  envelope)`를 적용했다. `&&`는 partial GiST(`idx_features_geom_gist`)를 구동하는 MBR
  prefilter로 남기고 exact `ST_Intersects`로 false positive를 제거한다. point `coord`의
  `&&`는 점-envelope 교차에서 이미 정확해 그대로 뒀다. `ST_Transform`은 술어에 없다(ADR-012).
- 후보 술어 단일화(D-9-4): 공통 attribute 필터(kind/category/provider EXISTS)를
  `_bbox_attribute_filter_sql`로, 공간 후보 술어를 `_bbox_candidate_predicate_sql`로
  한 곳에 정의해 경량/geometry/cluster 3변형이 재사용한다. 심층 리뷰 후 cluster도 exact
  geometry 후보를 집계하고 bbox 교차 부분 위의 대표 좌표를 만들도록 바로잡았다.
- in-bounds 응답 완결성: `PublicFeatureListData`에 `mode`(items|clusters)·`truncated`·
  `coverage`(returned/limit)를 명시했다. truncation은 `max_items+1` 조회로 판정해
  **명시적**으로 노출한다(F-8 silent truncation 해소). cluster drill-down은 data의 결정적
  `cluster_key`(행정코드)와 `meta.cluster`의 현재/다음 단위로 표현한다.
- 스코프 준수: bbox/in-bounds/cluster **READ SQL + in-bounds 응답 DTO만** 수정. public_features
  view(T-VN-04)·weather/price LATERAL(T-VN-38)·인덱스/모델(T-VN-18)·write 경로(A1 T-VN-13)는
  무수정. OpenAPI admin/user 재생성(drift 0).
- 검증(WSL testcontainers PostGIS, 최소 seed): 신규 membership-stability 통합 2건(exact
  ST_Intersects가 MBR false positive 제외 + include_geometry true/false 동일 집합) +
  perf-gate tier-1 12건(경량 bbox가 여전히 coord GiST, features Seq Scan 없음 — ST_Intersects
  OR-arm 추가 후에도 green) + public-features-view/cluster 회귀 17건 = 31 green. router 단위
  30 green(mode/truncated/coverage/drill-down 계약 assert 추가). ruff·mypy --strict(core+api)·
  lint-imports·redaction clean. C: 디스크 무증가.

## 2026-07-19 (claude, agent A1) — T-VN-13 Feature row_revision + If-Match/ETag

- report D-10-3/D-9-8: `feature.features`에 server-owned monotonic `row_revision`
  (bigint)을 추가하고(migration 0062) correction PATCH/DELETE/approve에 If-Match/412·
  admin detail read에 ETag/304를 연결했다. policy revision ledger(#727/0056)와 합치지
  않는다(F-2: 그건 provider-refresh-policy CAS로 별개 자원).
- **revision 메커니즘 = BEFORE UPDATE 트리거**(0058 poi lock_version 패턴 미러링):
  `feature.force_features_row_revision()`가 모든 UPDATE에서 `NEW.row_revision :=
  OLD.row_revision + 1`을 강제 — application이 값을 무엇으로 보내도 우회 불가·server-owned.
  provider upsert의 ON CONFLICT DO UPDATE, soft-delete, deactivate, change apply 등
  **모든 write 경로가 자동 bump**(provider path 비면제 — F-2가 지목한 data_version은
  provider load에서 0이라 validator 부적합). 한 correction이 여러 UPDATE(apply +
  data_version set)를 내면 revision이 2 이상 뛴다 — 단조·불투명 counter라 무방(clients는
  ETag를 opaque로 취급). 기존 `trg_features_coord_precision`(coord 한정 BEFORE 트리거)과
  독립 실행.
- **online-safety(D-12)**: `ADD COLUMN ... DEFAULT 1`은 PG11+ 메타데이터 전용이라 대형
  features rewrite/backfill 없이 즉시 적용. CHECK(`row_revision >= 1`)는 NOT VALID 후
  같은 migration transaction에서 VALIDATE. model(`FeatureRow`)에 컬럼+CHECK를 미러링해 T-VN-19
  metadata 정합 gate(autogenerate diff 0) green.
- **If-Match/ETag 배선**: ETag = row_revision strong validator(`"7"`). correction
  PATCH/DELETE는 If-Match 필수 — 누락 428, 형식오류 422, stale 412(제출 직전
  `SELECT ... FOR UPDATE`로 현재 revision 대조, 없는 feature는 404). 승인 요청은 제출 때 저장한
  `base_row_revision`을 적용 직전 다시 대조한다. public detail GET은 ETag/304, Admin은 별도
  revision endpoint를 제공한다. `FeaturePreconditionFailed`는
  `FeatureChangeConflict`(409)와 구분되는 별도 예외.
- **breaking**: bundled admin frontend와 PinVi Admin client가 revision GET→If-Match를 수행한다.
  PinVi는 upstream 412를 자체 Admin API의 412 `PRECONDITION_FAILED`로 보존한다. OpenAPI/생성 TS
  타입도 재생성했다.
- 검증: 신규 admin_features 라우터 단위 16 green(428/422/412/304/ETag·expected_row_revision
  passthrough 포함), row_revision 통합 3 green(트리거 단조·If-Match precondition, WSL
  testcontainers 1행 seed), alembic metadata 정합 gate green, ruff/mypy(--strict 신규 파일)/
  lint-imports clean, openapi drift 0(user spec 무변경). feature_repo READ SQL/라우터/모델의
  bbox 경로(A2 T-VN-14)는 건드리지 않음 — write/revision/ETag 경로만 국소 변경.

## 2026-07-19 (claude, agent A1) — T-VN-21 3단 성능·DDL gate 인프라

- ADR-075 D-12-4 / performance.md §8.3을 3단 gate의 **정본**으로 확정하고 CI·release
  절차에 연결했다. 일회성 측정이 아니라 상시 인프라다(무엇이·어디서·어떻게 실행되는지 §8.3).
- tier-1(매 PR, 기존 integration job): `tests/integration/test_perf_gate_tier1.py`가
  hot public query 9종(bbox/in-bounds·nearby·search·detail·batch·category counts·
  cluster sido/sigungu/eupmyeondong)을 planner-default EXPLAIN(`enable_seqscan` 미조작)해
  `feature.features` Seq Scan 부재 + 기대 index 사용을 검증하고, public batch read의 SQL
  statement 수가 item 50→100에도 1건으로 일정함(N+1 가드), 결과 컬럼이 frozen snapshot과
  일치함(response-shape 회귀)을 확인한다. hot query registry·seed·EXPLAIN helper는
  `tests/integration/perf_gate.py`. hot query 추가는 `HOT_QUERIES` 한 줄.
- tier-2(release/cutover, **CI 아님**): `scripts/perf_tier2_release_harness.py`가 100만+
  실분포 fixture에서 대표 viewport(서울 밀집·전국 low-zoom·100km nearby·상용 검색어·200건
  batch)를 EXPLAIN(ANALYZE,BUFFERS)로 재고 p50/p95·shared read blocks·응답 bytes를 JSON으로
  기록한다. `--rows 2000` smoke green(예: 200건 batch p95 0.41ms, 100km nearby p95 11.65ms).
- tier-3(index/DDL PR): `perf_gate.measure_index_write_cost`로 변경 전후 write 비용·index
  크기를 측정해 PR에 첨부한다(GiST partial 정리 ~1.6× write 개선 선례). 변경별 index가 달라
  하드 CI gate 불가라 리뷰가 첨부 여부를 enforce한다.
- 스코프 준수: `feature_repo` 쿼리/라우터/마이그레이션/모델 무수정(hot SQL 상수는 읽기만).
  모든 hot query가 planner 기본에서 `features` clean — 실 perf-bug 없음(STOP 불필요).
  small-fixture에서 category-counts 등 집계가 index를 타려면 공개 notice 필터의 `source_links`
  NOT EXISTS anti-join이 populated여야 해서 seed가 features + source lineage를 함께 채운다.
  price/weather LATERAL의 빈 aux 테이블 seq scan은 fixture-size 산물(`features` 아님)이며 aux
  index 실효는 tier-2 실분포에서 잰다.
- 검증: tier-1 12 tests green(WSL testcontainers PostGIS), ruff·mypy --strict(신규 파일, main
  패키지 무변경)·lint-imports·redaction clean. src 무변경이라 openapi drift 없음.

## 2026-07-19 (claude, agent A1) — T-VN-20 body actor 전면 제거 (principal 파생 완결)

- ADR-066 D-2: 모든 admin write의 감사 actor를 request body가 아니라 인증
  principal(`AdminProxyContext.actor`, admin BFF의 `X-Kor-Travel-Map-Actor`)에서만
  파생하도록 완결했다(T-VN-07 auth-event slice의 전면 sweep). 7개 router handler에
  `context = Depends(require_admin_frontend)`를 주입하고(FastAPI가 router-level
  dependency와 캐시 공유) body.operator/actor/reviewed_by/created_by → context.actor로
  전환했다.
- REMOVE vs ACCEPT-AND-IGNORE 결정은 stale F-4가 아니라 PinVi `origin/main`의 실제
  client(`apps/api/app/clients/kor_travel_map_admin.py`)를 대조해 판정했다. PinVi가
  실제로 보내는 것은 feature(operator="pinvi-admin")·issue(operator)·dedup(reviewed_by)
  뿐이라 이 3개는 deprecated 필드로 **수용·무시**(옛 caller 422 방지), 나머지 4개
  (auth-event actor·curated select/unselect actor·enrichment reviewed_by·offline
  created_by/operator)는 PinVi 미호출이라 **schema에서 제거**(extra="forbid" → 422).
  현재 PinVi에는 auth-event/curated select-unselect client 메서드가 없어 F-4보다 좁다.
- admin frontend sweep(subagent): auth-audit·curated·dedup·enrichment·issues·features·
  offline client에서 body actor 전송(하드코딩 "admin-ui"/"local-admin"/"ui-auth")과
  operator/created_by 폼 입력을 제거하고 BFF actor header만 쓰게 했다. OpenAPI/생성 TS
  타입 재생성 + typecheck/build.
- 테스트: 각 swept route가 principal(local-dev)을 기록하고 body 위조 값은 무시함을
  검증하고, 제거된 필드를 보내면 422(auth-event·curated·enrichment·offline), deprecated
  필드는 200+무시(feature·issue·dedup)임을 두 class로 확인했다. 기존 router 테스트의
  body-actor 단언을 principal로 갱신하고 422 테스트를 추가했다.
- PinVi 조정: `docs/integration-map.md` §3.3에 accept-and-ignore 3필드와 PinVi client의
  전송 중단 follow-up(별도 PR)을 성문화했다. 검증: api 관련 router 테스트 159 green,
  openapi drift 0, ruff/mypy --strict clean.

## 2026-07-19 (claude, agent A2) — T-VN-18 중복 GiST 제거 + BRIN 감사 (migration 0061)

- F-8/D-12-3: geoalchemy2 기본 `spatial_index=True`가 0002 create_table 시 만든
  자동 full GiST 3개(`idx_features_coord`/`idx_features_coord_5179`/
  `idx_features_geom`, WHERE 없음)를 제거하고, 공개 술어 partial GiST 3개
  (`idx_features_*_gist`, `WHERE deleted_at IS NULL`)만 유지한다.
- models.py: 3 geometry 컬럼에 `spatial_index=False` → metadata가 partial 3개만
  선언(T-VN-19 metadata gate 정합 유지, gate green 확인). 0061이 DB의 자동 full
  3개를 `DROP INDEX CONCURRENTLY`(autocommit_block)로 제거.
- **write-cost 실측(§8.3 필수)**: 전용 testcontainers DB에서 full 재생성(6 GiST)
  vs partial만(3 GiST)로 40k point INSERT 비교 — 2회 측정 6-GiST≈1.98~2.39s,
  3-partial≈1.67~1.85s, **ratio(6/3)≈1.18~1.29×**(partial-only가 빠름; 점 insert는
  coord/coord_5179 축만 색인해 report의 ~1.6× 대비 완만, geom은 point row에서 색인
  대상 아님). `test_gist_brin_index_audit.py::test_dropping_full_gist_reduces_write_cost`.
- **읽기 회귀 안전(감사)**: 전 파일의 geometry spatial 술어를 감사한 결과 GiST를
  구동(driving)하는 모든 조회는 `deleted_at IS NULL`(직접 또는 public_features view)
  을 포함해 partial index를 쓴다. `deleted_at` 없이 geometry를 참조하는 3곳
  (curated_repo._LIST_FEATURES_SQL, ops_repo violations bbox, consistency.py CRS-drift)
  은 PK-join residual `&&` 또는 negated `ST_DWithin`+`ST_Transform`(GiST 부적격,
  설계상 full-scan ETL)이라 full index를 구동하지 않아 seq-scan 회귀 없음. `geom`은
  어떤 조회에서도 spatial 술어로 안 쓰이므로 `idx_features_geom` drop은 read 영향 0.
  EXPLAIN 회귀: 공개 bbox→`idx_features_coord_gist`, nearest-weather(coord_5179
  ST_DWithin)→`idx_features_coord_5179_gist` 선택 확인.
- **BRIN 감사(D-12-3, 추가 안 함)**: 기존 weather `brin_weather_values_valid_at`(0017)·
  `collected_at`(0043), price `observed_at`(0034), source_records imported_at/
  fetched_at/last_seen_at. weather card/history는 항상 feature-scoped라 0043 복합
  B-tree(feature_id+issued_at/valid_at)를 쓰고, cross-feature append-time 축은 이미
  BRIN 보유. 누락된 hot 시간축이 없어 speculative BRIN 추가 안 함.
- **source-record FK 지원 index(T-VN-17 이월)**: price의 `idx_price_values_source_record`
  미러링해 `idx_weather_values_source_record`(partial, `WHERE source_record_key IS
  NOT NULL`)를 CONCURRENTLY 추가 — 0060 FK의 ON DELETE SET NULL이 ~30M행 seq-scan
  하지 않게.
- 게이트: ruff(6 trees)/mypy(main)/lint-imports/redaction green. 통합 테스트 통과분:
  T-VN-18 gist/brin 5, metadata gate + upgrade 11, perf-explain + public-view 5.
  **환경 사고**: 세션 누적 testcontainer 사용으로 Windows C:가 0 bytes로 차
  Docker containerd metadata가 read-only가 됐다(write-cost 대용량 seed가 마지막
  수 GB 소모 기여). 이 시점 이후 `test_weather_repo.py` 회귀는 setup 단계 Docker
  오류로 미실행 — 단, 해당 nearest-temp 테스트는 partial `idx_features_coord_5179_gist`
  를 단언(정적 확인)해 본 변경과 호환. C: 확보 후 재실행 필요.
## 2026-07-19 (codex) — Agent A PR #753 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 PR #753을 머지 후 재검토해, `alembic check`에서 제외한
  app-owned table 8개가 구조 drift 사각지대가 되고 제외 index를 이름으로만 확인해
  UNIQUE·키·predicate 훼손을 놓치는 S2 두 건을 확인했다.
- 제외 table의 전체 column type/nullability와 핵심 constraint/index를 DB catalog로
  고정하고, 인증·운영 CHECK의 실제 거부 동작을 검증한다. 제외 index 4개는 UNIQUE,
  key expression 순서, partial predicate를 정확히 비교한다.
- 새 SQLAlchemy mapping과 임시 제외 목록이 겹치면 Alembic 시작 시 즉시 실패하게 해
  T-VN-17/38 등 후속 모델 도입 뒤 stale exclusion이 남지 않도록 했다. table/index
  공용 ledger와 대체 계약 key의 정확한 집합 일치도 테스트해 검증 없는 제외 추가를 막는다.
- `uq_curated_features_theme_feature_active`에만 metadata로 잘못 붙어 있던
  `NULLS NOT DISTINCT`를 제거했다. 두 key는 `NOT NULL`이고 migration은 plain UNIQUE라
  런타임 의미 변경 없이 실제 DDL과 맞추며, 이 index는 Alembic 일반 비교로 복귀한다.
- 같은 전문 리뷰어의 재검토 승인을 받은 뒤 변경 대상 통합 테스트 13개와 unit 1,503개,
  ruff, mypy strict, import-linter를 통과했다. 전체 integration 재실행은 Docker Desktop의
  containerd metadata filesystem이 read-only로 전환돼 중단했으며, 변경 대상 통합 테스트는
  장애 전·독립 실행에서 모두 통과했다. 원격 CI에서 전체 gate를 다시 확인한다.

## 2026-07-19 (claude, agent A1) — T-VN-19 Alembic metadata 정합 CI gate

- ADR-075 D-12-2 / §8.1: 빈 PostGIS DB에서 `alembic upgrade head && alembic check`가
  diff 0건이 되도록 metadata/env를 정합화하고 상시 CI gate를 추가했다. WSL docker
  PostGIS(testcontainers와 동일 image)에서 반복 실행하며 초기 ~100건 diff를 0건으로 닫았다.
- env.py `include_object`로 명시 제외(이름 나열, blanket 아님): PostGIS `spatial_ref_sys`,
  ORM 모델 없는 app table 8개(feature_weather_values/feature_price_values/system_log/
  api_call_log/public_api_keys/admin_auth_events/ops_live_ticket_claims/
  ops_live_topic_revisions — weather/price는 T-VN-17/38이 모델 도입 시 제거),
  alembic이 round-trip 못하는 partial/expression index 4개(features yt_channel/yt_playlist/
  dedup_refresh_keyset, source_records kma_alert_history).
- models.py 실매핑 정합(마이그레이션 아님): DB가 TEXT인데 모델이 String이던 27개 컬럼
  Text화(features/feature_versions/feature_change_requests/source_entities/source_links/
  source_records.source_entity_key/notice_lifecycle_scopes/notice_lineage_states — DB에
  varchar/text가 혼재해 flagged 컬럼만 교체), dagster_schedule_active_claims에 0054가 만든
  resolvable_after/operation_finished_at 컬럼·CHECK 2개·created_at clock_timestamp() 기본값
  보강, source_records unique명 uq_source_records로 정정, curated_themes theme_slug를 0025
  inline UNIQUE의 PG 기본명(curated_themes_theme_slug_key)으로 명시, import_jobs.queue_sequence
  의 SERIAL 위양성 server_default 제거. repo는 raw SQL, DDL은 migration 소유라 런타임 불변.
- 새 test는 전용 빈 DB를 만들어 격리 실행하고, deferrable 상호 FK(ADR-063 head-pointer)의
  위상정렬 SAWarning과 coord_5179 computed-default UserWarning(둘 다 양성, CLI check는 통과)만
  test-local filterwarnings로 허용한다. 리뷰 후 비교 제외 index 4개는
  `test_alembic_uncompared_indexes_keep_exact_semantics`가 UNIQUE·key expression·partial
  predicate를 catalog로 고정한다. curated_features 유일 index는 잘못된 metadata 옵션을
  제거해 Alembic 일반 비교 대상으로 복귀했다.
- **GENUINE 마이그레이션 필요 drift는 없었다** — 전부 모델 metadata 버그(수정) 또는 alembic
  autogenerate 위양성(제외)이었다. 비차단 후속 관찰: (a) DB에 varchar/text가 의미상 같은
  컬럼군에 혼재 — 향후 정규화 migration 후보. (b) curated_themes/source_records 제약이 naming
  convention 밖 이름(0025 inline UNIQUE·0002) — 향후 rename migration 후보.
- 검증: 로컬 WSL PostGIS upgrade+check exit 0, 새 integration test green,
  affected ORM round-trip integration 100+ green, main unit 1492 green(사전존재 Windows-only
  15건: run-admin-stack bash·import_linter cp949 — 무관), ruff/mypy --strict/lint-imports clean.

## 2026-07-19 (claude, agent A2) — T-VN-17 weather 무결성 제약 (migration 0060)

- F-7(weather/price 비대칭) 해소: ``feature_weather_values``에 price(0034) 패턴을
  미러링해 semantic UNIQUE + range/payload CHECK + source-record FK를 도입했다
  (ADR-072/075, Wave 1). ~30M행이라 rewrite/STORED 추가 없이 online DDL만 사용.
- alembic 0060(down_revision=0059): (1) DEDUP FIRST — 같은 semantic tuple 중복
  (tz 표기 차이로 다른 weather_value_key를 받은 같은 instant 등)을
  collected_at(known_at proxy) 최신 우선으로 1건만 남기고 삭제(운영자 pre-count
  SELECT 제공). (2) ``CREATE UNIQUE INDEX CONCURRENTLY``(autocommit_block, NULLS
  NOT DISTINCT) — 재실행 안전을 위해 CREATE 전에 leftover INVALID index를
  CONCURRENTLY drop. (3) range/payload CHECK와 source FK를 NOT VALID→VALIDATE로
  적용. downgrade는 제약·index를 되돌린다(삭제한 중복행은 원본 재적재로 복원).
- semantic tuple = (feature_id, provider, weather_domain, forecast_style,
  metric_key, issued_at, valid_at, observed_at) — ``WeatherValue.identity()``·
  ``make_weather_value_key`` 축과 동일(timeline_bucket 제외). 3개 nullable 시간축
  때문에 NULLS NOT DISTINCT 필요.
- writer cutover(같은 PR): ``weather_repo._INSERT_SQL``의 ON CONFLICT 대상을
  PK(weather_value_key 해시)에서 semantic tuple로 전환. 단일 정본
  ``_WEATHER_IDENTITY_COLUMNS``에서 conflict target을 만들어 DB index와 항상
  일치하게 하고, 통합 테스트가 pg_index 컬럼과 대조한다. update-wins(ADR-072).
- 테스트: 중복 흡수(update-wins)·다른 key 같은 tuple 거부·NULLS NOT DISTINCT·
  reversed range 거부·payload 비-object 거부·FK orphan 거부·ON DELETE SET NULL,
  그리고 전용 stepping engine으로 dedup keep-rule + upgrade→downgrade→upgrade
  왕복. CONCURRENTLY+autocommit_block이 asyncpg env.py에서 정상 동작 확인.
- 범위 밖(다른 lane): weather SQLAlchemy 모델링(T-VN-38 — 그 전까지 weather는
  model-less라 T-VN-19 alembic-check 제외 유지), weather batch API(T-VN-16),
  current summary(T-VN-38), BRIN/GiST(T-VN-18). source FK 지원 index(price의
  idx_price_values_source_record 등가)는 T-VN-18 소유로 남김 — source_records는
  immutable이라 삭제가 드물어 즉시 위험 낮음(리뷰 판단).
- 위생: #752가 실수로 커밋한 repo-root ``uv.lock``(origin/main 미추적, uv는
  pyproject/CI/docs 어디에도 정본으로 참조되지 않는 로컬 아티팩트)을 제거했다.
- **후속 정정(#766)**: 위 concurrent 절차는 dedup commit 뒤 writer가 semantic duplicate를
  재삽입할 수 있어 T-VN-17R의 transactional writer-lock cutover로 대체한다.

## 2026-07-19 (codex) — Agent A PR #748 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 PR #748을 최신 `integration/t-vn`에서 재검토해, 서버/OpenAPI에서
  삭제한 beach no-op query 두 개가 구현 사양과 PinVi primary consumer에 남은 S2
  clean-cut 누락을 확인했다.
- 이 저장소의 `public-views-api` query 표를 실제 route/OpenAPI와 맞췄다. PinVi의
  route·Python/TS client·vendored OpenAPI와 query-shape drift gate는 cross-repo 후속
  PR로 함께 정리한다.
- 같은 전문 리뷰어가 양 저장소 최종 diff를 승인했다. 이 문서 후속은 diff whitespace와
  prod redaction gate를 통과했고, PinVi 관련 Python 테스트 31개와 정적 gate도 통과했다.

## 2026-07-19 (codex) — Agent A PR #747 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 PR #747의 route matrix와 `/metrics` 경계를 최신
  `integration/t-vn`에서 재검토했다. 인증 우회·미분류 route·후속 PR 충돌은 없었지만,
  추적 중인 Prometheus config에 실제 token을 inline하도록 한 배포 안내(S2)와 설정이
  허용한 비ASCII token이 header 인코딩 차이로 항상 401이 되는 경계(S3)를 확인했다.
- 배포 안내를 repository 밖 secret 파일의 read-only mount +
  `authorization.credentials_file` 선행 조건으로 바꾸고, metrics token은 RFC 6750
  `b64token` ASCII 범위만 허용하도록 설정 검증과 회귀 테스트를 추가했다.
- 같은 리뷰어 재검토에서 기존 S2/S3 해소를 확인했고, 지적된 import 순서 1건은
  기계적으로 정리했다. 관련 API unit 87건과 Ruff가 통과했다.

## 2026-07-19 (claude, agent A2) — T-VN-05 공개 raw payload 경계 제거

- D-9-1/F-3(ADR-073): 공개 read에서 provider raw 경계를 제거했다. DB 컬럼·ETL은
  건드리지 않고 **공개 read projection에서만** 벗겨낸다.
- 공개 detail/batch(`FeatureDetailResponse`)에서 raw observation lineage
  (`observations`: raw_data/raw_payload_hash/source_record_key)를 제거하고,
  `detail` JSONB의 provider raw passthrough(`payload`, 예: MOIS PlaceDetail.payload의
  mng_no/status_code/detail_status_*/opn_authority_code/title/epsg5174)를
  `_public_detail`로 벗겨낸다. typed 공개-안전 필드(place_kind/phones/facility_info/
  license_date 등)는 유지.
- raw lineage를 operator 표면으로 이동: 신규 `GET /features/{id}/sources`(operator,
  현재 관측값)와 기존 observation history endpoint를 `require_admin_frontend`로
  게이팅. 두 endpoint는 공개 가시성 gate 대신 raw row 존재로 404 판정(operator는
  비공개/종료 feature도 감사). route_policy 레지스트리: history를 PUBLIC_KEYED→
  OPERATOR로 재분류, `/sources`를 OPERATOR로 신규 등록(미분류 gate green 유지).
  user OpenAPI subset(`USER_OPERATIONS`)에서 raw lineage 두 표면 제외.
- service batch: `FeatureBatchRequest`가 `extra=forbid`로 feature_ids만 받아 raw
  opt-in이 불가하고, 공유 `FeatureDetailResponse`가 이제 typed-only라 batch도
  raw 없이 고정 payload만 반환한다. (trip_card 명명/5-state 재구성은 T-VN-11.)
- 테스트: 공개 detail/batch에 raw 필드 0(raw_data/raw_payload_hash/
  source_record_key/observations/detail.payload) — MOIS place 포함; operator
  sources/history는 admin secret 설정 시 인증 없이는 403; operator는 raw를 그대로
  조회. OpenAPI 양 profile 재생성 + drift clean, admin/user TS types 재생성.
- OUT(범위 밖): 5-state batch envelope·trip_card 재구성(T-VN-11), UUID identity,
  스키마/migration, observation lineage anti-join 비용(T-VN-37). admin/operator
  payload 내용은 그대로(raw 유지).
- **T-VN-37 후보(typed 승격)**: `payload` strip은 전 kind 일괄이라 `area.payload`
  (hazard_type/domain/protection_type)와 `notice.payload`(domain) 같은 ADR-027/028
  분류 의미도 함께 사라진다 — area(hazard_zone)/notice(generic)에서 이 값은 오직
  payload에만 존재한다. 현재 공개 소비자 0(grep 확인)이라 능동적 회귀는 아니지만,
  공개 지도가 위험구역 색칠/공지 domain 필터를 필요로 하면 이 필드들을 typed
  공개 필드로 승격해야 한다(festival public_views의 typed-extraction이 선례).
  승격/strip 범위 조정은 T-VN-37(typed notice/subtype) 소유 — 지금은 하지 않는다.

## 2026-07-19 (codex) — Agent A PR #746 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 최신 `integration/t-vn` 기준으로 PR #746을 재검토해 #745의
  alias-aware notice 필터와 충돌하는 S1을 확인했다. 방어 cast를 공유 helper에 이식해
  `f`, `pf`, `count_pf`, `public_count_pf` 공개 소비자가 같은 fail-closed 경계를 쓰게 했다.
- Agent A의 동시 head 갱신 뒤 같은 리뷰어가 현재 diff를 다시 확인해, 리뷰 기록·현재 진행
  정본이 사라진 문서 회귀(S2)와 corrupted curated 단건 및 collection count가 실제로
  검증되지 않는 테스트 공백(S3)을 확인했다. 단건은 `None`, collection detail/list는 정상
  item 1건만 집계하는지 직접 단언하도록 보완했다.

## 2026-07-19 (claude, agent A1) — T-VN-07 no-op beach 옵션 삭제 + auth-event actor principal 1차

- D-9-6: `/v1/public/beaches`(목록/상세)의 `include_quality`/`include_forecast`는 값을
  받아도 항상 `latest_water_quality=null`·`upcoming_index_forecasts=[]`·`latest_weather=null`을
  반환하던 no-op 옵션이었다. route 서명·`_beach_view` 시그니처·no-op 대입을 제거하고
  `openapi.json`/`openapi.user.json`을 재생성한 뒤 `openapi-typescript@7.13.0`으로 admin
  frontend·user-client TS 타입을 재생성했다(두 파일 각각 param 4줄만 삭제, 다른 변경 0).
  응답 필드 3개는 모델 기본값으로 유지해 응답 계약을 바꾸지 않는다 — 구현 시점에 옵션과
  함께 재도입한다. FastAPI가 미지 query 파라미터를 무시하므로 옛 caller는 정상 200(no 500).
- D-2/F-4: auth-event write(`POST /v1/admin/auth-events`)의 감사 actor를
  `body.actor or context.actor` → `context.actor`로 좁혀 body-actor 위조를 차단했다.
  저장소 전체에서 `X or context.actor` 패턴은 이 한 곳뿐이라 추가 동형 사례는 없었다.
  admin feature/curated/issue/offline/dedup/enrichment의 body-actor 필드 전면 제거와
  `AdminAuthEventCreateRequest.actor` 필드 자체의 schema 제거는 T-VN-20 소관이라
  손대지 않고 필드는 유지·무시한다(`extra="forbid"`라 지금 제거하면 옛 caller가 422 —
  T-VN-20이 frontend/PinVi와 함께 조율).
- 테스트: (1) OpenAPI가 beach 옵션을 더 이상 노출하지 않고 응답 필드는 유지됨(contract),
  (2) 옛 caller의 `include_forecast=true` 전송이 정상 200 + 응답 필드 유지(기존 테스트에
  단언 추가), (3) auth-event가 body actor가 아닌 인증 principal을 저장·반환. 검증:
  public_views/auth/export_openapi/route_policy green, openapi drift(admin/user)=0,
  TS drift(admin/user)=0, ruff/mypy --strict/lint-imports/redaction clean.

## 2026-07-19 (claude, agent A1) — T-VN-02 route policy matrix + /metrics 경계 + #742

- ADR-066 결정 1: `kortravelmap.api.route_policy`에 전 HTTP/WS route를 6개 정책 중
  정확히 하나로 분류하는 명시적 registry(`ROUTE_POLICIES`, 경로→정책)와 matrix
  생성기를 구현했다. 분류는 배선에서 추론하지 않으며, 미분류 route는 `create_app`
  구성 검사(RoutePolicyError)와 CI(`test_route_policy.py` — registry↔mount 양방향
  set-equality, 죽은 registry entry도 실패)가 함께 거부한다. FastAPI 0.136+ lazy
  `_IncludedRouter`는 OpenAPI 생성기가 쓰는 공개 helper
  `fastapi.routing.iter_route_contexts`로 평탄화하고(구버전은 concrete routes
  fallback), WS의 해석 경로는 `RouteContext.path`가 아니라 `starlette_route`
  프록시로 얻는다(0.139.2에서 WS는 `path=""`인 내부 표현 실측). 0.135.3/0.139.2
  양쪽 venv에서 동일 matrix(157 rows) green.
- 정책-배선 검증: route별 관측 enforcing dependency(callable identity)로 판정하고,
  배선≠정책은 `KNOWN_WIRING_EXCEPTIONS` ledger(소유 task 명시)만 허용한다. 현재
  ledger는 전부 T-VN-03(codex b1) 소유 — 무키 legacy `/v1/curated-*` 4건(→
  public-keyed)과 무의존 `/v1/ops/{metrics,system-logs,api-call-logs,
  consistency/reports,consistency/issues,health-deep}` 6건(→ operator, PinVi
  라이브 소비라 T-VN-00 principal·caller 전환과 같은 cutover). gap이 닫히면 stale
  entry가 CI에서 실패해 ledger가 줄어들기만 한다. ops-live WS는 #725
  `authenticate_ops_live_websocket`을 enforcing dependency로 기록만 하고 재사용.
- ADR-066 결정 4: `/metrics`를 scrape identity 경계로 닫았다 —
  `KOR_TRAVEL_MAP_API_METRICS_TOKEN` 설정 시 `Authorization: Bearer` 상수시간 검증,
  production은 metrics endpoint 활성 시 token 필수(형태 기준은 service token과 동일
  `_deployable_secret_shape` — root `.env.example` CHANGE_ME가 local-dev full-stack을
  막지 않게 field-level 32자 강제는 하지 않음). compose hard-require + 배포 전제
  (Prometheus scrape_config authorization)는 CHANGELOG/deploy.md/.env.example에 명시.
- issue #742: ops pair 검증 정본을 settings production matrix로 일원화하고,
  entrypoint가 production+ops surface 활성+pair 미구성을 migration 전에 settings와
  동일 문구로 거부하게 했다(2단계 혼란 실패 제거, profile 기본값은 image와 같은
  production). settings provenance 메시지를 "must be configured together"로
  lockstep 정렬했고, 메시지 동기화는 양쪽 소스를 대조하는 unit 테스트로 상시 강제.
- 검증: api 패키지 전체 649 passed(rebase 전) + rebase(#743·#744 반영) 후 관련 5개
  파일 150 passed, `tests/unit/test_docker_dagster_runtime.py`는 신규 포함 53
  passed(사전 존재 Windows 한정 `run-admin-stack.sh` bash 실패 14건은 base에서도
  동일 재현 — 본 변경과 무관), `ruff check` clean, `mypy --strict -p
  kortravelmap.api` clean, openapi drift 없음(`/metrics`는 스키마 밖).
- 리뷰 반영(PASS-WITH-FIXES): (S2) deploy.md/CHANGELOG/integration-map/settings
  docstring을 정정 — docker-manager `prometheus.yml`에 **현재 12701 scrape job이
  없음**을 명시하고("목표"로 wording), zero-gap 순서(scrape config에 Bearer
  authorization job 신규 추가 → 그다음 token 켜고 배포; 역순은 401 gap)를 YAML
  예시와 함께 성문화. (S3.1) 인증 없는 interactive docs UI(`/docs`·`/redoc`·swagger
  oauth2-redirect)를 production에서 내리고(`docs_url`/`redoc_url`=None) `debug`로
  재분류 — D-1 public-unauthenticated를 넓히지 않는다. 기계 판독 `/openapi.json`은
  유지(ADR-031, `include_in_schema=False`라 committed openapi.json 불변, drift 없음).
  (S3.2) metrics token 검사를 UTF-8 bytes 비교로 바꿔 비-ASCII Authorization 헤더가
  500이 아닌 401 fail-closed(TypeError→500 재현 후 수정 확인). (S3.3)
  `assert_route_policy_wiring`에 ledger 경로 GET-only 강제 + 비-GET 면제 거부 가드와
  테스트 추가. (S3.4) entrypoint PROFILE을 `+x` set-vs-unset으로 판정해 set-but-empty가
  조용히 production으로 접히지 않게 함(직접 `docker run` 경로). (S3.5) callable-identity
  anti-spoof 테스트(같은 이름 impostor는 enforcement로 기록 안 됨) pin.
- 리뷰 지시대로 defer(범위 밖, 1줄 note): (a) entrypoint의 DEBUG_ROUTES_ENABLED
  ambiguous-spelling 게이트 — #742는 PROFILE/FEATURES/OPS만 정정, DEBUG flag는 후속.
  (b) 기존 auth.py의 동일 latin-1 TypeError 패턴 3곳(`_admin_proxy_secret_matches`
  L167 계열·`require_ops_operator` L308 계열·`service_token_matches` L363 계열,
  본 PR 이전 코드) — 이번 metrics 검사만 bytes 비교로 고쳤고 나머지는 별도 후속.

## 2026-07-19 (codex) — Agent A PR #743 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 PR #743 최신 head를 테스트 전에 독립 검토해 `admin_only` theme의 공개
  curated/curation 노출(S1), 비공개 연결 item의 복제 장소정보 잔존(S2), 종료·구버전 notice의
  curation 재노출(S2)을 확인했다. 공개 theme/overlay를 SQL에서 고정하고 비공개 연결 item은
  부분 NULL 처리 대신 행째 제외했으며, notice 감산 SQL을 모든 공개 소비자가 공유하게 했다.
- 같은 리뷰어가 보완 diff를 재검토해 public feature detail/batch curation의 theme visibility
  누락을 추가 차단한 뒤 최종 승인했다. 공개 query parameter 2개를 제거하고 OpenAPI/admin·user
  TypeScript 산출물을 재생성했다.
- 승인 뒤 unit/API 70건과 PostGIS 공개 경계 15건, Ruff를 통과했다. pytest 첫 실행의 WSL 3.14
  capture 임시파일 오류는 전용 `/tmp`와 capture-off 재실행으로 코드 실패가 아님을 확인했다.

## 2026-07-19 (claude, agent A2) — T-VN-06 notice timestamp 방어적 cast (+ 리뷰 S3 반영, #745 rebase)

- report §2 D-9-7(+T-VN-06 row): ``detail->>'valid_end_time'`` 직접 CAST 때문에
  오염된 notice 한 행이 ``_PUBLIC_ACTIVE_NOTICE_FILTER_SQL``을 공유하는 모든
  공개 read(bbox/search/nearby/in-area/cluster/counts/notice IDs + notice
  detail·batch 가시성)를 500으로 만들었다. Wave 0 완화로 notice 종료 감산
  SQL 한 곳(#745 rebase 후 ``_ended_notice_hidden_sql(feature_alias)`` 함수)에
  ``pg_input_is_valid``(PG16+, 배포·테스트 이미지 모두 16 고정) 가드 CASE를
  넣었다 — 파싱 불가 row는 fail-closed로 "notice 없음" 강등(노출 아님),
  JSON null/키 부재는 기존 의미(활성) 유지. 스키마 변경 0, migration 0.
- **#745 rebase(공개 curation 경계 후속)**: #745가 종료 notice 감산을
  ``_ended_notice_hidden_sql(feature_alias)`` 함수로 중앙화하고 curation_repo·
  curated_repo(``/v1/curated-features``·``/v1/curations``·``/v1/curations/
  collections/{id}``)까지 정본으로 확산시켰다 — 단, **naked** cast로. 내 가드를
  그 함수 본문에 이식(``f`` → ``{feature_alias}``)해 그 6개 신규 표면까지 한
  곳으로 동시에 방어했다(충돌 리뷰가 지적한 S1 blast-radius를 닫음). 가드 존재
  단위 단언과 통합 테스트를 새 함수/표면 기준으로 갱신했다.
- 리뷰 S3 반영: (1) ADR-073 인용 정정 — ADR-073 결정 목록에 D-9-7이 없어
  코드 주석·CHANGELOG를 "report §2 D-9-7 (+ T-VN-06 row)"로 교체(ADR-073
  본문은 미변경 — 설계 문서 변경은 범위 밖). (2) admin naked cast fold-in —
  ``admin_feature_repo`` notice 목록(요청 경로, include_ended=false면 운영자가
  바로 그 오염 row를 찾는 화면)에도 동일 가드 5줄 적용. (3) 가드 존재 단위
  단언 — 필터를 합성한 10개 공개 read 상수(bbox lite/geom, cluster×3, search×2,
  nearby×2, in-area, counts, notice IDs) 각각이 ``pg_input_is_valid``를 포함하는지
  단위 테스트로 고정(미래 per-surface fork가 가드를 빠뜨리면 fast-fail).
- 통합 테스트: 오염 4종(빈 문자열/garbage/달력 불가값/불가능 timezone) ×
  bbox(경량/geometry)/search/notice IDs/단건 가시성 + admin 목록(기본/감사) —
  수정 전 SQL로는 ``InvalidDatetimeFormatError`` 재현을 확인했다. notice
  lifecycle·public view matrix·perf EXPLAIN 회귀 green.
- 범위 외로 남긴 cast: ``_PURGE_EXPIRED_NOTICES_SQL``(ETL maintenance)·notice
  reconcile CTE(``feature_repo.py`` ~2741-2769, Dagster write 경로) — 요청 경로가
  아니라 T-VN-37 소유. lineage anti-join 상시 비용도 T-VN-37(불변).
- **텔레메트리 공백(T-VN-37 선행 후보)**: 이번 완화로 오염된 **active** notice는
  텔레메트리 0으로 공개·admin 표면에서 조용히 사라진다(fail-closed 제외라
  안전하지만 관측 불가). 게다가 그 오염 row는 reconcile CTE에서 여전히 직접
  CAST를 만나 Dagster job이 그 자리에서 깨진다(self-heal 불가 — 오염을 스스로
  치우지 못한다). typed 재설계 전이라도 값싼 주기적 ops count 쿼리
  (예: ``kind='notice' AND deleted_at IS NULL AND detail ? 'valid_end_time' AND
  NOT pg_input_is_valid(detail->>'valid_end_time','timestamptz')`` 행 수)를
  T-VN-37 선행 후보로 남긴다 — 이 task 범위에서는 코드 추가 없음.

## 2026-07-19 (claude, agent A2) — T-VN-04 공개 predicate view 단일화 + 적대 리뷰 반영

- ADR-067 Wave 0: alembic 0059가 `feature.public_features` VIEW(`status='active' AND
  deleted_at IS NULL`, DDL은 CREATE VIEW만, partial index는 T-VN-34)를 만들고 bbox/cluster/
  search/nearby/in-area/detail/batch/category counts/notice ids/weather anchor/public views/
  curation·curated 공개 read를 전부 그 projection으로 수렴했다. F-1 양방향(provider-retired
  은닉 vs admin-inactive/draft/broken 노출)을 endpoint별 술어 재구현 삭제로 동시 해소.
- 적대 리뷰 BLOCK 반영: (S1) 무인증 `GET /v1/curations/collections/{id}`에서 비공개 연결
  feature의 id/이름/좌표/주소와 복제 장소정보가 새던 구멍을 공개 SQL의 item 행 제외로
  봉인하고 8-state matrix 통합 테스트를 추가했다. (S2) 특보 이력
  `/v1/features/weather/alerts`는 base features 대신
  공개 projection에 LEFT JOIN — alert row는 생존, 비공개 anchor의 feature 필드는 NULL,
  상수화된 `feature_status` 필드는 응답에서 제거(OpenAPI/TS 재생성). (S2) admin weather/price
  panel은 404를 오류 Alert가 아니라 "공개 카드 없음" 빈 상태로 처리(전용 admin 카드 표면은
  issue #741). (S2) batch 의미 변화(admin-inactive/draft → `missing`, resolver T-VN-11)를
  `docs/integration-map.md` §3.2에 성문화 — PinVi trip view는 그 사이 false-broken 표시 가능.
- batch `missing` 균일화, weather/price 카드 404 가드, categories `active_only` 파라미터 제거,
  admin map viewport(`GET /v1/features`) active-only 전환이 소비자 가시 변경이다(CHANGELOG).
- nearby `status` 파라미터는 동작 유지 + "공개 projection과 교집합, active 외 값은 빈 결과"
  OpenAPI 설명만 추가(정리는 T-VN-11/34). notice lineage 경쟁자 `deleted_at IS NULL` 판정은
  T-VN-06/37 소관으로 보류.

## 2026-07-19 (claude) — T-VN-01 production fail-closed 전환

- `feat/t-vn-01-fail-closed`(target: `integration/t-vn`)에서 ADR-066 D-1의 T-VN-01을 구현했다.
  `ApiSettings.profile`(`KOR_TRAVEL_MAP_API_PROFILE`, production|local-dev, 코드 기본 local-dev)을
  추가하고 production은 기동 시점 fail-closed 검증을 수행한다: admin proxy secret(앞뒤 공백 없는
  32자 이상), ops surface 활성 시 read/cancel token 쌍, features surface 활성 시
  `public_api_key_required=true`와 service token(앞뒤 공백 없는 32자 이상), 인증 없는 `/debug`
  라우터 비활성. 위반은 하나의 ValidationError에 함께 나열된다(기존 ops pair/shape 검증은 정의
  순서상 먼저 단독 실패).
- secret 미설정 local-dev fallback(admin actor `local-dev` pass-through)은 non-production 전용으로
  격리했고, auth dependency도 production+secret 없음 비정상 상태를 403/None으로 방어적으로 닫는다.
  flag 해석(`None`→features 추종)은 settings의 resolved 속성으로 단일화해 mount와 검증이 같은
  해석을 공유한다.
- Docker는 image ENV와 compose 기본값으로 production을 주입하고, compose가 `/debug` off·
  `public_api_key_required=true`를 컨테이너 기본으로 강제한다(environment가 package .env보다
  우선). service token은 admin secret과 같은 `${...:?}` hard-require로 전달한다. **배포 전제**:
  n150은 다음 배포에서 root `.env`에 admin secret·ops token들과 다른 32자 이상
  `KOR_TRAVEL_MAP_API_SERVICE_TOKEN`을 추가해야 한다. legacy `/v1/curated-*` keyless read는
  T-VN-03 범위로 남긴다(F-3 잔여).
- 적대 리뷰 PASS-WITH-FIXES 반영: features surface의 service token 필수화(공백/32자 미만 형태
  거부 포함), root/package `.env.example`의 compose override 우선순위 문서화, wording(앞뒤 공백),
  hermetic env 테스트 fixture. startup 거부/통과 matrix + dependency 격리 테스트를 추가했고
  uvicorn import 경로로 거부·기동 양방향을 실검증했다.
- PR #740 CI에서 app 조립 테스트 1건이 3.11/3.12/3.13 전부 실패(로컬 green): FastAPI 0.136+가
  `include_router`를 lazy `_IncludedRouter`로 담아 `app.routes` 순회로는 sub-router `path`가 안
  보이는 내부 표현 변화였다(로컬은 0.135.3, CI는 0.139.2 — CI 버전 재현 venv로 확정). 테스트를
  공개 API인 `application.openapi()["paths"]` 기반으로 고쳐 두 버전 모두 green. 코드 결함 아님.

## 2026-07-19 (codex) — Agent A PR #744 적대적 심층 리뷰 후속

- 전문 리뷰어 1명이 닫혀서 `main`에 병합된 PR #744를 재검토해, 비활성 manual link를
  resolver가 재발견하면 `active=true, relation='manual'`로 부활시켜 이후 빈 snapshot도
  제거하지 못하는 S3를 확인했다.
- direct upsert는 caller relation을 적용하고 resolver snapshot upsert만 기존 row가
  `active AND relation='manual'`일 때 provenance를 보존하도록 SQL을 분리했다.
  deactivate→resolver 재분류→빈 snapshot 비활성화 회귀를 추가했다.
- 같은 리뷰어가 잠금 순서와 provenance 전이를 재검토해 승인했다. 관련 unit/PostGIS
  테스트 30개, Ruff, strict mypy 115개 소스, import 계약 4개와 prod redaction이 통과했다.

## 2026-07-19 (claude) — #733~#737 병합 PR 심층 적대 리뷰 후속 수정

- **S2-1**: `upsert_poi_cache_target`의 moved/reject 판정을 unlocked pre-read에서
  `_LOCK_ACTIVE_TARGET_SQL` `FOR UPDATE` lock-first로 옮겼다(DELETE 경로와 동일 패턴).
  create 경합의 패자는 `DO NOTHING` insert 뒤 lock 재획득으로 stable row에서 재판정한다 —
  동시 PUT(reject)의 조용한 좌표 덮어쓰기와 stale `moved=False` link 잔존을 닫는다.
  재-lock이 다시 비는 3자 경합(winner commit 직후 동시 soft-delete)은 create→재-lock
  유한 반복(상한 3, 소진 시 명확한 실패)으로 닫아 `DO UPDATE` tail이 lock 보유 없이는
  실행되지 않는다(3자 통합 재현은 결정적 관측점이 없어 unit 계약으로 고정).
  receipt/lock_version은 trigger 소유 그대로다. 두-세션 blocking 통합 회귀
  (`test_concurrent_put_reject_race_yields_single_winner_and_conflict`)를 추가했다.
- **S2-2**: ADR-074 결정 1의 ledger key를 D-10-1 3요소
  `(principal namespace, operation, Idempotency-Key)`로 복원하고(postgres-schema.md
  domain-ledger 행 동일), 결정 2에 D-10-3 "If-Match 누락은 428"을 명시했다.
- **S3 docs**: ADR-071 cross-ref ADR-045→ADR-046, ADR-070 route geometry
  `MultiLineString`(D-6-2) + 3종 geometry CHECK 명명, ADR-066 결정 3에 D-1-3 무키
  legacy `/v1/curated-*` public-keyed 배선(T-VN-03), ADR-069 결정 2에 D-5-4
  `source_role` 일원화·`is_primary_source` 제거, ADR-073 결정 2에 D-9-1 service batch
  기본 `trip_card` projection, ADR-075에 0058 NOT VALID 예외 부합 기록,
  performance.md에 admin POI mutation×장기 ETL `data_integrity_violations` writer의
  `dataset_projection` revision-row 직렬화 경합 note, integration-map.md에 #733 cancel
  결박의 canonical hyphenated UUID·ASGI root_path fail-closed caveat.
- **S3 code**: snapshot sync `_DEACTIVATE_LINKS_FOR_TARGETS_SQL`에 `relation <> 'manual'`
  guard(#699 패턴, 운영자 manual link 보존 — 단건 delete/move 경로는 기존대로 전체
  비활성화) + unit/integration 회귀. link upsert 두 경로의 `ON CONFLICT DO UPDATE`도
  `CASE` guard로 manual→resolver 재분류를 차단해 다음 sync가 manual link를
  비활성화하지 못하게 했다. playwright.live.config.ts `E2E_LIVE_WORKERS`를
  1 이상 정수로 검증(garbage는 redacted 오류). C7 runner의 causal POI grep을 한글
  제목에서 안정 `@c7-causal` tag로 교체하고 runner 정적 계약을 갱신했다. OpenAPI의
  canonical ops service 대안을 `OpsToken`+`OpsScope` AND 결합으로 선언해 런타임의
  scope 필수(누락 422) 판정과 일치시키고 openapi.json을 재수출했다.
- **명시적 보류**: #740×#733 ops-pair validation 조정과 production/both-explicit-empty
  entrypoint 테스트는 미병합 T-VN-01 profile 개념에 의존해 보류. BLOCKED sentinel의
  preflight 이전 생성은 PR #735 본문·journal("state root→lock→BLOCKED→residue 순서를
  정적 계약으로 고정")과 runner 계약 테스트의 순서 고정이 의도를 명시하므로 유지한다.

## 2026-07-18 (codex) — C7 n150 runner Python preflight 보강

- read-only n150 점검에서 SSH·Docker·Node·Playwright runner는 사용 가능하고 C7 residual state도
  없지만 host `python` 명령과 고정 attestation 파일은 아직 없음을 확인했다.
- host-side fsync/lock/attestation/state/UI env 검증을 `python3`로 고정하고 실행 전 command 존재를
  fail-fast한다. Dagster container 내부 Python 호출은 변경하지 않는다.
- attestation은 tracked 문서에 실제 host/origin/hash를 기록하지 않고 배포 직전 local-only root atomic
  write로 provision한다. 기능 보정은 단일 적대적 리뷰 승인 전 테스트·lint를 실행하지 않는다.
- 리뷰가 요구한 정적 계약을 보강해 host 6곳 exact count, container 1곳, pipe alias 0건과
  `python3` preflight→state root→lock→BLOCKED 순서를 고정했다. 재승인 뒤 `bash -n`, Ruff와 targeted
  pytest `16 passed`를 확인했다. 첫 pytest는 NTFS capture 임시파일 오류였고 `/tmp` 재실행은 green이다.

## 2026-07-18 (codex) — vNext 재설계 ADR·architecture·tasks 정본 전개

- PR #732 보고서 §0, D-1~D-12, §3~§8을 ADR-066~075와 PostgreSQL/REST/data model/
  performance/integration/deploy/runbook 정본에 전개했다. UUID identity, DB-owned provider dataset,
  직교 publication, typed subtype, field override, weather bitemporal, 쓰기 안전성과 write-fence를
  독립 결정과 rollback 단위로 고정했다.
- `T-ADM-C6c`/`C7` 다음의 T-VN Wave 0~3과 hardening을 모두 PR 단위 open task로 기록했다.
  `T-VN-00`은 C6c 별칭이라 중복 checkbox를 만들지 않았고 문서 전개 완료 항목도 백로그에 남기지
  않았다. 코드 PR 리뷰는 최신 정책대로 테스트 전 적대적 리뷰어 1명으로 정리했다.
- source 보고서에는 PR #736(`docs/vnext-review-propagation`)을 §7 정본 전개 PR로 역기입했다.

## 2026-07-18 (codex) — T-ADM-C7 prod live E2E 4차 적대 리뷰 반영

- KMA target 소유권 barrier는 `external_system`별 active 목록을 500건 cursor 두 페이지까지
  완주하고 최대 501건 전체 key/UUID/ETag 집합을 journal과 exact 비교한다. 빈 continuation,
  cursor 반복, page/집합 상한 초과와 scope 누출은 모두 mutation 전에 차단한다.
- preview의 `matched_scope.provider_datasets`는 빈 배열이나 부가 pair를 허용하지 않고 KMA
  provider/dataset/effective sync scope 한 쌍과 비음수 정수 feature count를 요구한다.
- 실행과 event history는 각 응답의 total-order identity tuple을 중복 없이 엄격한 내림차순으로
  검증한다. 다음 페이지는 첫 페이지와 서로소이고 경계 순서를 보존해야 하며, DataTable의
  `data-row-identity` 전체 배열이 현재 응답 tuple 배열과 순서까지 exact 일치해야 한다.
- standalone POI의 첫 create는 실제 `route.fetch()`로 서버 commit 응답과 causal receipt를 확보한
  뒤 브라우저 응답만 결정적으로 끊는다. exact GET 재탐색과 commit 증거 일치 후에만 성공하며,
  handler settlement 뒤 route를 제거한다. fresh 리뷰 2인 승인 전 규율에 따라 테스트·lint·build·
  외부 호출은 실행하지 않고 정적 계약과 `git diff --check`만 확인한다.

## 2026-07-18 (codex) — T-ADM-C7 prod live E2E 3차 적대 리뷰 반영

- 이전 KMA journal은 그 payload만으로 restored residue를 먼저 판정한 뒤 누적 이력에 합친다. 현재
  scenario의 target/request/idempotency key와 진행된 status는 이전 snapshot으로 절대 덮어쓰지 않아,
  새 scenario의 pending 상태를 과거 scenario residue로 오판하지 않는다.
- create뿐 아니라 실제 run-now/provider dispatch 직전에도 서버 active target 전체 key/UUID/ETag를
  owned journal과 exact 비교한다. 같은 자연키 재생성은 삭제된 이전 UUID와 다른 새 UUID, version 1
  strong ETag, 필수 history를 증명하며 runner도 current/history UUID 교차 중복을 거부한다.
- 고정 `orchestrator.lock`은 Python guard가 `O_NOFOLLOW|O_CREAT`로 열고 regular root-owned `0600`을
  `fstat`한 뒤 non-blocking `flock`한다. 기존 symlink/FIFO/device와 truncate redirection은 허용하지
  않으며 runner의 state root→lock→BLOCKED→residue 순서를 정적 계약으로 고정했다.
- standalone POI journal에도 최종 파일 fsync를 추가했다. causal PUT 응답 유실은 intended body exact
  GET, 404일 때만 동일 PUT 1회 재생, 최종 exact body/UUID/ETag/version 재검증으로 처리한다. receipt나
  identity가 불확실하면 BLOCKED하며 cleanup도 intended body 없이 identity만 보고 삭제하지 않는다.
- KMA cursor의 `base_datetime`은 선택값이 아니라 달력상 유효한 비어 있지 않은 `YYYYMMDDHHmm` 필수값으로
  강화했다. 새 리뷰 2인 승인 전 규율에 따라 테스트·lint·build·외부 호출 없이 `git diff --check`만
  수행한다.

## 2026-07-18 (codex) — T-ADM-C7 prod live E2E 2차 적대 리뷰 반영

- 같은 자연키를 삭제 후 재생성하면 active 소유 객체를 새 UUID·strong ETag·version으로 교체하고,
  과거 객체는 별도 `target_history`에 보존한다. PUT 응답 유실은 intended body journal을 기준으로
  exact GET 재탐색 후 부재일 때 한 번 같은 PUT을 재생하며, 끝내 identity를 증명하지 못하면 cleanup을
  `restored=false`로 닫는다.
- 모든 KMA create 직전에 external-system의 서버 active target 전체 집합을 owned journal과 비교한다.
  preview plan과 terminal의 eligible/skipped/executed provider scope 전체를 KMA-only로 검증하고,
  `membership_fingerprint`는 소문자 SHA-256, `base_datetime`은 실제 달력에 존재하는 `YYYYMMDDHHmm`만
  허용한다.
- KMA/sensor/schedule/runner 상태와 `BLOCKED.json`은 임시 파일 fsync→rename→최종 파일·부모 디렉터리
  fsync 순서로 기록한다. runner 상태·lock·BLOCKED는 `/var/lib/kor-travel-map/c7-prod-live-e2e`의
  root-owned `0700` 경로로 고정하고 `XDG_STATE_HOME` 우회는 거부한다.
- 모든 `route.fetch()` interception은 in-flight handler 정산 뒤 `unroute`하며 이를 실제 파일 순서로
  고정하는 정적 회귀 계약을 추가했다. 사용자 규율에 따라 신규 리뷰 2인 승인 전 테스트·lint·build·
  외부 호출은 실행하지 않았고 `git diff --check`만 허용했다.

## 2026-07-18 (codex) — T-ADM-C7 prod live E2E 적대 리뷰 보강

- C7C POI causal live spec를 최종 runner에 포함하고 create/update/delete마다 mutation 직전 frame
  cursor 이후 같은 원본 socket의 `update.data.live_revision >= receipt`만 인정하도록 보강했다.
  socket close/reconnect와 snapshot은 causal 성공을 만들 수 없다.
- KMA/standalone POI PUT은 자연키·intended body를 응답 전 durable journal에 기록하고, 응답 뒤
  UUID·strong ETag·lock version을 보강한다. 모든 cleanup은 exact GET ETag 기반 `If-Match`만 쓰며
  `412`와 소유 version drift를 fail-closed한다.
- KMA request 직전 external-system active target의 전체 key/UUID/ETag 집합, 실행·event continuation의
  provider/dataset/scope/cursor request와 response tuple을 exact 검증한다. RFC7807
  `application/problem+json`도 최종 shell browser probe가 JSON으로 파싱한다.
- 고정 root-owned attestation 파일로 실제 machine-id/hostname/UI·API-WS·Dagster origin을 검증하고,
  로그인 POST `200 + Set-Cookie`와 실행 중 UI container의 non-empty password hash를 preflight에
  추가했다. 실제 host·URL·hash·비밀 값은 코드·로그·문서에 기록하지 않는다.
- 본 변경은 두 fresh 적대 리뷰 승인 전이므로 Playwright·lint·build를 실행하지 않았다. reviewer
  승인 뒤 정적/로컬 gate와 최종 n150 prod runner를 순서대로 수행한다.

## 2026-07-18 (codex) — T-ADM-C7C causal receipt·조건부 삭제 로컬 gate 완료

- POI target mutation transaction에서 trigger 이후 `ops.ops_live_topic_revisions`의
  `dataset_projection` 값을 필수 receipt로 읽고, Alembic 0058의 server-owned BIGINT version과
  UUID로 body/header strong ETag를 만든다.
- DELETE repository는 active natural key `FOR UPDATE`와 READ COMMITTED 재조회로 concurrent
  recreate와 실제 부재를 구분한다. UUID+version 일치 시에만 UPDATE하며 link upsert는 active parent
  `FOR KEY SHARE`로 직렬화한다.
- API의 RFC7807 `428`/`422`/`412`/`404`, OpenAPI header/response 선언, admin UI exact
  `If-Match`, BFF request/response header allowlist를 연결했다.
- 일반 unit/integration와 live write E2E에 strict ETag, stale PUT/recreate, 실패 revision 불변,
  link/delete 2-session race, 같은 기존 socket update의 `live_revision >= receipt`를 추가했다.
- admin OpenAPI와 TypeScript 타입을 재생성했고 admin-only 계약 변경으로 user OpenAPI는 불변이다.
- 재리뷰에서 multi-target sync의 교차 parent 잠금과 stale UI selection을 보강했다. repository가 모든
  active parent를 UUID 순서로 먼저 잠근 뒤 link를 교체하고, UI는 target UUID에서 refetch row를
  파생한다. live E2E도 create/update/delete별 새 frame cursor와 최신 server `entity_tag`를 사용한다.
- Reviewer B 잔여 지적에 따라 `If-Match` raw header line을 strict parser보다 먼저 계수한다. 누락은
  `428`, 물리적 중복은 순서와 무관하게 `422`로 닫고 ASGI raw tuple 양방향 회귀 테스트로 고정했다.
- 최종 제품 diff는 두 독립 적대 리뷰어가 DB locking·HTTP precondition·causal socket·UI stale
  selection 관점에서 차단 finding 없음으로 승인했다. 승인 뒤 root unit 1,435건, API 520건,
  실제 PostgreSQL migration/up-down·2-session 경쟁 묶음 8건, frontend unit 212건과 mocked POI
  E2E 10건을 통과했다. Ruff, strict mypy 115+52파일, import 계약 4/4, admin/user OpenAPI·생성
  타입 drift, frontend type-check·lint(오류 0)와 31-route production build도 green이다.
- C6c Map PR #733의 merge commit `a5af45f2` 위에 rebase한 뒤 admin/user OpenAPI와 생성 타입을
  정본에서 다시 생성했다. `T-ADM-C7C`는 완료 이력으로 옮기고 최종 C7 n150 live gate만 남겼다.

## 2026-07-18 (codex) — T-ADM-C7C causal receipt·조건부 삭제 설계 확정

- C7 테스트 전 적대 리뷰에서 `updated_at` 이후의 임의 `dataset_projection` revision을 해당
  mutation 원인으로 인정하는 거짓 양성과, target exact GET 뒤 자연키 DELETE가 concurrent
  delete/recreate된 새 UUID를 지울 수 있는 TOCTOU를 확인했다.
- 이 문서 선행 결론의 exact equality와 UUID-only version/schema 불필요 판단은 적대 리뷰에서
  각각 coalesced topic update와 same-row concurrent PUT을 처리하지 못하는 것으로 확인됐다.
  최종 계약은 ADR-065의 `live_revision >= receipt`와 Alembic 0058 UUID+BIGINT version으로 대체한다.

## 2026-07-18 (codex, agent B) — T-ADM-C6c map service principal 적대 리뷰 반영

- canonical `/v1/ops/datasets*`·`/v1/ops/pipeline*`만 기존 trusted frontend BFF 또는 별도
  `OpsToken` principal이 통과하도록 인증 dependency를 분리했다. read secret은 `GET`의
  `ops:read`, cancel secret은 exact import-job cancel POST의 `ops:cancel`에 결박했다. 나머지
  mutation은 BFF 전용이며 token·scope 오류를 typed RFC7807 `401/403/422`로 구분했다.
- service actor를 설정 불가능한 코드 상수 `service:pinvi`로 고정했다. 요청 actor header와 제거된
  actor env를 거부하고 `/v1/admin/*`, legacy ops, frontend BFF의 권한은 넓히지 않았다. OpenAPI는
  GET/exact cancel만 AdminBFF 또는 OpsToken이고 다른 mutation은 AdminBFF만 표시한다.
- `OPS_PRINCIPAL_REQUIRED=true`는 non-empty pair를 강제한다. local false는 두 값 모두 absent 또는
  모두 explicit empty만 허용하며 partial/missing+empty/모든 whitespace/read=cancel/admin·service
  secret 재사용을 거부한다. API-only ops env가 Dagster webserver/daemon에 유입되면 image
  entrypoint가 값의 유무와 무관하게 시작을 차단한다.
- 위 경계를 고정하는 dependency/OpenAPI/launcher/compose test code를 보강했다. 독립 적대 리뷰
  2건을 반영한 뒤 root unit 1,463건과 API 563건, targeted C6c 306건, ruff, strict mypy
  190파일, import 계약 4/4, admin/user OpenAPI·admin generated type drift, frontend type-check·
  unit 210건·lint(오류 0, 기존 경고 6)·production build를 통과했다.
- PR #733의 Python 3.11~3.13 CI에서 FastAPI/Starlette 조합에 따라 `route.path`가 router prefix를
  보존하지 않아 exact cancel principal이 거짓 거부되는 차이를 확인했다. 권한 판정을 framework
  내부 route template 대신 ASGI decoded path의 anchored import-job UUID cancel 경로에 결박하고,
  상대 route template과 실제 full path를 분리한 회귀 테스트를 추가했다. 이 보정 diff도 두 독립
  적대 리뷰어가 fail-open 없음으로 승인했으며 집중 API 217건과 API 전체 563건을 통과했다.
- 첫 재실행의 PostGIS integration은 principal 활성 시 무헤더 read를 구 계약 `403`으로 기대한 기존
  assertion 1건 때문에 실패했다. 제품 코드는 바꾸지 않고 새 typed 계약 `401 OPS_TOKEN_REQUIRED`를
  함께 단언하도록 고쳤으며 해당 실제 PostgreSQL REST projection test를 다시 통과했다.

## 2026-07-18 (codex) — PR #708 정본 최신 코드 2차 재검증 (#730 병합)

- PR #708은 이미 병합된 상태여서 최신 KTM `main@13eb8d40`과 PinVi
  `origin/main@48085afb`를 기준으로 후속 검토했다. C5~C7B의 route·migration·auth·actor·CAS·
  exact-scope 구현을 코드와 테스트에서 재대조해 해소된 판정을 제거하거나 남은 범위로 좁혔다.
- feature-update와 schedule의 0054 domain ledger, #725 ops-live ticket, #727 policy CAS를
  범용 미구현으로 오판하지 않도록 목표 구조와 실행 계획을 보정했다. 잔여 무인증 ops/debug read,
  body actor, Feature revision은 별도 위험으로 유지했다.
- PR #724가 legacy ops를 삭제했지만 PinVi admin client·proxy·test가 삭제 경로를 계속 호출하는
  cross-repo 계약 단절을 새 P0로 확정했다. `T-ADM-C6c`를 C7 선행 task로 만들고, canonical
  caller 전환·명시적 service/operator principal·양 저장소 contract smoke를 완료 조건으로 고정했다.
- 위 문서 보강은 PR #730의 8개 CI 게이트가 모두 통과한 뒤 merge commit `d0609226`으로
  `main`에 반영됐다. 후속 구현 범위를 넓히지 않고 #730 관련 문서 이력만 마감했다.

## 2026-07-18 (codex) — 완료 admin ops 이슈 4건 종결

- 이슈 본문과 최신 `main`, 병합 PR, 적대 리뷰·CI 증거를 다시 대조해 #682, #686, #718,
  #720에 완료 근거를 코멘트하고 닫았다. #680은 기존 CLOSED 상태를 재확인했다.
- #684·#712·#719는 본문의 n150/live 수용조건이 남았고 #694는 C7 UI 의미 단언이 남아
  열린 상태를 유지한다. `T-ADM-C7`의 최종 이슈 종결 대상도 이 네 건으로 줄였다.

## 2026-07-18 (codex, agent B) — C7B-UI 적대 리뷰·전체 frontend gate 완료

- `/ops/datasets`가 exact scope의 active/terminal 실행과 nested run/event history,
  canonical continuation URL을 직접 소비하게 했다. invalid deep link는 다른 행으로 폴백하지
  않고, 정책 draft는 같은 dataset의 scope 전환과 지연 응답 중에도 보존한다.
- `/ops/pipeline`의 provider/dataset/scope를 URL controlled state로 통일했다. 불완전 tuple과
  상위 filter 변경은 종속 filter와 cursor를 함께 제거하고 browser Back/Forward를 그대로
  추종한다. dataset-wide request는 명시적 scope 입력을 차단해 서버 정규화와 일치시켰다.
- 독립 적대 리뷰 2인이 P0~P3 잔여 0건으로 승인했다. Vitest 26 files·210 tests,
  앱·E2E type-check, lint 오류 0건, `git diff --check`, package-lock 무변경과 31-route
  production build를 확인했다. 실제 Playwright와 #712/#719 종결은 최종 C7 n150 gate에 남겼다.

## 2026-07-18 (codex, agent A) — C7B-API 적대 리뷰·전체 backend gate 완료

- datasets canonical root projection을 scope별 활성/종료 두 그룹으로 나눠 더 최신 terminal이
  아직 살아 있는 실행을 가리거나 active가 마지막 완료 결과를 지우지 않게 했다. grid/detail은
  같은 DB snapshot을 사용하고 실행·event 첫 페이지를 독립
  `{items,next_cursor,canonical_url}`로 반환한다.
- Alembic 0057은 visible event의 provider/dataset을 owning job에서 복구하고 canonical direct
  update event에만 typed `sync_scope`를 backfill한다. trigger·constraint로 owner identity를
  불변화하고 exact-scope partial index에서 조건→keyset→LIMIT 순서를 고정했다. run/event cursor에는
  전체 filter fingerprint를 묶어 다른 filter 재사용과 non-canonical scope를 typed `422`로 닫았다.
- 첫 natural-plan gate에서 dataset-only no-cursor가 시간 index로 4,001행을 버리는 실제 plan과
  Bitmap Heap→Bitmap Index child를 놓치는 assertion을 분리 진단했다. dataset key는 provider
  namespace라는 clean contract에 맞춰 provider 없는 event filter를 REST/repository에서 거부하고
  dead `idx_import_job_events_dataset_time`을 제거했으며, EXPLAIN assertion은 전체 plan tree의
  index와 relation touch/removed bound를 각각 검증하도록 고쳤다.
- 두 독립 DB/API 적대 리뷰어가 migration up/down, lock·DDL 순서, 0052 역사 계약, 최신 ORM
  metadata, production caller와 EXPLAIN 정당성을 검토해 P0/P1/P2/P3 잔여 0건으로 승인했다.
  승인 뒤 migration 0057 3건, ops 8건, pipeline 23건, jobs 14건, dataset status 2건, API
  projection 1건, feature executor 21건, C7B unit metadata/repository 9건을 순차 재실행해
  81/81 green을 확인했다. root unit/lint 1,430건, API 504건, Ruff, strict mypy 167개 소스,
  frontend unit 210건·type-check·lint, admin/user OpenAPI·생성 타입 drift도 모두 green이다.
- `T-ADM-C7B-API`를 완료 이력으로 옮겼다. 다음은 최신 main 위 C7B-UI 소비를 완결하고 마지막
  C7 n150 파괴적 live E2E에서 #712/#719를 종결하는 것이다.

## 2026-07-18 (codex, agent A) — AUD-718 적대 리뷰·전체 로컬 gate 완료

- DB/API와 frontend 적대 리뷰어가 실제 row-lock 경쟁, BIGINT 최댓값 소진, source 불변과
  RFC7807 schema, 탭 수명·browser Back focus·지연 응답 세대·scope cache 경합을 재검토했다.
  최종 제품 SHA `b7b600447368d8ed79bc1a8b56772af881104bf3`의 판정은 S1/S2/S3 0건이다.
- root unit 1,411건, API 489건, 실제 PostGIS migration/schema 14건·CAS 저장소/API 23건·집중
  10건과 독립 row-lock 경쟁 3회를 통과했다. Ruff, strict mypy 115+52파일, import 계약 4/4도
  green이다.
- 같은 제품 SHA에서 frontend Vitest 212건, type-check, lint 오류 0건, OpenAPI/admin 생성 타입
  drift와 31-route production build가 통과했다. local Playwright는 실행하지 않았으며 issue #718은
  최종 C7 n150 live 증거 뒤 닫는다.

## 2026-07-17 (codex, agent A) — AUD-718 revision CAS 구현 스냅샷

- 1차 적대 리뷰에서 단순 순차 stale 테스트, BIGINT overflow, `source_kind` 재적용,
  non-problem OpenAPI ref 보존, tab unmount·popstate focus·충돌 중 반복 저장 경계를 지적했다.
  실제 PostgreSQL row lock에서 ASGI 요청이 대기하는 commit/rollback/create 경쟁, max-1→max와
  typed 소진, 생성 뒤 source 불변, RFC required-field schema gate로 보강했다.
- UI는 policy panel을 keep-mounted하고 충돌/지연 서버값을 명시 조정하기 전 저장을 이중 차단한다.
  concurrent create의 서버 `source_kind`, 2^53 초과 revision 문자열, browser Back focus 복귀를
  mock live 계약에 추가했다. 같은 2인 재리뷰 전이므로 테스트·lint·typecheck·build는 미실행이다.
- Alembic 0056으로 `ops.provider_refresh_policies.revision` 양수 BIGINT 정본을 추가하고,
  신규 생성은 `expected_revision=null`, 기존 갱신은 동일 revision을 조건으로 원자적 `+1`하는
  create-only/update-only 저장 계약으로 바꿨다. 불일치는 현재 record/revision을 포함한 typed
  RFC7807 `409`로 반환한다.
- admin 정책 편집기는 작성 시작 revision과 최신 관측 revision을 분리한다. background refetch나
  `409`가 와도 로컬 초안을 보존하고, 운영자가 명시적으로 선택할 때 3-way 조정하거나 서버 값으로
  되돌린다. BIGINT revision은 OpenAPI/TypeScript 경계에서 정규화된 10진 문자열로 표현한다.
- migration backfill/default/check/downgrade, 두 세션 stale write, typed `409`, UI 충돌·조정
  회귀를 추가했다. 적대 리뷰 2인에게 넘기기 위한 구현 스냅샷이며 지시에 따라 리뷰 전 테스트·lint·
  build는 아직 실행하지 않았다.

## 2026-07-18 (codex, agent A) — AUD-686 적대 리뷰·전체 로컬 gate 완료

- 두 독립 리뷰어가 KMA empty preflight, cancellation/cleanup, terminal transaction과
  exact-scope event query를 제품 SHA `c07259fb`에서 검토해 S1/S2/S3 0건으로 승인했다.
  뒤이은 변경은 Dagster test import sentinel 격리와 generated type 설명 동기화뿐이다.
- 최종 SHA에서 root unit 1,413건, API 485건, Dagster 475건(1 skip), 실제 PostGIS 집중
  6건과 frontend Vitest 185건을 통과했다. Ruff, strict mypy 115+52+23파일, import 계약
  4/4, OpenAPI admin/user·generated type drift, frontend type-check·lint(오류 0, 기존 경고 6),
  31-route production build도 모두 green이다.
- `T-ADM-AUD-686`을 완료 이력으로 옮겼다. PR은 #686을 `Refs`로 연결하되 이슈는 닫지 않고,
  최종 C7 n150 파괴적 live E2E 증거 뒤 #684/#712 등 운영 종결 이슈와 함께 닫는다.

## 2026-07-17 (codex, agent A) — AUD-686 2차 적대 리뷰 지적 반영

- 정규 schedule resource가 client를 asset preflight 전에 생성하던 경로를
  `kma_weather_client_factory`로 교체했다. 세 grid asset의 actual materialization에서 empty와
  동일 cursor는 credential 검증·`kma` import·constructor 호출이 모두 0이며, client는 통과한
  task가 동기 생성·소유·close한다.
- cleanup은 `BaseException` primary identity를 보존한다. cancellation/provider failure 뒤 close와
  진단 logger까지 실패해도 원래 오류를 유지하고, primary가 없을 때만 close 오류를 전파한다.
- dataset event는 canonical event/job/request를 JOIN해 typed job scope를 cursor/ORDER/LIMIT 전에
  제한한다. scope A cursor와 더 최신인 scope B 22건 격리, DTO/URL/다음 cursor, pipeline events
  filter와 UI history link를 추가했다. 0057 migration은 후속 C7B-API 소유로 남겼다.
- empty terminal 전이의 event writer fault는 request/job/event transaction을 rollback하고 기존
  provider state를 byte-for-byte 보존한다. 같은 active request 경쟁 loser와 terminal replay도
  event를 늘리지 않으며 generic/GridLimit/다른 provider는 empty code를 만들지 않는다.
- 이 snapshot에서는 사용자 지시에 따라 테스트·lint·build를 실행하지 않았다. 동일 2인 적대
  재리뷰 승인 뒤에만 검증한다.

## 2026-07-17 (codex, agent B) — C7A 적대 리뷰·전체 로컬 gate 완료

- backend/DB/security 리뷰어와 frontend 상태 모델 리뷰어가 테스트 전에 same-origin ticket,
  nonce claim/lease, topic revision, reconnect·standby·polling 계약을 검토했다. Compose env 중복,
  유효한 공개 secret 예시, 긴 WebSocket close reason, pipeline projection 구독 누락, polling 의미와
  문서·runtime test drift를 반영하고 제품 변경 S1/S2/S3 0건 승인을 받았다.
- 정확한 제품 SHA `c49829f0`에서 root unit 1,411건, API 484건, 실제 PostGIS 전체
  migration/schema 14건과 C7A 집중 9건, frontend Vitest 185건을 통과했다. Ruff, strict mypy
  115+52파일, import 계약 4/4, OpenAPI/admin/user generated type drift, base·host Compose rendering,
  frontend type-check·lint와 Next.js production build도 green이다.
- `tasks.md`의 완료 항목을 아카이브했다. 실제 Chrome close code·재연결은 local에서 실행하지
  않고 모든 후속 C7 변경을 병합한 뒤 n150 prod 파괴적 live E2E로 종결한다.

## 2026-07-17 (codex, agent B) — C7A 선행 적대 리뷰 보강

- dataset grid/detail 합성값 중 기존 `provider_sync` clock이 포괄하지 못한 integrity issue와
  POI cache target을 `dataset_projection` topic으로 분리했다. 두 원본 table의 statement
  trigger는 원본 transaction과 함께 revision을 올려 rollback과 동시 late commit을 보존한다.
- malformed/비단조 frame 뒤 서버가 보내지 않을 same-socket 재구독을 기다리던 상태 머신을
  socket 즉시 폐기·backoff 재연결·새 exact `replace` 방식으로 바꿨다. 인증 만료 UI는
  `로그인 필요`로 표시하고 공유 secret 32자 하한을 launcher/container 기동 경계에 추가했다.
- DB rollback/source mapping/topic row lock, 다른 tab/process projection invalidation, 실제
  `socket.send` 재구독 계약 테스트를 보강했다. C6B 병합 정본 위에서 migration을
  `0055`/`down_revision=0054`로 확정한 뒤 최종 2인 적대 리뷰와 전체 gate를 수행한다.

## 2026-07-17 (codex, agent A) — C6b 최종 리뷰·로컬 gate·PR #724 병합 완료

- C7B-720 병합 commit 위로 최종 rebase하고 admin/user OpenAPI와 generated type을 다시
  대조했다. 두 적대 리뷰어가 bridge/host/external overlay, BFF 인증, credential 격리,
  legacy 부재, canonical status URL과 C7B 필터 보존을 최종 S1/S2/S3 0건으로 승인했다.
- 테스트에서 드러난 live envelope exact assertion과 direct service test의 canonical status
  prefix를 두 리뷰어 재승인 뒤 보강했다. root unit 1,410, API 450, Dagster 457(1 skip),
  실제 PostGIS 92, frontend 142건 및 전체 정적·생성·build gate가 green이다.
- local Playwright는 실행하지 않았다. live UI·파괴적 시나리오는 C7에서 n150 prod에 배포한
  뒤 file-by-file 저부하 실행과 상태 복원으로 종결한다.
- 보안 감사와 전체 CI green 뒤 PR #724를 squash merge했다.

## 2026-07-17 (codex, agent A) — C6b backend/API legacy clean-cut 구현

- Dagster 9, provider ops 2, refresh policy 3, import job/event 5, feature update request 6,
  debug ETL 3개 등 legacy OpenAPI operation 28개와 전용 router를 삭제했다. canonical
  `/ops/pipeline/*`·`/ops/datasets/*`, 관측 read, `/ops/live` WS와 public provider read는
  유지했다.
- public provider 계약은 운영 정책·request 결합이 없는 소형 router로 옮겼다. raw HTTP live
  ETL loader와 adapter tests를 제거하고 catalog preview를 fixture/none으로 닫았으며 REST API
  settings·Docker·load-env에서 provider credential 복제 경로도 제거했다.
- legacy 부재 28개와 canonical/public 존치를 기계적으로 고정하는 테스트를 추가하고 public
  provider parser/필터/cursor 비노출 회귀를 보존했다. migration은 만들지 않았다. 외부 적대
  리뷰 2인 전이므로 테스트·push·PR은 실행하지 않았고 C5/C6A merge 뒤 rebase가 필요하다.
- 기존 Codex codegraph index로 제거 대표 route의 영향도를 확인했다. legacy import-job route는
  route 자체 외 caller가 없었고 public last-sync는 route 단독 영향이라 소형 router로 동일 계약을
  옮겼다. canonical service caller는 별도 pipeline/datasets router에 남는다.
- 적대 리뷰 1차는 production S1/S2 결함 0건으로 판정했다. S3로 확인된 CORS preflight,
  canonical feature-update idempotency/strict DTO matrix, public provider empty-list 회귀를
  canonical 테스트에 복원했다. 현행 architecture/runbook 문서의 legacy path도 두 그룹으로
  정리했다.
- 적대 리뷰 2차는 API container가 root `.env`와 main provider secret을 받는 S2 경계를
  발견했다. API를 package-scoped `.env`로 격리하고 data.go/OpiNet/KREX/MOIS 설정은 Dagster
  service에만 남겼다. 사용되지 않는 Dagster NUX mutation/schema를 삭제하고 canonical
  request의 필수 UUID `Idempotency-Key`, 재생/active 재사용 분리, 충돌 계약을 문서에
  명시했다.
- 반영 snapshot 재리뷰는 actor-scoped ledger를 전역 key처럼 설명한 문서 오류와 API 전용
  env 부재 시 인증 기본값 기동 가능성을 S2로 확인했다. 문서는 actor별 독립 namespace로
  정정하고 API env를 Compose 필수 입력으로 바꿨다. root 예시의 중복 API runtime 설정도
  제거하고 provider secret 격리 회귀 테스트를 추가했다. 후속 재검토의 운영 CORS 문서와
  오래된 전역 key/provider 주입 주석도 정정하고, root/Compose/load-env의 허용 API 설정을
  allowlist로 고정했다. 추가 재검토에서 발견한 local `admin:stack` 우회도 process별
  `env -i` allowlist와 필수 scoped API env로 닫았다. API cwd 변경에 따른 backup root 분기와
  env inline comment/proxy-secret 공백도 root 절대경로·strict parser로 보강했다. 재리뷰와
  테스트는 아직 진행 전이다. 독립 runtime 재검토의 구 API provider key, MOIS/file-registry/
  offline prefix, Compose frontend auth/BFF, direct uvicorn 문서 지적도 fail-closed runtime과
  현행 기동 문서에 반영했다. BFF shared secret은 root 단일 이름을 API/frontend가 직접
  읽도록 바꾸고 package env의 구 API 전용 중복 secret을 금지했으며, dead fixture 목록 helper와
  no-auth/legacy endpoint 설명도 제거했다. 생성 OpenAPI와 admin type은 C6A/UI 최종 rebase 뒤
  반드시 갱신하고 drift green을 확인하기 전에는 C6b를 병합하지 않는다.
## 2026-07-17 (agent B) — C6b 구 UI clean-cut 리뷰 반영

- 구 `/ops/import-jobs*`, `/ops/providers`, `/admin/features/update-requests*`, `/admin/dagster`,
  `/etl` route와 전용 hook/mock E2E를 redirect 없이 삭제했다. 홈은 canonical pipeline root와
  overview 집계를 쓰고, 운영 로그는 system/API 감사 로그만 남겨 작업 event를 pipeline으로
  일원화했다. frontend README의 route/API inventory도 같은 현행 표면으로 갱신했다.
- 외부 적대 리뷰 B의 지적을 반영해 홈 Dagster 외부 링크 E2E를 배포별 환경 URL과 독립적인
  절대 URL·새 탭 계약으로 바꿨다. offline validation/load와 POI target upsert/delete가
  pipeline executions/overview 및 ops dataset grid/detail을 무효화하는 hook 단위 계약을
  추가했고 POI mutation의 누락된 pipeline 무효화도 연결했다. 테스트는 최종 통합 리뷰 뒤로
  보류했다.

## 2026-07-17 (codex, agent B) — C7B-720 datasets 이슈 의미 통일·PR #723 병합 완료

- dataset/provider issue count를 합산하는 순수 projection을 두고 필터·정렬·행 badge가 같은
  의미를 사용하게 했다. grid 요약은 dataset을 `(provider,dataset)`, provider를 provider별로
  한 번만 세어 scope 반복 행과 문자열 delimiter 충돌을 피한다.
- provider-only, dataset-only, both, neither와 scope 중복을 unit/mock E2E 계약에 추가했다.
  두 독립 적대 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했고 unit 5건, type-check, lint,
  production build를 통과했다. Playwright 실제 실행은 C7 n150 live wave에 합친다.
- 보안 감사와 전체 CI green 뒤 PR #723을 squash merge했다. issue #720 종결은 최종 n150
  live 증거 뒤 수행한다.

## 2026-07-17 (codex, agent B) — C6a 통합 화면 링크 재배선 완료

- `EntityLink`의 import job·update request·load batch를 `/ops/pipeline`으로, provider를
  `/ops/datasets`의 `provider/dataset/sync_scope` URL 계약으로 전환하고 단위 계약을 추가했다.
  홈·Feature 지도·큐레이션·운영 로그·구 갱신 요청 전환 화면의 직접 링크도 같은 두 화면만
  가리키게 해 구 상세 페이지 제거 전에 진입점을 먼저 끊었다.
- ops-live topic은 legacy import-job/provider cache 대신 pipeline overview/execution/event와
  dataset grid/detail을 무효화한다. import job 응답의 `status_url`과 self/events/cancel/parent,
  Dagster run HATEOAS도 canonical pipeline API로 바꿨고 load batch는 통합 UI filter로 연결했다.
- load batch와 parent UUID deep link가 전체 pipeline graph를 먼저 읽지 않도록 두 partial
  index에서 member를 seed한 뒤 같은 root component를 확장하고, 실제 Postgres EXPLAIN gate로
  access path를 고정했다. live E2E 시나리오 카탈로그에도 두 통합 화면의 read/write·반영
  계약을 추가했다.
- 두 독립 적대 리뷰어가 canonical identity, root membership, HATEOAS, 실시간 invalidation을
  최종 SHA에서 재검토해 S1/S2/S3 0건으로 승인했다. root unit 18건, API 140건, 실제 Postgres
  통합 22건, frontend unit 27건, Ruff·strict mypy·import 계약·type-check·lint·production
  build를 통과했다.

## 2026-07-17 (codex) — admin 감사 후속 PR·migration single-head 계획

- issue #720, #718, #686, #712, #719의 잔여를 C7B-720, AUD-718, AUD-686,
  C7B-API, C7B-UI 다섯 PR로 나눴다. frontend-only 필터 보강, 갱신 정책 revision
  CAS, KMA zero-target fail-closed, active/exact-scope API, UI 소비가 서로 다른 리뷰·병합
  경계를 갖도록 해 완료 조건을 섞지 않는다.
- C6a 뒤 C6b·C7A·C7B-720, C7A 뒤 AUD-718·AUD-686을 병렬 wave로 두고 API→UI→C7
  n150 순으로 결선한다. Alembic은 C7A 0055, AUD-718 0056, C7B-API 0057만 순차
  소유해 병렬 migration head를 만들지 않는다. 각 wave는 시작·PR 직전·병합 직후 rebase한다.
- 문서 branch는 C5 최신 `2a3e12bc`에서 만들었다. C5 병합 전에는 push/PR을 금지하고,
  병합 뒤 문서-only PR로 올려 별도 적대 재리뷰 없이 먼저 병합한다.

## 2026-07-17 (codex) — C5 pipeline 통합·append-only 조작 원장

- 기존 PR #691을 C3e/C45X/C4 정본 위에서 재작성해 `/ops/pipeline`의 상태·타임라인·Dagster
  run·event·schedule·feature update 조작을 완결했다. root와 descendant job, 요청 상태와
  projected job을 분리하고 provider/dataset pair·URL·자동 갱신·degraded 의미를 통일했다.
- 0054 migration에 feature request idempotency와 schedule audit/claim/resolution ledger를
  append-only로 추가했다. DB clock lease, advisory lock, 120초 timeout과 mutation guard로
  동시 명령·응답 유실·불확실 결과를 fail-closed하며, UI는 frozen command/request를 session에
  보존해 reload 후 같은 identity로 복구한다.
- 적대 리뷰에서 sensor fail-open, target/priority/dry-run 상태 drift, active claim 재실행,
  결과 불확실성 및 React session 복원 문제를 보강했다. 의미 있는 최종 변경은 두 리뷰어 모두
  S1/S2/S3 0건으로 승인했다. #693·#716의 재현 조건도 회귀 테스트에 포함했다.

## 2026-07-17 (codex) — C4R datasets 통합·scope UI 폐루프

- Claude Code PR #698의 `/ops/datasets` 구현을 C45X typed scope 정본에 맞춰 재작성했다.
  grid/detail/pipeline history는 `(provider,dataset_key,sync_scope)`를 끝까지 보존하고,
  dataset-wide 기본 state와 orphan/stale external scope, active request 재사용과 409 충돌을
  조작 capability에 연결했다. 정책·preview·refresh now·Feature/issue 링크를 한 drawer에 모았다.
- 적대 리뷰에서 exact history의 SQL pre-limit 필터, dataset-wide scope 해석, URL canonicalization,
  draft 보존, stale scope fail-closed, focus 복귀 경쟁을 보강했다. focus E2E 계측 과정에서 이전
  production build를 재사용한 테스트 오류를 분리했고, 최신 build에서는 native History API와
  stable cell DOM으로 X/Escape/fallback 초점이 모두 유지됐다. 최종 두 리뷰 판정은 S1/S2/S3 0건이다.
- unit 1,398, API 534, 관련 PostGIS/FastAPI 통합 28, frontend Vitest 96, mocked Playwright 47와
  production build를 통과했다. Ruff·strict mypy·import 계약·OpenAPI/admin/user 생성 drift도
  green이다. 다음은 #698 rebase·보안 감사·CI·병합이며 #684/#686/#712 운영 종결은 C7 n150에 남긴다.

## 2026-07-16 (codex) — C45X typed scope·active idempotency 완결

- Claude Code PR #701을 0052 typed identity 정본 위에서 재작성했다. 0053 migration은 direct
  request job의 effective scope/dispatch intent를 열로 추가하고 active partial unique index,
  request↔job identity trigger, POI/external-system 112자와 locale 독립 Unicode trim CHECK를
  설치한다. legacy direct KMA grid는 `target_grids`, 나머지는 `dataset_wide`로 clean-cut한다.
- API는 requested/effective scope를 분리하고 같은 active plan을 200으로 재사용하며, run-now는
  canonical request/job identity를 유지한다. cancellation-requested/terminal은 typed 409로
  거절한다. KMA runner는 typed scope 누락을 fail-close하고 exact target membership fingerprint,
  cap 초과 전량 실패, scope별 durable failure를 적용한다. datasets projection은 scope별
  first-run/stale/orphan/latest/recent를 완결했다.
- 두 적대 리뷰에서 발견한 running+cancellation 200, request JSON/default KMA fallback,
  PostgreSQL locale별 NBSP 허용을 수정했다. 서비스 실제 unique 충돌은 독립 migration DB와
  2-party barrier로 검증했다. 테스트 과정에서 0052 migration 전용 DB가 현재 0053 repository를
  호출하던 세대 혼용은 0052 physical invariant 검사로 바꿨으며 구 schema 호환 코드는 넣지 않았다.
- API 530, Dagster 444(+1 skip), unit 1,396, 관련 PostGIS/migration, frontend Vitest 82와
  C45X Playwright 27, production build를 통과했다. Ruff/mypy/import-linter/OpenAPI/type drift도
  green이다. 외부 geo live 5건의 HTTP 400과 C4R/C6 이전 legacy mocked selector 실패는 별도
  후속 경계로 기록했다. 다음은 #701 rebase·보안 감사·CI·병합 후 #698 C4R 개선이다.

## 2026-07-16 (codex) — C3e-I2 n150 prod 일방향 전환·live UI 종결

- 배포 전 pg_dump와 SHA-256을 기록하고 maintenance drain 뒤 0051/0052를 적용했다. 취소된
  Dagster run에 연결된 legacy active request 1건은 감사 row를 삭제하지 않고 request/job을
  `cancelled`로 명시 정리해 migration preflight를 통과시켰다. 0048 재수렴 변경 0, 0051 예상 밖
  exact untyped 0, request validation/identity/quarantine 불일치 0, event clock singleton과
  constraint/trigger/index를 readback했다.
- Dagster webserver와 daemon을 각각 새 이미지로 재빌드하고 sensor 10개를 RUNNING으로 복원했다.
  reconciliation cursor는 maintenance anchor 5160에서 5175로 전진했으며 최근 5개 tick 모두
  `dagster_panel_only=0`, `database_observation_errors=0`이다. schedule snapshot도 34 RUNNING·3
  STOPPED로 정확히 복원했다.
- admin manual KMA, 자연 schedule KREX, feature update KMA, standalone MOIS import 네 실행이
  terminal로 끝나고 datasets/pipeline 상세의 `execution/root(kind,id)`가 일치했다. 공식
  Playwright 1.60.0·worker 1로 prod provider consistency 112건, Dagster 4건, update request 8건,
  offline upload 6건, import action 3건, home dashboard 5건을 통과했다(전제 미충족 2건 skip).
  로그인 POST/Set-Cookie와 오답 401도 반복 확인했다.
- 최종 DB/Dagster active run 0과 서비스 상태를 확인한 뒤 상세 증거를 이슈 #679에 남기고 닫았다.
  `T-ADM-C3e-I2`를 완료 이력으로 옮겼으며 다음 작업은 C45X #701과 C4R #698/#712의 적대적
  리뷰·0052 정본 보강이다.

## 2026-07-16 (codex) — C3e-I1 B2→B3 실제 PostGIS 교차 회귀

- production 코드를 바꾸지 않고 실제 migration 0001→0052가 적용된 PostGIS에서 B2 public
  wrapper 결과를 B3 terminal record가 닫는 경계를 통합 테스트 2건으로 고정했다. 단일 provider
  성공은 root/member 완료와 engine 시각·수동 trigger를, MCST 부분 실패는 13개 exact pair의
  identity·job·완료 시각과 redacted attempt event 보존을 검증한다.
- 1차 적대 리뷰의 명시적 manual seam, event identity, MCST 전체 pair freeze, 실패 cleanup 지적을
  반영했다. 보강 후 두 리뷰어의 최종 판정은 각각 S1/S2/S3 0건이다.
- focused 32건, live 제외 전체 1,902건(5 deselected), Ruff, strict mypy 136개 소스, import 계약
  4/4를 통과했다. raw 전체 실행은 외부 `kor-travel-geo` reverse endpoint의 HTTP 400 때문에
  live 5건만 실패했고 191건 통과 시점에 중단했으므로 green 결과로 기록하지 않는다.
- 다음 단계 `T-ADM-C3e-I2`는 n150 maintenance drain·0051/0052 migration과 0048 수렴,
  8개 sensor/cursor readback, 일정/수동/갱신/import 4종 동일-root 증거를 완료한 뒤 이슈 #679를
  닫는다.

## 2026-07-16 (agent A) — C3e-B2 provider guard·public wrapper tracking 완결

- B1 canonical registry를 모든 live provider resource와 public asset/KMA wrapper에 연결했다.
  authoritative Dagster run record의 job·selection·config·identity/version·trigger를 provider I/O
  전에 exact match로 검증하고 resource 초기화 뒤에도 마지막 ensure를 반복해 취소 marker와
  runtime drift를 fail-closed한다.
- wrapper가 raw 성공 뒤 자기 exact pair만 완료하도록 했고, MCST는 nullable async callback으로
  앞선 pair 성공을 보존한다. direct `FeatureUpdateAssetRunner`는 tracking 0을 유지한다. KNPS의
  비기본 point/geometry 설정은 provider fetcher와 asset resource가 같은 `model_copy` snapshot을
  사용하도록 고쳤다.
- 두 적대 리뷰어가 timestamp timezone, 빈 resolved selection, retry outcome 어휘, KNPS 실제
  `Definitions` 구성 등을 점검했고 최종 판정은 각각 S1/S2/S3 0건이다. focused 260건(1 skip),
  실제 PostGIS canonical operation 30건, Dagster 전체 428건(1 skip), main unit 1,366건과 Ruff,
  strict mypy 136개 소스, import 계약 4/4를 통과했다.
- 완료 task는 `docs/tasks-done.md`로 이동했다. 다음 단계는 PR CI·승인·병합 뒤 C3e-I에서
  B2→B3 실제 terminal DB 연쇄와 일정·수동·갱신·import 교차 회귀를 검증하고 #679를 닫는 것이다.
  n150/prod 검증도 C3e-I/C7 전까지 완료로 간주하지 않는다.

## 2026-07-16 (agent B) — C3e-B3 run sensor·양방향 reconcile 완결

- 수정 전 `reconcile_dagster_feature_run`의 codegraph 영향과 실제 caller를 확인하고, C3e-B1
  registry를 compile target으로 삼았다. DB schema 추가보다 기존 canonical operation과 sensor
  cursor의 책임 분리가 단순하고 우월하다고 판단해 migration은 추가하지 않았다.
- 7개 active/terminal run-status sensor와 30초 periodic reconcile sensor를 기본 RUNNING으로
  등록했다. 등록 job은 registry의 job·asset selection·run config·identity/version/trigger를
  검증하고 비등록 run은 panel-only로 둔다. active 상태는 root/child를 ensure하고 terminal은
  direct cancel·pre-resource 실패·partial success를 원자 reconcile한다.
- 두 적대 리뷰어가 발견한 trigger 불일치 active 고착, terminal 전 cursor 선반영, 동일 시각의
  무한 replay, 실제 DB periodic 증거 부재, 예외 비밀 노출, 삭제된 anchor와 자동 latest cutover,
  timestamp 조건 때문에 낮은 unsettled ID를 건너뛰는 문제를 모두 보강했다. 최종 cursor는
  insertion ID page의 연속 settled prefix만 commit 뒤 전진하고 DB keyset은 끝에서 wrap한다.
  anchor 삭제·변조와 비어 있지 않은 storage의 초기 무cursor는 fail-closed하며 운영 복구 절차를
  C3e 정본 문서에 기록했다. 두 리뷰어 최종 판정은 S1/S2/S3 0건이다.
- focused 101건, 실제 migration/PostGIS 27건, Dagster 전체 342건(1 skip), main unit 1,366건을
  통과했다. Python 3.14 import 위치·import 정렬·타입 주석 같은 기계적 수정 뒤 focused 52건도
  재통과했고 Ruff, strict mypy 135개 소스, import 계약 4/4를 확인했다. pytest capture의 NTFS
  임시파일 오류는 테스트 0건임을 확인한 뒤 `-s`로 우회했다.
- 완료 task는 `docs/tasks-done.md`로 이동했다. 다음 단계는 B3 PR CI·병합과 B2 완료 뒤
  C3e-I 교차 회귀다.

## 2026-07-16 (agent B) — C3e-B1 operation registry 구현 준비

- 수정 전에 worktree 전용 codegraph를 초기화했다. `FeatureLoadScheduleSpec`의 직접 caller는
  `_datagokr_file_data_schedule_specs`, `_feature_load_run_tags`의 caller는
  `_coalescing_execution_fn`이며, `schedules.py` 변경 영향 파일은 자체와
  `test_definitions.py`로 확인했다. request trigger tag 정본 이동 영향은
  `feature_update_request_failure_sensor`, `_tags_for_request`, `_failure_message`,
  `test_sensors.py`로 확인했다. 적대 리뷰 보강 전 `run_schedule_now` caller와 service file
  impact는 Dagster router, ops pipeline command, schedule override integration까지 확인했고,
  `ops_dataset_schedule.py` impact는 dataset service/router와 두 API 회귀 파일까지 확인했다.
- 33개 schedule job을 canonical provider 상수 기반 immutable registry로 옮겼다. 구성은
  static singleton 26개, 고정 fileData singleton 4개, KNPS runtime singleton 2개, MCST
  13-pair 1개이며 가능한 exact pair는 53개다. 기존 provider alias 11건, KNPS placeholder,
  MCST pseudo dataset은 identity에서 제거했다.
- registry version과 canonical redacted identity tag를 분리했다. job definition에는 identity만,
  schedule launch에는 `trigger_kind=schedule`만 추가해 UI/CLI manual 실행의 system/schedule
  오분류를 없앴다. 등록 job의 selection/config/version/tag drift는 typed conflict로 막고,
  비등록 user-code job만 panel-only로 둔다.
- 적대 리뷰 2인의 S1/S2를 반영해 registry를 main provider 계층의 공용 canonical manifest로
  이동하고 manifest 전체의 SHA-256 digest를 `v1-<12자리>` version에 결합했다. API의 admin
  schedule 수동 실행도 이 manifest가 만든 KNPS snapshot과 fileData 4종의 두 resource config,
  `manual` identity tag를 실제 GraphQL launch에 전달한다. datasets schedule projection은
  `pipelineName`과 identity job의 일치까지 검증한 뒤 MCST 13 pair를 모두 펼친다. scalar pair
  fallback은 제거했다. MCST 13-pair JSON tag 크기는 현재 비차단 S3로 두되 canonical byte
  parse와 manifest digest/version 검증 없이는 소비하지 않는다.
- coalescing은 `NOT_STARTED`/`MANAGED`를 포함하고 job/version/identity 전체가 같은 run만 막는다.
  배포 시 구 alias pair tag만 가진 active run은 새 coalescing 정본과 일치하지 않으므로, schedule
  활성화 전에 기존 run이 자연 종료됐는지 확인하고 남은 run은 운영 절차에 따라 취소한다.
- KNPS는 전체 settings를 import 시 검증하지 않는 두 필드 전용 settings로 공식 env prefix와
  `.env`를 읽고, launch 값을 run config에 복사한다. 비기본 point/geometry로 실제 provider
  fetcher resource와 asset dataset resource를 초기화해 양쪽이 같은 snapshot을 소비함을
  회귀로 고정했다. `FeatureUpdateAssetRunner` direct raw 경로의 동일 오염 수정은 B2에 인계한다.
- 전체 schedule/asset과 MCST 13종, KNPS 10개 runtime 선택지, fileData 두 config 및 admin
  Run-now 4종, immutable/version/selection/tag drift, trigger 우선순위/manual fallback,
  arbitrary panel-only 회귀를 작성했다. API package에서 `catalog_refreshable_entries`와 main
  registry의 exact equality를 검증해 Dagster test의 sibling API 역의존은 제거했다.
- B1은 manifest compile target과 schedule/admin/projection launch consumer까지만 완결한다.
  provider I/O 전 guard/public wrapper는 B2, run-status/reconcile caller는 B3에서 이 strict parser를
  연결한다. `FeatureUpdateAssetRunner`의 비기본 KNPS direct raw fetcher 오염 수정도 B2 범위다.
- 최종 적대 리뷰 2인은 B1 경계에서 S1/S2 0건으로 승인했다. main unit 1,366건,
  focused 159건, API 전체 513건, Dagster 전체 308건(1 skip), Ruff, strict mypy와 import 계약
  4/4를 통과했고 task를 완료 이력으로 아카이브했다. 첫 pytest capture 임시 파일 오류는
  테스트 0건 실행 전 환경 문제였으며 capture를 끈 동일 명령으로 재실행해 전부 통과했다.
## 2026-07-16 (agent A) — C3e-C REST 교차 통합 회귀·slash identity 보강

- 제품 수정 전 전용 worktree codegraph를 신규 동기화했다(785 files, 19,093 nodes,
  60,659 edges). `get_dataset_detail` route/function 영향은 2개, `load_dataset_detail`은
  5개, `run_dataset_fixture_preview`는 5개, `upsert_dataset_refresh_policy`는 10개,
  `OpsDatasetGridRow`는 6개, `OpsDatasetPreviewData`는 5개 symbol이다. 실제 frontend
  호출자는 아직 없고 생성된 admin OpenAPI type만 소비 경계로 확인됐다.
- 후속 적대 리뷰에서 provider와 dataset identity가 `/`를 허용하지만 동적 path segment로는
  표현할 수 없는 계약 결함을 확인했다. detail/preview/refresh-policy를 각각 고정 path와
  `provider`/`dataset_key` query 복합키로 원자 전환하고 구 동적 route는 삭제했다. grid
  `detail_url`, preview 응답의 `dataset_key`, admin OpenAPI/type, 설정·계약 문서도 같은
  clean-cut 경계로 맞췄다. 현재 branch에는 실제 C4 frontend 호출자가 없어 별도 caller 변경은 없다.
- 최종 type 재리뷰에서 수동 patch가 `detail_url`을 `OpsDatasetGridRow`가 아니라
  `OpsDatasetDetailData`에 넣은 생성 drift를 확인했다. canonical `openapi.json`에서
  `openapi-typescript 7.13.0`을 frontend workdir 기준으로 다시 실행해 grid row에만 필드를
  생성했다. OpenAPI 구조 회귀는 grid의 required `detail_url`과 detail의 필드 부재를 함께
  단언하고, 기존 `gen:types:check`가 이 spec↔type drift를 검출하는 단일 gate로 남는다.
- 실제 migrated PostgreSQL에 별도 session으로
  seed를 commit한 뒤 각 FastAPI 요청도 새 `AsyncSession`을 사용한다. `ASGITransport` 호출은
  datasets grid/detail과 pipeline executions router·service·repository를 모두 통과하며,
  seed 호출 자체부터 `try/finally`로 보호한다. append-only 행은 integration 관례의 별도
  `TRUNCATE ... CASCADE` transaction으로 정리한다.
- 같은 exact provider/dataset에 update request 1개와 manual Dagster feature root 11개를 넣고,
  동률 `created_at`과 10개 page 경계를 만든다. provider만 같은 member와 dataset만 같은 member를
  한 root에 둔 최신 cross-product decoy도 추가해 exact-pair AND를 검증한다. feature oracle은
  호출 입력과 고정 lifecycle 계약을 사용하고 DB 생성 root/member UUID만 mutation 반환값에서
  취한다. root/member 비중복, status/raw Dagster/engine 시각/projected job, request/job 접힘과
  detail cursor를 이용한 pipeline 2페이지 무누락 순서를 고정한다.
- 실제 proxy secret/actor 인증 성공과 무인증 403, history URL query round-trip, 현실적인 tagged
  Dagster schedule 응답도 포함한다. provider와 dataset 양쪽에 `/`·예약문자·한글을 포함한 orphan
  identity를 고정 detail path의 query로 조회하고 상대 history URL query가 원본 복합키로
  복원되는지도 확인한다.
- 세 구 동적 detail/preview/policy URL은 인증 ASGI에서 모두 404임을 고정한다. preview는 slash와
  예약문자가 있는 pair가 정적 catalog/fixture에 없으므로 catalog authorization과 fixture 실행
  경계만 명시 주입하고 실제 인증·query parsing·response schema를 통과한다. provider 실행이나
  fixture registry까지 실제라고 과장하지 않는다. refresh-policy는 catalog authorization만 주입하고
  실제 service/repository/DB transaction으로 upsert한 뒤 별도 session의 SQL로 exact identity와
  저장값을 독립 확인한다. cleanup은 `ops.provider_refresh_policies`도 포함한다.
  외부 호출은 schedule GraphQL만 `MockTransport`로 격리한다.
- `TRUNCATE` 격리는 현재 disposable testcontainer DB와 순차 integration 실행 전제다. 동일 DB를
  공유하는 병렬 실행을 도입할 때는 test별 DB 격리 또는 행 단위 정리 전략으로 바꿔야 한다.
  최종 적대 리뷰 2인은 S1/S2 0건으로 승인했다. API 전체 503건, router focused 13건,
  실제 migration·PostgreSQL/FastAPI 통합 1건, Ruff, strict mypy, admin/user OpenAPI drift와
  admin generated type drift, frontend type-check와 lint(오류 0, 기존 warning 2)를 통과했다.
  `T-ADM-C3e-C`는 완료 이력으로 아카이브했다.
- B1 병합 뒤 PR CI에서 구 scalar schedule mock이 strict canonical parser에 거부되는 통합
  회귀를 확인했다. mock을 실제 MOIS job/schedule 이름, `pipelineName`, registry가 생성한
  identity/version/schedule trigger/timezone tag로 교체했다. 추가 적대 리뷰 2인은 S1/S2/S3
  0건으로 승인했고, WSL capture 임시파일 오류로 0건 실행된 첫 시도와 분리해 `-s` 재실행한
  실제 migration·PostgreSQL/FastAPI 통합 1건과 Ruff를 통과했다.

## 2026-07-16 (codex) — C3e-B 복구 감사·PR 단위 재분할

- PR #705 병합과 main CI green을 확인한 뒤 Claude Code의 C3e-B branch/worktree를 reflog,
  stash, remote PR/branch와 filesystem blob으로 감사했다. 고유 C3e-B 변경은 없었고 의미 있는
  고아 worktree 파일은 이미 push된 C4R/C45X commit과 동일했다.
- 구현 결합도를 줄이기 위해 C3e-B를 B1(registry/run identity), B2(guard/wrapper/MCST),
  B3(active·terminal sensor/reconcile) 세 PR로 분리했다. B1과 C3e-C를 먼저 병렬로 진행하고
  B1 뒤 B2/B3를 병렬 진행한다.
- C3e-C의 제품 코드는 A2에서 이미 공용 projection·REST DTO·OpenAPI로 완결돼 있었다. 별도
  production 구현을 만들지 않고 실제 PostgreSQL과 FastAPI를 관통해 datasets grid/detail과
  pipeline timeline의 root/pair/status/timestamp가 같은지 검증하는 교차 통합 PR로 축소했다.
- 이 변경은 문서-only이므로 사용자 지시에 따라 추가 적대 리뷰 없이 rebase·CI green 후
  병합한다. 코드·DB·테스트 의미 변경에는 기존 적대 리뷰 2인 gate를 유지한다.

## 2026-07-16 (agent A) — C3e-A2 구현·로컬 gate 완료(PR 전)

- lifecycle 이중 정본을 제거해 request 테이블에는 immutable 입력/감사, `matched_scope`, 양수
  `generation`만 남겼다. status/Dagster owner/cancellation/error/timeline은 canonical job 한 행만
  변경하며 REST와 projection은 unique JOIN으로 읽는다. 취소 member도 `job_id` 단일 identity와
  import job `RESTRICT` FK로 전환했다.
- DB 적대 리뷰에서 stale generation MVCC race와 `NULL` run owner의 중복 claim을 확인했다.
  start/heartbeat/finish/requeue/scope write는 request+job을 함께 잠그고 exact generation과
  trimmed non-empty Dagster run owner를 CAS한다. DB CHECK는 queued owner NULL, running owner
  non-NULL을 양방향 강제하고 0052는 legacy 위반 ID를 명시 진단한다.
- DB clean-cut 재리뷰에서 request→job FK+UNIQUE만으로는 reverse orphan을 막지 못한다는 S2를
  반영했다. 0052는 unlinked terminal `feature_update_request`의 양방향 연결 component 전체에
  `quarantined_at`과 고정 사유를 기록하되 원래 `kind`·`payload`는 보존한다. projection과 generic
  writer에서 제외하고 DB trigger로 runtime 표식 변경, UPDATE/DELETE/event 추가와 새 child attach를
  금지한다. active/cancellation-protected component는 중단한다. deferred constraint trigger는
  job INSERT와 request DELETE의 commit 시점에 양방향 1:1을 강제하고 request의 `job_id` 변경도
  금지한다. generic job writer는 이 kind의 생성·일반 lifecycle을 거부하며 전용 enqueue/lifecycle/
  heartbeat 경계만 사용한다. canonical job은 parent와 load batch가 없는 root다.
- UI clean-cut 재리뷰의 S2를 반영해 구 `/admin/feature-update-requests` 목록·상세 redirect route를
  삭제하고 client 구현을 정본 `/admin/features/update-requests` route 내부로 이동했다.
- 이 UI/DB S2 이전 snapshot의 승인은 최신 diff의 최종 gate로 사용하지 않는다.
- 0052 migration 실DB 검증에서 SQLAlchemy naming convention이 생성한 실제 FK 이름이
  `fk_feature_update_requests_job_id_import_jobs`임을 확인해 upgrade/downgrade가 같은 이름을
  사용하도록 고쳤다. 새 CHECK는 convention이 이름을 다시 붙여 이중 prefix가 생기지 않도록
  Alembic의 `op.f(...)`와 ORM의 `conv(...)`로 이미 완성된 이름임을 명시했다.
- migration 회귀 fixture는 0051의 canonical root/child 불변식을 만족하도록 바꿨다. active
  relink preflight truth table은 source DB 상태, raw Dagster 상태, request cancellation,
  jobless request, child 상태를 각 행에서 하나씩만 활성화해 조건별 차단을 독립 검증한다.
- SQLAlchemy text SQL에서 `:null`이 bind parameter로 해석되던 테스트를 안전한 literal 표현으로
  수정했다. selective EXPLAIN은 direct-exact seed가 실제로 선택적인 분포를 갖도록 배경 데이터와
  통계를 보강해 planner access path 회귀가 우연한 fixture 분포에 기대지 않게 했다.
- 격리 component의 event에도 직접 `quarantined_at`을 두고 여섯 감사 조회용 부분 index를
  visible event만 대상으로 재구성했다. statement-level singleton event clock은 INSERT/UPDATE/
  DELETE/TRUNCATE마다 transaction 안에서 revision을 한 번 올려 late commit, rollback, cascade,
  zero-job snapshot에서도 live invalidation을 보존한다. direct clock 변조는 DB trigger로 막았다.
- 최종 DB/REST/UI 및 이후 로직 수정은 매번 적대 리뷰 2인의 S1/S2/S3 0건 승인을 받은 뒤
  검증했다. Ruff, strict mypy(main 112/API 55/Dagster 21), import 계약 4/4, OpenAPI/admin type
  drift, frontend type/lint(오류 0), unit 1,366, API 502, Dagster 270(1 skip), non-live integration
  518, frontend unit 82와 production build가 통과했다. n150 격리 checkout의 mocked E2E 11개
  spec은 501/501 통과했고 prod checkout/container는 변경하지 않았다.
- 로컬 reverse geocoder HTTP 400인 live 전용 5건은 C3e-I/C7의 n150 prod gate로 분리했다.
  사용자 지시에 따라 A2 PR 제출 직전에 `docs/tasks.md`에서 제거해 `docs/tasks-done.md`로
  아카이브했다. 다음은 보안 감사·문서-only main rebase·PR CI/review/merge다.

## 2026-07-15 (agent A) — C3e-A2 canonical root/exact-pair projection 구현

- codegraph를 동기화해 pipeline execution/count와 datasets latest의 생산 호출자를 확인했다.
  기존 signature 영향은 `list_pipeline_executions` 19개, `PipelineExecution` 7개,
  `list_latest_dataset_executions`·`DatasetLatestExecution` 각 11개,
  `get_pipeline_status_counts` 9개, `PipelineStatusCounts` 12개,
  `PipelineOverviewData` 3개이며, detail raw job 확장은 `OpsImportJob` 34개 symbol이었다.
  writer 경계 재분리 전 codegraph는 `enqueue_import_job` caller 31개·영향 100개,
  `start_import_job` caller 45개·영향 137개를 확인했다.
- C3b lineage CTE를 공용 root projection으로 확장했다. exact pair는 실컬럼 member를 우선해
  결정적으로 고르고 direct request scope는 같은 member의 `sync_scope`만 보강한다. provider/dataset
  display 배열은 pair 복원에 사용하지 않으며 exact pair filter가 서로 다른 행의 provider와
  dataset을 조합하지 않는다. import job event는 감사·타임라인 전용으로 projection에서 읽지 않는다.
- feature-load run은 임의 child가 아니라 root 자체를 projected job으로 고정하고 pair child 상태는
  정렬된 `provider_datasets[]`에만 노출한다. pipeline overview는 raw job/request 분리 count를
  제거하고 canonical root 단위 세 필드로 원자 전환했다. datasets 독자 recursive/payload lineage
  SQL을 제거하고 grid latest, detail recent와 pipeline detail이 같은 projection을 사용한다.
- all-dataset latest batch, common detail correlation, exact pair 교차곱 차단, feature root 고정,
  overview/timeline count 일치와 0051의 pair/provider-only/dataset-only identity index EXPLAIN
  회귀를 작성했다. 1차 적대 리뷰에서 feature root projection·typed pair 우선순위·request
  correlation을 보강하고, production caller가 사라진 `OpsDatasetRunSummary` 계열과 별도 job
  일괄 조회를 제거했다. 1,005개 root 전수 pagination/latest/count 회귀, status/latest/detail
  raw SQL EXPLAIN을 추가했다. 2차 적대 리뷰의 S2 3건에 따라
  update request detail의 trigger와 scalar pair를 strict direct scope/root와 일치시키고 non-exact
  배열의 cross-product를 막았다. direct scope 양쪽을 JSON string·trim 보존·nonempty인 단일
  validated pair로 묶어 malformed scope가 SQL projection에서 부활하지 않게 했다. 사용자 지시에
  따라 첫 리뷰 승인을 받은 뒤 로컬 gate를 실행했다. 최종 성능 리뷰에서 selective
  pair/UUID도 전체 graph를 순회하는 문제와 optional pair 필드·문서 drift를 다시 발견해,
  indexed identity seed→connected component projection과 required/required-nullable OpenAPI 계약,
  production-like natural-planner EXPLAIN gate로 보강했다. 이후 DB-boundary 적대 리뷰에서 append-only
  event log를 runtime identity source로 쓰는 구조와 그 write-amplifying projection index를 반려했다.
  typed `import_jobs`를 단독 정본으로 고정하고 0051 one-time backfill만 event를 읽게 했으며,
  event-only 잔여의 의도된 read-model 제외와 prod preflight 집계를 문서화했다. 무필터·dataset-only·
  exact pair event 감사 조회는 각각의 시간순 index와 nullable-OR 없는 고정-clause SQL로 보존한다.
  generic writer 이름도 pair/unpaired 네 함수로 분리하고 event INSERT는 job typed pair만 원자적으로
  복사하게 했다. 최종 DB 리뷰에서 남은 JSON scope 이중 정본을 제거하기 위해 0052가 jobless·
  scope 불일치 request를 새 canonical job으로 재연결한 뒤 `job_id NOT NULL/RESTRICT`, direct scope
  shape/linked pair trigger, import pair 불변 trigger를 적용한다. direct JSON expression index와
  root-status fallback, 단일값 `status_source` 응답 필드를 제거하고 member id를 non-null로 고정했다.
  재리뷰 S1 2/S2 2를 받아 upgrade 시작 시 두 writer table을 잠그고 cancellation marker/member
  relink를 fail-closed했으며 이전 job ID를 audit payload에 보존했다. 공통 CHECK는 모든 scope의
  canonical JSON shape 전체를 강제하고 direct scope와 typed job pair를 교차 검증한다.
  upgrade는 중복 `idx_feature_update_job`을 제거하고 unique request-job index를 역추적 경로로
  쓰며 downgrade에서만 기존 partial index를 복원한다. request/source의 양방향
  connected component에 active DB/Dagster 상태가 있는 relink도 중복 실행을 막기 위해 중단한다.
  후속 적대 점검에서 DB CHECK만 엄격하고 main client preview가 느슨한 경계와 실행 의미가 없던
  `sigungu_by_radius.match` 두 값을 발견했다. main-library 공용 canonical validator를 preview/enqueue/
  client에 적용하고 DB의 Python-equivalent whitespace·6종 exact shape와 맞췄으며, match는 실제
  지원하는 `intersects`만 남겼다. REST는 201 영속 생성과 200 비영속 preview endpoint로 분리하고,
  write 없는 dry-run을 행 속성으로 표현하지 않도록 DB의 `dry_run` 컬럼도 제거한다. 최종 리뷰의
  reserved Dagster kind 연결과 provider/dataset JSON shape S2를 반영해 linked job은 정확히
  `kind=feature_update_request`만 허용하고 kind/provider/dataset을 불변으로 고정했다. terminal
  reserved 연결은 canonical job으로 repair하고 active/cancellation branch는 계속 중단한다.
  provider/dataset filter는 JSONB에서 typed `TEXT[]`로 clean cut해 비배열·비문자열 상태 자체를
  제거하고, DB/Python 양쪽에 32/64개·trimmed non-empty·128자 규칙을 동일하게 강제한다.
  최신 전체 diff 재리뷰에서 REST/UI reviewer는 S1/S2/S3 0건으로 승인했으나 DB reviewer가
  typed API와 임의 JSONB 저장이 어긋나는 `update_policy`를 S2로 반려했다. repository
  canonicalizer와 0052 fail-closed preflight, 허용 key/type DB CHECK를 추가해
  `mode='refresh_existing'`와 boolean override 5개만 저장하고 `None`은 키 생략으로
  정규화했다. unknown/wrong type/JSON null·array를 repo와 migration/CHECK 양쪽에서 거부하며,
  valid non-empty policy 보존과 migration rollback 회귀를 추가한 최신 diff를 다시 동결·재리뷰한다.
  이어진 REST 계약 재리뷰는 Pydantic의 boolean coercion과 nullable model 기본값이 sparse DB
  policy를 응답에서 6개 `null` key로 재팽창시키는 두 S2를 발견했다. policy HTTP 모델을
  `total=False` strict `TypedDict`로 clean cut해 key는 생략 가능하되 존재하면 non-null exact
  JSON type만 허용하고, 저장 `{}`/부분 policy를 응답에서도 그대로 유지한다. OpenAPI/admin
  generated type은 nullable union 없이 optional boolean/literal key로 재생성했고 create/preview의
  문자열·정수·null boolean 422 회귀와 live `{}` 계약을 고정했다.

## 2026-07-15 (agent A) — C3e-A1 canonical operation 영속화 구현

- codegraph를 동기화해 `ImportJobRow` 변경 영향 52개 symbol과
  `AsyncKorTravelMapClient` caller 20개를 확인했다. repository symbol 미탐지는 runtime의 모든
  `ops.import_jobs` direct-write SQL을 `rg`로 전수해 보완했다.
- Alembic 0051/ORM에 exact pair·trigger·registry/raw Dagster status와 parent/identity 제약,
  partial unique/index, payload를 쓰지 않는 보수적 backfill과 fail-closed downgrade를 구현했다.
  immutable main-package DTO와 operation repository/client에는 전체 selection ensure, 단조 상태,
  pair progress, attempt event, terminal invariant closure, unmarked active keyset sweep을 고정했다.
- generic jobs/update-request writer의 reserved kind·parent·target 우회를 차단하고 offline upload,
  MOIS, exact update request가 canonical identity/trigger 실컬럼을 쓰도록 정렬했다. C3d cancellation
  snapshot/API/OpenAPI/admin type에는 `operation_kind`와 `requires_run_termination`을 추가해 queued
  feature run도 at-most-once terminate, frozen retry와 authoritative terminal CAS를 사용한다.
- migration up/down/backfill, 멱등 lifecycle·역전 방지, generic claim/stale 제외, writer fail-close,
  active sweep, queued run-backed cancellation/service terminate 회귀를 작성했다. 사용자 지시에 따라
  테스트/lint/mypy/build/OpenAPI export·drift는 이 단계에서 실행하지 않았다.
- 테스트 전 적대 리뷰에서 canonical SUCCESS의 non-done terminal child 보존, same-run 동시 ensure,
  STARTED ensure↔C3d marker 양방향 barrier, cancellation run 시각 NULL 보충·drift 거부, runless
  running definitive failure, queued canonical terminate 실패 뒤 frozen retry를 추가로 고정했다.
  terminal engine 시각은 legacy/generic의 both-NULL을 허용하되 부분 start-only 저장은 typed
  invariant로 즉시 거부하고, feature terminal heartbeat는 queued 출발도 authoritative finish로 맞춘다.
- 리뷰 반영 뒤 외부 geocoder live 전용 파일을 제외한 전체 1,762건, API 473건,
  Dagster 270건(1 skip), frontend unit 82건과 focused migration/cancellation 200건을
  통과했다. 전체 실행에서 분리된 live 5건은 로컬 geocoder의 HTTP 400이며 C3e 관련
  실패 4건은 fake signature·오류 문구·설정 최소값을 현재 계약에 맞춰 해소했다.
- Ruff, strict mypy 3패키지, import 계약 4/4, OpenAPI admin/user drift, admin generated
  type drift와 frontend type/lint/build를 통과했다. production public URL placeholder를
  명시한 build는 34개 route를 생성했다.

## 2026-07-15 (codex) — C3d 종결·C3e 문서 계약 재설계

- PR #695는 Python 3.11/3.12/3.13, fixture replay, PostGIS integration, lint,
  OpenAPI, frontend 8개 check가 모두 green인 상태에서 merge됐다. 이슈 #680에 구현·테스트
  증거를 남기고 closed/completed로 종결했다.
- Claude Code 전용 worktree·branch·stash·reflog를 조사했으나 C3e 구현 diff는 없었고 상세
  설계 기록만 복구했다. 구현을 가져온 것으로 가장하지 않고 C3d merge commit
  `28dfe224`와 migration head `0050_pipeline_cancellations` 위에서 문서부터 다시 설계했다.
- 두 적대 리뷰어가 retry 첫 실패 terminal 오기록, datasets 독자 payload 계보 SQL,
  pre-resource failure, provider alias, exact pair filter, mixed-version 순서와 가장 중요하게
  같은 run의 pair별 standalone root가 C3d 공유-run 취소 경계를 깨는 문제를 차단했다.
  최종 계약은 Dagster run root 한 건 + exact provider/dataset child, sensor terminal 소유,
  공용 C3b lineage projection, `(kind,id)` correlation, C45X의 sync scope 비선점이다.
- 후속 적대 리뷰에서 registered identity의 panel-only fail-open, terminal child-set mismatch의
  active 고착, overview child N배 집계, 임의 pair `projected_job`, reconciliation cursor 비순환,
  queued feature 취소의 running-only C3d 상태기계, raw Dagster status/engine timestamp·root progress
  누락을 추가 차단했다. 0051 cancellation frozen identity와 raw run 관측, overview canonical DTO,
  provider 선행 fail-closed, sweep wrap과 downgrade guard까지 문서 정본에 고정했다.
- codegraph 인덱스가 이 worktree에서 없어 `codegraph init -i`를 실행했으나 157파일 중 Python
  53파일만 인덱싱해 대상 symbol을 찾지 못했다. 따라서 기존 C3b/C3d lineage SQL,
  datasets repository, Dagster schedule/assets, API schema의 호출·import를 `rg`로 전수해
  영향도 평가를 보완했다. source edit은 문서 적대 재승인 전 0으로 유지한다.
- 두 적대 리뷰어는 registered/unregistered identity, terminal invariant closure, C3d queued
  retry, raw status/timestamp/progress, overview/home 집계, migration DDL과 PR 독립 CI 경계를
  반복 재검토한 뒤 최신 문서 diff를 S1/S2 0건으로 승인했다.

## 2026-07-15 (codex) — C3d CI coverage 측정 경계 수정

- PR #695의 Python 3개 job에서 1,299개 테스트는 모두 통과했지만, unit 측정만으로 DB
  transaction/repository 신규 코드를 0%에 가깝게 계산해 전체 coverage가 75.24%가 됐다.
- threshold를 낮추거나 DB 코드를 제외하지 않고, Python 3.13 unit 원시 coverage와 별도
  PostGIS integration coverage를 합산한 결과에 기존 `fail_under=80`을 적용하도록 CI를
  수정했다. Python 3.11/3.12는 동일 unit 회귀를 계속 실행한다.
- workflow 구조 테스트와 테스트 전략 문서를 같은 계약으로 갱신했다.
- 로컬 합산 실행은 89.50%로 coverage gate를 통과했다. 전체 integration을 함께 돌리며
  발견한 0048 migration의 고정 최신-head 단언은 단일 head+ancestor 단언으로 바꾸고,
  phase commit 테스트가 남긴 운영 로그가 목록 테스트를 오염하지 않도록 해당 테스트의
  transaction-local 초기화를 추가했다. 로컬 `kor-travel-geo` 400 응답 5건은 외부 live
  서비스 상태이며 GitHub runner에서는 도달 불가 skip되는 기존 계약이다.
- 최종 적대 리뷰에서 API/Dagster package coverage 누락, artifact wiring의 문자열 단언,
  실패 시 combined XML 미보존을 확인했다. 로컬 실측 API 77%, Dagster 82%를 기준으로
  각각 70%/80% 독립 gate를 추가하고 YAML job/step 구조를 파싱해 artifact 대칭과 threshold
  위치를 고정했다. combined XML은 취소가 아니면 실패 시에도 보존한다.
- 2차 CI의 합산 coverage는 89.51%를 통과했지만 fresh DB의 1행 EXPLAIN이 비용상 seq scan을
  선택했다. index 사용 가능성 검증 목적에 맞게 transaction-local `enable_seqscan=off`를
  설정해 planner 우연성을 제거했다.

## 2026-07-15 (claude, agent A) — T-ADM-C3c 잔여범위 감사 → 전 항목 기충족 확인·종결

T-ADM-C3c(#681) 착수 전 잔여범위 감사를 수행한 결과, 이슈 수용 기준 전 항목이
이미 main(3f3ef6d3)에 머지된 후속 체인으로 충족되어 **추가 구현 없이 종결**한다
(tasks.md C3c `[x]` + 본 감사 기록만 반영).

- 상세 endpoint `GET /v1/ops/pipeline/dagster-runs/{run_id}` — 기충족(#690).
- event cursor 전진 페이지네이션(`after` opaque cursor, `event_cursor`/
  `event_has_more`; DB keyset cursor 정본과 분리) — 기충족(#690).
- `failure_reason`·`failure_events`(현재 event page 범위 명시) — 기충족(#690).
- 404 `DAGSTER_RUN_NOT_FOUND` / 503 `DAGSTER_UNAVAILABLE` / 502
  `DAGSTER_QUERY_FAILED` RFC7807 + 목록 degrade 계약 유지 —
  기충족(#690, `test_ops_pipeline_router.py` 상세 테스트 9건 실측).
- 외부 Dagster 링크 fallback(`dagster_url`/`graphql_url`) — 기충족(#690).
- pipeline `nux-seen` 계약 삭제(legacy `/ops/dagster/nux-seen`은 C6b까지
  존치) — 기충족(#687, openapi.json 실측: pipeline 그룹에 nux 없음).
- C3a 공용 service 경계 — 신/구 라우터가 `dagster_query_service.get_run_detail`
  공유(직접 import 실측), private 심볼 사용 없음 — 기충족(#687/#690).
- OpenAPI/admin types 고정 — 기충족(#690 재생성분, `types.ts`에
  `/v1/ops/pipeline/dagster-runs/{run_id}` 실측). UI 소비 경로는 C5(#691)/C4R.

## 2026-07-15 — T-ADM-C3d 테스트 전 구현·적대 리뷰 반영

- Agent A/B가 feature update phase executor와 pipeline cancellation coordinator를 병렬
  구현하고, 별도 적대 리뷰어 2명의 S1/S2 지적을 테스트 실행 전에 반영했다.
- queue claim-before-lock, `CancelledError` active 고착, scope checkpoint 유실,
  reservation CAS loser, stale ownership reload, mixed 결과 덮어쓰기, downgrade TOCTOU,
  terminate 오류 오분류, advisory lock backend 오염을 수정했다.
- 네 cancel 진입점은 reason-only+인증 actor+공용 `PipelineCancellationResponse`로 수렴했고,
  기존 admin UI hooks/call site도 같은 응답과 member 단위 invalidation으로 원자 전환했다.
- concurrency/crash/shared·multi-run/backend invalidation 회귀를 추가하고 OpenAPI/admin types를
  재생성했다. 최종 적대 재리뷰 전이므로 테스트·lint·typecheck는 아직 실행하지 않았다.
- 첫 최종 재리뷰에서 old Dagster failure run의 generation CAS 부재, production asset이 executor
  session을 무시하는 적재 경계, `Retry-After` 기계 계약 누락, mocked/live E2E의 구 cancel
  envelope를 확인했다. failure sensor→client→request/job에 expected run CAS를 연결하고,
  production asset client를 scope transaction의 physical connection에 bind했다. 세 공개
  operation은 공용 OpenAPI header 선언을 사용하며 browser client는 RFC7807와 재시도 초를
  보존하고 오류 뒤에도 durable 상태를 invalidate/reload한다. reason-only 요청과 root/member
  응답으로 E2E fixture·파괴적 live spec을 함께 바꿨다.
- 실제 production 축제 asset의 data write 뒤 checkpoint 실패 rollback, stale old-run의
  queued/new-running 비변경, hard invalidate 뒤 backend PID 소멸·request lease 재획득을
  회귀로 추가했다. 수정 snapshot 재리뷰 전이므로 실행 게이트는 계속 닫아 두었다.
- 2차 최종 재리뷰에서 확인된 pre-start resource failure 영구 queued, Next BFF의
  `Retry-After` 유실, 연결 member 상세 cache 잔존, 임의 queued child를 root로 가정한 파괴적
  live E2E, bound client의 원본 engine 탈출을 R2A/B/C로 분리했다. sensor run key/config/tag에
  동일 `updated_at` generation을 고정하고, 같은 queued/null-run generation만 전진시킨다.
  start는 request/job owner CAS 전체가 성공해야 하며 불일치는 savepoint rollback한다.
  BFF는 응답 header allowlist로 재시도 초를 전달하고, 오류 뒤 singular detail prefix를
  invalidate하며, live E2E는 canonical standalone import root와 `linked_job_count`를 먼저
  고정한다. transaction-bound asset client의 원본 engine 연결은 fail-closed로 거부하고
  data·provider sync state·checkpoint rollback을 함께 검증한다.
- 이슈 #680과 원인 PR #677 및 root projection PR #689를 다시 대조했다. marker/status 분리,
  frozen hierarchy, authenticated actor/audit, request/job/run CAS, GraphQL problem 5xx, runless
  running 사실 보존, member별 결과, commit 데이터 비롤백을 구현·회귀에 반영했다. 이슈는
  C3d PR CI/review/merge 뒤 증거 코멘트를 남기고 닫는다.
- 리뷰 전문 agent가 최근 2일 Claude Code PR 중 공동작성 trailer/session 근거가 있는
  #672, #674, #675, #676, #677, #683, #691, #692를 닫힘 여부와 무관하게 상세
  감사하고 각 PR에 코멘트를 남겼다. review-fix 전용 PR은 없었다. pipeline UI 상태
  격리·sensor fail-closed·URL 복원은 #693, live E2E 의미 단언은 #694로 묶어 새 이슈를
  만들었다. 기존 #682, #684, #685, #686에는 보강 코멘트를 남겼고, #687이
  actor/problem/schedule 수용 기준을 완료하지 않아 #682를 다시 열었다.
- 사용자 후속 지시로 C3d 다음 순서를 바꿨다. Claude Code worktree에 남은 C3e
  schedule/manual canonical operation 작업을 보존적으로 회수해 별도 PR로 완료한 뒤,
  adm-c5 merge를 확인하고 C6→C7로 진행한다.
- 최종 교차 리뷰에서 failure sensor가 DB client resource를 필수 선언하지 않아 운영 context가
  pre-start generation 복구를 건너뛸 수 있는 S2를 확인했다. sensor decorator에
  `kor_travel_map_client` resource 계약을 추가하고 정의 수준 회귀로 고정했다. 실행 게이트는
  재리뷰 승인 전까지 계속 닫아 둔다.
- 같은 리뷰의 S3로 mock 응답이 `running + run 없음`과 `queued + STARTED run`을 만들 수 있음을
  확인했다. cancellation fixture가 running에는 run ID를 요구하고 queued에는 DB-only no-run
  경로만 허용하도록 상태별 invariant를 강제했으며 기존 호출부를 실제 사실 모델에 맞췄다.
- 두 번째 교차 리뷰의 S3로 provider resource 생성 뒤 transaction-bound client 결합 실패 시
  teardown이 실행되지 않는 handle 누수를 확인했다. resource 생성 직후부터 bind/context/asset
  실행 전체를 `try/finally`로 감싸고 bind 실패에서도 teardown 1회를 보장하는 회귀를 추가했다.
- 첫 실행 게이트에서 설치된 Dagster의 `run_failure_sensor` decorator가
  `required_resource_keys` 인자를 받지 않아 collection 2건이 실패했다. 이 버전이 지원하는
  `ResourceParam` 함수 인자 주입으로 DB client를 필수 resource로 선언하고 handler에 직접
  전달하도록 바꿨다. 정의의 `required_resource_keys` 회귀는 동일 운영 계약을 계속 검증한다.
- 전체 로컬 gate는 main unit 1,295건, API 470건, Dagster 270건(1 skipped), C3d 관련
  Python 134건, PostGIS 관련 통합 92건, frontend unit 82건을 통과했다. Ruff, strict mypy
  main 110/API 54/Dagster 21파일, import 계약 4/4, OpenAPI/admin type drift, frontend
  type-check/lint도 green이다. WSL pytest는 Windows `TMP` 상속 시 capture 파일이 사라지는
  환경 오류가 있어 `TMPDIR`/`TMP`/`TEMP`를 `/tmp`로 고정했다.
- mocked Playwright 첫 실행에서 BFF 요청을 legacy pathname과 비교해 인증 redirect가 난
  하네스 결함과 오래된 영문 접근성 이름을 확인했다. 공용 `bffApiPath`가
  `/api/proxy/v1/*` 경유를 먼저 강제한 뒤 backend pathname을 반환하게 하고, feature
  update/import-job 5개 spec을 현재 한글 UI·HATEOAS 계약으로 정렬했다. 새 Next 서버의
  현재 빌드에서 36건을 통과하고, ID가 빠진 `feature_update_request` mock link를 실제
  `/{request_id}` 형태로 고친 단독 1건도 통과해 대상 37건을 전량 확인했다.
- 최종 교차 리뷰에서 실제 `load_batch` HATEOAS가
  `/v1/ops/import-jobs?load_batch_id=...`인데 UI와 mock이 path tail 형태로 오해한
  S2를 확인했다. UI는 query parameter를 fail-closed로 읽고, actions/base fixture는
  실제 batch query와 ID 포함 feature-update-request 링크로 맞췄다. 새 서버 현재
  빌드에서 relation link와 base smoke 2건을 다시 통과했다.
- 위 수정까지 두 적대 리뷰어가 다시 확인해 최종 `S1/S2/S3 0`으로 승인했다.

## 2026-07-15 — T-ADM-C3d coordinator crash 계약 보강

- C3d DB phase 최초 실행 게이트에서 단위 14건, cancellation 통합 32건, migration 1건,
  batch 14건과 Ruff/mypy/import-linter를 통과했다.
- phase 2 사전 적대 리뷰에서 canonical root coordinator 동시 실행과 process crash 창을 분석했다.
  별도 nonblocking session lease, `termination_reserved_at` durable CAS, orphan `in_progress`
  resume를 계약에 추가해 attempt별 at-most-once Dagster terminate dispatch를 명시했다.
- `termination_reserved_at` commit과 실제 HTTP 사이 crash는 같은 attempt에서 mutation을
  재호출하지 않고 poll 후 retryable로 닫아 다음 attempt에서 복구한다.

## 2026-07-15 (codex, agent B) — C3d DB phase 2차 적대 리뷰 보강 진행 중

- cancellation SQL, immutable record, 종결 불변식을 query/types/invariants 모듈로 분리했다.
  일반 member/run writer는 열린 attempt를 먼저 잠그며 성공 member 결과는 Dagster run 종결과 정확한
  base marker/status/run 대응을 확인하는 전이에서만 기록한다. queued 대상은 명시적인
  DB-only 경로로 분리했고 닫힌 예전 attempt의 stale write는 거부한다.
- completed/retryable/failed 종결 조건을 frozen detail과 잠근 base 전체에서 검증한다.
  attempt finish/retry 같은 계층 writer는 hierarchy를 재탐색하지 않고
  lineage-global→root→source attempt→detail→base 순서로
  잠근 뒤 실제 retry-capable 미해결 대상만 복사한다. attempt/member/run JSON 상태 조합은
  Alembic/ORM CHECK에도 고정했다.
- full-load batch gate의 단일 transaction repo orchestrator를 삭제했다. 전용 connection과
  batch별 session mutex는 유지하되 prepare, consistency, MV 시작, MV refresh/finalize를
  각각 commit한다. 장기 단계의 lineage lock 누출, 다른 backend로의 unlock, phase 예외의
  부분 상태, cancellation marker 덮어쓰기를 막는 회귀 테스트를 정의했다.
- 2차 리뷰의 S1/S2 지적에 따라 queued shared-run, definitive mismatch, batch sentinel
  rollback, JSON error NULL 제약과 실제 side-effect 부재 테스트를 다시 보강 중이다.
  최종 read-only 리뷰에서는 `cancel_failed`를 frozen running으로 제한하고 exact terminal
  run의 failure 우회를 차단했으며, unit phase fake와 post-refresh MV rollback 회귀를
  실제 guard/lock 의미에 맞게 교정했다.
  사용자 지시에 따라 test/ruff/mypy/import/compile은 실행하지 않았으며, 재리뷰·게이트 전
  완료로 표시하지 않는다.

## 2026-07-15 (codex, agent B) — 계층형 취소 문서 우선 설계 (T-ADM-C3d, #680)

- C3b root projection과 동일한 scope를 취소 정본으로 고정했다. owner request는 nearest
  anchor branch만, duplicate non-owner request는 자기 행만, standalone root는 미소유
  partition만 소유한다. import job 취소는 request branch 안이면 request root로
  canonicalize하고 nested request branch를 넘지 않는다. terminal root 아래 active
  descendant는 계속 처리한다.
- 기존 job/request status CHECK에 중간 상태를 추가하지 않는다. 두 base table의 marker와
  정규화한 `pipeline_cancellations`, `pipeline_cancellation_members`,
  `pipeline_cancellation_runs`를 시도·대상·run 결과의 durable 정본으로 설계했다. 같은 run은
  시도당 한 번만 terminate하고 member에 결과를 전파한다. 재시도는 이전 frozen scope의
  미해결 member만 복사하며 hierarchy를 다시 탐색하지 않는다.
- marker/감사를 먼저 commit하고 외부 transaction 없이 Dagster terminate한 뒤 terminal을
  재확인한다. queued는 marker CAS, running은 `CANCELED`일 때만 cancelled이며 정확한
  marker/member/run의 `SUCCESS`/`FAILURE`만 done/failed다. attempt status는 workflow
  `in_progress`/`retryable`/`completed`/`failed`, 실제 결과는 member/run에만 둔다. run id 없는
  local running·mapping 불일치는 attempt `failed`, GraphQL/terminate transient 실패는
  `retryable`이며 둘 다 member `cancel_failed`와 marker를 남긴다.
- feature update의 장기 transaction은 전용 `AsyncConnection` 하나에 session advisory
  lock을 고정한 scope별 짧은 transaction으로 분리하기로 했다. 이미 commit된 scope와
  provider 외부 효과는 rollback하지 않으며 REST 응답도
  `committed_data_rolled_back=false`로 명시한다. downgrade는 active marker/시도가 있으면
  거부한다.
- 이번 단계는 data model/REST/tasks/journal/resume 문서만 수정했다. 적대적 문서 재승인
  전 source edit은 0으로 유지한다.

## 2026-07-15 (codex, agent A) — pipeline Dagster run 상세 계약 이식 (T-ADM-C3c, #681)

- `GET /v1/ops/pipeline/dagster-runs/{run_id}`를 추가했다. event cursor는
  `after`로 전진 조회하고, `failure_reason`·`failure_events`는 현재 event page
  범위임을 DTO/OpenAPI에 고정했다. 성공만 200이며 not-found, 연결 실패,
  query/설정/응답 오류를 각각 404/503/502 RFC7807 problem으로 반환한다.
- public Dagster parser/service를 재사용하되 `__typename=Run`만으로 성공시키지
  않는다. 응답 `runId`의 누락·불일치, 잘못된 eventConnection pagination shape,
  다음 page cursor 누락·빈 값·2,048자 초과를 `status=error`로 차단했다. 신규 strict
  route는 502, 전환 중인 legacy route는 기존 200 envelope 안의 error로 보존한다.
  codegraph `impact parse_run_detail` 결과 영향 심볼은 공용 `get_run_detail` 하나였다.
- HTTP 연결·timeout만 unavailable로 분류하고, upstream HTTP 상태·JSON 해석 실패는
  query error로 분리했다. 새 UI가 iframe을 쓰지 않으므로 신규 pipeline
  `nux-seen`은 제거했고 legacy `/ops/dagster/nux-seen`은 C6b까지 유지한다.
- 테스트 전 적대적 리뷰 2인은 URL/PythonError 502 공백과 malformed Run 오인 경계를
  발견했다. 두 지적을 반영한 수정 diff 재리뷰는 S1/S2 0건으로 승인됐다.
  root unit/lint 1,289건, API 전체 451건, 관련 Dagster router 82건, 전체 Ruff,
  strict mypy main 104파일/API 51파일, import 계약 4/4, OpenAPI admin/user와 admin
  TypeScript drift가 통과했다. C3c는 DB/migration 변경이 없어 별도 PostGIS 전용
  integration gate는 적용하지 않았다. PR #690은 CI 8/8 green 뒤 merge됐다.

## 2026-07-15 (codex, agent B) — pipeline root projection (T-ADM-C3b, #679)

- import job `parent_job_id` hierarchy를 recursive SQL에서 cycle-safe component로
  접고, 각 job의 ancestry에서 가장 가까운 request anchor를 선택해 request branch와
  standalone partition으로 분리했다. 같은 anchor의 request만 생성 시각·ID로 owner
  하나를 고르며 loser request는 `lineage_owner=false` 진단 root로 보존한다.
  이 C3b 당시 진단 계약은 후속 C3e-A2의 request↔root job 양방향 1:1 clean-cut으로 대체됐다.
- root 상태와 대표 job 상태를 덮어쓰지 않고 `projected_job`으로 분리했다. request의
  저장 providers/dataset_keys 순서·중복을 유지하면서 direct scope 누락값을 보완하고,
  provider/dataset/sync_scope pair는 typed object로 보존한다. standalone identity/filter는
  partition 전체 `import_job_events` 실컬럼만 사용한다. payload는 hot path에서 읽지 않는다.
- cursor는 `(created_at DESC, id DESC, kind DESC)` v2 total order로 바꾸고
  `dataset_key` filter를 추가했다. detail/cancel과 persistence/migration은 변경하지 않았다.
- 실 PostGIS 회귀는 batch root 아래 request sibling 2개, nested anchor, 동일 anchor
  loser, cycle, 부모 누락, event identity, 동일 시각·UUID cursor를 포함한다. root/
  agent A 적대적 리뷰 2인 승인 후 root unit 1,285건, API 전체 416건,
  관련 integration 10건, Ruff, strict mypy 155파일, import 계약 4/4,
  OpenAPI/admin types drift가 통과했다. EXPLAIN은
  event 접근에 `idx_import_job_events_job_time` 3회와 root PK 2회, temp I/O 0,
  실행 2.31ms를 확인했다. 나머지 세 후보 index는 소규모 planner 선택을 기록만 했다.

## 2026-07-15 (codex, agent A) — C2 적대적 리뷰 차단 계약 보강 (T-ADM-C2R, #678)

PR #676의 후속 적대적 리뷰가 C4 frontend의 정본으로 쓰기 어려운 시간·실행·preview
의미를 발견했다. schedule/manual 전체 operation 정본은 pipeline 축과 겹치므로 #679로
분리하고, C4를 직접 차단하는 datasets 계약만 수술적으로 보강했다.

- `ops.provider_refresh_policies.stale_after_minutes`를 Alembic 0049 nullable 양수
  필드로 추가했다. freshness는 disabled 우선, 성공 이력 없음 `never_run`, 명시적
  SLA 없음 `unknown`, SLA가 있을 때만 `fresh|overdue`를 서버에서 계산한다.
- `provider_sync_state.next_run_after`를 `eligible_after`로 명확히 하고, Dagster 전체
  schedule을 GraphQL 한 번으로 읽어 definition tag 두 개와 RUNNING future tick에서
  실제 `next_scheduled_at`을 계산한다. provider tag alias는 공용 정본으로
  canonicalize하며 schedule 이름 추론은 하지 않는다. GraphQL 실패는 DB 그리드 200과
  `unknown` schedule을 유지한다.
- import job event의 canonical provider/dataset과 `provider_dataset` update request를
  단일 SQL로 합쳤다. direct job, `parent_job_id` child/grandchild, payload request id
  연결을 request 계보로 먼저 접어 root 한 행만 남기고 request 상태와 가장 깊은 child
  job 상태·진척을 분리했다. event 발생 시각이 root 최신 순서를 바꾸지 않으며 자유 JSON
  request id를 UUID cast하지 않는다.
- provider-level issue와 dataset-level issue를 별도 집계로 반환한다. 카탈로그에서
  사라진 sync/policy 잔존 row는 `orphan`, `mutable=false`로 표시하고 정책 mutation은
  409 `mutation_disabled_reason`으로 금지한다.
- 신규 ops preview는 fixture capability만 허용하고 typed body, `max_items(1..100)`,
  cooperative timeout, 외부 호출 budget 0, `truncated` 메타를 반환한다. raw live HTTP
  adapter는 신규 제품 API에서 제거했다.
- codegraph `impact ProviderRefreshPolicyRow` 결과 영향 심볼은 해당 ORM row 1개였다.
  PostgreSQL 변경은 nullable 컬럼+CHECK라 기존 행 rewrite/backfill이 없다.
- 구/new refresh-policy PUT 모두 SLA 필드를 전달하게 고정했고, grid 전용 정책 전량 조회로
  admin 목록의 500건 clamp를 재사용해 orphan을 조용히 누락하던 경계를 제거했다.
- PR #687을 rebase해 schedule transport는 public `dagster_graphql`, request context는
  `dagster_http`만 사용한다. 테스트 중 generic `HTTP 409 error`로 손실되던 orphan·
  preview 오류는 중앙 RFC7807 `{code,message,details}` 정본의 세 code로 고정했다.
- **적대적 리뷰·검증**: root/agent B의 테스트 전·실패 수정 delta 리뷰를 모두 통과했다.
  API 관련 23건, API 전체 416건, root unit 1,284건, 관련 PostGIS/Alembic integration
  20건이 통과했다. Ruff 전체, strict mypy 176파일, import-linter 4계약, OpenAPI
  admin/user와 admin TypeScript drift, Alembic 단일 head, docs redaction도 green이다.

## 2026-07-15 (codex, agent B) — pipeline 공용 application 경계 추출 (T-ADM-C3a, 이슈 #682)

PR #677 적대적 리뷰에서 확인된 신규 `/ops/pipeline`의 구 라우터 private 심볼
의존을 제거했다. HTTP 동작과 OpenAPI를 바꾸지 않는 구조 정리이며, C3b~C3e의
실행 정본 개편은 포함하지 않았다.

- **공유 경계**: Dagster DTO를 `dagster_schema.py`, GraphQL transport/parser를
  `dagster_graphql.py`, 조회·NUX application 로직을 `dagster_query_service.py`,
  schedule override·command transaction을 `dagster_schedule_service.py`로 분리했다.
  feature update 요청도 schema/application service로 나눠 legacy/new router가 같은
  public 모듈을 사용한다. application 모듈은 FastAPI `Request`/`HTTPException`을
  모르며 settings·HTTP client·DB session을 명시적으로 받는다.
- **HTTP adapter**: request dependency 조립과 typed application exception→HTTP
  응답 변환은 `dagster_http.py`·`feature_update_http.py`에 한정했다. 두 router는
  decorator와 request-context만 소유하고 공용 service에 위임한다. client 재사용,
  advisory lock 409 `Retry-After`, 검증 422, resolver 502/503, 미분류 오류 500을
  adapter 단위 테스트로 고정했다.
- **적대적 리뷰 2인 반영**: 단일 1,800행 service 이동안을 query/schedule/GraphQL로
  재분리하고, FastAPI 의존·private alias·테스트 monkeypatch drift·schedule override
  SQL 식별자 손상을 제거했다. 마지막 OpenAPI 검사에서 발견한 DTO class description
  drift는 origin/main 문구를 그대로 복원해 admin/user spec 모두 무변경으로 닫았다.
- **검증·merge**: 관련 API unit 68건, API 패키지 전체 421건, 저장소 unit 1,282건,
  schedule override PostGIS integration 1건과 CI 8개를 통과해 PR #687로 merge했다.
  Ruff 전체, strict mypy 3패키지, import-linter 4계약, OpenAPI admin/user 무변경도
  확인했다.

## 2026-07-14 (claude, agent B) — backend /ops/pipeline 그룹 신설 (T-ADM-C3)

ADR-064 페이지 ①(`/ops/pipeline`)의 백엔드 리소스 그룹 12 endpoint를 신설했다
(구 라우터 삭제는 T-ADM-C6b 범위 — 추가만). PR #677.

- **신규 라우터 `routers/ops_pipeline.py`**: overview(Dagster 요약+큐/failure
  sensor 상태+DB 작업/요청 카운트 — Dagster 다운 시 200 `unavailable`로 DB
  카운트는 유지) · executions(**DB-only UNION**: `ops.import_jobs` ∪
  `ops.feature_update_requests`, 공유 keyset cursor `(created_at DESC, id DESC)`
  + kind discriminator, kind/상태/provider/기간 필터 — Dagster run은 cursor에
  섞지 않고 실컬럼 속성으로만 연결) · `/{kind}/{id}`(+cancel) · events(전역
  스트림 이식) · dagster-runs(보조 패널, degrade 유지) · schedules(override
  병합+sensor) + PATCH(**`cron_schedule: null`=override 삭제** — 구 default 명령
  대체) + commands(4종 enum) · requests(6-type scope union·카탈로그 검증·geo
  resolver·advisory lock 409/Retry-After·operator/reason 전량 승계) ·
  run-now(201+새 request) · nux-seen. UNION 조회는 신규
  `infra/pipeline_repo.py`(strict+coverage). 마운트는 `ops_routes_enabled` +
  `require_admin_frontend`의 자체 include 블록.
- **alembic 0048**: `ops.import_jobs.dagster_run_id` 실컬럼 + payload
  (`dagster_run_id`/레거시 `run_id`) 백필 + 부분 인덱스. jobs_repo INSERT/UPDATE
  경로가 payload run id를 실컬럼으로 승격. 통합 테스트가 0047 파일명↔revision id
  불일치(`0047_notice_reconcile_stats`)로 끊긴 down_revision을 검출·수정.
- **Dagster 조립·갱신요청 계약은 구 라우터에서 import 재사용**(대량 복제 대신
  계약 동일성 보장 + OpenAPI 스키마 이름 충돌 회피) — C6b가 구 라우터 삭제 전
  중립 모듈로 이식해야 한다(tasks.md C6b 전제로 명문).
- **적대적 리뷰 2인 반영(PR #677, S3 9건)**: ① ops_live dagster 스냅샷을
  실컬럼 우선 + payload COALESCE 폴백으로 견고화 — migration runner가
  api-entrypoint뿐이라 생기는 mixed-version 배포 창(구 dagster 이미지가 백필
  이후 payload-only row 기록)을 정확성 우선으로 흡수, 0048 docstring에 배포
  순서(api 먼저)와 백필 재실행 SQL 명기. ② cursor key·`{kind}/{id}`·events
  job_id·run-now request_id에 UUID 검증(비정형 입력 500→422). ③ 감사 필드 유령
  수용 2건 해소 — PATCH override 삭제와 update request cancel의 operator/reason을
  구조화 로그로 남기고 테스트로 고정. ④ 409 응답의 `Retry-After` 헤더 OpenAPI
  명문화. ⑤ A의 `dataset_status_repo`에 `dagster_run_id` 컬럼/매퍼 전파(누락 시
  datasets 상세 최근 실행에서 항상 None). ⑥ postgres-schema.md에 컬럼·부분
  인덱스 기재, tasks.md에 C5 소비 전제(이중 행 접기·provider 필터 탈락·progress
  취득처)와 C6b 이식 전제 명문.
- **생성물**: `openapi.json`(+12 path·+22 스키마, 순수 additive) + admin
  `types.ts` 재생성, `openapi.user.json` 불변 확인(PinVi read 표면 무변).
- 게이트(throwaway python:3.13 Docker, WSL): ruff 6트리 / mypy --strict 3패키지 /
  lint-imports 4계약 / openapi --check / alembic 단일 head / pytest unit+lint
  1,281(+coverage 80.16%) · api 387 · dagster 264 · 통합 신규 13+영향 55 green.

## 2026-07-14 (claude, agent A) — backend /ops/datasets 그룹 신설 (T-ADM-C2)

ADR-064 페이지 ②(`/ops/datasets`)의 백엔드 리소스 그룹을 신설했다(구 라우터
삭제는 T-ADM-C6b 범위 — 추가만).

- **신규 라우터 `routers/ops_datasets.py`** (`/v1/ops/datasets/*` 4 endpoint):
  ① 그리드 — ETL 카탈로그 전 행 base(비-refreshable 포함, `/etl` 흡수 대비) ×
  sync state(scope별 다행=3원) × 2원 정책 × 미해결 이슈 카운트, `never_run` 합성.
  카탈로그에서 빠진 잔존 sync/policy row도 `catalog: null`로 보존(defensive).
  ② 상세 — scope 배열(cursor 포함) + 최근 실행(update request+연결 import job
  요약 join) + 최근 이벤트 + 정책/이슈. 카탈로그 조합은 row 없어도 200(never_run
  scope 합성), 셋 다 없으면 404. ③ refresh-policy PUT — 기존 upsert repo 재사용,
  카탈로그/잔존 sync state 검증으로 유령 정책 row 방지(404). ④ preview —
  `/debug/etl` 로직 이식, fixture 상시 / **live는 신규
  `etl_live_preview_enabled`(기본 off) opt-in 뒤 403 게이트**(OpiNet류 쿼터 보호).
- **마운트**: `app.py`에 `ops_routes_enabled` + `require_admin_frontend` 의존성의
  **자체 include 블록**(T-ADM-C3 pipeline 그룹과 rebase 충돌 최소화). 조작 포함
  그룹이라 무인증 ops 패턴 미승계(ADR-064 결정 3).
- **infra 신규 `dataset_status_repo`**(strict+coverage 범위):
  `count_open_integrity_issues_by_dataset`(open/acknowledged 집계, severity 분해,
  provider/dataset 필터) + `list_ops_import_jobs_by_ids`(jsonb 텍스트 배열→uuid
  캐스팅, 타임스탬프 포함 `OpsImportJob` 반환). unit+integration(testcontainers)
  테스트 동반.
- **공유 schema 이동**: `ProviderRefreshPolicyUpsertRequest`를
  `provider_refresh_schema.py`로 이동(구/신 라우터 공용) — C6b에서 구 라우터를
  지워도 계약이 남는다.
- **생성물**: `openapi.json` + admin `types.ts` 재생성. `openapi.user.json` 불변
  확인(admin 표면 한정 — PinVi read 계약 무변).
- 게이트(throwaway python:3.13 Docker, WSL): ruff 6트리 / mypy --strict 3패키지 /
  lint-imports 4계약 / pytest unit+lint 1274 · api 377 · 신규 integration 2 전부 green.
- **적대적 리뷰 2인 반영(PR #676)**: refresh-policy PUT의 begin 밖 존재 검증
  SELECT(autobegin)가 이후 `session.begin()`을 500으로 터뜨리던 S2를 단일
  transaction 구조로 수정 + 실세션(fresh AsyncSession) integration 회귀
  (`test_ops_datasets_refresh_policy.py` 4건 — `_FakeSession` unit은 이 결함
  계급을 못 잡는다는 한계 명주석). PUT 허용 집합을 카탈로그∪잔존 sync∪기존
  policy로 확장(S3 — policy-only 잔존 행의 read/write 자기모순 해소),
  `.env.example`에 `..._ETL_LIVE_PREVIEW_ENABLED=false` 항목 추가(S3).

## 2026-07-14 (claude) — admin ops 통합 재작성 플랜 확정(ADR-064) + concierge #672 n150 live 검증

### admin ops 통합 재작성 플랜 (T-ADM-C1)

사용자 지시(dagster job·provider 기능의 다페이지 분산 해소 — 2페이지 통합 재작성,
호환성·문서계약 무시, 직관적 REST·일관 UI)로 플랜을 수립했다. 초안에 대해 적대적
설계 리뷰 2인(A: 백엔드·REST·데이터 모델 — S1 1·S2 6·S3 8 / B: UX·운영 워크플로·
e2e·분할 — S1 3·S2 7·S3 6)을 돌리고 전량 반영해 확정했다. 정본:
`docs/reports/admin-ops-consolidation-plan-2026-07-14.md` + ADR-064, 실행 단위
`docs/tasks.md` `T-ADM-C1`~`C7`(agent A/B 병렬).

리뷰가 바꾼 핵심 결정: ① 실행 타임라인은 DB-only UNION(keyset) — Dagster
run(GraphQL·휘발)은 목록 cursor에 섞지 않고 실컬럼 연결+보조 패널로(“하나의 실행
이력” 초안 폐기), ② 신규 2그룹은 admin 게이트 마운트(무인증 ops 승계는 현행 대비
다운그레이드), ③ `GET /v1/providers` 계열은 PinVi read 계약으로 존치, ④ OpenAPI/
types 생성물은 각 백엔드 PR에서 재생성(T-C6 일괄안은 openapi-drift 게이트와 충돌),
⑤ `import_jobs.dagster_run_id` 실컬럼+인덱스(현 WS hot path가 payload JSONB 풀스캔),
⑥ sensor 상태 노출(큐 침묵-정지 장애 모드), ⑦ 진입점 재배선 체크리스트(entity-link
단일 URL 테이블 등 존치 화면 9파일+mock spec 19파일), ⑧ 파괴적 live e2e의 게이트
체계·SAFE provider·쿼터 금지 목록 승계.

### concierge export 소비 정렬(#672) n150 배포·live 검증

- **배포**: main(`c8a54dca`)을 표준 절차(노드 clone+rsync+로컬 빌드)로 재배포.
  alembic `0047` head, 컨테이너 4개 healthy, 공개 도메인 로그인 POST 200. prod
  dagster env에 `..._FEATURE_SYNC_ENDPOINT`/`..._FEATURE_CURSOR` override 부재
  확인 → 재배포만으로 `changes` 전체 재생 전환.
- **materialize 검증**: `feature_place_kor_travel_concierge_youtube` RUN_SUCCESS.
  producer ledger는 현재 upsert 1,430 / reject·tombstone 0 → 철회 전파 0건이
  정답(전파할 철회가 아직 없음). T-189 전 item 재발급으로 980건 재-render + 신규
  40건 적재(active 980→1,020, inactive 0). 평면 provenance 키 backfill 포함.
- **발견(사전 존재, #672 무관)**: ledger 1,430 중 410건이
  `provider_address_mismatch`(error·drop)로 **한 번도 적재된 적 없음** — 유효해
  보이는 국내 장소(해동용궁사 등) 포함. 검증 규칙 적합성 검토를 이슈 **#673**으로
  분리(역지오코딩 시군구명 vs provider 주소 문자열 대조 규칙).
- **live UI e2e(n150 prod, 저부하 per-file 배치)**: dagster-runs-roundtrip 3 passed ·
  providers-consistency 111 passed/1 failed · features-list 핵심(status/kind 필터)
  42 passed · features-detail 딥링크 25 passed — 총 **181 passed / 1 failed**.
  유일 실패는 제품 회귀가 아니라 `/ops/providers` 요약 배지의 i18n(영문→한국어)
  이후 미갱신 스펙 드리프트(`PROVIDER_BADGE_LABELS`) — 한국어 라벨(제공자/데이터셋/
  정책/실패)로 정정 후 해당 테스트 라이브 재실행 green. e2e CI 부재로 스펙 드리프트가
  머지됐던 사례(메모리 규칙 재확인). features-list/detail 전체 매트릭스(각 333/310
  테스트)는 n150 4코어 저부하 원칙에 따라 핵심 부분집합만 실행.

## 2026-07-14 (claude) — concierge export 소비 계약 정렬 (endpoint 기본 changes·provenance 평면 키·되돌리기 회귀)

사용자 지시 "concierge api 수정내용반영"으로, producer(kor-travel-concierge)의
2026-06-25~07-14 export 변경을 소비 측에 정렬했다. producer 7월 검수 개편
(T-160 soft-delete·T-165 grounding 회수·#202 되돌리기/제거 목록·#205 bulk)으로
`reject`/`tombstone` 발행과 **같은 후보의 upsert 재발행(되돌리기)**이 일상 흐름이
됐다. wire 계약(envelope·cursor·operation 3종)은 불변임을 producer diff
(`bec63ad..15cd214`)로 확인했다.

- **소비 갭 수정(핵심)**: 기본 sync endpoint `snapshot` → `changes`
  (`settings.kor_travel_concierge_feature_sync_endpoint`). `snapshot`은 active
  upsert만 반환해 제거 목록/검수 회수가 소비자에 영구 미전파 — 철회된 후보가
  공개 지도에 잔존한다. `changes`는 cursor 없이 시작하면 후보당 1행으로 압축된
  ledger 전체(upsert/reject/tombstone)를 sequence 순 재생 → full sync + 철회
  전파를 매 실행 멱등으로 만족. `snapshot`은 opt-in으로 유지(일회성 초기 적재
  검증용). n150은 endpoint override 미설정으로 추정(repo `.env.example`에 concierge
  항목 없음) — 배포 시 실제 env를 확인하고, override가 있으면 `changes`로 정렬한다.
- **provenance 평면 키**: producer 8720dda(6/25)의 `youtube.source_type`/
  `source_value`/`source_title`/`source_search_query`/`corrected_search_query`를
  `facility_info.youtube_source_*`로 노출(None이면 키 생략). nested pass-through와
  curated source rule(`{payload,kor_travel_concierge,youtube,source_title}`)은
  기존 동작 그대로.
- **되돌리기 라이프사이클 회귀 고정**: tombstone→`inactivate_features_by_source_entity_ids`
  →inactive 후 재-upsert가 provider self-heal(generic loader 복구)로 active
  복원됨을 concierge 경로 통합 테스트 3건으로 고정 — 동일 payload fast-path,
  변경 payload(새 source_record_key) 경로, `prevent_provider_reactivation` 차단.
  코드 수정은 불필요했다(generic loader가 이미 처리).
- **문서 미러**: `docs/etl/concierge-feature-etl.md` §3(endpoint 선택 기준·cursor
  미설정 전제), §4(provenance·T-189 행정코드 실데이터+schema_version), §5(되돌리기
  재활성화·producer 게이트 미러·rejection_reason은 소비 측에 저장되지 않음 명시·
  mid-run 수렴), §8(회귀 목록); `docs/external-apis.md` §3.13. producer GET 순수
  읽기(T-171 outbox)는 소비 폴링 비용 노트로 반영.
- **적대적 리뷰 1차 반영**(4관점 find + 2인 반증 verify, 사용자 지시로 이후 2인
  체제 축소): ① 문서 오류 정정 — "rejection_reason이 raw_data에 보존"은 거짓
  (비-upsert item은 bundle화 전 skip → SourceRecord 자체가 없음), §10 구 ADR-050
  '(+사유 기록)'에 미구현 주석. ② mid-run 검수 전이 역전 수정 —
  `kor_travel_concierge_latest_items`(후보별 마지막 관측 item 압축)를 asset 앞단에
  두어, changes 재생 도중 producer 되돌리기(re-sequence)로 같은 후보가 구 reject·신
  upsert로 공존해도 구 operation이 신 상태를 덮지 않게 함(+unit 2건). ③ stale 노트
  정정 — producer T-189(884dc7b, 2026-07-14 오전 머지)가 행정코드 실데이터
  (`legal_dong_code`/`sigungu_code`+유도 sido)·additive `schema_version`을 이미
  배송, 전 item payload_hash 재발급 → 다음 materialize에서 전 후보 재-render(신규
  평면 키 backfill 포함). 실코드→Address 반영+feature_id 불변 unit 1건 추가.
  ④ 여러 줄 assert의 무효 `# type: ignore` 위치 정정. ⑤ cursor 전제(FEATURE_CURSOR
  미설정) 배포 확인 문구를 §3/external-apis에 명시.
- **적대적 리뷰 2차 반영**(독립 리뷰어 2명·교차 배치, S1/S2 0·S3 6): ① asset
  압축 배선 asset-level 테스트 2건 신설(`test_concierge_assets.py` — 배선 제거/
  편측 적용 리팩터 시 빨간불). ② 되돌리기 문구 정정 — producer `reopen_candidate`는
  되돌리기·제거 복원 시 **즉시 tombstone**을 발행하고 재확정 시에만 upsert 재발행
  (재확정 전 inactive 유지가 정상). ③ sido 유도 규칙에 legal_dong 앞 2자리
  fallback 병기. ④ 통합/유닛 픽스처 정밀화 — `schema_version: 1` 추가,
  `source_title`을 접두사 없는 검색어 원문으로(producer `_source_title` 실동작).
  ⑤ resume 배포 체크에 `..._FEATURE_CURSOR` 부재 확인 병기. ⑥ E501 1건 정정.
  리뷰어 검증으로 T-189 이후 producer 커밋(T-190~T-173)의 export 계약 무변경,
  압축 "마지막 관측=최신" 전제(sequence 단조 전진·후보당 1행)도 확인됐다.

## 2026-07-14 (codex) — notice reconcile 제곱 비용 운영 재현·제거

- **운영 재현**: 0046 배포 후 KREX 실수집에서 asset step이 6분 넘게 진행되지 않았다. DB wait
  audit 결과 lock 대기가 아니라 약 9,700개 KREX entity를 대상으로 한
  `lineage_candidates` query가 계속 실행 중이었고, 동일 scope의 각 계보마다 동일 scope 전체를
  다시 찾는 lateral 비교를 확인했다.
- **근본 수정**: 동일 provider/dataset/type winner는 기존 `ranked` CTE 결과를 재사용한다.
  전역 lateral 비교는 호출 scope 밖의 primary lineage를 공유한 Feature 보호에만 남겨,
  cross-provider 생존 의미는 보존하면서 동일 scope의 제곱 탐색을 제거했다.
- **2차 운영 원인**: 최적화 배포 뒤 out-of-scope link 0건·lateral loop 제거를 확인했지만
  lifecycle UPDATE가 다시 5분을 넘었다. `feature.features`는 실제 1,029,113행인데 planner
  통계는 약 970행이고 `last_analyze`도 없었다. blocker/JIT가 아니라 잘못된 join plan이
  남은 병목이었다.
- **통계 복구**: 운영 read/rollback A/B에서 관련 table `ANALYZE` 전에는 `jit=off`도 120초
  timeout, 이후에는 동일 reconcile이 JIT on 1.4초·off 2.2초였다. Alembic 0047에 reconcile
  join table 통계 갱신을 추가해 수동 운영 조치로 남기지 않았다.
- **재발 경로 차단**: 2차 적대적 리뷰에서 6월 28일 n150 backup→staging restore→swap으로
  전환된 DB는 planner 통계가 복원되지 않았고 Alembic revision은 그대로라 migration도
  재실행되지 않는 직접 경로를 찾았다. 일반 restore와 n150 runner 모두 직후
  `vacuumdb --analyze-in-stages`를 필수화하고, 일반 swap 전 검증에서 `feature.features` 통계가
  없으면 실패하도록 수정했다.
- **검증**: SQL 구조 회귀 unit 2건을 추가하고 feature repository unit 14건, notice lifecycle
  PostGIS integration 23건, 변경 파일 Ruff와 strict mypy를 통과했다.
- **적대적 리뷰 2회**: 1차 `S1 0 / S2 0 / S3 1`에서 scope 세 차원의 정확한 `OR`와
  provider/dataset/entity type 단독 차이 회귀 검증이 부족하다는 지적을 반영했다. 차원별
  PostGIS 통합 3건을 추가한 뒤 2차 독립 리뷰는 `S1/S2/S3 0`으로 종료했다.
- **통계 보강 적대적 리뷰 2회**: 권한 부족 `ANALYZE`의 warning-only skip, 일반 restore와
  실제 n150 runner의 통계 미생성, session DB의 빈 table만 보던 migration test를 순서대로
  발견했다. table/database owner 권한 preflight, 두 restore 경로의 staged analyze, 0046 전용
  DB 256행의 0047 전후 `reltuples` 검증으로 수정한 뒤 두 독립 리뷰 모두
  `S1/S2/S3 0`으로 종료했다.

## 2026-07-14 (codex) — notice 반복 중복·오종료의 계보 상태 원천 수정

- **반복 원인**: notice 부재/해제를 각 실행의 scope-local 집합과 Feature ID 직접 갱신으로
  처리해, 같은 Feature에 연결된 다른 provider/dataset 계보의 현재 상태를 다음 실행이 알 수
  없었다. KREX bundle load와 reconcile도 서로 다른 transaction이라 부분 성공 시 중복·재노출이
  반복될 수 있었다.
- **영속 정본**: Alembic 0046에 scope별 `snapshot`/`event` mode, watermark/fingerprint와
  계보별 `present`/`changed_at`/`valid_until`을 저장했다. KREX는 과거/equal-conflict
  snapshot을 CAS로 거부하고 exact replay를 허용하며, KMA는 batch watermark가 아니라 계보별
  event 시각으로 발표·해제와 공급자 예정 종료를 적용한다. backfill 없는 계보는 `unknown`으로
  보수적으로 보존한다. 상태가 생긴 뒤의 손실성 0046 downgrade는 명시적으로 거부한다.
- **원자 적용**: 전역 transaction advisory lock 아래 bundle 적재, 상태 전이, 중복 정리,
  Feature 종료·재개를 한 transaction으로 묶었다. 모든 구조적 winner가 명시적 `false`일 때만
  마지막 winner 전이 시각으로 닫고, 다른 scope의 `true` winner는 재개방 근거로 사용한다.
- **적대적 리뷰 1차 반영**: load 전에 member를 동기화해 신규 lineage를 누락하던 순서, equal replay의
  self-heal 누락, cross-scope 마지막 종료 시각 대신 첫 시각을 쓰던 계산, out-of-scope
  `true`/`unknown`을 같은 재개방 근거로 취급하던 문제와 중복 JOIN을 수정했다. 같은 `false`의
  더 최신 event 또는 미래 예정 종료보다 이른 explicit lift가 materialized 종료 시각에 반영되지
  않던 양방향 drift도 차단했다.
- **적대적 리뷰 2차 반영**: 늦은 과거 KMA 발표의 다른 payload가 source current/Feature 본문을
  되돌리던 경로는 DB가 수락한 current-present bundle만 적재하도록 막았다. finite/open,
  `unknown` 혼합, 운영자 재활성화 방지, 실제 공개 전이 count와 정상 발표+동일 계보 해제 batch를
  경우표로 고정했다. KREX preflight는 equal watermark를 DB fingerprint CAS로 넘겼다. 두 리뷰
  모두 수정 후 재검토에서 S1/S2/S3 0건으로 종료했다.
- **영향도·검증**: codegraph `impact close_notice_features --depth 3`에서 48개 영향 symbol을
  확인하고 실제 직접 호출자는 client/KMA/tests로 재확인했다. core unit 1,259건, 외부 live
  `kor-travel-geo` 5건을 제외한 PostGIS integration 308건, Dagster 전체 262건, frontend Vitest
  78건을 통과했다. 변경 Python Ruff, core 102개/Dagster 21개 strict mypy, import-linter 4계약,
  frontend type-check·lint(기존 경고 2건, 오류 0건), Alembic single head를 통과했다.

## 2026-07-13 (codex) — 동일 provider payload 재등장 self-heal 보강

- **운영 재현**: n150 KREX 수집은 46건을 정상 반환했지만 그중 5건이 과거 중복 정리로
  soft-delete된 Feature에만 연결되어 공개 지도에서 보이지 않았다. 사용자 변경이나
  ``prevent_provider_reactivation`` override는 없었다.
- **근본 원인**: 동일 ``source_record_key`` 재수집 fast-path가 Feature 존재 여부만 확인해,
  원문이 변하지 않은 채 재등장한 provider Feature의 ``inactive + deleted_at`` 상태를
  복구하는 upsert를 건너뛰었다.
- **수정**: provider 소유 ``inactive`` 상태를 ``deleted_at`` 유무와 관계없이 1회 재활성화하고,
  사용자 요청 Feature와 재활성화 방지 override는 그대로 보호한다. notice snapshot reconcile도
  현재 feed의 soft-delete된 정본을 복구하며, 다중 primary 계보 Feature는 한 계보라도 winner면
  보존하고 active인 winner 계보만으로 종료·재등장을 결정한다.
- **검증**: 동일 payload 복구 후 다음 수집 no-op, 사용자/override 보호, notice 정본 복구·
  다중 계보 공개 read와 중복 정리를 포함한 관련 통합 33건·unit 12건과 Ruff·strict mypy를
  통과했다.

## 2026-07-13 (codex) — 고zoom Feature bbox PostgreSQL JIT 병목 수정

- **원인 확정**: 운영 중앙 서울 z12 tile을 읽기 전용
  ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)``로 재현했다. 실제 feature
  scan은 51건을 찾는 데 약 14ms였지만, notice 계보·weather 상관
  subplan의 높은 추정 cost가 JIT 78개 function을 컴파일해 약
  1.8초를 소모했다. 동일 query는 ``jit=off``에서 전체 20.2ms였다.
- **수정**: ``make_async_engine``에 후방 호환 optional ``server_settings``를
  추가하고 FastAPI engine에만 asyncpg ``server_settings={"jit": "off"}``를
  적용했다. Dagster/CLI는 배치 특성을 고려해 기본 JIT 설정을 유지한다.
- **live marker 회귀**: 첫 n150 E2E에서 API 목록은 1~2건인데 DOM marker가
  0개인 상태를 재현했다. GeoJSON ``setData`` 직후 예약한 조회가 worker tile
  교체보다 먼저 실행된 뒤, ``idle`` 재동기화가 제거되어 다시 조회하지 않는
  것이 원인이었다. 자체 source 완료 이벤트는 유지하고 ``idle`` fallback을
  복구했으며, mock E2E도 실제 Feature 좌표로 viewport를 이동한 뒤 검증한다.
- **영향도·검증**: codegraph ``impact make_async_engine --depth 2``로 127개
  영향 symbol을 확인했다. 기존 caller는 optional 기본값으로 동작을
  유지하고 API caller 하나만 설정을 넘긴다. engine 전달·API 정책 unit
  13건과 변경 파일 Ruff/strict mypy를 통과했다.

## 2026-07-13 (codex) — 지도 신선도 반복 장애 근본 수정·적대적 리뷰 2회

- **운영 원인**: n150에서 종료되지 않은 Dagster run 10개가 전역 동시 실행 슬롯을 모두
  점유해 OpiNet/KREX 예약 실행 수백 개가 대기했다. 여기에 notice 불완전 snapshot 수용과
  비직렬 reconcile, OpiNet 0건/전일·혼합 가격 성공 판정, scope를 무시한 targeted 전국 조회가
  겹쳐 공지 중복·재노출과 유가 미갱신이 반복됐다.
- **provider 수집 경계**: KREX notice는 strict envelope/pagination과 lineage 중복 검사를 거친
  동일한 2회 연속 snapshot만 적재하고, 부재 항목은 종료·재등장 항목은 재개 처리한다. KREX
  upstream envelope 검증은 `python-krex-api` PR #11에 먼저 반영·머지하고 본 저장소 pin을
  갱신했다. OpiNet은 raw/변환 0건을 실패시키고 실제 KST 당일 가격 전체 적재와 최신 관측일을
  cursor로 증명해야만 당일 성공을 합친다.
- **실행 복구**: Dagster run monitoring, provider별 pool·최대 실행 시간, KREX tick coalescing과
  PostgreSQL advisory lock을 결합했다. pool을 우회하는 targeted worker도 같은 DB lock을 쓰며,
  scope를 적용할 수 없는 OpiNet targeted update는 호출 전에 생략하고 cache target 신선도를
  잘못 전진시키지 않는다. KREX 10분 snapshot에서는 row별 reverse geocoding을 제거했다.
- **지도/UI**: AirKorea와 KMA marker를 violet 대기질/blue 날씨로 구분했다. OpiNet은 KST 기준
  전일 가격에 `과거 M/D`를 표시하고 단일·동시각 이력도 점으로 그린다. Feature tile fan-out과
  DOM marker 범위를 제한하고, 큐레이션 지도는 padded quantized bbox cache와 실제 viewport
  필터를 사용한다.
- **적대적 리뷰 2회**: 1차의 snapshot 순서·pagination·AirKorea SQL·canonical tie-break·
  큐레이션 경계·KST 자정 지적과, 2차의 provider별 timeout·asset pool 우회·OpiNet 0건/targeted
  quota/혼합 날짜·notice direct lookup·KREX geocoder/churn 지적을 모두 반영했다. 최종 전 diff
  재검토에서 S1/S2 잔여 지적은 0건이다.
- **로컬 게이트**: 외부 인증이 필요한 live marker를 제외한 전체 Python 1,555건, API 354건,
  Dagster 260건, frontend Vitest 78건과 marker 1건을 통과했다. Ruff, core/API/Dagster strict
  mypy, import-linter, OpenAPI all profile·admin/user 생성 타입 drift, frontend/marker type-check·
  build도 통과했다. 로컬 geo live 5건은 API key가 없는 상태에서 auth-required 서비스가
  `/v2/reverse` 400을 반환하는 기존 fixture 전제이며 n150 인증 환경에서 별도 검증한다.

## 2026-07-13 (codex) — 다중 관측·collection 큐레이션 구현·n150 검증

- **스키마/관측**: Alembic 0044에서 provider 자연 entity와 immutable payload record를
  분리했다. `source_links`는 Feature↔entity membership이 되고, Feature 단건·batch·admin
  상세는 entity별 현재 관측을 모두 반환하며 과거 payload는 별도 cursor 이력 API로 조회한다.
- **큐레이션**: Alembic 0045에서 theme/title/edition/source를 소유하는 collection과
  공식 membership item을 분리했다. item의 `feature_id`는 nullable이며, 기존 Feature와
  안전하게 매칭하지 못한 공식 항목도 장소명·주소 hint·원천 안정키를 잃지 않고 저장한다.
- **API/UI**: Feature별 grouped public API, collection 상세, admin 수동 입력·편집·archive,
  CSV 양식 다운로드·dry-run·원자적 멱등 import를 구현했다. Feature 지도·목록·상세와 admin
  상세는 같은 Feature의 여러 회차 큐레이션과 여러 provider 현재 관측을 배열로 모두 표시한다.
- **공식 데이터**: 한국관광 100선 2개 회차, 국가유산 방문 캠페인, 2026 수목원·정원
  스탬프투어, 등대 스탬프투어 CSV를 `resources/curations/`에 추가했다. 공식 462개 항목을
  복합 장소 membership 486행으로 보존한다. repo CSV의 사전 확정 연결은 217행이고,
  n150 기존 Feature resolver까지 적용한 실제 적재 결과는 연결 225행·미연결 261행이다.
- **카테고리**: `01050400`(`관광 > 자연명소 > 등대`)과 marker icon을 추가했다. 박물관 등
  등대가 아닌 stamp point에는 등대 category를 제안하지 않는다.
- **n150 prod**: 747MB custom-format 사전 dump를 생성·검증한 뒤 Alembic
  `0043_weather_history_idx`에서 `0045_curation_collections`까지 자동 migration했다. map 서비스
  4개 기동, API/UI/Dagster health, 공개 로그인 GET/POST 200 + Set-Cookie, 오답 401을 확인했다.
- **실데이터 검증**: collection 19개·membership 486개, 한국관광 두 회차 중첩 Feature 40개,
  지정 Feature의 `data.go.kr-standard`/`python-visitkorea-api` 관측 2개를 DB와 REST에서 확인했다.
  공식 CSV 5종의 두 번째 dry-run은 모두 `inserted=0`, `updated=0`, `removed=0`이었고,
  prod Playwright는 CSV 반영·등대·admin 상세·지도 marker·목록·Feature 상세·관측 이력 4건을 통과했다.
- **게이트/리뷰**: 비통합 Python 1,761 passed(1 skipped), PostGIS 286 passed, frontend Vitest
  62 passed, route-mocked Playwright 35 passed, prod live Playwright 4 passed다. CI 단위 coverage는
  `curation_repo.py` 99.55%, 전체 80.44%(1,255 passed)로 복구했다. 최종 적대적 리뷰에서 찾은
  공개 hidden/deleted 관측 이력 노출, CSV `int4` overflow, 0044 손실성 downgrade를 모두
  차단했다. 파일 전체 CSV 오류의 UI 반영 차단과 ordinal 0 보존까지 보완해 남은 HIGH/MEDIUM/LOW
  지적은 0건이며 게시 PR은 #666이다.

## 2026-07-13 (codex) — concierge 소비자 키를 DB read scope 계약으로 전환

- **소비 계약**: `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`를 concierge static
  `API_KEYS` 공유값이 아니라 외부 소비자용 DB `read` scope 키로 정의했다. fetcher는 기존처럼
  `/api/v1/features/{snapshot|changes}`와 `X-API-Key` header만 사용한다.
- **resource metadata**: provider source env `API_KEYS` 매핑을 제거하고, 설정 설명·guard 메시지·
  resource 테스트를 read 키 발급 모델로 정렬했다.
- **회전 계약**: Concierge scope migration → 새 read 키 발급 → kor-travel-map secret 교체·재시작 →
  snapshot/changes 다중 page·cursor 불변식과 내부/write 403 → BFF/operator static admin overlap 회전 →
  구 키 폐기 순서를 문서화했다. 실제 키 값·길이·digest는 기록하지 않는다.
- **n150 검증**: Python 3.11 일회성 컨테이너에서 core/lint 1,169개, API 331개, Dagster
  220개 테스트를 통과했고 Dagster 1개는 환경성 skip이었다. 전체 Ruff, main/API/Dagster strict
  mypy, import 계약, prod 문서 redaction 검사도 통과했다. live smoke는 prod 전환 단계에서 수행한다.

