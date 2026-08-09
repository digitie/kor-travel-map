-- =============================================================================
-- tvn34c-post-cutover-invariants-v1.sql — T-VN-34C / T-VN-36 경계 contract
-- =============================================================================
-- 이 파일은 0096에서 T-VN-34C final migration까지 적용한 직후에 실행한다.
-- `target-schema-v1.sql`은 T-VN-36C/T-VN-39 이후 UUID final state이므로 이 중간
-- schema를 그 파일과 비교하지 않는다. 각 assertion은 count(*)=0이어야 하며 trailer는
-- target invariant와 같은 `-- expect: 0 -- phase: post-cutover` 형식이다.
-- =============================================================================

-- [INV-34C-01] C가 fence하는 Feature core legacy state/provenance 열은 없다.
SELECT count(*)
FROM information_schema.columns
WHERE table_schema = 'feature'
  AND table_name = 'features'
  AND column_name = ANY (ARRAY[
      'status', 'deleted_at', 'user_deleted_at', 'user_deleted_by',
      'user_change_kind', 'user_change_status', 'user_change_request_id',
      'user_change_reason'
  ]); -- expect: 0 -- phase: post-cutover

-- [INV-34C-02] T-VN-36 입력인 data origin/version은 아직 남는다.
SELECT 2 - count(*)
FROM information_schema.columns
WHERE table_schema = 'feature'
  AND table_name = 'features'
  AND column_name = ANY (ARRAY['data_origin', 'data_version']); -- expect: 0 -- phase: post-cutover

-- [INV-34C-03] transitional private detail bridge는 물리적으로 사라지고 public view만 남는다.
SELECT count(*)
FROM (VALUES
    (to_regclass('feature.features_detailed') IS NOT NULL),
    (to_regclass('feature.public_features') IS NULL)
) AS violations(is_violation)
WHERE is_violation; -- expect: 0 -- phase: post-cutover

-- [INV-34C-04] public payload의 ordered allowlist는 contract와 정확히 같다. denylist만
-- 확인하면 새 internal 열이 public API로 누출될 수 있으므로 순서까지 고정한다.
SELECT count(*)
FROM (
    SELECT array_agg(attribute.attname ORDER BY attribute.attnum) AS actual_columns
    FROM pg_attribute AS attribute
    WHERE attribute.attrelid = 'feature.public_features'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
) AS actual
WHERE actual.actual_columns IS DISTINCT FROM ARRAY[
    'feature_id', 'feature_uuid', 'kind', 'name', 'category',
    'coord', 'coord_5179', 'coord_precision_digits', 'address',
    'legal_dong_code', 'road_name_code', 'road_address_management_no',
    'admin_dong_code', 'sido_code', 'sigungu_code', 'urls',
    'marker_icon', 'marker_color', 'parent_feature_id', 'sibling_group_id',
    'raw_refs', 'created_at', 'updated_at', 'row_revision', 'geom', 'detail'
]::text[]; -- expect: 0 -- phase: post-cutover

-- [INV-34C-05] public projection은 detail bridge가 아닌 typed core+모든 subtype을 직접
-- 참조한다. direct relation dependency가 하나라도 빠지면 assembly contract 위반이다.
SELECT count(*)
FROM (VALUES
    ('feature.features'),
    ('feature.feature_points'),
    ('feature.feature_events'),
    ('feature.feature_notices'),
    ('feature.feature_routes'),
    ('feature.feature_areas')
) AS expected(relation_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_rewrite AS rewrite
    JOIN pg_depend AS dependency ON dependency.objid = rewrite.oid
    WHERE rewrite.ev_class = 'feature.public_features'::regclass
      AND dependency.refobjid = to_regclass(expected.relation_name)
); -- expect: 0 -- phase: post-cutover

-- [INV-34C-06] public은 정확한 세 축 tuple만 포함하고 eligible 행을 하나도 빠뜨리지 않는다.
SELECT count(*)
FROM (
    (SELECT public_row.feature_id
       FROM feature.public_features AS public_row
     EXCEPT ALL
     SELECT feature_row.feature_id
       FROM feature.features AS feature_row
      WHERE feature_row.lifecycle_state = 'active'
        AND feature_row.publication_state = 'published'
        AND feature_row.quality_state = 'valid')
    UNION ALL
    (SELECT feature_row.feature_id
       FROM feature.features AS feature_row
      WHERE feature_row.lifecycle_state = 'active'
        AND feature_row.publication_state = 'published'
        AND feature_row.quality_state = 'valid'
     EXCEPT ALL
     SELECT public_row.feature_id
       FROM feature.public_features AS public_row)
) AS drift; -- expect: 0 -- phase: post-cutover

