# ADR-111 — Feature advisory fence는 Feature마다가 아니라 전역 gate 하나다

- 상태: proposed (PR #1319, 미머지·미배포 — 머지 때 accepted로, n150 배포 확인 때 배포 날짜를 이 줄과
  `docs/adr/README.md` 색인에 함께 고친다)
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
  sensor는 그 tick을 실패로 두고 30초 뒤 다시 한다(main 그대로, 결정 4). 배타 try는 **공유 보유자도** 막는다:
  대량 명령뿐 아니라 그 순간 진행 중인 단건 writer(최대 5초) 하나만 있어도 이번 시도는 진다. 단건
  writer는 짧고 드물어 30초 간격의 재시도로 충분하다고 본다. 순서는 바꾸지 않는다.
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

### 4. reconcile sensor 재시도 설계는 이 ADR에서 하지 않는다 — 후속(`T-RECONCILE-RETRY`)

`feature_operation_reconciliation_sensor`는 main 그대로다: 한 run의 반영 실패가 tick 전체를 실패시키고
(두 cursor 모두 제자리) 30초 뒤 같은 일을 다시 한다. 2026-10-12에는 이것이 53200을 30초마다 되풀이했지만,
원인(Feature마다의 advisory lock)은 결정 1이 없앤다. root 완결의 gate try가 바쁜 55P03도 같은 경로로
30초 뒤 다시 할 뿐이고, 닫거나 버리지 않는다.

PR #1319는 재시도·물러섬·멈춤 알림·root 닫기를 세 판에 걸쳐 시도했고, 리뷰마다 새 결함이 나와 되돌렸다.
그 결함들을 후속 설계의 입력으로 남긴다.

- **parking 표 판**(run별 미뤄 두는 표): 넘침으로 버린 Dagster 쪽 run은 watermark가 이미 지나 DB root가
  없으면 영영 사라진다(A-H1); tick당 실패 예산이 없어 무거운 완결이 한 tick에 수백 번 돌고 평가 timeout을
  넘긴다(A-H2); manifest 해석의 일시 실패가 guard 거부로 감싸져 표를 피한다(A-M1); 다시 집을 때 관측 오류면
  30초마다 영구 재시도(A-M2); cursor가 수십 KB가 되어 매 tick body에 복사된다(A-M3); 취소로 막힌 닫기가
  영구 `blocked`(A-L3); 55P03 대기를 멈춤으로 잘못 알림, 이벤트 이름이 `q`로 검색되지 않음(B).
- **머리 run backpressure 판**: 닫을 수 있는 머리라도 DB root가 없으면 영구히 잡힌다(H1); 모든 lock_timeout
  55P03을 "gate 바쁨"으로 보아 긴 잠금 대기가 알림 없이 멈춘다(H2); 서명이 번갈아 바뀌면 횟수가 초기화되어
  멈춤 알림도 닫기도 일어나지 않는다(H3); tick 시간 상한이 실제로는 없다(M1); cursor commit이 DB page 목록
  조회 성공에 결박된다(M2); `retry_after`가 실패 시각이 아니라 tick 시작 기준이다(M3); 그 밖 L1~L4.

후속 설계의 조건(잃지 않음·tick 시간 유계·경과 시간 기준 알림·gate 경합 전용 SQLSTATE·명시 목록만 닫기)은
`docs/tasks-acceptance.md` §T-RECONCILE-RETRY가 소유한다. 설계안은 ADR-112(proposed, 2026-10-20)다.

한 가지는 이 PR에 남긴다 — 실행 manifest 해석(`resolve_run_execution_manifest`)이 카탈로그 부재
(`FeatureOperationInvariantConflict`)만 guard 거부로 바꾼다. 종전에는 연결 끊김 같은 일시 실패까지 거부로
감싸, main sensor가 그것을 관측 오류(panel-only)로 보고 watermark를 그 run 뒤로 옮겼다 — 다시 집지 않는다.
이제 일시 실패는 그대로 올라와 main의 다른 DB 실패와 똑같이 tick을 실패시키고 30초 뒤 다시 한다.

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
- reconcile sensor의 재시도·알림은 main 그대로다(실패한 tick은 30초 뒤 다시) — 설계는 `T-RECONCILE-RETRY`.
- OpenAPI·PinVi 계약 변경 없음.

### 되돌릴 때(rollback)

- **앞으로 고친다(fix forward).** 406은 forward-only이고, 405 판 코드를 406 DB에 다시 올리는 것은 검증하지
  않았다 — 되돌림을 약속하지 않는다. reconcile sensor cursor는 이 PR이 바꾸지 않았다.

### 후속 — 적재의 fence 대기 상한(2026-10-22, T-LOAD-LOCK-WAIT)

결정 1의 "Dagster `lock_timeout=30000`" 전제는 provider 적재끼리도 깨졌다 — 동시 적재가 다른 적재의 쓰기 단계 뒤에서
30초 만에 55P03으로 실패했다. client의 적재 transaction은 이제 `feature-curation-write`를 **처음 잡는 한 문장만**
`lock_timeout`을 설정값(기본 900초)으로, 필요하면 `statement_timeout`을 그 + 60초로 늘리고 직후 되돌린다. 잠금 의미·
순서(§2)는 그대로이고, 단건 writer(5초·503)·reconcile sensor(ADR-112 예산)·completion sweep은 무장하지 않는다.
