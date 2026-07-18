# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [ ] `T-ADM-C6c` — PinVi legacy ops caller canonical 전환 + 인증 계약 복구
  - [ ] `T-ADM-C7C` — live invalidation causal receipt + target 조건부 삭제
  - [ ] `T-ADM-C7` — live e2e 재작성 + n150 검증 (C6c 뒤)
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

- [ ] `T-ADM-C6c` — **PinVi legacy ops caller canonical 전환 + 인증 계약 복구**
  (C7 선행, PR #730 재검증에서 확정): PR #724가 `/v1/ops/dagster/summary`,
  `/v1/ops/providers*`, `/v1/ops/import-jobs*`를 clean-cut한 뒤에도 PinVi 최신 main의
  admin client·provider-sync
  proxy·unit test가 해당 경로를 호출하므로, PinVi caller를 `/v1/ops/datasets`와
  `/v1/ops/pipeline` 계약으로 전환하고 양 저장소 contract test를 같은 commit 조합으로 고정한다.
  KTM frontend BFF secret을 공유하거나 trusted frontend `/32`를 넓히지 말고, PinVi server에
  필요한 최소 service/operator principal과 route policy를 명시한다. service 권한은 canonical
  GET read와 exact import-job cancel로 제한하고 schedule/policy/request mutation은 허용하지
  않는다. n150은 `OPS_PRINCIPAL_REQUIRED=true`와 read/cancel non-empty pair를 강제하며 local
  opt-out은 both absent 또는 both explicit empty만 허용한다. 두 token은 모든 whitespace를
  금지하고 서로 및 admin BFF/service token과 달라야 한다. actor는 설정 불가능한
  `service:pinvi` 상수이고 제거된 actor env는 거부한다. OpenAPI는 GET/exact cancel만
  AdminBFF 또는 OpsToken, 나머지 mutation은 AdminBFF 전용으로 정확히 선언하며 API ops env가
  Dagster web/daemon에 들어가면 entrypoint가 fail-closed한다.
  완료 조건은 PinVi production
  코드·테스트의 삭제 경로 0건, canonical success와 principal 없음/오류 scope의 typed
  401/403/422, raw/debug/BFF 우회 0건, 배포 순서와 rollback image가 명시된 cross-repo smoke다.

- [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (C6c 뒤, 의존
  C6b·C7A·C7B-720·AUD-686·C7B-UI·C6c·C7C): 기존 게이트
  체계(PART A/B/C·`finally` 복원) 승계, SAFE provider(kma)·쿼터-민감 provider(OpiNet)
  금지 목록, `/preview` 우선, per-file 저부하 실행표 + 검증 리포트. 임시 POI target을
  생성·복원하며 `external_system:*` 생성/200 재사용/run-now identity, membership
  fingerprint 변화와 grid cap 초과 fail-closed·scope별 durable failure를 검증한다.
  실제 Chrome에서 없음/변조 ticket은 data frame 0건 + `CloseEvent.code===4401`,
  signed-expired ticket은 data frame 0건 + `4408` 후 fresh ticket 재연결을 증거로
  남긴다. C4R의 운영 종결 이슈 #684/#686/#712와 후속 #718/#719/#720은 최종
  live 증거를 첨부한 뒤 닫는다.

- [ ] `T-ADM-C7C` — **live invalidation causal receipt + target 조건부 삭제**
  (C7 선행): POI target PUT/DELETE 성공 응답 `meta.dataset_projection_revision`을 source
  transaction 안에서 읽어 반환하고, C7은 같은 socket의 `dataset_projection` update frame이
  `data.live_revision >= receipt`를 전달한 경우에만 causal invalidation으로 인정한다(snapshot 및
  top-level fingerprint revision 제외). Alembic 0058의 server-owned `lock_version`으로
  `ETag: "{canonical_uuid}:{version}"`을 만들며 DELETE는 body `entity_tag`를 합성 없이
  `If-Match`로 수신한다. repository soft-delete는 natural key row lock 뒤 UUID+version 조건을
  검증해 GET→DELETE 사이 PUT/delete-recreate 경쟁을 `412`로 닫는다. link sync는 UUID 순서로 모든
  active parent를 먼저 KEY SHARE lock한 뒤 link를 교체해 delete와 parent→link 순서로 직렬화한다.
  API·admin UI·OpenAPI·생성 타입·일반/live E2E를 함께 갱신한다.
  구현·2인 적대 리뷰·로컬 gate와 admin OpenAPI/생성 타입 검증을 완료했으며 user OpenAPI는
  불변이다. 현재 남은 완료 조건은 최신 main rebase와 CI green·승인·병합이다. header 누락은 RFC7807 `428`,
  weak·wildcard·쉼표 결합 multiple·물리적 duplicate line·malformed 값은 RFC7807 `422` 계약으로
  검증한다.

병렬 wave는 다음처럼 고정한다. **Wave 1**의 C6b·C7A/0055·C7B-720,
**Wave 2**의 AUD-686·AUD-718/0056, **Wave 3**의 C7B-API/0057,
**Wave 4**의 C7B-UI까지 완료했다. 현재는 누락된 소비자 선전환을 C6c로 복구한 뒤
C7 n150을 수행한다.
C45X-B·C4/C4R·C5·C6a·C6b·C7A·C7B-720·AUD-686·AUD-718·C7B-API·C7B-UI는
완료 이력으로 옮겼다. 각 wave 시작·PR 직전·병합 직후 원격 main에 자주 rebase한다.

Alembic은 병렬 branch에서 복수 head를 만들지 않는다. migration 정본은
**C7A `0055` → AUD-718 `0056` → C7B-API `0057`** 단일 chain이며, 후속 migration
소유자는 직전 migration PR이 main에 병합된 뒤 실제 `down_revision`을 확인하고
착수한다. C7B-720·AUD-686·C7B-UI는 migration을 만들지 않는다.

공통 규율: 잦은 rebase(origin/main), task 완료 시 상대 agent 2일치 PR(닫힘 무관,
리뷰 반영 PR 제외) 적대적 리뷰→코멘트→이슈→수정→머지. 각 구현 PR은 테스트 전
적대적 리뷰어 2명.

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
