-- =============================================================================
-- contracts/vnext/target-schema-v1.sql — T-VN-31A vNext target freeze
-- =============================================================================
-- Wave 2(T-VN-32~40)가 구현할 **목표 상태**의 실행 가능 DDL 정본이다.
--
-- 정본 근거:
--   * ADR-066~075 (특히 ADR-067 직교 상태 / ADR-068 UUID identity /
--     ADR-069 provider_datasets / ADR-070 subtype / ADR-071 field override /
--     ADR-072 weather bitemporal), ADR-078 price series identity, ADR-088
--     DB 소유 dataset operation/immutable observation head
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
--   * `ops.import_jobs` 등 T-VN-33 전수 FK/membership 도착점은 이 파일 다음에 적용하는
--     `tvn33-reference-ownership-v1.sql`이 고정한다. 이 파일은 양쪽이 공통으로 쓰는
--     dataset/operation/lineage 최종형을 고정한다.
--   * legacy 산출물(feature.curated_features overlay, source_records denorm 열,
--     features의 legacy status/user_change_* 열 등)은 목표 상태에 **존재하지
--     않으므로** 이 파일에 없다. 물리 삭제 순서는 consumer-rollout-v1.json과
--     T-VN-39 removal manifest가 소유한다.
--   * 현행 0095의 `materialize_user_feature_change_provenance`와
--     `feature_versions` whole-row snapshot은 T-VN-36 effective projection/field
--     override lineage가 대체할 때까지만 쓰는 bridge다. 따라서 post-T36C/T39
--     final target에는 이 procedure·legacy request/version relation을 두지 않는다.
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
-- 2. provider_sync.provider_datasets — provider×dataset identity 정본 (ADR-069/087)
-- =============================================================================
CREATE FUNCTION provider_sync.is_valid_provider_dataset_capabilities(value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog
AS $$
DECLARE
    produced text;
BEGIN
    IF jsonb_typeof(value) <> 'object'
       OR NOT (value ?& ARRAY['schema_version', 'produces', 'extensions'])
       OR (value - ARRAY['schema_version', 'produces', 'extensions']) <> '{}'::jsonb
       OR jsonb_typeof(value -> 'schema_version') IS DISTINCT FROM 'number'
       OR value -> 'schema_version' <> '1'::jsonb
       OR jsonb_typeof(value -> 'produces') IS DISTINCT FROM 'array'
       OR jsonb_typeof(value -> 'extensions') IS DISTINCT FROM 'object'
    THEN
        RETURN false;
    END IF;

    FOR produced IN SELECT jsonb_array_elements_text(value -> 'produces') LOOP
        IF produced NOT IN (
            'place', 'event', 'notice', 'price', 'weather', 'route', 'area', 'enrichment'
        ) THEN
            RETURN false;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(value -> 'produces') AS item(value)
        GROUP BY item.value HAVING count(*) > 1
    ) THEN
        RETURN false;
    END IF;

    RETURN true;
END;
$$;

