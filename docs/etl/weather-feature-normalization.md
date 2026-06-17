# weather-feature-normalization.md — weather 정규화

본 문서는 여러 provider의 날씨/대기/지수 데이터를 KMA 시간축 기준 단일
`WeatherValue` + `feature_weather_values` table로 정규화하는 규약이다. TripMate는
별도 weather DB를 만들지 않고 이 계약을 그대로 사용한다.

## 1. 두 축의 분리 (ADR-010)

| 축 | 컬럼 | 의미 |
|----|------|------|
| 성격 | `forecast_style` | 원천값의 본질 (관측/예보/지수/특보) |
| 조회 | `timeline_bucket` | KMA식 조회 시간축 (분류 결과) |

두 축은 직교. 한 컬럼에 합치면 조회 복잡도 폭발.

### 1.1 `forecast_style` (원천값 성격)

| value | 의미 |
|-------|------|
| `nowcast` | KMA 초단기실황 (관측 기반, 최근 1시간) |
| `ultra_short` | KMA 초단기예보 (6시간 이내) |
| `short` | KMA 단기예보 (당일~3일) / 당일 지수 |
| `mid` | KMA 중기예보 (3~10일) |
| `observed` | 휴게소/산악기상/공항/공공기상 등 현재 관측 |
| `index` | 지수성 (산불위험, 산사태위험, 해양지수) |
| `advisory` | 특보/경보 |

**규칙**: 관측을 예보로 가공하지 않는다 (반대도 동일). provider 원천 성격 보존.

### 1.2 `timeline_bucket` (조회 축)

| value | 의미 |
|-------|------|
| `ultra_short` | 현재/관측, 초단기실황, 0-6시간 context |
| `short` | 당일/익일 단기예보, 당일 지수 |
| `mid` | 3-10일 중기예보 |

`null` 허용 (지수/특보 등 시간축 모호한 경우).

**중요**: `timeline_bucket`은 unique key에 포함되지 **않는다**. 분류 결과이므로
재계산 가능.

## 2. 표준 `metric_key` (KMA 카테고리 우선)

| metric_key | 의미 | unit |
|-----------|------|------|
| `T1H` | 초단기실황 기온 | deg_c |
| `TMP` | 예보 기온 | deg_c |
| `REH` | 상대습도 | % |
| `WSD` | 풍속 | m/s |
| `VEC` | 풍향 | deg |
| `RN1` | 1시간 강수량 | mm |
| `PTY` | 강수형태 | code (0 없음, 1 비, 2 비/눈, 3 눈, ...) |
| `SKY` | 하늘상태 | code (1 맑음, 3 구름많음, 4 흐림) |
| `POP` | 강수확률 | % |
| `PCP` | 1시간 강수량 (예보) | mm |
| `SNO` | 1시간 적설 | cm |
| `WAV` | 파고 | m |
| `UUU` | 동서바람성분 | m/s |
| `VVV` | 남북바람성분 | m/s |
| `T3H` | 3시간 기온 | deg_c |
| `TMN` | 일 최저기온 | deg_c |
| `TMX` | 일 최고기온 | deg_c |
| `WSDM` | 평균 풍속 | m/s |
| `FIRE_RISK` | 산불위험지수 | score 0-100 |
| `LANDSLIDE_RISK` | 산사태위험지수 | score 0-100 |
| `PM10` | 미세먼지 농도 | μg/m³ |
| `PM2_5` | 초미세먼지 농도 | μg/m³ |
| `O3` | 오존 농도 | ppm |
| `NO2` | 이산화질소 농도 | ppm |
| `SO2` | 아황산가스 농도 | ppm |
| `CO` | 일산화탄소 농도 | ppm |
| `CAI` | 통합대기환경지수 | code 1-5 |
| `WATER_TEMP` | 수온 | deg_c |
| `TIDE_LEVEL` | 조위 | cm |

표준에 없는 provider 고유 지표는 `source_metric_key`에 원문 유지하고 새
`metric_key`를 도입할 때 ADR + 본 문서 갱신.

## 3. provider별 1차 매핑

