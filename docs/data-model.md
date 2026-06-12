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
  모든 feature와 관련 데이터는 API에서 KST aware `last_updated_at`을 반환할 수
  있어야 한다. 기존 row에 `updated_at`이 없으면 `imported_at`/`observed_at`/
  `valid_at`으로 임시 계산하되, 운영 API 확장 시 `updated_at` 추가를 우선 검토한다.
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
  coord_precision_digits       SMALLINT,               -- 원천 좌표 precision, coord 있으면 3~8
  coord_5179                   geometry(Point, 5179)
    GENERATED ALWAYS AS (
      CASE WHEN coord IS NULL THEN NULL
           ELSE ST_Transform(coord, 5179)
      END
    ) STORED,
  geom                         geometry(Geometry, 4326), -- route LINESTRING / area MULTIPOLYGON

  -- 주소 (krtour.map.dto.Address 직렬화)
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

  -- effective row 출처/version (provider reload vs 사용자 요청)
  data_origin                  TEXT NOT NULL DEFAULT 'provider',    -- provider / user_request
  data_version                 INTEGER NOT NULL DEFAULT 0,          -- provider=0, user_request=1
  user_change_kind             TEXT,                                -- add / update / delete
  user_change_status           TEXT,                                -- pending / applied / rejected
  user_change_request_id       UUID,
  user_deleted_at              TIMESTAMPTZ,
  user_deleted_by              TEXT,
  user_change_reason           TEXT,

  created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                   TIMESTAMPTZ,

  CONSTRAINT ck_features_kind   CHECK (kind IN ('place','event','notice','price','weather','route','area')),
  CONSTRAINT ck_features_status CHECK (status IN ('draft','active','inactive','hidden','broken','deleted')),
  CONSTRAINT ck_features_data_origin CHECK (data_origin IN ('provider','user_request')),
  CONSTRAINT ck_features_data_version CHECK (data_version >= 0),
  CONSTRAINT ck_features_user_change_kind CHECK (
    user_change_kind IS NULL OR user_change_kind IN ('add','update','delete')
  ),
  CONSTRAINT ck_features_user_change_status CHECK (
    user_change_status IS NULL OR user_change_status IN ('pending','applied','rejected')
  ),
  CONSTRAINT ck_features_coord_pair CHECK (
    coord IS NULL OR (
      ST_X(coord) BETWEEN 124.0 AND 132.0 AND ST_Y(coord) BETWEEN 33.0 AND 39.5
    )
  ),
  CONSTRAINT ck_features_coord_precision CHECK (
    (coord IS NULL AND coord_precision_digits IS NULL)
    OR (coord IS NOT NULL AND coord_precision_digits BETWEEN 3 AND 8)
  )
);

CREATE FUNCTION feature.set_feature_coord_precision() RETURNS trigger AS $$
BEGIN
  IF NEW.coord IS NULL THEN
    NEW.coord_precision_digits := NULL;
  ELSIF NEW.coord_precision_digits IS NULL THEN
    NEW.coord_precision_digits := 6;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_features_coord_precision
  BEFORE INSERT OR UPDATE OF coord, coord_precision_digits
  ON feature.features
  FOR EACH ROW
  EXECUTE FUNCTION feature.set_feature_coord_precision();

-- 표준 인덱스 (성능 설계 — docs/performance.md 참고)
CREATE INDEX idx_features_coord_gist        ON feature.features USING GIST (coord)       WHERE deleted_at IS NULL;
CREATE INDEX idx_features_coord_5179_gist   ON feature.features USING GIST (coord_5179)  WHERE deleted_at IS NULL;
CREATE INDEX idx_features_geom_gist         ON feature.features USING GIST (geom)        WHERE deleted_at IS NULL AND geom IS NOT NULL;
CREATE INDEX idx_features_kind_category     ON feature.features (kind, category)         WHERE deleted_at IS NULL;
CREATE INDEX idx_features_status_updated    ON feature.features (status, updated_at);
CREATE INDEX idx_features_dedup_refresh_keyset
  ON feature.features (updated_at DESC, feature_id DESC)
  WHERE deleted_at IS NULL AND status='active' AND coord IS NOT NULL;
