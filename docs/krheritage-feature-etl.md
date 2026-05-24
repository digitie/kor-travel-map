# 국가유산 feature ETL

`python-krtour-map`은 국가유산청 데이터를 `place`, `area`, `event` feature로 정리한다.
provider 호출은 안정된 `python-krheritage-api` public API 표면에 남기며, 이 라이브러리는
`KheritageWrapper`, `HeritageAdapter`, TripMate 전용 gateway를 만들지 않는다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-krheritage-api` |
| dataset key | `search_list`, `gis_spca`, `gis_3070426`, `event_list` |
| feature kind | `place`, `area`, `event` |
| source type | `heritage`, `heritage_event` |
| detail table | `feature_place_details`, `feature_area_details`, `feature_event_details`, `feature_files` |
| 코드 entrypoint | `krtour_map.heritage` |

## 원천 라이브러리

- Provider package: `python-krheritage-api`
- import module: `krheritage`
- 표준 provider name: `python-krheritage-api`
- 과거 로컬 폴더명 alias: `python-kheritage-api`

endpoint 범위, typed model, pagination, cursor 처리, exception, raw payload 보존은
provider package가 소유한다. `python-krtour-map`은 provider public model을
feature/source/detail/file row로 변환한다.

## `dataset_key`

| dataset_key | 목적 | feature 출력 |
| --- | --- | --- |
| `search_list` | `SearchKindOpenapiList`, `SearchKindOpenapiDt` 기반 국가유산 요약/상세 model | `place` 또는 `area` |
| `gis_spca` | `gis-heritage.go.kr/openapi/xmlService/spca.do` 기반 과거 GIS 위치 API | 좌표/경계 보강 |
| `gis_3070426` | 좌표, 면적, 규제 범위, media metadata가 있는 공공데이터 공간 dataset | `area` 경계/detail 보강 |
| `event_list` | `selectEventListOpenapi` 같은 국가유산 행사 목록 | `event` |
| `15145324` | 고시/공고 source 후보 | 향후 `notice` 보강 |
| `15041861` | 무형유산 행사/source 후보 | 향후 `event` 보강 |

## Feature 매핑

국가유산 record의 source natural key는 다음 형식을 사용한다.

```text
ccbaKdcd-ccbaAsno-ccbaCtcd
```

매핑 규칙:

- 국보, 보물, 등록문화유산, 민속/유형 유산 대부분은 `place` feature로 만든다.
- 사적, 사적 및 명승, 명승, 매장유산, GIS geometry가 있는 record는 `area` feature로 만든다.
- 경계가 없는 천연기념물은 `place`로 유지하고, 서식지나 보호구역처럼 GIS geometry가 있으면
  `area`로 만든다.
- 무형유산 전수교육관과 공연장은 `place`로 만들고, 공연/교육 프로그램은 `event`로 만든다.
- 행사 row는 provider event id인 `sn`을 `source_entity_id`로 사용한다.

KRMOIS는 상업/장소 row의 넓은 base dataset으로 남는다. 국가유산 record가 feature를 직접 만들면
`primary` source가 되고, 이미 다른 source에서 승격된 실제 장소와 같다면 host merge process가
`enrichment` source로 연결할 수 있다.

## Feature별 상세 기준

국가유산 `place` feature:

- `PlaceDetail.place_kind`는 `heritage_site`, `natural_heritage`,
  `intangible_heritage_venue` 같은 값을 사용한다.
- 지정일, 관리자/관리 기관, 유산 유형 코드, provider 분류는 `PlaceDetail.payload`에 저장한다.
- provider 상세에 사용 가능한 WGS84 좌표가 없으면 좌표는 `None`을 허용한다. source row는 이후
  GIS 보강을 위해 계속 보존한다.

국가유산 `area` feature:

- `AreaDetail.area_kind`는 `heritage_area`, `natural_heritage_area`,
  `buried_heritage_area` 같은 값을 사용한다.
- natural key가 매칭되면 `gis_3070426` 또는 `gis_spca`의 안정된 GIS geometry를 우선한다.
- API 목록이 대표 좌표를 사용할 수 있도록 centroid/point 자료와 boundary geometry를 payload에서
  분리해 보존한다.

국가유산 `event` feature:

- provider event id `sn`을 `source_entity_id`로 사용한다.
- 행사 기간은 `EventDetail.starts_on`/`ends_on`, 장소 텍스트는 `EventDetail.venue_name`에 저장한다.
- 대표 이미지와 관련 media는 `FeatureFileSource`로 다룬다. provider package는 typed URL/raw media
  model을 소유하고, 이 라이브러리는 RustFS 업로드와 `feature_files` metadata를 소유한다.

검토용 필드:

- `Feature.detail.selected_source`: provider, dataset key, source type, natural key, 선택 confidence.
- `Feature.detail.address_codes`: provider 원본 주소/코드 필드와 `AddressMatchReport` 결과.
- `Feature.detail.heritage`: 유산 유형/domain/category, 지정 정보, 관리자, source URL hint,
  raw-derived long-tail 값.

## DB 스키마

국가유산 place row는 기존 `features`, `source_records`, `source_links`,
`feature_place_details`, `feature_files` table을 사용한다.

국가유산 area row는 `feature_area_details`를 사용한다.

| 컬럼 | 의미 |
| --- | --- |
| `feature_id` | `features.feature_id` FK이자 primary key |
| `area_kind` | `heritage_area`, `natural_heritage_area`, provider별 area kind |
| `boundary_source` | `gis_3070426`, `gis_spca` 또는 다른 public dataset key |
| `area_square_meters` | provider가 제공한 면적 값 |
| `regulation_scope` | 보호/규제 범위 텍스트 |
| `administrative_office` | 관리 기관 또는 관리자 |
| `description` | 구역 설명 또는 본문 텍스트 |
| `geometry` | GeoJSON-like geometry payload |
| `payload` | provider detail payload와 match metadata |

이미지, 동영상, 내레이션/오디오, 문서 asset은 feature row에 직접 저장하지 않는다. RustFS에
업로드하고 1:N `feature_files` row로 표현한다. `python-krheritage-api`는 typed media URL/raw
model만 소유하며, RustFS upload/list/config 로직은 `python-krtour-map`에 둔다.

## Dagster 경계

이 라이브러리는 ETL 본문과 정규화된 DB 적재 helper를 소유한다.

- `collect_krheritage_heritage_features(items, ...)`
- `load_krheritage_heritage_result(session, result, ...)`
- `load_krheritage_heritage_features(resource, run)`
- `collect_krheritage_events(items, ...)`
- `load_krheritage_event_result(session, result, ...)`
- `load_krheritage_events(resource, run)`

실제 Dagster 실행, schedule, resource, 운영 알림은 TripMate가 소유한다. TripMate는
`krheritage` public client 또는 이미 수집된 provider model, feature DB session, 선택적 RustFS
store, 선택적 file fetcher, 선택적 reverse geocoder callable을 넘긴다.

`krheritage.HeritageClient`가 resource로 전달되면 ETL 본문은 provider public API를 직접 사용한다.

- 국가유산 place/area scan: `client.heritage.iter_all_details(...)` 또는
  `client.search.iter_all_details(...)`
- 행사 scan: `client.event.iter_months(...)`
- GIS 좌표/경계 source: `client.gis.spca(...)`는 caller가 provider model source로 받을 수 있으며,
  heritage natural key에 매칭한 뒤 같은 normalize/load 흐름에 넣는다.

지원하는 run config key는 TripMate wrapper 없이 provider client에 전달한다.
`page_size`, `max_pages`, `ccba_kdcd`, `ccba_ctcd`, `ccba_asno`, `st_ccba_asdt`,
`st_ccba_aedt`, `ccba_cndt`, `ccba_mnm1`, `search_year`, `search_month`,
`months_back`, `months_ahead`를 지원한다. `ccbaKdcd` 같은 camel-case API key는 public client 호출
전에 provider service의 snake-case 인자로 정규화한다.

이 라이브러리가 노출하는 job spec:

- `krheritage_heritage_full_scan_job_spec`: 주간 전체 스캔. tag에는 `schedule:weekly`,
  `feature:place`, `feature:area`가 포함된다.
- `krheritage_event_full_scan_job_spec`: 일간 전체 스캔. tag에는 `schedule:daily`,
  `feature:event`가 포함된다.

`KHERITAGE_API_KEY`, `KRHERITAGE_API_KEY`, `DATA_GO_KR_SERVICE_KEY` 중 하나가 있으면 schedule을
활성화할 수 있다.

## 주소와 좌표

좌표는 `python-kraddr-base`의 `PlaceCoordinate`를 local `Coordinate` alias로 사용한다. 객체를
만들 때는 `lat`, `lon` 순서를 사용하고, DB row는 `latitude`, `longitude` 컬럼을 명시한다.

주소 보강은 공통 `AddressMatchReport` 흐름을 따른다. provider 주소 텍스트와 좌표 기반
법정동 정보는 provider 전용 DB 컬럼을 추가하지 않고 `Feature.detail.address_codes`에 보존한다.

## python-krheritage-api 요구사항

provider package는 아래 필드 또는 동등한 alias가 있는 안정된 public model을 제공해야 한다.

- `HeritageKey.ccba_kdcd`, `ccba_asno`, `ccba_ctcd`, `natural_key`
- `HeritageSummary` / `HeritageDetail`: `key`, `name_ko`, `longitude`, `latitude`,
  `image_url`, `domain`, `category`, `location_text`, `designated_at`, `manager`,
  `content`, `raw` 또는 `model_dump(mode="json")`
- `HeritageEvent`: `sn`, `title` 또는 `sub_title`, `sub_title2`, `starts_on`,
  `ends_on`, `place`, `address`, `tel_name`, `contents`, `main_image`, `longitude`,
  `latitude`
- `GeoFeature`: `geometry`, 그리고 area source identity를 만들 안정 id를 담은 `properties`

필요한 endpoint, field, pagination helper, exception, raw payload 규칙이 없으면
`python-krheritage-api`에서 먼저 수정한다. TripMate나 `python-krtour-map`에 임시 provider wrapper를
추가하지 않는다.
