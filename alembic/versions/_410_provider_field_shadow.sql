-- ADR115: shadow 후보만 기록하며 effective/base/policy 활성 상태는 바꾸지 않는다.
CREATE TABLE feature.provider_field_shadow_policies (
    policy_revision bigint NOT NULL CHECK (policy_revision >= 1),
    provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
    normalizer_revision text NOT NULL CHECK (normalizer_revision = btrim(normalizer_revision) AND normalizer_revision <> '' AND length(normalizer_revision) <= 128),
    fields jsonb NOT NULL CHECK (jsonb_typeof(fields) = 'array' AND jsonb_array_length(fields) BETWEEN 1 AND 256),
    CONSTRAINT pk_provider_field_shadow_policies PRIMARY KEY (policy_revision, provider_dataset_id)
);
ALTER TABLE feature.provider_field_shadow_policies OWNER TO ktm_feature_schema_owner;
CREATE INDEX idx_provider_field_shadow_policies_dataset ON feature.provider_field_shadow_policies(provider_dataset_id);

-- 전체 fieldset은 등록 진입점 한 번에 고정한다. 행별 수정 트리거에서 global fence를
-- 기다리면 collector(global -> policy)와 admin(policy -> global)의 순서가 역전된다.
CREATE PROCEDURE feature.register_provider_field_shadow_policy(
    IN p_policy_revision bigint, IN p_provider_dataset_id bigint,
    IN p_normalizer_revision text, IN p_fields jsonb
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_fields jsonb;
    v_existing feature.provider_field_shadow_policies%ROWTYPE;
BEGIN
    -- 어떤 정책 행/unique key를 잠그기 전에 기존 전역 fence를 먼저 획득한다.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
    IF p_policy_revision IS NULL OR p_policy_revision < 1
       OR p_provider_dataset_id IS NULL
       OR p_normalizer_revision IS NULL OR p_normalizer_revision <> btrim(p_normalizer_revision)
       OR p_normalizer_revision = '' OR length(p_normalizer_revision) > 128
       OR jsonb_typeof(p_fields) IS DISTINCT FROM 'array'
       OR pg_column_size(p_fields) > 131072 THEN
        RAISE EXCEPTION 'invalid shadow policy header' USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(p_fields) NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'invalid shadow policy field count' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_fields) field
        WHERE jsonb_typeof(field) <> 'object') THEN
        RAISE EXCEPTION 'invalid shadow policy field shape' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_fields) field
        WHERE (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(field) key)
               IS DISTINCT FROM ARRAY['field_path','null_policy','omitted_policy','provider_rank']::text[]
           OR jsonb_typeof(field->'field_path') <> 'string'
           OR jsonb_typeof(field->'provider_rank') <> 'number'
           OR (field->>'provider_rank') !~ '^(0|[1-9][0-9]*)$'
           OR (field->>'omitted_policy') NOT IN ('carry_forward','remove')
           OR (field->>'null_policy') NOT IN ('remove','value')
           OR jsonb_typeof(field->'omitted_policy') <> 'string'
           OR jsonb_typeof(field->'null_policy') <> 'string'
           OR NOT EXISTS (SELECT 1 FROM ops.feature_override_field_paths registry
               WHERE registry.field_path=field->>'field_path' AND registry.provider_writable)) THEN
        RAISE EXCEPTION 'invalid typed shadow policy field' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_fields) field
        WHERE (field->>'provider_rank')::numeric > 2147483647)
       OR (SELECT count(DISTINCT field->>'field_path') FROM jsonb_array_elements(p_fields) field)
          <> jsonb_array_length(p_fields) THEN
        RAISE EXCEPTION 'duplicate field or invalid shadow provider rank' USING ERRCODE='23514';
    END IF;
    SELECT jsonb_agg(jsonb_build_object(
        'field_path',field->>'field_path', 'provider_rank',(field->>'provider_rank')::integer,
        'omitted_policy',field->>'omitted_policy', 'null_policy',field->>'null_policy'
    ) ORDER BY field->>'field_path' COLLATE "C") INTO v_fields FROM jsonb_array_elements(p_fields) field;
    INSERT INTO feature.provider_field_shadow_policies(
        policy_revision,provider_dataset_id,normalizer_revision,fields
    ) VALUES (p_policy_revision,p_provider_dataset_id,p_normalizer_revision,v_fields)
    ON CONFLICT (policy_revision,provider_dataset_id) DO NOTHING;
    SELECT * INTO v_existing FROM feature.provider_field_shadow_policies
        WHERE policy_revision=p_policy_revision AND provider_dataset_id=p_provider_dataset_id;
    IF NOT FOUND OR v_existing.normalizer_revision IS DISTINCT FROM p_normalizer_revision
       OR v_existing.fields IS DISTINCT FROM v_fields THEN
        -- RR에 새 revision이 보이지 않거나 동일 revision이 다르면 승인하지 않는다.
        RAISE EXCEPTION 'shadow policy revision is immutable or not visible' USING ERRCODE='23514';
    END IF;
