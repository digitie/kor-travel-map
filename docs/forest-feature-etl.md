# forest-feature-etl.md — 산림청 + 국립공원공단(KNPS) ETL

본 문서는 다음 두 기관 데이터를 `place`/`area`/`route` + `WeatherValue`로
정규화하는 ETL이다:

- **산림청** (`python-krforest-api`): 휴양림 / 수목원 / 숲길 / 등산로 / 산악기상
  / 산림 안전공지
- **국립공원공단 KNPS** (data.go.kr public datasets): 공원경계 / 탐방로 /
  탐방안내소 / 위험지역 / 기상관측 / 화장실 / 문화자원 등

> KNPS는 현재 별도 provider 라이브러리가 없다. 본 문서는 KNPS 데이터 통합
> 계획을 박아두는 곳이며, 실제 적재 코드는 `python-krforest-api` 후속 PR
> (또는 별도 `python-knps-api` — 본 doc §11에서 결정)에서 다룬다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krforest-api` |
| dataset_key | `forest_recreation_forests`, `forest_arboretums`, `forest_trails`, `forest_mountain_weather` |
| Feature.kind | `place`, `area`, `route` / `WeatherValue` |
| 코드 entrypoint | `krtour.map.providers.krforest`, `krtour.map.forest` |
| 갱신 주기 | provider별 (place/area/route 월~분기, 산악기상 시간 단위) |

## 2. dataset 매핑

| dataset_key | provider client/model | feature/detail |
|-------------|---------------------|----------------|
| `forest_recreation_forests` | `travel.recreation_forests()` | `place`, `place_kind="recreation_forest"` |
| `forest_arboretums` | `travel.arboretums()` | `place`, `place_kind="arboretum"` |
| `forest_trails` | `travel.forest_trail_file_features()` / `dulle_trail_features()` | LineString → `route` / Polygon → `area` |
| `forest_mountain_weather` | 산악기상 관측/예보 typed model | `WeatherValue` |

## 3. 매핑 룰

- 휴양림 / 수목원: 단일 point → `place`
- 등산로 / 둘레길 / 숲길: 
  - LineString / MultiLineString → `route`
  - Polygon / MultiPolygon → `area`
- 산악기상: `feature_weather_values`에 저장 (장소 detail에 섞지 X)
- `RouteDetail.route_type` ∈ `hiking_trail` / `trekking` / `forest_trail`

## 4. category (`docs/category.md` §4)

| 종류 | category 코드 | Tier path | marker_icon |
|------|-------------|-----------|------------|
| 국립 휴양림 (산림청 운영) | **`03030101`** `LODGING_RECREATION_FOREST_NATIONAL_KFS` | 숙박 > 휴양림 > 국립휴양림 > 산림청 운영 | `park` |
| 공립 휴양림 | **`03030201`** `LODGING_RECREATION_FOREST_PUBLIC_LOCAL` | 숙박 > 휴양림 > 공립휴양림 > 지자체 운영 | `park` |
| 사립 휴양림 | **`03030301`** `LODGING_RECREATION_FOREST_PRIVATE_OPERATOR` | 숙박 > 휴양림 > 사립휴양림 > 민간 운영 | `park` |
| 수목원 (공립) | **`01030102`** `TOURISM_BOTANICAL_GARDEN_PUBLIC` | 관광 > 수목원·식물원 > 수목원 > 공립 | `garden` |
| 수목원 (국립) | **`01030101`** `TOURISM_BOTANICAL_GARDEN_NATIONAL` | 동일 > 국립 | `garden` |
| 수목원 (사립) | **`01030103`** `TOURISM_BOTANICAL_GARDEN_PRIVATE` | 동일 > 사립 | `garden` |
| 숲길/산림욕장 | **`01020103`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` | 관광 > 자연경관 > 산·계곡 > 산림욕장 | `park` |
| 등산로 (route) | route는 카테고리보다 `RouteDetail.route_type=hiking_trail`로 1차 분류. 보조 category는 `01080500` `TOURISM_ACTIVITY_TREKKING` | 관광 > 액티비티 > 트레킹·둘레길 | `park` |
| 산악기상 anchor | weather-only marker — `features.category`는 비움 또는 `01050300` `TOURISM_NATURE_OBSERVATORY` 대용. 후속 ADR에서 `WEATHER_MOUNTAIN_STATION` 신설 검토 (§11.6) | n/a | `marker` |

