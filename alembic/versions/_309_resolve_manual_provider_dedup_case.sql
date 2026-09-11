-- 이 사이드카는 자기 역할 창을 스스로 연다.
--
-- 바깥에서 `SET ROLE`로 묶으면 순서에 결박된다 — 자기 창을 가진 사이드카가 끝에서
-- 스키마 소유자로 되돌리는 순간, 뒤따르는 파일은 바깥 그룹이 지정한 롤이 아니라
-- 스키마 소유자로 실행된다. 2026-09-09 n150 실행이 그것을 잡았다
-- (`must be owner of function derive_subtype_public_ready`).
--
-- 롤은 NOINHERIT라 멤버십만으로는 소유자 검사를 통과하지 못한다. `feature` 스키마는
-- 모든 소유자 롤이 `ALL`을 가지므로(alembic/head-schema.sql:24731-24737) 이 창 안에서
-- DROP·CREATE·GRANT가 모두 성립한다.
SET ROLE ktm_manual_provider_dedup_procedure_owner;

DROP PROCEDURE feature.resolve_manual_provider_dedup_case(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id text, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id text, OUT o_manual_feature_row_revision bigint);

CREATE PROCEDURE feature.resolve_manual_provider_dedup_case(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $_$
DECLARE
    v_case ops.manual_provider_dedup_cases%ROWTYPE;
    v_manual feature.features%ROWTYPE;
    v_provider feature.features%ROWTYPE;
    v_origin feature.feature_creation_origins%ROWTYPE;
    v_source record;
    v_primary_source_count integer;
    v_command ops.domain_commands%ROWTYPE;
    v_transition_feature_id uuid;
    v_transition_row_revision bigint;
    v_transition_id bigint;
    v_action text;
    v_payload jsonb;
    v_event_sha256 text;
    v_event_sequence bigint;
    v_occurred_at timestamptz;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'manual/provider dedup decision requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_decision_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup decision requires the admin-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_decision_executor';
    END IF;
    IF p_case_id IS NULL
       OR p_decision NOT IN ('kept', 'merged', 'manual_retired')
       OR p_expected_case_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_expected_manual_row_revision IS NULL OR p_expected_manual_row_revision < 1
       OR p_expected_provider_row_revision IS NULL OR p_expected_provider_row_revision < 1
       OR nullif(btrim(p_reason), '') IS NULL
       OR nullif(btrim(p_actor), '') IS NULL
       OR p_domain_command_id IS NULL OR p_domain_command_id < 1
       OR (p_decision = 'merged' AND p_survivor_feature_id IS NULL)
       OR (p_decision <> 'merged' AND p_survivor_feature_id IS NOT NULL) THEN
        RAISE EXCEPTION 'manual/provider dedup decision input is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_decision_input';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_domain_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.manual-provider-dedup-case.resolve.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_domain_command_id
       ) THEN
        RAISE EXCEPTION 'manual/provider dedup decision command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_decision_command';
    END IF;

    -- A sequence is allocated only while this fence is held.  Thus its commit
    -- visibility order is the same as the reconciliation action order.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-m05', 0));
    SELECT candidate.* INTO v_case
    FROM ops.manual_provider_dedup_cases AS candidate
    WHERE candidate.case_id = p_case_id
    FOR UPDATE;
    IF NOT FOUND
       OR EXISTS (
           SELECT 1 FROM ops.manual_provider_dedup_resolutions AS resolution
           WHERE resolution.case_id = p_case_id
       )
       OR v_case.evidence_fingerprint <> p_expected_case_fingerprint
       OR v_case.manual_feature_row_revision <> p_expected_manual_row_revision
       OR v_case.provider_feature_row_revision <> p_expected_provider_row_revision THEN
        o_outcome := 'stale';
        RETURN;
    END IF;

    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_id IN (v_case.manual_feature_id, v_case.provider_feature_id)
    ORDER BY locked.feature_id
    FOR UPDATE;
    SELECT * INTO v_manual
    FROM feature.features
    WHERE feature_id = v_case.manual_feature_id
    FOR UPDATE;
    SELECT * INTO v_provider
    FROM feature.features
    WHERE feature_id = v_case.provider_feature_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_manual.row_revision <> v_case.manual_feature_row_revision
       OR v_provider.row_revision <> v_case.provider_feature_row_revision
       OR v_manual.lifecycle_state <> 'active' OR v_manual.publication_state <> 'published'
       OR v_manual.quality_state <> 'valid' OR v_provider.lifecycle_state <> 'active'
       OR v_provider.publication_state <> 'published' OR v_provider.quality_state <> 'valid'
       OR v_manual.coord IS NULL OR v_provider.coord IS NULL THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT origin.* INTO v_origin
    FROM feature.feature_creation_origins AS origin
    WHERE origin.feature_id = v_manual.feature_id
      AND origin.creation_command_id = v_case.manual_creation_command_id
      AND origin.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request');
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = v_manual.feature_id
          AND claim.claimed_by_command_id = v_origin.creation_command_id
    ) THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT count(*) INTO v_primary_source_count
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary';
    IF v_primary_source_count <> 1 THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    SELECT entity.provider_dataset_id, link.source_entity_key,
           head.current_source_record_key AS source_record_key,
           source.raw_payload_hash, head.observed_at
    INTO v_source
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = v_provider.feature_id
      AND link.source_role = 'primary'
    FOR SHARE OF link, entity, head, source;
    IF NOT FOUND
       OR v_source.provider_dataset_id <> v_case.provider_dataset_id
       OR v_source.source_entity_key <> v_case.source_entity_key
       OR v_source.source_record_key <> v_case.source_record_key
       OR v_source.raw_payload_hash <> v_case.source_record_raw_payload_hash
       OR v_source.observed_at <> v_case.source_head_observed_at THEN
        o_outcome := 'stale';
        RETURN;
    END IF;
    IF p_decision = 'merged' AND p_survivor_feature_id <> v_provider.feature_id THEN
        o_outcome := 'stale';
        RETURN;
    END IF;

    INSERT INTO ops.manual_provider_dedup_resolutions (
        case_id, decision, command_id, actor, reason
    ) VALUES (
        v_case.case_id, p_decision, p_domain_command_id, p_actor, btrim(p_reason)
    ) RETURNING resolution_id INTO o_resolution_id;
    o_manual_feature_id := v_manual.feature_id;
    IF p_decision = 'kept' THEN
        o_outcome := 'kept';
        o_manual_feature_row_revision := v_manual.row_revision;
        RETURN;
    END IF;

    CALL feature.transition_admin_feature_state(
        v_manual.feature_id, NULL, NULL, NULL, v_manual.row_revision,
        'manual-provider-dedup', p_actor, 'retire',
        v_transition_feature_id, v_transition_row_revision, v_transition_id
    );
    IF v_transition_feature_id <> v_manual.feature_id
       OR v_transition_row_revision <> v_manual.row_revision + 1
       OR v_transition_id IS NULL THEN
        RAISE EXCEPTION 'manual/provider dedup retirement transition is inconsistent'
            USING ERRCODE = '55000';
    END IF;
    v_action := CASE WHEN p_decision = 'merged' THEN 'rebind' ELSE 'detach' END;
    o_event_id := x_extension.gen_random_uuid();
    SELECT nextval(pg_get_serial_sequence(
        'ops.feature_reference_reconciliation_events', 'event_sequence'
    )) INTO v_event_sequence;
    v_occurred_at := clock_timestamp();
    v_payload := jsonb_build_object(
        'payload_schema_version', 1,
        'event_id', o_event_id,
        'event_sequence', v_event_sequence,
        'occurred_at', to_char(
            v_occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        'case_id', v_case.case_id,
        'resolution_id', o_resolution_id,
        'action', v_action,
        'old_feature', jsonb_build_object(
            'feature_id', v_manual.feature_id,
            'feature_uuid', CAST(v_manual.feature_id AS text),
            'row_revision', v_manual.row_revision
        ),
        'replacement_feature', CASE WHEN v_action = 'rebind' THEN jsonb_build_object(
            'feature_id', v_provider.feature_id,
            'feature_uuid', CAST(v_provider.feature_id AS text),
            'row_revision', v_provider.row_revision
        ) ELSE NULL END,
        'manual_retire_transition_id', v_transition_id,
        'manual_retire_row_revision_after_transition', v_transition_row_revision,
        'command_id', p_domain_command_id
    );
    v_event_sha256 := encode(
        x_extension.digest(convert_to(v_payload::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO ops.feature_reference_reconciliation_events (
        event_id, event_sequence, case_id, resolution_id, action,
        old_feature_id, old_feature_row_revision_before_transition,
        replacement_feature_id, replacement_feature_row_revision,
        manual_retire_transition_id, manual_retire_row_revision_after_transition,
        command_id, payload_schema_version, event_payload, event_sha256, occurred_at
    ) OVERRIDING SYSTEM VALUE VALUES (
        o_event_id, v_event_sequence, v_case.case_id, o_resolution_id, v_action,
        v_manual.feature_id, v_manual.row_revision,
        CASE WHEN v_action = 'rebind' THEN v_provider.feature_id END,
        CASE WHEN v_action = 'rebind' THEN v_provider.row_revision END,
        v_transition_id, v_transition_row_revision, p_domain_command_id,
        1, v_payload, v_event_sha256, v_occurred_at
    );
    o_manual_feature_row_revision := v_transition_row_revision;
    o_outcome := p_decision;
END
$_$;

DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_manual_provider_dedup_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_manual_provider_dedup_procedure_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.resolve_manual_provider_dedup_case(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint) OWNER TO ktm_manual_provider_dedup_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_provider_dedup_procedure_owner';
    END IF;
END
$t39_owner$;

REVOKE ALL ON PROCEDURE feature.resolve_manual_provider_dedup_case(IN p_case_id uuid, IN p_decision text, IN p_expected_case_fingerprint text, IN p_expected_manual_row_revision bigint, IN p_expected_provider_row_revision bigint, IN p_survivor_feature_id uuid, IN p_reason text, IN p_actor text, IN p_domain_command_id bigint, OUT o_outcome text, OUT o_resolution_id uuid, OUT o_event_id uuid, OUT o_manual_feature_id uuid, OUT o_manual_feature_row_revision bigint) FROM PUBLIC;

SET ROLE ktm_feature_schema_owner;
