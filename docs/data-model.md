# data-model.md — PostgreSQL + PostGIS 스키마 reference

이 문서는 `python-krtour-map` v2의 데이터 모델 reference다. 모든 컬럼/인덱스/
CHECK constraint가 여기에 박혀 있고, Alembic migration 작성 시 본 문서를 기준으로
한다. 인덱스 설계 근거는 `docs/performance.md`와 ADR을 참고한다.

## 0. 공통

- **DB**: PostgreSQL 16
- **확장**: `postgis`, `postgis_topology`, `pg_trgm`, `pgcrypto`
  → 모두 `x_extension` schema에 설치 (ADR-008). `search_path = public, x_extension`.
- **schema 분리**:
  - `feature` — feature 도메인 본체
  - `provider_sync` — source 추적과 sync state
  - `ops` — 운영 (작업 큐, 검수, 정합성 위반)
  - `x_extension` — 확장
- **시간**: 모두 `TIMESTAMPTZ` (KST 저장 권장). `created_at`, `updated_at` 표준.
- **JSON**: PostgreSQL `JSONB` 강제. `JSON` 타입 사용 금지.
- **좌표계**: WGS84 (EPSG:4326) 외 EPSG:5179 (UTM-K, meter)를 동시 보유.
  반경 검색은 항상 EPSG:5179 (ADR-012).
- **PK 명명**: `feature_id`, `source_record_key`, `job_id` 등 의미 있는 prefix.
  raw UUID 단독 사용은 `dedup_review_queue`, `import_jobs` 같은 운영 테이블에만.
- **외래키 정책**: 도메인 cascade 명시 — `source_links.feature_id ON DELETE CASCADE`,
  `feature_files.source_record_key ON DELETE SET NULL` 등.

## 1. `feature.features` (기준 테이블)

```sql
CREATE TABLE feature.features (
  feature_id                   TEXT PRIMARY KEY,
  kind                         TEXT NOT NULL,            -- FeatureKind enum
  name                         TEXT NOT NULL,
  category                     TEXT NOT NULL,            -- PlaceCategoryCode value

  -- 좌표 (양 좌표계 보유, ADR-012)
  coord                        geometry(Point, 4326),
  coord_5179                   geometry(Point, 5179)
    GENERATED ALWAYS AS (
      CASE WHEN coord IS NULL THEN NULL
           ELSE ST_Transform(coord, 5179)
      END
    ) STORED,
  geom                         geometry(Geometry, 4326), -- route LINESTRING / area MULTIPOLYGON

  -- 주소 (kraddr.base.Address 직렬화)
  address                      JSONB NOT NULL DEFAULT '{}'::jsonb,
  legal_dong_code              CHAR(10),
  road_name_code               TEXT,
  road_address_management_no   TEXT,
  admin_dong_code              CHAR(10),
  sido_code                    CHAR(2),
  sigungu_code                 CHAR(5),

  -- 표시
  urls                         JSONB NOT NULL DEFAULT '{}'::jsonb,
  marker_icon                  TEXT,
  marker_color                 TEXT,                     -- 'P-01' ~ 'P-16'

  -- 관계
  parent_feature_id            TEXT REFERENCES feature.features(feature_id) ON DELETE SET NULL,
  sibling_group_id             UUID,

  -- 상세
  detail                       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- Pydantic DETAIL_MODELS 직렬화 (ADR-018)
  raw_refs                     JSONB NOT NULL DEFAULT '[]'::jsonb,
  status                       TEXT NOT NULL DEFAULT 'active',      -- FeatureStatus enum

  created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                   TIMESTAMPTZ,

  CONSTRAINT ck_features_kind   CHECK (kind IN ('place','event','notice','price','weather','route','area')),
  CONSTRAINT ck_features_status CHECK (status IN ('draft','active','inactive','hidden','broken','deleted')),
  CONSTRAINT ck_features_coord_pair CHECK (
    coord IS NULL OR (
      ST_X(coord) BETWEEN 124.0 AND 132.0 AND ST_Y(coord) BETWEEN 33.0 AND 39.5
    )
  )
);

-- 표준 인덱스 (성능 설계 — docs/performance.md 참고)
CREATE INDEX idx_features_coord_gist        ON feature.features USING GIST (coord)       WHERE deleted_at IS NULL;
CREATE INDEX idx_features_coord_5179_gist   ON feature.features USING GIST (coord_5179)  WHERE deleted_at IS NULL;
CREATE INDEX idx_features_geom_gist         ON feature.features USING GIST (geom)        WHERE deleted_at IS NULL AND geom IS NOT NULL;
CREATE INDEX idx_features_kind_category     ON feature.features (kind, category)         WHERE deleted_at IS NULL;
CREATE INDEX idx_features_status_updated    ON feature.features (status, updated_at);
CREATE INDEX idx_features_legal_dong_code   ON feature.features (legal_dong_code);
CREATE INDEX idx_features_sigungu           ON feature.features (sigungu_code, kind)     WHERE deleted_at IS NULL;
CREATE INDEX idx_features_parent            ON feature.features (parent_feature_id)      WHERE parent_feature_id IS NOT NULL;
CREATE INDEX idx_features_sibling           ON feature.features (sibling_group_id)       WHERE sibling_group_id IS NOT NULL;
CREATE INDEX idx_features_name_trgm         ON feature.features USING GIN (name x_extension.gin_trgm_ops);

-- 부분 인덱스 (자주 쓰는 필터)
CREATE INDEX idx_features_event_end
  ON feature.features (((detail->>'ends_on')::date))
  WHERE kind='event' AND deleted_at IS NULL;
CREATE INDEX idx_features_notice_valid
  ON feature.features (((detail->>'valid_end_time')::timestamptz))
  WHERE kind='notice' AND deleted_at IS NULL;
```

