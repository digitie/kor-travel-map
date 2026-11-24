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


> **2026-10-24 ADR-114 결정 7(1단계, migration `419_retire_pg_transport_values`)** — 유가(주유소·휴게소)·고속도로 돌발의 PG 적재(asset·job·schedule·resource·preview)는 퇴역했고 그 Feature는 `retired`·`suppressed`다. 현재 값은 Valkey `transport_state_*`와 `/v1/service/transport/*`가 준다. 아래 유가·돌발 서술은 이력이다. 장소(주유소·휴게소·공항 place) 적재는 그대로다.
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

- `transport_fuel_stations`
- `transport_rest_areas`
- `transport_airports`
- `krheritage_items`
- `krheritage_events`
- `mois_license_records`
- `knps_point_records`
- `knps_geometry_records`
- `krforest_recreation_forests`
- `krforest_arboretums`
- `krforest_mountain_trails`
- `krforest_dulle_trails`
- `krforest_landslide_forecast_issues`
- `standard_museums`
- `standard_tourist_attractions`
- `standard_parking_lots`
- `standard_traditional_markets`
- `khoa_beaches`
- `visitkorea_festivals`
- `visitkorea_tourist_attractions`
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
| `transport_fuel_stations` | `kor-travel-transport` | `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL`, `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN` | transport `TRANSPORT_SERVICE_EXPORT_TOKEN`(같은 값) |
| `transport_rest_areas` | `kor-travel-transport` | 위와 같음 | 위와 같음 |
| `transport_airports` | `kor-travel-transport` | 위와 같음 | 위와 같음 |
| `krheritage_items` | `python-krheritage-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krheritage_events` | `python-krheritage-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `mois_license_records` | `python-mois-api` | `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH` | 없음 |
| `knps_point_records` | `python-knps-api` | 없음 | 없음 |
| `knps_geometry_records` | `python-knps-api` | 없음 | 없음 |
| `krforest_recreation_forests` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krforest_arboretums` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krforest_mountain_trails` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krforest_dulle_trails` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `krforest_landslide_forecast_issues` | `python-krforest-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `standard_museums` | `python-datagokr-api` | — (포털 공개 파일, 서비스키 불필요) | — |
| `standard_tourist_attractions` | `python-datagokr-api` | — (포털 공개 파일, 서비스키 불필요) | — |
| `standard_parking_lots` | `python-datagokr-api` | — (포털 공개 파일, 서비스키 불필요) | — |
| `standard_traditional_markets` | `python-datagokr-api` | — (포털 공개 파일, 서비스키 불필요) | — |
| `standard_special_streets` | `python-datagokr-api` | — (포털 공개 파일, 서비스키 불필요) | — |
| `khoa_beaches` | `python-khoa-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `visitkorea_festivals` | `python-visitkorea-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `visitkorea_tourist_attractions` | `python-visitkorea-api` | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` |
| `kor_travel_concierge_youtube_features` | `kor-travel-concierge` | `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`, `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` | 없음(DB `read` 키 발급) |

### kor-travel-transport export (ADR-106)

`transport_*` resource는 provider 라이브러리가 아니라 같은 호스트의 kor-travel-transport
`GET /v1/service/exports/{fuel-stations,rest-areas,rest-area-fuel-prices,highway-incidents/active,airports}`를
읽는다. 설정의 정본은 `kortravelmap.settings.KorTravelMapSettings`다.

