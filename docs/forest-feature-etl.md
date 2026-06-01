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
        coord=Coordinate(lon=station.lon, lat=station.lat),
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

## 11. KNPS (국립공원공단) 데이터 통합

본 라이브러리는 산림청(KFS) 데이터 외에 국립공원공단(KNPS, 환경부 산하)
데이터를 통합 적재한다. **외부 provider 라이브러리는 이미 scaffold 단계까지
완료**되었고 (`digitie/python-knps-api`, `6e36990 Initial KNPS API client
scaffold`), 본 라이브러리에서는 ADR-027 (proposed, PR#9) + **ADR-028
(proposed, 본 PR#12)** 로 통합 계약을 박는다. 실제 적재 코드 (`krtour.map.
providers.knps`)는 Sprint 2 진입 후.

### 11.1 provider 분리 결정 — 옵션 B 채택 (구현 완료)

| 옵션 | 평가 |
|------|------|
| **A. `python-krforest-api` 확장** | 산림청·KNPS 모두 산/등산 도메인이라 사용자 인지에 가깝지만, **두 기관 별도(KFS=농림식품부, KNPS=환경부)**라 라이브러리 컨벤션(1기관 1라이브러리) 위반. 비추천. |
| **B. 별도 `python-knps-api` 신설** ✅ | 컨벤션 일관 (`python-mois-api`, `python-krheritage-api`, `python-khoa-api`, `python-krforest-api`와 동일 패턴). auth/rate limit/exception 독립. KNPS는 file dataset(SHP/GeoJSON) 비중이 큼 → file dataset 처리 모듈 응집. **채택 (2026-05-25, ADR-028 후보)**. |
| C. 본 라이브러리 internal client | ADR-006 (wrapper 금지) + 1기관 1라이브러리 컨벤션 위반. 비추천. |

**채택**: 옵션 B — `python-knps-api` 신설. **외부 repo scaffold 완료**.

| 항목 | 값 |
|------|----|
| GitHub | `digitie/python-knps-api` (`06da125f` 시점 = PR#4 `codex/keyless-file-download-dtos` merged 2026-05-25) |
| canonical provider name | `python-knps-api` |
| import | `from knps import KnpsClient, FileDataset, FileArtifact, ...` (knps-api PR#4 표면 — `ApiEndpoint`/`Page`/`raw_endpoint` 삭제됨, ADR-028 amendment §H) |
| 본 라이브러리 변환 | `krtour.map.providers.knps` (Sprint 3 작성, ADR-034 7단계) |
| dataset_key prefix | `knps_*` |
| 인증 | **없음 (keyless)** — ADR-028 amendment + knps-api PR#4. `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함 |
| Python | `>=3.11` |
| 의존 | `httpx>=0.27`, `pydantic>=2.7`; `pyproj>=3.6`/`pyshp>=2.3`는 `[geo]` extra |
| 라이선스 | GPL-3.0-or-later (본 라이브러리와 동일) |

후속:
- `provider-contract.md` §2 `CANONICAL_PROVIDER_NAMES`에 추가 (본 PR#12).
- `provider-contract.md` §3 dataset_key 표에 14건 file dataset 추가
  (PR#25에서 keyless/file-only 계약으로 정정).
- `provider-contract.md` §4 책임 매트릭스에 한 줄 추가:
  `| python-knps-api | place, route, area, weather | primary | 월/분기/연 |
  국립공원 경계·탐방로·시설·위험지역·문화자원 |` (PR#25에서 notice 제거).
- ~~`external-apis.md` §2 환경변수 카탈로그에 `KNPS_SERVICE_KEY` 추가~~
  → **취소** (knps-api PR#4 keyless): `KNPS_SERVICE_KEY` 사용 안 함.
  external-apis.md §3.8.1은 keyless로 정정 (PR#25).
- `pyproject.toml` `providers` extras에 git URL 핀 (PR#25에서 활성화 —
  `@06da125f`).
- 본 라이브러리에 `docs/knps-feature-etl.md` 신설 — feature 변환 계약
  (knps-api 측 `docs/knps-feature-etl.md`와 정합, 본 PR#12).

### 11.1.1 외부 provider 라이브러리 공개 API (현 구현, `06da125f` = PR#4 keyless)

```python
from knps import (
    KnpsClient,            # 비동기 facade
    KnpsConfig,            # timeout / max_rps만 (api_key/service_key 제거 PR#4)
    CatalogEntry,          # 14 file dataset의 human-readable 표현
    FileDataset,           # data.go.kr 파일데이터 메타
    FileArtifact,          # PR#4 신규: 다운로드 결과 (kind/members/csv_previews)
    FileMember,            # PR#4 신규: ZIP entry 메타
    CsvPreview,            # PR#4 신규: CSV preview (member/encoding/headers/rows)
    CsvPreviewRow,         # PR#4 신규: 한 row (frozen tuple)
    PROVIDER_NAME,         # "python-knps-api"
    # 예외 계층 (KNPS 전용)
    KnpsApiError, KnpsAuthError, KnpsNoDataError, KnpsParseError,
    KnpsRateLimitError, KnpsRequestError, KnpsServerError,
    # catalog helper
    catalog_entries, file_dataset, file_datasets,
)
# 삭제됨 (knps-api PR#3): ApiEndpoint, Page, api_endpoint, api_endpoints,
# KnpsClient.raw_endpoint, KnpsClient.endpoints

async with KnpsClient(max_rps=5.0) as client:
    # 카탈로그 enumerate (14건 all file_dataset)
    for dataset in client.file_datasets():
        print(dataset.key, dataset.data_go_id, dataset.formats,
              dataset.feature_kind, dataset.verification_status)
    # 또는 카테고리 필터
    for spatial in client.file_datasets(category="spatial"):
        ...
    # 다운로드 — raw bytes
    data: bytes = await client.files.download("knps_park_boundaries")
    # 또는 preview용 (debug UI / 디버깅)
    artifact: FileArtifact = await client.files.download_artifact(
        "knps_trails", preview_rows=5,
    )
    for csv in artifact.csv_previews:
        print(csv.member_name, csv.encoding, csv.headers, csv.rows[:1])
```

특이사항 (knps-api PR#3+#4 후, 2026-05-25):
- **OpenAPI/REST 표면 전체 삭제** (PR#3 `aa40541`). data.go.kr API endpoint
  호출 X. 14건 모두 `kind="file_dataset"`로 통일.
- **keyless** (PR#4 `codex/keyless-file-download-dtos`). `KnpsConfig`에
  `api_key`/`service_key` 필드 없음. `KnpsConfig.from_env`는 env var 안 읽음
  (alias for `__init__`).
- 다운로드 URL은 카탈로그에 박혀 있음 (`atchFileId={ID}&fileDetailSn=1&insertDataPrcus=N`).
  `client.files.download(key)`는 항상 `verified` dataset만 — `needs_verification`
  중 `download_url=None`이면 `KnpsRequestError(failure_kind='catalog')`.
- `FileArtifact`는 ZIP/CSV inspect 결과 (members + N개 CSV preview row).
  preview는 **debug UI 용도** — 실 적재는 raw bytes (`client.files.download`).
- **SHP/CSV parser는 본 라이브러리 책임** (knps-api는 raw bytes + preview만).
  `[geo]` extra (`pyshp`, `pyproj`)는 knps-api 측 placeholder — 본 라이브러리
  `providers/knps` (Sprint 3)에서 실제 사용.
- 좌표계: 원본 EPSG:5179 → WGS84 변환은 본 라이브러리 `infra/crs.py`의
  `transformer_4326_to_5179`/`transformer_5179_to_4326` singleton 사용 (PR#21,
  ADR-030 narrow cache).
- CSV 인코딩: knps-api `CsvPreview.encoding`이 자동 감지 (`utf-8-sig`/`utf-8`/
  `cp949`/`euc-kr`). 본 라이브러리 parser는 동일 detection 적용.

### 11.2 v1 단서

v1 `outdoor-feature-etl.md`도 §"후속 보강"에서 동일 결론에 도달:
> "KNPS 국립공원 경계/탐방로/시설 POI source가 필요하면 먼저 provider
> 라이브러리 public model을 안정화한다."

v1에 KNPS dataset ID/필드 단서 없음 — 본 §11이 v2의 첫 정밀 카탈로그.

### 11.3 핵심 dataset 7건 (사용자 명시, PR#25 verified ID 반영)

> PR#25 기준 data.go.kr ID는 knps-api `06da125f`의 `FILE_DATASETS` verified
> catalog와 정합. 모두 file dataset이며 인증 키가 필요 없다.

#### 11.3.1 공원경계 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 공원경계 공간데이터 |
| data.go.kr ID | `15017313` |
| format | SHP (ZIP, file dataset, OpenAPI X) |
| geometry | MultiPolygon (EPSG:5179 → WGS84 변환) |
| 주요 필드 | `PARK_NM` (공원명), `PARK_CD` (공원코드), `AREA` (면적 m²), `OBJECTID`, `geometry` |
| dataset_key | `knps_park_boundaries` |
| FeatureKind | `area` |
| category | **`01020101`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK` |
| area_kind | `national_park` (`AreaDetail.area_kind`) |
| marker_icon | `park` (maki) |
| marker_color | `P-04` (자연/녹색 계열) |
| 갱신 주기 | 연 1회 (`0 3 1 1 *`) — 행정구역 개정 시 |

#### 11.3.2 탐방로 공간데이터

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 탐방로 공간데이터 |
| data.go.kr ID | `15003467` |
| format | CSV |
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
| data.go.kr ID | `15003445` |
| format | CSV |
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
| data.go.kr ID | `15003441` |
| format | CSV |
| geometry | Polygon / MultiPolygon |
| 주요 필드 | `PARK_NM`, `RISK_TYPE` (낙석/추락/급류 등), `RISK_GRD` (등급), `DESC`, `EFF_DATE` (효력일) |
| dataset_key | `knps_hazard_zones` |
| FeatureKind | `area` |
| category | 전용 코드 미존재 — **카테고리 확장 권고**: `SAFETY_HAZARD_ZONE` 신설 (§11.6) |
| area_kind | `hazard_zone` (`AreaDetail.area_kind`) |
| marker_icon | `danger` (maki) |
| marker_color | `P-13` (경고 적색) |
| 갱신 주기 | 월 1회 (`0 3 1 * *`) — 안전 정보는 자주 변동 |

#### 11.3.5 기상관측시설 현황

| 항목 | 값 |
|------|----|
| 공식 이름 | 국립공원공단_국립공원 기상관측시설 현황 |
| data.go.kr ID | `15090557` |
| format | CSV file dataset |
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
| data.go.kr ID | `15003468` |
| format | CSV |
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
| data.go.kr ID | `15003443` |
| format | CSV |
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

### 11.4 추가 발굴 후보 (knps-api PR#4 후 정정, 9건 중 3건 채택 + 4건 source 이전)

knps-api `06da125f` 시점 카탈로그 14건 중 §11.3 7건 외 추가 채택/제외:

| dataset_key | 공식 이름 | FeatureKind | category | 상태 (PR#25 정정) |
|-------------|----------|-------------|----------|-------------------|
| `knps_campgrounds` | 국립공원 야영장 공간데이터 | `place` | **`03060100`** `LODGING_CAMPGROUND_AUTO` | **채택** — knps-api `15003469`. MOIS auto_campgrounds와 sibling 가능 |
| `knps_shelters` | 국립공원 대피소 공간데이터 | `place` | **`03080100`** `LODGING_MOUNTAIN_SHELTER_KNPS` (ADR-027) | **채택** — knps-api `2982556`. 산장/긴급 대피소 |
| `knps_linear_facilities` | 국립공원 선형시설 | `route` | `01020103` 동일 | **채택 (신규, knps-api `15091972`)** — `route_type='facility_road'`. PR#25 신규 항목 |
| `knps_protected_areas` | 국립공원 특별보호구역 | `area` | (no category) | **채택 (신규, knps-api `15127921`)** — `area_kind='protected_area'`. PR#25 신규 항목 |
| ~~`knps_access_restrictions`~~ | ~~국립공원 입산통제구간~~ | `notice` | — | **knps-api PR#3 source 삭제** — 산림청 (`python-krforest-api`) / scrape로 이전. 별도 ADR |
| ~~`knps_fire_alerts`~~ | ~~산불경보 / CCTV stream~~ | `notice` | — | **knps-api PR#3 source 삭제** — 소방청/산림청 별도 source. 별도 ADR |
| ~~`knps_recommended_courses`~~ | ~~국립공원 추천 탐방코스 (난이도별)~~ | `route` | `01020103` | **knps-api PR#3 source 삭제** — visitkorea/scrape로 이전 후속 PR |
| ~~`knps_park_photos`~~ | ~~국립공원 명소 사진/360 VR~~ | (media) | — | **knps-api PR#3 source 삭제** — KNPS web 직접 fetch (license 확인 후) |
| `knps_basic_statistics` | 국립공원 기초통계 | (timeseries) | — | **feature 본문 X**. knps-api `15087598` `needs_verification` |
| `knps_visitor_statistics` | 국립공원별 월별 탐방객 통계 | (timeseries) | — | **feature 본문 X**. knps-api `15107577` |
| `knps_lod_table_catalog` | KNPS LOD 테이블 카탈로그 | (메타) | — | **적재 안 함**. knps-api `15118945` self-meta — upstream catalog 보강용 |
| `knps_vegetation_zones` | 국립공원 식생도 | `area` | — | **knps-api 카탈로그 외** (외부 보강 시 별도 source) |
| `knps_species_habitats` | 멸종위기종 서식지 | `area` | — | **knps-api 카탈로그 외** (보안 마스킹 필요, 별도 ADR) |

### 11.5 Dagster asset 카탈로그 (KNPS, PR#25 정정 — 11건)

knps-api 14건 중 공간 데이터 11건만 Dagster asset. 통계/메타 3건은 별도
처리 (§11.4 표 참조). 이전 notice asset 2건은 source 이전으로 KNPS 표에서
제거.

| asset | dataset_key | cron | group | concurrency |
|-------|-------------|------|-------|------|
| `feature_area_knps_park_boundaries` | `knps_park_boundaries` | `0 3 1 1 *` (연) | `features_area` | `knps_api: 1` |
| `feature_route_knps_trails` | `knps_trails` | `0 3 1 */3 *` (분기) | `features_route` | 동일 |
| `feature_route_knps_linear_facilities` | `knps_linear_facilities` | `0 3 1 1 *` (연) | `features_route` | 동일 |
| `feature_place_knps_visitor_centers` | `knps_visitor_centers` | `0 3 1 1,7 *` (반기) | `features_place` | 동일 |
| `feature_area_knps_hazard_zones` | `knps_hazard_zones` | `0 3 1 * *` (월) | `features_area` | 동일 |
| `feature_area_knps_protected_areas` | `knps_protected_areas` | `0 3 1 1 *` (연) | `features_area` | 동일 |
| `feature_weather_knps_stations` | `knps_weather_stations` | `0 3 1 1 *` (연 메타) | `features_weather` | 동일 |
| `feature_place_knps_restrooms` | `knps_restrooms` | `0 3 1 1,7 *` (반기) | `features_place` | 동일 |
| `feature_place_knps_cultural_resources` | `knps_cultural_resources` | `0 3 1 1 *` (연) | `features_place` | 동일 |
| `feature_place_knps_campgrounds` | `knps_campgrounds` | `0 3 1 */3 *` (분기) | `features_place` | 동일 |
| `feature_place_knps_shelters` | `knps_shelters` | `0 3 1 1 *` (연) | `features_place` | 동일 |

이전 표의 `notice_knps_*` 2건 / `feature_route_knps_recommended_courses`는
knps-api PR#3 source 삭제로 제거. 다른 provider로 이전 (별도 후속 ADR/PR).

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

1. **완료**: 옵션 B 채택 + `python-knps-api` 저장소 신설 + ADR-027/028 accepted.
2. **완료**: PR#25에서 knps-api PR#3+#4 keyless/file-only 계약 동기.
3. **Sprint 3 구현**: `krtour.map.providers.knps` 모듈 신설, raw bytes 기반
   SHP/CSV parsing, `FeatureBundle` 변환, fixture 회귀 테스트.
4. **후속 ADR**: `access_restriction`/`fire_alert` notice source 결정
   (산림청/소방청/scrape). KNPS는 notice source 아님.

### 11.9 좌표/인코딩 처리 (KNPS 공통)

- KNPS 파일은 보통 EPSG:5179 (UTM-K) 좌표를 포함한다. `python-knps-api`는
  raw bytes와 `FileArtifact` preview만 제공하고, WGS84 변환은 본 라이브러리
  `providers/knps`에서 수행한다.
- 한국어 필드 CP949 인코딩 가능 — `shapefile.Reader(encoding='cp949')` 또는
  `pyogrio.read_dataframe(..., encoding='cp949')`.
- `features.geom` PostGIS 컬럼은 4326. `coord_5179` generated column으로 반경
  검색 호환 (ADR-012).
