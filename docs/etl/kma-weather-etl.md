# kma-weather-etl.md — KMA 기상청 weather ETL

본 문서는 KMA(`python-kma-api`)의 4종 weather endpoint를 `WeatherValue`로
적재하는 ETL이다. 표준 metric_key / forecast_style / timeline_bucket 매핑은
`docs/etl/weather-feature-normalization.md`가 정답.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-kma-api` |
| dataset_key | `kma_ultra_short_nowcast`, `kma_ultra_short_forecast`, `kma_short_forecast`, `kma_mid_forecast`, `kma_weather_alerts` (notice로 변환) |
| Feature.kind | (weather → `WeatherValue` 적재) / (alert → `notice` 적재) |
| 코드 entrypoint | `kortravelmap.providers.kma` |
| 갱신 주기 | endpoint별 (10분~12시간) |
| category | 격자 weather feature(`kind=weather`)는 `category="99000000"` sentinel (weather kind는 detail 없음). 초단기/단기 격자 feature는 §3 참조 (`docs/architecture/category.md` §4). 산악 관측소 anchor는 `WEATHER_MOUNTAIN_STATION` 신설 후보 (forest-feature-etl.md §11.6) |

## 2. 4종 weather endpoint

| dataset_key | KMA endpoint | forecast_style | timeline_bucket | 갱신 주기 |
|-------------|--------------|---------------|----------------|----------|
| `kma_ultra_short_nowcast` | 초단기실황 (`getUltraSrtNcst`) | `nowcast` | `ultra_short` | 10분 |
| `kma_ultra_short_forecast` | 초단기예보 (`getUltraSrtFcst`) | `ultra_short` | `ultra_short` | 30분 |
| `kma_short_forecast` | 단기예보 (`getVilageFcst`) | `short` | `short` | 30분 |
| `kma_mid_forecast` | 중기예보 (`getMidLandFcst`) | `mid` | `mid` | 12시간 (일 2회) |

특보(`kma_weather_alerts`)는 `notice`로 변환 → `docs/etl/notice-feature-etl.md`.

## 3. KMA 격자 좌표

KMA API는 위경도 대신 격자 좌표 `(nx, ny)` 사용. 변환은 **python-kma-api 책임**
(LCC DFS 내장) — krtour에 grid 모듈을 두지 않는다(ADR-006, 계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.1):

```python
from kma.grid import to_grid  # Dagster asset에서 lazy import

nx, ny = to_grid(37.5, 127.0)  # (lat, lon) 순서
# (60, 127) — 서울 종로구 일대
```

격자 → weather feature 전략 (**KMA-own-grid-features**, 2026-06-29 개정 —
초기 옵션 B "place 빌리기"에서 옵션 A "격자 자체 feature"로 전환):

각 대상 격자를 **자체** `Feature(kind=weather)`(격자 중심 좌표 =
`kma.grid.to_latlon(nx, ny)`)로 만든다 — `providers.kma.grid_to_weather_bundle`.
KMA 예보값은 이 격자 feature에 붙는다. place feature를 빌리지 않으므로 KMA 날씨가
**airkorea 측정소와 완전 별개** 마커로 뜬다. 격자당 1 feature·1 값세트라
격자×feature 팬아웃(약 30M행)은 없다(#496 anti-replication 유지). 다른 place의
날씨는 `build_weather_card`가 반경 내 가장 가까운 KMA 격자 기온 anchor를 조회·병합해
서빙한다(`weather_repo` nearest-temp, 반경 50km).

**초단기·단기는 격자 간격·갱신 주기가 달라 별개 feature로 분리**한다(같은 격자
`(nx,ny)`라도 `source_type`이 달라 `feature_id`가 다름):

| weather feature | `grid_dataset_key` | name_label | 적재 endpoint | 갱신 |
|-----------------|--------------------|-----------|--------------|------|
| 초단기 | `kma_ultra_short_grid` | `기상청 초단기` | 실황(`getUltraSrtNcst`) + 초단기예보(`getUltraSrtFcst`) **한 feature** | 매시간 |
| 단기 | `kma_short_grid` | `기상청 단기` | 단기예보(`getVilageFcst`) 별도 feature | 하루 8회 |

중기·특보는 격자가 아닌 region 단위라 좌표 매핑이 다르다 → **Phase 2**(별도
region feature, 후속 — reg_id→중심좌표 소스 결정 후).

**대상 격자 한정**(T-219a/b): 전 격자가 아니라 ① 활성 `poi_cache_targets` 좌표 + ②
설정 `KOR_TRAVEL_MAP_KMA_WEATHER_EXTRA_POINTS`(`lon,lat;lon,lat`)의 distinct 격자만,
run당 `KOR_TRAVEL_MAP_KMA_WEATHER_MAX_GRIDS_PER_RUN`(기본 300, ≤500) 상한 — "주요
도시·시군 단위" 커버리지. 격자에 매핑된 place feature가 없어도 격자 feature는
만든다(borrow 시절의 "place 없는 격자 skip"은 제거 — 격자가 자체 feature라 적재처가
항상 존재).

## 4. 단기예보 변환 (TMP, REH, WSD, PTY, SKY 등)

```python
from kortravelmap.providers.kma import short_forecast_to_weather_values

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