CREATE FUNCTION provider_sync.is_valid_provider_dataset_sync_scope(
    value text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT value IN ('dataset_wide', 'target_grids')
        OR value ~ '^external_system:[^[:space:]][^[:space:]]{0,111}$'
$$;

CREATE TABLE provider_sync.provider_datasets (
    -- surrogate 타입(bigint identity)은 본 freeze가 고정한다(ADR-069는 침묵).
    provider_dataset_id bigint GENERATED ALWAYS AS IDENTITY,
    provider text NOT NULL,
    dataset_key text NOT NULL,
    display_name text NOT NULL,
    source_kind text NOT NULL,
    -- 활성 상태 (ADR-069 결정 1)
    is_active boolean NOT NULL DEFAULT true,
    -- capability는 dataset의 산출 metadata만 소유한다. 실행 가능 operation과 scope는
    -- provider_dataset_operations 및 그 정규 scope child가 유일하게 소유한다(ADR-088).
    capabilities jsonb NOT NULL DEFAULT
        '{"schema_version":1,"produces":[],"extensions":{}}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_datasets PRIMARY KEY (provider_dataset_id),
    CONSTRAINT uq_provider_datasets_identity UNIQUE (provider, dataset_key),
    CONSTRAINT ck_provider_datasets_provider_canonical CHECK (
        provider <> '' AND provider = btrim(provider)
        AND provider = normalize(provider, NFC) AND length(provider) <= 112
    ),
    CONSTRAINT ck_provider_datasets_dataset_key_canonical CHECK (
        dataset_key <> '' AND dataset_key = btrim(dataset_key)
        AND dataset_key = normalize(dataset_key, NFC) AND length(dataset_key) <= 112
    ),
    CONSTRAINT ck_provider_datasets_display_name_canonical CHECK (
        display_name <> '' AND display_name = btrim(display_name)
        AND display_name = normalize(display_name, NFC) AND length(display_name) <= 256
    ),
    CONSTRAINT ck_provider_datasets_source_kind CHECK (
        source_kind IN ('openapi', 'filedata', 'manual', 'system', 'standard', 'internal')
    ),
    CONSTRAINT ck_provider_datasets_capabilities CHECK (
        provider_sync.is_valid_provider_dataset_capabilities(capabilities)
    )
);

CREATE FUNCTION provider_sync.reject_provider_dataset_identity_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key
    THEN
        RAISE EXCEPTION 'provider dataset identity is immutable (ADR-088)'
            USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.touch_provider_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_provider_dataset_identity_immutable
    BEFORE UPDATE OF provider, dataset_key ON provider_sync.provider_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_provider_dataset_identity_update();

CREATE TRIGGER trg_provider_dataset_touch
    BEFORE UPDATE ON provider_sync.provider_datasets
    FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset();

CREATE TABLE provider_sync.provider_dataset_operations (
    provider_dataset_id bigint NOT NULL,
    operation_key text NOT NULL,
    operation_kind text NOT NULL,
    is_enabled boolean NOT NULL DEFAULT true,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_dataset_operations PRIMARY KEY (provider_dataset_id, operation_key),
    CONSTRAINT fk_provider_dataset_operations_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT ck_provider_dataset_operations_key_canonical CHECK (
        operation_key <> '' AND operation_key = btrim(operation_key)
        AND operation_key = normalize(operation_key, NFC) AND length(operation_key) <= 128
    ),
    CONSTRAINT ck_provider_dataset_operations_kind CHECK (
        operation_kind IN ('feature_load', 'refresh', 'preview')
    ),
    CONSTRAINT uq_provider_dataset_operations_kind UNIQUE (
        provider_dataset_id, operation_key, operation_kind
    ),
    CONSTRAINT ck_provider_dataset_operations_config CHECK (jsonb_typeof(config) = 'object')
);

CREATE INDEX idx_provider_dataset_operations_enabled
    ON provider_sync.provider_dataset_operations (provider_dataset_id, operation_key)
    WHERE is_enabled;

CREATE FUNCTION provider_sync.assert_active_provider_dataset(dataset_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF dataset_id IS NULL THEN
        RETURN;
    END IF;
    PERFORM 1
    FROM provider_sync.provider_datasets AS dataset
    WHERE dataset.provider_dataset_id = dataset_id
      AND dataset.is_active
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive normal writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_provider_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id
    THEN
        RAISE EXCEPTION 'provider dataset ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.assert_active_source_entity_dataset(entity_key text)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM 1
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = entity.provider_dataset_id
    WHERE entity.source_entity_key = entity_key
      AND dataset.is_active
    FOR SHARE OF dataset;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'inactive provider dataset cannot receive lineage writes'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
    END IF;
END;
$$;

CREATE FUNCTION provider_sync.reject_inactive_source_entity_dataset()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key
    THEN
        RAISE EXCEPTION 'source entity ownership is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entity_ownership_immutable';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        PERFORM provider_sync.assert_active_source_entity_dataset(OLD.source_entity_key);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM provider_sync.assert_active_source_entity_dataset(NEW.source_entity_key);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION provider_sync.touch_provider_dataset_operation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_provider_dataset_operations_active_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_dataset_operations
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE TRIGGER trg_provider_dataset_operations_touch
    BEFORE UPDATE ON provider_sync.provider_dataset_operations
    FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset_operation();

-- =============================================================================
-- 3. feature.features — 축소된 core (ADR-067·068·070)
-- =============================================================================
-- core에는 UUID·kind·name·category FK·직교 3상태·row_revision만 남는다
-- (ADR-070 결정 1). 좌표/geometry/detail/주소/URL 등은 subtype 소관이다.
-- 0095 current head는 아직 text business ``feature_id``와 ``feature_uuid`` shadow를
-- 병행한다. 이 target UUID key와 UUID procedure signature는 T39 physical re-key 뒤의
-- final shape이며, current writer의 text procedure signature를 이 target에 섞지 않는다.
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
    -- T-VN-34A: active 3×2 여섯 tuple과 retired/suppressed 2 tuple만 유효하다.
    -- published + quarantined는 의도적으로 유효하다(quality 복구만으로 재공개).
    CONSTRAINT ck_features_state_tuple CHECK (
        lifecycle_state = 'active' OR publication_state = 'suppressed'
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

-- T-VN-34B: category/keyset/text hot paths도 공개 정본의 정확한 3축을 partial
-- predicate로 직접 가진다. status/deleted_at 같은 legacy surrogate는 섞지 않는다.
CREATE INDEX idx_features_public_kind_category
    ON feature.features (kind, category_code)
    WHERE lifecycle_state = 'active'
      AND publication_state = 'published'
      AND quality_state = 'valid';
CREATE INDEX idx_features_public_updated_keyset
    ON feature.features (updated_at DESC, feature_id DESC)
    WHERE lifecycle_state = 'active'
      AND publication_state = 'published'
      AND quality_state = 'valid';
CREATE INDEX idx_features_public_lower_name_keyset
    ON feature.features (lower(name), feature_id)
    WHERE lifecycle_state = 'active'
      AND publication_state = 'published'
      AND quality_state = 'valid';
CREATE INDEX idx_features_public_name_trgm
    ON feature.features USING gin (name x_extension.gin_trgm_ops)
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

-- 3.1 full-tuple 전이 감사 이력 (ADR-090). Feature purge 뒤에도 business
-- identifier/audit evidence는 남아야 하므로 Feature FK나 cascade를 두지 않는다.
-- current 0095 audit은 purge 보존을 위해 text legacy key와 ``feature_uuid``를 함께
-- 기록하고, T39가 legacy key를 제거한 뒤 이 final UUID identity 열로 수렴한다.
CREATE TABLE feature.feature_state_transitions (
    transition_id bigint GENERATED ALWAYS AS IDENTITY,
    feature_id uuid NOT NULL,
    from_lifecycle_state text,
    from_publication_state text,
    from_quality_state text,
    to_lifecycle_state text NOT NULL,
    to_publication_state text NOT NULL,
    to_quality_state text NOT NULL,
    transition_kind text NOT NULL,
    reason_code text NOT NULL,
    principal text NOT NULL,
    causation_ref text,
    provider_dataset_id bigint,
    source_entity_key text,
    source_record_key text,
    provider_evidence jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    row_revision bigint NOT NULL,
    invoker_role text NOT NULL,
    state_procedure_definer text NOT NULL,
    audit_writer_definer text NOT NULL,
    CONSTRAINT pk_feature_state_transitions PRIMARY KEY (transition_id),
    CONSTRAINT ck_feature_state_transitions_kind CHECK (
        transition_kind IN (
            'initial', 'legacy_backfill', 'provider_sync', 'admin',
            'user_request', 'merge', 'quality_validation', 'system'
        )
    ),
    CONSTRAINT ck_feature_state_transitions_reason CHECK (btrim(reason_code) <> ''),
    CONSTRAINT ck_feature_state_transitions_principal CHECK (btrim(principal) <> ''),
    CONSTRAINT ck_feature_state_transitions_old_tuple CHECK (
        (from_lifecycle_state IS NULL AND from_publication_state IS NULL AND from_quality_state IS NULL)
        OR (
            from_lifecycle_state IN ('active', 'retired')
            AND from_publication_state IN ('draft', 'published', 'suppressed')
            AND from_quality_state IN ('valid', 'quarantined')
            AND (from_lifecycle_state = 'active' OR from_publication_state = 'suppressed')
        )
    ),
    CONSTRAINT ck_feature_state_transitions_new_tuple CHECK (
        to_lifecycle_state IN ('active', 'retired')
        AND to_publication_state IN ('draft', 'published', 'suppressed')
        AND to_quality_state IN ('valid', 'quarantined')
        AND (to_lifecycle_state = 'active' OR to_publication_state = 'suppressed')
    ),
    CONSTRAINT ck_feature_state_transitions_initial_old_tuple CHECK (
        (
            from_lifecycle_state IS NULL
            AND transition_kind IN ('initial', 'legacy_backfill', 'provider_sync')
        ) OR (
            from_lifecycle_state IS NOT NULL
            AND transition_kind NOT IN ('initial', 'legacy_backfill')
        )
    ),
    CONSTRAINT ck_feature_state_transitions_provider_provenance CHECK (
        (
            transition_kind = 'provider_sync'
            AND provider_dataset_id IS NOT NULL
            AND btrim(source_entity_key) <> ''
            AND btrim(source_record_key) <> ''
            AND jsonb_typeof(provider_evidence) = 'object'
            AND jsonb_typeof(provider_evidence -> 'authoritative_receipt') = 'string'
            AND btrim(provider_evidence ->> 'authoritative_receipt') <> ''
        ) OR (
            transition_kind <> 'provider_sync'
            AND provider_dataset_id IS NULL
            AND source_entity_key IS NULL
            AND source_record_key IS NULL
            AND provider_evidence IS NULL
        )
    ),
    CONSTRAINT ck_feature_state_transitions_row_revision CHECK (row_revision >= 1)
);

CREATE INDEX idx_feature_state_transitions_feature_occurred
    ON feature.feature_state_transitions (feature_id, occurred_at, transition_id);

-- T-VN-34A privilege boundary. LOGIN runtime/migrator provisioning and DSN activation
-- are deployment-owned; these NOLOGIN roles are the schema-level grant targets.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_state_procedure_owner') THEN
        CREATE ROLE ktm_feature_state_procedure_owner NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_audit_writer') THEN
        CREATE ROLE ktm_feature_audit_writer NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ktm_feature_runtime') THEN
        CREATE ROLE ktm_feature_runtime NOLOGIN NOINHERIT;
    END IF;
END;
$$;

CREATE FUNCTION feature.prepare_feature_state_context(p_context jsonb, p_mode text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_kind text;
    v_reason text;
    v_principal text;
    v_dataset_id bigint;
    v_source_entity_key text;
    v_source_record_key text;
    v_provider_receipt text;
    v_context jsonb;
BEGIN
    IF jsonb_typeof(p_context) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature state context must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_context) AS key_name(key_name)
        WHERE key_name NOT IN (
            'transition_kind', 'reason_code', 'principal', 'causation_ref',
            'provider_dataset_id', 'source_entity_key', 'source_record_key',
            'reactivation_evidence'
        )
    ) THEN
        RAISE EXCEPTION 'feature state context contains an unknown key'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_kind := p_context ->> 'transition_kind';
    v_reason := p_context ->> 'reason_code';
    IF v_kind NOT IN (
        'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
        'merge', 'quality_validation', 'system'
    ) OR v_reason IS NULL OR btrim(v_reason) = ''
       OR (p_mode = 'create' AND v_kind NOT IN ('initial', 'legacy_backfill', 'provider_sync'))
       OR (p_mode = 'transition' AND v_kind IN ('initial', 'legacy_backfill')) THEN
        RAISE EXCEPTION 'feature state context has invalid kind, reason, or mode'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    IF v_kind = 'provider_sync' THEN
        IF (p_context ->> 'provider_dataset_id') !~ '^[1-9][0-9]*$'
           OR p_context ? 'principal'
           OR jsonb_typeof(p_context -> 'source_entity_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_entity_key') = ''
           OR jsonb_typeof(p_context -> 'source_record_key') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'source_record_key') = '' THEN
            RAISE EXCEPTION 'provider state principal must derive from an active dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_dataset_id := (p_context ->> 'provider_dataset_id')::bigint;
        v_source_entity_key := btrim(p_context ->> 'source_entity_key');
        v_source_record_key := btrim(p_context ->> 'source_record_key');
        SELECT 'provider:' || provider || '/' || dataset_key INTO v_principal
        FROM provider_sync.provider_datasets
        WHERE provider_dataset_id = v_dataset_id AND is_active;
        IF v_principal IS NULL THEN
            RAISE EXCEPTION 'provider dataset must be active'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        SELECT record.raw_payload_hash
          INTO v_provider_receipt
          FROM provider_sync.source_records AS record
          JOIN provider_sync.source_entities AS entity
            ON entity.source_entity_key = record.source_entity_key
          JOIN provider_sync.source_entity_heads AS head
            ON head.source_entity_key = entity.source_entity_key
           AND head.current_source_record_key = record.source_record_key
         WHERE record.source_record_key = v_source_record_key
           AND record.source_entity_key = v_source_entity_key
           AND entity.provider_dataset_id = v_dataset_id;
        IF v_provider_receipt IS NULL OR btrim(v_provider_receipt) = '' THEN
            RAISE EXCEPTION 'provider state context source does not belong to the active dataset'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
        END IF;
    ELSE
        IF p_context ? 'provider_dataset_id'
           OR jsonb_typeof(p_context -> 'principal') IS DISTINCT FROM 'string'
           OR btrim(p_context ->> 'principal') = '' THEN
            RAISE EXCEPTION 'non-provider state context requires authenticated principal'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
        END IF;
        v_principal := btrim(p_context ->> 'principal');
    END IF;
    IF p_context ? 'causation_ref'
       AND jsonb_typeof(p_context -> 'causation_ref') NOT IN ('string', 'null') THEN
        RAISE EXCEPTION 'causation_ref must be a string or null'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_context := jsonb_build_object(
        'transition_kind', v_kind,
        'reason_code', btrim(v_reason),
        'principal', v_principal,
        'causation_ref', p_context -> 'causation_ref'
    );
    IF v_dataset_id IS NOT NULL THEN
        v_context := v_context || jsonb_build_object(
            'provider_dataset_id', v_dataset_id,
            'source_entity_key', v_source_entity_key,
            'source_record_key', v_source_record_key,
            'provider_evidence', jsonb_build_object(
                'authoritative_receipt', v_provider_receipt
            )
        );
    END IF;
    IF p_context ? 'reactivation_evidence' THEN
        v_context := v_context || jsonb_build_object('reactivation_evidence', p_context -> 'reactivation_evidence');
    END IF;
    PERFORM set_config('feature.state_transition_context', v_context::text, true);
    PERFORM set_config('feature.state_procedure_definer', current_user::text, true);
END;
$$;

CREATE FUNCTION feature.write_feature_state_transition()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_context jsonb;
    v_context_text text;
    v_definer text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.lifecycle_state IS NOT DISTINCT FROM NEW.lifecycle_state
       AND OLD.publication_state IS NOT DISTINCT FROM NEW.publication_state
       AND OLD.quality_state IS NOT DISTINCT FROM NEW.quality_state THEN
        RETURN NULL;
    END IF;
    v_context_text := current_setting('feature.state_transition_context', true);
    v_definer := current_setting('feature.state_procedure_definer', true);
    IF v_context_text IS NULL OR v_definer <> 'ktm_feature_state_procedure_owner'
       OR current_user <> 'ktm_feature_audit_writer' THEN
        -- migration/schema owner is outside the runtime trust boundary; fixture and
        -- fresh target seeding use that privileged identity. Runtime grants deny DML.
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles
            WHERE rolname = session_user AND rolsuper
        ) THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'feature state mutation requires state procedure context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_context := v_context_text::jsonb;
    IF (v_context ->> 'transition_kind') NOT IN (
            'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
            'merge', 'quality_validation', 'system'
       ) OR coalesce(btrim(v_context ->> 'reason_code'), '') = ''
       OR coalesce(btrim(v_context ->> 'principal'), '') = '' THEN
        RAISE EXCEPTION 'feature state context is malformed'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    IF TG_OP = 'INSERT' AND (v_context ->> 'transition_kind') NOT IN (
        'initial', 'legacy_backfill', 'provider_sync'
    ) THEN
        RAISE EXCEPTION 'feature insert has invalid transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;
    IF TG_OP = 'UPDATE' AND (v_context ->> 'transition_kind') IN ('initial', 'legacy_backfill') THEN
        RAISE EXCEPTION 'feature update has invalid transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;
    INSERT INTO feature.feature_state_transitions (
        feature_id,
        from_lifecycle_state, from_publication_state, from_quality_state,
        to_lifecycle_state, to_publication_state, to_quality_state,
        transition_kind, reason_code, principal, causation_ref,
        provider_dataset_id, source_entity_key, source_record_key, provider_evidence,
        occurred_at,
        row_revision, invoker_role, state_procedure_definer, audit_writer_definer
    ) VALUES (
        NEW.feature_id,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.lifecycle_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.publication_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.quality_state END,
        NEW.lifecycle_state, NEW.publication_state, NEW.quality_state,
        v_context ->> 'transition_kind', v_context ->> 'reason_code',
        v_context ->> 'principal', v_context ->> 'causation_ref',
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN (v_context ->> 'provider_dataset_id')::bigint END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_entity_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_record_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context -> 'provider_evidence' END,
        clock_timestamp(),
        NEW.row_revision, session_user::text, v_definer, current_user::text
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION feature.reject_feature_state_transition_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'feature state transitions are append-only'
        USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_state_transitions_append_only';
END;
$$;

CREATE PROCEDURE feature.create_feature_with_initial_state(
    IN p_feature jsonb,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_context jsonb,
    OUT o_feature_id uuid,
    OUT o_row_revision bigint,
    OUT o_inserted boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_feature_id uuid;
    v_kind text;
    v_name text;
    v_category_code text;
BEGIN
    IF jsonb_typeof(p_feature) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'feature payload must be an object'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_feature) AS key_name(key_name)
        WHERE key_name NOT IN ('feature_id', 'kind', 'name', 'category_code')
    ) OR p_feature ?| ARRAY[
        'status', 'deleted_at', 'user_deleted_at', 'user_deleted_by',
        'user_change_kind', 'user_change_status', 'user_change_request_id',
        'user_change_reason', 'lifecycle_state', 'publication_state', 'quality_state'
    ] THEN
        RAISE EXCEPTION 'feature create payload contains a forbidden or unknown field'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    v_feature_id := nullif(btrim(p_feature ->> 'feature_id'), '')::uuid;
    v_kind := nullif(btrim(p_feature ->> 'kind'), '');
    v_name := nullif(btrim(p_feature ->> 'name'), '');
    v_category_code := nullif(btrim(p_feature ->> 'category_code'), '');
    IF v_feature_id IS NULL OR v_kind IS NULL OR v_name IS NULL
       OR v_category_code IS NULL THEN
        RAISE EXCEPTION 'feature payload lacks required core fields'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_create_payload';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'create');
    INSERT INTO feature.features (
        feature_id, kind, name, category_code,
        lifecycle_state, publication_state, quality_state
    ) VALUES (
        v_feature_id, v_kind, v_name, v_category_code,
        p_lifecycle_state, p_publication_state, p_quality_state
    ) ON CONFLICT (feature_id) DO NOTHING
    RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
    o_inserted := FOUND;
    IF NOT o_inserted THEN
        SELECT feature_id, row_revision INTO o_feature_id, o_row_revision
        FROM feature.features WHERE feature_id = v_feature_id;
    END IF;
