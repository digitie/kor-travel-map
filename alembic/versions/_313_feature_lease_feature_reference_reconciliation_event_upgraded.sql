CREATE OR REPLACE PROCEDURE feature.lease_feature_reference_reconciliation_event(IN p_principal_id text, IN p_worker_id uuid, OUT o_outcome text, OUT o_lease_epoch bigint, OUT o_lease_expires_at timestamp with time zone, OUT o_event_id uuid, OUT o_event_sequence bigint, OUT o_case_id uuid, OUT o_resolution_id uuid, OUT o_action text, OUT o_event_payload jsonb, OUT o_event_sha256 text, OUT o_occurred_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
    v_subscription ops.feature_reference_reconciliation_subscriptions%ROWTYPE;
    v_lease ops.feature_reference_reconciliation_leases%ROWTYPE;
    v_event ops.feature_reference_reconciliation_events%ROWTYPE;
    v_now timestamptz := clock_timestamp();
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'feature reference reconciliation lease requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_reconciliation_lease_isolation';
    END IF;
    IF session_user <> 'ktm_feature_service'
       OR NOT pg_has_role(
           session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation lease requires the service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_reconciliation_service_executor';
    END IF;
    IF nullif(btrim(p_principal_id), '') IS NULL
       OR char_length(p_principal_id) > 200 OR p_worker_id IS NULL THEN
        RAISE EXCEPTION 'feature reference reconciliation lease input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_reconciliation_lease_input';
    END IF;
    SELECT subscription.* INTO v_subscription
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    WHERE subscription.principal_id = p_principal_id
      AND subscription.read_scope = 'feature-reference-reconciliation:read'
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
    IF v_lease.acked_through_sequence < v_subscription.initial_event_sequence THEN
        RAISE EXCEPTION 'feature reference reconciliation lease cursor is below subscription cursor'
            USING ERRCODE = '55000';
    END IF;
    SELECT event.* INTO v_event
    FROM ops.feature_reference_reconciliation_events AS event
    WHERE event.event_sequence > v_lease.acked_through_sequence
    ORDER BY event.event_sequence
    LIMIT 1
    FOR SHARE;
    IF NOT FOUND THEN
        o_outcome := 'empty';
        o_lease_epoch := v_lease.lease_epoch;
        RETURN;
    END IF;
    IF v_lease.worker_id IS NOT NULL
       AND v_lease.lease_expires_at > v_now
       AND v_lease.worker_id <> p_worker_id THEN
        o_outcome := 'lease_conflict';
        o_lease_epoch := v_lease.lease_epoch;
        o_lease_expires_at := v_lease.lease_expires_at;
        RETURN;
    END IF;
    IF v_lease.worker_id IS DISTINCT FROM p_worker_id
       OR v_lease.lease_expires_at IS NULL OR v_lease.lease_expires_at <= v_now THEN
        v_lease.lease_epoch := v_lease.lease_epoch + 1;
    END IF;
    v_lease.worker_id := p_worker_id;
    v_lease.lease_expires_at := v_now + interval '60 seconds';
    UPDATE ops.feature_reference_reconciliation_leases
    SET worker_id = v_lease.worker_id,
        lease_epoch = v_lease.lease_epoch,
        lease_expires_at = v_lease.lease_expires_at,
        updated_at = v_now
    WHERE principal_id = p_principal_id;
    o_outcome := 'leased';
    o_lease_epoch := v_lease.lease_epoch;
    o_lease_expires_at := v_lease.lease_expires_at;
    o_event_id := v_event.event_id;
    o_event_sequence := v_event.event_sequence;
    o_case_id := v_event.case_id;
    o_resolution_id := v_event.resolution_id;
    o_action := v_event.action;
    o_event_payload := v_event.event_payload;
    o_event_sha256 := v_event.event_sha256;
    o_occurred_at := v_event.occurred_at;
END
$$;
