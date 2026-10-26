-- 432: DB 소속으로 고정한 Airport/Rest만 등록한다. 기존430 원본은 보존한다.
CREATE OR REPLACE FUNCTION ops.register_provider_snapshot_artifact(
    p_root uuid,p_source_job uuid,p_member uuid,p_payload bytea,p_context bytea,
    p_native_digest text,p_lease_seconds integer
) RETURNS TABLE(snapshot_id uuid,created boolean,generation bigint,fence uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE
    v_member ops.import_job_datasets%ROWTYPE;
    v_dataset record;
    v_domain text;
    v_observation_domain text;
    v_source_type text;
    v_max_count integer;
    v_export jsonb;
    v_collection jsonb;
    v_existing record;
    v_payload jsonb;
    v_context jsonb;
    v_pin jsonb;
    v_key text;
    v_pin_keys text[]:=ARRAY['code_revision','sdk_inventory_sha256','provider','dataset_key',
        'source_entity_type','normalizer_revision','geo_domain','clock_domain','native_domain'];
    v_payload_keys text[]:=ARRAY['version','domain','pins','native_input_digest','bundles','geo'];
    v_context_keys text[]:=ARRAY['version','domain','artifact_sha256','pins','root_run_id',
        'observation_generation','upstream_eof','validation_mode','dropped','source_observations',
        'validation','geo_stats'];
    v_run text;
    v_generation text;
    v_suffix text;
    v_count integer;
    v_bytes bigint;
    v_quota bigint;
    v_limit ops.provider_snapshot_quota_limits%ROWTYPE;
    v_snapshot uuid;
    v_fence uuid;
    v_now timestamptz;
BEGIN
    IF NOT pg_has_role(session_user,'ktm_curation_provider_executor','member') THEN
        RAISE EXCEPTION 'snapshot registration requires provider executor' USING ERRCODE='42501';
    END IF;
    IF p_root IS NULL OR p_source_job IS NULL OR p_member IS NULL
       OR p_payload IS NULL OR p_context IS NULL OR p_native_digest IS NULL
       OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 5 AND 300 THEN
        RAISE EXCEPTION 'invalid snapshot registration input' USING ERRCODE='22023';
    END IF;
    -- bytea 길이는 TOAST raw length로 확인하고 JSON/UTF8 전개 전에 상한을 고정한다.
    IF octet_length(p_payload) NOT BETWEEN 1 AND 1048576
       OR octet_length(p_context) NOT BETWEEN 1 AND 8192
       OR octet_length(p_native_digest)<>64 THEN
        RAISE EXCEPTION 'snapshot registration input exceeds its bounds' USING ERRCODE='22023';
    END IF;
    IF p_native_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid native input digest' USING ERRCODE='22023';
    END IF;
    IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION 'snapshot registration requires READ COMMITTED' USING ERRCODE='25001';
    END IF;
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(false);
    SELECT * INTO STRICT v_member FROM ops.import_job_datasets member
        WHERE member.import_job_dataset_id=p_member AND member.job_id=p_source_job;
    -- 불변 UUID로만 먼저 해석한다. 가변 membership key는 길이를 확인한 뒤 비교한다.
    IF v_member.provider_dataset_id<=0 OR octet_length(v_member.sync_scope) NOT BETWEEN 1 AND 128
       OR octet_length(v_member.operation_key) NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'unsupported member key' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    PERFORM 1 FROM provider_sync.provider_datasets
        WHERE provider_dataset_id=v_member.provider_dataset_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'snapshot dataset changed; replan' USING ERRCODE='40001';
    END IF;
    PERFORM ops._lock_scoped_feature_write_scope(v_member.provider_dataset_id,'[]'::jsonb,false);
    SELECT root.dagster_run_id INTO v_run
    FROM ops.import_jobs root
    WHERE root.job_id=p_root AND root.kind='provider_feature_load_run'
      AND root.status='running' AND root.dagster_run_status='STARTED'
      AND root.dagster_run_id IS NOT NULL
      AND root.cancellation_id IS NULL AND root.cancellation_requested_at IS NULL
      AND root.quarantined_at IS NULL AND root.root_id=root.job_id AND root.root_kind='import_job'
    ;
    IF NOT FOUND OR octet_length(v_run) NOT BETWEEN 1 AND 128 THEN
        RAISE EXCEPTION 'snapshot root is not active' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    -- metadata 길이를 먼저 확인한 CASE 안에서만 저장된 child run을 비교한다.
    PERFORM 1 FROM ops.import_jobs child
    WHERE child.job_id=p_source_job AND child.parent_job_id=p_root AND child.kind='provider_feature_load'
      AND child.status IN ('queued','running')
      AND CASE WHEN octet_length(child.dagster_run_id) BETWEEN 1 AND 128
          THEN child.dagster_run_id=v_run ELSE false END
      AND child.cancellation_id IS NULL AND child.cancellation_requested_at IS NULL
      AND child.quarantined_at IS NULL AND child.root_id=p_root AND child.root_kind='import_job'
      AND child.dataset_membership_mode='single'
      AND (SELECT count(*) FROM ops.import_job_datasets members WHERE members.job_id=child.job_id)=1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'snapshot member is not an active single child' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_member_binding';
    END IF;
    SELECT dataset.provider,dataset.dataset_key INTO STRICT v_dataset
    FROM provider_sync.provider_datasets dataset
    JOIN provider_sync.provider_dataset_operations operation
      ON operation.provider_dataset_id=dataset.provider_dataset_id
    WHERE dataset.provider_dataset_id=v_member.provider_dataset_id AND dataset.is_active
      AND operation.operation_key=v_member.operation_key AND operation.is_enabled
      AND operation.operation_kind='refresh';
    IF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_airports' THEN
        v_domain:='airport-prepared-typed-v1';
        v_observation_domain:='airport-snapshot-observation-v1';
        v_source_type:='airport';
        v_max_count:=2730;
    ELSIF v_dataset.provider='kor-travel-transport' AND v_dataset.dataset_key='transport_rest_areas' THEN
        v_domain:='rest-area-prepared-typed-v1';
        v_observation_domain:='rest-area-snapshot-observation-v1';
        v_source_type:='rest_area';
        v_max_count:=256;
        v_context_keys:=v_context_keys||ARRAY['export_window'];
    ELSE
        RAISE EXCEPTION 'unsupported registered snapshot dataset' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;

    -- JSON header 확인은 DTO/clock/validation 권위가 아니다. 실제 apply가 exact codec을 재검증한다.
    v_payload:=convert_from(p_payload,'UTF8')::jsonb;
    v_context:=convert_from(p_context,'UTF8')::jsonb;
    IF jsonb_typeof(v_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(v_context) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'snapshot envelopes must be objects' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(v_payload))<>6
       OR NOT (v_payload ?& v_payload_keys)
       OR (SELECT count(*) FROM jsonb_object_keys(v_context))<>cardinality(v_context_keys)
       OR NOT (v_context ?& v_context_keys) THEN
        RAISE EXCEPTION 'unexpected snapshot envelope keys' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF jsonb_typeof(v_payload->'version') IS DISTINCT FROM 'number'
       OR jsonb_typeof(v_context->'version') IS DISTINCT FROM 'number'
       OR jsonb_typeof(v_context->'dropped') IS DISTINCT FROM 'number'
       OR jsonb_typeof(v_context->'source_observations') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'snapshot counters must be JSON numbers' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF scale((v_payload->'version')::numeric)<>0 OR scale((v_context->'version')::numeric)<>0
       OR scale((v_context->'dropped')::numeric)<>0
       OR scale((v_context->'source_observations')::numeric)<>0 THEN
        RAISE EXCEPTION 'snapshot counters must be integers' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF v_payload->'version' IS DISTINCT FROM '1'::jsonb
       OR v_context->'version' IS DISTINCT FROM '1'::jsonb
       OR v_payload->'domain' IS DISTINCT FROM to_jsonb(v_domain)
       OR v_context->'domain' IS DISTINCT FROM to_jsonb(v_observation_domain)
       OR v_context->'upstream_eof' IS DISTINCT FROM 'true'::jsonb
       OR v_context->'validation_mode' IS DISTINCT FROM '"strict"'::jsonb
       OR v_context->'dropped' IS DISTINCT FROM '0'::jsonb
       OR v_payload->'native_input_digest' IS DISTINCT FROM to_jsonb(p_native_digest)
       OR v_context->'artifact_sha256' IS DISTINCT FROM
            to_jsonb(encode(x_extension.digest(p_payload,'sha256'),'hex'))
       OR v_context->'root_run_id' IS DISTINCT FROM to_jsonb(v_run)
       OR v_context->'pins' IS DISTINCT FROM v_payload->'pins' THEN
        RAISE EXCEPTION 'snapshot domain or observation binding mismatch' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF jsonb_typeof(v_payload->'pins') IS DISTINCT FROM 'object'
       OR jsonb_typeof(v_payload->'bundles') IS DISTINCT FROM 'array'
       OR jsonb_typeof(v_context->'validation') IS DISTINCT FROM 'object'
       OR jsonb_typeof(v_context->'geo_stats') NOT IN ('object','null')
       OR jsonb_typeof(v_context->'observation_generation') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'unsupported snapshot envelope shape' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF (SELECT count(*) FROM jsonb_object_keys(v_payload->'pins'))<>9
       OR NOT ((v_payload->'pins') ?& v_pin_keys)
       OR jsonb_array_length(v_payload->'bundles')<>2
       OR v_payload->'bundles'->0 IS DISTINCT FROM '"tuple"'::jsonb THEN
        RAISE EXCEPTION 'unsupported snapshot pins or bundle tag' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    FOREACH v_key IN ARRAY v_pin_keys LOOP
        v_pin:=v_payload->'pins'->v_key;
        IF jsonb_typeof(v_pin) IS DISTINCT FROM 'string' OR pg_column_size(v_pin)>1024 THEN
            RAISE EXCEPTION 'unsupported snapshot pin' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF length(v_pin#>>'{}') NOT BETWEEN 1 AND 128 OR (v_pin#>>'{}')<>btrim(v_pin#>>'{}') THEN
            RAISE EXCEPTION 'noncanonical snapshot pin' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
    END LOOP;
    IF v_payload->'pins'->>'code_revision' !~ '^[0-9a-f]{40}$'
       OR v_payload->'pins'->>'sdk_inventory_sha256' !~ '^[0-9a-f]{64}$'
       OR v_payload->'pins'->>'provider'<>v_dataset.provider
       OR v_payload->'pins'->>'dataset_key'<>v_dataset.dataset_key
       OR v_payload->'pins'->>'source_entity_type'<>v_source_type
       OR v_payload->'pins'->>'native_domain'<>'native-full-refresh-v1' THEN
        RAISE EXCEPTION 'unsupported snapshot provider pins' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF jsonb_typeof(v_payload->'bundles'->1) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'snapshot bundle tuple has no array' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    v_count:=jsonb_array_length(v_payload->'bundles'->1);
    IF v_count NOT BETWEEN 1 AND v_max_count OR v_context->'source_observations' IS DISTINCT FROM to_jsonb(v_count) THEN
        RAISE EXCEPTION 'snapshot source count mismatch' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF v_source_type='rest_area' THEN
        -- 이 검사는 bounded header뿐이다. 전체 DTO/원 clock 권위는 canonical decoder가 재검증한다.
        IF v_payload->'pins'->>'normalizer_revision'<>'transport-rest-area-name-phones-v1'
           OR v_payload->'pins'->>'geo_domain'<>'transport-rest-area-geo-v1'
           OR v_payload->'pins'->>'clock_domain'<>'aware-clock-preserved-v1' THEN
            RAISE EXCEPTION 'unsupported Rest snapshot pins' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        v_export:=v_context->'export_window';
        IF jsonb_typeof(v_export) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Rest export metadata required' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(v_export))<>11
           OR NOT(v_export ?& ARRAY['version','domain','path','limit','item_count','has_more',
               'next_cursor','collection','body_bytes','body_sha256','captured_at']) THEN
            RAISE EXCEPTION 'unexpected Rest export metadata keys' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF jsonb_typeof(v_export->'version') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_export->'limit') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_export->'item_count') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_export->'body_bytes') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_export->'body_sha256') IS DISTINCT FROM 'string'
           OR jsonb_typeof(v_export->'captured_at') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'invalid Rest export metadata types' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF scale((v_export->'version')::numeric)<>0
           OR scale((v_export->'limit')::numeric)<>0
           OR scale((v_export->'item_count')::numeric)<>0
           OR scale((v_export->'body_bytes')::numeric)<>0
           OR v_export->'version' IS DISTINCT FROM '1'::jsonb
           OR v_export->'domain' IS DISTINCT FROM '"transport-rest-current-export-window-v1"'::jsonb
           OR v_export->'path' IS DISTINCT FROM '"/v1/service/exports/rest-areas"'::jsonb
           OR v_export->'limit' IS DISTINCT FROM '256'::jsonb
           OR v_export->'item_count' IS DISTINCT FROM to_jsonb(v_count)
           OR v_export->'has_more' IS DISTINCT FROM 'false'::jsonb
           OR v_export->'next_cursor' IS DISTINCT FROM 'null'::jsonb
           OR (v_export->'body_bytes')::numeric NOT BETWEEN 1 AND 2097152
           OR v_export->>'body_sha256' !~ '^[0-9a-f]{64}$'
           OR octet_length(v_export->>'captured_at') NOT BETWEEN 20 AND 64
           OR v_export->>'captured_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
            RAISE EXCEPTION 'incomplete Rest export window' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        v_collection:=v_export->'collection';
        IF jsonb_typeof(v_collection) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Rest collection metadata required' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(v_collection))<>4
           OR NOT(v_collection ?& ARRAY['source','last_success_at','failed','stale'])
           OR v_collection->'source' IS DISTINCT FROM '"krex_rest_area"'::jsonb
           OR v_collection->'failed' IS DISTINCT FROM 'false'::jsonb
           OR v_collection->'stale' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_typeof(v_collection->'last_success_at') IS DISTINCT FROM 'string'
           OR octet_length(v_collection->>'last_success_at') NOT BETWEEN 20 AND 64
           OR v_collection->>'last_success_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
            RAISE EXCEPTION 'unsupported Rest current collection' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        -- 원문 bytes는 context SHA와 함께 immutable 보존한다. 현재/새 시각을 만들지 않는다.
        PERFORM (v_export->>'captured_at')::timestamptz;
        PERFORM (v_collection->>'last_success_at')::timestamptz;
    END IF;
    -- text 변환은 작은 context 내부 string에만 한다. 의미 복원은 후속 context codec의 책임이다.
    IF pg_column_size(v_context->'observation_generation')>1024 THEN
        RAISE EXCEPTION 'observation generation exceeds its bound' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    v_generation:=v_context->>'observation_generation';
    IF octet_length(v_generation) NOT BETWEEN 1 AND 160 THEN
        RAISE EXCEPTION 'invalid observation generation' USING ERRCODE='23514',
            CONSTRAINT='ck_provider_snapshot_registration_domain';
    END IF;
    IF v_generation<>v_run THEN
        IF left(v_generation,length(v_run)+8)<>v_run||'::retry:' THEN
            RAISE EXCEPTION 'observation generation belongs to another run' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        v_suffix:=substr(v_generation,length(v_run)+9);
        IF v_suffix !~ '^[1-9][0-9]{0,18}$' THEN
            RAISE EXCEPTION 'invalid observation retry suffix' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
        IF v_suffix::numeric>9223372036854775807 THEN
            RAISE EXCEPTION 'observation retry suffix overflow' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_registration_domain';
        END IF;
    END IF;

    -- 동일 member의 중복은 새 quota 접근/lease 갱신/기존 nonce 노출 없이 반환한다.
    SELECT artifact.snapshot_id,artifact.root_job_id,artifact.source_job_id,
           artifact.provider_dataset_id,artifact.sync_scope,artifact.operation_key,
           artifact.dagster_run_id,artifact.capture_profile,artifact.native_input_digest,
           artifact.artifact_payload,artifact.observation_context
      INTO v_existing FROM ops.provider_snapshot_artifacts artifact
      WHERE artifact.import_job_dataset_id=p_member;
    IF FOUND THEN
        IF v_existing.root_job_id IS DISTINCT FROM p_root OR v_existing.source_job_id IS DISTINCT FROM p_source_job
           OR v_existing.provider_dataset_id IS DISTINCT FROM v_member.provider_dataset_id
           OR v_existing.sync_scope IS DISTINCT FROM v_member.sync_scope
           OR v_existing.operation_key IS DISTINCT FROM v_member.operation_key
           OR v_existing.dagster_run_id IS DISTINCT FROM v_run
           OR v_existing.capture_profile IS DISTINCT FROM 'bounded-place-v1'
           OR v_existing.native_input_digest IS DISTINCT FROM p_native_digest
           OR v_existing.artifact_payload IS DISTINCT FROM p_payload
           OR v_existing.observation_context IS DISTINCT FROM p_context THEN
            RAISE EXCEPTION 'registered member input is immutable' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_immutable_input';
        END IF;
        IF NOT EXISTS(SELECT 1 FROM ops.provider_snapshot_controls control WHERE control.snapshot_id=v_existing.snapshot_id) THEN
            RAISE EXCEPTION 'snapshot control is missing' USING ERRCODE='23514',
                CONSTRAINT='ck_provider_snapshot_apply_required';
        END IF;
        RETURN QUERY SELECT v_existing.snapshot_id,false,NULL::bigint,NULL::uuid;
        RETURN;
    END IF;
    -- 최초 INSERT의 FK도 tuple KEY SHARE를 잡는다. canonical root→child→member를 선취득한다.
    -- duplicate/claim/renew/apply의 tracking tuple 잠금0과 이 초기 등록 예외를 혼동하지 않는다.
    PERFORM 1 FROM ops.import_jobs WHERE job_id=p_root FOR KEY SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'snapshot root disappeared' USING ERRCODE='40001'; END IF;
    PERFORM 1 FROM ops.import_jobs WHERE job_id=p_source_job FOR KEY SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'snapshot child disappeared' USING ERRCODE='40001'; END IF;
    PERFORM 1 FROM ops.import_job_datasets WHERE import_job_dataset_id=p_member AND job_id=p_source_job FOR KEY SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'snapshot member disappeared' USING ERRCODE='40001'; END IF;
    v_bytes:=octet_length(p_payload)::bigint+octet_length(p_context)::bigint+8192;
    FOREACH v_quota IN ARRAY ARRAY[0::bigint,v_member.provider_dataset_id] LOOP
        SELECT * INTO v_limit FROM ops.provider_snapshot_quota_limits quota
            WHERE quota.quota_key=v_quota FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'snapshot quota is not configured' USING ERRCODE='53000',
                CONSTRAINT='ck_provider_snapshot_quota_available';
        END IF;
        IF v_limit.used_rows>=v_limit.max_rows OR v_bytes>v_limit.max_bytes-v_limit.used_bytes THEN
            RAISE EXCEPTION 'snapshot quota is exhausted' USING ERRCODE='53000',
                CONSTRAINT='ck_provider_snapshot_quota_available';
        END IF;
    END LOOP;
    v_snapshot:=x_extension.gen_random_uuid();
    v_fence:=x_extension.gen_random_uuid();
    v_now:=clock_timestamp();
    INSERT INTO ops.provider_snapshot_artifacts(snapshot_id,root_job_id,source_job_id,
        import_job_dataset_id,provider_dataset_id,sync_scope,operation_key,dagster_run_id,
        capture_profile,artifact_payload,native_input_digest,observation_context)
    VALUES(v_snapshot,p_root,p_source_job,p_member,v_member.provider_dataset_id,
        v_member.sync_scope,v_member.operation_key,v_run,'bounded-place-v1',p_payload,p_native_digest,p_context);
    INSERT INTO ops.provider_snapshot_controls(snapshot_id,executor_generation,executor_fence,lease_expires_at,status)
    VALUES(v_snapshot,1,v_fence,v_now+make_interval(secs=>p_lease_seconds),'prepared');
    INSERT INTO ops.provider_snapshot_quota_reservations(snapshot_id,provider_dataset_id,reserved_bytes)
        VALUES(v_snapshot,v_member.provider_dataset_id,v_bytes);
    UPDATE ops.provider_snapshot_quota_limits quota SET used_rows=used_rows+1,used_bytes=used_bytes+v_bytes
        WHERE quota.quota_key=ANY(ARRAY[0::bigint,v_member.provider_dataset_id]);
    RETURN QUERY SELECT v_snapshot,true,1::bigint,v_fence;
END;
$$;
