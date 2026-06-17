# kor-travel-map-dagster

`kor-travel-map` 독립 프로그램의 Dagster code location 패키지다.

- 본 패키지는 Dagster asset/job/resource 정의를 소유한다.
- 메인 라이브러리 `kortravelmap`은 Dagster를 import하지 않는다.
- asset은 provider record resource를 받아 기존 `kortravelmap.providers.*` 변환 함수로
  `FeatureBundle`을 만들고, 주소/좌표 검증 후 `AsyncKorTravelMapClient`로 PostGIS에
  적재한다.
- `feature_update_request_queue_sensor`는 `ops.feature_update_requests` queued/now
  request를 15초 간격으로 감지하고 `feature_update_request_worker` run을 만든다.
- Feature 적재 asset은 provider별 KST schedule로 묶어 등록한다. 기본 status는
  로컬 개발 중 실 provider 호출을 막기 위해 `STOPPED`이며, 운영 배포에서 필요한
  schedule만 enable한다.
- `curated_features` asset group은 provider 적재 뒤 source metadata, 후보화 rule,
  status sweep, PinVi copy snapshot cache를 갱신한다. 기본 schedule은 `STOPPED`다.

```bash
# Docker 운영 기본: webserver + daemon 분리
docker compose up dagster dagster-daemon

# 로컬 venv 직접 실행
dagster-webserver -m kortravelmap.dagster.definitions -h 0.0.0.0 -p 12702
dagster-daemon run -m kortravelmap.dagster.definitions
```

Docker 이미지는 `docker/dagster.yaml`을 `DAGSTER_HOME`에 포함한다. 이 설정은
`KOR_TRAVEL_MAP_DAGSTER_PG_URL`을 읽어 같은 Postgres container 안의 별도 DB
`kor_travel_map_dagster`에 Dagster run/event/schedule metadata를 저장한다. 로컬
`npm run admin:stack`도 같은 파일을 `$DAGSTER_HOME/dagster.yaml`로 설치하고
`dagster-webserver`와 `dagster-daemon`을 분리 실행하므로, local/Docker 모두 같은
PostgreSQL-backed instance config를 쓴다.

## 패키지 설치 기준

`kor-travel-map-dagster`는 독립 code location으로 clean install될 수 있어야 한다.
따라서 `pyproject.toml`의 runtime dependencies는 Dagster 실행 중 직접 import하는
라이브러리를 직접 선언한다.

- `kor-travel-map==0.2.0-dev`: 같은 릴리스의 메인 라이브러리와 함께 배포한다.
- `dagster`, `dagster-webserver`, `dagster-postgres`: webserver, daemon, Postgres
  metadata storage 런타임.
- `boto3`, `botocore`: `offline_upload_store` resource가 RustFS/S3 호환 client를
  만들 때 직접 import한다.
- `httpx`: kor-travel-geo REST resource, kor-travel-concierge REST export fetcher, Dagster summary
  연동에서 사용한다.

패키지 로컬 테스트도 루트 `pyproject.toml`에만 의존하지 않도록
`[tool.pytest.ini_options] asyncio_mode="auto"`를 가진다.

## 1차 resource 계약

공통 resource:

- `kor_travel_map_client`: `AsyncKorTravelMapClient`.
- `reverse_geocoder`: kor-travel-geo REST v2 기반 reverse geocoder. **필수**(ADR-058) —
  `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` 미설정 시 resource init에서 실패한다.
- `feature_update_runner`: `ProviderDatasetRefreshRunner`. worker job이 provider/dataset
  refresh를 실행할 때 호출한다.
- `offline_upload_store`: `OfflineUploadObjectStore`. `offline_upload_load` job이
  `ops.offline_uploads.storage_key` 원본 bytes를 읽을 때 호출한다. 기본 resource는
  `KOR_TRAVEL_MAP_OBJECT_STORE_*`와 `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET`에서 RustFS/S3 호환
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
- `krforest_recreation_forests`
- `krforest_arboretums`
- `standard_museums`
- `standard_tourist_attractions`
- `standard_parking_lots`
- `khoa_beaches`
- `krairport_airports`
- `airkorea_stations`
- `airkorea_air_quality`
- `visitkorea_festival_events`
- `kor_travel_concierge_youtube_features`

현재 기본 `defs`는 provider record key마다 guard 또는 live resource를 등록한다. code
location과 schedule/job 정의는 로드되며, credential이 필요한 live resource는 설정이
없을 때 명확한 `RuntimeError`를 낸다. 이는 `_missing_resource`로 어느 key가 왜 비어
있는지 알 수 없던 상태를 막기 위한 운영 guard다.

