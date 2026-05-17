# Postgres 스키마 기준

이 문서는 TripMate DB 구현이 따라야 할 최소 계약입니다. 실제 Alembic migration은 TripMate 저장소에서 관리합니다.

## `features`

공통 feature table입니다.

필수 컬럼:

- `feature_id text primary key`
- `kind text not null`
- `name text not null`
- `bjd_code text null`
- `coord geometry(point, 4326) not null`
- `geom geometry(geometry, 4326) null`
- `address_road text null`
- `address_jibun text null`
- `category text not null`
- `parent_feature_id text null references features(feature_id) on delete set null`
- `sibling_group_id uuid null`
- `urls jsonb not null default '{}'`
- `marker_icon text not null`
- `marker_color text not null`
- `detail jsonb null`
- `raw_refs jsonb not null default '[]'`
- `status text not null default 'active'`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

권장 인덱스:

- `gist(coord)`
- `gist(geom)`
- `(kind, category)`
- `(bjd_code)`
- `(parent_feature_id)`
- `gin(name gin_trgm_ops)`

## `source_records`

원천 row를 보존합니다.

unique 기준:

- `provider`
- `dataset_key`
- `source_entity_type`
- `source_entity_id`
- `raw_payload_hash`

필수 컬럼:

- `source_record_key text primary key`
- `provider text not null`
- `dataset_key text not null`
- `source_entity_type text not null`
- `source_entity_id text not null`
- `raw_payload_hash text not null`
- `raw_name text null`
- `raw_address text null`
- `raw_longitude numeric(12, 8) null`
- `raw_latitude numeric(12, 8) null`
- `raw_data jsonb null`
- `fetched_at timestamptz null`
- `imported_at timestamptz not null`
- `expires_at timestamptz null`

## `feature_source_links`

feature와 source record의 관계를 저장합니다.

필수 컬럼:

- `feature_id text references features(feature_id) on delete cascade`
- `source_record_key text references source_records(source_record_key) on delete cascade`
- `source_role text not null`
- `match_method text not null`
- `confidence integer not null`
- `is_primary_source boolean not null default false`
- `created_at timestamptz not null`

제약:

- `primary key(feature_id, source_record_key)`
- `confidence between 0 and 100`
- `source_role in ('base_address', 'base_coordinate', 'primary', 'enrichment', 'correction', 'duplicate_candidate', 'media', 'weather_context')`

## `feature_weather_values`

feature 기준 weather context 저장소입니다.

unique 기준:

- `feature_id`
- `provider`
- `weather_domain`
- `forecast_style`
- `metric_key`
- `issued_at`
- `valid_at`
- `observed_at`

필수 컬럼:

- `id uuid primary key`
- `feature_id text references features(feature_id) on delete cascade`
- `provider text not null`
- `weather_domain text not null`
- `forecast_style text not null`
- `metric_key text not null`
- `issued_at timestamptz null`
- `valid_at timestamptz null`
- `observed_at timestamptz null`
- `metric_name text null`
- `value_number numeric(14, 4) null`
- `value_text text null`
- `unit text null`
- `severity text null`
- `payload jsonb not null default '{}'`
- `source_record_key text null references source_records(source_record_key) on delete set null`
- `collected_at timestamptz not null`

권장 인덱스:

- `(feature_id, valid_at)`
- `(provider, weather_domain)`
- `brin(valid_at)`
- `brin(observed_at)`

## `price_points`, `price_values`

가격 feature는 지점과 가격 시계열을 분리합니다.

`price_points`:

- `feature_id text primary key references features(feature_id) on delete cascade`
- `price_category text not null`
- `retention_days integer not null`

`price_values`:

- `feature_id text references price_points(feature_id) on delete cascade`
- `item_key text not null`
- `observed_at timestamptz not null`
- `value numeric(12, 2) not null`
- `currency char(3) not null default 'KRW'`
- `payload_hash text null`
- `primary key(feature_id, item_key, observed_at)`

`price_values.observed_at`에는 BRIN index를 둡니다. retention은 `price_points.retention_days`를 기준으로 정리합니다.

## `provider_sync_state`

provider별 cursor와 실패 상태입니다.

unique 기준:

- `provider`
- `dataset_key`
- `sync_scope`

필수 컬럼:

- `provider text not null`
- `dataset_key text not null`
- `sync_scope text not null default 'global'`
- `status text not null default 'active'`
- `cursor jsonb null`
- `last_success_at timestamptz null`
- `last_attempt_at timestamptz null`
- `next_run_after timestamptz null`
- `last_error text null`
- `last_error_at timestamptz null`
- `extra jsonb not null default '{}'`
- `updated_at timestamptz not null`

## 운영 원칙

- PostGIS와 `pg_trgm` extension을 활성화합니다.
- LexoRank/fractional indexing이 필요한 TripMate POI sort key는 `TEXT COLLATE "C"`를 사용합니다.
- feature 삭제는 기본 soft delete입니다. TripMate POI snapshot은 유지하고 feature link만 끊습니다.
- 공공 provider raw payload는 재처리와 schema drift 감지를 위해 보존할 수 있습니다.
- 상업 provider의 장기 원문 보존은 provider 약관을 별도 확인한 뒤 허용 필드만 저장합니다.
