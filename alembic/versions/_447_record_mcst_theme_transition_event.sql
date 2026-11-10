CREATE OR REPLACE PROCEDURE feature.record_mcst_theme_transition_event(
    IN p_item_id uuid,
    OUT o_event_id uuid,
    OUT o_event_sequence bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
AS $_$
-- ADR-121 R4: MCST 전환 executor가 퇴역시킨 Feature 하나의 PinVi 참조 정리 사건(M05)을 남긴다.
-- 사건 payload 모양·hash·sequence 규칙은 resolve_manual_provider_dedup_case와 같다 — PinVi
-- 소비자는 case_id/resolution_id를 불투명 UUID로만 쓰므로 여기서는 batch_id/item_id를 싣는다.
DECLARE
    v_item ops.mcst_theme_transition_items%ROWTYPE;
    v_command_id bigint;
    v_old_lifecycle text;
    v_old_revision bigint;
    v_target_lifecycle text;
    v_target_revision bigint;
    v_action text;
    v_occurred_at timestamptz;
    v_payload jsonb;
    v_event_sha256 text;
BEGIN
    IF session_user <> 'ktm_feature_service'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'MEMBER') THEN
        RAISE EXCEPTION 'MCST theme transition event requires the feature service executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_mcst_theme_transition_event_executor';
    END IF;
    PERFORM ops.lock_scoped_feature_write_protocol(true);

    SELECT * INTO v_item FROM ops.mcst_theme_transition_items WHERE item_id = p_item_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MCST theme transition item does not exist'
            USING ERRCODE = 'P0002', CONSTRAINT = 'ck_mcst_theme_transition_event_item';
    END IF;
    SELECT command_id INTO STRICT v_command_id
      FROM ops.mcst_theme_transition_batches WHERE batch_id = v_item.batch_id;

    -- 사건은 이미 일어난 퇴역을 증언한다 — 퇴역 뒤 revision이 item과 같아야 한다.
    SELECT lifecycle_state, row_revision INTO v_old_lifecycle, v_old_revision
      FROM feature.features WHERE feature_id = v_item.feature_id;
    IF v_old_lifecycle IS DISTINCT FROM 'retired'
       OR v_old_revision IS DISTINCT FROM v_item.row_revision_after THEN
        RAISE EXCEPTION 'MCST theme transition event does not match the retired feature'
            USING ERRCODE = '55000', CONSTRAINT = 'ck_mcst_theme_transition_event_retired';
    END IF;

    v_action := CASE WHEN v_item.target_feature_id IS NULL THEN 'detach' ELSE 'rebind' END;
    IF v_action = 'rebind' THEN
        SELECT lifecycle_state, row_revision INTO v_target_lifecycle, v_target_revision
          FROM feature.features WHERE feature_id = v_item.target_feature_id;
        IF v_target_lifecycle IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION 'MCST theme transition replacement feature is not active'
                USING ERRCODE = '55000', CONSTRAINT = 'ck_mcst_theme_transition_event_replacement';
        END IF;
    END IF;

    -- sequence는 이 잠금 아래에서만 배정한다 — commit 순서 = sequence 순서(M05와 같은 잠금).
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-m05', 0));
    o_event_id := x_extension.gen_random_uuid();
    SELECT nextval(pg_get_serial_sequence(
        'ops.feature_reference_reconciliation_events', 'event_sequence'
    )) INTO o_event_sequence;
    v_occurred_at := clock_timestamp();
    v_payload := jsonb_build_object(
        'payload_schema_version', 1,
        'event_id', o_event_id,
        'event_sequence', o_event_sequence,
        'occurred_at', to_char(
            v_occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        'case_id', v_item.batch_id,
        'resolution_id', v_item.item_id,
        'action', v_action,
        'old_feature', jsonb_build_object(
            'feature_id', v_item.feature_id,
            'feature_uuid', CAST(v_item.feature_id AS text),
            'row_revision', v_item.old_row_revision
        ),
        'replacement_feature', CASE WHEN v_action = 'rebind' THEN jsonb_build_object(
            'feature_id', v_item.target_feature_id,
            'feature_uuid', CAST(v_item.target_feature_id AS text),
            'row_revision', v_target_revision
        ) ELSE NULL END,
        'manual_retire_transition_id', v_item.transition_id,
        'manual_retire_row_revision_after_transition', v_item.row_revision_after,
        'command_id', v_command_id
    );
    v_event_sha256 := encode(
        x_extension.digest(convert_to(v_payload::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO ops.feature_reference_reconciliation_events (
        event_id, event_sequence, origin_kind, case_id, resolution_id, action,
        old_feature_id, old_feature_row_revision_before_transition,
        replacement_feature_id, replacement_feature_row_revision,
        manual_retire_transition_id, manual_retire_row_revision_after_transition,
        command_id, payload_schema_version, event_payload, event_sha256, occurred_at
    ) OVERRIDING SYSTEM VALUE VALUES (
        o_event_id, o_event_sequence, 'mcst_theme_transition', v_item.batch_id,
        v_item.item_id, v_action,
        v_item.feature_id, v_item.old_row_revision,
        CASE WHEN v_action = 'rebind' THEN v_item.target_feature_id END,
        CASE WHEN v_action = 'rebind' THEN v_target_revision END,
        v_item.transition_id, v_item.row_revision_after, v_command_id,
        1, v_payload, v_event_sha256, v_occurred_at
    );
END
$_$;
