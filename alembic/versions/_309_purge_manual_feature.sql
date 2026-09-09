DROP PROCEDURE feature.purge_manual_feature(uuid, text, boolean, text, bigint);

CREATE PROCEDURE feature.purge_manual_feature(IN p_feature_id uuid, IN p_reason_code text, IN p_release_identity boolean, IN p_actor text, IN p_command_id bigint, OUT o_purge_id uuid, OUT o_outcome text, OUT o_captured_relation_count integer, OUT o_captured_row_count integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $$
DECLARE
    v_claim feature.manual_feature_identity_claims%ROWTYPE;
    v_legacy_feature_id text;
    v_command ops.domain_commands%ROWTYPE;
    v_blockers text;
    v_relation text;
    v_predicate text;
    v_rows jsonb;
    v_captured jsonb := '{}'::jsonb;
    v_relation_count integer := 0;
    v_row_count integer := 0;
    v_existing feature.manual_feature_purge_records%ROWTYPE;
BEGIN
    IF p_feature_id IS NULL
       OR p_reason_code NOT IN ('mistaken_creation', 'erasure_required')
       OR p_release_identity IS NULL
       OR coalesce(btrim(p_actor), '') = ''
       OR p_command_id IS NULL THEN
        RAISE EXCEPTION 'manual Feature purge has invalid arguments'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    SELECT * INTO v_command
    FROM ops.domain_commands AS command
    WHERE command.command_id = p_command_id
    FOR SHARE;
    IF NOT FOUND
       OR v_command.actor <> p_actor
       OR v_command.operation <> 'admin.manual-feature.purge.v1'
       OR EXISTS (
           SELECT 1 FROM ops.domain_command_results AS result
           WHERE result.command_id = p_command_id
       ) THEN
        RAISE EXCEPTION 'manual Feature purge command is not open'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_command';
    END IF;

    SELECT * INTO v_claim
    FROM feature.manual_feature_identity_claims AS claim
    WHERE claim.feature_id = p_feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target has no manual identity claim'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    IF v_claim.purged_by_command_id IS NOT NULL THEN
        SELECT * INTO v_existing
        FROM feature.manual_feature_purge_records AS record
        WHERE record.feature_id = p_feature_id;
        o_purge_id := v_existing.purge_id;
        o_outcome := 'already_purged';
        o_captured_relation_count := v_existing.captured_relation_count;
        o_captured_row_count := v_existing.captured_row_count;
        RETURN;
    END IF;

    PERFORM 1
    FROM feature.features AS feature
    WHERE feature.feature_id = p_feature_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'purge target Feature does not exist'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_manual';
    END IF;

    -- T-VN-39 뒤 legacy `f_*` 문자열은 `feature.features`에 남아 있지 않다. 유일한
    -- 잔존처인 alias map에서 읽어 purge 증거의 `legacy_feature_id`에 남긴다.
    --
    -- **계약 선결조건**: `feature.manual_feature_purge_records.legacy_feature_id`는
    -- nullable이어야 한다. legacy alias 발급이 멎은 뒤 태어난 Feature에는 legacy id가
    -- 애초에 없고 그것은 결손이 아니라 참이다. 개명하며 NOT NULL을 함께 끌고 오면
    -- 그런 Feature의 purge가 evidence INSERT에서 23502로 죽고,
    -- `manual_feature_purge_repo._raise_purge_error`는 `{23514, 42501}` 밖 sqlstate를
    -- 그대로 re-raise하므로 catch-all 500이 된다.
    --
    -- `alias <> p_feature_id::text`는 `feature.ensure_features_legacy_alias`가 재키
    -- 뒤에도 살아남아 `alias = <uuid 문자열>` 행을 새로 심는 경우를 배제한다 — uuid를
    -- `legacy_feature_id`로 적재하면 append-only 증거가 영구히 오염된다. 캐스트는
    -- 파라미터에 붙으므로 `idx_feature_aliases_feature` 탐색은 그대로다.
    --
    -- `ck_feature_aliases_legacy_identity`(alias = feature_id)는 text=uuid가 되어
    -- 재키와 함께 사라진다. 그러면 한 Feature에 legacy alias가 둘 이상일 수 있고
    -- `SELECT ... INTO`는 다중 행에서 에러 없이 임의의 한 행을 고르므로 순서를 못 박는다.
    SELECT legacy.alias INTO v_legacy_feature_id
    FROM feature.feature_aliases AS legacy
    WHERE legacy.feature_id = p_feature_id
      AND legacy.alias_kind = 'legacy_feature_id'
      AND legacy.alias <> p_feature_id::text
    ORDER BY legacy.alias
    LIMIT 1;

    SELECT string_agg(blocked.relation_name || '=' || blocked.tally::text, ', '
                      ORDER BY blocked.relation_name)
    INTO v_blockers
    FROM (
        SELECT feature.qualified_relation_name(constraint_row.conrelid) AS relation_name,
               count(*) AS tally
        FROM pg_catalog.pg_constraint AS constraint_row
        CROSS JOIN LATERAL (
            SELECT format(
                'SELECT count(*) FROM %s AS child WHERE (%s) IN'
                ' (SELECT %s FROM feature.features WHERE feature_id = %L)',
                feature.qualified_relation_name(constraint_row.conrelid),
                (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = position.attnum),
                (SELECT string_agg(format('%I', attribute.attname), ', '
                                   ORDER BY position.ordinality)
                 FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_row.confrelid
                  AND attribute.attnum = position.attnum),
                p_feature_id
            ) AS statement
        ) AS built
        CROSS JOIN LATERAL feature.count_rows_dynamic(built.statement) AS counted(tally)
        WHERE constraint_row.confrelid = 'feature.features'::regclass
          AND constraint_row.contype = 'f'
          -- **`'a'`(NO ACTION)도 막는다.** 지연되지 않은 FK에서 NO ACTION은 RESTRICT와
          -- 똑같이 삭제를 거부한다. `'r'`만 보면 그런 참조자가 probe를 통과한 뒤
          -- DELETE에서 raw 23503으로 죽고, 그러면 "이름을 대는 거부"라는 이 설계의
          -- 요지가 그 경로에서만 조용히 무효가 된다.
          --
          -- 지금 그런 FK는 정확히 하나다 — `ops.feature_requests.resolved_feature_id`.
          -- 그리고 그것은 **M04 승인으로 태어난 manual Feature 전부**에 달린다
          -- (`approve_feature_request_with_initial_state`가 claim을 심고 같은
          -- 트랜잭션에서 `resolved_feature_id`를 세운다). 즉 드문 경로가 아니다.
          AND constraint_row.confdeltype IN ('r', 'a')
          AND counted.tally > 0
        GROUP BY constraint_row.conrelid
    ) AS blocked;

    IF v_blockers IS NOT NULL THEN
        RAISE EXCEPTION 'purge target is bound by immutable evidence: %', v_blockers
            USING ERRCODE = '23514',
                CONSTRAINT = 'ck_manual_feature_purge_evidence_bound';
    END IF;

    IF p_reason_code = 'mistaken_creation' THEN
        FOR v_relation, v_predicate IN
            SELECT feature.qualified_relation_name(constraint_row.conrelid),
                   string_agg(
                       format(
                           '(%s) IN (SELECT %s FROM feature.features WHERE feature_id = %L)',
                           (SELECT string_agg(format('child.%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.conkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.conrelid
                             AND attribute.attnum = position.attnum),
                           (SELECT string_agg(format('%I', attribute.attname), ', '
                                              ORDER BY position.ordinality)
                            FROM unnest(constraint_row.confkey) WITH ORDINALITY AS position(attnum, ordinality)
                            JOIN pg_catalog.pg_attribute AS attribute
                              ON attribute.attrelid = constraint_row.confrelid
                             AND attribute.attnum = position.attnum),
                           p_feature_id
                       ),
                       ' OR '
                   )
            FROM pg_catalog.pg_constraint AS constraint_row
            WHERE constraint_row.confrelid = 'feature.features'::regclass
              AND constraint_row.contype = 'f'
              -- **`'n'`(SET NULL)도 담는다.** cascade는 행을 지우고 SET NULL은 행을
              -- 고치지만, 복구점의 관점에서는 둘 다 "이 삭제가 되돌릴 수 없게 바꾸는
              -- 것"이다. 담지 않으면 어느 행의 어느 컬럼이 NULL이 됐는지 알 수 없다.
              AND constraint_row.confdeltype IN ('c', 'n')
            GROUP BY constraint_row.conrelid
            ORDER BY feature.qualified_relation_name(constraint_row.conrelid)
        LOOP
            EXECUTE format(
                'SELECT coalesce(jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text), ''[]''::jsonb)'
                ' FROM %s AS child WHERE %s',
                v_relation, v_predicate
            ) INTO v_rows;
            IF jsonb_array_length(v_rows) > 0 THEN
                v_captured := v_captured || jsonb_build_object(v_relation, v_rows);
                v_relation_count := v_relation_count + 1;
                v_row_count := v_row_count + jsonb_array_length(v_rows);
            END IF;
        END LOOP;
        v_captured := v_captured || jsonb_build_object(
            'feature.features',
            (SELECT jsonb_build_array(to_jsonb(feature))
             FROM feature.features AS feature
             WHERE feature.feature_id = p_feature_id)
        );
        v_relation_count := v_relation_count + 1;
        v_row_count := v_row_count + 1;
    END IF;

    UPDATE feature.manual_feature_identity_claims
    SET purged_by_command_id = p_command_id,
        purged_at = clock_timestamp(),
        identity_released = p_release_identity
    WHERE feature_id = p_feature_id;

    INSERT INTO feature.manual_feature_purge_records (
        feature_id, legacy_feature_id, reason_code, identity_released,
        purged_by_command_id, purged_by_actor, captured_rows,
        captured_relation_count, captured_row_count, captured_sha256
    ) VALUES (
        p_feature_id, v_legacy_feature_id, p_reason_code, p_release_identity,
        p_command_id, p_actor,
        CASE WHEN p_reason_code = 'mistaken_creation' THEN v_captured ELSE NULL END,
        v_relation_count, v_row_count,
        encode(
            x_extension.digest(
                convert_to(
                    CASE WHEN p_reason_code = 'mistaken_creation'
                         THEN v_captured::text
                         ELSE p_feature_id::text
                    END,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    ) RETURNING purge_id INTO o_purge_id;

    DELETE FROM feature.features WHERE feature_id = p_feature_id;

    o_outcome := 'purged';
    o_captured_relation_count := v_relation_count;
    o_captured_row_count := v_row_count;
END
$$;

DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_feature_schema_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_schema_owner';
    END IF;
    EXECUTE 'ALTER PROCEDURE feature.purge_manual_feature(IN p_feature_id uuid, IN p_reason_code text, IN p_release_identity boolean, IN p_actor text, IN p_command_id bigint, OUT o_purge_id uuid, OUT o_outcome text, OUT o_captured_relation_count integer, OUT o_captured_row_count integer) OWNER TO ktm_feature_schema_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_schema_owner';
    END IF;
END
$t39_owner$;

REVOKE ALL ON PROCEDURE feature.purge_manual_feature(uuid, text, boolean, text, bigint) FROM PUBLIC;
