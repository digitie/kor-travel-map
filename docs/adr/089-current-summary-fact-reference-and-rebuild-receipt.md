# ADR-089: current summary는 불변 fact를 참조하고 rebuild receipt와 분리한다

- 상태: accepted
- 날짜: 2026-08-08
- 결정자: human, Codex

## 컨텍스트

weather와 price의 현재 조회는 원본 fact에서 매 요청마다 winner를 계산한다. bbox/detail의
per-row `LATERAL`은 feature 수에 비례하여 같은 순위화를 반복한다. 값을 복제한 summary는
history와 값이 달라질 수 있고, `provider` 문자열을 price에 유지하면 ADR-088의 canonical
dataset 정본과 두 개의 identity가 공존한다. backfill/restore를 위한 실행 시각을 current
winner의 시간으로 쓰면 더 늦은 재적재가 더 오래된 관측을 현재로 되돌리는 오류도 생긴다.

## 결정

1. weather와 price 사실은 모두 non-null `provider_dataset_id`, `source_entity_key`,
   `source_record_key`, `known_at`을 갖는다. `(source_entity_key, provider_dataset_id)`와
   `(source_record_key, source_entity_key, known_at=fetched_at)` 복합 FK가 canonical source
   lineage와 dataset 소유자를 강제한다. source-less value write는 제거한다. price의 provider 문자열
   저장 identity는 제거하며, 표시명은 dataset join에서 얻는다.
   KMA grid feature source와 forecast value producer dataset은 다르므로 value ETL은 producing
   dataset 아래 response source entity/record를 별도 생성한다. grid record를 value fact에 쓰지
   않는다.
   Provider client의 pure 변환 DTO는 DB ID를 소유하지 않고, persistence 경계만 exact operation
   membership에서 얻은 non-null `provider_dataset_id`를 별도 인자로 받는다.
2. `current_weather_summary`와 `current_price_summary`는 선택된 immutable fact key를 참조한다.
   summary에 value, unit, observation time을 복제하지 않는다. summary natural identity와
   참조 fact의 identity 일치는 DB가 복합 FK로 강제한다. derived summary→fact는 `ON DELETE CASCADE`
   이며 feature cascade가 fact/summary의 물리 삭제 순서에 의존하지 않는다.
3. `ops.current_summary_runs`는 ingest, reconcile, backfill, restore의 projection 실행 receipt를
   기록한다. succeeded/failed terminal receipt는 immutable이고 summary는 자신을 **변경한** successful
   run을 반드시 참조한다. winner가 그대로인 reconcile은 summary row를 다시 쓰지 않고 scope·건수
   receipt만 남긴다. receipt의 시간이나 종류는 winner rank에 참여하지 않는다.
4. weather fact identity는 source-record revision을 포함하고, price fact identity도
   `observed_at + source_record_key`를 포함한다. correction은 UPDATE가 아니라 새 source record와
   fact append다. fact row UPDATE/직접 DELETE는 DB trigger가 거부한다.
5. weather current 후보는 `known_at <= selected_at`, `target_at <= selected_at`, 유효 range 포함을
   모두 만족한다. winner 순서는 `target_at DESC, known_at DESC, valid range upper DESC NULLS LAST,
   issued_at DESC NULLS LAST, valid_at DESC NULLS LAST, observed_at DESC NULLS LAST, fact key DESC`다.
   price는 `observed_at DESC, known_at DESC, fact key DESC`다. 모든 writer·reconcile·snapshot reader는
   이 하나의 set-based SQL rule을 사용한다.
6. weather summary에는 `GREATEST(target_at, known_at, lower(valid_during))`인 다음 candidate
   eligibility, selected validity 종료,
   canonical freshness SLA 중 가장 빠른 future 경계(`refresh_after`)를 보관한다. weather dataset은
   non-null freshness SLA가 있어야 normal current summary를 제공한다. Dagster가 deadline 전에
   재물화하며, 만료한 summary는 current 결과로 조용히 반환하지 않고 stale 상태로 드러낸다.
7. normal current read는 target별 own/nearest/KMA tier anchor를 window-ranked set CTE로 먼저
   고른 뒤 summary set join을 사용한다. explicit time-travel/timeline은 raw facts의
   set-based ranked CTE를 쓰며 normal summary fallback으로 위장하지 않는다. per-row `LATERAL`
   경로는 cutover 뒤 normal reader에서 제거한다.
8. API/UI series identity는 `provider_dataset_id`와 `dataset_key`를 포함한다. provider name은
   표시 보조값이고 React key·chart legend·marker identity가 아니다. current endpoint와 explicit
   `(target_at, known_at)` snapshot endpoint는 별도 contract로 둔다.
9. final schema로의 전환은 destructive rebuild + provider ETL 재적재로 한다. long-lived dual
   write, old provider-string compatibility, intermediate DB backup 보존은 만들지 않는다.

## 근거

fact-key 참조는 current 값을 하나만 보유하게 하므로 reconciliation이 winner pointer의 정합성에
집중할 수 있다. canonical dataset FK는 provider rename/addition에도 series identity를 안정화한다.
receipt를 business fact와 분리하면 복구·재적재의 운영 사실을 감사하면서 temporal meaning을
오염시키지 않는다. set-based join은 bbox가 갖는 집합 문제와 일치한다.

## 결과

- 긍정: current/history 값 drift가 구조적으로 사라지고, 두 domain이 같은 provider dataset
  정본과 정확한 full-series cardinality를 공유한다.
- 긍정: restore/backfill은 재현 가능하고, 행 단위 재적재가 최신 관측을 역행시키지 않는다.
- 부정: fact insert와 projection maintenance/reconciliation을 함께 구현·검증해야 하며, final
  schema DB를 다시 적재해야 한다.

## 후속

T-VN-38A/B/C 단일 PR에서 `0091` 뒤 선형 migration, repository/API/UI cutover, empty-DB
upgrade, reconciliation, EXPLAIN 및 n150 live E2E를 완결한다. `contracts/vnext`의 UUID
`feature_id`는 T-VN-39 physical re-key 뒤의 final-state artifact이고, T-VN-38 actual migration은
그 전까지 existing TEXT FK를 사용한다. 구현 전 적대 리뷰 2명의 승인을 받고, 승인 뒤 이 ADR
상태를 accepted로 바꾼다.
