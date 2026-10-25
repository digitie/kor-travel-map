-- metadata 전체 통과 뒤 호출하는 내부 shape 검사다. 공개 입력/쓰기 권한을 발급하지 않는다.
CREATE FUNCTION feature._bounded_curation_string_object(p_value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path TO pg_catalog AS $$
DECLARE
    v_key text;
    v_value jsonb;
    v_count integer := 0;
BEGIN
    IF p_value IS NULL OR jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
        RETURN false;
    END IF;
    FOR v_key, v_value IN SELECT key, value FROM jsonb_each(p_value) LOOP
        v_count := v_count + 1;
        IF v_count > 32 OR octet_length(v_key) > 256
           OR jsonb_typeof(v_value) NOT IN ('string', 'null') THEN
            RETURN false;
        END IF;
        -- 숫자를 문자열로 확장하지 않는다. string 판정 후의 문자열만 꺼낸다.
        IF jsonb_typeof(v_value) = 'string' THEN
            IF octet_length(v_value #>> '{}'::text[]) > 256 THEN
                RETURN false;
            END IF;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;
