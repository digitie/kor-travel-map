-- 정본 activation에 연결하지 않는 schema-owner 전용 설치기다.
CREATE FUNCTION feature._install_strict_sh_data_guards()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_relations text[]:=ARRAY['feature.feature_areas','feature.feature_base_field_values','feature.feature_creation_origins','feature.feature_events','feature.feature_geocode_stamps','feature.feature_notices','feature.feature_places','feature.feature_route_geometries','feature.feature_routes','feature.features','feature.manual_feature_identity_claims','feature.provider_field_active_policies','feature.provider_field_policy_epoch','feature.provider_field_shadow_candidates','feature.provider_field_shadow_policies','ops.feature_override_field_paths','ops.feature_overrides','provider_sync.provider_dataset_operation_scopes','provider_sync.provider_dataset_operations','provider_sync.provider_datasets','provider_sync.provider_feature_identities','provider_sync.source_entities','provider_sync.source_entity_heads','provider_sync.source_links','provider_sync.source_records'];
    v_shared text[]:=ARRAY['feature.feature_base_field_values','feature.feature_geocode_stamps','feature.feature_places','feature.features','feature.provider_field_shadow_candidates','provider_sync.source_entities','provider_sync.source_entity_heads','provider_sync.source_records'];
    v_relation text;
    v_profile text;
    v_function regprocedure;
    v_expected integer:=33;
    v_count integer;
    v_trigger record;
BEGIN
    -- P EX 이전에는 table/epoch/행을 잠그지 않는다.
    PERFORM feature._strict_sh_data_context(false);
    SELECT count(*) INTO v_count FROM pg_trigger
     WHERE NOT tgisinternal AND tgfoid IN (
        'feature._strict_sh_data_statement_guard()'::regprocedure,
        'feature._strict_sh_source_row_guard()'::regprocedure,
        'feature._strict_sh_feature_row_guard()'::regprocedure);
    IF v_count NOT IN (0,v_expected) THEN
        RAISE EXCEPTION 'partial strict data guard installation'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_inventory';
    END IF;
    IF v_count=0 THEN
        -- 인접 호출자의 table lock 순서는 고정한다. 성공 후만 33개 전체가 보인다.
        FOREACH v_relation IN ARRAY v_relations LOOP
            EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE',v_relation::regclass);
        END LOOP;
        FOREACH v_relation IN ARRAY v_relations LOOP
            v_profile:=CASE WHEN v_relation=ANY(v_shared) THEN 'strict_sh' ELSE 'ex_only' END;
            EXECUTE format('CREATE TRIGGER trg_00_strict_sh_data_protocol BEFORE INSERT OR UPDATE OR DELETE ON %s FOR EACH STATEMENT EXECUTE FUNCTION feature._strict_sh_data_statement_guard(%L)',v_relation::regclass,v_profile);
            IF v_relation=ANY(v_shared) THEN
                v_function:=CASE WHEN v_relation LIKE 'provider_sync.%'
                    THEN 'feature._strict_sh_source_row_guard()'::regprocedure
                    ELSE 'feature._strict_sh_feature_row_guard()'::regprocedure END;
                EXECUTE format('CREATE TRIGGER trg_00_strict_sh_data_target BEFORE INSERT OR UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION %s',v_relation::regclass,v_function);
            END IF;
        END LOOP;
    END IF;
    -- 기존 이름과 부딪히면 CREATE 자체가 원자적으로 실패한다. disabled/타표/타함수도 거부한다.
    FOREACH v_relation IN ARRAY v_relations LOOP
        v_profile:=CASE WHEN v_relation=ANY(v_shared) THEN 'strict_sh' ELSE 'ex_only' END;
        SELECT * INTO v_trigger FROM pg_trigger
         WHERE tgrelid=v_relation::regclass AND tgname='trg_00_strict_sh_data_protocol';
        IF NOT FOUND OR v_trigger.tgisinternal OR v_trigger.tgtype<>30
           OR v_trigger.tgenabled<>'O' OR v_trigger.tgconstraint<>0
           OR v_trigger.tgfoid<>'feature._strict_sh_data_statement_guard()'::regprocedure
           OR v_trigger.tgnargs<>1 OR v_trigger.tgargs<>
                convert_to(v_profile,'UTF8')||decode('00','hex')
           OR v_trigger.tgqual IS NOT NULL OR cardinality(v_trigger.tgattr::smallint[])<>0 THEN
            RAISE EXCEPTION 'strict statement guard definition drift'
                USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_inventory';
        END IF;
        IF v_relation=ANY(v_shared) THEN
            v_function:=CASE WHEN v_relation LIKE 'provider_sync.%'
                THEN 'feature._strict_sh_source_row_guard()'::regprocedure
                ELSE 'feature._strict_sh_feature_row_guard()'::regprocedure END;
            SELECT * INTO v_trigger FROM pg_trigger
             WHERE tgrelid=v_relation::regclass AND tgname='trg_00_strict_sh_data_target';
            IF NOT FOUND OR v_trigger.tgisinternal OR v_trigger.tgtype<>31
               OR v_trigger.tgenabled<>'O' OR v_trigger.tgconstraint<>0
               OR v_trigger.tgfoid<>v_function OR v_trigger.tgnargs<>0
               OR v_trigger.tgargs<>''::bytea OR v_trigger.tgqual IS NOT NULL
               OR cardinality(v_trigger.tgattr::smallint[])<>0 THEN
                RAISE EXCEPTION 'strict target guard definition drift'
                    USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_inventory';
            END IF;
        END IF;
    END LOOP;
    SELECT count(*) INTO v_count FROM pg_trigger
     WHERE NOT tgisinternal AND tgfoid IN (
        'feature._strict_sh_data_statement_guard()'::regprocedure,
        'feature._strict_sh_source_row_guard()'::regprocedure,
        'feature._strict_sh_feature_row_guard()'::regprocedure);
    IF v_count<>v_expected THEN
        RAISE EXCEPTION 'strict guard relation set drift'
            USING ERRCODE='23514',CONSTRAINT='ck_strict_data_guard_inventory';
    END IF;
END;
$$;
