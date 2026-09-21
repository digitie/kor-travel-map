CREATE PROCEDURE feature.reject_feature_request(IN p_request_id uuid, IN p_reason text, IN p_domain_command_id bigint, OUT o_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE v_command ops.domain_commands%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' OR session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_feature_request_admin_executor', 'member') THEN
        RAISE EXCEPTION 'Feature request rejection requires admin executor at READ COMMITTED' USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_request_executor';
    END IF;
    SELECT command.* INTO v_command FROM ops.domain_commands AS command WHERE command.command_id = p_domain_command_id FOR UPDATE;
    IF NOT FOUND OR v_command.operation <> 'admin.feature-request.reject.v1' OR btrim(v_command.actor) = '' OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result WHERE result.command_id = p_domain_command_id) THEN
        RAISE EXCEPTION 'Feature request rejection command does not match writer' USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_command';
    END IF;
    UPDATE ops.feature_requests SET status = 'rejected', resolved_at = clock_timestamp(), resolved_by_actor = v_command.actor,
        resolution_command_id = p_domain_command_id, rejection_reason = nullif(btrim(p_reason), '')
    WHERE request_id = p_request_id AND status = 'pending' RETURNING status INTO o_status;
    IF o_status IS NULL THEN RAISE EXCEPTION 'Feature request is not pending' USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_pending'; END IF;
END
$$;
