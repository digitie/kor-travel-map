# ADR-111 — Feature advisory fence는 Feature마다가 아니라 전역 gate 하나다

- 상태: proposed (PR #1319, 미머지·미배포)
- 날짜: 2026-10-13
- 결정자: Claude (소유자 승인 대기)
- 관계: ADR-103(Map DB가 공용 instance 안에 있다), ADR-011(advisory lock), ADR-021(forward-only)

## 컨텍스트

curation·Feature 의미 writer는 같은 Feature를 동시에 바꾸지 않으려고
`pg_advisory_xact_lock(hashtextextended('feature-write:' || feature_id, 0))`을 잡아 왔다.
단건 writer에게는 맞는 모양이다. 그런데 **dataset 전체를 건드리는 프로시저 아홉**도 같은
잠금을 대상 Feature마다 하나씩, 정렬 순서로 잡았다:

| 프로시저 | 잠그는 집합 |
|---|---|
| `finalize_provider_curation_root` | root의 모든 provider dataset 링크 Feature ∪ active candidate |
| `finalize_provider_curation_receipts` (호출자 없음) | 같은 집합, dataset 하나 |
| `materialize_theme_candidate_generation` | rule의 dataset 링크 Feature ∪ candidate |
| `create_/patch_/archive_curated_source_rule_command` | 같은 집합 |
| `patch_/archive_curated_theme_command`, `archive_curated_source_command` | theme/source의 모든 rule 집합 |

advisory lock은 트랜잭션이 끝날 때까지 공유 lock table의 칸 하나를 차지한다. 그 표의 크기는
`max_locks_per_transaction × (max_connections + max_prepared_transactions + 보조 프로세스)`로
**cluster 전체가 함께 쓴다.** n150 공용 PostgreSQL(64 × 약 122 ≈ 7.8k 칸, 해시 여유분 포함
약 11k)에서 2026-10-12 09:25Z dataset 99(`transport_fuel_stations`, 11,820 Feature) root가
SQLSTATE 53200 `out of shared memory`로 롤백됐고, reconcile sensor가 30초마다 다시 시도해
같은 cluster의 다른 tenant까지 lock을 못 잡게 만들었다. 설정을 256으로 올리는 것(Manager
쪽 응급조치)은 상한을 옮길 뿐이다 — MOIS는 수십만 행이다.

## 결정

### 1. 전역 gate `feature-write-all`을 둔다

- **대량 writer**(위 아홉)는 Feature별 잠금 대신 `pg_advisory_xact_lock(hashtextextended('feature-write-all', 0))`을
  **배타로 한 번** 잡는다. 자리는 종전 Feature 잠금 루프가 있던 자리 그대로다
  (`curation-catalog-write` 바로 앞). 잠금 수가 데이터 크기와 무관해진다.
- **단건 writer**(`approve_feature_request_with_initial_state`, `create_/patch_/archive_curation_item_command`,
  `create_manual_curation_item_with_feature_command`, `promote_theme_feature_candidate`)는
  `feature-write:<id>` 바로 앞에서 gate를 **공유**로 잡는다.

종전 보장 — 두 writer의 Feature 집합이 겹치면 직렬화된다 — 은 그대로다. 대량 writer의 배타
gate는 모든 Feature를 덮는 잠금이고, 단건 writer는 그 공유 몫을 먼저 든다. 단건끼리는
공유끼리라 서로 막지 않는다(Feature 잠금이 막는다). 잃는 것은 **서로 다른 dataset의 대량
writer 둘이 동시에 도는 것**뿐이다 — 둘 다 관리 명령이거나 root 완결이고, 서로 다른 dataset
root 완결의 병렬성은 운영상 필요하지 않다.

### 2. 순서

한 트랜잭션이 잡는 전역 잠금의 순서는

`kortravelmap:curation-import` → `feature-curation-write` → `feature-write-all` → `feature-write:<id>` → `curation-catalog-write`

이다. gate는 종전 Feature 잠금이 있던 자리에 들어가므로 기존 순서를 바꾸지 않는다. 공유로
든 gate를 같은 트랜잭션에서 배타로 올리는 경로는 없다(단건 writer는 대량 writer를 부르지
않는다). 중첩 호출(`finalize_provider_curation_root` → `refresh_curated_source_observation`
→ 관측 트리거 → `materialize_theme_candidate_generation`)은 이미 든 배타 gate를 재진입한다.
`tests/lint/test_feature_write_lock_order.py`가 head 스키마의 모든 루틴을 중첩 `CALL`까지
펼쳐 이 순서와 "Feature 잠금은 스칼라 하나·gate 뒤"를 센다. Python은 `feature-write`를 잡지
않는다(`lock_feature_curation_write`는 `feature-curation-write`만) — 그것도 같은 파일이 센다.

### 3. 기각한 대안 — 대량 writer의 Feature 잠금을 그냥 지운다

"모든 Feature 잠금 taker가 이미 `feature-curation-write`를 든다"면 Feature 잠금은 중복이라
지워도 된다. 사실이 아니다: curated theme/source/rule 명령(`curated_repo.py`)과
`promote_theme_feature_candidate`, `approve_feature_request_with_initial_state`는
`feature-curation-write`를 잡지 않는다. 지우면 그 명령과 root 완결이 같은 Feature를 동시에
바꿀 수 있다. gate는 그 경로들을 고치지 않고 같은 직렬화를 유지한다.

### 4. reconcile sensor는 같은 실패를 끝없이 재시도하지 않는다

`feature_operation_reconciliation_sensor`는 실패한 tick을 그대로 실패로 둔다(watermark를
옮기지 않는다 — 종전 의미). 실패가 **결정적 SQLSTATE**(08·40·57 class, 53300·55P03·55006
제외)이면 cursor에 `{run_id, SQLSTATE, 연속 횟수}`만 적는다. 같은 run이 같은 SQLSTATE로
5회(약 2분 반) 연속 실패하고 그 Dagster run이 terminal이면, 기존 terminal 전이
(`ops.transition_provider_feature_operation_terminal_command`, `failed`/stage `failed`)로 root를
닫고 `feature_operation.reconcile_abandoned` 시스템 로그를 error로 남긴다. 다음 tick은 그 run을
terminal로 지나간다. 새 상태·새 컬럼은 없다(`ops.import_jobs.quarantined_at`은 migration 소유라
런타임이 쓰지 않는다).

## 결과

- 대량 writer 한 트랜잭션의 advisory lock 수는 상수다(통합 검사:
  `tests/integration/test_feature_write_gate_lock_budget.py`가 lock table 칸 수의 두 배 Feature를
  한 dataset에 링크하고 root를 완결한다 — 406 전 53200, 뒤 초록).
- 서로 다른 dataset의 대량 writer는 직렬화된다.
- 결정적으로 막힌 root는 2분 반 뒤 `failed`로 보이고 재시도가 멈춘다.
- OpenAPI·PinVi 계약 변경 없음.
