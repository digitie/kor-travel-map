# ADR-114 — kor-travel-transport 출처 데이터는 Map에 최신값만 둔다(이력은 transport가 갖는다)

- 상태: proposed (2026-10-23, `T-TRANSPORT-LATEST-ONLY`. 소유자 결정 2026-10-23 — 머지 때 accepted로 고친다)
- 날짜: 2026-10-23
- 결정자: 소유자(정책) + Claude(설계)
- 관계: ADR-106(transport export 소비), ADR-089(price fact 불변), ADR-098(provider identity claim),
  ADR-017(보존 정책), ADR-111(전역 write gate), ADR-090/100(runtime ACL·SECURITY DEFINER 경계).
  transport 쪽: transport ADR-013(service export) + 이 결정이 요구하는 가격 이력 export(transport ADR-015).

## 컨텍스트

ADR-106 이후 Map은 주유소·유가·휴게소·휴게소 유가·고속도로 돌발·공항을 provider에서 직접 받지 않고
kor-travel-transport의 service export로 읽는다. transport는 그 값을 **스스로 이력과 함께 보관**한다
(`fuel_price_snapshots`, `highway_incident_snapshots`, `raw_api_responses` …). 그런데 Map도 같은 값을
적재할 때마다 이력을 쌓는다.

- price fact(`feature.feature_price_values`)는 불변 append-only다(ADR-089). 주유소 유가는 적재마다
  series당 1행이 늘어난다(관측 시각 = transport 수집 시각이므로 값이 같아도 새 행이다).
- `provider_sync.source_records`는 payload가 바뀔 때마다 새 불변 행을 남긴다. 유가 원문 응답은 run마다
  새 source entity(`run:<fetched_at>`)가 생긴다.
- 고속도로 돌발 notice는 끝나도 1년 동안 feature로 남는다(§9 보존 정책은 notice 일반 규칙이다).

같은 사실의 이력을 두 서비스가 따로 보관하는 것은 단일 정본 원칙(ADR-066~075 우선순위 2)에 어긋난다.
2026-10-23 소유자 결정: **Map은 transport 출처 데이터의 이력을 보관하지 않는다. transport는 바꾸지
않는다.** 같은 날 추가 결정: **가격 추이는 Map DB가 아니라 transport에서 직접 읽는다.**

prod 규모(2026-10-23 읽기 전용 실측): provider_dataset 99~104, 주유소 유가 fact 29,821(=summary
29,821, 적재 1회분), 휴게소 유가 fact 1,162(summary 590), 돌발 notice 485(종료 379), 돌발 source
record 2,643(entity 485). 백로그는 작다.

## 결정

### 1. 정책은 한 곳: `kortravelmap.core.retention`

```python
LATEST_ONLY_DATASETS: frozenset[tuple[str, str]]  # (provider, dataset_key)
ENDED_NOTICE_DELETE_AFTER: Mapping[tuple[str, str], timedelta]  # 돌발: 1일
```

여섯 transport dataset 전부(`transport_fuel_stations`, `transport_fuel_prices`, `transport_rest_areas`,
`transport_rest_area_fuel_prices`, `transport_highway_incidents`, `transport_airports`)가 latest-only다.
돌발만 "종료 1일 뒤 삭제" override를 갖는다. dataset 번호(99~104)가 아니라 `(provider, dataset_key)`로
고른다 — 번호는 DB마다 다르다.

`core`에 두는 이유: 이 정책을 읽는 `infra`(price_repo·retention_repo)는 `providers`를 import할 수
없다(의존 방향). 키 문자열은 `providers.kor_travel_transport`의 `DATASET_KEY_*`와 같아야 하며 단위
검사가 둘을 대조한다(정책 쪽에 새 transport dataset이 빠지면 빨갛다).

**DB 쪽 fence는 provider 단위다.** 아래 트리거·함수는 dataset이 `provider = 'kor-travel-transport'`
이고 활성일 때만 삭제를 허용한다. 정책(dataset 단위)과 fence(provider 단위)를 같은 목록으로 두 번 적지
않는다 — 소유자 결정의 범위가 "transport 출처"라서 provider가 자연스러운 DB 경계이고, dataset_key 목록을
마이그레이션에 다시 적으면 두 번째 정본이 생긴다. 이 fence의 목적은 **다른 provider의 불변 이력(ADR-089)이
코드 실수로 지워지지 않게** 하는 것이다.