END;
$$;

CREATE PROCEDURE feature.transition_feature_state(
    IN p_feature_id uuid,
    IN p_lifecycle_state text,
    IN p_publication_state text,
    IN p_quality_state text,
    IN p_expected_row_revision bigint,
    IN p_context jsonb,
    OUT o_feature_id uuid,
    OUT o_row_revision bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_current feature.features%ROWTYPE;
BEGIN
    IF p_expected_row_revision IS NULL OR p_expected_row_revision < 1 THEN
        RAISE EXCEPTION 'expected row revision is required'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_expected_revision';
    END IF;
    PERFORM feature.prepare_feature_state_context(p_context, 'transition');
    SELECT * INTO v_current FROM feature.features
    WHERE feature_id = p_feature_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature does not exist' USING ERRCODE = 'P0002';
    END IF;
    IF v_current.row_revision <> p_expected_row_revision THEN
        RAISE EXCEPTION 'feature revision changed' USING ERRCODE = '40001';
    END IF;
    IF (v_current.lifecycle_state, v_current.publication_state, v_current.quality_state)
       IS NOT DISTINCT FROM (p_lifecycle_state, p_publication_state, p_quality_state) THEN
        RAISE EXCEPTION 'feature state transition must change an axis'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_non_noop';
    END IF;
    IF p_context ->> 'transition_kind' = 'provider_sync'
       AND (
            (v_current.lifecycle_state = 'active' AND p_lifecycle_state = 'retired')
            OR (v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active')
       )
       AND NOT EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS link
            JOIN provider_sync.source_entities AS entity
              ON entity.source_entity_key = link.source_entity_key
            JOIN provider_sync.source_records AS record
              ON record.source_entity_key = entity.source_entity_key
            JOIN provider_sync.source_entity_heads AS head
              ON head.source_entity_key = entity.source_entity_key
             AND head.current_source_record_key = record.source_record_key
            WHERE link.feature_id = p_feature_id
              AND link.source_entity_key = p_context ->> 'source_entity_key'
              AND entity.provider_dataset_id = (p_context ->> 'provider_dataset_id')::bigint
              AND record.source_record_key = p_context ->> 'source_record_key'
       ) THEN
        RAISE EXCEPTION 'provider lifecycle transition requires linked authoritative source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
    END IF;
    IF v_current.lifecycle_state = 'retired' AND p_lifecycle_state = 'active' THEN
        IF p_context ->> 'transition_kind' <> 'provider_sync'
           AND (p_context ->> 'transition_kind' NOT IN ('admin', 'user_request', 'system')
           OR coalesce(btrim(p_context ->> 'reactivation_evidence'), '') = '') THEN
            RAISE EXCEPTION 'retired feature may be reactivated only by explicit reingest'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_reactivation_explicit';
        END IF;
        IF p_context ->> 'transition_kind' = 'provider_sync' AND EXISTS (
            SELECT 1 FROM ops.feature_overrides AS override
            WHERE override.feature_id = p_feature_id
              AND override.field_path = 'lifecycle_state'
              AND override.status = 'active'
              AND override.override_value = '"retired"'::jsonb
              AND override.prevent_provider_reactivation
        ) THEN
            RAISE EXCEPTION 'provider reactivation is fenced by lifecycle override'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_reactivation_override';
        END IF;
    END IF;
    UPDATE feature.features
       SET lifecycle_state = p_lifecycle_state,
           publication_state = p_publication_state,
           quality_state = p_quality_state,
           updated_at = clock_timestamp()
     WHERE feature_id = p_feature_id
     RETURNING feature_id, row_revision INTO o_feature_id, o_row_revision;
END;
$$;

ALTER FUNCTION feature.prepare_feature_state_context(jsonb, text)
    OWNER TO ktm_feature_state_procedure_owner;
ALTER PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb)
    OWNER TO ktm_feature_state_procedure_owner;
