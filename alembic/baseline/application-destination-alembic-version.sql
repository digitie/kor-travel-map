-- destination public Alembic metadata **ACL** facet.
--
-- production API/Dagster final-permit verifier는 자기 runtime LOGIN으로 raw revision을
-- read한다. 그러므로 destination에는 shared runtime role의 table-level SELECT만 남고,
-- source ``0236``에 없던 이 ACL delta는 common catalog receipt와 별도로 증명한다.
--
-- **revision 값은 여기서 보지 않는다.** 종전에는 마지막 조건이
-- ``alembic_version = ARRAY['300']``이었는데, 이 SQL의 산출물은 성공/실패 두 문자열뿐인
-- **단일 boolean**이고 기대 digest는 성공 sentinel의 해시다. 즉 조건 하나가 거짓이면
-- 무엇이 틀렸는지 구분되지 않은 채 같은 ``mismatch``가 나오고, migration을 하나
-- 더하는 순간 이 facet은 **영원히 mismatch**가 되어 옮겨갈 digest가 존재하지 않는다.
--
-- revision 동등성은 값을 여기 얼려 두는 대신 호출자가 파생 head로 대조한다 —
-- ``application-schema-fresh-300.py`` · ``-fresh-finalize.py`` · ``-final-permit.py`` ·
-- ``transition-application-schema-0236-to-300.py`` 넷 모두 ``versions != (head,)``를
-- 이미 강제하며, 그쪽이 얼린 리터럴보다 **강하다**(현재 graph에서 파생한 값과 비교한다).
-- 따라서 이 변경은 성질을 잃지 않고 얼린 값만 푼다.
WITH destination_table AS (
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
)
SELECT CASE
    WHEN EXISTS (
        SELECT 1
        FROM destination_table
        WHERE relowner = 'ktm_feature_schema_owner'::regrole
          AND relacl IS NOT NULL
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
          AND has_table_privilege(
              'ktm_feature_runtime', oid, 'SELECT'
          )
          AND NOT has_table_privilege(
              'ktm_feature_runtime', oid,
              'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
          )
          AND 8 = (
              SELECT count(*)
              FROM aclexplode(relacl)
          )
          AND NOT EXISTS (
              SELECT 1
              FROM aclexplode(relacl) AS privilege
              WHERE NOT (
                  (
                      privilege.grantee = relowner
                      AND privilege.grantor = relowner
                      AND privilege.privilege_type = ANY (
                          ARRAY[
                              'INSERT', 'SELECT', 'UPDATE', 'DELETE', 'TRUNCATE',
                              'REFERENCES', 'TRIGGER'
                          ]::text[]
                      )
                      AND NOT privilege.is_grantable
                  )
                  OR (
                      privilege.grantee = 'ktm_feature_runtime'::regrole
                      AND privilege.grantor = relowner
                      AND privilege.privilege_type = 'SELECT'
                      AND NOT privilege.is_grantable
                  )
              )
          )
    )
    THEN 'kor-travel-map.application-destination-alembic-version.v1'
    ELSE 'kor-travel-map.application-destination-alembic-version.mismatch'
END AS item;