### 2. 가격: series당 현재 fact 하나만 남긴다

- migration 410이 `feature.reject_price_value_mutation()`을 고친다. DELETE를 허용하는 경우가 하나 더 생긴다:
  그 fact의 dataset이 활성 transport dataset이고, `feature.current_price_summary`가 그 fact를 가리키지
  않을 때. UPDATE는 여전히 거부한다. parent feature cascade 예외는 그대로다.
- runtime ACL: `feature_price_values`에 `DELETE`를 더한다(`SELECT, INSERT, DELETE`). 위 트리거가 행 단위로
  좁힌다 — 권한만 넓히고 트리거가 그대로면 아무 것도 지워지지 않고, 트리거만 넓히고 권한이 없으면 42501이다.
- `price_repo.prune_superseded_price_facts(session, provider_dataset_ids)`가 summary가 가리키지 않는 fact를
  지운다. **같은 transaction, 같은 advisory lock**(`projection:current-price-summary`) 안에서 summary
  물화 직후에 돈다. `load_price_values`는 dataset이 latest-only면 이것을 부른다(같은 session). summary
  winner 규칙(`observed_at DESC, known_at DESC, price_value_key DESC`)과 4일 stale 지평선(`_CURRENT_SQL`)은
  그대로다 — winner가 4일보다 오래돼도 지우지 않는다(현재값이 그것뿐이다).
- 그래서 `/v1/features/{id}/price`의 Map DB `history`는 이 dataset들에서 현재값만 남는다. 추이는 결정 6이
  transport에서 읽는다.

### 3. source record: head만 남긴다

`retention_repo.prune_latest_only_lineage(session, provider_dataset_ids)`:

1. head가 아닌 record를 지운다 — 단 그 record를 `ON DELETE RESTRICT/NO ACTION`(또는 SET NULL이지만 의미를
   잃는 참조)로 붙든 행이 없을 때만(`NOT EXISTS`). 보는 참조: `feature_base_field_values`,
   `feature_price_values`, `theme_feature_candidates`, `ops.enrichment_review_queue`,
   `ops.manual_provider_dedup_cases`, `feature.curation_items`, `ops.feature_overrides`.
   `ops.data_integrity_violations`의 링크는 `ON DELETE SET NULL`로 끊긴다 — 소유자가 받아들였다.
2. 아무 feature에도 link되지 않은 entity(orphan)를 head·record와 함께 지운다 — 같은 `NOT EXISTS`를 그
   entity의 모든 record에 건다. 유가 원문 응답 entity(`run:<fetched_at>`)가 fact를 다 잃으면 여기서
   사라진다. 결정 4가 지운 돌발 feature의 entity도 여기서 사라진다.
3. 남은 head가 없는 notice 계보의 `notice_lineage_states` 행(present=false만)을 지운다.

참조 목록은 손으로 적되, 통합 검사가 `pg_constraint`에서 `source_records`/`source_entities`를 가리키는
FK 중 `confdeltype IN ('r','a')`를 뽑아 이 목록이 모두 덮는지 대조한다 — 새 RESTRICT 참조자가 생기면
그 검사가 빨갛다(RESTRICT를 빠뜨리면 DELETE가 23503으로 죽어 적재가 실패한다).

`feature_state_transitions`·`theme_candidate_generation_observations`·`theme_feature_candidate_transitions`의
`source_record_key`/`source_entity_key`는 FK가 없는 append-only 증거다. 지우지 않고 dangling을 허용한다
(`purge_manual_feature`·migration 402와 같은 규율).

이 함수는 **적재가 끝난 뒤 별도 transaction**과 maintenance op에서 돈다(결정 5). price fact prune과 달리
summary와 원자적일 필요가 없다 — 실패해도 다음 적재가 같은 일을 다시 한다(멱등).

### 4. 고속도로 돌발: 종료 1일 뒤 feature를 실제로 지운다

- migration 410이 SECURITY DEFINER 함수 `feature.purge_ended_provider_notices(p_provider_dataset_id bigint,
  p_grace interval) RETURNS TABLE(purged integer, blocked integer)`를 만든다(소유자 `ktm_feature_schema_owner`,
  EXECUTE는 `ktm_feature_runtime`에만). runtime은 `feature.features`를 지울 권한이 없고 앞으로도 없다 —
  이 함수가 유일한 경로다.
