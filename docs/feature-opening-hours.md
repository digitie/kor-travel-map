# feature-opening-hours.md — feature 영업시간

본 문서는 모든 kind의 feature(`place`/`event`/`notice`/`area`)가 공유하는
영업시간/운영시간 DTO와 DB 모델이다. Google Places signature 호환 + 한국 운영
관습 반영.

## 1. 설계 원칙

- **장소 로컬 시간만 저장**. 절대 timestamp 저장 X. DST는 영업 여부 계산
  시점에만 변환.
- Google Places 표준 호환 (`OpeningHours` JSON 구조).
- 자정 넘는 구간(`open` 금20:00, `close` 토02:00)은 **하나의 period로 유지**.
- 24/7은 Google signature 그대로: `open={day:0,time:"0000"}, close=None`.
- 예외(공휴일/임시 휴무/연장)는 `feature_special_days`에서 처리. 정규
  `feature_opening_periods`보다 우선.

## 2. DTO

### 2.1 `OpeningTime`

```python
class OpeningTime(BaseModel):
    day: int = Field(ge=0, le=6)              # 0 = Sunday (Google Places)
    time: str = Field(pattern=r"^([01]\d|2[0-3])[0-5]\d$")  # HHMM
```

### 2.2 `OpeningPeriod`

```python
class OpeningPeriod(BaseModel):
    open: OpeningTime
    close: OpeningTime | None = None          # None만 24/7 (open=Sun 0000)
    
    @computed_field
    @property
    def duration_minutes(self) -> int:
        if self.close is None:
            return 7 * 24 * 60
        start = _minute_of_week(self.open.day, self.open.time)
        end = _minute_of_week(self.close.day, self.close.time)
        if end <= start:
            end += 7 * 24 * 60                # 자정 넘는 period
        return end - start
```

### 2.3 `SpecialOpeningDay`

```python
class SpecialOpeningDay(BaseModel):
    date: date
    is_closed: bool = False
    periods: list[OpeningPeriod] | None = None
    exceptional_hours: bool = True
    
    @model_validator(mode="after")
    def _check(self):
        if self.is_closed and self.periods:
            raise ValueError("closed special days cannot have periods")
        if not self.is_closed and not self.periods:
            raise ValueError("open special days must have ≥1 period")
        return self
```

### 2.4 `FeatureOpeningHours`

```python
class FeatureOpeningHours(BaseModel):
    timezone: str = "Asia/Seoul"
    open_now: bool | None = None              # 조회 시점 계산값
    periods: list[OpeningPeriod] = Field(default_factory=list)
    special_days: list[SpecialOpeningDay] = Field(default_factory=list)
    weekday_text: list[str] = Field(default_factory=list)  # 사용자 가시 문자열
```

## 3. 24/7 표기 (Google Places signature)

```python
ALWAYS_OPEN = FeatureOpeningHours(
    periods=[OpeningPeriod(
        open=OpeningTime(day=0, time="0000"),
        close=None,
    )],
    weekday_text=["연중무휴 24시간"],
)
```

- `close=None`은 **24/7에만 허용** (validator로 강제).
- 다른 케이스에서 `close=None`은 ValidationError.

## 4. 자정 넘는 period

금요일 20:00 ~ 토요일 02:00:

```python
OpeningPeriod(
    open=OpeningTime(day=5, time="2000"),
    close=OpeningTime(day=6, time="0200"),
)
# duration_minutes = 6 * 60 = 360
```

`duration_minutes` 계산이 자정 넘김 처리. `close < open` 같은 동일 weekday
케이스는 다음 주로 wrap (드물지만 처리).

## 5. 적용 대상

| Feature kind | 필드 | 비고 |
|--------------|------|------|
| `place` | `PlaceDetail.business_hours` | 식당/카페/관광시설/주유소 영업시간 |
| `event` | `EventDetail.opening_hours` | 축제/행사 운영시간 (기간 내 일별) |
| `area` | `AreaDetail.payload.access_hours` (옵션) | 국립공원 입장시간 등 |
| `notice` | 사용 안 함 | notice는 `valid_start/end_time`으로 |

## 6. DB 매핑

