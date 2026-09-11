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

DROP PROCEDURE feature.record_manual_provider_dedup_candidate(IN p_manual_feature_id text, IN p_provider_feature_id text, IN p_scores jsonb, IN p_detector_causation jsonb, OUT o_case_id uuid, OUT o_outcome text);

CREATE PROCEDURE feature.record_manual_provider_dedup_candidate(IN p_manual_feature_id uuid, IN p_provider_feature_id uuid, IN p_scores jsonb, IN p_detector_causation jsonb, OUT o_case_id uuid, OUT o_outcome text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $_$
DECLARE
    v_manual feature.features%ROWTYPE;
    v_provider feature.features%ROWTYPE;
    v_origin feature.feature_creation_origins%ROWTYPE;
    v_source record;
    v_manual_snapshot jsonb;
    v_provider_snapshot jsonb;
    v_input jsonb;
    v_fingerprint text;
    v_name_score numeric;
    v_spatial_score numeric;
    v_category_score numeric;
    v_total_score numeric;
    v_distance_meters numeric;
    v_scorer_input_sha256 text;
    v_primary_source_count integer;
    v_prior_case_id uuid;
    v_decision_fingerprint text;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires READ COMMITTED'
            USING ERRCODE = '25001', CONSTRAINT = 'ck_m05_detector_isolation';
    END IF;
    IF session_user <> 'ktm_feature_dagster_runtime'
       OR NOT pg_has_role(session_user, 'ktm_manual_provider_dedup_detector_executor', 'member')
       OR pg_has_role(session_user, 'ktm_manual_provider_dedup_admin_executor', 'member')
       OR pg_has_role(session_user, 'ktm_feature_reference_reconciliation_service_executor', 'member') THEN
        RAISE EXCEPTION 'manual/provider dedup detector requires the Dagster-only executor'
            USING ERRCODE = '42501', CONSTRAINT = 'ck_m05_detector_executor';
    END IF;
    IF p_manual_feature_id IS NULL
       OR p_provider_feature_id IS NULL
       OR p_manual_feature_id = p_provider_feature_id
       OR jsonb_typeof(p_scores) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_detector_causation) IS DISTINCT FROM 'object'
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_scores) AS key_name(key_name)
           WHERE key_name NOT IN (
               'name_score', 'spatial_score', 'category_score', 'total_score',
               'distance_meters', 'scorer_input_sha256'
           )
       )
       OR jsonb_typeof(p_scores -> 'name_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'spatial_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'category_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'total_score') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'distance_meters') IS DISTINCT FROM 'number'
       OR jsonb_typeof(p_scores -> 'scorer_input_sha256') IS DISTINCT FROM 'string'
       OR p_scores ->> 'scorer_input_sha256' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'manual/provider dedup candidate input is not canonical'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END IF;
    BEGIN
        v_name_score := (p_scores ->> 'name_score')::numeric;
        v_spatial_score := (p_scores ->> 'spatial_score')::numeric;
        v_category_score := (p_scores ->> 'category_score')::numeric;
        v_total_score := (p_scores ->> 'total_score')::numeric;
        v_distance_meters := (p_scores ->> 'distance_meters')::numeric;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'manual/provider dedup score is invalid'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END;
    IF v_name_score NOT BETWEEN 0 AND 1 OR v_spatial_score NOT BETWEEN 0 AND 1
       OR v_category_score NOT BETWEEN 0 AND 1 OR v_total_score NOT BETWEEN 0 AND 1
       OR v_distance_meters < 0 THEN
        RAISE EXCEPTION 'manual/provider dedup score is outside its canonical range'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_input';
    END IF;
    v_scorer_input_sha256 := p_scores ->> 'scorer_input_sha256';

    -- event publication·decision과 같은 global fence가 case episode도 직렬화한다.
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-m05', 0));
    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_id IN (p_manual_feature_id, p_provider_feature_id)
    ORDER BY locked.feature_id
    FOR UPDATE;
    SELECT * INTO v_manual
    FROM feature.features WHERE feature_id = p_manual_feature_id FOR UPDATE;
    SELECT * INTO v_provider
    FROM feature.features WHERE feature_id = p_provider_feature_id FOR UPDATE;
    IF NOT FOUND
       OR v_manual.lifecycle_state <> 'active' OR v_manual.publication_state <> 'published'
       OR v_manual.quality_state <> 'valid' OR v_provider.lifecycle_state <> 'active'
       OR v_provider.publication_state <> 'published' OR v_provider.quality_state <> 'valid'
       OR v_manual.coord IS NULL OR v_provider.coord IS NULL THEN
        RAISE EXCEPTION 'manual/provider candidate Feature proof is not eligible'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_feature_proof';
    END IF;
    SELECT * INTO v_origin
    FROM feature.feature_creation_origins AS origin
    WHERE origin.feature_id = v_manual.feature_id
      AND origin.origin_kind IN ('manual_admin', 'manual_curation', 'manual_request');
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = v_manual.feature_id
          AND claim.claimed_by_command_id = v_origin.creation_command_id
    ) THEN
        RAISE EXCEPTION 'manual Feature lacks immutable creation evidence'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_manual_origin';
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
        RAISE EXCEPTION 'provider Feature lacks one current primary source proof'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_provider_source';
    END IF;
    SELECT
        link.source_entity_key,
        head.current_source_record_key AS source_record_key,
        head.observed_at AS source_head_observed_at,
        source.raw_payload_hash AS source_record_raw_payload_hash,
        entity.provider_dataset_id
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
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provider Feature lacks one current primary source proof'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_m05_candidate_provider_source';
    END IF;

    v_manual_snapshot := jsonb_build_object(
        'feature_id', v_manual.feature_id,
        'feature_uuid', CAST(v_manual.feature_id AS text),
        'row_revision', v_manual.row_revision,
        'kind', v_manual.kind,
        'name', v_manual.name,
        'category', v_manual.category,
        'lon', ST_X(v_manual.coord),
        'lat', ST_Y(v_manual.coord)
    );
    v_provider_snapshot := jsonb_build_object(
        'feature_id', v_provider.feature_id,
        'feature_uuid', CAST(v_provider.feature_id AS text),
        'row_revision', v_provider.row_revision,
        'kind', v_provider.kind,
        'name', v_provider.name,
        'category', v_provider.category,
        'lon', ST_X(v_provider.coord),
        'lat', ST_Y(v_provider.coord)
    );
    v_input := jsonb_build_object(
        'manual', v_manual_snapshot,
        'manual_creation_command_id', v_origin.creation_command_id,
        'provider', v_provider_snapshot,
        'provider_dataset_id', v_source.provider_dataset_id,
        'source_entity_key', v_source.source_entity_key,
        'source_record_key', v_source.source_record_key,
        'source_record_raw_payload_hash', v_source.source_record_raw_payload_hash,
        'source_head_observed_at', v_source.source_head_observed_at,
        'scorer_id', 'manual-provider-v1',
        'scores', p_scores
    );
    v_fingerprint := encode(
        x_extension.digest(convert_to(v_input::text, 'UTF8'), 'sha256'), 'hex'
    );
    -- **재심 차단.** 멱등성(`evidence_fingerprint`)은 미해결 case에만 성립하므로
    -- admin이 판정한 쌍은 지문이 같아도 새 case가 됐다 — 주기 실행에서 admin 큐가
    -- 쳇바퀴가 되는 원인이다(T-VN-M05-RELITIGATION R1).
    --
    -- 차단 키는 `evidence_fingerprint`가 **아니다.** 그 지문은 두 Feature의
    -- `row_revision`과 source head 관측 시각을 포함하므로, score와 무관한 필드 patch
    -- 하나에도 달라져 차단이 무력해진다(R3). 대신 판정을 실제로 좌우하는 것만 넣는다:
    -- 두 snapshot에서 `row_revision`을 뺀 것(= kind·name·category·lon·lat와 식별자),
    -- provider의 **현재 source 내용**(`raw_payload_hash`), 그리고 `scorer_id`.
    --
    -- 넣지 않는 것과 이유: `source_head_observed_at`은 내용이 그대로인데 head만
    -- 갱신되는 경로가 실재한다. `source_record_key`도 넣지 않는다 — 같은 내용을
    -- 다시 fetch하면 record key만 바뀌므로, 넣으면 그때마다 차단이 풀린다(변이
    -- 검증이 이것을 드러냈다). 점수 **값**도 넣지 않는다 — 부동소수 잡음이 차단을
    -- 흔들면 안 된다. scorer가 바뀌면 `scorer_id`가 바뀌어 다시 올라온다.
    --
    -- 반대 방향은 R2가 진다: score-facing 값이나 provider source 내용이 바뀌면 이
    -- 지문이 달라져 새 후보가 된다. 두 방향 모두 게이트가 있어야 한다.
    v_decision_fingerprint := encode(
        x_extension.digest(
            convert_to(
                jsonb_build_object(
                    'manual', v_manual_snapshot - 'row_revision',
                    'provider', v_provider_snapshot - 'row_revision',
                    'source_record_raw_payload_hash',
                        v_source.source_record_raw_payload_hash,
                    'scorer_id', 'manual-provider-v1'
                )::text,
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
    SELECT candidate.case_id INTO o_case_id
    FROM ops.manual_provider_dedup_cases AS candidate
    JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    WHERE candidate.manual_feature_id = v_manual.feature_id
      AND candidate.provider_feature_id = v_provider.feature_id
      AND candidate.decision_fingerprint = v_decision_fingerprint
      -- `superseded`는 탐지기가 만든 것이라 admin 판정이 아니다. 그것으로 차단하면
      -- 탐지기가 자기 자신을 영구히 침묵시킨다.
      AND resolution.decision IN ('kept', 'merged', 'manual_retired')
    ORDER BY resolution.resolved_at DESC
    LIMIT 1;
    IF FOUND THEN
        o_outcome := 'suppressed';
        RETURN;
    END IF;

    SELECT candidate.case_id INTO o_case_id
    FROM ops.manual_provider_dedup_cases AS candidate
    LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
      ON resolution.case_id = candidate.case_id
    WHERE candidate.evidence_fingerprint = v_fingerprint
      AND resolution.case_id IS NULL
    FOR SHARE OF candidate;
    IF FOUND THEN
        o_outcome := 'idempotent';
        RETURN;
    END IF;
    INSERT INTO ops.manual_provider_dedup_cases (
        manual_feature_id, manual_creation_command_id,
        manual_feature_row_revision, provider_feature_id,
        provider_feature_row_revision, provider_dataset_id, source_entity_key,
        source_record_key, source_record_raw_payload_hash, source_head_observed_at,
        manual_feature_snapshot, provider_feature_snapshot, scorer_id,
        scorer_input_sha256, name_score, spatial_score, category_score, total_score,
        distance_meters, evidence_fingerprint, decision_fingerprint, detector_causation
    ) VALUES (
        v_manual.feature_id, v_origin.creation_command_id,
        v_manual.row_revision, v_provider.feature_id,
        v_provider.row_revision, v_source.provider_dataset_id, v_source.source_entity_key,
        v_source.source_record_key, v_source.source_record_raw_payload_hash,
        v_source.source_head_observed_at, v_manual_snapshot, v_provider_snapshot,
        'manual-provider-v1', v_scorer_input_sha256, v_name_score, v_spatial_score,
        v_category_score, v_total_score, v_distance_meters, v_fingerprint,
        v_decision_fingerprint, p_detector_causation
    ) RETURNING case_id INTO o_case_id;
    FOR v_prior_case_id IN
        SELECT candidate.case_id
        FROM ops.manual_provider_dedup_cases AS candidate
        LEFT JOIN ops.manual_provider_dedup_resolutions AS resolution
          ON resolution.case_id = candidate.case_id
        WHERE candidate.manual_feature_id = v_manual.feature_id
          AND candidate.provider_feature_id = v_provider.feature_id
          AND candidate.case_id <> o_case_id
          AND resolution.case_id IS NULL
        FOR UPDATE OF candidate
    LOOP
        INSERT INTO ops.manual_provider_dedup_resolutions (
            case_id, decision, superseded_by_case_id, detector_causation
        ) VALUES (
            v_prior_case_id, 'superseded', o_case_id, p_detector_causation
        );
    END LOOP;
    o_outcome := 'created';
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
    EXECUTE 'ALTER PROCEDURE feature.record_manual_provider_dedup_candidate(IN p_manual_feature_id uuid, IN p_provider_feature_id uuid, IN p_scores jsonb, IN p_detector_causation jsonb, OUT o_case_id uuid, OUT o_outcome text) OWNER TO ktm_manual_provider_dedup_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_manual_provider_dedup_procedure_owner';
    END IF;
END
$t39_owner$;

REVOKE ALL ON PROCEDURE feature.record_manual_provider_dedup_candidate(IN p_manual_feature_id uuid, IN p_provider_feature_id uuid, IN p_scores jsonb, IN p_detector_causation jsonb, OUT o_case_id uuid, OUT o_outcome text) FROM PUBLIC;
GRANT ALL ON PROCEDURE feature.record_manual_provider_dedup_candidate(IN p_manual_feature_id uuid, IN p_provider_feature_id uuid, IN p_scores jsonb, IN p_detector_causation jsonb, OUT o_case_id uuid, OUT o_outcome text) TO ktm_manual_provider_dedup_detector_executor;

SET ROLE ktm_feature_schema_owner;
