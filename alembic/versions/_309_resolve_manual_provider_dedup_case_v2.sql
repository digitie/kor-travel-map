DROP PROCEDURE feature.resolve_manual_provider_dedup_case_v2(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id text, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id text, OUT o_manual_feature_row_revision bigint);

CREATE PROCEDURE feature.resolve_manual_provider_dedup_case_v2(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops'
    AS $$
BEGIN
    -- An immutable cursor-zero subscription is the paired-consumer activation
    -- receipt. No M05 resolution (including "kept") can predate it.
    PERFORM 1
    FROM ops.feature_reference_reconciliation_subscriptions AS subscription
    JOIN ops.feature_reference_reconciliation_leases AS lease
      ON lease.principal_id = subscription.principal_id
    WHERE subscription.principal_id = 'service:feature-reference-reconciliation'
      AND subscription.initial_event_sequence = 0
      AND subscription.read_scope = 'feature-reference-reconciliation:read'
      AND subscription.ack_scope = 'feature-reference-reconciliation:ack'
      AND lease.acked_through_sequence >= 0
    FOR SHARE OF subscription, lease;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'feature reference reconciliation subscription is not provisioned'
            USING ERRCODE = 'P0002';
    END IF;
    CALL feature.resolve_manual_provider_dedup_case(
        p_case_id, p_decision, p_expected_case_fingerprint,
        p_expected_manual_row_revision, p_expected_provider_row_revision,
        p_survivor_feature_id, p_reason, p_actor, p_domain_command_id,
        o_outcome, o_resolution_id, o_event_id, o_manual_feature_id,
        o_manual_feature_row_revision
    );
END
$$;

ALTER PROCEDURE feature.resolve_manual_provider_dedup_case_v2(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint) OWNER TO ktm_manual_provider_dedup_procedure_owner;

REVOKE ALL ON PROCEDURE feature.resolve_manual_provider_dedup_case_v2(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.resolve_manual_provider_dedup_case_v2(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint) TO ktm_manual_provider_dedup_admin_executor;
