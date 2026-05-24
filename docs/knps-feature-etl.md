# knps-feature-etl.md — KNPS feature 적재 계약

본 문서는 `python-knps-api`가 제공하는 endpoint/dataset을 본 라이브러리의
`Feature` / `AreaDetail` / `RouteDetail` / `NoticeDetail` / `WeatherValue`로
정규화하는 ETL 계약이다. ADR-027 (forest 카테고리/notice_type 확장,
proposed) + **ADR-028 (`python-knps-api` provider 등록, proposed)** 기준.

> upstream (`digitie/python-knps-api`) 측 동일 주제 문서:
> `docs/knps-feature-etl.md`. 본 문서는 *downstream(`python-krtour-map`) 입장*
> 의 ETL 계약. 두 문서는 dataset_key, category 코드, notice_type, area_kind
> 표기를 정합 유지한다 (PR로 양방향 동기).

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-knps-api` (`digitie/python-knps-api`) |
| import | `from knps import KnpsClient, KnpsConfig, ApiEndpoint, FileDataset, ...` |
| Python | `>=3.11` |
| 인증 env | `KNPS_SERVICE_KEY` 우선, `DATA_GO_KR_SERVICE_KEY` 폴백 |
| 코드 entrypoint (본 라이브러리) | `krtour.map.providers.knps` (Sprint 2 작성) |
| Feature.kind | `place`, `area`, `route`, `notice`, `weather` |
| 갱신 주기 | API notice 30분~일, 파일 공간데이터 월~연 |
| 라이선스 | GPL-3.0-or-later (upstream과 동일) |
| Upstream PR 워크플로 | `python-krtour-map` 측에서 발견한 maki/카테고리/명명 정합 이슈는 upstream PR로 적극 수정 (ADR-025 사용자 보강 패턴 미러). 예: knps-api PR#1 `docs/knps-feature-maki-icons` (shelter/barrier 정정). |

## 2. dataset 매핑 (총 14건 = API 3 + 파일 11)

### 2.1 API endpoints (3건)

| dataset_key (knps-api) | data.go.kr ID | feature.kind | notice_type | upstream verification | 비고 |
|------------------------|---------------|--------------|-------------|----------------------|------|
| `knps_visitor_statistics` | `15107577` | (none, timeseries) | — | `needs_verification` | API endpoint 제공 여부 live 검증. timeseries는 별도 처리 (3.5). |
| `knps_access_restrictions` | TBD | `notice` | `access_restriction` (ADR-027 generic) | `planned` | `payload.domain='forest'` 박음. |
| `knps_fire_alerts` | TBD | `notice` | `fire_alert` (ADR-027 generic) | `planned` | `payload.domain='forest'`. |

### 2.2 파일 datasets (11건)

| dataset_key (knps-api) | data.go.kr ID | feature.kind | category / area_kind | upstream verification | 비고 |
|------------------------|---------------|--------------|---------------------|----------------------|------|
| `knps_park_boundaries` | `15084538` | `area` | `area_kind='national_park'` | `needs_verification` | MultiPolygon. polygon centroid가 `feature.coord`. |
| `knps_trails` | `15084540` | `route` | `route_type='hiking_trail'` | `needs_verification` | LineString/MultiLineString. |
| `knps_visitor_centers` | `15084541` | `place` | `01060101` `TOURISM_INFORMATION_CENTER_PUBLIC` | `needs_verification` | Point. `place_kind='visitor_center'`. |
| `knps_hazard_zones` | `15084542` | `area` | `area_kind='hazard_zone'` (ADR-027) | `needs_verification` | Polygon. `payload.hazard_type`, `payload.risk_grade`, `payload.domain='forest'`. |
| `knps_weather_stations` | `15084543` | `weather` (anchor) | (kind=weather, category 없음) | `needs_verification` | Point. weather feature anchor. 관측값은 별도 API 확보 후 `WeatherValue` 분리 적재. |
| `knps_restrooms` | `15084544` | `place` | `05060000` `CONVENIENCE_TOILET` | `needs_verification` | Point. `place_kind='restroom_national_park'`. |
| `knps_cultural_resources` | `15084545` | `place` | (subtype 분기, 2.3) | `needs_verification` | Point. RESOURCE_TYPE에 따라 사찰/유적/기타로 category 분기. |
| `knps_campgrounds` | TBD | `place` (또는 area) | `03060100` `LODGING_CAMPGROUND_AUTO` | `needs_verification` | Point/Polygon. `place_kind='campground'`. |
| `knps_shelters` | TBD | `place` | **`03080100` `LODGING_MOUNTAIN_SHELTER_KNPS`** (ADR-027) | `planned` | Point. `place_kind='mountain_shelter'`. maki `shelter`. |
| `knps_recommended_courses` | TBD | `route` | `01020103` `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` | `planned` | LineString. `RouteDetail.difficulty` 직접 채움. |
| `knps_park_photos` | TBD | (none, media) | — | `planned` | feature 본문 X. `feature_files` + `source_links(role='media')`로 연결. |

### 2.3 cultural_resources subtype 분기

`knps_cultural_resources` raw record의 `RESOURCE_TYPE` (또는 유사 필드)에
따라:

| RESOURCE_TYPE 패턴 | category | place_kind | maki |
|--------------------|----------|-----------|------|
| `사찰` | `01070100` `TOURISM_HERITAGE_TEMPLE` | `temple` | `religious-buddhist` |
| `유적`, `사적`, `기념물` | `01070300` `TOURISM_HERITAGE_HISTORIC_SITE` | `historic_site` | `monument` |
| 기타 | `01070000` `TOURISM_HERITAGE` | `cultural_resource` | `monument` |

## 3. 매핑 룰

### 3.1 area (공원경계 / 위험지역)
- `feature.kind='area'`, `AreaDetail.area_kind` 적절히 설정.
- `feature.coord` = polygon centroid (`ST_Centroid`).
- `feature.geom` = MultiPolygon (EPSG:4326 변환 후 저장).
- 위험지역은 카테고리 트리에 진입하지 않음 — `category=NULL` 또는 sentinel
  `00000000`. 식별은 `AreaDetail.area_kind='hazard_zone'`로만.

### 3.2 route (탐방로 / 추천 탐방코스)
- `feature.kind='route'`, `RouteDetail.route_type` 적절히 설정.
- `feature.geom` = LineString/MultiLineString (EPSG:4326 변환 후).
- 구간 상태가 통제이면 `RouteDetail.payload.status='restricted'` 보존 + notice
  dataset과 `source_links`로 연결 (양방향 cross-reference).
- `knps_recommended_courses`는 `RouteDetail.difficulty` 1~5 직접 채움.

### 3.3 place (시설)
- `feature.kind='place'`, `PlaceDetail.place_kind` 적절히 설정.
- 화장실/탐방안내소/야영장/대피소/문화자원 모두 place.
- 좌표는 raw record point.

### 3.4 weather (관측시설 anchor)
- `feature.kind='weather'`, category는 없음 (`weather` kind 자체가 분류).
- meta: `station_type='mountain'` (선택).
- 실제 관측값은 별도 `WeatherValue` 적재 — 본 dataset은 anchor만.

### 3.5 notice (입산통제 / 산불경보)
- `feature.kind='notice'`, `NoticeDetail.notice_type` = `access_restriction`
  또는 `fire_alert` (ADR-027 generic).
- `NoticeDetail.payload.domain='forest'`.
- `valid_start_time`/`valid_end_time` 보존.
- `source_links(role='source')`에 KNPS 발표 URL.
- 만료된 notice는 ADR-017 보관 정책에 따라 +1y 후 purge.

### 3.6 timeseries / media (feature 본문 X)
- `knps_visitor_statistics`: feature 본문에 섞지 않음. 별도 timeseries 테이블
  (Sprint 3+ 도입 시점에 ADR 신설) 또는 `ops.api_call_log` 옆 통계 테이블.
  v2 1차 범위 밖.
- `knps_park_photos`: `feature_files` 또는 `source_links(role='media')`로
  기존 KNPS 시설/area feature에 연결. feature 본문 X.

## 4. category 매핑 요약 (검증된 표)

| 종류 | category 코드 | detail | maki |
|------|---------------|--------|------|
| 국립공원 경계 | (area, no category) | `area_kind='national_park'` | (polygon, no maki) |
| 탐방로/추천코스 | `01020103` `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` | `route_type='hiking_trail'` | (route, no maki) |
| 탐방안내소 | `01060101` `TOURISM_INFORMATION_CENTER_PUBLIC` | `place_kind='visitor_center'` | `information` |
| 위험지역 | (area, no category) | `area_kind='hazard_zone'` | (polygon, marker maki `barrier`) |
| 화장실 | `05060000` `CONVENIENCE_TOILET` | `place_kind='restroom_national_park'` | `toilet` |
| 문화자원: 사찰 | `01070100` `TOURISM_HERITAGE_TEMPLE` | `place_kind='temple'` | `religious-buddhist` |
| 문화자원: 유적 | `01070300` `TOURISM_HERITAGE_HISTORIC_SITE` | `place_kind='historic_site'` | `monument` |
| 문화자원: 기타 | `01070000` `TOURISM_HERITAGE` | `place_kind='cultural_resource'` | `monument` |
| 야영장 | `03060100` `LODGING_CAMPGROUND_AUTO` | `place_kind='campground'` | `campsite` |
| 대피소 | **`03080100` `LODGING_MOUNTAIN_SHELTER_KNPS`** (ADR-027) | `place_kind='mountain_shelter'` | **`shelter`** (ADR-027) |
| 산악 관측소 | (weather, no category) | meta `station_type='mountain'` | (anchor, fallback maki) |

> upstream knps-api docs/knps-feature-etl.md §4 표와 1:1 일치. upstream PR#1
> (`docs/knps-feature-maki-icons`)에서 `shelter`/`barrier` maki icon 정정
> 적용 후.

## 5. 핵심 함수 (Sprint 2 작성 시 시그니처 후보)

```python
# src/krtour/map/providers/knps/__init__.py
from collections.abc import AsyncIterable
from datetime import datetime
from krtour.map.dto import FeatureBundle, NoticeDetail, WeatherValue
from knps import FileDataset, Page, ApiEndpoint