- 함수 안의 fence: dataset이 존재·활성·`provider = 'kor-travel-transport'`·`produces`에 `notice`. 대상은
  그 dataset의 primary link를 가진 notice 중 `valid_end_time < now() - p_grace`이고, 다른 dataset entity에
  link가 없고, manual identity claim이 없는 것.
- 증거 FK(`confdeltype IN ('r','a')`)로 붙들린 feature는 **건너뛴다**(blocked로 센다). 판정은
  `purge_manual_feature`와 같은 catalog 순회(`pg_constraint`)다 — 목록을 손으로 적지 않으므로 새 증거 표가
  생겨도 저절로 덮인다. 대상: theme candidate, reference reconciliation event, manual/provider dedup case,
  `ops.feature_requests.resolved_feature_id`.
- 지우는 것: identity claim(`provider_feature_identities` — 남겨 두면 다시 나타난 사건이 옛 uuid를 받는다),
  그리고 `feature.features` 행. 나머지는 스키마의 FK 동작이 따라간다 — CASCADE: notice subtype, alias, base
  field, override, dedup/enrichment 큐, merge 이력, POI cache 링크, source link; SET NULL: curation item,
  integrity violation, 자식의 parent. entity·record·head·lineage state는 결정 3이 orphan으로 지운다.
- **다시 나타난 사건은 새 identity를 받는다.** claim이 없으므로 `create_provider_feature_with_initial_state`가
  새 uuid v7을 발급한다. legacy alias(`f_*`)도 feature와 함께 사라져 충돌하지 않는다.
- 남기는 증거: `feature.feature_state_transitions`(FK 없음, append-only 트리거가 DELETE를 막는다 — 지울 수도
  없다), curation receipt, `ops.import_jobs`/events. 이 표들은 "무엇이 있었는가"의 기록이고 지워진 feature를
  가리키는 soft reference로 남는다. 이 함수는 그 표에 쓰지 않는다(삭제는 상태 전이가 아니라 transition
  트리거가 발화하지 않는다).
- 다른 dataset의 notice는 종전대로다(`purge_expired_notices`의 1년 retire). 돌발은 1일 삭제가 먼저 오므로
  1년 retire 대상에 남지 않는다. `purge_expired_notices`는 dataset override를 보고 override가 있는 dataset을
  건너뛴다.
- 종료 후 1일은 공개 read에서 이미 보이지 않는 구간이다(`valid_end_time` 지난 notice는 숨김) — 삭제가 공개
  응답을 바꾸지 않는다.

### 5. 언제 도는가 — 적재 뒤와 maintenance

- 가격 적재(`load_price_values`): 결정 2를 같은 transaction에서.
- transport dataset 적재(asset 6개, Dagster schedule 경로와 큐 경로 공통 — `_load`와 가격 asset 두 개):
  적재가 commit된 뒤 `client.apply_latest_only_retention(provider, dataset_key)`가 별도 transaction에서
  (돌발이면 결정 4 → ) 결정 3을 한다. 돌발은 provider run lock 안에서 돈다(snapshot reconcile과 직렬).
  write gate(`feature-curation-write`, ADR-111)를 잡는다.
- maintenance job `consistency_dedup_refresh`에 `apply_latest_only_retention` op를 더한다. 정책의 모든
  dataset에 결정 2(가격 dataset만)·4·3을 한다 — 적재가 오래 멈춘 dataset의 백로그와 1일 경과 돌발을 거둔다.
- 기존 행: 수동 정리는 없다. 위 경로의 첫 실행이 백로그를 지운다. 모든 단계가 집합 술어라 몇 번 돌아도
  결과가 같다(멱등). 실패는 run 실패로 드러낸다 — 적재는 이미 commit됐고 다음 실행이 다시 시도한다.

### 6. 가격 추이는 transport에서 읽는다

- transport에 additive export를 하나 더한다(transport PR, transport ADR-015):
  `GET /v1/service/exports/fuel-stations/{natural_key}/price-history?since&until&limit` — 같은 토큰·peer 대역
  fence, `fuel_price_snapshots`(가격이 바뀐 때마다 1행, 키 `(station, product, observed_at)`)를
  `observed_at DESC`로. 기존 기능·테이블은 바꾸지 않는다.
- Map API는 price card를 만들 때 feature의 series가 latest-only dataset이면 그 dataset의 history를 Map DB가
  아니라 transport에서 읽는다(`kortravelmap.api.transport_price_history`). current는 Map DB summary 그대로다
  (transport가 죽어도 현재가는 나온다).
