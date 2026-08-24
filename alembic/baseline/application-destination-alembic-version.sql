-- exact destination ``300`` public Alembic metadata facet.
--
-- production API/Dagster final-permit verifier는 자기 runtime LOGIN으로 raw ``300``을
-- read한다. 그러므로 destination에는 shared runtime role의 table-level SELECT만 남고,
-- source ``0236``에 없던 이 ACL delta는 common catalog receipt와 별도로 증명한다.
WITH destination_table AS (
    SELECT relation.oid, relation.relowner, relation.relacl
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'alembic_version'
      AND relation.relkind = 'r'
), destination_rows AS (
    SELECT COALESCE(
        array_agg(version.version_num::text ORDER BY version.version_num),
        ARRAY[]::text[]
    ) AS values
    FROM public.alembic_version AS version
)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM destination_table
        WHERE relowner = 'ktm_feature_schema_owner'::regrole
          AND relacl IS NOT NULL
          AND has_table_privilege(
              'ktm_feature_runtime', oid, 'SELECT'
          )
          AND NOT has_table_privilege(
              'ktm_feature_runtime', oid,
              'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM aclexplode(relacl) AS privilege
              WHERE NOT (
                  privilege.grantee = relowner
                  OR (
                      privilege.grantee = 'ktm_feature_runtime'::regrole
                      AND privilege.privilege_type = 'SELECT'
                      AND NOT privilege.is_grantable
                  )
              )
          )
    )
    AND (SELECT values FROM destination_rows) = ARRAY['300']::text[]
    THEN 'kor-travel-map.application-destination-alembic-version.v1'
    ELSE 'kor-travel-map.application-destination-alembic-version.mismatch'
END AS item;