ALTER PROCEDURE feature.transition_feature_state(uuid, text, text, text, bigint, jsonb)
    OWNER TO ktm_feature_state_procedure_owner;
ALTER FUNCTION feature.write_feature_state_transition()
    OWNER TO ktm_feature_audit_writer;
ALTER FUNCTION feature.reject_feature_state_transition_mutation()
    OWNER TO ktm_feature_audit_writer;

CREATE TRIGGER trg_features_state_transition_audit
    AFTER INSERT OR UPDATE OF lifecycle_state, publication_state, quality_state
    ON feature.features FOR EACH ROW EXECUTE FUNCTION feature.write_feature_state_transition();
CREATE TRIGGER trg_feature_state_transitions_append_only_row
    BEFORE UPDATE OR DELETE ON feature.feature_state_transitions
    FOR EACH ROW EXECUTE FUNCTION feature.reject_feature_state_transition_mutation();
CREATE TRIGGER trg_feature_state_transitions_append_only_truncate
    BEFORE TRUNCATE ON feature.feature_state_transitions
    FOR EACH STATEMENT EXECUTE FUNCTION feature.reject_feature_state_transition_mutation();

GRANT USAGE ON SCHEMA feature, provider_sync, ops
    TO ktm_feature_state_procedure_owner, ktm_feature_audit_writer, ktm_feature_runtime;
