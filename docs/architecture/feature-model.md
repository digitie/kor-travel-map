# feature-model.md — Feature DTO 사양

본 문서는 `kor-travel-map` v2의 `Feature` DTO와 kind별 detail의 사양이다.
`docs/architecture/data-model.md`(DB 스키마)와 1:1 대응한다.

## 1. `FeatureKind` (7종)

| value | 의미 |
|-------|------|
| `place` | 장소·시설·주차장·화장실·주유소·휴게소·해수욕장 등 |
| `event` | 축제·공연·전시 (기간성) |
| `notice` | 교통·기상·안전·해양 공지 (short-lived) |
| `price` | 가격 시계열 anchor marker (`feature_price_values`와 연결) |
| `weather` | weather-only marker (place와 분리된 관측소 등) |
| `route` | 산책로·등산로·자전거길·관광도로 (LINESTRING) |
| `area` | 국립공원·해수욕장구역·매장유산구역 (MULTIPOLYGON) |

## 2. `FeatureStatus`

| value | 의미 |
|-------|------|
| `draft` | ETL 중간상태 |
| `active` | 운영 노출 |
| `inactive` | 운영 미노출 (재활성화 가능) |
| `hidden` | 관리자 숨김 |
| `broken` | 정합성/좌표 문제 — 운영 점검 필요 |
| `deleted` | soft delete (`deleted_at` 기록) |

## 3. `SourceRole`

| value | 용도 |
|-------|------|
| `primary` | 이 feature의 1차 source |
| `base_address` | 주소 1차 출처 |
| `base_coordinate` | 좌표 1차 출처 |
| `enrichment` | 이름/전화/리뷰 부분 보강 |
| `correction` | 수동/자동 보정 |
| `duplicate_candidate` | dedup 검수 후보 |
| `media` | 이미지/문서 출처 |
| `weather_context` | weather 시계열 출처 |

## 4. `Feature` 본체

```python
class Feature(BaseModel):
    feature_id: str                      # make_feature_id(...) 결과
    kind: FeatureKind
    name: str = Field(min_length=1)
    coord: Coordinate | None = None      # WGS84 lon/lat — Korean bounds 검증
    coord_precision_digits: int | None = Field(default=None, ge=3, le=8)
                                         # coord 있으면 기본 6, coord 없으면 None
    geom: str | None = None              # route/area WKT (EPSG:4326); Point kind는 None
    address: Address = Field(default_factory=Address)
    category: str                        # 8자리 숫자, ^\d{8}$ 검증 (ADR-023)
    urls: FeatureUrls = Field(default_factory=FeatureUrls)
    marker_icon: str = Field(min_length=1)  # maki id
    marker_color: str                    # 'P-01' ~ 'P-16'
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None  # dedup group UUID의 string 표현
    detail: PlaceDetail | EventDetail | NoticeDetail | RouteDetail | AreaDetail | None = None
    raw_refs: list[RawDataRef] = Field(default_factory=list)
    status: FeatureStatus = FeatureStatus.ACTIVE
    created_at: datetime = Field(default_factory=kst_now)
    updated_at: datetime = Field(default_factory=kst_now)
    deleted_at: datetime | None = None
```

### 4.1 검증 룰 (Pydantic validator)

- `coord` 좌표: longitude ∈ [124.0, 132.0], latitude ∈ [33.0, 39.5].
  벗어나면 ValidationError.
- `coord_precision_digits`: `coord`가 None이면 None이어야 한다(아니면
  ValidationError). `coord`가 있고 값이 None이면 model validator가 기본 6으로
  채운다. 명시 값은 3~8 범위(`ge=3, le=8`).
- `geom`: route/area feature의 선·면 geometry (WKT, EPSG:4326). place/event 등
  Point feature는 `None`(좌표는 `coord`). `features.geom` 컬럼에 저장(ADR-012).
- 모든 datetime: timezone aware (Asia/Seoul). naive datetime 입력은
  ValidationError (ADR-019).