**인덱스 설계 근거**:
- `coord_gist` — 응답 직렬화용 좌표 추출, in-bounds 빠른 필터링.
- `coord_5179_gist` — 반경 검색 핵심 인덱스 (ADR-012).
- `geom_gist` — route LINESTRING / area MULTIPOLYGON 교차/포함 검색.
- `kind_category WHERE deleted_at IS NULL` — `/features/in-bounds` 주된 필터.
- `name_trgm GIN` — pg_trgm 부분 문자열 검색 (검색 페이지).
- 부분 인덱스 `(event_end)`, `(notice_valid)` — 진행중/유효 필터를 자주 사용.

## 2. `provider_sync.source_records`

```sql
CREATE TABLE provider_sync.source_records (
  source_record_key      TEXT PRIMARY KEY,            -- make_source_record_key(...)
  provider               TEXT NOT NULL,               -- canonical provider name
  dataset_key            TEXT NOT NULL,
  source_entity_type     TEXT NOT NULL,
  source_entity_id       TEXT NOT NULL,
  source_version         TEXT,
  raw_name               TEXT,
  raw_address            TEXT,
  raw_longitude          NUMERIC(12,8),
  raw_latitude           NUMERIC(12,8),
  raw_data               JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_payload_hash       TEXT NOT NULL,
  fetched_at             TIMESTAMPTZ NOT NULL,
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at             TIMESTAMPTZ,

  CONSTRAINT uq_source_records UNIQUE (provider, dataset_key, source_entity_type, source_entity_id, raw_payload_hash)
);

CREATE INDEX idx_source_records_provider_dataset_entity
  ON provider_sync.source_records (provider, dataset_key, source_entity_type, source_entity_id);
CREATE INDEX idx_source_records_imported_at_brin
  ON provider_sync.source_records USING BRIN (imported_at);
CREATE INDEX idx_source_records_fetched_at_brin
  ON provider_sync.source_records USING BRIN (fetched_at);
CREATE INDEX idx_source_records_expires_at
  ON provider_sync.source_records (expires_at) WHERE expires_at IS NOT NULL;
```

**인덱스 설계**:
- BRIN on `imported_at/fetched_at` — 적재 시계열 누적 패턴에 최적, 디스크 절약.
- partial on `expires_at IS NOT NULL` — purge job에서만 스캔.

## 3. `provider_sync.source_links`

