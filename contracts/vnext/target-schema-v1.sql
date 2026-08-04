-- =============================================================================
-- contracts/vnext/target-schema-v1.sql — T-VN-31A vNext target freeze
-- =============================================================================
-- Wave 2(T-VN-32~40)가 구현할 **목표 상태**의 실행 가능 DDL 정본이다.
--
-- 정본 근거:
--   * ADR-066~075 (특히 ADR-067 직교 상태 / ADR-068 UUID identity /
--     ADR-069 provider_datasets / ADR-070 subtype / ADR-071 field override /
--     ADR-072 weather bitemporal), ADR-078 price series identity
--   * docs/reports/system-structure-api-schema-review-2026-07-16.md §3(목표 DB
--     schema 표), §2 D-3~D-8, §8.1
--   * docs/tasks.md T-VN-31~40 정의
--
-- 규율:
--   * migration 번호·`op.` 구현·backfill SQL을 포함하지 않는다. 실제 전환 DDL은
--     ADR-075 결정 5를 따른다 — 대형 CHECK/FK는 `ADD CONSTRAINT ... NOT VALID` 후
--     별도 `VALIDATE CONSTRAINT`, UNIQUE는 `CREATE UNIQUE INDEX CONCURRENTLY` 후
--     writer conflict target과 같은 cutover에서 연결한다. 본 파일은 그 절차의
--     **도착점(최종형)**만 기술하며 빈 PostGIS DB에 그대로 적용 가능하다.
--   * `x_extension` schema와 postgis/pgcrypto/pg_trgm 확장은 사전 존재를 가정한다
--     (ADR-008; tests/integration/test_vnext_target_freeze.py가 생성).
--   * Wave 2가 변경하지 않는 유지 기준선(ops.import_jobs 계열, cache-target 계열,
--     domain command ledger 계열 등)은 현행 alembic head가 정본이며 여기 반복하지
--     않는다. 현행과 겹치는 부모 테이블은 목표 형태의 최소 정의로만 포함한다.
--   * legacy 산출물(feature.curated_features overlay, source_records denorm 열,
--     features의 legacy status/user_change_* 열 등)은 목표 상태에 **존재하지
--     않으므로** 이 파일에 없다. 물리 삭제 순서는 consumer-rollout-v1.json과
--     T-VN-39 removal manifest가 소유한다.
--
-- 미정 표기 원칙(freeze 정직성):
--   ADR·보고서·task 정의가 침묵하는 세부는 발명하지 않고
--   `-- 미정(T-VN-XX 구현 소관)`으로 남긴다. 반면 DDL이 실행 가능하려면 이름이
--   필요한 객체(테이블·제약·인덱스 이름)는 본 freeze가 고정한다.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS provider_sync;
CREATE SCHEMA IF NOT EXISTS ops;

-- =============================================================================
-- 1. feature.categories — category 정본 (ADR-070 결정 3, 보고서 D-6-3)
-- =============================================================================
-- features가 `(kind, code)` composite FK로 참조한다. 현행 코드 registry에서 DB
-- 정본으로 승격되는 최소형이다.
CREATE TABLE feature.categories (
    kind text NOT NULL,
    code text NOT NULL,
    CONSTRAINT pk_categories PRIMARY KEY (kind, code),
    CONSTRAINT ck_categories_kind CHECK (
        kind IN ('place', 'event', 'notice', 'price', 'weather', 'route', 'area')
    ),
    CONSTRAINT ck_categories_code_canonical CHECK (code <> '' AND code = btrim(code))
    -- 표시명·정렬·계층 등 나머지 컬럼: 미정(T-VN-35A 구현 소관)
);

-- =============================================================================
-- 2. provider_sync.provider_datasets — provider×dataset identity 정본 (ADR-069)
-- =============================================================================
CREATE TABLE provider_sync.provider_datasets (
    -- surrogate 타입(bigint identity)은 본 freeze가 고정한다(ADR-069는 침묵).
    provider_dataset_id bigint GENERATED ALWAYS AS IDENTITY,
    provider text NOT NULL,
    dataset_key text NOT NULL,
    -- 활성 상태 (ADR-069 결정 1)
    is_active boolean NOT NULL DEFAULT true,
    -- capability 정본 (ADR-069 결정 1·2 — provider_catalog는 이 값의 projection).
    -- capability 표현 shape(키 집합·typed column 승격 여부): 미정(T-VN-33A 구현 소관)
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_datasets PRIMARY KEY (provider_dataset_id),
    CONSTRAINT uq_provider_datasets_identity UNIQUE (provider, dataset_key),
    CONSTRAINT ck_provider_datasets_provider_canonical CHECK (
        provider <> '' AND provider = btrim(provider)
    ),
    CONSTRAINT ck_provider_datasets_dataset_key_canonical CHECK (
        dataset_key <> '' AND dataset_key = btrim(dataset_key)
    ),
    CONSTRAINT ck_provider_datasets_capabilities_object CHECK (
        jsonb_typeof(capabilities) = 'object'
    )
);

