# ADR-072: Weather bitemporal 사실과 current summary

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-8

## 컨텍스트

weather row는 발표·유효·관측·수집 시각을 nullable tuple로 섞고 semantic UNIQUE, source FK,
기간 순서 제약이 불완전하다. 최신 카드와 bbox query가 원본 이력에서 매행 LATERAL 조회를
반복한다.

## 결정

1. weather 사실은 `target_at`(예보/관측 대상 시각)과 `known_at`(시스템이 알게 된 시각)을
   bitemporal 축으로 저장한다. provider-native 발표/유효/관측 시각은 typed 컬럼으로 보존한다.
2. provider dataset, feature/anchor, metric, forecast kind, native semantic identity에 FK·CHECK·
   UNIQUE를 둔다. 기간은 range type과 순서 제약을 사용하고 raw payload는 source record FK로
   추적한다.
3. nullable semantic tuple은 PostgreSQL `UNIQUE NULLS NOT DISTINCT` 의미로 중복을 막는다. PG16에서
   `CREATE UNIQUE INDEX CONCURRENTLY ... NULLS NOT DISTINCT`로 만들고 writer conflict target과
   같은 cutover에서 전환한다.
4. public API는 `target_at`, `known_at`을 받는다. 최신 weather/price 카드는 원본 이력과 분리한
   검증 가능한 current summary projection으로 제공한다.
5. `target_at`/`known_at` hot path에는 복합 B-tree를, append 시간 축에는 실측 후 BRIN을 사용한다.

### 0060 current-row 단계의 단조성 결정 (#797)

0060 schema는 아직 known-at별 correction fact와 별도 current summary를 만들지 않고, native
semantic tuple마다 현재 row 한 건만 유지한다. 이 단계에서는 `collected_at`을 `known_at` proxy로
삼아 **최신 `collected_at`이 승리**한다. 더 오래된 provider backfill은 no-op이다.

- `collected_at`은 DTO와 DB 모두 non-null aware `TIMESTAMPTZ`이므로 NULL 입력을 거부한다.
- 동률인데 저장 내용이 다르면 나중에 수용된 write가 이기고 `updated_at`을 갱신한다.
- 동률이고 저장 내용도 같으면 물리 UPDATE를 하지 않는다. writer의 반환 건수는 실제 변경 행이
  아니라 수용한 입력 건수다.

known-at correction 이력을 모두 보존하는 fact-history 전환도 비교했으나, 현재 semantic UNIQUE를
known-at identity로 확장하고 current summary·모든 read·backfill을 함께 전환해야 한다. correction
시점 재현 consumer와 cutover가 아직 없는 상태에서는 #797의 역행 방지보다 변경 범위만 크게 만든다.
따라서 이 단계는 0060 migration dedup의 `collected_at DESC NULLS LAST` 승자 의미와 runtime
조건부 upsert를 정렬한다. 향후 full bitemporal/current-summary 전환 결정은 그대로 유지한다.

## 근거

예보가 언제 유효했는지와 당시 무엇을 알고 있었는지를 분리해야 과거 재현과 최신 카드가 모두
정확하다. current summary는 원본 이력을 버리지 않고 조회 비용만 분리한다.

## 결과

- **긍정**: point-in-time 예보 재현, semantic dedup, source lineage가 하나의 모델로 수렴한다.
- **부정**: 기존 nullable 시간 tuple을 정규화하고 writer와 UNIQUE를 동시 전환해야 한다.
- **전환/rollback**: CHECK/FK는 `NOT VALID` 후 `VALIDATE`, UNIQUE는 concurrent index로 준비한다.
  writer cutover 실패 시 구 writer를 유지하고 신규 index를 사용하지 않는다. current summary는
  원본 이력에서 재생성 가능하다.

## 기존 결정과의 관계

ADR-062의 공개 weather API와 3년 보존 지평선은 유지한다. 시간 의미, 무결성, batch/current
projection은 이 ADR이 확장한다.