```sql
CREATE TABLE provider_sync.source_links (
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  source_record_key    TEXT NOT NULL REFERENCES provider_sync.source_records(source_record_key) ON DELETE CASCADE,
  source_role          TEXT NOT NULL,                 -- SourceRole enum
  match_method         TEXT NOT NULL,                 -- 'natural_key', 'reverse_geocode', 'place_phone_search', ...
  confidence           NUMERIC(5,2) NOT NULL,
  is_primary_source    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (feature_id, source_record_key),
  CONSTRAINT ck_source_links_confidence CHECK (confidence BETWEEN 0 AND 100),
  CONSTRAINT ck_source_links_role CHECK (source_role IN (
    'base_address','base_coordinate','primary','enrichment','correction',
    'duplicate_candidate','media','weather_context'
  ))
);

CREATE INDEX idx_source_links_record       ON provider_sync.source_links (source_record_key);
CREATE INDEX idx_source_links_role         ON provider_sync.source_links (source_role);
CREATE INDEX idx_source_links_primary      ON provider_sync.source_links (feature_id) WHERE is_primary_source;
```

## 4. `provider_sync.provider_sync_state`

```sql
CREATE TABLE provider_sync.provider_sync_state (
  provider                       TEXT NOT NULL,
  dataset_key                    TEXT NOT NULL,
  sync_scope                     TEXT NOT NULL DEFAULT 'global',
  status                         TEXT NOT NULL DEFAULT 'active',  -- active, paused, error
  cursor                         JSONB,
  metadata_hash                  TEXT,
  last_observed_source_version   TEXT,
  last_success_at                TIMESTAMPTZ,
  last_attempt_at                TIMESTAMPTZ,
  last_full_scan_at              TIMESTAMPTZ,
  next_run_after                 TIMESTAMPTZ,
  last_error                     TEXT,
  last_error_at                  TIMESTAMPTZ,
  extra                          JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (provider, dataset_key, sync_scope)
);

CREATE INDEX idx_sync_state_next_run ON provider_sync.provider_sync_state (next_run_after) WHERE status='active';
```

## 5. `feature.feature_files`

```sql
CREATE TABLE feature.feature_files (
  file_id              TEXT PRIMARY KEY,
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  file_type            TEXT NOT NULL,                 -- image, video, audio, document, file
  storage_backend      TEXT NOT NULL DEFAULT 's3',    -- 's3' (RustFS 포함) — backend swap 가능 (ADR-015)
  bucket               TEXT NOT NULL,
  object_key           TEXT NOT NULL,
  source_url           TEXT,
  public_url           TEXT,
  content_type         TEXT,
  byte_size            BIGINT,
  checksum_sha256      CHAR(64),
  width                INTEGER,
  height               INTEGER,
  role                 TEXT NOT NULL DEFAULT 'gallery', -- primary, thumbnail, gallery
  display_order        INTEGER NOT NULL DEFAULT 0,
  alt_text             TEXT,
  provider             TEXT,
  dataset_key          TEXT,
  source_record_key    TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_feature_files_storage UNIQUE (storage_backend, bucket, object_key),
  CONSTRAINT ck_feature_files_file_type CHECK (file_type IN ('image','video','audio','document','file')),
  CONSTRAINT ck_feature_files_display_order CHECK (display_order >= 0),
  CONSTRAINT ck_feature_files_byte_size CHECK (byte_size IS NULL OR byte_size >= 0),
  CONSTRAINT ck_feature_files_width CHECK (width IS NULL OR width > 0),
  CONSTRAINT ck_feature_files_height CHECK (height IS NULL OR height > 0)
);

CREATE INDEX idx_feature_files_feature_type   ON feature.feature_files (feature_id, file_type);
CREATE INDEX idx_feature_files_feature_order  ON feature.feature_files (feature_id, display_order);
CREATE INDEX idx_feature_files_provider       ON feature.feature_files (provider, dataset_key) WHERE provider IS NOT NULL;
```

## 6. kind별 detail 테이블

### 6.1 `feature.feature_place_details`

