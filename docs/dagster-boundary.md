# Dagster 경계

`python-krtour-map`은 API 수집 결과를 feature/source/weather/price 계약으로 가공하는 ETL 단계의 공통 로직을 가진다. 실제 Dagster process, daemon, UI, schedule 실행은 TripMate가 가진다.

## python-krtour-map 책임

- Dagster op에 전달되는 실행 context DTO: `DagsterEtlExecution`, `DagsterEtlRun`
- ETL job metadata 계약: `EtlJobSpec`, `EtlRunIdentity`
- logical datetime, `run_type`, 수동 backfill config 파싱
- provider/data 부재를 실패가 아닌 skip으로 표현하는 `EtlSkip`
- loader 결과를 Dagster metadata/log payload에 넣기 위한 `json_ready`
- download/log directory resolution helper
- feature/source/weather/price DTO와 DB row 변환
- provider typed model을 feature/detail/weather/price 계약으로 정규화하는 순수 함수
- 수집 결과를 열린 feature DB session에 staged write하는 `load_feature_rows`와 provider별 적재 helper
- provider 이미지/파일을 RustFS에 적재하고 `FeatureFile` metadata를 만드는 helper
- PostGIS blocking과 scoring 기준, dedup review payload, data integrity violation payload
- provider sync cursor와 retry 가능한 checkpoint row helper

`python-krtour-map`은 Dagster package를 필수 dependency로 두지 않는다. 이 라이브러리의 ETL 계약은 Dagster 없이도 테스트 가능해야 하며, Dagster-specific decorator와 `Definitions`는 TripMate에 둔다.

## TripMate 책임

- `dagster dev`, daemon, Docker Compose, 운영 runbook
- `dagster` package import와 `@op`, `@job`, `ScheduleDefinition`, `Definitions` 생성
- DB session/resource 주입
- `etl_run_logs`, 관리자 알림, Telegram outbox 같은 운영 실행 로그
- retry 소진 판단과 실패 알림
- Odroid 단일 worker 환경의 concurrency=1 실행 설정
- TripMate 제품 DB와 API serving 조립

## 구현 규칙

- 새 feature ETL을 추가할 때 provider API 호출 후 가공/정규화 로직은 `python-krtour-map`에 먼저 둔다.
- API 데이터 수집 후 가공과 feature DB 적재 세부 로직은 `python-krtour-map`에 둔다.
- TripMate의 `app.dagster_etl`은 `krtour_map.dagster` 계약을 import해서 job/schedule을 생성하고 실행 로그를 남기는 얇은 shell이어야 한다.
- TripMate는 provider client와 feature DB session을 resource로 넘기고, commit/rollback, schedule, daemon, 알림 정책을 담당한다.
- TripMate는 RustFS client/resource도 함께 넘긴다. 바이너리 저장은 RustFS, metadata 저장은 `feature_files`를 사용한다.
- 주소/좌표 보강이 필요한 ETL은 `address_geocoder`와 `reverse_geocoder` callable을 resource로
  받을 수 있다. 명시 callable이 없으면 `kraddr_geo_store` 또는 `kraddr_geo_database_path`
  resource로 `python-kraddr-geo` 기반 callable을 생성한다. VWorld fallback은 `python-kraddr-geo`
  설정 안에서만 사용하고, 이 라이브러리는 `python-vworld-api`를 직접 로드하지 않는다.
- provider별 wrapper/adapter/gateway를 만들지 않는다. 안정된 provider public client와 typed model을 직접 사용한다.
- Dagster 실행 편의를 위해 TripMate에 임시 정규화 함수를 만들지 않는다. 필요한 변환 함수는 `python-krtour-map`에 둔다.
- 중복 판단과 검수 queue 저장은 이 라이브러리의 `dedup_review_queue` 계약을 사용한다.

## VisitKorea 축제 전체 스캔

축제/행사 수집은 `visitkorea_festival_full_scan_job_spec`로 노출한다. 이 job spec은
TripMate가 실제 Dagster `ScheduleDefinition`을 만들 때 사용할 메타데이터이며, 라이브러리
자체가 Dagster daemon을 실행하지 않는다.

- 실행 주기: 1일 1회
- dataset key: `visitkorea_festival_events`
- provider: `python-visitkorea-api`
- pagination: `iter_pages(client.search_festival, ...)`로 마지막 페이지까지 순회
- 기본 `max_pages`: 없음
- 적재: `load_visitkorea_festival_result` 또는 session resource가 포함된 `load_visitkorea_festival_events`
- 이미지: `first_image`, `first_image2`를 RustFS에 적재하고 `feature_files`에 1:N metadata 저장

TripMate 운영 config에서 `max_pages`를 넘기면 긴급 제한용으로만 사용한다. 기본 full scan은
모든 축제자료를 가져오는 것을 우선한다.

## KHOA 해수욕장정보 전체 스캔

해수욕장 장소 수집은 `khoa_oceans_beach_info_full_scan_job_spec`로 노출한다.
TripMate는 `python-khoa-api`의 `KhoaClient`를 resource로 넘기고, 이 라이브러리는
`iter_oceans_beach_info_pages()` public paginator와 `OceanBeachInfo` DTO를 직접
사용해 `place` feature로 정규화한다.

- 실행 주기: 1일 1회
- dataset key: `khoa_oceans_beach_info`
- provider: `python-khoa-api`
- source endpoint: data.go.kr `15058519`
- pagination: 시도 목록과 page를 모두 순회
- 기본 `max_pages`: 없음
- category: `python-kraddr-base` `TOURISM_NATURE_BEACH` (`01050100`)
- 이미지: `beachImg` URL을 RustFS에 적재하고 `feature_files`에 1:N metadata 저장
- 주소: `reverse_geocoder` 또는 `kraddr_geo_*` resource로 좌표 기반 주소/법정동코드 보강