-- Runtime subtype geometry DML and qualified PostGIS reads must resolve the
-- x_extension type/functions without inheriting an ambient search_path.
GRANT USAGE ON SCHEMA x_extension
    TO ktm_feature_state_procedure_owner, ktm_feature_runtime;
GRANT SELECT, INSERT ON feature.features TO ktm_feature_state_procedure_owner;
GRANT UPDATE (lifecycle_state, publication_state, quality_state, updated_at)
    ON feature.features TO ktm_feature_state_procedure_owner;
GRANT SELECT ON provider_sync.provider_datasets TO ktm_feature_state_procedure_owner;
GRANT INSERT ON feature.feature_state_transitions TO ktm_feature_audit_writer;
GRANT USAGE, SELECT ON SEQUENCE feature.feature_state_transitions_transition_id_seq
    TO ktm_feature_audit_writer;
GRANT EXECUTE ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb)
    TO ktm_feature_runtime;
GRANT EXECUTE ON PROCEDURE feature.transition_feature_state(uuid, text, text, text, bigint, jsonb)
    TO ktm_feature_runtime;
GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime;
REVOKE ALL ON feature.feature_state_transitions FROM PUBLIC, ktm_feature_runtime;
GRANT SELECT ON feature.feature_state_transitions TO ktm_feature_runtime;
REVOKE ALL ON FUNCTION feature.prepare_feature_state_context(jsonb, text) FROM PUBLIC, ktm_feature_runtime;
REVOKE ALL ON FUNCTION feature.write_feature_state_transition() FROM PUBLIC, ktm_feature_runtime;
REVOKE ALL ON FUNCTION feature.reject_feature_state_transition_mutation() FROM PUBLIC, ktm_feature_runtime;
REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state(jsonb, text, text, text, jsonb) FROM PUBLIC;
REVOKE ALL ON PROCEDURE feature.transition_feature_state(uuid, text, text, text, bigint, jsonb) FROM PUBLIC;

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

-- ``create_feature_with_initial_state``가 만든 core row의 alias trigger도 state
-- procedure owner로 실행된다. alias direct DML은 runtime에 grant하지 않는다.
GRANT SELECT, INSERT ON feature.feature_aliases TO ktm_feature_state_procedure_owner;

-- =============================================================================
-- 5. kind별 typed subtype 테이블 (ADR-070)
-- =============================================================================
-- 공통 장치(본 freeze가 고정):
--   * 1:1 — feature_id PK + `(feature_id, kind)` composite FK로 core kind 일치 강제
--   * geometry: canonical 4326 + generated 5179 (보고서 §3)
--   * geometry CHECK 3종: GeometryType(typmod)·ST_IsValid·NOT ST_IsEmpty +
--     anchor 일치 (ADR-070 결정 2)
--   * 공간 인덱스: 정본은 "공개 술어 partial GiST만"이다(보고서 §3:379, D-12
--     결정 3 — full GiST는 write 1.6× 실측 근거로 금지). point의 core geometry는
--     3축 exact predicate를 직접 쓴다. route/area처럼 geometry가 subtype에 있는
--     경우에는 core 정본을 복제하지 않는 DB-owned `public_ready` cache를 써
--     subtype-local `WHERE public_ready` GiST를 고정한다. 아래 T-VN-34B DDL이
--     그 cache, lock/identity fence, 4326 route/area index를 실행 가능하게 정의한다.

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
    -- 3축 core 상태에서만 계산되는 partial-GiST bridge. route/area 이외의
    -- relation에는 이것과 같은 독립 공개 상태를 두지 않는다.
    public_ready boolean NOT NULL DEFAULT false,
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

-- 5.5 area subtype (T-VN-35C) — MultiPolygon (보고서 D-6-2)
CREATE TABLE feature.feature_areas (
    feature_id uuid NOT NULL,
    kind text NOT NULL,
    geom x_extension.geometry(MultiPolygon, 4326) NOT NULL,
    geom_5179 x_extension.geometry(MultiPolygon, 5179)
        GENERATED ALWAYS AS (x_extension.st_transform(geom, 5179)) STORED,
    anchor x_extension.geometry(Point, 4326) NOT NULL,
    -- route와 같은 DB-owned projection cache (visibility 정본은 core 3축).
    public_ready boolean NOT NULL DEFAULT false,
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

-- route/area geometry와 core state는 서로 다른 relation에 있으므로 partial
-- GiST는 join predicate를 직접 표현할 수 없다. 기존 subtype UPDATE가 parent를
-- `FOR UPDATE`로 잠그면 state transition(parent → subtype)과 역순 40P01이 된다.
-- 새 subtype attach만 parent를 잠가 current cache를 만든다. 이미 연결된 subtype은
-- identity를 DB에서 immutable로 막고, payload/geometry UPDATE는 cache를 보존한다.
-- core axis trigger만 existing cache를 변경하므로 서로 교차하는 tuple lock이 없다.
-- supplied public_ready는 항상 DB가 재계산하거나 보존한다.
CREATE FUNCTION feature.derive_subtype_public_ready()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_lifecycle_state text;
    v_publication_state text;
    v_quality_state text;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
           OR NEW.kind IS DISTINCT FROM OLD.kind THEN
            RAISE EXCEPTION 'route/area subtype identity is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_subtype_identity_immutable';
        END IF;
        IF NEW.public_ready IS NOT DISTINCT FROM OLD.public_ready THEN
            RETURN NEW;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id
         FOR UPDATE;
    ELSE
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'route/area public projection requires a parent feature'
            USING ERRCODE = '23503', CONSTRAINT = 'fk_feature_subtype_public_ready_parent';
    END IF;
    NEW.public_ready := v_lifecycle_state = 'active'
        AND v_publication_state = 'published'
        AND v_quality_state = 'valid';
    RETURN NEW;
END;
$$;

CREATE FUNCTION feature.sync_subtype_public_ready()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_public_ready boolean;
BEGIN
    v_public_ready := NEW.lifecycle_state = 'active'
        AND NEW.publication_state = 'published'
        AND NEW.quality_state = 'valid';
    UPDATE feature.feature_routes
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    UPDATE feature.feature_areas
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    RETURN NULL;
END;
$$;

ALTER FUNCTION feature.derive_subtype_public_ready()
    OWNER TO ktm_feature_state_procedure_owner;
ALTER FUNCTION feature.sync_subtype_public_ready()
    OWNER TO ktm_feature_state_procedure_owner;

CREATE TRIGGER trg_feature_routes_public_ready
    BEFORE INSERT OR UPDATE ON feature.feature_routes
    FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready();
CREATE TRIGGER trg_feature_areas_public_ready
    BEFORE INSERT OR UPDATE ON feature.feature_areas
    FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready();
CREATE TRIGGER trg_features_sync_subtype_public_ready
    AFTER UPDATE OF lifecycle_state, publication_state, quality_state
    ON feature.features FOR EACH ROW
    WHEN (
        OLD.lifecycle_state IS DISTINCT FROM NEW.lifecycle_state
        OR OLD.publication_state IS DISTINCT FROM NEW.publication_state
        OR OLD.quality_state IS DISTINCT FROM NEW.quality_state
    )
    EXECUTE FUNCTION feature.sync_subtype_public_ready();

CREATE INDEX idx_feature_routes_geom_gist
    ON feature.feature_routes USING gist (geom)
    WHERE public_ready;
CREATE INDEX idx_feature_areas_geom_gist
    ON feature.feature_areas USING gist (geom)
    WHERE public_ready;

-- Runtime gets exactly the subtype business columns. INSERT creates the fixed
-- subtype identity; UPDATE cannot reattach it or delete a geometry relation.
-- Column-list grants keep table-level UPDATE false and never expose the
-- DB-owned public_ready flag.
REVOKE ALL ON feature.feature_routes, feature.feature_areas FROM PUBLIC, ktm_feature_runtime;
GRANT SELECT ON feature.feature_routes, feature.feature_areas TO ktm_feature_runtime;
GRANT INSERT (
    feature_id, kind, geom, anchor
) ON feature.feature_routes TO ktm_feature_runtime;
GRANT UPDATE (
    geom, anchor
) ON feature.feature_routes TO ktm_feature_runtime;
GRANT INSERT (
    feature_id, kind, geom, anchor
) ON feature.feature_areas TO ktm_feature_runtime;
GRANT UPDATE (
    geom, anchor
) ON feature.feature_areas TO ktm_feature_runtime;
GRANT SELECT (feature_id, public_ready), UPDATE (public_ready)
    ON feature.feature_routes, feature.feature_areas
    TO ktm_feature_state_procedure_owner;
REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready()
    FROM PUBLIC, ktm_feature_runtime;
REVOKE ALL ON FUNCTION feature.sync_subtype_public_ready()
    FROM PUBLIC, ktm_feature_runtime;

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
GRANT SELECT ON feature.public_features TO ktm_feature_runtime;

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
    -- domain fact의 source lineage dataset 일치 복합 FK target (ADR-089).
    CONSTRAINT uq_source_entities_key_dataset UNIQUE (
        source_entity_key, provider_dataset_id
    ),
    CONSTRAINT ck_source_entities_type_canonical CHECK (
        source_entity_type <> '' AND source_entity_type = btrim(source_entity_type)
        AND source_entity_type = normalize(source_entity_type, NFC)
        AND length(source_entity_type) <= 512
    ),
    CONSTRAINT ck_source_entities_id_canonical CHECK (
        source_entity_id <> '' AND source_entity_id = btrim(source_entity_id)
        AND source_entity_id = normalize(source_entity_id, NFC)
        AND length(source_entity_id) <= 512
    ),
    CONSTRAINT ck_source_entities_seen_order CHECK (first_seen_at <= last_seen_at)
    -- head pointer는 source_entity_heads로 분리(순환 FK 제거 — 보고서 D-5-3).
);