- `detail`: kind에 맞는 모델만 허용. dict 입력은 ValidationError (ADR-018).
  - kind=place → PlaceDetail
  - kind=event → EventDetail
  - kind=notice → NoticeDetail
  - kind=route → RouteDetail
  - kind=area → AreaDetail
  - kind=price/weather → None 가능 (별도 테이블에 시계열 저장)
- `marker_color`: regex `^P-(0[1-9]|1[0-6])$`.
- `category`: 8자리 숫자 regex `^\d{8}$`로 검증(ADR-023). known
  `PlaceCategoryCode` value strict 검증은 미적용 — unknown 8자리 코드(예
  `99000000`)도 임시 허용(transitional, fallback 룰 확정 전까지).

### 4.2 `FeatureUrls`

```python
class FeatureUrls(BaseModel):
    homepage: AnyUrl | None = None
    sns1: AnyUrl | None = None
    sns2: AnyUrl | None = None
    review_naver: AnyUrl | None = None
    review_kakao: AnyUrl | None = None
    review_google: AnyUrl | None = None
```

### 4.3 `RawDataRef`

```python
class RawDataRef(BaseModel):
    provider: str                        # canonical name (normalize_provider_name)
    dataset_key: str
    source_entity_id: str
    source_role: SourceRole = SourceRole.PRIMARY
    fetched_at: datetime | None = None
    payload_hash: str | None = None
```

`Feature.raw_refs`는 빠른 lookup용 요약. 정확한 source 관계는 `source_links`
테이블이 정답.

## 5. `PlaceDetail`