CREATE INDEX idx_features_legal_dong_code   ON feature.features (legal_dong_code);
CREATE INDEX idx_features_sigungu           ON feature.features (sigungu_code, kind)     WHERE deleted_at IS NULL;
CREATE INDEX idx_features_parent            ON feature.features (parent_feature_id)      WHERE parent_feature_id IS NOT NULL;
CREATE INDEX idx_features_sibling           ON feature.features (sibling_group_id)       WHERE sibling_group_id IS NOT NULL;
CREATE INDEX idx_features_name_trgm         ON feature.features USING GIN (name x_extension.gin_trgm_ops);
CREATE INDEX idx_features_data_origin       ON feature.features (data_origin, data_version);
CREATE INDEX idx_features_user_deleted      ON feature.features (user_deleted_at)        WHERE user_deleted_at IS NOT NULL;

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
- `coord_precision_digits` — provider 원천 좌표 신뢰도/정밀도 신호. `Feature` DTO와
  trigger가 coord 보유 row의 기본값을 6으로 맞추고, coord 제거 시 NULL로 정리한다.
- `data_origin`/`data_version` — provider 재적재 snapshot은 version 0,
  사용자 요청 추가·수정·삭제는 version 1이다. `feature.features`는 조회용 effective
  row이고, snapshot 보존은 `feature.feature_versions`가 맡는다.
- `user_deleted_at` — 사용자 요청 soft delete marker. provider 재적재나 snapshot 미포함
  정리 작업은 이 값이 있는 row를 되살리지 않는다.
- `geom_gist` — route LINESTRING / area MULTIPOLYGON 교차/포함 검색.
- `kind_category WHERE deleted_at IS NULL` — `/features/in-bounds` 주된 필터.
- `idx_features_dedup_refresh_keyset` — dedup refresh가 `(updated_at, feature_id)`
  keyset으로 진행하며 같은 앞부분만 반복 조회하지 않도록 한다.
- `name_trgm GIN` — pg_trgm 부분 문자열 검색 (검색 페이지).
- 부분 인덱스 `(event_end)`, `(notice_valid)` — 진행중/유효 필터를 자주 사용.

### 1.1 `feature.feature_versions`

provider 적재와 사용자 요청 변경 snapshot을 feature별 version으로 보존한다.
`feature.features`는 조회용 effective row다. provider 재적재는 version 0 snapshot을
갱신하고, 사용자 요청이 적용되면 version 1 snapshot을 갱신한다.

```sql
CREATE TABLE feature.feature_versions (
  feature_id   TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  version      INTEGER NOT NULL,
  origin       TEXT NOT NULL,          -- provider / user_request
  change_kind  TEXT NOT NULL,          -- load / add / update / delete
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id   UUID,
  created_by   TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (feature_id, version),
  CONSTRAINT ck_feature_versions_version CHECK (version >= 0),
  CONSTRAINT ck_feature_versions_origin CHECK (origin IN ('provider','user_request')),
  CONSTRAINT ck_feature_versions_change_kind CHECK (
    change_kind IN ('load','add','update','delete')
  )
);

CREATE INDEX idx_feature_versions_request
  ON feature.feature_versions (request_id);
```

우선순위 규칙:

- provider reload는 `version=0`, `origin='provider'`, `change_kind='load'`.
- 사용자 추가·수정·삭제는 `version=1`, `origin='user_request'`.
- 같은 `feature_id`에서 version 1이 effective row면 provider reload가 version 0
  snapshot만 갱신하고 effective row의 사용자 값을 덮지 않는다.
- 사용자 요청 삭제는 version 1 `change_kind='delete'`와 `feature.features` soft delete
  marker를 함께 남긴다.

### 1.2 `feature.curated_*` (테마형 overlay, T-223c-1/T-223c-2 구현)

테마형 큐레이션은 `feature.features`를 복제하지 않고 overlay로 관리한다. 정본 계약은
[`docs/curated-features.md`](curated-features.md)다. DB schema는 `feature`에 둔다.
T-223c-1에서 Alembic `0025_curated_features`로 4개 테이블과 1차 seed metadata/rule을
추가했고, T-223c-2에서 Alembic `0026_curated_copy_snapshots`로 TripMate copy snapshot
cache를 추가했다.

테이블:

- `feature.curated_themes` — `theme_slug`, `theme_name`, `theme_group`,
  `default_curated`, `visibility`, 표시 metadata.
