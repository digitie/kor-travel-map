-- source 키의 기존 manifest target만 허용한다. EX에서는 정본 후속 trigger를 그대로 쓴다.
CREATE FUNCTION feature._strict_sh_source_row_guard()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_attempt uuid;
    v_dataset bigint;
    v_key text;
    v_existing provider_sync.source_entities%ROWTYPE;
BEGIN
    v_attempt:=feature._strict_sh_data_context(true);
    IF v_attempt IS NULL THEN
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_SCHEMA<>'provider_sync' OR TG_TABLE_NAME NOT IN
       ('source_entities','source_entity_heads','source_records') THEN
        RAISE EXCEPTION 'unknown strict source relation'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_profile';
    END IF;
    IF TG_TABLE_NAME='source_records' AND TG_OP='DELETE' THEN
        RAISE EXCEPTION 'shared source records are append-only'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
    END IF;
    SELECT provider_dataset_id INTO STRICT v_dataset FROM ops.feature_write_attempts
     WHERE attempt_id=v_attempt;
    -- source record의 raw_data를 직렬화하지 않고 명시 key 필드만 읽는다.
    IF TG_TABLE_NAME='source_entities' THEN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'shared source entity deletion is unsupported'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
        END IF;
        v_key:=NEW.source_entity_key;
        SELECT * INTO v_existing FROM provider_sync.source_entities WHERE source_entity_key=v_key;
        IF NOT FOUND OR NEW.provider_dataset_id IS DISTINCT FROM v_dataset
           OR v_existing.provider_dataset_id IS DISTINCT FROM v_dataset
           OR NEW.source_entity_type IS DISTINCT FROM v_existing.source_entity_type
           OR NEW.source_entity_id IS DISTINCT FROM v_existing.source_entity_id
           OR (TG_OP='UPDATE' AND OLD.source_entity_key IS DISTINCT FROM v_key) THEN
            RAISE EXCEPTION 'shared source entity must retain existing dataset and identity'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
        END IF;
        -- INSERT ON CONFLICT 후보의 first_seen_at은 새 값이어도 된다.
        -- 실제 UPDATE first_seen/last_seen 검사는 기존 immutable/seen trigger가 한다.
    ELSE
        v_key:=CASE WHEN TG_OP='DELETE' THEN OLD.source_entity_key ELSE NEW.source_entity_key END;
        IF TG_OP='UPDATE' AND OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key THEN
            RAISE EXCEPTION 'shared source row cannot change entity identity'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM provider_sync.source_entities
            WHERE source_entity_key=v_key AND provider_dataset_id=v_dataset) THEN
            RAISE EXCEPTION 'shared source row is outside its own dataset'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
        END IF;
        IF TG_TABLE_NAME='source_entity_heads' THEN
            IF TG_OP='DELETE' OR NOT EXISTS (SELECT 1 FROM provider_sync.source_entity_heads
                WHERE source_entity_key=v_key) OR NOT EXISTS (
                SELECT 1 FROM provider_sync.source_records
                 WHERE source_record_key=NEW.current_source_record_key AND source_entity_key=v_key) THEN
                RAISE EXCEPTION 'shared head must retain an existing head and owned record'
                    USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
            END IF;
        END IF;
        -- source_records UPDATE의 원 immutable 오류는 뒤의 정본 trigger가 보존한다.
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ops.feature_write_manifests
        WHERE attempt_id=v_attempt AND dependency_kind='source_head' AND dependency_key=v_key) THEN
        RAISE EXCEPTION 'shared source row is outside its frozen manifest'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_source_target';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