## 5. 중기예보 (T-219c 구현 기준)

지역 단위 (107 지점 — 광역시도 + 특수지역). 격자 X — 옵션 B 좌표 매핑 불가.
**1차는 운영자가 region→feature 매핑을 설정으로 명시 주입**하고, 미설정이면
asset이 skip한다(cursor 미전진):

```bash
# 육상(getMidLandFcst)과 기온(getMidTa)은 reg_id 체계가 다르다 —
# 예: 서울 육상 11B00000 vs 기온 11B10101.
KOR_TRAVEL_MAP_KMA_MID_REGION_FEATURES='[{"land_reg_id": "11B00000",
  "ta_reg_id": "11B10101", "feature_ids": ["<feature_id>", ...]}]'
```

파서는 `kortravelmap.providers.kma.parse_mid_region_features`(JSON 오류/필수 키
누락/빈 feature_ids/중복 페어는 ValueError). asset
`feature_weather_kma_mid_forecast`가 region별로 `DataGoKrClient.
mid_land_forecast` + `mid_temperature_forecast`를 호출해 SKY 텍스트/POP/TMN/TMX
`WeatherValue`를 적재한다. 변환은 `mid_land_forecast_to_weather_values` /
`mid_temperature_to_weather_values`(기구현).

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

`provider_sync_state.cursor`에 `base_datetime`(``YYYYMMDDHHMM``) 저장 → 같은
base 중복 호출 회피(T-219b 구현). 최신 base 계산도 python-kma-api
`kma.time_utils.latest_{ultra_srt_ncst,ultra_srt_fcst,vilage}_base`를 그대로
쓴다(발표 지연 내장 — 재구현 금지). KMA 호출/적재 실패 시 cursor 미전진 +
`record_sync_failure`(신선도 대시보드 T-217g 신호).

## 7. 적재 흐름 (단기예보 — 30분 cron)

> **NOTE (2026-06-29):** 아래 pseudocode는 격자→feature 빌리기 시절의 설계
> 스케치다. **현재 정본은 §3 + §8** — 각 격자가 자체 weather feature이고, 적재는
> `providers.kma.grid_to_weather_bundle` + asset(`dagster.kma_weather`)이 담당한다
> (per-feature 루프 아님).

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

## 8. Dagster (T-219b 구현 기준)

`kortravelmap.dagster.kma_weather` — 대상 좌표가 DB에서 나오므로 표준
record-resource 패턴이 아니라 **asset 직접 구현**(resource는
`kma_weather_client` = `KmaClient` live 인스턴스 + settings 값 2종). 발표
운영 schedule은 시간당 1회로 맞춘다. 원천 발표 주기보다 자주 실행되는 dataset은
같은 base 재실행을 cursor가 skip한다.

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `feature_weather_kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `45 * * * *` | `features_weather` |
| `feature_weather_kma_ultra_short_forecast` | `kma_ultra_short_forecast` | `50 * * * *` | `features_weather` |
| `feature_weather_kma_short_forecast` | `kma_short_forecast` | `20 * * * *` | `features_weather` |
| `feature_weather_kma_mid_forecast` | `kma_mid_forecast` | `25 * * * *` | `features_weather` |
| `feature_notice_kma_weather_alerts` | `kma_weather_alerts` | `15 * * * *` | `features_notice` |

특보(T-219c)는 표준 record-resource 패턴 — `kma_weather_alert_records`
(getWthrWrnList, 전국 발표관서 108, rolling window
`KOR_TRAVEL_MAP_KMA_WEATHER_ALERT_LOOKBACK_DAYS` 기본 3일, 멱등 upsert). 종류/등급은
title 토큰 스캔(미매칭은 generic `weather_alert`), 특보구역은 1차 발표관서
단위 1건 — region명이 `SourceRecord.raw_address` 위치 단서로 주소 검증을
통과한다. 구역→좌표 enrichment·구역별 fan-out은 백로그(§11).

변환 입력: `KmaClient`의 `ForecastItem`/`WeatherSnapshot`은 base/forecast를
`datetime`으로 정규화한 모델이라 krtour 변환 Protocol(KMA 공식 필드명
snake_case row)과 shape이 다르다 — client가 보존한 `raw` payload에서
`KmaForecastRow`/`KmaNowcastRow`를 만들어 변환에 넘긴다(ADR-044 신뢰·미러).

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
