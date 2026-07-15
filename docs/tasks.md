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
  - [x] `T-ADM-C3e-D` — canonical operation 문서 계약·적대 리뷰 gate (PR #696)
  - [ ] `T-ADM-C3e-A1` — 0051·operation 계층·frozen repo/client 계약 (agent A)
  - [ ] `T-ADM-C3e-A2` — 공용 root/exact-pair projection·batch query (agent A)
  - [ ] `T-ADM-C3e-B` — Dagster tracking registry·wrapper·run status sensor (agent B)
  - [ ] `T-ADM-C3e-C` — datasets REST/OpenAPI/admin types canonical 소비 (agent A)
  - [ ] `T-ADM-C3e-I` — 통합 rebase·교차 회귀·#679 종료 (codex)
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
- [ ] `T-ADM-C3e-A1` — **0051·operation repository frozen 계약** (agent **A**,
  의존 C3e-D): `ops.import_jobs` typed identity/trigger/registry 컬럼·trim/shape CHECK·feature-kind
  parent constraint trigger·partial unique/index, raw Dagster status/engine timestamp, writer identity
  matrix, idempotent lifecycle와 frozen client DTO/method를 구현한다. C3d cancellation member의
  `operation_kind`/`requires_run_termination` migration·응답/OpenAPI/type과 run-backed queued
  terminate/retry/terminal race를 함께 확장한다. C3d marker/CAS/direct-write inventory, generic
  claim/stale recovery 제외, reserved feature kind의 모든 generic writer fail-closed, migration
  up/down과 invariant conflict를 포함한다. **구현·로컬 gate 완료, PR/CI 대기** — 테스트 전
  적대 리뷰 2인이 S1/S2 0건으로 승인했고, 비-live 전체 1,762건·API 473건·Dagster
  270건(1 skip), frontend unit 82건과 focused migration/cancellation 200건을 통과했다.
  외부 geocoder live 전용 5건은 로컬 upstream HTTP 400으로 분리했으며 C3e 회귀는 없다.
  Ruff, strict mypy 3패키지, import 계약 4/4, OpenAPI/admin type drift, frontend
  type/lint/build도 통과했다. 최종 diff 적대 재리뷰와 원격 CI는 PR 단계가 소유한다.
- [ ] `T-ADM-C3e-A2` — **공용 root/exact-pair projection** (agent **A**, 의존 C3e-A1):
  C3b lineage CTE를 확장해 pipeline/grid/detail이 같은 deterministic pair member/status source를
  쓰고 전 dataset latest batch query와 pair/dataset-only EXPLAIN을 구현한다. feature run
  projected job은 root로 고정하고 pipeline overview를 canonical `operations_by_status`/
  `active_operations`/`failed_operations_24h`로 원자 전환한다. 이 PR이 overview router/schema와 OpenAPI/admin generated
  type, nullable `dagster_run_status`와 authoritative engine 시각까지 함께 바꿔 독립 CI를
  green으로 유지한다.
- [ ] `T-ADM-C3e-B` — **Dagster canonical tracking** (agent **B**, 의존 C3e-A1,
  C3e-A2와 병렬): 모든 public feature-load wrapper와 KMA/MCST를 immutable registry에 연결하고
  definition trigger tag 오분류를 제거한다. event-backed QUEUED/STARTING/STARTED/CANCELING 각 sensor가
  DB-only 1차 ensure하고 NOT_STARTED/MANAGED는 periodic scan/guard가 처리하며,
  guard resource가 provider fetcher 전 ensure, wrapper가 마지막 fallback/pair success를 소유하고
  SUCCESS/FAILURE/CANCELED와 periodic reconcile sensor가 run terminal을 소유한다. MCST에는
  wrapper-owned pair completion callback을 주입한다.
  등록 identity drift fail-closed와 비등록 arbitrary panel-only, pre-resource/queued cancel,
  partial success, multi-asset/shared-run, direct Dagster cancel, sensor default/readiness·selection
  mismatch·중복 delivery와 끝에서 wrap하는 양방향 watermark reconcile을 회귀로 고정한다.
- [ ] `T-ADM-C3e-C` — **datasets REST/OpenAPI 소비** (agent **A**, 의존 C3e-A2):
  독자 recursive SQL과 payload 계보를 제거하고 grid latest/detail recent/timeline이 같은 root와
  pair member status·nullable raw Dagster status·engine 시각을 반환하게 한다. recent cursor/history URL, status vocabulary,
  `db_recorded_canonical_operations` coverage, 공용 DTO/HATEOAS mapper, OpenAPI/admin types를
  완결한다.
- [ ] `T-ADM-C3e-I` — **C3e 통합·종결** (codex, 의존 C3e-A1/A2/B/C): 선행 merge마다
  origin/main rebase하고 교차 회귀·적대 리뷰 2인·전체 CI를 통과시킨다. 일정/수동/갱신/import
  실행과 datasets/pipeline 동일 root 증거를 이슈 #679에 남긴 뒤 닫는다.
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
  홈 작업 상태 위젯은 `/v1/ops/pipeline/overview.operations_by_status`를 정본으로 사용한다.
  `/ops/metrics.import_jobs_by_status` raw physical-row count를 작업 수로 표시하지 않는다.
  **C3b API 소비 정본**(#689):
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

현재 codex 실행 순서는 사용자 지시로 **C3e-D/A1/A2/B/C/I → C45X·C4R 차단 계약 → 기존
C4/C5 PR rebase·수정·CI green·merge → C6a → C6b → C7A → C7 n150**이다. Claude Code
worktree에는 C3e 구현 diff가 없고 설계 기록만 복구됐으므로 문서 gate부터 다시 진행한다.
C4/C5는 기존 PR을 정본에 맞게 보강하며 새 구현을 중복 생성하지 않는다. C6 착수 전 원격에서
C4/C5와 관련 차단 PR의 실제 merge·CI 상태를 확인한다.

공통 규율: 잦은 rebase(origin/main), task 완료 시 상대 agent 2일치 PR(닫힘 무관,
리뷰 반영 PR 제외) 적대적 리뷰→코멘트→이슈→수정→머지. 각 구현 PR은 테스트 전
적대적 리뷰어 2명.

`T-ADM-C3a`~`C3e`는 PR #677 병합 후 적대적 리뷰에서 확인된 C5 차단 후속이다.
순서를 바꾸거나 한 PR로 합치지 않는다. 기존 C5 PR #691은 재작업 대기 상태이며,
**C3e까지 merge·CI green 전에는 신규 C5 구현이나 #691 merge를 진행하지 않는다.**

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
