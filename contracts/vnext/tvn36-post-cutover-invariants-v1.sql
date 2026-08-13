-- tvn36-post-cutover-invariants-v1.sql — T-VN-36D final destructive fence
--
-- 이 artifact는 0104 적용 직후의 실제 DB 정본만 검사한다. T-VN-36A--C가
-- field registry/base ledger/override history로 입력을 소진한 뒤에는 whole-row
-- freeze와 request/version bridge가 어떤 runtime 경로에도 남아서는 안 된다.

-- [INV-36-01] whole-row bridge relation은 물리적으로 존재하지 않는다.
SELECT count(*)
FROM (VALUES
    ('feature.feature_versions'),
    ('ops.feature_change_requests')
) AS removed_relation(qualified_name)
WHERE to_regclass(removed_relation.qualified_name) IS NOT NULL; -- expect: 0 -- phase: post-tvn36

-- [INV-36-02] Feature와 override에 legacy provenance/request surrogate가 없다.
SELECT count(*)
FROM information_schema.columns AS column_info
WHERE (column_info.table_schema, column_info.table_name, column_info.column_name) IN (
    ('feature', 'features', 'data_origin'),
    ('feature', 'features', 'data_version'),
    ('ops', 'feature_overrides', 'request_id')
); -- expect: 0 -- phase: post-tvn36

-- [INV-36-03] bridge materializer/replay와 request UUID procedure overload는 제거한다.
SELECT count(*)
FROM (VALUES
    ('feature.replay_legacy_whole_row_freezes(boolean)'),
    ('feature.materialize_user_feature_change_provenance(text,text,uuid,text,text,bigint)'),
    ('feature.materialize_provider_feature_version(text)'),
    ('feature.author_feature_field_overrides(text,bigint,text,text,bigint,uuid,jsonb,jsonb)'),
    ('feature.revoke_feature_field_overrides(text,bigint,text,text,bigint,uuid,text[])')
) AS removed_procedure(regprocedure_name)
WHERE to_regprocedure(removed_procedure.regprocedure_name) IS NOT NULL; -- expect: 0 -- phase: post-tvn36

-- [INV-36-04] runtime command surface는 request-free typed override procedures다.
SELECT count(*)
FROM (VALUES
    ('feature.author_feature_field_overrides(text,bigint,text,text,bigint,jsonb,jsonb)'),
    ('feature.revoke_feature_field_overrides(text,bigint,text,text,bigint,text[])')
) AS required_procedure(regprocedure_name)
WHERE to_regprocedure(required_procedure.regprocedure_name) IS NULL; -- expect: 0 -- phase: post-tvn36

-- [INV-36-05] final writer DDL은 제거 대상 bridge identifier를 참조하지 않는다.
SELECT count(*)
FROM pg_catalog.pg_proc AS routine
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
WHERE namespace.nspname = 'feature'
  AND routine.proname IN (
      'create_feature_with_initial_state',
      'author_feature_field_overrides',
      'revoke_feature_field_overrides'
  )
  AND pg_catalog.pg_get_functiondef(routine.oid) ~
      '(data_origin|data_version|feature_versions|feature_change_requests|p_request_id|request_id)'; -- expect: 0 -- phase: post-tvn36

-- [INV-36-06] active overrides와 provider base ledger는 final effective projection의 유일한
-- field provenance relation이다.
SELECT count(*)
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE (namespace.nspname, relation.relname) IN (
    ('feature', 'feature_base_field_values'),
    ('ops', 'feature_overrides'),
    ('ops', 'feature_override_field_paths')
)
  AND relation.relkind NOT IN ('r', 'p'); -- expect: 0 -- phase: post-tvn36