-- =============================================================================
-- 3. feature.features — 축소된 core (ADR-067·068·070)
-- =============================================================================
-- core에는 UUID·kind·name·category FK·직교 3상태·row_revision만 남는다
-- (ADR-070 결정 1). 좌표/geometry/detail/주소/URL 등은 subtype 소관이다.
CREATE TABLE feature.features (
    -- 애플리케이션 생성 UUID surrogate (ADR-068 결정 1). UUIDv7 채택 여부와
    -- generator 정본은 미정(T-VN-32A 구현 소관) — 따라서 DB server default를
    -- 두지 않는다(PG16 gen_random_uuid()는 v4 — 보고서 D-4-1).
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    name text NOT NULL,
    category_code text NOT NULL,
    -- 직교 3축 상태 (ADR-067 결정 1). legacy status/deleted_at/user_change_* 열은
    -- 목표 상태에 없다(무손실 매핑·물리 삭제는 T-VN-34A/34C/39 소관).
    lifecycle_state text NOT NULL,
    publication_state text NOT NULL,
    quality_state text NOT NULL,
    -- server-owned 단조 revision (ADR-074 결정 2, 현행 0062 의미 유지)
    row_revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- 공통 표시 필드(ADR-070 결정 1 "공통 표시 필드")의 정확한 집합(name 외
    -- marker/주소 요약 등): 미정(T-VN-35A 구현 소관)
    CONSTRAINT pk_features PRIMARY KEY (feature_id),
    -- subtype composite FK 대상 — core kind와 subtype row의 일치를 DB가 강제하는
    -- 장치(ADR-070 결정 3의 DB 제약 구현으로 본 freeze가 고정).
    CONSTRAINT uq_features_id_kind UNIQUE (feature_id, kind),
    CONSTRAINT ck_features_kind CHECK (
        kind IN ('place', 'event', 'notice', 'price', 'weather', 'route', 'area')
    ),
    CONSTRAINT ck_features_name_nonempty CHECK (btrim(name) <> ''),
    CONSTRAINT ck_features_lifecycle_state CHECK (lifecycle_state IN ('active', 'retired')),
    CONSTRAINT ck_features_publication_state CHECK (
        publication_state IN ('draft', 'published', 'suppressed')
    ),
    CONSTRAINT ck_features_quality_state CHECK (quality_state IN ('valid', 'quarantined')),
    -- 불가능 조합 CHECK (ADR-067 결정 5). 최소 고정분: retired∧draft.
    -- 근거 — 0059 view가 정본화한 legacy 무손실 매핑에서 draft의 lifecycle 상은
    -- 항상 active이고(retire 경로는 published/suppressed를 거친 행에만 존재),
    -- 어떤 legacy status도 (retired, draft, *)로 매핑되지 않는다.
    -- 추가 불가능 조합(예: retired∧suppressed 허용 여부): 미정(T-VN-34A 구현 소관)
    CONSTRAINT ck_features_state_combination CHECK (
        NOT (lifecycle_state = 'retired' AND publication_state = 'draft')
    ),
    CONSTRAINT ck_features_row_revision CHECK (row_revision >= 1),
    CONSTRAINT fk_features_category FOREIGN KEY (kind, category_code)
        REFERENCES feature.categories (kind, code)
);

-- 공개 술어와 동일한 base-table partial index (ADR-067 결정 2).
-- 키 컬럼 구성은 실제 hot query 실측으로 확정한다: 미정(T-VN-34B 구현 소관).
-- 술어 자체는 본 freeze가 고정한다.
CREATE INDEX idx_features_public_state
    ON feature.features (kind, feature_id)
    WHERE lifecycle_state = 'active'
      AND publication_state = 'published'
      AND quality_state = 'valid';

-- server-owned row_revision 강제 트리거 (현행 0062 정본 의미를 목표 상태에 유지).
CREATE FUNCTION feature.force_features_row_revision()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.row_revision := OLD.row_revision + 1;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_features_row_revision
    BEFORE UPDATE ON feature.features
    FOR EACH ROW EXECUTE FUNCTION feature.force_features_row_revision();

-- =============================================================================
-- 4. feature.feature_aliases — legacy `f_*` alias (ADR-068 결정 3)
-- =============================================================================
CREATE TABLE feature.feature_aliases (
    alias text NOT NULL,
    feature_id uuid NOT NULL,
    alias_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- alias 전역 UNIQUE (보고서 §3 "alias UNIQUE") — PK로 고정.
    CONSTRAINT pk_feature_aliases PRIMARY KEY (alias),
    -- ON DELETE 의미(feature 물리 삭제 시 alias 처분): 미정(T-VN-32A 구현 소관)
    CONSTRAINT fk_feature_aliases_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id),
    CONSTRAINT ck_feature_aliases_alias_canonical CHECK (alias <> '' AND alias = btrim(alias)),
    CONSTRAINT ck_feature_aliases_kind_canonical CHECK (
        alias_kind <> '' AND alias_kind = btrim(alias_kind)
    )
    -- alias_kind 값 집합(legacy f_* 외 추가 kind 허용 여부): 미정(T-VN-32A 구현 소관)
);

