# knps-feature-etl.md — KNPS feature 적재 계약

본 문서는 `python-knps-api`가 제공하는 14건 **file dataset**을 본 라이브러리의
`Feature` / `AreaDetail` / `RouteDetail` / `WeatherValue`로 정규화하는 ETL
계약이다. ADR-027 (forest 카테고리/notice_type 확장) + **ADR-028 (`python-knps-api`
provider 등록) + Amendment 2026-05-25 (keyless + file-only)** 기준.

> upstream (`digitie/python-knps-api`) 측 동일 주제 문서: `docs/knps-feature-
> etl.md`. 본 문서는 *downstream(`python-krtour-map`) 입장*의 ETL 계약.
> 두 문서는 dataset_key, category 코드, area_kind 표기를 정합 유지한다 (PR로
> 양방향 동기).
>
> **knps-api PR#3+#4 변경 반영 (2026-05-25, 본 PR#25)**: OpenAPI 표면 전체
> 제거 → 14건 모두 file dataset. 인증 env 제거 (keyless data.go.kr 직접
> 다운로드 URL). 이전 표(API 3 + 파일 11)는 무효.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-knps-api` (`digitie/python-knps-api`, commit `06da125f`) |
| import | `from knps import KnpsClient, FileDataset, FileArtifact, ...` (아래 §5) |
| Python | `>=3.11` |
| 인증 | **없음 (keyless)** — knps-api PR#4. data.go.kr 직접 다운로드 URL 사용. `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함 (ADR-028 amendment) |
| 코드 entrypoint (본 라이브러리) | `krtour.map.providers.knps` (Sprint 3 작성, ADR-034 7단계) |
| Feature.kind | `place`, `area`, `route`, `weather` (notice는 다른 source — ADR-028 amendment) |
| 갱신 주기 | 모두 파일 데이터 (월~연 갱신). real-time notice 없음 |
| 라이선스 | GPL-3.0-or-later (upstream과 동일) |
| Rate limit | `KnpsClient(max_rps=5.0)` 기본 (token bucket). data.go.kr 정책 5 RPS 보수치 |
| Upstream PR 워크플로 | `python-krtour-map` 측에서 발견한 maki/카테고리/명명 정합 이슈는 upstream PR로 적극 수정 (ADR-025 사용자 보강 패턴 미러). 예: knps-api PR#1 `docs/knps-feature-maki-icons` (shelter/barrier 정정). |

## 2. dataset 매핑 (총 14건 = 모두 file dataset, keyless)

knps-api `knps.catalog.FILE_DATASETS` 14건 (`from knps import file_datasets`
로 enumerate). 모두 `kind="file_dataset"`, 13건 `verification_status='verified'`,
1건 `needs_verification`.

### 2.1 공간 데이터 (11건)

| dataset_key | data.go.kr ID | format | geometry | feature.kind | category / area_kind |
|-------------|---------------|--------|----------|--------------|----------------------|
| `knps_park_boundaries` | `15017313` | SHP (ZIP) | MultiPolygon | `area` | `area_kind='national_park'` |
| `knps_trails` | `15003467` | CSV | LineString | `route` | `route_type='hiking_trail'` |
| `knps_visitor_centers` | `15003445` | CSV | Point | `place` | `01060101` `TOURISM_INFORMATION_CENTER_PUBLIC`, `place_kind='visitor_center'` |
| `knps_hazard_zones` | `15003441` | CSV | Polygon | `area` | `area_kind='hazard_zone'` (ADR-027). `payload.hazard_type`/`risk_grade`/`domain='forest'` |
| `knps_weather_stations` | `15090557` | CSV | Point | `weather` (anchor) | (kind=weather, no category) |
| `knps_restrooms` | `15003468` | CSV | Point | `place` | `05060000` `CONVENIENCE_TOILET`, `place_kind='restroom_national_park'` |
| `knps_cultural_resources` | `15003443` | CSV | Point | `place` | (subtype 분기 §2.3) |
| `knps_campgrounds` | `15003469` | CSV | Point | `place` | `03060100` `LODGING_CAMPGROUND_AUTO`, `place_kind='campground'` |
| `knps_shelters` | `2982556` | CSV | Point | `place` | **`03080100` `LODGING_MOUNTAIN_SHELTER_KNPS`** (ADR-027), `place_kind='mountain_shelter'`, maki `shelter` |
| `knps_linear_facilities` | `15091972` | CSV | LineString | `route` | `route_type='facility_road'` (탐방로 외 시설 도로) |
| `knps_protected_areas` | `15127921` | CSV | Polygon | `area` | `area_kind='protected_area'` (특별보호구역). `payload.protection_type` 보존 |

