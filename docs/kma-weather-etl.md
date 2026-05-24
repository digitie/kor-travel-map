# kma-weather-etl.md — KMA 기상청 weather ETL

본 문서는 KMA(`python-kma-api`)의 4종 weather endpoint를 `WeatherValue`로
적재하는 ETL이다. 표준 metric_key / forecast_style / timeline_bucket 매핑은
`docs/weather-feature-normalization.md`가 정답.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-kma-api` |
| dataset_key | `kma_ultra_short_nowcast`, `kma_ultra_short_forecast`, `kma_short_forecast`, `kma_mid_forecast`, `kma_weather_alerts` (notice로 변환) |
| Feature.kind | (weather → `WeatherValue` 적재) / (alert → `notice` 적재) |
| 코드 entrypoint | `krtour.map.providers.kma` |
| 갱신 주기 | endpoint별 (10분~12시간) |

## 2. 4종 weather endpoint

| dataset_key | KMA endpoint | forecast_style | timeline_bucket | 갱신 주기 |
|-------------|--------------|---------------|----------------|----------|
| `kma_ultra_short_nowcast` | 초단기실황 (`getUltraSrtNcst`) | `nowcast` | `ultra_short` | 10분 |
| `kma_ultra_short_forecast` | 초단기예보 (`getUltraSrtFcst`) | `ultra_short` | `ultra_short` | 30분 |
| `kma_short_forecast` | 단기예보 (`getVilageFcst`) | `short` | `short` | 30분 |
| `kma_mid_forecast` | 중기예보 (`getMidLandFcst`) | `mid` | `mid` | 12시간 (일 2회) |

특보(`kma_weather_alerts`)는 `notice`로 변환 → `docs/notice-feature-etl.md`.

## 3. KMA 격자 좌표

KMA API는 위경도 대신 격자 좌표 `(nx, ny)` 사용. 변환:

```python
# python-kma-api 또는 본 라이브러리 helper
from krtour.map.providers.kma.grid import latlon_to_grid

nx, ny = latlon_to_grid(lat=37.5, lon=127.0)
# (60, 127) — 서울 종로구 일대
```

격자 → 인근 feature 매핑 전략:
- **옵션 A**: 격자마다 weather-only `Feature(kind=weather)` 생성, 인근 place
  feature와 `sibling_group_id`로 묶음.
- **옵션 B**: 각 place의 `coord`로 격자 계산 → 같은 격자의 weather를 직접 매핑.

v2 1차: 옵션 B (place 별로 격자 계산하면 매핑 N:1로 깔끔).

## 4. 단기예보 변환 (TMP, REH, WSD, PTY, SKY 등)

```python
from krtour.map.providers.kma import short_forecast_to_weather_values

async def update_short_forecast_for_grid(client, async_session, nx, ny, feature_ids):
    """특정 격자의 단기예보 → 격자 내 모든 feature에 적용."""
    items = await client.aget_short_forecast(nx=nx, ny=ny, base_date=..., base_time=...)
    
    values = []
    for feature_id in feature_ids:
        async for value in short_forecast_to_weather_values(
            items, feature_id=feature_id, fetched_at=kst_now(),
        ):
            values.append(value)
    
    await upsert_weather_values(async_session, values)
    await async_session.commit()
```

`short_forecast_to_weather_values`:

```python
async def short_forecast_to_weather_values(
    items: Iterable[KmaShortForecastItem],
    *,
    feature_id: str,
    fetched_at: datetime,
) -> AsyncIterator[WeatherValue]:
    for item in items:
        # KMA category code → metric_key (이미 표준에 가까움)
        metric_key = item.category                # T1H/TMP/REH/WSD/VEC/RN1/PTY/SKY/POP/PCP/SNO/WAV/UUU/VVV/T3H/TMN/TMX
        if metric_key not in STANDARD_METRIC_KEYS:
            continue                              # 미지원은 skip
        
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

## 5. 중기예보

지역 단위 (107 지점 — 광역시도 + 특수지역). 격자 X.

