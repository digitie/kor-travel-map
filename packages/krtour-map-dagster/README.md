# krtour-map-dagster

`python-krtour-map` 독립 프로그램의 Dagster code location 패키지다.

- 본 패키지는 Dagster asset/job/resource 정의를 소유한다.
- 메인 라이브러리 `krtour.map`은 Dagster를 import하지 않는다.
- asset은 provider record resource를 받아 기존 `krtour.map.providers.*` 변환 함수로
  `FeatureBundle`을 만들고, 주소/좌표 검증 후 `AsyncKrtourMapClient`로 PostGIS에
  적재한다.
- `feature_update_request_queue_sensor`는 `ops.feature_update_requests` queued/now
  request를 15초 간격으로 감지하고 `feature_update_request_worker` run을 만든다.
- Feature 적재 asset 9개는 provider별 KST schedule로 묶어 등록한다. 기본 status는
  로컬 개발 중 실 provider 호출을 막기 위해 `STOPPED`이며, 운영 배포에서 필요한
  schedule만 enable한다.

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

## Feature load schedules

모든 schedule은 `execution_timezone="Asia/Seoul"`이며, 같은 시각에 외부 API 호출이
몰리지 않도록 분 단위를 분산한다.

| schedule | job | cron |
|----------|-----|------|
| `feature_event_datagokr_cultural_festivals_daily_schedule` | `feature_event_datagokr_cultural_festivals_job` | `10 3 * * *` |
| `feature_place_opinet_stations_monthly_schedule` | `feature_place_opinet_stations_job` | `5 3 1 * *` |
| `feature_place_krex_rest_areas_monthly_schedule` | `feature_place_krex_rest_areas_job` | `20 2 1 * *` |
| `feature_notice_krex_traffic_notices_quarter_hour_schedule` | `feature_notice_krex_traffic_notices_job` | `7,22,37,52 * * * *` |
| `feature_place_krheritage_items_weekly_schedule` | `feature_place_krheritage_items_job` | `15 2 * * 1` |
| `feature_event_krheritage_events_daily_schedule` | `feature_event_krheritage_events_job` | `25 3 * * *` |
| `feature_place_mois_licenses_weekly_schedule` | `feature_place_mois_licenses_job` | `35 4 * * 1` |
| `feature_place_knps_points_semiannual_schedule` | `feature_place_knps_points_job` | `45 3 1 1,7 *` |
| `feature_geometry_knps_records_semiannual_schedule` | `feature_geometry_knps_records_job` | `15 4 1 1,7 *` |

## Feature update queue

- Sensor: `feature_update_request_queue_sensor`
- Job: `feature_update_request_worker`
- Op: `execute_feature_update_request`
- Failure sensor: `feature_update_request_failure_sensor`

Sensor는 `peek_next_update_request()`로 다음 queued request를 상태 변경 없이 확인한다.
실제 상태 전이는 worker job 안에서 `AsyncKrtourMapClient.execute_feature_update_request()`
가 맡는다. 이 구조는 RunRequest 생성 실패가 request를 `running`에 남기는 상황을 피한다.