| provider | weather_domain | forecast_style | timeline_bucket | 비고 |
|----------|----------------|----------------|----------------|------|
| `python-kma-api` | `kma_ultra_short_nowcast` | `nowcast` | `ultra_short` | 초단기실황 |
| `python-kma-api` | `kma_ultra_short_forecast` | `ultra_short` | `ultra_short` | 초단기예보 |
| `python-kma-api` | `kma_short_forecast` | `short` | `short` | 단기예보 (3시간 단위) |
| `python-kma-api` | `kma_mid_forecast` | `mid` | `mid` | 중기예보 (일 2회) |
| `python-kma-api` | `kma_weather_alert` | `advisory` | null | 특보 (notice로도 별도 변환) |
| `python-krforest-api` | `forest_mountain_weather` | `observed` | `ultra_short` | 산악 관측 |
| `python-krforest-api` | `forest_fire_risk` | `index` | `short` | 산불위험 |
| `python-krforest-api` | `forest_landslide_risk` | `advisory` | `short` | 산사태 (지수 + 위험등급) |
| `python-krex-api` | `rest_area_weather` | `observed` | `ultra_short` | 휴게소 관측 |
| `python-krairport-api` | `airport_weather` | `observed` | `ultra_short` | 공항 관측 |
| `python-khoa-api` | `beach_marine` | `index` | `short` | 해수욕장 해양지수 |
| `python-khoa-api` | `coastal_observation` | `observed` | `ultra_short` | 조위/수온/기상 관측 |
| `python-airkorea-api` | `air_quality` | `observed` | `ultra_short` | PM10/PM2.5/CAI |
| 농촌진흥청 (data.go.kr) | `agri_weather` | `observed` | `ultra_short` | 농업기상 관측소 |
| 한국수자원공사 (data.go.kr) | `hydro_weather` | `observed` | `ultra_short` | 수문기상 |

## 4. `WeatherValue` DTO

```python
class WeatherValue(BaseModel):
    feature_id: str
    provider: str
    weather_domain: WeatherDomain
    forecast_style: ForecastStyle
    timeline_bucket: TimelineBucket | None = None
    metric_key: str                        # 표준 metric_key (T1H, TMP, ...)
    
    # 시간축
    issued_at: datetime | None = None      # 예보 발표 시각
    valid_at: datetime | None = None       # 예보 유효 시점 (단일 시각)
    valid_from: datetime | None = None     # 예보 유효 시작 (구간형)
    valid_until: datetime | None = None    # 예보 유효 종료
    observed_at: datetime | None = None    # 관측 시각
    
    # provider 원문 보존
    source_metric_key: str | None = None
    source_metric_name: str | None = None
    metric_name: str | None = None         # 표준 한글 이름 (예: "현재 기온")
    
    # 값
    value_number: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None
    severity: str | None = None            # 특보/지수 등급
    
    normalization_version: str | None = None  # 정규화 규약 버전
    payload: dict = Field(default_factory=dict)   # provider raw
    collected_at: datetime = Field(default_factory=kst_now)
    source_record_key: str | None = None
    
    def identity(self) -> tuple:
        return (self.feature_id, self.provider, self.weather_domain.value,
                self.forecast_style.value, self.metric_key,
                self.issued_at, self.valid_at, self.observed_at)
```

`identity()`가 unique key (`timeline_bucket` 제외).

## 5. DB 매핑

`feature.feature_weather_values`:

```sql
CREATE TABLE feature.feature_weather_values (
  weather_value_key       TEXT PRIMARY KEY,           -- make_weather_value_key(value)
  feature_id              TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider                TEXT NOT NULL,
  weather_domain          TEXT NOT NULL,
  forecast_style          TEXT NOT NULL,
  timeline_bucket         TEXT,
  metric_key              TEXT NOT NULL,
  source_metric_key       TEXT,
  source_metric_name      TEXT,
  metric_name             TEXT,
  issued_at               TIMESTAMPTZ,
  valid_at                TIMESTAMPTZ,
  valid_from              TIMESTAMPTZ,
  valid_until             TIMESTAMPTZ,
  observed_at             TIMESTAMPTZ,
  value_number            NUMERIC(14,4),
  value_text              TEXT,
  unit                    TEXT,
  severity                TEXT,
  normalization_version   TEXT,
  source_record_key       TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  collected_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_weather_values UNIQUE (
    feature_id, provider, weather_domain, forecast_style,
    metric_key, issued_at, valid_at, observed_at
  )
);
```

인덱스: `(feature_id, metric_key, valid_at DESC NULLS LAST)`,
`(provider, weather_domain, valid_at DESC NULLS LAST)`,
`BRIN(valid_at)`, `BRIN(collected_at)`.

## 6. `build_weather_card` helper

frontend가 한 번에 받는 통합 응답:

