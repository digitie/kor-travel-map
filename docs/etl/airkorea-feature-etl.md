# airkorea-feature-etl.md — AirKorea 대기질 측정소/측정값 ETL

본 문서는 AirKorea(`python-airkorea-api`)의 대기질 데이터를 두 갈래로 적재하는
ETL이다 — **측정소(station)는 `weather`-kind `Feature`**, **측정값(measurement)은
오염물질별 `WeatherValue`**. 측정값은 장소가 아니라 관측값이므로(ADR-010) 측정소를
weather-kind anchor로 만들고 값을 그 anchor에 붙인다. 표준 metric_key / 단위 매핑은
`docs/etl/weather-feature-normalization.md`가 정답.

코드 정본: `src/kortravelmap/providers/airkorea.py`.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-airkorea-api` (`AIRKOREA_PROVIDER_NAME`) |
| dataset_key (측정소) | `airkorea_stations` (`DATASET_KEY_STATIONS`) |
| dataset_key (측정값) | `airkorea_air_quality` (`DATASET_KEY_AIR_QUALITY`) |
| Feature.kind | `weather` (측정소 anchor) → 값은 `WeatherValue` |
| source_entity_type | `air_quality_station` |
| category | **`99000000`** sentinel (`AIR_QUALITY_STATION_CATEGORY`) — weather-kind는 detail이 없어 category가 부차적이라 KMA 특보와 동일한 placeholder를 쓴다(ADR-018) |
| marker_icon | `marker` — `99000000`은 maki 카탈로그에 없어 `mapbox_maki_icon_or_none`이 None을 반환, `_DEFAULT_STATION_ICON` fallback |
| marker_color | `P-16` (`AIR_QUALITY_MARKER_COLOR`) |
| weather_domain | `air_quality` (`WeatherDomain.AIR_QUALITY`) |
| forecast_style | `observed` (`ForecastStyle.OBSERVED`) |
| normalization_version | `airkorea-v1.0` (`AIRKOREA_NORMALIZATION_VERSION`) |
| 코드 entrypoint | `kortravelmap.providers.airkorea` |
| 갱신 주기 | 측정소(정적) 월 1회 / 측정값(시간별 관측) 1시간 1회 |

## 2. 범위 / 책임

- `python-airkorea-api` (`import airkorea`): REST 호출, typed model
  (`Station`, `AirQualityMeasurement`), pagination.
- `kor-travel-map`: typed model → 측정소 `Feature(kind=weather)` +
  오염물질별 `WeatherValue` 적재.
- kor-travel-map Dagster: schedule.

## 3. 측정소 변환 (weather anchor)

```python
from kortravelmap.providers.airkorea import air_quality_stations_to_bundles

bundles = await air_quality_stations_to_bundles(
    stations,                        # AirQualityStationItem Protocol iterable
    fetched_at=kst_now(),
    reverse_geocoder=reverse_geocoder,
)
# bundle.feature: Feature(kind=weather, category="99000000", detail=None)
# bundle.source_record + source_link
```

좌표는 station `lat`/`lon`(WGS84 float). `detail`은 None — weather-kind는
`PlaceDetail`/`NoticeDetail`을 가질 수 없다(ADR-018).

## 4. 필드 매핑 (측정소)

| provider 필드 | DTO 저장 위치 |
|--------------|--------------|
| `station_name` | `Feature.name` (`normalize_korean_text`), natural key 구성 |
| `addr` | `Address.admin` fallback + 시도 추출(composite key) |
| `lat`, `lon` | `Feature.coord` (WGS84 → `Decimal`) |
| 전체 row | `source_records.raw_data` (`station_name`/`sido`/`addr`/`latitude`/`longitude`) |

## 5. 측정값 변환 (WeatherValue)

한 측정 row에 오염물질이 컬럼으로 들어있다. 변환 시 오염물질당 `WeatherValue`
1행으로 펼친다(결측 오염물질 row는 생성하지 않음).

```python
from kortravelmap.providers.airkorea import air_quality_to_weather_values

values = air_quality_to_weather_values(
    measurements,                    # AirQualityMeasurementItem Protocol iterable
    station_feature_ids=station_feature_ids,   # composite key → weather feature_id
    source_record_key=source_record_key,
)
```

`AIRKOREA_POLLUTANTS` 매핑 (`metric_key` / 단위 / metric_name):

| metric_key | provider value 필드 | 단위 | metric_name |
|-----------|--------------------|------|-------------|
| `PM10` | `pm10_value` | `μg/m³` | 미세먼지(PM10) |
| `PM2_5` | `pm25_value` | `μg/m³` | 초미세먼지(PM2.5) |
| `O3` | `o3_value` | `ppm` | 오존 |
| `NO2` | `no2_value` | `ppm` | 이산화질소 |
| `SO2` | `so2_value` | `ppm` | 아황산가스 |
| `CO` | `co_value` | `ppm` | 일산화탄소 |
| `CAI` | `khai_value` | `score` | 통합대기환경지수 |

- `*_grade`(1~4)는 `severity` 라벨로 매핑: 1=좋음 / 2=보통 / 3=나쁨 / 4=매우나쁨.
- `data_time`은 관측 시각 → `observed_at`(naive면 KST 부여, ADR-019).
- `weather_domain=air_quality`, `forecast_style=observed`, `timeline_bucket=None`.

## 6. natural key / 조인

측정소명(`station_name`)은 전국에서 유일하지 않다(예: `중구`가 여러 시도에 존재).
안정키는 **composite** `station_name::<sido>`다(ADR-009 derived-key separator `::`,
`|` 예약 회피). 측정소는 `addr` 첫 토큰에서, 측정값은 `sido_name`에서 같은 canonical
약식 시도를 만들어 매핑한다(`_canonical_sido`). 매핑(`station_feature_ids`)에 없는
측정값 row는 건너뛴다(#300 — 다른 지역 feature에 값이 잘못 붙는 것 방지).

```text
source_entity_id = "<station_name>::<canonical_sido>"   # 예: "중구::서울"
```

## 7. feature_id 안정성 (F-01 caveat)

`make_feature_id`는 `bjd_code` + `category`를 식별자에 embed한다. 측정소 변환은
**`bjd_code`를 station 좌표의 reverse geocoding으로 늦게 얻는다** — `reverse_geocoder`는
optional(Dagster resource 기본 None)이라 geocoder 유무·출력 변동 시 같은 측정소가
`f_global_…`↔`f_<bjd>_…`로 갈려 재import 시 중복(soft-delete-old + new-feature)이
날 수 있다. 즉 feature_id는 **geocoder-conditional**(조건부 결정성)이다. 이는
geocoder 의존 ~10 provider 공통 결함 class이며, ADR-057이 concierge에 적용한
anchoring(stable source key + 고정 identity category, bjd는 가변 속성)을 어느 provider에
확대할지는 backlog 결정이다.

상세: `docs/reports/full-consistency-audit-2026-06-16.md` §3 F-01 +
`docs/architecture/provider-contract.md` §6.

## 8. 후속

- 측정소 anchor를 인근 place feature와 `sibling_group_id`로 묶는 전략(KMA 격자와 동일).
- 대기질 예보(`getMinuDustFrcstDspth`) → forecast_style 분기.
- 측정소 feature에 ADR-057 anchoring 적용 시 F-01 비멱등 해소(backlog).
