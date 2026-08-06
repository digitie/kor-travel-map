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
| 상세 테이블 | `feature_places`, `feature_price_values` |
| 코드 entrypoint | `kortravelmap.providers.opinet` |
| category | **`06020000`** `TRANSPORT_FUEL` (`docs/architecture/category.md` §4) — Tier path: 교통 > 주유소 |
| place_kind | `fuel_station` |
| marker_icon | `fuel` (maki) |
| marker_color | `P-08` (주황) |
| place 갱신 주기 | 월 1회 또는 OpiNet 분기 갱신 |
| price 갱신 주기 | 일 1회 (`18 18 * * *`, #545 quota guard) |

## 2. 범위 / 책임

- `python-opinet-api`: OpiNet REST 호출, typed model (`Station`,
  `StationDetail`, `OilPrice`), KATEC (EPSG:5181) 좌표 처리.
- `kor-travel-map`: typed model → `Feature(kind=place)` + `PlaceDetail` +
  `Feature(kind=price)` + `PriceValue`, DB 적재.
- kor-travel-map Dagster: schedule, run당 호출 예산, OpiNet asset 직렬 실행
  (`opinet_api` pool, instance 전역 `max_concurrent=1`).

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
  주요 도심 anchor와 전국 샘플 그리드의 `aroundAll`로 호출한다. 전체 주유소는 아니지만
  전국 분포를 OpiNet 일일 한도 안에서 제공한다. `lowTop10`이 분포 임계치
  (`_OPINET_LOW_TOP_FALLBACK_MIN_STATIONS`) 이상을 산출하면 grid fallback은
  건너뛴다(#545).

시군 윈도 로테이션 (staleness 근본 수정):

- `lowTop10` 호출 상한(기본 180 = 시군 60개 윈도/run)이 전국 ~230 시군을 한 run에
  다 덮지 못하는데, 이전에는 시군 목록 앞쪽 윈도만 매일 소비해 **같은 ~60개 시군의
  top-20 저가 주유소만 갱신**됐다 — 한 번 dataset에 들어온 뒤 윈도/top-20 밖으로
  밀린 주유소는 영구 stale(prod 실측: price feature 37%가 3–7일 stale, 일간 동일
  주유소 겹침 93%, 사용 호출 ~198/1,500).
- 이제 run 날짜(KST) 기반 결정적 offset(`_opinet_rotation_offset`, `toordinal() ×
  윈도 크기`)으로 시군 목록을 회전시켜 매일 윈도 크기만큼 전진한다 → 전국 1주기
  ≈ ceil(230/60) = **4일**, 호출량은 그대로(~198/run). round-robin 인접 시군은 서로
  다른 시도라 윈도 안 지리 분포 공정성도 유지된다.
- 이 4일은 **시군 조회 윈도**의 1주기이지, 저장된 모든 주유소 가격의 갱신 보장이
  아니다. `lowTop10`의 유종별 top-20 밖으로 밀린 기존 주유소는 다시 응답될 때까지
  더 오래된 값이 남을 수 있다. 일일 quota 안에서 전체 known station을 `detailById`로
  매일 갱신할 수 없으므로, 지도는 관측 날짜를 숨기지 않고 아래처럼 과거로 표시한다.
  stale-first `detailById` 보강은 별도 quota/주기 설계 없이는 이 계약에 포함하지 않는다.
- 표시 계층 정합: price card의 `current`는 로테이션 주기보다 오래된 관측을 숨긴다
  (`KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS`, 기본 4일; 이력은 보존). 지도 API는 갱신
  장애를 은폐하지 않도록 오래된 `price_summary`도 `observed_at`과 함께 반환하며,
  admin 지도 마커는 오늘(KST)이 아닌 OpiNet 유종마다 `과거 M/D`를 표시한다.

OpiNet 쿼터 가드(#545):

- 동시 실행 1개 — place/price asset 모두 Dagster `opinet_api` pool을 선언하고,
  `docker/dagster.yaml`의 `concurrency.pools.default_limit=1`, `granularity=run`이
  schedule·수동 materialize를 포함해 instance 전역에서 직렬화한다. 이전 문서의
  `ConcurrencyConfig` 표기는 실제 설정이 아니었다.
- pool을 거치지 않고 같은 `run_feature_*` 함수를 직접 호출하는 targeted feature update
  worker까지 포함하도록, 두 실행 함수는 fetch 시작 전부터 sync 성공 기록까지 공통
  PostgreSQL session advisory lock(`provider-run:python-opinet-api`)을 잡는다. pool은
  불필요한 run 시작·DB lock 대기를 줄이는 1차 제어이고, DB lock이 process/실행 경로를
  가로지르는 최종 상호 배제 경계다. process/connection 종료 시 lock은 자동 해제된다.
- OpiNet `low_top_area`는 update request의 feature/bbox/cache-target scope를 직접 적용하지
  못하고 설정된 전국 회전 window를 다시 조회한다. 따라서 `provider_dataset`이 아닌 targeted
  request에서는 OpiNet place/price를 API fetch 전에
  `skipped(global_provider_not_targetable)`로 기록하고 system schedule에 맡긴다. 이를 허용하면
  서로 다른 target request가 같은 전국 조회를 반복해 무료키 일일 quota를 소진한다.
- schedule 또는 명시적 provider-wide 실행도 DB lock 안에서 persisted sync state를 확인한다.
  같은 dataset의 성공 cursor `loaded_at`과 현재 run 시작이 KST 당일이면 provider fetch를
  한 번으로 합친다(DB commit 시각 `last_success_at`은 자정 통과 run에서 쓰지 않는다). 단 price는 그
  성공 cursor의 `today_values_count == price_values_upserted > 0`, 즉 적재값 전체가 당일
  관측이고 `latest_observed_at`도 같은 KST 날짜일 때만 합친다. 오전 수동 실행이 전일/혼합
  가격을 받아도 저녁 정식 schedule을 막지 않으며, 실패 run은 성공 시각을 전진시키지 않아
  재시도할 수 있다.
- 분당 60회 — `python-opinet-api`(`bb6385c` 확인)는 token bucket을 제공하지 않고
  README에서 rate-limit을 호출자 책임으로 둔다. transport의 sleep은 5xx/network retry
  backoff일 뿐 요청 pacing이 아니다. 따라서 현재 보호선은 **동시 run 직렬화 + run당
  hard budget + 서버 `OpinetRateLimitError` 즉시 run 실패**다. provider에 실제 limiter가
  추가되기 전까지 token bucket이 있다고 가정하지 않는다.
- 일일 1,500회 — `low_top_area` fetcher가 run당 hard call budget
  (`KOR_TRAVEL_MAP_OPINET_RUN_CALL_BUDGET`, 기본 600, 최대 700,
  `get_area_codes`+`lowTop10`+
  `aroundAll` 합산)을 적용한다. 서버가 먼저 `OpinetRateLimitError`를 던지면 일부 record를
  이미 받았어도 run을 실패시켜 sync 성공으로 오인하지 않는다. 가격 적재는 일 1회로
  낮춰 월간 place job과 같은 날 겹쳐도 한도 아래를 유지한다.
- 가격 asset의 enabled scope 전체 raw 결과가 0건이거나, raw record는 있어도 변환된
  `PriceValue`가 0건이면 load/sync 성공을 기록하지 않고 실패한다. 후자는 provider 응답
  스키마 drift나 가격 필드 누락으로 갱신이 멈췄는데 성공 cursor만 전진하는 반복 장애를
  막는다. 개별 시군·유종의 정상 no-data는 계속 허용한다. 성공 cursor와 Dagster materialize
  metadata에는 `records_fetched`, `coverage=configured_scope|rotating_partial`,
  `latest_observed_at`, `today_values_count`를 기록한다. `today_values_count`는 asset의
  `fetched_at`과 각 `PriceValue.observed_at`을 모두 KST 날짜로 바꿔 계산하므로, run 성공과
  별개로 실제 당일 유가가 들어왔는지 운영에서 판별할 수 있다.
- 운영 노브: `KOR_TRAVEL_MAP_OPINET_LOW_TOP_MAX_CALLS`(기본 180)는 반드시 run budget에서
  시도 코드 조회 호출량을 뺀 범위 안에서만 늘린다. 무료키 한도에 대한 안전 여유를 지키기
  위해 `KOR_TRAVEL_MAP_OPINET_RUN_CALL_BUDGET`은 최대 700으로 검증하며, place/price가 같은
  날 각각 한 번 실행돼도 합계 1,400회 이하가 된다. 기본값은 `max_calls=180`,
  `run_call_budget=600`이다.

### 8.3 가격 시계열만 갱신 (일 1회)

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
| cron (place) | `5 3 1 * *` (매월 1일 03:05 KST) |
| cron (price) | `18 18 * * *` (매일 18:18 KST) |
| group | `features_place` / `features_price` |
| 실행 직렬화 | `opinet_api` Dagster pool + `provider-run:python-opinet-api` DB advisory lock |

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
