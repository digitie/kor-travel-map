# ADR-111 — Feature advisory fence는 Feature마다가 아니라 전역 gate 하나다

- 상태: proposed (PR #1319, 미머지·미배포)
- 날짜: 2026-10-13
- 결정자: Claude (소유자 승인 대기)
- 관계: ADR-103(Map DB가 공용 instance 안에 있다), ADR-011(advisory lock), ADR-021(forward-only)

## 컨텍스트

curation·Feature 의미 writer는 같은 Feature를 동시에 바꾸지 않으려고
`pg_advisory_xact_lock(hashtextextended('feature-write:' || feature_id, 0))`을 잡아 왔다.
단건 writer에게는 맞는 모양이다. 그런데 **dataset 전체를 건드리는 프로시저 아홉**(하나는 호출자 없음)도 같은
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

- **대량 writer** 여덟(`finalize_provider_curation_root`, `materialize_theme_candidate_generation`,
  curated source/rule/theme create·patch·archive)은 Feature별 잠금 대신
  `pg_advisory_xact_lock(hashtextextended('feature-write-all', 0))`을 **배타로 한 번** 잡는다. 자리는
  종전 Feature 잠금 루프가 있던 자리 그대로다(`curation-catalog-write` 바로 앞). 잠금 수가 데이터
  크기와 무관해진다. 그 루프를 덮던 "잠그는 동안 범위가 바뀌었나" 재검사(잠금 전·후 두 번의 집합
  scan과 40001)는 gate가 모든 Feature를 덮으므로 지운다.
- **`finalize_provider_curation_root`만** gate를 기다리지 않는다. 이 트랜잭션은 이미
  `feature-curation-write`를 들고 있어서, 관리자 대량 명령 뒤에 줄을 서면 무관한 provider 적재가
  그 뒤에 멈추고(Dagster `lock_timeout=30000`) 55P03으로 실패한다. 그래서
  `pg_try_advisory_xact_lock`으로 한 번 시도하고 바쁘면 SQLSTATE 55P03으로 끝난다 — reconcile
  sensor가 물러섰다가 다시 한다(결정 4). 순서는 바꾸지 않는다.
- **단건 writer** 여섯(`approve_feature_request_with_initial_state`, `create_/patch_/archive_curation_item_command`,
  `create_manual_curation_item_with_feature_command`, `promote_theme_feature_candidate`)은
  `feature-write:<id>` 바로 앞에서 gate를 **공유**로 잡는다. 승인·수동 생성은 **방금 발급한 새
  Feature**에도 똑같이 잡는다 — 새 id라 대량 writer와 실제로 겹칠 수 없지만, "Feature 잠금 앞에는
  언제나 gate"라는 한 규칙이 예외 목록보다 검사하기 쉽다(lint가 그 규칙 하나를 센다).
- 단건 writer는 이제 대량 writer 뒤에서 기다릴 수 있는데 API 엔진에는 `lock_timeout`이 없다. 그래서
  이 여섯은 루틴 설정 `SET lock_timeout TO '5s'`를 갖고(루틴이 끝나면 호출자 값으로 돌아간다),
  API는 SQLSTATE 55P03을 `503 LOCK_TIMEOUT` + `Retry-After: 5`로 돌려준다(전역 예외 처리기 —
  OpenAPI는 5xx를 이미 problem+json으로 선언하므로 바이트가 바뀌지 않는다).

종전 보장 — 두 writer의 Feature 집합이 겹치면 직렬화된다 — 은 그대로다. 단건끼리는 공유끼리라
서로 막지 않는다(Feature 잠금이 막는다). 잃는 것은 **서로 다른 dataset의 대량 writer 둘이 동시에
도는 것**뿐이다.

### 2. 순서

한 트랜잭션이 잡는 전역 잠금의 순서는

`kortravelmap:curation-import` → `feature-curation-write` → `feature-write-all` → `feature-write:<id>` → `curation-catalog-write`

이다. gate는 종전 Feature 잠금이 있던 자리에 들어가므로 기존 순서를 바꾸지 않는다. 공유로 든
gate를 같은 트랜잭션에서 배타로 올리는 경로는 없다(단건 writer는 대량 writer를 부르지 않는다).
`finalize_provider_curation_root` → `refresh_curated_source_observation` → 관측 receipt INSERT →
trigger `trg_curation_source_observation_sync_concierge` → `sync_concierge_theme_catalog` →
`materialize_theme_candidate_generation`은 이미 든 배타 gate를 재진입한다.
`tests/lint/test_feature_write_lock_order.py`가 head 스키마의 모든 루틴을 펼쳐 — `feature`·`ops`·
`provider_sync` 호출과 **행 쓰기가 부르는 trigger 함수**까지 — 이 순서와 "Feature 잠금은 스칼라
하나·gate 뒤", 공유→배타 승격 금지를 센다. Python은 `feature-write`를 잡지 않는다
(`lock_feature_curation_write`는 `feature-curation-write`만) — 그것도 같은 파일이 센다.

### 3. 기각한 대안 — 대량 writer의 Feature 잠금을 그냥 지운다

"모든 Feature 잠금 taker가 이미 `feature-curation-write`를 든다"면 Feature 잠금은 중복이라 지워도
된다. 사실이 아니다: curated theme/source/rule 명령(`curated_repo.py`)과
`promote_theme_feature_candidate`, `approve_feature_request_with_initial_state`는
`feature-curation-write`를 잡지 않는다. 지우면 그 명령과 root 완결이 같은 Feature를 동시에 바꿀 수
있다. gate는 그 경로들을 고치지 않고 같은 직렬화를 유지한다.

### 4. reconcile sensor는 물러서고, 결정적 실패만 root를 닫는다

`feature_operation_reconciliation_sensor`는 실패한 tick을 그대로 실패로 둔다(watermark를 옮기지
않는다 — 종전 의미). 대신 cursor에 `last_failure = {run_id, 서명, 연속 횟수, retry_after}`를 적고,
`retry_after` 전의 tick은 아무것도 하지 않는다. 기다림은 30초에서 두 배씩 늘어 15분에서 멈춘다 —
무거운 트랜잭션(대형 root 완결)이 30초마다 다시 돌며 공유 자원을 흔들지 않게 한다. 서명은
`SQLSTATE xxxxx` 또는 예외 class 이름이고 메시지 본문은 담지 않는다.

root를 닫는 것은 **허용 목록**뿐이다: SQLSTATE class 22(데이터 예외)·23(무결성 위반)·P0(plpgsql
RAISE). 같은 run이 같은 그 서명으로 5회 연속 실패하고 Dagster run이 terminal이면, 기존 terminal 전이
(`ops.transition_provider_feature_operation_terminal_command`, `failed`/stage `failed`)로 root를 닫고
`feature_operation.reconcile_abandoned` error 로그(대상 `provider_dataset_ids`, `action: re-run the
dataset`)를 남긴다. 그 밖 — 53xxx(53200처럼 cluster의 다른 tenant가 일으킬 수 있는 자원 고갈),
배포 중 42xxx, 25006, 40001, 55P03, 57014, 58xxx, XX000, SQLSTATE 없는 실패 — 는 물러섰다가 다시 할
뿐 닫지 않는다. 특히 406 배포 전에 sensor가 다시 켜져도 53200으로 막힌 root는 닫히지 않는다.
새 상태·새 컬럼은 없다(`ops.import_jobs.quarantined_at`은 migration 소유라 런타임이 쓰지 않는다).

### 5. `finalize_provider_curation_receipts`는 걷어낸다

호출자가 없다(0209가 root 완결로 대체). 같은 Feature별 잠금 패턴에 더해 gate 자리보다 **앞에서**
`ops.import_jobs` 행을 갱신한다 — 고치려면 순서까지 바꿔야 한다. 406이 `DROP PROCEDURE`한다.

## 결과

- 대량 writer 한 트랜잭션의 advisory lock 수는 상수다(통합 검사
  `tests/integration/test_feature_write_gate_lock_budget.py`가 lock table 칸 수의 두 배 Feature를 한
  dataset에 링크하고 active rule 하나를 걸어 root를 완결한다 — 406 전 53200, 뒤 초록. 세션 공유 DB를
  더럽히지 않도록 그 모듈만의 DB에서 돈다).
- 서로 다른 dataset의 대량 writer는 직렬화된다. root 완결은 대량 관리 명령이 도는 동안 기다리지 않고
  다음 tick으로 미뤄진다.
- 단건 API 명령은 대량 writer 뒤에서 최대 5초 기다리고, 넘으면 503 `LOCK_TIMEOUT`(재시도 가능)이다.
- 결정적으로(22/23/P0) 막힌 root는 다섯 번 물러선 뒤(약 7분 반) `failed`로 보이고 재시도가 멈춘다.
- OpenAPI·PinVi 계약 변경 없음.

### 되돌릴 때(rollback)

- **cursor.** 앞 판 코드의 `FeatureOperationReconcileCursor.from_json`은 키가 정확히
  `{database, dagster, version}`이어야 한다. 새 코드는 실패가 없으면 `last_failure` 키를 쓰지 않지만,
  실패 중에 되돌리면 앞 판은 그 cursor를 거부하고 tick마다 조용히 건너뛴다. 되돌릴 때는 sensor를
  멈춘 뒤 cursor에서 `last_failure` 키를 빼거나(`dagster sensor cursor --set`) cursor를 지우고
  (`--delete`, 첫 tick이 다시 초기화한다) 다시 켠다.
- **스키마.** 406은 forward-only다. 루틴만 바뀌었으므로 앞 판 코드는 406 스키마 위에서도 돈다(새
  코드가 부르는 것은 `abandon_dagster_feature_run`뿐이고 그것은 기존 프로시저만 쓴다).
