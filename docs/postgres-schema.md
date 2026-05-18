# Postgres schema 기준

이 schema는 `python-krtour-map`이 소유한다. TripMate는 같은 feature DB를 복제하지 않고, 이 라이브러리의 SQLAlchemy Core metadata와 row helper를 import해서 같은 DB 설정으로 초기화한다.

목표 운영 환경은 PostgreSQL 16, PostGIS 3.5, `pg_trgm`이다. 로컬 단위 테스트에서는 동일 metadata가 SQLite에서도 생성될 수 있도록 PostGIS geometry 컬럼만 portable하게 컴파일한다.

## `features`

지도에 올릴 수 있는 공통 feature의 기준 table이다.

필수/핵심 컬럼:

- `feature_id text primary key`
- `kind text not null`: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- `name text not null`
- `category text not null`: `python-kraddr-base` category code
- `longitude numeric(12, 8) null`
- `latitude numeric(12, 8) null`
- `geom geometry(Geometry, 4326) null`
- `address json/jsonb not null default '{}'`
- `legal_dong_code text null`
- `road_name_code text null`
- `road_address_management_no text null`
- `admin_dong_code text null`
- `sido_code text null`
- `sigungu_code text null`
- `urls json/jsonb not null default '{}'`
- `marker_icon text null`
- `marker_color text null`
- `parent_feature_id text references features(feature_id) on delete set null`
- `sibling_group_id text null`
- `detail json/jsonb not null default '{}'`
- `raw_refs json/jsonb not null default '[]'`
- `status text not null`: `draft`, `active`, `inactive`, `hidden`, `broken`, `deleted`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

권장 인덱스:

- `(kind, category)`
- `(status)`
- `(legal_dong_code)`
- `(parent_feature_id)`
- `(sibling_group_id)`
- `(longitude, latitude)`
- `gist(geom)`
- `gin(name gin_trgm_ops)` 또는 host DB의 동등 검색 index

`parent_feature_id`는 직접 부모만 저장하고, N-depth tree 조회는 recursive CTE로 처리한다. 대체 후보나 형제 feature는 `sibling_group_id`로 묶는다.

## `source_records`

provider 원천 row를 재처리 가능한 형태로 보존한다.

unique 기준:

- `provider`
- `dataset_key`
- `source_entity_type`
- `source_entity_id`
- `raw_payload_hash`

핵심 컬럼:

- `source_record_key text primary key`
- `provider text not null`
- `dataset_key text not null`
- `source_entity_type text not null`
- `source_entity_id text not null`
- `source_version text null`
- `raw_name text null`
- `raw_address text null`
- `raw_longitude numeric(12, 8) null`
- `raw_latitude numeric(12, 8) null`
- `raw_data json/jsonb not null default '{}'`
- `raw_payload_hash text not null`
- `fetched_at timestamptz not null`
- `imported_at timestamptz not null`
- `expires_at timestamptz null`

## `source_links`

feature와 provider source record의 관계를 저장한다.

핵심 컬럼:

- `feature_id text references features(feature_id) on delete cascade`
- `source_record_key text references source_records(source_record_key) on delete cascade`
- `source_role text not null`
- `match_method text not null`
- `confidence numeric(5, 2) not null`
- `is_primary_source boolean not null`
- `created_at timestamptz not null`

제약:

- `primary key(feature_id, source_record_key)`
- `confidence between 0 and 100`
- `source_role in ('base_address', 'base_coordinate', 'primary', 'enrichment', 'correction', 'duplicate_candidate', 'media', 'weather_context')`

## `feature_place_details`

장소 feature의 공통 상세값을 저장한다. OpiNet 주유소/충전소, KREX 휴게소, 산림청 공원 시설처럼
장소성이 있고 provider별 상세 필드가 많은 원천은 `features.detail`에만 숨기지 않고 공통 조회
필드를 이 테이블에 구조화한다.

핵심 컬럼:

- `feature_id text primary key references features(feature_id) on delete cascade`
- `place_kind text not null default 'place'`
- `phones json/jsonb not null default '[]'`: 대표 전화번호 최대 3개는 DTO에서 검증한다.
- `reviews_link json/jsonb not null default '{}'`
- `business_hours json/jsonb null`: `FeatureOpeningHours` payload
- `facility_info json/jsonb not null default '{}'`
- `license_date date null`
- `biz_number text null`
- `payload json/jsonb not null default '{}'`

권장 인덱스:

- `(place_kind)`
- `(biz_number)`

## `feature_event_details`

행사/축제처럼 기간성이 있는 event feature의 세부 정보를 저장한다. VisitKorea 축제 ETL은
`python-visitkorea-api`의 `content_id`를 source natural key로 사용하고 이 테이블에 기간과
provider 식별자를 둔다.

