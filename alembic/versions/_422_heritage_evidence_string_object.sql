-- private helper만 추가한다. 이 파일은 metadata 전체 예산 통과 뒤에만 호출된다.
-- JSONB payload를 metadata helper 인자로 넘기거나 text로 먼저 변환하지 않는다.
CREATE FUNCTION feature._heritage_evidence_string_object(p_value jsonb,p_keys text[])
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path TO pg_catalog AS $$
DECLARE v_key text; v_value jsonb; v_count integer:=0;
BEGIN
    IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
        RETURN false;
    END IF;
    FOR v_key,v_value IN SELECT key,value FROM jsonb_each(p_value) LOOP
        v_count:=v_count+1;
        IF NOT(v_key=ANY(p_keys)) OR jsonb_typeof(v_value) NOT IN ('string','null') THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN v_count=cardinality(p_keys);
END;
$$;