실제 provider live fetch가 연결된 resource는 기본 definitions에서 바로 동작한다.
credential이 없거나 아직 guard로 남은 resource는 운영 실행 전에
`Definitions(..., resources={...})` override로 record iterable을 주입하거나 환경변수를
채워야 한다. 기본 guard/live resource가 안내하는 env 매핑은 다음과 같다.

| resource | provider package | kor-travel-map env | source env |
|----------|------------------|----------------|------------|
| `datagokr_cultural_festivals` | `python-datagokr-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `opinet_stations` | `python-opinet-api` | `KOR_TRAVEL_MAP_OPINET_API_KEY` | `OPINET_API_KEY` |
| `krex_rest_areas` | `python-krex-api` | `KOR_TRAVEL_MAP_KREX_GO_API_KEY`, `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `KEX_GO_API_KEY`, `DATA_GO_KR_SERVICE_KEY` |
| `krex_traffic_notices` | `python-krex-api` | `KOR_TRAVEL_MAP_KREX_EX_API_KEY` | `KEX_GO_API_KEY` |
| `krheritage_items` | `python-krheritage-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krheritage_events` | `python-krheritage-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `mois_license_records` | `python-mois-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `knps_point_records` | `python-knps-api` | 없음 | 없음 |
| `knps_geometry_records` | `python-knps-api` | 없음 | 없음 |
| `krforest_recreation_forests` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krforest_arboretums` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `standard_museums` | `python-datagokr-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `standard_tourist_attractions` | `python-datagokr-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `standard_parking_lots` | `python-datagokr-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `khoa_beaches` | `python-khoa-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krairport_airports` | `python-krairport-api` | 없음 | 없음 |
| `airkorea_stations` | `python-airkorea-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `airkorea_air_quality` | `python-airkorea-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `visitkorea_festival_events` | `python-visitkorea-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `kor_travel_concierge_youtube_features` | `kor-travel-concierge` | `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`, `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` | `API_KEYS` |

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
| `feature_place_kor_travel_concierge_youtube_daily_schedule` | `feature_place_kor_travel_concierge_youtube_job` | `40 3 * * *` |

## Curated features

- Asset group: `curated_features`
- Asset: `curated_source_metadata`
- Asset: `curated_feature_candidates`
- Asset: `curated_feature_status_sweep`
- Asset: `curated_tripmate_copy_snapshots`
- Job: `curated_features_refresh`
- Schedule: `curated_features_refresh_daily_schedule` (`55 4 * * *`, KST, 기본
  `STOPPED`)

이 group은 `feature.curated_sources`의 row count/last checked metadata를
`provider_sync.source_records` 기준으로 갱신하고, enabled source rule을 적용한 뒤,
inactive/deleted feature를 가리키는 curated row를 archive한다. 마지막 asset은
`feature.curated_tripmate_copy_snapshots`에 REST `/tripmate-copy`와 같은 payload를
materialize/cache한다.

## Feature update queue

- Sensor: `feature_update_request_queue_sensor`
- Job: `feature_update_request_worker`
- Op: `execute_feature_update_request`
- Failure sensor: `feature_update_request_failure_sensor`

Sensor는 `peek_next_update_request()`로 다음 queued request를 상태 변경 없이 확인한다.
실제 상태 전이는 worker job 안에서 `AsyncKorTravelMapClient.execute_feature_update_request()`
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

`mv_refresh_strategy=swap` 또는 `concurrently`로 실제 MV를 넘기려면 대상 MV에 refresh
identity `UNIQUE` 인덱스가 있어야 하고, 생성 직후 최초 1회는 비-concurrent
`REFRESH MATERIALIZED VIEW schema.view`로 populate한 뒤 연결한다. 이 전제는 T-101 MV
도입 migration 체크리스트에서 보장한다.

## Offline upload load

- Job: `offline_upload_load`
- Op: `load_offline_upload`
- Config: `ops.load_offline_upload.config.upload_id`
- Required resources: `kor_travel_map_client`, `offline_upload_store`

`offline_upload_load`는 JSON/JSONL `FeatureBundle` dump와 CSV/TSV tabular 원본을
지원한다. CSV/TSV는 admin validation job이 `ops.import_jobs.payload`에 저장한 column
mapping을 재사용하며, 행에 `bjd_code`가 없으면 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`
kor-travel-geo REST v2 geocode/reverse 결과로 보강한다.