```sql
CREATE TABLE feature.feature_place_details (
  feature_id              TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  place_kind              TEXT NOT NULL DEFAULT 'place',
  phones                  JSONB NOT NULL DEFAULT '[]'::jsonb,
  reviews_link            JSONB NOT NULL DEFAULT '{}'::jsonb,
  business_hours          JSONB,
  facility_info           JSONB NOT NULL DEFAULT '{}'::jsonb,
  license_date            DATE,
  biz_number              TEXT,
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT ck_place_phones_len CHECK (jsonb_typeof(phones)='array' AND jsonb_array_length(phones) <= 3)
);

CREATE INDEX idx_place_kind       ON feature.feature_place_details (place_kind);
CREATE INDEX idx_place_biz_number ON feature.feature_place_details (biz_number) WHERE biz_number IS NOT NULL;
```

### 6.2 `feature.feature_event_details`

```sql
CREATE TABLE feature.feature_event_details (
  feature_id        TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  event_kind        TEXT NOT NULL DEFAULT 'festival',
  starts_on         DATE,
  ends_on           DATE,
  timezone          TEXT NOT NULL DEFAULT 'Asia/Seoul',
  venue_name        TEXT,
  tel               TEXT,
  content_id        TEXT,
  content_type_id   TEXT,
  area_code         TEXT,
  sigungu_code      TEXT,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT ck_event_dates CHECK (starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on)
);

CREATE INDEX idx_event_dates       ON feature.feature_event_details (starts_on, ends_on);
CREATE INDEX idx_event_kind        ON feature.feature_event_details (event_kind);
CREATE INDEX idx_event_content_id  ON feature.feature_event_details (content_id) WHERE content_id IS NOT NULL;
```

### 6.3 `feature.feature_area_details`

```sql
CREATE TABLE feature.feature_area_details (
  feature_id              TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  area_kind               TEXT NOT NULL DEFAULT 'area',
  boundary_source         TEXT,
  area_square_meters      NUMERIC(18,4),
  regulation_scope        TEXT,
  administrative_office   TEXT,
  description             TEXT,
  geometry                JSONB,                      -- geom 컬럼은 features.geom; 본 컬럼은 부가
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_area_kind            ON feature.feature_area_details (area_kind);
CREATE INDEX idx_area_boundary_source ON feature.feature_area_details (boundary_source) WHERE boundary_source IS NOT NULL;
```

### 6.4 `feature.feature_route_details`

```sql
CREATE TABLE feature.feature_route_details (
  feature_id                  TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  route_type                  TEXT NOT NULL DEFAULT 'route',
  geometry_source             TEXT,
  geometry_status             TEXT,                   -- 'provided', 'missing_route_geometry'
  total_distance_meters       NUMERIC(14,2),
  expected_duration_minutes   INTEGER,
  difficulty                  TEXT,
  begin_name                  TEXT,
  begin_address               TEXT,
  end_name                    TEXT,
  end_address                 TEXT,
  payload                     JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT ck_route_distance CHECK (total_distance_meters IS NULL OR total_distance_meters >= 0),
  CONSTRAINT ck_route_duration CHECK (expected_duration_minutes IS NULL OR expected_duration_minutes > 0)
);

CREATE INDEX idx_route_type            ON feature.feature_route_details (route_type);
CREATE INDEX idx_route_geometry_status ON feature.feature_route_details (geometry_status);
```

### 6.5 `feature.feature_notice_details`

```sql
CREATE TABLE feature.feature_notice_details (
  feature_id          TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  notice_type         TEXT NOT NULL,
  severity            SMALLINT,
  valid_start_time    TIMESTAMPTZ,
  valid_end_time      TIMESTAMPTZ,
  source_agency       TEXT,
  officer_name        TEXT,
  payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT ck_notice_severity CHECK (severity IS NULL OR severity BETWEEN 0 AND 5),
  CONSTRAINT ck_notice_time_range CHECK (valid_start_time IS NULL OR valid_end_time IS NULL OR valid_end_time >= valid_start_time)
);

CREATE INDEX idx_notice_type         ON feature.feature_notice_details (notice_type);
CREATE INDEX idx_notice_type_valid   ON feature.feature_notice_details (notice_type, valid_start_time, valid_end_time);
CREATE INDEX idx_notice_valid_start  ON feature.feature_notice_details (valid_start_time);
CREATE INDEX idx_notice_source_agency ON feature.feature_notice_details (source_agency) WHERE source_agency IS NOT NULL;
```