```python
async def mid_forecast_to_weather_values(
    items, *, feature_id_by_region: dict[str, str], fetched_at,
) -> AsyncIterator[WeatherValue]:
    """region code (e.g., '11B00000' 서울) → feature_id 매핑."""
    ...
```

각 region마다 weather-only feature를 미리 생성하거나, 광역시도 행정구역 area
feature에 연결.

## 6. base_time 처리

KMA 단기예보 `base_time`: 02, 05, 08, 11, 14, 17, 20, 23 (3시간 간격).
초단기실황: 매시 정각 발표 후 10분 뒤 사용 가능.

```python
def _latest_base_time(now: datetime) -> tuple[str, str]:
    """가장 최근에 발표된 base_date, base_time."""
    SHORT_FCST_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]
    base_hour = max(h for h in SHORT_FCST_HOURS if h <= now.hour - 1)  # 발표 후 ~10분
    return now.strftime("%Y%m%d"), f"{base_hour:02d}00"
```

`provider_sync_state.cursor`에 `last_base_datetime` 저장 → 같은 base 중복 호출
회피.

## 7. 적재 흐름 (단기예보 — 30분 cron)

```python
async def kma_short_forecast_etl(client, async_session):
    # 1. 모든 격자 + feature 매핑 조회
    grid_features = await load_grid_feature_mapping(async_session)
    # {(nx, ny): [feature_id, ...]}
    
    # 2. 최신 base 시각 결정
    base_date, base_time = _latest_base_time(kst_now())
    
    # 3. 격자별 호출
    for (nx, ny), feature_ids in grid_features.items():
        items = await client.aget_short_forecast(nx=nx, ny=ny,
                                                  base_date=base_date, base_time=base_time)
        for feature_id in feature_ids:
            values = [v async for v in short_forecast_to_weather_values(
                items, feature_id=feature_id, fetched_at=kst_now(),
            )]
            await upsert_weather_values(async_session, values)
    
    await async_session.commit()
```

격자가 많으면 (전국 ~5000) 분당 호출 한도 고려. KMA API 키 한도는 보통 일
~10,000 호출. 격자 그룹화 또는 batch 분할.

## 8. Dagster

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `weather_kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `*/10 * * * *` | `features_weather` |
| `weather_kma_ultra_short_forecast` | `kma_ultra_short_forecast` | `*/30 * * * *` | `features_weather` |
| `weather_kma_short_forecast` | `kma_short_forecast` | `*/30 * * * *` | `features_weather` |
| `weather_kma_mid_forecast` | `kma_mid_forecast` | `0 6,18 * * *` | `features_weather` |
| `notice_kma_weather_alerts` | `kma_weather_alerts` | `*/10 * * * *` | `features_notice` |

ConcurrencyConfig: `kma_api: max_concurrent=1`.

## 9. 데이터 양과 인덱스

- 격자 5000 × forecast 시점 24 × metric 8 = 약 96만 row/일.
- BRIN(valid_at), BRIN(collected_at) 효율적.
- partial index `WHERE valid_at > now() - interval '30 days'` 검토 (30일 retention).

## 10. 검증

### fixture

- `kma_short_forecast_typical.json` — 정상 (격자 60,127, base 1400)
- `kma_short_forecast_sky_change.json` — 시간대별 SKY 변화
- `kma_ultra_short_nowcast_typical.json` — 초단기실황
- `kma_mid_forecast_seoul.json` — 중기예보 서울

### 통합 테스트

- 격자 → feature 매핑 정확성
- base_time 결정 (현재 시각 → 가장 최근 발표)
- 동일 base 중복 호출 회피 (`provider_sync_state.cursor`)
- BRIN 인덱스 효율 (1주 누적 후 EXPLAIN)

## 11. 후속

- 격자 그룹화 최적화 (인접 격자 일괄)
- 단기예보 → 중기예보 fallback (단기예보가 3일까지만 커버)
- KMA 영향예보 (impact-based forecasting) 추가
- 항공기상 (`python-krairport-api` 연계)