```python
class PlaceDetail(BaseModel):
    feature_id: str
    place_kind: str = "place"            # fuel_station / rest_area / beach / recreation_forest / museum / parking / license_place ...
    phones: list[str] = Field(default_factory=list, max_length=3)
    reviews_link: dict[str, AnyUrl] = Field(default_factory=dict)
    business_hours: FeatureOpeningHours | None = None
    facility_info: dict[str, Any] = Field(default_factory=dict)
    license_date: date | None = None
    biz_number: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

`facility_info`는 provider별 부가 정보 (예: 해수욕장의 `beachWid`/`beachLen`).
신규 필드 추가 시 ADR + 마이그레이션.

## 6. `EventDetail`

```python
class EventDetail(BaseModel):
    feature_id: str
    event_kind: str = "festival"         # festival / exhibition / concert / performance ...
    starts_on: date | None = None
    ends_on: date | None = None
    timezone: str = "Asia/Seoul"
    opening_hours: FeatureOpeningHours | None = None
    venue_name: str | None = None
    tel: str | None = None
    content_id: str | None = None
    content_type_id: str | None = None
    area_code: str | None = None
    sigungu_code: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dates(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must be >= starts_on")
        return self
```

## 7. `NoticeDetail`

```python
class NoticeDetail(BaseModel):
    feature_id: str
    notice_type: str                     # NOTICE_TYPES 중 (validator로 정규화)
    severity: int | None = Field(default=None, ge=0, le=5)
    valid_start_time: datetime | None = None
    valid_end_time: datetime | None = None
    source_agency: str | None = None
    officer_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

`notice_type` 정규화 상수:
```
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
```

`normalize_notice_type(value)`가 한국어 alias("호우주의보", "교통사고", ...)도
처리한다.

## 8. `RouteDetail`

```python
class RouteDetail(BaseModel):
    feature_id: str
    route_type: str = "route"            # ROUTE_TYPES 중
    geometry_source: str | None = None   # 'krforest', 'datagokr_standard', ...
    geometry_status: str | None = None   # 'provided' / 'missing_route_geometry'
    total_distance_meters: Decimal | None = Field(default=None, ge=0)
    expected_duration_minutes: int | None = Field(default=None, ge=1)
    difficulty: str | None = None        # 'easy', 'moderate', 'hard'
    begin_name: str | None = None
    begin_address: str | None = None
    end_name: str | None = None
    end_address: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

`route_type` 상수:
```
ROUTE_TYPE_ROUTE            = "route"
ROUTE_TYPE_HIKING_TRAIL     = "hiking_trail"
ROUTE_TYPE_ACCESSIBLE_WALK  = "accessible_walk"
ROUTE_TYPE_TREKKING         = "trekking"
ROUTE_TYPE_FOREST_TRAIL     = "forest_trail"
ROUTE_TYPE_TOURISM_ROAD     = "tourism_road"
ROUTE_TYPE_FACILITY_ROAD    = "facility_road"
ROUTE_TYPE_WALKING_COURSE   = "walking_course"
ROUTE_TYPE_CYCLING          = "cycling"
ROUTE_TYPE_DRIVE_COURSE     = "drive_course"
```

`normalize_route_type(value)`가 한국어 alias("등산로", "무장애산책길", "트레킹",
...) 처리.

geometry 자체는 `features.geom` 컬럼에 저장 (LINESTRING/MULTILINESTRING).
RouteDetail에는 메타만.

## 9. `AreaDetail`

```python
class AreaDetail(BaseModel):
    feature_id: str
    area_kind: str = "area"              # national_park / provincial_park / recreation_forest / tourism_district / beach / campsite / heritage_area / natural_heritage_area / buried_heritage_area / hazard_zone / protected_area / other
    boundary_source: str | None = None   # 'gis_3070426', 'gis_spca', 'krforest', ...
    area_square_meters: Decimal | None = None
    regulation_scope: str | None = None
    administrative_office: str | None = None
    description: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    # hazard_zone일 때 payload 예: {"hazard_type": "rockfall" | "flash_flood" | "wildlife" | ..., "domain": "forest" | "coastal" | ...}
    # protected_area일 때 payload 예: {"protection_type": "special" | "restricted_use" | ...}
```

geometry는 `features.geom` (MULTIPOLYGON).

## 10. 영업시간

```python
class OpeningTime(BaseModel):
    day: int = Field(ge=0, le=6)         # 0 = Sunday (Google Places)
    time: str = Field(pattern=r"^([01]\d|2[0-3])[0-5]\d$")  # HHMM

class OpeningPeriod(BaseModel):
    open: OpeningTime
    close: OpeningTime | None = None      # None만 24/7 (open=일요일 0000)

class SpecialOpeningDay(BaseModel):
    date: date
    is_closed: bool = False
    periods: list[OpeningPeriod] | None = None
    exceptional_hours: bool = True

class FeatureOpeningHours(BaseModel):
    timezone: str = "Asia/Seoul"
    open_now: bool | None = None
    periods: list[OpeningPeriod] = Field(default_factory=list)
    special_days: list[SpecialOpeningDay] = Field(default_factory=list)
    weekday_text: list[str] = Field(default_factory=list)
```

## 11. `SourceRecord`

```python
class SourceRecord(BaseModel):
    source_record_key: str                # make_source_record_key(...) 결과
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    raw_payload_hash: str
    source_version: str | None = None
    raw_name: str | None = None
    raw_address: str | None = None
    raw_longitude: Decimal | None = None
    raw_latitude: Decimal | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime
    imported_at: datetime = Field(default_factory=kst_now)
    expires_at: datetime | None = None
```

고유성: `(provider, dataset_key, source_entity_type, source_entity_id, raw_payload_hash)`.
`SourceRecord`는 `dto`가 `core`를 import하지 않도록 `.key()` 메서드를 두지 않는다.
provider 변환 함수가 `make_payload_hash(...)`와 `make_source_record_key(...)`를
호출해 `source_record_key`를 명시적으로 넣는다.

## 12. `SourceLink`

```python
class SourceLink(BaseModel):
    feature_id: str
    source_record_key: str
    source_role: SourceRole = SourceRole.ENRICHMENT
    match_method: str                    # 'natural_key', 'reverse_geocode', 'place_phone_search', 'dedup_merge', ...
    confidence: int = Field(ge=0, le=100)
    is_primary_source: bool = False
    created_at: datetime = Field(default_factory=kst_now)
```

## 13. `FeatureFile` (persisted row) / `FeatureFileSource` (dto)

`kortravelmap.dto`에 있는 파일 모델은 **`FeatureFileSource` 하나**다(업로드 전
입력). 아래 `FeatureFile`은 객체 저장소 적재 후의 **저장 row 형상**(`feature.
feature_files` 테이블, `docs/architecture/data-model.md` §5 정본)을 기록한 것으로, repo/SQL이
관리하며 별도 Pydantic dto 클래스로 구현돼 있지 않다. RustFS/업로드 계약 정본은
`docs/architecture/feature-files-rustfs.md`다.

```python
# persisted row 형상 (feature.feature_files) — dto 클래스 아님
class FeatureFile:
    file_id: str                         # make_feature_file_id(feature_id, bucket, object_key)
    feature_id: str
    file_type: Literal["image", "video", "audio", "document", "file"] = "image"
    storage_backend: str = "s3"          # validator로 's3' 강제 (RustFS 포함)
    bucket: str
    object_key: str
    source_url: str | None = None
    public_url: str | None = None
    content_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    role: Literal["primary", "thumbnail", "gallery"] = "gallery"
    display_order: int = Field(default=0, ge=0)
    alt_text: str | None = None
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=kst_now)
    updated_at: datetime = Field(default_factory=kst_now)