- `feature.curated_sources` — `provider`, `dataset_key`, `source_name`,
  `source_url`, `source_kind`, `license`, `update_cycle`,
  `last_source_modified_at`, `last_checked_at`, `next_expected_at`, `row_count`,
  `freshness_note`, `provider_status`, source metadata.
- `feature.curated_source_rules` — provider/dataset/category/place_kind 조건을
  `candidate`/`curated`/`ignore` 기본 action으로 매핑한다.
- `feature.curated_features` — `theme_id + feature_id` overlay 본체. 상태와
  TripMate 복사 정책을 저장한다.
- `feature.curated_tripmate_copy_snapshots` — Dagster가 materialize한 TripMate 복사용
  snapshot cache. `curated_feature_id` PK, `copy_version`, `etag`, `snapshot`,
  `materialized_at`, `updated_at`을 가진다.

핵심 상태:

- `curation_status`: `candidate` / `curated` / `rejected` / `archived`
- `selection_origin`: `source_rule` / `admin` / `external_api`
- `tripmate_relation`: `primary_stop` / `food_stop` / `cafe_stop` /
  `bookstore_stop` / `nearby_option` / `accessibility_support` / `pet_support` /
  `family_support` / `theme_area_anchor`

인덱스 기준:

- `UNIQUE (theme_id, feature_id) WHERE archived_at IS NULL`
- `INDEX (curation_status, updated_at DESC, curated_feature_id DESC)`
- `INDEX (theme_id, curation_status, rank_score DESC)`
- `INDEX (source_id, curation_status)`
- `INDEX (feature_id)`
- snapshot cache: `PRIMARY KEY (curated_feature_id)`,
  `INDEX (updated_at DESC, curated_feature_id DESC)`, `INDEX (etag)`

`rejected`/`archived` row는 provider 재적재나 source rule 재적용으로 되살리지 않는다.
TripMate는 REST snapshot을 읽어 `app.curated_trip_plans` /
`app.curated_plan_pois`로 복사하며, krtour-map DB에 직접 접근하지 않는다.

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

실제 구현(alembic 0002 / `infra/models.py` `ProviderSyncStateRow`):

```sql
CREATE TABLE provider_sync.provider_sync_state (
  provider               TEXT NOT NULL,
  dataset_key            TEXT NOT NULL,
  sync_scope             TEXT NOT NULL,                  -- PK 구성요소 (DEFAULT 없음)
  status                 TEXT NOT NULL DEFAULT 'active',
  cursor                 JSONB NOT NULL DEFAULT '{}'::jsonb,  -- Step B 증분 진행 위치 (예: {"last_modified_date": "2026-06-01"}), infra/sync_state_repo.py 가 운영
  last_success_at        TIMESTAMPTZ,
  last_failure_at        TIMESTAMPTZ,
  consecutive_failures   INTEGER NOT NULL DEFAULT 0,
  next_run_after         TIMESTAMPTZ,
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (provider, dataset_key, sync_scope),
  CONSTRAINT ck_provider_sync_state_status
    CHECK (status IN ('active','paused','disabled','failed'))
);

CREATE INDEX idx_sync_state_next_run ON provider_sync.provider_sync_state
  (next_run_after) WHERE status='active';
```

> **후속 후보 (미구현)**: 초기 설계에 있던 `metadata_hash` /
> `last_observed_source_version` / `last_attempt_at` / `last_full_scan_at` /
> `last_error`/`last_error_at` / `extra`는 현재 스키마에서 제외됐다 (간소화).
> 실패 추적은 `last_failure_at` + `consecutive_failures`로 대체. 필요 시 ADR +
> 마이그레이션으로 정식 추가.

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
  area_kind               TEXT NOT NULL DEFAULT 'area',  -- 'area' | 'national_park' | 'provincial_park' | 'recreation_forest' | 'tourism_district' | 'beach' | 'campsite' | 'heritage_area' | 'natural_heritage_area' | 'buried_heritage_area' | 'hazard_zone' (ADR-027) | 'other'
  boundary_source         TEXT,
  area_square_meters      NUMERIC(18,4),
  regulation_scope        TEXT,
  administrative_office   TEXT,
  description             TEXT,
  geometry                JSONB,                      -- geom 컬럼은 features.geom; 본 컬럼은 부가
  payload                 JSONB NOT NULL DEFAULT '{}'::jsonb  -- hazard_zone일 때 {"hazard_type": "rockfall|flash_flood|wildlife|...", "domain": "forest|coastal|..."} (ADR-027)
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
  load_batch_id     UUID,                             -- full-load root/child batch id
  parent_job_id     UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  status            TEXT NOT NULL DEFAULT 'queued',   -- queued, running, done, failed, cancelled
  progress          INTEGER NOT NULL DEFAULT 0,       -- 0~100
  current_stage     TEXT,
  source_checksum   TEXT,
  error_message     TEXT,
  started_at        TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  heartbeat_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_import_jobs_status CHECK (status IN ('queued','running','done','failed','cancelled')),
  CONSTRAINT ck_import_jobs_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX idx_import_jobs_status        ON ops.import_jobs (status, created_at);
