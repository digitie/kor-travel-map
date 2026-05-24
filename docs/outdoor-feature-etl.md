# outdoor-feature-etl.md — 산림청 outdoor (휴양림/숲길/산악기상) ETL

본 문서는 산림청(`python-krforest-api`) 데이터 — 휴양림/수목원/숲길/등산로/
산악기상 — 를 `place`/`area`/`route` + `WeatherValue`로 정규화하는 ETL이다.

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

## 4. category

| 종류 | category |
|------|---------|
| 휴양림 | `LEISURE_NATURE_RECREATION_FOREST` (또는 `TOURISM_NATURE_FOREST`) |
| 수목원 | `TOURISM_NATURE_ARBORETUM` |
| 숲길/등산로 | `LEISURE_HIKING_TRAIL` 또는 route_type별 분류 |
| 산악기상 anchor | `weather` kind (weather-only marker) |

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

- KNPS (국립공원공단) 경계/탐방로/시설 POI — provider 라이브러리에서 먼저.
- 산 경계 polygon source 추가 (provider 결정).
- 산림 안전 공지 — `docs/notice-feature-etl.md`의 `forest_safety_notices`.
- 추가 산악기상 dataset (산불위험, 산사태위험): `weather_domain ∈ {forest_fire_risk, forest_landslide_risk}` — `docs/weather-feature-normalization.md` §3.