-- lookup index (보고서 §3) — feature → alias 역방향.
CREATE INDEX idx_feature_aliases_feature ON feature.feature_aliases (feature_id);

-- =============================================================================
-- 5. kind별 typed subtype 테이블 (ADR-070)
-- =============================================================================
-- 공통 장치(본 freeze가 고정):
--   * 1:1 — feature_id PK + `(feature_id, kind)` composite FK로 core kind 일치 강제
--   * geometry: canonical 4326 + generated 5179 (보고서 §3)
--   * geometry CHECK 3종: GeometryType(typmod)·ST_IsValid·NOT ST_IsEmpty +
--     anchor 일치 (ADR-070 결정 2)
--   * 공간 인덱스: §3의 "공개 술어 partial GiST만"은 상태 컬럼이 core로 분리된
--     목표 구조에서 subtype-local 술어로 표현할 수 없다(설계 공백). 여기서는
--     무술어 GiST 최소형만 고정하고 partial 표현 수단(denorm flag vs join 유지)과
--     4326/5179 축 채택은 실측 소관으로 남긴다: 미정(T-VN-35D·ADR-075 결정 7)

-- 5.1 point subtype — place/price/weather (T-VN-35A)
CREATE TABLE feature.feature_points (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    geom x_extension.geometry(Point, 4326) NOT NULL,
    geom_5179 x_extension.geometry(Point, 5179)
        GENERATED ALWAYS AS (x_extension.st_transform(geom, 5179)) STORED,
    -- point류는 geometry 자체가 anchor다 — 별도 anchor 컬럼·CHECK 없음.
    -- kind별 전용 컬럼(주소·detail·좌표 정밀도 등)의 subtype 배치: 미정(T-VN-35A 구현 소관)
    CONSTRAINT pk_feature_points PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_points_feature FOREIGN KEY (feature_id, kind)
        REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
    CONSTRAINT ck_feature_points_kind CHECK (kind IN ('place', 'price', 'weather')),
    CONSTRAINT ck_feature_points_geom_valid CHECK (x_extension.st_isvalid(geom)),
    CONSTRAINT ck_feature_points_geom_not_empty CHECK (NOT x_extension.st_isempty(geom))
);

CREATE INDEX idx_feature_points_geom_gist
    ON feature.feature_points USING gist (geom);
CREATE INDEX idx_feature_points_geom_5179_gist
    ON feature.feature_points USING gist (geom_5179);

-- 5.2 event subtype (T-VN-35B)
CREATE TABLE feature.feature_events (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    geom x_extension.geometry(Point, 4326) NOT NULL,
    geom_5179 x_extension.geometry(Point, 5179)
        GENERATED ALWAYS AS (x_extension.st_transform(geom, 5179)) STORED,
    -- 기간의 range 승격 (보고서 D-6-4 "filter/sort 필드는 typed column/range").
    -- 단일 range vs from/until 분해·추가 event 전용 컬럼: 미정(T-VN-35B 구현 소관)
    event_period tstzrange NOT NULL,
    CONSTRAINT pk_feature_events PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_events_feature FOREIGN KEY (feature_id, kind)
        REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
    CONSTRAINT ck_feature_events_kind CHECK (kind = 'event'),
    CONSTRAINT ck_feature_events_geom_valid CHECK (x_extension.st_isvalid(geom)),
    CONSTRAINT ck_feature_events_geom_not_empty CHECK (NOT x_extension.st_isempty(geom)),
    CONSTRAINT ck_feature_events_period_not_empty CHECK (NOT isempty(event_period))
);

CREATE INDEX idx_feature_events_geom_gist
    ON feature.feature_events USING gist (geom);
CREATE INDEX idx_feature_events_geom_5179_gist
    ON feature.feature_events USING gist (geom_5179);

-- 5.3 notice subtype (T-VN-35B)
CREATE TABLE feature.feature_notices (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    -- notice 전용 컬럼(대상 feature 연결·본문 typed 필드)과 geometry 보유 여부:
    -- 미정(T-VN-35B 구현 소관 — 현행 notice feature의 coord 사용 실태 조사 후 확정)
    CONSTRAINT pk_feature_notices PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_notices_feature FOREIGN KEY (feature_id, kind)
        REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
    CONSTRAINT ck_feature_notices_kind CHECK (kind = 'notice')
);