END;
$$;
ALTER PROCEDURE feature.register_provider_field_shadow_policy(bigint,bigint,text,jsonb) OWNER TO ktm_feature_schema_owner;
REVOKE ALL ON PROCEDURE feature.register_provider_field_shadow_policy(bigint,bigint,text,jsonb) FROM PUBLIC;
-- 정책 등록은 schema 관리자만 한다. runtime/typed recorder owner에게 EXECUTE를 주지 않는다.
CREATE FUNCTION feature.guard_provider_field_shadow_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'shadow policy revision and complete fieldset are immutable' USING ERRCODE='23514';
END;
$$;
ALTER FUNCTION feature.guard_provider_field_shadow_policy() OWNER TO ktm_feature_schema_owner;
REVOKE ALL ON FUNCTION feature.guard_provider_field_shadow_policy() FROM PUBLIC;
CREATE TRIGGER trg_provider_field_shadow_policy_immutable BEFORE UPDATE OR DELETE
ON feature.provider_field_shadow_policies FOR EACH ROW EXECUTE FUNCTION feature.guard_provider_field_shadow_policy();

CREATE TABLE feature.provider_field_shadow_candidates (
    feature_id uuid NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
    policy_revision bigint NOT NULL,
    provider_dataset_id bigint NOT NULL,
    field_path text NOT NULL REFERENCES ops.feature_override_field_paths(field_path) ON DELETE RESTRICT,
    source_entity_key text NOT NULL REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
    value_source_record_key text REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT,
    value_source_hash text,
    validated_source_record_key text NOT NULL REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT,
    validated_source_hash text NOT NULL CHECK (btrim(validated_source_hash) <> ''),
    value_json jsonb,
    value_geometry x_extension.geometry(Geometry,4326),
    availability text NOT NULL CHECK (availability IN ('value', 'removed', 'unresolved')),
    reason text NOT NULL CHECK (reason IN ('supplied', 'explicit_null', 'omitted_carry', 'omitted_remove', 'missing_initial_value', 'presence_unknown', 'geo_evidence_unsupported')),
    value_observed_at timestamptz,
    validated_at timestamptz NOT NULL,
    normalizer_revision text,
    CONSTRAINT pk_provider_field_shadow_candidates PRIMARY KEY (feature_id, field_path, provider_dataset_id, source_entity_key, policy_revision),
    CONSTRAINT fk_provider_field_shadow_candidates_policy FOREIGN KEY(policy_revision, provider_dataset_id)
        REFERENCES feature.provider_field_shadow_policies(policy_revision, provider_dataset_id) ON DELETE RESTRICT,
    CONSTRAINT ck_provider_field_shadow_candidates_single_value CHECK (value_json IS NULL OR value_geometry IS NULL),
    CONSTRAINT ck_provider_field_shadow_candidates_value CHECK (
        availability <> 'value' OR (value_source_record_key IS NOT NULL AND value_source_hash IS NOT NULL
        AND value_observed_at IS NOT NULL AND (value_json IS NOT NULL OR value_geometry IS NOT NULL))
    ),
    CONSTRAINT ck_provider_field_shadow_candidates_record_hash CHECK (
        (value_source_record_key IS NULL) = (value_source_hash IS NULL)
    )
);
ALTER TABLE feature.provider_field_shadow_candidates OWNER TO ktm_feature_schema_owner;
CREATE INDEX idx_provider_field_shadow_candidates_policy ON feature.provider_field_shadow_candidates(policy_revision, provider_dataset_id, field_path);
CREATE INDEX idx_provider_field_shadow_candidates_entity ON feature.provider_field_shadow_candidates(source_entity_key);
CREATE INDEX idx_provider_field_shadow_candidates_value_record ON feature.provider_field_shadow_candidates(value_source_record_key);
CREATE INDEX idx_provider_field_shadow_candidates_validated_record ON feature.provider_field_shadow_candidates(validated_source_record_key);