### 6.1 `feature.feature_opening_periods`

```sql
CREATE TABLE feature.feature_opening_periods (
  feature_id        TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  period_index      SMALLINT NOT NULL,
  start_weekday     SMALLINT NOT NULL,        -- 0 = Sunday (Google)
  start_time        CHAR(4) NOT NULL,         -- HHMM
  duration_minutes  INTEGER NOT NULL,         -- 1 .. 10080 (7*24*60)
  timezone          TEXT NOT NULL DEFAULT 'Asia/Seoul',
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, period_index),
  CHECK (start_weekday BETWEEN 0 AND 6),
  CHECK (start_time ~ '^([01]\d|2[0-3])[0-5]\d$'),
  CHECK (duration_minutes > 0 AND duration_minutes <= 10080)
);
```

- `duration_minutes`로 자정 넘는 period를 portable하게 표현 (SQLite도 호환).
- PostgreSQL 운영에서는 추가로 `btree_gist` + `tsrange`/interval 기반 겹침 방지
  제약 검토 (선택, 코드 작성 단계).

### 6.2 `feature.feature_special_days`

```sql
CREATE TABLE feature.feature_special_days (
  feature_id     TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  special_date   DATE NOT NULL,
  is_closed      BOOLEAN NOT NULL,
  periods        JSONB,                       -- list[OpeningPeriod] dump
  payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, special_date)
);
```

- `periods`는 JSONB (단일 row에 0~N개 period를 그대로). 정규 `feature_opening_periods`와 다른 구조.
- `is_closed=True`이면 `periods` null.

### 6.3 DTO ↔ DB 변환

```python
def opening_hours_to_period_rows(feature_id: str, hours: FeatureOpeningHours) -> list[dict]:
    return [
        opening_period_to_row(feature_id, idx, p)
        for idx, p in enumerate(hours.periods)
    ]

def opening_period_to_row(feature_id: str, idx: int, p: OpeningPeriod) -> dict:
    return {
        "feature_id": feature_id,
        "period_index": idx,
        "start_weekday": p.open.day,
        "start_time": p.open.time,
        "duration_minutes": p.duration_minutes,
    }

def special_opening_day_to_row(feature_id: str, day: SpecialOpeningDay) -> dict:
    return {
        "feature_id": feature_id,
        "special_date": day.date,
        "is_closed": day.is_closed,
        "periods": [p.model_dump(mode="json") for p in day.periods] if day.periods else None,
    }
```

## 7. 영업 여부 계산

특정 datetime의 영업 여부:

```python
def is_open_at(hours: FeatureOpeningHours, dt: datetime) -> bool:
    """dt is timezone-aware (or assumed in hours.timezone)."""
    local_dt = dt.astimezone(ZoneInfo(hours.timezone))
    
    # 1. special_days 먼저
    for special in hours.special_days:
        if special.date == local_dt.date():
            if special.is_closed:
                return False
            return any(_period_contains(p, local_dt) for p in (special.periods or []))
    
    # 2. 정규 periods
    return any(_period_contains_weekday_time(p, local_dt) for p in hours.periods)
```

`open_now`는 조회 시점에 계산해 응답에 포함 (DB에는 저장 X).

## 8. provider별 매핑

### 8.1 MOIS (영업시간 X)

MOIS API는 영업시간 제공 안 함. `business_hours=None`.

### 8.2 OpiNet

provider 응답에 `business_hours`/`opening_hours` 필드 있으면 구조화 dict →
`FeatureOpeningHours`. 원문 문자열은 `PlaceDetail.payload.raw_business_hours`.

### 8.3 VisitKorea (event)

축제는 `EventDetail.starts_on`/`ends_on`이 기간. 일별 운영시간(`playtime`)이
구조화 가능하면 `EventDetail.opening_hours: FeatureOpeningHours`. 원문은
`payload.raw_playtime`. v2 1차에서는 starts_on/ends_on만 채우고 playtime 구조화는
별도 단계.

### 8.4 KHOA beach (입수 가능 시간)

해수욕장은 보통 24/7 출입 가능하나 개장 기간(`개장일`/`폐장일`)이 별도.
`SpecialOpeningDay`로 비개장일 표시 가능.

