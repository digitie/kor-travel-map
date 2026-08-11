# T-VN-38 current summary 사전 설계 — 2026-08-08

## 목적과 선행 조건

T-VN-38A/B/C는 weather·price의 원본 사실 이력을 버리지 않으면서, 현재 카드와 bbox
조회가 매 feature마다 원본을 다시 순위화하던 경로를 검증 가능한 현재 projection으로
교체한다. 세 항목은 분리 PR이 아니라 **하나의 PR**로 구현한다.

이 PR은 T-VN-33 draft PR #966의 `0092_tvn33_offline_cleanup` 위에 쌓는다. #966은
`provider_datasets`와 exact operation triple을 DB 정본으로 만들고 source head를 최종
스키마로 전환한다. 따라서 T-VN-38은 `provider` 문자열이나 `(provider, dataset_key)`
호환 경로를 새로 만들지 않는다. weather와 price 모두 `provider_dataset_id`만 저장
정본으로 사용한다. #966이 main에 병합되면 이 PR을 즉시 main 위로 rebase/retarget한다.

서비스 전 단계이므로 중간 DB 보존·호환 migration·dual write는 범위 밖이다. 스키마가
바뀌면 빈 DB를 최종 head까지 올리고 provider ETL을 재실행해 사실을 다시 만든다.

## 데이터 모델

### 불변 사실과 summary의 역할

- `feature.feature_weather_values`, `feature.feature_price_values`는 immutable 사실이다.
  각 fact는 non-null `source_record_key`, `source_entity_key`, `provider_dataset_id`를 가진다.
  `(source_record_key, source_entity_key, known_at)`와 `(source_entity_key,
  provider_dataset_id)`의 복합 FK로 source lineage와 dataset 소유자가 일치하게 한다. 값만
  적재하는 source-less 경로는 제거하고 provider ETL이 source record를 먼저 만든다.
- KMA의 grid feature source (`kma_*_grid`)와 forecast value producer dataset은 별개다.
  따라서 value ETL은 exact operation membership의 forecast/nowcast dataset 아래에 request/response
  단위 `source_entity`와 immutable `source_record`를 먼저 만든 뒤 그 record로 facts를 적재한다.
  grid feature record를 value fact provenance로 재사용하지 않는다. price를 포함한 모든 value
  producer도 동일하게 **producing dataset 소유 response record**를 사용한다.
- weather fact identity는 `(feature_id, provider_dataset_id, weather_domain, forecast_style,
  metric_key, target_at, source_record_key)`다. price fact identity는 `(feature_id,
  provider_dataset_id, price_domain, product_key, observed_at, source_record_key)`다.
  `known_at`은 source record의 `fetched_at`과 같으며 source record revision이 correction을
  식별한다. 동일 target/observed 시각의 정정도 새 source record와 새 immutable fact로 append한다.
  두 fact table의 UPDATE/DELETE trigger와 insert `ON CONFLICT DO NOTHING`이 immutability를
  DB에서 강제한다. 기존 0060의 `collected_at` latest-wins upsert는 제거한다.
- T-VN-38은 실제 `feature.features.feature_id TEXT`를 유지한다. 전 저장소 UUID PK re-key는
  이 작업에 섞지 않으며, T‑VN‑32의 API UUID projection은 별도 경계로 계속 처리한다.
- weather의 metric name/source metric/severity/normalization metadata와 price의 product
  name/source product/normalization metadata는 immutable fact row에 보존한다. summary는 그
  표시값도 복제하지 않는다.
- `feature.current_weather_summary`, `feature.current_price_summary`는 값을 복제하지
  않는다. 각 identity당 선택된 `weather_value_key` 또는 `price_value_key` 한 개를 FK로
  참조한다. UI/API는 summary를 facts에 set join하여 값을 읽는다. 따라서 summary의 값과
  history 값이 달라지는 drift 자체를 모델에서 없앤다.
- weather summary identity는 `(feature_id, provider_dataset_id, weather_domain,
  forecast_style, metric_key)`이며 `timeline_bucket`은 표시 파생값이라 identity가 아니다.
  price summary identity는 `(feature_id, provider_dataset_id, price_domain, product_key)`다.
  이는 ADR-078의 full series cardinality를 dataset 정본으로 확장한 것이다.
