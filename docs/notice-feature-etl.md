# notice-feature-etl.md — 통합 notice ETL (교통/기상/안전/해양)

본 문서는 4개 provider의 짧은 수명 공지성 데이터를 `Feature(kind=notice)` +
`NoticeDetail`로 통합 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krex-api`, `python-kma-api`, `python-krforest-api`, `python-khoa-api` |
| dataset_key | `krex_traffic_notices`, `kma_weather_alerts`, `forest_safety_notices`, `khoa_coastal_notices` |
| Feature.kind | `notice` |
| 상세 테이블 | `feature_notice_details` |
| 코드 entrypoint | `krtour.map.providers.{krex,kma,krforest,khoa}`, `krtour.map.notices` |

## 2. 4 dataset 갱신 주기

| dataset_key | provider | 갱신 주기 | 이유 |
|-------------|---------|----------|------|
| `krex_traffic_notices` | `python-krex-api` | **5분** | 사고/공사/통제 즉시 영향 |
| `kma_weather_alerts` | `python-kma-api` | **10분** | 특보 발효/해제 짧은 시간 변경 |
| `forest_safety_notices` | `python-krforest-api` | **30분** | 산사태/산불/탐방 위험 |
| `khoa_coastal_notices` | `python-khoa-api` | **60분** | 바다 갈라짐/해양 위험 |

## 2.5 카테고리 매핑

`notice` kind는 **`Feature.category`를 비워두거나** Tier 1 `01000000`
`TOURISM` (대분류 — 여행 영향)으로 설정. 분류는 `NoticeDetail.notice_type`이
1차 담당 (`docs/category.md` §4의 8개 Tier 1과는 별도 축).

marker_icon: `notice_type`별 (예: `alert` / `roadblock` / `rainwear`).
marker_color: `notice_type`별 (`P-13` 위험 / `P-08` 기상 / `P-14` 일반).

자세한 marker 매핑은 `notice_marker_style(notice_type, severity)` helper.

## 3. `notice_type` 표준 값

```python
NOTICE_TYPE_TRAFFIC            = "traffic"
NOTICE_TYPE_TRAFFIC_ACCIDENT   = "traffic_accident"
NOTICE_TYPE_ROAD_CLOSURE       = "road_closure"
NOTICE_TYPE_ROADWORK           = "roadwork"
NOTICE_TYPE_WEATHER_ALERT      = "weather_alert"
NOTICE_TYPE_HEAVY_RAIN         = "heavy_rain_warning"
NOTICE_TYPE_HEAVY_SNOW         = "heavy_snow_warning"
NOTICE_TYPE_HEAT_WAVE          = "heat_wave_warning"
NOTICE_TYPE_SAFETY             = "safety"
NOTICE_TYPE_EARTHQUAKE         = "earthquake"
NOTICE_TYPE_LANDSLIDE          = "landslide_warning"
NOTICE_TYPE_COASTAL_ISOLATION  = "coastal_isolation"

NOTICE_TYPES = (
    NOTICE_TYPE_TRAFFIC, NOTICE_TYPE_TRAFFIC_ACCIDENT, NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_WEATHER_ALERT, NOTICE_TYPE_HEAVY_RAIN, NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_SAFETY, NOTICE_TYPE_EARTHQUAKE, NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_COASTAL_ISOLATION,
)
```

`normalize_notice_type(value)`가 한/영 alias 정규화:

| 입력 | 출력 |
|------|------|
| `"호우주의보"`, `"호우경보"`, `"heavy_rain"` | `heavy_rain_warning` |
| `"대설"`, `"폭설"`, `"heavy_snow"` | `heavy_snow_warning` |
| `"폭염"`, `"폭염주의보"` | `heat_wave_warning` |
| `"지진"`, `"earthquake"` | `earthquake` |
| `"산사태"`, `"landslide"` | `landslide_warning` |
| `"바다갈라짐"`, `"coastal_isolation"` | `coastal_isolation` |
| `"교통사고"`, `"accident"` | `traffic_accident` |
| `"통제"`, `"도로통제"`, `"road_closure"` | `road_closure` |
| `"공사"`, `"도로공사"`, `"roadwork"` | `roadwork` |

provider 원문 등급/문구는 `NoticeDetail.payload`에 보존.

## 4. NoticeDetail

```python
class NoticeDetail(BaseModel):
    feature_id: str
    notice_type: str                          # NOTICE_TYPES 중 (validator로 정규화)
    severity: int | None = Field(default=None, ge=0, le=5)   # 공통 등급
    valid_start_time: datetime | None = None
    valid_end_time: datetime | None = None
    source_agency: str | None = None          # 발령기관
    officer_name: str | None = None
    payload: dict = Field(default_factory=dict)
