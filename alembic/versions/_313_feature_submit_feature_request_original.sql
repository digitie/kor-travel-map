CREATE OR REPLACE PROCEDURE feature.submit_feature_request(IN p_request_id uuid, IN p_request_payload jsonb, IN p_domain_command_id bigint, OUT o_status text, OUT o_submitted_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $_$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
    v_existing ops.feature_requests%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Feature request submission requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_feature_request_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_feature_request_service_executor', 'member') THEN
        RAISE EXCEPTION 'Feature request submission requires service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_feature_request_executor';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command WHERE command.command_id = p_domain_command_id FOR UPDATE;
    IF NOT FOUND OR v_command.operation <> 'service.feature-request.submit.v1'
       OR btrim(v_command.actor) <> 'service:feature-request'
       OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result WHERE result.command_id = p_domain_command_id) THEN
        RAISE EXCEPTION 'Feature request submission command does not match writer'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_command';
    END IF;
    IF p_request_id IS NULL OR jsonb_typeof(p_request_payload) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_request_payload -> 'kind') IS DISTINCT FROM 'string'
       OR p_request_payload ->> 'kind' NOT IN ('place', 'event')
       OR jsonb_typeof(p_request_payload -> 'name') IS DISTINCT FROM 'string'
       OR nullif(btrim(p_request_payload ->> 'name'), '') IS NULL
       OR char_length(p_request_payload ->> 'name') > 200
       OR jsonb_typeof(p_request_payload -> 'lon') IS DISTINCT FROM 'number'
       OR (p_request_payload ->> 'lon')::numeric NOT BETWEEN 124 AND 132
       OR jsonb_typeof(p_request_payload -> 'lat') IS DISTINCT FROM 'number'
       OR (p_request_payload ->> 'lat')::numeric NOT BETWEEN 33 AND 39.5
       OR jsonb_typeof(p_request_payload -> 'categories') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_request_payload -> 'categories') > 10
       OR jsonb_path_exists(
            p_request_payload,
            '$.categories[*] ? (@.type() != "string")'
       )
       OR (
            p_request_payload ? 'note'
            AND (
                jsonb_typeof(p_request_payload -> 'note') IS DISTINCT FROM 'string'
                OR char_length(p_request_payload ->> 'note') > 2000
            )
       )
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_request_payload) AS key_name(key_name)
                  WHERE key_name NOT IN ('kind', 'name', 'lon', 'lat', 'categories', 'note')) THEN
        RAISE EXCEPTION 'Feature request payload is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_requests_payload';
    END IF;
    INSERT INTO ops.feature_requests (request_id, request_payload, submission_command_id)
    VALUES (p_request_id, p_request_payload, p_domain_command_id)
    ON CONFLICT (request_id) DO NOTHING
    RETURNING status, submitted_at INTO o_status, o_submitted_at;
    IF o_status IS NULL THEN
        SELECT request.* INTO v_existing
        FROM ops.feature_requests AS request WHERE request.request_id = p_request_id;
        IF NOT FOUND OR v_existing.request_payload IS DISTINCT FROM p_request_payload THEN
        RAISE EXCEPTION 'Feature request id conflicts with a different payload'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_request_idempotency';
        END IF;
        o_status := v_existing.status;
        o_submitted_at := v_existing.submitted_at;
    END IF;
END
$_$;