이 ETL도 provider wrapper/adapter를 만들지 않는다. `python-khoa-api`에 없는 endpoint나
pagination 계약이 필요하면 먼저 provider 라이브러리의 public API로 구현한다.

## data.go.kr 표준데이터 전체 스캔

공공데이터포털 표준데이터 5종은 별도 provider 라이브러리로 빼지 않고
`krtour_map.standard_data`에서 bounded asyncio client와 `standard_data_full_scan_job_spec(s)`로
노출한다. 디버그 UI의 `run_dagster_etl` 액션도 같은 `DagsterEtlRun`/`EtlJobSpec` 계약을 사용한다.

- `standard_tourism_roads`: `route`, `feature_route_details.route_type`
- `standard_museums`: `place`
- `standard_parking_lots`: `place`
- `standard_tourist_sites`: `place`
- `standard_cultural_festivals`: `event`

`DATAGOKR_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `PUBLIC_DATA_SERVICE_KEY`, `SERVICE_KEY` 중 하나가
있으면 live scan을 시도할 수 있다. 운영 schedule, retry, commit/rollback은 TripMate가 담당한다.

## 국가유산 place/area/event 전체 스캔

국가유산 feature 수집은 `krheritage_heritage_full_scan_job_spec`와
`krheritage_event_full_scan_job_spec`로 노출한다. TripMate는 실제 Dagster schedule,
resource 연결, commit/rollback, 알림을 맡고, 이 라이브러리는 provider public model을
`Feature`/detail/source/file row로 변환한다.

Heritage place/area scan:

- 실행 주기: 1주일 1회
- dataset key: `search_list`
- provider: `python-krheritage-api`
- source key: `ccbaKdcd-ccbaAsno-ccbaCtcd`
- 출력: `place`, `area`, `feature_place_details`, `feature_area_details`
- boundary enrichment: `gis_spca`, `gis_3070426`
- media: provider image/video/audio/document URL을 RustFS에 적재하고 `feature_files`에 1:N metadata 저장

Heritage event scan:

- 실행 주기: 1일 1회
- dataset key: `event_list`
- provider: `python-krheritage-api`
- source key: provider event id `sn`
- 출력: `event`, `feature_event_details`
- media: `mainImage`와 provider media URL을 RustFS에 적재하고 `feature_files`에 metadata 저장

필요 resource:

- `krheritage.HeritageClient` public client 또는 이미 수집된 typed model iterable
- feature DB session
- optional RustFS store와 file fetcher
- optional reverse geocoder callable 또는 `kraddr_geo_*` resource

ETL 본문은 provider client를 직접 호출한다. place/area 스캔은
`client.heritage.iter_all_details(...)` 또는 `client.search.iter_all_details(...)`를 사용하고,
event 스캔은 `client.event.iter_months(...)`를 사용한다. GIS 보강은
`client.gis.spca(...)`가 반환하는 `GeoFeatureCollection`을 source model로 받아 동일한
정규화 흐름에 넣는다.

TripMate/python-krtour-map에는 `KheritageWrapper`, `HeritageAdapter`, gateway를 만들지 않는다.
누락된 endpoint, model alias, pagination, raw payload 보존은 `python-krheritage-api`에서 먼저 보강한다.

## KRMOIS 인허가 feature 주간 전체 갱신

KRMOIS 인허가 feature 갱신은 `krmois_license_feature_full_update_job_spec`로 노출한다.
TripMate는 `python-krmois-api` source DB session, `LocalDataFileClient`, feature DB session을
resource로 넘긴다.

- 실행 주기: 1주일 1회
- dataset key: `krmois_license_features`
- provider: `python-krmois-api`
- source DB 갱신: `python-krmois-api.sync_localdata_source_db(..., sync_kind="localdata_full")`
- source DB 조회: `python-krmois-api.iter_open_place_records(...)`
- 적재: `load_krmois_license_feature_result(..., prune_existing=True)`
- 폐업/취소: 최신 영업중 snapshot에 없는 KRMOIS feature는 삭제
- source raw/localdata 보존: `python-krmois-api` source DB가 담당하며, `python-krtour-map`
  `source_records`에는 KRMOIS raw row를 중복 저장하지 않음
- 주소: `reverse_geocoder` 또는 `kraddr_geo_*` resource로 좌표 기반 주소/법정동코드를 보강

폐업/취소 업체만 따로 확인해야 하는 운영 도구는
`python-krmois-api.iter_closed_place_records(...)`를 직접 사용한다. 이 경우 TripMate는
`delete_krmois_license_features_for_records(...)`를 호출해 feature row를 제거할 수 있다.

## Notice 주기 스캔

짧은 수명의 공지성 feature는 `notice_job_specs()`로 노출한다. provider 호출 wrapper를 만들지 않고
TripMate Dagster resource가 각 `python-*-api` public client에서 받은 item iterable을 넘기면,
이 라이브러리는 `Feature(kind="notice")`, `NoticeDetail`, `SourceRecord`, `SourceLink`로 변환한다.

- `krex_traffic_notices`: 5분, 사고/공사/통제 등 교통 notice
- `kma_weather_alerts`: 10분, 호우/대설/폭염 등 기상특보 notice
- `forest_safety_notices`: 30분, 산사태/산불/탐방 위험 notice
- `khoa_coastal_notices`: 60분, 해양 갈라짐/고립 위험 notice

자세한 타입 기준은 [공지 feature ETL](notice-feature-etl.md)을 따른다.
