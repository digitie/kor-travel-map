# 산림·등산 feature ETL

산림·등산 feature는 TripMate의 과거 `docs/architecture/outdoor-feature-db.md` 내용을
`python-krtour-map` 기준으로 옮긴 문서다. 산, 휴양림, 수목원, 등산로, 숲길, 산악기상 context를
공통 feature/source/weather 계약으로 정리한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-krforest-api`, 보조 source로 `python-krmois-api` |
| 주요 dataset key | `forest_recreation_forests`, `forest_arboretums`, `forest_trails`, `forest_mountain_weather` |
| feature kind | `place`, `area`, `route`; 산악기상은 `WeatherValue` |
| 코드 entrypoint | `krtour_map.forest` |
| DB load | `load_krforest_result(session, result)` |

## Provider 경계

`python-krtour-map`은 산림청 API wrapper를 만들지 않는다. `python-krforest-api` public client와
typed model을 직접 사용하고, 부족한 endpoint, geometry model, pagination, exception, raw payload
보존은 `python-krforest-api`에서 먼저 안정화한다.

KRMOIS 인허가 row는 이 문서의 primary outdoor source가 아니다. 캠핑장, 휴양업처럼 산림 여행을
보조하거나 교차검증할 장소는 [KRMOIS license feature ETL](krmois-license-feature-etl.md) 기준에
따라 feature로 승격한다.

## Dataset 매핑

| dataset_key | public client/model | feature/detail |
| --- | --- | --- |
| `forest_recreation_forests` | `travel.standard_recreation_forests()` | `place`, `PlaceDetail.place_kind="recreation_forest"` |
| `forest_arboretums` | `travel.recreation_forest_arboretums()` | `place`, `PlaceDetail.place_kind="arboretum"` |
| `forest_trails` | `travel.forest_trail_file_features()`, `travel.dulle_trail_features()` | `route` 또는 `area`, `RouteDetail`/`AreaDetail` |
| `forest_mountain_weather` | 산악기상 관측/예보 typed model | `WeatherValue` |

## 매핑 규칙

- 휴양림과 수목원은 point `place` feature로 적재한다.
- 등산로/둘레길/숲길은 geometry가 LineString이면 `route`, Polygon/MultiPolygon이면 `area`로 적재한다.
- 산 또는 국립공원 경계가 별도 provider geometry로 안정화되기 전까지 centroid-only area는 보수적으로
  다루고, raw geometry/source를 payload에 보존한다.
- `RouteDetail.route_type`은 `hiking_trail`, `trekking`, `forest_trail` 같은 provider-neutral 값을
  사용한다.
- 산악기상은 장소 feature 본문에 섞지 않고 `feature_weather_values`에 저장한다.

## 주소와 좌표

좌표는 `kraddr.base.PlaceCoordinate`를 사용한다. 원천에 주소 코드가 없고 좌표가 있으면
`python-kraddr-geo` 기반 reverse geocoder callable 또는 `kraddr_geo_*` resource로 법정동코드를
보강할 수 있다. provider별 지역 코드는 raw/payload에 보존하고 feature 저장 컬럼에는 검증된
법정동코드만 반영한다.

## DB 적재

- `collect_krforest_recreation_features(items, ...)`
- `collect_krforest_spatial_features(items, ...)`
- `async_collect_krforest_recreation_features(client, ...)`
- `async_collect_krforest_arboretum_features(client, ...)`
- `async_collect_krforest_trail_features(client, ...)`
- `collect_krforest_mountain_weather_values(items, feature_id_by_source_key=...)`
- `load_krforest_result(session, result)`

Transaction commit/rollback은 호출자가 담당한다. 이 라이브러리는 staged write와 DTO/row 변환만
수행한다.

## TripMate 이관 메모

TripMate의 과거 `map_features`, `outdoor_feature_profiles`, provider ref table 설계는 이 저장소의
공통 `features`, `source_records`, `source_links`, `feature_place_details`,
`feature_area_details`, `feature_route_details`, `feature_weather_values` 계약으로 흡수한다.
TripMate에는 사용자 일정/POI와 API response 조립만 남긴다.

## 후속 보강

- KNPS 국립공원 경계/탐방로/시설 POI source가 필요하면 먼저 provider 라이브러리 public model을
  안정화한다.
- 산 경계 polygon, route topology, 입구/주차장 POI가 추가되면 `AreaDetail`/`RouteDetail` payload가
  아니라 공통 조회 필드로 승격할지 별도 결정한다.
- 산림 안전 notice는 [공지 feature ETL](notice-feature-etl.md)의 `forest_safety_notices` 기준을
  따른다.
