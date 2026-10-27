-- 433 DC-1(ADR-115 §5.2(3)·§8(3) 개정): 단건·관리 writer의 protocol 진입.
-- scalar policy regime(epoch>0)에서만 P를 잡는다. regime 전(epoch=0)에는 P 없이
-- 기존 행 잠금 순서(source → link → Feature)와 기존 advisory만 쓴다.
CREATE FUNCTION ops.lock_single_feature_writer_protocol() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_epoch bigint;
BEGIN
    -- 행 잠금이 아닌 일반 읽기다. 이 읽기가 남기는 epoch 표의 ACCESS SHARE가
    -- 첫 활성화의 ACCESS EXCLUSIVE 설치를 이 transaction이 끝날 때까지 기다리게 한다.
    -- 활성화가 끝난 뒤의 읽기는 epoch>0을 보고 아래 EX로 들어간다.
    SELECT epoch INTO STRICT v_epoch FROM feature.provider_field_policy_epoch
     WHERE singleton;
    IF v_epoch > 0 THEN
        -- 첫 활성화가 함께 설치하는 strict guard(429)는 manifest 없는 SH 쓰기를 거부한다.
        -- 그래서 regime의 단건 writer는 EX다. SH 허용은 strict guard 재설계(DC-2)의 몫이다.
        PERFORM ops.lock_scoped_feature_write_protocol(true);
    END IF;
END;
$$;