- summary가 참조하는 fact는 같은 feature/dataset/도메인/series인지 복합 FK로 강제한다.
  derived summary→fact FK는 `ON DELETE CASCADE`여서 feature cascade가 fact/summary 삭제 순서에
  막히지 않는다. 단일 fact-key FK만 두고 writer를 신뢰하지 않는다.
- provider client의 pure 변환 DTO는 외부 provider 이름을 가질 수 있으나 DB identity를
  소유하지 않는다. persistence 경계의 `load_*_values`는 non-null `provider_dataset_id`를
  별도 인자로 요구하고, T-VN-33의 exact operation membership에서만 이를 얻는다. 문자열로
  dataset을 다시 찾거나 fallback하는 경로는 만들지 않는다.
- persistence mapper는 `WeatherValue`의 `target_at`을 `valid_at`, `valid_from`,
  `observed_at` 순서로 도출한다. 세 값이 모두 없으면 weather fact를 거부한다. `known_at`은
  DTO의 `collected_at`이 아니라 반드시 source record의 `fetched_at`이다. key generator는
  weather `(feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
  target_at, source_record_key)`, price `(feature_id, provider_dataset_id, price_domain,
  product_key, observed_at, source_record_key)` 전체를 입력으로 받는다. 모든 provider/Dagster/
  fixture call site가 이 한 mapper를 거쳐야 한다.

### materialization receipt

`ops.current_summary_runs`는 `run_id`, `projection_kind(weather|price)`,
`run_kind(ingest|reconcile|backfill|restore)`, 시작/종료 시각, 입력/삽입/수정/삭제 건수와
성공 상태를 보유한다. terminal 상태는 종료 시각을 반드시 가지며 successful receipt는 UPDATE/
DELETE할 수 없다. summary row는 마지막 successful verifier run을 **반드시** 참조한다.

이 receipt는 감사와 재현의 증거일 뿐 승자 선택의 정본이 아니다. restore/backfill이 더
나중에 실행되어도 business time이 더 오래된 사실을 current로 되돌릴 수 없다.

### 순위 규칙과 원자성

- weather candidate는 `known_at <= selected_at`, `target_at <= selected_at`,
  `(valid_during IS NULL OR valid_during @> selected_at)`를 모두 만족해야 한다. 같은
  summary identity에서 `target_at DESC, known_at DESC, upper(valid_during) DESC NULLS LAST,
  issued_at DESC NULLS LAST, valid_at DESC NULLS LAST, observed_at DESC NULLS LAST,
  weather_value_key DESC`로 하나를 고른다. 이 ORDER BY와 eligibility는 writer/reconcile/
  time-travel CTE가 공유하는 한 SQL fragment로 둔다.
- price는 series별 `observed_at DESC, known_at DESC, price_value_key DESC`로 선택한다.
  materialization 실행 시각이나 `collected_at`은 어느 domain의 순위에도 쓰지 않는다.
- 단일 fact ingest는 같은 DB transaction에서 fact append와 해당 identity summary upsert를
  마친다. bulk/backfill/restore는 사실 적재 후 set-based reconciliation으로 summary를
  재계산하고 receipt를 남긴다.
- reconciliation은 기대 집합과 실제 summary의 `EXCEPT ALL` 양방향 차이를 검사하고,
  불일치가 있으면 set-based upsert/delete로 수리한다. 완료 receipt가 성공이 아니면
  current read cutover를 통과로 보지 않는다.

weather의 `current`는 위 selection 시각 winner다. summary의 `refresh_after`는 다음 후보의
`GREATEST(target_at, known_at, lower(valid_during))`, selected fact의 `valid_during` upper bound, 그리고 canonical
refresh policy의 `stale_after_minutes` 경계 중 selection 이후 가장 이른 시각이다. weather
dataset은 non-null SLA가 있어야 normal current summary를 제공한다. Dagster의
`current_weather_summary_refresh` job은 기본 실행 minute schedule로 `refresh_after` 경계를
재계산한다. 전역 weather projection은 transaction advisory lock 아래 desired set을 만들고,
같은 winner/deadline은 receipt만 남기며 달라진 pointer/deadline만 upsert한다. 만료 summary와
inactive dataset은 normal card·anchor·bbox join에서 제외한다. 따라서 scheduler 지연은 오래된
값을 정답처럼 표시하지 않는 empty current 결과로 관측된다.

## 조회 cutover (T-VN-38C)