```

```python
class FeatureFileSource(BaseModel):
    """provider 측 ETL이 생성하는 업로드 입력 DTO."""
    feature_id: str
    source_url: str
    role: Literal["primary", "thumbnail", "gallery"] = "gallery"
    display_order: int = 0
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    content_type: str | None = None
    alt_text: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

`upload_feature_files(sources)` → 다운로드 + 업로드 + FeatureFile 메타 생성.

## 14. `WeatherValue` (ADR-010)

```python
class WeatherValue(BaseModel):
    feature_id: str
    provider: str
    weather_domain: WeatherDomain
    forecast_style: ForecastStyle
    timeline_bucket: TimelineBucket | None = None
    metric_key: str = Field(min_length=1)    # T1H, TMP, REH, WSD, RN1, PTY, SKY, FIRE_RISK ...
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None
    source_metric_key: str | None = None     # provider 원문 키
    source_metric_name: str | None = None
    metric_name: str | None = None           # 표준 이름 (한글 가능)
    value_number: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None                  # deg_c, %, m/s, mm, code, score ...
    severity: str | None = None
    normalization_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=kst_now)
    source_record_key: str | None = None

    def identity(self) -> tuple:
        return (self.feature_id, self.provider, self.weather_domain.value,
                self.forecast_style.value, self.metric_key,
                self.issued_at, self.valid_at, self.observed_at)
```

`timeline_bucket`은 분류 결과라 unique key에 포함 안 함. 자세한 매핑은
`docs/etl/weather-feature-normalization.md` (별도).

## 15. `PriceValue`

```python
class PriceValue(BaseModel):
    feature_id: str
    provider: str                        # canonical provider name (ADR-024)
    price_domain: PriceDomain            # provider별 가격 dataset 식별자 (enum)
    product_key: str                     # 'gasoline', 'diesel', 'lpg', 'adult', 'child', ...
    product_name: str | None = None      # 표준 한글 이름
    source_product_key: str | None = None    # provider 원천 product code
    source_product_name: str | None = None   # provider 원천 product 이름
    observed_at: datetime
    value_number: Decimal                # NUMERIC(14,4) 정합, 0 이상
    unit: str = "KRW"                    # 'KRW', 'KRW/L', 'KRW/회' ...
    normalization_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=kst_now)
    source_record_key: str | None = None

    def identity(self) -> tuple:
        return (self.feature_id, self.provider, self.price_domain.value,
                self.product_key, self.observed_at)
```

> `PricePoint`(price_category/retention_days)은 현재 dto에 구현되어 있지 않다.
> price 시계열은 `PriceValue`만 dto이고, `feature_id`는 `kind=price` anchor
> feature를 참조한다. DB 정본은 `feature.feature_price_values`
> (`docs/architecture/data-model.md` §8.2)다.

## 16. `ProviderSyncStateRow` (dto 아님 — ORM row)