-- [INV-34C-07] request retry receipt는 exact partial unique index와 request binding을
-- 가진다. procedure test는 request/action 검증→receipt lookup→expected revision→insert 순서,
-- concurrent conflict return, request receipt UPDATE/DELETE guard를 별도로 실행한다.
SELECT coalesce(sum(violation_count), 0)
FROM (
    SELECT count(*)::bigint AS violation_count
    FROM (VALUES
        (NOT EXISTS (
            SELECT 1
            FROM pg_index AS index_meta
            JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
            WHERE index_relation.oid = to_regclass('feature.uq_feature_versions_user_request_receipt')
              AND index_meta.indrelid = 'feature.feature_versions'::regclass
              AND index_meta.indisunique
              AND ARRAY(
                    SELECT attribute.attname
                    FROM unnest(index_meta.indkey) WITH ORDINALITY AS key_column(attnum, ordinal)
                    JOIN pg_attribute AS attribute
                      ON attribute.attrelid = index_meta.indrelid
                     AND attribute.attnum = key_column.attnum
                    ORDER BY key_column.ordinal
                  ) = ARRAY['feature_id', 'request_id']::name[]
              AND pg_get_expr(index_meta.indpred, index_meta.indrelid) LIKE '%request_id IS NOT NULL%'
              AND pg_get_expr(index_meta.indpred, index_meta.indrelid) LIKE '%origin = ''user_request''%'
        )),
        (to_regprocedure('feature.reject_user_feature_version_mutation()') IS NULL),
        (NOT EXISTS (
            SELECT 1
            FROM pg_trigger AS trigger
            WHERE trigger.tgrelid = 'feature.feature_versions'::regclass
              AND trigger.tgname = 'trg_feature_versions_user_request_immutable'
              AND NOT trigger.tgisinternal
        ))
    ) AS required(is_violation)
    WHERE is_violation
    UNION ALL
    SELECT count(*)::bigint AS violation_count
    FROM feature.feature_versions AS version
    LEFT JOIN ops.feature_change_requests AS request
      ON request.request_id = version.request_id
    WHERE version.origin = 'user_request'
      AND (version.request_id IS NULL
           OR request.request_id IS NULL
           OR request.feature_id <> version.feature_id
           OR request.action <> version.change_kind
           OR request.state <> 'applied')
) AS violation_counts; -- expect: 0 -- phase: post-cutover

-- [INV-34C-08] C 동안 필요한 version/materializer bridge는 남고 runtime은 직접 DML을 받지 않는다.
SELECT count(*)
FROM (VALUES
    (to_regclass('feature.feature_versions') IS NULL),
    (to_regprocedure('feature.materialize_user_feature_change_provenance(text,text,uuid,text,text,bigint)') IS NULL),
    (to_regprocedure('feature.materialize_provider_feature_version(text)') IS NULL),
    (has_table_privilege('ktm_feature_runtime', 'feature.feature_versions', 'INSERT')),
    (has_table_privilege('ktm_feature_runtime', 'feature.feature_versions', 'UPDATE')),
    (has_table_privilege('ktm_feature_runtime', 'feature.feature_versions', 'DELETE'))
) AS violations(is_violation)
WHERE is_violation; -- expect: 0 -- phase: post-cutover

-- [INV-34C-09] user/provider materializer snapshot은 typed subtype detail, 당시의 세
-- state axis와 retained ownership fields를 보존하고 legacy state/provenance key를 담지 않는다.
-- exact axis value와 provider version=0/user immutable receipt의 snapshot 시점은 seeded procedure
-- integration이 따로 검증한다.
SELECT count(*)
FROM feature.feature_versions AS version
WHERE version.origin IN ('provider', 'user_request')
  AND (
      NOT (version.payload ?& ARRAY[
          'feature_id', 'kind', 'name', 'category', 'detail',
          'lifecycle_state', 'publication_state', 'quality_state',
          'data_origin', 'data_version'
      ])
      OR version.payload ?| ARRAY[
          'status', 'deleted_at', 'user_deleted_at', 'user_deleted_by',
          'user_change_kind', 'user_change_status', 'user_change_request_id',
          'user_change_reason'
      ]
  ); -- expect: 0 -- phase: post-cutover

-- [INV-34C-10] runtime normal reader의 view grant는 public 하나이고 removed bridge read는 없다.
SELECT count(*)
FROM (VALUES
    (NOT has_table_privilege('ktm_feature_runtime', 'feature.public_features', 'SELECT')),
    (to_regclass('feature.features_detailed') IS NOT NULL)
) AS violations(is_violation)
WHERE is_violation; -- expect: 0 -- phase: post-cutover

-- [INV-34C-11] Feature core의 view/trigger/index/constraint에는 제거한 legacy state
-- token이 없다. procedure body와 source DTO/API/UI/PinVi fixture는 integration runner의
-- Feature-scope static allowlist가 별도로 검사한다; 다른 ops/curation status는 대상이 아니다.
SELECT count(*)
FROM (
    SELECT pg_get_viewdef('feature.public_features'::regclass, true) AS definition
    UNION ALL
    SELECT pg_get_triggerdef(trigger.oid, true)
    FROM pg_trigger AS trigger
    WHERE trigger.tgrelid = 'feature.features'::regclass
      AND NOT trigger.tgisinternal
    UNION ALL
    SELECT pg_get_indexdef(index_relation.oid)
    FROM pg_index AS index_meta
    JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
    WHERE index_meta.indrelid = 'feature.features'::regclass
    UNION ALL
    SELECT pg_get_constraintdef(constraint.oid, true)
    FROM pg_constraint AS constraint
    WHERE constraint.conrelid = 'feature.features'::regclass
) AS definitions
WHERE definitions.definition ~
    E'\\m(status|deleted_at|user_deleted_at|user_deleted_by|user_change_kind|user_change_status|user_change_request_id|user_change_reason)\\M'; -- expect: 0 -- phase: post-cutover