## 5. 핵심 함수

```python
# providers/krforest.py
async def recreation_forests_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> AsyncIterator[FeatureBundle]:
    ...

async def arboretums_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> AsyncIterator[FeatureBundle]:
    ...

async def forest_trails_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> AsyncIterator[FeatureBundle]:
    """LineString → route, Polygon → area로 분기."""
    for item in items:
        kind = FeatureKind.AREA if _is_polygon(item.geometry) else FeatureKind.ROUTE
        yield _trail_to_bundle(item, kind=kind, ...)

async def mountain_weather_to_values(items, *, feature_id_by_obs_id, fetched_at) -> AsyncIterator[WeatherValue]:
    """관측소 ID → feature_id 매핑 dict 필요."""
    ...
```

## 6. DB 적재

```python
from krtour.map.forest import (
    collect_krforest_recreation_features,
    collect_krforest_arboretum_features,
    collect_krforest_trail_features,
    collect_krforest_mountain_weather_values,
    load_krforest_result,
)

async def run_krforest_recreation(client, async_session, reverse_geocoder):
    result = await collect_krforest_recreation_features(client, reverse_geocoder=reverse_geocoder)
    await load_krforest_result(async_session, result)
    await async_session.commit()
```

## 7. 산악기상 매핑

`mountain_weather_to_values`는 관측소 ID → feature_id 매핑 dict가 필요:
- 옵션 A: weather-only `Feature(kind=weather)`를 산악기상 관측소마다 생성
- 옵션 B: 인근 휴양림 feature에 연결
- v2 1차: 옵션 A 권장 (관측소 ID 안정성 우선)

```python
# 미리 weather-only feature 생성
mountain_stations = list(await client.aget_all_mountain_stations())
station_features = [
    Feature(
        feature_id=make_feature_id(
            bjd_code=None, kind=FeatureKind.WEATHER,
            category="WEATHER_MOUNTAIN_STATION",
            source_type="mountain_station",
            source_natural_key=station.obs_id,
        ),
        kind=FeatureKind.WEATHER,
        name=f"산악기상 {station.obs_name}",
        coord=PlaceCoordinate(lat=station.lat, lon=station.lon),
        ...
    )
    for station in mountain_stations
]
# load + 매핑
feature_id_by_obs_id = {f.detail.payload["obs_id"]: f.feature_id for f in station_features}

# 시간 단위로 weather value 적재
values = mountain_weather_to_values(items, feature_id_by_obs_id=feature_id_by_obs_id)
await upsert_weather_values(session, values)
```

## 8. Dagster

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `feature_place_krforest_recreation` | `forest_recreation_forests` | `0 2 1 * *` (월 1회) | `features_place` |
| `feature_place_krforest_arboretums` | `forest_arboretums` | `0 2 1 * *` | `features_place` |
| `feature_route_krforest_trails` | `forest_trails` | `0 2 1 * *` | `features_route` |
| `weather_krforest_mountain` | `forest_mountain_weather` | `0 * * * *` (시간) | `features_weather` |
| `notice_krforest_safety` | `forest_safety_notices` (별도 — notice doc) | `*/30 * * * *` | `features_notice` |

ConcurrencyConfig: `krforest_api: max_concurrent=1`.

## 9. 검증

### fixture (≥ 3)

- `recreation_forest_typical.json` — 휴양림 정상
- `arboretum_typical.json` — 수목원
- `trail_with_linestring.json` — 등산로 (route)
- `trail_with_polygon.json` — 둘레길 (area)
- `mountain_weather_typical.json` — 산악기상

### 통합 테스트

- LineString/Polygon 분기 (`forest_trails_to_bundles`)
- 산악기상 관측소 매핑 (`feature_id_by_obs_id`)
- weather value bulk 적재 (BRIN 효율)

## 10. 후속

- 산 경계 polygon source 추가 (산림청 provider 결정).
- 산림 안전 공지 — `docs/notice-feature-etl.md`의 `forest_safety_notices`.
- 추가 산악기상 dataset (산불위험, 산사태위험): `weather_domain ∈ {forest_fire_risk, forest_landslide_risk}` — `docs/weather-feature-normalization.md` §3.

