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