- 응답에 `history_source`(`map` / `kor_travel_transport` / `unavailable`)를 더한다. transport 미설정·timeout·
  503·계약 위반이면 `unavailable`이고 history는 비지만 200이다 — 현재가를 깨지 않는다.
- **휴게소 유가(`transport_rest_area_fuel_prices`)는 transport에 이력이 없다**(`rest_area_fuel_prices`는
  휴게소당 최신 1행, 모델 docstring "이력은 소비자(Map)가 보관한다"). transport를 기능적으로 바꾸지 않는다는
  조건 아래에서는 추이를 줄 곳이 없다 → `unavailable`. 소유자 확인 필요 사항으로 남긴다(transport에 이력 표를
  더하거나, 이 dataset만 latest-only에서 빼거나).
- snapshot(`/price/snapshot`): transport 이력으로 재현하되 **observed cutoff만** 적용한다. transport 행의
  `collected_at`은 같은 가격을 다시 볼 때마다 앞으로 갱신되므로 knowledge-time 재현은 불가능하다.
  `known_at`은 이 series에서 무시한다(문서화). bitemporal 재현은 이 결정이 의도적으로 잃는 것이다.
- series 대응: Map price feature의 자연키 = 오피넷 `uni_id` = transport `fuel_stations.source_station_id`.
  product: transport `product_code`(B027·D047·B034·C004·K015) → `OPINET_PRODUCT_KEY_MAP`. 이력 점의
  `observed_at` = transport `observed_at`(가격 변경 시각, 없으면 수집 시각), `known_at` = transport
  `collected_at`(그 가격을 마지막으로 확인한 수집 시각). current 점의 `observed_at`(=마지막 수집 시각)과
  의미가 다르다 — 추이는 "가격이 바뀐 시점"의 계단이다.
- Map API 컨테이너는 지금 transport 토큰을 받지 않는다(Manager compose가 code-server에만 둔다). 배선은 Manager
  변경이다(`kor-travel-map-api`에 `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL`·`_SERVICE_TOKEN`). 배선 전에는
  `unavailable`이다.

## 의도적으로 잃는 것

- transport dataset의 Map DB 가격 이력·bitemporal snapshot 재현(ADR-089의 "불변 fact로 과거를 재현"은
  transport 출처에 한해 끝난다). 추이는 transport가 가진 만큼만, knowledge-time 없이.
- 휴게소 유가 추이(위 6 — 소유자 확인 대기).
- head가 아닌 원문 payload와 orphan run 응답 원문. `data_integrity_violations`의 record 링크(NULL이 된다).
- 종료 1일이 지난 돌발 notice와 그 identity — 같은 사건이 다시 나타나면 새 uuid다. 소비자가 옛 uuid로
  조회하면 404다.
- 돌발 feature의 POI cache 링크·dedup/enrichment 큐 행(CASCADE).

## 지키는 것

- 다른 provider의 price fact 불변(트리거 fence가 provider 단위로 막는다).
- current price summary와 4일 stale 지평선.
- append-only 증거 표(transition·curation receipt·import job). 삭제는 그 표에 쓰지 않고, 그 표를 지우지도 않는다.
- 증거 FK로 붙들린 feature·record는 지우지 않는다(건너뛰고 센다).
- 다른 dataset notice의 1년 retire.

## 대안

- **dataset_key 목록을 DB 트리거에도 적는다** — 두 번째 정본. provider fence로 충분하다(결정 1).
- **GUC로 prune 범위를 연다** — runtime이 아무 dataset이나 열 수 있어 fence가 아니다.
- **돌발을 retire만 하고 남긴다** — 소유자가 실제 삭제와 새 identity를 요구했다.
- **price prune을 maintenance에만 둔다** — 소유자가 summary 물화와 같은 transaction/lock을 요구했고, 그래야
  "summary가 가리키는 것만 남는다"가 commit 경계마다 참이다.

## 결과

- migration `410_transport_latest_only_retention`(forward-only, 소유자 롤로 끝난다 — RESET ROLE 없음).
- 공개 OpenAPI: `PriceCardData.history_source` 추가(공개 `/v1/features/{id}/price`·`/price/snapshot`).
  admin OpenAPI: admin price card 응답에 같은 필드 → **PinVi 재vendor 필요**.
