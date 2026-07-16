# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [ ] `T-ADM-C3e-B2` — provider guard·public wrapper·MCST pair callback (agent A)
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

- [ ] `T-ADM-C3e-B2` — **provider guard·public wrapper tracking** (agent **A**, 의존
  C3e-B1, C3e-B3와 병렬): 모든 live provider resource 앞에 DB-only operation guard를 두고,
  실제 Dagster context의 job·asset selection·run config·run tag를 B1 registry와 대조해
  Launchpad·직접 GraphQL override 및 API/Dagster version 불일치를 provider I/O 전에 차단한다.
  모든 public feature-load asset/KMA wrapper가 raw runner 직전 마지막 ensure와 자기 exact pair
  success를 기록하게 한다. MCST raw runner에는 nullable async pair-completion callback을 주입하되
  `FeatureUpdateAssetRunner` direct raw 경로는 tracking 0을 유지한다. marker 선점 시 provider I/O와
  child 생성 0, ensure 선점 시 selection 전체 freeze, step retry·partial success·shared run과
  MCST 전반 성공/후반 실패를 회귀로 고정한다. 알려진 KNPS direct runner 오염도 이 PR에서
  수정한다. 비기본 point/geometry scope dataset을 `settings.model_copy(update=...)`로 고정해
  fetcher와 asset resource 양쪽에 같은 값을 전달하고 fetch/record mismatch 회귀를 추가한다.
- [ ] `T-ADM-C3e-I` — **C3e 통합·종결** (codex, 의존 C3e-A1/A2/B1/B2/B3/C): 선행 merge마다
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
  표시는 effective `providers[]`/`dataset_keys[]`와 typed `provider_datasets[]` pair를
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
  금지 목록, `/preview` 우선, per-file 저부하 실행표 + 검증 리포트.

현재 codex 실행 순서는 사용자 지시로 **C3e-B1과 C3e-C 병렬 → C3e-B2와 B3 병렬 → C3e-I
→ C45X·C4R 차단 계약 → 기존
C4/C5 PR rebase·수정·CI green·merge → C6a → C6b → C7A → C7 n150**이다. Claude Code
worktree의 C45X/C4R 구현이 정본이다. C3e 종료 뒤 해당 worktree와 PR을 가져와 적대적 상세 리뷰
후 개선을 반영한다. C4/C5는 기존 PR을 정본에 맞게 보강하며 새 구현을 중복 생성하지 않는다.
C6 착수 전 원격에서 C4/C5와 관련 차단 PR의 실제 merge·CI 상태를 확인한다.

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
