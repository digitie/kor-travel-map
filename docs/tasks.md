# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **즉시 실행**
  - [ ] `T-230` — **큐레이션 CSV와 다중 관측 aggregate 계약**
- **보류/결정 대기**
  - [ ] `T-101` — **Materialized View 도입 검토**

## 현재 상태

`tasks.md`에는 열린 항목만 둔다. 완료된 Sprint/Phase 이력과 감사 세부 해소 항목은
[`docs/tasks-done.md`](tasks-done.md)와 [`docs/journal.md`](journal.md)를 본다. 2026-06-29
정리 기준 `T-229-buildx`는 추가 추적하지 않고, `T-AUDIT-0616` F-01 옵션 A는
ADR-058의 옵션 B 채택으로 필수 진행 백로그에서 제외한다.

## T-230 — 큐레이션 CSV와 다중 관측 aggregate 계약

- [ ] T-230 — **큐레이션 CSV·다중 source/연도 aggregate 계약 구현**

  GitHub #665. 같은 Feature에 여러 provider 관측과 여러 연도·캠페인 큐레이션을
  손실 없이 보존하고 REST/admin 지도·목록·상세에 모두 노출한다. admin UI의
  테마·제목 수동 입력, CSV 양식 다운로드·검증·멱등 업로드, 공식 seed CSV와 기존
  prod Feature 매칭 적재를 포함한다. 완료 조건은 전체 게이트, 적대적 리뷰 보정,
  n150 prod 실데이터 live UI E2E green과 PR merge다.

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
