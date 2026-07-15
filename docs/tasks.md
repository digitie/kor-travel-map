# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [x] `T-ADM-C1` — 플랜 확정 + ADR-064 + tasks 등록 (본 문서 PR)
  - [x] `T-ADM-C2` — backend `/ops/datasets/*` (agent A, PR #676)
  - [x] `T-ADM-C2R` — C2 적대적 리뷰 차단 계약 보강 (agent A, PR #688)
  - [x] `T-ADM-C3` — backend `/ops/pipeline/*` + alembic (agent B, PR #677)
  - [x] `T-ADM-C3a` — pipeline 공용 application service/schema 추출 (#682, PR #687)
  - [x] `T-ADM-C3b` — root operation SQL projection·cursor·다중 식별자 (#679, PR #689)
  - [x] `T-ADM-C3c` — pipeline Dagster run 상세·failure 조회 이식 (#681 — 감사 결과
    전 항목 #687/#690에서 기충족, 잔여범위 감사 기록 PR)
  - [ ] `T-ADM-C3d` — 실제 계층형 취소·Dagster terminate (#680)
  - [ ] `T-ADM-C3d-P1R` — 취소 DB phase 2차 적대 리뷰 보강(본 PR, PR·CI 대기)
  - [ ] `T-ADM-C3d-R2A` — Dagster pre-start generation 실패 복구(agent A, C3d PR 내부)
  - [ ] `T-ADM-C3d-R2B` — browser 취소 계약·canonical live E2E(agent B, C3d PR 내부)
  - [ ] `T-ADM-C3d-R2C` — production bound-client DB 탈출 차단(codex, C3d PR 내부)
  - [ ] `T-ADM-C3e` — schedule/manual canonical operation 영속화 (#679)
  - [ ] `T-ADM-C4R` — C4 UI 소비 계약 수정 (agent A, issue #684, PR 1개)
  - [ ] `T-ADM-C45X` — sync_scope 전파+active request 멱등성 (agent A, issue #686, PR 1개)
  - [ ] `T-ADM-C7A` — ops-live same-origin 인증+무효화 (agent B, issue #685, PR 1개)
  - [ ] `T-ADM-C4` — frontend `/ops/datasets` (agent A)
  - [ ] `T-ADM-C5` — frontend `/ops/pipeline` (agent B)
  - [ ] `T-ADM-C6a` — 존치 화면 링크 재배선 (선착)
  - [ ] `T-ADM-C6b` — 구 표면 삭제 + nav 정리 (선착)
  - [ ] `T-ADM-C7` — live e2e 재작성 + n150 검증 (선착)
- **보류/결정 대기**
  - [ ] `T-101` — **Materialized View 도입 검토**

## 현재 상태

`tasks.md`에는 열린 항목만 둔다. 완료된 Sprint/Phase 이력과 감사 세부 해소 항목은
[`docs/tasks-done.md`](tasks-done.md)와 [`docs/journal.md`](journal.md)를 본다. 2026-06-29
정리 기준 `T-229-buildx`는 추가 추적하지 않고, `T-AUDIT-0616` F-01 옵션 A는
ADR-058의 옵션 B 채택으로 필수 진행 백로그에서 제외한다.

## T-ADM-C — admin ops 통합 재작성 (ADR-064)

정본 설계: [`docs/reports/admin-ops-consolidation-plan-2026-07-14.md`](reports/admin-ops-consolidation-plan-2026-07-14.md)
(적대적 설계 리뷰 2인 반영 확정판). dagster job·provider 운영 표면(7페이지+홈 위젯,
4개 인증 게이트 혼재)을 `/ops/pipeline`(실행·작업)·`/ops/datasets`(상태·정책)
2페이지로 통합 재작성한다. 구 표면은 redirect 없이 폐기(공용 `GET /v1/providers`
계열은 PinVi 계약으로 존치).

- [x] `T-ADM-C1` — **플랜 확정 + ADR-064 + tasks 등록** (본 PR)
- [x] `T-ADM-C2` — **backend datasets 그룹** (agent **A**, 의존 C1, **PR #676**):
  `/v1/ops/datasets`(그리드 join)·`/{provider}/{dataset}`(scope 배열 상세)·
  `refresh-policy` PUT·`preview`(fixture 상시/live opt-in flag). admin 게이트 마운트.
  infra 신규 조회는 `kortravelmap.infra`(coverage·strict 범위). **OpenAPI/types
  재생성 포함**(rebase 충돌은 재생성으로 해소, 수동 병합 금지). 적대적 리뷰
  2인 반영 — S2 transaction 순서 500 수정(실세션 integration 회귀 포함),
  S3 PUT 허용 집합 확장(카탈로그∪잔존 sync∪기존 policy)·`.env.example` flag.
- [x] `T-ADM-C2R` — **C2 적대적 리뷰 차단 계약 보강** (agent **A**, issue
  **#678**, **PR #688**, C4 선행): 서버 계산 freshness(명시적
  `stale_after_minutes`만 사용),
  `eligible_after`와 Dagster 실제 `next_scheduled_at` 분리, root request 우선 최신
  실행 batch projection(N+1/쌍둥이 행 제거), provider/dataset 이슈 분리, orphan
  mutation 금지, fixture-only typed preview(`max_items`/timeout/외부 호출 budget 0/
  `truncated`)를 완결한다. router는 schema/service/query/preview 경계로 분리한다.
  schedule/manual 전체 실행 정본·원자 취소는 **#679**로 분리하며 C3와 함께 해소한다.
- [x] `T-ADM-C3` — **backend pipeline 그룹** (agent **B**, 의존 C1, **PR #677**):
  `/v1/ops/pipeline` overview(+sensor)·executions(DB-only UNION keyset)·
  `/{kind}/{id}`(+cancel)·events(전역)·dagster-runs(보조)·schedules(+PATCH
  cron null·commands 4종)·requests(6-type scope union 전량 승계 + operator/reason)·
  run-now·nux-seen. **alembic: `import_jobs.dagster_run_id` 실컬럼+백필+인덱스** +
  ops_live 스냅샷 전환. OpenAPI/types 재생성 포함. 적대적 리뷰 2인 반영 —
  mixed-version 배포 창 COALESCE 폴백(0048 docstring에 배포 순서+백필 재실행 SQL),
  cursor/식별자 UUID 검증(500→422), 감사 필드(override 삭제·request cancel) 구조화
  로그, 409 Retry-After 헤더 명문화, datasets `dataset_status_repo`에
  `dagster_run_id` 전파.
- [x] `T-ADM-C3a` — **pipeline 공용 application service/schema 추출**
  (agent **B**, 이슈 **#682**, **PR #687**, C3 후속 1/5): `ops_pipeline.py`가 삭제 예정인
  `routers/dagster.py`·`routers/feature_update_requests.py` private 심볼을 직접
  import하지 않도록 Dagster 외부 I/O/transaction application service와 순수
  schema/parser를 분리한다. legacy/new router가 전환 기간 같은 public 모듈을
  사용한다. **동작·HTTP 의미·OpenAPI는 보존**하고 schedule capability/actor/
  problem+json 변경은 이 PR에 섞지 않는다.
- [x] `T-ADM-C3b` — **root operation SQL projection** (agent **B**, 이슈 **#679**,
  **PR #689**,
  C3 후속 2/5, C3a 뒤): recursive SQL에서 import job hierarchy를 component로 먼저
  접고, job별 가장 가까운 request anchor로 branch owner를 결정한다. nested anchor는
  상위 branch를 분리하고, 같은 anchor의 다중 request만 생성 시각·ID로 owner 하나를
  고른다. request가 소유하지 않은 partition은 최상위 import job root로 남긴다. cycle은
  `uuid[] path`로 종료하고 부모 누락은 self-root다. component projection은
  branch/root 기준 `depth DESC, created_at DESC, job_id DESC`, partition별
  `linked_job_count`를 함께 노출한다.
  다중 owner에서 탈락한 request는 `lineage_owner=false`·`requested_job_id`와
  projection 없음으로 보존한다. Python 후접기 금지. keyset total order는
  `(created_at DESC, id DESC, kind DESC)`, 저장 순서·중복을 유지하면서 direct scope
  누락값을 보완한 `providers[]`/`dataset_keys[]`, pair 보존 typed `provider_dataset`,
  direct scope+array membership filter를 포함한다. standalone identity는 미소유
  partition의 event 실컬럼을 정렬 DISTINCT 집계하며 import job payload를 읽지 않는다. root/child
  상태는 덮어쓰지 않고 각각 노출한다. **migration·operation 영속화는 C3e 범위**다.
  로컬 게이트는 root unit 1,285건, API 전체 416건, 관련 PostGIS/
  EXPLAIN integration 10건과 Ruff, strict mypy 155파일, import 계약 4/4,
  OpenAPI/admin types drift를 통과했다. root/agent A 적대적 리뷰 2인은
  S1/S2 0건으로 승인했고 CI 8/8 green 뒤 merge했다.
- [x] `T-ADM-C3c` — **pipeline Dagster run 상세/failure 조회 이식** (agent **A**,
  이슈 **#681**, C3 후속 3/5, C3b 뒤): event cursor와 failure 구조를 신규 그룹에
  이식한다. 개별 상세는 성공만 200이고 `not_found`는
  `404 DAGSTER_RUN_NOT_FOUND`, 연결 실패는 `503 DAGSTER_UNAVAILABLE`,
  설정·GraphQL·응답 오류는 `502 DAGSTER_QUERY_FAILED` RFC7807로 승격한다.
  failure 요약은 현재 event page 범위이며 opaque event cursor는 DB cursor 정본에
  섞지 않는다. 외부 Dagster 링크를 fallback으로 유지하고, iframe 미사용 새 UI의
  pipeline `nux-seen`만 제거한다(legacy route/service/schema는 C6b까지 유지).
  **잔여범위 감사 결과 전 항목 기충족** — 상세 endpoint+cursor+failure 구조+
  RFC7807 3분류+테스트 9건은 #690, pipeline `nux-seen` 계약 삭제와 공용
  `dagster_query_service` 경계(신/구 라우터 공유)는 #687, OpenAPI/admin types
  고정은 #690 재생성분. UI 소비는 C5(#691)/C4R 범위. 감사 기록은 journal
  2026-07-15 (claude, agent A).
- [ ] `T-ADM-C3d` — **실제 계층형 취소** (agent **B**, 이슈 **#680**, C3 후속
  4/5, C3c 뒤): 기존 job/request status CHECK를 늘리지 않고 두 base table에
  `cancellation_id/requested_at/requested_by/reason` marker를 추가한다. C3b와 같은
  request-owner branch/duplicate non-owner/standalone partition/nested-request 경계로
  frozen scope를 만들고, 정규화한 attempt/member/run 행을 대상·결과·재시도 정본으로
  쓴다. root가 terminal이어도 active descendant는 계속 취소하며, ancestor marker 뒤에는
  같은 canonical root transaction lock으로 child attach/enqueue를 직렬화하고 worker
  claim/start/scope write/heartbeat/finish를 marker CAS로 막는다. queued member는 marker 뒤
  DB CAS로 취소하고 running member만 Dagster terminal 확인을 요구한다.
  marker·감사 commit → transaction 밖 Dagster terminate → terminal 재확인 순서를 지키고,
  preliminary canonical resolve 뒤 전용 connection에서 먼저 얻는 canonical root별
  nonblocking session lease로 동시 coordinator를 막는다. lease 전 attempt/marker 생성과 외부
  phase의 열린 lease transaction을 금지한다. orphan
  `in_progress`는 같은 frozen scope에서 재개하고, run별 `termination_reserved_at` NULL CAS를
  첫 권위 `initial_status`·audit와 함께 외부 호출 전에 commit해 attempt별 at-most-once
  dispatch와 crash 복구를 함께 보장한다.
  running은 `CANCELED`만 cancelled, 안전하게 대응되는 `SUCCESS`/`FAILURE`만 done/failed로
  reconcile한다. run id 없는 active local job, mapping 불일치, terminate 실패에는 base
  상태를 거짓으로 바꾸지 않고 member `cancel_failed`와 retryable/failed attempt를
  남긴다. 재시도는 이전 frozen scope의 미해결 member만 복사하며 hierarchy를 재탐색하지
  않는다. 목록/detail DTO는 base status를 덮지 않는 nullable current cancellation overlay
  (`cancellation_id/status/requested_at/requested_by/reason/retryable/
  unresolved_member_count`)를 노출하고 detail은 current
  member/run 결과까지 reload 가능하게 반환한다. terminal root에 active child가 없으면
  durable `already_terminal` no-op 200, 이미 완료한 terminal cancellation은 같은 결과 200
  replay로 Dagster 재호출을 막는다. attempt status는 workflow
  `in_progress|retryable|completed|failed`, 실제 결과는 member/run
  `cancelled|already_terminal|cancel_failed`로 분리한다. feature update는 같은 전용
  `AsyncConnection`에 session advisory lock을 고정해 scope별 짧은 transaction으로 분리하고
  이미 commit된 데이터는 rollback하지 않는다. production asset의 public client도 executor
  session의 physical connection에 결합해 scope data와 checkpoint를 같은 transaction에 두며,
  Dagster failure sensor는 실제 실패 run id를 request/job expected generation CAS로 넘겨
  재큐잉된 행이나 새 running owner를 닫지 않는다.
  body는 reason만 받고 actor는 인증 context에서 파생하며, durable audit·RFC7807
  404/409/502/503·`Retry-After` OpenAPI response header·admin generated type·브라우저 typed
  problem/retry 정보·0050 strict downgrade를 함께 완결한다. 오류 응답도 durable attempt를
  만들 수 있으므로 UI query invalidation/reload는 성공 여부와 무관하게 수행한다.
  marker 수용 테스트는 `update_import_job_payload`, `attach_import_jobs_to_batch`,
  `recover_stale_running_jobs`, import job enqueue/claim/heartbeat/finish/cancel,
  feature update claim/start/matched-scope/finish/cancel과 내부 job start/finish, legacy
  cancel/requeue를 포함한다. marked row의 모든 status/payload/lineage mutation 0건, unmarked
  기존 동작, cancellation-id 일치 coordinator CAS, event/audit append 허용을 unit+PostGIS
  concurrency로 검증하고 base table direct-write SQL inventory가 새 우회 mutator를 거부하게
  한다. 502/503 뒤 GET overlay 복구, no-op 200, 완료 결과 replay 시 attempt/run-call 증가 0도
  API 회귀로 고정한다. GET in-progress와 5xx details의 member/run result는 `pending`을
  허용하고, 200 completed 응답에는 `pending`이 0건이라는 DTO/invariant도 검증한다.
  same-root winner/loser lease와 다른-root 병행, resolve↔lease root 변경, marker·reservation·
  mutation·partial result·finish 각 crash resume, reservation CAS loser 외부 0회, shared run 1회,
  lease backend PID/외부 중 no-tx/exact unlock·invalidate를 통합 테스트로 고정한다. 신규 action과
  legacy import-job/feature-update cancel 세 진입점은 reason-only+인증 actor+동일 coordinator 위임을
  API 테스트로 검증한다. pre-marker lease loser 409는 bounded reload 뒤에도 attempt가 없으면
  canonical root와 `cancellation:null`을 반환한다. `termination_reserved_at`은 GET detail·5xx
  snapshot·OpenAPI·admin generated type에 같은 nullable 필드로 보존한다.
  **문서 우선 gate**: data model/REST/task/journal/resume 계약을 적대적 재승인받기 전에는
  source를 수정하지 않는다.
- [ ] `T-ADM-C3d-P1R` — **취소 DB phase 2차 적대 리뷰 보강** (agent **B**, C3d
  내부 PR, 로컬 gate 완료·PR 대기): queued shared-run 독립 취소, running-only retry, definitive mismatch
  비변경 경로, JSON error NULL 차단을 반영한다. batch consistency/MV 장기 transaction은
  side effect 뒤에만 lineage-global→canonical root lock을 얻어 marker CAS와 finalize를
  원자화하고, CAS 패배는 sentinel rollback 뒤 별도 read transaction으로 reload한다.
  실제 report/MV side-effect rollback과 반대 lock 순서 회귀를 정의했다. phase2 적대 리뷰의
  running 고착·CAS loser·mixed/pending 사실 보존·downgrade TOCTOU·hard invalidation 지적과
  stale run generation CAS·production asset transaction bind·`Retry-After` 기계 계약·mock/live
  E2E 원자 전환까지 구현했다. 생성물 포함 적대 재리뷰와 로컬 전체 gate는 통과했으며,
  C3d PR의 CI green·merge 전이므로 완료로 표시하지 않는다.
- [ ] `T-ADM-C3d-R2A` — **Dagster pre-start generation 실패 복구** (agent **A**,
  C3d PR 내부): sensor가 request `updated_at` generation을 run config/tag에 고정하고,
  executor CAS start 전에 실패한 run의 failure side effect가 `queued + dagster_run_id IS NULL +
  generation 동일`일 때만 `updated_at`을 전진시켜 새 run key를 만든다. old generation이
  재큐잉/새 owner를 덮지 않는 기존 expected run CAS와 함께 pre-start resource/lock 실패 뒤
  다음 sensor run이 실제로 발행되는 회귀를 추가한다. start는 queued 동일 generation 또는
  running 동일 owner만 허용하고, 연결 import job owner CAS가 실패하면 request 변경도 같은
  savepoint에서 rollback한다.
- [ ] `T-ADM-C3d-R2B` — **browser 취소 계약·canonical live E2E** (agent **B**,
  C3d PR 내부): Next BFF가 upstream `Retry-After`를 allowlist 전달하고 proxy 경계 테스트로
  고정한다. 409/502/503 뒤에는 연결 member를 알 수 없는 경우까지 포함해 import-job/
  update-request singular detail·events cache를 실제 key prefix로 invalidate한다. 파괴적 import-job
  live E2E는 임의 queued child를 standalone root로 가정하지 않고 canonical root와 파괴 범위를
  먼저 확인한 안전 대상만 취소한다.
- [ ] `T-ADM-C3d-R2C` — **production bound-client DB 탈출 차단** (codex, C3d PR 내부):
  executor transaction에 bind한 asset client가 `_session_factory` 외 원본 `_engine.connect()`로
  별도 commit하지 못하게 fail-closed 경계를 둔다. production asset 적재·sync state·checkpoint
  전체 rollback과 engine-direct public method 거부를 회귀로 고정한다.
- [ ] `T-ADM-C3e` — **schedule/manual canonical operation 영속화** (agent **B**,
  이슈 **#679**, C3 후속 5/5, C3d 뒤): schedule tick/manual launch/update request/
  import 실행이 같은 canonical operation 정본과 provider/dataset identity를 사용하고,
  stable correlation id·Dagster run id·최종 상태를 기록한다. mixed-version 백필·
  인덱스·datasets recent execution 연결까지 포함한다.
- [ ] `T-ADM-C4R` — **C4 UI 소비 계약 수정** (agent **A**, issue **#684**,
  **PR 1개**, 의존 C2R·C3e): freshness/schedule/latest operation/orphan/preview의
  보강 계약을 UI 상태·조작 모델에 반영한다. `T-ADM-C4` 완료 전에 반드시 머지한다.
- [ ] `T-ADM-C45X` — **sync_scope 전파 + active request 멱등성** (agent **A**,
  issue **#686**, **PR 1개**, 의존 C2R·C3e): datasets→pipeline 갱신 폐루프가 정확한
  scope를 보존하고 active 중복 요청을 만들지 않게 한다. C4/C5 실행 조작 완료의
  선행 조건이다.
- [ ] `T-ADM-C7A` — **ops-live same-origin 인증 + query invalidation** (agent
  **B**, issue **#685**, **PR 1개**, 의존 C4·C5): 브라우저 live 연결을 same-origin
  인증 경계로 옮기고 datasets/pipeline query invalidation을 연결한다. C7 live gate
  전에 반드시 머지한다.
- [ ] `T-ADM-C4` — **frontend `/ops/datasets`**
  (agent **A**, 의존 C2R·C3e·C4R·C45X): 그리드(3원
  행·never_run/stale 구분·이슈 배지)+drawer(정책 편집·ETL preview·지금 갱신 인라인
  폐루프·Feature 보기)+mock e2e.
- [ ] `T-ADM-C5` — **frontend `/ops/pipeline`** (agent **B**, 의존 C3e·C45X): 상태
  스트립(+sensor)·타임라인(자동 갱신 1페이지 한정+"새 실행 N건" 배지)·Dagster runs
  패널(degrade)·전역 이벤트 탭·스케줄 패널·요청 dialog(MOIS 조건부 경고)+mock e2e.
  홈 위젯 소스(overview vs `/ops/metrics`) 결정 포함. **C3b API 소비 정본**(#689):
  (a) 타임라인은 request branch 또는 standalone root를 행 하나로 노출하며,
  descendant job을 별도 행으로 중복 노출하지 않는다. (b) provider/dataset 필터와
  표시는 effective `providers[]`/`dataset_keys[]`와 typed `provider_dataset` pair를
  사용한다. (c) request root의 상태와 `projected_job` 상태·진행률·단계를
  분리해 표시한다. standalone root는 자체 진행률을 쓰고 `projected_job.detail_url`로
  대표 descendant 상세에 연결한다. Dagster run 상세는 C3c가
  `GET /v1/ops/pipeline/dagster-runs/{run_id}`로 추가하며 C5는 이 정본을 소비한다.
- [ ] `T-ADM-C6a` — **존치 화면 링크 재배선** (선착, 의존 C4·C5): entity-link kind
  재매핑(1급)+직접 href 9파일+live.ts topic 매핑+HATEOAS `_job_links`+
  scenario catalog. 구 페이지 제거 **전** 독립 PR.
- [ ] `T-ADM-C6b` — **구 표면 삭제** (선착, 의존 C6a): 라우트 6종·라우터
  ~30 endpoint·구 훅·mock spec 19파일 삭제 + nav/홈 정리 + OpenAPI 재생성(삭제분).
  C3a/#687에서 Dagster application service/schema와 feature update service/schema의
  public 공유 모듈 추출을 완료했다. legacy router를 삭제해도 이 public 모듈은
  유지하며, 스케줄 쓰기의 200+`status=error` envelope을 404/502
  problem+json으로 승격할지만 이 시점에 검토한다.
  ops_live dagster 스냅샷의 payload COALESCE 폴백 제거(순수 실컬럼 전환)도 구
  이미지 소진+0048 백필 SQL 재실행 확인 후 이 시점에 재검토.
- [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (선착, 의존 C6b·C7A): 기존 게이트
  체계(PART A/B/C·`finally` 복원) 승계, SAFE provider(kma)·쿼터-민감 provider(OpiNet)
  금지 목록, dry_run 우선, per-file 저부하 실행표 + 검증 리포트.

현재 codex 실행 순서는 사용자 지시로 **C3d merge·#680 종료 → Claude Code worktree의
C3e 작업 회수·완료 → adm-c5 merge 확인 → C6a → C6b → C7**이다. C4/C5를 이 실행
흐름에서 새로 구현하지 않으며, C3e는 Claude worktree의 branch/commit/dirty diff를 먼저
보존적으로 조사해 가져온 뒤 별도 PR로 완결한다. C6 착수 전 원격에서 C4/C5와 관련 차단
PR의 실제 merge·CI 상태를 확인한다.

공통 규율: 잦은 rebase(origin/main), task 완료 시 상대 agent 2일치 PR(닫힘 무관,
리뷰 반영 PR 제외) 적대적 리뷰→코멘트→이슈→수정→머지. 각 구현 PR은 테스트 전
적대적 리뷰어 2명.

`T-ADM-C3a`~`C3e`는 PR #677 병합 후 적대적 리뷰에서 확인된 C5 차단 후속이다.
순서를 바꾸거나 한 PR로 합치지 않으며, **C3e까지 merge·CI green 전에는 C5를
시작하지 않는다.**

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
