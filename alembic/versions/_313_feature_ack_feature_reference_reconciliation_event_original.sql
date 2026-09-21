CREATE PROCEDURE feature.ack_feature_reference_reconciliation_event(IN p_principal_id text, IN p_event_id uuid, IN p_worker_id uuid, IN p_lease_epoch bigint, IN p_event_sha256 text, IN p_local_receipt_sha256 text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_acked_through_sequence bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $_$
DECLARE
    v_subscription ops.feature_reference_reconciliation_subscriptions%ROWTYPE;
    v_lease ops.feature_reference_reconciliation_leases%ROWTYPE;
    v_event ops.feature_reference_reconciliation_events%ROWTYPE;
    v_existing_ack ops.feature_reference_reconciliation_acks%ROWTYPE;
    v_command ops.domain_commands%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'feature reference reconciliation ack requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_reconciliation_ack_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(
           session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation ack requires the service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_reconciliation_service_executor';
    END IF;
    IF nullif(btrim(p_principal_id), '') IS NULL
       OR char_length(p_principal_id) > 200 OR p_event_id IS NULL OR p_worker_id IS NULL
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_event_sha256 !~ '^[0-9a-f]{64}$'
       OR p_local_receipt_sha256 !~ '^[0-9a-f]{64}$'
       OR p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'feature reference reconciliation ack input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_reconciliation_ack_input';
    END IF;
    SELECT ack.* INTO v_existing_ack
    FROM ops.feature_reference_reconciliation_acks AS ack
    WHERE ack.event_id = p_event_id AND ack.principal_id = p_principal_id
    FOR SHARE;
    IF FOUND THEN
        SELECT lease.acked_through_sequence INTO o_acked_through_sequence
        FROM ops.feature_reference_reconciliation_leases AS lease
        WHERE lease.principal_id = p_principal_id;
        IF v_existing_ack.event_sha256 = p_event_sha256
           AND v_existing_ack.local_receipt_sha256 = p_local_receipt_sha256 THEN
            o_outcome := 'replayed';
        ELSE
            o_outcome := 'conflict';
        END IF;
        RETURN;
    END IF;
    SELECT subscription.* INTO v_subscription
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    WHERE subscription.principal_id = p_principal_id
      AND subscription.ack_scope = 'feature-reference-reconciliation:ack'
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription is not provisioned'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT lease.* INTO v_lease
    FROM ops.feature_reference_reconciliation_leases AS lease
    WHERE lease.principal_id = p_principal_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription lacks lease state'
            USING ERRCODE = '55000';
    END IF;
    IF v_lease.worker_id IS DISTINCT FROM p_worker_id
       OR v_lease.lease_epoch <> p_lease_epoch
       OR v_lease.lease_expires_at IS NULL
       OR v_lease.lease_expires_at <= clock_timestamp() THEN
        o_outcome := 'lease_conflict';
        o_acked_through_sequence := v_lease.acked_through_sequence;
        RETURN;
    END IF;
    SELECT event.* INTO v_event
    FROM ops.feature_reference_reconciliation_events AS event
    WHERE event.event_sequence > v_lease.acked_through_sequence
    ORDER BY event.event_sequence
    LIMIT 1
    FOR SHARE;
    IF NOT FOUND OR v_event.event_id <> p_event_id THEN
        o_outcome := 'not_next';
        o_acked_through_sequence := v_lease.acked_through_sequence;
        RETURN;
    END IF;
    IF v_event.event_sha256 <> p_event_sha256 THEN
        o_outcome := 'conflict';
        o_acked_through_sequence := v_lease.acked_through_sequence;
        RETURN;
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_principal_id
       OR v_command.operation <> 'service.feature-reference-reconciliation.ack.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation ack command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_reconciliation_ack_command';
    END IF;
    INSERT INTO ops.feature_reference_reconciliation_acks (
        event_id, principal_id, event_sha256, local_receipt_sha256, command_id
    ) VALUES (
        v_event.event_id, p_principal_id, p_event_sha256,
        p_local_receipt_sha256, p_domain_command_id
    );
    UPDATE ops.feature_reference_reconciliation_leases
    SET acked_through_sequence = v_event.event_sequence,
        updated_at = clock_timestamp()
    WHERE principal_id = p_principal_id;
    o_outcome := 'acked';
    o_acked_through_sequence := v_event.event_sequence;
END
$_$;
