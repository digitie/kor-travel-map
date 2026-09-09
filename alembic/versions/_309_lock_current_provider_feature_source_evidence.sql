-- ─────────────────────────────────────────────────────────────────────────
-- feature.lock_current_provider_feature_source_evidence
--   p_feature_id : text → uuid  (provider_sync.source_links.feature_id가 uuid)
--   p_source_entity_key / p_source_record_key : text 그대로 (Feature id가 아니다)
--   RETURNS text 그대로 (반환값은 raw payload 해시다)
-- ─────────────────────────────────────────────────────────────────────────
SET ROLE ktm_feature_state_procedure_owner;

DROP FUNCTION feature.lock_current_provider_feature_source_evidence(text,bigint,text,text);

SET ROLE ktm_feature_schema_owner;

CREATE FUNCTION feature.lock_current_provider_feature_source_evidence(p_feature_id uuid, p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_raw_payload_hash text;
BEGIN
    -- Match the provider bundle writer exactly: dataset/entity/record/head,
    -- then its Feature source link, then the Feature row taken by the caller.
    -- In particular, do not lock the link first: a concurrent bundle holds
    -- the entity head while it later upserts the link, which would form a
    -- head↔link cycle.
    v_raw_payload_hash := feature.lock_current_provider_source_evidence(
        p_provider_dataset_id,
        p_source_entity_key,
        p_source_record_key
    );
    PERFORM 1
      FROM provider_sync.source_links AS link
     WHERE link.feature_id = p_feature_id
       AND link.source_entity_key = p_source_entity_key
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provider lifecycle transition requires linked source evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_provider_source_provenance';
    END IF;
    RETURN v_raw_payload_hash;
END;
$$;

ALTER FUNCTION feature.lock_current_provider_feature_source_evidence(p_feature_id uuid, p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) OWNER TO ktm_feature_state_procedure_owner;

-- head의 명시 ACL은 이 REVOKE 한 줄뿐이다(head-schema.sql:25050) — GRANT는 0건이다.
-- in-DB 호출자 3개가 전부 같은 소유자 role의 SECURITY DEFINER라 owner 권한으로 실행된다.
SET ROLE ktm_feature_state_procedure_owner;

REVOKE ALL ON FUNCTION feature.lock_current_provider_feature_source_evidence(p_feature_id uuid, p_provider_dataset_id bigint, p_source_entity_key text, p_source_record_key text) FROM PUBLIC;

SET ROLE ktm_feature_schema_owner;