normal current card와 bbox/detail은 `features → weather_anchor_candidates → current_summary →
fact` 및 price summary의 set join만 쓴다. `weather_anchor_candidates`는 현재 own/nearest/KMA
tier 우선순위를 그대로 `(target_feature_id, tier)` partition의 window rank로 계산해 anchor를
하나만 남긴다. 공간 후보는 `ST_DWithin` + KNN/명시 tie-break를 사용하고 per-row `LATERAL`을
사용하지 않는다. 따라서 own/nearest anchor fallback을 잃지 않으면서 set query로 바뀐다.
explicit `target_at`, `known_at` 과거 재현이나 forecast timeline은 summary의 의미가 아니므로
동일 anchor CTE 뒤 raw-history window/ranked CTE를 사용한다.

current endpoint는 summary만 읽고 `asof`를 받지 않는다. historical snapshot endpoint는
`target_at`, `known_at`을 모두 필수로 받아 raw ranked CTE를 실행한다. current/history·bbox API
DTO와 OpenAPI/UI React key는 `provider_dataset_id`, `dataset_key`, `display_name`을 series identity로
노출한다. provider name은 표시 보조값일 뿐 key가 아니다.
summary가 존재하는 map DTO는 `provider_dataset_id`, `dataset_key`, `dataset_display_name`,
`refresh_after`를 필수로 하며, marker는 deadline을 넘긴 row를 받지 않는다.

기존 history index는 T-VN-39 removal manifest 판단 전까지 shadow로 남긴다. 신규 summary
index는 identity와 fact-key join을 실제 EXPLAIN으로 검증한 뒤에만 추가한다. 단순히
`Nested Loop` 노드가 없음을 요구하지 않고, normal query가 summary 및 의도한 access path를
사용하며 row/cardinality가 일치함을 gate로 둔다.

## PR 분해와 migration chain

단일 stacked PR 안에서 다음 선형 revision을 만든다.

1. `0092` (38A): `current_summary_runs`, immutable weather final fact/lineage, current summary,
   writer/reconciliation 및 weather refresh scheduler.
2. `0093` (38B): immutable price fact의 dataset/lineage clean cut, current summary 및
   reconciliation.
3. `0094` (38C): normal reader/API/UI cutover, set-based query/index, legacy normal path fence.

세 revision은 `0091_tvn33_cutover_fence → 0092_weather_current_summary → 0093 → 0094`를
구성한다. T-VN-33의 동시 후속 `0092_tvn33_offline_cleanup`까지 포함한 stacked head는
`0095_tvn33_tvn38_head_merge`가 수렴시킨다. 현행 intermediate data의 보존 migration은
만들지 않는다.

## 검증과 승인 게이트

- 빈 PostGIS DB upgrade부터 provider ETL 재적재까지 실행한다.
- out-of-order ingest, 동일 시각 tie, backfill, restore, 삭제/재적재에서 winner가 business
  time 규칙대로 유지되는지 검증한다.
- weather/price 각각 expected ranked facts와 summary의 양방향 set difference가 0인지
  검증한다.
- 원자 writer 실패 시 fact와 summary가 함께 rollback되는지, reconcile만으로 훼손된
  summary를 수리하는지 검증한다.
- API/admin current·history의 full-series cardinality, dataset identity, freshness, OpenAPI 및
  frontend type을 검증한다. source-less write, cross-dataset provenance, fact/receipt mutation,
  summary/fact cascade delete, expired `refresh_after`도 DB rejection·회귀 fixture로 고정한다.
- actual `0092`/`0093` migration은 T‑VN‑39의 physical feature PK re-key 전이므로 existing
  `feature_id TEXT` FK를 쓴다. `contracts/vnext`의 UUID fact FK는 T‑VN‑39 뒤 final target
  artifact다. 두 형태를 섞지 않는 fresh-upgrade migration test와 final target-freeze test를
  각각 둔다.
- KMA grid source와 forecast-response source를 의도적으로 분리한 positive ETL fixture, 그리고
  grid record를 forecast fact에 연결하려는 cross-dataset 음성 fixture를 둔다.
- n150의 서비스와 동일한 prod 환경에서 파괴적 final-head rebuild → provider ETL → admin
  UI live E2E를 수행한다. 실제 서비스 데이터 보존은 목표가 아니다.

코드 착수 전 독립 적대 리뷰어 2명이 이 문서와 ADR-089의 DB identity, 순위, 복합 FK,
time-travel 경계를 승인해야 한다. 리뷰 발견 사항은 구현 전에 이 문서/ADR에 반영한다.