### 2.2 비공간/통계/메타 (3건)

| dataset_key | data.go.kr ID | format | feature 본문 처리 |
|-------------|---------------|--------|-------------------|
| `knps_basic_statistics` | `15087598` | CSV | **needs_verification** — feature 본문 X. 통계 테이블 (v2 1차 범위 밖, Sprint 3+ 결정) |
| `knps_visitor_statistics` | `15107577` | CSV/XLSX | feature 본문 X. 별도 timeseries 테이블 또는 dashboard용 raw 보관만 |
| `knps_lod_table_catalog` | `15118945` | CSV | 메타 카탈로그 — 적재 안 함. knps-api catalog 보강용 (upstream PR로 활용) |

### 2.3 cultural_resources subtype 분기

`knps_cultural_resources` raw record의 `RESOURCE_TYPE` (또는 유사 필드)에
따라:

| RESOURCE_TYPE 패턴 | category | place_kind | maki |
|--------------------|----------|-----------|------|
| `사찰` | `01070100` `TOURISM_HERITAGE_TEMPLE` | `temple` | `religious-buddhist` |
| `유적`, `사적`, `기념물` | `01070300` `TOURISM_HERITAGE_HISTORIC_SITE` | `historic_site` | `monument` |
| 기타 | `01070000` `TOURISM_HERITAGE` | `cultural_resource` | `monument` |

### 2.4 삭제된 이전 dataset (knps-api에 더 이상 없음)

knps-api PR#3 (`aa40541`)에서 OpenAPI 표면 삭제로 다음 keys는 카탈로그에서
사라졌다:

- `knps_access_restrictions` (입산통제) — `notice_type='access_restriction'`
- `knps_fire_alerts` (산불경보) — `notice_type='fire_alert'`
- `knps_recommended_courses` — `route_type='recommended_course'`
- `knps_park_photos` — media

**대안 source (후속 ADR로 결정)**:
- 입산통제 / 산불경보 → `python-krforest-api` (산림청), 산림청 RSS 또는 한국
  소방청 API. KNPS 단독 source 아님.
- 추천코스 → KNPS 웹사이트 scrape 또는 `python-visitkorea-api` 산악 카테고리.
- 사진 → 본 라이브러리 `feature_files` 적재 시 KNPS web에서 직접 수집 (license
  확인 후).

## 3. 매핑 룰

### 3.1 area (공원경계 / 위험지역 / 보호지역)
- `feature.kind='area'`, `AreaDetail.area_kind` 적절히 설정.
- `feature.coord` = polygon centroid (`ST_Centroid` — 구현은 shapely centroid).
- `feature.geom` = (Multi)Polygon (EPSG:4326).
- **국립공원 경계**는 실제 관광 category 보유 — `01020101`
  `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK` (upstream §4).
- **위험지역/보호지역**은 카테고리 트리 밖 — sentinel `00000000`. 식별은
  `AreaDetail.area_kind='hazard_zone'`/`'protected_area'`로만.

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

### 3.5 notice (별도 source — KNPS에서 제거)

knps-api PR#3에서 `knps_access_restrictions`/`knps_fire_alerts` 삭제. 본 dataset
은 다른 provider로 대체 (ADR-028 amendment §F):

- 입산통제 (`access_restriction`) → `python-krforest-api` (산림청) 또는 산림청
  RSS scrape. KNPS dataset 사용 안 함.
- 산불경보 (`fire_alert`) → `python-krforest-api` + 한국 소방청 RSS. KNPS dataset
  사용 안 함.

ADR-027 generic notice_type (`access_restriction` / `fire_alert`)은 유효 —
다른 provider에서 NoticeDetail로 생성 시 동일 spec.

