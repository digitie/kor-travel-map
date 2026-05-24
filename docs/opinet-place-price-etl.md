# opinet-place-price-etl.md — OpiNet 주유소 → place + price ETL

본 문서는 OpiNet의 주유소/충전소 데이터를 장소(`place`)와 가격 시계열
(`PricePoint` + `PriceValue`)로 분리 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-opinet-api` |
| dataset_key | `opinet_fuel_station_details` |
| Feature.kind | `place` + `PricePoint` + `PriceValue` |
| source_entity_type | `fuel_station` |
| 상세 테이블 | `feature_place_details`, `price_points`, `price_values` |
| 코드 entrypoint | `krtour.map.providers.opinet`, `krtour.map.opinet` |
| place 갱신 주기 | 월 1회 또는 OpiNet 분기 갱신 |
| price 갱신 주기 | 일 3회 (`0 6,14,22 * * *`) |

## 2. 범위 / 책임

- `python-opinet-api`: OpiNet REST 호출, typed model (`StationDetail`,
  `StationPrice`), pagination, KATEC (EPSG:5181) 좌표 처리.
- `python-krtour-map`: typed model → `Feature(kind=place)` + `PlaceDetail` +
  `PricePoint` + `PriceValue`, DB 적재.
- TripMate: Dagster, schedule, OpiNet 분당 60회 쿼터 보호 (max_concurrent=1).

## 3. 변환 계약

```python
from krtour.map.providers.opinet import station_detail_to_bundle

bundle: OpinetStationFeatureBundle = station_detail_to_bundle(
    detail,                          # python-opinet-api StationDetail
    collected_at=kst_now(),
)
# bundle.feature: Feature(kind=place)
# bundle.detail:  PlaceDetail(phones, facility_info, place_kind="fuel_station")
# bundle.price_point: PricePoint(price_category="fuel", retention_days=3650)
# bundle.price_values: list[PriceValue]  # 제품별
# bundle.source_record + source_link
```

## 4. 주소·좌표

- 좌표: OpiNet 응답은 KATEC (EPSG:5181). `python-opinet-api`가 WGS84 변환 결과를
  `PlaceCoordinate(lat, lon)`로 제공.
- 주소: `address_road` (도로명) + `address_jibun` (지번) → `kraddr.base.Address`.
- **OpiNet `sigun_code`는 OpiNet 자체 코드** — 법정동코드 X. raw/payload만.
- reverse geocoder **필수** — 정확한 `legal_dong_code` 확정.

## 5. PriceValue

```python
PriceValue(
    feature_id=feature_id,
    item_key="gasoline",                  # gasoline / diesel / lpg / premium_gasoline / kerosene
    observed_at=trade_datetime,           # trade_date + trade_time, KST aware
    value=Decimal("1690.00"),
    currency="KRW",
    payload_hash=make_payload_hash(raw),
)
```

`trade_datetime()`이 없으면 `trade_date + trade_time` 조합. timezone naive면
KST 가정 (`docs/feature-opening-hours.md` 패턴).

## 6. PricePoint

```python
PricePoint(
    feature_id=feature_id,
    price_category="fuel",
    retention_days=3650,                  # 10년 (ADR-017)
)
```

장소(feature) 적재 시 1회 생성. 가격 적재마다 별도 생성 X.

## 7. PlaceDetail.facility_info

OpiNet 시설 정보:

```python
{
    "self_service": True,                 # 셀프 주유 여부
    "car_wash": True,
    "convenience_store": False,
    "maintenance": True,                  # 정비
    "polaris_card": True,                 # 폴라리스 카드
    "brand": "SK에너지",
    "station_type": "주유소",             # 주유소 / LPG충전소 / 전기충전소
}
```

영업시간 (`business_hours` / `opening_hours`)이 provider 응답에 있으면
`PlaceDetail.business_hours: FeatureOpeningHours`. 원문 문자열은
`payload.raw_business_hours`.

## 8. DB 적재

### 8.1 단일 station

```python
from krtour.map.opinet import load_opinet_station_detail

async def update_one_station(client, async_session, station_no, reverse_geocoder):
    detail = await client.aget_station_detail(station_no)
    result = await load_opinet_station_detail(
        async_session, detail, reverse_geocoder=reverse_geocoder,
    )
    await async_session.commit()
    return result
```

### 8.2 전체 station 적재

`python-opinet-api`의 `aiter_all_stations()` 사용:

```python
async def update_all_stations(client, async_session, reverse_geocoder):
    async for batch in _batched(client.aiter_all_stations(), size=200):
        await load_opinet_station_details(
            async_session, batch, reverse_geocoder=reverse_geocoder,
        )
    await async_session.commit()
```

OpiNet 분당 60회 쿼터 — Dagster `ConcurrencyConfig(opinet_api,
max_concurrent=1)` + provider 라이브러리의 token bucket.

### 8.3 가격 시계열만 갱신 (일 3회)

기존 station feature는 그대로 두고 PriceValue만 적재:

```python
async def refresh_prices(client, async_session):
    """현재 모든 station의 최신 가격만 갱신."""
    async for batch in _batched(client.aiter_all_station_prices(), size=500):
        await load_opinet_price_values(async_session, batch)
    await async_session.commit()
```

PriceValue는 `(feature_id, item_key, observed_at)` PK이므로 같은 시각 적재는
no-op (ON CONFLICT DO NOTHING).

bulk 적재가 30k 파라미터 초과 가능 → `psycopg.copy_*` 사용 (ADR-013).

## 9. Dagster

| 항목 | 값 |
|------|----|
| place asset 이름 | `feature_place_opinet_stations` |
| price asset 이름 | `price_opinet_fuel` |
| JOB_SPEC | `krtour.map.providers.opinet.PLACE_JOB_SPEC` / `PRICE_JOB_SPEC` |
| suggested cron (place) | `0 3 1 * *` (매월 1일 03:00 KST) |
| suggested cron (price) | `0 6,14,22 * * *` (일 3회) |
| group | `features_place` / `features_price` |
| ConcurrencyConfig | `opinet_api: max_concurrent=1` |

## 10. 검증

### 10.1 fixture (≥ 3)

- `station_detail_typical.json` — 정상 (전화/시설/가격 모두)
- `station_detail_no_phone.json` — 전화 없음
- `station_detail_lpg.json` — LPG 충전소 (item_key=lpg만)
- `station_detail_self_service.json` — 셀프 주유
- `station_price_history.json` — PriceValue 시계열 적재 회귀

### 10.2 통합 테스트

- 동일 station 적재 2회 → idempotent (place row 1, price row는 observed_at별 누적).
- KATEC 좌표 → WGS84 변환 정확성 (sample station 5개).
- bulk price 적재 10k 행 → `psycopg.copy_*` 경로 동작.
- BRIN(observed_at) 인덱스 효율 (1년치 데이터 적재 후 EXPLAIN).

## 11. 후속

- 전기 충전소 (전기차) 별도 dataset 검토 — 환경부 무공해차 통합누리집과 매핑.
- LPG 충전소 가격 시계열 (제품 추가).
- 가격 변동 알림 (Slack 등) — TripMate 측 정합성 검사 후속.