| env | 기본값 | 뜻 |
|-----|--------|----|
| `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL` | 없음(필수) | scheme+host[:port]만. 운영(host network)은 `http://127.0.0.1:14001`, repo compose는 `http://host.docker.internal:14001` |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN` | 없음(필수) | header `X-Kor-Travel-Transport-Service-Token`. transport `TRANSPORT_SERVICE_EXPORT_TOKEN`과 같은 값(32자 이상) |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_PAGE_SIZE` | `500` | cursor 페이지 크기(1~1000, transport `MAX_PAGE_SIZE`) |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_TIMEOUT_SECONDS` | `30.0` | 요청 하나의 httpx timeout(0.2~120) |

빈 문자열은 미설정과 같다(compose `${X:-}`) — 요청 전에 `ProviderCredentialMissing`으로 실패한다.
transport는 token **그리고 접속 peer 주소**(`SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`, 기본 loopback)가 맞아야
응답하고 아니면 404로 경로를 숨긴다(`Host` header는 보지 않는다). 실패는 `failure_kind`로 가른다:

| failure_kind | 원인 | step 재시도 |
|--------------|------|-------------|
| `transport_hidden` | 404 — token·peer 주소·export 없는 버전 | **끈다**(`retryable=False` → `Failure(allow_retries=False)`) |
| `transport_not_current` | 503 또는 200 본문 `collection`이 이력 없음·실패·stale, 돌발 `collected_at` 30분 초과 | **재시도 대상**(`retryable=True`, HTTP 층에서는 바로 다시 부르지 않는다) |
| `transport_empty` | 완전 snapshot export(주유소·휴게소·휴게소 유가·공항)가 0건 | 끈다 |
| `transport_contract` | 필수 필드·타입·페이지·cursor 계약 위반 | 끈다 |
| `transport_malformed_upstream` | 본문이 JSON이 아니다 | 끈다 |

step 재시도를 끄는 자리는 asset 경계 `run_tracked_feature_asset`의
`quota_exhaustion.raise_terminal_if_transport_unrecoverable`이다(쿼터 소진과 같은 방식). **큐 경로
(`feature_update_request_worker`)는 다르다** — 실패한 update request는 어떤 원인이든(503 포함) 그 request로
끝나고 다시 큐에 넣지 않는다. 다음 schedule이나 새 request가 다시 돈다(2026-10-04 결정: 503 재큐잉은 하지
않는다).

전송 오류와 502/504만 HTTP 층에서 다시 부른다(경계당 2회). 그 재시도는 **run 하나에 예산 하나**다 —
asset step과 큐 run(`execute_feature_update_request`, scope 여러 개)이 `upstream_retry.sharing_run_retry_budget`을
열고 그 안의 transport fetcher가 모두 나눠 쓴다.

## Feature load schedules

모든 schedule은 `execution_timezone="Asia/Seoul"`이며, 같은 시각에 외부 API 호출이
몰리지 않도록 분 단위를 분산한다.

| schedule | job | cron |
|----------|-----|------|
| `feature_event_visitkorea_festivals_daily_schedule` | `feature_event_visitkorea_festivals_job` | `35 4 * * *` |
| `feature_place_transport_fuel_stations_weekly_schedule` | `feature_place_transport_fuel_stations_job` | `5 3 * * 1` |
| `feature_place_transport_rest_areas_weekly_schedule` | `feature_place_transport_rest_areas_job` | `20 4 * * 1` |
| `feature_place_transport_airports_monthly_schedule` | `feature_place_transport_airports_job` | `5 5 4 * *` |
| `feature_place_krheritage_items_monthly_schedule` | `feature_place_krheritage_items_job` | `15 2 2 * *` |
| `feature_event_krheritage_events_monthly_schedule` | `feature_event_krheritage_events_job` | `25 3 2 * *` |
| `feature_place_mois_licenses_monthly_schedule` | `feature_place_mois_licenses_job` | `35 4 2 * *` |
| `feature_place_knps_points_monthly_schedule` | `feature_place_knps_points_job` | `45 3 3 * *` |
| `feature_geometry_knps_records_monthly_schedule` | `feature_geometry_knps_records_job` | `15 4 3 * *` |
| `feature_{place_knps_points,geometry_knps_records}_<dataset>_monthly_schedule` | 같은 KNPS job | 기본 cron + 2분 간격 (#1450) |
| `feature_place_kor_travel_concierge_youtube_monthly_schedule` | `feature_place_kor_travel_concierge_youtube_job` | `40 3 3 * *` |
| `feature_route_krforest_mountain_trails_monthly_schedule` | `feature_route_krforest_mountain_trails_job` | `0 2 1 * *` |
| `feature_route_krforest_dulle_trails_monthly_schedule` | `feature_route_krforest_dulle_trails_job` | `15 2 1 * *` |
| `feature_notice_krforest_landslide_forecast_issues_six_daily_schedule` | `feature_notice_krforest_landslide_forecast_issues_job` | `20 1,5,9,13,17,21 * * *` |

## Run 큐 우선순위 (`dagster/priority`)

n150 공용 Dagster instance(Map·PinVi·concierge)의 run 큐는 instance 전체에서 `dagster/priority`
(정수 문자열, 클수록 먼저 dequeue, 없으면 0, 같은 값은 FIFO)로 줄을 선다. 값은 테넌트 공통 규칙이다
(정본: kor-travel-docker-manager `docs/dagster-tenant-fairness.md`, 소유자 결정 2026-11-24). 분류는 자료의
성격 + 주기다 — 기준정보·시간표·목록·POI 같은 기준 자료는 주기와 무관하게 0이다.

| 값 | 뜻 | Map job |
|---|---|---|
| 10 | 현황(관측·상태)을 1시간 미만 주기로 갱신하는 정기 수집·상태 적재 | `transport_state_highway_incidents`(10분), `weather_state_current`(매시 :25·:40) |
| 5 | 시간 단위로 바뀌는 값(가격·예보 등)을 하루 미만 주기로 갱신하는 정기 수집(1시간 미만이어도 현황이 아니면 5) | `transport_state_fuel_stations`·`transport_state_rest_area_fuel_prices`(매시), `weather_state_forecast_ultra_short`·`weather_state_daily_summaries`(매시), `weather_state_forecast_short`·`weather_state_forecast_external`(3시간), `weather_state_forecast_mid`(하루 4회), `feature_notice_krforest_landslide_forecast_issues_job`(하루 6회) |
| 0 | 하루 이상 주기·backfill·전체 재적재·정리·유지보수·검증·큐·수동 | 나머지 전부(매일·매주·매월 feature 적재, 매일 상태 적재, 매시 GC·6시간 file scan 같은 정리, 큐 worker, offline upload, 탐침) |

- 표는 `kortravelmap.dagster.run_priority.JOB_RUN_PRIORITIES` 하나다. 값은 **job 정의 tag에만** 달려
  schedule·sensor·launchpad·관리자 "지금 실행"(GraphQL `launchRun`)·재실행 run에 모두 실린다.
  schedule·sensor `RunRequest`와 schedule tag는 이 key를 싣지 않는다(같은 key를 덮지 않는다 — 시험이 막는다).
  표에 없는 job은 code location 로드에서 실패한다.
- 정기 job을 사람이 띄워도(launchpad·"지금 실행"·재실행) job 값을 그대로 받는다. 규칙의 "수동 일괄 실행 = 0"은
  수동으로만 도는 일괄 job(offline upload·batch gate 등)이다. geo 릴리스 재지오코딩 sensor가 띄우는 산사태
  notice run도 job 값(5)을 받는다. UI에서 asset을 직접 materialize하는 암묵 `__ASSET_JOB` run은 tag가 없어 0이다.
- 우선순위는 대기 중인 run끼리의 dequeue 순서만 바꾼다. 이미 도는 run을 밀어내지 않고, pool·tag 상한에 막힌 run은
  그대로 기다린다.
- 분류는 schedule의 **코드 기본 cron**으로 한다. cron override는 값을 바꾸지 않는다 — 주기를 바꾸면 표도 바꾼다.
  `tests/test_run_priority.py`가 표 ↔ 정의된 job ↔ 코드 cron 주기를 대조한다.
- 음수·10 초과는 두지 않는다(다른 테넌트를 굶기지 않는다).

## Curation candidate 갱신

T-VN-40부터 독립 `curated_features_refresh` asset/job/schedule은 없다. provider full-snapshot의
authoritative terminal receipt가 같은 transaction에서 source observation과 candidate generation을
시작하며, catalog semantic command는 affected rule reconcile을 직접 수행한다. 임의 시점의 daily
rule apply/sweep/cache는 지원하지 않는다.

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