CREATE INDEX idx_source_entities_provider_dataset
    ON provider_sync.source_entities (provider_dataset_id);

CREATE TRIGGER trg_source_entities_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_entities
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.provider_dataset_id IS DISTINCT FROM OLD.provider_dataset_id
       OR NEW.source_entity_type IS DISTINCT FROM OLD.source_entity_type
       OR NEW.source_entity_id IS DISTINCT FROM OLD.source_entity_id
    THEN
        RAISE EXCEPTION 'source entity identity is immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entities_identity_immutable';
    END IF;
    IF NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
       OR NEW.last_seen_at < OLD.last_seen_at
    THEN
        RAISE EXCEPTION 'source entity observed time cannot move backwards'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entities_seen_freshness';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_source_entities_identity_and_seen_at
    BEFORE UPDATE ON provider_sync.source_entities
    FOR EACH ROW EXECUTE FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at();

-- 7.2 source_records — immutable payload (ADR-069 결정 2)
-- denorm identity 열(provider/dataset/type/id)과 raw_name/raw_address/raw 좌표
-- 파생 열은 목표 상태에서 제거된다(물리 삭제는 T-VN-33C manifest → T-VN-39).
-- 재관측/만료는 source_entity_heads가 소유한다. record에는 쓰지 않는다.
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
    -- domain fact의 known_at=fetched_at provenance 복합 FK target (ADR-089).
    CONSTRAINT uq_source_records_record_entity_fetched UNIQUE (
        source_record_key, source_entity_key, fetched_at
    ),
    CONSTRAINT ck_source_records_raw_data_object CHECK (jsonb_typeof(raw_data) = 'object'),
    CONSTRAINT ck_source_records_payload_hash_canonical CHECK (
        raw_payload_hash ~ '^[0-9a-f]{1,64}$'
    )
);

-- immutable 보장(ADR-069 결정 2 "immutable raw payload") — UPDATE 거부 트리거.
-- inactive dataset lineage의 DELETE도 normal 경로에서는 active guard가 거부한다.
CREATE FUNCTION provider_sync.reject_source_record_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'provider_sync.source_records is immutable (ADR-069)'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_source_records_immutable';
END;
$$;

CREATE TRIGGER trg_source_records_immutable
    BEFORE UPDATE ON provider_sync.source_records
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_source_record_update();

CREATE TRIGGER trg_source_records_active_dataset_write
    BEFORE INSERT OR DELETE ON provider_sync.source_records
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();

CREATE INDEX idx_source_records_entity_history
    ON provider_sync.source_records (
        source_entity_key, fetched_at DESC, imported_at DESC, source_record_key DESC
    );

-- 7.3 source_entity_heads — 검증된 current pointer (ADR-069 결정 3)
CREATE TABLE provider_sync.source_entity_heads (
    source_entity_key text NOT NULL,
    current_source_record_key text NOT NULL,
    -- incoming observation의 권위 시간. 기존 raw record를 재관측해도 이 값이
    -- 전진하면 current head가 될 수 있다; record.fetched/imported_at은 immutable
    -- snapshot 시각이라 head 선택 기준이 아니다.
    observed_at timestamptz NOT NULL,
    expires_at timestamptz,
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

CREATE FUNCTION provider_sync.enforce_source_entity_head_freshness()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF (NEW.observed_at, NEW.current_source_record_key)
       < (OLD.observed_at, OLD.current_source_record_key)
    THEN
        RAISE EXCEPTION 'source entity head freshness cannot move backwards'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entity_heads_freshness';
    END IF;
    IF NEW.observed_at = OLD.observed_at
       AND NEW.current_source_record_key = OLD.current_source_record_key
       AND NEW.expires_at IS DISTINCT FROM OLD.expires_at
    THEN
        RAISE EXCEPTION 'head expiry needs a newer observation'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entity_heads_expiry_freshness';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_source_entity_heads_freshness
    BEFORE UPDATE ON provider_sync.source_entity_heads
    FOR EACH ROW EXECUTE FUNCTION provider_sync.enforce_source_entity_head_freshness();

CREATE FUNCTION provider_sync.assert_source_entity_head_completeness()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    entity_key text;
    record_count bigint;
    head_count bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        entity_key := OLD.source_entity_key;
    ELSE
        entity_key := NEW.source_entity_key;
    END IF;
    SELECT count(*) INTO record_count
    FROM provider_sync.source_records WHERE source_entity_key = entity_key;
    SELECT count(*) INTO head_count
    FROM provider_sync.source_entity_heads WHERE source_entity_key = entity_key;
    IF (record_count = 0 AND head_count <> 0)
       OR (record_count > 0 AND head_count <> 1)
    THEN
        RAISE EXCEPTION 'source entity head must exist exactly once for records'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_source_entity_heads_complete';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_source_records_head_completeness
    AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_records
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();

CREATE CONSTRAINT TRIGGER trg_source_entity_heads_completeness
    AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_entity_heads
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();

CREATE TRIGGER trg_source_entity_heads_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_entity_heads
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();

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

CREATE TRIGGER trg_source_links_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_links
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();

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
    prevent_provider_reactivation boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'active',
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
    CONSTRAINT ck_feature_overrides_status CHECK (status IN ('active', 'revoked')),
    CONSTRAINT ck_feature_overrides_tombstone_pair CHECK (
        (status = 'active' AND revoked_at IS NULL AND revoked_by IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)
    )
);