### 3.6 통계 / 메타 (feature 본문 X)

- `knps_basic_statistics` (`needs_verification`): feature 본문에 섞지 않음.
  별도 통계 테이블 또는 `ops.api_call_log` 옆 분석 테이블. v2 1차 범위 밖
  (Sprint 3+ 결정).
- `knps_visitor_statistics`: 동일 — timeseries 별도. dashboard용 raw 보관만.
- `knps_lod_table_catalog`: knps-api 자체 카탈로그 메타. **적재 안 함**.
  upstream knps-api catalog 보강 PR 시 참고용.

## 4. category 매핑 요약 (검증된 표)

| 종류 | category 코드 | detail | maki |
|------|---------------|--------|------|
| 국립공원 경계 | `01020101` `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK` | `area_kind='national_park'` | `park` (centroid 마커) |
| 탐방로 | `01020103` `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` | `route_type='hiking_trail'` | `park` |
| 시설 도로 (linear_facilities) | `01020103` 동일 | `route_type='facility_road'` | `park` |
| 탐방안내소 | `01060101` `TOURISM_INFORMATION_CENTER_PUBLIC` | `place_kind='visitor_center'` | `information` |
| 위험지역 | (area, no category) | `area_kind='hazard_zone'` | (polygon, marker maki `barrier`) |
| 특별보호구역 (protected_areas) | (area, no category) | `area_kind='protected_area'` | (polygon, marker maki `barrier`) |
| 화장실 | `05060000` `CONVENIENCE_TOILET` | `place_kind='restroom_national_park'` | `toilet` |
| 문화자원: 사찰 | `01070100` `TOURISM_HERITAGE_TEMPLE` | `place_kind='temple'` | `religious-buddhist` |
| 문화자원: 유적 | `01070300` `TOURISM_HERITAGE_HISTORIC_SITE` | `place_kind='historic_site'` | `monument` |
| 문화자원: 기타 | `01070000` `TOURISM_HERITAGE` | `place_kind='cultural_resource'` | `monument` |
| 야영장 | `03060100` `LODGING_CAMPGROUND_AUTO` | `place_kind='campground'` | `campsite` |
| 대피소 | **`03080100` `LODGING_MOUNTAIN_SHELTER_KNPS`** (ADR-027) | `place_kind='mountain_shelter'` | **`shelter`** (ADR-027) |
| 산악 관측소 | (weather, no category) | meta `station_type='mountain'` | (anchor, fallback maki) |

> upstream knps-api docs/knps-feature-etl.md §4 표와 1:1 일치. upstream PR#1
> (`docs/knps-feature-maki-icons`)에서 `shelter`/`barrier` maki icon 정정
> 적용 후. `linear_facilities`/`protected_areas`는 knps-api PR#4 시점 신규
> 항목 — upstream `docs/knps-feature-etl.md`에 추가 필요 (양방향 sync PR).

## 5. 핵심 함수 (Sprint 3 작성 시 시그니처 후보, ADR-034 7단계)

