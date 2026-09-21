CREATE PROCEDURE feature.provision_feature_reference_reconciliation_subscription(IN p_principal_id text, IN p_initial_event_sequence bigint, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_initial_event_sequence bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
DECLARE
    v_max_event_sequence bigint;
    v_command ops.domain_commands%ROWTYPE;
    v_subscription ops.feature_reference_reconciliation_subscriptions%ROWTYPE;
    v_lease ops.feature_reference_reconciliation_leases%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_subscription_provision_isolation';
    END IF;
    IF session_user <> 'ktm_feature_service'
       OR NOT pg_has_role(
           session_user, 'ktm_manual_provider_dedup_admin_executor', 'member'
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision requires the admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_subscription_provision_executor';
    END IF;
    IF p_principal_id <> 'service:feature-reference-reconciliation'
       OR p_initial_event_sequence IS DISTINCT FROM 0
       OR nullif(btrim(p_actor), '') IS NULL OR char_length(p_actor) > 200
       OR p_domain_command_id IS NULL OR p_domain_command_id < 1 THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision input is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_input';
    END IF;
    -- There is exactly one paired-consumer activation receipt.  A row-level
    -- lock cannot serialize concurrent inserts while the row is absent.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('feature-reference-reconciliation-subscription', 0)
    );
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.feature-reference-reconciliation-subscription.provision.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription provision command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_command';
    END IF;
    SELECT coalesce(max(event.event_sequence), 0) INTO v_max_event_sequence
    FROM ops.feature_reference_reconciliation_events AS event;
    IF p_initial_event_sequence > v_max_event_sequence THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription cursor exceeds current event frontier'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_subscription_provision_input';
    END IF;
    SELECT subscription.* INTO v_subscription
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    WHERE subscription.principal_id = p_principal_id
    FOR UPDATE;
    IF FOUND THEN
        SELECT lease.* INTO v_lease
        FROM ops.feature_reference_reconciliation_leases AS lease
        WHERE lease.principal_id = p_principal_id
        FOR SHARE;
        IF NOT FOUND OR v_lease.acked_through_sequence < v_subscription.initial_event_sequence THEN
            RAISE EXCEPTION 'feature reference reconciliation subscription lease state is inconsistent'
                USING ERRCODE = '55000';
        END IF;
        o_outcome := 'already_provisioned';
        o_initial_event_sequence := v_subscription.initial_event_sequence;
        RETURN;
    END IF;
    INSERT INTO ops.feature_reference_reconciliation_subscriptions (
        principal_id, initial_event_sequence, read_scope, ack_scope
    ) VALUES (
        p_principal_id, p_initial_event_sequence,
        'feature-reference-reconciliation:read',
        'feature-reference-reconciliation:ack'
    );
    INSERT INTO ops.feature_reference_reconciliation_leases (
        principal_id, acked_through_sequence, worker_id, lease_epoch, lease_expires_at
    ) VALUES (
        p_principal_id, p_initial_event_sequence, NULL, 0, NULL
    );
    o_outcome := 'provisioned';
    o_initial_event_sequence := p_initial_event_sequence;
END
$$;