```

`severity` 공통 등급:
- `0`: 정보 알림
- `1`: 주의보
- `2`: 경보
- `3`: 긴급
- `4`: 위험
- `5`: 매우 위험 / 즉시 대응

provider 원문 등급은 `payload`. 예시:
```python
severity = 2  # 경보
payload = {"krex_grade": "Level3", "krex_grade_desc": "차량 통행 통제"}
```

## 5. dataset별 매핑

### 5.1 krex_traffic_notices

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `incident_type` | `notice_type` (사고/공사/통제 → 정규화) |
| `grade` | `severity` (0-5 정규화) |
| `start_time` / `end_time` | `valid_start_time` / `valid_end_time` |
| `road_name` + `direction` | `payload.road_info` |
| `description` | `Feature.detail.description` |

좌표: 사고/공사 지점 → `Feature.coord`.

### 5.2 kma_weather_alerts

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `alert_type` (예: 호우경보) | `notice_type` 정규화 |
| `level` | `severity` |
| `effective_time` / `expiration_time` | `valid_*_time` |
| `affected_areas[]` | `payload.areas` (행정구역 리스트) |
| `description` | `Feature.detail.description` |

특보는 지역 단위 → 한 알림이 여러 행정구역에 영향. 한 alert를 N개 feature로
복제하거나, 단일 feature + `payload.affected_areas`로 처리. v2 1차: 후자
(단일 feature).

### 5.3 forest_safety_notices

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `notice_kind` (산불/산사태/입산통제) | `notice_type` 정규화 |
| `risk_level` | `severity` |
| `start_date` / `end_date` | `valid_*_time` |
| `mountain_name` | `Feature.name` (산이름 prefix) |
| `description` | `Feature.detail.description` |

좌표: 해당 산 좌표 또는 입산통제 구역 centroid.

### 5.4 khoa_coastal_notices

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `notice_kind` (바다 갈라짐 / 너울 / 이안류) | `notice_type` 정규화 |
| `severity` | `severity` |
| `valid_period` | `valid_*_time` |
| `location_name` | `Feature.name` |

## 6. 핵심 함수

```python
# providers/krex.py
async def traffic_notice_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# providers/kma.py
async def weather_alert_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# providers/krforest.py
async def safety_notice_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# providers/khoa.py
async def coastal_notice_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# notices.py
from krtour.map.dto.etl import EtlJobSpec

def notice_job_specs() -> list[EtlJobSpec]:
    return [
        EtlJobSpec(
            provider="python-krex-api", dataset_key="krex_traffic_notices",
            source_entity_type="traffic_notice",
            feature_kind=FeatureKind.NOTICE,
            full_scan_interval_days=None, interval_minutes=5,
            suggested_concurrency=1, suggested_group_name="features_notice",
            description="한국도로공사 교통 공지 (5분)",
        ),
        EtlJobSpec(
            provider="python-kma-api", dataset_key="kma_weather_alerts",
            source_entity_type="weather_alert",
            feature_kind=FeatureKind.NOTICE,
            interval_minutes=10, suggested_group_name="features_notice",
            ...
        ),
        EtlJobSpec(
            provider="python-krforest-api", dataset_key="forest_safety_notices",
            source_entity_type="safety_notice",
            feature_kind=FeatureKind.NOTICE,
            interval_minutes=30, ...
        ),
        EtlJobSpec(
            provider="python-khoa-api", dataset_key="khoa_coastal_notices",
            source_entity_type="coastal_notice",
            feature_kind=FeatureKind.NOTICE,
            interval_minutes=60, ...
        ),
    ]
```

## 7. 마커 스타일

| notice_type | maki icon | color |
|-------------|-----------|-------|
| `traffic`, `traffic_accident`, `road_closure`, `roadwork` | `roadblock` | `P-14` (검정) |
| `weather_alert`, `heavy_rain_warning` | `rainwear` | `P-08` (파랑) |
| `heavy_snow_warning` | `snowflake` | `P-07` (하늘) |
| `heat_wave_warning` | `temperature` | `P-15` (주홍) |
| `earthquake` | `alert` | `P-14` |
| `landslide_warning` | `alert` | `P-12` (갈색) |
| `coastal_isolation` | `alert` | `P-13` (회색) |
| 기타 `safety` | `alert` | `P-14` |

`notice_marker_style(notice_type, severity)` helper 제공.

## 8. Dagster

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `notice_krex_traffic` | `krex_traffic_notices` | `*/5 * * * *` | `features_notice` |
| `notice_kma_weather_alerts` | `kma_weather_alerts` | `*/10 * * * *` | `features_notice` |
| `notice_krforest_safety` | `forest_safety_notices` | `*/30 * * * *` | `features_notice` |
| `notice_khoa_coastal` | `khoa_coastal_notices` | `0 * * * *` | `features_notice` |

ConcurrencyConfig: provider별 `max_concurrent=1`.

## 9. 보관 정책

`docs/data-model.md` §7 + ADR-017:
- notice 종료일 또는 발표일 +1년 후 purge
- 활성(현재 유효) notice만 frontend에 표시

```sql
DELETE FROM feature.feature_notice_details d USING feature.features f
WHERE d.feature_id=f.feature_id AND f.kind='notice'
  AND d.valid_end_time < now() - interval '1 year';
```

## 10. 검증

### fixture (≥ 12 — provider × 케이스 3)

- `krex_traffic_accident.json`, `krex_road_closure.json`, `krex_roadwork.json`
- `kma_heavy_rain_warning.json`, `kma_earthquake.json`, `kma_heat_wave.json`
- `forest_landslide_warning.json`, `forest_fire_risk_notice.json`, `forest_hiking_closure.json`
- `khoa_coastal_isolation_warning.json`, `khoa_high_waves.json`, `khoa_rip_current.json`

### 통합 테스트

- `normalize_notice_type` 한/영 alias 전수 검증
- `severity` 정규화 (provider 등급 → 0-5)
- 만료 notice purge 동작
- frontend 표시 필터 (`valid_end_time > now()`)

## 11. 후속

- KMA 영향예보, 폭염주의보 추가 등급 검토.
- 산림 안전 공지 GIS (위치/영역) 보강.
- KHOA marine 지수 → notice 자동 생성 (특정 threshold 초과 시).
- 알림 자동 전송 (TripMate trip POI가 영향 지역과 겹치면 사용자에게 push).
