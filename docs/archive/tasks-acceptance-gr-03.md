# tasks-acceptance 아카이브 — `T-GR-03` (완료)

> `T-GR-03`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-22).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-GR-03

**T-GR-02에서 넘어온 것(2026-10-16, #1327)** — 이 task가 함께 판정한다: (a) `current_dataset`·`geo_applied`를 적재
wrapper(`dagster/etl.py` `load_feature_bundles_for_dagster`·`load_feature_bundle_batches_for_dagster` — T-GR-02가 이미 받는다)
에서 client(`load_feature_bundles`·`load_feature_bundle_batches`·`load_authoritative_feature_snapshot`·asset `load_all`
callable)와 repo(`load_bundles`/`load_bundle`)로 넘긴다; (b) `dagster/etl.py` run 단위 빈 답 비율 가드 — 분모
`GeoCallStats.calls['reverse']`·분자 `empty['reverse']`를 chunk 간 누적, 상수·비율 계산 함수는 MOIS(ADR-108 §3a-2)와
**한 곳**에서 공유, **같은 조건의 MOIS run은 FAILURE가 아니다**(degraded 그대로 — 회귀 테스트); (c) MOIS 재개형 경로
(`mois_chunked_load.py`)의 `geo_applied`·현재 토큰 배선(행별 evidence); (d) price asset(`assets.py`
`feature_price_transport_fuel_stations`·`…_rest_areas`, `load_price_features`)은 `geo_applied`를 받지 않는 별도 적재
경로다 — 적재 뒤 스탬프 0건·`coverage` 분모 불변 검사(§T-GR-02 "(T-GR-03 뒤)" 항목)에 이 경로를 포함한다.

ADR-109 결정 4·6. 수정 파일: `src/kortravelmap/infra/feature_repo.py`(`load_bundle(current_dataset=, geo_applied=)`
:3035, 빈 답 가드(판정 집합 G — `address-geocoding.md` §4), 무쓰기(override 열 제외), CTE 토큰 조건 :3199-3231,
`find_unchanged_active_source_entities` :3291), `infra/feature_address_repo.py`(`FeatureAddressSnapshot` :104-117에
`road_name_code`·`admin_dong_code` 추가 — 현재 6개 주소 열 중 4개만 담는다),
`src/kortravelmap/client/__init__.py`(`load_feature_bundles` :1058, `find_unchanged_active_source_entities` :1081,
`load_feature_bundles_reobserving` :1104, `find_fresh_open_findings(expected_payload_fields=)` :2654),
`dagster/mois_chunked_load.py`(:473-485 토큰 전달·행별 evidence outcome → chunk commit 안 bulk upsert, :853-882, :905-944),
`infra/integrity_violation_repo.py:399`, `dagster/validation.py`(`address_override_geo_stale` 상수·dedupe 키),
`providers/mois.py`(:721-730 geocode 분기의 결과(코드를 받았는가)를 행별 `GeoAttemptEvidence{reverse_attempted,
geocode_obtained_code}`(T-GR-01, `dto/geo_dataset.py`)로 내보낸다 — `AdminEvidence`에 시도 필드는 더하지 않는다, :817),
`providers/kor_travel_concierge.py`(`kor_travel_concierge_items_to_bundles(…, current_data_token: str | None = None)`
:125-131 additive kwarg → `_item_to_bundle` → `_address` :523-556 토큰 신뢰 규칙; :278-290 `address.geo_data_token` 제외
해시), `dagster/assets.py:1508`(호출처 — `kor_travel_geo_dataset` resource의 `data_token` 전달),
`tests/lint/test_converters_call_geo_when_input_present.py`(신규, 변환 **함수** 단위), 통합 tests. 의존: T-GR-01·02. 규모 M.

- `address-geocoding.md` §7 "통합(DB)" 열의 케이스 전부가 통합 테스트로 있다.
- 스탬프가 채워진 뒤 릴리스(재빌드 아님) 뒤 첫 MOIS run에서 변환된 행 수 == `called|geocoded` 스탬프 행 수이고
  `not_called` 스탬프 행의 변환은 0건이다. 스탬프가 **없는** 행(롤아웃 첫 run)은 payload-bjd라도 변환되어 reverse
  0회로 `not_called` 스탬프를 받는다(T-GR-08 replay와 같은 술어).
- **의도적 빨강 3건을 PR 본문에 기록한다**: (1) 빈 답 가드를 끄면 저장 코드 non-NULL 행이 NULL로 덮이고 현재
  토큰으로 봉인된다 — **krheritage·standard_data·concierge 픽스처(원문 `legal` 있음 + geo None)에서도** `row_revision`
  불변·스탬프 미전진이어야 하고, 판정 집합에 `address.legal`을 넣으면 그 세 픽스처가 빨갛다; (2) override 열을 비교
  집합에 넣으면 값 동일에도 `row_revision`이 전진한다; (3) 토큰을 `raw_payload_hash`에 넣으면 토큰만 바뀐 concierge
  payload가 `became_current`가 된다.
- stale + 값 동일 → `row_revision` 불변(ETag 단언)·스탬프만 전진; `road_name_code`만 바뀐 행 → UPDATE(스냅샷 열
  추가 결박). 현재 토큰 None(`DatasetRef is None` **또는** `data_token is None`) → 쓰기 0이고 `DatasetRef(data_token=None)`
  픽스처로 적재해도 기존 스탬프 행 바이트 불변.
- asset run에서 resource 토큰 ≠ payload `geo_data_token` 픽스처 → geo `bjd_code` 채택(kwarg 전달 경로 결박);
  kwarg 생략(None) → 옛 동작과 bundle 동일.
- override 불일치 → `address_override_geo_stale` 1건, 같은 토큰 두 번째 run 0건, 일치 → 0건.
- 변환 함수 단위 lint가 `opinet`·`krex`의 price/notice 변환기를 유도 제외하고 초록이며, place 변환기의 reverse 호출을
  하나 지우면 빨갛다. `address_resolver=`를 받아 쓰는 6모듈(mois·standard_data·datagokr_file_data·krforest·
  krheritage·opinet)마다 "reverse None/빈 bjd 또는 좌표 없음 → geocode 1회", krex는 "geocode 0회"(`address-geocoding.md`
  §1 표) — 하나를 지우면 빨갛다.
- concierge 스탬프: 좌표 있는 행은 payload 코드를 썼어도 `called`, 좌표 없는 payload 코드 행만 `not_called`
  (`decide_outcome` 순서 ③/⑤).
- 롤아웃 첫 run의 전 행 1회 스탬프 비용(행 수·소요)을 PR 본문에 실측 기록한다(격리 스택).
- 구현 메모(2026-10-16, 브랜치 `feat/t-gr-03-stale-stamps`): (1) **현재 토큰은 첫 지오코딩 전에 읽는다**(#1327 최종 리뷰
  HARD 요구) — asset의 역지오코더를 감싸 처음 불릴 때 resource handle을 먼저 읽고(`_TokenFirstReverseGeocoder`), MOIS·
  concierge는 run 시작에 명시적으로 읽는다. 덧붙여 응답이 run 토큰과 다른 `data_token`을 내면(`GeoLoadContext.
  effective_token()` None) 그 적재는 stale 분기·스탬프를 하지 않는다 — 전환 run이 새 토큰으로 봉인되지 않는다(통합 테스트
  `test_mid_run_dataset_switch_never_produces_fresh_looking_stamps`). (2) 적재 경로 입력은 `GeoLoadContext{geo_applied,
  current_dataset, observed_data_tokens}`(dto) 하나다 — client 4 메서드(`load_feature_bundles`·`…_reobserving`·
  `…_batches`·`load_authoritative_feature_snapshot`)와 repo `load_bundles/load_bundle`이 받고, 적재 wrapper의 `load_all`
  callable은 `(bundles, geo)`를 받는다. (3) run 빈 답 가드의 분자는 endpoint 빈 답(`empty['reverse']`)이 아니라 **행 단위
  최종** 빈 답(`empty['reverse_result']` — region fallback까지 비었을 때)이다 — 산악 centroid처럼 reverse가 거의 늘 비고
  fallback이 채우는 dataset이 정상 run에서 실패하지 않게. 판정은 `dagster/geocode_ratio.py` 한 곳(MOIS와 공유, 비율은
  `mois_geocode_degraded_ratio`). (4) 행 빈 답 가드의 finding은 기존 주소 검증의 `reverse_geocode_failed`(좌표 + bjd 없음)가
  이미 남긴다 — 가드는 쓰기·스탬프를 막고 메타 `geo_empty_guarded`로 센다. (5) concierge: `current_data_token` 생략(None)은
  acceptance대로 **종전과 같다(payload 코드 우선)** — 설계 §4 문구 "기본 None = payload 코드 불신·geo 우선"은 이
  acceptance와 모순이라 acceptance를 따랐다; 해시는 payload가 `geo_data_token`을 실어 올 때만 Map이 직접 잰다(토큰·
  producer 해시 제외) — 토큰 없는 오늘의 payload는 종전 producer 해시라 롤아웃이 전 행을 흔들지 않는다. (6) override와 다르면
  `address_override_geo_stale`(info)를 적재 경로가 `(feature_id, geo_data_token)` dedupe로 쓴다; override는 열 단위라
  `core.address` jsonb에도 같은 코드가 있으면 address도 override돼 있어야 "값 동일"이 된다. (7) MOIS 행 evidence는
  `FeatureBundle.geo_attempt`(`GeoAttemptEvidence`)다. (8) 롤아웃 비용은 격리 스택 대신 통합 DB 프록시로 쟀다(PR 본문) —
  격리 스택 실측은 live e2e 단계에서. → **2차 리뷰(2026-10-16)로 대체**: 아래 (9)의 격리 스택 실측이 정본이다.
- 구현 메모 2(2026-10-16, #1328 적대 리뷰 2인 반영): (9) **geo 사실은 chunk 단위다** — `load_bundles`가 chunk 시작에
  정본 키를 dataset별로 한 번에 풀고(`feature.resolve_provider_feature_id`를 `unnest`로), stale 판정(`stale_among`)·
  저장값(`read_stored_geo_columns_many`)을 각 한 문장으로 읽고, 스탬프는 chunk 끝 한 문장(같은 transaction)이다. 같은
  Feature가 chunk에 두 번 나오면 두 번째부터는 행 단위로 다시 묻는다(선읽기가 낡았다). 끝에서 유효 토큰을 다시 보고
  None이면 스탬프를 쓰지 않는다. **실측(2026-10-16, n150 격리 PostGIS 컨테이너 — 통합 testcontainer가 아니라 배포
  bootstrap 경로로 올린 별도 DB, MOIS 재개형 루프 그대로, 12,000행 = 500행 × 24 chunk, 역지오코더는 네트워크 없는 가짜,
  chunk 일괄(이 브랜치)과 행 단위(54002adb)를 번갈아 2회)**: 롤아웃 run(전 행 스탬프 없음 → 다시 변환 → 값 동일 → 스탬프만)
  일괄 103.0·101.1초 / 행 단위 115.9·116.6초, 다음 릴리스 run 일괄 90.6·106.2초 / 행 단위 110.7·118.4초 — 행당 약 8.5ms
  (MOIS 50만 행이면 geo 호출을 뺀 적재 쪽만 약 70분). 빈 dataset 첫 적재는 스탬프 없음 301~325초·있음 279~363초로 차이가
  n150 부하 변동(load 3~8) 안이다. 정상 상태(전 행 현재 토큰) "그대로" 판정은 토큰 없음과 같은 1.1초 — EXPLAIN은 스탬프
  PK 인덱스 스캔(chunk당 9ms); 대량 쓰기 직후 첫 정상 run만 3.4~17초(hint bit 설정 — 두 번째부터 1.1초).
  (10) **부분 퇴행 유지** — stale 분기에서 새 답의 법정동코드가 저장값과 같은데 `road_name_code`·`admin_dong_code`·
  `zipcode`가 새 답에서만 비었으면 저장값을 지킨다(override 열은 손대지 않는다), 메타 `geo_partial_kept`. 법정동이
  바뀌었으면 새 답이 정답이다. (11) concierge 해시 입력에서 최상위 `updated_at`·`operation`도 뺀다 — producer
  `_serialize_item`(kor-travel-concierge `feature_export_service.py`)은 payload가 바뀌면(토큰만 바뀌어도) `updated_at`을
  새로 찍는다; `operation`은 변환되는 행에서 늘 `upsert`인 export 상태다(`export_id`는 `ytpc_{candidate_id}`로 안정이라
  남긴다). (12) 빈 답 가드가 `address`에 override가 있는 행을 만나면 저장값(=override 값)을 provider base로 옮겨 적지
  않는다 — 그 열은 patch가 건너뛰므로 새 답을 base에 둔다(runtime 롤은 base 표를 읽을 수 없어 "base 값 사용"은 택하지
  않았다). (13) `GeoLoadContext.observed_data_tokens`의 기본은 None이고, geo를 쓰는 run이 관측 집합을 넘기지 않으면
  `effective_token()`은 None이다(fail closed) — `_geo_load_context`·MOIS `_observed_tokens`가 계수 없음을 None으로 넘긴다.
  (14) 설계와 다른 자리: `FeatureAddressSnapshot`은 넓히지 않고 `read_stored_geo_columns`를 썼다(6열 + `address` +
  active override를 한 문장으로 — snapshot을 넓히면 그 소비처 전부의 계약이 바뀐다).
- 구현 메모 3(2026-10-16, #1328 3차 리뷰): (15) 선읽기는 기존 Feature를 건드리는 **모든** 행이 소비한다(geo 대상이
  아니어도) — payload를 바꾼 행이 주소를 고쳐 쓴 뒤 같은 chunk의 뒤 행이 낡은 선읽기로 "값 동일"을 오판하지 않게.
  (16) 부분 퇴행 유지의 `road_name_code`는 도로명 텍스트가 같을 때만 낱개로, 아니면 `road_address_management_no`와
  함께 사라졌을 때만 짝으로 지킨다. (17) chunk 도중 전환 통합 테스트 — 전환 전 행은 다시 쓰이고 스탬프 0건, 다음 run은
  stale로 다시 본다.
