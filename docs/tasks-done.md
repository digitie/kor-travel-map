# tasks-done.md — 완료/아카이브 task 이력

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

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

## Admin ops-live 인증·무효화 완결 (2026-07-17, `T-ADM-C7A`)

- [x] **T-ADM-C7A — same-origin 실시간 갱신 경계를 완결.** 로그인 session과
  `Origin`·Fetch Metadata를 모두 검사하는 ticket BFF, HMAC 서명 subprotocol ticket, DB nonce
  단일 소비와 60초 연결 lease를 구현했다. 없음·변조 ticket은 `4401`, handshake 전 만료는
  data frame 없이 `4408`로 닫으며 공유 secret은 local launcher와 API container에서 앞뒤
  공백 없이 32자 이상이어야 기동한다.
- [x] **transaction-coupled invalidation과 복구 상태 모델 고정.** Alembic 0055로
  `ops.ops_live_ticket_claims`와 `ops.ops_live_topic_revisions`를 추가했다. provider 상태·정책,
  schedule override·audit·claim resolution, integrity issue·POI cache target 변경을 원본
  transaction과 함께 topic revision에 반영하고 pipeline/datasets canonical query key를
  무효화한다. malformed·비단조 frame은 오염 socket을 폐기하고 새 ticket/socket에서 exact
  `replace`를 다시 보낸다. 연속 두 번 실패는 standby, 세 번째부터 polling fallback으로 전환한다.
- [x] **적대 리뷰와 로컬 gate 완료.** backend/DB/security와 frontend 상태 모델 리뷰어가 제품
  변경을 테스트 전에 승인했다. 정확한 최종 제품 SHA에서 root unit 1,411건, API 484건,
  실제 PostGIS migration/schema 14건과 C7A 집중 9건, frontend unit 185건, Ruff, strict mypy
  115+52파일, import 계약 4/4, OpenAPI/admin/user type drift, base·host Compose rendering과
  production build를 통과했다. 실제 browser의 close code·재연결은 최종 `T-ADM-C7` n150
  파괴적 live E2E에서 검증한다.

## Admin legacy surface clean-cut (2026-07-17, `T-ADM-C6b`)

- [x] **T-ADM-C6b — 운영 표면을 pipeline/datasets 두 화면으로 clean-cut.** legacy REST
  operation 28개와 `/ops/import-jobs*`, `/ops/providers`, `/admin/features/update-requests*`,
  `/admin/dagster`, `/etl` UI를 redirect·호환 shim 없이 삭제했다. canonical
  `/v1/ops/pipeline/*`, `/v1/ops/datasets/*`, 관측 read와 public provider read 2종만 유지했다.
- [x] **provider credential과 BFF 런타임 경계 분리.** API/frontend는 process별 env allowlist와
  package-scoped API env를 사용하고 provider 비밀은 Dagster에만 둔다. bridge mode는 전용
  control-plane network의 frontend 고정 주소 `/32`만 신뢰하며 host mode는 loopback으로
  덮어쓴다. root raw env 예제의 inline comment와 API package secret 중복은 fail-closed한다.
- [x] **계약·검증 완료.** 두 독립 적대 리뷰어가 최종 제품 및 테스트 보강을 S1/S2/S3 0건으로
  승인했다. root unit 1,410건, API 450건, Dagster 457건(1 skip), 실제 PostGIS 92건,
  frontend unit 142건, Ruff, strict mypy 115+51파일, import 계약 4/4, OpenAPI/admin/user type
  drift, base·host Compose rendering과 production build를 통과했다. live UI는 최종
  `T-ADM-C7` n150 gate에서 검증한다.

## Admin datasets 이슈 의미 통일 (2026-07-17, `T-ADM-C7B-720`)

- [x] **T-ADM-C7B-720 — dataset/provider open issue를 단일 행 의미로 통합.** `이슈 있음`
  필터·정렬·행 badge는 dataset 또는 provider open issue가 하나라도 있으면 선택한다. 요약은
  dataset을 `(provider,dataset)`, provider를 provider 단위로 중복 제거해 scope 반복 행을
  한 번만 집계한다.
- [x] **네 소유 조합과 frontend-only 경계를 고정.** provider-only, dataset-only, both,
  neither를 unit과 mocked E2E 계약에 추가했고 API·OpenAPI·DB는 변경하지 않았다. 두 독립
  리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했으며 unit 5건, type-check, lint와 production
  build를 통과했다. #720은 본문 수용조건을 재확인한 뒤 2026-07-18 닫았다.

## Admin 통합 화면 링크 정본화 (2026-07-17, `T-ADM-C6a`)

- [x] **T-ADM-C6a — 존치 화면과 API 링크를 두 운영 화면으로 재배선.** import job,
  update request, load batch, provider/dataset과 홈·Feature·큐레이션·로그의 링크를
  `/ops/pipeline`·`/ops/datasets`로 전환했다. provider/dataset/scope와 canonical root
  identity를 보존하고 caller query가 엔티티 identity를 덮어쓰지 못하게 했다.
- [x] **선택 조회와 실시간 갱신 계약 보강.** load batch와 parent UUID deep link는 전용
  partial index에서 member를 먼저 선택한 뒤 root component를 확장한다. ops-live query key,
  import job HATEOAS와 live scenario catalog도 두 통합 화면 계약으로 맞췄다.
- [x] **적대 리뷰·회귀 검증.** 두 독립 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했다.
  root unit 18건, API 140건, 실제 Postgres 통합 22건, frontend unit 27건과 Ruff, strict
  mypy 115파일, import 계약 4/4, type-check, lint, production build를 통과했다.

## Admin pipeline 통합 화면 (2026-07-17, `T-ADM-C5`)

- [x] **T-ADM-C5 — `/ops/pipeline` 실행·스케줄 조작 단일 표면.** canonical root 기준
  상태 strip·타임라인·Dagster run·전역 event·schedule audit/claim·feature update 요청을
  한 화면에 통합했다. provider/dataset pair와 request root/projected job을 분리해 표시하고,
  URL 상태·1페이지 자동 갱신·신규 실행 배지·degraded 경계를 일관되게 적용했다.
- [x] **멱등·동시성·불확실 결과 폐루프.** Alembic 0054로 feature update idempotency와
  schedule command audit/active claim/resolution ledger를 append-only로 고정했다. DB clock 기반
  lease와 advisory lock, 120초 operation timeout, mutation guard를 사용하며 응답 유실 뒤에도
  동일 command/request를 복원한다. mutation 이후 결과가 불확실하면 claim을 보존하고 운영자가
  audit 근거로 명시 해소하기 전 재실행하지 않는다.
- [x] **적대 리뷰와 회귀 검증.** 의미 있는 최종 제품 커밋과 session 복원 변경을 backend/UI
  적대 리뷰어 2명이 각각 재검토해 S1/S2/S3 0건으로 승인했다. append-only cleanup은 테스트
  transaction에만 제한하고 실제 trigger 검증은 유지했다. #693·#716의 지적을 구현과 회귀
  테스트로 흡수했다.

## Admin datasets 통합·scope 폐루프 (2026-07-17, `T-ADM-C45X-B`·`C4R`·`C4`)

- [x] **T-ADM-C45X-B — sync_scope·active request 백엔드 정본.** PR #701에서 direct
  update의 typed scope·dispatch intent, active 유일성·멱등 재사용, KMA exact target과
  scope별 cursor/failure를 완결하고 병합했다.
- [x] **T-ADM-C4R / C45X-U — C4 UI 소비 계약과 scope 폐루프.** PR #698에서
  datasets projection과 pipeline history를 exact 3원 scope로 정렬하고, dataset-wide 기본
  state와 orphan/stale scope를 구분했다. active `external_system:*` 첫 실행, 기존 active
  operation 재사용 링크, 정책·preview·freshness·schedule degrade를 fail-closed UI에 연결했다.
- [x] **T-ADM-C4 — `/ops/datasets` 통합 화면.** 검색·상태 그리드, URL/history 기반 drawer,
  정책 편집, fixture preview, 지금 갱신과 scope별 이력을 한 화면에 구현했다. 두 적대 리뷰어의
  최종 판정은 S1/S2/S3 0건이고 mocked production UI E2E 47건이 통과했다. #684/#686/#712의
  운영 종결은 `T-ADM-C7` n150 live 증거 뒤 수행한다.

## C3e n150 운영 종결 (2026-07-16, `T-ADM-C3e-I2`)

- [x] **T-ADM-C3e-I2 — migration·sensor/cursor·4종 동일-root·live UI 검증.** 배포 전
  pg_dump(259,608,395 bytes, SHA-256
  `0c01693808a0cc94dcbe1dce9a04c5996364c642ac4fa3f1df77d87c08667167`) 뒤 n150 prod에
  0051/0052를 일방향 적용했고 Alembic single head와 0048 재수렴 `updated=0`, 예상 밖 exact
  untyped `0`, request validation/identity/quarantine 불일치 `0`을 확인했다. tracking sensor
  8개와 update sensor 2개는 모두 RUNNING이며 reconciliation cursor는 maintenance anchor
  `storage_id=5160`에서 `5175`로 전진하고 최근 5개 tick이 관측 오류 0으로 끝났다. 스케줄은
  기존 snapshot인 34 RUNNING·3 STOPPED로 정확히 복원했다. 일정·수동·갱신·standalone import가
  datasets/pipeline 상세에서 같은 `(kind,id)` root를 반환했고 모두 terminal이다. 공식 Playwright
  1.60.0 컨테이너로 provider consistency, Dagster/update request, offline upload, import action,
  home dashboard를 실제 prod에 실행해 138건 통과·전제 미충족 2건 skip을 기록했다. 최종 DB와
  Dagster active run은 0이고 이슈 #679에 전체 증거를 남긴 뒤 완료로 닫았다.

## C3e B2→B3 실제 PostGIS 교차 회귀 (2026-07-16, `T-ADM-C3e-I1`)

- [x] **T-ADM-C3e-I1 — public wrapper 결과와 terminal sensor의 단일 lifecycle 검증.** 실제
  migration 0001→0052를 적용한 PostGIS에서 단일 provider wrapper 성공과 MCST 부분 성공·실패를
  B2 public 경계로 기록한 뒤 B3 terminal record로 닫았다. 단일 성공은 root/member 완료·진행률
  100·engine 시각과 수동 trigger를, MCST 실패는 13개 exact pair의 identity·job·완료 시각 보존,
  active pair만 실패 처리, redacted attempt event 보존과 raw 오류 비노출을 고정했다. 두 적대
  리뷰어의 최종 판정은 각각 S1/S2/S3 0건이다. focused 32건, live 제외 전체 1,902건(5 deselected),
  Ruff, strict mypy 136개 소스, import 계약 4/4를 통과했다. raw 전체 실행에서는 외부
  `kor-travel-geo` reverse endpoint가 HTTP 400을 반환해 live 5건만 실패했으며 C3e seam 실패와
  분리했다. n150 migration·sensor/cursor·4종 동일-root 증거와 이슈 #679 종결은
  `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster provider guard·public wrapper tracking (2026-07-16, `T-ADM-C3e-B2`)

- [x] **T-ADM-C3e-B2 — authoritative provider guard와 exact-pair tracking.** 모든 live
  provider resource가 I/O 전에 실제 Dagster run record의 job·asset selection·run config·tag와
  B1 registry identity를 대조하고, 각 public asset/KMA wrapper가 마지막 ensure와 자기 exact pair
  완료를 소유하게 했다. MCST는 nullable pair-completion callback으로 부분 성공을 보존하며 direct
  `FeatureUpdateAssetRunner`는 tracking 0을 유지한다. 취소 marker·identity drift·naive timestamp는
  fail-closed하고, 비기본 KNPS point/geometry 설정은 provider fetcher와 asset resource가 같은
  `model_copy` snapshot을 사용한다. 적대 리뷰어 2명의 최종 판정은 S1/S2/S3 0건이다. focused
  260건(1 skip), 실제 PostGIS canonical operation 30건, Dagster 전체 428건(1 skip), main unit
  1,366건과 Ruff·strict mypy 136개 소스·import 계약 4/4를 통과했다. B2→B3 실제 terminal DB
  연쇄는 `T-ADM-C3e-I1`에서 완료했고, 이슈 #679 종결과 n150 증거는 `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster run sensor·양방향 복구 (2026-07-16, `T-ADM-C3e-B3`)

- [x] **T-ADM-C3e-B3 — active/terminal sensor·양방향 reconcile.** QUEUED부터
  CANCELED까지 7개 run-status sensor와 NOT_STARTED/MANAGED·누락 event를 복구하는 30초
  periodic sensor를 기본 RUNNING으로 등록했다. public Dagster insertion cursor는 300초
  settle lag와 연속 settled prefix를 사용하고, DB active-root keyset은 마지막 page에서 처음으로
  wrap한다. cursor anchor 삭제·변조, 비어 있지 않은 storage의 무cursor 시작, scan/list/write
  실패는 fail-closed하며 cursor를 전진시키지 않는다. terminal trigger·selection 불변식 위반은
  같은 transaction에서 root/child를 `tracking_invariant`로 닫는다. 적대 리뷰어 2명 최종
  S1/S2/S3 0건 승인 뒤 focused 101건과 수정 후 52건, 실제 PostGIS 27건, Dagster 전체
  342건(1 skip), main unit 1,366건, Ruff·strict mypy·import 계약 4/4를 통과했다.

## C3e Dagster operation registry (2026-07-16, `T-ADM-C3e-B1`)

- [x] **T-ADM-C3e-B1 — immutable registry·run identity.** 33개 feature-load job과
  53개 exact provider/dataset 선택지를 canonical manifest와 내용 기반 digest version으로
  고정했다. KNPS launch snapshot, fileData 4종의 두 resource config, MCST 13-pair identity,
  trigger 분리와 exact coalescing을 schedule/admin/projection 경계에 연결했다. 등록 job의
  누락·교차 identity는 fail-closed하고 비등록 job만 panel-only로 유지한다. 적대 리뷰 2인
  S1/S2 0건 승인 뒤 main unit 1,366건, API 513건, Dagster 308건(1 skip), focused 159건,
  Ruff·strict mypy·import 계약 4/4를 통과했다. 실제 Dagster context의 override guard와
  provider tracking은 B2로 이관했다.
## C3e REST canonical 교차 통합 (2026-07-16, `T-ADM-C3e-C`)

- [x] **T-ADM-C3e-C — datasets/pipeline 실제 DB·REST 교차 증거.** 실제 migration을 적용한
  PostgreSQL에 canonical operation을 commit하고 요청별 새 FastAPI session으로 datasets grid/detail과
  pipeline 2페이지가 같은 root·member·상태·engine 시각·projected job을 반환함을 고정했다.
  exact-pair decoy, 인증, cursor, schedule, slash·예약문자 복합키도 검증한다. detail/preview/
  refresh-policy는 고정 path와 `provider`/`dataset_key` query로 clean-cut 전환했으며 OpenAPI와
  admin 생성 타입을 함께 갱신했다. 적대 리뷰 2인 S1/S2 0건 승인 뒤 API 503건, router 13건,
  실제 DB 통합 1건, Ruff·strict mypy·OpenAPI/type drift·frontend type/lint gate를 통과했다.
## C3e 실행 재분할 문서화 (2026-07-16, `T-ADM-C3e-D2`)