DATASET_KEYS_KNPS_FILE = (
    "knps_park_boundaries", "knps_trails", "knps_visitor_centers",
    "knps_hazard_zones", "knps_weather_stations", "knps_restrooms",
    "knps_cultural_resources", "knps_campgrounds", "knps_shelters",
    "knps_recommended_courses",
)
DATASET_KEYS_KNPS_NOTICE = ("knps_access_restrictions", "knps_fire_alerts")
DATASET_KEYS_KNPS_MEDIA = ("knps_park_photos",)

async def park_boundaries_to_bundles(
    raw_bytes: bytes, *, fetched_at: datetime,
    reverse_geocoder=None,
) -> list[FeatureBundle]: ...

async def trails_to_bundles(
    raw_bytes: bytes, *, fetched_at: datetime,
    reverse_geocoder=None,
) -> list[FeatureBundle]: ...

async def facility_points_to_bundles(
    raw_bytes: bytes, *, dataset_key: str, fetched_at: datetime,
    reverse_geocoder=None,
) -> list[FeatureBundle]: ...

async def hazard_zones_to_bundles(
    raw_bytes: bytes, *, fetched_at: datetime,
    reverse_geocoder=None,
) -> list[FeatureBundle]: ...

async def access_restrictions_page_to_notices(
    page: Page, *, fetched_at: datetime,
) -> list[NoticeDetail]: ...