## 11. KNPS (국립공원공단) 데이터 통합 계획

본 라이브러리는 산림청(KFS) 데이터 외에 국립공원공단(KNPS, 환경부 산하)
데이터를 통합 적재할 계획이다. **현재 단계는 docs/계약만**이며, 실제 client
라이브러리/적재 코드는 후속 PR.

### 11.1 provider 분리 결정 (권고)

| 옵션 | 평가 |
|------|------|
| **A. `python-krforest-api` 확장** | 산림청·KNPS 모두 산/등산 도메인이라 사용자 인지에 가깝지만, **두 기관 별도(KFS=농림식품부, KNPS=환경부)**라 라이브러리 컨벤션(1기관 1라이브러리) 위반. 비추천. |
| **B. 별도 `python-knps-api` 신설** | 컨벤션 일관 (`python-krmois-api`, `python-krheritage-api`, `python-khoa-api`, `python-krforest-api`와 동일 패턴). auth/rate limit/exception 독립. KNPS는 file dataset(SHP/GeoJSON) 비중이 큼 → file dataset 처리 모듈 응집. **권고**. |
| C. 본 라이브러리 internal client | ADR-006 (wrapper 금지) + 1기관 1라이브러리 컨벤션 위반. 비추천. |

**결정 (사용자 검토 필요)**: 옵션 B — `python-knps-api` 신설.

- canonical provider name: `python-knps-api`
- import: `from knps import KnpsClient`
- 본 라이브러리 변환: `krtour.map.providers.knps`
- 본 라이브러리 loader: `krtour.map.knps`
- dataset_key prefix: `knps_*`
- `provider-contract.md` §2 `CANONICAL_PROVIDER_NAMES`에 추가
- `provider-contract.md` §3 dataset_key 표에 아래 §11.3 13건 추가
- `provider-contract.md` §4 책임 매트릭스에 한 줄 추가:
  `| python-knps-api | place, route, area, notice, weather | primary | 일/분기/연 | 국립공원 경계·탐방로·시설·위험지역·문화자원 |`

### 11.2 v1 단서

v1 `outdoor-feature-etl.md`도 §"후속 보강"에서 동일 결론에 도달:
> "KNPS 국립공원 경계/탐방로/시설 POI source가 필요하면 먼저 provider
> 라이브러리 public model을 안정화한다."

v1에 KNPS dataset ID/필드 단서 없음 — 본 §11이 v2의 첫 정밀 카탈로그.

### 11.3 핵심 dataset 7건 (사용자 명시)

> data.go.kr ID는 web access 차단 환경에서 작성되어 **확인 필요**.
> 검색 entry: `https://www.data.go.kr/tcs/dss/selectDataSetList.do?orgFullName=국립공원공단`

#### 11.3.1 공원경계 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 공원경계 공간데이터 |
| data.go.kr ID | `15084538` (확인 필요) |
| format | SHP (ZIP) / GeoJSON (file dataset, OpenAPI X) |
| geometry | MultiPolygon (EPSG:5179 또는 5186 → WGS84 변환) |
| 주요 필드 | `PARK_NM` (공원명), `PARK_CD` (공원코드), `AREA` (면적 m²), `OBJECTID`, `geometry` |
| dataset_key | `knps_park_boundaries` |
| FeatureKind | `area` |
| category | **`01020101`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK` |
| area_kind | `national_park` (`kraddr.base.domains`에 이미 정의됨) |
| marker_icon | `park` (maki) |
| marker_color | `P-04` (자연/녹색 계열) |
| 갱신 주기 | 연 1회 (`0 3 1 1 *`) — 행정구역 개정 시 |

#### 11.3.2 탐방로 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 탐방로 공간데이터 |
| data.go.kr ID | `15084540` (확인 필요) |
| format | SHP / GeoJSON |
| geometry | LineString / MultiLineString |
| 주요 필드 | `PARK_NM`, `TRAIL_NM` (탐방로명), `TRAIL_CD`, `LENGTH` (구간거리 m), `DIFFICULTY` (난이도), `STATUS` (개방/통제), `UP_TIME` (오르막 시간), `DOWN_TIME` |
| dataset_key | `knps_trails` |
| FeatureKind | `route` |
| category | **`01020103`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` (산림청 숲길과 카테고리 공유) |
| route_type | `hiking_trail` (`ROUTE_TYPE_HIKING_TRAIL`) |
| marker_icon | `park` (산림 통일) 또는 `attraction` |
| marker_color | `P-04` |
| 갱신 주기 | 분기 1회 (`0 3 1 1,4,7,10 *`) |