CREATE INDEX idx_import_jobs_kind_status   ON ops.import_jobs (kind, status, created_at DESC);
CREATE INDEX idx_import_jobs_heartbeat     ON ops.import_jobs (heartbeat_at) WHERE status='running';
CREATE INDEX idx_import_jobs_load_batch_created
  ON ops.import_jobs (load_batch_id, created_at DESC, job_id DESC)
  WHERE load_batch_id IS NOT NULL;
CREATE INDEX idx_import_jobs_parent_created
  ON ops.import_jobs (parent_job_id, created_at DESC, job_id DESC)
  WHERE parent_job_id IS NOT NULL;
```

`load_batch_id`/`parent_job_id`는 ADR-045 T-205d에서 추가했다. T-200 Batch DAG는
root import job에 `load_batch_id`를 만들고, provider별 child job과
`consistency_check` job이 같은 `load_batch_id`와 root `parent_job_id`를 공유한다.

### 9.1.1 `ops.import_job_events` (T-221b)

```sql
CREATE TABLE ops.import_job_events (
  event_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE,
  provider    TEXT,
  dataset_key TEXT,
  feature_id  TEXT,
  stage       TEXT,
  level       TEXT NOT NULL, -- debug, info, warning, error, critical
  code        TEXT,
  message     TEXT NOT NULL,
  payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_import_job_events_level
    CHECK (level IN ('debug','info','warning','error','critical'))
);

CREATE INDEX idx_import_job_events_job_time
  ON ops.import_job_events (job_id, occurred_at DESC, event_id DESC);
CREATE INDEX idx_import_job_events_provider_time
  ON ops.import_job_events (provider, occurred_at DESC, event_id DESC)
  WHERE provider IS NOT NULL;
CREATE INDEX idx_import_job_events_level_time
  ON ops.import_job_events (level, occurred_at DESC, event_id DESC);
