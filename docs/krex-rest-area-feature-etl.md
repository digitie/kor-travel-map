# krex-rest-area-feature-etl.md — 한국도로공사 휴게소 ETL

본 문서는 한국도로공사(`python-krex-api`) 휴게소 데이터 — 위치, 시설, 유가,
기상 — 를 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krex-api` |
| dataset_key | `krex_rest_areas`, `krex_rest_area_prices`, `krex_rest_area_weather`, `krex_traffic_notices` |
| Feature.kind | `place` (휴게소) + `PricePoint`/`PriceValue` (유가) + `WeatherValue` (기상) + `notice` (교통) |
| source_entity_type | `rest_area` |
| 상세 테이블 | `feature_place_details`, `price_*`, `feature_weather_values`, `feature_notice_details` |
| 코드 entrypoint | `krtour.map.providers.krex`, `krtour.map.highways`, `krtour.map.notices` |

## 2. 4가지 sub-ETL

### 2.1 휴게소 place (`krex_rest_areas`)

| 항목 | 값 |
|------|----|
| natural key | 휴게소 ID (provider 제공) |
| FeatureKind | `place` |
| place_kind | `rest_area` |
| category | **`06040101`** `TRANSPORT_REST_AREA_HIGHWAY_EX` (`docs/category.md` §4) — Tier path: 교통 > 휴게소 > 고속도로휴게소 > 한국도로공사 휴게소 |
| marker_icon | `highway-rest-area` (maki) |
| marker_color | `P-15` (주홍) |
| 갱신 주기 | 월 1회 |
| `KREX_REST_AREA_FULL_SCAN_INTERVAL_DAYS` | 30 |

### 2.2 휴게소 유가 (`krex_rest_area_prices`)

| 항목 | 값 |
|------|----|
| 분리 모델 | `PricePoint(price_category="fuel")` + `PriceValue` |
| 갱신 주기 | 일 3회 (`0 6,14,22 * * *`) |
| `KREX_PRICE_RETENTION_DAYS` | 3650 (10년) |

### 2.3 휴게소 기상 (`krex_rest_area_weather`)

| 항목 | 값 |
|------|----|
| 분리 모델 | `WeatherValue` |
| weather_domain | `rest_area_weather` |
| forecast_style | `observed` |
| timeline_bucket | `ultra_short` |
| 갱신 주기 | 시간 (`0 * * * *`) |

### 2.4 교통 공지 (`krex_traffic_notices`)

→ `docs/notice-feature-etl.md`로 별도 분리.

## 3. 휴게소 place 매핑

provider 응답 → DTO:

```python
def krex_rest_area_to_bundle(item, *, fetched_at, reverse_geocoder=None):
    return FeatureBundle(
        feature=Feature(
            feature_id=make_feature_id(
                bjd_code=None,  # reverse geocoder가 보강
                kind=FeatureKind.PLACE,
                category="TRANSPORT_REST_AREA",
                source_type="rest_area",
                source_natural_key=item.rest_area_id,
            ),
            kind=FeatureKind.PLACE,
            name=item.name,
            coord=PlaceCoordinate(lat=item.lat, lon=item.lon),
            address=Address(display_address=item.address),
            category="TRANSPORT_REST_AREA",
            marker_icon="car",
            marker_color="P-15",
            detail=PlaceDetail(
                feature_id=...,
                place_kind="rest_area",
                phones=[item.tel] if item.tel else [],
                business_hours=_parse_business_hours(item.business_hours),
                facility_info={
                    "highway_name": item.highway_name,        # 예: "경부선"
                    "direction": item.direction,              # 상행 / 하행
                    "amenities": item.amenities,              # 리스트
                    "ev_charger": item.has_ev_charger,
                    "fuel_station": item.has_fuel,
                    "restaurant_count": item.restaurant_count,
                },
            ),
            ...
        ),
        ...
    )
```

## 4. 유가 적재

```python
from krtour.map.highways import collect_krex_rest_area_prices

async def refresh_rest_area_prices(client, async_session):
    items = await client.aget_all_rest_area_prices()
    values = collect_krex_rest_area_prices(items, observed_at=kst_now())
    
    # PricePoint는 휴게소 place 적재 시 한 번 생성, 여기서는 PriceValue만
    await upsert_price_values(async_session, values)
    await async_session.commit()
```

`PriceValue.item_key`: `gasoline` / `diesel` / `lpg` / `premium_gasoline` /
`kerosene`.

## 5. 기상 적재

```python
from krtour.map.highways import collect_krex_rest_area_weather_values

async def refresh_rest_area_weather(client, async_session, feature_id_by_rest_area):
    items = await client.aget_all_rest_area_weather()
    values = list(collect_krex_rest_area_weather_values(
        items, feature_id_by_rest_area_id=feature_id_by_rest_area,
    ))
    await upsert_weather_values(async_session, values)
    await async_session.commit()
```

매핑은 `feature_id_by_rest_area_id` dict — 미리 휴게소 place 적재해 둠.

## 6. Dagster

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `feature_place_krex_rest_areas` | `krex_rest_areas` | `0 2 1 * *` (월) | `features_place` |
| `price_krex_rest_area_fuel` | `krex_rest_area_prices` | `0 6,14,22 * * *` (일 3회) | `features_price` |
| `weather_krex_rest_area` | `krex_rest_area_weather` | `0 * * * *` (시간) | `features_weather` |

ConcurrencyConfig: `krex_api: max_concurrent=1`.

## 7. 검증

### fixture (≥ 3)

- `rest_area_typical.json` — 정상 (시설/전화/이미지)
- `rest_area_no_fuel.json` — 유류 없는 휴게소
- `rest_area_with_ev_charger.json` — 전기충전소 포함
- `rest_area_fuel_price_typical.json` — 유가 시계열
- `rest_area_weather_typical.json` — 기상 (T1H, REH, WSD)

### 통합 테스트

- 휴게소 적재 → PricePoint 동시 생성
- 유가 적재 idempotent (`(feature_id, item_key, observed_at)` PK)
- BRIN(observed_at) 효율

## 8. 후속

- 영업 시간 구조화 (`business_hours` 자유 텍스트 → `FeatureOpeningHours`).
- 휴게소 음식점 → POI 도메인 연계 (TripMate 책임).
- 휴게소 주차 가능 대수 → `facility_info` 추가.
- 교통 공지는 `docs/notice-feature-etl.md`.