-- 5.4 route subtype (T-VN-35C) — MultiLineString (보고서 D-6-2)
CREATE TABLE feature.feature_routes (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    geom x_extension.geometry(MultiLineString, 4326) NOT NULL,
    geom_5179 x_extension.geometry(MultiLineString, 5179)
        GENERATED ALWAYS AS (x_extension.st_transform(geom, 5179)) STORED,
    -- 대표 좌표(anchor) — core 좌표와 geometry의 anchor 일치 CHECK 대상(ADR-070 결정 2)
    anchor x_extension.geometry(Point, 4326) NOT NULL,
    CONSTRAINT pk_feature_routes PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_routes_feature FOREIGN KEY (feature_id, kind)
        REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
    CONSTRAINT ck_feature_routes_kind CHECK (kind = 'route'),
    CONSTRAINT ck_feature_routes_geom_valid CHECK (x_extension.st_isvalid(geom)),
    CONSTRAINT ck_feature_routes_geom_not_empty CHECK (NOT x_extension.st_isempty(geom)),
    -- anchor 일치의 최소 고정분: anchor는 geometry envelope 안에 있어야 한다
    -- (구판 발견 "coord-geom 325km 이격" 차단). envelope보다 강한 정밀 술어
    -- (거리 허용오차 등): 미정(T-VN-35C 구현 소관)
    CONSTRAINT ck_feature_routes_anchor_in_envelope CHECK (
        x_extension.st_intersects(x_extension.st_envelope(geom), anchor)
    )
);

CREATE INDEX idx_feature_routes_geom_gist
    ON feature.feature_routes USING gist (geom);
CREATE INDEX idx_feature_routes_geom_5179_gist
    ON feature.feature_routes USING gist (geom_5179);

-- 5.5 area subtype (T-VN-35C) — MultiPolygon (보고서 D-6-2)
CREATE TABLE feature.feature_areas (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    geom x_extension.geometry(MultiPolygon, 4326) NOT NULL,
    geom_5179 x_extension.geometry(MultiPolygon, 5179)
        GENERATED ALWAYS AS (x_extension.st_transform(geom, 5179)) STORED,
    anchor x_extension.geometry(Point, 4326) NOT NULL,
    CONSTRAINT pk_feature_areas PRIMARY KEY (feature_id),
    CONSTRAINT fk_feature_areas_feature FOREIGN KEY (feature_id, kind)
        REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
    CONSTRAINT ck_feature_areas_kind CHECK (kind = 'area'),
    CONSTRAINT ck_feature_areas_geom_valid CHECK (x_extension.st_isvalid(geom)),
    CONSTRAINT ck_feature_areas_geom_not_empty CHECK (NOT x_extension.st_isempty(geom)),
    CONSTRAINT ck_feature_areas_anchor_in_envelope CHECK (
        x_extension.st_intersects(x_extension.st_envelope(geom), anchor)
    )
);

CREATE INDEX idx_feature_areas_geom_gist
    ON feature.feature_areas USING gist (geom);
CREATE INDEX idx_feature_areas_geom_5179_gist
    ON feature.feature_areas USING gist (geom_5179);

-- =============================================================================
-- 6. 공개 정본 projection (ADR-067 결정 2·3)
-- =============================================================================
-- 모든 공개 payload projection(단건·batch·bbox·search·nearby·cluster·collection)이
-- 이 view만 사용한다. 0059의 교훈에 따라 컬럼 목록을 명시한다(SELECT * 금지 —
-- 새 core 컬럼이 공개 projection에 무심코 노출되는 것을 막는다).
CREATE VIEW feature.public_features AS
SELECT
    f.feature_id,
    f.kind,
    f.name,
    f.category_code,
    f.row_revision,
    f.created_at,
    f.updated_at
FROM feature.features AS f
WHERE f.lifecycle_state = 'active'
  AND f.publication_state = 'published'
  AND f.quality_state = 'valid';

-- =============================================================================
-- 7. source lineage 정본 (ADR-068 결정 2, ADR-069)
-- =============================================================================

-- 7.1 source_entities — provider natural identity 3-tuple UNIQUE (ADR-068 결정 2)
CREATE TABLE provider_sync.source_entities (
    source_entity_key text NOT NULL,
    provider_dataset_id bigint NOT NULL,
    source_entity_type text NOT NULL,
    source_entity_id text NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    CONSTRAINT pk_source_entities PRIMARY KEY (source_entity_key),
    CONSTRAINT fk_source_entities_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    -- provider identity 3-tuple (ADR-068 결정 2 — bjd/category/이름/좌표는
    -- identity 입력이 아니다)
    CONSTRAINT uq_source_entities_provider_identity UNIQUE (
        provider_dataset_id, source_entity_type, source_entity_id
    ),
    CONSTRAINT ck_source_entities_type_canonical CHECK (
        source_entity_type <> '' AND source_entity_type = btrim(source_entity_type)
    ),
    CONSTRAINT ck_source_entities_id_canonical CHECK (
        source_entity_id <> '' AND source_entity_id = btrim(source_entity_id)
    ),
    CONSTRAINT ck_source_entities_seen_order CHECK (first_seen_at <= last_seen_at)
    -- head pointer는 source_entity_heads로 분리(순환 FK 제거 — 보고서 D-5-3).
);