필수/옵션 컬럼:

- `feature_id text primary key references features(feature_id) on delete cascade`
- `event_kind text not null`
- `starts_on date null`
- `ends_on date null`
- `timezone text not null default 'Asia/Seoul'`
- `venue_name text null`
- `tel text null`
- `content_id text null`
- `content_type_id text null`
- `area_code text null`
- `sigungu_code text null`
- `payload json/jsonb not null default '{}'`

제약:

- `ends_on >= starts_on` when both values exist

권장 인덱스:

- `(starts_on, ends_on)`
- `(event_kind)`
- `(content_id)`

## `feature_notice_details`

지도상의 장소/구역/경로에 붙는 공지성 feature의 공통 상세값을 저장한다. 기상특보 raw data는
weather context로 남기고, 산사태 경보, 탐방로 폐쇄, 도로 통제, 해양 고립 위험처럼 사용자가
공간적으로 회피하거나 확인해야 하는 물리적 위험은 notice feature로 승격한다.

핵심 컬럼:

- `feature_id text primary key references features(feature_id) on delete cascade`
- `notice_type text not null`
- `severity integer null`: 공통 0-5 등급. provider 원문 등급은 `payload`에 남긴다.
- `valid_start_time timestamptz null`
- `valid_end_time timestamptz null`
- `source_agency text null`
- `officer_name text null`
- `payload json/jsonb not null default '{}'`

제약:

- `severity between 0 and 5` when not null
- `valid_end_time >= valid_start_time` when both values exist

권장 인덱스:

- `(notice_type)`
- `(valid_start_time)`
- `(source_agency)`

## `feature_opening_periods`, `feature_special_days`

영업시간과 행사 운영시간은 Google Places-style DTO를 공통 자료로 삼는다. 정규 영업 구간은
`feature_opening_periods`, 날짜별 예외는 `feature_special_days`에 둔다.

`feature_opening_periods`:

- `feature_id text references features(feature_id) on delete cascade`
- `period_index integer`
- `start_weekday integer`: `0=Sunday`부터 `6=Saturday`
- `start_time text`: `HHMM`
- `duration_minutes integer`
- `timezone text not null default 'Asia/Seoul'`
- `payload json/jsonb not null default '{}'`
- `primary key(feature_id, period_index)`

`feature_special_days`:

- `feature_id text references features(feature_id) on delete cascade`
- `special_date date`
- `is_closed boolean not null`
- `periods json/jsonb null`
- `payload json/jsonb not null default '{}'`
- `primary key(feature_id, special_date)`

Portable schema는 `duration_minutes`를 기본으로 사용한다. 운영 PostgreSQL에서는 필요할 때
`btree_gist`와 `tsrange`/interval 기반 겹침 방지 제약을 추가한다.

## `feature_weather_values`

feature 기준 weather context 저장소다. 다른 provider의 관측/지수/특보 데이터도 KMA식 초단기/단기/중기 축에 맞출 수 있도록 `timeline_bucket`과 `forecast_style`을 분리한다.

unique 기준:

- `feature_id`
- `provider`
- `weather_domain`
- `forecast_style`
- `metric_key`
- `issued_at`
- `valid_at`
- `observed_at`

핵심 컬럼:

- `weather_value_key text primary key`
- `feature_id text references features(feature_id) on delete cascade`
- `provider text not null`
- `weather_domain text not null`
- `forecast_style text not null`
- `timeline_bucket text null`: `ultra_short`, `short`, `mid`
- `source_record_key text null references source_records(source_record_key) on delete set null`
- `issued_at timestamptz null`
- `valid_at timestamptz null`
- `valid_from timestamptz null`
- `valid_until timestamptz null`
- `observed_at timestamptz null`
- `metric_key text not null`
- `source_metric_key text null`
- `source_metric_name text null`
- `metric_name text null`
- `value_number numeric(14, 4) null`
- `value_text text null`
- `unit text null`
- `severity text null`
- `normalization_version text null`
- `payload json/jsonb not null default '{}'`
- `collected_at timestamptz not null`

권장 인덱스:

- `(feature_id, valid_at)`
- `(feature_id, timeline_bucket, valid_at)`
- `(provider, weather_domain)`
- `brin(valid_at)`
- `brin(valid_from)`
- `brin(valid_until)`
- `brin(observed_at)`

## `price_points`, `price_values`

가격 feature의 지점성과 가격 시계열을 분리한다.

`price_points`:

- `feature_id text primary key references features(feature_id) on delete cascade`
- `price_category text not null`
- `retention_days integer not null`

`price_values`:

