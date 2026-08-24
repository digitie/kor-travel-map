-- exact source ``0236`` public Alembic metadata facet.
--
-- `application-catalog.sql`은 source와 fresh ``300``이 공통으로 가져야 할
-- 구조·seed contract다. public.alembic_version의 row와 table ACL은 controlled handoff
-- 중 의도적으로 바뀌므로 그 공통 digest에서 분리한다. 이 query는 exact legacy source가
-- `0236` row와 ACL NULL 상태임을 한 줄 marker로 receipt화한다.
WITH source_table AS (
    SELECT relation.oid, relation.relowner, relation.relacl, row_type.typacl,
           row_type.oid AS row_type_oid, row_type.typarray AS array_type_oid,
           array_type.typacl AS array_typacl
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_type AS row_type ON row_type.typrelid = relation.oid
    JOIN pg_catalog.pg_type AS array_type ON array_type.oid = row_type.typarray
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'alembic_version'
      AND relation.relkind = 'r'
), source_rows AS (
    SELECT COALESCE(
        array_agg(version.version_num::text ORDER BY version.version_num),
        ARRAY[]::text[]
    ) AS values
    FROM public.alembic_version AS version
)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM source_table
        WHERE relowner = 'ktm_feature_schema_owner'::regrole
          AND relacl IS NULL
          AND typacl IS NULL
          AND row_type_oid <> 0
          AND array_type_oid <> 0
          AND array_typacl IS NULL
          AND EXISTS (
              SELECT 1
              FROM pg_catalog.pg_type AS array_type
              WHERE array_type.oid = array_type_oid
                AND array_type.typnamespace = 'public'::regnamespace
                AND array_type.typname = '_alembic_version'
                AND array_type.typowner = relowner
                AND array_type.typtype = 'b'::"char"
                AND array_type.typcategory = 'A'::"char"
                AND array_type.typisdefined
                AND array_type.typcollation = 0
                AND array_type.typrelid = 0
                AND array_type.typarray = 0
                AND array_type.typelem = row_type_oid
          )
    )
    AND (SELECT values FROM source_rows)
        = ARRAY['0236_tvn41s_compaction_drained']::text[]
    THEN 'kor-travel-map.application-source-alembic-version.v1'
    ELSE 'kor-travel-map.application-source-alembic-version.mismatch'
END AS item;
