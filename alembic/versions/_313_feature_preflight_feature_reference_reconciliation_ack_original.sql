CREATE OR REPLACE FUNCTION feature.preflight_feature_reference_reconciliation_ack(p_principal_id text, p_event_id uuid, p_event_sha256 text, p_local_receipt_sha256 text) RETURNS TABLE(o_outcome text, o_acked_through_sequence bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $_$
DECLARE
    v_existing_ack ops.feature_reference_reconciliation_acks%ROWTYPE;
BEGIN
    -- 이 read는 HTTP domain-command claim보다 먼저 호출된다. 응답 유실 뒤 새
    -- Idempotency-Key로 같은 receipt를 재전송해도 빈 command claim을 만들지
    -- 않도록, 이미 확정된 ACK만 server-owned principal로 판별한다.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'feature reference reconciliation ack preflight requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_reconciliation_ack_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation ack preflight requires the service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_reconciliation_service_executor';
    END IF;
    IF nullif(btrim(p_principal_id), '') IS NULL
       OR char_length(p_principal_id) > 200 OR p_event_id IS NULL
       OR p_event_sha256 !~ '^[0-9a-f]{64}$'
       OR p_local_receipt_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'feature reference reconciliation ack preflight input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_reconciliation_ack_input';
    END IF;

    SELECT ack.* INTO v_existing_ack
    FROM ops.feature_reference_reconciliation_acks AS ack
    WHERE ack.event_id = p_event_id AND ack.principal_id = p_principal_id
    FOR SHARE;
    IF NOT FOUND THEN
        o_outcome := 'absent';
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT lease.acked_through_sequence INTO o_acked_through_sequence
    FROM ops.feature_reference_reconciliation_leases AS lease
    WHERE lease.principal_id = p_principal_id;
    IF v_existing_ack.event_sha256 = p_event_sha256
       AND v_existing_ack.local_receipt_sha256 = p_local_receipt_sha256 THEN
        o_outcome := 'replayed';
    ELSE
        o_outcome := 'conflict';
    END IF;
    RETURN NEXT;
END
$_$;
