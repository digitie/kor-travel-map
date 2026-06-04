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
# Docker 운영 기본: webserver + daemon 분리
docker compose up dagster dagster-daemon

# 로컬 venv 직접 실행
dagster-webserver -m krtour.map_dagster.definitions -h 0.0.0.0 -p 9013
dagster-daemon run -m krtour.map_dagster.definitions
```

Docker 이미지는 `docker/dagster.yaml`을 `DAGSTER_HOME`에 포함한다. 이 설정은
`KRTOUR_MAP_DAGSTER_PG_URL`을 읽어 같은 Postgres container 안의 별도 DB
`krtour_map_dagster`에 Dagster run/event/schedule metadata를 저장한다.

## 1차 resource 계약

공통 resource:

- `krtour_map_client`: `AsyncKrtourMapClient`.
- `reverse_geocoder`: kraddr-geo REST v2 기반 reverse geocoder.
- `feature_update_runner`: `ProviderDatasetRefreshRunner`. worker job이 provider/dataset
  refresh를 실행할 때 호출한다.
- `offline_upload_store`: `OfflineUploadObjectStore`. `offline_upload_load` job이
  `ops.offline_uploads.storage_key` 원본 bytes를 읽을 때 호출한다. 기본 resource는
  `KRTOUR_MAP_OBJECT_STORE_*`와 `KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET`에서 RustFS/S3 호환
  client를 만든다. 테스트/특수 배포는 기존처럼 resource override가 가능하다.
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

## Batch consistency gate

- Job: `full_load_batch_consistency_gate`
- Op: `run_full_load_batch_consistency_gate`
- Config:
  - `child_job_ids`: 기존 실제 source load import job id 목록.
  - `load_batch_id`: 선택 UUID. 없으면 생성.
  - `plan_only`: `true`면 DB write 없이 child job 존재 여부만 확인.
  - `materialized_views`: gate 통과 후 refresh할 `schema.view` 목록.
  - `mv_refresh_strategy`: 기본 `swap`.

child job이 모두 `done`이면 `run_consistency_checks(batch_id=load_batch_id)`를 실행한다.
`severity_max=ERROR`이면 `mv_refresh`를 차단하고 root/gate import job을 `failed`로 닫는다.
현재 운영 materialized view 카탈로그가 없으므로 `materialized_views=[]` 기본 실행은
`skipped:no_materialized_views` payload를 남긴다.

## Offline upload load

- Job: `offline_upload_load`
- Op: `load_offline_upload`
- Config: `ops.load_offline_upload.config.upload_id`
- Required resources: `krtour_map_client`, `offline_upload_store`

`offline_upload_load`는 JSON/JSONL `FeatureBundle` dump와 CSV/TSV tabular 원본을
지원한다. CSV/TSV는 admin validation job이 `ops.import_jobs.payload`에 저장한 column
mapping을 재사용하며, 행에 `bjd_code`가 없으면 `KRTOUR_MAP_KRADDR_GEO_BASE_URL`
kraddr-geo REST v2 geocode/reverse 결과로 보강한다.