- `feature_id text references price_points(feature_id) on delete cascade`
- `item_key text not null`
- `observed_at timestamptz not null`
- `value numeric(12, 2) not null`
- `currency text not null default 'KRW'`
- `payload_hash text null`
- `payload json/jsonb not null default '{}'`
- `primary key(feature_id, item_key, observed_at)`

권장 인덱스:

- `price_points(price_category)`
- `price_values(observed_at)`
- `price_values(feature_id, observed_at)`

retention은 `price_points.retention_days`를 기준으로 정리한다.

## `provider_sync_state`

provider별 cursor, 다음 실행 시각, 실패 상태를 저장한다. Dagster 실행 shell은 TripMate에 있지만 cursor 계약은 이 라이브러리가 소유한다.

primary key:

- `provider`
- `dataset_key`
- `sync_scope`

핵심 컬럼:

- `status text not null default 'active'`
- `cursor json/jsonb null`
- `last_success_at timestamptz null`
- `last_attempt_at timestamptz null`
- `next_run_after timestamptz null`
- `last_error text null`
- `last_error_at timestamptz null`
- `extra json/jsonb not null default '{}'`
- `updated_at timestamptz not null`

권장 인덱스:

- `(status, next_run_after)`

## `feature_overrides`

provider source 값과 운영 보정값의 차이를 추적한다. 보정 UI는 TripMate Admin이 제공할 수 있지만 저장 계약은 이 라이브러리를 따른다.

핵심 컬럼:

- `override_key text primary key`
- `feature_id text null references features(feature_id) on delete set null`
- `source_record_key text null references source_records(source_record_key) on delete set null`
- `provider text null`
- `dataset_key text null`
- `field_path text not null`
- `source_value json/jsonb null`
- `override_value json/jsonb null`
- `status text not null`: `active`, `inactive`, `superseded`
- `reason text null`
- `created_by text null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

권장 인덱스:

- `(feature_id, status)`
- `(provider, dataset_key)`

## `dedup_review_queue`

자동 병합이 애매한 record linkage 후보를 검수 queue로 저장한다.

핵심 컬럼:

- `review_key text primary key`
- `feature_id_a text references features(feature_id) on delete cascade`
- `feature_id_b text references features(feature_id) on delete cascade`
- `score numeric(5, 2) not null`
- `name_score numeric(5, 2) null`
- `spatial_score numeric(5, 2) null`
- `category_score numeric(5, 2) null`
- `status text not null`: `pending`, `accepted`, `rejected`, `merged`, `ignored`
- `decision_reason text null`
- `reviewed_by text null`
- `reviewed_at timestamptz null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

제약:

- `unique(feature_id_a, feature_id_b)`
- `feature_id_a <> feature_id_b`
- `score between 0 and 100`

record linkage 기본값:

- blocking: PostGIS 100m 반경
- score weight: 이름 0.45, 공간 0.35, category 0.20
- 자동 병합: 85점 이상
- 검수 queue: 65점 이상 85점 미만

## `data_integrity_violations`

provider schema drift, 필수 좌표 누락, 주소 코드 불일치 같은 검증 실패를 저장한다.

핵심 컬럼:

- `violation_key text primary key`
- `provider text not null`
- `dataset_key text not null`
- `source_record_key text null references source_records(source_record_key) on delete set null`
- `feature_id text null references features(feature_id) on delete set null`
- `violation_type text not null`
- `severity text not null`: `info`, `warning`, `error`, `critical`
- `message text not null`
- `payload json/jsonb not null default '{}'`
- `status text not null`: `open`, `acknowledged`, `resolved`, `ignored`
- `created_at timestamptz not null`
- `resolved_at timestamptz null`

권장 인덱스:

- `(status, severity)`
- `(provider, dataset_key)`

## 보존 정책

- `event`: 종료 후 20년
- `notice`: 종료 후 1년
- `weather`: 30일
- `price`: `price_points.retention_days`
- source raw payload: 재처리와 drift 감지를 위해 feature 보존 기간보다 짧게 잡지 않는다.

## 운영 원칙

- 사용자, 여행계획, POI snapshot은 TripMate 제품 도메인에서 관리한다.
- POI 순서가 필요한 TripMate 제품 table은 fractional/LexoRank 문자열과 `TEXT COLLATE "C"`를 사용한다.
- API 수집 후 정규화, DB 적재 helper, source trace, 중복 판단 계약은 이 라이브러리에 둔다.
- 실제 Dagster process, schedule, daemon, 운영 알림은 TripMate에서 실행한다.
- provider별 wrapper/adapter/gateway를 새로 만들지 않는다. 안정된 provider public client와 typed model을 직접 사용한다.