#### 11.3.3 탐방안내소 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 탐방안내소 공간데이터 |
| data.go.kr ID | `15084541` (확인 필요) |
| format | SHP / GeoJSON |
| geometry | Point |
| 주요 필드 | `PARK_NM`, `FAC_NM` (시설명), `FAC_CD`, `ADDR`, `TEL`, `LON`, `LAT` |
| dataset_key | `knps_visitor_centers` |
| FeatureKind | `place` |
| category | **`01060101`** `TOURISM_INFORMATION_CENTER_PUBLIC` |
| place_kind | `visitor_center` |
| marker_icon | `information` |
| marker_color | `P-04` |
| 갱신 주기 | 반기 1회 (`0 3 1 1,7 *`) |

#### 11.3.4 위험지역 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 위험지역 공간데이터 |
| data.go.kr ID | `15084542` (확인 필요) |
| format | SHP / GeoJSON |
| geometry | Polygon / MultiPolygon |
| 주요 필드 | `PARK_NM`, `RISK_TYPE` (낙석/추락/급류 등), `RISK_GRD` (등급), `DESC`, `EFF_DATE` (효력일) |
| dataset_key | `knps_hazard_zones` |
| FeatureKind | `area` |
| category | 전용 코드 미존재 — **카테고리 확장 권고**: `SAFETY_HAZARD_ZONE` 신설 (§11.6) |
| area_kind | `hazard_zone` (`kraddr.base.domains` 확장 후보) |
| marker_icon | `danger` (maki) |
| marker_color | `P-13` (경고 적색) |
| 갱신 주기 | 월 1회 (`0 3 1 * *`) — 안전 정보는 자주 변동 |

#### 11.3.5 기상관측시설 현황

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 기상관측시설 현황 |
| data.go.kr ID | `15084543` (확인 필요) |
| format | JSON/XML OpenAPI 또는 CSV file dataset |
| geometry | Point |
| 주요 필드 | `OBS_ID`, `OBS_NM`, `PARK_NM`, `LON`, `LAT`, `INSTALL_DATE`, `ELEV` (해발고도) |
| dataset_key | `knps_weather_stations` |
| FeatureKind | `weather` (관측소 anchor — weather-only marker) |
| category | 전용 코드 미존재 — **카테고리 확장 권고**: `WEATHER_MOUNTAIN_STATION` 신설 (§11.6) |
| marker_icon | `observation-tower` 또는 `marker` |
| marker_color | `P-09` (정보/청색) |
| 갱신 주기 | 시설 메타 연 1회 + 관측치는 산림청 산악기상 (`forest_mountain_weather`) 또는 신설 `knps_mountain_weather` (시간 단위) |

산악기상 관측치 자체는 본 doc §3 `forest_mountain_weather`에 통합 적재 — KNPS는
관측소 메타데이터(좌표/소속/고도)만 제공.

#### 11.3.6 화장실 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 화장실 공간데이터 |
| data.go.kr ID | `15084544` (확인 필요) |
| format | SHP / GeoJSON |
| geometry | Point |
| 주요 필드 | `PARK_NM`, `FAC_NM`, `FAC_TYPE` (수세식/이동식), `MALE_CNT`, `FEMALE_CNT`, `DISABLED` (장애인용 Y/N) |
| dataset_key | `knps_restrooms` |
| FeatureKind | `place` |
| category | **`05060000`** `CONVENIENCE_TOILET` |
| place_kind | `restroom_national_park` (일반 `CONVENIENCE_TOILET`과 공유, place_kind로 구분) |
| marker_icon | `toilet` |
| marker_color | `P-09` |
| 갱신 주기 | 반기 1회 |

