-- 첫 작동 단위는 name/phones만 지원한다. 다른 필드·Geo를 이 규약으로 승인하지 않는다.
CREATE FUNCTION feature.provider_field_scalar_winners(
    p_feature_id uuid, p_policy_revision bigint, p_field_paths text[]
) RETURNS TABLE(
    field_path text, value_json jsonb, provider_dataset_id bigint,
    source_entity_key text, value_source_record_key text, value_source_hash text,
    validated_source_record_key text, validated_source_hash text,
    value_observed_at timestamptz, validated_at timestamptz, normalizer_revision text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_member record;
    v_header feature.provider_field_shadow_policies%ROWTYPE;
    v_candidate feature.provider_field_shadow_candidates%ROWTYPE;
    v_field text;
    v_count integer := 0;
    v_fields text[] := ARRAY[]::text[];
    v_value_hash text;
    v_value_clock timestamptz;
    v_kind text;
BEGIN
    -- private helper: 호출자는 kernel 및 epoch에 먼저 진입한다. shared 경로의
    -- applying/manifest 권한은 별도의 쓰기 entry가 확인하며 이 helper는 잠금을 추가하지 않는다.
    IF NOT EXISTS (SELECT 1 FROM pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
          AND classid=1369104691 AND objid=115 AND objsubid=2
          AND mode IN ('ShareLock','ExclusiveLock')) THEN
        RAISE EXCEPTION 'candidate projection requires protocol entry' USING ERRCODE='23514';
    END IF;
    IF p_feature_id IS NULL OR p_policy_revision IS NULL OR p_policy_revision < 1
       OR p_field_paths IS NULL OR cardinality(p_field_paths) NOT BETWEEN 1 AND 2
       OR EXISTS (SELECT 1 FROM unnest(p_field_paths) path
                  WHERE path IS NULL OR path NOT IN ('core.name','place.phones'))
       OR cardinality(p_field_paths) <> (SELECT count(DISTINCT path) FROM unnest(p_field_paths) path) THEN
        RAISE EXCEPTION 'unsupported scalar policy selection' USING ERRCODE='23514';
    END IF;
    SELECT feature.kind INTO STRICT v_kind FROM feature.features feature
        WHERE feature.feature_id=p_feature_id;
    IF 'place.phones'=ANY(p_field_paths) AND v_kind <> 'place' THEN
        RAISE EXCEPTION 'phones policy requires place subtype' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM provider_sync.source_links link
        JOIN provider_sync.source_entities entity USING(source_entity_key)
        JOIN provider_sync.provider_datasets dataset USING(provider_dataset_id)
        WHERE link.feature_id=p_feature_id AND NOT dataset.is_active) THEN
        RAISE EXCEPTION 'inactive source membership requires an explicit retirement protocol' USING ERRCODE='23514';
    END IF;
    IF EXISTS (SELECT 1 FROM provider_sync.source_links own
        JOIN provider_sync.source_links other USING(source_entity_key)
        WHERE own.feature_id=p_feature_id AND other.feature_id<>p_feature_id) THEN
        RAISE EXCEPTION 'single Feature policy does not support a shared source entity' USING ERRCODE='23514';
    END IF;
    -- 모든 연결을 먼저 열거한다. 다른 role의 필드 기여를 없는 것으로 추정하지 않는다.
    FOR v_member IN
        SELECT dataset.provider_dataset_id,dataset.provider,dataset.dataset_key,
               entity.source_entity_key,link.source_role,
               head.current_source_record_key,head.observed_at,head.expires_at,
               record.raw_payload_hash
          FROM provider_sync.source_links link
          JOIN provider_sync.source_entities entity USING(source_entity_key)
          JOIN provider_sync.provider_datasets dataset USING(provider_dataset_id)
          LEFT JOIN provider_sync.source_entity_heads head USING(source_entity_key)
          LEFT JOIN provider_sync.source_records record
            ON record.source_record_key=head.current_source_record_key
           AND record.source_entity_key=entity.source_entity_key
         WHERE link.feature_id=p_feature_id AND dataset.is_active
         ORDER BY dataset.provider COLLATE "C",dataset.dataset_key COLLATE "C",
                  entity.source_entity_key COLLATE "C"
    LOOP
        v_count := v_count+1;
        IF v_count > 128 OR v_member.source_role <> 'primary'
           OR v_member.current_source_record_key IS NULL OR v_member.raw_payload_hash IS NULL
           OR v_member.expires_at IS NOT NULL THEN
            RAISE EXCEPTION 'unsupported or incomplete candidate membership' USING ERRCODE='23514';
        END IF;
        SELECT * INTO v_header FROM feature.provider_field_shadow_policies policy
         WHERE policy.policy_revision=p_policy_revision
           AND policy.provider_dataset_id=v_member.provider_dataset_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'every active membership needs an explicit policy' USING ERRCODE='23514';
        END IF;
        FOR v_field IN SELECT item->>'field_path' FROM jsonb_array_elements(v_header.fields) item LOOP
            IF v_field NOT IN ('core.name','place.phones') OR NOT(v_field=ANY(p_field_paths)) THEN
                RAISE EXCEPTION 'Geo and undeclared fields cannot enter scalar cutover' USING ERRCODE='23514';
            END IF;
            v_fields := array_append(v_fields,v_field);
            SELECT * INTO v_candidate FROM feature.provider_field_shadow_candidates candidate
             WHERE candidate.feature_id=p_feature_id AND candidate.field_path=v_field
               AND candidate.provider_dataset_id=v_member.provider_dataset_id
               AND candidate.source_entity_key=v_member.source_entity_key
               AND candidate.policy_revision=p_policy_revision;
            IF NOT FOUND OR v_candidate.availability NOT IN ('value','removed')
               OR v_candidate.validated_source_record_key IS DISTINCT FROM v_member.current_source_record_key
               OR v_candidate.validated_source_hash IS DISTINCT FROM v_member.raw_payload_hash
               OR v_candidate.validated_at IS DISTINCT FROM v_member.observed_at
               OR v_candidate.normalizer_revision IS DISTINCT FROM v_header.normalizer_revision
               OR v_candidate.value_geometry IS NOT NULL THEN
                RAISE EXCEPTION 'candidate is missing or not validated through current head' USING ERRCODE='23514';
            END IF;
            IF v_candidate.availability='value' THEN
                SELECT record.raw_payload_hash,record.fetched_at INTO v_value_hash,v_value_clock
                  FROM provider_sync.source_records record
                 WHERE record.source_record_key=v_candidate.value_source_record_key
                   AND record.source_entity_key=v_member.source_entity_key;
                IF NOT FOUND OR v_value_hash IS DISTINCT FROM v_candidate.value_source_hash
                   OR v_value_clock IS DISTINCT FROM v_candidate.value_observed_at
                   OR v_candidate.value_json IS NULL OR v_candidate.value_json='null'::jsonb THEN
                    -- 두 지원 필드는 registry가 explicit null을 허용하지 않는다.
                    RAISE EXCEPTION 'winner value lacks immutable typed source evidence' USING ERRCODE='23514';
                END IF;
            END IF;
        END LOOP;
    END LOOP;
    IF v_count=0 OR (SELECT array_agg(DISTINCT path COLLATE "C" ORDER BY path COLLATE "C") FROM unnest(v_fields) path)
        IS DISTINCT FROM (SELECT array_agg(path ORDER BY path COLLATE "C") FROM unnest(p_field_paths) path) THEN
        RAISE EXCEPTION 'candidate field coverage is incomplete' USING ERRCODE='23514';
    END IF;
    -- 다른 provider의 시각을 직접 비교하지 않는다. 동순위 provider는 정책 모호성이다.
    IF EXISTS (
        SELECT item->>'field_path',(item->>'provider_rank')::integer
          FROM provider_sync.source_links link
          JOIN provider_sync.source_entities entity USING(source_entity_key)
          JOIN provider_sync.provider_datasets dataset USING(provider_dataset_id)
          JOIN feature.provider_field_shadow_policies policy
            ON policy.provider_dataset_id=dataset.provider_dataset_id AND policy.policy_revision=p_policy_revision
          CROSS JOIN LATERAL jsonb_array_elements(policy.fields) item
         WHERE link.feature_id=p_feature_id AND dataset.is_active
         GROUP BY item->>'field_path',(item->>'provider_rank')::integer
        HAVING count(DISTINCT dataset.provider)>1
    ) THEN
        RAISE EXCEPTION 'equal field rank across providers is not configured' USING ERRCODE='23514';
    END IF;
    -- entity 안의 최신성은 정본 current head가 결정한다. 서로 다른 entity의 도착 clock은
    -- 비교하지 않고 명시 rank 뒤 안정된 dataset/entity/hash 순서만 사용한다.
    FOREACH v_field IN ARRAY p_field_paths LOOP
        SELECT candidate.* INTO v_candidate
          FROM feature.provider_field_shadow_candidates candidate
          JOIN provider_sync.source_entities entity
            ON entity.source_entity_key=candidate.source_entity_key
           AND entity.provider_dataset_id=candidate.provider_dataset_id
          JOIN provider_sync.provider_datasets dataset
            ON dataset.provider_dataset_id=candidate.provider_dataset_id
          JOIN provider_sync.source_links link
            ON link.feature_id=candidate.feature_id AND link.source_entity_key=candidate.source_entity_key
          JOIN feature.provider_field_shadow_policies policy
            ON policy.provider_dataset_id=dataset.provider_dataset_id AND policy.policy_revision=candidate.policy_revision
          CROSS JOIN LATERAL jsonb_array_elements(policy.fields) item
         WHERE candidate.feature_id=p_feature_id AND candidate.policy_revision=p_policy_revision
           AND candidate.field_path=v_field AND item->>'field_path'=v_field
           AND dataset.is_active AND candidate.availability='value'
         ORDER BY (item->>'provider_rank')::integer,
                  dataset.provider COLLATE "C",dataset.dataset_key COLLATE "C",
                  candidate.source_entity_key COLLATE "C",
                  candidate.validated_source_hash COLLATE "C" DESC
         LIMIT 1;
        IF NOT FOUND THEN
            -- name/phones는 nullable이 아니다. 마지막 값의 정당한 무값 의미는 후속 계약이다.
            RAISE EXCEPTION 'no valid scalar winner remains' USING ERRCODE='23514';
        END IF;
        field_path := v_field;
        value_json := v_candidate.value_json;
        provider_dataset_id := v_candidate.provider_dataset_id;
        source_entity_key := v_candidate.source_entity_key;
        value_source_record_key := v_candidate.value_source_record_key;
        value_source_hash := v_candidate.value_source_hash;
        validated_source_record_key := v_candidate.validated_source_record_key;
        validated_source_hash := v_candidate.validated_source_hash;
        value_observed_at := v_candidate.value_observed_at;
        validated_at := v_candidate.validated_at;
        normalizer_revision := v_candidate.normalizer_revision;
        RETURN NEXT;
    END LOOP;
END;
$$;