- [x] **T-ADM-C3e-D2 — C3e-B 복구 감사와 병렬 PR 재분할.** Claude Code의 branch,
  reflog, stash, remote와 고아 worktree blob을 감사해 C3e-B 고유 구현이 없음을 확인했다.
  B를 registry/run identity, guard/wrapper/MCST, sensor/reconcile의 B1/B2/B3 PR로 나누고,
  A2에서 제품 구현이 끝난 C는 실제 DB/FastAPI REST 교차 통합 증거 PR로 축소했다. 문서-only
  변경이므로 사용자 지시에 따라 추가 적대 리뷰 없이 rebase·CI green 뒤 병합한다.

## Admin ops 통합 기반 (2026-07-14~15, `T-ADM-C1`~`C3c`)

- [x] **T-ADM-C1 — 플랜·ADR-064·task 분해.** Dagster job/provider 운영 표면을
  `/ops/pipeline`과 `/ops/datasets` 두 페이지로 통합하는 정본 계획과 병렬 PR 경계를 확정했다.
- [x] **T-ADM-C2 / C2R — datasets backend와 차단 계약 보강** (PR #676/#688,
  issue #678). 그리드·상세·refresh policy·typed preview, 서버 계산 freshness,
  schedule 시각 분리, canonical latest batch, provider/dataset 이슈 분리, orphan mutation
  차단을 완결했다.
- [x] **T-ADM-C3 — pipeline backend** (PR #677). overview·root execution·detail/cancel·
  event·Dagster run·schedule·request API와 `dagster_run_id` 실컬럼을 추가했다.
- [x] **T-ADM-C3a — 공용 application service/schema 추출** (issue #682, PR #687).
  삭제 예정 router의 private symbol 의존을 제거하고 신·구 표면의 공용 경계를 만들었다.
- [x] **T-ADM-C3b — canonical root projection** (issue #679, PR #689). recursive lineage,
  nearest request owner, standalone partition, deterministic projected job과 keyset cursor를
  구현했다. C3e가 typed identity 정본으로 후속 강화한다.
- [x] **T-ADM-C3c — Dagster run detail/failure 계약 이식** (issue #681, PR #687/#690).
  opaque event cursor, failure 구조, 404/502/503 RFC7807과 공용 query service를 완결했다.

## C3e canonical operation 영속화 (2026-07-15, `T-ADM-C3e-A1`)

- [x] **T-ADM-C3e-A1 — 0051·operation repository frozen 계약**.
  `ops.import_jobs`에 exact pair·trigger·registry version·raw Dagster status와 feature operation
  구조 제약·partial index를 추가하고, payload를 읽지 않는 보수적 backfill을 적용했다. frozen
  repository/client lifecycle, direct writer identity, feature operation의 authoritative engine 시각,
  C3d run-backed queued 취소 경계를 적대 리뷰 2회와 전체 로컬 gate로 고정했다. 상세 구현·검증
  기록은 `docs/journal.md`와 `docs/resume.md`의 2026-07-15 A1 항목을 따른다.

## C3e 공용 projection·request/job 단일 정본 (2026-07-16, `T-ADM-C3e-A2`)

- [x] **T-ADM-C3e-A2 — canonical root/exact-pair projection과 0052 clean-cut.**
  pipeline/grid/detail/overview를 같은 cycle-safe root와 typed pair member에 연결하고,
  feature update request lifecycle을 canonical import job 한 행으로 통합했다. request/job 양방향
  1:1, 6종 scope·typed filter·update policy, 격리 component, 전용 writer/CAS를 DB와 Python에서
  함께 강제한다. event 감사 부분 index와 statement-level live revision clock을 추가했으며,
  두 적대 리뷰어 승인 뒤 전체 Python/DB/frontend gate와 n150 mocked E2E 501건을 통과했다.

## C3e canonical operation 문서 gate (2026-07-15, `T-ADM-C3e-D`)

- [x] **T-ADM-C3e-D — canonical provider operation 문서 계약** (#679, PR #696).
  Claude Code worktree의 설계 기록을 C3d 정본 위에서 복구하고, Dagster run root 한 건과 exact
  provider/dataset child, retry/terminal 소유권, frozen client 계약, 0051 migration·backfill/down,
  C3d queued run-backed 취소, 공용 projection·mixed-version 순서를 구현 전에 고정했다. 적대 리뷰
  2인의 S1/S2 0건 승인과 CI green 뒤 문서 PR을 병합해 C3e-A1/A2/B/C의 compile target으로 삼았다.

## Pipeline 계층형 취소 완결 (2026-07-15, `T-ADM-C3d`)

- [x] **T-ADM-C3d — 실제 계층형 취소·Dagster terminate** (#680, PR #695).
  C3b canonical root의 frozen scope, base marker, 정규화 attempt/member/run, run별
  at-most-once terminate reservation, crash resume, authenticated audit, marker CAS와
  `Retry-After`/RFC7807/OpenAPI/admin types를 완결했다. pre-start generation 복구,
  browser invalidation/live E2E 계약, production bound-client DB 탈출 차단까지 하위
  `T-ADM-C3d-P1R`·`R2A`·`R2B`·`R2C`로 반영했다. 두 적대 리뷰와 로컬 전체 gate,
  GitHub Actions 8/8 green 뒤 merge commit
  `28dfe224dee9c7a09775293b37be6795edb92651`로 main에 반영했고, 수용 증거를 남긴 뒤
  이슈 #680을 닫았다.

## 최근 2일 Claude Code PR 사후 적대 리뷰 (2026-07-15, `T-ADM-RV-CLAUDE-2D`)

- [x] **T-ADM-RV-CLAUDE-2D — 닫힘 여부와 무관한 Claude Code PR 상세 리뷰·이슈화.**
  공동작성 trailer와 Claude session 근거가 있는 PR #672, #674, #675, #676, #677,
  #683, #691, #692를 각각 상세 리뷰했다. review-fix 전용 PR은 없었고, Claude 근거가 없는
  #664, #666~#671, #687~#690은 제외했다. pipeline UI 상태 격리·sensor fail-closed·URL
  복원은 #693, live UI E2E 의미 단언은 #694로 묶어 새 이슈를 만들었다. 기존 #682,
  #684, #685, #686에는 재현 근거와 보강 수용 기준을 남겼으며, #687로 완료되지 않은
  actor/problem/schedule 범위 때문에 #682를 다시 열었다.

## 지도 신선도·provider 실행·고zoom 성능 반복 장애 수정 (2026-07-13, `T-231`)

- [x] **T-231 — notice/OpiNet 반복 장애 근본 수정과 지도 응답성 보강.** KREX notice를
  strict pagination·lineage 검증을 거친 동일한 2회 연속 snapshot으로만 반영하고, 부재 공지
  종료·재등장 복원·공개 active 필터를 일관 적용했다. Dagster 고착 run 슬롯 고갈은 monitoring,
  provider pool·DB advisory lock, KREX tick coalescing으로 차단했다. OpiNet raw/변환 0건과
  전일·혼합 가격 성공 오인, scope를 무시한 targeted 전국 재조회도 실패/skip/cursor 계약으로
  교정했다. AirKorea/KMA marker, 과거 유가 표기·단일 시계열 점, Feature/큐레이션 고zoom
  로딩을 함께 보강했다. KREX upstream 수정은 `python-krex-api` PR #11에 선반영했다. 적대적
  리뷰 2회 후 S1/S2 잔여 0건이며 전체 로컬 Python/API/Dagster/frontend/OpenAPI 게이트를
  통과했다. PR merge·n150 운영 복구와 live E2E 인수 결과는 `docs/resume.md`의 다음 작업으로
  추적한다.

## 큐레이션 CSV·다중 관측 aggregate 계약 (2026-07-13, `T-230`)

- [x] **T-230 — 큐레이션 CSV·다중 source/연도 aggregate 계약 구현** (#665, PR #666).
  provider entity/current record와 immutable observation 이력, 회차형 collection/item schema를
  Alembic 0044/0045로 구현했다. admin 수동 입력·CSV 양식·preview·원자적 멱등 import와
  지도·목록·상세·REST의 다중 관측/다중 membership 표시를 추가하고 등대 category도 등록했다.
  공식 CSV 5종은 collection 19개·membership 486행이며, n150 기존 Feature에 225행을 연결하고
  261행은 원천 안정키·장소명·주소 hint를 가진 미연결 item으로 보존했다. 전체 로컬 게이트와
  적대적 리뷰(HIGH/MEDIUM 잔여 0), n150 Alembic 0045, 로그인, 실제 DB/REST, prod live Playwright
  4건, 동일 CSV 두 번째 dry-run 변경 0건을 통과했다. 정본 계획·결과는
  `docs/reports/t-230-curation-multi-observation-plan.md`다.

## UI live e2e 재실행 (2026-06-21, `T-UI-E2E-LIVE-20260621`)

- [x] **T-UI-E2E-LIVE-20260621 — UI live e2e 재실행 + 하네스 안정화.**
  live stack 기준 전체 Playwright e2e를 재실행했다. 1차는 629 passed / 1 failed였고,
  실패는 `home-density-matrix.spec.ts`의 공통 `gotoHome()`이 full `load` 이벤트를 기다리다
  live static asset 지연에 걸린 하네스 문제였다. `waitUntil: "domcontentloaded"`로 조정 후
  `npm run type-check:e2e`, 실패 케이스 단독 재현, 리베이스 후 현재 브랜치 별도 live stack에서
  전체 live UI e2e **631 passed**로 닫았다.
  정본 `docs/reports/ui-live-e2e-rerun-2026-06-21.md`.

## maplibre-vworld-js dependency 제거 (2026-06-18, `T-MAP-VWORLD-04`)

- [x] **T-MAP-VWORLD-04 — `maplibre-vworld-js` dependency 제거** (#475).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin web 지도 경계를
  `vworld-map-core`/`vworld-map-web` 모델에 맞췄다. admin frontend와
  `@kor-travel-map/map-marker-react`에서 `maplibre-vworld` package dependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언을 제거하고,
  `package-lock.json`에서 `maplibre-vworld` 및 전용 transitive를 제거했다.
  `VWorldMapView`는 maxZoom clamp, redacted error logging, stable marker click
  callback을 보강했다. 검증: admin type-check, marker typecheck/build,
  admin vitest 27 passed, ESLint 0 errors(기존 warnings 6), Next build, Windows
  Playwright 지도 e2e 5 passed. 정본 리포트:
  `docs/reports/maplibre-vworld-js-dependency-removal-2026-06-18.md`.

## OpenAPI 에러 본문 RFC7807 problem+json 기계 계약 보강 (2026-06-18, `T-452`)

- [x] **T-452-openapi-problem-json — OpenAPI 4xx/5xx problem+json 선언.**
  생성 `openapi.json`/`openapi.user.json`이 에러 응답을 `422 application/json`
  (`HTTPValidationError`)로만 선언하던 under-spec(#452/#444 잔여)을 해소했다. `create_app`의
  custom `app.openapi()`가 모든 operation의 4xx/5xx·`default` 응답을 `application/problem+json`
  (`ProblemDetail`/`ProblemDetailError`, `code`·`request_id` 확장 멤버 포함)으로 선언하고, FastAPI
  자동 422도 problem+json으로 대체하며 orphan 검증 schema를 제거한다. 핸들러별 `responses=`
  대신 중앙 핸들러(`_error_response`)와 대칭인 중앙 openapi 주입을 택했다. 산출물 재생성
  (`export_openapi.py --profile all`) + frontend/user-client `gen:types` 동반, `--check` drift
  gate·`gen:types:check`로 고정. 정본 `docs/architecture/rest-api.md §1.5`,
  회귀 테스트 `test_export_openapi.py::test_openapi_declares_rfc7807_problem_json_error_responses`.

## admin TanStack 테이블 이행 후속 종결 (2026-06-18, `T-ADMIN-TANSTACK`)

- [x] **T-ADMIN-TANSTACK — admin UI TanStack 테이블 이행 후속 종결.**
  이행 본체는 PR #454(정본 `docs/reports/admin-tanstack-table-migration-2026-06-17.md`). 잔여
  2건이 모두 해소되어 종결한다.
  - **(a) backend-의존 e2e 라이브 실행 ✅**: 라이브 Docker 스택(api :12701 / dagster :12702 /
    migrated frontend :12705)에서 전 spec 실행 → PR #458/#459 후 **57 passed / 0 failed**
    (2026-06-17, `docs/resume.md`). admin-ops/curated/features-new 포함 backend-의존 표면 무회귀
    확인. (사용자 결정: 이미 검증됨 → 재실행 생략.)
  - **(b) bulk 동작 정책 가드 ✅**: main에 이미 구현됨 — dedup bulk는
    `enableRowSelection` pending-only + `decideBulk` 방어적 필터로 **완료 review 재결정 차단**,
    curated bulk archive는 `window.confirm("선택한 N건을 보관할까요?")` **일괄 confirm**.
    enrichment는 단일 행 pending-only(bulk 표면 없음 — 가드 불필요).

## 외부/보류 task won't-do 종결 (2026-06-18)

사용자 지시로 아래 task를 **진행하지 않음(won't-do)** 으로 종결했다. 산출물 없이 백로그에서만
정리한다(`docs/tasks.md` 외부 추적 섹션 제거 + 보류에서 T-103 제거).

- [x] **T-019 — PinVi Kakao Maps → maplibre-vworld 교체 / SPEC supersede 추적** (won't-do, PinVi repo 외부).
  본 저장소 책임은 ADR-026/043 reference와 `@kor-travel-map/map-marker-react` 계약 유지로 한정한다.
- [x] **T-210b — PinVi 문서 supersede** (won't-do, PinVi repo 외부).
- [x] **T-210c — PinVi `apps/etl` 레거시 Dagster 이관/삭제** (won't-do, PinVi repo 외부).
- [x] **T-210d — PinVi httpx OpenAPI client 신규** (won't-do, PinVi repo 외부).
  PinVi-side 정렬 작업으로 본 저장소는 OpenAPI 계약(정본 `docs/integration-map.md`)만 책임진다.
- [x] **T-103 — streaming ETL(Kafka/Redpanda) 대응** (won't-do).
  `docs/architecture/performance.md §9.4` 기준 — 초 단위 latency를 실제로 요구하는 provider 증거가
  없어 도입하지 않는다. 필요 신호가 생기면 신규 task로 재개한다.

## maplibre-vworld-react 지도 전환 (2026-06-17, `T-MAP-VWORLD`)

- [x] **T-MAP-VWORLD-01 — 계획 및 Task 생성** (#465, PR #468).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin `features` 지도 전환 범위를
  정했다. 전체 외부 모노레포 vendoring 없이 필요한 `VWorldMapView`/React marker 모델만
  admin UI 내부에 얇게 이식하는 방향이다. 정본 계획은
  `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`.
- [x] **T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환** (#466).
  직접 `maplibre-gl` 인스턴스와 marker 배열을 관리하던 `features-client.tsx`를
  `VWorldMapView`/`VWorldMarker` 컴포넌트 모델로 전환했다. bbox 동기화, kind 필터
  refetch, marker/table 선택 상세 패널, VWorld key 미설정 fallback을 유지했다.
  Windows localhost forwarding이 실패하는 e2e 환경을 위해 `NEXT_ALLOWED_DEV_ORIGINS`
  기반 dev origin 추가 허용도 넣었다.
- [x] **T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정** (#467).
  PR #469 merge 후 main 기준으로 Windows Playwright 지도 e2e를 재실행했다.
  `features-map-interactions.spec.ts`는 **5 passed / 0 failed**였고 추가 수정할
  회귀는 없었다. 정본 리포트는
  `docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`.

## T-212e 후속 라이브 검증 (2026-06-14, `T-229`)

- [x] **T-229 — T-212e 후속 라이브 검증** (arm64 buildx만 잔여).
  T-225가 분리한 커버리지 갭을 실데이터(features 1,095,665)로 라이브 검증했다. T-212e
  데이터가 옛 claude postgres(15433)에 잔존 + 격리 복원본 `krtour_map_restore` 존재라
  복원 불필요했고, 운영 데이터 무손상 원칙으로 **복원본에만** 검증했다. **curated
  오버레이 완전 검증**: `curated_features_refresh` 4-asset RUN_SUCCESS → curated_features
  0→**86,341** 후보(테마 7종, MCST source 카운트 정합), admin API 실제 서빙, 사용자
  표면은 미선택 후보 숨김(선택 게이트), curated-themes/sources 200, tripmate-copy는
  선택 시 생성(0). `/metrics` 200, smoke breadth 전 표면 응답(200/정상404). AS-01/
  API-11/12 실데이터 해소. arm64 multi-arch buildx는 당시 환경 제약으로 검증하지 못했으나,
  2026-06-29 사용자 결정으로 추가 추적하지 않는다. codex 스택은 사용자 지시로
  강제종료 후 external-infra 재기동. 정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`.

## T-212e closure 재검증 (2026-06-13, `T-225`)

- [x] **T-225 — T-212e closure 재검증.**
  라이브 full reload 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 문서/코드 증거
  대조로 닫았다(인수기준 충족). 5개 차원 교차검증 + 각 gap 반증(서브에이전트 18).
  **T-212e closure 유효**: 실패 provider 6건 수정 전부 main 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 102,121, 이슈 #397/#407/#409 close + 보강 PR 머지,
  broken link 없음), identity는 #429가 리포트까지 재작성해 이미 post-rename,
  패키지 분리(#430)·#434 포트 재기준은 데이터 closure에 영향 없음. 착수 가정이던
  "구 이름 drift"는 실재하지 않았다. 남은 라이브 검증 커버리지 갭(curated 오버레이,
  Prometheus `/metrics`/arm64 buildx, smoke breadth)은 후속 **T-229**로 분리.
  정본 `docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

## 운영 배포 자동화 (2026-06-13, `T-108`)

- [x] **T-108 — 운영 배포 자동화 (pinvi T-108 이식).**
  pinvi 원문은 Odroid M1S + N150 16GB 양쪽, multi-platform Docker build,
  streaming replication을 포함했으나, 사용자 재지시에 따라 kor-travel-map에서는
  **streaming replication은 하지 않는다**. 본 저장소 범위는 N150 16GB(`linux/amd64`)와
  Odroid M1S(`linux/arm64`)에 같은 image tag를 배포할 수 있는 buildx 자동화로 닫았다.
  `scripts/docker-buildx.sh`, `npm run docker:buildx`, `.env.example`,
  `docs/deploy.md`, `docs/runbooks/docker-app.md`, ADR-056이 정본이다.

## 태스크 문서 정리 (2026-06-13, Codex)

- [x] **태스크 문서 전반 정리.**
  `docs/tasks.md`를 열린 `[ ]` task만 남기는 백로그로 축소하고,
  `docs/resume.md`를 현재 상태 + 다음 한 작업 중심으로 다시 정리했다.
  중복 완료 체크박스와 오래된 Sprint 2/3 미완료 표기가 현재 인수인계에 노출되지
  않도록 완료 묶음은 이 파일에 요약 아카이브한다.

## 패키지 정체성 / 메트릭 후속 (2026-06-13, `T-226`/`T-227`)

- [x] **T-226 — 배포명/임포트명 재정의: `kor-travel-map` / `kortravelmap`.**
  ADR-054와 `docs/package-identity-rename.md` 기준으로 public distribution
  `kor-travel-map`, Python import root `kortravelmap`, 권장 예시
  `import kortravelmap as ktm`, CLI `ktmctl`, DB `kor_travel_map`,
  Dagster metadata DB `kor_travel_map_dagster`, RustFS bucket/prefix
  `kor-travel-map` 계열로 clean cut했다. `T-226a` 문서 정본,
  `T-226b` 실행계획, `T-226c/d/e` 코드·runtime·소비자 문서 전파가 모두 완료됐다.
- [x] **T-227 — Prometheus 성능 메트릭 표면.**
  `kortravelmap.api` FastAPI app에 `GET /metrics`를 추가했다. HTTP 요청 total/duration,
  in-progress, response size, exception count, DB query count/duration,
  process/runtime metrics를 Prometheus exposition format으로 제공하고
  `surface=public/admin/ops/debug/system/other` label로 공개 REST와 운영 REST를 분리했다.

## API/admin 패키지 분리 (2026-06-13, `T-228`)

- [x] **T-228 — `kor-travel-map-api` backend와 `kor-travel-map-admin` frontend 분리.**
  FastAPI/OpenAPI backend를 `packages/kor-travel-map-api/`로 이동하고,
  `kor-travel-map-admin`은 Next.js admin frontend만 소유하도록 정리했다.
  `KOR_TRAVEL_MAP_API_*`, `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `packages/kor-travel-map-api/openapi*.json` 기준으로 Docker/CI/scripts/docs를 갱신했다.

## Admin UI 접근성/e2e 보강 (2026-06-10, `T-218`)

- [x] **T-218 — admin UI 상세 구현 점검 + a11y/e2e 완비.**
  화면별 상세 점검과 a11y/e2e 보강을 완료했다. 정본은
  `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`와
  `docs/runbooks/admin-ui-screen-checklist.md`.
  - [x] `T-218a` — 공통 폼 a11y wrapper와 `validateForm` util 도입.
  - [x] `T-218b` — 좌표 scope, offline upload, issue manual override 폼에
        visible label/error/focus 경로 적용.
  - [x] `T-218c` — `/admin/backups` e2e 신설로 admin/ops 16/16 화면 커버 달성.
  - [x] `T-218d` — 위험 액션 음성 경로 e2e 보강.
  - [x] `T-218e` — `Alert` live-region 정합성 보강.
  - [x] `T-218f` — 화면별 상세 회귀 점검 체크리스트 작성.

## Sprint 5 운영 진입 완료 묶음 (2026-06-07~10)

- [x] **T-200~T-204 — 운영 진입 기반.**
  Batch DAG + 정합성 게이트, `ops.feature_consistency_reports`, pre-commit hook,
  PR CI workflow, branch protection 가이드를 완료했다.
- [x] **T-212a~d — ADR-045 전체점검/튜닝 선행 묶음.**
  전체 inventory + Playwright/e2e gap matrix, admin UI 완결성, API endpoint/error/log
  contract, DB/API/frontend 성능 튜닝과 read-heavy 재측정을 완료했다.
- [x] **T-216a~g — REST API 정합성 심화.**
  `/v1` clean cut, pagination 단일화, envelope payload/meta 분리,
  parameter/error/좌표 정합성, 명명 통일, 코드/DB surrogate 명명 전파,
  단일 정본과 버전 거버넌스를 완료했다.
- [x] **T-RV-50~55 — T-RV-04b provider/admin 후속 프로그램.**
  `maplibre-vworld-js` v0.1.3 정합, dedup 수동처리 UI/기본 scope,
  visitkorea 축제 enrichment, krforest 휴양림/수목원, datagokr 박물관/미술관,
  관광지·주차장·KHOA 해수욕장·AirKorea 대기질·공항 provider 후속을 완료했다.

## 실데이터 full reload 최종 검증 (2026-06-12, `T-212e`)

- [x] **T-212e — 실데이터 전체 재적재 + offline upload 실데이터 검증 + 최종 리포트.**
  정본은 `docs/reports/t-212e-live-full-reload-final-2026-06-12.md`.
  - 빈 DB(WSL 재설치로 환경 전체 재구축)에서 전 provider Dagster 적재
    **1,095,665 features**(MOIS bulk 980,970 / MCST CSV 13종 102,121 /
    주차장 18,294 / knps_trails 618 등) + weather values 92,923.
  - `full_load_batch_consistency_gate` 최종 report `99159eea` severity_max
    OK, `ops.data_integrity_violations` 0.
  - offline upload 실데이터 CSV/TSV/JSONL 3포맷 종단 `loaded` + #397→#417
    DELETE lifecycle live 검증(좀비 2건 삭제 → 동일 checksum 재업로드 201).
  - Windows Playwright e2e **33/33**, API smoke 17/17, backup→staging
    restore 검증값 운영 정확 일치(1,095,665), 대표 read P99 수집
    (in-bounds 442ms — 클러스터 MV ADR 재판단 입력).
  - 실측 적발 수정: krtour #392/#393/#400/#408/#410/#411/#413/#416/#417/
    #420/#424 + provider 5 repo(datagokr·krheritage·kma·mcst·knps)
    이슈→PR→머지. 이슈 #397/#407/#409 close.

## curated_features + TripMate import (2026-06-12, `T-223`)

- [x] **T-223 — curated_features + TripMate curated_trip_plans import 계약/구현.**
  T-223a~d 전부 완료. 정본은 `docs/curated-features.md`.
  - [x] **T-223a — 문서 계약 정리.**
    책/음식 테마 source 조사, overlay DB 모델, REST/Admin UI/Dagster,
    TripMate 1:1 복사 계약을 정리했다.
  - [x] **T-223b — provider 보강.**
    `python-mcst-api` 중고서점 CSV(provider PR#11),
    `python-datagokr-api` 서울 책방·무슬림 친화 음식점·안산 세계맛집·제주 향토음식점
    fileData + 전국지역특화거리 표준데이터 서비스(provider PR#10)를 반영하고,
    kor-travel-map 변환 함수와 단위 테스트를 추가했다.
  - [x] **T-223c — kor-travel-map DB/API/Dagster/Admin UI.**
    `feature.curated_*` 테이블, seed source/rule, `/v1/curated-*`,
    `/v1/admin/curated-*`, source rule apply, TripMate copy snapshot, OpenAPI/user-client,
    Dagster `curated_features` group, `/admin/curated-features` UI를 구현했다.
  - [x] **T-223d — TripMate 연동.**
    TripMate PR #184(`5966628192a1f7b0c359a6435011f3e2f3f04469`)에서
    krtour REST snapshot을 `app.curated_trip_plans` / `app.curated_plan_pois`로
    복사하고 source version/etag/item provenance를 저장하는 admin import를 머지했다.
    `kor-travel-concierge`는 curated trip plan 생성에 관여하지 않는다.

## TripMate T-130 공개 해수욕장/축제 뷰 API (2026-06-12, `T-222`)

- [x] **T-222 — TripMate T-130 공개 해수욕장/축제 뷰 API.**
  T-222a~c 전부 완료. 정본은 `docs/public-views-api.md`와 TripMate PR#183.
  - [x] **T-222a — API 사양 초안.**
    `/v1/public/beaches*`, `/v1/public/festivals*`, 스키마, category drift,
    KHOA index/축제 월별 집계 결정점을 정리했다.
  - [x] **T-222b — kor-travel-map 백엔드/OpenAPI/user-client 구현.**
    `/v1/public/beaches*`, `/v1/public/festivals*`를 추가하고 user OpenAPI와
    `@kor-travel-map/map-user-client` 타입을 재생성했다. 해수욕장은
    `detail.place_kind='beach'`를 1차 판별로 쓰며, KHOA provider category
    `01020300`은 보조 정보로 유지한다.
  - [x] **T-222c — TripMate 소비 문서/픽스처 동기화.**
    TripMate `/public/beaches*`와 `/public/festivals*`가 krtour
    `openapi.user.json` 기반 schema/client를 소비하도록 연결했다(TripMate PR#183).

## Admin UI/UX 연결성 + 실시간성 (2026-06-12, `T-221`)

- [x] **T-221 — admin UI/UX 시나리오 연결성 + 실시간성 보강.**
  T-221a~e 전부 완료. 정본 점검은
  `docs/reports/admin-ui-scenario-linkage-recheck-2026-06-11.md`.
  - [x] **T-221a — feature 상세/수동 작성 흐름.**
    `/features/[feature_id]` 1급 상세 route와 `GET /v1/admin/features/{feature_id}`,
    `/admin/features/new` 수동 feature 작성 화면(지도 좌표 선택, kor-travel-geo
    geocode/reverse, kind별 form, nearby 중복 후보)을 구현했다.
  - [x] **T-221b — import job 상세/event/cancel.**
    `ops.import_job_events`, `/ops/import-jobs/[job_id]`, job event timeline,
    `POST /v1/ops/import-jobs/{job_id}/cancel`을 연결했다.
  - [x] **T-221c — admin live signal channel.**
    `WS /v1/ops/live` topic 다중화와 frontend TanStack Query invalidation을 구현했다.
  - [x] **T-221d — provider 상세/refresh policy.**
    `/ops/providers` 상세, `provider_dataset` update request, `provider_refresh_policies`
    편집 UI/API를 구현했다. 중복 provider run endpoint는 만들지 않는다.
  - [x] **T-221e — ops logs + debug 재판정.**
    `/ops/logs`에 job event stream을 붙이고, `/debug/explain`·`/debug/fixtures` REST/UI는
    만들지 않는 것으로 정리했다.

## Provider Dagster 완결 — KMA/MCST (2026-06-11, `T-219`/`T-220`)

- [x] **T-219 — KMA weather Dagster 파이프라인 완결.**
  T-219a~c 전부 완료. asset 5종(실황/초단기/단기/중기/특보) + KST schedule +
  cursor/credential guard를 구현했다. 정본은
  `docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.
  - [x] **T-219a — weather 대상 격자/feature 매핑 조회 기반.**
    `parse_weather_extra_points`(lon,lat;… 파서 + 한국 bbox 검증)와
    `kma_weather_extra_points`/`kma_weather_max_grids_per_run` 설정,
    `list_active_target_coords`(poi_cache_targets),
    `list_active_place_coords`(deleted_at IS NULL — D-12 read 정합)를 추가했다.
    LGT 메트릭은 기등록 확인 후 노후 docstring만 정정했다.
  - [x] **T-219b — 초단기실황/초단기예보/단기예보 asset+schedule.**
    `map_dagster.kma_weather` asset 3종, KST cron(45분/20·50분/02~23시 8회),
    `kma_weather_client` resource(credential guard), cursor `base_datetime` skip/failure 기록,
    fake client 테스트 12종을 추가했다. `python-kma-api@ab1a0b8` 핀 활성화.
  - [x] **T-219c — 중기 + 특보.**
    mid asset(설정 주입 `kma_mid_region_features` JSON — 육상/기온 reg_id 분리,
    미설정 skip, `kma_datagokr_client` resource)과 특보 record resource
    `kma_weather_alert_records`(전국 108, rolling window)→notice 적재를 구현했다.
    ASOS/해수욕장(beach_*)/APIHub 표면 + 특보 구역별 fan-out·좌표 enrichment는
    1차 범위 밖 백로그 비고로 남겼다.
- [x] **T-220 — MCST(python-mcst-api) 신규 provider 풀스택.**
  T-220a~c 전부 완료. 변환/Dagster/fixture·문서를 구현했고 marker `P-12`,
  `DATA_GO_KR_SERVICE_KEY` 공유 기준을 문서화했다. 정본은 같은 리포트 §3과
  `docs/mcst-feature-etl.md`.
  - [x] **T-220a — `providers/mcst.py`.**
    slug 메타표 16종(`MCST_CULTURE_DATASETS` 14 + `MCST_LIBRARY_DATASETS` 2,
    dataset_key `mcst_<slug>`), 공용 `culture_records_to_bundles`,
    `library_records_to_bundles`(한국어 컬럼 방언 관대 조회), 단위 테스트 11종을 추가했다.
    category 신설 없이 기존 코드 매핑과 `place_kind` 세부 구분을 사용한다.
  - [x] **T-220b — Dagster 배선.**
    fetch 2종(`(slug, record)` 튜플 스트림, dataset당 `mcst_max_items_per_dataset` 상한),
    record resource 2종(live), `mcst_features.py` asset 2종(slug별 분리 `_load`,
    `McstLoadResult` 합산 metadata), 주 1회 schedule 2종, definitions 배선을 구현했다.
  - [x] **T-220c — fixture/문서.**
    ETL preview fixture 2종(공용 변환 대표 — independent_bookstores/public_libraries),
    `docs/mcst-feature-etl.md`, external-apis §3.14, provider-contract §3/§12,
    `python-mcst-api@d06e8d2` 핀, CHANGELOG를 갱신했다. dedup pair는 실데이터
    매칭 품질 확인 후 재검토한다.

## Phase 6.7 — Feature 사용자 요청 CRUD/versioning (2026-06-08, `T-215`)

- [x] **T-215a — place/event feature 추가·수정·삭제 admin API + versioning.**
  `/admin/features`에 `POST`, `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다.
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=require_review|immediate` 설정에 따라
  요청을 `pending`으로 보관하거나 같은 transaction에서 바로 적용한다. provider 적재는
  `data_origin='provider', data_version=0`, 사용자 요청은
  `data_origin='user_request', data_version=1`로 구분하고
  `feature.feature_versions` snapshot을 남긴다. 사용자 요청 삭제는 soft delete이며
  provider 재적재나 snapshot 누락 정리로 되살리지 않는다.
- [x] **T-215b — admin UI feature change queue 화면.** (2026-06-09)
  `/admin/features/change-requests` 화면을 추가해 `GET /admin/features/change-requests`
  목록, add/update/delete 요청 form, approve/reject 동작을 연결했다. 목록 meta에
  `review_mode`를 추가해 `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE` 현재값을 빈 큐에서도
  표시한다. 기존 정본 mutation endpoint만 사용하며 새 중복 REST 표면은 만들지 않았다.
- [x] **T-215c — frontend generated type/e2e workflow 보강.** (2026-06-09)
  OpenAPI 생성 schema 타입 기반 route mock으로 pending→approve→applied, immediate mode
  create, update/delete 요청 생성, soft delete 적용 표시와 action delete 필터 e2e를 추가했다.
  Next RSC prefetch는 mock 범위에서 제외해 document/API 요청을 분리했다.


## Phase 6.6 — REST API v1 정리 후속 (2026-06-08, `T-214`)

전 표면 계약 정본은 `docs/rest-api.md`, TripMate 소비 view는 `docs/tripmate-rest-api.md`.
기준 입력은 `docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate
`docs/integrations/kor-travel-map-rest-api.md`. 사용자 결정으로 `/tripmate/feature-update-requests*`는
admin 영역으로 이동한다.

- [x] **T-214a — REST API 정본 문서 작성.**
  Versioning, envelope, parameter 규약, endpoint naming, 중복 처리, 누락 API를
  종합해 `docs/tripmate-rest-api.md`를 목표 `/v1` 계약과 현재 구현 gap 중심으로
  재작성했다. `docs/openapi-admin-contract.md`, `docs/tripmate-integration.md`,
  `docs/poi-cache-update-targets.md`, `docs/architecture.md`의 충돌 문구도 정리했다.
- [x] **T-214b — 사용자/서비스 API `/v1` prefix 도입.** (2026-06-09)
  `features`/`categories`/`providers` 라우터를 `application.include_router(..., prefix="/v1")`로
  `/v1/*` 노출(`/features/*`(batch 포함)·`/categories`·`/providers/{provider}/last-sync`).
  구 unversioned 경로는 유지하지 않는다(clean cut, alias 없음). liveness `/health`·`/version`은
  비버저닝 유지. `USER_OPERATIONS`·OpenAPI 두 profile·frontend 호출부(`api/features.ts`·
  `api/poiCacheTargets.ts`)·generated type·e2e mock·테스트 일괄 갱신. admin/ops/debug의
  `/v1` 이동은 ADR-048/T-216a에서 처리한다.
- [x] **T-214c — `/tripmate/feature-update-requests*` 제거, admin-only 전환.**
  user OpenAPI와 `USER_OPERATIONS`에서 `POST/GET /tripmate/feature-update-requests*`를
  제거하고 `/admin/feature-update-requests*`만 정본으로 남긴다. TripMate 사용자 제안 큐는
  TripMate app DB 소유로 문서화하고, 운영자 승인 뒤 admin API 호출로 연결한다.
- [x] **T-214d — `/tripmate/*` namespace 제거, batch를 `POST /features/batch`로 일반화.**
  (2026-06-09, 사용자 지시 — kor-travel-map은 TripMate 전용이 아니다.) `tripmate_router` 제거,
  batch를 `features_router`의 `POST /features/batch`로 옮기고 service-token을 route-level
  gate로 유지(ServiceToken scheme 보존). `USER_OPERATIONS`·OpenAPI 두 profile·frontend
  generated type·테스트·문서 일괄 갱신. `/v1` prefix 부여는 T-214b/T-216a에서. 응답은 list
  `items[]`와 충돌하지 않게 `data={found:{feature_id:Feature},missing[]}`로 정렬(후속).
- [x] **T-214e — pagination/parameter 일관성 정리.** (2026-06-09)
  규약 확정: **페이지 가능한 목록 = `page_size`+`cursor`**(search·nearby·admin/ops),
  **bounded 지도 조회 = `limit`**(`/features` flat·`/features/in-bounds` — 뷰포트 로드),
  다중 값 = 단수 반복 query parameter, bbox = `min_lon/min_lat/max_lon/max_lat` 4-float.
  코드: `/v1/features/search`의 CSV `bbox` 제거 → 4-float, `limit`→`page_size`,
  `_parse_bbox_csv` 삭제. `/features` flat은 bounded map이라 `limit` 유지(admin/지도 호환).
  (envelope `meta.page`·`total` opt-in·2-티어 캡 등 심화는 T-216b/c, ADR-048.)
- [x] **T-214f — POI cache target write 표면 결정.** (2026-06-09)
  **결정: TripMate 직접 write 미허용 — admin/operator flow만.** POI cache target
  upsert/delete는 `/admin/poi-cache-targets*`(인프라 SSO + kill-switch)로만 수행하고,
  service-safe `/v1/poi-cache-targets/*` write 경로는 **추가하지 않는다**. TripMate는 등록된
  target 기준 read(`GET /v1/features/nearby/by-target`)만 소비. (rest-api.md·
  tripmate-rest-api.md 명시.)
- [x] **T-214g — error/idempotency/rate-limit/deprecation header 규약 명시.** (2026-06-09)
  규약을 `docs/rest-api.md`에 단일 표로 고정: `X-Request-ID`(구현됨 — 모든 응답),
  problem+json `code` enum(§4), `Retry-After`(LOCK_BUSY/RATE_LIMITED), `Idempotency-Key`·
  `RateLimit-*`·`Deprecation`/`Sunset`(규약 정의 + 적용 시점 명시; idempotency/rate-limit
  구현은 T-216 외부 변경 호출에서). 실제 problem+json 본문 전환은 T-216d.
- [x] **T-214h — endpoint naming cleanup.** (2026-06-09)
  `/debug/health`·`/debug/version` **제거**(ADR-048 clean cut — 공용 `/health`·`/version`과
  중복). `health.py`/`version.py` 라우터 삭제, app.py/__init__ 정리, 상태확인은
  `/health`·`/version`(public_status) + `/ops/health-deep`(readiness)로 수렴. frontend
  `useHealth`/`useVersion`을 public `/health`·`/version`(envelope) 소비로 repoint.
  `dedup-review`/`enrichment-review` **복수화는 T-216e(major 컷)로 이월** — 본 task에선
  결정만(소비자 영향 큰 path 개명은 ADR-048 명명 묶음에서 일괄).


## 문서 정합성 백로그 (T-DA, 2026-06-06)

문서 전수 정합성 감사 결과. 전체 지적·근거·파일위치·의사결정은
**`docs/reports/docs-consistency-audit-2026-06-06.md`** 가 정본. task id는 `T-DA-NN`,
사용자 결정은 `DA-D-NN`. 사용자 결정(DA-D-01 포인터 대체 / DA-D-02 한 PR 반영)에
따라 T-DA-01~10은 **본 배치에서 반영 완료**.

- ~~**T-DA-01** CLAUDE.md §2 "현 단계" 전면 stale(PR#149/Sprint4 완료)~~ ✅ DA-D-01(A)
  포인터 대체.
- ~~**T-DA-02** CLAUDE.md geocoding 로컬 포트 `8888`~~ ✅ → `12201`(`.env.example` 정합).
- ~~**T-DA-03** CLAUDE.md ADR "001~046 / 다음 047"~~ ✅ → "001~047 / 다음 **048**".
- ~~**T-DA-04** AGENTS.md "코드 작성 단계"(PR#156) stale~~ ✅ 포인터 대체.
- ~~**T-DA-05** sprints/README "현 위치"(PR#149) + Sprint5 "🟡 진입 준비"~~ ✅ 포인터
  대체 + "🟢 진행 중".
- ~~**T-DA-06** category 개수 "141건" 표기(코드=144)~~ ✅ category.md/debug-ui-package.md/
  decisions.md 라벨을 **144**로 통일(§4 트리는 이미 ADR-027 3건 포함 완성 상태였음).
- ~~**T-DA-07** architecture.md 큰그림 의존체인에서 `category` 누락~~ ✅ 추가.
- ~~**T-DA-08** decisions.md ADR-025 "Next.js 15"/"port 8610" 현행 교차참조 없음~~ ✅
  현행 기준 note 추가(역사 본문 보존).
- ~~**T-DA-09** decisions.md ADR-002 체인이 `api` 포함·`category` 누락~~ ✅ 현행 체인
  note 추가.
- ~~**T-DA-10** decisions.md ADR-036 제목 `v0.1.0`~~ ✅ 현행 핀 v0.1.2 note 추가.
- ~~**T-DA-12** CLAUDE.md §5 "전체 22개 룰은 SKILL.md §4"(실제 26개)~~ ✅ → **26개**.
- ~~**SKILL.md 2차 스윕**: §8 ADR "001~046/047" + §9 "코드 작성 단계" 상태 블록
  (PR#149/Sprint4 완료)~~ ✅ T-DA-01/03과 동일 처리(포인터 대체 + 001~047/048).
- ~~**README.md 3차 스윕**: 상단 "현재 상태"(PR#155/#156/Sprint4 완료) 블록 + "빠른 시작
  (Sprint 4 완료…)" 헤더~~ ✅ T-DA-01과 동일 처리(DA-D-01(A) 포인터 대체, 기준값만
  유지). entry doc 4종(CLAUDE/AGENTS/SKILL/README) 상태 블록 drift 모두 정리 완료.
- **T-DA-11** `openapi-admin-contract.md` ↔ 구현 endpoint/error/log 전수 대조 —
  외부 노출 API 한정으로 **수행함**(감사 §8 = 아래 T-DA-13~17). 라우터별 세부
  contract 전수는 계속 `T-212a`/`T-212c`로 위임.

### 외부 노출 API 일관성/완결성 (감사 §8, 2026-06-06 추가)

생성 spec(`openapi.json` 35 path / `openapi.user.json` 7 path) ↔ contract 문서 대조.
코드 영향이 있어 본 문서 PR과 분리(결정 DA-D-03/04 확정 후 반영).

- ~~**T-DA-13** (MED, 빠진 기능, **DA-D-04 = T-212 묶음**) `/admin/issues`
  GET/GET{id}/PATCH(resolve/ignore/reopen/retry_geocode/retry_reverse_geocode/
  apply_kor_travel_geo_address/manual_override)~~ ✅ **구현 완료(2026-06-07)**. ADR-046
  주소/좌표 이슈 운영자 수동 처리 API. `routers/admin_issues.py`(목록 keyset cursor +
  단건 detail + PATCH 7 action) + 신규 `infra/feature_address_repo.py`(feature.features
  UPDATE + `ops.feature_overrides` upsert) + kor-travel-geo `geocoding` 정/역지오코딩.
  `{data, meta}` envelope. 단위 14 + PostGIS 통합 3 테스트. 목록 `q`(message/feature_id/
  source_record_key ILIKE) + `bbox`(연결 feature 4326 GiST `&&`) 필터도 구현 완료
  (`ops_repo` 확장 + 통합 테스트). admin UI(승인/거절 화면)는 **T-212b** 별도 에이전트
  후속.
- ~~**T-DA-14** (LOW, doc) contract §4 표 `admin-providers` 미구현 표기 누락~~ ✅
  "(미구현 — T-207b 취소, feature-update-requests provider_dataset scope 대체)" 표기.
- ~~**T-DA-15** (MED, API 일관성, **DA-D-03 = 전면 통일**) list 응답 셰입 이원화
  (`{data,meta}` vs `{count,items,next_cursor}`) → 전면 envelope 통일~~ ✅ 3 flat list
  라우터 모두 `data.{items,next_cursor}` + `meta.{count,duration_ms}`로 통일.
  - [x] `/admin/feature-update-requests` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets` (2026-06-06).
- ~~**T-DA-16** (MED, API 일관성, **DA-D-03 = 전면 통일**) 단건 응답 envelope 불일치
  (bare object 6종 + import-jobs/{id} `{data}`만) → `{data,meta}` 통일~~ ✅ 감사 열거
  단건 전부 통일 완료(추가 발견 nux-seen은 T-DA-18로 분리).
  - [x] `/admin/feature-update-requests/{id}`·`/tripmate/feature-update-requests/{id}`
    → `{data, meta}` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads/{id}` → `{data, meta}` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets/{id}` → `{data, meta}` (#252, 2026-06-06).
  - [x] `/ops/metrics` → `{data: OpsMetricsData, meta:{duration_ms}}`,
    `/ops/import-jobs/{job_id}` → `meta.duration_ms` 추가 (#253, 2026-06-06).
  - [x] `/ops/dagster/summary` → `{data: DagsterSummaryData, meta}`,
    `/debug/mois-license/{id}` → `{data, meta(cached, duration_ms)}` (2026-06-06).
- ~~**T-DA-18** (LOW, API 일관성, **DA-D-03 추가 발견**) `POST /ops/dagster/nux-seen`
  flat bare → `{data, meta}`~~ ✅ `DagsterNuxSeenData` + envelope, 4 return을
  `_nux_seen_response` 헬퍼로 wrap. 프런트 `useMarkDagsterNuxSeen` 본문 미소비라
  소비측 무변(2026-06-06). **DA-D-03 전면 통일(T-DA-15/16/18) 코드 전환 완료.**
- ~~**T-DA-17** (INFO) contract 문서 구현/미구현 혼재 표기~~ ✅ §4 표·§4.1 미구현 배지
  반영(전체 endpoint 상태 컬럼화는 T-212c).
- **DA-D-03 = 전면 통일** (확정) — 코드 전환은 별도 PR(T-DA-15/16). 본 PR은 표준 문서화.
- **DA-D-04 = T-212 묶음** (확정) — `/admin/issues`는 T-212b/c. 본 PR은 미구현 배지.


## 코드 리뷰 후속 백로그 (PR#181~#233, 2026-06-06)

직전 리뷰(#153~#179) 이후 머지된 비-T-RV 실질 PR(정합성 Phase 2 F5~F8 / T-200
batch gate / 운영 게이트 T-202~204 / T-208i 등)을 상세 리뷰한 결과. T-RV-\* 구현
PR과 T-DA 문서 PR(#227/#230)은 리뷰 생략. 정본은
**`docs/reports/pr-181-233-review-2026-06-06.md`**. 신규 지적은 **전부 LOW**(관측
전용 WARN 케이스의 count 의미/성능) — 운영 진입을 막지 않는다. (검토 중 세운 F5
join fan-out·F7 score 스케일 risk는 schema PK/CHECK로 해소 = 결함 아님.)

- ~~**T-RV-38** (LOW, consistency F8) `infra/consistency.py:529-557` — file row가
  `feature_missing` + `metadata_missing_object` 동시 충족 시 count 2 증가(distinct
  orphan보다 과다).~~ ✅ `count`는 distinct metadata/object row 기준으로 dedup하고,
  세부 문제유형은 `sample_ids`와 `metadata`에 보존한다.
- ~~**T-RV-39** (LOW, consistency F4/WARN) `infra/consistency.py:400-410` — F4 임계
  초과 시 `count=pending`(백로그 전체 수)이 `total_violations`/`by_severity.WARN`에
  혼입.~~ ✅ 임계 초과형 `count=1`, 실제 pending/threshold는
  `metadata.pending_count`/`summary.case_metadata.F4`에 분리한다.
- ~~**T-RV-40** (LOW perf, consistency F6) `infra/consistency.py:146-185` — F6가
  `feature.features`를 LATERAL `jsonb_path_query`로 4회 풀스캔.~~ ✅
  `candidate_features` CTE로 삭제되지 않고 detail 후보가 있는 feature를 한 번만 읽고,
  4개 JSONPath period 추출은 단일 `CROSS JOIN LATERAL` 안으로 모았다.
- ~~**T-RV-41** (LOW 전제, batch_dag) `infra/batch_dag.py:454-460` — `CONCURRENTLY`
  refresh는 MV UNIQUE 인덱스 + 사전 populate 전제. 현재 MV 없어 latent.~~ ✅
  **`T-101`** MV 도입 체크리스트와 performance/Dagster 문서에 UNIQUE 인덱스 +
  최초 비-concurrent populate 전제를 고정했다.


## 코드 리뷰 후속 백로그 (PR#153~#179, 2026-06-04)

리뷰 없이 머지된 ADR-045 구현 배치(#153~#179)를 영역별 상세 리뷰한 결과.
전체 지적·근거·파일위치는 **`docs/reports/pr-153-179-review-2026-06-04.md`** 가
정본. task id는 `T-RV-NN`. 권장 처리 순서는 리포트 §5.

**HIGH (운영/계약/보안 — 선반영):**
- ~~**T-RV-01/02** Dagster 운영 형상 (D-2): metadata를 별도 `kor_travel_map_dagster`
  Postgres DB로 (현재 SQLite 폴백) + `dagster dev`→webserver/daemon 분리.~~
  ✅ `dagster-db-init`, `dagster` webserver, `dagster-daemon`,
  `docker/dagster.yaml` Postgres storage, `dagster-postgres` dependency와 compose
  회귀 테스트를 추가했다.
- ~~**T-RV-03** Dagster `kor_travel_map_client` resource engine dispose 누수.~~
  ✅ generator resource로 전환해 run/tick 종료 시 `AsyncEngine.dispose()`를 호출하고,
  running event loop 안에서도 teardown이 동작하는 회귀 테스트를 추가했다.
- **T-RV-04** Dagster provider 서비스키 resource 미구현(D-15, feature-load asset
  provider fetcher 기본 wiring 미완료).
  - ✅ **T-RV-04a**: provider record key별 guard resource와
    `KOR_TRAVEL_MAP_*` credential env mapping을 등록했다. 기본 `defs`는 더 이상 generic
    `_missing_resource`로 죽지 않고, resource materialize 시 provider/package/env
    안내를 내며 secret 값을 숨긴다.
  - **T-RV-04b**(✅ 완료 2026-06-08, provider 순차 wiring): provider public client live fetcher를
    실제 record iterable로 연결. 패턴 = `provider_fetchers.fetch_<provider>(settings)`
    (lazy provider import, credential 없으면 guard 메시지) + `resources.
    build_provider_record_live_resource(spec, fetch)`로 해당 resource_key만 guard→live 교체.
    - [x] **datagokr_cultural_festivals**(festival, #261) — `DataGoKrClient.festival.
      iter_all()`. dagster 단위 테스트(fake client) + 37 dagster suite green.
    - **나머지 6종은 설계 결정 선행 필요** — 적합성 감사
      `docs/reports/t-rv-04b-provider-fetcher-audit-2026-06-07.md`. 요약:
      - [x] **krheritage_events**(2026-06-07) — **ADR-044 재조정 + wiring**. 검증 결과
        `HeritageEvent` 필드명(starts_on/ends_on/place/tel_name/address)이 krtour Protocol
        (start_date/venue_name/...)과 불일치 + `raw` 부재. 조치: **upstream PR**
        `python-krheritage-api#4`(HeritageEvent.raw 주입, sibling 모델 정합, merged) +
        krtour `KrHeritageEvent` Protocol/transform을 provider 필드명에 맞춰 재정렬(+테스트).
        fetcher = `HeritageClient.event.iter_months()`(provider 기본 rolling window
        months_back=1/ahead=12). dagster fetcher 단위(fake) + 39 dagster suite green.
      - [x] **krex_rest_areas**(2026-06-07) — ADR-044 재정렬 + **option 2 파생 자연키**.
        `RestArea`에 안정 id·address 없음(사용자 결정: 안정키 있으면 사용·없으면 파생) →
        `_rest_area_natural_key`=`name::route_name::direction`(`|`는 ADR-009 예약 → `::`).
        Protocol을 RestArea 필드명(route_name/lat/lon/phone_number)으로 재정렬, uni_id/address
        제거. admin etl_fixtures/etl_live 어댑터도 갱신. provider 측 안정 id/address 노출은
        **upstream 이슈 `python-krex-api#7`**로 분리(AI agent 작업용). fetcher=`restarea.
        list_all` 페이지네이션, dagster 단위 + 통합 green.
      - [x] **krex_traffic_notices**(2026-06-07) — ADR-044 재정렬: Protocol을 `Incident`
        실제 shape(route_no/incident_type/message/started_at/ended_at/raw)로, krtour-side
        파생(notice_id=`::` 복합키+payload_hash, title 합성, notice_type=normalize, valid_from·
        until=방어적 파싱, severity=None, source_agency="한국도로공사", coord=None).
        coordless notice는 raw_address=route로 strict 검증 통과. fetcher=`traffic.incident`
        페이지네이션(`krex_ex_api_key`). **잔여(krtour follow-up)**: EX `incidentType`
        숫자코드→notice_type 매핑 테이블(현재 대부분 "traffic" 기본값). 일시적 incident의
        영속 Feature 적재 = 재실행 갱신 + `valid_until` 만료(설계 메모).
      - [x] **opinet_stations** — provider 보강 + krtour wiring(bbox+POI-타깃) 완료(2026-06-08).
        조사 결론(2026-06-07): OpiNet OpenAPI에 지역/전국 bulk 주유소 목록 엔드포인트가
        **물리적으로 없음**(station 반환은 aroundAll 반경≤5km/lowTop10 top20/detailById 단건뿐,
        나머지는 코드/가격 집계). `python-opinet-api#7` 코멘트로 결론 기록.
        - [x] **provider 보강**(`python-opinet-api#8` merged, **v0.2.0**): `iter_stations_in_bbox()`
          (sync+async) — bbox를 aroundAll 반경 격자(`radius*√2`)로 덮고 `uni_id` dedup하는
          **근사 enumeration**. 한계(면적 비례 호출수 급증→bounded 권장, tel/lpg_yn 부재→detail
          N+1) README/docstring 명시.
        - **krtour wiring 후속** — 사용자 결정(2026-06-08): **bbox + POI-타깃 둘 다 지원**. 3 PR:
          - [x] **opinet-1 ADR-044 재정렬**(2026-06-08) `OpinetStationItem` Protocol을 provider
            `Station` 필드명(uni_id/name/brand/address_road/address_jibun/lon·lat float)에 정렬,
            `tel`/`lpg_yn`은 `StationDetail` 한정이라 Protocol 필수에서 빼고 transform이 `getattr`로
            보강(`Station`이 그대로 만족). `stations_to_bundles`/ETL fixture/etl_live 어댑터/단위·통합
            테스트 갱신. 게이트: ruff/mypy(map 85/admin 26)/unit+lint 965(coverage 81%)/full 1168 green.
          - [x] **opinet-2 bbox fetcher**(2026-06-08): settings `opinet_scope_mode`(disabled/bbox/
            poi_cache_target) + `opinet_scope_bbox` + `opinet_scope_radius_m` + `fetch_opinet_stations`
            (`OpinetClient.iter_stations_in_bbox`, uni_id dedup, finally close) + resource guard→live
            (기존 `feature_place_opinet_stations` asset 그대로 소비). poi_cache_target 모드는 명확
            guard로 opinet-3 대기. 게이트: ruff/mypy(map 85/dagster 13/admin 26)/lint-imports/unit+lint
            965(coverage 81%)/full 1168/dagster 85 green.
          - [x] **opinet-3 POI-타깃**(2026-06-08): `fetch_opinet_stations`의 `poi_cache_target`
            분기 연결. `_opinet_poi_target_bboxes`가 `settings.pg_dsn`(async)→sync psycopg DSN으로
            `ops.poi_cache_targets`의 opinet 활성 target(lon/lat/radius_km, update_enabled,
            non-deleted) 조회 → `_center_radius_to_bbox`(위경도 근사)로 bbox 변환 → 기존
            `_enumerate_opinet_stations`로 enumerate(target 간 uni_id dedup). 단위(math/enumerate/
            empty) + 통합(`test_opinet_poi_scope` 실 PostGIS seed→조회) 테스트. **→ T-RV-04b 완전 종료.**
            - **리뷰 수정(#304, 2026-06-08)**: `external_system`은 provider명이 아니라 외부 호출자
              (tripmate 등) — `='opinet'` 필터 제거(실제 등록 target 누락 P1). active 정의를
              `scope_repo`와 동일하게(`deleted_at` 없음 + `update_enabled` + `refresh_policy<>'disabled'`
              P2) + opinet `provider_overrides` `targeted_policy='disabled'` 옵트아웃 제외. 통합
              테스트를 tripmate/kakao + disabled/update-off/deleted/optout seed로 회귀 보강.
              게이트: ruff/mypy(3pkg)/lint-imports/dagster 87/coverage 81%/POI 통합 green.
      - [x] **mois_license_records**(Phase B, 2026-06-07) — clean match(provider `PlaceRecord`이
        `MoisLicensePlaceRecord` Protocol 전부 충족, 재조정 불요). fetcher
        `fetch_mois_license_records`가 미리 sync된 MOIS 소스 SQLite DB(설정
        `mois_source_db_path`, env `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`)에 sqlite Session 열고
        `mois.db.iter_open_place_records(service_slugs=PROMOTED_SERVICE_SLUGS)` stream. DB
        부재 시 명확 실패. dagster 단위(temp-DB 실측 + guard) green.
        - [x] **mois Phase A(소스 DB sync)**(2026-06-07) — `mois_source_sync.py`:
          순수 helper `sync_mois_source_db(settings, service_slugs=None)` + Dagster op
          `mois_localdata_source_sync` + job + 주간 schedule(STOPPED, `0 4 * * 1` KST).
          provider `mois.create_sqlite_schema` → keyless `LocalDataFileClient` →
          `sync_localdata_source_db(service_slugs=PROMOTED_SERVICE_SLUGS, commit=True)`로
          LOCALDATA 다운로드→소스 DB 적재. **정정: 공개 파일 포털(`file.localdata.go.kr`)
          이라 API key 불요(네트워크만 필요)** — provider `LocalDataFileClient`에 key
          파라미터 없음. dagster 단위(fake mois 5 + op + schedule) green. 실데이터 검증은
          T-212e.
      - [x] **knps_point/geometry**(2026-06-07) — **provider 보강**으로 해결. 사용자
        지시(적극 수정)대로 `python-knps-api#7`(merged, v0.2.0)에 헤더 정규화 typed
        record(`KnpsPlaceRecord`/`KnpsGeoRecord`) + `read_place_records`/`read_geo_records`
        추가. krtour는 best-guess 컬럼 매핑 폐기, provider typed record 직접 소비.
        fetcher는 **async generator**(다운로드/파싱 async)이고 live builder를
        `Iterable | AsyncIterator`로 확장. dataset key(`knps_visitor_centers`/`knps_trails`)는
        settings 값을 fetcher/asset이 공유(`SETTINGS_VALUE_RESOURCES`). keyless라 credential
        불요. dagster 단위(fake knps client) green. 실 fetch 검증은 T-212e.


## 최근 완료 (2026-05-31~2026-06-03)

- **T-208h** (2026-06-03): `/admin/offline-uploads*` backend와 admin UI 기본
  upload 화면을 추가했다. JSON/JSONL `FeatureBundle` 파일을 RustFS/S3 store에 쓰고,
  `ops.offline_uploads` row 생성/list/detail, Dagster GraphQL
  `offline_upload_load` launch까지 연결했다. CSV/TSV validation/column mapping은
  T-208i로 남긴다. WSL live smoke에서 upload → Dagster `SUCCESS` → DB
  `loaded/done/progress=100`을 확인했고, Windows Playwright `admin-ops.spec.ts`는 새
  `/admin/offline-uploads` route 포함 6/6 통과했다.
- **T-208b 후속** (2026-06-03): RustFS/S3 호환 `offline_upload_store` resource와
  Docker RustFS bucket init을 구현했다. API `12101`, console `12105`, bucket
  `kor-travel-map`/`krtour-uploads` 기준으로 실제 put/get smoke를 확인했다.
- **T-208f** (2026-06-03): `consistency_dedup_refresh` Dagster maintenance job을
  추가했다. DB에 적재된 provider/dataset scope를 다시 읽어 pair/sibling dedup 후보를
  큐에 upsert하고, 이어서 F1~F4 consistency report를 저장한다. schedule은
  `consistency_dedup_refresh_daily_schedule`이며 기본 `STOPPED`다.
- **T-211b** (2026-06-03): admin frontend 전역 app shell/navigation, 운영 홈
  dashboard, `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets` 화면을 최신 REST/Dagster
  계약에 맞춰 구현했다. `/admin/dagster`는 Dagster webserver embed와 자체 summary
  UI를 함께 보여주며 schedules/sensors 정보를 노출한다.
- **T-211a** (2026-06-03): admin UI 최신화 선행 gap audit과 typed frontend API
  layer를 추가했다. `/ops/import-jobs` 정본, `/features/nearby/by-target` 범위,
  backend gap을 문서화하고 화면 구현 선행 조건을 정리했다.
- **T-208d** (2026-06-03): `packages/kor-travel-map-dagster`에 Feature 적재 asset 9개의
  KST schedule과 asset job을 등록했다. 모든 schedule은 `Asia/Seoul` 기준이고,
  외부 API 호출 분산을 위해 분/요일을 나눴으며 기본 status는 `STOPPED`다.
- **T-207g** (2026-06-03): OpenAPI export를 admin 전체
  `packages/kor-travel-map-api/openapi.json`과 TripMate/user subset
  `packages/kor-travel-map-api/openapi.user.json`으로 이원화했다. CI drift gate는
  `--profile all --check`로 두 산출물을 함께 검증한다.
- **T-207e** (2026-06-03): `GET /features/in-bounds`, `GET /features/search`,
  `GET /features/{feature_id}` envelope 상세, `POST /tripmate/features/batch`를
  연결. 기존 `GET /features` bbox raw 응답은 admin frontend 호환용으로 유지하고,
  TripMate/public 응답은 `{data, meta}` envelope로 분리했다.
- **T-207d** (2026-06-03): `/ops/metrics`, `/ops/import-jobs`,
  `/ops/import-jobs/{job_id}`, `/ops/consistency/reports`,
  `/ops/consistency/issues` backend를 연결. `infra.ops_repo`는 import job,
  consistency report, data integrity issue를 read-only keyset cursor로 조회한다.
- **T-207c** (2026-06-03): `/admin/features` 목록/비활성화, `ops.feature_overrides`
  `prevent_provider_reactivation`, provider upsert status 보호, `/admin/dedup-review`
  목록/결정/merge backend를 연결. 이후 T-215a에서 사용자 요청 기반 place/event
  추가·수정·soft delete API를 붙였다. hard delete와 별도 audit log는 여전히 후속이다.
- **PR#168** (merged 2026-06-03): Dagster `feature_update_request_queue_sensor` +
  `feature_update_request_worker` + failure sensor. queued/now request를
  `AsyncKorTravelMapClient.execute_feature_update_request()`로 실행하고, 실패 시
  request/import job 실패 전이와 notifier payload를 보강.
- **PR#167** (merged 2026-06-03): `/admin/poi-cache-targets` admin API와
  `/features/nearby/by-target` summary 조회. target CRUD/list/detail/delete,
  PostGIS `coord_5179` 거리 조회, filter/sort/cursor, OpenAPI export, unit/integration
  테스트.
- **PR#166** (merged 2026-06-03): `/admin/feature-update-requests` admin API. POST(dry-run/actual),
  GET(list/detail), cancel, run-now 재큐잉, OpenAPI export, list filter 통합 테스트.
- **PR#165** (merged 2026-06-03): `infra.feature_update_executor`, `cache_target_keys`
  resolver, target link 재계산, provider refresh policy skip, runner 기반 DB 적재 통합
  테스트.
- **PR#164** (merged 2026-06-03): `alembic 0009`로
  `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies`를 추가하고,
  ORM row + raw SQL repo + PostGIS 통합 테스트를 구현.
- **PR#163** (merged 2026-06-03): T-206a-geo 검증 완료 문서화 +
  RustFS dev compose 예시 host port `12101`/`12105` 정렬.
- **PR#162** (merged 2026-06-03): `AsyncKorTravelMapClient` feature update request
  메서드 4종 + top-level client export + RustFS 포트 12101/12105 문서 정렬.
- **T-206a-geo 확인** (2026-06-03): `kor-travel-geo` main의
  `/v2/regions/within-radius` 구현과 optional 실제 PostGIS 테스트를 재검증.
  WSL targeted test `15 passed, 1 skipped`, 로컬 12201 server smoke는 `sigungu`
  `11650`(서초구) contains 응답 확인.
- **PR#161** (merged 2026-06-03): `infra.feature_update_repo` request/import job
  lifecycle repository + kor-travel-geo REST API 로컬 포트 12201 문서/설정 정렬.
- **PR#160** (merged 2026-06-03): `infra.scope_repo` scope resolver.
- **PR#159** (merged 2026-06-03): `ops.feature_update_requests` Alembic 0008 +
  ORM 매핑 + DDL 계약 통합 테스트.
- **PR#158** (merged 2026-06-02): Docker API 컨테이너의 Dagster URL을
  `KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL` 기본값(`http://dagster:12302`)로 분리.
- **PR#157** (merged 2026-06-02): admin UI `/admin/dagster` + backend
  `GET /ops/dagster/summary` + Dagster webserver embed.
- **PR#156** (merged 2026-06-02): Docker 이미지/compose, API `12301`, admin UI
  `12305`, Dagster `12302` 고정 포트, `.env` key mapping, 기동/포트 종료 스크립트.
- **PR#155** (merged 2026-06-02): kor-travel-map-owned Dagster Feature ETL 1차.
  `packages/kor-travel-map-dagster/` code location과 9개 Feature asset runner, PostGIS
  적재 통합 테스트.
- **PR#114** (merged 2026-05-31): geocoding live 기본 포트 정합(현재 12201),
  Next.js 16 + `maplibre-vworld-js#v0.1.2`, GDAL 3.8.4 고정, Windows Playwright
  e2e 14/14, 관련 문서 갱신.
- **PR#110~#112**: Windows Git + NTFS source-of-truth 정책, WSL 실행/Playwright
  분리, journal/resume 정책 로그 보강.
- **PR#96~#100**: Sprint 4 prep, `/features` UX 보강, map-marker-react 구현,
  direct-main push revert와 통합 검증 보고서 재적용.


## 완료 이력 (Sprint 2)

- **PR#49** (merged 2026-05-28): `maplibre-vworld` v0.1.0 의존 핀 정합 — 기존
  `^1.0.0`은 이중 오류(버전 미존재 + npm 미게시) → `github:digitie/maplibre-
  vworld-js#v0.1.0` git URL+tag 핀 + `zod ^4.4.3`(peer) + ADR-036 amendment.
- **PR#48** (merged 2026-05-28): agent worktree 접두사 `geo-*` → `kor-travel-map-*`
  일괄 rename (7 normative docs) + 본 `tasks.md` 최신화 (PR#19~#47 반영).
- **PR#47** (merged 2026-05-28): 디버그 UI ETL preview `?source=live` 활성화 +
  8 provider API key(`SecretStr`) settings + `.env.example`. KMA 3 dataset
  (short/nowcast/ultra_short_forecast) 실 호출, 나머지 8은 framework(501).
  `etl_live.py` httpx async loader + LIVE_LOADER_REGISTRY. **CI red 3종 동반
  해소**: httpx dep 누락 / Alembic 1.18 `path_separator` deprecation /
  Alembic 1.18 async migration commit 안 됨(env.py) / coord_5179 assert
  대소문자. 450+21 green.
- **PR#46** (merged): KMA weather_alerts → notice FeatureBundle (alert×region
  fan-out) + krex TRAFFIC_NOTICE_CATEGORY 99000000 정정 + ETL preview registry
  11 dataset.
- **PR#45** (merged): Sprint 2 §2.4 krex 휴게소 multi-kind — 4 Protocol + 4
  변환(rest_areas place / prices food|fuel / weather observed / traffic notice)
  + 동일 feature_id 통합 검증.
- **PR#44** (merged): 디버그 UI ETL preview 라우터 3종 (`providers`/`{provider}/
  datasets`/`{provider}/{dataset}/preview`) + frontend `etl/page.tsx`. dry-run.
- **PR#43** (merged): Sprint 2 §2.3 마무리 — opinet `stations_to_bundles`
  (gas station place Feature, category 06020000).
- **PR#42** (merged): Sprint 2 §2.3 진입 — `PriceValue` DTO + `PriceDomain` +
  `make_price_value_key` + opinet `prices_to_values`.
- **PR#41** (merged): KMA `ultra_short_forecast_to_weather_values`
  (getUltraSrtFcst) + LGT(낙뢰) metric.
- **PR#40** (merged): `python-*-api` 라이브러리 status sweep — pyproject
  `[providers]` extra Sprint 그룹화 + provider-contract §12 git URL/sha 표.
- **PR#39** (merged): KMA `ultra_short_nowcast_to_weather_values` + `core/
  weather.py` pure 헬퍼 5종.
- **PR#38** (merged): Sprint 2 §2.2 진입 — `WeatherValue` DTO + 3 enum
  (WeatherDomain/ForecastStyle/TimelineBucket, ADR-010) + `make_weather_value_
  key` + KMA `short_forecast_to_weather_values`.
- **PR#37** (merged): ADR-041 본격 구현 — `python-kraddr-base` 의존 제거,
  `Address` DTO 보강 + `core/address.py` (bjd/phone/한글 정규화 utility).
- **PR#36** (merged): 디버그 UI frontend skeleton — Next.js 15 + React 19 +
  TanStack Query + Zustand (ADR-037) + map-marker-react `private:true` (ADR-043).
- **PR#35** (merged): 디버그 UI backend 첫 라우터 — `create_app` factory +
  `/debug/health` + `/debug/version` + `openapi.json` drift gate 활성 (ADR-031).
- **PR#34** (merged): Sprint 2 §2.1 datagokr 표준데이터 축제 1차 source
  (`cultural_festivals_to_bundles`, ADR-042).
- **PR#30~33** (merged): agent worktree + codegraph 룰 docs / codegraph MCP /
  거버넌스 보강 + ADR-035~043 proposed→accepted 일괄 전환.
- **PR#28~29** (merged): Sprint 2 prep — `infra/models.py` + Alembic 첫 2
  revision / `core/scoring.py`(ADR-016) + `core/providers.py`.
- **PR#19~27** (merged): Sprint 1 scaffolding (dto/core/infra) + review P0/P1
  해소. 상세는 `docs/journal.md`.
- **upstream knps-api PR#1** (https://github.com/digitie/python-knps-api/pull/1):
  maki icon 정정 (shelter / barrier).


**Phase 1 — DB 스키마 (alembic/models)**
- [x] T-205a — `alembic 0008` + `FeatureUpdateRequestRow` (`ops.feature_update_requests`,
  DDL은 `openapi-admin-contract.md §6.1`). 본 PR은 schema/ORM/DDL 검증까지만 포함하고
  scope resolver/repository는 T-206에서 분리.
- [~] T-205b — ~~`feature.sigungu_boundaries`~~ **취소**(D-11: 경계는 kor-travel-geo
  소유, kor-travel-map은 REST 호출). → T-206a-geo로 대체.
- [x] T-205c — (Phase 2) `ops.data_integrity_violations`
  (F5~F8) / `ops.poi_cache_targets` + `_feature_links` /
  `ops.provider_refresh_policies`. 본 PR에서 `alembic 0009`, ORM row, raw SQL repo,
  PostGIS schema/repo 통합 테스트를 추가했다. `cache_target_keys` scope와 provider별
  update 주기/rate limit enforcement는 T-206d 실행 본체에서 사용한다.
- [x] T-205d — `import_jobs` batch 컬럼(`load_batch_id`/`parent_job_id`, T-200 연계, D-6).
  `alembic 0012`, ORM, `jobs_repo`, `/ops/import-jobs` 조회·필터, admin UI 목록
  표시, migrated PostGIS 통합 테스트를 추가했다.


**Phase 2 — 로직 (scope resolver + 큐 브리지)**
- [x] T-206a — `infra/scope_repo.py` (resolve feature_ids/center_radius/bbox/
  sigungu_by_radius/provider_dataset + `count_features_matching_scope` dry_run).
  `sigungu_by_radius`는 kor-travel-geo `/v2/regions/within-radius` 호출(D-11).
  DB repo는 kor-travel-geo client를 직접 import하지 않고 async resolver를 주입받는다.
  `cache_target_keys` resolver는 T-206d에서 `ops.poi_cache_targets` 기반으로 완료.
- [x] T-206a-geo — (형제 repo `kor-travel-geo`) `POST
  /v2/regions/within-radius` 엔드포인트와 optional PostGIS 실데이터 테스트가
  `kor-travel-geo` main(PR #114/#115 계열)에 반영됨을 재검증했다. kor-travel-map은
  REST v2 계약/로컬 포트 `12201`/resolver 주입 경계를 유지한다.
- [x] T-206b — `infra/feature_update_repo.py` (enqueue/claim/start/finish/get/list/cancel,
  advisory lock + SKIP LOCKED, keyset cursor D-10).
- [x] T-206c — `AsyncKorTravelMapClient` feature-update 메서드 4종.
- [x] T-206d — request 실행 본체(scope→provider/dataset 역추적 refresh, D-6/D-8).
  runner 주입형 `infra.feature_update_executor`, `cache_target_keys` resolver, target
  link 재계산, provider refresh policy skip, `AsyncKorTravelMapClient` 실행 메서드.


**Phase 3 — FastAPI 라우터 (`kor-travel-map-admin` 패키지)**
- [x] T-207a — `/admin/feature-update-requests` CRUD + cancel + run-now (§5).
  실제 provider/Dagster 직접 실행 대신 `run_mode='now'` request 재큐잉까지 연결했다.
- [x] T-207f — `/admin/poi-cache-targets` + `/features/nearby/by-target` (Phase 2,
  PR#167). target CRUD/list/detail/delete와 by-target summary/cursor 조회를 연결했다.
- [x] T-207b — `/admin/providers/{p}/datasets/{d}/runs` (§7). 사용자 결정에 따라
  구현하지 않음으로 닫는다. provider run 상세는 T-207d `/ops/*`와 Dagster UI/summary
  경로에서 필요한 만큼 다룬다.
- [x] T-207c — `/admin/features` 검토/병합/override/deactivate (D-8).
  `/admin/features` 목록과 deactivate, active status override, provider upsert
  재활성화 방지, `/admin/dedup-review` 목록/accepted/rejected/ignored/merged 전이를
  연결했다. 이후 T-215a에서 `POST /admin/features`, `PATCH`/`DELETE /admin/features/{id}`
  사용자 요청 API를 추가했다. `DELETE`는 user-request soft delete이며, hard delete와
  별도 admin audit log는 후속 작업으로 남긴다.
- [x] T-207d — `/ops/*` consistency/jobs/metrics. `GET /ops/metrics`,
  `GET /ops/import-jobs`, `GET /ops/import-jobs/{job_id}`,
  `GET /ops/consistency/reports`, `GET /ops/consistency/issues`를 연결했다.
- [x] T-207e — `/features/*` + `/tripmate/features/batch` (사용자, `tripmate-rest-api.md`, D-7).
  `GET /features/in-bounds`, `GET /features/search`, envelope 상세, TripMate batch
  상세 조회를 연결했다. 기존 `GET /features` raw bbox 응답은 admin frontend 호환용으로
  유지한다.
- [x] T-207g — OpenAPI export 이원화(admin/user) + drift gate (ADR-031 amend, D-3).
  `scripts/export_openapi.py --profile all`이 admin 전체 spec과 TripMate/user subset
  spec을 함께 생성하고, CI drift gate도 두 산출물을 모두 비교한다.


**Phase 4 — Dagster (kor-travel-map 독립 구현)**
- [x] T-208a — `packages/kor-travel-map-dagster/` 골격 + definitions. 메인
      `kortravelmap`은 Dagster를 import하지 않고 별도 `kortravelmap.dagster`
      package가 code location을 제공.
- [~] T-208b — resources(DB/client/provider 9 + kor-travel-geo/rustfs, D-15). 1차:
      `kor_travel_map_client`, `reverse_geocoder`, `fetched_at`, provider record iterable
      resource 계약 구현. `offline_upload_store` resource key는 T-208g에서 추가한다.
      RustFS/S3 호환 `offline_upload_store` 기본 resource와 Docker RustFS bucket init은
      후속 T-208b 작업으로 구현했다. 실제 provider client resource wiring은 남는다.
- [x] T-208c — provider load asset 9종(이미 구현·검증된 Feature provider 변환 함수
      연결) + 주소/좌표 검증 + `AsyncKorTravelMapClient.load_feature_bundles` PostGIS
      적재 통합 테스트.
- [x] T-208d — schedules(KST cron, 부하 분산).
      현재 구현된 Feature 적재 asset 9개의 provider별 `ScheduleDefinition`과 asset job을
      등록했다. 기본 status는 `STOPPED`.
- [x] T-208e — sensors(feature_update_requests 폴링 + run_failure → 알림, D-6).
      `feature_update_request_queue_sensor`는 `peek_next_update_request()`로 queued/now
      request를 감지하고, `feature_update_request_worker`가 request id별 실행을 맡는다.
- [x] T-208f — consistency/dedup refresh job.
      `consistency_dedup_refresh` job이 `refresh_dedup_candidates` →
      `run_consistency_check` 순서로 실행된다. dedup refresh는 pair/sibling scope config를
      받고, consistency report는 `ops.feature_consistency_reports`에 저장한다.
- [x] T-208g — offline upload load job (D-14).
      `ops.offline_uploads`(alembic 0011), `infra.offline_upload_repo`,
      `kortravelmap.offline_upload` JSON/JSONL `FeatureBundle` parser/load
      orchestration, `AsyncKorTravelMapClient.run_offline_upload_load_job`,
      Dagster `offline_upload_load` job을 추가했다.


**Phase 4.2 — Offline upload admin UI 선행**
- [x] T-208h — `/admin/offline-uploads*` API + 기본 upload 화면.
      RustFS/S3 store에 JSON/JSONL `FeatureBundle` 파일을 저장하고,
      `ops.offline_uploads` row 생성/list/detail/load 실행까지 admin UI에서 연결한다.
- [x] T-208i — CSV/TSV validation + column mapping wizard.
      CSV/TSV 업로드 허용, preview/header/sample endpoint, validation import job,
      column mapping, kor-travel-geo address geocode/reverse 보강, load 전 validation gate,
      admin UI validation panel, Dagster load parser 연계를 추가했다. `bjd_code`가 없는
      provider/offline row는 resolver가 있으면 kor-travel-geo REST v2 geocode/reverse 결과로
      보강한다.


**Phase 4.5 — Admin UI 최신화 (사용자 지시로 T-208d 이후 최우선)**
- [x] T-211a — admin UI 최신 문서/현재 구현 gap audit + 선행 API/데이터 계약 보강.
      `docs/admin-ui-modernization-gap-audit.md`를 추가하고, frontend에
      `/admin/features`, `/ops/import-jobs`, `/ops/metrics`, `/ops/consistency`,
      `/admin/dedup-review`, `/admin/feature-update-requests`,
      `/admin/poi-cache-targets`, `/features/nearby/by-target` typed hook layer를
      추가했다. `/admin/import-jobs` 과거 표기는 `/ops/import-jobs` 정본으로
      정리했다.
- [x] T-211b — admin UI 최신화 구현. Dagster 관리 화면 embed와 별개로 자체 UI에서
      schedule/sensor/job/run/asset 상태를 꾸며 보여주고, feature/update request/ops
      화면을 최신 문서 기준으로 보완한다. React Doctor 검증 필수.


**Phase 5 — Docker / 배포**
- [x] T-209a — `docker-compose.yml` 1차(api/frontend/dagster/postgres) + 고정 포트
  API `12301`, frontend `12305`, Dagster `12302`, Postgres host `5432`.
- [x] T-209b — 기동 순서 1차(postgres health → API `alembic upgrade head` →
  api/frontend/dagster). 2026-06-04 Codex 후속으로 `scripts/run-admin-stack.sh`가
  시작 전 `alembic upgrade head`를 실행하고, `setsid` detached 실행 + URL 기준
  readiness로 API/frontend/Dagster를 유지하도록 보정했다. Dagster metadata DB 분리/init와
  daemon/schedule 운영은 `T-209b-a`에서 완료했다.
- [x] **T-209b-a — Dagster schedule/run/event storage PostgreSQL 강제 전환.**
  Docker standalone과 로컬 admin-stack 모두 `docker/dagster.yaml`의 unified
  `storage.postgres` instance config를 사용한다. Dagster 공식 instance config 기준에서
  이 key는 run/event/schedule-sensor tick metadata를 함께 PostgreSQL에 저장하므로,
  `KOR_TRAVEL_MAP_DAGSTER_PG_URL`이 단일 source다.
  - Docker 이미지는 기존처럼 `docker/dagster.yaml`을 포함하고, `dagster` webserver와
    `dagster-daemon`이 같은 `DAGSTER_HOME`/`KOR_TRAVEL_MAP_DAGSTER_PG_URL`을 공유한다.
  - `scripts/run-admin-stack.sh`는 시작 전 `kor_travel_map_dagster` DB 존재를 확인/생성하고,
    `docker/dagster.yaml`을 `$DAGSTER_HOME/dagster.yaml`로 설치한다.
  - 로컬 admin-stack도 `dagster dev` 대신 `dagster-webserver`와 `dagster-daemon`을
    분리 실행하고, daemon pid가 살아 있는지 readiness 뒤 확인한다.
  - `$DAGSTER_HOME/schedules/schedules.db*` 생성은 회귀로 문서화했고,
    compose/local script 회귀 테스트를 추가했다.
- [x] T-209c — Dockerfile 3종(api/frontend/dagster).
  frontend Dockerfile은 T-RV-28에서 root `package-lock.json` 기반 `npm ci`로 전환했다.
- [x] T-209d — `docs/runbooks/docker-app.md` + `docs/deploy.md`.
- [x] T-209e — backup/restore 독립 DB 묶음(ADR-040 amend, D-5).
  `T-209e-a`에서 `npm run docker:backup`과 `docs/backup-restore.md`를 추가해
  `kor_travel_map` app DB + `kor_travel_map_dagster` Dagster metadata DB + RustFS volume cold
  backup 산출물과 검증 절차를 고정한다. `T-209e-b`에서 `npm run docker:restore`와
  `scripts/docker-restore.sh`를 추가해 backup 산출물을 staging DB/volume
  (`kor_travel_map_restore`, `kor_travel_map_dagster_restore`, `kor-travel-map-rustfs-restore`)으로
  복원하는 비파괴 cold restore 자동화를 고정한다. `T-209e-c`에서
  `/admin/backups`, `/admin/restore/{backup_id}` router와 `/admin/backups` UI를 추가해
  artifact 목록과 backup/restore/swap command plan을 노출한다. 최종 잔여로
  `scripts/with-pg-advisory-lock.py` 기반 `maintenance:backup-restore` mutex,
  `scripts/docker-restore-verify.sh` staging smoke/count 검증,
  `scripts/docker-restore-swap.sh` restore hot-swap env 전환을 추가했다.


**Phase 6.5 — TripMate 요구사항 대조 후속 (2026-06-06, `T-213`)**

정본 리포트는 `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`. TripMate
문서의 기준 kor-travel-map commit이 `b775c74`라 현재 `origin/main`과 차이가 크므로, 단순
호환 shim이나 최소 수정이 아니라 ADR-045 OpenAPI 독립 프로그램 모델 기준으로 완성도,
안정성, 확장성, 성능을 우선한다.

- [x] **T-213a — TripMate 요구사항 대조 리포트 작성.**
  TripMate `docs/kor-travel-map-requirements.md` K-1~K-14를 현재 user OpenAPI 7개 path,
  repo/client 구현, ADR-045/046 경계와 대조해 이미 충족/부분 충족/신규 task를 분리한다.
- [x] **T-213b — 일반 좌표 기준 `/features/nearby` 구현.** (claude, 2026-06-06)
  `GET /features/nearby`(`lon`/`lat`/`radius_m`≤100km/`kind[]`/`category[]`/`status[]`/
  `provider[]`/`sort`/`page_size`/`cursor`) + repo `features_nearby` + client
  `features_nearby`를 추가했다. 입력 좌표를 `origin` CTE에서 1회만 5179로 변환하고
  술어는 STORED `coord_5179`에 `ST_DWithin`/거리 정렬(ADR-012, by-target nearby와 동일
  candidates CTE — row/cursor/page helper 재사용). 응답 `{data:{origin,items,
  next_cursor}, meta}`, user OpenAPI subset 포함(`export_openapi.py` USER_OPERATIONS).
  검증: 격리 WSL sandbox에서 OpenAPI 재생성/drift green, ruff/mypy/lint-imports,
  admin router unit(검증 422 + spec presence), client unit, **PostGIS 통합 4건**
  (필터/거리·cursor·invalid·EXPLAIN ADR-012 stored-coord_5179 술어 확인). 참고: 소량
  테스트 데이터에서 planner가 GiST 대신 seqscan을 고를 수 있어 인덱스 *이름*은
  단언하지 않고 술어 대상 컬럼/per-row transform 부재로 ADR-012를 검증한다.
- [x] **T-213c — bbox clustering(`cluster_unit`) 설계/구현.** (claude, 2026-06-06)
  **설계 결정: 서버 행정구역 rollup**(client-side·grid bucket 대신) — feature에 이미
  있는 `sido_code`/`sigungu_code`/`legal_dong_code`를 GROUP BY해 geometry 계산 없이
  region별 count + 평균 좌표(대표 마커 위치)를 낸다. repo `cluster_features_in_bbox`
  (cluster_unit allowlist→고정 코드 컬럼, bbox는 stored `coord` GIST `&&`, ADR-012
  술어 변환 없음) + `/features/in-bounds`에 `cluster_unit`(sido|sigungu|eupmyeondong)
  쿼리 추가, 미지정 시 `zoom`으로 유도(≤7=sido/≤10=sigungu/≤13=eupmyeondong/≥14=개별).
  응답 `data.clusters[]`(cluster_unit None이면 `items`, 아니면 `clusters`,`items=[]`).
  검증: router unit 4(cluster/zoom 유도/고줌 개별/invalid 422), PostGIS rollup 통합 2
  (sigungu·sido count+centroid, invalid), 격리 sandbox에서 OpenAPI drift/frontend
  types/ruff/mypy/lint-imports green.
- [x] **T-213d — `AsyncKorTravelMapClient` read parity 보강.** (claude, 2026-06-06)
  `get_features`(→`get_feature_rows_by_ids`), `search_features`(→repo
  `search_features`), `features_nearby_poi_cache_target`(→repo 동명 함수) 3개 read
  메서드를 `AsyncKorTravelMapClient`에 추가했다. 기존 repo 함수에 위임만 하므로 새 SQL/
  스키마 없음. TripMate 운영은 계속 OpenAPI만 쓰지만, API/Dagster 내부와 테스트가
  admin `/features/{batch,search,nearby-by-target}`와 같은 read path를 재사용한다.
  DB 미접근 unit test 3건(repo/세션 monkeypatch pass-through). **T-213b/e/g의 선행
  기반.**
- [x] **T-213e — weather card/시계열 사용자 API.** (claude, 2026-06-06)
  `feature.feature_weather_values` 테이블 신설(**alembic 0017**, PK=결정적
  `weather_value_key` ADR-010, card 복합 인덱스 + valid_at BRIN ADR-013, feature FK
  CASCADE). `infra/weather_repo.py`: `load_weather_values`(멱등 upsert) +
  `build_weather_card(feature_id, asof, freshness_seconds)` — (forecast_style,
  metric_key)별 `COALESCE(valid_at,observed_at,issued_at)` 최신 DISTINCT ON, asof 필터,
  `source_styles` trace, `is_stale`(기본 6h). `GET /features/{feature_id}/weather` user
  spec 포함 + client `build_weather_card`/`load_weather_values`. 검증: PostGIS 통합 2
  (load/card/asof/freshness/idempotent/empty) + alembic upgrade 0017 체인 + router unit 2.
  격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports green.
  **→ T-213a~h 전부 완료.**
- [x] **T-213f — category catalog HTTP/runtime 표면.** (claude, 2026-06-06)
  `GET /categories`(`routers/categories.py`) — 144건 정적 카탈로그(code/depth/tier/
  label/path/maki_icon/...)를 노출. `include_counts`/`active_only`면 repo
  `category_feature_counts`로 DB 분포(`db_feature_count`/`db_active`) 합침. 정적
  카탈로그는 모듈 로드 시 1회 구성(ADR-030). user OpenAPI subset 포함, frontend
  types 재생성. drift gate는 `@kor-travel-map/map-marker-react` `maki.ts`가 **name→glyph**
  구조라 ADR-029 원안의 category↔TS 1:1이 아니라 **완화형**(TS maki name kebab 유효성
  + 핵심 provider maki 글리프 커버 + Python 카탈로그 self-consistency)으로 적용
  (`tests/unit/test_category_catalog_contract.py`). 부수: `category/__init__.py`
  docstring tier 개수(34/73/29)·`category.md` icon 개수(57) 코드 기준 reconcile.
  검증: 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports +
  admin router 3·main contract 3·PostGIS counts 1건 green.
- [x] **T-213g — provider export + sync state/last-sync 표면.** (claude, 2026-06-06)
  `kortravelmap.providers`에 knps/krheritage 변환 함수·dataset/provider 상수 re-export.
  `AsyncKorTravelMapClient`에 `get_sync_state`/`list_sync_states`(read) +
  `record_sync_success`/`record_sync_failure`(write, 1 transaction) helper 추가.
  `GET /providers/{provider}/last-sync`(`routers/providers.py`) — `sync_state_repo.
  list_sync_states`(provider + dataset_key/sync_scope 필터) 기반, `items[]`(dataset/
  scope/status/last_success_at/last_failure_at/consecutive_failures) 반환, **내부
  cursor 비노출**, 매칭 0건이면 404. user OpenAPI subset 포함, frontend types 재생성.
  검증: router unit 3(spec/404/200 cursor-exclude), providers export unit 1, PostGIS
  list 통합 1, client unit, 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/
  lint-imports green.
- [x] **T-213h — public health/version.** (claude, 2026-06-06)
  `GET /health`(liveness, 의존 없는 정적 200, `{data:{status,service},meta}`) +
  `GET /version`(`{data:{version, kor_travel_map_version, openapi_version, commit},meta}`,
  commit=env `KOR_TRAVEL_MAP_GIT_COMMIT`)를 `routers/public_status.py`로 추가. liveness는
  DB 장애에도 동작해야 하므로 `features_routes_enabled`와 무관하게 **항상 mount**.
  user OpenAPI subset 포함, frontend types 재생성. router unit 5(spec presence/
  liveness/version/env commit/feature-off 시에도 mount). **deep readiness**(DB/RustFS/
  Dagster `/ops/health-deep`)는 후속 — liveness를 DB-free로 유지하기 위해 분리.


## 완료

- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md, performance.md, test-strategy.md
  - docs/backend-package.md, agent-guide.md, dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md, provider-contract.md, external-apis.md
- [x] T-001b — ADR-020 + 디버그 UI 별도 패키지로 분리 (완료: 2026-05-24)
  - decisions(ADR-020), architecture, backend-package, debug-ui-package(신규),
    AGENTS, SKILL, CLAUDE, README, pyproject(`[api]` 제거 + forbidden 계약 추가),
    .env.example, test-strategy 갱신
  - `packages/kor-travel-map-admin/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001c — ADR-021/022/023 + PR-only workflow + `kortravelmap` namespace +
      kraddr-base category 이전 (완료: 2026-05-24, PR#1)
  - AGENTS/SKILL/CLAUDE/architecture/agent-guide 일괄 갱신
  - `docs/category.md` 신설
  - import-linter 계약 placeholder
- [x] T-016 — `python-mois-api` 활용 feature 적재 4단계 lifecycle docs +
      ADR-024 canonical name 정정 (완료: 2026-05-24, PR#3)
  - `docs/mois-feature-etl.md` 신설 + 195 슬러그 카탈로그
  - 일괄 krmois→mois rename (`mois-license-feature-etl.md` 등)
- [x] T-015 — forest rename + category Tier 1~4 catalog + KNPS data.go.kr
      카탈로그 + 모든 ETL doc category 정보 audit (완료: 2026-05-25, PR#5)
  - `outdoor-feature-etl.md` → `forest-feature-etl.md` (git mv)
  - `docs/category.md` Tier 1~4 상세 테이블 (141건)
  - KNPS dataset 7건 카탈로그 + 옵션 A/B 비교 (옵션 B 권고)
- [x] T-017a — ADR-025 디버그 UI frontend = `maplibre-vworld-js` + ADR-025
      사용자 보강 (key 공유 + upstream 직접 PR) + ADR-026 TripMate 사용자 UI도
      maplibre-vworld 통일 (완료: 2026-05-25, PR#6 merged)
  - `docs/decisions.md` ADR-025 + ADR-026
  - `docs/debug-ui-package.md` §14 frontend 사양
  - `packages/kor-travel-map-admin/frontend/` skeleton
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호
- [x] T-017b — ADR-025 2차 사용자 보강 (frontend 빌드 도구 Vite → **Next.js**
      정정) (완료: 2026-05-25, PR#11 merged)
  - `docs/decisions.md` ADR-025 §사용자 보강 2차 추가
  - `docs/debug-ui-package.md` §14 Next.js 전환 + 운영 옵션 3가지
  - `packages/kor-travel-map-admin/frontend/` skeleton 일괄 Next.js 전환
    (package.json / .env.example / .gitignore / README / **next.config.js**
    신설), `VITE_*` → `NEXT_PUBLIC_*`
  - `docs/external-apis.md` / `docs/tripmate-integration.md` §14.5 / `docs/
    tasks.md` (T-100 재해석) 동기
- [x] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (완료: 2026-05-25, PR#10 merged)
  - ADR-024~033 + T-101~103 + 명명 일치화 + 코드 변경 모두 inline
- [x] T-013b — 잔존 `krmois` → `mois` 명명 sweep (완료: 2026-05-25, PR#10
      merged) — 4건 정리 (forest §11.1 / mois-license §payload / journal 2건),
      ADR-024 narrative 등 역사 기록 컨텍스트는 유지
- [x] T-014a — Sprint 1 진입 계획 작성 (완료: 2026-05-25, PR#10 merged)
  - `docs/sprints/README.md` (Sprint 1~5 표 + 공통 진입 게이트)
  - `docs/sprints/SPRINT-1.md` (진입 조건 + 산출물 + DoD + Sprint 2 진입)
  - 실제 Sprint 1 진입 PR은 T-014 본체로 계속 pending (사용자 승인 필요)
- [x] T-017c — ADR-029 (proposed) + `@kor-travel-map/map-marker-react` skeleton
      (완료: 2026-05-25, PR#10 merged)
  - `docs/decisions.md` ADR-029 본문 (MIT, monorepo 위치, peer deps,
    drift gate, 배포 정책)
  - `packages/map-marker-react/` skeleton (`package.json` / `README.md` /
    `vite.config.ts` / `.gitignore`)
  - 실 코드는 T-017 본체 (Sprint 2)
- [x] T-018a — `python-knps-api` upstream scaffold 모니터링 + 본 라이브러리
      ADR-028 (proposed) 작성 (완료: 2026-05-25, PR#12 merged)
  - upstream `digitie/python-knps-api` `6e36990` scaffold 확인
  - `docs/decisions.md` ADR-028 본문
  - `docs/knps-feature-etl.md` 신설 (feature 적재 계약)
  - `docs/forest-feature-etl.md §11` 갱신 (외부 API 표면 + 채택 ✅ 표기)
  - `docs/provider-contract.md` / `docs/external-apis.md` / `pyproject.toml`
    동기
- [x] T-018b — upstream knps-api 측 PR — maki icon 정정 (완료: 2026-05-25,
      knps-api PR#1 open, https://github.com/digitie/python-knps-api/pull/1)
  - `docs/knps-feature-etl.md §4` shelter / barrier 정정 (본 라이브러리
    ADR-027 정합 + Maki 표준 호환)
  - 양방향 PR 워크플로 적용 사례 (ADR-028 §D)
- [x] T-012a — T-101~103 상세 분석을 `docs/performance.md`에 inline (완료:
      2026-05-25, PR#10 merged)
  - §9.3 T-101 (PostGIS MV), §9.4 T-103 (streaming ETL), §9.5 T-102
    (pg_prewarm) — 도입 조건, 부작용, ROI, 절차
- [x] T-012b — ADR-030/031/032/033 enforcement 코드 (완료: 2026-05-25, PR#10
      merged)
  - `pyproject.toml`: import-linter 차단 계약 (cachetools/async_lru/
    aiocache/diskcache + kafka/aiokafka/confluent_kafka/faust), coverage
    Sprint별 schedule 주석
  - `packages/kor-travel-map-api/scripts/export_openapi.py` skeleton
    (ADR-031, `--check` drift gate)


## 폐기 / 재해석

- ~~T-100~~ — "디버그 UI 별도 Next.js 패키지 분리" — **부분 재해석** (PR#11
  2026-05-25):
  - 원래 의도 = Next.js로 별도 패키지화. 실제 구현 = Python 패키지로 분리
    (T-001b, ADR-020) + frontend는 그 안의 `frontend/` 하위에 **Next.js**
    (ADR-025 2차 보강).
  - 즉 "Next.js 미채택"이라고 한 PR#7의 기록은 잘못됨 — ADR-025 2차 보강
    으로 Next.js 채택 확정.


## 머지 history (참조)

| PR | branch | 머지 일자 | 핵심 |
|----|--------|----------|------|
| #1 | `chore/pr-workflow-namespace-rename-category-migration` | 2026-05-24 | ADR-021/022/023 |
| #2 | `docs/v1-to-v2-feature-ports` | 2026-05-24 | T-002~T-011 (14 docs) |
| #3 | `feat/mois-feature-etl` | 2026-05-24 | ADR-024 + mois-feature-etl.md |
| #4 | (merged via #3 lineage) | 2026-05-24 | 동일 |
| #5 | `feat/forest-knps-category` | 2026-05-25 | T-015 (forest rename + KNPS 카탈로그 + category Tier 1~4) |
| #6 | `feat/debug-ui-maplibre-vworld` | 2026-05-25 | ADR-025 + ADR-025 사용자 보강 + ADR-026 |
| #7 | `chore/tasks-md-update` | 2026-05-25 | tasks.md 백로그 |
| #8 | `docs/adr-030-031-032-033-proposed` | 2026-05-25 | ADR-030/031/032/033 proposed |
| #9 | `docs/adr-027-forest-category-expansion` | 2026-05-25 | ADR-027 proposed |
| #10 | `docs/pr10-t012-t018-codify` | 2026-05-25 | ADR-029 + T-013/14a/17c/12a/12b + 명명 sweep + 코딩 |
| #11 | `docs/pr11-debug-ui-nextjs` | 2026-05-25 | ADR-025 2차 보강 (Vite → Next.js) |
| #12 | `docs/pr12-knps-api-integration` | 2026-05-25 | ADR-028 + knps-feature-etl.md |
| #13 | `chore/tasks-md-pr12-merged-update` | 2026-05-25 | tasks.md 백로그 갱신 (PR#12 머지 후) |
| #14 | `docs/pr14-impl-order-sprint-plans` | 2026-05-25 | ADR-034 provider 9단계 + Sprint 2~5 plan |
| #15 | `docs/pr15-governance-sweep` | 2026-05-25 | governance docs sweep + DO NOT bug fix 3건 |
| #16 | `feat/sprint1-entry-adr-accepted` | 2026-05-25 | T-014 Sprint 1 진입 — ADR 027~034 일괄 accepted + fail_under=50 |
| #17 | `feat/sprint1-pr17-scaffolding` | 2026-05-25 | `src/kortravelmap/` PEP 420 scaffolding + `settings.py` + smoke |
| #18 | `feat/sprint1-pr18-category-migration` | 2026-05-25 | `category/` 144건 (kraddr-base 이전 + ADR-027 3건) + 16 tests |
| #19 | `feat/sprint1-pr19-dto-foundation` | 2026-05-25 | `dto/` Feature + 5 detail + NOTICE_TYPES 14 (ADR-027) + AreaDetail hazard_zone + KST + 27 tests |
| #20 | `feat/sprint1-pr20-core-exceptions-id` | 2026-05-25 | `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests |
| #21 | `feat/sprint1-pr21-infra-skeleton` | 2026-05-25 | `infra/crs.py` + `infra/db.py` + testcontainers PostGIS conftest |
| #22 | `feat/sprint1-pr22-ci-import-linter` | 2026-05-25 | CI workflows + import-linter 4 계약 + ADR-002 위반 해소 (dto/_time.py) |
| #23 | `docs/pr23-review-report` | 2026-05-25 | `docs/reports/pr-1-21-review.md` 종합 리뷰 |
| #24 | `fix/pr24-dto-strictness-p0` | 2026-05-25 | review P0-1/2/3 — detail dict 거부 + datetime aware + category 정규식 |
| #25 | `docs/pr25-knps-keyless-sync` | 2026-05-25 | python-knps-api keyless(`06da125f`) 반영 + ADR-028 amendment §H |
| #26 | `feat/pr26-source-record-bundle-dto` | 2026-05-25 | review P0-4 — ID helper 2종 + SourceRecord/Link/FeatureBundle DTO |
| #27 | `docs/pr27-p1-docs-drift-sweep` | 2026-05-25 | review P1 docs drift sweep |
| #28 | `feat/pr28-infra-models-alembic` | 2026-05-26 | `infra/models.py` + Alembic 첫 2 revision (0001/0002) + 통합 테스트 6 |
| #29 | `feat/pr29-core-scoring-providers` | 2026-05-26 | `core/scoring.py`(ADR-016) + `core/providers.py` (canonical 18종) |
| #30~31 | `docs/pr30-31-codegraph-worktree` | 2026-05-27 | agent worktree + codegraph 룰 docs + MCP 등록 |
| #32~33 | `docs/pr32-33-adr-035-043` | 2026-05-27 | 거버넌스 보강 + ADR-035~043 proposed→accepted |
| #34 | `feat/pr34-datagokr-festivals` | 2026-05-27 | Sprint 2 §2.1 datagokr 축제 1차 source (ADR-042) |
| #35 | `feat/pr35-debug-ui-routers` | 2026-05-27 | 디버그 UI `create_app` + health/version + openapi drift gate |
| #36 | `feat/pr36-frontend-skeleton` | 2026-05-27 | Next.js 15 frontend skeleton + TanStack/Zustand (ADR-037) |
| #37 | `feat/pr37-kraddr-base-absorb` | 2026-05-28 | ADR-041 — Address DTO 보강 + `core/address.py` |
| #38 | `feat/pr38-kma-short-forecast` | 2026-05-28 | `WeatherValue` DTO + 3 enum + KMA 단기예보 1차 |
| #39 | `feat/pr39-kma-nowcast` | 2026-05-28 | KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종 |
| #40 | `docs/pr40-provider-status-sweep` | 2026-05-28 | `python-*-api` 라이브러리 status sweep |
| #41 | `feat/pr41-kma-ultra-short-forecast` | 2026-05-28 | KMA 초단기예보 (getUltraSrtFcst) + LGT |
| #42 | `feat/pr42-pricevalue-opinet` | 2026-05-28 | `PriceValue` DTO + opinet 가격 1차 |
| #43 | `feat/pr43-opinet-stations` | 2026-05-28 | opinet `stations_to_bundles` (gas station Feature) |
| #44 | `feat/pr44-etl-preview-router` | 2026-05-28 | 디버그 UI ETL preview 라우터 (fixture dry-run) |
| #45 | `feat/pr45-krex-multi-kind` | 2026-05-28 | Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind |
| #46 | `feat/pr46-kma-weather-alerts` | 2026-05-28 | KMA weather_alerts → notice + krex category fix + ETL 11 dataset |
| #47 | `feat/pr47-etl-live-source` | 2026-05-28 | ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소 |
| #48 | `docs/pr48-worktree-rename-tasks-sweep` | 2026-05-28 | worktree `geo-*`→`kor-travel-map-*` rename + tasks.md 최신화 |
| #49 | `feat/pr49-maplibre-vworld-v010` | 2026-05-28 | maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment) |
| #50 | `docs/pr50-sprint-task-resume-consolidation` | 2026-05-28 | Sprint/task/resume 일관성 재정비 |
| #51~#95 | (Sprint 2 잔여 + Sprint 3) | 2026-05-28~30 | visitkorea enrichment / KMA mid_forecast / ETL live 11 / KNPS·krheritage provider / geocoding REST / `feature_repo` 적재 / consistency F1~F3 / `AsyncKorTravelMapClient` / `/features` debug UI + frontend / dedup queue |
| #96~#114 | (Sprint 4 prep) | 2026-05-30~31 | `/features` UX / `map-marker-react` / geocoding v2 회귀 / NTFS+Windows Git 정책 / Next.js 16 + `maplibre-vworld-js#v0.1.2` |
| #115~#132 | (Sprint 4a) | 2026-05-31~06-01 | MOIS Step A bulk + Step B incremental(cursor) / advisory lock + `ops.import_jobs` / CLI mutex + `status` / `ktmctl import mois`(NDJSON) / dedup self-sibling / geocoder live 재검증 |
| #133 | `feat/cli-dedup-merge` | 2026-06-01 | `ktmctl dedup-merge` + merge primitive + `ops.feature_merge_history`(alembic 0007) + `core.scoring.select_master` (ADR-016) |
| #134 | `feat/step-b-incremental` | 2026-06-01 | MOIS Step B 증분 적재 + `infra/sync_state_repo`(cursor) |
| #135 | `chore/dedup-fp-measurement` | 2026-06-01 | dedup FP 측정 리포트 + 회귀 가드 (가중치 변경 없음) |
| #136 | `feat/step-c-closed` | 2026-06-01 | MOIS Step C 폐업/취소 → feature inactive |
| #137 | `feat/step-d-detail-router` | 2026-06-01 | MOIS Step D on-demand 상세 (debug-ui `/debug/mois-license/{id}`, 캐시만) |
| #138 | `feat/dedup-fp-ops-stats` | 2026-06-01 | dedup 운영 FP 통계 (`status_repo.dedup_fp_stats` + `ktmctl status`) |
| #139 | `feat/consistency-f4` | 2026-06-01 | ADR-033 F4 — dedup 백로그 baseline WARN |
| #140 | `feat/place-phone-enrichment` | 2026-06-01 | Place 전화번호 보강 (`kortravelmap.enrichment`) |
| #141 | `chore/coverage-bar-80` | 2026-06-01 | coverage gate 75→80 (실측 94.12%) — Sprint 4 종료 |
| #142 | `docs/agent-runbooks` | 2026-06-01 | 에이전트 공용 runbook (`docs/runbooks/` agent-workflow + failure-patterns) |
| (post) | (main) | 2026-06-01 | admin OpenAPI cache 문서 (ADR-045 후속) |
| knps-api #1 | `docs/knps-feature-maki-icons` | **open** | maki icon 정정 (shelter / barrier) |