-- 7.2 source_records — immutable payload (ADR-069 결정 2)
-- denorm identity 열(provider/dataset/type/id)과 raw_name/raw_address/raw 좌표
-- 파생 열은 목표 상태에서 제거된다(물리 삭제는 T-VN-33C manifest → T-VN-39).
-- retention 열(last_seen_at/expires_at)의 존치: 미정(T-VN-33A 구현 소관 — ADR-017
-- 보관 정책과의 결합)
CREATE TABLE provider_sync.source_records (
    source_record_key text NOT NULL,
    source_entity_key text NOT NULL,
    raw_data jsonb NOT NULL,
    raw_payload_hash text NOT NULL,
    -- 수집 시각 (ADR-069 결정 2)
    fetched_at timestamptz NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_source_records PRIMARY KEY (source_record_key),
    CONSTRAINT fk_source_records_entity FOREIGN KEY (source_entity_key)
        REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE RESTRICT,
    -- 같은 entity 안에서 payload 중복 금지 (현행 uq_source_records의 denorm 제거형)
    CONSTRAINT uq_source_records_entity_payload UNIQUE (source_entity_key, raw_payload_hash),
    -- head composite FK 대상 (ADR-069 결정 3)
    CONSTRAINT uq_source_records_entity_record UNIQUE (source_entity_key, source_record_key),
    CONSTRAINT ck_source_records_raw_data_object CHECK (jsonb_typeof(raw_data) = 'object'),
    CONSTRAINT ck_source_records_payload_hash_canonical CHECK (
        raw_payload_hash <> '' AND raw_payload_hash = btrim(raw_payload_hash)
    )
);

-- immutable 보장(ADR-069 결정 2 "immutable raw payload") — UPDATE 거부 트리거.
-- DELETE는 보관 정책(ADR-017) purge 소관이라 막지 않는다.
CREATE FUNCTION provider_sync.reject_source_record_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'provider_sync.source_records is immutable (ADR-069)'
        USING ERRCODE = 'P0001';
END;
$$;

CREATE TRIGGER trg_source_records_immutable
    BEFORE UPDATE ON provider_sync.source_records
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_source_record_update();

-- 7.3 source_entity_heads — 검증된 current pointer (ADR-069 결정 3)
CREATE TABLE provider_sync.source_entity_heads (
    source_entity_key text NOT NULL,
    current_source_record_key text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_source_entity_heads PRIMARY KEY (source_entity_key),
    CONSTRAINT fk_source_entity_heads_entity FOREIGN KEY (source_entity_key)
        REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE CASCADE,
    -- head FK는 같은 entity의 record만 가리킨다 — composite FK (ADR-069 결정 3)
    CONSTRAINT fk_source_entity_heads_record FOREIGN KEY (
        source_entity_key, current_source_record_key
    ) REFERENCES provider_sync.source_records (source_entity_key, source_record_key)
        ON DELETE RESTRICT
);

-- 7.4 source_links — Feature ↔ SourceEntity membership (ADR-069 결정 2 D-5-4)
-- `is_primary_source` boolean은 제거되고 primary 판정은 `source_role` 단일 필드다.
-- primary role의 feature당 유일성 강제 여부: 미정(T-VN-33B 구현 소관)
CREATE TABLE provider_sync.source_links (
    feature_id uuid NOT NULL,
    source_entity_key text NOT NULL,
    source_role text NOT NULL DEFAULT 'enrichment',
    match_method text NOT NULL,
    confidence integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_source_links PRIMARY KEY (feature_id, source_entity_key),
    CONSTRAINT fk_source_links_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_source_links_entity FOREIGN KEY (source_entity_key)
        REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE RESTRICT,
    -- role 값 집합은 현행 정본을 유지한다.
    CONSTRAINT ck_source_links_role CHECK (
        source_role IN (
            'primary', 'base_address', 'base_coordinate', 'enrichment',
            'correction', 'duplicate_candidate', 'media', 'weather_context'
        )
    ),
    CONSTRAINT ck_source_links_confidence CHECK (confidence BETWEEN 0 AND 100)
);

CREATE INDEX idx_source_links_entity ON provider_sync.source_links (source_entity_key);
CREATE INDEX idx_source_links_primary
    ON provider_sync.source_links (feature_id)
    WHERE source_role = 'primary';

-- =============================================================================
-- 8. field-level override 정본 (ADR-071)
-- =============================================================================