-- `(feature_id, field_path)` active UNIQUE (ADR-071 결정 1)
CREATE UNIQUE INDEX uq_feature_overrides_active
    ON ops.feature_overrides (feature_id, field_path)
    WHERE status = 'active';

CREATE INDEX idx_feature_overrides_feature ON ops.feature_overrides (feature_id);

-- State procedures are declared before lineage/override tables so the frozen
-- schema remains sectioned by ownership; grant their read dependencies only
-- after those relations exist.
GRANT SELECT ON provider_sync.source_entities, provider_sync.source_records,
    provider_sync.source_entity_heads, provider_sync.source_links, ops.feature_overrides
    TO ktm_feature_state_procedure_owner;

-- =============================================================================
-- 8A. current summary projection receipt (ADR-089, T-VN-38)
-- =============================================================================
-- 사실의 business time과 projection/rebuild의 실행 시각을 분리한다. summary는 성공한
-- receipt만 복합 FK로 참조한다. run은 weather/price 전체 또는 일부 dataset을 set-based로
-- materialize할 수 있으므로 provider_dataset_id를 row마다 중복 저장하지 않는다.
CREATE TABLE ops.current_summary_runs (
    summary_run_id bigint GENERATED ALWAYS AS IDENTITY,
    projection_kind text NOT NULL,
    run_kind text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    input_count bigint NOT NULL DEFAULT 0,
    inserted_count bigint NOT NULL DEFAULT 0,
    updated_count bigint NOT NULL DEFAULT 0,
    deleted_count bigint NOT NULL DEFAULT 0,
    scope jsonb NOT NULL DEFAULT '{}'::jsonb,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_current_summary_runs PRIMARY KEY (summary_run_id),
    CONSTRAINT uq_current_summary_runs_receipt_state UNIQUE (
        summary_run_id, projection_kind, status
    ),
    CONSTRAINT ck_current_summary_runs_projection_kind CHECK (
        projection_kind IN ('weather', 'price')
    ),
    CONSTRAINT ck_current_summary_runs_run_kind CHECK (
        run_kind IN ('ingest', 'reconcile', 'backfill', 'restore')
    ),
    CONSTRAINT ck_current_summary_runs_status CHECK (
        status IN ('running', 'succeeded', 'failed')
    ),
    CONSTRAINT ck_current_summary_runs_finished_at CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND finished_at >= started_at)
    ),
    CONSTRAINT ck_current_summary_runs_counts_nonnegative CHECK (
        input_count >= 0 AND inserted_count >= 0 AND updated_count >= 0 AND deleted_count >= 0
    ),
    CONSTRAINT ck_current_summary_runs_scope_object CHECK (jsonb_typeof(scope) = 'object'),
    CONSTRAINT ck_current_summary_runs_detail_object CHECK (jsonb_typeof(detail) = 'object')
);

CREATE INDEX idx_current_summary_runs_projection_finished
    ON ops.current_summary_runs (projection_kind, finished_at DESC)
    WHERE status = 'succeeded';

CREATE FUNCTION ops.reject_terminal_current_summary_run_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF OLD.status IN ('succeeded', 'failed') THEN
        RAISE EXCEPTION 'terminal current summary receipt is immutable: %', OLD.summary_run_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_current_summary_runs_terminal_immutable';
    END IF;
    -- 실행 중 receipt만 진행 건수·scope를 갱신하거나 terminal 상태로 전이할 수 있다.
    -- status CHECK가 허용 domain을 제한하므로 failed → succeeded 같은 재개는 불가능하다.
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER trg_current_summary_runs_terminal_immutable
    BEFORE UPDATE OR DELETE ON ops.current_summary_runs
    FOR EACH ROW EXECUTE FUNCTION ops.reject_terminal_current_summary_run_mutation();

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

CREATE TRIGGER trg_notice_states_active_dataset_write
    BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.notice_states
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