## 7. 영업시간

```sql
CREATE TABLE feature.feature_opening_periods (
  feature_id        TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  period_index      SMALLINT NOT NULL,
  start_weekday     SMALLINT NOT NULL,                -- 0=Sunday (Google Places)
  start_time        CHAR(4) NOT NULL,                 -- 'HHMM'
  duration_minutes  INTEGER NOT NULL,
  timezone          TEXT NOT NULL DEFAULT 'Asia/Seoul',
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, period_index),
  CONSTRAINT ck_opening_weekday CHECK (start_weekday BETWEEN 0 AND 6),
  CONSTRAINT ck_opening_time CHECK (start_time ~ '^([01]\d|2[0-3])[0-5]\d$'),
  CONSTRAINT ck_opening_duration CHECK (duration_minutes > 0 AND duration_minutes <= 10080)
);

CREATE INDEX idx_opening_start ON feature.feature_opening_periods (start_weekday, start_time);

CREATE TABLE feature.feature_special_days (
  feature_id     TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  special_date   DATE NOT NULL,
  is_closed      BOOLEAN NOT NULL,
  periods        JSONB,
  payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, special_date)
);

CREATE INDEX idx_special_date ON feature.feature_special_days (special_date);
```

## 8. weather / price

### 8.1 `feature.feature_weather_values`

```sql
CREATE TABLE feature.feature_weather_values (
  weather_value_key       TEXT PRIMARY KEY,           -- make_weather_value_key(...)
  feature_id              TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider                TEXT NOT NULL,
  weather_domain          TEXT NOT NULL,              -- WeatherDomain enum
  forecast_style          TEXT NOT NULL,              -- ForecastStyle enum
  timeline_bucket         TEXT,                       -- ultra_short, short, mid (분류)
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
    feature_id, provider, weather_domain, forecast_style, metric_key, issued_at, valid_at, observed_at
  )
);

CREATE INDEX idx_weather_feature_metric_time
  ON feature.feature_weather_values (feature_id, metric_key, valid_at DESC NULLS LAST);
CREATE INDEX idx_weather_provider_domain
  ON feature.feature_weather_values (provider, weather_domain, valid_at DESC NULLS LAST);
CREATE INDEX idx_weather_valid_at_brin
  ON feature.feature_weather_values USING BRIN (valid_at);
CREATE INDEX idx_weather_collected_at_brin
  ON feature.feature_weather_values USING BRIN (collected_at);
```

**인덱스 설계**:
- 시계열 누적 → BRIN.
- `feature_id + metric_key + valid_at DESC` — `build_weather_card`의 핵심
  쿼리 (각 metric별 최신값).
- `provider + weather_domain + valid_at DESC` — admin 검증.

### 8.2 `feature.price_points` / `feature.price_values`

```sql
CREATE TABLE feature.price_points (
  feature_id       TEXT PRIMARY KEY REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  price_category   TEXT NOT NULL,                     -- 'fuel', 'admission', 'parking', ...
  retention_days   INTEGER NOT NULL DEFAULT 3650,
  CONSTRAINT ck_price_points_retention CHECK (retention_days >= 1)
);

CREATE INDEX idx_price_points_category ON feature.price_points (price_category);

CREATE TABLE feature.price_values (
  feature_id     TEXT NOT NULL REFERENCES feature.price_points(feature_id) ON DELETE CASCADE,
  item_key       TEXT NOT NULL,                       -- 'gasoline', 'diesel', 'lpg', ...
  observed_at    TIMESTAMPTZ NOT NULL,
  value          NUMERIC(12,2) NOT NULL,
  currency       CHAR(3) NOT NULL DEFAULT 'KRW',
  payload_hash   TEXT,
  payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (feature_id, item_key, observed_at)
);

CREATE INDEX idx_price_values_observed_at_brin
  ON feature.price_values USING BRIN (observed_at);
CREATE INDEX idx_price_values_item_observed
  ON feature.price_values (item_key, observed_at DESC);
```

**인덱스 설계**: BRIN on `observed_at` (시계열 누적), `item_key + observed_at
DESC` (특정 종목 최신 가격 조회).