-- 허용 field_path registry (ADR-071 결정 4). 값 type 체계와 적용 가능 subtype의
-- 표현(enum vs 배열): 미정(T-VN-36A 구현 소관) — 최소형만 고정.
CREATE TABLE ops.feature_override_field_paths (
    field_path text NOT NULL,
    value_type text NOT NULL,
    CONSTRAINT pk_feature_override_field_paths PRIMARY KEY (field_path),
    CONSTRAINT ck_override_field_path_canonical CHECK (
        field_path <> '' AND field_path = btrim(field_path)
    ),
    CONSTRAINT ck_override_value_type_canonical CHECK (
        value_type <> '' AND value_type = btrim(value_type)
    )
);

CREATE TABLE ops.feature_overrides (
    override_id bigint GENERATED ALWAYS AS IDENTITY,
    feature_id uuid NOT NULL,
    field_path text NOT NULL,
    -- override 값 (ADR-071 결정 2 — provider base value와 분리 저장).
    -- value_type과의 결합 검증 방식: 미정(T-VN-36B 구현 소관)
    override_value jsonb,
    -- provenance (ADR-071 결정 2) — 생성 시점 base revision과 인증 principal
    -- (ADR-066 결정 5). provenance 세부 컬럼 확장: 미정(T-VN-36A 구현 소관)
    base_row_revision bigint,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- tombstone — 해제돼도 행은 보존한다(ADR-071 전환/rollback).
    revoked_at timestamptz,
    revoked_by text,
    CONSTRAINT pk_feature_overrides PRIMARY KEY (override_id),
    CONSTRAINT fk_feature_overrides_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_feature_overrides_field_path FOREIGN KEY (field_path)
        REFERENCES ops.feature_override_field_paths (field_path),
    CONSTRAINT ck_feature_overrides_created_by CHECK (btrim(created_by) <> ''),
    CONSTRAINT ck_feature_overrides_tombstone_pair CHECK (
        (revoked_at IS NULL) = (revoked_by IS NULL)
    )
);

-- `(feature_id, field_path)` active UNIQUE (ADR-071 결정 1)
CREATE UNIQUE INDEX uq_feature_overrides_active
    ON ops.feature_overrides (feature_id, field_path)
    WHERE revoked_at IS NULL;

CREATE INDEX idx_feature_overrides_feature ON ops.feature_overrides (feature_id);

-- =============================================================================
-- 9. typed notice state (보고서 D-9-7, T-VN-37)
-- =============================================================================
-- 현행 provider_sync.notice_lineage_states(문자열 시각·anti-join hot path)의
-- 목표형. feature 연결(공개 판정 join 경로)의 표현: 미정(T-VN-37A 구현 소관)
CREATE TABLE provider_sync.notice_states (
    notice_state_id bigint GENERATED ALWAYS AS IDENTITY,
    provider_dataset_id bigint NOT NULL,
    source_entity_type text NOT NULL,
    lineage_key text NOT NULL,
    present boolean NOT NULL,
    valid_during tstzrange NOT NULL,
    is_current boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_notice_states PRIMARY KEY (notice_state_id),
    CONSTRAINT fk_notice_states_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_notice_states_type_canonical CHECK (
        source_entity_type <> '' AND source_entity_type = btrim(source_entity_type)
    ),
    CONSTRAINT ck_notice_states_lineage_key_canonical CHECK (
        lineage_key <> '' AND lineage_key = btrim(lineage_key)
    ),
    CONSTRAINT ck_notice_states_valid_during_not_empty CHECK (NOT isempty(valid_during))
);

-- lineage당 current 1건 (보고서 §3 "current partial UNIQUE")
CREATE UNIQUE INDEX uq_notice_states_current
    ON provider_sync.notice_states (provider_dataset_id, source_entity_type, lineage_key)
    WHERE is_current;

-- range GiST (보고서 §3). lineage 복합 GiST/EXCLUDE(overlap 금지)는 btree_gist
-- 도입이 필요해 미정(T-VN-37A 구현 소관) — 최소형 단일 컬럼 GiST만 고정.
CREATE INDEX idx_notice_states_valid_during
    ON provider_sync.notice_states USING gist (valid_during);

