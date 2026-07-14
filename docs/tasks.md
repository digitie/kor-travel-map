# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [x] `T-ADM-C1` — 플랜 확정 + ADR-064 + tasks 등록 (본 문서 PR)
  - [x] `T-ADM-C2` — backend `/ops/datasets/*` (agent A, PR #676)
  - [x] `T-ADM-C3` — backend `/ops/pipeline/*` + alembic (agent B, PR #677)
  - [x] `T-ADM-C4` — frontend `/ops/datasets` (agent A)
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
- [x] `T-ADM-C4` — **frontend `/ops/datasets`** (agent **A**, 의존 C2): 그리드(3원
  행·never_run/stale 구분·이슈 배지)+drawer(정책 편집·ETL preview·지금 갱신 인라인
  폐루프·Feature 보기)+mock e2e. 지금 갱신은 `POST /ops/pipeline/requests`(#677)
  직접 호출 + `feature_update_request:{id}` WS/폴링 추적. 딥링크
  `?provider=&dataset=&sync_scope=&panel=` 초기 상태. nav "데이터셋" 추가(구 항목
  제거는 C6b). mock e2e 12 시나리오 — 로그인 게이트(#520)는 live suite의
  `E2E_ADMIN_PASSWORD` 관례로 대응.
- [ ] `T-ADM-C5` — **frontend `/ops/pipeline`** (agent **B**, 의존 C3): 상태
  스트립(+sensor)·타임라인(자동 갱신 1페이지 한정+"새 실행 N건" 배지)·Dagster runs
  패널(degrade)·전역 이벤트 탭·스케줄 패널·요청 dialog(MOIS 조건부 경고)+mock e2e.
  홈 위젯 소스(overview vs `/ops/metrics`) 결정 포함. **C3 API 소비 전제**(#677):
  (a) 타임라인 UNION은 update request와 그 쌍둥이 `kind=feature_update_request`
  import job을 **모두** 행으로 노출한다 — UI가 연결 필드(`job_id`/`request_id`)로
  이중 행을 접되, 페이지 경계로 쌍이 분단되면 지연 접기(degrade)로 처리한다.
  (b) 쌍둥이 job 행은 `provider`가 NULL이라 provider 필터 시 job 쌍만 목록에서
  탈락한다(request 행 기준으로 판단). (c) `progress`/`current_stage`는 job 쌍에서
  취득한다(request 행에는 없음). 그리고 구 dagster run 상세 GET은 신규 그룹에
  없다(설계대로) — C5는 그 UI 패턴을 이식하지 말고 목록+Dagster UI 외부 링크로
  구성한다.
- [ ] `T-ADM-C6a` — **존치 화면 링크 재배선** (선착, 의존 C4·C5): entity-link kind
  재매핑(1급)+직접 href 9파일+live.ts topic 매핑+HATEOAS `_job_links`+
  scenario catalog. 구 페이지 제거 **전** 독립 PR.
- [ ] `T-ADM-C6b` — **구 표면 삭제** (선착, 의존 C6a): 라우트 6종·라우터
  ~30 endpoint·구 훅·mock spec 19파일 삭제 + nav/홈 정리 + OpenAPI 재생성(삭제분).
  **선행 전제(#677)**: `routers/ops_pipeline.py`가 구 라우터(`dagster.py`·
  `feature_update_requests.py`)의 private 심볼 ~20개(GraphQL 조립·파서·override
  CRUD·cron 가드·scope union 모델·`_enqueue`)를 import 재사용 중 — 구 라우터 삭제
  **전에** 공유 조립/DTO를 중립 모듈로 이식해야 한다. 이식 시점에 스케줄 쓰기의
  200+`status=error` envelope을 404/502 problem+json으로 승격할지 함께 검토.
  ops_live dagster 스냅샷의 payload COALESCE 폴백 제거(순수 실컬럼 전환)도 구
  이미지 소진+0048 백필 SQL 재실행 확인 후 이 시점에 재검토.
- [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (선착, 의존 C6b): 기존 게이트
  체계(PART A/B/C·`finally` 복원) 승계, SAFE provider(kma)·쿼터-민감 provider(OpiNet)
  금지 목록, dry_run 우선, per-file 저부하 실행표 + 검증 리포트.

공통 규율: 잦은 rebase(origin/main), task 완료 시 상대 agent 2일치 PR(닫힘 무관,
리뷰 반영 PR 제외) 적대적 리뷰→코멘트→이슈→수정→머지. 각 구현 PR은 테스트 전
적대적 리뷰어 2명.

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