provider sync state는 dto Pydantic 모델이 아니라 `infra/models.py`의 SQLAlchemy
ORM row `ProviderSyncStateRow`(`provider_sync.provider_sync_state` 테이블 매핑)다.
실제 컬럼 집합과 CHECK는 `docs/architecture/data-model.md` §4가 정본이다. 아래는 그 요약이다 —
초기 설계에 있던 `metadata_hash`/`last_observed_source_version`/`last_attempt_at`/
`last_full_scan_at`/`last_error`/`last_error_at`/`extra`는 구현 스키마에서 제외됐고,
실패 추적은 `last_failure_at` + `consecutive_failures`로 대체됐다.

```python
class ProviderSyncStateRow(Base):  # infra/models.py, provider_sync.provider_sync_state
    provider: str                  # PK
    dataset_key: str               # PK
    sync_scope: str                # PK (DEFAULT 없음)
    status: str = "active"         # active, paused, disabled, failed
    cursor: dict[str, Any]         # JSONB, default {}
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = 0
    next_run_after: datetime | None = None
    updated_at: datetime           # DEFAULT now()
```

## 17. `ImportJob` (dto 아님 — repo dataclass)

`ImportJob`은 dto Pydantic 모델이 아니라 `infra/jobs_repo.py`의 frozen dataclass
(`ops.import_jobs` 행 표현, repo 반환용)다. 별도 `ImportJobState` enum은 없고
`status`는 `str`다(허용 값 `queued`/`running`/`done`/`failed`/`cancelled`는
`ops.import_jobs` CHECK으로 강제 — `docs/architecture/data-model.md` §9.1 정본).

```python
@dataclass(frozen=True)
class ImportJob:  # infra/jobs_repo.py
    job_id: str
    kind: str                            # 'visitkorea_festival_full_scan', ...
    payload: dict[str, Any]
    status: str                          # queued / running / done / failed / cancelled
    progress: int
    current_stage: str | None
    source_checksum: str | None
    error_message: str | None
    load_batch_id: str | None = None     # T-200 full-load batch id
    parent_job_id: str | None = None     # root import job self-FK
```

`started_at`/`finished_at`/`heartbeat_at`/`created_at` 등 lifecycle 타임스탬프 컬럼은
`ops.import_jobs` 테이블에 있으며 repo dataclass에는 포함되지 않는다.

## 18. `FeatureBundle` (provider → load 전달 단위)

```python
class FeatureBundle(BaseModel):
    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink

    @property
    def detail(self) -> PlaceDetail | EventDetail | NoticeDetail | RouteDetail | AreaDetail | None: ...
```

`AsyncKorTravelMapClient.load_feature_bundles(bundles)`이 받는 단위.
`detail`은 별도 필드가 아니라 `feature.detail` alias다. PR#26 기준 bundle은
`feature`/`source_record`/`source_link` 3개 필수 필드만 받으며,
`file_sources`/`weather_values`/`price_values`는 해당 DTO가 구현되는 후속 PR에서
추가한다. `FeatureBundle`은 `source_link.feature_id == feature.feature_id`와
`source_link.source_record_key == source_record.source_record_key`를 검증한다.

## 19. detail 디스패치 (ADR-018)

```python
DETAIL_MODELS: Final[dict[FeatureKind, type[BaseModel]]] = {
    FeatureKind.PLACE:  PlaceDetail,
    FeatureKind.EVENT:  EventDetail,
    FeatureKind.NOTICE: NoticeDetail,
    FeatureKind.ROUTE:  RouteDetail,
    FeatureKind.AREA:   AreaDetail,
    # price / weather: None
}
```

직렬화/역직렬화는 이 dict로만. 자유 dict 우회 금지.

## 20. 단위 테스트 매트릭스 (요약, 상세는 test-strategy)

- `Feature` 좌표 검증: 한국 영역 내/외 boundary case
- `Feature.detail` kind mismatch → ValidationError
- `OpeningPeriod` close=None 24/7만 허용
- `EventDetail` `ends_on < starts_on` → ValidationError
- `NoticeDetail` time range 검증
- `WeatherValue.identity()` 결정성
- `SourceRecord.source_record_key` ↔ `make_source_record_key` 일치
- naive datetime 입력 → ValidationError
- 자유 dict → ValidationError