```

`ops.import_job_events`는 `ops.import_jobs` lifecycle과 provider/Dagster/offline upload
작업 단계 event를 저장한다. REST 조회 정렬은 `(occurred_at DESC, event_id DESC)`다.

### 9.1.2 `ops.offline_uploads` (ADR-045 D-14 / T-208g)

```sql
CREATE TABLE ops.offline_uploads (
  upload_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  provider          TEXT NOT NULL,
  dataset_key       TEXT NOT NULL,
  sync_scope        TEXT NOT NULL DEFAULT 'default',
  original_filename TEXT NOT NULL,
  storage_backend   TEXT NOT NULL,      -- rustfs / s3 / local-test 등
  storage_key       TEXT NOT NULL,
  byte_size         BIGINT NOT NULL,
  checksum_sha256   CHAR(64) NOT NULL,
  detected_format   TEXT,
  detected_encoding TEXT,
  status            TEXT NOT NULL DEFAULT 'uploaded',
  validation_job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  load_job_id       UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  created_by        TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_offline_uploads_status CHECK (
    status IN (
      'uploaded','validating','validated','validation_failed',
      'loading','loaded','load_failed','cancelled'
    )
  ),
  CONSTRAINT ck_offline_uploads_byte_size CHECK (byte_size >= 0),
  CONSTRAINT ck_offline_uploads_checksum_sha256
    CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_offline_uploads_provider_dataset
  ON ops.offline_uploads (provider, dataset_key, created_at DESC);
CREATE INDEX idx_offline_uploads_status
  ON ops.offline_uploads (status, created_at DESC);
```

첫 load job과 기본 admin API/UI 구현은 JSON/JSONL `FeatureBundle` dump만 지원한다.
CSV/TSV column mapping과 validation wizard는 후속에서 같은 테이블과 `import_jobs`
연결을 사용한다.

### 9.2 `ops.dedup_review_queue` (ADR-016)

```sql
CREATE TABLE ops.dedup_review_queue (
  review_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
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
  CONSTRAINT ck_dedup_pair_order CHECK (feature_id_a < feature_id_b),
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

`feature_id_a`/`feature_id_b`는 항상 lexicographic canonical 방향으로 저장한다.
`dedup_repo`는 upsert 전에 pair를 정렬하고, self-pair는 검토 큐에 넣지 않는다.

### 9.3 `ops.feature_overrides`

구현됨 — **alembic 0010** + `infra/models.py::FeatureOverrideRow` +
`infra/admin_feature_repo.py`. 운영자가 비활성화/수동 보정한 field를 provider 재적재가
덮지 않도록 기록한다. T-207c는 `field_path='status'` +
`prevent_provider_reactivation=true`를 `feature_repo.upsert_feature`에서 존중한다.

```sql
CREATE TABLE ops.feature_overrides (
  override_id         UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id           TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  source_record_key    TEXT REFERENCES provider_sync.source_records(source_record_key) ON DELETE SET NULL,
  field_path           TEXT NOT NULL,                 -- 'name', 'detail.phones[0]', ...
  source_value         JSONB,
  override_value       JSONB,
  prevent_provider_reactivation BOOLEAN NOT NULL DEFAULT false,
  status               TEXT NOT NULL DEFAULT 'active', -- active, inactive, superseded
  reason               TEXT,
  created_by           TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_overrides_status CHECK (status IN ('active','inactive','superseded'))
);

CREATE INDEX idx_overrides_feature  ON ops.feature_overrides (feature_id, status);
CREATE INDEX idx_overrides_field    ON ops.feature_overrides (field_path);
CREATE UNIQUE INDEX uq_overrides_active_feature_field
  ON ops.feature_overrides (feature_id, field_path)
  WHERE status = 'active';
CREATE INDEX idx_overrides_prevent_reactivation
  ON ops.feature_overrides (feature_id, field_path)
  WHERE status = 'active' AND prevent_provider_reactivation;
```

### 9.4 `ops.feature_merge_history`

구현됨 — **alembic 0007** + `infra/models.py::FeatureMergeHistoryRow` +
`infra/merge_repo.py`(`apply_feature_merge`/`merge_from_review`). `krtour-map
dedup-merge`가 `dedup_review_queue` 후보 1쌍을 master/loser로 확정(ADR-016
`core.scoring.select_master`)해 병합할 때 1행 INSERT. loser의 `source_links`는
master로 재지정되고 loser feature는 soft-delete(`status='deleted'`)된다.

```sql
CREATE TABLE ops.feature_merge_history (
  merge_id          UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  master_feature_id TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  loser_feature_id  TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  score             NUMERIC(5,2),                     -- dedup total_score (0~100), nullable
  review_id        UUID REFERENCES ops.dedup_review_queue(review_id) ON DELETE SET NULL,
  merged_by         TEXT,                             -- 운영자 ID 등
  reason            TEXT,
  merged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_merge_history_distinct CHECK (master_feature_id <> loser_feature_id)
);

CREATE INDEX idx_merge_history_loser  ON ops.feature_merge_history (loser_feature_id);
CREATE INDEX idx_merge_history_master ON ops.feature_merge_history (master_feature_id, merged_at DESC);
```

> 설계 메모: master/loser **둘 다** FK(CASCADE) — loser는 하드 삭제가 아니라
> soft-delete(ADR-017)라 행이 남으므로 FK 유효. `review_id` FK는 큐 행 삭제 시
> SET NULL(이력 보존). master 자동 선정은 `select_master`(좌표 보유 → updated_at →
> source 우선순위 행안부>TourAPI>사용자, 동률은 feature_id 사전순).

### 9.5 `ops.data_integrity_violations` (ADR-045 T-205c, alembic 0009)

위반 1건 = 1행인 운영 큐다. ADR-033 Phase 1의
`ops.feature_consistency_reports`(배치 단위 집계)와 달리, admin UI가 개별 이슈를
`open`/`acknowledged`/`resolved`/`ignored`로 관리한다.

```sql
CREATE TABLE ops.data_integrity_violations (
  issue_id       UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
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
CREATE INDEX idx_violations_source_record ON ops.data_integrity_violations (source_record_key) WHERE source_record_key IS NOT NULL;
CREATE INDEX idx_violations_detected_brin ON ops.data_integrity_violations USING BRIN (detected_at);
```

주소/좌표 정합성 위반은 다음 `violation_type`을 우선 지원한다.

| violation_type | 발생 조건 | payload 필수 필드 |
|----------------|-----------|-------------------|
| `provider_address_mismatch` | provider 주소와 좌표 기준 kraddr-geo reverse 주소가 다른 장소로 판단됨 | `provider_address`, `kraddr_geo_address`, `coord`, `match_level`, `distance_m`, `source_record_key` |
| `provider_address_partial_match` | 시군구/읍면동은 맞지만 상세 주소가 불완전하거나 다름 | `provider_address`, `kraddr_geo_address`, `match_level`, `notes` |
| `geocode_failed` | provider 주소 문자열로 `POST /v2/geocode` 후보를 얻지 못함 | `provider_address`, `provider_fields`, `error` |
| `reverse_geocode_failed` | 좌표로 `POST /v2/reverse` 주소를 얻지 못함 | `coord`, `error` |
| `missing_address` | provider 주소도 kraddr-geo 주소도 없음 | `provider_fields`, `coord` |
| `missing_bjd_code` | kraddr-geo 결과에 10자리 법정동코드가 없음 | `kraddr_geo_address`, `coord` |

admin UI가 수동 수정하면 `status='resolved'`, `resolved_at`, `payload.resolution`
(`field_path`, `old_value`, `new_value`, `operator`, `reason`)을 기록한다. 실제 보정값은
`feature.features` row와 `ops.feature_overrides`에 반영해 provider 재적재가 덮어쓰지
않도록 한다.

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

### 9.7 `ops.feature_consistency_reports` (ADR-033 Phase 1, 구현됨)

정합성 배치 1회 = 1행. F1~F3(orphan source_record / detail 누락 / CRS drift)을
`infra/consistency.py`가 검사해 집계 결과를 적재한다 (관측 모드 — Dagster swap
게이트는 Phase 2/Sprint 5). alembic `0003_consistency_reports`로 도입.

```sql
CREATE TABLE ops.feature_consistency_reports (
  report_id    UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  batch_id     UUID NOT NULL,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  severity_max TEXT NOT NULL CHECK (severity_max IN ('OK','WARN','ERROR')),
  cases        JSONB NOT NULL,   -- [{code, severity, description, count, sample_ids}]
  summary      JSONB NOT NULL    -- {total_violations, cases_evaluated, by_severity, by_code}
);
CREATE INDEX idx_reports_batch   ON ops.feature_consistency_reports (batch_id);
CREATE INDEX idx_reports_started ON ops.feature_consistency_reports (started_at DESC);
```

### 9.8 `ops.feature_update_requests` (ADR-045 accepted — alembic 0008)

OpenAPI로 들어온 feature update request를 저장한다. `center_radius`,
`sigungu_by_radius`, `provider_dataset`, `cache_target_keys` 같은 scope를 Dagster
run/import job으로 연결한다. 상세 계약은 `docs/openapi-admin-contract.md`.

핵심 컬럼:

| 컬럼 | 의미 |
|------|------|
| `request_id` | UUID PK, `x_extension.gen_random_uuid()` 기본값 |
| `scope_type` / `scope` | 요청 범위 종류와 JSONB payload |
| `providers` / `dataset_keys` | 제한할 provider/dataset 목록(JSONB array) |
| `update_policy` | 재적재/중복/정합성 정책 JSONB |
| `run_mode` | `queued` 또는 `now` |
| `priority` | queue 우선순위, 기본 50 |
| `status` | `queued`/`running`/`done`/`failed`/`cancelled` |
| `dry_run` | 영향 범위만 계산한 요청 여부 |
| `matched_scope` | scope resolver가 계산한 feature/provider/sigungu 요약 |
| `job_id` | `ops.import_jobs(job_id)` FK, job 삭제 시 `NULL` |
| `dagster_run_id` | Dagster run 추적 id |

인덱스:

- `idx_feature_update_status_priority` — queued/running claim과 목록.
- `idx_feature_update_created` — 최신 요청 목록.
- `idx_feature_update_job` — import job에서 request 역추적.

T-205a는 테이블/ORM 매핑까지만 구현했다. scope resolver, enqueue/claim/peek
repository, client 표면은 T-206a/b/c와 T-208e에서 구현했고, admin API와 Dagster
sensor는 T-207/T-208에서 연결했다.

### 9.9 `ops.feature_change_requests` (alembic 0021)

사용자/admin 요청으로 들어온 place/event feature 추가·수정·삭제 요청을 저장한다.
`review_mode='require_review'`면 `pending`으로 남고, admin 승인이 들어오면 적용된다.
`review_mode='immediate'`면 같은 transaction에서 바로 적용되어 `applied`가 된다.

```sql
CREATE TABLE ops.feature_change_requests (
  request_id   UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  feature_id   TEXT NOT NULL,
  action       TEXT NOT NULL,           -- add / update / delete
  state        TEXT NOT NULL DEFAULT 'pending',
  review_mode  TEXT NOT NULL,           -- require_review / immediate
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason       TEXT,
  requested_by TEXT,
  reviewed_by  TEXT,
  reviewed_at  TIMESTAMPTZ,
  applied_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT ck_feature_change_action CHECK (action IN ('add','update','delete')),
  CONSTRAINT ck_feature_change_state CHECK (state IN ('pending','applied','rejected')),
  CONSTRAINT ck_feature_change_review_mode CHECK (
    review_mode IN ('require_review','immediate')
  )
);

CREATE INDEX idx_feature_change_state_created
  ON ops.feature_change_requests (state, created_at DESC, request_id DESC);
CREATE INDEX idx_feature_change_feature
  ON ops.feature_change_requests (feature_id);
```

적용 규칙:

- 대상 kind는 `place`, `event`만 허용한다.
- add/update/delete가 적용되면 `feature.features.data_origin='user_request'`,
  `data_version=1`, `user_change_request_id=request_id`로 effective row를 갱신한다.
- delete는 hard delete가 아니라 `status='deleted'`, `deleted_at`, `user_deleted_at`을
  기록하는 soft delete다.
- provider reload와 snapshot 누락 정리는 `data_origin='user_request'` row를 삭제하거나
  되살리지 않는다.

### 9.10 `ops.poi_cache_targets` / `ops.poi_cache_target_feature_links` (ADR-045 T-205c, alembic 0009)

외부 앱 POI/cache target을 `external_system + target_key + 좌표 + 반경`으로 저장하고,
target 주변 feature와 다대다로 연결한다. 목적은 전체 provider 재적재 없이 저장 POI
주변의 자주 바뀌는 값(날씨, 유가, 경고, 유고정보 등)을 캐싱 갱신하는 것이다.

핵심 규칙:

- `target_key`는 좌표가 아니라 외부 앱이 보장하는 고유 key다.
- 같은 key와 같은 normalized 좌표는 idempotent upsert다.
- 같은 key와 다른 normalized 좌표는 기본 409이며, 이동은 명시적 `move`로 처리한다.
- soft deleted target은 targeted update에서 제외한다.
- 여러 target 반경의 교집합 feature/provider scope는 한 번만 업데이트한다.

상세 DDL은 `docs/poi-cache-update-targets.md` §6과 `alembic 0009`가 정본이다.
repository는 `infra.poi_cache_target_repo`가 제공한다. `infra.scope_repo`의
`resolve_cache_target_keys`와 `infra.feature_update_executor`는 active target 주변
feature를 계산하고 `ops.poi_cache_target_feature_links`를 재계산한다.

### 9.11 `ops.provider_refresh_policies` (ADR-045 T-205c, alembic 0009)

provider/dataset별 update 주기, targeted update 허용 여부, filedata/openapi 구분,
rate limit, 최적 기본값, 출처 문서를 저장한다.

핵심 규칙:

- filedata provider는 기본적으로 POI 등록 여부와 무관하게 system schedule을 따른다.
- admin UI/설정/DB override는 가능하지만 provider rate limit을 넘을 수 없다.
- rate limit과 최적값은 provider API 프로젝트의 문서/코드(로컬 `F:\dev\python-*-api`
  우선, ADR-044)를 근거로 저장한다.

repository는 `infra.provider_refresh_policy_repo`가 제공한다. T-206d request 실행
본체는 `enabled`/`source_kind`/`targeted_policy`를 실행 계획에 적용하고, rate-limit
값을 runner scope metadata로 전달한다. provider 호출 단위의 hard enforcement는
Dagster resource/provider runner가 수행한다.

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