-- =============================================================================
-- 10. weather bitemporal history + current summary (ADR-072, T-VN-38A)
-- =============================================================================
-- 현행 feature.feature_weather_values(0060 이후)의 목표형 — 변경점:
--   * feature_id uuid FK / provider → provider_dataset_id FK (ADR-072 결정 2)
--   * bitemporal 축 target_at/known_at 명시 (ADR-072 결정 1)
--   * provider-native 발표/유효/관측 시각은 typed 컬럼으로 보존
-- BRIN-on-time은 실측 후 채택: 미정(ADR-072 결정 5, T-VN-38C 구현 소관)
CREATE TABLE feature.feature_weather_values (
    weather_value_key text NOT NULL,
    feature_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    weather_domain text NOT NULL,
    forecast_style text NOT NULL,
    timeline_bucket text,
    metric_key text NOT NULL,
    value_number numeric(14, 4),
    value_text text,
    unit text,
    issued_at timestamptz,
    valid_at timestamptz,
    valid_from timestamptz,
    valid_until timestamptz,
    observed_at timestamptz,
    -- bitemporal 축 (ADR-072 결정 1)
    target_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_record_key text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_weather_values PRIMARY KEY (weather_value_key),
    CONSTRAINT fk_weather_values_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_weather_values_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_weather_value_source_record FOREIGN KEY (source_record_key)
        REFERENCES provider_sync.source_records (source_record_key) ON DELETE SET NULL,
    CONSTRAINT ck_weather_value_present CHECK (
        value_number IS NOT NULL OR value_text IS NOT NULL
    ),
    CONSTRAINT ck_weather_value_range CHECK (
        valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until
    ),
    CONSTRAINT ck_weather_value_payload_object CHECK (jsonb_typeof(payload) = 'object'),
    -- historical은 issued_at <= known_at (보고서 D-8-3 — 미래지식 누출 차단)
    CONSTRAINT ck_weather_value_bitemporal_order CHECK (
        issued_at IS NULL OR issued_at <= known_at
    )
);

-- native semantic tuple UNIQUE — NULLS NOT DISTINCT (ADR-072 결정 3).
-- 실 전환은 CREATE UNIQUE INDEX CONCURRENTLY + writer conflict target 동일 cutover
-- (ADR-075 결정 5).
CREATE UNIQUE INDEX uq_weather_value_identity
    ON feature.feature_weather_values (
        feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
        issued_at, valid_at, observed_at
    )
    NULLS NOT DISTINCT;

-- target_at/known_at hot path 복합 B-tree (ADR-072 결정 5)
CREATE INDEX idx_weather_values_feature_target_known
    ON feature.feature_weather_values (feature_id, target_at DESC, known_at DESC);

-- current weather summary (ADR-072 결정 4, T-VN-38A) — bbox 매행 LATERAL을
-- set JOIN으로 치환하는 검증 가능 projection. 원본 이력에서 재생성 가능하다.
-- reconciliation 절차·summary 값 컬럼 확장: 미정(T-VN-38A 구현 소관)
CREATE TABLE feature.current_weather_summary (
    feature_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    weather_domain text NOT NULL,
    forecast_style text NOT NULL,
    metric_key text NOT NULL,
    timeline_bucket text,
    target_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    value_number numeric(14, 4),
    value_text text,
    unit text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_current_weather_summary_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_current_weather_summary_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_current_weather_summary_value_present CHECK (
        value_number IS NOT NULL OR value_text IS NOT NULL
    )
);

-- summary identity — nullable 구성원(timeline_bucket) 포함 NULLS NOT DISTINCT
-- (ADR-072 결정 3의 summary 적용).
CREATE UNIQUE INDEX uq_current_weather_summary_identity
    ON feature.current_weather_summary (
        feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
        timeline_bucket
    )
    NULLS NOT DISTINCT;

-- =============================================================================
-- 11. price history + current summary (ADR-078, T-VN-38B)
-- =============================================================================
-- 현행 feature.feature_price_values의 목표형(feature_id uuid). series identity는
-- `(feature_id, provider, price_domain, product_key)` (ADR-078 결정 1).
-- provider 문자열의 provider_dataset_id FK 수렴(ADR-069 결정 5와의 조정):
-- 미정(T-VN-38B·T-VN-33B 조율 소관)
CREATE TABLE feature.feature_price_values (
    price_value_key text NOT NULL,
    feature_id uuid NOT NULL,
    provider text NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    observed_at timestamptz NOT NULL,
    value_number numeric(14, 4) NOT NULL,
    unit text NOT NULL DEFAULT 'KRW',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_record_key text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_price_values PRIMARY KEY (price_value_key),
    CONSTRAINT fk_price_values_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_value_source_record FOREIGN KEY (source_record_key)
        REFERENCES provider_sync.source_records (source_record_key) ON DELETE SET NULL,
    CONSTRAINT ck_price_value_nonnegative CHECK (value_number >= 0),
    CONSTRAINT ck_price_value_payload_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT uq_price_value_identity UNIQUE (
        feature_id, provider, price_domain, product_key, observed_at
    )
);

-- history access path (ADR-078 결정 5)
CREATE INDEX idx_price_values_feature_observed_identity
    ON feature.feature_price_values (
        feature_id, observed_at DESC, provider, price_domain, product_key
    );