```python
async def build_weather_card(
    client: AsyncKorTravelMapClient,
    feature_id: str,
    *,
    asof: datetime | None = None,
) -> WeatherCard:
    """KMA timeline + 부가 source 통합 view."""
    asof = asof or kst_now()
    rows = await client.list_weather_values_for_card(feature_id, asof=asof)
    return WeatherCard(
        feature_id=feature_id,
        asof=asof,
        nowcast=_pick_nowcast(rows),                 # 가장 최근 관측
        ultra_short=_pick_timeline(rows, "ultra_short"),
        short=_pick_timeline(rows, "short"),
        mid=_pick_timeline(rows, "mid"),
        sources=_extra_sources(rows),                # 같은 valid_at의 다른 provider
    )
```

`WeatherCard`:
```python
class WeatherCard(BaseModel):
    feature_id: str
    asof: datetime
    nowcast: dict[str, WeatherValue] | None       # metric_key → 최신값
    ultra_short: list[WeatherTimelineEntry]       # 시간순
    short: list[WeatherTimelineEntry]
    mid: list[WeatherTimelineEntry]
    sources: list[WeatherSourceEntry]             # 부가 provider 그대로
```

## 7. provider별 변환 패턴

### 7.1 KMA 단기예보

```python
# providers/kma.py
async def short_forecast_to_weather_values(
    items: Iterable[KmaShortForecastItem],
    *,
    feature_id: str,
    fetched_at: datetime,
) -> Iterator[WeatherValue]:
    for item in items:
        # KMA category code → metric_key (이미 표준에 가까움)
        metric_key = item.category                    # T1H, TMP, REH, ...
        if metric_key not in STANDARD_METRIC_KEYS:
            continue                                   # 미지원 metric은 skip
        
        valid_at = _kma_valid_at(item.fcst_date, item.fcst_time)
        issued_at = _kma_issued_at(item.base_date, item.base_time)
        
        yield WeatherValue(
            feature_id=feature_id,
            provider="python-kma-api",
            weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
            forecast_style=ForecastStyle.SHORT,
            timeline_bucket=TimelineBucket.SHORT,
            metric_key=metric_key,
            source_metric_key=item.category,
            source_metric_name=KMA_METRIC_NAMES.get(item.category),
            metric_name=STANDARD_METRIC_NAMES.get(metric_key),
            issued_at=issued_at,
            valid_at=valid_at,
            value_number=_to_decimal(item.fcst_value),
            unit=STANDARD_METRIC_UNITS.get(metric_key),
            normalization_version="weather-feature-v1",
            payload=item.model_dump(mode="json"),
        )
```

### 7.2 산림청 산악기상 (observed)

```python
async def mountain_weather_to_values(
    items: Iterable[MountainWeatherItem],
    *,
    feature_id_by_obs_id: dict[str, str],
    fetched_at: datetime,
) -> Iterator[WeatherValue]:
    for item in items:
        feature_id = feature_id_by_obs_id.get(item.obs_id)
        if not feature_id:
            continue                                   # 매칭 안 된 관측소 skip
        
        observed_at = item.tm                          # 관측 시각
        common = dict(
            feature_id=feature_id,
            provider="python-krforest-api",
            weather_domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
            forecast_style=ForecastStyle.OBSERVED,
            timeline_bucket=TimelineBucket.ULTRA_SHORT,
            observed_at=observed_at,
            normalization_version="weather-feature-v1",
            payload=item.model_dump(mode="json"),
        )
        
        if item.temperature is not None:
            yield WeatherValue(**common, metric_key="T1H",
                                value_number=item.temperature, unit="deg_c")
        if item.humidity is not None:
            yield WeatherValue(**common, metric_key="REH",
                                value_number=item.humidity, unit="%")
        if item.wind_speed is not None:
            yield WeatherValue(**common, metric_key="WSD",
                                value_number=item.wind_speed, unit="m/s")
        # ... 등
```

### 7.3 AirKorea (대기질)

```python
async def airkorea_to_values(items, *, feature_id_by_station, fetched_at):
    for item in items:
        feature_id = feature_id_by_station.get(item.station_name)
        if not feature_id:
            continue
        
        observed_at = item.data_time
        common = dict(
            feature_id=feature_id,
            provider="python-airkorea-api",
            weather_domain=WeatherDomain.AIR_QUALITY,
            forecast_style=ForecastStyle.OBSERVED,
            timeline_bucket=TimelineBucket.ULTRA_SHORT,
            observed_at=observed_at,
            normalization_version="weather-feature-v1",
            payload=item.model_dump(mode="json"),
        )
        
        for metric_key, value, unit in [
            ("PM10", item.pm10_value, "μg/m³"),
            ("PM2_5", item.pm25_value, "μg/m³"),
            ("O3", item.o3_value, "ppm"),
            ("NO2", item.no2_value, "ppm"),
            ("CAI", item.khai_value, "code"),
        ]:
            if value is not None:
                yield WeatherValue(**common, metric_key=metric_key,
                                    value_number=value, unit=unit)
```