## 9. 운영 보조 (`ops` schema)

### 9.1 `ops.import_jobs` (ADR-011)

```sql
CREATE TABLE ops.import_jobs (
  job_id            UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  kind              TEXT NOT NULL,                    -- 'visitkorea_festival_full_scan', 'mois_license_full_update', ...
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  state             TEXT NOT NULL DEFAULT 'queued',   -- queued, running, done, failed, cancelled
  progress          INTEGER NOT NULL DEFAULT 0,       -- 0~100
  current_stage     TEXT,
  source_checksum   TEXT,
  error_message     TEXT,
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  heartbeat_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_import_jobs_state CHECK (state IN ('queued','running','done','failed','cancelled')),
  CONSTRAINT ck_import_jobs_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX idx_import_jobs_state         ON ops.import_jobs (state, created_at);
CREATE INDEX idx_import_jobs_kind_state    ON ops.import_jobs (kind, state, created_at DESC);
CREATE INDEX idx_import_jobs_heartbeat     ON ops.import_jobs (heartbeat_at) WHERE state='running';
```

### 9.2 `ops.dedup_review_queue` (ADR-016)

```sql
CREATE TABLE ops.dedup_review_queue (
  review_key         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id_a       TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  feature_id_b       TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  total_score        NUMERIC(5,2) NOT NULL,
  name_score         NUMERIC(5,2) NOT NULL,
  spatial_score      NUMERIC(5,2) NOT NULL,
  category_score     NUMERIC(5,2) NOT NULL,
  status             TEXT NOT NULL DEFAULT 'pending', -- pending, accepted, rejected, merged, ignored
  decision_reason    TEXT,
  reviewed_by        TEXT,
  reviewed_at        TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_dedup_pair UNIQUE (feature_id_a, feature_id_b),
  CONSTRAINT ck_dedup_status CHECK (status IN ('pending','accepted','rejected','merged','ignored')),
  CONSTRAINT ck_dedup_scores CHECK (
    total_score BETWEEN 0 AND 100 AND
    name_score BETWEEN 0 AND 100 AND
    spatial_score BETWEEN 0 AND 100 AND
    category_score BETWEEN 0 AND 100
  )
);

CREATE INDEX idx_dedup_status_score ON ops.dedup_review_queue (status, total_score DESC);
```

### 9.3 `ops.feature_overrides`

```sql
CREATE TABLE ops.feature_overrides (
  override_key         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  source_record_key    TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  field_path           TEXT NOT NULL,                 -- 'name', 'detail.phones[0]', ...
  source_value         JSONB,
  override_value       JSONB,
  status               TEXT NOT NULL DEFAULT 'active', -- active, inactive, superseded
  reason               TEXT,
  created_by           TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_overrides_status CHECK (status IN ('active','inactive','superseded'))
);

CREATE INDEX idx_overrides_feature  ON ops.feature_overrides (feature_id, status);
CREATE INDEX idx_overrides_field    ON ops.feature_overrides (field_path);
```

### 9.4 `ops.feature_merge_history`

```sql
CREATE TABLE ops.feature_merge_history (
  history_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  loser_id      TEXT NOT NULL,                        -- FK 안 검 (loser는 이미 삭제됨)
  master_id     TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  score         NUMERIC(5,2) NOT NULL,
  merged_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  reason        TEXT,
  reviewer      TEXT
);

CREATE INDEX idx_merge_history_master  ON ops.feature_merge_history (master_id);
CREATE INDEX idx_merge_history_merged_at_brin ON ops.feature_merge_history USING BRIN (merged_at);
```

### 9.5 `ops.data_integrity_violations`