CREATE PROCEDURE feature.record_provider_field_candidates(
    IN p_feature_id uuid, IN p_provider_dataset_id bigint,
    IN p_source_entity_key text, IN p_source_record_key text,
    IN p_policy_revision bigint, IN p_normalizer_revision text, IN p_presence_proven boolean,
    IN p_values jsonb, IN p_geometry_wkt jsonb,
    OUT o_field_count integer, OUT o_unresolved_count integer
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_hash text;
    v_kind text;
    v_observed_at timestamptz;
    v_validated_at timestamptz;
    v_header feature.provider_field_shadow_policies%ROWTYPE;
    v_policy record;
    v_registry ops.feature_override_field_paths%ROWTYPE;
    v_old feature.provider_field_shadow_candidates%ROWTYPE;
    v_candidate feature.provider_field_shadow_candidates%ROWTYPE;
    v_supplied boolean;
    v_value jsonb;
    v_target_type text;
    v_cast_value jsonb;
BEGIN
    IF p_policy_revision IS NULL OR p_policy_revision < 1 OR p_presence_proven IS NULL
       OR jsonb_typeof(p_values) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_geometry_wkt) IS DISTINCT FROM 'object'
       OR (NOT p_presence_proven AND (p_values <> '{}'::jsonb OR p_geometry_wkt <> '{}'::jsonb))
       OR (p_presence_proven AND coalesce(btrim(p_normalizer_revision), '') = '') THEN
        RAISE EXCEPTION 'invalid shadow observation' USING ERRCODE='23514';
    END IF;
    -- 기존 전역 fence를 유지한다. 이 shadow 프로시저는 독립 dataset 쓰기를 허용하지 않는다.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));
    v_hash := feature.lock_current_provider_feature_source_evidence(
        p_feature_id, p_provider_dataset_id, p_source_entity_key, p_source_record_key
    );
    SELECT kind INTO STRICT v_kind FROM feature.features WHERE feature_id=p_feature_id FOR UPDATE;
    SELECT record.fetched_at, head.observed_at INTO STRICT v_observed_at, v_validated_at
      FROM provider_sync.source_records record
      JOIN provider_sync.source_entity_heads head ON head.source_entity_key=record.source_entity_key
      WHERE record.source_record_key=p_source_record_key AND head.current_source_record_key=record.source_record_key;
    SELECT * INTO v_header FROM feature.provider_field_shadow_policies
        WHERE policy_revision=p_policy_revision AND provider_dataset_id=p_provider_dataset_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shadow policy is not explicitly configured or visible' USING ERRCODE='23514';
    END IF;
    IF EXISTS (
        SELECT path FROM (
            SELECT jsonb_object_keys(p_values) path UNION ALL SELECT jsonb_object_keys(p_geometry_wkt)
        ) supplied
        WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_header.fields) field
            WHERE field->>'field_path'=supplied.path)
    ) OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_values) path WHERE p_geometry_wkt ? path) THEN
        RAISE EXCEPTION 'supplied field has missing policy or conflicting typed values' USING ERRCODE='23514';
    END IF;
    o_field_count := 0;
    o_unresolved_count := 0;
    FOR v_policy IN SELECT * FROM jsonb_to_recordset(v_header.fields)
        AS field(field_path text,provider_rank integer,omitted_policy text,null_policy text)
        ORDER BY field_path COLLATE "C"
    LOOP
        SELECT * INTO STRICT v_registry FROM ops.feature_override_field_paths WHERE field_path=v_policy.field_path;
        IF NOT v_registry.provider_writable OR (v_registry.feature_kind <> '*' AND v_registry.feature_kind <> v_kind) THEN
            RAISE EXCEPTION 'shadow field does not belong to typed Feature' USING ERRCODE='23514';
        END IF;
        IF p_presence_proven AND p_normalizer_revision IS DISTINCT FROM v_header.normalizer_revision THEN
            RAISE EXCEPTION 'shadow normalizer revision is not declared' USING ERRCODE='23514';
        END IF;
        SELECT * INTO v_old FROM feature.provider_field_shadow_candidates
          WHERE feature_id=p_feature_id AND field_path=v_policy.field_path
            AND provider_dataset_id=p_provider_dataset_id AND source_entity_key=p_source_entity_key
            AND policy_revision=p_policy_revision FOR UPDATE;
        v_candidate := v_old;
        v_candidate.feature_id := p_feature_id;
        v_candidate.policy_revision := p_policy_revision;
        v_candidate.provider_dataset_id := p_provider_dataset_id;
        v_candidate.field_path := v_policy.field_path;
        v_candidate.source_entity_key := p_source_entity_key;
        v_candidate.validated_source_record_key := p_source_record_key;
        v_candidate.validated_source_hash := v_hash;
        v_candidate.validated_at := v_validated_at;
        v_candidate.normalizer_revision := p_normalizer_revision;
        v_supplied := p_values ? v_policy.field_path OR p_geometry_wkt ? v_policy.field_path;
        IF NOT p_presence_proven THEN
            v_candidate.availability := 'unresolved';
            v_candidate.reason := 'presence_unknown';
        ELSIF v_registry.value_kind = 'geometry' OR v_policy.field_path IN (
            'core.address', 'core.legal_dong_code', 'core.road_name_code', 'core.road_address_management_no',
            'core.admin_dong_code', 'core.sido_code', 'core.sigungu_code', 'core.coord_precision_digits',
            'core.parent_feature_id', 'core.sibling_group_id', 'core.raw_refs'
        ) THEN
            -- Geo 일관 그룹/stamp 증거는 후속 단위다. 독립 scalar처럼 승인하지 않는다.
            v_candidate.availability := 'unresolved';
            v_candidate.reason := 'geo_evidence_unsupported';
        ELSIF v_supplied THEN
            IF p_geometry_wkt ? v_policy.field_path THEN
                RAISE EXCEPTION 'scalar field supplied as geometry' USING ERRCODE='23514';
            END IF;
            v_value := p_values -> v_policy.field_path;
            IF (v_value = 'null'::jsonb AND NOT v_registry.allows_null)
                OR (v_value <> 'null'::jsonb AND (
                    (v_registry.value_kind IN ('text','uuid','date','timestamptz') AND jsonb_typeof(v_value) <> 'string')
                    OR (v_registry.value_kind IN ('integer','numeric') AND jsonb_typeof(v_value) <> 'number')
                    OR (v_registry.value_kind='boolean' AND jsonb_typeof(v_value) <> 'boolean')
                    OR (v_registry.value_kind='json_object' AND jsonb_typeof(v_value) <> 'object')
                    OR (v_registry.value_kind IN ('json_array','text_array') AND jsonb_typeof(v_value) <> 'array')
                )) THEN
                RAISE EXCEPTION 'shadow scalar does not match typed registry' USING ERRCODE='23514';
            END IF;
            IF v_registry.value_kind='text_array' AND v_value <> 'null'::jsonb AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_value) element WHERE jsonb_typeof(element) <> 'string'
            ) THEN
                RAISE EXCEPTION 'shadow text array contains nontext value' USING ERRCODE='23514';
            END IF;
            IF v_value <> 'null'::jsonb THEN
                -- registry JSON 종류만으로 fractional integer/잘못된 날짜를 승인하지 않는다.
                -- 실제 저장 열의 smallint/int/numeric 정밀도·길이까지 검증한다.
                SELECT format_type(attribute.atttypid,attribute.atttypmod) INTO STRICT v_target_type
                FROM pg_attribute attribute
                JOIN pg_class relation ON relation.oid=attribute.attrelid
                JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
                WHERE namespace.nspname='feature' AND relation.relname=v_registry.target_relation
                  AND attribute.attname=v_registry.target_column AND NOT attribute.attisdropped;
                IF v_registry.value_kind NOT IN ('json_object','json_array','text_array') THEN
                    IF NOT pg_input_is_valid(v_value #>> '{}',v_target_type) THEN
                        RAISE EXCEPTION 'shadow scalar cannot be stored in typed target' USING ERRCODE='23514';
                    END IF;
                    IF v_registry.value_kind='date' AND (v_value #>> '{}') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
                        RAISE EXCEPTION 'shadow date requires an ISO calendar date' USING ERRCODE='23514';
                    END IF;
                    IF v_registry.value_kind='timestamptz' AND (v_value #>> '{}') !~
                        '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
                        RAISE EXCEPTION 'shadow timestamp requires an explicit timezone' USING ERRCODE='23514';
                    END IF;
                    IF v_registry.value_kind IN ('integer','numeric','text') THEN
                        -- format_type는 trusted catalog 값이다. 입력값은 바인딩해 SQL에 섞지 않는다.
                        EXECUTE format('SELECT to_jsonb(($1)::%s)',v_target_type)
                            INTO v_cast_value USING v_value #>> '{}';
                        IF v_cast_value IS DISTINCT FROM v_value THEN
                            RAISE EXCEPTION 'shadow scalar would lose precision or length' USING ERRCODE='23514';
                        END IF;
                    END IF;
                END IF;
            END IF;
            v_candidate.value_json := v_value;
            v_candidate.value_geometry := NULL;
            v_candidate.value_source_record_key := p_source_record_key;
            v_candidate.value_source_hash := v_hash;
            v_candidate.value_observed_at := v_observed_at;
            v_candidate.availability := CASE WHEN v_value='null'::jsonb AND v_policy.null_policy='remove' THEN 'removed' ELSE 'value' END;
            v_candidate.reason := CASE WHEN v_value='null'::jsonb THEN 'explicit_null' ELSE 'supplied' END;
        ELSIF v_policy.omitted_policy='remove' THEN
            v_candidate.availability := 'removed';
            v_candidate.reason := 'omitted_remove';
        ELSIF v_old.value_source_record_key IS NOT NULL AND v_old.availability IN ('value','removed') THEN
            v_candidate.availability := v_old.availability;
            v_candidate.reason := 'omitted_carry';
        ELSE
            v_candidate.availability := 'unresolved';
            v_candidate.reason := 'missing_initial_value';
        END IF;
        INSERT INTO feature.provider_field_shadow_candidates SELECT (v_candidate).*
        ON CONFLICT (feature_id,field_path,provider_dataset_id,source_entity_key,policy_revision) DO UPDATE
        SET value_source_record_key=EXCLUDED.value_source_record_key,
            value_source_hash=EXCLUDED.value_source_hash,
            validated_source_record_key=EXCLUDED.validated_source_record_key,
            validated_source_hash=EXCLUDED.validated_source_hash,
            value_json=EXCLUDED.value_json,value_geometry=EXCLUDED.value_geometry,
            availability=EXCLUDED.availability,reason=EXCLUDED.reason,
            value_observed_at=EXCLUDED.value_observed_at,validated_at=EXCLUDED.validated_at,
            normalizer_revision=EXCLUDED.normalizer_revision;
        o_field_count := o_field_count+1;
        o_unresolved_count := o_unresolved_count + CASE WHEN v_candidate.availability='unresolved' THEN 1 ELSE 0 END;
    END LOOP;
END;
$$;
ALTER PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) OWNER TO ktm_feature_state_procedure_owner;
SET ROLE ktm_feature_state_procedure_owner;
REVOKE ALL ON PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) TO ktm_feature_runtime;
SET ROLE ktm_feature_schema_owner;
GRANT SELECT ON feature.provider_field_shadow_policies TO ktm_feature_state_procedure_owner;
GRANT SELECT,INSERT,UPDATE ON feature.provider_field_shadow_candidates TO ktm_feature_state_procedure_owner;
