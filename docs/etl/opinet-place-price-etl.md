# opinet-place-price-etl.md — OpiNet 주유소 → place + price ETL

본 문서는 OpiNet의 주유소/충전소 데이터를 장소(`place`)와 가격 표시 anchor
(`price`) + 가격 시계열(`PriceValue`)로 분리 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-opinet-api` |
| dataset_key | `opinet_fuel_station_details` |
| Feature.kind | `place` + `price` + `PriceValue` |
| source_entity_type | `fuel_station` |
| 상세 테이블 | `feature_place_details`, `feature_price_values` |
| 코드 entrypoint | `kortravelmap.providers.opinet` |
| category | **`06020000`** `TRANSPORT_FUEL` (`docs/architecture/category.md` §4) — Tier path: 교통 > 주유소 |
| place_kind | `fuel_station` |
| marker_icon | `fuel` (maki) |
| marker_color | `P-08` (주황) |
| place 갱신 주기 | 월 1회 또는 OpiNet 분기 갱신 |
| price 갱신 주기 | 일 2회 (`18 6,18 * * *`) |

## 2. 범위 / 책임

- `python-opinet-api`: OpiNet REST 호출, typed model (`Station`,
  `StationDetail`, `OilPrice`), KATEC (EPSG:5181) 좌표 처리.
- `kor-travel-map`: typed model → `Feature(kind=place)` + `PlaceDetail` +
  `Feature(kind=price)` + `PriceValue`, DB 적재.
- kor-travel-map Dagster: schedule, OpiNet 분당 60회 쿼터 보호 (max_concurrent=1).

## 3. 변환 계약

```python
from kortravelmap.providers.opinet import (
    station_details_to_price_features_and_values,
    stations_to_price_features_and_values,
    stations_to_bundles,
)

place_bundles = await stations_to_bundles(station_rows, fetched_at=fetched_at)
price_bundles, price_values = await station_details_to_price_features_and_values(
    station_detail_rows, fetched_at=fetched_at
)
low_top_price_bundles, low_top_price_values = await stations_to_price_features_and_values(
    low_top_station_rows, fetched_at=fetched_at
)
```

## 4. 주소·좌표

- 좌표: OpiNet 응답은 KATEC (EPSG:5181). `python-opinet-api`가 WGS84 변환 결과를
  제공하고, 본 라이브러리는 `Coordinate(lon=..., lat=...)`로 저장한다.
- 주소: `address_road` (도로명) + `address_jibun` (지번) → `kortravelmap.dto.Address`.
- **OpiNet `sigun_code`는 OpiNet 자체 코드** — 법정동코드 X. raw/payload만.
- reverse geocoder **필수** — 정확한 `legal_dong_code` 확정.

## 5. PriceValue

```python
PriceValue(
    feature_id=price_feature_id,
    provider="python-opinet-api",
    price_domain="opinet_gas_station",
    product_key="gasoline",              # gasoline / diesel / lpg / premium_gasoline / kerosene
    product_name="휘발유",
    observed_at=trade_datetime,           # trade_date + trade_time, KST aware
    value_number=Decimal("1690.00"),
    unit="KRW/L",
    source_record_key=source_record_key,
    payload=raw,
)
```

`trade_datetime()`이 없으면 `trade_date + trade_time` 조합. timezone naive면
KST 가정 (`docs/architecture/feature-opening-hours.md` 패턴).

## 6. Price anchor feature

가격 feature는 주유소 place feature와 분리한다. admin Feature UI의 `price`
필터는 이 anchor feature를 조회하고, 제품별 값은 `feature.feature_price_values`
에서 읽는다.

- `kind`: `price`
- `category`: `06020000`
- `name`: `{station_name} 유가`
- `parent_feature_id`: 주유소 `place` feature id
- `marker_icon` / `marker_color`: `fuel` / `P-08`

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

단일 station도 운영 경로와 동일하게 provider detail row를
`station_details_to_price_features_and_values([detail], ...)`로 변환한 뒤
`AsyncKorTravelMapClient.load_price_features(...)`에 전달한다.

### 8.2 운영 scope

OpiNet 공개 API에는 전국/지역 단위 전체 주유소 bulk endpoint가 없다. 공개 5종 중
좌표가 있는 주유소 row를 주는 경로는 `aroundAll`(반경 5km 이하),
`lowTop10`(저가 목록), `detailById`(단건)뿐이다.

- `OPINET_SCOPE_MODE=bbox`: 운영자가 지정한 bbox를 `aroundAll` 격자로 덮는다. 시군구 등
  작은 영역용이다. 전국 bbox는 1만 회 이상 호출되어 OpiNet 일일 한도를 넘을 수 있다.
- `OPINET_SCOPE_MODE=poi_cache_target`: 등록된 active cache target 주변만 `aroundAll`
  격자로 덮는다.
- `OPINET_SCOPE_MODE=low_top_area`: 전국 시군구별 `lowTop10`을 휘발유/경유/고급휘발유
  3종으로 호출한다. 운영 API가 `areaCode`/`lowTop10` 빈 응답을 반환하면 같은 3종을
  전국 샘플 그리드의 `aroundAll`로 호출한다. 전체 주유소는 아니지만 전국 분포를
  OpiNet 일일 한도 안에서 제공한다.

OpiNet 분당 60회 쿼터 — Dagster `ConcurrencyConfig(opinet_api,
max_concurrent=1)` + provider 라이브러리의 token bucket.

### 8.3 가격 시계열만 갱신 (일 2회)

기존 station place feature는 그대로 두고 price anchor feature와 PriceValue를 적재한다.
`bbox`/`poi_cache_target`은 `detailById`의 제품별 가격을 쓰고, `low_top_area`는
`lowTop10` 또는 fallback `aroundAll` Station row의 단일 제품 가격을 같은 price anchor에
누적한다.

```python
async def refresh_prices(map_client, settings):
    """현재 모든 station의 최신 가격만 갱신."""
    details = await fetch_opinet_station_price_details(settings)
    if details and hasattr(details[0], "prices"):
        bundles, values = await station_details_to_price_features_and_values(
            details, fetched_at=kst_now()
        )
    else:
        bundles, values = await stations_to_price_features_and_values(
            details, fetched_at=kst_now()
        )
    await map_client.load_price_features(bundles, values)
```

PriceValue는 결정적 `price_value_key`와
`(feature_id, provider, price_domain, product_key, observed_at)` unique key를
함께 쓰므로 같은 시각 적재는 멱등 upsert다.

bulk 적재가 30k 파라미터 초과 가능 → `psycopg.copy_*` 사용 (ADR-013).

## 9. Dagster

| 항목 | 값 |
|------|----|
| place asset 이름 | `feature_place_opinet_stations` |
| price asset 이름 | `feature_price_opinet_stations` |
| JOB_SPEC | Dagster asset/job 정의 |
| suggested cron (place) | `0 3 1 * *` (매월 1일 03:00 KST) |
| suggested cron (price) | `0 6,14,22 * * *` (일 3회) |
| group | `features_place` / `features_price` |
| ConcurrencyConfig | `opinet_api: max_concurrent=1` |

## 10. 검증

### 10.1 fixture (≥ 3)

- `station_detail_typical.json` — 정상 (전화/시설/가격 모두)
- `station_detail_no_phone.json` — 전화 없음
- `station_detail_lpg.json` — LPG 충전소 (`product_key=lpg`만)
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
- 가격 변동 알림 (Slack 등) — PinVi 측 정합성 검사 후속.
