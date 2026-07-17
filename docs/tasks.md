# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [ ] `T-ADM-C7A` — ops-live same-origin 인증+무효화 (agent B, issue #685, PR 1개)
  - [ ] `T-ADM-C6b` — 구 표면 삭제 + nav 정리 (선착)
  - [ ] `T-ADM-C7B-720` — datasets 이슈 필터 의미 통일 (issue #720, frontend-only, PR 1개)
  - [ ] `T-ADM-AUD-718` — 갱신 정책 BIGINT revision CAS (issue #718, migration 0056, PR 1개)
  - [ ] `T-ADM-AUD-686` — KMA 유효 대상 0건 fail-closed (issue #686, PR 1개)
  - [ ] `T-ADM-C7B-API` — active projection·exact-scope 이력 API (issues #712/#719, migration 0057, PR 1개)
  - [ ] `T-ADM-C7B-UI` — exact-scope 조작·이력 UI 소비 (issues #712/#719, PR 1개)
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

- [ ] `T-ADM-C7A` — **ops-live same-origin 인증 + query invalidation** (agent
  **B**, issue **#685**, **PR 1개**, 의존 C4·C5): 브라우저 live 연결을 same-origin
  인증 경계로 옮기고 datasets/pipeline query invalidation을 연결한다. C7 live gate
  전에 반드시 머지한다.
- [ ] `T-ADM-C6b` — **구 표면 삭제** (선착, 의존 C6a): 라우트 6종·라우터
  ~30 endpoint·구 훅·mock spec 19파일 삭제 + nav/홈 정리 + OpenAPI 재생성(삭제분).
  C3a/#687에서 Dagster application service/schema와 feature update service/schema의
  public 공유 모듈 추출을 완료했다. legacy router를 삭제해도 이 public 모듈은
  유지하며, 스케줄 쓰기의 200+`status=error` envelope을 404/502
  problem+json으로 승격할지만 이 시점에 검토한다.
  ops_live dagster 스냅샷의 payload COALESCE 폴백 제거(순수 실컬럼 전환)도 구
  이미지 소진+0048 백필 SQL 재실행 확인 후 이 시점에 재검토.
- [ ] `T-ADM-C7B-720` — **datasets 이슈 필터 의미 통일** (issue **#720**,
  **frontend-only**, **PR 1개**, 의존 C6a): `이슈 있음`을 dataset 또는 provider
  open issue가 하나라도 있는 행으로 정의하고 badge·filter 의미를 일치시킨다.
  provider-only, dataset-only, 양쪽 모두, 양쪽 모두 없음 네 경우를 unit/mock E2E로
  고정한다. C6a 뒤 시작하며 C6b·C7A와 병렬로 진행하고, API·OpenAPI·DB schema는
  변경하지 않는다.
- [ ] `T-ADM-AUD-718` — **갱신 정책 BIGINT revision CAS** (issue **#718**,
  **migration 0056**, **PR 1개**, 의존 C7A/0055):
  `ops.provider_refresh_policies`에 `BIGINT NOT NULL DEFAULT 1`과 양수 CHECK를 둔
  단조 revision을 추가하고, 전체 정책 write를 `expected_revision` 조건부 갱신과
  원자적 `revision + 1`로 바꾼다. 불일치는 write 없이 현재 서버 record/revision을
  포함한 typed 409로 반환하고 UI draft를 보존한다.
  두 독립 transaction의 동일 revision 경쟁, create/update 구분, rollback과 OpenAPI/UI
  충돌 복구를 검증한다.
- [ ] `T-ADM-AUD-686` — **KMA 유효 대상 0건 fail-closed** (issue **#686**,
  **PR 1개**, migration 없음, `T-ADM-AUD-718`과 병렬): C45X가 완성한 typed
  scope·active request 멱등성 위에서 KMA target 해석 결과가 0건이면 dispatch/provider
  I/O/sync-state write 전에 거절한다. 요청 target과 active membership의 교집합이
  비는 경우를 typed 오류와 durable operation 증거로 노출하고, operation 중복·provider
  호출·cursor/timestamp 변경이 없음을 통합 테스트로 고정한다.
- [ ] `T-ADM-C7B-API` — **active projection + exact-scope event/history API**
  (issues **#712/#719**, **migration 0057**, **PR 1개**, 의존
  `T-ADM-AUD-718`/0056): canonical root/member와 effective `sync_scope`를 기준으로
  active operation projection과 event/history 조회 경계를 typed DB 열·제약·실제
  access path로 고정한다. exact-scope 조건을 cursor/LIMIT 전에 적용하고 run/event
  continuation과 canonical history URL을 모두 반환한다. 두 scope 혼합과 page limit 초과,
  stale/terminal/active 조합을 실제 DB/API 통합 테스트로 증명한다.
- [ ] `T-ADM-C7B-UI` — **exact-scope 조작·이력 UI 소비** (issues **#712/#719**,
  **PR 1개**, 의존 C7B-API·C7A): 잘못된 dataset/scope deep link는 다른 행으로
  폴백하지 않고 fail-closed하며, provider-only URL은 실제 선택 tuple로 canonicalize한
  뒤에만 조작을 허용한다. scope capability·active operation 링크를 선제 소비하고
  run/event continuation을 `더 보기` 또는 canonical pipeline history로 끝까지 탐색한다.
  local draft와 back/forward/focus 의미를 보존하고 mock/live UI E2E로 POST tuple과 URL,
  requested/effective scope를 대조한다.
- [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (선착, 의존
  C6b·C7A·C7B-720·AUD-686·C7B-UI): 기존 게이트
  체계(PART A/B/C·`finally` 복원) 승계, SAFE provider(kma)·쿼터-민감 provider(OpiNet)
  금지 목록, `/preview` 우선, per-file 저부하 실행표 + 검증 리포트. 임시 POI target을
  생성·복원하며 `external_system:*` 생성/200 재사용/run-now identity, membership
  fingerprint 변화와 grid cap 초과 fail-closed·scope별 durable failure를 검증한다.
  C4R의 운영 종결 이슈 #684/#686/#712와 후속 #718/#719/#720도 이 live 증거를
  첨부한 뒤 닫는다.

병렬 wave는 다음처럼 고정한다. **Wave 1**은 C6a 뒤 C6b·C7A/0055·C7B-720을
병렬 진행한다. **Wave 2**는 C7A/0055 뒤 AUD-718/0056과 AUD-686을 병렬 진행한다.
**Wave 3**은 AUD-718/0056 뒤 C7B-API/0057, **Wave 4**는 C7B-API와 C7A 뒤
C7B-UI, 마지막은 C7 n150이다. C45X-B·C4/C4R·C5는 완료 이력으로 옮겼다.
C7A의 query-key 결선은 C6b merge 뒤 rebase하고, 각 wave 시작·PR 직전·병합 직후
원격 main에 자주 rebase한다.

Alembic은 병렬 branch에서 복수 head를 만들지 않는다. migration 정본은
**C7A `0055` → AUD-718 `0056` → C7B-API `0057`** 단일 chain이며, 후속 migration
소유자는 직전 migration PR이 main에 병합된 뒤 실제 `down_revision`을 확인하고
착수한다. C7B-720·AUD-686·C7B-UI는 migration을 만들지 않는다.

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