## 8. 시간 처리

- `issued_at`: 예보가 발표된 시각 (KMA 단기예보는 base_date + base_time)
- `valid_at`: 예보가 유효한 단일 시각 (KMA 단기는 fcst_date + fcst_time)
- `valid_from`/`valid_until`: 구간 예보 (특보, 지수)
- `observed_at`: 관측값 시각
- 모두 KST aware (ADR-019). naive datetime 입력은 ValidationError.

## 9. 적재 패턴

```python
# infra/weather_repo.py
async def upsert_weather_values(
    session: AsyncSession,
    values: Iterable[WeatherValue],
) -> int:
    rows = [weather_value_to_row(v) for v in values]
    if not rows:
        return 0
    
    # 작은 batch는 INSERT ON CONFLICT
    if len(rows) < 5000:
        return await _upsert_via_insert(session, rows)
    
    # 큰 batch는 staging COPY → INSERT FROM SELECT (ADR-013)
    return await _upsert_via_copy(session, rows)
```

bulk insert는 ADR-013 (`psycopg.copy_*` 안전 마진 30k).

## 10. 보관 정책 (ADR-017)

- `weather_values`: +30일 (참조 trip 0건은 즉시 삭제 — TripMate trip_pois join
  으로 별도 검증).
- purge SQL: `docs/architecture/data-model.md` §7 또는 `docs/architecture/postgres-schema.md` §7.

## 11. provider sync state cursor 예시

```python
ProviderSyncState(
    provider="python-kma-api",
    dataset_key="kma_short_forecast",
    sync_scope="grid_60_127",      # 격자 단위로 분할 시
    cursor={"last_base_datetime": "20260524_1400"},
    last_success_at=kst_now(),
    next_run_after=kst_now() + timedelta(minutes=30),
)
```

## 12. feature 연결

| weather provider | feature 매핑 |
|------------------|-------------|
| KMA 단기/중기 | grid 좌표 → 인근 place feature_id (또는 weather-only marker) |
| KMA 특보 | 행정구역 단위 → `area` 또는 `notice` feature로도 변환 |
| 산악기상 | 관측소 ID → feature_id (산림청 휴양림 또는 별도 weather-only) |
| 휴게소 weather | rest_area feature_id 직접 |
| 공항 weather | airport feature_id 직접 |
| 해수욕장 marine | beach feature_id 직접 |
| AirKorea | 측정소 ID → feature_id (또는 인근 place 매핑) |
| 농업/수문 | 관측소 → feature_id 또는 weather-only marker |

weather-only marker는 `FeatureKind.WEATHER` 사용. 사용자 가시 UI에는 표시 안
하고 weather 데이터의 anchor 역할.

## 13. 정합성 검증 (T-201)

| 케이스 | 검사 |
|--------|------|
| `W1` | 모든 `WeatherValue.feature_id`가 `features`에 존재 |
| `W2` | `valid_at < issued_at` 검출 (예보가 발표 전 시각) |
| `W3` | `observed_at > now() + 1h` (관측 미래값) |
| `W4` | provider 한 dataset에 30분 이상 새 데이터 없음 (sync 정체) |
| `W5` | 같은 `(feature_id, metric_key, valid_at)`에 provider별 값 편차 > threshold (예: KMA short vs KMA mid 기온 차이 10°C 이상) |

일 1회 검사 + admin 알림.

## 14. v1 → v2 변경

- import: `kor_travel_map.models.WeatherValue` → `kortravelmap.dto.weather.WeatherValue`.
- `kor_travel_map.db.feature_weather_values` → `kortravelmap.infra.models.feature_weather_values`.
- async-only: provider 호출 모두 `async for`.
- 표준 `metric_key` 카탈로그는 v2에서 본 문서가 정답.
- `build_weather_card` helper는 v2 신규.

## 15. 운영 체크리스트

- [ ] 모든 provider weather adapter에 `normalization_version="weather-feature-v1"` 박힘
- [ ] BRIN(valid_at) 효율 측정
- [ ] purge job 작동 (30일 누적 row 0건)
- [ ] sync state `next_run_after` 모니터링 (`provider_sync_state.status='active'`)
- [ ] W1~W5 정합성 검사 일 1회
