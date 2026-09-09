DROP PROCEDURE ops.record_curation_import_manual_feature_child(uuid, integer, text, text, bigint, uuid, uuid, uuid, uuid);


CREATE PROCEDURE ops.record_curation_import_manual_feature_child(IN p_import_plan_id uuid, IN p_plan_row_number integer, IN p_plan_sha256 text, IN p_manual_payload_sha256 text, IN p_child_command_id bigint, IN p_feature_id uuid, IN p_import_row_id uuid, IN p_curation_item_id uuid, IN p_link_decision_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $_$
DECLARE
    v_command ops.domain_commands%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'import child linkage requires SERIALIZABLE'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m03_child_linkage_isolation';
    END IF;
    IF session_user <> 'ktm_feature_api_runtime'
       OR NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
        RAISE EXCEPTION 'import child linkage requires the admin executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m03_child_linkage_executor';
    END IF;
    SELECT command.* INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_child_command_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_command.operation <> 'admin.curation-import.manual-feature-row.create-v1'
       OR btrim(v_command.actor) = '' THEN
        RAISE EXCEPTION 'import child linkage command does not match the child operation'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_command';
    END IF;
    IF p_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_manual_payload_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'import child linkage digests are not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_digest';
    END IF;
    -- 존재 결박(plan claim/plan row/claim causation/receipt/decision evidence)은
    -- `301` FK가 강제한다. FK가 못 보는 **인자 사이 정합**은 여기서 fail-close한다
    -- (적대 리뷰 H3 — 교차된 linkage가 FK 일곱을 전부 만족한 채 통과했다).
    IF NOT EXISTS (
        SELECT 1 FROM feature.curation_import_rows AS import_row
        WHERE import_row.import_row_id = p_import_row_id
          AND import_row.curation_item_id = p_curation_item_id
          AND import_row.row_number = p_plan_row_number
    ) THEN
        RAISE EXCEPTION 'import receipt does not match the plan row number'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_row_number';
    END IF;
    IF (
        SELECT plan_row.normalized_payload ->> 'manual_feature_sha256'
        FROM feature.curation_import_plan_rows AS plan_row
        WHERE plan_row.import_plan_id = p_import_plan_id
          AND plan_row.row_number = p_plan_row_number
    ) IS DISTINCT FROM p_manual_payload_sha256 THEN
        RAISE EXCEPTION 'manual payload digest does not match the immutable plan row'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_payload';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM feature.curation_link_decisions AS decision
        WHERE decision.decision_id = p_link_decision_id
          AND decision.decision_kind = 'accepted'
          AND decision.match_basis = 'manual_feature_child'
    ) THEN
        RAISE EXCEPTION 'linkage decision must be an accepted manual_feature_child decision'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_decision';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM feature.curation_items AS item
        WHERE item.curation_item_id = p_curation_item_id
          AND item.feature_id = p_feature_id
    ) THEN
        RAISE EXCEPTION 'curation item is not bound to the linkage feature'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_feature';
    END IF;
    IF v_command.actor IS DISTINCT FROM (
        SELECT parent.actor
        FROM ops.curation_import_plan_claims AS claim
        JOIN ops.domain_commands AS parent ON parent.command_id = claim.command_id
        WHERE claim.import_plan_id = p_import_plan_id
          AND claim.plan_sha256 = p_plan_sha256
    ) THEN
        RAISE EXCEPTION 'child actor does not match the claimed plan actor'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m03_child_linkage_actor';
    END IF;
    INSERT INTO ops.curation_import_manual_feature_children (
        import_plan_id, plan_row_number, plan_sha256, manual_payload_sha256,
        child_command_id, feature_id, import_row_id, curation_item_id,
        link_decision_id
    ) VALUES (
        p_import_plan_id, p_plan_row_number, p_plan_sha256, p_manual_payload_sha256,
        p_child_command_id, p_feature_id, p_import_row_id, p_curation_item_id,
        p_link_decision_id
    );
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
    had_create := has_schema_privilege('ktm_curation_command_owner', 'ops', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA ops TO ktm_curation_command_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE ops.record_curation_import_manual_feature_child(IN p_import_plan_id uuid, IN p_plan_row_number integer, IN p_plan_sha256 text, IN p_manual_payload_sha256 text, IN p_child_command_id bigint, IN p_feature_id uuid, IN p_import_row_id uuid, IN p_curation_item_id uuid, IN p_link_decision_id uuid) OWNER TO ktm_curation_command_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner';
    END IF;
END
$t39_owner$;


REVOKE ALL ON PROCEDURE ops.record_curation_import_manual_feature_child(IN p_import_plan_id uuid, IN p_plan_row_number integer, IN p_plan_sha256 text, IN p_manual_payload_sha256 text, IN p_child_command_id bigint, IN p_feature_id uuid, IN p_import_row_id uuid, IN p_curation_item_id uuid, IN p_link_decision_id uuid) FROM PUBLIC;
GRANT ALL ON PROCEDURE ops.record_curation_import_manual_feature_child(IN p_import_plan_id uuid, IN p_plan_row_number integer, IN p_plan_sha256 text, IN p_manual_payload_sha256 text, IN p_child_command_id bigint, IN p_feature_id uuid, IN p_import_row_id uuid, IN p_curation_item_id uuid, IN p_link_decision_id uuid) TO ktm_curation_admin_executor;