-- =============================================================================
-- 10. weather bitemporal history + current summary (ADR-072, T-VN-38A)
-- =============================================================================
-- 현행 feature.feature_weather_values(0060 이후)의 목표형 — 변경점:
--   * final feature_id uuid FK / provider → provider_dataset_id FK (ADR-072 결정 2)
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
    metric_name text,
    source_metric_key text,
    source_metric_name text,
    value_number numeric(14, 4),
    value_text text,
    unit text,
    severity text,
    issued_at timestamptz,
    valid_at timestamptz,
    -- 유효 기간 — range type 채택 (ADR-072 결정 2 "기간은 range type과 순서
    -- 제약을 사용"). 현행 valid_from/valid_until 쌍의 목표형이며 event/notice의
    -- range 표현과 일관된다. 순서 제약은 range type 자체가 강제한다.
    valid_during tstzrange,
    observed_at timestamptz,
    -- bitemporal 축 (ADR-072 결정 1)
    target_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    normalization_version text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_weather_values PRIMARY KEY (weather_value_key),
    CONSTRAINT fk_weather_values_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_weather_values_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_weather_value_source_lineage FOREIGN KEY (
        source_record_key, source_entity_key, known_at
    ) REFERENCES provider_sync.source_records (
        source_record_key, source_entity_key, fetched_at
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_weather_value_source_dataset FOREIGN KEY (
        source_entity_key, provider_dataset_id
    ) REFERENCES provider_sync.source_entities (
        source_entity_key, provider_dataset_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_weather_value_present CHECK (
        value_number IS NOT NULL OR value_text IS NOT NULL
    ),
    CONSTRAINT ck_weather_value_valid_during_not_empty CHECK (
        valid_during IS NULL OR NOT isempty(valid_during)
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
        target_at, source_record_key
    );

-- summary가 다른 feature/dataset/series의 fact를 가리키지 못하게 하는 복합 FK target.
CREATE UNIQUE INDEX uq_weather_value_summary_reference
    ON feature.feature_weather_values (
        weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
    );

-- target_at/known_at hot path 복합 B-tree (ADR-072 결정 5)
CREATE INDEX idx_weather_values_feature_target_known
    ON feature.feature_weather_values (feature_id, target_at DESC, known_at DESC);

CREATE TRIGGER trg_feature_weather_values_active_dataset_write
    BEFORE INSERT ON feature.feature_weather_values
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

CREATE FUNCTION feature.reject_weather_value_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'feature_weather_values facts are immutable (ADR-089)'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_weather_values_immutable';
END;
$$;

CREATE TRIGGER trg_feature_weather_values_immutable
    BEFORE UPDATE OR DELETE ON feature.feature_weather_values
    FOR EACH ROW EXECUTE FUNCTION feature.reject_weather_value_mutation();

-- current weather summary (ADR-072 결정 4, ADR-089, T-VN-38A) — bbox 매행
-- LATERAL을 set JOIN으로 치환하는 검증 가능 projection. 값/시각을 복제하지 않고
-- immutable fact와 성공한 materialization receipt만 참조하므로 history와 drift하지 않는다.
CREATE TABLE feature.current_weather_summary (
    feature_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    weather_domain text NOT NULL,
    forecast_style text NOT NULL,
    metric_key text NOT NULL,
    weather_value_key text NOT NULL,
    summary_run_id bigint NOT NULL,
    selected_at timestamptz NOT NULL,
    refresh_after timestamptz NOT NULL,
    projection_kind text NOT NULL DEFAULT 'weather',
    receipt_status text NOT NULL DEFAULT 'succeeded',
    CONSTRAINT pk_current_weather_summary PRIMARY KEY (
        feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
    ),
    CONSTRAINT fk_current_weather_summary_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_current_weather_summary_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_current_weather_summary_fact FOREIGN KEY (
        weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
    ) REFERENCES feature.feature_weather_values (
        weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
    ) ON DELETE CASCADE,
    CONSTRAINT fk_current_weather_summary_successful_run FOREIGN KEY (
        summary_run_id, projection_kind, receipt_status
    ) REFERENCES ops.current_summary_runs (summary_run_id, projection_kind, status),
    CONSTRAINT ck_current_weather_summary_projection_kind CHECK (projection_kind = 'weather'),
    CONSTRAINT ck_current_weather_summary_receipt_status CHECK (receipt_status = 'succeeded'),
    CONSTRAINT ck_current_weather_summary_refresh_after CHECK (
        refresh_after > selected_at
    )
);

CREATE INDEX idx_current_weather_summary_fact
    ON feature.current_weather_summary (weather_value_key);

CREATE TRIGGER trg_current_weather_summary_active_dataset_write
    BEFORE INSERT OR UPDATE ON feature.current_weather_summary
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

-- =============================================================================
-- 11. price history + current summary (ADR-078, T-VN-38B)
-- =============================================================================
-- price series identity는 `(feature_id, provider_dataset_id, price_domain, product_key)`다.
-- provider 표시는 canonical dataset join으로만 얻으며 문자열은 stored identity가 아니다.
CREATE TABLE feature.feature_price_values (
    price_value_key text NOT NULL,
    feature_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    product_name text,
    source_product_key text,
    source_product_name text,
    observed_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    value_number numeric(14, 4) NOT NULL,
    unit text NOT NULL DEFAULT 'KRW',
    normalization_version text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_entity_key text NOT NULL,
    source_record_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_feature_price_values PRIMARY KEY (price_value_key),
    CONSTRAINT fk_price_values_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_values_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_price_value_source_lineage FOREIGN KEY (
        source_record_key, source_entity_key, known_at
    ) REFERENCES provider_sync.source_records (
        source_record_key, source_entity_key, fetched_at
    ) ON DELETE RESTRICT,
    CONSTRAINT fk_price_value_source_dataset FOREIGN KEY (
        source_entity_key, provider_dataset_id
    ) REFERENCES provider_sync.source_entities (
        source_entity_key, provider_dataset_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ck_price_value_nonnegative CHECK (value_number >= 0),
    CONSTRAINT ck_price_value_payload_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT uq_price_value_identity UNIQUE (
        feature_id, provider_dataset_id, price_domain, product_key, observed_at, source_record_key
    )
);

CREATE UNIQUE INDEX uq_price_value_summary_reference
    ON feature.feature_price_values (
        price_value_key, feature_id, provider_dataset_id, price_domain, product_key
    );

-- history access path (ADR-078 결정 5)
CREATE INDEX idx_price_values_feature_observed_identity
    ON feature.feature_price_values (
        feature_id, observed_at DESC, known_at DESC, provider_dataset_id, price_domain, product_key
    );

CREATE FUNCTION feature.reject_price_value_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'feature_price_values facts are immutable (ADR-089)'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_price_values_immutable';
END;
$$;

CREATE TRIGGER trg_feature_price_values_immutable
    BEFORE UPDATE OR DELETE ON feature.feature_price_values
    FOR EACH ROW EXECUTE FUNCTION feature.reject_price_value_mutation();

CREATE TRIGGER trg_feature_price_values_active_dataset_write
    BEFORE INSERT ON feature.feature_price_values
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

-- current price summary (T-VN-38B) — series identity당 current 1건. price 값을
-- 복제하지 않고 선택된 immutable fact와 successful receipt를 참조한다.
CREATE TABLE feature.current_price_summary (
    feature_id uuid NOT NULL,
    provider_dataset_id bigint NOT NULL,
    price_domain text NOT NULL,
    product_key text NOT NULL,
    price_value_key text NOT NULL,
    summary_run_id bigint NOT NULL,
    projection_kind text NOT NULL DEFAULT 'price',
    receipt_status text NOT NULL DEFAULT 'succeeded',
    CONSTRAINT pk_current_price_summary PRIMARY KEY (
        feature_id, provider_dataset_id, price_domain, product_key
    ),
    CONSTRAINT fk_current_price_summary_feature FOREIGN KEY (feature_id)
        REFERENCES feature.features (feature_id) ON DELETE CASCADE,
    CONSTRAINT fk_current_price_summary_provider_dataset FOREIGN KEY (provider_dataset_id)
        REFERENCES provider_sync.provider_datasets (provider_dataset_id),
    CONSTRAINT fk_current_price_summary_fact FOREIGN KEY (
        price_value_key, feature_id, provider_dataset_id, price_domain, product_key
    ) REFERENCES feature.feature_price_values (
        price_value_key, feature_id, provider_dataset_id, price_domain, product_key
    ) ON DELETE CASCADE,
    CONSTRAINT fk_current_price_summary_successful_run FOREIGN KEY (
        summary_run_id, projection_kind, receipt_status
    ) REFERENCES ops.current_summary_runs (summary_run_id, projection_kind, status),
    CONSTRAINT ck_current_price_summary_projection_kind CHECK (projection_kind = 'price'),
    CONSTRAINT ck_current_price_summary_receipt_status CHECK (receipt_status = 'succeeded')
);

CREATE INDEX idx_current_price_summary_fact
    ON feature.current_price_summary (price_value_key);

CREATE TRIGGER trg_current_price_summary_active_dataset_write
    BEFORE INSERT OR UPDATE ON feature.current_price_summary
    FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

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
