# Provider 계약

## Canonical provider name

문서, DB, API 응답에는 canonical provider name만 사용합니다.

| Provider | 역할 |
| --- | --- |
| `python-kraddr-base` | 주소, 좌표, 카테고리 공통 타입 |
| `python-kraddr-geo` | Juso/주소 TXT/PostGIS 주소점, reverse geocoding |
| `python-vworld-api` | VWorld 검색, geocoder, 경계, OGC |
| `python-visitkorea-api` | KTO 관광지, 숙박, 행사/축제, 이미지, 증분 동기화 |
| `python-krmois-api` | 지방행정 인허가 데이터. place feature의 1차 원천 |
| `python-opinet-api` | 주유소와 유가 source |
| `python-krex-api` | 고속도로, 휴게소, 휴게소 날씨와 유가 source |
| `python-kma-api` | 초단기/단기/중기/특보, DFS grid |
| `python-krairport-api` | 공항 운항, 주차, 혼잡, 공항/도시 날씨 |
| `python-khoa-api` | 해수욕장, 해양지수, 조석, 파고, 수온 |
| `python-airkorea-api` | PM10, PM25, CAI, 예보/경보 |
| `python-mcst-api` | 문화/여가/숙박/도서관 위치 데이터 |
| `python-krforest-api` | 휴양림, 숲길, 국립공원, 산림 안전 |
| `python-krheritage-api` | Korea Heritage Administration heritage, GIS area, media, and event public models |
| `data.go.kr-standard` | `python-krtour-map` 내부 bounded client가 직접 처리하는 공공데이터포털 표준데이터 5건 |

`pykma`, `kma`, `opinet`, `krex` 같은 alias는 입력 편의로만 받아들이고 저장 전에 canonical name으로 바꿉니다.

## Adapter 금지

TripMate 내부와 `python-krtour-map` 내부에 provider별 adapter/gateway/wrapper를 새로 만들지 않습니다.

외부 API 관련 작업을 시작할 때는 이 원칙을 제일 먼저 반영합니다. 안정된 provider public client와 typed model을 직접 사용하고, 부족한 인터페이스는 TripMate 임시 계층이 아니라 해당 `python-*-api` 저장소에서 먼저 보강합니다.

허용되는 경계:

- provider public client 직접 호출
- provider typed model을 `Feature`, `SourceRecord`, `WeatherValue`, `PriceValue`로 바꾸는 순수 함수
- DB 저장 repository

부족한 endpoint, pagination, typed model, cursor, exception, raw payload 보존 규칙은 해당 provider 라이브러리에서 빠르게 안정화합니다.

금지되는 경계:

- 안정된 public API를 단순 전달하는 `KmaWrapper`, `VWorldAdapter`, `OpiNetGateway` 같은 중간 계층
- 기존 호출부 수정을 피하기 위한 장기 호환 alias/facade
- provider별 예외와 응답 모델을 TripMate 안에서 다시 정의하는 임시 계층

## Source role

`SourceRole`은 하나의 source row가 feature에 어떤 역할로 붙었는지 나타냅니다.

| Role | 의미 |
| --- | --- |
| `primary` | feature 생성의 1차 원천 |
| `base_address` | 주소 보정 원천 |
| `base_coordinate` | 좌표 보정 원천 |
| `enrichment` | 부가 정보 보강 |
| `correction` | 운영자 또는 더 신뢰도 높은 원천으로 보정 |
| `duplicate_candidate` | 중복 후보 판단 근거 |
| `media` | 이미지/미디어 원천 |
| `weather_context` | 날씨/대기질/해양 context 원천 |

## Dataset key

`dataset_key`는 provider 안의 수집 단위를 식별합니다.

예:

- `fuel_lowest_station`
- `fuel_avg_price`
- `rest_area_weather`
- `weather_short_term`
- `weather_mid_term`
- `forest_mountain_weather`
- `forest_fire_risk`
- `forest_landslide_risk`
- `air_quality_sido_measurement`
- `beach_marine_index`
- `visitkorea_festival_events`
- `krmois_license_features`
- `search_list`
- `gis_spca`
- `gis_3070426`
- `event_list`
- `15145324`
- `15041861`

VisitKorea 축제 source는 `python-visitkorea-api` public client의
`iter_pages(client.search_festival, ...)`를 직접 사용한다. 일일 full scan은 기본적으로
`max_pages`를 두지 않고 provider pagination이 끝날 때까지 순회한다.