#### 11.3.7 문화자원 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 문화자원 공간데이터 |
| data.go.kr ID | `15084545` (확인 필요) |
| format | SHP / GeoJSON |
| geometry | Point |
| 주요 필드 | `PARK_NM`, `RESOURCE_NM`, `RESOURCE_TYPE` (사찰/탑/비석/유적 등), `HERITAGE_CD` (지정 문화재 번호, nullable), `DESC` |
| dataset_key | `knps_cultural_resources` |
| FeatureKind | `place` |
| category | `RESOURCE_TYPE`에 따라 분기:<br>- 사찰 → **`01070100`** `TOURISM_HERITAGE_TEMPLE`<br>- 유적/사적 → **`01070300`** `TOURISM_HERITAGE_HISTORIC_SITE`<br>- 기타 → **`01070000`** `TOURISM_HERITAGE` |
| place_kind | `cultural_resource` (또는 분기된 `temple` / `historic_site`) |
| marker_icon | `monument` / `religious-buddhist` |
| marker_color | `P-07` |
| 갱신 주기 | 연 1회 |
| 비고 | krheritage 카테고리와 중복 가능 — `sibling_group_id`로 묶기, dedup_review_queue 후보 |

### 11.4 추가 발굴 후보 (8건)

| dataset_key | 공식 이름 | FeatureKind | category | 비고 |
|-------------|----------|-------------|----------|------|
| `knps_campgrounds` | 국립공원 야영장 공간데이터 | `place` (또는 area) | **`03060100`** `LODGING_CAMPGROUND_AUTO` | MOIS auto_campgrounds와 sibling 가능 |
| `knps_shelters` | 국립공원 대피소 공간데이터 | `place` | **`03080100`** `LODGING_MOUNTAIN_SHELTER_KNPS` (ADR-027) | 산장/긴급 대피소 |
| `knps_access_restrictions` | 국립공원 입산통제구간 | `notice` (+ area) | n/a (notice는 `notice_type`으로) | `notice_type=access_restriction` (ADR-027, generic), `payload.domain='forest'` |
| `knps_vegetation_zones` | 국립공원 식생도 | `area` | 미적용 — v2 1차 범위 밖 (ADR-027 거부) | 학술용. 향후 분석 도구에서 raw 사용 |
| `knps_species_habitats` | 멸종위기종 서식지 | `area` | 미적용 — v2 1차 범위 밖 (ADR-027 거부) | 보안상 마스킹 필요. 향후 도입 시 별도 ADR |
| `knps_park_photos` | 국립공원 명소 사진/360 VR | (feature 본문 X) | n/a | `feature_files` (RustFS) + `source_links(role='media')` |
| `knps_visitor_statistics` | 국립공원별 월별 탐방객 통계 | (feature 본문 X) | n/a | timeseries — 본 라이브러리 범위 밖 (`python-knps-api`만 raw 보존) |
| `knps_recommended_courses` | 국립공원 추천 탐방코스 (난이도별) | `route` | **`01020103`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` | LineString (탐방로 조합). `RouteDetail.difficulty` 직접 채움 |
| `knps_fire_alerts` | 산불경보 / CCTV stream | `notice` | n/a | `notice_type=fire_alert` (ADR-027, generic), `payload.domain='forest'` |

### 11.5 Dagster asset 카탈로그 (KNPS, 권고)

| asset | dataset_key | cron | group | concurrency |
|-------|-------------|------|-------|------|
| `feature_area_knps_park_boundaries` | `knps_park_boundaries` | `0 3 1 1 *` (연) | `features_area` | `knps_api: 1` |
| `feature_route_knps_trails` | `knps_trails` | `0 3 1 */3 *` (분기) | `features_route` | 동일 |
| `feature_place_knps_visitor_centers` | `knps_visitor_centers` | `0 3 1 1,7 *` (반기) | `features_place` | 동일 |
| `feature_area_knps_hazard_zones` | `knps_hazard_zones` | `0 3 1 * *` (월) | `features_area` | 동일 |
| `feature_weather_knps_stations` | `knps_weather_stations` | `0 3 1 1 *` (연 메타) | `features_weather` | 동일 |
| `feature_place_knps_restrooms` | `knps_restrooms` | `0 3 1 1,7 *` (반기) | `features_place` | 동일 |
| `feature_place_knps_cultural_resources` | `knps_cultural_resources` | `0 3 1 1 *` (연) | `features_place` | 동일 |
| `feature_place_knps_campgrounds` | `knps_campgrounds` | `0 3 1 */3 *` (분기) | `features_place` | 동일 |
| `feature_place_knps_shelters` | `knps_shelters` | `0 3 1 1 *` (연) | `features_place` | 동일 |
| `notice_knps_access_restrictions` | `knps_access_restrictions` | `0 5 * * *` (일 + on-demand) | `features_notice` | 동일 |
| `notice_knps_fire_alerts` | `knps_fire_alerts` | `*/30 * * * *` (30분) | `features_notice` | 동일 |

### 11.6 카테고리/도메인 확장 (ADR-027 결정 요약)

KNPS dataset 통합에 필요한 분류 확장은 **ADR-027** (proposed)로 결정됨.
요약:

| 항목 | 결정 | 위치 / 코드 |
|------|------|------------|
| 대피소·산장 | ✅ **신규 PlaceCategory** | `03.08 LODGING_MOUNTAIN_SHELTER` Tier 2 + `03.08.01` KNPS / `03.08.02` KFS Tier 3 |
| 위험지역 (낙석/급류 등) | ✅ **신규 area_kind** (PlaceCategory 미신설) | `AreaDetail.area_kind='hazard_zone'` + `payload.hazard_type` |
| 입산통제 | ✅ **신규 notice_type** (generic) | `notice_type='access_restriction'` + `payload.domain='forest'` |
| 산불경보 | ✅ **신규 notice_type** (generic) | `notice_type='fire_alert'` + `payload.domain='forest'` |
| 산악 관측소 | ❌ 카테고리 미신설 | `kind=weather` 자체로 분류 + `meta.station_type='mountain'` |
| 위험지역 SAFETY Tier 1 | ❌ 거부 | area_kind=hazard_zone로 대체. Tier 1 enum 변경은 광범위 영향 |
| 식생/서식지 (`NATURE_ECOLOGY`) | ❌ v2 1차 범위 밖 | 학술용 — 향후 분석 도구에서 raw 사용 |

신규 명명 일반화 원칙 (사용자 결정 2026-05-25):
- notice_type은 `forest_*` prefix 미사용 — 산림 외 도메인(해변/도시) 재사용
  가능한 generic 이름. provider 출처는 `NoticeDetail.payload.domain`으로
  구분.
- Tier 1 PlaceCategory enum은 8개 그대로 유지 (Tier 2 추가만으로 해결).

자세한 근거 / 후속 작업은 `docs/decisions.md` ADR-027 참조.

### 11.7 라이선스

KNPS data.go.kr 대부분 KOGL Type 1 (출처 표기, 상업 이용 가능). `python-knps-api`
README + 본 저장소 NOTICE에 출처 표기 의무.

### 11.8 후속 작업 순서

1. **사용자 검토**: 옵션 B 권고 + 카테고리 확장 후보 결정
2. **`python-knps-api` 저장소 신설**: `digitie/python-knps-api`
   - `python-mois-api` 패턴 미러 (file dataset client + OpenAPI client + SQLite source DB)
   - SHP/GeoJSON parsing (`pyogrio` 또는 `shapefile`)
   - EPSG:5179/5186 → WGS84 변환 (`pyproj`)
3. **본 라이브러리에 통합**:
   - ADR-027 (카테고리/notice_type 확장, proposed → accepted 전환) +
     ADR-028 (`python-knps-api` provider 등록, 후속 후보)
   - `provider-contract.md` §2/§3/§4 갱신
   - `krtour.map.providers.knps` 모듈 신설
   - `docs/knps-feature-etl.md` 신설 (본 §11이 옮겨감)
4. **data.go.kr ID 확정**: web access 권한 부여 후 7건 ID 검증 + 누락 dataset 발굴

### 11.9 좌표/인코딩 처리 (KNPS 공통)

- KNPS SHP는 보통 EPSG:5179 (UTM-K) 또는 5186 (단북원점). `python-knps-api`가
  WGS84(`PlaceCoordinate(lat, lon)`)로 변환 후 본 라이브러리에 전달.
- 한국어 필드 CP949 인코딩 가능 — `shapefile.Reader(encoding='cp949')` 또는
  `pyogrio.read_dataframe(..., encoding='cp949')`.
- `features.geom` PostGIS 컬럼은 4326. `coord_5179` generated column으로 반경
  검색 호환 (ADR-012).
