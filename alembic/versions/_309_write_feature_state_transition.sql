CREATE FUNCTION feature.write_feature_state_transition() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_context_text text;
    v_context jsonb;
    v_state_definer text;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.lifecycle_state IS NOT DISTINCT FROM NEW.lifecycle_state
       AND OLD.publication_state IS NOT DISTINCT FROM NEW.publication_state
       AND OLD.quality_state IS NOT DISTINCT FROM NEW.quality_state THEN
        RETURN NULL;
    END IF;

    v_context_text := current_setting('feature.state_transition_context', true);
    v_state_definer := current_setting('feature.state_procedure_definer', true);
    IF v_context_text IS NULL
       OR v_state_definer <> 'ktm_feature_state_procedure_owner'
       OR current_user <> 'ktm_feature_audit_writer' THEN
        -- schema/migration owner는 runtime trust boundary 밖이다. existing DDL
        -- migration과 fixture seeding은 이 privileged identity로만 direct write를
        -- 수행할 수 있고, application runtime login은 아래 privilege fence에서
        -- 이 분기에 도달하기 전에 거부된다.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = session_user
              AND role_row.rolsuper
        ) THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'feature state mutation requires the state procedure context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;
    v_context := v_context_text::jsonb;
    IF jsonb_typeof(v_context) IS DISTINCT FROM 'object'
       OR (v_context ->> 'transition_kind') NOT IN (
            'initial', 'legacy_backfill', 'provider_sync', 'admin', 'user_request',
            'merge', 'quality_validation', 'system'
       )
       OR coalesce(btrim(v_context ->> 'reason_code'), '') = ''
       OR coalesce(btrim(v_context ->> 'principal'), '') = '' THEN
        RAISE EXCEPTION 'feature state mutation has malformed context'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_context';
    END IF;

    IF TG_OP = 'INSERT' AND (v_context ->> 'transition_kind') NOT IN (
        'initial', 'legacy_backfill', 'provider_sync'
    ) THEN
        RAISE EXCEPTION 'feature insert needs initial or provider-sync state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;
    IF TG_OP = 'UPDATE' AND (v_context ->> 'transition_kind') IN ('initial', 'legacy_backfill') THEN
        RAISE EXCEPTION 'feature update cannot use initial state transition kind'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_state_transition_kind';
    END IF;

    INSERT INTO feature.feature_state_transitions (
        feature_id,
        from_lifecycle_state, from_publication_state, from_quality_state,
        to_lifecycle_state, to_publication_state, to_quality_state,
        transition_kind, reason_code, principal, causation_ref,
        provider_dataset_id, source_entity_key, source_record_key, provider_evidence,
        occurred_at,
        row_revision, invoker_role, state_procedure_definer, audit_writer_definer
    ) VALUES (
        NEW.feature_id,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.lifecycle_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.publication_state END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.quality_state END,
        NEW.lifecycle_state, NEW.publication_state, NEW.quality_state,
        v_context ->> 'transition_kind', v_context ->> 'reason_code',
        v_context ->> 'principal', v_context ->> 'causation_ref',
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN (v_context ->> 'provider_dataset_id')::bigint END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_entity_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context ->> 'source_record_key' END,
        CASE WHEN v_context ->> 'transition_kind' = 'provider_sync'
             THEN v_context -> 'provider_evidence' END,
        clock_timestamp(),
        NEW.row_revision, session_user::text, v_state_definer, current_user::text
    );
    RETURN NULL;
END;
$$;


ALTER FUNCTION feature.write_feature_state_transition() OWNER TO ktm_feature_audit_writer;