```python
# src/krtour/map/providers/knps/__init__.py
from datetime import datetime
from krtour.map.dto import FeatureBundle
# knps-api PR#4 이후 공개 API (ApiEndpoint/Page/raw_endpoint/api_endpoints는
# knps-api에서 삭제됨)
from knps import (
    KnpsClient, KnpsConfig, CatalogEntry, FileDataset,
    FileArtifact, FileMember, CsvPreview, CsvPreviewRow,
    PROVIDER_NAME,
    KnpsApiError, KnpsAuthError, KnpsNoDataError, KnpsParseError,
    KnpsRateLimitError, KnpsRequestError, KnpsServerError,
    catalog_entries, file_dataset, file_datasets,
)

# 공간 데이터 11건 (변환 함수 11개)
DATASET_KEYS_KNPS_SPATIAL = (
    "knps_park_boundaries", "knps_trails", "knps_visitor_centers",
    "knps_hazard_zones", "knps_weather_stations", "knps_restrooms",
    "knps_cultural_resources", "knps_campgrounds", "knps_shelters",
    "knps_linear_facilities", "knps_protected_areas",
)
# feature 본문 X (적재 안 함 또는 별도 timeseries 테이블)
DATASET_KEYS_KNPS_STATS = (
    "knps_basic_statistics", "knps_visitor_statistics", "knps_lod_table_catalog",
)

# 구현된 공개 API (raw bytes를 받지 않음 — knps-api가 파싱한 record를 소비).
# Point/place 5건:
def knps_point_records_to_bundles(
    records: Iterable[KnpsPointRecord], *, dataset_key: str, fetched_at: datetime,
) -> list[FeatureBundle]:
    """visitor_centers/restrooms/cultural_resources/campgrounds/shelters →
    place FeatureBundle. dataset_key로 category 분기 (cultural_resources는 subtype)."""

# route/area 5건 (geometry WKT 4326 입력):
def knps_geometry_records_to_bundles(
    records: Iterable[KnpsGeometryRecord], *, dataset_key: str, fetched_at: datetime,
) -> list[FeatureBundle]:
    """trails/linear_facilities → route, park_boundaries/hazard_zones/
    protected_areas → area. centroid를 coord로, geom(WKT)을 Feature.geom으로.
    파싱실패/경계밖/type불일치 행은 skip."""

# knps-api CsvPreview 브리지 (knps-api parse_records API가 아직 없을 때 — 현재 경로).
# knps-api는 CSV를 CsvPreview(헤더+행)로 파싱해 주므로, 그 행을 직접 bundle로 잇는다.
def knps_csv_preview_to_point_bundles(
    preview: KnpsCsvPreview, *, dataset_key: str, fetched_at: datetime,
    column_map: KnpsPointColumnMap | None = None,
) -> list[FeatureBundle]:
    """CsvPreview(헤더→값 행) → place bundle. column_map None이면 best-guess
    KNPS_DEFAULT_POINT_COLUMN_MAP(경도/위도/명칭/관리번호 후보). ⚠️ live headers 검증."""

def knps_csv_preview_to_geometry_bundles(
    preview: KnpsCsvPreview, *, dataset_key: str, fetched_at: datetime,
    column_map: KnpsGeometryColumnMap | None = None,
) -> list[FeatureBundle]:
    """CsvPreview → route/area bundle (geom WKT 컬럼). WKT 컬럼 없는 행 skip."""

# 호출 측 예시 (Sprint 3 Dagster asset 내부)
async def example_dagster_op() -> None:
    async with KnpsClient(max_rps=5.0) as client:
        # (A) CSV Point: 현재 가능 — download_artifact preview_rows를 크게.
        artifact = await client.files.download_artifact(
            "knps_restrooms", preview_rows=10**9,
        )
        for preview in artifact.csv_previews:
            # ⚠️ preview.headers로 실제 컬럼명 확인 후 column_map 지정 권장.
            bundles = knps_csv_preview_to_point_bundles(
                preview, dataset_key="knps_restrooms", fetched_at=kst_now(),
            )
        # (B) SHP geometry: knps-api가 WGS84 WKT를 노출한 뒤 (upstream PR) 직접.
        # records = await client.files.parse_records("knps_park_boundaries")
        # bundles = knps_geometry_records_to_bundles(records, dataset_key=..., ...)
```

**SHP/CSV parsing 책임 = knps-api (ADR-044)**: 데이터 정합성·파싱의 1차 책임은
provider 라이브러리. 따라서 raw 파일(SHP ZIP / CSV) → typed record(좌표·geometry
**WKT 4326** 포함) 변환은 **knps-api 측**에서 수행한다 (필요 시 upstream PR —
ADR-025 보강 패턴):
- SHP (ZIP) → geometry 디코딩 — knps-api `[geo]` extra(`pyshp`/`pyogrio`/`fiona`)
- CP949/euc-kr 인코딩 처리 (knps-api `CsvPreview.encoding`)
- EPSG:5179 → 4326 좌표계 변환 (knps-api 측에서 4326 WKT/좌표로 노출)

