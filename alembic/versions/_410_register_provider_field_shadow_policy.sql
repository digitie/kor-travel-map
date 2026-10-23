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