-- current price summary (T-VN-38B) — series identity당 current 1건.
-- restore/backfill generation 구분의 표현(전용 컬럼 vs restore epoch 참조):
-- 미정(T-VN-38B 구현 소관)
CREATE TABLE feature.current_price_summary (
    feature_id uuid NOT NULL,
    provider text NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    observed_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    value_number numeric(14, 4) NOT NULL,
    unit text NOT NULL DEFAULT 'KRW',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_current_price_summary PRIMARY KEY (
        feature_id, provider, price_domain, product_key
    ),
    CONSTRAINT fk_current_price_summary_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT ck_current_price_summary_nonnegative CHECK (value_number >= 0)
);

-- =============================================================================
-- 12. curation 단일 write model (보고서 F-16, T-VN-40)
-- =============================================================================
-- feature.curation_collections/curation_items가 유일한 write model이다. legacy
-- feature.curated_features overlay·단방향 trigger·legacy route는 목표 상태에
-- 존재하지 않는다(fence는 T-VN-40C, 물리 삭제는 T-VN-39 removal manifest).
-- 아래는 현행 canonical 모델의 **최소형**이다 — Wave 2 결정이 걸린 부분
-- (archive 결합 CHECK, feature_id uuid 전환)만 고정하고, 나머지 현행 컬럼
-- (source/import/link-decision 계열)은 현행 정본을 유지한다.

CREATE TABLE feature.curated_themes (
    theme_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    theme_key text NOT NULL,
    title text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_curated_themes PRIMARY KEY (theme_id),
    CONSTRAINT uq_curated_themes_key UNIQUE (theme_key),
    CONSTRAINT ck_curated_themes_key_canonical CHECK (
        theme_key <> '' AND theme_key = btrim(theme_key)
    ),
    CONSTRAINT ck_curated_themes_title CHECK (btrim(title) <> '')
);

CREATE TABLE feature.curation_collections (
    collection_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    collection_key text NOT NULL,
    theme_id uuid NOT NULL,
    title text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    visibility text NOT NULL DEFAULT 'admin_only',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT pk_curation_collections PRIMARY KEY (collection_id),
    CONSTRAINT uq_curation_collections_key UNIQUE (collection_key),
    CONSTRAINT fk_curation_collections_theme FOREIGN KEY (theme_id)
        REFERENCES feature.curated_themes (theme_id) ON DELETE RESTRICT,
    CONSTRAINT ck_curation_collections_key CHECK (btrim(collection_key) <> ''),
    CONSTRAINT ck_curation_collections_title CHECK (btrim(title) <> ''),
    CONSTRAINT ck_curation_collections_status CHECK (
        status IN ('draft', 'published', 'archived')
    ),
    CONSTRAINT ck_curation_collections_visibility CHECK (
        visibility IN ('admin_only', 'public')
    ),
    -- archive 상태·archived_at 결합 CHECK (보고서 §3 curation 행 — F-16)
    CONSTRAINT ck_curation_collections_archive_pair CHECK (
        (status = 'archived') = (archived_at IS NOT NULL)
    )
);

CREATE TABLE feature.curation_items (
    curation_item_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    collection_id uuid NOT NULL,
    feature_id uuid,
    status text NOT NULL DEFAULT 'candidate',
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT pk_curation_items PRIMARY KEY (curation_item_id),
    CONSTRAINT fk_curation_items_collection FOREIGN KEY (collection_id)
        REFERENCES feature.curation_collections (collection_id) ON DELETE CASCADE,
    CONSTRAINT fk_curation_items_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE SET NULL,
    CONSTRAINT ck_curation_items_status CHECK (
        status IN ('candidate', 'included', 'rejected', 'archived')
    ),
    CONSTRAINT ck_curation_items_sort_order CHECK (sort_order >= 0)
    -- external_item/component identity·import/link-decision 결합 제약은 현행
    -- canonical 정본 유지(본 freeze 재정의 대상 아님).
);

CREATE INDEX idx_curation_items_collection
    ON feature.curation_items (collection_id, status, sort_order);

-- 자동 후보 lifecycle 분리 (T-VN-40B) — 신설.
-- lifecycle 값 집합·검수 전이·candidate 산출 provenance 컬럼: 미정(T-VN-40B 구현 소관)
CREATE TABLE feature.theme_feature_candidates (
    candidate_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
    theme_id uuid NOT NULL,
    feature_id uuid NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_theme_feature_candidates PRIMARY KEY (candidate_id),
    CONSTRAINT fk_theme_feature_candidates_theme FOREIGN KEY (theme_id)
        REFERENCES feature.curated_themes (theme_id) ON DELETE CASCADE,
    CONSTRAINT fk_theme_feature_candidates_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT uq_theme_feature_candidates_identity UNIQUE (theme_id, feature_id),
    CONSTRAINT ck_theme_feature_candidates_status CHECK (btrim(status) <> '')
);

-- =============================================================================
-- 끝. (removal manifest 대상 — 목표 상태에 존재하지 않는 legacy 객체 목록은
-- consumer-rollout-v1.json의 removal_manifest 항목이 정본이다.)
-- =============================================================================
