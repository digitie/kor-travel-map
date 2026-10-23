# tasks-acceptance 아카이브 — `T-GR-02` (완료)

> `T-GR-02`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-23).
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

## T-GR-02

ADR-109 결정 2·3. 수정 파일: `packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py`
(`kor_travel_geo_client_resource`·`kor_travel_geo_dataset_resource`·`fetch_current_dataset`), `definitions.py`
(`DEFAULT_RESOURCE_DEFINITIONS`), `feature_update_runner.py`(`_COMMON_RESOURCE_KEYS`), `assets.py`(각 feature load
asset이 `load_feature_bundles`에 `geo_applied=` 전달; `required_resource_keys`), `offline_uploads.py`,
`src/kortravelmap/cli/main.py`, `dagster/etl.py`(공통 chunk 루프: 전달 + 빈 답 비율 가드 — 분모 `GeoCallStats.calls['reverse']`·
분자 `empty['reverse']` chunk 간 누적, 상수·비율 계산은 MOIS와 공유), tests. 의존: T-GR-01(+ 아래 "(T-GR-03 뒤)"
표시 항목은 스탬프 쓰기·CTE 조건이 T-GR-03에 있어 PR-1에서 셋을 함께 판정한다 — 단독으로는 스탬프 표가 비어
항진명제다). 규모 S.

- (T-GR-03 뒤) geo 실패(HTTP 예외·`available=false`)를 주입하면 `current_dataset=None`으로 run이 **계속**되고 경고 로그가
  정확히 1건이며, unchanged 집합이 토큰 도입 전 집합과 **동일**하다(같은 픽스처로 두 번 실행해 집합 비교).
- 성공 시 asset·큐 runner·offline upload·CLI 네 경로가 같은 `DatasetRef` 값을 받는다(팩토리 1개 — 단위 테스트가
  호출 지점을 센다).
- 응답 `dataset`이 run-scoped 값과 다른 픽스처 → op 메타 `geo_dataset_mismatch=true` + WARNING 1건.
- (T-GR-03 뒤) `feature_price_transport_*`·`feature_notice_transport_highway_incidents` 적재 뒤 스탬프 0건, `coverage` 분모 불변.
- AST lint: asset이 `_reverse_geocoder(context)`를 쓰면 `geo_applied.reverse=True`, `address_resolver=`를 넘기면
  `geocode=True`를 넘긴다 — 현재 asset은 전부 `geocode=False`(`assets.py`에 `address_resolver=` 0건,
  `address-geocoding.md` §1 호출자 표)이고 offline upload·CLI만 `geocode=True`. `assets.py`에서 하나를 일부러
  False로 바꿔 빨간 것을 확인한다.
- (T-GR-03 뒤) 빈 답 비율 가드: 좌표 있는 50건 중 빈 답(200, `bjd_code` None) 3건(> 5%) 픽스처 → run FAILURE·그 chunk
  스탬프 0건; 좌표 없는 1,000건을 섞어도 분모(`calls['reverse']`)가 불변이다. **같은 조건의 MOIS run은 FAILURE가
  아니다**(ADR-108 §3a-2 degraded 그대로 — 회귀 테스트; 상수·비율 계산 함수는 한 곳).
- 구현 메모(2026-10-16, 브랜치 `feat/t-gr-02-geo-dataset-resource`, #1326 위에 쌓음): (1) 팩토리 `fetch_current_dataset(client)`는
  `kortravelmap.geocoding`에 있다 — CLI가 `kortravelmap.dagster`를 import할 수 없어서다. Dagster resource
  `kor_travel_geo_dataset`(asset·큐 runner 공통 resource 키)이 짧은 수명 client로 한 번 부르고, offline upload·CLI는 같은
  함수를 직접 부른다(호출 지점 3 — `tests/lint/test_geo_applied_matches_asset_geo_callables.py`가 센다). (2) 설계의
  `kor_travel_geo_client_resource`(경량 client)는 이 PR에 넣지 않았다 — 쓰는 곳이 센서(T-GR-05)뿐이라 그때 더한다(§T-GR-05 수정 파일에 적었다). 리뷰 반영(2026-10-16): resource는
  **lazy handle**(`GeoDatasetHandle.current()` — 처음 쓰일 때 1회, 동시 호출도 1회)이라 geo 콜러블이 없는 run(price/notice·
  visitkorea·MOIS)은 읽지 않는다; 경고는 managed logger(`kortravelmap.dagster.resources`)·`context.log`로 낸다(event
  stream 결박 테스트); 키 미배선은 WARNING.
  (3) `geo_applied`는 `_load`·`_load_snapshot_batches`의 필수 인자이고 asset 21곳 + MCST 1곳이 리터럴로 넘긴다(AST lint가
  run 함수의 실제 콜러블과 대조 — 하나를 False로 바꾸면 빨갛다). 적재 wrapper는 그것과 현재 토큰·reverse 계수를 받아
  output 메타 `geo_applied_reverse/geocode`·`geo_data_token`·`geo_dataset_mismatch`를 낸다(불일치면 WARNING 1건).
  **client·infra 적재 함수로 넘기는 것과 빈 답 비율 가드는 T-GR-03**이다 — 이 PR이 넘기면 받는 쪽이 아무것도 하지 않는
  인자가 된다. MOIS 재개형 적재(`mois_chunked_load.py`)도 T-GR-03(행별 evidence)에서 배선한다. offline upload은 메타
  `geo_data_token`, CLI는 stderr 한 줄로 어느 데이터셋으로 적재했는지 남긴다.