async def fire_alerts_page_to_notices(
    page: Page, *, fetched_at: datetime,
) -> list[NoticeDetail]: ...
```

SHP/GeoJSON parsing은 `pyproj` + `pyshp` 또는 `pyogrio` 사용. ADR-007 GDAL
의존 그대로.

## 6. Dagster asset 카탈로그

| asset | dataset_key | cron | group | concurrency |
|-------|-------------|------|-------|-------------|
| `feature_area_knps_park_boundaries` | `knps_park_boundaries` | `0 3 1 1 *` (연) | `features_area` | `knps_api: 1` |
| `feature_route_knps_trails` | `knps_trails` | `0 3 1 */3 *` (분기) | `features_route` | `knps_api: 1` |
| `feature_place_knps_visitor_centers` | `knps_visitor_centers` | `0 3 1 1,7 *` (반기) | `features_place` | `knps_api: 1` |
| `feature_area_knps_hazard_zones` | `knps_hazard_zones` | `0 3 1 * *` (월) | `features_area` | `knps_api: 1` |
| `feature_weather_knps_stations` | `knps_weather_stations` | `0 3 1 1 *` (연 메타) | `features_weather` | `knps_api: 1` |
| `feature_place_knps_restrooms` | `knps_restrooms` | `0 3 1 1,7 *` (반기) | `features_place` | `knps_api: 1` |
| `feature_place_knps_cultural_resources` | `knps_cultural_resources` | `0 3 1 1 *` (연) | `features_place` | `knps_api: 1` |
| `feature_place_knps_campgrounds` | `knps_campgrounds` | `0 3 1 */3 *` (분기) | `features_place` | `knps_api: 1` |
| `feature_place_knps_shelters` | `knps_shelters` | `0 3 1 1 *` (연) | `features_place` | `knps_api: 1` |
| `feature_route_knps_recommended_courses` | `knps_recommended_courses` | `0 3 1 */3 *` (분기) | `features_route` | `knps_api: 1` |
| `notice_knps_access_restrictions` | `knps_access_restrictions` | `0 5 * * *` (일 + on-demand) | `features_notice` | `knps_api: 1` |
| `notice_knps_fire_alerts` | `knps_fire_alerts` | `*/30 * * * *` (30분) | `features_notice` | `knps_api: 1` |

`knps_park_photos`/`knps_visitor_statistics`는 별도 처리 (3.6).

## 7. 검증

### 7.1 fixture (Sprint 2)
- dataset별 최소 1건 + geometry type별 1건 이상.
- `knps_park_boundaries`: 1 park 1 polygon + 1 multipolygon.
- `knps_trails`: 1 trail 1 LineString + 1 MultiLineString.
- `knps_hazard_zones`: hazard_type 3종 (rockfall, flash_flood, wildlife).
- `knps_access_restrictions`: 입산통제 시작/종료 + on-demand.
- `knps_fire_alerts`: severity 등급별 1건.

### 7.2 통합 테스트 (EXPLAIN)
- area centroid + GiST(`coord_5179`) 인덱스 사용 검증 (ADR-012).
- notice `notice_type='access_restriction'` partial index 사용 (`docs/
  performance.md §6`).
- BRIN index on `notice_knps_*` `valid_start_time` (시계열 BRIN, ADR-014).

### 7.3 정합성 (ADR-033 Phase 1, Sprint 3~4)
- F1 (orphan source) — KNPS raw가 있는데 Feature 없음.
- F2 (detail 누락) — `kind=place`인데 `PlaceDetail` 없음.
- F3 (CRS drift) — `coord_5179 ≠ ST_Transform(coord, 5179)`.

### 7.4 upstream verification (knps-api 측)
- knps-api catalog `verification_status="needs_verification"` 항목은 live
  test 후 `verified`로 승격 (upstream 책임).
- upstream PR이 dataset 추가/제거 시 본 §2 표 동기 (양방향 reference).

## 8. 후속 작업

1. **knps-api 측 verification_status `verified` 승격**: data.go.kr ID 확정,
   직접 다운로드 URL 검증. upstream live test 책임.
2. **knps-api 측 SHP/GeoJSON parser 추가 또는 본 라이브러리 측 파싱**:
   현 시점 knps-api는 `[geo]` extra placeholder. Sprint 2 진입 시 결정 —
   knps-api에 PR로 parser 추가 vs 본 라이브러리 `providers/knps`에서 처리.
3. **ADR-028 accepted 전환**: T-018 시점에 본 라이브러리 통합 구현과 함께.
4. **ADR-027 accepted 전환**: T-018 시점에 `LODGING_MOUNTAIN_SHELTER` 코드
   적용과 함께 (`PLACE_CATEGORY_DEFINITIONS`에 3행 추가).

## 9. 비책임

- KNPS 예약/결제: KNPS 예약 시스템 정책 + robots/login 흐름 확인 전까지
  제외 (upstream knps-api docs/knps-api.md §"제외/보류"와 일치).
- 식생도 / 멸종위기종 서식지: v2 1차 범위 밖 (ADR-027 §D 거부). 보안 마스킹
  정책 선행 필요.
- 사진/VR 원본 호스팅: 본 라이브러리 RustFS에 복사하지 않고 `source_links`
  URL만 보존 — 저작권 + 트래픽 비용 절감.
