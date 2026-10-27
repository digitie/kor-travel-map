CREATE FUNCTION ops.lock_provider_evidence_writer_protocol() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO pg_catalog
    AS $$
DECLARE
    v_epoch bigint;
BEGIN
    -- provider source 증거를 Feature보다 먼저 잡는 관리 writer(M05·재활성화)의 진입이다.
    -- 적재는 한 transaction에서 bundle을 차례로 쓰며 앞 bundle의 Feature를 쥔 채 뒤 bundle의
    -- head를 갱신한다. 그래서 epoch=0에서도 P를 공유로 잡아 적재(P EX)와 직렬화한다. 단건
    -- writer끼리·scoped kernel(P SH)과는 막지 않는다. epoch 읽기는 단건 진입과 같다(drain).
    SELECT epoch INTO STRICT v_epoch FROM feature.provider_field_policy_epoch
     WHERE singleton;
    -- regime에서는 strict guard가 manifest 없는 SH 쓰기를 거부하므로 배타다.
    PERFORM ops.lock_scoped_feature_write_protocol(v_epoch > 0);
END;
$$;