```sql
CREATE TABLE ops.data_integrity_violations (
  violation_key       UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  provider            TEXT,
  dataset_key         TEXT,
  source_record_key   TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  feature_id          TEXT REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  violation_type      TEXT NOT NULL,                  -- 'F1_coord_outside_bjd', 'F4_provider_coord_drift', ...
  severity            TEXT NOT NULL,                  -- info, warning, error, critical
  message             TEXT NOT NULL,
  payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  status              TEXT NOT NULL DEFAULT 'open',
  detected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at         TIMESTAMPTZ,
  CONSTRAINT ck_violations_severity CHECK (severity IN ('info','warning','error','critical')),
  CONSTRAINT ck_violations_status   CHECK (status IN ('open','acknowledged','resolved','ignored'))
);

CREATE INDEX idx_violations_type_status ON ops.data_integrity_violations (violation_type, status);
CREATE INDEX idx_violations_feature     ON ops.data_integrity_violations (feature_id) WHERE feature_id IS NOT NULL;
CREATE INDEX idx_violations_detected_brin ON ops.data_integrity_violations USING BRIN (detected_at);
```

### 9.6 `ops.api_call_log` (옵션)

```sql
CREATE TABLE ops.api_call_log (
  id            BIGSERIAL PRIMARY KEY,
  provider      TEXT NOT NULL,
  endpoint      TEXT NOT NULL,
  status        SMALLINT,
  latency_ms    INTEGER,
  error         TEXT,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_api_call_occurred_brin ON ops.api_call_log USING BRIN (occurred_at);
CREATE INDEX idx_api_call_provider_time ON ops.api_call_log (provider, occurred_at DESC);
```

## 10. 보관 정책 (ADR-017) → purge 작업

```sql
-- weather_values: +30일 + 참조 trip 0건 (참조 검사는 TripMate trip_pois 조인)
DELETE FROM feature.feature_weather_values WHERE valid_at < now() - interval '30 days';

-- notice: 종료일 또는 발표일 +1년 (kind='notice' AND valid_end_time < now() - 1y)
DELETE FROM feature.feature_notice_details d USING feature.features f
WHERE d.feature_id=f.feature_id
  AND f.kind='notice' AND d.valid_end_time < now() - interval '1 year';

-- event: 종료일 +20년
DELETE FROM feature.feature_event_details d USING feature.features f
WHERE d.feature_id=f.feature_id
  AND f.kind='event' AND d.ends_on < (now() - interval '20 years')::date;

-- source_records: 대응 feature 보존 기간 이상 → purge cascade 자동
-- (source_records는 source_links로 cascade; orphan만 별도 purge)
DELETE FROM provider_sync.source_records sr
WHERE NOT EXISTS (SELECT 1 FROM provider_sync.source_links sl WHERE sl.source_record_key=sr.source_record_key)
  AND (sr.expires_at IS NULL OR sr.expires_at < now() - interval '30 days');
```

이 SQL은 Dagster purge asset에서 실행한다. `infra/purge_repo.py`에 상수로 박는다.

## 11. ID 생성 규약 (다른 곳에서도 인용)

```python
make_feature_id(*, bjd_code: str | None, kind: FeatureKind, category: str,
                source_type: str, source_natural_key: str,
                content_hash: str | None = None) -> str
# 포맷: f_{bjd_code or 'global'}_{kind.value[0]}_{sha1(input)[:16]}
# input: f"{bjd_code or 'global'}|{kind.value}|{category}|{source_type}|{source_natural_key}|{content_hash or ''}"

make_source_record_key(*, provider: str, dataset_key: str,
                       source_entity_type: str, source_entity_id: str,
                       raw_payload_hash: str) -> str
# 포맷: sr_{sha1(input)[:20]}

make_payload_hash(data: Any, *, length: int = 32) -> str
# canonical_json(data) → sha256 → [:length]

make_weather_value_key(value: WeatherValue) -> str
# 포맷: wv_{sha1(value.identity()_tuple)[:20]}
```

## 12. 마이그레이션 가이드

- 모든 schema 변경은 Alembic migration + ADR 동반.
- 마이그레이션은 backward-compatible 우선:
  1. 컬럼 추가 (nullable + default)
  2. 백필 (BRIN 인덱스 영향 없음 — `UPDATE` 시 batched)
  3. nullability tighten (옵션)
- 인덱스 추가는 `CREATE INDEX CONCURRENTLY`로 (운영 중 lock 없음).
- 인덱스 삭제는 `DROP INDEX CONCURRENTLY IF EXISTS`.
- 컬럼 타입 변경은 `USING` cast + downtime 또는 새 컬럼 + 백필 + swap.
