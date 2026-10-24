CREATE FUNCTION ops.append_scoped_feature_write_manifest(p_attempt uuid,p_owner uuid,p_members jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_attempt ops.feature_write_attempts%ROWTYPE; v_member jsonb; v_digest text; v_existing ops.feature_write_manifests%ROWTYPE; v_count integer;
BEGIN
    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);
    IF v_attempt.status<>'preparing' THEN RAISE EXCEPTION 'manifest is sealed' USING ERRCODE='23514'; END IF;
    IF jsonb_typeof(p_members) IS DISTINCT FROM 'array' OR pg_column_size(p_members)>131072 THEN
        RAISE EXCEPTION 'invalid bounded manifest batch' USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(p_members) NOT BETWEEN 1 AND 256 THEN RAISE EXCEPTION 'invalid manifest batch count' USING ERRCODE='23514'; END IF;
    FOR v_member IN SELECT value FROM jsonb_array_elements(p_members) LOOP
        IF jsonb_typeof(v_member) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'invalid manifest object' USING ERRCODE='23514'; END IF;
        IF (SELECT array_agg(key ORDER BY key COLLATE "C") FROM jsonb_object_keys(v_member) key)
            IS DISTINCT FROM ARRAY['dependency_key','dependency_kind','expected_value','ordinal']::text[]
            OR jsonb_typeof(v_member->'ordinal') IS DISTINCT FROM 'number'
            OR (v_member->>'ordinal') !~ '^(0|[1-9][0-9]{0,3})$'
            OR jsonb_typeof(v_member->'dependency_kind') IS DISTINCT FROM 'string'
            OR (v_member->>'dependency_kind') NOT IN ('feature','source_head')
            OR jsonb_typeof(v_member->'dependency_key') IS DISTINCT FROM 'string'
            OR octet_length(v_member->>'dependency_key') NOT BETWEEN 1 AND 128
            OR jsonb_typeof(v_member->'expected_value') IS DISTINCT FROM 'string'
            OR octet_length(v_member->>'expected_value') NOT BETWEEN 1 AND 128 THEN
            RAISE EXCEPTION 'invalid manifest member' USING ERRCODE='23514';
        END IF;
        IF (v_member->>'ordinal')::integer>=v_attempt.expected_members THEN RAISE EXCEPTION 'manifest ordinal overflow' USING ERRCODE='23514'; END IF;
        IF v_member->>'dependency_kind'='feature' AND ((v_member->>'dependency_key') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR (v_member->>'expected_value') !~ '^[1-9][0-9]{0,18}$') THEN
            RAISE EXCEPTION 'invalid feature dependency' USING ERRCODE='23514';
        END IF;
        v_digest:=encode(sha256(convert_to(v_member::text,'UTF8')),'hex');
        INSERT INTO ops.feature_write_manifests(attempt_id,ordinal,dependency_kind,dependency_key,expected_value,member_digest)
            VALUES(p_attempt,(v_member->>'ordinal')::integer,v_member->>'dependency_kind',v_member->>'dependency_key',v_member->>'expected_value',v_digest) ON CONFLICT(attempt_id,ordinal) DO NOTHING;
        SELECT * INTO v_existing FROM ops.feature_write_manifests WHERE attempt_id=p_attempt AND ordinal=(v_member->>'ordinal')::integer;
        IF NOT FOUND OR v_existing.member_digest<>v_digest THEN RAISE EXCEPTION 'manifest member is immutable or not visible' USING ERRCODE='23514'; END IF;
    END LOOP;
    SELECT count(*) INTO v_count FROM ops.feature_write_manifests WHERE attempt_id=p_attempt;
    IF v_count>v_attempt.expected_members OR (SELECT COALESCE(sum(octet_length(dependency_key)+octet_length(expected_value)+octet_length(dependency_kind)+68),0) FROM ops.feature_write_manifests WHERE attempt_id=p_attempt)>1048576 THEN
        RAISE EXCEPTION 'manifest budget exceeded' USING ERRCODE='23514';
    END IF;
    RETURN v_count;
END;
$$;