### 8.5 국가유산

- 관람 시간: 사찰/유적지는 `FeatureOpeningHours`로 일반 영업시간.
- 무형유산 공연: `EventDetail`의 `opening_hours`.

### 8.6 Place phone enrichment (Kakao/Naver/Google)

Google Places (New) API는 `regularOpeningHours.periods`를 표준 구조로 제공:

```python
def google_places_hours_to_dto(google_hours: dict) -> FeatureOpeningHours:
    periods = []
    for p in google_hours.get("periods", []):
        periods.append(OpeningPeriod(
            open=OpeningTime(day=p["open"]["day"], time=f"{p['open']['hour']:02d}{p['open']['minute']:02d}"),
            close=OpeningTime(day=p["close"]["day"], time=f"{p['close']['hour']:02d}{p['close']['minute']:02d}") if "close" in p else None,
        ))
    return FeatureOpeningHours(
        periods=periods,
        weekday_text=google_hours.get("weekdayDescriptions", []),
    )
```

Place phone enrichment는 현재 전화번호만 보강 (v2 1차). 영업시간 보강은 별도
ADR 후 추가 (`place-phone-enrichment.md` §13 후속).

## 9. UI 표시

`weekday_text`는 사용자 가시 문자열:

```python
weekday_text = [
    "일요일: 휴무",
    "월요일: 오전 10:00 - 오후 9:00",
    "화요일: 오전 10:00 - 오후 9:00",
    ...
]
```

provider가 제공하면 그대로. 없으면 `periods`에서 자동 생성 (TripMate frontend
또는 본 라이브러리 helper).

## 10. 시간대

- 기본 `Asia/Seoul`. 모든 한국 feature.
- 해외 feature 가능성 (v2 1차 범위 외)이면 `timezone` 필드로 처리.
- DST 처리는 영업 여부 계산 시점만 — DB 저장은 wall-clock 그대로.

## 11. 정합성 룰 (예시)

```sql
-- 동일 feature 내 period 겹침 (PostgreSQL only; tsrange + EXCLUDE)
ALTER TABLE feature.feature_opening_periods
  ADD CONSTRAINT no_overlap EXCLUDE USING gist (
    feature_id WITH =,
    int4range(
      start_weekday * 1440 + (substring(start_time from 1 for 2)::int * 60 + substring(start_time from 3 for 2)::int),
      start_weekday * 1440 + (substring(start_time from 1 for 2)::int * 60 + substring(start_time from 3 for 2)::int) + duration_minutes
    ) WITH &&
  );
```

(자정 넘는 period는 wrap 처리 별도 — 코드 작성 단계에서 결정)

T-201 정합성 케이스:
- `H1`: special_date < today - 1y 누적 — purge 대상
- `H2`: period 겹침 (위 EXCLUDE 위반 row)
- `H3`: 24/7인데 추가 period 존재
- `H4`: `is_closed=True`인데 periods 존재 (validator로 차단되지만 DB 직접 수정 시)

## 12. 단위 테스트 매트릭스

- `OpeningTime` regex (`HHMM` 0000~2359).
- `OpeningPeriod.duration_minutes`: 정상 / 자정 넘김 / 24/7.
- `OpeningPeriod.close=None` validation (24/7만 허용).
- `SpecialOpeningDay.is_closed` ↔ `periods` 상호배타.
- `is_open_at` 시나리오 (정규 / special / DST 경계).

## 13. v1 → v2 변경

- import: `krtour_map.opening_hours` → `krtour.map.opening_hours` (또는
  `krtour.map.dto.opening_hours`).
- DTO 자체는 v1 그대로 유지 (Google Places 호환).
- DB 컬럼/CHECK 그대로 유지.

## 14. 운영 체크리스트

- [ ] 모든 place의 `business_hours` 비율 모니터링 (provider 미제공 시 null 정상)
- [ ] `special_days` purge job (`H1`)
- [ ] PostgreSQL EXCLUDE 제약 검토 (운영 부하 없으면 활성)
- [ ] frontend `weekday_text` 표시 일관
