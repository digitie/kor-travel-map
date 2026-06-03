# krtour-map-dagster

`python-krtour-map` 독립 프로그램의 Dagster code location 패키지다.

- 본 패키지는 Dagster asset/job/resource 정의를 소유한다.
- 메인 라이브러리 `krtour.map`은 Dagster를 import하지 않는다.
- asset은 provider record resource를 받아 기존 `krtour.map.providers.*` 변환 함수로
  `FeatureBundle`을 만들고, 주소/좌표 검증 후 `AsyncKrtourMapClient`로 PostGIS에
  적재한다.
- `feature_update_request_queue_sensor`는 `ops.feature_update_requests` queued/now
  request를 15초 간격으로 감지하고 `feature_update_request_worker` run을 만든다.

```bash
dagster dev -m krtour.map_dagster.definitions -h 0.0.0.0 -p 9013
```

## 1차 resource 계약

공통 resource:

- `krtour_map_client`: `AsyncKrtourMapClient`.
- `reverse_geocoder`: kraddr-geo REST v2 기반 reverse geocoder.
- `feature_update_runner`: `ProviderDatasetRefreshRunner`. worker job이 provider/dataset
  refresh를 실행할 때 호출한다.
- `fetched_at`: batch 기준 aware `datetime`. 기본값은 실행 시점 KST.
- `strict_address`: 주소/좌표 error 시 적재 전 중단 여부. 기본 `true`.
- `feature_update_failure_notifier`: 선택 알림 callable. worker run 실패 시
  `{request_id, run_id, job_name, message}` payload를 받는다. 기본값은 `None`.

provider record resource:

- `datagokr_cultural_festivals`
- `opinet_stations`
- `krex_rest_areas`
- `krex_traffic_notices`
- `krheritage_items`
- `krheritage_events`
- `mois_license_records`
- `knps_point_records`
- `knps_geometry_records`

## Feature update queue

- Sensor: `feature_update_request_queue_sensor`
- Job: `feature_update_request_worker`
- Op: `execute_feature_update_request`
- Failure sensor: `feature_update_request_failure_sensor`

Sensor는 `peek_next_update_request()`로 다음 queued request를 상태 변경 없이 확인한다.
실제 상태 전이는 worker job 안에서 `AsyncKrtourMapClient.execute_feature_update_request()`
가 맡는다. 이 구조는 RunRequest 생성 실패가 request를 `running`에 남기는 상황을 피한다.