본 라이브러리 `providers/knps`는 그 결과를 `KnpsPointRecord`(좌표) /
`KnpsGeometryRecord`(geometry WKT) Protocol로 **소비**만 한다 — geometry 검증·
centroid·DTO 조립은 `core/geometry.py`(shapely WKT). `shapely`/`pyproj`는 본
라이브러리 본 의존이지만 **`pyshp`/SHP 디코딩은 본 lib에 두지 않는다**(knps-api).

## 6. Dagster asset 카탈로그 (Sprint 3 KNPS 적재 시점, ADR-034 7단계)

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
| `feature_route_knps_linear_facilities` | `knps_linear_facilities` | `0 3 1 1 *` (연) | `features_route` | `knps_api: 1` |
| `feature_area_knps_protected_areas` | `knps_protected_areas` | `0 3 1 1 *` (연) | `features_area` | `knps_api: 1` |

`knps_basic_statistics`/`knps_visitor_statistics`/`knps_lod_table_catalog`는
별도 처리 (§3.6) — feature 적재 안 함.

이전 표의 `notice_knps_access_restrictions` / `notice_knps_fire_alerts` 항목은
knps-api PR#3에서 source 삭제로 제거 — 산림청/소방청 provider로 이전 (별도
ADR).

## 7. 검증

### 7.1 fixture (Sprint 3)
- dataset별 최소 1건 + geometry type별 1건 이상.
- `knps_park_boundaries`: 1 park 1 polygon + 1 multipolygon.
- `knps_trails`: 1 trail 1 LineString + 1 MultiLineString.
- `knps_hazard_zones`: hazard_type 3종 (rockfall, flash_flood, wildlife).
- `knps_protected_areas`: protection_type 2종 (special, restricted_use).
- `knps_linear_facilities`: facility_type 2종 (service_road, boundary_fence).

### 7.2 통합 테스트 (EXPLAIN)
- area centroid + GiST(`coord_5179`) 인덱스 사용 검증 (ADR-012).
- (notice/timeseries 항목은 KNPS 적재 범위에서 제외 — 산림청/소방청 별도 source.)

### 7.3 정합성 (ADR-033 Phase 1, Sprint 3~4)
- F1 (orphan source) — KNPS raw가 있는데 Feature 없음.
- F2 (detail 누락) — `kind=place`인데 `PlaceDetail` 없음.
- F3 (CRS drift) — `coord_5179 ≠ ST_Transform(coord, 5179)`.

### 7.4 upstream verification (knps-api 측)
- knps-api catalog `verification_status="needs_verification"` 항목은 live
  test 후 `verified`로 승격 (upstream 책임).
- upstream PR이 dataset 추가/제거 시 본 §2 표 동기 (양방향 reference).

## 8. 후속 작업

1. **knps-api 측 `knps_basic_statistics` verification 승격**: 13/14
   `verified`, 1건 (`knps_basic_statistics`)만 `needs_verification`. live
   download 테스트 후 upstream에 verification PR.
2. **본 라이브러리 SHP/CSV parser 구현 (Sprint 3 ADR-034 7단계)**: knps-api
   raw bytes + `FileArtifact` preview만 제공 — 실 parser는 본 라이브러리
   `providers/knps`. `pyshp` + `shapely` + `pyproj` (이미 본 의존).
3. **`access_restriction` / `fire_alert` notice source 결정 (별도 ADR)**:
   knps-api PR#3에서 source 삭제 → 산림청 (`python-krforest-api`) /
   소방청 (`python-fireapi` TBD) / scrape 중 선택. Sprint 3 이전에 ADR.
4. **`knps_lod_table_catalog` 활용**: knps-api `FILE_DATASETS` 카탈로그
   보강에 사용 — upstream PR로 직접 반영 (downstream에서는 적재 안 함).

## 9. 비책임

- KNPS 예약/결제: KNPS 예약 시스템 정책 + robots/login 흐름 확인 전까지
  제외 (upstream knps-api docs/knps-api.md §"제외/보류"와 일치).
- 식생도 / 멸종위기종 서식지: v2 1차 범위 밖 (ADR-027 §D 거부). 보안 마스킹
  정책 선행 필요.
- 사진/VR 원본 호스팅: 본 라이브러리 RustFS에 복사하지 않고 `source_links`
  URL만 보존 — 저작권 + 트래픽 비용 절감.
