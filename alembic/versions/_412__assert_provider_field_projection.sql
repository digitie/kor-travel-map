CREATE FUNCTION feature._assert_provider_field_projection(p_feature uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_active feature.provider_field_active_policies%ROWTYPE; v_winner record;
        v_effective jsonb; v_expected jsonb;
BEGIN
    SELECT * INTO v_active FROM feature.provider_field_active_policies WHERE feature_id=p_feature;
    IF NOT FOUND THEN RETURN; END IF;
    FOR v_winner IN SELECT * FROM feature.provider_field_scalar_winners(
        p_feature,v_active.policy_revision,v_active.field_paths) LOOP
        IF NOT EXISTS (SELECT 1 FROM feature.feature_base_field_values base
            WHERE base.feature_id=p_feature AND base.field_path=v_winner.field_path
              AND base.provider_dataset_id=v_winner.provider_dataset_id
              AND base.source_entity_key=v_winner.source_entity_key
              AND base.source_record_key=v_winner.value_source_record_key
              AND base.source_raw_payload_hash=v_winner.value_source_hash
              AND base.value_json IS NOT DISTINCT FROM v_winner.value_json
              AND base.value_geometry IS NULL AND base.observed_at=v_winner.value_observed_at) THEN
            RAISE EXCEPTION 'active scalar base is not the complete current candidate winner' USING ERRCODE='23514';
        END IF;
        SELECT override.override_value INTO v_expected FROM ops.feature_overrides override
            WHERE override.feature_id=p_feature AND override.field_path=v_winner.field_path
              AND override.status='active';
        IF NOT FOUND THEN v_expected:=v_winner.value_json; END IF;
        IF v_winner.field_path='core.name' THEN
            SELECT to_jsonb(name) INTO v_effective FROM feature.features WHERE feature_id=p_feature;
        ELSE
            SELECT to_jsonb(phones) INTO v_effective FROM feature.feature_places WHERE feature_id=p_feature;
        END IF;
        IF v_effective IS DISTINCT FROM v_expected THEN
            RAISE EXCEPTION 'active scalar effective value disagrees with winner or operator override' USING ERRCODE='23514';
        END IF;
    END LOOP;
END;
$$;
