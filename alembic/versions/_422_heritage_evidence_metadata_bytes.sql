-- 숫자/bool metadata만 받는다. payload datum을 helper 인자로 전달하지 않는다.
CREATE FUNCTION feature._heritage_evidence_metadata_bytes(
    p_sizes bigint[], p_compressed boolean[], p_caps integer[], p_nullable boolean[]
) RETURNS bigint LANGUAGE plpgsql IMMUTABLE SET search_path TO pg_catalog AS $$
DECLARE v_count integer; v_index integer; v_total bigint:=0;
BEGIN
    -- 이 helper는 SD reader owner 내부 전용이다. 임의 runtime 호출 권한이 없다.
    v_count:=cardinality(p_sizes);
    IF v_count IS NULL OR v_count<1 OR v_count>64
       OR cardinality(p_compressed) IS DISTINCT FROM v_count
       OR cardinality(p_caps) IS DISTINCT FROM v_count
       OR cardinality(p_nullable) IS DISTINCT FROM v_count
       OR array_lower(p_sizes,1) IS DISTINCT FROM 1
       OR array_lower(p_compressed,1) IS DISTINCT FROM 1
       OR array_lower(p_caps,1) IS DISTINCT FROM 1
       OR array_lower(p_nullable,1) IS DISTINCT FROM 1
       OR array_ndims(p_sizes) IS DISTINCT FROM 1
       OR array_ndims(p_compressed) IS DISTINCT FROM 1
       OR array_ndims(p_caps) IS DISTINCT FROM 1
       OR array_ndims(p_nullable) IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'invalid internal metadata inventory' USING ERRCODE='22023';
    END IF;
    FOR v_index IN 1..v_count LOOP
        IF p_caps[v_index] IS NULL OR p_caps[v_index]<1 OR p_caps[v_index]>8192
           OR p_nullable[v_index] IS NULL THEN
            RAISE EXCEPTION 'invalid internal metadata cap' USING ERRCODE='22023';
        END IF;
        IF p_sizes[v_index] IS NULL THEN
            IF NOT p_nullable[v_index] THEN RETURN -1; END IF;
        ELSE
            IF p_compressed[v_index] IS DISTINCT FROM false
               OR p_sizes[v_index]<1 OR p_sizes[v_index]>p_caps[v_index] THEN
                RETURN -1;
            END IF;
            -- short/external datum의 flattened header 차이를 보수적으로 더한다.
            v_total:=v_total+p_sizes[v_index]+4;
        END IF;
    END LOOP;
    RETURN v_total;
END;
$$;