Weather source는 provider public client를 직접 호출한 뒤 `WeatherValue`로 정규화한다. `forecast_style`에는 관측/예보/지수/특보 성격을 남기고, KMA식 초단기/단기/중기 분류는 `timeline_bucket`에 둔다. 세부 mapping은 `docs/weather-feature-normalization.md`를 따른다.

Address/geocoding source도 같은 원칙을 따른다. `python-krtour-map`은 VWorld/Juso/주소점 호출
wrapper가 아니며, TripMate가 `python-kraddr-geo` 또는 `python-vworld-api` public client를
직접 사용하는 reverse geocoder callable을 resource로 넘긴다. 이 라이브러리는 그 결과를
`kraddr.base.Address`와 `AddressCodeSet`으로 정규화하고, provider별 지역 코드는 원문에 보존하되
feature 저장 컬럼에는 검증된 법정동코드만 반영한다. 세부 기준은
`docs/address-geocoding.md`를 따른다.

Feature/source/weather/price 저장소는 `python-krtour-map`의 DB 계약이다. TripMate는 별도 feature DB를 정의하지 않고 `krtour_map.db` schema와 함수를 import해 사용한다.

KRMOIS 인허가 raw/localdata row는 `python-krmois-api` source DB가 보존한다. 이 라이브러리는
`python-krmois-api` public `PlaceRecord`를 직접 읽어 여행자에게 의미 있는 영업중 row만
`Feature`/`PlaceDetail`로 승격하고, KRMOIS raw row를 `source_records`에 중복 저장하지 않는다.
폐업/취소 row는 feature로 남기지 않으며, 필요 시 `python-krmois-api.iter_closed_place_records()`
결과를 이용해 feature 삭제 작업을 실행한다. 세부 기준은
`docs/krmois-license-feature-etl.md`를 따른다.

Korea Heritage source uses canonical provider `python-krheritage-api`, even if a
local workspace folder is named `python-kheritage-api`. Heritage natural keys use
`ccbaKdcd-ccbaAsno-ccbaCtcd`. `search_list` rows create `place` or `area`
features, `gis_spca` and `gis_3070426` enrich coordinates/boundaries, and
`event_list` rows create `event` features. The provider package owns public
clients, typed models, endpoint pagination, exceptions, and raw payload
preservation; `python-krtour-map` consumes those public models directly and does
not add a provider wrapper/adapter/gateway.

The direct provider methods used by ETL are
`HeritageClient.search.iter_all_details(...)`,
`HeritageClient.heritage.iter_all_details(...)`,
`HeritageClient.event.iter_months(...)`, and `HeritageClient.gis.spca(...)`.
TripMate passes the client/session/resources to `python-krtour-map`; this
library performs normalize/load work but does not own Dagster execution.
Provider media models such as image, video, narration/audio, and document URLs are
converted to `FeatureFileSource` here; RustFS upload/config/list logic is not kept
in `python-krheritage-api`.

provider cursor와 실패 상태는 `ProviderSyncState(provider, dataset_key, sync_scope)` 단위로 저장합니다.

## data.go.kr standard-data exception

공공데이터포털 표준데이터 중 다음 5건은 별도 `python-*-api` 라이브러리로 분리하지 않고
`krtour_map.standard_data` 내부의 bounded asyncio client와 ETL에서 처리합니다.
이는 범용 data.go.kr gateway가 아니라 명시된 dataset만 다루는 예외입니다.

| dataset_key | data.go.kr id | Feature |
| --- | --- | --- |
| `standard_tourism_roads` | `15017321` 전국길관광정보표준데이터 | `route` |
| `standard_museums` | `15017323` 전국박물관미술관정보표준데이터 | `place` |
| `standard_parking_lots` | `15012896` 전국주차장정보표준데이터 | `place` |
| `standard_tourist_sites` | `15021141` 전국관광지정보표준데이터 | `place` 우선, 경계 확인 후 `area` 승격 후보 |
| `standard_cultural_festivals` | `15013104` 전국문화축제표준데이터 | `event` |

내장 client는 `StandardDataClient.aio()`로 생성하고, `config`, `catalog`, `client`, `etl`,
`exceptions` 경계를 둡니다. Web debug UI는 `krtour_map.debug_ui`에 포함하되 stdlib 기반
로컬 도구로 제한합니다. raw item은 `source_records.raw_data`에 보존하고, feature id는
provider=`data.go.kr-standard`, dataset key, source entity id, kind, category,
legal dong code 조합으로 생성합니다.
`standard_tourism_roads`는 `feature_route_details.route_type`에 `hiking_trail`,
`accessible_walk`, `trekking`, `tourism_road` 같은 세부 타입을 저장합니다.
